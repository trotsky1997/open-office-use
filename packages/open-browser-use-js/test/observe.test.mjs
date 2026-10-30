import { runInNewContext } from 'node:vm';
import assert from "node:assert/strict";
import test from "node:test";
import { OpenBrowserUseBrowser, OpenBrowserUseClient, OpenBrowserUseFileChooser } from "../dist/index.js";

test("browser discovers and claims a user tab before returning its handle", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  client.request = async (method, params) => {
    if (method === "getUserTabs") return [{ id: 12, title: "Example" }];
    if (method === "claimUserTab") return { id: params.tabId };
    throw new Error("Unexpected method");
  };
  const browser = new OpenBrowserUseBrowser({ client });
  assert.equal((await browser.getUserTabs())[0].id, 12);
  assert.equal((await browser.claimTab(12)).id, 12);
  await assert.rejects(browser.claimTab(-1), /valid tab ID/);
});

test("observation indexes resolve to current, uncovered controls and expire after use", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  let documentId = 1, name = "Save", point = { x: 10, y: 20, width: 10, height: 10 };
  const events = [];
  client.request = async (method, params) => {
    if (method === "attach") return {};
    const command = params.method;
    if (command === "DOM.getDocument") return { root: { backendNodeId: documentId } };
    if (command === "Accessibility.getFullAXTree") return { nodes: [
      { role: { value: "heading" }, name: { value: "Account" } },
      { backendDOMNodeId: 7, role: { value: "button" }, name: { value: name } }
    ] };
    if (command === "DOM.resolveNode") return { object: { objectId: "node" } };
    if (command === "Runtime.callFunctionOn") return { result: { value: point } };
    if (command === "Input.dispatchMouseEvent") events.push(params.commandParams.type);
    return {};
  };
  const tab = new OpenBrowserUseBrowser({ client }).tab(10);
  const state = await tab.observe();
  assert.deepEqual(state.nodes, [{ index: 1, role: "button", name: "Save" }]);
  assert.equal(state.text, 'heading "Account"\n[1] button "Save"');
  assert.equal(state.truncated, false);
  await tab.click(1, state.snapshotId);
  assert.deepEqual(events, ["mousePressed", "mouseReleased"]);
  await assert.rejects(tab.click(1, state.snapshotId), /stale/);
  const renamed = await tab.observe();
  name = "Delete";
  await assert.rejects(tab.click(1, renamed.snapshotId), /changed/);
  const navigated = await tab.observe();
  documentId = 2;
  await assert.rejects(tab.click(1, navigated.snapshotId), /changed/);
  const covered = await tab.observe();
  point = null;
  await assert.rejects(tab.click(1, covered.snapshotId), /covered/);
  assert.equal(events.length, 2);
});

test("hover sends one mouse move after target validation", async () => {
  const client = new OpenBrowserUseClient({socketPath:"unused"}), events=[];
  let point = {x:10,y:20,width:10,height:10}, fail = false;
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "Page.getFrameTree") return {frameTree:{frame:{id:"root",loaderId:"v1",url:"https://example.test"}}};
    if (params.method === "DOM.getDocument") return {root:{backendNodeId:1}};
    if (params.method === "Accessibility.getFullAXTree") return {nodes:[{backendDOMNodeId:7,role:{value:"button"},name:{value:"Menu"}}]};
    if (params.method === "DOM.resolveNode") return {object:{objectId:"node"}};
    if (params.method === "Runtime.callFunctionOn") return {result:{value:point}};
    if (params.method === "Input.dispatchMouseEvent") { events.push(params.commandParams); if (fail) throw new Error("input outcome unknown"); }
    return {};
  };
  const tab = new OpenBrowserUseBrowser({client}).tab(1);
  await tab.playwright.getByRole("button",{name:"Menu"}).hover();
  assert.deepEqual(events.map(event=>event.type),["mouseMoved"]);
  point = null;
  await assert.rejects(tab.playwright.getByRole("button",{name:"Menu"}).hover({timeoutMs:0}),/covered/);
  assert.equal(events.length,1);
  point = {x:10,y:20,width:10,height:10}; fail = true;
  await assert.rejects(tab.playwright.getByRole("button",{name:"Menu"}).hover({timeoutMs:1000}),/input outcome unknown/);
  assert.equal(events.length,2);
});

test('locator innerText requires a unique current target and enforces its size limit',async()=>{
  const client=new OpenBrowserUseClient({socketPath:'unused'});let text='Visible text',count=1,released=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'one',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:Array.from({length:count},(_,i)=>({backendDOMNodeId:7+i,role:{value:'button'},name:{value:'Save'}}))};
    if(params.method==='DOM.resolveNode')return {object:{objectId:'node'}};
    if(params.method==='Runtime.callFunctionOn')return {result:{value:{value:['enabled','visible'].includes(params.commandParams.arguments[0].value) ? true : params.commandParams.arguments[0].value === 'attribute' ? params.commandParams.arguments[1].value === 'href' ? '/target' : null : text}}};
    if(params.method==='Runtime.releaseObject'){released++;return {};}
    return {};
  };
  const locator=new OpenBrowserUseBrowser({client}).tab(1).playwright.getByRole('button',{name:'Save',exact:true});
  assert.equal(await locator.innerText(),'Visible text');
  assert.equal(await locator.isEnabled(),true);
  assert.equal(await locator.isVisible(),true);
  assert.equal(await locator.textContent(),'Visible text');
  assert.equal(await locator.getAttribute('href'),'/target');assert.equal(await locator.getAttribute('missing'),null);
  await assert.rejects(locator.getAttribute(''),/Invalid attribute name/);
  text='x'.repeat(30001);await assert.rejects(locator.innerText({timeoutMs:0}),/30000 character limit/);
  assert.equal(released,7);count=2;await assert.rejects(locator.innerText({timeoutMs:0}),/matched 2/);await assert.rejects(locator.isVisible(),/matched 2/);
  count=0;assert.equal(await locator.isVisible(),false);
  await assert.rejects(locator.setChecked('yes'),/boolean/);
});

test('history navigation stays within the tab and does not repeat a failed action', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), calls=[], handlers=new Set();
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  let currentIndex=1, failure=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    calls.push(params);
    if(params.method==='Page.getNavigationHistory')return {currentIndex,entries:[{id:10},{id:20},{id:30}]};
    if(params.method==='Page.reload')for(const handler of handlers)handler({method:'onCDPEvent',params:{source:{tabId:1},method:'Page.loadEventFired',params:{}}});
    if(params.method==='Page.navigateToHistoryEntry' && failure)throw new Error('navigation outcome unknown');
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await tab.back();assert.deepEqual(calls.at(-1).commandParams,{entryId:10});
  await tab.forward();assert.deepEqual(calls.at(-1).commandParams,{entryId:30});
  currentIndex=0;const before=calls.length;await tab.back();assert.equal(calls.length,before+1);
  await tab.reload();assert.equal(calls.at(-1).method,'Page.reload');
  failure=true;await assert.rejects(tab.forward(),/outcome unknown/);
  assert.equal(calls.filter(call=>call.method==='Page.navigateToHistoryEntry').length,3);
  currentIndex=3;await assert.rejects(tab.back(),/history is unavailable/);
});

test('goto does not treat a loaded previous document as a completed navigation', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let sameDocument=false, detached=false;const handlers=new Set();
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='Page.navigate'){
      if(detached)for(const handler of handlers)handler({method:'onDebuggerDetach',params:{tabId:1}});
      return sameDocument ? {frameId:'main'} : {frameId:'main',loaderId:'next'};
    }
    if(params.method==='Runtime.evaluate')return {result:{value:{href:'https://example.test/old#section',readyState:'complete'}}};
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await assert.rejects(tab.goto('https://example.test/new',{timeoutMs:15}),/Timed out waiting for load/);
  sameDocument=true;
  await tab.goto('https://example.test/old#section',{timeoutMs:1000});
  detached=true;await assert.rejects(tab.goto('https://example.test/old#section',{timeoutMs:1000}),/debugger detached/);
});

