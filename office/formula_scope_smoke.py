"""Verify LET/LAMBDA binding scopes and dynamic-formula writes."""
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from openpyxl import Workbook
import grid_values
import officecli_backend
import session

matches = grid_values.dynamic_formula_matches
assert matches('LET(x,1,y,x+2,y*2)', '_xlfn.LET(_xlpm.x,1,_xlpm.y,_xlpm.x+2,_xlpm.y*2)')
assert matches('LET(x,1,LET(y,x+2,y+x))', '_xlfn.LET(_xlpm.x,1,_xlfn.LET(_xlpm.y,_xlpm.x+2,_xlpm.y+_xlpm.x))')
assert matches('LET(f,LAMBDA(x,x+1),f(2))', '_xlfn.LET(_xlpm.f,_xlfn.LAMBDA(_xlpm.x,_xlpm.x+1),_xlpm.f(2))')
assert not matches('LET(x,x,x)', '_xlfn.LET(_xlpm.x,_xlpm.x,_xlpm.x)')
assert not matches('LET(x,1,x)+x', '_xlfn.LET(_xlpm.x,1,_xlpm.x)+_xlpm.x')
assert not matches('LET(x,1,LET(y,x,y))+y', '_xlfn.LET(_xlpm.x,1,_xlfn.LET(_xlpm.y,_xlpm.x,_xlpm.y))+_xlpm.y')
assert not matches('LET(SEQUENCE,1,SEQUENCE(3))', '_xlfn.LET(_xlpm.SEQUENCE,1,_xlfn.SEQUENCE(3))')
assert not matches('LET(x,1,x+"x")', '_xlfn.LET(_xlpm.x,1,_xlpm.x+"_xlpm.x")')
assert not matches('LET(x,1,x)', '_xlfn._xlws.LET(_xlpm.x,1,_xlpm.x)')
assert not matches('LET(x,1,x+A1)', '_xlfn.LET(_xlpm.x,1,_xlpm.x+_xlpm.A1)')
X = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.xlsx'; wb = Workbook(); wb.active['A1'] = 5; wb.active['B1'] = '=A1*2'; wb.save(source)
    draft = root / 'draft'; session.start(draft, source=source)
    formulas = ['=LET(x,1,y,x+2,y*2)', '=LET(x,1,LET(y,x+2,y+x))', '=LAMBDA(x,y,x+y)(1,2)', '=MAP(A1:A3,LAMBDA(x,x+1))', '=LET(f,LAMBDA(x,x+1),f(2))']
    changes = [{'cell': f'{chr(67+i)}1', 'value': value} for i, value in enumerate(formulas)]
    result = session.edit_grid(draft, 0, 'Sheet', 'C1:G1', changes)
    assert result['dynamic_formula_cells'] == [f'{chr(67+i)}1' for i in range(len(formulas))]
    with zipfile.ZipFile(result['file']) as archive:
        sheet = etree.fromstring(archive.read('xl/worksheets/sheet1.xml')); cells = {cell.get('r'):cell for cell in sheet.iter(X+'c')}
        assert grid_values.metadata_part(archive) == 'xl/office-use-metadata.xml'
        assert all(cells[item['cell']].get('cm') == '1' and cells[item['cell']].find(X+'v') is None for item in changes)
        assert cells['B1'].find(X+'f').text == 'A1*2'
    audit = officecli_backend.audit(result['file']); assert audit['validation']['exit_code'] == 0 and audit['validation']['result']['success'], audit
    refused = root / 'refused'; session.start(refused, source=source)
    try: session.edit_grid(refused, 0, 'Sheet', 'C1', [{'cell':'C1','value':'=LET(x,x,x)'}])
    except ValueError as exc: assert 'differs from requested' in str(exc)
    else: raise AssertionError('Out-of-scope variable rewrite accepted')
    assert session.info(refused)['latest_revision'] == 0
print('Dynamic formula scope smoke passed')
