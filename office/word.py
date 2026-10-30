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


def replace_text(source, output, path, find, replacement):
    if not paragraph_path(path):
        raise ValueError('Target must be a body or table paragraph path such as /body/p[1]')
    if Path(source).suffix.lower() != '.docx' or Path(output).suffix.lower() != '.docx':
        raise ValueError('Text replacement requires DOCX input and output')

    def edit(tree):
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
        if any(child.tag not in (W + 'pPr', W + 'r') for child in paragraph):
            raise ValueError('Paragraph contains unsupported structures such as hyperlinks or annotations')
        nodes = []
        for run in paragraph.findall(W + 'r'):
            if any(child.tag not in (W + 'rPr', W + 't') for child in run):
                raise ValueError('Paragraph contains unsupported run content such as fields, tabs or images')
            nodes.extend(run.findall(W + 't'))
        ooxml.replace_nodes(nodes, find, replacement, preserve_space=True)

    return ooxml.edit_xml(source, output, lambda _: 'word/document.xml', edit)
