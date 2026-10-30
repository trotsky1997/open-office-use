"""MCP access to the local office authoring workbench."""
from pathlib import Path

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image

import officecli_backend
import spreadsheet
import layout
import visual
import word
import review
import session
import selection_text
import selection_candidates
from open_office_use import inspect, preview, render

server = FastMCP(
    'open-office-use',
    instructions='Use structured_read to find element paths, then apply_batch to create a new file. '
                 'Save and close external OfficeCLI sessions before using a source. '
                 'Render and inspect page images before delivering an artifact.',
)


@server.tool()
def inspect_file(file: str) -> dict[str, Any]:
    """Extract basic text and cell content from a DOCX, XLSX, or PPTX file."""
    return inspect(file)


@server.tool()
def structured_read(file: str, mode: Literal['outline', 'get', 'query'], target: str | None = None) -> dict[str, Any]:
    """Read an outline, element path, or selector through OfficeCLI. get/query require target."""
    if (mode == 'outline') != (target is None):
        raise ValueError('get and query require a target; outline takes no target')
    return {'data': officecli_backend.read(file, mode, target)}


@server.tool()
def apply_batch(output: str, operations: list[dict[str, Any]], source: str | None = None) -> dict[str, Any]:
    """Apply OfficeCLI operations to a new file or a saved source copy. Existing output is protected."""
    return officecli_backend.batch(operations, output, source)


@server.tool()
def start_session(directory: str, source: str | None = None, format: Literal['docx', 'xlsx', 'pptx'] | None = None) -> dict[str, Any]:
    """Start a session in a new directory, from a saved source or a blank format."""
    return session.start(directory, source, format)


@server.tool()
def session_info(directory: str) -> dict[str, Any]:
    """List immutable revision files and the latest revision number."""
    return session.info(directory)


@server.tool()
def session_selection(directory: str) -> dict[str, Any]:
    """Read the latest saved visual selection, its revision and whether it is stale."""
    return session.get_selection(directory)


@server.tool()
def session_selection_text(directory: str) -> dict[str, Any]:
    """Extract PDF text whose word centers fall in the saved visual selection, including revision and bounds."""
    return selection_text.extract(directory, render)


@server.tool()
def session_selection_candidates(directory: str) -> dict[str, Any]:
    """Find text and, when available, PowerPoint geometric candidates for a visual selection; verify each target."""
    return selection_candidates.candidates(directory, render)


@server.tool()
def session_selection_image(directory: str) -> Image:
    """Render and return the selected region of the exact selected revision as PNG."""
    selection = session.get_selection(directory)
    state = session.info(directory)
    source = session.revision_file(state, selection['revision'])
    data, _ = visual.page_image(source, selection['page'], render, selection['box'])
    return Image(data=data, format='png')


@server.tool()
def session_sheets(directory: str, base_revision: int) -> dict[str, Any]:
    """List worksheet names in the latest saved XLSX session revision."""
    return session.sheet_names(directory, base_revision)


@server.tool()
def session_read_grid(directory: str, base_revision: int, sheet: str, cell_range: str) -> dict[str, Any]:
    """Read up to 200 cells for version-bound grid editing."""
    return session.read_grid(directory, base_revision, sheet, cell_range)


@server.tool()
def session_edit_grid(directory: str, base_revision: int, sheet: str, cell_range: str, changes: list[dict[str, str]]) -> dict[str, Any]:
    """Apply changed cell values or formulas atomically in a new revision."""
    return session.edit_grid(directory, base_revision, sheet, cell_range, changes)


