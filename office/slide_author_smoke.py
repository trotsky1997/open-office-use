"""Create a positioned slide with editable text, shape and image."""
import tempfile
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
import open_office_use
import session

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
    for index, bad_table in enumerate([
        {'rows':[['x'],['y','z']]}, {'rows':[['x','y']],'column_weights':[1]},
        {'rows':[['x']],'header_fill':'000000'}, {'rows':[['x']],'header':1}]):
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
