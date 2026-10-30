import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('./background.js',import.meta.url),'utf8');
const end=source.indexOf('chrome.runtime.onInstalled.addListener');
assert.notEqual(end,-1);
const commands=[];
const chrome={debugger:{onDetach:{addListener(){}},async sendCommand(target,method,params){commands.push({target,method,params});}},storage:{local:{async get(){return {};},async set(){}}}};
const Backend=vm.runInNewContext(`${source.slice(0,end)}\nBrowserBackend;`,{chrome,crypto:webcrypto,Date,setTimeout,clearTimeout,AbortController});

test('tab presentation reports physical selection only for owned tabs',async()=>{
  const backend=new Backend();await backend.store.ready;let active=false,gets=0,state='normal';
  backend.requireSessionTab=async params=>{if(params.tabId!==1)throw new Error('not owned');};
  const oldTabs=chrome.tabs,oldWindows=chrome.windows;
  chrome.tabs={async get(){gets++;return {active,windowId:4};}};chrome.windows={async get(){return {state,focused:true};}};
  try {
    assert.deepEqual(JSON.parse(JSON.stringify(await backend.getTabPresentation({tabId:1}))),{backend:'chrome',selected:false,visible:false,windowFocused:true});
    active=true;assert.deepEqual(JSON.parse(JSON.stringify(await backend.getTabPresentation({tabId:1}))),{backend:'chrome',selected:true,visible:null,windowFocused:true});
    state='minimized';assert.equal((await backend.getTabPresentation({tabId:1})).visible,false);
    await assert.rejects(backend.getTabPresentation({tabId:2}),/not owned/);assert.equal(gets,3);
  } finally {chrome.tabs=oldTabs;chrome.windows=oldWindows;}
});

test('download wait observes the next start while paths retain completed results',async()=>{
  const backend=new Backend();await backend.store.ready;
  backend.requireSessionTab=async()=>({});backend.requireSession=async()=>({});
  backend.emitDownloadChange({id:'old',status:'complete',filename:'/tmp/old'});
  let settled=false;
  const pending=backend.waitForDownload({session_id:'owner',tabId:1,timeoutMs:1000}).then(value=>{settled=true;return value;});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
  backend.emitDownloadChange({id:'old',status:'in_progress',filename:'/tmp/old'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
  backend.emitDownloadChange({id:'new',status:'started',filename:'/tmp/new',url:'https://example.test/file'});
  const download=await pending;assert.notEqual(download.downloadId,'new');assert.match(download.downloadId,/^[0-9a-f-]{36}$/);assert.equal(download.url,'https://example.test/file');assert.equal(download.attribution,'browser');
  backend.emitDownloadChange({id:'new',status:'complete',filename:'/tmp/new'});
  assert.equal((await backend.downloadPath({session_id:'owner',downloadId:download.downloadId})).path,'/tmp/new');
  await assert.rejects(backend.waitForDownload({tabId:1,timeoutMs:10}),/Timed out/);
  assert.equal(backend.downloadWaiters.size,0);
});

test('download readiness is emitted only after the waiter is installed',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});
  let observed=false;backend.downloadReadyListeners.add((id,session)=>{observed=true;assert.equal(session,'owner');assert.equal(id,'00000000-0000-0000-0000-000000000000');assert.equal(backend.downloadWaiters.size,1);});
  const pending=backend.waitForDownload({session_id:'owner',tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(observed,true);
  backend.emitDownloadChange({id:'ready',status:'started'});assert.equal(backend.downloadHandles.get((await pending).downloadId).nativeId,'ready');
});

test('clipboard evaluation exposes a bounded permission error',async()=>{
  const backend=new Backend();await backend.store.ready;const original=chrome.debugger.sendCommand;
  chrome.debugger.sendCommand=async()=>({exceptionDetails:{text:'Uncaught (in promise)',exception:{description:'NotAllowedError: clipboard denied\n    at page.js:1'}}});
  try {await assert.rejects(backend.evaluateJavascript(1,'navigator.clipboard.readText()',true),error=>error.message==='NotAllowedError: clipboard denied');}
  finally {chrome.debugger.sendCommand=original;}
});

test('only one Chrome download start wait may be active',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});
  const first=backend.waitForDownload({tabId:1,timeoutMs:1000});
  await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(backend.waitForDownload({tabId:2,timeoutMs:1000}),/Already waiting/);
  backend.emitDownloadChange({id:'first',status:'started'});assert.equal(backend.downloadHandles.get((await first).downloadId).nativeId,'first');
  await assert.rejects(backend.waitForDownload({tabId:2,timeoutMs:10}),/Timed out/);
  const next=backend.waitForDownload({tabId:2,timeoutMs:1000});
  await new Promise(resolve=>setImmediate(resolve));
  backend.emitDownloadChange({id:'next',status:'started'});assert.equal(backend.downloadHandles.get((await next).downloadId).nativeId,'next');
});

