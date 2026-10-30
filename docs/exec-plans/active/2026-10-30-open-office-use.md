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

Added bounded XLSX worksheet listing and grid editing through the local viewer and MCP. Real OfficeCLI and Chrome checks cover multiple cells, formulas, clearing cells, stale updates, retained unsaved input and origin restriction. Bounded grid and single-cell value edits retain unrelated formula caches, invalidate changed formula caches and request recalculation; validated saved calculation chains are removed when formulas change, and ambiguous chains are rejected. Explicit text input preserves numeric-looking and formula-looking strings in both the grid and the single-cell editor; formula candidates are checked against the requested expression; the viewer provides per-cell type overrides and type-only conversion. Expanded array, data-table and shared formula ranges are protected; a verified dynamic-array anchor with a one-cell saved range can be edited. Run-preserving replacement supports inline and shared Excel text cells with atomic worksheet and string-table updates; dependent formula caches remain unchanged. Multiline grid text is editable; quoted multiline TSV paste is validated against grid bounds and protected formulas before changing inputs. Unchanged carriage returns remain intact; editing normalizes them to line feeds. Font properties, RGB colors, alignment, wrap, number formats and borders with range outline, interior and per-side colors are available for grid subranges through CLI, MCP and the viewer; row heights and column widths can be inspected and changed for bounded ranges. Empty-interior ranges can be merged and exact merged ranges can be split, with protected content and complex worksheet cases rejected. Table references and legacy/threaded-comment anchors are checked against the merge range so unrelated table and comment parts can remain intact. Frozen panes can be set or cleared through the viewer, CLI and MCP while preserving formula caches; complex worksheet views are rejected. Broader formatting, complex dynamic metadata, broader formula structures, large sheets and live Office interoperability remain open. New dynamic arrays use verified XLDAPR metadata; the spill is unresolved until compatible recalculation, and local LibreOffice did not populate a SEQUENCE spill. Formula scans identify dynamic-array metadata; LibreOffice recalculation requires an explicit override when detected or inspection is incomplete.

## Slide layout candidates

Added bounded PPTX off-slide and overlap-candidate inspection through CLI, MCP and the revision viewer. Geometry covers rotations and nested group transforms; results include shapes and intersection polygons. Intentional layering, master content and text overflow still require rendered visual review.

## Atomic text batches

Added explicit ordered formatting-preserving text replacements across Word, PowerPoint and Excel as a single revision via CLI and MCP. Failure leaves no published batch revision; concurrent writers compete for the same revision. Verified the three formats, rollback and concurrent publication.

## Dynamic-array preview advisory

Rendered XLSX previews disclose XLDAPR metadata or incomplete inspection for the displayed revision and comparison sides. Structured render and image-file results return advisories; MCP image responses include image, text and structured advisory, page and revision metadata. Local LibreOffice preview of SEQUENCE showed only the first result.

## Snapshot-bound rendering

Structured renders, visual results and selection extraction use a copied source and report its SHA-256. Selection candidate text extraction and OfficeCLI queries share one copy. Viewer candidate requests are tied to the displayed preview hash and reject mismatches. Shared render, selection, text-search, tracked-change, review-bundle, OfficeCLI batch and session start/restore/export snapshots check file identity, size and modification metadata during copying and reject detected changes; filesystem metadata checks do not lock writers. Other inspection snapshot paths still need equivalent protection.

## Scoped dynamic formulas

Dynamic candidate validation resolves LET bindings and LAMBDA parameters lexically, including nested expressions and local function calls. Unbound or shadowed-name changes are rejected; verified common formulas through OfficeCLI and versioned grid editing. Complex metadata and native Excel interoperability remain open.

## Speaker notes search

Slide search supports a notes scope with bounded, snapshot-bound pagination, hidden-slide metadata and paragraph-level candidates. Viewer results open the notes editor for targeted replacement; unsupported paragraph content remains marked for review.

## Word footnotes and endnotes

Ordinary footnote and endnote paragraphs can be searched with snapshot-bound pagination and edited through verified part paths. Targeted replacement preserves note markers and supported run formatting; separator notes and complex structures remain outside the edit scope.

## Grid data validation visibility

Grid reads report bounded standard data-validation rules intersecting the loaded cells, with explicit coverage issues for malformed metadata, unsupported extensions and output limits. Grid edits preserve rules and report affected cells without evaluating values. Compatible spreadsheet applications remain necessary to evaluate formula-based and custom rules.

