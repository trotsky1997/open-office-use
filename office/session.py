"""Persistent local draft sessions with immutable, optimistic revisions."""
import json
import math
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries

import cell_text
import chart_cache
import grid_styles
import grid_values
import layout
import notes
import officecli_backend
import ooxml
import review
import spreadsheet
import snapshot as snapshots
import slides
import slide_text_check
import word

FORMATS = ('.docx', '.xlsx', '.pptx')
MAIN_TYPES = {
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml',
}


def validate_source(source, suffix):
    """Check the saved snapshot is an Office package of the requested type."""
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if names.count('[Content_Types].xml') != 1 or '_rels/.rels' not in names:
                raise ValueError('Missing or ambiguous Office package metadata')
            metadata = archive.getinfo('[Content_Types].xml')
            if metadata.file_size > 1024 * 1024:
                raise ValueError('Office package content types exceed 1 MiB')
            root = ooxml.parse_xml(archive.read(metadata)).getroot()
            namespace = '{http://schemas.openxmlformats.org/package/2006/content-types}'
            if root.tag != namespace + 'Types': raise ValueError('Invalid Office package content types')
            overrides = {item.get('PartName', '').lstrip('/'): item.get('ContentType') for item in root.findall(namespace + 'Override')}
            defaults = {item.get('Extension', '').lower(): item.get('ContentType') for item in root.findall(namespace + 'Default')}
            if not any((overrides.get(name) or defaults.get(name.rsplit('.', 1)[-1].lower())) == MAIN_TYPES[suffix] for name in names):
                raise ValueError('Office package type does not match the file extension')
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ooxml.etree.XMLSyntaxError) as exc:
        raise ValueError('Invalid Office package') from exc


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
            with tempfile.TemporaryDirectory(dir=directory, prefix='.office-source-') as tmp:
                candidate, _ = snapshots.copy(source, tmp)
                validate_source(candidate, suffix)
                os.replace(candidate, initial)
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


def dump(directory, revision, path='/'):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **officecli_backend.dump(source, path)}


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
    return {'revision': base_revision + 1, 'file': result['output'], 'result': result['result'], **({'formula_cache_effect': result['formula_cache_effect']} if 'formula_cache_effect' in result else {})}


def restore(directory, base_revision, revision):
    state = info(directory)
    revision_file(state, base_revision)
    source = revision_file(state, revision)
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f"revision-{base_revision + 1:06d}.{state['format']}"
    with tempfile.TemporaryDirectory(dir=state['directory'], prefix='.office-restore-') as tmp:
        candidate, _ = snapshots.copy(source, tmp)
        try:
            os.link(candidate, output)
        except FileExistsError as exc:
            raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'restored_revision': revision, 'file': str(output)}


def list_comments(directory, revision):
    state = info(directory)
    source = revision_file(state, revision)
    if state['format'] != 'docx':
        raise ValueError('Comment inspection requires a DOCX session')
    return {'revision': revision, **word.list_comments(source)}


def tracked_changes(directory, revision):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **word.tracked_changes(source)}


def inspect_layout(directory, revision):
    state = info(directory)
    source = revision_file(state, revision)
    if state['format'] != 'pptx':
        raise ValueError('Slide layout inspection requires a PPTX session')
    return {'revision': revision, **layout.inspect(source)}



def inspect_slide_text(directory, revision, render):
    state = info(directory); source = revision_file(state, revision)
    if state['format'] != 'pptx': raise ValueError('Slide text inspection requires a PPTX session')
    return {'revision': revision, **slide_text_check.scan(source, render)}

def search_slides(directory, revision, query, slide=None, offset=0, snapshot_sha256=None, scope='slides'):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **slides.search_text(source, query, slide, offset, snapshot_sha256, scope)}


def recalculate(directory, base_revision, allow_dynamic_arrays=False):
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'xlsx':
        raise ValueError('Recalculation requires an XLSX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    try:
        spreadsheet.recalculate(source, output, allow_dynamic_arrays=allow_dynamic_arrays)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'engine': 'LibreOffice', 'dynamic_array_override': allow_dynamic_arrays}


def scan_formulas(directory, base_revision):
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'xlsx':
        raise ValueError('Formula scanning requires an XLSX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    result = spreadsheet.scan_formulas(source)
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, **result}


def inspect_workbook(directory, revision):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **spreadsheet.inspect_workbook(source)}


def search_cells(directory, revision, query, sheet=None, offset=0, snapshot_sha256=None):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **spreadsheet.search_cells(source, query, sheet, offset, snapshot_sha256)}


def scan_chart_caches(directory, revision):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **chart_cache.scan(source)}


