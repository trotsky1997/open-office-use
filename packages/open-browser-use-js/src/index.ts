import { Socket, createConnection } from "node:net";
import { endianness } from "node:os";
import { createHash, randomUUID } from "node:crypto";
import { types } from "node:util";
import { isAbsolute } from "node:path";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type BrowserUseRequestParams = { [key: string]: JsonValue };

export type OpenBrowserUseClientOptions = {
  socketPath: string;
  sessionId?: string;
  turnId?: string;
  timeoutMs?: number;
};

type PendingRequest = {
  resolve: (value: JsonValue) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
};

export type OpenBrowserUseNotification = {
  method: string;
  params?: JsonValue;
};

export type NotificationHandler = (notification: OpenBrowserUseNotification) => void;

const headerBytes = 4;
const defaultNavigationTimeoutMs = 10_000;

export type OpenBrowserUseLoadState = "domcontentloaded" | "load";
export type OpenBrowserUseWaitUntil = OpenBrowserUseLoadState | "commit";

export type OpenBrowserUseGotoOptions = {
  waitUntil?: OpenBrowserUseLoadState;
  timeoutMs?: number;
};

export type OpenBrowserUseWaitForLoadStateOptions = {
  state?: OpenBrowserUseLoadState;
  timeoutMs?: number;
};

export type OpenBrowserUseBrowserOptions = OpenBrowserUseClientOptions | { client: OpenBrowserUseClient };

export type InteractiveNode = { index: number; role: string; name: string; frameId?: string; level?: number; checked?: boolean | "mixed"; disabled?: boolean; pressed?: boolean | "mixed"; selected?: boolean; expanded?: boolean; placeholder?: string; placeholderTruncated?: boolean; altText?: string; altTextTruncated?: boolean; value?: string | number; valueRedacted?: boolean; valueUnavailable?: boolean; valueTruncated?: boolean };
export type SelectOption = string | {value?: string; label?: string; index?:number};
export type OpenBrowserUseDialogInfo = { id: string; type: "alert" | "confirm" | "prompt" | "beforeunload"; message: string; url: string; defaultPrompt?: string };
export type OpenBrowserUseLogEntry = {level: "debug" | "info" | "log" | "warn" | "error"; message: string; timestamp: string; url?: string};
export type OpenBrowserUseClipboardEntry = {mimeType: string; text?: string; base64?: string};
export type OpenBrowserUseClipboardItem = {entries: OpenBrowserUseClipboardEntry[]; presentationStyle?: "unspecified" | "inline" | "attachment"};
export type OpenBrowserUseTabPresentation = {backend:"chrome" | "electron"; selected:boolean; visible:boolean | null; windowFocused:boolean | null};
export type TextMatcher = string | RegExp;
export type LocatorLocatorOptions = {hasText?:TextMatcher; hasNotText?:TextMatcher; has?:OpenBrowserUseCssLocator; hasNot?:OpenBrowserUseCssLocator};
export type RoleLocatorOptions = {name?: TextMatcher; exact?: boolean; level?: number; checked?: boolean; disabled?: boolean; pressed?: boolean; selected?: boolean; expanded?: boolean};
export type InteractiveState = { snapshotId: string; nodes: InteractiveNode[]; text: string; textMode: "full" | "diff"; truncated: boolean; frameCoverage?: "same-process" | "cross-process"; unavailableFrames?: string[]; valuesTruncated?: boolean };
type FrameInfo = { id: string; parentId?: string; loaderId: string; url: string; sessionId?: string };
type SelectSpec = {value?:string; label?:string; index?:number; either:boolean};
function selectSpecs(values: SelectOption | SelectOption[]): SelectSpec[] {
  return (Array.isArray(values) ? values : [values]).map(value => {
    if (typeof value === "string") return {value,label:value,either:true};
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key=>!["value","label","index"].includes(key)) ||
        (value.value === undefined && value.label === undefined && value.index === undefined) || (value.value !== undefined && typeof value.value !== "string") || (value.label !== undefined && typeof value.label !== "string") || (value.index !== undefined && (!Number.isSafeInteger(value.index) || value.index<0))) throw new Error("Invalid select option");
    return {...value,either:false};
  });
}
async function locatorReadBeforeDeadline<T>(read: Promise<T>, timeoutMs: number, deadline: number, message: string): Promise<T> {
  if (timeoutMs === 0) return await read;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout=()=>new Error(message);
  try {
    const result=await Promise.race([read,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(timeout()),Math.max(0,deadline-performance.now()));})]);
    if (performance.now()>=deadline) throw timeout();
    return result;
  } finally { if (timer) clearTimeout(timer); }
}
function testIdSelector(testId: string): string {
  if (typeof testId !== "string" || testId.length > 500 || /[\u0000\ud800-\udfff]/u.test(testId)) throw new Error("Invalid test id");
  return `[data-testid="${Array.from(testId,char=>`\\${char.codePointAt(0)!.toString(16)} `).join("")}"]`;
}
function applyLocatorOptions(locator:OpenBrowserUseCssLocator, options?:LocatorLocatorOptions):OpenBrowserUseCssLocator {
  if (options === undefined) return locator;
  if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key=>!["hasText","hasNotText","has","hasNot"].includes(key))) throw new Error("Invalid locator options");
  return Object.values(options).every(value=>value === undefined) ? locator : locator.filter(options);
}
type LocatorClickOptions = {timeoutMs?:number; button?:"left" | "middle" | "right"; modifiers?:Array<"Alt" | "Control" | "ControlOrMeta" | "Meta" | "Shift">; force?:boolean};
type LocatorCheckOptions = {timeoutMs?:number; force?:boolean};
function validateCheckOptions(options:LocatorCheckOptions):void {
  if(!options || typeof options!=="object" || Array.isArray(options) || Object.keys(options).some(key=>!["timeoutMs","force"].includes(key)) || (options.force!==undefined && typeof options.force!=="boolean"))throw new Error("Invalid locator check options");
}
type MouseClick = {button:"left" | "middle" | "right"; buttons:number; modifiers:number; force?:boolean};
function locatorClickOptions(options:LocatorClickOptions):MouseClick {
  if (!options || typeof options!=="object" || Array.isArray(options) || Object.keys(options).some(key=>!["timeoutMs","button","modifiers","force"].includes(key)) || (options.force!==undefined && typeof options.force!=="boolean")) throw new Error("Invalid locator click options");
  const button=options.button ?? "left", masks={left:1,middle:4,right:2};
  if (!Object.hasOwn(masks,button)) throw new Error("Invalid mouse button");
  return {button,buttons:masks[button],modifiers:cuaModifiers(options.modifiers),...(options.force ? {force:true} : {})};
}
type CssMatcher = string | {source:string; flags:string};
type CssTextFilter = {title?:{matcher:CssMatcher;exact:boolean}; hasText?:CssMatcher; hasNotText?:CssMatcher; has?:readonly CssStep[]; hasNot?:readonly CssStep[]; and?:readonly CssStep[]; visible?:boolean};
type CssStep = {selector:string; position?:number; before?:readonly CssTextFilter[]; after?:readonly CssTextFilter[]; union?:readonly [readonly CssStep[],readonly CssStep[]]};
type SemanticRoot = {scope:OpenBrowserUseRoleLocator; roots:Array<{backendNodeId:number; frameId:string}>};
type DomIdentity = {tag:string;role:string | null;name:string | null;type:string | null;disabled:boolean;checked:boolean | "mixed" | null};
const inputValueFunction = `function(){if(this instanceof HTMLInputElement && this.type==='password')return {error:'redacted'};if(!(this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement || this instanceof HTMLSelectElement))return {error:'unsupported'};return {value:this.value.slice(0,30001)}}`;
const editableFunction = `function(role){
  if(!(this instanceof Element) || !this.isConnected)return null;
  const native=this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement || this instanceof HTMLSelectElement;
  const supported=['checkbox','combobox','grid','gridcell','listbox','radiogroup','slider','spinbutton','textbox','columnheader','rowheader','searchbox','switch','treegrid'];
  const ariaRole=(role || this.getAttribute('role') || '').trim().split(/\\s+/)[0];
  const aria=supported.includes(ariaRole);
  if(!native && !aria && !this.isContentEditable)return {error:'not-editable'};
  for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null))if(el.matches(':disabled') || el.getAttribute('aria-disabled')?.toLowerCase()==='true')return {value:false};
  const readonly=native ? this.hasAttribute('readonly') : aria && this.getAttribute('aria-readonly')?.toLowerCase()==='true';
  return {value:!readonly};
}`;
const domIdentityFunction = `function(){
  if(!this.isConnected)return null;
  const root=this.getRootNode(),references=(this.getAttribute('aria-labelledby') || '').trim().split(/\\s+/).filter(Boolean).map(id=>root.getElementById?.(id)?.textContent || '').join(' ').trim();
  const labels=this.labels ? Array.from(this.labels,label=>label.textContent || '').join(' ').trim() : '';
  const name=references || this.getAttribute('aria-label') || labels || this.getAttribute('alt') || this.getAttribute('title') || this.getAttribute('placeholder') || this.innerText || '';
  let disabled=false;for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null))if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true'){disabled=true;break}
  const aria=this.getAttribute('aria-checked');let checked=null;
  if(this instanceof HTMLInputElement && ['checkbox','radio'].includes(this.type))checked=this.indeterminate ? 'mixed' : this.checked;
  else if(['true','false','mixed'].includes(aria))checked=aria==='mixed' ? 'mixed' : aria==='true';
  return {tag:this.tagName.toLowerCase(),role:this.getAttribute('role')?.slice(0,200) ?? null,name:name.replace(/\\s+/g,' ').trim().slice(0,500) || null,type:(this instanceof HTMLInputElement || this instanceof HTMLButtonElement ? this.type : this.getAttribute('type'))?.slice(0,100) ?? null,disabled,checked};
}`;
type DomClip = {left:number;top:number;right:number;bottom:number};
type CssSnapshot = { frameId?:string; step:CssStep; scopes:readonly CssStep[]; scopeIds:number[][]; framePath?:readonly string[]; semantic?:SemanticRoot; frame:FrameInfo | null; frames:FrameInfo[]; documentId:number; ids:number[] };
type CssGuard = {snapshot:CssSnapshot; scopeId:number};
type RoleGuard = {locator:OpenBrowserUseRoleLocator; expected:Array<{backendNodeId:number; frameId:string}>};
type LocatorMatch = {node:InteractiveNode; path:number[]; filters:FilterGuard[]; css?:CssGuard};
type ObservedNode = InteractiveNode & { backendNodeId: number; stateKey: string; axOrder?:number; frameChain?: FrameInfo[] };
const supplementalRoles = ["heading", "StaticText", "image", "dialog", "alertdialog", "group", "list", "listitem", "table", "row", "cell", "columnheader", "rowheader", "grid", "gridcell", "tree", "treeitem", "navigation", "main", "region", "form", "article"];
type TextFilter = { visible?:boolean; hasText?: TextMatcher; hasNotText?: TextMatcher; has?:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator; hasNot?:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator };
type LogCapture = {generation: number; entries: OpenBrowserUseLogEntry[]; sessions: Map<string,Promise<void>>; ready?: Promise<void>};
type FilterGuard = { index: number; filters: TextFilter[] };
type UnindexedText = { backendNodeId?: number; ancestors:number[]; name:string; axOrder:number; frameId?: string; frameChain?: FrameInfo[] };
type Observation = { id: string; documentId: number; nodes: ObservedNode[]; unindexedText: UnindexedText[]; frames?:FrameInfo[]; guards: Map<number,{scopes:number[]; filters:FilterGuard[]; framePath?:string[]; css?:CssGuard; role?:RoleGuard}> };
class RetryablePreflightError extends Error {}
function unindexedTextAncestors(tree: JsonValue): UnindexedText[] {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) return [];
  const nodes = tree.nodes.filter(isObject);
  const byId = new Map(nodes.filter(node => typeof node.nodeId === "string").map(node => [node.nodeId,node]));
  return tree.nodes.flatMap((node,axOrder) => {
    if (!isObject(node) || node.ignored === true || !isObject(node.role) || node.role.value !== "StaticText" || !isObject(node.name) || typeof node.name.value !== "string" || !node.name.value || typeof node.backendDOMNodeId === "number") return [];
    const seen = new Set<string>(), ancestors:number[]=[];let parent = node.parentId;
    while (typeof parent === "string" && !seen.has(parent)) {
      seen.add(parent);const ancestor = byId.get(parent);if (!ancestor) break;
      if (typeof ancestor.backendDOMNodeId === "number") ancestors.push(ancestor.backendDOMNodeId);
      parent = ancestor.parentId;
    }
    return [{...(ancestors.length ? {backendNodeId:ancestors[0]} : {}),ancestors,name:node.name.value,axOrder}];
  });
}
function matchesTextFilters(text: string, filters: TextFilter[]): boolean {
  const matches = (value: TextMatcher) => typeof value === "string" ? text.toLowerCase().includes(value.replace(/\s+/g," ").trim().toLowerCase()) : new RegExp(value.source,value.flags).test(text);
  return filters.every(filter => (filter.hasText === undefined || matches(filter.hasText)) && (filter.hasNotText === undefined || !matches(filter.hasNotText)));
}

function copyMatcher(value: TextMatcher): TextMatcher { return typeof value === "string" ? value : new RegExp(value.source,value.flags); }

function browserLogEntry(method: string, params: {[key:string]:JsonValue}): OpenBrowserUseLogEntry | null {
  const browserEntry = method === "Log.entryAdded" && isObject(params.entry) ? params.entry : undefined;
  if (method === "Log.entryAdded" && !browserEntry) return null;
  const details = isObject(params.exceptionDetails) ? params.exceptionDetails : undefined;
  const exception = details && isObject(details.exception) ? details.exception : undefined;
  const kind = method === "Runtime.exceptionThrown" ? "error" : browserEntry?.level ?? params.type;
  const level: OpenBrowserUseLogEntry["level"] = kind === "warning" || kind === "warn" ? "warn" : kind === "error" || kind === "assert" ? "error" : kind === "verbose" ? "debug" : kind === "debug" || kind === "info" ? kind : "log";
  const message = browserEntry ? String(browserEntry.text ?? "") : method === "Runtime.exceptionThrown"
    ? String(exception?.description ?? exception?.value ?? details?.text ?? "Uncaught exception")
    : Array.isArray(params.args) ? params.args.slice(0,50).map(arg => isObject(arg) ? String(arg.value ?? arg.unserializableValue ?? arg.description ?? "[object]").slice(0,4096) : "[object]").join(" ") : "";
  const trace = isObject(params.stackTrace) && Array.isArray(params.stackTrace.callFrames) ? params.stackTrace.callFrames[0] : undefined;
  const url = typeof browserEntry?.url === "string" ? browserEntry.url : typeof details?.url === "string" ? details.url : isObject(trace) && typeof trace.url === "string" ? trace.url : undefined;
  return {level,message:message.slice(0,4096),timestamp:new Date().toISOString(),...(url ? {url:url.slice(0,4096)} : {})};
}


export class OpenBrowserUseClient {
  readonly socketPath: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly timeoutMs: number;
  #socket: Socket | null = null;
  #connection: Promise<void> | null = null;
  #pendingData = Buffer.alloc(0);
  #nextId = 1;
  #pending = new Map<string, PendingRequest>();
  #notificationHandlers = new Set<NotificationHandler>();
  #disconnectHandlers = new Set<(error: Error) => void>();
  #generation = 0;

