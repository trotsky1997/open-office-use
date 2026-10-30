"""OfficeCLI structured authoring on isolated copies."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def call(*args, data=None):
    executable = shutil.which('officecli')
    if not executable:
        raise RuntimeError('OfficeCLI is required: install it and add officecli to PATH')
    result = subprocess.run([executable, *map(str, args), '--json'],
                            input=json.dumps(data, ensure_ascii=False) if data is not None else None,
                            text=True, capture_output=True, timeout=120, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'OfficeCLI returned invalid JSON: {result.stderr or result.stdout}') from exc
    if result.returncode or not isinstance(payload, dict) or payload.get('success') is not True:
        raise RuntimeError(f'OfficeCLI failed: {json.dumps(payload, ensure_ascii=False)} {result.stderr}'.strip())
    return payload.get('data')


def read(source, mode, target=None):
    source = Path(source).resolve(strict=True)
    if mode == 'outline':
        return call('view', source, 'outline')
    return call(mode, source, target)


def batch(operations, output, source=None):
    if not isinstance(operations, list) or not all(isinstance(op, dict) for op in operations):
        raise ValueError('Batch specification must be a JSON array of operation objects')
    output = Path(output).absolute()
    if output.suffix.lower() not in ('.docx', '.xlsx', '.pptx'):
        raise ValueError('Supported formats: .docx, .xlsx, .pptx')
    if source:
        source = Path(source).resolve(strict=True)
        if source.suffix.lower() != output.suffix.lower():
            raise ValueError('Source and output formats must match')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-use-') as tmp:
        candidate = Path(tmp) / ('document' + output.suffix.lower())
        created = False
        try:
            if source:
                shutil.copyfile(source, candidate)
            else:
                # create may start a resident even if its response fails.
                created = True
                call('create', candidate)
            created = True
            result = call('batch', candidate, data=operations)
            call('close', candidate)
            created = False
            # Hard-link publishes the complete file exclusively on the same filesystem.
            os.link(candidate, output)
        finally:
            if created:
                try:
                    call('close', candidate)
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    pass
    return {'output': str(output), 'result': result}
