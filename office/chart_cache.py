"""Compare bounded chart caches with stored worksheet values in an XLSX snapshot."""
import math
import re
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries
from lxml import etree

import ooxml
import snapshot as snapshots
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
        snapshot, digest = snapshots.copy(source, tmp)
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
                            if node.tag in (C+'numLit', C+'strLit'):
                                counts = node.findall(C+'ptCount'); count_text = counts[0].get('val') if len(counts) == 1 else None
                                if count_text is None or not count_text.isdecimal() or len(count_text) > 8 or int(count_text) > 2000:
                                    item['reason'] = 'invalid_or_oversized_literal'; complete = False; continue
                                count = int(count_text); seen = set(); invalid = False; examples = []
                                for point in node.findall(C+'pt'):
                                    index = point.get('idx'); values = point.findall(C+'v')
                                    if index is None or not index.isdecimal() or len(index) > 8 or int(index) >= count or int(index) in seen or len(values) != 1 or len(values[0]) or values[0].text is None or len(values[0].text) > 10000:
                                        invalid = True; break
                                    seen.add(int(index))
                                    if len(examples) < 20: examples.append({'point': int(index)+1, 'value': values[0].text[:500], 'value_truncated': len(values[0].text)>500})
                                    if node.tag == C+'numLit':
                                        try:
                                            if not math.isfinite(float(values[0].text)): raise ValueError()
                                        except (ValueError, OverflowError): invalid = True; break
                                if invalid: item['reason'] = 'invalid_literal_points'; complete = False; continue
                                item.update({'status': 'literal', 'reason': 'no_worksheet_reference', 'points': count, 'stored_points': len(seen), 'examples': examples, 'examples_truncated': len(seen)>len(examples)})
                                continue
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
                        areas = chart.findall(C+'chart/'+C+'plotArea'); plots = [node for node in areas[0] if isinstance(node.tag, str) and node.tag.startswith(C) and node.tag.endswith('Chart')] if len(areas) == 1 else []
                        series_items = []; series_complete = len(areas) == 1
                        for plot_index, plot in enumerate(plots, 1):
                            for series_index, series in enumerate(plot.findall(C+'ser'), 1):
                                if len(series_items) >= 30: series_complete = False; break
                                names = series.findall(C+'tx'); entry = {'plot': plot_index, 'index': series_index, 'name': None, 'name_status': 'absent'}
                                if len(names) > 1: entry['name_status'] = 'unsupported'; series_complete = False
                                elif names:
                                    values = names[0].findall(C+'v'); refs = names[0].findall(C+'strRef')
                                    if len(values) == 1 and len(names[0]) == 1 and len(values[0]) == 0 and not values[0].attrib:
                                        value = values[0].text or ''; entry.update(name=value[:500], name_status='literal', name_truncated=len(value)>500)
                                        if len(value) > 500: series_complete = False
                                    elif len(refs) == 1 and len(names[0]) == 1: entry['name_status'] = 'reference'
                                    else: entry['name_status'] = 'unsupported'; series_complete = False
                                series_items.append(entry)
                        results.append({'part': part, 'status': 'scanned' if references else 'no_references_found', 'external_data': external_data, 'extensions_present': extensions, 'references': references, 'series': series_items, 'series_complete': series_complete, 'plot_count': len(plots)})
                        if limit_hit: break
                    if len(chart_parts) > 50: complete = False
                    refs = [ref for chart in results for ref in chart['references']]
                    return {'snapshot_sha256': digest, 'charts': results, 'chart_parts_total': len(chart_parts), 'complete': complete,
                            'mismatch_references': sum(ref['status']=='mismatch' for ref in refs),
                            'missing_caches': sum(ref['status']=='missing_cache' for ref in refs),
                            'literal_sources': sum(ref['status']=='literal' for ref in refs),
                            'unverified_references': sum(ref['status']=='unverified' or ref.get('unverified_points', 0)>0 for ref in refs), 'source_cells_read': points_read,
                            'notes': ['Comparison uses stored worksheet values; formula caches can be stale.', 'Chart parts may be unreferenced; unsupported chart types and data sources are not fully covered.', 'Literal chart data has no worksheet source reference and will not update with worksheet edits.', 'Blank values, hidden data, formatting and rendering may affect chart behavior.']}
                finally: workbook.close()
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Invalid workbook package: {exc}') from exc


