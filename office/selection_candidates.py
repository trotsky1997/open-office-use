"""Find textual OfficeCLI candidates for a visual selection."""
import shutil
import tempfile
from pathlib import Path

import officecli_backend
import selection_text
import session


def candidates(directory, render):
    selected = selection_text.extract(directory, render)
    lines = []
    for line in selected['text'].splitlines():
        phrase = ' '.join(line.split())[:200]
        if phrase and phrase not in lines:
            lines.append(phrase)
        if len(lines) == 3:
            break
    state = session.info(directory)
    source = session.revision_file(state, selected['revision'])
    found = {}
    with tempfile.TemporaryDirectory(prefix='office-selection-candidates-') as tmp:
        snapshot = Path(tmp) / ('document' + source.suffix)
        shutil.copyfile(source, snapshot)
        for phrase in lines:
            result = officecli_backend.call('query', snapshot, '*', '--find=' + phrase)
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
    latest = session.info(directory)['latest_revision']
    return {'revision': selected['revision'], 'page': selected['page'], 'box': selected['box'],
            'latest_revision': latest, 'stale': selected['revision'] != latest,
            'search_text': lines, 'selection_text_truncated': selected['truncated'],
            'candidates': list(found.values())[:50], 'returned_candidate_count': len(found),
            'candidates_truncated': len(found) > 50, 'requires_verification': True,
            'method': 'text_search', 'search_exhaustive': False}
