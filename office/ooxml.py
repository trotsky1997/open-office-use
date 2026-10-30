"""Bounded, atomic edits to a single XML part of an Office package."""
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree


def replace_nodes(nodes, find, replacement, preserve_space=False):
    if not isinstance(find, str) or not find or len(find) > 4000:
        raise ValueError('Find text must contain 1 to 4,000 characters')
    if not isinstance(replacement, str) or len(replacement) > 4000:
        raise ValueError('Replacement must contain at most 4,000 characters')
    if any(ord(char) < 32 for char in find + replacement):
        raise ValueError('Control characters are not supported in text replacement')
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
            if preserve_space and (value.startswith(' ') or value.endswith(' ')):
                node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            inserted = True
        offset = next_offset


def edit_xml(source, output, select_part, edit):
    source = Path(source).resolve(strict=True); output = Path(output).absolute()
    if source.suffix.lower() not in ('.docx', '.pptx') or source.suffix.lower() != output.suffix.lower():
        raise ValueError('Input and output must use the same supported Office format')
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Document exceeds the 128 MiB size limit')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('Document exceeds package limits or contains duplicate parts')
            if any(name.startswith('_xmlsignatures/') for name in names):
                raise ValueError('Digitally signed documents are not supported by text replacement')
            part = select_part(source)
            document = archive.read(part)
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            tree = etree.parse(io.BytesIO(document), parser)
            if tree.docinfo.doctype:
                raise ValueError('Document XML contains an unsupported document type')
            edit(tree)
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
            with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-ooxml-') as tmp:
                candidate = Path(tmp) / ('document' + output.suffix.lower())
                with zipfile.ZipFile(candidate, 'w') as result:
                    result.comment = archive.comment
                    for entry in entries:
                        result.writestr(entry, changed if entry.filename == part else archive.read(entry))
                os.link(candidate, output)
    except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError) as exc:
        raise ValueError(f'Invalid Office document: {exc}') from exc
    return str(output)
