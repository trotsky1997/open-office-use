"""Check the stdio MCP lifecycle and real artifact operations."""
import asyncio
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Protection
from docx import Document
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
                assert {t.name for t in tools.tools} == {'office_doctor', 'office_schema', 'inspect_file', 'session_inspect_workbook', 'search_cells', 'session_search_cells', 'scan_chart_caches', 'session_scan_chart_caches', 'session_sync_chart_cache', 'inspect_slide_layout', 'session_inspect_slide_layout', 'inspect_slide_text', 'session_inspect_slide_text', 'search_slide_text', 'session_search_slide_text', 'structured_read', 'dump_office_subtree', 'session_dump_office_subtree', 'apply_batch', 'render_pdf', 'preview_pages', 'view_page', 'view_contact_sheet', 'session_contact_sheet', 'view_document_page', 'session_view_page', 'compare_page_images', 'session_compare_page_images', 'read_cells', 'recalculate_workbook', 'compare_files', 'audit_file', 'review_document_bundle', 'session_review_bundle', 'start_session', 'session_info', 'session_apply', 'session_export', 'session_selection', 'session_selection_image', 'session_selection_text', 'session_selection_candidates', 'session_restore', 'session_recalculate', 'session_scan_formulas', 'session_edit_target', 'session_edit', 'session_replace_text', 'session_track_replace_text', 'session_track_insert_text', 'session_resolve_tracked_runs', 'read_slide_notes', 'session_read_slide_notes', 'compare_slide_notes', 'session_compare_slide_notes', 'session_replace_slide_notes', 'session_replace_slide_notes_text', 'session_add_comment', 'session_reply_comment', 'session_resolve_comment', 'list_word_comments', 'list_word_tracked_changes', 'session_list_word_tracked_changes', 'list_word_stories', 'search_word_body', 'session_search_word_body', 'search_word_stories', 'session_search_word_stories', 'session_list_word_stories', 'session_list_comments', 'session_replace_picture', 'compare_cells', 'session_sheets', 'session_read_grid', 'session_edit_grid', 'session_format_grid', 'scan_formulas'}
                diagnostics = await session.call_tool('office_doctor', {})
                assert not diagnostics.isError and diagnostics.structuredContent['capabilities']['mcp_server'] is True, diagnostics
                word_source = root / 'search.docx'; search_doc = Document(); search_doc.add_paragraph('find needle'); search_doc.save(word_source)
                tracked = await session.call_tool('list_word_tracked_changes', {'file': str(word_source)})
                assert not tracked.isError and tracked.structuredContent['records_scanned'] == 0, tracked
                track_draft = root / 'tracked-draft'; tracked_started = await session.call_tool('start_session', {'directory': str(track_draft), 'source': str(word_source)})
                assert not tracked_started.isError, tracked_started
                tracked_edit = await session.call_tool('session_track_replace_text', {'directory': str(track_draft), 'base_revision': 0, 'path': '/body/p[1]', 'find': 'needle', 'replacement': 'thread', 'author': 'Reviewer'})
                assert not tracked_edit.isError and tracked_edit.structuredContent['revision'] == 1, tracked_edit
                tracked_view = await session.call_tool('session_list_word_tracked_changes', {'directory': str(track_draft), 'revision': 1})
                assert not tracked_view.isError and tracked_view.structuredContent['counts'] == {'del': 1, 'ins': 1}, tracked_view
                record_ids = [record['id'] for record in tracked_view.structuredContent['records']]
                resolved = await session.call_tool('session_resolve_tracked_runs', {'directory': str(track_draft), 'base_revision': 1, 'part': 'word/document.xml', 'ids': record_ids, 'accept': True})
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
                changed_picture = await session.call_tool('session_replace_picture', {'directory': str(picture_draft), 'base_revision': 0, 'path': f'/slide[1]/picture[@id={picture.shape_id}]', 'image_file': str(replacement_image)})
                assert not changed_picture.isError and Presentation(picture_draft / 'revision-000001.pptx').slides[0].shapes[0].image.blob == replacement_image.read_bytes(), changed_picture
                changed_notes = await session.call_tool('session_replace_slide_notes', {'directory': str(picture_draft), 'base_revision': 1, 'slide': 1, 'text': 'Talk track'})
                assert not changed_notes.isError and changed_notes.structuredContent['revision'] == 2, changed_notes
                read_notes = await session.call_tool('session_read_slide_notes', {'directory': str(picture_draft), 'revision': 2, 'slide': 1})
                assert not read_notes.isError and read_notes.structuredContent['text'] == 'Talk track', read_notes
                note_edit = await session.call_tool('session_replace_slide_notes_text', {'directory': str(picture_draft), 'base_revision': 2, 'slide': 1, 'paragraph': 1, 'find': 'track', 'replacement': 'notes'})
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
                replied = await session.call_tool('session_reply_comment', {'directory': str(comment_draft), 'base_revision': 1, 'parent_id': '0', 'text': 'Acknowledged', 'author': 'Editor'})
                assert not replied.isError and replied.structuredContent['revision'] == 2, replied
                replied_listing = await session.call_tool('session_list_comments', {'directory': str(comment_draft), 'revision': 2})
                assert not replied_listing.isError and replied_listing.structuredContent['comments'][1]['reply_to_comment_id'] == '0', replied_listing
                resolved_comment = await session.call_tool('session_resolve_comment', {'directory': str(comment_draft), 'base_revision': 2, 'comment_id': '0', 'resolved': True})
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
                assert not cropped.isError and cropped.content[0].type == 'image', cropped
                advanced = await session.call_tool('session_apply', {'directory': str(directory), 'base_revision': 1, 'operations': []})
                assert not advanced.isError, advanced
                stale_selection = await session.call_tool('session_selection', {'directory': str(directory)})
                assert not stale_selection.isError and stale_selection.structuredContent['stale'] is True, stale_selection
                stale_image = await session.call_tool('session_selection_image', {'directory': str(directory)})
                assert not stale_image.isError and stale_image.content[0].data == cropped.content[0].data, stale_image
                restored = await session.call_tool('session_restore', {'directory': str(directory), 'base_revision': 2, 'revision': 0})
                assert not restored.isError and restored.structuredContent['revision'] == 3, restored
                outdated_restore = await session.call_tool('session_restore', {'directory': str(directory), 'base_revision': 2, 'revision': 0})
                assert outdated_restore.isError, outdated_restore
                target = await session.call_tool('session_edit_target', {'directory': str(directory), 'base_revision': 3, 'path': '/body/p[1]'})
                assert not target.isError and target.structuredContent['value'] == 'MCP works', target
                edited = await session.call_tool('session_edit', {'directory': str(directory), 'base_revision': 3, 'path': target.structuredContent['path'], 'mode': 'text', 'value': 'Edited via MCP'})
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
                saved_grid = await session.call_tool('session_edit_grid', {'directory': str(grid_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'changes': [{'cell': 'A1', 'value': '5'}]})
                assert not saved_grid.isError and saved_grid.structuredContent['revision'] == 1, saved_grid
                styled = await session.call_tool('session_format_grid', {'directory': str(grid_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'style_range': 'A1', 'properties': {'bold': True}})
                assert not styled.isError and styled.structuredContent['revision'] == 2, styled
                format_diff = await session.call_tool('compare_cells', {'before': str(grid_draft / 'revision-000001.xlsx'), 'after': str(grid_draft / 'revision-000002.xlsx'), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not format_diff.isError and 'format.font' in format_diff.structuredContent['changes'][0]['changed_fields'], format_diff
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
