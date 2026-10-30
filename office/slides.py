"""Conservative text replacement in a PowerPoint slide paragraph."""
import re
import tempfile
import snapshot as snapshots
import zipfile
from pathlib import Path

from pptx import Presentation
from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE

import ooxml

P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
P14 = '{http://schemas.microsoft.com/office/powerpoint/2010/main}'
INDEX = r'[1-9][0-9]{0,5}'
SELECTOR = r'(?:' + INDEX + r'|@id=' + INDEX + r')'
PATH = re.compile(r'/slide\[(' + INDEX + r')\](?:/group\[' + SELECTOR + r'\]){0,8}(?:/shape\[' + SELECTOR + r'\]|/table\[' + SELECTOR + r'\]/tr\[' + INDEX + r'\]/tc\[' + INDEX + r'\])(?:/paragraph\[(' + INDEX + r')\])?\Z')
SEGMENT = re.compile(r'/(group|shape|table|tr|tc)\[([^]]+)\]')
NOTES_PATH = re.compile(r'/slide\[(' + INDEX + r')\]/notes/paragraph\[(' + INDEX + r')\]\Z')


def paragraph_path(path):
    return isinstance(path, str) and len(path) <= 512 and PATH.fullmatch(path) is not None


def search_text(source, query, slide=None, offset=0, snapshot_sha256=None, scope='slides'):
    """Search slide or speaker-note paragraphs using bounded candidates."""
    if scope not in ('slides', 'notes'): raise ValueError('Search scope must be slides or notes')
    if not isinstance(query, str) or not query or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise ValueError('Search text must contain 1 to 200 characters without control characters')
    if isinstance(slide, bool) or slide is not None and (not isinstance(slide, int) or slide < 1): raise ValueError('Slide must be a positive integer')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0: raise ValueError('Offset must be a nonnegative integer')
    if offset and snapshot_sha256 is None: raise ValueError('Continuing a search requires the prior snapshot SHA-256')
    if snapshot_sha256 is not None and (not isinstance(snapshot_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot_sha256)):
        raise ValueError('Invalid snapshot SHA-256')
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.pptx': raise ValueError('Slide search requires a PPTX file')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Presentation exceeds the 128 MiB size limit')
    with tempfile.TemporaryDirectory(prefix='office-slide-search-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        if snapshot_sha256 is not None and digest != snapshot_sha256: raise ValueError('Presentation snapshot changed; restart the search')
        try:
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist(); names = [entry.filename for entry in entries]
                if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                    raise ValueError('Presentation exceeds package limits or contains duplicate parts')
            presentation = Presentation(snapshot)
            if slide is not None and slide > len(presentation.slides): raise ValueError('Slide does not exist')
            unsupported = set()
            def events(shapes, prefix, slide_number, hidden, depth):
                if depth > 8:
                    unsupported.add('group_depth'); return
                if shapes._spTree.find(MC + 'AlternateContent') is not None: unsupported.add('alternate_content')
                allowed = {P + name for name in ('nvGrpSpPr', 'grpSpPr', 'sp', 'grpSp', 'graphicFrame', 'pic', 'cxnSp', 'extLst')}
                if any(child.tag not in allowed and child.tag != MC + 'AlternateContent' for child in shapes._spTree): unsupported.add('shape_tree_structure')
                counts = {'shape': 0, 'group': 0, 'table': 0}
                for shape in shapes:
                    yield None
                    tag = shape._element.tag
                    if tag == P + 'grpSp':
                        counts['group'] += 1
                        yield from events(shape.shapes, f"{prefix}/group[{counts['group']}]", slide_number, hidden, depth + 1)
                    elif tag == P + 'sp':
                        counts['shape'] += 1
                        if shape.has_text_frame:
                            for index, paragraph in enumerate(shape.text_frame.paragraphs, 1):
                                yield (f"{prefix}/shape[{counts['shape']}]/paragraph[{index}]", paragraph._p, slide_number, hidden)
                    elif tag == P + 'graphicFrame' and shape.has_table:
                        counts['table'] += 1
                        for row_index, row in enumerate(shape.table.rows, 1):
                            for col_index, cell in enumerate(row.cells, 1):
                                if cell.is_spanned: continue
                                for index, paragraph in enumerate(cell.text_frame.paragraphs, 1):
                                    yield (f"{prefix}/table[{counts['table']}]/tr[{row_index}]/tc[{col_index}]/paragraph[{index}]", paragraph._p, slide_number, hidden)
                    elif tag == MC + 'AlternateContent':
                        unsupported.add('alternate_content')
            def all_events():
                for number, item in enumerate(presentation.slides, 1):
                    if slide is not None and slide != number: continue
                    visibility = item._element.get('show')
                    hidden = visibility in ('0', 'false') if visibility in (None, '0', 'false', '1', 'true') else None
                    if scope == 'slides':
                        yield from events(item.shapes, f'/slide[{number}]', number, hidden, 0)
                    else:
                        yield None
                        if item.has_notes_slide:
                            frame = item.notes_slide.notes_text_frame
                            if frame is None: unsupported.add('missing_notes_placeholder')
                            else:
                                for index, paragraph in enumerate(frame.paragraphs, 1):
                                    yield (f'/slide[{number}]/notes/paragraph[{index}]', paragraph._p, number, hidden)

            matches, scanned, skipped, uncertain = [], 0, 0, 0
            scan_complete = True; stop_reason = None
            for event in all_events():
                if skipped < offset: skipped += 1; continue
                if scanned >= 10000 or len(matches) >= 100:
                    scan_complete = False; stop_reason = 'match_limit' if len(matches) >= 100 else 'item_limit'; break
                scanned += 1
                if event is None: continue
                path, paragraph, number, hidden = event
                text = ''.join(node.text or '' for node in paragraph.iter(A + 't'))
                text_complete = all(child.tag in (A + 'pPr', A + 'r', A + 'endParaRPr') and (child.tag != A + 'r' or all(item.tag in (A + 'rPr', A + 't') for item in child)) for child in paragraph)
                if not text_complete: uncertain += 1
                if query in text:
                    index = text.index(query); start = max(0, index - 100); end = min(len(text), index + len(query) + 100)
                    matches.append({'slide': number, 'hidden': hidden, 'path': path, 'excerpt': text[start:end], 'excerpt_start': start,
                                    'text_length': len(text), 'occurrences': sum(1 for _ in re.finditer('(?=' + re.escape(query) + ')', text)),
                                    'text_complete': text_complete, 'replace_text_path_supported': paragraph_path(path) or bool(NOTES_PATH.fullmatch(path)), **({'notes_paragraph': int(path.rsplit('[', 1)[1][:-1])} if scope == 'notes' else {})})
            if skipped < offset: raise ValueError('Search offset exceeds the selected slide content')
            return {'query': query, 'slide': slide, 'scope': scope, 'total_slides': len(presentation.slides), 'snapshot_sha256': digest,
                    'offset': offset, 'next_offset': offset + scanned if not scan_complete else None, 'stop_reason': stop_reason,
                    'items_scanned': scanned, 'matches': matches, 'unverified_paragraphs': uncertain,
                    'unsupported_structure': sorted(unsupported), 'scan_complete': scan_complete,
                    'complete': offset == 0 and scan_complete and not uncertain and not unsupported,
                    'limits': {'items': 10000, 'matches': 100},
                    'notes': ["Search covers speaker-note paragraphs, including hidden slides; other notes shapes and masters are excluded." if scope == 'notes' else 'Search covers slide shape and table paragraphs, including hidden slides; masters, notes, charts and SmartArt are excluded.',
                              'Paths are candidates; inspect structure and validate targeted edits before applying them.']}
        except zipfile.BadZipFile as exc:
            raise ValueError(f'Invalid presentation package: {exc}') from exc


def slide_part(file, index):
    presentation = Presentation(file)
    listing = presentation._element.find(P + 'sldIdLst')
    entries = listing.findall(P + 'sldId') if listing is not None else []
    if index >= len(entries):
        raise ValueError('Slide does not exist')
    parts = []
    for entry in entries:
        relationship = presentation.part.rels[entry.get(R + 'id')]
        if relationship.is_external or relationship.reltype != RELATIONSHIP_TYPE.SLIDE:
            raise ValueError('Slide relationship is invalid')
        parts.append(str(relationship.target_part.partname).lstrip('/'))
    if parts.count(parts[index]) != 1:
        raise ValueError('Slide part is referenced by multiple slides')
    return parts[index]




def section_groups(root, ids):
    if root.find(MC + 'AlternateContent') is not None: raise ValueError('Presentation alternate content is unsupported for slide reorder')
    extensions = root.findall(P + 'extLst')
    if len(extensions) > 1: raise ValueError('Presentation extensions are ambiguous')
    if extensions:
        extension_items = list(extensions[0])
        if len(extension_items) != 1 or extension_items[0].tag != P + 'ext' or extension_items[0].get('uri', '').upper() != '{521415D9-36F7-43E2-AB2F-B90AF26B5E84}' or len(extension_items[0]) != 1 or extension_items[0][0].tag != P14 + 'sectionLst':
            raise ValueError('Unsupported presentation extensions for slide reorder')
        sections = extension_items[0][0]; section_items = list(sections); groups = []; members = []
        if not section_items: raise ValueError('Presentation section list is empty')
        section_ids = [section.get('id') for section in section_items]
        if any(not value for value in section_ids) or len({value.casefold() for value in section_ids}) != len(section_ids): raise ValueError('Presentation section IDs are ambiguous')
        for section in section_items:
            if section.tag != P14 + 'section' or len(section) != 1 or section[0].tag != P14 + 'sldIdLst': raise ValueError('Unsupported presentation section structure')
            group = list(section[0]); group_ids = [node.get('id') for node in group]
            if not group or any(node.tag != P14 + 'sldId' or len(node) or set(node.attrib) != {'id'} for node in group) or any(not item or not item.isascii() or not item.isdecimal() for item in group_ids): raise ValueError('Unsupported presentation section slide list')
            groups.append((section, group)); members.extend(int(item) for item in group_ids)
        if any(not item.isascii() or not item.isdecimal() for item in ids) or members != [int(item) for item in ids] or len(set(members)) != len(members):
            raise ValueError('Presentation section membership or order is ambiguous')
        return sections, groups
    return None


def inventory(source):
    """List a bounded slide order and supported section membership from one snapshot."""
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.pptx' or source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Slide inventory requires a PPTX of at most 128 MiB')
    with tempfile.TemporaryDirectory(prefix='office-slide-inventory-') as tmp:
        snapshot, digest = snapshots.copy(source, tmp)
        with zipfile.ZipFile(snapshot) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or len({item.filename for item in entries}) != len(entries) or sum(item.file_size for item in entries) > 128 * 1024 * 1024: raise ValueError('Presentation exceeds package limits or contains duplicate parts')
        presentation = Presentation(snapshot); root = presentation._element
        lists = root.findall(P + 'sldIdLst')
        if len(lists) > 1: raise ValueError('Presentation slide list is ambiguous')
        entries = list(lists[0]) if lists else []
        if len(entries) > 1000: raise ValueError('Slide inventory supports at most 1000 slides')
        if any(item.tag != P + 'sldId' for item in entries): raise ValueError('Unsupported slide list structure')
        ids = [item.get('id') for item in entries]; rels = [item.get(R + 'id') for item in entries]
        if any(not value for value in ids + rels) or len(set(ids)) != len(ids) or len(set(rels)) != len(rels): raise ValueError('Presentation slide IDs or relationships are ambiguous')
        result = []; targets = []
        for number, (item, relationship_id) in enumerate(zip(presentation.slides, rels), 1):
            try: relationship = presentation.part.rels[relationship_id]
            except KeyError: raise ValueError('Slide relationship is missing') from None
            if relationship.is_external or relationship.reltype != RELATIONSHIP_TYPE.SLIDE: raise ValueError('Slide relationship is invalid')
            target = str(relationship.target_part.partname); targets.append(target)
            title = item.shapes.title.text if item.shapes.title is not None else ''
            visible = item._element.get('show')
            result.append({'slide':number, 'id':ids[number-1], 'title':title[:500], 'title_truncated':len(title)>500, 'hidden':visible in ('0','false') if visible in (None,'0','false','1','true') else None, 'has_notes':item.has_notes_slide})
        if len(result) != len(entries) or len(set(targets)) != len(targets): raise ValueError('Slide parts are ambiguous')
        sections = []
        try:
            grouping = section_groups(root, ids)
            section_status = 'supported' if grouping is not None else 'none'; issue = None
            if grouping is not None:
                _, groups = grouping; positions = {int(value): number for number, value in enumerate(ids,1)}
                for section, nodes in groups:
                    name = section.get('name', '')
                    sections.append({'id':section.get('id'), 'name':name[:500], 'name_truncated':len(name)>500, 'slides':[positions[int(node.get('id'))] for node in nodes]})
        except ValueError as exc:
            section_status = 'unsupported'; issue = str(exc)
        return {'snapshot_sha256':digest, 'slides':result, 'sections':sections, 'section_status':section_status, 'section_issue':issue}

