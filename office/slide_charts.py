"""Inspect bounded cached chart data in saved PowerPoint presentations."""
import hashlib
import copy
import io
import itertools
import math
import tempfile
import zipfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE

import snapshot as snapshots
import chart_cache
import ooxml

C = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


SYNTHETIC_PART = 'xl/charts/office-use-inspection.xml'


def prepare_workbook(blob, chart_blob, candidate):
    if len(blob) > 16 * 1024 * 1024: raise ValueError('Embedded workbook exceeds size limit')
    with zipfile.ZipFile(io.BytesIO(blob)) as source:
        entries = source.infolist(); names = [entry.filename for entry in entries]
        if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 64 * 1024 * 1024:
            raise ValueError('Embedded workbook exceeds package limits or contains duplicates')
        manifest = ooxml.parse_xml(source.read('[Content_Types].xml')).getroot()
        if manifest.tag != chart_cache.CT + 'Types': raise ValueError('Invalid content types')
        if SYNTHETIC_PART in names or any(item.get('PartName') == '/' + SYNTHETIC_PART for item in manifest):
            raise ValueError('Synthetic chart part already exists')
        entry = etree.Element(chart_cache.CT + 'Override', PartName='/' + SYNTHETIC_PART, ContentType=chart_cache.CHART_TYPE)
        overrides = [index for index, item in enumerate(manifest) if item.tag == chart_cache.CT + 'Override']
        manifest.insert(overrides[0] if overrides else len(manifest), entry)
        chart_root = ooxml.parse_xml(chart_blob).getroot()
        for node in chart_root.findall(C + 'externalData'): chart_root.remove(node)
        chart_xml = etree.tostring(chart_root, encoding='utf-8', xml_declaration=True)
        if len(chart_xml) > 4 * 1024 * 1024: raise ValueError('Chart exceeds size limit')
        with zipfile.ZipFile(candidate, 'w') as destination:
            for item in entries:
                data = etree.tostring(manifest, encoding='utf-8', xml_declaration=True) if item.filename == '[Content_Types].xml' else source.read(item)
                destination.writestr(item, data)
            destination.writestr(SYNTHETIC_PART, chart_xml)


