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

Edits set whole paragraphs, cells or text frames. Replacing paragraph or shape text drops its run-level formatting. The libraries may alter or drop unsupported Office features when saving existing files; retain the original and review the output. Formula strings are stored, not recalculated by `author`. LibreOffice rendering may recalculate and can differ visually from Microsoft Office. Inspect is a basic content extraction and is not a full fidelity representation (e.g. charts, text in DOCX tables during paragraph edits, speaker notes, and embedded objects). Rendering produces PDF; use a PDF viewer to inspect pages visually. Encrypted files, macro-enabled formats, live editing, collaboration, comments, tracked changes, cloud documents, and rich styling are not implemented.

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

`preview` creates a new directory containing one PNG per rendered page. It refuses an existing directory. Inspect the images, since a successful render or schema validation alone does not establish visual quality or Office fidelity.

## Multi-step draft sessions

A session is a local directory of saved revision files. Start from a saved source, or pass `--format docx`, `xlsx` or `pptx` to start blank. The directory must be new and its parent must exist.

```sh
office-use session start ./draft --source original.docx
office-use session info ./draft
office-use session apply ./draft --base 0 --spec operations.json
office-use session restore ./draft --base 1 --revision 0
office-use session export ./draft --revision 2 --out final.docx
```

Each successful batch creates the next revision. `--base` must match the latest revision; a stale or concurrent competing write fails. A failed batch leaves the previous revision intact. Restoring a historical revision creates a new latest revision; it uses the same base-revision conflict check and keeps all earlier versions. `info` lists file paths for use with `structured`, `compare`, `audit` and `preview`. Export copies any revision to a new output outside the session directory. Session operations never replace the source or an existing export. Keep the session directory private to its owner and do not edit its revision files directly: the session protocol assumes those files remain unchanged. Save and close external editing sessions before creating a session from a source. Session history persists until the directory is removed manually.

To watch the latest revision in a browser, run this in a separate terminal:

```sh
office-use watch ./draft
```

Open the printed URL on the same machine. The preview follows committed revisions and shows LibreOffice/Poppler page images. Open the revision control and choose “Preview selected revision” to inspect an earlier version before restoring it; “Compare with latest” displays the selected and latest rendered pages side by side; “Show latest” returns to the current version. The latest side refreshes when another edit is committed. Open “Text and file changes” and select “Load changes” to inspect a bounded text diff and changed OOXML parts for the displayed pair; the panel clears when the pair changes. Compare corresponding pages manually; changes in pagination can shift content between pages. Historical preview keeps the selected version visible while displaying the latest version number. Selection is available on the latest version. Drag a rectangle on a page to save a visual selection for the agent; the selection form also accepts page-relative percentages by keyboard. The selection is stored in the session directory and replaces the previous selection. Use `office-use session selection ./draft` to read it and `office-use session selection-text ./draft` to extract text from that region, and `office-use session selection-candidates ./draft` to search for possible OfficeCLI element paths. Stop the server with Ctrl+C. It binds to `127.0.0.1`, uses a random URL token and rejects other Host headers. Anyone who obtains that URL and can reach the local server can view the document, save selections, edit supported elements and restore earlier revisions; keep it private. The preview page offers historical preview, revision restore and a limited element editor. After selecting an area, open “Find selected elements” to search for candidate paths; choose a candidate to load it for review. Candidates are text matches and require verification. Enter an OfficeCLI path, load the element and inspect its content, then save a new revision. The editor supports Word paragraphs and runs, spreadsheet cells, and PowerPoint text elements. It limits content to 4,000 characters; replacing text can change run formatting, and spreadsheet numeric values may be converted. Select formula mode for expressions beginning with `=`; value mode rejects them. Exports use the CLI or MCP. Render fidelity and page layout depend on LibreOffice.

## Inspect for issues

```sh
office-use audit report.docx
```

This uses a saved disk snapshot with OfficeCLI's Open XML schema validator and issues view. The result includes the validator's exit code and original JSON envelope, plus up to 200 issue entries. A nonzero validator exit code or `success: false` requires inspecting its result; an `issues_error` means the issue scan did not finish. The issues list can be truncated, and its reported count describes OfficeCLI's returned results. These checks cover only what OfficeCLI detects. Inspect rendered pages, formulas and the destination application's behavior separately. Save and close external editor sessions before auditing.

