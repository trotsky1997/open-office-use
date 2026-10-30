import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {app,BrowserWindow} from 'electron';
import {createIabRuntime} from '../../packages/open-browser-use-electron/dist/index.js';
import {connectSocketIab} from '../../packages/open-browser-use-electron/dist/client.js';
import {startFixture} from './fixture.mjs';
if (!['darwin','linux'].includes(process.platform)) throw new Error('Socket upload smoke requires macOS or Linux');
app.commandLine.appendSwitch('site-per-process');
const root=mkdtempSync(join(tmpdir(),'obu-upload-smoke-'));app.setPath('userData',root);
app.whenReady().then(async()=>{
  const fixture=await startFixture();const runtime=createIabRuntime({appId:'upload-smoke'});
  const window=new BrowserWindow({show:true,width:820,height:620,webPreferences:{backgroundThrottling:true}});
  try{
    runtime.profiles.open({id:'p',persistent:false});const scope=runtime.scopes.open({id:'s',profileId:'p'});
    const tab=await scope.tabs.create({url:fixture.url});const surface=runtime.surfaces.register({id:'panel',window,owner:window.webContents});surface.setBounds({x:0,y:0,width:800,height:600});surface.present(tab.id);
    const file=join(root,'fixture.txt');writeFileSync(file,'fixture');await scope.files.authorize([file]);await scope.downloads.configure({directory:root,maxBytes:1024});
    await runtime.connections.openSocket();
    const grant=runtime.connections.grant(scope.id,'socket',{ttlMs:120000,operations:['page.control','files.upload','files.download']},process.pid);
    const client=await connectSocketIab(grant);
    const sdk=client.browser().tab(tab.id);
    await sdk.evaluate(`(()=>{const e=document.createElement('input');e.type='file';e.id='upload';Object.assign(e.style,{position:'fixed',left:'20px',top:'150px',width:'250px',height:'40px',zIndex:'9999'});document.body.append(e)})()`);
    const armed=await sdk.prepareFileChooser({timeoutMs:20000});const choosing=armed.wait();void choosing.catch(()=>{});
    const clicking=sdk.clickAt(40,158);void clicking.catch(()=>{});const chooser=await choosing;await chooser.setFiles(file);await clicking;
    assert.deepEqual(await sdk.evaluate("Array.from(document.querySelector('#upload').files,f=>f.name)"),['fixture.txt']);
    await sdk.evaluate(`(()=>{const a=document.createElement('a');a.href='/download-fixture';a.textContent='Download fixture';a.id='fixture-download';Object.assign(a.style,{position:'fixed',left:'20px',top:'100px',zIndex:'9999'});document.body.append(a)})()`);
    const downloadReady=await sdk.prepareDownload({timeoutMs:20000});const downloadWait=downloadReady.wait();void downloadWait.catch(()=>{});
    await sdk.playwright.getByRole('link',{name:'Download fixture',exact:true}).click({timeoutMs:20000});
    const download=await downloadWait, downloadPath=await download.path(20000);assert.ok(downloadPath);assert.equal(readFileSync(downloadPath,'utf8'),'isolated download fixture');
    await scope.downloads.configure({directory:root,maxBytes:1});
    const limitReady=await sdk.prepareDownload({timeoutMs:20000}),limitedWait=limitReady.wait();void limitedWait.catch(()=>{});
    await sdk.playwright.getByRole('link',{name:'Download fixture',exact:true}).click({timeoutMs:20000});
    let limitedPath=null;
    try { limitedPath=await (await limitedWait).path(20000); }
    catch(error){if (!(error instanceof Error) || error.message!=='IAB_DOWNLOAD_SIZE_LIMIT')throw error;}
    assert.equal(limitedPath,null);
    await new Promise(resolve=>setImmediate(resolve));await scope.downloads.configure({directory:root,maxBytes:1024});


    const crossUrl=fixture.url.replace('127.0.0.1','localhost')+'/cross-frame';
    await sdk.evaluate(`(async()=>{const f=document.createElement('iframe');f.id='cross';f.src=${JSON.stringify(crossUrl)};Object.assign(f.style,{position:'fixed',left:'20px',top:'200px',width:'500px',height:'300px',zIndex:'9999'});document.body.append(f);await new Promise(resolve=>f.onload=resolve)})()`,{awaitPromise:true});
    const observed=await sdk.observe({includeFrames:true});const node=observed.nodes.find(item=>item.name==='Cross-frame action');assert.ok(node?.frameId);
    const session=(await sdk.browser.cdp.frameSessions(tab.id)).find(frame=>frame.frameId===node.frameId)?.sessionId;assert.ok(session);
    await sdk.browser.cdp.call(tab.id,'Runtime.evaluate',{expression:`(()=>{const e=document.createElement('input');e.type='file';e.id='child-upload';e.setAttribute('aria-label','Child upload');document.body.prepend(e)})()`},{sessionId:session});
    window.hide();
    const childReady=await sdk.prepareFileChooser({timeoutMs:20000});const childWait=childReady.wait();void childWait.catch(()=>{});
    const childClick=sdk.playwright.getByRole('button',{name:'Child upload',exact:true}).click({timeoutMs:20000});void childClick.catch(()=>{});
    const childChooser=await childWait;await childChooser.setFiles(file);await childClick;
    const selected=await sdk.browser.cdp.call(tab.id,'Runtime.evaluate',{expression:"Array.from(document.querySelector('#child-upload').files,f=>f.name)",returnByValue:true},{sessionId:session});
    assert.deepEqual(selected.result.value,['fixture.txt']);
    await sdk.browser.cdp.call(tab.id,'Runtime.evaluate',{expression:`(()=>{const a=document.createElement('a');a.href=${JSON.stringify(fixture.url+'/download-fixture')};a.textContent='Child download';document.body.prepend(a)})()`},{sessionId:session});
    const childDownloadReady=await sdk.prepareDownload({timeoutMs:20000});const childDownloading=childDownloadReady.wait();void childDownloading.catch(()=>{});
    await sdk.playwright.getByRole('link',{name:'Child download',exact:true}).click({timeoutMs:20000});
    const childDownload=await childDownloading,childPath=await childDownload.path(20000);assert.ok(childPath);assert.equal(readFileSync(childPath,'utf8'),'isolated download fixture');
    console.log(JSON.stringify({passed:true,platform:process.platform,electron:process.versions.electron,scope:'socket-upload-download-and-hidden-cross-frame'}));
  }finally{await runtime.dispose();window.destroy();await fixture.close();rmSync(root,{recursive:true,force:true});}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