  get connectionGeneration(): number { return this.#generation; }
  get isConnected(): boolean { return this.#socket !== null && this.#connection === null; }

  constructor(options: OpenBrowserUseClientOptions) {
    this.socketPath = options.socketPath;
    this.sessionId = options.sessionId ?? "open-browser-use-js";
    this.turnId = options.turnId ?? `turn-${Date.now()}`;
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  async connect(): Promise<this> {
    if (this.#socket) {
      if (this.#connection) await this.#connection;
      return this;
    }
    const socket = createConnection(this.socketPath);
    this.#socket = socket;
    socket.on("data", (chunk) => this.#handleData(Buffer.from(chunk)));
    socket.on("close", () => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      this.#generation++;
      this.#pendingData = Buffer.alloc(0);
      const error = new Error("Open Browser Use socket closed");
      this.#rejectAll(error);
      this.emitDisconnect(error);
    });
    socket.on("error", (error) => { if (this.#socket === socket) this.#rejectAll(error); });
    const connection = new Promise<void>((resolve, reject) => {
      const cleanup = () => { socket.off("connect", connected); socket.off("error", failed); socket.off("close", closed); };
      const connected = () => { cleanup(); resolve(); };
      const failed = (error: Error) => { cleanup(); reject(error); };
      const closed = () => failed(new Error("Open Browser Use socket closed before connecting"));
      socket.once("connect", connected);
      socket.once("error", failed);
      socket.once("close", closed);
    });
    this.#connection = connection;
    try { await connection; this.#generation++; } catch (error) {
      if (this.#socket === socket) { this.#socket = null; this.#pendingData = Buffer.alloc(0); }
      socket.destroy();
      throw error;
    } finally { if (this.#connection === connection) this.#connection = null; }
    return this;
  }

  close(): void {
    if (this.#socket) this.#generation++;
    this.#socket?.destroy();
    this.#socket = null;
    this.#connection = null;
    this.#pendingData = Buffer.alloc(0);
    const error = new Error("Open Browser Use socket closed");
    this.#rejectAll(error);
    this.emitDisconnect(error);
  }

  onDisconnect(handler: (error: Error) => void): () => void {
    this.#disconnectHandlers.add(handler);
    return () => { this.#disconnectHandlers.delete(handler); };
  }

  protected emitDisconnect(error: Error): void {
    for (const handler of this.#disconnectHandlers) handler(error);
  }

  onNotification(handler: NotificationHandler): () => void {
    this.#notificationHandlers.add(handler);
    return () => {
      this.#notificationHandlers.delete(handler);
    };
  }

  async request(method: string, params: BrowserUseRequestParams = {}, expectedGeneration?: number, requestTimeoutMs = this.timeoutMs): Promise<JsonValue> {
    await this.connect();
    if (expectedGeneration !== undefined && expectedGeneration !== this.#generation) throw new Error("Connection changed; observe again");
    const socket = this.#socket;
    if (!socket) {
      throw new Error("Open Browser Use socket is not connected");
    }
    const id = String(this.#nextId++);
    const mergedParams = {
      session_id: this.sessionId,
      turn_id: this.turnId,
      ...params
    };
    const message = {
      jsonrpc: "2.0",
      id,
      method,
      params: mergedParams
    };
    const payload = encodeFrame(message);
    const promise = new Promise<JsonValue>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`Open Browser Use request timed out: ${method}`));
      }, requestTimeoutMs);
      this.#pending.set(id, { resolve, reject, timeout });
    });
    socket.write(payload);
    return await promise;
  }

  getInfo(): Promise<JsonValue> {
    return this.request("getInfo");
  }

  createTab(): Promise<JsonValue> {
    return this.request("createTab");
  }

  getTabs(): Promise<JsonValue> {
    return this.request("getTabs");
  }

  getUserTabs(): Promise<JsonValue> {
    return this.request("getUserTabs");
  }

  getUserHistory(params: BrowserUseRequestParams = {}): Promise<JsonValue> {
    return this.request("getUserHistory", params);
  }

  claimUserTab(tabId: number): Promise<JsonValue> {
    return this.request("claimUserTab", { tabId });
  }

  finalizeTabs(keep: JsonValue[]): Promise<JsonValue> {
    return this.request("finalizeTabs", { keep });
  }

  nameSession(name: string): Promise<JsonValue> {
    return this.request("nameSession", { name });
  }

  attach(tabId: number, requestTimeoutMs = this.timeoutMs): Promise<JsonValue> {
    return this.request("attach", { tabId },undefined,requestTimeoutMs);
  }

  detach(tabId: number): Promise<JsonValue> {
    return this.request("detach", { tabId });
  }

  executeCdp(tabId: number, method: string, commandParams: BrowserUseRequestParams = {}): Promise<JsonValue> {
    return this.request("executeCdp", {
      target: { tabId },
      method,
      commandParams
    });
  }

  moveMouse(tabId: number, x: number, y: number, waitForArrival = true): Promise<JsonValue> {
    return this.request("moveMouse", { tabId, x, y, waitForArrival });
  }

  waitForFileChooser(tabId: number, timeoutMs?: number): Promise<JsonValue> {
    return this.request("waitForFileChooser", {
      tabId,
      ...(timeoutMs === undefined ? {} : { timeoutMs })
    });
  }

  setFileChooserFiles(fileChooserId: string, files: string[]): Promise<JsonValue> {
    return this.request("setFileChooserFiles", { fileChooserId, files });
  }

  waitForDownload(tabId: number, timeoutMs?: number): Promise<JsonValue> {
    return this.request("waitForDownload", {
      tabId,
      ...(timeoutMs === undefined ? {} : { timeoutMs })
    });
  }

  downloadPath(downloadId: string, timeoutMs?: number): Promise<JsonValue> {
    return this.request("downloadPath", {
      downloadId,
      ...(timeoutMs === undefined ? {} : { timeoutMs })
    }, undefined, typeof timeoutMs === "number" && Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.max(this.timeoutMs, timeoutMs + 2000) : this.timeoutMs);
  }

  browserUserHistory(params: BrowserUseRequestParams = {}): Promise<JsonValue> {
    return this.getUserHistory(params);
  }

  readClipboardText(tabId: number): Promise<JsonValue> {
    return this.request("readClipboardText", { tabId });
  }

  writeClipboardText(tabId: number, text: string): Promise<JsonValue> {
    return this.request("writeClipboardText", { tabId, text });
  }

  readClipboard(tabId: number): Promise<JsonValue> {
    return this.request("readClipboard", { tabId });
  }

  writeClipboard(tabId: number, items: JsonValue[]): Promise<JsonValue> {
    return this.request("writeClipboard", { tabId, items });
  }

  turnEnded(): Promise<JsonValue> {
    return this.request("turnEnded");
  }

  #handleData(chunk: Buffer): void {
    this.#pendingData = Buffer.concat([this.#pendingData, chunk]);
    while (this.#pendingData.length >= headerBytes) {
      const length =
        endianness() === "LE"
          ? this.#pendingData.readUInt32LE(0)
          : this.#pendingData.readUInt32BE(0);
      const total = headerBytes + length;
      if (this.#pendingData.length < total) {
        return;
      }
      const payload = this.#pendingData.subarray(headerBytes, total);
      this.#pendingData = this.#pendingData.subarray(total);
      this.#handleMessage(JSON.parse(payload.toString("utf8")) as JsonValue);
    }
  }

  #handleMessage(message: JsonValue): void {
    if (!isObject(message)) {
      return;
    }
    const id = typeof message.id === "string" || typeof message.id === "number" ? String(message.id) : null;
    if (!id && typeof message.method === "string") {
      const notification = {
        method: message.method,
        params: message.params
      };
      for (const handler of this.#notificationHandlers) {
        handler(notification);
      }
      return;
    }
    if (!id) {
      return;
    }
    const pending = this.#pending.get(id);
    if (!pending) {
      return;
    }
    this.#pending.delete(id);
    clearTimeout(pending.timeout);
    if (isObject(message.error)) {
      pending.reject(new Error(String(message.error.message ?? "Open Browser Use request failed")));
      return;
    }
    pending.resolve((message.result ?? null) as JsonValue);
  }

  #rejectAll(error: Error): void {
    for (const [id, pending] of this.#pending) {
      this.#pending.delete(id);
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
  }
}

export async function connectOpenBrowserUse(options: OpenBrowserUseBrowserOptions): Promise<OpenBrowserUseBrowser> {
  const browser = new OpenBrowserUseBrowser(options);
  await browser.connect();
  return browser;
}

type BrowserTabInfo = {id:string;title?:string;url?:string;active?:boolean;openerTabId?:string};
type BrowserUserTabInfo = {id:string;title?:string;url?:string;lastOpened?:string;tabGroup?:string};
export type BrowserHistoryEntry = {url:string;dateVisited:string;title?:string};
function browserTabId(value:unknown):number {
  const raw=value instanceof OpenBrowserUseTab ? value.id : value && typeof value==='object' && 'id' in value ? value.id : value;
  if(typeof raw==='number' && Number.isSafeInteger(raw) && raw>0)return raw;
  if(typeof raw==='string' && /^[1-9][0-9]*$/.test(raw) && Number.isSafeInteger(Number(raw)))return Number(raw);
  throw new Error('Invalid tab ID');
}
function browserTabs(value:JsonValue):BrowserTabInfo[] {
  if(!Array.isArray(value))throw new Error('Browser returned an invalid tab list');
  const ids=new Set<number>();return value.map(item=>{
    if(!isObject(item))throw new Error('Browser returned an invalid tab');
    const id=browserTabId(item.id);if(ids.has(id))throw new Error('Browser returned duplicate tab IDs');ids.add(id);
    if((item.title!==undefined && item.title!==null && typeof item.title!=='string') || (item.url!==undefined && item.url!==null && typeof item.url!=='string') || (item.active!==undefined && typeof item.active!=='boolean'))throw new Error('Browser returned an invalid tab');
    return {id:String(id),...(typeof item.title==='string' ? {title:item.title} : {}),...(typeof item.url==='string' ? {url:item.url} : {}),...(typeof item.active==='boolean' ? {active:item.active} : {}),...(item.openerTabId == null ? {} : {openerTabId:String(browserTabId(item.openerTabId))})};
  });
}

export class OpenBrowserUseBrowser {
  readonly client: OpenBrowserUseClient;
  readonly cdp: OpenBrowserUseCdp;
  browserId?:string;
  readonly tabs: OpenBrowserUseTabs;
  readonly capabilities:OpenBrowserUseCapabilities;
  readonly user: OpenBrowserUseBrowserUser;
  #domCua = new Map<number,WeakRef<OpenBrowserUseTabDomCUA>>();
  #popupWaits = new Set<number>();

  constructor(options: OpenBrowserUseBrowserOptions) {
    this.client = "client" in options ? options.client : new OpenBrowserUseClient(options);
    this.cdp = new OpenBrowserUseCdp(this.client);
    this.tabs = new OpenBrowserUseTabs(this);
    this.capabilities = new OpenBrowserUseCapabilities(this);
    this.user = new OpenBrowserUseBrowserUser(this);
  }

  async connect(): Promise<this> {
    await this.client.connect();
    return this;
  }

  close(): void {
    this.client.close();
  }

  async nameSession(name:string):Promise<void> {
    if(typeof name!=='string' || !name.trim() || name.length>200)throw new Error('Invalid session name');
    await this.client.nameSession(name);
  }

  async newTab(options: OpenBrowserUseGotoOptions & { url?: string } = {}): Promise<OpenBrowserUseTab> {
    const created = await this.client.createTab();
    const tabId = tabIdFromValue(created, "createTab response");
    const tab = this.tab(tabId);
    if (options.url) {
      try { await tab.goto(options.url, options); }
      catch (error) {
        try { await tab.close(); }
        catch (cleanupError) { throw new AggregateError([error,cleanupError],"Navigation failed and cleanup of the new tab could not be confirmed"); }
        throw error;
      }
    }
    return tab;
  }

  tab(tabId: number): OpenBrowserUseTab {
    return new OpenBrowserUseTab(this, tabId);
  }

  /** @internal */
  domCuaFor(tab:OpenBrowserUseTab):OpenBrowserUseTabDomCUA {
    const existing=this.#domCua.get(tab.id)?.deref();
    if(existing)return existing;
    const dom=new OpenBrowserUseTabDomCUA(tab);this.#domCua.set(tab.id,new WeakRef(dom));return dom;
  }

  /** @internal */
  beginPopupWait(tabId:number):()=>void {
    if(this.#popupWaits.has(tabId))throw new Error("A popup expectation is already active for this tab");
    this.#popupWaits.add(tabId);return ()=>{this.#popupWaits.delete(tabId);};
  }

  getTabs(): Promise<JsonValue> {
    return this.client.getTabs();
  }

  getUserTabs(): Promise<JsonValue> {
    return this.client.getUserTabs();
  }

  async claimTab(tabId: number): Promise<OpenBrowserUseTab> {
    if (!Number.isSafeInteger(tabId) || tabId < 1) throw new Error("A valid tab ID is required");
    const claimed = await this.client.claimUserTab(tabId);
    if (tabIdFromValue(claimed, "claimUserTab response") !== tabId) throw new Error("Browser claimed a different tab");
    return this.tab(tabId);
  }
}

export class OpenBrowserUseTabs {
  constructor(private browser:OpenBrowserUseBrowser) {}
  async list():Promise<BrowserTabInfo[]> { return browserTabs(await this.browser.getTabs()); }
  async get(id:string | number):Promise<OpenBrowserUseTab> {
    const tabId=browserTabId(id),tabs=await this.list();
    if(!tabs.some(tab=>tab.id===String(tabId)))throw new Error('Tab is outside this browser session');
    return this.browser.tab(tabId);
  }
  async getByUrl(url:string):Promise<OpenBrowserUseTab> {
    if(typeof url!=="string" || !url || url.length>8192)throw new Error("Invalid tab URL");
    const matches=(await this.list()).filter(tab=>tab.url===url);
    if(matches.length!==1)throw new Error(matches.length ? "Multiple session tabs match the URL" : "No session tab matches the URL");
    return this.browser.tab(browserTabId(matches[0].id));
  }
  new():Promise<OpenBrowserUseTab> { return this.browser.newTab(); }
  async selected():Promise<OpenBrowserUseTab | undefined> {
    const selected=(await this.list()).filter(tab=>tab.active===true);
    if(selected.length>1)throw new Error('Multiple session tabs are selected');
    return selected.length ? this.browser.tab(browserTabId(selected[0].id)) : undefined;
  }
  async finalize(options:{keep?:Array<{status:'handoff' | 'deliverable';tab:string | number | OpenBrowserUseTab | BrowserTabInfo}>} = {}):Promise<void> {
    if(!options || typeof options!=='object' || Array.isArray(options) || Object.keys(options).some(key=>key!=='keep') || (options.keep!==undefined && !Array.isArray(options.keep)))throw new Error('Invalid tab finalization options');
    const seen=new Set<number>(),keep=(options.keep ?? []).map(item=>{
      if(!item || !['handoff','deliverable'].includes(item.status) || (item.tab instanceof OpenBrowserUseTab && item.tab.browser!==this.browser))throw new Error('Invalid kept tab');
      const tabId=browserTabId(item.tab);if(seen.has(tabId))throw new Error('Duplicate kept tab');seen.add(tabId);return {tabId,status:item.status};
    });
    await this.browser.client.finalizeTabs(keep);
  }
}

export class OpenBrowserUseBrowserUser {
  constructor(private browser:OpenBrowserUseBrowser) {}
  async openTabs():Promise<BrowserUserTabInfo[]> {
    const result=await this.browser.getUserTabs();if(!Array.isArray(result))throw new Error('Browser returned an invalid user tab list');
    return result.map(item=>{
      if(!isObject(item))throw new Error('Browser returned an invalid user tab');
      const id=String(browserTabId(item.id));
      for(const key of ['title','url','lastOpened','tabGroup'])if(item[key]!==undefined && item[key]!==null && typeof item[key]!=='string')throw new Error('Browser returned an invalid user tab');
      return {id,...(typeof item.title==='string' ? {title:item.title} : {}),...(typeof item.url==='string' ? {url:item.url} : {}),...(typeof item.lastOpened==='string' ? {lastOpened:item.lastOpened} : {}),...(typeof item.tabGroup==='string' ? {tabGroup:item.tabGroup} : {})};
    });
  }
  async claimTab(tab:string | number | BrowserUserTabInfo):Promise<OpenBrowserUseTab> {
    const id=browserTabId(tab);
    if((await this.browser.tabs.list()).some(item=>item.id===String(id)))return this.browser.tab(id);
    return this.browser.claimTab(id);
  }
  async history(options:{from?:string | Date;to?:string | Date;limit?:number;query?:string} = {}):Promise<BrowserHistoryEntry[]> {
    if(!options || typeof options!=='object' || Array.isArray(options) || Object.keys(options).some(key=>!['from','to','limit','query'].includes(key)))throw new Error('Invalid history options');
    const date=(value:string | Date | undefined):string | undefined=>{
      if(value===undefined)return undefined;
      const parsed=types.isDate(value) ? value : typeof value==='string' ? new Date(value) : new Date(NaN);
      if(!Number.isFinite(parsed.getTime()))throw new Error('Invalid history date');return parsed.toISOString();
    };
    const from=date(options.from),to=date(options.to);
    if((from && to && from>to) || (options.limit!==undefined && (!Number.isSafeInteger(options.limit) || options.limit<1)) || (options.query!==undefined && typeof options.query!=='string'))throw new Error('Invalid history options');
    const result=await this.browser.client.getUserHistory({...(from ? {from} : {}),...(to ? {to} : {}),...(options.limit!==undefined ? {limit:options.limit} : {}),...(options.query!==undefined ? {query:options.query} : {})});
    if(!Array.isArray(result))throw new Error('Browser returned invalid history');
    return result.map(item=>{
      if(!isObject(item) || typeof item.url!=='string' || typeof item.dateVisited!=='string' || !Number.isFinite(Date.parse(item.dateVisited)) || (item.title!==undefined && typeof item.title!=='string'))throw new Error('Browser returned invalid history entry');
      return {url:item.url,dateVisited:item.dateVisited,...(typeof item.title==='string' ? {title:item.title} : {})};
    });
  }
}

export type OpenBrowserUseCapabilityInfo = {id:string;description:string};
export type OpenBrowserUseWebMcpTool = {name:string;registration_id:string;input_schema:JsonValue;title?:string;description?:string;annotations?:JsonValue;origin?:string;pageUrl?:string};
export class OpenBrowserUseCapabilities {
  constructor(private browser:OpenBrowserUseBrowser,private tab?:OpenBrowserUseTab) {}
  async list():Promise<OpenBrowserUseCapabilityInfo[]> {
    const info=await this.browser.client.getInfo();
    if(!isObject(info) || !isObject(info.capabilities))throw new Error('Browser capability metadata is unavailable');
    const entries=info.capabilities[this.tab ? 'tab' : 'browser'];
    if(entries===undefined)return [];
    if(!Array.isArray(entries))throw new Error('Invalid browser capability metadata');
    const seen=new Set<string>();const result=entries.map(item=>{
      if(!isObject(item) || typeof item.id!=='string' || !item.id || typeof item.description!=='string' || seen.has(item.id))throw new Error('Invalid browser capability metadata');
      seen.add(item.id);return {id:item.id,description:item.description};
    });
    if(this.tab && result.length)await this.browser.tabs.get(this.tab.id);
    return result;
  }
  async get(id:'webmcp'):Promise<OpenBrowserUseWebMcp>;
  async get(id:string):Promise<unknown>;
  async get(id:string):Promise<unknown> {
    if(typeof id!=='string' || !id)throw new Error('Invalid capability ID');
    if(!(await this.list()).some(item=>item.id===id))throw new Error(`Capability unavailable: ${id}`);
    if(id==='webmcp' && this.tab)return new OpenBrowserUseWebMcp(this.tab);
    throw new Error(`Capability is not implemented: ${id}`);
  }
}

export class OpenBrowserUseWebMcp {
  constructor(private tab:OpenBrowserUseTab) {}
  async listTools():Promise<OpenBrowserUseWebMcpTool[]> {
    const result=await this.tab.browser.client.request('webmcp_list_tools',{tabId:this.tab.id});
    if(!isObject(result) || !Array.isArray(result.tools))throw new Error('Invalid WebMCP tool list');
    return result.tools.map(tool=>{
      if(!isObject(tool) || typeof tool.name!=='string' || !tool.name || typeof tool.registration_id!=='string' || !tool.registration_id || !Object.hasOwn(tool,'input_schema') || (tool.title!==undefined && typeof tool.title!=='string') || (tool.description!==undefined && typeof tool.description!=='string') || (tool.origin!==undefined && typeof tool.origin!=='string') || (tool.pageUrl!==undefined && typeof tool.pageUrl!=='string'))throw new Error('Invalid WebMCP tool descriptor');
      return tool as OpenBrowserUseWebMcpTool;
    });
  }
  async invokeTool(tool:OpenBrowserUseWebMcpTool,input:JsonValue,options:{timeoutMs?:number} = {}):Promise<JsonValue> {
    if(!tool || typeof tool.name!=='string' || !tool.name.trim() || typeof tool.registration_id!=='string' || !tool.registration_id.trim() || input===undefined || !options || typeof options!=='object' || Array.isArray(options) || Object.keys(options).some(key=>key!=='timeoutMs'))throw new Error('Invalid WebMCP invocation');
    const timeoutMs=options.timeoutMs ?? 10_000;
    if(!Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>120_000)throw new Error('Invalid WebMCP timeout');
    const result=await this.tab.browser.client.request('webmcp_invoke_tool',{tabId:this.tab.id,tool_name:tool.name,registration_id:tool.registration_id,input,timeout_ms:timeoutMs,...(typeof tool.title==='string' ? {tool_title:tool.title} : {}),...(typeof tool.description==='string' ? {tool_description:tool.description} : {})},undefined,Math.max(this.tab.browser.client.timeoutMs,timeoutMs+2000));
    if(!isObject(result) || !Object.hasOwn(result,'result'))throw new Error('Invalid WebMCP invocation result');
    return result.result;
  }
}

export class OpenBrowserUseDialog {
  constructor(private cdp: OpenBrowserUseCdp, private tabId: number, readonly info: OpenBrowserUseDialogInfo) {}
  accept(promptText?: string): Promise<void> { return this.cdp.resolveDialog(this.tabId,this.info.id,true,promptText); }
  dismiss(): Promise<void> { return this.cdp.resolveDialog(this.tabId,this.info.id,false); }
}

export class OpenBrowserUseDownload {
  constructor(private client: OpenBrowserUseClient, readonly id: string, readonly url: string | null = null) {}
  async path(timeoutMs?: number): Promise<string | null> {
    const result = await this.client.downloadPath(this.id, timeoutMs);
    if (!isObject(result) || (typeof result.path !== "string" && result.path !== null)) throw new Error("Browser returned an invalid download path");
    return result.path;
  }
}

export class OpenBrowserUseDownloadWait {
  constructor(private client: OpenBrowserUseClient, private result: Promise<JsonValue>) {}
  async wait(): Promise<OpenBrowserUseDownload> {
    const result = await this.result;
    if (!isObject(result) || typeof result.downloadId !== "string" || !result.downloadId) throw new Error("Browser returned an invalid download ID");
    if (result.url !== undefined && result.url !== null && typeof result.url !== "string") throw new Error("Browser returned an invalid download URL");
    return new OpenBrowserUseDownload(this.client, result.downloadId, result.url ?? null);
  }
}

export class OpenBrowserUseFileChooser {
  #issued = false;
  constructor(private client: OpenBrowserUseClient, readonly id: string, private multiple: boolean) {}
  isMultiple(): boolean { return this.multiple; }
  async setFiles(files: string | string[]): Promise<void> {
    const paths = typeof files === "string" ? [files] : Array.isArray(files) ? [...files] : [];
    if (!paths.length || paths.some(path => typeof path !== "string" || !isAbsolute(path))) throw new Error("File paths must be absolute");
    if (!this.multiple && paths.length > 1) throw new Error("File chooser does not accept multiple files");
    if (this.#issued) throw new Error("File chooser decision has already been issued; observe again");
    this.#issued = true;
    await this.client.setFileChooserFiles(this.id, paths);
  }
}

export class OpenBrowserUseFileChooserWait {
  #chooser?: Promise<OpenBrowserUseFileChooser>;
  constructor(private client: OpenBrowserUseClient, private result: Promise<JsonValue>) {}
  wait(): Promise<OpenBrowserUseFileChooser> {
    return this.#chooser ??= this.result.then(result => {
      if (!isObject(result) || typeof result.fileChooserId !== "string" || !result.fileChooserId || typeof result.isMultiple !== "boolean") throw new Error("Browser returned an invalid file chooser");
      return new OpenBrowserUseFileChooser(this.client,result.fileChooserId,result.isMultiple);
    });
  }
}

export class OpenBrowserUseTab {
  readonly browser: OpenBrowserUseBrowser;
  readonly id: number;
  readonly playwright: OpenBrowserUseTabPlaywright;
  readonly capabilities:OpenBrowserUseCapabilities;
  readonly cua: OpenBrowserUseTabCUA;
  readonly dom_cua: OpenBrowserUseTabDomCUA;
  readonly dev: OpenBrowserUseTabDev;
  readonly clipboard: OpenBrowserUseTabClipboard;
  #observation?: Observation;
  #lastText?: { documentId: number; includeFrames: boolean; includeValues: boolean; includeText: boolean; text: string; truncated: boolean };

  constructor(browser: OpenBrowserUseBrowser, id: number) {
    this.browser = browser;
    this.id = id;
    this.playwright = new OpenBrowserUseTabPlaywright(this);
    this.capabilities = new OpenBrowserUseCapabilities(browser,this);
    this.cua = new OpenBrowserUseTabCUA(this);
    this.dom_cua = browser.domCuaFor(this);
    this.dev = new OpenBrowserUseTabDev(this);
    this.clipboard = new OpenBrowserUseTabClipboard(this);
  }

  goto(url: string, options: OpenBrowserUseGotoOptions = {}): Promise<JsonValue> {
    this.#observation = undefined;
    return this.browser.cdp.navigate(this.id, url, options);
  }

  async title():Promise<string | undefined> { return (await this.browser.tabs.list()).find(tab=>tab.id===String(this.id))?.title; }
  async url():Promise<string | undefined> { return (await this.browser.tabs.list()).find(tab=>tab.id===String(this.id))?.url; }

  async back(): Promise<void> { await this.moveHistory(-1); }
  async forward(): Promise<void> { await this.moveHistory(1); }
  async bringToFront(): Promise<void> {
    this.#observation = undefined;
    await this.browser.cdp.call(this.id,"Page.bringToFront");
  }
  async getPresentation(): Promise<OpenBrowserUseTabPresentation> {
    const result = await this.browser.client.request("getTabPresentation",{tabId:this.id});
    if (!isObject(result) || !["chrome","electron"].includes(String(result.backend)) || typeof result.selected !== "boolean" || (result.visible !== null && typeof result.visible !== "boolean") || (result.windowFocused !== null && typeof result.windowFocused !== "boolean")) throw new Error("Invalid tab presentation response");
    return result as OpenBrowserUseTabPresentation;
  }

  private async moveHistory(direction: -1 | 1): Promise<void> {
    const history = await this.browser.cdp.call(this.id, "Page.getNavigationHistory");
    if (!isObject(history) || !Number.isInteger(history.currentIndex) || !Array.isArray(history.entries)) throw new Error("Browser navigation history is unavailable");
    const current = history.currentIndex as number;
    if (current < 0 || current >= history.entries.length) throw new Error("Browser navigation history is unavailable");
    const index = current + direction;
    if (index < 0 || index >= history.entries.length) return;
    const entry = history.entries[index];
    if (!isObject(entry) || !Number.isInteger(entry.id)) throw new Error("Browser navigation history is unavailable");
    this.#observation = undefined;
    await this.browser.cdp.call(this.id, "Page.navigateToHistoryEntry", {entryId:entry.id});
  }

  async reload(options:{timeoutMs?:number} = {}): Promise<void> {
    if(!options || typeof options!=="object" || Array.isArray(options) || Object.keys(options).some(key=>key!=="timeoutMs"))throw new Error("Invalid reload options");
    const timeoutMs=options.timeoutMs ?? defaultNavigationTimeoutMs;
    if(!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000)throw new Error("Invalid reload timeout");
    this.#observation=undefined;
    const deadline=performance.now()+timeoutMs,initialGeneration=this.browser.client.isConnected ? this.browser.client.connectionGeneration : undefined,controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>|undefined,started=false;
    const timeout=()=>new Error(started ? "Timed out waiting for reload; outcome unknown" : "Reload preparation timed out before action");
    try {
      const work=(async()=>{
        await this.browser.cdp.call(this.id,"Page.enable",{},{timeoutMs:Math.max(1,deadline-performance.now()),signal:controller.signal});
        if(controller.signal.aborted || performance.now()>=deadline)throw timeout();
        if(initialGeneration!==undefined && initialGeneration!==this.browser.client.connectionGeneration)throw new Error("Connection changed during reload preparation before action");
        const generation=this.browser.client.connectionGeneration,remaining=deadline-performance.now();
        if(remaining<=0)throw timeout();
        const wait=this.browser.cdp.waitForLoadEvent(this.id,"load",remaining,controller.signal).catch(error=>{
          if(error instanceof Error && error.message===`Timed out waiting for load in tab ${this.id}`)throw timeout();
          throw error;
        });
        void wait.catch(()=>{});
        started=true;
        await this.browser.cdp.call(this.id,"Page.reload",{},{timeoutMs:remaining,expectedGeneration:generation,signal:controller.signal});
        await wait;
      })();
      await Promise.race([work,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(timeout()),Math.max(0,deadline-performance.now()));})]);
      if(performance.now()>=deadline)throw timeout();
    } finally {if(timer)clearTimeout(timer);controller.abort();}
  }

  waitForLoadState(options: OpenBrowserUseWaitForLoadStateOptions = {}): Promise<void> {
    return this.browser.cdp.waitForLoadState(this.id, options);
  }

  async expectNavigation<T>(action: () => Promise<T>, options: {timeoutMs?: number; url?: string | RegExp; waitUntil?: OpenBrowserUseLoadState} = {}): Promise<T> {
    if (typeof action !== "function") throw new Error("Navigation action must be a function");
    if (options.url !== undefined && typeof options.url !== "string" && !types.isRegExp(options.url)) throw new Error("URL matcher must be a string or RegExp");
    const waitUntil = options.waitUntil ?? "load", timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    assertSupportedLoadState(waitUntil);
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid navigation timeout");
    const deadline=performance.now()+timeoutMs;
    let generation=this.browser.client.isConnected ? this.browser.client.connectionGeneration : undefined;
    let stopped=false,preflightTimer:ReturnType<typeof setTimeout>|undefined;
    const ensureReady=()=>{
      if(stopped || performance.now()>=deadline)throw new Error("Navigation preparation timed out before action");
      if(generation!==undefined && generation!==this.browser.client.connectionGeneration)throw new Error("Connection changed during navigation preparation before action");
      generation=this.browser.client.connectionGeneration;
    };
    let tree:JsonValue;
    try {
      const prepare=(async()=>{await this.browser.cdp.call(this.id,"Page.enable");ensureReady();return this.browser.cdp.call(this.id,"Page.getFrameTree");})();
      tree=await Promise.race([prepare,new Promise<never>((_,reject)=>{preflightTimer=setTimeout(()=>reject(new Error("Navigation preparation timed out before action")),Math.max(0,deadline-performance.now()));})]);
      ensureReady();
    } finally {stopped=true;if(preflightTimer)clearTimeout(preflightTimer);}
    const root = isObject(tree) && isObject(tree.frameTree) && isObject(tree.frameTree.frame) ? tree.frameTree.frame.id : undefined;
    if (typeof root !== "string") throw new Error("Main frame is unavailable");
    const remaining=deadline-performance.now();
    if(remaining<=0)throw new Error("Navigation preparation timed out before action");
    const controller = new AbortController();
    const navigation = this.browser.cdp.waitForEvent(this.id,notification => {
      const event = cdpEventForTab(notification,this.id);
      if (!event || !isObject(event.params)) return false;
      if (event.method === "Page.navigatedWithinDocument") return event.params.frameId === root;
      return event.method === "Page.frameNavigated" && isObject(event.params.frame) && event.params.frame.id === root && !event.params.frame.parentId;
    },{timeoutMs:remaining,signal:controller.signal,timeoutMessage:`Timed out waiting for navigation after ${timeoutMs} ms; action outcome unknown`});
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const work = (async () => {
        const [result] = await Promise.all([Promise.resolve().then(action),navigation]);
        if (controller.signal.aborted) throw new Error("Navigation wait cancelled");
        const remaining = Math.max(0, deadline - performance.now());
        if (options.url !== undefined) await this.waitForURL(options.url,{waitUntil,timeoutMs:remaining});
        else await this.waitForLoadState({state:waitUntil,timeoutMs:remaining});
        return result;
      })();
      return await Promise.race([work,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error(`Timed out waiting for navigation after ${timeoutMs} ms; action outcome unknown`)),remaining);})]);
    } finally { if (timer) clearTimeout(timer); controller.abort(); }
  }

  async waitForURL(url: string | RegExp, options: {waitUntil?: OpenBrowserUseWaitUntil; timeoutMs?: number} = {}): Promise<void> {
    if (typeof url !== "string" && !types.isRegExp(url)) throw new Error("URL matcher must be a string or RegExp");
    const matcher = typeof url === "string" ? url : new RegExp(url.source, url.flags);
    const waitUntil = options.waitUntil ?? "load";
    if(waitUntil!=="commit")assertSupportedLoadState(waitUntil);
    const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid URL timeout");
    const deadline = performance.now() + timeoutMs;
    const timedOut=()=>new Error(`Timed out waiting for URL after ${timeoutMs} ms`);
    while (true) {
      if(timeoutMs>0 && performance.now()>=deadline)throw timedOut();
      let state: JsonValue = null, timer:ReturnType<typeof setTimeout>|undefined;
      try {
        const read=this.browser.cdp.readDocumentStateStrict(this.id);
        state=timeoutMs===0 ? await read : await Promise.race([read,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(timedOut()),Math.max(0,deadline-performance.now()));})]);
      } catch (error) {
        if (!(error instanceof Error) || !/Execution context was destroyed|Cannot find context with specified id/i.test(error.message)) throw error;
      } finally {if(timer)clearTimeout(timer);}
      if(timeoutMs>0 && performance.now()>=deadline)throw timedOut();
      if (isObject(state) && typeof state.href === "string") {
        if (matcher instanceof RegExp) matcher.lastIndex = 0;
        const matches = typeof matcher === "string" ? state.href === matcher : matcher.test(state.href);
        if (matches && (waitUntil==="commit" || documentStateMatches({readyState:stringValue(state.readyState)},waitUntil))) return;
      }
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw timedOut();
      await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
    }
  }

  async domSnapshot(): Promise<string> {
    const state = await this.observe({includeFrames:true,includeText:true});
    const text = state.text.replace(/^([ \t]*)\[\d+\] /gm, "$1");
    return [text, ...(state.truncated ? ["[Snapshot truncated]"] : []), ...(state.unavailableFrames?.length ? [`[${state.unavailableFrames.length} frame(s) unavailable]`] : [])].filter(Boolean).join("\n");
  }

  getAXState(): Promise<JsonValue> {
    return this.browser.cdp.call(this.id, "Accessibility.getFullAXTree");
  }

  async observe(options: { diff?: boolean; includeFrames?: boolean; includeValues?: boolean; includeText?: boolean } = {}): Promise<InteractiveState> {
    this.#observation = undefined;
    const documentId = await this.documentId();
    const tree = await this.getAXState();
    const nodes: ObservedNode[] = interactiveNodes(tree, 0, options.includeText);
    const unindexedText: UnindexedText[] = options.includeText ? unindexedTextAncestors(tree) : [];
    const valueBudget = { remaining: 8_000, truncated: false };
    if (options.includeValues) await this.readAXValues(tree, nodes, valueBudget);
    let full = options.includeFrames ? {text:"",truncated:false} : renderAXState(tree, nodes);
    const unavailableFrames: string[] = [];
    let observedFrames: FrameInfo[] | undefined;
    let crossProcess = false;
    if (options.includeFrames) {
      crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
      const frames = await this.frameTree();
      observedFrames = frames;
      const trees = new Map<string,{tree:JsonValue; nodes:ObservedNode[]; owner?:number}>();
      trees.set(frames[0].id,{tree,nodes:[...nodes]});
      for (const frame of frames.slice(1)) {
        try {
          const childTree = await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: frame.id }, { sessionId: frame.sessionId });
          if (options.includeText) unindexedText.push(...unindexedTextAncestors(childTree).map(item=>({...item,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
          const childNodes = interactiveNodes(childTree, nodes.length, options.includeText).map(node => ({ ...node, frameId: frame.id, frameChain: frameAncestry(frame, frames) }));
          if (options.includeValues) await this.readAXValues(childTree, childNodes, valueBudget, frame.sessionId);
          nodes.push(...childNodes);
          let owner: number | undefined;
          try {
            const parent = frames.find(item=>item.id === frame.parentId);
            const result = await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:frame.id},{sessionId:parent?.sessionId});
            if (isObject(result) && typeof result.backendNodeId === "number") owner = result.backendNodeId;
          } catch { /* A readable frame can still be shown without its position. */ }
          trees.set(frame.id,{tree:childTree,nodes:childNodes,owner});
        } catch { unavailableFrames.push(frame.id); }
      }
      const attachments = new Map<string,Map<number,RenderedFrame[]>>();
      const unplaced: RenderedFrame[] = [];
      for (const frame of [...frames].reverse()) {
        const entry = trees.get(frame.id);
        if (!entry) continue;
        const rendered = renderAXState(entry.tree,entry.nodes,attachments.get(frame.id));
        if (!frame.parentId) { full = rendered; continue; }
        const child = {url:frame.url,...rendered};
        if (entry.owner === undefined || !trees.has(frame.parentId)) { unplaced.unshift(child); continue; }
        const parent = attachments.get(frame.parentId) ?? new Map<number,RenderedFrame[]>();
        const siblings = parent.get(entry.owner) ?? []; siblings.unshift(child); parent.set(entry.owner,siblings); attachments.set(frame.parentId,parent);
      }
      if (unplaced.length) full = appendUnplacedFrames(full,unplaced);
      const current = await this.frameTree();
      if (JSON.stringify(current) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed during observation; observe again");
    }
    if (documentId !== await this.documentId()) throw new RetryablePreflightError("Page changed during observation; observe again");
    const id = randomUUID();
    this.#observation = { id, documentId, nodes, unindexedText, ...(observedFrames ? {frames:observedFrames} : {}), guards:new Map() };
    const previous = this.#lastText;
    const useDiff = options.diff === true && previous?.documentId === documentId && previous.includeFrames === !!options.includeFrames && previous.includeValues === !!options.includeValues && previous.includeText === !!options.includeText && !previous.truncated && !full.truncated && !valueBudget.truncated && !unavailableFrames.length;
    const output = useDiff ? diffAXState(previous.text, full.text) : full;
    this.#lastText = (output.truncated && useDiff) || unavailableFrames.length || valueBudget.truncated ? undefined : { documentId, includeFrames: !!options.includeFrames, includeValues: !!options.includeValues, includeText: !!options.includeText, ...full };
    return { snapshotId: id, nodes: nodes.map(({ index, role, name, frameId, level, checked, disabled, pressed, selected, expanded, placeholder, placeholderTruncated, altText, altTextTruncated, value, valueRedacted, valueUnavailable, valueTruncated }) => ({ index, role, name, ...(frameId ? {frameId} : {}), ...(level !== undefined ? {level} : {}), ...(checked !== undefined ? {checked} : {}), ...(disabled ? {disabled:true} : {}), ...(pressed !== undefined ? {pressed} : {}), ...(selected !== undefined ? {selected} : {}), ...(expanded !== undefined ? {expanded} : {}), ...(placeholder !== undefined ? {placeholder} : {}), ...(placeholderTruncated ? {placeholderTruncated} : {}), ...(altText !== undefined ? {altText} : {}), ...(altTextTruncated ? {altTextTruncated} : {}), ...(value !== undefined ? {value} : {}), ...(valueRedacted ? {valueRedacted} : {}), ...(valueUnavailable ? {valueUnavailable} : {}), ...(valueTruncated ? {valueTruncated} : {}) })), ...output, textMode: useDiff ? "diff" : "full", ...(options.includeFrames ? {frameCoverage: crossProcess ? "cross-process" as const : "same-process" as const, unavailableFrames} : {}), ...(options.includeValues ? {valuesTruncated:valueBudget.truncated} : {}) };
  }

  private async readAXValues(tree: JsonValue, nodes: ObservedNode[], budget: {remaining: number; truncated: boolean}, sessionId?: string): Promise<void> {
    if (!isObject(tree) || !Array.isArray(tree.nodes)) throw new Error("Invalid accessibility tree");
    const byId = new Map(tree.nodes.filter(isObject).map(node => [node.backendDOMNodeId, node]));
    for (const node of nodes) {
      if (!["textbox", "searchbox", "combobox", "slider", "spinbutton", "Date", "DateTime", "InputTime"].includes(node.role)) continue;
      const ax = byId.get(node.backendNodeId);
      const value = isObject(ax?.value) ? ax.value.value : undefined;
      if (typeof value !== "string" && (typeof value !== "number" || !Number.isFinite(value))) continue;
      {
        let objectId: string | undefined;
        try {
          const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", {backendNodeId:node.backendNodeId}, {sessionId});
          const id = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
          if (typeof id !== "string") throw new Error("Unresolved field");
          objectId = id;
          const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {objectId, returnByValue:true,
            functionDeclaration:`function() { if (this instanceof HTMLInputElement) return this.type === 'password' ? 'redacted' : 'visible'; if (this instanceof HTMLTextAreaElement || this instanceof HTMLSelectElement || this.isContentEditable || (this instanceof HTMLElement && ['slider','spinbutton'].includes(this.getAttribute('role')))) return 'visible'; return 'unknown'; }`}, {sessionId});
          const kind = isObject(result) && isObject(result.result) ? result.result.value : undefined;
          if (kind === "redacted") { node.valueRedacted = true; continue; }
          if (kind !== "visible") { node.valueUnavailable = true; continue; }
        } catch { node.valueUnavailable = true; continue; }
        finally { if (objectId) await this.browser.cdp.call(this.id, "Runtime.releaseObject", {objectId}, {sessionId}).catch(() => {}); }
      }
      const text = String(value), limit = Math.min(512, budget.remaining);
      if (text.length > limit) { node.valueTruncated = true; budget.truncated = true; }
      if (limit > 0 || !text.length) node.value = typeof value === "number" ? value : text.slice(0, limit);
      budget.remaining -= Math.min(text.length, limit);
    }
  }

  /** @internal */
  currentObservation(snapshotId: string): Observation {
    const observation=this.#observation;
    if (!observation || observation.id!==snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    return observation;
  }

  /** @internal */
  bindLocatorScope(snapshotId: string, targetIndex: number, scopeIndices: number[], filters: FilterGuard[], framePath?: string[], css?: CssGuard, role?: RoleGuard): void {
    const observation = this.#observation;
    if (!observation || observation.id !== snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    observation.guards.set(targetIndex, {scopes:[...scopeIndices],filters:filters.map(item => ({index:item.index,filters:item.filters.map(filter=>({...filter}))})),...(framePath ? {framePath:[...framePath]} : {}),...(css ? {css} : {}),...(role ? {role} : {})});
  }

  /** @internal */
  async resolveFramePath(path: readonly string[], snapshotId?: string, expectedFrames?: readonly FrameInfo[]): Promise<string | null> {
    const frames = await this.frameTree();
    const checkSnapshot = () => { if ((snapshotId && (!this.#observation || this.#observation.id !== snapshotId || JSON.stringify(this.#observation.frames) !== JSON.stringify(frames))) || (expectedFrames && JSON.stringify(expectedFrames)!==JSON.stringify(frames))) throw new RetryablePreflightError("Frame tree changed; observe again"); };
    checkSnapshot();
    let parent = frames[0];
    for (const selector of path) {
      const matched: FrameInfo[] = [];
      const children = frames.filter(item=>item.parentId === parent.id);
      const world = await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:parent.id,worldName:"open-browser-use-selector"},{sessionId:parent.sessionId});
      const contextId = isObject(world) ? world.executionContextId : undefined;
      if (typeof contextId !== "number" || !Number.isSafeInteger(contextId)) throw new RetryablePreflightError("Frame selector context is unavailable; observe again");
      if (!children.length) {
        const result = await this.browser.cdp.call(this.id,"Runtime.evaluate",{contextId,returnByValue:true,expression:`(() => { try { document.createElement('iframe').matches(${JSON.stringify(selector)}); return true; } catch { return false; } })()`},{sessionId:parent.sessionId});
        const valid = isObject(result) && isObject(result.result) ? result.result.value : undefined;
        if (valid === false) throw new Error("Invalid frame selector");
        if (valid !== true) throw new RetryablePreflightError("Frame selector is unavailable; observe again");
      }
      for (const frame of children) {
        const owner = await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:frame.id},{sessionId:parent.sessionId});
        if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
        const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:owner.backendNodeId,executionContextId:contextId},{sessionId:parent.sessionId});
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
        try {
          // Flush the matched frame owner layout before querying its child viewport.
          const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:selector}],functionDeclaration:`function(selector) { if (!this.isConnected) return null; const matched=this.matches(selector); if (matched) this.getBoundingClientRect(); return matched; }`},{sessionId:parent.sessionId});
          if (isObject(result) && result.exceptionDetails) throw new Error("Invalid frame selector");
          const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
          if (typeof value !== "boolean") throw new RetryablePreflightError("Frame owner changed; observe again");
          if (value) matched.push(frame);
        } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId:parent.sessionId}).catch(()=>{}); }
      }
      if (matched.length > 1) throw new Error(`Frame selector matched ${matched.length} frames; expected exactly one`);
      if (!matched.length) {
        if (JSON.stringify(await this.frameTree()) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed; observe again");
        checkSnapshot();
        return null;
      }
      parent = matched[0];
    }
    if (JSON.stringify(await this.frameTree()) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed; observe again");
    checkSnapshot();
    return parent.id;
  }

  /** @internal */
  async queryCss(step: CssStep, framePath?: readonly string[], scopes: readonly CssStep[] = [], semanticScope?: OpenBrowserUseRoleLocator, base?: {observation:Observation; index:number}, explicitFrame?:string): Promise<CssSnapshot> {
    const selector=step.selector;
    if (typeof selector !== "string" || !selector.trim() || selector.length > 4096) throw new Error("Invalid CSS selector");
    const documentId = await this.documentId();
    const crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
    const frames = await this.frameTree();
    if (framePath && !crossProcess) throw new Error("Frame routing is unavailable");
    const baseNode=base?.observation.nodes.find(node=>node.index===base.index);
    if (base && (!baseNode || !base.observation.frames || semanticScope)) throw new RetryablePreflightError("Filter scope is unavailable; observe again");
    const semantic=semanticScope ? await semanticScope.detachedRoots() : base && baseNode ? {documentId:base.observation.documentId,frames:base.observation.frames!,roots:[{backendNodeId:baseNode.backendNodeId,frameId:baseNode.frameId ?? ""}]} : undefined;
    if (semantic && (semantic.documentId!==documentId || JSON.stringify(semantic.frames)!==JSON.stringify(frames))) throw new RetryablePreflightError("Semantic scope changed; observe again");
    if (semantic && semantic.roots.length>1000) throw new Error("Semantic scope matched more than 1000 elements");
    const semanticFrames=new Set(semantic?.roots.map(root=>root.frameId || frames[0].id));
    if (semanticFrames.size>1) throw new Error("Semantic CSS scope spans multiple frames; choose one frame");
    const semanticFrame=semanticFrames.values().next().value;
    if (explicitFrame && (framePath || semanticScope || base)) throw new Error("Invalid explicit frame scope");
    const frameId = explicitFrame ?? (framePath ? await this.resolveFramePath(framePath) : semanticFrame ?? frames[0].id);
    if (semanticFrame && frameId && semanticFrame!==frameId) throw new Error("Semantic scope and CSS frame differ");
    if (!frameId) {
      if (await this.documentId() !== documentId || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed; observe again");
      return {step,scopes,scopeIds:[],framePath,...(explicitFrame ? {frameId:explicitFrame} : {}),...(semanticScope && semantic ? {semantic:{scope:semanticScope,roots:semantic.roots}} : {}),frame:null,frames,documentId,ids:[]};
    }
    const frame = frames.find(item=>item.id === frameId);
    if (!frame) throw new RetryablePreflightError("Frame tree changed; observe again");
    const needsVisibility=(steps:readonly CssStep[]):boolean=>steps.some(step=>(step.union ? step.union.some(needsVisibility) : false) || [...(step.before ?? []),...(step.after ?? [])].some(filter=>filter.visible !== undefined || (filter.has ? needsVisibility(filter.has) : false) || (filter.hasNot ? needsVisibility(filter.hasNot) : false) || (filter.and ? needsVisibility(filter.and) : false)));
    const checkVisibility=needsVisibility([...scopes,step]);
    const frameVisible=checkVisibility ? await this.cssFrameVisible(frame,frames) : true;
    const sessionId = frame.sessionId;
    const world = await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    const contextId = isObject(world) ? world.executionContextId : undefined;
    if (typeof contextId !== "number" || !Number.isSafeInteger(contextId)) throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const expression = `(() => {
      const steps=${JSON.stringify([...scopes,step])}, output=[], frameVisible=${JSON.stringify(frameVisible)}; let total=0, visited=0;
      const guarded=steps.some(step=>step.union || [...(step.before || []),...(step.after || [])].some(filter=>filter.has || filter.hasNot || filter.and));
      const normalize=text=>text.replace(/\\s+/g,' ').trim();
      const textOf=element=>{let text='',stack=[element];while(stack.length){const node=stack.pop();if(node.nodeType===Node.TEXT_NODE){text+=node.nodeValue || '';if(text.length>30000)throw new Error('Filter text exceeds the 30000 character limit');continue;}if(node.nodeType===Node.ELEMENT_NODE && ['SCRIPT','STYLE','NOSCRIPT'].includes(node.tagName))continue;if(node.shadowRoot)stack.push(node.shadowRoot);const children=node.childNodes;for(let j=children.length-1;j>=0;j--)stack.push(children[j]);}return normalize(text);};
      const apply=(items,filters,initial)=>{if(!filters?.length)return items;const intersections=new Map();return items.filter(element=>filters.every(filter=>{
        if(filter.visible!==undefined){const r=element.getBoundingClientRect(),visible=frameVisible && getComputedStyle(element).visibility==='visible' && r.width>0 && r.height>0;if(visible!==filter.visible)return false;}
        if(filter.title){const values=[];const attr=element.getAttribute('title');if(attr!==null)values.push(attr);if(element.namespaceURI==='http://www.w3.org/2000/svg')for(const child of element.children)if(child.localName==='title' && child.namespaceURI===element.namespaceURI)values.push(child.textContent || '');const pattern=filter.title.matcher,match=raw=>{if(raw.length>30000)throw new Error('Title exceeds the 30000 character limit');const text=normalize(raw);if(typeof pattern!=='string')return new RegExp(pattern.source,pattern.flags).test(text);const value=normalize(pattern);return filter.title.exact ? text===value : text.toLowerCase().includes(value.toLowerCase());};if(!values.some(match))return false;}
        if(filter.hasText!==undefined || filter.hasNotText!==undefined){const text=textOf(element),match=pattern=>typeof pattern==='string' ? text.toLowerCase().includes(normalize(pattern).toLowerCase()) : new RegExp(pattern.source,pattern.flags).test(text);if(filter.hasText!==undefined && !match(filter.hasText))return false;if(filter.hasNotText!==undefined && match(filter.hasNotText))return false;}
        if(filter.has && !resolve([element],filter.has,false).length)return false;
        if(filter.hasNot && resolve([element],filter.hasNot,false).length)return false;
        if(filter.and){if(!intersections.has(filter))intersections.set(filter,new Set(resolve(initial,filter.and,false)));if(!intersections.get(filter).has(element))return false;}
        return true;
      }));};
      const validate=selectors=>{for(const step of selectors){document.createDocumentFragment().querySelector(step.selector);if(step.union){validate(step.union[0]);validate(step.union[1]);}for(const filter of [...(step.before || []),...(step.after || [])]){if(filter.has)validate(filter.has);if(filter.hasNot)validate(filter.hasNot);if(filter.and)validate(filter.and);}}};
      validate(steps);
      const resolve=(initial,selectors,record)=>{let roots=initial;for(let i=0;i<selectors.length;i++) {
        const {selector,position,before,after,union}=selectors[i], found=[], seen=new Set();
        const merged=union ? new Set([...resolve(initial,union[0],false),...resolve(initial,union[1],false)]) : null;
        const walk=root=>{const matched=merged || new Set(root.querySelectorAll(selector));for(const element of root.querySelectorAll('*')) {if(guarded && ++visited>100000)throw new Error('Locator filter search exceeds the 100000 element limit');if(matched.has(element) && !seen.has(element)){seen.add(element);found.push(element);if(found.length>1000)throw new Error('Selector matched more than 1000 elements');}if(element.shadowRoot)walk(element.shadowRoot);}};
        for(const root of roots) {walk(root);if(root instanceof Element && root.shadowRoot)walk(root.shadowRoot);}
        const filtered=apply(found,before,initial),selected=apply(position===undefined ? filtered : position===-1 ? filtered.slice(-1) : filtered.slice(position,position+1),after,initial);
        if(record){total+=selected.length;if(total>1000)throw new Error('Selector matched more than 1000 elements');output.push(i,...selected);}
        roots=selected;
      }return roots;};
      resolve(${semantic ? (semantic.roots.length ? "roots" : "[]") : "[document]"},steps,true);
      return output;
    })()`;
    const rootObjects:string[]=[];
    let evaluated:JsonValue;
    try {
      for (const root of semantic?.roots ?? []) {
        const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:root.backendNodeId,executionContextId:contextId},{sessionId});
        const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if(typeof objectId!=="string") throw new RetryablePreflightError("Semantic scope is unavailable; observe again");
        rootObjects.push(objectId);
      }
      if (rootObjects.length) evaluated=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId:rootObjects[0],arguments:rootObjects.slice(1).map(objectId=>({objectId})),returnByValue:false,functionDeclaration:`function(...others) { const roots=[this,...others].filter(root=>typeof root.querySelectorAll==='function'); return ${expression}; }`},{sessionId});
      else evaluated=await this.browser.cdp.call(this.id,"Runtime.evaluate",{expression,contextId,returnByValue:false},{sessionId});
    } finally { for(const objectId of rootObjects) await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
    if (isObject(evaluated) && evaluated.exceptionDetails) {
      const details = isObject(evaluated.exceptionDetails) && isObject(evaluated.exceptionDetails.exception) ? evaluated.exceptionDetails.exception.description : undefined;
      if (typeof details === "string" && details.includes("Selector matched more than 1000 elements")) throw new Error("Selector matched more than 1000 elements");
      if (typeof details === "string" && details.includes("Filter text exceeds the 30000 character limit")) throw new Error("Filter text exceeds the 30000 character limit");
      if (typeof details === "string" && details.includes("Locator filter search exceeds the 100000 element limit")) throw new Error("Locator filter search exceeds the 100000 element limit");
      throw new Error("Invalid CSS selector");
    }
    const arrayId = isObject(evaluated) && isObject(evaluated.result) ? evaluated.result.objectId : undefined;
    if (typeof arrayId !== "string") throw new RetryablePreflightError("Selector result is unavailable; observe again");
    const objectIds: string[] = [];
    try {
      const properties = await this.browser.cdp.call(this.id,"Runtime.getProperties",{objectId:arrayId,ownProperties:true},{sessionId});
      if (!isObject(properties) || !Array.isArray(properties.result)) throw new RetryablePreflightError("Selector result is unavailable; observe again");
      const entries = properties.result.filter(isObject).filter(item=>typeof item.name === "string" && /^(0|[1-9][0-9]*)$/.test(item.name)).sort((a,b)=>Number(a.name)-Number(b.name));
      for (const item of entries) if (isObject(item.value) && typeof item.value.objectId === "string") objectIds.push(item.value.objectId);
      if (objectIds.length > 1000) throw new Error("Selector matched more than 1000 elements");
      const stages: number[][] = [];
      for (const item of entries) {
        if (!isObject(item.value)) throw new RetryablePreflightError("Selector result is unavailable; observe again");
        if (typeof item.value.value === "number" && item.value.value === stages.length && stages.length <= scopes.length) { stages.push([]); continue; }
        if (typeof item.value.objectId !== "string" || !stages.length) throw new RetryablePreflightError("Selector result is unavailable; observe again");
        const result = await this.browser.cdp.call(this.id,"DOM.describeNode",{objectId:item.value.objectId},{sessionId});
        const node = isObject(result) && isObject(result.node) ? result.node : undefined;
        if (!node || typeof node.backendNodeId !== "number") throw new RetryablePreflightError("Selector target changed; observe again");
        stages[stages.length-1].push(node.backendNodeId);
      }
      if (checkVisibility && await this.cssFrameVisible(frame,frames) !== frameVisible) throw new RetryablePreflightError("Frame visibility changed; observe again");
      if (stages.length !== scopes.length+1 || await this.documentId() !== documentId || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed; observe again");
      return {step,scopes,scopeIds:stages.slice(0,-1),framePath,...(explicitFrame ? {frameId:explicitFrame} : {}),...(semanticScope && semantic ? {semantic:{scope:semanticScope,roots:semantic.roots}} : {}),frame,frames,documentId,ids:stages[stages.length-1]};
    } finally {
      for (const objectId of objectIds) await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{});
      await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId:arrayId},{sessionId}).catch(()=>{});
    }
  }

  /** @internal */
  async domFrames():Promise<FrameInfo[]> {
    if (!await this.browser.cdp.enableFrameSessions(this.id)) throw new Error("Frame routing is unavailable");
    return this.frameTree();
  }
  /** @internal */
  async domFrameInViewport(frame:FrameInfo,frames:FrameInfo[]):Promise<boolean> { return this.cssFrameVisible(frame,frames,true); }
  /** @internal */
  async domFrameClip(frame:FrameInfo,frames:FrameInfo[]):Promise<DomClip | null> {
    const metrics=await this.browser.cdp.call(this.id,'Page.getLayoutMetrics');
    const viewport=isObject(metrics) && isObject(metrics.cssVisualViewport) ? metrics.cssVisualViewport : null;
    if(!viewport || typeof viewport.clientWidth!=='number' || typeof viewport.clientHeight!=='number')throw new RetryablePreflightError('Viewport unavailable; observe again');
    let clip:DomClip={left:0,top:0,right:viewport.clientWidth,bottom:viewport.clientHeight};
    const chain=frameAncestry(frame,frames);
    for(let i=chain.length-1;i>=0;i--) {
      const child=chain[i],sessionId=chain[i+1]?.sessionId;
      const geometry=await this.frameGeometry(child,sessionId);
      if(!geometry)return null;
      const {x,y,width,height,sx,sy}=geometry;
      clip={left:Math.max(0,(clip.left-x)/sx),top:Math.max(0,(clip.top-y)/sy),right:Math.min(width,(clip.right-x)/sx),bottom:Math.min(height,(clip.bottom-y)/sy)};
      if(clip.right<=clip.left || clip.bottom<=clip.top)return null;
    }
    return clip;
  }
  private async frameGeometry(child:FrameInfo,sessionId?:string):Promise<{x:number;y:number;width:number;height:number;sx:number;sy:number}|null> {
    const owner=await this.browser.cdp.call(this.id,'DOM.getFrameOwner',{frameId:child.id},{sessionId});
    if(!isObject(owner) || typeof owner.backendNodeId!=='number')throw new RetryablePreflightError('Frame owner unavailable; observe again');
    const world=await this.browser.cdp.call(this.id,'Page.createIsolatedWorld',{frameId:child.parentId!,worldName:'open-browser-use-selector'},{sessionId});
    if(!isObject(world) || typeof world.executionContextId!=='number')throw new RetryablePreflightError('Frame context unavailable; observe again');
    const resolved=await this.browser.cdp.call(this.id,'DOM.resolveNode',{backendNodeId:owner.backendNodeId,executionContextId:world.executionContextId},{sessionId});
    const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if(typeof objectId!=='string')throw new RetryablePreflightError('Frame owner unavailable; observe again');
    try {
      const result=await this.browser.cdp.call(this.id,'Runtime.callFunctionOn',{objectId,returnByValue:true,functionDeclaration:`function(){if(!this.isConnected)return null;for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)){const t=getComputedStyle(el).transform;if(t!=='none'){const m=new DOMMatrixReadOnly(t);if(!m.is2D || m.b!==0 || m.c!==0 || m.a<=0 || m.d<=0)return {unsupported:true}}}const r=this.getBoundingClientRect();if(!this.offsetWidth || !this.offsetHeight)return null;const sx=r.width/this.offsetWidth,sy=r.height/this.offsetHeight;return {x:r.left+this.clientLeft*sx,y:r.top+this.clientTop*sy,width:this.clientWidth,height:this.clientHeight,sx,sy}}`},{sessionId});
      const value=isObject(result) && isObject(result.result) ? result.result.value : null;
      if(isObject(value) && value.unsupported===true)throw new Error('Cannot map a rotated or skewed frame');
      if(!isObject(value) || !['x','y','width','height','sx','sy'].every(key=>typeof value[key]==='number' && Number.isFinite(value[key])))throw new RetryablePreflightError('Frame geometry changed; observe again');
      const {x,y,width,height,sx,sy}=value as {x:number;y:number;width:number;height:number;sx:number;sy:number};
      if(sx<=0 || sy<=0 || width<=0 || height<=0)return null;
      return {x,y,width,height,sx,sy};
    } finally {await this.browser.cdp.call(this.id,'Runtime.releaseObject',{objectId},{sessionId}).catch(()=>{});}
  }
  /** @internal */
  async nodeBoundingBox(frame:FrameInfo,frames:FrameInfo[],id:number):Promise<{x:number;y:number;width:number;height:number}|null> {
    const sessionId=frame.sessionId,world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    if(!isObject(world) || typeof world.executionContextId!=="number")throw new RetryablePreflightError("Target context unavailable; observe again");
    const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:id,executionContextId:world.executionContextId},{sessionId});
    const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if(typeof objectId!=="string")throw new RetryablePreflightError("Target unavailable; observe again");
    try {
      const measure=async()=>{
        const result=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function(){if(!this.isConnected)return null;const element=this.nodeType===3?this.parentElement:this;if(!(element instanceof Element))return null;const range=this.nodeType===3?this.ownerDocument.createRange():null;if(range)range.selectNodeContents(this);const r=range?range.getBoundingClientRect():element.getBoundingClientRect();if(getComputedStyle(element).visibility!=='visible' || !r.width || !r.height)return {hidden:true};return {x:r.left,y:r.top,width:r.width,height:r.height}}`},{sessionId});
        const value=isObject(result) && isObject(result.result) ? result.result.value : null;
        if(isObject(value) && value.hidden===true)return null;
        if(!isObject(value) || ![value.x,value.y,value.width,value.height].every(v=>typeof v==="number" && Number.isFinite(v)))throw new RetryablePreflightError("Target geometry unavailable; observe again");
        return value as {x:number;y:number;width:number;height:number};
      };
      const box=await measure();if(!box)return null;
      const chain=frameAncestry(frame,frames),geometry=[];
      for(let i=0;i<chain.length;i++) {
        const current=await this.frameGeometry(chain[i],chain[i+1]?.sessionId);if(!current)return null;geometry.push(current);
        box.x=current.x+box.x*current.sx;box.y=current.y+box.y*current.sy;box.width*=current.sx;box.height*=current.sy;
      }
      const again=await measure();if(!again)throw new RetryablePreflightError("Target geometry changed; observe again");
      for(const current of geometry) {again.x=current.x+again.x*current.sx;again.y=current.y+again.y*current.sy;again.width*=current.sx;again.height*=current.sy;}
      if(JSON.stringify(again)!==JSON.stringify(box))throw new RetryablePreflightError("Target geometry changed; observe again");
      for(let i=0;i<chain.length;i++)if(JSON.stringify(await this.frameGeometry(chain[i],chain[i+1]?.sessionId))!==JSON.stringify(geometry[i]))throw new RetryablePreflightError("Frame geometry changed; observe again");
      await this.validateFrames(chain);return box;
    } finally {await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{});}
  }

  /** @internal */
  async domFramePoint(snapshot:CssSnapshot,point:{x:number;y:number}):Promise<{point:{x:number;y:number};inputPoint:{x:number;y:number}}> {
    if (!snapshot.frame) throw new RetryablePreflightError("Frame is unavailable; observe again");
    const chain=frameAncestry(snapshot.frame,snapshot.frames), sessionId=snapshot.frame.sessionId;
    let inputPoint=point;
    for(let i=0;i<chain.length;i++) {
      const ownerSession=chain[i+1]?.sessionId;
      point=await this.framePoint(chain[i].id,chain[i].parentId,point.x,point.y,ownerSession);
      if(ownerSession===sessionId) inputPoint=point;
    }
    await this.validateFrames(chain);return {point,inputPoint};
  }

  private async cssFrameVisible(frame: FrameInfo, frames: FrameInfo[], viewport = false): Promise<boolean> {
    const chain=frameAncestry(frame,frames);
    for (let i=0;i<chain.length;i++) {
      const child=chain[i], ownerSession=chain[i+1]?.sessionId;
      const owner=await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:child.id},{sessionId:ownerSession});
      if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
      const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:child.parentId!,worldName:"open-browser-use-selector"},{sessionId:ownerSession});
      if (!isObject(world) || typeof world.executionContextId !== "number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
      const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:owner.backendNodeId,executionContextId:world.executionContextId},{sessionId:ownerSession});
      const ownerId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
      if (typeof ownerId !== "string") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
      try {
        const state=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId:ownerId,returnByValue:true,arguments:[{value:viewport}],functionDeclaration:`function(viewport) { if(!this.isConnected)return null;const r=this.getBoundingClientRect();return getComputedStyle(this).visibility==='visible' && r.width>0 && r.height>0 && (!viewport || (r.right>0 && r.bottom>0 && r.left<innerWidth && r.top<innerHeight)); }`},{sessionId:ownerSession});
        const value=isObject(state) && isObject(state.result) ? state.result.value : undefined;
        if (typeof value !== "boolean") throw new RetryablePreflightError("Frame owner changed; observe again");
        if (!value) return false;
      } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId:ownerId},{sessionId:ownerSession}).catch(()=>{}); }
    }
    return true;
  }

  /** @internal */
  async readCss(snapshot: CssSnapshot, id: number, mode: "innerText" | "textContent" | "attribute" | "enabled" | "visible" | "checked" | "inputValue" | "editable", attribute = ""): Promise<string | boolean | null> {
    const frame = snapshot.frame;
    if (!frame || !snapshot.ids.includes(id)) throw new RetryablePreflightError("Selector target changed; observe again");
    const sessionId = frame.sessionId;
    const world = await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    const contextId = isObject(world) ? world.executionContextId : undefined;
    if (typeof contextId !== "number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:id,executionContextId:contextId},{sessionId});
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Selector target is unavailable; observe again");
    try {
      const readRole=async():Promise<string>=>{
        const tree=await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:frame.id},{sessionId});
        if(!isObject(tree) || !Array.isArray(tree.nodes))throw new RetryablePreflightError("Accessibility tree unavailable; observe again");
        const node=tree.nodes.find(item=>isObject(item) && item.backendDOMNodeId===id);
        return isObject(node) && isObject(node.role) && typeof node.role.value==="string" ? node.role.value : "";
      };
      const role=mode === "editable" ? await readRole() : "";
      const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:mode},{value:attribute},{value:role}],functionDeclaration:`function(mode,name,role) { if (!this.isConnected) return null; if(mode==='inputValue')return (${inputValueFunction}).call(this); if(mode==='editable')return (${editableFunction}).call(this,role); if(mode==='visible'){const r=this.getBoundingClientRect();return {value:getComputedStyle(this).visibility==='visible' && r.width>0 && r.height>0};} if(mode==='checked'){if(this instanceof HTMLInputElement && ['checkbox','radio'].includes(this.type))return {value:this.indeterminate ? null : this.checked};const role=(this.getAttribute('role') || '').trim().split(/\\s+/)[0], checked=this.getAttribute('aria-checked');if(['checkbox','radio','switch','menuitemcheckbox','menuitemradio'].includes(role) && ['true','false'].includes(checked))return {value:checked==='true'};return {value:null};} if(mode==='enabled'){for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true')return {value:false};return {value:true};} const value=mode === 'attribute' ? this.getAttribute(name) : this[mode]; return {value:typeof value === 'string' ? value.slice(0,30001) : null}; }`},{sessionId});
      const payload = isObject(result) && isObject(result.result) ? result.result.value : undefined;
      if(mode === "editable" && await readRole() !== role)throw new RetryablePreflightError("Target role changed; observe again");
      if (isObject(payload) && payload.error === "not-editable") throw new Error("Target does not support editable state");
      if (isObject(payload) && payload.error === "redacted") throw new Error("Password values are redacted");
      if (isObject(payload) && payload.error === "unsupported") throw new Error("Target is not an input, textarea or select");
      if (isObject(payload) && mode === "checked" && payload.value === null) throw new Error("Target does not have a binary checked state");
      if (!isObject(payload) || (["visible","enabled","checked","editable"].includes(mode) ? typeof payload.value !== "boolean" : typeof payload.value !== "string" && payload.value !== null)) throw new RetryablePreflightError("Selector target is unavailable; observe again");
      if (typeof payload.value === "string" && payload.value.length > 30_000) throw new Error("Locator value exceeds the 30000 character limit");
      const frameVisible = mode === "visible" && payload.value === true ? await this.cssFrameVisible(frame,snapshot.frames) : true;
      const fresh = await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
      if (fresh.documentId !== snapshot.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids) !== JSON.stringify(snapshot.ids)) throw new RetryablePreflightError("Selector target changed; observe again");
      return mode === "visible" && payload.value === true ? frameVisible : payload.value as string | boolean | null;
    } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
  }

  /** @internal */
  async actCss(snapshot: CssSnapshot, id: number, hover: boolean, key?: string, text?: string, doubleClick = false, checked?: boolean, selection?: SelectSpec[], append = false, mouse:MouseClick = {button:"left",buttons:1,modifiers:0}, domIdentity?:DomIdentity, domConnectionGeneration?:number, focusOnly = false): Promise<void | string[]> {
    if (key !== undefined) this.parseKey(key);
    const frame = snapshot.frame;
    if (!frame || !snapshot.ids.includes(id)) throw new RetryablePreflightError("Selector target changed; observe again");
    const sessionId = frame.sessionId;
    const world = await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    const contextId = isObject(world) ? world.executionContextId : undefined;
    if (typeof contextId !== "number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:id,executionContextId:contextId},{sessionId});
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Selector target is unavailable; observe again");
    let inputIssued = false;
    try {
      if (focusOnly) {
        const verify=async()=>{const fresh=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);if(fresh.documentId!==snapshot.documentId || JSON.stringify(fresh.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids)!==JSON.stringify(snapshot.ids))throw new RetryablePreflightError("Selector target changed; observe again");};
        await verify();this.#observation=undefined;inputIssued=true;
        await this.browser.cdp.call(this.id,"DOM.focus",{objectId},{sessionId});
        const focused=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function(){if(!this.isConnected)return false;let element=this;while(true){const root=element.getRootNode();if(root.activeElement!==element)return false;if(!(root instanceof ShadowRoot))return true;element=root.host}}`},{sessionId});
        if(!isObject(focused) || !isObject(focused.result) || focused.result.value!==true || !await this.targetFrameFocused(frame.id,id,snapshot.frames))throw new Error("Target lost focus; observe again");
        await verify();return;
      }
      const chain = frameAncestry(frame,snapshot.frames);
      const measure = async () => {
        const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:hover},{value:!!mouse.force}],functionDeclaration:`function(allowDisabled,force) {
          if (!this.isConnected) return null;
          if (!allowDisabled) for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return null;
          this.scrollIntoView({block:'center',inline:'center'});
          const r=this.getBoundingClientRect(), x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2, y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;
          if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
          if(force)return {x,y,width:r.width,height:r.height};
          let target=this, root=target.getRootNode();
          while (true) { const hit=root.elementFromPoint(x,y); if (!hit || (hit!==target && !target.contains(hit))) return null; if (!(root instanceof ShadowRoot)) return {x,y,width:r.width,height:r.height}; target=root.host; root=target.getRootNode(); }
        }`},{sessionId});
        const value = isObject(result) && isObject(result.result) ? result.result.value : null;
        if (!isObject(value) || ![value.x,value.y,value.width,value.height].every(v=>typeof v === "number" && Number.isFinite(v)) || (value.width as number) <= 0 || (value.height as number) <= 0) throw new RetryablePreflightError("Target is hidden, disabled, or covered; observe again");
        const geometry = {x:value.x as number,y:value.y as number,width:value.width as number,height:value.height as number};
        let point = {x:geometry.x,y:geometry.y}, inputPoint = point;
        for (let i=0;i<chain.length;i++) {
          const ownerSession=chain[i+1]?.sessionId;
          point=await this.framePoint(chain[i].id,chain[i].parentId,point.x,point.y,ownerSession,!!mouse.force);
          if (ownerSession===sessionId) inputPoint=point;
        }
        await this.validateFrames(chain);
        if (await this.documentId() !== snapshot.documentId) throw new RetryablePreflightError("Page changed; observe again");
        return {geometry,point,inputPoint};
      };
      const first=await measure();
      await new Promise(resolve=>setTimeout(resolve,75));
      const second=await measure();
      const moving=(a:number,b:number)=>Math.abs(a-b)>0.25;
      if (moving(first.geometry.x,second.geometry.x) || moving(first.geometry.y,second.geometry.y) || moving(first.geometry.width,second.geometry.width) || moving(first.geometry.height,second.geometry.height) || moving(first.point.x,second.point.x) || moving(first.point.y,second.point.y)) throw new RetryablePreflightError("Target is moving; observe again");
      const fresh=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
      if (fresh.documentId!==snapshot.documentId || JSON.stringify(fresh.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds)!==JSON.stringify(snapshot.scopeIds) || (domIdentity ? !fresh.ids.includes(id) : JSON.stringify(fresh.ids)!==JSON.stringify(snapshot.ids))) throw new RetryablePreflightError("Selector target changed; observe again");
      const checkedState = async () => {
        const result=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function() {
          if (!this.isConnected) return null;
          if (this instanceof HTMLInputElement && ['checkbox','radio'].includes(this.type)) return {value:this.indeterminate ? null : this.checked,radio:this.type==='radio'};
          const role=(this.getAttribute('role') || '').trim().split(/\\s+/)[0], checked=this.getAttribute('aria-checked');
          if (!['checkbox','radio','switch','menuitemcheckbox','menuitemradio'].includes(role) || !['true','false'].includes(checked)) return {value:null,radio:false};
          return {value:checked==='true',radio:role==='radio' || role==='menuitemradio'};
        }`},{sessionId});
        const value=isObject(result) && isObject(result.result) ? result.result.value : null;
        if (!isObject(value) || typeof value.value !== "boolean" || typeof value.radio !== "boolean") throw new Error("Target does not have a binary checked state");
        return {value:value.value,radio:value.radio};
      };
      if (checked !== undefined) {
        const state=await checkedState();
        const latest=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
        if (latest.documentId!==snapshot.documentId || JSON.stringify(latest.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids)!==JSON.stringify(snapshot.ids)) throw new RetryablePreflightError("Selector target changed; observe again");
        const current=await checkedState();
        if (current.value!==state.value || current.radio!==state.radio) throw new RetryablePreflightError("Checked state changed; observe again");
        if (current.value===checked) return;
        if (!checked && current.radio) throw new Error("A selected radio cannot be unchecked directly");
      }
      if (selection !== undefined) {
        const inspected=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:selection}],functionDeclaration:`function(specs) {
          if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.matches(':disabled') || this.getAttribute('aria-disabled')==='true') return {status:'not-select'};
          if (!this.multiple && specs.length>1) return {status:'multiple'};
          const options=Array.from(this.options),chosen=[];
          for(const spec of specs) {
            const hits=options.map((option,index)=>({option,index})).filter(({option,index})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.index===undefined || index===spec.index) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));
            if(!hits.length)return {status:'missing'};
            if(hits.length>1 || chosen.some(item=>item.index===hits[0].index))return {status:'ambiguous'};
            chosen.push({index:hits[0].index,value:hits[0].option.value,label:hits[0].option.label});
          }
          return {status:'ok',chosen};
        }`},{sessionId});
        const found=isObject(inspected) && isObject(inspected.result) ? inspected.result.value : null;
        if (!isObject(found) || typeof found.status!=="string") throw new Error("Invalid select options result");
        if (found.status==='missing') throw new RetryablePreflightError("Requested select option is unavailable");
        if (found.status==='ambiguous') throw new Error("Requested select option is ambiguous");
        if (found.status==='multiple') throw new Error("Multiple options require a multiple select");
        if (found.status!=='ok' || !Array.isArray(found.chosen)) throw new Error("Target is not an enabled native select");
        const latest=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
        if (latest.documentId!==snapshot.documentId || JSON.stringify(latest.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids)!==JSON.stringify(snapshot.ids)) throw new RetryablePreflightError("Selector target changed; observe again");
        this.#observation=undefined;
        inputIssued=true;
        const applied=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:found.chosen},{value:selection}],functionDeclaration:`function(chosen,specs) {
          if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.matches(':disabled') || this.getAttribute('aria-disabled')==='true' || (!this.multiple && chosen.length>1)) return null;
          for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true') return null;
          const options=Array.from(this.options);
          for(let i=0;i<specs.length;i++) {const spec=specs[i],hits=options.map((option,index)=>({option,index})).filter(({option,index})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.index===undefined || index===spec.index) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));if(hits.length!==1 || hits[0].index!==chosen[i]?.index)return null;}
          if(chosen.some(item=>{const o=options[item.index];return !o || o.value!==item.value || o.label!==item.label || o.disabled || (o.parentElement instanceof HTMLOptGroupElement && o.parentElement.disabled)}))return null;
          if(!this.multiple && !chosen.length)this.selectedIndex=-1;
          else {const indices=new Set(chosen.map(item=>item.index));for(let i=0;i<options.length;i++)options[i].selected=indices.has(i);}
          this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));this.dispatchEvent(new Event('change',{bubbles:true}));
          return this.isConnected ? Array.from(this.selectedOptions,option=>option.value) : null;
        }`},{sessionId});
        const selected=isObject(applied) && isObject(applied.result) ? applied.result.value : null;
        const expected=found.chosen.map(item=>isObject(item) ? item.value : null);
        if (!Array.isArray(selected) || selected.some(value=>typeof value!=="string") || JSON.stringify([...selected].sort())!==JSON.stringify([...expected].sort())) throw new Error("Select did not retain the requested options");
        return selected as string[];
      }
      if (text !== undefined) {
        const editable=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:text},{value:append}],functionDeclaration:`function(value,append) {
          if (!this.isConnected || this.disabled || this.readOnly || this.getAttribute('aria-readonly') === 'true') return 'unsupported';
          if (this instanceof HTMLInputElement && ['date','time','month','week','datetime-local'].includes(this.type)) { if(append)return 'temporal-append';const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;return probe.value===value ? 'temporal' : 'invalid'; }
          if (!append && this instanceof HTMLInputElement && this.type==='number') {const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;if(probe.value!==value)return 'invalid-number';}
          return this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type)) ? 'text' : 'unsupported';
        }`},{sessionId});
        const status=isObject(editable) && isObject(editable.result) ? editable.result.value : undefined;
        if (status==='temporal-append') throw new Error("Use fill for date and time inputs");
        if (status==='invalid') throw new Error("Invalid date or time value");
        if (status==='invalid-number') throw new Error("Invalid number value");
        if (status==='temporal') {
          const latest=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
          if (latest.documentId!==snapshot.documentId || JSON.stringify(latest.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids)!==JSON.stringify(snapshot.ids)) throw new RetryablePreflightError("Selector target changed; observe again");
          this.#observation=undefined;
          inputIssued=true;
          const applied=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:text}],functionDeclaration:`function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly || this.getAttribute('aria-readonly')==='true') return false; for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true') return false; const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;if(probe.value!==value)return false; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;if(!setter)return false;setter.call(this,value);this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));this.dispatchEvent(new Event('change',{bubbles:true}));return this.isConnected && this.value===value; }`},{sessionId});
          if (!isObject(applied) || !isObject(applied.result) || applied.result.value!==true) throw new Error("Date or time input did not retain the requested value");
          return;
        }
        if (status!=='text') throw new Error("Target is not an editable text field");
      }
      const verifyDomIdentity=async()=>{
        if(!domIdentity)return;
        if(this.browser.client.connectionGeneration!==domConnectionGeneration)throw new RetryablePreflightError('Connection changed; observe again');
        const result=await this.browser.cdp.call(this.id,'Runtime.callFunctionOn',{objectId,returnByValue:true,functionDeclaration:domIdentityFunction},{sessionId});
        const value=isObject(result) && isObject(result.result) ? result.result.value : null;
        if(this.browser.client.connectionGeneration!==domConnectionGeneration || !isObject(value) || value.tag!==domIdentity.tag || value.role!==domIdentity.role || value.name!==domIdentity.name || value.type!==domIdentity.type || value.disabled!==domIdentity.disabled || value.checked!==domIdentity.checked)throw new RetryablePreflightError('DOM target changed; observe again');
      };
      await verifyDomIdentity();
      this.#observation=undefined;
      const options={sessionId,...(sessionId ? {visualPoint:second.point} : {}),...(domConnectionGeneration !== undefined ? {expectedGeneration:domConnectionGeneration} : {})};
      inputIssued=true;
      if (key !== undefined || text !== undefined) {
        await this.browser.cdp.call(this.id,"DOM.focus",{objectId},{sessionId});
        const verifyFocus = async () => {
          const afterFocus=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
          if (afterFocus.documentId!==snapshot.documentId || JSON.stringify(afterFocus.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(afterFocus.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(afterFocus.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(afterFocus.ids)!==JSON.stringify(snapshot.ids)) throw new Error("Selector target changed after focus; observe again");
          if ((await this.focusedInputFrame()).id !== frame.id) throw new Error("Target frame lost focus; observe again");
          const focused=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:text !== undefined},{value:text ?? ''},{value:append}],functionDeclaration:`function(editable,value,append) { if (!this.isConnected) return false; for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return false; if (editable && (this.readOnly || this.getAttribute('aria-readonly') === 'true' || !(this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type))))) return false; if(editable && !append && this instanceof HTMLInputElement && this.type==='number'){const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;if(probe.value!==value)return 'invalid-number';} let element=this; while (true) { const root=element.getRootNode(); if (root.activeElement!==element) return false; if (!(root instanceof ShadowRoot)) return true; element=root.host; } }`},{sessionId});
          if (isObject(focused) && isObject(focused.result) && focused.result.value==='invalid-number') throw new Error("Invalid number value");
          if (!isObject(focused) || !isObject(focused.result) || focused.result.value!==true) throw new Error("Target lost focus or is not editable; observe again");
        };
        await verifyFocus();
        if (key !== undefined) { await this.sendKey(key,sessionId); return; }
        if (text === undefined) throw new Error("Text is unavailable");
        if (append) { if(text) await this.browser.cdp.call(this.id,"Input.insertText",{text},{sessionId}); return; }
        await this.sendKey(process.platform === "darwin" ? "Meta+A" : "Control+A",sessionId);
        await verifyFocus();
        const selected=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function() { if (this.isContentEditable) { const selection=this.getRootNode().getSelection?.() ?? getSelection(); return !!selection && selection.toString()===this.innerText; } return this.selectionStart===null || (this.selectionStart===0 && this.selectionEnd===this.value.length); }`},{sessionId});
        if (!isObject(selected) || !isObject(selected.result) || selected.result.value!==true) throw new Error("Could not select the text field contents");
        if (text) await this.browser.cdp.call(this.id,"Input.insertText",{text},{sessionId});
        else await this.sendKey("Backspace",sessionId);
        const applied=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,arguments:[{value:text}],functionDeclaration:`function(value) { return this.isConnected && (this.isContentEditable ? this.innerText : this.value)===value; }`},{sessionId});
        if (!isObject(applied) || !isObject(applied.result) || applied.result.value!==true) throw new Error("Text field did not retain the requested value");
        return;
      }
      const pointerPoint=mouse.force ? second.point : second.inputPoint;
      const pointerOptions=mouse.force ? (domConnectionGeneration !== undefined ? {expectedGeneration:domConnectionGeneration} : {}) : options;
      if (hover) await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseMoved",...pointerPoint,button:"none",buttons:0},pointerOptions);
      else {
        await this.dispatchClick(pointerPoint,mouse,1,pointerOptions);
        if (checked !== undefined) {
          const latest=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
          if (latest.documentId!==snapshot.documentId || JSON.stringify(latest.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids)!==JSON.stringify(snapshot.ids) || (await checkedState()).value!==checked) throw new Error("Target did not retain the requested checked state");
        }
        if (doubleClick) {
          const after=await measure();
          if (moving(second.geometry.x,after.geometry.x) || moving(second.geometry.y,after.geometry.y) || moving(second.geometry.width,after.geometry.width) || moving(second.geometry.height,after.geometry.height) || moving(second.point.x,after.point.x) || moving(second.point.y,after.point.y)) throw new Error("Target moved after the first click; observe again");
          const latest=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
          if (latest.documentId!==snapshot.documentId || JSON.stringify(latest.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds)!==JSON.stringify(snapshot.scopeIds) || (domIdentity ? !latest.ids.includes(id) : JSON.stringify(latest.ids)!==JSON.stringify(snapshot.ids))) throw new Error("Selector target changed after the first click; observe again");
          await verifyDomIdentity();
          await this.dispatchClick(pointerPoint,mouse,2,pointerOptions);
        }
      }
    } catch (error) {
      if (inputIssued && error instanceof RetryablePreflightError) throw new Error(error.message,{cause:error});
      throw error;
    } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
  }

  /** @internal */
  async triggerMediaDownload(backendNodeId:number, frame:FrameInfo, verify:()=>Promise<unknown>):Promise<void> {
    const sessionId=frame.sessionId;
    const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    if (!isObject(world) || typeof world.executionContextId!=="number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId,executionContextId:world.executionContextId},{sessionId});
    const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId!=="string") throw new RetryablePreflightError("Download target is unavailable; observe again");
    try {
      await verify();
      const result=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,userGesture:true,functionDeclaration:`function() {
        if (!this.isConnected) return 'stale';
        const element=this.nodeType===3 ? this.parentElement : this;
        const target=element?.closest?.('img,video,audio,source,a[href]') ?? element?.querySelector?.('img,video,audio,source,a[href]');
        const value=target?.currentSrc || target?.src || target?.href;
        if (!value) return 'missing';
        let url;try {url=new URL(value,document.baseURI)} catch {return 'invalid'}
        if (!['http:','https:','blob:','data:'].includes(url.protocol)) return 'invalid';
        if (['http:','https:'].includes(url.protocol) && url.origin!==location.origin) return 'cross-origin';
        const anchor=document.createElement('a');anchor.href=url.href;anchor.download='';anchor.rel='noopener';anchor.style.display='none';document.documentElement.append(anchor);
        try {anchor.click()} finally {anchor.remove()};return 'ok';
      }`},{sessionId});
      const value=isObject(result) && isObject(result.result) ? result.result.value : undefined;
      if (value==='stale') throw new RetryablePreflightError("Download target changed; observe again");
      if (value==='missing') throw new Error("Target does not expose a media URL");
      if (value==='invalid') throw new Error("Invalid media URL");
      if (value==='cross-origin') throw new Error("Cross-origin media downloads are not supported");
      if (value!=='ok') throw new Error("Media download outcome is unknown");
    } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
  }

  /** @internal */
  async locatorRead(snapshotId: string, index: number, mode: "innerText" | "textContent" | "attribute" | "enabled" | "visible" | "checked" | "inputValue" | "editable", attribute = ""): Promise<string | boolean | null> {
    const observation = this.#observation;
    if (!observation || observation.id !== snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    const target = observation.nodes.find(node => node.index === index);
    if (!target || await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
    if (target.frameChain) await this.validateFrames(target.frameChain);
    await this.verifyLocatorScope(observation, target);
    const sessionId = target.frameChain?.[0]?.sessionId;
    const tree = target.frameId ? await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:target.frameId},{sessionId}) : await this.getAXState();
    const fresh = interactiveNodes(tree,0,true).find(node => node.backendNodeId === target.backendNodeId && node.role === target.role);
    if (!fresh || fresh.name !== target.name || fresh.stateKey !== target.stateKey) throw new RetryablePreflightError("Target changed; observe again");
    if (mode === "checked") {
      if (typeof fresh.checked !== "boolean") throw new Error("Target does not have a binary checked state");
      if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      if (target.frameChain) await this.validateFrames(target.frameChain);
      await this.verifyLocatorScope(observation,target);
      return fresh.checked;
    }
    let executionContextId:number | undefined;
    if (mode === "inputValue" || mode === "editable") {
      const frameId=target.frameId ?? observation.frames?.[0]?.id;
      if (!frameId) throw new RetryablePreflightError("Target frame is unavailable; observe again");
      const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId,worldName:"open-browser-use-selector"},{sessionId});
      if (!isObject(world) || typeof world.executionContextId !== "number") throw new RetryablePreflightError("Target context is unavailable; observe again");
      executionContextId=world.executionContextId;
    }
    const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:target.backendNodeId,...(executionContextId === undefined ? {} : {executionContextId})},{sessionId});
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Target is unavailable; observe again");
    try {
      const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{
        objectId,returnByValue:true,arguments:[{value:mode},{value:attribute},{value:fresh.role}],
        functionDeclaration:`function(mode, name, role) { if (!this.isConnected) return null; if (mode === 'inputValue') return (${inputValueFunction}).call(this); if (mode === 'editable') return (${editableFunction}).call(this,role); if (mode === 'enabled' || mode === 'visible') { const element = this.nodeType === 3 ? this.parentElement : this; if (!(element instanceof Element)) return null; if (mode === 'visible') { const r = this.nodeType === 3 ? (() => {const range=document.createRange();range.selectNode(this);return range.getBoundingClientRect();})() : element.getBoundingClientRect(); return {value:getComputedStyle(element).visibility === 'visible' && r.width > 0 && r.height > 0}; } for (let el=element; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return {value:false}; return {value:true}; } const value = mode === 'attribute' ? (this.nodeType === 1 ? this.getAttribute(name) : null) : mode === 'textContent' || this.nodeType === 3 ? this.textContent : this.innerText; return {value: typeof value === 'string' ? value.slice(0, 30001) : null}; }`
      },{sessionId});
      const payload = isObject(result) && isObject(result.result) ? result.result.value : undefined;
      if (isObject(payload) && payload.error === "not-editable") throw new Error("Target does not support editable state");
      if (isObject(payload) && payload.error === "redacted") throw new Error("Password values are redacted");
      if (isObject(payload) && payload.error === "unsupported") throw new Error("Target is not an input, textarea or select");
      if (!isObject(payload) || (["enabled","visible","editable"].includes(mode) ? typeof payload.value !== "boolean" : typeof payload.value !== "string" && payload.value !== null)) throw new RetryablePreflightError("Target value is unavailable; observe again");
      const value = payload.value;
      if (value === null && mode === "innerText") throw new RetryablePreflightError("Target text is unavailable; observe again");
      if (typeof value === "string" && value.length > 30_000) throw new Error("Locator value exceeds the 30000 character limit");
      if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      if (target.frameChain) await this.validateFrames(target.frameChain);
      if (mode === "visible" && value === true) {
        let frameVisible = true;
        for (let i=0; i<(target.frameChain?.length ?? 0); i++) {
          const frame = target.frameChain![i], ownerSession = target.frameChain![i+1]?.sessionId;
          const owner = await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:frame.id},{sessionId:ownerSession});
          if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
          const result = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:owner.backendNodeId},{sessionId:ownerSession});
          const ownerId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
          if (typeof ownerId !== "string") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
          try {
            const visibility = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId:ownerId,returnByValue:true,functionDeclaration:`function() { if (!this.isConnected) return null; const r=this.getBoundingClientRect(); return getComputedStyle(this).visibility === 'visible' && r.width > 0 && r.height > 0; }`},{sessionId:ownerSession});
            const visible = isObject(visibility) && isObject(visibility.result) ? visibility.result.value : undefined;
            if (typeof visible !== "boolean") throw new RetryablePreflightError("Frame owner changed; observe again");
            if (!visible) { frameVisible = false; break; }
          } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId:ownerId},{sessionId:ownerSession}).catch(() => {}); }
        }
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        if (target.frameChain) await this.validateFrames(target.frameChain);
        return frameVisible;
      }
      return mode === "enabled" ? value === true && !fresh.disabled : value as string | boolean | null;
    } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(() => {}); }
  }

  /** @internal */
  async scopeVisible(observation: Observation, index: number): Promise<boolean> {
    const node=observation.nodes.find(item=>item.index===index);
    const frame=observation.frames?.find(item=>item.id===(node?.frameId ?? observation.frames?.[0]?.id));
    if (!node || !frame || !observation.frames) throw new RetryablePreflightError("Filter scope is unavailable; observe again");
    const sessionId=frame.sessionId;
    const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    if (!isObject(world) || typeof world.executionContextId!=="number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:node.backendNodeId,executionContextId:world.executionContextId},{sessionId});
    const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId!=="string") throw new RetryablePreflightError("Filter scope is unavailable; observe again");
    try {
      const result=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function() { if(!this.isConnected)return null;const element=this.nodeType===3 ? this.parentElement : this;if(!(element instanceof Element))return null;const r=this.nodeType===3 ? (()=>{const range=document.createRange();range.selectNode(this);return range.getBoundingClientRect()})() : element.getBoundingClientRect();return getComputedStyle(element).visibility==='visible' && r.width>0 && r.height>0; }`},{sessionId});
      const visible=isObject(result) && isObject(result.result) ? result.result.value : undefined;
      if (typeof visible!=="boolean") throw new RetryablePreflightError("Filter scope changed; observe again");
      const frameVisible=visible ? await this.cssFrameVisible(frame,observation.frames) : false;
      if (await this.documentId()!==observation.documentId || JSON.stringify(await this.frameTree())!==JSON.stringify(observation.frames)) throw new RetryablePreflightError("Frame tree changed; observe again");
      return visible && frameVisible;
    } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
  }

  /** @internal */
  async scopeText(observation: Observation, index: number): Promise<string> {
    const scope = observation.nodes.find(node => node.index === index);
    if (!scope) throw new RetryablePreflightError("Scope changed; observe again");
    const membership=new Map<string,boolean>(), extra:UnindexedText[]=[];
    for (const item of observation.unindexedText) {
      if (item.backendNodeId === undefined) throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
      const key = `${item.frameId ?? "root"}:${item.backendNodeId}`;
      let inside=membership.get(key);
      if(inside===undefined) {
        if (scope.frameId === item.frameId && item.ancestors.includes(scope.backendNodeId)) inside=true;
        else {
          const probe: ObservedNode = {index:-1,role:"",name:"",stateKey:"",backendNodeId:item.backendNodeId,frameId:item.frameId,frameChain:item.frameChain};
          const withProbe = {...observation,nodes:[...observation.nodes,probe]};
          inside=await this.scopeContains(withProbe,index,-1);
          if(!inside && await this.scopeContains(withProbe,-1,index))throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
        }
        membership.set(key,inside);
      }
      if(inside)extra.push(item);
    }
    const textNodes = observation.nodes.filter(node => node.name && node.role === "StaticText");
    const included = new Set<number>();
    if (scope.role === "StaticText") included.add(scope.index);
    const sameFrame = textNodes.filter(node => node.index !== index && node.frameId === scope.frameId);
    if (sameFrame.length) {
      if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      if (scope.frameChain) await this.validateFrames(scope.frameChain);
      const sessionId = scope.frameChain?.[0]?.sessionId;
      const objects: string[] = [];
      const resolve = async (node: ObservedNode): Promise<string> => {
        const result = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:node.backendNodeId},{sessionId});
        const objectId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
        if (typeof objectId !== "string") throw new RetryablePreflightError("Scope target is unavailable; observe again");
        return objectId;
      };
      try {
        const scopeObject = await resolve(scope); objects.push(scopeObject);
        for (let offset=0; offset<sameFrame.length; offset+=32) {
          const batch = sameFrame.slice(offset,offset+32);
          const resolved = await Promise.allSettled(batch.map(resolve));
          for (const result of resolved) if (result.status === "fulfilled") objects.push(result.value);
          const failure = resolved.find(result => result.status === "rejected");
          if (failure?.status === "rejected") throw failure.reason;
          const targetObjects = resolved.map(result => (result as PromiseFulfilledResult<string>).value);
          const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{
            objectId:scopeObject, arguments:targetObjects.map(objectId=>({objectId})), returnByValue:true,
            functionDeclaration:`function(...targets) { return targets.map(target => { if (!this.isConnected || !target.isConnected) return null; if (target===this) return false; for (let node=target; node; node=node.parentNode || node.getRootNode()?.host) if (node===this) return true; return false; }); }`
          },{sessionId});
          const values = isObject(result) && isObject(result.result) ? result.result.value : undefined;
          if (!Array.isArray(values) || values.length !== batch.length || values.some(value => typeof value !== "boolean")) throw new RetryablePreflightError("Scope target changed; observe again");
          for (let i=0; i<batch.length; i++) if (values[i]) included.add(batch[i].index);
          await Promise.allSettled(targetObjects.map(objectId=>this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId})));
          objects.splice(1);
        }
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        if (scope.frameChain) await this.validateFrames(scope.frameChain);
      } finally {
        await Promise.allSettled(objects.map(objectId=>this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId})));
      }
    }
    const frameMembership = new Map<string,boolean>();
    for (const node of textNodes) {
      if (node.frameId === scope.frameId) continue;
      const key = node.frameId ?? "root";
      if (!frameMembership.has(key)) frameMembership.set(key,await this.scopeContains(observation,index,node.index));
      if (frameMembership.get(key)) included.add(node.index);
    }
    const parts=[...textNodes.filter(node=>included.has(node.index)).map(node=>({name:node.name,frameId:node.frameId,axOrder:node.axOrder ?? 0})),...extra];
    const order=(frameId?:string)=>frameId ? Math.max(0,observation.frames?.findIndex(frame=>frame.id===frameId) ?? 0) : 0;
    parts.sort((a,b)=>order(a.frameId)-order(b.frameId) || a.axOrder-b.axOrder);
    if(parts.reduce((sum,item)=>sum+item.name.length+1,0)>30_000)throw new Error("Locator text exceeds the 30000 character limit");
    return parts.map(item=>item.name).join(" ").replace(/\s+/g," ").trim();
  }

  /** @internal */
  async freshFilterObservation(): Promise<Observation> {
    const documentId = await this.documentId();
    await this.browser.cdp.enableFrameSessions(this.id);
    const frames = await this.frameTree();
    const tree = await this.getAXState();
    const unindexedText: UnindexedText[] = unindexedTextAncestors(tree);
    const nodes: ObservedNode[] = interactiveNodes(tree,0,true);
    for (const frame of frames.slice(1)) {
      const tree = await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:frame.id},{sessionId:frame.sessionId});
      unindexedText.push(...unindexedTextAncestors(tree).map(item=>({...item,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
      nodes.push(...interactiveNodes(tree,nodes.length,true).map(node => ({...node,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
    }
    if (documentId !== await this.documentId() || JSON.stringify(frames) !== JSON.stringify(await this.frameTree())) throw new RetryablePreflightError("Page changed; observe again");
    return {id:"",documentId,nodes,unindexedText,frames,guards:new Map()};
  }

  /** @internal */
  async scopeContains(observation: Observation, scopeIndex: number, targetIndex: number): Promise<boolean> {
    const scope = observation.nodes.find(node => node.index === scopeIndex);
    const target = observation.nodes.find(node => node.index === targetIndex);
    if (!scope || !target) throw new RetryablePreflightError("Scope changed; observe again");
    if (scopeIndex === targetIndex) return false;
    if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
    if (scope.frameChain) await this.validateFrames(scope.frameChain);
    if (target.frameChain) await this.validateFrames(target.frameChain);
    const sessionId = scope.frameChain?.[0]?.sessionId;
    let backendNodeId = target.backendNodeId;
    if (scope.frameId !== target.frameId) {
      const chain = target.frameChain ?? [];
      const frame = scope.frameId ? chain.find(item => item.parentId === scope.frameId) : chain.at(-1);
      if (!frame) return false;
      const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", {frameId:frame.id}, {sessionId});
      if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner changed; observe again");
      backendNodeId = owner.backendNodeId;
    }
    const objects: string[] = [];
    try {
      for (const id of [scope.backendNodeId,backendNodeId]) {
        const result = await this.browser.cdp.call(this.id, "DOM.resolveNode", {backendNodeId:id}, {sessionId});
        const objectId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
        if (typeof objectId !== "string") throw new RetryablePreflightError("Scope target is unavailable; observe again");
        objects.push(objectId);
      }
      const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
        objectId:objects[0], arguments:[{objectId:objects[1]}], returnByValue:true,
        functionDeclaration:`function(target) { if (!this.isConnected || !target.isConnected || target===this) return false; for (let node=target; node; node=node.parentNode || node.getRootNode()?.host) if (node===this) return true; return false; }`
      }, {sessionId});
      if (!isObject(result) || !isObject(result.result) || typeof result.result.value !== "boolean") throw new Error("Could not verify locator scope");
      if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      if (scope.frameChain) await this.validateFrames(scope.frameChain);
      if (target.frameChain) await this.validateFrames(target.frameChain);
      return result.result.value;
    } finally {
      for (const objectId of objects) await this.browser.cdp.call(this.id, "Runtime.releaseObject", {objectId}, {sessionId}).catch(() => {});
    }
  }

  /** @internal */
  async cssScopeContains(observation: Observation, snapshot: CssSnapshot, scopeId: number, targetIndex: number): Promise<boolean> {
    const frame=snapshot.frame,target=observation.nodes.find(node=>node.index===targetIndex);
    if (!frame || !target || !snapshot.ids.includes(scopeId) || observation.documentId!==snapshot.documentId || JSON.stringify(observation.frames)!==JSON.stringify(snapshot.frames)) throw new RetryablePreflightError("CSS scope changed; observe again");
    if ((target.frameId ?? snapshot.frames[0].id)!==frame.id) return false;
    const sessionId=frame.sessionId;
    const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{sessionId});
    if (!isObject(world) || typeof world.executionContextId!=="number") throw new RetryablePreflightError("Selector context is unavailable; observe again");
    const objects:string[]=[];
    try {
      for(const id of [scopeId,target.backendNodeId]) {
        const resolved=await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:id,executionContextId:world.executionContextId},{sessionId});
        const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if(typeof objectId!=="string") throw new RetryablePreflightError("Scope target is unavailable; observe again");
        objects.push(objectId);
      }
      const result=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId:objects[0],arguments:[{objectId:objects[1]}],returnByValue:true,functionDeclaration:`function(target) {if(!this.isConnected || !target.isConnected)return null;if(target===this)return false;for(let node=target;node;node=node.parentNode || node.getRootNode()?.host)if(node===this)return true;return false;}`},{sessionId});
      const value=isObject(result) && isObject(result.result) ? result.result.value : undefined;
      if(typeof value!=="boolean") throw new RetryablePreflightError("Scope target changed; observe again");
      if(await this.documentId()!==observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      return value;
    } finally { for(const objectId of objects) await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId}).catch(()=>{}); }
  }

  private async verifyLocatorScope(observation: Observation, target: ObservedNode): Promise<void> {
    const guard = observation.guards.get(target.index);
    if (guard?.css) {
      const {snapshot,scopeId}=guard.css, fresh=await this.queryCss(snapshot.step,snapshot.framePath,snapshot.scopes,snapshot.semantic?.scope,undefined,snapshot.frameId);
      if(fresh.documentId!==snapshot.documentId || JSON.stringify(fresh.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots)!==JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds)!==JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids)!==JSON.stringify(snapshot.ids) || !await this.cssScopeContains(observation,snapshot,scopeId,guard.scopes[0] ?? target.index)) throw new RetryablePreflightError("CSS scope changed; observe again");
    }
    if (guard?.framePath && await this.resolveFramePath(guard.framePath) !== target.frameId) throw new RetryablePreflightError("Frame selector changed; observe again");
    const scopes = guard?.scopes ?? [];
    for (let i=0; i<scopes.length; i++) {
      const scope = observation.nodes.find(node => node.index === scopes[i]);
      if (!scope) throw new RetryablePreflightError("Scope changed; observe again");
      const sessionId = scope.frameChain?.[0]?.sessionId;
      const tree = scope.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", {frameId:scope.frameId}, {sessionId}) : await this.getAXState();
      const current = interactiveNodes(tree,0,true).find(node => node.backendNodeId === scope.backendNodeId && node.role === scope.role);
      if (!current || current.name !== scope.name || current.stateKey !== scope.stateKey) throw new RetryablePreflightError("Scope changed; observe again");
      if (!await this.scopeContains(observation,scope.index,scopes[i+1] ?? target.index)) throw new RetryablePreflightError("Target moved outside scope; observe again");
    }
    if (guard?.filters.length) {
      const fresh = await this.freshFilterObservation();
      if (fresh.documentId !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
      for (const item of guard.filters) {
        const original = observation.nodes.find(node => node.index === item.index);
        const current = original && fresh.nodes.find(node => node.backendNodeId === original.backendNodeId && node.frameId === original.frameId && node.role === original.role);
        if (!original || !current || current.name !== original.name || current.stateKey !== original.stateKey) throw new RetryablePreflightError("Filtered target changed; observe again");
        const textFilters=item.filters.filter(filter=>filter.hasText !== undefined || filter.hasNotText !== undefined);
        if (textFilters.length && !matchesTextFilters(await this.scopeText(fresh,current.index),textFilters)) throw new RetryablePreflightError("Locator text changed; observe again");
      }
    }
    if (guard?.role) await guard.role.locator.verifyMatches(observation,guard.role.expected);
  }

  private async prepareBrowserEvent(method: string, readyMethod: string, timeoutMs: number): Promise<{result: Promise<JsonValue>}> {
    const waitId = randomUUID(), client = this.browser.client;
    let remove = () => {};
    const ready = new Promise<void>(resolve => {
      remove = client.onNotification(event => {
        if (event.method === readyMethod && isObject(event.params) && event.params.waitId === waitId) resolve();
      });
    });
    const result = Promise.resolve().then(() => client.request(method, {tabId:this.id,timeoutMs,waitId}, undefined, Math.max(client.timeoutMs,timeoutMs + 2000)));
    void result.catch(() => {});
    try {
      await Promise.race([ready, result.then(() => { throw new Error("Event wait ended before registration was confirmed"); })]);
      return {result};
    } finally { remove(); }
  }

  async prepareDownload(options: {timeoutMs?: number} = {}): Promise<OpenBrowserUseDownloadWait> {
    const timeoutMs = options.timeoutMs ?? 10_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000) throw new Error("Invalid download timeout");
    const prepared = await this.prepareBrowserEvent("waitForDownload", "onDownloadWaitReady", timeoutMs);
    return new OpenBrowserUseDownloadWait(this.browser.client,prepared.result);
  }

  async prepareFileChooser(options: {timeoutMs?: number} = {}): Promise<OpenBrowserUseFileChooserWait> {
    const timeoutMs = options.timeoutMs ?? 10_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000) throw new Error("Invalid file chooser timeout");
    await this.browser.cdp.enableFrameSessions(this.id);
    const prepared = await this.prepareBrowserEvent("waitForFileChooser", "onFileChooserWaitReady", timeoutMs);
    return new OpenBrowserUseFileChooserWait(this.browser.client,prepared.result);
  }

  async watchDialogs(): Promise<void> { await this.browser.cdp.enableDialogs(this.id); }

  currentDialog(): OpenBrowserUseDialog | null {
    const info = this.browser.cdp.currentDialog(this.id);
    return info ? new OpenBrowserUseDialog(this.browser.cdp,this.id,info) : null;
  }

  async waitForDialog(options: {timeoutMs?: number} = {}): Promise<OpenBrowserUseDialog> {
    const timeoutMs = options.timeoutMs ?? 10_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid dialog timeout");
    let dialog = this.currentDialog();
    if (dialog) return dialog;
    await this.watchDialogs();
    dialog = this.currentDialog();
    if (dialog) return dialog;
    await this.browser.cdp.waitForEvent(this.id,notification => {
      if (notification.method !== "onCDPEvent" || !isObject(notification.params)) return false;
      const source = notification.params.source;
      return isObject(source) && source.tabId === this.id && notification.params.method === "Page.javascriptDialogOpening";
    },{timeoutMs,timeoutMessage:"Timed out waiting for a JavaScript dialog"});
    dialog = this.currentDialog();
    if (!dialog) throw new Error("Dialog closed before it could be observed");
    return dialog;
  }

  async click(index: number, snapshotId: string, mouse?:MouseClick): Promise<void> {
    await this.act(index, snapshotId, undefined, false, undefined, undefined, false, undefined, false, mouse);
  }

  async dblclick(index: number, snapshotId: string, mouse?:MouseClick): Promise<void> {
    await this.act(index, snapshotId, undefined, false, undefined, undefined, false, undefined, true, mouse);
  }

  async hover(index: number, snapshotId: string): Promise<void> {
    await this.act(index, snapshotId, undefined, false, undefined, undefined, true);
  }

  /** @internal */
  async focus(index:number,snapshotId:string):Promise<void> { await this.act(index,snapshotId,undefined,false,undefined,undefined,false,undefined,false,undefined,true); }

  async press(index: number, snapshotId: string, key: string): Promise<void> {
    this.parseKey(key);
    await this.act(index, snapshotId, undefined, false, undefined, undefined, false, key);
  }

  async hoverAt(x: number, y: number, modifiers = 0): Promise<void> {
    this.#observation = undefined;
    if (!Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15) throw new Error("Invalid mouse modifiers");
    await this.checkPoint(x, y);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers });
  }

  private async dispatchClick(point:{x:number;y:number}, mouse:MouseClick, clickCount:number, options:{sessionId?:string;visualPoint?:{x:number;y:number};expectedGeneration?:number} = {}):Promise<void> {
    const release={type:"mouseReleased",...point,button:mouse.button,buttons:0,modifiers:mouse.modifiers,clickCount};
    let pending=true;
    try {
      await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{...release,type:"mousePressed",buttons:mouse.buttons},options);
      await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",release,options);
      pending=false;
    } finally { if (pending) await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",release,options).catch(()=>{}); }
  }

  async clickAt(x: number, y: number, options: {button?:number; modifiers?:number; double?:boolean} = {}): Promise<void> {
    this.#observation = undefined;
    const buttons = [{name:"left",mask:1},{name:"middle",mask:4},{name:"right",mask:2},{name:"back",mask:8},{name:"forward",mask:16}];
    const button = buttons[(options.button ?? 1)-1], modifiers = options.modifiers ?? 0;
    if (!Number.isInteger(options.button ?? 1) || !button || !Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15 || (options.double !== undefined && typeof options.double !== "boolean")) throw new Error("Invalid mouse options");
    await this.checkPoint(x, y);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers });
    for (let count=1; count<=(options.double ? 2 : 1); count++) {
      let pressed = true;
      try {
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", {type:"mousePressed",x,y,button:button.name,buttons:button.mask,clickCount:count,modifiers});
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", {type:"mouseReleased",x,y,button:button.name,buttons:0,clickCount:count,modifiers});
        pressed = false;
      } finally {
        if (pressed) await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:button.name,buttons:0,clickCount:count,modifiers}).catch(()=>{});
      }
    }
  }

  async dragPath(path: Array<{x:number; y:number}>, modifiers = 0): Promise<void> {
    this.#observation = undefined;
    if (!Array.isArray(path) || path.length < 2 || path.length > 1000 || !Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15) throw new Error("Invalid drag path");
    path = path.map(point=>({x:point?.x,y:point?.y}));
    const viewport = await this.getViewport();
    for (const point of path) if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.y < 0 || point.x >= viewport.width || point.y >= viewport.height) throw new Error("Drag point is outside the viewport");
    let {x,y} = path[0], pressed = false;
    await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseMoved",x,y,button:"none",buttons:0,modifiers});
    try {
      pressed = true;
      await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mousePressed",x,y,button:"left",buttons:1,clickCount:1,modifiers});
      for (const point of path.slice(1)) { x=point.x; y=point.y; await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseMoved",x,y,button:"left",buttons:1,modifiers}); }
      await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:"left",buttons:0,clickCount:1,modifiers}); pressed = false;
    } finally { if (pressed) await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:"left",buttons:0,clickCount:1,modifiers}).catch(()=>{}); }
  }

  async drag(from: [number, number], to: [number, number]): Promise<void> {
    this.#observation = undefined;
    if (!Array.isArray(from) || from.length !== 2 || !Array.isArray(to) || to.length !== 2) throw new Error("Drag requires two coordinate pairs");
    await this.checkPoint(from[0], from[1]);
    await this.checkPoint(to[0], to[1]);
    let x = from[0], y = from[1], pressed = false;
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
    try {
      pressed = true;
      await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
      for (let step = 1; step <= 5; step++) {
        x = from[0] + (to[0] - from[0]) * step / 5;
        y = from[1] + (to[1] - from[1]) * step / 5;
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "left", buttons: 1 });
      }
      await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
      pressed = false;
    } finally {
      if (pressed) await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 }).catch(() => {});
    }
  }

  async scrollAt(x: number, y: number, deltaX: number, deltaY: number, modifiers = 0, expectedGeneration?:number, frame?:{sessionId:string;contextId:number;inputPoint:{x:number;y:number}}): Promise<void> {
    this.#observation = undefined;
    if (!Number.isFinite(deltaX) || !Number.isFinite(deltaY)) throw new Error("Scroll deltas must be finite numbers");
    if (!Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15) throw new Error("Invalid mouse modifiers");
    await this.checkPoint(x, y);
    const options={...(expectedGeneration === undefined ? {} : {expectedGeneration}),...(frame ? {sessionId:frame.sessionId,visualPoint:{x,y}} : {})};
    if(frame) ({x,y}=frame.inputPoint);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers },options);
    try {
      if (modifiers || frame) await this.browser.cdp.call(this.id,"Input.dispatchMouseEvent",{type:"mouseWheel",x,y,deltaX,deltaY,modifiers},options);
      else await this.browser.cdp.call(this.id, "Input.synthesizeScrollGesture", { x, y, xDistance: -deltaX, yDistance: -deltaY, gestureSourceType: "mouse", preventFling: true },options);
    } catch (error) {
      if (error instanceof Error && /Timed out after \d+ms waiting for CDP command|IAB_BACKGROUND_SCROLL_TIMEOUT|IAB_INPUT_OUTCOME_UNKNOWN/.test(error.message)) throw new Error("Wheel outcome unknown after timeout; inspect the page before retrying",{cause:error});
      throw error;
    }
    if (frame) {
      try { const result=await this.browser.cdp.call(this.id,"Runtime.evaluate",{contextId:frame.contextId,expression:"Promise.race([new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))),new Promise(r=>setTimeout(r,1000))])",awaitPromise:true},{sessionId:frame.sessionId,timeoutMs:3000,...(expectedGeneration === undefined ? {} : {expectedGeneration})}); if(isObject(result) && result.exceptionDetails) throw new Error("Frame rendering wait failed"); }
      catch (error) { throw new Error("Wheel was sent but its completion could not be observed; inspect the page before retrying",{cause:error}); }
    }
  }

  private parseKey(key: string) {
    if (typeof key !== "string") throw new Error("Key must be a string");
    const definitions: Record<string, [string, number]> = {
      Enter: ["Enter", 13], Tab: ["Tab", 9], Escape: ["Escape", 27], Backspace: ["Backspace", 8],
      Delete: ["Delete", 46], ArrowLeft: ["ArrowLeft", 37], ArrowUp: ["ArrowUp", 38],
      ArrowRight: ["ArrowRight", 39], ArrowDown: ["ArrowDown", 40], Home: ["Home", 36], End: ["End", 35],
      PageUp: ["PageUp", 33], PageDown: ["PageDown", 34], Space: ["Space", 32],
      Alt:["AltLeft",18], Control:["ControlLeft",17], Meta:["MetaLeft",91], Shift:["ShiftLeft",16]
    };
    const parts = key === "+" ? ["+"] : key.split("+");
    const rawName = parts.pop() ?? "";
    const name = rawName === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : rawName;
    const modifierBits: Record<string, number> = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };
    const modifiers = parts.map(part => part === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : part);
    if (new Set(modifiers).size !== modifiers.length || modifiers.includes(name) || modifiers.some(modifier => !Object.hasOwn(modifierBits, modifier))) throw new Error("Invalid keyboard modifiers");
    const pairs: Array<[string, string, string, number]> = [
      ...Array.from({length:10}, (_,digit) => [String(digit), ")!@#$%^&*("[digit], `Digit${digit}`, 48+digit] as [string,string,string,number]),
      ["-","_","Minus",189],["=","+","Equal",187],["[","{","BracketLeft",219],
      ["]","}","BracketRight",221],["\\","|","Backslash",220],[";",":","Semicolon",186],
      ["'",'"',"Quote",222],[",","<","Comma",188],[".",">","Period",190],
      ["/","?","Slash",191],["`","~","Backquote",192]
    ];
    const printablePair = pairs.find(([plain,shifted]) => name === plain || name === shifted);
    if (printablePair && name === printablePair[1] && !modifiers.includes("Shift")) modifiers.push("Shift");
    const definition = (Object.hasOwn(definitions,name) ? definitions[name] : undefined) ?? (printablePair ? [printablePair[2],printablePair[3]] : /^[a-zA-Z]$/.test(name) ? [`Key${name.toUpperCase()}`, name.toUpperCase().charCodeAt(0)] : undefined) as [string,number] | undefined;
    if (!definition) throw new Error("Unsupported key");
    return {name, modifiers, modifierBits, definition, printablePair};
  }

  async pressKey(key: string): Promise<void> {
    this.parseKey(key);
    this.#observation = undefined;
    await this.sendKey(key,(await this.focusedInputFrame()).sessionId);
  }

  async typeAtFocus(text: string): Promise<void> {
    if (typeof text !== "string") throw new Error("Text must be a string");
    this.#observation = undefined;
    const sessionId = (await this.focusedInputFrame()).sessionId;
    if (text) await this.browser.cdp.call(this.id,"Input.insertText",{text},{sessionId});
  }

  private async focusedInputFrame(): Promise<FrameInfo> {
    const documentId = await this.documentId();
    const crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
    const frames = await this.frameTree();
    if (!crossProcess && frames.length > 1) throw new Error("Focused frame routing is unavailable");
    const focusedFrame = async (): Promise<FrameInfo> => {
      let current = frames[0];
      while (true) {
        let focused: FrameInfo | undefined;
        for (const child of frames.filter(frame=>frame.parentId === current.id)) {
          const owner = await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:child.id},{sessionId:current.sessionId});
          if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
          const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:current.id,worldName:"open-browser-use-selector"},{sessionId:current.sessionId});
          if(!isObject(world) || typeof world.executionContextId!=="number")throw new RetryablePreflightError("Frame focus context is unavailable; observe again");
          const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:owner.backendNodeId,executionContextId:world.executionContextId},{sessionId:current.sessionId});
          const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
          if (typeof objectId !== "string") throw new RetryablePreflightError("Frame owner is unavailable; observe again");
          try {
            const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function() { if (!this.isConnected) return null; let element=this; while (true) { const root=element.getRootNode(); if (root.activeElement !== element) return false; if (!(root instanceof ShadowRoot)) return true; element=root.host; } }`},{sessionId:current.sessionId});
            const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (typeof value !== "boolean") throw new RetryablePreflightError("Frame focus is unavailable; observe again");
            if (value) { if (focused) throw new RetryablePreflightError("Frame focus changed; observe again"); focused = child; }
          } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId:current.sessionId}).catch(()=>{}); }
        }
        if (!focused) return current;
        current = focused;
      }
    };
    const target = await focusedFrame();
    if ((await focusedFrame()).id !== target.id || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames) || await this.documentId() !== documentId) throw new RetryablePreflightError("Frame focus changed; observe again");
    return target;
  }

  private async targetFrameFocused(frameId:string, backendNodeId:number, frames:FrameInfo[]):Promise<boolean> {
    const active=await this.focusedInputFrame();
    if(active.id===frameId)return true;
    const chain=frameAncestry(active,frames),child=chain.find(item=>item.parentId===frameId),parent=frames.find(item=>item.id===frameId);
    if(!child || !parent)return false;
    const owner=await this.browser.cdp.call(this.id,"DOM.getFrameOwner",{frameId:child.id},{sessionId:parent.sessionId});
    return isObject(owner) && owner.backendNodeId===backendNodeId;
  }

  private async sendKey(key: string, sessionId?: string): Promise<void> {
    const {name, modifiers, modifierBits, definition, printablePair} = this.parseKey(key);
    const modifierCodes: Record<string, [string, number]> = { Alt: ["AltLeft", 18], Control: ["ControlLeft", 17], Meta: ["MetaLeft", 91], Shift: ["ShiftLeft", 16] };
    let mask = 0;
    const pressed: string[] = [];
    let activeKey: BrowserUseRequestParams | undefined;
    try {
      for (const modifier of modifiers) {
        mask |= modifierBits[modifier];
        const [code, windowsVirtualKeyCode] = modifierCodes[modifier];
        pressed.push(modifier);
        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { type: "rawKeyDown", key: modifier, code, windowsVirtualKeyCode, modifiers: mask }, {sessionId});
      }
      const actualKey = name === "Space" ? " " : printablePair ? printablePair[mask & 8 ? 1 : 0] : /^[a-zA-Z]$/.test(name) ? (mask & 8 ? name.toUpperCase() : name.toLowerCase()) : name;
      const params = { key: actualKey, code: definition[0], windowsVirtualKeyCode: definition[1], modifiers: mask | (Object.hasOwn(modifierBits,name) ? modifierBits[name] : 0) };
      const selectAll = actualKey === "a" && (mask === 2 || mask === 4);
      const printable = (name === "Space" || !!printablePair || /^[a-zA-Z]$/.test(name)) && !(mask & 7);
      activeKey = params;
      await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, type: printable ? "keyDown" : "rawKeyDown", ...(printable ? {text:actualKey, unmodifiedText:name === "Space" ? " " : printablePair ? printablePair[0] : name.toLowerCase()} : {}), ...(selectAll ? { commands: ["selectAll"] } : {}) }, {sessionId});
      await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, modifiers:mask, type: "keyUp" }, {sessionId});
      activeKey = undefined;
    } finally {
      if (activeKey) await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...activeKey, modifiers:mask, type: "keyUp" }, {sessionId}).catch(() => {});
      for (const modifier of pressed.reverse()) {
        mask &= ~modifierBits[modifier];
        const [code, windowsVirtualKeyCode] = modifierCodes[modifier];
        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { type: "keyUp", key: modifier, code, windowsVirtualKeyCode, modifiers: mask }, {sessionId}).catch(() => {});
      }
    }
  }

  private async checkPoint(x: number, y: number): Promise<void> {
    if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error("Coordinates must be finite numbers");
    const viewport = await this.getViewport();
    if (x < 0 || y < 0 || x >= viewport.width || y >= viewport.height) throw new Error("Coordinates are outside the viewport");
  }

  async getViewport(): Promise<{ width: number; height: number }> {
    const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
    const viewport = isObject(metrics) ? metrics.cssVisualViewport : null;
    if (!isObject(viewport) || typeof viewport.clientWidth !== "number" || !Number.isFinite(viewport.clientWidth) || viewport.clientWidth <= 0 || typeof viewport.clientHeight !== "number" || !Number.isFinite(viewport.clientHeight) || viewport.clientHeight <= 0) throw new Error("Browser viewport is unavailable");
    return { width: viewport.clientWidth, height: viewport.clientHeight };
  }

  async typeText(index: number, snapshotId: string, text: string): Promise<void> {
    if (typeof text !== "string") throw new Error("Text must be a string");
    await this.act(index, snapshotId, text);
  }

  async fill(index: number, snapshotId: string, text: string): Promise<void> {
    if (typeof text !== "string") throw new Error("Text must be a string");
    await this.act(index, snapshotId, text, true);
  }

  async setChecked(index: number, snapshotId: string, checked: boolean, force = false): Promise<void> {
    if (typeof checked !== "boolean") throw new Error("Checked state must be boolean");
    await this.act(index, snapshotId, undefined, false, checked, undefined, false, undefined, false, {button:"left",buttons:1,modifiers:0,...(force ? {force:true} : {})});
  }

  async selectOption(index: number, snapshotId: string, values: SelectOption | SelectOption[]): Promise<string[]> {
    const specs = selectSpecs(values);
    const result = await this.act(index, snapshotId, undefined, false, undefined, specs);
    if (!Array.isArray(result) || result.some(value => typeof value !== "string")) throw new Error("Invalid selected options result");
    return result as string[];
  }

  private async act(index: number, snapshotId: string, text?: string, replace = false, checked?: boolean, selection?: Array<{value?: string; label?: string; either: boolean}>, hover = false, key?: string, doubleClick = false, mouse:MouseClick = {button:"left",buttons:1,modifiers:0}, focusOnly = false): Promise<void | string[]> {
    const observation = this.#observation;
    this.#observation = undefined;
    const node = observation?.nodes.find((item) => item.index === index);
    if (!observation || observation.id !== snapshotId || !node) throw new RetryablePreflightError("Observation is stale or index is invalid; observe again");
    if (text !== undefined && !["textbox", "searchbox", "combobox", "spinbutton", "Date", "DateTime", "InputTime"].includes(node.role)) throw new Error("Target is not a text field");
    if (text !== undefined && !replace && ["Date", "DateTime", "InputTime"].includes(node.role)) throw new Error("Use fill for date and time inputs");
    if (selection !== undefined && !["combobox", "listbox"].includes(node.role)) throw new Error("Target is not a select control");
    if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
    if (node.frameChain) await this.validateFrames(node.frameChain);
    const targetSession = node.frameChain?.[0]?.sessionId;
    const targetTree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
    const current = interactiveNodes(targetTree, 0, supplementalRoles.includes(node.role)).find((item) => item.backendNodeId === node.backendNodeId && item.role === node.role);
    if (!current || current.role !== node.role || current.name !== node.name || current.stateKey !== node.stateKey) throw new RetryablePreflightError("Target changed; observe again");
    if (current.disabled && !hover) throw new RetryablePreflightError("Target is disabled; observe again");
    await this.verifyLocatorScope(observation,node);
    let frameId=node.frameId ?? observation.frames?.[0]?.id;
    if(!frameId){
      const tree=await this.browser.cdp.call(this.id,"Page.getFrameTree");
      const root=isObject(tree) && isObject(tree.frameTree) && isObject(tree.frameTree.frame) ? tree.frameTree.frame.id : undefined;
      if(typeof root!=="string")throw new RetryablePreflightError("Target frame is unavailable; observe again");
      frameId=root;
    }
    const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId,worldName:"open-browser-use-selector"},{sessionId:targetSession});
    if(!isObject(world) || typeof world.executionContextId!=="number" || await this.documentId()!==observation.documentId)throw new RetryablePreflightError("Target context is unavailable; observe again");
    const executionContextId=world.executionContextId;
    if (checked !== undefined) {
      if (!["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(node.role) || typeof current.checked !== "boolean") throw new Error("Target does not have a binary checked state");
      if (current.checked === checked) {
        const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:node.backendNodeId,executionContextId},{sessionId:targetSession});
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string") throw new RetryablePreflightError("Target is unavailable; observe again");
        try {
          const result = await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,
            functionDeclaration:`function() { if (!(this instanceof Element) || !this.isConnected) return 'unavailable'; for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return 'disabled'; return 'enabled'; }`
          },{sessionId:targetSession});
          const status = isObject(result) && isObject(result.result) ? result.result.value : undefined;
          if (status === "disabled") throw new RetryablePreflightError("Target is disabled; observe again");
          if (status !== "enabled") throw new RetryablePreflightError("Target is unavailable; observe again");
          if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
          if (node.frameChain) await this.validateFrames(node.frameChain);
          await this.verifyLocatorScope(observation,node);
          const tree = node.frameId ? await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:node.frameId},{sessionId:targetSession}) : await this.getAXState();
          const latest = interactiveNodes(tree).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
          if (!latest || latest.name !== node.name || latest.stateKey !== node.stateKey) throw new RetryablePreflightError("Target changed; observe again");
          return;
        } finally { await this.browser.cdp.call(this.id,"Runtime.releaseObject",{objectId},{sessionId:targetSession}).catch(() => {}); }
      }
      if (!checked && ["radio", "menuitemradio"].includes(node.role)) throw new Error("A selected radio cannot be unchecked directly");
    }
    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId, executionContextId }, { sessionId: targetSession });
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Target is unavailable; observe again");
    let inputIssued = false;
    try {
      if (focusOnly) {
        inputIssued=true;
        await this.browser.cdp.call(this.id,"DOM.focus",{objectId},{sessionId:targetSession});
        const focused=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function(){if(!this.isConnected)return false;let element=this;while(true){const root=element.getRootNode();if(root.activeElement!==element)return false;if(!(root instanceof ShadowRoot))return true;element=root.host}}`},{sessionId:targetSession});
        if(!isObject(focused) || !isObject(focused.result) || focused.result.value!==true || await this.documentId()!==observation.documentId || (node.frameId && observation.frames && !await this.targetFrameFocused(node.frameId,node.backendNodeId,observation.frames)))throw new Error("Target lost focus; observe again");
        if(node.frameChain)await this.validateFrames(node.frameChain);
        await this.verifyLocatorScope(observation,node);return;
      }
      const measure = async () => {
        const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue: true, arguments:[{value:hover},{value:!!mouse.force}],
          functionDeclaration: `function(allowDisabled,force) {
            const element=this.nodeType===Node.TEXT_NODE ? this.parentElement : this;
            if (!this.isConnected || !(element instanceof Element)) return null;
            if (!allowDisabled) for (let el=element; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return null;
            element.scrollIntoView({ block: 'center', inline: 'center' });
            let r;
            if (this.nodeType===Node.TEXT_NODE) {
              const range=this.ownerDocument.createRange();range.selectNodeContents(this);
              r=Array.from(range.getClientRects()).find(rect=>rect.width>0 && rect.height>0 && rect.right>0 && rect.bottom>0 && rect.left<innerWidth && rect.top<innerHeight);
            } else r=element.getBoundingClientRect();
            if (!r) return null;
            const x = (Math.max(0,r.left) + Math.min(innerWidth,r.right)) / 2, y = (Math.max(0,r.top) + Math.min(innerHeight,r.bottom)) / 2;
            if (!r.width || !r.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;
            if(force)return {x,y,width:r.width,height:r.height};
            let target = element, root = target.getRootNode();
            while (true) {
              const hit = root.elementFromPoint(x, y);
              if (!hit || (hit !== target && ((this.nodeType===Node.TEXT_NODE && target===element) || !target.contains(hit)))) return null;
              if (!(root instanceof ShadowRoot)) return { x, y, width:r.width, height:r.height };
              target = root.host; root = target.getRootNode();
            }
          }`
        }, { sessionId: targetSession });
        let point = isObject(result) && isObject(result.result) ? result.result.value : null;
        if (!isObject(point) || typeof point.x !== "number" || !Number.isFinite(point.x) || typeof point.y !== "number" || !Number.isFinite(point.y) || typeof point.width !== "number" || !Number.isFinite(point.width) || point.width <= 0 || typeof point.height !== "number" || !Number.isFinite(point.height) || point.height <= 0) throw new RetryablePreflightError("Target is hidden, disabled, or covered; observe again");
        const geometry = {x:point.x, y:point.y, width:point.width, height:point.height};
        let inputPoint = point;
        if (node.frameChain) {
          for (let i = 0; i < node.frameChain.length; i++) {
            const frame = node.frameChain[i];
            const ownerSession = node.frameChain[i + 1]?.sessionId;
            point = await this.framePoint(frame.id, frame.parentId, point.x as number, point.y as number, ownerSession,!!mouse.force);
            if (ownerSession === targetSession) inputPoint = point;
          }
          await this.validateFrames(node.frameChain);
        }
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        return {point, inputPoint, geometry};
      };
      const first = await measure();
      await new Promise(resolve => setTimeout(resolve, 75));
      const second = await measure();
      const moving = (a: number, b: number) => Math.abs(a - b) > 0.25;
      if (moving(first.geometry.x, second.geometry.x) || moving(first.geometry.y, second.geometry.y) ||
          moving(first.geometry.width, second.geometry.width) || moving(first.geometry.height, second.geometry.height) ||
          moving(first.point.x as number, second.point.x as number) || moving(first.point.y as number, second.point.y as number)) throw new RetryablePreflightError("Target is moving; observe again");
      const finalTree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", {frameId:node.frameId}, {sessionId:targetSession}) : await this.getAXState();
      const finalNode = interactiveNodes(finalTree, 0, supplementalRoles.includes(node.role)).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
      if (!finalNode || finalNode.name !== node.name || finalNode.stateKey !== node.stateKey) throw new RetryablePreflightError("Target changed; observe again");
      await this.verifyLocatorScope(observation,node);
      let {point, inputPoint} = second;
      if (text !== undefined && node.role === "combobox") {
        const editable=await this.browser.cdp.call(this.id,"Runtime.callFunctionOn",{objectId,returnByValue:true,functionDeclaration:`function(){return this.isConnected && !this.disabled && !this.readOnly && this.getAttribute('aria-readonly')!=='true' && (this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type)))}`},{sessionId:targetSession});
        if(!isObject(editable) || !isObject(editable.result) || editable.result.value!==true)throw new Error("Target is not an editable text field");
        if(await this.documentId()!==observation.documentId)throw new RetryablePreflightError("Page changed; observe again");
        if(node.frameChain)await this.validateFrames(node.frameChain);
        await this.verifyLocatorScope(observation,node);
      }
      if (text !== undefined && replace && ["Date", "DateTime", "InputTime"].includes(node.role)) {
        const temporal = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true, arguments:[{value:text}],
          functionDeclaration:`function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly) return 'unsupported'; const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;return probe.value === value ? 'ok' : 'invalid'; }`
        }, {sessionId:targetSession});
        const status = isObject(temporal) && isObject(temporal.result) ? temporal.result.value : null;
        if (status === "invalid") throw new Error("Invalid date or time value");
        if (status !== "ok") throw new Error("Target is not an editable native date or time input");
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
        await this.verifyLocatorScope(observation,node);
        inputIssued = true;
        const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true, arguments:[{value:text}],
          functionDeclaration:`function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly) return false; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set; if (!setter) return false; setter.call(this,value); this.dispatchEvent(new Event('input',{bubbles:true,composed:true})); this.dispatchEvent(new Event('change',{bubbles:true})); return this.isConnected && this.value===value; }`
        }, {sessionId:targetSession});
        if (!isObject(applied) || !isObject(applied.result) || applied.result.value !== true) throw new Error("Date or time input did not retain the requested value");
        return;
      }
      if (text !== undefined && node.role === "spinbutton") {
        const checkedNumber = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true, arguments:[{value:text},{value:replace}],
          functionDeclaration:`function(value, replace) { if (!(this instanceof HTMLInputElement) || this.type !== 'number' || !this.isConnected || this.disabled || this.readOnly) return 'unsupported'; if (!replace) return 'ok'; const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;return probe.value === value ? 'ok' : 'invalid'; }`
        }, {sessionId:targetSession});
        const status = isObject(checkedNumber) && isObject(checkedNumber.result) ? checkedNumber.result.value : null;
        if (status === "invalid") throw new Error("Invalid number value");
        if (status !== "ok") throw new Error("Target is not an editable native number input");
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
      }
      if (selection !== undefined) {
        const options = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true, arguments:[{value:selection}],
          functionDeclaration:`function(specs) {
            if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.disabled) return {status:'not-select'};
            if (!this.multiple && specs.length > 1) return {status:'multiple'};
            const options=Array.from(this.options), chosen=[];
            for (const spec of specs) {
              const hits=options.map((option,index)=>({option,index})).filter(({option,index})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.index===undefined || index===spec.index) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));
              if (!hits.length) return {status:'missing'};
              if (hits.length > 1 || chosen.some(item=>item.index===hits[0].index)) return {status:'ambiguous'};
              chosen.push({index:hits[0].index,value:hits[0].option.value,label:hits[0].option.label});
            }
            return {status:'ok',chosen};
          }`
        }, {sessionId:targetSession});
        const found = isObject(options) && isObject(options.result) ? options.result.value : null;
        if (!isObject(found) || typeof found.status !== "string") throw new Error("Invalid select options result");
        if (found.status === "missing") throw new RetryablePreflightError("Requested select option is unavailable");
        if (found.status === "ambiguous") throw new Error("Requested select option is ambiguous");
        if (found.status === "multiple") throw new Error("Multiple options require a multiple select");
        if (found.status !== "ok" || !Array.isArray(found.chosen)) throw new Error("Target is not an enabled native select");
        if (await this.documentId() !== observation.documentId) throw new RetryablePreflightError("Page changed; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
        await this.verifyLocatorScope(observation,node);
        inputIssued = true;
        const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true, arguments:[{value:found.chosen},{value:selection}],
          functionDeclaration:`function(chosen,specs) {
            if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.disabled || (!this.multiple && chosen.length > 1)) return null;
            for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true') return null;
            const options=Array.from(this.options);
            for(let i=0;i<specs.length;i++) {const spec=specs[i],hits=options.map((option,index)=>({option,index})).filter(({option,index})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.index===undefined || index===spec.index) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));if(hits.length!==1 || hits[0].index!==chosen[i]?.index)return null;}
            if (chosen.some(item=>{const o=options[item.index]; return !o || o.value!==item.value || o.label!==item.label || o.disabled || (o.parentElement instanceof HTMLOptGroupElement && o.parentElement.disabled);})) return null;
            if (!this.multiple && !chosen.length) this.selectedIndex=-1;
            else { const indices=new Set(chosen.map(item=>item.index)); for (let i=0;i<options.length;i++) options[i].selected=indices.has(i); }
            this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
            this.dispatchEvent(new Event('change',{bubbles:true}));
            return this.isConnected ? Array.from(this.selectedOptions, option=>option.value) : null;
          }`
        }, {sessionId:targetSession});
        const selected = isObject(applied) && isObject(applied.result) ? applied.result.value : null;
        const expected = found.chosen.map(item => isObject(item) ? item.value : null);
        if (!Array.isArray(selected) || JSON.stringify([...selected].sort()) !== JSON.stringify([...expected].sort())) throw new Error("Select did not retain the requested options");
        return selected as string[];
      }
      if (key !== undefined) {
        inputIssued = true;
        await this.browser.cdp.call(this.id, "DOM.focus", {objectId}, {sessionId:targetSession});
        const focused = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue:true,
          functionDeclaration:`function() { return this.isConnected && this.getRootNode().activeElement === this; }`
        }, {sessionId:targetSession});
        if (!isObject(focused) || !isObject(focused.result) || focused.result.value !== true || await this.documentId() !== observation.documentId) throw new Error("Target lost focus; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
        await this.verifyLocatorScope(observation,node);
        await this.sendKey(key,targetSession);
        return;
      }
      const inputOptions = mouse.force ? {} : {sessionId: targetSession, ...(targetSession ? {visualPoint: {x: point.x as number, y: point.y as number}} : {})};
      if(mouse.force)inputPoint=point;
      inputIssued = true;
      if (hover) {
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x: inputPoint.x, y: inputPoint.y, button: "none", buttons: 0 }, inputOptions);
        return;
      }
      await this.dispatchClick({x:inputPoint.x as number,y:inputPoint.y as number},mouse,1,inputOptions);
      if (doubleClick) {
        const after = await measure();
        if (moving(second.geometry.x, after.geometry.x) || moving(second.geometry.y, after.geometry.y) || moving(second.geometry.width, after.geometry.width) || moving(second.geometry.height, after.geometry.height) || moving(point.x as number, after.point.x as number) || moving(point.y as number, after.point.y as number)) throw new Error("Target moved after the first click; observe again");
        const tree = node.frameId ? await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:node.frameId},{sessionId:targetSession}) : await this.getAXState();
        const latest = interactiveNodes(tree,0,supplementalRoles.includes(node.role)).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
        if (!latest || latest.name !== node.name || latest.stateKey !== node.stateKey) throw new Error("Target changed after the first click; observe again");
        await this.verifyLocatorScope(observation,node);
        await this.dispatchClick({x:inputPoint.x as number,y:inputPoint.y as number},mouse,2,inputOptions);
      }
      if (checked !== undefined) {
        if (await this.documentId() !== observation.documentId) throw new Error("Page changed after input; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
        const result = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", {frameId: node.frameId}, {sessionId: targetSession}) : await this.getAXState();
        if (interactiveNodes(result).find(item => item.backendNodeId === node.backendNodeId)?.checked !== checked) throw new Error("Target did not retain the requested checked state");
      }
      if (text !== undefined) {
        const checkFocus = () => this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue: true,
          functionDeclaration: `function() { return this.isConnected && !this.disabled && !this.readOnly && this.getAttribute('aria-readonly') !== 'true' && this.getRootNode().activeElement === this && (this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type))); }`
        }, { sessionId: targetSession });
        const focused = await checkFocus();
        if (!isObject(focused) || !isObject(focused.result) || focused.result.value !== true || await this.documentId() !== observation.documentId) throw new Error("Text field lost focus or is not editable; observe again");
        if (node.frameChain) await this.validateFrames(node.frameChain);
        if (replace) {
          const modifier = process.platform === "darwin" ? {key:"Meta",code:"MetaLeft",windowsVirtualKeyCode:91,modifiers:4} : {key:"Control",code:"ControlLeft",windowsVirtualKeyCode:17,modifiers:2};
          const key = {key:"a",code:"KeyA",windowsVirtualKeyCode:65,modifiers:modifier.modifiers};
          let modifierDown = false, keyDown = false;
          try {
            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...modifier,type:"rawKeyDown"}, {sessionId:targetSession}); modifierDown = true;
            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"rawKeyDown",commands:["selectAll"]}, {sessionId:targetSession}); keyDown = true;
            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"keyUp"}, {sessionId:targetSession}); keyDown = false;
          } finally {
            if (keyDown) await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"keyUp"}, {sessionId:targetSession}).catch(() => {});
            if (modifierDown) await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...modifier,type:"keyUp",modifiers:0}, {sessionId:targetSession}).catch(() => {});
          }
          const stillFocused = await checkFocus();
          if (!isObject(stillFocused) || !isObject(stillFocused.result) || stillFocused.result.value !== true || await this.documentId() !== observation.documentId) throw new Error("Text field changed during fill; observe again");
          if (node.frameChain) await this.validateFrames(node.frameChain);
          const selected = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
            objectId, returnByValue:true,
            functionDeclaration:`function() { if (this.isContentEditable) { const selection=this.getRootNode().getSelection?.() ?? getSelection(); return !!selection && selection.toString() === this.innerText; } return this.selectionStart === null || (this.selectionStart === 0 && this.selectionEnd === this.value.length); }`
          }, {sessionId:targetSession});
          if (!isObject(selected) || !isObject(selected.result) || selected.result.value !== true) throw new Error("Could not select the text field contents");
        }
        if (text) await this.browser.cdp.call(this.id, "Input.insertText", { text }, {sessionId: targetSession});
        else if (replace) {
          const key = {key:"Backspace",code:"Backspace",windowsVirtualKeyCode:8};
          await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"rawKeyDown"}, {sessionId:targetSession});
          try { await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"keyUp"}, {sessionId:targetSession}); }
          catch (error) { await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", {...key,type:"keyUp"}, {sessionId:targetSession}).catch(() => {}); throw error; }
        }
        if (replace) {
          const check = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
            objectId, returnByValue:true, arguments:[{value:text}],
            functionDeclaration:`function(value) { return this.isConnected && (this.isContentEditable ? this.innerText : this.value) === value; }`
          }, {sessionId:targetSession});
          if (!isObject(check) || !isObject(check.result) || check.result.value !== true) throw new Error("Text field did not retain the requested value");
        }
      }
    } catch (error) {
      if (inputIssued && error instanceof RetryablePreflightError) throw new Error(error.message, {cause:error});
      throw error;
    } finally {
      await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId: targetSession }).catch(() => {});
    }
  }

  private async documentId(): Promise<number> {
    const result = await this.browser.cdp.call(this.id, "DOM.getDocument", { depth: 0 });
    const root = isObject(result) ? result.root : null;
    if (!isObject(root) || typeof root.backendNodeId !== "number") throw new Error("Could not identify page document");
    return root.backendNodeId;
  }

  private async frameTree(): Promise<FrameInfo[]> {
    const frames: FrameInfo[] = [];
    const visit = (tree: JsonValue, sessionId?: string, parentId?: string): void => {
      if (!isObject(tree) || !isObject(tree.frame) || typeof tree.frame.id !== "string" || typeof tree.frame.loaderId !== "string" || typeof tree.frame.url !== "string") throw new Error("Invalid frame tree");
      const frame: FrameInfo = { id: tree.frame.id, loaderId: tree.frame.loaderId, url: tree.frame.url, ...(parentId ? {parentId} : {}), ...(sessionId ? {sessionId} : {}) };
      frames.push(frame);
      if (Array.isArray(tree.childFrames)) for (const child of tree.childFrames) visit(child, sessionId, frame.id);
    };
    const root = await this.browser.cdp.call(this.id, "Page.getFrameTree");
    if (!isObject(root) || !isObject(root.frameTree)) throw new Error("Invalid frame tree");
    visit(root.frameTree);
    const pending = await this.browser.cdp.frameSessions(this.id);
    while (pending.length) {
      const index = pending.findIndex(child => frames.some(frame => frame.id === child.parentFrameId));
      if (index < 0) throw new RetryablePreflightError("Frame sessions changed; observe again");
      const child = pending.splice(index, 1)[0];
      const tree = await this.browser.cdp.call(this.id, "Page.getFrameTree", {}, {sessionId: child.sessionId});
      if (!isObject(tree) || !isObject(tree.frameTree) || !isObject(tree.frameTree.frame) || tree.frameTree.frame.id !== child.frameId) throw new RetryablePreflightError("Frame session changed; observe again");
      visit(tree.frameTree, child.sessionId, child.parentFrameId);
    }
    return frames;
  }

  private async validateFrames(chain: FrameInfo[]): Promise<void> {
    const current = await this.frameTree();
    if (chain.some(frame => !current.some(item => item.id === frame.id && item.loaderId === frame.loaderId && item.parentId === frame.parentId && item.sessionId === frame.sessionId))) throw new RetryablePreflightError("Frame changed; observe again");
  }

  private async framePoint(frameId: string, parentFrameId: string | undefined, x: number, y: number, sessionId?: string, force = false): Promise<{ x: number; y: number }> {
    if(!parentFrameId)throw new RetryablePreflightError("Frame parent is unavailable");
    const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId }, {sessionId});
    if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable");
    const world=await this.browser.cdp.call(this.id,"Page.createIsolatedWorld",{frameId:parentFrameId,worldName:"open-browser-use-selector"},{sessionId});
    if(!isObject(world) || typeof world.executionContextId!=="number" || !Number.isSafeInteger(world.executionContextId))throw new RetryablePreflightError("Frame owner context is unavailable");
    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId,executionContextId:world.executionContextId }, {sessionId});
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Frame owner is unavailable");
    try {
      const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
        objectId, returnByValue: true, arguments: [{value:x},{value:y},{value:force}],
        functionDeclaration: `function(x,y,force) {
          if (!this.isConnected) return null;
          this.scrollIntoView({block:'center',inline:'center'});
          for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) {
            const t=getComputedStyle(el).transform;
            if (t !== 'none') { const m=new DOMMatrixReadOnly(t); if (!m.is2D || m.b !== 0 || m.c !== 0 || m.a <= 0 || m.d <= 0) return null; }
          }
          const r=this.getBoundingClientRect();
          if (!this.offsetWidth || !this.offsetHeight) return null;
          x=r.left+(this.clientLeft+x)*r.width/this.offsetWidth;
          y=r.top+(this.clientTop+y)*r.height/this.offsetHeight;
          if (x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
          if(force)return {x,y};
          let target=this, root=target.getRootNode();
          while (true) { const hit=root.elementFromPoint(x,y); if (!hit || (hit!==target && !target.contains(hit))) return null; if (!(root instanceof ShadowRoot)) return {x,y}; target=root.host; root=target.getRootNode(); }
        }`
      }, {sessionId});
      const point = isObject(result) && isObject(result.result) ? result.result.value : null;
      if (!isObject(point) || typeof point.x !== "number" || !Number.isFinite(point.x) || typeof point.y !== "number" || !Number.isFinite(point.y)) throw new RetryablePreflightError("Frame is hidden, covered or has an unsupported transform");
      return {x:point.x,y:point.y};
    } finally { await this.browser.cdp.call(this.id, "Runtime.releaseObject", {objectId}, {sessionId}).catch(() => {}); }
  }

  async getScreenshot(options: {clip?: {x: number; y: number; width: number; height: number}; fullPage?: boolean} = {}): Promise<Buffer> {
    if (options.fullPage !== undefined && typeof options.fullPage !== "boolean") throw new Error("Invalid fullPage option");
    const fullPage = options.fullPage === true;
    if (fullPage && options.clip !== undefined) throw new Error("Full-page screenshot cannot use a clip");
    let clip: {x: number; y: number; width: number; height: number; scale: number} | undefined;
    if (fullPage) {
      const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
      const content = isObject(metrics) ? metrics.cssContentSize : null;
      if (!isObject(content) || ![content.x,content.y,content.width,content.height].every(value => typeof value === "number" && Number.isFinite(value))) throw new Error("Page dimensions are unavailable");
      const {x,y,width,height} = content as {x:number; y:number; width:number; height:number};
      if (width <= 0 || height <= 0 || width > 32767 || height > 32767 || width * height > 32_000_000) throw new Error("Page is too large for a full-page screenshot");
      clip = {x,y,width,height,scale:1};
    } else if (options.clip !== undefined) {
      const rect = {...options.clip};
      if (![rect.x,rect.y,rect.width,rect.height].every(Number.isFinite) || rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0) throw new Error("Invalid screenshot clip");
      const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
      const viewport = isObject(metrics) ? metrics.cssVisualViewport : null;
      if (!isObject(viewport) || ![viewport.pageX,viewport.pageY,viewport.clientWidth,viewport.clientHeight].every(value => typeof value === "number" && Number.isFinite(value))) throw new Error("Browser viewport is unavailable");
      const {pageX, pageY, clientWidth, clientHeight} = viewport as {pageX: number; pageY: number; clientWidth: number; clientHeight: number};
      if (rect.x + rect.width > clientWidth || rect.y + rect.height > clientHeight) throw new Error("Screenshot clip is outside the viewport");
      clip = {x:pageX+rect.x,y:pageY+rect.y,width:rect.width,height:rect.height,scale:1};
    }
    const result = await this.browser.cdp.call(this.id, "Page.captureScreenshot", { format: "png", ...(clip ? {clip,captureBeyondViewport:fullPage} : {}) });
    if (!isObject(result) || typeof result.data !== "string" || !result.data) throw new Error("Browser returned an invalid screenshot");
    const png=Buffer.from(result.data,"base64");
    if (png.toString("base64") !== result.data || png.length < 45 || !png.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || png.readUInt32BE(8) !== 13 || png.toString("ascii",12,16) !== "IHDR" || !png.readUInt32BE(16) || !png.readUInt32BE(20) || !png.subarray(-12).equals(Buffer.from([0,0,0,0,73,69,78,68,174,66,96,130]))) throw new Error("Browser returned an invalid PNG screenshot");
    return png;
  }

  evaluate(expression: string, options: { awaitPromise?: boolean } = {}): Promise<JsonValue> {
    return this.browser.cdp.evaluate(this.id, expression, options);
  }

  close(): Promise<JsonValue> {
    return this.browser.cdp.call(this.id, "Page.close");
  }
}

