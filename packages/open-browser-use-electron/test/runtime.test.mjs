import { mkdtemp, writeFile, rm, symlink, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { IabRuntime } from '../dist/runtime.js';
import { connectSocketIab } from '../dist/client.js';
import { fakeElectron } from './fake-electron.mjs';
import { once } from 'node:events';

function setup(t) {
  const adapter = fakeElectron(), runtime = new IabRuntime(adapter, 'test');
  runtime.profiles.open({ id: 'work' });
  const a = runtime.scopes.open({ id: 'a', profileId: 'work' });
  const b = runtime.scopes.open({ id: 'b', profileId: 'work' });
  t.after(() => runtime.dispose()); return { runtime, adapter, a, b };
}
test('file chooser requires a scoped grant and explicit file authorization', async t => {
  const {runtime,adapter,a,b}=setup(t), tab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-upload-test-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const allowed=join(dir,'allowed.txt'),other=join(dir,'other.txt');await writeFile(allowed,'allowed');await writeFile(other,'other');
  await a.files.authorize([allowed]);
  await assert.rejects(runtime.dispatch('a','waitForFileChooser',{tabId:tab.id,waitId:'00000000-0000-0000-0000-000000000000'},['page.control']),/DENIED/);
  await assert.rejects(a.call('executeCdp',{target:{tabId:tab.id},method:'DOM.setFileInputFiles',commandParams:{files:[allowed]}}),/outside page permissions/);
  const debuggerApi=adapter.views[0].webContents.debugger;
  debuggerApi.emit('message',{},'Target.attachedToTarget',{sessionId:'child',targetInfo:{type:'iframe'}},undefined);
  let ready=false;const unsubscribe=runtime.subscribe(e=>{if(e.method==='onFileChooserWaitReady')ready=true;});
  const pending=runtime.dispatch('a','waitForFileChooser',{tabId:tab.id,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'},['page.control','files.upload']);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(ready,true);
  debuggerApi.emit('message',{},'Page.fileChooserOpened',{backendNodeId:42,mode:'selectSingle'},'child');
  const chooser=await pending;unsubscribe();
  await assert.rejects(runtime.dispatch('b','setFileChooserFiles',{fileChooserId:chooser.fileChooserId,files:[allowed]},['page.control','files.upload']),/unavailable/);
  await assert.rejects(runtime.dispatch('a','setFileChooserFiles',{fileChooserId:chooser.fileChooserId,files:[other]},['page.control','files.upload']),/not authorized/);
  await runtime.dispatch('a','setFileChooserFiles',{fileChooserId:chooser.fileChooserId,files:[allowed]},['page.control','files.upload']);
  const command=debuggerApi.commands.at(-1);assert.equal(command.method,'DOM.setFileInputFiles');assert.equal(command.sessionId,'child');assert.deepEqual(command.params.files,[await import('node:fs/promises').then(fs=>fs.realpath(allowed))]);
  await assert.rejects(a.call('setFileChooserFiles',{fileChooserId:chooser.fileChooserId,files:[allowed]}),/unavailable/);
});

test('upload decisions recheck grant and resolve symlinks against the approved files', async t => {
  const {runtime,adapter,a}=setup(t),tab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-upload-revoke-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const allowed=join(dir,'allowed.txt'),other=join(dir,'other.txt'),link=join(dir,'link');
  await writeFile(allowed,'allowed');await writeFile(other,'other');await symlink(allowed,link);await a.files.authorize([link]);
  const debug=adapter.views[0].webContents.debugger;
  async function chooser(){
    const pending=runtime.dispatch('a','waitForFileChooser',{tabId:tab.id,timeoutMs:1000},['page.control','files.upload']);
    await new Promise(resolve=>setImmediate(resolve));debug.emit('message',{},'Page.fileChooserOpened',{backendNodeId:9,mode:'selectSingle'},undefined);
    return (await pending).fileChooserId;
  }
  let id=await chooser();await unlink(link);await symlink(other,link);
  await assert.rejects(runtime.dispatch('a','setFileChooserFiles',{fileChooserId:id,files:[link]},['page.control','files.upload']),/not authorized/);
  let checks=0;await assert.rejects(runtime.dispatch('a','setFileChooserFiles',{fileChooserId:id,files:[allowed]},['page.control','files.upload'],()=>++checks===1),/REVOKED/);
  assert.equal(debug.commands.some(command=>command.method==='DOM.setFileInputFiles'),false);
  await a.files.authorize([]);await assert.rejects(a.call('setFileChooserFiles',{fileChooserId:id,files:[allowed]}),/not authorized/);
});

test('authorized socket client can complete the file chooser handshake', {skip:!['darwin','linux'].includes(process.platform)}, async t => {
  const {runtime,adapter,a}=setup(t), tab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-upload-socket-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const file=join(dir,'fixture.txt');await writeFile(file,'fixture');await a.files.authorize([file]);
  await runtime.connections.openSocket();
  const bootstrap=runtime.connections.grant('a','socket',{ttlMs:5000,operations:['page.control','files.upload']},process.pid);
  const client=await connectSocketIab(bootstrap);t.after(()=>client.close());
  const ready=await client.browser().tab(tab.id).prepareFileChooser({timeoutMs:1000});
  const waiting=ready.wait();
  adapter.views[0].webContents.debugger.emit('message',{},'Page.fileChooserOpened',{backendNodeId:7,mode:'selectSingle'},undefined);
  const chooser=await waiting;await chooser.setFiles(file);
  assert.equal(adapter.views[0].webContents.debugger.commands.at(-1).method,'DOM.setFileInputFiles');
});

test('clipboard requires independent scoped read and write grants',async t=>{
  const {runtime,adapter,a,b}=setup(t),tab=await a.tabs.create(),other=await b.tabs.create();
  const read=['page.control','clipboard.read'],write=['page.control','clipboard.write'];
  assert.equal((await runtime.dispatch('a','getInfo',{},['page.control'])).capabilities.clipboard,false);
  assert.equal((await runtime.dispatch('a','getInfo',{},read)).capabilities.clipboard,true);
  assert.equal((await runtime.dispatch('a','getInfo',{},read)).capabilities.clipboardRead,true);
  assert.equal((await runtime.dispatch('a','getInfo',{},read)).capabilities.clipboardWrite,false);
  await assert.rejects(runtime.dispatch('a','writeClipboardText',{tabId:tab.id,text:'secret'},read),/DENIED/);
  await assert.rejects(runtime.dispatch('a','readClipboardText',{tabId:tab.id},write),/DENIED/);
  await assert.rejects(runtime.dispatch('b','readClipboardText',{tabId:tab.id},read),/tab/i);
  await runtime.dispatch('a','writeClipboardText',{tabId:tab.id,text:'fixture'},write);
  assert.equal((await runtime.dispatch('a','readClipboardText',{tabId:tab.id},read)).text,'fixture');
  const items=[{entries:[{mime_type:'text/plain',text:'plain'},{mime_type:'image/png',base64:'AQID'}]}];
  await runtime.dispatch('a','writeClipboard',{tabId:tab.id,items},write);
  assert.deepEqual((await runtime.dispatch('a','readClipboard',{tabId:tab.id},read)).items,[{entries:items[0].entries,presentation_style:'unspecified'}]);
  await assert.rejects(runtime.dispatch('a','writeClipboard',{tabId:tab.id,items:[{entries:[{mime_type:'image/png',base64:'invalid!'}]}]},write),/INVALID/);
  assert.equal((await runtime.dispatch('a','readClipboardText',{tabId:tab.id},read)).text,'plain');
  await assert.rejects(runtime.dispatch('a','writeClipboardText',{tabId:tab.id,text:'x'.repeat(3*1024*1024+1)},write),/TOO_LARGE/);
  let release;adapter.clipboard.readText=()=>new Promise(resolve=>{release=resolve;});const controller=new AbortController();
  const pending=runtime.dispatch('b','readClipboardText',{tabId:other.id},read,()=>!controller.signal.aborted,controller.signal);
  controller.abort();release('private');await assert.rejects(pending,/REVOKED/);
  let finishWrite;adapter.clipboard.writeText=()=>new Promise(resolve=>{finishWrite=resolve;});const writer=new AbortController();
  const writing=runtime.dispatch('a','writeClipboardText',{tabId:tab.id,text:'issued'},write,()=>!writer.signal.aborted,writer.signal);
  writer.abort();finishWrite();await assert.rejects(writing,/REVOKED/);
  delete adapter.clipboard;assert.equal((await runtime.dispatch('a','getInfo',{},read)).capabilities.clipboard,false);
  await assert.rejects(runtime.dispatch('a','readClipboardText',{tabId:tab.id},read),/UNAVAILABLE/);
});

test('clipboard socket grant supports SDK text and structured data', {skip:!['darwin','linux'].includes(process.platform)}, async t=>{
  const {runtime,a}=setup(t),tab=await a.tabs.create();await runtime.connections.openSocket();
  const grant=runtime.connections.grant('a','socket',{ttlMs:5000,operations:['page.control','clipboard.read','clipboard.write']},process.pid);
  const client=await connectSocketIab(grant);t.after(()=>client.close());const clipboard=client.browser().tab(tab.id).clipboard;
  await clipboard.writeText('socket fixture');assert.equal(await clipboard.readText(),'socket fixture');
  await clipboard.write([{entries:[{mimeType:'text/plain',text:'text'},{mimeType:'image/png',base64:'AQID'}]}]);
  assert.deepEqual((await clipboard.read())[0].entries,[{mimeType:'text/plain',text:'text'},{mimeType:'image/png',base64:'AQID'}]);
  const readGrant=runtime.connections.grant('a','socket',{ttlMs:5000,operations:['page.control','clipboard.read']},process.pid);
  const reader=await connectSocketIab(readGrant);t.after(()=>reader.close());const readClipboard=reader.browser().tab(tab.id).clipboard;
  assert.equal(await readClipboard.readText(),'text');
  await assert.rejects(readClipboard.writeText('unauthorized'),/DENIED/);
  assert.equal(await clipboard.readText(),'text');
});

function fakeDownload(filename='fixture.txt',total=10) {
  const item=Object.assign(new EventEmitter(),{filename,total,received:0,cancelled:false,path:'',
    getFilename(){return this.filename;},getURL(){return 'https://example.test/fixture';},getTotalBytes(){return this.total;},getReceivedBytes(){return this.received;},
    setSavePath(path){this.path=path;},cancel(){this.cancelled=true;this.emit('done',{},'cancelled');}});
  return item;
}

test('downloads require scoped authorization and match the originating page',async t=>{
  const {runtime,adapter,a,b}=setup(t),tab=await a.tabs.create(),otherTab=await b.tabs.create(),sameScopeTab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-download-test-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const wc=adapter.views[0].webContents,other=adapter.views[1].webContents,session=wc.session;
  const denied={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',denied,fakeDownload(),wc);assert.equal(denied.blocked,true);
  await a.downloads.configure({directory:dir,maxBytes:100});
  assert.equal((await runtime.dispatch('a','getInfo',{},['page.control'])).capabilities.downloads,false);
  assert.equal((await runtime.dispatch('a','getInfo',{},['page.control','files.download'])).capabilities.downloads,true);
  await assert.rejects(runtime.dispatch('a','waitForDownload',{tabId:tab.id},['page.control']),/DENIED/);
  let ready=false;const unsubscribe=runtime.subscribe(event=>{if(event.method==='onDownloadWaitReady')ready=true;});
  const pending=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'},['page.control','files.download']);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(ready,true);
  const unrelated={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',unrelated,fakeDownload(),other);assert.equal(unrelated.blocked,true);
  const sameScope={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',sameScope,fakeDownload(),adapter.views[2].webContents);assert.equal(sameScope.blocked,true);
  const item=fakeDownload('../../private.txt'),event={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',event,item,wc);
  const duplicate={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',duplicate,fakeDownload(),wc);assert.equal(duplicate.blocked,true);
  const result=await pending;unsubscribe();assert.equal(result.url,'https://example.test/fixture');const resolvedDir=await import('node:fs/promises').then(fs=>fs.realpath(dir));assert.equal(event.blocked,false);assert.ok(item.path.startsWith(resolvedDir+'/'));assert.ok(item.path.endsWith('.txt'));assert.notEqual(item.path,join(resolvedDir,'private.txt'));
  await assert.rejects(runtime.dispatch('b','downloadPath',{downloadId:result.downloadId},['page.control','files.download']),/UNAVAILABLE/);
  const path=runtime.dispatch('a','downloadPath',{downloadId:result.downloadId,timeoutMs:1000},['page.control','files.download']);
  item.received=10;item.emit('done',{},'completed');assert.equal((await path).path,item.path);
});

test('download revocation and size limits cancel the item',async t=>{
  const {runtime,adapter,a}=setup(t),tab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-download-limit-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  await a.downloads.configure({directory:dir,maxBytes:100});const wc=adapter.views[0].webContents,session=wc.session;
  const controller=new AbortController();
  const pending=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000},['page.control','files.download'],()=>!controller.signal.aborted,controller.signal);
  const item=fakeDownload('fixture.txt',10);session.emit('will-download',{preventDefault(){}},item,wc);
  const result=await pending;const path=runtime.dispatch('a','downloadPath',{downloadId:result.downloadId},['page.control','files.download']);
  controller.abort();assert.equal((await path).path,null);await new Promise(resolve=>setImmediate(resolve));assert.equal(item.cancelled,true);
  const oversized=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000},['page.control','files.download']);
  const denied={blocked:false,preventDefault(){this.blocked=true;}};session.emit('will-download',denied,fakeDownload('big.bin',101),wc);
  await assert.rejects(oversized,/SIZE_LIMIT/);assert.equal(denied.blocked,true);
  const streaming=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000},['page.control','files.download']);
  const large=fakeDownload('unknown.bin',0);session.emit('will-download',{preventDefault(){}},large,wc);const started=await streaming;
  large.received=101;large.emit('updated',{},'progressing');assert.equal((await a.call('downloadPath',{downloadId:started.downloadId})).path,null);await new Promise(resolve=>setImmediate(resolve));assert.equal(large.cancelled,true);
  const active=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000},['page.control','files.download']);
  const activeItem=fakeDownload('active.bin',10);session.emit('will-download',{preventDefault(){}},activeItem,wc);const activeResult=await active;
  const activePath=runtime.dispatch('a','downloadPath',{downloadId:activeResult.downloadId},['page.control','files.download']);
  const pathRejected=assert.rejects(activePath,/REVOKED/);
  await a.downloads.configure(null);await pathRejected;await new Promise(resolve=>setImmediate(resolve));assert.equal(activeItem.cancelled,true);
  await a.downloads.configure({directory:dir,maxBytes:100});
  const waiting=runtime.dispatch('a','waitForDownload',{tabId:tab.id,timeoutMs:1000},['page.control','files.download']);
  const revoked=assert.rejects(waiting,/REVOKED/);await a.downloads.configure(null);await revoked;
});

