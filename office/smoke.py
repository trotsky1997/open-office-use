"""Exercise each format and the render boundary using temporary files."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

cli = Path(__file__).with_name('open_office_use.py')

def run(*args, ok=True):
    result = subprocess.run([sys.executable, str(cli), *map(str, args)], capture_output=True, text=True)
    assert (result.returncode == 0) == ok, (result.stdout, result.stderr)
    return json.loads(result.stdout) if ok else result.stderr

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    cases = [('.docx', {'paragraphs': ['Hello']}, 'Hello'),
             ('.xlsx', {'sheets': {'Data': {'A1': 3, 'A2': '=A1*2'}}}, '=A1*2'),
             ('.pptx', {'slides': [{'title': 'Hello', 'body': 'World'}]}, 'Hello')]
    for suffix, spec, expected in cases:
        file = root / ('sample' + suffix)
        path = root / 'spec.json'
        path.write_text(json.dumps(spec), encoding='utf-8')
        run('author', '--spec', path, '--out', file)
        assert expected in json.dumps(run('inspect', file))
        assert 'already exists' in run('author', '--spec', path, '--out', file, ok=False)
        copy = root / ('copy' + suffix)
        edits = {'.docx': {'replace_paragraphs': {'0': 'Changed'}}, '.xlsx': {'sheets': {'Data': {'A1': 9}}}, '.pptx': {'replace_text': [{'slide': 0, 'shape': 0, 'text': 'Changed'}]}}
        path.write_text(json.dumps(edits[suffix]), encoding='utf-8')
        run('author', '--source', file, '--spec', path, '--out', copy)
        changed = json.dumps(run('inspect', copy))
        assert ('9' if suffix == '.xlsx' else 'Changed') in changed
        assert expected in json.dumps(run('inspect', file))
        pdf = Path(run('render', file, '--out-dir', root / suffix[1:])['pdf'])
        assert pdf.read_bytes().startswith(b'%PDF')
print('Office smoke passed: create, inspect, edit copy, render, and overwrite protection for three formats')
