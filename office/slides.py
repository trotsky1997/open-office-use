"""Conservative text replacement in a PowerPoint slide paragraph."""
import re
from pathlib import Path

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE

import ooxml

P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
INDEX = r'[1-9][0-9]{0,5}'
SELECTOR = r'(?:' + INDEX + r'|@id=' + INDEX + r')'
PATH = re.compile(r'/slide\[(' + INDEX + r')\](?:/group\[' + SELECTOR + r'\]){0,8}(?:/shape\[' + SELECTOR + r'\]|/table\[' + SELECTOR + r'\]/tr\[' + INDEX + r'\]/tc\[' + INDEX + r'\])(?:/paragraph\[(' + INDEX + r')\])?\Z')
SEGMENT = re.compile(r'/(group|shape|table|tr|tc)\[([^]]+)\]')


def paragraph_path(path):
    return isinstance(path, str) and len(path) <= 512 and PATH.fullmatch(path) is not None


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


def replace_text(source, output, path, find, replacement):
    match = PATH.fullmatch(path) if paragraph_path(path) else None
    if not match:
        raise ValueError('Target must be a slide shape or table-cell paragraph path')
    if Path(source).suffix.lower() != '.pptx' or Path(output).suffix.lower() != '.pptx':
        raise ValueError('Text replacement requires PPTX input and output')
    slide_index = int(match.group(1)) - 1
    paragraph_index = int(match.group(2)) - 1 if match.group(2) else None

    def edit(tree, archive):
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
        if any(child.tag not in (A + 'pPr', A + 'r', A + 'endParaRPr') for child in paragraph):
            raise ValueError('Paragraph contains unsupported content such as fields or line breaks')
        nodes = []
        for run in paragraph.findall(A + 'r'):
            if any(child.tag not in (A + 'rPr', A + 't') for child in run):
                raise ValueError('Run contains unsupported content')
            if run.find('.//' + A + 'hlinkClick') is not None or run.find('.//' + A + 'hlinkMouseOver') is not None:
                raise ValueError('Paragraph contains a hyperlink')
            nodes.extend(run.findall(A + 't'))
        ooxml.replace_nodes(nodes, find, replacement)

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