The viewer offers fixed literal list suggestions for unambiguous supported validation rules, preserving values such as `001` and `=text` as text. Absolute one-dimensional references containing verified plain text can also be resolved from the loaded revision, within bounded source limits; simple scoped names resolving to those ranges are supported, while dynamic names, relative references and computed or non-text values remain unresolved.

## Office-first project entry point

Replaced the inherited browser-first root README with English and Chinese Office setup, a runnable authoring example, MCP and skill configuration, and clear links to preserved upstream browser documentation. The project remains early and its full capability and fidelity limits are documented in the Office guide.

## Review visibility for comments and presentation notes

Review bundles flag Word comments, hidden slides and speaker-note parts or body text. The notes inventory returns slide numbers and text presence without copying note contents, with a 500-slide scan limit and explicit placeholder-only scope. Other notes content and comments require independent inspection.

## Small-font review candidates

A real PPTX was authored through OfficeCLI, rendered and inspected. Slide layout inspection and review bundles now flag directly specified runs below 14 pt, including table cells, and report unresolved inherited sizes and scan limits. The threshold is advisory; theme inheritance, auto-fit, grouped scaling and final legibility require rendered review.

The viewer lists small-text candidates and highlights their visible object geometry, with separate font-size coverage status. Table candidates highlight the full table; hidden-slide and page-mapping restrictions remain.

Font-size inspection also uses explicit paragraph default run sizes when a run has no direct size, with direct run settings taking precedence and `size_source` identifying the source. Theme, list-style and layout/master inheritance still require review.

## External relationship inventory

CLI, MCP and revision-aware inspection report bounded OPC external relationships without network access, and review bundles flag their presence or incomplete output. Targets may contain sensitive information. Formulas, field codes, embedded documents and indirect references require separate inspection.

## Basic authoring over MCP

MCP `author_file` exposes the existing JSON-spec authoring path for DOCX, XLSX and PPTX without requiring OfficeCLI. Source-based authoring takes a checked snapshot before loading. Whole-element replacement and library round-tripping retain their documented fidelity limits.

## Structured basic Word authoring

JSON `blocks` in CLI/MCP authoring create ordered semantic headings, formatted text runs, bullets, numbered paragraphs, styled tables with repeating headers, and page breaks. Verified generated DOCX structure and LibreOffice page previews; advanced formatting and fidelity in existing rich documents still require targeted workflows.

## Positioned basic slide authoring

JSON slide specs support new-deck sizing, blank layouts, backgrounds, positioned textboxes, rectangles and local PNG/JPEG images with alt descriptions. Image sources are snapshotted and bounded; existing templates supply their own Blank layout. Validated PPTX structure, MCP, and LibreOffice rendering. Native PowerPoint fidelity and advanced visual features remain open.

PowerPoint image authoring supports `contain` and centered `cover` alongside `stretch`; contain changes the picture frame and cover stores editable crop values. EXIF orientation must be normalized for aspect-preserving modes.

Basic slide authoring also supports positioned, editable tables with text, an optional formatted header and proportional column widths. PPTX table theme inheritance and final text layout require visual review.

## Basic formatted spreadsheet authoring

CLI/MCP JSON specs can now create cell values and formulas together with bounded direct formatting, row and column dimensions, frozen panes and an auto-filter range. Existing filter criteria are protected from replacement. Formula calculation and rich-workbook preservation remain separate workflows.

## Basic spreadsheet charts

CLI/MCP spreadsheet specs support same-sheet column and line charts, inferred or explicit category types and page-width fitting. LibreOffice preview was checked with three textual categories; Excel chart and formula caches remain unpopulated by the basic writer and require separate review.

Basic chart authoring now writes bounded caches from verified literal source values; formula, blank, ambiguous or oversized ranges remain uncached and are reported by chart cache inspection. Subsequent grid edits may make caches stale.

Basic Word blocks now support external HTTP(S)/mailto hyperlinks and aspect-preserving local PNG/JPEG images with accessible descriptions. Rendered pages and targeted hyperlink editing were verified; complex fields and existing-document round-tripping remain separate concerns.

## PowerPoint chart creation

Basic CLI/MCP slide specs support native column and line charts with bounded literal categories, series, colors, cached values and an embedded XLSX workbook. The generated workbook is checked for literal labels and preserved numbers. LibreOffice rendering and direct MCP authoring were verified; native PowerPoint fidelity remains open.

