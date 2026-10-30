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

test('file chooser readiness follows interception and preserves the frame session',async()=>{
  const backend=new Backend();await backend.store.ready;backend.requireSessionTab=async()=>({});backend.requireSession=async()=>({});backend.attachedTabs.add(1);
  commands.length=0;let ready=false;
  backend.fileChooserReadyListeners.add(()=>{ready=true;assert.equal(commands.at(-1).method,'Page.setInterceptFileChooserDialog');assert.equal(commands.at(-1).params.enabled,true);});
  const pending=backend.waitForFileChooser({tabId:1,timeoutMs:1000,waitId:'00000000-0000-0000-0000-000000000000'});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(ready,true);
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