test('navigation waits clean up on failure and observe load events during state reads', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), handlers=new Set();
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  let mode='event';
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='Page.navigate'){
      if(mode==='throw')throw new Error('scope revoked');
      return {errorText:'net::ERR_FAILED'};
    }
    if(params.method==='Runtime.evaluate'){
      if(mode==='event')for(const handler of handlers)handler({method:'onCDPEvent',params:{source:{tabId:1},method:'Page.loadEventFired',params:{}}});
      return {result:{value:{href:'https://example.test',readyState:mode==='ready'?'complete':'loading'}}};
    }
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await tab.waitForLoadState({timeoutMs:1000});assert.equal(handlers.size,1);
  mode='ready';await tab.waitForLoadState({timeoutMs:1000});assert.equal(handlers.size,1);
  let settled=false;
  const wait=tab.browser.cdp.waitForLoadEvent(1,'load',1000).then(()=>{settled=true;});
  for(const handler of handlers)handler({method:'onCDPEvent',params:{source:{tabId:1,sessionId:'child'},method:'Page.loadEventFired',params:{}}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
  for(const handler of handlers)handler({method:'onCDPEvent',params:{source:{tabId:1},method:'Page.loadEventFired',params:{}}});
  await wait;assert.equal(handlers.size,1);

  mode='failed';await assert.rejects(tab.goto('https://example.test'),/net::ERR_FAILED/);assert.equal(handlers.size,1);
  mode='throw';await assert.rejects(tab.goto('https://example.test'),/scope revoked/);assert.equal(handlers.size,1);
});

test('URL wait checks the matching document state and propagates transport errors', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let step=0, calls=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    calls++;
    if(step++===0)throw new Error('Execution context was destroyed');
    return {result:{value:{href:'https://example.test/done',readyState:step===2?'loading':'complete'}}};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1), pattern=/\/done$/g;
  await tab.playwright.waitForURL(pattern,{timeoutMs:1000});
  assert.equal(calls,3);assert.equal(pattern.lastIndex,0);
  await tab.waitForURL(runInNewContext('/done$/'),{timeoutMs:0});
  await assert.rejects(tab.waitForURL('https://example.test/missing',{timeoutMs:0}),/Timed out/);
  await assert.rejects(tab.waitForURL(/done/,{timeoutMs:-1}),/Invalid URL timeout/);
  client.request=async()=>{throw new Error('scope revoked');};
  await assert.rejects(tab.waitForURL(/done/),/scope revoked/);
});

test('screenshot clips use viewport coordinates and reject invalid regions', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), calls=[];
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    calls.push(params);
    if(params.method==='Page.getLayoutMetrics')return {cssVisualViewport:{pageX:10,pageY:500,clientWidth:800,clientHeight:600}};
    return {data:Buffer.from('png').toString('base64')};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  const options={clip:{x:20,y:30,width:40,height:50}};
  const screenshot=tab.getScreenshot(options);options.clip.x=-1;
  assert.equal((await screenshot).toString(),'png');
  assert.deepEqual(calls.at(-1).commandParams,{format:'png',clip:{x:30,y:530,width:40,height:50,scale:1},captureBeyondViewport:false});
  await assert.rejects(tab.getScreenshot({clip:{x:0,y:0,width:NaN,height:1}}),/Invalid screenshot clip/);
  await assert.rejects(tab.getScreenshot({clip:{x:799,y:0,width:2,height:1}}),/outside the viewport/);
  assert.equal(calls.filter(call=>call.method==='Page.captureScreenshot').length,1);
});

test('full-page screenshots use content dimensions and enforce size limits', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}),calls=[];let height=3000;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    calls.push(params);
    if(params.method==='Page.getLayoutMetrics')return {cssContentSize:{x:0,y:0,width:800,height}};
    return {data:Buffer.from('png').toString('base64')};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),options={fullPage:true};
  const screenshot=tab.getScreenshot(options);options.fullPage=false;
  assert.equal((await screenshot).toString(),'png');
  assert.deepEqual(calls.at(-1).commandParams,{format:'png',clip:{x:0,y:0,width:800,height:3000,scale:1},captureBeyondViewport:true});
  height=40001;await assert.rejects(tab.getScreenshot({fullPage:true}),/too large/);
  await assert.rejects(tab.getScreenshot({fullPage:true,clip:{x:0,y:0,width:1,height:1}}),/cannot use a clip/);
  assert.equal(calls.filter(call=>call.method==='Page.captureScreenshot').length,1);
});

test('prepared download waits for registration and retains the eventual result',async()=>{
  const client=new OpenBrowserUseClient({socketPath:'unused',timeoutMs:100}),handlers=new Set();let complete, waitId, requestTimeout;
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=(method,params,_generation,timeout)=>{
    if(method==='waitForDownload'){waitId=params.waitId;requestTimeout=timeout;return new Promise(resolve=>{complete=resolve;});}
    if(method==='downloadPath')return Promise.resolve({path:'/tmp/fixture'});
    throw new Error('Unexpected request');
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  let prepared=false;const preparing=tab.prepareDownload({timeoutMs:20000}).then(value=>{prepared=true;return value;});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(prepared,false);assert.equal(requestTimeout,22000);
  for(const handler of handlers)handler({method:'onDownloadWaitReady',params:{waitId:'wrong'}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(prepared,false);
  for(const handler of handlers)handler({method:'onDownloadWaitReady',params:{waitId}});
  const wait=await preparing;assert.equal(handlers.size,1);
  complete({downloadId:'123',url:'https://example.test/file'});const download=await wait.wait();assert.equal(download.id,'123');assert.equal(download.url,'https://example.test/file');assert.equal(await download.path(),'/tmp/fixture');
  client.request=()=>{throw new Error('connection unavailable');};
  await assert.rejects(tab.prepareDownload(),/connection unavailable/);assert.equal(handlers.size,1);
});

test('prepared file chooser validates paths and permits one file decision',async()=>{
  const client=new OpenBrowserUseClient({socketPath:'unused'}),handlers=new Set();let complete,waitId,chosen;
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=(method,params)=>{
    if(method==='attach' || method==='executeCdp')return Promise.resolve({});
    if(method==='waitForFileChooser'){waitId=params.waitId;return new Promise(resolve=>{complete=resolve;});}
    if(method==='setFileChooserFiles'){chosen=params;return Promise.resolve({});}
    throw new Error('Unexpected request');
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  const preparing=tab.prepareFileChooser();await new Promise(resolve=>setImmediate(resolve));
  for(const handler of handlers)handler({method:'onFileChooserWaitReady',params:{waitId}});
  const prepared=await preparing;complete({fileChooserId:'chooser',isMultiple:false});
  const chooser=await prepared.wait();assert.equal(await prepared.wait(),chooser);assert.equal(chooser.isMultiple(),false);
  await assert.rejects(chooser.setFiles('relative.txt'),/absolute/);
  await assert.rejects(chooser.setFiles(['/tmp/a','/tmp/b']),/multiple/);
  await chooser.setFiles('/tmp/a');assert.deepEqual(chosen,{fileChooserId:'chooser',files:['/tmp/a']});
  await assert.rejects(chooser.setFiles('/tmp/a'),/already been issued/);
  client.setFileChooserFiles=async()=>{throw new Error('outcome unknown');};
  const uncertain=new OpenBrowserUseFileChooser(client,'other',true);
  await assert.rejects(uncertain.setFiles('/tmp/a'),/outcome unknown/);
  await assert.rejects(uncertain.setFiles('/tmp/a'),/already been issued/);
});

test('dialog waits fail promptly on tab detach or client close, without crossing tabs', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), handlers=new Set();
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=async()=>({});
  const browser=new OpenBrowserUseBrowser({client}), tab=browser.tab(1);
  await tab.watchDialogs();
  const detached=tab.waitForDialog({timeoutMs:5000});
  await new Promise(resolve=>setImmediate(resolve));
  for(const handler of handlers)handler({method:'onDebuggerDetach',params:{tabId:2}});
  for(const handler of handlers)handler({method:'onDebuggerDetach',params:{tabId:1}});
  await assert.rejects(detached,/Tab 1 debugger detached/);
  const closed=tab.waitForDialog({timeoutMs:5000});
  await new Promise(resolve=>setImmediate(resolve));
  client.close();
  await assert.rejects(closed,/socket closed/);
  assert.equal(handlers.size,1);
});

test('JavaScript dialogs are observed, scoped and decided only once', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), handlers=new Set(), calls=[];
  let release;
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    calls.push(params);
    if(params.method==='Page.handleJavaScriptDialog')await new Promise(resolve=>{release=resolve;});
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await tab.watchDialogs();
  const waiting=tab.waitForDialog({timeoutMs:1000});
  const emit=(method,params,source={tabId:1,sessionId:'frame'})=>{for(const handler of handlers)handler({method:'onCDPEvent',params:{source,method,params}});};
  emit('Page.javascriptDialogOpening',{type:'prompt',message:'Name?',url:'https://example.test',defaultPrompt:'Guest'});
  const dialog=await waiting;
  assert.deepEqual({...dialog.info,id:'id'},{id:'id',type:'prompt',message:'Name?',url:'https://example.test',defaultPrompt:'Guest'});
  const pending=dialog.accept('Ada');
  await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(dialog.dismiss(),/already been issued/);
  assert.deepEqual(calls.at(-1).commandParams,{accept:true,promptText:'Ada'});
  assert.equal(calls.at(-1).target.sessionId,'frame');
  release();await pending;
  assert.equal(tab.currentDialog(),null);
  await assert.rejects(dialog.dismiss(),/no longer open/);
  emit('Page.javascriptDialogOpening',{type:'confirm',message:'Continue?',url:'https://example.test'},{tabId:1});
  await assert.rejects(tab.currentDialog().accept('text'),/prompt dialog/);
  emit('Page.javascriptDialogClosed',{}, {tabId:1});
  assert.equal(tab.currentDialog(),null);
  emit('Page.javascriptDialogOpening',{type:'alert',message:'Closed',url:'https://example.test'},{tabId:1});
  for(const handler of handlers)handler({method:'onTabClosed',params:{tabId:1}});
  assert.equal(tab.currentDialog(),null);
  await assert.rejects(tab.waitForDialog({timeoutMs:0}),/Timed out/);
});

