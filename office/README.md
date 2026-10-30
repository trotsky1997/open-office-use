# Open Office Use — early local harness

A first office-file workbench in the [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use) fork. It offers a JSON CLI for local DOCX, XLSX and PPTX inspection, creation, limited edits, and PDF rendering. It does not require Chrome. The inherited browser tooling remains available under its original name.

## Install

Python 3.10+. PDF rendering requires LibreOffice on PATH; page PNG previews additionally require Poppler `pdftoppm`, and selected text extraction requires `pdftotext`. The structured operations below require OfficeCLI on PATH (tested with 1.0.147):

```sh
python3 -m pip install ./office
```

## Use

```sh
office-use inspect report.docx
# Create a document from a JSON specification
office-use author --spec doc.json --out report.docx
# Edit a copy of an existing file
office-use author --source input.xlsx --spec edits.json --out output.xlsx
office-use render output.xlsx --out-dir pdfs
office-use preview output.xlsx --out-dir page-images
```

The command writes one JSON result to stdout, reports failures to stderr and returns a nonzero status. Output files must not already exist. Inspect returns zero-based paragraph and slide indices; PPTX inspection includes each text shape’s index in the underlying shape collection.

Specifications:

```json
{"paragraphs": ["First paragraph"], "replace_paragraphs": {"0": "Replacement"}}
```

```json
{"sheets": {"Forecast": {"A1": "Revenue", "B1": 120, "B2": "=B1*2"}}}
```

```json
{"slides": [{"title": "Overview", "body": "Details"}], "replace_text": [{"slide": 0, "shape": 0, "text": "New title"}]}
```

The `author` command sets whole paragraphs, cells or text frames. Replacing paragraph or shape text drops its run-level formatting. The libraries may alter or drop unsupported Office features when saving existing files; retain the original and review the output. Formula strings are stored, not recalculated by `author`. LibreOffice rendering may recalculate and can differ visually from Microsoft Office. Inspect is a basic content extraction and is not a full fidelity representation (e.g. charts, text in DOCX tables during paragraph edits, speaker notes, and embedded objects). Rendering produces PDF; use a PDF viewer to inspect pages visually. The `author` command does not support encrypted or macro-enabled files, live editing, collaboration, comments, tracked changes, cloud documents, or rich styling.

## Structured OfficeCLI operations

OfficeCLI provides element paths, queries, formatting, charts, images and other operations. Its full command and property schema is available through `officecli help`. `structured` returns the OfficeCLI JSON data for an outline, element, or query:

```sh
office-use structured input.docx outline
office-use structured input.docx get '/body/p[1]'
office-use structured input.docx query 'paragraph'
```

`batch` creates a new file or applies an OfficeCLI JSON batch to a copy:

```json
[{"command":"add","parent":"/body","type":"paragraph","props":{"text":"Executive summary","bold":"true"}}]
```

```sh
office-use batch --spec operations.json --out new.docx
office-use batch --source original.docx --spec operations.json --out revised.docx
```

Operations run on a temporary file. A successful batch is closed before the complete result is published to a new path; errors leave the requested output absent. Existing outputs are never replaced. This publication uses a hard link on the destination filesystem; filesystems that do not support hard links return an error. Use a saved and closed source file: edits held in another OfficeCLI resident session are not included in the disk copy. Only the tested OfficeCLI version is known to work; its operation schemas and rendering fidelity must be checked against the target version and documents. These commands use the separately installed OfficeCLI executable; it is not bundled.

`preview` creates a new directory containing one PNG per rendered page. It refuses an existing directory. For a numbered overview of up to 12 pages, use `office-use contact-sheet slides.pptx --out overview.png --start 1 --count 12`; choose another start page to continue. The equivalent MCP tools are `view_contact_sheet` for a saved file and `session_contact_sheet` for a specific revision. Each returns a native PNG image, with the rendered page range and total in the header. These page numbers refer to LibreOffice's PDF output; hidden slides can change the mapping to PowerPoint slide numbers. Inspect full-size page images for small text and details, since an overview, successful render, or schema validation alone does not establish visual quality or Office fidelity.

