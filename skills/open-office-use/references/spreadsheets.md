# Spreadsheet workflows

Use `inspect_file` / `session_inspect_workbook` for a bounded sparse overview, `search_cells` / `session_search_cells` for literal text or formulas, and `read_cells` for detailed ranges. Search pagination requires the same query, sheet, `next_offset`, and snapshot hash; check coverage and unverified text. Range reads have response limits; narrow the range on an error.

For edits, `session_sheets` and `session_read_grid` load at most 200 cells. Check `sheet_protected`, `read_only_reason`, `merged_anchor`, text completeness, worksheet view, and `data_validation` coverage and rules. The viewer offers literal list choices and bounded absolute one-dimensional ranges of verified text from the loaded revision when coverage is complete and a single rule applies. Simple workbook- or sheet-scoped names can resolve to those ranges; check `list_resolution`, `list_source`, and `list_name`. Dynamic names, formulas and numeric source cells require review. Grid edits retain validation rules without evaluating them; review affected cells in a compatible spreadsheet application. `session_edit_grid` edits bounded cells; set `type: "text"` on nonempty changes to preserve values such as `00123` or `=literal`. XLSX `session_edit` uses the same value path and supports `literal` mode. Long or unverified cells and protected formula ranges are restricted; targeted `session_replace_text` can preserve supported rich-text runs. `session_replace_text_batch` applies ordered changes atomically.

`session_format_grid` applies supported font, color, alignment, wrap, number format, and borders. Borders support all edges, outline, inside, and individual sides; consult the project guide for property names and color rules. `session_resize_grid` changes entire rows or columns, including cells outside the selected rectangle. `session_freeze_panes` freezes above/left of a specified cell; pass `null` or `A1` to unfreeze. It resets the saved selection and rejects unsupported views. `session_merge_cells` merges an empty-interior range or unmerges an exact existing range. It rejects overlapping tables, multi-cell formulas, non-anchor content or comments, protected sheets, and ambiguous structures. For example, `session_freeze_panes` with `cell: "B2"` freezes the first row and column; `session_merge_cells` with `cell_range: "A1:B2"` and `merge: false` removes that exact merge. Inspect the result in the target application.

Grid value edits retain unrelated formula caches, remove changed formula caches, request sheet recalculation, and remove a validated calculation chain when formulas change. Other caches may be stale. `scan_formulas` / `session_scan_formulas` report stored errors and missing caches, not freshness. `compare_cells` / `session_compare_cells` compare values, formulas, direct styles and dimensions; themes, conditional formatting, and chart semantics need separate review.

Supported dynamic-array formulas require verified XLDAPR metadata and candidate tokens. Their spill and cached values need a compatible calculation application. LibreOffice recalculation rejects detected or uninspectable dynamic-array metadata by default; `allow_dynamic_arrays: true` explicitly allows conversion with potentially incomplete spill results. LibreOffice may change other workbook features, so review any recalculated copy. After changing chart sources, use `scan_chart_caches` / `session_scan_chart_caches`; `session_sync_chart_cache` updates or adds points and removes points for verified blank cells in a fully comparable reference, with explicit opt-in for formula sources. Rescan and review rendering.

For basic workbook creation, `author_file` supports `sheet_options` for freeze panes, auto-filter ranges, row/column sizes, direct formats, number formats, editable column/line charts and optional page-width fitting in the same request as cell values. Formula results are not calculated. Source-based library round-tripping can alter unsupported features and caches; use targeted session editing where preservation matters.
 Basic chart authoring caches supported literal sources within documented bounds; formula and other unsupported sources can leave chart caches missing. Formula caches are not calculated. Inspect caches and recalculate where needed.

For printable authored sheets, `sheet_options.print_options` sets paper, orientation, print area, repeating rows/columns, margins, and default/odd-page header/footer with optional page number. Inspect every rendered page; small margins can suppress running text.

Use `author_file` with `sheet_options.images` to embed a local PNG or JPEG as a cell-anchored drawing. Provide pixel width and a useful `description`; inspect rendered pages and print-area coverage.

`author_file` can create native styled/filterable Excel tables using `sheet_options.tables`. Table headers and totals are read-only in the targeted grid and text replacement workflows; use a table-aware operation and review table metadata for changes there.

Use `session_rename_table_column` to update a supported table header and column metadata together. Explicit simple and nested structured references are rewritten, along with implicit references in uniquely identified table cells and calculated-column or totals-row formula metadata, preserving references to other tables. Ambiguous implicit references, unsupported table-column metadata, indirect references and opaque dependencies cause a refusal. Recalculate and inspect formula and chart caches afterward.

