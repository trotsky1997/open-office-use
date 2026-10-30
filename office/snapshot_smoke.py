"""Check snapshot identity and detection of writes during copying."""
import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import snapshot

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.docx'; source.write_bytes(b'a' * (1024 * 1024 + 17))
    out = root / 'out'; out.mkdir()
    frozen, digest = snapshot.copy(source, out)
    assert frozen.read_bytes() == source.read_bytes() and digest == hashlib.sha256(source.read_bytes()).hexdigest()
    frozen.unlink()
    real_sha256 = hashlib.sha256
    class MutatingDigest:
        def __init__(self, action): self.inner = real_sha256(); self.action = action
        def update(self, block):
            self.inner.update(block)
            if self.action: action, self.action = self.action, None; action()
        def hexdigest(self): return self.inner.hexdigest()
    def modify():
        with source.open('r+b') as stream: stream.seek(-1, 2); stream.write(b'b')
    def replace():
        other = root / 'other'; other.write_bytes(b'c' * source.stat().st_size); os.replace(other, source)
    for action in (modify, replace):
        with patch.object(snapshot.hashlib, 'sha256', side_effect=lambda: MutatingDigest(action)):
            try: snapshot.copy(source, out)
            except ValueError as exc: assert 'changed while creating snapshot' in str(exc)
            else: raise AssertionError('Concurrent source change accepted')
        assert not (out / source.name).exists()
print('Snapshot smoke passed: stable data, concurrent writes and replacement')
