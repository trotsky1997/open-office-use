# PowerPoint workflows

Use `search_slide_text` / `session_search_slide_text` with `scope: "slides"` for shape and table paragraphs or `scope: "notes"` for speaker-note paragraphs. Results include hidden slides. Page with the same scope, query, optional slide, `next_offset`, and `snapshot_sha256`; check completeness and inspect candidates. Notes results include `slide` and `notes_paragraph` for targeted editing. Masters, charts, SmartArt, and other notes shapes are outside these searches.

`session_replace_text` performs a unique literal replacement in supported slide shape or table-cell paragraphs, retaining run formatting. Use `read_slide_notes` / `session_read_slide_notes` with a one-based slide number and `session_replace_slide_notes_text` for a unique match in a one-based simple paragraph. `session_replace_slide_notes` replaces the entire notes text and resets its formatting. `compare_slide_notes` / `session_compare_slide_notes` compare explicitly corresponding slides and report truncation.

For an embedded picture, use `session_replace_picture` with a local PNG or JPEG; the existing crop remains. `inspect_slide_layout` / `session_inspect_slide_layout` report overlap, off-slide and small-font candidates from run or paragraph-default sizes, plus unresolved font coverage; the viewer lists and highlights these objects; `inspect_slide_text` / `session_inspect_slide_text` report text rendering candidates. Check coverage and inspect rendered pages: intentional overlaps, master content, hidden slides, text overflow, and page-to-slide mapping need review. Contact sheets are overviews; inspect important slides at full size.

For basic new decks, `author_file` can set slide dimensions and create blank slides with positioned textboxes, editable text-bearing shapes, editable lines and arrows, editable tables, native column/bar/line/pie charts with embedded data and optional `show_values` labels; column/bar/line charts accept `value_axis_min` and `value_axis_max` for numeric axis bounds; pie charts also support `point_colors` and `show_percent`, and local PNG/JPEG images; provide `target_slide` for a one-based shape click target and inspect shape and regular text-run click/hover actions with `inspect_slide_navigation` and update supported shape or regular text-run slide jumps using `session_set_slide_navigation` with the inspected snapshot or the viewer’s Slide navigation panel; provide `description` for nonvisual alternative text on positioned elements; use `session_set_slide_description` to update an existing object using an inspected path and snapshot; choose `fit` as `contain` or `cover` to preserve aspect ratio, or `stretch` to fill the frame. See the project guide for units, formatting options, image limits and template requirements. Inspect rendered slides and use OfficeCLI for richer elements.

Use `inspect_slide_charts` / `session_inspect_slide_charts` to inventory saved chart caches, series, categories, source formulas and embedded workbook metadata. Check each reconciliation status and completeness, including when a mismatch is reported: saved embedded workbook values are compared to caches within documented limits, while formula result freshness remains unknown.

Use `session_sync_slide_chart_cache` to repair one fully comparable mismatched reference, including missing points, from saved embedded workbook values, creating a new revision. Choose `chart_part` and the reference index from inspection. Formula source caches require explicit opt-in and may be stale; inspect rendered slides after changes.

Use `session_read_slide_chart_grid` and `session_edit_slide_chart_grid` to inspect and edit an embedded workbook using the chart part and source sheet from chart inspection. The edit creates a revision and can leave chart caches and formula results stale; re-inspect, synchronize supported references and review the slides. Shared workbooks can affect multiple charts.

Set `sync_caches: true` on `session_edit_slide_chart_grid` to synchronize fully comparable affected chart references in the same atomic revision. All charts sharing the workbook must be inspected and initially match; unsupported or stale caches cause the edit to fail. Formula freshness remains unknown.

Verified blank cells can be filled or cleared with atomic cache synchronization. Blanks in merged or multi-cell formula ranges and formulas without saved results remain unverified; chart blank display depends on rendering settings.

Positioned textboxes support rich paragraphs and runs with bullets, levels, fonts, colors and links. Set a run’s `target_slide` to a one-based position in the final deck for an internal click jump; forward references and source slides are supported. A run accepts either `target_slide` or `url`. Use paragraph-level search and targeted replacement for later edits, and inspect rendered slides for wrapping.

Textbox margins, vertical alignment, wrapping and auto-fit modes can be set during authoring. Inspect rendered slides: auto-fit behavior depends on the application, and text beyond saved shape bounds may be flagged.

