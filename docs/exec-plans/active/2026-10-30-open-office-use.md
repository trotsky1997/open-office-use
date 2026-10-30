# Open Office Use

Goal: adapt the open-browser-use fork into an agent-friendly office harness. First deliver a local file-based authoring and inspection loop for DOCX, XLSX and PPTX with independent output and PDF review. Validate each format end to end.

Next work: faithful structured inspection, rich authoring, formula calculation and error reporting, page/slide previews, selective edits, and live session integrations. Establish realistic document fixtures and measure preservation before claiming parity with any office editor. Retain upstream attribution and keep browser tooling distinct while deciding what to remove.

## Reference review (2026-10-30)

- [GenOffice](https://github.com/genspark-ai/genoffice): visible editor sessions, CLI/MCP, targeted edits, review and rollback, per-page rendering, and staged slide creation with audit. Its README describes preservation and atomicity as project claims; evaluate them against real fixtures before relying on them. Most of the repository is Apache-2.0; `ee/` has a separate enterprise license.
- [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI): semantic views, element paths and queries, batch operations, OOXML fallback, validation, preview, and MCP. Apache-2.0. On macOS, installed version 1.0.147 successfully created one file per format, added basic content, returned an outline, and passed its schema validator. This checks the basic workflow only.

## Direction

Prioritize evaluating OfficeCLI as an optional existing authoring engine before expanding our Python format operations. A prospective integration needs explicit executable discovery, version reporting, session save/close behavior, a new-output transaction boundary, error propagation and format-preservation tests. Evaluate GenOffice's visible editor and review workflow separately, including distribution and licensing boundaries. Keep authoring, rendering and agent-facing session orchestration distinct so that each can be replaced. Compare both renderers and LibreOffice against representative Office files; do not infer visual fidelity from a schema validation pass.

## Implemented next step

Added optional OfficeCLI-backed outline, get, query and atomic copy-based batches, plus LibreOffice/Poppler page PNG previews. Real OfficeCLI 1.0.147 checks cover create, copy edit, structured reads, failed multi-operation batches and existing output protection in each format. Follow-up remains: rich real-world fidelity fixtures, formula calculation, interactive sessions, visual comparison, and stronger artifact validation.

## MCP access

The optional stdio MCP server exposes structured reads, isolated batch edits, PDF rendering, page previews and image delivery. Tested with Python MCP SDK 1.30.0. It has local filesystem access; session sharing, rich in-app review, and cross-platform validation remain open work.

## Formula workflow

Added bounded cell reads with formula text, cached values and errors, plus explicit LibreOffice recalculation to a protected copy. Verified basic arithmetic, error results and empty ranges through CLI, and calculation through MCP. A bounded workbook-wide scan now reports stored formula errors and empty or missing caches across worksheets, with explicit scan completeness and issue truncation. Revision-bound scans and explicit LibreOffice recalculation are available in CLI, MCP and the viewer, with concurrent-write protection. Advanced formula compatibility, external links and workbook fidelity remain unverified.

## Review

Added saved-file text diffs and OOXML part-change summaries through CLI and MCP. Tested text changes in three formats, identical files and a formatting-only DOCX edit. Text views are bounded and may omit formulas or styling; per-element review, rich diffs, live sessions and visual comparison remain open.

## Artifact checks

Added OfficeCLI schema validation and issue scanning via CLI and MCP, retaining the raw validator result and reporting issue-scan failures. Verified a valid DOCX, invalid OOXML and a formula error; broader Office compatibility and visual evaluation are still required.

## Draft sessions

Added persistent local multi-step sessions with explicit base revisions, concurrent-writer conflict protection and copy-based export through CLI and MCP. Tested all three formats, stale writes, failed edits, competing writers and exports. A visible editor, collaborative CRDT state, undo UI and external-editor synchronization remain open.

## Visible preview

Added a local read-only browser preview that updates for committed session revisions. Tested route isolation, real LibreOffice/Poppler images, and automatic revision refresh in Chrome. Direct editing, selection-aware requests and collaborative synchronization remain open.

## Visual selections

Added page rectangle selection in the local viewer, persisted with revision and page. MCP returns selection metadata, staleness, and a rendered crop of the selected revision. Verified browser drag, stale selection rejection and cross-origin request rejection. Selection-to-element mapping and direct editing remain open.

## Selected text

Added PDF word-geometry extraction for saved visual selections via CLI and MCP. Verified selected text for DOCX, XLSX and PPTX, a bounded DOCX region and historical revision behavior. OCR, exact visual-to-element mapping and complex layout fidelity remain open.

## Selection candidate paths

Added text-based candidate lookup for visual selections via CLI and MCP. Tests cover duplicate text across DOCX, XLSX and PPTX, an empty selection and stale revision handling. The result requires verification; geometric mapping, editable text ranges, OCR and direct editor integration remain open.

## Revision restoration

Added optimistic restore to a new revision through CLI, MCP and the local preview. Original revisions remain intact; cross-origin restrictions and version conflict checks apply. Verified three formats and real Chrome interaction. Direct canvas editing and live collaboration remain open.

## Historical preview

The local viewer can preview a selected historical revision before restoration, while showing the latest revision and restricting selection to the current version. Tested two Chrome tabs across a new commit, a historical preview and restoration. The viewer remains a rendered-page surface rather than a direct editing canvas.

## Element editing

Added limited element editing through the viewer and MCP: load one target at a specified latest revision, review content, and save a new revision. Tested Word text, spreadsheet formulas, PowerPoint titles, stale writes, cross-origin rejection and real Chrome interaction. Simple Word body and table-cell paragraphs and supported PowerPoint text shapes and table cells now support unique literal replacements spanning text runs while retaining run formatting and other package parts. Word hyperlink text and text within bookmark or comment boundaries are also supported without moving anchors. Unsaved element input stays selectable when stale and requires confirmation before replacement; pending edits also trigger a browser navigation warning. Direct canvas editing, collaborative synchronization and advanced formatting remain open.

## Viewer candidates

Connected selection-based candidate lookup to the local viewer. The user chooses a candidate and reviews it before committing an edit. The server checks selection identity and version around the lookup. Verified cross-origin, stale and changed-selection rejection and Chrome interaction. Geometric identity and complete canvas editing remain open.

## Spreadsheet change review

Added bounded cell comparison via CLI and MCP, with formula/value/type differences, unknown cache freshness, full change count and 500-item output cap. Verified formula changes, recalculated cache, missing sheets and truncation. Direct cell formatting is compared by resolved style component, and stored row, column and worksheet-default dimensions are compared separately. OfficeCLI XLSX batches can update formula caches. Theme resolution, conditional formatting and workbook-wide semantic diff remain open.

## Visual revision comparison

Added a side-by-side rendered comparison of a selected revision and latest revision to the viewer. The latest side updates after commits; editing and selection remain disabled while comparing. Tested two Chrome tabs with a new commit and restoration. Automatic visual change detection and pagination-aware alignment remain open.

## Viewer change details

Added on-demand text and OOXML part change details to the visual comparison viewer. The request identifies both revisions and the UI clears old results when the pair changes. Tested real Chrome display, version updates and invalid revision requests. The XLSX comparison viewer additionally shows cell-level values, formulas and direct formatting for a user-selected range; results clear when the revision pair changes. Text views remain bounded and omit some semantics.

## Worksheet grid

Added bounded XLSX worksheet listing and grid editing through the local viewer and MCP. Real OfficeCLI and Chrome checks cover multiple cells, formulas, clearing cells, stale updates, retained unsaved input and origin restriction. Bounded grid and single-cell value edits retain unrelated formula caches, invalidate changed formula caches and request recalculation; validated saved calculation chains are removed when formulas change, and ambiguous chains are rejected. Explicit text input preserves numeric-looking and formula-looking strings; the viewer provides per-cell type overrides and type-only conversion. Declared array, data-table and shared formula ranges are protected from grid edits. Run-preserving replacement supports inline and shared Excel text cells with atomic worksheet and string-table updates; dependent formula caches remain unchanged. Multiline grid text is editable; quoted multiline TSV paste is validated against grid bounds and protected formulas before changing inputs. Unchanged carriage returns remain intact; editing normalizes them to line feeds. Font properties, RGB colors, alignment, wrap and number formats are available for grid subranges through CLI, MCP and the viewer; row heights and column widths can be inspected and changed for bounded ranges. Broader formatting, other advanced formula structures, large sheets and live Office interoperability remain open.

## Slide layout candidates

Added bounded PPTX off-slide and overlap-candidate inspection through CLI, MCP and the revision viewer. Geometry covers rotations and nested group transforms; results include shapes and intersection polygons. Intentional layering, master content and text overflow still require rendered visual review.

## Atomic text batches

Added explicit ordered formatting-preserving text replacements across Word, PowerPoint and Excel as a single revision via CLI and MCP. Failure leaves no published batch revision; concurrent writers compete for the same revision. Verified the three formats, rollback and concurrent publication.
