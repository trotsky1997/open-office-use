"""Check the stdio MCP lifecycle and real artifact operations."""
import asyncio
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from lxml import etree
from openpyxl.styles import Font, Protection
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from pptx import Presentation
from PIL import Image as PILImage
from pptx.util import Inches
import xlsxwriter
from session import set_selection
from thread_comment_smoke import fixture as thread_fixture
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    cli = Path(__file__).with_name('open_office_use.py')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(cli), 'mcp'])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {'office_doctor', 'office_schema', 'inspect_file', 'author_file', 'inspect_external_relationships', 'session_inspect_external_relationships', 'session_inspect_workbook', 'search_cells', 'session_search_cells', 'scan_chart_caches', 'session_scan_chart_caches', 'session_sync_chart_cache', 'session_set_chart_literal_value', 'session_set_chart_literal_category', 'session_set_chart_literal_series_name', 'session_sync_slide_chart_cache', 'session_set_slide_chart_axis_bounds', 'session_set_slide_chart_literal_value', 'session_set_slide_chart_literal_text', 'session_set_slide_chart_text_color', 'session_read_slide_chart_grid', 'session_edit_slide_chart_grid', 'inspect_slide_layout', 'session_inspect_slide_layout', 'inspect_slide_charts', 'session_inspect_slide_charts', 'inspect_slide_navigation', 'session_inspect_slide_navigation', 'inspect_slide_text', 'session_inspect_slide_text', 'search_slide_text', 'session_search_slide_text', 'structured_read', 'dump_office_subtree', 'session_dump_office_subtree', 'apply_batch', 'render_pdf', 'preview_pages', 'view_page', 'view_contact_sheet', 'session_contact_sheet', 'view_document_page', 'session_view_page', 'compare_page_images', 'session_compare_page_images', 'read_cells', 'recalculate_workbook', 'compare_files', 'audit_file', 'review_document_bundle', 'session_review_bundle', 'start_session', 'session_info', 'session_apply', 'session_export', 'session_selection', 'session_selection_image', 'session_selection_text', 'session_selection_candidates', 'session_restore', 'session_recalculate', 'session_scan_formulas', 'session_edit_target', 'session_edit', 'session_replace_text', 'session_refresh_word_toc', 'session_replace_text_batch', 'session_track_replace_text', 'session_track_insert_text', 'session_resolve_tracked_runs', 'read_slide_notes', 'session_read_slide_notes', 'compare_slide_notes', 'session_compare_slide_notes', 'session_replace_slide_notes', 'session_replace_slide_notes_text', 'session_reorder_slides', 'inspect_slides', 'session_inspect_slides', 'session_add_comment', 'session_reply_comment', 'session_resolve_comment', 'list_word_comments', 'list_word_tracked_changes', 'session_list_word_tracked_changes', 'list_word_stories', 'search_word_body', 'session_search_word_body', 'search_word_stories', 'session_search_word_stories', 'search_word_notes', 'session_search_word_notes', 'session_list_word_stories', 'session_list_comments', 'session_replace_picture', 'session_set_slide_description', 'session_set_slide_navigation', 'compare_cells', 'session_compare_cells', 'session_sheets', 'session_read_grid', 'session_rename_table_column', 'session_edit_grid', 'session_set_grid_hyperlink', 'session_format_grid', 'session_resize_grid', 'session_freeze_panes', 'session_merge_cells', 'scan_formulas'}
                for suffix, spec, expected in (('docx', {'paragraphs':['MCP authored']}, 'MCP authored'), ('xlsx', {'sheets':{'Data':{'A1':'MCP authored'}}}, 'MCP authored'), ('pptx', {'slides':[{'title':'MCP authored'}]}, 'MCP authored')):
                    path = root / ('authored.' + suffix)
                    authored = await session.call_tool('author_file', {'spec':spec, 'output':str(path)})
                    assert not authored.isError and path.exists(), authored
                    inspected = await session.call_tool('inspect_file', {'file':str(path)})
                    assert not inspected.isError and expected in json.dumps(inspected.structuredContent)
                    refused = await session.call_tool('author_file', {'spec':spec, 'output':str(path)})
                    assert refused.isError
                structured_word = root / 'blocks.docx'
                blocks = [{'type':'heading','text':'Summary'}, {'type':'paragraph','align':'center','runs':[{'text':'Growth '},{'text':'18%','bold':True,'url':'https://example.com/report','font_size':16,'color':'236B8E'}]}, {'type':'table','header':True,'header_fill':'236B8E','header_color':'FFFFFF','column_weights':[2,1],'rows':[['Metric','Value'],['Growth',{'paragraphs':[{'runs':[{'text':'18%','bold':True},{'text':' source','url':'https://example.com/table'}]},{'text':'Year over year'}]}]]}]
                authored_blocks = await session.call_tool('author_file', {'spec':{'blocks':blocks, 'page_setup':{'size':'a4','header':{'text':'Report'},'footer':{'text':'Page','page_number':True}}}, 'output':str(structured_word)})
                assert not authored_blocks.isError and Document(structured_word).sections[0].header.paragraphs[0].text == 'Report' and Document(structured_word).sections[0].footer.paragraphs[0]._p.find(qn('w:fldSimple')) is not None and Document(structured_word).paragraphs[1].hyperlinks[0].runs[0].bold and Document(structured_word).paragraphs[1].hyperlinks[0].runs[0].font.size.pt == 16 and Document(structured_word).paragraphs[1].alignment == 1 and Document(structured_word).paragraphs[1].hyperlinks[0].address == 'https://example.com/report' and Document(structured_word).tables[0].cell(0,0)._tc.tcPr.find(qn('w:shd')).get(qn('w:fill')) == '236B8E' and Document(structured_word).tables[0].cell(1,1).paragraphs[0].hyperlinks[0].address == 'https://example.com/table' and Document(structured_word).tables[0].cell(1,1).paragraphs[1].text == 'Year over year', authored_blocks
                toc_file = root/'toc.docx'
                toc_result = await session.call_tool('author_file', {'spec':{'blocks':[{'type':'table_of_contents'},{'type':'heading','text':'Overview'}]},'output':str(toc_file)})
                assert not toc_result.isError and 'Overview' in Document(toc_file).paragraphs[0].text, toc_result
                toc_doc = Document(toc_file); heading_style = toc_doc.styles.add_style('MCP Custom Heading',WD_STYLE_TYPE.PARAGRAPH); heading_style.base_style = toc_doc.styles['Heading 2']
                toc_doc.add_paragraph('Inherited heading',style=heading_style); toc_doc.save(toc_file)
                toc_draft = root/'toc-draft'; assert not (await session.call_tool('start_session', {'directory':str(toc_draft),'source':str(toc_file)})).isError
                toc_search = await session.call_tool('session_search_word_body', {'directory':str(toc_draft),'revision':0,'query':'Overview'})
                assert toc_search.structuredContent['matches'][0]['in_field'] and not toc_search.structuredContent['matches'][0]['replace_text_path_supported'], toc_search
                toc_target = await session.call_tool('session_edit_target', {'directory':str(toc_draft),'base_revision':0,'path':'/body/p[1]'})
                assert toc_target.structuredContent['read_only_reason'] == 'word_field' and not toc_target.structuredContent['replace_text_path_supported'], toc_target
                blocked_toc = await session.call_tool('session_edit', {'directory':str(toc_draft),'base_revision':0,'path':'/body/p[1]','mode':'text','value':'Changed'})
                assert blocked_toc.isError, blocked_toc
                heading_update = await session.call_tool('session_replace_text', {'directory':str(toc_draft),'base_revision':0,'path':'/body/p[2]','find':'Overview','replacement':'Revised'})
                assert not heading_update.isError, heading_update
                toc_refresh = await session.call_tool('session_refresh_word_toc', {'directory':str(toc_draft),'base_revision':1,'path':'/body/p[1]'})
                assert not toc_refresh.isError and toc_refresh.structuredContent['page_numbers'] == 'require_field_update' and Document(toc_refresh.structuredContent['file']).paragraphs[0].text == 'Revised\n  Inherited heading', toc_refresh
                oversized_cell = root / 'oversized-cell.xlsx'
                rejected_cell = await session.call_tool('author_file', {'spec':{'sheets':{'Data':{'A1':'😀'*16384}}}, 'output':str(oversized_cell)})
                assert rejected_cell.isError and not oversized_cell.exists(), rejected_cell
                linked_book = root/'linked-book.xlsx'
                linked_result = await session.call_tool('author_file', {'spec':{'sheets':{'Sources':{'A1':{'type':'hyperlink','value':'=Source','url':'https://example.com/source'}}}},'output':str(linked_book)})
                assert not linked_result.isError and load_workbook(linked_book)['Sources']['A1'].data_type == 's' and load_workbook(linked_book)['Sources']['A1'].hyperlink.target == 'https://example.com/source', linked_result
                linked_draft = root/'linked-book-draft'; assert not (await session.call_tool('start_session', {'directory':str(linked_draft),'source':str(linked_book)})).isError
                linked_grid = await session.call_tool('session_read_grid', {'directory':str(linked_draft),'base_revision':0,'sheet':'Sources','cell_range':'A1'})
                assert linked_grid.structuredContent['hyperlink_inspection']['complete'] and linked_grid.structuredContent['rows'][0][0]['hyperlink']['target'] == 'https://example.com/source', linked_grid
                changed_link = await session.call_tool('session_set_grid_hyperlink', {'directory':str(linked_draft),'base_revision':0,'sheet':'Sources','cell':'A1','url':'https://example.org/revised','expected_sha256':linked_grid.structuredContent['snapshot_sha256']})
                assert not changed_link.isError, changed_link
                revised_link = await session.call_tool('session_read_grid', {'directory':str(linked_draft),'base_revision':1,'sheet':'Sources','cell_range':'A1'})
                assert revised_link.structuredContent['rows'][0][0]['hyperlink']['target'] == 'https://example.org/revised', revised_link
                removed_link = await session.call_tool('session_set_grid_hyperlink', {'directory':str(linked_draft),'base_revision':1,'sheet':'Sources','cell':'A1','url':None})
                assert not removed_link.isError and load_workbook(removed_link.structuredContent['file'])['Sources']['A1'].hyperlink is None, removed_link
                internal_link = await session.call_tool('session_set_grid_hyperlink', {'directory':str(linked_draft),'base_revision':2,'sheet':'Sources','cell':'A1','url':None,'location':{'sheet':'Sources','cell':'B2'}})
                assert not internal_link.isError and load_workbook(internal_link.structuredContent['file'])['Sources']['A1'].hyperlink.location == "'Sources'!B2", internal_link
                sheet_picture = root/'sheet-picture.png'; PILImage.new('RGB',(80,40),'#236B8E').save(sheet_picture)
                formatted_book = root / 'formatted.xlsx'
                book_spec = {'sheets':{'Data':{'A1':'Revenue','A2':120,'B2':'=SUM(RevenueTable[Revenue])','F1':{'type':'text','value':'=literal'}}}, 'ranges':{'Data':[{'start':'G1','values':[['Region','Value'],['North',42],['Date',{'type':'date','value':'2026-10-31'}]]}]}, 'sheet_options':{'Data':{'images':[{'path':str(sheet_picture),'anchor':'D1','width':160,'description':'Sales figure'}], 'tables':[{'name':'RevenueTable','range':'A1:A2'}], 'conditional_formats':[{'type':'cell','range':'A2','operator':'greaterThan','values':[100],'fill':'C6EFCE'}], 'list_validations':[{'range':'E1:E3','values':['Low','High']}], 'freeze_panes':'A2','column_widths':{'A':20},'formats':[{'range':'A1','bold':True,'fill':'236B8E'}], 'charts':[{'type':'column','data':'A1:A2','anchor':'C2','series_colors':['236B8E'],'legend':False,'y_min':0,'y_max':200,'show_gridlines':False,'show_values':True}], 'fit_to_page':True, 'print_options':{'paper':'a4','orientation':'landscape','area':'A1:A2','repeat_rows':'1:1','footer':{'text':'Page','page_number':True}}}}}
                authored_book = await session.call_tool('author_file', {'spec':book_spec, 'output':str(formatted_book)})
                assert not authored_book.isError and load_workbook(formatted_book)['Data']['H2'].value == 42 and load_workbook(formatted_book)['Data']['H3'].is_date and load_workbook(formatted_book)['Data']['H3'].value.isoformat() == '2026-10-31T00:00:00' and load_workbook(formatted_book)['Data']['F1'].value == '=literal' and load_workbook(formatted_book)['Data']['F1'].data_type == 's' and load_workbook(formatted_book)['Data']['A1'].font.bold and len(load_workbook(formatted_book)['Data'].conditional_formatting) == 1 and load_workbook(formatted_book)['Data'].data_validations.dataValidation[0].formula1 == '"Low,High"' and load_workbook(formatted_book)['Data'].freeze_panes == 'A2' and 'RevenueTable' in load_workbook(formatted_book)['Data'].tables and len(load_workbook(formatted_book)['Data']._images) == 1 and load_workbook(formatted_book)['Data']._images[0].anchor.pic.nvPicPr.cNvPr.descr == 'Sales figure' and len(load_workbook(formatted_book)['Data']._charts) == 1 and load_workbook(formatted_book)['Data'].print_title_rows == '$1:$1' and load_workbook(formatted_book)['Data'].oddFooter.right.text == 'Page &P', authored_book
                authored_chart = load_workbook(formatted_book)['Data']._charts[0]; assert authored_chart.dLbls.showVal and authored_chart.legend is None and authored_chart.y_axis.scaling.max == 200 and authored_chart.series[0].graphicalProperties.solidFill.srgbClr == '236B8E'
                sheet_table_draft = root/'native-xlsx-table-draft'; assert not (await session.call_tool('start_session', {'directory':str(sheet_table_draft),'source':str(formatted_book)})).isError
                sheet_table_grid = await session.call_tool('session_read_grid', {'directory':str(sheet_table_draft),'base_revision':0,'sheet':'Data','cell_range':'A1:A2'})
                assert sheet_table_grid.structuredContent['conditional_formatting']['rules'][0]['cells'] == ['A2'] and sheet_table_grid.structuredContent['conditional_formatting']['complete'], sheet_table_grid
                assert sheet_table_grid.structuredContent['rows'][0][0]['read_only_reason'] == 'table_header' and sheet_table_grid.structuredContent['rows'][1][0]['editable'], sheet_table_grid
                sheet_renamed = await session.call_tool('session_rename_table_column', {'directory':str(sheet_table_draft),'base_revision':0,'sheet':'Data','table_name':'RevenueTable','old_name':'Revenue','new_name':'Net Revenue'})
                assert not sheet_renamed.isError and sheet_renamed.structuredContent['rewritten_references'] == 1 and load_workbook(sheet_renamed.structuredContent['file'])['Data']['B2'].value == '=SUM(RevenueTable[Net Revenue])' and load_workbook(sheet_renamed.structuredContent['file'])['Data'].tables['RevenueTable'].tableColumns[0].name == 'Net Revenue', sheet_renamed
                dated_draft = root/'mcp-date-draft'; assert not (await session.call_tool('start_session', {'directory':str(dated_draft),'source':str(formatted_book)})).isError
                dated_edit = await session.call_tool('session_edit_grid', {'directory':str(dated_draft),'base_revision':0,'sheet':'Data','cell_range':'H3','changes':[{'cell':'H3','value':'2026-11-02T10:45:30.125'}]})
                assert not dated_edit.isError and load_workbook(dated_edit.structuredContent['file'])['Data']['H3'].value.isoformat() == '2026-11-02T10:45:30.125000', dated_edit
                sheet_chart_check = await session.call_tool('session_scan_chart_caches', {'directory':str(sheet_table_draft),'revision':1})
                assert not sheet_chart_check.isError and sheet_chart_check.structuredContent['mismatch_references'] >= 1, sheet_chart_check
                date_chart_file=root/'mcp-date-chart.xlsx'
                date_chart_spec={'ranges':{'Data':[{'start':'A1','values':[['Date','Revenue'],[{'type':'date','value':'2026-10-31'},100],[{'type':'date','value':'2026-11-01'},120]]}]},'sheet_options':{'Data':{'charts':[{'type':'line','data':'B1:B3','categories':'A2:A3','anchor':'D1','date_format':'mmm d'}]}}}
                date_chart_author=await session.call_tool('author_file',{'spec':date_chart_spec,'output':str(date_chart_file)});assert not date_chart_author.isError,date_chart_author
                assert load_workbook(date_chart_file)['Data']._charts[0].x_axis.numFmt.formatCode=='mmm d'
                date_chart_report=await session.call_tool('scan_chart_caches',{'file':str(date_chart_file)});assert not date_chart_report.isError and date_chart_report.structuredContent['complete'],date_chart_report
                static_chart_file=root/'mcp-static-chart.xlsx'; chart_ns='{http://schemas.openxmlformats.org/drawingml/2006/chart}'
                with zipfile.ZipFile(date_chart_file) as original,zipfile.ZipFile(static_chart_file,'w') as changed:
                    for entry in original.infolist():
                        data=original.read(entry.filename)
                        if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                            tree=etree.fromstring(data); parent=tree.find('.//'+chart_ns+'val'); reference=parent.find(chart_ns+'numRef'); cache=reference.find(chart_ns+'numCache')
                            reference.remove(cache); cache.tag=chart_ns+'numLit'; parent.replace(reference,cache); data=etree.tostring(tree)
                        changed.writestr(entry,data)
                static_chart_report=await session.call_tool('scan_chart_caches',{'file':str(static_chart_file)})
                assert not static_chart_report.isError and static_chart_report.structuredContent['literal_sources']==1,static_chart_report
                static_chart_draft=root/'mcp-static-chart-draft'; assert not (await session.call_tool('start_session',{'directory':str(static_chart_draft),'source':str(static_chart_file)})).isError
                static_part=static_chart_report.structuredContent['charts'][0]; static_ref=next(item for item in static_part['references'] if item['status']=='literal' and item['role']=='val')
                static_args={'directory':str(static_chart_draft),'base_revision':0,'part':static_part['part'],'reference':static_ref['index'],'point':1,'value':125,'expected_sha256':static_chart_report.structuredContent['snapshot_sha256']}
                assert (await session.call_tool('session_set_chart_literal_value',{**static_args,'value':True})).isError
                static_edit=await session.call_tool('session_set_chart_literal_value',static_args); assert not static_edit.isError and static_edit.structuredContent['old_value']==100,static_edit
                precision_args={**static_args,'base_revision':1,'expected_sha256':None,'value':9007199254740993}
                assert (await session.call_tool('session_set_chart_literal_value',precision_args)).isError
                precision_edit=await session.call_tool('session_set_chart_literal_value',{**precision_args,'value':9007199254740994}); assert not precision_edit.isError,precision_edit
                precision_scan=await session.call_tool('session_scan_chart_caches',{'directory':str(static_chart_draft),'revision':2})
                precision_ref=next(item for item in precision_scan.structuredContent['charts'][0]['references'] if item['kind']=='numLit')
                assert precision_ref['examples'][0]['value']=='9007199254740994',precision_ref
                static_category_file=root/'mcp-static-category.xlsx'
                with zipfile.ZipFile(static_chart_file) as original,zipfile.ZipFile(static_category_file,'w') as changed:
                    for entry in original.infolist():
                        data=original.read(entry.filename)
                        if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                            tree=etree.fromstring(data); parent=tree.find('.//'+chart_ns+'cat'); reference=parent.find(chart_ns+'numRef'); cache=reference.find(chart_ns+'numCache')
                            reference.remove(cache); cache.tag=chart_ns+'strLit'; formatting=cache.find(chart_ns+'formatCode')
                            if formatting is not None: cache.remove(formatting)
                            parent.replace(reference,cache); data=etree.tostring(tree)
                        changed.writestr(entry,data)
                static_categories=await session.call_tool('scan_chart_caches',{'file':str(static_category_file)}); category_part=static_categories.structuredContent['charts'][0]
                category_ref=next(item for item in category_part['references'] if item['status']=='literal' and item['role']=='cat')
                category_draft=root/'mcp-static-category-draft'; assert not (await session.call_tool('start_session',{'directory':str(category_draft),'source':str(static_category_file)})).isError
                category_args={'directory':str(category_draft),'base_revision':0,'part':category_part['part'],'reference':category_ref['index'],'point':1,'text':'Period One','expected_sha256':static_categories.structuredContent['snapshot_sha256']}
                assert (await session.call_tool('session_set_chart_literal_category',{**category_args,'point':True})).isError
                category_edit=await session.call_tool('session_set_chart_literal_category',category_args); assert not category_edit.isError and category_edit.structuredContent['series_updated']==1,category_edit
                category_after=await session.call_tool('session_scan_chart_caches',{'directory':str(category_draft),'revision':1})
                assert next(item for item in category_after.structuredContent['charts'][0]['references'] if item['role']=='cat')['examples'][0]['value']=='Period One',category_after
                literal_name_file=root/'mcp-static-series-name.xlsx'
                with zipfile.ZipFile(static_category_file) as original,zipfile.ZipFile(literal_name_file,'w') as changed:
                    for entry in original.infolist():
                        data=original.read(entry.filename)
                        if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                            tree=etree.fromstring(data); title=tree.find('.//'+chart_ns+'ser/'+chart_ns+'tx'); title.clear(); etree.SubElement(title,chart_ns+'v').text='Revenue'; data=etree.tostring(tree)
                        changed.writestr(entry,data)
                names=await session.call_tool('scan_chart_caches',{'file':str(literal_name_file)}); assert names.structuredContent['charts'][0]['series'][0]['name']=='Revenue',names
                name_draft=root/'mcp-static-series-draft'; assert not (await session.call_tool('start_session',{'directory':str(name_draft),'source':str(literal_name_file)})).isError
                name_args={'directory':str(name_draft),'base_revision':0,'part':names.structuredContent['charts'][0]['part'],'series':1,'text':'Sales','expected_sha256':names.structuredContent['snapshot_sha256']}
                assert (await session.call_tool('session_set_chart_literal_series_name',{**name_args,'series':True})).isError
                name_edit=await session.call_tool('session_set_chart_literal_series_name',name_args); assert not name_edit.isError and name_edit.structuredContent['old_text']=='Revenue',name_edit
                date_chart_draft=root/'mcp-date-chart-draft';assert not (await session.call_tool('start_session',{'directory':str(date_chart_draft),'source':str(date_chart_file)})).isError
                date_edit=await session.call_tool('session_edit_grid',{'directory':str(date_chart_draft),'base_revision':0,'sheet':'Data','cell_range':'A2','changes':[{'cell':'A2','value':'2026-11-02'}]});assert not date_edit.isError,date_edit
                date_report=await session.call_tool('session_scan_chart_caches',{'directory':str(date_chart_draft),'revision':1});date_cat=next(item for item in date_report.structuredContent['charts'][0]['references'] if item['role']=='cat')
                assert date_cat['status']=='mismatch' and date_cat['unverified_points']==0,date_report
                date_args={'directory':str(date_chart_draft),'base_revision':1,'part':date_report.structuredContent['charts'][0]['part'],'reference':date_cat['index']}
                assert (await session.call_tool('session_sync_chart_cache',{**date_args,'expected_sha256':'0'*64})).isError
                date_sync=await session.call_tool('session_sync_chart_cache',{**date_args,'expected_sha256':date_report.structuredContent['snapshot_sha256']});assert not date_sync.isError and date_sync.structuredContent['updated_points']==1,date_sync
                scatter_file=root/'mcp-scatter.xlsx'
                scatter_spec={'ranges':{'Data':[{'start':'A1','values':[['Time','Value'],[{'type':'datetime','value':'2026-10-31T08:00:00'},20],[{'type':'datetime','value':'2026-10-31T09:00:00'},30],[{'type':'datetime','value':'2026-10-31T15:00:00'},40]]}]},'sheet_options':{'Data':{'charts':[{'type':'scatter','data':'B1:B4','categories':'A2:A4','date_format':'hh:mm'}]}}}
                scatter_created=await session.call_tool('author_file',{'spec':scatter_spec,'output':str(scatter_file)});assert not scatter_created.isError,scatter_created
                scatter_chart=load_workbook(scatter_file)['Data']._charts[0];assert scatter_chart.__class__.__name__=='ScatterChart' and scatter_chart.x_axis.numFmt.formatCode=='hh:mm'
                scatter_scan=await session.call_tool('scan_chart_caches',{'file':str(scatter_file)});assert not scatter_scan.isError and scatter_scan.structuredContent['complete'],scatter_scan
                positioned = root / 'positioned.pptx'
                nav_file = root/'navigation.pptx'
                nav_spec = {'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':4,'height':1,'text':'Go','target_slide':2}]},{'title':'Destination'}]}
                assert not (await session.call_tool('author_file', {'spec':nav_spec,'output':str(nav_file)})).isError
                nav = await session.call_tool('inspect_slide_navigation', {'file':str(nav_file)})
                assert not nav.isError and nav.structuredContent['complete'] and nav.structuredContent['actions'][0]['target_slide'] == 2, nav
                nav_draft = root/'navigation-draft'; assert not (await session.call_tool('start_session', {'directory':str(nav_draft),'source':str(nav_file)})).isError
                nav_session = await session.call_tool('session_inspect_slide_navigation', {'directory':str(nav_draft),'revision':0})
                assert nav_session.structuredContent['actions'][0]['target_slide'] == 2, nav_session
                nav_text_file = root/'navigation-text.pptx'
                nav_text_spec = {'slides':[{'layout':'blank','elements':[{'type':'textbox','x':1,'y':1,'width':4,'height':1,'paragraphs':[{'runs':[{'text':'Source','url':'https://example.com/source'},{'text':'Details','target_slide':2}]}]}]},{'title':'Destination'}]}
                assert not (await session.call_tool('author_file', {'spec':nav_text_spec,'output':str(nav_text_file)})).isError
                nav_text = await session.call_tool('inspect_slide_navigation', {'file':str(nav_text_file)})
                assert nav_text.structuredContent['actions'][0]['kind'] == 'text_run' and nav_text.structuredContent['actions'][0]['target_url'] == 'https://example.com/source' and nav_text.structuredContent['actions'][1]['target_slide'] == 2, nav_text
                text_draft = root/'navigation-text-draft'; assert not (await session.call_tool('start_session', {'directory':str(text_draft),'source':str(nav_text_file)})).isError
                text_action = nav_text.structuredContent['actions'][1]
                text_edit = await session.call_tool('session_set_slide_navigation', {'directory':str(text_draft),'base_revision':0,'path':text_action['path'],'target_slide':1,'expected_sha256':nav_text.structuredContent['snapshot_sha256']})
                assert not text_edit.isError, text_edit
                text_updated = await session.call_tool('session_inspect_slide_navigation', {'directory':str(text_draft),'revision':1})
                assert text_updated.structuredContent['actions'][1]['target_slide'] == 1, text_updated
                nav_target = nav_session.structuredContent['actions'][0]['path']
                nav_edit = await session.call_tool('session_set_slide_navigation', {'directory':str(nav_draft),'base_revision':0,'path':nav_target,'target_slide':1,'expected_sha256':nav_session.structuredContent['snapshot_sha256']})
                assert not nav_edit.isError, nav_edit
                nav_updated = await session.call_tool('session_inspect_slide_navigation', {'directory':str(nav_draft),'revision':1})
                assert nav_updated.structuredContent['actions'][0]['target_slide'] == 1, nav_updated
                nav_removed = await session.call_tool('session_set_slide_navigation', {'directory':str(nav_draft),'base_revision':1,'path':nav_target,'target_slide':None})
                assert not nav_removed.isError, nav_removed
                slide_spec = {'slide_size':{'width':13.333,'height':7.5}, 'slides':[{'layout':'blank','notes':'Presenter context\nNext step','elements':[{'type':'textbox','x':1,'y':1,'width':5,'height':1,'paragraphs':[{'runs':[{'text':'Positioned '},{'text':'title','bold':True,'color':'236B8E'}]}],'font_size':32,'vertical_align':'middle','auto_fit':'shrink','margins':{'left':0.2}}, {'type':'table','x':1,'y':2,'width':5,'height':1,'rows':[['Metric','Value'],['Growth',{'paragraphs':[{'runs':[{'text':'18%','bold':True},{'text':' source','url':'https://example.com/chart'}]},{'text':'Year over year'}]}]],'header':True}, {'type':'chart','chart_type':'column','description':'Quarterly revenue chart','value_axis_min':0,'value_axis_max':150,'x':1,'y':3,'width':5,'height':2,'categories':['Q1','Q2'],'series':[{'name':'Revenue','values':[100,120]}]}, {'type':'line','x':1,'y':6,'end_x':6,'end_y':6,'arrow':'end','color':'236B8E'}, {'type':'shape','id':'first','shape_kind':'rounded_rectangle','x':7,'y':1,'width':2,'height':1,'fill':'236B8E','text':'Start','color':'FFFFFF','font_size':20}, {'type':'shape','id':'last','shape_kind':'ellipse','x':10,'y':1,'width':2,'height':1,'fill':'65A68D','text':'Done'}, {'type':'connector','start':{'shape':'first','side':'right'},'end':{'shape':'last','side':'left'}}]}]}
                authored_slide = await session.call_tool('author_file', {'spec':slide_spec, 'output':str(positioned)})
                assert not authored_slide.isError and Presentation(positioned).slides[0].notes_slide.notes_text_frame.text == 'Presenter context\nNext step' and Presentation(positioned).slides[0].shapes[0].text == 'Positioned title' and Presentation(positioned).slides[0].shapes[0].text_frame.paragraphs[0].runs[1].font.bold and Presentation(positioned).slides[0].shapes[0].text_frame.auto_size == 2 and Presentation(positioned).slides[0].shapes[1].table.cell(1,1).text_frame.paragraphs[0].runs[1].hyperlink.address == 'https://example.com/chart' and Presentation(positioned).slides[0].shapes[1].table.cell(1,1).text_frame.paragraphs[1].text == 'Year over year' and tuple(Presentation(positioned).slides[0].shapes[2].chart.series[0].values) == (100,120), authored_slide
                assert Presentation(positioned).slides[0].shapes[2].chart.value_axis.minimum_scale == 0 and Presentation(positioned).slides[0].shapes[2].chart.value_axis.maximum_scale == 150
                assert Presentation(positioned).slides[0].shapes[3]._element.spPr.ln.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd').get('type') == 'triangle'
                assert Presentation(positioned).slides[0].shapes[4].text == 'Start'
                assert Presentation(positioned).slides[0].shapes[6]._element.nvCxnSpPr.cNvCxnSpPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}endCxn').get('idx') == '2'
                chart_inventory = await session.call_tool('inspect_slide_charts', {'file':str(positioned)})
                assert not chart_inventory.isError and chart_inventory.structuredContent['charts'][0]['series'][0]['values'] == [100,120], chart_inventory
                assert chart_inventory.structuredContent['charts'][0]['reconciliation']['status'] == 'match' and chart_inventory.structuredContent['charts'][0]['description'] == 'Quarterly revenue chart', chart_inventory
                literal_slide = root/'literal-slide.pptx'; chart_part = chart_inventory.structuredContent['charts'][0]['chart_part'].lstrip('/')
                chart_ns = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
                with zipfile.ZipFile(positioned) as original, zipfile.ZipFile(literal_slide,'w') as changed:
                    for entry in original.infolist():
                        data=original.read(entry.filename)
                        if entry.filename == chart_part:
                            tree=etree.fromstring(data); ser=tree.find('.//'+chart_ns+'ser'); title=ser.find(chart_ns+'tx'); title.clear(); etree.SubElement(title,chart_ns+'v').text='Revenue'
                            for role,ref,cache,literal in [('cat','strRef','strCache','strLit'),('val','numRef','numCache','numLit')]:
                                parent=ser.find(chart_ns+role); old=parent.find(chart_ns+ref); data_node=old.find(chart_ns+cache); old.remove(data_node); data_node.tag=chart_ns+literal; parent.replace(old,data_node)
                            external=tree.find(chart_ns+'externalData')
                            if external is not None: tree.remove(external)
                            data=etree.tostring(tree)
                        changed.writestr(entry,data)
                literal_result=await session.call_tool('inspect_slide_charts', {'file':str(literal_slide)})
                assert not literal_result.isError and literal_result.structuredContent['complete'] and literal_result.structuredContent['charts'][0]['series'][0]['references']['val']['status']=='literal' and literal_result.structuredContent['charts'][0]['series'][0]['values']==[100,120], literal_result
                literal_draft=root/'literal-slide-draft'; assert not (await session.call_tool('start_session', {'directory':str(literal_draft),'source':str(literal_slide)})).isError
                literal_args={'directory':str(literal_draft),'base_revision':0,'part':'/'+chart_part,'series':1,'point':2,'value':125,'expected_sha256':literal_result.structuredContent['snapshot_sha256']}
                assert (await session.call_tool('session_set_slide_chart_literal_value', {**literal_args,'value':True})).isError
                literal_change=await session.call_tool('session_set_slide_chart_literal_value', literal_args); assert not literal_change.isError, literal_change
                literal_after=await session.call_tool('session_inspect_slide_charts', {'directory':str(literal_draft),'revision':1})
                assert literal_after.structuredContent['charts'][0]['series'][0]['values']==[100,125], literal_after
                literal_text=await session.call_tool('session_set_slide_chart_literal_text', {'directory':str(literal_draft),'base_revision':1,'part':'/'+chart_part,'kind':'category','point':1,'text':'First quarter','expected_sha256':literal_after.structuredContent['snapshot_sha256']})
                assert not literal_text.isError, literal_text
                literal_after_text=await session.call_tool('session_inspect_slide_charts', {'directory':str(literal_draft),'revision':2})
                assert literal_after_text.structuredContent['charts'][0]['categories']==['First quarter','Q2'], literal_after_text
                slide_precision={'directory':str(literal_draft),'base_revision':2,'part':'/'+chart_part,'series':1,'point':1,'value':9007199254740993}
                assert (await session.call_tool('session_set_slide_chart_literal_value',slide_precision)).isError
                slide_precise=await session.call_tool('session_set_slide_chart_literal_value',{**slide_precision,'value':9007199254740994}); assert not slide_precise.isError,slide_precise
                with zipfile.ZipFile(slide_precise.structuredContent['output']) as archive:
                    tree=etree.fromstring(archive.read(chart_part)); assert tree.find('.//'+chart_ns+'val/'+chart_ns+'numLit/'+chart_ns+'pt/'+chart_ns+'v').text=='9007199254740994'
                axis_inventory = chart_inventory.structuredContent['charts'][0]['axis_inventory']; axis = next(item for item in axis_inventory['axes'] if item['type'] == 'valAx')
                assert axis_inventory['complete'] and axis['minimum'] == 0 and axis['maximum'] == 150, axis_inventory
                color_draft=root/'chart-color-draft'; assert not (await session.call_tool('start_session', {'directory':str(color_draft),'source':str(positioned)})).isError
                color_change=await session.call_tool('session_set_slide_chart_text_color', {'directory':str(color_draft),'base_revision':0,'part':'/'+chart_part,'color':'AABBCC','expected_sha256':chart_inventory.structuredContent['snapshot_sha256']})
                assert not color_change.isError and str(Presentation(color_change.structuredContent['output']).slides[0].shapes[2].chart.value_axis.tick_labels.font.color.rgb)=='AABBCC', color_change
                axis_draft = root/'chart-axis-draft'; assert not (await session.call_tool('start_session', {'directory':str(axis_draft),'source':str(positioned)})).isError
                assert (await session.call_tool('session_set_slide_chart_axis_bounds', {'directory':str(axis_draft),'base_revision':0,'part':chart_inventory.structuredContent['charts'][0]['chart_part'],'axis_id':axis['id'],'minimum':True,'maximum':200})).isError
                axis_changed = await session.call_tool('session_set_slide_chart_axis_bounds', {'directory':str(axis_draft),'base_revision':0,'part':chart_inventory.structuredContent['charts'][0]['chart_part'],'axis_id':axis['id'],'minimum':None,'maximum':110,'expected_sha256':chart_inventory.structuredContent['snapshot_sha256']})
                assert not axis_changed.isError, axis_changed
                axis_after = await session.call_tool('session_inspect_slide_charts', {'directory':str(axis_draft),'revision':1})
                axis_result = next(item for item in axis_after.structuredContent['charts'][0]['axis_inventory']['axes'] if item['id'] == axis['id'])
                assert axis_result['minimum'] is None and axis_result['maximum'] == 110, axis_result
                assert axis_after.structuredContent['charts'][0]['axis_range_candidates']['count'] == 1, axis_after
                description_draft = root/'description-draft'; assert not (await session.call_tool('start_session', {'directory':str(description_draft),'source':str(positioned)})).isError
                chart_target = chart_inventory.structuredContent['charts'][0]
                described_chart = await session.call_tool('session_set_slide_description', {'directory':str(description_draft),'base_revision':0,'path':chart_target['path'],'description':'Updated revenue chart','expected_sha256':chart_inventory.structuredContent['snapshot_sha256']})
                assert not described_chart.isError, described_chart
                checked_description = await session.call_tool('session_inspect_slide_charts', {'directory':str(description_draft),'revision':1})
                assert checked_description.structuredContent['charts'][0]['description'] == 'Updated revenue chart', checked_description
                chart_draft = root/'chart-inventory-draft'; assert not (await session.call_tool('start_session', {'directory':str(chart_draft),'source':str(positioned)})).isError
                table_shape = Presentation(positioned).slides[0].shapes[1]
                table_path = f'/slide[1]/table[@id={table_shape.shape_id}]/tr[2]/tc[2]/paragraph[2]'
                table_target = await session.call_tool('session_edit_target', {'directory':str(chart_draft),'base_revision':0,'path':table_path})
                assert not table_target.isError and table_target.structuredContent['value']=='Year over year' and table_target.structuredContent['replace_only'], table_target
                link_draft = root/'mcp-slide-link-draft'; assert not (await session.call_tool('start_session', {'directory':str(link_draft),'source':str(positioned)})).isError
                link_path = f'/slide[1]/table[@id={table_shape.shape_id}]/tr[2]/tc[2]/paragraph[1]'
                link_target = await session.call_tool('session_edit_target', {'directory':str(link_draft),'base_revision':0,'path':link_path})
                assert not link_target.isError and link_target.structuredContent['replace_text_path_supported'], link_target
                link_edit = await session.call_tool('session_replace_text', {'directory':str(link_draft),'base_revision':0,'path':link_path,'find':'source','replacement':'reference'})
                link_run = Presentation(link_edit.structuredContent['file']).slides[0].shapes[1].table.cell(1,1).text_frame.paragraphs[0].runs[1]
                assert not link_edit.isError and link_run.text==' reference' and link_run.hyperlink.address=='https://example.com/chart', link_edit
                reorder_file = root/'mcp-reorder.pptx'; reorder_draft = root/'mcp-reorder-draft'
                assert not (await session.call_tool('author_file', {'spec':{'slides':[{'title':'First','notes':'First notes'},{'title':'Second','notes':'Second notes'}]},'output':str(reorder_file)})).isError
                assert not (await session.call_tool('start_session', {'directory':str(reorder_draft),'source':str(reorder_file)})).isError
                slide_list = await session.call_tool('session_inspect_slides', {'directory':str(reorder_draft),'revision':0})
                assert not slide_list.isError and [slide['title'] for slide in slide_list.structuredContent['slides']] == ['First','Second'] and slide_list.structuredContent['section_status'] == 'none', slide_list
                bad_order = await session.call_tool('session_reorder_slides', {'directory':str(reorder_draft),'base_revision':0,'order':[True,2]}); assert bad_order.isError
                reordered = await session.call_tool('session_reorder_slides', {'directory':str(reorder_draft),'base_revision':0,'order':[2,1]})
                assert not reordered.isError and Presentation(reordered.structuredContent['file']).slides[0].shapes.title.text == 'Second' and Presentation(reordered.structuredContent['file']).slides[0].notes_slide.notes_text_frame.text == 'Second notes', reordered
                notes_link_file=root/'mcp-notes-link.pptx'; notes_link_deck=Presentation(); notes_slide=notes_link_deck.slides.add_slide(notes_link_deck.slide_layouts[1]); notes_slide.shapes.title.text='Agenda'
                notes_run=notes_slide.notes_slide.notes_text_frame.paragraphs[0].add_run(); notes_run.text='Linked'; notes_run.hyperlink.address='https://example.com/notes'; notes_link_deck.save(notes_link_file)
                notes_link_draft=root/'mcp-notes-link-draft'; assert not (await session.call_tool('start_session',{'directory':str(notes_link_draft),'source':str(notes_link_file)})).isError
                notes_link_edit=await session.call_tool('session_replace_slide_notes_text',{'directory':str(notes_link_draft),'base_revision':0,'slide':1,'paragraph':1,'find':'Linked','replacement':'Reference'})
                assert not notes_link_edit.isError, notes_link_edit
                notes_after=Presentation(notes_link_edit.structuredContent['file']).slides[0].notes_slide.notes_text_frame.paragraphs[0].runs[0]
                assert notes_after.text=='Reference' and notes_after.hyperlink.address=='https://example.com/notes'
                note_target=await session.call_tool('session_edit_target',{'directory':str(notes_link_draft),'base_revision':1,'path':'/slide[1]/notes/paragraph[1]'})
                assert not note_target.isError and note_target.structuredContent['value']=='Reference' and note_target.structuredContent['replace_only'], note_target
                notes_batch=await session.call_tool('session_replace_text_batch',{'directory':str(notes_link_draft),'base_revision':1,'changes':[{'path':'/slide[1]/notes/paragraph[1]','find':'Reference','replacement':'Final'}, {'path':f'/slide[1]/shape[@id={notes_slide.shapes.title.shape_id}]/paragraph[1]','find':'Agenda','replacement':'Summary'}]})
                assert not notes_batch.isError and notes_batch.structuredContent['revision']==2, notes_batch
                notes_batch_deck=Presentation(notes_batch.structuredContent['file']); assert notes_batch_deck.slides[0].shapes.title.text=='Summary' and notes_batch_deck.slides[0].notes_slide.notes_text_frame.paragraphs[0].runs[0].hyperlink.address=='https://example.com/notes'
                session_inventory = await session.call_tool('session_inspect_slide_charts', {'directory':str(chart_draft),'revision':0})
                assert not session_inventory.isError and session_inventory.structuredContent['snapshot_sha256'] == chart_inventory.structuredContent['snapshot_sha256'], session_inventory
                mismatched = root/'mismatched.pptx'
                with zipfile.ZipFile(positioned) as src, zipfile.ZipFile(mismatched, 'w') as dst:
                    for entry in src.infolist():
                        data = src.read(entry.filename)
                        if entry.filename == 'ppt/charts/chart1.xml':
                            tree = etree.fromstring(data); ns = {'c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
                            tree.xpath('.//c:val/c:numRef/c:numCache/c:pt/c:v', namespaces=ns)[0].text = '999'
                            data = etree.tostring(tree)
                        dst.writestr(entry, data)
                mismatch_draft = root/'mismatch-draft'
                assert not (await session.call_tool('start_session', {'directory':str(mismatch_draft),'source':str(mismatched)})).isError
                mismatch_inspect = await session.call_tool('session_inspect_slide_charts', {'directory':str(mismatch_draft),'revision':0})
                mismatch_chart = mismatch_inspect.structuredContent['charts'][0]
                ref = next(item['index'] for item in mismatch_chart['reconciliation']['references'] if item['status'] == 'mismatch')
                slide_sync_args = {'directory':str(mismatch_draft),'base_revision':0,'part':mismatch_chart['chart_part'],'reference':ref}
                assert (await session.call_tool('session_sync_slide_chart_cache',{**slide_sync_args,'expected_sha256':'0'*64})).isError
                repaired = await session.call_tool('session_sync_slide_chart_cache', {**slide_sync_args,'expected_sha256':mismatch_inspect.structuredContent['snapshot_sha256']})
                assert not repaired.isError and repaired.structuredContent['updated_points'] == 1, repaired
                verified = await session.call_tool('session_inspect_slide_charts', {'directory':str(mismatch_draft),'revision':1})
                assert verified.structuredContent['charts'][0]['reconciliation']['status'] == 'match', verified
                chart_grid = await session.call_tool('session_read_slide_chart_grid', {'directory':str(chart_draft),'revision':0,'part':chart_inventory.structuredContent['charts'][0]['chart_part'],'sheet':'Sheet1','cell_range':'B2'})
                assert not chart_grid.isError and chart_grid.structuredContent['rows'][0][0]['value'] == 100, chart_grid
                chart_edit = await session.call_tool('session_edit_slide_chart_grid', {'directory':str(chart_draft),'base_revision':0,'part':chart_inventory.structuredContent['charts'][0]['chart_part'],'sheet':'Sheet1','cell_range':'B2','changes':[{'cell':'B2','value':'125'}], 'sync_caches':True})
                assert not chart_edit.isError and chart_edit.structuredContent['revision'] == 1, chart_edit
                chart_changed = await session.call_tool('session_inspect_slide_charts', {'directory':str(chart_draft),'revision':1})
                assert chart_changed.structuredContent['charts'][0]['reconciliation']['status'] == 'match' and chart_edit.structuredContent['synchronized_references'], chart_changed
                blank_slide = root/'blank-chart.pptx'
                blank_spec = {'slides':[{'layout':'blank','elements':[{'type':'chart','chart_type':'pie','show_values':True,'x':1,'y':1,'width':5,'height':3,'categories':['Q1','Q2'],'series':[{'name':'Revenue','values':[100,None]}]}]}]}
                assert not (await session.call_tool('author_file', {'spec':blank_spec,'output':str(blank_slide)})).isError
                blank_draft = root/'blank-chart-draft'; assert not (await session.call_tool('start_session', {'directory':str(blank_draft),'source':str(blank_slide)})).isError
                blank_scan = await session.call_tool('session_inspect_slide_charts', {'directory':str(blank_draft),'revision':0})
                blank_chart = blank_scan.structuredContent['charts'][0]; assert blank_chart['reconciliation']['status'] == 'match', blank_scan
                blank_fill = await session.call_tool('session_edit_slide_chart_grid', {'directory':str(blank_draft),'base_revision':0,'part':blank_chart['chart_part'],'sheet':'Sheet1','cell_range':'B3','changes':[{'cell':'B3','value':'125'}],'sync_caches':True})
                assert not blank_fill.isError and blank_fill.structuredContent['synchronized_references'], blank_fill
                blank_clear = await session.call_tool('session_edit_slide_chart_grid', {'directory':str(blank_draft),'base_revision':1,'part':blank_chart['chart_part'],'sheet':'Sheet1','cell_range':'B2','changes':[{'cell':'B2','value':''}],'sync_caches':True})
                assert not blank_clear.isError and blank_clear.structuredContent['synchronized_references'], blank_clear
                blank_check = await session.call_tool('session_inspect_slide_charts', {'directory':str(blank_draft),'revision':2})
                assert blank_check.structuredContent['charts'][0]['series'][0]['values'] == [None,125], blank_check
                diagnostics = await session.call_tool('office_doctor', {})
                assert not diagnostics.isError and diagnostics.structuredContent['capabilities']['mcp_server'] is True, diagnostics
                word_source = root / 'search.docx'; search_doc = Document(); search_doc.add_paragraph('find needle'); search_doc.save(word_source)
                batch_draft = root / 'text-batch-draft'
                assert not (await session.call_tool('start_session', {'directory': str(batch_draft), 'source': str(word_source)})).isError
                external = await session.call_tool('inspect_external_relationships', {'file': str(word_source)})
                scoped_external = await session.call_tool('session_inspect_external_relationships', {'directory': str(batch_draft), 'revision': 0})
                assert not external.isError and external.structuredContent['complete'] and external.structuredContent['external_count'] == 0
                assert not scoped_external.isError and scoped_external.structuredContent['revision'] == 0 and scoped_external.structuredContent['snapshot_sha256'] == external.structuredContent['snapshot_sha256']
                batch = await session.call_tool('session_replace_text_batch', {'directory': str(batch_draft), 'base_revision': 0, 'changes': [{'path':'/body/p[1]','find':'find','replacement':'locate'}, {'path':'/body/p[1]','find':'needle','replacement':'target'}]})
                assert not batch.isError and batch.structuredContent['count'] == 2 and Document(batch_draft / 'revision-000001.docx').paragraphs[0].text == 'locate target', batch
                tracked = await session.call_tool('list_word_tracked_changes', {'file': str(word_source)})
                assert not tracked.isError and tracked.structuredContent['records_scanned'] == 0, tracked
                track_draft = root / 'tracked-draft'; tracked_started = await session.call_tool('start_session', {'directory': str(track_draft), 'source': str(word_source)})
                assert not tracked_started.isError, tracked_started
                tracked_edit = await session.call_tool('session_track_replace_text', {'directory': str(track_draft), 'base_revision': 0, 'path': '/body/p[1]', 'find': 'needle', 'replacement': 'thread', 'author': 'Reviewer'})
                assert not tracked_edit.isError and tracked_edit.structuredContent['revision'] == 1, tracked_edit
                tracked_view = await session.call_tool('session_list_word_tracked_changes', {'directory': str(track_draft), 'revision': 1})
                assert not tracked_view.isError and tracked_view.structuredContent['counts'] == {'del': 1, 'ins': 1}, tracked_view
                record_ids = [record['id'] for record in tracked_view.structuredContent['records']]
                assert (await session.call_tool('session_resolve_tracked_runs', {'directory':str(track_draft),'base_revision':1,'part':'word/document.xml','ids':record_ids,'accept':True,'expected_sha256':'0'*64})).isError
                resolved = await session.call_tool('session_resolve_tracked_runs', {'directory': str(track_draft), 'base_revision': 1, 'part': 'word/document.xml', 'ids': record_ids, 'accept': True, 'expected_sha256':tracked_view.structuredContent['snapshot_sha256']})
                assert not resolved.isError and Document(track_draft / 'revision-000002.docx').paragraphs[0].text == 'find thread', resolved
                insert_draft = root / 'insert-draft'
                assert not (await session.call_tool('start_session', {'directory': str(insert_draft), 'source': str(word_source)})).isError
                inserted = await session.call_tool('session_track_insert_text', {'directory': str(insert_draft), 'base_revision': 0, 'path': '/body/p[1]', 'anchor': 'needle', 'text': 'new ', 'position': 'before', 'author': 'Reviewer'})
                assert not inserted.isError and inserted.structuredContent['revision'] == 1, inserted
                inserted_view = await session.call_tool('session_list_word_tracked_changes', {'directory': str(insert_draft), 'revision': 1})
                assert inserted_view.structuredContent['records'][0]['id'] == inserted.structuredContent['id']
                header_source = root / 'tracked-header.docx'; header_doc = Document(); header_doc.sections[0].header.paragraphs[0].text = 'header anchor'; header_doc.save(header_source)
                header_draft = root / 'tracked-header-draft'
                assert not (await session.call_tool('start_session', {'directory': str(header_draft), 'source': str(header_source)})).isError
                stories = await session.call_tool('session_list_word_stories', {'directory': str(header_draft), 'revision': 0})
                story = stories.structuredContent['stories'][0]
                header_hit = await session.call_tool('session_search_word_stories', {'directory': str(header_draft), 'revision': 0, 'query': 'anchor'})
                assert not header_hit.isError and header_hit.structuredContent['matches'][0]['path'] == story['paragraphs'][0]['path'], header_hit
                direct_hit = await session.call_tool('search_word_stories', {'file': str(header_source), 'query': 'anchor'})
                assert not direct_hit.isError and direct_hit.structuredContent['matches'][0]['part'] == story['part'], direct_hit
                header_edit = await session.call_tool('session_track_insert_text', {'directory': str(header_draft), 'base_revision': 0, 'path': story['paragraphs'][0]['path'], 'anchor': 'anchor', 'text': 'new ', 'position': 'before', 'author': 'Reviewer'})
                assert not header_edit.isError and header_edit.structuredContent['part'] == story['part'], header_edit
                header_resolved = await session.call_tool('session_resolve_tracked_runs', {'directory': str(header_draft), 'base_revision': 1, 'part': story['part'], 'ids': [header_edit.structuredContent['id']], 'accept': True})
                assert not header_resolved.isError and Document(header_draft / 'revision-000002.docx').sections[0].header.paragraphs[0].text == 'header new anchor', header_resolved
                word_hit = await session.call_tool('search_word_body', {'file': str(word_source), 'query': 'needle'})
                assert not word_hit.isError and word_hit.structuredContent['matches'][0]['path'] == '/body/p[1]', word_hit
                schema_catalog = await session.call_tool('office_schema', {'format': 'xlsx', 'operation': 'add', 'query': 'chart'})
                assert not schema_catalog.isError and any(item['element'] == 'chart' for item in schema_catalog.structuredContent['elements']), schema_catalog
                chart_schema = await session.call_tool('office_schema', {'format': 'xlsx', 'element': 'chart', 'operation': 'add', 'query': 'datarange'})
                assert not chart_schema.isError and 'dataRange' in chart_schema.structuredContent['schema']['properties'], chart_schema
                bad_schema = await session.call_tool('office_schema', {'format': 'xlsx', 'element': '--help'})
                assert bad_schema.isError, bad_schema
                original_image = root / 'mcp-original.png'; replacement_image = root / 'mcp-new.png'
                PILImage.new('RGB', (20, 20), 'red').save(original_image)
                PILImage.new('RGB', (20, 20), 'blue').save(replacement_image)
                deck = Presentation(); slide = deck.slides.add_slide(deck.slide_layouts[6])
                picture = slide.shapes.add_picture(str(original_image), Inches(1), Inches(1), Inches(1), Inches(1))
                picture_source = root / 'mcp-picture.pptx'; deck.save(picture_source)
                picture_draft = root / 'mcp-picture-draft'
                slide_search = await session.call_tool('search_slide_text', {'file': str(picture_source), 'query': 'absent'})
                assert not slide_search.isError and slide_search.structuredContent['scan_complete'], slide_search
                started_picture = await session.call_tool('start_session', {'directory': str(picture_draft), 'source': str(picture_source)})
                assert not started_picture.isError, started_picture
                picture_inventory = await session.call_tool('session_inspect_slides', {'directory':str(picture_draft),'revision':0})
                picture_args = {'directory':str(picture_draft),'base_revision':0,'path':f'/slide[1]/picture[@id={picture.shape_id}]','image_file':str(replacement_image)}
                assert (await session.call_tool('session_replace_picture', {**picture_args,'expected_sha256':'0'*64})).isError
                changed_picture = await session.call_tool('session_replace_picture', {**picture_args,'expected_sha256':picture_inventory.structuredContent['snapshot_sha256']})
                assert not changed_picture.isError and Presentation(picture_draft / 'revision-000001.pptx').slides[0].shapes[0].image.blob == replacement_image.read_bytes(), changed_picture
                initial_notes = await session.call_tool('session_read_slide_notes', {'directory':str(picture_draft),'revision':1,'slide':1})
                assert (await session.call_tool('session_replace_slide_notes', {'directory':str(picture_draft),'base_revision':1,'slide':1,'text':'bad','expected_sha256':'0'*64})).isError
                changed_notes = await session.call_tool('session_replace_slide_notes', {'directory': str(picture_draft), 'base_revision': 1, 'slide': 1, 'text': 'Talk track', 'expected_sha256':initial_notes.structuredContent['snapshot_sha256']})
                assert not changed_notes.isError and changed_notes.structuredContent['revision'] == 2, changed_notes
                read_notes = await session.call_tool('session_read_slide_notes', {'directory': str(picture_draft), 'revision': 2, 'slide': 1})
                assert not read_notes.isError and read_notes.structuredContent['text'] == 'Talk track', read_notes
                note_edit = await session.call_tool('session_replace_slide_notes_text', {'directory': str(picture_draft), 'base_revision': 2, 'slide': 1, 'paragraph': 1, 'find': 'track', 'replacement': 'notes', 'expected_sha256':read_notes.structuredContent['snapshot_sha256']})
                assert not note_edit.isError and note_edit.structuredContent['revision'] == 3, note_edit
                edited_notes = await session.call_tool('session_read_slide_notes', {'directory': str(picture_draft), 'revision': 3, 'slide': 1})
                assert not edited_notes.isError and edited_notes.structuredContent['text'] == 'Talk notes', edited_notes
                notes_diff = await session.call_tool('session_compare_slide_notes', {'directory': str(picture_draft), 'before_revision': 2, 'after_revision': 3, 'before_slide': 1, 'after_slide': 1})
                assert not notes_diff.isError and notes_diff.structuredContent['text_changed'] and '+Talk notes' in notes_diff.structuredContent['diff'], notes_diff
                file_notes_diff = await session.call_tool('compare_slide_notes', {'before': str(picture_source), 'after': str(picture_draft / 'revision-000003.pptx'), 'before_slide': 1, 'after_slide': 1})
                assert not file_notes_diff.isError and file_notes_diff.structuredContent['text_changed'], file_notes_diff
                empty_notes = await session.call_tool('read_slide_notes', {'file': str(picture_source), 'slide': 1})
                assert not empty_notes.isError and not empty_notes.structuredContent['has_notes_slide'], empty_notes
                output = root / 'report.docx'
                operations = [{'command': 'add', 'parent': '/body', 'type': 'paragraph', 'props': {'text': 'MCP works'}}]
                created = await session.call_tool('apply_batch', {'output': str(output), 'operations': operations})
                assert not created.isError and output.exists(), created
                dumped = await session.call_tool('dump_office_subtree', {'file': str(output), 'path': '/body/p[1]'})
                assert not dumped.isError and dumped.structuredContent['operations'][0]['command'] == 'meta', dumped
                replay_draft = root / 'replay-draft'; replay_start = await session.call_tool('start_session', {'directory': str(replay_draft), 'format': 'docx'})
                assert not replay_start.isError, replay_start
                replay = await session.call_tool('session_apply', {'directory': str(replay_draft), 'base_revision': 0, 'operations': dumped.structuredContent['operations']})
                assert not replay.isError and any(p.text == 'MCP works' for p in Document(replay_draft / 'revision-000001.docx').paragraphs), replay
                replay_dump = await session.call_tool('session_dump_office_subtree', {'directory': str(replay_draft), 'revision': 1, 'path': '/body/p[1]'})
                assert not replay_dump.isError and replay_dump.structuredContent['revision'] == 1, replay_dump
                readback = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get', 'target': '/body/p[1]'})
                assert not readback.isError and 'MCP works' in str(readback), readback
                revised = root / 'revised.docx'
                edit = await session.call_tool('apply_batch', {'source': str(output), 'output': str(revised), 'operations': [{'command': 'set', 'path': '/body/p[1]', 'props': {'text': 'Revised'}}]})
                assert not edit.isError, edit
                compared = await session.call_tool('compare_files', {'before': str(output), 'after': str(revised)})
                assert not compared.isError and 'Revised' in str(compared.structuredContent['text_diff']), compared
                audited = await session.call_tool('audit_file', {'file': str(revised)})
                assert not audited.isError and audited.structuredContent['validation']['result']['success'] is True, audited
                word_draft = root / 'word-draft'
                word_started = await session.call_tool('start_session', {'directory': str(word_draft), 'source': str(output)})
                assert not word_started.isError, word_started
                word_edit = await session.call_tool('session_replace_text', {'directory': str(word_draft), 'base_revision': 0, 'path': '/body/p[1]', 'find': 'MCP works', 'replacement': 'MCP changed'})
                assert not word_edit.isError and word_edit.structuredContent['revision'] == 1, word_edit
                table_source = root / 'table.docx'; table_doc = Document()
                table_doc.add_table(rows=1, cols=1).cell(0, 0).text = 'table content'; table_doc.save(table_source)
                table_draft = root / 'table-draft'
                table_started = await session.call_tool('start_session', {'directory': str(table_draft), 'source': str(table_source)})
                assert not table_started.isError, table_started
                table_edit = await session.call_tool('session_replace_text', {'directory': str(table_draft), 'base_revision': 0, 'path': '/body/tbl[1]/tr[1]/tc[1]/p[1]', 'find': 'content', 'replacement': 'result'})
                assert not table_edit.isError and Document(table_draft / 'revision-000001.docx').tables[0].cell(0, 0).text == 'table result', table_edit
                slide_source = root / 'slides.pptx'; deck = Presentation(); slide = deck.slides.add_slide(deck.slide_layouts[6])
                slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'slide content'
                slide.shapes.add_table(1, 1, Inches(1), Inches(2), Inches(4), Inches(1)).table.cell(0, 0).text = 'table content'; deck.save(slide_source)
                layout_check = await session.call_tool('inspect_slide_layout', {'file': str(slide_source)})
                assert not layout_check.isError and layout_check.structuredContent['complete'], layout_check
                slide_draft = root / 'slide-draft'
                slide_started = await session.call_tool('start_session', {'directory': str(slide_draft), 'source': str(slide_source)})
                assert not slide_started.isError, slide_started
                layout_revision = await session.call_tool('session_inspect_slide_layout', {'directory': str(slide_draft), 'revision': 0})
                assert not layout_revision.isError and layout_revision.structuredContent['revision'] == 0, layout_revision
                slide_text = await session.call_tool('inspect_slide_text', {'file': str(slide_source)})
                assert not slide_text.isError and slide_text.structuredContent['mapping_valid'] and slide_text.structuredContent['text_shapes_checked'] == 1 and slide_text.structuredContent['table_cells_checked'] == 1, slide_text
                slide_text_revision = await session.call_tool('session_inspect_slide_text', {'directory': str(slide_draft), 'revision': 0})
                assert not slide_text_revision.isError and slide_text_revision.structuredContent['revision'] == 0, slide_text_revision
                group_source = root / 'group-text.pptx'; group_deck = Presentation(); group_slide = group_deck.slides.add_slide(group_deck.slide_layouts[6]); group = group_slide.shapes.add_group_shape()
                group.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'group text'; group_deck.save(group_source)
                group_check = await session.call_tool('inspect_slide_text', {'file': str(group_source)})
                assert not group_check.isError and group_check.structuredContent['complete'] and group_check.structuredContent['text_shapes_checked'] == 1, group_check
                slide_edit = await session.call_tool('session_replace_text', {'directory': str(slide_draft), 'base_revision': 0, 'path': '/slide[1]/shape[1]/paragraph[1]', 'find': 'content', 'replacement': 'result'})
                assert not slide_edit.isError and Presentation(slide_draft / 'revision-000001.pptx').slides[0].shapes[0].text == 'slide result', slide_edit
                historic_layout = await session.call_tool('session_inspect_slide_layout', {'directory': str(slide_draft), 'revision': 0})
                assert not historic_layout.isError and historic_layout.structuredContent['revision'] == 0, historic_layout
                cell_edit = await session.call_tool('session_replace_text', {'directory': str(slide_draft), 'base_revision': 1, 'path': '/slide[1]/table[1]/tr[1]/tc[1]', 'find': 'content', 'replacement': 'result'})
                assert not cell_edit.isError and Presentation(slide_draft / 'revision-000002.pptx').slides[0].shapes[1].table.cell(0, 0).text == 'table result', cell_edit
                comment_source = root / 'comment.docx'; comment_doc = Document(); comment_doc.add_paragraph('Needs review'); comment_doc.save(comment_source)
                comment_draft = root / 'comment-draft'; comment_started = await session.call_tool('start_session', {'directory': str(comment_draft), 'source': str(comment_source)})
                assert not comment_started.isError, comment_started
                comment_result = await session.call_tool('session_add_comment', {'directory': str(comment_draft), 'base_revision': 0, 'path': '/body/p[1]', 'text': 'Review this', 'author': 'Reviewer', 'anchor': 'review'})
                assert not comment_result.isError and next(iter(Document(comment_draft / 'revision-000001.docx').comments)).text == 'Review this', comment_result
                listed_comments = await session.call_tool('session_list_comments', {'directory': str(comment_draft), 'revision': 1})
                assert not listed_comments.isError and listed_comments.structuredContent['comments'][0]['anchor_text'] == 'review', listed_comments
                header_source = root / 'header.docx'; header_doc = Document(); header_doc.sections[0].header.paragraphs[0].text = 'Header text'; header_doc.save(header_source)
                header_listing = await session.call_tool('list_word_stories', {'file': str(header_source)})
                assert not header_listing.isError, header_listing
                header_path = header_listing.structuredContent['stories'][0]['paragraphs'][0]['path']; header_draft = root / 'header-draft'
                header_start = await session.call_tool('start_session', {'directory': str(header_draft), 'source': str(header_source)})
                assert not header_start.isError, header_start
                header_target = await session.call_tool('session_edit_target', {'directory': str(header_draft), 'base_revision': 0, 'path': header_path})
                assert not header_target.isError and header_target.structuredContent['story_impact']['complete'] and header_target.structuredContent['story_impact']['linked_sections'][0]['section'] == 1, header_target
                header_edit = await session.call_tool('session_replace_text', {'directory': str(header_draft), 'base_revision': 0, 'path': header_path, 'find': 'Header', 'replacement': 'Updated'})
                assert not header_edit.isError, header_edit
                header_new = await session.call_tool('session_list_word_stories', {'directory': str(header_draft), 'revision': 1})
                assert not header_new.isError and header_new.structuredContent['stories'][0]['paragraphs'][0]['text'] == 'Updated text', header_new
                empty_comments = await session.call_tool('list_word_comments', {'file': str(comment_source)})
                assert not empty_comments.isError and empty_comments.structuredContent['total_comments'] == 0, empty_comments
                threaded = await session.call_tool('list_word_comments', {'file': str(thread_fixture(root))})
                assert not threaded.isError and threaded.structuredContent['comments'][0]['resolved'] is True
                assert threaded.structuredContent['comments'][1]['reply_to_comment_id'] == threaded.structuredContent['comments'][0]['id'], threaded
                modern_source = thread_fixture(root, 'modern_both'); modern_draft = root / 'modern-mcp-draft'
                modern_started = await session.call_tool('start_session', {'directory': str(modern_draft), 'source': str(modern_source)})
                assert not modern_started.isError, modern_started
                modern_root = await session.call_tool('session_add_comment', {'directory': str(modern_draft), 'base_revision': 0, 'path': '/body/p[4]', 'text': 'New root', 'author': 'Editor'})
                assert not modern_root.isError and modern_root.structuredContent['revision'] == 1, modern_root
                modern_root_list = await session.call_tool('session_list_comments', {'directory': str(modern_draft), 'revision': 1})
                assert not modern_root_list.isError and modern_root_list.structuredContent['comments'][-1]['resolved'] is False, modern_root_list
                modern_opened = await session.call_tool('session_resolve_comment', {'directory': str(modern_draft), 'base_revision': 1, 'comment_id': '0', 'resolved': False})
                assert not modern_opened.isError, modern_opened
                modern_reply = await session.call_tool('session_reply_comment', {'directory': str(modern_draft), 'base_revision': 2, 'parent_id': '0', 'text': 'Modern reply', 'author': 'Editor'})
                assert not modern_reply.isError, modern_reply
                modern_list = await session.call_tool('session_list_comments', {'directory': str(modern_draft), 'revision': 3})
                assert not modern_list.isError and modern_list.structuredContent['comments'][-1]['reply_to_comment_id'] == '0', modern_list
                historic_comments = await session.call_tool('session_list_comments', {'directory': str(comment_draft), 'revision': 0})
                assert not historic_comments.isError and historic_comments.structuredContent['total_comments'] == 0, historic_comments
                current_comments = await session.call_tool('session_list_comments', {'directory':str(comment_draft),'revision':1})
                assert (await session.call_tool('session_reply_comment', {'directory':str(comment_draft),'base_revision':1,'parent_id':'0','text':'Bad','author':'Editor','expected_sha256':'0'*64})).isError
                replied = await session.call_tool('session_reply_comment', {'directory': str(comment_draft), 'base_revision': 1, 'parent_id': '0', 'text': 'Acknowledged', 'author': 'Editor', 'expected_sha256':current_comments.structuredContent['snapshot_sha256']})
                assert not replied.isError and replied.structuredContent['revision'] == 2, replied
                replied_listing = await session.call_tool('session_list_comments', {'directory': str(comment_draft), 'revision': 2})
                assert not replied_listing.isError and replied_listing.structuredContent['comments'][1]['reply_to_comment_id'] == '0', replied_listing
                resolved_comment = await session.call_tool('session_resolve_comment', {'directory': str(comment_draft), 'base_revision': 2, 'comment_id': '0', 'resolved': True, 'expected_sha256':replied_listing.structuredContent['snapshot_sha256']})
                assert not resolved_comment.isError and resolved_comment.structuredContent['revision'] == 3, resolved_comment
                resolved_listing = await session.call_tool('session_list_comments', {'directory': str(comment_draft), 'revision': 3})
                assert not resolved_listing.isError and resolved_listing.structuredContent['comments'][0]['resolved'] is True, resolved_listing
                stale_comment = await session.call_tool('session_add_comment', {'directory': str(comment_draft), 'base_revision': 0, 'path': '/body/p[1]', 'text': 'Stale', 'author': 'Reviewer'})
                assert stale_comment.isError, stale_comment
                link_source = root / 'link.docx'; linked = Document(); paragraph = linked.add_paragraph('Read ')
                hyperlink = OxmlElement('w:hyperlink'); hyperlink.set(qn('r:id'), linked.part.relate_to('https://example.com', RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
                run = OxmlElement('w:r'); content = OxmlElement('w:t'); content.text = 'linked text'; run.append(content); hyperlink.append(run); paragraph._p.append(hyperlink); linked.save(link_source)
                link_draft = root / 'link-draft'; link_started = await session.call_tool('start_session', {'directory': str(link_draft), 'source': str(link_source)})
                assert not link_started.isError, link_started
                link_edit = await session.call_tool('session_replace_text', {'directory': str(link_draft), 'base_revision': 0, 'path': '/body/p[1]', 'find': 'linked', 'replacement': 'updated'})
                assert not link_edit.isError, link_edit
                linked_result = Document(link_draft / 'revision-000001.docx'); link_node = linked_result.paragraphs[0]._p.find(qn('w:hyperlink'))
                assert linked_result.part.rels[link_node.get(qn('r:id'))].target_ref == 'https://example.com', link_edit
                directory = root / 'draft'
                started = await session.call_tool('start_session', {'directory': str(directory), 'source': str(output)})
                assert not started.isError and started.structuredContent['latest_revision'] == 0, started
                updated = await session.call_tool('session_apply', {'directory': str(directory), 'base_revision': 0, 'operations': [{'command': 'set', 'path': '/body/p[1]', 'props': {'text': 'Session edit'}}]})
                assert not updated.isError and updated.structuredContent['revision'] == 1, updated
                set_selection(directory, {'revision': 1, 'page': 1, 'box': [0, 0, 1, 1]})
                selected = await session.call_tool('session_selection', {'directory': str(directory)})
                assert not selected.isError and selected.structuredContent['stale'] is False, selected
                selected_text = await session.call_tool('session_selection_text', {'directory': str(directory)})
                assert not selected_text.isError and 'Session edit' in selected_text.structuredContent['text'], selected_text
                matches = await session.call_tool('session_selection_candidates', {'directory': str(directory)})
                assert not matches.isError and matches.structuredContent['requires_verification'] and matches.structuredContent['candidates'], matches
                cropped = await session.call_tool('session_selection_image', {'directory': str(directory)})
                assert not cropped.isError and cropped.content[0].type == 'image' and cropped.content[1].type == 'text' and cropped.structuredContent['stale'] is False, cropped
                advanced = await session.call_tool('session_apply', {'directory': str(directory), 'base_revision': 1, 'operations': []})
                assert not advanced.isError, advanced
                stale_selection = await session.call_tool('session_selection', {'directory': str(directory)})
                assert not stale_selection.isError and stale_selection.structuredContent['stale'] is True, stale_selection
                stale_image = await session.call_tool('session_selection_image', {'directory': str(directory)})
                assert not stale_image.isError and stale_image.content[0].data == cropped.content[0].data and stale_image.structuredContent['stale'] is True, stale_image
                restored = await session.call_tool('session_restore', {'directory': str(directory), 'base_revision': 2, 'revision': 0})
                assert not restored.isError and restored.structuredContent['revision'] == 3, restored
                outdated_restore = await session.call_tool('session_restore', {'directory': str(directory), 'base_revision': 2, 'revision': 0})
                assert outdated_restore.isError, outdated_restore
                target = await session.call_tool('session_edit_target', {'directory': str(directory), 'base_revision': 3, 'path': '/body/p[1]'})
                assert not target.isError and target.structuredContent['value'] == 'MCP works', target
                wrong_target = await session.call_tool('session_edit', {'directory':str(directory),'base_revision':3,'path':target.structuredContent['path'],'mode':'text','value':'bad','expected_sha256':'0'*64})
                assert wrong_target.isError, wrong_target
                edited = await session.call_tool('session_edit', {'directory': str(directory), 'base_revision': 3, 'path': target.structuredContent['path'], 'mode': 'text', 'value': 'Edited via MCP', 'expected_sha256':target.structuredContent['snapshot_sha256']})
                assert not edited.isError and edited.structuredContent['revision'] == 4, edited

                conflict = await session.call_tool('session_apply', {'directory': str(directory), 'base_revision': 0, 'operations': []})
                assert conflict.isError and 'conflict' in str(conflict).lower(), conflict
                exported = await session.call_tool('session_export', {'directory': str(directory), 'revision': 1, 'output': str(root / 'session.docx')})
                assert not exported.isError and (root / 'session.docx').exists(), exported
                invalid = await session.call_tool('apply_batch', {'output': str(output), 'operations': operations})
                assert invalid.isError and 'already exists' in str(invalid), invalid
                bundle = await session.call_tool('review_document_bundle', {'file': str(output), 'output_dir': str(root / 'mcp-bundle')})
                assert not bundle.isError and not bundle.structuredContent['check_errors'], bundle
                bundle_image = await session.call_tool('view_page', {'file': bundle.structuredContent['artifacts']['overview.png']})
                assert not bundle_image.isError and bundle_image.content[0].type == 'image', bundle_image
                historic_bundle = await session.call_tool('session_review_bundle', {'directory': str(directory), 'revision': 0, 'output_dir': str(root / 'mcp-history-bundle')})
                assert not historic_bundle.isError and historic_bundle.structuredContent['revision'] == 0, historic_bundle
                rejected_bundle = await session.call_tool('session_review_bundle', {'directory': str(directory), 'revision': 0, 'output_dir': str(directory / 'bad-bundle')})
                assert rejected_bundle.isError and not (directory / 'bad-bundle').exists(), rejected_bundle
                images = await session.call_tool('preview_pages', {'file': str(output), 'output_dir': str(root / 'pages')})
                assert not images.isError, images
                paths = images.structuredContent['pages']
                assert paths and Path(paths[0]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                page_view = await session.call_tool('view_document_page', {'file': str(output), 'page': 1, 'box': [0, 0, .5, .5]})
                assert not page_view.isError and page_view.content[0].type == 'image', page_view
                first_page = await session.call_tool('session_view_page', {'directory': str(directory), 'revision': 0, 'page': 1})
                second_page = await session.call_tool('session_view_page', {'directory': str(directory), 'revision': 1, 'page': 1})
                assert not first_page.isError and not second_page.isError and first_page.content[0].data != second_page.content[0].data
                visual_comparison = await session.call_tool('session_compare_page_images', {'directory': str(directory), 'before_revision': 0, 'after_revision': 1, 'before_page': 1, 'after_page': 1})
                assert not visual_comparison.isError and visual_comparison.content[0].type == 'image', visual_comparison
                file_comparison = await session.call_tool('compare_page_images', {'before': str(output), 'after': str(output), 'before_page': 1, 'after_page': 1})
                assert not file_comparison.isError and file_comparison.content[0].type == 'image', file_comparison
                missing_page = await session.call_tool('session_view_page', {'directory': str(directory), 'revision': 0, 'page': 100})
                assert missing_page.isError, missing_page
                overview = await session.call_tool('view_contact_sheet', {'file': str(output), 'start_page': 1, 'count': 1})
                assert not overview.isError and overview.content[0].type == 'image' and overview.content[0].mimeType == 'image/png', overview
                history_overview = await session.call_tool('session_contact_sheet', {'directory': str(directory), 'revision': 0, 'count': 1})
                assert not history_overview.isError and history_overview.content[0].type == 'image', history_overview
                missing_overview = await session.call_tool('session_contact_sheet', {'directory': str(directory), 'revision': 999})
                assert missing_overview.isError, missing_overview
                image = await session.call_tool('view_page', {'file': paths[0]})
                assert not image.isError and image.content[0].type == 'image' and image.content[0].mimeType == 'image/png', image
                workbook = Workbook(); workbook.active['A1'] = 4; workbook.active['A2'] = '=A1*3'
                original = root / 'numbers.xlsx'; workbook.save(original)
                calculated = root / 'calculated.xlsx'
                calc = await session.call_tool('recalculate_workbook', {'file': str(original), 'output': str(calculated)})
                assert not calc.isError, calc
                text_source = root / 'text.xlsx'; text_book = Workbook(); text_book.active['A1'] = 'value alpha'; text_book.active['A1'].font = Font(bold=True); text_book.save(text_source)
                text_draft = root / 'text-draft'; text_started = await session.call_tool('start_session', {'directory': str(text_draft), 'source': str(text_source)})
                assert not text_started.isError, text_started
                text_edit = await session.call_tool('session_replace_text', {'directory': str(text_draft), 'base_revision': 0, 'path': '/Sheet/A1', 'find': 'alpha', 'replacement': 'beta'})
                assert not text_edit.isError, text_edit
                changed_cell = load_workbook(text_draft / 'revision-000001.xlsx').active['A1']
                assert changed_cell.value == 'value beta' and changed_cell.font.bold
                grid_text = await session.call_tool('session_edit_grid', {'directory': str(text_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1', 'changes': [{'cell': 'A1', 'value': 'gamma beta'}]})
                assert not grid_text.isError, grid_text
                grid_text_target = await session.call_tool('session_edit_target', {'directory': str(text_draft), 'base_revision': 2, 'path': '/Sheet/A1'})
                assert not grid_text_target.isError and grid_text_target.structuredContent['replace_text_path_supported'], grid_text_target
                grid_text_edit = await session.call_tool('session_replace_text', {'directory': str(text_draft), 'base_revision': 2, 'path': '/Sheet/A1', 'find': 'gamma', 'replacement': 'delta'})
                assert not grid_text_edit.isError and load_workbook(text_draft / 'revision-000003.xlsx').active['A1'].value == 'delta beta', grid_text_edit
                grid_draft = root / 'grid-draft'
                grid_started = await session.call_tool('start_session', {'directory': str(grid_draft), 'source': str(original)})
                assert not grid_started.isError, grid_started
                chart_scan = await session.call_tool('session_scan_chart_caches', {'directory': str(grid_draft), 'revision': 0})
                assert not chart_scan.isError and chart_scan.structuredContent['chart_parts_total'] == 0 and chart_scan.structuredContent['complete'], chart_scan
                authored_source = root / 'authored-chart-source.xlsx'; authored_book = Workbook(); authored_sheet = authored_book.active; authored_sheet.title = 'Sales'
                for values in [('Month', 'Revenue'), ('Jan', 10), ('Feb', 20)]: authored_sheet.append(values)
                authored_book.save(authored_source); authored_draft = root / 'authored-chart-draft'
                authored_start = await session.call_tool('start_session', {'directory': str(authored_draft), 'source': str(authored_source)})
                assert not authored_start.isError, authored_start
                authored = await session.call_tool('session_apply', {'directory': str(authored_draft), 'base_revision': 0, 'operations': [{'command': 'add', 'parent': '/Sales', 'type': 'chart', 'props': {'chartType': 'column', 'dataRange': 'Sales!A1:B3', 'title': 'Revenue', 'anchor': 'D2:J15'}}]})
                assert not authored.isError, authored
                authored_read = await session.call_tool('structured_read', {'file': str(authored_draft / 'revision-000001.xlsx'), 'mode': 'query', 'target': 'chart'})
                assert not authored_read.isError and authored_read.structuredContent['data']['results'][0]['format']['title'] == 'Revenue', authored_read
                chart_source = root / 'chart-source.xlsx'; chart_book = xlsxwriter.Workbook(str(chart_source)); chart_sheet = chart_book.add_worksheet('Sales'); chart_sheet.write_column('A1', ['Jan', 'Feb']); chart_sheet.write_column('B1', [10, 20]); chart = chart_book.add_chart({'type': 'column'}); chart.add_series({'categories': '=Sales!$A$1:$A$2', 'values': '=Sales!$B$1:$B$2'}); chart_sheet.insert_chart('D1', chart); chart_book.close()
                chart_draft = root / 'chart-draft'; chart_start = await session.call_tool('start_session', {'directory': str(chart_draft), 'source': str(chart_source)})
                assert not chart_start.isError, chart_start
                chart_edit = await session.call_tool('session_replace_text', {'directory': str(chart_draft), 'base_revision': 0, 'path': '/Sales/A1', 'find': 'Jan', 'replacement': 'March'})
                assert not chart_edit.isError, chart_edit
                assert chart_edit.structuredContent['formula_cache_effect'] == 'may_be_stale' and chart_edit.structuredContent['recalculation_requested'], chart_edit
                chart_formula_scan = await session.call_tool('session_scan_formulas', {'directory': str(chart_draft), 'base_revision': 1})
                assert not chart_formula_scan.isError and chart_formula_scan.structuredContent['recalculation_requests'] == 1, chart_formula_scan
                chart_result = await session.call_tool('session_scan_chart_caches', {'directory': str(chart_draft), 'revision': 1})
                assert not chart_result.isError and chart_result.structuredContent['mismatch_references'] == 1, chart_result
                saved_chart_result = await session.call_tool('scan_chart_caches', {'file': str(chart_draft / 'revision-000001.xlsx')})
                assert not saved_chart_result.isError and saved_chart_result.structuredContent['mismatch_references'] == 1, saved_chart_result
                chart_part = chart_result.structuredContent['charts'][0]; chart_ref = next(item for item in chart_part['references'] if item['status'] == 'mismatch')
                chart_sync = await session.call_tool('session_sync_chart_cache', {'directory': str(chart_draft), 'base_revision': 1, 'part': chart_part['part'], 'reference': chart_ref['index']})
                assert not chart_sync.isError and chart_sync.structuredContent['revision'] == 2 and chart_sync.structuredContent['updated_points'] == 1, chart_sync
                chart_after = await session.call_tool('session_scan_chart_caches', {'directory': str(chart_draft), 'revision': 2})
                assert not chart_after.isError and chart_after.structuredContent['mismatch_references'] == 0, chart_after
                workbook_view = await session.call_tool('session_inspect_workbook', {'directory': str(grid_draft), 'revision': 0})
                assert not workbook_view.isError and workbook_view.structuredContent['revision'] == 0 and workbook_view.structuredContent['sheets'][0]['cells'][0]['cell'] == 'A1', workbook_view
                searched = await session.call_tool('session_search_cells', {'directory': str(chart_draft), 'revision': 0, 'query': 'Jan'})
                assert not searched.isError and searched.structuredContent['revision'] == 0 and searched.structuredContent['matches'][0]['cell'] == 'A1', searched
                searched_file = await session.call_tool('search_cells', {'file': str(chart_source), 'query': 'Jan'})
                assert not searched_file.isError and searched_file.structuredContent['matches'][0]['cell'] == 'A1', searched_file
                file_workbook_view = await session.call_tool('inspect_file', {'file': str(original)})
                assert not file_workbook_view.isError and file_workbook_view.structuredContent['type'] == 'xlsx', file_workbook_view
                sheets = await session.call_tool('session_sheets', {'directory': str(grid_draft), 'base_revision': 0})
                assert not sheets.isError and sheets.structuredContent['sheets'] == ['Sheet'], sheets
                grid = await session.call_tool('session_read_grid', {'directory': str(grid_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not grid.isError and grid.structuredContent['rows'][1][0]['formula'] == '=A1*3', grid
                guarded_source = root / 'guarded.xlsx'; guarded = Workbook(); guarded.active['A1'] = 'Merged'; guarded.active.merge_cells('A1:B2'); guarded.active['C1'] = 'Unlocked'; guarded.active['C1'].protection = Protection(locked=False); guarded.active.protection.sheet = True; guarded.save(guarded_source)
                guarded_draft = root / 'guarded-draft'; guarded_start = await session.call_tool('start_session', {'directory': str(guarded_draft), 'source': str(guarded_source)})
                assert not guarded_start.isError, guarded_start
                guarded_grid = await session.call_tool('session_read_grid', {'directory': str(guarded_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:C1'})
                assert not guarded_grid.isError and guarded_grid.structuredContent['sheet_protected'] and guarded_grid.structuredContent['rows'][0][1]['read_only_reason'] == 'merged_placeholder' and guarded_grid.structuredContent['rows'][0][2]['editable'], guarded_grid
                guarded_edit = await session.call_tool('session_edit_grid', {'directory': str(guarded_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:C1', 'changes': [{'cell': 'B1', 'value': 'hidden'}]})
                assert guarded_edit.isError, guarded_edit
                long_source = root / 'long-grid.xlsx'; long_book = Workbook()
                for row in range(1, 102): long_book.active.cell(row, 1, 'x' * 10000)
                long_book.save(long_source); long_draft = root / 'long-grid-draft'
                long_start = await session.call_tool('start_session', {'directory': str(long_draft), 'source': str(long_source)})
                assert not long_start.isError, long_start
                long_grid = await session.call_tool('session_read_grid', {'directory': str(long_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1'})
                assert not long_grid.isError and long_grid.structuredContent['rows'][0][0]['read_only_reason'] == 'value_too_long', long_grid
                oversized = await session.call_tool('read_cells', {'file': str(long_source), 'sheet': 'Sheet', 'cell_range': 'A1:A101'})
                assert oversized.isError, oversized
                single_draft = root / 'single-grid-draft'
                assert not (await session.call_tool('start_session', {'directory': str(single_draft), 'source': str(original)})).isError
                single = await session.call_tool('session_edit', {'directory': str(single_draft), 'base_revision': 0, 'path': '/Sheet/A1', 'mode': 'value', 'value': '12'})
                assert not single.isError and single.structuredContent['formula_cache_effect'] == 'may_be_stale' and single.structuredContent['recalculation_requested'], single
                literal_single = await session.call_tool('session_edit', {'directory': str(single_draft), 'base_revision': 1, 'path': '/Sheet/A1', 'mode': 'literal', 'value': '=literal text'})
                assert not literal_single.isError and load_workbook(single_draft / 'revision-000002.xlsx').active['A1'].value == '=literal text' and load_workbook(single_draft / 'revision-000002.xlsx').active['A1'].data_type == 's', literal_single
                literal_draft = root / 'literal-grid-draft'
                assert not (await session.call_tool('start_session', {'directory': str(literal_draft), 'source': str(original)})).isError
                literal_edit = await session.call_tool('session_edit_grid', {'directory': str(literal_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'changes': [{'cell': 'A1', 'value': '00123', 'type': 'text'}, {'cell': 'A2', 'value': '=literal', 'type': 'text'}]})
                assert not literal_edit.isError, literal_edit
                literal_book = load_workbook(literal_draft / 'revision-000001.xlsx')
                assert literal_book.active['A1'].value == '00123' and literal_book.active['A2'].value == '=literal' and literal_book.active['A2'].data_type == 's'
                dynamic_draft = root / 'dynamic-grid-draft'
                assert not (await session.call_tool('start_session', {'directory': str(dynamic_draft), 'source': str(original)})).isError
                dynamic = await session.call_tool('session_edit_grid', {'directory': str(dynamic_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'C1', 'changes': [{'cell': 'C1', 'value': '=SEQUENCE(3)'}]})
                assert not dynamic.isError and dynamic.structuredContent['recalculation_requested'] and dynamic.structuredContent['dynamic_formula_cells'] == ['C1'], dynamic
                dynamic_read = await session.call_tool('session_read_grid', {'directory': str(dynamic_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'C1'})
                assert not dynamic_read.isError and dynamic_read.structuredContent['rows'][0][0]['editable'] and dynamic_read.structuredContent['rows'][0][0]['dynamic_formula_anchor'], dynamic_read
                dynamic_edit_draft = root / 'dynamic-edit-draft'
                assert not (await session.call_tool('start_session', {'directory': str(dynamic_edit_draft), 'source': str(dynamic_draft / 'revision-000001.xlsx')})).isError
                dynamic_edited = await session.call_tool('session_edit_grid', {'directory': str(dynamic_edit_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'C1', 'changes': [{'cell':'C1','value':'=SEQUENCE(4)'}]})
                assert not dynamic_edited.isError and dynamic_edited.structuredContent['dynamic_formula_cells'] == ['C1'], dynamic_edited
                assert load_workbook(dynamic_edit_draft / 'revision-000001.xlsx').active['C1'].value.text == '=_xlfn.SEQUENCE(4)'
                scoped_edit = await session.call_tool('session_edit', {'directory': str(dynamic_edit_draft), 'base_revision': 1, 'path': '/Sheet/C1', 'mode': 'formula', 'value': '=LET(x,1,y,x+2,y*2)'})
                assert not scoped_edit.isError and scoped_edit.structuredContent['dynamic_formula_cells'] == ['C1'], scoped_edit
                dynamic_pdf = await session.call_tool('render_pdf', {'file': str(dynamic_draft / 'revision-000001.xlsx'), 'output_dir': str(root / 'dynamic-pdf')})
                assert not dynamic_pdf.isError and dynamic_pdf.structuredContent['render_advisory']['dynamic_array_metadata'] is True, dynamic_pdf
                dynamic_view = await session.call_tool('session_view_page', {'directory': str(dynamic_draft), 'revision': 1, 'page': 1})
                assert not dynamic_view.isError and dynamic_view.content[0].type == 'image' and dynamic_view.content[1].type == 'text' and dynamic_view.structuredContent['revision'] == 1 and dynamic_view.structuredContent['snapshot_sha256'] == hashlib.sha256((dynamic_draft / 'revision-000001.xlsx').read_bytes()).hexdigest() and dynamic_view.structuredContent['warnings'], dynamic_view
                dynamic_contact = await session.call_tool('view_contact_sheet', {'file': str(dynamic_draft / 'revision-000001.xlsx'), 'count': 1})
                assert not dynamic_contact.isError and dynamic_contact.content[0].type == 'image' and dynamic_contact.structuredContent['render_advisory']['dynamic_array_metadata'] is True and dynamic_contact.structuredContent['warnings'], dynamic_contact
                dynamic_comparison = await session.call_tool('session_compare_page_images', {'directory': str(dynamic_draft), 'before_revision': 0, 'after_revision': 1, 'before_page': 1, 'after_page': 1})
                assert not dynamic_comparison.isError and dynamic_comparison.content[0].type == 'image' and dynamic_comparison.structuredContent['after_render_advisory']['dynamic_array_metadata'] is True and dynamic_comparison.structuredContent['before_render_advisory']['dynamic_array_metadata'] is False, dynamic_comparison
                set_selection(dynamic_draft, {'revision': 1, 'page': 1, 'box': [0,0,.5,.5]})
                dynamic_selection = await session.call_tool('session_selection_image', {'directory': str(dynamic_draft)})
                assert not dynamic_selection.isError and dynamic_selection.structuredContent['stale'] is False and not dynamic_selection.structuredContent['selection_changed'] and dynamic_selection.structuredContent['warnings'], dynamic_selection
                dynamic_text = await session.call_tool('session_selection_text', {'directory': str(dynamic_draft)})
                assert not dynamic_text.isError and dynamic_text.structuredContent['render_advisory']['dynamic_array_metadata'] is True and not dynamic_text.structuredContent['selection_changed'] and dynamic_text.structuredContent['snapshot_sha256'] == dynamic_view.structuredContent['snapshot_sha256'], dynamic_text
                dynamic_candidates = await session.call_tool('session_selection_candidates', {'directory': str(dynamic_draft)})
                assert not dynamic_candidates.isError and dynamic_candidates.structuredContent['render_advisory']['dynamic_array_metadata'] is True and not dynamic_candidates.structuredContent['selection_changed'] and dynamic_candidates.structuredContent['snapshot_sha256'] == dynamic_view.structuredContent['snapshot_sha256'], dynamic_candidates
                dynamic_scan = await session.call_tool('session_scan_formulas', {'directory': str(dynamic_draft), 'base_revision': 1})
                assert not dynamic_scan.isError and dynamic_scan.structuredContent['dynamic_array_metadata'] is True, dynamic_scan
                denied_calc = await session.call_tool('session_recalculate', {'directory': str(dynamic_draft), 'base_revision': 1})
                assert denied_calc.isError, denied_calc
                allowed_calc = await session.call_tool('session_recalculate', {'directory': str(dynamic_draft), 'base_revision': 1, 'allow_dynamic_arrays': True})
                assert not allowed_calc.isError and allowed_calc.structuredContent['dynamic_array_override'], allowed_calc
                stale_dynamic = await session.call_tool('session_selection_image', {'directory': str(dynamic_draft)})
                assert not stale_dynamic.isError and stale_dynamic.structuredContent['revision'] == 1 and stale_dynamic.structuredContent['latest_revision'] == 2 and stale_dynamic.structuredContent['stale'] is True, stale_dynamic
                saved_grid = await session.call_tool('session_edit_grid', {'directory': str(grid_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'changes': [{'cell': 'A1', 'value': '5'}]})
                assert not saved_grid.isError and saved_grid.structuredContent['revision'] == 1 and saved_grid.structuredContent['formula_cache_effect'] == 'may_be_stale' and saved_grid.structuredContent['recalculation_requested'], saved_grid
                styled = await session.call_tool('session_format_grid', {'directory': str(grid_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'style_range': 'A1', 'properties': {'bold': True, 'italic': True, 'font_color': '336699', 'horizontal': 'center', 'wrap': True, 'border': 'thin', 'border_scope': 'outline', 'border_color': '336699'}})
                assert not styled.isError and styled.structuredContent['revision'] == 2 and styled.structuredContent['formula_cache_effect'] == 'preserved', styled
                styled_cell = load_workbook(grid_draft / 'revision-000002.xlsx').active['A1']
                assert styled_cell.font.i and styled_cell.font.color.rgb[-6:] == '336699' and styled_cell.alignment.horizontal == 'center' and styled_cell.alignment.wrap_text
                assert styled_cell.border.top.style == 'thin' and styled_cell.border.top.color.rgb[-6:] == '336699'
                format_diff = await session.call_tool('compare_cells', {'before': str(grid_draft / 'revision-000001.xlsx'), 'after': str(grid_draft / 'revision-000002.xlsx'), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not format_diff.isError and 'format.font' in format_diff.structuredContent['changes'][0]['changed_fields'], format_diff
                merge_draft = root / 'grid-merge-draft'
                assert not (await session.call_tool('start_session', {'directory': str(merge_draft), 'source': str(grid_draft / 'revision-000002.xlsx')})).isError
                merged = await session.call_tool('session_merge_cells', {'directory': str(merge_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'C1:D1'})
                assert not merged.isError and 'C1:D1' in str(load_workbook(merge_draft / 'revision-000001.xlsx').active.merged_cells), merged
                freeze_draft = root / 'grid-freeze-draft'
                assert not (await session.call_tool('start_session', {'directory': str(freeze_draft), 'source': str(grid_draft / 'revision-000002.xlsx')})).isError
                freeze = await session.call_tool('session_freeze_panes', {'directory': str(freeze_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell': 'B2'})
                assert not freeze.isError and load_workbook(freeze_draft / 'revision-000001.xlsx').active.freeze_panes == 'B2', freeze
                sizing_draft = root / 'grid-sizing-draft'
                assert not (await session.call_tool('start_session', {'directory': str(sizing_draft), 'source': str(grid_draft / 'revision-000002.xlsx')})).isError
                resized = await session.call_tool('session_resize_grid', {'directory': str(sizing_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'target_range': 'A1', 'column_width': 21, 'row_height': 28})
                assert not resized.isError and resized.structuredContent['revision'] == 1 and resized.structuredContent['formula_cache_effect'] == 'preserved', resized
                dimensions = await session.call_tool('session_read_grid', {'directory': str(sizing_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1'})
                assert float(dimensions.structuredContent['dimensions']['columns']['A']['width']) == 21 and float(dimensions.structuredContent['dimensions']['rows']['1']['ht']) == 28, dimensions
                sizing_diff = await session.call_tool('session_compare_cells', {'directory': str(sizing_draft), 'before_revision': 0, 'after_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not sizing_diff.isError and sizing_diff.structuredContent['dimensions']['changed_count'] == 2, sizing_diff
                revision_scan = await session.call_tool('session_scan_formulas', {'directory': str(grid_draft), 'base_revision': 2})
                assert not revision_scan.isError and revision_scan.structuredContent['revision'] == 2, revision_scan
                revision_calc = await session.call_tool('session_recalculate', {'directory': str(grid_draft), 'base_revision': 2})
                assert not revision_calc.isError and revision_calc.structuredContent['revision'] == 3, revision_calc
                assert load_workbook(grid_draft / 'revision-000003.xlsx', data_only=True).active['A2'].value == 15
                stale_scan = await session.call_tool('session_scan_formulas', {'directory': str(grid_draft), 'base_revision': 2})
                assert stale_scan.isError, stale_scan
                scanned = await session.call_tool('scan_formulas', {'file': str(calculated)})
                assert not scanned.isError and scanned.structuredContent['formulas'] == 1 and scanned.structuredContent['complete'], scanned
                cells = await session.call_tool('read_cells', {'file': str(calculated), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not cells.isError and cells.structuredContent['rows'][1][0]['value'] == 12, cells
                diff = await session.call_tool('compare_cells', {'before': str(original), 'after': str(calculated), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not diff.isError and any(item['cell'] == 'A2' and item['after']['value'] == 12 for item in diff.structuredContent['changes']), diff

                wrong = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get'})
                assert wrong.isError, wrong
    print('MCP stdio smoke passed: discovery, authoring, read, preview and errors')


if __name__ == '__main__':
    asyncio.run(main())