def set_pie_point_colors(source, output, part, colors, expected_sha256=None):
    """Set explicit solid fills for every point in a simple pie or doughnut chart."""
    if Path(source).suffix.lower() != '.xlsx' or Path(output).suffix.lower() != '.xlsx': raise ValueError('Chart color editing requires XLSX input and output')
    if not isinstance(part, str) or not isinstance(colors, list) or not 1 <= len(colors) <= 200 or any(not isinstance(color, str) or not re.fullmatch(r'[0-9a-fA-F]{6}', color) for color in colors): raise ValueError('Provide a chart part and 1 to 200 six-digit RGB colors')
    def select(file):
        result = scan(file); charts = [item for item in result['charts'] if item['part'] == part]
        if len(charts) != 1 or charts[0]['status'] != 'scanned' or charts[0]['external_data'] or charts[0]['extensions_present'] or charts[0]['plot_count'] != 1: raise ValueError('Chart is unavailable or contains unsupported extensions or plots')
        refs = [item for item in charts[0]['references'] if item['role'] == 'val' and item['kind'] in ('numLit','numRef')]
        if len(refs) != 1 or refs[0]['status'] not in ('literal','match','mismatch') or refs[0].get('unverified_points', 0) or refs[0]['points'] != len(colors): raise ValueError('Chart values must be fully inspected with one color per point')
        return part
    def edit(tree, _archive):
        areas = tree.getroot().findall(C+'chart/'+C+'plotArea')
        plots = [node for node in areas[0] if isinstance(node.tag, str) and node.tag.startswith(C) and node.tag.endswith('Chart')] if len(areas) == 1 else []
        if len(plots) != 1 or plots[0].tag not in (C+'pieChart', C+'doughnutChart'): raise ValueError('Chart must contain one pie or doughnut plot')
        series = plots[0].findall(C+'ser')
        if len(series) != 1: raise ValueError('Chart must have exactly one series')
        series = series[0]; existing = {}
        for point in series.findall(C+'dPt'):
            ids = point.findall(C+'idx'); raw = ids[0].get('val') if len(ids) == 1 else None
            if raw is None or not raw.isdecimal() or len(raw) > 8 or int(raw) >= len(colors) or int(raw) in existing: raise ValueError('Chart point formatting is ambiguous')
            existing[int(raw)] = point
        A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
        fills = {A+name for name in ('noFill','solidFill','gradFill','blipFill','pattFill','grpFill')}
        for index, color in enumerate(colors):
            point = existing.get(index)
            if point is None:
                point = etree.Element(C+'dPt'); etree.SubElement(point,C+'idx',val=str(index))
                following = next((child for child in series if child.tag in (C+'dLbls',C+'trendline',C+'errBars',C+'cat',C+'val',C+'extLst')),None)
                if following is None: series.append(point)
                else: series.insert(series.index(following),point)
            properties = point.findall(C+'spPr')
            if len(properties) > 1: raise ValueError('Point shape properties are ambiguous')
            if properties: shape = properties[0]
            else:
                shape = etree.Element(C+'spPr'); following = next((child for child in point if child.tag in (C+'pictureOptions',C+'extLst')),None)
                if following is None: point.append(shape)
                else: point.insert(point.index(following),shape)
            old = [child for child in shape if child.tag in fills]
            if len(old) > 1: raise ValueError('Point fill is ambiguous')
            for child in old: shape.remove(child)
            fill = etree.Element(A+'solidFill'); etree.SubElement(fill,A+'srgbClr',val=color.upper())
            following = next((child for child in shape if child.tag not in (A+'xfrm',A+'prstGeom',A+'custGeom')),None)
            if following is None: shape.append(fill)
            else: shape.insert(shape.index(following),fill)
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'colors': [color.upper() for color in colors], 'point_count': len(colors)}


def set_literal_series_name(source, output, part, series, text, expected_sha256=None):
    """Edit a direct literal series name in one supported plot."""
    if Path(source).suffix.lower() != '.xlsx' or Path(output).suffix.lower() != '.xlsx': raise ValueError('Chart name editing requires XLSX input and output')
    if not isinstance(part, str) or isinstance(series, bool) or not isinstance(series, int) or not 1 <= series <= 30: raise ValueError('Provide a chart part and positive one-based series index')
    if not isinstance(text, str) or not 1 <= len(text) <= 255 or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or (ord(char) & 0xFFFF) in (0xFFFE, 0xFFFF) for char in text): raise ValueError('Series name must contain 1 to 255 valid single-line characters')
    selected = {}
    def select(file):
        result = scan(file); charts = [item for item in result['charts'] if item['part'] == part]
        if len(charts) != 1 or charts[0]['status'] != 'scanned' or charts[0]['external_data'] or charts[0]['extensions_present'] or charts[0]['plot_count'] != 1 or not charts[0]['series_complete']: raise ValueError('Chart series inventory is unavailable or incomplete')
        items = [item for item in charts[0]['series'] if item['plot'] == 1 and item['index'] == series]
        if len(items) != 1 or items[0]['name_status'] != 'literal': raise ValueError('Series name must be a direct literal')
        return part
    def edit(tree, _archive):
        areas = tree.getroot().findall(C+'chart/'+C+'plotArea')
        plots = [node for node in areas[0] if isinstance(node.tag, str) and node.tag.startswith(C) and node.tag.endswith('Chart')] if len(areas) == 1 else []
        if len(plots) != 1 or plots[0].tag not in (C+'barChart', C+'lineChart', C+'pieChart', C+'doughnutChart'): raise ValueError('Unsupported chart plot')
        items = plots[0].findall(C+'ser')
        if series > len(items): raise ValueError('Chart series changed')
        titles = items[series-1].findall(C+'tx'); nodes = titles[0].findall(C+'v') if len(titles) == 1 else []
        if len(nodes) != 1 or len(titles[0]) != 1 or len(nodes[0]) or nodes[0].attrib: raise ValueError('Series name structure is unsupported')
        selected['old_text'] = nodes[0].text or ''; nodes[0].text = text
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'series': series, 'old_text': selected['old_text'], 'text': text}


