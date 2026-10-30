"""Check Word comment insertion and package preservation."""
import tempfile
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import officecli_backend
import session
import word

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.docx'; draft = root / 'draft'
    doc = Document(); para = doc.add_paragraph(); para.add_run('Important ').bold = True; para.add_run('text').italic = True
    table = doc.add_table(rows=1, cols=1); table.cell(0, 0).text = 'Table value'
    tracked = doc.add_paragraph('Track '); inserted = OxmlElement('w:ins'); inserted.set(qn('w:id'), '2'); inserted.set(qn('w:author'), 'Author'); tracked._p.append(inserted)
    doc.save(source); original = source.read_bytes(); session.start(draft, source=source)
    first = session.add_comment(draft, 0, '/body/p[1]', 'Please review\nSecond line', 'Reviewer')
    assert first['comment_id'] == 0
    result = Document(first['file']); comments = list(result.comments)
    assert len(comments) == 1 and comments[0].author == 'Reviewer' and comments[0].text == 'Please review\nSecond line'
    assert result.paragraphs[0].text == 'Important text' and result.paragraphs[0].runs[0].bold and result.paragraphs[0].runs[1].italic
    assert source.read_bytes() == original
    validation = officecli_backend.audit(first['file'])['validation']; assert validation['exit_code'] == 0, validation
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(first['file']) as b:
        changed = {'word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'}
        assert set(b.namelist()) == set(a.namelist()) | {'word/comments.xml'}
        assert all(a.read(name) == b.read(name) for name in a.namelist() if name not in changed)
    second = session.add_comment(draft, 1, '/body/table[1]/row[1]/cell[1]/p[1]', 'Review table', 'Editor')
    assert second['comment_id'] == 1
    listing = session.list_comments(draft, 2)
    assert listing['total_comments'] == 2 and listing['anchor_scan_complete'], listing
    assert listing['comments'][0]['text'] == 'Please review\nSecond line' and listing['comments'][0]['anchor_text'] == 'Important text', listing
    assert listing['comments'][0]['paragraph_paths'] == ['/body/p[1]'] and listing['comments'][0]['anchor_status'] == 'range', listing
    assert listing['comments'][1]['paragraph_paths'] == ['/body/tbl[1]/tr[1]/tc[1]/p[1]'] and listing['comments'][1]['anchor_text'] == 'Table value', listing
    assert word.list_comments(source)['total_comments'] == 0
    comments = list(Document(second['file']).comments)
    assert len(comments) == 2 and comments[1].text == 'Review table'
    for base, path in [(1, '/body/p[1]'), (2, '/body/p[1]'), (2, '/body/p[2]')]:
        try: session.add_comment(draft, base, path, 'rejected', 'Reviewer')
        except ValueError: pass
        else: raise AssertionError('Stale or unsupported paragraph accepted')
    assert session.info(draft)['latest_revision'] == 2
    external = Document(); old_paragraph = external.add_paragraph(); old_run = old_paragraph.add_run('Already reviewed')
    external.add_comment(old_run, text='Existing comment', author='Other'); external.add_paragraph('Another paragraph')
    external_file = root / 'existing.docx'; external.save(external_file); external_draft = root / 'existing-draft'; session.start(external_draft, source=external_file)
    external_result = session.add_comment(external_draft, 0, '/body/p[2]', 'New comment', 'Reviewer')
    assert [item.text for item in Document(external_result['file']).comments] == ['Existing comment', 'New comment']
    external_listing = word.list_comments(external_result['file']); assert external_listing['comments'][0]['anchor_text'] == 'Already reviewed', external_listing
    spanning = Document(); p1 = spanning.add_paragraph('First anchor'); p2 = spanning.add_paragraph('Second anchor')
    spanning.add_comment([p1.runs[0], p2.runs[0]], text='Cross paragraph', author='Reviewer')
    span_file = root / 'span.docx'; spanning.save(span_file); item = word.list_comments(span_file)['comments'][0]
    assert item['anchor_text'] == 'First anchor\nSecond anchor' and item['paragraph_paths'] == ['/body/p[1]', '/body/p[2]'], item
    assert item['anchor_status'] == 'range'
    many = Document()
    for number in range(201):
        paragraph = many.add_paragraph(str(number)); many.add_comment(paragraph.runs[0], text=f'Comment {number}', author='Reviewer')
    many_file = root / 'many.docx'; many.save(many_file); many_result = word.list_comments(many_file)
    assert many_result['total_comments'] == 201 and len(many_result['comments']) == 200 and many_result['truncated']
    cli = Path(__file__).with_name('open_office_use.py')
    listed_cli = subprocess.run([sys.executable, str(cli), 'session', 'comments', str(draft), '--revision', '2'], check=True, capture_output=True, text=True)
    assert json.loads(listed_cli.stdout)['total_comments'] == 2
    cli_draft = root / 'cli-draft'; session.start(cli_draft, source=source)
    subprocess.run([sys.executable, str(Path(__file__).with_name('open_office_use.py')), 'session', 'add-comment', str(cli_draft), '--base', '0', '--path', '/body/p[1]', '--text', 'CLI review', '--author', 'Editor'], check=True, capture_output=True)
    assert next(iter(Document(cli_draft / 'revision-000001.docx').comments)).text == 'CLI review'
print('Comment smoke passed: new and existing comments, tables, formatting and conflicts')
