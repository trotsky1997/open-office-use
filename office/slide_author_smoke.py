"""Create a positioned slide with editable text, shape and image."""
import tempfile
import json
import sys
import subprocess
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
import open_office_use
import officecli_backend
import slide_text_check
import session
import notes
import slides

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); image = root/'picture.png'; Image.new('RGB', (32, 20), '#2b8a91').save(image)
    spec = {'slide_size':{'width':13.333,'height':7.5}, 'slides':[{'layout':'blank','background':'F5F8FC','elements':[
        {'type':'rectangle','x':0.5,'y':0.5,'width':0.2,'height':1.0,'fill':'236B8E'},
        {'type':'textbox','x':1,'y':0.5,'width':9,'height':1,'text':'Quarterly review','font_size':32,'font':'Arial','bold':True,'color':'14283F'},
        {'type':'textbox','x':1,'y':2,'width':6,'height':2,'text':'Revenue +18%\nRetention 92%','font_size':20,'color':'31485F'},
        {'type':'image','path':str(image),'x':9,'y':2,'width':3,'height':2,'description':'Teal illustration'}]}]}
    out = root/'slide.pptx'; open_office_use.author(spec, out)
    deck = Presentation(out); slide = deck.slides[0]
    assert abs(deck.slide_width-Inches(13.333)) < 5 and slide.background.fill.fore_color.rgb == (0xf5,0xf8,0xfc)
    assert len(slide.shapes) == 4 and slide.shapes[1].text == 'Quarterly review'
    assert slide.shapes[1].text_frame.paragraphs[0].runs[0].font.size.pt == 32
    assert slide.shapes[3]._element.nvPicPr.cNvPr.get('descr') == 'Teal illustration'
    pdf = open_office_use.render(out, root/'render'); assert Path(pdf).read_bytes().startswith(b'%PDF')
    line_file=root/'lines.pptx'
    lines=[{'type':'line','x':1,'y':1,'end_x':5,'end_y':1,'color':'236B8E','line_width':3,'arrow':'end'}, {'type':'line','x':5,'y':2,'end_x':1,'end_y':2,'color':'BA5A32','arrow':'end'}, {'type':'line','x':6,'y':1,'end_x':6,'end_y':3,'arrow':'both'}]
    open_office_use.author({'slides':[{'layout':'blank','elements':lines}]},line_file)
    first_line, reverse_line, vertical_line = Presentation(line_file).slides[0].shapes
    a='{http://schemas.openxmlformats.org/drawingml/2006/main}'
    assert first_line.line.width.pt == 3 and str(first_line.line.color.rgb) == '236B8E' and first_line._element.spPr.ln.find(a+'tailEnd').get('type') == 'triangle'
    assert reverse_line._element.spPr.xfrm.get('flipH') == '1' and reverse_line._element.spPr.ln.find(a+'tailEnd') is not None
    assert vertical_line._element.spPr.ln.find(a+'headEnd') is not None and vertical_line._element.spPr.ln.find(a+'tailEnd') is not None
    code, validation, _=officecli_backend.invoke('validate',line_file); assert code==0 and validation['success'],validation
    for bad in [dict(lines[0], end_x=1),dict(lines[0], arrow='side'),dict(lines[0], line_width=0),dict(lines[0], color='bad')]:
        invalid=root/'invalid-line.pptx'
        try: open_office_use.author({'slides':[{'layout':'blank','elements':[bad]}]},invalid)
        except ValueError: assert not invalid.exists()
        else: raise AssertionError('Invalid line accepted')
    notes_file=root/'notes-authored.pptx'
    notes_spec={'slides':[{'title':'First','notes':'Opening detail\nSecond paragraph'}, {'layout':'blank','notes':'Blank slide speaker notes'}, {'title':'No notes'}, {'title':'Empty notes','notes':''}]}
    notes_spec_file=root/'notes-spec.json';notes_spec_file.write_text(json.dumps(notes_spec))
    cli=Path(__file__).with_name('open_office_use.py')
    subprocess.run([sys.executable,str(cli),'author','--spec',str(notes_spec_file),'--out',str(notes_file)],capture_output=True,text=True,check=True)
    assert notes.read(notes_file,1)['text']=='Opening detail\nSecond paragraph' and notes.read(notes_file,2)['text']=='Blank slide speaker notes'
    assert not notes.read(notes_file,3)['has_notes_slide'] and notes.read(notes_file,4)['has_notes_slide']
    code, validation, _=officecli_backend.invoke('validate',notes_file); assert code==0 and validation['success'],validation
    found=slides.search_text(notes_file,'Second',scope='notes');assert len(found['matches'])==1 and found['matches'][0]['notes_paragraph']==2
    notes_draft=root/'authored-notes-draft';session.start(notes_draft,source=notes_file)
    session.replace_notes_text(notes_draft,0,1,2,'Second','Updated');assert session.read_notes(notes_draft,1,1)['text']=='Opening detail\nUpdated paragraph'
    extended=root/'notes-extended.pptx';open_office_use.author({'slides':[{'title':'Added','notes':'Added speaker notes'}]},extended,notes_file)
    assert notes.read(extended,1)['text']=='Opening detail\nSecond paragraph' and notes.read(extended,5)['text']=='Added speaker notes'
    for index, bad in enumerate([12,'bad\rtext','bad\x00text','bad\ud800text','x'*100001]):
        bad_file=root/f'bad-slide-notes-{index}.pptx'
        try: open_office_use.author({'slides':[{'title':'Bad','notes':bad}]},bad_file)
        except ValueError: pass
        else: raise AssertionError('Invalid slide notes accepted')
        assert not bad_file.exists()
    rich_spec={'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':7,'height':3,'font':'Arial','font_size':24,'color':'14283F','margins':{'left':0.2,'right':0.15,'top':0.1,'bottom':0.1},'vertical_align':'middle','auto_fit':'shrink','wrap':True,'paragraphs':[{'runs':[{'text':'Revenue '},{'text':'+18%','bold':True,'color':'236B8E','url':'https://example.com/report'}]},{'text':'Retention 92%','bullet':True,'level':0,'space_after':8},{'text':'Renewals improved','bullet':True,'level':1}]}]}]}
    rich=root/'rich.pptx'; rich_spec_path=root/'rich.json'; rich_spec_path.write_text(json.dumps(rich_spec))
    cli=Path(__file__).with_name('open_office_use.py'); call=subprocess.run([sys.executable,str(cli),'author','--spec',str(rich_spec_path),'--out',str(rich)],capture_output=True,text=True,check=True)
    assert json.loads(call.stdout)['output']==str(rich.resolve())
    rich_shape=Presentation(rich).slides[0].shapes[0]; paragraphs=rich_shape.text_frame.paragraphs
    assert rich_shape.text_frame.vertical_anchor == MSO_ANCHOR.MIDDLE and rich_shape.text_frame.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    assert abs(rich_shape.text_frame.margin_left.inches-0.2)<0.001 and rich_shape.text_frame.word_wrap
    assert [paragraph.text for paragraph in paragraphs]==['Revenue +18%','Retention 92%','Renewals improved']
    assert paragraphs[0].runs[1].font.bold and paragraphs[0].runs[1].font.size.pt==24 and str(paragraphs[0].runs[1].font.color.rgb)=='236B8E'
    assert paragraphs[0].runs[1].hyperlink.address=='https://example.com/report' and paragraphs[2].level==1
    assert paragraphs[1]._p.pPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}buChar').get('char')=='•'
    code, validation, _=officecli_backend.invoke('validate',rich); assert code==0 and validation['success'],validation
    rich_pdf=open_office_use.render(rich,root/'rich-render'); rich_text=subprocess.run(['pdftotext',rich_pdf,'-'],capture_output=True,text=True,check=True).stdout
    assert 'Retention 92%' in rich_text and 'Renewals improved' in rich_text
    rich_draft=root/'rich-draft';session.start(rich_draft,source=rich)
    changed=session.replace_text(rich_draft,0,f'/slide[1]/shape[@id={rich_shape.shape_id}]/paragraph[2]','Retention','Customer retention')
    assert Presentation(changed['file']).slides[0].shapes[0].text_frame.paragraphs[1].text=='Customer retention 92%'
    for mode, expected in [('none',1),('shrink',0),('resize',1)]:
        text_file=root/f'auto-{mode}.pptx'
        text_spec={'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':2,'height':0.6,'text':'A very long sentence that overflows this small text box and requires attention','font_size':24,'auto_fit':mode}]}]}
        open_office_use.author(text_spec,text_file); result=slide_text_check.scan(text_file,open_office_use.render)
        assert result['mapping_valid'] and result['candidate_count']==expected, (mode,result)
        if mode=='resize': assert Presentation(text_file).slides[0].shapes[0].text_frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    no_wrap=root/'no-wrap.pptx'
    open_office_use.author({'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':4,'height':1,'text':'Short','wrap':False,'vertical_align':'bottom','auto_fit':'none'}]}]},no_wrap)
    frame=Presentation(no_wrap).slides[0].shapes[0].text_frame
    assert frame.word_wrap is False and frame.vertical_anchor==MSO_ANCHOR.BOTTOM and frame.auto_size==MSO_AUTO_SIZE.NONE
    fit_spec = {'slides':[{'layout':'blank','elements':[
        {'type':'image','path':str(image),'x':1,'y':1,'width':2,'height':2,'fit':'contain'},
        {'type':'image','path':str(image),'x':4,'y':1,'width':2,'height':2,'fit':'cover'}]}]}
    fitted = root/'fitted.pptx'; open_office_use.author(fit_spec, fitted)
    contained, covered = Presentation(fitted).slides[0].shapes
    assert abs(contained.left-Inches(1)) <= 1 and abs(contained.top-Inches(1.375)) <= 1
    assert abs(contained.width-Inches(2)) <= 1 and abs(contained.height-Inches(1.25)) <= 1
    assert covered.width == Inches(2) and covered.height == Inches(2) and abs(covered.crop_left - 0.1875) < 0.00001 and abs(covered.crop_right - 0.1875) < 0.00001
    assert contained.crop_left == contained.crop_right == contained.crop_top == contained.crop_bottom == 0
    portrait = root/'portrait.png'; Image.new('RGB',(20,40),'blue').save(portrait)
    portrait_spec = {'slides':[{'layout':'blank','elements':[{'type':'image','path':str(portrait),'x':1,'y':1,'width':2,'height':2,'fit':'cover'}, {'type':'image','path':str(portrait),'x':4,'y':1,'width':2,'height':2,'fit':'contain'}]}]}
    portrait_deck = root/'portrait.pptx'; open_office_use.author(portrait_spec, portrait_deck)
    cropped, letterboxed = Presentation(portrait_deck).slides[0].shapes
    assert abs(cropped.crop_top - 0.25) < 0.00001 and abs(cropped.crop_bottom - 0.25) < 0.00001
    assert abs(letterboxed.left-Inches(4.5)) <= 1 and abs(letterboxed.width-Inches(1)) <= 1 and letterboxed.height == Inches(2)
    oriented = root/'rotated.jpg'; photo = Image.new('RGB',(10,20),'red'); exif = Image.Exif(); exif[274] = 6; photo.save(oriented, exif=exif)
    try: open_office_use.author({'slides':[{'layout':'blank','elements':[{'type':'image','path':str(oriented),'x':0,'y':0,'width':1,'height':1,'fit':'contain'}]}]}, root/'rotated.pptx')
    except ValueError as exc: assert 'orientation' in str(exc)
    else: raise AssertionError('Image with unresolved orientation accepted')
    table_spec = {'slide_size':{'width':13.333,'height':7.5}, 'slides':[{'layout':'blank','elements':[{'type':'table','x':1,'y':1,'width':8,'height':2,'rows':[['Metric','Current','Prior'],['Revenue','18%','12%'],['Retention','92%','90%']],'header':True,'font':'Arial','font_size':18,'color':'14283F','header_fill':'236B8E','header_color':'FFFFFF','column_weights':[2,1,1]}]}]}
    table_file = root/'table.pptx'; open_office_use.author(table_spec, table_file)
    shape = Presentation(table_file).slides[0].shapes[0]; table = shape.table
    assert table.cell(1,0).text == 'Revenue' and table.cell(0,1).text == 'Current' and table.first_row
    assert [column.width for column in table.columns] == [Inches(4), Inches(2), Inches(2)]
    assert table.cell(0,0).fill.fore_color.rgb == (0x23,0x6b,0x8e)
    assert table.cell(0,0).text_frame.paragraphs[0].runs[0].font.bold
    assert table.cell(1,0).text_frame.paragraphs[0].runs[0].font.size.pt == 18
    assert Path(open_office_use.render(table_file, root/'table-render')).read_bytes().startswith(b'%PDF')
    draft = root/'table-draft'; session.start(draft, source=table_file)
    edited = session.replace_text(draft, 0, f'/slide[1]/table[@id={shape.shape_id}]/tr[2]/tc[2]', '18%', '21%')
    updated = Presentation(edited['file']).slides[0].shapes[0].table
    assert updated.cell(1,1).text == '21%' and updated.cell(1,1).text_frame.paragraphs[0].runs[0].font.size.pt == 18
    rich_table_spec={'slides':[{'layout':'blank','elements':[{'type':'table','x':1,'y':1,'width':8,'height':2,'header':True,'header_fill':'236B8E','header_color':'FFFFFF','font':'Arial','font_size':18,'rows':[[{'paragraphs':[{'runs':[{'text':'Metric'},{'text':' detail','italic':True}]}]},'Value'],['Growth',{'paragraphs':[{'runs':[{'text':'18%','bold':True,'color':'14804A'},{'text':' source','url':'https://example.com/source'}]},{'text':'Year over year','align':'right'}]}]]}]}]}
    rich_table=root/'rich-table.pptx';rich_table_json=root/'rich-table.json';rich_table_json.write_text(json.dumps(rich_table_spec))
    subprocess.run([sys.executable,str(cli),'author','--spec',str(rich_table_json),'--out',str(rich_table)],capture_output=True,text=True,check=True)
    rich_shape=Presentation(rich_table).slides[0].shapes[0];rich_header=rich_shape.table.cell(0,0).text_frame.paragraphs[0];rich_cell=rich_shape.table.cell(1,1).text_frame
    assert rich_header.text=='Metric detail' and all(run.font.bold and str(run.font.color.rgb)=='FFFFFF' for run in rich_header.runs) and rich_header.runs[1].font.italic
    assert [paragraph.text for paragraph in rich_cell.paragraphs]==['18% source','Year over year']
    assert rich_cell.paragraphs[0].runs[0].font.bold and str(rich_cell.paragraphs[0].runs[0].font.color.rgb)=='14804A'
    assert rich_cell.paragraphs[0].runs[1].hyperlink.address=='https://example.com/source' and rich_cell.paragraphs[0].runs[1].font.name=='Arial'
    code, validation, _=officecli_backend.invoke('validate',rich_table); assert code==0 and validation['success'],validation
    rich_table_pdf=open_office_use.render(rich_table,root/'rich-table-render');rich_table_text=subprocess.run(['pdftotext',rich_table_pdf,'-'],capture_output=True,text=True,check=True).stdout
    assert 'Metric detail' in rich_table_text and 'Year over year' in rich_table_text
    found=slides.search_text(rich_table,'Year over year');assert len(found['matches'])==1
    rich_table_draft=root/'rich-table-draft';session.start(rich_table_draft,source=rich_table)
    edited=session.replace_text(rich_table_draft,0,f'/slide[1]/table[@id={rich_shape.shape_id}]/tr[2]/tc[2]/paragraph[2]','Year over year','Annual comparison')
    assert Presentation(edited['file']).slides[0].shapes[0].table.cell(1,1).text_frame.paragraphs[1].text=='Annual comparison'
    for index, bad_table in enumerate([
        {'rows':[['x'],['y','z']]}, {'rows':[['x','y']],'column_weights':[1]},
        {'rows':[['x']],'header_fill':'000000'}, {'rows':[['x']],'header':1}, {'rows':[[{'paragraphs':[{'runs':[{'text':'x','url':'javascript:x'}]}]}]]}]):
        bad = {'slides':[{'layout':'blank','elements':[{'type':'table','x':0,'y':0,'width':4,'height':1,**bad_table}]}]}; bad_path=root/f'bad-table{index}.pptx'
        try: open_office_use.author(bad, bad_path)
        except ValueError: pass
        else: raise AssertionError('Invalid slide table accepted')
        assert not bad_path.exists()
    original = out.read_bytes(); appended = root/'appended.pptx'
    open_office_use.author({'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':4,'height':1,'text':'Append'}]}]}, appended, out)
    assert out.read_bytes() == original and len(Presentation(appended).slides) == 2
    try: open_office_use.author({'slide_size':{'width':10,'height':7.5}}, root/'resize.pptx', out)
    except ValueError: pass
    else: raise AssertionError('Existing presentation was resized')
    invalid_paragraphs=[{'paragraphs':[{'text':'x','runs':[]}]}, {'paragraphs':[{'text':'x','bullet':'yes'}]}, {'paragraphs':[{'text':'x','level':9}]}, {'paragraphs':[{'runs':[{'text':'x','url':'javascript:alert(1)'}]}]}, {'paragraphs':[{'runs':[{'text':'bad\nline'}]}]}, {'text':'x','paragraphs':[{'text':'x'}]}, {'text':'x','vertical_align':'center'}, {'text':'x','auto_fit':'invalid'}, {'text':'x','wrap':'yes'}, {'text':'x','margins':{'left':2,'right':2}}, {'text':'x','margins':None}]
    for index, content in enumerate(invalid_paragraphs):
        path=root/f'bad-rich-{index}.pptx'
        try: open_office_use.author({'slides':[{'layout':'blank','elements':[{'type':'textbox','x':0,'y':0,'width':3,'height':2,**content}]}]},path)
        except ValueError: pass
        else: raise AssertionError('Invalid rich slide text accepted')
        assert not path.exists()
    for i, bad in enumerate([
        {'slides':[{'layout':'blank','elements':[{'type':'textbox','x':0,'y':0,'width':0,'height':1,'text':'x'}]}]},
        {'slides':[{'layout':'blank','elements':[{'type':'rectangle','x':0,'y':0,'width':1,'height':1,'fill':'INVALID'}]}]},
        {'slides':[{'layout':'blank','elements':[{'type':'image','x':0,'y':0,'width':1,'height':1,'path':str(root/'missing')}]}]},
        {'slide_size':{'width':float('nan'),'height':7.5}}]):
        target = root/f'bad{i}.pptx'
        try: open_office_use.author(bad, target)
        except (ValueError, OSError): pass
        else: raise AssertionError('Invalid slide specification accepted')
        assert not target.exists()
print('Slide author passed: layout, formatting, image, render and invalid input')