def reorder(source, output, order, expected_sha256=None):
    """Reorder the presentation's existing slide IDs in a new package."""
    if not isinstance(order, list) or not order or len(order) > 1000 or any(isinstance(i, bool) or not isinstance(i, int) for i in order):
        raise ValueError('Slide order must be a nonempty list of at most 1000 slide numbers')
    if Path(source).suffix.lower() != '.pptx' or Path(output).suffix.lower() != '.pptx': raise ValueError('Slide reorder requires PPTX input and output')
    presentation = None
    def select(file):
        nonlocal presentation
        presentation = Presentation(file)
        return str(presentation.part.partname).lstrip('/')
    def edit(tree, archive):
        root = tree.getroot()
        if root.tag != P + 'presentation' or root.find(MC + 'AlternateContent') is not None:
            raise ValueError('Presentation alternate content is unsupported for slide reorder')
        lists = root.findall(P + 'sldIdLst')
        if len(lists) != 1: raise ValueError('Presentation slide list is missing or ambiguous')
        listing = lists[0]; entries = list(listing)
        if any(item.tag != P + 'sldId' for item in entries) or len(entries) != len(order) or sorted(order) != list(range(1, len(entries) + 1)):
            raise ValueError('Slide order must contain every slide number exactly once')
        ids = [item.get('id') for item in entries]; relationships = [item.get(R + 'id') for item in entries]
        if any(not value for value in ids + relationships) or len(set(ids)) != len(ids) or len(set(relationships)) != len(relationships): raise ValueError('Presentation slide IDs or relationships are ambiguous')
        grouping = section_groups(root, ids)
        if grouping is not None:
            sections, groups = grouping
            owner = {int(node.get('id')): index for index, (_, group) in enumerate(groups) for node in group}
            reordered_ids = [int(ids[number - 1]) for number in order]
            owners = [owner[value] for value in reordered_ids]
            section_order = list(dict.fromkeys(owners))
            if any(owners.count(index) != len(groups[index][1]) or owners.index(index) + owners.count(index) - 1 != len(owners) - 1 - owners[::-1].index(index) for index in section_order):
                raise ValueError('Reorder must keep each section contiguous')
            for section, _ in groups: sections.remove(section)
            for index in section_order:
                section, group = groups[index]; group_list = section[0]; by_id = {int(node.get('id')): node for node in group}
                for node in group: group_list.remove(node)
                for value in reordered_ids:
                    if owner[value] == index: group_list.append(by_id[value])
                sections.append(section)
        targets = []
        for relationship_id in relationships:
            try: relationship = presentation.part.rels[relationship_id]
            except KeyError: raise ValueError('Slide relationship is missing') from None
            if relationship.is_external or relationship.reltype != RELATIONSHIP_TYPE.SLIDE: raise ValueError('Slide relationship is invalid')
            targets.append(str(relationship.target_part.partname))
        if len(set(targets)) != len(targets): raise ValueError('Slide part is referenced by multiple slides')
        for item in entries: listing.remove(item)
        for number in order: listing.append(entries[number - 1])
    return ooxml.edit_xml(source, output, select, edit, expected_sha256=expected_sha256)

