"""Small local file-oriented office harness."""
import argparse
from copy import copy
from datetime import date, datetime
import importlib
import importlib.metadata
import io
import math
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.shared import Inches as DocxInches, Pt as DocxPt, Twips as DocxTwips, RGBColor as DocxRGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, ScatterChart, Series, Reference
from openpyxl.chart.axis import DateAxis, ChartLines
from openpyxl.chart.label import DataLabelList
from openpyxl.drawing.image import Image as WorkbookImage
from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing, _check_anchor
from openpyxl.chart.data_source import AxDataSource, StrRef, StrData, StrVal, NumData, NumVal
from openpyxl.styles import PatternFill
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.utils.cell import column_index_from_string, get_column_letter, range_boundaries, quote_sheetname
from openpyxl.utils.datetime import to_excel
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement as PptxElement
from pptx.util import Inches, Pt
from PIL import Image

import layout
import slide_text_check
import slide_charts
import slides
import chart_cache
import notes
import visual
import word
import officecli_backend
import spreadsheet
import review
import review_bundle
import session
import selection_text
import selection_candidates
import slides
import snapshot as snapshots


def doctor():
    """Probe local dependencies without modifying documents or configuration."""
    tools = {}
    for name, candidates, flag in (
        ('officecli', ('officecli',), '--version'),
        ('libreoffice', ('soffice', 'libreoffice'), '--version'),
        ('pdftoppm', ('pdftoppm',), '-v'),
        ('pdfinfo', ('pdfinfo',), '-v'),
        ('pdftotext', ('pdftotext',), '-v'),
    ):
        executable = next((path for candidate in candidates if (path := shutil.which(candidate))), None)
        if not executable:
            tools[name] = {'status': 'missing', 'path': None, 'version': None}
            continue
        try:
            result = subprocess.run([executable, flag], capture_output=True, text=True, timeout=5, check=False)
            output = (result.stdout or result.stderr).strip()
            tools[name] = {'status': 'available' if result.returncode == 0 else 'error', 'path': executable,
                           'version': output.splitlines()[0][:200] if output else None}
        except (OSError, subprocess.SubprocessError) as exc:
            tools[name] = {'status': 'error', 'path': executable, 'version': None, 'error': str(exc)[:200]}
    try:
        importlib.import_module('mcp.server.fastmcp')
        try: version = importlib.metadata.version('mcp')
        except importlib.metadata.PackageNotFoundError: version = None
        tools['mcp'] = {'status': 'available', 'version': version}
    except ImportError as exc:
        tools['mcp'] = {'status': 'missing' if exc.name == 'mcp' else 'error', 'version': None, 'error': str(exc)[:200]}
    available = lambda *names: all(tools[name]['status'] == 'available' for name in names)
    return {'dependencies': tools, 'capabilities': {
        'structured_authoring': available('officecli'), 'pdf_rendering': available('libreoffice'),
        'page_images': available('libreoffice', 'pdftoppm', 'pdfinfo'),
        'selected_text': available('libreoffice', 'pdftotext'), 'mcp_server': available('mcp')},
        'notes': ['Version probes check startup only; test actual document rendering and fidelity separately.']}


def kind(path):
    suffix = Path(path).suffix.lower()
    if suffix not in ('.docx', '.xlsx', '.pptx'):
        raise ValueError('Supported formats: .docx, .xlsx, .pptx')
    return suffix


def inspect(path):
    suffix = kind(path)
    if suffix == '.docx':
        doc = Document(path)
        return {'type': 'docx', 'paragraphs': [p.text for p in doc.paragraphs],
                'tables': [[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables]}
    if suffix == '.xlsx':
        return spreadsheet.inspect_workbook(path)
    prs = Presentation(path)
    return {'type': 'pptx', 'slides': [[{'shape': i, 'text': shape.text} for i, shape in enumerate(slide.shapes) if shape.has_text_frame] for slide in prs.slides]}


def configure_word_page(doc, setup):
    """Configure the page and running text of a newly created document."""
    if not isinstance(setup, dict) or set(setup) - {'size', 'orientation', 'margins', 'header', 'footer'}: raise ValueError('Invalid Word page setup')
    section = doc.sections[0]
    size = setup.get('size')
    if size is not None:
        if not isinstance(size, str) or size not in ('a4', 'letter'): raise ValueError('Word page size must be a4 or letter')
        width, height = {'a4': (8.2677165354, 11.6929133858), 'letter': (8.5, 11)}[size]
        section.page_width, section.page_height = DocxInches(width), DocxInches(height)
    orientation = setup.get('orientation', 'portrait')
    if not isinstance(orientation, str) or orientation not in ('portrait', 'landscape'): raise ValueError('Invalid Word page orientation')
    section.orientation = WD_ORIENT.PORTRAIT if orientation == 'portrait' else WD_ORIENT.LANDSCAPE
    if (section.page_width > section.page_height) != (orientation == 'landscape'):
        section.page_width, section.page_height = section.page_height, section.page_width
    margins = setup.get('margins', {})
    if not isinstance(margins, dict) or set(margins) - {'top', 'bottom', 'left', 'right'}: raise ValueError('Invalid Word page margins')
    for name, value in margins.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 5: raise ValueError('Word page margins must be 0 to 5 inches')
        setattr(section, name + '_margin', DocxInches(value))
    if section.page_width - section.left_margin - section.right_margin < DocxInches(0.5) or section.page_height - section.top_margin - section.bottom_margin < DocxInches(0.5):
        raise ValueError('Word page margins leave insufficient content area')
    for name in ('header', 'footer'):
        if name not in setup: continue
        value = setup[name]
        allowed = {'text', 'align'} | ({'page_number'} if name == 'footer' else set())
        if not isinstance(value, dict) or set(value) - allowed: raise ValueError(f'Invalid Word {name}')
        text = value.get('text', ''); alignment = value.get('align', 'right' if name == 'footer' else 'left')
        if not isinstance(text, str) or len(text) > 1000 or any(ord(char) < 32 for char in text): raise ValueError(f'Invalid Word {name} text')
        alignments = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER, 'right': WD_ALIGN_PARAGRAPH.RIGHT}
        if not isinstance(alignment, str) or alignment not in alignments: raise ValueError(f'Invalid Word {name} alignment')
        page_number = value.get('page_number', False)
        if not isinstance(page_number, bool): raise ValueError('page_number must be a boolean')
        paragraph = getattr(section, name).paragraphs[0]; paragraph.alignment = alignments[alignment]
        if text: paragraph.add_run(text)
        if page_number:
            if text: paragraph.add_run(' ')
            field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), ' PAGE ')
            run = OxmlElement('w:r'); text_node = OxmlElement('w:t'); text_node.text = '1'; run.append(text_node); field.append(run); paragraph._p.append(field)


