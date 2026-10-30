"""Extract text from a revision-bound visual selection via rendered PDF."""
import math
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import session
import spreadsheet


def extract(directory, render):
    selection = session.get_selection(directory)
    state = session.info(directory)
    source = session.revision_file(state, selection['revision'])
    executable = shutil.which('pdftotext')
    if not executable:
        raise RuntimeError('Poppler pdftotext is required for selected text')
    with tempfile.TemporaryDirectory(prefix='office-selection-text-') as tmp:
        pdf = render(source, Path(tmp) / 'pdf')
        page_count = None
        if source.suffix.lower() == '.pptx' and shutil.which('pdfinfo'):
            try:
                info = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True, timeout=120,
                                      check=False, env={**os.environ, 'LC_ALL': 'C'})
                match = re.search(r'^Pages:\s*(\d+)\s*$', info.stdout, re.MULTILINE)
                if info.returncode == 0 and match:
                    page_count = int(match.group(1))
            except (OSError, subprocess.TimeoutExpired):
                pass
        output = Path(tmp) / 'words.xhtml'
        result = subprocess.run([executable, '-f', str(selection['page']), '-l', str(selection['page']),
                                 '-bbox-layout', pdf, str(output)], capture_output=True, text=True,
                                timeout=120, check=False)
        if result.returncode or not output.is_file():
            raise RuntimeError(f'PDF text extraction failed: {result.stderr or result.stdout}')
        if output.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Selected page text exceeds the 8 MiB extraction limit')
        try:
            document = ET.parse(output)
            pages = [e for e in document.iter() if e.tag.rsplit('}', 1)[-1] == 'page']
            if len(pages) != 1:
                raise ValueError('Selected page was not found')
            page = pages[0]
            width, height = float(page.attrib['width']), float(page.attrib['height'])
            if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
                raise ValueError('Invalid PDF page dimensions')
            bounds = selection['box']
            lines, words = [], []
            truncated = False
            for line in (e for e in page.iter() if e.tag.rsplit('}', 1)[-1] == 'line'):
                line_words = []
                for word in (e for e in line if e.tag.rsplit('}', 1)[-1] == 'word'):
                    x1, y1 = float(word.attrib['xMin']) / width, float(word.attrib['yMin']) / height
                    x2, y2 = float(word.attrib['xMax']) / width, float(word.attrib['yMax']) / height
                    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
                    if bounds[0] <= center_x <= bounds[2] and bounds[1] <= center_y <= bounds[3]:
                        if len(words) >= 5000:
                            truncated = True
                            break
                        value = ''.join(word.itertext())
                        words.append({'text': value, 'box': [x1, y1, x2, y2]})
                        line_words.append(value)
                if line_words:
                    lines.append(' '.join(line_words))
                if truncated:
                    break
        except (ET.ParseError, KeyError, TypeError) as exc:
            raise RuntimeError(f'Invalid PDF text geometry: {exc}') from exc
    current = session.get_selection(directory); latest = current['latest_revision']
    return {'revision': selection['revision'], 'page': selection['page'], 'box': selection['box'],
            'latest_revision': latest, 'stale': selection['revision'] != latest, 'selection_changed': any(selection[key] != current[key] for key in ('revision', 'page', 'box')),
            'render_advisory': spreadsheet.render_advisory(source),
            'text': '\n'.join(lines), 'words': words, 'truncated': truncated,
            'pdf_page_count': page_count, 'pdf_page_size': [width, height],
            'method': 'pdf_word_centers'}
