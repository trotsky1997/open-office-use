"""Conservative, targeted text replacement in a saved Word document."""
import re
from pathlib import Path

import ooxml

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
W14_PARAGRAPH_ID = '{http://schemas.microsoft.com/office/word/2010/wordml}paraId'
INDEX = r'[1-9][0-9]{0,5}'
PATH = re.compile(r'/body(?:(?:/(?:tbl|table)\[' + INDEX + r'\]/(?:tr|row)\[' + INDEX + r'\]/(?:tc|cell)\[' + INDEX + r'\])){0,8}/p(?:\[' + INDEX + r'\]|\[@paraId=[0-9A-Fa-f]{8}\])\Z')
SEGMENT = re.compile(r'/(tbl|table|tr|row|tc|cell|p)\[([^]]+)\]')


def paragraph_path(path):
    return isinstance(path, str) and len(path) <= 512 and PATH.fullmatch(path) is not None


def find_paragraph(tree, path):
    if tree.getroot().tag != W + 'document':
        raise ValueError('Document XML has an invalid root')
    paragraph = tree.getroot().find(W + 'body')
    if paragraph is None:
        raise ValueError('Document has no body')
    aliases = {'table': 'tbl', 'row': 'tr', 'cell': 'tc'}
    for tag, selector in SEGMENT.findall(path):
        candidates = paragraph.findall(W + aliases.get(tag, tag))
        if selector.startswith('@paraId='):
            requested = selector.partition('=')[2].upper()
            candidates = [item for item in candidates if item.get(W14_PARAGRAPH_ID, '').upper() == requested]
            if len(candidates) != 1:
                raise ValueError('Paragraph ID must identify exactly one paragraph in its container')
            paragraph = candidates[0]
        else:
            index = int(selector) - 1
            if index >= len(candidates):
                raise ValueError('Target paragraph path does not exist')
            paragraph = candidates[index]
    return paragraph


def replace_text(source, output, path, find, replacement):
    if not paragraph_path(path):
        raise ValueError('Target must be a body or table paragraph path such as /body/p[1]')
    if Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Text replacement requires DOCX input and output')

    def edit(tree, archive):
        paragraph = find_paragraph(tree, path)
        groups, current = [], []

        def boundary():
            if current:
                groups.append(current[:]); current.clear()

        def add_run(run):
            tags = {child.tag for child in run}
            if tags <= {W + 'rPr', W + 'commentReference'} and W + 'commentReference' in tags:
                boundary(); return
            if not tags <= {W + 'rPr', W + 't'}:
                raise ValueError('Paragraph contains unsupported run content such as fields, tabs or images')
            current.extend(run.findall(W + 't'))

        markers = {W + name for name in ('bookmarkStart', 'bookmarkEnd', 'commentRangeStart', 'commentRangeEnd', 'proofErr')}
        for child in paragraph:
            if child.tag == W + 'pPr':
                continue
            if child.tag == W + 'r':
                add_run(child)
            elif child.tag == W + 'hyperlink':
                boundary()
                if any(run.tag != W + 'r' for run in child):
                    raise ValueError('Hyperlink contains unsupported content')
                for run in child:
                    add_run(run)
                boundary()
            elif child.tag in markers:
                boundary()
            else:
                raise ValueError('Paragraph contains unsupported structures such as fields or tracked changes')
        boundary()
        text = ''.join(node.text or '' for group in groups for node in group)
        start = ooxml.match_index(text, find, replacement); end = start + len(find); offset = 0
        for group in groups:
            length = sum(len(node.text or '') for node in group)
            if offset <= start and end <= offset + length:
                ooxml.replace_nodes(group, find, replacement, preserve_space=True)
                return
            offset += length
        raise ValueError('Match crosses a hyperlink or annotation boundary')

    return ooxml.edit_xml(source, output, lambda _: 'word/document.xml', edit)