test('dialog decisions cannot cross a reconnect during attachment', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), handlers=new Set(), calls=[];
  let generation=0, reconnect=false;
  Object.defineProperty(client,'connectionGeneration',{get:()=>generation});
  client.onNotification=handler=>{handlers.add(handler);return ()=>handlers.delete(handler);};
  client.request=async(method,params)=>{
    if(method==='attach'){if(reconnect)generation++;return {};}
    calls.push(params);return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await tab.watchDialogs();
  for(const handler of handlers)handler({method:'onCDPEvent',params:{source:{tabId:1},method:'Page.javascriptDialogOpening',params:{type:'confirm',message:'Continue?',url:'https://example.test'}}});
  const dialog=tab.currentDialog();reconnect=true;
  await assert.rejects(dialog.dismiss(),/Connection changed/);
  assert.equal(calls.some(call=>call.method==='Page.handleJavaScriptDialog'),false);
  assert.equal(tab.currentDialog(),null);
});

test("large page text is bounded and reports truncation", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "DOM.getDocument") return { root: { backendNodeId: 1 } };
    if (params.method === "Accessibility.getFullAXTree") return { nodes: [
      { role: { value: "StaticText" }, name: { value: "x".repeat(31_000) } }
    ] };
    throw new Error("Unexpected method");
  };
  const state = await new OpenBrowserUseBrowser({ client }).tab(1).observe();
  assert.equal(state.truncated, true);
  assert.ok(state.text.length <= 30_000);
});

test("observation diffs preserve ordering and reset on navigation", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  let documentId = 1;
  let labels = ["A", "B", "A"];
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "DOM.getDocument") return { root: { backendNodeId: documentId } };
    if (params.method === "Accessibility.getFullAXTree") return { nodes: labels.map(value => ({role:{value:"StaticText"},name:{value}})) };
    throw new Error("Unexpected method");
  };
  const tab = new OpenBrowserUseBrowser({ client }).tab(1);
  const first = await tab.observe({diff:true});
  assert.equal(first.textMode, "full");
  labels = ["B", "A", "A"];
  const changed = await tab.observe({diff:true});
  assert.equal(changed.textMode, "diff");
  assert.equal(changed.text, '- StaticText "A"\n- StaticText "B"\n+ StaticText "B"\n+ StaticText "A"');
  assert.notEqual(changed.snapshotId, first.snapshotId);
  assert.equal((await tab.observe({diff:true})).text, "");
  documentId = 2;
  const navigated = await tab.observe({diff:true});
  assert.equal(navigated.textMode, "full");
  assert.equal(navigated.text, 'StaticText "B"\nStaticText "A"\nStaticText "A"');
  labels = ["x".repeat(20_000)];
  await tab.observe();
  labels = ["y".repeat(20_000)];
  const largeDiff = await tab.observe({diff:true});
  assert.equal(largeDiff.truncated, true);
  assert.equal((await tab.observe({diff:true})).textMode, "full");
});

test("observation includes control states without exposing arbitrary values", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  let checked = "false";
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "DOM.getDocument") return { root: { backendNodeId: 1 } };
    if (params.method === "Accessibility.getFullAXTree") return { nodes: [{
      backendDOMNodeId: 5, role: {value:"checkbox"}, name: {value:"Alerts"},
      properties: [{name:"checked",value:{value:checked}}, {name:"expanded",value:{value:false}}, {name:"secret",value:{value:"hidden"}}]
    }] };
    throw new Error("Unexpected method");
  };
  const tab = new OpenBrowserUseBrowser({client}).tab(1);
  const first = await tab.observe();
  assert.equal(first.text, '[1] checkbox "Alerts" checked="false" expanded=false');
  checked = "true";
  await assert.rejects(tab.click(1, first.snapshotId), /Target changed/);
  const changed = await tab.observe({diff:true});
  assert.match(changed.text, /\+ .*checked="true"/);
  assert.doesNotMatch(changed.text, /hidden/);
});

test("same-process frame targets translate coordinates and reject frame navigation", async () => {
  const client = new OpenBrowserUseClient({socketPath:"unused"});
  let loader = "v1", covered = false;
  const events = [];
  client.request = async (method, params) => {
    if (method === "attach") return {};
    const command = params.method, args = params.commandParams;
    if (command === "DOM.getDocument") return {root:{backendNodeId:1}};
    if (command === "Target.setAutoAttach") throw new Error("IAB CDP command is outside page permissions");
    if (command === "Page.getFrameTree") return {frameTree:{frame:{id:"root",loaderId:"root-v1",url:"https://example.test"},childFrames:[{frame:{id:"child",loaderId:loader,url:"https://example.test/frame"}}]}};
    if (command === "Accessibility.getFullAXTree") return {nodes:args.frameId ? [{backendDOMNodeId:7,role:{value:"button"},name:{value:"Child"}}] : []};
    if (command === "DOM.getFrameOwner") return {backendNodeId:8};
    if (command === "DOM.resolveNode") return {object:{objectId:args.backendNodeId === 8 ? "frame" : "target"}};
    if (command === "Runtime.callFunctionOn") return {result:{value:args.objectId === "frame" ? (covered ? null : {x:110,y:120}) : {x:10,y:20,width:10,height:10}}};
    if (command === "Input.dispatchMouseEvent") events.push(args);
    return {};
  };
  const tab = new OpenBrowserUseBrowser({client}).tab(1);
  const state = await tab.observe({includeFrames:true});
  assert.deepEqual(state.nodes, [{index:1,role:"button",name:"Child",frameId:"child"}]);
  assert.deepEqual(state.unavailableFrames, []);
  assert.equal(state.frameCoverage, "same-process");
  await tab.click(1,state.snapshotId);
  assert.deepEqual(events.map(event=>[event.type,event.x,event.y]), [["mousePressed",110,120],["mouseReleased",110,120]]);
  const stale = await tab.observe({includeFrames:true});
  loader = "v2";
  await assert.rejects(tab.click(1,stale.snapshotId), /Frame changed/);
  const hidden = await tab.observe({includeFrames:true});
  covered = true;
  await assert.rejects(tab.click(1,hidden.snapshotId), /Frame is hidden/);
  assert.equal(events.length, 2);
});

