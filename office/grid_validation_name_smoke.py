"""Check scoped defined names used by validation lists."""
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile
from lxml import etree
from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
import session

with TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.xlsx'; draft = root / 'draft'
    book = Workbook(); sheet = book.active; sheet.title = 'Input'; options = book.create_sheet('Options')
    options['A1'] = 'Global'; options['B1'] = 'Local'
    book.defined_names.add(DefinedName('Choices', attr_text="'Options'!$A$1"))
    sheet.defined_names.add(DefinedName('Choices', attr_text="'Options'!$B$1", localSheetId=0))
    book.defined_names.add(DefinedName('GlobalList', attr_text="'Options'!$A$1"))
    book.defined_names.add(DefinedName('Dynamic', attr_text="OFFSET(Options!$A$1,0,0,1,1)"))
    for cell, formula in [('A1','=choices'), ('B1','GlobalList'), ('C1','Dynamic'), ('D1','Missing')]:
        rule = DataValidation(type='list', formula1=formula); sheet.add_data_validation(rule); rule.add(cell)
    book.save(source); session.start(draft, source=source)
    grid = session.read_grid(draft, 0, 'Input', 'A1:D1')
    rules = {item['cells'][0]: item for item in grid['data_validation']['rules']}
    assert rules['A1']['list_values'] == ['Local'] and rules['A1']['list_name'] == {'name':'Choices', 'scope':'Input'}
    assert rules['B1']['list_values'] == ['Global'] and rules['B1']['list_name'] == {'name':'GlobalList', 'scope':'workbook'}
    assert rules['C1']['list_resolution'] == 'unsupported_reference' and rules['D1']['list_resolution'] == 'missing_name'
    # Duplicate names are rejected even if the workbook reader collapses them.
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(root / 'ambiguous.xlsx', 'w') as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == 'xl/workbook.xml':
                tree = etree.fromstring(data); ns = {'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                names = tree.find('x:definedNames', ns); original = next(n for n in names if n.get('name') == 'GlobalList')
                duplicate = etree.fromstring(etree.tostring(original)); duplicate.set('name','globallist'); names.append(duplicate); data = etree.tostring(tree)
            dst.writestr(item, data)
    session.start(root / 'ambiguous', source=root / 'ambiguous.xlsx')
    bad = session.read_grid(root / 'ambiguous', 0, 'Input', 'B1')['data_validation']['rules'][0]
    assert bad['list_resolution'] == 'ambiguous_name' and 'list_values' not in bad
print('Named validation reference smoke passed')
