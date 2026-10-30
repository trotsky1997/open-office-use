"""Local browser preview and visual selection for a versioned office session."""
import json
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
import selection_candidates
import session

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
#comparison-text,#comparison-parts{max-height:18rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:.75rem;border-radius:.3rem}
input{width:4.5rem}button,select,input,textarea{font:inherit}button{cursor:pointer}form p{flex-basis:100%}.grid-scroll{overflow:auto;max-height:32rem;flex-basis:100%}input[readonly]{background:#f4f6f8}table{border-collapse:collapse}th,td{border:1px solid #ccd3da;padding:.15rem}td input{width:10rem}
.comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.comparison section{min-width:0}.comparison h2{font-size:1rem;margin:.5rem 0}.comparison img{width:100%}
@media(max-width:700px){.comparison{grid-template-columns:1fr}}
#compare-sheet{width:min(14rem,70vw)}#compare-range{width:8rem}#cell-comparison-output td{max-width:24rem;overflow-wrap:anywhere}
#word-find,#word-replacement{width:min(14rem,65vw)}#edit-path{width:min(28rem,80vw)}#edit-value{width:min(40rem,90vw);min-height:6rem}#edit-form label{display:flex;gap:.4rem;align-items:center}

</style></head><body><header><h1>Office session preview</h1><p id="status" role="status">Loading…</p><p id="selection" role="status">Drag on a page to save a selection for the agent.</p></header>
<details><summary>Restore a previous revision</summary><form id="restore-form">
<label for="restore-revision">Revision</label> <select id="restore-revision" required></select>
<button type="button" id="preview-revision">Preview selected revision</button><button type="button" id="compare-revision">Compare with latest</button><button type="button" id="show-latest">Show latest</button><button type="submit">Restore as new revision</button><p id="restore-status" role="status"></p></form></details>
<details id="candidate-panel"><summary>Find selected elements</summary>
<p>Matches use text and may be incomplete or ambiguous. Verify the target before editing.</p>
<button type="button" id="candidate-search" disabled>Find candidates</button><p id="candidate-status" role="status"></p><ul id="candidate-list"></ul></details>
<details id="edit-panel"><summary>Edit an element</summary><form id="edit-form">
<label>Element path <input id="edit-path" required maxlength="512" placeholder="/body/p[1]"></label>
<button type="button" id="edit-load">Load element</button>
<label>Kind <select id="edit-mode" disabled></select></label>
<label>Content <textarea id="edit-value" maxlength="4000" disabled></textarea></label>
<button type="submit" id="edit-save" disabled>Save as new revision</button>
<fieldset id="word-replace-panel" hidden><legend>Replace text while retaining run formatting</legend>
<label>Find text <input id="word-find" maxlength="4000"></label>
<label>Replace with <input id="word-replacement" maxlength="4000"></label>
<button type="button" id="word-replace">Replace once</button>
<p>Requires one exact match in a simple body or table paragraph. Replacement takes the first matched run's formatting; fields, links and annotations require another workflow.</p></fieldset>
<p>Replacing text can change run formatting. A cell value replaces its formula; numeric values may be converted by OfficeCLI. Use formula mode for expressions beginning with =.</p>
<p id="edit-status" role="status"></p></form></details>
<details id="grid-panel" hidden><summary>Edit worksheet range</summary><form id="grid-form">
<button type="button" id="grid-sheets">List sheets</button><label for="grid-sheet">Sheet</label> <select id="grid-sheet" required></select>
<label>Range <input id="grid-range" required value="A1:D10" maxlength="32"></label><button type="button" id="grid-load">Load cells</button>
<div id="grid-output" class="grid-scroll"></div><button type="submit" id="grid-save" disabled>Save changed cells</button>
<fieldset><legend>Format a range</legend>
<label>Format range <input id="grid-style-range" maxlength="32"></label>
<label>Bold <select id="grid-bold"><option value="">Keep</option><option value="true">On</option><option value="false">Off</option></select></label>
<label><input id="grid-fill-enabled" type="checkbox"> Set fill</label> <input id="grid-fill" type="color" value="#ffcc00" aria-label="Fill color">
<label>Number format <input id="grid-numberformat" maxlength="120" placeholder="Keep"></label>
<button type="button" id="grid-format" disabled>Apply formatting</button></fieldset>
<p>Formatting applies to the loaded range or a smaller range. Existing patterned fills keep their pattern; theme colors are not previewed in the grid.</p>
<p>Up to 200 cells. Paste tab-separated cells starting at the focused cell. Enter formulas beginning with =. Numeric and date values can be converted by OfficeCLI; declared array, data-table and shared formula ranges are read-only.</p>
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
<section id="cell-comparison" hidden><h2>Worksheet changes</h2>
<p>Compare values, formulas and direct formatting. Cached formula results may be stale; conditional formatting and theme changes need separate review.</p>
<form id="cell-comparison-form"><label>Worksheet <input id="compare-sheet" required maxlength="31"></label>
<label>Cell range <input id="compare-range" required value="A1:D10" maxlength="32"></label>
<button id="compare-cells" type="submit">Compare cells</button></form>
<p id="cell-comparison-status" role="status"></p><div id="cell-comparison-output" class="grid-scroll"></div></section></details>
<main id="pages" aria-label="Document pages"></main>
<script nonce="NONCE">
let current = -1, displayed = -1, pinned = null, viewKey = "", busy = false, loaded = null, comparing = false, comparedLatest = -1;
let savedSelection = null, selectionEpoch = 0, gridLoaded = null, cellComparisonEpoch = 0, editBaseline = null, editBusy = false, gridBusy = false;
function clearCandidates() {
 savedSelection=null; selectionEpoch++; document.getElementById('candidate-search').disabled=true;
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
  const response=await fetch('candidates', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({selection:requested})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Search failed');
  if (epoch !== selectionEpoch || pinned !== null || current !== result.revision) return;
  const list=document.getElementById('candidate-list'); list.replaceChildren();
  for (const item of result.candidates) {
   const row=document.createElement('li'); const label=document.createElement('span');
   label.textContent=`${item.type || 'element'} · ${item.path} · ${String(item.text || '').slice(0,200)}`;
   const use=document.createElement('button'); use.type='button'; use.textContent=`Use ${item.path}`;
   use.addEventListener('click', () => {
    if (epoch !== selectionEpoch || current !== result.revision || pinned !== null) return;
    document.getElementById('edit-panel').open=true; loadElement(item.path);
   });
   row.append(label, document.createTextNode(' '), use); list.appendChild(row);
  }
  document.getElementById('candidate-status').textContent = result.candidates.length ? `${result.candidates.length} candidate(s). Verify the target; matches may be incomplete.` : 'No candidates found. Try a different selection or enter a path.';
 } catch (error) { if (epoch === selectionEpoch) document.getElementById('candidate-status').textContent=`Candidate error: ${error.message}`; }
 finally { if (epoch === selectionEpoch && pinned === null && savedSelection) button.disabled=false; }
});
function gridDirty() {
 return [...document.querySelectorAll('#grid-output input')].some(input=>input.value!==input.dataset.baseline);
}
function elementDirty() {
 return editBaseline !== null && (document.getElementById('edit-value').value !== editBaseline.value || document.getElementById('edit-mode').value !== editBaseline.mode);
}
window.addEventListener('beforeunload', event => {
 if (gridDirty() || elementDirty()) { event.preventDefault(); event.returnValue=''; }
});
function invalidateGrid(message) {
 gridLoaded=null; document.getElementById('grid-save').disabled=true; document.getElementById('grid-format').disabled=true;
 document.querySelectorAll('#grid-output input').forEach(input=>input.readOnly=true);
 if (message) document.getElementById('grid-status').textContent=message;
}
for (const id of ['grid-sheet','grid-range']) document.getElementById(id).addEventListener('change', () => invalidateGrid('Reload the range before saving.'));
document.getElementById('grid-sheets').addEventListener('click', async () => {
 if (gridBusy) return; gridBusy=true;
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
document.getElementById('grid-load').addEventListener('click', async () => {
 if (gridBusy) return;
 if (gridDirty() && !window.confirm('Discard unsaved cell edits and load another range?')) return;
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
    const td=document.createElement('td'), input=document.createElement('input'); input.type='text'; input.maxLength=4000;
    const formula=cell.formula, value=typeof formula==='string' ? formula : (formula && typeof formula==='object' ? (formula.text || '[complex formula]') : (cell.value == null ? '' : String(cell.value)));
    input.value=value; input.dataset.baseline=value; input.dataset.cell=cell.cell; input.dataset.editable=String(cell.editable);
    input.readOnly=!cell.editable; input.setAttribute('aria-label', `${sheet} ${cell.cell}`);
    if (cell.style.bold) input.style.fontWeight='bold';
    if (/^[0-9A-Fa-f]{6}$/.test(cell.style.fill_rgb || '')) {
     input.style.backgroundColor='#'+cell.style.fill_rgb;
     const rgb=cell.style.fill_rgb.match(/../g).map(part=>parseInt(part,16));
     input.style.color=(rgb[0]*299+rgb[1]*587+rgb[2]*114)/1000 < 140 ? 'white' : 'black';
    }
    input.title=`Number format: ${cell.style.number_format}`;
    if (typeof formula==='string') input.title+=`; cached result: ${cell.value == null ? 'unknown' : cell.value}`;
    if (!cell.editable) input.title='Protected formula range: use a supported workflow';
    td.appendChild(input); tr.appendChild(td);
   }
   body.appendChild(tr);
  }
  table.appendChild(body); document.getElementById('grid-output').replaceChildren(table); gridLoaded={revision,sheet,cell_range};
  document.getElementById('grid-save').disabled=false; document.getElementById('grid-format').disabled=false; document.getElementById('grid-style-range').value=cell_range; document.getElementById('grid-status').textContent=`Loaded ${sheet} ${cell_range} at revision ${revision}.`;
 } catch(error) { document.getElementById('grid-status').textContent=`Grid error: ${error.message}`; }
 finally { gridBusy=false; button.disabled=pinned !== null; }
});
function parseGridPaste(text) {
 const rows=[], row=[]; let field='', quoted=false, closed=false, atEnd=false;
 for (let i=0; i<text.length; i++) {
  const char=text[i]; atEnd=false;
  if (quoted) {
   if (char==='"') { if (text[i+1]==='"') { field+='"'; i++; } else { quoted=false; closed=true; } }
   else if (char==='\\r' || char==='\\n') throw new Error('Multiline cell text is not supported.');
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
   const input=body.rows[firstRow+r]?.cells[firstCol+c+1]?.querySelector('input'), value=pasted[r][c];
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
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output input')];
 const changes=inputs.filter(input=>input.dataset.editable==='true' && input.value!==input.dataset.baseline).map(input=>({cell:input.dataset.cell,value:input.value}));
 if (!changes.length) { document.getElementById('grid-status').textContent='No changed cells.'; return; }
 const body=JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:loaded.cell_range,changes});
 if (new TextEncoder().encode(body).length > 20000) { document.getElementById('grid-status').textContent='Changes exceed 20 KB; save fewer cells at a time.'; return; }
 gridBusy=true; const button=document.getElementById('grid-save'); button.disabled=true; document.getElementById('grid-format').disabled=true; inputs.forEach(input=>input.readOnly=true);
 try {
  const response=await fetch('grid-edit', {method:'POST',headers:{'Content-Type':'application/json'},body});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Save failed');
  inputs.forEach(input=>input.dataset.baseline=input.value);
  invalidateGrid(`Saved ${changes.length} cell(s) as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded === loaded && current === loaded.revision && pinned === null) { inputs.forEach(input=>input.readOnly=input.dataset.editable!=='true'); button.disabled=false; document.getElementById('grid-format').disabled=false; }
 } finally { gridBusy=false; }
});
document.getElementById('grid-format').addEventListener('click', async () => {
 if (gridBusy) return;
 if (!gridLoaded || gridLoaded.revision !== current || pinned !== null) { invalidateGrid('Version changed; reload the range.'); return; }
 const loaded=gridLoaded, inputs=[...document.querySelectorAll('#grid-output input')];
 if (inputs.some(input=>input.value!==input.dataset.baseline)) { document.getElementById('grid-status').textContent='Save or copy pending cell edits before formatting.'; return; }
 const properties={}, bold=document.getElementById('grid-bold').value, numberformat=document.getElementById('grid-numberformat').value;
 if (bold) properties.bold=bold==='true';
 if (document.getElementById('grid-fill-enabled').checked) properties.fill=document.getElementById('grid-fill').value.slice(1);
 if (numberformat) properties.numberformat=numberformat;
 if (!Object.keys(properties).length) { document.getElementById('grid-status').textContent='Choose a formatting change.'; return; }
 gridBusy=true; const button=document.getElementById('grid-format'); button.disabled=true; document.getElementById('grid-save').disabled=true; inputs.forEach(input=>input.readOnly=true);
 try {
  const response=await fetch('grid-format', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_revision:loaded.revision,sheet:loaded.sheet,cell_range:loaded.cell_range,style_range:document.getElementById('grid-style-range').value,properties})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Formatting failed');
  invalidateGrid(`Formatting saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('grid-status').textContent=`Grid error: ${error.message}`;
  if (gridLoaded === loaded && current === loaded.revision && pinned === null) { inputs.forEach(input=>input.readOnly=input.dataset.editable!=='true'); button.disabled=false; document.getElementById('grid-save').disabled=false; }
 } finally { gridBusy=false; }
});
function invalidateEdit(message) {
 loaded=null; document.getElementById('edit-save').disabled=true; document.getElementById('word-replace-panel').hidden=true;
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
  const mode=document.getElementById('edit-mode'); const kinds=target.format==='xlsx' ? ['value','formula'] : ['text'];
  mode.replaceChildren(...kinds.map(kind=>{const option=document.createElement('option');option.value=kind;option.textContent=kind;return option;}));
  mode.value=target.mode; mode.disabled=false;
  const value=document.getElementById('edit-value'); value.disabled=false; value.readOnly=false; value.value=target.value;
  editBaseline={value:value.value,mode:mode.value};
  document.getElementById('edit-save').disabled=false;
  document.getElementById('word-replace-panel').hidden=!target.replace_text_path_supported;
  document.getElementById('edit-status').textContent=`Loaded ${target.type} at revision ${target.revision}. Review content before saving.`;
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
  editBaseline=snapshot; invalidateEdit(`Saved as revision ${result.revision}.`); await refresh();
 } catch (error) {
  document.getElementById('edit-status').textContent=`Edit error: ${error.message}`;
  if (loaded === target && current === target.revision && pinned === null) { value.readOnly=false; mode.disabled=false; button.disabled=false; }
 }
 finally { editBusy=false; path.disabled=pinned !== null; document.getElementById('edit-load').disabled=pinned !== null; }
});
document.getElementById('word-replace').addEventListener('click', async () => {
 if (editBusy) return;
 if (!loaded || loaded.format!=='docx' || loaded.type!=='paragraph' || pinned!==null || loaded.revision!==current) { invalidateEdit('Version changed; load the paragraph again.'); return; }
 if (elementDirty()) { document.getElementById('edit-status').textContent='Save or copy pending element edits before replacing text.'; return; }
 const target=loaded, path=document.getElementById('edit-path'), mode=document.getElementById('edit-mode'), value=document.getElementById('edit-value');
 const find=document.getElementById('word-find'), replacement=document.getElementById('word-replacement'), button=document.getElementById('word-replace');
 editBusy=true; button.disabled=true; find.disabled=true; replacement.disabled=true; document.getElementById('edit-save').disabled=true; document.getElementById('edit-load').disabled=true; path.disabled=true; mode.disabled=true; value.readOnly=true;
 try {
  const response=await fetch('replace-text', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({base_revision:target.revision,path:target.path,find:find.value,replacement:replacement.value})});
  const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Replacement failed');
  invalidateEdit(`Replacement saved as revision ${result.revision}.`); await refresh();
 } catch(error) {
  document.getElementById('edit-status').textContent=`Replacement error: ${error.message}`;
  if (loaded===target && current===target.revision && pinned===null) { value.readOnly=false; mode.disabled=false; document.getElementById('edit-save').disabled=false; }
 } finally { editBusy=false; button.disabled=false; find.disabled=false; replacement.disabled=false; path.disabled=pinned!==null; document.getElementById('edit-load').disabled=pinned!==null; }
});
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
function display(state, live) {
 document.getElementById('comparison-details').hidden=true;
 const key = `${state.revision}:${live}`;
 if (key === viewKey) return;
 const fragment = document.createDocumentFragment();
 for (let i=0; i<state.pages; i++) {
  const image=document.createElement('img'); image.src=`page/${state.revision}/${i}`;
  image.alt=`Revision ${state.revision}, page ${i+1}`; image.loading='lazy'; image.draggable=false;
  fragment.appendChild(selectable(image, i+1, state.revision, live));
 }
 document.getElementById('pages').replaceChildren(fragment); displayed=state.revision; viewKey=key; clearCandidates();
 document.getElementById('selection').textContent = live ? 'Drag on a page to save a selection for the agent.' : 'Selections are available on the latest revision.';
 document.querySelectorAll('#selection-form input, #selection-form button, #edit-path, #edit-load, #grid-sheets, #grid-sheet, #grid-range, #grid-load').forEach(element => element.disabled=!live);
 if (!live) invalidateGrid('Return to the latest revision to edit cells.');
 if (!live) invalidateEdit('Return to the latest revision to edit.');
}
function displayComparison(state) {
 const key=`compare:${state.revision}:${state.latest_revision}`;
 if (key === viewKey) return;
 const grid=document.createElement('div'); grid.className='comparison';
 for (const [revision, count, label] of [[state.revision,state.pages,'Selected'], [state.latest_revision,state.latest_pages,'Latest']]) {
  const section=document.createElement('section'); const title=document.createElement('h2');
  title.textContent=`${label} · revision ${revision} · ${count} page(s)`; section.appendChild(title);
  for (let i=0; i<count; i++) {
   const image=document.createElement('img'); image.src=`page/${revision}/${i}`; image.loading='lazy';
   image.alt=`${label} revision ${revision}, page ${i+1}`; section.appendChild(image);
  }
  grid.appendChild(section);
 }
 document.getElementById('pages').replaceChildren(grid); displayed=state.revision; viewKey=key; clearCandidates();
 document.getElementById('comparison-details').hidden=false;
 document.getElementById('changes-status').textContent='';
 document.getElementById('comparison-text').textContent=''; document.getElementById('comparison-parts').textContent='';
 cellComparisonEpoch++; document.getElementById('cell-comparison-output').replaceChildren(); document.getElementById('cell-comparison-status').textContent='';
 document.getElementById('selection').textContent='Selections are available on the latest revision.';
 document.querySelectorAll('#selection-form input, #selection-form button, #edit-path, #edit-load, #grid-sheets, #grid-sheet, #grid-range, #grid-load').forEach(element => element.disabled=true);
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
  document.getElementById('cell-comparison-status').textContent=`Revision ${before} → ${after}: ${result.changed_count} changed cell(s). ${result.truncated ? 'Showing the first 500 cells.' : ''}`;
 } catch(error) { if (epoch === cellComparisonEpoch && comparing && pinned === before && comparedLatest === after) document.getElementById('cell-comparison-status').textContent=`Cell comparison error: ${error.message}`; }
 finally { button.disabled=false; }
});
async function loadComparison(revision) {
 const response=await fetch(`comparison/${revision}/state`, {cache:'no-store'}); const state=await response.json();
 if (!response.ok) throw new Error(state.error || 'Comparison unavailable');
 if (!comparing || pinned !== revision || state.latest_revision < current) return;
 displayComparison(state); comparedLatest=state.latest_revision;
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
  document.getElementById('grid-panel').hidden=state.format !== 'xlsx'; document.getElementById('cell-comparison').hidden=state.format !== 'xlsx';
  if (state.revision !== current) {
   if (gridLoaded) invalidateGrid('Version changed; copy unsaved edits and reload the range.');
   if (loaded) invalidateEdit('Version changed; load the element again.');
   const select=document.getElementById('restore-revision'); const previous=select.value;
   select.replaceChildren(...state.revisions.map(revision => {const option=document.createElement('option'); option.value=revision; option.textContent=`Revision ${revision}`; return option;}));
   if (state.revisions.some(revision => String(revision) === previous)) select.value=previous;
  }
  current=state.revision;
  if (comparing && pinned !== null) {
   if (comparedLatest !== current) await loadComparison(pinned);
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
                cache[revision] = preview(source, root / f'rev-{revision}')
                if len(cache) > 4:
                    old, _ = cache.popitem(last=False)
                    shutil.rmtree(root / f'rev-{old}', ignore_errors=True)
            cache.move_to_end(revision)
            return cache[revision]

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
                self.send_header('Content-Security-Policy', f"default-src 'none'; img-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                port = cast(ThreadingHTTPServer, self.server).server_port
                host = f'127.0.0.1:{port}'
                if self.headers.get('Host') != host or self.headers.get('Origin') != 'http://' + host:
                    self.send(403, b'Forbidden', 'text/plain; charset=utf-8'); return
                route = urlsplit(self.path).path
                if route not in ('/' + token + '/selection', '/' + token + '/restore', '/' + token + '/element', '/' + token + '/edit', '/' + token + '/candidates', '/' + token + '/sheets', '/' + token + '/grid', '/' + token + '/grid-edit', '/' + token + '/grid-format', '/' + token + '/cell-comparison', '/' + token + '/replace-text'):
                    self.send(404, b'Not found', 'text/plain; charset=utf-8'); return
                length = self.headers.get('Content-Length', '')
                if self.headers.get('Content-Type') != 'application/json' or not length.isdecimal() or len(length) > 5 or not 0 < int(length) <= 20000:
                    self.send(400, b'Invalid request', 'text/plain; charset=utf-8'); return
                try:
                    payload = json.loads(self.rfile.read(int(length)))
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
                        if not isinstance(payload, dict) or set(payload) != {'selection'}:
                            raise ValueError('Candidates require a saved selection')
                        expected = session.validate_selection(payload['selection'])
                        with lock:
                            selected = session.get_selection(directory)
                            if selected['stale'] or any(selected[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                        if render is None:
                            raise RuntimeError('Candidate rendering is unavailable')
                        result = selection_candidates.candidates(directory, render)
                        with lock:
                            selected = session.get_selection(directory)
                            if selected['stale'] or result['stale'] or any(selected[key] != expected[key] for key in expected) or any(result[key] != expected[key] for key in expected):
                                raise ValueError('Selection changed; select the current page again')
                        self.send(200, json.dumps(result).encode(), 'application/json'); return
                    with lock:
                        if route.endswith('/selection'):
                            selection = session.validate_selection(payload)
                            pages = cache.get(selection['revision'])
                            if pages is None or selection['page'] > len(pages):
                                raise ValueError('Selection refers to an unavailable preview')
                            saved = session.set_selection(directory, selection)
                        elif route.endswith('/restore'):
                            if not isinstance(payload, dict) or set(payload) != {'base_revision', 'revision'}:
                                raise ValueError('Restore requires base_revision and revision')
                            saved = session.restore(directory, payload['base_revision'], payload['revision'])
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
                                    'revisions': [item['revision'] for item in state['revisions']]}
                            if comparison:
                                latest = state['latest_revision']
                                data.update(latest_revision=latest, latest_pages=len(pages_for(state, latest)))
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
