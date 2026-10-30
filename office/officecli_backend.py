"""OfficeCLI structured authoring on isolated copies."""
import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import snapshot as snapshots
from pathlib import Path


def invoke(*args, data=None):
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
    if not isinstance(payload, dict) or not isinstance(payload.get('success'), bool):
        raise RuntimeError('OfficeCLI returned an invalid result envelope')
    return result.returncode, payload, result.stderr


def call(*args, data=None):
    code, payload, stderr = invoke(*args, data=data)
    if code or payload['success'] is not True:
        raise RuntimeError(f'OfficeCLI failed: {json.dumps(payload, ensure_ascii=False)} {stderr}'.strip())
    return payload.get('data')


def audit(source):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() not in ('.docx', '.xlsx', '.pptx'):
        raise ValueError('Supported formats: .docx, .xlsx, .pptx')
    with tempfile.TemporaryDirectory(prefix='office-audit-') as tmp:
        snapshot = Path(tmp) / ('document' + source.suffix.lower())
        shutil.copyfile(source, snapshot)
        code, validation, stderr = invoke('validate', snapshot)
        if code == 0 and validation['success'] is not True:
            raise RuntimeError('OfficeCLI validation returned inconsistent success status')
        try:
            issues = call('view', snapshot, 'issues', '--limit', '200')
            issues_error = None
        except RuntimeError as exc:
            issues, issues_error = None, str(exc)
    return {'validation': {'exit_code': code, 'result': validation, 'stderr': stderr},
            'issues': issues, 'issues_error': issues_error, 'issues_limit': 200,
            'issues_may_be_truncated': True}


def read(source, mode, target=None):
    source = Path(source).resolve(strict=True)
    if mode == 'outline':
        return call('view', source, 'outline')
    return call(mode, source, target)


def dump(source, path='/'):
    """Extract a bounded OfficeCLI batch from one saved document snapshot."""
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() not in ('.docx', '.xlsx', '.pptx'): raise ValueError('Supported formats: .docx, .xlsx, .pptx')
    if not isinstance(path, str) or not path.startswith('/') or len(path) > 512 or any(ord(c) < 32 for c in path):
        raise ValueError('Dump path must begin with / and contain at most 512 characters')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    executable = shutil.which('officecli')
    if not executable: raise RuntimeError('OfficeCLI is required: install it and add officecli to PATH')
    with tempfile.TemporaryDirectory(prefix='office-dump-') as tmp:
        snapshot = Path(tmp) / ('document' + source.suffix.lower()); shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
        digest = hashlib.sha256()
        with snapshot.open('rb') as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b''): digest.update(chunk)
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Document exceeds package limits or contains duplicate parts')
        except zipfile.BadZipFile as exc: raise ValueError('Invalid Office package') from exc
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run([executable, 'dump', str(snapshot), path, '--json'], stdout=stdout, stderr=stderr, timeout=120, check=False)
            if stdout.tell() > 1024 * 1024: raise ValueError('Dump exceeds the 1 MiB output limit; choose a smaller subtree')
            stdout.seek(0); stderr.seek(0)
            try: payload = json.loads(stdout.read())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc: raise RuntimeError('OfficeCLI returned invalid dump JSON') from exc
            if result.returncode or not isinstance(payload, dict) or payload.get('success') is not True:
                raise RuntimeError(f"OfficeCLI dump failed: {str(payload.get('error', payload))[:2000] if isinstance(payload, dict) else 'invalid response'} {stderr.read(2000).decode('utf-8', 'replace')}")
        operations = payload.get('data')
        if not isinstance(operations, list) or not all(isinstance(op, dict) for op in operations): raise RuntimeError('OfficeCLI returned an invalid batch dump')
        if len(operations) > 1000: raise ValueError('Dump exceeds 1,000 operations; choose a smaller subtree')
    return {'format': source.suffix.lower()[1:], 'path': path, 'snapshot_sha256': digest.hexdigest(), 'operations': operations,
            'notes': ['Inspect operations and dependencies before applying; paths can target existing content.',
                      'Subtree dumps can omit sibling resources and objects, including XLSX charts; slide layouts may require a matching template.',
                      'Compare structure and render the result to verify fidelity.']}