def append_word_blocks(doc, blocks):
    """Append ordered semantic Word content from a bounded JSON list."""
    if not isinstance(blocks, list) or len(blocks) > 200:
        raise ValueError('Word blocks must be a list of at most 200 items')
    if len(json.dumps(blocks, ensure_ascii=False)) > 2000000:
        raise ValueError('Word blocks exceed the 2,000,000-character limit')
    def validate_runs(runs):
        if not isinstance(runs, list) or not 1 <= len(runs) <= 200: raise ValueError('Word runs must contain 1 to 200 items')
        for run in runs:
            if not isinstance(run, dict) or set(run) - {'text', 'bold', 'italic', 'underline', 'url', 'font', 'font_size', 'color'} or not isinstance(run.get('text'), str) or len(run['text']) > 10000 or any(key in run and not isinstance(run[key], bool) for key in ('bold', 'italic', 'underline')):
                raise ValueError('Each run requires text and optional boolean bold, italic or underline')
            if 'font' in run and (not isinstance(run['font'], str) or not 1 <= len(run['font']) <= 100 or not run['font'].strip() or any(ord(char) < 32 for char in run['font'])): raise ValueError('Font must be a name of at most 100 characters')
            if 'font_size' in run and (isinstance(run['font_size'], bool) or not isinstance(run['font_size'], (int, float)) or not math.isfinite(run['font_size']) or not 1 <= run['font_size'] <= 400 or run['font_size'] * 2 % 1): raise ValueError('Word font size must be 1 to 400 points in half-point increments')
            if 'color' in run and (not isinstance(run['color'], str) or not re.fullmatch(r'[0-9a-fA-F]{6}', run['color'])): raise ValueError('Word color must be six-digit RGB')
            if 'url' in run:
                url = run['url']
                if not isinstance(url, str) or len(url) > 2048 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url): raise ValueError('Invalid hyperlink URL')
                try: parsed = urlsplit(url)
                except ValueError: raise ValueError('Invalid hyperlink URL') from None
                if parsed.scheme.lower() not in ('http', 'https', 'mailto') or (parsed.scheme.lower() in ('http', 'https') and not parsed.hostname) or (parsed.scheme.lower() == 'mailto' and not parsed.path): raise ValueError('Hyperlink must be an HTTP, HTTPS or mailto URL')
    def add_runs(paragraph, runs, defaults=None):
        defaults = defaults or {}
        for run in runs:
            target = paragraph.add_run(run['text'])
            if defaults.get('bold'): target.bold = True
            if defaults.get('color'): target.font.color.rgb = DocxRGBColor.from_string(defaults['color'].upper())
            if defaults.get('font_size'): target.font.size = DocxPt(defaults['font_size'])
            if defaults.get('font'):
                target.font.name = defaults['font']; fonts = target._r.get_or_add_rPr().rFonts
                fonts.set(qn('w:eastAsia'), defaults['font']); fonts.set(qn('w:cs'), defaults['font'])
            if 'url' in run:
                target.font.color.rgb = DocxRGBColor.from_string('0563C1'); target.underline = True
            for name in ('bold', 'italic', 'underline'):
                if name in run: setattr(target, name, run[name])
            if 'font' in run:
                target.font.name = run['font']
                fonts = target._r.get_or_add_rPr().rFonts
                fonts.set(qn('w:eastAsia'), run['font']); fonts.set(qn('w:cs'), run['font'])
            if 'font_size' in run: target.font.size = DocxPt(run['font_size'])
            if 'color' in run: target.font.color.rgb = DocxRGBColor.from_string(run['color'].upper())
            if 'url' in run:
                link = OxmlElement('w:hyperlink'); link.set(qn('r:id'), doc.part.relate_to(run['url'], RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
                link.append(target._r); paragraph._p.append(link)
    image_bytes = 0
    for block in blocks:
        if not isinstance(block, dict): raise ValueError('Each Word block must be an object')
        kind = block.get('type')
        if kind == 'table_of_contents':
            if set(block) - {'type', 'max_level'}: raise ValueError('Unsupported table of contents property')
            level = block.get('max_level', 3)
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9: raise ValueError('Table of contents max_level must be 1 to 9')
            headings = []
            for item in blocks:
                if not isinstance(item, dict) or item.get('type') != 'heading': continue
                heading_level = item.get('level', 1)
                if isinstance(heading_level, bool) or not isinstance(heading_level, int) or not 1 <= heading_level <= 9: raise ValueError('Heading level must be 1 to 9')
                if ('text' in item) == ('runs' in item): raise ValueError('Provide text or runs for each Word text block')
                runs = [{'text': item['text']}] if 'text' in item else item['runs']
                validate_runs(runs)
                if heading_level <= level: headings.append((heading_level, ''.join(run['text'] for run in runs)))
            if not headings: raise ValueError('Table of contents requires a heading within its level range')
            paragraph = doc.add_paragraph()
            begin = OxmlElement('w:fldChar'); begin.set(qn('w:fldCharType'), 'begin'); begin.set(qn('w:dirty'), 'true'); paragraph.add_run()._r.append(begin)
            instruction = OxmlElement('w:instrText'); instruction.set(qn('xml:space'), 'preserve'); instruction.text = f' TOC \\o "1-{level}" \\h \\z \\u '; paragraph.add_run()._r.append(instruction)
            separator = OxmlElement('w:fldChar'); separator.set(qn('w:fldCharType'), 'separate'); paragraph.add_run()._r.append(separator)
            for index, (heading_level, heading) in enumerate(headings):
                if index: paragraph.add_run().add_break()
                paragraph.add_run('  ' * (heading_level - 1) + heading)
            end = OxmlElement('w:fldChar'); end.set(qn('w:fldCharType'), 'end'); paragraph.add_run()._r.append(end)
            settings = doc.settings._element; update = settings.find(qn('w:updateFields'))
            if update is None:
                update = OxmlElement('w:updateFields')
                settings.insert_element_before(update, 'w:hdrShapeDefaults', 'w:footnotePr', 'w:endnotePr', 'w:compat', 'w:docVars', 'w:rsids', 'm:mathPr', 'w:attachedSchema', 'w:themeFontLang', 'w:clrSchemeMapping', 'w:doNotIncludeSubdocsInStats', 'w:doNotAutoCompressPictures', 'w:forceUpgrade', 'w:captions', 'w:readModeInkLockDown', 'w:smartTagType', 'sl:schemaLibrary', 'w:shapeDefaults', 'w:doNotEmbedSmartTags', 'w:decimalSymbol', 'w:listSeparator')
            update.set(qn('w:val'), 'true')
        elif kind == 'table':
            if set(block) - {'type', 'rows', 'header', 'style', 'column_weights', 'header_fill', 'header_color', 'font', 'font_size'}: raise ValueError('Unsupported Word table property')
            rows = block.get('rows'); header = block.get('header', False); style = block.get('style')
            if not isinstance(rows, list) or not 1 <= len(rows) <= 100 or not all(isinstance(row, list) for row in rows): raise ValueError('A table requires 1 to 100 rows')
            width = len(rows[0])
            if not 1 <= width <= 20 or len(rows) * width > 2000 or any(len(row) != width for row in rows): raise ValueError('A table requires a rectangular grid of at most 2,000 cells and 20 columns')
            for row in rows:
                for value in row:
                    if isinstance(value, str):
                        if len(value) > 10000: raise ValueError('Table text exceeds 10,000 characters')
                        continue
                    if not isinstance(value, dict) or set(value) != {'paragraphs'} or not isinstance(value['paragraphs'], list) or not 1 <= len(value['paragraphs']) <= 20: raise ValueError('Table cells require text or 1 to 20 paragraphs')
                    for para in value['paragraphs']:
                        if not isinstance(para, dict) or set(para) - {'text','runs','align'} or ('text' in para) == ('runs' in para): raise ValueError('Table paragraphs require text or runs')
                        if 'align' in para and para['align'] not in ('left','center','right','justify'): raise ValueError('Invalid table paragraph alignment')
                        validate_runs([{'text':para['text']}] if 'text' in para else para['runs'])
            if not isinstance(header, bool): raise ValueError('Table header must be a boolean')
            if not header and ('header_fill' in block or 'header_color' in block): raise ValueError('Header colors require a header row')
            for key in ('header_fill', 'header_color'):
                if key in block and (not isinstance(block[key], str) or not re.fullmatch(r'[0-9a-fA-F]{6}', block[key])): raise ValueError('Word table colors must be six-digit RGB')
            if 'font' in block and (not isinstance(block['font'], str) or not 1 <= len(block['font']) <= 100 or not block['font'].strip() or any(ord(char) < 32 for char in block['font'])): raise ValueError('Font must be a name of at most 100 characters')
            if 'font_size' in block and (isinstance(block['font_size'], bool) or not isinstance(block['font_size'], (int, float)) or not math.isfinite(block['font_size']) or not 1 <= block['font_size'] <= 400 or block['font_size'] * 2 % 1): raise ValueError('Word font size must be 1 to 400 points in half-point increments')
            weights = block.get('column_weights')
            if weights is not None:
                if not isinstance(weights, list) or len(weights) != width or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.01 <= value <= 1000 for value in weights): raise ValueError('Provide one positive column weight per column')
                section = doc.sections[-1]
                if section.page_width is None or section.left_margin is None or section.right_margin is None: raise ValueError('Word page width and margins are required for column weights')
                total_twips = round((section.page_width - section.left_margin - section.right_margin) / 635)
                total_weight = sum(weights); ends = [round(total_twips * sum(weights[:index + 1]) / total_weight) for index in range(width)]
                starts = [0] + ends[:-1]; widths = [end - start for start, end in zip(starts, ends)]
                if any(value < 1 for value in widths): raise ValueError('Column weights produce an invalid width')
            if style is not None:
                if not isinstance(style, str): raise ValueError('Table style must be a name')
                try: selected = doc.styles[style]
                except KeyError: raise ValueError(f'Word table style not found: {style}') from None
                if selected.type != WD_STYLE_TYPE.TABLE: raise ValueError('The selected style is not a table style')
            table = doc.add_table(rows=len(rows), cols=width)
            if style is not None: table.style = style
            if weights is not None:
                table.autofit = False
                for column, twips in zip(table.columns, widths): column.width = DocxTwips(twips)
            cells = table._cells
            for row_index, values in enumerate(rows):
                for column_index, value in enumerate(values):
                    cell = cells[row_index * width + column_index]
                    paragraphs = [{'text':value}] if isinstance(value, str) else value['paragraphs']
                    for para_index, para in enumerate(paragraphs):
                        paragraph = cell.paragraphs[0] if para_index == 0 else cell.add_paragraph()
                        if 'align' in para: paragraph.alignment = {'left':WD_ALIGN_PARAGRAPH.LEFT,'center':WD_ALIGN_PARAGRAPH.CENTER,'right':WD_ALIGN_PARAGRAPH.RIGHT,'justify':WD_ALIGN_PARAGRAPH.JUSTIFY}[para['align']]
                        runs = [{'text':para['text']}] if 'text' in para else para['runs']
                        defaults = {'bold':header and row_index == 0, 'color':block.get('header_color') if header and row_index == 0 else None, 'font':block.get('font'), 'font_size':block.get('font_size')}
                        add_runs(paragraph, runs, defaults)
                    if weights is not None: cell.width = DocxTwips(widths[column_index])
                    is_header = header and row_index == 0
                    if is_header and 'header_fill' in block:
                        shading = OxmlElement('w:shd'); shading.set(qn('w:val'), 'clear'); shading.set(qn('w:fill'), block['header_fill'].upper()); cell._tc.get_or_add_tcPr().append(shading)
            if header:
                properties = table.rows[0]._tr.get_or_add_trPr()
                marker = OxmlElement('w:tblHeader'); properties.append(marker)
        elif kind == 'image':
            if set(block) - {'type', 'path', 'width', 'description', 'align'}: raise ValueError('Unsupported Word image property')
            path, width = block.get('path'), block.get('width')
            description, align = block.get('description', ''), block.get('align', 'left')
            if not isinstance(path, str) or not isinstance(description, str) or len(description) > 1000: raise ValueError('Image requires a local path and optional short description')
            if isinstance(width, bool) or not isinstance(width, (int, float)) or not 0.1 <= width <= 22 or not math.isfinite(width): raise ValueError('Image width must be 0.1 to 22 inches')
            alignments = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER, 'right': WD_ALIGN_PARAGRAPH.RIGHT}
            if not isinstance(align, str) or align not in alignments: raise ValueError('Image alignment must be left, center or right')
            if Path(path).stat().st_size > 20 * 1024 * 1024: raise ValueError('Image exceeds 20 MiB')
            with tempfile.TemporaryDirectory(prefix='office-word-image-') as directory:
                snapshot, _ = snapshots.copy(path, directory); data = snapshot.read_bytes()
            image_bytes += len(data)
            if len(data) > 20 * 1024 * 1024 or image_bytes > 128 * 1024 * 1024: raise ValueError('Image size exceeds per-image or document limits')
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG') or image.width * image.height > 40000000: raise ValueError('Image must be PNG or JPEG with at most 40 million pixels')
                height = width * image.height / image.width
                if not 0.01 <= height <= 22: raise ValueError('Image aspect ratio produces an unsupported height')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.getexif().get(274, 1) != 1: raise ValueError('Normalize image orientation before inserting it')
            paragraph = doc.add_paragraph(); paragraph.alignment = alignments[align]
            picture = paragraph.add_run().add_picture(io.BytesIO(data), width=DocxInches(width), height=DocxInches(height))
            picture._inline.docPr.set('descr', description)
        elif kind == 'page_break':
            if set(block) != {'type'}: raise ValueError('A page-break block has no other properties')
            doc.add_page_break()
        elif kind in ('paragraph', 'heading', 'bullet', 'numbered'):
            allowed = {'type', 'text', 'runs', 'align', 'space_before', 'space_after', 'line_spacing', 'keep_with_next', 'keep_together', 'page_break_before'} | ({'level'} if kind == 'heading' else set())
            if set(block) - allowed or ('text' in block) == ('runs' in block): raise ValueError('Provide text or runs for each Word text block')
            level = block.get('level', 1)
            if kind == 'heading' and (isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9): raise ValueError('Heading level must be 1 to 9')
            alignments = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER, 'right': WD_ALIGN_PARAGRAPH.RIGHT, 'justify': WD_ALIGN_PARAGRAPH.JUSTIFY}
            if 'align' in block and (not isinstance(block['align'], str) or block['align'] not in alignments): raise ValueError('Invalid Word paragraph alignment')
            for key, minimum, maximum in (('space_before', 0, 400), ('space_after', 0, 400), ('line_spacing', 0.5, 4)):
                if key in block:
                    value = block[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum: raise ValueError(f'Invalid Word paragraph {key}')
            for key in ('keep_with_next', 'keep_together', 'page_break_before'):
                if key in block and not isinstance(block[key], bool): raise ValueError(f'Word paragraph {key} must be a boolean')
            runs = [{'text': block['text']}] if 'text' in block else block['runs']
            validate_runs(runs)
            if kind == 'heading': paragraph = doc.add_heading(level=level)
            else: paragraph = doc.add_paragraph(style={'bullet': 'List Bullet', 'numbered': 'List Number'}.get(kind))
            if 'align' in block: paragraph.alignment = alignments[block['align']]
            for key in ('space_before', 'space_after'):
                if key in block: setattr(paragraph.paragraph_format, key, DocxPt(block[key]))
            if 'line_spacing' in block: paragraph.paragraph_format.line_spacing = float(block['line_spacing'])
            for key in ('keep_with_next', 'keep_together', 'page_break_before'):
                if key in block: setattr(paragraph.paragraph_format, key, block[key])
            add_runs(paragraph, runs)
        else:
            raise ValueError('Unsupported Word block type')


def append_slides(presentation, slides):
    """Add bounded slides with optional positioned visual elements."""
    if not isinstance(slides, list) or len(slides) > 100 or len(json.dumps(slides, ensure_ascii=False)) > 2000000:
        raise ValueError('Slides must be a list of at most 100 items and 2,000,000 characters')
    def number(value, name, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not minimum <= value <= maximum or not math.isfinite(value):
            raise ValueError(f'{name} must be between {minimum} and {maximum}')
        return value
    def color(value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', value): raise ValueError('Colors must be six-digit RGB values')
        return RGBColor.from_string(value.upper())
    alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}
    def validate_slide_paragraphs(paragraphs):
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 100: raise ValueError('Slide paragraphs must contain 1 to 100 entries')
        for para in paragraphs:
            if not isinstance(para, dict) or set(para) - {'text', 'runs', 'align', 'bullet', 'level', 'space_after'} or ('text' in para) == ('runs' in para): raise ValueError('Each slide paragraph requires text or runs')
            if 'align' in para and (not isinstance(para['align'], str) or para['align'] not in alignment): raise ValueError('Invalid slide paragraph alignment')
            if 'bullet' in para and not isinstance(para['bullet'], bool): raise ValueError('Slide bullet must be a boolean')
            if 'level' in para and (isinstance(para['level'], bool) or not isinstance(para['level'], int) or not 0 <= para['level'] <= 8): raise ValueError('Slide paragraph level must be 0 to 8')
            if 'space_after' in para: number(para['space_after'], 'space_after', 0, 400)
            runs = [{'text': para['text']}] if 'text' in para else para['runs']
            if not isinstance(runs, list) or not 1 <= len(runs) <= 100: raise ValueError('Slide paragraph requires 1 to 100 runs')
            for run in runs:
                if not isinstance(run, dict) or set(run) - {'text', 'font', 'font_size', 'color', 'bold', 'italic', 'underline', 'url', 'target_slide'} or not isinstance(run.get('text'), str) or len(run['text']) > 10000 or any(c in run['text'] for c in '\r\n'): raise ValueError('Invalid slide text run')
                for key in ('bold', 'italic', 'underline'):
                    if key in run and not isinstance(run[key], bool): raise ValueError(f'{key} must be a boolean')
                if 'font' in run and (not isinstance(run['font'], str) or not 1 <= len(run['font']) <= 100): raise ValueError('Font must be a name of at most 100 characters')
                if 'font_size' in run: number(run['font_size'], 'font_size', 1, 400)
                if 'color' in run: color(run['color'])
                if 'target_slide' in run:
                    if 'url' in run or isinstance(run['target_slide'], bool) or not isinstance(run['target_slide'], int) or not 1 <= run['target_slide'] <= final_slide_count: raise ValueError('Run target_slide must be a valid one-based slide number and cannot be combined with url')
                if 'url' in run:
                    url = run['url']
                    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url): raise ValueError('Invalid hyperlink URL')
                    try: parsed = urlsplit(url)
                    except ValueError: raise ValueError('Invalid hyperlink URL') from None
                    if parsed.scheme.lower() not in ('http', 'https', 'mailto') or parsed.scheme.lower() in ('http', 'https') and not parsed.hostname or parsed.scheme.lower() == 'mailto' and not parsed.path: raise ValueError('Hyperlink must be an HTTP, HTTPS or mailto URL')
    def write_slide_paragraphs(frame, paragraphs, defaults):
        frame.clear()
        for index, spec in enumerate(paragraphs):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            if 'align' in spec or 'align' in defaults: paragraph.alignment = alignment[spec.get('align', defaults.get('align'))]
            level = spec.get('level', 0); paragraph.level = level
            if 'space_after' in spec: paragraph.space_after = Pt(spec['space_after'])
            properties = paragraph._p.get_or_add_pPr()
            if spec.get('bullet', False):
                properties.set('marL', str(Inches(0.3 * (level + 1)))); properties.set('indent', str(-Inches(0.18)))
                bullet = PptxElement('a:buChar'); bullet.set('char', '•'); properties.append(bullet)
            else: properties.append(PptxElement('a:buNone'))
            runs = [{'text': spec['text']}] if 'text' in spec else spec['runs']
            for run_spec in runs:
                run = paragraph.add_run(); run.text = run_spec['text']; font = run.font
                for key in ('font_size', 'font', 'color', 'bold', 'italic', 'underline'):
                    value = run_spec.get(key, defaults.get(key))
                    if value is None: continue
                    if key == 'font_size': font.size = Pt(value)
                    elif key == 'font': font.name = value
                    elif key == 'color': font.color.rgb = color(value)
                    else: setattr(font, key, value)
                if 'url' in run_spec: run.hyperlink.address = run_spec['url']
                if 'target_slide' in run_spec: pending_run_navigation.append((run, run_spec['target_slide']))
    image_bytes = 0; chart_count = 0; chart_points = 0; pending_navigation = []; pending_run_navigation = []
    final_slide_count = len(presentation.slides) + len(slides)
    for item in slides:
        if not isinstance(item, dict) or set(item) - {'layout', 'title', 'body', 'background', 'elements', 'notes'}: raise ValueError('Invalid slide properties')
        if 'notes' in item: notes.validate_text(item['notes'])
        layout_name = item.get('layout', 'title_content')
        if layout_name == 'blank':
            matches = [layout for layout in presentation.slide_layouts if layout.name.casefold() == 'blank']
            if len(matches) != 1: raise ValueError('A unique Blank slide layout is required')
            if 'title' in item or 'body' in item: raise ValueError('Blank slides use positioned textboxes instead of title or body')
            slide = presentation.slides.add_slide(matches[0])
        elif layout_name == 'title_content':
            if not isinstance(item.get('title'), str) or not isinstance(item.get('body', ''), str): raise ValueError('Title and body must be text')
            if len(item['title']) > 10000 or len(item.get('body', '')) > 10000: raise ValueError('Slide text exceeds 10,000 characters')
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            if slide.shapes.title is None or 1 not in [placeholder.placeholder_format.idx for placeholder in slide.placeholders]: raise ValueError('Title and Content placeholders are unavailable')
            slide.shapes.title.text = item['title']; slide.placeholders[1].text = item.get('body', '')
        else: raise ValueError('Slide layout must be blank or title_content')
        if 'notes' in item:
            notes_frame = slide.notes_slide.notes_text_frame
            if notes_frame is None: raise ValueError('Notes slide has no speaker notes placeholder')
            notes_frame.text = item['notes']
        if 'background' in item:
            fill = slide.background.fill; fill.solid(); fill.fore_color.rgb = color(item['background'])
        elements = item.get('elements', [])
        if not isinstance(elements, list) or len(elements) > 200: raise ValueError('Slide elements must be a list of at most 200 items')
        named_shapes = {}
        for element in elements:
            if not isinstance(element, dict): raise ValueError('Slide elements must be objects')
            kind = element.get('type'); geometry = {'type', 'x', 'y', 'width', 'height'}
            allowed = {'textbox': geometry | {'text', 'paragraphs', 'font_size', 'font', 'color', 'bold', 'italic', 'align', 'fill', 'margins', 'vertical_align', 'auto_fit', 'wrap'},
                       'rectangle': geometry | {'fill'}, 'shape': geometry | {'id', 'shape_kind', 'fill', 'line_color', 'line_width', 'text', 'paragraphs', 'font', 'font_size', 'color', 'bold', 'italic', 'align', 'auto_fit'}, 'line': {'type', 'x', 'y', 'end_x', 'end_y', 'color', 'line_width', 'arrow'}, 'connector': {'type', 'start', 'end', 'color', 'line_width', 'arrow'}, 'image': geometry | {'path', 'description', 'fit'},
                       'table': geometry | {'rows', 'header', 'font_size', 'font', 'color', 'header_fill', 'header_color', 'column_weights'},
                       'chart': geometry | {'chart_type', 'categories', 'series', 'title', 'legend', 'x_axis_title', 'y_axis_title', 'show_values', 'show_percent', 'point_colors', 'value_axis_min', 'value_axis_max', 'text_color'}}
            if not isinstance(kind, str) or kind not in allowed or set(element) - (allowed[kind] | {'description', 'target_slide'}): raise ValueError('Unsupported slide element or property')
            if 'description' in element and (not isinstance(element['description'], str) or len(element['description']) > 1000): raise ValueError('Slide description must be text of at most 1,000 characters')
            if 'target_slide' in element and (isinstance(element['target_slide'], bool) or not isinstance(element['target_slide'], int) or not 1 <= element['target_slide'] <= final_slide_count): raise ValueError('Target slide must be a valid one-based slide number in the final deck')
            def describe(shape):
                if 'target_slide' in element: pending_navigation.append((shape, element['target_slide']))
                if 'description' in element:
                    properties = shape._element.xpath('./p:nvSpPr/p:cNvPr | ./p:nvCxnSpPr/p:cNvPr | ./p:nvGraphicFramePr/p:cNvPr | ./p:nvPicPr/p:cNvPr')
                    if len(properties) != 1: raise ValueError('Slide element has ambiguous nonvisual properties')
                    properties[0].set('descr', element['description'])
            if kind == 'connector':
                ends = []
                for key in ('start', 'end'):
                    endpoint = element.get(key)
                    if not isinstance(endpoint, dict) or set(endpoint) != {'shape', 'side'} or not isinstance(endpoint['shape'], str) or endpoint['shape'] not in named_shapes or endpoint['side'] not in ('top', 'left', 'bottom', 'right'): raise ValueError('Connector endpoints require an earlier named shape and a valid side')
                    target, target_kind = named_shapes[endpoint['shape']]; side = endpoint['side']
                    sites = {'top':0, 'left':2, 'bottom':4, 'right':6} if target_kind == 'ellipse' else {'top':0, 'left':1, 'bottom':2, 'right':3}
                    point = {'top':(target.left + target.width // 2, target.top), 'left':(target.left, target.top + target.height // 2), 'bottom':(target.left + target.width // 2, target.top + target.height), 'right':(target.left + target.width, target.top + target.height // 2)}[side]
                    ends.append((target, sites[side], point))
                if ends[0][2] == ends[1][2]: raise ValueError('Connector endpoints must differ')
                arrow = element.get('arrow', 'end')
                if arrow not in ('none', 'start', 'end', 'both'): raise ValueError('Connector arrow must be none, start, end or both')
                ink = color(element.get('color', '000000')); line_width = number(element.get('line_width', 2), 'line_width', 0.1, 20)
                shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, *ends[0][2], *ends[1][2])
                properties = shape._element.nvCxnSpPr.cNvCxnSpPr
                for tag, (target, index, _) in zip(('a:stCxn', 'a:endCxn'), ends):
                    connection = PptxElement(tag); connection.set('id', str(target.shape_id)); connection.set('idx', str(index)); properties.append(connection)
                shape.line.color.rgb = ink; shape.line.width = Pt(line_width); line = shape._element.spPr.get_or_add_ln()
                if arrow in ('start', 'both'): head = PptxElement('a:headEnd'); head.set('type', 'triangle'); line.append(head)
                if arrow in ('end', 'both'): tail = PptxElement('a:tailEnd'); tail.set('type', 'triangle'); line.append(tail)
                describe(shape)
                continue
            x = Inches(number(element.get('x'), 'x', -100, 100)); y = Inches(number(element.get('y'), 'y', -100, 100))
            if kind == 'line':
                end_x = Inches(number(element.get('end_x'), 'end_x', -100, 100)); end_y = Inches(number(element.get('end_y'), 'end_y', -100, 100))
                if (x, y) == (end_x, end_y): raise ValueError('Line endpoints must differ')
                arrow = element.get('arrow', 'none')
                if arrow not in ('none', 'start', 'end', 'both'): raise ValueError('Line arrow must be none, start, end or both')
                ink = color(element.get('color', '000000'))
                line_width = number(element.get('line_width', 2), 'line_width', 0.1, 20)
                shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, y, end_x, end_y)
                shape.line.color.rgb = ink; shape.line.width = Pt(line_width)
                line = shape._element.spPr.get_or_add_ln()
                if arrow in ('start', 'both'): head = PptxElement('a:headEnd'); head.set('type', 'triangle'); line.append(head)
                if arrow in ('end', 'both'): tail = PptxElement('a:tailEnd'); tail.set('type', 'triangle'); line.append(tail)
                describe(shape)
                continue
            width = Inches(number(element.get('width'), 'width', 0.01, 100)); height = Inches(number(element.get('height'), 'height', 0.01, 100))
            if kind == 'textbox':
                if ('text' in element) == ('paragraphs' in element): raise ValueError('Textbox requires text or paragraphs')
                text = element.get('text'); paragraphs = element.get('paragraphs')
                if text is not None and (not isinstance(text, str) or len(text) > 10000): raise ValueError('Textbox text must be at most 10,000 characters')
                if 'text' in element and text is None: raise ValueError('Textbox text must be a string')
                for key in ('bold', 'italic'):
                    if key in element and not isinstance(element[key], bool): raise ValueError(f'{key} must be a boolean')
                if 'font' in element and (not isinstance(element['font'], str) or not 1 <= len(element['font']) <= 100): raise ValueError('Font must be a name of at most 100 characters')
                alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}
                if 'align' in element and (not isinstance(element['align'], str) or element['align'] not in alignment): raise ValueError('Alignment must be left, center or right')
                if 'font_size' in element: number(element['font_size'], 'font_size', 1, 400)
                if 'color' in element: color(element['color'])
                if 'wrap' in element and not isinstance(element['wrap'], bool): raise ValueError('Textbox wrap must be a boolean')
                vertical = {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}
                if 'vertical_align' in element and (not isinstance(element['vertical_align'], str) or element['vertical_align'] not in vertical): raise ValueError('Invalid textbox vertical alignment')
                auto_fit = {'none': MSO_AUTO_SIZE.NONE, 'shrink': MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE, 'resize': MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT}
                if 'auto_fit' in element and (not isinstance(element['auto_fit'], str) or element['auto_fit'] not in auto_fit): raise ValueError('Invalid textbox auto fit')
                margins = element.get('margins')
                if 'margins' in element:
                    if not isinstance(margins, dict) or set(margins) - {'left', 'right', 'top', 'bottom'}: raise ValueError('Invalid textbox margins')
                    for key, value in margins.items(): number(value, 'margin ' + key, 0, 5)
                if paragraphs is not None: validate_slide_paragraphs(paragraphs)
                elif 'paragraphs' in element: raise ValueError('Textbox paragraphs must be a list')
                shape = slide.shapes.add_textbox(x, y, width, height); frame = shape.text_frame
                frame.word_wrap = element.get('wrap', True)
                if 'vertical_align' in element: frame.vertical_anchor = vertical[element['vertical_align']]
                if 'auto_fit' in element: frame.auto_size = auto_fit[element['auto_fit']]
                if margins is not None:
                    for key, value in margins.items(): setattr(frame, 'margin_' + key, Inches(value))
                    if frame.margin_left + frame.margin_right >= width or frame.margin_top + frame.margin_bottom >= height: raise ValueError('Textbox margins leave no content area')
                if 'fill' in element: shape.fill.solid(); shape.fill.fore_color.rgb = color(element['fill'])
                if paragraphs is None:
                    shape.text = text
                    for paragraph in shape.text_frame.paragraphs:
                        if 'align' in element: paragraph.alignment = alignment[element['align']]
                        for run in paragraph.runs:
                            for key in ('font_size', 'font', 'color', 'bold', 'italic'):
                                if key in element:
                                    value = element[key]; target = run.font
                                    if key == 'font_size': target.size = Pt(value)
                                    elif key == 'font': target.name = value
                                    elif key == 'color': target.color.rgb = color(value)
                                    else: setattr(target, key, value)
                else: write_slide_paragraphs(shape.text_frame, paragraphs, element)
            elif kind == 'rectangle':
                if 'fill' not in element: raise ValueError('Rectangle requires a fill color')
                shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, width, height)
                shape.fill.solid(); shape.fill.fore_color.rgb = color(element['fill']); shape.line.fill.background()
            elif kind == 'shape':
                kinds = {'rectangle':MSO_SHAPE.RECTANGLE, 'rounded_rectangle':MSO_SHAPE.ROUNDED_RECTANGLE, 'ellipse':MSO_SHAPE.OVAL, 'diamond':MSO_SHAPE.DIAMOND}
                shape_kind = element.get('shape_kind')
                if not isinstance(shape_kind, str) or shape_kind not in kinds: raise ValueError('Unsupported shape kind')
                shape_id = element.get('id')
                if 'id' in element and (not isinstance(shape_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', shape_id) or shape_id in named_shapes): raise ValueError('Shape id must be a unique identifier')
                if 'fill' not in element: raise ValueError('Shape requires a fill color')
                fill = color(element['fill'])
                if 'line_width' in element and 'line_color' not in element: raise ValueError('Shape line_width requires line_color')
                if 'line_color' in element: color(element['line_color'])
                if 'line_width' in element: number(element['line_width'], 'line_width', 0.1, 20)
                if 'text' in element and 'paragraphs' in element: raise ValueError('Shape accepts text or paragraphs')
                if 'font' in element and (not isinstance(element['font'], str) or not 1 <= len(element['font']) <= 100): raise ValueError('Font must be a name of at most 100 characters')
                if 'font_size' in element: number(element['font_size'], 'font_size', 1, 400)
                if 'color' in element: color(element['color'])
                for key in ('bold', 'italic'):
                    if key in element and not isinstance(element[key], bool): raise ValueError(f'{key} must be a boolean')
                if 'align' in element and (not isinstance(element['align'], str) or element['align'] not in alignment): raise ValueError('Invalid shape text alignment')
                if 'auto_fit' in element and element['auto_fit'] not in ('none', 'shrink'): raise ValueError('Shape auto_fit must be none or shrink')
                paragraphs = element.get('paragraphs')
                if 'text' in element:
                    text = element['text']
                    if not isinstance(text, str) or len(text) > 10000 or '\r' in text: raise ValueError('Shape text must be at most 10,000 characters')
                    paragraphs = [{'text':line} for line in text.split('\n')]
                if paragraphs is not None: validate_slide_paragraphs(paragraphs)
                elif 'paragraphs' in element: raise ValueError('Shape paragraphs must be a list')
                shape = slide.shapes.add_shape(kinds[shape_kind], x, y, width, height)
                if shape_id is not None: named_shapes[shape_id] = (shape, shape_kind)
                shape.fill.solid(); shape.fill.fore_color.rgb = fill
                if 'line_color' in element:
                    shape.line.color.rgb = color(element['line_color']); shape.line.width = Pt(element.get('line_width', 1))
                else: shape.line.fill.background()
                if paragraphs is not None:
                    shape.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE; shape.text_frame.word_wrap = True
                    if 'auto_fit' in element: shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE if element['auto_fit'] == 'shrink' else MSO_AUTO_SIZE.NONE
                    write_slide_paragraphs(shape.text_frame, paragraphs, {'align':'center', **element})
            elif kind == 'table':
                rows = element.get('rows'); header = element.get('header', False)
                if not isinstance(rows, list) or not 1 <= len(rows) <= 50 or any(not isinstance(row, list) for row in rows): raise ValueError('Slide table requires 1 to 50 rows')
                columns = len(rows[0])
                if not 1 <= columns <= 20 or len(rows) * columns > 500 or any(len(row) != columns for row in rows): raise ValueError('Slide table must be rectangular with at most 500 cells and 20 columns')
                for row in rows:
                    for value in row:
                        if isinstance(value, str):
                            if len(value) > 10000: raise ValueError('Slide table text exceeds 10,000 characters')
                        elif isinstance(value, dict) and set(value) == {'paragraphs'}:
                            validate_slide_paragraphs(value['paragraphs'])
                        else: raise ValueError('Slide table cells require text or paragraphs')
                if not isinstance(header, bool): raise ValueError('Table header must be a boolean')
                if not header and ('header_fill' in element or 'header_color' in element): raise ValueError('Header colors require a header row')
                if 'font_size' in element: number(element['font_size'], 'font_size', 1, 400)
                if 'font' in element and (not isinstance(element['font'], str) or not 1 <= len(element['font']) <= 100): raise ValueError('Font must be a name of at most 100 characters')
                for key in ('color', 'header_fill', 'header_color'):
                    if key in element: color(element[key])
                weights = element.get('column_weights')
                if weights is not None:
                    if not isinstance(weights, list) or len(weights) != columns: raise ValueError('Provide one column weight per column')
                    weights = [number(value, 'column weight', 0.01, 1000) for value in weights]
                shape = slide.shapes.add_table(len(rows), columns, x, y, width, height); table = shape.table
                table.first_row = header
                if weights is not None:
                    total = sum(weights); previous = 0; cumulative = 0
                    for index, weight in enumerate(weights):
                        cumulative += weight; end = width if index == columns - 1 else round(width * cumulative / total)
                        if end <= previous: raise ValueError('Column weights produce a zero-width column')
                        table.columns[index].width = end - previous; previous = end
                for row_index, values in enumerate(rows):
                    for column_index, text in enumerate(values):
                        cell = table.cell(row_index, column_index); cell.text_frame.word_wrap = True
                        is_header = header and row_index == 0
                        if isinstance(text, dict):
                            defaults = {key:element[key] for key in ('font_size','font','color') if key in element}
                            if is_header:
                                defaults['bold'] = True
                                if 'header_color' in element: defaults['color'] = element['header_color']
                            write_slide_paragraphs(cell.text_frame, text['paragraphs'], defaults)
                        else: cell.text = text
                        if is_header and 'header_fill' in element: cell.fill.solid(); cell.fill.fore_color.rgb = color(element['header_fill'])
                        if isinstance(text, str):
                            for paragraph in cell.text_frame.paragraphs:
                                for run in paragraph.runs:
                                    if 'font_size' in element: run.font.size = Pt(element['font_size'])
                                    if 'font' in element: run.font.name = element['font']
                                    ink = element.get('header_color') if is_header and 'header_color' in element else element.get('color')
                                    if ink is not None: run.font.color.rgb = color(ink)
                                    if is_header: run.font.bold = True
            elif kind == 'chart':
                chart_count += 1
                if chart_count > 20: raise ValueError('At most 20 slide charts are supported per request')
                chart_type = element.get('chart_type'); categories = element.get('categories'); series_specs = element.get('series')
                if chart_type not in ('column', 'bar', 'line', 'pie'): raise ValueError('Chart type must be column, bar, line or pie')
                if not isinstance(categories, list) or not 1 <= len(categories) <= 200 or any(not isinstance(value, str) or not value or len(value) > 255 for value in categories): raise ValueError('Chart categories require 1 to 200 nonempty text values')
                if not isinstance(series_specs, list) or not 1 <= len(series_specs) <= 20 or len(series_specs) * len(categories) > 2000: raise ValueError('Chart requires at most 20 series and 2,000 data points')
                chart_points += len(series_specs) * len(categories)
                if chart_points > 10000: raise ValueError('Slide chart data exceeds 10,000 points per request')
                title = element.get('title'); legend = element.get('legend', chart_type == 'pie' or len(series_specs) > 1)
                if chart_type == 'pie' and (len(series_specs) != 1 or any(key in element for key in ('x_axis_title', 'y_axis_title', 'value_axis_min', 'value_axis_max'))): raise ValueError('Pie charts require one series and have no axes')
                if chart_type != 'pie' and ('show_percent' in element or 'point_colors' in element): raise ValueError('Percent labels and point colors require a pie chart')
                if 'show_percent' in element and not isinstance(element['show_percent'], bool): raise ValueError('Chart show_percent must be a boolean')
                point_colors = element.get('point_colors')
                if point_colors is not None:
                    if not isinstance(point_colors, list) or len(point_colors) != len(categories): raise ValueError('Pie point_colors require one color per category')
                    for value in point_colors: color(value)
                if title is not None and (not isinstance(title, str) or len(title) > 255): raise ValueError('Chart title must be text of at most 255 characters')
                for key in ('x_axis_title', 'y_axis_title'):
                    if key in element and (not isinstance(element[key], str) or len(element[key]) > 255): raise ValueError('Chart axis titles must be text of at most 255 characters')
                for key in ('value_axis_min', 'value_axis_max'):
                    if key in element:
                        value = element[key]
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e100 <= value <= 1e100 or not math.isfinite(value): raise ValueError(f'Chart {key} must be a finite number within ±1e100')
                if 'value_axis_min' in element and 'value_axis_max' in element and element['value_axis_min'] >= element['value_axis_max']: raise ValueError('Chart value_axis_min must be less than value_axis_max')
                if not isinstance(legend, bool): raise ValueError('Chart legend must be a boolean')
                if 'show_values' in element and not isinstance(element['show_values'], bool): raise ValueError('Chart show_values must be a boolean')
                data = CategoryChartData(); data.categories = categories
                for series in series_specs:
                    if not isinstance(series, dict) or set(series) - {'name', 'values', 'color', 'number_format'}: raise ValueError('Invalid chart series')
                    name, values = series.get('name'), series.get('values')
                    if not isinstance(name, str) or not name or len(name) > 255 or not isinstance(values, list) or len(values) != len(categories): raise ValueError('Chart series needs a name and one value per category')
                    if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e100 <= value <= 1e100 or not math.isfinite(value)) for value in values): raise ValueError('Chart values must be finite numbers or null')
                    if chart_type == 'pie' and ('color' in series or any(value is not None and value < 0 for value in values) or not any(value is not None and value > 0 for value in values)): raise ValueError('Pie charts require nonnegative values, at least one positive value, and optional point_colors instead of series color')
                    number_format = series.get('number_format')
                    if number_format is not None and (not isinstance(number_format, str) or not 1 <= len(number_format) <= 255): raise ValueError('Chart number format must be text of at most 255 characters')
                    if 'color' in series: color(series['color'])
                    data.add_series(name, values, number_format=number_format)
                shape = slide.shapes.add_chart({'column': XL_CHART_TYPE.COLUMN_CLUSTERED, 'bar': XL_CHART_TYPE.BAR_CLUSTERED, 'line': XL_CHART_TYPE.LINE, 'pie': XL_CHART_TYPE.PIE}[chart_type], x, y, width, height, data); chart = shape.chart
                # Chart axis IDs must be positive and cross-references must stay consistent.
                axis_ids = {}
                for axis_id in chart._element.xpath('.//c:axId | .//c:crossAx'):
                    value = axis_id.get('val')
                    if value not in axis_ids: axis_ids[value] = str(len(axis_ids) + 1)
                    axis_id.set('val', axis_ids[value])
                embedded = load_workbook(io.BytesIO(chart.part.chart_workbook.xlsx_part.blob), data_only=False)
                try:
                    table = embedded.active
                    for row, expected in enumerate(categories, 2):
                        cell = table.cell(row=row, column=1)
                        if cell.value != expected or cell.data_type == 'f' or cell.hyperlink is not None: raise ValueError('Chart category was not preserved as literal text')
                    for column, spec in enumerate(series_specs, 2):
                        header = table.cell(row=1, column=column)
                        if header.value != spec['name'] or header.data_type == 'f' or header.hyperlink is not None: raise ValueError('Chart series name was not preserved as literal text')
                        for row, expected in enumerate(spec['values'], 2):
                            cell = table.cell(row=row, column=column)
                            if cell.value != expected or cell.data_type == 'f': raise ValueError('Chart numeric value could not be preserved')
                finally:
                    embedded.close()
                chart.has_legend = legend
                if element.get('show_values', False) or element.get('show_percent', False):
                    chart.plots[0].has_data_labels = True
                    labels = chart.plots[0].data_labels
                    labels.show_value = element.get('show_values', False)
                    labels.show_category_name = False; labels.show_series_name = False; labels.show_legend_key = False; labels.show_percentage = element.get('show_percent', False)
                if title is not None: chart.has_title = True; chart.chart_title.text_frame.text = title
                if chart_type != 'pie':
                    if 'value_axis_min' in element: chart.value_axis.minimum_scale = element['value_axis_min']
                    if 'value_axis_max' in element: chart.value_axis.maximum_scale = element['value_axis_max']
                    for key, axis in (('x_axis_title', chart.value_axis), ('y_axis_title', chart.category_axis)) if chart_type == 'bar' else (('x_axis_title', chart.category_axis), ('y_axis_title', chart.value_axis)):
                        if key in element: axis.has_title = True; axis.axis_title.text_frame.text = element[key]
                if 'text_color' in element: slide_charts.apply_text_color(chart, color(element['text_color']))
                if point_colors is not None:
                    for point, value in zip(chart.series[0].points, point_colors):
                        point.format.fill.solid(); point.format.fill.fore_color.rgb = color(value)
                for chart_series, spec in zip(chart.series, series_specs):
                    if 'color' in spec:
                        if chart_type in ('column', 'bar'): chart_series.format.fill.solid(); chart_series.format.fill.fore_color.rgb = color(spec['color'])
                        else: chart_series.format.line.color.rgb = color(spec['color'])
            else:
                path = element.get('path'); description = element.get('description', ''); fit = element.get('fit', 'stretch')
                if fit not in ('stretch', 'contain', 'cover'): raise ValueError('Image fit must be stretch, contain or cover')
                if not isinstance(path, str) or not isinstance(description, str) or len(description) > 1000: raise ValueError('Image requires a local path and optional short description')
                if Path(path).stat().st_size > 20 * 1024 * 1024: raise ValueError('Image exceeds 20 MiB')
                with tempfile.TemporaryDirectory(prefix='office-slide-image-') as directory:
                    image_snapshot, _ = snapshots.copy(path, directory); data = image_snapshot.read_bytes()
                image_bytes += len(data)
                if len(data) > 20 * 1024 * 1024 or image_bytes > 128 * 1024 * 1024: raise ValueError('Image size exceeds per-image or presentation limits')
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in ('PNG', 'JPEG') or image.width * image.height > 40000000: raise ValueError('Image must be PNG or JPEG with at most 40 million pixels')
                    aspect = image.width / image.height
                    image.verify()
                if fit != 'stretch':
                    with Image.open(io.BytesIO(data)) as image:
                        if image.getexif().get(274, 1) != 1: raise ValueError('Normalize image orientation before using contain or cover')
                box_aspect = width / height
                if fit == 'contain':
                    if aspect > box_aspect:
                        fit_width, fit_height = width, max(1, round(width / aspect))
                    else:
                        fit_width, fit_height = max(1, round(height * aspect)), height
                    shape = slide.shapes.add_picture(io.BytesIO(data), x + (width - fit_width) // 2, y + (height - fit_height) // 2, fit_width, fit_height)
                else:
                    shape = slide.shapes.add_picture(io.BytesIO(data), x, y, width, height)
                    if fit == 'cover':
                        crop = (1 - min(aspect / box_aspect, box_aspect / aspect)) / 2
                        if crop >= 0.49999: raise ValueError('Image aspect ratio is too extreme for cover')
                        if aspect > box_aspect: shape.crop_left = shape.crop_right = crop
                        else: shape.crop_top = shape.crop_bottom = crop
                shape._element.nvPicPr.cNvPr.set('descr', description)
            describe(shape)
    for shape, number in pending_navigation:
        shape.click_action.target_slide = presentation.slides[number - 1]
    for run, number in pending_run_navigation:
        relationship = run.part.relate_to(presentation.slides[number - 1].part, RELATIONSHIP_TYPE.SLIDE)
        action = run._r.get_or_add_rPr().get_or_add_hlinkClick(); action.set('action', 'ppaction://hlinksldjump'); action.set(qn('r:id'), relationship)


def format_workbook(workbook, options):
    """Apply bounded presentation settings to an authored workbook."""
    if not isinstance(options, dict) or len(options) > 100: raise ValueError('Sheet options must be an object with at most 100 sheets')
    total_cells = 0; chart_cache_bytes = 0; chart_cache_points = 0; image_bytes = 0; image_count = 0; table_count = 0
    # shortcut: cache bounded literal text, dates and finite numbers; calculated and ambiguous values require recalculation.
    def chart_cache(cells, text):
        nonlocal chart_cache_bytes, chart_cache_points
        if len(cells) > 2000 or chart_cache_points + len(cells) > 50000: return None
        values = []
        for cell in cells:
            value = cell.value
            if cell.data_type in ('f', 'e') or value is None or isinstance(value, bool): return None
            if text:
                if not isinstance(value, str) or isinstance(value, spreadsheet.UnverifiedSharedString) or not value or len(value) > 1000 or re.search(r'_x[0-9a-fA-F]{4}_', value): return None
                values.append(value)
            else:
                if isinstance(value, (date, datetime)):
                    if isinstance(value, datetime) and value.tzinfo is not None: return None
                    try: value = to_excel(value, workbook.epoch)
                    except (OverflowError, TypeError, ValueError): return None
                if not isinstance(value, (int, float)): return None
                try: numeric = float(value)
                except (OverflowError, ValueError): return None
                if not math.isfinite(numeric): return None
                values.append(numeric)
        size = sum(len(str(value).encode('utf-8')) for value in values)
        if chart_cache_bytes + size > 8 * 1024 * 1024: return None
        chart_cache_bytes += size; chart_cache_points += len(values)
        if text: return StrData(ptCount=len(values), pt=[StrVal(idx=index, v=value) for index, value in enumerate(values)])
        formats = {cell.number_format for cell in cells}
        format_code = next(iter(formats)) if len(formats) == 1 else 'General'
        if not isinstance(format_code, str) or not 1 <= len(format_code) <= 255: format_code = 'General'
        return NumData(formatCode=format_code, ptCount=len(values), pt=[NumVal(idx=index, v=value) for index, value in enumerate(values)])
    def bounds(reference, limit):
        if not isinstance(reference, str) or len(reference) > 32: raise ValueError('Invalid cell range')
        try: a, b, c, d = range_boundaries(reference)
        except ValueError: raise ValueError('Invalid cell range') from None
        if not all(isinstance(value, int) for value in (a, b, c, d)) or not (1 <= a <= c <= 16384 and 1 <= b <= d <= 1048576) or (c-a+1)*(d-b+1) > limit:
            raise ValueError('Invalid or oversized cell range')
        return a, b, c, d
    def amount(value, name, maximum):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= maximum or not math.isfinite(value): raise ValueError(f'Invalid {name}')
        return value
    def rgb(value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9A-Fa-f]{6}', value): raise ValueError('Colors must be six-digit RGB values')
        return 'FF' + value.upper()
    for name, setting in options.items():
        if name not in workbook.sheetnames: raise ValueError(f'Worksheet not found: {name}')
        if not isinstance(setting, dict) or set(setting) - {'freeze_panes', 'auto_filter', 'column_widths', 'row_heights', 'formats', 'charts', 'fit_to_page', 'print_options', 'images', 'tables', 'list_validations', 'conditional_formats'}: raise ValueError('Invalid worksheet options')
        sheet = workbook[name]
        if not isinstance(sheet, Worksheet): raise ValueError('Sheet options require a worksheet')
        if 'freeze_panes' in setting:
            value = setting['freeze_panes']
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', value): raise ValueError('Freeze panes requires a single cell')
                bounds(value, 1)
            sheet.freeze_panes = value
        if 'fit_to_page' in setting:
            fit = setting['fit_to_page']
            if not isinstance(fit, bool): raise ValueError('Fit to page must be a boolean')
            if sheet.sheet_properties.pageSetUpPr is None: sheet.sheet_properties.pageSetUpPr = PageSetupProperties()
            sheet.sheet_properties.pageSetUpPr.fitToPage = fit
            if fit: sheet.page_setup.fitToWidth = 1; sheet.page_setup.fitToHeight = 0
        if 'print_options' in setting:
            printing = setting['print_options']
            if not isinstance(printing, dict) or set(printing) - {'paper', 'orientation', 'area', 'repeat_rows', 'repeat_columns', 'margins', 'header', 'footer'}: raise ValueError('Invalid worksheet print options')
            if 'paper' in printing:
                paper = printing['paper']
                if not isinstance(paper, str) or paper not in ('a4', 'letter'): raise ValueError('Print paper must be a4 or letter')
                sheet.page_setup.paperSize = {'a4': sheet.PAPERSIZE_A4, 'letter': sheet.PAPERSIZE_LETTER}[paper]
            if 'orientation' in printing:
                orientation = printing['orientation']
                if not isinstance(orientation, str) or orientation not in ('portrait', 'landscape'): raise ValueError('Invalid print orientation')
                sheet.page_setup.orientation = orientation
            if 'area' in printing:
                area = printing['area']
                if area is not None: bounds(area, 10000000)
                sheet.print_area = area
            if 'repeat_rows' in printing:
                rows = printing['repeat_rows']
                match = re.fullmatch(r'([1-9][0-9]{0,6}):([1-9][0-9]{0,6})', rows) if isinstance(rows, str) else None
                if rows is not None and (match is None or not 1 <= int(match[1]) <= int(match[2]) <= 1048576): raise ValueError('Repeat rows must be a range such as 1:2')
                sheet.print_title_rows = rows
            if 'repeat_columns' in printing:
                columns = printing['repeat_columns']
                match = re.fullmatch(r'([A-Za-z]{1,3}):([A-Za-z]{1,3})', columns) if isinstance(columns, str) else None
                if columns is not None and (match is None or not 1 <= column_index_from_string(match[1].upper()) <= column_index_from_string(match[2].upper()) <= 16384): raise ValueError('Repeat columns must be a range such as A:B')
                sheet.print_title_cols = columns.upper() if columns is not None else None
            margins = printing.get('margins', {})
            if not isinstance(margins, dict) or set(margins) - {'left', 'right', 'top', 'bottom', 'header', 'footer'}: raise ValueError('Invalid worksheet print margins')
            for margin, value in margins.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5 or not math.isfinite(value): raise ValueError('Print margins must be 0 to 5 inches')
                setattr(sheet.page_margins, margin, value)
            dimensions = {'1': (8.5, 11), '9': (8.2677165354, 11.6929133858)}.get(str(sheet.page_setup.paperSize))
            if dimensions is not None:
                page_width, page_height = dimensions if sheet.page_setup.orientation != 'landscape' else dimensions[::-1]
                if sheet.page_margins.left + sheet.page_margins.right > page_width - 0.5 or sheet.page_margins.top + sheet.page_margins.bottom > page_height - 0.5: raise ValueError('Print margins leave insufficient content area')
            for name in ('header', 'footer'):
                if name not in printing: continue
                value = printing[name]; allowed = {'text', 'align'} | ({'page_number'} if name == 'footer' else set())
                if not isinstance(value, dict) or set(value) - allowed: raise ValueError(f'Invalid worksheet print {name}')
                text = value.get('text', ''); align = value.get('align', 'right' if name == 'footer' else 'left'); page_number = value.get('page_number', False)
                if not isinstance(text, str) or len(text) > 255 or any(ord(char) < 32 for char in text): raise ValueError(f'Invalid worksheet print {name} text')
                if not isinstance(align, str) or align not in ('left', 'center', 'right') or not isinstance(page_number, bool): raise ValueError(f'Invalid worksheet print {name} options')
                content = text.replace('&', '&&') + ((' ' if text else '') + '&P' if page_number else '')
                target = sheet.oddHeader if name == 'header' else sheet.oddFooter
                getattr(target, align).text = content
                if len(str(target).encode('utf-16-le')) // 2 > 255: raise ValueError(f'Worksheet print {name} exceeds 255 characters')
        if 'auto_filter' in setting:
            value = setting['auto_filter']
            if value is not None: bounds(value, 10000000)
            if sheet.auto_filter.filterColumn or sheet.auto_filter.sortState is not None: raise ValueError('Existing filter criteria or sort state require targeted editing')
            sheet.auto_filter.ref = value
        for key, maximum in (('column_widths', 255), ('row_heights', 409.5)):
            dimensions = setting.get(key, {})
            if not isinstance(dimensions, dict) or len(dimensions) > 200: raise ValueError('Dimensions must be an object with at most 200 entries')
            for index, value in dimensions.items():
                if key == 'column_widths':
                    if not isinstance(index, str) or not re.fullmatch(r'[A-Za-z]{1,3}', index) or column_index_from_string(index.upper()) > 16384: raise ValueError('Invalid column')
                    sheet.column_dimensions[index.upper()].width = amount(value, 'column width', maximum)
                else:
                    if not isinstance(index, str) or not re.fullmatch(r'[1-9][0-9]{0,6}', index) or int(index) > 1048576: raise ValueError('Invalid row')
                    sheet.row_dimensions[int(index)].height = amount(value, 'row height', maximum)
        formats = setting.get('formats', [])
        if not isinstance(formats, list) or len(formats) > 100: raise ValueError('Formats must be a list of at most 100 entries')
        for style in formats:
            allowed = {'range', 'bold', 'italic', 'font_size', 'font_color', 'fill', 'number_format', 'horizontal', 'wrap'}
            if not isinstance(style, dict) or not set(style) <= allowed or 'range' not in style or len(style) == 1: raise ValueError('Invalid worksheet format')
            a, b, c, d = bounds(style['range'], 10000); total_cells += (c-a+1)*(d-b+1)
            if total_cells > 20000: raise ValueError('Worksheet formats exceed 20,000 cells')
            for key in ('bold', 'italic', 'wrap'):
                if key in style and not isinstance(style[key], bool): raise ValueError(f'{key} must be a boolean')
            if 'font_size' in style and amount(style['font_size'], 'font size', 409) < 1: raise ValueError('Font size must be at least 1 point')
            for key in ('font_color', 'fill'):
                if key in style: rgb(style[key])
            if 'number_format' in style and (not isinstance(style['number_format'], str) or not 1 <= len(style['number_format']) <= 255): raise ValueError('Number format must be text of at most 255 characters')
            if 'horizontal' in style and style['horizontal'] not in ('general', 'left', 'center', 'right'): raise ValueError('Invalid horizontal alignment')
            for row in sheet.iter_rows(min_row=b, max_row=d, min_col=a, max_col=c):
                for cell in row:
                    if isinstance(cell, MergedCell): raise ValueError('Cannot format merged-cell placeholders in basic authoring')
                    if any(key in style for key in ('bold', 'italic', 'font_size', 'font_color')):
                        font = copy(cell.font)
                        for key, attr in (('bold','bold'), ('italic','italic'), ('font_size','size'), ('font_color','color')):
                            if key in style: setattr(font, attr, rgb(style[key]) if key == 'font_color' else style[key])
                        cell.font = font
                    if 'fill' in style: cell.fill = PatternFill(fill_type='solid', fgColor=rgb(style['fill']))
                    if 'horizontal' in style or 'wrap' in style:
                        alignment = copy(cell.alignment)
                        if 'horizontal' in style: alignment.horizontal = style['horizontal']
                        if 'wrap' in style: alignment.wrap_text = style['wrap']
                        cell.alignment = alignment
                    if 'number_format' in style: cell.number_format = style['number_format']
        conditional_formats = setting.get('conditional_formats', [])
        if not isinstance(conditional_formats, list) or len(conditional_formats) > 100: raise ValueError('Conditional formats must be a list of at most 100 entries')
        if conditional_formats:
            priorities = [rule.priority for rules in sheet.conditional_formatting._cf_rules.values() for rule in rules]
            if any(not isinstance(value, int) or not 1 <= value <= 2147483647 for value in priorities) or len(set(priorities)) != len(priorities) or max(priorities, default=0) + len(conditional_formats) > 2147483647: raise ValueError('Existing conditional format priorities are ambiguous')
            sheet.conditional_formatting.max_priority = max(sheet.conditional_formatting.max_priority, max(priorities, default=0))
        for rule in conditional_formats:
            if not isinstance(rule, dict): raise ValueError('Invalid conditional format')
            kind = rule.get('type'); a, b, c, d = bounds(rule.get('range'), 1000000)
            if kind == 'cell':
                if set(rule) - {'type', 'range', 'operator', 'values', 'fill', 'stop_if_true'}: raise ValueError('Invalid cell conditional format')
                operator = rule.get('operator'); values = rule.get('values')
                allowed = ('equal', 'notEqual', 'lessThan', 'lessThanOrEqual', 'greaterThan', 'greaterThanOrEqual', 'between', 'notBetween')
                if operator not in allowed or not isinstance(values, list) or len(values) != (2 if operator in ('between', 'notBetween') else 1): raise ValueError('Invalid conditional format operator or values')
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e307 or not math.isfinite(value) for value in values): raise ValueError('Conditional format values must be finite numbers')
                if len(values) == 2 and values[0] > values[1]: raise ValueError('Conditional format bounds are reversed')
                if 'stop_if_true' in rule and not isinstance(rule['stop_if_true'], bool): raise ValueError('stop_if_true must be a boolean')
                formatted = CellIsRule(operator=operator, formula=[str(value) for value in values], fill=PatternFill(fill_type='solid', fgColor=rgb(rule.get('fill'))), stopIfTrue=rule.get('stop_if_true', False))
            elif kind == 'formula':
                if set(rule) - {'type', 'range', 'formula', 'fill', 'stop_if_true'}: raise ValueError('Invalid formula conditional format')
                formula = rule.get('formula')
                if not isinstance(formula, str) or not formula or re.search(r'[\x00-\x1f\ud800-\udfff\ufffe\uffff]|_x[0-9a-fA-F]{4}_', formula) or len(formula.encode('utf-16-le')) // 2 > 8192: raise ValueError('Invalid conditional format formula')
                if formula.startswith('='): formula = formula[1:]
                if not formula: raise ValueError('Invalid conditional format formula')
                if 'stop_if_true' in rule and not isinstance(rule['stop_if_true'], bool): raise ValueError('stop_if_true must be a boolean')
                formatted = FormulaRule(formula=[formula], fill=PatternFill(fill_type='solid', fgColor=rgb(rule.get('fill'))), stopIfTrue=rule.get('stop_if_true', False))
            elif kind == 'color_scale':
                if set(rule) - {'type', 'range', 'min_color', 'mid_color', 'max_color'}: raise ValueError('Invalid color scale')
                args = {'start_type':'min', 'start_color':rgb(rule.get('min_color')), 'end_type':'max', 'end_color':rgb(rule.get('max_color'))}
                if 'mid_color' in rule: args.update(mid_type='percentile', mid_value=50, mid_color=rgb(rule['mid_color']))
                formatted = ColorScaleRule(**args)
            elif kind == 'data_bar':
                if set(rule) - {'type', 'range', 'color'}: raise ValueError('Invalid data bar')
                formatted = DataBarRule(start_type='min', end_type='max', color=rgb(rule.get('color')), showValue=True)
            else: raise ValueError('Unsupported conditional format type')
            sheet.conditional_formatting.add(f'{get_column_letter(a)}{b}:{get_column_letter(c)}{d}', formatted)
        list_validations = setting.get('list_validations', [])
        if not isinstance(list_validations, list) or len(list_validations) > 100: raise ValueError('List validations must be a list of at most 100 entries')
        for rule in list_validations:
            if not isinstance(rule, dict) or set(rule) - {'range', 'values', 'source', 'allow_blank'} or ('values' in rule) == ('source' in rule): raise ValueError('List validation requires a range and exactly one of values or source')
            a, b, c, d = bounds(rule.get('range'), 1000000)
            if 'allow_blank' in rule and not isinstance(rule['allow_blank'], bool): raise ValueError('allow_blank must be a boolean')
            if 'values' in rule:
                values = rule['values']
                if not isinstance(values, list) or not values or len(values) > 255 or any(not isinstance(value, str) or not value or re.search(r'[,"\x00-\x1f\ud800-\udfff\ufffe\uffff]|_x[0-9a-fA-F]{4}_', value) for value in values): raise ValueError('Invalid literal list validation values')
                formula = '"' + ','.join(values) + '"'
                if len(formula.encode('utf-16-le')) // 2 > 255: raise ValueError('Literal list validation exceeds 255 UTF-16 units')
            else:
                source = rule['source']
                if not isinstance(source, str) or not re.fullmatch(r'\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})?', source): raise ValueError('List validation source must be a local cell range')
                x, y, z, w = bounds(source, 100)
                if x != z and y != w: raise ValueError('List validation source must be one-dimensional')
                formula = f'${get_column_letter(x)}${y}:${get_column_letter(z)}${w}'
            for existing in sheet.data_validations.dataValidation:
                for ref in existing.sqref.ranges:
                    if a <= ref.max_col and ref.min_col <= c and b <= ref.max_row and ref.min_row <= d: raise ValueError('List validation overlaps an existing validation')
            validation = DataValidation(type='list', formula1=formula, allow_blank=rule.get('allow_blank', False), showErrorMessage=True, showDropDown=False, errorStyle='stop')
            validation.add(f'{get_column_letter(a)}{b}:{get_column_letter(c)}{d}')
            sheet.add_data_validation(validation)
        tables = setting.get('tables', [])
        if not isinstance(tables, list) or len(tables) > 20: raise ValueError('Tables must be a list of at most 20 entries per sheet')
        for spec in tables:
            table_count += 1
            if table_count > 100: raise ValueError('At most 100 workbook tables are supported per request')
            if not isinstance(spec, dict) or set(spec) - {'name', 'range', 'style', 'row_stripes', 'column_stripes', 'first_column', 'last_column'}: raise ValueError('Invalid worksheet table specification')
            table_name = spec.get('name')
            if not isinstance(table_name, str) or len(table_name) > 255 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', table_name) or table_name.casefold() in ('r', 'c') or re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]*', table_name) or re.fullmatch(r'R[1-9][0-9]*C[1-9][0-9]*', table_name, re.I): raise ValueError('Invalid worksheet table name')
            names = {key.casefold() for key in workbook.defined_names}
            for ws in workbook.worksheets:
                names.update(key.casefold() for key in ws.defined_names)
                names.update(key.casefold() for key in ws.tables)
            if table_name.casefold() in names: raise ValueError('Table name conflicts with an existing table or defined name')
            c1, r1, c2, r2 = bounds(spec.get('range'), 1000000)
            if r2 <= r1: raise ValueError('A table requires a header and at least one data row')
            def overlaps(other):
                a,b,c,d = other
                return c1 <= c and a <= c2 and r1 <= d and b <= r2
            if any(overlaps((item.min_col,item.min_row,item.max_col,item.max_row)) for item in sheet.merged_cells.ranges): raise ValueError('Tables cannot overlap merged cells')
            if any(overlaps(range_boundaries(item.ref)) for item in sheet.tables.values()): raise ValueError('Tables cannot overlap existing tables')
            if sheet.auto_filter.ref and overlaps(bounds(sheet.auto_filter.ref, 10000000)): raise ValueError('Table cannot overlap the worksheet auto-filter')
            headers = [sheet.cell(row=r1, column=column) for column in range(c1,c2+1)]
            if any(not isinstance(cell.value, str) or isinstance(cell.value, spreadsheet.UnverifiedSharedString) or cell.data_type == 'f' or not cell.value.strip() or cell.value != cell.value.strip() or len(cell.value.encode('utf-16-le'))//2 > 255 or any(ord(ch) < 32 for ch in cell.value) or re.search(r'_x[0-9a-fA-F]{4}_', cell.value) for cell in headers): raise ValueError('Table headers require nonempty literal text of at most 255 characters')
            if len({cell.value.casefold() for cell in headers}) != len(headers): raise ValueError('Table headers must be unique')
            style = spec.get('style', 'TableStyleMedium2')
            match = re.fullmatch(r'TableStyle(Light|Medium|Dark)([1-9][0-9]?)', style) if isinstance(style, str) else None
            if match is None or int(match[2]) > {'Light':21,'Medium':28,'Dark':11}[match[1]]: raise ValueError('Invalid built-in table style')
            for key in ('row_stripes','column_stripes','first_column','last_column'):
                if key in spec and not isinstance(spec[key], bool): raise ValueError(f'{key} must be a boolean')
            reference = f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}'
            table = Table(displayName=table_name, ref=reference); table._initialise_columns()
            for column, cell in zip(table.tableColumns, headers): column.name = cell.value
            table.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=spec.get('row_stripes', True), showColumnStripes=spec.get('column_stripes', False), showFirstColumn=spec.get('first_column', False), showLastColumn=spec.get('last_column', False))
            sheet.add_table(table)
        images = setting.get('images', []); added_images = []
        if not isinstance(images, list) or len(images) > 20: raise ValueError('Images must be a list of at most 20 entries per sheet')
        for spec in images:
            image_count += 1
            if image_count > 50: raise ValueError('At most 50 workbook images are supported per request')
            if not isinstance(spec, dict) or set(spec) - {'path', 'anchor', 'width', 'description'}: raise ValueError('Invalid worksheet image specification')
            path, anchor, width = spec.get('path'), spec.get('anchor'), spec.get('width')
            description = spec.get('description', '')
            if not isinstance(description, str) or len(description) > 1000: raise ValueError('Image description must be text of at most 1,000 characters')
            if not isinstance(path, str): raise ValueError('Worksheet image requires a local path')
            if not isinstance(anchor, str) or not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', anchor): raise ValueError('Image anchor must be a single cell')
            bounds(anchor, 1)
            width = amount(width, 'image width', 4096)
            if width < 1: raise ValueError('Image width must be at least one pixel')
            if Path(path).stat().st_size > 20 * 1024 * 1024: raise ValueError('Image exceeds 20 MiB')
            with tempfile.TemporaryDirectory(prefix='office-workbook-image-') as tmp:
                snapshot, _ = snapshots.copy(path, tmp); data = snapshot.read_bytes()
            image_bytes += len(data)
            if len(data) > 20 * 1024 * 1024 or image_bytes > 128 * 1024 * 1024: raise ValueError('Image size exceeds per-image or workbook limits')
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG') or image.width * image.height > 40000000: raise ValueError('Image must be PNG or JPEG with at most 40 million pixels')
                height = width * image.height / image.width
                if not 1 <= height <= 4096: raise ValueError('Image aspect ratio produces an unsupported height')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.getexif().get(274, 1) != 1: raise ValueError('Normalize image orientation before inserting it')
            picture = WorkbookImage(io.BytesIO(data)); picture.width = width; picture.height = height
            sheet.add_image(picture, anchor.upper()); added_images.append((picture, description))
        charts = setting.get('charts', [])
        if not isinstance(charts, list) or len(charts) > 20: raise ValueError('Charts must be a list of at most 20 entries')
        for chart_spec in charts:
            allowed = {'type', 'data', 'categories', 'anchor', 'title', 'x_axis_title', 'y_axis_title', 'titles_from_data', 'category_type', 'date_format', 'width', 'height', 'series_colors', 'legend', 'y_min', 'y_max', 'show_gridlines', 'show_values'}
            if not isinstance(chart_spec, dict) or set(chart_spec) - allowed or chart_spec.get('type') not in ('column', 'line', 'scatter'): raise ValueError('Invalid chart specification')
            a, b, c, d = bounds(chart_spec.get('data'), 10000)
            headings = chart_spec.get('titles_from_data', True)
            if not isinstance(headings, bool) or d - b + 1 <= int(headings) or c - a + 1 > 30: raise ValueError('Chart data requires at least one data row and at most 30 series')
            anchor = chart_spec.get('anchor', 'E2')
            if not isinstance(anchor, str) or not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', anchor): raise ValueError('Chart anchor must be a single cell')
            bounds(anchor, 1)
            category_type = chart_spec.get('category_type', 'auto')
            if category_type not in ('auto', 'text', 'number', 'date', 'datetime') or category_type != 'auto' and 'categories' not in chart_spec or category_type == 'datetime' and chart_spec['type'] != 'scatter': raise ValueError('Invalid chart category type')
            if chart_spec['type'] == 'scatter' and 'categories' not in chart_spec: raise ValueError('Scatter charts require X values in categories')
            labels = None; text_categories = False; date_categories = False; datetime_categories = False
            if 'categories' in chart_spec:
                ca, cb, cc, cd = bounds(chart_spec['categories'], 10000)
                if ca != cc or cd - cb + 1 != d - b + 1 - int(headings): raise ValueError('Chart categories must be one column matching the data rows')
                labels = Reference(sheet, min_col=ca, min_row=cb, max_col=cc, max_row=cd)
                category_cells = [sheet.cell(row=row, column=ca) for row in range(cb, cd + 1)]
                if category_type == 'auto':
                    kinds = set()
                    for cell in category_cells:
                        if cell.value is None: continue
                        if cell.data_type in ('f', 'e'): kinds.add('unknown')
                        elif isinstance(cell.value, str): kinds.add('text')
                        elif not isinstance(cell.value, bool) and isinstance(cell.value, (int, float, date, datetime)): kinds.add('number')
                        else: kinds.add('unknown')
                    if 'unknown' in kinds or len(kinds) > 1: raise ValueError('Choose text or number category_type for mixed or formula categories')
                    text_categories = 'text' in kinds
                else:
                    text_categories = category_type == 'text'
                dated = [cell.value for cell in category_cells if cell.value is not None]
                date_categories = category_type == 'date' or (category_type == 'auto' and bool(dated) and all(isinstance(value, date) and (not isinstance(value, datetime) or value.time().isoformat() == '00:00:00') for value in dated))
                datetime_categories = chart_spec['type'] == 'scatter' and (category_type == 'datetime' or category_type == 'auto' and bool(dated) and all(isinstance(value, date) for value in dated)) and not date_categories
                if chart_spec['type'] == 'scatter' and text_categories: raise ValueError('Scatter chart X values must be numeric')
                if chart_spec['type'] == 'scatter' and category_type == 'auto' and any(isinstance(value, date) for value in dated) and not all(isinstance(value, date) for value in dated): raise ValueError('Choose number or datetime category_type for mixed scatter X values')
                if date_categories:
                    for cell in category_cells:
                        value = cell.value
                        if value is None or cell.data_type == 'f': continue
                        if isinstance(value, datetime):
                            if value.tzinfo is not None or value.time().isoformat() != '00:00:00': raise ValueError('Date-axis categories require whole days')
                            value = to_excel(value, workbook.epoch)
                        elif isinstance(value, date): value = to_excel(value, workbook.epoch)
                        if not isinstance(value, (int,float)) or isinstance(value, bool) or not 1 <= value <= to_excel(date.max, workbook.epoch) or not math.isfinite(value) or value != int(value): raise ValueError('Date-axis categories require valid whole-day serials, dates, formulas or blank cells')
                if chart_spec['type'] == 'scatter' and not date_categories and not datetime_categories:
                    for cell in category_cells:
                        value = cell.value
                        if value is None or cell.data_type == 'f': continue
                        if isinstance(value, (date, datetime)): continue
                        if not isinstance(value, (int,float)) or isinstance(value, bool) or not -1.7976931348623157e308 <= value <= 1.7976931348623157e308 or not math.isfinite(value): raise ValueError('Scatter chart X values must be finite numbers, dates, formulas or blank cells')
                if datetime_categories:
                    maximum = to_excel(datetime(9999,12,31,23,59,59,999000), workbook.epoch)
                    for cell in category_cells:
                        value = cell.value
                        if value is None or cell.data_type == 'f': continue
                        if isinstance(value, datetime):
                            if value.tzinfo is not None or value.microsecond % 1000: raise ValueError('Datetime-axis values must be timezone-free with millisecond precision')
                            value = to_excel(value, workbook.epoch)
                        elif isinstance(value, date): value = to_excel(value, workbook.epoch)
                        if not isinstance(value, (int,float)) or isinstance(value, bool) or not 1 <= value <= maximum or not math.isfinite(value): raise ValueError('Datetime-axis values require valid dates, numeric serials, formulas or blank cells')
            if 'date_format' in chart_spec:
                value = chart_spec['date_format']
                if not (date_categories or datetime_categories) or not isinstance(value, str) or not value or re.search(r'[\x00-\x1f\ud800-\udfff\ufffe\uffff]', value) or len(value.encode('utf-16-le')) // 2 > 255: raise ValueError('Date format requires a date axis and valid format code')
            for key in ('title', 'x_axis_title', 'y_axis_title'):
                if key in chart_spec and (not isinstance(chart_spec[key], str) or len(chart_spec[key]) > 255): raise ValueError('Chart titles must be text of at most 255 characters')
            colors = chart_spec.get('series_colors')
            if colors is not None:
                if not isinstance(colors, list) or len(colors) != c - a + 1: raise ValueError('Chart series_colors must contain one color per series')
                colors = [rgb(color)[2:] for color in colors]
            for key in ('legend', 'show_gridlines', 'show_values'):
                if key in chart_spec and not isinstance(chart_spec[key], bool): raise ValueError(f'Chart {key} must be boolean')
            for key in ('y_min', 'y_max'):
                if key in chart_spec:
                    value = chart_spec[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1.7976931348623157e308 <= value <= 1.7976931348623157e308 or not math.isfinite(value): raise ValueError(f'Chart {key} must be a finite number')
            if 'y_min' in chart_spec and 'y_max' in chart_spec and chart_spec['y_min'] >= chart_spec['y_max']: raise ValueError('Chart y_min must be less than y_max')
            scatter = chart_spec['type'] == 'scatter'
            chart = BarChart() if chart_spec['type'] == 'column' else ScatterChart() if scatter else LineChart()
            if chart_spec['type'] == 'column': chart.type = 'col'
            if chart_spec['type'] == 'line': chart.smooth = False
            if chart_spec.get('legend') is False: chart.legend = None
            if 'show_values' in chart_spec: chart.dLbls = DataLabelList(showVal=chart_spec['show_values'], showLegendKey=False, showCatName=False, showSerName=False, showPercent=False, showBubbleSize=False)
            if 'show_gridlines' in chart_spec: chart.y_axis.majorGridlines = ChartLines() if chart_spec['show_gridlines'] else None
            if 'y_min' in chart_spec: chart.y_axis.scaling.min = chart_spec['y_min']
            if 'y_max' in chart_spec: chart.y_axis.scaling.max = chart_spec['y_max']
            if scatter:
                chart.scatterStyle = 'lineMarker'; chart.x_axis.axPos = 'b'
                if date_categories or datetime_categories: chart.x_axis.numFmt = chart_spec.get('date_format', 'yyyy-mm-dd hh:mm' if datetime_categories else 'yyyy-mm-dd')
                for column in range(a, c+1):
                    series = Series(Reference(sheet, min_col=column, min_row=b, max_row=d), xvalues=labels, title_from_data=headings)
                    series.marker.symbol = 'circle'; series.smooth = False; chart.series.append(series)
            else:
                if date_categories:
                    chart.x_axis = DateAxis(axId=chart.x_axis.axId, crossAx=chart.y_axis.axId, axPos='b', baseTimeUnit='days', numFmt=chart_spec.get('date_format', 'yyyy-mm-dd'))
                chart.add_data(Reference(sheet, min_col=a, min_row=b, max_col=c, max_row=d), titles_from_data=headings)
                if labels is not None:
                    if text_categories:
                        for series in chart.series: series.cat = AxDataSource(strRef=StrRef(f=str(labels)))
                    else: chart.set_categories(labels)
            for index, series in enumerate(chart.series):
                if chart_spec['type'] == 'line': series.smooth = False
                if colors is not None:
                    if chart_spec['type'] == 'column': series.graphicalProperties.solidFill = colors[index]
                    else:
                        series.graphicalProperties.line.solidFill = colors[index]
                        if scatter:
                            series.marker.graphicalProperties.solidFill = colors[index]
                            series.marker.graphicalProperties.line.solidFill = colors[index]
                if headings and series.tx and series.tx.strRef:
                    series.tx.strRef.strCache = chart_cache([sheet.cell(row=b, column=a + index)], True)
                values = [sheet.cell(row=row, column=a + index) for row in range(b + int(headings), d + 1)]
                (series.yVal if scatter else series.val).numRef.numCache = chart_cache(values, False)
                if labels is not None:
                    if scatter: series.xVal.numRef.numCache = chart_cache(category_cells, False)
                    elif text_categories: series.cat.strRef.strCache = chart_cache(category_cells, True)
                    else: series.cat.numRef.numCache = chart_cache(category_cells, False)
            if 'title' in chart_spec: chart.title = chart_spec['title']
            if 'x_axis_title' in chart_spec: chart.x_axis.title = chart_spec['x_axis_title']
            if 'y_axis_title' in chart_spec: chart.y_axis.title = chart_spec['y_axis_title']
            if 'width' in chart_spec: chart.width = amount(chart_spec['width'], 'chart width', 100)
            if 'height' in chart_spec: chart.height = amount(chart_spec['height'], 'chart height', 100)
            sheet.add_chart(chart, anchor.upper())
        if added_images:
            reserved = [len(sheet._charts) + len(sheet._images)]
            for picture in sheet._images:
                existing = getattr(picture.anchor, 'pic', None)
                group = getattr(picture.anchor, 'groupShape', None)
                if existing is None and group is not None: existing = group.pic
                if existing is not None: reserved.append(existing.nvPicPr.cNvPr.id)
            next_id = max(reserved) + 1
            if next_id + len(added_images) - 1 > 2147483647: raise ValueError('Workbook drawing identifier limit reached')
            for picture, description in added_images:
                anchor = _check_anchor(picture); anchor.pic = SpreadsheetDrawing()._picture_frame(next_id)
                anchor.pic.nvPicPr.cNvPr.descr = description
                picture.anchor = anchor; next_id += 1


def author(spec, output, source=None):
    if not isinstance(spec, dict): raise ValueError('Author specification must be a JSON object')
    suffix = kind(output)
    if 'page_setup' in spec and suffix != '.docx': raise ValueError('Word page setup requires DOCX output')
    if 'blocks' in spec and suffix != '.docx': raise ValueError('Word blocks require DOCX output')
    if 'slide_size' in spec and suffix != '.pptx': raise ValueError('Slide size requires PPTX output')
    if ('sheet_options' in spec or 'ranges' in spec) and suffix != '.xlsx': raise ValueError('Sheet options and ranges require XLSX output')
    if source and kind(source) != suffix:
        raise ValueError('Source and output formats must match')
    out = Path(output)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f'Output already exists: {out}')
    if source and out.resolve() == Path(source).resolve():
        raise ValueError('Output must differ from source')
    with tempfile.TemporaryDirectory(prefix='office-author-source-') as tmp:
        if source:
            source, _ = snapshots.copy(source, tmp)
        if suffix == '.docx':
            doc = Document(source) if source else Document()
            if 'page_setup' in spec:
                if source: raise ValueError('Word page setup requires a new document')
                configure_word_page(doc, spec['page_setup'])
            for index, text in spec.get('replace_paragraphs', {}).items():
                # Setting paragraph text discards run-level formatting in that paragraph.
                doc.paragraphs[int(index)].text = text
            for text in spec.get('paragraphs', []):
                doc.add_paragraph(text)
            if source and isinstance(spec.get('blocks'), list) and any(isinstance(block, dict) and block.get('type') == 'table_of_contents' for block in spec['blocks']): raise ValueError('Table of contents authoring requires a new document')
            if 'blocks' in spec: append_word_blocks(doc, spec['blocks'])
            obj = doc
        elif suffix == '.xlsx':
            obj = spreadsheet.load_author_workbook(source) if source else Workbook()
            sheets = spec.get('sheets', {}); ranges = spec.get('ranges', {})
            if not isinstance(sheets, dict) or not isinstance(ranges, dict) or len(ranges) > 100: raise ValueError('Workbook sheets and ranges must be objects with at most 100 range sheets')
            internal_targets = []
            def write_cell(ws, address, value):
                if ws.tables:
                    try:
                        c1, r1, c2, r2 = range_boundaries(address)
                        if None in (c1, r1, c2, r2) or c1 != c2 or r1 != r2: raise ValueError
                    except (TypeError, ValueError): raise ValueError('Worksheet cell address must be a single cell') from None
                    for table in ws.tables.values():
                        a, b, c, d = range_boundaries(table.ref)
                        if a <= c1 <= c and ((r1 == b and table.headerRowCount != 0) or (r1 == d and (table.totalsRowCount or table.totalsRowShown))):
                            raise ValueError('Table header and totals cells require a table-aware edit')
                literal = False; temporal = False; link_url = None; link_location = None
                if isinstance(value, dict):
                    if value.get('type') == 'hyperlink':
                        if set(value) not in ({'type', 'value', 'url'}, {'type', 'value', 'location'}) or not isinstance(value['value'], str) or not value['value']: raise ValueError('Hyperlink cell requires nonempty text and one target')
                        if 'location' in value:
                            link_location = session.normalize_hyperlink_location(value['location']); internal_targets.append(link_location)
                        else:
                            link_url = value['url']
                            if not isinstance(link_url, str) or len(link_url) > 2048 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 or 0xd800 <= ord(char) <= 0xdfff or ord(char) in (0xfffe, 0xffff) for char in link_url): raise ValueError('Invalid hyperlink URL')
                            try: parsed = urlsplit(link_url); hostname = parsed.hostname
                            except ValueError: raise ValueError('Invalid hyperlink URL') from None
                            if parsed.scheme.lower() not in ('http', 'https', 'mailto') or (parsed.scheme.lower() in ('http', 'https') and not hostname) or (parsed.scheme.lower() == 'mailto' and not parsed.path): raise ValueError('Hyperlink must be an HTTP, HTTPS or mailto URL')
                        literal = True; value = value['value']
                    else:
                        if set(value) != {'type', 'value'} or value['type'] not in ('text', 'date', 'datetime') or not isinstance(value['value'], str) or not value['value']: raise ValueError('Invalid typed cell value')
                        kind, value = value['type'], value['value']
                        if kind == 'text': literal = True
                        else:
                            pattern = r'[0-9]{4}-[0-9]{2}-[0-9]{2}' if kind == 'date' else r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,3})?'
                            if not re.fullmatch(pattern, value): raise ValueError('Invalid ISO date or datetime')
                            try: value = date.fromisoformat(value) if kind == 'date' else datetime.fromisoformat(value)
                            except ValueError: raise ValueError('Invalid ISO date or datetime') from None
                            day = value.date() if isinstance(value, datetime) else value
                            if day < date(1900, 1, 1) or day <= obj.epoch.date(): raise ValueError('Date must be after the workbook epoch and no earlier than 1900-01-01')
                            temporal = True
                formula = isinstance(value, str) and value.startswith('=') and not literal
                if isinstance(value, str):
                    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', value): raise ValueError('Cell text contains unsupported XML characters')
                    if len(value.encode('utf-16-le')) // 2 > (8192 if formula else 32767): raise ValueError('Cell text or formula exceeds Excel length limits')
                    if formula and value == '=': raise ValueError('Formula expression is empty')
                elif not temporal and value is not None and not isinstance(value, (int, float, bool)): raise ValueError('Cell value must be text, number, boolean, typed date or null')
                elif isinstance(value, (int, float)) and not isinstance(value, bool) and (value > 1.7976931348623157e308 or value < -1.7976931348623157e308 or isinstance(value, float) and not math.isfinite(value)): raise ValueError('Cell number must be finite and within Excel numeric range')
                if not formula: spreadsheet.validate_cell_value(value)
                ws[address] = value
                if literal: ws[address].data_type = 's'
                if link_url is not None or link_location is not None:
                    cell = ws[address]
                    cell.hyperlink = link_url if link_url is not None else Hyperlink(ref=cell.coordinate, location=quote_sheetname(link_location['sheet']) + '!' + link_location['cell'])
                    if not cell.has_style:
                        font = copy(cell.font); font.color = 'FF0563C1'; font.underline = 'single'; cell.font = font
            def worksheet(name):
                if not isinstance(name, str) or not name: raise ValueError('Worksheet name must be nonempty text')
                ws = obj[name] if name in obj.sheetnames else obj.create_sheet(name)
                if not isinstance(ws, Worksheet) or ws.title != name: raise ValueError('Worksheet name is unavailable or ambiguous')
                return ws
            occupied = {}; range_cells = 0
            for name, cells in sheets.items():
                if not isinstance(cells, dict): raise ValueError('Worksheet cells must be an object')
                ws = worksheet(name)
                occupied[name] = set()
                for address, value in cells.items():
                    try:
                        c1, r1, c2, r2 = range_boundaries(address)
                        if not all(isinstance(v, int) for v in (c1,r1,c2,r2)) or c1 != c2 or r1 != r2 or not (1 <= c1 <= 16384 and 1 <= r1 <= 1048576): raise ValueError()
                    except (TypeError, ValueError): raise ValueError('Worksheet cell address must be a single cell') from None
                    if (c1,r1) in occupied[name]: raise ValueError('Duplicate worksheet cell address')
                    occupied[name].add((c1,r1)); write_cell(ws, address, value)
            for name, blocks in ranges.items():
                if not isinstance(blocks, list) or len(blocks) > 100: raise ValueError('Worksheet ranges must be a list of at most 100 blocks')
                ws = worksheet(name)
                seen = occupied.setdefault(name, set())
                for block in blocks:
                    if not isinstance(block, dict) or set(block) != {'start','values'}: raise ValueError('Each worksheet range requires start and values')
                    address, rows = block['start'], block['values']
                    if not isinstance(address, str) or not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', address): raise ValueError('Range start must be a single cell')
                    c1, r1, _, _ = range_boundaries(address)
                    if not isinstance(rows, list) or not rows or not all(isinstance(row, list) for row in rows): raise ValueError('Range values must be a nonempty rectangular array')
                    width = len(rows[0])
                    if not 1 <= width <= 200 or any(len(row) != width for row in rows) or c1 + width - 1 > 16384 or r1 + len(rows) - 1 > 1048576: raise ValueError('Range values have invalid dimensions')
                    range_cells += len(rows) * width
                    if range_cells > 100000: raise ValueError('Worksheet ranges exceed 100,000 cells per request')
                    for row_index, row in enumerate(rows):
                        for column_index, value in enumerate(row):
                            col, number = c1 + column_index, r1 + row_index
                            if (col,number) in seen: raise ValueError('Worksheet ranges overlap another authored cell')
                            seen.add((col,number)); write_cell(ws, f'{get_column_letter(col)}{number}', value)
            if not source and 'Sheet' not in sheets and 'Sheet' not in ranges and len(obj.sheetnames) > 1:
                del obj['Sheet']
            for target in internal_targets:
                if target['sheet'] not in obj.sheetnames or not isinstance(obj[target['sheet']], Worksheet): raise ValueError('Internal hyperlink target worksheet is unavailable')
            if 'sheet_options' in spec: format_workbook(obj, spec['sheet_options'])
        else:
            obj = Presentation(source) if source else Presentation()
            for item in spec.get('replace_text', []):
                shape = obj.slides[item['slide']].shapes[item['shape']]
                if not shape.has_text_frame:
                    raise ValueError('Selected shape has no text frame')
                shape.text = item['text']
            if 'slide_size' in spec:
                size = spec['slide_size']
                if source: raise ValueError('Slide size can only be set when creating a new presentation')
                if not isinstance(size, dict) or set(size) != {'width', 'height'} or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 56 or not math.isfinite(v) for v in size.values()): raise ValueError('Slide width and height must be 1 to 56 inches')
                obj.slide_width, obj.slide_height = Inches(size['width']), Inches(size['height'])
            append_slides(obj, spec.get('slides', []))
        out.parent.mkdir(parents=True, exist_ok=True)
        # Save into the target directory, then exclusively create the requested output.
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            candidate = Path(tmp) / out.name
            obj.save(candidate)
            if suffix == '.xlsx' and any(setting.get('images') for setting in spec.get('sheet_options', {}).values() if isinstance(setting, dict)):
                with zipfile.ZipFile(candidate) as archive:
                    entries = archive.infolist()
                    if candidate.stat().st_size > 128 * 1024 * 1024 or len(entries) > 5000 or sum(entry.file_size for entry in entries) > 128 * 1024 * 1024:
                        raise ValueError('Authored workbook with images exceeds package limits')
            os.link(candidate, out)
        return str(out.resolve())


