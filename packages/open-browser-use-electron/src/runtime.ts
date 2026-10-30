import { randomUUID } from 'node:crypto';
import { spawn, type ChildProcess } from 'node:child_process';
import { once, EventEmitter } from 'node:events';
import { realpath, stat } from 'node:fs/promises';
import { isAbsolute, join, extname } from 'node:path';
import type { Duplex } from 'node:stream';
import type { WebContentsView, WebContents, Session, BaseWindow, DownloadItem } from 'electron';
import { IabConnections, type Backend, type IabEvent, type Operation, type GrantOptions } from './transport.js';
import { frame } from './wire.js';
import { FeedbackController, type VisualFeedbackOptions } from './feedback.js';
import { webMcpSource } from './webmcp-source.js';

export type ElectronAdapter = {
  createView(session: Session, contents?: WebContents): WebContentsView;
  createSession(partition: string): Session;
  clipboard?: {
    readText(): Promise<string>;
    writeText(text: string): Promise<void>;
    read(): Promise<Array<{types: string[]; getType(type: string): Promise<unknown>}>>;
    write(items: Array<Record<string,Blob>>): Promise<void>;
  };
};
type Tab = {
  id: number; scopeId: string; view: WebContentsView; contents: WebContents; lifetime: 'temporary' | 'persistent';
  touched: Set<string>; marks: Map<string, 'handoff' | 'deliverable'>;
  attached: boolean; webMcpReady:boolean; mouseReady: boolean; pending: number; queue: Promise<any>; removers: (() => void)[];
  frameSessions: Map<string, string | undefined>;
  loading: boolean; pendingUrl?: string; loadError?: { code: number; description: string; url: string };
};
type ScopeState = { id: string; profileId: string; webmcp:boolean; tabs: Map<number, Tab>; name: string; uploadFiles: Set<string>; uploadEpoch: number; download?: { directory: string; maxBytes: number }; downloadEpoch: number; closing?: boolean };
type DownloadWait = { scopeId: string; tabId: number; epoch: number; authorized: () => boolean; signal?: AbortSignal; resolve: (value: {downloadId: string; url: string | null}) => void; reject: (error: Error) => void };
type DownloadRecord = { scopeId: string; epoch: number; path: string; done: Promise<string | null>; cancel: () => void; cleanup: () => void };
type Surface = { window: BaseWindow; owner: WebContents; tabId?: number; bounds: { x: number; y: number; width: number; height: number }; remove: () => void };
const pageCommands = new Set([
  'Page.enable', 'Page.disable', 'Page.navigate', 'Page.reload', 'Page.stopLoading', 'Page.handleJavaScriptDialog',
  'Page.getNavigationHistory', 'Page.navigateToHistoryEntry', 'Page.captureScreenshot', 'Page.getFrameTree',
  'Page.getLayoutMetrics', 'Page.close', 'Page.createIsolatedWorld',
  'Runtime.enable', 'Runtime.disable', 'Runtime.evaluate', 'Runtime.callFunctionOn',
  'Runtime.getProperties', 'Runtime.releaseObject', 'Runtime.releaseObjectGroup',
  'Log.enable', 'Log.disable',
  'DOM.enable', 'DOM.disable', 'DOM.getDocument', 'DOM.describeNode', 'DOM.querySelector',
  'DOM.querySelectorAll', 'DOM.getBoxModel', 'DOM.getContentQuads', 'DOM.getOuterHTML',
  'DOM.resolveNode', 'DOM.focus', 'DOM.scrollIntoViewIfNeeded', 'DOM.getFrameOwner',
  'Accessibility.enable', 'Accessibility.disable', 'Accessibility.getFullAXTree',
  'Input.dispatchMouseEvent', 'Input.dispatchKeyEvent', 'Input.insertText', 'Input.synthesizeScrollGesture',
  'Network.enable', 'Network.disable', 'Network.getResponseBody',
]);
export function assertUrl(value: unknown): string {
  if (value === 'about:blank') return value;
  if (typeof value !== 'string') throw new Error('Invalid URL');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('IAB navigation only permits http, https and about:blank');
  return value;
}

