"""Reject source changes before session or OfficeCLI publication."""
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from docx import Document
import officecli_backend
import session
import snapshot

real_sha256 = hashlib.sha256
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); original = root / 'original.docx'
    document = Document(); document.add_paragraph('source'); document.save(original)
    class MutatingDigest:
        def __init__(self, source): self.inner = real_sha256(); self.source = source
        def update(self, block):
            self.inner.update(block)
            if self.source:
                with self.source.open('r+b') as stream:
                    stream.seek(-1, 2); value = stream.read(1); stream.seek(-1, 2); stream.write(bytes([value[0] ^ 1]))
                self.source = None
        def hexdigest(self): return self.inner.hexdigest()
    def reject(source, action):
        with patch.object(snapshot.hashlib, 'sha256', side_effect=lambda: MutatingDigest(source)):
            try: action()
            except ValueError as exc: assert 'changed while creating snapshot' in str(exc)
            else: raise AssertionError('Concurrent source write accepted')
    source = root / 'start.docx'; source.write_bytes(original.read_bytes())
    reject(source, lambda: session.start(root / 'failed-draft', source=source))
    assert not (root / 'failed-draft').exists()
    source = root / 'batch.docx'; source.write_bytes(original.read_bytes()); output = root / 'batch-output.docx'
    reject(source, lambda: officecli_backend.batch([], output, source))
    assert not output.exists()
    for kind in ('restore', 'export', 'apply'):
        draft = root / kind; session.start(draft, source=original); source = draft / 'revision-000000.docx'
        output = root / 'export.docx'
        actions = {'restore': lambda: session.restore(draft, 0, 0),
                   'export': lambda: session.export(draft, 0, output),
                   'apply': lambda: session.apply(draft, 0, [])}
        reject(source, actions[kind])
        assert session.info(draft)['latest_revision'] == 0 and not output.exists()
print('Session snapshot smoke passed: start, batch, apply, restore and export')
