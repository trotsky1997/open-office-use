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
from pathlib import Path
from urllib.parse import urlsplit

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.shared import Inches as DocxInches, RGBColor as DocxRGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.data_source import AxDataSource, StrRef, StrData, StrVal, NumData, NumVal
from openpyxl.styles import PatternFill
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.utils.cell import column_index_from_string, range_boundaries
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from PIL import Image

import layout
import slide_text_check
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


def append_word_blocks(doc, blocks):
    """Append ordered semantic Word content from a bounded JSON list."""
    if not isinstance(blocks, list) or len(blocks) > 200:
        raise ValueError('Word blocks must be a list of at most 200 items')
    if len(json.dumps(blocks, ensure_ascii=False)) > 2000000:
        raise ValueError('Word blocks exceed the 2,000,000-character limit')
    image_bytes = 0
    for block in blocks:
        if not isinstance(block, dict): raise ValueError('Each Word block must be an object')
        kind = block.get('type')
        if kind == 'table':
            if set(block) - {'type', 'rows', 'header', 'style'}: raise ValueError('Unsupported Word table property')
            rows = block.get('rows'); header = block.get('header', False); style = block.get('style')
            if not isinstance(rows, list) or not 1 <= len(rows) <= 100 or not all(isinstance(row, list) for row in rows): raise ValueError('A table requires 1 to 100 rows')
            width = len(rows[0])
            if not 1 <= width <= 20 or len(rows) * width > 2000 or any(len(row) != width for row in rows): raise ValueError('A table requires a rectangular grid of at most 2,000 cells and 20 columns')
            if any(not isinstance(value, str) or len(value) > 10000 for row in rows for value in row): raise ValueError('Table cells must be text of at most 10,000 characters')
            if not isinstance(header, bool): raise ValueError('Table header must be a boolean')
            if style is not None:
                if not isinstance(style, str): raise ValueError('Table style must be a name')
                try: selected = doc.styles[style]
                except KeyError: raise ValueError(f'Word table style not found: {style}') from None
                if selected.type != WD_STYLE_TYPE.TABLE: raise ValueError('The selected style is not a table style')
            table = doc.add_table(rows=len(rows), cols=width)
            if style is not None: table.style = style
            cells = table._cells
            for row_index, values in enumerate(rows):
                for column_index, value in enumerate(values):
                    cell = cells[row_index * width + column_index]; cell.text = value
                    if header and row_index == 0:
                        for run in cell.paragraphs[0].runs: run.bold = True
            if header:
                properties = table.rows[0]._tr.get_or_add_trPr()
                marker = OxmlElement('w:tblHeader'); marker.set(qn('w:val'), 'true'); properties.append(marker)
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
            allowed = {'type', 'text', 'runs'} | ({'level'} if kind == 'heading' else set())
            if set(block) - allowed or ('text' in block) == ('runs' in block): raise ValueError('Provide text or runs for each Word text block')
            level = block.get('level', 1)
            if kind == 'heading' and (isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9): raise ValueError('Heading level must be 1 to 9')
            runs = [{'text': block['text']}] if 'text' in block else block['runs']
            if not isinstance(runs, list) or not 1 <= len(runs) <= 200: raise ValueError('Word runs must contain 1 to 200 items')
            for run in runs:
                if not isinstance(run, dict) or set(run) - {'text', 'bold', 'italic', 'underline', 'url'} or not isinstance(run.get('text'), str) or len(run['text']) > 10000 or any(key in run and not isinstance(run[key], bool) for key in ('bold', 'italic', 'underline')):
                    raise ValueError('Each run requires text and optional boolean bold, italic or underline')
                if 'url' in run:
                    url = run['url']
                    if not isinstance(url, str) or len(url) > 2048 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url): raise ValueError('Invalid hyperlink URL')
                    try: parsed = urlsplit(url)
                    except ValueError: raise ValueError('Invalid hyperlink URL') from None
                    if parsed.scheme.lower() not in ('http', 'https', 'mailto') or (parsed.scheme.lower() in ('http', 'https') and not parsed.hostname) or (parsed.scheme.lower() == 'mailto' and not parsed.path): raise ValueError('Hyperlink must be an HTTP, HTTPS or mailto URL')
            if kind == 'heading': paragraph = doc.add_heading(level=level)
            else: paragraph = doc.add_paragraph(style={'bullet': 'List Bullet', 'numbered': 'List Number'}.get(kind))
            for run in runs:
                target = paragraph.add_run(run['text'])
                if 'url' in run:
                    target.font.color.rgb = DocxRGBColor.from_string('0563C1'); target.underline = True
                for name in ('bold', 'italic', 'underline'):
                    if name in run: setattr(target, name, run[name])
                if 'url' in run:
                    link = OxmlElement('w:hyperlink'); link.set(qn('r:id'), doc.part.relate_to(run['url'], RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
                    link.append(target._r); paragraph._p.append(link)
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
    image_bytes = 0
    for item in slides:
        if not isinstance(item, dict) or set(item) - {'layout', 'title', 'body', 'background', 'elements'}: raise ValueError('Invalid slide properties')
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
        if 'background' in item:
            fill = slide.background.fill; fill.solid(); fill.fore_color.rgb = color(item['background'])
        elements = item.get('elements', [])
        if not isinstance(elements, list) or len(elements) > 200: raise ValueError('Slide elements must be a list of at most 200 items')
        for element in elements:
            if not isinstance(element, dict): raise ValueError('Slide elements must be objects')
            kind = element.get('type'); geometry = {'type', 'x', 'y', 'width', 'height'}
            allowed = {'textbox': geometry | {'text', 'font_size', 'font', 'color', 'bold', 'italic', 'align', 'fill'},
                       'rectangle': geometry | {'fill'}, 'image': geometry | {'path', 'description', 'fit'},
                       'table': geometry | {'rows', 'header', 'font_size', 'font', 'color', 'header_fill', 'header_color', 'column_weights'}}
            if not isinstance(kind, str) or kind not in allowed or set(element) - allowed[kind]: raise ValueError('Unsupported slide element or property')
            x = Inches(number(element.get('x'), 'x', -100, 100)); y = Inches(number(element.get('y'), 'y', -100, 100))
            width = Inches(number(element.get('width'), 'width', 0.01, 100)); height = Inches(number(element.get('height'), 'height', 0.01, 100))
            if kind == 'textbox':
                text = element.get('text')
                if not isinstance(text, str) or len(text) > 10000: raise ValueError('Textbox text must be at most 10,000 characters')
                for key in ('bold', 'italic'):
                    if key in element and not isinstance(element[key], bool): raise ValueError(f'{key} must be a boolean')
                if 'font' in element and (not isinstance(element['font'], str) or not 1 <= len(element['font']) <= 100): raise ValueError('Font must be a name of at most 100 characters')
                alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}
                if 'align' in element and (not isinstance(element['align'], str) or element['align'] not in alignment): raise ValueError('Alignment must be left, center or right')
                if 'font_size' in element: number(element['font_size'], 'font_size', 1, 400)
                shape = slide.shapes.add_textbox(x, y, width, height); shape.text = text; shape.text_frame.word_wrap = True
                if 'fill' in element: shape.fill.solid(); shape.fill.fore_color.rgb = color(element['fill'])
                for paragraph in shape.text_frame.paragraphs:
                    if 'align' in element: paragraph.alignment = alignment[element['align']]
                    for run in paragraph.runs:
                        font = run.font
                        if 'font_size' in element: font.size = Pt(element['font_size'])
                        if 'font' in element: font.name = element['font']
                        if 'color' in element: font.color.rgb = color(element['color'])
                        for key in ('bold', 'italic'):
                            if key in element: setattr(font, key, element[key])
            elif kind == 'rectangle':
                if 'fill' not in element: raise ValueError('Rectangle requires a fill color')
                shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, width, height)
                shape.fill.solid(); shape.fill.fore_color.rgb = color(element['fill']); shape.line.fill.background()
            elif kind == 'table':
                rows = element.get('rows'); header = element.get('header', False)
                if not isinstance(rows, list) or not 1 <= len(rows) <= 50 or any(not isinstance(row, list) for row in rows): raise ValueError('Slide table requires 1 to 50 rows')
                columns = len(rows[0])
                if not 1 <= columns <= 20 or len(rows) * columns > 500 or any(len(row) != columns for row in rows): raise ValueError('Slide table must be rectangular with at most 500 cells and 20 columns')
                if any(not isinstance(value, str) or len(value) > 10000 for row in rows for value in row): raise ValueError('Slide table cells must be text of at most 10,000 characters')
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
                table = slide.shapes.add_table(len(rows), columns, x, y, width, height).table
                table.first_row = header
                if weights is not None:
                    total = sum(weights); previous = 0; cumulative = 0
                    for index, weight in enumerate(weights):
                        cumulative += weight; end = width if index == columns - 1 else round(width * cumulative / total)
                        if end <= previous: raise ValueError('Column weights produce a zero-width column')
                        table.columns[index].width = end - previous; previous = end
                for row_index, values in enumerate(rows):
                    for column_index, text in enumerate(values):
                        cell = table.cell(row_index, column_index); cell.text = text; cell.text_frame.word_wrap = True
                        is_header = header and row_index == 0
                        if is_header and 'header_fill' in element: cell.fill.solid(); cell.fill.fore_color.rgb = color(element['header_fill'])
                        for paragraph in cell.text_frame.paragraphs:
                            for run in paragraph.runs:
                                if 'font_size' in element: run.font.size = Pt(element['font_size'])
                                if 'font' in element: run.font.name = element['font']
                                ink = element.get('header_color') if is_header and 'header_color' in element else element.get('color')
                                if ink is not None: run.font.color.rgb = color(ink)
                                if is_header: run.font.bold = True
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


