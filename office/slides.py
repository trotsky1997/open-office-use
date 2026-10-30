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
PATH = re.compile(r'/slide\[(' + INDEX + r')\](?:/group\[' + SELECTOR + r'\]){0,8}/shape\[' + SELECTOR + r'\](?:/paragraph\[(' + INDEX + r')\])?\Z')
SEGMENT = re.compile(r'/(group|shape)\[([^]]+)\]')


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
        raise ValueError('Target must be a slide shape or paragraph path')
    if Path(source).suffix.lower() != '.pptx' or Path(output).suffix.lower() != '.pptx':
        raise ValueError('Text replacement requires PPTX input and output')
    slide_index = int(match.group(1)) - 1
    paragraph_index = int(match.group(2)) - 1 if match.group(2) else None

    def edit(tree):
        if tree.getroot().tag != P + 'sld':
            raise ValueError('Slide XML has an invalid root')
        parent = tree.getroot().find(P + 'cSld/' + P + 'spTree')
        if parent is None:
            raise ValueError('Slide has no shape tree')
        for kind, selector in SEGMENT.findall(path):
            if parent.find(MC + 'AlternateContent') is not None:
                raise ValueError('Shape container contains unsupported alternate content')
            tag = 'grpSp' if kind == 'group' else 'sp'
            children = parent.findall(P + tag)
            if selector.startswith('@id='):
                requested = selector.partition('=')[2]
                nonvisual = 'nvGrpSpPr' if kind == 'group' else 'nvSpPr'
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
        text_body = parent.find(P + 'txBody')
        if text_body is None:
            raise ValueError('Shape has no editable text body')
        paragraphs = text_body.findall(A + 'p')
        if paragraph_index is None:
            if len(paragraphs) != 1:
                raise ValueError('Choose a paragraph in a shape with multiple paragraphs')
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
