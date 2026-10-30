"""Exercise versioned, run-preserving Word text replacement."""
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from PIL import Image
from lxml import etree

import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.docx'; draft = root / 'draft'
    image = root / 'image.png'; Image.new('RGB', (10, 10), 'red').save(image)
    doc = Document(); para = doc.add_paragraph(); para.add_run('Hello ').bold = True; para.add_run('world!').italic = True
    doc.add_paragraph('red red'); doc.add_paragraph('before\tafter'); doc.add_picture(str(image))
    marked = doc.add_paragraph('marked'); marker = OxmlElement('w:bookmarkStart'); marker.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id', '0'); marker.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}name', 'test'); marked._p.insert(0, marker)
    doc.save(source); original = source.read_bytes(); session.start(draft, source=source)
    for path, find in [('/body/p[2]', 'red'), ('/body/p[3]', 'before'), ('/body/p[5]', 'marked'), ('/body/p[1]', 'missing')]:
        try:
            session.replace_text(draft, 0, path, find, 'new')
            raise AssertionError('Unsafe or ambiguous replacement succeeded')
        except ValueError:
            pass
    assert session.info(draft)['latest_revision'] == 0
    result = session.replace_text(draft, 0, '/body/p[1]', 'llo wor', 'i earth')
    assert result['revision'] == 1 and source.read_bytes() == original
    revised = Document(result['file']); runs = revised.paragraphs[0].runs
    assert revised.paragraphs[0].text == 'Hei earthld!' and runs[0].bold and runs[1].italic
    assert runs[0].text == 'Hei earth' and runs[1].text == 'ld!'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(result['file']) as after:
        assert set(before.namelist()) == set(after.namelist())
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name != 'word/document.xml')
        assert before.read('word/document.xml') != after.read('word/document.xml')
        assert b"standalone='yes'" in before.read('word/document.xml')[:100]
        assert b"standalone='yes'" in after.read('word/document.xml')[:100]
        old_tree = etree.fromstring(before.read('word/document.xml')); new_tree = etree.fromstring(after.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        for tree in (old_tree, new_tree):
            for node in tree.xpath('/w:document/w:body/w:p[1]/w:r/w:t', namespaces=ns): node.text = 'MATCH'
        assert etree.tostring(old_tree, method='c14n') == etree.tostring(new_tree, method='c14n')

    signed = root / 'signed.docx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(signed, 'w') as dest:
        for item in src.infolist(): dest.writestr(item, src.read(item))
        dest.writestr('_xmlsignatures/sig1.xml', '<Signature/>')
    signed_draft = root / 'signed-draft'; session.start(signed_draft, source=signed)
    try:
        session.replace_text(signed_draft, 0, '/body/p[1]', 'Hello', 'Hi')
        raise AssertionError('Signed document accepted')
    except ValueError as error:
        assert 'signed' in str(error)
    assert session.info(signed_draft)['latest_revision'] == 0
    try:
        session.replace_text(draft, 0, '/body/p[1]', 'Hello', 'Bad')
        raise AssertionError('Stale revision accepted')
    except ValueError as error:
        assert 'conflict' in str(error)
    assert session.info(draft)['latest_revision'] == 1
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'table.docx'; draft = root / 'draft'; doc = Document()
    doc.add_paragraph('outside'); table = doc.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = 'merged'
    para = table.cell(0, 2).paragraphs[0]; para.add_run('Cell ').bold = True; para.add_run('value').italic = True
    para._p.set('{http://schemas.microsoft.com/office/word/2010/wordml}paraId', 'ABCDEF01')
    nested = table.cell(1, 1).add_table(rows=1, cols=1); nested.cell(0, 0).text = 'nested text'
    doc.save(source); session.start(draft, source=source)
    canonical = '/body/tbl[1]/tr[1]/tc[2]/p[1]'
    assert session.edit_target(draft, 0, canonical)['replace_text_path_supported']
    first = session.replace_text(draft, 0, '/body/table[1]/row[1]/cell[2]/p[1]', 'll va', 'LL VA')
    table_after = Document(first['file']).tables[0]; changed = table_after.cell(0, 2).paragraphs[0]
    assert changed.text == 'CeLL VAlue' and changed.runs[0].bold and changed.runs[1].italic
    assert table_after.cell(0, 0).text == 'merged'
    second = session.replace_text(draft, 1, '/body/tbl[1]/tr[2]/tc[2]/tbl[1]/tr[1]/tc[1]/p[1]', 'nested', 'inner')
    assert Document(second['file']).tables[0].cell(1, 1).tables[0].cell(0, 0).text == 'inner text'
    third = session.replace_text(draft, 2, '/body/tbl[1]/tr[1]/tc[2]/p[@paraId=ABCDEF01]', 'CeLL', 'Whole')
    assert Document(third['file']).tables[0].cell(0, 2).text == 'Whole VAlue'
    duplicate = root / 'duplicate.docx'; copy = Document(source); target = copy.tables[0].cell(0, 2)
    target.add_paragraph('duplicate')._p.set('{http://schemas.microsoft.com/office/word/2010/wordml}paraId', 'ABCDEF01'); copy.save(duplicate)
    other = root / 'duplicate-draft'; session.start(other, source=duplicate)
    try:
        session.replace_text(other, 0, '/body/tbl[1]/tr[1]/tc[2]/p[@paraId=ABCDEF01]', 'Cell', 'Wrong')
        raise AssertionError('Duplicate paragraph ID accepted')
    except ValueError as error:
        assert 'exactly one' in str(error)
    assert session.info(other)['latest_revision'] == 0
    for encoding in ('utf8-bom', 'utf16'):
        encoded = root / (encoding + '.docx')
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(encoded, 'w') as dest:
            for entry in src.infolist():
                data = src.read(entry)
                if entry.filename == 'word/document.xml':
                    if encoding == 'utf8-bom': data = b'\xef\xbb\xbf' + data
                    else: data = data.decode('utf-8').replace("encoding='UTF-8'", "encoding='UTF-16'").encode('utf-16')
                dest.writestr(entry, data)
        encoded_draft = root / (encoding + '-draft'); session.start(encoded_draft, source=encoded)
        replaced = session.replace_text(encoded_draft, 0, '/body/p[1]', 'outside', 'inside')
        assert Document(replaced['file']).paragraphs[0].text == 'inside'
        with zipfile.ZipFile(replaced['file']) as archive:
            assert b"standalone='yes'" in archive.read('word/document.xml')[:100]
print('Word replacement smoke passed: body, merged and nested tables, IDs and package preservation')
