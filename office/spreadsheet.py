"""Bounded worksheet inspection and explicit LibreOffice recalculation."""
import os
import posixpath
import re
import json
import math
import shutil
import subprocess
import tempfile
import snapshot as snapshots
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.etree.ElementTree import tostring

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries


def inspect_workbook(file):
    """Return bounded sparse samples from a saved XLSX snapshot."""
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.xlsx': raise ValueError('Workbook inspection requires an XLSX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-workbook-inspect-') as tmp:
        snapshot = Path(tmp) / 'workbook.xlsx'; shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Workbook exceeds package limits or contains duplicate parts')
                workbook = load_workbook(snapshot, read_only=True, data_only=False, keep_links=False)
                try:
                    prepare_shared_strings(workbook, archive)
                    worksheets = workbook.worksheets; sheet_names = workbook.sheetnames; worksheet_names = {sheet.title for sheet in worksheets}
                    chart_names = [name for name in sheet_names if name not in worksheet_names]
                    results = []
                    # shortcut: inspect only the first 50 worksheets and first 100 populated cells per sheet; use targeted reads for the rest.
                    for sheet in worksheets[:50]:
                        path = getattr(sheet, '_worksheet_path', None)
                        if not isinstance(path, str) or path not in names: raise ValueError(f'Cannot locate worksheet XML: {sheet.title}')
                        strings = sheet._shared_strings; sample = []; scanned = 0; complete = True
                        with archive.open(path) as stream:
                            stack, sheet_data = [], None
                            for event, element in ET.iterparse(stream, events=('start', 'end')):
                                ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                                tag = element.tag[len(ns):] if isinstance(element.tag, str) and element.tag.startswith(ns) else ''
                                if event == 'start':
                                    if not stack and element.tag != '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet': raise ValueError(f'Invalid worksheet XML: {sheet.title}')
                                    if tag == 'sheetData' and stack[-1:] == ['worksheet']:
                                        if sheet_data is not None: raise ValueError(f'Worksheet has duplicate sheet data: {sheet.title}')
                                        sheet_data = element
                                    stack.append(tag); continue
                                if stack[-3:] == ['sheetData', 'row', 'c']:
                                    if scanned >= 10000: complete = False; break
                                    scanned += 1; parts = {child.tag[len(ns):]: child for child in element if isinstance(child.tag, str) and child.tag.startswith(ns)}
                                    formula, value, inline = parts.get('f'), parts.get('v'), parts.get('is')
                                    if formula is not None or value is not None and value.text is not None or inline is not None:
                                        if len(sample) >= 100: complete = False; break
                                        cell_type = element.get('t', 'n'); raw = value.text if value is not None else None
                                        text = None; text_complete = True
                                        if formula is not None:
                                            text = '=' + formula.text if formula.text else None
                                            if not formula.text: text_complete = None
                                        elif cell_type == 's':
                                            if raw is None or not raw.isdecimal() or len(raw) > 10 or int(raw) >= len(strings):
                                                raise ValueError(f'Invalid shared string index in {sheet.title}')
                                            text = strings[int(raw)]
                                            text_complete = not isinstance(text, UnverifiedSharedString)
                                        elif cell_type == 'inlineStr' and inline is not None:
                                            x = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                                            text = ''.join(node.text or '' for child in inline for node in ([child] if child.tag == x + 't' else child.findall(x + 't') if child.tag == x + 'r' else []))
                                            text_complete = all(child.tag == x + 't' or child.tag == x + 'r' and all(item.tag in (x + 't', x + 'rPr') for item in child) for child in inline)
                                        else: text = raw
                                        if text is not None and not isinstance(text, str): text = str(text)
                                        if text is not None and re.search(r'_x[0-9a-fA-F]{4}_', text): text_complete = False
                                        sample.append({'cell': element.get('r'), 'type': cell_type, 'formula_kind': formula.get('t', 'normal') if formula is not None else None,
                                                       'value': text[:500] if text is not None else None, 'value_truncated': text is not None and len(text) > 500, 'text_complete': text_complete})
                                    element.clear()
                                elif stack[-2:] == ['sheetData', 'row']:
                                    element.clear()
                                    if sheet_data is not None: sheet_data.remove(element)
                                stack.pop()
                        if sheet_data is None: raise ValueError(f'Worksheet has no sheet data: {sheet.title}')
                        results.append({'name': sheet.title, 'state': sheet.sheet_state, 'declared_max_row': sheet.max_row,
                                        'declared_max_column': sheet.max_column, 'cells': sample, 'stored_cells_scanned': scanned, 'sample_complete': complete})
                    return {'type': 'xlsx', 'sheets': results, 'total_worksheets': len(worksheets), 'worksheets_truncated': len(worksheets) > 50,
                            'chartsheet_names': chart_names[:50], 'chartsheets_truncated': len(chart_names) > 50,
                            'limits': {'worksheets': 50, 'cells_per_sheet': 100, 'stored_cells_scanned_per_sheet': 10000, 'characters_per_value': 500},
                            'dimension_note': 'Declared dimensions may be inaccurate; samples cover stored cells only.', 'formula_cache_freshness': 'unknown'}
                finally:
                    workbook.close()
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise ValueError(f'Invalid workbook package or worksheet XML: {exc}') from exc


def read_range(file, sheet, cell_range, include_style=False):
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.xlsx':
        raise ValueError('Worksheet reading requires an .xlsx file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-cell-read-') as tmp:
        snapshot = Path(tmp) / 'workbook.xlsx'; shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Workbook exceeds package limits or contains duplicate parts')
            return _read_range(snapshot, sheet, cell_range, include_style)
        except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
            raise ValueError('Invalid workbook package') from exc


