# Open Office Use foundation

Forked the browser project locally and added an independent Python CLI for basic DOCX, XLSX and PPTX inspection, creation, copy editing and LibreOffice PDF rendering. Output creation refuses overwrites. Added an agent skill, examples and an end-to-end smoke script. The current CLI is a foundation and does not claim fidelity or feature parity with Codex office tools.

Reference review: documented GenOffice and OfficeCLI capabilities and licensing boundaries. Locally exercised OfficeCLI 1.0.147 with basic create, edit, outline and schema-validation operations for all three formats. Recorded engine evaluation and session lifecycle as next steps; no integration or fidelity claim has been made.

Added optional OfficeCLI structured reads and isolated batch authoring, with exclusive output publication and session closure. Added per-page PNG preview through LibreOffice and Poppler. Verified basic paths for all three formats, including failures and source preservation.

Added optional MCP stdio access to the office workbench with image delivery for page inspection. Verified discovery, authoring, structured reads, visual output and error propagation with the official MCP client.

Added bounded spreadsheet formula/cache inspection and explicit LibreOffice recalculation through CLI and MCP. Verified basic formulas, errors, empty ranges and source protection with a real local calculation engine.

Added bounded saved-file comparison through CLI and MCP, reporting textual excerpts and changed OOXML parts. Verified three formats and formatting-only change detection.

Added audit commands for OfficeCLI schema validation and issue checks with a saved snapshot. Validated real schema errors, formula issues and MCP access.

Added file-backed versioned draft sessions with conflict detection and export via CLI and MCP. Verified all formats, failure and concurrent write handling.

Added loopback browser preview for the latest session revision with random URL access and automatic refresh. Tested real rendering, route restrictions and Chrome revision updates.

Added revision-bound visual area selection in the session viewer and MCP access to metadata and rendered crops. Tested browser interaction, origin restrictions and stale revisions.

Added selected-region PDF text and word geometry through CLI and MCP, retaining revision and staleness context. Verified three formats and narrow-region selection.