@server.tool()
def session_format_grid(directory: str, base_revision: int, sheet: str, cell_range: str, style_range: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Apply bold, RGB fill or number format to cells in a version-bound range."""
    return session.format_grid(directory, base_revision, sheet, cell_range, style_range, properties)


@server.tool()
def session_edit_target(directory: str, base_revision: int, path: str) -> dict[str, Any]:
    """Read one element in the latest revision, including replacement eligibility."""
    return session.edit_target(directory, base_revision, path)


@server.tool()
def session_edit(directory: str, base_revision: int, path: str, mode: Literal['text', 'value', 'formula'], value: str) -> dict[str, Any]:
    """Set one element's text, cell value, or formula in a new revision; replacing text may change formatting."""
    return session.edit(directory, base_revision, path, mode, value)


@server.tool()
def session_replace_text(directory: str, base_revision: int, path: str, find: str, replacement: str) -> dict[str, Any]:
    """Replace one unique text match in supported Word, PowerPoint or Excel text, retaining formatting."""
    return session.replace_text(directory, base_revision, path, find, replacement)


@server.tool()
def list_word_comments(file: str) -> dict[str, Any]:
    """List Word comments, bounded body anchor hints and available Word 2013 thread metadata."""
    return word.list_comments(file)


@server.tool()
def session_list_comments(directory: str, revision: int) -> dict[str, Any]:
    """List comments from an exact DOCX session revision and report main-body anchor hints."""
    return session.list_comments(directory, revision)


@server.tool()
def session_reply_comment(directory: str, base_revision: int, parent_id: str, text: str, author: str) -> dict[str, Any]:
    """Reply to a supported open root Word comment and create a new revision."""
    return session.reply_comment(directory, base_revision, parent_id, text, author)


@server.tool()
def session_resolve_comment(directory: str, base_revision: int, comment_id: str, resolved: bool) -> dict[str, Any]:
    """Resolve or reopen a root Word comment as a new revision; ambiguous metadata is rejected."""
    return session.resolve_comment(directory, base_revision, comment_id, resolved)


@server.tool()
def session_add_comment(directory: str, base_revision: int, path: str, text: str, author: str, anchor: str | None = None) -> dict[str, Any]:
    """Add a Word comment to a paragraph or unique literal anchor and create a new revision."""
    return session.add_comment(directory, base_revision, path, text, author, anchor)


@server.tool()
def session_replace_picture(directory: str, base_revision: int, path: str, image_file: str) -> dict[str, Any]:
    """Replace a PPTX picture with a local PNG or JPEG, preserving its geometry and crop."""
    image = Path(image_file).resolve(strict=True)
    if image.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Image must be at most 10 MiB')
    return session.replace_picture(directory, base_revision, path, image.read_bytes())


@server.tool()
def session_apply(directory: str, base_revision: int, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply an OfficeCLI batch to the latest revision; reject concurrent or stale edits."""
    return session.apply(directory, base_revision, operations)


@server.tool()
def session_inspect_slide_layout(directory: str, revision: int) -> dict[str, Any]:
    """Inspect geometric layout candidates in a saved PPTX session revision."""
    return session.inspect_layout(directory, revision)


@server.tool()
def session_recalculate(directory: str, base_revision: int) -> dict[str, Any]:
    """Recalculate a saved XLSX revision with LibreOffice and publish a new revision."""
    return session.recalculate(directory, base_revision)


@server.tool()
def session_scan_formulas(directory: str, base_revision: int) -> dict[str, Any]:
    """Scan saved formulas and error caches in the latest XLSX revision."""
    return session.scan_formulas(directory, base_revision)


@server.tool()
def session_restore(directory: str, base_revision: int, revision: int) -> dict[str, Any]:
    """Copy a historical revision into a new latest revision; reject stale or concurrent writes."""
    return session.restore(directory, base_revision, revision)


@server.tool()
def session_export(directory: str, revision: int, output: str) -> dict[str, Any]:
    """Export a revision to a new file outside the session directory."""
    return session.export(directory, revision, output)


@server.tool()
def audit_file(file: str) -> dict[str, Any]:
    """Check a saved Office file using OfficeCLI schema validation and its issues view."""
    return officecli_backend.audit(file)


@server.tool()
def inspect_slide_layout(file: str) -> dict[str, Any]:
    """Report off-slide and overlapping-text geometric candidates in a saved PPTX."""
    return layout.inspect(file)


@server.tool()
def compare_files(before: str, after: str) -> dict[str, Any]:
    """Compare saved Office files: changed package parts and a bounded text-view diff."""
    return review.compare(before, after)


@server.tool()
def compare_cells(before: str, after: str, sheet: str, cell_range: str) -> dict[str, Any]:
    """Compare formulas, cached values and direct cell formatting in a bounded XLSX range."""
    return review.compare_cells(before, after, sheet, cell_range)


@server.tool()
def read_cells(file: str, sheet: str, cell_range: str) -> dict[str, Any]:
    """Read up to 10,000 cells, including formulas and stored cached values; freshness is unknown."""
    return spreadsheet.read_range(file, sheet, cell_range)


@server.tool()
def scan_formulas(file: str) -> dict[str, Any]:
    """Scan stored formulas and error values across a saved XLSX; cache freshness is unknown."""
    return spreadsheet.scan_formulas(file)


@server.tool()
def recalculate_workbook(file: str, output: str) -> dict[str, str]:
    """Recalculate an XLSX with LibreOffice and write a new file; conversion may affect fidelity."""
    return {'output': spreadsheet.recalculate(file, output)}


@server.tool()
def render_pdf(file: str, output_dir: str) -> dict[str, str]:
    """Render an Office file to a new PDF using LibreOffice."""
    return {'pdf': render(file, output_dir)}


@server.tool()
def preview_pages(file: str, output_dir: str) -> dict[str, list[str]]:
    """Render page PNGs into a new directory using LibreOffice and Poppler."""
    return {'pages': preview(file, output_dir)}


@server.tool()
def view_document_page(file: str, page: int, box: list[float] | None = None) -> Image:
    """View one rendered PDF page, optionally cropped to normalized [left, top, right, bottom]."""
    data, _ = visual.page_image(file, page, render, box)
    return Image(data=data, format='png')


@server.tool()
def session_view_page(directory: str, revision: int, page: int, box: list[float] | None = None) -> Image:
    """View one page of an exact session revision, optionally cropped to normalized page coordinates."""
    state = session.info(directory)
    source = session.revision_file(state, revision)
    data, _ = visual.page_image(source, page, render, box)
    return Image(data=data, format='png')


@server.tool()
def compare_page_images(before: str, after: str, before_page: int, after_page: int) -> Image:
    """Compare rendered pages visually; red shows RGB differences of at least 16/255."""
    data, _ = visual.compare_pages(before, after, before_page, after_page, render)
    return Image(data=data, format='png')


@server.tool()
def session_compare_page_images(directory: str, before_revision: int, after_revision: int, before_page: int, after_page: int) -> Image:
    """Compare rendered pages from two exact session revisions; red marks visible pixel differences."""
    state = session.info(directory)
    before = session.revision_file(state, before_revision)
    after = session.revision_file(state, after_revision)
    data, _ = visual.compare_pages(before, after, before_page, after_page, render)
    return Image(data=data, format='png')


@server.tool()
def view_contact_sheet(file: str, start_page: int = 1, count: int = 12) -> Image:
    """Render up to 12 numbered pages as a PNG overview. Page numbers refer to rendered PDF pages."""
    data, _ = visual.contact_sheet(file, start_page, count, render)
    return Image(data=data, format='png')


@server.tool()
def session_contact_sheet(directory: str, revision: int, start_page: int = 1, count: int = 12) -> Image:
    """Render a numbered overview of an exact session revision, up to 12 PDF pages."""
    state = session.info(directory)
    source = session.revision_file(state, revision)
    data, _ = visual.contact_sheet(source, start_page, count, render)
    return Image(data=data, format='png')


@server.tool()
def view_page(file: str) -> Image:
    """Return a PNG page preview as an image for visual inspection, up to 10 MiB."""
    path = Path(file)
    with path.open('rb') as image:
        data = image.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Expected a PNG image no larger than 10 MiB')
    return Image(data=data, format='png')


def main():
    server.run(transport='stdio')