def render(source, output_dir):
    kind(source)
    source = Path(source).resolve(strict=True)
    destination = Path(output_dir).absolute()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (source.stem + '.pdf')
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'Output already exists: {target}')
    executable = shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('LibreOffice (soffice) is required for rendering')
    with tempfile.TemporaryDirectory(dir=destination, prefix='.office-render-') as tmp:
        profile = (Path(tmp) / 'profile').as_uri()
        result = subprocess.run([executable, '-env:UserInstallation=' + profile, '--headless', '--convert-to', 'pdf', '--outdir', tmp, str(source)], capture_output=True, text=True, timeout=120, check=False)
        pdf = Path(tmp) / target.name
        if result.returncode or not pdf.is_file():
            raise RuntimeError(f'LibreOffice conversion failed: {result.stderr or result.stdout}')
        os.link(pdf, target)
    return str(target.resolve())


def preview(source, output_dir):
    executable = shutil.which('pdftoppm')
    if not executable:
        raise RuntimeError('Poppler pdftoppm is required for page previews')
    destination = Path(output_dir).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.office-preview-') as tmp:
        pdf = render(source, tmp)
        result = subprocess.run([executable, '-png', '-r', '120', pdf, str(Path(tmp) / 'page')],
                                capture_output=True, text=True, timeout=120, check=False)
        pages = sorted(Path(tmp).glob('page-*.png'))
        if result.returncode or not pages:
            raise RuntimeError(f'Page rendering failed: {result.stderr}')
        destination.mkdir()
        published = []
        try:
            for page in pages:
                target = destination / page.name
                os.link(page, target)
                published.append(target)
        except OSError:
            for target in published:
                target.unlink()
            destination.rmdir()
            raise
    return [str(page) for page in published]