def schema(format, element=None, operation=None, query=None):
    """Discover installed OfficeCLI element and property schemas."""
    if format not in ('docx', 'xlsx', 'pptx'): raise ValueError('Format must be docx, xlsx or pptx')
    if operation not in (None, 'add', 'set', 'get', 'query', 'remove'): raise ValueError('Unsupported schema operation')
    if element is not None and (not isinstance(element, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', element)):
        raise ValueError('Invalid schema element name')
    if query is not None and (not isinstance(query, str) or len(query) > 100 or any(ord(c) < 32 for c in query)):
        raise ValueError('Schema query must be text of at most 100 characters')
    executable = shutil.which('officecli')
    if not executable: raise RuntimeError('OfficeCLI is required: install it and add officecli to PATH')
    version_result = subprocess.run([executable, '--version'], text=True, capture_output=True, timeout=10, check=False)
    version = version_result.stdout.strip()[:100] if version_result.returncode == 0 else None
    term = (query or '').casefold()
    if element is None:
        rows = call('help', 'all')
        if not isinstance(rows, list): raise RuntimeError('OfficeCLI returned an invalid schema catalog')
        letter = {'add': 'a', 'set': 's', 'get': 'g', 'query': 'q', 'remove': 'r'}.get(operation)
        elements = [row for row in rows if isinstance(row, dict) and row.get('kind') == 'ELEM' and row.get('format') == format
                    and isinstance(row.get('element'), str) and isinstance(row.get('ops'), str) and (not letter or letter in row['ops'])
                    and (not term or term in row['element'].casefold() or any(term in str(path).casefold() for path in (row.get('paths') or [])))]
        return {'officecli_version': version, 'format': format, 'operation': operation, 'query': query, 'elements': elements}
    result = subprocess.run([executable, 'help', format, element, '--json'], text=True, capture_output=True, timeout=30, check=False)
    if len(result.stdout) > 1000000: raise RuntimeError('OfficeCLI schema exceeds the 1,000,000-character limit')
    try: data = json.loads(result.stdout)
    except json.JSONDecodeError as exc: raise RuntimeError('OfficeCLI did not return a JSON element schema') from exc
    if result.returncode or not isinstance(data, dict) or data.get('success') is False:
        raise ValueError(f'OfficeCLI schema lookup failed: {str(data)[:2000]}')
    properties = data.get('properties'); operations = data.get('operations')
    if not isinstance(properties, dict) or not isinstance(operations, dict): raise RuntimeError('OfficeCLI returned an invalid element schema')
    if operation is not None and operations.get(operation) is not True: raise ValueError(f'{element} does not support {operation}')
    selected = {}
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, dict): raise RuntimeError('OfficeCLI returned an invalid property schema')
        if operation in ('add', 'set', 'get') and prop.get(operation) is not True: continue
        aliases = prop.get('aliases') or []
        if not isinstance(aliases, list): raise RuntimeError('OfficeCLI returned invalid property aliases')
        if term and not any(term in str(value).casefold() for value in (name, *aliases, prop.get('description', ''))): continue
        selected[name] = prop
    return {'officecli_version': version, 'format': format, 'operation': operation, 'query': query,
            'total_properties': len(properties), 'returned_properties': len(selected),
            'property_operation_filter_applied': operation in ('add', 'set', 'get'), 'schema': {**data, 'properties': selected}}


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
                frozen, _ = snapshots.copy(source, tmp)
                os.replace(frozen, candidate)
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
    return {'output': str(output), 'result': result, **({'formula_cache_effect': 'may_change'} if output.suffix.lower() == '.xlsx' else {})}
