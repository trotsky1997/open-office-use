"""Verify the installed distribution outside the source checkout."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); target = root / 'site'; env = os.environ.copy()
    staged = root / 'source'; shutil.copytree(source, staged, ignore=shutil.ignore_patterns('__pycache__', 'build', '*.egg-info'))
    env.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '--target', str(target), str(staged)], cwd=root, env=env, check=True, capture_output=True)
    env['PYTHONPATH'] = str(target)
    cli = target / ('Scripts' if os.name == 'nt' else 'bin') / ('office-use.exe' if os.name == 'nt' else 'office-use')
    doctor = subprocess.run([str(cli), 'doctor'], cwd=root, env=env, check=True, capture_output=True, text=True)
    assert isinstance(json.loads(doctor.stdout), dict)
    spec = root / 'spec.json'; spec.write_text(json.dumps({'paragraphs': ['Installed distribution']}))
    doc = root / 'installed.docx'
    subprocess.run([str(cli), 'author', '--spec', str(spec), '--out', str(doc)], cwd=root, env=env, check=True, capture_output=True)
    inspected = subprocess.run([str(cli), 'inspect', str(doc)], cwd=root, env=env, check=True, capture_output=True, text=True)
    assert 'Installed distribution' in inspected.stdout
    subprocess.run([sys.executable, '-c', 'import office_mcp, snapshot; assert snapshot.__file__.startswith(' + repr(str(target)) + ')'], cwd=root, env=env, check=True, capture_output=True)
    async def check_mcp():
        params = StdioServerParameters(command=str(cli), args=['mcp'], env=env, cwd=str(root))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert 'office_doctor' in {tool.name for tool in (await client.list_tools()).tools}
                result = await client.call_tool('office_doctor', {})
                assert not result.isError and result.structuredContent['capabilities']['mcp_server']
    asyncio.run(check_mcp())
print('Install smoke passed: isolated CLI, document authoring, inspection and MCP handshake')