def format_workbook(workbook, options):
    """Apply bounded presentation settings to an authored workbook."""
    if not isinstance(options, dict) or len(options) > 100: raise ValueError('Sheet options must be an object with at most 100 sheets')
    total_cells = 0; chart_cache_bytes = 0; chart_cache_points = 0
    # shortcut: cache bounded, nonempty literal text or finite numbers; calculated and ambiguous values require recalculation.
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
        if not isinstance(setting, dict) or set(setting) - {'freeze_panes', 'auto_filter', 'column_widths', 'row_heights', 'formats', 'charts', 'fit_to_page'}: raise ValueError('Invalid worksheet options')
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
        charts = setting.get('charts', [])
        if not isinstance(charts, list) or len(charts) > 20: raise ValueError('Charts must be a list of at most 20 entries')
        for chart_spec in charts:
            allowed = {'type', 'data', 'categories', 'anchor', 'title', 'x_axis_title', 'y_axis_title', 'titles_from_data', 'category_type', 'width', 'height'}
            if not isinstance(chart_spec, dict) or set(chart_spec) - allowed or chart_spec.get('type') not in ('column', 'line'): raise ValueError('Invalid chart specification')
            a, b, c, d = bounds(chart_spec.get('data'), 10000)
            headings = chart_spec.get('titles_from_data', True)
            if not isinstance(headings, bool) or d - b + 1 <= int(headings) or c - a + 1 > 30: raise ValueError('Chart data requires at least one data row and at most 30 series')
            anchor = chart_spec.get('anchor', 'E2')
            if not isinstance(anchor, str) or not re.fullmatch(r'[A-Za-z]{1,3}[1-9][0-9]{0,6}', anchor): raise ValueError('Chart anchor must be a single cell')
            bounds(anchor, 1)
            category_type = chart_spec.get('category_type', 'auto')
            if category_type not in ('auto', 'text', 'number') or category_type != 'auto' and 'categories' not in chart_spec: raise ValueError('Category type requires categories and must be auto, text or number')
            labels = None; text_categories = False
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
            for key in ('title', 'x_axis_title', 'y_axis_title'):
                if key in chart_spec and (not isinstance(chart_spec[key], str) or len(chart_spec[key]) > 255): raise ValueError('Chart titles must be text of at most 255 characters')
            chart = BarChart() if chart_spec['type'] == 'column' else LineChart()
            if chart_spec['type'] == 'column': chart.type = 'col'
            chart.add_data(Reference(sheet, min_col=a, min_row=b, max_col=c, max_row=d), titles_from_data=headings)
            if labels is not None:
                if text_categories:
                    for series in chart.series: series.cat = AxDataSource(strRef=StrRef(f=str(labels)))
                else: chart.set_categories(labels)
            for index, series in enumerate(chart.series):
                if headings and series.tx and series.tx.strRef:
                    series.tx.strRef.strCache = chart_cache([sheet.cell(row=b, column=a + index)], True)
                values = [sheet.cell(row=row, column=a + index) for row in range(b + int(headings), d + 1)]
                series.val.numRef.numCache = chart_cache(values, False)
                if labels is not None:
                    if text_categories: series.cat.strRef.strCache = chart_cache(category_cells, True)
                    else: series.cat.numRef.numCache = chart_cache(category_cells, False)
            if 'title' in chart_spec: chart.title = chart_spec['title']
            if 'x_axis_title' in chart_spec: chart.x_axis.title = chart_spec['x_axis_title']
            if 'y_axis_title' in chart_spec: chart.y_axis.title = chart_spec['y_axis_title']
            if 'width' in chart_spec: chart.width = amount(chart_spec['width'], 'chart width', 100)
            if 'height' in chart_spec: chart.height = amount(chart_spec['height'], 'chart height', 100)
            sheet.add_chart(chart, anchor.upper())


