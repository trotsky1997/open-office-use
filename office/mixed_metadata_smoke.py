"""Exercise dynamic formulas alongside embedded-image metadata."""
import copy
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from PIL import Image
import xlsxwriter
import grid_values
import officecli_backend
import session

X = grid_values.X
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); image = root / 'image.png'; Image.new('RGB', (10, 10), 'red').save(image)
    source = root / 'source.xlsx'; book = xlsxwriter.Workbook(source); sheet = book.add_worksheet('Sheet')
    sheet.embed_image('A1', str(image)); sheet.write_dynamic_array_formula('B1', '=SEQUENCE(3)'); book.close()
    # Give the existing anchor the second valid metadata record.
    reordered = root / 'reordered.xlsx'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(reordered, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'xl/metadata.xml':
                tree = etree.fromstring(data); records = tree.find(X + 'cellMetadata')
                records.insert(0, copy.deepcopy(records[0])); records.set('count', '2'); data = etree.tostring(tree)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                tree = etree.fromstring(data)
                next(cell for cell in tree.iter(X + 'c') if cell.get('r') == 'B1').set('cm', '2'); data = etree.tostring(tree)
            after.writestr(entry, data)
    draft = root / 'draft'; session.start(draft, source=reordered)
    grid = session.read_grid(draft, 0, 'Sheet', 'B1')
    assert grid['rows'][0][0]['editable'] and grid['rows'][0][0]['dynamic_formula_anchor']
    result = session.edit_grid(draft, 0, 'Sheet', 'C1', [{'cell': 'C1', 'value': '=SEQUENCE(4)'}])
    with zipfile.ZipFile(reordered) as before, zipfile.ZipFile(result['file']) as after:
        assert grid_values.dynamic_metadata_indices(after.read('xl/metadata.xml')) == {'1', '2'}
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name not in ('xl/worksheets/sheet1.xml', 'xl/styles.xml'))
        cells = {cell.get('r'): cell for cell in etree.fromstring(after.read('xl/worksheets/sheet1.xml')).iter(X + 'c')}
        assert cells['A1'].get('vm') == '1' and cells['B1'].get('cm') == '2' and cells['C1'].get('cm') == '1'
    assert officecli_backend.audit(result['file'])['validation']['exit_code'] == 0
    result = session.edit_grid(draft, 1, 'Sheet', 'B1', [{'cell': 'B1', 'value': '=SEQUENCE(5)'}])
    with zipfile.ZipFile(reordered) as before, zipfile.ZipFile(result['file']) as after:
        assert before.read('xl/metadata.xml') == after.read('xl/metadata.xml')
        cells = {cell.get('r'): cell for cell in etree.fromstring(after.read('xl/worksheets/sheet1.xml')).iter(X + 'c')}
        assert cells['B1'].get('cm') == '1' and cells['B1'].find(X + 'f').text == '_xlfn.SEQUENCE(5)'
    with zipfile.ZipFile(reordered) as archive:
        tree = etree.fromstring(archive.read('xl/metadata.xml')); types = tree.find(X + 'metadataTypes')
        types.append(copy.deepcopy(types[0])); types.set('count', str(len(types)))
        try: grid_values.dynamic_metadata_indices(etree.tostring(tree))
        except ValueError: pass
        else: raise AssertionError('Duplicate dynamic metadata types accepted')
    image_only = root / 'image-only.xlsx'; book = xlsxwriter.Workbook(image_only); sheet = book.add_worksheet('Sheet')
    sheet.embed_image('A1', str(image)); book.close()
    image_draft = root / 'image-only'; session.start(image_draft, source=image_only)
    try: session.edit_grid(image_draft, 0, 'Sheet', 'C1', [{'cell': 'C1', 'value': '=SEQUENCE(3)'}])
    except ValueError: pass
    else: raise AssertionError('Metadata without a dynamic record accepted')
print('mixed metadata smoke passed')