test("coordinate input is bounded to the CSS viewport and invalidates observations", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  const events = [];
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "Page.getLayoutMetrics") return { cssVisualViewport: { clientWidth: 100, clientHeight: 80 } };
    if (params.method === "DOM.getDocument") return { root: { backendNodeId: 1 } };
    if (params.method === "Accessibility.getFullAXTree") return { nodes: [{ backendDOMNodeId: 7, role: { value: "button" }, name: { value: "Go" } }] };
    if (params.method === "Input.dispatchMouseEvent" || params.method === "Input.synthesizeScrollGesture") events.push({ method: params.method, ...params.commandParams });
    return {};
  };
  const tab = new OpenBrowserUseBrowser({ client }).tab(1);
  const state = await tab.observe();
  await tab.clickAt(20, 30);
  await assert.rejects(tab.click(1, state.snapshotId), /stale/);
  await tab.hoverAt(10, 20);
  await tab.scrollAt(20, 30, 0, 200);
  assert.deepEqual(events.map(event => event.type ?? event.method), ["mouseMoved", "mousePressed", "mouseReleased", "mouseMoved", "mouseMoved", "Input.synthesizeScrollGesture"]);
  assert.equal(events[5].yDistance, -200);
  await assert.rejects(tab.clickAt(100, 0), /outside/);
  await assert.rejects(tab.hoverAt(0, 80), /outside/);
  await assert.rejects(tab.scrollAt(0, 0, 0, Infinity), /finite/);
  assert.equal(events.length, 6);
});

test("drag sends a pointer path and releases the button after failure", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  const events = [];
  let failMove = false;
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "Page.getLayoutMetrics") return { cssVisualViewport: { clientWidth: 100, clientHeight: 80 } };
    if (params.method === "Input.dispatchMouseEvent") {
      events.push(params.commandParams);
      if (failMove && params.commandParams.type === "mouseMoved" && params.commandParams.buttons === 1) throw new Error("move failed");
    }
    return {};
  };
  const tab = new OpenBrowserUseBrowser({client}).tab(1);
  await tab.drag([10, 10], [50, 30]);
  assert.equal(events.filter(event => event.type === "mouseMoved" && event.buttons === 1).length, 5);
  assert.deepEqual([events.at(-1).type, events.at(-1).x, events.at(-1).y], ["mouseReleased", 50, 30]);
  failMove = true;
  await assert.rejects(tab.drag([10,10], [50,30]), /move failed/);
  assert.equal(events.at(-1).type, "mouseReleased");
  const count = events.length;
  await assert.rejects(tab.drag([10,10], [100,30]), /outside/);
  assert.equal(events.length, count);
});

test("keyboard input validates keys and sends paired events with modifiers", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  const events = [];
  let failDown = false;
  client.request = async (method, params) => {
    if (method === "attach") return {};
    if (params.method === "Input.dispatchKeyEvent") { events.push(params.commandParams); if (failDown && params.commandParams.type === "rawKeyDown" && params.commandParams.key === "a") throw new Error("unknown outcome"); }
    return {};
  };
  const tab = new OpenBrowserUseBrowser({ client }).tab(1);
  await tab.pressKey("Control+A");
  assert.deepEqual(events.map(event => event.type), ["rawKeyDown", "rawKeyDown", "keyUp", "keyUp"]);
  assert.equal(events[1].modifiers, 2);
  assert.equal(events[1].windowsVirtualKeyCode, 65);
  await tab.pressKey("Space");
  assert.equal(events[4].key," ");
  assert.equal(events[4].code,"Space");
  assert.equal(events[4].text," ");
  await tab.pressKey("Shift+B");
  assert.equal(events[7].key,"B");
  assert.equal(events[7].text,"B");
  assert.equal(events[7].unmodifiedText,"b");
  await assert.rejects(tab.pressKey("Unknown+Enter"), /modifiers/);
  await assert.rejects(tab.pressKey("toString+Enter"), /modifiers/);
  await assert.rejects(tab.pressKey("F42"), /Unsupported/);
  assert.equal(events.length, 10);
  failDown = true;
  await assert.rejects(tab.pressKey("Control+A"),/unknown outcome/);
  assert.deepEqual(events.slice(-4).map(event=>event.type),["rawKeyDown","rawKeyDown","keyUp","keyUp"]);
});

test("number and symbol keys use their physical code and shifted text", async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), events=[];
  client.request=async(method,params)=>{if(method==='attach')return {}; if(params.method==='Input.dispatchKeyEvent')events.push(params.commandParams);return {};};
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await tab.pressKey('1'); await tab.pressKey('Shift+1'); await tab.pressKey('@'); await tab.pressKey('.'); await tab.pressKey('+');
  const keys=events.filter(event=>event.type==='keyDown');
  assert.deepEqual(keys.map(event=>[event.key,event.code,event.text,event.unmodifiedText]),[['1','Digit1','1','1'],['!','Digit1','!','1'],['@','Digit2','@','2'],['.','Period','.','.'],['+','Equal','+','=']]);
  await tab.pressKey('Control+1');
  assert.equal(events.at(-2).type,'keyUp');
  assert.ok(events.some(event=>event.type==='rawKeyDown' && event.key==='1' && event.modifiers===2 && event.text===undefined));
});

test("text input requires an editable focused observed textbox", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  let focused = true, selected = true;
  const calls = [];
  client.request = async (method, params) => {
    if (method === "attach") return {};
    calls.push(params.method);
    if (params.method === "DOM.getDocument") return { root: { backendNodeId: 1 } };
    if (params.method === "Accessibility.getFullAXTree") return { nodes: [{ backendDOMNodeId: 7, role: { value: "textbox" }, name: { value: "Message" } }] };
    if (params.method === "DOM.resolveNode") return { object: { objectId: "node" } };
    if (params.method === "Runtime.callFunctionOn") {
      const fn=params.commandParams.functionDeclaration;
      return {result:{value:fn.includes("activeElement") ? focused : fn.includes("selectionStart") ? selected : fn.includes("function(value)") ? true : {x:1,y:2,width:10,height:10}}};
    }
    return {};
  };
  const tab = new OpenBrowserUseBrowser({ client }).tab(1);
  const first = await tab.observe();
  await tab.typeText(1, first.snapshotId, "hello");
  assert.equal(calls.filter((name) => name === "Input.insertText").length, 1);
  const replacement = await tab.observe();await tab.fill(1,replacement.snapshotId,"new");
  assert.equal(calls.filter((name) => name === "Input.insertText").length, 2);
  const blockedSelection = await tab.observe();selected = false;
  await assert.rejects(tab.fill(1,blockedSelection.snapshotId,"blocked"),/select the text/);
  assert.equal(calls.filter((name) => name === "Input.insertText").length, 2);
  const second = await tab.observe();
  focused = false;
  await assert.rejects(tab.typeText(1, second.snapshotId, "wrong target"), /focus/);
  assert.equal(calls.filter((name) => name === "Input.insertText").length, 2);
});