test('ending the owning session cancels its pending download wait',async()=>{
  const backend=new Backend();await backend.store.ready;
  backend.requireSessionTab=async()=>({});backend.requireSession=async params=>({sessionId:params.session_id});
  backend.getSessionTabs=async()=>[];backend.publishCursorState=async()=>{};
  const first=backend.waitForDownload({session_id:'first',tabId:1,timeoutMs:1000});
  const canceled=assert.rejects(first,/Download wait canceled/);
  await new Promise(resolve=>setImmediate(resolve));
  await backend.turnEnded({session_id:'other'});assert.equal(backend.downloadWaiters.size,1);
  await backend.turnEnded({session_id:'first'});await canceled;
  assert.equal(backend.downloadWaiters.size,0);assert.equal(backend.downloadStartWait,null);
  const next=backend.waitForDownload({session_id:'other',tabId:2,timeoutMs:1000});
  await new Promise(resolve=>setImmediate(resolve));backend.emitDownloadChange({id:'next',status:'started'});
  assert.equal(backend.downloadHandles.get((await next).downloadId).nativeId,'next');
});

test('session cleanup also cancels a download wait during tab validation',async()=>{
  const backend=new Backend();await backend.store.ready;
  let release;backend.requireSessionTab=()=>new Promise(resolve=>{release=resolve;});
  backend.requireSession=async params=>({sessionId:params.session_id});backend.getSessionTabs=async()=>[];
  let ready=false;backend.downloadReadyListeners.add(()=>{ready=true;});
  const pending=backend.waitForDownload({session_id:'first',tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
  const canceled=assert.rejects(pending,/Download wait canceled/);
  await backend.turnEnded({session_id:'first'});release();await canceled;
  assert.equal(ready,false);assert.equal(backend.downloadWaiters.size,0);assert.equal(backend.downloadStartWait,null);
});

test('file chooser readiness follows interception and preserves the frame session',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.requireSession=async()=>({});backend.attachedTabs.add(1);
  commands.length=0;let ready=false;
  backend.handleCdpEvent({tabId:1},'Target.attachedToTarget',{sessionId:'frame-session',targetInfo:{type:'iframe'}});
  backend.fileChooserReadyListeners.add((_id,session)=>{assert.equal(session,'owner');ready=true;assert.equal(commands.at(-1).method,'Page.setInterceptFileChooserDialog');assert.equal(commands.at(-1).params.enabled,true);});
  const pending=backend.waitForFileChooser({session_id:'owner',tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(ready,true);
  assert.ok(commands.some(call=>call.target.sessionId==='frame-session' && call.method==='Page.setInterceptFileChooserDialog' && call.params.enabled));
  backend.handleCdpEvent({tabId:1,sessionId:'frame-session'},'Page.fileChooserOpened',{backendNodeId:42,mode:'selectMultiple'});
  const result=await pending;assert.equal(result.isMultiple,true);
  await backend.setFileChooserFiles({fileChooserId:result.fileChooserId,files:['/tmp/fixture']});
  const call=commands.at(-1);assert.equal(call.method,'DOM.setFileInputFiles');assert.equal(call.target.sessionId,'frame-session');assert.equal(call.params.backendNodeId,42);
});

test('navigation invalidates pending chooser handles before a file decision',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSession=async()=>({});
  let release;backend.requireSessionTab=()=>new Promise(resolve=>{release=resolve;});
  backend.fileChoosersById.set('chooser',{tabId:1,backendNodeId:42,isMultiple:false});
  const decision=backend.setFileChooserFiles({fileChooserId:'chooser',files:['/tmp/fixture']});
  await new Promise(resolve=>setImmediate(resolve));
  backend.handleCdpEvent({tabId:1},'Page.frameNavigated',{});release();
  await assert.rejects(decision,/no longer available/);
});

test('file chooser decision is consumed before a failed browser command',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSession=async()=>({});backend.requireSessionTab=async()=>({});
  backend.fileChoosersById.set('chooser',{tabId:1,backendNodeId:42,isMultiple:false});
  const original=chrome.debugger.sendCommand;let count=0;
  chrome.debugger.sendCommand=async()=>{count++;throw new Error('outcome unknown');};
  try {
    await assert.rejects(backend.setFileChooserFiles({fileChooserId:'chooser',files:['/tmp/fixture']}),/outcome unknown/);
    await assert.rejects(backend.setFileChooserFiles({fileChooserId:'chooser',files:['/tmp/fixture']}),/Unknown file chooser/);
    assert.equal(count,1);
  } finally {chrome.debugger.sendCommand=original;}
});

test('frame changes stop an armed chooser and release interception',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.attachedTabs.add(1);
  const pending=backend.waitForFileChooser({tabId:1,timeoutMs:1000});
  const rejected=assert.rejects(pending,/Frame tree changed/);
  await new Promise(resolve=>setImmediate(resolve));
  backend.handleCdpEvent({tabId:1},'Target.attachedToTarget',{sessionId:'new-frame',targetInfo:{type:'iframe'}});
  await rejected;assert.equal(backend.fileChooserWaitersByTabId.size,0);
});