export class OpenBrowserUseImage extends Uint8Array {
  toBase64(): string { return Buffer.from(this).toString("base64"); }
}

function cuaModifiers(keys: string[] = []): number {
  if (!Array.isArray(keys)) throw new Error("Invalid mouse modifiers");
  const bits: Record<string,number> = {Alt:1,Control:2,Meta:4,Shift:8};
  const normalized = keys.map(key=>key === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : key);
  if (new Set(normalized).size !== normalized.length || normalized.some(key=>typeof key !== "string" || !Object.hasOwn(bits,key))) throw new Error("Invalid mouse modifiers");
  return normalized.reduce((mask,key)=>mask | bits[key],0);
}

export class OpenBrowserUseTabCUA {
  constructor(private tab: OpenBrowserUseTab) {}
  click(options: {x:number; y:number; button?:number; keypress?:string[]}): Promise<void> { return this.tab.clickAt(options.x,options.y,{button:options.button,modifiers:cuaModifiers(options.keypress)}); }
  double_click(options: {x:number; y:number; keypress?:string[]}): Promise<void> { return this.tab.clickAt(options.x,options.y,{double:true,modifiers:cuaModifiers(options.keypress)}); }
  move(options: {x:number; y:number; keys?:string[]}): Promise<void> { return this.tab.hoverAt(options.x,options.y,cuaModifiers(options.keys)); }
  scroll(options: {x:number; y:number; scrollX:number; scrollY:number; keypress?:string[]}): Promise<void> { return this.tab.scrollAt(options.x,options.y,options.scrollX,options.scrollY,cuaModifiers(options.keypress)); }
  drag(options: {path:Array<{x:number; y:number}>; keys?:string[]}): Promise<void> { return this.tab.dragPath(options.path,cuaModifiers(options.keys)); }
  type(options: {text:string}): Promise<void> { return this.tab.typeAtFocus(options.text); }
  keypress(options: {keys:string[]}): Promise<void> {
    if (!Array.isArray(options.keys) || !options.keys.length || options.keys.some(key=>typeof key !== "string" || !key)) throw new Error("Invalid key combination");
    const aliases: Record<string,string> = {ctrl:"ControlOrMeta",control:"Control",controlormeta:"ControlOrMeta",cmd:"Meta",meta:"Meta",alt:"Alt",option:"Alt",shift:"Shift",esc:"Escape",return:"Enter",del:"Delete",space:"Space",left:"ArrowLeft",right:"ArrowRight",up:"ArrowUp",down:"ArrowDown"};
    const keys = options.keys.map(key=>Object.hasOwn(aliases,key.toLowerCase()) ? aliases[key.toLowerCase()] : key);
    if (keys.length > 1 && keys.at(-1) === "+") { keys[keys.length-1] = "="; if (!keys.includes("Shift")) keys.splice(keys.length-1,0,"Shift"); }
    return this.tab.pressKey(keys.join("+"));
  }
  async get_visible_screenshot(): Promise<OpenBrowserUseImage> { return new OpenBrowserUseImage(await this.tab.getScreenshot()); }
}

