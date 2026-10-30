import { readFile, writeFile } from 'node:fs/promises';
const source=await readFile(new URL('../../../apps/chrome-extension/content-webmcp-main.js',import.meta.url),'utf8');
const output='// Generated from apps/chrome-extension/content-webmcp-main.js.\nexport const webMcpSource = '+JSON.stringify(source)+';\n';
const target=new URL('../src/webmcp-source.ts',import.meta.url);
if(process.argv.includes('--check')) {if(await readFile(target,'utf8')!==output)throw new Error('WebMCP source is out of date');}
else await writeFile(target,output);