def sync_chart_cache(directory, base_revision, part, reference, allow_formula_caches=False):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'xlsx': raise ValueError('Chart cache sync requires an XLSX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    try: result = chart_cache.sync(source, output, part, reference, allow_formula_caches)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, **result}


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
        candidate, _ = snapshots.copy(source, tmp)
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


def edit_target(directory, base_revision, path):
    if not isinstance(path, str) or not path.startswith('/') or len(path) > 512 or '\x00' in path:
        raise ValueError('Provide a valid element path of at most 512 characters')
    state = info(directory)
    source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if state['format'] == 'docx' and word.STORY_PATH.fullmatch(path):
        inventory = word.list_stories(source)
        match = word.STORY_PATH.fullmatch(path)
        stories = [item for item in inventory['stories'] if item['id'] == match.group(2) and item['type'] == match.group(1)]
        if len(stories) != 1: raise ValueError('Header or footer relationship does not exist')
        story = stories[0]
        with zipfile.ZipFile(source) as archive:
            tree = ooxml.parse_xml(archive.read(story['part']))
            target = word.find_paragraph(tree, path)
            text = ''.join(node.text or '' for node in target.iter(word.W + 't'))
        if len(text) > 4000: raise ValueError('Header or footer paragraph exceeds the editor text limit')
        paragraph = {'text': text}
        if info(directory)['latest_revision'] != base_revision: raise ValueError('Revision conflict: latest revision changed')
        links = [{'relationship_id': item['id'], **link} for item in inventory['stories'] if item['part'] == story['part'] for link in item['linked_sections']]
        return {'revision': base_revision, 'path': path, 'type': 'paragraph', 'format': 'docx', 'mode': 'text', 'value': paragraph['text'], 'replace_text_path_supported': True, 'replace_only': True,
                'story_impact': {'part': story['part'], 'linked_sections': links, 'same_part_ids': story['same_part_ids'], 'complete': inventory['reference_resolution_complete']}}
    result = officecli_backend.read(source, 'get', path)
    if not isinstance(result, dict) or result.get('matches') != 1 or not isinstance(result.get('results'), list) or len(result['results']) != 1:
        raise ValueError('The path must identify exactly one editable element')
    item = result['results'][0]
    supported = {'docx': {'paragraph', 'run'}, 'xlsx': {'cell'},
                 'pptx': {'title', 'shape', 'textbox', 'placeholder', 'paragraph', 'run', 'tc'}}
    if not isinstance(item, dict) or item.get('type') not in supported[state['format']] or not isinstance(item.get('path'), str):
        raise ValueError('Element type is not supported by this editor')
    format_data = item.get('format')
    if not isinstance(format_data, dict):
        format_data = {}
    formula = format_data.get('formula') if state['format'] == 'xlsx' else None
    text = item.get('text')
    if text is not None and not isinstance(text, str):
        text = str(text)
    if isinstance(formula, str):
        mode = 'formula'
        value = formula if formula.startswith('=') else '=' + formula
    else:
        mode = ('literal' if format_data.get('type') in {'String', 'SharedString', 'InlineString'} else 'value') if state['format'] == 'xlsx' else 'text'
        value = text or ''
    if len(value) > 4000:
        raise ValueError('Element value exceeds the 4,000-character editor limit')
    read_only_reason = None
    if state['format'] == 'xlsx':
        match = cell_text.PATH.fullmatch(item['path'])
        if not match or not cell_text.cell_path(item['path']):
            read_only_reason = 'unsupported_cell_path'
        else:
            address = match.group(2).upper() + match.group(3)
            cell = read_grid(directory, base_revision, match.group(1), address)['rows'][0][0]
            read_only_reason = cell['read_only_reason']
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, 'path': item['path'], 'type': item['type'],
            'format': state['format'], 'mode': mode, 'value': value, 'read_only_reason': read_only_reason,
            'replace_text_path_supported': (state['format'] == 'docx' and item['type'] == 'paragraph' and word.paragraph_path(item['path'])) or (state['format'] == 'pptx' and item['type'] in {'paragraph', 'title', 'shape', 'textbox', 'placeholder', 'tc'} and slides.paragraph_path(item['path'])) or (state['format'] == 'xlsx' and read_only_reason is None and mode in ('value', 'literal') and format_data.get('type') in {'String', 'SharedString', 'InlineString'} and cell_text.cell_path(item['path']))}


def edit(directory, base_revision, path, mode, value):
    if not isinstance(value, str) or len(value) > 4000:
        raise ValueError('Value must be text of at most 4,000 characters')
    target = edit_target(directory, base_revision, path)
    if target.get('read_only_reason'): raise ValueError(f"Cell cannot be edited: {target['read_only_reason']}")
    if target.get('replace_only'): raise ValueError('Use text replacement for header and footer paragraphs')
    if target['format'] == 'pptx' and target['type'] == 'tc':
        raise ValueError('Use text replacement to edit PowerPoint table cells')
    allowed = {'xlsx': {'value', 'formula', 'literal'}, 'docx': {'text'}, 'pptx': {'text'}}
    if mode not in allowed[target['format']]:
        raise ValueError('Edit mode is not supported for this format')
    if mode == 'value' and value.lstrip().startswith('='):
        raise ValueError('Choose formula mode for a value starting with =')
    if mode == 'formula' and (not value.startswith('=') or len(value) < 2):
        raise ValueError('A formula must start with = and contain an expression')
    if target['format'] == 'xlsx':
        match = cell_text.PATH.fullmatch(target['path'])
        address = match.group(2).upper() + match.group(3)
        return edit_grid(directory, base_revision, match.group(1), address, [{'cell': address, 'value': value, **({'type': 'text'} if mode == 'literal' and value else {})}])
    return apply(directory, base_revision, [{'command': 'set', 'path': target['path'], 'props': {mode: value}}])


