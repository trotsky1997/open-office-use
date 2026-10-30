import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { IabRuntime } from '../dist/runtime.js';
import { fakeElectron } from './fake-electron.mjs';
import { once } from 'node:events';

function setup(t) {
  const adapter = fakeElectron(), runtime = new IabRuntime(adapter, 'test');
  runtime.profiles.open({ id: 'work' });
  const a = runtime.scopes.open({ id: 'a', profileId: 'work' });
  const b = runtime.scopes.open({ id: 'b', profileId: 'work' });
  t.after(() => runtime.dispose()); return { runtime, adapter, a, b };
}
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