export class OpenBrowserUseTabDomCUA {
  private snapshot=false;
  private generation=0;
  private connectionGeneration=-1;
  private busy=false;
  private ids=new Map<string,{snapshot:CssSnapshot;id:number;identity:DomIdentity}>();
  constructor(private tab:OpenBrowserUseTab) {}
  private invalidate():void { this.generation++;this.snapshot=false;this.ids.clear(); }
  private beginAction():()=>void {
    if(this.busy)throw new Error('DOM CUA action is already in progress');
    this.busy=true;this.invalidate();return ()=>{this.invalidate();this.busy=false;};
  }
  async get_visible_dom():Promise<{nodes:Array<{node_id:string;frame_id:string} & DomIdentity>;visibility_incomplete?:boolean}> {
    if(this.busy)throw new Error('DOM CUA action is already in progress');
    this.invalidate();const generation=this.generation;
    const ids=new Map<string,{snapshot:CssSnapshot;id:number;identity:DomIdentity}>();
    const step:CssStep={selector:'a[href],button,input,textarea,select,summary,details,label,img,video,audio,[role],[onclick],[contenteditable="true"],[tabindex]',before:[{visible:true}]};
    const frames=await this.tab.domFrames(), connectionGeneration=this.tab.browser.client.connectionGeneration;
    const nodes:Array<{node_id:string;frame_id:string} & DomIdentity>=[];
    let total=0,visibilityIncomplete=false;const frameVisibility=new Map<string,boolean>(),frameClips=new Map<string,DomClip | null>();
    for(const frame of frames) {
    const inViewport=await this.tab.domFrameInViewport(frame,frames);frameVisibility.set(frame.id,inViewport);const clip=inViewport ? await this.tab.domFrameClip(frame,frames) : null;frameClips.set(frame.id,clip);if(!clip)continue;
    const snapshot=await this.tab.queryCss(step,undefined,[],undefined,undefined,frame.id);
    if(JSON.stringify(snapshot.frames)!==JSON.stringify(frames))throw new RetryablePreflightError("Frame tree changed; observe again");
    total+=snapshot.ids.length;if(total>1000)throw new Error("DOM snapshot matched more than 1000 elements");
    if (!snapshot.frame) throw new RetryablePreflightError('DOM frame unavailable; observe again');
    const sessionId=snapshot.frame.sessionId;
    const world=await this.tab.browser.cdp.call(this.tab.id,'Page.createIsolatedWorld',{frameId:snapshot.frame.id,worldName:'open-browser-use-selector'},{sessionId});
    if(!isObject(world) || typeof world.executionContextId!=='number')throw new RetryablePreflightError('DOM context unavailable; observe again');
    const objects:Array<{id:number;objectId:string}>=[];
    try {
      for(const id of snapshot.ids) {
        const resolved=await this.tab.browser.cdp.call(this.tab.id,'DOM.resolveNode',{backendNodeId:id,executionContextId:world.executionContextId},{sessionId});
        const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if(typeof objectId!=='string')throw new RetryablePreflightError('DOM target changed; observe again');
        objects.push({id,objectId});
      }
      if(objects.length && !visibilityIncomplete) {
        const state=await this.tab.browser.cdp.call(this.tab.id,'Runtime.callFunctionOn',{objectId:objects[0].objectId,returnByValue:true,functionDeclaration:`function(){return this.ownerDocument.visibilityState}`},{sessionId});
        const value=isObject(state) && isObject(state.result) ? state.result.value : undefined;
        if(value!=='hidden' && value!=='visible')throw new RetryablePreflightError('DOM visibility unavailable; observe again');
        if(value==='hidden')visibilityIncomplete=true;
      }
      const observeIntersections=async():Promise<boolean[]>=>{
        if(!objects.length)return [];
        if(visibilityIncomplete)return objects.map(()=>true);
        const observed=await this.tab.browser.cdp.call(this.tab.id,'Runtime.callFunctionOn',{objectId:objects[0].objectId,arguments:objects.slice(1).map(item=>({objectId:item.objectId})),returnByValue:true,awaitPromise:true,functionDeclaration:`async function(...others){const nodes=[this,...others];return await new Promise((resolve,reject)=>{const indices=new Map(nodes.map((node,index)=>[node,index])),values=Array(nodes.length),seen=new Set();const timer=setTimeout(()=>{observer.disconnect();reject(new Error('Intersection observation timed out'))},3000);const observer=new IntersectionObserver(entries=>{for(const entry of entries){const index=indices.get(entry.target);if(index===undefined)continue;values[index]=entry.isIntersecting && entry.intersectionRect.width>0 && entry.intersectionRect.height>0;seen.add(index)}if(seen.size===nodes.length){clearTimeout(timer);observer.disconnect();resolve(values)}});for(const node of nodes)observer.observe(node)})}`},{sessionId});
        const exception=isObject(observed) && isObject(observed.exceptionDetails) && isObject(observed.exceptionDetails.exception) ? observed.exceptionDetails.exception.description : undefined;
        if(typeof exception==='string' && exception.includes('Intersection observation timed out')) {visibilityIncomplete=true;return objects.map(()=>true);}
        const values=isObject(observed) && isObject(observed.result) ? observed.result.value : null;
        if(!Array.isArray(values) || values.length!==objects.length || values.some(value=>typeof value!=='boolean'))throw new RetryablePreflightError('DOM visibility unavailable; observe again');
        return values as boolean[];
      };
      const intersections=await observeIntersections();
      for(let i=0;i<objects.length;i++) {
        if(!intersections[i])continue;
        const {id,objectId}=objects[i];
        const result=await this.tab.browser.cdp.call(this.tab.id,'Runtime.callFunctionOn',{objectId,returnByValue:true,arguments:[{value:clip},{value:visibilityIncomplete}],functionDeclaration:`function(clip,fallback){if(!this.isConnected)return null;const r=this.getBoundingClientRect();let left=Math.max(r.left,clip.left),right=Math.min(r.right,clip.right),top=Math.max(r.top,clip.top),bottom=Math.min(r.bottom,clip.bottom);if(fallback){let child=this,escape=null;while(child){const childStyle=getComputedStyle(child);if(!escape && (childStyle.position==='absolute' || childStyle.position==='fixed'))escape=childStyle.position;const parent=child.parentElement || (child.getRootNode() instanceof ShadowRoot ? child.getRootNode().host : null);if(!parent)break;const style=getComputedStyle(parent), containing=style.transform!=='none' || style.perspective!=='none' || style.filter!=='none' || /(?:layout|paint|strict|content)/.test(style.contain);if(escape && style.display!=='contents' && (containing || (escape==='absolute' && style.position!=='static')))escape=null;if(!escape){const bounds=parent.getBoundingClientRect();if(['hidden','scroll','auto'].includes(style.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right)}if(['hidden','scroll','auto'].includes(style.overflowY)){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom)}}child=parent}}if(right<=left || bottom<=top)return {outside:true};return (${domIdentityFunction}).call(this)}`},{sessionId});
        const value=isObject(result) && isObject(result.result) ? result.result.value : null;
        if(!isObject(value))throw new RetryablePreflightError('DOM target changed; observe again');
        if(value.outside===true)continue;
        if(typeof value.tag!=='string' || (value.role!==null && typeof value.role!=='string') || (value.name!==null && typeof value.name!=='string') || (value.type!==null && typeof value.type!=='string') || typeof value.disabled!=='boolean' || ![true,false,'mixed',null].includes(value.checked as any))throw new RetryablePreflightError('DOM target changed; observe again');
        const node_id=randomUUID(),identity:DomIdentity={tag:value.tag,role:value.role as string | null,name:value.name as string | null,type:value.type as string | null,disabled:value.disabled,checked:value.checked as boolean | 'mixed' | null};ids.set(node_id,{snapshot,id,identity});nodes.push({node_id,frame_id:frame.id,...identity});
      }
      const beforeIncomplete=visibilityIncomplete,latestIntersections=await observeIntersections();
      if(!beforeIncomplete && !visibilityIncomplete && JSON.stringify(latestIntersections)!==JSON.stringify(intersections))throw new RetryablePreflightError('DOM visibility changed; observe again');
    } finally {for(const {objectId} of objects)await this.tab.browser.cdp.call(this.tab.id,'Runtime.releaseObject',{objectId},{sessionId}).catch(()=>{});}
    const fresh=await this.tab.queryCss(step,undefined,[],undefined,undefined,frame.id);
    if(fresh.documentId!==snapshot.documentId || JSON.stringify(fresh.frames)!==JSON.stringify(snapshot.frames) || JSON.stringify(fresh.ids)!==JSON.stringify(snapshot.ids)) {throw new RetryablePreflightError('DOM changed; observe again');}
    }
    if(JSON.stringify(await this.tab.domFrames())!==JSON.stringify(frames))throw new RetryablePreflightError("Frame tree changed; observe again");
    for(const frame of frames) {const visible=await this.tab.domFrameInViewport(frame,frames);if(visible!==frameVisibility.get(frame.id) || JSON.stringify(visible ? await this.tab.domFrameClip(frame,frames) : null)!==JSON.stringify(frameClips.get(frame.id)))throw new RetryablePreflightError("Frame visibility changed; observe again");}
    if(this.busy || this.generation!==generation || this.tab.browser.client.connectionGeneration!==connectionGeneration)throw new RetryablePreflightError('DOM snapshot superseded; observe again');
    this.ids=ids;this.connectionGeneration=connectionGeneration;this.snapshot=true;return {nodes,...(visibilityIncomplete ? {visibility_incomplete:true} : {})};
  }
  private target(node_id:string):{snapshot:CssSnapshot;id:number;identity:DomIdentity} {
    const target=this.ids.get(node_id);if(!this.snapshot || !target || this.tab.browser.client.connectionGeneration!==this.connectionGeneration)throw new Error('Unknown or stale DOM node id');return target;
  }
  private async clickNode(node_id:string,double:boolean):Promise<void> {
    const {snapshot,id,identity}=this.target(node_id),finish=this.beginAction();try {if(!snapshot.frame || !await this.tab.domFrameInViewport(snapshot.frame,snapshot.frames))throw new RetryablePreflightError('DOM frame is outside the viewport; observe again');await this.tab.actCss(snapshot,id,false,undefined,undefined,double,undefined,undefined,false,undefined,identity,this.connectionGeneration);} finally {finish();}
  }
  click(options:{node_id:string}):Promise<void> { return this.clickNode(options.node_id,false); }
  double_click(options:{node_id:string}):Promise<void> { return this.clickNode(options.node_id,true); }
  async keypress(options:{keys:string[]}):Promise<void> { const finish=this.beginAction();try {await this.tab.cua.keypress(options);} finally {finish();} }
  async type(options:{text:string}):Promise<void> { const finish=this.beginAction();try {await this.tab.cua.type(options);} finally {finish();} }
  async scroll(options:{node_id?:string;x:number;y:number}):Promise<void> {
    const target=options.node_id!==undefined ? this.target(options.node_id) : undefined, finish=this.beginAction();
    try {
    let point:{x:number;y:number}, frame:{sessionId:string;contextId:number;inputPoint:{x:number;y:number}}|undefined;
    if(options.node_id!==undefined) {
      const {snapshot,id,identity}=target!;if(!snapshot.frame || !await this.tab.domFrameInViewport(snapshot.frame,snapshot.frames))throw new RetryablePreflightError('DOM frame is outside the viewport; observe again');if(await this.tab.readCss(snapshot,id,'visible')!==true)throw new RetryablePreflightError('DOM target is hidden; observe again');
      const world=await this.tab.browser.cdp.call(this.tab.id,'Page.createIsolatedWorld',{frameId:snapshot.frame!.id,worldName:'open-browser-use-selector'},{sessionId:snapshot.frame?.sessionId});
      if(!isObject(world) || typeof world.executionContextId!=='number')throw new RetryablePreflightError('DOM context unavailable; observe again');
      const resolved=await this.tab.browser.cdp.call(this.tab.id,'DOM.resolveNode',{backendNodeId:id,executionContextId:world.executionContextId},{sessionId:snapshot.frame?.sessionId});
      const objectId=isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
      if(typeof objectId!=='string')throw new RetryablePreflightError('DOM target changed; observe again');
      try {
        const result=await this.tab.browser.cdp.call(this.tab.id,'Runtime.callFunctionOn',{objectId,returnByValue:true,arguments:[{value:identity}],functionDeclaration:`function(expected){if(!this.isConnected)return null;const actual=(${domIdentityFunction}).call(this);if(!actual || Object.keys(expected).some(key=>actual[key]!==expected[key]))return null;const r=this.getBoundingClientRect(),x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;let target=this,root=target.getRootNode();while(true){const hit=root.elementFromPoint(x,y);if(!hit || (hit!==target && !target.contains(hit)))return null;if(!(root instanceof ShadowRoot))return {x,y};target=root.host;root=target.getRootNode()}}`},{sessionId:snapshot.frame?.sessionId});
        const value=isObject(result) && isObject(result.result) ? result.result.value : null;
        if(!isObject(value) || typeof value.x!=='number' || typeof value.y!=='number')throw new RetryablePreflightError('DOM target changed; observe again');
        const mapped=await this.tab.domFramePoint(snapshot,{x:value.x,y:value.y});point=mapped.point;if(snapshot.frame.sessionId)frame={sessionId:snapshot.frame.sessionId,contextId:world.executionContextId,inputPoint:mapped.inputPoint};await this.tab.readCss(snapshot,id,'visible');
      } finally {await this.tab.browser.cdp.call(this.tab.id,'Runtime.releaseObject',{objectId},{sessionId:snapshot.frame?.sessionId}).catch(()=>{});}
    } else {
      const metrics=await this.tab.browser.cdp.call(this.tab.id,'Page.getLayoutMetrics');const viewport=isObject(metrics) && isObject(metrics.cssVisualViewport) ? metrics.cssVisualViewport : null;
      if(!viewport || typeof viewport.clientWidth!=='number' || typeof viewport.clientHeight!=='number')throw new Error('Browser viewport is unavailable');point={x:viewport.clientWidth/2,y:viewport.clientHeight/2};
    }
    if(target && this.tab.browser.client.connectionGeneration!==this.connectionGeneration)throw new RetryablePreflightError('Connection changed; observe again');
    await this.tab.scrollAt(point.x,point.y,options.x,options.y,0,target ? this.connectionGeneration : undefined,frame);
    } finally {finish();}
  }
}

