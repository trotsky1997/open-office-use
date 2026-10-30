"""Reorder slides while retaining each slide's parts and notes."""
import tempfile
import zipfile
import subprocess
import sys
from lxml import etree
from pathlib import Path
from pptx import Presentation
import officecli_backend
import open_office_use
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root/'deck.pptx'; draft = root/'draft'
    open_office_use.author({'slides':[{'title':'First','notes':'Notes one'}, {'title':'Second','notes':'Notes two'}, {'title':'Third','notes':'Notes three'}]},source)
    session.start(draft, source=source)
    result = session.reorder_slides(draft, 0, [3,1,2]); result_file = Path(result['file'])
    deck = Presentation(result_file)
    assert [slide.shapes.title.text for slide in deck.slides] == ['Third','First','Second']
    assert [slide.notes_slide.notes_text_frame.text for slide in deck.slides] == ['Notes three','Notes one','Notes two']
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(result_file) as changed:
        assert original.namelist() == changed.namelist()
        assert all(original.read(name) == changed.read(name) for name in original.namelist() if name != 'ppt/presentation.xml')
    code, validation, _ = officecli_backend.invoke('validate', result_file); assert code == 0 and validation['success']
    pdf = open_office_use.render(result_file, root/'render')
    rendered = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True).stdout.split('\f')
    assert ['Third','First','Second'] == [next(name for name in ('First','Second','Third') if name in page) for page in rendered if page.strip()]
    for order in ([1,1,2], [1,2], [True,2,3]):
        try: session.reorder_slides(draft, 1, order)
        except ValueError: pass
        else: raise AssertionError('Invalid order accepted')
    try: session.reorder_slides(draft, 0, [1,2,3])
    except ValueError as exc: assert 'conflict' in str(exc)
    else: raise AssertionError('Stale revision accepted')
    assert session.info(draft)['latest_revision'] == 1
    cli = subprocess.run([sys.executable, str(Path(open_office_use.__file__)), 'session', 'reorder-slides', str(draft), '--base', '1', '--order', '[2,3,1]'], capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert [slide.shapes.title.text for slide in Presentation(draft/'revision-000002.pptx').slides] == ['First','Second','Third']
    extended = root/'extended.pptx'
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(extended, 'w') as modified:
        for item in original.infolist():
            data = original.read(item)
            if item.filename == 'ppt/presentation.xml':
                tree = etree.fromstring(data); etree.SubElement(tree, '{http://schemas.openxmlformats.org/presentationml/2006/main}extLst'); data = etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)
            modified.writestr(item, data)
    extended_draft = root/'extended-draft'; session.start(extended_draft, source=extended)
    try: session.reorder_slides(extended_draft, 0, [3,1,2])
    except ValueError as exc: assert 'extensions' in str(exc)
    else: raise AssertionError('Presentation extensions accepted')
    assert session.info(extended_draft)['latest_revision'] == 0
print('Slide reorder passed: notes, package preservation, validation and conflicts')