def _read_range(file, sheet, cell_range, include_style=False):
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        if min_col is None or min_row is None or max_col is None or max_row is None:
            raise ValueError
        if (min_col < 1 or min_row < 1
                or max_col > 16384 or max_row > 1048576 or min_col > max_col or min_row > max_row
                or (max_col - min_col + 1) * (max_row - min_row + 1) > 10000):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Specify a valid rectangular cell range of at most 10,000 cells') from None
    formulas = load_workbook(file, read_only=True, data_only=False)
    values = None
    try:
        values = load_workbook(file, read_only=True, data_only=True)
        with zipfile.ZipFile(file) as archive:
            raw_strings = search_shared_strings(archive)
        prepare_shared_strings(formulas, raw_strings=raw_strings)
        prepare_shared_strings(values, raw_strings=raw_strings)
        if sheet not in formulas.sheetnames:
            raise ValueError(f'Worksheet not found: {sheet}')
        f_rows = formulas[sheet].iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
        v_rows = values[sheet].iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
        rows = []; size = 0
        for _ in range(max_row - min_row + 1):
            f_row = next(f_rows, ())
            v_row = next(v_rows, ())
            row = []
            for col in range(max_col - min_col + 1):
                f = f_row[col] if col < len(f_row) else None
                v = v_row[col] if col < len(v_row) else None
                if f is not None and f.data_type == 'f':
                    formula = f.value
                    if not isinstance(formula, str):
                        formula = {'text': getattr(formula, 'text', None), 'ref': getattr(formula, 'ref', None)}
                    row.append({'formula': formula, 'value': v.value if v else None, 'type': v.data_type if v else 'n'})
                else:
                    row.append({'value': f.value if f else None, 'type': f.data_type if f else 'n'})
                value = row[-1]['value']
                if isinstance(value, str):
                    row[-1]['text_complete'] = not isinstance(value, UnverifiedSharedString) and not re.search(r'_x[0-9a-fA-F]{4}_', value)
                size += len(json.dumps(row[-1], ensure_ascii=False, default=str))
                if size > 1000000: raise ValueError('Cell data exceeds the 1,000,000-character response limit; request a smaller range')
            if include_style:
                for index, cell in enumerate(row):
                    f = f_row[index] if index < len(f_row) else None
                    font, fill = getattr(f, 'font', None), getattr(f, 'fill', None)
                    color = getattr(fill, 'fgColor', None)
                    rgb = color.rgb if fill and fill.patternType == 'solid' and color and color.type == 'rgb' else None
                    if include_style == 'review':
                        # Style IDs are workbook-local, so compare resolved components instead.
                        style = formulas._cell_styles[getattr(f, '_style_id', 0)]
                        cell['format'] = {
                            name: tostring(collection[index].to_tree(), encoding='unicode')
                            for name, collection, index in (
                                ('font', formulas._fonts, style.fontId),
                                ('fill', formulas._fills, style.fillId),
                                ('border', formulas._borders, style.borderId),
                                ('alignment', formulas._alignments, style.alignmentId),
                                ('protection', formulas._protections, style.protectionId),
                            )
                        }
                        cell['format']['number_format'] = getattr(f, 'number_format', 'General')
                    else:
                        font_color = getattr(font, 'color', None)
                        font_rgb = font_color.rgb if font_color and font_color.type == 'rgb' else None
                        alignment = getattr(f, 'alignment', None)
                        cell['style'] = {'bold': bool(getattr(font, 'bold', False)), 'italic': bool(getattr(font, 'italic', False)),
                                         'underline': getattr(font, 'underline', None), 'font_name': getattr(font, 'name', None), 'font_size': getattr(font, 'sz', None),
                                         'font_color_rgb': font_rgb[-6:] if isinstance(font_rgb, str) else None,
                                         'fill_rgb': rgb[-6:] if isinstance(rgb, str) else None, 'number_format': getattr(f, 'number_format', 'General'),
                                         'horizontal': getattr(alignment, 'horizontal', None), 'vertical': getattr(alignment, 'vertical', None), 'wrap': getattr(alignment, 'wrap_text', None)}
                        cell['locked'] = getattr(getattr(f, 'protection', None), 'locked', True) is not False
                    size += len(json.dumps(cell.get('format', cell.get('style')), ensure_ascii=False, default=str))
                    if size > 1000000: raise ValueError('Cell data exceeds the 1,000,000-character response limit; request a smaller range')
            rows.append(row)
        return {'sheet': sheet, 'range': cell_range, 'rows': rows, 'cache_freshness': 'unknown'}
    finally:
        formulas.close()
        if values:
            values.close()


FORMULA_SCAN_MAX_CELLS = 1000000
FORMULA_SCAN_MAX_ISSUES = 200


def validate_cell_value(value):
    if isinstance(value, str) and re.search(r'_x[0-9a-fA-F]{4}_', value):
        raise ValueError('Cell text containing an Excel escape-like sequence is not supported by this editor')


class UnverifiedSharedString(str):
    """A shared value whose displayed text cannot be verified from the package."""


