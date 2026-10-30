"""Bounded, page-numbered visual overviews for Office documents."""
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def contact_sheet(source, start, count, render):
    if isinstance(start, bool) or not isinstance(start, int) or start < 1 or start > 1_000_000:
        raise ValueError('Start page must be an integer from 1 to 1,000,000')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
        raise ValueError('Page count must be an integer from 1 to 12')
    info = shutil.which('pdfinfo'); raster = shutil.which('pdftoppm')
    if not info or not raster:
        raise RuntimeError('Poppler pdfinfo and pdftoppm are required for contact sheets')
    with tempfile.TemporaryDirectory(prefix='office-contact-sheet-') as tmp:
        root = Path(tmp); pdf = render(source, root / 'pdf')
        result = subprocess.run([info, pdf], capture_output=True, text=True, timeout=120, check=False,
                                env={**os.environ, 'LC_ALL': 'C'})
        match = re.search(r'^Pages:\s*(\d+)\s*$', result.stdout, re.MULTILINE)
        if result.returncode or not match:
            raise RuntimeError('Could not determine rendered PDF page count')
        total = int(match.group(1))
        if start > total:
            raise ValueError(f'Start page exceeds rendered page count ({total})')
        end = min(total, start + count - 1)
        result = subprocess.run([raster, '-f', str(start), '-l', str(end), '-scale-to', '360', '-png', pdf, str(root / 'page')],
                                capture_output=True, text=True, timeout=120, check=False)
        pages = sorted(root.glob('page-*.png'))
        page_numbers = [int(page.stem.removeprefix('page-')) for page in pages if page.stem.removeprefix('page-').isdigit()]
        if result.returncode or page_numbers != list(range(start, end + 1)):
            raise RuntimeError(f'Page rendering failed: {result.stderr or result.stdout}')
        columns = min(3, len(pages)); rows = (len(pages) + columns - 1) // columns
        cell_width, cell_height, margin, header = 380, 300, 16, 44
        sheet = Image.new('RGB', (margin + columns * cell_width, header + rows * cell_height + margin), '#e9edf2')
        draw = ImageDraw.Draw(sheet)
        try: font = ImageFont.load_default(size=16)
        except TypeError: font = ImageFont.load_default()
        draw.text((margin, 12), f'Rendered pages {start}-{end} of {total}', fill='#1f2937', font=font)
        for index, page in enumerate(pages):
            x = margin + (index % columns) * cell_width; y = header + (index // columns) * cell_height
            with Image.open(page) as image:
                image.thumbnail((360, 260), Image.Resampling.LANCZOS)
                x_image = x + (360 - image.width) // 2; y_image = y + (260 - image.height) // 2
                sheet.paste(image.convert('RGB'), (x_image, y_image))
                draw.rectangle((x_image, y_image, x_image + image.width - 1, y_image + image.height - 1), outline='#9ca3af')
            draw.text((x, y + 266), f'Page {start + index}', fill='#1f2937', font=font)
        output = io.BytesIO(); sheet.save(output, format='PNG')
        return output.getvalue(), {'start_page': start, 'end_page': end, 'total_pages': total}


def save_contact_sheet(source, output, start, count, render):
    output = Path(output).absolute()
    if output.suffix.lower() != '.png':
        raise ValueError('Contact sheet output must be a PNG file')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    data, details = contact_sheet(source, start, count, render)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-contact-sheet-') as tmp:
        candidate = Path(tmp) / 'contact.png'; candidate.write_bytes(data)
        os.link(candidate, output)
    return {'output': str(output), **details}
