"""Inspect bounded cached chart data in saved PowerPoint presentations."""
import hashlib
import itertools
import math
import tempfile
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE

import snapshot as snapshots

C = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


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
                  'scope': 'Chart values and categories are saved caches; embedded workbook contents and cache freshness are not verified.'}
        points = 0
        def issue(slide, path, reason):
            result['complete'] = False; result['issue_count'] += 1
            if len(result['issues']) < 200: result['issues'].append({'slide': slide, 'path': path, 'reason': reason})
        def reference(series, role):
            parent = series._element.find(C + role)
            if parent is None: return {'status': 'absent', 'formula': None}
            nodes = [child for child in parent if child.tag in (C + 'numRef', C + 'strRef')]
            if len(nodes) != 1: return {'status': 'unsupported', 'formula': None}
            node = nodes[0]; formulas = node.findall(C + 'f'); caches = node.findall(C + ('numCache' if node.tag == C + 'numRef' else 'strCache'))
            formula = formulas[0].text if len(formulas) == 1 else None
            status = 'present' if len(formulas) == 1 and bool(formula) and len(caches) == 1 else 'missing_or_ambiguous'
            count = None
            if status == 'present':
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
                              'plot_count': len(plots), 'series_total': len(series), 'series': [], 'workbook': workbook(chart)}
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
                        if refs['val']['status'] != 'present' or refs['cat']['status'] not in ('present', 'absent') or refs['tx']['status'] not in ('present', 'absent'):
                            issue(slide_no, path, 'unsupported_or_missing_cache'); category_safe = False
                        if category_count is not None and category_count > 200: issue(slide_no, path, 'category_limit'); category_safe = False
                        if value_count is None or value_count > 200:
                            issue(slide_no, path, 'series_value_limit' if value_count is not None else 'unavailable_values'); values = ()
                        else: values = item.values
                        name = item.name
                        if name is not None and len(name) > 500: issue(slide_no, path, 'series_name_truncated')
                        clipped = []
                        for value in values[:200]:
                            if value is None or isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value): clipped.append(value)
                            else: clipped.append(None); issue(slide_no, path, 'unverified_cached_value')
                        record['series'].append({'index': index, 'name': name[:500] if name else name, 'values': clipped,
                                                 'values_total': value_count, 'values_truncated': value_count is not None and value_count > 200, 'references': refs})
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
                    result['charts'].append(record)
                except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError) as exc:
                    issue(slide_no, path, 'unsupported_chart'); result['charts'].append({'slide': slide_no, 'path': path, 'error': type(exc).__name__})
            return True
        # shortcut: bounded inventory of saved chart caches; add pagination and workbook reconciliation when supported.
        for slide_no in range(1, min(len(slides), 200) + 1):
            slide = slides[slide_no - 1]; visibility = slide._element.get('show')
            if visibility not in (None, '0', 'false', '1', 'true'): issue(slide_no, None, 'unknown_visibility')
            result['slides_scanned'] = slide_no
            if not walk(slide.shapes, slide_no, f'/slide[{slide_no}]', 0, visibility in ('0', 'false')): break
        if len(slides) > 200: issue(None, None, 'slide_limit')
        result['issues_truncated'] = result['issue_count'] > len(result['issues'])
        return result