export class OpenBrowserUseTabClipboard {
  constructor(private tab: OpenBrowserUseTab) {}
  async readText(): Promise<string> {
    const result = await this.tab.browser.client.readClipboardText(this.tab.id);
    if (!isObject(result) || typeof result.text !== "string") throw new Error("Browser returned invalid clipboard text");
    return result.text;
  }
  async writeText(text: string): Promise<void> {
    if (typeof text !== "string") throw new Error("Clipboard text must be a string");
    await this.tab.browser.client.writeClipboardText(this.tab.id,text);
  }
  async read(): Promise<OpenBrowserUseClipboardItem[]> {
    const result = await this.tab.browser.client.readClipboard(this.tab.id);
    if (!isObject(result) || !Array.isArray(result.items)) throw new Error("Browser returned invalid clipboard items");
    return result.items.map(item => {
      if (!isObject(item) || !Array.isArray(item.entries) || (item.presentation_style !== undefined && !["unspecified","inline","attachment"].includes(String(item.presentation_style)))) throw new Error("Browser returned invalid clipboard item");
      const entries = item.entries.map(entry => {
        if (!isObject(entry) || typeof entry.mime_type !== "string" || !entry.mime_type || (entry.text !== undefined && typeof entry.text !== "string") || (entry.base64 !== undefined && typeof entry.base64 !== "string") || (typeof entry.text === "string") === (typeof entry.base64 === "string")) throw new Error("Browser returned invalid clipboard entry");
        return {mimeType:entry.mime_type,...(typeof entry.text === "string" ? {text:entry.text} : {base64:entry.base64 as string})};
      });
      return {entries,...(item.presentation_style !== undefined ? {presentationStyle:item.presentation_style as OpenBrowserUseClipboardItem["presentationStyle"]} : {})};
    });
  }
  async write(items: OpenBrowserUseClipboardItem[]): Promise<void> {
    if (!Array.isArray(items)) throw new Error("Clipboard items must be an array");
    const wire = items.map(item => {
      if (!item || !Array.isArray(item.entries) || !item.entries.length || (item.presentationStyle !== undefined && !["unspecified","inline","attachment"].includes(item.presentationStyle))) throw new Error("Invalid clipboard item");
      const seen = new Set<string>();
      const entries = item.entries.map(entry => {
        if (!entry || typeof entry.mimeType !== "string" || !entry.mimeType || seen.has(entry.mimeType) || (entry.text !== undefined && typeof entry.text !== "string") || (entry.base64 !== undefined && typeof entry.base64 !== "string") || (typeof entry.text === "string") === (typeof entry.base64 === "string")) throw new Error("Invalid clipboard entry");
        if (entry.base64 !== undefined && !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}(?:==)?|[A-Za-z0-9+/]{3}=?)?$/.test(entry.base64)) throw new Error("Invalid clipboard base64");
        seen.add(entry.mimeType);
        return {mime_type:entry.mimeType,...(typeof entry.text === "string" ? {text:entry.text} : {base64:entry.base64!})};
      });
      return {entries,...(item.presentationStyle !== undefined ? {presentation_style:item.presentationStyle} : {})};
    });
    await this.tab.browser.client.writeClipboard(this.tab.id,wire);
  }
}

