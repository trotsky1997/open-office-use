"""Local browser preview and visual selection for a versioned office session."""
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import selection_candidates
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
input{width:4.5rem}button,select,input,textarea{font:inherit}button{cursor:pointer}form p{flex-basis:100%}
#edit-path{width:min(28rem,80vw)}#edit-value{width:min(40rem,90vw);min-height:6rem}#edit-form label{display:flex;gap:.4rem;align-items:center}

</style></head><body><header><h1>Office session preview</h1><p id="status" role="status">Loading…</p><p id="selection" role="status">Drag on a page to save a selection for the agent.</p></header>
<details><summary>Restore a previous revision</summary><form id="restore-form">
<label for="restore-revision">Revision</label> <select id="restore-revision" required></select>
<button type="button" id="preview-revision">Preview selected revision</button><button type="button" id="show-latest">Show latest</button><button type="submit">Restore as new revision</button><p id="restore-status" role="status"></p></form></details>
<details id="candidate-panel"><summary>Find selected elements</summary>
<p>Matches use text and may be incomplete or ambiguous. Verify the target before editing.</p>
<button type="button" id="candidate-search" disabled>Find candidates</button><p id="candidate-status" role="status"></p><ul id="candidate-list"></ul></details>
<details id="edit-panel"><summary>Edit an element</summary><form id="edit-form">
<label>Element path <input id="edit-path" required maxlength="512" placeholder="/body/p[1]"></label>
<button type="button" id="edit-load">Load element</button>
<label>Kind <select id="edit-mode" disabled></select></label>
<label>Content <textarea id="edit-value" maxlength="4000" disabled></textarea></label>
<button type="submit" id="edit-save" disabled>Save as new revision</button>
<p>Replacing text can change run formatting. A cell value replaces its formula; numeric values may be converted by OfficeCLI. Use formula mode for expressions beginning with =.</p>
<p id="edit-status" role="status"></p></form></details>
<details><summary>Enter a selection with the keyboard</summary><form id="selection-form">
<label>Page <input name="page" type="number" min="1" required value="1"></label>
<label>Left % <input name="left" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Top % <input name="top" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Right % <input name="right" type="number" min="0" max="100" step="0.1" required value="90"></label>
<label>Bottom % <input name="bottom" type="number" min="0" max="100" step="0.1" required value="90"></label>
<button type="submit">Save selection</button></form></details>
<main id="pages" aria-label="Document pages"></main>
<script nonce="NONCE">
let current = -1, displayed = -1, pinned = null, viewKey = "", busy = false, loaded = null;
let savedSelection = null, selectionEpoch = 0;
function clearCandidates() {
 savedSelection=null; selectionEpoch++; document.getElementById('candidate-search').disabled=true;
 document.getElementById('candidate-list').replaceChildren(); document.getElementById('candidate-status').textContent='';
}
async function saveSelection(revision, page, coordinates) {
 clearCandidates(); const epoch=selectionEpoch;
 try {
  const response=await fetch('selection', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({revision,page,box:coordinates})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Selection failed');
  if (epoch !== selectionEpoch || revision !== current || pinned !== null) return;
  savedSelection=result; document.getElementById('candidate-search').disabled=false;
  document.getElementById('selection').textContent = `Selection saved · revision ${revision}, page ${page}`;
  document.querySelectorAll('.box').forEach(item => item.style.display='none');
  const selected = revision === current && document.querySelector(`.page[data-page="${page}"] .box`);
  if (selected) Object.assign(selected.style, {display:'block', left:`${coordinates[0]*100}%`, top:`${coordinates[1]*100}%`, width:`${(coordinates[2]-coordinates[0])*100}%`, height:`${(coordinates[3]-coordinates[1])*100}%`});
 } catch (error) { document.getElementById('selection').textContent = `Selection error: ${error.message}`; }
}
document.getElementById('candidate-search').addEventListener('click', async () => {
 if (!savedSelection || pinned !== null || savedSelection.revision !== current) return;
 const requested=savedSelection, epoch=selectionEpoch, button=document.getElementById('candidate-search'); button.disabled=true;
 document.getElementById('candidate-status').textContent='Finding candidates…';
 try {
  const response=await fetch('candidates', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({selection:requested})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Search failed');
  if (epoch !== selectionEpoch || pinned !== null || current !== result.revision) return;
  const list=document.getElementById('candidate-list'); list.replaceChildren();
  for (const item of result.candidates) {
   const row=document.createElement('li'); const label=document.createElement('span');
   label.textContent=`${item.type || 'element'} · ${item.path} · ${String(item.text || '').slice(0,200)}`;
   const use=document.createElement('button'); use.type='button'; use.textContent=`Use ${item.path}`;
   use.addEventListener('click', () => {
    if (epoch !== selectionEpoch || current !== result.revision || pinned !== null) return;
    document.getElementById('edit-panel').open=true; document.getElementById('edit-path').value=item.path;
    invalidateEdit('Load and verify this candidate.'); document.getElementById('edit-load').click();
   });
   row.append(label, document.createTextNode(' '), use); list.appendChild(row);
  }
  document.getElementById('candidate-status').textContent = result.candidates.length ? `${result.candidates.length} candidate(s). Verify the target; matches may be incomplete.` : 'No candidates found. Try a different selection or enter a path.';
 } catch (error) { if (epoch === selectionEpoch) document.getElementById('candidate-status').textContent=`Candidate error: ${error.message}`; }
 finally { if (epoch === selectionEpoch && pinned === null && savedSelection) button.disabled=false; }
});
function invalidateEdit(message) {
 loaded=null; document.getElementById('edit-save').disabled=true;
 document.getElementById('edit-mode').disabled=true; document.getElementById('edit-value').disabled=true;
 if (message) document.getElementById('edit-status').textContent=message;
}
document.getElementById('edit-path').addEventListener('input', () => invalidateEdit('Load the element before saving.'));
document.getElementById('edit-load').addEventListener('click', async () => {
 const button=document.getElementById('edit-load'); button.disabled=true; invalidateEdit('Loading…');
 try {
  const path=document.getElementById('edit-path').value;
  const response=await fetch('element', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:current,path})});
  const target=await response.json(); if (!response.ok) throw new Error(target.error || 'Could not load element');
  if (target.revision !== current || pinned !== null || document.getElementById('edit-path').value !== path) throw new Error('Version or path changed; load the element again.');
  loaded=target; document.getElementById('edit-path').value=target.path;
  const mode=document.getElementById('edit-mode'); const kinds=target.format==='xlsx' ? ['value','formula'] : ['text'];
  mode.replaceChildren(...kinds.map(kind=>{const option=document.createElement('option');option.value=kind;option.textContent=kind;return option;}));
  mode.value=target.mode; mode.disabled=false;
  const value=document.getElementById('edit-value'); value.disabled=false; value.value=target.value;
  document.getElementById('edit-save').disabled=false;
  document.getElementById('edit-status').textContent=`Loaded ${target.type} at revision ${target.revision}. Review content before saving.`;
 } catch (error) { invalidateEdit(`Load error: ${error.message}`); }
 finally { button.disabled = pinned !== null; }
});
document.getElementById('edit-form').addEventListener('submit', async event => {
 event.preventDefault(); if (!loaded || pinned !== null || loaded.revision !== current) { invalidateEdit('Version changed; load the element again.'); return; }
 const button=document.getElementById('edit-save'); button.disabled=true;
 try {
  const response=await fetch('edit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:loaded.revision,path:loaded.path,mode:document.getElementById('edit-mode').value,value:document.getElementById('edit-value').value})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Edit failed');
  invalidateEdit(`Saved as revision ${result.revision}.`); await refresh();
 } catch (error) { document.getElementById('edit-status').textContent=`Edit error: ${error.message}`; button.disabled=false; }
});
document.getElementById('restore-form').addEventListener('submit', async event => {
 event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true;
 try {
  const revision = Number(document.getElementById('restore-revision').value);
  const response = await fetch('restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:current, revision})});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Restore failed');
  document.getElementById('restore-status').textContent = `Restored revision ${revision} as revision ${result.revision}`;
  pinned=null; viewKey=''; await refresh();
 } catch (error) { document.getElementById('restore-status').textContent = `Restore error: ${error.message}`; }
 finally { button.disabled = false; }
});
document.getElementById('selection-form').addEventListener('submit', event => {
 event.preventDefault(); const data = new FormData(event.currentTarget);
 const page = Number(data.get('page'));
 const coordinates = ['left','top','right','bottom'].map(key => Number(data.get(key))/100);
 saveSelection(current, page, coordinates);
});
function selectable(image, page, revision, enabled) {
 const wrapper = document.createElement('div'); wrapper.className = 'page'; wrapper.dataset.page = String(page);
 const box = document.createElement('div'); box.className = 'box'; wrapper.append(image, box);
 if (!enabled) { wrapper.style.cursor='default'; return wrapper; }
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
function display(state, live) {
 const key = `${state.revision}:${live}`;
 if (key === viewKey) return;
 const fragment = document.createDocumentFragment();
 for (let i=0; i<state.pages; i++) {
  const image=document.createElement('img'); image.src=`page/${state.revision}/${i}`;
  image.alt=`Revision ${state.revision}, page ${i+1}`; image.loading='lazy'; image.draggable=false;
  fragment.appendChild(selectable(image, i+1, state.revision, live));
 }
 document.getElementById('pages').replaceChildren(fragment); displayed=state.revision; viewKey=key; clearCandidates();
 document.getElementById('selection').textContent = live ? 'Drag on a page to save a selection for the agent.' : 'Selections are available on the latest revision.';
 document.querySelectorAll('#selection-form input, #selection-form button, #edit-path, #edit-load').forEach(element => element.disabled=!live);
 if (!live) invalidateEdit('Return to the latest revision to edit.');
}
document.getElementById('preview-revision').addEventListener('click', async () => {
 const revision=Number(document.getElementById('restore-revision').value); pinned=revision;
 try {
  const response=await fetch(`revision/${revision}/state`, {cache:'no-store'}); const state=await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  if (pinned !== revision) return;
  display(state, false); document.getElementById('status').textContent=`Viewing revision ${revision} · latest ${current} · ${state.pages} page(s)`;
 } catch (error) { pinned=null; document.getElementById('restore-status').textContent=`Preview error: ${error.message}`; refresh(); }
});
document.getElementById('show-latest').addEventListener('click', () => { pinned=null; viewKey=''; refresh(); });
async function refresh() {
 if (busy) return; busy = true;
 try {
  const response = await fetch('state', {cache:'no-store'});
  const state = await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  if (state.revision !== current) {
   if (loaded) invalidateEdit('Version changed; load the element again.');
   const select=document.getElementById('restore-revision'); const previous=select.value;
   select.replaceChildren(...state.revisions.map(revision => {const option=document.createElement('option'); option.value=revision; option.textContent=`Revision ${revision}`; return option;}));
   if (state.revisions.some(revision => String(revision) === previous)) select.value=previous;
  }
  current=state.revision;
  if (pinned === null) {
   display(state, true); document.getElementById('status').textContent=`Revision ${current} · ${state.pages} page(s)`;
  } else if (displayed === pinned) {
   document.getElementById('status').textContent=`Viewing revision ${displayed} · latest ${current}`;
  }
 } catch (error) { document.getElementById('status').textContent = `Preview error: ${error.message}`; }
 finally { busy = false; }
}
refresh(); setInterval(refresh, 2000);
</script></body></html>'''


def serve(directory, preview, port=0, render=None):
    directory = session.info(directory)['directory']
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    token = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    lock = threading.Lock()
    cache = OrderedDict()
    with tempfile.TemporaryDirectory(prefix='office-watch-') as tmp:
        root = Path(tmp)

        def pages_for(state, revision):
            source = session.revision_file(state, revision)
            if revision not in cache:
                cache[revision] = preview(source, root / f'rev-{revision}')
                if len(cache) > 4:
                    old, _ = cache.popitem(last=False)
                    shutil.rmtree(root / f'rev-{old}', ignore_errors=True)
            cache.move_to_end(revision)
            return cache[revision]

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
                if route not in ('/' + token + '/selection', '/' + token + '/restore', '/' + token + '/element', '/' + token + '/edit', '/' + token + '/candidates'):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                length = self.headers.get('Content-Length', '')
                if self.headers.get('Content-Type') != 'application/json' or not length.isdecimal() or len(length) > 5 or not 0 < int(length) <= 20000:
                    self.send(400, b'Invalid request', 'text/plain; charset=utf-8'); return
                try:
                    payload = json.loads(self.rfile.read(int(length)))
                    if route.endswith('/candidates'):
                        if not isinstance(payload, dict) or set(payload) != {'selection'}:
                            raise ValueError('Candidates require a saved selection')
                        expected = session.validate_selection(payload['selection'])
                        with lock:
                            selected = session.get_selection(directory)
                            if selected['stale'] or any(selected[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                        if render is None:
                            raise RuntimeError('Candidate rendering is unavailable')
                        result = selection_candidates.candidates(directory, render)
                        with lock:
                            selected = session.get_selection(directory)
                            if selected['stale'] or result['stale'] or any(selected[key] != expected[key] for key in expected) or any(result[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                        self.send(200, json.dumps(result).encode(), 'application/json'); return
                    with lock:
                        if route.endswith('/selection'):
                            selection = session.validate_selection(payload)
                            pages = cache.get(selection['revision'])
                            if pages is None or selection['page'] > len(pages):
                                raise ValueError('Selection refers to an unavailable preview')
                            saved = session.set_selection(directory, selection)
                        elif route.endswith('/restore'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'revision'}:
                                raise ValueError('Restore requires base_revision and revision')
                            saved = session.restore(directory, payload['base_revision'], payload['revision'])
                        elif route.endswith('/element'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path'}:
                                raise ValueError('Element requires base_revision and path')
                            saved = session.edit_target(directory, payload['base_revision'], payload['path'])
                        else:
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'mode', 'value'}:
                                raise ValueError('Edit requires base_revision, path, mode and value')
                            saved = session.edit(directory, payload['base_revision'], payload['path'], payload['mode'], payload['value'])
                    self.send(200, json.dumps(saved).encode(), 'application/json')
                except (ValueError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
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
                history = re.fullmatch(r'revision/(\d{1,6})/state', route)
                page_match = re.fullmatch(r'page/(\d{1,6})/(\d{1,6})', route)
                if route == 'state' or history or page_match:
                    try:
                        with lock:
                            state = session.info(directory)
                            if history:
                                rev = int(history.group(1))
                            elif page_match:
                                rev = int(page_match.group(1))
                            else:
                                rev = state['latest_revision']
                            if rev > state['latest_revision']:
                                self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                            pages = pages_for(state, rev)
                            if page_match:
                                index = int(page_match.group(2))
                                if index >= len(pages):
                                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                                self.send(200, Path(pages[index]).read_bytes(), 'image/png'); return
                            data = {'revision': rev, 'pages': len(pages),
                                    'revisions': [item['revision'] for item in state['revisions']]}
                        self.send(200, json.dumps(data).encode(), 'application/json'); return
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        self.send(500, json.dumps({'error': str(exc)}).encode(), 'application/json'); return
                self.send(404, b'Not found', 'text/plain; charset=utf-8')

        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        try:
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/{token}/'}), flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
