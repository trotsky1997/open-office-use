import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('./background.js',import.meta.url),'utf8');
const end=source.indexOf('chrome.runtime.onInstalled.addListener');
assert.notEqual(end,-1);
const chrome={debugger:{onDetach:{addListener(){}}},storage:{local:{async get(){return {};},async set(){}}}};
const Backend=vm.runInNewContext(`${source.slice(0,end)}\nBrowserBackend;`,{chrome,Date,setTimeout,clearTimeout});

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
