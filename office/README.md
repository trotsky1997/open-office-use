# Open Office Use — early local harness

A first office-file workbench in the [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use) fork. It offers a JSON CLI for local DOCX, XLSX and PPTX inspection, creation, limited edits, and PDF rendering. It does not require Chrome. The inherited browser tooling remains available under its original name.

## Install

Python 3.10+. PDF rendering requires LibreOffice on PATH; page PNG previews additionally require Poppler `pdftoppm`. The structured operations below require OfficeCLI on PATH (tested with 1.0.147):

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

The server offers `inspect_file`, `structured_read`, `apply_batch`, `render_pdf`, `preview_pages`, `view_page`, `read_cells`, and `recalculate_workbook`. `view_page` returns a PNG image to a vision-capable client (maximum 10 MiB). Paths refer to the machine running the server. The server has access to files available to its process; configure it only in a trusted local environment. OfficeCLI, LibreOffice and Poppler are required for their corresponding tools. Existing output protection and the saved-source requirement also apply over MCP.

## Verification

```sh
python3 office/smoke.py
python3 office/structured_smoke.py  # requires OfficeCLI
python3 office/spreadsheet_smoke.py # requires LibreOffice
python3 office/mcp_smoke.py         # requires the MCP extra and OfficeCLI
```
