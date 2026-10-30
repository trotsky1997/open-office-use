"""Conservative, targeted text replacement in a saved Word document."""
import re
import posixpath
import tempfile
import snapshot as snapshots
import zipfile
from pathlib import Path
from lxml import etree

import ooxml

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
W14_PARAGRAPH_ID = '{http://schemas.microsoft.com/office/word/2010/wordml}paraId'
INDEX = r'[1-9][0-9]{0,5}'
PATH = re.compile(r'/body(?:(?:/(?:tbl|table)\[' + INDEX + r'\]/(?:tr|row)\[' + INDEX + r'\]/(?:tc|cell)\[' + INDEX + r'\])){0,8}/p(?:\[' + INDEX + r'\]|\[@paraId=[0-9A-Fa-f]{8}\])\Z')
SEGMENT = re.compile(r'/(tbl|table|tr|row|tc|cell|p)\[([^]]+)\]')
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
STORY_ID = r'[A-Za-z_][A-Za-z0-9_.-]{0,127}'
STORY_PATH = re.compile(r'^/(header|footer)\[@id=(' + STORY_ID + r')\](?:(?:/(?:tbl|table)\[' + INDEX + r'\]/(?:tr|row)\[' + INDEX + r'\]/(?:tc|cell)\[' + INDEX + r'\])){0,8}/p(?:\[' + INDEX + r'\]|\[@paraId=[0-9A-Fa-f]{8}\])\Z')


def paragraph_path(path):
    return isinstance(path, str) and len(path) <= 512 and PATH.fullmatch(path) is not None


def replacement_path(path):
    return paragraph_path(path) or isinstance(path, str) and len(path) <= 512 and STORY_PATH.fullmatch(path) is not None


def tracked_changes(source):
    """Inventory common tracked-change XML records in a saved Word snapshot."""
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.docx': raise ValueError('Tracked-change inspection requires a DOCX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-word-changes-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Document exceeds package limits or contains duplicate parts')
                if 'word/document.xml' not in names: raise ValueError('Document part is missing')
                parts = {'word/document.xml': {'kind': 'body', 'relationship_ids': []}}
                issues = set(); settings_part = None
                rel_path = 'word/_rels/document.xml.rels'
                if rel_path in names:
                    relationships = ooxml.parse_xml(archive.read(rel_path)).getroot()
                    if relationships.tag != REL + 'Relationships': raise ValueError('Invalid document relationships')
                    relation_base = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                    related = 0
                    for rel in relationships.findall(REL + 'Relationship'):
                        reltype = rel.get('Type', '')
                        if not reltype.startswith(relation_base): continue
                        kind = reltype[len(relation_base):]
                        if kind not in ('header', 'footer', 'footnotes', 'endnotes', 'settings'): continue
                        related += 1
                        if related > 1000: issues.add('relationship_limit'); break
                        target, rid = rel.get('Target', ''), rel.get('Id', '')
                        path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
                        if rel.get('TargetMode') not in (None, 'Internal') or not target or len(target) > 512 or len(path) > 512 or not path.startswith('word/') or path not in names or not rid or len(rid) > 128:
                            issues.add('unresolved_relationship'); continue
                        if kind == 'settings':
                            if settings_part is not None and settings_part != path: issues.add('ambiguous_settings')
                            settings_part = path; continue
                        if path in parts and parts[path]['kind'] != kind:
                            issues.add('ambiguous_part_type'); continue
                        parts.setdefault(path, {'kind': kind, 'relationship_ids': []})['relationship_ids'].append(rid)
                tracking_enabled = None
                if settings_part is not None and 'ambiguous_settings' not in issues:
                    settings = ooxml.parse_xml(archive.read(settings_part)).getroot()
                    if settings.tag != W + 'settings': issues.add('invalid_settings')
                    else:
                        markers = settings.findall(W + 'trackRevisions')
                        if len(markers) > 1: issues.add('ambiguous_tracking_setting')
                        elif not markers: tracking_enabled = False
                        else:
                            value = markers[0].get(W + 'val')
                            if value in (None, '1', 'true', 'on'): tracking_enabled = True
                            elif value in ('0', 'false', 'off'): tracking_enabled = False
                            else: issues.add('invalid_tracking_setting')
                kinds = {'ins', 'del', 'moveFrom', 'moveTo', 'moveFromRangeStart', 'moveFromRangeEnd', 'moveToRangeStart', 'moveToRangeEnd',
                         'rPrChange', 'pPrChange', 'sectPrChange', 'tblPrChange', 'tblPrExChange', 'tblGridChange', 'trPrChange', 'tcPrChange', 'numberingChange',
                         'cellIns', 'cellDel', 'cellMerge', 'customXmlInsRangeStart', 'customXmlInsRangeEnd', 'customXmlDelRangeStart', 'customXmlDelRangeEnd',
                         'customXmlMoveFromRangeStart', 'customXmlMoveFromRangeEnd', 'customXmlMoveToRangeStart', 'customXmlMoveToRangeEnd'}
                revision_tags = {W + kind for kind in kinds} | {W14 + kind for kind in ('customXmlConflictInsRangeStart', 'customXmlConflictInsRangeEnd', 'customXmlConflictDelRangeStart', 'customXmlConflictDelRangeEnd', 'conflictIns', 'conflictDel')}
                records, counts, scanned_parts = [], {}, []
                scanned, complete = 0, True
                for part, info in list(parts.items())[:200]:
                    tree = ooxml.parse_xml(archive.read(part)); root = tree.getroot()
                    expected = {'body': 'document', 'header': 'hdr', 'footer': 'ftr', 'footnotes': 'footnotes', 'endnotes': 'endnotes'}[info['kind']]
                    if root.tag != W + expected: issues.add('invalid_story_root'); continue
                    for node in root.iter():
                        if node.tag not in revision_tags: continue
                        if scanned >= 10000: complete = False; break
                        scanned += 1; kind = node.tag.rsplit('}', 1)[-1]; counts[kind] = counts.get(kind, 0) + 1
                        if len(records) < 200:
                            chunks, length, clipped = [], 0, False
                            for item in node.iter():
                                if item.tag not in (W + 't', W + 'delText', W + 'instrText', W + 'delInstrText'): continue
                                value = item.text or ''; available = 2000 - length
                                if len(value) > available: clipped = True
                                if available > 0: chunks.append(value[:available]); length += min(len(value), available)
                            parent = node.getparent(); location = tree.getpath(node)
                            records.append({'part': part, 'story': info['kind'], 'kind': kind, 'id': (node.get(W + 'id') or '')[:100],
                                            'author': (node.get(W + 'author') or '')[:200], 'date': (node.get(W + 'date') or '')[:100],
                                            'parent': parent.tag[len(W):] if parent is not None and isinstance(parent.tag, str) and parent.tag.startswith(W) else None,
                                            'xml_path': location[:512], 'path_truncated': len(location) > 512,
                                            'text': ''.join(chunks), 'text_truncated': clipped})
                    scanned_parts.append({'part': part, **info, 'complete': complete})
                    if not complete: break
                if len(parts) > 200: issues.add('part_limit')
                return {'snapshot_sha256': digest, 'tracking_enabled': tracking_enabled, 'records': records,
                        'counts': counts, 'records_scanned': scanned, 'records_truncated': scanned > len(records),
                        'parts': scanned_parts, 'total_parts': len(parts), 'issues': sorted(issues),
                        'scan_complete': complete and not issues,
                        'limits': {'relationships': 1000, 'parts': 200, 'records_scanned': 10000, 'records_returned': 200, 'text_characters': 2000},
                        'notes': ['Records represent XML elements, not necessarily individual user-visible revisions.',
                                  'Scope covers the main document and related headers, footers, footnotes and endnotes; comments and other parts are excluded.',
                                  'Text can omit fields, formatting and complex content; XML paths are inspection hints, not edit paths.']}
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Invalid Word document: {exc}') from exc