When authoring new slides, set `notes` on each slide to create editable speaker notes; newlines separate paragraphs. Use notes read/search and session edits for review.

Slide table cells accept strings or `{"paragraphs":[...]}` with the same rich runs, links and paragraph settings as textboxes. Inspect wrapping and use a paragraph-specific path for targeted edits.

Rendered-text candidates can include `paragraph_candidates` for multi-paragraph shapes and table cells. Check truncation and rendered output; table paragraph targets open for supported text replacement, including matches within one hyperlink region; complex structures are read-only and matches cannot cross link boundaries.

Speaker-note paragraph replacement also supports text within one hyperlink region and preserves its relationship; matches crossing hyperlink boundaries are rejected.

Speaker-note search paths like `/slide[1]/notes/paragraph[2]` work with `session_edit_target`, `session_replace_text`, and `session_replace_text_batch`. Batch note and slide edits together for one atomic revision.

Use `session_reorder_slides` with the latest revision and a complete array of one-based slide positions to rearrange an existing deck. Slide IDs, slide parts, speaker notes and custom-show order are retained. Supported nonempty PowerPoint sections keep their members and may be reordered as contiguous groups; interleaving sections, empty sections, other presentation extensions and alternate content are rejected. Slide-number paths change after reordering, so rediscover targets in the new revision.

Use `inspect_slides` or `session_inspect_slides` before reordering to list slide positions, IDs, titles, visibility, notes presence and recognized section membership. `section_status` reports `none`, `supported`, or `unsupported` with an explanation. Results are snapshot-bound, limited to 1,000 slides, and titles and section names are truncated at 500 characters.

In the local viewer, the Slide order panel loads the displayed revision's slide list and recognized sections and saves a complete comma-separated order in the latest revision. Reload after changing revisions.

Speaker-note reads return `snapshot_sha256`. Pass it as `expected_sha256` when replacing full notes or a notes paragraph; the viewer binds these operations to the displayed snapshot.

For picture replacement, pass the selected presentation `snapshot_sha256` as `expected_sha256` to bind the operation to the inspected source. The viewer submits the selection snapshot automatically; local replacement images are read from checked snapshots.

Slide chart inventories return `snapshot_sha256`; pass it as `expected_sha256` to slide chart cache synchronization to bind repair to the inspected presentation.

Use `{"type":"line","x":2,"y":2,"end_x":5,"end_y":2,"color":"236B8E","line_width":3,"arrow":"end"}` for a straight editable connector. Coordinates are inches, width is points, and `arrow` can be `none`, `start`, `end`, or `both`. Endpoints are free positions, so review connections after moving shapes.

For a flowchart node, use `type: "shape"`, `shape_kind` (`rectangle`, `rounded_rectangle`, `ellipse`, `diamond`), geometry and `fill`; add `text` or rich `paragraphs`, text styling, and optional `line_color`/`line_width`. Text is centered vertically; `auto_fit: "shrink"` can reduce overflow. Inspect the rendered slide.

To attach an arrow to shape nodes, give each earlier `shape` a unique `id` and use `type: "connector"` with `start` and `end` objects, each containing `shape` and `side` (`top`, `left`, `bottom`, `right`). This writes native shape connection references; it supports the four documented node shapes and straight lines. Inspect behavior after moving nodes in the destination app.

Slide chart inspection returns `axis_inventory` with saved standard-axis bounds, positions, orientations and log bases. Null bounds are automatic; check `complete` and `issues` and inspect the rendered chart.

Use `session_set_slide_chart_axis_bounds` with an inspected chart part, value-axis ID and snapshot hash to set both explicit bounds in an existing revision; pass null for an automatic bound. Check `affected_paths` and `affected_paths_complete` for shared chart parts, then re-inspect and render. The viewer’s Slide chart axes panel also edits a selected value axis against its displayed snapshot.

Inspect `axis_range_candidates` for saved cache points outside explicit value-axis bounds. It covers one unstacked bar/column or line plot; unsupported structures report their reason. Cache freshness and rendered clipping require separate review.

Chart inspection also reads directly embedded literal category and numeric series data. Check workbook status: literal-only charts may have no embedded worksheet to reconcile or edit.