def author(spec, output, source=None):
    if not isinstance(spec, dict): raise ValueError('Author specification must be a JSON object')
    suffix = kind(output)
    if 'blocks' in spec and suffix != '.docx': raise ValueError('Word blocks require DOCX output')
    if 'slide_size' in spec and suffix != '.pptx': raise ValueError('Slide size requires PPTX output')
    if 'sheet_options' in spec and suffix != '.xlsx': raise ValueError('Sheet options require XLSX output')
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
            for index, text in spec.get('replace_paragraphs', {}).items():
                # Setting paragraph text discards run-level formatting in that paragraph.
                doc.paragraphs[int(index)].text = text
            for text in spec.get('paragraphs', []):
                doc.add_paragraph(text)
            if 'blocks' in spec: append_word_blocks(doc, spec['blocks'])
            obj = doc
        elif suffix == '.xlsx':
            obj = spreadsheet.load_author_workbook(source) if source else Workbook()
            for name, cells in spec.get('sheets', {}).items():
                ws = obj[name] if name in obj.sheetnames else obj.create_sheet(name)
                for address, value in cells.items():
                    if not isinstance(value, str) or not value.startswith('='): spreadsheet.validate_cell_value(value)
                    ws[address] = value
            if not source and 'Sheet' not in spec.get('sheets', {}) and len(obj.sheetnames) > 1:
                del obj['Sheet']
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
    layout_read = commands.add_parser('inspect-layout'); layout_read.add_argument('file')
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
    replace_batch = sub.add_parser('replace-text-batch'); replace_batch.add_argument('directory'); replace_batch.add_argument('--base', type=int, required=True); replace_batch.add_argument('--changes', required=True, help='JSON array of path/find/replacement objects')
    session_cell_diff = sub.add_parser('compare-cells'); session_cell_diff.add_argument('directory'); session_cell_diff.add_argument('--before', type=int, required=True); session_cell_diff.add_argument('--after', type=int, required=True); session_cell_diff.add_argument('--sheet', required=True); session_cell_diff.add_argument('--range', required=True, dest='cell_range')
    grid_edit = sub.add_parser('edit-grid'); grid_edit.add_argument('directory'); grid_edit.add_argument('--base', type=int, required=True); grid_edit.add_argument('--sheet', required=True); grid_edit.add_argument('--range', required=True, dest='cell_range'); grid_edit.add_argument('--changes', required=True, help='JSON array of cell/value objects')
    grid_resize = sub.add_parser('resize-grid'); grid_resize.add_argument('directory'); grid_resize.add_argument('--base', type=int, required=True); grid_resize.add_argument('--sheet', required=True); grid_resize.add_argument('--range', required=True, dest='cell_range'); grid_resize.add_argument('--target-range', required=True); grid_resize.add_argument('--column-width', type=float); grid_resize.add_argument('--row-height', type=float)
    merge = sub.add_parser('merge-cells'); merge.add_argument('directory'); merge.add_argument('--base', type=int, required=True); merge.add_argument('--sheet', required=True); merge.add_argument('--range', required=True, dest='cell_range'); merge.add_argument('--unmerge', action='store_true')
    freeze = sub.add_parser('freeze-panes'); freeze.add_argument('directory'); freeze.add_argument('--base', type=int, required=True); freeze.add_argument('--sheet', required=True); freeze.add_argument('--cell', required=True, help='Top-left scrollable cell, or A1 to unfreeze')
    grid_format = sub.add_parser('format-grid'); grid_format.add_argument('directory'); grid_format.add_argument('--base', type=int, required=True); grid_format.add_argument('--sheet', required=True); grid_format.add_argument('--range', required=True, dest='cell_range'); grid_format.add_argument('--style-range', required=True); grid_format.add_argument('--properties', required=True, help='JSON formatting object')
    track_replace = sub.add_parser('track-replace-text'); track_replace.add_argument('directory'); track_replace.add_argument('--base', type=int, required=True); track_replace.add_argument('--path', required=True); track_replace.add_argument('--find', required=True); track_replace.add_argument('--replace', required=True, dest='replacement'); track_replace.add_argument('--author', required=True)
    track_insert = sub.add_parser('track-insert-text'); track_insert.add_argument('directory'); track_insert.add_argument('--base', type=int, required=True); track_insert.add_argument('--path', required=True); track_insert.add_argument('--anchor', required=True); track_insert.add_argument('--text', required=True); track_insert.add_argument('--position', choices=('before', 'after'), required=True); track_insert.add_argument('--author', required=True)
    track_resolve = sub.add_parser('resolve-tracked-runs'); track_resolve.add_argument('directory'); track_resolve.add_argument('--base', type=int, required=True); track_resolve.add_argument('--part', required=True); track_resolve.add_argument('--id', action='append', required=True, dest='ids'); track_resolve.add_argument('--decision', choices=['accept', 'reject'], required=True)
    note_session = sub.add_parser('notes'); note_session.add_argument('directory'); note_session.add_argument('--revision', type=int, required=True); note_session.add_argument('--slide', type=int, required=True)
    note_compare = sub.add_parser('compare-notes'); note_compare.add_argument('directory'); note_compare.add_argument('--before', type=int, required=True); note_compare.add_argument('--after', type=int, required=True); note_compare.add_argument('--before-slide', type=int, required=True); note_compare.add_argument('--after-slide', type=int, required=True)
    note_write = sub.add_parser('replace-notes'); note_write.add_argument('directory'); note_write.add_argument('--base', type=int, required=True); note_write.add_argument('--slide', type=int, required=True); note_write.add_argument('--text-file', required=True)
    note_edit = sub.add_parser('replace-notes-text'); note_edit.add_argument('directory'); note_edit.add_argument('--base', type=int, required=True); note_edit.add_argument('--slide', type=int, required=True); note_edit.add_argument('--paragraph', type=int, required=True); note_edit.add_argument('--find', required=True); note_edit.add_argument('--replace', required=True, dest='replacement')
    reply = sub.add_parser('reply-comment'); reply.add_argument('directory'); reply.add_argument('--base', type=int, required=True); reply.add_argument('--parent-id', required=True); reply.add_argument('--text', required=True); reply.add_argument('--author', required=True)
    resolve = sub.add_parser('resolve-comment'); resolve.add_argument('directory'); resolve.add_argument('--base', type=int, required=True); resolve.add_argument('--id', required=True); resolve.add_argument('--resolved', choices=['true', 'false'], required=True)
    comment = sub.add_parser('add-comment'); comment.add_argument('directory'); comment.add_argument('--base', type=int, required=True); comment.add_argument('--path', required=True); comment.add_argument('--text', required=True); comment.add_argument('--author', required=True); comment.add_argument('--anchor')
    picture = sub.add_parser('replace-picture'); picture.add_argument('directory'); picture.add_argument('--base', type=int, required=True); picture.add_argument('--path', required=True); picture.add_argument('--image', required=True)
    session_review = sub.add_parser('review'); session_review.add_argument('directory'); session_review.add_argument('--revision', type=int, required=True); session_review.add_argument('--out-dir', required=True)
    session_comments = sub.add_parser('comments'); session_comments.add_argument('directory'); session_comments.add_argument('--revision', type=int, required=True)
    session_changes = sub.add_parser('tracked-changes'); session_changes.add_argument('directory'); session_changes.add_argument('--revision', type=int, required=True)
    session_stories = sub.add_parser('stories'); session_stories.add_argument('directory'); session_stories.add_argument('--revision', type=int, required=True)
    session_layout = sub.add_parser('inspect-layout'); session_layout.add_argument('directory'); session_layout.add_argument('--revision', type=int, required=True)
    session_external = sub.add_parser('external-links'); session_external.add_argument('directory'); session_external.add_argument('--revision', type=int, required=True)
    session_slide_text = sub.add_parser('inspect-slide-text'); session_slide_text.add_argument('directory'); session_slide_text.add_argument('--revision', type=int, required=True)
    session_calc = sub.add_parser('recalculate'); session_calc.add_argument('directory'); session_calc.add_argument('--base', type=int, required=True); session_calc.add_argument('--allow-dynamic-arrays', action='store_true')
    session_scan = sub.add_parser('scan-formulas'); session_scan.add_argument('directory'); session_scan.add_argument('--base', type=int, required=True)
    session_chart_scan = sub.add_parser('scan-chart-caches'); session_chart_scan.add_argument('directory'); session_chart_scan.add_argument('--revision', type=int, required=True)
    session_chart_sync = sub.add_parser('sync-chart-cache'); session_chart_sync.add_argument('directory'); session_chart_sync.add_argument('--base', type=int, required=True); session_chart_sync.add_argument('--part', required=True); session_chart_sync.add_argument('--reference', type=int, required=True); session_chart_sync.add_argument('--allow-formula-caches', action='store_true')
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
            elif args.action == 'replace-text-batch':
                result = session.replace_text_batch(args.directory, args.base, json.loads(args.changes))
            elif args.action == 'compare-cells':
                result = session.compare_cells(args.directory, args.before, args.after, args.sheet, args.cell_range)
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
            elif args.action == 'replace-picture':
                image = Path(args.image)
                if image.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError('Image must be at most 10 MiB')
                result = session.replace_picture(args.directory, args.base, args.path, image.read_bytes())
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
            elif args.action == 'external-links':
                result = session.external_relationships(args.directory, args.revision)
            elif args.action == 'recalculate':
                result = session.recalculate(args.directory, args.base, args.allow_dynamic_arrays)
            elif args.action == 'scan-formulas':
                result = session.scan_formulas(args.directory, args.base)
            elif args.action == 'scan-chart-caches':
                result = session.scan_chart_caches(args.directory, args.revision)
            elif args.action == 'sync-chart-cache':
                result = session.sync_chart_cache(args.directory, args.base, args.part, args.reference, args.allow_formula_caches)
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
        elif args.command == 'inspect-layout':
            result = layout.inspect(args.file)
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