## PowerPoint chart cache inspection

CLI, MCP, session revisions and review bundles expose bounded PowerPoint chart cache inventories, source references and embedded-workbook metadata. Complex charts and scan limits are flagged; formula cache freshness remains unknown.

PowerPoint chart inspection now compares supported chart caches with saved values in embedded workbooks, with bounded per-chart results and review flags. Formula-result freshness remains open.

Supported PowerPoint chart cache mismatches can be synchronized from saved embedded workbook values, one reference per revision, via CLI and MCP; formula caches require explicit opt-in. Embedded workbook grid edits are available in session revisions; cache synchronization remains a separate explicit step.

PowerPoint sessions expose embedded workbook grid reads and edits through CLI/MCP, reusing workbook protections and immutable revisions. Editing can stale chart and formula caches; targeted cache sync and rendered review follow separately.

Optional atomic chart-grid edits synchronize comparable affected chart caches, including inspected charts sharing the workbook, before publishing one revision. Incomplete coverage and unsupported formula caches fail the transaction; formula freshness remains unknown.

PowerPoint chart reconciliation now reports incomplete coverage when a mismatched reference also contains unverified points, so review bundles retain both flags.

Chart cache synchronization can add missing points when saved source values are fully comparable, in XLSX and embedded PPTX chart data. Missing caches and unverified source values remain unsupported.

New PowerPoint chart authoring normalizes axis IDs to positive values, preserving cross-axis references. Column and line chart examples pass OfficeCLI schema validation and LibreOffice rendering.

Chart cache checks and sync handle verified literal blank cells, including filling and clearing points during atomic PowerPoint grid edits. Formula cells with no stored result and blank cells in merged or multi-cell formula ranges stay unverified.

Word block authoring supports run font, size and color plus paragraph alignment, spacing and pagination controls. Generated table header flags use schema-valid markup; OfficeCLI validation and multipage LibreOffice rendering were checked.

New Word documents support page size, orientation, margins, running header/footer text and a PAGE field through CLI/MCP authoring. Two-page LibreOffice rendering and schema validation were verified; native Word and complex multi-section layouts remain open.

Word table authoring supports fixed proportional columns, header fill and ink, and table font settings. Validated OOXML, CLI/MCP, and LibreOffice rendering; complex section layouts and native Word fidelity remain open.

Workbook authoring supports print paper, orientation, area, repeat rows/columns, margins and default/odd-page header/footer text and page numbers. A four-page LibreOffice render verified repeating headings and page numbers with default margins; small margins can suppress running text.

Workbook authoring supports bounded local PNG/JPEG drawings with pixel-preserving aspect ratio, cell anchors and alternative text. Validated source snapshots, existing images and charts, OOXML schema, CLI/MCP and LibreOffice PDF image output; native Excel fidelity remains open.

Positioned slide textboxes support rich runs, links, multiple paragraphs, bullet levels and paragraph spacing. Validated OOXML, targeted paragraph editing, CLI/MCP and LibreOffice rendering; native PowerPoint and complex text formatting remain open.

Slide textbox authoring supports margins, vertical alignment, wrapping and none/shrink/resize auto-fit. LibreOffice shrink was compared with a clipped baseline; resize can render beyond saved shape bounds and remains a review candidate.

Workbook authoring supports named, styled native tables with verified headers and bounded ranges. Targeted grid/text edits protect table headers and totals while permitting data edits; generic OfficeCLI operations require separate review. Native Excel and table-aware header editing remain open.

A revision-bound table column rename updates the header and column metadata together after conservative dependency inspection; structured/indirect references, opaque features and shared parts are rejected. Formula and chart caches remain potentially stale.

Table column rename rewrites supported explicit Table[Column] references in worksheet, chart, validation, conditional-format and defined-name formulas, clears changed cell caches and removes calculation chains. Later revisions also support nested references and implicit references in uniquely identified table contexts, including calculated-column and totals-row metadata. Shared and indirect references remain unsupported.

Workbook authoring now creates bounded literal or same-sheet range dropdown validations; the grid exposes supported options while validation enforcement remains application-dependent.

Workbook authoring supports threshold and formula conditional fills, color scales and data bars. LibreOffice rendering shows representative styles; native Excel rendering remains unverified.

Word table cells support formatted runs, hyperlinks and multiple aligned paragraphs. CLI and OfficeCLI validation and LibreOffice page rendering are covered; native Word remains unverified.