def set_literal_category(source, output, part, reference, point, text, expected_sha256=None):
    """Edit a matching literal category across the series of one plot."""
    if Path(source).suffix.lower() != '.xlsx' or Path(output).suffix.lower() != '.xlsx': raise ValueError('Chart category editing requires XLSX input and output')
    if not isinstance(part, str) or any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in (reference, point)): raise ValueError('Provide a chart part and positive one-based reference and point')
    if not isinstance(text, str) or not 1 <= len(text) <= 255 or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or (ord(char) & 0xFFFF) in (0xFFFE, 0xFFFF) for char in text): raise ValueError('Category must contain 1 to 255 valid single-line characters')
    selected = {}
    def select(file):
        result = scan(file); charts = [item for item in result['charts'] if item['part'] == part]
        if len(charts) != 1 or charts[0]['status'] != 'scanned' or charts[0]['external_data'] or charts[0]['extensions_present']: raise ValueError('Chart is unavailable or contains unsupported extensions')
        refs = charts[0]['references']; selected['references'] = {item['index']: item for item in refs}
        matches = [item for item in refs if item['index'] == reference]
        if len(matches) != 1 or matches[0]['status'] != 'literal' or matches[0]['kind'] != 'strLit' or matches[0]['role'] != 'cat' or point > matches[0]['points']: raise ValueError('Target must be a literal category from chart inspection')
        return part
    def edit(tree, _archive):
        nodes = [node for node in tree.getroot().iter() if node.tag in REF_TYPES]
        if reference > len(nodes): raise ValueError('Chart reference changed')
        target = nodes[reference - 1]
        if target.tag != C+'strLit' or target.getparent().tag != C+'cat': raise ValueError('Chart category source changed')
        ser = target.getparent().getparent(); plot = ser.getparent() if ser is not None else None
        if ser is None or ser.tag != C+'ser' or plot is None or plot.tag not in (C+'barChart', C+'lineChart', C+'pieChart', C+'doughnutChart'): raise ValueError('Unsupported chart series or plot')
        areas = tree.getroot().findall(C+'chart/'+C+'plotArea')
        if len(areas) != 1 or len([item for item in areas[0] if isinstance(item.tag, str) and item.tag.startswith(C) and item.tag.endswith('Chart')]) != 1: raise ValueError('Chart must contain one plot')
        series = plot.findall(C+'ser')
        if not series or len(series) > 30: raise ValueError('Chart series exceed limits')
        baseline = None; targets = []
        for item in series:
            categories = item.findall(C+'cat/'+C+'strLit')
            if len(categories) != 1: raise ValueError('Every series must contain literal string categories')
            category = categories[0]; index = nodes.index(category) + 1; checked = selected['references'].get(index)
            if not checked or checked['status'] != 'literal' or checked['kind'] != 'strLit': raise ValueError('Category inspection is incomplete')
            counts = category.findall(C+'ptCount'); values = {}
            for entry in category.findall(C+'pt'):
                raw = entry.get('idx'); values_node = entry.findall(C+'v')
                if not raw or not raw.isdecimal() or len(raw) > 8 or int(raw) in values or len(values_node) != 1 or len(values_node[0]) or values_node[0].attrib: raise ValueError('Category points are ambiguous')
                values[int(raw)] = values_node[0].text or ''
                if int(raw) == point - 1: targets.append(values_node[0])
            current = (counts[0].get('val') if len(counts) == 1 else None, values)
            if baseline is not None and current != baseline: raise ValueError('Series categories do not match')
            baseline = current
        if len(targets) != len(series): raise ValueError('Category point is missing')
        selected['old_text'] = targets[0].text or ''
        for node in targets: node.text = text
        selected['series_updated'] = len(series)
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'reference': reference, 'point': point, 'old_text': selected['old_text'], 'text': text, 'series_updated': selected['series_updated']}


