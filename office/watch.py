"""Read-only local browser preview for a versioned office session."""
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
img{display:block;max-width:100%;height:auto;margin:1rem auto;background:white;box-shadow:0 2px 12px #0002}
</style></head><body><header><h1>Office session preview</h1><p id="status" role="status">Loading…</p></header>
<main id="pages" aria-label="Document pages"></main>
<script nonce="NONCE">
let current = -1, busy = false;
async function refresh() {
 if (busy) return; busy = true;
 try {
  const response = await fetch('state', {cache:'no-store'});
  const state = await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  document.getElementById('status').textContent = `Revision ${state.revision} · ${state.pages} page(s)`;
  if (state.revision !== current) {
   const fragment = document.createDocumentFragment();
   for (let i=0; i<state.pages; i++) {
    const image = document.createElement('img'); image.src = `page/${state.revision}/${i}`;
    image.alt = `Revision ${state.revision}, page ${i+1}`; image.loading = 'lazy'; fragment.appendChild(image);
   }
   document.getElementById('pages').replaceChildren(fragment); current = state.revision;
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
                            data = {'revision': rev, 'pages': len(cache['pages'])}
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
