"""MCP access to the local office authoring workbench."""
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image

import officecli_backend
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
