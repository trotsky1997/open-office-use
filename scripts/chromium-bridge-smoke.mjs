import { spawn } from 'node:child_process';
import { access, mkdtemp, cp, readFile, writeFile, rm } from 'node:fs/promises';
import { constants } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir, endianness } from 'node:os';
import { join } from 'node:path';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { OpenBrowserUseClient, OpenBrowserUseBrowser, encodeFrame } from '../packages/open-browser-use-js/dist/index.js';
const root=fileURLToPath(new URL('..', import.meta.url));
const chromium=process.env.OBU_CHROMIUM_PATH;
if (!chromium) throw Error('Set OBU_CHROMIUM_PATH to a Chromium executable');
await Promise.all([access(chromium, constants.X_OK), access(join(root,'build/obu-bridge-smoke'), constants.X_OK)]);
const dir=await mkdtemp(join(tmpdir(),'obu-e2e-'));
const ext=join(dir,'extension'), profile=join(dir,'profile'), sock=join(dir,'native.sock');
let chrome,host,ws,browser;
const http=createServer((_req,res)=>{res.writeHead(200,{'Content-Type':'text/html'});res.end('<h1>Fixture</h1><button onclick="this.textContent=\'Done\';window.trusted=event.isTrusted">Save</button><label><input type="checkbox">Alerts</label><input type="range" aria-label="Volume" value="10" oninput="window.dragTrusted=event.isTrusted">');});
try {
 await cp(join(root,'apps/chrome-extension'),ext,{recursive:true});
 const background=join(ext,'background.js');
 await writeFile(background,(await readFile(background,'utf8'))+'\nglobalThis.__testBackend=backend; peer.sendNotification=(method,params)=>console.log("__OBU_EVENT__"+JSON.stringify({jsonrpc:"2.0",method,params}));\n');
 http.listen(0,'127.0.0.1'); await once(http,'listening');
 chrome=spawn(chromium, ['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`,`--disable-extensions-except=${ext}`,`--load-extension=${ext}`,'about:blank'],{stdio:'ignore'});
 let port; for(let i=0;i<100;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await new Promise(r=>setTimeout(r,100));}}
 if(!port)throw Error('Chromium did not start');
 let target; for(let i=0;i<100;i++){target=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='service_worker'&&t.url.endsWith('/background.js'));if(target)break;await new Promise(r=>setTimeout(r,100));}
 if(!target)throw Error('Extension worker unavailable');
 ws=new WebSocket(target.webSocketDebuggerUrl); await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
 let sequence=0;const waiting=new Map();
 const cdp=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=event=>{const message=JSON.parse(event.data);const pending=waiting.get(message.id);if(pending){waiting.delete(message.id);message.error?pending.reject(Error(message.error.message)):pending.resolve(message.result);return;}if(message.method==='Runtime.consoleAPICalled'){const value=message.params.args?.[0]?.value;if(typeof value==='string'&&value.startsWith('__OBU_EVENT__'))host?.stdin.write(encodeFrame(JSON.parse(value.slice(13))));}};
 await cdp('Runtime.enable');
 host=spawn(join(root,'build/obu-bridge-smoke'),['host','--socket-dir',dir,'--socket-path',sock],{stdio:['pipe','pipe','pipe']});
 host.stderr.resume(); host.stdin.on('error',()=>{});
 let bytes=Buffer.alloc(0), chain=Promise.resolve(); host.stdout.on('data',chunk=>{bytes=Buffer.concat([bytes,chunk]);while(bytes.length>=4){const len=endianness()==='LE'?bytes.readUInt32LE():bytes.readUInt32BE();if(bytes.length<len+4)break;const req=JSON.parse(bytes.subarray(4,len+4));bytes=bytes.subarray(len+4);chain=chain.then(async()=>{const expression=`(async()=>{try { const r=${JSON.stringify(req)}; const value=await globalThis.__testBackend[r.method](r.params||{}); return {jsonrpc:'2.0',id:r.id,result:value??{}}; } catch(e) {return {jsonrpc:'2.0',id:${JSON.stringify(req.id)},error:{code:-32000,message:String(e.message||e)}}}})()`;const result=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);host.stdin.write(encodeFrame(result.result.value));}).catch(e=>{console.error(e);host.kill();});}});
 for(let i=0;i<100;i++){try{await readFile(join(dir,'active.json'));break;}catch{await new Promise(r=>setTimeout(r,50));}}
 const client=new OpenBrowserUseClient({socketPath:sock,sessionId:'isolated-e2e',timeoutMs:15000}); browser=new OpenBrowserUseBrowser({client}); await browser.connect();
 const info=await client.getInfo(); assert.equal(info.type,'extension');
 const tab=await browser.newTab(); await tab.goto(`http://127.0.0.1:${http.address().port}/`,{timeoutMs:15000});
 const state=await tab.observe(); const button=state.nodes.find(n=>n.role==='button'&&n.name==='Save'); assert.ok(button);
 assert.match(state.text,/checked="false"/);
 await tab.click(button.index,state.snapshotId);
 const result=await tab.evaluate('({text:document.querySelector("button").textContent,trusted:window.trusted})'); assert.deepEqual(result,{text:'Done',trusted:true});
 const diff=await tab.observe({diff:true});assert.match(diff.text,/\+ .*button.*Done/);
 const checkbox=diff.nodes.find(node=>node.role==='checkbox'&&node.name==='Alerts');assert.ok(checkbox);
 await tab.click(checkbox.index,diff.snapshotId);
 const checked=await tab.observe({diff:true});assert.match(checked.text,/\+ .*checked="true"/);
 const drag=await tab.evaluate('(()=>{const r=document.querySelector("input[type=range]").getBoundingClientRect();return {from:[r.left+r.width*.15,r.top+r.height/2],to:[r.left+r.width*.85,r.top+r.height/2]}})()');
 await tab.drag(drag.from,drag.to);
 const slider=await tab.evaluate('({value:Number(document.querySelector("input[type=range]").value),trusted:window.dragTrusted})');assert.ok(slider.value>50);assert.equal(slider.trusted,true);
 await tab.evaluate(`(()=>{const host=document.createElement('div');document.body.append(host);const outer=host.attachShadow({mode:'open'});outer.innerHTML='<div></div>';const inner=outer.querySelector('div').attachShadow({mode:'closed'});inner.innerHTML='<button>Shadow Action</button>';window.fixtureShadowButton=inner.querySelector('button');window.fixtureShadowButton.onclick=e=>window.shadowTrusted=e.isTrusted})()`);
 const shadow=await tab.observe();const shadowButton=shadow.nodes.find(node=>node.role==='button'&&node.name==='Shadow Action');assert.ok(shadowButton);
 await tab.click(shadowButton.index,shadow.snapshotId);assert.equal(await tab.evaluate('window.shadowTrusted'),true);
 await tab.evaluate(`(()=>{const overlay=document.createElement('div');overlay.id='overlay';Object.assign(overlay.style,{position:'fixed',inset:'0',zIndex:'9999'});document.body.append(overlay)})()`);
 const covered=await tab.observe();const coveredButton=covered.nodes.find(node=>node.name==='Shadow Action');assert.ok(coveredButton);
 await assert.rejects(tab.click(coveredButton.index,covered.snapshotId),/covered/);
 await tab.evaluate('document.querySelector("#overlay").remove()');
 const png=await tab.getScreenshot();assert.equal(png.subarray(1,4).toString(),'PNG');
 await client.finalizeTabs([]);
 const repl=spawn(process.execPath,[join(root,'packages/open-browser-use-js/dist/repl-cli.js')],{stdio:['pipe','pipe','pipe'],env:{...process.env,OBU_SOCKET_DIR:dir}}); repl.stderr.resume();
 const lines=createInterface({input:repl.stdout})[Symbol.asyncIterator](); let id=0;
 const call=async(code)=>{const requestId=++id;repl.stdin.write(JSON.stringify({jsonrpc:'2.0',id:requestId,method:'tools/call',params:{name:'js',arguments:{code}}})+'\n');const response=JSON.parse((await lines.next()).value);assert.equal(response.id,requestId);assert.notEqual(response.result?.isError,true,JSON.stringify(response));return response.result;};
 try {
  await call(`const browser = await connectBrowser(); const tab = await browser.newTab(); await tab.goto(${JSON.stringify(`http://127.0.0.1:${http.address().port}/`)})`);
  await call('const state = await tab.observe(); const button = state.nodes.find(n => n.role === "button" && n.name === "Save"); await tab.click(button.index,state.snapshotId)');
  const output=await call('nodeRepl.write(await tab.evaluate("window.trusted"))');assert.equal(output.content[0].text,'true');
  const image=await call('nodeRepl.emitImage(await tab.getScreenshot())');assert.equal(image.content[0].type,'image');
  await call('await browser.client.finalizeTabs([])');
 } finally {const exited=once(repl,'exit');repl.stdin.end();await exited;}
 console.log('Chromium extension backend + Go relay + SDK/REPL: observe, trusted click and drag, nested shadow and overlay, diff, screenshot, cleanup passed (test CDP bridge)');
} finally {
 browser?.close(); ws?.close();
 for (const child of [host,chrome]) if (child && child.exitCode === null && child.signalCode === null) {
  const exited=once(child,'exit'); child.kill('SIGTERM'); await exited;
 }
 http.close(); await rm(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
