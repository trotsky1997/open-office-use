"""Exercise sparse search, result limits and revision-specific access."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from openpyxl import Workbook
import xlsxwriter
import session
import spreadsheet

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.xlsx'; book = Workbook(); sheet = book.active
    sheet['XFD1048576'] = 'distant needle'; sheet['A1'] = '=SUM(needle)'
    hidden = book.create_sheet('Hidden'); hidden.sheet_state = 'hidden'
    for i in range(1, 203): hidden.cell(i, 1, 'needle')
    book.save(source)
    result = spreadsheet.search_cells(source, 'needle')
    assert result['complete'] and result['match_count'] == 204 and result['matches_truncated']
    assert result['matches'][0]['kind'] == 'formula' and result['matches'][1]['cell'] == 'XFD1048576'
    assert result['matches'][2]['sheet_state'] == 'hidden'
    assert spreadsheet.search_cells(source, 'Needle')['match_count'] == 0
    draft = root / 'draft'; session.start(draft, source=source)
    assert session.search_cells(draft, 0, 'distant')['matches'][0]['cell'] == 'XFD1048576'
    cli = Path(__file__).with_name('open_office_use.py')
    output = subprocess.run([sys.executable, str(cli), 'session', 'search-cells', str(draft), '--revision', '0', '--query', 'distant'], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout)['revision'] == 0
    shared = root / 'shared.xlsx'; writer = xlsxwriter.Workbook(str(shared)); writer.add_worksheet().write('A1', '共享文本'); writer.close()
    shared_result = spreadsheet.search_cells(shared, '共享')
    assert shared_result['matches'][0]['cell'] == 'A1' and not shared_result['complete'] and shared_result['unverified_text_cells'] == 1
    large = root / 'large.xlsx'; big = Workbook(write_only=True); page = big.create_sheet()
    for _ in range(100000): page.append(['other'])
    page.append(['needle']); big.save(large)
    limited = spreadsheet.search_cells(large, 'needle')
    assert limited['stored_cells_scanned'] == 100000 and not limited['scan_complete'] and not limited['matches']
    for query in ('', 'a' * 201, '\x00'):
        try: spreadsheet.search_cells(source, query)
        except ValueError: pass
        else: raise AssertionError('invalid search query accepted')
print('Cell search smoke passed: sparse, formulas, hidden sheets, bounds and saved revisions')
