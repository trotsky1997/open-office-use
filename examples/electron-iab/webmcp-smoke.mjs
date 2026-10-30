import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { app } from 'electron';
import { startFixture } from './fixture.mjs';

const root=mkdtempSync(join(tmpdir(),'obu-webmcp-smoke-'));
app.setPath('userData',root);
const packageDir=process.env.OBU_IAB_PACKAGE_DIR ? resolve(process.env.OBU_IAB_PACKAGE_DIR) : resolve('packages/open-browser-use-electron');
const {createIabRuntime}=await import(pathToFileURL(join(packageDir,'dist/index.js')).href);
const {connectSocketIab}=await import(pathToFileURL(join(packageDir,'dist/client.js')).href);

app.whenReady().then(async()=>{
  const fixture=await startFixture(),runtime=createIabRuntime({appId:'webmcp-smoke'});
  try {
    runtime.profiles.open({id:'p',persistent:false});
    const scope=runtime.scopes.open({id:'s',profileId:'p',webmcp:true});
    const tab=await scope.tabs.create({url:fixture.url+'/webmcp-fixture'});
    await runtime.connections.openSocket();
    const grant=runtime.connections.grant(scope.id,'socket',{ttlMs:30000,operations:['tabs.read','page.control']},process.pid);
    const client=await connectSocketIab(grant),sdk=client.browser().tab(tab.id);
    const web=await sdk.capabilities.get('webmcp'),tool=(await web.listTools()).find(item=>item.name==='fixture_echo');
    assert.ok(tool);assert.deepEqual(await web.invokeTool(tool,{message:'main'}),{echo:'main'});
    await sdk.evaluate(`(()=>{window.open('/webmcp-fixture','_blank');return true})()`);
    let popup;
    for(let i=0;i<100;i++) {
      popup=scope.tabs.list().find(item=>item.id!==tab.id && item.url?.includes('/webmcp-fixture'));
      if(popup)break;
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    assert.ok(popup);
    const popupWeb=await client.browser().tab(popup.id).capabilities.get('webmcp');
    const popupTool=(await popupWeb.listTools()).find(item=>item.name==='fixture_echo');
    assert.ok(popupTool);assert.deepEqual(await popupWeb.invokeTool(popupTool,{message:'popup'}),{echo:'popup'});
    client.close();
    console.log(JSON.stringify({passed:true,platform:process.platform,electron:process.versions.electron}));
  } finally {await runtime.dispose();await fixture.close();rmSync(root,{recursive:true,force:true});}
  app.exit(0);
}).catch(error=>{console.error(error);app.exit(1);});
