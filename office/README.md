# Open Office Use — early local harness

A first office-file workbench in the [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use) fork. It offers a JSON CLI for local DOCX, XLSX and PPTX inspection, creation, limited edits, and PDF rendering. It does not require Chrome. The inherited browser tooling remains available under its original name.

## Install

Python 3.10+. PDF rendering requires LibreOffice on PATH; page PNG previews additionally require Poppler `pdftoppm`, and selected text extraction requires `pdftotext`. The structured operations below require OfficeCLI on PATH (tested with 1.0.147):

```sh
python3 -m pip install ./office
```

The Codex skill is discoverable from the repository root and can be installed separately:

```sh
npx skills add trotsky1997/open-office-use -g -a codex --skill open-office-use -y
```

The skill supplies agent guidance; install the CLI and, for MCP, the optional dependency as described below. OfficeCLI, LibreOffice and Poppler are separate system tools.

Run `office-use doctor` to probe the available executables, versions and optional MCP import. MCP clients can call `office_doctor` for the same report. Capability flags summarize the dependencies used by structured authoring, PDF rendering, page images and selected-text extraction. A successful version probe confirms startup only; it does not validate a document or guarantee rendering fidelity. The command returns a report even when dependencies are missing.

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

`author` and `render` prepare each output in a temporary directory on the destination filesystem, then publish it with an exclusive hard link. Failure before publication leaves no output from that attempt; a competing writer's output is preserved. Filesystems without hard-link support return an error. A forcibly interrupted process may leave its temporary directory behind. When editing an XLSX copy, `author` rejects workbooks with unverified shared strings; supported targeted session edits remain available.

Use `office-use search-word report.docx --query 'Revenue'`, `office-use session search-word ./draft --revision 0 --query 'Revenue'`, or MCP `search_word_body` / `session_search_word_body` to locate case-sensitive literal text in body and nested table paragraphs. Results provide candidate paths for `session_replace_text`, bounded excerpts and overlapping occurrence counts. Each page scans up to 10,000 paragraphs and returns at most 100 matches; when `next_offset` is present, continue with the same query, the returned offset and `snapshot_sha256` (`--offset` and `--snapshot-sha256` in the CLI). A changed snapshot is rejected. `scan_complete`, `complete`, `unverified_paragraphs` and `unsupported_structure` describe coverage for the scanned page. Headers, footers, notes, text boxes and unsupported wrappers are outside this search; use `stories` for supported headers and footers. Complex paragraph content may be omitted or joined differently from the rendered view. Inspect the target, require an unambiguous match and let targeted edit validation check the paragraph before modifying it. Search copies the saved DOCX and enforces the 5,000-part and 128 MiB package limits.

For related Word headers and footers, use `office-use search-word report.docx --scope stories --query 'Revenue'`, the corresponding session command, or MCP `search_word_stories` / `session_search_word_stories`. The viewer's search scope selector offers the same operation. Results contain relationship-based paragraph paths and package parts, including supported tables. The same paragraph and result limits, snapshot-bound pagination, uncertainty and structure coverage fields apply. Up to 200 header/footer relationships are searched; other document stories are outside this scope. A part shared by multiple relationship IDs appears for each ID. Load a result to inspect linked sections before editing; display of first/even variants depends on page settings and pagination. Viewer targets over 4,000 characters remain unavailable.

For presentations, `office-use search-slides deck.pptx --query 'Revenue'`, `office-use session search-slides ./draft --revision 0 --query 'Revenue'`, and MCP `search_slide_text` / `session_search_slide_text` search shape and table paragraphs, including supported groups and hidden slides. Supply `--slide` or `slide` for a one-based slide number. Results include candidate paths, hidden-slide status, occurrence counts and bounded excerpts. Each page scans at most 10,000 items (shapes and paragraphs) and returns at most 100 matches; continue with `next_offset` and `snapshot_sha256`, preserving the query and slide. Check coverage fields for unsupported structures or uncertain text. Masters, layouts, notes, charts and SmartArt content are outside the search. Paths and text are candidates for targeted editing; inspect the slide and let edit validation check the target. Search uses a saved snapshot and enforces the same package limits as Word search.

For XLSX, `inspect` and MCP `inspect_file` return a bounded sparse sample of stored cells. They inspect up to 50 worksheets, scanning up to 10,000 stored cells and returning up to 100 populated cells per sheet, with values clipped to 500 characters. Recognized hidden worksheets are included and chart sheet names are reported separately; unsupported sheet types can be omitted by openpyxl. `sample_complete`, `worksheets_truncated`, `chartsheets_truncated`, `value_truncated` and `text_complete` describe the limits. Declared dimensions can be inaccurate. Numeric and date samples are raw stored values; shared-formula followers can lack formula text. `text_complete: null` indicates missing formula text; unverified shared strings and raw Excel escape sequences are marked incomplete. Use `cells` or `read_cells` for decoded values in a specific range and review formula caches separately. The inspector reads a saved snapshot, rejects packages exceeding 5,000 parts or 128 MiB uncompressed, and loads the shared-string table through openpyxl. `office-use session inspect-workbook ./draft --revision 0` and MCP `session_inspect_workbook` inspect an exact revision. The viewer's “Workbook overview” displays the same sample for its displayed revision.

To locate text outside that sample, use `office-use search-cells book.xlsx --query 'Revenue'`, `office-use session search-cells ./draft --revision 0 --query 'Revenue'`, or MCP `search_cells` / `session_search_cells`. The case-sensitive literal search scans stored worksheet text and formula text, including hidden sheets and sparse cells; results contain cell addresses and bounded excerpts. `--sheet` or `sheet` restricts the search to one named worksheet. Each page scans at most 100,000 stored cells and returns at most 200 matches. When `next_offset` is present, continue with that offset and the returned `snapshot_sha256`, keeping the query and sheet unchanged; the CLI options are `--offset` and `--snapshot-sha256`. A changed snapshot is rejected. Counts and `scan_complete` describe the current page and its remaining scope; `complete` is true only for a fully verified search from offset zero. Check every page's `unverified_text_cells`: complex shared strings, Excel escapes, unsupported rich-text content and shared-formula followers can make coverage incomplete. Supported plain and rich shared strings are checked directly against the package XML; Excel escape syntax follows the considerations documented in [Microsoft’s ST_Xstring notes](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/bd0aa042-434a-4ca7-b25f-4e1fd25a954d). Chart sheets, chart contents and calculated values are outside the search. Use `cells` to inspect a located range and check formula cache freshness separately. The operation copies the saved workbook and enforces the same package limits as the overview; later pages rescan preceding cells.

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

