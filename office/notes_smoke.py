"""Exercise speaker notes creation, editing and version safety."""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from pptx import Presentation
import notes
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'deck.pptx'; draft = root / 'draft'
    presentation = Presentation(); slide = presentation.slides.add_slide(presentation.slide_layouts[1]); slide.shapes.title.text = 'Title'; presentation.save(source)
    assert not notes.read(source, 1)['has_notes_slide']
    session.start(draft, source=source)
    one = session.replace_notes(draft, 0, 1, 'Opening\nSecond line')
    assert session.read_notes(draft, 0, 1)['text'] == ''
    assert session.read_notes(draft, 1, 1)['text'] == 'Opening\nSecond line'
    two = session.replace_notes(draft, 1, 1, 'Updated speaker notes')
    assert session.read_notes(draft, 2, 1)['text'] == 'Updated speaker notes'
    assert Presentation(two['file']).slides[0].shapes.title.text == 'Title'
    with zipfile.ZipFile(one['file']) as a, zipfile.ZipFile(two['file']) as b:
        changed = {name for name in a.namelist() if a.read(name) != b.read(name)}
        assert len(changed) == 1 and next(iter(changed)).startswith('ppt/notesSlides/'), changed
    try: session.replace_notes(draft, 0, 1, 'stale')
    except ValueError as exc: assert 'Revision conflict' in str(exc)
    else: raise AssertionError('Stale edit succeeded')
    assert session.info(draft)['latest_revision'] == 2
    cli = Path(__file__).with_name('open_office_use.py')
    read = subprocess.run([sys.executable, str(cli), 'session', 'notes', str(draft), '--revision', '1', '--slide', '1'], capture_output=True, text=True, check=True)
    assert json.loads(read.stdout)['text'] == 'Opening\nSecond line'
    payload = root / 'notes.txt'; payload.write_text('CLI edit', encoding='utf-8')
    subprocess.run([sys.executable, str(cli), 'session', 'replace-notes', str(draft), '--base', '2', '--slide', '1', '--text-file', str(payload)], capture_output=True, text=True, check=True)
    assert session.read_notes(draft, 3, 1)['text'] == 'CLI edit'
print('Speaker notes smoke passed: create, replace, CLI and revision safety')