Slide authoring now accepts speaker notes on each new slide; authored notes work with the existing read, search and targeted revision workflows.

Grid inspection now summarizes intersecting conditional-format rules and coverage, and the viewer warns when direct styles may differ from evaluated formatting.

PowerPoint table cells accept formatted paragraphs and hyperlinks, and support search and targeted paragraph edits. LibreOffice rendering and OfficeCLI validation passed; native PowerPoint remains unverified.

Workbook authoring supports explicit literal-text cells, preserving strings such as `=literal` and `#N/A` without changing formula behavior for ordinary strings.

Workbook authoring rejects unsupported cell characters, oversized text and formulas, and non-finite or out-of-range numbers before publishing.

Workbook authoring supports bounded rectangular arrays per sheet, with overlap checks and the same typed-cell validation and source table protections as individual cell writes.

Workbook authoring supports native typed date and millisecond date-time values, respecting the source workbook date epoch.

Date-formatted grid cells support verified ISO date/date-time updates without replacing the saved number format; numeric results are checked against the workbook epoch.

Rendered-text checks offer bounded paragraph-level candidates and table paragraph inspection/targeted replacement; paragraph matching shares container bounds and remains a visual-review heuristic.

PowerPoint targeted paragraph replacement supports linked text within a single hyperlink region and rejects boundary-crossing replacements.

Speaker-note paragraph edits can update text within one hyperlink region while preserving link metadata; cross-boundary edits are rejected.

PowerPoint speaker-note search paths support target inspection and atomic batches combining note and slide paragraph replacements.

Chart cache creation, inspection and synchronization now cover verifiable numeric date sources using their saved serial values and workbook epochs.

Line and column workbook charts can use daily date axes with custom label formats; sub-day timelines and formula-date calculation remain separate.

Workbook authoring supports scatter charts with numeric or sub-day datetime X values, multiple Y series and cached data. Formula-source caches require calculation and review.

Workbook chart authoring supports series colors, legend and gridline visibility, and Y-axis bounds; verify visual output in the target application.

Workbook charts can display value labels. Independent label number formats and native Excel rendering remain to be verified.

Session slide reordering retains slide IDs and related parts, rejects presentation extensions, and requires rediscovering positional slide paths. Custom shows retain their own order.

Slide reordering supports contiguous nonempty PowerPoint 2010 sections and updates section/member ordering; other presentation extensions remain unsupported.

Slide inventory exposes revision-bound positions and supported section membership before reordering, with explicit unsupported-section status and bounded output.

The PPTX viewer supports inspecting slide order and saving a complete new order; snapshot and revision checks protect the request, and package/section limits apply.

Shared OOXML part selection and rewriting use one checked snapshot; slide reorder relationships and viewer hash checks bind to that snapshot. Preprocessing outside this helper and external writers still need independent consistency review.

Grid read, value edit and formatting now use snapshot-bound checks and allow an expected hash; viewer value/style edits bind to the loaded grid. Other grid mutations remain to be reviewed.

Grid merge, freeze and resize now bind validation and writes to checked snapshots; the viewer and MCP can validate against a previously read grid hash.

Element target inspection and direct/replacement edits support expected source hashes; viewer binds those actions to the displayed snapshot. Other element actions need separate consistency review.

Tracked insertion/replacement and new paragraph comments can bind to the inspected target snapshot. Comment replies, resolution, notes and image workflows remain for consistency review.

Speaker-note reads and replacements use checked snapshots; the viewer binds saves and targeted replacements to its loaded notes hash.

Comment inventory and reply/resolution operations use checked snapshots, with expected hashes in MCP and viewer actions.

Tracked-change resolution can enforce the inventory snapshot hash; the viewer validates its preview and supplies the hash.

Picture replacement accepts a source snapshot hash; viewer selections bind the hash, and local image inputs use checked snapshots.

Chart-cache inspection and sync support snapshot-bound repair in XLSX and PPTX; formula-cache freshness remains unknown.

PowerPoint authoring supports editable straight lines and arrows with free-position endpoints; attached connectors and advanced routing remain open.

PowerPoint authoring supports editable text-bearing rectangle, rounded rectangle, ellipse and diamond nodes; inspect rendered text fit and connector placement.

Straight connectors can reference earlier named shape nodes with cardinal connection sites, including ellipse-specific indices; native PowerPoint interaction remains unverified.
