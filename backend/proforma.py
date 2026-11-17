"""Official template mapping and export reconciliation, using reviewed claim data."""
import io
from copy import copy
from datetime import date, time
from decimal import Decimal
import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.workbook.properties import CalcProperties
from .core import ROOT, DIVISIONS, money

def claim_errors(claim):
    errors=[]
    if claim.division not in DIVISIONS:
        errors.append('Select a Postal Division from the existing division master.')
    for key,label in [('employee_name','Employee name'),('designation','Designation'),('headquarters','Headquarters')]:
        if not getattr(claim,key).strip(): errors.append(label+' is required.')
    return errors

def put(sheet, address, value):
    cell=sheet[address]
    cell.value=value
    if isinstance(value,str): cell.data_type='s'
    cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)

def add_summary(w,result):
    s=w.create_sheet('ClaimSummary');c=result['claim'];summary=result['summary']
    records=[('TA claim summary',None),('Employee',c['employee_name']),('Designation',c['designation']),
             ('Postal Division',c['division']),('Headquarters',c['headquarters']),('Basic pay',c['basic_pay']),
             ('Pay level',c['pay_level']),('Purpose',c['purpose']),('Conveyance',c['conveyance']),
             ('Mileage',summary['mileage']),('Hotel accommodation',c['hotel']),('Daily allowance',c['daily_allowance']),
             ('Personal effects',c['personal_effects']),('Total allowances',summary['gross']),
             ('Deductions',summary['deductions']),('Advance',summary['advance']),('Net TA payable',summary['net'])]
    for i,(label,value) in enumerate(records,1):
        put(s,f'A{i}',label)
        put(s,f'B{i}',float(value) if value is not None and i in (6,10,11,12,13,14,15,16,17) else value)
        if i>=10:s[f'B{i}'].number_format='#,##0.00'
        s.row_dimensions[i].height=30
    s['A1'].font=Font(bold=True,size=15);s.column_dimensions['A'].width=27;s.column_dimensions['B'].width=65
    s.print_area='A1:B17';s.page_setup.orientation='portrait';s.sheet_properties.pageSetUpPr.fitToPage=True
    s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=1