The `author` command sets whole paragraphs, cells or text frames. Replacing paragraph or shape text drops its run-level formatting. The libraries may alter or drop unsupported Office features when saving existing files; retain the original and review the output. Formula strings are stored, not recalculated by `author`. LibreOffice rendering may recalculate and can differ visually from Microsoft Office. Inspect is a basic content extraction and is not a full fidelity representation (e.g. charts, text in DOCX tables during paragraph edits, speaker notes, and embedded objects). Rendering produces PDF; use a PDF viewer to inspect pages visually. The `author` command does not support encrypted or macro-enabled files, live editing, collaboration, comments, tracked changes, cloud documents, or rich styling.

## Structured OfficeCLI operations

OfficeCLI provides element paths, queries, formatting, charts, images and other operations. Its full command and property schema is available through `officecli help`. `structured` returns the OfficeCLI JSON data for an outline, element, or query:

```sh
office-use schema xlsx --operation add --query chart
office-use schema xlsx --element chart --operation add --query datarange
office-use structured input.docx outline
office-use structured input.docx get '/body/p[1]'
office-use structured input.docx query 'paragraph'
```

`office-use schema` and MCP `office_schema` query the locally installed OfficeCLI version. Without `--element`, they list matching elements and paths; with an element they return its operations, property definitions, aliases and examples. The query matches element names and paths in a catalog, or property names, aliases and descriptions in an element schema. For `add`, `set` and `get`, property results are filtered by the operation; `query` and `remove` filter element availability while returning the matching property descriptions. The returned version identifies the schema source. OfficeCLI schemas describe the installed executable; validate and visually inspect authored files.

`batch` creates a new file or applies an OfficeCLI JSON batch to a copy:

```json
[{"command":"add","parent":"/body","type":"paragraph","props":{"text":"Executive summary","bold":"true"}}]
```

```sh
office-use batch --spec operations.json --out new.docx
office-use batch --source original.docx --spec operations.json --out revised.docx
```

For example, an XLSX chart can be added to a workbook whose `Sales` sheet contains category and value columns in `A1:B3`:

```json
[{"command":"add","parent":"/Sales","type":"chart","props":{"chartType":"column","dataRange":"Sales!A1:B3","title":"Revenue","anchor":"D2:J15"}}]
```

Save that array as `chart.json` and call `office-use batch --source sales.xlsx --spec chart.json --out charted.xlsx`, or pass it to MCP `session_apply` for a new session revision. Check the installed chart schema, source ranges, rendered output and chart caches before delivery.

To extract a starting batch from a saved document or a session revision:

```sh
office-use dump input.docx '/body/p[1]' | jq '.operations' > paragraph-ops.json
office-use session dump ./draft --revision 1 --path '/slide[1]'
```

MCP offers `dump_office_subtree` and `session_dump_office_subtree`. The result includes the snapshot SHA-256 and OfficeCLI's operation array, including its `meta` item; inspect the paths and operations before passing them to `batch` or `session_apply`. Paths may target existing content. Subtrees can depend on styles, numbering, themes, masters or layouts from sibling parts. OfficeCLI 1.0.147 was observed omitting charts from an XLSX sheet dump, and a slide dump using a numeric layout required a compatible target template. Compare source and replayed structure and render the result before delivery. Dumps are limited to 1 MiB of JSON and 1,000 operations; larger results are rejected without returning a partial batch. Source and extracted operations can contain sensitive document content.

Operations run on a temporary file. A successful batch is closed before the complete result is published to a new path; errors leave the requested output absent. Existing outputs are never replaced. This publication uses a hard link on the destination filesystem; filesystems that do not support hard links return an error. Use a saved and closed source file: edits held in another OfficeCLI resident session are not included in the disk copy. Only the tested OfficeCLI version is known to work; its operation schemas and rendering fidelity must be checked against the target version and documents. These commands use the separately installed OfficeCLI executable; it is not bundled.

`preview` creates a new directory containing one PNG per rendered page. It refuses an existing directory. For a numbered overview of up to 12 pages, use `office-use contact-sheet slides.pptx --out overview.png --start 1 --count 12`; choose another start page to continue. The equivalent MCP tools are `view_contact_sheet` for a saved file and `session_contact_sheet` for a specific revision. Each returns a native PNG image, with the rendered page range and total in the header. These page numbers refer to LibreOffice's PDF output; hidden slides can change the mapping to PowerPoint slide numbers. Inspect full-size page images for small text and details, since an overview, successful render, or schema validation alone does not establish visual quality or Office fidelity.

To inspect one rendered page without producing all page PNGs, use `office-use render-page slides.pptx --page 2 --out page-2.png`. Add `--box 0 0 1 0.5` to crop to the top half; coordinates are normalized left, top, right, bottom from the top-left. MCP `view_document_page` and `session_view_page` return the page or crop as a native image, with an explicit session revision for the latter. Whole-page images have a maximum dimension of 1,800 pixels. Crops are rendered again at up to a 7,200-pixel full-page scale, targeting a 1,800-pixel maximum crop dimension; coordinates are rounded to raster pixels. Very small regions or low-resolution embedded images may need another source. Outputs are limited to 10 MiB and existing PNG files are protected.

## Multi-step draft sessions

A session is a local directory of saved revision files. Start from a saved source, or pass `--format docx`, `xlsx` or `pptx` to start blank. The directory must be new and its parent must exist.

For an existing source, startup checks the copied snapshot for ZIP packaging, required package metadata and a main content type matching its extension. This is a basic format check; use `audit` and visual review to assess document validity and fidelity. If startup fails, the new session directory is removed.

```sh
office-use session start ./draft --source original.docx
office-use session info ./draft
# Replace one match in a simple Word body paragraph, creating revision 1
office-use session replace-text ./draft --base 0 --path '/body/p[1]' --find 'old text' --replace 'new text'
office-use session apply ./draft --base 1 --spec operations.json
office-use session restore ./draft --base 2 --revision 0
office-use session export ./draft --revision 3 --out final.docx
```