export class IabRuntime implements Backend {
  readonly instanceId = randomUUID();
  readonly connections = new IabConnections(this);
  private events = new EventEmitter();
  private profileSessions = new Map<string, Session>();
  private sessionRemovers: (() => void)[] = [];
  private states = new Map<string, ScopeState>();
  private scopeDisposals = new Map<string, Promise<void>>();
  private tabsById = new Map<number, Tab>();
  private chooserWaits = new Set<number>();
  private downloadWaits = new Map<number, DownloadWait>();
  private downloads = new Map<string, DownloadRecord>();
  private choosers = new Map<string, {scopeId: string; tabId: number; backendNodeId: number; sessionId?: string; multiple: boolean}>();
  private surfaceStates = new Map<string, Surface>();
  private workers = new Set<ChildProcess>();
  private nextTabId = 1;
  private closed = false;
  private disposing?: Promise<void>;
  private feedbackController: FeedbackController;
  constructor(private adapter: ElectronAdapter, readonly appId: string, feedback: VisualFeedbackOptions = {}) {
    this.feedbackController = new FeedbackController(feedback);
    if (!appId || appId.length > 100) throw new Error('appId is required');
    this.events.setMaxListeners(256);
  }
  readonly visualFeedback = {
    configure: (options: VisualFeedbackOptions) => { this.ensureOpen(); return this.feedbackController.configure(options); },
    getOptions: () => this.feedbackController.configuration,
  };
  async setFeedbackActive(scopeId: string,tabId: number,active: boolean): Promise<void> {
    this.ensureOpen(); await this.feedbackController.setActive(this.tab(scopeId,tabId).contents,active);
  }
  readonly profilesApi = {
    open: (options: { id: string; persistent?: boolean }): { id: string } => {
      this.ensureOpen();
      if (!options.id || options.id.length > 100) throw new Error('Invalid profile id');
      const key = `${options.persistent === false ? '' : 'persist:'}obu-iab:${encodeURIComponent(this.appId)}:${encodeURIComponent(options.id)}`;
      if (!this.profileSessions.has(options.id)) {
        const session = this.adapter.createSession(key);
        session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
        session.setPermissionCheckHandler(() => false);
        const download = (event: { preventDefault(): void }, item: DownloadItem, contents: WebContents) => this.handleDownload(event,item,contents);
        session.on('will-download', download);
        this.sessionRemovers.push(() => session.off('will-download', download));
        this.profileSessions.set(options.id, session);
      } else if ((this.profileSessions.get(options.id)!.isPersistent?.() ?? options.persistent !== false) !== (options.persistent !== false)) {
        throw new Error('Cannot change profile persistence');
      }
      return { id: options.id };
    },
  };
  readonly profiles = this.profilesApi;
  readonly scopes = {
    open: (options: { id: string; profileId: string; webmcp?:boolean }): IabScope => {
      this.ensureOpen();
      if (!options.id || options.id.length > 200 || !this.profileSessions.has(options.profileId) || (options.webmcp!==undefined && typeof options.webmcp!=='boolean')) throw new Error('Scope requires a registered profile and valid options');
      const previous = this.states.get(options.id);
      if (previous?.closing) throw new Error('IAB_SCOPE_CLOSED');
      if (previous && previous.profileId !== options.profileId) throw new Error('Cannot change scope profile');
      if (previous && options.webmcp!==undefined && previous.webmcp!==options.webmcp) throw new Error('Cannot change scope WebMCP configuration');
      if (!previous) this.states.set(options.id, { ...options, webmcp:options.webmcp===true, tabs: new Map(), name: options.id, uploadFiles: new Set(), uploadEpoch: 0, downloadEpoch: 0 });
      return new IabScope(this, options.id);
    },
  };
  hasScope(id: string): boolean { return !this.closed && !this.disposing && this.states.has(id) && !this.states.get(id)!.closing; }
  subscribe(handler: (event: IabEvent) => void): () => void { this.events.on('event', handler); return () => { this.events.off('event', handler); }; }
  private emit(scopeId: string, method: string, params: Record<string, any>): void { this.events.emit('event', { scopeId, method, params }); }
  private ensureOpen(): void { if (this.closed || this.disposing) throw new Error('IAB_DISPOSED'); }
  private scope(id: string): ScopeState { const s = this.states.get(id); if (!s || s.closing || this.closed) throw new Error('IAB_SCOPE_CLOSED'); return s; }
  private tab(scopeId: string, id: unknown): Tab {
    if (!Number.isSafeInteger(id)) throw new Error('Explicit numeric tabId required');
    const tab = this.scope(scopeId).tabs.get(id as number);
    if (!tab || tab.contents.isDestroyed()) throw new Error('IAB_TAB_NOT_OWNED');
    return tab;
  }
  private snapshot(tab: Tab): Record<string, any> {
    return { id: tab.id, title: tab.contents.getTitle(), url: tab.contents.getURL(),
        active: [...this.surfaceStates.values()].some(s => s.tabId === tab.id), lifetime: tab.lifetime,
        loading: tab.loading, pendingUrl: tab.pendingUrl, loadError: tab.loadError };
  }
  private allocate(scopeId: string, contents?: WebContents): Tab {
    const scope = this.scope(scopeId);
    if (scope.tabs.size >= 32 || this.tabsById.size >= 128) throw new Error('IAB_TAB_LIMIT');
    const profile = this.profileSessions.get(scope.profileId)!;
    if (contents && contents.session !== profile) throw new Error('Popup profile mismatch');
    const view = this.adapter.createView(profile, contents);
    view.setBounds({ x: 0, y: 0, width: 800, height: 600 }); view.setVisible(false);
    const tab: Tab = { id: this.nextTabId++, scopeId, view, contents: view.webContents, lifetime: 'temporary', touched: new Set(), marks: new Map(), attached: false, webMcpReady:false, mouseReady: false, pending: 0, queue: Promise.resolve(), removers: [], loading: false, frameSessions: new Map() };
    scope.tabs.set(tab.id, tab); this.tabsById.set(tab.id, tab);
    const wc = view.webContents;
    this.feedbackController.register(wc);
    const updated = () => { if (!wc.isDestroyed()) this.emit(scopeId,'onTabUpdated',{tab:this.snapshot(tab)}); };
    const listen = (target: EventEmitter, name: string, listener: (...args: any[]) => void) => {
      target.on(name, listener); tab.removers.push(() => target.off(name, listener));
    };
    const checkNavigation = (event: { preventDefault(): void }, urlOrDetails: string | { url: string }) => {
      try { assertUrl(typeof urlOrDetails === 'string' ? urlOrDetails : urlOrDetails.url); }
      catch { event.preventDefault(); }
    };
    listen(wc, 'will-navigate', checkNavigation); listen(wc, 'will-frame-navigate', checkNavigation); listen(wc, 'will-redirect', checkNavigation);
    listen(wc, 'destroyed', () => this.forget(tab));
    const navigating = (details: any,url: string,_inPlace: boolean,isMainFrame: boolean) => {
      if (!(details.isMainFrame ?? isMainFrame)) return;
      const target=details.url ?? url;
      if (target?.startsWith('chrome-error:')) return;
      tab.pendingUrl=(details.isSameDocument ?? _inPlace)?undefined:target; tab.loadError=undefined; updated();
    };
    listen(wc,'did-start-navigation',navigating);
    listen(wc,'did-redirect-navigation',navigating);
    listen(wc,'did-start-loading',()=>{tab.loading=true;updated();});
    listen(wc,'did-stop-loading',()=>{tab.loading=false;tab.pendingUrl=undefined;updated();});
    listen(wc,'did-fail-load',(_event: any,code: number,description: string,url: string,isMainFrame: boolean)=>{
      if (!isMainFrame || code===-3) return; // Superseded/stopped navigation is not a site error.
      tab.loadError={code,description,url}; updated();
    });
    listen(wc, 'did-finish-load', () => { tab.mouseReady = false; });
    listen(wc, 'did-finish-load', () => this.feedbackController.resetDocument(wc));
    listen(wc, 'did-navigate-in-page', () => this.feedbackController.resetDocument(wc));
    listen(wc, 'page-title-updated', () => this.emit(scopeId, 'onTabUpdated', { tab: this.snapshot(tab) }));
    for (const event of ['did-navigate', 'did-navigate-in-page', 'did-stop-loading']) {
      listen(wc, event, () => { if (!wc.isDestroyed()) this.emit(scopeId, 'onTabUpdated', { tab: this.snapshot(tab) }); });
    }
    listen(wc, 'render-process-gone', () => { void this.destroyTab(tab).catch(() => {}); });
    listen(wc.debugger, 'message', (_event, method, params, sessionId) => {
      if (['Page.frameNavigated','Page.frameDetached','Target.detachedFromTarget'].includes(method)) this.invalidateChoosers(tab.id);
      if (sessionId && !tab.frameSessions.has(sessionId)) return;
      if (method === 'Target.attachedToTarget') {
        if (params?.targetInfo?.type !== 'iframe' || typeof params?.sessionId !== 'string') return;
        tab.frameSessions.set(params.sessionId, sessionId);
      }
      if (method === 'Target.detachedFromTarget' && typeof params?.sessionId === 'string') {
        const remove = (id: string) => { tab.frameSessions.delete(id); for (const [child, parent] of tab.frameSessions) if (parent === id) remove(child); };
        remove(params.sessionId);
      }
      if (this.states.get(scopeId)?.tabs.has(tab.id)) this.emit(scopeId, 'onCDPEvent', { source: { tabId: tab.id, ...(sessionId ? {sessionId} : {}) }, method, params });
    });
    listen(wc.debugger, 'detach', () => { this.invalidateChoosers(tab.id); tab.attached = false; tab.webMcpReady=false; tab.frameSessions.clear(); this.emit(scopeId, 'onDebuggerDetach', { tabId: tab.id }); });
    wc.setWindowOpenHandler(details => {
      try { assertUrl(details.url); } catch { return { action: 'deny' }; }
      if (!this.hasScope(scopeId) || scope.tabs.size >= 32 || this.tabsById.size >= 128) return { action: 'deny' };
      return { action: 'allow', createWindow: options => {
        // Electron internally supplies a precreated WebContents for some popup
        // dispositions; preserve it when present to retain opener semantics.
        const contents = (options as typeof options & { webContents?: WebContents }).webContents;
        const popup = this.allocate(scopeId, contents);
        return popup.contents;
      } };
    });
    this.emit(scopeId, 'onTabCreated', { tab: this.snapshot(tab) }); return tab;
  }
  async createTab(scopeId: string, options: { url?: string; turnId?: string } = {}, authorized:()=>boolean = ()=>true): Promise<Record<string, any>> {
    const url = assertUrl(options.url ?? 'about:blank');
    const tab = this.allocate(scopeId);
    if (options.turnId) tab.touched.add(options.turnId);
    try { if(this.scope(scopeId).webmcp) {await tab.contents.loadURL('about:blank');if(!authorized())throw new Error('IAB_AUTH_REVOKED');await this.setupWebMcp(tab,()=>this.hasScope(scopeId) && authorized());}if(!authorized())throw new Error('IAB_AUTH_REVOKED');if(url!=='about:blank' || !this.scope(scopeId).webmcp)await tab.contents.loadURL(url);if(!authorized())throw new Error('IAB_AUTH_REVOKED');return this.snapshot(tab); }
    catch (error) { await this.closeTab(scopeId, tab.id); throw error; }
  }
  listTabs(scopeId: string): Record<string, any>[] { return [...this.scope(scopeId).tabs.values()].map(t => this.snapshot(t)); }
  private forget(tab: Tab): void {
    this.invalidateChoosers(tab.id);
    this.downloadWaits.get(tab.id)?.reject(new Error('IAB_DOWNLOAD_TAB_CLOSED'));
    if (!this.tabsById.delete(tab.id)) return;
    this.feedbackController.release(tab.contents);
    this.states.get(tab.scopeId)?.tabs.delete(tab.id);
    for (const surface of this.surfaceStates.values()) if (surface.tabId === tab.id) {
      if (!surface.window.isDestroyed?.()) surface.window.contentView.removeChildView(tab.view);
      surface.tabId = undefined;
    }
    for (const remove of tab.removers) remove(); tab.removers = [];
    this.emit(tab.scopeId, 'onTabClosed', { tabId: tab.id });
  }
  async closeTab(scopeId: string, tabId: number): Promise<void> {
    await this.destroyTab(this.tab(scopeId, tabId));
  }
  private async destroyTab(tab: Tab): Promise<void> {
    this.forget(tab);
    if (!tab.contents.isDestroyed()) {
      const done = once(tab.contents, 'destroyed');
      tab.contents.close({ waitForBeforeUnload: false });
      await done;
    }
  }
  private async webMcpDeadline<T>(promise:Promise<T>,timeoutMs:number):Promise<T> {
    let timer:ReturnType<typeof setTimeout> | undefined;
    try {return await Promise.race([promise,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error('IAB_WEBMCP_OUTCOME_UNKNOWN')),timeoutMs);})]);}
    finally {if(timer)clearTimeout(timer);}
  }
  private async setupWebMcp(tab:Tab,authorized:()=>boolean):Promise<void> {
    if(tab.webMcpReady)return;
    if(!authorized() || tab.contents.isDestroyed())throw new Error('IAB_AUTH_REVOKED');
    if(!tab.contents.debugger.isAttached())tab.contents.debugger.attach('1.3');
    tab.attached=true;
    await this.webMcpDeadline(tab.contents.debugger.sendCommand('Page.enable'),5000);
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    await this.webMcpDeadline(tab.contents.debugger.sendCommand('Page.addScriptToEvaluateOnNewDocument',{source:webMcpSource}),5000);
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    const result=await this.webMcpDeadline(tab.contents.debugger.sendCommand('Runtime.evaluate',{expression:webMcpSource}),5000);
    if(result?.exceptionDetails)throw new Error('IAB_WEBMCP_SETUP_FAILED');
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    tab.webMcpReady=true;
  }
  private async webMcp(tab:Tab,method:string,params:Record<string,any>,authorized:()=>boolean):Promise<any> {
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    if(!this.scope(tab.scopeId).webmcp)throw new Error('IAB_WEBMCP_DISABLED');
    const timeout=method==='webmcp_list_tools' ? 5000 : (params.timeout_ms ?? 10000);
    if(!Number.isSafeInteger(timeout) || timeout<1 || timeout>120000)throw new Error('Invalid WebMCP timeout');
    if(method==='webmcp_invoke_tool' && (typeof params.tool_name!=='string' || !params.tool_name.trim() || typeof params.registration_id!=='string' || !params.registration_id.trim() || !Object.hasOwn(params,'input')))throw new Error('Invalid WebMCP invocation');
    await this.setupWebMcp(tab,authorized);
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    const request={source:'open-browser-use-webmcp-bridge',requestId:randomUUID(),action:method==='webmcp_list_tools' ? 'list' : 'invoke',...(method==='webmcp_invoke_tool' ? {tool_name:params.tool_name.trim(),registration_id:params.registration_id.trim(),input:params.input,timeout_ms:timeout} : {})};
    const expression=`new Promise((resolve,reject)=>{const request=${JSON.stringify(request)};const timer=setTimeout(()=>{window.removeEventListener('message',receive);reject(new Error('WebMCP bridge timed out'))},${timeout+1500});function receive(event){const data=event.data;if(event.source!==window || data?.source!=='open-browser-use-webmcp-page' || data.requestId!==request.requestId)return;clearTimeout(timer);window.removeEventListener('message',receive);if(data.ok)resolve(data.result);else reject(new Error(String(data.error || 'WebMCP request failed')))}window.addEventListener('message',receive);window.postMessage(request,'*')})`;
    const result=await this.webMcpDeadline(tab.contents.debugger.sendCommand('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true}),timeout+2000);
    if(!authorized())throw new Error('IAB_AUTH_REVOKED');
    if(result?.exceptionDetails) {const message=result.exceptionDetails.exception?.description;throw new Error(typeof message==='string' && message.includes('WebMCP tool registration is stale') ? 'IAB_WEBMCP_STALE' : 'IAB_WEBMCP_FAILED');}
    const value=result?.result?.value;
    if(!value || typeof value!=='object' || (method==='webmcp_list_tools' ? !Array.isArray(value.tools) : !Object.hasOwn(value,'result')))throw new Error('IAB_WEBMCP_INVALID_RESULT');
    return value;
  }

  private async cdp(tab: Tab, method: string, params: Record<string, any>, authorized: () => boolean, sessionId?: string, visualPoint?: {x: number; y: number}, internalFileCommand = false): Promise<any> {
    if (sessionId && !tab.frameSessions.has(sessionId)) throw new Error('Invalid CDP frame session');
    if (method === 'Target.setAutoAttach') {
      const filter = [{type:'iframe',exclude:false},{exclude:true}];
      if (typeof params.autoAttach !== 'boolean' || params.waitForDebuggerOnStart !== false || params.flatten !== true ||
          (params.autoAttach && JSON.stringify(params.filter) !== JSON.stringify(filter)) ||
          Object.keys(params).some(key => !['autoAttach','waitForDebuggerOnStart','flatten','filter'].includes(key))) throw new Error('Invalid frame auto-attach');
      if (!params.autoAttach && !sessionId) tab.frameSessions.clear();
    } else if (!pageCommands.has(method) && !(internalFileCommand && ['Page.setInterceptFileChooserDialog','DOM.setFileInputFiles'].includes(method))) throw new Error('IAB CDP command is outside page permissions');
    if (params.includeCommandLineAPI) throw new Error('DevTools command-line helpers are not exposed to page grants');
    if (method === 'Page.createIsolatedWorld' && (typeof params.frameId !== 'string' || !params.frameId || params.worldName !== 'open-browser-use-selector' || Object.keys(params).some(key=>!['frameId','worldName'].includes(key)))) throw new Error('Invalid isolated world request');
    if (method === 'Page.navigate') assertUrl(params.url);
    if (method === 'Page.handleJavaScriptDialog' && (typeof params.accept !== 'boolean' || (params.promptText !== undefined && typeof params.promptText !== 'string') || Object.keys(params).some(key => !['accept','promptText'].includes(key)))) throw new Error('Invalid dialog decision');
    if (method === 'Page.close') { await this.closeTab(tab.scopeId, tab.id); return {}; }
    const scroll = method === 'Input.synthesizeScrollGesture' || (method === 'Input.dispatchMouseEvent' && params.type === 'mouseWheel');
    const mouse = method === 'Input.dispatchMouseEvent' || method === 'Input.synthesizeScrollGesture';
    const preparingMouse = mouse && !tab.mouseReady;
    const surface = scroll || preparingMouse ? [...this.surfaceStates.values()].find(item => item.tabId === tab.id) : undefined;
    const backgroundInput = (scroll || preparingMouse) && !!surface && (!surface.window.isVisible() || surface.window.isMinimized());
    if (scroll && !surface) throw new Error('IAB_SCROLL_REQUIRES_PRESENTED_SURFACE');
    let command = method, commandParams = params;
    if (backgroundInput && method === 'Input.synthesizeScrollGesture') {
      if (params.gestureSourceType !== 'mouse' || params.preventFling !== true ||
          Object.keys(params).some(key => !['x','y','xDistance','yDistance','gestureSourceType','preventFling'].includes(key)) ||
          ![params.x,params.y,params.xDistance,params.yDistance].every(Number.isFinite)) throw new Error('IAB_BACKGROUND_SCROLL_UNSUPPORTED_GESTURE');
      command = 'Input.dispatchMouseEvent';
      commandParams = {type:'mouseWheel',x:params.x,y:params.y,deltaX:-params.xDistance,deltaY:-params.yDistance};
    }
    const previousThrottling = backgroundInput ? tab.contents.backgroundThrottling : undefined;
    if (backgroundInput) tab.contents.setBackgroundThrottling(false);
    const bounded = backgroundInput || preparingMouse || command === 'Page.captureScreenshot' || command === 'Page.createIsolatedWorld';
    let expired = false, inputIssued = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeoutError = () => command === 'Page.createIsolatedWorld' ? 'IAB_SELECTOR_CONTEXT_TIMEOUT' : preparingMouse && !inputIssued ? 'IAB_INPUT_PREPARATION_TIMEOUT' : scroll ? 'IAB_BACKGROUND_SCROLL_TIMEOUT' : inputIssued ? 'IAB_INPUT_OUTCOME_UNKNOWN' : 'IAB_SCREENSHOT_TIMEOUT';
    const check = () => { if (expired) throw new Error(timeoutError()); if (!authorized()) throw new Error('IAB_AUTH_REVOKED'); };
    const run = async () => {
      if (!tab.contents.debugger.isAttached()) tab.contents.debugger.attach('1.3');
      tab.attached = true;
      if (command === 'Page.createIsolatedWorld') {
        const tree = await tab.contents.debugger.sendCommand('Page.getFrameTree',{},sessionId);
        check();
        if (this.tabsById.get(tab.id) !== tab || tab.contents.isDestroyed() || (sessionId && !tab.frameSessions.has(sessionId))) throw new Error('Invalid CDP frame session');
        const pending = [tree?.frameTree];let found = false;
        while (pending.length) { const item=pending.pop(); if (!item || typeof item !== 'object') continue; if (item.frame?.id === params.frameId) {found=true;break;} if (Array.isArray(item.childFrames)) pending.push(...item.childFrames); }
        if (!found) throw new Error('Invalid CDP frame');
      }
      if (preparingMouse) {
        await tab.contents.debugger.sendCommand('Page.captureScreenshot', { format: 'png' });
        check();
        tab.mouseReady = true;
      }
      check();
      if (command.startsWith('Input.') && (!sessionId || visualPoint || command !== 'Input.dispatchMouseEvent')) {
        await this.feedbackController.input(tab.contents,command,visualPoint ? {...commandParams,...visualPoint} : sessionId ? {} : commandParams);
      }
      check();
      if (command.startsWith('Input.')) inputIssued = true;
      const result = await tab.contents.debugger.sendCommand(command, commandParams, sessionId);
      if (expired) throw new Error(timeoutError());
      if (backgroundInput) {
        check();
        // Allow Chromium to apply input before restoring hidden-page throttling.
        const painted = await tab.contents.executeJavaScriptInIsolatedWorld(999,[{code:'Promise.race([new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)))), new Promise(resolve => setTimeout(() => resolve(false), 1000))])'}]);
        check();
        if (!painted) throw new Error(timeoutError());
      }
      if (method === 'Page.captureScreenshot') {
        if (typeof result?.data === 'string' && Buffer.byteLength(result.data) > 8 * 1024 * 1024 - 1024) throw new Error('IAB_SCREENSHOT_TOO_LARGE');
        tab.mouseReady = true;
      }
      if (['Page.navigate', 'Page.reload', 'Page.navigateToHistoryEntry'].includes(method)) tab.mouseReady = false;
      return result;
    };
    try {
      if (!bounded) return await run();
      return await Promise.race([run(),new Promise<never>((_,reject) => { timer=setTimeout(() => {
        expired = true;
        try { if (!tab.contents.isDestroyed() && tab.contents.debugger.isAttached()) tab.contents.debugger.detach(); } catch {}
        reject(new Error(timeoutError()));
      },3000); })]);
    } finally {
      if (timer) clearTimeout(timer);
      if (backgroundInput && !tab.contents.isDestroyed()) tab.contents.setBackgroundThrottling(previousThrottling!);
    }
  }
  async configureDownloads(scopeId: string, options: {directory: string; maxBytes: number} | null): Promise<void> {
    const scope=this.scope(scopeId), epoch=++scope.downloadEpoch;
    if (options === null) { scope.download=undefined; this.cancelScopeDownloads(scopeId); return; }
    if (!options || typeof options.directory !== 'string' || !isAbsolute(options.directory) || !Number.isSafeInteger(options.maxBytes) || options.maxBytes < 1 || options.maxBytes > 1_000_000_000) throw new Error('Invalid download configuration');
    const directory=await realpath(options.directory);
    if (!(await stat(directory)).isDirectory()) throw new Error('Download directory is unavailable');
    if (this.scope(scopeId) !== scope || scope.downloadEpoch !== epoch) throw new Error('Download authorization changed');
    this.cancelScopeDownloads(scopeId);
    scope.download={directory,maxBytes:options.maxBytes};
  }

  private cancelScopeDownloads(scopeId: string): void {
    for (const waiter of this.downloadWaits.values()) if (waiter.scopeId === scopeId) waiter.reject(new Error('IAB_AUTH_REVOKED'));
    for (const [id, download] of this.downloads) if (download.scopeId === scopeId) { download.cancel(); download.cleanup(); this.downloads.delete(id); }
  }

  private handleDownload(event: {preventDefault(): void}, item: DownloadItem, contents: WebContents): void {
    const tab=[...this.tabsById.values()].find(candidate => candidate.contents === contents);
    const waiter=tab && this.downloadWaits.get(tab.id), scope=waiter && this.states.get(waiter.scopeId);
    if (!tab || !waiter || !scope || scope.closing || !scope.download || scope.downloadEpoch !== waiter.epoch || !waiter.authorized() || waiter.signal?.aborted) {
      event.preventDefault(); waiter?.reject(new Error('IAB_AUTH_REVOKED')); return;
    }
    if (this.downloads.size >= 128) { event.preventDefault(); waiter.reject(new Error('IAB_DOWNLOAD_LIMIT')); return; }
    this.downloadWaits.delete(tab.id);
    const maxBytes=scope.download.maxBytes;
    let totalBytes: number, filename: string, url: string;
    try { totalBytes=item.getTotalBytes(); filename=item.getFilename(); url=item.getURL(); }
    catch { event.preventDefault(); waiter.reject(new Error('IAB_DOWNLOAD_FAILED')); return; }
    if (totalBytes > maxBytes) { event.preventDefault(); waiter.reject(new Error('IAB_DOWNLOAD_SIZE_LIMIT')); return; }
    const id=randomUUID(), extension=extname(filename).toLowerCase();
    const suffix=/^\.[a-z0-9]{1,12}$/.test(extension) ? extension : '';
    const path=join(scope.download.directory, id + suffix);
    let resolveDone!: (path: string | null) => void, finished=false, expiry: ReturnType<typeof setTimeout> | undefined;
    const done=new Promise<string | null>(resolve => { resolveDone=resolve; });
    const onAbort=() => cancel();
    const onUpdated=() => { try { if (!waiter.authorized() || this.states.get(waiter.scopeId)?.downloadEpoch !== waiter.epoch || item.getReceivedBytes() > maxBytes) cancel(); } catch { cancel(); } };
    const onDone=(_event: unknown, state: string) => { try { finish(state === 'completed' && waiter.authorized() && this.states.get(waiter.scopeId)?.downloadEpoch === waiter.epoch && item.getReceivedBytes() <= maxBytes ? path : null); } catch { finish(null); } };
    const cleanup = () => { if (expiry) clearTimeout(expiry); waiter.signal?.removeEventListener('abort',onAbort); item.removeListener('updated',onUpdated); item.removeListener('done',onDone); };
    const finish = (value: string | null) => {
      if (finished) return;
      finished=true; cleanup(); resolveDone(value);
      expiry=setTimeout(() => { this.downloads.delete(id); }, 300_000); expiry.unref();
    };
    const cancel = () => {
      if (finished) return;
      finish(null);
      setImmediate(() => { try { item.cancel(); } catch {} });
    };
    item.on('updated',onUpdated); item.once('done',onDone); waiter.signal?.addEventListener('abort',onAbort,{once:true});
    this.downloads.set(id,{scopeId:waiter.scopeId,epoch:waiter.epoch,path,done,cancel,cleanup});
    try { item.setSavePath(path); }
    catch { event.preventDefault(); cancel(); this.downloads.delete(id); cleanup(); waiter.reject(new Error('IAB_DOWNLOAD_FAILED')); return; }
    waiter.resolve({downloadId:id,url:url || null});
  }

  private async waitForDownload(scopeId: string, tab: Tab, params: Record<string, any>, authorized: () => boolean, signal?: AbortSignal): Promise<{downloadId: string; url: string | null}> {
    const timeoutMs=params.timeoutMs ?? 10_000, scope=this.scope(scopeId);
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000 || (params.waitId !== undefined && (typeof params.waitId !== 'string' || !/^[0-9a-f-]{36}$/.test(params.waitId)))) throw new Error('Invalid download wait');
    if (!scope.download) throw new Error('IAB_DOWNLOAD_NOT_CONFIGURED');
    if (this.downloadWaits.has(tab.id)) throw new Error('IAB_DOWNLOAD_WAIT_PENDING');
    if (signal?.aborted || !authorized()) throw new Error('IAB_AUTH_REVOKED');
    tab.pending++;
    let resolveEvent!: (value: {downloadId: string; url: string | null}) => void, rejectEvent!: (error: Error) => void;
    const result=new Promise<{downloadId: string; url: string | null}>((resolve,reject)=>{resolveEvent=resolve;rejectEvent=reject;});
    const waiter: DownloadWait={scopeId,tabId:tab.id,epoch:scope.downloadEpoch,authorized,signal,resolve:resolveEvent,reject:rejectEvent};
    this.downloadWaits.set(tab.id,waiter);
    const abort=()=>waiter.reject(new Error('IAB_AUTH_REVOKED'));
    signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(()=>waiter.reject(new Error('IAB_DOWNLOAD_TIMEOUT')),timeoutMs);
    try {
      if (params.waitId) this.emit(scopeId,'onDownloadWaitReady',{waitId:params.waitId});
      return await result;
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort',abort);
      if (this.downloadWaits.get(tab.id) === waiter) this.downloadWaits.delete(tab.id);
      tab.pending--;
    }
  }

  private async downloadPath(scopeId: string, params: Record<string, any>, authorized: () => boolean, signal?: AbortSignal): Promise<{path: string | null}> {
    const download=typeof params.downloadId === 'string' ? this.downloads.get(params.downloadId) : undefined;
    if (!download || download.scopeId !== scopeId) throw new Error('IAB_DOWNLOAD_UNAVAILABLE');
    const timeoutMs=params.timeoutMs ?? 10_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000) throw new Error('Invalid download timeout');
    if (!authorized() || signal?.aborted) throw new Error('IAB_AUTH_REVOKED');
    let timer: ReturnType<typeof setTimeout> | undefined, abort: (()=>void) | undefined;
    try {
      const path=await Promise.race([
        download.done,
        new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error('IAB_DOWNLOAD_TIMEOUT')),timeoutMs);abort=()=>reject(new Error('IAB_AUTH_REVOKED'));signal?.addEventListener('abort',abort,{once:true});}),
      ]);
      if (!authorized() || signal?.aborted || this.states.get(scopeId)?.downloadEpoch !== download.epoch || this.downloads.get(params.downloadId) !== download) throw new Error('IAB_AUTH_REVOKED');
      return {path};
    } finally { if (timer) clearTimeout(timer); if (abort) signal?.removeEventListener('abort',abort); }
  }

  private async clipboardCall(scope: ScopeState, tab: Tab, method: string, params: Record<string, any>, authorized: () => boolean, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const clipboard = this.adapter.clipboard;
    if (!clipboard) throw new Error('IAB_CLIPBOARD_UNAVAILABLE');
    const check = () => { if (!authorized() || signal?.aborted || this.states.get(scope.id) !== scope || scope.closing || this.tabsById.get(tab.id) !== tab) throw new Error('IAB_AUTH_REVOKED'); };
    const maxBytes = 3 * 1024 * 1024;
    const mime = (value: unknown): value is string => typeof value === 'string' && value.length <= 256 && /^(?:web )?[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/i.test(value);
    const output = (value: Record<string, unknown>) => { if (Buffer.byteLength(JSON.stringify(value)) > 4 * 1024 * 1024) throw new Error('IAB_CLIPBOARD_TOO_LARGE'); return value; };
    check();
    if (method === 'readClipboardText') {
      const text = await clipboard.readText(); check();
      if (typeof text !== 'string' || Buffer.byteLength(text) > maxBytes) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
      return output({text});
    }
    if (method === 'writeClipboardText') {
      if (typeof params.text !== 'string') throw new Error('IAB_CLIPBOARD_INVALID');
      if (Buffer.byteLength(params.text) > maxBytes) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
      check(); await clipboard.writeText(params.text); check(); return {};
    }
    if (method === 'readClipboard') {
      const items = await clipboard.read(); check();
      if (!Array.isArray(items) || items.length > 16) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
      let total = 0;
      const result: Array<{entries: Array<Record<string,string>>; presentation_style: string}> = [];
      for (const item of items) {
        if (!Array.isArray(item.types) || item.types.length > 64) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
        const entries: Array<Record<string,string>> = [];
        for (const type of item.types) {
          if (!mime(type)) continue;
          const blob = await item.getType(type); check();
          if (!(blob instanceof Blob)) throw new Error('IAB_CLIPBOARD_INVALID');
          total += blob.size; if (total > maxBytes) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
          if (type.startsWith('text/')) entries.push({mime_type:type,text:await blob.text()});
          else entries.push({mime_type:type,base64:Buffer.from(await blob.arrayBuffer()).toString('base64')});
          check();
        }
        if (entries.length) result.push({entries,presentation_style:'unspecified'});
      }
      return output({items:result});
    }
    if (!Array.isArray(params.items) || params.items.length > 16) throw new Error('IAB_CLIPBOARD_INVALID');
    if (Buffer.byteLength(JSON.stringify(params.items)) > 4 * 1024 * 1024) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
    let total = 0;
    const items: Array<Record<string,Blob>> = [];
    for (const item of params.items) {
      if (!item || !Array.isArray(item.entries) || !item.entries.length || item.entries.length > 64 || (item.presentation_style !== undefined && item.presentation_style !== 'unspecified')) throw new Error('IAB_CLIPBOARD_INVALID');
      const entries: Record<string,Blob> = Object.create(null);
      for (const entry of item.entries) {
        if (!entry || !mime(entry.mime_type) || Object.hasOwn(entries,entry.mime_type) || (typeof entry.text === 'string') === (typeof entry.base64 === 'string') || (entry.text !== undefined && typeof entry.text !== 'string') || (entry.base64 !== undefined && typeof entry.base64 !== 'string')) throw new Error('IAB_CLIPBOARD_INVALID');
        if (typeof entry.base64 === 'string' && !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}(?:==)?|[A-Za-z0-9+/]{3}=?)?$/.test(entry.base64)) throw new Error('IAB_CLIPBOARD_INVALID');
        const bytes = typeof entry.text === 'string' ? Buffer.from(entry.text) : Buffer.from(entry.base64,'base64');
        total += bytes.length; if (total > maxBytes) throw new Error('IAB_CLIPBOARD_TOO_LARGE');
        entries[entry.mime_type] = new Blob([new Uint8Array(bytes)]);
      }
      items.push(entries);
    }
    check(); await clipboard.write(items); check(); return {};
  }

  private invalidateChoosers(tabId: number): void {
    for (const [id, chooser] of this.choosers) if (chooser.tabId === tabId) this.choosers.delete(id);
  }

  async authorizeUploadFiles(scopeId: string, paths: string[]): Promise<void> {
    const scope = this.scope(scopeId), epoch = ++scope.uploadEpoch;
    if (!Array.isArray(paths) || paths.length > 128 || paths.some(path => typeof path !== 'string' || !isAbsolute(path))) throw new Error('Upload paths must be absolute');
    const files = await Promise.all(paths.map(async path => {
      const resolved = await realpath(path);
      if (!(await stat(resolved)).isFile()) throw new Error('Upload path must be a regular file');
      return resolved;
    }));
    if (this.scope(scopeId) !== scope || scope.uploadEpoch !== epoch) throw new Error('Upload authorization changed');
    scope.uploadFiles = new Set(files);
  }

  private async waitForFileChooser(scopeId: string, tab: Tab, params: Record<string, any>, authorized: () => boolean): Promise<any> {
    const timeoutMs = params.timeoutMs ?? 10_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000 || (params.waitId !== undefined && (typeof params.waitId !== 'string' || !/^[0-9a-f-]{36}$/.test(params.waitId)))) throw new Error('Invalid file chooser wait');
    if (this.chooserWaits.has(tab.id)) throw new Error('File chooser already pending');
    this.chooserWaits.add(tab.id); tab.pending++;
    let failure: Error | undefined, settled = false;
    let resolveEvent!: (event: {params: Record<string, any>; sessionId?: string}) => void;
    let rejectEvent!: (error: Error) => void;
    const event = new Promise<{params: Record<string, any>; sessionId?: string}>((resolve,reject) => { resolveEvent=resolve; rejectEvent=reject; });
    void event.catch(() => {});
    const reject = (error: Error) => { if (!settled) { settled=true; failure=error; rejectEvent(error); } };
    const unsubscribe = this.subscribe(message => {
      if (message.scopeId !== scopeId || settled) return;
      if (message.method === 'onDebuggerDetach' && message.params.tabId === tab.id) return reject(new Error('File chooser debugger detached'));
      if (message.method === 'onTabClosed' && message.params.tabId === tab.id) return reject(new Error('File chooser tab closed'));
      if (message.method !== 'onCDPEvent' || message.params.source?.tabId !== tab.id) return;
      const method = message.params.method;
      if (['Page.frameNavigated','Page.frameDetached','Target.attachedToTarget','Target.detachedFromTarget'].includes(method)) return reject(new Error('Frame tree changed while waiting for file chooser'));
      if (method === 'Page.fileChooserOpened') {
        if (!authorized()) return reject(new Error('IAB_AUTH_REVOKED'));
        const data = message.params.params;
        if (!Number.isInteger(data?.backendNodeId) || !['selectSingle','selectMultiple'].includes(data.mode)) return reject(new Error('Invalid file chooser event'));
        settled=true; resolveEvent({params:data,sessionId:message.params.source.sessionId});
      }
    });
    const timer = setTimeout(() => reject(new Error('Timed out waiting for file chooser')), timeoutMs);
    const enabled: Array<string | undefined> = [];
    let active = true, setupFinished = false;
    const setupAuthorized = () => active && authorized();
    try {
      const setup = tab.queue.then(async () => {
        for (const sessionId of [undefined, ...tab.frameSessions.keys()]) {
          await this.cdp(this.tab(scopeId,tab.id),'Page.enable',{},setupAuthorized,sessionId);
          enabled.push(sessionId);
          await this.cdp(this.tab(scopeId,tab.id),'Page.setInterceptFileChooserDialog',{enabled:true},setupAuthorized,sessionId,undefined,true);
        }
      });
      const boundedSetup = Promise.race([setup, event.then(() => setup)]);
      tab.queue=boundedSetup.catch(() => {}); await boundedSetup; setupFinished = true;
      if (failure) throw failure;
      if (!authorized()) throw new Error('IAB_AUTH_REVOKED');
      if (params.waitId) this.emit(scopeId,'onFileChooserWaitReady',{waitId:params.waitId});
      const opened = await event;
      if (!authorized()) throw new Error('IAB_AUTH_REVOKED');
      const id=randomUUID();
      this.choosers.set(id,{scopeId,tabId:tab.id,backendNodeId:opened.params.backendNodeId,sessionId:opened.sessionId,multiple:opened.params.mode==='selectMultiple'});
      return {fileChooserId:id,isMultiple:opened.params.mode==='selectMultiple'};
    } finally {
      active = false;
      clearTimeout(timer); reject(new Error('File chooser wait ended')); unsubscribe();
      if (!setupFinished && !tab.contents.isDestroyed() && tab.contents.debugger.isAttached()) {
        try { tab.contents.debugger.detach(); } catch {}
      }
      try {
        await Promise.all(enabled.map(sessionId => this.cdp(tab,'Page.setInterceptFileChooserDialog',{enabled:false},()=>true,sessionId,undefined,true).catch(() => {})));
      } finally { this.chooserWaits.delete(tab.id); tab.pending--; }
    }
  }

  private async setFileChooserFiles(scopeId: string, params: Record<string, any>, authorized: () => boolean): Promise<void> {
    const id=params.fileChooserId, chooser=typeof id === 'string' ? this.choosers.get(id) : undefined;
    if (!chooser || chooser.scopeId !== scopeId) throw new Error('File chooser is unavailable');
    const scope=this.scope(scopeId), epoch=scope.uploadEpoch;
    if (!Array.isArray(params.files) || !params.files.length || params.files.length > 128 || params.files.some((path: unknown) => typeof path !== 'string' || !isAbsolute(path))) throw new Error('Upload paths must be absolute');
    if (!chooser.multiple && params.files.length > 1) throw new Error('File chooser does not accept multiple files');
    const files=await Promise.all(params.files.map(async (path: string) => {
      const resolved=await realpath(path);
      if (!scope.uploadFiles.has(resolved) || !(await stat(resolved)).isFile()) throw new Error('Upload file is not authorized');
      return resolved;
    }));
    if (!authorized() || this.scope(scopeId) !== scope || scope.uploadEpoch !== epoch) throw new Error('IAB_AUTH_REVOKED');
    if (this.choosers.get(id) !== chooser) throw new Error('File chooser is unavailable');
    const tab=this.tab(scopeId,chooser.tabId);
    this.choosers.delete(id); tab.pending++;
    try { await this.cdp(tab,'DOM.setFileInputFiles',{backendNodeId:chooser.backendNodeId,files},authorized,chooser.sessionId,undefined,true); }
    finally { tab.pending--; }
  }

  async dispatch(scopeId: string, method: string, params: Record<string, any> = {}, operations: readonly Operation[] = ['tabs.read', 'tabs.create', 'page.control'], authorized: () => boolean = () => true, signal?: AbortSignal): Promise<any> {
    this.ensureOpen();
    if (!authorized()) throw new Error('IAB_AUTH_REVOKED');
    const scope = this.scope(scopeId);
    if (params.session_id !== undefined && params.session_id !== scopeId) throw new Error('IAB_SCOPE_MISMATCH');
    const need = (operation: Operation) => { if (!operations.includes(operation)) throw new Error('IAB_OPERATION_DENIED'); };
    switch (method) {
      case 'getInfo': return { name: 'Open Browser Use IAB', type: 'iab', version: '1.1.0', metadata: { instanceId: this.instanceId, scopeId },
        capabilities: { ...(scope.webmcp && operations.includes('page.control') ? {tab:[{id:'webmcp',description:'Fetch and invoke page-defined WebMCP tools.'}]} : {}), multiTab: true, fileUploads: operations.includes('files.upload') && operations.includes('page.control') && scope.uploadFiles.size > 0, downloads: operations.includes('files.download') && operations.includes('page.control') && !!scope.download, clipboard: !!this.adapter.clipboard && operations.includes('page.control') && (operations.includes('clipboard.read') || operations.includes('clipboard.write')), clipboardRead: !!this.adapter.clipboard && operations.includes('page.control') && operations.includes('clipboard.read'), clipboardWrite: !!this.adapter.clipboard && operations.includes('page.control') && operations.includes('clipboard.write'), history: false, childTargets: false } };
      case 'ping': return 'pong';
      case 'setFileChooserFiles': need('page.control'); need('files.upload'); await this.setFileChooserFiles(scopeId,params,authorized); return {};
      case 'downloadPath': need('page.control'); need('files.download'); return this.downloadPath(scopeId,params,authorized,signal);
      case 'getTabs': case 'getUserTabs': need('tabs.read'); return this.listTabs(scopeId);
      case 'createTab': need('tabs.create'); return this.createTab(scopeId, { url: params.url, turnId: params.turn_id },authorized);
      case 'nameSession': need('page.control'); scope.name = String(params.name).slice(0, 200); return { name: scope.name };
      case 'finalizeTabs': {
        need('page.control');
        if (!Array.isArray(params.keep)) throw new Error('keep must be an array');
        const kept = new Map<number, 'handoff' | 'deliverable'>();
        for (const item of params.keep) {
          const tab = this.tab(scopeId, item.tabId ?? item.id);
          if (!['handoff', 'deliverable'].includes(item.status)) throw new Error('Invalid disposition');
          kept.set(tab.id, item.status);
        }
        for (const t of [...scope.tabs.values()]) {
          if (kept.has(t.id)) { t.lifetime = 'persistent'; t.touched.clear(); t.marks.clear(); }
          else if (t.pending === 0) await this.closeTab(scopeId, t.id);
        }
        return this.listTabs(scopeId);
      }
      case 'turnEnded': {
        need('page.control');
        if (typeof params.turn_id !== 'string') throw new Error('turn_id required');
        for (const t of [...scope.tabs.values()]) if (t.touched.delete(params.turn_id)) {
          const mark = t.marks.get(params.turn_id); t.marks.delete(params.turn_id);
          if (mark) t.lifetime = 'persistent';
          if (!mark && t.lifetime === 'temporary' && t.touched.size === 0 && t.pending === 0) await this.closeTab(scopeId, t.id);
        }
        return this.listTabs(scopeId);
      }
    }
    need('page.control');
    const tab = this.tab(scopeId, params.tabId ?? params.target?.tabId);
    if (method === 'getTabPresentation') {
      const surface = [...this.surfaceStates.values()].find(item=>item.tabId === tab.id);
      const window = surface?.window;
      const visible = window && typeof window.isVisible === 'function' && typeof window.isMinimized === 'function' ? window.isVisible() && !window.isMinimized() : null;
      return {backend:'electron',selected:!!surface,visible:surface ? visible : false,windowFocused:window && typeof window.isFocused === 'function' ? window.isFocused() : null};
    }
    if (typeof params.turn_id === 'string') tab.touched.add(params.turn_id);
    if (['readClipboardText','readClipboard','writeClipboardText','writeClipboard'].includes(method)) {
      need(method.startsWith('read') ? 'clipboard.read' : 'clipboard.write');
      tab.pending++;
      try { return await this.clipboardCall(scope,tab,method,params,authorized,signal); } finally { tab.pending--; }
    }
    if (method === 'waitForFileChooser') { need('files.upload'); return this.waitForFileChooser(scopeId,tab,params,authorized); }
    if (method==='webmcp_list_tools' || method==='webmcp_invoke_tool') {
      need('page.control');tab.pending++;
      const run=tab.queue.then(()=>this.webMcp(this.tab(scopeId,tab.id),method,params,authorized));tab.queue=run.catch(()=>{});
      try {return await run;} finally {tab.pending--;}
    }
    if (method === 'waitForDownload') { need('files.download'); return this.waitForDownload(scopeId,tab,params,authorized,signal); }
    if (method === 'markTab') {
      if (!['handoff', 'deliverable'].includes(params.status) || typeof params.turn_id !== 'string') throw new Error('Invalid mark');
      tab.marks.set(params.turn_id, params.status); return {};
    }
    if (method === 'attach') {
      if (!tab.contents.debugger.isAttached()) tab.contents.debugger.attach('1.3'); tab.attached = true; return {};
    }
    if (method === 'detach') { if (tab.attached) tab.contents.debugger.detach(); tab.attached = false; return {}; }
    if (method !== 'executeCdp') throw new Error('IAB method not supported');
    if (typeof params.method !== 'string' || params.sessionId || (params.target?.sessionId !== undefined && (typeof params.target.sessionId !== 'string' || !params.target.sessionId))) throw new Error('Invalid CDP target');
    if (params.visualPoint !== undefined && (!params.target?.sessionId || params.method !== 'Input.dispatchMouseEvent' ||
        !params.visualPoint || !Number.isFinite(params.visualPoint.x) || !Number.isFinite(params.visualPoint.y) || params.visualPoint.x < 0 || params.visualPoint.y < 0)) throw new Error('Invalid visual point');
    tab.pending++;
    const execute = () => {
      if (!authorized()) throw new Error('IAB_AUTH_REVOKED');
      return this.cdp(this.tab(scopeId, tab.id), params.method, params.commandParams ?? {}, authorized, params.target?.sessionId, params.visualPoint);
    };
    // Dialog decisions must bypass an input or evaluation blocked by that dialog.
    const run = params.method === 'Page.handleJavaScriptDialog' ? Promise.resolve().then(execute) : tab.queue.then(execute);
    if (params.method !== 'Page.handleJavaScriptDialog') tab.queue = run.catch(() => {});
    try { return await run; } finally { tab.pending--; }
  }
  readonly surfaces = {
    register: (options: { id: string; window: BaseWindow; owner: WebContents }) => {
      this.ensureOpen();
      if (this.surfaceStates.has(options.id)) throw new Error('Surface already registered');
      const surface: Surface = { ...options, bounds: { x: 0, y: 0, width: 800, height: 600 }, remove: () => {} };
      const unbind = () => {
        const tab = surface.tabId === undefined ? undefined : this.tabsById.get(surface.tabId);
        if (tab) {
          if (!surface.window.isDestroyed?.()) surface.window.contentView.removeChildView(tab.view);
          tab.view.setVisible(false);
          tab.mouseReady = false;
        }
        surface.tabId = undefined;
      };
      const closed = () => { unbind(); this.surfaceStates.delete(options.id); options.window.off('closed', closed); };
      surface.remove = closed; options.window.on('closed', closed); this.surfaceStates.set(options.id, surface);
      return {
        present: (tabId: number) => {
          const tab = this.tabsById.get(tabId); if (!tab) throw new Error('Unknown tab');
          for (const other of this.surfaceStates.values()) if (other !== surface && other.tabId === tabId) throw new Error('Tab is already displayed in another surface');
          unbind(); surface.tabId = tabId; surface.window.contentView.addChildView(tab.view); tab.view.setBounds(surface.bounds); tab.view.setVisible(true); tab.mouseReady = false;
        },
        setBounds: (bounds: Surface['bounds']) => {
          if (Object.values(bounds).some(v => !Number.isSafeInteger(v) || v < 0 || v > 16384) || bounds.width < 1 || bounds.height < 1) throw new Error('Invalid bounds');
          surface.bounds = { ...bounds };
          if (surface.tabId !== undefined) {
            const tab = this.tabsById.get(surface.tabId);
            if (tab) { tab.view.setBounds(surface.bounds); tab.mouseReady = false; }
          }
        },
        hide: unbind,
        dispose: closed,
      };
    },
  };
  async launchClient(options: GrantOptions & { scopeId: string; command: string; args?: string[]; env?: NodeJS.ProcessEnv; transport?: 'private' | 'socket'; stdin?: 'ignore' | 'pipe' }): Promise<{ child: ChildProcess; revoke: () => void }> {
    this.scope(options.scopeId);
    if (options.stdin !== undefined && options.stdin !== 'ignore' && options.stdin !== 'pipe') throw new Error('Invalid client stdin mode');
    const transport = options.transport ?? 'private';
    if (transport === 'socket') await this.connections.openSocket();
    const child = spawn(options.command, options.args ?? [], { env: options.env, stdio: [options.stdin ?? 'ignore', 'pipe', 'pipe', 'pipe'], shell: false });
    let grantId: string | undefined;
    try {
      await once(child, 'spawn'); this.workers.add(child);
      const stream = child.stdio[3] as Duplex;
      stream.on('error', () => {});
      if (transport === 'private') grantId = this.connections.servePrivate(stream, options.scopeId, options).grantId;
      else {
        const bootstrap = this.connections.grant(options.scopeId, transport, options, child.pid);
        grantId = bootstrap.grantId; stream.write(frame({ jsonrpc: '2.0', method: 'iab.bootstrap', params: bootstrap }));
      }
      const revoke = () => { if (grantId) this.connections.revoke(grantId); };
      child.once('exit', () => { revoke(); this.workers.delete(child); });
      return { child, revoke };
    } catch (error) {
      if (grantId) this.connections.revoke(grantId);
      this.workers.delete(child); child.kill(); throw error;
    }
  }
  disposeScope(id: string): Promise<void> {
    const previous = this.scopeDisposals.get(id);
    if (previous) return previous;
    const scope = this.states.get(id);
    if (!scope) return Promise.resolve();
    scope.closing = true; this.connections.revokeScope(id); this.cancelScopeDownloads(id);
    const done = (async () => {
      // Closing an opener may synchronously destroy its popup as well.
      for (const tab of [...scope.tabs.values()]) await this.destroyTab(tab);
      this.states.delete(id);
    })().finally(() => this.scopeDisposals.delete(id));
    this.scopeDisposals.set(id, done); return done;
  }
  dispose(): Promise<void> {
    if (!this.disposing) this.disposing = this.finishDispose();
    return this.disposing;
  }
  private async finishDispose(): Promise<void> {
    if (this.closed) return;
    await this.connections.dispose();
    for (const worker of this.workers) worker.kill(); this.workers.clear();
    for (const id of [...this.states.keys()]) await this.disposeScope(id);
    for (const surface of this.surfaceStates.values()) surface.remove();
    for (const remove of this.sessionRemovers) remove(); this.sessionRemovers = [];
    this.profileSessions.clear();
    this.closed = true; this.events.removeAllListeners();
  }
}
export class IabScope {
  constructor(private runtime: IabRuntime, readonly id: string) {}
  readonly tabs = {
    create: (options: { url?: string; turnId?: string } = {}) => this.runtime.createTab(this.id, options),
    list: () => this.runtime.listTabs(this.id),
    close: (id: number) => this.runtime.closeTab(this.id, id),
  };
  readonly visualFeedback = {
    setActive: (tabId: number,active: boolean) => this.runtime.setFeedbackActive(this.id,tabId,active),
  };
  readonly files = { authorize: (paths: string[]) => this.runtime.authorizeUploadFiles(this.id, paths) };
  readonly downloads = { configure: (options: {directory: string; maxBytes: number} | null) => this.runtime.configureDownloads(this.id, options) };
  call(method: string, params: Record<string, any> = {}): Promise<any> { return this.runtime.dispatch(this.id, method, params, ['tabs.read','tabs.create','page.control','files.upload','files.download','clipboard.read','clipboard.write']); }
  dispose(): Promise<void> { return this.runtime.disposeScope(this.id); }
}
