import { Socket, createConnection } from "node:net";
import { endianness } from "node:os";
import { createHash, randomUUID } from "node:crypto";

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

export type OpenBrowserUseGotoOptions = {
  waitUntil?: OpenBrowserUseLoadState;
  timeoutMs?: number;
};

export type OpenBrowserUseWaitForLoadStateOptions = {
  state?: OpenBrowserUseLoadState;
  timeoutMs?: number;
};

export type OpenBrowserUseBrowserOptions = OpenBrowserUseClientOptions | { client: OpenBrowserUseClient };

export type InteractiveNode = { index: number; role: string; name: string; frameId?: string; checked?: boolean | "mixed"; disabled?: boolean; pressed?: boolean | "mixed"; selected?: boolean; expanded?: boolean; placeholder?: string; placeholderTruncated?: boolean; altText?: string; altTextTruncated?: boolean; value?: string | number; valueRedacted?: boolean; valueUnavailable?: boolean; valueTruncated?: boolean };
export type SelectOption = string | {value?: string; label?: string};
export type OpenBrowserUseDialogInfo = { id: string; type: "alert" | "confirm" | "prompt" | "beforeunload"; message: string; url: string; defaultPrompt?: string };
export type RoleLocatorOptions = {name?: string; exact?: boolean; checked?: boolean; disabled?: boolean; pressed?: boolean; selected?: boolean; expanded?: boolean};
export type InteractiveState = { snapshotId: string; nodes: InteractiveNode[]; text: string; textMode: "full" | "diff"; truncated: boolean; frameCoverage?: "same-process" | "cross-process"; unavailableFrames?: string[]; valuesTruncated?: boolean };
type FrameInfo = { id: string; parentId?: string; loaderId: string; url: string; sessionId?: string };
type ObservedNode = InteractiveNode & { backendNodeId: number; stateKey: string; frameChain?: FrameInfo[] };
const supplementalRoles = ["heading", "StaticText", "image", "dialog", "alertdialog", "group", "list", "listitem", "table", "row", "cell", "columnheader", "rowheader", "grid", "gridcell", "tree", "treeitem", "navigation", "main", "region", "form", "article"];
type TextFilter = { hasText?: string; hasNotText?: string };
type FilterGuard = { index: number; filters: TextFilter[] };
type UnindexedText = { backendNodeId?: number; frameId?: string; frameChain?: FrameInfo[] };
type Observation = { id: string; documentId: number; nodes: ObservedNode[]; unindexedText: UnindexedText[]; guards: Map<number,{scopes:number[]; filters:FilterGuard[]}> };
class RetryablePreflightError extends Error {}
function unindexedTextAncestors(tree: JsonValue): Array<number | undefined> {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) return [];
  const nodes = tree.nodes.filter(isObject);
  const byId = new Map(nodes.filter(node => typeof node.nodeId === "string").map(node => [node.nodeId,node]));
  return nodes.filter(node => node.ignored !== true && isObject(node.role) && node.role.value === "StaticText" &&
    isObject(node.name) && typeof node.name.value === "string" && node.name.value.length > 0 && typeof node.backendDOMNodeId !== "number").map(node => {
      const seen = new Set<string>();
      let parent = node.parentId;
      while (typeof parent === "string" && !seen.has(parent)) {
        seen.add(parent);
        const ancestor = byId.get(parent);
        if (!ancestor) break;
        if (typeof ancestor.backendDOMNodeId === "number") return ancestor.backendDOMNodeId;
        parent = ancestor.parentId;
      }
      return undefined;
    });
}
function matchesTextFilters(text: string, filters: TextFilter[]): boolean {
  const normalized = text.toLowerCase();
  const needle = (value: string) => value.replace(/\s+/g," ").trim().toLowerCase();
  return filters.every(filter => (filter.hasText === undefined || normalized.includes(needle(filter.hasText))) && (filter.hasNotText === undefined || !normalized.includes(needle(filter.hasNotText))));
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
  #generation = 0;

  get connectionGeneration(): number { return this.#generation; }

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
      this.#rejectAll(new Error("Open Browser Use socket closed"));
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
    this.#rejectAll(new Error("Open Browser Use socket closed"));
  }

  onNotification(handler: NotificationHandler): () => void {
    this.#notificationHandlers.add(handler);
    return () => {
      this.#notificationHandlers.delete(handler);
    };
  }

  async request(method: string, params: BrowserUseRequestParams = {}, expectedGeneration?: number): Promise<JsonValue> {
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
      }, this.timeoutMs);
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

  attach(tabId: number): Promise<JsonValue> {
    return this.request("attach", { tabId });
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
    });
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

export class OpenBrowserUseBrowser {
  readonly client: OpenBrowserUseClient;
  readonly cdp: OpenBrowserUseCdp;

  constructor(options: OpenBrowserUseBrowserOptions) {
    this.client = "client" in options ? options.client : new OpenBrowserUseClient(options);
    this.cdp = new OpenBrowserUseCdp(this.client);
  }

  async connect(): Promise<this> {
    await this.client.connect();
    return this;
  }

  close(): void {
    this.client.close();
  }

  async newTab(options: OpenBrowserUseGotoOptions & { url?: string } = {}): Promise<OpenBrowserUseTab> {
    const created = await this.client.createTab();
    const tabId = tabIdFromValue(created, "createTab response");
    const tab = this.tab(tabId);
    if (options.url) {
      await tab.goto(options.url, options);
    }
    return tab;
  }

