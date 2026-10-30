"""MCP access to the local office authoring workbench."""
from pathlib import Path
import json

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import CallToolResult, TextContent
from pydantic import StrictFloat, StrictInt

import officecli_backend
import chart_cache
import spreadsheet
import layout
import notes
import visual
import word
import review
import review_bundle
import session
import selection_text
import selection_candidates
import slides
import slide_text_check
import slide_charts
from open_office_use import author, doctor, inspect, render, render_with_info

server = FastMCP(
    'open-office-use',
    instructions='Use office_schema to discover operations and properties, structured_read to find element paths, then apply_batch to create a new file. '
                 'Save and close external OfficeCLI sessions before using a source. '
                 'Render and inspect page images before delivering an artifact.',
)


def image_result(data, details):
    warnings = []
    for field, label in (('render_advisory', 'Rendered workbook'), ('before_render_advisory', 'Before workbook'), ('after_render_advisory', 'After workbook')):
        advisory = details.get(field)
        if advisory and advisory.get('dynamic_array_metadata') is not False:
            state = 'has dynamic-array metadata' if advisory.get('dynamic_array_metadata') is True else 'has unverified dynamic-array metadata'
            warnings.append(f'{label} {state}; LibreOffice may omit spill results. Review in a compatible application.')
    details = {**details, 'warnings': warnings}
    return CallToolResult(content=[Image(data=data, format='png').to_image_content(), TextContent(type='text', text=json.dumps(details, ensure_ascii=False))], structuredContent=details)


@server.tool()
def office_doctor() -> dict[str, Any]:
    """Probe local authoring and preview dependencies; results do not verify fidelity."""
    return doctor()


@server.tool()
def office_schema(format: Literal['docx', 'xlsx', 'pptx'], element: str | None = None, operation: Literal['add', 'set', 'get', 'query', 'remove'] | None = None, query: str | None = None) -> dict[str, Any]:
    """Discover installed OfficeCLI elements or inspect an element's properties and examples."""
    return officecli_backend.schema(format, element, operation, query)


@server.tool()
def inspect_file(file: str) -> dict[str, Any]:
    """Extract basic content; XLSX uses bounded sparse cell samples and reports scan limits."""
    return inspect(file)


@server.tool()
def author_file(spec: dict[str, Any], output: str, source: str | None = None) -> dict[str, str]:
    """Create a new file from a simple spec: DOCX {paragraphs: [text], blocks: [ordered table_of_contents, heading, paragraph, bullet, numbered, table, image or page_break objects]}, XLSX {sheets: {name: {cell: value}}, sheet_options: {name: {freeze_panes, auto_filter, column_widths, row_heights, formats, charts, fit_to_page}}}, or PPTX {slides: [{title, body}]}. PPTX also supports slide_size and blank slides with positioned textbox, rectangle, shape, line, connector, table, chart and image elements, with optional description text, one-based target_slide navigation on elements and rich text runs, and image fit stretch, contain or cover. Slide charts support column/bar/line/pie types, text categories, numeric series with embedded workbook data, optional show_values labels, text_color, and value_axis_min/value_axis_max for non-pie charts. Pie charts accept one nonnegative series, point_colors, and show_percent labels. Word TOC fields in new documents cache headings without page numbers and need updating in an editor after pagination. Word text blocks use text or runs, including HTTP(S)/mailto links; headings accept level 1–9, tables accept rectangular string rows, and image blocks embed local PNG/JPEG with width and description. With source, also supports DOCX replace_paragraphs and PPTX replace_text. Output must not exist. XLSX typed hyperlink values use literal display text and HTTP(S)/mailto or workbook cell targets; formulas are saved without calculation; basic column and line charts reference worksheet data; bounded literal data gets chart caches, while formula and ambiguous values may leave caches missing. Whole-element replacement and library saves can change rich formatting, formula caches and features."""
    return {'output': author(spec, output, source)}


@server.tool()
def inspect_external_relationships(file: str) -> dict[str, Any]:
    """List bounded external OPC relationships from a saved file without opening targets."""
    return review.external_relationships(file)


