"""Compare slide text boxes with text extracted from a rendered PDF."""
import hashlib
import math
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import layout
import visual


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())



def validate_package(source):
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist(); names = [item.filename for item in entries]
        if len(entries) > 5000 or len(set(names)) != len(names) or sum(item.file_size for item in entries) > 128 * 1024 * 1024:
            raise ValueError('Presentation exceeds package limits or contains duplicate parts')

def inspect(source, pdf):
    source = Path(source)
    if source.suffix.lower() != '.pptx': raise ValueError('Slide text inspection requires PPTX')
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Presentation exceeds the 128 MiB limit')
    validate_package(source)
    presentation = Presentation(source); slides = presentation.slides
    width, height = presentation.slide_width, presentation.slide_height
    if not width or not height or width <= 0 or height <= 0: raise ValueError('Invalid slide size')
    page_count = visual.pdf_page_count(pdf)
    visibility = [slide._element.get('show') for slide in slides]
    reasons = []
    if any(value not in (None, '1', 'true') for value in visibility): reasons.append('hidden_or_unknown_slide_visibility')
    if page_count != len(slides): reasons.append('page_count_mismatch')
    if len(slides) > 100: reasons.append('slide_limit')
    result = {'slides_total': len(slides), 'pdf_pages': page_count, 'mapping_valid': not reasons,
              'mapping_issues': reasons, 'shapes_scanned': 0, 'text_shapes_checked': 0,
              'skipped_count': 0, 'skipped': [], 'skipped_truncated': False, 'candidate_count': 0, 'candidates': [], 'candidates_truncated': False, 'complete': False,
              'notes': ['Candidates compare source text with extracted PDF text within the shape bounds; inspect the rendered page.',
                        'Font encoding, overlapping objects, line order, clipping and renderer differences affect results. Masters, layouts, tables, groups and OCR are outside this check.']}
    if reasons: return result
    executable = shutil.which('pdftotext')
    if not executable: raise RuntimeError('Poppler pdftotext is required for slide text inspection')
    with tempfile.TemporaryDirectory(prefix='office-slide-text-') as tmp:
        output = Path(tmp) / 'text.xhtml'
        command = subprocess.run([executable, '-bbox-layout', str(pdf), str(output)], capture_output=True, text=True, timeout=120)
        if command.returncode or not output.is_file(): raise RuntimeError(f'PDF text extraction failed: {command.stderr[:1000]}')
        if output.stat().st_size > 32 * 1024 * 1024: raise ValueError('PDF text extraction exceeds 32 MiB')
        try: pages = [node for node in ET.parse(output).getroot().iter() if node.tag.rsplit('}', 1)[-1] == 'page']
        except ET.ParseError as exc: raise ValueError('Invalid PDF text extraction') from exc
    if len(pages) != len(slides): raise ValueError('PDF text extraction has an unexpected page count')
    checks = 0
    def skip(slide, path, reason):
        result['skipped_count'] += 1
        if len(result['skipped']) < 200: result['skipped'].append({'slide': slide, 'path_hint': path, 'reason': reason})
    stop = False
    for index, (slide, page) in enumerate(zip(slides, pages), 1):
        try: pw, ph = float(page.attrib['width']), float(page.attrib['height'])
        except (ValueError, KeyError) as exc: raise ValueError('Invalid PDF page dimensions') from exc
        if not math.isfinite(pw) or not math.isfinite(ph) or pw <= 0 or ph <= 0 or abs(pw / ph - width / height) > 0.01:
            result['mapping_valid'] = False; result['mapping_issues'].append('page_aspect_mismatch'); result['candidates'] = []; result['candidate_count'] = 0; result['text_shapes_checked'] = 0; return result
        words = []
        for node in page.iter():
            if node.tag.rsplit('}', 1)[-1] != 'word': continue
            try: box = [float(node.attrib[name]) for name in ('xMin', 'yMin', 'xMax', 'yMax')]
            except (KeyError, ValueError) as exc: raise ValueError('Invalid PDF word bounds') from exc
            if not all(math.isfinite(value) for value in box): raise ValueError('Invalid PDF word bounds')
            words.append(((box[0] + box[2]) / (2 * pw), (box[1] + box[3]) / (2 * ph), ''.join(node.itertext())))
        for shape in slide.shapes:
            if result['shapes_scanned'] >= 10000: skip(index, None, 'shape_limit'); stop = True; break
            result['shapes_scanned'] += 1
            metadata = next(shape._element.iter(layout.P + 'cNvPr'), None)
            if metadata is not None and metadata.get('hidden') in ('1', 'true'): continue
            path = f'/slide[{index}]/shape[@id={shape.shape_id}]'
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP: skip(index, path, 'group'); continue
            if shape.has_table: skip(index, path, 'table'); continue
            if not shape.has_text_frame or not shape.text_frame.text.strip(): continue
            if shape.rotation or shape.left is None or shape.top is None or not shape.width or not shape.height:
                skip(index, path, 'rotated_or_empty_bounds'); continue
            text = shape.text_frame.text
            if len(text) > 10000: skip(index, path, 'text_limit'); continue
            expected = normalize(text)
            if not expected: skip(index, path, 'no_comparable_characters'); continue
            if checks + len(words) > 2000000: skip(index, path, 'comparison_limit'); stop = True; break
            checks += len(words)
            x1, y1 = shape.left / width, shape.top / height
            x2, y2 = (shape.left + shape.width) / width, (shape.top + shape.height) / height
            extracted = normalize(' '.join(text for x, y, text in words if x1 <= x <= x2 and y1 <= y <= y2))
            result['text_shapes_checked'] += 1
            if expected not in extracted:
                result['candidate_count'] += 1
                if len(result['candidates']) < 200:
                    result['candidates'].append({'slide': index, 'path_hint': path, 'name': str(shape.name or '')[:200], 'source_text': text[:200], 'source_text_truncated': len(text) > 200,
                                                 'bounds': [x1, y1, x2, y2], 'extracted_text': extracted[:200]})
        if stop: break
    result['complete'] = not result['skipped_count'] and result['mapping_valid']
    result['candidates_truncated'] = result['candidate_count'] > len(result['candidates'])
    result['skipped_truncated'] = result['skipped_count'] > len(result['skipped'])
    return result


def scan(source, render):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.pptx' or source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Provide a PPTX within the 128 MiB limit')
    with tempfile.TemporaryDirectory(prefix='office-slide-text-snapshot-') as tmp:
        snapshot = Path(tmp) / 'snapshot.pptx'; shutil.copyfile(source, snapshot)
        if snapshot.stat().st_size > 128 * 1024 * 1024: raise ValueError('Presentation exceeds the 128 MiB limit')
        digest = hashlib.sha256()
        with snapshot.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        digest = digest.hexdigest()
        validate_package(snapshot)
        pdf = render(snapshot, Path(tmp) / 'render')
        return {'snapshot_sha256': digest, **inspect(snapshot, pdf)}