`replace-text` and MCP `session_replace_text` find exactly one literal match in a Word body, header or footer paragraph, including matches spanning multiple text runs. Replacement text uses the first matched run's formatting; other runs and all other package parts remain intact. It preserves ordinary hyperlinks, bookmarks and comment anchors when the match stays within one region. Matches crossing a hyperlink or anchor boundary are rejected. Ambiguous matches, signed documents, control characters, fields, tracked changes and other unsupported structures are also rejected. Paths use one-based physical table, row, cell and paragraph indices, including nested tables. A paragraph may also be addressed by its saved `paraId`; duplicate IDs within its container are rejected. `session_edit_target` exposes `replace_text_path_supported` for path eligibility; actual paragraph structure is checked when applying the replacement. Packages are limited to 5,000 parts and 128 MiB. The edited XML part is reserialized, so visually review the result.

List header and footer paragraphs with `office-use stories input.docx`, `office-use session stories ./draft --revision 0`, MCP `list_word_stories` or `session_list_word_stories`, or the viewer's “Word headers and footers” panel. These paths use relationship IDs, for example `/header[@id=rId9]/p[1]`, and are distinct from OfficeCLI's numbered header paths. `references` identifies explicit section references; `linked_sections` traces each default, first and even reference through subsequent sections, and `same_part_ids` identifies other relationships pointing to the same part. Check all such IDs before editing: changes affect every section using the part. First and even page variants depend on document settings, section properties and pagination; links describe references, while actual display requires visual review. Word's default header inheritance behavior is described in the [Microsoft interoperability notes](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/5de15e59-3ec1-4f80-aa4d-00bdd447b86f).

`reference_resolution_complete: false` indicates unsupported section locations or a limit: at most 5,000 sections and 2,000 linked section entries are resolved. Documents with more than 200 header/footer relationships are rejected by the inventory. Inventory text concatenates Word text nodes and can omit fields or other content. It lists at most 200 paragraphs and 4,000 characters each; `complete` and per-paragraph `truncated` identify limitations. Unsupported wrappers or excessive nesting make the paragraph inventory incomplete. The viewer offers text replacement for listed paragraphs; header and footer comments are not supported.

For a loaded header or footer paragraph, `session_edit_target` returns `story_impact` with linked sections from every relationship pointing to that part, alongside its completeness flag. The viewer shows the same impact before replacement.

For PPTX sessions, `replace-text` and `session_replace_text` also accept paths such as `/slide[1]/shape[1]/paragraph[1]` or `/slide[1]/shape[@id=2]/paragraph[1]`. Slides follow the presentation order, even when package part names have been reordered; a slide part referenced by multiple slide entries is rejected. Shape and group indices each count their own element type; shape IDs from structured reads are also accepted. Nested group paths are supported through CLI and MCP. A shape path without a paragraph is accepted only for a single-paragraph text body. Replacement uses the first matched run's formatting and preserves the other package parts. Table-cell paths such as `/slide[1]/table[1]/tr[1]/tc[1]/paragraph[1]` use one-based physical row and cell indices; merged-cell placeholders are rejected and the merged origin can be edited. Select a paragraph explicitly when a cell or shape contains more than one. The viewer loads supported table cells read-only and offers paragraph-based replacement. Paragraphs containing line breaks, fields or run hyperlinks, and shape containers with alternate content, are rejected; charts and notes require other workflows. The viewer offers this operation for supported targets that OfficeCLI can load. Review the rendered output.


Add a Word review comment to a simple nonempty body or table-cell paragraph with `office-use session add-comment ./draft --base 0 --path '/body/p[1]' --author 'Reviewer' --text 'Please review'`. MCP `session_add_comment` and the viewer's element editor provide the same operation. It adds a new revision and returns the comment ID. By default it anchors the whole paragraph; pass `--anchor "exact phrase"`, the MCP `anchor` argument, or the viewer’s anchor field to select one unique literal phrase within adjacent text runs. Splitting runs preserves their text and formatting. Literal matching rejects repeated or missing phrases and ranges that cross or lie within hyperlink or annotation boundaries. With an explicit anchor, separate links and existing anchors elsewhere in the paragraph are retained. Whole-paragraph comments require a simple paragraph. Fields, tabs, tracked structures, unsafe run identities, and digitally signed packages are rejected. The operation accepts plain-text comments up to 4,000 characters. When extended comment metadata already exists, new root comments receive matching thread, paragraph and, where present, durable-ID and extensible records; duplicate, malformed or unlinked metadata is rejected. Legacy documents keep their existing metadata model. Mention and application-identity metadata are not generated.

Reply to an open root comment using `office-use session reply-comment ./draft --base 1 --parent-id 0 --author 'Editor' --text 'Acknowledged'`, MCP `session_reply_comment`, or the viewer's comment list. The reply inherits the root comment's exact main-body anchor and creates a new revision. The parent must appear among the first 200 comments, have one complete ordered body anchor whose range markers are direct paragraph children, and have an unambiguous open root-thread state. Reopen a resolved thread first. Legacy threads receive Word 2013 metadata when needed. When a document has a uniquely mapped `commentsIds` part, the reply receives a distinct durable ID; an existing `commentsExtensible` part also receives the matching UTC record. The operation rejects unlinked, incomplete, malformed or ambiguous modern metadata, including an extensible part without IDs. Mentions and application identity metadata are not generated. See the [Word comment ID](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/9c360cd7-653f-4d82-82be-7bda2488c0c1) and [extensible comment](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/a7b57225-42e5-43e7-8d98-d90eabf3ca25) specifications. Replies to replies are not supported. Review the result in Word; native Word interoperability has not yet been tested.

Resolve or reopen a root comment with `office-use session resolve-comment ./draft --base 1 --id 0 --resolved true` (use `false` to reopen), MCP `session_resolve_comment`, or the comment list in the latest viewer revision. This creates a new revision. For a legacy comment with a complete main-document anchor, the operation adds Word 2013 extended metadata and, if needed, a unique paragraph ID. If an extended record already exists, it must identify a unique root comment. A legacy anchored comment with no extended record can receive one when newer comment-ID and extensible metadata are absent. Ambiguous or malformed mappings, replies and unsupported modern metadata are rejected. Other comment parts are preserved. Review the resulting file in Word; native Word interoperability has not yet been tested.