test('authorized socket client receives the correct page download and grant revocation cancels it', {skip:!['darwin','linux'].includes(process.platform)}, async t => {
  const {runtime,adapter,a}=setup(t),tab=await a.tabs.create();
  const dir=await mkdtemp(join(tmpdir(),'obu-download-socket-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  await a.downloads.configure({directory:dir,maxBytes:100});await runtime.connections.openSocket();
  const grant=runtime.connections.grant('a','socket',{ttlMs:5000,operations:['page.control','files.download']},process.pid);
  const client=await connectSocketIab(grant);t.after(()=>client.close());
  const ready=await client.browser().tab(tab.id).prepareDownload({timeoutMs:1000});
  const item=fakeDownload('fixture.txt'),wc=adapter.views[0].webContents;
  wc.session.emit('will-download',{preventDefault(){throw new Error('unexpected rejection');}},item,wc);
  const download=await ready.wait();assert.ok(download.id);
  runtime.connections.revoke(grant.grantId);await new Promise(resolve=>setImmediate(resolve));assert.equal(item.cancelled,true);
});

test('managed clients opt into piped stdin without exposing the private bootstrap', async t => {
  const { runtime, a } = setup(t);
  const { child } = await runtime.launchClient({scopeId:a.id,command:process.execPath,
    args:['-e','process.stdin.on("data", chunk => process.stdout.write(chunk));'],stdin:'pipe',ttlMs:5000});
  let output=''; child.stdout.on('data',chunk=>{output+=chunk;});
  const closed=once(child,'close'); child.stdin.end('agent MCP input\n');
  assert.equal((await closed)[0],0); assert.equal(output,'agent MCP input\n');
  const normal = await runtime.launchClient({scopeId:a.id,command:process.execPath,args:['-e',''],ttlMs:5000});
  assert.equal(normal.child.stdin,null); await once(normal.child,'close');
  await assert.rejects(runtime.launchClient({scopeId:a.id,command:process.execPath,stdin:'inherit',ttlMs:5000}),/stdin/);
});
test('tab loading, redirects, failure and retry are scoped and reset on navigation', async t => {
  const { runtime, adapter, a, b } = setup(t);
  const x=await a.tabs.create(), y=await b.tabs.create();
  const wc=adapter.views[0].webContents, events=[];
  runtime.subscribe(event=>{if(event.method==='onTabUpdated') events.push(event);});
  wc.emit('did-start-navigation',{url:'https://example.com/',isMainFrame:true,isSameDocument:false});
  wc.emit('did-start-loading');
  assert.equal(a.tabs.list()[0].loading,true);
  assert.equal(a.tabs.list()[0].pendingUrl,'https://example.com/');
  assert.equal(b.tabs.list()[0].loading,false);
  wc.emit('did-redirect-navigation',{},'https://example.com/next',false,true);
  assert.equal(a.tabs.list()[0].pendingUrl,'https://example.com/next');
  wc.emit('did-fail-load',{},-105,'ERR_NAME_NOT_RESOLVED','https://example.com/next',true);
  wc.emit('did-stop-loading');
  assert.equal(a.tabs.list()[0].loading,false);
  assert.equal(a.tabs.list()[0].pendingUrl,undefined);
  assert.equal(a.tabs.list()[0].loadError.code,-105);
  wc.emit('did-start-navigation',{},'https://example.org/',false,true);
  assert.equal(a.tabs.list()[0].loadError,undefined);
  wc.emit('did-fail-load',{},-3,'ERR_ABORTED','https://example.org/',true);
  wc.emit('did-fail-load',{},-105,'ERR_NAME_NOT_RESOLVED','https://frame.example/',false);
  assert.equal(a.tabs.list()[0].loadError,undefined);
  assert.ok(events.every(event=>event.scopeId==='a' && event.params.tab.id===x.id && event.params.tab.id!==y.id));
});
test('one scope owns independent tabs; profiles share storage, not tab ownership', async t => {
  const { runtime, adapter, a, b } = setup(t);
  const x = await a.tabs.create({ url: 'https://example.com/a' });
  const y = await a.tabs.create({ url: 'https://example.com/b' });
  const z = await b.tabs.create();
  assert.deepEqual(a.tabs.list().map(t => t.id), [x.id, y.id]);
  assert.equal(adapter.views[0].webContents.session, adapter.views[2].webContents.session);
  await assert.rejects(b.call('executeCdp', { target: { tabId: x.id }, method: 'Runtime.evaluate' }));
  await a.tabs.close(x.id);
  assert.deepEqual(a.tabs.list().map(t => t.id), [y.id]);
  assert.equal(b.tabs.list()[0].id, z.id);
  await assert.rejects(runtime.dispatch('a', 'getTabs', { session_id: 'b' }));
});
test('surface selection and hiding do not redirect automation or close tabs', async t => {
  const { runtime, adapter, a } = setup(t);
  const x = await a.tabs.create(), y = await a.tabs.create();
  const window = Object.assign(new EventEmitter(), { contentView: { addChildView() {}, removeChildView() {} } });
  const surface = runtime.surfaces.register({ id: 'panel', window, owner: adapter.views[0].webContents });
  surface.present(x.id); surface.present(y.id); surface.hide();
  await a.call('executeCdp', { target: { tabId: x.id }, method: 'Input.insertText', commandParams: { text: 'x' } });
  assert.equal(adapter.views[0].webContents.debugger.commands[0].params.text, 'x');
  assert.equal(a.tabs.list().length, 2);
  window.emit('closed'); assert.equal(a.tabs.list().length, 2);
});
test('background scroll uses wheel input and restores throttling', async t => {
  const { runtime, adapter, a } = setup(t);
  const tab = await a.tabs.create(), wc = adapter.views[0].webContents;
  let visible = false, minimized = false;
  const window = Object.assign(new EventEmitter(), {
    isVisible: () => visible, isMinimized: () => minimized,
    contentView: { addChildView() {}, removeChildView() {} }
  });
  const surface = runtime.surfaces.register({ id:'panel', window, owner:wc });
  const params = {x:100,y:100,xDistance:0,yDistance:-250,gestureSourceType:'mouse',preventFling:true};
  const send = (method, commandParams = {}) => a.call('executeCdp', { target:{tabId:tab.id}, method, commandParams });
  await assert.rejects(send('Input.synthesizeScrollGesture', params), /IAB_SCROLL_REQUIRES_PRESENTED_SURFACE/);
  await send('Runtime.evaluate');
  surface.present(tab.id);
  await send('Input.synthesizeScrollGesture', params);
  assert.deepEqual(wc.debugger.commands.at(-1).params, {type:'mouseWheel',x:100,y:100,deltaX:-0,deltaY:250});
  assert.equal(wc.backgroundThrottling, true);
  assert.ok(wc.isolatedCalls.some(call => call.scripts[0].code.includes('requestAnimationFrame')));
  await assert.rejects(send('Input.synthesizeScrollGesture', {...params, speed:100}), /IAB_BACKGROUND_SCROLL_UNSUPPORTED_GESTURE/);
  visible = true; minimized = true;
  await send('Input.synthesizeScrollGesture', params);
  assert.equal(wc.debugger.commands.at(-1).method, 'Input.dispatchMouseEvent');
  minimized = false;
  await send('Input.synthesizeScrollGesture', params);
  assert.equal(wc.debugger.commands.at(-1).method, 'Input.synthesizeScrollGesture');
});
test('a stalled background scroll releases the tab queue', async t => {
  const { runtime, adapter, a } = setup(t), tab = await a.tabs.create();
  const wc = adapter.views[0].webContents;
  const window = Object.assign(new EventEmitter(), { isVisible:()=>false, isMinimized:()=>false, contentView:{addChildView(){}, removeChildView(){}} });
  runtime.surfaces.register({id:'panel', window, owner:wc}).present(tab.id);
  wc.executeJavaScriptInIsolatedWorld = () => new Promise(() => {});
  const call = (method, commandParams = {}) => a.call('executeCdp', {target:{tabId:tab.id}, method, commandParams});
  await assert.rejects(call('Input.synthesizeScrollGesture', {x:1,y:1,xDistance:0,yDistance:-10,gestureSourceType:'mouse',preventFling:true}), /IAB_BACKGROUND_SCROLL_TIMEOUT/);
  assert.equal(wc.backgroundThrottling, true);
  await call('Runtime.evaluate');
});
test('dialog decisions bypass a blocked page command without crossing scopes', async t => {
  const { adapter, a, b }=setup(t), tab=await a.tabs.create(), commands=[];
  let release;
  adapter.views[0].webContents.debugger.sendCommand=async (method,params)=>{
    commands.push(method);
    if(method==='Runtime.evaluate')await new Promise(resolve=>{release=resolve;});
    if(method==='Page.handleJavaScriptDialog')release();
    return {};
  };
  const pending=a.call('executeCdp',{target:{tabId:tab.id},method:'Runtime.evaluate'});
  await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(b.call('executeCdp',{target:{tabId:tab.id},method:'Page.handleJavaScriptDialog',commandParams:{accept:true}}));
  await assert.rejects(a.call('executeCdp',{target:{tabId:tab.id},method:'Page.handleJavaScriptDialog',commandParams:{accept:'yes'}}),/Invalid dialog decision/);
  await a.call('executeCdp',{target:{tabId:tab.id},method:'Page.handleJavaScriptDialog',commandParams:{accept:false}});
  await pending;
  assert.deepEqual(commands,['Runtime.evaluate','Page.handleJavaScriptDialog']);
});

test('reject global CDP and unsafe navigation; enforce operation grants', async t => {
  const { runtime, a } = setup(t); const tab = await a.tabs.create();
  for (const method of ['Browser.close', 'Target.getTargets', 'Storage.clearDataForOrigin', 'Network.getAllCookies', 'DOM.setFileInputFiles']) {
    await assert.rejects(a.call('executeCdp', { target: { tabId: tab.id }, method }));
  }
  await assert.rejects(a.tabs.create({ url: 'file:///etc/passwd' }));
  await assert.rejects(a.call('executeCdp', { target: { tabId: tab.id }, method: 'Page.navigate', commandParams: { url: 'javascript:alert(1)' } }));
  await assert.rejects(a.call('executeCdp', { target: { tabId: tab.id }, method: 'Runtime.evaluate', commandParams: { expression: 'copy("test")', includeCommandLineAPI: true } }));
  await assert.rejects(runtime.dispatch('a', 'createTab', {}, ['tabs.read']));
  assert.equal((await runtime.dispatch('a', 'getTabs', {}, ['tabs.read'])).length, 1);
});
test('turn cleanup retains other turns, marked tabs and persistent tabs', async t => {
  const { a } = setup(t);
  const retained = await a.tabs.create({ turnId: 'one' });
  await a.call('markTab', { tabId: retained.id, status: 'handoff', turn_id: 'one' });
  const later = await a.tabs.create({ turnId: 'two' });
  await a.tabs.create({ turnId: 'one' });
  await a.call('turnEnded', { turn_id: 'one' });
  assert.deepEqual(a.tabs.list().map(t => t.id), [retained.id, later.id]);
  await a.call('turnEnded', { turn_id: 'two' }); assert.equal(a.tabs.list().length, 1);
});
test('revoking authorization stops queued input before dispatch', async t => {
  const { runtime, adapter, a } = setup(t); const tab = await a.tabs.create();
  let release; let count = 0; let allowed = true;
  adapter.views[0].webContents.debugger.sendCommand = async () => { count++; await new Promise(r => { release = r; }); return {}; };
  const params = { target: { tabId: tab.id }, method: 'Input.insertText', commandParams: { text: 'test' } };
  const first = runtime.dispatch('a', 'executeCdp', params, ['page.control'], () => allowed);
  await new Promise(r => setImmediate(r));
  const second = runtime.dispatch('a', 'executeCdp', params, ['page.control'], () => allowed);
  const denied = assert.rejects(second, /REVOKED/);
  allowed = false; release(); await first; await denied; assert.equal(count, 1);
});
test('disposal closes views and cleans listeners, including a crashed tab', async t => {
  const { runtime, adapter, a } = setup(t); await a.tabs.create(); await a.tabs.create();
  adapter.views[0].webContents.emit('render-process-gone');
  await Promise.all([runtime.dispose(), runtime.dispose()]); await runtime.dispose();
  assert.ok(adapter.views.every(v => v.webContents.isDestroyed()));
  assert.equal(adapter.views[0].webContents.debugger.listenerCount('message'), 0);
});
test('opener disposal tolerates native popup controllers already removed from their view', async t => {
  const { runtime, adapter, a } = setup(t);
  await a.tabs.create(); await a.tabs.create();
  const opener = adapter.views[0].webContents, popup = adapter.views[1].webContents;
  const close = opener.close.bind(opener);
  opener.close = () => { popup.close(); adapter.views[1].webContents = undefined; close(); };
  await runtime.dispose();
  assert.equal(opener.isDestroyed(), true); assert.equal(popup.isDestroyed(), true);
});
test('untrusted popup requests are denied at the scope tab limit', async t => {
  const { adapter, a } = setup(t);
  for (let i=0; i<32; i++) await a.tabs.create();
  assert.deepEqual(adapter.views[0].webContents.popup({url:'https://example.com'}), {action:'deny'});
  await assert.rejects(a.tabs.create(), /LIMIT/);
});
test('revocation during hidden view rendering prevents the pending mouse input', async t => {
  const { runtime, adapter, a } = setup(t); const tab = await a.tabs.create();
  let release, allowed = true;
  const commands = [];
  adapter.views[0].webContents.debugger.sendCommand = async method => {
    commands.push(method);
    if (method === 'Page.captureScreenshot') await new Promise(resolve => { release = resolve; });
    return {};
  };
  const input = runtime.dispatch('a','executeCdp', {target:{tabId:tab.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mousePressed',x:10,y:10}},['page.control'],()=>allowed);
  const denied = assert.rejects(input,/REVOKED/);
  await new Promise(resolve => setImmediate(resolve));
  allowed = false; release(); await denied;
  assert.deepEqual(commands, ['Page.captureScreenshot']);
});
test('oversized screenshots fail without closing the page queue', async t => {
  const { adapter, a } = setup(t), tab = await a.tabs.create();
  adapter.views[0].webContents.debugger.sendCommand = async method => method === 'Page.captureScreenshot' ? {data:'x'.repeat(8 * 1024 * 1024)} : {};
  await assert.rejects(a.call('executeCdp',{target:{tabId:tab.id},method:'Page.captureScreenshot'}),/IAB_SCREENSHOT_TOO_LARGE/);
  await a.call('executeCdp',{target:{tabId:tab.id},method:'Runtime.evaluate'});
});
test('stalled mouse preparation times out without issuing late input', async t => {
  const { runtime, adapter, a } = setup(t), tab = await a.tabs.create();
  const debuggerApi = adapter.views[0].webContents.debugger, commands = [];
  let release;
  debuggerApi.sendCommand = async method => {
    commands.push(method);
    if (method === 'Page.captureScreenshot') await new Promise(resolve => { release = resolve; });
    return {};
  };
  const screenshotTab = await a.tabs.create();
  const screenshotDebugger = adapter.views[1].webContents.debugger;
  let releaseScreenshot;
  screenshotDebugger.sendCommand = async method => {
    if (method === 'Page.captureScreenshot') await new Promise(resolve => { releaseScreenshot = resolve; });
    return {};
  };
  const params = {target:{tabId:tab.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:10,y:10}};
  await Promise.all([
    assert.rejects(a.call('executeCdp',params),/IAB_INPUT_PREPARATION_TIMEOUT/),
    assert.rejects(a.call('executeCdp',{target:{tabId:screenshotTab.id},method:'Page.captureScreenshot'}),/IAB_SCREENSHOT_TIMEOUT/),
  ]);
  releaseScreenshot();
  await a.call('executeCdp',{target:{tabId:tab.id},method:'Runtime.evaluate'});
  release(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(commands,['Page.captureScreenshot','Runtime.evaluate']);
});
test('visual feedback is opt-in and explicit activity remains scoped to owned tabs', async t => {
  const { runtime, adapter, a, b } = setup(t); const tab = await a.tabs.create();
  await a.call('executeCdp',{target:{tabId:tab.id},method:'Input.insertText',commandParams:{text:'plain'}});
  assert.equal(adapter.views[0].webContents.isolatedCalls.length,0);
  await runtime.visualFeedback.configure({cursor:true,edgeGlow:true});
  await assert.rejects(b.visualFeedback.setActive(tab.id,true),/NOT_OWNED/);
  await a.visualFeedback.setActive(tab.id,true);
  assert.equal(adapter.views[0].webContents.isolatedCalls[0].worldId,999);
});
test('revoking authorization while feedback renders prevents the actual input', async t => {
  const { runtime, adapter, a } = setup(t); const tab = await a.tabs.create();
  await runtime.visualFeedback.configure({cursor:true});
  let release, allowed=true;
  adapter.views[0].webContents.executeJavaScriptInIsolatedWorld = () => new Promise(resolve=>{release=resolve;});
  const input=runtime.dispatch('a','executeCdp',{target:{tabId:tab.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:20,y:20}},['page.control'],()=>allowed);
  const denied=assert.rejects(input,/REVOKED/); await new Promise(resolve=>setImmediate(resolve));
  allowed=false; release(true); await denied;
  assert.ok(!adapter.views[0].webContents.debugger.commands.some(command=>command.method==='Input.dispatchMouseEvent'));
});

test('frame debugger sessions stay inside their owning tab and permit iframe auto-attach only', async t => {
  const { runtime, adapter, a, b } = setup(t);
  const tab = await a.tabs.create(), other = await a.tabs.create();
  const debuggerApi = adapter.views[0].webContents.debugger, events = [];
  runtime.subscribe(event => events.push(event));
  const call = (target, method, commandParams = {}) => a.call('executeCdp', {target,method,commandParams});
  const config = {autoAttach:true,waitForDebuggerOnStart:false,flatten:true,filter:[{type:'iframe',exclude:false},{exclude:true}]};
  await assert.rejects(call({tabId:tab.id},'Target.setAutoAttach',{...config,filter:[{type:'page'}]}), /Invalid frame/);
  await assert.rejects(call({tabId:tab.id},'Target.setAutoAttach',{...config,waitForDebuggerOnStart:true}), /Invalid frame/);
  await assert.rejects(call({tabId:tab.id,sessionId:'unowned'},'Runtime.evaluate'), /Invalid CDP frame session/);
  await call({tabId:tab.id},'Target.setAutoAttach',config);
  debuggerApi.emit('message',{},'Target.attachedToTarget',{sessionId:'child',targetInfo:{type:'iframe',targetId:'frame',parentFrameId:'root'}},undefined);
  assert.equal(events.at(-1).params.source.tabId,tab.id);
  await call({tabId:tab.id,sessionId:'child'},'Runtime.evaluate',{expression:'1'});
  assert.equal(debuggerApi.commands.at(-1).sessionId,'child');
  await runtime.visualFeedback.configure({cursor:true});
  await a.call('executeCdp',{target:{tabId:tab.id,sessionId:'child'},method:'Input.dispatchMouseEvent',commandParams:{type:'mousePressed',x:10,y:20},visualPoint:{x:110,y:120}});
  assert.match(adapter.views[0].webContents.isolatedCalls.at(-1).scripts[0].code,/"x":110,"y":120/);
  await assert.rejects(a.call('executeCdp',{target:{tabId:tab.id,sessionId:'child'},method:'Input.dispatchMouseEvent',commandParams:{type:'mousePressed',x:10,y:20},visualPoint:{x:-1,y:120}}),/Invalid visual point/);
  await assert.rejects(call({tabId:other.id,sessionId:'child'},'Runtime.evaluate'), /Invalid CDP frame session/);
  await assert.rejects(b.call('executeCdp',{target:{tabId:tab.id,sessionId:'child'},method:'Runtime.evaluate'}));
  debuggerApi.emit('message',{},'Target.detachedFromTarget',{sessionId:'child'},undefined);
  await assert.rejects(call({tabId:tab.id,sessionId:'child'},'Runtime.evaluate'), /Invalid CDP frame session/);
});

test('stalled chooser setup times out and does not issue late interception', async t => {
  const {runtime,adapter,a}=setup(t), tab=await a.tabs.create(), debuggerApi=adapter.views[0].webContents.debugger;
  let release;const commands=[];
  debuggerApi.sendCommand=async method=>{
    commands.push(method);
    if(method==='Page.enable')await new Promise(resolve=>{release=resolve;});
    return {};
  };
  await assert.rejects(runtime.dispatch('a','waitForFileChooser',{tabId:tab.id,timeoutMs:25,waitId:'00000000-0000-0000-0000-000000000000'},['page.control','files.upload']),/Timed out/);
  assert.equal(debuggerApi.isAttached(),false);
  await a.call('executeCdp',{target:{tabId:tab.id},method:'Runtime.evaluate'});
  release();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(commands,['Page.enable','Runtime.evaluate']);
});

test('socket distinguishes input already issued from preparation timeout', {skip:!['darwin','linux'].includes(process.platform)}, async t => {
  const {runtime,adapter,a}=setup(t),tab=await a.tabs.create(),debug=adapter.views[0].webContents.debugger;
  let release;const commands=[];
  debug.sendCommand=async method=>{commands.push(method);if(method==='Input.dispatchMouseEvent')await new Promise(resolve=>{release=resolve;});return {};};
  await runtime.connections.openSocket();
  const grant=runtime.connections.grant('a','socket',{ttlMs:10000,operations:['page.control']},process.pid);
  const client=await connectSocketIab(grant);t.after(()=>client.close());
  await assert.rejects(client.request('executeCdp',{target:{tabId:tab.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mousePressed',x:1,y:1}}),error=>error.message==='IAB_INPUT_OUTCOME_UNKNOWN');
  release();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(commands,['Page.captureScreenshot','Input.dispatchMouseEvent']);
});