def set_literal_values(source, output, part, changes, expected_sha256=None):
    """Update multiple literal chart points atomically without rewriting worksheets."""
    if Path(source).suffix.lower() != '.xlsx' or Path(output).suffix.lower() != '.xlsx': raise ValueError('Chart literal editing requires XLSX input and output')
    if not isinstance(part, str) or not isinstance(changes, list) or not 1 <= len(changes) <= 100: raise ValueError('Provide a chart part and 1 to 100 changes')
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'reference', 'point', 'value'}: raise ValueError('Each change requires reference, point and value')
        reference, point, value = change['reference'], change['point'], change['value']
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in (reference, point)) or (reference, point) in seen: raise ValueError('Reference and point must be unique positive one-based indices')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e100 <= value <= 1e100 or not math.isfinite(value): raise ValueError('Chart value must be a finite number within ±1e100')
        if isinstance(value, int) and int(float(value)) != value: raise ValueError('Chart integer cannot be represented exactly as a binary64 value')
        seen.add((reference, point))
    selected = {'changes': []}
    def select(file):
        result = scan(file); charts = [item for item in result['charts'] if item['part'] == part]
        if len(charts) != 1 or charts[0]['status'] != 'scanned' or charts[0]['external_data'] or charts[0]['extensions_present']: raise ValueError('Chart is unavailable or contains unsupported extensions')
        refs = {item['index']: item for item in charts[0]['references']}
        for change in changes:
            ref = refs.get(change['reference'])
            if not ref or ref['status'] != 'literal' or ref['kind'] != 'numLit' or ref['role'] != 'val' or change['point'] > ref['points']: raise ValueError('Target must be a numeric literal series value from chart inspection')
        return part
    def edit(tree, _archive):
        nodes = [node for node in tree.getroot().iter() if node.tag in REF_TYPES]; pies = set()
        for change in changes:
            reference, point, value = change['reference'], change['point'], change['value']
            if reference > len(nodes): raise ValueError('Chart reference changed')
            node = nodes[reference - 1]
            if node.tag != C+'numLit' or node.getparent().tag != C+'val': raise ValueError('Chart literal source changed')
            points = [item for item in node.findall(C+'pt') if item.get('idx') == str(point - 1)]
            if len(points) != 1: raise ValueError('Chart point is missing or ambiguous')
            values = points[0].findall(C+'v')
            if len(values) != 1 or len(values[0]) or values[0].attrib: raise ValueError('Chart value has unsupported structure')
            parent = node.getparent().getparent(); plot = parent.getparent() if parent is not None else None
            if parent is None or parent.tag != C+'ser' or plot is None or plot.tag not in (C+'barChart', C+'lineChart', C+'pieChart', C+'doughnutChart'): raise ValueError('Unsupported chart series or plot')
            if plot.tag in (C+'pieChart', C+'doughnutChart'):
                if value < 0: raise ValueError('Pie chart values must be nonnegative')
                pies.add(node)
            selected['changes'].append({'reference': reference, 'point': point, 'old_value': float(values[0].text), 'old_value_raw': values[0].text, 'value': value})
            values[0].text = str(value)
        for node in pies:
            if not any(float(item.find(C+'v').text) > 0 for item in node.findall(C+'pt')): raise ValueError('Pie chart requires a positive value')
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'changes': selected['changes']}


def set_literal_value(source, output, part, reference, point, value, expected_sha256=None):
    result = set_literal_values(source, output, part, [{'reference': reference, 'point': point, 'value': value}], expected_sha256)
    return {'output': result['output'], 'chart_part': part, **result['changes'][0]}


def sync(source, output, part, reference, allow_formula_caches=False, expected_sha256=None):
    """Synchronize mismatched cache points from stored worksheet values."""
    source = Path(source).resolve(strict=True); output = Path(output).absolute()
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx': raise ValueError('Chart cache sync requires XLSX input and output')
    if not isinstance(part, str) or isinstance(reference, bool) or not isinstance(reference, int) or reference < 1:
        raise ValueError('Provide a chart part and positive reference index')
    if not isinstance(allow_formula_caches, bool): raise ValueError('allow_formula_caches must be a boolean')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Workbook exceeds the 128 MiB size limit')
    if output.exists() or output.is_symlink(): raise FileExistsError(f'Output already exists: {output}')
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-chart-sync-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        if expected_sha256 is not None and digest != expected_sha256: raise ValueError('Workbook snapshot changed; rescan chart caches')
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
    return {'output': str(output), 'snapshot_sha256': digest, 'part': part, 'reference': reference, 'source_sheet': sheet, 'source_range': cell_range,
            'updated_points': updated, 'source_formula_cells': formula_count, 'formula_cache_freshness': 'unknown'}
