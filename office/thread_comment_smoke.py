"""Exercise Word comment threading and uncertain metadata with an OOXML fixture."""
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from docx import Document

import word

W = word.W
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
W15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'


def fixture(root, variant='normal'):
    root = Path(root); original = root / f'{variant}-original.docx'; result = root / f'{variant}.docx'
    doc = Document()
    for title in ('Original', 'Reply', 'Third'):
        paragraph = doc.add_paragraph(title); doc.add_comment(paragraph.runs[0], text=title + ' comment', author='Reviewer')
    doc.save(original)
    with zipfile.ZipFile(original) as src:
        comments = etree.fromstring(src.read('word/comments.xml'))
        for index, comment in enumerate(comments.findall(W + 'comment')):
            p = comment.findall(W + 'p')[-1]; p.set(W14 + 'paraId', f'{index+1:08X}')
        first = comments.findall(W + 'comment')[0]
        earlier = etree.Element(W + 'p'); earlier.set(W14 + 'paraId', 'AAAABBBB'); first.insert(0, earlier)
        if variant == 'duplicate_comment_para': comments.findall(W + 'comment')[1].findall(W + 'p')[-1].set(W14 + 'paraId', '00000001')
        rels = etree.fromstring(src.read('word/_rels/document.xml.rels'))
        etree.SubElement(rels, REL + 'Relationship', Id='rIdOfficeThread', Type='http://schemas.microsoft.com/office/2011/relationships/commentsExtended', Target='commentsExtended.xml')
        types = etree.fromstring(src.read('[Content_Types].xml'))
        etree.SubElement(types, CT + 'Override', PartName='/word/commentsExtended.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml')
        ext = etree.Element(W15 + 'commentsEx', nsmap={'w15': W15[1:-1]})
        etree.SubElement(ext, W15 + 'commentEx', {W15 + 'paraId': '00000001', W15 + 'done': '1'})
        etree.SubElement(ext, W15 + 'commentEx', {W15 + 'paraId': '00000002', W15 + 'paraIdParent': '00000001'})
        etree.SubElement(ext, W15 + 'commentEx', {W15 + 'paraId': '00000003', W15 + 'done': 'bogus' if variant == 'invalid_done' else '0', W15 + 'paraIdParent': 'DEADBEEF'})
        if variant == 'duplicate_record': etree.SubElement(ext, W15 + 'commentEx', {W15 + 'paraId': '00000001', W15 + 'done': '0'})
        changes = {'word/comments.xml': etree.tostring(comments, encoding='UTF-8', xml_declaration=True),
                   'word/_rels/document.xml.rels': etree.tostring(rels, encoding='UTF-8', xml_declaration=True),
                   '[Content_Types].xml': etree.tostring(types, encoding='UTF-8', xml_declaration=True),
                   'word/commentsExtended.xml': b'<invalid' if variant == 'malformed' else etree.tostring(ext, encoding='UTF-8', xml_declaration=True)}
        with zipfile.ZipFile(result, 'w') as dst:
            for item in src.infolist(): dst.writestr(item, changes.pop(item.filename, src.read(item.filename)))
            for name, data in changes.items(): dst.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return result


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        normal = word.list_comments(fixture(tmp)); assert normal['thread_metadata_status'] == 'available', normal
        a, b, c = normal['comments']
        assert a['resolved'] is True and a['reply_parent_status'] == 'root', a
        assert b['resolved'] is False and b['reply_to_comment_id'] == a['id'] and b['reply_parent_status'] == 'matched', b
        assert c['resolved'] is False and c['reply_to_paragraph_id'] == 'DEADBEEF' and c['reply_parent_status'] == 'unresolved', c
        duplicate = word.list_comments(fixture(tmp, 'duplicate_record')); assert duplicate['comments'][0]['thread_metadata'] == 'ambiguous' and duplicate['comments'][0]['resolved'] is None
        same_para = word.list_comments(fixture(tmp, 'duplicate_comment_para')); assert same_para['comments'][0]['thread_metadata'] == 'ambiguous' and same_para['comments'][1]['thread_metadata'] == 'ambiguous'
        invalid = word.list_comments(fixture(tmp, 'invalid_done')); assert invalid['comments'][2]['thread_metadata'] == 'invalid' and invalid['comments'][2]['resolved'] is None
        broken = word.list_comments(fixture(tmp, 'malformed')); assert broken['thread_metadata_status'] == 'invalid' and all(item['resolved'] is None for item in broken['comments'])
    print('Thread comment smoke passed: resolution, parents and uncertain metadata')