To inspect one rendered page without producing all page PNGs, use `office-use render-page slides.pptx --page 2 --out page-2.png`. Add `--box 0 0 1 0.5` to crop to the top half; coordinates are normalized left, top, right, bottom from the top-left. MCP `view_document_page` and `session_view_page` return the page or crop as a native image, with an explicit session revision for the latter. Whole-page images have a maximum dimension of 1,800 pixels. Crops are rendered again at up to a 7,200-pixel full-page scale, targeting a 1,800-pixel maximum crop dimension; coordinates are rounded to raster pixels. Very small regions or low-resolution embedded images may need another source. Outputs are limited to 10 MiB and existing PNG files are protected.

## Multi-step draft sessions

A session is a local directory of saved revision files. Start from a saved source, or pass `--format docx`, `xlsx` or `pptx` to start blank. The directory must be new and its parent must exist.

```sh
office-use session start ./draft --source original.docx
office-use session info ./draft
# Replace one match in a simple Word body paragraph, creating revision 1
office-use session replace-text ./draft --base 0 --path '/body/p[1]' --find 'old text' --replace 'new text'
office-use session apply ./draft --base 1 --spec operations.json
office-use session restore ./draft --base 2 --revision 0
office-use session export ./draft --revision 3 --out final.docx
```

`replace-text` and MCP `session_replace_text` find exactly one literal match in a Word body or table-cell paragraph, including matches spanning multiple text runs. Replacement text uses the first matched run's formatting; other runs and all other package parts remain intact. It preserves ordinary hyperlinks, bookmarks and comment anchors when the match stays within one region. Matches crossing a hyperlink or anchor boundary are rejected. Ambiguous matches, signed documents, control characters, fields, tracked changes and other unsupported structures are also rejected. Paths use one-based physical table, row, cell and paragraph indices, including nested tables. A paragraph may also be addressed by its saved `paraId`; duplicate IDs within its container are rejected. `session_edit_target` exposes `replace_text_path_supported` for path eligibility; actual paragraph structure is checked when applying the replacement. Headers and footers are outside this workflow. Packages are limited to 5,000 parts and 128 MiB. The document XML is reserialized, so visually review the result.

For PPTX sessions, `replace-text` and `session_replace_text` also accept paths such as `/slide[1]/shape[1]/paragraph[1]` or `/slide[1]/shape[@id=2]/paragraph[1]`. Slides follow the presentation order, even when package part names have been reordered; a slide part referenced by multiple slide entries is rejected. Shape and group indices each count their own element type; shape IDs from structured reads are also accepted. Nested group paths are supported through CLI and MCP. A shape path without a paragraph is accepted only for a single-paragraph text body. Replacement uses the first matched run's formatting and preserves the other package parts. Table-cell paths such as `/slide[1]/table[1]/tr[1]/tc[1]/paragraph[1]` use one-based physical row and cell indices; merged-cell placeholders are rejected and the merged origin can be edited. Select a paragraph explicitly when a cell or shape contains more than one. The viewer loads supported table cells read-only and offers paragraph-based replacement. Paragraphs containing line breaks, fields or run hyperlinks, and shape containers with alternate content, are rejected; charts and notes require other workflows. The viewer offers this operation for supported targets that OfficeCLI can load. Review the rendered output.


For an embedded PowerPoint picture, use `office-use session replace-picture ./draft --base 0 --path '/slide[1]/picture[@id=2]' --image replacement.png`, or MCP `session_replace_picture` with a local image file. In the viewer, select a picture, choose its geometric candidate, and upload a replacement. Static PNG and JPEG images are accepted up to 10 MiB and 40 megapixels. The operation creates a new revision and retains the picture's position, size, rotation, crop, and other slide properties; a new media relationship keeps other pictures using the original image unchanged. Linked images, animated images, pictures with unsupported blip extensions or effects, and digitally signed packages are rejected. Existing crop can change how the replacement appears; inspect the rendered revision. The original media remains in the package.

