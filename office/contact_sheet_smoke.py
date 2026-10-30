"""Verify rendered page order, pagination and safe output handling."""
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.dml.color import RGBColor

import open_office_use
import visual

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    deck = Presentation()
    for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)):
        slide = deck.slides.add_slide(deck.slide_layouts[6]); fill = slide.background.fill
        fill.solid(); fill.fore_color.rgb = RGBColor(*color)
    for _ in range(8): deck.slides.add_slide(deck.slide_layouts[6])
    source = root / 'slides.pptx'; deck.save(source)
    data, meta = visual.contact_sheet(source, 2, 2, open_office_use.render)
    assert meta == {'start_page': 2, 'end_page': 3, 'total_pages': 12}, meta
    sheet = Image.open(io.BytesIO(data)); assert sheet.size == (776, 360)
    assert sheet.getpixel((196, 170))[1] > 200 and sheet.getpixel((576, 170))[2] > 200
    assert visual.contact_sheet(source, 10, 12, open_office_use.render)[1]['end_page'] == 12
    output = root / 'contact.png'; cli = Path(__file__).with_name('open_office_use.py')
    subprocess.run([sys.executable, str(cli), 'contact-sheet', str(source), '--out', str(output), '--start', '12'], check=True, capture_output=True)
    original = output.read_bytes()
    try: visual.save_contact_sheet(source, output, 1, 2, open_office_use.render)
    except FileExistsError: pass
    else: raise AssertionError('Existing output overwritten')
    assert output.read_bytes() == original
    for start, count in ((0, 1), (13, 1), (1, 13)):
        try: visual.contact_sheet(source, start, count, open_office_use.render)
        except ValueError: pass
        else: raise AssertionError('Invalid range accepted')
    doc = Document(); doc.add_paragraph('Page one'); doc.add_page_break(); doc.add_paragraph('Page two'); doc_path = root / 'doc.docx'; doc.save(doc_path)
    assert visual.contact_sheet(doc_path, 2, 12, open_office_use.render)[1]['total_pages'] == 2
    book = Workbook(); book.active['A1'] = 'Workbook'; book_path = root / 'book.xlsx'; book.save(book_path)
    assert visual.contact_sheet(book_path, 1, 12, open_office_use.render)[1]['total_pages'] == 1
print('Contact sheet smoke passed: three formats, pagination, page order and output protection')