def search_body(source, query, offset=0, snapshot_sha256=None):
    """Search body and table paragraphs, returning paths usable for targeted edits."""
    return search_paragraphs(source, query, offset, snapshot_sha256, 'body')


def search_stories(source, query, offset=0, snapshot_sha256=None):
    """Search related header and footer paragraphs, including table cells."""
    return search_paragraphs(source, query, offset, snapshot_sha256, 'stories')


def search_paragraphs(source, query, offset, snapshot_sha256, scope):
    if not isinstance(query, str) or not query or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise ValueError('Search text must contain 1 to 200 characters without control characters')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0: raise ValueError('Offset must be a nonnegative integer')
    if offset and snapshot_sha256 is None: raise ValueError('Continuing a search requires the prior snapshot SHA-256')
    if snapshot_sha256 is not None and (not isinstance(snapshot_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot_sha256)):
        raise ValueError('Invalid snapshot SHA-256')
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.docx': raise ValueError('Word search requires a DOCX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-word-search-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        if snapshot_sha256 is not None and digest != snapshot_sha256: raise ValueError('Document snapshot changed; restart the search')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Document exceeds package limits or contains duplicate parts')
                def roots():
                    if scope == 'body':
                        root = ooxml.parse_xml(archive.read('word/document.xml')).getroot()
                        if root.tag != W + 'document': raise ValueError('Document XML has an invalid root')
                        body = root.find(W + 'body')
                        if body is None: raise ValueError('Document has no body')
                        yield '/body', None, body
                    else:
                        stories = story_relationships(archive)
                        if len(stories) > 200: raise ValueError('Document exceeds the 200 header/footer relationship limit')
                        for rid, story in stories.items():
                            root = ooxml.parse_xml(archive.read(story['part'])).getroot()
                            if root.tag != W + ('hdr' if story['type'] == 'header' else 'ftr'): raise ValueError('Header or footer has an invalid root')
                            yield f"/{story['type']}[@id={rid}]", story['part'], root
                unsupported = set()
                def paragraphs(container, path, depth):
                    if depth > 8:
                        unsupported.add('table_depth'); return
                    counts = {'p': 0, 'tbl': 0}
                    for child in container:
                        tag = child.tag
                        if tag == W + 'p':
                            counts['p'] += 1
                            yield f"{path}/p[{counts['p']}]", child
                        elif tag == W + 'tbl':
                            counts['tbl'] += 1
                            for table_child in child:
                                if table_child.tag not in (W + 'tr', W + 'tblPr', W + 'tblGrid'): unsupported.add('table_structure')
                            for row_index, row in enumerate(child.findall(W + 'tr'), 1):
                                for row_child in row:
                                    if row_child.tag not in (W + 'tc', W + 'trPr'): unsupported.add('row_structure')
                                for cell_index, cell in enumerate(row.findall(W + 'tc'), 1):
                                    yield from paragraphs(cell, f"{path}/tbl[{counts['tbl']}]/tr[{row_index}]/tc[{cell_index}]", depth + 1)
                        elif tag not in (W + 'sectPr', W + 'tcPr'):
                            unsupported.add('container_structure')
                matches, scanned, skipped, uncertain = [], 0, 0, 0
                scan_complete = True; stop_reason = None
                complex_tags = {W + name for name in ('fldChar', 'fldSimple', 'instrText', 'drawing', 'object', 'del', 'ins', 'sdt', 'tab', 'br', 'cr', 'sym', 'softHyphen', 'noBreakHyphen', 'footnoteReference', 'endnoteReference')}
                def candidates():
                    for prefix, part, root in roots():
                        for path, paragraph in paragraphs(root, prefix, 0): yield path, part, paragraph
                for path, part, paragraph in candidates():
                    if skipped < offset: skipped += 1; continue
                    if scanned >= 10000 or len(matches) >= 100:
                        scan_complete = False; stop_reason = 'match_limit' if len(matches) >= 100 else 'paragraph_limit'; break
                    scanned += 1
                    text_nodes = [node for node in paragraph.iter(W + 't') if next(node.iterancestors(W + 'p'), None) is paragraph]
                    text = ''.join(node.text or '' for node in text_nodes)
                    text_complete = not any(node.tag in complex_tags or node.tag == W + 'p' and node is not paragraph for node in paragraph.iter())
                    if not text_complete: uncertain += 1
                    if query in text:
                        index = text.index(query); start = max(0, index - 100); end = min(len(text), index + len(query) + 100)
                        matches.append({'path': path, 'excerpt': text[start:end], 'excerpt_start': start, 'text_length': len(text),
                                        'occurrences': sum(1 for _ in re.finditer('(?=' + re.escape(query) + ')', text)), 'text_complete': text_complete,
                                        'replace_text_path_supported': replacement_path(path), **({'part': part} if part else {})})
                if skipped < offset: raise ValueError('Search offset exceeds the paragraph count')
                return {'scope': scope, 'query': query, 'case_sensitive': True, 'snapshot_sha256': digest, 'offset': offset,
                        'next_offset': offset + scanned if not scan_complete else None, 'stop_reason': stop_reason,
                        'paragraphs_scanned': scanned, 'matches': matches, 'unverified_paragraphs': uncertain,
                        'unsupported_structure': sorted(unsupported), 'scan_complete': scan_complete,
                        'complete': offset == 0 and scan_complete and not uncertain and not unsupported,
                        'limits': {'paragraphs': 10000, 'matches': 100},
                        'notes': [('Search covers body and supported table paragraphs; headers, footers, notes and text boxes are excluded.' if scope == 'body' else 'Search covers related header and footer paragraphs and tables; shared parts can appear under multiple relationship IDs. Check section impact before editing.'),
                                  'Paths are candidates: inspect paragraph structure and use targeted editing validation before replacing text.']}
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Invalid Word document: {exc}') from exc