export class OpenBrowserUseTabDev {
  constructor(private tab: OpenBrowserUseTab) {}
  async watch(): Promise<void> { await this.tab.browser.cdp.watchLogs(this.tab.id); }
  async logs(options: {filter?: string; levels?: Array<OpenBrowserUseLogEntry["level"] | "warning">; limit?: number} = {}): Promise<OpenBrowserUseLogEntry[]> {
    if (!options || typeof options !== "object" || (options.filter !== undefined && typeof options.filter !== "string") ||
        (options.limit !== undefined && (!Number.isSafeInteger(options.limit) || options.limit < 0 || options.limit > 500)) ||
        (options.levels !== undefined && (!Array.isArray(options.levels) || options.levels.some(level => !["debug","info","log","warn","warning","error"].includes(level))))) throw new Error("Invalid log options");
    await this.watch();
    const levels = options.levels?.map(level => level === "warning" ? "warn" : level);
    const entries = this.tab.browser.cdp.logs(this.tab.id).filter(entry => (!levels || levels.includes(entry.level)) && (options.filter === undefined || entry.message.includes(options.filter)));
    return options.limit === undefined ? entries : options.limit === 0 ? [] : entries.slice(-options.limit);
  }
}

export class OpenBrowserUseTabPlaywright {
  readonly tab: OpenBrowserUseTab;

  constructor(tab: OpenBrowserUseTab) {
    this.tab = tab;
  }

  waitForLoadState(options: OpenBrowserUseWaitForLoadStateOptions = {}): Promise<void> {
    return this.tab.waitForLoadState(options);
  }

  expectNavigation<T>(action: () => Promise<T>, options: {timeoutMs?: number; url?: string | RegExp; waitUntil?: OpenBrowserUseLoadState} = {}): Promise<T> {
    return this.tab.expectNavigation(action, options);
  }

  waitForURL(url: string | RegExp, options: {waitUntil?: OpenBrowserUseWaitUntil; timeoutMs?: number} = {}): Promise<void> {
    return this.tab.waitForURL(url, options);
  }

  async expectPopup(action:()=>Promise<unknown>, options:{timeoutMs?:number} = {}):Promise<OpenBrowserUseTab> {
    if(typeof action!=="function" || !options || typeof options!=="object" || Array.isArray(options) || Object.keys(options).some(key=>key!=="timeoutMs"))throw new Error("Invalid popup expectation");
    const timeoutMs=options.timeoutMs ?? defaultNavigationTimeoutMs;
    if(!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000)throw new Error("Invalid popup timeout");
    const release=this.tab.browser.beginPopupWait(this.tab.id),deadline=performance.now()+timeoutMs;
    let generation=this.tab.browser.client.isConnected ? this.tab.browser.client.connectionGeneration : undefined;
    try {
    let preflightTimer:ReturnType<typeof setTimeout>|undefined;
    let baseline:BrowserTabInfo[];
    try {
      baseline=await Promise.race([this.tab.browser.tabs.list(),new Promise<never>((_,reject)=>{preflightTimer=setTimeout(()=>reject(new Error("Popup preparation timed out before action")),Math.max(0,deadline-performance.now()));})]);
    } finally {if(preflightTimer)clearTimeout(preflightTimer);}
    if(generation!==undefined && generation!==this.tab.browser.client.connectionGeneration)throw new Error("Connection changed during popup preparation before action");
    generation=this.tab.browser.client.connectionGeneration;
    if(!baseline.some(item=>item.id===String(this.tab.id)))throw new Error("Opener is outside this browser session");
    const remaining=deadline-performance.now();
    if(remaining<=0)throw new Error("Popup preparation timed out before action");
    const existing=new Set(baseline.map(item=>item.id));
    let done=false,timer:ReturnType<typeof setTimeout>|undefined;
    try {
      const watch=async():Promise<OpenBrowserUseTab>=>{
        while(!done) {
          const tabs=await this.tab.browser.tabs.list();
          if(done)throw new Error("Popup wait cancelled");
          if(generation!==this.tab.browser.client.connectionGeneration)throw new Error("Connection changed while waiting for popup");
          const matches=tabs.filter(item=>!existing.has(item.id) && item.openerTabId===String(this.tab.id));
          if(matches.length>1)throw new Error("Multiple popups matched; inspect the session before continuing");
          if(matches.length===1)return this.tab.browser.tab(browserTabId(matches[0].id));
          const remaining=deadline-performance.now();if(remaining<=0)throw new Error("Popup outcome unknown after timeout; inspect the session before retrying");
          await new Promise(resolve=>setTimeout(resolve,Math.min(50,remaining)));
        }
        throw new Error("Popup wait cancelled");
      };
      const work=Promise.all([Promise.resolve().then(action),watch()]).then(async ([,popup])=>{
        const tabs=await this.tab.browser.tabs.list();
        if(done)throw new Error("Popup wait cancelled");
        if(generation!==this.tab.browser.client.connectionGeneration)throw new Error("Connection changed while waiting for popup");
        const matches=tabs.filter(item=>!existing.has(item.id) && item.openerTabId===String(this.tab.id));
        if(matches.length>1)throw new Error("Multiple popups matched; inspect the session before continuing");
        if(matches.length!==1 || matches[0].id!==String(popup.id))throw new Error("Popup changed or closed; inspect the session before continuing");
        return popup;
      });
      return await Promise.race([work,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error("Popup outcome unknown after timeout; inspect the session before retrying")),remaining);})]);
    } finally {done=true;if(timer)clearTimeout(timer);}
    } finally {release();}
  }

  domSnapshot(): Promise<string> {
    return this.tab.domSnapshot();
  }

  evaluate<T extends JsonValue = JsonValue>(pageFunction: string | ((arg:T) => unknown), arg?:T): Promise<JsonValue> {
    if (typeof pageFunction === "string") {
      if (arg !== undefined) throw new Error("An evaluation argument requires a function");
      return this.tab.evaluate(pageFunction,{awaitPromise:true});
    }
    if (typeof pageFunction !== "function") throw new Error("Evaluation requires a function or expression");
    let serialized: string | undefined;
    try {
      serialized=arg === undefined ? undefined : JSON.stringify(arg,(_key,value)=>{
        if (typeof value === "number" && (!Number.isFinite(value) || Object.is(value,-0))) throw new Error("Invalid JSON number");
        if (["undefined","function","symbol","bigint"].includes(typeof value) || (value && typeof value === "object" && Object.getOwnPropertySymbols(value).length)) throw new Error("Invalid JSON value");
        return value;
      });
    } catch { throw new Error("Evaluation argument must be JSON serializable without losing values"); }
    if (arg !== undefined && serialized === undefined) throw new Error("Evaluation argument must be JSON serializable");
    // Computed keys preserve __proto__ as data without using the page’s JSON.parse.
    const encode=(value:JsonValue):string => Array.isArray(value) ? `[${value.map(encode).join(",")}]` : value !== null && typeof value === "object" ? `{${Object.entries(value).map(([key,item])=>`[${JSON.stringify(key)}]:${encode(item)}`).join(",")}}` : JSON.stringify(value);
    let input:string;
    try { input=serialized === undefined ? "undefined" : encode(JSON.parse(serialized) as JsonValue); } catch { throw new Error("Evaluation argument must be JSON serializable"); }
    return this.tab.evaluate(`(${Function.prototype.toString.call(pageFunction)})(${input})`,{awaitPromise:true});
  }

  async screenshot(options: {clip?: {x:number; y:number; width:number; height:number}; fullPage?: boolean} = {}): Promise<OpenBrowserUseImage> {
    return new OpenBrowserUseImage(await this.tab.getScreenshot(options));
  }

  waitForTimeout(timeoutMs: number): Promise<void> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid timeout");
    return new Promise(resolve=>setTimeout(resolve,timeoutMs));
  }

  waitForEvent(event: "download", options?: {timeoutMs?: number}): Promise<OpenBrowserUseDownload>;
  waitForEvent(event: "filechooser", options?: {timeoutMs?: number}): Promise<OpenBrowserUseFileChooser>;
  waitForEvent(event: "download" | "filechooser", options: {timeoutMs?: number} = {}): Promise<OpenBrowserUseDownload | OpenBrowserUseFileChooser> {
    if (event !== "download" && event !== "filechooser") throw new Error("Unsupported browser event");
    const preparing: Promise<OpenBrowserUseDownloadWait | OpenBrowserUseFileChooserWait> = event === "download" ? this.tab.prepareDownload(options) : this.tab.prepareFileChooser(options);
    this.tab.browser.cdp.blockUntilPrepared(this.tab.id,preparing);
    return preparing.then(async wait=>await wait.wait());
  }

  frameLocator(selector: string): OpenBrowserUseFrameLocator {
    return new OpenBrowserUseFrameLocator(this.tab,[]).frameLocator(selector);
  }

  locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab,selector),options); }
  getByTestId(testId: string): OpenBrowserUseCssLocator { return this.locator(testIdSelector(testId)); }
  getByTitle(title: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseCssLocator { return this.locator("[title], :is(svg, svg *):has(> title)").matchTitle(title,options); }

  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator {
    if (typeof role !== "string" || !role || !options || typeof options !== "object" || Array.isArray(options) ||
        Object.keys(options).some(key => !["name","exact","level","checked","disabled","pressed","selected","expanded"].includes(key)) ||
        (options.name !== undefined && typeof options.name !== "string" && !types.isRegExp(options.name)) ||
        (options.level !== undefined && (role !== "heading" || !Number.isSafeInteger(options.level) || options.level < 1)) ||
        [options.exact,options.checked,options.disabled,options.pressed,options.selected,options.expanded].some(value => value !== undefined && typeof value !== "boolean")) throw new Error("Invalid role locator");
    return new OpenBrowserUseRoleLocator(this.tab, [role === "img" ? "image" : role], {...options,...(options.name !== undefined ? {name:copyMatcher(options.name)} : {})});
  }

  getByLabel(name: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if ((typeof name !== "string" && !types.isRegExp(name)) || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid label locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "switch", "slider", "spinbutton", "Date", "DateTime", "InputTime"], {name:copyMatcher(name), ...options});
  }

  getByText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if ((typeof text !== "string" && !types.isRegExp(text)) || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid text locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["StaticText"], {name:copyMatcher(text), ...options}, undefined, true);
  }

  getByAltText(altText: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if ((typeof altText !== "string" && !types.isRegExp(altText)) || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid alt text locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["image", "button", "link"], {name:copyMatcher(altText), ...options}, undefined, false, "altText");
  }

  getByPlaceholder(placeholder: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if ((typeof placeholder !== "string" && !types.isRegExp(placeholder)) || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid placeholder locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "spinbutton"], {name:copyMatcher(placeholder), ...options}, undefined, false, "placeholder");
  }
}

export class OpenBrowserUseFrameLocator {
  constructor(private tab: OpenBrowserUseTab, private path: readonly string[]) {}
  frameLocator(selector: string): OpenBrowserUseFrameLocator {
    if (typeof selector !== "string" || !selector.trim() || selector.length > 4096 || this.path.length >= 32) throw new Error("Invalid frame selector");
    return new OpenBrowserUseFrameLocator(this.tab,[...this.path,selector]);
  }
  locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab,selector,this.path),options); }
  getByTestId(testId: string): OpenBrowserUseCssLocator { return this.locator(testIdSelector(testId)); }
  getByTitle(title: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseCssLocator { return this.locator("[title], :is(svg, svg *):has(> title)").matchTitle(title,options); }
  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByRole(role,options).withinFrame(this.path); }
  getByLabel(name: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByLabel(name,options).withinFrame(this.path); }
  getByText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByText(text,options).withinFrame(this.path); }
  getByAltText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByAltText(text,options).withinFrame(this.path); }
  getByPlaceholder(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByPlaceholder(text,options).withinFrame(this.path); }
}

