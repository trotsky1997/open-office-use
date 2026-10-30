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
const Backend=vm.runInNewContext(`${source.slice(0,end)}\nBrowserBackend;`,{chrome,crypto:webcrypto,Date,setTimeout,clearTimeout});

test('download wait observes the next start while paths retain completed results',async()=>{
  const backend=new Backend();await backend.store.ready;
  backend.requireSessionTab=async()=>({});backend.requireSession=async()=>({});
  backend.emitDownloadChange({id:'old',status:'complete',filename:'/tmp/old'});
  let settled=false;
  const pending=backend.waitForDownload({tabId:1,timeoutMs:1000}).then(value=>{settled=true;return value;});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
  backend.emitDownloadChange({id:'old',status:'in_progress',filename:'/tmp/old'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
  backend.emitDownloadChange({id:'new',status:'started',filename:'/tmp/new'});
  assert.equal((await pending).downloadId,'new');
  backend.emitDownloadChange({id:'new',status:'complete',filename:'/tmp/new'});
  assert.equal((await backend.downloadPath({downloadId:'new'})).path,'/tmp/new');
  await assert.rejects(backend.waitForDownload({tabId:1,timeoutMs:10}),/Timed out/);
  assert.equal(backend.downloadWaiters.size,0);
});

test('download readiness is emitted only after the waiter is installed',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});
  let observed=false;backend.downloadReadyListeners.add(id=>{observed=true;assert.equal(id,'00000000-0000-0000-0000-000000000000');assert.equal(backend.downloadWaiters.size,1);});
  const pending=backend.waitForDownload({tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(observed,true);
  backend.emitDownloadChange({id:'ready',status:'started'});assert.equal((await pending).downloadId,'ready');
});

test('only one Chrome download start wait may be active',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});
  const first=backend.waitForDownload({tabId:1,timeoutMs:1000});
  await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(backend.waitForDownload({tabId:2,timeoutMs:1000}),/Already waiting/);
  backend.emitDownloadChange({id:'first',status:'started'});assert.equal((await first).downloadId,'first');
  await assert.rejects(backend.waitForDownload({tabId:2,timeoutMs:10}),/Timed out/);
  const next=backend.waitForDownload({tabId:2,timeoutMs:1000});
  await new Promise(resolve=>setImmediate(resolve));
  backend.emitDownloadChange({id:'next',status:'started'});assert.equal((await next).downloadId,'next');
});

test('file chooser readiness follows interception and preserves the frame session',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.requireSession=async()=>({});backend.attachedTabs.add(1);
  commands.length=0;let ready=false;
  backend.handleCdpEvent({tabId:1},'Target.attachedToTarget',{sessionId:'frame-session',targetInfo:{type:'iframe'}});
  backend.fileChooserReadyListeners.add(()=>{ready=true;assert.equal(commands.at(-1).method,'Page.setInterceptFileChooserDialog');assert.equal(commands.at(-1).params.enabled,true);});
  const pending=backend.waitForFileChooser({tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
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