def story_relationships(archive):
    tree = ooxml.parse_xml(archive.read('word/_rels/document.xml.rels'))
    if tree.getroot().tag != REL + 'Relationships': raise ValueError('Invalid document relationships')
    seen = set(); stories = {}
    for rel in tree.getroot().findall(REL + 'Relationship'):
        rid = rel.get('Id'); relation_type = rel.get('Type', '')
        if not rid or rid in seen: raise ValueError('Missing or duplicate relationship ID')
        seen.add(rid)
        types = {R[1:-1] + '/header': 'header', R[1:-1] + '/footer': 'footer'}
        if relation_type not in types: continue
        kind = types[relation_type]
        target = rel.get('Target', '')
        if not re.fullmatch(STORY_ID, rid) or rel.get('TargetMode', 'Internal') != 'Internal' or not target or any(c in target for c in ('\\', '%', '?', '#')):
            raise ValueError('Unsupported header or footer relationship')
        path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
        if not path.startswith('word/') or path not in archive.namelist(): raise ValueError('Invalid header or footer part')
        stories[rid] = {'type': kind, 'part': path}
    return stories


def list_stories(source):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.docx': raise ValueError('Headers and footers require a DOCX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(set(names)) != len(names) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Document exceeds package limits or contains duplicate parts')
            stories = story_relationships(archive); doc = ooxml.parse_xml(archive.read('word/document.xml'))
            if len(stories) > 200: raise ValueError('Document exceeds the 200 header/footer relationship inventory limit')
            if doc.getroot().tag != W + 'document': raise ValueError('Document XML has an invalid root')
            body = doc.getroot().find(W + 'body')
            if body is None: raise ValueError('Document has no body')
            sections = body.xpath('./w:p/w:pPr/w:sectPr | ./w:sectPr', namespaces={'w': W[1:-1]})
            # shortcut: nonstandard section locations cannot be resolved; inspect them in Word.
            reference_complete = len(list(body.iter(W + 'sectPr'))) == len(sections)
            if not sections: sections = [None]
            if len(sections) > 5000: reference_complete = False
            part_ids = {}
            for rid, story in stories.items(): part_ids.setdefault(story['part'], []).append(rid)
            for rid, story in stories.items():
                story['references'] = []; story['linked_sections'] = []
                story['same_part_ids'] = [other for other in part_ids[story['part']] if other != rid]
            linked = {(kind, variant): None for kind in ('header', 'footer') for variant in ('default', 'first', 'even')}
            link_count = 0
            for number, section in enumerate(sections[:5000], 1):
                explicit = set()
                for kind in ('header', 'footer'):
                    for ref in section.findall(W + kind + 'Reference') if section is not None else ():
                        rid = ref.get(R + 'id')
                        if rid not in stories or stories[rid]['type'] != kind: raise ValueError('Invalid section header or footer reference')
                        variant = ref.get(W + 'type')
                        if variant not in ('default', 'first', 'even') or (kind, variant) in explicit:
                            raise ValueError('Invalid or duplicate section header or footer type')
                        explicit.add((kind, variant)); linked[(kind, variant)] = rid
                        stories[rid]['references'].append({'section': number, 'type': variant})
                for (kind, variant), rid in linked.items():
                    if rid is not None:
                        link_count += 1
                        if link_count <= 2000:
                            stories[rid]['linked_sections'].append({'section': number, 'type': variant, 'inherited': (kind, variant) not in explicit})
                        else: reference_complete = False
            result = []; total = 0; complete = True
            for rid, story in stories.items():
                root = ooxml.parse_xml(archive.read(story['part'])).getroot()
                if root.tag != W + ('hdr' if story['type'] == 'header' else 'ftr'): raise ValueError('Header or footer has an invalid root')
                prefix = f"/{story['type']}[@id={rid}]"; paragraphs = []
                def walk(container, path, depth):
                    nonlocal total, complete
                    if depth > 8: complete = False; return
                    counts = {'p': 0, 'tbl': 0}
                    for child in container:
                        tag = child.tag.removeprefix(W) if isinstance(child.tag, str) else ''
                        if tag == 'p':
                            counts['p'] += 1; total += 1
                            if total > 200: complete = False; continue
                            text = ''.join(node.text or '' for node in child.iter(W + 't'))
                            paragraphs.append({'path': f"{path}/p[{counts['p']}]", 'text': text[:4000], 'truncated': len(text) > 4000})
                        elif tag == 'tbl':
                            counts['tbl'] += 1
                            for row_index, row in enumerate(child.findall(W + 'tr'), 1):
                                for cell_index, cell in enumerate(row.findall(W + 'tc'), 1): walk(cell, f"{path}/tbl[{counts['tbl']}]/tr[{row_index}]/tc[{cell_index}]", depth + 1)
                        elif tag not in ('pPr', 'tblPr', 'tblGrid', 'tcPr'): complete = False
                walk(root, prefix, 0)
                result.append({'id': rid, **story, 'paragraphs': paragraphs})
            return {'stories': result, 'sections': len(sections), 'paragraphs_scanned': min(total, 200), 'complete': complete, 'reference_resolution_complete': reference_complete}
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError(f'Invalid Word document: {exc}') from exc


def find_paragraph(tree, path):
    story = STORY_PATH.fullmatch(path)
    if story:
        if tree.getroot().tag != W + ('hdr' if story.group(1) == 'header' else 'ftr'): raise ValueError('Header or footer has an invalid root')
        paragraph = tree.getroot()
    else:
        if tree.getroot().tag != W + 'document': raise ValueError('Document XML has an invalid root')
        paragraph = tree.getroot().find(W + 'body')
        if paragraph is None: raise ValueError('Document has no body')
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