  tab(tabId: number): OpenBrowserUseTab {
    return new OpenBrowserUseTab(this, tabId);
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

export class OpenBrowserUseDialog {
  constructor(private cdp: OpenBrowserUseCdp, private tabId: number, readonly info: OpenBrowserUseDialogInfo) {}
  accept(promptText?: string): Promise<void> { return this.cdp.resolveDialog(this.tabId,this.info.id,true,promptText); }
  dismiss(): Promise<void> { return this.cdp.resolveDialog(this.tabId,this.info.id,false); }
}

export class OpenBrowserUseTab {
  readonly browser: OpenBrowserUseBrowser;
  readonly id: number;
  readonly playwright: OpenBrowserUseTabPlaywright;
  #observation?: Observation;
  #lastText?: { documentId: number; includeFrames: boolean; includeValues: boolean; includeText: boolean; text: string; truncated: boolean };

  constructor(browser: OpenBrowserUseBrowser, id: number) {
    this.browser = browser;
    this.id = id;
    this.playwright = new OpenBrowserUseTabPlaywright(this);
  }

  goto(url: string, options: OpenBrowserUseGotoOptions = {}): Promise<JsonValue> {
    return this.browser.cdp.navigate(this.id, url, options);
  }

  waitForLoadState(options: OpenBrowserUseWaitForLoadStateOptions = {}): Promise<void> {
    return this.browser.cdp.waitForLoadState(this.id, options);
  }

  domSnapshot(): Promise<string> {
    return this.browser.cdp.evaluate(this.id, "document.body?.innerText ?? ''").then((value) => String(value ?? ""));
  }

  getAXState(): Promise<JsonValue> {
    return this.browser.cdp.call(this.id, "Accessibility.getFullAXTree");
  }

  async observe(options: { diff?: boolean; includeFrames?: boolean; includeValues?: boolean; includeText?: boolean } = {}): Promise<InteractiveState> {
    this.#observation = undefined;
    const documentId = await this.documentId();
    const tree = await this.getAXState();
    const nodes: ObservedNode[] = interactiveNodes(tree, 0, options.includeText);
    const unindexedText: UnindexedText[] = options.includeText ? unindexedTextAncestors(tree).map(backendNodeId=>({backendNodeId})) : [];
    const valueBudget = { remaining: 8_000, truncated: false };
    if (options.includeValues) await this.readAXValues(tree, nodes, valueBudget);
    const full = renderAXState(tree, nodes);
    const unavailableFrames: string[] = [];
    let crossProcess = false;
    if (options.includeFrames) {
      crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
      const frames = await this.frameTree();
      for (const frame of frames.slice(1)) {
        try {
          const childTree = await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: frame.id }, { sessionId: frame.sessionId });
          if (options.includeText) unindexedText.push(...unindexedTextAncestors(childTree).map(backendNodeId=>({backendNodeId,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
          const childNodes = interactiveNodes(childTree, nodes.length, options.includeText).map(node => ({ ...node, frameId: frame.id, frameChain: frameAncestry(frame, frames) }));
          if (options.includeValues) await this.readAXValues(childTree, childNodes, valueBudget, frame.sessionId);
          nodes.push(...childNodes);
          const rendered = renderAXState(childTree, childNodes);
          const text = `${full.text}${full.text ? "\n" : ""}frame ${JSON.stringify(frame.url)}\n${rendered.text}`;
          full.text = text.slice(0, 30_000);
          full.truncated ||= rendered.truncated || text.length > 30_000;
        } catch { unavailableFrames.push(frame.id); }
      }
      const current = await this.frameTree();
      if (JSON.stringify(current) !== JSON.stringify(frames)) throw new RetryablePreflightError("Frame tree changed during observation; observe again");
    }
    if (documentId !== await this.documentId()) throw new RetryablePreflightError("Page changed during observation; observe again");
    const id = randomUUID();
    this.#observation = { id, documentId, nodes, unindexedText, guards:new Map() };
    const previous = this.#lastText;
    const useDiff = options.diff === true && previous?.documentId === documentId && previous.includeFrames === !!options.includeFrames && previous.includeValues === !!options.includeValues && previous.includeText === !!options.includeText && !previous.truncated && !full.truncated && !valueBudget.truncated && !unavailableFrames.length;
    const output = useDiff ? diffAXState(previous.text, full.text) : full;
    this.#lastText = (output.truncated && useDiff) || unavailableFrames.length || valueBudget.truncated ? undefined : { documentId, includeFrames: !!options.includeFrames, includeValues: !!options.includeValues, includeText: !!options.includeText, ...full };
    return { snapshotId: id, nodes: nodes.map(({ index, role, name, frameId, checked, disabled, pressed, selected, expanded, placeholder, placeholderTruncated, altText, altTextTruncated, value, valueRedacted, valueUnavailable, valueTruncated }) => ({ index, role, name, ...(frameId ? {frameId} : {}), ...(checked !== undefined ? {checked} : {}), ...(disabled ? {disabled:true} : {}), ...(pressed !== undefined ? {pressed} : {}), ...(selected !== undefined ? {selected} : {}), ...(expanded !== undefined ? {expanded} : {}), ...(placeholder !== undefined ? {placeholder} : {}), ...(placeholderTruncated ? {placeholderTruncated} : {}), ...(altText !== undefined ? {altText} : {}), ...(altTextTruncated ? {altTextTruncated} : {}), ...(value !== undefined ? {value} : {}), ...(valueRedacted ? {valueRedacted} : {}), ...(valueUnavailable ? {valueUnavailable} : {}), ...(valueTruncated ? {valueTruncated} : {}) })), ...output, textMode: useDiff ? "diff" : "full", ...(options.includeFrames ? {frameCoverage: crossProcess ? "cross-process" as const : "same-process" as const, unavailableFrames} : {}), ...(options.includeValues ? {valuesTruncated:valueBudget.truncated} : {}) };
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
  async locatorContains(snapshotId: string, scopeIndex: number, targetIndex: number): Promise<boolean> {
    const observation = this.#observation;
    if (!observation || observation.id !== snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    return this.scopeContains(observation, scopeIndex, targetIndex);
  }

  /** @internal */
  bindLocatorScope(snapshotId: string, targetIndex: number, scopeIndices: number[], filters: FilterGuard[]): void {
    const observation = this.#observation;
    if (!observation || observation.id !== snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    observation.guards.set(targetIndex, {scopes:[...scopeIndices],filters:filters.map(item => ({index:item.index,filters:item.filters.map(filter=>({...filter}))}))});
  }

  /** @internal */
  async locatorText(snapshotId: string, index: number): Promise<string> {
    const observation = this.#observation;
    if (!observation || observation.id !== snapshotId) throw new RetryablePreflightError("Observation is stale; observe again");
    return this.scopeText(observation,index);
  }

  private async scopeText(observation: Observation, index: number): Promise<string> {
    const scope = observation.nodes.find(node => node.index === index);
    if (!scope) throw new RetryablePreflightError("Scope changed; observe again");
    const seen = new Set<string>();
    for (const item of observation.unindexedText) {
      if (item.backendNodeId === undefined) throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
      const key = `${item.frameId ?? "root"}:${item.backendNodeId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (scope.frameId === item.frameId && scope.backendNodeId === item.backendNodeId) throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
      const probe: ObservedNode = {index:-1,role:"",name:"",stateKey:"",backendNodeId:item.backendNodeId,frameId:item.frameId,frameChain:item.frameChain};
      const withProbe = {...observation,nodes:[...observation.nodes,probe]};
      if (await this.scopeContains(withProbe,index,-1) || await this.scopeContains(withProbe,-1,index)) throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
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
    const parts: string[] = [];
    let length = 0;
    for (const node of textNodes) {
      if (!included.has(node.index)) continue;
      length += node.name.length + 1;
      if (length > 30_000) throw new Error("Locator text exceeds the 30000 character limit");
      parts.push(node.name);
    }
    return parts.join(" ").replace(/\s+/g," ").trim();
  }

  private async freshFilterObservation(): Promise<Observation> {
    const documentId = await this.documentId();
    await this.browser.cdp.enableFrameSessions(this.id);
    const frames = await this.frameTree();
    const tree = await this.getAXState();
    const unindexedText: UnindexedText[] = unindexedTextAncestors(tree).map(backendNodeId=>({backendNodeId}));
    const nodes: ObservedNode[] = interactiveNodes(tree,0,true);
    for (const frame of frames.slice(1)) {
      const tree = await this.browser.cdp.call(this.id,"Accessibility.getFullAXTree",{frameId:frame.id},{sessionId:frame.sessionId});
      unindexedText.push(...unindexedTextAncestors(tree).map(backendNodeId=>({backendNodeId,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
      nodes.push(...interactiveNodes(tree,nodes.length,true).map(node => ({...node,frameId:frame.id,frameChain:frameAncestry(frame,frames)})));
    }
    if (documentId !== await this.documentId() || JSON.stringify(frames) !== JSON.stringify(await this.frameTree())) throw new RetryablePreflightError("Page changed; observe again");
    return {id:"",documentId,nodes,unindexedText,guards:new Map()};
  }

  private async scopeContains(observation: Observation, scopeIndex: number, targetIndex: number): Promise<boolean> {
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

  private async verifyLocatorScope(observation: Observation, target: ObservedNode): Promise<void> {
    const guard = observation.guards.get(target.index);
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
        if (!matchesTextFilters(await this.scopeText(fresh,current.index),item.filters)) throw new RetryablePreflightError("Locator text changed; observe again");
      }
    }
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

  async click(index: number, snapshotId: string): Promise<void> {
    await this.act(index, snapshotId);
  }

  async hover(index: number, snapshotId: string): Promise<void> {
    await this.act(index, snapshotId, undefined, false, undefined, undefined, true);
  }

  async press(index: number, snapshotId: string, key: string): Promise<void> {
    this.parseKey(key);
    await this.act(index, snapshotId, undefined, false, undefined, undefined, false, key);
  }

  async hoverAt(x: number, y: number): Promise<void> {
    this.#observation = undefined;
    await this.checkPoint(x, y);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
  }

  async clickAt(x: number, y: number): Promise<void> {
    this.#observation = undefined;
    await this.checkPoint(x, y);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
  }

  async drag(from: [number, number], to: [number, number]): Promise<void> {
    this.#observation = undefined;
    if (!Array.isArray(from) || from.length !== 2 || !Array.isArray(to) || to.length !== 2) throw new Error("Drag requires two coordinate pairs");
    await this.checkPoint(from[0], from[1]);
    await this.checkPoint(to[0], to[1]);
    let x = from[0], y = from[1], pressed = false;
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
    try {
      await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
      pressed = true;
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

  async scrollAt(x: number, y: number, deltaX: number, deltaY: number): Promise<void> {
    this.#observation = undefined;
    if (!Number.isFinite(deltaX) || !Number.isFinite(deltaY)) throw new Error("Scroll deltas must be finite numbers");
    await this.checkPoint(x, y);
    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
    await this.browser.cdp.call(this.id, "Input.synthesizeScrollGesture", { x, y, xDistance: -deltaX, yDistance: -deltaY, gestureSourceType: "mouse", preventFling: true });
  }

  private parseKey(key: string) {
    if (typeof key !== "string") throw new Error("Key must be a string");
    const definitions: Record<string, [string, number]> = {
      Enter: ["Enter", 13], Tab: ["Tab", 9], Escape: ["Escape", 27], Backspace: ["Backspace", 8],
      Delete: ["Delete", 46], ArrowLeft: ["ArrowLeft", 37], ArrowUp: ["ArrowUp", 38],
      ArrowRight: ["ArrowRight", 39], ArrowDown: ["ArrowDown", 40], Home: ["Home", 36], End: ["End", 35],
      PageUp: ["PageUp", 33], PageDown: ["PageDown", 34], Space: ["Space", 32]
    };
    const parts = key === "+" ? ["+"] : key.split("+");
    const name = parts.pop() ?? "";
    const modifierBits: Record<string, number> = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };
    const modifiers = parts.map(part => part === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : part);
    if (new Set(modifiers).size !== modifiers.length || modifiers.some(modifier => !Object.hasOwn(modifierBits, modifier))) throw new Error("Invalid keyboard modifiers");
    const pairs: Array<[string, string, string, number]> = [
      ...Array.from({length:10}, (_,digit) => [String(digit), ")!@#$%^&*("[digit], `Digit${digit}`, 48+digit] as [string,string,string,number]),
      ["-","_","Minus",189],["=","+","Equal",187],["[","{","BracketLeft",219],
      ["]","}","BracketRight",221],["\\","|","Backslash",220],[";",":","Semicolon",186],
      ["'",'"',"Quote",222],[",","<","Comma",188],[".",">","Period",190],
      ["/","?","Slash",191],["`","~","Backquote",192]
    ];
    const printablePair = pairs.find(([plain,shifted]) => name === plain || name === shifted);
    if (printablePair && name === printablePair[1] && !modifiers.includes("Shift")) modifiers.push("Shift");
    const definition = definitions[name] ?? (printablePair ? [printablePair[2],printablePair[3]] : /^[a-zA-Z]$/.test(name) ? [`Key${name.toUpperCase()}`, name.toUpperCase().charCodeAt(0)] : undefined) as [string,number] | undefined;
    if (!definition) throw new Error("Unsupported key");
    return {name, modifiers, modifierBits, definition, printablePair};
  }

  async pressKey(key: string): Promise<void> {
    this.#observation = undefined;
    await this.sendKey(key);
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
      const params = { key: actualKey, code: definition[0], windowsVirtualKeyCode: definition[1], modifiers: mask };
      const selectAll = actualKey === "a" && (mask === 2 || mask === 4);
      const printable = (name === "Space" || !!printablePair || /^[a-zA-Z]$/.test(name)) && !(mask & 7);
      activeKey = params;
      await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, type: printable ? "keyDown" : "rawKeyDown", ...(printable ? {text:actualKey, unmodifiedText:name === "Space" ? " " : printablePair ? printablePair[0] : name.toLowerCase()} : {}), ...(selectAll ? { commands: ["selectAll"] } : {}) }, {sessionId});
      await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, type: "keyUp" }, {sessionId});
      activeKey = undefined;
    } finally {
      if (activeKey) await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...activeKey, type: "keyUp" }, {sessionId}).catch(() => {});
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

  async setChecked(index: number, snapshotId: string, checked: boolean): Promise<void> {
    if (typeof checked !== "boolean") throw new Error("Checked state must be boolean");
    await this.act(index, snapshotId, undefined, false, checked);
  }

  async selectOption(index: number, snapshotId: string, values: SelectOption | SelectOption[]): Promise<string[]> {
    const specs = (Array.isArray(values) ? values : [values]).map(value => {
      if (typeof value === "string") return {value, label:value, either:true};
      if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !["value", "label"].includes(key)) ||
          (value.value === undefined && value.label === undefined) || (value.value !== undefined && typeof value.value !== "string") || (value.label !== undefined && typeof value.label !== "string")) throw new Error("Invalid select option");
      return {...value, either:false};
    });
    const result = await this.act(index, snapshotId, undefined, false, undefined, specs);
    if (!Array.isArray(result) || result.some(value => typeof value !== "string")) throw new Error("Invalid selected options result");
    return result as string[];
  }