def reconcile(chart, budget):
    """Compare chart caches against a bounded embedded workbook copy."""
    if budget['charts'] >= 20: return {'status': 'incomplete', 'reason': 'chart_limit', 'complete': False}
    budget['charts'] += 1
    try:
        part = chart.part.chart_workbook.xlsx_part
        if part is None: return {'status': 'unavailable', 'reason': 'missing_workbook', 'complete': False}
        blob = part.blob
        if len(blob) > 16 * 1024 * 1024 or budget['bytes'] + len(blob) > 64 * 1024 * 1024:
            return {'status': 'incomplete', 'reason': 'workbook_size_limit', 'complete': False}
        budget['bytes'] += len(blob)
        with tempfile.TemporaryDirectory(prefix='office-slide-chart-reconcile-') as tmp:
            candidate = Path(tmp) / 'embedded.xlsx'
            prepare_workbook(blob, chart.part.blob, candidate)
            report = chart_cache.scan(candidate)
        synthetic_part = SYNTHETIC_PART
        found = [item for item in report['charts'] if item['part'] == synthetic_part]
        if len(found) != 1 or found[0]['status'] != 'scanned': return {'status': 'incomplete', 'reason': 'unsupported_chart', 'complete': False}
        chart_report = found[0]; refs = chart_report['references']
        incomplete = chart_report['extensions_present'] or chart_report['external_data'] or any(ref['status'] not in ('match', 'mismatch') or ref.get('unverified_points', 0) for ref in refs)
        mismatch_count = sum(ref.get('mismatch_count', 0) for ref in refs)
        visible = []
        for ref in refs[:30]:
            item = dict(ref); mismatches = item.get('mismatches', [])
            item['mismatches'] = mismatches[:3]
            item['mismatches_truncated'] = item.get('mismatches_truncated', False) or len(mismatches) > 3
            visible.append(item)
        return {'status': 'mismatch' if mismatch_count else 'incomplete' if incomplete or len(refs) > 30 else 'match',
                'complete': not incomplete and len(refs) <= 30, 'mismatch_count': mismatch_count,
                'references': visible, 'references_truncated': len(refs) > 30,
                'formula_freshness': 'unknown'}
    except (ValueError, TypeError, KeyError, OSError, EOFError, IndexError, AttributeError, OverflowError, RuntimeError, NotImplementedError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        return {'status': 'incomplete', 'reason': 'embedded_workbook_unreadable', 'error_type': type(exc).__name__, 'complete': False}


def axis_inventory(chart):
    """Read saved axis settings; automatic bounds depend on the rendering application."""
    areas = chart.part._element.findall(C + 'chart/' + C + 'plotArea')
    if len(areas) != 1: return {'axes': [], 'complete': False, 'issues': ['ambiguous_plot_area']}
    axes = [node for node in areas[0] if node.tag in (C + 'valAx', C + 'catAx', C + 'dateAx', C + 'serAx')]
    issues = set(); records = []; seen = set()
    if len(axes) > 20: issues.add('axis_limit')
    for axis in axes[:20]:
        record = {'type': axis.tag[len(C):], 'id': None, 'position': None, 'minimum': None, 'maximum': None, 'log_base': None, 'orientation': None}
        for tag, key in (('axId', 'id'), ('axPos', 'position')):
            nodes = axis.findall(C + tag)
            if len(nodes) != 1 or not nodes[0].get('val'): issues.add('ambiguous_axis_' + key)
            else:
                value = nodes[0].get('val')
                if len(value) > 100: issues.add('axis_' + key + '_truncated')
                record[key] = value[:100]
        if record['id'] in seen: issues.add('duplicate_axis_id')
        if record['id'] is not None: seen.add(record['id'])
        if record['position'] not in ('b', 't', 'l', 'r'): issues.add('invalid_axis_position')
        scales = axis.findall(C + 'scaling')
        if len(scales) != 1: issues.add('ambiguous_axis_scaling')
        else:
            for tag, key in (('min', 'minimum'), ('max', 'maximum'), ('logBase', 'log_base')):
                nodes = scales[0].findall(C + tag)
                if len(nodes) > 1: issues.add('ambiguous_axis_' + key)
                elif nodes:
                    raw = nodes[0].get('val', '')
                    try:
                        if len(raw) > 100: raise ValueError()
                        value = float(raw)
                        if not math.isfinite(value): raise ValueError()
                        record[key] = value
                    except ValueError: issues.add('invalid_axis_' + key)
            orientation = scales[0].findall(C + 'orientation')
            if len(orientation) > 1: issues.add('ambiguous_axis_orientation')
            elif orientation:
                record['orientation'] = orientation[0].get('val')
                if record['orientation'] not in ('minMax', 'maxMin'): issues.add('invalid_axis_orientation')
            if record['minimum'] is not None and record['maximum'] is not None and record['minimum'] >= record['maximum']: issues.add('invalid_axis_range')
            if record['log_base'] is not None and not 2 <= record['log_base'] <= 1000: issues.add('invalid_axis_log_base')
        records.append(record)
    return {'axes': records, 'complete': not issues, 'issues': sorted(issues)}


def axis_range_candidates(chart, record):
    """Compare saved cache points to explicit bounds for simple, unstacked plots."""
    result = {'status': 'unsupported', 'reason': None, 'count': 0, 'examples': [], 'source': 'saved_chart_values'}
    axes = record['axis_inventory']
    if not axes['complete']: result['reason'] = 'incomplete_axis_inventory'; return result
    if not axes['axes']: result.update(status='not_applicable', reason='no_axes'); return result
    if not any(axis['minimum'] is not None or axis['maximum'] is not None for axis in axes['axes'] if axis['type'] == 'valAx'):
        result.update(status='not_applicable', reason='automatic_bounds'); return result
    if len(chart.plots) != 1: result['reason'] = 'multiple_plots'; return result
    plot = chart.plots[0]._element; group = plot.findall(C + 'grouping')
    if (plot.tag, group[0].get('val') if len(group) == 1 else None) not in ((C + 'barChart', 'clustered'), (C + 'lineChart', 'standard')):
        result['reason'] = 'unsupported_plot_or_grouping'; return result
    refs = [node.get('val') for node in plot.findall(C + 'axId')]
    matching = [axis for axis in axes['axes'] if axis['type'] == 'valAx' and axis['id'] in refs]
    if len(matching) != 1: result['reason'] = 'ambiguous_value_axis'; return result
    axis = matching[0]; result['axis_id'] = axis['id']; result['minimum'] = axis['minimum']; result['maximum'] = axis['maximum']
    if axis['minimum'] is None and axis['maximum'] is None: result.update(status='not_applicable', reason='automatic_bounds'); return result
    if len(record['series']) != record['series_total'] or any(item['references']['val']['status'] not in ('present', 'literal') or item['values_truncated'] or item['unverified_values'] or len(item['values']) != item['values_total'] for item in record['series']):
        result['reason'] = 'incomplete_cached_values'; return result
    result['status'] = 'checked'; result['blank_points'] = 0
    for series in record['series']:
        for index, value in enumerate(series['values'], 1):
            if value is None: result['blank_points'] += 1; continue
            side = 'below' if axis['minimum'] is not None and value < axis['minimum'] else 'above' if axis['maximum'] is not None and value > axis['maximum'] else None
            if side:
                result['count'] += 1
                if len(result['examples']) < 20: result['examples'].append({'series': series['index'], 'point': index, 'value': value, 'side': side})
    result['examples_truncated'] = result['count'] > len(result['examples'])
    return result


def inspect(file):
    source = Path(file).resolve(strict=True)
    if source.suffix.lower() != '.pptx': raise ValueError('Slide chart inspection requires PPTX')
    with tempfile.TemporaryDirectory(prefix='office-slide-charts-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        with zipfile.ZipFile(snapshot) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or len({entry.filename for entry in entries}) != len(entries) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Presentation exceeds package limits or contains duplicate parts')
        presentation = Presentation(snapshot); slides = presentation.slides
        result = {'snapshot_sha256': digest, 'slides_total': len(slides), 'slides_scanned': 0, 'shapes_scanned': 0,
                  'charts': [], 'issues': [], 'issue_count': 0, 'complete': True,
                  'scope': 'Chart values are saved caches; reconciliation compares them with saved embedded workbook values. Formula cache freshness remains unknown.'}
        reconcile_budget = {'charts': 0, 'bytes': 0}
        points = 0
        def issue(slide, path, reason):
            result['complete'] = False; result['issue_count'] += 1
            if len(result['issues']) < 200: result['issues'].append({'slide': slide, 'path': path, 'reason': reason})
        def reference(series, role):
            parent = series._element.find(C + role)
            if parent is None: return {'status': 'absent', 'formula': None}
            nodes = [child for child in parent if child.tag in (C + 'numRef', C + 'strRef', C + 'numLit', C + 'strLit', C + 'v')]
            if len(nodes) != 1: return {'status': 'unsupported', 'formula': None}
            node = nodes[0]
            if node.tag == C + 'v':
                return {'status': 'literal' if role == 'tx' and node.text is not None and not len(node) else 'unsupported', 'formula': None, 'count': 1}
            literal = node.tag in (C + 'numLit', C + 'strLit')
            formulas = node.findall(C + 'f') if not literal else []
            caches = [node] if literal else node.findall(C + ('numCache' if node.tag == C + 'numRef' else 'strCache'))
            formula = formulas[0].text if len(formulas) == 1 else None
            status = 'literal' if literal else 'present' if len(formulas) == 1 and bool(formula) and len(caches) == 1 else 'missing_or_ambiguous'
            count = None
            if status in ('present', 'literal'):
                counts = caches[0].findall(C + 'ptCount'); raw = counts[0].get('val') if len(counts) == 1 else None
                if raw is None or not raw.isdecimal() or len(raw) > 8: status = 'invalid_cache'
                else:
                    count = int(raw); seen = set()
                    for point in caches[0].findall(C + 'pt'):
                        raw_index = point.get('idx'); values = point.findall(C + 'v')
                        if raw_index is None or not raw_index.isdecimal() or len(raw_index) > 8 or len(values) != 1 or len(values[0]): status = 'invalid_cache'; break
                        index = int(raw_index)
                        if index >= count or index in seen: status = 'invalid_cache'; break
                        seen.add(index)
            if formula is not None and len(formula) > 500: status = 'truncated'
            return {'status': status, 'formula': formula[:500] if formula else None, 'count': count}
        def workbook(chart):
            nodes = chart.part._element.findall(C + 'externalData')
            if not nodes: return {'status': 'absent'}
            if len(nodes) != 1 or not nodes[0].get(R + 'id'): return {'status': 'ambiguous'}
            try: relation = chart.part.rels[nodes[0].get(R + 'id')]
            except KeyError: return {'status': 'invalid_relationship'}
            if relation.is_external: return {'status': 'external'}
            if relation.reltype != RELATIONSHIP_TYPE.PACKAGE: return {'status': 'unsupported_relationship'}
            part = relation.target_part; blob = part.blob
            metadata = {'part': str(part.partname), 'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(), 'content_type': part.content_type}
            if part.content_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': return {'status': 'unsupported_embedded_part', **metadata}
            return {'status': 'embedded', **metadata}
        def walk(shapes, slide_no, prefix, depth, hidden):
            nonlocal points
            for shape in shapes:
                if result['shapes_scanned'] >= 10000: issue(slide_no, prefix, 'shape_limit'); return False
                result['shapes_scanned'] += 1
                path = f'{prefix}/shape[@id={shape.shape_id}]'
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    path = f'{prefix}/group[@id={shape.shape_id}]'
                    if depth >= 8: issue(slide_no, path, 'group_depth'); continue
                    if not walk(shape.shapes, slide_no, path, depth + 1, hidden): return False
                    continue
                if not shape.has_chart: continue
                path = f'{prefix}/chart[@id={shape.shape_id}]'
                if len(result['charts']) >= 100: issue(slide_no, path, 'chart_limit'); return False
                try:
                    chart = shape.chart; series = chart.series; plots = chart.plots
                    metadata = next(shape._element.iter('{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr'), None)
                    hidden_shape = metadata.get('hidden') if metadata is not None else None
                    if hidden_shape not in (None, '0', 'false', '1', 'true'): issue(slide_no, path, 'unknown_shape_visibility')
                    record = {'slide': slide_no, 'hidden_slide': hidden, 'hidden_shape': hidden_shape in ('1', 'true'), 'shape_id': shape.shape_id, 'name': str(shape.name or '')[:200],
                              'path': path, 'chart_part': str(chart.part.partname), 'chart_type': str(chart.chart_type),
                              'plot_count': len(plots), 'series_total': len(series), 'series': [], 'workbook': workbook(chart),
                              'description': (metadata.get('descr', '') if metadata is not None else '')[:1000],
                              'description_truncated': metadata is not None and len(metadata.get('descr', '')) > 1000}
                    record['axis_inventory'] = axis_inventory(chart)
                    if not record['axis_inventory']['complete']: issue(slide_no, path, 'incomplete_axis_inventory')
                    title = chart.part._element.find('.//' + C + 'chart/' + C + 'title')
                    if title is not None:
                        rich = title.find(C + 'tx/' + C + 'rich')
                        if rich is None: issue(slide_no, path, 'unsupported_chart_title'); record['title'] = None
                        else:
                            title_text = ''.join(node.text or '' for node in rich.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t'))
                            record['title'] = title_text[:500]
                            if len(title_text) > 500: issue(slide_no, path, 'chart_title_truncated')
                    else: record['title'] = None
                    if record['workbook']['status'] not in ('embedded', 'absent'): issue(slide_no, path, 'workbook_' + record['workbook']['status'])
                    record['reconciliation'] = reconcile(chart, reconcile_budget) if record['workbook']['status'] == 'embedded' else {'status': 'unavailable', 'reason': record['workbook']['status'], 'complete': False}
                    if len(plots) != 1: issue(slide_no, path, 'multiple_plots')
                    if len(series) > 30: issue(slide_no, path, 'series_limit')
                    category_safe = True
                    for index, item in enumerate(itertools.islice(series, 30), 1):
                        refs = {role: reference(item, role) for role in ('tx', 'cat', 'val')}
                        cache_points = sum(1 for node in item._element.iter(C + 'pt'))
                        if cache_points > 1000 or points + cache_points > 5000:
                            issue(slide_no, path, 'point_limit'); category_safe = False; break
                        points += cache_points
                        value_count = refs['val'].get('count')
                        category_count = refs['cat'].get('count')
                        if refs['val']['status'] not in ('present', 'literal') or refs['cat']['status'] not in ('present', 'literal', 'absent') or refs['tx']['status'] not in ('present', 'literal', 'absent'):
                            issue(slide_no, path, 'unsupported_or_missing_cache'); category_safe = False
                        if category_count is not None and category_count > 200: issue(slide_no, path, 'category_limit'); category_safe = False
                        if value_count is None or value_count > 200:
                            issue(slide_no, path, 'series_value_limit' if value_count is not None else 'unavailable_values'); values = ()
                        else: values = item.values
                        literal_name = item._element.find(C + 'tx/' + C + 'v')
                        name = literal_name.text if literal_name is not None and refs['tx']['status'] == 'literal' else item.name
                        if name is not None and len(name) > 500: issue(slide_no, path, 'series_name_truncated')
                        clipped = []; unverified_values = False
                        for value in values[:200]:
                            if value is None or isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value): clipped.append(value)
                            else: clipped.append(None); unverified_values = True; issue(slide_no, path, 'unverified_cached_value')
                        record['series'].append({'index': index, 'name': name[:500] if name else name, 'values': clipped,
                                                 'values_total': value_count, 'values_truncated': value_count is not None and value_count > 200, 'unverified_values': unverified_values, 'references': refs})
                    if len(plots) == 1 and category_safe:
                        category_view = plots[0].categories; count = len(category_view)
                        if count > 200: issue(slide_no, path, 'category_limit')
                        labels = []
                        for category in itertools.islice(category_view, 200):
                            value = category.label
                            label = str(value) if value is not None else None
                            if label is not None and len(label) > 500: issue(slide_no, path, 'category_truncated'); label = label[:500]
                            labels.append(label)
                        record['categories'] = labels; record['categories_total'] = count
                    record['axis_range_candidates'] = axis_range_candidates(chart, record)
                    result['charts'].append(record)
                except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError) as exc:
                    issue(slide_no, path, 'unsupported_chart'); result['charts'].append({'slide': slide_no, 'path': path, 'error': type(exc).__name__})
            return True
        # shortcut: bounded chart inventory and reconciliation; add pagination for larger presentations.
        for slide_no in range(1, min(len(slides), 200) + 1):
            slide = slides[slide_no - 1]; visibility = slide._element.get('show')
            if visibility not in (None, '0', 'false', '1', 'true'): issue(slide_no, None, 'unknown_visibility')
            result['slides_scanned'] = slide_no
            if not walk(slide.shapes, slide_no, f'/slide[{slide_no}]', 0, visibility in ('0', 'false')): break
        if len(slides) > 200: issue(None, None, 'slide_limit')
        result['issues_truncated'] = result['issue_count'] > len(result['issues'])
        return result


def apply_text_color(chart, rgb):
    """Color chart title, axis labels and titles, legend and default data labels."""
    if len(chart.plots) != 1 or chart.plots[0]._element.tag not in (C + 'barChart', C + 'lineChart', C + 'pieChart'): raise ValueError('Chart text color supports one bar, column, line or pie plot')
    def color_title(title):
        rich = title._element.find(C + 'tx/' + C + 'rich')
        if rich is None or any(node.tag == '{http://schemas.openxmlformats.org/drawingml/2006/main}fld' for node in rich.iter()): raise ValueError('Chart title text is not a supported rich-text title')
        for paragraph in title.text_frame.paragraphs:
            paragraph.font.color.rgb = rgb
            for run in paragraph.runs: run.font.color.rgb = rgb
    if chart.has_title: color_title(chart.chart_title)
    if chart.has_legend: chart.legend.font.color.rgb = rgb
    if chart.plots[0].has_data_labels: chart.plots[0].data_labels.font.color.rgb = rgb
    if chart.plots[0]._element.tag != C + 'pieChart':
        for axis in (chart.value_axis, chart.category_axis):
            axis.tick_labels.font.color.rgb = rgb
            if axis.has_title: color_title(axis.axis_title)


def set_text_color(source, output, part, color, expected_sha256=None):
    """Set chart text color while preserving every other Office package part."""
    if not isinstance(part, str) or not part.startswith('/'): raise ValueError('Provide a chart part from inspection')
    if not isinstance(color, str) or len(color) != 6 or any(char not in '0123456789abcdefABCDEF' for char in color): raise ValueError('Chart text color must be six hexadecimal RGB digits')
    selected = {}
    def select(file):
        inventory = inspect(file); charts = [item for item in inventory['charts'] if item.get('chart_part') == part]
        if not charts or any(item.get('plot_count') != 1 or not item.get('axis_inventory', {}).get('complete') for item in charts): raise ValueError('Chart inventory or axes are unavailable or incomplete')
        axes = charts[0]['axis_inventory']['axes']
        if axes and (len(axes) != 2 or sorted(axis['type'] for axis in axes) != ['catAx', 'valAx']): raise ValueError('Unsupported chart axis structure')
        presentation = Presentation(file); parts = [item for item in presentation.part.package.iter_parts() if str(item.partname) == part]
        if len(parts) != 1 or not hasattr(parts[0], 'chart'): raise ValueError('Chart part is unavailable')
        chart = parts[0].chart; apply_text_color(chart, RGBColor.from_string(color.upper()))
        selected['root'] = copy.deepcopy(chart.part._element); selected['paths'] = [item['path'] for item in charts]; selected['complete'] = inventory['complete']
        return part.lstrip('/')
    def edit(tree, _archive):
        tree._setroot(selected['root'])
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'color': color.upper(), 'affected_paths': selected['paths'], 'affected_paths_complete': selected['complete']}