def replace_text(directory, base_revision, path, find, replacement):
    state = info(directory)
    source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f"revision-{base_revision + 1:06d}.{state['format']}"
    try:
        {'docx': word, 'pptx': slides, 'xlsx': cell_text}[state['format']].replace_text(source, output, path, find, replacement)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'path': path, **({'formula_cache_effect': 'may_be_stale', 'recalculation_requested': True} if state['format'] == 'xlsx' else {})}


def replace_text_batch(directory, base_revision, changes):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 25:
        raise ValueError('Provide 1 to 25 text replacements')
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'path', 'find', 'replacement'} or not all(isinstance(change[key], str) for key in change):
            raise ValueError('Each replacement requires text path, find and replacement')
    state = info(directory); source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f"revision-{base_revision + 1:06d}.{state['format']}"
    replace = {'docx': word, 'pptx': slides, 'xlsx': cell_text}[state['format']].replace_text
    with tempfile.TemporaryDirectory(dir=state['directory'], prefix='.office-replace-batch-') as tmp:
        previous = source
        for index, change in enumerate(changes):
            candidate = Path(tmp) / f"step-{index:02d}.{state['format']}"
            try: replace(previous, candidate, change['path'], change['find'], change['replacement'])
            except ValueError as exc: raise ValueError(f'Replacement {index + 1}: {exc}') from exc
            if previous != source: previous.unlink()
            previous = candidate
        try: os.link(previous, output)
        except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'count': len(changes), **({'formula_cache_effect': 'may_be_stale', 'recalculation_requested': True} if state['format'] == 'xlsx' else {})}