For XLSX sessions, `replace-text` and `session_replace_text` also accept a text cell path such as `/Sales Data/A1`. Inline and shared rich-text runs retain their formatting. Shared strings are reused when equivalent or added as a new entry, leaving other cells that referenced the original unchanged. Cell styles, hyperlinks, ordinary comments and unrelated package parts are retained. Formula cells, array/data-table/shared formula ranges, merged-cell placeholders, phonetic content, unsupported metadata and Excel escaped-text sequences are rejected. Formula caches elsewhere are left unchanged and can become stale after editing; use the calculation and review workflow when needed.


Each successful batch creates the next revision. `--base` must match the latest revision; a stale or concurrent competing write fails. A failed batch leaves the previous revision intact. Restoring a historical revision creates a new latest revision; it uses the same base-revision conflict check and keeps all earlier versions. `info` lists file paths for use with `structured`, `compare`, `audit` and `preview`. Export copies any revision to a new output outside the session directory. Session operations never replace the source or an existing export. Keep the session directory private to its owner and do not edit its revision files directly: the session protocol assumes those files remain unchanged. Save and close external editing sessions before creating a session from a source. Session history persists until the directory is removed manually.

To watch the latest revision in a browser, run this in a separate terminal:

```sh
office-use watch ./draft
```

Open the printed URL on the same machine. The preview follows committed revisions and shows LibreOffice/Poppler page images. Open the revision control and choose “Preview selected revision” to inspect an earlier version before restoring it; “Compare with latest” displays the selected and latest rendered pages side by side; “Show latest” returns to the current version. The latest side refreshes when another edit is committed. Open “Text and file changes” and select “Load changes” to inspect a bounded text diff and changed OOXML parts for the displayed pair; the panel clears when the pair changes. For XLSX comparisons, enter a worksheet and cell range in “Worksheet changes” to inspect changed values, formulas and direct formatting alongside the pages. The result is tied to the displayed revision pair and clears when either the pair or inputs change. Compare corresponding pages manually; changes in pagination can shift content between pages. Historical preview keeps the selected version visible while displaying the latest version number. Selection is available on the latest version. Drag a rectangle on a page to save a visual selection for the agent; the selection form also accepts page-relative percentages by keyboard. The selection is stored in the session directory and replaces the previous selection. Use `office-use session selection ./draft` to read it and `office-use session selection-text ./draft` to extract text from that region, and `office-use session selection-candidates ./draft` to search for possible OfficeCLI element paths. Stop the server with Ctrl+C. It binds to `127.0.0.1`, uses a random URL token and rejects other Host headers. Anyone who obtains that URL and can reach the local server can view the document, save selections, edit supported elements and restore earlier revisions; keep it private. For XLSX sessions, “Edit worksheet range” lists sheets and loads up to 200 cells into a keyboard-accessible grid. A tab-separated rectangular clipboard range can be pasted starting at the focused cell, then reviewed before saving. Paste rejects the entire block if it extends past the loaded range or touches a protected cell. Quoted tabs and escaped quotes are supported; multiline cell text is unsupported. Clipboard data is limited to 20 KB, and the final JSON request has its own 20 KB limit. Only changed cells are sent in one versioned batch. A leading `=` writes a formula; other input is passed as a value and OfficeCLI may infer numbers or dates. Clearing an input clears that cell. Declared array, data-table and shared formula ranges are read-only in the grid, including cells whose formula anchor is outside the displayed range. The grid can apply bold, an RGB fill and an Excel number format to a selected subrange in a new revision. Save pending cell edits first. Patterned fills keep their pattern when their foreground color changes; theme colors are not displayed in the grid. Other advanced workbook structures and formatting need separate review. A viewer grid request is limited to 20 KB, so large changes must be split. When another edit advances the version, unsaved input stays visible and selectable in read-only fields. Reloading a grid or element with pending changes asks before replacing the input, and the browser warns before leaving with unsaved edits. Element text also remains selectable after its target becomes stale.

