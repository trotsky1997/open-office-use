"""Local browser preview and visual selection for a versioned office session."""
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import session

PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Office session preview</title><style>
body{margin:0;font:16px system-ui,sans-serif;background:#eef1f4;color:#182333}
header{position:sticky;top:0;background:#fff;padding:1rem 1.5rem;border-bottom:1px solid #ccd3da;z-index:1}
h1{font-size:1.1rem;margin:0 0 .3rem}p{margin:0;color:#48596b}main{max-width:1050px;margin:1.5rem auto;padding:0 1rem}
.page{position:relative;width:fit-content;max-width:100%;margin:1rem auto;touch-action:none;cursor:crosshair}
img{display:block;max-width:100%;height:auto;background:white;box-shadow:0 2px 12px #0002}
.box{position:absolute;border:2px solid #0867c4;background:#087dd126;pointer-events:none;display:none;box-sizing:border-box}
details{margin:.6rem 1.5rem;background:#fff;border:1px solid #ccd3da;border-radius:.4rem;padding:.65rem .8rem}
summary{cursor:pointer;font-weight:600}form{display:flex;align-items:center;gap:.65rem;flex-wrap:wrap;padding-top:.6rem}
input{width:4.5rem}button,select,input{font:inherit}button{cursor:pointer}form p{flex-basis:100%}

</style></head><body><header><h1>Office session preview</h1><p id="status" role="status">Loading…</p><p id="selection" role="status">Drag on a page to save a selection for the agent.</p></header>
<details><summary>Restore a previous revision</summary><form id="restore-form">
<label for="restore-revision">Revision</label> <select id="restore-revision" required></select>
<button type="submit">Restore as new revision</button><p id="restore-status" role="status"></p></form></details>
<details><summary>Enter a selection with the keyboard</summary><form id="selection-form">
<label>Page <input name="page" type="number" min="1" required value="1"></label>
<label>Left % <input name="left" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Top % <input name="top" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Right % <input name="right" type="number" min="0" max="100" step="0.1" required value="90"></label>
<label>Bottom % <input name="bottom" type="number" min="0" max="100" step="0.1" required value="90"></label>
<button type="submit">Save selection</button></form></details>
<main id="pages" aria-label="Document pages"></main>
<script nonce="NONCE">
let current = -1, busy = false;
async function saveSelection(revision, page, coordinates) {
 try {
  const response=await fetch('selection', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({revision,page,box:coordinates})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Selection failed');
  document.getElementById('selection').textContent = `Selection saved · revision ${revision}, page ${page}`;
  document.querySelectorAll('.box').forEach(item => item.style.display='none');
  const selected = revision === current && document.querySelector(`.page[data-page="${page}"] .box`);
  if (selected) Object.assign(selected.style, {display:'block', left:`${coordinates[0]*100}%`, top:`${coordinates[1]*100}%`, width:`${(coordinates[2]-coordinates[0])*100}%`, height:`${(coordinates[3]-coordinates[1])*100}%`});
 } catch (error) { document.getElementById('selection').textContent = `Selection error: ${error.message}`; }
}
document.getElementById('restore-form').addEventListener('submit', async event => {
 event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true;
 try {
  const revision = Number(document.getElementById('restore-revision').value);
  const response = await fetch('restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:current, revision})});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Restore failed');
  document.getElementById('restore-status').textContent = `Restored revision ${revision} as revision ${result.revision}`;
  await refresh();
 } catch (error) { document.getElementById('restore-status').textContent = `Restore error: ${error.message}`; }
 finally { button.disabled = false; }
});
document.getElementById('selection-form').addEventListener('submit', event => {
 event.preventDefault(); const data = new FormData(event.currentTarget);
 const page = Number(data.get('page'));
 const coordinates = ['left','top','right','bottom'].map(key => Number(data.get(key))/100);
 saveSelection(current, page, coordinates);
});
function selectable(image, page, revision) {
 const wrapper = document.createElement('div'); wrapper.className = 'page'; wrapper.dataset.page = String(page);
 const box = document.createElement('div'); box.className = 'box'; wrapper.append(image, box);
 let start = null;
 function point(event) {
  const rect = image.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)), Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))];
 }
 function draw(end) {
  const left = Math.min(start[0],end[0]), top = Math.min(start[1],end[1]);
  const right = Math.max(start[0],end[0]), bottom = Math.max(start[1],end[1]);
  Object.assign(box.style, {display:'block', left:`${left*100}%`, top:`${top*100}%`, width:`${(right-left)*100}%`, height:`${(bottom-top)*100}%`});
  return [left, top, right, bottom];
 }
 wrapper.addEventListener('pointerdown', event => { if (event.button !== 0) return; start=point(event); wrapper.setPointerCapture(event.pointerId); event.preventDefault(); });
 wrapper.addEventListener('pointermove', event => { if (start) draw(point(event)); });
 wrapper.addEventListener('pointercancel', () => { start=null; box.style.display='none'; });
 wrapper.addEventListener('pointerup', async event => {
  if (!start) return; const coordinates=draw(point(event)); start=null;
  if (coordinates[2]-coordinates[0] < .005 || coordinates[3]-coordinates[1] < .005) { box.style.display='none'; return; }
  await saveSelection(revision, page, coordinates);
 });
 return wrapper;
}
async function refresh() {
 if (busy) return; busy = true;
 try {
  const response = await fetch('state', {cache:'no-store'});
  const state = await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  document.getElementById('status').textContent = `Revision ${state.revision} · ${state.pages} page(s)`;
  if (state.revision !== current) {
   const select = document.getElementById('restore-revision'); const previous = select.value;
   select.replaceChildren(...state.revisions.map(revision => {const option=document.createElement('option'); option.value=revision; option.textContent=`Revision ${revision}`; return option;}));
   if (state.revisions.some(revision => String(revision) === previous)) select.value=previous;
   const fragment = document.createDocumentFragment();
   for (let i=0; i<state.pages; i++) {
    const image = document.createElement('img'); image.src = `page/${state.revision}/${i}`;
    image.alt = `Revision ${state.revision}, page ${i+1}`; image.loading = 'lazy'; image.draggable = false; fragment.appendChild(selectable(image, i+1, state.revision));
   }
   document.getElementById('pages').replaceChildren(fragment); current = state.revision;
   document.getElementById('selection').textContent = 'Drag on a page to save a selection for the agent.';
  }
 } catch (error) { document.getElementById('status').textContent = `Preview error: ${error.message}`; }
 finally { busy = false; }
}
refresh(); setInterval(refresh, 2000);
</script></body></html>'''


def serve(directory, preview, port=0):
    directory = session.info(directory)['directory']
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    token = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    lock = threading.Lock()
    cache = {'revision': -1, 'pages': []}
    with tempfile.TemporaryDirectory(prefix='office-watch-') as tmp:
        root = Path(tmp)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def send(self, status, body, content_type):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', f"default-src 'none'; img-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                port = cast(ThreadingHTTPServer, self.server).server_port
                host = f'127.0.0.1:{port}'
                if self.headers.get('Host') != host or self.headers.get('Origin') != 'http://' + host:
                    self.send(403, b'Forbidden', 'text/plain; charset=utf-8'); return
                route = urlsplit(self.path).path
                if route not in ('/' + token + '/selection', '/' + token + '/restore'):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                length = self.headers.get('Content-Length', '')
                if self.headers.get('Content-Type') != 'application/json' or not length.isdecimal() or len(length) > 4 or not 0 < int(length) <= 4096:
                    self.send(400, b'Invalid request', 'text/plain; charset=utf-8'); return
                try:
                    payload = json.loads(self.rfile.read(int(length)))
                    with lock:
                        if route.endswith('/selection'):
                            selection = session.validate_selection(payload)
                            if selection['revision'] != cache['revision'] or selection['page'] > len(cache['pages']):
                                raise ValueError('Selection refers to an unavailable preview')
                            saved = session.set_selection(directory, selection)
                        else:
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'revision'}:
                                raise ValueError('Restore requires base_revision and revision')
                            saved = session.restore(directory, payload['base_revision'], payload['revision'])
                    self.send(200, json.dumps(saved).encode(), 'application/json')
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    self.send(400, json.dumps({'error': str(exc)}).encode(), 'application/json')

            def do_GET(self):
                expected_host = f'127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}'
                if self.headers.get('Host') != expected_host:
                    self.send(403, b'Forbidden', 'text/plain; charset=utf-8'); return
                path = urlsplit(self.path).path
                prefix = '/' + token + '/'
                if not path.startswith(prefix):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                route = path[len(prefix):]
                if route == '':
                    self.send(200, PAGE.replace('NONCE', nonce).encode(), 'text/html; charset=utf-8'); return
                if route == 'state':
                    try:
                        with lock:
                            state = session.info(directory)
                            rev = state['latest_revision']
                            if rev != cache['revision']:
                                pages = preview(session.revision_file(state, rev), root / f'rev-{rev}')
                                old = cache['revision']
                                cache.update(revision=rev, pages=pages)
                                if old >= 0:
                                    shutil.rmtree(root / f'rev-{old}', ignore_errors=True)
                            data = {'revision': rev, 'pages': len(cache['pages']),
                                    'revisions': [item['revision'] for item in state['revisions']]}
                        self.send(200, json.dumps(data).encode(), 'application/json'); return
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        self.send(500, json.dumps({'error': str(exc)}).encode(), 'application/json'); return
                match = re.fullmatch(r'page/(\d+)/(\d+)', route)
                if match:
                    with lock:
                        rev, index = map(int, match.groups())
                        if rev == cache['revision'] and index < len(cache['pages']):
                            self.send(200, Path(cache['pages'][index]).read_bytes(), 'image/png'); return
                self.send(404, b'Not found', 'text/plain; charset=utf-8')

        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        try:
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/{token}/'}), flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