def track_replace_text(directory, base_revision, path, find, replacement, author):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'docx': raise ValueError('Tracked replacement requires a DOCX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try: word.track_replace_text(source, output, path, find, replacement, author)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'path': path}



def track_insert_text(directory, base_revision, path, anchor, text, position, author):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'docx': raise ValueError('Tracked insertion requires a DOCX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try: result = word.track_insert_text(source, output, path, anchor, text, position, author)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'path': path, 'id': result['id'], 'part': result['part'], 'position': position}

def resolve_tracked_runs(directory, base_revision, part, ids, accept):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'docx': raise ValueError('Tracked revision resolution requires a DOCX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try: word.resolve_tracked_runs(source, output, part, ids, accept)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'part': part, 'ids': ids, 'accepted': accept}


def read_notes(directory, revision, slide):
    state = info(directory); source = revision_file(state, revision)
    result = notes.read(source, slide); result['revision'] = revision
    return result


def list_stories(directory, revision):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **word.list_stories(source)}


def search_body(directory, revision, query, offset=0, snapshot_sha256=None):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **word.search_body(source, query, offset, snapshot_sha256)}



def search_stories(directory, revision, query, offset=0, snapshot_sha256=None):
    state = info(directory); source = revision_file(state, revision)
    return {'revision': revision, **word.search_stories(source, query, offset, snapshot_sha256)}


def compare_cells(directory, before_revision, after_revision, sheet, cell_range):
    state = info(directory)
    before = revision_file(state, before_revision); after = revision_file(state, after_revision)
    return {'before_revision': before_revision, 'after_revision': after_revision, **review.compare_cells(before, after, sheet, cell_range)}

def compare_notes(directory, before_revision, after_revision, before_slide, after_slide):
    state = info(directory)
    before = revision_file(state, before_revision); after = revision_file(state, after_revision)
    result = review.compare_notes(before, after, before_slide, after_slide)
    return {'before_revision': before_revision, 'after_revision': after_revision, **result}


def replace_notes(directory, base_revision, slide, text):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'pptx': raise ValueError('Speaker notes require a PPTX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.pptx'
    try: notes.replace(source, output, slide, text)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'slide': slide}


def replace_notes_text(directory, base_revision, slide, paragraph, find, replacement):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'pptx': raise ValueError('Speaker notes require a PPTX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.pptx'
    try: notes.replace_text(source, output, slide, paragraph, find, replacement)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'slide': slide, 'paragraph': paragraph}


def reply_comment(directory, base_revision, parent_id, text, author):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'docx': raise ValueError('Comment replies require a DOCX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try:
        result = word.reply_comment(source, output, parent_id, text, author)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, **result}


def resolve_comment(directory, base_revision, comment_id, resolved):
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'docx': raise ValueError('Comment state requires a DOCX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try:
        word.set_comment_resolved(source, output, comment_id, resolved)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'comment_id': comment_id, 'resolved': resolved}


def add_comment(directory, base_revision, path, text, author, anchor=None):
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'docx':
        raise ValueError('Comments require a DOCX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.docx'
    try:
        result = word.add_comment(source, output, path, text, author, anchor)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'path': path, 'comment_id': result['comment_id']}


def replace_picture(directory, base_revision, path, image_data):
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'pptx':
        raise ValueError('Picture replacement requires a PPTX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999:
        raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.pptx'
    try:
        slides.replace_picture(source, output, path, image_data)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'path': path}


def grid_bounds(cell_range):
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        if min_col is None or min_row is None or max_col is None or max_row is None:
            raise ValueError
        if (min_col < 1 or min_row < 1 or max_col > 16384 or max_row > 1048576
                or min_col > max_col or min_row > max_row
                or (max_col - min_col + 1) * (max_row - min_row + 1) > 200):
            raise ValueError
        return min_col, min_row, max_col, max_row
    except (TypeError, ValueError):
        raise ValueError('Specify a valid rectangular range of at most 200 cells') from None


def read_grid(directory, base_revision, sheet, cell_range):
    if not isinstance(sheet, str) or not sheet or '/' in sheet or '\x00' in sheet:
        raise ValueError('Invalid sheet name')
    min_col, min_row, max_col, max_row = grid_bounds(cell_range)
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'xlsx':
        raise ValueError('Grid editing requires an XLSX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    constraints = spreadsheet.worksheet_constraints(source, sheet, (min_col, min_row, max_col, max_row), True, True)
    result = spreadsheet.read_range(source, sheet, cell_range, include_style=True)
    complex_addresses = {f'{get_column_letter(min_col + col_index)}{min_row + row_index}' for row_index, row in enumerate(result['rows']) for col_index, cell in enumerate(row) if isinstance(cell.get('formula'), dict)}
    dynamic_anchors = grid_values.unexpanded_dynamic_anchors(source, sheet, complex_addresses)
    rows = []
    for row_index, row in enumerate(result['rows']):
        cells = []
        for col_index, cell in enumerate(row):
            col, row_number = min_col + col_index, min_row + row_index
            address = f'{get_column_letter(col)}{row_number}'
            reason, origin = spreadsheet.cell_constraint(constraints, col, row_number, cell['locked'], isinstance(cell.get('formula'), dict))
            overlaps = [bounds for bounds in constraints['formula_ranges'] if bounds[0] <= col <= bounds[2] and bounds[1] <= row_number <= bounds[3]]
            dynamic_anchor = address in dynamic_anchors and overlaps == [(col, row_number, col, row_number)] and not any(bounds[0] <= col <= bounds[2] and bounds[1] <= row_number <= bounds[3] for bounds in constraints['merged_ranges']) and not (constraints['sheet_protected'] and cell['locked'])
            if dynamic_anchor and reason == 'formula_range': reason = None
            formula = cell.get('formula')
            display = formula if isinstance(formula, str) else formula.get('text') if isinstance(formula, dict) else cell.get('value')
            if reason is None and 'formula' not in cell and cell.get('text_complete') is False:
                reason = 'unverified_text'
            if reason is None and isinstance(display, str) and len(display.encode('utf-16-le')) // 2 > 4000:
                reason = 'value_too_long'
            cells.append({'cell': address, **cell, 'dynamic_formula_anchor': dynamic_anchor,
                          'editable': reason is None, 'read_only_reason': reason, 'merged_anchor': origin})
        rows.append(cells)
    part = grid_styles.sheet_part(source, sheet)
    with zipfile.ZipFile(source) as archive:
        root = ooxml.parse_xml(archive.read(part)).getroot(); views = root.findall(grid_styles.X + 'sheetViews')
        if len(views) != 1 or len(views[0]) != 1 or views[0][0].tag != grid_styles.X + 'sheetView':
            view_info = {'pane': None, 'issue': 'unsupported_worksheet_views'}
        else:
            panes = views[0][0].findall(grid_styles.X + 'pane')
            view_info = {'pane': dict(panes[0].attrib) if len(panes) == 1 else None, 'issue': 'ambiguous_panes' if len(panes) > 1 else None}
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, 'sheet': sheet, 'range': cell_range, 'sheet_protected': constraints['sheet_protected'], 'dimensions': constraints['dimensions'], 'worksheet_view': view_info,
            'rows': rows, 'cache_freshness': 'unknown'}


def edit_grid(directory, base_revision, sheet, cell_range, changes):
    if not isinstance(changes, list) or not changes or len(changes) > 200:
        raise ValueError('Provide 1 to 200 changed cells')
    grid = read_grid(directory, base_revision, sheet, cell_range)
    min_col, min_row, max_col, max_row = grid_bounds(cell_range)
    original = {cell['cell']: cell for row in grid['rows'] for cell in row}
    seen, operations, normalized = set(), [], []
    for change in changes:
        if not isinstance(change, dict) or set(change) not in ({'cell', 'value'}, {'cell', 'value', 'type'}):
            raise ValueError('Each change requires cell and value and may specify type')
        kind = change.get('type', 'auto')
        if kind not in ('auto', 'text'): raise ValueError('Cell type must be auto or text')
        address, value = change['cell'], change['value']
        match = re.fullmatch(r'([A-Za-z]{1,3})([1-9][0-9]{0,6})', address) if isinstance(address, str) else None
        if match is None:
            raise ValueError('Invalid cell address')
        col, row = column_index_from_string(match.group(1)), int(match.group(2))
        address = match.group(1).upper() + str(row)
        if not (min_col <= col <= max_col and min_row <= row <= max_row) or address in seen:
            raise ValueError('Cell is outside the range or repeated')
        if not original[address]['editable']:
            raise ValueError(f"Cell cannot be edited: {address} ({original[address]['read_only_reason']}); Array, data-table and shared formula ranges are protected")
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError('Cell values must be text of at most 4,000 characters')
        if kind == 'text' and (not value or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', value)):
            raise ValueError('Explicit text must be nonempty and contain valid XML characters')
        if kind == 'auto' and value.lstrip().startswith('=') and not value.startswith('='):
            raise ValueError('Formula expressions must begin with =')
        if kind == 'auto' and value == '=':
            raise ValueError('A formula requires an expression')
        seen.add(address)
        mode = 'formula' if kind == 'auto' and value.startswith('=') else 'value'
        if mode == 'value': spreadsheet.validate_cell_value(value)
        operations.append({'command': 'set', 'path': f'/{sheet}/{address}', 'props': {mode: 'office-use-literal-text' if kind == 'text' else value}})
        normalized.append({'cell': address, 'value': value, 'type': kind})
    state = info(directory); source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    try: result = grid_values.apply(source, output, sheet, normalized, operations)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': result['output'], 'result': result['result'], 'formula_cache_effect': result['formula_cache_effect'], 'recalculation_requested': True, 'calculation_chain': result['calculation_chain'], 'dynamic_formula_cells': result['dynamic_formula_cells']}


def format_grid(directory, base_revision, sheet, cell_range, style_range, properties):
    allowed = {'bold', 'italic', 'underline', 'font_name', 'font_size', 'font_color', 'fill', 'horizontal', 'vertical', 'wrap', 'numberformat', 'border', 'border_color', 'border_top', 'border_bottom', 'border_left', 'border_right', 'border_scope', 'border_top_color', 'border_bottom_color', 'border_left_color', 'border_right_color'}
    if not isinstance(properties, dict) or not properties or not set(properties) <= allowed:
        raise ValueError('Provide supported cell formatting properties')
    props = {}
    for name, target in (('bold', 'font.bold'), ('italic', 'font.italic'), ('wrap', 'alignment.wrapText')):
        if name in properties:
            if not isinstance(properties[name], bool): raise ValueError(f'{name} must be true or false')
            props[target] = str(properties[name]).lower()
    for name, target in (('font_color', 'font.color'), ('fill', 'fill')):
        if name in properties:
            if not isinstance(properties[name], str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', properties[name]): raise ValueError(f'{name} must be a six-digit RGB color')
            props[target] = properties[name]
    for name, target, choices in (('horizontal', 'alignment.horizontal', ('left', 'center', 'right', 'justify', 'fill', 'distributed')), ('vertical', 'alignment.vertical', ('top', 'center', 'bottom')), ('underline', 'underline', ('none', 'single', 'double', 'singleAccounting', 'doubleAccounting'))):
        if name in properties:
            if properties[name] not in choices: raise ValueError(f'Invalid {name}')
            props[target] = properties[name]
    border_names = ('border', 'border_top', 'border_bottom', 'border_left', 'border_right')
    if 'border' in properties and any(name in properties for name in border_names[1:]): raise ValueError('Choose either all borders or individual sides')
    for name in border_names:
        if name in properties:
            if properties[name] not in ('thin', 'medium', 'thick', 'double', 'dashed', 'dotted', 'none'): raise ValueError(f'Invalid {name}')
            props['border.all' if name == 'border' else 'border.' + name[7:]] = properties[name]
    if 'border_color' in properties:
        color = properties['border_color']
        if not isinstance(color, str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', color): raise ValueError('border_color must be a six-digit RGB color')
        if properties.get('border') in (None, 'none'): raise ValueError('border_color requires an all-sides border style')
        props['border.color'] = color
    scope = properties.get('border_scope', 'all')
    if scope not in ('all', 'outline', 'inside') or ('border_scope' in properties and 'border' not in properties): raise ValueError('Border scope requires an all-sides border style')
    for side in ('top', 'bottom', 'left', 'right'):
        key = f'border_{side}_color'
        if key in properties:
            color = properties[key]
            if not isinstance(color, str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', color): raise ValueError(f'{key} must be a six-digit RGB color')
            if properties.get(f'border_{side}') in (None, 'none'): raise ValueError(f'{key} requires a matching border style')
            props[f'border.{side}.color'] = color
    if 'font_name' in properties:
        value = properties['font_name']
        if not isinstance(value, str) or not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value): raise ValueError('Font name must contain 1 to 100 characters without control characters')
        props['font.name'] = value
    if 'font_size' in properties:
        value = properties['font_size']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 409 or not math.isfinite(value): raise ValueError('Font size must be between 1 and 409 points')
        props['font.size'] = f'{value}pt'
    if 'numberformat' in properties:
        value = properties['numberformat']
        if not isinstance(value, str) or not value or len(value) > 120:
            raise ValueError('Number format must contain 1 to 120 characters')
        props['numberformat'] = value
    grid = read_grid(directory, base_revision, sheet, cell_range)
    if grid['sheet_protected']: raise ValueError('Grid formatting is unavailable for protected worksheets')
    c1, r1, c2, r2 = grid_bounds(cell_range)
    sc1, sr1, sc2, sr2 = grid_bounds(style_range)
    if not (c1 <= sc1 <= sc2 <= c2 and r1 <= sr1 <= sr2 <= r2):
        raise ValueError('Formatting range must be within the loaded range')
    operations = []
    for row in grid['rows']:
        for cell in row:
            match = re.fullmatch(r'([A-Z]+)([0-9]+)', cell['cell'])
            col, number = column_index_from_string(match.group(1)), int(match.group(2))
            if sc1 <= col <= sc2 and sr1 <= number <= sr2:
                cell_props = props.copy()
                if scope != 'all':
                    cell_props.pop('border.all'); cell_props.pop('border.color', None)
                    edges = {'top': number == sr1, 'bottom': number == sr2, 'left': col == sc1, 'right': col == sc2}
                    for side, outer in edges.items():
                        if outer == (scope == 'outline'):
                            cell_props[f'border.{side}'] = properties['border']
                            if 'border_color' in properties: cell_props[f'border.{side}.color'] = properties['border_color']
                if not cell_props: continue
                if not cell['editable'] or cell['dynamic_formula_anchor']:
                    raise ValueError(f"Cell cannot be formatted in the grid: {cell['cell']} ({cell['read_only_reason'] or 'formula_range'})")
                operations.append({'command': 'set', 'path': f"/{sheet}/{cell['cell']}", 'props': cell_props})
    if not operations: raise ValueError('Formatting selection contains no applicable changes')
    state = info(directory); source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    try: result = grid_styles.apply(source, output, sheet, [op['path'].rsplit('/', 1)[1] for op in operations], operations)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': result['output'], 'result': result['result'], 'formula_cache_effect': result['formula_cache_effect']}


def merge_cells(directory, base_revision, sheet, cell_range, merge=True):
    if not isinstance(merge, bool): raise ValueError('merge must be true or false')
    c1, r1, c2, r2 = grid_bounds(cell_range)
    if (c1, r1) == (c2, r2): raise ValueError('A merged range requires at least two cells')
    address = f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}'
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'xlsx': raise ValueError('Merging cells requires an XLSX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    constraints = spreadsheet.worksheet_constraints(source, sheet)
    if constraints['sheet_protected']: raise ValueError('Protected worksheets cannot be merged')
    def overlap(a, b): return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
    bounds = (c1, r1, c2, r2)
    if merge and any(overlap(bounds, other) for other in constraints['formula_ranges']): raise ValueError('Merged range overlaps a multi-cell formula')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'; ns = grid_styles.X
    part = grid_styles.sheet_part(source, sheet)
    def edit(tree, archive):
        from lxml import etree
        root = tree.getroot(); data = root.findall(ns + 'sheetData'); containers = root.findall(ns + 'mergeCells')
        if root.tag != ns + 'worksheet' or len(data) != 1 or len(list(root.iter(ns + 'sheetData'))) != 1 or len(containers) > 1 or len(list(root.iter(ns + 'mergeCells'))) != len(containers): raise ValueError('Ambiguous worksheet structure')
        container = containers[0] if containers else None; matches = []
        if container is not None:
            count = container.get('count')
            if set(container.attrib) - {'count'} or (count is not None and (not re.fullmatch(r'[0-9]{1,8}', count) or int(count) != len(container))): raise ValueError('Invalid merge collection')
            for item in container:
                if item.tag != ns + 'mergeCell' or set(item.attrib) != {'ref'} or len(item): raise ValueError('Unsupported merge record')
                try: other = range_boundaries(item.get('ref'))
                except (ValueError, TypeError): raise ValueError('Invalid merge record') from None
                if any(v is None for v in other) or not (1 <= other[0] <= other[2] <= 16384 and 1 <= other[1] <= other[3] <= 1048576): raise ValueError('Invalid merge record')
                if overlap(bounds, other): matches.append((item, other))
        if merge:
            if matches: raise ValueError('Range overlaps an existing merged range')
            rel_path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            relationships = []
            if rel_path in archive.namelist():
                rels = ooxml.parse_xml(archive.read(rel_path)).getroot()
                if rels.tag != grid_styles.REL + 'Relationships': raise ValueError('Invalid worksheet relationships')
                relationships = rels.findall(grid_styles.REL + 'Relationship')
                ids = [item.get('Id') for item in relationships]
                if any(not rid for rid in ids) or len(ids) != len(set(ids)): raise ValueError('Ambiguous worksheet relationships')
            base = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            def related(item, expected_type):
                target = item.get('Target', '')
                if item.get('Type') != expected_type or item.get('TargetMode', 'Internal') != 'Internal' or not target or any(c in target for c in ('%', '?', '#', chr(92), ':')): raise ValueError('Unsupported related worksheet part')
                path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part), target))
                if not path.startswith('xl/') or path not in archive.namelist(): raise ValueError('Invalid related worksheet part')
                return ooxml.parse_xml(archive.read(path)).getroot()
            table_parts = root.findall(ns + 'tableParts')
            if len(table_parts) > 1 or len(list(root.iter(ns + 'tableParts'))) != len(table_parts): raise ValueError('Ambiguous table parts')
            table_rels = [item for item in relationships if item.get('Type', '').lower().endswith('/table')]
            table_ids = []
            if table_parts:
                collection = table_parts[0]; count = collection.get('count')
                if set(collection.attrib) - {'count'} or (count is not None and (not re.fullmatch(r'[0-9]{1,8}', count) or int(count) != len(collection))): raise ValueError('Invalid table parts')
                rid_key = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
                for item in collection:
                    if item.tag != ns + 'tablePart' or set(item.attrib) != {rid_key} or len(item): raise ValueError('Unsupported table part')
                    table_ids.append(item.get(rid_key))
            if len(table_ids) != len(set(table_ids)) or set(table_ids) != {item.get('Id') for item in table_rels}: raise ValueError('Ambiguous table references')
            for rel in table_rels:
                table = related(rel, base + 'table')
                if table.tag != ns + 'table': raise ValueError('Invalid table part')
                try: table_bounds = range_boundaries(table.get('ref'))
                except (TypeError, ValueError): raise ValueError('Invalid table range') from None
                if any(v is None for v in table_bounds) or not (1 <= table_bounds[0] <= table_bounds[2] <= 16384 and 1 <= table_bounds[1] <= table_bounds[3] <= 1048576): raise ValueError('Invalid table range')
                if overlap(bounds, table_bounds): raise ValueError('Merged range overlaps a table')
            comment_rels = [item for item in relationships if item.get('Type', '').lower().endswith('/comments')]
            threaded_rels = [item for item in relationships if item.get('Type', '').lower().endswith('/threadedcomment')]
            thread_type = 'http://schemas.microsoft.com/office/2017/10/relationships/threadedComment'
            if len(comment_rels) > 1 or len(threaded_rels) > 1: raise ValueError('Ambiguous comment references')
            for rel in comment_rels:
                comments = related(rel, base + 'comments'); lists = comments.findall(ns + 'commentList')
                if comments.tag != ns + 'comments' or len(lists) != 1 or len(list(comments.iter(ns + 'commentList'))) != 1 or any(child.tag not in (ns + 'authors', ns + 'commentList') for child in comments): raise ValueError('Unsupported comment structure')
                seen_comments = set()
                for comment in lists[0]:
                    ref = comment.get('ref', '')
                    if comment.tag != ns + 'comment' or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', ref) or ref in seen_comments: raise ValueError('Invalid comment reference')
                    seen_comments.add(ref); col, number = range_boundaries(ref)[:2]
                    if col > 16384 or number > 1048576: raise ValueError('Invalid comment reference')
                    if c1 <= col <= c2 and r1 <= number <= r2 and (col, number) != (c1, r1): raise ValueError(f'Non-anchor cell {ref} has a comment')
            thread_ns = '{http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments}'
            for rel in threaded_rels:
                thread = related(rel, thread_type)
                if thread.tag != thread_ns + 'ThreadedComments' or any(child.tag != thread_ns + 'threadedComment' for child in thread): raise ValueError('Unsupported threaded comment structure')
                for comment in thread:
                    ref = comment.get('ref', '')
                    if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', ref): raise ValueError('Invalid threaded comment reference')
                    col, number = range_boundaries(ref)[:2]
                    if col > 16384 or number > 1048576: raise ValueError('Invalid threaded comment reference')
                    if c1 <= col <= c2 and r1 <= number <= r2 and (col, number) != (c1, r1): raise ValueError(f'Non-anchor cell {ref} has a threaded comment')
            for link in root.iter(ns + 'hyperlink'):
                try: linked = range_boundaries(link.get('ref'))
                except (ValueError, TypeError): raise ValueError('Invalid hyperlink range') from None
                if any(value is None for value in linked): raise ValueError('Invalid hyperlink range')
                if overlap(bounds, linked) and (max(c1, linked[0]), max(r1, linked[1]), min(c2, linked[2]), min(r2, linked[3])) != (c1, r1, c1, r1): raise ValueError('Non-anchor cell contains a hyperlink')
            seen = set()
            for row in data[0].findall(ns + 'row'):
                for cell in row.findall(ns + 'c'):
                    ref = cell.get('r', '')
                    if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', ref): raise ValueError('Invalid cell reference')
                    col, number = range_boundaries(ref)[:2]
                    if ref in seen: raise ValueError('Duplicate worksheet cell')
                    seen.add(ref)
                    if c1 <= col <= c2 and r1 <= number <= r2 and (col, number) != (c1, r1):
                        if len(cell) or set(cell.attrib) - {'r', 's', 't'} or cell.get('t') not in (None, 'n') or (cell.text and cell.text.strip()): raise ValueError(f'Non-anchor cell {ref} contains data or metadata')
            if container is None:
                container = etree.Element(ns + 'mergeCells')
                preceding = {ns + name for name in ('sheetData','sheetCalcPr','sheetProtection','protectedRanges','scenarios','autoFilter','sortState','dataConsolidate','customSheetViews')}
                position = max(i for i, node in enumerate(root) if node.tag in preceding) + 1
                root.insert(position, container)
            etree.SubElement(container, ns + 'mergeCell', ref=address)
        else:
            if len(matches) != 1 or matches[0][1] != bounds: raise ValueError('Select exactly one existing merged range')
            container.remove(matches[0][0])
        if len(container): container.set('count', str(len(container)))
        else: root.remove(container)
        dimensions = root.findall(ns + 'dimension')
        if len(dimensions) > 1: raise ValueError('Ambiguous worksheet dimension')
        if merge and dimensions:
            try: left, top, right, bottom = range_boundaries(dimensions[0].get('ref'))
            except (ValueError, TypeError): raise ValueError('Invalid worksheet dimension') from None
            if any(v is None for v in (left, top, right, bottom)) or not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576): raise ValueError('Invalid worksheet dimension')
            dimensions[0].set('ref', f'{get_column_letter(min(left,c1))}{min(top,r1)}:{get_column_letter(max(right,c2))}{max(bottom,r2)}')
    try: ooxml.edit_xml(source, output, lambda _: part, edit)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'sheet': sheet, 'range': address, 'merged': merge, 'formula_cache_effect': 'preserved'}