def anchor_runs(paragraph, anchor):
    """Find and split a unique literal range within adjacent simple paragraph runs."""
    from copy import deepcopy

    groups = []; current = []
    def flush():
        if current:
            groups.append((current[:], ''.join(node.text or '' for run in current for node in run.findall(W + 't')))); current.clear()
    def run_text(run):
        if any(child.tag not in (W + 'rPr', W + 't') for child in run):
            raise ValueError('Paragraph contains unsupported run content')
        if any(node.get(W + 'id') is not None or node.get('{http://www.w3.org/XML/1998/namespace}id') is not None or node.tag in {W + 'rPrChange', W + 'ins', W + 'del', W + 'moveFrom', W + 'moveTo', W14 + 'conflictIns', W14 + 'conflictDel'} for node in run.iter()):
            raise ValueError('Run contains tracked or identity-bearing formatting')
        return ''.join(node.text or '' for node in run.findall(W + 't'))
    boundaries = {W + name for name in ('bookmarkStart', 'bookmarkEnd', 'commentRangeStart', 'commentRangeEnd', 'proofErr')}
    for child in paragraph:
        if child.tag == W + 'pPr': continue
        if child.tag == W + 'r':
            tags = {node.tag for node in child}
            if tags <= {W + 'rPr', W + 'commentReference'} and W + 'commentReference' in tags:
                flush(); continue
            run_text(child); current.append(child)
        elif child.tag == W + 'hyperlink':
            flush()
            if any(run.tag != W + 'r' for run in child): raise ValueError('Hyperlink contains unsupported content')
            groups.append((None, ''.join(run_text(run) for run in child)))
        elif child.tag in boundaries:
            flush()
        else:
            raise ValueError('Paragraph contains unsupported structures such as fields or tracked changes')
    flush()
    text = ''.join(value for _, value in groups)
    start = ooxml.match_index(text, anchor, ''); end = start + len(anchor); offset = 0
    for runs, value in groups:
        next_offset = offset + len(value)
        if runs is not None and offset <= start and end <= next_offset:
            start -= offset; end -= offset
            break
        offset = next_offset
    else:
        raise ValueError('Anchor crosses or lies within a hyperlink or annotation boundary')

    def split_at(position):
        offset = 0
        for index, run in enumerate(runs):
            value = run_text(run); next_offset = offset + len(value)
            if offset < position < next_offset:
                allowed = {W + 'rsidR', W + 'rsidRPr', W + 'rsidDel'}
                if any(name not in allowed for name in run.attrib): raise ValueError('Run has unsupported identity attributes')
                if any(name != '{http://www.w3.org/XML/1998/namespace}space' for node in run.findall(W + 't') for name in node.attrib):
                    raise ValueError('Text has unsupported attributes for splitting')
                right = deepcopy(run); left_nodes = run.findall(W + 't'); right_nodes = right.findall(W + 't')
                local = position - offset; cursor = 0
                for left_node, right_node in zip(left_nodes, right_nodes):
                    original = left_node.text or ''; cut = max(0, min(len(original), local - cursor))
                    left_node.text = original[:cut]; right_node.text = original[cut:]; cursor += len(original)
                    for node in (left_node, right_node):
                        value = node.text or ''
                        if value.startswith(' ') or value.endswith(' '): node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                run.addnext(right); runs.insert(index + 1, right); return
            offset = next_offset
    split_at(end); split_at(start)
    selected = []; offset = 0
    for run in runs:
        length = len(run_text(run)); next_offset = offset + length
        if length and offset >= start and next_offset <= end: selected.append(run)
        offset = next_offset
    if not selected: raise ValueError('Anchor has no selectable runs')
    return selected[0], selected[-1]


def replace_text(source, output, path, find, replacement):
    if not replacement_path(path):
        raise ValueError('Target must be a body, header or footer paragraph path')
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

    return ooxml.edit_xml(source, output, lambda file: paragraph_part(file, path), edit)


def paragraph_part(file, path):
    story = STORY_PATH.fullmatch(path)
    if story is None: return 'word/document.xml'
    with zipfile.ZipFile(file) as archive: relationships = story_relationships(archive)
    info = relationships.get(story.group(2))
    if info is None or info['type'] != story.group(1): raise ValueError('Header or footer relationship does not exist')
    return info['part']


def validate_tracked_context(tree, targets):
    """Reject targets inside ambiguous tracked ranges or structural revisions."""
    known = {W + name for name in ('ins', 'del', 'moveFrom', 'moveTo')}
    conflicts = {W14 + 'conflictIns', W14 + 'conflictDel'}
    range_names = [(W, name) for name in ('moveFrom', 'moveTo', 'customXmlIns', 'customXmlDel', 'customXmlMoveFrom', 'customXmlMoveTo')]
    range_names += [(W14, name) for name in ('customXmlConflictIns', 'customXmlConflictDel')]
    markers = {namespace + name + 'Range' + suffix: (namespace + name, suffix == 'Start')
               for namespace, name in range_names for suffix in ('Start', 'End')}
    active, seen, found = set(), set(), set()
    targets = set(targets)
    def story_scope(node):
        return next((parent for parent in node.iterancestors() if parent.tag in (W + 'footnote', W + 'endnote', W + 'txbxContent')), tree.getroot())
    for node in tree.iter():
        if node.tag in markers:
            raw = node.get(W + 'id', '').strip()
            if not re.fullmatch(r'[+-]?[0-9]{1,100}', raw): raise ValueError('Tracked range has an invalid ID')
            kind, starting = markers[node.tag]; key = (kind, int(raw), story_scope(node))
            if starting:
                if key in seen: raise ValueError('Tracked range IDs are ambiguous')
                seen.add(key); active.add(key)
            else:
                if key not in active: raise ValueError('Tracked range markers are unmatched')
                active.remove(key)
        if node in targets:
            found.add(node); current_scope = story_scope(node)
            if any(scope == current_scope for _, _, scope in active): raise ValueError('Target lies inside a tracked move or custom XML range')
    if active: raise ValueError('Tracked range markers are unmatched')
    if found != targets: raise ValueError('Tracked revision target is missing')
    structural = known | conflicts | {W + name for name in ('cellIns', 'cellDel', 'cellMerge', 'tblGridChange', 'tblPrExChange', 'numberingChange')}
    for node in targets:
        if any(ancestor.tag in known or ancestor.tag in conflicts for ancestor in node.iterancestors()): raise ValueError('Nested tracked revisions are not supported')
        for ancestor in node.iterancestors():
            prop_name = {W + 'p': 'pPr', W + 'tr': 'trPr', W + 'tc': 'tcPr', W + 'tbl': 'tblPr'}.get(ancestor.tag)
            props = ancestor.find(W + prop_name) if prop_name else None
            grid = ancestor.find(W + 'tblGrid') if ancestor.tag == W + 'tbl' else None
            exceptions = ancestor.find(W + 'tblPrEx') if ancestor.tag == W + 'tr' else None
            for container in (props, grid, exceptions):
                if container is not None and any(item.tag in structural or isinstance(item.tag, str) and item.tag.startswith(W) and item.tag.endswith('PrChange') for item in container.iter()):
                    raise ValueError('Tracked paragraph, table or row properties are not supported')


def tracked_change_elements(tree, archive, part, author, kinds):
    import secrets
    from datetime import datetime, timezone
    used = set()
    for name in archive.namelist():
        if not name.startswith('word/') or not name.endswith('.xml'): continue
        part_tree = tree if name == part else ooxml.parse_xml(archive.read(name))
        for item in part_tree.iter():
            value = item.get(W + 'id')
            if value:
                value = value.strip()
                if re.fullmatch(r'[+-]?[0-9]+', value):
                    digits = value.lstrip('+-').lstrip('0') or '0'
                    if len(digits) <= 10: used.add(-int(digits) if value.startswith('-') else int(digits))
    ids = []
    while len(ids) < len(kinds):
        value = secrets.randbelow(2147483647)
        if value not in used: ids.append(value); used.add(value)
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    def change(kind, identifier):
        element = etree.Element(W + kind)
        element.set(W + 'id', str(identifier)); element.set(W + 'author', author); element.set(W + 'date', timestamp)
        return element
    return [change(kind, identifier) for kind, identifier in zip(kinds, ids)]