  private async act(index: number, snapshotId: string, text?: string, replace = false, checked?: boolean, selection?: Array<{value?: string; label?: string; either: boolean}>, hover = false, key?: string): Promise<void | string[]> {
    const observation = this.#observation;
    this.#observation = undefined;
    const node = observation?.nodes.find((item) => item.index === index);
    if (!observation || observation.id !== snapshotId || !node) throw new RetryablePreflightError("Observation is stale or index is invalid; observe again");
    if (text !== undefined && !["textbox", "searchbox", "spinbutton", "Date", "DateTime", "InputTime"].includes(node.role)) throw new Error("Target is not a text field");
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
    if (checked !== undefined) {
      if (!["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(node.role) || typeof current.checked !== "boolean") throw new Error("Target does not have a binary checked state");
      if (current.checked === checked) {
        const resolved = await this.browser.cdp.call(this.id,"DOM.resolveNode",{backendNodeId:node.backendNodeId},{sessionId:targetSession});
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
    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId }, { sessionId: targetSession });
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Target is unavailable; observe again");
    let inputIssued = false;
    try {
      const measure = async () => {
        const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
          objectId, returnByValue: true, arguments:[{value:hover}],
          functionDeclaration: `function(allowDisabled) {
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
            point = await this.framePoint(frame.id, point.x as number, point.y as number, ownerSession);
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
              const hits=options.map((option,index)=>({option,index})).filter(({option})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));
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
          objectId, returnByValue:true, arguments:[{value:found.chosen}],
          functionDeclaration:`function(chosen) {
            if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.disabled || (!this.multiple && chosen.length > 1)) return null;
            const options=Array.from(this.options);
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
      const inputOptions = {sessionId: targetSession, ...(targetSession ? {visualPoint: {x: point.x as number, y: point.y as number}} : {})};
      inputIssued = true;
      if (hover) {
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x: inputPoint.x, y: inputPoint.y, button: "none", buttons: 0 }, inputOptions);
        return;
      }
      await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x: inputPoint.x, y: inputPoint.y, button: "left", buttons: 1, clickCount: 1 }, inputOptions);
      await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x: inputPoint.x, y: inputPoint.y, button: "left", buttons: 0, clickCount: 1 }, inputOptions);
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

  private async framePoint(frameId: string, x: number, y: number, sessionId?: string): Promise<{ x: number; y: number }> {
    const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId }, {sessionId});
    if (!isObject(owner) || typeof owner.backendNodeId !== "number") throw new RetryablePreflightError("Frame owner is unavailable");
    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId }, {sessionId});
    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
    if (typeof objectId !== "string") throw new RetryablePreflightError("Frame owner is unavailable");
    try {
      const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
        objectId, returnByValue: true, arguments: [{value:x},{value:y}],
        functionDeclaration: `function(x,y) {
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
          let target=this, root=target.getRootNode();
          while (true) { const hit=root.elementFromPoint(x,y); if (!hit || (hit!==target && !target.contains(hit))) return null; if (!(root instanceof ShadowRoot)) return {x,y}; target=root.host; root=target.getRootNode(); }
        }`
      }, {sessionId});
      const point = isObject(result) && isObject(result.result) ? result.result.value : null;
      if (!isObject(point) || typeof point.x !== "number" || !Number.isFinite(point.x) || typeof point.y !== "number" || !Number.isFinite(point.y)) throw new RetryablePreflightError("Frame is hidden, covered or has an unsupported transform");
      return {x:point.x,y:point.y};
    } finally { await this.browser.cdp.call(this.id, "Runtime.releaseObject", {objectId}, {sessionId}).catch(() => {}); }
  }

  async getScreenshot(options: {clip?: {x: number; y: number; width: number; height: number}} = {}): Promise<Buffer> {
    let clip: {x: number; y: number; width: number; height: number; scale: number} | undefined;
    if (options.clip !== undefined) {
      const rect = {...options.clip};
      if (![rect.x,rect.y,rect.width,rect.height].every(Number.isFinite) || rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0) throw new Error("Invalid screenshot clip");
      const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
      const viewport = isObject(metrics) ? metrics.cssVisualViewport : null;
      if (!isObject(viewport) || ![viewport.pageX,viewport.pageY,viewport.clientWidth,viewport.clientHeight].every(value => typeof value === "number" && Number.isFinite(value))) throw new Error("Browser viewport is unavailable");
      const {pageX, pageY, clientWidth, clientHeight} = viewport as {pageX: number; pageY: number; clientWidth: number; clientHeight: number};
      if (rect.x + rect.width > clientWidth || rect.y + rect.height > clientHeight) throw new Error("Screenshot clip is outside the viewport");
      clip = {x:pageX+rect.x,y:pageY+rect.y,width:rect.width,height:rect.height,scale:1};
    }
    const result = await this.browser.cdp.call(this.id, "Page.captureScreenshot", { format: "png", ...(clip ? {clip,captureBeyondViewport:false} : {}) });
    if (!isObject(result) || typeof result.data !== "string" || !result.data) {
      throw new Error("Browser returned an invalid screenshot");
    }
    return Buffer.from(result.data, "base64");
  }

  evaluate(expression: string, options: { awaitPromise?: boolean } = {}): Promise<JsonValue> {
    return this.browser.cdp.evaluate(this.id, expression, options);
  }

  close(): Promise<JsonValue> {
    return this.browser.cdp.call(this.id, "Page.close");
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

  domSnapshot(): Promise<string> {
    return this.tab.domSnapshot();
  }

  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator {
    if (typeof role !== "string" || !role || !options || typeof options !== "object" || Array.isArray(options) ||
        Object.keys(options).some(key => !["name","exact","checked","disabled","pressed","selected","expanded"].includes(key)) ||
        (options.name !== undefined && typeof options.name !== "string") ||
        [options.exact,options.checked,options.disabled,options.pressed,options.selected,options.expanded].some(value => value !== undefined && typeof value !== "boolean")) throw new Error("Invalid role locator");
    return new OpenBrowserUseRoleLocator(this.tab, [role === "img" ? "image" : role], {...options});
  }

  getByLabel(name: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if (typeof name !== "string" || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid label locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "switch", "slider", "spinbutton", "Date", "DateTime", "InputTime"], {name, ...options});
  }

  getByText(text: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if (typeof text !== "string" || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid text locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["StaticText"], {name:text, ...options}, undefined, true);
  }

  getByAltText(altText: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if (typeof altText !== "string" || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid alt text locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["image", "button", "link"], {name:altText, ...options}, undefined, false, "altText");
  }

  getByPlaceholder(placeholder: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator {
    if (typeof placeholder !== "string" || (options.exact !== undefined && typeof options.exact !== "boolean")) throw new Error("Invalid placeholder locator");
    return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "spinbutton"], {name:placeholder, ...options}, undefined, false, "placeholder");
  }
}

