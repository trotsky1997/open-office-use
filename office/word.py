"""Conservative, targeted text replacement in a saved Word document."""
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
W14_PARAGRAPH_ID = '{http://schemas.microsoft.com/office/word/2010/wordml}paraId'
INDEX = r'[1-9][0-9]{0,5}'
PATH = re.compile(r'/body(?:(?:/(?:tbl|table)\[' + INDEX + r'\]/(?:tr|row)\[' + INDEX + r'\]/(?:tc|cell)\[' + INDEX + r'\])){0,8}/p(?:\[' + INDEX + r'\]|\[@paraId=[0-9A-Fa-f]{8}\])\Z')
SEGMENT = re.compile(r'/(tbl|table|tr|row|tc|cell|p)\[([^]]+)\]')


def paragraph_path(path):
    return isinstance(path, str) and len(path) <= 512 and PATH.fullmatch(path) is not None


def replace_text(source, output, path, find, replacement):
    if not paragraph_path(path):
        raise ValueError('Target must be a body or table paragraph path such as /body/p[1]')
    if not isinstance(find, str) or not find or len(find) > 4000:
        raise ValueError('Find text must contain 1 to 4,000 characters')
    if not isinstance(replacement, str) or len(replacement) > 4000:
        raise ValueError('Replacement must contain at most 4,000 characters')
    if any(ord(char) < 32 for char in find + replacement):
        raise ValueError('Control characters are not supported in text replacement')
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Document exceeds the 128 MiB size limit')
    if source.suffix.lower() != '.docx' or output.suffix.lower() != '.docx':
        raise ValueError('Text replacement requires DOCX input and output')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Document exceeds package limits or contains duplicate parts')
            if any(name.startswith('_xmlsignatures/') for name in names):
                raise ValueError('Digitally signed documents are not supported by text replacement')
            document = archive.read('word/document.xml')
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            tree = etree.parse(io.BytesIO(document), parser)
            if tree.docinfo.doctype:
                raise ValueError('Document XML contains an unsupported document type')
            if tree.getroot().tag != W + 'document':
                raise ValueError('Document XML has an invalid root')
            body = tree.getroot().find(W + 'body')
            if body is None:
                raise ValueError('Document has no body')
            paragraph = body
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
            text = ''.join(node.text or '' for node in nodes)
            start = text.find(find)
            if start < 0 or text.find(find, start + 1) >= 0:
                raise ValueError('Find text must match exactly once in the paragraph')
            end = start + len(find); offset = 0; inserted = False
            for node in nodes:
                value = node.text or ''; next_offset = offset + len(value)
                if offset < end and next_offset > start:
                    left = max(0, start - offset); right = min(len(value), end - offset)
                    value = value[:left] + (replacement if not inserted else '') + value[right:]
                    node.text = value
                    if value.startswith(' ') or value.endswith(' '):
                        node.set(XML_SPACE, 'preserve')
                    inserted = True
                offset = next_offset
            prefix = document[:4096].decode(tree.docinfo.encoding or 'UTF-8', errors='ignore').lstrip('\ufeff \t\r\n')
            declaration = prefix.startswith('<?xml')
            header, separator, _ = prefix.partition('?>')
            if declaration and not separator:
                raise ValueError('Document XML declaration exceeds the supported limit')
            standalone = re.search(r"\bstandalone\s*=\s*(['\"])(yes|no)\1", header) if declaration else None
            options = {'encoding': 'UTF-8', 'xml_declaration': declaration}
            if standalone:
                options['standalone'] = standalone.group(2) == 'yes'
            changed = etree.tostring(tree, **options)
            with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-word-') as tmp:
                candidate = Path(tmp) / 'document.docx'
                with zipfile.ZipFile(candidate, 'w') as result:
                    result.comment = archive.comment
                    for entry in entries:
                        result.writestr(entry, changed if entry.filename == 'word/document.xml' else archive.read(entry))
                os.link(candidate, output)
    except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError) as exc:
        raise ValueError(f'Invalid Word document: {exc}') from exc
    return str(output)