def track_replace_text(source, output, path, find, replacement, author):
    """Replace a unique Word story text range with Word insertion and deletion records."""
    import copy

    if not replacement_path(path) or Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Target must be a DOCX body, header or footer paragraph path')
    if not isinstance(author, str) or not author.strip() or len(author) > 100 or any(ord(c) < 32 for c in author):
        raise ValueError('Author must contain 1 to 100 characters without control characters')
    ooxml.match_index(find, find, replacement)

    selected_part = None
    def part(file):
        nonlocal selected_part
        selected_part = paragraph_part(file, path)
        return selected_part

    def edit(tree, archive):
        paragraph = find_paragraph(tree, path)
        first, last = anchor_runs(paragraph, find)
        validate_tracked_context(tree, (first, last))
        selected = []; node = first
        while node is not None:
            if node.tag != W + 'r': raise ValueError('Tracked replacement crosses an unsupported boundary')
            for text in node.findall(W + 't'):
                if any(key != '{http://www.w3.org/XML/1998/namespace}space' for key in text.attrib):
                    raise ValueError('Text has unsupported attributes for tracked replacement')
            selected.append(node)
            if node is last: break
            node = node.getnext()
        if not selected or selected[-1] is not last: raise ValueError('Tracked replacement range is inconsistent')
        changes = tracked_change_elements(tree, archive, selected_part, author, ('del', 'ins') if replacement else ('del',))
        deleted = changes[0]; first.addprevious(deleted)
        inserted = changes[1] if replacement else None
        if inserted is not None:
            run = etree.SubElement(inserted, W + 'r'); properties = first.find(W + 'rPr')
            if properties is not None: run.append(copy.deepcopy(properties))
            text = etree.SubElement(run, W + 't'); text.text = replacement
            if replacement.startswith(' ') or replacement.endswith(' '): text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            deleted.addnext(inserted)
        for run in selected:
            for text in run.findall(W + 't'): text.tag = W + 'delText'
            deleted.append(run)
    return ooxml.edit_xml(source, output, part, edit)


def track_insert_text(source, output, path, anchor, text, position, author):
    """Insert a tracked run adjacent to a unique Word story text anchor."""
    import copy
    if not replacement_path(path) or Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Target must be a DOCX body, header or footer paragraph path')
    if not isinstance(author, str) or not author.strip() or len(author) > 100 or any(ord(c) < 32 for c in author):
        raise ValueError('Author must contain 1 to 100 characters without control characters')
    if position not in ('before', 'after'): raise ValueError('Position must be before or after')
    ooxml.match_index(anchor, anchor, text)
    if not text: raise ValueError('Insertion text must not be empty')
    identifier = None
    selected_part = None
    def part(file):
        nonlocal selected_part
        selected_part = paragraph_part(file, path)
        return selected_part

    def edit(tree, archive):
        nonlocal identifier
        first, last = anchor_runs(find_paragraph(tree, path), anchor)
        validate_tracked_context(tree, (first, last))
        inserted = tracked_change_elements(tree, archive, selected_part, author, ('ins',))[0]
        identifier = inserted.get(W + 'id')
        reference = first if position == 'before' else last
        run = etree.SubElement(inserted, W + 'r'); properties = reference.find(W + 'rPr')
        if properties is not None: run.append(copy.deepcopy(properties))
        node = etree.SubElement(run, W + 't'); node.text = text
        if text.startswith(' ') or text.endswith(' '): node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        if position == 'before': first.addprevious(inserted)
        else: last.addnext(inserted)
    result = ooxml.edit_xml(source, output, part, edit)
    return {'file': result, 'id': identifier, 'part': selected_part}


def resolve_tracked_runs(source, output, part, ids, accept):
    """Accept or reject selected simple insertion/deletion run records in one part."""
    if Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx': raise ValueError('Tracked revision resolution requires DOCX input and output')
    if not isinstance(accept, bool): raise ValueError('Accept must be true or false')
    if not isinstance(part, str) or len(part) > 512 or not part.startswith('word/') or '..' in part.split('/'):
        raise ValueError('Provide a supported Word story part')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(value, str) or not re.fullmatch(r'[+-]?[0-9]{1,100}', value) for value in ids):
        raise ValueError('Provide 1 to 100 numeric revision IDs')
    requested = [int(value) for value in ids]
    if len(set(requested)) != len(requested): raise ValueError('Revision IDs must be distinct')
    selected_kind = None

    def select_part(file):
        nonlocal selected_kind
        if part == 'word/document.xml': selected_kind = 'document'; return part
        with zipfile.ZipFile(file) as archive:
            rels = ooxml.parse_xml(archive.read('word/_rels/document.xml.rels')).getroot()
            if rels.tag != REL + 'Relationships': raise ValueError('Invalid document relationships')
            base = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            matches = set()
            for rel in rels.findall(REL + 'Relationship'):
                kind = rel.get('Type', '').removeprefix(base)
                if rel.get('Type') != base + kind or kind not in ('header', 'footer', 'footnotes', 'endnotes') or rel.get('TargetMode') not in (None, 'Internal'): continue
                target = rel.get('Target', '')
                resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
                if target and resolved == part: matches.add(kind)
            if len(matches) == 1:
                selected_kind = {'header': 'hdr', 'footer': 'ftr', 'footnotes': 'footnotes', 'endnotes': 'endnotes'}[matches.pop()]
                return part
        raise ValueError('Part is not a related Word story')

    def edit(tree, archive):
        if tree.getroot().tag != W + selected_kind: raise ValueError('Word story has an invalid root')
        known = {W + name for name in ('ins', 'del', 'moveFrom', 'moveTo')}
        matches = {identifier: [] for identifier in requested}
        for node in tree.iter():
            if node.tag not in known: continue
            value = node.get(W + 'id', '').strip()
            if re.fullmatch(r'[+-]?[0-9]{1,100}', value):
                key = int(value)
                if key in matches: matches[key].append(node)
        chosen = []
        for identifier in requested:
            candidates = matches[identifier]
            if len(candidates) != 1: raise ValueError(f'Revision ID {identifier} is missing or ambiguous')
            node = candidates[0]; parent = node.getparent()
            if node.tag not in (W + 'ins', W + 'del') or parent is None or parent.tag != W + 'p':
                raise ValueError('Only direct paragraph insertion or deletion runs can be resolved')
            if any(key not in (W + 'id', W + 'author', W + 'date') for key in node.attrib): raise ValueError('Revision has unsupported metadata')
            runs = list(node)
            if not runs or any(run.tag != W + 'r' for run in runs): raise ValueError('Revision contains unsupported content')
            text_tag = W + ('t' if node.tag == W + 'ins' else 'delText')
            for run in runs:
                if any(child.tag not in (W + 'rPr', text_tag) for child in run) or not run.findall(text_tag):
                    raise ValueError('Revision contains unsupported run content')
                if any(item.tag in known or item.tag in (W + 'rPrChange', W14 + 'conflictIns', W14 + 'conflictDel') for item in run.iter()):
                    raise ValueError('Revision contains nested tracked formatting')
                for text in run.findall(text_tag):
                    if len(text) or any(key != '{http://www.w3.org/XML/1998/namespace}space' for key in text.attrib):
                        raise ValueError('Revision text has unsupported content or attributes')
            chosen.append(node)
        validate_tracked_context(tree, chosen)
        for node in chosen:
            parent = node.getparent(); keep = (node.tag == W + 'ins') == accept
            if keep:
                position = parent.index(node)
                for run in list(node):
                    for text in run.findall(W + 'delText'): text.tag = W + 't'
                    parent.insert(position, run); position += 1
            parent.remove(node)
    return ooxml.edit_xml(source, output, select_part, edit)


