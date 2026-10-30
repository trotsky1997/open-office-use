# Word workflows

Find target text with `search_word_body`, `search_word_stories`, or `search_word_notes`, and the corresponding `session_` tools. Stories cover headers and footers; notes cover ordinary footnote and endnote paragraphs. Continue paginated results with the same query, `next_offset`, and `snapshot_sha256`. Check `scan_complete`, `complete`, `unverified_paragraphs`, and `unsupported_structure`; separators, text boxes, fields, or other complex content may be excluded or incomplete.

For a unique literal match in a supported paragraph, inspect `session_edit_target` then use `session_replace_text` to preserve supported run formatting. Matches cannot cross hyperlink or annotation boundaries; fields and tracked changes can require another workflow. A result such as `/footnote[@id=1]/p[1]` is a targeted replacement path. Notes preserve the note marker; all references to the same note ID share its text. For headers and footers inspect `story_impact`, linked sections, and shared relationship IDs; first/even display depends on page settings. `session_replace_text_batch` applies 1–25 ordered replacements atomically.

Use `session_add_comment` on a supported body or table paragraph; a unique literal `anchor` targets adjacent runs, while omitting it covers a simple paragraph. Inspect with `list_word_comments` / `session_list_comments`; thread parents and resolved status are reported when mappings are clear. `session_reply_comment` replies to a supported open root, and `session_resolve_comment` resolves or reopens one.

For proposed revisions in supported body, header, or footer paragraphs, use `session_track_replace_text` or `session_track_insert_text` with an author and a unique match. Inspect `list_word_tracked_changes` / `session_list_word_tracked_changes` coverage; records are XML evidence, not edit paths. `session_resolve_tracked_runs` accepts or rejects selected supported insertion/deletion run IDs within one part when requested. Review the resulting revision.

For basic new Word files, `author_file` supports ordered `blocks`: headings, paragraphs with aligned and spaced text, styled or hyperlinked runs with font, size and color, bullets, numbered items, tables with optional repeating headers, proportional column widths, header colors and cell typography, embedded PNG/JPEG images with descriptions, and page breaks. See the project guide for the schema and limits. Source-based authoring appends blocks but may change unsupported features; use targeted session edits for existing rich documents.

For a new document, `author_file` accepts `page_setup` with A4 or Letter size, orientation, margins, header text and footer text with an optional PAGE field. Page numbers are fields updated by a compatible application; inspect the rendered pages.

Word table cells may contain multiple paragraphs with formatted runs and hyperlinks using `rows` cells shaped as `{"paragraphs":[{"runs":[...]}]}`. Render and review cell wrapping and layout.

`session_edit_target` returns a snapshot hash; pass `expected_sha256` to tracked insertion, tracked replacement or paragraph comment creation to bind the action to the inspected document. The viewer supplies this hash for these actions.

Comment inventories return `snapshot_sha256`. Supply it as `expected_sha256` for comment replies or resolved-state changes; the viewer binds these actions to its loaded comment list.
