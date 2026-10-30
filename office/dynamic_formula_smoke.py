"""Exercise dynamic formula metadata and protected spreadsheet edits."""
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from openpyxl import Workbook, load_workbook
import grid_values
import officecli_backend
import session

X = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); raw = root / 'raw.xlsx'; source = root / 'source.xlsx'; book = Workbook()
    book.active['A1'] = 7; book.active['B1'] = '=A1*2'; book.active['G1'] = 9; book.save(raw)
    with zipfile.ZipFile(raw) as before, zipfile.ZipFile(source, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                tree = etree.fromstring(data)
                for cell in tree.iter(X + 'c'):
                    if cell.get('r') == 'B1': cell.find(X + 'v').text = '14'
                data = etree.tostring(tree)
            after.writestr(entry, data)
    draft = root / 'draft'; session.start(draft, source=source)
    result = session.edit_grid(draft, 0, 'Sheet', 'D1:E1', [{'cell':'D1', 'value':'=SEQUENCE(3)'}, {'cell':'E1', 'value':'=LET(x,1,x+1)'}])
    assert result['revision'] == 1 and result['recalculation_requested'] and result['dynamic_formula_cells'] == ['D1', 'E1']
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(result['file']) as after:
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name not in ('[Content_Types].xml', 'xl/_rels/workbook.xml.rels', 'xl/worksheets/sheet1.xml', 'xl/styles.xml'))
        assert grid_values.metadata_part(after) == 'xl/office-use-metadata.xml'
        sheet = etree.fromstring(after.read('xl/worksheets/sheet1.xml'))
        cells = {cell.get('r'):cell for cell in sheet.iter(X+'c')}
        assert cells['B1'].find(X+'v').text == '14' and cells['D1'].get('cm') == '1' and cells['E1'].get('cm') == '1'
        assert cells['D1'].find(X+'f').text == '_xlfn.SEQUENCE(3)' and cells['E1'].find(X+'f').text == '_xlfn.LET(_xlpm.x,1,_xlpm.x+1)'
        assert cells['D1'].find(X+'v') is None and cells['E1'].find(X+'v') is None
    assert officecli_backend.audit(result['file'])['validation']['exit_code'] == 0
    grid = session.read_grid(draft, 1, 'Sheet', 'D1:E1'); assert all(not item['editable'] and item['read_only_reason'] == 'formula_range' for item in grid['rows'][0])
    added = session.edit_grid(draft, 1, 'Sheet', 'F1', [{'cell':'F1','value':'=XLOOKUP(A1,D1:D3,E1:E3)'}])
    with zipfile.ZipFile(added['file']) as archive:
        assert grid_values.metadata_part(archive) == 'xl/office-use-metadata.xml'
        cells = {cell.get('r'):cell for cell in etree.fromstring(archive.read('xl/worksheets/sheet1.xml')).iter(X+'c')}
        assert cells['F1'].find(X+'f').text == '_xlfn.XLOOKUP(A1,D1:D3,E1:E3)' and cells['F1'].find(X+'v') is None
    single = session.edit(draft, 2, '/Sheet/G1', 'formula', '=SORT(A1:A2)')
    assert single['dynamic_formula_cells'] == ['G1'] and single['revision'] == 3
    try: session.edit_grid(draft, 3, 'Sheet', 'D1', [{'cell':'D1','value':'4'}])
    except ValueError: pass
    else: raise AssertionError('Dynamic array anchor was editable')
    assert session.info(draft)['latest_revision'] == 3
    unsupported = root / 'unsupported.xlsx'
    with zipfile.ZipFile(result['file']) as before, zipfile.ZipFile(unsupported, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'xl/office-use-metadata.xml':
                tree = etree.fromstring(data); tree.set('unknown', '1'); data = etree.tostring(tree)
            after.writestr(entry, data)
    with zipfile.ZipFile(unsupported) as archive:
        try: grid_values.metadata_part(archive)
        except ValueError as error: assert 'Unsupported sheet metadata' in str(error)
        else: raise AssertionError('Unexpected metadata accepted')
    rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'; ct = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    chain_source = root / 'chain.xlsx'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(chain_source, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'xl/_rels/workbook.xml.rels':
                tree = etree.fromstring(data); etree.SubElement(tree, rel+'Relationship', Id='chain', Type=grid_values.CHAIN_REL, Target='calcChain.xml'); data=etree.tostring(tree)
            if entry.filename == '[Content_Types].xml':
                tree = etree.fromstring(data); etree.SubElement(tree, ct+'Override', PartName='/xl/calcChain.xml', ContentType=grid_values.CHAIN_TYPE); data=etree.tostring(tree)
            after.writestr(entry, data)
        chain = etree.Element(X+'calcChain'); etree.SubElement(chain, X+'c', r='B1', i='1'); after.writestr('xl/calcChain.xml', etree.tostring(chain))
    chain_draft = root / 'chain'; session.start(chain_draft, source=chain_source)
    chain_edit = session.edit_grid(chain_draft, 0, 'Sheet', 'D1', [{'cell':'D1','value':'=SEQUENCE(3)'}]); assert chain_edit['calculation_chain'] == 'removed'
    with zipfile.ZipFile(chain_edit['file']) as archive:
        assert 'xl/calcChain.xml' not in archive.namelist() and grid_values.metadata_part(archive) == 'xl/office-use-metadata.xml'
    assert officecli_backend.audit(chain_edit['file'])['validation']['exit_code'] == 0
    assert not grid_values.dynamic_formula_matches('SEQUENCE(A1)', '_xlfn.SEQUENCE(_xlpm.A1)')
    assert not grid_values.dynamic_formula_matches('LET(x,x,x)', '_xlfn.LET(_xlpm.x,_xlpm.x,_xlpm.x)')
    assert not grid_values.dynamic_formula_matches('SUM(A1)', '_xlfn.SUM(A1)')
print('Dynamic formula smoke passed: metadata, preservation, validation and protection')
