# Open Office Use — early local harness

A first office-file workbench in the [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use) fork. It offers a JSON CLI for local DOCX, XLSX and PPTX inspection, creation, limited edits, and PDF rendering. It does not require Chrome. The inherited browser tooling remains available under its original name.

## Install

Python 3.10+, and LibreOffice on PATH for PDF rendering:

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
office-use render output.xlsx --out-dir previews
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

## Verification

```sh
python3 office/smoke.py
```
