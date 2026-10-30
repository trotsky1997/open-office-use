"""Verify bounded reads and real LibreOffice formula caches."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook

cli = Path(__file__).with_name('open_office_use.py')

def run(*args, ok=True):
    result = subprocess.run([sys.executable, str(cli), *map(str, args)], capture_output=True, text=True)
    assert (result.returncode == 0) == ok, (result.stdout, result.stderr)
    return json.loads(result.stdout) if ok else result.stderr

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    source = root / 'source.xlsx'
    workbook = Workbook(); sheet = workbook.active; sheet.title = 'Data'
    sheet['A1'] = 2; sheet['A2'] = 3; sheet['A3'] = '=SUM(A1:A2)'; sheet['A4'] = '=1/0'
    workbook.save(source)
    original = source.read_bytes()
    before = run('cells', source, '--sheet', 'Data', '--range', 'A1:A4')
    assert before['rows'][2][0]['formula'] == '=SUM(A1:A2)' and before['rows'][2][0]['value'] is None
    assert before['cache_freshness'] == 'unknown'
    blank = run('cells', source, '--sheet', 'Data', '--range', 'C8:D9')
    assert len(blank['rows']) == 2 and all(len(row) == 2 for row in blank['rows'])
    assert all(cell['value'] is None for row in blank['rows'] for cell in row)
    output = root / 'calculated.xlsx'
    run('recalculate', source, '--out', output)
    after = run('cells', output, '--sheet', 'Data', '--range', 'A1:A4')
    assert after['rows'][2][0]['formula'] == '=SUM(A1:A2)' and after['rows'][2][0]['value'] == 5
    assert after['rows'][3][0]['value'] == '#DIV/0!' and after['rows'][3][0]['type'] == 'e'
    assert source.read_bytes() == original
    assert 'already exists' in run('recalculate', source, '--out', output, ok=False)
    assert '10,000' in run('cells', output, '--sheet', 'Data', '--range', 'A1:Z1000', ok=False)
    assert 'not found' in run('cells', output, '--sheet', 'Absent', '--range', 'A1', ok=False)
print('Spreadsheet smoke passed: bounded reads, cached results, formula errors and copy protection')