test('a second chooser cannot arm while interception is being released',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.attachedTabs.add(1);
  const original=chrome.debugger.sendCommand;let release;
  chrome.debugger.sendCommand=async(_target,method,params)=>{
    if(method==='Page.setInterceptFileChooserDialog' && !params.enabled)await new Promise(resolve=>{release=resolve;});
  };
  try {
    const pending=backend.waitForFileChooser({tabId:1,timeoutMs:1000});
    await new Promise(resolve=>setImmediate(resolve));
    backend.handleCdpEvent({tabId:1},'Page.fileChooserOpened',{backendNodeId:7,mode:'selectSingle'});
    await new Promise(resolve=>setImmediate(resolve));
    await assert.rejects(backend.waitForFileChooser({tabId:1,timeoutMs:1000}),/Already waiting/);
    release();await pending;assert.equal(backend.fileChooserWaitersByTabId.size,0);
  } finally {chrome.debugger.sendCommand=original;}
});

test('interception setup failure still attempts to disable interception',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.attachedTabs.add(1);
  const original=chrome.debugger.sendCommand;const states=[];
  chrome.debugger.sendCommand=async(_target,method,params)=>{
    if(method==='Page.setInterceptFileChooserDialog'){states.push(params.enabled);if(params.enabled)throw new Error('setup outcome unknown');}
  };
  try {
    await assert.rejects(backend.waitForFileChooser({tabId:1,timeoutMs:1000}),/setup outcome unknown/);
    assert.deepEqual(states,[true,false]);assert.equal(backend.fileChooserWaitersByTabId.size,0);
  } finally {chrome.debugger.sendCommand=original;}
});