def find_paragraph(tree, path):
    match = PATH.fullmatch(path) if paragraph_path(path) else None
    if not match: raise ValueError('Target must be a slide shape or table-cell paragraph path')
    paragraph_index = int(match.group(2)) - 1 if match.group(2) else None
    if tree.getroot().tag != P + 'sld':
        raise ValueError('Slide XML has an invalid root')
    parent = tree.getroot().find(P + 'cSld/' + P + 'spTree')
    if parent is None:
        raise ValueError('Slide has no shape tree')
    for kind, selector in SEGMENT.findall(path):
        if parent.find(MC + 'AlternateContent') is not None:
            raise ValueError('Target container contains unsupported alternate content')
        if kind in ('group', 'shape', 'table'):
            tag = {'group': 'grpSp', 'shape': 'sp', 'table': 'graphicFrame'}[kind]
            children = parent.findall(P + tag)
            if kind == 'table':
                children = [child for child in children if child.find(A + 'graphic/' + A + 'graphicData/' + A + 'tbl') is not None]
            if selector.startswith('@id='):
                requested = selector.partition('=')[2]
                nonvisual = {'group': 'nvGrpSpPr', 'shape': 'nvSpPr', 'table': 'nvGraphicFramePr'}[kind]
                children = [child for child in children if child.find(P + nonvisual + '/' + P + 'cNvPr') is not None
                            and child.find(P + nonvisual + '/' + P + 'cNvPr').get('id') == requested]
                if len(children) != 1:
                    raise ValueError('Shape ID must identify exactly one shape in its container')
                parent = children[0]
            else:
                index = int(selector) - 1
                if index >= len(children):
                    raise ValueError('Shape path does not exist')
                parent = children[index]
            if kind == 'table':
                tables = parent.findall(A + 'graphic/' + A + 'graphicData/' + A + 'tbl')
                if len(tables) != 1:
                    raise ValueError('Table frame must contain exactly one table')
                parent = tables[0]
        else:
            children = parent.findall(A + kind)
            index = int(selector) - 1
            if index >= len(children):
                raise ValueError('Table cell path does not exist')
            parent = children[index]
            if kind == 'tc' and any(parent.get(key) not in (None, '0', 'false') for key in ('hMerge', 'vMerge')):
                raise ValueError('Merged-cell placeholders cannot be edited; use the merged cell origin')
    text_body = parent.find(A + 'txBody') if parent.tag == A + 'tc' else parent.find(P + 'txBody')
    if text_body is None:
        raise ValueError('Target has no editable text body')
    paragraphs = text_body.findall(A + 'p')
    if paragraph_index is None:
        if len(paragraphs) != 1:
            raise ValueError('Choose a paragraph in a target with multiple paragraphs')
        paragraph_index_value = 0
    else:
        paragraph_index_value = paragraph_index
    if paragraph_index_value >= len(paragraphs):
        raise ValueError('Paragraph does not exist')
    paragraph = paragraphs[paragraph_index_value]
    return paragraph