Read saved comments with `office-use comments file.docx` or `office-use session comments ./draft --revision 1`. MCP offers `list_word_comments` and `session_list_comments`; the viewer can load comments for the displayed revision. The result includes the first 200 comments, author, date, plain-text body and main-document anchor hints, with truncation and scan-completeness flags. Paragraph paths cover supported body and table structures; fields, deleted content, drawings and other complex content can make extracted anchor text incomplete. Anchors outside the main body, unsupported wrappers and malformed or partial ranges may lack a usable path. When a valid Word 2013 `commentsExtended` relationship maps a comment by the final paragraph’s `w14:paraId`, `resolved` and reply parent IDs are exposed. Missing, invalid, duplicate or unlinked metadata remains unknown and is identified by the metadata status fields; parent IDs may refer to comments outside the first 200 returned items. Other modern comment extensions are not interpreted. The mapping follows [Microsoft’s CT_CommentEx specification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/9660dacc-2ceb-4352-87d2-42ba1184f522). Comment text is limited to 4,000 characters per item, anchor text to 2,000 characters and paths to 20 per item. Inspect the original document for full review context.

Inspect existing Word revisions with `office-use tracked-changes file.docx`, `office-use session tracked-changes ./draft --revision 1`, or MCP `list_word_tracked_changes` / `session_list_word_tracked_changes`. The result includes a snapshot hash, the saved tracking setting when known, and a bounded inventory of common insertion, deletion, move, range-marker and formatting-change XML elements from the main document and related headers, footers, footnotes and endnotes. Entries include their type, parent, author, date, XML path hint and bounded text. A paragraph-mark deletion or formatting revision can have no text; XML elements do not map one-to-one to the revisions shown by Word. See [Microsoft's tracked-revision examples](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-accept-all-revisions-in-a-word-processing-document). Check `scan_complete`, `issues` and `records_truncated`: at most 1,000 relevant relationships, 200 parts and 10,000 records are scanned, and the first 200 records are returned. Comments, other package parts, unsupported revision types, field semantics and full formatting diffs are outside this inventory. XML paths are inspection hints, not editable element paths. The viewer’s “Word tracked changes” panel inspects its displayed revision. Report contents can include sensitive text and author metadata.

To insert tracked text adjacent to an existing unique anchor, use `office-use session track-insert-text ./draft --base 0 --path '/body/p[1]' --anchor 'existing' --text 'new ' --position before --author 'Editor'`, or MCP `session_track_insert_text`. The viewer provides Insert before and Insert after alongside tracked replacement; Find supplies the anchor and Replacement supplies the new text. The result includes the insertion revision ID for later acceptance or rejection. The inserted run inherits formatting from the first anchor run for before, or the last for after. The same supported body, header and footer paths, range safeguards, and package restrictions as tracked replacement apply. The returned part and ID identify the insertion for later resolution. Inspect the resulting revision in Word.

To propose a tracked Word text replacement, run `office-use session track-replace-text ./draft --base 0 --path '/body/p[1]' --find 'old' --replace 'new' --author 'Editor'`, or call MCP `session_track_replace_text`. The viewer offers “Track replacement” after loading a supported body, header or footer paragraph. Review the displayed linked-section impact before editing a header or footer, since all sections referencing that part share the change. A unique literal match becomes a deletion record and, when replacement is nonempty, an insertion record in a new revision; deleted text retains its original run formatting, and the inserted text uses the first matched run's formatting. A match can span adjacent runs, but cannot cross hyperlink or annotation boundaries. Paragraphs containing existing tracked content, fields or unsupported structures are rejected. Targets inside tracked move or custom XML ranges, tracked paragraph or table structures, and parts with ambiguous or unmatched range markers are also rejected. The operation does not change the document's tracking setting; an empty replacement creates a deletion only. The original revision remains available. IDs are chosen after checking Word XML parts; signed packages are rejected. Inspect the resulting revision and review it in Word; native Word interoperability has not been tested.

To accept or reject selected simple Word insertion/deletion run records, use `office-use session resolve-tracked-runs ./draft --base 1 --part word/document.xml --id 12 --id 13 --decision accept`, or MCP `session_resolve_tracked_runs` with the part and IDs from a fresh tracked-change inventory. Use `reject` or `accept: false` to restore deleted runs and discard inserted runs. The viewer permits selecting candidate records and applying one decision within one part; backend validation determines whether each can be resolved. All selected records are validated before a new revision is published; earlier revisions remain available. A shared header or footer part can affect multiple sections. IDs must be unique and identify direct paragraph runs with supported content. Moves, tracked structural or formatting changes, nested revisions, complex run contents, selections inside tracked move or custom XML ranges, and parts with ambiguous or unmatched tracked ranges are rejected. Paired range markers elsewhere in the same story are preserved; move pairing and full revision validity are not assessed. These operations preserve the remaining package parts and reserialize the edited part. Review the result in Word; native Word interoperability has not been tested.

For an embedded PowerPoint picture, use `office-use session replace-picture ./draft --base 0 --path '/slide[1]/picture[@id=2]' --image replacement.png`, or MCP `session_replace_picture` with a local image file. In the viewer, select a picture, choose its geometric candidate, and upload a replacement. Static PNG and JPEG images are accepted up to 10 MiB and 40 megapixels. The operation creates a new revision and retains the picture's position, size, rotation, crop, and other slide properties; a new media relationship keeps other pictures using the original image unchanged. Linked images, animated images, pictures with unsupported blip extensions or effects, and digitally signed packages are rejected. Existing crop can change how the replacement appears; inspect the rendered revision. The original media remains in the package.

For XLSX sessions, `replace-text` and `session_replace_text` also accept a text cell path such as `/Sales Data/A1`. Inline and shared rich-text runs retain their formatting. Plain `str` cells without a formula are supported, including text written by the grid editor. Shared strings are reused when equivalent or added as a new entry, leaving other cells that referenced the original unchanged. Cell styles, hyperlinks, ordinary comments and unrelated package parts are retained. Formula cells, array/data-table/shared formula ranges, merged-cell placeholders, phonetic content, unsupported metadata and Excel escaped-text sequences are rejected. Formula caches elsewhere are left unchanged and can become stale after editing; use the calculation and review workflow when needed.


Each successful batch creates the next revision. `--base` must match the latest revision; a stale or concurrent competing write fails. A failed batch leaves the previous revision intact. Restoring a historical revision creates a new latest revision; it uses the same base-revision conflict check and keeps all earlier versions. `info` lists file paths for use with `structured`, `compare`, `audit` and `preview`. Export copies any revision to a new output outside the session directory. Session operations never replace the source or an existing export. Keep the session directory private to its owner and do not edit its revision files directly: the session protocol assumes those files remain unchanged. Save and close external editing sessions before creating a session from a source. Session history persists until the directory is removed manually.

To watch the latest revision in a browser, run this in a separate terminal:

```sh
office-use watch ./draft
```

Open the printed URL on the same machine. The preview follows committed revisions and shows LibreOffice/Poppler page images. Open the revision control and choose “Preview selected revision” to inspect an earlier version before restoring it; “Compare with latest” displays the selected and latest rendered pages side by side; “Show latest” returns to the current version. The latest side refreshes when another edit is committed. Open “Text and file changes” and select “Load changes” to inspect a bounded text diff and changed OOXML parts for the displayed pair; the panel clears when the pair changes. For XLSX comparisons, enter a worksheet and cell range in “Worksheet changes” to inspect changed values, formulas and direct formatting alongside the pages. The result is tied to the displayed revision pair and clears when either the pair or inputs change. Compare corresponding pages manually; changes in pagination can shift content between pages. Historical preview keeps the selected version visible while displaying the latest version number. Selection is available on the latest version. Drag a rectangle on a page to save a visual selection for the agent; the selection form also accepts page-relative percentages by keyboard. The selection is stored in the session directory and replaces the previous selection. Use `office-use session selection ./draft` to read it and `office-use session selection-text ./draft` to extract text from that region, and `office-use session selection-candidates ./draft` to search for possible OfficeCLI element paths. Stop the server with Ctrl+C. It binds to `127.0.0.1`, uses a random URL token and rejects other Host headers. Anyone who obtains that URL and can reach the local server can view the document, save selections, edit supported elements and restore earlier revisions; keep it private. For XLSX sessions, “Edit worksheet range” lists sheets and loads up to 200 cells into a keyboard-accessible grid. A tab-separated rectangular clipboard range can be pasted starting at the focused cell, then reviewed before saving. Paste rejects the entire block if it extends past the loaded range or touches a protected cell. Quoted tabs and escaped quotes are supported; multiline cell text is unsupported. Clipboard data is limited to 20 KB, and the final JSON request has its own 20 KB limit. Only changed cells are sent in one versioned batch. A leading `=` writes a formula; other input is passed as a value and OfficeCLI may infer numbers or dates. Clearing an input clears that cell. Declared array, data-table and shared formula ranges are read-only in the grid, including cells whose formula anchor is outside the displayed range. Merged-cell placeholders are read-only and identify their anchor, even when the anchor is outside the displayed range; overlapping merges are read-only. On a protected worksheet, cells with locked direct styles and unstyled empty cells are read-only, while explicitly unlocked cells can be edited. Grid formatting is disabled on protected worksheets. The grid can apply bold, an RGB fill and an Excel number format to a selected subrange in a new revision. Save pending cell edits first. Patterned fills keep their pattern when their foreground color changes; theme colors are not displayed in the grid. Other advanced workbook structures and formatting need separate review. A viewer grid request is limited to 20 KB, so large changes must be split. When another edit advances the version, unsaved input stays visible and selectable in read-only fields. Reloading a grid or element with pending changes asks before replacing the input, and the browser warns before leaving with unsaved edits. Element text also remains selectable after its target becomes stale.

The preview page offers historical preview, revision restore and a limited element editor. After selecting an area, open “Find selected elements” to search for candidate paths; choose a candidate to load it for review. Candidates are text matches and require verification. Enter an OfficeCLI path, load the element and inspect its content, then save a new revision. The editor supports Word paragraphs and runs, spreadsheet cells, and PowerPoint text elements. Loaded supported Word, PowerPoint and Excel text targets, including table cells, offer “Replace once” for a unique match while retaining run formatting. It limits content to 4,000 characters; replacing text can change run formatting, and spreadsheet numeric values may be converted. Select formula mode for expressions beginning with `=`; value mode rejects them. Exports use the CLI or MCP. Render fidelity and page layout depend on LibreOffice.

“Search document text” searches the displayed revision using the format-specific search described above, including continuation batches. Word and PowerPoint results can load a candidate into the element editor when viewing the latest revision; inspect it before editing. Excel results can open a matching cell in the grid when viewing the latest revision; changing the grid prompts before discarding unsaved cell edits. Search results clear when the displayed revision or query changes, and the format-specific coverage limits still apply.

## PowerPoint speaker notes

```sh
office-use notes slides.pptx --slide 1
office-use session notes ./slides-draft --revision 0 --slide 1
office-use session replace-notes ./slides-draft --base 0 --slide 1 --text-file ./speaker-notes.txt
office-use session replace-notes-text ./slides-draft --base 1 --slide 1 --paragraph 1 --find 'old phrase' --replace 'new phrase'
```

Slide numbers are one-based and follow presentation order. Reading a slide without a notes part does not create one. Replacement writes a new session revision and creates a notes part when needed. It replaces the complete speaker-notes text and resets its paragraph and run formatting; slide text and other package parts are preserved. The edit is rejected if the library would change unrelated package parts, if the notes placeholder is missing, or if the document is digitally signed. Notes text is limited to 100,000 characters; read results indicate truncation. The original session revision remains available. MCP provides `read_slide_notes`, `session_read_slide_notes` and `session_replace_slide_notes`. Inspect notes and the deck in the destination application before delivery.

For a smaller edit, `replace-notes-text` and MCP `session_replace_slide_notes_text` replace one unique literal match within a one-based notes paragraph. The match can cross runs, and the replacement uses the first matched run's formatting. Other runs, paragraphs and package parts are retained. Paragraphs containing fields, line breaks, hyperlinks or other unsupported structures are rejected; ambiguous matches and shared notes parts are also rejected. Find and replacement are each limited to 4,000 characters and cannot contain control characters. Verify the result in the destination application.

The session viewer's “Slide speaker notes” panel reads the displayed revision and saves changes on the latest revision. Its paragraph replacement control retains run formatting and requires any pending full-text edits to be saved or copied first. Slide numbers include hidden slides and can differ from rendered page numbers. Historical notes and truncated results are read-only. If the session advances while text is being edited, the unsaved text stays selectable and read-only; copy it or reload before editing the new revision. Loading other notes prompts before discarding unsaved text.

## Review a single snapshot

```sh
office-use review-bundle report.docx --out-dir ./report-review
office-use session review ./draft --revision 2 --out-dir ./draft-review
```

The bundle copies the saved source once and records its SHA-256 and size in `report.json`. It runs OfficeCLI validation and issue scanning, plus Word comment and tracked-change inspection, XLSX formula-cache scanning or PPTX layout inspection as appropriate. It also produces `preview.pdf` and an `overview.png` for up to the first 12 rendered pages. `check_errors` lists checks that could not execute; `flags` identifies specific findings such as schema failures, formula errors or incomplete scans. Read each check's details and inspect the rendered pages. An absent error or flag does not certify correctness or layout quality. The preview may differ from Microsoft Office and can recalculate workbook formulas during rendering. Report contents can include document comments and formulas; keep the bundle with the same care as the source. Save and close the source before review.

The output directory must be new. A failed individual check is recorded in the report and other checks continue; if rendering fails, the report remains available without visual artifacts. MCP provides `review_document_bundle` and `session_review_bundle`, which return local artifact paths, flags and the snapshot hash. A session bundle targets the requested immutable revision and must be outside its session directory.

XLSX review bundles also run the chart-cache check below. `chart_cache_mismatch`, `chart_cache_missing` and `chart_cache_scan_incomplete` flag findings and coverage gaps. The report can contain chart source references and cell values; treat it as sensitive workbook content.

## Inspect for issues

```sh
office-use audit report.docx
```

This uses a saved disk snapshot with OfficeCLI's Open XML schema validator and issues view. The result includes the validator's exit code and original JSON envelope, plus up to 200 issue entries. A nonzero validator exit code or `success: false` requires inspecting its result; an `issues_error` means the issue scan did not finish. The issues list can be truncated, and its reported count describes OfficeCLI's returned results. These checks cover only what OfficeCLI detects. Inspect rendered pages, formulas and the destination application's behavior separately. Save and close external editor sessions before auditing.


For PowerPoint geometry, inspect a saved file or one revision:

```sh
office-use inspect-layout deck.pptx
office-use session inspect-layout ./slides-draft --revision 2
```

The matching MCP tools are `inspect_slide_layout` and `session_inspect_slide_layout`; the viewer can check its displayed revision. In the viewer, choose a candidate to highlight its visible geometry on the corresponding page, including the selected side of a revision comparison. Highlights are disabled when slides are hidden, visibility is unknown, preview page counts differ, or slide and preview aspect ratios differ. An object fully outside the slide has no visible area to highlight. Results report visible slide objects extending beyond the slide and geometric overlaps involving a text-bearing shape or table. Each candidate includes slide and object IDs, path hints, draw-order hints, bounds and polygons in inches from the slide's top-left; overlap polygons are clipped to the visible slide. Rotated and nested group transforms are considered. Treat overlaps as candidates: backgrounds, intentional layering, transparency, strokes, shadows and actual glyph shapes are not resolved. The check does not measure text overflow or scan master/layout content, chart labels, SmartArt internals, notes or hidden objects. Verify path hints and inspect rendered slides. Limits are 10,000 shapes, 200,000 checked pairs, eight nested groups, and 200 results per category; completeness and truncation flags identify partial reports. Packages are limited to 5,000 parts and 128 MiB.

To check rendered text boxes and table cells, run `office-use inspect-slide-text deck.pptx` or `office-use session inspect-slide-text ./slides-draft --revision 2`; MCP offers `inspect_slide_text` and `session_inspect_slide_text`. The viewer's slide layout panel includes the same check and can load candidates in the editor, and PPTX review bundles report `slide_text_candidates` and `slide_text_scan_incomplete`. The check compares normalized source text with PDF words whose centers lie inside each unrotated top-level text box or supported table cell, including merged-cell origins. Results provide slide, shape or table-cell path, bounds and bounded text excerpts for visual review. A candidate can indicate overflowing or clipped text, extraction order or encoding differences, overlapping text, or renderer differences. Conversely, text within a box can be obscured or too small. Hidden slides, unknown visibility, page-count mismatches and aspect-ratio mismatches prevent mapping. Groups, flipped or malformed tables, rotated text, masters, layouts, chart text and images are outside the check. Text stored in merged-cell placeholders makes the table ineligible. Limits are 100 slides, 10,000 shapes, 10,000 physical table cells, 2,000,000 word/shape comparisons, 200 candidates and a 32 MiB PDF text extraction. Review `mapping_valid`, `complete`, `skipped` and truncation fields. This check requires LibreOffice and Poppler `pdfinfo` and `pdftotext`; it does not perform OCR. See [Poppler's pdftotext documentation](https://manpages.debian.org/bookworm/poppler-utils/pdftotext.1.en.html) for bounding-box extraction.

## Review edits

```sh
office-use compare original.docx revised.docx
office-use compare-cells original.xlsx revised.xlsx --sheet Forecast --range A1:D20
office-use compare-notes original.pptx revised.pptx --before-slide 1 --after-slide 2
office-use session compare-notes ./slides-draft --before 0 --after 1 --before-slide 1 --after-slide 2
```

The result contains added, removed and modified OOXML package part names, plus a unified diff of OfficeCLI text views. The comparison reads saved disk snapshots; save and close external editing sessions first. Text views are limited to 2,000 lines per file, then 100,000 characters per view and 500 diff lines; truncation flags are returned. The text view can omit formatting, formulas and other content. Part changes indicate underlying file changes but do not describe their visual or semantic effect. Use `cells`, structured reads and page previews to review the relevant details. Files exceeding 5,000 package parts or 128 MiB uncompressed are rejected.

`compare-notes` compares speaker notes from two explicitly selected slides, including hidden slides. Choose corresponding slides manually when the order has changed. The result reports whether each notes part exists, whether text changed, and a unified text diff. Each notes text is capped at 100,000 characters, the diff input at 2,000 lines per side, and output at 500 lines. `truncated` marks an incomplete diff; `text_changed: null` means equality is unknown when both clipped prefixes match. Formatting and other notes objects are outside this text comparison. MCP offers `compare_slide_notes` and `session_compare_slide_notes`. In the session viewer, compare a selected revision with the latest and open “Text and file changes” to compare the corresponding speaker notes.

For visual review, `office-use compare-pages original.pptx revised.pptx --before-page 2 --after-page 2 --out diff.png` renders the selected PDF pages and creates before, after and red change-map panels. The JSON result reports the fraction of pixels whose largest RGB channel difference is at least 16/255; red marks are expanded slightly for visibility. MCP `compare_page_images` compares saved files, and `session_compare_page_images` compares explicit session revisions. In the viewer, compare a selected revision with the latest, open “Text and file changes”, and choose one rendered page from each revision under “Visual page changes”. Changing pages or advancing the latest revision clears the old comparison. Compare corresponding rendered pages: inserted pages and hidden slides can change page numbering. Different raster dimensions are rejected. Pages with the same aspect ratio are normalized to the same raster size, so changes in physical page size may not be apparent. The metric is a visual aid: rendering and antialiasing can change pixels, and differences below the threshold are omitted. Inspect full pages and structural changes before delivery.

`compare-cells` compares one worksheet rectangle in saved XLSX files. It reports changed formula text, values, types and direct cell formatting, with before/after details for the first 500 changed cells and a total count. Formatting includes font, fill, border, alignment and protection as resolved Open XML component fragments, plus the number format; component IDs are resolved within each workbook before comparison. The range is limited to 10,000 cells. For formula cells, `value` is the stored cached result and its freshness is unknown. `text_comparison_complete: false` means one or more displayed text values could not be verified. The comparison does not evaluate conditional formatting, workbook theme changes, inherited row or column formatting, charts, comments or worksheet structure; use the broader comparison and visual review alongside it.

These merged-cell and worksheet-protection checks apply to the session grid, single-cell editing and text replacement. `session_read_grid` returns `sheet_protected`, `locked`, `merged_anchor` and `read_only_reason` for review; unverified text cells are read-only. Text or formulas exceeding 4,000 UTF-16 code units are displayed read-only in the grid and cannot be formatted there. For supported text cells, use targeted `session_replace_text` for a small edit. Unstyled empty cells are treated as locked when the sheet is protected; row or column style inheritance is not resolved. The lower-level `session_apply` and `apply_batch` pass explicit OfficeCLI operations through and do not enforce these editor checks. Inspect the saved workbook and its intended permissions after editing.

Range reads use verified plain or rich shared strings from package XML where possible; string values with `text_complete: false` require review. Range reads copy the saved workbook once so formula and cached-value views use the same snapshot. They reject packages above 5,000 parts or 128 MiB uncompressed, as well as responses exceeding 1,000,000 estimated serialized cell-data characters. Request a smaller range when that limit is reached; the operation returns an error and no partial grid. The same limits apply to cell comparisons and grid reads. Save and close external editing sessions before reading.

The grid, single-cell editor and `author` reject literal text containing an Excel escape-like sequence such as `_x0041_`; the tested writer emits unescaped syntax, so interpretation can vary by application. Formula expressions are not restricted by this check. Lower-level OfficeCLI batch operations pass through without this validation, so inspect their outputs in the destination application.

## Spreadsheet calculation

Inspect a bounded rectangular range (at most 10,000 cells):

```sh
office-use cells budget.xlsx --sheet Forecast --range A1:D20
office-use scan-chart-caches budget.xlsx
office-use session scan-chart-caches ./draft --revision 1
office-use session sync-chart-cache ./draft --base 1 --part xl/charts/chart1.xml --reference 2
office-use scan-formulas budget.xlsx
office-use recalculate budget.xlsx --out budget-calculated.xlsx
```

`scan-chart-caches` compares supported cached chart points with stored worksheet values from one saved snapshot. This can reveal mismatches after direct cell-text edits leave chart parts unchanged. MCP provides `scan_chart_caches` and `session_scan_chart_caches`; the viewer checks the displayed revision under “Chart cache checks”. Results include chart part names, source references and bounded mismatch examples. They may include chart parts that are no longer referenced by a worksheet. Numeric comparisons use stored values; blank cells, dates, errors, external references, named ranges, multidimensional ranges, literal chart data and newer chart types can be unverified. Formula-cell values may themselves be stale. A mismatch is a review candidate, and a match covers only the compared points. `complete: false` identifies missing caches, unsupported sources, chart extensions, charts without recognized references or limits. Inspect the chart and source workbook in the destination application before delivery.

The scan covers at most 50 chart parts, 100 references, 2,000 source cells per reference and 10,000 source cells overall; chart XML is limited to 4 MiB per part. It returns at most 20 mismatch examples per reference with values clipped to 500 characters. It does not calculate formulas, refresh caches or change the workbook. Save and close external editing sessions first.

For a fully comparable mismatch, `session sync-chart-cache` or MCP `session_sync_chart_cache` copies stored worksheet values into the existing points of one selected chart reference and creates a new revision. Use the chart `part` and one-based `reference` index from a fresh scan; a chart part can be shared by multiple placements. The operation rejects missing points, unverified values, escaped Excel text, chart extensions, external data and signed packages. It preserves other package parts and reserializes the selected chart XML. Source formulas require an explicit `--allow-formula-caches` / `allow_formula_caches: true` opt-in to use their saved results; recalculate first when appropriate. The viewer offers sync for eligible mismatch candidates in the latest revision and requires formula sources to be handled separately. Rescan and inspect the chart after syncing; formula cache freshness remains unknown.

`scan-formulas` scans stored cells across worksheets, including hidden sheets, and reports counts and the first 200 formula errors, literal error cells, and empty or missing formula caches in separate lists. Formula text is OOXML text without a leading `=` and is clipped to 500 characters; shared-formula followers may have empty formula text. An empty cached string can be intentional. `complete: false` means the one-million-cell limit stopped the scan and counts cover only scanned cells; package limits are 5,000 parts and 128 MiB. This scan does not calculate formulas or determine whether existing caches are current. `cells` reports formulas, their stored cached values, and cell types, including formula errors. Cache freshness is always `unknown`; a missing cached result is returned as `null`. Rows include blank cells in the requested rectangle. `recalculate` opens a copy in a fresh LibreOffice profile, saves a new XLSX, and refuses an existing output. Read the output again to inspect calculated values and errors. LibreOffice uses its own calculation engine and may change layout or unsupported workbook features; review the resulting file against the source. External links, advanced Excel functions, complex workbooks and fidelity have not been comprehensively validated. Use a saved, closed source and review workbooks containing external links before conversion.


For a versioned XLSX session, scan its latest saved revision and explicitly recalculate into a new revision:

```sh
office-use session start ./budget-draft --source budget.xlsx
office-use session scan-formulas ./budget-draft --base 0
office-use session recalculate ./budget-draft --base 0
office-use session scan-formulas ./budget-draft --base 1
```

The equivalent MCP tools are `session_scan_formulas` and `session_recalculate`. Both require the latest base revision; competing writes are rejected. The local viewer's “Workbook calculation and checks” offers both operations, clears obsolete scan results, and keeps pending edits available. The scan examines saved caches; LibreOffice recalculation creates a new revision and may alter workbook features. Compare the revisions and inspect resulting errors and layout before delivery.

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

The server offers `office_doctor`, `office_schema`, `inspect_file`, `session_inspect_workbook`, `search_cells`, `session_search_cells`, `scan_chart_caches`, `session_scan_chart_caches`, `session_sync_chart_cache`, `inspect_slide_layout`, `session_inspect_slide_layout`, `inspect_slide_text`, `session_inspect_slide_text`, `search_slide_text`, `session_search_slide_text`, `structured_read`, `dump_office_subtree`, `session_dump_office_subtree`, `apply_batch`, `render_pdf`, `preview_pages`, `view_page`, `view_document_page`, `session_view_page`, `compare_page_images`, `session_compare_page_images`, `view_contact_sheet`, `session_contact_sheet`, `read_cells`, `scan_formulas`, `recalculate_workbook`, `compare_files`, `compare_cells`, `audit_file`, `review_document_bundle`, `session_review_bundle`, `start_session`, `session_info`, `session_apply`, `session_restore`, `session_recalculate`, `session_scan_formulas`, `session_export`, `session_edit_target`, `session_edit`, `session_replace_text`, `session_track_replace_text`, `session_track_insert_text`, `session_resolve_tracked_runs`, `read_slide_notes`, `session_read_slide_notes`, `compare_slide_notes`, `session_compare_slide_notes`, `session_replace_slide_notes`, `session_replace_slide_notes_text`, `session_add_comment`, `session_reply_comment`, `session_resolve_comment`, `list_word_comments`, `list_word_tracked_changes`, `session_list_word_tracked_changes`, `list_word_stories`, `search_word_body`, `session_search_word_body`, `search_word_stories`, `session_search_word_stories`, `session_list_word_stories`, `session_list_comments`, `session_replace_picture`, `session_sheets`, `session_read_grid`, `session_edit_grid`, `session_format_grid`, `session_selection`, `session_selection_image`, `session_selection_text`, and `session_selection_candidates`. `view_page` returns a PNG image to a vision-capable client (maximum 10 MiB). `session_selection` returns the selected revision, page and normalized rectangle, with a stale flag if the session advanced. `session_selection_image` renders only the selected PDF page and crops the exact selected revision; call `session_selection` to check whether it is stale. Selected text extraction uses `pdftotext` word centers within the rectangle on a freshly rendered PDF and returns text, normalized word boxes, revision and staleness. It is bounded to 5,000 selected words and an 8 MiB page extraction. It can miss partially selected words, reordered text, images, or scanned text; it does not perform OCR. Candidate lookup searches up to three selected text lines against OfficeCLI. For PPTX it also matches the selection against visible shape geometry, including images and empty shapes, when slide visibility, rendered page count and aspect ratio permit a reliable page mapping. Geometric candidates are listed first and carry overlap fractions; the viewer labels the match method. Hidden slides or uncertain mapping fall back to text search. Geometry describes transformed shape bounds rather than exact painted pixels, and master content, hidden objects and some complex elements are omitted. Results are limited and non-exhaustive: repeated text, wrapped lines, tables, formulas, images and complex layouts can yield ambiguity or missing matches. Check the selected revision and use structured reads and visual context to verify the exact target before editing. Search fragments are passed as OfficeCLI command arguments, which may be visible to other local processes. Paths refer to the machine running the server. The server has access to files available to its process; configure it only in a trusted local environment. OfficeCLI, LibreOffice and Poppler are required for their corresponding tools. Existing output protection and the saved-source requirement also apply over MCP.

## Verification

```sh
python3 office/smoke.py
python3 office/structured_smoke.py  # requires OfficeCLI
python3 office/cell_compare_smoke.py # requires LibreOffice
python3 office/candidates_smoke.py  # requires LibreOffice, Poppler and OfficeCLI
python3 office/selection_smoke.py   # requires LibreOffice, Poppler and OfficeCLI
python3 office/watch_smoke.py       # requires OfficeCLI, LibreOffice and Poppler
python3 office/grid_constraints_smoke.py # merged and protected cells
python3 office/string_cell_smoke.py  # grid-to-text replacement and formula guard
python3 office/dump_smoke.py        # bounded extraction and replay fidelity
python3 office/schema_smoke.py      # installed schema discovery and chart authoring
python3 office/chart_cache_smoke.py # chart-cache comparison and review bundle
python3 office/workbook_inspect_smoke.py # sparse, bounded workbook inspection
python3 office/range_safety_smoke.py # range snapshot, response limit and long-cell safety
python3 office/grid_smoke.py        # requires OfficeCLI
python3 office/paste_smoke.py       # requires Node.js
python3 office/stories_smoke.py      # Word headers and footers
python3 office/word_replace_smoke.py # run-preserving Word replacement
python3 office/word_anchor_smoke.py  # requires python-docx 1.2+ for comment fixture
python3 office/slides_replace_smoke.py # run-preserving PowerPoint replacement
python3 office/cell_text_smoke.py     # requires OfficeCLI and xlsxwriter
python3 office/editor_smoke.py      # requires OfficeCLI
python3 office/session_smoke.py     # requires OfficeCLI
python3 office/audit_smoke.py       # requires OfficeCLI
python3 office/review_bundle_smoke.py # multi-format snapshot review
python3 office/review_smoke.py      # requires OfficeCLI
python3 office/spreadsheet_smoke.py # requires LibreOffice
python3 office/formula_scan_smoke.py # requires LibreOffice
python3 office/session_calc_smoke.py # requires LibreOffice
python3 office/contact_sheet_smoke.py # rendered overviews
python3 office/comment_smoke.py      # DOCX comments
python3 office/comment_range_smoke.py # exact comment anchors
python3 office/thread_comment_smoke.py # Word comment thread metadata
python3 office/picture_smoke.py      # PPTX picture replacement
python3 office/notes_smoke.py        # PPTX speaker notes and revision safety
python3 office/notes_compare_smoke.py # speaker notes diffs and truncation
python3 office/notes_watch_smoke.py  # viewer notes routes and revision safety
python3 office/layout_smoke.py       # slide geometry checks
python3 office/selection_geometry_smoke.py # slide selection with real PDF rendering
python3 office/mcp_smoke.py         # requires the MCP extra and OfficeCLI
```
