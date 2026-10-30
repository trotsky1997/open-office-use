"""Local browser preview and visual selection for a versioned office session."""
import json
import base64
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import review
import visual
import selection_candidates
import session
import spreadsheet
import snapshot

PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Office session preview</title><style>
body{margin:0;font:16px system-ui,sans-serif;background:#eef1f4;color:#182333}
header{position:sticky;top:0;background:#fff;padding:1rem 1.5rem;border-bottom:1px solid #ccd3da;z-index:1}
h1{font-size:1.1rem;margin:0 0 .3rem}p{margin:0;color:#48596b}main{max-width:1050px;margin:1.5rem auto;padding:0 1rem}
.page{position:relative;width:fit-content;max-width:100%;margin:1rem auto;touch-action:none;cursor:crosshair}
img{display:block;max-width:100%;height:auto;background:white;box-shadow:0 2px 12px #0002}
.box{position:absolute;border:2px solid #0867c4;background:#087dd126;pointer-events:none;display:none;box-sizing:border-box}
details{margin:.6rem 1.5rem;background:#fff;border:1px solid #ccd3da;border-radius:.4rem;padding:.65rem .8rem}
summary{cursor:pointer;font-weight:600}form{display:flex;align-items:center;gap:.65rem;flex-wrap:wrap;padding-top:.6rem}
#comparison-text,#comparison-parts,#formula-scan-output,#layout-scan-output,#slide-text-output,#chart-cache-output,#grid-dimensions{max-height:18rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:.75rem;border-radius:.3rem}
input{width:4.5rem}#picture-file{width:min(22rem,70vw)}button,select,input,textarea{font:inherit}button{cursor:pointer}form p{flex-basis:100%}.grid-scroll{overflow:auto;max-height:32rem;flex-basis:100%}input[readonly],textarea[readonly]{background:#f4f6f8}table{border-collapse:collapse}th,td{border:1px solid #ccd3da;padding:.15rem}#grid-output textarea{display:block;width:10rem;min-height:2.4rem;resize:vertical;box-sizing:border-box}#grid-output select{max-width:10rem;font-size:.8rem}
.comparison-page{position:relative;width:100%}.comparison-page img{display:block}.layout-overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden}.layout-overlay polygon{vector-effect:non-scaling-stroke;stroke-width:2}
.comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.comparison section{min-width:0}.comparison h2{font-size:1rem;margin:.5rem 0}.comparison img{width:100%}
@media(max-width:700px){.comparison{grid-template-columns:1fr}}
#visual-diff-image{display:block;max-width:100%;height:auto}#visual-diff-image[hidden]{display:none}#compare-sheet{width:min(14rem,70vw)}#compare-range{width:8rem}#cell-comparison-output td{max-width:24rem;overflow-wrap:anywhere}
#word-find,#word-replacement,#comment-anchor{width:min(24rem,65vw)}#edit-path{width:min(28rem,80vw)}#edit-value{width:min(40rem,90vw);min-height:6rem}#edit-form label{display:flex;gap:.4rem;align-items:center}

</style></head><body><header><h1>Office session preview</h1><p id="status" role="status">Loading…</p><p id="selection" role="status">Drag on a page to save a selection for the agent.</p><p id="render-advisory" role="status" hidden></p></header>
<details><summary>Restore a previous revision</summary><form id="restore-form">
<label for="restore-revision">Revision</label> <select id="restore-revision" required></select>
<button type="button" id="preview-revision">Preview selected revision</button><button type="button" id="compare-revision">Compare with latest</button><button type="button" id="show-latest">Show latest</button><button type="submit">Restore as new revision</button><p id="restore-status" role="status"></p></form></details>
<details id="candidate-panel"><summary>Find selected elements</summary>
<p>Matches use text and, when available for PowerPoint, visible shape geometry. Results may be incomplete or ambiguous. Verify the target before editing.</p>
<button type="button" id="candidate-search" disabled>Find candidates</button><p id="candidate-status" role="status"></p><ul id="candidate-list"></ul><div id="picture-panel" hidden><p id="picture-target"></p><label>Replacement image <input id="picture-file" type="file" accept="image/png,image/jpeg"></label> <button type="button" id="picture-replace">Replace picture</button><p>PNG or JPEG, up to 10 MiB. Existing crop and shape size remain; review the new revision.</p><p id="picture-status" role="status"></p></div></details>
<details id="search-panel"><summary>Search document text</summary>
<p>Search the displayed saved revision. Results are candidates; inspect their context before editing. Coverage can be incomplete for complex content.</p>
<form id="text-search-form"><label id="text-search-scope-label" hidden>Scope <select id="text-search-scope"><option value="body">Body</option><option value="stories">Headers and footers</option><option value="word-notes">Footnotes and endnotes</option><option value="slides">Slide text</option><option value="notes">Speaker notes</option></select></label> <label>Find <input id="text-search-query" maxlength="200" required></label> <button type="submit" id="text-search-start">Search</button> <button type="button" id="text-search-next" disabled>Next results</button></form>
<p id="text-search-status" role="status"></p><ul id="text-search-results"></ul></details>
<details id="edit-panel"><summary>Edit an element</summary><form id="edit-form">
<label>Element path <input id="edit-path" required maxlength="512" placeholder="/body/p[1]"></label>
<button type="button" id="edit-load">Load element</button>
<label>Kind <select id="edit-mode" disabled></select></label>
<label>Content <textarea id="edit-value" maxlength="4000" disabled></textarea></label>
<button type="submit" id="edit-save" disabled>Save as new revision</button>
<fieldset id="word-replace-panel" hidden><legend>Replace text while retaining run formatting</legend>
<label>Find text <input id="word-find" maxlength="4000"></label>
<label>Replace with <input id="word-replacement" maxlength="4000"></label>
<label id="replace-paragraph-label" hidden>Paragraph number <input id="replace-paragraph" inputmode="numeric" maxlength="6" placeholder="Auto"></label>
<button type="button" id="word-replace">Replace once</button>
<div id="word-track-row" hidden><label>Revision author <input id="word-track-author" maxlength="100"></label> <button type="button" id="word-track-replace">Track replacement</button> <button type="button" id="word-track-insert-before">Insert before</button> <button type="button" id="word-track-insert-after">Insert after</button><p>For insertion, Find is the anchor and Replacement is the inserted text.</p></div>
<p>Requires one exact match in supported Word, PowerPoint or Excel text. Replacement takes the first matched run's formatting. Word matches must stay within link or annotation boundaries; fields and complex content require another workflow.</p></fieldset>
<fieldset id="comment-panel" hidden><legend>Add a comment to this paragraph</legend>
<label>Author <input id="comment-author" maxlength="100"></label>
<label>Anchor text (optional) <input id="comment-anchor" maxlength="4000"></label>
<label>Comment <textarea id="comment-text" maxlength="4000"></textarea></label>
<button id="comment-add" type="button">Add comment as new revision</button>
<p>For simple nonempty Word paragraphs. Leave anchor text empty to cover the paragraph. A specified anchor must match exactly once within adjacent text runs; fields and tracked changes require another workflow.</p></fieldset>
<p>Replacing text can change run formatting. A cell value replaces its formula; numeric values may be converted by OfficeCLI. Use formula mode for expressions beginning with =.</p>
<p id="edit-status" role="status"></p></form></details>
<details id="stories-panel" hidden><summary>Word headers and footers</summary>
<p>List paragraph targets, direct references and section links. First/even links depend on document settings; actual page display needs visual review. Edits affect every section using a part.</p>
<button type="button" id="stories-load">Load displayed revision</button><p id="stories-status" role="status"></p><ul id="stories-list"></ul></details>
<details id="tracked-panel" hidden><summary>Word tracked changes</summary>
<p>Inspect common revision records in the displayed saved revision. Records are XML elements; paragraph marks, formatting and moves may need review in Word. Comments and some revision types are outside this scan.</p>
<button type="button" id="tracked-load">Inspect displayed revision</button> <button type="button" id="tracked-accept" disabled>Accept selected</button> <button type="button" id="tracked-reject" disabled>Reject selected</button><p id="tracked-status" role="status"></p><ul id="tracked-results"></ul></details>
<details id="comments-panel" hidden><summary>Word comments</summary>
<p>Read comments from the displayed revision. Anchor text and paths are bounded body hints. Word 2013 thread metadata is shown when available; review unknown or ambiguous states in Word. Root comments can be resolved or reopened in the latest revision.</p>
<button type="button" id="comments-load">Load comments</button><p id="comments-status" role="status"></p><ul id="comments-list"></ul>
<fieldset id="reply-panel" hidden><legend>Reply to comment</legend><p id="reply-target"></p><label>Author <input id="reply-author" maxlength="100"></label>
<label>Reply <textarea id="reply-text" maxlength="4000"></textarea></label><button type="button" id="reply-send">Save reply as new revision</button></fieldset></details>
<details id="slide-order-panel" hidden><summary>Slide order</summary>
<p>Load the displayed revision, then enter every current slide number in the desired order. Slides in the same section must remain together.</p>
<button type="button" id="slide-order-load">Load slide list</button><ol id="slide-order-list"></ol><p id="slide-order-sections"></p>
<form id="slide-order-form"><label>New order <input id="slide-order-input" style="width:min(32rem,70vw)" placeholder="3, 1, 2" required></label> <button type="submit" id="slide-order-save" disabled>Save order as new revision</button></form><p id="slide-order-status" role="status"></p></details>
<details id="notes-panel" hidden><summary>Slide speaker notes</summary><form id="notes-form">
<p>Choose a slide by presentation order, including hidden slides. Saving replaces all notes text and resets its formatting.</p>
<label>Slide number <input id="notes-slide" type="number" min="1" step="1" value="1" required></label>
<button type="button" id="notes-load">Load displayed revision</button>
<label>Speaker notes <textarea id="notes-text" maxlength="100000" rows="8" disabled></textarea></label>
<button type="submit" id="notes-save" disabled>Save notes as new revision</button>
<fieldset><legend>Replace text while retaining formatting</legend>
<label>Paragraph number <input id="notes-paragraph" type="number" min="1" step="1" value="1"></label>
<label>Find <input id="notes-find" maxlength="4000"></label><label>Replace with <input id="notes-replacement" maxlength="4000"></label>
<button type="button" id="notes-replace-text" disabled>Replace once in paragraph</button>
<p>One exact match in a simple paragraph is required. Replacement uses the first matched run's formatting.</p></fieldset><p id="notes-status" role="status"></p>
</form></details>
<details id="layout-panel" hidden><summary>Slide layout checks</summary>
<p>Check the displayed revision for off-slide objects, overlaps involving text, and small text with direct run or paragraph sizes. Results are candidates; intentional layers and text overflow need visual review. Master and layout content are not scanned.</p>
<button type="button" id="layout-scan">Check displayed revision</button><p id="layout-status" role="status"></p><p id="layout-highlight-status" role="status"></p><button type="button" id="layout-clear" hidden>Clear highlight</button><ul id="layout-results"></ul><details><summary>Full geometry and font-size report</summary><pre id="layout-scan-output"></pre></details><p>Compare text boxes and table cells with extracted text from the rendered PDF; review candidates visually.</p><button type="button" id="slide-text-scan">Check rendered text</button><p id="slide-text-status" role="status"></p><ul id="slide-text-results"></ul><details><summary>Full rendered text report</summary><pre id="slide-text-output"></pre></details></details>
<details id="formula-panel" hidden><summary>Workbook calculation and checks</summary>
<p>Scan the latest saved revision for cached errors and missing results. Recalculation creates a new revision using LibreOffice, which can change workbook features; compare and review the result.</p>
<button type="button" id="formula-scan">Scan formulas</button> <label><input type="checkbox" id="formula-allow-dynamic"> Allow conversion with dynamic-array metadata or incomplete inspection; spill results may be lost</label> <button type="button" id="formula-recalculate">Recalculate and save revision</button>
<p id="formula-status" role="status"></p><pre id="formula-scan-output"></pre></details>
<details id="chart-cache-panel" hidden><summary>Chart cache checks</summary>
<p>Compare supported chart caches with stored worksheet values. Sync affects every placement sharing a chart part. Formula caches may be stale; inspect chart rendering and unverified sources separately.</p>
<button type="button" id="chart-cache-scan">Check displayed revision</button><p id="chart-cache-status" role="status"></p><ul id="chart-cache-actions"></ul><pre id="chart-cache-output"></pre></details>
<details id="workbook-panel" hidden><summary>Workbook overview</summary>
<p>Inspect a bounded sample of stored cells in each worksheet. Numbers and dates can be raw stored values; use a cell range for detailed reads.</p>
<button type="button" id="workbook-load">Inspect displayed revision</button><p id="workbook-status" role="status"></p><div id="workbook-results"></div></details>
<details id="grid-panel" hidden><summary>Edit worksheet range</summary><form id="grid-form">
<button type="button" id="grid-sheets">List sheets</button><label for="grid-sheet">Sheet</label> <select id="grid-sheet" required></select>
<label>Range <input id="grid-range" required value="A1:D10" maxlength="32"></label><button type="button" id="grid-load">Load cells</button>
<div id="grid-output" class="grid-scroll"></div><details><summary>Data validation rules for this range</summary><p>Fixed list values and resolved text ranges from the loaded revision can be selected in the grid. Rules are retained but are not evaluated when saving.</p><pre id="grid-validation"></pre></details><details><summary>Conditional formatting for this range</summary><p>The grid shows direct formatting only. Rules are not evaluated; inspect the rendered workbook for effective appearance.</p><pre id="grid-conditional-formatting"></pre></details><label>Default for changed cells <select id="grid-input-type"><option value="auto">Automatic values and formulas</option><option value="text">Literal text</option></select></label> <button type="submit" id="grid-save" disabled>Save changed cells</button>
<fieldset id="grid-format-fields"><legend>Format a range</legend>
<label>Format range <input id="grid-style-range" maxlength="32"></label>
<label>Bold <select id="grid-bold"><option value="">Keep</option><option value="true">On</option><option value="false">Off</option></select></label>
<label>Italic <select id="grid-italic"><option value="">Keep</option><option value="true">On</option><option value="false">Off</option></select></label>
<label>Underline <select id="grid-underline"><option value="">Keep</option><option value="none">None</option><option value="single">Single</option><option value="double">Double</option><option value="singleAccounting">Single accounting</option><option value="doubleAccounting">Double accounting</option></select></label>
<label>Font <input id="grid-font-name" maxlength="100" placeholder="Keep"></label>
<label>Size (pt) <input id="grid-font-size" type="number" min="1" max="409" step="any" placeholder="Keep"></label>
<label><input id="grid-font-color-enabled" type="checkbox"> Set font color</label> <input id="grid-font-color" type="color" value="#000000" aria-label="Font color">
<label>Horizontal <select id="grid-horizontal"><option value="">Keep</option><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option><option value="justify">Justify</option><option value="fill">Fill</option><option value="distributed">Distributed</option></select></label>
<label>Vertical <select id="grid-vertical"><option value="">Keep</option><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label>
<label>Wrap <select id="grid-wrap"><option value="">Keep</option><option value="true">On</option><option value="false">Off</option></select></label>
<label><input id="grid-fill-enabled" type="checkbox"> Set fill</label> <input id="grid-fill" type="color" value="#ffcc00" aria-label="Fill color">
<label>Border style <select id="grid-border"><option value="">Keep</option><option value="none">None</option><option value="thin">Thin</option><option value="medium">Medium</option><option value="thick">Thick</option><option value="double">Double</option><option value="dashed">Dashed</option><option value="dotted">Dotted</option></select></label>
<label>Border placement <select id="grid-border-scope"><option value="all">All cell edges</option><option value="outline">Outside of range</option><option value="inside">Inside range</option></select></label>
<label><input id="grid-border-color-enabled" type="checkbox"> Set border color</label> <input id="grid-border-color" type="color" value="#000000" aria-label="Border color">
<label>Number format <input id="grid-numberformat" maxlength="120" placeholder="Keep"></label>
<button type="button" id="grid-format" disabled>Apply formatting</button></fieldset>
<fieldset><legend>Merge cells</legend>
<label>Range <input id="grid-merge-range" maxlength="32"></label>
<button type="button" id="grid-merge" disabled>Merge</button>
<button type="button" id="grid-unmerge" disabled>Unmerge</button>
<p>Only the top-left cell may contain data. Unmerge requires the exact merged range.</p></fieldset>
<fieldset><legend>Freeze panes</legend>
<label>First scrollable cell <input id="grid-freeze-cell" value="A2" maxlength="10"></label>
<button type="button" id="grid-freeze" disabled>Freeze</button>
<button type="button" id="grid-unfreeze" disabled>Unfreeze</button>
<p id="grid-freeze-info"></p></fieldset>
<fieldset><legend>Size columns and rows</legend>
<label>Target range <input id="grid-size-range" maxlength="32"></label>
<label>Column width (characters) <input id="grid-column-width" type="number" min="0.01" max="255" step="any" placeholder="Keep"></label>
<label>Row height (points) <input id="grid-row-height" type="number" min="0.01" max="409.5" step="any" placeholder="Keep"></label>
<button type="button" id="grid-resize" disabled>Apply sizes</button>
<p>Changes affect entire columns or rows, including cells outside this range.</p>
<details><summary>Stored dimensions for loaded range</summary><pre id="grid-dimensions"></pre></details></fieldset>
<p>Formatting applies to the loaded range or a smaller range. Existing patterned fills keep their pattern; theme colors are not previewed in the grid.</p>
<p>Up to 200 cells. Paste tab-separated cells starting at the focused cell. Enter formulas beginning with =. Choose a default type or override it for each cell. Literal text retains leading zeros or = characters. Changing a nonempty cell’s type also saves it. Enter line breaks in a cell; quoted clipboard cells may contain line breaks. Numeric and date values can be converted by OfficeCLI; expanded array, data-table and shared formula ranges are read-only; supported unexpanded dynamic-array anchors can be edited.</p>
<p id="grid-status" role="status"></p></form></details>
<details><summary>Enter a selection with the keyboard</summary><form id="selection-form">
<label>Page <input name="page" type="number" min="1" required value="1"></label>
<label>Left % <input name="left" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Top % <input name="top" type="number" min="0" max="100" step="0.1" required value="10"></label>
<label>Right % <input name="right" type="number" min="0" max="100" step="0.1" required value="90"></label>
<label>Bottom % <input name="bottom" type="number" min="0" max="100" step="0.1" required value="90"></label>
<button type="submit">Save selection</button></form></details>
<details id="comparison-details" hidden><summary>Text and file changes</summary>
<p>Text is a bounded view; file-part changes may include formatting or metadata. Compare page appearance separately.</p>
<button type="button" id="load-changes">Load changes</button><p id="changes-status" role="status"></p>
<h2>Text</h2><pre id="comparison-text"></pre><h2>Changed file parts</h2><pre id="comparison-parts"></pre>
<section id="notes-comparison" hidden><h2>Speaker notes changes</h2>
<p>Choose corresponding slide numbers in each revision. Slide numbers include hidden slides and may change when slides are reordered.</p>
<form id="notes-comparison-form"><label>Selected revision slide <input id="notes-before-slide" type="number" min="1" step="1" value="1" required></label>
<label>Latest revision slide <input id="notes-after-slide" type="number" min="1" step="1" value="1" required></label><button id="compare-notes" type="submit">Compare notes</button></form>
<p id="notes-comparison-status" role="status"></p><pre id="notes-comparison-output"></pre></section>
<section id="visual-comparison"><h2>Visual page changes</h2>
<p>Choose corresponding rendered pages. Red highlights show RGB differences of at least 16/255; page insertions and hidden slides can change numbering.</p>
<form id="visual-diff-form"><label>Selected revision page <input id="visual-before-page" type="number" min="1" step="1" value="1" required></label>
<label>Latest revision page <input id="visual-after-page" type="number" min="1" step="1" value="1" required></label><button id="visual-diff-button" type="submit">Compare pages visually</button></form>
<p id="visual-diff-status" role="status"></p><a id="visual-diff-open" hidden target="_blank" rel="noopener">Open comparison at full size</a><img id="visual-diff-image" hidden alt="Visual comparison of the selected and latest revisions"></section>
<section id="cell-comparison" hidden><h2>Worksheet changes</h2>
<p>Compare values, formulas, direct formatting, and stored row and column dimensions. Cached formula results may be stale; conditional formatting and theme changes need separate review.</p>
<form id="cell-comparison-form"><label>Worksheet <input id="compare-sheet" required maxlength="31"></label>
<label>Cell range <input id="compare-range" required value="A1:D10" maxlength="32"></label>
<button id="compare-cells" type="submit">Compare cells</button></form>
<p id="cell-comparison-status" role="status"></p><div id="cell-comparison-output" class="grid-scroll"></div></section></details>
<main id="pages" aria-label="Document pages"></main>
<script nonce="NONCE">
let current = -1, displayed = -1, displayedHash = null, pinned = null, viewKey = "", busy = false, loaded = null, comparing = false, comparedLatest = -1, comparedLatestHash = null;
let savedSelection = null, selectionEpoch = 0, gridLoaded = null, cellComparisonEpoch = 0, editBaseline = null, editBusy = false, gridBusy = false, scanBusy = false, calcBusy = false, formulaStatusRevision = null, layoutBusy = false, layoutRevision = null, layoutReport = null, layoutHighlight = null, overlayEpoch = 0, displayedPages = 0, pictureTarget = null, visualEpoch = 0, visualUrl = null, commentListRevision = null, commentListEpoch = 0, commentsBusy = false, replyTarget = null;
let notesLoaded=null, notesBaseline=null, notesEpoch=0, notesBusy=false, notesComparisonEpoch=0, storiesEpoch=0, storiesRevision=null, workbookEpoch=0, workbookRevision=null, chartCacheEpoch=0, chartCacheRevision=null;
let textSearchEpoch=0, textSearchState=null, textSearchBusy=false;
let slideOrderLoaded=null, slideOrderBusy=false;
let trackedEpoch=0, trackedRevision=null, trackedBusy=false, slideTextRevision=null, slideTextEpoch=0;
function clearTextSearch() {
 textSearchEpoch++; textSearchState=null; document.getElementById('text-search-next').disabled=true;
 document.getElementById('text-search-results').replaceChildren(); document.getElementById('text-search-status').textContent='';
}
document.getElementById('text-search-query').addEventListener('input', clearTextSearch);
document.getElementById('text-search-scope').addEventListener('change', clearTextSearch);
async function textSearch(next) {
 if (textSearchBusy || displayed<0) return;
 const query=document.getElementById('text-search-query').value, revision=displayed, scope=document.getElementById('text-search-scope').value;
 if (!query) return;
 if (next && (!textSearchState || textSearchState.revision!==revision || textSearchState.query!==query || textSearchState.scope!==scope || textSearchState.next===null)) return;
 if (!next) clearTextSearch();
 const epoch=++textSearchEpoch, previous=next ? textSearchState : null;
 const status=document.getElementById('text-search-status'), results=document.getElementById('text-search-results');
 textSearchBusy=true; document.getElementById('text-search-start').disabled=true; document.getElementById('text-search-next').disabled=true; status.textContent=`Searching revision ${revision}…`;
 try {
  const response=await fetch('text-search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,query,scope,offset:previous ? previous.next : 0,snapshot_sha256:previous ? previous.hash : null})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Search failed');
  if (epoch!==textSearchEpoch || displayed!==revision || document.getElementById('text-search-query').value!==query) return;
  if (!next) results.replaceChildren();
  for (const item of result.matches) {
   const row=document.createElement('li'), label=document.createElement('span');
   const location=result.format==='xlsx' ? `${item.sheet} · ${item.cell || 'address unavailable'}` : result.format==='pptx' && result.scope==='notes' ? `Slide ${item.slide} · notes paragraph ${item.notes_paragraph}` : item.path;
   label.textContent=`${location}${item.hidden ? ' · hidden slide' : ''}: ${item.excerpt}${item.text_complete ? '' : ' (text may be incomplete)'}`; row.appendChild(label);
   if (result.format==='pptx' && result.scope==='notes' && Number.isSafeInteger(item.notes_paragraph)) {
    const use=document.createElement('button'); use.type='button'; use.textContent='Open speaker notes'; use.disabled=pinned!==null || current!==revision;
    use.addEventListener('click', async () => {
     if (displayed!==revision || current!==revision || pinned!==null || !textSearchState || textSearchState.revision!==revision || textSearchState.query!==query) return;
     const find=document.getElementById('notes-find'), replacement=document.getElementById('notes-replacement');
     if ((find.value || replacement.value) && !window.confirm('Replace the pending notes search and replacement fields?')) return;
     document.getElementById('notes-panel').open=true; const opened=await loadNotes(item.slide);
     if (opened && notesLoaded && notesLoaded.revision===revision && notesLoaded.slide===item.slide && !notesLoaded.truncated && current===revision && pinned===null) {
      document.getElementById('notes-paragraph').value=String(item.notes_paragraph);
      find.value=item.occurrences===1 ? query : ''; replacement.value='';
     }
    });
    row.append(document.createTextNode(' '),use);
   } else if (result.format!=='xlsx' && item.replace_text_path_supported) {
    const use=document.createElement('button'); use.type='button'; use.textContent='Load target'; use.disabled=pinned!==null || current!==revision;
    use.addEventListener('click', async () => {
     if (displayed!==revision || current!==revision || pinned!==null || !textSearchState || textSearchState.revision!==revision || textSearchState.query!==query) return;
     const old=loaded; document.getElementById('edit-panel').open=true; await loadElement(item.path);
     if (loaded && loaded!==old && loaded.revision===revision && current===revision && pinned===null && item.occurrences===1 && !document.getElementById('word-replace-panel').hidden) document.getElementById('word-find').value=query;
    });
    row.append(document.createTextNode(' '),use);
   } else if (result.format==='xlsx' && typeof item.sheet==='string' && /^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(item.cell || '')) {
    const use=document.createElement('button'); use.type='button'; use.textContent='Open cell in grid'; use.disabled=pinned!==null || current!==revision;
    use.addEventListener('click', async () => {
     if (displayed!==revision || current!==revision || pinned!==null || !textSearchState || textSearchState.revision!==revision || textSearchState.query!==query) return;
     document.getElementById('grid-panel').open=true; await loadGrid({sheet:item.sheet,cell:item.cell,revision});
    });
    row.append(document.createTextNode(' '),use);
   }
   results.appendChild(row);
  }
  textSearchState={revision,query,scope,next:result.next_offset,hash:result.snapshot_sha256};
  const uncertain=result.unverified_paragraphs ?? result.unverified_text_cells ?? 0;
  status.textContent=`Revision ${revision}: ${result.matches.length} match(es) in this batch. ${result.scan_complete ? 'End of search scope.' : 'More content remains.'} ${uncertain ? uncertain+' text item(s) need review. ' : ''}${result.unsupported_structure?.length ? 'Some structures were omitted. ' : ''}Coverage is limited to supported content.`;
 } catch(error) { if (epoch===textSearchEpoch) status.textContent=`Search error: ${error.message}`; }
 finally { textSearchBusy=false; document.getElementById('text-search-start').disabled=false; document.getElementById('text-search-next').disabled=!(textSearchState && textSearchState.revision===displayed && textSearchState.next!==null); }
}
document.getElementById('text-search-form').addEventListener('submit', event=>{event.preventDefault(); textSearch(false);});
document.getElementById('text-search-next').addEventListener('click', ()=>textSearch(true));
function clearCandidates() {
 savedSelection=null; selectionEpoch++; pictureTarget=null; document.getElementById('picture-panel').hidden=true; document.getElementById('candidate-search').disabled=true;
 document.getElementById('candidate-list').replaceChildren(); document.getElementById('candidate-status').textContent='';
}
async function saveSelection(revision, page, coordinates) {
 clearCandidates(); const epoch=selectionEpoch;
 try {
  const response=await fetch('selection', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({revision,page,box:coordinates})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Selection failed');
  if (epoch !== selectionEpoch || revision !== current || pinned !== null) return;
  savedSelection=result; document.getElementById('candidate-search').disabled=false;
  document.getElementById('selection').textContent = `Selection saved · revision ${revision}, page ${page}`;
  document.querySelectorAll('.box').forEach(item => item.style.display='none');
  const selected = revision === current && document.querySelector(`.page[data-page="${page}"] .box`);
  if (selected) Object.assign(selected.style, {display:'block', left:`${coordinates[0]*100}%`, top:`${coordinates[1]*100}%`, width:`${(coordinates[2]-coordinates[0])*100}%`, height:`${(coordinates[3]-coordinates[1])*100}%`});
 } catch (error) { document.getElementById('selection').textContent = `Selection error: ${error.message}`; }
}
document.getElementById('candidate-search').addEventListener('click', async () => {
 if (!savedSelection || pinned !== null || savedSelection.revision !== current) return;
 const requested=savedSelection, epoch=selectionEpoch, button=document.getElementById('candidate-search'); button.disabled=true;
 document.getElementById('candidate-status').textContent='Finding candidates…';
 try {
  const response=await fetch('candidates', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({selection:requested,snapshot_sha256:displayedHash})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Search failed');
  if (epoch !== selectionEpoch || pinned !== null || current !== result.revision) return;
  const list=document.getElementById('candidate-list'); list.replaceChildren();
  for (const item of result.candidates) {
   const row=document.createElement('li'); const label=document.createElement('span');
   label.textContent=`${item.type || 'element'} · ${item.path} · ${item.geometry_match ? 'geometry match · ' : 'text match · '}${String(item.text || '').slice(0,200)}`;
   const use=document.createElement('button'); use.type='button'; use.textContent=`Use ${item.path}`;
   use.addEventListener('click', () => {
    if (epoch !== selectionEpoch || current !== result.revision || pinned !== null) return;
    if (item.type === 'picture') { pictureTarget={revision:result.revision,path:item.path}; document.getElementById('picture-target').textContent=`Picture: ${item.path}`; document.getElementById('picture-file').value=''; document.getElementById('picture-status').textContent=''; document.getElementById('picture-panel').hidden=false; }
    else { document.getElementById('edit-panel').open=true; loadElement(item.path); }
   });
   row.append(label, document.createTextNode(' '), use); list.appendChild(row);
  }
  document.getElementById('candidate-status').textContent = result.candidates.length ? `${result.candidates.length} candidate(s). ${result.geometry_available ? 'Geometry and text matches. ' : 'Text matches. '}Verify the target; matches may be incomplete.` : 'No candidates found. Try a different selection or enter a path.';
 } catch (error) { if (epoch === selectionEpoch) document.getElementById('candidate-status').textContent=`Candidate error: ${error.message}`; }
 finally { if (epoch === selectionEpoch && pinned === null && savedSelection) button.disabled=false; }
});
document.getElementById('picture-replace').addEventListener('click', async () => {
 const target=pictureTarget, file=document.getElementById('picture-file').files[0], button=document.getElementById('picture-replace');
 if (!target || pinned!==null || target.revision!==current) { document.getElementById('picture-status').textContent='Version changed; select the picture again.'; return; }
 if (!file || file.size===0 || file.size>10*1024*1024) { document.getElementById('picture-status').textContent='Choose a PNG or JPEG up to 10 MiB.'; return; }
 button.disabled=true;
 try {
  const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read image'));reader.readAsDataURL(file);});
  if (target!==pictureTarget || pinned!==null || target.revision!==current) throw new Error('Version or selection changed; select the picture again.');
  const response=await fetch('replace-picture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,path:target.path,image:encoded})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Picture replacement failed');
  document.getElementById('picture-status').textContent=`Saved as revision ${result.revision}.`; await refresh();
 } catch(error) { document.getElementById('picture-status').textContent=`Picture error: ${error.message}`; }
 finally {button.disabled=false;}
});
function gridChanged(input) {
 return input.value!==input.dataset.baseline || (input.value!=='' && input.parentElement.querySelector('select').value!=='default');
}
function gridDirty() {
 return [...document.querySelectorAll('#grid-output textarea')].some(gridChanged);
}
function lockGridInputs(inputs, locked) {
 inputs.forEach(input=>{input.readOnly=locked || input.dataset.editable!=='true'; input.parentElement.querySelectorAll('select').forEach(select=>{select.disabled=input.readOnly;});});
}
function elementDirty() {
 return editBaseline !== null && (document.getElementById('edit-value').value !== editBaseline.value || document.getElementById('edit-mode').value !== editBaseline.mode);
}
function notesDirty() { return notesBaseline!==null && document.getElementById('notes-text').value!==notesBaseline; }
window.addEventListener('beforeunload', event => {
 if (gridDirty() || elementDirty() || notesDirty()) { event.preventDefault(); event.returnValue=''; }
});
document.getElementById('formula-scan').addEventListener('click', async () => {
 if (scanBusy || calcBusy || pinned!==null || current<0) return;
 const revision=current, button=document.getElementById('formula-scan'); scanBusy=true; formulaStatusRevision=revision; button.disabled=true; document.getElementById('formula-recalculate').disabled=true;
 document.getElementById('formula-status').textContent='Scanning saved revision…'; document.getElementById('formula-scan-output').textContent='';
 try {
  const response=await fetch('formula-scan', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Scan failed');
  if (current!==revision || pinned!==null) return;
  document.getElementById('formula-status').textContent=`Revision ${revision}: ${result.formula_errors} formula error(s), ${result.literal_errors} literal error(s), ${result.empty_or_missing_cache} empty or missing cache(s), ${result.recalculation_requests} worksheet recalculation request(s). Dynamic-array metadata: ${result.dynamic_array_metadata === null ? 'unknown' : result.dynamic_array_metadata ? 'present' : 'not found'}. ${result.complete && result.calculation_metadata_complete && result.dynamic_array_metadata !== null ? 'Scan complete.' : 'Scan incomplete.'}`;
  document.getElementById('formula-scan-output').textContent=JSON.stringify(result, null, 2);
 } catch(error) { if (current===revision && pinned===null) document.getElementById('formula-status').textContent=`Scan error: ${error.message}`; }
 finally { scanBusy=false; button.disabled=pinned!==null; document.getElementById('formula-recalculate').disabled=pinned!==null || calcBusy; }
});
document.getElementById('formula-recalculate').addEventListener('click', async () => {
 if (calcBusy || scanBusy || pinned!==null || current<0) return;
 if (gridBusy || editBusy || gridDirty() || elementDirty()) { document.getElementById('formula-status').textContent='Save or copy pending edits before recalculation.'; return; }
 const revision=current, button=document.getElementById('formula-recalculate'); calcBusy=true; formulaStatusRevision=revision; button.disabled=true; document.getElementById('formula-scan').disabled=true; document.getElementById('formula-scan-output').textContent='';
 document.getElementById('formula-status').textContent=`Recalculating revision ${revision} with LibreOffice…`;
 try {
  const response=await fetch('formula-recalculate', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision,allow_dynamic_arrays:document.getElementById('formula-allow-dynamic').checked})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Recalculation failed');
  document.getElementById('formula-allow-dynamic').checked=false; formulaStatusRevision=result.revision; await refresh(); document.getElementById('formula-status').textContent=`Recalculated revision ${revision} as revision ${result.revision}. Review formulas, errors and file changes.`;
 } catch(error) { document.getElementById('formula-status').textContent=`Recalculation error: ${error.message}`; }
 finally { calcBusy=false; button.disabled=pinned!==null; document.getElementById('formula-scan').disabled=pinned!==null || scanBusy; }
});
function invalidateGrid(message) {
 gridLoaded=null; document.getElementById('grid-merge').disabled=true; document.getElementById('grid-unmerge').disabled=true; document.getElementById('grid-freeze').disabled=true; document.getElementById('grid-unfreeze').disabled=true; document.getElementById('grid-save').disabled=true; document.getElementById('grid-format').disabled=true; document.getElementById('grid-resize').disabled=true;
 lockGridInputs([...document.querySelectorAll('#grid-output textarea')], true);
 if (message) document.getElementById('grid-status').textContent=message;
}
for (const id of ['grid-sheet','grid-range']) document.getElementById(id).addEventListener('change', () => invalidateGrid('Reload the range before saving.'));
document.getElementById('grid-sheets').addEventListener('click', async () => {
 if (gridBusy) return;
 if (gridDirty() && !window.confirm('List sheets and make the unsaved grid read-only? You can still copy its values.')) return;
 gridBusy=true;
 const button=document.getElementById('grid-sheets'); button.disabled=true; invalidateGrid('Loading sheets…'); const revision=current;
 try {
  const response=await fetch('sheets', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision})});
  const data=await response.json(); if (!response.ok) throw new Error(data.error || 'Could not list sheets');
  if (data.revision !== current || pinned !== null) throw new Error('Version changed; list sheets again.');
  const select=document.getElementById('grid-sheet'); select.replaceChildren(...data.sheets.map(name=>{const option=document.createElement('option');option.value=name;option.textContent=name;return option;}));
  document.getElementById('grid-status').textContent=`${data.sheets.length} sheet(s) available at revision ${revision}.`;
 } catch(error) { document.getElementById('grid-status').textContent=`Sheet error: ${error.message}`; }
 finally { gridBusy=false; button.disabled=pinned !== null; }
});
function validationList(validation, cell) {
 if (!validation.complete) return null;
 const rules=validation.rules.filter(rule=>rule.cells.includes(cell));
 if (rules.length!==1 || rules[0].attributes.type!=='list') return null;
 if (rules[0].list_resolution==='resolved') return rules[0].list_values;
 const formula=rules[0].formula1;
 // shortcut: fixed literal lists and resolved text ranges only; add formula and name evaluation when supported.
 if (typeof formula!=='string' || !/^"[^"\\r\\n]*"$/.test(formula)) return null;
 const choices=formula.slice(1,-1).split(',');
 return choices.length && choices.every(choice=>choice.length>0) ? choices : null;
}
async function loadGrid(target=null) {
 if (gridBusy || pinned!==null || target && (target.revision!==current || displayed!==current)) return;
 if (gridDirty() && !window.confirm('Discard unsaved cell edits and load another range?')) return;
 if (target) {
  const select=document.getElementById('grid-sheet');
  if (![...select.options].some(option=>option.value===target.sheet)) { const option=document.createElement('option'); option.value=target.sheet; option.textContent=target.sheet; select.appendChild(option); }
  select.value=target.sheet; document.getElementById('grid-range').value=target.cell;
 }
 gridBusy=true; const button=document.getElementById('grid-load'); button.disabled=true; invalidateGrid('Loading range…');
 const revision=current, sheet=document.getElementById('grid-sheet').value, cell_range=document.getElementById('grid-range').value;
 try {
  const response=await fetch('grid', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision,sheet,cell_range})});
  const data=await response.json(); if (!response.ok) throw new Error(data.error || 'Could not load range');
  if (data.revision !== current || pinned !== null || sheet !== document.getElementById('grid-sheet').value || cell_range !== document.getElementById('grid-range').value) throw new Error('Version or range changed; load again.');
  const table=document.createElement('table'); const head=document.createElement('thead'), header=document.createElement('tr');
  header.appendChild(document.createElement('th'));
  for (const cell of data.rows[0]) { const th=document.createElement('th'); th.scope='col'; th.textContent=cell.cell.replace(/[0-9]+$/, ''); header.appendChild(th); }
  head.appendChild(header); table.appendChild(head); const body=document.createElement('tbody');
  for (const row of data.rows) {
   const tr=document.createElement('tr'); const th=document.createElement('th'); th.scope='row'; th.textContent=row[0].cell.match(/[0-9]+$/)[0]; tr.appendChild(th);
   for (const cell of row) {
    const td=document.createElement('td'), input=document.createElement('textarea'); input.rows=2; input.maxLength=4000;
    const formula=cell.formula, value=typeof formula==='string' ? formula : (formula && typeof formula==='object' ? (formula.text || '[complex formula]') : (cell.value == null ? '' : String(cell.value)));
    input.value=value; input.dataset.baseline=input.value; input.dataset.cell=cell.cell; input.dataset.editable=String(cell.editable);
    input.readOnly=!cell.editable; input.setAttribute('aria-label', `${sheet} ${cell.cell}${cell.read_only_reason ? ' · '+cell.read_only_reason.replaceAll('_',' ') : ''}`);
    if (cell.style.bold) input.style.fontWeight='bold';
    if (cell.style.italic) input.style.fontStyle='italic';
    if (cell.style.underline) input.style.textDecoration='underline';
    if (/^[0-9A-Fa-f]{6}$/.test(cell.style.fill_rgb || '')) {
     input.style.backgroundColor='#'+cell.style.fill_rgb;
     const rgb=cell.style.fill_rgb.match(/../g).map(part=>parseInt(part,16));
     input.style.color=(rgb[0]*299+rgb[1]*587+rgb[2]*114)/1000 < 140 ? 'white' : 'black';
    }
    if (/^[0-9A-Fa-f]{6}$/.test(cell.style.font_color_rgb || '')) input.style.color='#'+cell.style.font_color_rgb;
    for (const side of ['top','bottom','left','right']) {
     const border=cell.style.border?.[side], style=border?.style;
     const css={thin:'1px solid',medium:'2px solid',thick:'3px solid',double:'3px double',dashed:'1px dashed',dotted:'1px dotted'}[style];
     if (css) input.style.setProperty(`border-${side}`, `${css} ${/^[0-9A-Fa-f]{6}$/.test(border.color_rgb || '') ? '#'+border.color_rgb : '#808080'}`);
    }
    if (['left','center','right'].includes(cell.style.horizontal)) input.style.textAlign=cell.style.horizontal;
    input.title=`Number format: ${cell.style.number_format}`;
    if (value.includes('\\r')) input.title+='; editing normalizes carriage returns to line feeds';
    if (typeof formula==='string') input.title+=`; cached result: ${cell.value == null ? 'unknown' : cell.value}`;
    if (cell.dynamic_formula_anchor) input.title+='; dynamic array anchor with unresolved spill range';
    if (!cell.editable) input.title=cell.read_only_reason==='merged_placeholder' ? `Merged cell placeholder; edit ${cell.merged_anchor}` : cell.read_only_reason==='locked_cell' ? 'Locked cell on a protected worksheet' : cell.read_only_reason==='overlapping_merges' ? 'Overlapping merged ranges' : cell.read_only_reason==='value_too_long' ? 'Cell content exceeds the 4,000 UTF-16-unit editing limit' : cell.read_only_reason==='unverified_text' ? 'Text could not be verified; inspect the source before editing' : cell.read_only_reason==='table_header' ? 'Table header requires a table-aware edit' : cell.read_only_reason==='table_totals' ? 'Table totals require a table-aware edit' : 'Protected formula range';
    else if (cell.merged_anchor) input.title+=`; merged region anchor ${cell.merged_anchor}`;
    const mode=document.createElement('select'); mode.setAttribute('aria-label', `${sheet} ${cell.cell} input type`);
    for (const [value,label] of [['default','Default'],['auto','Automatic'],['text','Literal text']]) { const option=document.createElement('option'); option.value=value; option.textContent=label; mode.appendChild(option); }
    mode.disabled=!cell.editable; td.append(input,mode);
    if (data.conditional_formatting.rules.some(rule=>rule.cells.includes(cell.cell))) input.title+='; conditional formatting may change appearance';
    if (!data.conditional_formatting.complete) input.title+='; conditional formatting inspection incomplete';
    const choices=validationList(data.data_validation,cell.cell);
    if (choices) {
     const list=document.createElement('select'); list.setAttribute('aria-label', `${sheet} ${cell.cell} suggested list values`);
     const placeholder=document.createElement('option'); placeholder.value=''; placeholder.textContent='Choose a suggested value'; list.appendChild(placeholder);
     for (const choice of choices) { const option=document.createElement('option'); option.value=choice; option.textContent=choice; list.appendChild(option); }
     list.disabled=!cell.editable; list.addEventListener('change',()=>{if (!list.value) return; input.value=list.value; mode.value='text'; input.dispatchEvent(new Event('input',{bubbles:true})); list.value='';});
     td.appendChild(list);
    }
    tr.appendChild(td);
   }
   body.appendChild(tr);
  }
  table.appendChild(body); document.getElementById('grid-output').replaceChildren(table); gridLoaded={revision,sheet,cell_range,sheet_protected:data.sheet_protected};
  document.getElementById('grid-merge').disabled=data.sheet_protected; document.getElementById('grid-unmerge').disabled=data.sheet_protected; document.getElementById('grid-merge-range').value=cell_range;
  const pane=data.worksheet_view.pane;
  document.getElementById('grid-freeze').disabled=false; document.getElementById('grid-unfreeze').disabled=false;
  document.getElementById('grid-freeze-info').textContent=data.worksheet_view.issue ? 'Worksheet view requires review.' : !pane ? 'No frozen panes.' : pane.state==='frozen' && pane.topLeftCell ? `Frozen panes; first scrollable cell: ${pane.topLeftCell}.` : 'Existing pane requires review before editing.';
  document.getElementById('grid-validation').textContent=JSON.stringify(data.data_validation,null,2);
  document.getElementById('grid-conditional-formatting').textContent=JSON.stringify(data.conditional_formatting,null,2);
  document.getElementById('grid-save').disabled=false; document.getElementById('grid-format').disabled=data.sheet_protected; document.getElementById('grid-style-range').value=cell_range; document.getElementById('grid-size-range').value=cell_range; document.getElementById('grid-resize').disabled=data.sheet_protected; document.getElementById('grid-dimensions').textContent=JSON.stringify({revision,sheet,range:cell_range,...data.dimensions},null,2); document.getElementById('grid-status').textContent=`Loaded ${sheet} ${cell_range} at revision ${revision}.${data.sheet_protected ? ' Worksheet protection is enabled; locked cells and grid formatting are read-only.' : ''}${data.conditional_formatting.rules.length ? ' Conditional formatting is not evaluated in this grid.' : ''}${!data.conditional_formatting.complete ? ' Conditional formatting inspection is incomplete.' : ''}`;
 } catch(error) { document.getElementById('grid-status').textContent=`Grid error: ${error.message}`; }
 finally { gridBusy=false; button.disabled=pinned !== null; }
}
document.getElementById('grid-load').addEventListener('click', () => loadGrid());
function parseGridPaste(text) {
 const rows=[], row=[]; let field='', quoted=false, closed=false, atEnd=false;
 for (let i=0; i<text.length; i++) {
  const char=text[i]; atEnd=false;
  if (quoted) {
   if (char==='"') { if (text[i+1]==='"') { field+='"'; i++; } else { quoted=false; closed=true; } }
   else if (char==='\\r') { field+='\\n'; if (text[i+1]==='\\n') i++; }
   else field+=char;
  } else if (closed && char!=='\\t' && char!=='\\r' && char!=='\\n') throw new Error('Invalid quoted clipboard text.');
  else if (char==='"' && field==='' && !closed) quoted=true;
  else if (char==='\\t') { row.push(field); field=''; closed=false; }
  else if (char==='\\r' || char==='\\n') {
   if (char==='\\r' && text[i+1]==='\\n') i++;
   row.push(field); rows.push(row.splice(0)); field=''; closed=false; atEnd=true;
  } else field+=char;
 }
 if (quoted) throw new Error('Unclosed quoted clipboard text.');
 if (!atEnd) { row.push(field); rows.push(row); }
 if (!rows.length || rows.some(row=>row.length!==rows[0].length)) throw new Error('Paste a rectangular range.');
 return rows;
}
document.getElementById('grid-output').addEventListener('paste', event => {
 const text=event.clipboardData?.getData('text/plain');
 if (!text || !/[\\t\\r\\n]/.test(text)) return;
 event.preventDefault();
 try {
  if (gridBusy || !gridLoaded || gridLoaded.revision!==current || pinned!==null || event.target.readOnly) throw new Error('Load the current range before pasting.');
  if (new TextEncoder().encode(text).length > 20000) throw new Error('Clipboard data exceeds 20 KB.');
  const pasted=parseGridPaste(text), start=event.target.closest('td'), row=start?.parentElement, body=row?.parentElement;
  if (!start || body?.tagName!=='TBODY') throw new Error('Choose a cell in the grid.');
  const firstRow=row.sectionRowIndex, firstCol=start.cellIndex-1, targets=[];
  for (let r=0; r<pasted.length; r++) for (let c=0; c<pasted[r].length; c++) {
   const input=body.rows[firstRow+r]?.cells[firstCol+c+1]?.querySelector('textarea'), value=pasted[r][c];
   if (!input) throw new Error('Paste extends beyond the loaded range.');
   if (input.readOnly || input.dataset.editable!=='true') throw new Error('Paste includes a protected cell.');
   if (value.length>4000 || value.includes('\\0')) throw new Error('Cell text exceeds the supported limit or contains a null character.');
   targets.push([input,value]);
  }
  for (const [input,value] of targets) { input.value=value; input.dispatchEvent(new Event('input',{bubbles:true})); }
  document.getElementById('grid-status').textContent=`Pasted ${targets.length} cell(s). Review and save changes.`;
 } catch(error) { document.getElementById('grid-status').textContent=`Paste error: ${error.message}`; }
});
document.getElementById('grid-form').addEventListener('submit', async event => {
 event.preventDefault(); if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision !== current || pinned !== null) { invalidateGrid('Version changed; reload the range.'); return; }
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output textarea')];
 const changes=inputs.filter(input=>input.dataset.editable==='true' && gridChanged(input)).map(input=>{const choice=input.parentElement.querySelector('select').value, mode=choice==='default' ? document.getElementById('grid-input-type').value : choice; return {cell:input.dataset.cell,value:input.value,...(mode==='text' && input.value ? {type:'text'} : {})};});
 if (!changes.length) { document.getElementById('grid-status').textContent='No changed cells.'; return; }
 const body=JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:loaded.cell_range,changes});
 if (new TextEncoder().encode(body).length > 20000) { document.getElementById('grid-status').textContent='Changes exceed 20 KB; save fewer cells at a time.'; return; }
 gridBusy=true; const button=document.getElementById('grid-save'); button.disabled=true; document.getElementById('grid-format').disabled=true; document.getElementById('grid-resize').disabled=true; lockGridInputs(inputs,true);
 try {
  const response=await fetch('grid-edit', {method:'POST',headers:{'Content-Type':'application/json'},body});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Save failed');
  inputs.forEach(input=>{input.dataset.baseline=input.value; input.parentElement.querySelector('select').value='default';});
  invalidateGrid(`Saved ${changes.length} cell(s) as revision ${result.revision}. Formula caches may be stale; recalculation is requested on open.${result.calculation_chain === 'removed' ? ' Calculation chain removed for rebuilding.' : ''}${result.dynamic_formula_cells?.length ? ' Dynamic formula spill ranges require compatible recalculation and review.' : ''}${result.data_validation.affected_cells.length ? ' Data validation was not evaluated for: '+result.data_validation.affected_cells.join(', ')+'.' : ''}${!result.data_validation.coverage_complete ? ' Data validation coverage is incomplete; review the workbook.' : ''}`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded === loaded && current === loaded.revision && pinned === null) { lockGridInputs(inputs,false); button.disabled=false; document.getElementById('grid-format').disabled=loaded.sheet_protected; document.getElementById('grid-resize').disabled=loaded.sheet_protected; }
 } finally { gridBusy=false; }
});
function resetGridFormatting() {
 for (const name of ['bold','italic','underline','horizontal','vertical','wrap','border','font-name','font-size','numberformat']) document.getElementById(`grid-${name}`).value='';
 document.getElementById('grid-border-scope').value='all';
 for (const name of ['font-color','fill','border-color']) document.getElementById(`grid-${name}-enabled`).checked=false;
}
document.getElementById('grid-format').addEventListener('click', async () => {
 if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision !== current || pinned !== null) { invalidateGrid('Version changed; reload the range.'); return; }
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output textarea')];
 if (inputs.some(gridChanged)) { document.getElementById('grid-status').textContent='Save or copy pending cell edits before formatting.'; return; }
 const properties={}, bold=document.getElementById('grid-bold').value, numberformat=document.getElementById('grid-numberformat').value;
 if (bold) properties.bold=bold==='true';
 for (const name of ['italic','wrap']) {const value=document.getElementById(`grid-${name}`).value; if (value) properties[name]=value==='true';}
 for (const name of ['underline','horizontal','vertical']) {const value=document.getElementById(`grid-${name}`).value; if (value) properties[name]=value;}
 const fontName=document.getElementById('grid-font-name').value, fontSize=document.getElementById('grid-font-size').value;
 if (fontName) properties.font_name=fontName;
 if (fontSize) properties.font_size=Number(fontSize);
 if (document.getElementById('grid-font-color-enabled').checked) properties.font_color=document.getElementById('grid-font-color').value.slice(1);
 if (document.getElementById('grid-fill-enabled').checked) properties.fill=document.getElementById('grid-fill').value.slice(1);
 const border=document.getElementById('grid-border').value;
 if (border) { properties.border=border; properties.border_scope=document.getElementById('grid-border-scope').value; }
 if (document.getElementById('grid-border-color-enabled').checked) {
  if (!border || border==='none') { document.getElementById('grid-status').textContent='Choose a border style before setting its color.'; return; }
  properties.border_color=document.getElementById('grid-border-color').value.slice(1);
 }
 if (numberformat) properties.numberformat=numberformat;
 if (!Object.keys(properties).length) { document.getElementById('grid-status').textContent='Choose a formatting change.'; return; }
 gridBusy=true; const button=document.getElementById('grid-format'), fields=document.getElementById('grid-format-fields'); button.disabled=true; fields.disabled=true; document.getElementById('grid-resize').disabled=true; document.getElementById('grid-save').disabled=true; lockGridInputs(inputs,true);
 try {
  const response=await fetch('grid-format', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:loaded.cell_range,style_range:document.getElementById('grid-style-range').value,properties})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Formatting failed');
  resetGridFormatting(); invalidateGrid(`Formatting saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded === loaded && current === loaded.revision && pinned === null) { lockGridInputs(inputs,false); button.disabled=false; document.getElementById('grid-resize').disabled=loaded.sheet_protected; document.getElementById('grid-save').disabled=false; }
 } finally { fields.disabled=false; gridBusy=false; }
});
async function mergeGrid(merge) {
 if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision !== current || pinned !== null) { invalidateGrid('Version changed; reload the range.'); return; }
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output textarea')];
 if (inputs.some(gridChanged)) { document.getElementById('grid-status').textContent='Save or copy pending cell edits before merging.'; return; }
 gridBusy=true; const buttons=['grid-merge','grid-unmerge','grid-freeze','grid-unfreeze','grid-save','grid-format','grid-resize'];
 for (const name of buttons) document.getElementById(name).disabled=true; lockGridInputs(inputs,true);
 try {
  const response=await fetch('grid-merge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:document.getElementById('grid-merge-range').value,merge})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Merge failed');
  invalidateGrid(`${merge ? 'Merged' : 'Unmerged'} ${result.range} as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded===loaded && current===loaded.revision && pinned===null) { for (const name of buttons) document.getElementById(name).disabled=loaded.sheet_protected && !['grid-freeze','grid-unfreeze','grid-save'].includes(name); lockGridInputs(inputs,false); }
 } finally { gridBusy=false; }
}
document.getElementById('grid-merge').addEventListener('click',()=>mergeGrid(true));
document.getElementById('grid-unmerge').addEventListener('click',()=>mergeGrid(false));
async function freezeGrid(cell) {
 if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision !== current || pinned !== null) { invalidateGrid('Version changed; reload the range.'); return; }
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output textarea')];
 if (inputs.some(gridChanged)) { document.getElementById('grid-status').textContent='Save or copy pending cell edits before changing the pane.'; return; }
 gridBusy=true; const freeze=document.getElementById('grid-freeze'), unfreeze=document.getElementById('grid-unfreeze');
 freeze.disabled=true; unfreeze.disabled=true; document.getElementById('grid-save').disabled=true; document.getElementById('grid-format').disabled=true; document.getElementById('grid-resize').disabled=true; lockGridInputs(inputs,true);
 try {
  const response=await fetch('grid-freeze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Pane change failed');
  invalidateGrid(`Pane saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded===loaded && current===loaded.revision && pinned===null) { freeze.disabled=false; unfreeze.disabled=false; document.getElementById('grid-save').disabled=false; document.getElementById('grid-format').disabled=loaded.sheet_protected; document.getElementById('grid-resize').disabled=loaded.sheet_protected; lockGridInputs(inputs,false); }
 } finally { gridBusy=false; }
}
document.getElementById('grid-freeze').addEventListener('click',()=>freezeGrid(document.getElementById('grid-freeze-cell').value));
document.getElementById('grid-unfreeze').addEventListener('click',()=>freezeGrid(null));
document.getElementById('grid-resize').addEventListener('click', async () => {
 if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision!==current || pinned!==null) {invalidateGrid('Version changed; reload the range.'); return;}
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output textarea')];
 if (inputs.some(gridChanged)) {document.getElementById('grid-status').textContent='Save or copy pending cell edits before sizing.'; return;}
 const width=document.getElementById('grid-column-width').value, height=document.getElementById('grid-row-height').value;
 if (!width && !height) {document.getElementById('grid-status').textContent='Enter a width or height.'; return;}
 gridBusy=true; document.getElementById('grid-resize').disabled=true; document.getElementById('grid-format').disabled=true; document.getElementById('grid-save').disabled=true; lockGridInputs(inputs,true);
 try {
  const response=await fetch('grid-resize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:loaded.cell_range,target_range:document.getElementById('grid-size-range').value,column_width:width ? Number(width) : null,row_height:height ? Number(height) : null})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Sizing failed');
  invalidateGrid(`Sizing saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded===loaded && current===loaded.revision && pinned===null) {lockGridInputs(inputs,false); document.getElementById('grid-resize').disabled=loaded.sheet_protected; document.getElementById('grid-format').disabled=loaded.sheet_protected; document.getElementById('grid-save').disabled=false;}
 } finally {gridBusy=false;}
});
function invalidateEdit(message) {
 loaded=null; document.getElementById('edit-save').disabled=true; document.getElementById('word-replace-panel').hidden=true; document.getElementById('comment-panel').hidden=true;
 document.getElementById('edit-mode').disabled=true; document.getElementById('edit-value').readOnly=true;
 if (message) document.getElementById('edit-status').textContent=message;
}
document.getElementById('edit-path').addEventListener('input', () => invalidateEdit('Load the element before saving.'));
async function loadElement(path) {
 if (editBusy) return;
 if (elementDirty() && !window.confirm('Discard unsaved element edits and load another element?')) return;
 const button=document.getElementById('edit-load'); button.disabled=true; editBusy=true;
 document.getElementById('edit-path').value=path; invalidateEdit('Loading…');
 try {
  const response=await fetch('element', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:current,path})});
  const target=await response.json(); if (!response.ok) throw new Error(target.error || 'Could not load element');
  if (target.revision !== current || pinned !== null || document.getElementById('edit-path').value !== path) throw new Error('Version or path changed; load the element again.');
  loaded=target; document.getElementById('edit-path').value=target.path;
  const mode=document.getElementById('edit-mode'); const kinds=target.format==='xlsx' ? ['value','formula','literal'] : ['text'];
  mode.replaceChildren(...kinds.map(kind=>{const option=document.createElement('option');option.value=kind;option.textContent=kind==='literal' ? 'literal text' : kind;return option;}));
  const tableCell=target.format==='pptx' && target.type==='tc' || target.replace_only || Boolean(target.read_only_reason);
  mode.value=target.mode; mode.disabled=tableCell;
  const value=document.getElementById('edit-value'); value.disabled=false; value.readOnly=tableCell; value.value=target.value;
  editBaseline={value:value.value,mode:mode.value};
  document.getElementById('edit-save').disabled=tableCell;
  document.getElementById('word-replace-panel').hidden=!target.replace_text_path_supported;
  document.getElementById('word-track-row').hidden=!(target.format==='docx' && target.type==='paragraph' && target.replace_text_path_supported && !target.replace_only);
  document.getElementById('comment-panel').hidden=!(target.format==='docx' && target.type==='paragraph' && target.replace_text_path_supported && !target.replace_only); document.getElementById('comment-text').value=''; document.getElementById('comment-anchor').value='';
  document.getElementById('replace-paragraph-label').hidden=target.format!=='pptx' || target.path.includes('/paragraph['); document.getElementById('replace-paragraph').value='';
  if (target.replace_only && target.note_impact) {
   document.getElementById('edit-status').textContent=`Loaded ${target.note_impact.kind} ${target.note_impact.id} at revision ${target.revision}. References to this note share its text. Use Replace once; review the rendered document.`;
  } else if (target.replace_only && target.format==='pptx') {
   document.getElementById('edit-status').textContent=target.read_only_reason ? `Loaded read-only slide paragraph: ${target.read_only_reason}.` : `Loaded slide paragraph at revision ${target.revision}. Use Replace once; review the rendered slide.`;
  } else if (target.replace_only) {
   const impact=target.story_impact, linked=impact.linked_sections.map(r=>`${r.section} (${r.type}, ${r.inherited ? 'linked' : 'direct'}, ${r.relationship_id})`).join(', ') || 'none found';
   document.getElementById('edit-status').textContent=`Loaded ${target.type} at revision ${target.revision}. Part ${impact.part}; sections: ${linked}. ${impact.same_part_ids.length ? 'Other relationship IDs share this part: '+impact.same_part_ids.join(', ')+'. ' : ''}${impact.complete ? '' : 'Section links are incomplete. '}Use Replace once; verify the rendered document.`;
  } else document.getElementById('edit-status').textContent=target.read_only_reason ? `Loaded read-only cell: ${target.read_only_reason.replaceAll('_',' ')}.` : `Loaded ${target.type} at revision ${target.revision}. Review content before saving.`;
 } catch (error) { invalidateEdit(`Load error: ${error.message}`); }
 finally { editBusy=false; button.disabled = pinned !== null; }
}
document.getElementById('edit-load').addEventListener('click', () => loadElement(document.getElementById('edit-path').value));
document.getElementById('edit-form').addEventListener('submit', async event => {
 event.preventDefault(); if (editBusy) return;
 if (!loaded || pinned !== null || loaded.revision !== current) { invalidateEdit('Version changed; load the element again.'); return; }
 const target=loaded, button=document.getElementById('edit-save'), path=document.getElementById('edit-path');
 const mode=document.getElementById('edit-mode'), value=document.getElementById('edit-value'), snapshot={value:value.value,mode:mode.value};
 editBusy=true; button.disabled=true; document.getElementById('edit-load').disabled=true; path.disabled=true; mode.disabled=true; value.readOnly=true;
 try {
  const response=await fetch('edit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:target.revision,path:target.path,mode:snapshot.mode,value:snapshot.value})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Edit failed');
  editBaseline=snapshot; invalidateEdit(`Saved as revision ${result.revision}.${result.recalculation_requested ? ' Formula caches may be stale; recalculation is requested on open.' : ''}${result.calculation_chain === 'removed' ? ' Calculation chain removed for rebuilding.' : ''}${result.dynamic_formula_cells?.length ? ' Dynamic formula spill ranges require compatible recalculation and review.' : ''}`); await refresh();
 } catch (error) {
  document.getElementById('edit-status').textContent=`Edit error: ${error.message}`;
  if (loaded === target && current === target.revision && pinned === null) { value.readOnly=false; mode.disabled=false; button.disabled=false; }
 }
 finally { editBusy=false; path.disabled=pinned !== null; document.getElementById('edit-load').disabled=pinned !== null; }
});
document.getElementById('comment-add').addEventListener('click', async () => {
 if (editBusy) return;
 if (!loaded || loaded.format!=='docx' || loaded.type!=='paragraph' || pinned!==null || loaded.revision!==current) { invalidateEdit('Version changed; load the paragraph again.'); return; }
 if (elementDirty()) { document.getElementById('edit-status').textContent='Save or copy pending element edits before adding a comment.'; return; }
 const target=loaded, author=document.getElementById('comment-author').value, text=document.getElementById('comment-text').value, anchor=document.getElementById('comment-anchor').value || null, button=document.getElementById('comment-add');
 if (!author.trim() || !text.trim()) { document.getElementById('edit-status').textContent='Enter an author and comment.'; return; }
 editBusy=true; button.disabled=true;
 try {
  const response=await fetch('add-comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,path:target.path,text,author,anchor})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not add comment');
  invalidateEdit(`Comment saved as revision ${result.revision}.`); await refresh();
 } catch(error) { document.getElementById('edit-status').textContent=`Comment error: ${error.message}`; }
 finally { editBusy=false; button.disabled=false; }
});
document.getElementById('word-replace').addEventListener('click', async () => {
 if (editBusy) return;
 if (!loaded || !loaded.replace_text_path_supported || pinned!==null || loaded.revision!==current) { invalidateEdit('Version changed; load the paragraph again.'); return; }
 if (elementDirty()) { document.getElementById('edit-status').textContent='Save or copy pending element edits before replacing text.'; return; }
 const target=loaded, path=document.getElementById('edit-path'), mode=document.getElementById('edit-mode'), value=document.getElementById('edit-value');
 const find=document.getElementById('word-find'), replacement=document.getElementById('word-replacement'), button=document.getElementById('word-replace');
 const paragraph=document.getElementById('replace-paragraph'), number=paragraph.value;
 if (number && !/^[1-9][0-9]{0,5}$/.test(number)) { document.getElementById('edit-status').textContent='Paragraph number must be a positive integer.'; return; }
 const replacementPath=number && !paragraph.parentElement.hidden ? `${target.path}/paragraph[${number}]` : target.path;
 editBusy=true; button.disabled=true; find.disabled=true; replacement.disabled=true; document.getElementById('edit-save').disabled=true; document.getElementById('edit-load').disabled=true; path.disabled=true; mode.disabled=true; value.readOnly=true;
 try {
  const response=await fetch('replace-text', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:target.revision,path:replacementPath,find:find.value,replacement:replacement.value})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Replacement failed');
  invalidateEdit(`Replacement saved as revision ${result.revision}. ${result.recalculation_requested ? 'Formula caches may be stale; recalculation is requested on open. ' : ''}Reload the element to see its updated content.`); await refresh();
 } catch(error) {
  document.getElementById('edit-status').textContent=`Replacement error: ${error.message}`;
  if (loaded===target && current===target.revision && pinned===null) { const tableCell=target.format==='pptx' && target.type==='tc' || Boolean(target.replace_only || target.read_only_reason); value.readOnly=tableCell; mode.disabled=tableCell; document.getElementById('edit-save').disabled=tableCell; }
 } finally { editBusy=false; button.disabled=false; find.disabled=false; replacement.disabled=false; path.disabled=pinned!==null; document.getElementById('edit-load').disabled=pinned!==null; }
});
async function trackedTextEdit(position) {
 if (editBusy) return;
 if (!loaded || loaded.format!=='docx' || !loaded.replace_text_path_supported || pinned!==null || loaded.revision!==current) { invalidateEdit('Version changed; load the paragraph again.'); return; }
 if (elementDirty()) { document.getElementById('edit-status').textContent='Save or copy pending element edits before replacing text.'; return; }
 const target=loaded, find=document.getElementById('word-find'), replacement=document.getElementById('word-replacement'), author=document.getElementById('word-track-author'), buttons=['word-track-replace','word-track-insert-before','word-track-insert-after'].map(id => document.getElementById(id)), path=document.getElementById('edit-path'), mode=document.getElementById('edit-mode'), value=document.getElementById('edit-value');
 if (!author.value.trim()) { document.getElementById('edit-status').textContent='Enter a revision author.'; return; }
 editBusy=true; buttons.forEach(button => button.disabled=true); find.disabled=true; replacement.disabled=true; author.disabled=true; path.disabled=true; mode.disabled=true; value.readOnly=true; document.getElementById('edit-save').disabled=true; document.getElementById('edit-load').disabled=true;
 try {
  const payload=position ? {base_revision:target.revision,path:target.path,anchor:find.value,text:replacement.value,position,author:author.value} : {base_revision:target.revision,path:target.path,find:find.value,replacement:replacement.value,author:author.value};
  const response=await fetch(position ? 'track-insert-text' : 'track-replace-text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Tracked edit failed');
  invalidateEdit(`Tracked edit saved as revision ${result.revision}. Review the changes in Word.`); await refresh();
 } catch(error) {
  document.getElementById('edit-status').textContent=`Tracked edit error: ${error.message}`;
  if (loaded===target && current===target.revision && pinned===null) {const readOnly=Boolean(target.replace_only || target.read_only_reason); mode.disabled=readOnly; value.readOnly=readOnly; document.getElementById('edit-save').disabled=readOnly;}
 } finally {editBusy=false; buttons.forEach(button => button.disabled=false); find.disabled=false; replacement.disabled=false; author.disabled=false; path.disabled=pinned!==null; document.getElementById('edit-load').disabled=pinned!==null;}
}
document.getElementById('word-track-replace').addEventListener('click', () => trackedTextEdit(null));
for (const position of ['before', 'after']) document.getElementById(`word-track-insert-${position}`).addEventListener('click', () => trackedTextEdit(position));
document.getElementById('restore-form').addEventListener('submit', async event => {
 event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true;
 try {
  const revision = Number(document.getElementById('restore-revision').value);
  const response = await fetch('restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:current, revision})});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Restore failed');
  document.getElementById('restore-status').textContent = `Restored revision ${revision} as revision ${result.revision}`;
  pinned=null; comparing=false; viewKey=''; await refresh();
 } catch (error) { document.getElementById('restore-status').textContent = `Restore error: ${error.message}`; }
 finally { button.disabled = false; }
});
document.getElementById('selection-form').addEventListener('submit', event => {
 event.preventDefault(); const data = new FormData(event.currentTarget);
 const page = Number(data.get('page'));
 const coordinates = ['left','top','right','bottom'].map(key => Number(data.get(key))/100);
 saveSelection(current, page, coordinates);
});
function selectable(image, page, revision, enabled) {
 const wrapper = document.createElement('div'); wrapper.className = 'page'; wrapper.dataset.page = String(page);
 wrapper.dataset.layoutRevision=String(revision); wrapper.dataset.layoutPage=String(page); wrapper.dataset.layoutSide='single';
 const box = document.createElement('div'); box.className = 'box'; wrapper.append(image, box);
 if (!enabled) { wrapper.style.cursor='default'; return wrapper; }
 let start = null;
 function point(event) {
  const rect = image.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)), Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))];
 }
 function draw(end) {
  const left = Math.min(start[0],end[0]), top = Math.min(start[1],end[1]);
  const right = Math.max(start[0],end[0]), bottom = Math.max(start[1],end[1]);
  Object.assign(box.style, {display:'block', left:`${left*100}%`, top:`${top*100}%`, width:`${(right-left)*100}%`, height:`${(bottom-top)*100}%`});
  return [left, top, right, bottom];
 }
 wrapper.addEventListener('pointerdown', event => { if (event.button !== 0) return; start=point(event); wrapper.setPointerCapture(event.pointerId); event.preventDefault(); });
 wrapper.addEventListener('pointermove', event => { if (start) draw(point(event)); });
 wrapper.addEventListener('pointercancel', () => { start=null; box.style.display='none'; });
 wrapper.addEventListener('pointerup', async event => {
  if (!start) return; const coordinates=draw(point(event)); start=null;
  if (coordinates[2]-coordinates[0] < .005 || coordinates[3]-coordinates[1] < .005) { box.style.display='none'; return; }
  await saveSelection(revision, page, coordinates);
 });
 return wrapper;
}
function clearHighlight() {
 overlayEpoch++; layoutHighlight=null; document.querySelectorAll('.layout-overlay').forEach(item=>item.remove());
 document.getElementById('layout-clear').hidden=true; document.getElementById('layout-highlight-status').textContent='';
}
document.getElementById('layout-clear').addEventListener('click', clearHighlight);
function clearLayoutFor(revision) {
 if (slideTextRevision !== null && slideTextRevision !== revision) { slideTextEpoch++; slideTextRevision=null; document.getElementById('slide-text-status').textContent=''; document.getElementById('slide-text-results').replaceChildren(); document.getElementById('slide-text-output').textContent=''; }
 if (layoutRevision !== null && layoutRevision !== revision) {
  clearHighlight(); layoutReport=null; layoutRevision=null; document.getElementById('layout-status').textContent=''; document.getElementById('layout-results').replaceChildren(); document.getElementById('layout-scan-output').textContent='';
 }
}
function layoutMappingAvailable() {
 return layoutReport && layoutReport.visibility_known && Array.isArray(layoutReport.hidden_slides) && layoutReport.hidden_slides.length===0 && layoutReport.slides_total===displayedPages;
}
async function showLayoutHighlight(highlight, scroll) {
 const epoch=++overlayEpoch; document.querySelectorAll('.layout-overlay').forEach(item=>item.remove());
 if (!layoutReport || layoutRevision!==displayed || !layoutMappingAvailable()) { document.getElementById('layout-highlight-status').textContent='Highlight unavailable: slide-to-page mapping is uncertain.'; return; }
 const side=comparing ? 'selected' : 'single';
 const wrapper=[...document.querySelectorAll('[data-layout-revision]')].find(item=>Number(item.dataset.layoutRevision)===displayed && Number(item.dataset.layoutPage)===highlight.slide && item.dataset.layoutSide===side);
 if (!wrapper) { document.getElementById('layout-highlight-status').textContent='The matching preview page is unavailable.'; return; }
 if (scroll) wrapper.scrollIntoView({block:'center'});
 const img=wrapper.querySelector('img');
 try { await img.decode(); } catch(error) { if (epoch===overlayEpoch) document.getElementById('layout-highlight-status').textContent='The preview image could not be loaded.'; return; }
 if (epoch!==overlayEpoch || !wrapper.isConnected || layoutRevision!==displayed) return;
 const [width,height]=layoutReport.slide_size_inches;
 if (!(Number.isFinite(width) && Number.isFinite(height) && width>0 && height>0 && img.naturalWidth>0 && img.naturalHeight>0) || Math.abs((img.naturalWidth/img.naturalHeight)/(width/height)-1)>0.015) {
  document.getElementById('layout-highlight-status').textContent='Highlight unavailable: preview dimensions do not match the slide.'; return;
 }
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.classList.add('layout-overlay'); svg.setAttribute('viewBox',`0 0 ${width} ${height}`); svg.setAttribute('preserveAspectRatio','none'); svg.setAttribute('aria-hidden','true');
 let count=0;
 for (const [points,color] of highlight.polygons) {
  if (!Array.isArray(points) || points.length<3 || !points.every(pair=>Array.isArray(pair) && pair.length===2 && pair.every(Number.isFinite))) continue;
  const polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  polygon.setAttribute('points',points.map(([x,y])=>`${Math.max(0,Math.min(width,x))},${Math.max(0,Math.min(height,y))}`).join(' '));
  polygon.setAttribute('stroke',color); polygon.setAttribute('fill',color); polygon.setAttribute('fill-opacity','0.14'); svg.appendChild(polygon); count++;
 }
 layoutHighlight=highlight; document.getElementById('layout-clear').hidden=false;
 if (count) { wrapper.appendChild(svg); document.getElementById('layout-highlight-status').textContent=`Slide ${highlight.slide}: highlighted visible geometry.`; }
 else document.getElementById('layout-highlight-status').textContent=`Slide ${highlight.slide}: the object is outside the visible page; inspect its path.`;
}
document.getElementById('slide-text-scan').addEventListener('click', async () => {
 if (displayed<0) return;
 const revision=displayed, epoch=++slideTextEpoch, button=document.getElementById('slide-text-scan'); slideTextRevision=revision; button.disabled=true;
 document.getElementById('slide-text-status').textContent=`Checking revision ${revision}…`; document.getElementById('slide-text-results').replaceChildren(); document.getElementById('slide-text-output').textContent='';
 try {
  const response=await fetch('slide-text-scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Text check failed');
  if (epoch!==slideTextEpoch || displayed!==revision) return;
  document.getElementById('slide-text-status').textContent=`Revision ${revision}: ${result.candidate_count} candidate(s); ${result.complete ? 'eligible checks complete' : 'scan incomplete'}. Inspect the rendered slides.`;
  for (const candidate of result.candidates) {
   const row=document.createElement('li'), use=document.createElement('button');
   row.append(document.createTextNode(`${candidate.path_hint}: ${candidate.source_text} `));
   use.type='button'; use.textContent='Load target'; use.disabled=pinned!==null || current!==revision;
   use.addEventListener('click', async () => {
    if (pinned!==null || current!==revision || displayed!==revision || slideTextRevision!==revision) return;
    document.getElementById('edit-panel').open=true; await loadElement(candidate.path_hint);
   });
   row.appendChild(use);
   for (const paragraph of candidate.paragraph_candidates || []) {
    if (paragraph.path_hint === candidate.path_hint) continue;
    const target=document.createElement('button'); target.type='button'; target.textContent=`Load ${paragraph.path_hint.split('/').pop()}`; target.disabled=pinned!==null || current!==revision;
    target.addEventListener('click', async () => {
     if (pinned!==null || current!==revision || displayed!==revision || slideTextRevision!==revision) return;
     document.getElementById('edit-panel').open=true; await loadElement(paragraph.path_hint);
    });
    row.append(' ',target);
   }
   if (candidate.paragraph_candidates_truncated) row.append(' Additional paragraphs were not fully checked.');
   document.getElementById('slide-text-results').appendChild(row);
  }
  document.getElementById('slide-text-output').textContent=JSON.stringify(result,null,2);
 } catch(error) { if (epoch===slideTextEpoch && displayed===revision) document.getElementById('slide-text-status').textContent=`Text check error: ${error.message}`; }
 finally {button.disabled=false;}
});
document.getElementById('layout-scan').addEventListener('click', async () => {
 if (layoutBusy || displayed<0) return;
 const revision=displayed, button=document.getElementById('layout-scan'); clearHighlight(); layoutReport=null; layoutBusy=true; layoutRevision=revision; button.disabled=true;
 document.getElementById('layout-status').textContent=`Checking revision ${revision}…`; document.getElementById('layout-results').replaceChildren(); document.getElementById('layout-scan-output').textContent='';
 try {
  const response=await fetch('layout-scan', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Layout check failed');
  if (displayed!==revision || layoutRevision!==revision) return;
  document.getElementById('layout-status').textContent=`Revision ${revision}: ${result.off_slide_count} off-slide, ${result.overlap_count} overlap, ${result.font_size.candidate_count} small-text candidate(s). ${result.complete ? 'Geometry scan complete.' : 'Geometry scan incomplete.'} ${result.font_size.complete ? 'Direct font-size scan complete.' : 'Font-size scan incomplete; '+result.font_size.unresolved_runs+' run(s) have unresolved size.'}`;
  layoutReport=result;
  const list=document.getElementById('layout-results');
  if (!layoutMappingAvailable()) document.getElementById('layout-highlight-status').textContent='Page highlights are unavailable when slides are hidden, visibility is unknown, or preview page counts differ.';
  const describe=item=>`${item.name || 'Object'} (ID ${item.id}, ${item.path_hint || 'no path hint'})${item.text_preview ? ': ' + item.text_preview : ''}`;
  function addCandidate(label, highlight) {
   const row=document.createElement('li'); row.appendChild(document.createTextNode(label+' '));
   const show=document.createElement('button'); show.type='button'; show.textContent='Show on slide'; show.setAttribute('aria-label',`Show ${label} on slide`); show.disabled=!layoutMappingAvailable();
   show.addEventListener('click',()=>showLayoutHighlight(highlight,true)); row.appendChild(show); list.appendChild(row);
  }
  for (const item of result.off_slide) addCandidate(`Slide ${item.slide}: off-slide — ${describe(item)}`, {slide:item.slide,polygons:[[item.visible_polygon_inches,'#c62828']]});
  for (const item of result.overlaps) addCandidate(`Slide ${item.slide}: overlap — ${describe(item.first)} / ${describe(item.second)} (${Math.round(item.fraction_of_smaller*100)}% of smaller object)`, {slide:item.slide,polygons:[[item.first.visible_polygon_inches,'#0063b1'],[item.second.visible_polygon_inches,'#c62828'],[item.intersection_polygon_inches,'#b26a00']]});
  for (const item of result.font_size.candidates) addCandidate(`Slide ${item.slide}: small text — ${item.name || 'Object'}${item.cell ? `, table row ${item.cell[0]} column ${item.cell[1]}` : ''} (${item.size_pt} pt, ${item.size_source === 'paragraph' ? 'paragraph default' : 'run'}): ${item.text_preview}`, {slide:item.slide,polygons:[[item.visible_polygon_inches,'#b26a00']]});
  if (!result.off_slide.length && !result.overlaps.length && !result.font_size.candidates.length) { const row=document.createElement('li'); row.textContent='No candidates found in the scanned portion.'; list.appendChild(row); }
  if (result.off_slide_truncated || result.overlaps_truncated || result.font_size.candidates_truncated) { const row=document.createElement('li'); row.textContent='Some candidates are omitted; see report counts.'; list.appendChild(row); }
  document.getElementById('layout-scan-output').textContent=JSON.stringify(result, null, 2);
 } catch(error) { if (displayed===revision && layoutRevision===revision) document.getElementById('layout-status').textContent=`Layout error: ${error.message}`; }
 finally { layoutBusy=false; button.disabled=false; }
});
function clearVisualDiff() {
 visualEpoch++; if (visualUrl) URL.revokeObjectURL(visualUrl); visualUrl=null;
 const image=document.getElementById('visual-diff-image'); image.hidden=true; image.removeAttribute('src');
 const link=document.getElementById('visual-diff-open'); link.hidden=true; link.removeAttribute('href');
 document.getElementById('visual-diff-status').textContent='';
}
for (const id of ['visual-before-page','visual-after-page']) document.getElementById(id).addEventListener('input', clearVisualDiff);
document.getElementById('visual-diff-form').addEventListener('submit', async event => {
 event.preventDefault(); if (!comparing || pinned===null || comparedLatest<0) return;
 clearVisualDiff(); const epoch=visualEpoch, before=pinned, after=comparedLatest, before_page=Number(document.getElementById('visual-before-page').value), after_page=Number(document.getElementById('visual-after-page').value);
 const button=document.getElementById('visual-diff-button'), status=document.getElementById('visual-diff-status'); button.disabled=true; status.textContent='Comparing rendered pages…';
 try {
  const response=await fetch('visual-comparison',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({before,after,before_page,after_page})});
  if (!response.ok) { const result=await response.json(); throw new Error(result.error || 'Visual comparison unavailable'); }
  const blob=await response.blob(); if (epoch!==visualEpoch || !comparing || pinned!==before || comparedLatest!==after) return;
  visualUrl=URL.createObjectURL(blob); const image=document.getElementById('visual-diff-image'); image.src=visualUrl; image.alt=`Revision ${before} page ${before_page} compared with revision ${after} page ${after_page}`; image.hidden=false; const link=document.getElementById('visual-diff-open'); link.href=visualUrl; link.hidden=false;
  status.textContent=`Revision ${before} page ${before_page} compared with revision ${after} page ${after_page}.`;
 } catch(error) { if (epoch===visualEpoch && comparing && pinned===before && comparedLatest===after) status.textContent=`Visual comparison error: ${error.message}`; }
 finally { button.disabled=false; }
});
function clearCommentsFor(revision) {
 if (commentListRevision !== null && commentListRevision !== revision) {
  commentListEpoch++; commentListRevision=null; replyTarget=null; document.getElementById('reply-panel').hidden=true; document.getElementById('comments-status').textContent=''; document.getElementById('comments-list').replaceChildren();
 }
}
function clearStoriesFor(revision) {
 if (storiesRevision!==null && storiesRevision!==revision) { storiesEpoch++; storiesRevision=null; document.getElementById('stories-status').textContent=''; document.getElementById('stories-list').replaceChildren(); }
}
function clearWorkbookFor(revision) {
 if (workbookRevision!==null && workbookRevision!==revision) { workbookEpoch++; workbookRevision=null; document.getElementById('workbook-status').textContent=''; document.getElementById('workbook-results').replaceChildren(); }
}
function clearTrackedFor(revision) {
 if (trackedRevision!==null && trackedRevision!==revision) { trackedEpoch++; trackedRevision=null; document.getElementById('tracked-status').textContent=''; document.getElementById('tracked-results').replaceChildren(); document.getElementById('tracked-accept').disabled=true; document.getElementById('tracked-reject').disabled=true; }
}
document.getElementById('tracked-load').addEventListener('click', async () => {
 if (displayed<0 || trackedBusy) return;
 const revision=displayed, epoch=++trackedEpoch, button=document.getElementById('tracked-load'), status=document.getElementById('tracked-status'), output=document.getElementById('tracked-results');
 trackedRevision=revision; button.disabled=true; document.getElementById('tracked-accept').disabled=true; document.getElementById('tracked-reject').disabled=true; output.replaceChildren(); status.textContent=`Inspecting revision ${revision}…`;
 try {
  const response=await fetch('tracked-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not inspect tracked changes');
  if (epoch!==trackedEpoch || displayed!==revision) return;
  for (const item of result.records) {
   const row=document.createElement('li'), label=document.createElement('label'), box=document.createElement('input');
   box.type='checkbox'; box.dataset.part=item.part; box.dataset.id=item.id;
   box.dataset.supported=String((item.kind==='ins' || item.kind==='del') && item.parent==='p' && /^[+-]?[0-9]{1,100}$/.test(item.id));
   box.disabled=box.dataset.supported!=='true' || pinned!==null || current!==revision;
   label.append(box,document.createTextNode(` ${item.story} · ${item.kind} in ${item.parent || 'unknown parent'} · ${item.author || 'unknown author'}${item.date ? ' · '+item.date : ''}: ${item.text || '(no text)'}${item.text_truncated ? '…' : ''}`)); row.appendChild(label); output.appendChild(row);
  }
  document.getElementById('tracked-accept').disabled=pinned!==null || current!==revision;
  document.getElementById('tracked-reject').disabled=pinned!==null || current!==revision;
  const tracking=result.tracking_enabled===null ? 'unknown' : result.tracking_enabled ? 'on' : 'off';
  status.textContent=`Revision ${revision}: ${result.records_scanned} record(s) scanned; saved tracking setting ${tracking}. ${result.records_truncated ? 'Showing the first 200 records. ' : ''}${result.scan_complete ? '' : 'Scan incomplete. '}Other parts and revision types are outside this inventory.`;
 } catch(error) { if (epoch===trackedEpoch) status.textContent=`Tracked changes error: ${error.message}`; }
 finally {button.disabled=false;}
});
async function resolveTracked(accept) {
 if (trackedBusy || trackedRevision===null || displayed!==trackedRevision || current!==trackedRevision || pinned!==null) return;
 const selected=[...document.querySelectorAll('#tracked-results input:checked:not(:disabled)')], status=document.getElementById('tracked-status');
 if (!selected.length) {status.textContent='Select at least one supported run revision.'; return;}
 const part=selected[0].dataset.part;
 if (selected.some(item=>item.dataset.part!==part)) {status.textContent='Select revisions from one document part at a time.'; return;}
 const revision=trackedRevision, ids=selected.map(item=>item.dataset.id); trackedBusy=true;
 document.querySelectorAll('#tracked-panel button, #tracked-results input').forEach(item=>item.disabled=true);
 try {
  const response=await fetch('tracked-resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision,part,ids,accept})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not resolve revisions');
  await refresh(); status.textContent=`Selected revisions ${accept ? 'accepted' : 'rejected'} in revision ${result.revision}.`;
 } catch(error) { status.textContent=`Resolution error: ${error.message}`; }
 finally {
  trackedBusy=false; document.getElementById('tracked-load').disabled=false;
  const live=pinned===null && current===trackedRevision && displayed===trackedRevision;
  document.getElementById('tracked-accept').disabled=!live; document.getElementById('tracked-reject').disabled=!live;
  document.querySelectorAll('#tracked-results input').forEach(item=>item.disabled=!live || item.dataset.supported!=='true');
 }
}
document.getElementById('tracked-accept').addEventListener('click',()=>resolveTracked(true));
document.getElementById('tracked-reject').addEventListener('click',()=>resolveTracked(false));
function clearChartCacheFor(revision) {
 if (chartCacheRevision!==null && chartCacheRevision!==revision) { chartCacheEpoch++; chartCacheRevision=null; document.getElementById('chart-cache-status').textContent=''; document.getElementById('chart-cache-output').textContent=''; document.getElementById('chart-cache-actions').replaceChildren(); }
}
document.getElementById('chart-cache-scan').addEventListener('click', async () => {
 if (displayed<0) return;
 const revision=displayed, epoch=++chartCacheEpoch, button=document.getElementById('chart-cache-scan'), status=document.getElementById('chart-cache-status');
 chartCacheRevision=revision; button.disabled=true; document.getElementById('chart-cache-output').textContent=''; document.getElementById('chart-cache-actions').replaceChildren(); status.textContent=`Checking revision ${revision}…`;
 try {
  const response=await fetch('chart-cache-scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Chart cache check failed');
  if (epoch!==chartCacheEpoch || displayed!==revision) return;
  status.textContent=`Revision ${revision}: ${result.chart_parts_total} chart part(s), ${result.mismatch_references} mismatch candidate(s), ${result.missing_caches} missing cache(s), ${result.unverified_references} unverified reference(s). ${result.complete ? 'Supported checks completed.' : 'Coverage incomplete.'}`;
  document.getElementById('chart-cache-output').textContent=JSON.stringify(result, null, 2);
  const list=document.getElementById('chart-cache-actions');
  for (const chart of result.charts) for (const ref of chart.references) {
   if (ref.status!=='mismatch' || ref.unverified_points || ref.mismatches_truncated || ref.mismatches.some(m=>!['value_differs','missing_point','extra_point'].includes(m.reason)) || chart.external_data || chart.extensions_present) continue;
   const row=document.createElement('li'); row.appendChild(document.createTextNode(`${chart.part} · reference ${ref.index} · ${ref.formula} · ${ref.mismatch_count} mismatch(es) `));
   const sync=document.createElement('button'); sync.type='button'; sync.textContent='Sync cache as new revision'; sync.disabled=revision!==current || pinned!==null;
   sync.addEventListener('click', async () => {
    if (revision!==current || pinned!==null || displayed!==revision || chartCacheRevision!==revision) { status.textContent='Version changed; check the latest revision again.'; return; }
    sync.disabled=true; button.disabled=true; status.textContent='Syncing stored values into this chart cache…';
    try {
     const response=await fetch('chart-cache-sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision,part:chart.part,reference:ref.index})});
     const saved=await response.json(); if (!response.ok) throw new Error(saved.error || 'Cache sync failed');
     list.replaceChildren(); await refresh(); status.textContent=`Synced ${saved.updated_points} point(s) as revision ${saved.revision}. Recheck the chart and render.`;
    } catch(error) { status.textContent=`Chart cache sync error: ${error.message}`; if (revision===current && pinned===null && displayed===revision) sync.disabled=false; }
    finally {button.disabled=false;}
   }); row.appendChild(sync); list.appendChild(row);
  }
 } catch(error) { if (epoch===chartCacheEpoch) status.textContent=`Chart cache error: ${error.message}`; }
 finally {button.disabled=false;}
});
document.getElementById('workbook-load').addEventListener('click', async () => {
 if (displayed<0) return;
 const revision=displayed, epoch=++workbookEpoch, button=document.getElementById('workbook-load'), status=document.getElementById('workbook-status'), output=document.getElementById('workbook-results');
 workbookRevision=revision; button.disabled=true; output.replaceChildren(); status.textContent=`Inspecting revision ${revision}…`;
 try {
  const response=await fetch('workbook-inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Workbook inspection failed');
  if (epoch!==workbookEpoch || displayed!==revision) return;
  for (const sheet of result.sheets) {
   const section=document.createElement('details'), title=document.createElement('summary'); title.textContent=`${sheet.name} (${sheet.state}) · ${sheet.cells.length} sampled cell(s)${sheet.sample_complete ? '' : ' · sample truncated'}`; section.appendChild(title);
   const description=document.createElement('p'); description.textContent=`Declared maximum row ${sheet.declared_max_row ?? 'unknown'}, column ${sheet.declared_max_column ?? 'unknown'}; scanned ${sheet.stored_cells_scanned} stored cell(s).`; section.appendChild(description);
   const list=document.createElement('ul'); for (const cell of sheet.cells) { const row=document.createElement('li'); row.textContent=`${cell.cell || '(address unavailable)'} · ${cell.type}${cell.formula_kind ? ' · formula '+cell.formula_kind : ''}: ${cell.value ?? '(no value)'}${cell.value_truncated ? '…' : ''}${cell.text_complete ? '' : ' (text may be incomplete)'}`; list.appendChild(row); } section.appendChild(list); output.appendChild(section);
  }
  status.textContent=`Revision ${revision}: ${result.total_worksheets} recognized worksheet(s). ${result.worksheets_truncated ? 'Only the first 50 are shown. ' : ''}${result.chartsheet_names.length ? 'Chart sheets: '+result.chartsheet_names.join(', ')+(result.chartsheets_truncated ? '…' : '')+'. ' : ''}Declared dimensions may be inaccurate.`;
 } catch(error) { if (epoch===workbookEpoch) status.textContent=`Workbook inspection error: ${error.message}`; }
 finally {button.disabled=false;}
});
document.getElementById('stories-load').addEventListener('click', async () => {
 if (displayed<0) return;
 const revision=displayed, epoch=++storiesEpoch, button=document.getElementById('stories-load'), status=document.getElementById('stories-status'), list=document.getElementById('stories-list');
 storiesRevision=revision; button.disabled=true; list.replaceChildren(); status.textContent=`Loading revision ${revision}…`;
 try {
  const response=await fetch('stories-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not load headers and footers');
  if (epoch!==storiesEpoch || displayed!==revision) return;
  for (const story of result.stories) {
   const row=document.createElement('li'); row.appendChild(document.createTextNode(`${story.type} ${story.id} · ${story.part} · sections: ${story.linked_sections.map(r=>`${r.section} (${r.type}, ${r.inherited ? 'linked' : 'direct'})`).join(', ') || 'none found'}${story.same_part_ids.length ? ' · same part IDs: '+story.same_part_ids.join(', ') : ''} `));
   const paragraphs=document.createElement('ul');
   for (const paragraph of story.paragraphs) {
    const item=document.createElement('li'); item.textContent=`${paragraph.path}: ${paragraph.text}${paragraph.truncated ? '…' : ''} `;
    const edit=document.createElement('button'); edit.type='button'; edit.textContent='Load for replacement'; edit.disabled=revision!==current || pinned!==null || paragraph.truncated;
    edit.addEventListener('click',()=>{ if (revision!==current || pinned!==null) { status.textContent='Revision changed; load the latest revision.'; return; } document.getElementById('edit-panel').open=true; loadElement(paragraph.path); }); item.appendChild(edit); paragraphs.appendChild(item);
   }
   row.appendChild(paragraphs); list.appendChild(row);
  }
  status.textContent=`Revision ${revision}: ${result.stories.length} relationship(s), ${result.paragraphs_scanned} paragraph(s). ${result.complete ? '' : 'Paragraph inventory incomplete. '}${result.reference_resolution_complete ? '' : 'Section links incomplete. '}First/even page display depends on document settings.`;
 } catch(error) { if (epoch===storiesEpoch) status.textContent=`Header/footer error: ${error.message}`; }
 finally {button.disabled=false;}
});
document.getElementById('comments-load').addEventListener('click', async () => {
 if (commentsBusy || displayed<0) return;
 const revision=displayed, epoch=++commentListEpoch, button=document.getElementById('comments-load'); commentsBusy=true; commentListRevision=revision; button.disabled=true;
 const status=document.getElementById('comments-status'), list=document.getElementById('comments-list'); replyTarget=null; document.getElementById('reply-panel').hidden=true; list.replaceChildren(); status.textContent=`Loading revision ${revision} comments…`;
 try {
  const response=await fetch('comments-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not read comments');
  if (epoch!==commentListEpoch || displayed!==revision || commentListRevision!==revision) return;
  for (const comment of result.comments) {
   const row=document.createElement('li'); const location=comment.paragraph_paths.length ? comment.paragraph_paths.join(', ') : 'No body path found';
   const state=comment.resolved===true ? 'Resolved' : comment.resolved===false ? 'Open' : 'Status unknown';
   const parent=comment.reply_parent_status==='matched' ? ` · Reply to #${comment.reply_to_comment_id}` : comment.reply_to_paragraph_id ? ` · Reply parent ${comment.reply_to_paragraph_id} (${comment.reply_parent_status})` : '';
   row.textContent=`#${comment.id} · ${state}${parent} · ${comment.author || 'Unknown author'} · ${comment.date || 'No date'} · ${comment.text}${comment.text_truncated ? '…' : ''}${comment.text_approximate ? ' (text may be incomplete)' : ''} | Anchor (${comment.anchor_status}): ${comment.anchor_text || '(no text)'}${comment.anchor_text_truncated ? '…' : ''}${comment.anchor_text_approximate ? ' (text may be incomplete)' : ''} | ${location}${comment.path_unavailable || comment.paths_truncated ? ' (some paths unavailable)' : ''}`;
   const canChange=revision===current && pinned===null && (comment.reply_parent_status==='root' && comment.thread_metadata==='matched' || ['absent','available'].includes(result.thread_metadata_status) && ['missing','unavailable'].includes(comment.thread_metadata) && comment.anchor_status==='range');
   if (canChange) {
    const change=document.createElement('button'); change.type='button'; const resolved=comment.resolved!==true;
    change.textContent=resolved ? 'Resolve' : 'Reopen'; change.setAttribute('aria-label',`${change.textContent} comment ${comment.id}`);
    change.addEventListener('click', async () => {
     if (commentsBusy || current!==revision || pinned!==null || displayed!==revision) return;
     commentsBusy=true; button.disabled=true; list.querySelectorAll('button').forEach(item=>item.disabled=true); status.textContent='Saving comment status…';
     try {
      const response=await fetch('resolve-comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:revision,comment_id:comment.id,resolved})});
      const saved=await response.json(); if (!response.ok) throw new Error(saved.error || 'Could not update comment');
      await refresh(); status.textContent=`Comment ${comment.id} ${resolved ? 'resolved' : 'reopened'} in revision ${saved.revision}. Load comments to review.`;
     } catch(error) { status.textContent=`Comment status error: ${error.message}`; }
     finally {commentsBusy=false; button.disabled=false; if (current===revision && pinned===null) list.querySelectorAll('button').forEach(item=>item.disabled=false);}
    });
    row.appendChild(document.createTextNode(' ')); row.appendChild(change);
    if (comment.resolved!==true && comment.anchor_status==='range' && result.anchor_scan_complete) {
     const reply=document.createElement('button'); reply.type='button'; reply.textContent='Reply'; reply.setAttribute('aria-label',`Reply to comment ${comment.id}`);
     reply.addEventListener('click',()=>{if (current!==revision || pinned!==null || displayed!==revision || commentsBusy) return; replyTarget={revision,parent_id:comment.id}; document.getElementById('reply-target').textContent=`Replying to comment ${comment.id}`; document.getElementById('reply-text').value=''; document.getElementById('reply-panel').hidden=false;});
     row.appendChild(document.createTextNode(' ')); row.appendChild(reply);
    }
   }
   list.appendChild(row);
  }
  status.textContent=`Revision ${revision}: ${result.total_comments} comment(s). ${result.truncated ? 'First 200 shown. ' : ''}${result.anchor_scan_complete ? '' : 'Anchor scan incomplete. ' }${result.thread_metadata_status==='available' ? 'Thread metadata loaded; unmatched states remain unknown.' : 'Resolved status is unavailable.'}`;
 } catch(error) { if (epoch===commentListEpoch && displayed===revision) status.textContent=`Comments error: ${error.message}`; }
 finally { commentsBusy=false; button.disabled=false; }
});
document.getElementById('reply-send').addEventListener('click', async () => {
 const target=replyTarget, author=document.getElementById('reply-author').value, text=document.getElementById('reply-text').value;
 const button=document.getElementById('reply-send'), load=document.getElementById('comments-load'), status=document.getElementById('comments-status');
 if (commentsBusy || !target || current!==target.revision || displayed!==target.revision || pinned!==null) return;
 if (!author.trim() || !text.trim()) { status.textContent='Enter an author and reply.'; return; }
 commentsBusy=true; button.disabled=true; load.disabled=true; document.querySelectorAll('#comments-list button').forEach(item=>item.disabled=true);
 try {
  const response=await fetch('reply-comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,parent_id:target.parent_id,text,author})});
  const saved=await response.json(); if (!response.ok) throw new Error(saved.error || 'Could not save reply');
  await refresh(); status.textContent=`Reply saved in revision ${saved.revision}. Load comments to review.`;
 } catch(error) {status.textContent=`Reply error: ${error.message}`;}
 finally {commentsBusy=false; button.disabled=false; load.disabled=false; if (current===target.revision && pinned===null) document.querySelectorAll('#comments-list button').forEach(item=>item.disabled=false);}
});
function invalidateNotes(message) {
 notesEpoch++; notesLoaded=null; document.getElementById('notes-text').readOnly=true; document.getElementById('notes-save').disabled=true; document.getElementById('notes-replace-text').disabled=true;
 if (message) document.getElementById('notes-status').textContent=message;
}
function clearNotesFor(revision, live) {
 if (notesLoaded && (notesLoaded.revision!==revision || !live || notesLoaded.slide!==Number(document.getElementById('notes-slide').value))) {
  if (notesLoaded.revision!==revision || notesLoaded.slide!==Number(document.getElementById('notes-slide').value)) invalidateNotes('View changed; copy pending notes and load the displayed revision.');
  else { document.getElementById('notes-text').readOnly=true; document.getElementById('notes-save').disabled=true; document.getElementById('notes-replace-text').disabled=true; }
 }
}
document.getElementById('notes-slide').addEventListener('input', () => invalidateNotes('Slide changed; load notes before saving.'));
async function loadNotes(requestedSlide=null) {
 if (notesBusy || displayed<0) return;
 if (notesDirty() && !window.confirm('Discard unsaved speaker notes and load another revision or slide?')) return;
 if (requestedSlide!==null) { document.getElementById('notes-slide').value=String(requestedSlide); invalidateNotes('Slide changed; loading notes.'); }
 const revision=displayed, slide=Number(document.getElementById('notes-slide').value), epoch=++notesEpoch;
 const button=document.getElementById('notes-load'), text=document.getElementById('notes-text'), status=document.getElementById('notes-status');
 if (!Number.isSafeInteger(slide) || slide<1) { status.textContent='Choose a positive slide number.'; return; }
 notesBusy=true; button.disabled=true; text.readOnly=true; document.getElementById('notes-save').disabled=true; document.getElementById('notes-replace-text').disabled=true; status.textContent=`Loading slide ${slide} in revision ${revision}…`;
 try {
  const response=await fetch('notes-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,slide})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not read notes');
  if (epoch!==notesEpoch || displayed!==revision || Number(document.getElementById('notes-slide').value)!==slide) return;
  text.value=result.text; text.disabled=false; notesBaseline=result.text; notesLoaded={revision,slide,truncated:result.truncated};
  const editable=revision===current && pinned===null && !result.truncated;
  text.readOnly=!editable; document.getElementById('notes-save').disabled=!editable; document.getElementById('notes-replace-text').disabled=!editable;
  status.textContent=`Revision ${revision}, slide ${slide}. ${result.truncated ? 'Notes were truncated; editing is unavailable.' : editable ? 'Ready to edit.' : 'Read-only preview.'}`;
  return true;
 } catch(error) {
  if (epoch===notesEpoch) {
   status.textContent=`Notes error: ${error.message}`;
   if (notesLoaded && notesLoaded.revision===current && notesLoaded.revision===displayed && notesLoaded.slide===Number(document.getElementById('notes-slide').value) && pinned===null && !notesLoaded.truncated) { text.readOnly=false; document.getElementById('notes-save').disabled=false; document.getElementById('notes-replace-text').disabled=false; }
  }
 }
 finally { notesBusy=false; button.disabled=false; }
}
document.getElementById('slide-order-load').addEventListener('click', async () => {
 if (slideOrderBusy || displayed<0) return;
 if (slideOrderLoaded && document.getElementById('slide-order-input').value!==slideOrderLoaded.initial && !window.confirm('Discard the unsaved slide order and reload?')) return;
 const revision=displayed, hash=displayedHash, status=document.getElementById('slide-order-status'); slideOrderBusy=true;
 document.getElementById('slide-order-save').disabled=true; status.textContent=`Loading revision ${revision}…`;
 try {
  const response=await fetch('slide-order-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not list slides');
  if (displayed!==revision || displayedHash!==hash || result.snapshot_sha256!==hash) throw new Error('Preview changed; load again');
  const list=document.getElementById('slide-order-list'); list.replaceChildren(...result.slides.map(slide=>{const item=document.createElement('li'); item.textContent=`${slide.title || '(untitled)'}${slide.hidden ? ' · hidden' : ''}${slide.has_notes ? ' · notes' : ''}`; return item;}));
  document.getElementById('slide-order-sections').textContent=result.section_status==='supported' ? result.sections.map(section=>`${section.name || '(unnamed)'}: ${section.slides.join(', ')}`).join(' · ') : result.section_status==='unsupported' ? `Sections unavailable: ${result.section_issue}` : 'No sections.';
  document.getElementById('slide-order-input').value=result.slides.map(slide=>slide.slide).join(', ');
  slideOrderLoaded={revision,hash,count:result.slides.length,initial:document.getElementById('slide-order-input').value};
  const editable=revision===current && pinned===null && !comparing && result.slides.length>0 && result.section_status!=='unsupported';
  document.getElementById('slide-order-save').disabled=!editable; status.textContent=editable ? `Revision ${revision}: ready to reorder.` : `Revision ${revision}: read-only or unsupported.`;
 } catch(error) { slideOrderLoaded=null; status.textContent=`Slide list error: ${error.message}`; }
 finally { slideOrderBusy=false; }
});
document.getElementById('slide-order-form').addEventListener('submit', async event => {
 event.preventDefault(); const target=slideOrderLoaded, status=document.getElementById('slide-order-status');
 if (slideOrderBusy || !target || target.revision!==current || target.revision!==displayed || target.hash!==displayedHash || pinned!==null || comparing) { document.getElementById('slide-order-save').disabled=true; status.textContent='Revision changed; load the slide list again.'; return; }
 const raw=document.getElementById('slide-order-input').value.split(',').map(value=>value.trim());
 if (raw.length!==target.count || raw.some(value=>!/^[0-9]+$/.test(value))) { status.textContent='Enter every slide number once, separated by commas.'; return; }
 const order=raw.map(Number); if (new Set(order).size!==target.count || order.some(value=>!Number.isSafeInteger(value) || value<1 || value>target.count)) { status.textContent='Enter every slide number once, separated by commas.'; return; }
 slideOrderBusy=true; document.getElementById('slide-order-save').disabled=true;
 try {
  const response=await fetch('slide-order-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,snapshot_sha256:target.hash,order})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not reorder slides');
  slideOrderLoaded=null; status.textContent=`Saved revision ${result.revision}; load its slide list to continue.`; await refresh();
 } catch(error) { status.textContent=`Slide order error: ${error.message}`; if (target.revision===current && target.revision===displayed && target.hash===displayedHash && pinned===null && !comparing) document.getElementById('slide-order-save').disabled=false; }
 finally { slideOrderBusy=false; }
});
document.getElementById('notes-load').addEventListener('click',()=>loadNotes());
document.getElementById('notes-form').addEventListener('submit', async event => {
 event.preventDefault(); const target=notesLoaded, text=document.getElementById('notes-text'), status=document.getElementById('notes-status');
 if (notesBusy || !target || target.truncated || pinned!==null || target.revision!==current || target.revision!==displayed || target.slide!==Number(document.getElementById('notes-slide').value)) { invalidateNotes('Version or slide changed; load notes again.'); return; }
 const value=text.value, button=document.getElementById('notes-save'); notesBusy=true; button.disabled=true; document.getElementById('notes-replace-text').disabled=true; text.readOnly=true;
 try {
  const response=await fetch('notes-replace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,slide:target.slide,text:value})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not save notes');
  notesBaseline=value; invalidateNotes(`Notes saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  status.textContent=`Notes error: ${error.message}`;
  if (notesLoaded===target && current===target.revision && pinned===null && displayed===target.revision) { text.readOnly=false; button.disabled=false; document.getElementById('notes-replace-text').disabled=false; }
 } finally { notesBusy=false; }
});
document.getElementById('notes-replace-text').addEventListener('click', async () => {
 const target=notesLoaded, text=document.getElementById('notes-text'), status=document.getElementById('notes-status');
 if (notesBusy || !target || target.truncated || pinned!==null || target.revision!==current || target.revision!==displayed || target.slide!==Number(document.getElementById('notes-slide').value)) { invalidateNotes('Version or slide changed; load notes again.'); return; }
 if (notesDirty()) { status.textContent='Save or copy the pending notes before replacing text.'; return; }
 const paragraph=Number(document.getElementById('notes-paragraph').value), find=document.getElementById('notes-find').value, replacement=document.getElementById('notes-replacement').value;
 if (!Number.isSafeInteger(paragraph) || paragraph<1 || !find) { status.textContent='Enter a paragraph number and text to find.'; return; }
 notesBusy=true; text.readOnly=true; document.getElementById('notes-save').disabled=true; document.getElementById('notes-replace-text').disabled=true;
 try {
  const response=await fetch('notes-replace-text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:target.revision,slide:target.slide,paragraph,find,replacement})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Could not replace notes text');
  invalidateNotes(`Replacement saved as revision ${result.revision}; load it to see updated notes.`); await refresh();
 } catch(error) {
  status.textContent=`Notes error: ${error.message}`;
  if (notesLoaded===target && current===target.revision && pinned===null && displayed===target.revision) { text.readOnly=false; document.getElementById('notes-save').disabled=false; document.getElementById('notes-replace-text').disabled=false; }
 } finally { notesBusy=false; }
});
function showRenderAdvisory(items) {
 const messages=items.filter(item=>item[1] && item[1].dynamic_array_metadata !== false).map(([label, info])=>`${label}: ${info.dynamic_array_metadata === true ? 'dynamic-array metadata detected' : 'dynamic-array metadata could not be inspected'}. LibreOffice previews may omit spill results; review in a compatible application.`);
 const output=document.getElementById('render-advisory'); output.hidden=!messages.length; output.textContent=messages.join(' ');
}
function display(state, live) {
 displayedHash=state.snapshot_sha256;
 if (slideOrderLoaded && (slideOrderLoaded.revision!==state.revision || slideOrderLoaded.hash!==state.snapshot_sha256 || !live)) document.getElementById('slide-order-save').disabled=true;
 showRenderAdvisory([[`Revision ${state.revision}`,state.render_advisory]]);
 clearTrackedFor(state.revision);
 document.querySelectorAll('#tracked-results input').forEach(item=>item.disabled=trackedBusy || !live || item.dataset.supported!=='true');
 document.getElementById('tracked-accept').disabled=trackedBusy || !live || trackedRevision!==state.revision; document.getElementById('tracked-reject').disabled=trackedBusy || !live || trackedRevision!==state.revision;
 if (textSearchState && textSearchState.revision!==state.revision) clearTextSearch();
 document.querySelectorAll('#text-search-results button').forEach(button=>button.disabled=!live);
 document.querySelectorAll('#slide-text-results button').forEach(button=>button.disabled=!live);
 clearChartCacheFor(state.revision);
 if (!live) document.querySelectorAll('#chart-cache-actions button').forEach(button=>button.disabled=true);
 clearWorkbookFor(state.revision);
 clearStoriesFor(state.revision);
 if (!live) document.querySelectorAll('#stories-list button').forEach(button=>button.disabled=true);
 notesComparisonEpoch++;
 clearNotesFor(state.revision, live);
 clearCommentsFor(state.revision);
 if (!document.getElementById('comparison-details').hidden) clearVisualDiff();
 clearLayoutFor(state.revision);
 document.getElementById('comparison-details').hidden=true;
 const key = `${state.revision}:${live}:${state.snapshot_sha256}`;
 if (key === viewKey) return;
 const fragment = document.createDocumentFragment();
 for (let i=0; i<state.pages; i++) {
  const image=document.createElement('img'); image.src=`page/${state.revision}/${i}`;
  image.alt=`Revision ${state.revision}, page ${i+1}`; image.loading='lazy'; image.draggable=false;
  fragment.appendChild(selectable(image, i+1, state.revision, live));
 }
 document.getElementById('pages').replaceChildren(fragment); displayed=state.revision; displayedPages=state.pages; viewKey=key; clearCandidates();
 if (layoutHighlight) showLayoutHighlight(layoutHighlight,false);
 document.getElementById('selection').textContent = live ? 'Drag on a page to save a selection for the agent.' : 'Selections are available on the latest revision.';
 document.querySelectorAll('#selection-form input, #selection-form button, #edit-path, #edit-load, #grid-sheets, #grid-sheet, #grid-range, #grid-load').forEach(element => element.disabled=!live);
 document.getElementById('formula-scan').disabled=!live || scanBusy || calcBusy; document.getElementById('formula-recalculate').disabled=!live || scanBusy || calcBusy;
 if (!live) invalidateGrid('Return to the latest revision to edit cells.');
 if (!live) invalidateEdit('Return to the latest revision to edit.');
}
function displayComparison(state) {
 displayedHash=null;
 showRenderAdvisory([[`Revision ${state.revision}`,state.render_advisory],[`Revision ${state.latest_revision}`,state.latest_render_advisory]]);
 clearChartCacheFor(state.revision);
 document.querySelectorAll('#chart-cache-actions button').forEach(button=>button.disabled=true);
 clearWorkbookFor(state.revision);
 clearStoriesFor(state.revision);
 document.querySelectorAll('#stories-list button').forEach(button=>button.disabled=true);
 clearNotesFor(state.revision, false);
 clearCommentsFor(state.revision);
 clearTrackedFor(state.revision);
 document.querySelectorAll('#tracked-results input, #tracked-accept, #tracked-reject').forEach(item=>item.disabled=true);
 clearLayoutFor(state.revision);
 const key=`compare:${state.revision}:${state.snapshot_sha256}:${state.latest_revision}:${state.latest_snapshot_sha256}`;
 if (key === viewKey) return;
 notesComparisonEpoch++; document.getElementById('notes-comparison-output').textContent=''; document.getElementById('notes-comparison-status').textContent='';
 clearVisualDiff(); document.getElementById('visual-before-page').max=state.pages; document.getElementById('visual-after-page').max=state.latest_pages;
 const grid=document.createElement('div'); grid.className='comparison';
 for (const [revision, count, label] of [[state.revision,state.pages,'Selected'], [state.latest_revision,state.latest_pages,'Latest']]) {
  const section=document.createElement('section'); const title=document.createElement('h2');
  title.textContent=`${label} · revision ${revision} · ${count} page(s)`; section.appendChild(title);
  for (let i=0; i<count; i++) {
   const image=document.createElement('img'); image.src=`page/${revision}/${i}`; image.loading='lazy';
   image.alt=`${label} revision ${revision}, page ${i+1}`;
   const wrapper=document.createElement('div'); wrapper.className='comparison-page'; wrapper.dataset.layoutRevision=String(revision); wrapper.dataset.layoutPage=String(i+1); wrapper.dataset.layoutSide=label.toLowerCase(); wrapper.appendChild(image); section.appendChild(wrapper);
  }
  grid.appendChild(section);
 }
 document.getElementById('pages').replaceChildren(grid); displayed=state.revision; displayedPages=state.pages; viewKey=key; clearCandidates();
 if (layoutHighlight) showLayoutHighlight(layoutHighlight,false);
 document.getElementById('comparison-details').hidden=false;
 document.getElementById('changes-status').textContent='';
 document.getElementById('comparison-text').textContent=''; document.getElementById('comparison-parts').textContent='';
 cellComparisonEpoch++; document.getElementById('cell-comparison-output').replaceChildren(); document.getElementById('cell-comparison-status').textContent='';
 document.getElementById('selection').textContent='Selections are available on the latest revision.';
 document.querySelectorAll('#selection-form input, #selection-form button, #edit-path, #edit-load, #grid-sheets, #grid-sheet, #grid-range, #grid-load, #formula-scan, #formula-recalculate').forEach(element => element.disabled=true);
 invalidateGrid('Return to the latest revision to edit cells.');
 invalidateEdit('Return to the latest revision to edit.');
}
document.getElementById('load-changes').addEventListener('click', async () => {
 if (!comparing || pinned === null || comparedLatest < 0) return;
 const before=pinned, after=comparedLatest, button=document.getElementById('load-changes'); button.disabled=true;
 document.getElementById('changes-status').textContent='Loading changes…';
 try {
  const response=await fetch(`comparison/${before}/${after}/changes`, {cache:'no-store'});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Changes unavailable');
  if (!comparing || pinned !== before || comparedLatest !== after) return;
  document.getElementById('comparison-text').textContent=result.text_diff.length ? result.text_diff.join('\\n') : 'No text changes in the bounded views.';
  document.getElementById('comparison-parts').textContent=['added','removed','modified'].map(kind => `${kind}:\\n${result.parts[kind].join('\\n') || '(none)'}`).join('\\n\\n');
  document.getElementById('changes-status').textContent=`Revision ${before} → ${after}. Text view may be truncated; ${result.text_diff_truncated ? 'diff output was truncated.' : 'diff output is within its limit.'}`;
 } catch (error) { if (comparing && pinned === before && comparedLatest === after) document.getElementById('changes-status').textContent=`Changes error: ${error.message}`; }
 finally { button.disabled=false; }
});
for (const id of ['compare-sheet','compare-range']) document.getElementById(id).addEventListener('input', () => {
 cellComparisonEpoch++; document.getElementById('cell-comparison-output').replaceChildren(); document.getElementById('cell-comparison-status').textContent='Inputs changed; compare again.';
});
for (const id of ['notes-before-slide','notes-after-slide']) document.getElementById(id).addEventListener('input', () => {
 notesComparisonEpoch++; document.getElementById('notes-comparison-output').textContent=''; document.getElementById('notes-comparison-status').textContent='Inputs changed; compare again.';
});
document.getElementById('notes-comparison-form').addEventListener('submit', async event => {
 event.preventDefault(); if (!comparing || pinned===null || comparedLatest<0) return;
 const before=pinned, after=comparedLatest, before_slide=Number(document.getElementById('notes-before-slide').value), after_slide=Number(document.getElementById('notes-after-slide').value), epoch=++notesComparisonEpoch;
 const button=document.getElementById('compare-notes'), status=document.getElementById('notes-comparison-status'), output=document.getElementById('notes-comparison-output'); button.disabled=true; output.textContent=''; status.textContent='Comparing speaker notes…';
 try {
  const response=await fetch('notes-comparison',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({before,after,before_slide,after_slide})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Comparison unavailable');
  if (epoch!==notesComparisonEpoch || !comparing || pinned!==before || comparedLatest!==after) return;
  const changed=result.text_changed===null ? 'Text equality is unknown because notes were truncated.' : result.text_changed ? 'Text changed.' : 'Text is identical.';
  status.textContent=`Revision ${before} slide ${before_slide} → revision ${after} slide ${after_slide}. ${changed} Notes part: ${result.before_has_notes ? 'present' : 'absent'} → ${result.after_has_notes ? 'present' : 'absent'}. ${result.truncated ? 'Diff is truncated.' : ''}`;
  output.textContent=result.diff.length ? result.diff.join('\\n') : 'No differences in the compared text view.';
 } catch(error) { if (epoch===notesComparisonEpoch && comparing && pinned===before && comparedLatest===after) status.textContent=`Notes comparison error: ${error.message}`; }
 finally { button.disabled=false; }
});
document.getElementById('cell-comparison-form').addEventListener('submit', async event => {
 event.preventDefault(); if (!comparing || pinned === null || comparedLatest < 0) return;
 const before=pinned, after=comparedLatest, sheet=document.getElementById('compare-sheet').value, cell_range=document.getElementById('compare-range').value;
 const epoch=++cellComparisonEpoch, button=document.getElementById('compare-cells'), output=document.getElementById('cell-comparison-output');
 button.disabled=true; output.replaceChildren(); document.getElementById('cell-comparison-status').textContent='Comparing cells…';
 try {
  const response=await fetch('cell-comparison', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({before,after,sheet,cell_range})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Comparison unavailable');
  if (epoch !== cellComparisonEpoch || !comparing || pinned !== before || comparedLatest !== after) return;
  const table=document.createElement('table'), head=document.createElement('thead'), header=document.createElement('tr');
  for (const label of ['Cell','Changed field','Before','After']) { const th=document.createElement('th'); th.scope='col'; th.textContent=label; header.appendChild(th); }
  head.appendChild(header); table.appendChild(head); const body=document.createElement('tbody');
  for (const change of result.changes) for (const field of change.changed_fields) {
   const row=document.createElement('tr'), key=field.startsWith('format.') ? field.slice(7) : field;
   const old=field.startsWith('format.') ? change.before.format[key] : change.before[key];
   const next=field.startsWith('format.') ? change.after.format[key] : change.after[key];
   for (const value of [change.cell,field,old,next]) { const td=document.createElement('td'); td.textContent=value === undefined ? '(absent)' : (typeof value === 'string' ? value : JSON.stringify(value)); row.appendChild(td); }
   body.appendChild(row);
  }
  table.appendChild(body); if (result.changes.length) output.appendChild(table);
  const dimensions=result.dimensions, heading=document.createElement('h3'); heading.textContent='Stored row and column dimensions'; output.appendChild(heading);
  if (dimensions.status==='error') {const message=document.createElement('p'); message.textContent=`Dimension comparison unavailable: ${dimensions.error}`; output.appendChild(message);}
  else {
   const message=document.createElement('p'); message.textContent=`${dimensions.changed_count} changed dimension(s). ${dimensions.complete ? '' : 'Some dimension metadata needs review. '}${dimensions.truncated ? 'Showing first 500. ' : ''}Stored attributes may differ from effective display; changes affect entire rows or columns.`; output.appendChild(message);
   const list=document.createElement('ul');
   for (const change of dimensions.changes) {const item=document.createElement('li'); item.textContent=`${change.kind} ${change.target}: ${change.changed_fields.join(', ')} · ${JSON.stringify(change.before)} → ${JSON.stringify(change.after)}`; list.appendChild(item);}
   output.appendChild(list);
  }
  document.getElementById('cell-comparison-status').textContent=`Revision ${before} → ${after}: ${result.changed_count} changed cell(s). ${result.truncated ? 'Showing the first 500 cells. ' : ''}${result.text_comparison_complete ? '' : 'Some text values could not be verified. '}`;
 } catch(error) { if (epoch === cellComparisonEpoch && comparing && pinned === before && comparedLatest === after) document.getElementById('cell-comparison-status').textContent=`Cell comparison error: ${error.message}`; }
 finally { button.disabled=false; }
});
async function loadComparison(revision) {
 const response=await fetch(`comparison/${revision}/state`, {cache:'no-store'}); const state=await response.json();
 if (!response.ok) throw new Error(state.error || 'Comparison unavailable');
 if (!comparing || pinned !== revision || state.latest_revision < current) return;
 displayComparison(state); comparedLatest=state.latest_revision; comparedLatestHash=state.latest_snapshot_sha256;
 document.getElementById('status').textContent=`Comparing revision ${revision} with latest ${state.latest_revision}`;
}
document.getElementById('compare-revision').addEventListener('click', async () => {
 const revision=Number(document.getElementById('restore-revision').value); pinned=revision; comparing=true; comparedLatest=-1;
 try { await loadComparison(revision); }
 catch (error) { if (comparing && pinned === revision) { comparing=false; pinned=null; document.getElementById('restore-status').textContent=`Comparison error: ${error.message}`; refresh(); } }
});
document.getElementById('preview-revision').addEventListener('click', async () => {
 const revision=Number(document.getElementById('restore-revision').value); pinned=revision; comparing=false;
 try {
  const response=await fetch(`revision/${revision}/state`, {cache:'no-store'}); const state=await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  if (pinned !== revision || comparing) return;
  display(state, false); document.getElementById('status').textContent=`Viewing revision ${revision} · latest ${current} · ${state.pages} page(s)`;
 } catch (error) { if (!comparing && pinned === revision) { pinned=null; document.getElementById('restore-status').textContent=`Preview error: ${error.message}`; refresh(); } }
});
document.getElementById('show-latest').addEventListener('click', () => { pinned=null; comparing=false; viewKey=''; refresh(); });
async function refresh() {
 if (busy) return; busy = true;
 try {
  const response = await fetch('state', {cache:'no-store'});
  const state = await response.json();
  if (!response.ok) throw new Error(state.error || 'Preview unavailable');
  document.getElementById('comments-panel').hidden=state.format !== 'docx';
  const scopeControl=document.getElementById('text-search-scope'), available=state.format==='docx' ? ['body','stories','word-notes'] : state.format==='pptx' ? ['slides','notes'] : ['body'];
  for (const option of scopeControl.options) option.hidden=!available.includes(option.value);
  if (!available.includes(scopeControl.value)) { scopeControl.value=available[0]; clearTextSearch(); }
  document.getElementById('text-search-scope-label').hidden=state.format === 'xlsx';
  document.getElementById('tracked-panel').hidden=state.format !== 'docx';
  document.getElementById('stories-panel').hidden=state.format !== 'docx';
  document.getElementById('slide-order-panel').hidden=state.format !== 'pptx';
  document.getElementById('notes-panel').hidden=state.format !== 'pptx';
  document.getElementById('notes-comparison').hidden=state.format !== 'pptx';
  document.getElementById('layout-panel').hidden=state.format !== 'pptx';
  document.getElementById('formula-panel').hidden=state.format !== 'xlsx';
  document.getElementById('chart-cache-panel').hidden=state.format !== 'xlsx';
  document.getElementById('workbook-panel').hidden=state.format !== 'xlsx';
  document.getElementById('grid-panel').hidden=state.format !== 'xlsx'; document.getElementById('cell-comparison').hidden=state.format !== 'xlsx';
  const snapshotChanged = pinned===null && displayed===current && displayedHash && state.snapshot_sha256!==displayedHash;
  if (state.revision !== current || snapshotChanged) {
   document.getElementById('formula-allow-dynamic').checked=false;
   if (snapshotChanged || formulaStatusRevision !== state.revision) { formulaStatusRevision=null; document.getElementById('formula-status').textContent=''; document.getElementById('formula-scan-output').textContent=''; }
   if (gridLoaded) invalidateGrid('Version or preview source changed; copy unsaved edits and reload the range.');
   if (loaded) invalidateEdit('Version or preview source changed; load the element again.');
   const select=document.getElementById('restore-revision'); const previous=select.value;
   select.replaceChildren(...state.revisions.map(revision => {const option=document.createElement('option'); option.value=revision; option.textContent=`Revision ${revision}`; return option;}));
   if (state.revisions.some(revision => String(revision) === previous)) select.value=previous;
  }
  current=state.revision;
  if (comparing && pinned !== null) {
   if (comparedLatest !== current || comparedLatestHash !== state.snapshot_sha256) await loadComparison(pinned);
  } else if (pinned === null) {
   display(state, true); document.getElementById('status').textContent=`Revision ${current} · ${state.pages} page(s)`;
  } else if (displayed === pinned) {
   document.getElementById('status').textContent=`Viewing revision ${displayed} · latest ${current}`;
  }
 } catch (error) { document.getElementById('status').textContent = `Preview error: ${error.message}`; }
 finally { busy = false; }
}
refresh(); setInterval(refresh, 2000);
</script></body></html>'''


def serve(directory, preview, port=0, render=None):
    directory = session.info(directory)['directory']
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    token = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    lock = threading.Lock()
    cache = OrderedDict()
    with tempfile.TemporaryDirectory(prefix='office-watch-') as tmp:
        root = Path(tmp)

        def pages_for(state, revision):
            source = session.revision_file(state, revision)
            if revision not in cache:
                with tempfile.TemporaryDirectory(dir=root, prefix='.snapshot-') as tmp_source:
                    frozen, digest = snapshot.copy(source, tmp_source)
                    cache[revision] = {'pages': preview(frozen, root / f'rev-{revision}'), 'render_advisory': spreadsheet.render_advisory(frozen), 'snapshot_sha256': digest}
                if len(cache) > 4:
                    old, _ = cache.popitem(last=False)
                    shutil.rmtree(root / f'rev-{old}', ignore_errors=True)
            cache.move_to_end(revision)
            return cache[revision]['pages']

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def send(self, status, body, content_type):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', f"default-src 'none'; img-src 'self' blob:; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                port = cast(ThreadingHTTPServer, self.server).server_port
                host = f'127.0.0.1:{port}'
                if self.headers.get('Host') != host or self.headers.get('Origin') != 'http://' + host:
                    self.send(403, b'Forbidden', 'text/plain; charset=utf-8'); return
                route = urlsplit(self.path).path
                if route not in ('/' + token + '/selection', '/' + token + '/restore', '/' + token + '/element', '/' + token + '/edit', '/' + token + '/candidates', '/' + token + '/sheets', '/' + token + '/grid', '/' + token + '/grid-edit', '/' + token + '/grid-format', '/' + token + '/grid-resize', '/' + token + '/grid-freeze', '/' + token + '/grid-merge', '/' + token + '/cell-comparison', '/' + token + '/visual-comparison', '/' + token + '/replace-text', '/' + token + '/track-replace-text', '/' + token + '/track-insert-text', '/' + token + '/add-comment', '/' + token + '/resolve-comment', '/' + token + '/reply-comment', '/' + token + '/replace-picture', '/' + token + '/formula-scan', '/' + token + '/formula-recalculate', '/' + token + '/layout-scan', '/' + token + '/slide-text-scan', '/' + token + '/comments-read', '/' + token + '/tracked-read', '/' + token + '/tracked-resolve', '/' + token + '/stories-read', '/' + token + '/workbook-inspect', '/' + token + '/text-search', '/' + token + '/chart-cache-scan', '/' + token + '/chart-cache-sync', '/' + token + '/slide-order-read', '/' + token + '/slide-order-save', '/' + token + '/notes-read', '/' + token + '/notes-replace', '/' + token + '/notes-replace-text', '/' + token + '/notes-comparison'):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                length = self.headers.get('Content-Length', '')
                limit = 14 * 1024 * 1024 if route.endswith('/replace-picture') else 650000 if route.endswith('/notes-replace') else 65000 if route.endswith('/notes-replace-text') else 20000
                if self.headers.get('Content-Type') != 'application/json' or not length.isdecimal() or len(length) > 8 or not 0 < int(length) <= limit:
                    self.send(400, b'Invalid request', 'text/plain; charset=utf-8'); return
                try:
                    payload = json.loads(self.rfile.read(int(length)))
                    if route.endswith('/text-search'):
                        if not isinstance(payload, dict) or set(payload) not in ({'revision', 'query', 'offset', 'snapshot_sha256'}, {'revision', 'query', 'scope', 'offset', 'snapshot_sha256'}):
                            raise ValueError('Search requires revision, query, offset and snapshot SHA-256')
                        state = session.info(directory)
                        scope = payload.get('scope', 'body')
                        allowed = {'docx': ('body', 'stories', 'word-notes'), 'xlsx': ('body',), 'pptx': ('body', 'slides', 'notes')}
                        if scope not in allowed[state['format']]: raise ValueError('Invalid search scope')
                        args = (directory, payload['revision'], payload['query'])
                        options = {'offset': payload['offset'], 'snapshot_sha256': payload['snapshot_sha256']}
                        search = {'docx': session.search_stories if scope == 'stories' else session.search_notes if scope == 'word-notes' else session.search_body, 'xlsx': session.search_cells, 'pptx': session.search_slides}[state['format']]
                        if state['format'] == 'pptx': options['scope'] = 'notes' if scope == 'notes' else 'slides'
                        saved = {'format': state['format'], **search(*args, **options)}
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/chart-cache-scan'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Chart cache scan requires a revision')
                        saved = session.scan_chart_caches(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/workbook-inspect'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Workbook inspection requires a revision')
                        saved = session.inspect_workbook(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/stories-read'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Header/footer inventory requires a revision')
                        saved = session.list_stories(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/notes-comparison'):
                        if not isinstance(payload, dict) or set(payload) != {'before', 'after', 'before_slide', 'after_slide'}:
                            raise ValueError('Notes comparison requires revisions and slide numbers')
                        with lock:
                            if payload['after'] != session.info(directory)['latest_revision']:
                                raise ValueError('Latest revision changed; compare again')
                        result = session.compare_notes(directory, payload['before'], payload['after'], payload['before_slide'], payload['after_slide'])
                        with lock:
                            if payload['after'] != session.info(directory)['latest_revision']:
                                raise ValueError('Latest revision changed; compare again')
                        self.send(200, json.dumps(result).encode(), 'application/json'); return
                    if route.endswith('/slide-order-read'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Slide inventory requires revision')
                        saved = session.inventory_slides(directory, payload['revision'])
                        self.send(200, json.dumps(saved).encode(), 'application/json'); return
                    if route.endswith('/slide-order-save'):
                        if not isinstance(payload, dict) or set(payload) != {'base_revision', 'snapshot_sha256', 'order'}: raise ValueError('Slide reorder requires revision, snapshot and order')
                        if not isinstance(payload['snapshot_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['snapshot_sha256']): raise ValueError('Slide reorder requires a valid snapshot SHA-256')
                        with lock:
                            saved = session.reorder_slides(directory, payload['base_revision'], payload['order'], expected_sha256=payload['snapshot_sha256'])
                        self.send(200, json.dumps(saved).encode(), 'application/json'); return
                    if route.endswith('/notes-read'):
                        if not isinstance(payload, dict) or set(payload) != {'revision', 'slide'}:
                            raise ValueError('Notes reading requires revision and slide')
                        saved = session.read_notes(directory, payload['revision'], payload['slide'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/tracked-read'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Tracked changes require a revision')
                        saved = session.tracked_changes(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/comments-read'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}:
                            raise ValueError('Comments require a revision')
                        saved = session.list_comments(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/slide-text-scan'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}: raise ValueError('Slide text scan requires a revision')
                        saved = session.inspect_slide_text(directory, payload['revision'], render)
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/layout-scan'):
                        if not isinstance(payload, dict) or set(payload) != {'revision'}:
                            raise ValueError('Layout inspection requires revision')
                        saved = session.inspect_layout(directory, payload['revision'])
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/formula-scan') or route.endswith('/formula-recalculate'):
                        if not isinstance(payload, dict) or (set(payload) != {'base_revision'} and not (route.endswith('/formula-recalculate') and set(payload) == {'base_revision', 'allow_dynamic_arrays'})):
                            raise ValueError('Formula operation requires base_revision and optional dynamic-array override')
                        saved = session.scan_formulas(directory, payload['base_revision']) if route.endswith('/formula-scan') else session.recalculate(directory, payload['base_revision'], payload.get('allow_dynamic_arrays', False))
                        self.send(200, json.dumps(saved, default=str).encode(), 'application/json'); return
                    if route.endswith('/visual-comparison'):
                        if not isinstance(payload, dict) or set(payload) != {'before', 'after', 'before_page', 'after_page'}:
                            raise ValueError('Visual comparison requires revisions and pages')
                        if render is None:
                            raise RuntimeError('Visual comparison rendering is unavailable')
                        with lock:
                            state = session.info(directory)
                            before = session.revision_file(state, payload['before'])
                            after = session.revision_file(state, payload['after'])
                            if payload['after'] != state['latest_revision']:
                                raise ValueError('Latest revision changed; compare again')
                        data, _ = visual.compare_pages(before, after, payload['before_page'], payload['after_page'], render)
                        with lock:
                            if session.info(directory)['latest_revision'] != payload['after']:
                                raise ValueError('Latest revision changed; compare again')
                        self.send(200, data, 'image/png'); return
                    if route.endswith('/cell-comparison'):
                        if not isinstance(payload, dict) or set(payload) != {'before', 'after', 'sheet', 'cell_range'}:
                            raise ValueError('Cell comparison requires revisions, sheet and range')
                        with lock:
                            state = session.info(directory)
                            before = session.revision_file(state, payload['before'])
                            after = session.revision_file(state, payload['after'])
                            if payload['after'] != state['latest_revision']:
                                raise ValueError('Latest revision changed; compare again')
                        result = review.compare_cells(before, after, payload['sheet'], payload['cell_range'])
                        with lock:
                            if session.info(directory)['latest_revision'] != payload['after']:
                                raise ValueError('Latest revision changed; compare again')
                        self.send(200, json.dumps(result, default=str).encode(), 'application/json'); return
                    if route.endswith('/candidates'):
                        if not isinstance(payload, dict) or set(payload) != {'selection', 'snapshot_sha256'} or not isinstance(payload['snapshot_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['snapshot_sha256']):
                            raise ValueError('Candidates require a saved selection and preview snapshot SHA-256')
                        expected = session.validate_selection(payload['selection']); expected_hash = payload['snapshot_sha256']
                        with lock:
                            selected = session.get_selection(directory)
                            if selected['stale'] or any(selected[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                            state = session.info(directory); pages_for(state, expected['revision'])
                            if cache[expected['revision']]['snapshot_sha256'] != expected_hash: raise ValueError('Preview snapshot changed; reload the page')
                        if render is None:
                            raise RuntimeError('Candidate rendering is unavailable')
                        result = selection_candidates.candidates(directory, render)
                        with lock:
                            selected = session.get_selection(directory)
                            if result['snapshot_sha256'] != expected_hash:
                                cache.pop(expected['revision'], None); shutil.rmtree(root / f"rev-{expected['revision']}", ignore_errors=True)
                                raise ValueError('Preview source changed; reload the browser page and select again')
                            if selected['stale'] or result['stale'] or result['selection_changed'] or any(selected[key] != expected[key] for key in expected) or any(result[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                        self.send(200, json.dumps(result).encode(), 'application/json'); return
                    with lock:
                        if route.endswith('/chart-cache-sync'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'part', 'reference'}: raise ValueError('Chart cache sync requires revision, part and reference')
                            saved = session.sync_chart_cache(directory, payload['base_revision'], payload['part'], payload['reference'])
                        elif route.endswith('/notes-replace-text'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'slide', 'paragraph', 'find', 'replacement'}:
                                raise ValueError('Notes text replacement requires revision, slide, paragraph, find and replacement')
                            saved = session.replace_notes_text(directory, payload['base_revision'], payload['slide'], payload['paragraph'], payload['find'], payload['replacement'])
                        elif route.endswith('/notes-replace'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'slide', 'text'}:
                                raise ValueError('Notes replacement requires revision, slide and text')
                            saved = session.replace_notes(directory, payload['base_revision'], payload['slide'], payload['text'])
                        elif route.endswith('/selection'):
                            selection = session.validate_selection(payload)
                            pages = cache.get(selection['revision'])
                            if pages is None or selection['page'] > len(pages):
                                raise ValueError('Selection refers to an unavailable preview')
                            saved = session.set_selection(directory, selection)
                        elif route.endswith('/restore'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'revision'}:
                                raise ValueError('Restore requires base_revision and revision')
                            saved = session.restore(directory, payload['base_revision'], payload['revision'])
                        elif route.endswith('/replace-picture'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'image'} or not isinstance(payload['image'], str):
                                raise ValueError('Picture replacement requires revision, path and image')
                            image_data = base64.b64decode(payload['image'], validate=True)
                            saved = session.replace_picture(directory, payload['base_revision'], payload['path'], image_data)
                        elif route.endswith('/reply-comment'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'parent_id', 'text', 'author'}:
                                raise ValueError('Reply requires revision, parent ID, text and author')
                            saved = session.reply_comment(directory, payload['base_revision'], payload['parent_id'], payload['text'], payload['author'])
                        elif route.endswith('/resolve-comment'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'comment_id', 'resolved'}:
                                raise ValueError('Comment state requires revision, comment ID and resolved')
                            saved = session.resolve_comment(directory, payload['base_revision'], payload['comment_id'], payload['resolved'])
                        elif route.endswith('/add-comment'):
                            if not isinstance(payload, dict) or set(payload) not in ({'base_revision', 'path', 'text', 'author'}, {'base_revision', 'path', 'text', 'author', 'anchor'}):
                                raise ValueError('Comment requires revision, path, text and author')
                            saved = session.add_comment(directory, payload['base_revision'], payload['path'], payload['text'], payload['author'], payload.get('anchor'))
                        elif route.endswith('/tracked-resolve'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'part', 'ids', 'accept'}:
                                raise ValueError('Resolution requires revision, part, IDs and decision')
                            saved = session.resolve_tracked_runs(directory, payload['base_revision'], payload['part'], payload['ids'], payload['accept'])
                        elif route.endswith('/track-insert-text'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'anchor', 'text', 'position', 'author'}:
                                raise ValueError('Tracked insertion requires revision, path, anchor, text, position and author')
                            saved = session.track_insert_text(directory, payload['base_revision'], payload['path'], payload['anchor'], payload['text'], payload['position'], payload['author'])
                        elif route.endswith('/track-replace-text'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'find', 'replacement', 'author'}:
                                raise ValueError('Tracked replacement requires revision, path, find, replacement and author')
                            saved = session.track_replace_text(directory, payload['base_revision'], payload['path'], payload['find'], payload['replacement'], payload['author'])
                        elif route.endswith('/replace-text'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'find', 'replacement'}:
                                raise ValueError('Text replacement requires revision, path, find and replacement')
                            saved = session.replace_text(directory, payload['base_revision'], payload['path'], payload['find'], payload['replacement'])
                        elif route.endswith('/element'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path'}:
                                raise ValueError('Element requires base_revision and path')
                            saved = session.edit_target(directory, payload['base_revision'], payload['path'])
                        elif route.endswith('/sheets'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision'}:
                                raise ValueError('Sheet listing requires base_revision')
                            saved = session.sheet_names(directory, payload['base_revision'])
                        elif route.endswith('/grid'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell_range'}:
                                raise ValueError('Grid requires base_revision, sheet and cell_range')
                            saved = session.read_grid(directory, payload['base_revision'], payload['sheet'], payload['cell_range'])
                        elif route.endswith('/grid-merge'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell_range', 'merge'}: raise ValueError('Merge requires revision, sheet, range and operation')
                            saved = session.merge_cells(directory, payload['base_revision'], payload['sheet'], payload['cell_range'], payload['merge'])
                        elif route.endswith('/grid-freeze'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell'}: raise ValueError('Freeze requires revision, sheet and cell')
                            saved = session.freeze_panes(directory, payload['base_revision'], payload['sheet'], payload['cell'])
                        elif route.endswith('/grid-resize'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell_range', 'target_range', 'column_width', 'row_height'}:
                                raise ValueError('Grid sizing requires revision, sheet, ranges, width and height')
                            saved = session.resize_grid(directory, payload['base_revision'], payload['sheet'], payload['cell_range'], payload['target_range'], payload['column_width'], payload['row_height'])
                        elif route.endswith('/grid-format'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell_range', 'style_range', 'properties'}:
                                raise ValueError('Grid formatting requires revision, sheet, ranges and properties')
                            saved = session.format_grid(directory, payload['base_revision'], payload['sheet'], payload['cell_range'], payload['style_range'], payload['properties'])
                        elif route.endswith('/grid-edit'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'sheet', 'cell_range', 'changes'}:
                                raise ValueError('Grid edit requires base_revision, sheet, cell_range and changes')
                            saved = session.edit_grid(directory, payload['base_revision'], payload['sheet'], payload['cell_range'], payload['changes'])
                        else:
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'path', 'mode', 'value'}:
                                raise ValueError('Edit requires base_revision, path, mode and value')
                            saved = session.edit(directory, payload['base_revision'], payload['path'], payload['mode'], payload['value'])
                    self.send(200, json.dumps(saved, default=str).encode(), 'application/json')
                except (ValueError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    self.send(400, json.dumps({'error': str(exc)}).encode(), 'application/json')

            def do_GET(self):
                expected_host = f'127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}'
                if self.headers.get('Host') != expected_host:
                    self.send(403, b'Forbidden', 'text/plain; charset=utf-8'); return
                path = urlsplit(self.path).path
                prefix = '/' + token + '/'
                if not path.startswith(prefix):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                route = path[len(prefix):]
                if route == '':
                    self.send(200, PAGE.replace('NONCE', nonce).encode(), 'text/html; charset=utf-8'); return
                changes = re.fullmatch(r'comparison/(\d{1,6})/(\d{1,6})/changes', route)
                history = re.fullmatch(r'revision/(\d{1,6})/state', route)
                comparison = re.fullmatch(r'comparison/(\d{1,6})/state', route)
                page_match = re.fullmatch(r'page/(\d{1,6})/(\d{1,6})', route)
                if changes:
                    try:
                        with lock:
                            state = session.info(directory)
                            before = session.revision_file(state, int(changes.group(1)))
                            after = session.revision_file(state, int(changes.group(2)))
                        data = review.compare(before, after)
                        self.send(200, json.dumps(data, ensure_ascii=False).encode(), 'application/json'); return
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        self.send(400, json.dumps({'error': str(exc)}).encode(), 'application/json'); return
                if route == 'state' or history or comparison or page_match:
                    try:
                        with lock:
                            state = session.info(directory)
                            if history:
                                rev = int(history.group(1))
                            elif comparison:
                                rev = int(comparison.group(1))
                            elif page_match:
                                rev = int(page_match.group(1))
                            else:
                                rev = state['latest_revision']
                            if rev > state['latest_revision']:
                                self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                            pages = pages_for(state, rev)
                            if page_match:
                                index = int(page_match.group(2))
                                if index >= len(pages):
                                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                                self.send(200, Path(pages[index]).read_bytes(), 'image/png'); return
                            data = {'revision': rev, 'pages': len(pages), 'format': state['format'],
                                    'revisions': [item['revision'] for item in state['revisions']], 'render_advisory': cache[rev]['render_advisory'], 'snapshot_sha256': cache[rev]['snapshot_sha256']}
                            if comparison:
                                latest = state['latest_revision']
                                latest_pages = pages_for(state, latest)
                                data.update(latest_revision=latest, latest_pages=len(latest_pages), latest_render_advisory=cache[latest]['render_advisory'], latest_snapshot_sha256=cache[latest]['snapshot_sha256'])
                        self.send(200, json.dumps(data).encode(), 'application/json'); return
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        self.send(500, json.dumps({'error': str(exc)}).encode(), 'application/json'); return
                self.send(404, b'Not found', 'text/plain; charset=utf-8')

        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        try:
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/{token}/'}), flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
