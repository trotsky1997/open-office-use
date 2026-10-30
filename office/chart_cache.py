"""Compare bounded chart caches with stored worksheet values in an XLSX snapshot."""
import math
import re
import shutil
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries
from lxml import etree

import ooxml
import spreadsheet

C = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
CHART_TYPE = 'application/vnd.openxmlformats-officedocument.drawingml.chart+xml'
CHARTEX_TYPE = 'application/vnd.ms-office.chartex+xml'
REFERENCE = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})(?::(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}))?\Z")
ESCAPED = re.compile(r'_x[0-9a-fA-F]{4}_')
REF_TYPES = (C+'numRef', C+'strRef', C+'multiLvlStrRef', C+'numLit', C+'strLit')


def parse_reference(formula):
    match = REFERENCE.fullmatch(formula or '')
    if not match: return None
    sheet = match.group(1).replace("''", "'") if match.group(1) is not None else match.group(2)
    if '[' in sheet or ']' in sheet: return None
    ref = match.group(3) + (':' + match.group(4) if match.group(4) else '')
    try: c1, r1, c2, r2 = range_boundaries(ref)
    except ValueError: return None
    if not (1 <= c1 <= c2 <= 16384 and 1 <= r1 <= r2 <= 1048576) or (c1 != c2 and r1 != r2): return None
    return sheet, c1, r1, c2, r2


TEMPORAL = (date, datetime, time, timedelta)


def worksheet_numeric_values(archive, sheet):
    """Return exact numeric XML values for a bounded worksheet, or no coverage."""
    path = getattr(sheet, '_worksheet_path', None)
    if not isinstance(path, str) or path not in archive.namelist() or archive.getinfo(path).file_size > 8 * 1024 * 1024: return {}
    root = ooxml.parse_xml(archive.read(path)).getroot(); ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    data = root.findall(ns+'sheetData')
    if root.tag != ns+'worksheet' or len(data) != 1 or len(list(root.iter(ns+'sheetData'))) != 1: return {}
    values = {}; seen = set()
    for row in data[0].findall(ns+'row'):
        row_number = row.get('r', '')
        if not re.fullmatch(r'[1-9][0-9]{0,6}', row_number) or int(row_number) > 1048576: return {}
        for cell in row.findall(ns+'c'):
            address = cell.get('r', '')
            match = re.fullmatch(r'[A-Z]{1,3}([1-9][0-9]{0,6})', address)
            if not match or match[1] != row_number: return {}
            if address in seen: values.pop(address, None); continue
            seen.add(address)
            if cell.get('t') not in (None, 'n'): continue
            nodes = cell.findall(ns+'v')
            if len(nodes) != 1 or len(nodes[0]): continue
            raw = nodes[0].text or ''
            if len(raw) > 256: continue
            try:
                if Decimal(raw).is_finite(): values[address] = raw
            except InvalidOperation: pass
    return values


