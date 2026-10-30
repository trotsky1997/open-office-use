"""Transplant validated grid values into the original XLSX package."""
import copy
import math
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from lxml import etree
from openpyxl.formula import Tokenizer
import cell_text
import grid_styles
import officecli_backend
import ooxml
import spreadsheet

X = grid_styles.X
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
SHARED = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'


CHAIN_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/calcChain'
CHAIN_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml'


META_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/sheetMetadata'
META_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheetMetadata+xml'
DYNAMIC_METADATA = b'''<metadata xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:xda="http://schemas.microsoft.com/office/spreadsheetml/2017/dynamicarray"><metadataTypes count="1"><metadataType name="XLDAPR" minSupportedVersion="120000" copy="1" pasteAll="1" pasteValues="1" merge="1" splitFirst="1" rowColShift="1" clearFormats="1" clearComments="1" assign="1" coerce="1" cellMeta="1"/></metadataTypes><futureMetadata name="XLDAPR" count="1"><bk><extLst><ext uri="{bdbb8cdc-fa1e-496e-a857-3c3f30c029c3}"><xda:dynamicArrayProperties fDynamic="1" fCollapsed="0"/></ext></extLst></bk></futureMetadata><cellMetadata count="1"><bk><rc t="1" v="0"/></bk></cellMetadata></metadata>'''


def dynamic_formula_matches(requested, candidate):
    if requested == candidate: return True
    try:
        before = Tokenizer('=' + requested).items; after = Tokenizer('=' + candidate).items
    except Exception as exc: raise ValueError('Unable to verify dynamic formula') from exc
    if len(before) != len(after): return False
    local = None; result_start = len(before)
    if before and before[0].type == 'FUNC' and before[0].value.upper() == 'LET(':
        depth = 0; separators = []; nested = False
        for index, token in enumerate(before):
            if token.subtype == 'OPEN':
                if index and token.type == 'FUNC' and token.value.upper() in ('LET(', 'LAMBDA('): nested = True
                depth += 1
            elif token.subtype == 'CLOSE': depth -= 1
            elif token.type == 'SEP' and token.subtype == 'ARG' and depth == 1: separators.append(index)
        if not nested and len(separators) == 2 and separators[0] == 2 and before[1].type == 'OPERAND' and before[1].subtype == 'RANGE':
            name = before[1].value
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', name) and not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', name):
                local = name; result_start = separators[1] + 1
    future = {'SEQUENCE', 'XLOOKUP', 'FILTER', 'SORT', 'SORTBY', 'UNIQUE', 'RANDARRAY', 'LET'}
    for index, (original, produced) in enumerate(zip(before, after)):
        if (original.type, original.subtype) != (produced.type, produced.subtype): return False
        value = produced.value
        if produced.type == 'FUNC' and produced.subtype == 'OPEN':
            match = re.fullmatch(r'_xlfn\.(?:_xlws\.)?([A-Za-z][A-Za-z0-9.]*)\(', value, re.IGNORECASE)
            if match and match.group(1).upper() in future: value = match.group(1) + '('
        elif produced.type == 'OPERAND' and produced.subtype == 'RANGE' and local and (index == 1 or index >= result_start):
            if value.lower() == ('_xlpm.' + local).lower(): value = value[6:]
        if value != original.value: return False
    return True


def metadata_part(archive):
    rels = ooxml.parse_xml(archive.read('xl/_rels/workbook.xml.rels')).getroot()
    manifest = ooxml.parse_xml(archive.read('[Content_Types].xml')).getroot()
    if rels.tag != grid_styles.REL + 'Relationships' or manifest.tag != CT + 'Types': raise ValueError('Invalid workbook metadata')
    relationships = [item for item in rels.findall(grid_styles.REL + 'Relationship') if item.get('Type', '').endswith('/sheetMetadata')]
    overrides = [item for item in manifest.findall(CT + 'Override') if item.get('ContentType', '').endswith('.sheetMetadata+xml')]
    if any(item.get('ContentType') == META_TYPE for item in manifest.findall(CT + 'Default')): raise ValueError('Unsupported default sheet metadata content type')
    if not relationships and not overrides: return None
    if len(relationships) != 1 or len(overrides) != 1 or relationships[0].get('Type') != META_REL or overrides[0].get('ContentType') != META_TYPE: raise ValueError('Ambiguous sheet metadata')
    rel = relationships[0]; target = rel.get('Target', '')
    if rel.get('TargetMode', 'Internal') != 'Internal' or not target or any(c in target for c in ('%', '?', '#', '\\', ':')): raise ValueError('Unsupported sheet metadata target')
    path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
    if not path.startswith('xl/') or path not in archive.namelist() or overrides[0].get('PartName') != '/' + path: raise ValueError('Invalid sheet metadata part')
    if len([item for item in manifest.findall(CT + 'Override') if item.get('PartName') == '/' + path]) != 1: raise ValueError('Ambiguous sheet metadata content type')
    if posixpath.join(posixpath.dirname(path), '_rels', posixpath.basename(path) + '.rels') in archive.namelist(): raise ValueError('Sheet metadata has relationships')
    root = ooxml.parse_xml(archive.read(path)).getroot()
    expected = ooxml.parse_xml(DYNAMIC_METADATA).getroot()
    if grid_styles.equivalent(root) != grid_styles.equivalent(expected): raise ValueError('Unsupported sheet metadata structure')
    return path