export class OpenBrowserUseCssLocator {
  constructor(private tab: OpenBrowserUseTab, private selector: string, private framePath?: readonly string[], private position?: number, private scopes: readonly CssStep[] = [], private before: readonly CssTextFilter[] = [], private after: readonly CssTextFilter[] = [], private union?: readonly [readonly CssStep[],readonly CssStep[]], private semanticScope?: OpenBrowserUseRoleLocator) {
    if (typeof selector !== "string" || !selector.trim() || selector.length > 4096) throw new Error("Invalid CSS selector");
  }
  nth(index: number): OpenBrowserUseCssLocator {
    if (!Number.isSafeInteger(index) || index < 0) throw new Error("Locator index must be a non-negative integer");
    return new OpenBrowserUseCssLocator(this.tab,this.selector,this.framePath,this.position === undefined ? index : index === 0 ? this.position : Number.MAX_SAFE_INTEGER,this.scopes,this.before,this.after,this.union,this.semanticScope);
  }
  first(): OpenBrowserUseCssLocator { return this.nth(0); }
  last(): OpenBrowserUseCssLocator { return this.position === undefined ? new OpenBrowserUseCssLocator(this.tab,this.selector,this.framePath,-1,this.scopes,this.before,this.after,this.union,this.semanticScope) : this; }
  locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator {
    if (this.scopes.length >= 31) throw new Error("CSS locator nesting exceeds 32 levels");
    return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab,selector,this.framePath,undefined,[...this.scopes,this.step()],[],[],undefined,this.semanticScope),options);
  }
  /** @internal */
  matchTitle(title: TextMatcher, options: {exact?: boolean}): OpenBrowserUseCssLocator {
    if ((typeof title !== "string" && !types.isRegExp(title)) || (typeof title === "string" && title.length > 30000) || !options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key=>key!=="exact") || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid title locator");
    const matcher=typeof title === "string" ? title : {source:title.source,flags:title.flags};
    return new OpenBrowserUseCssLocator(this.tab,this.selector,this.framePath,this.position,this.scopes,[...this.before,{title:{matcher,exact:options.exact === true}}],this.after,this.union,this.semanticScope);
  }
  /** @internal */
  getFramePath(): readonly string[] | undefined { return this.framePath; }
  /** @internal */
  isRelativeTo(tab:OpenBrowserUseTab, framePath?:readonly string[]): boolean {
    return this.tab.browser===tab.browser && this.tab.id===tab.id && JSON.stringify(this.framePath ?? null)===JSON.stringify(framePath ?? null) && !this.semanticScope;
  }
  /** @internal */
  async countWithin(observation:Observation, index:number): Promise<number> {
    return (await this.snapshotWithin(observation,index)).ids.length;
  }
  /** @internal */
  snapshotWithin(observation:Observation, index:number): Promise<CssSnapshot> {
    return this.tab.queryCss(this.step(),this.framePath,this.scopes,undefined,{observation,index});
  }
  getByTestId(testId: string): OpenBrowserUseCssLocator { return this.locator(testIdSelector(testId)); }
  getByTitle(title: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseCssLocator { return this.locator("[title], :is(svg, svg *):has(> title)").matchTitle(title,options); }
  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByRole(role,options).withinCss(this); }
  getByLabel(name: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByLabel(name,options).withinCss(this); }
  getByText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByText(text,options).withinCss(this); }
  getByAltText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByAltText(text,options).withinCss(this); }
  getByPlaceholder(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.tab.playwright.getByPlaceholder(text,options).withinCss(this); }
  /** @internal */
  snapshot(): Promise<CssSnapshot> { return this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope); }
  private step(): CssStep { return {selector:this.selector,...(this.position !== undefined ? {position:this.position} : {}),before:this.before,after:this.after,...(this.union ? {union:this.union} : {})}; }
  private innerSteps(value:OpenBrowserUseCssLocator):CssStep[] {
    if (!(value instanceof OpenBrowserUseCssLocator) || (value.tab.browser!==this.tab.browser || value.tab.id!==this.tab.id) || JSON.stringify(value.framePath ?? null)!==JSON.stringify(this.framePath ?? null)) throw new Error("Filter locator must belong to the same tab and frame");
    if (value.semanticScope && value.semanticScope!==this.semanticScope) throw new Error("Filter locator must share the semantic scope");
    const steps=[...value.scopes,value.step()];
    const depth=(items:readonly CssStep[],level:number):void=>{
      if(level>8)throw new Error("Locator filter nesting exceeds 8 levels");
      for(const step of items) {if(step.union) {depth(step.union[0],level+1);depth(step.union[1],level+1);}for(const filter of [...(step.before ?? []),...(step.after ?? [])]) {if(filter.has)depth(filter.has,level+1);if(filter.hasNot)depth(filter.hasNot,level+1);if(filter.and)depth(filter.and,level+1);}}
    };
    depth(steps,2);
    return steps;
  }
  and(locator: OpenBrowserUseCssLocator): OpenBrowserUseCssLocator;
  and(locator: OpenBrowserUseRoleLocator): OpenBrowserUseRoleLocator;
  and(locator: OpenBrowserUseCssLocator | OpenBrowserUseRoleLocator): OpenBrowserUseCssLocator | OpenBrowserUseRoleLocator {
    if (locator instanceof OpenBrowserUseRoleLocator) return locator.and(this);
    if (locator?.semanticScope!==this.semanticScope) throw new Error("Intersection locators must share a semantic scope");
    const filter:CssTextFilter={and:this.innerSteps(locator)};
    return new OpenBrowserUseCssLocator(this.tab,this.selector,this.framePath,this.position,this.scopes,this.position === undefined ? [...this.before,filter] : this.before,this.position === undefined ? this.after : [...this.after,filter],this.union,this.semanticScope);
  }
  or(locator: OpenBrowserUseCssLocator): OpenBrowserUseCssLocator {
    if (locator?.semanticScope!==this.semanticScope) throw new Error("Union locators must share a semantic scope");
    return new OpenBrowserUseCssLocator(this.tab,"*",this.framePath,undefined,[],[],[],[this.innerSteps(this),this.innerSteps(locator)],this.semanticScope);
  }
  filter(options: {hasText?: TextMatcher; hasNotText?: TextMatcher; has?: OpenBrowserUseCssLocator; hasNot?: OpenBrowserUseCssLocator; visible?: boolean}): OpenBrowserUseCssLocator {
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key=>!["hasText","hasNotText","has","hasNot","visible"].includes(key)) ||
        (options.hasText === undefined && options.hasNotText === undefined && options.has === undefined && options.hasNot === undefined && options.visible === undefined) || (options.visible !== undefined && typeof options.visible !== "boolean") || [options.hasText,options.hasNotText].some(value=>value !== undefined && (typeof value === "string" ? value.length>30_000 : !types.isRegExp(value)))) throw new Error("Invalid locator filter");
    const encode=(value:TextMatcher):CssMatcher=>typeof value === "string" ? value : {source:value.source,flags:value.flags};
    const filter:CssTextFilter={...(options.hasText !== undefined ? {hasText:encode(options.hasText)} : {}),...(options.hasNotText !== undefined ? {hasNotText:encode(options.hasNotText)} : {}),...(options.has !== undefined ? {has:this.innerSteps(options.has)} : {}),...(options.hasNot !== undefined ? {hasNot:this.innerSteps(options.hasNot)} : {}),...(options.visible !== undefined ? {visible:options.visible} : {})};
    return new OpenBrowserUseCssLocator(this.tab,this.selector,this.framePath,this.position,this.scopes,this.position === undefined ? [...this.before,filter] : this.before,this.position === undefined ? this.after : [...this.after,filter],this.union,this.semanticScope);
  }
  async count(): Promise<number> { return (await this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope)).ids.length; }
  async all(): Promise<OpenBrowserUseCssLocator[]> { return Array.from({length:await this.count()},(_,i)=>this.nth(i)); }
  allTextContents(options: {timeoutMs?: number} = {}): Promise<string[]> { return this.readAllText("textContent",options); }
  allInnerTexts(options: {timeoutMs?: number} = {}): Promise<string[]> { return this.readAllText("innerText",options); }
  private async readAllText(mode: "textContent" | "innerText", options: {timeoutMs?: number}): Promise<string[]> {
    const timeoutMs=options.timeoutMs ?? 5000;
    if (!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000) throw new Error("Invalid locator timeout");
    const deadline=performance.now()+timeoutMs;
    while (true) {
      try {
        const snapshot=await locatorReadBeforeDeadline(this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope),timeoutMs,deadline,"Timed out reading locator texts"), values:string[]=[];
        let total=0;
        for (const id of snapshot.ids) {
          const value=await locatorReadBeforeDeadline(this.tab.readCss(snapshot,id,mode),timeoutMs,deadline,"Timed out reading locator texts");
          if (typeof value !== "string") throw new RetryablePreflightError("Target text is unavailable; observe again");
          total+=value.length;if(total>1_000_000) throw new Error("Locator values exceed the 1000000 character limit");
          values.push(value);
        }
        return values;
      } catch(error) {
        if (!(error instanceof RetryablePreflightError) || performance.now()>=deadline) throw error;
        await new Promise(resolve=>setTimeout(resolve,Math.min(100,deadline-performance.now())));
      }
    }
  }
  private async perform<T>(action: (snapshot: CssSnapshot, id: number) => Promise<T>, timeoutMs = 5000, readOnly = false): Promise<T> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid locator timeout");
    const deadline = performance.now()+timeoutMs;
    while (true) {
      try {
        const snapshot = await locatorReadBeforeDeadline(this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope),timeoutMs,deadline,`Locator target unavailable before timeout (${timeoutMs} ms)`);
        const ids = snapshot.ids;
        if (ids.length > 1) throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
        if (ids.length) { const result=action(snapshot,ids[0]);return readOnly ? await locatorReadBeforeDeadline(result,timeoutMs,deadline,"Timed out reading locator") : await result; }
      } catch (error) { if (!(error instanceof RetryablePreflightError)) throw error; }
      const remaining = deadline-performance.now();
      if (remaining <= 0) throw new Error(`Locator target unavailable before timeout (${timeoutMs} ms)`);
      await new Promise(resolve=>setTimeout(resolve,Math.min(100,remaining)));
    }
  }
  private read(mode: "innerText" | "textContent" | "attribute", name = "", timeoutMs = 5000): Promise<string | null> {
    return this.perform(async (snapshot,id)=>await this.tab.readCss(snapshot,id,mode,name) as string | null,timeoutMs,true);
  }
  isEnabled(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (snapshot,id)=>await this.tab.readCss(snapshot,id,"enabled") as boolean,options.timeoutMs,true); }
  isChecked(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (snapshot,id)=>await this.tab.readCss(snapshot,id,"checked") as boolean,options.timeoutMs,true); }
  isEditable(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (snapshot,id)=>await this.tab.readCss(snapshot,id,"editable") as boolean,options.timeoutMs,true); }
  boundingBox(options:{timeoutMs?:number} = {}):Promise<{x:number;y:number;width:number;height:number}|null> { return this.perform(async (snapshot,id)=>{if(!snapshot.frame)throw new RetryablePreflightError("Frame unavailable; observe again");if(!await this.tab.readCss(snapshot,id,"visible"))return null;const box=await this.tab.nodeBoundingBox(snapshot.frame,snapshot.frames,id);if(!box || !await this.tab.readCss(snapshot,id,"visible"))throw new RetryablePreflightError("Target geometry changed; observe again");return box;},options.timeoutMs,true); }
  inputValue(options: {timeoutMs?: number} = {}): Promise<string> { return this.perform(async (snapshot,id)=>await this.tab.readCss(snapshot,id,"inputValue") as string,options.timeoutMs,true); }
  async isVisible(options: {timeoutMs?:number} = {}): Promise<boolean> {
    const timeoutMs=options.timeoutMs ?? 5000;
    if (!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000) throw new Error("Invalid locator timeout");
    const deadline=performance.now()+timeoutMs, message="Timed out reading locator visibility";
    const snapshot=await locatorReadBeforeDeadline(this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope),timeoutMs,deadline,message), ids=snapshot.ids;
    if (!ids.length) return false;
    if (ids.length>1) throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
    return await locatorReadBeforeDeadline(this.tab.readCss(snapshot,ids[0],"visible"),timeoutMs,deadline,message) as boolean;
  }
  async isHidden(options: {timeoutMs?:number} = {}): Promise<boolean> { return !(await this.isVisible(options)); }
  async isDisabled(options: {timeoutMs?:number} = {}): Promise<boolean> { return !(await this.isEnabled(options)); }
  async waitFor(options: {state: "attached" | "detached" | "visible" | "hidden"; timeoutMs?: number}): Promise<void> {
    if (!options || !["attached","detached","visible","hidden"].includes(options.state)) throw new Error("Invalid locator wait state");
    const timeoutMs=options.timeoutMs ?? 5000;
    if (!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000) throw new Error("Invalid locator timeout");
    const deadline=performance.now()+timeoutMs;
    while (true) {
      try {
        const snapshot=await locatorReadBeforeDeadline(this.tab.queryCss(this.step(),this.framePath,this.scopes,this.semanticScope),timeoutMs,deadline,`Timed out waiting for locator to become ${options.state}`), ids=snapshot.ids;
        if (ids.length>1) throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
        const matched=options.state==='attached' || options.state==='detached' ? ids.length>0 : ids.length>0 && await locatorReadBeforeDeadline(this.tab.readCss(snapshot,ids[0],"visible"),timeoutMs,deadline,`Timed out waiting for locator to become ${options.state}`)===true;
        if (matched === (options.state==='attached' || options.state==='visible')) return;
      } catch(error) { if (!(error instanceof RetryablePreflightError)) throw error; }
      const remaining=deadline-performance.now();
      if (remaining<=0) throw new Error(`Timed out waiting for locator to become ${options.state}`);
      await new Promise(resolve=>setTimeout(resolve,Math.min(100,remaining)));
    }
  }
  downloadMedia(options:{timeoutMs?:number} = {}):Promise<void> {
    return this.first().perform(async (snapshot,id)=>{if (!snapshot.frame) throw new RetryablePreflightError("Download target is unavailable; observe again"); await this.tab.triggerMediaDownload(id,snapshot.frame,()=>this.tab.readCss(snapshot,id,"attribute","src"));},options.timeoutMs);
  }
  click(options: LocatorClickOptions = {}): Promise<void> { const mouse=locatorClickOptions(options); return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,undefined,false,undefined,undefined,false,mouse);},options.timeoutMs); }
  dblclick(options: LocatorClickOptions = {}): Promise<void> { const mouse=locatorClickOptions(options); return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,undefined,true,undefined,undefined,false,mouse);},options.timeoutMs); }
  hover(options: {timeoutMs?: number} = {}): Promise<void> { return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,true);},options.timeoutMs); }
  check(options: LocatorCheckOptions = {}): Promise<void> { return this.setChecked(true,options); }
  uncheck(options: LocatorCheckOptions = {}): Promise<void> { return this.setChecked(false,options); }
  setChecked(checked: boolean, options: LocatorCheckOptions = {}): Promise<void> {
    validateCheckOptions(options);
    if (typeof checked !== "boolean") throw new Error("Checked state must be a boolean");
    return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,undefined,false,checked,undefined,false,{button:"left",buttons:1,modifiers:0,...(options.force ? {force:true} : {})});},options.timeoutMs);
  }
  focus(options: {timeoutMs?: number} = {}): Promise<void> { return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,undefined,false,undefined,undefined,false,undefined,undefined,undefined,true);},options.timeoutMs); }
  press(key: string, options: {timeoutMs?: number} = {}): Promise<void> {
    if (typeof key !== "string") throw new Error("Invalid key");
    return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,key);},options.timeoutMs);
  }
  clear(options: {timeoutMs?: number} = {}): Promise<void> { return this.fill("",options); }
  fill(text: string, options: {timeoutMs?: number} = {}): Promise<void> {
    if (typeof text !== "string") throw new Error("Text must be a string");
    return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,text);},options.timeoutMs);
  }
  type(text: string, options: {timeoutMs?: number} = {}): Promise<void> {
    if (typeof text !== "string") throw new Error("Text must be a string");
    return this.perform(async (snapshot,id)=>{await this.tab.actCss(snapshot,id,false,undefined,text,false,undefined,undefined,true);},options.timeoutMs);
  }
  async selectOption(values: SelectOption | SelectOption[], options: {timeoutMs?: number} = {}): Promise<string[]> {
    const specs=selectSpecs(values);
    const result=await this.perform((snapshot,id)=>this.tab.actCss(snapshot,id,false,undefined,undefined,false,undefined,specs),options.timeoutMs);
    if (!Array.isArray(result)) throw new Error("Invalid selected options result");
    return result;
  }
  async innerText(options: {timeoutMs?: number} = {}): Promise<string> {
    const value = await this.read("innerText","",options.timeoutMs);
    if (value === null) throw new Error("Target text is unavailable");
    return value;
  }
  textContent(options: {timeoutMs?: number} = {}): Promise<string | null> { return this.read("textContent","",options.timeoutMs); }
  getAttribute(name: string, options: {timeoutMs?: number} = {}): Promise<string | null> {
    if (typeof name !== "string" || !name || name.length > 256) throw new Error("Invalid attribute name");
    return this.read("attribute",name,options.timeoutMs);
  }
}

export class OpenBrowserUseRoleLocator {
  constructor(private tab: OpenBrowserUseTab, private roles: readonly string[], private options: RoleLocatorOptions, private position?: number, private textMatch = false, private field: "name" | "placeholder" | "altText" = "name", private scope?: OpenBrowserUseRoleLocator, private filtersBefore: TextFilter[] = [], private filtersAfter: TextFilter[] = [], private framePath?: readonly string[], private cssScope?: OpenBrowserUseCssLocator, private combination?: {kind:"and" | "or"; left:OpenBrowserUseRoleLocator; right:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator}) {}

  /** @internal */
  withinFrame(path: readonly string[]): OpenBrowserUseRoleLocator {
    return new OpenBrowserUseRoleLocator(this.tab,this.roles,this.options,this.position,this.textMatch,this.field,this.scope,this.filtersBefore,this.filtersAfter,[...path],this.cssScope,this.combination);
  }

  /** @internal */
  withinCss(scope: OpenBrowserUseCssLocator): OpenBrowserUseRoleLocator {
    return new OpenBrowserUseRoleLocator(this.tab,this.roles,this.options,this.position,this.textMatch,this.field,this.scope,this.filtersBefore,this.filtersAfter,this.framePath ?? scope.getFramePath(),scope,this.combination);
  }

  nth(index: number): OpenBrowserUseRoleLocator {
    if (!Number.isSafeInteger(index) || index < 0) throw new Error("Locator index must be a non-negative integer");
    if (this.position !== undefined) return index === 0 ? this : new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, Number.MAX_SAFE_INTEGER, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter,this.framePath,this.cssScope,this.combination);
    return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, index, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter,this.framePath,this.cssScope,this.combination);
  }

  first(): OpenBrowserUseRoleLocator { return this.nth(0); }
  last(): OpenBrowserUseRoleLocator {
    return this.position !== undefined ? this : new OpenBrowserUseRoleLocator(this.tab,this.roles,this.options,-1,this.textMatch,this.field,this.scope,this.filtersBefore,this.filtersAfter,this.framePath,this.cssScope,this.combination);
  }

  locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab,selector,this.framePath,undefined,[],[],[],undefined,this),options); }
  getByTestId(testId: string): OpenBrowserUseCssLocator { return this.locator(testIdSelector(testId)); }
  getByTitle(title: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseCssLocator { return this.locator("[title], :is(svg, svg *):has(> title)").matchTitle(title,options); }

  private child(locator: OpenBrowserUseRoleLocator): OpenBrowserUseRoleLocator {
    return new OpenBrowserUseRoleLocator(this.tab,locator.roles,locator.options,locator.position,locator.textMatch,locator.field,this,locator.filtersBefore,locator.filtersAfter,this.framePath);
  }

  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByRole(role,options)); }
  getByLabel(name: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByLabel(name,options)); }
  getByText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByText(text,options)); }
  getByAltText(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByAltText(text,options)); }
  getByPlaceholder(text: TextMatcher, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByPlaceholder(text,options)); }

  private combine(kind:"and" | "or", other:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator):OpenBrowserUseRoleLocator {
    if (other instanceof OpenBrowserUseCssLocator) {
      if(kind!=="and" || !other.isRelativeTo(this.tab,this.framePath)) throw new Error("Combined locators must belong to the same tab and frame without a semantic CSS scope");
    } else if (!(other instanceof OpenBrowserUseRoleLocator) || other.tab.browser!==this.tab.browser || other.tab.id!==this.tab.id || JSON.stringify(other.framePath ?? null)!==JSON.stringify(this.framePath ?? null)) throw new Error("Combined locators must belong to the same tab and frame");
    const depth=(locator:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator):number=>locator instanceof OpenBrowserUseRoleLocator && locator.combination ? 1+Math.max(depth(locator.combination.left),depth(locator.combination.right)) : 1;
    if(Math.max(depth(this),depth(other))>=8)throw new Error("Locator combination nesting exceeds 8 levels");
    return new OpenBrowserUseRoleLocator(this.tab,[],{},undefined,false,"name",undefined,[],[],this.framePath,undefined,{kind,left:this,right:other});
  }
  and(other:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator):OpenBrowserUseRoleLocator { return this.combine("and",other); }
  or(other:OpenBrowserUseRoleLocator):OpenBrowserUseRoleLocator { return this.combine("or",other); }

  filter(options: {hasText?: TextMatcher; hasNotText?: TextMatcher; has?:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator; hasNot?:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator; visible?:boolean}): OpenBrowserUseRoleLocator {
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["hasText","hasNotText","has","hasNot","visible"].includes(key)) ||
        (options.hasText === undefined && options.hasNotText === undefined && options.has === undefined && options.hasNot === undefined && options.visible === undefined) ||
        (options.visible !== undefined && typeof options.visible !== "boolean") ||
        (options.hasText !== undefined && (typeof options.hasText === "string" ? options.hasText.length > 30_000 : !types.isRegExp(options.hasText))) ||
        (options.hasNotText !== undefined && (typeof options.hasNotText === "string" ? options.hasNotText.length > 30_000 : !types.isRegExp(options.hasNotText)))) throw new Error("Invalid locator filter");
    const check=(locator:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator,level:number):void=>{
      if (level>8) throw new Error("Locator filter nesting exceeds 8 levels");
      if (locator instanceof OpenBrowserUseCssLocator) {
        if (!locator.isRelativeTo(this.tab,this.framePath)) throw new Error("Filter locator must belong to the same tab and frame without a semantic scope");
        return;
      }
      if (!(locator instanceof OpenBrowserUseRoleLocator) || locator.tab.browser!==this.tab.browser || locator.tab.id!==this.tab.id || JSON.stringify(locator.framePath ?? null)!==JSON.stringify(this.framePath ?? null)) throw new Error("Filter locator must belong to the same tab and frame");
      if (locator.cssScope) throw new Error("Semantic filter locator cannot use a CSS scope yet");
      if(locator.scope) check(locator.scope,level);
      if(locator.combination) {check(locator.combination.left,level+1);check(locator.combination.right,level+1);}
      for(const filter of [...locator.filtersBefore,...locator.filtersAfter]) {if(filter.has)check(filter.has,level+1);if(filter.hasNot)check(filter.hasNot,level+1);}
    };
    if(options.has !== undefined)check(options.has,2);
    if(options.hasNot !== undefined)check(options.hasNot,2);
    const filter:TextFilter={...(options.visible !== undefined ? {visible:options.visible} : {}),...(options.hasText !== undefined ? {hasText:copyMatcher(options.hasText)} : {}),...(options.hasNotText !== undefined ? {hasNotText:copyMatcher(options.hasNotText)} : {}),...(options.has !== undefined ? {has:options.has} : {}),...(options.hasNot !== undefined ? {hasNot:options.hasNot} : {})};
    return new OpenBrowserUseRoleLocator(this.tab,this.roles,this.options,this.position,this.textMatch,this.field,this.scope,
      this.position === undefined ? [...this.filtersBefore,filter] : this.filtersBefore,
      this.position === undefined ? this.filtersAfter : [...this.filtersAfter,filter],this.framePath,this.cssScope,this.combination);
  }

  private needsText(): boolean {
    return this.filtersBefore.length > 0 || this.filtersAfter.length > 0 || this.roles.some(role => supplementalRoles.includes(role)) || !!this.scope?.needsText() || !!this.combination && (this.combination.left.needsText() || (this.combination.right instanceof OpenBrowserUseRoleLocator && this.combination.right.needsText()));
  }

  private async matches(observation: Observation, baseIndex?: number): Promise<LocatorMatch[]> {
    const frameId = this.framePath ? await this.tab.resolveFramePath(this.framePath,undefined,observation.frames) : undefined;
    if (this.framePath && !frameId) return [];
    const base=baseIndex === undefined ? undefined : observation.nodes.find(node=>node.index===baseIndex);
    if (baseIndex !== undefined && !base) throw new RetryablePreflightError("Filter scope changed; observe again");
    const inFrame = (node:InteractiveNode) => (!this.framePath || node.frameId === frameId) && (!base || node.frameId === base.frameId);
    if (this.field === "placeholder" && observation.nodes.some(node => inFrame(node) && this.roles.includes(node.role) && node.placeholderTruncated)) throw new Error("Some placeholders were truncated; locator results are incomplete");
    if (this.field === "altText" && observation.nodes.some(node => inFrame(node) && this.roles.includes(node.role) && node.altTextTruncated)) throw new Error("Some alt text was truncated; locator results are incomplete");
    const normalize = (value: string) => this.textMatch ? value.replace(/\s+/g," ").trim() : value;
    const matches: LocatorMatch[] = [];
    if (this.combination) {
      const left=await this.combination.left.matches(observation,baseIndex);
      let right:LocatorMatch[];
      if(this.combination.right instanceof OpenBrowserUseCssLocator) {
        const snapshot=baseIndex===undefined ? await this.combination.right.snapshot() : await this.combination.right.snapshotWithin(observation,baseIndex);
        if(snapshot.documentId!==observation.documentId || JSON.stringify(snapshot.frames)!==JSON.stringify(observation.frames))throw new RetryablePreflightError("CSS intersection changed; observe again");
        const ids=new Set(snapshot.ids);
        right=left.filter(item=>{const node=observation.nodes.find(node=>node.index===item.node.index);return !!node && (node.frameId ?? observation.frames?.[0]?.id)===snapshot.frame?.id && ids.has(node.backendNodeId);});
      } else right=await this.combination.right.matches(observation,baseIndex);
      const byIndex=new Map(right.map(item=>[item.node.index,item]));
      if(this.combination.kind==='and') matches.push(...left.filter(item=>byIndex.has(item.node.index)));
      else {
        const merged=new Map(left.map(item=>[item.node.index,item]));
        for(const item of right)if(!merged.has(item.node.index))merged.set(item.node.index,item);
        for(const node of observation.nodes) {const item=merged.get(node.index);if(item)matches.push(item);}
      }
    } else {
    const candidates = observation.nodes.filter(node => {
      const value = node[this.field];
      return inFrame(node) && this.roles.includes(node.role) && typeof value === "string" &&
        (this.options.level === undefined || node.level === this.options.level) &&
        (this.options.checked === undefined || node.checked === this.options.checked) &&
        (this.options.disabled === undefined || !!node.disabled === this.options.disabled) &&
        (this.options.pressed === undefined || node.pressed === this.options.pressed) &&
        (this.options.selected === undefined || node.selected === this.options.selected) &&
        (this.options.expanded === undefined || node.expanded === this.options.expanded) &&
        (this.options.name === undefined || (typeof this.options.name !== "string" ? new RegExp(this.options.name.source,this.options.name.flags).test(normalize(value)) : this.options.exact ? normalize(value) === normalize(this.options.name) : normalize(value).toLowerCase().includes(normalize(this.options.name).toLowerCase())));
    });
    if (!this.scope && this.cssScope) {
      const snapshot=await this.cssScope.snapshot();
      for (const node of candidates) for (const scopeId of snapshot.ids) {
        if (await this.tab.cssScopeContains(observation,snapshot,scopeId,node.index)) {matches.push({node,path:[],filters:[],css:{snapshot,scopeId}});break;}
      }
    } else if (!this.scope) {
      for (const node of candidates) if (!base || await this.tab.scopeContains(observation,base.index,node.index)) matches.push({node,path:[],filters:[]});
    } else {
      const scopes = await this.scope.matches(observation,baseIndex);
      for (const node of candidates) for (const scope of scopes) {
        if (await this.tab.scopeContains(observation,scope.node.index,node.index)) {
          matches.push({node,path:[...scope.path,scope.node.index],filters:[...scope.filters],...(scope.css ? {css:scope.css} : {})}); break;
        }
      }
    }
    }
    const apply = async (items: typeof matches, filters: TextFilter[]) => {
      if (!filters.length) return items;
      const accepted: typeof matches = [];
      for (const item of items) {
        const textFilters=filters.filter(filter=>filter.hasText !== undefined || filter.hasNotText !== undefined);
        if (textFilters.length && !matchesTextFilters(await this.tab.scopeText(observation,item.node.index),textFilters)) continue;
        const visibilityFilters=filters.filter(filter=>filter.visible !== undefined);
        if (visibilityFilters.length) {const visible=await this.tab.scopeVisible(observation,item.node.index);if (visibilityFilters.some(filter=>filter.visible!==visible)) continue;}
        let matched=true;
        const count=(locator:OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator)=>locator instanceof OpenBrowserUseCssLocator ? locator.countWithin(observation,item.node.index) : locator.matches(observation,item.node.index).then(matches=>matches.length);
        for(const filter of filters) {
          if(filter.has && !(await count(filter.has))) {matched=false;break;}
          if(filter.hasNot && await count(filter.hasNot)) {matched=false;break;}
        }
        if(matched) accepted.push({...item,filters:[...item.filters,{index:item.node.index,filters}]});
      }
      return accepted;
    };
    const before = await apply(matches,this.filtersBefore);
    return apply(this.position === undefined ? before : this.position === -1 ? before.slice(-1) : before.slice(this.position,this.position + 1),this.filtersAfter);
  }

  private identities(observation: Observation, matches: LocatorMatch[]): Array<{backendNodeId:number; frameId:string}> {
    return matches.map(match=>{
      const node=observation.nodes.find(item=>item.index===match.node.index);
      if(!node) throw new RetryablePreflightError("Locator target changed; observe again");
      return {backendNodeId:node.backendNodeId,frameId:node.frameId ?? ""};
    });
  }

  /** @internal */
  async detachedRoots(): Promise<{documentId:number; frames:FrameInfo[]; roots:RoleGuard["expected"]}> {
    const observation=await this.tab.freshFilterObservation();
    const matches=await this.matches(observation);
    if (!observation.frames) throw new Error("Frame information is unavailable");
    return {documentId:observation.documentId,frames:observation.frames,roots:this.identities(observation,matches)};
  }

  private guard(snapshotId:string, matches:LocatorMatch[]): RoleGuard {
    return {locator:this,expected:this.identities(this.tab.currentObservation(snapshotId),matches)};
  }

  /** @internal */
  async verifyMatches(original:Observation, expected:RoleGuard["expected"]): Promise<void> {
    const fresh=await this.tab.freshFilterObservation();
    if(fresh.documentId!==original.documentId || JSON.stringify(fresh.frames)!==JSON.stringify(original.frames)) throw new RetryablePreflightError("Page changed; observe again");
    const actual=this.identities(fresh,await this.matches(fresh));
    if(JSON.stringify(actual)!==JSON.stringify(expected)) throw new RetryablePreflightError("Locator matches changed; observe again");
  }

  private async find(): Promise<{state: InteractiveState; matches: LocatorMatch[]}> {
    const state = await this.tab.observe({includeFrames:true, ...(this.needsText() ? {includeText:true} : {})});
    if (state.unavailableFrames?.length) throw new Error("Some frames could not be observed; locator results are incomplete");
    const observation=this.tab.currentObservation(state.snapshotId);
    const matches=await this.matches(observation);
    this.tab.currentObservation(state.snapshotId);
    return {state,matches};
  }

  async count(): Promise<number> { return (await this.find()).matches.length; }
  async all(): Promise<OpenBrowserUseRoleLocator[]> { return Array.from({length:await this.count()},(_,index)=>this.nth(index)); }

  allTextContents(options: {timeoutMs?: number} = {}): Promise<string[]> { return this.readAllText("textContent",options); }
  allInnerTexts(options: {timeoutMs?: number} = {}): Promise<string[]> { return this.readAllText("innerText",options); }
  private async readAllText(mode: "textContent" | "innerText", options: {timeoutMs?: number}): Promise<string[]> {
    const timeoutMs = options.timeoutMs ?? 5_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid locator timeout");
    const deadline = performance.now() + timeoutMs;
    while (true) {
      try {
        const {state,matches} = await locatorReadBeforeDeadline(this.find(),timeoutMs,deadline,"Timed out reading locator texts");
        const values: string[] = [];
        let total = 0;
        for (const match of matches) {
          this.tab.bindLocatorScope(state.snapshotId,match.node.index,match.path,match.filters,this.framePath ? [...this.framePath] : undefined,match.css,this.guard(state.snapshotId,matches));
          const value = await locatorReadBeforeDeadline(this.tab.locatorRead(state.snapshotId,match.node.index,mode),timeoutMs,deadline,"Timed out reading locator texts");
          if (typeof value !== "string") throw new RetryablePreflightError("Target text is unavailable; observe again");
          total += value.length;
          if (total > 1_000_000) throw new Error("Locator values exceed the 1000000 character limit");
          values.push(value);
        }
        return values;
      } catch (error) {
        if (!(error instanceof RetryablePreflightError) || performance.now() >= deadline) throw error;
        await new Promise(resolve => setTimeout(resolve,Math.min(100,deadline-performance.now())));
      }
    }
  }

  async innerText(options: {timeoutMs?: number} = {}): Promise<string> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"innerText")) as string, options.timeoutMs,true); }
  async textContent(options: {timeoutMs?: number} = {}): Promise<string | null> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"textContent")) as string | null, options.timeoutMs,true); }
  async isEnabled(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"enabled")) as boolean,options.timeoutMs,true); }
  async isChecked(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"checked")) as boolean,options.timeoutMs,true); }
  async isEditable(options: {timeoutMs?:number} = {}): Promise<boolean> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"editable")) as boolean,options.timeoutMs,true); }
  boundingBox(options:{timeoutMs?:number} = {}):Promise<{x:number;y:number;width:number;height:number}|null> { return this.perform(async (node,id)=>{if(!await this.tab.locatorRead(id,node.index,"visible"))return null;const observation=this.tab.currentObservation(id),target=observation.nodes.find(item=>item.index===node.index),frame=observation.frames?.find(item=>item.id===(target?.frameId ?? observation.frames?.[0]?.id));if(!target || !frame || !observation.frames)throw new RetryablePreflightError("Target frame unavailable; observe again");const box=await this.tab.nodeBoundingBox(frame,observation.frames,target.backendNodeId);if(!box || !await this.tab.locatorRead(id,node.index,"visible"))throw new RetryablePreflightError("Target geometry changed; observe again");return box;},options.timeoutMs,true); }
  inputValue(options: {timeoutMs?: number} = {}): Promise<string> { return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"inputValue")) as string,options.timeoutMs,true); }
  async isVisible(options: {timeoutMs?:number} = {}): Promise<boolean> {
    const timeoutMs=options.timeoutMs ?? 5000;
    if (!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000) throw new Error("Invalid locator timeout");
    const deadline=performance.now()+timeoutMs, message="Timed out reading locator visibility";
    const {state,matches} = await locatorReadBeforeDeadline(this.find(),timeoutMs,deadline,message);
    if (!matches.length) return false;
    if (matches.length > 1) throw new Error(`Locator matched ${matches.length} elements; expected exactly one`);
    const match = matches[0];
    this.tab.bindLocatorScope(state.snapshotId,match.node.index,match.path,match.filters,this.framePath ? [...this.framePath] : undefined,match.css,this.guard(state.snapshotId,matches));
    return await locatorReadBeforeDeadline(this.tab.locatorRead(state.snapshotId,match.node.index,"visible"),timeoutMs,deadline,message) as boolean;
  }
  async isHidden(options: {timeoutMs?:number} = {}): Promise<boolean> { return !(await this.isVisible(options)); }
  async isDisabled(options: {timeoutMs?:number} = {}): Promise<boolean> { return !(await this.isEnabled(options)); }
  async waitFor(options: {state: "visible" | "hidden"; timeoutMs?: number}): Promise<void> {
    if (!options || !["visible","hidden"].includes(options.state)) throw new Error("Locator wait supports visible and hidden states");
    const timeoutMs = options.timeoutMs ?? 5_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid locator timeout");
    const deadline = performance.now() + timeoutMs;
    while (true) {
      try { if (await locatorReadBeforeDeadline(this.isVisible({timeoutMs:0}),timeoutMs,deadline,`Timed out waiting for locator to become ${options.state}`) === (options.state === "visible")) return; }
      catch (error) { if (!(error instanceof RetryablePreflightError)) throw error; }
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error(`Timed out waiting for locator to become ${options.state}`);
      await new Promise(resolve => setTimeout(resolve,Math.min(100,remaining)));
    }
  }
  async getAttribute(name: string, options: {timeoutMs?: number} = {}): Promise<string | null> {
    if (typeof name !== "string" || !name || name.length > 256) throw new Error("Invalid attribute name");
    return this.perform(async (node,id)=>(await this.tab.locatorRead(id,node.index,"attribute",name)) as string | null, options.timeoutMs,true);
  }

  private async perform<T>(action: (node: InteractiveNode, snapshotId: string) => Promise<T>, timeoutMs = 5_000, readOnly = false): Promise<T> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid locator timeout");
    const deadline = performance.now() + timeoutMs;
    let lastError: Error = new Error(`Locator matched 0 elements before timeout (${timeoutMs} ms)`);
    while (true) {
      try {
        const {state, matches} = await locatorReadBeforeDeadline(this.find(),timeoutMs,deadline,`Locator target unavailable before timeout (${timeoutMs} ms)`);
        if (matches.length > 1) throw new Error(`Locator matched ${matches.length} elements; expected exactly one`);
        if (matches.length === 1) {
          this.tab.bindLocatorScope(state.snapshotId,matches[0].node.index,matches[0].path,matches[0].filters,this.framePath ? [...this.framePath] : undefined,matches[0].css,this.guard(state.snapshotId,matches));
          const result=action(matches[0].node,state.snapshotId);
          return readOnly ? await locatorReadBeforeDeadline(result,timeoutMs,deadline,"Timed out reading locator") : await result;
        }
        lastError = new Error(`Locator matched 0 elements before timeout (${timeoutMs} ms)`);
      } catch (error) {
        if (!(error instanceof RetryablePreflightError)) throw error;
        lastError = error;
      }
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw lastError;
      await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
    }
  }

  async downloadMedia(options:{timeoutMs?:number} = {}):Promise<void> {
    const locator=this.first();
    await locator.perform(async (node,id)=>{
      const observation=this.tab.currentObservation(id), target=observation.nodes.find(item=>item.index===node.index);
      const frame=observation.frames?.find(item=>item.id===(target?.frameId ?? observation.frames?.[0]?.id));
      if (!target || !frame) throw new RetryablePreflightError("Download target is unavailable; observe again");
      await this.tab.triggerMediaDownload(target.backendNodeId,frame,()=>this.tab.locatorRead(id,node.index,"attribute","src"));
    },options.timeoutMs);
  }
  async click(options: LocatorClickOptions = {}): Promise<void> { const mouse=locatorClickOptions(options); await this.perform((node,id)=>this.tab.click(node.index,id,mouse), options.timeoutMs); }
  async dblclick(options: LocatorClickOptions = {}): Promise<void> { const mouse=locatorClickOptions(options); await this.perform((node,id)=>this.tab.dblclick(node.index,id,mouse), options.timeoutMs); }
  async hover(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.hover(node.index,id), options.timeoutMs); }
  async focus(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.focus(node.index,id),options.timeoutMs); }
  async press(key: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.press(node.index,id,key), options.timeoutMs); }
  clear(options: {timeoutMs?: number} = {}): Promise<void> { return this.fill("",options); }
  async fill(text: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.fill(node.index,id,text), options.timeoutMs); }
  async type(text: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.typeText(node.index,id,text), options.timeoutMs); }
  async check(options: LocatorCheckOptions = {}): Promise<void> { await this.setChecked(true,options); }
  async uncheck(options: LocatorCheckOptions = {}): Promise<void> { await this.setChecked(false,options); }
  async setChecked(checked: boolean, options: LocatorCheckOptions = {}): Promise<void> {
    validateCheckOptions(options);
    if (typeof checked !== "boolean") throw new Error("Checked state must be a boolean");
    await this.perform((node,id)=>this.tab.setChecked(node.index,id,checked,options.force), options.timeoutMs);
  }
  async selectOption(values: SelectOption | SelectOption[], options: {timeoutMs?: number} = {}): Promise<string[]> { return this.perform((node,id)=>this.tab.selectOption(node.index,id,values), options.timeoutMs); }
}

