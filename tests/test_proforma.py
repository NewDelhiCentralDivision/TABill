import asyncio,io,zipfile
from datetime import date,timedelta
from decimal import Decimal
import openpyxl,pytest
from backend.core import Claim,DIVISIONS,review,workbook
from backend.proforma import official_workbook,reconcile
from test_core import leg,Fixed,A,B
from test_api import submit,client,audio_mock

def complete(**kw):
    return Claim(legs=kw.pop('legs',[leg(),leg(B,A)]),employee_name='Test Official',designation='Postal Assistant',headquarters='Delhi',division=DIVISIONS[0],**kw)

@pytest.mark.asyncio
@pytest.mark.parametrize('n',[1,6,7,25,100])
async def test_mapping_overflow_and_parity(n):
    legs=[leg(A if i%2==0 else B,B if i%2==0 else A,day=(date(2026,1,1)+timedelta(days=i)).isoformat(),from_time='09:00',to_time='10:00',remarks='Ticket: =123') for i in range(n)]
    r=await review(complete(legs=legs,hotel='200',daily_allowance='50',personal_effects='100',deductions='10',advance='30',basic_pay='40400',pay_level='4',purpose='Inspection'),Fixed())
    original=workbook(r);official=official_workbook(r);reconcile(original,official,r)
    w=openpyxl.load_workbook(official);s=w['Sheet1'];extra=max(0,n-6)
    assert w.sheetnames==['Sheet1']
    assert s['B8'].value=='Test Official\nPostal Assistant'
    assert s['J8'].value=='Inspection';assert s['D8'].value=='Basic pay: 40400\nPay level: 4'
    assert s[f'G{7+n}'].value==legs[-1].from_name
    assert s[f'P{7+n}'].value==135.85;assert s['M8'].value is None
    assert s[f'X{20+extra}'].value==f'=X{18+extra}-X{19+extra}'
    assert f'B8:B{18+extra}' in str(s.merged_cells)
    assert s.page_setup.orientation=='landscape' and s.page_setup.fitToWidth==1
    assert s.print_area.endswith(f'$Y${20+extra}')
    assert s['Y8'].data_type=='s'
    # Compare untouched official headings, column widths and top-header merges.
    source=openpyxl.load_workbook('data/Official_TA_Proforma.xlsx')['Sheet1']
    for row in range(5,8):
        for col in range(2,26):
            assert s.cell(row,col).value==source.cell(row,col).value
            assert s.cell(row,col)._style==source.cell(row,col)._style
    assert {k:dict(v) for k,v in s.column_dimensions.items()}=={k:dict(v) for k,v in source.column_dimensions.items()}

@pytest.mark.asyncio
async def test_optional_fields_no_example_leak_and_mismatch():
    r=await review(complete(),Fixed());old=workbook(r);new=official_workbook(r)
    s=openpyxl.load_workbook(new)['Sheet1']
    for cell in ('D8','J8','L8','M8','P14','W15','T16','X17','X19'):assert s[cell].value is None
    assert 'Pankaj' not in str(list(s.values));assert 'COURT INQUIRY' not in str(list(s.values))
    w=openpyxl.load_workbook(new);w['Sheet1']['P8']=999;bad=io.BytesIO();w.save(bad);bad.seek(0)
    with pytest.raises(ValueError,match='totals differ'):reconcile(old,bad,r)

def test_all_downloads_and_validation(client,audio_mock):
    submit(client);data=complete().model_dump(mode='json')
    assert client.post('/api/generate',json=data).json()['ready']
    for kind in ('existing','official','both'):
        response=client.post('/api/export?format='+kind,json=data);assert response.status_code==200
        assert 'Test_Official' in response.headers['content-disposition']
        if kind=='both':
            z=zipfile.ZipFile(io.BytesIO(response.content));assert len(z.namelist())==2
            assert any('Official' in x for x in z.namelist())
    for division in ('','Invented Division'):
        assert client.post('/api/export',json={**data,'division':division}).status_code==422
    for field,value in [('advance','-1'),('hotel','NaN'),('deductions','0.001')]:
        assert client.post('/api/export',json={**data,field:value}).status_code==422

@pytest.mark.asyncio
async def test_long_notes_overnight_and_literal_text():
    note='=HYPERLINK("unsafe") '+('ticket reference '*50)
    c=complete(legs=[leg(from_time='23:30',to_time='01:00',to_date='2026-11-04',remarks=note)])
    r=await review(c,Fixed());assert r['valid']
    w=openpyxl.load_workbook(official_workbook(r));s=w['Sheet1']
    assert s['Y8'].value=='See note 1'
    assert note in w['JourneyNotes']['B2'].value
    assert 'Arrival date: 04/11/2026' in w['JourneyNotes']['B2'].value
    assert w['JourneyNotes']['B2'].data_type=='s'