def search_shared_strings(archive):
    """Read verifiable plain and rich strings from the package's shared string table."""
    types_ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    main_ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    types = ET.fromstring(archive.read('[Content_Types].xml'))
    parts = [item.get('PartName', '').lstrip('/') for item in types.findall(types_ns + 'Override')
             if item.get('ContentType') == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml']
    if len(parts) != 1 or parts[0] not in archive.namelist(): return None
    strings = []
    with archive.open(parts[0]) as stream:
        root = None
        for event, node in ET.iterparse(stream, events=('start', 'end')):
            if root is None:
                root = node
                if root.tag != main_ns + 'sst': return None
            if event == 'end' and node.tag == main_ns + 'si':
                children = list(node); texts = []; valid = bool(children)
                plain = [child for child in children if child.tag == main_ns + 't']
                runs = [child for child in children if child.tag == main_ns + 'r']
                valid = valid and (len(plain) == 1 and len(children) == 1 or bool(runs) and len(runs) == len(children))
                for child in children:
                    if child.tag == main_ns + 't':
                        if len(child): valid = False
                        texts.append(child.text or '')
                    elif child.tag == main_ns + 'r':
                        run_text = child.findall(main_ns + 't')
                        if len(run_text) != 1 or len(child.findall(main_ns + 'rPr')) > 1 or any(len(item) for item in run_text) or any(item.tag not in (main_ns + 't', main_ns + 'rPr') for item in child): valid = False
                        texts.extend(item.text or '' for item in run_text)
                text = ''.join(texts)
                if re.search(r'_x[0-9a-fA-F]{4}_', text): valid = False
                strings.append((text, valid)); root.remove(node); node.clear()
    return strings


def prepare_shared_strings(workbook, archive=None, raw_strings=None):
    if archive is not None: raw_strings = search_shared_strings(archive)
    seen = set()
    for sheet in workbook.worksheets:
        strings = getattr(sheet, '_shared_strings', None)
        if not isinstance(strings, list) or id(strings) in seen: continue
        seen.add(id(strings))
        for index, value in enumerate(strings):
            if raw_strings is not None and len(raw_strings) == len(strings) and raw_strings[index][1]:
                strings[index] = raw_strings[index][0]
            else:
                strings[index] = UnverifiedSharedString(value)


def load_author_workbook(source):
    """Load an editable workbook without silently normalizing shared strings."""
    from openpyxl.reader.excel import ExcelReader

    source = Path(source)
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    class UnverifiedText(Exception): pass
    class Reader(ExcelReader):
        def read_strings(self):
            super().read_strings()
            if not self.shared_strings: return
            raw = search_shared_strings(self.archive)
            if raw is None or len(raw) != len(self.shared_strings) or any(not valid for _, valid in raw):
                raise UnverifiedText('Workbook contains unverified shared strings; use a targeted session edit')
            self.shared_strings = [text for text, _ in raw]
    reader = Reader(source)
    try:
        entries = reader.archive.infolist(); names = [entry.filename for entry in entries]
        if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
            raise ValueError('Workbook exceeds package limits or contains duplicate parts')
        try: reader.read()
        except UnverifiedText as exc: raise ValueError(str(exc)) from exc
        return reader.wb
    finally: reader.archive.close()


def search_cells(file, query, sheet=None, offset=0, snapshot_sha256=None):
    """Search stored worksheet text and formula text in a saved XLSX snapshot."""
    if not isinstance(query, str) or not query or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise ValueError('Search text must contain 1 to 200 characters without control characters')
    if sheet is not None and (not isinstance(sheet, str) or not sheet): raise ValueError('Sheet name must be nonempty text')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0: raise ValueError('Offset must be a nonnegative integer')
    if offset and snapshot_sha256 is None: raise ValueError('Continuing a search requires the prior snapshot SHA-256')
    if snapshot_sha256 is not None and (not isinstance(snapshot_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot_sha256)):
        raise ValueError('Invalid snapshot SHA-256')
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.xlsx': raise ValueError('Cell search requires an XLSX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-cell-search-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        if snapshot_sha256 is not None and digest != snapshot_sha256: raise ValueError('Workbook snapshot changed; restart the search')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Workbook exceeds package limits or contains duplicate parts')
                workbook = load_workbook(snapshot, read_only=True, data_only=False, keep_links=False)
                try:
                    sheets = [(s.title, s.sheet_state, s._worksheet_path, s._shared_strings) for s in workbook.worksheets]
                    raw_strings = search_shared_strings(archive)
                    chartsheets = len(workbook.sheetnames) - len(sheets)
                    total_worksheets = len(sheets)
                    if sheet is not None:
                        sheets = [s for s in sheets if s[0] == sheet]
                        if not sheets: raise ValueError('Worksheet not found')
                    matches, scanned, unverified, scanned_sheets = [], 0, 0, []
                    complete = True; skipped = 0; stop_reason = None
                    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    for name, state, path, strings in sheets:
                        if path not in names: raise ValueError(f'Cannot locate worksheet XML: {name}')
                        with archive.open(path) as stream:
                            stack, sheet_data = [], None
                            for event, element in ET.iterparse(stream, events=('start', 'end')):
                                tag = element.tag[len(ns):] if isinstance(element.tag, str) and element.tag.startswith(ns) else ''
                                if event == 'start':
                                    if not stack and element.tag != ns + 'worksheet': raise ValueError(f'Invalid worksheet XML: {name}')
                                    if tag == 'sheetData' and stack[-1:] == ['worksheet']:
                                        if sheet_data is not None: raise ValueError(f'Duplicate worksheet data: {name}')
                                        sheet_data = element
                                    stack.append(tag); continue
                                if stack[-3:] == ['sheetData', 'row', 'c']:
                                    if skipped < offset:
                                        skipped += 1; element.clear(); stack.pop(); continue
                                    if scanned >= 100000 or len(matches) >= 200:
                                        complete = False; stop_reason = 'match_limit' if len(matches) >= 200 else 'cell_limit'; break
                                    scanned += 1; children = {child.tag: child for child in element}
                                    formula, value, inline = children.get(ns + 'f'), children.get(ns + 'v'), children.get(ns + 'is')
                                    kind, text, uncertain = None, None, False
                                    if formula is not None:
                                        kind = 'formula'; text = '=' + formula.text if formula.text else None
                                        uncertain = text is None
                                    elif element.get('t') == 's':
                                        raw = value.text if value is not None else None
                                        if raw is None or not raw.isdecimal() or len(raw) > 10 or int(raw) >= len(strings): raise ValueError(f'Invalid shared string index in {name}')
                                        index = int(raw); kind, text, uncertain = 'text', strings[index], True
                                        if raw_strings is not None and len(raw_strings) == len(strings) and raw_strings[index][1]:
                                            text, uncertain = raw_strings[index][0], False
                                    elif element.get('t') == 'inlineStr' and inline is not None:
                                        kind = 'text'; text = ''.join(node.text or '' for child in inline for node in ([child] if child.tag == ns + 't' else child.findall(ns + 't') if child.tag == ns + 'r' else []))
                                        uncertain = any(child.tag not in (ns + 't', ns + 'r') or child.tag == ns + 'r' and any(item.tag not in (ns + 't', ns + 'rPr') for item in child) for child in inline)
                                    elif element.get('t') == 'inlineStr':
                                        uncertain = True
                                    elif element.get('t') == 'str' and value is not None:
                                        kind, text = 'text', value.text or ''
                                    if text is not None and (re.search(r'_x[0-9a-fA-F]{4}_', text) or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', element.get('r', ''))): uncertain = True
                                    if uncertain: unverified += 1
                                    if text is not None and query in text:
                                        index = text.index(query); start = max(0, index - 100); end = min(len(text), index + len(query) + 100)
                                        matches.append({'sheet': name, 'sheet_state': state, 'cell': element.get('r'), 'kind': kind,
                                                        'excerpt': text[start:end], 'excerpt_start': start, 'text_length': len(text), 'text_complete': not uncertain})
                                    element.clear()
                                elif stack[-2:] == ['sheetData', 'row']:
                                    element.clear()
                                    if sheet_data is not None: sheet_data.remove(element)
                                stack.pop()
                            if sheet_data is None: raise ValueError(f'Worksheet has no sheet data: {name}')
                        scanned_sheets.append({'sheet': name, 'complete': complete})
                        if not complete: break
                    if skipped < offset: raise ValueError('Search offset exceeds the selected worksheets')
                    return {'query': query, 'sheet': sheet, 'case_sensitive': True, 'snapshot_sha256': digest,
                            'offset': offset, 'cells_skipped': skipped, 'next_offset': offset + scanned if not complete else None,
                            'stop_reason': stop_reason, 'matches': matches, 'match_count': len(matches),
                            'matches_truncated': stop_reason == 'match_limit', 'stored_cells_scanned': scanned,
                            'sheets': scanned_sheets, 'total_worksheets': total_worksheets, 'chartsheets_omitted': chartsheets,
                            'complete': complete and offset == 0 and unverified == 0, 'scan_complete': complete, 'unverified_text_cells': unverified,
                            'limits': {'stored_cells': 100000, 'matches': 200},
                            'notes': ['Counts and completeness apply to this page; continue with the same query and sheet.',
                                      'Search covers stored text and formula text, not calculated values or chart content.',
                                      'Complex shared strings, shared formula followers and Excel escape sequences may be unverified.']}
                finally: workbook.close()
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise ValueError(f'Invalid workbook package or worksheet XML: {exc}') from exc


def scan_formulas(file):
    """Inspect stored formula caches and error cells across saved worksheets."""
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.xlsx':
        raise ValueError('Formula scanning requires an .xlsx file')
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Workbook exceeds the 128 MiB scan limit')
    with tempfile.TemporaryDirectory(prefix='office-formulas-') as tmp:
        snapshot = Path(tmp) / 'workbook.xlsx'
        shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('Workbook exceeds the 128 MiB scan limit')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Workbook exceeds package limits or contains duplicate parts')
                try: _, workbook_mode = workbook_calculation(archive); workbook_mode_issue = None
                except Exception as exc: workbook_mode = None; workbook_mode_issue = f'{type(exc).__name__}: {str(exc)[:300]}'
                try: dynamic_arrays = dynamic_array_metadata(archive); dynamic_issue = None
                except Exception as exc: dynamic_arrays = None; dynamic_issue = f'{type(exc).__name__}: {str(exc)[:300]}'
                workbook = load_workbook(snapshot, read_only=True, data_only=False, keep_links=False)
                try:
                    sheets = [(sheet.title, getattr(sheet, '_worksheet_path', None)) for sheet in workbook.worksheets]
                finally:
                    workbook.close()
                counts = {'scanned_cells': 0, 'formulas': 0, 'formula_errors': 0,
                          'literal_errors': 0, 'empty_or_missing_cache': 0}
                errors, missing, scanned_sheets = [], [], []
                complete = True
                for name, path in sheets:
                    if not isinstance(path, str) or path not in names:
                        raise ValueError(f'Cannot locate worksheet XML: {name}')
                    sheet_complete = True; calculation_seen = False; calculation_value = None; calculation_issue = None
                    with archive.open(path) as stream:
                        stack, sheet_data, data_seen = [], None, False
                        for event, element in ET.iterparse(stream, events=('start', 'end')):
                            tag = element.tag.rsplit('}', 1)[-1]
                            if event == 'start':
                                if tag == 'sheetData' and stack[-1:] == ['worksheet']:
                                    sheet_data = element; data_seen = True
                                stack.append(tag)
                                continue
                            if element.tag == '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetCalcPr' and stack != ['worksheet', 'sheetCalcPr']:
                                calculation_issue = 'nested_sheet_calculation_properties'
                            if stack == ['worksheet', 'sheetCalcPr'] and element.tag == '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetCalcPr':
                                if not data_seen: calculation_issue = 'out_of_order_sheet_calculation_properties'
                                if calculation_seen: calculation_issue = 'duplicate_sheet_calculation_properties'; calculation_value = None
                                else:
                                    calculation_seen = True; value = element.get('fullCalcOnLoad')
                                    if value in ('1', 'true'): calculation_value = True
                                    elif value in ('0', 'false'): calculation_value = False
                                    elif value is not None: calculation_issue = 'invalid_sheet_calculation_flag'
                            if stack[-3:] == ['sheetData', 'row', 'c']:
                                if counts['scanned_cells'] >= FORMULA_SCAN_MAX_CELLS:
                                    sheet_complete = complete = False
                                    break
                                counts['scanned_cells'] += 1
                                children = {child.tag.rsplit('}', 1)[-1]: child for child in element}
                                formula, value = children.get('f'), children.get('v')
                                is_formula = formula is not None
                                cached = value.text if value is not None else None
                                if is_formula:
                                    counts['formulas'] += 1
                                if element.get('t') == 'e':
                                    kind = 'formula_errors' if is_formula else 'literal_errors'
                                    counts[kind] += 1
                                    if len(errors) < FORMULA_SCAN_MAX_ISSUES:
                                        errors.append({'sheet': name, 'cell': element.get('r'), 'kind': kind,
                                                       'error': (cached or '')[:256], 'formula': (formula.text or '')[:500] if is_formula else None})
                                elif is_formula and (cached is None or cached == ''):
                                    counts['empty_or_missing_cache'] += 1
                                    if len(missing) < FORMULA_SCAN_MAX_ISSUES:
                                        missing.append({'sheet': name, 'cell': element.get('r'), 'formula': (formula.text or '')[:500]})
                                element.clear()
                            elif stack[-2:] == ['sheetData', 'row']:
                                element.clear()
                                if sheet_data is not None:
                                    sheet_data.remove(element)
                            stack.pop()
                    scanned_sheets.append({'sheet': name, 'complete': sheet_complete, 'recalculation_requested': calculation_value if sheet_complete and not calculation_issue else None,
                                           'calculation_metadata_complete': sheet_complete and not calculation_issue, 'calculation_metadata_issue': calculation_issue})
                    if not complete:
                        break
                return {**counts, 'sheets': scanned_sheets, 'total_sheets': len(sheets), 'complete': complete,
                        'errors': errors, 'errors_truncated': counts['formula_errors'] + counts['literal_errors'] > len(errors),
                        'empty_or_missing': missing, 'empty_or_missing_truncated': counts['empty_or_missing_cache'] > len(missing),
                        'cache_freshness': 'unknown', 'dynamic_array_metadata': dynamic_arrays, 'dynamic_array_metadata_issue': dynamic_issue, 'recalculation_requests': sum(item['recalculation_requested'] is True for item in scanned_sheets),
                        'workbook_calculation_mode': workbook_mode, 'workbook_calculation_metadata_issue': workbook_mode_issue,
                        'calculation_metadata_complete': complete and not workbook_mode_issue and all(item['calculation_metadata_complete'] for item in scanned_sheets)}
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise ValueError(f'Invalid workbook package or worksheet XML: {exc}') from exc



def workbook_calculation(archive):
    """Locate the XLSX workbook part and its explicitly stored calculation mode."""
    import ooxml
    ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    root = ooxml.parse_xml(archive.read('[Content_Types].xml')).getroot()
    if root.tag != ns + 'Types': raise ValueError('Invalid package content types')
    kind = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
    matches = [item.get('PartName', '').lstrip('/') for item in root.findall(ns + 'Override') if item.get('ContentType') == kind]
    if not matches and any(item.get('Extension', '').lower() == 'xml' and item.get('ContentType') == kind for item in root.findall(ns + 'Default')):
        matches = ['xl/workbook.xml']
    if len(matches) != 1 or not matches[0] or '..' in matches[0].split('/') or matches[0] not in archive.namelist():
        raise ValueError('Workbook part is missing or ambiguous')
    path = matches[0]; tree = ooxml.parse_xml(archive.read(path)); x = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    if tree.getroot().tag != x + 'workbook': raise ValueError('Invalid workbook XML')
    props = tree.getroot().findall(x + 'calcPr')
    if len(props) > 1 or len(list(tree.getroot().iter(x + 'calcPr'))) != len(props): raise ValueError('Ambiguous workbook calculation properties')
    mode = props[0].get('calcMode') if props else None
    if mode not in (None, 'auto', 'autoNoTable', 'manual'): raise ValueError('Invalid workbook calculation mode')
    return path, mode


def dynamic_array_metadata(archive):
    """Check the workbook's sheet metadata for dynamic-array markers."""
    import ooxml
    ct = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    x = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    xda = '{http://schemas.microsoft.com/office/spreadsheetml/2017/dynamicarray}'
    content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheetMetadata+xml'
    relationship_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/sheetMetadata'
    workbook, _ = workbook_calculation(archive)
    manifest = ooxml.parse_xml(archive.read('[Content_Types].xml')).getroot()
    if any(item.get('ContentType') == content_type for item in manifest.findall(ct + 'Default')): raise ValueError('Unsupported default sheet metadata type')
    overrides = [item for item in manifest.findall(ct + 'Override') if item.get('ContentType', '').endswith('.sheetMetadata+xml')]
    rel_path = posixpath.join(posixpath.dirname(workbook), '_rels', posixpath.basename(workbook) + '.rels')
    if rel_path not in archive.namelist(): raise ValueError('Workbook relationships are missing')
    rels = ooxml.parse_xml(archive.read(rel_path)).getroot()
    if rels.tag != rel + 'Relationships': raise ValueError('Invalid workbook relationships')
    relationships = [item for item in rels.findall(rel + 'Relationship') if item.get('Type', '').endswith('/sheetMetadata')]
    if not relationships and not overrides: return False
    if len(relationships) != 1 or len(overrides) != 1 or relationships[0].get('Type') != relationship_type or overrides[0].get('ContentType') != content_type:
        raise ValueError('Sheet metadata is ambiguous')
    item = relationships[0]; target = item.get('Target', '')
    if item.get('TargetMode', 'Internal') != 'Internal' or not target or any(c in target for c in ('%', '?', '#', '\\', ':')):
        raise ValueError('Sheet metadata target is unsupported')
    part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(workbook), target))
    if not part or part.startswith('../') or part not in archive.namelist() or overrides[0].get('PartName') != '/' + part:
        raise ValueError('Sheet metadata part is missing or ambiguous')
    if len([item for item in manifest.findall(ct + 'Override') if item.get('PartName') == '/' + part]) != 1: raise ValueError('Sheet metadata type is ambiguous')
    root = ooxml.parse_xml(archive.read(part)).getroot()
    if root.tag != x + 'metadata': raise ValueError('Invalid sheet metadata')
    return any(item.get('name') == 'XLDAPR' for item in root.iter() if item.tag in (x + 'metadataType', x + 'futureMetadata')) or any(True for _ in root.iter(xda + 'dynamicArrayProperties'))


