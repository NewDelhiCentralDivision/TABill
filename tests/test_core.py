import io
from datetime import date
from decimal import Decimal
import httpx,openpyxl,pytest
from backend.core import *
A=next(o for o in OFFICES if 'Indraprastha' in o['office_name'])
B=next(o for o in OFFICES if 'Sansad Marg' in o['office_name'])
C=next(o for o in OFFICES if 'New Delhi GPO' in o['office_name'])
class Fixed:
    async def km(self,a,b): return Decimal('12.35'),'road'
def leg(a=A,b=B,day='2026-11-03',**kw):
    return Leg(from_name=a['office_name'],to_name=b['office_name'],from_id=a['office_id'],to_id=b['office_id'],from_date=day,date_evidence='explicit' if day else 'missing',**kw)
async def run(legs,rate='11'):return await review(Claim(legs=legs,rate=rate),Fixed())
@pytest.mark.asyncio
async def test_simple():
    r=await run([leg()]);assert r['valid'];assert (r['legs'][0]['from_time'],r['legs'][0]['to_time'])==('10:00','10:30');assert r['total_fare']=='135.85'
@pytest.mark.asyncio
async def test_multistop_return():
    r=await run([leg(),leg(B,C),leg(C,A)]);assert r['valid'];assert [x['from_time'] for x in r['legs']]==['10:00','11:00','12:00'];assert len(r['legs'])==3
@pytest.mark.asyncio
async def test_missing_date_blocks():
    r=await run([leg(day=None)]);assert not r['valid'];assert 'Journey date not mentioned' in r['errors'][0]
    with pytest.raises(ValueError):workbook(r)
@pytest.mark.asyncio
async def test_multiple_dates_reset():
    r=await run([leg(),leg(B,A,day='2026-11-04')]);assert r['valid'];assert [x['from_time'] for x in r['legs']]==['10:00','10:00']
@pytest.mark.asyncio
async def test_rate_rounding_and_totals():
    r=await run([leg(),leg(B,A)],'12');assert r['total_fare']=='296.40';assert sum(Decimal(x['fare']) for x in r['legs'])==Decimal(r['total_fare'])
@pytest.mark.asyncio
async def test_explicit_partial_times():
    r=await run([leg(from_time='09:15'),leg(B,A,to_time='11:00')]);assert r['valid'];assert r['legs'][0]['from_time']=='09:15';assert r['legs'][1]['to_time']=='11:00'
@pytest.mark.asyncio
async def test_conflicting_times():
    r=await run([leg(from_time='12:00',to_time='11:00')]);assert not r['valid']
@pytest.mark.asyncio
async def test_midnight_and_overnight():
    r=await run([leg(from_time='23:50')]);assert not r['valid']
    r=await run([leg(from_time='23:50',to_time='00:30',to_date='2026-11-04')]);assert r['valid']
@pytest.mark.parametrize('rate',['0','-1','NaN','Infinity','11.111'])
def test_invalid_rate(rate):
    with pytest.raises(Exception):Claim(legs=[leg()],rate=rate)
def test_office_master():
    assert len(OFFICES)==len(BY_ID)==696;assert all(x['coordinates_valid'] for x in OFFICES)
def test_exact_and_abbreviated():
    assert resolve('INDRAPRASTHA HEAD OFFICE',None)[0]['office_id']==A['office_id']
def test_ambiguous_and_unknown():
    assert resolve('Delhi',None)[0] is None;assert resolve('nonexistent office zzzz',None)[0] is None;assert resolve('x','invalid') [0] is None
@pytest.mark.asyncio
async def test_template_compatibility():
    r=await run([leg(remarks='=HYPERLINK("bad")'),leg(B,A)])
    s=openpyxl.load_workbook(workbook(r))['JourneyDetails']
    assert s.max_column==10 and s.max_row==3;assert [c.value for c in s[1]]==HEADERS
    assert s['A2'].value=='03/11/2026' and s['A2'].number_format=='@';assert s['B2'].value=='10:00';assert s['G2'].value=='Road';assert s['H2'].data_type=='n';assert s['J2'].data_type=='s';assert s['J2'].value.startswith('=');assert s['J3'].value is None
@pytest.mark.asyncio
async def test_routing_failure_no_fallback(monkeypatch,tmp_path):
    monkeypatch.setenv('DISTANCE_CACHE',str(tmp_path/'d.db'));monkeypatch.delenv('ROUTING_URL',raising=False)
    with pytest.raises(ValueError,match='unavailable'): await Distance().km(A,B)
@pytest.mark.asyncio
async def test_haversine_requires_approval(monkeypatch,tmp_path):
    monkeypatch.setenv('DISTANCE_CACHE',str(tmp_path/'d.db'));monkeypatch.setenv('DISTANCE_METHOD','haversine');monkeypatch.delenv('ALLOW_HAVERSINE',raising=False)
    with pytest.raises(ValueError,match='approved'):await Distance().km(A,B)
    monkeypatch.setenv('ALLOW_HAVERSINE','true');km,method=await Distance().km(A,B);assert km>0 and method=='haversine'
@pytest.mark.asyncio
async def test_road_cache_direction(monkeypatch,tmp_path):
    monkeypatch.setenv('DISTANCE_CACHE',str(tmp_path/'d.db'));monkeypatch.setenv('ROUTING_URL','https://routing.invalid');monkeypatch.setenv('ROUTING_DATA_VERSION','v1');calls=[]
    async def get(self,url,**kw):calls.append(url);return httpx.Response(200,json={'code':'Ok','routes':[{'distance':12345}]},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx.AsyncClient,'get',get);d=Distance()
    assert (await d.km(A,B))[0]==Decimal('12.35');await d.km(A,B);await d.km(B,A);assert len(calls)==2
@pytest.mark.asyncio
async def test_hindi_hinglish_structured_fixture():
    # Mocked Gemini output: multilingual speech produces official Latin names for matching.
    for transcript in ['तीन नवंबर 2026 को इंद्रप्रस्थ से संसद मार्ग गया।','3 November 2026 ko Indraprastha HO se Sansad Marg HO gaya.']:
        e=Extraction(transcript=transcript,legs=[leg()]);r=await run(e.legs);assert r['valid'];assert len(r['legs'])==1
@pytest.mark.parametrize('spoken,office',[('IPHO',A),('इंद्रप्रस्थ प्रधान डाकघर',A),('संसद मार्ग प्रधान डाकघर',B)])
def test_validated_hindi_aliases(spoken,office):
    assert resolve(spoken,None)[0]['office_id']==office['office_id']
@pytest.mark.asyncio
async def test_impossible_date_and_chronology():
    with pytest.raises(ValueError):leg(day='2026-02-30')
    r=await run([leg(day='2026-11-04'),leg(B,A,day='2026-11-03')]);assert not r['valid']
@pytest.mark.asyncio
async def test_cached_straight_line_still_requires_approval(monkeypatch,tmp_path):
    monkeypatch.setenv('DISTANCE_CACHE',str(tmp_path/'d.db'));monkeypatch.setenv('DISTANCE_METHOD','haversine');monkeypatch.setenv('ALLOW_HAVERSINE','true');d=Distance();await d.km(A,B)
    monkeypatch.setenv('ALLOW_HAVERSINE','false')
    with pytest.raises(ValueError,match='approved'):await d.km(A,B)
@pytest.mark.asyncio
async def test_early_spoken_arrival():
    r=await run([leg(to_time='09:00')]);assert r['valid'];assert r['legs'][0]['from_time']=='08:30'
