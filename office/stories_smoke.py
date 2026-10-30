"""Exercise Word header/footer inventory and versioned replacement."""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.shared import Inches
import session
import word

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); source=root/'sections.docx'; draft=root/'draft'; doc=Document()
    section=doc.sections[0]; header=section.header; p=header.paragraphs[0]; p.add_run('Project ').bold=True; p.add_run('Alpha').italic=True
    table=header.add_table(rows=1,cols=1,width=Inches(3)); table.cell(0,0).text='Header table'
    section.first_page_header.paragraphs[0].text='First only'; footer=section.footer.paragraphs[0]; footer.add_run('Footer label')
    doc.add_paragraph('Body remains'); doc.add_section(WD_SECTION.NEW_PAGE); doc.save(source)
    listing=word.list_stories(source); assert listing['complete'] and listing['sections']==2
    header_story=next(x for x in listing['stories'] if any(p['text']=='Project Alpha' for p in x['paragraphs']))
    assert header_story['references']==[{'section':1,'type':'default'}]
    header_path=next(p['path'] for p in header_story['paragraphs'] if p['text']=='Project Alpha')
    table_path=next(p['path'] for p in header_story['paragraphs'] if p['text']=='Header table')
    footer_path=next(p['path'] for s in listing['stories'] for p in s['paragraphs'] if p['text']=='Footer label')
    session.start(draft, source=source); assert session.edit_target(draft,0,header_path)['replace_only']
    first=session.replace_text(draft,0,header_path,'ect Al','ECT AL')
    changed=Document(first['file']); p=changed.sections[0].header.paragraphs[0]
    assert p.text=='ProjECT ALpha' and p.runs[0].bold and p.runs[1].italic
    assert changed.sections[1].header.paragraphs[0].text=='ProjECT ALpha' and changed.paragraphs[0].text=='Body remains'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(first['file']) as after:
        modified={name for name in before.namelist() if before.read(name)!=after.read(name)}
        assert modified=={header_story['part']}, modified
    session.replace_text(draft,1,table_path,'table','cell'); session.replace_text(draft,2,footer_path,'label','note')
    assert Document(draft/'revision-000003.docx').sections[0].footer.paragraphs[0].text=='Footer note'
    try: session.add_comment(draft,3,header_path,'No','Author')
    except ValueError: pass
    else: raise AssertionError('Header comment unexpectedly accepted')
    try: session.replace_text(draft,1,header_path,'Project','Bad')
    except ValueError as exc: assert 'conflict' in str(exc)
    else: raise AssertionError('Stale edit succeeded')
    cli=Path(__file__).with_name('open_office_use.py'); result=subprocess.run([sys.executable,str(cli),'session','stories',str(draft),'--revision','3'],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['revision']==3
    field_doc=Document(); para=field_doc.sections[0].header.paragraphs[0]; para.add_run('label'); run=para.add_run(); fld=OxmlElement('w:fldChar'); fld.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType','begin'); run._r.append(fld)
    field_source=root/'field.docx'; field_doc.save(field_source); field_path=word.list_stories(field_source)['stories'][0]['paragraphs'][0]['path']
    try: word.replace_text(field_source,root/'bad.docx',field_path,'label','other')
    except ValueError: pass
    else: raise AssertionError('Field paragraph accepted')
    assert not (root/'bad.docx').exists()
print('Word story smoke passed: shared sections, headers, footers, tables and field protection')