def paragraph_nodes(paragraph):
    if any(child.tag not in (A + 'pPr', A + 'r', A + 'endParaRPr') for child in paragraph):
        raise ValueError('Paragraph contains unsupported content such as fields or line breaks')
    nodes = []
    for run in paragraph.findall(A + 'r'):
        if any(child.tag not in (A + 'rPr', A + 't') for child in run):
            raise ValueError('Run contains unsupported content')
        nodes.extend(run.findall(A + 't'))
    return nodes


def replace_paragraph(paragraph, find, replacement, preserve_space=False):
    nodes = paragraph_nodes(paragraph)
    text = ''.join(node.text or '' for node in nodes); start = ooxml.match_index(text, find, replacement); end = start + len(find)
    offset = 0; links = set()
    for node in nodes:
        next_offset = offset + len(node.text or '')
        if offset < end and next_offset > start:
            run = node.getparent(); link_nodes = [link for link in run.iter() if link.tag in (A+'hlinkClick', A+'hlinkMouseOver')]
            if len(link_nodes) > 2: raise ValueError('Run contains ambiguous hyperlink metadata')
            signature = tuple(etree.tostring(link, method='c14n') for link in link_nodes)
            if sum(map(len, signature)) > 32768: raise ValueError('Hyperlink metadata exceeds inspection limit')
            links.add(signature)
        offset = next_offset
    if len(links) > 1: raise ValueError('Match crosses a hyperlink boundary')
    ooxml.replace_nodes(nodes, find, replacement, preserve_space=preserve_space)


