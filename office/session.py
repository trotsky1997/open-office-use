"""Persistent local draft sessions with immutable, optimistic revisions."""
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import officecli_backend

FORMATS = ('.docx', '.xlsx', '.pptx')


def start(directory, source=None, format=None):
    directory = Path(directory).absolute()
    if (source is None) == (format is None):
        raise ValueError('Provide exactly one of source or format')
    if source is not None:
        source = Path(source).resolve(strict=True)
        suffix = source.suffix.lower()
    else:
        if format is None:
            raise ValueError('Format is required for a blank session')
        suffix = '.' + format.lower().lstrip('.')
    if suffix not in FORMATS:
        raise ValueError('Supported formats: docx, xlsx, pptx')
    directory.mkdir(parents=False)
    try:
        initial = directory / ('revision-000000' + suffix)
        if source:
            shutil.copyfile(source, initial)
        else:
            officecli_backend.batch([], initial)
        with (directory / 'session.json').open('x', encoding='utf-8') as f:
            json.dump({'version': 1, 'suffix': suffix}, f)
    except BaseException:
        shutil.rmtree(directory)
        raise
    return info(directory)


def info(directory):
    directory = Path(directory).resolve(strict=True)
    with (directory / 'session.json').open(encoding='utf-8') as f:
        manifest = json.load(f)
    suffix = manifest.get('suffix')
    if manifest.get('version') != 1 or suffix not in FORMATS:
        raise ValueError('Invalid session manifest')
    pattern = re.compile(r'revision-(\d{6})' + re.escape(suffix) + r'\Z')
    revisions = []
    for path in directory.iterdir():
        match = pattern.fullmatch(path.name)
        if match:
            if path.is_symlink() or not path.is_file():
                raise ValueError('Invalid session revision file')
            revisions.append(int(match.group(1)))
    revisions.sort()
    if not revisions or revisions[0] != 0 or revisions != list(range(len(revisions))):
        raise ValueError('Session revisions are missing or inconsistent')
    return {'directory': str(directory), 'format': suffix[1:], 'latest_revision': revisions[-1],
            'revisions': [{'revision': rev, 'file': str(directory / f'revision-{rev:06d}{suffix}')} for rev in revisions]}


def revision_file(state, revision):
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or revision > state['latest_revision']:
        raise ValueError('Session revision does not exist')
    return Path(state['revisions'][revision]['file'])


def apply(directory, base_revision, operations):
    state = info(directory)
    source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f"revision-{base_revision + 1:06d}.{state['format']}"
    try:
        result = officecli_backend.batch(operations, output, source)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': result['output'], 'result': result['result']}


def export(directory, revision, output):
    state = info(directory)
    source = revision_file(state, revision)
    output = Path(output).absolute()
    if output.suffix.lower() != source.suffix.lower():
        raise ValueError('Output format must match the session')
    if output.resolve().is_relative_to(Path(state['directory'])):
        raise ValueError('Export must be outside the session directory')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-export-') as tmp:
        candidate = Path(tmp) / ('document' + source.suffix)
        shutil.copyfile(source, candidate)
        os.link(candidate, output)
    return {'revision': revision, 'output': str(output)}
