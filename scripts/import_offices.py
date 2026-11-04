"""Import the supplied HTML-as-XLS master, retaining only required public fields."""
import json, sys, hashlib
from html.parser import HTMLParser
from pathlib import Path
class Table(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag=='tr': self.row=[]
        if tag in ('td','th'): self.cell=''
    def handle_data(self, text):
        if self.cell is not None: self.cell+=text
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None: self.row.append(self.cell.strip()); self.cell=None
        if tag=='tr' and self.row: self.rows.append(self.row)
def main(source, target):
    raw=Path(source).read_bytes(); t=Table(); t.feed(raw.decode('utf-8-sig'))
    fields=['office_id','office_name','office_type_code','pincode','latitude','longitude','division_name']
    records=[]; seen=set(); invalid=[]
    for values in t.rows[1:]:
        row=dict(zip(t.rows[0],values)); record={k:row[k] for k in fields}
        if record['office_id'] in seen: raise ValueError('Duplicate office ID')
        seen.add(record['office_id'])
        try:
            lat=float(record['latitude']); lon=float(record['longitude'])
            valid=6<=lat<=38 and 68<=lon<=98
        except (ValueError,TypeError): valid=False
        record['coordinates_valid']=valid
        if not valid: invalid.append(record['office_id'])
        records.append(record)
    Path(target).write_text(json.dumps(records,ensure_ascii=False,indent=2))
    report={'records':len(records),'invalid_coordinate_ids':invalid,'source_sha256':hashlib.sha256(raw).hexdigest()}
    Path(target).with_name('office_import_report.json').write_text(json.dumps(report,indent=2)); print(report)
if __name__=='__main__': main(*sys.argv[1:])
