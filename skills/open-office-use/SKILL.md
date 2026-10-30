---
name: open-office-use
description: Inspect, create, edit, review, and render local DOCX, XLSX, and PPTX files using the open-office-use CLI or MCP server. Use when working with this harness and its versioned local Office sessions.
---

# Open Office Use

Use `office-use --help` and the [project guide](https://github.com/trotsky1997/open-office-use/blob/main/office/README.md) for installation, MCP configuration, arguments, and fidelity limits. The skill supplies guidance; install the CLI and optional MCP dependency separately. `office-use doctor` or `office_doctor` reports available dependencies; a version probe does not establish output fidelity.

For multi-step work, start a local session from a saved, closed source or a blank format. Read `session_info`, use the latest revision as `base_revision` for edits, and export a selected revision to a new path. A conflict requires re-reading the latest revision. Historical revisions can be previewed, compared, and restored as a new revision. `office-use watch` provides a local viewer when a user wants to follow or edit the session.

For format-specific operations, read only the relevant reference:

- [Word](references/word.md): body, headers, footnotes, comments, and tracked changes.
- [PowerPoint](references/powerpoint.md): slide content, speaker notes, images, and layout review.
- [Spreadsheets](references/spreadsheets.md): bounded grid editing, formatting, formulas, charts, and worksheet views.

Use `office_schema` to discover the installed OfficeCLI element properties before unfamiliar structured operations. `structured_read` and `apply_batch` expose OfficeCLI on copies; its XLSX batches can change formula caches. `dump_office_subtree` / `session_dump_office_subtree` supply bounded starting operations, but can omit charts or sibling dependencies and may require a compatible slide layout. Inspect and verify the replayed result.

For visual selection, inspect `session_selection`, `session_selection_image`, and when useful `session_selection_text` / `session_selection_candidates`. Check revision, staleness, selection changes, and snapshot hashes; candidate text and geometry are evidence to verify, especially with repeated text, hidden slides, images, or partially selected words. XLSX rendered-image responses include a dynamic-array advisory; LibreOffice previews may omit spill results.

Use `inspect_external_relationships` / `session_inspect_external_relationships` to review bounded external OPC relationships without contacting targets; inspect coverage and handle targets as sensitive data. Formulas, field codes, and embedded documents can contain additional links.

For delivery, use `review_document_bundle` / `session_review_bundle`, `view_document_page` / `session_view_page`, `view_contact_sheet` / `session_contact_sheet`, and relevant structured checks. Review bundle flags highlight Word comments, hidden slides, and speaker-note parts or body text; check inventory coverage and inspect other notes shapes separately. `compare_files`, `compare_page_images`, and their session equivalents help review changes; align corresponding pages and inspect coverage, truncation, and application rendering. Explain material fidelity limitations and retain the original. The MCP server accesses local files using its process permissions.