def set_axis_bounds(source, output, part, axis_id, minimum, maximum, expected_sha256=None):
    """Set or clear both explicit bounds on one inspected chart value axis."""
    if not isinstance(part, str) or not part.startswith('/') or not isinstance(axis_id, str) or not axis_id.isdecimal() or len(axis_id) > 10 or int(axis_id) > 4294967295:
        raise ValueError('Provide a chart part and numeric axis ID from inspection')
    for value in (minimum, maximum):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e100 <= value <= 1e100 or not math.isfinite(value)):
            raise ValueError('Axis bounds must be finite numbers within ±1e100 or null')
    if minimum is not None and maximum is not None and minimum >= maximum: raise ValueError('Axis minimum must be less than maximum')
    selected = {}
    def select(file):
        inventory = inspect(file)
        charts = [item for item in inventory['charts'] if item.get('chart_part') == part]
        if not charts or any(not item['axis_inventory']['complete'] for item in charts): raise ValueError('Chart axis inventory is unavailable or incomplete')
        axes = [item for item in charts[0]['axis_inventory']['axes'] if item['id'] == axis_id and item['type'] == 'valAx']
        if len(axes) != 1: raise ValueError('Axis ID must identify one value axis in the chart')
        if axes[0]['log_base'] is not None and any(value is not None and value <= 0 for value in (minimum, maximum)): raise ValueError('Logarithmic axis bounds must be positive')
        selected['paths'] = [item['path'] for item in charts]; selected['complete'] = inventory['complete']
        return part.lstrip('/')
    def edit(tree, _archive):
        areas = tree.getroot().findall(C + 'chart/' + C + 'plotArea')
        if len(areas) != 1: raise ValueError('Chart plot area is ambiguous')
        axes = [node for node in areas[0].findall(C + 'valAx') if len(node.findall(C + 'axId')) == 1 and node.find(C + 'axId').get('val') == axis_id]
        if len(axes) != 1: raise ValueError('Value axis changed')
        scales = axes[0].findall(C + 'scaling')
        if len(scales) != 1: raise ValueError('Axis scaling is ambiguous')
        scale = scales[0]; order = {C + name: index for index, name in enumerate(('logBase', 'orientation', 'max', 'min', 'extLst'))}
        ranks = [order.get(child.tag, -1) for child in scale]
        if -1 in ranks or ranks != sorted(ranks) or len(ranks) != len(set(ranks)): raise ValueError('Unsupported axis scaling structure')
        for name, value in (('max', maximum), ('min', minimum)):
            tag = C + name; node = scale.find(tag)
            if node is not None:
                if set(node.attrib) != {'val'} or len(node): raise ValueError('Unsupported axis bound structure')
                scale.remove(node)
            if value is not None:
                node = etree.Element(tag, val=str(value))
                following = next((child for child in scale if order[child.tag] > order[tag]), None)
                if following is None: scale.append(node)
                else: scale.insert(scale.index(following), node)
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'axis_id': axis_id, 'minimum': minimum, 'maximum': maximum, 'affected_paths': selected['paths'], 'affected_paths_complete': selected['complete']}