export class OpenBrowserUseRoleLocator {
  constructor(private tab: OpenBrowserUseTab, private roles: readonly string[], private options: RoleLocatorOptions, private position?: number, private textMatch = false, private field: "name" | "placeholder" | "altText" = "name", private scope?: OpenBrowserUseRoleLocator, private filtersBefore: TextFilter[] = [], private filtersAfter: TextFilter[] = []) {}

  nth(index: number): OpenBrowserUseRoleLocator {
    if (!Number.isSafeInteger(index) || index < 0) throw new Error("Locator index must be a non-negative integer");
    if (this.position !== undefined) return index === 0 ? this : new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, Number.MAX_SAFE_INTEGER, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter);
    return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, index, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter);
  }

  first(): OpenBrowserUseRoleLocator { return this.nth(0); }

  private child(locator: OpenBrowserUseRoleLocator): OpenBrowserUseRoleLocator {
    return new OpenBrowserUseRoleLocator(this.tab,locator.roles,locator.options,locator.position,locator.textMatch,locator.field,this,locator.filtersBefore,locator.filtersAfter);
  }

  getByRole(role: string, options: RoleLocatorOptions = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByRole(role,options)); }
  getByLabel(name: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByLabel(name,options)); }
  getByText(text: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByText(text,options)); }
  getByAltText(text: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByAltText(text,options)); }
  getByPlaceholder(text: string, options: {exact?: boolean} = {}): OpenBrowserUseRoleLocator { return this.child(this.tab.playwright.getByPlaceholder(text,options)); }

  filter(options: {hasText?: string; hasNotText?: string}): OpenBrowserUseRoleLocator {
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["hasText","hasNotText"].includes(key)) ||
        (options.hasText === undefined && options.hasNotText === undefined) ||
        (options.hasText !== undefined && (typeof options.hasText !== "string" || options.hasText.length > 30_000)) ||
        (options.hasNotText !== undefined && (typeof options.hasNotText !== "string" || options.hasNotText.length > 30_000))) throw new Error("Invalid text filter");
    const filter = {...options};
    return new OpenBrowserUseRoleLocator(this.tab,this.roles,this.options,this.position,this.textMatch,this.field,this.scope,
      this.position === undefined ? [...this.filtersBefore,filter] : this.filtersBefore,
      this.position === undefined ? this.filtersAfter : [...this.filtersAfter,filter]);
  }

  private needsText(): boolean {
    return this.filtersBefore.length > 0 || this.filtersAfter.length > 0 || this.roles.some(role => supplementalRoles.includes(role)) || !!this.scope?.needsText();
  }

  private async matches(state: InteractiveState): Promise<Array<{node:InteractiveNode; path:number[]; filters:FilterGuard[]}>> {
    if (this.field === "placeholder" && state.nodes.some(node => this.roles.includes(node.role) && node.placeholderTruncated)) throw new Error("Some placeholders were truncated; locator results are incomplete");
    if (this.field === "altText" && state.nodes.some(node => this.roles.includes(node.role) && node.altTextTruncated)) throw new Error("Some alt text was truncated; locator results are incomplete");
    const normalize = (value: string) => this.textMatch ? value.replace(/\s+/g," ").trim() : value;
    const candidates = state.nodes.filter(node => {
      const value = node[this.field];
      return this.roles.includes(node.role) && typeof value === "string" &&
        (this.options.checked === undefined || node.checked === this.options.checked) &&
        (this.options.disabled === undefined || !!node.disabled === this.options.disabled) &&
        (this.options.pressed === undefined || node.pressed === this.options.pressed) &&
        (this.options.selected === undefined || node.selected === this.options.selected) &&
        (this.options.expanded === undefined || node.expanded === this.options.expanded) &&
        (this.options.name === undefined || (this.options.exact ? normalize(value) === normalize(this.options.name) : normalize(value).toLowerCase().includes(normalize(this.options.name).toLowerCase())));
    });
    const matches: Array<{node:InteractiveNode; path:number[]; filters:FilterGuard[]}> = [];
    if (!this.scope) for (const node of candidates) matches.push({node,path:[],filters:[]});
    else {
      const scopes = await this.scope.matches(state);
      for (const node of candidates) for (const scope of scopes) {
        if (await this.tab.locatorContains(state.snapshotId,scope.node.index,node.index)) {
          matches.push({node,path:[...scope.path,scope.node.index],filters:[...scope.filters]}); break;
        }
      }
    }
    const apply = async (items: typeof matches, filters: TextFilter[]) => {
      if (!filters.length) return items;
      const accepted: typeof matches = [];
      for (const item of items) {
        if (matchesTextFilters(await this.tab.locatorText(state.snapshotId,item.node.index),filters)) accepted.push({...item,filters:[...item.filters,{index:item.node.index,filters}]});
      }
      return accepted;
    };
    const before = await apply(matches,this.filtersBefore);
    return apply(this.position === undefined ? before : before.slice(this.position,this.position + 1),this.filtersAfter);
  }

  private async find(): Promise<{state: InteractiveState; matches: Array<{node:InteractiveNode; path:number[]; filters:FilterGuard[]}>}> {
    const state = await this.tab.observe({includeFrames:true, ...(this.needsText() ? {includeText:true} : {})});
    if (state.unavailableFrames?.length) throw new Error("Some frames could not be observed; locator results are incomplete");
    return {state,matches:await this.matches(state)};
  }

  async count(): Promise<number> { return (await this.find()).matches.length; }

  private async perform<T>(action: (node: InteractiveNode, snapshotId: string) => Promise<T>, timeoutMs = 5_000): Promise<T> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000) throw new Error("Invalid locator timeout");
    const deadline = performance.now() + timeoutMs;
    let lastError: Error = new Error(`Locator matched 0 elements before timeout (${timeoutMs} ms)`);
    while (true) {
      try {
        const {state, matches} = await this.find();
        if (matches.length > 1) throw new Error(`Locator matched ${matches.length} elements; expected exactly one`);
        if (matches.length === 1) {
          if (matches[0].path.length || matches[0].filters.length) this.tab.bindLocatorScope(state.snapshotId,matches[0].node.index,matches[0].path,matches[0].filters);
          return await action(matches[0].node, state.snapshotId);
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

  async click(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.click(node.index,id), options.timeoutMs); }
  async hover(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.hover(node.index,id), options.timeoutMs); }
  async press(key: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.press(node.index,id,key), options.timeoutMs); }
  async fill(text: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.fill(node.index,id,text), options.timeoutMs); }
  async type(text: string, options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.typeText(node.index,id,text), options.timeoutMs); }
  async check(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.setChecked(node.index,id,true), options.timeoutMs); }
  async uncheck(options: {timeoutMs?: number} = {}): Promise<void> { await this.perform((node,id)=>this.tab.setChecked(node.index,id,false), options.timeoutMs); }
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

  constructor(client: OpenBrowserUseClient) {
    this.client = client;
    client.onNotification(notification => {
      if (["onDebuggerDetach","onTabClosed"].includes(notification.method) && isObject(notification.params) && typeof notification.params.tabId === "number") {
        const tabId = notification.params.tabId;
        this.#frames.get(tabId)?.clear();
        this.#frames.delete(tabId);
        this.#generations.delete(tabId);
        this.#failure.delete(tabId);
        this.#dialogs.delete(tabId);
        this.#dialogEnabled.delete(tabId);
        return;
      }
      if (notification.method !== "onCDPEvent" || !isObject(notification.params)) return;
      const { source, method, params } = notification.params;
      if (!isObject(source) || typeof source.tabId !== "number" || !isObject(params)) return;
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
        .then(() => {}, error => { if (frames.has(sessionId)) this.#failure.set(tabId, error instanceof Error ? error : new Error(String(error))); })
        .finally(() => pending.delete(task));
      pending.add(task);
    });
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

  async call(
    tabId: number,
    method: string,
    commandParams: BrowserUseRequestParams = {},
    options: { timeoutMs?: number; sessionId?: string; visualPoint?: {x: number; y: number}; expectedGeneration?: number } = {}
  ): Promise<JsonValue> {
    await this.ensureAttached(tabId);
    if (options.expectedGeneration !== undefined && options.expectedGeneration !== this.client.connectionGeneration) throw new Error("Connection changed; observe again");
    const result = await this.client.request("executeCdp", {
      target: { tabId, ...(options.sessionId ? {sessionId: options.sessionId} : {}) },
      method,
      commandParams,
      ...(options.visualPoint ? {visualPoint: options.visualPoint} : {}),
      ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs })
    },options.expectedGeneration);
    if (method === "Page.disable" && !options.sessionId) this.#dialogEnabled.delete(tabId);
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
    return isObject(result) && isObject(result.result) ? (result.result.value ?? null) : null;
  }

  async navigate(tabId: number, url: string, options: OpenBrowserUseGotoOptions = {}): Promise<JsonValue> {
    if (!url) {
      throw new Error("goto requires a URL");
    }
    const waitUntil = options.waitUntil ?? "load";
    assertSupportedLoadState(waitUntil);
    const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    await this.call(tabId, "Page.enable");
    const wait = this.waitForLoadEvent(tabId, waitUntil, timeoutMs);
    const result = await this.call(tabId, "Page.navigate", { url }, { timeoutMs });
    if (isObject(result) && typeof result.errorText === "string" && result.errorText) {
      throw new Error(`Browser failed to navigate tab ${tabId}: ${result.errorText}`);
    }
    await wait.catch(async (error) => {
      const state = await this.readDocumentState(tabId);
      if (documentStateMatches(state, waitUntil)) {
        return;
      }
      throw error;
    });
    return result;
  }

  async waitForLoadState(tabId: number, options: OpenBrowserUseWaitForLoadStateOptions = {}): Promise<void> {
    const state = options.state ?? "load";
    assertSupportedLoadState(state);
    await this.call(tabId, "Page.enable");
    const documentState = await this.readDocumentState(tabId);
    if (documentStateMatches(documentState, state)) {
      return;
    }
    await this.waitForLoadEvent(tabId, state, options.timeoutMs ?? defaultNavigationTimeoutMs);
  }

  async readDocumentState(tabId: number): Promise<{ href?: string; readyState?: string } | undefined> {
    try {
      const value = await this.evaluate(tabId, "({ href: window.location.href, readyState: document.readyState })");
      return isObject(value) ? { href: stringValue(value.href), readyState: stringValue(value.readyState) } : undefined;
    } catch {
      return undefined;
    }
  }

  waitForEvent(
    tabId: number,
    predicate: (notification: OpenBrowserUseNotification) => boolean,
    options: { timeoutMs?: number; timeoutMessage?: string } = {}
  ): Promise<OpenBrowserUseNotification> {
    const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
    return new Promise((resolve, reject) => {
      let settled = false;
      let removeHandler: (() => void) | null = null;
      let timer: NodeJS.Timeout;
      const finish = (): boolean => {
        if (settled) {
          return false;
        }
        settled = true;
        clearTimeout(timer);
        removeHandler?.();
        return true;
      };
      timer = setTimeout(() => {
        if (finish()) {
          reject(new Error(options.timeoutMessage ?? `Timed out waiting for tab ${tabId} event`));
        }
      }, timeoutMs);
      removeHandler = this.client.onNotification((notification) => {
        try {
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

  waitForLoadEvent(tabId: number, state: OpenBrowserUseLoadState, timeoutMs: number): Promise<void> {
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
        timeoutMessage: `Timed out waiting for ${state} in tab ${tabId}`
      }
    ).then(() => undefined);
  }

  async ensureAttached(tabId: number): Promise<void> {
    await this.client.attach(tabId);
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

function interactiveNodes(tree: JsonValue, offset = 0, includeText = false): Array<InteractiveNode & { backendNodeId: number; stateKey: string }> {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) throw new Error("Invalid accessibility tree");
  const roles = new Set(["button", "link", "checkbox", "radio", "switch", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "combobox", "listbox", "textbox", "searchbox", "slider", "spinbutton", "Date", "DateTime", "InputTime", ...(includeText ? supplementalRoles : [])]);
  const nodes: Array<InteractiveNode & { backendNodeId: number; stateKey: string }> = [];
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
  for (const node of tree.nodes) {
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
    nodes.push({ index: offset + nodes.length + 1, role, name, backendNodeId: node.backendDOMNodeId, stateKey: JSON.stringify(states), ...(checked !== undefined ? {checked} : {}), ...(disabled ? {disabled:true} : {}), ...(pressed !== undefined ? {pressed} : {}), ...(selected !== undefined ? {selected} : {}), ...(expanded !== undefined ? {expanded} : {}), ...(placeholder !== undefined ? {placeholder} : {}), ...(placeholderTruncated ? {placeholderTruncated:true} : {}), ...(altText !== undefined ? {altText} : {}), ...(altTextTruncated ? {altTextTruncated:true} : {}) });
  }
  return nodes;
}

function axProperties(node: { [key: string]: JsonValue }): string[] {
  return Array.isArray(node.properties) ? node.properties.flatMap(property => {
    if (!isObject(property) || typeof property.name !== "string" || !["checked", "selected", "expanded", "disabled", "pressed", "required", "readonly"].includes(property.name) || !isObject(property.value)) return [];
    const value = property.value.value;
    return typeof value === "boolean" || typeof value === "string" ? [`${property.name}=${JSON.stringify(value)}`] : [];
  }).sort() : [];
}

function renderAXState(tree: JsonValue, targets: Array<InteractiveNode & { backendNodeId: number }>): { text: string; truncated: boolean } {
  if (!isObject(tree) || !Array.isArray(tree.nodes)) throw new Error("Invalid accessibility tree");
  const indexed = new Map(targets.map(node => [node.backendNodeId, node]));
  const lines: string[] = [];
  let length = 0;
  for (const node of tree.nodes) {
    if (!isObject(node) || node.ignored === true || !isObject(node.role)) continue;
    const role = node.role.value;
    const name = isObject(node.name) && typeof node.name.value === "string" ? node.name.value : "";
    const target = typeof node.backendDOMNodeId === "number" ? indexed.get(node.backendDOMNodeId) : undefined;
    const index = target?.index;
    if (typeof role !== "string" || (!name && index === undefined)) continue;
    const properties = axProperties(node);
    if (target?.altText !== undefined) properties.push(`alt=${JSON.stringify(target.altText)}${target.altTextTruncated ? "…" : ""}`);
    if (target?.placeholder !== undefined) properties.push(`placeholder=${JSON.stringify(target.placeholder)}${target.placeholderTruncated ? "…" : ""}`);
    if (target?.valueRedacted) properties.push("value=[redacted]");
    else if (target?.valueUnavailable) properties.push("value=[unavailable]");
    else if (target?.value !== undefined) properties.push(`value=${JSON.stringify(target.value)}${target.valueTruncated ? "…" : ""}`);
    else if (target?.valueTruncated) properties.push("value=[truncated]");
    const line = `${index === undefined ? "" : `[${index}] `}${role}${name ? ` ${JSON.stringify(name)}` : ""}${properties.length ? ` ${properties.join(" ")}` : ""}`;
    if (length + line.length + 1 > 30_000) {
      const available = 30_000 - length - 1;
      if (available > 1) lines.push(`${line.slice(0, available - 1)}…`);
      return { text: lines.join("\n"), truncated: true };
    }
    lines.push(line);
    length += line.length + 1;
  }
  return { text: lines.join("\n"), truncated: false };
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
): { method?: string } | null {
  if (notification.method !== "onCDPEvent" || !isObject(notification.params)) {
    return null;
  }
  const source = notification.params.source;
  if (!isObject(source) || source.tabId !== tabId) {
    return null;
  }
  return {
    method: stringValue(notification.params.method)
  };
}

function stringValue(value: JsonValue | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}
