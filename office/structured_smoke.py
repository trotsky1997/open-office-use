"""Exercise real OfficeCLI transactions on three Office formats."""
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

cases = {
    '.docx': ([{'command': 'add', 'parent': '/body', 'type': 'paragraph', 'props': {'text': 'Hello', 'bold': 'true'}}], '/body/p[1]', 'Hello'),
    '.xlsx': ([{'command': 'add', 'parent': '/', 'type': 'sheet', 'props': {'name': 'Data'}}, {'command': 'set', 'path': '/Data/A1', 'props': {'value': '42'}}], '/Data/A1', '42'),
    '.pptx': ([{'command': 'add', 'parent': '/', 'type': 'slide', 'props': {'title': 'Hello'}}], '/slide[1]', 'Hello'),
}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    spec = root / 'batch.json'
    for suffix, (operations, path, expected) in cases.items():
        out = root / ('created' + suffix)
        spec.write_text(json.dumps(operations), encoding='utf-8')
        run('batch', '--spec', spec, '--out', out)
        assert expected in json.dumps(run('structured', out, 'get', path))
        assert run('structured', out, 'outline')
        original = out.read_bytes()
        assert 'already exists' in run('batch', '--spec', spec, '--out', out, ok=False)
        assert out.read_bytes() == original
        failed = root / ('failed' + suffix)
        change = {'command': 'set', 'path': path, 'props': {'value': '99'} if suffix == '.xlsx' else {'text': 'Changed'}}
        if suffix == '.pptx':
            change['path'] = '/slide[1]/shape[1]'
        spec.write_text(json.dumps([change, {'command': 'remove', 'path': '/missing[999]'}]))
        run('batch', '--source', out, '--spec', spec, '--out', failed, ok=False)
        assert not failed.exists() and out.read_bytes() == original
        copied = root / ('copied' + suffix)
        spec.write_text(json.dumps([change]))
        run('batch', '--source', out, '--spec', spec, '--out', copied)
        assert ('99' if suffix == '.xlsx' else 'Changed') in json.dumps(run('structured', copied, 'get', path))
        assert out.read_bytes() == original
print('OfficeCLI smoke passed: structured creation, read, copy, failure and overwrite protection')