test("cross-process frame input uses its session and rejects detached targets", async () => {
  const client = new OpenBrowserUseClient({ socketPath: "unused" });
  let notify, detached = false, focused = true;
  const input = [], keys = [];
  client.onNotification = handler => { notify = handler; return () => {}; };
  client.request = async (method, params) => {
    if (method === "attach") return {};
    const command = params.method, args = params.commandParams, session = params.target.sessionId;
    if (command === "Target.setAutoAttach") {
      if (!session && args.autoAttach && !detached) notify({method:"onCDPEvent",params:{source:{tabId:1},method:"Target.attachedToTarget",params:{sessionId:"child-session",targetInfo:{type:"iframe",targetId:"cross",parentFrameId:"root"}}}});
      return {};
    }
    if (command === "DOM.getDocument") return {root:{backendNodeId:1}};
    if (command === "Page.getFrameTree") return session ? {frameTree:{frame:{id:"cross",loaderId:"cross-v1",url:"https://cross.test"},childFrames:[{frame:{id:"nested",loaderId:"nested-v1",url:"https://cross.test/nested"}}]}} : {frameTree:{frame:{id:"root",loaderId:"root-v1",url:"https://root.test"}}};
    if (command === "Accessibility.getFullAXTree") return {nodes:args.frameId === "nested" ? [{backendDOMNodeId:7,role:{value:"button"},name:{value:"Nested"}}] : []};
    if (command === "DOM.getFrameOwner") return {backendNodeId:args.frameId === "nested" ? 8 : 9};
    if (command === "DOM.resolveNode") return {object:{objectId:String(args.backendNodeId)}};
    if (command === "Runtime.callFunctionOn" && args.functionDeclaration.includes("activeElement")) return {result:{value:focused}};
    if (command === "Runtime.callFunctionOn") return {result:{value:args.objectId === "7" ? {x:10,y:20,width:10,height:10} : args.objectId === "8" ? {x:110,y:120} : {x:210,y:220}}};
    if (command === "Input.dispatchKeyEvent" || command === "DOM.focus") keys.push({session,command,...args});
    if (command === "Input.dispatchMouseEvent") input.push({session,visualPoint:params.visualPoint,...args});
    return {};
  };
  const tab = new OpenBrowserUseBrowser({client}).tab(1);
  const state = await tab.observe({includeFrames:true});
  assert.equal(state.frameCoverage,"cross-process");
  const target = state.nodes.find(node => node.name === "Nested");
  await tab.click(target.index,state.snapshotId);
  assert.deepEqual(input.map(({session,x,y})=>({session,x,y})),[{session:"child-session",x:110,y:120},{session:"child-session",x:110,y:120}]);
  assert.deepEqual(input.map(({visualPoint})=>visualPoint),[{x:210,y:220},{x:210,y:220}]);
  await tab.playwright.getByRole("button",{name:"Nested",exact:true}).press("Enter");
  assert.deepEqual(keys.map(({session,command})=>({session,command})),[{session:"child-session",command:"DOM.focus"},{session:"child-session",command:"Input.dispatchKeyEvent"},{session:"child-session",command:"Input.dispatchKeyEvent"}]);
  assert.equal(input.length,2);
  await assert.rejects(tab.playwright.getByRole("button",{name:"Nested",exact:true}).press("F42"),/Unsupported/);
  assert.equal(keys.length,3);
  focused = false;
  await assert.rejects(tab.playwright.getByRole("button",{name:"Nested",exact:true}).press("Enter"),/lost focus/);
  assert.equal(keys.length,4);
  assert.equal(keys.at(-1).command,"DOM.focus");
  const stale = await tab.observe({includeFrames:true});
  detached = true;
  notify({method:"onCDPEvent",params:{source:{tabId:1},method:"Target.detachedFromTarget",params:{sessionId:"child-session"}}});
  await assert.rejects(tab.click(stale.nodes.find(node=>node.name==="Nested").index,stale.snapshotId),/Frame changed/);
});

test("role locators reobserve, reject ambiguous matches and honor explicit position", async () => {
  const client = new OpenBrowserUseClient({socketPath:'unused'});
  const tab = new OpenBrowserUseBrowser({client}).tab(1), calls=[];
  let generation=0, unavailableFrames=[], nodes=[{index:1,role:'button',name:'Save draft'},{index:2,role:'button',name:'Save final'}];
  tab.observe=async options=>{assert.equal(options.includeFrames,true);return {snapshotId:String(++generation),nodes,unavailableFrames,text:'',textMode:'full',truncated:false};};
  tab.click=async(index,snapshotId)=>calls.push({index,snapshotId});
  const locator=tab.playwright.getByRole('button',{name:'save'});
  assert.equal(await locator.count(),2);
  await assert.rejects(locator.click(),/matched 2/);
  await locator.nth(1).click();assert.deepEqual(calls,[{index:2,snapshotId:'3'}]);
  assert.equal(await locator.nth(1).first().count(),1);
  assert.equal(await locator.nth(1).nth(1).count(),0);
  nodes=[{index:4,role:'button',name:'Save final'}];
  await locator.click();assert.deepEqual(calls.at(-1),{index:4,snapshotId:'6'});
  assert.equal(await tab.playwright.getByRole('button',{name:'save final',exact:true}).count(),0);
  nodes=[{index:10,role:'button',name:'Save first'},{index:11,role:'button',name:'Save last'}];
  const all=await locator.all();assert.equal(all.length,2);
  await locator.last().click();assert.equal(calls.at(-1).index,11);
  nodes.reverse();await all[0].click();assert.equal(calls.at(-1).index,11);
  assert.equal(await locator.nth(0).last().count(),1);
  nodes=[];assert.equal(await locator.last().count(),0);assert.deepEqual(await locator.all(),[]);
  unavailableFrames=['unknown'];await assert.rejects(locator.count(),/incomplete/);
  assert.throws(()=>locator.nth(-1),/non-negative/);
});

test("role locator waits for a missing target but never retries an issued action", async () => {
  const tab = new OpenBrowserUseBrowser({client:new OpenBrowserUseClient({socketPath:'unused'})}).tab(1);
  let nodes=[], observations=0, clicks=0;
  tab.observe=async()=>({snapshotId:String(++observations),nodes,unavailableFrames:[],text:'',textMode:'full',truncated:false});
  tab.click=async()=>{clicks++;};
  const locator=tab.playwright.getByRole('button',{name:'Later'});
  setTimeout(()=>{nodes=[{index:1,role:'button',name:'Later'}];},20);
  await locator.click({timeoutMs:500});assert.equal(clicks,1);assert.ok(observations>=2);
  nodes=[];await assert.rejects(locator.click({timeoutMs:0}),/matched 0/);assert.equal(clicks,1);
  nodes=[{index:1,role:'button',name:'Later'}];tab.click=async()=>{clicks++;throw Error('input result unknown');};
  await assert.rejects(locator.click({timeoutMs:500}),/input result unknown/);assert.equal(clicks,2);
  await assert.rejects(locator.click({timeoutMs:-1}),/Invalid locator timeout/);
});

test("locator retries a covered target before input, and stops at an unknown input result", async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let covered=true, mouse=0, failMouse=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:'button'},name:{value:'Submit'}}]};
    if(command==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(command==='Runtime.callFunctionOn')return {result:{value:covered?null:{x:10,y:10,width:10,height:10}}};
    if(command==='Input.dispatchMouseEvent'){mouse++;if(failMouse)throw Error('unknown input result');}
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),locator=tab.playwright.getByRole('button',{name:'Submit',exact:true});
  setTimeout(()=>{covered=false;},20);
  await locator.click({timeoutMs:500});assert.equal(mouse,2);
  failMouse=true;
  await assert.rejects(locator.click({timeoutMs:500}),/unknown input result/);assert.equal(mouse,3);
});

test("locator does not repeat a click when a frame changes after input", async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let loader='v1',mouse=0,inserted=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'root-v1',url:'https://root.test'},childFrames:[{frame:{id:'child',loaderId:loader,url:'https://root.test/child'}}]}};
    if(command==='Accessibility.getFullAXTree')return {nodes:args.frameId?[{backendDOMNodeId:7,role:{value:'textbox'},name:{value:'Message'}}]:[]};
    if(command==='DOM.getFrameOwner')return {backendNodeId:8};
    if(command==='DOM.resolveNode')return {object:{objectId:args.backendNodeId===8?'frame':'target'}};
    if(command==='Runtime.callFunctionOn')return {result:{value:args.functionDeclaration.includes('activeElement')?true:{x:10,y:10,width:10,height:10}}};
    if(command==='Input.dispatchMouseEvent'){mouse++;if(args.type==='mouseReleased')loader='v2';}
    if(command==='Input.insertText')inserted++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  await assert.rejects(tab.playwright.getByRole('textbox',{name:'Message'}).fill('text',{timeoutMs:500}),/Frame changed/);
  assert.equal(mouse,2);assert.equal(inserted,0);
});

