"""Exercise XLSX escape-like input protection without restricting formulas."""
import tempfile
from pathlib import Path
from openpyxl import Workbook
import open_office_use
import session
import spreadsheet

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.xlsx'; draft = root / 'draft'
    book = Workbook(); book.active['A1'] = 'original'; book.active['B1'] = 'other'; book.save(source)
    original = source.read_bytes(); session.start(draft, source=source)
    for action in (
        lambda: session.edit_grid(draft, 0, 'Sheet', 'A1:B1', [{'cell': 'A1', 'value': 'safe'}, {'cell': 'B1', 'value': 'literal _x0041_'}]),
        lambda: session.edit(draft, 0, '/Sheet/A1', 'value', 'literal _x0041_'),
        lambda: open_office_use.author({'sheets': {'Sheet': {'A1': 'literal _x0041_'}}}, root / 'authored.xlsx', source),
    ):
        try: action()
        except ValueError as exc: assert 'escape-like' in str(exc)
        else: raise AssertionError('escape-like text was accepted')
        assert session.info(draft)['latest_revision'] == 0 and source.read_bytes() == original
    assert not (root / 'authored.xlsx').exists()
    result = session.edit_grid(draft, 0, 'Sheet', 'A1', [{'cell': 'A1', 'value': '="_x0041_"'}])
    assert spreadsheet.read_range(result['file'], 'Sheet', 'A1')['rows'][0][0]['formula'] == '="_x0041_"'
print('Escape input smoke passed: rejected text, unchanged revisions and formula support')