test('cancelled CDP request does not dispatch after delayed tab authorization',async()=>{
  const Peer=vm.runInNewContext(`${source.slice(0,end)}\nJsonRpcPeer;`,{chrome,crypto:webcrypto,Date,setTimeout,clearTimeout,AbortController});
  const backend=new Backend();await backend.store.ready;backend.attachedTabs.add(1);let release;
  backend.requireSession=async()=>({});backend.requireSessionTab=async()=>await new Promise(resolve=>{release=resolve;});
  const sent=[],transport={setMessageCallback(){},sendMessage(message){sent.push(message);}},peer=new Peer(transport,backend);
  const before=commands.length;const pending=peer.handleMessage({jsonrpc:'2.0',id:'host-1',method:'executeCdp',params:{target:{tabId:1},method:'Input.insertText'}});
  while(!release)await new Promise(resolve=>setImmediate(resolve));
  await peer.handleMessage({jsonrpc:'2.0',method:'obu.cancel',params:{id:'host-1'}});release();await pending;
  assert.equal(commands.length,before);assert.equal(sent.length,0);assert.equal(peer.inFlight.size,0);
});

test('cancelled waits release download slots and file chooser interception',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.attachedTabs.add(1);
  const downloadAbort=new AbortController();const download=backend.waitForDownload({tabId:1,timeoutMs:1000},downloadAbort.signal);
  await new Promise(resolve=>setImmediate(resolve));downloadAbort.abort();await assert.rejects(download,/canceled/);assert.equal(backend.downloadStartWait,null);assert.equal(backend.downloadWaiters.size,0);
  const chooserAbort=new AbortController();const chooser=backend.waitForFileChooser({tabId:1,timeoutMs:1000},chooserAbort.signal);
  await new Promise(resolve=>setImmediate(resolve));chooserAbort.abort();await assert.rejects(chooser,/canceled/);assert.equal(backend.fileChooserWaitersByTabId.size,0);
  assert.deepEqual(commands.filter(c=>c.method==='Page.setInterceptFileChooserDialog').slice(-2).map(c=>c.params.enabled),[true,false]);
});

test('cancelled download path releases its completion listener',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSession=async()=>({});
  backend.downloadHandles.set('pending',{sessionId:'owner',nativeId:'native-pending'});const controller=new AbortController();const pending=backend.downloadPath({session_id:'owner',downloadId:'pending',timeoutMs:5000},controller.signal);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(backend.downloadWaiters.size,1);controller.abort();
  await assert.rejects(pending,/canceled/);assert.equal(backend.downloadWaiters.size,0);
});

test('debugger attachment records the owning session and clears it on detach',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>{};
  const previousAttach=chrome.debugger.attach,previousDetach=chrome.debugger.detach;
  chrome.debugger.attach=async()=>{};chrome.debugger.detach=async()=>{};
  try{await backend.attach({session_id:'owner',tabId:7});assert.equal(backend.debuggerSessionByTabId.get(7),'owner');await backend.detach({session_id:'owner',tabId:7});assert.equal(backend.debuggerSessionByTabId.has(7),false);}
  finally{chrome.debugger.attach=previousAttach;chrome.debugger.detach=previousDetach;}
});

test('download paths are restricted to the waiting session',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.requireSession=async params=>({sessionId:params.session_id});
  const pending=backend.waitForDownload({session_id:'owner',tabId:1,timeoutMs:1000});await new Promise(resolve=>setImmediate(resolve));
  backend.emitDownloadChange({id:'owned',status:'started',url:'https://example.test/file'});const handle=(await pending).downloadId;assert.notEqual(handle,'owned');
  await assert.rejects(backend.downloadPath({session_id:'other',downloadId:handle}),/unavailable/);
  await assert.rejects(backend.downloadPath({session_id:'other',downloadId:'unknown'}),/unavailable/);
  backend.emitDownloadChange({id:'owned',status:'complete',filename:'/private/file'});
  assert.equal((await backend.downloadPath({session_id:'owner',downloadId:handle})).path,'/private/file');
});