test('role locators filter supported states and reject invalid options', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let checked=false, pressed='true', changeOnMeasure=false, mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[
      {backendDOMNodeId:10,role:{value:'checkbox'},name:{value:'Alerts'},properties:[{name:'checked',value:{value:checked}}]},
      {backendDOMNodeId:11,role:{value:'checkbox'},name:{value:'Alerts'},properties:[{name:'checked',value:{value:'mixed'}}]},
      {backendDOMNodeId:12,role:{value:'button'},name:{value:'Toggle'},properties:[{name:'pressed',value:{value:pressed}},{name:'expanded',value:{value:false}}]},
      {backendDOMNodeId:13,role:{value:'tab'},name:{value:'View'},properties:[{name:'selected',value:{value:true}}]},
      {backendDOMNodeId:14,role:{value:'button'},name:{value:'Plain'}}
    ]};
    if(params.method==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(params.method==='Runtime.callFunctionOn'){if(changeOnMeasure)pressed='false';return {result:{value:{x:10,y:10,width:10,height:10}}};}
    if(params.method==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1), role=tab.playwright;
  assert.equal(await role.getByRole('checkbox',{name:'Alerts',checked:false}).count(),1);
  assert.equal(await role.getByRole('checkbox',{name:'Alerts',checked:true}).count(),0);
  assert.equal(await role.getByRole('button',{name:'Toggle',pressed:true,expanded:false}).count(),1);
  assert.equal(await role.getByRole('tab',{name:'View',selected:true}).count(),1);
  assert.equal(await role.getByRole('button',{name:'Plain',pressed:false}).count(),0);
  assert.throws(()=>role.getByRole('button',{pressed:'true'}),/Invalid role locator/);
  assert.throws(()=>role.getByRole('button',{level:1}),/Invalid role locator/);
  const state=await tab.observe();
  assert.equal(state.nodes.find(node=>node.name==='Toggle').pressed,true);
  assert.equal(state.nodes.find(node=>node.name==='Toggle').expanded,false);
  assert.equal(state.nodes.find(node=>node.role==='tab').selected,true);
  const first=state.nodes.find(node=>node.role==='checkbox' && node.checked===false);
  checked=true;
  await assert.rejects(tab.click(first.index,state.snapshotId),/Target changed/);
  changeOnMeasure=true;
  await assert.rejects(role.getByRole('button',{name:'Toggle',pressed:true}).click({timeoutMs:0}),/Target changed/);
  assert.equal(mouse,0);
});

test('disabled controls remain observable and never receive input', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let disabled=true, input=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[
      {backendDOMNodeId:10,role:{value:'checkbox'},name:{value:'Notifications'},properties:[{name:'checked',value:{value:true}},...(disabled?[{name:'disabled',value:{value:'true'}}]:[])]},
      {backendDOMNodeId:11,role:{value:'checkbox'},name:{value:'Notifications'},properties:[{name:'checked',value:{value:false}}]}
    ]};
    if(params.method==='Input.dispatchMouseEvent' || params.method==='Input.dispatchKeyEvent')input++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1), role=tab.playwright;
  assert.equal(await role.getByRole('checkbox',{name:'Notifications'}).count(),2);
  assert.equal(await role.getByRole('checkbox',{name:'Notifications',disabled:true}).count(),1);
  assert.equal(await role.getByRole('checkbox',{name:'Notifications',disabled:false}).count(),1);
  await assert.rejects(role.getByRole('checkbox',{name:'Notifications',disabled:true}).check({timeoutMs:0}),/disabled/);
  const snapshot=await tab.observe();
  assert.equal(snapshot.nodes.find(node=>node.checked===true).disabled,true);
  assert.match(snapshot.text,/disabled/);
  disabled=false;
  await assert.rejects(tab.click(snapshot.nodes.find(node=>node.checked===true).index,snapshot.snapshotId),/changed/);
  assert.equal(input,0);
});

test('disabled controls may be hovered without being clicked', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), events=[];
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:10,role:{value:'button'},name:{value:'Locked'},properties:[{name:'disabled',value:{value:true}}]}]};
    if(params.method==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(params.method==='Runtime.callFunctionOn'){assert.equal(params.commandParams.arguments[0].value,true);return {result:{value:{x:10,y:10,width:10,height:10}}};}
    if(params.method==='Input.dispatchMouseEvent')events.push(params.commandParams.type);
    return {};
  };
  const locator=new OpenBrowserUseBrowser({client}).tab(1).playwright.getByRole('button',{name:'Locked',disabled:true});
  await locator.hover(); assert.deepEqual(events,['mouseMoved']);
  await assert.rejects(locator.click({timeoutMs:0}),/disabled/);
  assert.deepEqual(events,['mouseMoved']);
});

test('label locator checks and unchecks once, validates state and refuses mixed or radio clearing', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let checked='false',role='checkbox',mouse=0,domDisabled=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:role},name:{value:'Alerts'},properties:[{name:'checked',value:{value:checked}}]}]};
    if(command==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(command==='Runtime.callFunctionOn')return {result:{value:args.functionDeclaration.includes("return 'enabled'") ? (domDisabled?'disabled':'enabled') : {x:10,y:10,width:10,height:10}}};
    if(command==='Input.dispatchMouseEvent'){mouse++;if(args.type==='mouseReleased')checked=checked==='true'?'false':'true';}
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),target=tab.playwright.getByLabel('Alerts',{exact:true});
  let state=await tab.observe();assert.equal(state.nodes[0].checked,false);
  await target.check();assert.equal(checked,'true');assert.equal(mouse,2);
  await target.check();assert.equal(mouse,2);
  domDisabled=true;await assert.rejects(target.check({timeoutMs:0}),/disabled/);assert.equal(mouse,2);domDisabled=false;
  await target.uncheck();assert.equal(checked,'false');assert.equal(mouse,4);
  state=await tab.observe();checked='true';await assert.rejects(tab.setChecked(1,state.snapshotId,false),/changed/);assert.equal(mouse,4);
  checked='mixed';await assert.rejects(target.check(),/binary checked state/);assert.equal(mouse,4);
  checked='true';role='radio';await assert.rejects(target.uncheck(),/radio cannot be unchecked/);assert.equal(mouse,4);
});

test('select locator waits for options and never repeats an uncertain mutation', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let preflights=0,mutations=0,failMutation=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:'combobox'},name:{value:'Colour'}}]};
    if(command==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(command==='Runtime.callFunctionOn'){
      if(args.functionDeclaration.includes("status:'not-select'")){preflights++;return {result:{value:preflights===1?{status:'missing'}:{status:'ok',chosen:[{index:1,value:'blue',label:'Blue'}]}}};}
      if(args.functionDeclaration.includes('dispatchEvent')){mutations++;if(failMutation)throw Error('select result unknown');return {result:{value:['blue']}};}
      return {result:{value:{x:10,y:10,width:10,height:10}}};
    }
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),select=tab.playwright.getByLabel('Colour');
  assert.deepEqual(await select.selectOption({label:'Blue'},{timeoutMs:500}),['blue']);assert.equal(preflights,2);assert.equal(mutations,1);
  failMutation=true;await assert.rejects(select.selectOption('blue',{timeoutMs:500}),/select result unknown/);assert.equal(mutations,2);
  await assert.rejects(select.selectOption({value:42},{timeoutMs:0}),/Invalid select option/);
});

test('optional field values are bounded, redact passwords and reset diffs across modes', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let email='hello@example.test';
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[
      {backendDOMNodeId:2,role:{value:'textbox'},name:{value:'Email'},value:{value:email}},
      {backendDOMNodeId:3,role:{value:'textbox'},name:{value:'Password'},value:{value:'raw-secret-must-not-leak'}},
      {backendDOMNodeId:4,role:{value:'textbox'},name:{value:'Unknown'},value:{value:'unknown-private'}},
      {backendDOMNodeId:5,role:{value:'spinbutton'},name:{value:'Count'},value:{value:42}}
    ]};
    if(command==='DOM.resolveNode')return {object:{objectId:String(args.backendNodeId)}};
    if(command==='Runtime.callFunctionOn')return {result:{value:args.objectId==='3'?'redacted':args.objectId==='4'?'unknown':'visible'}};
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  const initial=await tab.observe();assert.doesNotMatch(JSON.stringify(initial),/hello@example|raw-secret|unknown-private/);
  const withValues=await tab.observe({includeValues:true,diff:true});assert.equal(withValues.textMode,'full');
  assert.equal(withValues.nodes[0].value,'hello@example.test');assert.equal(withValues.nodes[1].valueRedacted,true);
  assert.equal(withValues.nodes[2].valueUnavailable,true);assert.equal(withValues.nodes[3].value,42);
  assert.doesNotMatch(JSON.stringify(withValues),/raw-secret|unknown-private/);
  email='new@example.test';const changed=await tab.observe({includeValues:true,diff:true});assert.equal(changed.textMode,'diff');assert.match(changed.text,/new@example/);
  const without=await tab.observe({diff:true});assert.equal(without.textMode,'full');assert.doesNotMatch(JSON.stringify(without),/new@example/);
  email='x'.repeat(700);const large=await tab.observe({includeValues:true});assert.equal(large.valuesTruncated,true);assert.equal(large.nodes[0].value.length,512);assert.equal(large.nodes[0].valueTruncated,true);
  assert.equal((await tab.observe({includeValues:true,diff:true})).textMode,'full');
});