@server.tool()
def session_inspect_external_relationships(directory: str, revision: int) -> dict[str, Any]:
    """List external OPC relationships in a session revision without opening targets."""
    return session.external_relationships(directory, revision)


@server.tool()
def session_inspect_workbook(directory: str, revision: int) -> dict[str, Any]:
    """Inspect a bounded sparse sample of an exact XLSX session revision."""
    return session.inspect_workbook(directory, revision)


@server.tool()
def search_cells(file: str, query: str, sheet: str | None = None, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search XLSX text and formulas. Continue with next_offset and snapshot_sha256, keeping query and sheet unchanged."""
    return spreadsheet.search_cells(file, query, sheet, offset, snapshot_sha256)


@server.tool()
def session_search_cells(directory: str, revision: int, query: str, sheet: str | None = None, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search an exact XLSX revision; continue with next_offset and snapshot_sha256, keeping query and sheet unchanged."""
    return session.search_cells(directory, revision, query, sheet, offset, snapshot_sha256)


@server.tool()
def scan_chart_caches(file: str) -> dict[str, Any]:
    """Compare chart caches with stored worksheet values and identify literal data with no worksheet reference; check completeness and formula freshness."""
    return chart_cache.scan(file)


@server.tool()
def session_scan_chart_caches(directory: str, revision: int) -> dict[str, Any]:
    """Check chart caches and identify literal data with no worksheet reference in an exact XLSX session revision."""
    return session.scan_chart_caches(directory, revision)


@server.tool()
def session_set_chart_literal_category(directory: str, base_revision: int, part: str, reference: StrictInt, point: StrictInt, text: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Change a literal chart category across matching series using a scanned part and one-based reference and point indices."""
    return session.set_chart_literal_category(directory, base_revision, part, reference, point, text, expected_sha256)


@server.tool()
def session_set_chart_literal_value(directory: str, base_revision: int, part: str, reference: StrictInt, point: StrictInt, value: StrictFloat, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set an existing numeric literal series point in an XLSX chart, using the inspected chart part and one-based reference and point indices."""
    return session.set_chart_literal_value(directory, base_revision, part, reference, point, value, expected_sha256)


@server.tool()
def session_sync_chart_cache(directory: str, base_revision: int, part: str, reference: int, allow_formula_caches: bool = False, expected_sha256: str | None = None) -> dict[str, Any]:
    """Sync one fully comparable chart reference in a new revision; formula source caches require explicit opt-in."""
    return session.sync_chart_cache(directory, base_revision, part, reference, allow_formula_caches, expected_sha256)


@server.tool()
def session_set_slide_chart_text_color(directory: str, base_revision: int, part: str, color: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set chart title, axes, legend and default label text color in a simple slide chart; color is six RGB hex digits."""
    return session.set_slide_chart_text_color(directory, base_revision, part, color, expected_sha256)


@server.tool()
def session_set_slide_chart_literal_text(directory: str, base_revision: int, part: str, kind: Literal['series_name', 'category'], text: str, series: StrictInt | None = None, point: StrictInt | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set a literal series name or category. Use series for a name, or point for a shared category; indices are one-based."""
    return session.set_slide_chart_literal_text(directory, base_revision, part, kind, text, series, point, expected_sha256)


@server.tool()
def session_set_slide_chart_literal_value(directory: str, base_revision: int, part: str, series: StrictInt, point: StrictInt, value: StrictFloat, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set one existing numeric literal chart point using one-based series and point indices from inspection. Shared chart parts affect all placements."""
    return session.set_slide_chart_literal_value(directory, base_revision, part, series, point, value, expected_sha256)


@server.tool()
def session_set_slide_chart_axis_bounds(directory: str, base_revision: int, part: str, axis_id: str, minimum: StrictFloat | None, maximum: StrictFloat | None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set both value-axis bounds in a slide chart; null clears a bound to automatic. Use an inspected chart part, axis ID and snapshot."""
    return session.set_slide_chart_axis_bounds(directory, base_revision, part, axis_id, minimum, maximum, expected_sha256)


@server.tool()
def session_sync_slide_chart_cache(directory: str, base_revision: int, part: str, reference: int, allow_formula_caches: bool = False, expected_sha256: str | None = None) -> dict[str, Any]:
    """Sync a verified slide chart cache reference from its saved embedded workbook into a new revision."""
    return session.sync_slide_chart_cache(directory, base_revision, part, reference, allow_formula_caches, expected_sha256)


@server.tool()
def structured_read(file: str, mode: Literal['outline', 'get', 'query'], target: str | None = None) -> dict[str, Any]:
    """Read an outline, element path, or selector through OfficeCLI. get/query require target."""
    if (mode == 'outline') != (target is None):
        raise ValueError('get and query require a target; outline takes no target')
    return {'data': officecli_backend.read(file, mode, target)}


@server.tool()
def dump_office_subtree(file: str, path: str = '/') -> dict[str, Any]:
    """Extract bounded OfficeCLI operations; inspect paths and fidelity before applying them."""
    return officecli_backend.dump(file, path)


@server.tool()
def session_dump_office_subtree(directory: str, revision: int, path: str = '/') -> dict[str, Any]:
    """Extract OfficeCLI operations from one saved session revision; verify omitted resources."""
    return session.dump(directory, revision, path)


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


@server.tool(structured_output=False)
def session_selection_image(directory: str) -> CallToolResult:
    """Render the selected region of the exact revision. Check XLSX dynamic-array metadata because LibreOffice may omit spill results."""
    selection = session.get_selection(directory)
    state = session.info(directory)
    source = session.revision_file(state, selection['revision'])
    data, details = visual.page_image(source, selection['page'], render, selection['box'])
    current_selection = session.get_selection(directory); latest = current_selection['latest_revision']
    return image_result(data, {**details, 'revision': selection['revision'], 'latest_revision': latest, 'stale': selection['revision'] != latest, 'selection_changed': any(selection[key] != current_selection[key] for key in ('revision', 'page', 'box'))})


@server.tool()
def session_sheets(directory: str, base_revision: int) -> dict[str, Any]:
    """List worksheet names in the latest saved XLSX session revision."""
    return session.sheet_names(directory, base_revision)


@server.tool()
def session_read_grid(directory: str, base_revision: int, sheet: str, cell_range: str) -> dict[str, Any]:
    """Read up to 200 cells with direct styles, stored row/column dimensions, protection, text completeness, bounded hyperlink targets and coverage, and data-validation and conditional-formatting metadata. Rules are not evaluated; simple absolute list ranges and scoped names of verified text include bounded choices and source details."""
    return session.read_grid(directory, base_revision, sheet, cell_range)


@server.tool()
def session_read_slide_chart_grid(directory: str, revision: int, part: str, sheet: str, cell_range: str) -> dict[str, Any]:
    """Read an embedded chart workbook grid from an exact PowerPoint revision."""
    return session.read_slide_chart_grid(directory, revision, part, sheet, cell_range)


@server.tool()
def session_edit_slide_chart_grid(directory: str, base_revision: int, part: str, sheet: str, cell_range: str, changes: list[dict[str, str]], sync_caches: bool = False) -> dict[str, Any]:
    """Edit an embedded chart workbook grid; optionally synchronize fully comparable chart caches atomically."""
    return session.edit_slide_chart_grid(directory, base_revision, part, sheet, cell_range, changes, sync_caches)


@server.tool()
def session_rename_table_column(directory: str, base_revision: int, sheet: str, table_name: str, old_name: str, new_name: str) -> dict[str, Any]:
    """Rename a table column and rewrite supported explicit and table-local structured references in one revision; indirect references are rejected."""
    return session.rename_table_column(directory, base_revision, sheet, table_name, old_name, new_name)


@server.tool()
def session_set_grid_hyperlink(directory: str, base_revision: int, sheet: str, cell: str, url: str | None, expected_sha256: str | None = None, location: dict[str, str] | None = None) -> dict[str, Any]:
    """Set an HTTP(S)/mailto hyperlink, set a workbook location {sheet, cell}, or remove the link when both are null; preserve cell content and formatting."""
    return session.set_grid_hyperlink(directory, base_revision, sheet, cell, url, expected_sha256, location)


@server.tool()
def session_edit_grid(directory: str, base_revision: int, sheet: str, cell_range: str, changes: list[dict[str, str]], expected_sha256: str | None = None) -> dict[str, Any]:
    """Edit grid values; each change may set type to text. Unrelated caches are retained; dynamic formula anchors are returned for spill review, validation rules are not evaluated, and recalculation is requested."""
    return session.edit_grid(directory, base_revision, sheet, cell_range, changes, expected_sha256)


@server.tool()
def session_format_grid(directory: str, base_revision: int, sheet: str, cell_range: str, style_range: str, properties: dict[str, Any], expected_sha256: str | None = None) -> dict[str, Any]:
    """Apply supported formatting while retaining formula caches; unsupported styles, protected sheets and merged placeholders are rejected."""
    return session.format_grid(directory, base_revision, sheet, cell_range, style_range, properties, expected_sha256)


@server.tool()
def session_merge_cells(directory: str, base_revision: int, sheet: str, cell_range: str, merge: bool = True, expected_sha256: str | None = None) -> dict[str, Any]:
    """Merge a bounded empty-interior range or unmerge an exact existing range."""
    return session.merge_cells(directory, base_revision, sheet, cell_range, merge, expected_sha256)


@server.tool()
def session_freeze_panes(directory: str, base_revision: int, sheet: str, cell: str | None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Freeze rows and columns above and left of cell; pass null or A1 to unfreeze."""
    return session.freeze_panes(directory, base_revision, sheet, cell, expected_sha256)


@server.tool()
def session_resize_grid(directory: str, base_revision: int, sheet: str, cell_range: str, target_range: str, column_width: float | None = None, row_height: float | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set entire column widths and/or row heights for a subrange of the loaded grid, in a new revision."""
    return session.resize_grid(directory, base_revision, sheet, cell_range, target_range, column_width, row_height, expected_sha256)


@server.tool()
def session_edit_target(directory: str, base_revision: int, path: str) -> dict[str, Any]:
    """Read one element in the latest revision, including replacement eligibility."""
    return session.edit_target(directory, base_revision, path)


@server.tool()
def session_edit(directory: str, base_revision: int, path: str, mode: Literal['text', 'value', 'formula', 'literal'], value: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set one element in a new revision; XLSX literal mode retains text, unrelated formula caches are preserved and recalculation is requested. Text replacement may change formatting."""
    return session.edit(directory, base_revision, path, mode, value, expected_sha256)


@server.tool()
def session_replace_text(directory: str, base_revision: int, path: str, find: str, replacement: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Replace one unique text match in supported Word, PowerPoint or Excel text, retaining formatting; Excel requests recalculation on open."""
    return session.replace_text(directory, base_revision, path, find, replacement, expected_sha256)


@server.tool()
def session_refresh_word_toc(directory: str, base_revision: int, path: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Refresh an authored Word TOC heading cache in a new revision; page numbers still require updating the field in an editor."""
    return session.refresh_word_toc(directory, base_revision, path, expected_sha256)


@server.tool()
def session_replace_text_batch(directory: str, base_revision: int, changes: list[dict[str, str]]) -> dict[str, Any]:
    """Apply 1–25 ordered formatting-preserving text replacements in a single atomic revision; PowerPoint paths can include slide text and speaker-note paragraphs."""
    return session.replace_text_batch(directory, base_revision, changes)


@server.tool()
def session_track_replace_text(directory: str, base_revision: int, path: str, find: str, replacement: str, author: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Create Word deletion and insertion revisions for one unique body, header or footer text range; preserve run formatting."""
    return session.track_replace_text(directory, base_revision, path, find, replacement, author, expected_sha256)


@server.tool()
def session_track_insert_text(directory: str, base_revision: int, path: str, anchor: str, text: str, position: Literal['before', 'after'], author: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Insert a Word tracked run before or after one unique body, header or footer text anchor, retaining adjacent formatting."""
    return session.track_insert_text(directory, base_revision, path, anchor, text, position, author, expected_sha256)


@server.tool()
def session_resolve_tracked_runs(directory: str, base_revision: int, part: str, ids: list[str], accept: bool, expected_sha256: str | None = None) -> dict[str, Any]:
    """Accept or reject selected simple Word insertion/deletion run records in one part; create a new revision."""
    return session.resolve_tracked_runs(directory, base_revision, part, ids, accept, expected_sha256)


@server.tool()
def inspect_slides(file: str) -> dict[str, Any]:
    """List slide positions, IDs, titles, visibility and supported section membership from a saved PPTX snapshot."""
    return slides.inventory(file)


@server.tool()
def session_inspect_slides(directory: str, revision: int) -> dict[str, Any]:
    """List slides and supported section membership from an exact PPTX revision."""
    return session.inventory_slides(directory, revision)


@server.tool()
def session_reorder_slides(directory: str, base_revision: int, order: list[StrictInt]) -> dict[str, Any]:
    """Reorder every slide by one-based position in a new PPTX revision; supported sections remain contiguous and keep their members."""
    return session.reorder_slides(directory, base_revision, order)


@server.tool()
def read_slide_notes(file: str, slide: int) -> dict[str, Any]:
    """Read speaker notes for a one-based slide number without creating a notes slide."""
    return notes.read(file, slide)


@server.tool()
def session_read_slide_notes(directory: str, revision: int, slide: int) -> dict[str, Any]:
    """Read speaker notes from an exact PPTX session revision."""
    return session.read_notes(directory, revision, slide)


@server.tool()
def compare_slide_notes(before: str, after: str, before_slide: int, after_slide: int) -> dict[str, Any]:
    """Compare speaker notes from explicitly corresponding slides in two saved decks."""
    return review.compare_notes(before, after, before_slide, after_slide)


@server.tool()
def session_compare_slide_notes(directory: str, before_revision: int, after_revision: int, before_slide: int, after_slide: int) -> dict[str, Any]:
    """Compare speaker notes from explicitly corresponding slides in two session revisions."""
    return session.compare_notes(directory, before_revision, after_revision, before_slide, after_slide)


@server.tool()
def session_replace_slide_notes(directory: str, base_revision: int, slide: int, text: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Replace all speaker notes on one slide in a new revision; notes formatting is reset."""
    return session.replace_notes(directory, base_revision, slide, text, expected_sha256)


@server.tool()
def session_replace_slide_notes_text(directory: str, base_revision: int, slide: int, paragraph: int, find: str, replacement: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Replace one unique literal in a one-based notes paragraph, preserving run formatting."""
    return session.replace_notes_text(directory, base_revision, slide, paragraph, find, replacement, expected_sha256)


@server.tool()
def list_word_comments(file: str) -> dict[str, Any]:
    """List Word comments, bounded body anchor hints and available Word 2013 thread metadata."""
    return word.list_comments(file)


@server.tool()
def list_word_tracked_changes(file: str) -> dict[str, Any]:
    """Inspect bounded tracked-change XML records and coverage from a saved DOCX snapshot."""
    return word.tracked_changes(file)


@server.tool()
def session_list_word_tracked_changes(directory: str, revision: int) -> dict[str, Any]:
    """Inspect tracked-change XML records in an exact saved Word revision."""
    return session.tracked_changes(directory, revision)


@server.tool()
def list_word_stories(file: str) -> dict[str, Any]:
    """List bounded header and footer paragraphs and explicit section references in a saved DOCX."""
    return word.list_stories(file)


@server.tool()
def search_word_body(file: str, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search Word body and table paragraphs; continue with next_offset and snapshot_sha256 using the same query."""
    return word.search_body(file, query, offset, snapshot_sha256)


@server.tool()
def search_word_notes(file: str, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search ordinary Word footnote and endnote paragraphs; paginate with the same query and snapshot hash."""
    return word.search_notes(file, query, offset, snapshot_sha256)


@server.tool()
def session_search_word_notes(directory: str, revision: int, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search footnotes and endnotes in an exact revision; validate candidates before editing."""
    return session.search_notes(directory, revision, query, offset, snapshot_sha256)


@server.tool()
def search_word_stories(file: str, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search related Word headers and footers; preserve query and snapshot hash when paging."""
    return word.search_stories(file, query, offset, snapshot_sha256)


@server.tool()
def session_search_word_stories(directory: str, revision: int, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search headers and footers in an exact revision; inspect shared section impact before editing."""
    return session.search_stories(directory, revision, query, offset, snapshot_sha256)


@server.tool()
def session_search_word_body(directory: str, revision: int, query: str, offset: int = 0, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Search an exact Word revision; check coverage, in_field and validate paths before editing."""
    return session.search_body(directory, revision, query, offset, snapshot_sha256)


@server.tool()
def session_list_word_stories(directory: str, revision: int) -> dict[str, Any]:
    """List header and footer paragraph targets from an exact DOCX session revision."""
    return session.list_stories(directory, revision)


@server.tool()
def session_list_comments(directory: str, revision: int) -> dict[str, Any]:
    """List comments from an exact DOCX session revision and report main-body anchor hints."""
    return session.list_comments(directory, revision)


@server.tool()
def session_reply_comment(directory: str, base_revision: int, parent_id: str, text: str, author: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Reply to a supported open root Word comment and create a new revision."""
    return session.reply_comment(directory, base_revision, parent_id, text, author, expected_sha256)


@server.tool()
def session_resolve_comment(directory: str, base_revision: int, comment_id: str, resolved: bool, expected_sha256: str | None = None) -> dict[str, Any]:
    """Resolve or reopen a root Word comment as a new revision; ambiguous metadata is rejected."""
    return session.resolve_comment(directory, base_revision, comment_id, resolved, expected_sha256)


@server.tool()
def session_add_comment(directory: str, base_revision: int, path: str, text: str, author: str, anchor: str | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Add a Word comment to a paragraph or unique literal anchor and create a new revision."""
    return session.add_comment(directory, base_revision, path, text, author, anchor, expected_sha256)


@server.tool()
def session_set_slide_navigation(directory: str, base_revision: int, path: str, target_slide: int | None, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set a one-based slide click target on a shape or regular text run, or remove a supported slide jump with null."""
    return session.set_slide_navigation(directory, base_revision, path, target_slide, expected_sha256)


@server.tool()
def session_set_slide_description(directory: str, base_revision: int, path: str, description: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Set alternative text on one PowerPoint shape, picture, connector, chart or table in a new revision."""
    return session.set_slide_description(directory, base_revision, path, description, expected_sha256)


@server.tool()
def session_replace_picture(directory: str, base_revision: int, path: str, image_file: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Replace a PPTX picture with a local PNG or JPEG, preserving its geometry and crop."""
    image_data = session.read_picture_file(image_file)
    return session.replace_picture(directory, base_revision, path, image_data, expected_sha256)


@server.tool()
def session_apply(directory: str, base_revision: int, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply an OfficeCLI batch to the latest revision; reject concurrent or stale edits."""
    return session.apply(directory, base_revision, operations)


@server.tool()
def inspect_slide_navigation(file: str) -> dict[str, Any]:
    """Inspect slide shape and regular text-run click/hover actions and their slide or external targets."""
    return slides.inspect_navigation(file)


@server.tool()
def session_inspect_slide_navigation(directory: str, revision: int) -> dict[str, Any]:
    """Inspect slide shape and regular text-run click/hover actions in a PowerPoint session revision."""
    return session.inspect_slide_navigation(directory, revision)


@server.tool()
def inspect_slide_charts(file: str) -> dict[str, Any]:
    """Inspect PowerPoint chart caches, saved axis settings, range-clipping candidates and embedded workbook values; formula freshness is unknown."""
    return slide_charts.inspect(file)


@server.tool()
def session_inspect_slide_charts(directory: str, revision: int) -> dict[str, Any]:
    """Inspect PowerPoint chart caches, saved axis settings, range-clipping candidates and embedded workbook values in a session revision."""
    return session.inspect_slide_charts(directory, revision)


@server.tool()
def session_inspect_slide_layout(directory: str, revision: int) -> dict[str, Any]:
    """Inspect geometric layout candidates in a saved PPTX session revision."""
    return session.inspect_layout(directory, revision)


@server.tool()
def session_recalculate(directory: str, base_revision: int, allow_dynamic_arrays: bool = False) -> dict[str, Any]:
    """Recalculate an XLSX with LibreOffice; dynamic-array metadata requires explicit allow_dynamic_arrays because spill results may be incomplete."""
    return session.recalculate(directory, base_revision, allow_dynamic_arrays)


@server.tool()
def session_scan_formulas(directory: str, base_revision: int) -> dict[str, Any]:
    """Scan saved formulas, error caches and dynamic-array metadata in the latest XLSX revision."""
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
def review_document_bundle(file: str, output_dir: str) -> dict[str, Any]:
    """Create a local audit, format-specific checks, PDF and overview from one snapshot."""
    return review_bundle.create(file, output_dir, render)


@server.tool()
def session_review_bundle(directory: str, revision: int, output_dir: str) -> dict[str, Any]:
    """Create a review bundle from an exact saved session revision."""
    state = session.info(directory); source = session.revision_file(state, revision)
    if Path(output_dir).resolve().is_relative_to(Path(state['directory'])):
        raise ValueError('Review output must be outside the session directory')
    return review_bundle.create(source, output_dir, render, revision)


@server.tool()
def audit_file(file: str) -> dict[str, Any]:
    """Check a saved Office file using OfficeCLI schema validation and its issues view."""
    return officecli_backend.audit(file)


@server.tool()
def inspect_slide_text(file: str) -> dict[str, Any]:
    """Find slide text box or table cell candidates needing review against a LibreOffice PDF rendering."""
    return slide_text_check.scan(file, render)


@server.tool()
def session_inspect_slide_text(directory: str, revision: int) -> dict[str, Any]:
    """Inspect a saved slide revision against its rendered PDF; review completeness and candidates."""
    return session.inspect_slide_text(directory, revision, render)


@server.tool()
def inspect_slide_layout(file: str) -> dict[str, Any]:
    """Report off-slide and overlapping-text geometric candidates in a saved PPTX."""
    return layout.inspect(file)


@server.tool()
def search_slide_text(file: str, query: str, slide: int | None = None, offset: int = 0, snapshot_sha256: str | None = None, scope: Literal['slides', 'notes'] = 'slides') -> dict[str, Any]:
    """Search slide text or speaker notes; continue with next_offset and snapshot_sha256 using the same query, slide and scope."""
    return slides.search_text(file, query, slide, offset, snapshot_sha256, scope)


@server.tool()
def session_search_slide_text(directory: str, revision: int, query: str, slide: int | None = None, offset: int = 0, snapshot_sha256: str | None = None, scope: Literal['slides', 'notes'] = 'slides') -> dict[str, Any]:
    """Search slide text or speaker-note paragraphs in an exact revision; inspect candidates before editing."""
    return session.search_slides(directory, revision, query, slide, offset, snapshot_sha256, scope)


@server.tool()
def compare_files(before: str, after: str) -> dict[str, Any]:
    """Compare saved Office files: changed package parts and a bounded text-view diff."""
    return review.compare(before, after)


@server.tool()
def session_compare_cells(directory: str, before_revision: int, after_revision: int, sheet: str, cell_range: str) -> dict[str, Any]:
    """Compare cell values, formulas, styles and stored dimensions across two session revisions."""
    return session.compare_cells(directory, before_revision, after_revision, sheet, cell_range)


@server.tool()
def compare_cells(before: str, after: str, sheet: str, cell_range: str) -> dict[str, Any]:
    """Compare formulas, cached values, direct formatting and stored dimensions; check completeness fields."""
    return review.compare_cells(before, after, sheet, cell_range)


@server.tool()
def read_cells(file: str, sheet: str, cell_range: str) -> dict[str, Any]:
    """Read up to 10,000 cells; check text completeness. Formula cache freshness is unknown."""
    return spreadsheet.read_range(file, sheet, cell_range)


@server.tool()
def scan_formulas(file: str) -> dict[str, Any]:
    """Scan stored formulas, error values and dynamic-array metadata across a saved XLSX; cache freshness is unknown."""
    return spreadsheet.scan_formulas(file)


@server.tool()
def recalculate_workbook(file: str, output: str, allow_dynamic_arrays: bool = False) -> dict[str, Any]:
    """Recalculate with LibreOffice; dynamic metadata requires explicit allow_dynamic_arrays and spill results may be incomplete."""
    return {'output': spreadsheet.recalculate(file, output, allow_dynamic_arrays), 'dynamic_array_override': allow_dynamic_arrays}


@server.tool()
def render_pdf(file: str, output_dir: str) -> dict[str, Any]:
    """Render an Office file to a new PDF using LibreOffice."""
    return render_with_info(file, output_dir)


@server.tool()
def preview_pages(file: str, output_dir: str) -> dict[str, Any]:
    """Render page PNGs into a new directory using LibreOffice and Poppler."""
    return render_with_info(file, output_dir, pages=True)


@server.tool(structured_output=False)
def view_document_page(file: str, page: int, box: list[float] | None = None) -> CallToolResult:
    """View a rendered page; for XLSX check scan_formulas first because dynamic-array spills can be incomplete in LibreOffice previews."""
    data, details = visual.page_image(file, page, render, box)
    return image_result(data, details)


@server.tool(structured_output=False)
def session_view_page(directory: str, revision: int, page: int, box: list[float] | None = None) -> CallToolResult:
    """View a session revision page; for XLSX inspect dynamic-array metadata because LibreOffice previews may omit spill results."""
    state = session.info(directory)
    source = session.revision_file(state, revision)
    data, details = visual.page_image(source, page, render, box)
    return image_result(data, {**details, 'revision': revision})


@server.tool(structured_output=False)
def compare_page_images(before: str, after: str, before_page: int, after_page: int) -> CallToolResult:
    """Compare rendered pages visually; red shows RGB differences of at least 16/255. Check XLSX dynamic-array metadata because LibreOffice may omit spill results."""
    data, details = visual.compare_pages(before, after, before_page, after_page, render)
    return image_result(data, details)


@server.tool(structured_output=False)
def session_compare_page_images(directory: str, before_revision: int, after_revision: int, before_page: int, after_page: int) -> CallToolResult:
    """Compare rendered pages from exact session revisions; check XLSX dynamic-array metadata because LibreOffice may omit spill results."""
    state = session.info(directory)
    before = session.revision_file(state, before_revision)
    after = session.revision_file(state, after_revision)
    data, details = visual.compare_pages(before, after, before_page, after_page, render)
    return image_result(data, {**details, 'before_revision': before_revision, 'after_revision': after_revision})


@server.tool(structured_output=False)
def view_contact_sheet(file: str, start_page: int = 1, count: int = 12) -> CallToolResult:
    """Render up to 12 numbered pages as a PNG overview. Check XLSX dynamic-array metadata because LibreOffice may omit spill results."""
    data, details = visual.contact_sheet(file, start_page, count, render)
    return image_result(data, details)


@server.tool(structured_output=False)
def session_contact_sheet(directory: str, revision: int, start_page: int = 1, count: int = 12) -> CallToolResult:
    """Render a numbered overview of an exact revision. Check XLSX dynamic-array metadata because LibreOffice may omit spill results."""
    state = session.info(directory)
    source = session.revision_file(state, revision)
    data, details = visual.contact_sheet(source, start_page, count, render)
    return image_result(data, {**details, 'revision': revision})


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
