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


def replace_text(source, output, path, find, replacement):
    match = re.fullmatch(r'/body/p\[([1-9][0-9]{0,5})\]', path) if isinstance(path, str) else None
    if not match:
        raise ValueError('Target must be a direct body paragraph path such as /body/p[1]')
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
            paragraphs = body.findall(W + 'p'); index = int(match.group(1)) - 1
            if index >= len(paragraphs):
                raise ValueError('Paragraph does not exist')
            paragraph = paragraphs[index]
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
            declaration = document.lstrip().startswith(b'<?xml')
            header = document.lstrip().split(b'?>', 1)[0] if declaration else b''
            standalone = re.search(rb"\\bstandalone\\s*=\\s*(['\"])(yes|no)\\1", header)
            options = {'encoding': 'UTF-8', 'xml_declaration': declaration}
            if standalone:
                options['standalone'] = standalone.group(2) == b'yes'
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