The preview page offers historical preview, revision restore and a limited element editor. After selecting an area, open “Find selected elements” to search for candidate paths; choose a candidate to load it for review. Candidates are text matches and require verification. Enter an OfficeCLI path, load the element and inspect its content, then save a new revision. The editor supports Word paragraphs and runs, spreadsheet cells, and PowerPoint text elements. Loaded supported Word, PowerPoint and Excel text targets, including table cells, offer “Replace once” for a unique match while retaining run formatting. It limits content to 4,000 characters; replacing text can change run formatting, and spreadsheet numeric values may be converted. Select formula mode for expressions beginning with `=`; value mode rejects them. Exports use the CLI or MCP. Render fidelity and page layout depend on LibreOffice.

## Inspect for issues

```sh
office-use audit report.docx
```

This uses a saved disk snapshot with OfficeCLI's Open XML schema validator and issues view. The result includes the validator's exit code and original JSON envelope, plus up to 200 issue entries. A nonzero validator exit code or `success: false` requires inspecting its result; an `issues_error` means the issue scan did not finish. The issues list can be truncated, and its reported count describes OfficeCLI's returned results. These checks cover only what OfficeCLI detects. Inspect rendered pages, formulas and the destination application's behavior separately. Save and close external editor sessions before auditing.


For PowerPoint geometry, inspect a saved file or one revision:

```sh
office-use inspect-layout deck.pptx
office-use session inspect-layout ./slides-draft --revision 2
```

The matching MCP tools are `inspect_slide_layout` and `session_inspect_slide_layout`; the viewer can check its displayed revision. In the viewer, choose a candidate to highlight its visible geometry on the corresponding page, including the selected side of a revision comparison. Highlights are disabled when slides are hidden, visibility is unknown, preview page counts differ, or slide and preview aspect ratios differ. An object fully outside the slide has no visible area to highlight. Results report visible slide objects extending beyond the slide and geometric overlaps involving a text-bearing shape or table. Each candidate includes slide and object IDs, path hints, draw-order hints, bounds and polygons in inches from the slide's top-left; overlap polygons are clipped to the visible slide. Rotated and nested group transforms are considered. Treat overlaps as candidates: backgrounds, intentional layering, transparency, strokes, shadows and actual glyph shapes are not resolved. The check does not measure text overflow or scan master/layout content, chart labels, SmartArt internals, notes or hidden objects. Verify path hints and inspect rendered slides. Limits are 10,000 shapes, 200,000 checked pairs, eight nested groups, and 200 results per category; completeness and truncation flags identify partial reports. Packages are limited to 5,000 parts and 128 MiB.

## Review edits

```sh
office-use compare original.docx revised.docx
office-use compare-cells original.xlsx revised.xlsx --sheet Forecast --range A1:D20
```

The result contains added, removed and modified OOXML package part names, plus a unified diff of OfficeCLI text views. The comparison reads saved disk snapshots; save and close external editing sessions first. Text views are limited to 2,000 lines per file, then 100,000 characters per view and 500 diff lines; truncation flags are returned. The text view can omit formatting, formulas and other content. Part changes indicate underlying file changes but do not describe their visual or semantic effect. Use `cells`, structured reads and page previews to review the relevant details. Files exceeding 5,000 package parts or 128 MiB uncompressed are rejected.