def render_advisory(source):
    """Report dynamic-array metadata that may affect LibreOffice previews."""
    source = Path(source)
    if source.suffix.lower() != '.xlsx': return None
    try:
        if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Workbook exceeds package limits or contains duplicate parts')
            dynamic = dynamic_array_metadata(archive)
        return {'dynamic_array_metadata': dynamic, 'issue': None}
    except Exception as exc:
        return {'dynamic_array_metadata': None, 'issue': f'{type(exc).__name__}: {str(exc)[:300]}'}

def recalculate(source, output, allow_dynamic_arrays=False):
    if not isinstance(allow_dynamic_arrays, bool): raise ValueError('allow_dynamic_arrays must be a boolean')
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx':
        raise ValueError('Recalculation requires .xlsx input and output')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    executable = shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('LibreOffice (soffice) is required for recalculation')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-calc-') as tmp:
        root = Path(tmp)
        inputs = root / 'input'; inputs.mkdir()
        results = root / 'result'; results.mkdir()
        copy = inputs / 'workbook.xlsx'
        shutil.copyfile(source, copy)
        if copy.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
        with zipfile.ZipFile(copy) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(set(names)) != len(names) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Workbook exceeds package limits or contains duplicate parts')
            if any(name.startswith('_xmlsignatures/') for name in names): raise ValueError('Digitally signed workbooks cannot be recalculated')
            _, original_mode = workbook_calculation(archive)
            import ooxml
            try: dynamic = dynamic_array_metadata(archive)
            except (ValueError, KeyError, ooxml.etree.XMLSyntaxError) as exc:
                if not allow_dynamic_arrays: raise ValueError(f'Cannot inspect dynamic-array metadata: {exc}; explicitly allow dynamic arrays to continue') from exc
            else:
                if dynamic and not allow_dynamic_arrays: raise ValueError('Dynamic-array metadata detected; LibreOffice may not preserve spill results. Explicitly allow dynamic arrays to continue')
        # A fresh default profile can reuse stale OOXML caches, including in manual mode.
        profile_path = root / 'profile'; user_profile = profile_path / 'user'; user_profile.mkdir(parents=True)
        (user_profile / 'registrymodifications.xcu').write_text(
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
            '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop>'
            '</item></oor:items>', encoding='utf-8')
        profile = profile_path.as_uri()
        result = subprocess.run([executable, '-env:UserInstallation=' + profile, '--headless',
                                 '--convert-to', 'xlsx', '--outdir', str(results), str(copy)],
                                capture_output=True, text=True, timeout=120, check=False)
        candidate = results / copy.name
        if result.returncode or not candidate.is_file():
            raise RuntimeError(f'LibreOffice recalculation failed: {result.stderr or result.stdout}')
        if candidate.stat().st_size > 128 * 1024 * 1024: raise ValueError('Recalculated workbook exceeds the 128 MiB size limit')
        with zipfile.ZipFile(candidate) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(set(names)) != len(names) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Recalculated workbook exceeds package limits or contains duplicate parts')
            workbook_part, result_mode = workbook_calculation(archive)
        check = load_workbook(candidate, read_only=True, data_only=False)
        check.close()
        if result_mode != original_mode:
            import ooxml
            x = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
            adjusted = root / 'adjusted.xlsx'
            def restore_mode(tree, archive):
                document = tree.getroot(); nodes = document.findall(x + 'calcPr')
                if len(nodes) > 1 or len(list(document.iter(x + 'calcPr'))) != len(nodes): raise ValueError('Ambiguous calculation properties')
                if nodes: node = nodes[0]
                else:
                    node = ooxml.etree.Element(x + 'calcPr')
                    following = {x + name for name in ('oleSize', 'customWorkbookViews', 'pivotCaches', 'smartTagPr', 'smartTagTypes', 'webPublishing', 'fileRecoveryPr', 'webPublishObjects', 'extLst')}
                    successor = next((child for child in document if child.tag in following), None)
                    if successor is None: document.append(node)
                    else: document.insert(document.index(successor), node)
                if original_mode is None: node.attrib.pop('calcMode', None)
                else: node.set('calcMode', original_mode)
            ooxml.edit_xml(candidate, adjusted, lambda _: workbook_part, restore_mode)
            candidate = adjusted
        os.link(candidate, output)
    return str(output)


