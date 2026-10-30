import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import { endianness, tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { IabConnections } from '../dist/transport.js';
import { frame } from '../dist/wire.js';
import { connectExampleMcp } from '../../../examples/electron-iab/mcp.mjs';

for (const transport of ['private', 'socket']) test(`IAB REPL uses a host-authorized ${transport} scope and honors revocation`, { skip: transport === 'socket' && !['darwin', 'linux'].includes(process.platform) }, async () => {
  const calls = [];
  const connections = new IabConnections({
    instanceId:'fixture', hasScope:id => id === 'task', subscribe:() => () => {},
    async dispatch(scope, method, params) { calls.push({scope, method, params}); return { id: 42 }; }
  });
  const child = spawn(process.env.OBU_TEST_NODE ?? process.execPath, [fileURLToPath(new URL('../dist/repl-mcp.js', import.meta.url))], { stdio:['pipe','pipe','pipe','pipe'], env:{...process.env, ELECTRON_RUN_AS_NODE:'1'} });
  await once(child,'spawn');
  child.stdio[3].on('error', () => {});
  let grant;
  if (transport === 'private') grant = connections.servePrivate(child.stdio[3], 'task', { ttlMs:10_000 });
  else {
    await connections.openSocket();
    const bootstrap = connections.grant('task', 'socket', { ttlMs:10_000 }, child.pid);
    child.stdio[3].write(frame({jsonrpc:'2.0', method:'iab.bootstrap', params:bootstrap}));
    grant = { revoke:() => connections.revoke(bootstrap.grantId) };
  }
  let mcp;
  try {
    mcp = await connectExampleMcp({child, revoke:grant.revoke});
    const run = code => mcp.callTool('js', {code});
    assert.equal((await run('const browser = await connectBrowser(); const tab = await browser.newTab()')).isError, undefined);
    assert.equal((await run('nodeRepl.write(tab.id)')).content[0].text, '42');
    assert.equal(calls[0].scope, 'task');
    assert.equal(calls[0].params.session_id, 'task');
    assert.equal((await run('nodeRepl.write((await getBrowserState()).available[0].kind)')).content[0].text,'embedded');
    assert.equal((await run('nodeRepl.write(typeof discoverBrowsers)')).content[0].text,'undefined');
    assert.equal((await run('nodeRepl.write((await connectBrowser({browserId:"host"})) === browser)')).content[0].text,'true');
    assert.equal((await run('await connectBrowser({browserId:"other"})')).isError,true);
    assert.equal(calls.at(-1).method,'getTabs');
    const count = calls.length;
    assert.equal((await run('await browser.client.request("getTabs", {session_id:"other"})')).isError, true);
    assert.equal(calls.length, count);
    grant.revoke();
    assert.equal((await run('await browser.getTabs()')).isError, true);
    assert.equal((await run('nodeRepl.write(typeof (await getBrowserState()).sessions[0].error)')).content[0].text,'string');
  } finally {
    if (mcp) await mcp.close(); else child.kill();
    await connections.dispose();
  }
});

test('host can explicitly enable extension discovery and route each backend independently', async () => {
  const directory=await mkdtemp(join(tmpdir(),'obu-mixed-')), socketPath=join(directory,'chrome.sock');
  const requests=[];
  const server=createServer(socket=>{let data=Buffer.alloc(0);socket.on('data',chunk=>{data=Buffer.concat([data,chunk]);while(data.length>=4){
    const size=endianness()==='LE'?data.readUInt32LE(0):data.readUInt32BE(0);if(data.length<size+4)return;
    const request=JSON.parse(data.subarray(4,size+4));data=data.subarray(size+4);requests.push(request);
    const result=request.method==='getInfo'?{browser:'chrome'}:request.method==='getTabs'?[{id:7,title:'Chrome tab'}]:{};
    socket.write(frame({jsonrpc:'2.0',id:request.id,result}));
  }});});
  server.listen(socketPath);await once(server,'listening');
  const connections=new IabConnections({instanceId:'fixture',hasScope:id=>id==='task',subscribe:()=>()=>{},
    async dispatch(_scope,method){return method==='getTabs'?[{id:42,title:'Host tab'}]:{};}});
  const child=spawn(process.env.OBU_TEST_NODE??process.execPath,[fileURLToPath(new URL('../dist/repl-mcp.js',import.meta.url)),'--allow-extension-discovery'],
    {stdio:['pipe','pipe','pipe','pipe'],env:{...process.env,ELECTRON_RUN_AS_NODE:'1',OBU_SOCKET_DIR:directory}});
  await once(child,'spawn');child.stdio[3].on('error',()=>{});
  const grant=connections.servePrivate(child.stdio[3],'task',{ttlMs:10_000});let mcp;
  try {
    mcp=await connectExampleMcp({child,revoke:grant.revoke});const run=code=>mcp.callTool('js',{code});
    assert.equal((await run('nodeRepl.write((await getBrowserState()).available.map(b=>b.kind).join(","))')).content[0].text,'embedded,extension');
    assert.equal((await run('await connectBrowser()')).isError,true);
    assert.equal((await run(`const host = await connectBrowser({browserId:'host'}); const chrome = await connectBrowser({browserId:${JSON.stringify(socketPath)}})`)).isError,undefined);
    assert.equal((await run('nodeRepl.write((await getBrowserState()).sessions.map(s=>s.tabs[0].title).sort().join(","))')).content[0].text,'Chrome tab,Host tab');
    grant.revoke();
    assert.equal((await run('nodeRepl.write((await chrome.getTabs())[0].title)')).content[0].text,'Chrome tab');
    assert.equal((await run('nodeRepl.write(typeof (await getBrowserState()).sessions.find(s=>s.browserId==="host").error)')).content[0].text,'string');
    assert.ok(requests.every(request=>request.params.session_id.startsWith('obu-repl-')));
  } finally {
    if(mcp)await mcp.close();else child.kill();
    await connections.dispose();const stopped=once(server,'close');server.close();await stopped;await rm(directory,{recursive:true,force:true});
  }
});
