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