def worksheet_constraints(file, sheet, dimension_bounds=None, check_columns=False, check_rows=False):
    """Inspect multi-cell formulas, merged ranges and sheet protection without rewriting."""
    import xml.etree.ElementTree as ET
    import zipfile

    if Path(file).stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    with zipfile.ZipFile(file) as archive:
        entries = archive.infolist(); names = [entry.filename for entry in entries]
        if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
            raise ValueError('Workbook exceeds package limits or contains duplicate parts')
    workbook = load_workbook(file, read_only=True, data_only=False)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f'Worksheet not found: {sheet}')
        # openpyxl resolves workbook relationships to this package-relative path.
        path = getattr(workbook[sheet], '_worksheet_path', None)
        if not isinstance(path, str):
            raise RuntimeError('Cannot locate worksheet XML for formula protection')
        if sum(getattr(item, '_worksheet_path', None) == path for item in workbook.worksheets) != 1:
            raise ValueError('Worksheet part is referenced by multiple sheets')
    finally:
        workbook.close()
    ranges = []; merges = []; sheet_protected = False; protection_seen = False
    shared_ranges, shared_uses = {}, set()
    seen_columns, seen_rows, dimension_issues = set(), set(), set()
    dimensions = {'columns': {}, 'rows': {}, 'defaults': {}}; defaults_seen = False
    def dimension_attrs(element, names):
        attrs = {}
        for key in names:
            value = element.get(key)
            if value is not None:
                if len(value) > 64: dimension_issues.add('oversized_dimension_attribute'); continue
                if key in ('width', 'ht', 'defaultColWidth', 'baseColWidth', 'defaultRowHeight'):
                    try:
                        number = float(value)
                        if not math.isfinite(number) or number < 0: raise ValueError
                    except ValueError: dimension_issues.add('invalid_dimension_attribute')
                if key in ('customWidth', 'customHeight', 'hidden', 'bestFit', 'collapsed', 'zeroHeight') and value not in ('0', '1', 'false', 'true'):
                    dimension_issues.add('invalid_dimension_attribute')
                if key == 'outlineLevel' and (not value.isdecimal() or len(value) > 1 or int(value) > 7):
                    dimension_issues.add('invalid_dimension_attribute')
                attrs[key] = value
        return attrs
    with zipfile.ZipFile(file) as archive, archive.open(path) as stream:
        for _, element in ET.iterparse(stream, events=('end',)):
            tag = element.tag.rsplit('}', 1)[-1]
            if dimension_bounds is not None and tag == 'sheetFormatPr':
                if defaults_seen: dimension_issues.add('duplicate_sheet_defaults')
                defaults_seen = True
                dimensions['defaults'] = dimension_attrs(element, ('defaultColWidth', 'baseColWidth', 'defaultRowHeight', 'zeroHeight'))
            if dimension_bounds is not None and tag == 'col' and check_columns:
                try:
                    first, last = int(element.get('min')), int(element.get('max'))
                    if not 1 <= first <= last <= 16384: raise ValueError
                    c1, _, c2, _ = dimension_bounds
                    for col in range(max(first, c1), min(last, c2) + 1):
                        if col in seen_columns: dimension_issues.add('overlapping_column_ranges')
                        seen_columns.add(col)
                        dimensions['columns'][get_column_letter(col)] = dimension_attrs(element, ('min', 'max', 'width', 'customWidth', 'hidden', 'bestFit', 'outlineLevel', 'collapsed'))
                except (ValueError, TypeError): dimension_issues.add('invalid_column_range')
            if dimension_bounds is not None and tag == 'row' and check_rows:
                try:
                    number = int(element.get('r'))
                    if not 1 <= number <= 1048576: raise ValueError
                    _, r1, _, r2 = dimension_bounds
                    if r1 <= number <= r2:
                        if number in seen_rows: dimension_issues.add('duplicate_row')
                        seen_rows.add(number)
                        dimensions['rows'][str(number)] = dimension_attrs(element, ('ht', 'customHeight', 'hidden', 'outlineLevel', 'collapsed'))
                except (ValueError, TypeError): dimension_issues.add('invalid_row_index')
            if element.tag == '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell':
                try:
                    bounds = range_boundaries(element.get('ref'))
                    if any(v is None for v in bounds) or not (1 <= bounds[0] <= bounds[2] <= 16384 and 1 <= bounds[1] <= bounds[3] <= 1048576): raise ValueError
                except (TypeError, ValueError):
                    raise ValueError('Invalid merged-cell range') from None
                merges.append(bounds)
            elif element.tag == '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetProtection':
                if protection_seen: raise ValueError('Worksheet has duplicate protection settings')
                protection_seen = True; flag = element.get('sheet', '0')
                if flag not in ('0', '1', 'true', 'false'): raise ValueError('Invalid worksheet protection setting')
                sheet_protected = flag in ('1', 'true')
            if element.tag.rsplit('}', 1)[-1] == 'f':
                kind, ref, shared_id = element.get('t'), element.get('ref'), element.get('si')
                if kind == 'shared':
                    if shared_id is None:
                        raise ValueError('Shared formula has no identifier')
                    shared_uses.add(shared_id)
                if kind in ('array', 'dataTable', 'shared') and ref:
                    try:
                        bounds = range_boundaries(ref)
                        if any(value is None for value in bounds) or not (1 <= bounds[0] <= bounds[2] <= 16384 and 1 <= bounds[1] <= bounds[3] <= 1048576):
                            raise ValueError
                    except (TypeError, ValueError):
                        raise ValueError('Invalid multi-cell formula range') from None
                    if kind == 'shared':
                        assert shared_id is not None
                        if shared_id in shared_ranges and shared_ranges[shared_id] != bounds:
                            raise ValueError('Conflicting shared formula ranges')
                        shared_ranges[shared_id] = bounds
                    ranges.append(bounds)
                elif kind in ('array', 'dataTable') and not ref:
                    raise ValueError('Multi-cell formula has no protected range')
            element.clear()
    if shared_uses - shared_ranges.keys():
        raise ValueError('Shared formula has no protected range')
    dimensions['issues'] = sorted(dimension_issues)
    return {'formula_ranges': ranges, 'merged_ranges': merges, 'sheet_protected': sheet_protected, 'dimension_issues': dimensions['issues'], 'dimensions': dimensions}