def remove_calculation_chain(archive, manifest):
    rel_path = 'xl/_rels/workbook.xml.rels'
    rel_raw = archive.read(rel_path); rel_tree = ooxml.parse_xml(rel_raw); rels = rel_tree.getroot()
    if rels.tag != grid_styles.REL + 'Relationships': raise ValueError('Invalid workbook relationships')
    chains = [item for item in rels.findall(grid_styles.REL + 'Relationship') if item.get('Type', '').endswith('/calcChain')]
    overrides = [item for item in manifest.getroot().findall(CT + 'Override') if item.get('ContentType', '').endswith('.calcChain+xml')]
    if not chains and not overrides: return {}, 'absent'
    if len(chains) != 1 or len(overrides) != 1 or chains[0].get('Type') != CHAIN_REL or overrides[0].get('ContentType') != CHAIN_TYPE:
        raise ValueError('Ambiguous calculation chain')
    chain = chains[0]; target = chain.get('Target', '')
    if chain.get('TargetMode', 'Internal') != 'Internal' or not target or any(c in target for c in ('%', '?', '#', '\\', ':')):
        raise ValueError('Unsupported calculation chain target')
    path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
    if not path.startswith('xl/') or path not in archive.namelist() or overrides[0].get('PartName') != '/' + path or path in ('xl/workbook.xml', 'xl/styles.xml'):
        raise ValueError('Invalid calculation chain part')
    if len([item for item in manifest.getroot().findall(CT + 'Override') if item.get('PartName') == '/' + path]) != 1:
        raise ValueError('Ambiguous calculation chain content type')
    own_rels = posixpath.join(posixpath.dirname(path), '_rels', posixpath.basename(path) + '.rels')
    if own_rels in archive.namelist(): raise ValueError('Calculation chain has relationships')
    root = ooxml.parse_xml(archive.read(path)).getroot()
    if root.tag != X + 'calcChain' or root.attrib or (root.text and root.text.strip()): raise ValueError('Unsupported calculation chain content')
    for cell in root:
        if cell.tag != X + 'c' or len(cell) or (cell.text and cell.text.strip()) or (cell.tail and cell.tail.strip()) or any(key not in ('r', 'i', 'l', 's', 'a') for key in cell.attrib) or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', cell.get('r', '')):
            raise ValueError('Unsupported calculation chain content')
    for name in archive.namelist():
        if not name.endswith('.rels'): continue
        if name == '_rels/.rels': base = ''
        elif '/_rels/' in name:
            parent, leaf = name.rsplit('/_rels/', 1); base = parent
            if not leaf.endswith('.rels') or '/' in leaf: raise ValueError('Invalid relationship part')
        elif name.startswith('_rels/') and '/' not in name[6:]: base = ''
        else: raise ValueError('Invalid relationship part')
        relationships = ooxml.parse_xml(archive.read(name)).getroot()
        if relationships.tag != grid_styles.REL + 'Relationships': raise ValueError('Invalid relationship part')
        for item in relationships.findall(grid_styles.REL + 'Relationship'):
            mode = item.get('TargetMode', 'Internal')
            if mode == 'External': continue
            if mode != 'Internal': raise ValueError('Invalid relationship target mode')
            uri = urlsplit(item.get('Target', ''))
            decoded = unquote(uri.path, errors='strict')
            if uri.scheme or uri.netloc or '%' in decoded or '\\' in decoded: raise ValueError('Unsupported relationship target')
            resolved = posixpath.normpath(decoded.lstrip('/') if decoded.startswith('/') else posixpath.join(base, decoded))
            if resolved == path and not (name == rel_path and item.get('Id') == chain.get('Id') and item.get('Type') == CHAIN_REL):
                raise ValueError('Calculation chain has additional references')
    rels.remove(chain); manifest.getroot().remove(overrides[0])
    return {rel_path: ooxml.serialize_xml(rel_tree, rel_raw), '[Content_Types].xml': ooxml.serialize_xml(manifest, archive.read('[Content_Types].xml')), path: None}, 'removed'


