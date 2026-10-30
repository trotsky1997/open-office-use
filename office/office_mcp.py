"""MCP access to the local office authoring workbench."""
from pathlib import Path
from io import BytesIO
import math
import tempfile

from PIL import Image as PILImage
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image

import officecli_backend
import spreadsheet
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
    """Find textual candidate element paths for the visual selection; verify each target before editing."""
    return selection_candidates.candidates(directory, render)


@server.tool()
def session_selection_image(directory: str) -> Image:
    """Render and return the selected region of the exact selected revision as PNG."""
    selection = session.get_selection(directory)
    state = session.info(directory)
    source = session.revision_file(state, selection['revision'])
    with tempfile.TemporaryDirectory(prefix='office-selection-') as tmp:
        pages = preview(source, Path(tmp) / 'pages')
        page = selection['page']
        if page > len(pages):
            raise ValueError('Selected page does not exist in this revision')
        with PILImage.open(pages[page - 1]) as image:
            x1, y1, x2, y2 = selection['box']
            box = (math.floor(x1 * image.width), math.floor(y1 * image.height),
                   math.ceil(x2 * image.width), math.ceil(y2 * image.height))
            result = BytesIO()
            image.crop(box).save(result, format='PNG')
    data = result.getvalue()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('Selected image exceeds 10 MiB')
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
    """Read one editable element in the latest revision before editing it."""
    return session.edit_target(directory, base_revision, path)


@server.tool()
def session_edit(directory: str, base_revision: int, path: str, mode: Literal['text', 'value', 'formula'], value: str) -> dict[str, Any]:
    """Set one element's text, cell value, or formula in a new revision; replacing text may change formatting."""
    return session.edit(directory, base_revision, path, mode, value)


@server.tool()
def session_apply(directory: str, base_revision: int, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply an OfficeCLI batch to the latest revision; reject concurrent or stale edits."""
    return session.apply(directory, base_revision, operations)


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