def resize_dimensions(source, output, sheet, bounds, column_width, row_height):
    """Modify worksheet dimensions without rewriting formula cells or other package parts."""
    import copy
    from lxml import etree
    import ooxml
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    c1, r1, c2, r2 = bounds

    def select_part(file):
        workbook = load_workbook(file, read_only=True, data_only=False)
        try:
            if sheet not in workbook.sheetnames: raise ValueError('Worksheet not found')
            path = getattr(workbook[sheet], '_worksheet_path', None)
            if not isinstance(path, str) or sum(getattr(item, '_worksheet_path', None) == path for item in workbook.worksheets) != 1:
                raise ValueError('Worksheet part is unavailable or shared')
            return path
        finally: workbook.close()

    def edit(tree, archive):
        root = tree.getroot()
        if root.tag != ns + 'worksheet': raise ValueError('Worksheet has an invalid root')
        sheets = root.findall(ns + 'sheetData'); containers = root.findall(ns + 'cols')
        if len(sheets) != 1 or len(containers) > 1 or len(list(root.iter(ns + 'sheetData'))) != 1 or len(list(root.iter(ns + 'cols'))) != len(containers):
            raise ValueError('Worksheet has ambiguous dimension containers')
        data = sheets[0]
        if containers and root.index(containers[0]) > root.index(data): raise ValueError('Worksheet columns appear after sheet data')
        if column_width is not None:
            cols = containers[0] if containers else etree.Element(ns + 'cols')
            segments = []; covered = set(); previous = 0
            for node in cols:
                if node.tag != ns + 'col' or len(node) or (node.text and node.text.strip()): raise ValueError('Unsupported column structure')
                try:
                    first, last = int(node.get('min')), int(node.get('max'))
                    if not 1 <= first <= last <= 16384 or first <= previous: raise ValueError
                except (TypeError, ValueError): raise ValueError('Ambiguous or unordered column ranges') from None
                previous = last
                cuts = sorted({first, last + 1, max(first, min(last + 1, c1)), max(first, min(last + 1, c2 + 1))})
                for start, stop in zip(cuts, cuts[1:]):
                    part = copy.deepcopy(node); part.set('min', str(start)); part.set('max', str(stop - 1))
                    if c1 <= start <= c2:
                        part.set('width', str(column_width)); part.set('customWidth', '1'); covered.update(range(start, stop))
                    segments.append(part)
            for column in range(c1, c2 + 1):
                if column not in covered:
                    segments.append(etree.Element(ns + 'col', min=str(column), max=str(column), width=str(column_width), customWidth='1'))
            segments.sort(key=lambda item: int(item.get('min')))
            cols[:] = segments
            if not containers: root.insert(root.index(data), cols)
        if row_height is not None:
            rows = []; existing = set(); previous = 0
            for node in data:
                if node.tag != ns + 'row': raise ValueError('Unsupported sheet data structure')
                raw = node.get('r', '')
                if not re.fullmatch(r'[0-9]{1,7}', raw): raise ValueError('Invalid row index')
                number = int(raw)
                if not 1 <= number <= 1048576 or number <= previous: raise ValueError('Duplicate or unordered rows')
                previous = number; existing.add(number)
                if r1 <= number <= r2: node.set('ht', str(row_height)); node.set('customHeight', '1')
                rows.append((number, node))
            for number in range(r1, r2 + 1):
                if number not in existing: rows.append((number, etree.Element(ns + 'row', r=str(number), ht=str(row_height), customHeight='1')))
            rows.sort(key=lambda item: item[0]); data[:] = [node for _, node in rows]
    return ooxml.edit_xml(source, output, select_part, edit)

def cell_constraint(constraints, col, row, locked, complex_formula=False):
    ranges = [bounds for bounds in constraints['merged_ranges'] if bounds[0] <= col <= bounds[2] and bounds[1] <= row <= bounds[3]]
    from openpyxl.utils.cell import get_column_letter
    anchor = f'{get_column_letter(ranges[0][0])}{ranges[0][1]}' if len(ranges) == 1 else None
    reason = ('overlapping_merges' if len(ranges) > 1 else
              'merged_placeholder' if ranges and (col, row) != ranges[0][:2] else
              'formula_range' if complex_formula or any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in constraints['formula_ranges']) else
              'locked_cell' if constraints['sheet_protected'] and locked else None)
    return reason, anchor
