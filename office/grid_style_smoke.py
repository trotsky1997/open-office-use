"""Exercise common spreadsheet formatting through versioned grid edits."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.xlsx'; draft = root / 'draft'; book = Workbook(); sheet = book.active
    sheet['A1'] = 'Report'; sheet['A1'].font = Font(bold=True, name='Calibri', size=11); sheet['A1'].fill = PatternFill('solid', fgColor='FFEECC')
    sheet['B1'] = '=1+1'; book.save(source); original = source.read_bytes(); session.start(draft, source=source)
    props = {'italic': True, 'underline': 'single', 'font_name': 'Arial', 'font_size': 14.5, 'font_color': '336699', 'horizontal': 'center', 'vertical': 'top', 'wrap': True}
    result = session.format_grid(draft, 0, 'Sheet', 'A1:B1', 'A1', props)
    output = load_workbook(result['file']); cell = output.active['A1']
    assert cell.value == 'Report' and cell.font.b and cell.font.i and cell.font.u == 'single', cell.font
    assert cell.font.name == 'Arial' and cell.font.sz == 14.5 and cell.font.color.rgb[-6:] == '336699', cell.font
    assert cell.fill.fgColor.rgb[-6:] == 'FFEECC' and cell.alignment.horizontal == 'center' and cell.alignment.vertical == 'top' and cell.alignment.wrap_text, cell.alignment
    assert output.active['B1'].value == '=1+1' and source.read_bytes() == original
    style = session.read_grid(draft, 1, 'Sheet', 'A1')['rows'][0][0]['style']
    assert style['italic'] and style['underline'] == 'single' and style['font_name'] == 'Arial' and style['font_size'] == 14.5 and style['font_color_rgb'] == '336699'
    assert style['horizontal'] == 'center' and style['vertical'] == 'top' and style['wrap']
    for props in ({'font_size': True}, {'font_size': 500}, {'font_size': float('nan')}, {'font_size': 10**400}, {'font_color': 'red'}, {'horizontal': 'bad'}, {'wrap': 'yes'}, {'font_name': '\n'}):
        try: session.format_grid(draft, 1, 'Sheet', 'A1:B1', 'A1', props)
        except ValueError: pass
        else: raise AssertionError(f'Invalid style accepted: {props}')
    assert session.info(draft)['latest_revision'] == 1
    cli = Path(__file__).with_name('open_office_use.py')
    command = subprocess.run([sys.executable, str(cli), 'session', 'format-grid', str(draft), '--base', '1', '--sheet', 'Sheet', '--range', 'A1:B1', '--style-range', 'A1', '--properties', json.dumps({'italic': False, 'wrap': False, 'underline': 'none'})], capture_output=True, text=True, check=True)
    assert json.loads(command.stdout)['revision'] == 2
    changed = load_workbook(draft / 'revision-000002.xlsx').active['A1']
    assert not changed.font.i and changed.font.u is None and not changed.alignment.wrap_text and changed.font.b and changed.font.name == 'Arial'
print('Spreadsheet grid formatting smoke passed')
