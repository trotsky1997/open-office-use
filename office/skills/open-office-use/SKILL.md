---
name: open-office-use
description: Inspect, create, edit copies of, and render local DOCX, XLSX, and PPTX files with the open-office-use CLI.
---

# Open Office Use

Read the office/README.md for installation, commands, MCP tools, spec formats and limitations. For multi-step work, use a session directory and pass the latest revision as the base for each edit. Inspect source files before editing. Write to a new output path. For structured operations use OfficeCLI through `office-use structured` and `office-use batch` when installed. Save and close the source first. Run `audit` or `audit_file` and inspect validation and issues before delivery. Use `compare` or `compare_files` to review text and package changes in saved files; inspect the actual content and rendered pages for details. Use `office-use preview` to render page PNGs and inspect them visually before delivery. Use `cells` or `read_cells` to inspect formulas and cached values. Cache freshness is unknown. When appropriate, use `recalculate` or `recalculate_workbook` to make a LibreOffice-calculated copy, check errors, and review conversion fidelity. Inform the user about any fidelity or feature limitations relevant to their file.