def official_workbook(result):
    if not result['valid']:raise ValueError('Resolve claim validation errors first.')
    w=openpyxl.load_workbook(ROOT/'data/Official_TA_Proforma.xlsx')
    s=w['Sheet1']
    for other in list(w):
        if other!=s:w.remove(other)
    count=len(result['legs']);extra=max(0,count-6)
    # Insert before the allowance section, preserving and extending original merges.
    if extra:
        merges=[copy(r) for r in s.merged_cells.ranges]
        for r in list(s.merged_cells.ranges):s.unmerge_cells(str(r))
        heights={r:copy(d) for r,d in s.row_dimensions.items() if r>=14}
        s.insert_rows(14,extra)
        for r,d in heights.items():s.row_dimensions[r+extra]=d;s.row_dimensions[r+extra].index=r+extra
        for r in merges:
            if r.min_row>=14:r.shift(row_shift=extra)
            elif r.max_row>=14:r.max_row+=extra
            s.merge_cells(str(r))
        for row in range(14,14+extra):
            for col in range(5,26):s.cell(row,col)._style=copy(s.cell(13,col)._style)
    c=result['claim'];hotel=14+extra;daily=15+extra;effects=16+extra;deduction=17+extra;balance=18+extra;advance=19+extra;net=20+extra
    # Clear example-only purpose and placeholder marks in the blank source.
    for row in range(8,net+1):
        put(s,f'Y{row}',None)
    put(s,'B4','Travelling Allowance Bill — '+c['employee_name']+' — '+c['division'])
    put(s,'B8',c['employee_name']+'\n'+c['designation'])
    put(s,'C8',c['headquarters'])
    pay=[]
    if c['basic_pay'] is not None:pay.append('Basic pay: '+c['basic_pay'])
    if c['pay_level']:pay.append('Pay level: '+c['pay_level'])
    put(s,'D8','\n'.join(pay) or None);put(s,'J8',c['purpose'] or None)
    notes_sheet=None
    for row,r in enumerate(result['legs'],8):
        values={'E':date.fromisoformat(r['from_date']),'F':time.fromisoformat(r['from_time']),
                'G':r['from_name'],'H':time.fromisoformat(r['to_time']),'I':r['to_name'],
                'K':'By Road','L':c['conveyance'] or None,'N':float(r['distance']),'O':float(result['rate']),
                'P':float(r['fare'])}
        # Actual fare is not the calculated mileage entitlement; leave M blank.
        notes=[r['remarks']] if r['remarks'] else []
        if r['to_date']!=r['from_date']:notes.append('Arrival date: '+date.fromisoformat(r['to_date']).strftime('%d/%m/%Y'))
        if r['default_times']:notes.append('Times unconfirmed')
        full_note='\n'.join(notes)
        if len(full_note)>45:
            if notes_sheet is None:
                notes_sheet=w.create_sheet('JourneyNotes')
                for col,label in [('A','Journey'),('B','Remarks / ticket information')]:put(notes_sheet,col+'1',label)
                notes_sheet.column_dimensions['A'].width=12;notes_sheet.column_dimensions['B'].width=100
                notes_sheet.page_setup.orientation='landscape';notes_sheet.sheet_properties.pageSetUpPr.fitToPage=True
                notes_sheet.page_setup.fitToWidth=1;notes_sheet.page_setup.fitToHeight=0;notes_sheet.print_title_rows='1:1'
            note_row=notes_sheet.max_row+1
            put(notes_sheet,f'A{note_row}',row-7);put(notes_sheet,f'B{note_row}',full_note)
            notes_sheet.row_dimensions[note_row].height=30+15*(len(full_note)//80+full_note.count('\n'))
            values['Y']=f'See note {row-7}'
        else:values['Y']=full_note or None
        for col,val in values.items():put(s,f'{col}{row}',val)
        s[f'E{row}'].number_format='dd/mm/yy'
        s[f'F{row}'].number_format=s[f'H{row}'].number_format='hh:mm'
        s[f'X{row}']=f'=SUM(P{row},T{row},W{row})'
        s.row_dimensions[row].height=max(48,min(160,24+12*max(len(r['from_name'])//12,len(r['to_name'])//12,len(values['Y'] or '')//12)))
    for address,key in [(f'P{hotel}','hotel'),(f'W{daily}','daily_allowance'),(f'T{effects}','personal_effects'),(f'X{advance}','advance')]:
        put(s,address,float(c[key]) if c[key] is not None else None)
    put(s,f'Q{effects}','Personal effects')
    put(s,f'U{deduction}','Deductions')
    for area in (f'N{hotel}:O{hotel}',f'N{daily}:P{daily}',f'Q{effects}:S{effects}',f'U{deduction}:W{deduction}'):
        s.merge_cells(area)
    put(s,f'N{hotel}','HOTEL ACCOMMODATION');put(s,f'N{daily}','DAILY ALLOWANCE')
    for row in (hotel,daily,effects,deduction):s.row_dimensions[row].height=32
    s.row_dimensions[hotel].height=48
    put(s,f'X{deduction}',-float(c['deductions']) if c['deductions'] is not None else None)
    for row,col in ((hotel,'P'),(daily,'W'),(effects,'T')):
        s[f'X{row}']=f'=IF({col}{row}="","",{col}{row})'
    s[f'X{balance}']=f'=SUM(X8:X{deduction})'
    s[f'X{net}']=f'=X{balance}-X{advance}'
    for row in range(8,net+1):
        for col in ('M','N','O','P','R','S','T','V','W','X'):s[f'{col}{row}'].number_format='#,##0.00'
    s.row_dimensions[4].height=36
    s.print_area=f'B4:Y{net}';s.print_title_rows='4:7'
    s.page_setup.orientation='landscape';s.page_setup.paperSize=s.PAPERSIZE_A3
    s.sheet_properties.pageSetUpPr.fitToPage=True;s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=0
    w.calculation=CalcProperties(calcId=0,fullCalcOnLoad=True)
    out=io.BytesIO();w.save(out);out.seek(0);return out

def reconcile(existing,official,result):
    """Independently read serialized amounts from both formats before any download."""
    old=openpyxl.load_workbook(existing);new=openpyxl.load_workbook(official);s=new['Sheet1']
    old_mileage=sum((money(row[8].value) for row in list(old['JourneyDetails'])[1:]),Decimal(0))
    official_mileage=sum((money(s[f'P{r}'].value) for r in range(8,8+len(result['legs']))),Decimal(0))
    extra=max(0,len(result['legs'])-6)
    def amount(addr):return money(s[addr].value or 0)
    official_net=official_mileage+amount(f'P{14+extra}')+amount(f'W{15+extra}')+amount(f'T{16+extra}')+amount(f'X{17+extra}')-amount(f'X{19+extra}')
    old_net=money(old['ClaimSummary']['B17'].value)
    if old_mileage!=official_mileage or old_net!=official_net or old_net!=money(result['summary']['net']):
        raise ValueError('The output totals differ. Download blocked; please review the claim.')
    if old['ClaimSummary']['B4'].value!=result['claim']['division'] or result['claim']['division'] not in s['B4'].value:
        raise ValueError('The division differs between output formats. Download blocked.')
    existing.seek(0);official.seek(0)
