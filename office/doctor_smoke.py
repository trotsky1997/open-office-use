"""Check real and missing local dependency probes."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import open_office_use

cli = Path(__file__).with_name('open_office_use.py')
def probe(env):
    result = subprocess.run([sys.executable, str(cli), 'doctor'], capture_output=True, text=True, env=env, check=True)
    return json.loads(result.stdout)

current = probe(os.environ.copy())
assert current['dependencies']['mcp']['status'] in ('available', 'missing', 'error')
assert set(current['capabilities']) == {'structured_authoring', 'pdf_rendering', 'page_images', 'selected_text', 'mcp_server'}
missing = probe(dict(os.environ, PATH=''))
assert all(missing['dependencies'][name]['status'] == 'missing' for name in ('officecli', 'libreoffice', 'pdftoppm', 'pdfinfo', 'pdftotext'))
assert missing['capabilities'] == {'structured_authoring': False, 'pdf_rendering': False, 'page_images': False, 'selected_text': False, 'mcp_server': current['capabilities']['mcp_server']}
with tempfile.TemporaryDirectory() as directory:
    fake = Path(directory) / 'officecli'; fake.write_text('#!/bin/sh\necho failed >&2\nexit 1\n'); fake.chmod(0o755)
    failed = probe(dict(os.environ, PATH=directory))
    assert failed['dependencies']['officecli']['status'] == 'error' and not failed['capabilities']['structured_authoring']
with patch('open_office_use.importlib.import_module', side_effect=ModuleNotFoundError("No module named 'mcp'", name='mcp')):
    assert not open_office_use.doctor()['capabilities']['mcp_server']
print('Doctor smoke passed: installed and missing tools')