def replace_text(source, output, path, find, replacement):
    match = PATH.fullmatch(path) if paragraph_path(path) else None
    if not match:
        raise ValueError('Target must be a slide shape or table-cell paragraph path')
    if Path(source).suffix.lower() != '.pptx' or Path(output).suffix.lower() != '.pptx':
        raise ValueError('Text replacement requires PPTX input and output')
    slide_index = int(match.group(1)) - 1

    def edit(tree, archive):
        replace_paragraph(find_paragraph(tree, path), find, replacement)

    return ooxml.edit_xml(source, output, lambda file: slide_part(file, slide_index), edit)


def replace_picture(source, output, path, image_data):
    """Replace one embedded picture while preserving slide XML geometry and crop."""
    import io
    import posixpath
    import uuid
    from PIL import Image

    picture_path = re.compile(r'/slide\[(' + INDEX + r')\](?:/group\[' + SELECTOR + r'\]){0,8}/picture\[' + SELECTOR + r'\]\Z')
    match = picture_path.fullmatch(path) if isinstance(path, str) and len(path) <= 512 else None
    if not match or Path(source).suffix.lower() != '.pptx' or Path(output).suffix.lower() != '.pptx':
        raise ValueError('Target must be a PPTX picture path')
    if not isinstance(image_data, bytes) or not 0 < len(image_data) <= 10 * 1024 * 1024:
        raise ValueError('Image must be at most 10 MiB')
    try:
        with Image.open(io.BytesIO(image_data)) as image:
            image_format = image.format
            if image_format not in ('PNG', 'JPEG') or image.width * image.height > 40_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Use a static PNG or JPEG up to 40 megapixels')
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Invalid or oversized image') from exc
    extension, content_type = ('png', 'image/png') if image_format == 'PNG' else ('jpg', 'image/jpeg')
    part = None
    def select_part(file):
        nonlocal part
        part = slide_part(file, int(match.group(1)) - 1)
        return part
    package_rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    types = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    media = 'ppt/media/office-use-' + uuid.uuid4().hex + '.' + extension

    def edit(tree, archive):
        parent = tree.getroot().find(P + 'cSld/' + P + 'spTree')
        if tree.getroot().tag != P + 'sld' or parent is None:
            raise ValueError('Invalid slide shape tree')
        for kind, selector in re.findall(r'/(group|picture)\[([^]]+)\]', path):
            if parent.find(MC + 'AlternateContent') is not None:
                raise ValueError('Target container contains unsupported alternate content')
            children = parent.findall(P + ('grpSp' if kind == 'group' else 'pic'))
            if selector.startswith('@id='):
                nv = 'nvGrpSpPr' if kind == 'group' else 'nvPicPr'
                children = [child for child in children if child.find(P + nv + '/' + P + 'cNvPr') is not None and child.find(P + nv + '/' + P + 'cNvPr').get('id') == selector[4:]]
                if len(children) != 1:
                    raise ValueError('Object ID must identify exactly one object in its container')
                parent = children[0]
            else:
                index = int(selector) - 1
                if index >= len(children):
                    raise ValueError('Picture path does not exist')
                parent = children[index]
        blips = parent.findall(P + 'blipFill/' + A + 'blip')
        if len(blips) != 1 or not blips[0].get(R + 'embed') or blips[0].get(R + 'link') or len(blips[0]):
            raise ValueError('Only simple embedded pictures are supported')
        rels_part = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        rel_bytes = archive.read(rels_part); rel_tree = ooxml.parse_xml(rel_bytes)
        if rel_tree.getroot().tag != package_rel + 'Relationships':
            raise ValueError('Invalid slide relationships')
        relations = rel_tree.getroot().findall(package_rel + 'Relationship')
        old = [rel for rel in relations if rel.get('Id') == blips[0].get(R + 'embed')]
        if len(old) != 1 or old[0].get('Type') != RELATIONSHIP_TYPE.IMAGE or old[0].get('TargetMode') == 'External':
            raise ValueError('Picture relationship is invalid')
        # shortcut: retain old media and relationships; remove only with package-wide reference analysis.
        existing = {rel.get('Id') for rel in relations}
        rid = 'rIdOfficeUse' + uuid.uuid4().hex
        if rid in existing or media in archive.namelist():
            raise ValueError('Package identifier collision')
        from lxml import etree
        etree.SubElement(rel_tree.getroot(), package_rel + 'Relationship', Id=rid, Type=RELATIONSHIP_TYPE.IMAGE,
                         Target=posixpath.relpath(media, posixpath.dirname(part)))
        blips[0].set(R + 'embed', rid)
        content_bytes = archive.read('[Content_Types].xml'); content_tree = ooxml.parse_xml(content_bytes)
        if content_tree.getroot().tag != types + 'Types':
            raise ValueError('Invalid package content types')
        etree.SubElement(content_tree.getroot(), types + 'Override', PartName='/' + media, ContentType=content_type)
        return {rels_part: ooxml.serialize_xml(rel_tree, rel_bytes), '[Content_Types].xml': ooxml.serialize_xml(content_tree, content_bytes), media: image_data}

    return ooxml.edit_xml(source, output, select_part, edit, allow_new=True)
