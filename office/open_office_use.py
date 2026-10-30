"""Small local file-oriented office harness."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation

import layout
import visual
import word
import officecli_backend
import spreadsheet
import review
import review_bundle
import session
import selection_text
import selection_candidates


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
        wb = load_workbook(path, data_only=False)
        return {'type': 'xlsx', 'sheets': [{'name': ws.title, 'rows': [[cell.value for cell in row] for row in ws.iter_rows()] } for ws in wb.worksheets]}
    prs = Presentation(path)
    return {'type': 'pptx', 'slides': [[{'shape': i, 'text': shape.text} for i, shape in enumerate(slide.shapes) if shape.has_text_frame] for slide in prs.slides]}


def author(spec, output, source=None):
    suffix = kind(output)
    if source and kind(source) != suffix:
        raise ValueError('Source and output formats must match')
    out = Path(output)
    if out.exists():
        raise FileExistsError(f'Output already exists: {out}')
    if source and out.resolve() == Path(source).resolve():
        raise ValueError('Output must differ from source')
    if suffix == '.docx':
        doc = Document(source) if source else Document()
        for index, text in spec.get('replace_paragraphs', {}).items():
            # Setting paragraph text discards run-level formatting in that paragraph.
            doc.paragraphs[int(index)].text = text
        for text in spec.get('paragraphs', []):
            doc.add_paragraph(text)
        obj = doc
    elif suffix == '.xlsx':
        obj = load_workbook(source) if source else Workbook()
        for name, cells in spec.get('sheets', {}).items():
            ws = obj[name] if name in obj.sheetnames else obj.create_sheet(name)
            for address, value in cells.items():
                ws[address] = value
        if not source and 'Sheet' not in spec.get('sheets', {}) and len(obj.sheetnames) > 1:
            del obj['Sheet']
    else:
        obj = Presentation(source) if source else Presentation()
        for item in spec.get('replace_text', []):
            shape = obj.slides[item['slide']].shapes[item['shape']]
            if not shape.has_text_frame:
                raise ValueError('Selected shape has no text frame')
            shape.text = item['text']
        for item in spec.get('slides', []):
            slide = obj.slides.add_slide(obj.slide_layouts[1])
            slide.shapes.title.text = item['title']
            slide.placeholders[1].text = item.get('body', '')
    out.parent.mkdir(parents=True, exist_ok=True)
    # Save into the target directory, then exclusively create the requested output.
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        candidate = Path(tmp) / out.name
        obj.save(candidate)
        with out.open('xb') as destination, candidate.open('rb') as original:
            shutil.copyfileobj(original, destination)
    return str(out.resolve())


def render(source, output_dir):
    kind(source)
    source = Path(source).resolve(strict=True)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (source.stem + '.pdf')
    if target.exists():
        raise FileExistsError(f'Output already exists: {target}')
    executable = shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('LibreOffice (soffice) is required for rendering')
    with tempfile.TemporaryDirectory() as tmp:
        profile = (Path(tmp) / 'profile').as_uri()
        result = subprocess.run([executable, '-env:UserInstallation=' + profile, '--headless', '--convert-to', 'pdf', '--outdir', tmp, str(source)], capture_output=True, text=True, timeout=120, check=False)
        pdf = Path(tmp) / target.name
        if result.returncode or not pdf.is_file():
            raise RuntimeError(f'LibreOffice conversion failed: {result.stderr or result.stdout}')
        with target.open('xb') as out, pdf.open('rb') as inp:
            shutil.copyfileobj(inp, out)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    read = commands.add_parser('inspect'); read.add_argument('file')
    comments = commands.add_parser('comments'); comments.add_argument('file')
    layout_read = commands.add_parser('inspect-layout'); layout_read.add_argument('file')
    edit = commands.add_parser('author'); edit.add_argument('--spec', required=True); edit.add_argument('--out', required=True); edit.add_argument('--source')
    render_command = commands.add_parser('render'); render_command.add_argument('file'); render_command.add_argument('--out-dir', required=True)
    images = commands.add_parser('preview'); images.add_argument('file'); images.add_argument('--out-dir', required=True)
    page = commands.add_parser('render-page'); page.add_argument('file'); page.add_argument('--out', required=True); page.add_argument('--page', type=int, required=True); page.add_argument('--box', type=float, nargs=4)
    visual_compare = commands.add_parser('compare-pages'); visual_compare.add_argument('before'); visual_compare.add_argument('after'); visual_compare.add_argument('--before-page', type=int, required=True); visual_compare.add_argument('--after-page', type=int, required=True); visual_compare.add_argument('--out', required=True)
    contact = commands.add_parser('contact-sheet'); contact.add_argument('file'); contact.add_argument('--out', required=True); contact.add_argument('--start', type=int, default=1); contact.add_argument('--count', type=int, default=12)
    structured = commands.add_parser('structured'); structured.add_argument('file'); structured.add_argument('mode', choices=['outline', 'get', 'query']); structured.add_argument('target', nargs='?')
    batch = commands.add_parser('batch'); batch.add_argument('--spec', required=True); batch.add_argument('--out', required=True); batch.add_argument('--source')
    cells = commands.add_parser('cells'); cells.add_argument('file'); cells.add_argument('--sheet', required=True); cells.add_argument('--range', required=True, dest='cell_range')
    formula_scan = commands.add_parser('scan-formulas'); formula_scan.add_argument('file')
    calc = commands.add_parser('recalculate'); calc.add_argument('file'); calc.add_argument('--out', required=True)
    bundle = commands.add_parser('review-bundle'); bundle.add_argument('file'); bundle.add_argument('--out-dir', required=True)
    audit = commands.add_parser('audit'); audit.add_argument('file')
    comparison = commands.add_parser('compare'); comparison.add_argument('before'); comparison.add_argument('after')
    cell_diff = commands.add_parser('compare-cells'); cell_diff.add_argument('before'); cell_diff.add_argument('after'); cell_diff.add_argument('--sheet', required=True); cell_diff.add_argument('--range', required=True, dest='cell_range')
    draft = commands.add_parser('session'); sub = draft.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start'); start.add_argument('directory'); group = start.add_mutually_exclusive_group(required=True); group.add_argument('--source'); group.add_argument('--format', choices=['docx', 'xlsx', 'pptx'])
    state = sub.add_parser('info'); state.add_argument('directory')
    selection = sub.add_parser('selection'); selection.add_argument('directory')
    selected_text = sub.add_parser('selection-text'); selected_text.add_argument('directory')
    candidates = sub.add_parser('selection-candidates'); candidates.add_argument('directory')
    apply = sub.add_parser('apply'); apply.add_argument('directory'); apply.add_argument('--base', type=int, required=True); apply.add_argument('--spec', required=True)
    replace = sub.add_parser('replace-text'); replace.add_argument('directory'); replace.add_argument('--base', type=int, required=True); replace.add_argument('--path', required=True); replace.add_argument('--find', required=True); replace.add_argument('--replace', required=True, dest='replacement')
    reply = sub.add_parser('reply-comment'); reply.add_argument('directory'); reply.add_argument('--base', type=int, required=True); reply.add_argument('--parent-id', required=True); reply.add_argument('--text', required=True); reply.add_argument('--author', required=True)
    resolve = sub.add_parser('resolve-comment'); resolve.add_argument('directory'); resolve.add_argument('--base', type=int, required=True); resolve.add_argument('--id', required=True); resolve.add_argument('--resolved', choices=['true', 'false'], required=True)
    comment = sub.add_parser('add-comment'); comment.add_argument('directory'); comment.add_argument('--base', type=int, required=True); comment.add_argument('--path', required=True); comment.add_argument('--text', required=True); comment.add_argument('--author', required=True); comment.add_argument('--anchor')
    picture = sub.add_parser('replace-picture'); picture.add_argument('directory'); picture.add_argument('--base', type=int, required=True); picture.add_argument('--path', required=True); picture.add_argument('--image', required=True)
    session_review = sub.add_parser('review'); session_review.add_argument('directory'); session_review.add_argument('--revision', type=int, required=True); session_review.add_argument('--out-dir', required=True)
    session_comments = sub.add_parser('comments'); session_comments.add_argument('directory'); session_comments.add_argument('--revision', type=int, required=True)
    session_layout = sub.add_parser('inspect-layout'); session_layout.add_argument('directory'); session_layout.add_argument('--revision', type=int, required=True)
    session_calc = sub.add_parser('recalculate'); session_calc.add_argument('directory'); session_calc.add_argument('--base', type=int, required=True)
    session_scan = sub.add_parser('scan-formulas'); session_scan.add_argument('directory'); session_scan.add_argument('--base', type=int, required=True)
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
            elif args.action == 'selection':
                result = session.get_selection(args.directory)
            elif args.action == 'selection-text':
                result = selection_text.extract(args.directory, render)
            elif args.action == 'selection-candidates':
                result = selection_candidates.candidates(args.directory, render)
            elif args.action == 'replace-text':
                result = session.replace_text(args.directory, args.base, args.path, args.find, args.replacement)
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
            elif args.action == 'inspect-layout':
                result = session.inspect_layout(args.directory, args.revision)
            elif args.action == 'recalculate':
                result = session.recalculate(args.directory, args.base)
            elif args.action == 'scan-formulas':
                result = session.scan_formulas(args.directory, args.base)
            elif args.action == 'restore':
                result = session.restore(args.directory, args.base, args.revision)
            elif args.action == 'apply':
                with open(args.spec, encoding='utf-8') as f:
                    operations = json.load(f)
                result = session.apply(args.directory, args.base, operations)
            else:
                result = session.export(args.directory, args.revision, args.out)
        elif args.command == 'inspect':
            result = inspect(args.file)
        elif args.command == 'comments':
            result = word.list_comments(args.file)
        elif args.command == 'inspect-layout':
            result = layout.inspect(args.file)
        elif args.command == 'author':
            with open(args.spec, encoding='utf-8') as f:
                spec = json.load(f)
            result = {'output': author(spec, args.out, args.source)}
        elif args.command == 'render':
            result = {'pdf': render(args.file, args.out_dir)}
        elif args.command == 'preview':
            result = {'pages': preview(args.file, args.out_dir)}
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
        elif args.command == 'cells':
            result = spreadsheet.read_range(args.file, args.sheet, args.cell_range)
        elif args.command == 'scan-formulas':
            result = spreadsheet.scan_formulas(args.file)
        elif args.command == 'recalculate':
            result = {'output': spreadsheet.recalculate(args.file, args.out)}
        elif args.command == 'structured':
            if (args.mode == 'outline') != (args.target is None):
                raise ValueError('get and query require a target; outline takes no target')
            result = officecli_backend.read(args.file, args.mode, args.target)
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
