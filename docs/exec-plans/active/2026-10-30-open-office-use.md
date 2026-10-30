# Open Office Use

Goal: adapt the open-browser-use fork into an agent-friendly office harness. First deliver a local file-based authoring and inspection loop for DOCX, XLSX and PPTX with independent output and PDF review. Validate each format end to end.

Next work: faithful structured inspection, rich authoring, formula calculation and error reporting, page/slide previews, selective edits, and live session integrations. Establish realistic document fixtures and measure preservation before claiming parity with any office editor. Retain upstream attribution and keep browser tooling distinct while deciding what to remove.

## Reference review (2026-10-30)

- [GenOffice](https://github.com/genspark-ai/genoffice): visible editor sessions, CLI/MCP, targeted edits, review and rollback, per-page rendering, and staged slide creation with audit. Its README describes preservation and atomicity as project claims; evaluate them against real fixtures before relying on them. Most of the repository is Apache-2.0; `ee/` has a separate enterprise license.
- [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI): semantic views, element paths and queries, batch operations, OOXML fallback, validation, preview, and MCP. Apache-2.0. On macOS, installed version 1.0.147 successfully created one file per format, added basic content, returned an outline, and passed its schema validator. This checks the basic workflow only.

## Direction

Prioritize evaluating OfficeCLI as an optional existing authoring engine before expanding our Python format operations. A prospective integration needs explicit executable discovery, version reporting, session save/close behavior, a new-output transaction boundary, error propagation and format-preservation tests. Evaluate GenOffice's visible editor and review workflow separately, including distribution and licensing boundaries. Keep authoring, rendering and agent-facing session orchestration distinct so that each can be replaced. Compare both renderers and LibreOffice against representative Office files; do not infer visual fidelity from a schema validation pass.