def set_literal_value(source, output, part, series, point, value, expected_sha256=None):
    """Update one existing numeric literal point without rewriting the presentation."""
    if not isinstance(part, str) or not part.startswith('/'): raise ValueError('Provide a chart part from slide chart inspection')
    if any(isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= limit for item, limit in ((series, 30), (point, 200))): raise ValueError('Series and point must be positive one-based indices within inspection limits')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e100 <= value <= 1e100 or not math.isfinite(value): raise ValueError('Chart value must be a finite number within ±1e100')
    if isinstance(value, int) and int(float(value)) != value: raise ValueError('Chart integer cannot be represented exactly as a binary64 value')
    selected = {}
    def select(file):
        inventory = inspect(file); charts = [item for item in inventory['charts'] if item.get('chart_part') == part]
        if not charts or any(item.get('plot_count') != 1 for item in charts): raise ValueError('Chart must have one inspectable plot')
        chart = charts[0]
        if len(chart['series']) != chart['series_total'] or series > len(chart['series']): raise ValueError('Series inventory is incomplete')
        item = chart['series'][series - 1]
        if item['references']['val']['status'] != 'literal' or item['values_truncated'] or item['unverified_values'] or point > len(item['values']) or item['values'][point - 1] is None: raise ValueError('Point must be an existing verified numeric literal')
        selected['old_value'] = item['values'][point - 1]; selected['values'] = item['values']; selected['paths'] = [item['path'] for item in charts]; selected['complete'] = inventory['complete']
        return part.lstrip('/')
    def edit(tree, _archive):
        areas = tree.getroot().findall(C + 'chart/' + C + 'plotArea')
        if len(areas) != 1: raise ValueError('Chart plot area is ambiguous')
        plots = [node for node in areas[0] if isinstance(node.tag, str) and node.tag.startswith(C) and node.tag.endswith('Chart')]
        if len(plots) != 1: raise ValueError('Chart plot structure is unsupported')
        all_series = plots[0].findall(C + 'ser')
        if series > len(all_series): raise ValueError('Chart series changed')
        values = all_series[series - 1].findall(C + 'val/' + C + 'numLit')
        if len(values) != 1: raise ValueError('Chart literal values changed')
        points = [node for node in values[0].findall(C + 'pt') if node.get('idx') == str(point - 1)]
        if len(points) != 1: raise ValueError('Chart point is missing or ambiguous')
        nodes = points[0].findall(C + 'v')
        if len(nodes) != 1 or len(nodes[0]) or nodes[0].attrib: raise ValueError('Chart point value has unsupported structure')
        if plots[0].tag in (C + 'pieChart', C + 'doughnutChart'):
            if value < 0: raise ValueError('Pie chart values must be nonnegative')
            if value == 0 and not any(item is not None and item > 0 for index, item in enumerate(selected['values']) if index != point - 1): raise ValueError('Pie chart requires a positive value')
        nodes[0].text = str(value)
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'series': series, 'point': point, 'old_value': selected['old_value'], 'value': value, 'affected_paths': selected['paths'], 'affected_paths_complete': selected['complete']}


