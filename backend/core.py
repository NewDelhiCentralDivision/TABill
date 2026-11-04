import io, json, math, os, re, sqlite3
from copy import copy
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal
import httpx, openpyxl
from pydantic import BaseModel, Field, ConfigDict
from rapidfuzz.fuzz import WRatio
from unidecode import unidecode
ROOT=Path(__file__).resolve().parents[1]
HEADERS=['From Date','From Time','From Place','To Date','To Time','To Place','Mode','Distance (Km)','Fare Paid','Remarks']
OFFICES=json.loads((ROOT/'data/offices.json').read_text())
BY_ID={o['office_id']:o for o in OFFICES}
ALIASES=json.loads((ROOT/'data/aliases.json').read_text())
if any(key not in BY_ID for key in ALIASES): raise ValueError('Alias references an unknown office ID')
class Leg(BaseModel):
    model_config=ConfigDict(extra='forbid')
    from_name: str=Field(max_length=200)
    to_name: str=Field(max_length=200)
    from_date: date|None=None
    to_date: date|None=None
    date_evidence: Literal['explicit','unambiguous_relative','missing']='missing'
    evidence: str=Field(default='',max_length=1000)
    from_time: str|None=None
    to_time: str|None=None
    from_id: str|None=None
    to_id: str|None=None
    remarks: str=Field(default='',max_length=1000)
class Extraction(BaseModel):
    transcript: str=Field(max_length=20000)
    legs: list[Leg]=Field(max_length=100)
class Claim(BaseModel):
    legs: list[Leg]=Field(min_length=1,max_length=100)
    rate: Decimal=Field(default=Decimal('11'),gt=0,le=10000,max_digits=8,decimal_places=2)
def money(v): return Decimal(str(v)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
def normalize(s):
    s=unidecode(s).lower()
    for a,b in [('head office','ho'),('head post office','ho'),('sub post office','so'),('post office',''),('h.o.','ho'),('s.o.','so')]: s=s.replace(a,b)
    return re.sub(r'[^a-z0-9]','',s)
def candidates(name):
    n=normalize(name)
    if not n: return []
    result=[]
    for o in OFFICES:
        official=normalize(o['office_name']); acronym=''.join(w[0] for w in re.findall(r'[a-z]+',unidecode(o['office_name']).lower()))
        score=100 if n==official or n in [normalize(alias) for alias in ALIASES.get(o['office_id'],[])] else (96 if n==acronym and len(n)>=3 else WRatio(n,official))
        # PIN and division are helpful only alongside an office name.
        if o['pincode'] in name and official in n: score=100
        result.append({**o,'score':round(score,1)})
    return sorted(result,key=lambda o:o['score'],reverse=True)[:5]
def resolve(name,chosen):
    if chosen:
        return BY_ID.get(chosen),[]
    options=candidates(name)
    if options and options[0]['score']>=96 and (len(options)==1 or options[0]['score']-options[1]['score']>=8): return BY_ID[options[0]['office_id']],options
    return None,options
class Distance:
    def __init__(self):
        self.path=os.getenv('DISTANCE_CACHE','/tmp/ta-distance.sqlite3')
        with sqlite3.connect(self.path) as c: c.execute('CREATE TABLE IF NOT EXISTS distances (key TEXT PRIMARY KEY, km TEXT)')
    async def km(self,a,b):
        if not a['coordinates_valid'] or not b['coordinates_valid']: raise ValueError('Office coordinates need correction by the administrator.')
        method=os.getenv('DISTANCE_METHOD','road')
        if method=='haversine' and os.getenv('ALLOW_HAVERSINE')!='true': raise ValueError('Straight-line distance has not been approved by the administrator.')
        if a['office_id']==b['office_id']: raise ValueError('Departure and destination are the same office. Review this journey.')
        version=os.getenv('ROUTING_DATA_VERSION','unconfigured')
        key=json.dumps([a['office_id'],b['office_id'],method,version,a['latitude'],a['longitude'],b['latitude'],b['longitude'],os.getenv('ROUTING_URL','')])
        with sqlite3.connect(self.path) as c:
            row=c.execute('SELECT km FROM distances WHERE key=?',(key,)).fetchone()
        if row: return Decimal(row[0]),method
        if a['office_id']==b['office_id']: raise ValueError('Departure and destination are the same office. Review this journey.')
        if method=='haversine':
            if os.getenv('ALLOW_HAVERSINE')!='true': raise ValueError('Straight-line distance has not been approved by the administrator.')
            p1,p2=map(math.radians,[float(a['latitude']),float(b['latitude'])]); dp=p2-p1; dl=math.radians(float(b['longitude'])-float(a['longitude']))
            v=6371*2*math.asin(min(1,math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2)))
        elif method=='road':
            base=os.getenv('ROUTING_URL','')
            if not base or version=='unconfigured': raise ValueError('Road distances are unavailable. Ask the administrator to configure the approved routing service.')
            coords=f"{a['longitude']},{a['latitude']};{b['longitude']},{b['latitude']}"
            try:
                async with httpx.AsyncClient(timeout=12) as client:
                    r=await client.get(base.rstrip('/')+'/route/v1/driving/'+coords,params={'overview':'false'}); r.raise_for_status(); data=r.json()
                if data.get('code')!='Ok' or not data.get('routes'): raise ValueError('No road route found between these offices.')
                v=float(data['routes'][0]['distance'])/1000
                if not math.isfinite(v) or v<=0: raise ValueError('Routing service returned an invalid distance.')
            except (httpx.HTTPError,KeyError,TypeError): raise ValueError('Road routing is unavailable. Please retry; no distance has been estimated.')
        else: raise ValueError('The administrator must select a supported distance method.')
        result=money(v)
        with sqlite3.connect(self.path) as c: c.execute('INSERT OR REPLACE INTO distances VALUES (?,?)',(key,str(result)))
        return result,method