def apply(source, output, sheet, changes, operations):
    source = Path(source); output = Path(output); targets = {change['cell']: change['value'] for change in changes}
    literal = {change['cell'] for change in changes if change.get('type') == 'text'}
    with zipfile.ZipFile(source) as archive:
        if any(name.startswith('_xmlsignatures/') for name in archive.namelist()): raise ValueError('Digitally signed workbooks are not supported for grid edits')
        style_name = grid_styles.style_part(archive)
    with tempfile.TemporaryDirectory(prefix='office-grid-value-') as tmp:
        candidate = Path(tmp) / 'candidate.xlsx'; batch = officecli_backend.batch(operations, candidate, source)
        source_part = grid_styles.sheet_part(source, sheet)
        with zipfile.ZipFile(candidate) as archive:
            entries = archive.infolist(); names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                raise ValueError('OfficeCLI candidate exceeds package limits or contains duplicate parts')
            candidate_part = grid_styles.sheet_part(candidate, sheet)
            if grid_styles.style_part(archive) != style_name: raise ValueError('OfficeCLI changed styles relationship')
            candidate_styles = archive.read(style_name); candidate_tree = ooxml.parse_xml(archive.read(candidate_part)); shared = None
            root = candidate_tree.getroot(); data = root.findall(X + 'sheetData')
            if root.tag != X + 'worksheet' or len(data) != 1 or len(list(root.iter(X + 'sheetData'))) != 1: raise ValueError('Invalid candidate worksheet')
            cells = {}
            for row in data[0].findall(X + 'row'):
                for cell in row.findall(X + 'c'):
                    address = cell.get('r')
                    if address in targets:
                        if address in cells or row.get('r') != re.fullmatch(r'[A-Z]{1,3}([1-9][0-9]{0,6})', address).group(1): raise ValueError('Duplicate or invalid candidate cell')
                        cells[address] = cell
            values = {}; dynamic = set(); dynamic_metadata = None
            for address, requested in targets.items():
                cell = cells.get(address)
                if cell is None:
                    if requested: raise ValueError('OfficeCLI omitted a target cell')
                    values[address] = (None, None, None); continue
                if any(key not in ('r', 's', 't', 'cm') for key in cell.attrib): raise ValueError('Candidate cell has unsupported metadata')
                is_dynamic = cell.get('cm') is not None
                if is_dynamic and (address in literal or not requested.startswith('=') or cell.get('cm') != '1'): raise ValueError('Unsupported candidate cell metadata')
                style = cell.get('s', '0'); kind = cell.get('t'); children = list(cell)
                if address not in literal and requested.startswith('='):
                    formulas = cell.findall(X + 'f')
                    if len(formulas) != 1 or len(formulas[0]) or not formulas[0].text or any(child.tag not in (X + 'f', X + 'v') for child in children): raise ValueError('Candidate formula is unsupported')
                    if is_dynamic:
                        if dict(formulas[0].attrib) != {'t': 'array', 'ref': address} or kind not in (None, 'n', 'e', 'str', 'b'): raise ValueError('Unsupported dynamic formula')
                        if not dynamic_formula_matches(requested[1:], formulas[0].text): raise ValueError('Candidate formula differs from requested expression')
                        metadata_path = metadata_part(archive)
                        if metadata_path is None: raise ValueError('Dynamic formula metadata is missing')
                        dynamic_metadata = archive.read(metadata_path); dynamic.add(address)
                    elif formulas[0].attrib or formulas[0].text != requested[1:]: raise ValueError('Candidate formula differs from requested expression or has unsupported metadata')
                    values[address] = (style, None, [copy.deepcopy(formulas[0])]); continue
                if address not in literal and requested == '':
                    if any(child.tag not in (X + 'v',) for child in children) or any((child.text or '') for child in children): raise ValueError('Candidate did not clear target cell')
                    values[address] = (style, None, []); continue
                if kind in ('str', 's', 'inlineStr'):
                    if kind == 'str':
                        if len(children) != 1 or children[0].tag != X + 'v' or len(children[0]): raise ValueError('Unsupported candidate text')
                        text = children[0].text or ''
                    elif kind == 's':
                        if len(children) != 1 or children[0].tag != X + 'v' or not re.fullmatch(r'[0-9]{1,10}', children[0].text or ''): raise ValueError('Unsupported candidate shared string')
                        if shared is None: shared = spreadsheet.search_shared_strings(archive)
                        index = int(children[0].text)
                        if shared is None or index >= len(shared) or not shared[index][1]: raise ValueError('Candidate shared string is unverified')
                        text = shared[index][0]
                    else:
                        if len(children) != 1 or children[0].tag != X + 'is' or len(children[0]) != 1 or children[0][0].tag != X + 't' or len(children[0][0]): raise ValueError('Unsupported candidate inline text')
                        text = children[0][0].text or ''
                    if text != ('office-use-literal-text' if address in literal else requested) or cell_text.ESCAPED.search(text): raise ValueError('Candidate text differs from requested value')
                    if address in literal: text = requested
                    content = etree.Element(X + 'is'); node = etree.SubElement(content, X + 't'); node.text = text
                    if text[0].isspace() or text[-1].isspace(): node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                    values[address] = (style, 'inlineStr', [content]); continue
                if address in literal: raise ValueError('Candidate literal text is not text')
                if kind not in (None, 'n', 'b', 'e', 'd') or len(children) != 1 or children[0].tag != X + 'v' or len(children[0]): raise ValueError('Unsupported candidate cell value')
                text = children[0].text or ''
                if kind in (None, 'n'):
                    try:
                        if not math.isfinite(float(text)): raise ValueError
                    except ValueError: raise ValueError('Invalid candidate numeric value') from None
                elif kind == 'b' and text not in ('0', '1'): raise ValueError('Invalid candidate boolean')
                elif kind == 'e' and text not in ('#NULL!', '#DIV/0!', '#VALUE!', '#REF!', '#NAME?', '#NUM!', '#N/A'): raise ValueError('Invalid candidate error value')
                values[address] = (style, kind, [copy.deepcopy(children[0])])
        chain_status = 'unchanged'
        def edit(tree, archive):
            nonlocal chain_status
            root = tree.getroot()
            if root.tag != X + 'worksheet': raise ValueError('Invalid worksheet')
            original_styles = archive.read(style_name); merged, style_count = grid_styles.merge_styles(original_styles, candidate_styles)
            original_xfs = ooxml.parse_xml(original_styles).getroot().find(X + 'cellXfs')
            merged_xfs = ooxml.parse_xml(merged).getroot().find(X + 'cellXfs')
            for style, _, _ in values.values():
                if style is not None and (not re.fullmatch(r'[0-9]{1,10}', style) or int(style) >= style_count): raise ValueError('Invalid target style index')
            existing = {cell.get('r') for data in root.findall(X + 'sheetData') for row in data.findall(X + 'row') for cell in row.findall(X + 'c')}
            addresses = [address for address, value in targets.items() if value != '' or address in existing]
            cells = grid_styles.prepare_cells(root, addresses); cell_text.request_recalculation(root)
            formula_changed = False; string_count_uncertain = False
            for address, cell in cells.items():
                if any(key not in ('r', 's', 't') for key in cell.attrib): raise ValueError('Target cell contains unsupported metadata')
                if any(child.tag not in (X + 'f', X + 'v', X + 'is') for child in cell): raise ValueError('Target cell contains unsupported content')
                if len(cell.findall(X + 'f')) > 1 or len(cell.findall(X + 'v')) > 1 or len(cell.findall(X + 'is')) > 1: raise ValueError('Target cell content is ambiguous')
                formula = cell.find(X + 'f')
                if formula is not None and any(key != 't' or value != 'normal' for key, value in formula.attrib.items()): raise ValueError('Target formula has unsupported metadata')
                inline = cell.find(X + 'is')
                if inline is not None and any(node.tag in (X + 'rPh', X + 'phoneticPr') for node in inline.iter()): raise ValueError('Target text contains phonetic metadata')
                style, kind, children = values[address]
                new_formula = next((child.text or '' for child in children or () if child.tag == X + 'f'), None)
                old_formula = (formula.text or '') if formula is not None else None
                old_is_text = formula is None and cell.get('t') in ('s', 'str', 'inlineStr')
                new_is_text = new_formula is None and kind == 'inlineStr'
                if old_formula is not None or new_formula is not None or old_is_text != new_is_text: string_count_uncertain = True
                if old_formula != new_formula: formula_changed = True
                old_style = cell.get('s', '0')
                if not re.fullmatch(r'[0-9]{1,10}', old_style) or original_xfs is None or int(old_style) >= len(original_xfs): raise ValueError('Invalid source style index')
                if style is not None and int(style) != int(old_style):
                    before_xf = copy.deepcopy(original_xfs[int(old_style)]); after_xf = copy.deepcopy(merged_xfs[int(style)])
                    old_format = before_xf.get('numFmtId', '0'); new_format = after_xf.get('numFmtId', '0')
                    if old_format != new_format and old_format != '0': raise ValueError('Candidate changed an existing number format')
                    for xf in (before_xf, after_xf):
                        xf.attrib.pop('numFmtId', None); xf.attrib.pop('applyNumberFormat', None)
                        for key in ('xfId', 'pivotButton', 'quotePrefix'):
                            if xf.get(key) in ('0', 'false'): xf.attrib.pop(key)
                    if grid_styles.equivalent(before_xf) != grid_styles.equivalent(after_xf): raise ValueError('Candidate changed unrelated cell formatting')
                if style is not None and int(style) != int(old_style): cell.set('s', style)
                if address in dynamic: cell.set('cm', '1')
                if kind is None: cell.attrib.pop('t', None)
                else: cell.set('t', kind)
                for child in list(cell): cell.remove(child)
                for child in children or (): cell.append(child)
            additional = {}
            if grid_styles.equivalent(ooxml.parse_xml(original_styles).getroot()) != grid_styles.equivalent(ooxml.parse_xml(merged).getroot()): additional[style_name] = merged
            manifest_tree = ooxml.parse_xml(archive.read('[Content_Types].xml')); manifest = manifest_tree.getroot()
            if manifest.tag != CT + 'Types': raise ValueError('Invalid content types')
            if formula_changed:
                chain_changes, chain_status = remove_calculation_chain(archive, manifest_tree)
                if source_part in chain_changes or style_name in chain_changes: raise ValueError('Calculation chain conflicts with workbook parts')
                additional.update(chain_changes)
            if dynamic:
                existing_metadata = metadata_part(archive)
                if existing_metadata is None:
                    path = 'xl/office-use-metadata.xml'
                    if path in archive.namelist() or any(item.get('PartName') == '/' + path for item in manifest.findall(CT + 'Override')): raise ValueError('Sheet metadata destination already exists')
                    rel_path = 'xl/_rels/workbook.xml.rels'; rel_raw = additional.get(rel_path, archive.read(rel_path)); rel_tree = ooxml.parse_xml(rel_raw); rels = rel_tree.getroot()
                    ids = {item.get('Id') for item in rels.findall(grid_styles.REL + 'Relationship')}; number = 1
                    while f'rId{number}' in ids: number += 1
                    etree.SubElement(rels, grid_styles.REL + 'Relationship', Id=f'rId{number}', Type=META_REL, Target='/'+path)
                    etree.SubElement(manifest, CT + 'Override', PartName='/'+path, ContentType=META_TYPE)
                    additional[rel_path] = ooxml.serialize_xml(rel_tree, rel_raw)
                    additional['[Content_Types].xml'] = ooxml.serialize_xml(manifest_tree, archive.read('[Content_Types].xml'))
                    additional[path] = dynamic_metadata
            shared_parts = [item.get('PartName', '').lstrip('/') for item in manifest.findall(CT + 'Override') if item.get('ContentType') == SHARED]
            if len(shared_parts) > 1 or (shared_parts and (not shared_parts[0] or shared_parts[0] not in archive.namelist())): raise ValueError('Ambiguous shared string table')
            if shared_parts:
                path = shared_parts[0]
                if path in (style_name, source_part): raise ValueError('Shared string part conflicts with a worksheet or stylesheet')
                raw = archive.read(path); shared_tree = ooxml.parse_xml(raw); table = shared_tree.getroot()
                if table.tag != X + 'sst': raise ValueError('Invalid shared string table')
                if string_count_uncertain and (table.get('count') is not None or table.get('uniqueCount') is not None):
                    table.attrib.pop('count', None); table.attrib.pop('uniqueCount', None)
                    additional[path] = ooxml.serialize_xml(shared_tree, raw)
            return additional
        result = copy.deepcopy(batch['result'])
        if not isinstance(result, dict) or not isinstance(result.get('results'), list): raise ValueError('Invalid OfficeCLI batch result')
        for item in result['results']:
            if not isinstance(item, dict): raise ValueError('Invalid OfficeCLI batch result')
            index = item.get('index')
            if isinstance(index, int) and 0 <= index < len(changes) and changes[index]['cell'] in literal and isinstance(item.get('output'), str):
                item['output'] = item['output'].replace('office-use-literal-text', '[literal text]')
        ooxml.edit_xml(source, output, lambda _: source_part, edit, allow_new=True, allow_remove=True)
        return {'output': str(output), 'result': result, 'formula_cache_effect': 'may_be_stale', 'recalculation_requested': True, 'calculation_chain': chain_status, 'dynamic_formula_cells': sorted(dynamic)}