def freeze_panes(directory, base_revision, sheet, cell):
    if cell is not None:
        if not isinstance(cell, str) or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', cell): raise ValueError('Freeze position must be an uppercase cell address or null')
        col, row = range_boundaries(cell)[:2]
        if col > 16384 or row > 1048576: raise ValueError('Freeze position is outside the worksheet')
        if cell == 'A1': cell = None
    state = info(directory); source = revision_file(state, base_revision)
    if state['format'] != 'xlsx': raise ValueError('Freeze panes require an XLSX session')
    if base_revision != state['latest_revision']: raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    ns = grid_styles.X
    def edit(tree, archive):
        root = tree.getroot(); containers = root.findall(ns + 'sheetViews')
        if root.tag != ns + 'worksheet' or len(containers) != 1 or len(list(root.iter(ns + 'sheetViews'))) != 1 or len(containers[0]) != 1 or containers[0][0].tag != ns + 'sheetView': raise ValueError('Unsupported worksheet views')
        view = containers[0][0]
        if view.get('workbookViewId') != '0' or any(child.tag not in (ns + 'pane', ns + 'selection') for child in view) or len(view.findall(ns + 'pane')) > 1: raise ValueError('Unsupported worksheet view')
        pane = view.find(ns + 'pane')
        if pane is not None and (pane.get('state') != 'frozen' or set(pane.attrib) - {'state', 'xSplit', 'ySplit', 'topLeftCell', 'activePane'} or len(pane)): raise ValueError('Unsupported existing pane')
        for selection in view.findall(ns + 'selection'):
            if len(selection) or set(selection.attrib) - {'pane', 'activeCell', 'sqref'}: raise ValueError('Unsupported existing selection')
        for child in list(view): view.remove(child)
        if cell is not None:
            attrs = {'topLeftCell':cell, 'state':'frozen'}
            if col > 1: attrs['xSplit'] = str(col - 1)
            if row > 1: attrs['ySplit'] = str(row - 1)
            active = 'bottomRight' if col > 1 and row > 1 else 'topRight' if col > 1 else 'bottomLeft'
            attrs['activePane'] = active
            from lxml import etree
            etree.SubElement(view, ns + 'pane', **attrs)
            if col > 1 and row > 1:
                etree.SubElement(view, ns + 'selection', pane='topRight')
                etree.SubElement(view, ns + 'selection', pane='bottomLeft')
            etree.SubElement(view, ns + 'selection', pane=active, activeCell=cell, sqref=cell)
        else:
            from lxml import etree
            etree.SubElement(view, ns + 'selection', activeCell='A1', sqref='A1')
    try: ooxml.edit_xml(source, output, lambda path: grid_styles.sheet_part(path, sheet), edit)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'sheet': sheet, 'freeze_panes': cell, 'formula_cache_effect': 'preserved'}