def add_comment(source, output, path, text, author, anchor=None):
    """Attach a plain-text comment to a paragraph or a unique literal range."""
    import posixpath
    import secrets
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
        if anchor is not None:
            first, last = anchor_runs(paragraph, anchor)
        else:
            runs = []
            for child in paragraph:
                if child.tag == W + 'pPr':
                    continue
                if child.tag != W + 'r' or any(node.tag not in (W + 'rPr', W + 't') for node in child):
                    raise ValueError('Comment requires a simple paragraph without fields, links, existing anchors or tracked changes')
                runs.append(child)
            if not runs or not ''.join(node.text or '' for run in runs for node in run.findall(W + 't')).strip():
                raise ValueError('Comment requires a nonempty paragraph')
            first, last = runs[0], runs[-1]
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
        w15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
        mc = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
        ext_type = 'http://schemas.microsoft.com/office/2011/relationships/commentsExtended'
        ext_links = [item for item in relationships if item.get('Type') == ext_type]
        if not links and (ext_links or any(item.get('Type', '').endswith(('/commentsIds', '/commentsExtensible')) for item in relationships)):
            raise ValueError('Modern comment metadata has no comments relationship')
        if len(ext_links) > 1: raise ValueError('Multiple extended comments relationships are unsupported')
        ext_part = None; ext = None; ext_bytes = None
        if ext_links:
            link = ext_links[0]; target = link.get('Target')
            if link.get('TargetMode') == 'External' or not target: raise ValueError('Invalid extended comments relationship')
            ext_part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
            if not ext_part.startswith('word/') or ext_part not in names or ext_part in (comments_part, 'word/document.xml'):
                raise ValueError('Invalid extended comments part')
            ext_bytes = archive.read(ext_part); ext = ooxml.parse_xml(ext_bytes)
            if ext.getroot().tag != w15 + 'commentsEx' or any(isinstance(node.tag, str) and node.tag != w15 + 'commentEx' for node in ext.getroot()):
                raise ValueError('Invalid extended comment metadata')
            records = ext.getroot().findall(w15 + 'commentEx')
            ext_ids = [(node.get(w15 + 'paraId') or '').upper() for node in records]
            if any(not re.fullmatch(r'[0-9A-F]{8}', value) or not 0 < int(value, 16) < 0x80000000 for value in ext_ids) or len(ext_ids) != len(set(ext_ids)):
                raise ValueError('Extended comment identifiers are invalid or ambiguous')
        elif 'word/commentsExtended.xml' in names:
            raise ValueError('Unreferenced extended comments part')
        modern = modern_comment_parts(archive, relationships, comments_part, ext_part)
        if modern['ids_tree'] is not None and ext is None:
            raise ValueError('Modern comments require an extended comments part')
        existing_ids = [node.get(W + 'id') for node in comments.getroot().findall(W + 'comment')]
        if any(value is None or not re.fullmatch(r'[0-9]{1,10}', value) for value in existing_ids) or len({int(value) for value in existing_ids}) != len(existing_ids):
            raise ValueError('Invalid or duplicate comment identifiers')
        used = []
        for item in list(comments.getroot().findall(W + 'comment')) + list(tree.getroot().iter(W + 'commentRangeStart')) + list(tree.getroot().iter(W + 'commentRangeEnd')) + list(tree.getroot().iter(W + 'commentReference')):
            value = item.get(W + 'id')
            if value is None or not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 2147483646:
                raise ValueError('Unsupported comment identifier')
            used.append(int(value))
        comment_id = str(max(used, default=-1) + 1); created_id = int(comment_id)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        comment = etree.SubElement(comments.getroot(), W + 'comment', {W + 'id': comment_id, W + 'author': author, W + 'date': timestamp})
        para_id = None
        if ext is not None:
            reserved = {(node.get(W14_PARAGRAPH_ID) or '').upper() for node in comments.getroot().iter(W + 'p')}
            reserved.update((node.get(attribute) or '').upper() for node in ext.getroot().findall(w15 + 'commentEx') for attribute in (w15 + 'paraId', w15 + 'paraIdParent'))
            reserved.update(modern['para_ids'])
            para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
            while para_id in reserved: para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
        lines = text.split('\n')
        for index, line in enumerate(lines):
            if para_id and index == len(lines) - 1:
                p = etree.SubElement(comment, W + 'p', nsmap={'w14': W14_PARAGRAPH_ID[1:].split('}', 1)[0], 'mc': mc[1:-1]})
                p.set(W14_PARAGRAPH_ID, para_id); p.set(mc + 'Ignorable', 'w14')
            else:
                p = etree.SubElement(comment, W + 'p')
            r = etree.SubElement(p, W + 'r'); t = etree.SubElement(r, W + 't')
            if line.startswith(' ') or line.endswith(' '):
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            t.text = line
        if ext is not None:
            etree.SubElement(ext.getroot(), w15 + 'commentEx', {w15 + 'paraId': para_id, w15 + 'done': '0'})
            additional[ext_part] = ooxml.serialize_xml(ext, ext_bytes)
            additional.update(append_modern_comment(modern, para_id, timestamp))
        start = etree.Element(W + 'commentRangeStart', {W + 'id': comment_id})
        end = etree.Element(W + 'commentRangeEnd', {W + 'id': comment_id})
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


