"""Search and safely edit ordinary Word footnote and endnote paragraphs."""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from docx import Document
import officecli_backend
import session
import word

W = word.W; R = word.R; REL = word.REL
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); raw = root / 'raw.docx'; source = root / 'notes.docx'
    doc = Document(); doc.add_paragraph('Main text'); doc.save(raw)
    with zipfile.ZipFile(raw) as before, zipfile.ZipFile(source, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'word/document.xml':
                tree = etree.fromstring(data); paragraph = tree.find(W + 'body/' + W + 'p')
                for kind, number in (('footnote', '1'), ('endnote', '2')):
                    run = etree.SubElement(paragraph, W + 'r'); etree.SubElement(run, W + kind + 'Reference', {W + 'id': number})
                data = etree.tostring(tree)
            if entry.filename == 'word/_rels/document.xml.rels':
                tree = etree.fromstring(data)
                for kind in ('footnotes', 'endnotes'): etree.SubElement(tree, REL + 'Relationship', Id='test-' + kind, Type=R[1:-1] + '/' + kind, Target=kind + '.xml')
                data = etree.tostring(tree)
            if entry.filename == '[Content_Types].xml':
                tree = etree.fromstring(data)
                for kind in ('footnotes', 'endnotes'): etree.SubElement(tree, CT + 'Override', PartName='/word/' + kind + '.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.' + kind + '+xml')
                data = etree.tostring(tree)
            after.writestr(entry, data)
        for kind, number in (('footnote', '1'), ('endnote', '2')):
            tree = etree.Element(W + kind + 's', nsmap={'w': W[1:-1]})
            separator = etree.SubElement(tree, W + kind, {W + 'type':'separator', W + 'id':'-1'})
            etree.SubElement(separator, W + 'p')
            note = etree.SubElement(tree, W + kind, {W + 'id':number}); paragraph = etree.SubElement(note, W + 'p')
            run = etree.SubElement(paragraph, W + 'r'); etree.SubElement(run, W + kind + 'Ref')
            for text, bold in ((kind + ' ', True), ('needle', False)):
                run = etree.SubElement(paragraph, W + 'r')
                if bold: etree.SubElement(etree.SubElement(run, W + 'rPr'), W + 'b')
                etree.SubElement(run, W + 't').text = text
            after.writestr('word/' + kind + 's.xml', etree.tostring(tree))
    result = word.search_notes(source, 'needle')
    assert result['complete'] and [m['path'] for m in result['matches']] == ['/footnote[@id=1]/p[1]', '/endnote[@id=2]/p[1]']
    draft = root / 'draft'; session.start(draft, source=source)
    target = session.edit_target(draft, 0, result['matches'][0]['path'])
    assert target['replace_only'] and target['note_impact']['kind'] == 'footnote'
    edited = session.replace_text(draft, 0, target['path'], 'needle', 'target')
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(edited['file']) as after:
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name != 'word/footnotes.xml')
        tree = etree.fromstring(after.read('word/footnotes.xml')); paragraph = tree.findall(W + 'footnote')[1].find(W + 'p')
        assert paragraph.find('.//' + W + 'footnoteRef') is not None and paragraph.find('.//' + W + 'b') is not None
        assert ''.join(node.text or '' for node in paragraph.iter(W + 't')) == 'footnote target'
    assert officecli_backend.audit(edited['file'])['validation']['exit_code'] == 0
    cli = Path(__file__).with_name('open_office_use.py')
    output = subprocess.run([sys.executable, str(cli), 'search-word', str(source), '--scope', 'notes', '--query', 'needle'], text=True, capture_output=True, check=True)
    assert len(json.loads(output.stdout)['matches']) == 2
    output = subprocess.run([sys.executable, str(cli), 'session', 'search-word', str(draft), '--revision', '1', '--scope', 'notes', '--query', 'target'], text=True, capture_output=True, check=True)
    assert json.loads(output.stdout)['matches'][0]['path'] == target['path']
    paged = root / 'paged.docx'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(paged, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'word/footnotes.xml':
                tree = etree.fromstring(data); note = tree.findall(W + 'footnote')[1]
                for i in range(104):
                    paragraph = etree.SubElement(note, W + 'p'); run = etree.SubElement(paragraph, W + 'r'); etree.SubElement(run, W + 't').text = f'needle {i}'
                data = etree.tostring(tree)
            after.writestr(entry, data)
    first = word.search_notes(paged, 'needle'); assert len(first['matches']) == 100 and first['next_offset'] is not None
    second = word.search_notes(paged, 'needle', first['next_offset'], first['snapshot_sha256']); assert second['scan_complete'] and len(second['matches']) == 6
    duplicate = root / 'duplicate.docx'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(duplicate, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'word/footnotes.xml':
                tree = etree.fromstring(data); tree.append(etree.fromstring(etree.tostring(tree.findall(W + 'footnote')[1]))); data = etree.tostring(tree)
            after.writestr(entry, data)
    try: word.search_notes(duplicate, 'needle')
    except ValueError: pass
    else: raise AssertionError('Duplicate note ID accepted')
    try: word.find_paragraph(word.ooxml.parse_xml(etree.tostring(tree)), '/footnote[@id=1]/p[1]')
    except ValueError: pass
    else: raise AssertionError('Ambiguous note target accepted')
    try: word.search_notes(edited['file'], 'needle', 1, result['snapshot_sha256'])
    except ValueError: pass
    else: raise AssertionError('Changed snapshot accepted')
print('Word notes search smoke passed: footnotes, endnotes, markers, formatting and snapshot safety')
