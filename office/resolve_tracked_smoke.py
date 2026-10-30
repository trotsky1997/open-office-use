"""Exercise atomic acceptance and rejection of selected Word run revisions."""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import officecli_backend
import session
import word

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp); source = root / 'source.docx'; draft = root / 'draft'; doc = Document()
    p = doc.add_paragraph('Start '); p.add_run('old').bold = True; p.add_run(' text').italic = True; p.add_run(' end'); doc.save(source)
    session.start(draft, source=source); changed = session.track_replace_text(draft, 0, '/body/p[1]', 'old text', 'new', 'Reviewer')
    changed_file = Path(changed['file']); records = session.tracked_changes(draft, 1)['records']; ids = [item['id'] for item in records]
    for accept, expected in ((True, 'Start new end'), (False, 'Start old text end')):
        isolated = root / ('accept' if accept else 'reject'); session.start(isolated, source=changed_file)
        for bad_ids in ([ids[0], '999999999999999999'], [ids[0], ids[0]]):
            try: session.resolve_tracked_runs(isolated, 0, 'word/document.xml', bad_ids, accept)
            except ValueError: pass
            else: raise AssertionError('invalid revision selection accepted')
            assert session.info(isolated)['latest_revision'] == 0
        result = session.resolve_tracked_runs(isolated, 0, 'word/document.xml', ids, accept)
        paragraph = Document(result['file']).paragraphs[0]
        assert paragraph.text == expected and paragraph.runs[1].bold is True
        if not accept: assert paragraph.runs[2].italic is True
        assert session.tracked_changes(isolated, 1)['records_scanned'] == 0
        with zipfile.ZipFile(changed_file) as before, zipfile.ZipFile(result['file']) as after:
            assert all(before.read(name) == after.read(name) for name in before.namelist() if name != 'word/document.xml')
        audit = officecli_backend.audit(result['file']); assert audit['validation']['result']['success'], audit
    cli_draft = root / 'cli'; session.start(cli_draft, source=changed_file); cli = Path(__file__).with_name('open_office_use.py')
    out = subprocess.run([sys.executable, str(cli), 'session', 'resolve-tracked-runs', str(cli_draft), '--base', '0', '--part', 'word/document.xml', '--id', ids[0], '--id', ids[1], '--decision', 'accept'], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)['revision'] == 1
    marked = root / 'paragraph-mark.docx'; mark_doc = Document(); paragraph = mark_doc.add_paragraph('text')
    props = paragraph._p.get_or_add_pPr(); run_props = OxmlElement('w:rPr'); marker = OxmlElement('w:del'); marker.set(qn('w:id'), '3'); run_props.append(marker); props.append(run_props); mark_doc.save(marked)
    marker_draft = root / 'marker'; session.start(marker_draft, source=marked)
    try: session.resolve_tracked_runs(marker_draft, 0, 'word/document.xml', ['3'], True)
    except ValueError: pass
    else: raise AssertionError('paragraph mark revision accepted as a run')
    assert session.info(marker_draft)['latest_revision'] == 0
    header_file = root / 'header.docx'; header_doc = Document(); header = header_doc.sections[0].header.paragraphs[0]
    insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), '10'); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'header text'; run.append(text); insertion.append(run); header._p.append(insertion); header_doc.save(header_file)
    header_draft = root / 'header'; session.start(header_draft, source=header_file)
    header_record = session.tracked_changes(header_draft, 0)['records'][0]
    header_result = session.resolve_tracked_runs(header_draft, 0, header_record['part'], ['10'], True)
    assert Document(header_result['file']).sections[0].header.paragraphs[0].text == 'header text'
    move_file = root / 'move.docx'; move_doc = Document(); move_paragraph = move_doc.add_paragraph()
    marker = OxmlElement('w:moveFromRangeStart'); marker.set(qn('w:id'), '2'); move_paragraph._p.addprevious(marker)
    insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), '3'); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'text'; run.append(text); insertion.append(run); move_paragraph._p.append(insertion); move_doc.save(move_file)
    move_draft = root / 'move'; session.start(move_draft, source=move_file)
    try: session.resolve_tracked_runs(move_draft, 0, 'word/document.xml', ['3'], True)
    except ValueError as exc: assert 'range' in str(exc).lower()
    else: raise AssertionError('tracked move range was accepted')
    assert session.info(move_draft)['latest_revision'] == 0
    bounded_file = root / 'bounded-move.docx'; bounded_doc = Document(); outside = bounded_doc.add_paragraph()
    insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), '11'); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'outside'; run.append(text); insertion.append(run); outside._p.append(insertion)
    moved = bounded_doc.add_paragraph(); start = OxmlElement('w:moveFromRangeStart'); start.set(qn('w:id'), '20'); moved._p.addprevious(start)
    insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), '12'); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'inside'; run.append(text); insertion.append(run); moved._p.append(insertion)
    end = OxmlElement('w:moveFromRangeEnd'); end.set(qn('w:id'), '20'); moved._p.addnext(end); bounded_doc.save(bounded_file)
    bounded_draft = root / 'bounded-move'; session.start(bounded_draft, source=bounded_file)
    try: session.resolve_tracked_runs(bounded_draft, 0, 'word/document.xml', ['12'], True)
    except ValueError as exc: assert 'inside' in str(exc)
    else: raise AssertionError('revision within a move range was accepted')
    resolved = session.resolve_tracked_runs(bounded_draft, 0, 'word/document.xml', ['11'], True)
    assert Document(resolved['file']).paragraphs[0].text == 'outside'
    remaining = session.tracked_changes(bounded_draft, 1)
    assert remaining['counts']['moveFromRangeStart'] == 1 and remaining['counts']['moveFromRangeEnd'] == 1 and remaining['counts']['ins'] == 1
    conflict_file = root / 'conflict.docx'; conflict_doc = Document(); paragraph = conflict_doc.add_paragraph()
    start = etree.Element(word.W14 + 'customXmlConflictInsRangeStart'); start.set(word.W + 'id', '30'); paragraph._p.append(start)
    insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), '31'); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'conflict'; run.append(text); insertion.append(run); paragraph._p.append(insertion)
    end = etree.Element(word.W14 + 'customXmlConflictInsRangeEnd'); end.set(word.W + 'id', '30'); paragraph._p.append(end); conflict_doc.save(conflict_file)
    conflict_draft = root / 'conflict'; session.start(conflict_draft, source=conflict_file)
    assert session.tracked_changes(conflict_draft, 0)['counts']['customXmlConflictInsRangeStart'] == 1
    try: session.resolve_tracked_runs(conflict_draft, 0, 'word/document.xml', ['31'], True)
    except ValueError as exc: assert 'inside' in str(exc)
    else: raise AssertionError('revision inside a conflict range was accepted')
    notes_file = root / 'notes.docx'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(notes_file, 'w') as after:
        for entry in before.infolist():
            data = before.read(entry)
            if entry.filename == 'word/_rels/document.xml.rels':
                rels = etree.fromstring(data); rel = etree.SubElement(rels, word.REL + 'Relationship'); rel.set('Id', 'rIdFootnoteTest'); rel.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes'); rel.set('Target', 'footnotes.xml'); data = etree.tostring(rels)
            elif entry.filename == '[Content_Types].xml':
                types = etree.fromstring(data); item = etree.SubElement(types, '{http://schemas.openxmlformats.org/package/2006/content-types}Override'); item.set('PartName', '/word/footnotes.xml'); item.set('ContentType', 'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'); data = etree.tostring(types)
            after.writestr(entry, data)
        root_notes = etree.Element(word.W + 'footnotes')
        for note_id, revision_id, inside in ((1, 40, True), (2, 41, False)):
            note = etree.SubElement(root_notes, word.W + 'footnote'); note.set(word.W + 'id', str(note_id))
            start = etree.SubElement(note, word.W + 'moveFromRangeStart'); start.set(word.W + 'id', '8')
            paragraph = etree.SubElement(note, word.W + 'p')
            end = etree.SubElement(note, word.W + 'moveFromRangeEnd'); end.set(word.W + 'id', '8')
            target = paragraph if inside else etree.SubElement(note, word.W + 'p')
            insertion = etree.SubElement(target, word.W + 'ins'); insertion.set(word.W + 'id', str(revision_id)); run = etree.SubElement(insertion, word.W + 'r'); text = etree.SubElement(run, word.W + 't'); text.text = 'note'
        after.writestr('word/footnotes.xml', etree.tostring(root_notes))
    notes_draft = root / 'notes'; session.start(notes_draft, source=notes_file)
    try: session.resolve_tracked_runs(notes_draft, 0, 'word/footnotes.xml', ['40'], True)
    except ValueError as exc: assert 'inside' in str(exc)
    else: raise AssertionError('revision inside footnote move range was accepted')
    assert session.resolve_tracked_runs(notes_draft, 0, 'word/footnotes.xml', ['41'], True)['revision'] == 1
    duplicate_file = root / 'duplicate.docx'; duplicate_doc = Document(); p = duplicate_doc.add_paragraph()
    for raw_id in ('3', '0003'):
        insertion = OxmlElement('w:ins'); insertion.set(qn('w:id'), raw_id); run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'x'; run.append(text); insertion.append(run); p._p.append(insertion)
    duplicate_doc.save(duplicate_file); duplicate_draft = root / 'duplicate'; session.start(duplicate_draft, source=duplicate_file)
    try: session.resolve_tracked_runs(duplicate_draft, 0, 'word/document.xml', ['3'], True)
    except ValueError as exc: assert 'ambiguous' in str(exc)
    else: raise AssertionError('ambiguous IDs were accepted')
    assert session.info(duplicate_draft)['latest_revision'] == 0
print('Resolve tracked runs smoke passed: accept, reject, formatting, atomic failures and paragraph marks')