def scan(file):
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.xlsx': raise ValueError('Chart cache inspection requires an XLSX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-chart-cache-') as tmp:
        snapshot = Path(tmp) / 'workbook.xlsx'; shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [item.filename for item in entries]
                if len(entries) > 5000 or len(set(names)) != len(names) or sum(item.file_size for item in entries) > 128 * 1024 * 1024:
                    raise ValueError('Workbook exceeds package limits or contains duplicate parts')
                manifest = ooxml.parse_xml(archive.read('[Content_Types].xml')).getroot()
                if manifest.tag != CT + 'Types': raise ValueError('Invalid content type manifest')
                chart_parts = []
                for item in manifest.findall(CT + 'Override'):
                    kind = item.get('ContentType'); name = item.get('PartName', '')
                    if kind not in (CHART_TYPE, CHARTEX_TYPE): continue
                    if not name.startswith('/') or '..' in name.split('/') or name[1:] not in names:
                        raise ValueError('Invalid chart part declaration')
                    chart_parts.append((name[1:], kind))
                if len({name for name, _ in chart_parts}) != len(chart_parts): raise ValueError('Duplicate chart part declaration')
                workbook = load_workbook(snapshot, read_only=True, data_only=True, keep_links=False)
                try:
                    spreadsheet.prepare_shared_strings(workbook, archive)
                    sheets = {sheet.title: sheet for sheet in workbook.worksheets}; results = []; complete = True; points_read = 0; limit_hit = False; constraints = {}; raw_values = {}
                    # shortcut: inspect 50 chart parts, 100 references and 10,000 source cells; split or inspect larger workbooks separately.
                    for part, kind in chart_parts[:50]:
                        if kind != CHART_TYPE or archive.getinfo(part).file_size > 4 * 1024 * 1024:
                            results.append({'part': part, 'status': 'unsupported_chart', 'references': []}); complete = False; continue
                        chart = ooxml.parse_xml(archive.read(part)).getroot()
                        if chart.tag != C + 'chartSpace':
                            results.append({'part': part, 'status': 'unsupported_chart', 'references': []}); complete = False; continue
                        external_data = chart.find('.//' + C + 'externalData') is not None
                        extensions = chart.find('.//' + C + 'extLst') is not None
                        if external_data or extensions: complete = False
                        references = []
                        for node in chart.iter():
                            if node.tag not in REF_TYPES: continue
                            if sum(len(item['references']) for item in results) + len(references) >= 100:
                                complete = False; limit_hit = True; break
                            parent = node.getparent(); role = parent.tag.rsplit('}',1)[-1] if parent is not None else None
                            formula_node = node.find(C+'f'); formula = formula_node.text if formula_node is not None else None
                            item = {'index': len(references) + 1, 'role': role, 'kind': node.tag.rsplit('}',1)[-1], 'formula': (formula or '')[:500], 'status': 'unverified', 'mismatches': []}
                            references.append(item)
                            if node.tag not in (C+'numRef', C+'strRef'):
                                item['reason'] = 'unsupported_source'; complete = False; continue
                            cache_nodes = node.findall(C+('numCache' if node.tag == C+'numRef' else 'strCache'))
                            if not cache_nodes:
                                item['status'] = 'missing_cache'; complete = False; continue
                            if len(cache_nodes) != 1 or len(node.findall(C+'f')) != 1:
                                item['reason'] = 'ambiguous_cache_or_formula'; complete = False; continue
                            cache = cache_nodes[0]
                            parsed = parse_reference(formula)
                            if parsed is None:
                                item['reason'] = 'unsupported_reference'; complete = False; continue
                            name,c1,r1,c2,r2 = parsed; count = (c2-c1+1)*(r2-r1+1)
                            if name not in sheets or count > 2000 or points_read + count > 10000:
                                item['reason'] = 'sheet_or_range_limit'; complete = False; continue
                            count_nodes = cache.findall(C+'ptCount'); count_node = count_nodes[0] if len(count_nodes) == 1 else None
                            count_text = count_node.get('val') if count_node is not None else None
                            points = {}; invalid = count_text is None or not count_text.isdecimal() or len(count_text)>8 or int(count_text)!=count
                            for point in cache.findall(C+'pt'):
                                index = point.get('idx'); values = point.findall(C+'v'); value = values[0] if len(values) == 1 else None
                                if index is None or not index.isdecimal() or len(index)>8 or value is None or len(value): invalid = True; break
                                index = int(index)
                                if index in points or index >= count: invalid = True; break
                                points[index] = value.text or ''
                            if invalid:
                                item['reason'] = 'invalid_or_nonmatching_cache_structure'; complete = False; continue
                            values = []
                            for row in sheets[name].iter_rows(min_row=r1,max_row=r2,min_col=c1,max_col=c2,values_only=False): values.extend(row)
                            values.extend([None] * (count-len(values))); points_read += count
                            blank_cells = None; protected = None
                            if any(cell is None or cell.value is None for cell in values):
                                try:
                                    if name not in constraints: constraints[name] = spreadsheet.worksheet_constraints(snapshot, name)
                                    protected = constraints[name]['formula_ranges'] + constraints[name]['merged_ranges']
                                    cell_range = f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}'
                                    blank_cells = [cell for row in spreadsheet.read_range(snapshot, name, cell_range)['rows'] for cell in row]
                                except (ValueError, TypeError, KeyError, OSError, RuntimeError):
                                    blank_cells = None
                            unknown = 0; compared = 0; mismatches = 0
                            for index, source_cell in enumerate(values[:count]):
                                value = source_cell.value if source_cell is not None else None
                                cached = points.get(index); reason = None
                                if value is None:
                                    col = c1 + (index if r1 == r2 else 0); row = r1 + (index if c1 == c2 else 0)
                                    blank = blank_cells[index] if blank_cells is not None and index < len(blank_cells) else None
                                    in_range = protected is None or any(a <= col <= c and b <= row <= d for a,b,c,d in protected)
                                    if blank is None or blank.get('value') is not None or 'formula' in blank or blank.get('type') == 'e' or in_range:
                                        unknown += 1; continue
                                    if cached is not None: reason = 'extra_point'
                                elif isinstance(value, bool) or getattr(source_cell, 'data_type', None) == 'e': unknown += 1; continue
                                elif node.tag == C+'numRef':
                                    if isinstance(value, TEMPORAL):
                                        if name not in raw_values: raw_values[name] = worksheet_numeric_values(archive, sheets[name])
                                        raw = raw_values[name].get(getattr(source_cell, 'coordinate', ''))
                                        if raw is None: unknown += 1; continue
                                        value = Decimal(raw)
                                    if not isinstance(value, (int,float,Decimal)) or isinstance(value,float) and not math.isfinite(value): unknown += 1; continue
                                    if cached is None: reason = 'missing_point'
                                    elif len(cached) > 256: unknown += 1; continue
                                    else:
                                        try:
                                            left, right = Decimal(str(value)), Decimal(cached)
                                            if not left.is_finite() or not right.is_finite(): raise InvalidOperation
                                            if left != right: reason = 'value_differs'
                                        except InvalidOperation: unknown += 1; continue
                                else:
                                    if not isinstance(value, str) or isinstance(value, spreadsheet.UnverifiedSharedString): unknown += 1; continue
                                    if ESCAPED.search(value) or cached is not None and ESCAPED.search(cached): unknown += 1; continue
                                    if cached is None: reason = 'missing_point'
                                    elif cached != value: reason = 'value_differs'
                                compared += 1
                                if reason:
                                    mismatches += 1
                                    if len(item['mismatches']) < 20:
                                        address = f'{get_column_letter(c1 + (index if r1 == r2 else 0))}{r1 + (index if c1 == c2 else 0)}'
                                        item['mismatches'].append({'index': index, 'cell': address, 'reason': reason, 'stored_value': str(value)[:500] if value is not None else None, 'cached_value': cached[:500] if cached is not None else None})
                            item.update({'sheet': name, 'range': f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}', 'points': count, 'compared_points': compared,
                                         'unverified_points': unknown, 'mismatch_count': mismatches, 'mismatches_truncated': mismatches > len(item['mismatches']),
                                         'status': 'mismatch' if mismatches else 'unverified' if unknown else 'match'})
                            if unknown: complete = False
                        if not references: complete = False
                        results.append({'part': part, 'status': 'scanned' if references else 'no_references_found', 'external_data': external_data, 'extensions_present': extensions, 'references': references})
                        if limit_hit: break
                    if len(chart_parts) > 50: complete = False
                    refs = [ref for chart in results for ref in chart['references']]
                    return {'charts': results, 'chart_parts_total': len(chart_parts), 'complete': complete,
                            'mismatch_references': sum(ref['status']=='mismatch' for ref in refs),
                            'missing_caches': sum(ref['status']=='missing_cache' for ref in refs),
                            'unverified_references': sum(ref['status']=='unverified' or ref.get('unverified_points', 0)>0 for ref in refs), 'source_cells_read': points_read,
                            'notes': ['Comparison uses stored worksheet values; formula caches can be stale.', 'Chart parts may be unreferenced; unsupported chart types and data sources are not fully covered.', 'Blank values, hidden data, formatting and rendering may affect chart behavior.']}
                finally: workbook.close()
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Invalid workbook package: {exc}') from exc