test('optional field values share one output budget', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:Array.from({length:20},(_,i)=>({backendDOMNodeId:i+2,role:{value:'textbox'},name:{value:`Field ${i}`},value:{value:'x'.repeat(512)}}))};
    if(params.method==='DOM.resolveNode')return {object:{objectId:String(params.commandParams.backendNodeId)}};
    if(params.method==='Runtime.callFunctionOn')return {result:{value:'visible'}};
    return {};
  };
  const state=await new OpenBrowserUseBrowser({client}).tab(1).observe({includeValues:true});
  assert.equal(state.valuesTruncated,true);
  assert.equal(state.nodes.reduce((sum,node)=>sum+(node.value?.length??0),0),8000);
  assert.ok(state.nodes.some(node=>node.valueTruncated));
});

test('text and heading locators observe semantic nodes and match normalized text', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[
      {backendDOMNodeId:2,role:{value:'heading'},name:{value:'Welcome'}},
      {backendDOMNodeId:3,role:{value:'StaticText'},name:{value:'  Save   now  '}},
      {backendDOMNodeId:4,role:{value:'image'},name:{value:'Catalog image',sources:[{attribute:'alt',attributeValue:{value:'Product photo'},superseded:true}]}},
      {backendDOMNodeId:5,role:{value:'dialog'},name:{value:'Sign in'}},
      {backendDOMNodeId:6,role:{value:'alertdialog'},name:{value:'Confirm'}}
    ]};
    if(command==='DOM.resolveNode')return {object:{objectId:'text'}};
    if(command==='Runtime.callFunctionOn')return {result:{value:{x:10,y:10,width:10,height:10}}};
    if(command==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  assert.equal((await tab.observe()).nodes.length,0);
  assert.equal(await tab.playwright.getByRole('heading',{name:'Welcome',exact:true}).count(),1);
  await tab.playwright.getByText('Save now',{exact:true}).click();assert.equal(mouse,2);
  assert.equal(await tab.playwright.getByRole('img',{name:'Catalog image',exact:true}).count(),1);
  await tab.playwright.getByRole('img',{name:'Catalog image',exact:true}).click();assert.equal(mouse,4);
  assert.equal(await tab.playwright.getByAltText('Product photo',{exact:true}).count(),1);
  await tab.playwright.getByAltText('Product photo',{exact:true}).click();assert.equal(mouse,6);
  assert.equal(await tab.playwright.getByRole('dialog',{name:'Sign in',exact:true}).count(),1);
  assert.equal(await tab.playwright.getByRole('alertdialog',{name:'Confirm',exact:true}).count(),1);
  const state=await tab.observe({includeText:true});
  assert.equal(state.nodes.find(node=>node.role==='image').altText,'Product photo');assert.deepEqual(state.nodes.map(node=>node.role),['heading','StaticText','image','dialog','alertdialog']);
  const changed=await tab.observe({diff:true});assert.equal(changed.textMode,'full');
});

test('scoped locators disambiguate descendants and recheck the scope before input', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let moved=false, moveOnMeasure=false, moveOnFocus=false, renameOnMeasure=false, scopeName='Alpha', mouse=0, keys=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method, args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[
      {backendDOMNodeId:10,role:{value:'dialog'},name:{value:scopeName}},
      {backendDOMNodeId:11,role:{value:'dialog'},name:{value:'Beta'}},
      {backendDOMNodeId:12,role:{value:'list'},name:{value:'Products'}},
      {backendDOMNodeId:13,role:{value:'listitem'},name:{value:'Apples'}},
      {backendDOMNodeId:20,role:{value:'button'},name:{value:'Save'}},
      {backendDOMNodeId:21,role:{value:'button'},name:{value:'Save'}}
    ]};
    if(command==='DOM.resolveNode')return {object:{objectId:String(args.backendNodeId)}};
    if(command==='DOM.focus') { if(moveOnFocus)moved=true; return {}; }
    if(command==='Input.dispatchKeyEvent')keys++;
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('activeElement')) return {result:{value:true}};
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('target===this')) return {result:{value:args.objectId==='10' && args.arguments[0].objectId==='20' && !moved || args.objectId==='11' && args.arguments[0].objectId==='21' || args.objectId==='12' && ['13','20'].includes(args.arguments[0].objectId) || args.objectId==='13' && args.arguments[0].objectId==='20'}};
    if(command==='Runtime.callFunctionOn') { if(moveOnMeasure)moved=true; if(renameOnMeasure)scopeName='Renamed'; return {result:{value:{x:10,y:10,width:10,height:10}}}; }
    if(command==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  const save=tab.playwright.getByRole('dialog',{name:'Alpha',exact:true}).getByRole('button',{name:'Save',exact:true});
  assert.equal(await tab.playwright.getByRole('button',{name:'Save'}).count(),2);
  assert.equal(await save.count(),1);
  assert.equal(await tab.playwright.getByRole('list',{name:'Products'}).getByRole('listitem',{name:'Apples'}).getByRole('button',{name:'Save'}).count(),1);
  await save.click(); assert.equal(mouse,2);
  moveOnMeasure=true;
  await assert.rejects(save.click({timeoutMs:0}),/outside scope/);
  assert.equal(mouse,2);
  moved=false; moveOnMeasure=false; renameOnMeasure=true;
  await assert.rejects(save.click({timeoutMs:0}),/Scope changed/);
  assert.equal(mouse,2);
  moved=false; renameOnMeasure=false; scopeName='Alpha'; moveOnFocus=true;
  await assert.rejects(save.press('Enter',{timeoutMs:1000}),/outside scope/);
  assert.equal(keys,0);
});

test('text filters select unnamed containers and recheck changing text before input', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let apple='Apples', changeOnMeasure=false, changeOnFocus=false, unindexed=false, mouse=0, keys=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[
      {nodeId:'item1',backendDOMNodeId:10,role:{value:'listitem'},name:{value:''}},
      {backendDOMNodeId:11,role:{value:'listitem'},name:{value:''}},
      {backendDOMNodeId:12,role:{value:'listitem'},name:{value:'Apples'}},
      {backendDOMNodeId:20,role:{value:'StaticText'},name:{value:apple}},
      {backendDOMNodeId:21,role:{value:'StaticText'},name:{value:'Pears'}},
      {backendDOMNodeId:30,role:{value:'button'},name:{value:'Add'}},
      {backendDOMNodeId:31,role:{value:'button'},name:{value:'Add'}},
      ...(unindexed ? [{nodeId:'outside',backendDOMNodeId:99,role:{value:'generic'},name:{value:''}}, {parentId:unindexed==='related'?'item1':unindexed==='unrelated'?'outside':undefined,role:{value:'StaticText'},name:{value:'unindexed content'}}] : [])
    ]};
    if(command==='DOM.resolveNode')return {object:{objectId:String(args.backendNodeId)}};
    if(command==='DOM.focus'){if(changeOnFocus)apple='Bananas';return {};}
    if(command==='Input.dispatchKeyEvent')keys++;
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('activeElement')) return {result:{value:true}};
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('targets.map')) return {result:{value:args.arguments.map(argument => args.objectId==='10' && argument.objectId==='20' || args.objectId==='11' && argument.objectId==='21')}};
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('target===this')) return {result:{value:args.objectId==='10' && ['20','30'].includes(args.arguments[0].objectId) || args.objectId==='11' && ['21','31'].includes(args.arguments[0].objectId)}};
    if(command==='Runtime.callFunctionOn'){if(changeOnMeasure)apple='Bananas';return {result:{value:{x:10,y:10,width:10,height:10}}};}
    if(command==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1), items=tab.playwright.getByRole('listitem');
  assert.equal(await items.filter({hasText:'apples'}).count(),1);
  assert.equal(await items.filter({hasText:'apples',hasNotText:'pears'}).count(),1);
  assert.equal(await items.filter({hasNotText:'pears'}).count(),2);
  assert.equal(await items.nth(0).filter({hasText:'pears'}).count(),0);
  assert.equal(await items.filter({hasText:'pears'}).nth(0).count(),1);
  assert.equal(await items.last().filter({hasText:'pears'}).count(),0);
  assert.equal(await items.filter({hasText:'pears'}).last().count(),1);
  const button=items.filter({hasText:'Apples'}).getByRole('button',{name:'Add'});
  await button.click(); assert.equal(mouse,2);
  changeOnMeasure=true;
  await assert.rejects(button.click({timeoutMs:0}),/text changed/);
  assert.equal(mouse,2);
  apple='Apples'; changeOnMeasure=false; changeOnFocus=true;
  await assert.rejects(button.press('Enter',{timeoutMs:1000}),/text changed/);
  assert.equal(keys,0);
  apple='Apples'; changeOnFocus=false; unindexed='unrelated';
  assert.equal(await items.filter({hasText:'Apples'}).count(),1);
  unindexed='related';
  await assert.rejects(items.filter({hasNotText:'unindexed'}).count(),/cannot be indexed/);
  unindexed='unknown';
  await assert.rejects(items.filter({hasNotText:'unindexed'}).count(),/cannot be indexed/);
  unindexed=false; apple='x'.repeat(30001);
  await assert.rejects(items.filter({hasText:'x'}).count(),/30000 character limit/);
});