def resize_grid(directory, base_revision, sheet, cell_range, target_range, column_width=None, row_height=None):
    for name, value, limit in (('column_width', column_width, 255), ('row_height', row_height, 409.5)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= limit or not math.isfinite(value)):
            raise ValueError(f'{name} must be greater than zero and at most {limit}')
    if column_width is None and row_height is None: raise ValueError('Provide a column width or row height')
    grid = read_grid(directory, base_revision, sheet, cell_range)
    if grid['sheet_protected']: raise ValueError('Grid sizing is unavailable for protected worksheets')
    c1, r1, c2, r2 = grid_bounds(cell_range); sc1, sr1, sc2, sr2 = grid_bounds(target_range)
    if not (c1 <= sc1 <= sc2 <= c2 and r1 <= sr1 <= sr2 <= r2): raise ValueError('Sizing range must be within the loaded range')
    state = info(directory); source = revision_file(state, base_revision)
    constraints = spreadsheet.worksheet_constraints(source, sheet, (sc1, sr1, sc2, sr2), column_width is not None, row_height is not None)
    if constraints['dimension_issues']: raise ValueError('Ambiguous worksheet dimensions: ' + ', '.join(constraints['dimension_issues']))
    if base_revision >= 999999: raise ValueError('Session revision limit reached')
    output = Path(state['directory']) / f'revision-{base_revision + 1:06d}.xlsx'
    try: spreadsheet.resize_dimensions(source, output, sheet, (sc1, sr1, sc2, sr2), column_width, row_height)
    except FileExistsError as exc: raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'sheet': sheet, 'target_range': target_range,
            'column_width': column_width, 'row_height': row_height, 'formula_cache_effect': 'preserved'}


def sheet_names(directory, base_revision):
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'xlsx':
        raise ValueError('Worksheet listing requires an XLSX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        names = workbook.sheetnames
    finally:
        workbook.close()
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, 'sheets': names}
