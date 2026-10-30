"""Check the stdio MCP lifecycle and real artifact operations."""
import asyncio
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook
from session import set_selection
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
                assert {t.name for t in tools.tools} == {'inspect_file', 'structured_read', 'apply_batch', 'render_pdf', 'preview_pages', 'view_page', 'read_cells', 'recalculate_workbook', 'compare_files', 'audit_file', 'start_session', 'session_info', 'session_apply', 'session_export', 'session_selection', 'session_selection_image', 'session_selection_text', 'session_selection_candidates', 'session_restore', 'session_edit_target', 'session_edit', 'compare_cells', 'session_sheets', 'session_read_grid', 'session_edit_grid', 'session_format_grid'}
                output = root / 'report.docx'
                operations = [{'command': 'add', 'parent': '/body', 'type': 'paragraph', 'props': {'text': 'MCP works'}}]
                created = await session.call_tool('apply_batch', {'output': str(output), 'operations': operations})
                assert not created.isError and output.exists(), created
                readback = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get', 'target': '/body/p[1]'})
                assert not readback.isError and 'MCP works' in str(readback), readback
                revised = root / 'revised.docx'
                edit = await session.call_tool('apply_batch', {'source': str(output), 'output': str(revised), 'operations': [{'command': 'set', 'path': '/body/p[1]', 'props': {'text': 'Revised'}}]})
                assert not edit.isError, edit
                compared = await session.call_tool('compare_files', {'before': str(output), 'after': str(revised)})
                assert not compared.isError and 'Revised' in str(compared.structuredContent['text_diff']), compared
                audited = await session.call_tool('audit_file', {'file': str(revised)})
                assert not audited.isError and audited.structuredContent['validation']['result']['success'] is True, audited
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
                images = await session.call_tool('preview_pages', {'file': str(output), 'output_dir': str(root / 'pages')})
                assert not images.isError, images
                paths = images.structuredContent['pages']
                assert paths and Path(paths[0]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                image = await session.call_tool('view_page', {'file': paths[0]})
                assert not image.isError and image.content[0].type == 'image' and image.content[0].mimeType == 'image/png', image
                workbook = Workbook(); workbook.active['A1'] = 4; workbook.active['A2'] = '=A1*3'
                original = root / 'numbers.xlsx'; workbook.save(original)
                calculated = root / 'calculated.xlsx'
                calc = await session.call_tool('recalculate_workbook', {'file': str(original), 'output': str(calculated)})
                assert not calc.isError, calc
                grid_draft = root / 'grid-draft'
                grid_started = await session.call_tool('start_session', {'directory': str(grid_draft), 'source': str(original)})
                assert not grid_started.isError, grid_started
                sheets = await session.call_tool('session_sheets', {'directory': str(grid_draft), 'base_revision': 0})
                assert not sheets.isError and sheets.structuredContent['sheets'] == ['Sheet'], sheets
                grid = await session.call_tool('session_read_grid', {'directory': str(grid_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not grid.isError and grid.structuredContent['rows'][1][0]['formula'] == '=A1*3', grid
                saved_grid = await session.call_tool('session_edit_grid', {'directory': str(grid_draft), 'base_revision': 0, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'changes': [{'cell': 'A1', 'value': '5'}]})
                assert not saved_grid.isError and saved_grid.structuredContent['revision'] == 1, saved_grid
                styled = await session.call_tool('session_format_grid', {'directory': str(grid_draft), 'base_revision': 1, 'sheet': 'Sheet', 'cell_range': 'A1:A2', 'style_range': 'A1', 'properties': {'bold': True}})
                assert not styled.isError and styled.structuredContent['revision'] == 2, styled
                cells = await session.call_tool('read_cells', {'file': str(calculated), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not cells.isError and cells.structuredContent['rows'][1][0]['value'] == 12, cells
                diff = await session.call_tool('compare_cells', {'before': str(original), 'after': str(calculated), 'sheet': 'Sheet', 'cell_range': 'A1:A2'})
                assert not diff.isError and any(item['cell'] == 'A2' and item['after']['value'] == 12 for item in diff.structuredContent['changes']), diff

                wrong = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get'})
                assert wrong.isError, wrong
    print('MCP stdio smoke passed: discovery, authoring, read, preview and errors')


if __name__ == '__main__':
    asyncio.run(main())