test('cancelled debugger attachment stops after delayed authorization',async()=>{
  const backend=new Backend();await backend.store.ready;let release,calls=0;backend.requireSessionTab=async()=>await new Promise(resolve=>{release=resolve;});
  const previous=chrome.debugger.attach;chrome.debugger.attach=async()=>{calls++;};
  try{const controller=new AbortController();const pending=backend.attach({session_id:'owner',tabId:7},controller.signal);while(!release)await new Promise(resolve=>setImmediate(resolve));controller.abort();release();await assert.rejects(pending,/cancelled/);assert.equal(calls,0);assert.equal(backend.debuggerSessionByTabId.size,0);}
  finally{chrome.debugger.attach=previous;}
});

test('discovered session tabs record their current owner',async()=>{
  const backend=new Backend();await backend.store.ready;backend.store.state.sessions.owner={chromeGroupId:9,tabOrigins:{}};
  const previous=chrome.tabs;chrome.tabs={async query(){return [{id:7,url:'https://example.test/'},{id:8,url:'chrome://settings'}];}};
  try{const tabs=await backend.getSessionTabs('owner');assert.equal(tabs.length,1);assert.equal(backend.sessionByTabId.get(7),'owner');assert.equal(backend.sessionByTabId.has(8),false);}
  finally{chrome.tabs=previous;}
});

test('moving a tab revokes previous ownership and pending waits',async()=>{
  const backend=new Backend();await backend.store.ready;backend.store.state.sessions.a={chromeGroupId:1};backend.store.state.sessions.b={chromeGroupId:2};
  backend.sessionByTabId.set(7,'a');backend.debuggerSessionByTabId.set(7,'a');let lost;backend.ownershipLostListeners.add((tabId,session)=>{lost={tabId,session};});
  const controller=new AbortController();backend.downloadStartWait={tabId:7,sessionId:'a',controller};backend.fileChoosersById.set('chooser',{tabId:7});
  backend.handleTabGroupChange(7,2);assert.deepEqual(lost,{tabId:7,session:'a'});assert.equal(backend.sessionByTabId.get(7),'b');assert.equal(backend.debuggerSessionByTabId.has(7),false);assert.equal(controller.signal.aborted,true);assert.equal(backend.fileChoosersById.has('chooser'),false);
});

test('delayed group query cannot restore stale tab ownership',async()=>{
  const backend=new Backend();await backend.store.ready;backend.store.state.sessions.a={chromeGroupId:1};backend.store.state.sessions.b={chromeGroupId:2};backend.sessionByTabId.set(7,'a');
  let release;const previous=chrome.tabs;chrome.tabs={query:async()=>await new Promise(resolve=>{release=resolve;})};
  try{const pending=backend.getSessionTabs('a');while(!release)await new Promise(resolve=>setImmediate(resolve));backend.handleTabGroupChange(7,2);release([{id:7,url:'https://example.test/'}]);assert.equal((await pending).length,0);assert.equal(backend.sessionByTabId.get(7),'b');}
  finally{chrome.tabs=previous;}
});

test('ungrouping distinguishes tab closure from ownership loss',async()=>{
  const backend=new Backend();await backend.store.ready;backend.store.state.sessions.a={chromeGroupId:1};let release;const previous=chrome.tabs;chrome.tabs={get:async()=>await new Promise(resolve=>{release=resolve;})};const lost=[];backend.ownershipLostListeners.add((tab,session)=>lost.push({tab,session}));
  try {
    backend.sessionByTabId.set(7,'a');backend.handleTabGroupChange(7,-1);assert.equal(backend.takeClosedOwner(7),'a');release({id:7,groupId:-1});await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(lost,[]);
    backend.sessionByTabId.set(8,'a');backend.handleTabGroupChange(8,-1);release({id:8,groupId:-1});await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(lost,[{tab:8,session:'a'}]);assert.equal(backend.takeClosedOwner(8),undefined);
    backend.sessionByTabId.set(9,'a');backend.handleTabGroupChange(9,-1);backend.handleTabGroupChange(9,1);release({id:9,groupId:1});await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(lost,[{tab:8,session:'a'},{tab:9,session:'a'}]);assert.equal(backend.sessionByTabId.get(9),'a');
  } finally{chrome.tabs=previous;}
});
