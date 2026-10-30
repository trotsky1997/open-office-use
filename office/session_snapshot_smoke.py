"""Reject source changes before session or OfficeCLI publication."""
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from docx import Document
from openpyxl import Workbook
import officecli_backend
import ooxml
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
    source = root/'ooxml-source.docx'; source.write_bytes(original.read_bytes()); output = root/'ooxml-output.docx'
    other = root/'other.docx'; replacement = Document(); replacement.add_paragraph('different'); replacement.save(other)
    def select_and_replace_live(snapshot_file):
        source.write_bytes(other.read_bytes())
        assert Document(snapshot_file).paragraphs[0].text == 'source'
        return 'word/document.xml'
    ooxml.edit_xml(source, output, select_and_replace_live, lambda tree, archive: None)
    assert Document(output).paragraphs[0].text == 'source' and Document(source).paragraphs[0].text == 'different'
    output = root/'ooxml-rejected.docx'; source.write_bytes(original.read_bytes())
    reject(source, lambda: ooxml.edit_xml(source, output, lambda file: 'word/document.xml', lambda tree, archive: None))
    assert not output.exists()
    book = Workbook(); book.active['A1'] = 'Original'; workbook = root/'source.xlsx'; book.save(workbook)
    book.active['A1'] = 'Changed'; changed = root/'changed.xlsx'; book.save(changed)
    real_read_grid = session.read_grid
    for mode in ('edit', 'format'):
        draft = root/('grid-' + mode); session.start(draft, source=workbook)
        revision = draft/'revision-000000.xlsx'
        def read_then_change(*args):
            result = real_read_grid(*args); revision.write_bytes(changed.read_bytes()); return result
        with patch.object(session, 'read_grid', side_effect=read_then_change):
            try:
                if mode == 'edit': session.edit_grid(draft, 0, 'Sheet', 'A1', [{'cell':'A1','value':'Updated'}])
                else: session.format_grid(draft, 0, 'Sheet', 'A1', 'A1', {'bold':True})
            except ValueError as exc: assert 'snapshot changed' in str(exc)
            else: raise AssertionError('Changed grid source accepted')
        assert session.info(draft)['latest_revision'] == 0
print('Session snapshot smoke passed: start, batch, apply, restore and export')
