import assert from 'node:assert/strict';
import { createConnection } from 'node:net';
import { once } from 'node:events';
import { frame } from '../../packages/open-browser-use-electron/dist/wire.js';
import { cursorBitmap } from '../../packages/open-browser-use-electron/dist/cursor.generated.js';
import { connectExampleMcp } from './mcp.mjs';
import { OpenBrowserUseBrowser, OpenBrowserUseClient } from '../../packages/open-browser-use-js/dist/index.js';

export async function runSmoke({ runtime, scope, fixture, surface, window, launch, launchMcp, launchRepl, present, savePage }) {
  const checks = [];
  const check = message => { checks.push(message); console.log(`IAB smoke: ${message}`); };
  const a = await scope.tabs.create({ url: `${fixture.url}/login` });
  const b = await scope.tabs.create({ url: `${fixture.url}/second` });
  assert.notEqual(a.id,b.id); assert.equal(scope.tabs.list().length,2);
  check('same session: independent tabs');
  const evaluate = async (id, expression) => {
    const result = await scope.call('executeCdp', { target:{tabId:id}, method:'Runtime.evaluate', commandParams:{expression,returnByValue:true,awaitPromise:true} });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  assert.match(await evaluate(b.id,'document.cookie'), /iab_example=logged-in/); check('named profile: shared login cookie');
  present(b.id);
  await scope.call('executeCdp', { target:{tabId:a.id}, method:'Runtime.evaluate', commandParams:{expression:'document.querySelector("#message").focus()'} });
  await scope.call('executeCdp', { target:{tabId:a.id}, method:'Input.insertText', commandParams:{text:'typed in hidden tab'} });
  assert.equal(await evaluate(a.id,'document.querySelector("#message").value'),'typed in hidden tab');
  assert.equal(await evaluate(a.id,'window.trustedInput'),true); check('CDP input: hidden tab, trusted input event');
  const point = await evaluate(a.id,'(()=>{const r=document.querySelector("#increment").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');
  for (const type of ['mouseMoved','mousePressed','mouseReleased']) await scope.call('executeCdp', {
    target:{tabId:a.id}, method:'Input.dispatchMouseEvent', commandParams:{type,...point,button:type==='mouseMoved'?'none':'left',buttons:type==='mousePressed'?1:0,clickCount:type==='mouseMoved'?0:1},
  });
  const clickDeadline = Date.now()+1000;
  while (await evaluate(a.id,'document.querySelector("#count").textContent')==='0' && Date.now()<clickDeadline) await new Promise(r=>setTimeout(r,20));
  assert.equal(await evaluate(a.id,'document.querySelector("#count").textContent'),'1');
  assert.equal(await evaluate(a.id,'window.trustedClick'),true); check('CDP mouse: hidden tab, trusted click event');
  const sdkClient = new OpenBrowserUseClient({ socketPath:'scope-adapter' });
  sdkClient.request = (method, params = {}) => scope.call(method, params);
  sdkClient.onNotification = handler => runtime.subscribe(event => { if (event.scopeId === scope.id) handler({method:event.method,params:event.params}); });
  const sdkTab = new OpenBrowserUseBrowser({ client:sdkClient }).tab(a.id);
  assert.equal((await sdkTab.browser.tabs.getByUrl(`${fixture.url}/login`)).id,a.id);
  await assert.rejects(sdkTab.browser.tabs.getByUrl(`${fixture.url}/absent`),/No session tab/);

  assert.equal(await sdkTab.playwright.getByRole('heading',{name:'login',exact:true}).count(),1);
  await evaluate(a.id,`(()=>{const root=document.createElement('div');root.id='bulk-text-test';root.innerHTML='<button title="  Helpful   Action  " aria-label="Bulk first">Alpha<span title="Nested Tip"></span><span hidden> concealed</span></button><button title="Another Action" aria-label="Bulk second">Beta</button>';document.body.append(root)})()`);
  const cssBulk=sdkTab.playwright.locator('#bulk-text-test button'),roleBulk=sdkTab.playwright.getByRole('button',{name:/^Bulk /});
  for (const locator of [cssBulk,roleBulk]) {
    assert.deepEqual(await locator.allInnerTexts(),['Alpha','Beta']);
    assert.deepEqual(await locator.allTextContents(),['Alpha concealed','Beta']);
  }
  assert.equal(await sdkTab.playwright.getByTitle('helpful action',{exact:true}).count(),0);
  assert.equal(await sdkTab.playwright.getByTitle('Helpful Action',{exact:true}).count(),1);
  assert.equal(await sdkTab.playwright.getByTitle('action').count(),2);
  assert.equal(await sdkTab.playwright.locator('#bulk-text-test').getByTitle(/^Another/i).count(),1);
  assert.equal(await sdkTab.playwright.getByRole('button',{name:'Bulk first'}).getByTitle('Nested Tip',{exact:true}).count(),1);
  const unicodeId='save 😀 "\\ path';
  await evaluate(a.id,`document.querySelector('#bulk-text-test button').setAttribute('data-testid',${JSON.stringify(unicodeId)})`);
  assert.equal(await sdkTab.playwright.getByTestId(unicodeId).count(),1);
  assert.equal(await sdkTab.playwright.locator('#bulk-text-test').getByTestId(unicodeId).count(),1);
  assert.throws(()=>sdkTab.playwright.getByTestId('bad\uD800'),/Invalid test id/);
  const changingTitle=sdkTab.playwright.getByTitle('Helpful Action',{exact:true});
  await evaluate(a.id,"document.querySelector('#bulk-text-test button').title='Updated title'");
  assert.equal(await changingTitle.count(),0);
  assert.equal(await sdkTab.playwright.getByTitle('Updated title',{exact:true}).count(),1);
  await evaluate(a.id,`document.querySelector('#bulk-text-test').insertAdjacentHTML('beforeend','<svg id="svg-title" viewBox="0 0 10 10"><title>Helpful Icon</title><rect width="10" height="10"><title>Inner Shape</title></rect></svg>')`);
  await evaluate(a.id,"document.querySelector('#svg-title').insertAdjacentHTML('beforeend','<path></path>'.repeat(1100))");
  assert.equal(await sdkTab.playwright.getByTitle('Helpful Icon',{exact:true}).count(),1);
  assert.equal(await sdkTab.playwright.locator('#bulk-text-test').getByTitle(/inner shape/i).count(),1);
  assert.equal(await sdkTab.playwright.getByTitle('Helpful Icon',{exact:true}).getAttribute('id'),'svg-title');
  const cssFirst=cssBulk.first(),roleFirst=roleBulk.first();
  for (const locator of [cssFirst,roleFirst]) { await locator.waitFor({state:'visible',timeoutMs:1000});assert.equal(await locator.isHidden(),false);assert.equal(await locator.isDisabled(),false); }
  await evaluate(a.id,"document.querySelector('#bulk-text-test button').disabled=true");
  for (const locator of [cssFirst,roleFirst]) assert.equal(await locator.isDisabled(),true);
  await evaluate(a.id,`document.querySelector('#bulk-text-test').insertAdjacentHTML('beforeend','<input id="editable-test" aria-label="Native editable"><select id="editable-select"><option>One</option></select><div id="editable-custom" role="textbox" aria-label="Custom editable" contenteditable="true"></div>')`);
  const nativeEditable=sdkTab.playwright.getByRole('textbox',{name:'Native editable'}),cssEditable=sdkTab.playwright.locator('#editable-test'),customEditable=sdkTab.playwright.getByRole('textbox',{name:'Custom editable'});
  for (const locator of [nativeEditable,cssEditable,customEditable,sdkTab.playwright.locator('#editable-select')]) assert.equal(await locator.isEditable(),true);
  await evaluate(a.id,"document.querySelector('#editable-test').readOnly=true;document.querySelector('#editable-custom').setAttribute('aria-readonly','true');document.querySelector('#editable-select').disabled=true");
  for (const locator of [nativeEditable,cssEditable,customEditable,sdkTab.playwright.locator('#editable-select')]) assert.equal(await locator.isEditable(),false);
  await assert.rejects(cssFirst.isEditable(),/does not support editable state/);
  await evaluate(a.id,`document.querySelector('#bulk-text-test').insertAdjacentHTML('beforeend','<table role="grid"><tbody><tr><td id="implicit-gridcell" aria-readonly="true">Cell</td></tr></tbody></table>')`);
  const gridCell=sdkTab.playwright.locator('#implicit-gridcell');assert.equal(await gridCell.isEditable(),false);
  await evaluate(a.id,"document.querySelector('#implicit-gridcell').setAttribute('aria-readonly','false')");assert.equal(await gridCell.isEditable(),true);

  await evaluate(a.id,`(()=>{const host=document.createElement('div');host.id='editable-shadow-host';document.querySelector('#bulk-text-test').append(host);host.attachShadow({mode:'open'}).innerHTML='<fieldset disabled><input aria-label="Shadow disabled"></fieldset>'})()`);
  assert.equal(await sdkTab.playwright.locator('#editable-shadow-host').locator('input').isEditable(),false);
  assert.equal(await sdkTab.playwright.getByRole('textbox',{name:'Shadow disabled'}).isEditable(),false);
  await evaluate(a.id,"(()=>{Object.defineProperty(HTMLInputElement.prototype,'hasAttribute',{configurable:true,value:()=>false});return true})()");
  try {assert.equal(await cssEditable.isEditable(),false);assert.equal(await nativeEditable.isEditable(),false);}
  finally {await evaluate(a.id,'delete HTMLInputElement.prototype.hasAttribute');}

  await evaluate(a.id,"document.querySelector('#bulk-text-test').replaceChildren()");
  assert.deepEqual(await cssBulk.allInnerTexts(),[]);assert.deepEqual(await roleBulk.allInnerTexts(),[]);
  for (const locator of [cssFirst,roleFirst]) { await locator.waitFor({state:'hidden',timeoutMs:1000});assert.equal(await locator.isHidden(),true); }
  await evaluate(a.id,"document.querySelector('#bulk-text-test').remove()");
  check('SDK locators: bulk inner text, hidden descendants and empty matches');

  const observation = await sdkTab.observe();
  const increment = observation.nodes.find(node => node.role === 'button' && node.name === '加 1');
  assert.ok(increment);
  await sdkTab.click(increment.index, observation.snapshotId);
  assert.equal(await evaluate(a.id,'document.querySelector("#count").textContent'),'2');
  assert.equal(await evaluate(a.id,'window.trustedClick'),true);
  await assert.rejects(sdkTab.click(increment.index, observation.snapshotId), /stale/);
  const changedState = await sdkTab.observe({diff:true});
  assert.equal(changedState.textMode,'diff');
  assert.match(changedState.text, /\+ .*"2"/);
  check('SDK observation: indexed trusted click and stale snapshot rejection');
  await evaluate(a.id,`(()=>{window.semanticIsolationClicks=0;const button=document.createElement('button');button.id='semantic-isolation-button';button.textContent='Isolation action';button.onclick=e=>{if(e.isTrusted)window.semanticIsolationClicks++};const input=document.createElement('input');input.id='semantic-isolation-input';input.setAttribute('aria-label','Isolation field');document.body.append(button,input);window.savedSemanticConnected=Object.getOwnPropertyDescriptor(Node.prototype,'isConnected');Object.defineProperty(Node.prototype,'isConnected',{configurable:true,get:()=>false});return true})()`);
  try {
    const isolatedState=await sdkTab.observe(),isolatedButton=isolatedState.nodes.find(node=>node.name==='Isolation action');assert.ok(isolatedButton);await sdkTab.click(isolatedButton.index,isolatedState.snapshotId);
    await sdkTab.playwright.getByRole('textbox',{name:'Isolation field',exact:true}).fill('safe');
    assert.equal(await evaluate(a.id,'window.semanticIsolationClicks'),1);assert.equal(await evaluate(a.id,"document.querySelector('#semantic-isolation-input').value"),'safe');
  } finally {await evaluate(a.id,`(()=>{Object.defineProperty(Node.prototype,'isConnected',window.savedSemanticConnected);document.querySelector('#semantic-isolation-button').remove();document.querySelector('#semantic-isolation-input').remove();return true})()`);}
  check('SDK semantic input: isolated from page DOM prototype changes');
  await evaluate(a.id,`(()=>{const scope=document.createElement('div');scope.id='scope-isolation-root';scope.setAttribute('role','group');scope.setAttribute('aria-label','Isolation group');scope.innerHTML='<span>Inside word</span>';const outside=document.createElement('button');outside.id='scope-isolation-outside';outside.textContent='Outside word';document.body.append(scope,outside);window.savedParent=Object.getOwnPropertyDescriptor(Node.prototype,'parentNode');Object.defineProperty(Node.prototype,'parentNode',{configurable:true,get(){if(this.id==='scope-isolation-outside' || (this.nodeType===3 && this.nodeValue==='Outside word'))return scope;return window.savedParent.get.call(this)}});return true})()`);
  try {
    const scoped=sdkTab.playwright.getByRole('group',{name:'Isolation group',exact:true});
    assert.equal(await scoped.getByRole('button',{name:'Outside word',exact:true}).count(),0);
    assert.equal(await scoped.filter({hasText:'Outside word'}).count(),0);
    assert.equal(await scoped.filter({hasText:'Inside word'}).count(),1);
  } finally {await evaluate(a.id,`(()=>{Object.defineProperty(Node.prototype,'parentNode',window.savedParent);document.querySelector('#scope-isolation-root').remove();document.querySelector('#scope-isolation-outside').remove();return true})()`);}
  check('SDK semantic scope: isolated from forged parent relationships');
  await evaluate(a.id,`(()=>{const p=document.createElement('input');p.id='isolated-password';p.type='password';p.setAttribute('aria-label','Isolated password');p.value='private-fixture-value';document.body.append(p);window.savedInputType=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'type');Object.defineProperty(HTMLInputElement.prototype,'type',{configurable:true,get:()=> 'text'});return true})()`);
  try {const values=await sdkTab.observe({includeValues:true,includeFrames:true});const password=values.nodes.find(node=>node.name==='Isolated password');assert.ok(password);assert.equal(password.valueRedacted,true);assert.doesNotMatch(JSON.stringify(values),/private-fixture-value/);}
  finally {await evaluate(a.id,`(()=>{Object.defineProperty(HTMLInputElement.prototype,'type',window.savedInputType);document.querySelector('#isolated-password').remove();return true})()`);}
  check('SDK observation: password redaction resists page prototype changes');



  await evaluate(a.id,'document.querySelector("#message").value = ""');
  const textState = await sdkTab.observe();
  const message = textState.nodes.find(node => node.role === 'textbox' && node.name === '消息');
  assert.ok(message);
  await sdkTab.typeText(message.index, textState.snapshotId, 'SDK input');
  assert.equal(await evaluate(a.id,'document.querySelector("#message").value'),'SDK input');
  assert.equal(await evaluate(a.id,'window.trustedInput'),true);
  check('SDK observation: indexed trusted text input');
  const messageCss=sdkTab.playwright.locator('#message'),messageRole=sdkTab.playwright.getByRole('textbox',{name:'消息',exact:true});
  await evaluate(a.id,`(()=>{window.focusProbe={clicks:0,keys:0};const el=document.querySelector('#message');el.addEventListener('click',()=>window.focusProbe.clicks++);el.addEventListener('keydown',()=>window.focusProbe.keys++)})()`);
  for (const locator of [messageCss,messageRole]) { await evaluate(a.id,"document.querySelector('#increment').focus()");await locator.focus({timeoutMs:3000});assert.equal(await evaluate(a.id,"document.activeElement.id"),'message'); }
  assert.deepEqual(await evaluate(a.id,'window.focusProbe'),{clicks:0,keys:0});
  await evaluate(a.id,`(()=>{window.savedConnected=Object.getOwnPropertyDescriptor(Node.prototype,'isConnected');Object.defineProperty(Node.prototype,'isConnected',{configurable:true,get:()=>false});return true})()`);
  try {await messageRole.focus();assert.equal(await evaluate(a.id,"document.activeElement.id"),'message');assert.equal(await messageRole.isVisible(),true);assert.equal(await messageRole.isEnabled(),true);assert.equal(await messageRole.getAttribute('id'),'message');}
  finally {await evaluate(a.id,"Object.defineProperty(Node.prototype,'isConnected',window.savedConnected);true");}

  check('SDK locators: focus without mouse or key events');

  await evaluate(a.id,`(()=>{const input=document.createElement('textarea');input.id='selection-field';input.setAttribute('aria-label','Selection field');input.value='red one, blue one';const rich=document.createElement('div');rich.id='selection-rich';rich.contentEditable='true';rich.setAttribute('role','textbox');rich.setAttribute('aria-label','Rich selection');rich.innerHTML='alpha <b>bravo</b> charlie';document.body.append(input,rich)})()`);
  async function selectionTarget(name){const state=await sdkTab.observe();const node=state.nodes.find(item=>item.name===name && item.role==='textbox');assert.ok(node);return [node.index,state.snapshotId];}
  await sdkTab.selectText(...await selectionTarget('Selection field'),'one',{prefix:'blue '});
  assert.deepEqual(await evaluate(a.id,`(()=>{const e=document.querySelector('#selection-field');return [e.selectionStart,e.selectionEnd,e.value.slice(e.selectionStart,e.selectionEnd)]})()`),[14,17,'one']);
  await sdkTab.typeAtFocus('two');assert.equal(await evaluate(a.id,"document.querySelector('#selection-field').value"),'red one, blue two');
  await evaluate(a.id,"document.querySelector('#selection-field').value='red one, blue one'");
  await sdkTab.selectText(...await selectionTarget('Selection field'),'one',{prefix:'red ',selectionType:'cursor_after'});
  assert.deepEqual(await evaluate(a.id,`(()=>{const e=document.querySelector('#selection-field');return [e.selectionStart,e.selectionEnd]})()`),[7,7]);
  await assert.rejects(sdkTab.selectText(...await selectionTarget('Selection field'),'one'),/ambiguous/);
  await sdkTab.selectText(...await selectionTarget('Rich selection'),'alpha bravo',{suffix:' charlie'});
  assert.equal(await evaluate(a.id,'document.getSelection().toString()'),'alpha bravo');
  await evaluate(a.id,"document.querySelector('#selection-rich').setAttribute('aria-readonly','true')");
  await assert.rejects(sdkTab.selectText(...await selectionTarget('Rich selection'),'bravo'),/disabled|readonly/);
  await evaluate(a.id,"document.querySelector('#selection-rich').removeAttribute('aria-readonly')");
  await evaluate(a.id,`(()=>{const host=document.createElement('div');host.id='selection-shadow-host';const shadow=host.attachShadow({mode:'open'});shadow.innerHTML='<div contenteditable="true" role="textbox" aria-label="Shadow selection">shadow <b>bravo</b> text</div>';document.body.append(host)})()`);
  await sdkTab.selectText(...await selectionTarget('Shadow selection'),'shadow bravo');
  assert.equal(await evaluate(a.id,`document.querySelector('#selection-shadow-host').shadowRoot.getSelection().toString()`),'shadow bravo');
  await evaluate(a.id,"document.querySelector('#selection-shadow-host').remove()");
  await evaluate(a.id,"document.querySelector('#selection-field').remove();document.querySelector('#selection-rich').remove()");
  check('SDK indexed text selection: context, caret, ambiguity and rich text');
  await evaluate(a.id,"document.querySelector('#increment').focus()");
  const originalCdpCall=sdkTab.browser.cdp.call.bind(sdkTab.browser.cdp);let unblockResolve,focusDispatches=0;
  sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='DOM.resolveNode' && !unblockResolve)await new Promise(resolve=>{unblockResolve=resolve});if(args[1]==='DOM.focus')focusDispatches++;return originalCdpCall(...args);};
  try {
    await assert.rejects(messageCss.focus({timeoutMs:500}),/preparation timed out/i);assert.ok(unblockResolve);unblockResolve();await new Promise(resolve=>setTimeout(resolve,250));
    assert.equal(focusDispatches,0);assert.equal(await evaluate(a.id,'document.activeElement.id'),'increment');
  } finally {unblockResolve?.();sdkTab.browser.cdp.call=originalCdpCall;}
  let unblockFocus,issuedFocuses=0;
  sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='DOM.focus'){issuedFocuses++;const result=await originalCdpCall(...args);await new Promise(resolve=>{unblockFocus=resolve});return result;}return originalCdpCall(...args);};
  try {
    await assert.rejects(messageCss.focus({timeoutMs:1000}),/outcome is unknown/i);assert.ok(unblockFocus);assert.equal(await evaluate(a.id,'document.activeElement.id'),'message');unblockFocus();await new Promise(resolve=>setTimeout(resolve,100));assert.equal(issuedFocuses,1);
  } finally {unblockFocus?.();sdkTab.browser.cdp.call=originalCdpCall;}
  check('SDK focus deadline: no late dispatch and unknown issued outcome');

  await evaluate(a.id,`(()=>{window.deadlineClicks=0;const el=document.createElement('button');el.id='deadline-click';el.textContent='Deadline click';el.onclick=()=>window.deadlineClicks++;document.body.append(el)})()`);
  let unblockClickPrepare,clickPresses=0;
  sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='DOM.resolveNode' && !unblockClickPrepare)await new Promise(resolve=>{unblockClickPrepare=resolve});if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mousePressed')clickPresses++;return originalCdpCall(...args);};
  try {
    await assert.rejects(sdkTab.playwright.locator('#deadline-click').click({timeoutMs:500}),/preparation timed out/i);unblockClickPrepare();await new Promise(resolve=>setTimeout(resolve,250));assert.equal(clickPresses,0);assert.equal(await evaluate(a.id,'window.deadlineClicks'),0);
  } finally {unblockClickPrepare?.();sdkTab.browser.cdp.call=originalCdpCall;}
  let unblockPress,presses=0,releases=0;
  sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mousePressed'){presses++;const result=await originalCdpCall(...args);await new Promise(resolve=>{unblockPress=resolve});return result;}if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mouseReleased')releases++;return originalCdpCall(...args);};
  try {
    await assert.rejects(sdkTab.playwright.locator('#deadline-click').click({timeoutMs:1000}),/outcome is unknown/i);assert.ok(unblockPress);unblockPress();await new Promise(resolve=>setTimeout(resolve,200));assert.equal(presses,1);assert.equal(releases,1);assert.equal(await evaluate(a.id,'window.deadlineClicks'),1);
  } finally {unblockPress?.();sdkTab.browser.cdp.call=originalCdpCall;await evaluate(a.id,"document.querySelector('#deadline-click').remove()");}
  check('SDK click deadline: no late press and release after an issued press');

  await evaluate(a.id,`(()=>{window.doubleDeadlineClicks=0;const el=document.createElement('button');el.id='double-deadline';el.textContent='Double deadline';el.onclick=()=>window.doubleDeadlineClicks++;document.body.append(el)})()`);
  for (const locator of [sdkTab.playwright.locator('#double-deadline'),sdkTab.playwright.getByRole('button',{name:'Double deadline',exact:true})]) {
    let unblockFirstRelease,pressed=0;
    sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mousePressed')pressed++;if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mouseReleased' && args[2].clickCount===1){const result=await originalCdpCall(...args);await new Promise(resolve=>{unblockFirstRelease=resolve});return result;}return originalCdpCall(...args);};
    try {
      const before=await evaluate(a.id,'window.doubleDeadlineClicks');await assert.rejects(locator.dblclick({timeoutMs:1000}),/outcome is unknown/i);assert.ok(unblockFirstRelease);unblockFirstRelease();await new Promise(resolve=>setTimeout(resolve,250));assert.equal(pressed,1);assert.equal(await evaluate(a.id,'window.doubleDeadlineClicks'),before+1);
    } finally {unblockFirstRelease?.();sdkTab.browser.cdp.call=originalCdpCall;}
  }
  await evaluate(a.id,"document.querySelector('#double-deadline').remove()");
  check('SDK double click deadline: no second press after timeout');

  await evaluate(a.id,`(()=>{const el=document.createElement('button');el.id='hover-deadline';el.textContent='Hover deadline';document.body.append(el)})()`);
  for (const locator of [sdkTab.playwright.locator('#hover-deadline'),sdkTab.playwright.getByRole('button',{name:'Hover deadline',exact:true})]) {
    let unblockPrepare,moves=0;
    sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='DOM.resolveNode' && !unblockPrepare)await new Promise(resolve=>{unblockPrepare=resolve});if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mouseMoved')moves++;return originalCdpCall(...args);};
    try {await assert.rejects(locator.hover({timeoutMs:500}),/timed out/i);assert.ok(unblockPrepare);unblockPrepare();await new Promise(resolve=>setTimeout(resolve,250));assert.equal(moves,0);}
    finally {unblockPrepare?.();sdkTab.browser.cdp.call=originalCdpCall;}
    let unblockMove,issued=0;
    sdkTab.browser.cdp.call=async (...args)=>{if(args[1]==='Input.dispatchMouseEvent' && args[2].type==='mouseMoved'){issued++;const result=await originalCdpCall(...args);await new Promise(resolve=>{unblockMove=resolve});return result;}return originalCdpCall(...args);};
    try {await assert.rejects(locator.hover({timeoutMs:1000}),/outcome is unknown/i);assert.ok(unblockMove);unblockMove();await new Promise(resolve=>setTimeout(resolve,100));assert.equal(issued,1);}
    finally {unblockMove?.();sdkTab.browser.cdp.call=originalCdpCall;}
  }
  await evaluate(a.id,"document.querySelector('#hover-deadline').remove()");
  check('SDK hover deadline: no late movement and unknown issued outcome');

  await evaluate(a.id,`(()=>{window.focusChanges=0;const el=document.createElement('input');el.id='focus-changing';el.addEventListener('focus',()=>{window.focusChanges++;el.id='focus-changed'});document.body.append(el)})()`);
  await assert.rejects(sdkTab.playwright.locator('#focus-changing').focus({timeoutMs:1000}),/changed|focus/i);
  assert.equal(await evaluate(a.id,'window.focusChanges'),1);await evaluate(a.id,"document.querySelector('#focus-changed').remove()");
  await evaluate(a.id,`(()=>{window.roleFocusChanges=0;const el=document.createElement('input');el.id='role-focus-changing';el.setAttribute('aria-label','Focus original');el.addEventListener('focus',()=>{window.roleFocusChanges++;el.setAttribute('aria-label','Focus changed')});document.body.append(el)})()`);
  await assert.rejects(sdkTab.playwright.getByRole('textbox',{name:'Focus original',exact:true}).focus({timeoutMs:1000}),/changed|focus/i);
  assert.equal(await evaluate(a.id,'window.roleFocusChanges'),1);await evaluate(a.id,"document.querySelector('#role-focus-changing').remove()");



  for (const locator of [messageCss,messageRole]) { await evaluate(a.id,'window.trustedInput=false');await locator.clear({timeoutMs:3000});assert.equal(await evaluate(a.id,'document.querySelector("#message").value'),'');assert.equal(await evaluate(a.id,'window.trustedInput'),true);await locator.fill('SDK input'); }
  assert.equal(await evaluate(a.id,'window.trustedInput'),true);
  check('SDK locators: CSS and semantic clear preserve trusted input');

  await evaluate(a.id,'document.querySelector("#message").addEventListener("keydown", e => window.sdkKey = {key:e.key, trusted:e.isTrusted})');
  await sdkTab.pressKey('Enter');
  assert.deepEqual(await evaluate(a.id,'window.sdkKey'), {key:'Enter', trusted:true});
  await sdkTab.pressKey('ControlOrMeta+A');
  assert.deepEqual(await evaluate(a.id,'({start:document.querySelector("#message").selectionStart,end:document.querySelector("#message").selectionEnd})'), {start:0,end:9});
  check('SDK keyboard: trusted Enter and select all');
  await evaluate(a.id,'(async()=>{const f=document.createElement("iframe");f.id="frame-test";f.srcdoc="<button onclick=\\"window.frameTrusted=event.isTrusted\\">Frame action</button>";document.body.append(f);await new Promise(resolve=>f.onload=resolve)})()');
  const frameState = await sdkTab.observe({includeFrames:true});
  const frameButton = frameState.nodes.find(node=>node.name==='Frame action');
  assert.ok(frameButton?.frameId);
  await sdkTab.click(frameButton.index,frameState.snapshotId);
  assert.equal(await evaluate(a.id,'document.querySelector("#frame-test").contentWindow.frameTrusted'),true);
  await evaluate(a.id,"document.querySelector('#frame-test').contentDocument.querySelector('button').title='Frame Help'");
  assert.equal(await sdkTab.playwright.frameLocator('#frame-test').getByTitle(/frame help/i).count(),1);
  const beforeReplace=await sdkTab.observe({includeFrames:true}),oldFrameButton=beforeReplace.nodes.find(node=>node.name==='Frame action');assert.ok(oldFrameButton);
  await evaluate(a.id,`(async()=>{const old=document.querySelector('#frame-test'),f=document.createElement('iframe');f.id='frame-test';f.srcdoc='<button title="Frame Help" onclick="window.frameTrusted=event.isTrusted">Frame action</button>';await new Promise(resolve=>{f.onload=resolve;old.replaceWith(f)})})()`);
  await assert.rejects(sdkTab.click(oldFrameButton.index,beforeReplace.snapshotId),/stale|changed|frame/i);
  await sdkTab.playwright.frameLocator('#frame-test').getByTitle('Frame Help',{exact:true}).click();
  assert.equal(await evaluate(a.id,'document.querySelector("#frame-test").contentWindow.frameTrusted'),true);
  await evaluate(a.id,'document.querySelector("#frame-test").remove()');
  check('SDK frame observation: indexed trusted click');
  await evaluate(a.id,`setTimeout(()=>{const b=document.createElement('button');b.id='delayed-sdk';b.textContent='Delayed SDK';b.onclick=e=>window.delayedSdkTrusted=e.isTrusted;document.body.prepend(b)},250)`);
  await sdkTab.playwright.getByRole('button',{name:'Delayed SDK',exact:true}).click({timeoutMs:3000});
  assert.equal(await evaluate(a.id,'window.delayedSdkTrusted'),true);
  await evaluate(a.id,`(()=>{window.delayedSdkTrusted=false;const r=document.querySelector('#delayed-sdk').getBoundingClientRect(),cover=document.createElement('div');Object.assign(cover.style,{position:'fixed',left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px',zIndex:'9999'});document.body.append(cover);setTimeout(()=>cover.remove(),250)})()`);
  await sdkTab.playwright.getByRole('button',{name:'Delayed SDK',exact:true}).click({timeoutMs:3000});
  assert.equal(await evaluate(a.id,'window.delayedSdkTrusted'),true);
  await evaluate(a.id,'document.querySelector("#delayed-sdk").remove()');
  check('SDK locator: waits for delayed target and sends trusted click');
  await evaluate(a.id,`(()=>{window.movingSdk=true;const b=document.createElement('button');b.id='moving-sdk';b.textContent='Moving SDK';Object.assign(b.style,{position:'fixed',top:'10px',left:'10px',zIndex:'1000'});b.onclick=e=>window.movingSdkClick={trusted:e.isTrusted,moving:window.movingSdk};document.body.append(b)})()`);
  const movement=(async()=>{for(let n=1;n<=12;n++){await evaluate(a.id,`document.querySelector('#moving-sdk').style.left='${10+8*n}px'`);await new Promise(resolve=>setTimeout(resolve,30));}await evaluate(a.id,'window.movingSdk=false')})();
  await sdkTab.playwright.getByRole('button',{name:'Moving SDK',exact:true}).click({timeoutMs:5000});await movement;
  assert.deepEqual(await evaluate(a.id,'window.movingSdkClick'),{trusted:true,moving:false});await evaluate(a.id,'document.querySelector("#moving-sdk").remove()');
  check('SDK locator: waits for moving target to settle');
  const crossUrl = fixture.url.replace('127.0.0.1','localhost') + '/cross-frame';
  await evaluate(a.id,`(async()=>{window.crossMessages=[];window.addEventListener('message',e=>window.crossMessages.push(e.data));const f=document.createElement('iframe');f.id='cross-frame';f.src=${JSON.stringify(crossUrl)};document.body.append(f);await new Promise(resolve=>f.onload=resolve)})()`);
  await evaluate(a.id,`(()=>{window.savedFrameRoot=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'getRootNode');HTMLIFrameElement.prototype.getRootNode=()=>({activeElement:null});return true})()`);
  try {await sdkTab.playwright.locator('#cross-frame').focus();assert.equal(await evaluate(a.id,"document.activeElement.id"),'cross-frame');}
  finally {await evaluate(a.id,"if(window.savedFrameRoot)Object.defineProperty(HTMLIFrameElement.prototype,'getRootNode',window.savedFrameRoot);else delete HTMLIFrameElement.prototype.getRootNode;true");}
  const coveredFrameState=await sdkTab.observe({includeFrames:true}),coveredFrameButton=coveredFrameState.nodes.find(node=>node.name==='Cross-frame action');assert.ok(coveredFrameButton);
  await evaluate(a.id,`(()=>{const frame=document.querySelector('#cross-frame'),r=frame.getBoundingClientRect(),cover=document.createElement('div');cover.id='cross-cover';Object.assign(cover.style,{position:'fixed',left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px',zIndex:'99999'});document.body.append(cover);window.savedPoint=Object.getOwnPropertyDescriptor(Document.prototype,'elementFromPoint');Document.prototype.elementFromPoint=()=>frame;return true})()`);
  try {await assert.rejects(sdkTab.click(coveredFrameButton.index,coveredFrameState.snapshotId),/covered|hidden|frame/i);assert.equal(await evaluate(a.id,'window.crossMessages.length'),0);}
  finally {await evaluate(a.id,`(()=>{Object.defineProperty(Document.prototype,'elementFromPoint',window.savedPoint);document.querySelector('#cross-cover').remove();return true})()`);}
  const crossState = await sdkTab.observe({includeFrames:true});
  assert.equal(crossState.frameCoverage,'cross-process');
  const crossButton = crossState.nodes.find(node=>node.name==='Cross-frame action');assert.ok(crossButton?.frameId);
  await sdkTab.click(crossButton.index,crossState.snapshotId);
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-click',trusted:true});
  const crossTextCount=await evaluate(a.id,'window.crossMessages.length');
  await sdkTab.playwright.getByText('Cross-frame action',{exact:true}).click();await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(await evaluate(a.id,'window.crossMessages.length'),crossTextCount+1);
  const crossSession=(await sdkTab.browser.cdp.frameSessions(a.id)).find(item=>item.frameId===crossButton.frameId)?.sessionId;assert.ok(crossSession);
  const localPoint=await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:`(()=>{const r=document.querySelector('button').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`,returnByValue:true},{sessionId:crossSession});
  const feedbackPoint=await evaluate(a.id,`(()=>{const f=document.querySelector('#cross-frame'),r=f.getBoundingClientRect(),p=document.querySelector('#obu-iab-visual-feedback');return {x:Number(p.dataset.x),y:Number(p.dataset.y),left:r.left+f.clientLeft,top:r.top+f.clientTop}})()`);
  assert.ok(Math.abs(feedbackPoint.x-feedbackPoint.left-localPoint.result.value.x)<1 && Math.abs(feedbackPoint.y-feedbackPoint.top-localPoint.result.value.y)<1);
  await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:`(()=>{const p=document.createElement('input');p.id='frame-password';p.type='password';p.setAttribute('aria-label','Frame password');p.value='frame-private-value';document.body.append(p);window.savedType=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'type');Object.defineProperty(HTMLInputElement.prototype,'type',{configurable:true,get:()=> 'text'});return true})()`,returnByValue:true},{sessionId:crossSession});
  try {const values=await sdkTab.observe({includeFrames:true,includeValues:true});const password=values.nodes.find(node=>node.name==='Frame password');assert.ok(password);assert.equal(password.valueRedacted,true);assert.doesNotMatch(JSON.stringify(values),/frame-private-value/);}
  finally {await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:`(()=>{Object.defineProperty(HTMLInputElement.prototype,'type',window.savedType);document.querySelector('#frame-password').remove();return true})()`,returnByValue:true},{sessionId:crossSession});}
  const frameInput=sdkTab.playwright.frameLocator('#cross-frame').getByRole('textbox',{name:'Cross-frame text'}),frameCss=sdkTab.playwright.frameLocator('#cross-frame').locator('input[aria-label="Cross-frame text"]');
  assert.equal(await frameInput.isEditable(),true);assert.equal(await frameCss.isEditable(),true);
  await evaluate(a.id,`(()=>{window.savedFrameRect=Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype,'getBoundingClientRect');HTMLIFrameElement.prototype.getBoundingClientRect=()=>({width:0,height:0});return true})()`);
  try {assert.equal(await frameInput.isVisible(),true);}
  finally {await evaluate(a.id,"if(window.savedFrameRect)Object.defineProperty(HTMLIFrameElement.prototype,'getBoundingClientRect',window.savedFrameRect);else delete HTMLIFrameElement.prototype.getBoundingClientRect;true");}

  await frameCss.focus();await frameInput.focus();

  await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:"document.querySelector('[aria-label=\"Cross-frame text\"]').readOnly=true",returnByValue:true},{sessionId:crossSession});
  assert.equal(await frameInput.isEditable(),false);assert.equal(await frameCss.isEditable(),false);
  await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:"document.querySelector('[aria-label=\"Cross-frame text\"]').readOnly=false",returnByValue:true},{sessionId:crossSession});
  const crossTextState=await sdkTab.observe({includeFrames:true});const crossText=crossTextState.nodes.find(node=>node.name==='Cross-frame text');assert.ok(crossText);
  await sdkTab.typeText(crossText.index,crossTextState.snapshotId,'hello');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-text',value:'hello',trusted:true});
  const selectFrameState=await sdkTab.observe({includeFrames:true});const selectFrame=selectFrameState.nodes.find(node=>node.name==='Cross-frame text');assert.ok(selectFrame);
  await sdkTab.selectText(selectFrame.index,selectFrameState.snapshotId,'ell');
  const selectionInFrame=await sdkTab.browser.cdp.call(a.id,'Runtime.evaluate',{expression:`(()=>{const e=document.querySelector('[aria-label="Cross-frame text"]');return [e.selectionStart,e.selectionEnd]})()`,returnByValue:true},{sessionId:crossSession});
  assert.deepEqual(selectionInFrame.result.value,[1,4]);
  await sdkTab.typeAtFocus('XYZ');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-text',value:'hXYZo',trusted:true});
  await frameCss.fill('hello');
  const valueState=await sdkTab.observe({includeFrames:true,includeValues:true});
  assert.equal(valueState.nodes.find(node=>node.name==='Cross-frame text').value,'hello');
  assert.equal(valueState.nodes.find(node=>node.name==='Cross secret').valueRedacted,true);
  assert.doesNotMatch(JSON.stringify(valueState),/fixture-private-123/);

  await sdkTab.playwright.getByPlaceholder('Type cross message',{exact:true}).fill('updated');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-text',value:'updated',trusted:true});
  const crossClearState=await sdkTab.observe({includeFrames:true});const crossClear=crossClearState.nodes.find(node=>node.name==='Cross-frame text');
  await sdkTab.fill(crossClear.index,crossClearState.snapshotId,'');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-text',value:'',trusted:true});
  const updates=sdkTab.playwright.getByLabel('Cross updates',{exact:true});await updates.check();await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-check',value:true,trusted:true});
  const checkCount=await evaluate(a.id,'window.crossMessages.length');await updates.check();await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(await evaluate(a.id,'window.crossMessages.length'),checkCount);
  await updates.uncheck();await new Promise(resolve=>setTimeout(resolve,100));assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-check',value:false,trusted:true});
  await sdkTab.playwright.getByPlaceholder('Amount',{exact:true}).fill('137.5');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-number',value:'137.5',trusted:true});
  const priorNumber=await evaluate(a.id,'window.crossMessages.length');await assert.rejects(sdkTab.playwright.getByLabel('Cross amount',{exact:true}).fill('invalid'),/Invalid number value/);assert.equal(await evaluate(a.id,'window.crossMessages.length'),priorNumber);
  await sdkTab.playwright.getByLabel('Cross date',{exact:true}).fill('2026-12-31');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'date-change',value:'2026-12-31',trusted:false});
  await sdkTab.playwright.getByLabel('Cross time',{exact:true}).fill('09:45');await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'time-change',value:'09:45',trusted:false});
  const colour=sdkTab.playwright.getByLabel('Cross colour',{exact:true});assert.deepEqual(await colour.selectOption({label:'Blue'}),['blue']);await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-select',values:['blue'],trusted:false});
  await assert.rejects(colour.selectOption('blocked',{timeoutMs:0}),/unavailable/);
  const choices=sdkTab.playwright.getByLabel('Cross choices',{exact:true});assert.deepEqual(await choices.selectOption(['red','green']),['red','green']);await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(await evaluate(a.id,'window.crossMessages.at(-1)'),{kind:'cross-multi',values:['red','green'],trusted:false});
  const staleCross=await sdkTab.observe({includeFrames:true});const staleCrossButton=staleCross.nodes.find(node=>node.name==='Cross-frame action');
  await evaluate(a.id,`(async()=>{const f=document.querySelector('#cross-frame');f.src=${JSON.stringify(crossUrl+'?changed')};await new Promise(resolve=>f.onload=resolve)})()`);
  await assert.rejects(sdkTab.click(staleCrossButton.index,staleCross.snapshotId),/Frame changed|Frame session|Frame sessions/);
  await evaluate(a.id,`(()=>{const r=document.querySelector('#cross-frame').getBoundingClientRect(),cover=document.createElement('div');cover.id='cross-cover';Object.assign(cover.style,{position:'fixed',left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px',zIndex:'9999'});document.body.append(cover)})()`);
  const coveredCross=await sdkTab.observe({includeFrames:true});const coveredCrossButton=coveredCross.nodes.find(node=>node.name==='Cross-frame action');assert.ok(coveredCrossButton);
  await assert.rejects(sdkTab.click(coveredCrossButton.index,coveredCross.snapshotId),/Frame is hidden/);
  await evaluate(a.id,'document.querySelector("#cross-cover").remove()');
  await evaluate(a.id,'document.querySelector("#cross-frame").remove()');
  check('SDK cross-process frame: trusted click and text');
  await evaluate(a.id,'document.body.insertAdjacentHTML("beforeend", "<input id=drag-test type=range value=10 style=\\"position:fixed;top:10px;left:10px;width:200px\\">"); document.querySelector("#drag-test").addEventListener("input",e=>window.sdkDragTrusted=e.isTrusted)');
  const drag = await evaluate(a.id,'(()=>{const r=document.querySelector("#drag-test").getBoundingClientRect();return {from:[r.left+r.width*.15,r.top+r.height/2],to:[r.left+r.width*.85,r.top+r.height/2]}})()');
  await sdkTab.drag(drag.from,drag.to);
  assert.ok(await evaluate(a.id,'Number(document.querySelector("#drag-test").value)')>50);
  assert.equal(await evaluate(a.id,'window.sdkDragTrusted'),true);
  await evaluate(a.id,'document.querySelector("#drag-test").remove()');
  check('SDK visual input: trusted drag');
  present(a.id);
  const visualPoint = await evaluate(a.id,'(()=>{const r=document.querySelector("#increment").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');
  await sdkTab.clickAt(visualPoint.x,visualPoint.y);
  const visualDeadline = Date.now()+2000;
  while (await evaluate(a.id,'document.querySelector("#count").textContent')==='2' && Date.now()<visualDeadline) await new Promise(r=>setTimeout(r,20));
  assert.equal(await evaluate(a.id,'document.querySelector("#count").textContent'),'3');
  check('SDK visual input: coordinate click');
  await evaluate(a.id, `document.body.style.height="3000px"; window.hiddenWheels=[]; window.addEventListener('wheel', e => window.hiddenWheels.push({trusted:e.isTrusted, delta:e.deltaY}))`);
  await sdkTab.scrollAt(visualPoint.x,visualPoint.y,0,250);
  assert.ok(await evaluate(a.id,'window.scrollY') > 0);
  assert.deepEqual(await evaluate(a.id,'window.hiddenWheels.at(-1)'), {trusted:true,delta:250});
  await evaluate(a.id,'window.scrollTo(0,0); document.body.style.height=""');
  check('SDK scroll: hidden window dispatches trusted wheel and remains usable');
  if (process.env.OBU_IAB_VISIBLE_SCROLL_SMOKE === '1') {
    window.showInactive();
    try {
      await evaluate(a.id,'document.body.style.height="3000px"');
      await sdkTab.getScreenshot();
      let timer;
      try {
        await Promise.race([sdkTab.scrollAt(visualPoint.x,visualPoint.y,0,250), new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('visible scroll timed out')),5000);})]);
      } finally { clearTimeout(timer); }
      const deadline = Date.now()+2000;
      while (await evaluate(a.id,'window.scrollY')===0 && Date.now()<deadline) await new Promise(r=>setTimeout(r,20));
      assert.ok(await evaluate(a.id,'window.scrollY')>0);
      await evaluate(a.id,'window.scrollTo(0,0); document.body.style.height=""');
      check('SDK scroll: visible host window');
    } finally { window.hide(); }
  }
  const other = runtime.scopes.open({ id:'other-task', profileId:'work' });
  await assert.rejects(other.call('executeCdp',{target:{tabId:a.id},method:'Runtime.evaluate'}));
  await assert.rejects(scope.call('executeCdp',{target:{tabId:a.id},method:'Browser.close'})); check('scope ownership and global CDP rejection');
  for (const mode of ['private','socket','cli-private','cli-socket']) {
    const before = scope.tabs.list().length; const result = await launch(mode);
    assert.equal(scope.tabs.list().length,before+1);
    assert.ok(mode.startsWith('cli') ? result.result.id : result.tabId); check(`${mode}: real process / RPC / page`);
  }
  // The MCP protocol uses stdin/stdout; browser bootstrap and RPC stay on FD 3
  // or the authenticated socket. Never bridge agent stdio to the private FD.
  for (const transport of ['private','socket']) {
    const mcp = await connectExampleMcp(await launchMcp(transport));
    let tabId;
    try {
      const tools = await mcp.request('tools/list');
      assert.ok(tools.tools.some(tool=>tool.name==='snapshot'));
      assert.ok(!tools.tools.some(tool=>tool.name==='user_tabs'));
      const opened = await mcp.callTool('open_tab',{url:`${fixture.url}/mcp-${transport}`});
      assert.equal(opened.isError,false); tabId = opened.structuredContent.id;
      const list = await mcp.callTool('tabs');
      assert.ok(list.structuredContent.result.some(tab=>tab.id===tabId));
      assert.equal((await mcp.callTool('tabs',{session_id:'other-task'})).isError,true);
      assert.equal((await mcp.callTool('page_info',{tab_id:a.id})).isError,false);
      assert.equal((await mcp.callTool('snapshot',{tab_id:tabId})).isError,false);
      const image = await mcp.callTool('screenshot',{tab_id:tabId});
      assert.equal(image.content[0].type,'image');
      assert.equal(Buffer.from(image.content[0].data,'base64').subarray(1,4).toString(),'PNG');
      assert.equal((await mcp.callTool('cdp',{tab_id:tabId,method:'Browser.close'})).isError,true);
      const foreign = await other.tabs.create();
      assert.equal((await mcp.callTool('snapshot',{tab_id:foreign.id})).isError,true);
      await other.tabs.close(foreign.id);
      const input = await evaluate(tabId,'(()=>{const r=document.querySelector("#message").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');
      assert.equal((await mcp.callTool('click',{tab_id:tabId,...input})).isError,false);
      assert.equal((await mcp.callTool('type_text',{tab_id:tabId,text:'Hello from MCP'})).isError,false);
      assert.equal(await evaluate(tabId,'document.querySelector("#message").value'),'Hello from MCP');
      assert.equal(await evaluate(tabId,'window.trustedInput'),true);
      const button = await evaluate(tabId,'(()=>{const r=document.querySelector("#increment").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');
      assert.equal((await mcp.callTool('click',{tab_id:tabId,...button})).isError,false);
      const deadline = Date.now()+2000;
      while (await evaluate(tabId,'document.querySelector("#count").textContent')==='0' && Date.now()<deadline) await new Promise(r=>setTimeout(r,20));
      assert.equal(await evaluate(tabId,'document.querySelector("#count").textContent'),'1');
      assert.equal(await evaluate(tabId,'window.trustedClick'),true);
    } finally { await mcp.close(); }
    assert.ok(scope.tabs.list().some(tab=>tab.id===tabId));
    check(`mcp-${transport}: stdio lifecycle, scoped tabs, image, trusted mouse/text, EOF retains pages`);
  }
  const restricted = await connectExampleMcp(await launchMcp('private',{operations:['tabs.read']}));
  try {
    assert.equal((await restricted.callTool('tabs')).isError,false);
    assert.equal((await restricted.callTool('open_tab')).isError,true);
    assert.equal((await restricted.callTool('snapshot',{tab_id:a.id})).isError,true);
    restricted.revoke();
    assert.equal((await restricted.callTool('tabs')).isError,true);
  } finally { await restricted.close(); }
  check('mcp: operation grants and revocation remain enforced by the IAB host');
  await evaluate(a.id,`(async()=>{const f=document.createElement('iframe');f.id='cross-repl';f.src=${JSON.stringify(crossUrl)};document.body.append(f);await new Promise(resolve=>f.onload=resolve)})()`);
  for (const transport of ['private','socket']) {
    const repl = await connectExampleMcp(await launchRepl(transport));
    try {
      const run = code => repl.callTool('js', {code});
      assert.equal((await run(`const inventory = await getBrowserState(); const browser = await connectBrowser({browserId:inventory.available[0].id}); const tab = browser.tab(${a.id})`)).isError, undefined);
      assert.equal((await run('nodeRepl.write((await getBrowserState()).sessions[0].tabs.some(item => item.id === tab.id))')).content[0].text,'true');
      if (process.env.OBU_IAB_MIXED_SMOKE === '1') {
        assert.equal((await run('await connectBrowser()')).isError,true);
        const mixed=await run('const chrome = await connectBrowser({browserId:inventory.available.find(item=>item.kind==="extension").id}); const chromeTab = await chrome.newTab(); nodeRepl.write((await getBrowserState()).sessions.some(item=>item.browserId!=="host" && item.tabs.some(t=>t.id===chromeTab.id)))');
        assert.equal(mixed.content[0].text,'true',JSON.stringify(mixed));
        assert.equal((await run('await chrome.client.finalizeTabs([])')).isError,undefined);
      }
      assert.equal((await run('nodeRepl.write((await tab.observe()).nodes.some(node => node.name === "加 1"))')).content[0].text, 'true');
      const messageCount = await evaluate(a.id,"window.crossMessages.filter(message=>message.kind==='cross-click').length");
      const cross = await run('const frameState = await tab.observe({includeFrames:true}); const frameButton = frameState.nodes.find(node => node.name === "Cross-frame action"); await tab.click(frameButton.index,frameState.snapshotId)');
      assert.equal(cross.isError,undefined,JSON.stringify(cross));
      await new Promise(resolve=>setTimeout(resolve,100));
      assert.equal(await evaluate(a.id,"window.crossMessages.filter(message=>message.kind==='cross-click').length"),messageCount+1);
      assert.deepEqual(await evaluate(a.id,"window.crossMessages.filter(message=>message.kind==='cross-click').at(-1)"),{kind:'cross-click',trusted:true});
      assert.equal((await run('nodeRepl.emitImage(await tab.getScreenshot())')).content[0].type, 'image');
      assert.equal((await run(`const tab = browser.tab(${a.id}); class Again {}\n(() => nodeRepl.write(tab.id))()`)).content[0].text,String(a.id));
      assert.equal((await repl.callTool('js_reset',{})).isError,undefined);
      assert.equal((await run('typeof tab')).content[0].text,"'undefined'");
      assert.equal((await run('const browser = await agent.browsers.get("iab"); nodeRepl.write((await browser.getTabs()).length > 0)')).content[0].text,'true');
      repl.revoke();
      assert.equal((await run('await browser.getTabs()')).isError, true);
    } catch (error) { await repl.close().catch(() => {}); throw error; }
    await repl.close();
    check(`repl-${transport}: scoped session, observation, image and revocation`);
  }
  await evaluate(a.id,'document.querySelector("#cross-repl").remove()');
  // CLI and worker processes have exited and their grants were revoked. This
  // unregistered process receives no browser response from the known endpoint.
  const endpoint = await runtime.connections.openSocket();
  const raw = createConnection(endpoint); let bytes = 0;
  raw.on('error',()=>{}); raw.on('data',data=>{bytes+=data.length});
  const closed = new Promise(resolve => raw.once('close',resolve));
  raw.once('connect',()=>raw.write(frame({jsonrpc:'2.0',id:'anonymous',method:'getInfo',params:{session_id:scope.id}})));
  await closed; assert.equal(bytes,0); check('anonymous known-path socket: rejected before RPC');
  present(a.id);
  await evaluate(a.id,'document.querySelector("#popup").click()');
  const deadline=Date.now()+5000;
  while (await evaluate(a.id,'document.querySelector("#status").textContent')!=='Popup connected' && Date.now()<deadline) await new Promise(r=>setTimeout(r,50));
  assert.equal(await evaluate(a.id,'document.querySelector("#status").textContent'),'Popup connected'); check('popup: separate tab with preserved opener');
  surface.hide(); assert.ok(scope.tabs.list().length>=7);
  const capture = await scope.call('executeCdp',{target:{tabId:a.id},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  assert.ok(capture.data.length>100); check('hidden page screenshot and retained lifecycle');
  await savePage(Buffer.from(capture.data,'base64'));
  present(a.id);
  // Exercise the example's real, sender-validated IPC through its own renderer.
  const ui = expression => window.webContents.executeJavaScript(expression);
  // Drive Chromium's real Enter default action, rather than calling
  // requestSubmit, so address navigation also covers the keyboard path.
  const pressEnter = async () => {
    window.webContents.debugger.attach('1.3');
    try {
      await window.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
      await window.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    } finally { window.webContents.debugger.detach(); }
  };
  const action = (name,value) => ui(`window.iabExample.action(${JSON.stringify(name)},${JSON.stringify(value) ?? 'undefined'})`);
  const waitFor = async (predicate,timeoutMs=5000) => {
    const until = Date.now()+timeoutMs;
    while (!(await predicate())) { if (Date.now()>=until) throw new Error('Browser panel UI timed out: '+JSON.stringify(await ui('({error:document.querySelector("#error").textContent,address:document.querySelector("#address").value,focus:document.activeElement?.id})'))); await new Promise(r=>setTimeout(r,25)); }
  };
  await waitFor(()=>ui(`document.querySelectorAll('[role="tab"]').length === ${scope.tabs.list().length}`));
  const layout = await ui(`(()=>{const r=document.querySelector('#viewport').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,label:document.body.textContent.includes('Native WebContentsView')}})()`);
  assert.equal(layout.label,false); assert.equal(layout.x,280); assert.equal(layout.y,134);
  const nativeBounds = () => window.contentView.children.find(view=>view.webContents && view.webContents !== window.webContents).getBounds();
  assert.deepEqual(nativeBounds(),{x:layout.x,y:layout.y,width:layout.width,height:layout.height});
  assert.ok(layout.width>=600 && layout.height>400); check('browser panel: tab strip, toolbar and native viewport aligned');
  window.setContentSize(960,760);
  await waitFor(()=>ui("Math.round(document.querySelector('#viewport').getBoundingClientRect().width)===680"));
  const small = await ui("(()=>{const r=document.querySelector('#viewport').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()");
  await action('viewport',small); assert.equal(small.height,626);
  assert.deepEqual(nativeBounds(),small);
  window.setContentSize(1240,828);
  await waitFor(()=>ui("Math.round(document.querySelector('#viewport').getBoundingClientRect().width)===960"));
  await assert.rejects(action('viewport',{x:0,y:0,width:960,height:760}));
  check('browser panel: resizing stays below chrome, invalid bounds rejected');
  const manual = await action('create');
  await waitFor(()=>ui(`document.querySelector('#address').value===${JSON.stringify(`${fixture.url}/manual`)}`));
  await ui(`(()=>{const input=document.querySelector('#address');input.focus();input.value=${JSON.stringify(`${fixture.url}/ui-target`)};document.querySelector('#address-form').requestSubmit();input.blur();return true})()`);
  await waitFor(()=>evaluate(manual.id,"location.pathname==='/ui-target'"));
  await waitFor(()=>ui(`document.querySelector('#address').value === ${JSON.stringify(`${fixture.url}/ui-target`)}`));
  await waitFor(()=>ui("!document.querySelector('#back').disabled"));
  await ui("document.querySelector('#back').click();true"); await waitFor(()=>evaluate(manual.id,"location.pathname==='/manual'"));
  await waitFor(()=>ui("!document.querySelector('#forward').disabled"));
  await ui("document.querySelector('#forward').click();true"); await waitFor(()=>evaluate(manual.id,"location.pathname==='/ui-target'"));
  await evaluate(manual.id,'window.__beforeReload=true');
  await ui("document.querySelector('#reload').click();true"); await waitFor(()=>evaluate(manual.id,"document.readyState==='complete' && window.__beforeReload===undefined"));
  await assert.rejects(action('navigate','file:///etc/passwd'));
  await action('hide'); assert.equal((await ui('window.iabExample.state()')).selected,undefined);
  await action('select',manual.id); await action('close',manual.id);
  assert.ok(!scope.tabs.list().some(tab=>tab.id===manual.id));
  await action('select',a.id);
  await waitFor(()=>ui(`document.querySelector('[role="tab"][aria-selected="true"]')?.title === ${JSON.stringify(`${fixture.url}/login`)}`));
  check('browser panel: address navigation, history, reload, hide, restore and close');
  await waitFor(()=>ui(`document.querySelector('#address').value===${JSON.stringify(`${fixture.url}/login`)}`));
  // Exercise the same fixed IPC the main process sends for Cmd/Ctrl+L. The
  // smoke window need not take OS foreground focus from the developer.
  window.webContents.send('iab-example:focus-address');
  await waitFor(()=>ui("document.querySelector('#address').selectionStart===0 && document.querySelector('#address').selectionEnd===document.querySelector('#address').value.length"));
  // The address bar now transitions between idle, hover and focus colors.
  await waitFor(()=>ui("getComputedStyle(document.querySelector('#address-form')).borderColor==='rgb(76, 132, 223)'"));
  const focused=await ui(`(()=>{const input=document.querySelector('#address');return {start:input.selectionStart,end:input.selectionEnd,length:input.value.length,selection:getComputedStyle(input,'::selection').backgroundColor,border:getComputedStyle(document.querySelector('#address-form')).borderColor}})()`);
  assert.equal(focused.start,0); assert.equal(focused.end,focused.length);
  assert.equal(focused.selection,'rgb(54, 121, 213)'); assert.equal(focused.border,'rgb(76, 132, 223)');
  await savePage((await window.webContents.capturePage()).toPNG(),'address-focused.png');
  const slowUrl=`${fixture.url}/slow`;
  await ui(`(()=>{const input=document.querySelector('#address');input.value=${JSON.stringify(slowUrl.replace('http://',''))};return true})()`);
  await pressEnter();
  await waitFor(async()=>!!(await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id)?.loading);
  await waitFor(()=>ui(`document.querySelector('[data-tab-id="${a.id}"]').classList.contains('loading') && document.querySelector('#address-form').classList.contains('loading')`));
  assert.equal((await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id).pendingUrl,slowUrl);
  assert.equal(await ui("document.querySelector('#address').value"),slowUrl);
  await savePage((await window.webContents.capturePage()).toPNG(),'address-loading.png');
  await action('select',b.id);
  await waitFor(()=>ui("!document.querySelector('#address-form').classList.contains('loading')"));
  assert.equal((await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id).loading,true);
  fixture.releaseSlowPages();
  await waitFor(()=>evaluate(a.id,'location.pathname==="/slow" && document.readyState==="complete"'));
  await waitFor(async()=>!(await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id).loading);
  assert.equal((await ui('window.iabExample.state()')).selected,b.id);
  await action('select',a.id);
  await waitFor(()=>ui("!document.querySelector('#address-form').classList.contains('loading')"));
  check('address: scheme-less Enter, clear focus/selection and live loading before slow server responds');
  await ui("window.__failedNavigation=window.iabExample.action('navigate','http://127.0.0.1:0/unreachable').then(()=>false,()=>true);true");
  assert.equal(await ui('window.__failedNavigation'),true);
  await waitFor(async()=>{const tab=(await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id);return !tab.loading && !!tab.loadError});
  await waitFor(()=>ui("document.querySelector('#status').textContent.includes('加载失败')"));
  const recovered=`http://localhost:${new URL(fixture.url).port}/recovered`;
  await ui(`(()=>{const input=document.querySelector('#address');input.focus();input.value=${JSON.stringify(recovered.replace('http://',''))};return true})()`);
  await pressEnter();
  await waitFor(()=>evaluate(a.id,'location.pathname==="/recovered" && document.readyState==="complete"'));
  await waitFor(async()=>{const tab=(await ui('window.iabExample.state()')).tabs.find(tab=>tab.id===a.id);return !tab.loading && !tab.loadError});
  await waitFor(()=>ui("!document.querySelector('#status').textContent.includes('加载失败')"));
  check('address: failed navigation stops loading, localhost:port retry clears the error');
  await action('feedback',true);
  await scope.visualFeedback.setActive(a.id,true);
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:80,y:80}});
  const overlay = await evaluate(a.id,'(()=>{const e=document.getElementById("obu-iab-visual-feedback");return {visible:!!e,cursor:e?.dataset.cursorVisible,edge:e?.dataset.edgeGlow,x:e?.dataset.x,closed:e?.shadowRoot===null,isolated:typeof globalThis.__obuIabFeedback,hit:document.elementFromPoint(80,80)?.id}})()');
  assert.equal(overlay.visible,true); assert.equal(overlay.cursor,'true'); assert.equal(overlay.edge,'true'); assert.equal(overlay.x,'80');
  assert.equal(overlay.closed,true); assert.equal(overlay.isolated,'undefined'); assert.notEqual(overlay.hit,'obu-iab-visual-feedback');
  const feedbackImage=await scope.call('executeCdp',{target:{tabId:a.id},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  await savePage(Buffer.from(feedbackImage.data,'base64'),'feedback.png');
  const feedbackGuest=window.contentView.children.find(view=>view.webContents && view.webContents!==window.webContents).webContents;
  const edgeStyle=()=>feedbackGuest.executeJavaScriptInIsolatedWorld(999,[{code:`(()=>{const c=globalThis.__obuIabFeedback;return {shadow:getComputedStyle(c.edge).boxShadow,hidden:c.edge.hidden,cursor:c.root.dataset.cursorVisible}})()`}]);
  await runtime.visualFeedback.configure({edgeGlowColor:'#A3c'});
  assert.equal(runtime.visualFeedback.getOptions().edgeGlowColor,'#aa33cc');
  assert.match((await edgeStyle()).shadow,/rgba\(170, 51, 204, 0\.32\)/);
  await assert.rejects(runtime.visualFeedback.configure({edgeGlow:false,edgeGlowColor:'invalid'}),/hex color/);
  assert.equal((await edgeStyle()).hidden,false);
  await runtime.visualFeedback.configure({edgeGlow:false});
  assert.deepEqual({hidden:(await edgeStyle()).hidden,cursor:(await edgeStyle()).cursor},{hidden:true,cursor:'true'});
  await runtime.visualFeedback.configure({edgeGlowColor:'#22C55E'});
  assert.equal((await edgeStyle()).hidden,true);
  await runtime.visualFeedback.configure({edgeGlow:true});
  assert.match((await edgeStyle()).shadow,/rgba\(34, 197, 94, 0\.32\)/);
  const coloredImage=await scope.call('executeCdp',{target:{tabId:a.id},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  await savePage(Buffer.from(coloredImage.data,'base64'),'feedback-custom-color.png');
  await runtime.visualFeedback.configure({edgeGlowColor:'#4f8fe8'});
  check('visual feedback: live custom color, atomic validation and independent edge toggle preserve the cursor');
  await action('feedback',false);
  assert.equal(await evaluate(a.id,'!!document.getElementById("obu-iab-visual-feedback")'),false);
  await action('feedback',true);
  await scope.visualFeedback.setActive(a.id,false); await scope.visualFeedback.setActive(b.id,true);
  assert.equal(await evaluate(a.id,'!!document.getElementById("obu-iab-visual-feedback")'),false);
  await scope.call('executeCdp',{target:{tabId:b.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:50,y:50}});
  await runtime.visualFeedback.configure({cursor:false,edgeGlow:true});
  assert.equal(await evaluate(b.id,'document.getElementById("obu-iab-visual-feedback").dataset.cursorVisible'),'false');
  await runtime.visualFeedback.configure({cursor:true,edgeGlow:false});
  assert.equal(await evaluate(b.id,'document.getElementById("obu-iab-visual-feedback").dataset.edgeGlow'),'false');
  await scope.visualFeedback.setActive(b.id,false); await action('feedback',true);
  check('visual feedback: isolated, nonblocking, scoped activity and independent/disabled options');
  await scope.visualFeedback.setActive(a.id,true);
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Page.navigate',commandParams:{url:`${fixture.url}/strict-csp`}});
  await waitFor(()=>evaluate(a.id,'location.pathname==="/strict-csp" && document.readyState==="complete" && !!document.getElementById("obu-iab-visual-feedback")').catch(()=>false));
  assert.equal(await evaluate(a.id,'document.getElementById("obu-iab-visual-feedback").dataset.cursorVisible'),'false');
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:80,y:80}});
  // Inspect through the trusted host's isolated world; the page cannot read the
  // closed shadow. Verify the actual bitmap, not only that an overlay exists.
  const guest = window.contentView.children.find(view=>view.webContents && view.webContents !== window.webContents).webContents;
  await runtime.visualFeedback.configure({edgeGlowColor:'#F0A'});
  const strictShadow=await guest.executeJavaScriptInIsolatedWorld(999,[{code:'getComputedStyle(globalThis.__obuIabFeedback.edge).boxShadow'}]);
  assert.match(strictShadow,/rgba\(255, 0, 170, 0\.32\)/);
  const rendered = await guest.executeJavaScriptInIsolatedWorld(999,[{code:`(()=>{const canvas=globalThis.__obuIabFeedback.cursorLayer.querySelector('canvas');return {width:canvas.width,height:canvas.height,displayWidth:canvas.style.width,displayHeight:canvas.style.height,pixels:Array.from(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data)}})()`}]);
  assert.equal(rendered.width,cursorBitmap.width); assert.equal(rendered.height,cursorBitmap.height);
  assert.equal(rendered.displayWidth,'23px'); assert.equal(rendered.displayHeight,'24px');
  // Canvas may round translucent RGB by one byte through premultiplication;
  // fully opaque pixels and alpha must retain the original asset exactly.
  const original=Buffer.from(cursorBitmap.rgba,'base64');
  for (let i=0;i<original.length;i+=4) {
    assert.equal(rendered.pixels[i+3],original[i+3]);
    if (original[i+3]===255) assert.deepEqual(rendered.pixels.slice(i,i+3),Array.from(original.subarray(i,i+3)));
  }
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mousePressed',x:80,y:80,button:'left',buttons:1,clickCount:1}});
  const ripple = await guest.executeJavaScriptInIsolatedWorld(999,[{code:`(()=>{const r=globalThis.__obuIabFeedback.ring.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`}]);
  assert.ok(Math.abs(ripple.x-80)<0.01 && Math.abs(ripple.y-80)<0.01,'Click ripple remains centered while scaling');
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseReleased',x:80,y:80,button:'left',buttons:0,clickCount:1}});
  const strictFeedbackImage=await scope.call('executeCdp',{target:{tabId:a.id},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  await savePage(Buffer.from(strictFeedbackImage.data,'base64'),'feedback-strict-csp.png');
  await runtime.visualFeedback.configure({edgeGlowColor:'#4f8fe8'});
  await scope.visualFeedback.setActive(a.id,false);
  await scope.call('executeCdp',{target:{tabId:a.id},method:'Input.dispatchMouseEvent',commandParams:{type:'mouseMoved',x:80,y:80}});
  await waitFor(()=>evaluate(a.id,'!document.getElementById("obu-iab-visual-feedback")'));
  check('visual feedback: navigation resets coordinates, custom color renders under strict CSP, transient activity expires');
  while (scope.tabs.list().length) await action('close',scope.tabs.list().at(-1).id);
  assert.equal(await ui("document.querySelectorAll('[data-step]').length"),5);
  await waitFor(()=>ui("[...document.querySelectorAll('[data-step]')].every(step=>!step.disabled)"));
  await assert.rejects(action('demo-step',3),/请先点击.*Tab 1/);
  await assert.rejects(action('demo-step',4),/请先点击.*Tab 2/);
  // Manual actions are independent: opening Tab 2 does not require Tab 1.
  const second = await action('demo-step',2); const first = await action('demo-step',1);
  assert.notEqual(first.tab1,second.tab2);
  assert.equal((await ui('window.iabExample.state()')).selected,first.tab1);
  const clicked = await action('demo-step',3);
  assert.equal(clicked.detail.count,1); assert.equal(clicked.detail.trustedClick,true);
  assert.equal((await ui('window.iabExample.state()')).selected,first.tab1);
  assert.equal(await evaluate(second.tab2,'document.querySelector("#count").textContent'),'0');
  const captureTab1 = await scope.call('executeCdp',{target:{tabId:first.tab1},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  await savePage(Buffer.from(captureTab1.data,'base64'),'demo-tab1.png');
  const submitted = await action('demo-step',4);
  assert.equal(submitted.detail.submitted,'已提交：Hello from CLI');
  assert.equal(submitted.detail.trustedInput,true); assert.equal(submitted.detail.trustedSubmit,true);
  assert.equal((await ui('window.iabExample.state()')).selected,second.tab2);
  const pageLayout = await evaluate(second.tab2,'(()=>{const controls=[...document.querySelectorAll(".control")].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}});return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,controls,background:getComputedStyle(document.body).backgroundColor}})()');
  assert.equal(pageLayout.controls.length,2); assert.equal(pageLayout.background,'rgb(255, 255, 255)');
  assert.ok(pageLayout.scrollWidth<=pageLayout.width && pageLayout.controls.every(control=>control.width>0 && control.height>0));
  assert.ok(pageLayout.controls[1].y>=pageLayout.controls[0].y+pageLayout.controls[0].height);
  const captureTab2 = await scope.call('executeCdp',{target:{tabId:second.tab2},method:'Page.captureScreenshot',commandParams:{format:'png'}});
  await savePage(Buffer.from(captureTab2.data,'base64'),'demo-tab2.png');
  const third = await action('demo-step',5);
  assert.notEqual(third.tab3,first.tab1); assert.notEqual(third.tab3,second.tab2);
  assert.equal(third.detail.url,`${fixture.url}/github-profile`);
  assert.equal((await ui('window.iabExample.state()')).selected,third.tab3);
  assert.equal(await evaluate(third.tab3,'location.pathname'),'/github-profile');
  assert.ok(scope.tabs.list().some(tab=>tab.id===first.tab1) && scope.tabs.list().some(tab=>tab.id===second.tab2));
  assert.equal(await evaluate(first.tab1,'document.querySelector("#count").textContent'),'1');
  assert.equal(await evaluate(second.tab2,'document.querySelector("#submitted").textContent'),'已提交：Hello from CLI');
  check('CLI private demo: third tab opens independently, existing page state is retained');
  assert.equal(scope.tabs.list().length,3);
  await assert.rejects(action('demo-step',6));
  await waitFor(()=>ui("document.querySelector('#step-progress').textContent==='5 / 5'"));
  check('CLI private demo: five manual steps retain all three tabs and trusted input results');
  // Use real button clicks after completion, not only direct IPC calls: an
  // enabled backend alone would miss a renderer that still locks old steps.
  const clickStep = async number => {
    await waitFor(()=>ui(`!document.querySelector('[data-step="${number}"]').disabled`));
    await ui(`document.querySelector('[data-step="${number}"]').click();true`);
  };
  const waitIdle = () => waitFor(async()=>!(await ui('window.iabExample.state()')).demo.busy,30_000);
  for (const count of [2,3]) {
    await clickStep(3);
    await waitFor(()=>evaluate(first.tab1,`document.querySelector('#count').textContent==='${count}'`),30_000);
    await waitIdle();
  }
  await evaluate(second.tab2,"window.__repeatSubmits=0;document.querySelector('#demo-form').addEventListener('submit',()=>window.__repeatSubmits++);true");
  for (const count of [1,2]) {
    await clickStep(4);
    await waitFor(()=>evaluate(second.tab2,`window.__repeatSubmits===${count}`),30_000);
    await waitIdle();
    assert.equal(await evaluate(second.tab2,"document.querySelector('#message').value"),'Hello from CLI');
  }
  let latest=third;
  for (const [step,key] of [[1,'tab1'],[2,'tab2'],[5,'tab3']]) {
    const previous=latest[key];
    await clickStep(step);
    await waitFor(async()=>{const demo=(await ui('window.iabExample.state()')).demo;return demo[key]!==previous && !demo.busy},30_000);
    latest=(await ui('window.iabExample.state()')).demo;
    assert.notEqual(latest[key],previous);
  }
  assert.equal(scope.tabs.list().length,6);
  assert.equal(await evaluate(first.tab1,"document.querySelector('#count').textContent"),'3');
  assert.equal(await evaluate(second.tab2,'window.__repeatSubmits'),2);
  assert.equal(await evaluate(latest.tab1,"document.querySelector('#count').textContent"),'0');
  assert.equal(await evaluate(latest.tab3,'location.pathname'),'/github-profile');
  assert.deepEqual(latest.completed,[1,2,3,4,5]); assert.equal(latest.results.length,5);
  await action('close',latest.tab1);
  await assert.rejects(action('demo-step',3),/请先点击.*Tab 1/);
  await clickStep(1);
  await waitFor(async()=>{const demo=(await ui('window.iabExample.state()')).demo;return demo.tab1!==latest.tab1 && !demo.busy},30_000);
  assert.equal(scope.tabs.list().length,6);
  await waitFor(()=>ui("document.querySelector('#step-progress').textContent==='5 / 5' && [...document.querySelectorAll('[data-step]')].every(step=>!step.disabled)"));
  check('manual actions: all five repeat via real buttons, new tabs preserve prior results, missing targets stay guarded');
  const automated = await action('demo-play');
  assert.deepEqual(automated.completed,[1,2,3,4,5]);
  assert.equal(automated.results.find(result=>result.step===3).detail.count,1);
  assert.equal(automated.results.find(result=>result.step===4).detail.trustedSubmit,true);
  assert.equal(automated.results.find(result=>result.step===5).detail.url,`${fixture.url}/github-profile`);
  assert.equal(scope.tabs.list().length,3);
  assert.ok(!scope.tabs.list().some(tab=>[first.tab1,second.tab2,third.tab3].includes(tab.id)));
  assert.equal(await evaluate(automated.tab1,'document.querySelector("#count").textContent'),'1');
  assert.equal(await evaluate(automated.tab2,'document.querySelector("#submitted").textContent'),'已提交：Hello from CLI');
  check('CLI private demo: replay resets old tabs, completes five steps and retains results');
  await waitFor(()=>ui(`!![...document.querySelectorAll('[role="tab"]')].find(tab=>tab.title===${JSON.stringify(`${fixture.url}/Tab%201`)})`));
  await ui(`[...document.querySelectorAll('[role="tab"]')].find(tab=>tab.title===${JSON.stringify(`${fixture.url}/Tab%201`)}).click();true`);
  await waitFor(async()=>(await ui('window.iabExample.state()')).selected===automated.tab1);
  assert.equal(await ui("document.querySelector('#address').disabled"),false);
  await ui(`(()=>{const input=document.querySelector('#address');input.focus();input.value=${JSON.stringify(`${fixture.url}/inspect`)};document.querySelector('#address-form').requestSubmit();input.blur();return true})()`);
  await waitFor(()=>evaluate(automated.tab1,'location.pathname==="/inspect"'));
  await waitFor(()=>ui("!document.querySelector('#back').disabled"));
  await ui("document.querySelector('#back').click();true"); await waitFor(()=>evaluate(automated.tab1,'location.pathname==="/Tab%201"'));
  await waitFor(()=>ui("!document.querySelector('#forward').disabled"));
  await ui("document.querySelector('#forward').click();true"); await waitFor(()=>evaluate(automated.tab1,'location.pathname==="/inspect"'));
  await evaluate(automated.tab1,'window.__beforeReload=true');
  await ui("document.querySelector('#reload').click();true"); await waitFor(()=>evaluate(automated.tab1,'window.__beforeReload===undefined && document.readyState==="complete"'));
  assert.equal(await evaluate(automated.tab2,'document.querySelector("#submitted").textContent'),'已提交：Hello from CLI');
  check('retained tabs: real tab button, address form, back/forward and refresh remain usable');
  const manualOpen = await action('demo-step',1);
  assert.deepEqual(manualOpen.completed,[1,2,3,4,5]); assert.equal(scope.tabs.list().length,4);
  assert.ok(scope.tabs.list().some(tab=>tab.id===automated.tab2));
  await ui("window.__demoPlayback=window.iabExample.action('demo-play');true");
  await waitFor(async()=>{const d=(await ui('window.iabExample.state()')).demo;return d.playing && d.completed.includes(1) && d.tab1!==manualOpen.tab1});
  await assert.rejects(action('demo-step',2));
  await action('demo-stop');
  const stopped = await ui('window.__demoPlayback');
  assert.equal(stopped.playing,false);
  const idle = (await ui('window.iabExample.state()')).demo;
  assert.equal(idle.playing,false); assert.equal(idle.busy,false); assert.ok(idle.completed.length<5);
  assert.ok(scope.tabs.list().length>0);
  check('CLI private demo: stop completes safely and preserves the opened pages');
  await ui("window.__demoPlayback=window.iabExample.action('demo-play');true");
  await waitFor(async()=>{const d=(await ui('window.iabExample.state()')).demo;return d.playing && d.current===3});
  const active=(await ui('window.iabExample.state()')).demo;
  assert.equal(await ui("document.querySelector('#address').disabled"),false);
  assert.equal(await ui("[...document.querySelectorAll('[role=tab]')].some(tab=>tab.disabled)"),false);
  await ui(`[...document.querySelectorAll('[role="tab"]')].find(tab=>tab.title===${JSON.stringify(`${fixture.url}/Tab%202`)}).click();true`);
  await waitFor(()=>ui(`document.querySelector('[role=tab][aria-selected=true]')?.title===${JSON.stringify(`${fixture.url}/Tab%202`)}`));
  await ui(`(()=>{const input=document.querySelector('#address');input.focus();input.value=${JSON.stringify(`${fixture.url}/user-controlled`)};document.querySelector('#address-form').requestSubmit();input.blur();return true})()`);
  await action('select',active.tab1);
  const takenOver=await ui('window.__demoPlayback');
  await waitFor(()=>evaluate(active.tab2,'location.pathname==="/user-controlled"'));
  assert.ok(!takenOver.completed.includes(4));
  assert.equal(await evaluate(active.tab1,'document.querySelector("#count").textContent'),'1');
  check('manual takeover: switch during playback, navigate captured tab after current step, cancel remaining steps');
  return { passed:true, electron:process.versions.electron, platform:process.platform, checks, tabs:scope.tabs.list().length };
}