export class OpenBrowserUseCdp {
  readonly client: OpenBrowserUseClient;
  #frames = new Map<number, Map<string, { sessionId: string; frameId: string; parentFrameId: string; parentSessionId?: string }>>();
  #pending = new Map<number, Set<Promise<void>>>();
  #failure = new Map<number, Error>();
  #generations = new Map<number, number>();
  #dialogs = new Map<number, {info: OpenBrowserUseDialogInfo; generation:number; sessionId?:string; issued:boolean}>();
  #dialogEnabled = new Map<number,number>();
  #logs = new Map<number,LogCapture>();
  #eventPreparations = new Map<number,Set<Promise<void>>>();

  constructor(client: OpenBrowserUseClient) {
    this.client = client;
    client.onDisconnect(() => this.#logs.clear());
    client.onNotification(notification => {
      if (["onDebuggerDetach","onTabClosed"].includes(notification.method) && isObject(notification.params) && typeof notification.params.tabId === "number") {
        const tabId = notification.params.tabId;
        this.#frames.get(tabId)?.clear();
        this.#frames.delete(tabId);
        this.#generations.delete(tabId);
        this.#failure.delete(tabId);
        this.#dialogs.delete(tabId);
        this.#dialogEnabled.delete(tabId);
        this.#logs.delete(tabId);
        return;
      }
      if (notification.method !== "onCDPEvent" || !isObject(notification.params)) return;
      const { source, method, params } = notification.params;
      if (!isObject(source) || typeof source.tabId !== "number" || !isObject(params)) return;
      const capture = this.#logs.get(source.tabId);
      if (capture && capture.generation === this.client.connectionGeneration && (method === "Runtime.consoleAPICalled" || method === "Runtime.exceptionThrown" || method === "Log.entryAdded")) {
        const entry = browserLogEntry(method,params);
        if (entry) { capture.entries.push(entry); if (capture.entries.length > 500) capture.entries.shift(); }
      }
      if (method === "Page.javascriptDialogOpening" && typeof params.type === "string" && ["alert","confirm","prompt","beforeunload"].includes(params.type) && typeof params.message === "string" && typeof params.url === "string") {
        const info: OpenBrowserUseDialogInfo = {id:randomUUID(),type:params.type as OpenBrowserUseDialogInfo["type"],message:params.message,url:params.url,...(typeof params.defaultPrompt === "string" ? {defaultPrompt:params.defaultPrompt} : {})};
        this.#dialogs.set(source.tabId,{info,generation:this.client.connectionGeneration,...(typeof source.sessionId === "string" ? {sessionId:source.sessionId} : {}),issued:false});
      } else if (method === "Page.javascriptDialogClosed") {
        const dialog = this.#dialogs.get(source.tabId);
        if (dialog && (dialog.sessionId === source.sessionId || typeof source.sessionId !== "string")) this.#dialogs.delete(source.tabId);
      }

      const frames = this.#frames.get(source.tabId);
      if (!frames) return;
      if (method === "Target.detachedFromTarget" && typeof params.sessionId === "string") {
        const remove = (id: string): void => {
          frames.delete(id);
          capture?.sessions.delete(id);
          for (const child of frames.values()) if (child.parentSessionId === id) remove(child.sessionId);
        };
        remove(params.sessionId);
      }
      if (method !== "Target.attachedToTarget" || typeof params.sessionId !== "string" || !isObject(params.targetInfo)) return;
      const info = params.targetInfo;
      if (info.type !== "iframe" || typeof info.targetId !== "string" || typeof info.parentFrameId !== "string") return;
      if (typeof source.sessionId === "string" && !frames.has(source.sessionId)) return;
      const sessionId = params.sessionId;
      const tabId = source.tabId;
      const pending = this.#pending.get(tabId) ?? new Set<Promise<void>>();
      this.#pending.set(tabId, pending);
      frames.set(sessionId, {sessionId, frameId: info.targetId, parentFrameId: info.parentFrameId, ...(typeof source.sessionId === "string" ? {parentSessionId: source.sessionId} : {})});
      const task = this.call(tabId, "Target.setAutoAttach", {autoAttach: true, waitForDebuggerOnStart: false, flatten: true, filter: [{type: "iframe", exclude: false}, {exclude: true}]}, {sessionId})
        .then(async () => { if (capture && this.#logs.get(tabId) === capture) await this.enableLogSession(tabId,capture,sessionId); })
        .then(() => {}, error => { if (frames.has(sessionId)) this.#failure.set(tabId, error instanceof Error ? error : new Error(String(error))); })
        .finally(() => pending.delete(task));
      pending.add(task);
    });
  }

  private enableLogSession(tabId: number, capture: LogCapture, sessionId?: string): Promise<void> {
    const key = sessionId ?? "";
    const existing = capture.sessions.get(key);
    if (existing) return existing;
    const pending = this.call(tabId,"Runtime.enable",{}, {sessionId,expectedGeneration:capture.generation})
      .then(() => this.call(tabId,"Log.enable",{}, {sessionId,expectedGeneration:capture.generation})).then(() => {});
    capture.sessions.set(key,pending);
    void pending.catch(() => { if (capture.sessions.get(key) === pending) capture.sessions.delete(key); });
    return pending;
  }

  /** @internal */
  async watchLogs(tabId: number): Promise<void> {
    await this.ensureAttached(tabId);
    let capture = this.#logs.get(tabId);
    if (capture?.generation !== this.client.connectionGeneration) { capture = {generation:this.client.connectionGeneration,entries:[],sessions:new Map()}; this.#logs.set(tabId,capture); }
    if (!capture.ready) {
      const current = capture;
      const ready = (async () => {
        await this.enableFrameSessions(tabId);
        await this.enableLogSession(tabId,current);
        for (const frame of await this.frameSessions(tabId)) await this.enableLogSession(tabId,current,frame.sessionId);
      })();
      current.ready = ready;
      void ready.catch(() => { if (current.ready === ready) current.ready = undefined; });
    }
    await capture.ready;
    for (const frame of await this.frameSessions(tabId)) await this.enableLogSession(tabId,capture,frame.sessionId);
  }

  /** @internal */
  logs(tabId: number): OpenBrowserUseLogEntry[] {
    const capture = this.#logs.get(tabId);
    return capture?.generation === this.client.connectionGeneration ? capture.entries.map(entry=>({...entry})) : [];
  }

  /** @internal */
  async enableDialogs(tabId: number): Promise<void> {
    if (this.#dialogEnabled.get(tabId) === this.client.connectionGeneration) return;
    await this.call(tabId,"Page.enable");
    this.#dialogEnabled.set(tabId,this.client.connectionGeneration);
  }

  /** @internal */
  currentDialog(tabId: number): OpenBrowserUseDialogInfo | null {
    const dialog = this.#dialogs.get(tabId);
    if (!dialog || dialog.generation !== this.client.connectionGeneration) { this.#dialogs.delete(tabId); return null; }
    return {...dialog.info};
  }

  /** @internal */
  async resolveDialog(tabId: number, id: string, accept: boolean, promptText?: string): Promise<void> {
    if (promptText !== undefined && typeof promptText !== "string") throw new Error("Prompt text must be a string");
    const dialog = this.#dialogs.get(tabId);
    if (!dialog || dialog.info.id !== id || dialog.generation !== this.client.connectionGeneration) throw new Error("Dialog is no longer open");
    if (dialog.issued) throw new Error("Dialog decision has already been issued; observe again");
    if (promptText !== undefined && (!accept || dialog.info.type !== "prompt")) throw new Error("Prompt text requires an accepted prompt dialog");
    dialog.issued = true;
    await this.call(tabId,"Page.handleJavaScriptDialog",{accept,...(promptText !== undefined ? {promptText} : {})},{sessionId:dialog.sessionId,expectedGeneration:dialog.generation});
    if (this.#dialogs.get(tabId)?.info.id === id) this.#dialogs.delete(tabId);
  }

  async enableFrameSessions(tabId: number): Promise<boolean> {
    await this.ensureAttached(tabId);
    if (this.#generations.get(tabId) !== this.client.connectionGeneration) {
      this.#frames.get(tabId)?.clear();
      this.#frames.delete(tabId);
      this.#failure.delete(tabId);
      this.#generations.set(tabId, this.client.connectionGeneration);
    }
    const first = !this.#frames.has(tabId);
    if (first) this.#frames.set(tabId, new Map());
    try {
      if (first) await this.call(tabId, "Target.setAutoAttach", {autoAttach: false, waitForDebuggerOnStart: false, flatten: true});
      await this.call(tabId, "Target.setAutoAttach", {autoAttach: true, waitForDebuggerOnStart: false, flatten: true, filter: [{type: "iframe", exclude: false}, {exclude: true}]});
      await this.frameSessions(tabId);
      return true;
    } catch (error) {
      if (error instanceof Error && error.message.includes("IAB CDP command is outside page permissions")) {
        this.#frames.delete(tabId);
        return false;
      }
      throw error;
    }
  }

  async frameSessions(tabId: number): Promise<Array<{sessionId: string; frameId: string; parentFrameId: string}>> {
    const pending = this.#pending.get(tabId);
    while (pending?.size) await Promise.all([...pending]);
    const failure = this.#failure.get(tabId);
    if (failure) { this.#failure.delete(tabId); throw failure; }
    return [...(this.#frames.get(tabId)?.values() ?? [])];
  }

  /** @internal */
  blockUntilPrepared(tabId: number, preparation: Promise<unknown>): void {
    const barrier=preparation.then(()=>{});
    let pending=this.#eventPreparations.get(tabId);
    if (!pending) { pending=new Set();this.#eventPreparations.set(tabId,pending); }
    pending.add(barrier);
    const cleanup=()=>{pending!.delete(barrier);if (!pending!.size && this.#eventPreparations.get(tabId)===pending) this.#eventPreparations.delete(tabId);};
    void barrier.then(cleanup,cleanup);
  }

  async call(
    tabId: number,
    method: string,
    commandParams: BrowserUseRequestParams = {},
    options: { timeoutMs?: number; sessionId?: string; visualPoint?: {x: number; y: number}; expectedGeneration?: number; signal?: AbortSignal } = {}
  ): Promise<JsonValue> {
    const preparations=this.#eventPreparations.get(tabId);
    // Frame attachment and log setup must finish before a chooser can be registered.
    if (preparations?.size && !["Target.setAutoAttach","Runtime.enable","Log.enable"].includes(method)) await Promise.all([...preparations]);
    const requestTimeoutMs=options.timeoutMs === undefined ? this.client.timeoutMs : Math.max(this.client.timeoutMs,Math.ceil(options.timeoutMs)+2000);
    await this.ensureAttached(tabId,requestTimeoutMs);
    if(options.signal?.aborted)throw new Error("Command cancelled before dispatch");
    if (options.expectedGeneration !== undefined && options.expectedGeneration !== this.client.connectionGeneration) throw new Error("Connection changed; observe again");
    const result = await this.client.request("executeCdp", {
      target: { tabId, ...(options.sessionId ? {sessionId: options.sessionId} : {}) },
      method,
      commandParams,
      ...(options.visualPoint ? {visualPoint: options.visualPoint} : {}),
      ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs })
    },options.expectedGeneration,requestTimeoutMs);
    if (method === "Page.disable" && !options.sessionId) this.#dialogEnabled.delete(tabId);
    if (method === "Runtime.disable" || method === "Log.disable") {
      const capture = this.#logs.get(tabId);
      capture?.sessions.delete(options.sessionId ?? "");
      if (capture) capture.ready = undefined;
    }
    return result;
  }

  async evaluate(tabId: number, expression: string, options: { awaitPromise?: boolean } = {}): Promise<JsonValue> {
    const result = await this.call(tabId, "Runtime.evaluate", {
      expression,
      returnByValue: true,
      ...(options.awaitPromise === undefined ? {} : { awaitPromise: options.awaitPromise })
    });
    if (isObject(result) && isObject(result.exceptionDetails)) {
      throw new Error(String(result.exceptionDetails.text ?? "Open Browser Use evaluation failed"));
    }
    if (!isObject(result) || !isObject(result.result)) throw new Error("Invalid browser evaluation response");
    const remote=result.result;
    if (remote.unserializableValue !== undefined || (!("value" in remote) && remote.type !== "undefined")) throw new Error("Evaluation result is not JSON serializable");
    return remote.type === "undefined" ? null : remote.value as JsonValue;
  }

  async navigate(tabId: number, url: string, options: OpenBrowserUseGotoOptions = {}): Promise<JsonValue> {
    if (!url) {
      throw new Error("goto requires a URL");
    }
    const waitUntil = options.waitUntil ?? "load";
    assertSupportedLoadState(waitUntil);
    const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    if(!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000)throw new Error("Invalid navigation timeout");
    const deadline=performance.now()+timeoutMs,initialGeneration=this.client.isConnected ? this.client.connectionGeneration : undefined,controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>|undefined,started=false;
    const timeout=()=>new Error(started ? `Timed out waiting for ${waitUntil} in tab ${tabId}; navigation outcome unknown` : "Navigation preparation timed out before action");
    try {
      const work=(async()=>{
        await this.call(tabId,"Page.enable",{},{timeoutMs:Math.max(1,deadline-performance.now()),signal:controller.signal});
        if(controller.signal.aborted || performance.now()>=deadline)throw timeout();
        if(initialGeneration!==undefined && initialGeneration!==this.client.connectionGeneration)throw new Error("Connection changed during navigation preparation before action");
        const generation=this.client.connectionGeneration,remaining=deadline-performance.now();
        if(remaining<=0)throw timeout();
        const wait=this.waitForLoadEvent(tabId,waitUntil,remaining,controller.signal).catch(error=>{
          if(error instanceof Error && error.message===`Timed out waiting for ${waitUntil} in tab ${tabId}`)throw timeout();
          throw error;
        });
        let waitError:unknown;void wait.catch(error=>{waitError=error;});
        started=true;
        const result=await this.call(tabId,"Page.navigate",{url},{timeoutMs:remaining,expectedGeneration:generation,signal:controller.signal});
        if(controller.signal.aborted)throw timeout();
        if(isObject(result) && typeof result.errorText==="string" && result.errorText)throw new Error(`Browser failed to navigate tab ${tabId}: ${result.errorText}`);
        if(isObject(result) && typeof result.loaderId!=="string") {
          const state=await this.readDocumentState(tabId);
          if(controller.signal.aborted)throw timeout();
          if(state?.href && documentStateMatches(state,waitUntil)) {
            let target:string | undefined;
            try { target=new URL(url,state.href).href; } catch { /* Page.navigate validates the URL. */ }
            if(target===state.href) {if(waitError!==undefined)throw waitError;return result;}
          }
        }
        await wait;
        return result;
      })();
      const result=await Promise.race([work,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(timeout()),Math.max(0,deadline-performance.now()));})]);
      if(performance.now()>=deadline)throw timeout();
      return result;
    } finally {if(timer)clearTimeout(timer);controller.abort();}
  }

  async waitForLoadState(tabId: number, options: OpenBrowserUseWaitForLoadStateOptions = {}): Promise<void> {
    const state = options.state ?? "load",timeoutMs=options.timeoutMs ?? defaultNavigationTimeoutMs;
    assertSupportedLoadState(state);
    if(!Number.isFinite(timeoutMs) || timeoutMs<0 || timeoutMs>120_000)throw new Error("Invalid load state timeout");
    const timedOut=()=>new Error(`Timed out waiting for ${state} in tab ${tabId}`);
    if(timeoutMs===0) {
      if(!documentStateMatches(await this.readDocumentState(tabId),state))throw timedOut();
      return;
    }
    const deadline=performance.now()+timeoutMs,generation=this.client.isConnected ? this.client.connectionGeneration : undefined,controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>|undefined;
    try {
      const work=(async()=>{
        await this.call(tabId,"Page.enable");
        if(controller.signal.aborted || performance.now()>=deadline)throw timedOut();
        if(generation!==undefined && generation!==this.client.connectionGeneration)throw new Error("Connection changed while preparing load state wait");
        const wait=this.waitForLoadEvent(tabId,state,deadline-performance.now(),controller.signal);
        const ready=await Promise.race([wait.then(()=>true),this.readDocumentState(tabId).then(value=>documentStateMatches(value,state))]);
        if(!ready)await wait;
      })();
      await Promise.race([work,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(timedOut()),Math.max(0,deadline-performance.now()));})]);
      if(performance.now()>=deadline)throw timedOut();
    } finally {if(timer)clearTimeout(timer);controller.abort();}
  }

  async readDocumentStateStrict(tabId:number):Promise<{href?:string;readyState?:string}> {
    const tree=await this.call(tabId,"Page.getFrameTree");
    const frame=isObject(tree) && isObject(tree.frameTree) && isObject(tree.frameTree.frame) ? tree.frameTree.frame : undefined;
    if(!frame || typeof frame.id!=="string")throw new Error("Main frame is unavailable");
    const generation=this.client.connectionGeneration;
    const world=await this.call(tabId,"Page.createIsolatedWorld",{frameId:frame.id,worldName:"open-browser-use-selector"},{expectedGeneration:generation});
    if(!isObject(world) || typeof world.executionContextId!=="number")throw new Error("Document state context is unavailable");
    const response=await this.call(tabId,"Runtime.evaluate",{contextId:world.executionContextId,expression:"({ href: window.location.href, readyState: document.readyState })",returnByValue:true},{expectedGeneration:generation});
    const value=isObject(response) && isObject(response.result) ? response.result.value : undefined;
    if(!isObject(value))throw new Error("Document state is unavailable");
    return {href:stringValue(value.href),readyState:stringValue(value.readyState)};
  }

  async readDocumentState(tabId: number): Promise<{ href?: string; readyState?: string } | undefined> {
    try { return await this.readDocumentStateStrict(tabId); } catch { return undefined; }
  }

  waitForEvent(
    tabId: number,
    predicate: (notification: OpenBrowserUseNotification) => boolean,
    options: { timeoutMs?: number; timeoutMessage?: string; signal?: AbortSignal } = {}
  ): Promise<OpenBrowserUseNotification> {
    if (options.signal?.aborted) return Promise.reject(new Error("Event wait cancelled"));
    const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    return new Promise((resolve, reject) => {
      let settled = false;
      let removeHandler: (() => void) | null = null;
      let removeDisconnect: (() => void) | null = null;
      let timer: NodeJS.Timeout;
      const finish = (): boolean => {
        if (settled) {
          return false;
        }
        settled = true;
        clearTimeout(timer);
        removeHandler?.();
        removeDisconnect?.();
        options.signal?.removeEventListener("abort", onAbort);
        return true;
      };
      const onAbort = () => { if (finish()) reject(new Error("Event wait cancelled")); };
      timer = setTimeout(() => {
        if (finish()) {
          reject(new Error(options.timeoutMessage ?? `Timed out waiting for tab ${tabId} event`));
        }
      }, timeoutMs);
      options.signal?.addEventListener("abort", onAbort, {once:true});
      removeDisconnect = this.client.onDisconnect(error => { if (finish()) reject(error); });
      removeHandler = this.client.onNotification((notification) => {
        try {
          if (["onTabClosed", "onDebuggerDetach"].includes(notification.method) && isObject(notification.params) && notification.params.tabId === tabId) {
            throw new Error(`Tab ${tabId} ${notification.method === "onTabClosed" ? "closed" : "debugger detached"}`);
          }
          if (predicate(notification)) {
            if (finish()) {
              resolve(notification);
            }
          }
        } catch (error) {
          if (finish()) {
            reject(error instanceof Error ? error : new Error(String(error)));
          }
        }
      });
    });
  }

  waitForLoadEvent(tabId: number, state: OpenBrowserUseLoadState, timeoutMs: number, signal?: AbortSignal): Promise<void> {
    return this.waitForEvent(
      tabId,
      (notification) => {
        const event = cdpEventForTab(notification, tabId);
        if (!event) {
          return false;
        }
        if (event.method === "Page.navigationBlocked") {
          throw new Error(`Navigation was blocked in tab ${tabId}`);
        }
        return state === "domcontentloaded"
          ? event.method === "Page.domContentEventFired"
          : event.method === "Page.loadEventFired";
      },
      {
        timeoutMs,
        signal,
        timeoutMessage: `Timed out waiting for ${state} in tab ${tabId}`
      }
    ).then(() => undefined);
  }

  async ensureAttached(tabId: number, requestTimeoutMs?:number): Promise<void> {
    await this.client.attach(tabId,requestTimeoutMs);
  }
}

export function encodeFrame(value: JsonValue | Record<string, unknown>): Buffer {
  const payload = Buffer.from(JSON.stringify(value), "utf8");
  const frame = Buffer.alloc(headerBytes + payload.length);
  if (endianness() === "LE") {
    frame.writeUInt32LE(payload.length, 0);
  } else {
    frame.writeUInt32BE(payload.length, 0);
  }
  payload.copy(frame, headerBytes);
  return frame;
}

function isObject(value: JsonValue | unknown): value is { [key: string]: JsonValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function frameAncestry(frame: FrameInfo, frames: FrameInfo[]): FrameInfo[] {
  const chain: FrameInfo[] = [];
  let current: FrameInfo | undefined = frame;
  while (current?.parentId) {
    chain.push(current);
    current = frames.find(item => item.id === current?.parentId);
    if (!current || chain.length > frames.length) throw new Error("Invalid frame ancestry");
  }
  return chain;
}

function interactiveNodes(tree: JsonValue, offset = 0, includeText = false): Array<InteractiveNode & { backendNodeId: number; stateKey: string; axOrder:number }> {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) throw new Error("Invalid accessibility tree");
  const roles = new Set(["button", "link", "checkbox", "radio", "switch", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "combobox", "listbox", "textbox", "searchbox", "slider", "spinbutton", "Date", "DateTime", "InputTime", ...(includeText ? supplementalRoles : [])]);
  const nodes: Array<InteractiveNode & { backendNodeId: number; stateKey: string; axOrder:number }> = [];
  const byId = new Map(tree.nodes.filter(isObject).filter(node => typeof node.nodeId === "string").map(node => [node.nodeId, node]));
  const temporalAncestor = (node: {[key:string]:JsonValue}): boolean => {
    const seen = new Set<string>();
    let parent = node.parentId;
    while (typeof parent === "string" && !seen.has(parent)) {
      seen.add(parent);
      const ancestor = byId.get(parent);
      if (!ancestor) break;
      if (isObject(ancestor.role) && ["Date", "DateTime", "InputTime"].includes(String(ancestor.role.value))) return true;
      parent = ancestor.parentId;
    }
    return false;
  };
  for (const [axOrder,node] of tree.nodes.entries()) {
    if (!isObject(node) || node.ignored === true || typeof node.backendDOMNodeId !== "number" || !isObject(node.role)) continue;
    const role = node.role.value;
    if (typeof role !== "string" || !roles.has(role) || temporalAncestor(node)) continue;
    const name = isObject(node.name) && typeof node.name.value === "string" ? node.name.value : "";
    const state = (name: string): boolean | "mixed" | undefined => {
      const property = Array.isArray(node.properties) ? node.properties.find(item => isObject(item) && item.name === name) : undefined;
      const value = isObject(property) && isObject(property.value) ? property.value.value : undefined;
      return value === true || value === "true" ? true : value === false || value === "false" ? false : value === "mixed" ? "mixed" : undefined;
    };
    const checked = state("checked"), pressed = state("pressed"), disabled = state("disabled") === true;
    const selectedValue = state("selected"), expandedValue = state("expanded");
    const selected = typeof selectedValue === "boolean" ? selectedValue : undefined;
    const expanded = typeof expandedValue === "boolean" ? expandedValue : undefined;
    const levelProperty = Array.isArray(node.properties) ? node.properties.find(item => isObject(item) && item.name === "level") : undefined;
    const rawLevel = isObject(levelProperty) && isObject(levelProperty.value) ? levelProperty.value.value : undefined;
    const level = typeof rawLevel === "number" && Number.isSafeInteger(rawLevel) && rawLevel > 0 ? rawLevel : undefined;
    const sources = isObject(node.name) && Array.isArray(node.name.sources) ? node.name.sources : [];
    const placeholderSource = ["placeholder", "aria-placeholder"].map(attribute => sources.find(source => isObject(source) && source.attribute === attribute && isObject(source.attributeValue) && typeof source.attributeValue.value === "string")).find(Boolean);
    const rawPlaceholder = isObject(placeholderSource) && isObject(placeholderSource.attributeValue) ? placeholderSource.attributeValue.value : undefined;
    const placeholder = typeof rawPlaceholder === "string" ? rawPlaceholder.slice(0,512) : undefined;
    const placeholderTruncated = typeof rawPlaceholder === "string" && rawPlaceholder.length > 512;
    const altSource = sources.find(source => isObject(source) && source.attribute === "alt" && isObject(source.attributeValue) && typeof source.attributeValue.value === "string");
    const rawAlt = isObject(altSource) && isObject(altSource.attributeValue) ? altSource.attributeValue.value : undefined;
    const altText = typeof rawAlt === "string" ? rawAlt.slice(0,512) : undefined;
    const altTextTruncated = typeof rawAlt === "string" && rawAlt.length > 512;
    const states = axProperties(node);
    if (placeholder !== undefined) states.push(`placeholder=${JSON.stringify(placeholder)}${placeholderTruncated ? createHash("sha256").update(rawPlaceholder as string).digest("hex") : ""}`);
    if (altText !== undefined) states.push(`alt=${JSON.stringify(altText)}${altTextTruncated ? createHash("sha256").update(rawAlt as string).digest("hex") : ""}`);
    nodes.push({ index: offset + nodes.length + 1, role, name, axOrder, backendNodeId: node.backendDOMNodeId, stateKey: JSON.stringify(states), ...(level !== undefined ? {level} : {}), ...(checked !== undefined ? {checked} : {}), ...(disabled ? {disabled:true} : {}), ...(pressed !== undefined ? {pressed} : {}), ...(selected !== undefined ? {selected} : {}), ...(expanded !== undefined ? {expanded} : {}), ...(placeholder !== undefined ? {placeholder} : {}), ...(placeholderTruncated ? {placeholderTruncated:true} : {}), ...(altText !== undefined ? {altText} : {}), ...(altTextTruncated ? {altTextTruncated:true} : {}) });
  }
  return nodes;
}

function axProperties(node: { [key: string]: JsonValue }): string[] {
  return Array.isArray(node.properties) ? node.properties.flatMap(property => {
    if (!isObject(property) || typeof property.name !== "string" || !["checked", "selected", "expanded", "disabled", "pressed", "required", "readonly", "level"].includes(property.name) || !isObject(property.value)) return [];
    const value = property.value.value;
    return typeof value === "boolean" || typeof value === "string" || (property.name === "level" && typeof value === "number" && Number.isSafeInteger(value) && value > 0) ? [`${property.name}=${JSON.stringify(value)}`] : [];
  }).sort() : [];
}

type RenderedFrame = {url:string; text:string; truncated:boolean};

function appendUnplacedFrames(base: {text:string; truncated:boolean}, frames: RenderedFrame[]): {text:string; truncated:boolean} {
  const extra = frames.map(frame=>`[frame placement unavailable]\nframe ${JSON.stringify(frame.url)}${frame.text ? `\n${frame.text}` : ""}`).join("\n");
  const text = [base.text,extra].filter(Boolean).join("\n");
  return {text:text.slice(0,30_000),truncated:base.truncated || frames.some(frame=>frame.truncated) || text.length > 30_000};
}

function renderAXState(tree: JsonValue, targets: Array<InteractiveNode & { backendNodeId: number }>, embedded = new Map<number,RenderedFrame[]>()): { text: string; truncated: boolean } {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) throw new Error("Invalid accessibility tree");
  const indexed = new Map(targets.map(node => [node.backendNodeId, node]));
  const nodes = tree.nodes.filter(isObject);
  const byId = new Map(nodes.flatMap((node,index) => typeof node.nodeId === "string" ? [[node.nodeId,index] as const] : []));
  const children = new Map<number,number[]>();
  const roots: number[] = [];
  for (let i=0; i<nodes.length; i++) {
    const parent = typeof nodes[i].parentId === "string" ? byId.get(nodes[i].parentId as string) : undefined;
    if (parent === undefined || parent === i) roots.push(i);
    else { const list = children.get(parent) ?? []; list.push(i); children.set(parent,list); }
  }
  const lines: string[] = [];
  const visited = new Set<number>();
  const remaining = new Map(embedded);
  let length = 0, truncated = false;
  const append = (line:string): boolean => {
    if (length + line.length + 1 > 30_000) {
      const available = 30_000 - length - 1;
      if (available > 1) lines.push(`${line.slice(0,available-1)}…`);
      return false;
    }
    lines.push(line); length += line.length + 1; return true;
  };
  const pending: Array<{index:number; depth:number}> = roots.reverse().map(index=>({index,depth:0}));
  let next = 0;
  while (pending.length || next < nodes.length) {
    if (!pending.length) { while (next < nodes.length && visited.has(next)) next++; if (next < nodes.length) pending.push({index:next,depth:0}); }
    const current = pending.pop();
    if (!current || visited.has(current.index)) continue;
    visited.add(current.index);
    const node = nodes[current.index];
    const target = typeof node.backendDOMNodeId === "number" ? indexed.get(node.backendDOMNodeId) : undefined;
    const show = node.ignored !== true && isObject(node.role) && typeof node.role.value === "string" && ((isObject(node.name) && typeof node.name.value === "string" && !!node.name.value) || target !== undefined);
    const descendants = children.get(current.index) ?? [];
    for (let i=descendants.length-1; i>=0; i--) pending.push({index:descendants[i],depth:current.depth+(show ? 1 : 0)});
    if (show && isObject(node.role)) {
      const role = node.role.value;
      const name = isObject(node.name) && typeof node.name.value === "string" ? node.name.value : "";
      const index = target?.index;
      const properties = axProperties(node);
      if (target?.altText !== undefined) properties.push(`alt=${JSON.stringify(target.altText)}${target.altTextTruncated ? "…" : ""}`);
      if (target?.placeholder !== undefined) properties.push(`placeholder=${JSON.stringify(target.placeholder)}${target.placeholderTruncated ? "…" : ""}`);
      if (target?.valueRedacted) properties.push("value=[redacted]");
      else if (target?.valueUnavailable) properties.push("value=[unavailable]");
      else if (target?.value !== undefined) properties.push(`value=${JSON.stringify(target.value)}${target.valueTruncated ? "…" : ""}`);
      else if (target?.valueTruncated) properties.push("value=[truncated]");
      const line = `${"  ".repeat(Math.min(current.depth,80))}${index === undefined ? "" : `[${index}] `}${role}${name ? ` ${JSON.stringify(name)}` : ""}${properties.length ? ` ${properties.join(" ")}` : ""}`;
      if (!append(line)) return {text:lines.join("\n"),truncated:true};
    }
    const owner = typeof node.backendDOMNodeId === "number" ? node.backendDOMNodeId : undefined;
    const frames = owner === undefined ? undefined : remaining.get(owner);
    if (owner !== undefined && frames) remaining.delete(owner);
    for (const frame of frames ?? []) {
      const indent = "  ".repeat(Math.min(current.depth+(show ? 1 : 0),80));
      if (!append(`${indent}frame ${JSON.stringify(frame.url)}`)) return {text:lines.join("\n"),truncated:true};
      for (const line of frame.text ? frame.text.split("\n") : []) if (!append(`${indent}  ${line}`)) return {text:lines.join("\n"),truncated:true};
      truncated ||= frame.truncated;
    }
  }
  const rendered = {text:lines.join("\n"),truncated};
  return remaining.size ? appendUnplacedFrames(rendered,[...remaining.values()].flat()) : rendered;
}

function diffAXState(before: string, after: string): { text: string; truncated: boolean } {
  const oldLines = before ? before.split("\n") : [];
  const newLines = after ? after.split("\n") : [];
  let start = 0;
  while (start < oldLines.length && start < newLines.length && oldLines[start] === newLines[start]) start++;
  let oldEnd = oldLines.length, newEnd = newLines.length;
  while (oldEnd > start && newEnd > start && oldLines[oldEnd - 1] === newLines[newEnd - 1]) { oldEnd--; newEnd--; }
  const text = [...oldLines.slice(start, oldEnd).map(line => `- ${line}`), ...newLines.slice(start, newEnd).map(line => `+ ${line}`)].join("\n");
  return text.length > 30_000 ? { text: `${text.slice(0, 29_999)}…`, truncated: true } : { text, truncated: false };
}

function tabIdFromValue(value: JsonValue, label: string): number {
  if (!isObject(value)) {
    throw new Error(`${label} did not include a tab object`);
  }
  const id = value.id;
  if (typeof id === "number" && Number.isInteger(id) && id > 0) {
    return id;
  }
  if (typeof id === "string") {
    const parsed = Number(id);
    if (Number.isInteger(parsed) && parsed > 0) {
      return parsed;
    }
  }
  throw new Error(`${label} did not include a numeric tab id`);
}

function assertSupportedLoadState(state: string): asserts state is OpenBrowserUseLoadState {
  if(state === "networkidle")throw new Error('The networkidle load state is not available; wait for a specific page condition instead');
  if (state !== "domcontentloaded" && state !== "load") {
    throw new Error(`Unsupported load state "${state}". Use "domcontentloaded" or "load".`);
  }
}

function documentStateMatches(documentState: { readyState?: string } | undefined, state: OpenBrowserUseLoadState): boolean {
  if (documentState?.readyState === "complete") {
    return true;
  }
  return state === "domcontentloaded" && documentState?.readyState === "interactive";
}

function cdpEventForTab(
  notification: OpenBrowserUseNotification,
  tabId: number
): { method?: string; params?: JsonValue } | null {
  if (notification.method !== "onCDPEvent" || !isObject(notification.params)) {
    return null;
  }
  const source = notification.params.source;
  if (!isObject(source) || source.tabId !== tabId || typeof source.sessionId === "string") {
    return null;
  }
  return {
    method: stringValue(notification.params.method), params: notification.params.params
  };
}

function stringValue(value: JsonValue | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}
