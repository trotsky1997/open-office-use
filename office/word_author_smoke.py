"""Create and render an ordered, styled Word document from blocks."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image
from docx.oxml.ns import qn
import open_office_use
import officecli_backend
import session
import review

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); output = root / 'brief.docx'
    spec = {'blocks': [
        {'type':'heading','level':1,'text':'Quarterly review'},
        {'type':'paragraph','align':'justify','space_before':6,'space_after':8,'line_spacing':1.5,'keep_with_next':True,'keep_together':True,'runs':[{'text':'Revenue grew '},{'text':'18%','bold':True,'font':'Arial','font_size':16,'color':'236B8E'},{'text':' year over year.'}]},
        {'type':'bullet','text':'Retention was stable'},
        {'type':'numbered','text':'Prioritize onboarding'},
        {'type':'table','header':True,'style':'Light Shading Accent 1','rows':[['Metric','Value'],['Retention','92%']]},
        {'type':'page_break'}, {'type':'heading','level':2,'text':'Next steps'}]}
    path = root/'spec.json'; path.write_text(json.dumps(spec), encoding='utf-8')
    cli = Path(__file__).with_name('open_office_use.py')
    result = subprocess.run([sys.executable,str(cli),'author','--spec',str(path),'--out',str(output)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['output'] == str(output.resolve())
    doc = Document(output); assert [p.text for p in doc.paragraphs] == ['Quarterly review','Revenue grew 18% year over year.','Retention was stable','Prioritize onboarding','','Next steps']
    assert doc.paragraphs[0].style.name == 'Heading 1' and doc.paragraphs[2].style.name == 'List Bullet' and doc.paragraphs[3].style.name == 'List Number'
    paragraph=doc.paragraphs[1]; formatted=paragraph.runs[1]
    assert formatted.bold and formatted.font.name=='Arial' and formatted.font.size.pt==16 and str(formatted.font.color.rgb)=='236B8E'
    assert formatted._r.rPr.rFonts.get(qn('w:eastAsia'))=='Arial' and paragraph.alignment==WD_ALIGN_PARAGRAPH.JUSTIFY
    assert paragraph.paragraph_format.space_before.pt==6 and paragraph.paragraph_format.space_after.pt==8 and paragraph.paragraph_format.line_spacing==1.5 and paragraph.paragraph_format.keep_with_next and paragraph.paragraph_format.keep_together
    assert doc.tables[0].cell(1,1).text == '92%'
    code, validation, _=officecli_backend.invoke('validate',output); assert code==0 and validation['success'],validation
    assert doc.tables[0].rows[0]._tr.trPr.find(qn('w:tblHeader')) is not None and doc.tables[0].cell(0,0).paragraphs[0].runs[0].bold
    assert doc.tables[0].style.name == 'Light Shading Accent 1'
    body = list(doc._element.body)
    assert [item.tag.rsplit('}', 1)[-1] for item in body] == ['p','p','p','p','tbl','p','p','sectPr']
    assert body[5].find('.//' + qn('w:br')).get(qn('w:type')) == 'page'
    pdf = open_office_use.render(output, root/'render'); assert Path(pdf).read_bytes().startswith(b'%PDF')
    paged=root/'paged.docx'
    page_spec={'page_setup':{'size':'a4','orientation':'landscape','margins':{'top':0.7,'bottom':0.7,'left':0.8,'right':0.8},'header':{'text':'Quarterly report','align':'left'},'footer':{'text':'Page','align':'right','page_number':True}},'blocks':[{'type':'paragraph','text':'First page'},{'type':'page_break'},{'type':'paragraph','text':'Second page'}]}
    page_path=root/'page-spec.json';page_path.write_text(json.dumps(page_spec),encoding='utf-8')
    page_call=subprocess.run([sys.executable,str(cli),'author','--spec',str(page_path),'--out',str(paged)],capture_output=True,text=True,check=True)
    assert json.loads(page_call.stdout)['output']==str(paged.resolve())
    paged_doc=Document(paged); section=paged_doc.sections[0]
    assert section.page_width > section.page_height and abs(section.page_width.inches-11.69)<0.02 and abs(section.left_margin.inches-0.8)<0.01
    assert section.header.paragraphs[0].text=='Quarterly report' and section.footer.paragraphs[0].text=='Page '
    assert section.footer.paragraphs[0]._p.find(qn('w:fldSimple')).get(qn('w:instr')).strip()=='PAGE'
    code, validation, _=officecli_backend.invoke('validate',paged); assert code==0 and validation['success'],validation
    paged_pdf=open_office_use.render(paged,root/'paged-render')
    text=subprocess.run(['pdftotext','-layout',paged_pdf,'-'],capture_output=True,text=True,check=True).stdout
    pages=[page for page in text.split('\f') if page.strip()]
    assert len(pages)==2 and 'Quarterly report' in pages[0] and 'Quarterly report' in pages[1] and 'Page 1' in pages[0] and 'Page 2' in pages[1],pages
    for index, setup in enumerate([{'size':'bad'}, {'margins':{'left':True}}, {'margins':{'left':5,'right':5}}, {'footer':{'page_number':'yes'}}, {'header':{'page_number':True}}]):
        target=root/f'bad-page-{index}.docx'
        try: open_office_use.author({'page_setup':setup},target)
        except ValueError: pass
        else: raise AssertionError(f'Invalid page setup accepted: {setup}')
        assert not target.exists()
    try: open_office_use.author({'page_setup':{}},root/'bad-source.docx',output)
    except ValueError: pass
    else: raise AssertionError('Page setup accepted on existing document')
    picture = root/'image.png'; Image.new('RGB',(80,40),'#348087').save(picture,dpi=(72,144))
    linked = root/'linked.docx'; link_spec = {'blocks':[{'type':'paragraph','runs':[{'text':'See '},{'text':'source','url':'https://example.com/report','bold':True,'font':'Arial','font_size':14,'color':'BA5A32'}]},{'type':'image','path':str(picture),'width':4,'align':'center','description':'Teal diagram'}]}
    open_office_use.author(link_spec, linked); linked_doc = Document(linked)
    assert linked_doc.paragraphs[0].text == 'See source' and linked_doc.paragraphs[0].hyperlinks[0].address == 'https://example.com/report'
    run = linked_doc.paragraphs[0].hyperlinks[0].runs[0]; assert run.bold and run.underline and run.font.name=='Arial' and run.font.size.pt==14 and str(run.font.color.rgb)=='BA5A32'
    inline = linked_doc.inline_shapes[0]; assert inline.width.inches == 4 and inline.height.inches == 2 and inline._inline.docPr.get('descr') == 'Teal diagram'
    assert review.external_relationships(linked)['external_count'] == 1
    draft = root/'draft'; session.start(draft, source=linked)
    edited = session.replace_text(draft, 0, '/body/p[1]', 'source', 'reference')
    result_doc = Document(edited['file']); assert result_doc.paragraphs[0].hyperlinks[0].text == 'reference' and result_doc.paragraphs[0].hyperlinks[0].address == 'https://example.com/report'
    assert Path(open_office_use.render(linked, root/'linked-render')).read_bytes().startswith(b'%PDF')
    for index, url in enumerate(['javascript:alert(1)', 'https://', 'https://example.com/bad path']):
        bad_file = root/f'bad-link{index}.docx'
        try: open_office_use.author({'blocks':[{'type':'paragraph','runs':[{'text':'Link','url':url}]}]}, bad_file)
        except ValueError: pass
        else: raise AssertionError('Invalid hyperlink accepted')
        assert not bad_file.exists()
    for i, bad in enumerate([{'blocks':[{'type':'table','rows':[['a'],['a','b']]}]}, {'blocks':[{'type':'heading','level':10,'text':'bad'}]}, {'blocks':[{'type':'paragraph','text':'a','runs':[]}]}, {'blocks':[{'type':'paragraph','runs':[{'text':'a','bold':'yes'}]}]}, {'blocks':[{'type':'paragraph','align':'bad','text':'a'}]}, {'blocks':[{'type':'paragraph','line_spacing':0,'text':'a'}]}, {'blocks':[{'type':'paragraph','runs':[{'text':'a','font_size':True}]}]}, {'blocks':[{'type':'paragraph','runs':[{'text':'a','font_size':12.1}]}]}, {'blocks':[{'type':'paragraph','runs':[{'text':'a','color':'oops'}]}]}]):
        target = root/f'bad{i}.docx'
        try: open_office_use.author(bad, target)
        except ValueError: pass
        else: raise AssertionError(f'Invalid block accepted: {bad}')
        assert not target.exists()
print('Word author blocks passed: structure, formatting, rendering and invalid input')
