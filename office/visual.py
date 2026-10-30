"""Bounded, page-numbered visual overviews for Office documents."""
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def pdf_page_count(pdf):
    info = shutil.which('pdfinfo')
    if not info:
        raise RuntimeError('Poppler pdfinfo is required for page rendering')
    result = subprocess.run([info, str(pdf)], capture_output=True, text=True, timeout=120, check=False,
                            env={**os.environ, 'LC_ALL': 'C'})
    match = re.search(r'^Pages:\s*(\d+)\s*$', result.stdout, re.MULTILINE)
    if result.returncode or not match:
        raise RuntimeError('Could not determine rendered PDF page count')
    return int(match.group(1))


def page_image(source, page, render, box=None):
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 1_000_000:
        raise ValueError('Page must be an integer from 1 to 1,000,000')
    if box is not None:
        if (not isinstance(box, (list, tuple)) or len(box) != 4 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box) or
                not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
            raise ValueError('Box must contain normalized left, top, right, bottom coordinates')
    raster = shutil.which('pdftoppm')
    if not raster:
        raise RuntimeError('Poppler pdftoppm is required for page rendering')
    with tempfile.TemporaryDirectory(prefix='office-page-') as tmp:
        root = Path(tmp); pdf = render(source, root / 'pdf'); total = pdf_page_count(pdf)
        if page > total:
            raise ValueError(f'Page exceeds rendered page count ({total})')
        result = subprocess.run([raster, '-f', str(page), '-l', str(page), '-singlefile', '-scale-to', '1800',
                                 '-png', pdf, str(root / 'page')], capture_output=True, text=True, timeout=120, check=False)
        png = root / 'page.png'
        if result.returncode or not png.is_file():
            raise RuntimeError(f'Page rendering failed: {result.stderr or result.stdout}')
        with Image.open(png) as image:
            page_size = [image.width, image.height]
        scale = 1800
        if box is not None:
            x1, y1, x2, y2 = box
            extent = max((x2 - x1) * page_size[0], (y2 - y1) * page_size[1])
            # shortcut: limit the full-page raster scale to 7200; increase only with a stronger resource bound.
            scale = 7200 if extent <= 450 else max(1800, math.floor(1800 * 1800 / extent))
            ratio = scale / 1800
            left = math.floor(x1 * page_size[0] * ratio); top = math.floor(y1 * page_size[1] * ratio)
            right = math.ceil(x2 * page_size[0] * ratio); bottom = math.ceil(y2 * page_size[1] * ratio)
            result = subprocess.run([raster, '-f', str(page), '-l', str(page), '-singlefile', '-scale-to', str(scale),
                                     '-x', str(left), '-y', str(top), '-W', str(right - left), '-H', str(bottom - top),
                                     '-png', pdf, str(root / 'crop')], capture_output=True, text=True, timeout=120, check=False)
            png = root / 'crop.png'
            if result.returncode or not png.is_file():
                raise RuntimeError(f'Page crop rendering failed: {result.stderr or result.stdout}')
        with Image.open(png) as image:
            image_size = [image.width, image.height]
            output = io.BytesIO(); image.save(output, format='PNG')
        data = output.getvalue()
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('Rendered page exceeds 10 MiB')
        return data, {'page': page, 'total_pages': total, 'page_size': page_size, 'image_size': image_size, 'box': box, 'raster_scale': scale}


def contact_sheet(source, start, count, render):
    if isinstance(start, bool) or not isinstance(start, int) or start < 1 or start > 1_000_000:
        raise ValueError('Start page must be an integer from 1 to 1,000,000')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
        raise ValueError('Page count must be an integer from 1 to 12')
    raster = shutil.which('pdftoppm')
    if not raster:
        raise RuntimeError('Poppler pdftoppm is required for contact sheets')
    with tempfile.TemporaryDirectory(prefix='office-contact-sheet-') as tmp:
        root = Path(tmp); pdf = render(source, root / 'pdf')
        total = pdf_page_count(pdf)
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


def save_png(output, generate):
    output = Path(output).absolute()
    if output.suffix.lower() != '.png':
        raise ValueError('Image output must be a PNG file')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    data, details = generate()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-image-') as tmp:
        candidate = Path(tmp) / 'image.png'; candidate.write_bytes(data)
        os.link(candidate, output)
    return {'output': str(output), **details}


def save_contact_sheet(source, output, start, count, render):
    return save_png(output, lambda: contact_sheet(source, start, count, render))
