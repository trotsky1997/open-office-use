"""Find textual OfficeCLI candidates for a visual selection."""
import tempfile

import officecli_backend
import layout
import selection_text
import session
import snapshot


def candidates(directory, render):
    selection = session.get_selection(directory)
    state = session.info(directory); source = session.revision_file(state, selection['revision'])
    with tempfile.TemporaryDirectory(prefix='office-selection-candidates-') as tmp:
        frozen, digest = snapshot.copy(source, tmp)
        return _candidates_from_snapshot(directory, render, selection, frozen, digest)


def _candidates_from_snapshot(directory, render, selection, frozen, digest):
    selected = selection_text.extract(directory, render, selection=selection, frozen=frozen, digest=digest)
    lines = []
    for line in selected['text'].splitlines():
        phrase = ' '.join(line.split())[:200]
        if phrase and phrase not in lines:
            lines.append(phrase)
        if len(lines) == 3:
            break
    source = frozen
    found = {}
    geometry = None
    if source.suffix.lower() == '.pptx':
        report = layout.inspect(source, {'page': selected['page'], 'box': selected['box']})
        width, height = report['slide_size_inches']
        pdf_width, pdf_height = selected['pdf_page_size']
        # shortcut: hidden slides disable page mapping; map exported slide identities when available.
        if (report['visibility_known'] and not report['hidden_slides'] and
                selected['pdf_page_count'] == report['slides_total'] and
                abs((pdf_width / pdf_height) / (width / height) - 1) <= 0.015):
            geometry = report
            for item in sorted(report['selection_matches'], key=lambda item: item['selection_overlap_fraction'], reverse=True):
                path = item['path_hint']
                found[path] = {'path': path, 'type': path.rsplit('/', 1)[-1].split('[')[0],
                               'text': item.get('text_preview', ''), 'text_truncated': item.get('text_truncated', False),
                               'matched_text': [], 'geometry_match': True,
                               'selection_overlap_fraction': item['selection_overlap_fraction']}
    for phrase in lines:
        result = officecli_backend.call('query', source, '*', '--find=' + phrase)
        if not isinstance(result, dict) or not isinstance(result.get('results'), list):
            raise RuntimeError('OfficeCLI returned an unexpected query result')
        for item in result['results']:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                continue
            path = item['path']
            if path not in found:
                text = item.get('text')
                found[path] = {'path': path, 'type': item.get('type'),
                               'text': text[:2000] if isinstance(text, str) else text,
                               'text_truncated': isinstance(text, str) and len(text) > 2000, 'matched_text': []}
            if phrase not in found[path]['matched_text']:
                found[path]['matched_text'].append(phrase)
    current = session.get_selection(directory); latest = current['latest_revision']
    return {'revision': selected['revision'], 'page': selected['page'], 'box': selected['box'],
            'latest_revision': latest, 'stale': selected['revision'] != latest,
            'selection_changed': selected['selection_changed'] or any(selected[key] != current[key] for key in ('revision', 'page', 'box')), 'render_advisory': selected['render_advisory'], 'snapshot_sha256': digest,
            'search_text': lines, 'selection_text_truncated': selected['truncated'],
            'candidates': list(found.values())[:50], 'returned_candidate_count': len(found),
            'candidates_truncated': len(found) > 50 or bool(geometry and geometry['selection_match_count'] > len(geometry['selection_matches'])), 'requires_verification': True,
            'method': 'geometry_and_text_search' if geometry else 'text_search', 'search_exhaustive': False,
            'geometry_available': geometry is not None,
            'geometry_complete': geometry['geometry_complete'] if geometry else None,
            'geometry_match_count': geometry['selection_match_count'] if geometry else None,
            'geometry_truncated': geometry['selection_match_count'] > len(geometry['selection_matches']) if geometry else None}