def set_literal_text(source, output, part, kind, text, series=None, point=None, expected_sha256=None):
    """Edit a literal series name or shared literal category in a single-plot chart."""
    if not isinstance(part, str) or not part.startswith('/'): raise ValueError('Provide a chart part from inspection')
    if kind not in ('series_name', 'category'): raise ValueError('Text kind must be series_name or category')
    if kind == 'series_name':
        if isinstance(series, bool) or not isinstance(series, int) or not 1 <= series <= 30 or point is not None: raise ValueError('Series name requires a one-based series index and no point')
    elif isinstance(point, bool) or not isinstance(point, int) or not 1 <= point <= 200 or series is not None: raise ValueError('Category requires a one-based point index and no series')
    if not isinstance(text, str) or not 1 <= len(text) <= 255 or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or (ord(char) & 0xFFFF) in (0xFFFE, 0xFFFF) for char in text): raise ValueError('Chart text must contain 1 to 255 valid single-line characters')
    selected = {}
    def select(file):
        inventory = inspect(file); charts = [item for item in inventory['charts'] if item.get('chart_part') == part]
        if not charts or any(item.get('plot_count') != 1 for item in charts): raise ValueError('Chart must have one inspectable plot')
        chart = charts[0]; items = chart['series']
        if len(items) != chart['series_total'] or not items: raise ValueError('Series inventory is incomplete')
        if kind == 'series_name':
            if series > len(items) or items[series - 1]['references']['tx']['status'] != 'literal': raise ValueError('Series name must be a literal value')
        elif any(item['references']['cat']['status'] != 'literal' or item['references']['cat'].get('count') is None or item['references']['cat']['count'] > 200 for item in items): raise ValueError('Every series must have bounded literal categories')
        selected['paths'] = [item['path'] for item in charts]; selected['complete'] = inventory['complete']
        return part.lstrip('/')
    def edit(tree, _archive):
        areas = tree.getroot().findall(C + 'chart/' + C + 'plotArea')
        if len(areas) != 1: raise ValueError('Chart plot area is ambiguous')
        plots = [node for node in areas[0] if isinstance(node.tag, str) and node.tag.startswith(C) and node.tag.endswith('Chart')]
        if len(plots) != 1: raise ValueError('Chart plot structure is unsupported')
        items = plots[0].findall(C + 'ser')
        if kind == 'series_name':
            if series > len(items): raise ValueError('Chart series changed')
            nodes = items[series - 1].findall(C + 'tx/' + C + 'v')
            if len(nodes) != 1 or len(nodes[0]) or nodes[0].attrib: raise ValueError('Literal series name has unsupported structure')
        else:
            if not items: raise ValueError('Chart has no series')
            nodes = []; baseline = None
            for item in items:
                categories = item.findall(C + 'cat/' + C + 'strLit')
                if len(categories) != 1: raise ValueError('Category is not a string literal')
                counts = categories[0].findall(C + 'ptCount'); points = categories[0].findall(C + 'pt')
                if len(counts) != 1: raise ValueError('Category count is ambiguous')
                values = {}
                for entry in points:
                    index = entry.get('idx'); value = entry.findall(C + 'v')
                    if not index or not index.isdecimal() or int(index) in values or len(value) != 1 or len(value[0]) or value[0].attrib: raise ValueError('Category values are ambiguous')
                    values[int(index)] = value[0].text or ''
                    if int(index) == point - 1: nodes.append(value[0])
                current = (counts[0].get('val'), values)
                if baseline is not None and current != baseline: raise ValueError('Series categories do not match')
                baseline = current
            if len(nodes) != len(items): raise ValueError('Category point is missing')
        selected['old_text'] = nodes[0].text or ''
        for node in nodes: node.text = text
    ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)
    return {'output': str(output), 'chart_part': part, 'kind': kind, 'series': series, 'point': point, 'old_text': selected['old_text'], 'text': text, 'affected_paths': selected['paths'], 'affected_paths_complete': selected['complete']}