def render_with_info(source, output_dir, pages=False):
    import snapshot
    with tempfile.TemporaryDirectory(prefix='office-render-snapshot-') as tmp:
        frozen, digest = snapshot.copy(source, tmp)
        advisory = spreadsheet.render_advisory(frozen)
        if pages: result = {'pages': preview(frozen, output_dir)}
        else: result = {'pdf': render(frozen, output_dir)}
        return {**result, 'snapshot_sha256': digest, 'render_advisory': advisory}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Probe local authoring and preview dependencies')
    read = commands.add_parser('inspect'); read.add_argument('file')
    comments = commands.add_parser('comments'); comments.add_argument('file')
    changes = commands.add_parser('tracked-changes'); changes.add_argument('file')
    stories = commands.add_parser('stories'); stories.add_argument('file')
    word_search = commands.add_parser('search-word'); word_search.add_argument('file'); word_search.add_argument('--query', required=True); word_search.add_argument('--offset', type=int, default=0); word_search.add_argument('--snapshot-sha256'); word_search.add_argument('--scope', choices=('body', 'stories', 'notes'), default='body')
    slide_search = commands.add_parser('search-slides'); slide_search.add_argument('file'); slide_search.add_argument('--query', required=True); slide_search.add_argument('--slide', type=int); slide_search.add_argument('--offset', type=int, default=0); slide_search.add_argument('--snapshot-sha256'); slide_search.add_argument('--scope', choices=('slides', 'notes'), default='slides')
    note_read = commands.add_parser('notes'); note_read.add_argument('file'); note_read.add_argument('--slide', type=int, required=True)
    slides_read = commands.add_parser('inspect-slides'); slides_read.add_argument('file')
    layout_read = commands.add_parser('inspect-layout'); layout_read.add_argument('file')
    slide_nav_read = commands.add_parser('inspect-slide-navigation'); slide_nav_read.add_argument('file')
    slide_charts_read = commands.add_parser('inspect-slide-charts'); slide_charts_read.add_argument('file')
    external_read = commands.add_parser('external-links'); external_read.add_argument('file')
    slide_text_read = commands.add_parser('inspect-slide-text'); slide_text_read.add_argument('file')
    edit = commands.add_parser('author'); edit.add_argument('--spec', required=True); edit.add_argument('--out', required=True); edit.add_argument('--source')
    render_command = commands.add_parser('render'); render_command.add_argument('file'); render_command.add_argument('--out-dir', required=True)
    images = commands.add_parser('preview'); images.add_argument('file'); images.add_argument('--out-dir', required=True)
    page = commands.add_parser('render-page'); page.add_argument('file'); page.add_argument('--out', required=True); page.add_argument('--page', type=int, required=True); page.add_argument('--box', type=float, nargs=4)
    visual_compare = commands.add_parser('compare-pages'); visual_compare.add_argument('before'); visual_compare.add_argument('after'); visual_compare.add_argument('--before-page', type=int, required=True); visual_compare.add_argument('--after-page', type=int, required=True); visual_compare.add_argument('--out', required=True)
    contact = commands.add_parser('contact-sheet'); contact.add_argument('file'); contact.add_argument('--out', required=True); contact.add_argument('--start', type=int, default=1); contact.add_argument('--count', type=int, default=12)
    structured = commands.add_parser('structured'); structured.add_argument('file'); structured.add_argument('mode', choices=['outline', 'get', 'query']); structured.add_argument('target', nargs='?')
    dump = commands.add_parser('dump'); dump.add_argument('file'); dump.add_argument('path', nargs='?', default='/')
    schema = commands.add_parser('schema'); schema.add_argument('format', choices=['docx', 'xlsx', 'pptx']); schema.add_argument('--element'); schema.add_argument('--operation', choices=['add', 'set', 'get', 'query', 'remove']); schema.add_argument('--query')
    batch = commands.add_parser('batch'); batch.add_argument('--spec', required=True); batch.add_argument('--out', required=True); batch.add_argument('--source')
    cells = commands.add_parser('cells'); cells.add_argument('file'); cells.add_argument('--sheet', required=True); cells.add_argument('--range', required=True, dest='cell_range')
    search = commands.add_parser('search-cells'); search.add_argument('file'); search.add_argument('--query', required=True)
    search.add_argument('--sheet'); search.add_argument('--offset', type=int, default=0); search.add_argument('--snapshot-sha256')
    formula_scan = commands.add_parser('scan-formulas'); formula_scan.add_argument('file')
    chart_scan = commands.add_parser('scan-chart-caches'); chart_scan.add_argument('file')
    calc = commands.add_parser('recalculate'); calc.add_argument('file'); calc.add_argument('--out', required=True); calc.add_argument('--allow-dynamic-arrays', action='store_true')
    bundle = commands.add_parser('review-bundle'); bundle.add_argument('file'); bundle.add_argument('--out-dir', required=True)
    audit = commands.add_parser('audit'); audit.add_argument('file')
    comparison = commands.add_parser('compare'); comparison.add_argument('before'); comparison.add_argument('after')
    note_diff = commands.add_parser('compare-notes'); note_diff.add_argument('before'); note_diff.add_argument('after'); note_diff.add_argument('--before-slide', type=int, required=True); note_diff.add_argument('--after-slide', type=int, required=True)
    cell_diff = commands.add_parser('compare-cells'); cell_diff.add_argument('before'); cell_diff.add_argument('after'); cell_diff.add_argument('--sheet', required=True); cell_diff.add_argument('--range', required=True, dest='cell_range')
    draft = commands.add_parser('session'); sub = draft.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start'); start.add_argument('directory'); group = start.add_mutually_exclusive_group(required=True); group.add_argument('--source'); group.add_argument('--format', choices=['docx', 'xlsx', 'pptx'])
    state = sub.add_parser('info'); state.add_argument('directory')
    session_dump = sub.add_parser('dump'); session_dump.add_argument('directory'); session_dump.add_argument('--revision', type=int, required=True); session_dump.add_argument('--path', default='/')
    selection = sub.add_parser('selection'); selection.add_argument('directory')
    selected_text = sub.add_parser('selection-text'); selected_text.add_argument('directory')
    candidates = sub.add_parser('selection-candidates'); candidates.add_argument('directory')
    apply = sub.add_parser('apply'); apply.add_argument('directory'); apply.add_argument('--base', type=int, required=True); apply.add_argument('--spec', required=True)
    replace = sub.add_parser('replace-text'); replace.add_argument('directory'); replace.add_argument('--base', type=int, required=True); replace.add_argument('--path', required=True); replace.add_argument('--find', required=True); replace.add_argument('--replace', required=True, dest='replacement')
    refresh_toc = sub.add_parser('refresh-word-toc'); refresh_toc.add_argument('directory'); refresh_toc.add_argument('--base', type=int, required=True); refresh_toc.add_argument('--path', required=True); refresh_toc.add_argument('--expected-sha256')
    replace_batch = sub.add_parser('replace-text-batch'); replace_batch.add_argument('directory'); replace_batch.add_argument('--base', type=int, required=True); replace_batch.add_argument('--changes', required=True, help='JSON array of path/find/replacement objects')
    session_cell_diff = sub.add_parser('compare-cells'); session_cell_diff.add_argument('directory'); session_cell_diff.add_argument('--before', type=int, required=True); session_cell_diff.add_argument('--after', type=int, required=True); session_cell_diff.add_argument('--sheet', required=True); session_cell_diff.add_argument('--range', required=True, dest='cell_range')
    chart_grid = sub.add_parser('read-slide-chart-grid'); chart_grid.add_argument('directory'); chart_grid.add_argument('--revision', type=int, required=True); chart_grid.add_argument('--part', required=True); chart_grid.add_argument('--sheet', required=True); chart_grid.add_argument('--range', dest='cell_range', required=True)
    chart_grid_edit = sub.add_parser('edit-slide-chart-grid'); chart_grid_edit.add_argument('directory'); chart_grid_edit.add_argument('--base', type=int, required=True); chart_grid_edit.add_argument('--part', required=True); chart_grid_edit.add_argument('--sheet', required=True); chart_grid_edit.add_argument('--range', dest='cell_range', required=True); chart_grid_edit.add_argument('--changes', required=True, help='JSON array of cell/value objects'); chart_grid_edit.add_argument('--sync-caches', action='store_true')
    table_column = sub.add_parser('rename-table-column'); table_column.add_argument('directory'); table_column.add_argument('--base', type=int, required=True); table_column.add_argument('--sheet', required=True); table_column.add_argument('--table', required=True); table_column.add_argument('--old', required=True); table_column.add_argument('--new', required=True)
    link_edit = sub.add_parser('set-grid-hyperlink'); link_edit.add_argument('directory'); link_edit.add_argument('--base', type=int, required=True); link_edit.add_argument('--sheet', required=True); link_edit.add_argument('--cell', required=True); link_mode = link_edit.add_mutually_exclusive_group(required=True); link_mode.add_argument('--url'); link_mode.add_argument('--target-sheet'); link_mode.add_argument('--remove', action='store_true'); link_edit.add_argument('--target-cell'); link_edit.add_argument('--expected-sha256')
    grid_edit = sub.add_parser('edit-grid'); grid_edit.add_argument('directory'); grid_edit.add_argument('--base', type=int, required=True); grid_edit.add_argument('--sheet', required=True); grid_edit.add_argument('--range', required=True, dest='cell_range'); grid_edit.add_argument('--changes', required=True, help='JSON array of cell/value objects')
    grid_resize = sub.add_parser('resize-grid'); grid_resize.add_argument('directory'); grid_resize.add_argument('--base', type=int, required=True); grid_resize.add_argument('--sheet', required=True); grid_resize.add_argument('--range', required=True, dest='cell_range'); grid_resize.add_argument('--target-range', required=True); grid_resize.add_argument('--column-width', type=float); grid_resize.add_argument('--row-height', type=float)
    merge = sub.add_parser('merge-cells'); merge.add_argument('directory'); merge.add_argument('--base', type=int, required=True); merge.add_argument('--sheet', required=True); merge.add_argument('--range', required=True, dest='cell_range'); merge.add_argument('--unmerge', action='store_true')
    freeze = sub.add_parser('freeze-panes'); freeze.add_argument('directory'); freeze.add_argument('--base', type=int, required=True); freeze.add_argument('--sheet', required=True); freeze.add_argument('--cell', required=True, help='Top-left scrollable cell, or A1 to unfreeze')
    grid_format = sub.add_parser('format-grid'); grid_format.add_argument('directory'); grid_format.add_argument('--base', type=int, required=True); grid_format.add_argument('--sheet', required=True); grid_format.add_argument('--range', required=True, dest='cell_range'); grid_format.add_argument('--style-range', required=True); grid_format.add_argument('--properties', required=True, help='JSON formatting object')
    track_replace = sub.add_parser('track-replace-text'); track_replace.add_argument('directory'); track_replace.add_argument('--base', type=int, required=True); track_replace.add_argument('--path', required=True); track_replace.add_argument('--find', required=True); track_replace.add_argument('--replace', required=True, dest='replacement'); track_replace.add_argument('--author', required=True)
    track_insert = sub.add_parser('track-insert-text'); track_insert.add_argument('directory'); track_insert.add_argument('--base', type=int, required=True); track_insert.add_argument('--path', required=True); track_insert.add_argument('--anchor', required=True); track_insert.add_argument('--text', required=True); track_insert.add_argument('--position', choices=('before', 'after'), required=True); track_insert.add_argument('--author', required=True)
    track_resolve = sub.add_parser('resolve-tracked-runs'); track_resolve.add_argument('directory'); track_resolve.add_argument('--base', type=int, required=True); track_resolve.add_argument('--part', required=True); track_resolve.add_argument('--id', action='append', required=True, dest='ids'); track_resolve.add_argument('--decision', choices=['accept', 'reject'], required=True)
    slide_inventory = sub.add_parser('inspect-slides'); slide_inventory.add_argument('directory'); slide_inventory.add_argument('--revision', type=int, required=True)
    reorder = sub.add_parser('reorder-slides'); reorder.add_argument('directory'); reorder.add_argument('--base', type=int, required=True); reorder.add_argument('--order', required=True, help='JSON array of one-based slide numbers')
    note_session = sub.add_parser('notes'); note_session.add_argument('directory'); note_session.add_argument('--revision', type=int, required=True); note_session.add_argument('--slide', type=int, required=True)
    note_compare = sub.add_parser('compare-notes'); note_compare.add_argument('directory'); note_compare.add_argument('--before', type=int, required=True); note_compare.add_argument('--after', type=int, required=True); note_compare.add_argument('--before-slide', type=int, required=True); note_compare.add_argument('--after-slide', type=int, required=True)
    note_write = sub.add_parser('replace-notes'); note_write.add_argument('directory'); note_write.add_argument('--base', type=int, required=True); note_write.add_argument('--slide', type=int, required=True); note_write.add_argument('--text-file', required=True)
    note_edit = sub.add_parser('replace-notes-text'); note_edit.add_argument('directory'); note_edit.add_argument('--base', type=int, required=True); note_edit.add_argument('--slide', type=int, required=True); note_edit.add_argument('--paragraph', type=int, required=True); note_edit.add_argument('--find', required=True); note_edit.add_argument('--replace', required=True, dest='replacement')
    reply = sub.add_parser('reply-comment'); reply.add_argument('directory'); reply.add_argument('--base', type=int, required=True); reply.add_argument('--parent-id', required=True); reply.add_argument('--text', required=True); reply.add_argument('--author', required=True)
    resolve = sub.add_parser('resolve-comment'); resolve.add_argument('directory'); resolve.add_argument('--base', type=int, required=True); resolve.add_argument('--id', required=True); resolve.add_argument('--resolved', choices=['true', 'false'], required=True)
    comment = sub.add_parser('add-comment'); comment.add_argument('directory'); comment.add_argument('--base', type=int, required=True); comment.add_argument('--path', required=True); comment.add_argument('--text', required=True); comment.add_argument('--author', required=True); comment.add_argument('--anchor')
    navigation = sub.add_parser('set-slide-navigation'); navigation.add_argument('directory'); navigation.add_argument('--base', type=int, required=True); navigation.add_argument('--path', required=True); nav_mode = navigation.add_mutually_exclusive_group(required=True); nav_mode.add_argument('--target-slide', type=int); nav_mode.add_argument('--remove', action='store_true'); navigation.add_argument('--expected-sha256')
    description = sub.add_parser('set-slide-description'); description.add_argument('directory'); description.add_argument('--base', type=int, required=True); description.add_argument('--path', required=True); description.add_argument('--description', required=True); description.add_argument('--expected-sha256')
    picture = sub.add_parser('replace-picture'); picture.add_argument('directory'); picture.add_argument('--base', type=int, required=True); picture.add_argument('--path', required=True); picture.add_argument('--image', required=True); picture.add_argument('--expected-sha256')
    session_review = sub.add_parser('review'); session_review.add_argument('directory'); session_review.add_argument('--revision', type=int, required=True); session_review.add_argument('--out-dir', required=True)
    session_comments = sub.add_parser('comments'); session_comments.add_argument('directory'); session_comments.add_argument('--revision', type=int, required=True)
    session_changes = sub.add_parser('tracked-changes'); session_changes.add_argument('directory'); session_changes.add_argument('--revision', type=int, required=True)
    session_stories = sub.add_parser('stories'); session_stories.add_argument('directory'); session_stories.add_argument('--revision', type=int, required=True)
    session_layout = sub.add_parser('inspect-layout'); session_layout.add_argument('directory'); session_layout.add_argument('--revision', type=int, required=True)
    session_nav = sub.add_parser('inspect-slide-navigation'); session_nav.add_argument('directory'); session_nav.add_argument('--revision', type=int, required=True)
    session_charts = sub.add_parser('inspect-slide-charts'); session_charts.add_argument('directory'); session_charts.add_argument('--revision', type=int, required=True)
    chart_color = sub.add_parser('set-slide-chart-text-color'); chart_color.add_argument('directory'); chart_color.add_argument('--base', type=int, required=True); chart_color.add_argument('--part', required=True); chart_color.add_argument('--color', required=True); chart_color.add_argument('--expected-sha256')
    literal_text = sub.add_parser('set-slide-chart-literal-text'); literal_text.add_argument('directory'); literal_text.add_argument('--base', type=int, required=True); literal_text.add_argument('--part', required=True); literal_text.add_argument('--kind', choices=('series_name','category'), required=True); literal_text.add_argument('--text', required=True); literal_text.add_argument('--series', type=int); literal_text.add_argument('--point', type=int); literal_text.add_argument('--expected-sha256')
    literal_edit = sub.add_parser('set-slide-chart-literal-value'); literal_edit.add_argument('directory'); literal_edit.add_argument('--base', type=int, required=True); literal_edit.add_argument('--part', required=True); literal_edit.add_argument('--series', type=int, required=True); literal_edit.add_argument('--point', type=int, required=True); literal_edit.add_argument('--value', type=float, required=True); literal_edit.add_argument('--expected-sha256')
    axis_edit = sub.add_parser('set-slide-chart-axis-bounds'); axis_edit.add_argument('directory'); axis_edit.add_argument('--base', type=int, required=True); axis_edit.add_argument('--part', required=True); axis_edit.add_argument('--axis-id', required=True); axis_edit.add_argument('--minimum', type=lambda value: None if value == 'auto' else float(value), required=True, help='Number or auto'); axis_edit.add_argument('--maximum', type=lambda value: None if value == 'auto' else float(value), required=True, help='Number or auto'); axis_edit.add_argument('--expected-sha256')
    slide_chart_sync = sub.add_parser('sync-slide-chart-cache'); slide_chart_sync.add_argument('directory'); slide_chart_sync.add_argument('--base', type=int, required=True); slide_chart_sync.add_argument('--part', required=True); slide_chart_sync.add_argument('--reference', type=int, required=True); slide_chart_sync.add_argument('--allow-formula-caches', action='store_true'); slide_chart_sync.add_argument('--expected-sha256')
    session_external = sub.add_parser('external-links'); session_external.add_argument('directory'); session_external.add_argument('--revision', type=int, required=True)
    session_slide_text = sub.add_parser('inspect-slide-text'); session_slide_text.add_argument('directory'); session_slide_text.add_argument('--revision', type=int, required=True)
    session_calc = sub.add_parser('recalculate'); session_calc.add_argument('directory'); session_calc.add_argument('--base', type=int, required=True); session_calc.add_argument('--allow-dynamic-arrays', action='store_true')
    session_scan = sub.add_parser('scan-formulas'); session_scan.add_argument('directory'); session_scan.add_argument('--base', type=int, required=True)
    session_chart_scan = sub.add_parser('scan-chart-caches'); session_chart_scan.add_argument('directory'); session_chart_scan.add_argument('--revision', type=int, required=True)
    session_chart_sync = sub.add_parser('sync-chart-cache'); session_chart_sync.add_argument('directory'); session_chart_sync.add_argument('--base', type=int, required=True); session_chart_sync.add_argument('--part', required=True); session_chart_sync.add_argument('--reference', type=int, required=True); session_chart_sync.add_argument('--allow-formula-caches', action='store_true'); session_chart_sync.add_argument('--expected-sha256')
    session_workbook = sub.add_parser('inspect-workbook'); session_workbook.add_argument('directory'); session_workbook.add_argument('--revision', type=int, required=True)
    session_search = sub.add_parser('search-cells'); session_search.add_argument('directory'); session_search.add_argument('--revision', type=int, required=True); session_search.add_argument('--query', required=True)
    session_search.add_argument('--sheet'); session_search.add_argument('--offset', type=int, default=0); session_search.add_argument('--snapshot-sha256')
    session_word_search = sub.add_parser('search-word'); session_word_search.add_argument('directory'); session_word_search.add_argument('--revision', type=int, required=True); session_word_search.add_argument('--query', required=True); session_word_search.add_argument('--offset', type=int, default=0); session_word_search.add_argument('--snapshot-sha256'); session_word_search.add_argument('--scope', choices=('body', 'stories', 'notes'), default='body')
    session_slide_search = sub.add_parser('search-slides'); session_slide_search.add_argument('directory'); session_slide_search.add_argument('--revision', type=int, required=True); session_slide_search.add_argument('--query', required=True); session_slide_search.add_argument('--slide', type=int); session_slide_search.add_argument('--offset', type=int, default=0); session_slide_search.add_argument('--snapshot-sha256'); session_slide_search.add_argument('--scope', choices=('slides', 'notes'), default='slides')
    restore = sub.add_parser('restore'); restore.add_argument('directory'); restore.add_argument('--base', type=int, required=True); restore.add_argument('--revision', type=int, required=True)
    export = sub.add_parser('export'); export.add_argument('directory'); export.add_argument('--revision', type=int, required=True); export.add_argument('--out', required=True)
    watcher = commands.add_parser('watch'); watcher.add_argument('directory'); watcher.add_argument('--port', type=int, default=0)
    commands.add_parser('mcp', help='Start the local MCP stdio server (requires the mcp extra)')
    args = parser.parse_args()
    try:
        if args.command == 'mcp':
            try:
                import office_mcp
            except ModuleNotFoundError as exc:
                if exc.name == 'mcp':
                    raise RuntimeError('Install the MCP extra from this checkout: pip install ./office[mcp]') from exc
                raise
            office_mcp.main()
            return 0
        if args.command == 'watch':
            import watch
            watch.serve(args.directory, preview, args.port, render)
            return 0
        if args.command == 'session':
            if args.action == 'start':
                result = session.start(args.directory, args.source, args.format)
            elif args.action == 'info':
                result = session.info(args.directory)
            elif args.action == 'dump':
                result = session.dump(args.directory, args.revision, args.path)
            elif args.action == 'selection':
                result = session.get_selection(args.directory)
            elif args.action == 'selection-text':
                result = selection_text.extract(args.directory, render)
            elif args.action == 'selection-candidates':
                result = selection_candidates.candidates(args.directory, render)
            elif args.action == 'replace-text':
                result = session.replace_text(args.directory, args.base, args.path, args.find, args.replacement)
            elif args.action == 'refresh-word-toc':
                result = session.refresh_word_toc(args.directory, args.base, args.path, args.expected_sha256)
            elif args.action == 'replace-text-batch':
                result = session.replace_text_batch(args.directory, args.base, json.loads(args.changes))
            elif args.action == 'compare-cells':
                result = session.compare_cells(args.directory, args.before, args.after, args.sheet, args.cell_range)
            elif args.action == 'read-slide-chart-grid':
                result = session.read_slide_chart_grid(args.directory, args.revision, args.part, args.sheet, args.cell_range)
            elif args.action == 'edit-slide-chart-grid':
                result = session.edit_slide_chart_grid(args.directory, args.base, args.part, args.sheet, args.cell_range, json.loads(args.changes), args.sync_caches)
            elif args.action == 'rename-table-column':
                result = session.rename_table_column(args.directory, args.base, args.sheet, args.table, args.old, args.new)
            elif args.action == 'set-grid-hyperlink':
                if (args.target_sheet is None) != (args.target_cell is None): raise ValueError('Internal links require --target-sheet and --target-cell')
                location = {'sheet': args.target_sheet, 'cell': args.target_cell} if args.target_sheet is not None else None
                result = session.set_grid_hyperlink(args.directory, args.base, args.sheet, args.cell, args.url, args.expected_sha256, location)
            elif args.action == 'edit-grid':
                result = session.edit_grid(args.directory, args.base, args.sheet, args.cell_range, json.loads(args.changes))
            elif args.action == 'resize-grid':
                result = session.resize_grid(args.directory, args.base, args.sheet, args.cell_range, args.target_range, args.column_width, args.row_height)
            elif args.action == 'merge-cells':
                result = session.merge_cells(args.directory, args.base, args.sheet, args.cell_range, not args.unmerge)
            elif args.action == 'freeze-panes':
                result = session.freeze_panes(args.directory, args.base, args.sheet, args.cell)
            elif args.action == 'format-grid':
                result = session.format_grid(args.directory, args.base, args.sheet, args.cell_range, args.style_range, json.loads(args.properties))
            elif args.action == 'track-insert-text':
                result = session.track_insert_text(args.directory, args.base, args.path, args.anchor, args.text, args.position, args.author)
            elif args.action == 'track-replace-text':
                result = session.track_replace_text(args.directory, args.base, args.path, args.find, args.replacement, args.author)
            elif args.action == 'resolve-tracked-runs':
                result = session.resolve_tracked_runs(args.directory, args.base, args.part, args.ids, args.decision == 'accept')
            elif args.action == 'inspect-slides':
                result = session.inventory_slides(args.directory, args.revision)
            elif args.action == 'reorder-slides':
                result = session.reorder_slides(args.directory, args.base, json.loads(args.order))
            elif args.action == 'notes':
                result = session.read_notes(args.directory, args.revision, args.slide)
            elif args.action == 'compare-notes':
                result = session.compare_notes(args.directory, args.before, args.after, args.before_slide, args.after_slide)
            elif args.action == 'replace-notes':
                if Path(args.text_file).stat().st_size > 400000: raise ValueError('Notes text file exceeds 400,000 bytes')
                result = session.replace_notes(args.directory, args.base, args.slide, Path(args.text_file).read_text(encoding='utf-8'))
            elif args.action == 'replace-notes-text':
                result = session.replace_notes_text(args.directory, args.base, args.slide, args.paragraph, args.find, args.replacement)
            elif args.action == 'reply-comment':
                result = session.reply_comment(args.directory, args.base, args.parent_id, args.text, args.author)
            elif args.action == 'resolve-comment':
                result = session.resolve_comment(args.directory, args.base, args.id, args.resolved == 'true')
            elif args.action == 'add-comment':
                result = session.add_comment(args.directory, args.base, args.path, args.text, args.author, args.anchor)
            elif args.action == 'set-slide-navigation':
                result = session.set_slide_navigation(args.directory, args.base, args.path, args.target_slide, args.expected_sha256)
            elif args.action == 'set-slide-description':
                result = session.set_slide_description(args.directory, args.base, args.path, args.description, args.expected_sha256)
            elif args.action == 'replace-picture':
                image_data = session.read_picture_file(args.image)
                result = session.replace_picture(args.directory, args.base, args.path, image_data, expected_sha256=args.expected_sha256)
            elif args.action == 'review':
                state = session.info(args.directory); source = session.revision_file(state, args.revision)
                if Path(args.out_dir).resolve().is_relative_to(Path(state['directory'])): raise ValueError('Review output must be outside the session directory')
                result = review_bundle.create(source, args.out_dir, render, args.revision)
            elif args.action == 'comments':
                result = session.list_comments(args.directory, args.revision)
            elif args.action == 'tracked-changes':
                result = session.tracked_changes(args.directory, args.revision)
            elif args.action == 'stories':
                result = session.list_stories(args.directory, args.revision)
            elif args.action == 'inspect-slide-text':
                result = session.inspect_slide_text(args.directory, args.revision, render)
            elif args.action == 'inspect-layout':
                result = session.inspect_layout(args.directory, args.revision)
            elif args.action == 'inspect-slide-navigation':
                result = session.inspect_slide_navigation(args.directory, args.revision)
            elif args.action == 'inspect-slide-charts':
                result = session.inspect_slide_charts(args.directory, args.revision)
            elif args.action == 'set-slide-chart-text-color':
                result = session.set_slide_chart_text_color(args.directory, args.base, args.part, args.color, args.expected_sha256)
            elif args.action == 'set-slide-chart-literal-text':
                result = session.set_slide_chart_literal_text(args.directory, args.base, args.part, args.kind, args.text, args.series, args.point, args.expected_sha256)
            elif args.action == 'set-slide-chart-literal-value':
                result = session.set_slide_chart_literal_value(args.directory, args.base, args.part, args.series, args.point, args.value, args.expected_sha256)
            elif args.action == 'set-slide-chart-axis-bounds':
                result = session.set_slide_chart_axis_bounds(args.directory, args.base, args.part, args.axis_id, args.minimum, args.maximum, args.expected_sha256)
            elif args.action == 'sync-slide-chart-cache':
                result = session.sync_slide_chart_cache(args.directory, args.base, args.part, args.reference, args.allow_formula_caches, args.expected_sha256)
            elif args.action == 'external-links':
                result = session.external_relationships(args.directory, args.revision)
            elif args.action == 'recalculate':
                result = session.recalculate(args.directory, args.base, args.allow_dynamic_arrays)
            elif args.action == 'scan-formulas':
                result = session.scan_formulas(args.directory, args.base)
            elif args.action == 'scan-chart-caches':
                result = session.scan_chart_caches(args.directory, args.revision)
            elif args.action == 'sync-chart-cache':
                result = session.sync_chart_cache(args.directory, args.base, args.part, args.reference, args.allow_formula_caches, args.expected_sha256)
            elif args.action == 'inspect-workbook':
                result = session.inspect_workbook(args.directory, args.revision)
            elif args.action == 'search-cells':
                result = session.search_cells(args.directory, args.revision, args.query, args.sheet, args.offset, args.snapshot_sha256)
            elif args.action == 'search-word':
                result = ({'body': session.search_body, 'stories': session.search_stories, 'notes': session.search_notes}[args.scope])(args.directory, args.revision, args.query, args.offset, args.snapshot_sha256)
            elif args.action == 'search-slides':
                result = session.search_slides(args.directory, args.revision, args.query, args.slide, args.offset, args.snapshot_sha256, args.scope)
            elif args.action == 'restore':
                result = session.restore(args.directory, args.base, args.revision)
            elif args.action == 'apply':
                with open(args.spec, encoding='utf-8') as f:
                    operations = json.load(f)
                result = session.apply(args.directory, args.base, operations)
            else:
                result = session.export(args.directory, args.revision, args.out)
        elif args.command == 'doctor':
            result = doctor()
        elif args.command == 'inspect':
            result = inspect(args.file)
        elif args.command == 'comments':
            result = word.list_comments(args.file)
        elif args.command == 'tracked-changes':
            result = word.tracked_changes(args.file)
        elif args.command == 'stories':
            result = word.list_stories(args.file)
        elif args.command == 'search-word':
            result = ({'body': word.search_body, 'stories': word.search_stories, 'notes': word.search_notes}[args.scope])(args.file, args.query, args.offset, args.snapshot_sha256)
        elif args.command == 'search-slides':
            result = slides.search_text(args.file, args.query, args.slide, args.offset, args.snapshot_sha256, args.scope)
        elif args.command == 'notes':
            result = notes.read(args.file, args.slide)
        elif args.command == 'inspect-slide-text':
            result = slide_text_check.scan(args.file, render)
        elif args.command == 'inspect-slides':
            result = slides.inventory(args.file)
        elif args.command == 'inspect-layout':
            result = layout.inspect(args.file)
        elif args.command == 'inspect-slide-navigation':
            result = slides.inspect_navigation(args.file)
        elif args.command == 'inspect-slide-charts':
            result = slide_charts.inspect(args.file)
        elif args.command == 'external-links':
            result = review.external_relationships(args.file)
        elif args.command == 'author':
            with open(args.spec, encoding='utf-8') as f:
                spec = json.load(f)
            result = {'output': author(spec, args.out, args.source)}
        elif args.command == 'render':
            result = render_with_info(args.file, args.out_dir)
        elif args.command == 'preview':
            result = render_with_info(args.file, args.out_dir, pages=True)
        elif args.command == 'render-page':
            result = visual.save_png(args.out, lambda: visual.page_image(args.file, args.page, render, args.box))
        elif args.command == 'compare-pages':
            result = visual.save_png(args.out, lambda: visual.compare_pages(args.before, args.after, args.before_page, args.after_page, render))
        elif args.command == 'contact-sheet':
            result = visual.save_contact_sheet(args.file, args.out, args.start, args.count, render)
        elif args.command == 'review-bundle':
            result = review_bundle.create(args.file, args.out_dir, render)
        elif args.command == 'audit':
            result = officecli_backend.audit(args.file)
        elif args.command == 'compare-cells':
            result = review.compare_cells(args.before, args.after, args.sheet, args.cell_range)
        elif args.command == 'compare':
            result = review.compare(args.before, args.after)
        elif args.command == 'compare-notes':
            result = review.compare_notes(args.before, args.after, args.before_slide, args.after_slide)
        elif args.command == 'cells':
            result = spreadsheet.read_range(args.file, args.sheet, args.cell_range)
        elif args.command == 'search-cells':
            result = spreadsheet.search_cells(args.file, args.query, args.sheet, args.offset, args.snapshot_sha256)
        elif args.command == 'scan-formulas':
            result = spreadsheet.scan_formulas(args.file)
        elif args.command == 'scan-chart-caches':
            result = chart_cache.scan(args.file)
        elif args.command == 'recalculate':
            result = {'output': spreadsheet.recalculate(args.file, args.out, args.allow_dynamic_arrays)}
        elif args.command == 'structured':
            if (args.mode == 'outline') != (args.target is None):
                raise ValueError('get and query require a target; outline takes no target')
            result = officecli_backend.read(args.file, args.mode, args.target)
        elif args.command == 'dump':
            result = officecli_backend.dump(args.file, args.path)
        elif args.command == 'schema':
            result = officecli_backend.schema(args.format, args.element, args.operation, args.query)
        else:
            with open(args.spec, encoding='utf-8') as f:
                operations = json.load(f)
            result = officecli_backend.batch(operations, args.out, args.source)
        print(json.dumps(result, ensure_ascii=False, default=str))
    except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'office-use: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
