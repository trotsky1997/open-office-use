import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { app, BrowserWindow } from 'electron';
import { createIabRuntime } from '../../packages/open-browser-use-electron/dist/index.js';
import { connectSocketIab } from '../../packages/open-browser-use-electron/dist/client.js';
import { startFixture } from './fixture.mjs';

if (!['darwin','linux'].includes(process.platform)) throw new Error('Socket probe requires macOS or Linux');
const directory=mkdtempSync(join(tmpdir(),'obu-hidden-input-probe-'));app.setPath('userData',directory);
app.whenReady().then(async()=>{
  const fixture=await startFixture(), runtime=createIabRuntime({appId:'hidden-input-probe'});
  const window=new BrowserWindow({show:false,width:820,height:620});let exitCode=1;
  try {
    runtime.profiles.open({id:'probe',persistent:false});const scope=runtime.scopes.open({id:'probe',profileId:'probe'});
    const tab=await scope.tabs.create({url:fixture.url});
    const surface=runtime.surfaces.register({id:'panel',window,owner:window.webContents});surface.setBounds({x:0,y:0,width:800,height:600});surface.present(tab.id);
    await runtime.connections.openSocket();
    const grant=runtime.connections.grant(scope.id,'socket',{ttlMs:30000,operations:['page.control']},process.pid);
    const client=await connectSocketIab(grant), sdk=client.browser().tab(tab.id);
    await sdk.evaluate(`(()=>{const button=document.createElement('button');button.id='probe';button.textContent='Probe';Object.assign(button.style,{position:'fixed',left:'20px',top:'20px',width:'100px',height:'50px',zIndex:'99999'});button.onclick=e=>window.probeTrusted=e.isTrusted;document.body.append(button)})()`);
    let outcome='clicked';
    try { await sdk.clickAt(50,40); }
    catch (error) { if (!(error instanceof Error) || error.message!=='IAB_INPUT_PREPARATION_TIMEOUT') throw error; outcome='preparation-timeout'; }
    await new Promise(resolve=>setTimeout(resolve,100));
    const clicked=await sdk.evaluate('window.probeTrusted ?? null');
    assert.equal(window.isVisible(),false);
    assert.equal(clicked,outcome==='clicked' ? true : null);
    client.close();
    console.log(JSON.stringify({platform:process.platform,electron:process.versions.electron,outcome,windowVisible:window.isVisible(),trustedClick:clicked}));
    exitCode=outcome==='clicked' ? 0 : 2;
  } catch(error) { console.error(error); }
  finally { await runtime.dispose();window.destroy();await fixture.close();rmSync(directory,{recursive:true,force:true});app.exit(exitCode); }
});