For visual review, `office-use compare-pages original.pptx revised.pptx --before-page 2 --after-page 2 --out diff.png` renders the selected PDF pages and creates before, after and red change-map panels. The JSON result reports the fraction of pixels whose largest RGB channel difference is at least 16/255; red marks are expanded slightly for visibility. MCP `compare_page_images` compares saved files, and `session_compare_page_images` compares explicit session revisions. In the viewer, compare a selected revision with the latest, open “Text and file changes”, and choose one rendered page from each revision under “Visual page changes”. Changing pages or advancing the latest revision clears the old comparison. Compare corresponding rendered pages: inserted pages and hidden slides can change page numbering. Different raster dimensions are rejected. Pages with the same aspect ratio are normalized to the same raster size, so changes in physical page size may not be apparent. The metric is a visual aid: rendering and antialiasing can change pixels, and differences below the threshold are omitted. Inspect full pages and structural changes before delivery.

`compare-cells` compares one worksheet rectangle in saved XLSX files. It reports changed formula text, values, types and direct cell formatting, with before/after details for the first 500 changed cells and a total count. Formatting includes font, fill, border, alignment and protection as resolved Open XML component fragments, plus the number format; component IDs are resolved within each workbook before comparison. The range is limited to 10,000 cells. For formula cells, `value` is the stored cached result and its freshness is unknown. The comparison does not evaluate conditional formatting, workbook theme changes, inherited row or column formatting, charts, comments or worksheet structure; use the broader comparison and visual review alongside it.

## Spreadsheet calculation

Inspect a bounded rectangular range (at most 10,000 cells):

```sh
office-use cells budget.xlsx --sheet Forecast --range A1:D20
office-use scan-formulas budget.xlsx
office-use recalculate budget.xlsx --out budget-calculated.xlsx
```

`scan-formulas` scans stored cells across worksheets, including hidden sheets, and reports counts and the first 200 formula errors, literal error cells, and empty or missing formula caches in separate lists. Formula text is OOXML text without a leading `=` and is clipped to 500 characters; shared-formula followers may have empty formula text. An empty cached string can be intentional. `complete: false` means the one-million-cell limit stopped the scan and counts cover only scanned cells; package limits are 5,000 parts and 128 MiB. This scan does not calculate formulas or determine whether existing caches are current. `cells` reports formulas, their stored cached values, and cell types, including formula errors. Cache freshness is always `unknown`; a missing cached result is returned as `null`. Rows include blank cells in the requested rectangle. `recalculate` opens a copy in a fresh LibreOffice profile, saves a new XLSX, and refuses an existing output. Read the output again to inspect calculated values and errors. LibreOffice uses its own calculation engine and may change layout or unsupported workbook features; review the resulting file against the source. External links, advanced Excel functions, complex workbooks and fidelity have not been comprehensively validated. Use a saved, closed source and review workbooks containing external links before conversion.


For a versioned XLSX session, scan its latest saved revision and explicitly recalculate into a new revision:

```sh
office-use session start ./budget-draft --source budget.xlsx
office-use session scan-formulas ./budget-draft --base 0
office-use session recalculate ./budget-draft --base 0
office-use session scan-formulas ./budget-draft --base 1
```

The equivalent MCP tools are `session_scan_formulas` and `session_recalculate`. Both require the latest base revision; competing writes are rejected. The local viewer's “Workbook calculation and checks” offers both operations, clears obsolete scan results, and keeps pending edits available. The scan examines saved caches; LibreOffice recalculation creates a new revision and may alter workbook features. Compare the revisions and inspect resulting errors and layout before delivery.

## MCP for agents

Install the optional MCP dependency from the repository root:

```sh
python3 -m pip install './office[mcp]'
```

Configure a local stdio MCP client, for example in Codex:

```toml
[mcp_servers.open_office_use]
command = "office-use"
args = ["mcp"]
```