def modern_comment_parts(archive, relationships, comments_part, ext_part, parent_para=None):
    """Validate existing modern comment parts and reserve their identifiers."""
    import posixpath
    def part_for(kind):
        links = [item for item in relationships if item.get('Type') == kind]
        if len(links) != 1 or links[0].get('TargetMode') == 'External' or not links[0].get('Target'):
            raise ValueError('Invalid comment relationship')
        target = links[0].get('Target')
        name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
        if not name.startswith('word/') or name not in archive.namelist(): raise ValueError('Invalid comment part')
        return name
    cid = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'
    cex = '{http://schemas.microsoft.com/office/word/2018/wordml/cex}'
    ids_type = 'http://schemas.microsoft.com/office/2016/09/relationships/commentsIds'
    cex_type = 'http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible'
    ids_links = [item for item in relationships if item.get('Type') == ids_type]
    cex_links = [item for item in relationships if item.get('Type') == cex_type]
    if any(item.get('Type', '').endswith(('/commentsIds', '/commentsExtensible')) and item.get('Type') not in (ids_type, cex_type) for item in relationships):
        raise ValueError('Unsupported modern comment metadata relationship')
    if len(ids_links) > 1 or len(cex_links) > 1 or (cex_links and not ids_links):
        raise ValueError('Modern comment metadata relationships are incomplete or ambiguous')
    if (not ids_links and 'word/commentsIds.xml' in archive.namelist()) or (not cex_links and 'word/commentsExtensible.xml' in archive.namelist()):
        raise ValueError('Unreferenced modern comment metadata part')
    ids_tree = None; cex_tree = None; modern_para_ids = set(); durable_ids = set()
    if ids_links:
        ids_part = part_for(ids_type); ids_bytes = archive.read(ids_part); ids_tree = ooxml.parse_xml(ids_bytes)
        if ids_tree.getroot().tag != cid + 'commentsIds' or any(isinstance(node.tag, str) and node.tag != cid + 'commentId' for node in ids_tree.getroot()):
            raise ValueError('Invalid comment-ID metadata')
        mapping = {}
        for record in ids_tree.getroot().findall(cid + 'commentId'):
            pid = (record.get(cid + 'paraId') or '').upper(); durable = (record.get(cid + 'durableId') or '').upper()
            if not re.fullmatch(r'[0-9A-F]{8}', pid) or not 0 < int(pid, 16) < 0x80000000 or not re.fullmatch(r'[0-9A-F]{8}', durable) or not 0 < int(durable, 16) < 0x7fffffff:
                raise ValueError('Invalid modern comment identifier')
            if pid in mapping or durable in durable_ids: raise ValueError('Duplicate modern comment identifier')
            mapping[pid] = durable; durable_ids.add(durable)
        modern_para_ids = set(mapping)
        parent_durable = mapping.get(parent_para.upper()) if parent_para else None
        if parent_para and not parent_durable: raise ValueError('Parent has no unique durable comment ID')
        if ids_part in (comments_part, ext_part, 'word/document.xml'):
            raise ValueError('Comment metadata parts overlap')
        if cex_links:
            cex_part = part_for(cex_type); cex_bytes = archive.read(cex_part); cex_tree = ooxml.parse_xml(cex_bytes)
            if cex_part in (ids_part, comments_part, ext_part, 'word/document.xml') or cex_tree.getroot().tag != cex + 'commentsExtensible':
                raise ValueError('Invalid extensible comment metadata')
            cex_ids = set(); parent_records = []; seen_extension = False
            for record in cex_tree.getroot():
                if not isinstance(record.tag, str): continue
                if record.tag == cex + 'extLst':
                    if seen_extension: raise ValueError('Duplicate extensible comment extension list')
                    seen_extension = True; continue
                if record.tag != cex + 'commentExtensible' or seen_extension: raise ValueError('Unsupported extensible comment metadata')
                durable = (record.get(cex + 'durableId') or '').upper()
                if not re.fullmatch(r'[0-9A-F]{8}', durable) or not 0 < int(durable, 16) < 0x7fffffff or durable in cex_ids:
                    raise ValueError('Invalid or duplicate extensible comment ID')
                cex_ids.add(durable)
                if durable == parent_durable: parent_records.append(record)
            if parent_para and (len(parent_records) != 1 or parent_records[0].get(cex + 'intelligentPlaceholder', '0') not in ('0', 'false', 'off')):
                raise ValueError('Parent extensible comment metadata is missing or unsupported')
            durable_ids.update(cex_ids)
    return {'ids_tree': ids_tree, 'ids_part': ids_part if ids_tree is not None else None,
            'ids_bytes': ids_bytes if ids_tree is not None else None,
            'cex_tree': cex_tree, 'cex_part': cex_part if cex_tree is not None else None,
            'cex_bytes': cex_bytes if cex_tree is not None else None,
            'para_ids': modern_para_ids, 'durable_ids': durable_ids}


def append_modern_comment(parts, para_id, timestamp):
    """Add the new comment to modern parts that already exist."""
    import secrets
    from lxml import etree
    cid = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'
    cex = '{http://schemas.microsoft.com/office/word/2018/wordml/cex}'
    ids_tree = parts['ids_tree']; cex_tree = parts['cex_tree']; additional = {}
    if ids_tree is not None:
        durable_id = f'{secrets.randbelow(0x7ffffffe) + 1:08X}'
        while durable_id in parts['durable_ids']: durable_id = f'{secrets.randbelow(0x7ffffffe) + 1:08X}'
        etree.SubElement(ids_tree.getroot(), cid + 'commentId', {cid + 'paraId': para_id, cid + 'durableId': durable_id})
        additional[parts['ids_part']] = ooxml.serialize_xml(ids_tree, parts['ids_bytes'])
        if cex_tree is not None:
            record = etree.Element(cex + 'commentExtensible', {cex + 'durableId': durable_id, cex + 'dateUtc': timestamp})
            extension = cex_tree.getroot().find(cex + 'extLst')
            if extension is None: cex_tree.getroot().append(record)
            else: extension.addprevious(record)
            additional[parts['cex_part']] = ooxml.serialize_xml(cex_tree, parts['cex_bytes'])
    return additional


