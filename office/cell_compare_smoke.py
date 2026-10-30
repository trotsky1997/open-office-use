"""Check formula and cached-value comparison on real workbooks."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side, Color

cli = Path(__file__).with_name('open_office_use.py')
def run(*args, ok=True):
    result = subprocess.run([sys.executable, str(cli), *map(str, args)], capture_output=True, text=True)
    assert (result.returncode == 0) == ok, (result.stdout, result.stderr)
    return json.loads(result.stdout) if ok else result.stderr

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); before = root / 'before.xlsx'; after = root / 'after.xlsx'
    workbook = Workbook(); ws = workbook.active; ws.title = 'Forecast'; ws['A1'] = 4; ws['A2'] = '=A1*3'; workbook.save(before)
    ws['A1'] = 5; ws['A2'] = '=A1*4'; ws['B2'] = 'New'; workbook.save(after)
    compared = run('compare-cells', before, after, '--sheet', 'Forecast', '--range', 'A1:B3')
    changes = {item['cell']: item for item in compared['changes']}
    assert compared['changed_count'] == 3 and set(changes) == {'A1', 'A2', 'B2'}, compared
    assert changes['A1']['before']['value'] == 4 and changes['A1']['after']['value'] == 5
    assert changes['A2']['before']['formula'] == '=A1*3' and changes['A2']['after']['formula'] == '=A1*4'
    assert 'formula' in changes['A2']['changed_fields'] and compared['cache_freshness'] == 'unknown'
    assert not run('compare-cells', before, before, '--sheet', 'Forecast', '--range', 'A1:B3')['changes']
    styled = root / 'styled.xlsx'; styles = Workbook(); sheet = styles.active; sheet.title = 'Forecast'
    sheet['A1'] = 4; sheet['A2'] = '=A1*3'
    sheet['A1'].font = Font(bold=True, color=Color(theme=4))
    sheet['A1'].fill = PatternFill('solid', fgColor='FFCC00')
    sheet['A1'].border = Border(bottom=Side(style='thin'))
    sheet['A1'].alignment = Alignment(horizontal='center')
    sheet['A1'].protection = Protection(locked=False)
    sheet['A1'].number_format = '0.00'
    sheet['B1'] = 'temporary'; sheet['B1'] = None
    styles.save(styled)
    formatting = run('compare-cells', before, styled, '--sheet', 'Forecast', '--range', 'A1:B2')
    assert formatting['changed_count'] == 1, formatting
    change = formatting['changes'][0]
    assert change['cell'] == 'A1' and set(change['changed_fields']) == {'format.font', 'format.fill', 'format.border', 'format.alignment', 'format.protection', 'format.number_format'}, change
    assert 'theme="4"' in change['after']['format']['font'] and change['after']['format']['number_format'] == '0.00'
    reindexed = root / 'reindexed.xlsx'; other = Workbook(); other_sheet = other.active; other_sheet.title = 'Forecast'
    other_sheet['Z1'].font = Font(italic=True); other_sheet['A1'] = 4; other_sheet['A2'] = '=A1*3'
    other_sheet['A1'].font = Font(bold=True, color=Color(theme=4))
    other_sheet['A1'].fill = PatternFill('solid', fgColor='FFCC00')
    other_sheet['A1'].border = Border(bottom=Side(style='thin'))
    other_sheet['A1'].alignment = Alignment(horizontal='center')
    other_sheet['A1'].protection = Protection(locked=False)
    other_sheet['A1'].number_format = '0.00'; other.save(reindexed)
    assert run('compare-cells', styled, reindexed, '--sheet', 'Forecast', '--range', 'A1:B2')['changed_count'] == 0
    calculated = root / 'calculated.xlsx'; run('recalculate', before, '--out', calculated)
    cached = run('compare-cells', before, calculated, '--sheet', 'Forecast', '--range', 'A2')
    assert cached['changes'][0]['before']['value'] is None and cached['changes'][0]['after']['value'] == 12, cached
    assert 'formula' not in cached['changes'][0]['changed_fields'], cached
    assert 'not found' in run('compare-cells', before, after, '--sheet', 'Absent', '--range', 'A1', ok=False)
    for row in range(1, 503):
        ws.cell(row, 3, row); ws.row_dimensions[row].height = 24
    workbook.save(after)
    capped = run('compare-cells', before, after, '--sheet', 'Forecast', '--range', 'C1:C502')
    assert capped['changed_count'] == 502 and len(capped['changes']) == 500 and capped['truncated'], capped
    assert capped['dimensions']['changed_count'] == 502 and len(capped['dimensions']['changes']) == 500 and capped['dimensions']['truncated'], capped
print('Cell comparison smoke passed: formulas, cache, values, missing sheet and truncation')
