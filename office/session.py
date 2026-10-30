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


def validate_selection(selection):
    if not isinstance(selection, dict) or set(selection) != {'revision', 'page', 'box'}:
        raise ValueError('Selection requires revision, page and box')
    revision, page, box = selection['revision'], selection['page'], selection['box']
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError('Invalid selection revision')
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError('Invalid selection page')
    if not isinstance(box, list) or len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box):
        raise ValueError('Selection box requires four normalized coordinates')
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError('Invalid selection box')
    return {'revision': revision, 'page': page, 'box': box}


def set_selection(directory, selection):
    selection = validate_selection(selection)
    state = info(directory)
    if selection['revision'] != state['latest_revision']:
        raise ValueError('Selection revision is stale; select the latest page')
    directory = Path(state['directory'])
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, prefix='.selection-', delete=False) as f:
        temp = Path(f.name)
        try:
            json.dump(selection, f, allow_nan=False)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, directory / 'selection.json')
    finally:
        temp.unlink(missing_ok=True)
    return selection


def get_selection(directory):
    state = info(directory)
    with (Path(state['directory']) / 'selection.json').open(encoding='utf-8') as f:
        selection = validate_selection(json.load(f))
    revision_file(state, selection['revision'])
    return {**selection, 'latest_revision': state['latest_revision'],
            'stale': selection['revision'] != state['latest_revision']}