def reply_comment(source, output, parent_id, text, author):
    """Add a plain-text reply to a root comment using its existing body range."""
    import posixpath
    import secrets
    import tempfile
    import zipfile
    from datetime import datetime, timezone
    from lxml import etree

    if Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Comment replies require DOCX input and output')
    if not isinstance(parent_id, str) or not re.fullmatch(r'0|[1-9][0-9]{0,9}', parent_id) or int(parent_id) > 2147483647:
        raise ValueError('Parent comment ID must be a nonnegative decimal string')
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or any(ord(c) < 32 and c != '\n' for c in text):
        raise ValueError('Reply must contain 1 to 4,000 characters without control characters')
    if not isinstance(author, str) or not author.strip() or len(author) > 100 or any(ord(c) < 32 for c in author):
        raise ValueError('Author must contain 1 to 100 characters without control characters')
    state = list_comments(source); parent = next((item for item in state['comments'] if item['id'] == parent_id), None)
    if parent is None: raise ValueError('Parent comment was not found in the first 200 comments')
    if not state['anchor_scan_complete'] or parent['anchor_status'] != 'range':
        raise ValueError('Parent comment must have one complete main-body anchor')
    if parent['thread_metadata'] == 'matched':
        if parent['reply_parent_status'] != 'root': raise ValueError('Reply to a root comment')
        if parent['resolved']: raise ValueError('Reopen the resolved comment before replying')
        initialize = False
    elif state['thread_metadata_status'] in ('absent', 'available') and parent['thread_metadata'] in ('missing', 'unavailable'):
        initialize = True
    else:
        raise ValueError('Parent comment thread metadata is ambiguous or invalid')
    rel_ns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    w15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
    mc = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
    comments_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
    extended_type = 'http://schemas.microsoft.com/office/2011/relationships/commentsExtended'
    created_id = None

    def edit(tree, archive):
        nonlocal created_id
        if tree.getroot().tag != W + 'document': raise ValueError('Invalid document XML')
        rels = ooxml.parse_xml(archive.read('word/_rels/document.xml.rels'))
        if rels.getroot().tag != rel_ns + 'Relationships': raise ValueError('Invalid document relationships')
        relationships = rels.getroot().findall(rel_ns + 'Relationship')
        def part_for(kind):
            links = [item for item in relationships if item.get('Type') == kind]
            if len(links) != 1 or links[0].get('TargetMode') == 'External' or not links[0].get('Target'):
                raise ValueError('Invalid comment relationship')
            target = links[0].get('Target')
            name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
            if not name.startswith('word/') or name not in archive.namelist(): raise ValueError('Invalid comment part')
            return name
        comments_part = part_for(comments_type); ext_part = part_for(extended_type)
        comments_bytes = archive.read(comments_part); ext_bytes = archive.read(ext_part)
        comments = ooxml.parse_xml(comments_bytes); ext = ooxml.parse_xml(ext_bytes)
        if comments.getroot().tag != W + 'comments' or ext.getroot().tag != w15 + 'commentsEx': raise ValueError('Invalid comment XML')
        nodes = comments.getroot().findall(W + 'comment'); values = [node.get(W + 'id') for node in nodes]
        if any(value is None or not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 2147483646 for value in values) or len({int(value) for value in values}) != len(values):
            raise ValueError('Invalid or duplicate comment identifiers')
        parents = [node for node in nodes if node.get(W + 'id') == parent_id]
        if len(parents) != 1: raise ValueError('Parent comment is ambiguous')
        metadata, status = comment_thread_metadata(archive, relationships, nodes); parent_meta = metadata.get(parent_id, {})
        if status != 'available' or parent_meta.get('thread_metadata') != 'matched' or parent_meta.get('reply_parent_status') != 'root' or parent_meta.get('resolved') is not False:
            raise ValueError('Parent must have unambiguous open root-thread metadata')
        parent_paragraphs = list(parents[0].iter(W + 'p')); parent_para = parent_paragraphs[-1].get(W14_PARAGRAPH_ID) if parent_paragraphs else None
        if not parent_para or not re.fullmatch(r'[0-9A-Fa-f]{8}', parent_para) or not 0 < int(parent_para, 16) < 0x80000000 or sum((node.get(W14_PARAGRAPH_ID) or '').upper() == parent_para.upper() for node in comments.getroot().iter(W + 'p')) != 1:
            raise ValueError('Parent paragraph ID is ambiguous')
        modern = modern_comment_parts(archive, relationships, comments_part, ext_part, parent_para)
        markers = [node for node in tree.getroot().iter() if node.tag in (W + 'commentRangeStart', W + 'commentRangeEnd', W + 'commentReference') and node.get(W + 'id') == parent_id]
        if [node.tag for node in markers] != [W + 'commentRangeStart', W + 'commentRangeEnd', W + 'commentReference']:
            raise ValueError('Parent comment must have one ordered main-body anchor')
        body = tree.getroot().find(W + 'body')
        if body is None or any(body not in node.iterancestors() for node in markers): raise ValueError('Parent anchor is outside the main body')
        if any(node.getparent() is None or node.getparent().tag != W + 'p' for node in markers[:2]):
            raise ValueError('Parent anchor boundaries must be direct paragraph children')
        used_ids = [int(value) for value in values]
        for tag in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
            for marker in tree.getroot().iter(W + tag):
                value = marker.get(W + 'id')
                if value is None or not re.fullmatch(r'[0-9]{1,10}', value) or int(value) > 2147483646:
                    raise ValueError('Unsupported comment identifier')
                used_ids.append(int(value))
        created_id = max(used_ids, default=-1) + 1
        para_ids = {(node.get(W14_PARAGRAPH_ID) or '').upper() for node in comments.getroot().iter(W + 'p')}
        ext_ids = {(node.get(attribute) or '').upper() for node in ext.getroot().findall(w15 + 'commentEx') for attribute in (w15 + 'paraId', w15 + 'paraIdParent')}
        para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
        while para_id in para_ids or para_id in ext_ids or para_id in modern['para_ids']: para_id = f'{secrets.randbelow(0x7fffffff) + 1:08X}'
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        comment = etree.SubElement(comments.getroot(), W + 'comment', {W + 'id': str(created_id), W + 'author': author, W + 'date': timestamp})
        lines = text.split('\n')
        for index, line in enumerate(lines):
            p = etree.SubElement(comment, W + 'p', nsmap={'w14': W14_PARAGRAPH_ID[1:].split('}', 1)[0], 'mc': mc[1:-1]})
            if index == len(lines) - 1:
                p.set(W14_PARAGRAPH_ID, para_id); p.set(mc + 'Ignorable', 'w14')
            r = etree.SubElement(p, W + 'r'); t = etree.SubElement(r, W + 't'); t.text = line
            if line.startswith(' ') or line.endswith(' '): t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        etree.SubElement(ext.getroot(), w15 + 'commentEx', {w15 + 'paraId': para_id, w15 + 'paraIdParent': parent_para.upper(), w15 + 'done': '0'})
        modern_additional = append_modern_comment(modern, para_id, timestamp)
        start = etree.Element(W + 'commentRangeStart', {W + 'id': str(created_id)})
        end = etree.Element(W + 'commentRangeEnd', {W + 'id': str(created_id)})
        markers[0].addprevious(start); markers[1].addnext(end)
        reference = etree.Element(W + 'r'); props = etree.SubElement(reference, W + 'rPr')
        etree.SubElement(props, W + 'rStyle', {W + 'val': 'CommentReference'})
        etree.SubElement(reference, W + 'commentReference', {W + 'id': str(created_id)}); end.addnext(reference)
        return {comments_part: ooxml.serialize_xml(comments, comments_bytes), ext_part: ooxml.serialize_xml(ext, ext_bytes), **modern_additional}

    with tempfile.TemporaryDirectory(dir=Path(output).absolute().parent, prefix='.office-reply-') as tmp:
        prepared = source
        if initialize:
            prepared = Path(tmp) / 'prepared.docx'
            set_comment_resolved(source, prepared, parent_id, False)
        file = ooxml.edit_xml(prepared, output, lambda _: 'word/document.xml', edit)
    return {'file': file, 'comment_id': created_id, 'parent_id': parent_id}
