"""Create a formatted workbook with formulas and worksheet settings."""
import tempfile
import json
import sys
import zipfile
from lxml import etree
import subprocess
from pathlib import Path
from openpyxl import load_workbook
from PIL import Image
import xlsxwriter
import open_office_use
import officecli_backend
import chart_cache
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); output = root/'forecast.xlsx'
    spec = {'sheets':{'Forecast':{'A1':'Metric','B1':'Revenue','C1':'Growth','A2':'Q1','B2':100,'C2':0.18,'A3':'Q2','B3':'=B2*1.2','C3':'=B3/B2-1'}},
            'sheet_options':{'Forecast':{'freeze_panes':'B2','auto_filter':'A1:C3','fit_to_page':True,'column_widths':{'A':20,'B':16,'C':14},'row_heights':{'1':24},'formats':[
                {'range':'A1:C1','bold':True,'fill':'236B8E','font_color':'FFFFFF','horizontal':'center','wrap':True},
                {'range':'B2:B3','number_format':'#,##0.00'}, {'range':'C2:C3','number_format':'0.0%'}]}}}
    spec['sheet_options']['Forecast']['charts'] = [{'type':'column','data':'B1:B3','categories':'A2:A3','anchor':'E2','title':'Revenue','y_axis_title':'USD','width':12,'height':7}, {'type':'line','data':'C1:C3','categories':'A2:A3','anchor':'E18','title':'Growth'}]
    open_office_use.author(spec,output)
    sheet = load_workbook(output)['Forecast']
    assert sheet.freeze_panes == 'B2' and sheet.auto_filter.ref == 'A1:C3'
    assert sheet.sheet_properties.pageSetUpPr.fitToPage and sheet.page_setup.fitToWidth == 1 and sheet.page_setup.fitToHeight == 0
    assert sheet.column_dimensions['A'].width == 20 and sheet.row_dimensions[1].height == 24
    assert sheet['A1'].font.bold and sheet['A1'].font.color.rgb == 'FFFFFFFF' and sheet['A1'].fill.fgColor.rgb == 'FF236B8E'
    assert sheet['A1'].alignment.horizontal == 'center' and sheet['A1'].alignment.wrap_text
    assert sheet['B3'].value == '=B2*1.2' and sheet['B3'].number_format == '#,##0.00' and sheet['C3'].number_format == '0.0%'
    assert load_workbook(output,data_only=True)['Forecast']['B3'].value is None
    assert len(sheet._charts) == 2 and sheet._charts[0].__class__.__name__ == 'BarChart' and sheet._charts[1].__class__.__name__ == 'LineChart'
    assert sheet._charts[0].series[0].val.numRef.f == "'Forecast'!$B$2:$B$3" and sheet._charts[0].series[0].cat.strRef.f == "'Forecast'!$A$2:$A$3"
    report = chart_cache.scan(output)
    refs = report['charts'][0]['references']; assert [ref['status'] for ref in refs] == ['match','match','missing_cache']
    literal_spec = {'sheets':{'Sales':{'A1':'Quarter','B1':'Revenue','A2':'Q1','B2':100,'A3':'Q2','B3':120}},'sheet_options':{'Sales':{'formats':[{'range':'B2:B3','number_format':'0.00'}],'charts':[{'type':'column','data':'B1:B3','categories':'A2:A3'}]}}}
    literal = root/'literal.xlsx'; open_office_use.author(literal_spec, literal)
    assert load_workbook(literal)['Sales']._charts[0].series[0].val.numRef.numCache.formatCode == '0.00'
    checked = chart_cache.scan(literal); assert checked['complete'] and checked['missing_caches'] == 0 and checked['mismatch_references'] == 0
    draft = root/'draft'; session.start(draft, source=literal)
    edited = session.edit_grid(draft, 0, 'Sales', 'B2', [{'cell':'B2','value':'200'}])
    stale = chart_cache.scan(edited['file']); assert stale['mismatch_references'] == 1
    formula_spec = {'sheets':{'Data':{'A1':'=1','A2':'=2','B1':10,'B2':20}},'sheet_options':{'Data':{'charts':[{'type':'line','data':'B1:B2','categories':'A1:A2','category_type':'number','titles_from_data':False}]}}}
    formula_chart = root/'formula-categories.xlsx'; open_office_use.author(formula_spec, formula_chart)
    assert load_workbook(formula_chart)['Data']._charts[0].series[0].cat.numRef is not None
    del formula_spec['sheet_options']['Data']['charts'][0]['category_type']
    try: open_office_use.author(formula_spec, root/'unknown-categories.xlsx')
    except ValueError as exc: assert 'category_type' in str(exc)
    else: raise AssertionError('Formula category type was guessed')
    assert Path(open_office_use.render(output, root/'render')).read_bytes().startswith(b'%PDF')
    printing=root/'printing.xlsx'; cells={'A1':'Metric','B1':'Value','A100':'OUTSIDE PRINT AREA'}
    cells.update({f'A{i}':f'Row {i}' for i in range(2,100)}); cells.update({f'B{i}':i for i in range(2,100)})
    print_settings={'paper':'a4','orientation':'landscape','area':'A1:B99','repeat_rows':'1:1','repeat_columns':'A:A','header':{'text':'R&D REPORT'},'footer':{'text':'Page','page_number':True}}
    print_spec=root/'print-spec.json'; print_spec.write_text(json.dumps({'sheets':{'Data':cells},'sheet_options':{'Data':{'print_options':print_settings}}}))
    cli=Path(__file__).with_name('open_office_use.py')
    created=subprocess.run([sys.executable,str(cli),'author','--spec',str(print_spec),'--out',str(printing)],capture_output=True,text=True,check=True)
    assert json.loads(created.stdout)['output']==str(printing.resolve())
    printed=load_workbook(printing)['Data']
    assert str(printed.page_setup.paperSize)=='9' and printed.page_setup.orientation=='landscape' and printed.print_title_rows=='$1:$1' and printed.print_title_cols=='$A:$A'
    assert str(printed.print_area)=="'Data'!$A$1:$B$99" and printed.oddHeader.left.text=='R&&D REPORT' and printed.oddFooter.right.text=='Page &P'
    code, validation, _=officecli_backend.invoke('validate',printing); assert code==0 and validation['success'],validation
    pdf=open_office_use.render(printing,root/'print-render'); text=subprocess.run(['pdftotext','-layout',pdf,'-'],capture_output=True,text=True,check=True).stdout
    pages=[page for page in text.split('\f') if page.strip()]; assert len(pages)>=2
    assert all('Metric' in page and 'R&D REPORT' in page and f'Page {index}' in page for index,page in enumerate(pages,1)),pages
    assert 'OUTSIDE PRINT AREA' not in text
    image_path=root/'figure.png'; Image.new('RGB',(80,40),'#236B8E').save(image_path)
    image_source=image_path.read_bytes(); image_book=root/'images.xlsx'
    image_spec={'sheets':{'Data':{'A1':'Chart'}},'sheet_options':{'Data':{'images':[{'path':str(image_path),'anchor':'C3','width':200,'description':'Revenue graphic'}]}}}
    image_spec_path=root/'image-spec.json';image_spec_path.write_text(json.dumps(image_spec));
    result=subprocess.run([sys.executable,str(cli),'author','--spec',str(image_spec_path),'--out',str(image_book)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['output']==str(image_book.resolve())
    image_path.unlink(); loaded=load_workbook(image_book)['Data']; assert loaded['A1'].value=='Chart' and len(loaded._images)==1
    picture=loaded._images[0]; assert picture._data()==image_source and picture.anchor._from.col==2 and picture.anchor._from.row==2
    assert picture.anchor.ext.width==200*9525 and picture.anchor.ext.height==100*9525
    assert picture.anchor.pic.nvPicPr.cNvPr.descr=='Revenue graphic'
    code, validation, _=officecli_backend.invoke('validate',image_book); assert code==0 and validation['success'],validation
    image_pdf=open_office_use.render(image_book,root/'image-render')
    listed=subprocess.run(['pdfimages','-list',image_pdf],capture_output=True,text=True,check=True).stdout
    assert any('image' in line and '80' in line and '40' in line for line in listed.splitlines()[2:]),listed
    second_image=root/'second.jpg'; Image.new('RGB',(40,40),'#BA5A32').save(second_image)
    mixed_book=root/'mixed-images.xlsx'
    open_office_use.author({'sheets':{'Data':{'A2':1,'A3':2}},'sheet_options':{'Data':{'images':[{'path':str(second_image),'anchor':'D4','width':120,'description':'Second graphic'}],'charts':[{'type':'line','data':'A1:A3'}]}}},mixed_book,image_book)
    mixed=load_workbook(mixed_book)['Data']; assert len(mixed._images)==2 and len(mixed._charts)==1
    assert [image.anchor.pic.nvPicPr.cNvPr.descr for image in mixed._images]==['Revenue graphic','Second graphic']
    with zipfile.ZipFile(mixed_book) as archive:
        drawing=etree.fromstring(archive.read('xl/drawings/drawing1.xml'))
        identifiers=drawing.xpath('//*[local-name()="cNvPr"]/@id')
    assert len(identifiers)==3 and len(set(identifiers))==3, identifiers
    code, validation, _=officecli_backend.invoke('validate',mixed_book); assert code==0 and validation['success'],validation
    for index, image in enumerate([{'path':str(image_book),'anchor':'A1','width':100}, {'path':str(image_book),'anchor':'XFE1','width':100}, {'path':str(image_book),'anchor':'A1','width':True}]):
        invalid=root/f'bad-image-{index}.xlsx'
        try: open_office_use.author({'sheets':{'Data':{}},'sheet_options':{'Data':{'images':[image]}}},invalid)
        except (ValueError, OSError): pass
        else: raise AssertionError('Invalid worksheet image accepted')
        assert not invalid.exists()
    table_file=root/'table.xlsx'
    table_spec={'sheets':{'Sales':{'A1':'Quarter','B1':'Revenue','A2':'Q1','B2':120,'A3':'Q2','B3':140}},'sheet_options':{'Sales':{'tables':[{'name':'SalesTable','range':'A1:B3','style':'TableStyleMedium2','row_stripes':True}]}}}
    table_json=root/'table-spec.json';table_json.write_text(json.dumps(table_spec))
    result=subprocess.run([sys.executable,str(cli),'author','--spec',str(table_json),'--out',str(table_file)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['output']==str(table_file.resolve())
    table_sheet=load_workbook(table_file)['Sales']; table=table_sheet.tables['SalesTable']
    assert table.ref=='A1:B3' and [column.name for column in table.tableColumns]==['Quarter','Revenue'] and table.autoFilter.ref=='A1:B3' and table.tableStyleInfo.showRowStripes
    code, validation, _=officecli_backend.invoke('validate',table_file); assert code==0 and validation['success'],validation
    try: open_office_use.author({'sheets':{'Sales':{'A1':'Period'}}},root/'unsafe-table-header.xlsx',table_file)
    except ValueError as exc: assert 'table' in str(exc).lower()
    else: raise AssertionError('Table header authoring edit accepted')
    assert not (root/'unsafe-table-header.xlsx').exists()
    copied_table=root/'copied-table.xlsx'
    open_office_use.author({'sheets':{'Sales':{'B2':160}}},copied_table,table_file)
    copied_sheet=load_workbook(copied_table)['Sales']; assert copied_sheet['B2'].value==160 and copied_sheet.tables['SalesTable'].tableColumns[0].name=='Quarter'
    table_draft=root/'table-draft';session.start(table_draft,source=table_file)
    grid=session.read_grid(table_draft,0,'Sales','A1:B2');assert grid['rows'][0][0]['read_only_reason']=='table_header' and grid['rows'][1][1]['editable']
    try: session.replace_text(table_draft,0,'/Sales/A1','Quarter','Period')
    except ValueError as exc: assert 'table' in str(exc).lower()
    else: raise AssertionError('Table header replacement accepted')
    try: session.edit(table_draft,0,'/Sales/A1','literal','Period')
    except ValueError as exc: assert 'table_header' in str(exc)
    else: raise AssertionError('Table header element edit accepted')
    try: session.edit_grid(table_draft,0,'Sales','A1',[{'cell':'A1','value':'Period'}])
    except ValueError as exc: assert 'table_header' in str(exc)
    else: raise AssertionError('Table header grid edit accepted')
    changed=session.edit_grid(table_draft,0,'Sales','B2',[{'cell':'B2','value':'150'}]);updated=load_workbook(changed['file'])['Sales']
    assert updated['B2'].value==150 and updated.tables['SalesTable'].tableColumns[0].name=='Quarter'
    assert Path(open_office_use.render(table_file,root/'table-render')).read_bytes().startswith(b'%PDF')
    for index, options in enumerate([{'tables':[{'name':'A1','range':'A1:B3'}]}, {'tables':[{'name':'T','range':'A1:B1'}]}, {'tables':[{'name':'T','range':'A1:B3','style':'Invalid'}]}, {'tables':[{'name':'T','range':'A1:B3'},{'name':'t','range':'D1:E3'}]}, {'tables':[{'name':'T','range':'A1:B3'},{'name':'U','range':'B2:C3'}]}, {'auto_filter':'A1:B3','tables':[{'name':'T','range':'A1:B3'}]}]):
        target=root/f'bad-structured-table-{index}.xlsx'
        try: open_office_use.author({'sheets':{'Sales':{'A1':'Quarter','B1':'Revenue','A2':'Q1','B2':10,'D1':'X','E1':'Y'}},'sheet_options':{'Sales':options}},target)
        except ValueError: pass
        else: raise AssertionError(f'Invalid table accepted: {options}')
        assert not target.exists()
    for index, headers in enumerate([['Name','name'],['Name',''],['=1','Value']]):
        target=root/f'bad-table-headers-{index}.xlsx'
        try: open_office_use.author({'sheets':{'Sales':{'A1':headers[0],'B1':headers[1],'A2':'x','B2':1}},'sheet_options':{'Sales':{'tables':[{'name':'SalesTable','range':'A1:B2'}]}}},target)
        except ValueError: pass
        else: raise AssertionError('Invalid table headers accepted')
        assert not target.exists()
    totals_file=root/'totals.xlsx';book=xlsxwriter.Workbook(str(totals_file));ws=book.add_worksheet('Data')
    ws.add_table('A1:B4',{'name':'TotalsTable','total_row':True,'columns':[{'header':'Item','total_string':'Total'},{'header':'Amount','total_function':'sum'}],'data':[['A',10],['B',20]]});book.close()
    totals_draft=root/'totals-draft';session.start(totals_draft,source=totals_file)
    totals_grid=session.read_grid(totals_draft,0,'Data','A4:B4')
    assert all(cell['read_only_reason']=='table_totals' for cell in totals_grid['rows'][0]),totals_grid
    try: session.edit_grid(totals_draft,0,'Data','A4',[{'cell':'A4','value':'Other'}])
    except ValueError: pass
    else: raise AssertionError('Table total edit accepted')
    before = output.read_bytes(); revised = root/'revised.xlsx'
    open_office_use.author({'sheet_options':{'Forecast':{'formats':[{'range':'A1','italic':True}]}}}, revised, output)
    revised_sheet = load_workbook(revised)['Forecast']; assert revised_sheet['A1'].font.bold and revised_sheet['A1'].font.italic and output.read_bytes() == before
    filtered = root/'filtered.xlsx'; filtered_book = load_workbook(output); filtered_book['Forecast'].auto_filter.add_filter_column(0, ['Q1']); filtered_book.save(filtered)
    try: open_office_use.author({'sheet_options':{'Forecast':{'auto_filter':'A1:C2'}}}, root/'unsafe.xlsx', filtered)
    except ValueError as exc: assert 'filter criteria' in str(exc)
    else: raise AssertionError('Existing filter criteria were silently changed')
    assert not (root/'unsafe.xlsx').exists()
    for index, opts in enumerate([{'freeze_panes':'A1:B2'}, {'fit_to_page':'yes'}, {'print_options':{'paper':'bad'}}, {'print_options':{'repeat_rows':'2:1'}}, {'print_options':{'repeat_columns':'A:XFE'}}, {'print_options':{'paper':'letter','margins':{'left':5,'right':5}}}, {'print_options':{'footer':{'page_number':'yes'}}}, {'column_widths':{'XFE':10}}, {'row_heights':{'1':True}}, {'formats':[{'range':'A1:Z10000','bold':True}]}, {'formats':[{'range':'A1','font_color':'BAD'}]}, {'charts':[{'type':'line','data':'B1:B3','categories':'A2:A2'}]}, {'charts':[{'type':'pie','data':'B1:B3'}]}]):
        target = root/f'bad{index}.xlsx'
        try: open_office_use.author({'sheets':{'Forecast':{}},'sheet_options':{'Forecast':opts}}, target)
        except ValueError: pass
        else: raise AssertionError('Invalid sheet setting accepted')
        assert not target.exists()
print('Workbook author passed: settings, formulas, formatting, render and invalid input')