test('text filters batch checks and release all resolved nodes after failure', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'}), batches=[], released=[];
  let fail=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:10,role:{value:'listitem'},name:{value:''}},...Array.from({length:35},(_,i)=>({backendDOMNodeId:100+i,role:{value:'StaticText'},name:{value:`word${i}`}}))]};
    if(command==='DOM.resolveNode'){if(fail && args.backendNodeId===110)throw new Error('resolve failed');return {object:{objectId:String(args.backendNodeId)}};}
    if(command==='Runtime.callFunctionOn' && args.functionDeclaration.includes('targets.map')) {batches.push(args.arguments.length);return {result:{value:args.arguments.map(()=>true)}};}
    if(command==='Runtime.releaseObject')released.push(args.objectId);
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  assert.equal(await tab.playwright.getByRole('listitem').filter({hasText:'word34'}).count(),1);
  assert.deepEqual(batches,[32,3]); assert.equal(released.length,36);
  released.length=0; fail=true;
  await assert.rejects(tab.playwright.getByRole('listitem').filter({hasText:'word34'}).count(),/resolve failed/);
  assert.equal(released.length,32); assert.ok(released.includes('10'));
});

test('truncated alt text rejects locator matching and invalidates stale observations', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  let alt='x'.repeat(512)+'first', mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:3,role:{value:'image'},name:{value:'Label',sources:[{attribute:'alt',attributeValue:{value:alt}}]}}]};
    if(params.method==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1);
  const state=await tab.observe({includeText:true});
  assert.equal(state.nodes[0].altText.length,512);
  assert.equal(state.nodes[0].altTextTruncated,true);
  assert.doesNotMatch(JSON.stringify(state),/first/);
  await assert.rejects(tab.playwright.getByAltText('x',{exact:false}).count(),/truncated/);
  const refreshed=await tab.observe({includeText:true});
  alt='x'.repeat(512)+'second';
  await assert.rejects(tab.click(1,refreshed.snapshotId),/changed/);
  assert.equal(mouse,0);
});

test('locator waits for stable target geometry without sending input while moving', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let moving=true,reads=0,mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:'button'},name:{value:'Moving'}}]};
    if(command==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(command==='Runtime.callFunctionOn')return {result:{value:{x:moving?++reads*5:100,y:10,width:30,height:20}}};
    if(command==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),locator=tab.playwright.getByRole('button',{name:'Moving'});
  await assert.rejects(locator.click({timeoutMs:0}),/moving/);assert.equal(mouse,0);
  setTimeout(()=>{moving=false;},170);await locator.click({timeoutMs:1000});assert.equal(mouse,2);assert.ok(reads>=4);
});

test('target semantics are rechecked after the geometry stability interval', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let name='Save',mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:'button'},name:{value:name}}]};
    if(params.method==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(params.method==='Runtime.callFunctionOn')return {result:{value:{x:10,y:10,width:30,height:20}}};
    if(params.method==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),state=await tab.observe();
  setTimeout(()=>{name='Delete';},20);
  await assert.rejects(tab.click(1,state.snapshotId),/Target changed/);assert.equal(mouse,0);
});

test('placeholder locators retain superseded hints and reject stale or truncated hints', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let placeholder='Enter email',mouse=0;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:7,role:{value:'textbox'},name:{value:'Contact',sources:[{attribute:'placeholder',superseded:true,attributeValue:{value:placeholder}}]}}]};
    if(params.method==='DOM.resolveNode')return {object:{objectId:'target'}};
    if(params.method==='Runtime.callFunctionOn')return {result:{value:{x:10,y:10,width:30,height:20}}};
    if(params.method==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),locator=tab.playwright.getByPlaceholder('enter EMAIL');
  const state=await tab.observe();assert.equal(state.nodes[0].name,'Contact');assert.equal(state.nodes[0].placeholder,'Enter email');assert.match(state.text,/placeholder="Enter email"/);
  await locator.click();assert.equal(mouse,2);
  const stale=await tab.observe();placeholder='Different';await assert.rejects(tab.click(1,stale.snapshotId),/Target changed/);assert.equal(mouse,2);
  placeholder='x'.repeat(513);const limited=await tab.observe();assert.equal(limited.nodes[0].placeholderTruncated,true);
  await assert.rejects(tab.playwright.getByPlaceholder('x').count(),/truncated/);
});

test('date and numeric fills validate before mutation and never repeat uncertain changes', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});let status='invalid',mutations=0,mouse=0,fail=false;
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    const command=params.method,args=params.commandParams;
    if(command==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(command==='Page.getFrameTree')return {frameTree:{frame:{id:'root',loaderId:'v1',url:'https://example.test'}}};
    if(command==='Accessibility.getFullAXTree')return {nodes:[{backendDOMNodeId:2,role:{value:'Date'},name:{value:'Day'}},{backendDOMNodeId:3,role:{value:'spinbutton'},name:{value:'Amount'}}]};
    if(command==='DOM.resolveNode')return {object:{objectId:String(args.backendNodeId)}};
    if(command==='Runtime.callFunctionOn'){
      if(args.functionDeclaration.includes('const probe='))return {result:{value:status}};
      if(args.functionDeclaration.includes('const setter=')){mutations++;if(fail)throw Error('mutation result unknown');return {result:{value:true}};}
      return {result:{value:{x:10,y:10,width:30,height:20}}};
    }
    if(command==='Input.dispatchMouseEvent')mouse++;
    return {};
  };
  const tab=new OpenBrowserUseBrowser({client}).tab(1),day=tab.playwright.getByLabel('Day'),amount=tab.playwright.getByLabel('Amount');
  await assert.rejects(day.fill('invalid',{timeoutMs:0}),/Invalid date or time/);assert.equal(mutations,0);assert.equal(mouse,0);
  await assert.rejects(amount.fill('invalid',{timeoutMs:0}),/Invalid number/);assert.equal(mouse,0);
  status='ok';await day.fill('2026-12-31');assert.equal(mutations,1);assert.equal(mouse,0);
  fail=true;await assert.rejects(day.fill('2026-01-01',{timeoutMs:500}),/mutation result unknown/);assert.equal(mutations,2);
});

test('date component internals are not exposed as separate targets', async () => {
  const client=new OpenBrowserUseClient({socketPath:'unused'});
  client.request=async(method,params)=>{
    if(method==='attach')return {};
    if(params.method==='DOM.getDocument')return {root:{backendNodeId:1}};
    if(params.method==='Accessibility.getFullAXTree')return {nodes:[
      {nodeId:'d',backendDOMNodeId:2,role:{value:'Date'},name:{value:'Day'}},
      {nodeId:'g',parentId:'d',backendDOMNodeId:3,role:{value:'group'},name:{value:''}},
      {nodeId:'year',parentId:'g',backendDOMNodeId:4,role:{value:'spinbutton'},name:{value:'Year'}},
      {nodeId:'text',parentId:'g',backendDOMNodeId:5,role:{value:'StaticText'},name:{value:'2026'}},
      {nodeId:'number',backendDOMNodeId:6,role:{value:'spinbutton'},name:{value:'Amount'}}
    ]};
    return {};
  };
  const state=await new OpenBrowserUseBrowser({client}).tab(1).observe({includeText:true});
  assert.deepEqual(state.nodes.map(node=>node.name),['Day','Amount']);
});
