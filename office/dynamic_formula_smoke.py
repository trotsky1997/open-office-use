"""Exercise dynamic formula metadata and protected spreadsheet edits."""
import tempfile
import subprocess
import sys
import json
import hashlib
import zipfile
from pathlib import Path
from lxml import etree
from openpyxl import Workbook, load_workbook
import grid_values
import officecli_backend
import session
import spreadsheet
import visual
import open_office_use

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
    assert spreadsheet.render_advisory(result['file'])['dynamic_array_metadata'] is True
    assert spreadsheet.render_advisory(source)['dynamic_array_metadata'] is False
    changing = root / 'changing.xlsx'; changing.write_bytes(Path(result['file']).read_bytes())
    expected_hash = hashlib.sha256(changing.read_bytes()).hexdigest()
    def render_while_source_changes(frozen, out):
        changing.write_bytes(source.read_bytes())
        return open_office_use.render(frozen, out)
    _, stable_page = visual.page_image(changing, 1, render_while_source_changes)
    assert stable_page['snapshot_sha256'] == expected_hash and stable_page['render_advisory']['dynamic_array_metadata'] is True
    assert spreadsheet.render_advisory(changing)['dynamic_array_metadata'] is False
    changing.write_bytes(Path(result['file']).read_bytes())
    original_render = open_office_use.render
    def changed_render(frozen, out):
        changing.write_bytes(source.read_bytes())
        return original_render(frozen, out)
    open_office_use.render = changed_render
    try: frozen_render = open_office_use.render_with_info(changing, root / 'frozen-pdf')
    finally: open_office_use.render = original_render
    assert frozen_render['snapshot_sha256'] == expected_hash and frozen_render['render_advisory']['dynamic_array_metadata'] is True
    assert spreadsheet.render_advisory(changing)['dynamic_array_metadata'] is False
    _, page = visual.page_image(result['file'], 1, open_office_use.render)
    assert page['render_advisory']['dynamic_array_metadata'] is True
    _, contact = visual.contact_sheet(result['file'], 1, 1, open_office_use.render)
    assert contact['render_advisory']['dynamic_array_metadata'] is True
    _, comparison = visual.compare_pages(result['file'], result['file'], 1, 1, open_office_use.render)
    assert comparison['before_render_advisory']['dynamic_array_metadata'] and comparison['after_render_advisory']['dynamic_array_metadata']
    cli_render = subprocess.run([sys.executable, str(Path(__file__).with_name('open_office_use.py')), 'render', result['file'], '--out-dir', str(root / 'pdf')], capture_output=True, text=True, check=True)
    assert json.loads(cli_render.stdout)['render_advisory']['dynamic_array_metadata'] and json.loads(cli_render.stdout)['snapshot_sha256'] == hashlib.sha256(Path(result['file']).read_bytes()).hexdigest()
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
    scan = session.scan_formulas(draft, 3); assert scan['dynamic_array_metadata'] is True and scan['dynamic_array_metadata_issue'] is None
    try: session.recalculate(draft, 3)
    except ValueError as error: assert 'Dynamic-array metadata detected' in str(error)
    else: raise AssertionError('Dynamic array converted without explicit override')
    assert session.info(draft)['latest_revision'] == 3
    cli = Path(__file__).with_name('open_office_use.py')
    denied = subprocess.run([sys.executable, str(cli), 'session', 'recalculate', str(draft), '--base', '3'], capture_output=True, text=True)
    assert denied.returncode != 0 and 'Dynamic-array metadata' in denied.stderr and session.info(draft)['latest_revision'] == 3
    allowed = subprocess.run([sys.executable, str(cli), 'session', 'recalculate', str(draft), '--base', '3', '--allow-dynamic-arrays'], capture_output=True, text=True, check=True)
    explicit = json.loads(allowed.stdout); assert explicit['revision'] == 4 and explicit['dynamic_array_override'] and session.info(draft)['latest_revision'] == 4
    ambiguous = root / 'ambiguous.xlsx'
    with zipfile.ZipFile(result['file']) as before, zipfile.ZipFile(ambiguous, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == '[Content_Types].xml':
                tree = etree.fromstring(data); ct_ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
                metadata = next(item for item in tree if item.get('ContentType') == grid_values.META_TYPE)
                etree.SubElement(tree, ct_ns + 'Override', PartName=metadata.get('PartName'), ContentType=grid_values.META_TYPE); data = etree.tostring(tree)
            after.writestr(entry, data)
    assert spreadsheet.render_advisory(ambiguous)['dynamic_array_metadata'] is None
    scan = spreadsheet.scan_formulas(ambiguous); assert scan['dynamic_array_metadata'] is None and scan['dynamic_array_metadata_issue']
    try: spreadsheet.recalculate(ambiguous, root / 'ambiguous-out.xlsx')
    except ValueError as error: assert 'Cannot inspect dynamic-array metadata' in str(error)
    else: raise AssertionError('Ambiguous metadata converted without explicit override')
    assert not (root / 'ambiguous-out.xlsx').exists()
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
    assert spreadsheet.scan_formulas(source)['dynamic_array_metadata'] is False
    assert not grid_values.dynamic_formula_matches('SEQUENCE(A1)', '_xlfn.SEQUENCE(_xlpm.A1)')
    assert not grid_values.dynamic_formula_matches('LET(x,x,x)', '_xlfn.LET(_xlpm.x,_xlpm.x,_xlpm.x)')
    assert not grid_values.dynamic_formula_matches('SUM(A1)', '_xlfn.SUM(A1)')
print('Dynamic formula smoke passed: metadata, preservation, validation and protection')