def sync(source, output, part, reference, allow_formula_caches=False):
    """Synchronize mismatched cache points from stored worksheet values."""
    source = Path(source).resolve(strict=True); output = Path(output).absolute()
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx': raise ValueError('Chart cache sync requires XLSX input and output')
    if not isinstance(part, str) or isinstance(reference, bool) or not isinstance(reference, int) or reference < 1:
        raise ValueError('Provide a chart part and positive reference index')
    if not isinstance(allow_formula_caches, bool): raise ValueError('allow_formula_caches must be a boolean')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    if output.exists() or output.is_symlink(): raise FileExistsError(f'Output already exists: {output}')
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-chart-sync-') as tmp:
        snapshot = Path(tmp) / 'source.xlsx'; shutil.copyfile(source, snapshot)
        result = scan(snapshot)
        matches = [item for item in result['charts'] if item['part'] == part]
        if len(matches) != 1 or matches[0]['status'] != 'scanned': raise ValueError('Chart part was not available in the bounded scan')
        chart = matches[0]
        if chart['external_data'] or chart['extensions_present']: raise ValueError('Chart contains external data or extensions; sync requires separate review')
        refs = [item for item in chart['references'] if item['index'] == reference]
        if len(refs) != 1: raise ValueError('Chart reference was not available in the bounded scan')
        ref = refs[0]
        if ref['status'] != 'mismatch' or ref.get('unverified_points') != 0:
            raise ValueError('Chart reference must have a fully comparable mismatch')
        parsed = parse_reference(ref['formula'])
        if parsed is None: raise ValueError('Chart source reference is unsupported')
        sheet, c1, r1, c2, r2 = parsed
        cell_range = f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}'
        rows = spreadsheet.read_range(snapshot, sheet, cell_range)['rows']
        cells = [cell for row in rows for cell in row]
        raw_values = {}
        if any(isinstance(cell.get('value'), TEMPORAL) for cell in cells):
            workbook = load_workbook(snapshot, read_only=True, data_only=True, keep_links=False)
            try:
                with zipfile.ZipFile(snapshot) as archive: raw_values = worksheet_numeric_values(archive, workbook[sheet])
            finally: workbook.close()
        formula_count = sum('formula' in cell for cell in cells)
        if formula_count and not allow_formula_caches:
            raise ValueError('Source contains formulas; recalculate if appropriate and explicitly allow stored formula caches')
        updated = 0
        def edit(tree, archive):
            nonlocal updated
            if tree.getroot().tag != C+'chartSpace': raise ValueError('Invalid chart XML')
            nodes = [node for node in tree.getroot().iter() if node.tag in REF_TYPES]
            if reference > len(nodes): raise ValueError('Chart reference no longer exists')
            node = nodes[reference-1]
            if node.tag not in (C+'numRef', C+'strRef') or node.find(C+'f') is None or node.find(C+'f').text != ref['formula']:
                raise ValueError('Chart reference changed during sync')
            cache_nodes = node.findall(C+('numCache' if node.tag == C+'numRef' else 'strCache'))
            if len(cache_nodes) != 1: raise ValueError('Chart cache is missing or ambiguous')
            points = {}
            for point in cache_nodes[0].findall(C+'pt'):
                raw = point.get('idx'); values = point.findall(C+'v')
                if raw is None or not raw.isdecimal() or len(raw)>8 or len(values)!=1 or len(values[0]): raise ValueError('Invalid chart cache point')
                index = int(raw)
                if index in points or index >= len(cells): raise ValueError('Invalid or duplicate chart cache point index')
                points[index] = values[0]
            for index, cell in enumerate(cells):
                value = cell.get('value'); node_value = points.get(index)
                if value is None:
                    if 'formula' in cell or cell.get('type') == 'e': raise ValueError('Chart source contains unverified values')
                    if node_value is not None:
                        cache_nodes[0].remove(node_value.getparent()); updated += 1
                    continue
                if isinstance(value, bool) or cell.get('type') == 'e' or cell.get('text_complete') is False: raise ValueError('Chart source contains unverified values')
                old = (node_value.text or '') if node_value is not None else None
                if node.tag == C+'numRef':
                    if isinstance(value, TEMPORAL):
                        address = f'{get_column_letter(c1 + (index if r1 == r2 else 0))}{r1 + (index if c1 == c2 else 0)}'
                        raw = raw_values.get(address)
                        if raw is None: raise ValueError('Chart date source is unavailable as a stored numeric value')
                        value = Decimal(raw)
                    if not isinstance(value, (int,float,Decimal)) or isinstance(value,float) and not math.isfinite(value) or old is not None and len(old)>256:
                        raise ValueError('Chart source contains unsupported numeric values')
                    try:
                        left = Decimal(str(value)); right = Decimal(old) if old is not None else None
                        if not left.is_finite() or right is not None and not right.is_finite(): raise InvalidOperation
                    except InvalidOperation as exc: raise ValueError('Chart cache contains unsupported numeric values') from exc
                    changed = left != right; new = str(value)
                else:
                    if not isinstance(value, str) or ESCAPED.search(value) or old is not None and ESCAPED.search(old): raise ValueError('Chart source contains unsupported text values')
                    changed = value != old; new = value
                if changed:
                    if node_value is None:
                        point = etree.Element(C+'pt', idx=str(index)); node_value = etree.SubElement(point, C+'v')
                        cache = cache_nodes[0]; position = len(cache)
                        for offset, child in enumerate(cache):
                            if child.tag == C+'extLst' or child.tag == C+'pt' and int(child.get('idx')) > index:
                                position = offset; break
                        cache.insert(position, point)
                    node_value.text = new; updated += 1
            if updated != ref['mismatch_count']: raise ValueError('Chart source or cache did not match the scan')
        ooxml.edit_xml(snapshot, output, lambda _: part, edit)
    return {'output': str(output), 'part': part, 'reference': reference, 'source_sheet': sheet, 'source_range': cell_range,
            'updated_points': updated, 'source_formula_cells': formula_count, 'formula_cache_freshness': 'unknown'}
