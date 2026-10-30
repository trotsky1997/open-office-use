"""Exercise Word comment threading and uncertain metadata with an OOXML fixture."""
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from docx import Document

import word
import session
import officecli_backend

W = word.W
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
W15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
CID = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'
CEX = '{http://schemas.microsoft.com/office/word/2018/wordml/cex}'


def fixture(root, variant='normal'):
    root = Path(root); original = root / f'{variant}-original.docx'; result = root / f'{variant}.docx'
    doc = Document()
    for title in ('Original', 'Reply', 'Third'):
        paragraph = doc.add_paragraph(title); doc.add_comment(paragraph.runs[0], text=title + ' comment', author='Reviewer')
    doc.add_paragraph('Fresh paragraph'); doc.save(original)
    with zipfile.ZipFile(original) as src:
        comments = etree.fromstring(src.read('word/comments.xml'))
        for index, comment in enumerate(comments.findall(W + 'comment')):
            p = comment.findall(W + 'p')[-1]; p.set(W14 + 'paraId', f'{index+1:08X}')
        first = comments.findall(W + 'comment')[0]
        earlier = etree.Element(W + 'p'); earlier.set(W14 + 'paraId', '0A0ABBBB'); first.insert(0, earlier)
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
        if variant.startswith('modern'):
            ids = etree.Element(CID + 'commentsIds', nsmap={'w16cid': CID[1:-1]})
            cex = etree.Element(CEX + 'commentsExtensible', nsmap={'w16cex': CEX[1:-1]})
            for index in range(3):
                if variant == 'modern_missing_parent' and index == 0: continue
                durable = f'{index+101:08X}'
                etree.SubElement(ids, CID + 'commentId', {CID + 'paraId': f'{index+1:08X}', CID + 'durableId': durable})
                etree.SubElement(cex, CEX + 'commentExtensible', {CEX + 'durableId': durable, CEX + 'dateUtc': '2024-01-01T00:00:00Z'})
            if variant == 'modern_duplicate': etree.SubElement(ids, CID + 'commentId', {CID + 'paraId': '00000009', CID + 'durableId': '00000065'})
            if variant == 'modern_placeholder': cex.find(CEX + 'commentExtensible').set(CEX + 'intelligentPlaceholder', '1')
            if variant == 'modern_cex_duplicate': etree.SubElement(cex, CEX + 'commentExtensible', {CEX + 'durableId': '00000065'})
            if variant == 'modern_invalid_durable': ids.find(CID + 'commentId').set(CID + 'durableId', '7FFFFFFF')
            etree.SubElement(cex, CEX + 'extLst')
            if variant != 'modern_ext_only':
                etree.SubElement(rels, REL + 'Relationship', Id='rIdModernIDs', Type='http://schemas.microsoft.com/office/2016/09/relationships/commentsIds', Target='commentsIds.xml')
                etree.SubElement(types, CT + 'Override', PartName='/word/commentsIds.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.commentsIds+xml')
                changes['word/commentsIds.xml'] = etree.tostring(ids, encoding='UTF-8', xml_declaration=True)
            if variant != 'modern_ids_only':
                if variant != 'modern_unlinked':
                    etree.SubElement(rels, REL + 'Relationship', Id='rIdModernExtensible', Type='http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible', Target='commentsExtensible.xml')
                etree.SubElement(types, CT + 'Override', PartName='/word/commentsExtensible.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtensible+xml')
                changes['word/commentsExtensible.xml'] = b'<broken' if variant == 'modern_malformed' else etree.tostring(cex, encoding='UTF-8', xml_declaration=True)
            changes['word/_rels/document.xml.rels'] = etree.tostring(rels, encoding='UTF-8', xml_declaration=True)
            changes['[Content_Types].xml'] = etree.tostring(types, encoding='UTF-8', xml_declaration=True)
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
        source = Path(tmp) / 'normal.docx'; draft = Path(tmp) / 'thread-draft'; session.start(draft, source=source)
        opened = session.resolve_comment(draft, 0, a['id'], False)
        assert session.list_comments(draft, 1)['comments'][0]['resolved'] is False
        with zipfile.ZipFile(source) as before, zipfile.ZipFile(opened['file']) as after:
            assert set(before.namelist()) == set(after.namelist())
            assert all(before.read(name) == after.read(name) for name in before.namelist() if name != 'word/commentsExtended.xml')
        modern_reply_draft = Path(tmp) / 'modern-reply'; session.start(modern_reply_draft, source=opened['file'])
        new_reply = session.reply_comment(modern_reply_draft, 0, a['id'], 'Modern reply', 'Editor')
        listed = session.list_comments(modern_reply_draft, 1)
        assert listed['comments'][-1]['reply_to_comment_id'] == a['id'], listed
        with zipfile.ZipFile(opened['file']) as before, zipfile.ZipFile(new_reply['file']) as after:
            assert set(before.namelist()) == set(after.namelist())
            changed = {'word/document.xml', 'word/comments.xml', 'word/commentsExtended.xml'}
            assert all(before.read(name) == after.read(name) for name in before.namelist() if name not in changed)
        for variant in ('modern_both', 'modern_ids_only'):
            modern_source = fixture(tmp, variant); modern_draft = Path(tmp) / (variant + '-draft'); session.start(modern_draft, source=modern_source)
            session.resolve_comment(modern_draft, 0, '0', False)
            with zipfile.ZipFile(modern_draft / 'revision-000001.docx') as before:
                old_parts = {name: before.read(name) for name in before.namelist()}
            result = session.reply_comment(modern_draft, 1, '0', 'Durable reply', 'Editor')
            assert session.list_comments(modern_draft, 2)['comments'][-1]['reply_to_comment_id'] == '0'
            if variant == 'modern_both':
                validation = officecli_backend.audit(result['file'])['validation']; assert validation['exit_code'] == 0, validation
            with zipfile.ZipFile(result['file']) as after:
                ids = etree.fromstring(after.read('word/commentsIds.xml')); records = ids.findall(CID + 'commentId')
                assert len(records) == 4
                latest = records[-1]; pid = latest.get(CID + 'paraId'); durable = latest.get(CID + 'durableId')
                assert 0 < int(durable, 16) < 0x7fffffff and len({node.get(CID + 'durableId') for node in records}) == 4
                comments = etree.fromstring(after.read('word/comments.xml')); new_comment = comments.findall(W + 'comment')[-1]
                assert new_comment.findall(W + 'p')[-1].get(W14 + 'paraId') == pid
                changed = {'word/document.xml', 'word/comments.xml', 'word/commentsExtended.xml', 'word/commentsIds.xml'}
                if variant == 'modern_both':
                    changed.add('word/commentsExtensible.xml'); cex = etree.fromstring(after.read('word/commentsExtensible.xml'))
                    assert cex[-1].tag == CEX + 'extLst' and cex[-2].get(CEX + 'durableId') == durable and cex[-2].get(CEX + 'dateUtc')
                assert all(after.read(name) == data for name, data in old_parts.items() if name not in changed)
        for variant in ('modern_duplicate', 'modern_missing_parent', 'modern_ext_only', 'modern_malformed', 'modern_placeholder', 'modern_cex_duplicate', 'modern_invalid_durable', 'modern_unlinked'):
            bad_file = fixture(tmp, variant); bad_draft = Path(tmp) / (variant + '-draft'); session.start(bad_draft, source=bad_file)
            session.resolve_comment(bad_draft, 0, '0', False)
            try: session.reply_comment(bad_draft, 1, '0', 'Rejected', 'Editor')
            except ValueError: pass
            else: raise AssertionError(f'{variant} metadata was accepted')
            assert session.info(bad_draft)['latest_revision'] == 1
        for variant in ('normal', 'modern_both', 'modern_ids_only'):
            new_source = fixture(tmp, variant); new_draft = Path(tmp) / (variant + '-root-draft'); session.start(new_draft, source=new_source)
            anchor = 'paragraph' if variant == 'modern_both' else None
            added = session.add_comment(new_draft, 0, '/body/p[4]', 'New root\nSecond line', 'Editor', anchor)
            added_listing = session.list_comments(new_draft, 1); item = added_listing['comments'][-1]
            assert item['resolved'] is False and item['reply_parent_status'] == 'root' and item['anchor_text'] == (anchor or 'Fresh paragraph'), added_listing
            with zipfile.ZipFile(new_source) as before, zipfile.ZipFile(added['file']) as after:
                old_parts = {name: before.read(name) for name in before.namelist()}
                comment_nodes = etree.fromstring(after.read('word/comments.xml')).findall(W + 'comment')
                new_para = comment_nodes[-1].findall(W + 'p')[-1].get(W14 + 'paraId')
                ex = etree.fromstring(after.read('word/commentsExtended.xml'))
                assert ex[-1].get(W15 + 'paraId') == new_para and ex[-1].get(W15 + 'paraIdParent') is None
                changed = {'word/document.xml', 'word/comments.xml', 'word/commentsExtended.xml'}
                if variant != 'normal':
                    changed.add('word/commentsIds.xml'); ids = etree.fromstring(after.read('word/commentsIds.xml'))
                    assert ids[-1].get(CID + 'paraId') == new_para
                    if variant == 'modern_both':
                        changed.add('word/commentsExtensible.xml'); cex = etree.fromstring(after.read('word/commentsExtensible.xml'))
                        assert cex[-2].get(CEX + 'durableId') == ids[-1].get(CID + 'durableId')
                assert all(after.read(name) == data for name, data in old_parts.items() if name not in changed)
            if variant == 'modern_both':
                validation = officecli_backend.audit(added['file'])['validation']; assert validation['exit_code'] == 0, validation
        for variant in ('modern_duplicate', 'modern_ext_only', 'modern_malformed', 'modern_cex_duplicate', 'modern_invalid_durable', 'modern_unlinked'):
            bad_source = fixture(tmp, variant); bad_root = Path(tmp) / (variant + '-root-draft'); session.start(bad_root, source=bad_source)
            try: session.add_comment(bad_root, 0, '/body/p[4]', 'Rejected', 'Editor')
            except ValueError: pass
            else: raise AssertionError(f'{variant} root comment metadata was accepted')
            assert session.info(bad_root)['latest_revision'] == 0
        for bad_id in (b['id'], c['id'], '999'):
            try: session.resolve_comment(draft, 1, bad_id, True)
            except ValueError: pass
            else: raise AssertionError('Invalid or reply comment state accepted')
        assert session.info(draft)['latest_revision'] == 1
        duplicate_file = fixture(tmp, 'duplicate_record'); duplicate_draft = Path(tmp) / 'duplicate-draft'; session.start(duplicate_draft, source=duplicate_file)
        try: session.resolve_comment(duplicate_draft, 0, a['id'], False)
        except ValueError: pass
        else: raise AssertionError('Ambiguous comment metadata accepted')
        duplicate = word.list_comments(fixture(tmp, 'duplicate_record')); assert duplicate['comments'][0]['thread_metadata'] == 'ambiguous' and duplicate['comments'][0]['resolved'] is None
        same_para = word.list_comments(fixture(tmp, 'duplicate_comment_para')); assert same_para['comments'][0]['thread_metadata'] == 'ambiguous' and same_para['comments'][1]['thread_metadata'] == 'ambiguous'
        invalid = word.list_comments(fixture(tmp, 'invalid_done')); assert invalid['comments'][2]['thread_metadata'] == 'invalid' and invalid['comments'][2]['resolved'] is None
        broken = word.list_comments(fixture(tmp, 'malformed')); assert broken['thread_metadata_status'] == 'invalid' and all(item['resolved'] is None for item in broken['comments'])
    print('Thread comment smoke passed: resolution, parents and uncertain metadata')