def clock(value):
    if not value or not re.fullmatch(r'\d{2}:\d{2}',value): raise ValueError('Use a valid time in HH:MM format.')
    return time.fromisoformat(value)
async def review(claim,distances):
    errors=[]; rows=[]; cursors={}; previous=None; total=Decimal(0); kms=Decimal(0)
    for i,leg in enumerate(claim.legs):
        row=leg.model_dump(mode='json'); row.update(errors=[],default_times=False,from_options=[],to_options=[])
        def fail(message): row['errors'].append(message)
        if not leg.from_date or leg.date_evidence=='missing': fail('Journey date not mentioned. Please record the date of travel to generate your TA Bill.')
        end=leg.to_date or leg.from_date
        if leg.from_date and end:
            if end<leg.from_date: fail('Arrival date is before departure date.')
            try:
                day=leg.from_date; cursor=cursors.get(day,datetime.combine(day,time(10)))
                departure=datetime.combine(day,clock(leg.from_time)) if leg.from_time else cursor
                arrival=datetime.combine(end,clock(leg.to_time)) if leg.to_time else departure+timedelta(minutes=30)
                if not leg.from_time and leg.to_time:
                    departure=max(previous or datetime.combine(day,time.min),arrival-timedelta(minutes=30))
                if departure.date()!=day or arrival.date()!=end: fail('Default times cross midnight. Please confirm the dates and times.')
                if arrival<=departure or (previous and departure<previous): fail('Travel times conflict with the journey sequence. Please correct them.')
                row.update(from_time=departure.strftime('%H:%M'),to_time=arrival.strftime('%H:%M'),to_date=end.isoformat(),default_times=not(leg.from_time and leg.to_time))
                cursors[day]=arrival+timedelta(minutes=30); previous=arrival
            except ValueError: fail('Invalid travel time. Use HH:MM and check the journey sequence.')
        a,opts=resolve(leg.from_name,leg.from_id); row['from_options']=opts
        b,opts=resolve(leg.to_name,leg.to_id); row['to_options']=opts
        for label,o in [('from',a),('to',b)]:
            if o: row[label+'_id']=o['office_id'];row[label+'_name']=o['office_name']
            else: fail('Please select the correct '+('departure' if label=='from' else 'destination')+' office.')
        if a and b:
            try:
                km,method=await distances.km(a,b); fare=money(km*claim.rate)
                row.update(distance=str(km),fare=str(fare),method=method);kms+=km;total+=fare
            except ValueError as e: fail(str(e))
        errors.extend(row['errors']); rows.append(row)
    return {'legs':rows,'errors':list(dict.fromkeys(errors)),'total_distance':str(kms),'total_fare':str(total),'rate':str(claim.rate),'valid':not errors}

def workbook(result):
    if not result['valid']: raise ValueError('Please resolve the highlighted details before downloading.')
    w=openpyxl.load_workbook(ROOT/'data/Journey_Details_Template.xlsx');s=w['JourneyDetails']
    if [c.value for c in s[1]]!=HEADERS: raise ValueError('The output template has changed. Contact the administrator.')
    styles=[copy(c._style) for c in s[2]];s.delete_rows(2,s.max_row)
    for i,r in enumerate(result['legs'],2):
        values=[date.fromisoformat(r['from_date']).strftime('%d/%m/%Y'),r['from_time'],r['from_name'],date.fromisoformat(r['to_date']).strftime('%d/%m/%Y'),r['to_time'],r['to_name'],'Road',float(r['distance']),float(r['fare']),r['remarks'] or None]
        for j,value in enumerate(values,1):
            c=s.cell(i,j,value);c._style=copy(styles[j-1])
            if isinstance(value,str): c.data_type='s' # prevent spoken spreadsheet formulas
    out=io.BytesIO();w.save(out);out.seek(0);return out
