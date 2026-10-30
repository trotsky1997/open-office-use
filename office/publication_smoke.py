"""Check that failed or competing publications do not leave partial outputs."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from docx import Document
import open_office_use

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); target = root / 'report.docx'
    def fail_document(source, output):
        assert Document(source).paragraphs[0].text == 'complete'
        assert not Path(output).exists()
        raise OSError('simulated publication failure')
    with patch('open_office_use.os.link', side_effect=fail_document):
        try: open_office_use.author({'paragraphs': ['complete']}, target)
        except OSError: pass
        else: raise AssertionError('publication failure was ignored')
    assert not target.exists() and list(root.iterdir()) == []
    open_office_use.author({'paragraphs': ['complete']}, target)
    pdf_dir = root / 'pdf'; pdf_dir.mkdir(); pdf = pdf_dir / 'report.pdf'
    def fail_pdf(source, output):
        assert Path(source).read_bytes().startswith(b'%PDF') and not Path(output).exists()
        raise OSError('simulated publication failure')
    with patch('open_office_use.os.link', side_effect=fail_pdf):
        try: open_office_use.render(target, pdf_dir)
        except OSError: pass
        else: raise AssertionError('PDF publication failure was ignored')
    assert not pdf.exists() and list(pdf_dir.iterdir()) == []
    real_link = os.link
    def race(source, output):
        Path(output).write_bytes(b'other writer')
        real_link(source, output)
    with patch('open_office_use.os.link', side_effect=race):
        try: open_office_use.render(target, pdf_dir)
        except FileExistsError: pass
        else: raise AssertionError('competing PDF was overwritten')
    assert pdf.read_bytes() == b'other writer' and list(pdf_dir.iterdir()) == [pdf]
    previous = Path.cwd()
    try:
        os.chdir(root)
        relative_pdf = Path(open_office_use.render(target, 'relative-pdf'))
        assert relative_pdf.read_bytes().startswith(b'%PDF')
    finally: os.chdir(previous)
print('Publication smoke passed: complete candidates, failed links and competing output')
