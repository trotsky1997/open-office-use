"""Check the stdio MCP lifecycle and real artifact operations."""
import asyncio
import sys
import tempfile
from pathlib import Path

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
                assert {t.name for t in tools.tools} == {'inspect_file', 'structured_read', 'apply_batch', 'render_pdf', 'preview_pages', 'view_page'}
                output = root / 'report.docx'
                operations = [{'command': 'add', 'parent': '/body', 'type': 'paragraph', 'props': {'text': 'MCP works'}}]
                created = await session.call_tool('apply_batch', {'output': str(output), 'operations': operations})
                assert not created.isError and output.exists(), created
                readback = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get', 'target': '/body/p[1]'})
                assert not readback.isError and 'MCP works' in str(readback), readback
                invalid = await session.call_tool('apply_batch', {'output': str(output), 'operations': operations})
                assert invalid.isError and 'already exists' in str(invalid), invalid
                images = await session.call_tool('preview_pages', {'file': str(output), 'output_dir': str(root / 'pages')})
                assert not images.isError, images
                paths = images.structuredContent['pages']
                assert paths and Path(paths[0]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                image = await session.call_tool('view_page', {'file': paths[0]})
                assert not image.isError and image.content[0].type == 'image' and image.content[0].mimeType == 'image/png', image
                wrong = await session.call_tool('structured_read', {'file': str(output), 'mode': 'get'})
                assert wrong.isError, wrong
    print('MCP stdio smoke passed: discovery, authoring, read, preview and errors')


if __name__ == '__main__':
    asyncio.run(main())
