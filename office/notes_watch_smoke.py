"""Check the viewer's speaker notes routes and revision protection."""
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from pptx import Presentation
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'deck.pptx'; draft = root / 'draft'
    deck = Presentation(); deck.slides.add_slide(deck.slide_layouts[1]); deck.save(source)
    session.start(draft, source=source)
    cli = Path(__file__).with_name('open_office_use.py')
    server = subprocess.Popen([sys.executable, str(cli), 'watch', str(draft)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = json.loads(server.stdout.readline())['url']; origin = 'http://' + urlsplit(url).netloc
        def post(route, data, origin=origin):
            request = urllib.request.Request(url + route, data=json.dumps(data).encode(), headers={'Origin': origin, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response: return json.load(response)
        assert not post('notes-read', {'revision': 0, 'slide': 1})['has_notes_slide']
        assert post('notes-replace', {'base_revision': 0, 'slide': 1, 'text': 'Notes'})['revision'] == 1
        assert post('notes-read', {'revision': 1, 'slide': 1})['text'] == 'Notes'
        search = {'revision': 1, 'query': 'Notes', 'scope': 'notes', 'offset': 0, 'snapshot_sha256': None}
        found = post('text-search', search)
        assert found['scope'] == 'notes' and found['matches'][0]['notes_paragraph'] == 1
        try: post('text-search', search, 'http://evil.test'); raise AssertionError('Cross-origin search accepted')
        except urllib.error.HTTPError as exc: assert exc.code == 403
        assert post('notes-replace-text', {'base_revision': 1, 'slide': 1, 'paragraph': 1, 'find': 'Notes', 'replacement': 'Edited'})['revision'] == 2
        assert post('notes-read', {'revision': 2, 'slide': 1})['text'] == 'Edited'
        diff = post('notes-comparison', {'before': 1, 'after': 2, 'before_slide': 1, 'after_slide': 1})
        assert diff['text_changed'] and '-Notes' in diff['diff'] and '+Edited' in diff['diff']
        for route, data, request_origin, code in [
            ('notes-replace', {'base_revision': 0, 'slide': 1, 'text': 'Stale'}, origin, 400),
            ('notes-replace', {'base_revision': 2, 'slide': 1, 'text': 'Forbidden'}, 'http://evil.test', 403),
            ('notes-read', {'revision': 1, 'slide': 0}, origin, 400),
            ('notes-comparison', {'before': 0, 'after': 1, 'before_slide': 1, 'after_slide': 1}, origin, 400),
        ]:
            try: post(route, data, request_origin)
            except urllib.error.HTTPError as exc: assert exc.code == code, exc
            else: raise AssertionError('Invalid request accepted')
        assert session.info(draft)['latest_revision'] == 2
    finally:
        server.terminate(); server.wait(timeout=10)
print('Speaker notes viewer routes passed: read, save, stale revision and origin checks')