For new workbook dropdowns, `author_file` accepts `sheet_options.list_validations` with a target `range` and either literal `values` or a one-dimensional same-sheet `source`. The local grid displays supported suggestions; spreadsheet applications enforce the saved validation rule.

Use `sheet_options.conditional_formats` to create native numeric threshold, formula, color-scale, or data-bar rules in authored workbooks. Rules evaluate in spreadsheet applications; inspect rendered output.

`session_read_grid` reports intersecting standard conditional-format rules and coverage issues. It does not evaluate rules or include complete rule styles; use a rendered workbook or spreadsheet application to inspect effective appearance.

For basic `author_file` workbook creation, use `{"type":"text","value":"=literal"}` for nonempty literal text that resembles a formula or error. Untyped strings starting with `=` remain formulas.

Workbook creation rejects oversized cell text and formulas, unsupported XML characters, non-finite numbers and numbers outside Excel numeric range before publishing. Use text for identifiers needing exact digits.

For tabular workbook creation, `author_file` accepts `ranges` keyed by sheet, each containing `{"start":"A1","values":[[...],...]}`. Blocks are rectangular and cannot overlap each other or individually authored cells.

For native spreadsheet dates, use typed values such as `{"type":"date","value":"2026-10-31"}` or `{"type":"datetime","value":"2026-10-31T09:30:45.125"}`. Date-times are timezone-free and limited to milliseconds; use a number format for the desired display.

For date-formatted cells, ISO date and millisecond date-time grid edits verify the resulting value against the workbook epoch and retain the existing date format. Use explicit text mode when the input should be literal text.

Chart authoring caches literal date sources using the workbook epoch. Cache scanning and sync use exact stored numeric date values when worksheet XML is inspectable; ISO-date XML storage and ambiguous or oversized worksheets remain unverified.

Daily line and column chart categories use a native date axis when date values are detected; `category_type: "date"` enables it for whole-day serials or formula sources, and `date_format` controls axis labels. For sub-day timelines use `type: "scatter"` with datetime X values and an appropriate `date_format`; numerical scatter plots also use a numeric X axis.

Chart specifications accept `series_colors` as one six-digit RGB string per Y series, `legend`, `show_gridlines`, and `show_values` (numeric data labels) as booleans, and finite numeric `y_min` / `y_max` with the minimum below the maximum. Line and scatter series use straight segments. Inspect the rendered output in the target application.

Grid reads return `snapshot_sha256`. Pass it as `expected_sha256` to `session_edit_grid` or `session_format_grid` when editing a previously inspected grid; a changed source is rejected. The same option is available for `session_merge_cells`, `session_freeze_panes`, and `session_resize_grid`; the viewer passes the loaded hash for all five operations.

Chart cache scans return `snapshot_sha256`; pass it as `expected_sha256` to session cache synchronization to bind the repair to inspected workbook bytes.

For workbook navigation, author a hyperlink with `location: {"sheet":"Details","cell":"A1"}` or use `session_set_grid_hyperlink` with `url: null` and the same `location`; the target sheet must exist. For native source links in newly authored cells, use `{"type":"hyperlink","value":"Source","url":"https://example.com/report"}`. Cell text is literal, and subsequent grid value edits preserve the link target. Use `session_set_grid_hyperlink` with an inspected snapshot, or the viewer’s grid controls, to change or remove a supported single-cell link; inspect `session_read_grid` hyperlink metadata and coverage, audit external relationships, and review the destination.

Chart-cache scans report `literal_sources` and `status: literal` for bounded fixed chart data with no worksheet source reference. Cell edits do not update that data; inspect the chart before delivery. Invalid or oversized literal data remains unverified.

Use `session_set_chart_literal_value` with an inspected chart part, literal reference index, one-based point and snapshot to edit an existing fixed numeric chart value. Worksheet cells stay unchanged, and all chart placements sharing that part are affected. Render and review.

Use `session_set_chart_literal_category` with a scanned literal category reference to update a one-based category point across matching series of a workbook chart. Mismatched or referenced categories are rejected; worksheet cells remain unchanged.

Chart-cache scans expose bounded plot and series indices and direct literal series names. Use `session_set_chart_literal_series_name` to rename an inspected literal series in a single plot; referenced names require changing their source cells.

The viewer’s Chart cache checks panel can select inspected fixed-data samples or literal series names and save a revision. It shows up to 200 candidates and rejects large integers outside JavaScript’s exact range. CLI/MCP reject integer values that cannot be represented exactly as binary64; client and Excel precision can be more limited.