## Review edits

```sh
office-use compare original.docx revised.docx
office-use compare-cells original.xlsx revised.xlsx --sheet Forecast --range A1:D20
```

The result contains added, removed and modified OOXML package part names, plus a unified diff of OfficeCLI text views. The comparison reads saved disk snapshots; save and close external editing sessions first. Text views are limited to 2,000 lines per file, then 100,000 characters per view and 500 diff lines; truncation flags are returned. The text view can omit formatting, formulas and other content. Part changes indicate underlying file changes but do not describe their visual or semantic effect. Use `cells`, structured reads and page previews to review the relevant details. Files exceeding 5,000 package parts or 128 MiB uncompressed are rejected.

`compare-cells` compares one worksheet rectangle in saved XLSX files. It reports changed formula text, values and types, with before/after details for the first 500 changed cells and a total count. The range is limited to 10,000 cells. For formula cells, `value` is the stored cached result and its freshness is unknown. The comparison does not cover formatting, charts, comments or worksheet structure; use the broader comparison and visual review alongside it.

## Spreadsheet calculation

Inspect a bounded rectangular range (at most 10,000 cells):

```sh
office-use cells budget.xlsx --sheet Forecast --range A1:D20
office-use recalculate budget.xlsx --out budget-calculated.xlsx
```

`cells` reports formulas, their stored cached values, and cell types, including formula errors. Cache freshness is always `unknown`; a missing cached result is returned as `null`. Rows include blank cells in the requested rectangle. `recalculate` opens a copy in a fresh LibreOffice profile, saves a new XLSX, and refuses an existing output. Read the output again to inspect calculated values and errors. LibreOffice uses its own calculation engine and may change layout or unsupported workbook features; review the resulting file against the source. External links, advanced Excel functions, complex workbooks and fidelity have not been comprehensively validated. Use a saved, closed source and review workbooks containing external links before conversion.

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

The server offers `inspect_file`, `structured_read`, `apply_batch`, `render_pdf`, `preview_pages`, `view_page`, `read_cells`, `recalculate_workbook`, `compare_files`, `compare_cells`, `audit_file`, `start_session`, `session_info`, `session_apply`, `session_restore`, `session_export`, `session_edit_target`, `session_edit`, `session_selection`, `session_selection_image`, `session_selection_text`, and `session_selection_candidates`. `view_page` returns a PNG image to a vision-capable client (maximum 10 MiB). `session_selection` returns the selected revision, page and normalized rectangle, with a stale flag if the session advanced. `session_selection_image` renders and crops that exact revision. Selected text extraction uses `pdftotext` word centers within the rectangle on a freshly rendered PDF and returns text, normalized word boxes, revision and staleness. It is bounded to 5,000 selected words and an 8 MiB page extraction. It can miss partially selected words, reordered text, images, or scanned text; it does not perform OCR. Candidate lookup searches up to three selected text lines against OfficeCLI and returns possible paths with matching text. Results are limited and non-exhaustive: repeated text, wrapped lines, tables, formulas, images and complex layouts can yield ambiguity or missing matches. The paths are not geometrically verified. Check the selected revision and use structured reads and visual context to verify the exact target before editing. Search fragments are passed as OfficeCLI command arguments, which may be visible to other local processes. Paths refer to the machine running the server. The server has access to files available to its process; configure it only in a trusted local environment. OfficeCLI, LibreOffice and Poppler are required for their corresponding tools. Existing output protection and the saved-source requirement also apply over MCP.

## Verification

```sh
python3 office/smoke.py
python3 office/structured_smoke.py  # requires OfficeCLI
python3 office/cell_compare_smoke.py # requires LibreOffice
python3 office/candidates_smoke.py  # requires LibreOffice, Poppler and OfficeCLI
python3 office/selection_smoke.py   # requires LibreOffice, Poppler and OfficeCLI
python3 office/watch_smoke.py       # requires OfficeCLI, LibreOffice and Poppler
python3 office/editor_smoke.py      # requires OfficeCLI
python3 office/session_smoke.py     # requires OfficeCLI
python3 office/audit_smoke.py       # requires OfficeCLI
python3 office/review_smoke.py      # requires OfficeCLI
python3 office/spreadsheet_smoke.py # requires LibreOffice
python3 office/mcp_smoke.py         # requires the MCP extra and OfficeCLI
```
