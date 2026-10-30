"""Verify version-bound single-element edits against real OfficeCLI."""
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation

import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for suffix in ('.docx', '.xlsx', '.pptx'):
        source = root / ('source' + suffix); draft = root / suffix[1:]
        if suffix == '.docx':
            obj = Document(); obj.add_paragraph('Original'); obj.save(source)
            path, mode, value = '/body/p[1]', 'text', 'Changed'
        elif suffix == '.xlsx':
            obj = Workbook(); obj.active['A1'] = '=1+2'; obj.save(source)
            path, mode, value = '/Sheet/A1', 'formula', '=2+3'
        else:
            obj = Presentation(); slide = obj.slides.add_slide(obj.slide_layouts[1]); slide.shapes.title.text = 'Original'; obj.save(source)
            path, mode, value = '/slide[1]/shape[1]', 'text', 'Changed'
        original = source.read_bytes()
        session.start(draft, source=source)
        target = session.edit_target(draft, 0, path)
        assert target['revision'] == 0 and target['mode'] == mode
        if suffix == '.xlsx':
            assert target['value'] == '=1+2'
        else:
            assert target['value'] == 'Original'
        edited = session.edit(draft, 0, target['path'], mode, value)
        assert edited['revision'] == 1 and source.read_bytes() == original
        after = session.edit_target(draft, 1, target['path'])
        assert after['value'] == value, after
        if suffix == '.xlsx':
            assert load_workbook(edited['file']).active['A1'].value == '=2+3'
        try:
            session.edit(draft, 0, path, mode, value)
            raise AssertionError('stale edit succeeded')
        except ValueError as error:
            assert 'conflict' in str(error)
        try:
            session.edit(draft, 1, path, 'invalid', value)
            raise AssertionError('invalid mode succeeded')
        except ValueError:
            pass
        if suffix == '.xlsx':
            try:
                session.edit(draft, 1, path, 'value', '=7+8')
                raise AssertionError('formula in value mode succeeded')
            except ValueError as error:
                assert 'formula mode' in str(error)
        assert session.info(draft)['latest_revision'] == 1
print('Editor smoke passed: docx, xlsx formula, pptx, stale and invalid edits')
