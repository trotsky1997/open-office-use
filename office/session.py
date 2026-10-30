"""Persistent local draft sessions with immutable, optimistic revisions."""
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries

import cell_text
import layout
import officecli_backend
import spreadsheet
import slides
import word

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
        candidate = Path(tmp) / ('document' + source.suffix)
        shutil.copyfile(source, candidate)
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


def inspect_layout(directory, revision):
    state = info(directory)
    source = revision_file(state, revision)
    if state['format'] != 'pptx':
        raise ValueError('Slide layout inspection requires a PPTX session')
    return {'revision': revision, **layout.inspect(source)}


def recalculate(directory, base_revision):
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
        spreadsheet.recalculate(source, output)
    except FileExistsError as exc:
        raise ValueError('Revision conflict: another edit committed first') from exc
    return {'revision': base_revision + 1, 'file': str(output), 'engine': 'LibreOffice'}


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


def edit_target(directory, base_revision, path):
    if not isinstance(path, str) or not path.startswith('/') or len(path) > 512 or '\x00' in path:
        raise ValueError('Provide a valid element path of at most 512 characters')
    state = info(directory)
    source = revision_file(state, base_revision)
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
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
        mode = 'value' if state['format'] == 'xlsx' else 'text'
        value = text or ''
    if len(value) > 4000:
        raise ValueError('Element value exceeds the 4,000-character editor limit')
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, 'path': item['path'], 'type': item['type'],
            'format': state['format'], 'mode': mode, 'value': value,
            'replace_text_path_supported': (state['format'] == 'docx' and item['type'] == 'paragraph' and word.paragraph_path(item['path'])) or (state['format'] == 'pptx' and item['type'] in {'paragraph', 'title', 'shape', 'textbox', 'placeholder', 'tc'} and slides.paragraph_path(item['path'])) or (state['format'] == 'xlsx' and mode == 'value' and format_data.get('type') in {'SharedString', 'InlineString'} and cell_text.cell_path(item['path']))}


def edit(directory, base_revision, path, mode, value):
    if not isinstance(value, str) or len(value) > 4000:
        raise ValueError('Value must be text of at most 4,000 characters')
    target = edit_target(directory, base_revision, path)
    if target['format'] == 'pptx' and target['type'] == 'tc':
        raise ValueError('Use text replacement to edit PowerPoint table cells')
    allowed = {'xlsx': {'value', 'formula'}, 'docx': {'text'}, 'pptx': {'text'}}
    if mode not in allowed[target['format']]:
        raise ValueError('Edit mode is not supported for this format')
    if mode == 'value' and value.lstrip().startswith('='):
        raise ValueError('Choose formula mode for a value starting with =')
    if mode == 'formula' and (not value.startswith('=') or len(value) < 2):
        raise ValueError('A formula must start with = and contain an expression')
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
    return {'revision': base_revision + 1, 'file': str(output), 'path': path}


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


def add_comment(directory, base_revision, path, text, author):
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
        result = word.add_comment(source, output, path, text, author)
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
    min_col, min_row, _, _ = grid_bounds(cell_range)
    state = info(directory)
    source = revision_file(state, base_revision)
    if state['format'] != 'xlsx':
        raise ValueError('Grid editing requires an XLSX session')
    if base_revision != state['latest_revision']:
        raise ValueError(f"Revision conflict: latest revision is {state['latest_revision']}")
    result = spreadsheet.read_range(source, sheet, cell_range, include_style=True)
    protected = spreadsheet.protected_formula_ranges(source, sheet)
    rows = []
    for row_index, row in enumerate(result['rows']):
        cells = []
        for col_index, cell in enumerate(row):
            col, row_number = min_col + col_index, min_row + row_index
            inside = any(c1 <= col <= c2 and r1 <= row_number <= r2 for c1, r1, c2, r2 in protected)
            cells.append({'cell': f'{get_column_letter(col)}{row_number}', **cell,
                          'editable': not inside and not isinstance(cell.get('formula'), dict)})
        rows.append(cells)
    latest = info(directory)['latest_revision']
    if base_revision != latest:
        raise ValueError(f'Revision conflict: latest revision is {latest}')
    return {'revision': base_revision, 'sheet': sheet, 'range': cell_range,
            'rows': rows, 'cache_freshness': 'unknown'}


def edit_grid(directory, base_revision, sheet, cell_range, changes):
    if not isinstance(changes, list) or not changes or len(changes) > 200:
        raise ValueError('Provide 1 to 200 changed cells')
    grid = read_grid(directory, base_revision, sheet, cell_range)
    min_col, min_row, max_col, max_row = grid_bounds(cell_range)
    original = {cell['cell']: cell for row in grid['rows'] for cell in row}
    seen, operations = set(), []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'cell', 'value'}:
            raise ValueError('Each change requires cell and value')
        address, value = change['cell'], change['value']
        match = re.fullmatch(r'([A-Za-z]{1,3})([1-9][0-9]{0,6})', address) if isinstance(address, str) else None
        if match is None:
            raise ValueError('Invalid cell address')
        col, row = column_index_from_string(match.group(1)), int(match.group(2))
        address = match.group(1).upper() + str(row)
        if not (min_col <= col <= max_col and min_row <= row <= max_row) or address in seen:
            raise ValueError('Cell is outside the range or repeated')
        if not original[address]['editable']:
            raise ValueError('Array, data-table or shared formula ranges are not supported by grid editing')
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError('Cell values must be text of at most 4,000 characters')
        if value.lstrip().startswith('=') and not value.startswith('='):
            raise ValueError('Formula expressions must begin with =')
        if value == '=':
            raise ValueError('A formula requires an expression')
        seen.add(address)
        mode = 'formula' if value.startswith('=') else 'value'
        operations.append({'command': 'set', 'path': f'/{sheet}/{address}', 'props': {mode: value}})
    return apply(directory, base_revision, operations)


def format_grid(directory, base_revision, sheet, cell_range, style_range, properties):
    if not isinstance(properties, dict) or not properties or not set(properties) <= {'bold', 'fill', 'numberformat'}:
        raise ValueError('Provide bold, fill and/or numberformat')
    props = {}
    if 'bold' in properties:
        if not isinstance(properties['bold'], bool):
            raise ValueError('Bold must be true or false')
        props['font.bold'] = str(properties['bold']).lower()
    if 'fill' in properties:
        if not isinstance(properties['fill'], str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', properties['fill']):
            raise ValueError('Fill must be a six-digit RGB color')
        props['fill'] = properties['fill']
    if 'numberformat' in properties:
        value = properties['numberformat']
        if not isinstance(value, str) or not value or len(value) > 120:
            raise ValueError('Number format must contain 1 to 120 characters')
        props['numberformat'] = value
    grid = read_grid(directory, base_revision, sheet, cell_range)
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
                if not cell['editable']:
                    raise ValueError('Array, data-table or shared formula ranges are not supported by grid formatting')
                operations.append({'command': 'set', 'path': f"/{sheet}/{cell['cell']}", 'props': props})
    return apply(directory, base_revision, operations)


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