The server offers `inspect_file`, `inspect_slide_layout`, `session_inspect_slide_layout`, `structured_read`, `apply_batch`, `render_pdf`, `preview_pages`, `view_page`, `view_document_page`, `session_view_page`, `compare_page_images`, `session_compare_page_images`, `view_contact_sheet`, `session_contact_sheet`, `read_cells`, `scan_formulas`, `recalculate_workbook`, `compare_files`, `compare_cells`, `audit_file`, `start_session`, `session_info`, `session_apply`, `session_restore`, `session_recalculate`, `session_scan_formulas`, `session_export`, `session_edit_target`, `session_edit`, `session_replace_text`, `session_replace_picture`, `session_sheets`, `session_read_grid`, `session_edit_grid`, `session_format_grid`, `session_selection`, `session_selection_image`, `session_selection_text`, and `session_selection_candidates`. `view_page` returns a PNG image to a vision-capable client (maximum 10 MiB). `session_selection` returns the selected revision, page and normalized rectangle, with a stale flag if the session advanced. `session_selection_image` renders only the selected PDF page and crops the exact selected revision; call `session_selection` to check whether it is stale. Selected text extraction uses `pdftotext` word centers within the rectangle on a freshly rendered PDF and returns text, normalized word boxes, revision and staleness. It is bounded to 5,000 selected words and an 8 MiB page extraction. It can miss partially selected words, reordered text, images, or scanned text; it does not perform OCR. Candidate lookup searches up to three selected text lines against OfficeCLI. For PPTX it also matches the selection against visible shape geometry, including images and empty shapes, when slide visibility, rendered page count and aspect ratio permit a reliable page mapping. Geometric candidates are listed first and carry overlap fractions; the viewer labels the match method. Hidden slides or uncertain mapping fall back to text search. Geometry describes transformed shape bounds rather than exact painted pixels, and master content, hidden objects and some complex elements are omitted. Results are limited and non-exhaustive: repeated text, wrapped lines, tables, formulas, images and complex layouts can yield ambiguity or missing matches. Check the selected revision and use structured reads and visual context to verify the exact target before editing. Search fragments are passed as OfficeCLI command arguments, which may be visible to other local processes. Paths refer to the machine running the server. The server has access to files available to its process; configure it only in a trusted local environment. OfficeCLI, LibreOffice and Poppler are required for their corresponding tools. Existing output protection and the saved-source requirement also apply over MCP.

## Verification

```sh
python3 office/smoke.py
python3 office/structured_smoke.py  # requires OfficeCLI
python3 office/cell_compare_smoke.py # requires LibreOffice
python3 office/candidates_smoke.py  # requires LibreOffice, Poppler and OfficeCLI
python3 office/selection_smoke.py   # requires LibreOffice, Poppler and OfficeCLI
python3 office/watch_smoke.py       # requires OfficeCLI, LibreOffice and Poppler
python3 office/grid_smoke.py        # requires OfficeCLI
python3 office/paste_smoke.py       # requires Node.js
python3 office/word_replace_smoke.py # run-preserving Word replacement
python3 office/word_anchor_smoke.py  # requires python-docx 1.2+ for comment fixture
python3 office/slides_replace_smoke.py # run-preserving PowerPoint replacement
python3 office/cell_text_smoke.py     # requires OfficeCLI and xlsxwriter
python3 office/editor_smoke.py      # requires OfficeCLI
python3 office/session_smoke.py     # requires OfficeCLI
python3 office/audit_smoke.py       # requires OfficeCLI
python3 office/review_smoke.py      # requires OfficeCLI
python3 office/spreadsheet_smoke.py # requires LibreOffice
python3 office/formula_scan_smoke.py # requires LibreOffice
python3 office/session_calc_smoke.py # requires LibreOffice
python3 office/contact_sheet_smoke.py # rendered overviews
python3 office/picture_smoke.py      # PPTX picture replacement
python3 office/layout_smoke.py       # slide geometry checks
python3 office/selection_geometry_smoke.py # slide selection with real PDF rendering
python3 office/mcp_smoke.py         # requires the MCP extra and OfficeCLI
```