def add_comment(source, output, path, text, author):
    """Attach a plain-text comment to all runs of a simple body paragraph."""
    import posixpath
    import uuid
    from datetime import datetime, timezone
    from lxml import etree

    if not paragraph_path(path) or Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Target must be a DOCX body or table paragraph path')
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or any(ord(c) < 32 and c != '\n' for c in text):
        raise ValueError('Comment must contain 1 to 4,000 characters without control characters')
    if not isinstance(author, str) or not author.strip() or len(author) > 100 or any(ord(c) < 32 for c in author):
        raise ValueError('Author must contain 1 to 100 characters without control characters')
    rel_ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    type_ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    comments_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
    rel_path = 'word/_rels/document.xml.rels'
    created_id = None

    def edit(tree, archive):
        nonlocal created_id
        paragraph = find_paragraph(tree, path)
        runs = []
        for child in paragraph:
            if child.tag == W + 'pPr':
                continue
            if child.tag != W + 'r' or any(node.tag not in (W + 'rPr', W + 't') for node in child):
                raise ValueError('Comment requires a simple paragraph without fields, links, existing anchors or tracked changes')
            runs.append(child)
        if not runs or not ''.join(node.text or '' for run in runs for node in run.findall(W + 't')).strip():
            raise ValueError('Comment requires a nonempty paragraph')
        names = set(archive.namelist())
        rel_bytes = archive.read(rel_path) if rel_path in names else None
        rel_tree = ooxml.parse_xml(rel_bytes) if rel_bytes else etree.ElementTree(etree.Element(rel_ns + 'Relationships', nsmap={None: rel_ns[1:-1]}))
        if rel_tree.getroot().tag != rel_ns + 'Relationships':
            raise ValueError('Invalid document relationships')
        relationships = rel_tree.getroot().findall(rel_ns + 'Relationship')
        links = [item for item in relationships if item.get('Type') == comments_type]
        if len(links) > 1:
            raise ValueError('Multiple comments relationships are not supported')
        additional = {}
        if links:
            link = links[0]
            if link.get('TargetMode') == 'External' or not link.get('Target'):
                raise ValueError('Invalid comments relationship')
            target = link.get('Target')
            comments_part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
            if not comments_part.startswith('word/') or comments_part not in names:
                raise ValueError('Invalid comments part')
            original = archive.read(comments_part); comments = ooxml.parse_xml(original)
        else:
            comments_part = 'word/comments.xml'
            if comments_part in names:
                raise ValueError('Unreferenced comments part already exists')
            original = None; comments = etree.ElementTree(etree.Element(W + 'comments', nsmap={'w': W[1:-1]}))
            rid = 'rIdOfficeUse' + uuid.uuid4().hex
            if any(item.get('Id') == rid for item in relationships):
                raise ValueError('Relationship identifier collision')
            etree.SubElement(rel_tree.getroot(), rel_ns + 'Relationship', Id=rid, Type=comments_type, Target='comments.xml')
            additional[rel_path] = ooxml.serialize_xml(rel_tree, rel_bytes) if rel_bytes else etree.tostring(rel_tree, encoding='UTF-8', xml_declaration=True)
            type_bytes = archive.read('[Content_Types].xml'); types = ooxml.parse_xml(type_bytes)
            if types.getroot().tag != type_ns + 'Types' or any(item.get('PartName') == '/' + comments_part for item in types.getroot()):
                raise ValueError('Invalid or conflicting package content types')
            etree.SubElement(types.getroot(), type_ns + 'Override', PartName='/' + comments_part,
                             ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml')
            additional['[Content_Types].xml'] = ooxml.serialize_xml(types, type_bytes)
        if comments.getroot().tag != W + 'comments':
            raise ValueError('Invalid comments XML')
        used = []
        for item in list(comments.getroot().findall(W + 'comment')) + list(tree.getroot().iter(W + 'commentRangeStart')) + list(tree.getroot().iter(W + 'commentRangeEnd')) + list(tree.getroot().iter(W + 'commentReference')):
            value = item.get(W + 'id')
            if value is None or not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 2147483646:
                raise ValueError('Unsupported comment identifier')
            used.append(int(value))
        comment_id = str(max(used, default=-1) + 1); created_id = int(comment_id)
        comment = etree.SubElement(comments.getroot(), W + 'comment', {W + 'id': comment_id, W + 'author': author, W + 'date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})
        for line in text.split('\n'):
            p = etree.SubElement(comment, W + 'p'); r = etree.SubElement(p, W + 'r'); t = etree.SubElement(r, W + 't')
            if line.startswith(' ') or line.endswith(' '):
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            t.text = line
        start = etree.Element(W + 'commentRangeStart', {W + 'id': comment_id})
        end = etree.Element(W + 'commentRangeEnd', {W + 'id': comment_id})
        first, last = runs[0], runs[-1]
        first.addprevious(start); last.addnext(end)
        reference_run = etree.Element(W + 'r'); props = etree.SubElement(reference_run, W + 'rPr')
        etree.SubElement(props, W + 'rStyle', {W + 'val': 'CommentReference'})
        etree.SubElement(reference_run, W + 'commentReference', {W + 'id': comment_id}); end.addnext(reference_run)
        additional[comments_part] = ooxml.serialize_xml(comments, original) if original else etree.tostring(comments, encoding='UTF-8', xml_declaration=True)
        return additional

    file = ooxml.edit_xml(source, output, lambda _: 'word/document.xml', edit, allow_new=True)
    return {'file': file, 'comment_id': created_id}


def comment_thread_metadata(archive, relationships, nodes):
    """Associate Word 2013 comment metadata by each comment's final paragraph ID."""
    import posixpath
    from collections import defaultdict
    from lxml import etree

    w15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
    rel_type = 'http://schemas.microsoft.com/office/2011/relationships/commentsExtended'
    links = [item for item in relationships if item.get('Type') == rel_type]
    if not links:
        return {}, 'unreferenced' if 'word/commentsExtended.xml' in archive.namelist() else 'absent'
    if len(links) != 1 or links[0].get('TargetMode') == 'External' or not links[0].get('Target'):
        return {}, 'invalid'
    target = links[0].get('Target')
    part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
    if not part.startswith('word/') or part not in archive.namelist():
        return {}, 'invalid'
    try:
        extended = ooxml.parse_xml(archive.read(part))
    except (KeyError, ValueError, etree.XMLSyntaxError):
        return {}, 'invalid'
    if extended.getroot().tag != w15 + 'commentsEx':
        return {}, 'invalid'
    para_ids = defaultdict(list); record_ids = defaultdict(list)
    for node in nodes:
        paragraphs = list(node.iter(W + 'p'))
        para_id = paragraphs[-1].get(W14_PARAGRAPH_ID) if paragraphs else None
        if para_id and re.fullmatch(r'[0-9A-Fa-f]{8}', para_id):
            para_ids[para_id.upper()].append(node.get(W + 'id'))
    for item in extended.getroot().findall(w15 + 'commentEx'):
        para_id = item.get(w15 + 'paraId')
        if para_id and re.fullmatch(r'[0-9A-Fa-f]{8}', para_id):
            record_ids[para_id.upper()].append(item)
    result = {}
    for para_id, comment_ids in para_ids.items():
        records = record_ids.get(para_id, [])
        if len(comment_ids) != 1 or len(records) != 1:
            for comment_id in comment_ids:
                result[comment_id] = {'thread_metadata': 'ambiguous' if len(comment_ids) > 1 or len(records) > 1 else 'missing'}
            continue
        record = records[0]; done = record.get(w15 + 'done', '0')
        parent = record.get(w15 + 'paraIdParent')
        values = {'0': False, 'false': False, 'off': False, '1': True, 'true': True, 'on': True}
        if done not in values or (parent is not None and not re.fullmatch(r'[0-9A-Fa-f]{8}', parent)):
            result[comment_ids[0]] = {'thread_metadata': 'invalid'}; continue
        parent = parent.upper() if parent else None
        parent_ids = para_ids.get(parent, []) if parent else []
        if parent == para_id:
            result[comment_ids[0]] = {'thread_metadata': 'invalid', 'reply_to_paragraph_id': parent, 'reply_parent_status': 'invalid'}; continue
        result[comment_ids[0]] = {'thread_metadata': 'matched', 'resolved': values[done],
                                  'reply_to_paragraph_id': parent,
                                  'reply_to_comment_id': parent_ids[0] if len(parent_ids) == 1 else None,
                                  'reply_parent_status': ('root' if parent is None else 'matched' if len(parent_ids) == 1 else 'unresolved' if not parent_ids else 'ambiguous')}
    return result, 'available'


def list_comments(source):
    """Read Word comments and bounded main-body anchor hints without modifying the file."""
    import posixpath
    import zipfile
    from lxml import etree

    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.docx' or source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Comment inspection requires a DOCX up to 128 MiB')
    rel_ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    comments_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist(); names = [item.filename for item in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(item.file_size for item in entries) > 128 * 1024 * 1024:
                raise ValueError('Document exceeds package limits or contains duplicate parts')
            document = ooxml.parse_xml(archive.read('word/document.xml'))
            if document.getroot().tag != W + 'document': raise ValueError('Invalid Word XML')
            body = document.getroot().find(W + 'body')
            if body is None: raise ValueError('Document has no body')
            rel_path = 'word/_rels/document.xml.rels'
            if rel_path not in names:
                if 'word/comments.xml' in names: raise ValueError('Unreferenced comments part')
                return {'total_comments': 0, 'comments': [], 'truncated': False, 'anchor_scan_complete': True, 'thread_metadata_status': 'absent'}
            rels = ooxml.parse_xml(archive.read(rel_path))
            if rels.getroot().tag != rel_ns + 'Relationships': raise ValueError('Invalid document relationships')
            links = [item for item in rels.getroot().findall(rel_ns + 'Relationship') if item.get('Type') == comments_type]
            if not links:
                if 'word/comments.xml' in names: raise ValueError('Unreferenced comments part')
                return {'total_comments': 0, 'comments': [], 'truncated': False, 'anchor_scan_complete': True, 'thread_metadata_status': 'absent'}
            if len(links) != 1 or links[0].get('TargetMode') == 'External' or not links[0].get('Target'):
                raise ValueError('Invalid comments relationship')
            target = links[0].get('Target')
            part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
            if not part.startswith('word/') or part not in names: raise ValueError('Invalid comments part')
            comments = ooxml.parse_xml(archive.read(part))
            if comments.getroot().tag != W + 'comments': raise ValueError('Invalid Word XML')
            nodes = comments.getroot().findall(W + 'comment'); ids = [node.get(W + 'id') for node in nodes]
            if any(not value or not re.fullmatch(r'[0-9]{1,10}', value) for value in ids) or len(ids) != len(set(ids)):
                raise ValueError('Invalid or duplicate comment identifiers')
            metadata, metadata_status = comment_thread_metadata(archive, rels.getroot().findall(rel_ns + 'Relationship'), nodes)
            result = []
            for node in nodes[:200]:
                paragraphs = []
                for p in node.findall(W + 'p'):
                    paragraphs.append(''.join(item.text or '' if item.tag == W + 't' else ('\t' if item.tag == W + 'tab' else '\n' if item.tag in (W + 'br', W + 'cr') else '') for item in p.iter()))
                text = '\n'.join(paragraphs)
                result.append({'id': node.get(W + 'id'), 'author': (node.get(W + 'author') or '')[:200],
                               'date': (node.get(W + 'date') or '')[:100], 'text': text[:4000], 'text_truncated': len(text) > 4000,
                               'text_approximate': any(child.tag != W + 'p' for child in node) or any(child.tag in (W + 'delText', W + 'instrText', W + 'drawing', W + 'object', W + 'sym', W + 'fldChar') for child in node.iter()),
                               'anchor_text': '', 'anchor_text_truncated': False, 'anchor_text_approximate': False,
                               'paragraph_paths': [], 'paths_truncated': False, 'path_unavailable': False,
                               'anchor_status': 'not_found_in_body', 'resolved': None, 'thread_metadata': 'unavailable',
                               'reply_to_comment_id': None, 'reply_to_paragraph_id': None, 'reply_parent_status': 'unknown',
                               **metadata.get(node.get(W + 'id'), {}), '_starts': 0, '_ends': 0, '_refs': 0})
            if not result:
                return {'total_comments': 0, 'comments': [], 'truncated': False, 'anchor_scan_complete': True, 'thread_metadata_status': metadata_status}
            by_id = {item['id']: item for item in result}; active = set(); paths = []; visited = 0; work = 0; complete = True
            sibling_indexes = {}
            def paragraph_path_for(node):
                tags = {W + 'p': ('p', {W + 'body', W + 'tc'}), W + 'tbl': ('tbl', {W + 'body', W + 'tc'}),
                        W + 'tr': ('tr', {W + 'tbl'}), W + 'tc': ('tc', {W + 'tr'})}
                parts = []
                while node is not body:
                    parent = node.getparent()
                    if parent is None or node.tag not in tags or parent.tag not in tags[node.tag][1]: return None
                    if parent not in sibling_indexes:
                        counts = {}; indexes = {}
                        for child in parent:
                            if child.tag in tags:
                                counts[child.tag] = counts.get(child.tag, 0) + 1; indexes[child] = counts[child.tag]
                        sibling_indexes[parent] = indexes
                    parts.append(f'{tags[node.tag][0]}[{sibling_indexes[parent][node]}]'); node = parent
                path = '/body/' + '/'.join(reversed(parts))
                return path if paragraph_path(path) else None
            def location(item, path):
                if path is None: item['path_unavailable'] = True
                if path and path not in item['paragraph_paths']:
                    if len(item['paragraph_paths']) < 20: item['paragraph_paths'].append(path)
                    else: item['paths_truncated'] = True
            def append_text(item, text):
                room = 2000 - len(item['anchor_text'])
                item['anchor_text'] += text[:max(room, 0)]
                if len(text) > room: item['anchor_text_truncated'] = True
            for event, node in etree.iterwalk(body, events=('start', 'end')):
                visited += 1
                if visited > 1_000_000 or work > 1_000_000:
                    complete = False; break
                tag = node.tag
                if event == 'start':
                    if tag == W + 'p':
                        path = paragraph_path_for(node); paths.append(path)
                        for cid in active:
                            item = by_id[cid]; location(item, path)
                            if item['anchor_text']: append_text(item, '\n')
                        work += len(active)
                    elif tag == W + 'commentRangeStart' and node.get(W + 'id') in by_id:
                        cid = node.get(W + 'id'); item = by_id[cid]; item['_starts'] += 1; active.add(cid); location(item, paths[-1] if paths else None)
                    elif tag == W + 'commentRangeEnd' and node.get(W + 'id') in by_id:
                        cid = node.get(W + 'id'); by_id[cid]['_ends'] += 1; active.discard(cid)
                    elif tag == W + 'commentReference' and node.get(W + 'id') in by_id:
                        item = by_id[node.get(W + 'id')]; item['_refs'] += 1; location(item, paths[-1] if paths else None)
                    elif tag in (W + 'delText', W + 'instrText', W + 'drawing', W + 'object', W + 'sym', W + 'fldChar'):
                        for cid in active: by_id[cid]['anchor_text_approximate'] = True
                        work += len(active)
                    elif tag in (W + 't', W + 'tab', W + 'br', W + 'cr'):
                        value = (node.text or '') if tag == W + 't' else ('\t' if tag == W + 'tab' else '\n')
                        for cid in active: append_text(by_id[cid], value)
                        work += len(active)
                elif tag == W + 'p' and paths:
                    paths.pop()
            for item in result:
                starts, ends, refs = item.pop('_starts'), item.pop('_ends'), item.pop('_refs')
                if starts == 1 and ends == 1 and item['id'] not in active and complete: item['anchor_status'] = 'range'
                elif starts or ends: item['anchor_status'] = 'incomplete_range'
                elif refs: item['anchor_status'] = 'reference_only'
            return {'total_comments': len(nodes), 'comments': result, 'truncated': len(nodes) > 200, 'anchor_scan_complete': complete, 'thread_metadata_status': metadata_status}
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError(f'Invalid Word document: {exc}') from exc


def set_comment_resolved(source, output, comment_id, resolved):
    """Set the done state on a root Word comment while preserving unrelated parts."""
    import posixpath
    import secrets
    import uuid
    import zipfile
    from lxml import etree

    if Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Comment state requires DOCX input and output')
    if not isinstance(comment_id, str) or not re.fullmatch(r'0|[1-9][0-9]{0,9}', comment_id) or int(comment_id) > 2147483647:
        raise ValueError('Comment ID must be a nonnegative decimal string')
    if not isinstance(resolved, bool):
        raise ValueError('Resolved must be a boolean')
    rel_ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    type_ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    w15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
    mc = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
    comments_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
    extended_type = 'http://schemas.microsoft.com/office/2011/relationships/commentsExtended'
    rel_path = 'word/_rels/document.xml.rels'

    def locate(archive, relation):
        target = relation.get('Target')
        if relation.get('TargetMode') == 'External' or not target:
            raise ValueError('Invalid comment relationship')
        part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
        if not part.startswith('word/') or part not in archive.namelist():
            raise ValueError('Invalid comment part')
        return part

    def select_part(file):
        with zipfile.ZipFile(file) as archive:
            rels = ooxml.parse_xml(archive.read(rel_path))
            if rels.getroot().tag != rel_ns + 'Relationships': raise ValueError('Invalid document relationships')
            links = [item for item in rels.getroot().findall(rel_ns + 'Relationship') if item.get('Type') == comments_type]
            if len(links) != 1: raise ValueError('Exactly one comments relationship is required')
            return locate(archive, links[0])

    def edit(tree, archive):
        if tree.getroot().tag != W + 'comments': raise ValueError('Invalid comments XML')
        nodes = tree.getroot().findall(W + 'comment')
        values = [node.get(W + 'id') for node in nodes]
        if any(value is None or not re.fullmatch(r'[0-9]{1,10}', value) for value in values): raise ValueError('Invalid comment identifier')
        matches = [node for node in nodes if int(node.get(W + 'id')) == int(comment_id)]
        if len(matches) != 1: raise ValueError('Comment ID must identify exactly one comment')
        rel_bytes = archive.read(rel_path); rels = ooxml.parse_xml(rel_bytes)
        if rels.getroot().tag != rel_ns + 'Relationships': raise ValueError('Invalid document relationships')
        relationships = rels.getroot().findall(rel_ns + 'Relationship')
        links = [item for item in relationships if item.get('Type') == extended_type]
        if len(links) > 1: raise ValueError('Multiple extended comments relationships are unsupported')
        paragraphs = list(matches[0].iter(W + 'p'))
        if not paragraphs: raise ValueError('Comment has no paragraph')
        paragraph = paragraphs[-1]; para_id = paragraph.get(W14_PARAGRAPH_ID)
        additional = {}; ext_bytes = None
        if links:
            ext_part = locate(archive, links[0]); ext_bytes = archive.read(ext_part); ext = ooxml.parse_xml(ext_bytes)
            metadata, status = comment_thread_metadata(archive, relationships, nodes)
            item = metadata.get(comment_id, {})
            if status != 'available': raise ValueError('Extended comment metadata is invalid')
            if item.get('thread_metadata') == 'matched':
                if item.get('reply_parent_status') != 'root': raise ValueError('Comment must be a root thread')
                if not para_id or not re.fullmatch(r'[0-9A-Fa-f]{8}', para_id) or not 0 < int(para_id, 16) < 0x80000000:
                    raise ValueError('Comment paragraph ID is invalid')
                if sum((node.get(W14_PARAGRAPH_ID) or '').upper() == para_id.upper() for node in tree.getroot().iter(W + 'p')) != 1:
                    raise ValueError('Comment paragraph ID is ambiguous')
                records = [record for record in ext.getroot().findall(w15 + 'commentEx') if record.get(w15 + 'paraId', '').upper() == para_id.upper()]
                if len(records) != 1: raise ValueError('Comment metadata is ambiguous')
                records[0].set(w15 + 'done', '1' if resolved else '0')
                return {ext_part: ooxml.serialize_xml(ext, ext_bytes)}
            if item.get('thread_metadata') not in (None, 'missing'):
                raise ValueError('Comment thread metadata is ambiguous or invalid')
        else:
            ext_part = 'word/commentsExtended.xml'
            if ext_part in archive.namelist(): raise ValueError('Unreferenced extended comments part')
            ext = etree.ElementTree(etree.Element(w15 + 'commentsEx', nsmap={'w15': w15[1:-1]}))
        if any(item.get('Type', '').endswith(('/commentsIds', '/commentsExtensible')) for item in relationships):
            raise ValueError('Existing modern comment metadata requires an explicit extended record')
        document = ooxml.parse_xml(archive.read('word/document.xml'))
        if document.getroot().tag != W + 'document': raise ValueError('Invalid document XML')
        markers = [node.tag for node in document.getroot().iter() if node.tag in (W + 'commentRangeStart', W + 'commentRangeEnd', W + 'commentReference') and node.get(W + 'id') == comment_id]
        if markers != [W + 'commentRangeStart', W + 'commentRangeEnd', W + 'commentReference']:
            raise ValueError('Legacy comment must have one complete main-document anchor')
        all_para_ids = [node.get(W14_PARAGRAPH_ID).upper() for node in tree.getroot().iter(W + 'p') if node.get(W14_PARAGRAPH_ID)]
        extended_ids = [(node.get(w15 + 'paraId') or '').upper() for node in ext.getroot().findall(w15 + 'commentEx')]
        if any(not re.fullmatch(r'[0-9A-F]{8}', value) for value in extended_ids) or len(extended_ids) != len(set(extended_ids)):
            raise ValueError('Existing extended comment identifiers are invalid or ambiguous')
        if para_id:
            if not re.fullmatch(r'[0-9A-Fa-f]{8}', para_id) or not 0 < int(para_id, 16) < 0x80000000 or all_para_ids.count(para_id.upper()) != 1:
                raise ValueError('Comment paragraph ID is invalid or ambiguous')
            para_id = para_id.upper()
        else:
            para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
            while para_id in all_para_ids or para_id in extended_ids: para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
            root = tree.getroot(); nsmap = dict(root.nsmap)
            prefix = next((key for key, value in nsmap.items() if key and value == W14_PARAGRAPH_ID[1:].split('}', 1)[0]), None)
            if prefix is None:
                prefix = 'w14'
                while prefix in nsmap: prefix += 'x'
                nsmap[prefix] = 'http://schemas.microsoft.com/office/word/2010/wordml'
            if not any(key and value == mc[1:-1] for key, value in nsmap.items()):
                mc_prefix = 'mc'
                while mc_prefix in nsmap: mc_prefix += 'x'
                nsmap[mc_prefix] = mc[1:-1]
            replacement = etree.Element(root.tag, attrib=dict(root.attrib), nsmap=nsmap); replacement.text = root.text
            for child in list(root): replacement.append(child)
            tree._setroot(replacement)
            ignorable = (replacement.get(mc + 'Ignorable') or '').split()
            if prefix not in ignorable: ignorable.append(prefix)
            replacement.set(mc + 'Ignorable', ' '.join(ignorable)); paragraph.set(W14_PARAGRAPH_ID, para_id)
        if para_id in extended_ids: raise ValueError('Comment metadata is ambiguous')
        etree.SubElement(ext.getroot(), w15 + 'commentEx', {w15 + 'paraId': para_id, w15 + 'done': '1' if resolved else '0'})
        additional[ext_part] = ooxml.serialize_xml(ext, ext_bytes) if ext_bytes else etree.tostring(ext, encoding='UTF-8', xml_declaration=True)
        if not links:
            rid = 'rIdOfficeUse' + uuid.uuid4().hex
            if any(item.get('Id') == rid for item in relationships): raise ValueError('Relationship identifier collision')
            etree.SubElement(rels.getroot(), rel_ns + 'Relationship', Id=rid, Type=extended_type, Target='commentsExtended.xml')
            additional[rel_path] = ooxml.serialize_xml(rels, rel_bytes)
            content_bytes = archive.read('[Content_Types].xml'); types = ooxml.parse_xml(content_bytes)
            if types.getroot().tag != type_ns + 'Types' or any(item.get('PartName') == '/' + ext_part for item in types.getroot()):
                raise ValueError('Invalid or conflicting package content types')
            etree.SubElement(types.getroot(), type_ns + 'Override', PartName='/' + ext_part, ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml')
            additional['[Content_Types].xml'] = ooxml.serialize_xml(types, content_bytes)
        return additional

    return ooxml.edit_xml(source, output, select_part, edit, allow_new=True)