def sync(source, output, part, reference, allow_formula_caches=False, expected_sha256=None):
    """Synchronize one verified chart reference from its saved embedded workbook."""
    if not isinstance(part, str) or not part.startswith('/'): raise ValueError('Provide a chart part from slide chart inspection')
    if isinstance(reference, bool) or not isinstance(reference, int) or reference < 1: raise ValueError('Provide a positive reference index')
    if not isinstance(allow_formula_caches, bool): raise ValueError('allow_formula_caches must be a boolean')
    source = Path(source).resolve(strict=True); output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError(f'Output already exists: {output}')
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-slide-chart-sync-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        if expected_sha256 is not None and digest != expected_sha256: raise ValueError('Presentation snapshot changed; rescan chart caches')
        inventory = inspect(snapshot)
        charts = [chart for chart in inventory['charts'] if chart.get('chart_part') == part]
        if not charts or any(chart['workbook']['status'] != 'embedded' for chart in charts): raise ValueError('Chart with embedded workbook was not available in the bounded inventory')
        if any(chart['workbook']['part'] != charts[0]['workbook']['part'] for chart in charts): raise ValueError('Ambiguous embedded workbook')
        workbook_part = charts[0]['workbook']['part'].lstrip('/')
        chart_part = part.lstrip('/')
        with zipfile.ZipFile(snapshot) as archive:
            workbook_blob = archive.read(workbook_part); chart_blob = archive.read(chart_part)
        candidate = Path(tmp) / 'embedded.xlsx'; updated = Path(tmp) / 'updated.xlsx'
        prepare_workbook(workbook_blob, chart_blob, candidate)
        synced = chart_cache.sync(candidate, updated, SYNTHETIC_PART, reference, allow_formula_caches)
        with zipfile.ZipFile(updated) as archive: new_root = ooxml.parse_xml(archive.read(SYNTHETIC_PART)).getroot()
        def edit(tree, _archive):
            refs = [node for node in tree.getroot().iter() if node.tag in chart_cache.REF_TYPES]
            new_refs = [node for node in new_root.iter() if node.tag in chart_cache.REF_TYPES]
            if reference > len(refs) or reference > len(new_refs): raise ValueError('Chart reference changed')
            old_ref, new_ref = refs[reference - 1], new_refs[reference - 1]
            cache_tag = C + ('numCache' if old_ref.tag == C + 'numRef' else 'strCache')
            old_caches, new_caches = old_ref.findall(cache_tag), new_ref.findall(cache_tag)
            if old_ref.tag != new_ref.tag or len(old_caches) != 1 or len(new_caches) != 1: raise ValueError('Chart cache changed')
            old_ref.replace(old_caches[0], copy.deepcopy(new_caches[0]))
        ooxml.edit_xml(snapshot, output, lambda _: chart_part, edit)
    return {'output': str(output), 'chart_part': part, 'reference': reference, 'updated_points': synced['updated_points'],
            'source_formula_cells': synced['source_formula_cells'], 'formula_cache_freshness': 'unknown', 'snapshot_sha256': digest}
