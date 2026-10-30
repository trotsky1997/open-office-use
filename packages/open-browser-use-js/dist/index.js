import { createConnection } from "node:net";
import { endianness } from "node:os";
import { createHash, randomUUID } from "node:crypto";
import { types } from "node:util";
import { isAbsolute } from "node:path";
const headerBytes = 4;
const defaultNavigationTimeoutMs = 10_000;
function selectSpecs(values) {
    return (Array.isArray(values) ? values : [values]).map(value => {
        if (typeof value === "string")
            return { value, label: value, either: true };
        if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !["value", "label"].includes(key)) ||
            (value.value === undefined && value.label === undefined) || (value.value !== undefined && typeof value.value !== "string") || (value.label !== undefined && typeof value.label !== "string"))
            throw new Error("Invalid select option");
        return { ...value, either: false };
    });
}
function testIdSelector(testId) {
    if (typeof testId !== "string" || testId.length > 500 || /[\u0000\ud800-\udfff]/u.test(testId))
        throw new Error("Invalid test id");
    return `[data-testid="${Array.from(testId, char => `\\${char.codePointAt(0).toString(16)} `).join("")}"]`;
}
function applyLocatorOptions(locator, options) {
    if (options === undefined)
        return locator;
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["hasText", "hasNotText", "has", "hasNot"].includes(key)))
        throw new Error("Invalid locator options");
    return Object.values(options).every(value => value === undefined) ? locator : locator.filter(options);
}
function locatorClickOptions(options) {
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["timeoutMs", "button", "modifiers", "force"].includes(key)) || (options.force !== undefined && typeof options.force !== "boolean"))
        throw new Error("Invalid locator click options");
    if (options.force)
        throw new Error("Forced locator clicks are not supported");
    const button = options.button ?? "left", masks = { left: 1, middle: 4, right: 2 };
    if (!Object.hasOwn(masks, button))
        throw new Error("Invalid mouse button");
    return { button, buttons: masks[button], modifiers: cuaModifiers(options.modifiers) };
}
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
const supplementalRoles = ["heading", "StaticText", "image", "dialog", "alertdialog", "group", "list", "listitem", "table", "row", "cell", "columnheader", "rowheader", "grid", "gridcell", "tree", "treeitem", "navigation", "main", "region", "form", "article"];
class RetryablePreflightError extends Error {
}
function unindexedTextAncestors(tree) {
    if (!isObject(tree) || !Array.isArray(tree.nodes))
        return [];
    const nodes = tree.nodes.filter(isObject);
    const byId = new Map(nodes.filter(node => typeof node.nodeId === "string").map(node => [node.nodeId, node]));
    return nodes.filter(node => node.ignored !== true && isObject(node.role) && node.role.value === "StaticText" &&
        isObject(node.name) && typeof node.name.value === "string" && node.name.value.length > 0 && typeof node.backendDOMNodeId !== "number").map(node => {
        const seen = new Set();
        let parent = node.parentId;
        while (typeof parent === "string" && !seen.has(parent)) {
            seen.add(parent);
            const ancestor = byId.get(parent);
            if (!ancestor)
                break;
            if (typeof ancestor.backendDOMNodeId === "number")
                return ancestor.backendDOMNodeId;
            parent = ancestor.parentId;
        }
        return undefined;
    });
}
function matchesTextFilters(text, filters) {
    const matches = (value) => typeof value === "string" ? text.toLowerCase().includes(value.replace(/\s+/g, " ").trim().toLowerCase()) : new RegExp(value.source, value.flags).test(text);
    return filters.every(filter => (filter.hasText === undefined || matches(filter.hasText)) && (filter.hasNotText === undefined || !matches(filter.hasNotText)));
}
function copyMatcher(value) { return typeof value === "string" ? value : new RegExp(value.source, value.flags); }
function browserLogEntry(method, params) {
    const browserEntry = method === "Log.entryAdded" && isObject(params.entry) ? params.entry : undefined;
    if (method === "Log.entryAdded" && !browserEntry)
        return null;
    const details = isObject(params.exceptionDetails) ? params.exceptionDetails : undefined;
    const exception = details && isObject(details.exception) ? details.exception : undefined;
    const kind = method === "Runtime.exceptionThrown" ? "error" : browserEntry?.level ?? params.type;
    const level = kind === "warning" || kind === "warn" ? "warn" : kind === "error" || kind === "assert" ? "error" : kind === "verbose" ? "debug" : kind === "debug" || kind === "info" ? kind : "log";
    const message = browserEntry ? String(browserEntry.text ?? "") : method === "Runtime.exceptionThrown"
        ? String(exception?.description ?? exception?.value ?? details?.text ?? "Uncaught exception")
        : Array.isArray(params.args) ? params.args.slice(0, 50).map(arg => isObject(arg) ? String(arg.value ?? arg.unserializableValue ?? arg.description ?? "[object]").slice(0, 4096) : "[object]").join(" ") : "";
    const trace = isObject(params.stackTrace) && Array.isArray(params.stackTrace.callFrames) ? params.stackTrace.callFrames[0] : undefined;
    const url = typeof browserEntry?.url === "string" ? browserEntry.url : typeof details?.url === "string" ? details.url : isObject(trace) && typeof trace.url === "string" ? trace.url : undefined;
    return { level, message: message.slice(0, 4096), timestamp: new Date().toISOString(), ...(url ? { url: url.slice(0, 4096) } : {}) };
}
export class OpenBrowserUseClient {
    socketPath;
    sessionId;
    turnId;
    timeoutMs;
    #socket = null;
    #connection = null;
    #pendingData = Buffer.alloc(0);
    #nextId = 1;
    #pending = new Map();
    #notificationHandlers = new Set();
    #disconnectHandlers = new Set();
    #generation = 0;
    get connectionGeneration() { return this.#generation; }
    constructor(options) {
        this.socketPath = options.socketPath;
        this.sessionId = options.sessionId ?? "open-browser-use-js";
        this.turnId = options.turnId ?? `turn-${Date.now()}`;
        this.timeoutMs = options.timeoutMs ?? 10_000;
    }
    async connect() {
        if (this.#socket) {
            if (this.#connection)
                await this.#connection;
            return this;
        }
        const socket = createConnection(this.socketPath);
        this.#socket = socket;
        socket.on("data", (chunk) => this.#handleData(Buffer.from(chunk)));
        socket.on("close", () => {
            if (this.#socket !== socket)
                return;
            this.#socket = null;
            this.#generation++;
            this.#pendingData = Buffer.alloc(0);
            const error = new Error("Open Browser Use socket closed");
            this.#rejectAll(error);
            this.emitDisconnect(error);
        });
        socket.on("error", (error) => { if (this.#socket === socket)
            this.#rejectAll(error); });
        const connection = new Promise((resolve, reject) => {
            const cleanup = () => { socket.off("connect", connected); socket.off("error", failed); socket.off("close", closed); };
            const connected = () => { cleanup(); resolve(); };
            const failed = (error) => { cleanup(); reject(error); };
            const closed = () => failed(new Error("Open Browser Use socket closed before connecting"));
            socket.once("connect", connected);
            socket.once("error", failed);
            socket.once("close", closed);
        });
        this.#connection = connection;
        try {
            await connection;
            this.#generation++;
        }
        catch (error) {
            if (this.#socket === socket) {
                this.#socket = null;
                this.#pendingData = Buffer.alloc(0);
            }
            socket.destroy();
            throw error;
        }
        finally {
            if (this.#connection === connection)
                this.#connection = null;
        }
        return this;
    }
    close() {
        if (this.#socket)
            this.#generation++;
        this.#socket?.destroy();
        this.#socket = null;
        this.#connection = null;
        this.#pendingData = Buffer.alloc(0);
        const error = new Error("Open Browser Use socket closed");
        this.#rejectAll(error);
        this.emitDisconnect(error);
    }
    onDisconnect(handler) {
        this.#disconnectHandlers.add(handler);
        return () => { this.#disconnectHandlers.delete(handler); };
    }
    emitDisconnect(error) {
        for (const handler of this.#disconnectHandlers)
            handler(error);
    }
    onNotification(handler) {
        this.#notificationHandlers.add(handler);
        return () => {
            this.#notificationHandlers.delete(handler);
        };
    }
    async request(method, params = {}, expectedGeneration, requestTimeoutMs = this.timeoutMs) {
        await this.connect();
        if (expectedGeneration !== undefined && expectedGeneration !== this.#generation)
            throw new Error("Connection changed; observe again");
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
        const promise = new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                this.#pending.delete(id);
                reject(new Error(`Open Browser Use request timed out: ${method}`));
            }, requestTimeoutMs);
            this.#pending.set(id, { resolve, reject, timeout });
        });
        socket.write(payload);
        return await promise;
    }
    getInfo() {
        return this.request("getInfo");
    }
    createTab() {
        return this.request("createTab");
    }
    getTabs() {
        return this.request("getTabs");
    }
    getUserTabs() {
        return this.request("getUserTabs");
    }
    getUserHistory(params = {}) {
        return this.request("getUserHistory", params);
    }
    claimUserTab(tabId) {
        return this.request("claimUserTab", { tabId });
    }
    finalizeTabs(keep) {
        return this.request("finalizeTabs", { keep });
    }
    nameSession(name) {
        return this.request("nameSession", { name });
    }
    attach(tabId) {
        return this.request("attach", { tabId });
    }
    detach(tabId) {
        return this.request("detach", { tabId });
    }
    executeCdp(tabId, method, commandParams = {}) {
        return this.request("executeCdp", {
            target: { tabId },
            method,
            commandParams
        });
    }
    moveMouse(tabId, x, y, waitForArrival = true) {
        return this.request("moveMouse", { tabId, x, y, waitForArrival });
    }
    waitForFileChooser(tabId, timeoutMs) {
        return this.request("waitForFileChooser", {
            tabId,
            ...(timeoutMs === undefined ? {} : { timeoutMs })
        });
    }
    setFileChooserFiles(fileChooserId, files) {
        return this.request("setFileChooserFiles", { fileChooserId, files });
    }
    waitForDownload(tabId, timeoutMs) {
        return this.request("waitForDownload", {
            tabId,
            ...(timeoutMs === undefined ? {} : { timeoutMs })
        });
    }
    downloadPath(downloadId, timeoutMs) {
        return this.request("downloadPath", {
            downloadId,
            ...(timeoutMs === undefined ? {} : { timeoutMs })
        }, undefined, typeof timeoutMs === "number" && Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.max(this.timeoutMs, timeoutMs + 2000) : this.timeoutMs);
    }
    browserUserHistory(params = {}) {
        return this.getUserHistory(params);
    }
    readClipboardText(tabId) {
        return this.request("readClipboardText", { tabId });
    }
    writeClipboardText(tabId, text) {
        return this.request("writeClipboardText", { tabId, text });
    }
    readClipboard(tabId) {
        return this.request("readClipboard", { tabId });
    }
    writeClipboard(tabId, items) {
        return this.request("writeClipboard", { tabId, items });
    }
    turnEnded() {
        return this.request("turnEnded");
    }
    #handleData(chunk) {
        this.#pendingData = Buffer.concat([this.#pendingData, chunk]);
        while (this.#pendingData.length >= headerBytes) {
            const length = endianness() === "LE"
                ? this.#pendingData.readUInt32LE(0)
                : this.#pendingData.readUInt32BE(0);
            const total = headerBytes + length;
            if (this.#pendingData.length < total) {
                return;
            }
            const payload = this.#pendingData.subarray(headerBytes, total);
            this.#pendingData = this.#pendingData.subarray(total);
            this.#handleMessage(JSON.parse(payload.toString("utf8")));
        }
    }
    #handleMessage(message) {
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
        pending.resolve((message.result ?? null));
    }
    #rejectAll(error) {
        for (const [id, pending] of this.#pending) {
            this.#pending.delete(id);
            clearTimeout(pending.timeout);
            pending.reject(error);
        }
    }
}
export async function connectOpenBrowserUse(options) {
    const browser = new OpenBrowserUseBrowser(options);
    await browser.connect();
    return browser;
}
function browserTabId(value) {
    const raw = value instanceof OpenBrowserUseTab ? value.id : value && typeof value === 'object' && 'id' in value ? value.id : value;
    if (typeof raw === 'number' && Number.isSafeInteger(raw) && raw > 0)
        return raw;
    if (typeof raw === 'string' && /^[1-9][0-9]*$/.test(raw) && Number.isSafeInteger(Number(raw)))
        return Number(raw);
    throw new Error('Invalid tab ID');
}
function browserTabs(value) {
    if (!Array.isArray(value))
        throw new Error('Browser returned an invalid tab list');
    const ids = new Set();
    return value.map(item => {
        if (!isObject(item))
            throw new Error('Browser returned an invalid tab');
        const id = browserTabId(item.id);
        if (ids.has(id))
            throw new Error('Browser returned duplicate tab IDs');
        ids.add(id);
        if ((item.title !== undefined && item.title !== null && typeof item.title !== 'string') || (item.url !== undefined && item.url !== null && typeof item.url !== 'string') || (item.active !== undefined && typeof item.active !== 'boolean'))
            throw new Error('Browser returned an invalid tab');
        return { id: String(id), ...(typeof item.title === 'string' ? { title: item.title } : {}), ...(typeof item.url === 'string' ? { url: item.url } : {}), ...(typeof item.active === 'boolean' ? { active: item.active } : {}) };
    });
}
export class OpenBrowserUseBrowser {
    client;
    cdp;
    browserId;
    tabs;
    capabilities;
    user;
    #domCua = new Map();
    constructor(options) {
        this.client = "client" in options ? options.client : new OpenBrowserUseClient(options);
        this.cdp = new OpenBrowserUseCdp(this.client);
        this.tabs = new OpenBrowserUseTabs(this);
        this.capabilities = new OpenBrowserUseCapabilities(this);
        this.user = new OpenBrowserUseBrowserUser(this);
    }
    async connect() {
        await this.client.connect();
        return this;
    }
    close() {
        this.client.close();
    }
    async nameSession(name) {
        if (typeof name !== 'string' || !name.trim() || name.length > 200)
            throw new Error('Invalid session name');
        await this.client.nameSession(name);
    }
    async newTab(options = {}) {
        const created = await this.client.createTab();
        const tabId = tabIdFromValue(created, "createTab response");
        const tab = this.tab(tabId);
        if (options.url) {
            await tab.goto(options.url, options);
        }
        return tab;
    }
    tab(tabId) {
        return new OpenBrowserUseTab(this, tabId);
    }
    /** @internal */
    domCuaFor(tab) {
        const existing = this.#domCua.get(tab.id)?.deref();
        if (existing)
            return existing;
        const dom = new OpenBrowserUseTabDomCUA(tab);
        this.#domCua.set(tab.id, new WeakRef(dom));
        return dom;
    }
    getTabs() {
        return this.client.getTabs();
    }
    getUserTabs() {
        return this.client.getUserTabs();
    }
    async claimTab(tabId) {
        if (!Number.isSafeInteger(tabId) || tabId < 1)
            throw new Error("A valid tab ID is required");
        const claimed = await this.client.claimUserTab(tabId);
        if (tabIdFromValue(claimed, "claimUserTab response") !== tabId)
            throw new Error("Browser claimed a different tab");
        return this.tab(tabId);
    }
}
export class OpenBrowserUseTabs {
    browser;
    constructor(browser) {
        this.browser = browser;
    }
    async list() { return browserTabs(await this.browser.getTabs()); }
    async get(id) {
        const tabId = browserTabId(id), tabs = await this.list();
        if (!tabs.some(tab => tab.id === String(tabId)))
            throw new Error('Tab is outside this browser session');
        return this.browser.tab(tabId);
    }
    new() { return this.browser.newTab(); }
    async selected() {
        const selected = (await this.list()).filter(tab => tab.active === true);
        if (selected.length > 1)
            throw new Error('Multiple session tabs are selected');
        return selected.length ? this.browser.tab(browserTabId(selected[0].id)) : undefined;
    }
    async finalize(options = {}) {
        if (!options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => key !== 'keep') || (options.keep !== undefined && !Array.isArray(options.keep)))
            throw new Error('Invalid tab finalization options');
        const seen = new Set(), keep = (options.keep ?? []).map(item => {
            if (!item || !['handoff', 'deliverable'].includes(item.status) || (item.tab instanceof OpenBrowserUseTab && item.tab.browser !== this.browser))
                throw new Error('Invalid kept tab');
            const tabId = browserTabId(item.tab);
            if (seen.has(tabId))
                throw new Error('Duplicate kept tab');
            seen.add(tabId);
            return { tabId, status: item.status };
        });
        await this.browser.client.finalizeTabs(keep);
    }
}
export class OpenBrowserUseBrowserUser {
    browser;
    constructor(browser) {
        this.browser = browser;
    }
    async openTabs() {
        const result = await this.browser.getUserTabs();
        if (!Array.isArray(result))
            throw new Error('Browser returned an invalid user tab list');
        return result.map(item => {
            if (!isObject(item))
                throw new Error('Browser returned an invalid user tab');
            const id = String(browserTabId(item.id));
            for (const key of ['title', 'url', 'lastOpened', 'tabGroup'])
                if (item[key] !== undefined && item[key] !== null && typeof item[key] !== 'string')
                    throw new Error('Browser returned an invalid user tab');
            return { id, ...(typeof item.title === 'string' ? { title: item.title } : {}), ...(typeof item.url === 'string' ? { url: item.url } : {}), ...(typeof item.lastOpened === 'string' ? { lastOpened: item.lastOpened } : {}), ...(typeof item.tabGroup === 'string' ? { tabGroup: item.tabGroup } : {}) };
        });
    }
    async claimTab(tab) {
        const id = browserTabId(tab);
        if ((await this.browser.tabs.list()).some(item => item.id === String(id)))
            return this.browser.tab(id);
        return this.browser.claimTab(id);
    }
    async history(options = {}) {
        if (!options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => !['from', 'to', 'limit', 'query'].includes(key)))
            throw new Error('Invalid history options');
        const date = (value) => {
            if (value === undefined)
                return undefined;
            const parsed = types.isDate(value) ? value : typeof value === 'string' ? new Date(value) : new Date(NaN);
            if (!Number.isFinite(parsed.getTime()))
                throw new Error('Invalid history date');
            return parsed.toISOString();
        };
        const from = date(options.from), to = date(options.to);
        if ((from && to && from > to) || (options.limit !== undefined && (!Number.isSafeInteger(options.limit) || options.limit < 1)) || (options.query !== undefined && typeof options.query !== 'string'))
            throw new Error('Invalid history options');
        return this.browser.client.getUserHistory({ ...(from ? { from } : {}), ...(to ? { to } : {}), ...(options.limit !== undefined ? { limit: options.limit } : {}), ...(options.query !== undefined ? { query: options.query } : {}) });
    }
}
export class OpenBrowserUseCapabilities {
    browser;
    tab;
    constructor(browser, tab) {
        this.browser = browser;
        this.tab = tab;
    }
    async list() {
        const info = await this.browser.client.getInfo();
        if (!isObject(info) || !isObject(info.capabilities))
            throw new Error('Browser capability metadata is unavailable');
        const entries = info.capabilities[this.tab ? 'tab' : 'browser'];
        if (entries === undefined)
            return [];
        if (!Array.isArray(entries))
            throw new Error('Invalid browser capability metadata');
        const seen = new Set();
        const result = entries.map(item => {
            if (!isObject(item) || typeof item.id !== 'string' || !item.id || typeof item.description !== 'string' || seen.has(item.id))
                throw new Error('Invalid browser capability metadata');
            seen.add(item.id);
            return { id: item.id, description: item.description };
        });
        if (this.tab && result.length)
            await this.browser.tabs.get(this.tab.id);
        return result;
    }
    async get(id) {
        if (typeof id !== 'string' || !id)
            throw new Error('Invalid capability ID');
        if (!(await this.list()).some(item => item.id === id))
            throw new Error(`Capability unavailable: ${id}`);
        if (id === 'webmcp' && this.tab)
            return new OpenBrowserUseWebMcp(this.tab);
        throw new Error(`Capability is not implemented: ${id}`);
    }
}
export class OpenBrowserUseWebMcp {
    tab;
    constructor(tab) {
        this.tab = tab;
    }
    async listTools() {
        const result = await this.tab.browser.client.request('webmcp_list_tools', { tabId: this.tab.id });
        if (!isObject(result) || !Array.isArray(result.tools))
            throw new Error('Invalid WebMCP tool list');
        return result.tools.map(tool => {
            if (!isObject(tool) || typeof tool.name !== 'string' || !tool.name || typeof tool.registration_id !== 'string' || !tool.registration_id || !Object.hasOwn(tool, 'input_schema') || (tool.title !== undefined && typeof tool.title !== 'string') || (tool.description !== undefined && typeof tool.description !== 'string') || (tool.origin !== undefined && typeof tool.origin !== 'string') || (tool.pageUrl !== undefined && typeof tool.pageUrl !== 'string'))
                throw new Error('Invalid WebMCP tool descriptor');
            return tool;
        });
    }
    async invokeTool(tool, input, options = {}) {
        if (!tool || typeof tool.name !== 'string' || !tool.name.trim() || typeof tool.registration_id !== 'string' || !tool.registration_id.trim() || input === undefined || !options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => key !== 'timeoutMs'))
            throw new Error('Invalid WebMCP invocation');
        const timeoutMs = options.timeoutMs ?? 10_000;
        if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000)
            throw new Error('Invalid WebMCP timeout');
        const result = await this.tab.browser.client.request('webmcp_invoke_tool', { tabId: this.tab.id, tool_name: tool.name, registration_id: tool.registration_id, input, timeout_ms: timeoutMs, ...(typeof tool.title === 'string' ? { tool_title: tool.title } : {}), ...(typeof tool.description === 'string' ? { tool_description: tool.description } : {}) }, undefined, Math.max(this.tab.browser.client.timeoutMs, timeoutMs + 2000));
        if (!isObject(result) || !Object.hasOwn(result, 'result'))
            throw new Error('Invalid WebMCP invocation result');
        return result.result;
    }
}
export class OpenBrowserUseDialog {
    cdp;
    tabId;
    info;
    constructor(cdp, tabId, info) {
        this.cdp = cdp;
        this.tabId = tabId;
        this.info = info;
    }
    accept(promptText) { return this.cdp.resolveDialog(this.tabId, this.info.id, true, promptText); }
    dismiss() { return this.cdp.resolveDialog(this.tabId, this.info.id, false); }
}
export class OpenBrowserUseDownload {
    client;
    id;
    url;
    constructor(client, id, url = null) {
        this.client = client;
        this.id = id;
        this.url = url;
    }
    async path(timeoutMs) {
        const result = await this.client.downloadPath(this.id, timeoutMs);
        if (!isObject(result) || (typeof result.path !== "string" && result.path !== null))
            throw new Error("Browser returned an invalid download path");
        return result.path;
    }
}
export class OpenBrowserUseDownloadWait {
    client;
    result;
    constructor(client, result) {
        this.client = client;
        this.result = result;
    }
    async wait() {
        const result = await this.result;
        if (!isObject(result) || typeof result.downloadId !== "string" || !result.downloadId)
            throw new Error("Browser returned an invalid download ID");
        if (result.url !== undefined && result.url !== null && typeof result.url !== "string")
            throw new Error("Browser returned an invalid download URL");
        return new OpenBrowserUseDownload(this.client, result.downloadId, result.url ?? null);
    }
}
export class OpenBrowserUseFileChooser {
    client;
    id;
    multiple;
    #issued = false;
    constructor(client, id, multiple) {
        this.client = client;
        this.id = id;
        this.multiple = multiple;
    }
    isMultiple() { return this.multiple; }
    async setFiles(files) {
        const paths = typeof files === "string" ? [files] : Array.isArray(files) ? [...files] : [];
        if (!paths.length || paths.some(path => typeof path !== "string" || !isAbsolute(path)))
            throw new Error("File paths must be absolute");
        if (!this.multiple && paths.length > 1)
            throw new Error("File chooser does not accept multiple files");
        if (this.#issued)
            throw new Error("File chooser decision has already been issued; observe again");
        this.#issued = true;
        await this.client.setFileChooserFiles(this.id, paths);
    }
}
export class OpenBrowserUseFileChooserWait {
    client;
    result;
    #chooser;
    constructor(client, result) {
        this.client = client;
        this.result = result;
    }
    wait() {
        return this.#chooser ??= this.result.then(result => {
            if (!isObject(result) || typeof result.fileChooserId !== "string" || !result.fileChooserId || typeof result.isMultiple !== "boolean")
                throw new Error("Browser returned an invalid file chooser");
            return new OpenBrowserUseFileChooser(this.client, result.fileChooserId, result.isMultiple);
        });
    }
}
export class OpenBrowserUseTab {
    browser;
    id;
    playwright;
    capabilities;
    cua;
    dom_cua;
    dev;
    clipboard;
    #observation;
    #lastText;
    constructor(browser, id) {
        this.browser = browser;
        this.id = id;
        this.playwright = new OpenBrowserUseTabPlaywright(this);
        this.capabilities = new OpenBrowserUseCapabilities(browser, this);
        this.cua = new OpenBrowserUseTabCUA(this);
        this.dom_cua = browser.domCuaFor(this);
        this.dev = new OpenBrowserUseTabDev(this);
        this.clipboard = new OpenBrowserUseTabClipboard(this);
    }
    goto(url, options = {}) {
        this.#observation = undefined;
        return this.browser.cdp.navigate(this.id, url, options);
    }
    async title() { return (await this.browser.tabs.list()).find(tab => tab.id === String(this.id))?.title; }
    async url() { return (await this.browser.tabs.list()).find(tab => tab.id === String(this.id))?.url; }
    async back() { await this.moveHistory(-1); }
    async forward() { await this.moveHistory(1); }
    async bringToFront() {
        this.#observation = undefined;
        await this.browser.cdp.call(this.id, "Page.bringToFront");
    }
    async getPresentation() {
        const result = await this.browser.client.request("getTabPresentation", { tabId: this.id });
        if (!isObject(result) || !["chrome", "electron"].includes(String(result.backend)) || typeof result.selected !== "boolean" || (result.visible !== null && typeof result.visible !== "boolean") || (result.windowFocused !== null && typeof result.windowFocused !== "boolean"))
            throw new Error("Invalid tab presentation response");
        return result;
    }
    async moveHistory(direction) {
        const history = await this.browser.cdp.call(this.id, "Page.getNavigationHistory");
        if (!isObject(history) || !Number.isInteger(history.currentIndex) || !Array.isArray(history.entries))
            throw new Error("Browser navigation history is unavailable");
        const current = history.currentIndex;
        if (current < 0 || current >= history.entries.length)
            throw new Error("Browser navigation history is unavailable");
        const index = current + direction;
        if (index < 0 || index >= history.entries.length)
            return;
        const entry = history.entries[index];
        if (!isObject(entry) || !Number.isInteger(entry.id))
            throw new Error("Browser navigation history is unavailable");
        this.#observation = undefined;
        await this.browser.cdp.call(this.id, "Page.navigateToHistoryEntry", { entryId: entry.id });
    }
    async reload() {
        this.#observation = undefined;
        await this.browser.cdp.call(this.id, "Page.enable");
        const controller = new AbortController();
        const wait = this.browser.cdp.waitForLoadEvent(this.id, "load", defaultNavigationTimeoutMs, controller.signal);
        void wait.catch(() => { });
        try {
            await this.browser.cdp.call(this.id, "Page.reload");
            await wait;
        }
        finally {
            controller.abort();
        }
    }
    waitForLoadState(options = {}) {
        return this.browser.cdp.waitForLoadState(this.id, options);
    }
    async expectNavigation(action, options = {}) {
        if (typeof action !== "function")
            throw new Error("Navigation action must be a function");
        if (options.url !== undefined && typeof options.url !== "string" && !types.isRegExp(options.url))
            throw new Error("URL matcher must be a string or RegExp");
        const waitUntil = options.waitUntil ?? "load", timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
        assertSupportedLoadState(waitUntil);
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid navigation timeout");
        await this.browser.cdp.call(this.id, "Page.enable");
        const tree = await this.browser.cdp.call(this.id, "Page.getFrameTree");
        const root = isObject(tree) && isObject(tree.frameTree) && isObject(tree.frameTree.frame) ? tree.frameTree.frame.id : undefined;
        if (typeof root !== "string")
            throw new Error("Main frame is unavailable");
        const controller = new AbortController(), deadline = performance.now() + timeoutMs;
        const navigation = this.browser.cdp.waitForEvent(this.id, notification => {
            const event = cdpEventForTab(notification, this.id);
            if (!event || !isObject(event.params))
                return false;
            if (event.method === "Page.navigatedWithinDocument")
                return event.params.frameId === root;
            return event.method === "Page.frameNavigated" && isObject(event.params.frame) && event.params.frame.id === root && !event.params.frame.parentId;
        }, { timeoutMs, signal: controller.signal, timeoutMessage: `Timed out waiting for navigation after ${timeoutMs} ms` });
        let timer;
        try {
            const work = (async () => {
                const [result] = await Promise.all([Promise.resolve().then(action), navigation]);
                if (controller.signal.aborted)
                    throw new Error("Navigation wait cancelled");
                const remaining = Math.max(0, deadline - performance.now());
                if (options.url !== undefined)
                    await this.waitForURL(options.url, { waitUntil, timeoutMs: remaining });
                else
                    await this.waitForLoadState({ state: waitUntil, timeoutMs: remaining });
                return result;
            })();
            return await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out waiting for navigation after ${timeoutMs} ms`)), timeoutMs); })]);
        }
        finally {
            if (timer)
                clearTimeout(timer);
            controller.abort();
        }
    }
    async waitForURL(url, options = {}) {
        if (typeof url !== "string" && !types.isRegExp(url))
            throw new Error("URL matcher must be a string or RegExp");
        const matcher = typeof url === "string" ? url : new RegExp(url.source, url.flags);
        const waitUntil = options.waitUntil ?? "load";
        assertSupportedLoadState(waitUntil);
        const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid URL timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            let state = null;
            try {
                state = await this.browser.cdp.evaluate(this.id, "({ href: window.location.href, readyState: document.readyState })");
            }
            catch (error) {
                if (!(error instanceof Error) || !/Execution context was destroyed|Cannot find context with specified id/i.test(error.message))
                    throw error;
            }
            if (isObject(state) && typeof state.href === "string") {
                if (matcher instanceof RegExp)
                    matcher.lastIndex = 0;
                const matches = typeof matcher === "string" ? state.href === matcher : matcher.test(state.href);
                if (matches && documentStateMatches({ readyState: stringValue(state.readyState) }, waitUntil))
                    return;
            }
            const remaining = deadline - performance.now();
            if (remaining <= 0)
                throw new Error(`Timed out waiting for URL after ${timeoutMs} ms`);
            await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
        }
    }
    async domSnapshot() {
        const state = await this.observe({ includeFrames: true, includeText: true });
        const text = state.text.replace(/^([ \t]*)\[\d+\] /gm, "$1");
        return [text, ...(state.truncated ? ["[Snapshot truncated]"] : []), ...(state.unavailableFrames?.length ? [`[${state.unavailableFrames.length} frame(s) unavailable]`] : [])].filter(Boolean).join("\n");
    }
    getAXState() {
        return this.browser.cdp.call(this.id, "Accessibility.getFullAXTree");
    }
    async observe(options = {}) {
        this.#observation = undefined;
        const documentId = await this.documentId();
        const tree = await this.getAXState();
        const nodes = interactiveNodes(tree, 0, options.includeText);
        const unindexedText = options.includeText ? unindexedTextAncestors(tree).map(backendNodeId => ({ backendNodeId })) : [];
        const valueBudget = { remaining: 8_000, truncated: false };
        if (options.includeValues)
            await this.readAXValues(tree, nodes, valueBudget);
        let full = options.includeFrames ? { text: "", truncated: false } : renderAXState(tree, nodes);
        const unavailableFrames = [];
        let observedFrames;
        let crossProcess = false;
        if (options.includeFrames) {
            crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
            const frames = await this.frameTree();
            observedFrames = frames;
            const trees = new Map();
            trees.set(frames[0].id, { tree, nodes: [...nodes] });
            for (const frame of frames.slice(1)) {
                try {
                    const childTree = await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: frame.id }, { sessionId: frame.sessionId });
                    if (options.includeText)
                        unindexedText.push(...unindexedTextAncestors(childTree).map(backendNodeId => ({ backendNodeId, frameId: frame.id, frameChain: frameAncestry(frame, frames) })));
                    const childNodes = interactiveNodes(childTree, nodes.length, options.includeText).map(node => ({ ...node, frameId: frame.id, frameChain: frameAncestry(frame, frames) }));
                    if (options.includeValues)
                        await this.readAXValues(childTree, childNodes, valueBudget, frame.sessionId);
                    nodes.push(...childNodes);
                    let owner;
                    try {
                        const parent = frames.find(item => item.id === frame.parentId);
                        const result = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: frame.id }, { sessionId: parent?.sessionId });
                        if (isObject(result) && typeof result.backendNodeId === "number")
                            owner = result.backendNodeId;
                    }
                    catch { /* A readable frame can still be shown without its position. */ }
                    trees.set(frame.id, { tree: childTree, nodes: childNodes, owner });
                }
                catch {
                    unavailableFrames.push(frame.id);
                }
            }
            const attachments = new Map();
            const unplaced = [];
            for (const frame of [...frames].reverse()) {
                const entry = trees.get(frame.id);
                if (!entry)
                    continue;
                const rendered = renderAXState(entry.tree, entry.nodes, attachments.get(frame.id));
                if (!frame.parentId) {
                    full = rendered;
                    continue;
                }
                const child = { url: frame.url, ...rendered };
                if (entry.owner === undefined || !trees.has(frame.parentId)) {
                    unplaced.unshift(child);
                    continue;
                }
                const parent = attachments.get(frame.parentId) ?? new Map();
                const siblings = parent.get(entry.owner) ?? [];
                siblings.unshift(child);
                parent.set(entry.owner, siblings);
                attachments.set(frame.parentId, parent);
            }
            if (unplaced.length)
                full = appendUnplacedFrames(full, unplaced);
            const current = await this.frameTree();
            if (JSON.stringify(current) !== JSON.stringify(frames))
                throw new RetryablePreflightError("Frame tree changed during observation; observe again");
        }
        if (documentId !== await this.documentId())
            throw new RetryablePreflightError("Page changed during observation; observe again");
        const id = randomUUID();
        this.#observation = { id, documentId, nodes, unindexedText, ...(observedFrames ? { frames: observedFrames } : {}), guards: new Map() };
        const previous = this.#lastText;
        const useDiff = options.diff === true && previous?.documentId === documentId && previous.includeFrames === !!options.includeFrames && previous.includeValues === !!options.includeValues && previous.includeText === !!options.includeText && !previous.truncated && !full.truncated && !valueBudget.truncated && !unavailableFrames.length;
        const output = useDiff ? diffAXState(previous.text, full.text) : full;
        this.#lastText = (output.truncated && useDiff) || unavailableFrames.length || valueBudget.truncated ? undefined : { documentId, includeFrames: !!options.includeFrames, includeValues: !!options.includeValues, includeText: !!options.includeText, ...full };
        return { snapshotId: id, nodes: nodes.map(({ index, role, name, frameId, level, checked, disabled, pressed, selected, expanded, placeholder, placeholderTruncated, altText, altTextTruncated, value, valueRedacted, valueUnavailable, valueTruncated }) => ({ index, role, name, ...(frameId ? { frameId } : {}), ...(level !== undefined ? { level } : {}), ...(checked !== undefined ? { checked } : {}), ...(disabled ? { disabled: true } : {}), ...(pressed !== undefined ? { pressed } : {}), ...(selected !== undefined ? { selected } : {}), ...(expanded !== undefined ? { expanded } : {}), ...(placeholder !== undefined ? { placeholder } : {}), ...(placeholderTruncated ? { placeholderTruncated } : {}), ...(altText !== undefined ? { altText } : {}), ...(altTextTruncated ? { altTextTruncated } : {}), ...(value !== undefined ? { value } : {}), ...(valueRedacted ? { valueRedacted } : {}), ...(valueUnavailable ? { valueUnavailable } : {}), ...(valueTruncated ? { valueTruncated } : {}) })), ...output, textMode: useDiff ? "diff" : "full", ...(options.includeFrames ? { frameCoverage: crossProcess ? "cross-process" : "same-process", unavailableFrames } : {}), ...(options.includeValues ? { valuesTruncated: valueBudget.truncated } : {}) };
    }
    async readAXValues(tree, nodes, budget, sessionId) {
        if (!isObject(tree) || !Array.isArray(tree.nodes))
            throw new Error("Invalid accessibility tree");
        const byId = new Map(tree.nodes.filter(isObject).map(node => [node.backendDOMNodeId, node]));
        for (const node of nodes) {
            if (!["textbox", "searchbox", "combobox", "slider", "spinbutton", "Date", "DateTime", "InputTime"].includes(node.role))
                continue;
            const ax = byId.get(node.backendNodeId);
            const value = isObject(ax?.value) ? ax.value.value : undefined;
            if (typeof value !== "string" && (typeof value !== "number" || !Number.isFinite(value)))
                continue;
            {
                let objectId;
                try {
                    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId }, { sessionId });
                    const id = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                    if (typeof id !== "string")
                        throw new Error("Unresolved field");
                    objectId = id;
                    const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true,
                        functionDeclaration: `function() { if (this instanceof HTMLInputElement) return this.type === 'password' ? 'redacted' : 'visible'; if (this instanceof HTMLTextAreaElement || this instanceof HTMLSelectElement || this.isContentEditable || (this instanceof HTMLElement && ['slider','spinbutton'].includes(this.getAttribute('role')))) return 'visible'; return 'unknown'; }` }, { sessionId });
                    const kind = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                    if (kind === "redacted") {
                        node.valueRedacted = true;
                        continue;
                    }
                    if (kind !== "visible") {
                        node.valueUnavailable = true;
                        continue;
                    }
                }
                catch {
                    node.valueUnavailable = true;
                    continue;
                }
                finally {
                    if (objectId)
                        await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
                }
            }
            const text = String(value), limit = Math.min(512, budget.remaining);
            if (text.length > limit) {
                node.valueTruncated = true;
                budget.truncated = true;
            }
            if (limit > 0 || !text.length)
                node.value = typeof value === "number" ? value : text.slice(0, limit);
            budget.remaining -= Math.min(text.length, limit);
        }
    }
    /** @internal */
    currentObservation(snapshotId) {
        const observation = this.#observation;
        if (!observation || observation.id !== snapshotId)
            throw new RetryablePreflightError("Observation is stale; observe again");
        return observation;
    }
    /** @internal */
    bindLocatorScope(snapshotId, targetIndex, scopeIndices, filters, framePath, css, role) {
        const observation = this.#observation;
        if (!observation || observation.id !== snapshotId)
            throw new RetryablePreflightError("Observation is stale; observe again");
        observation.guards.set(targetIndex, { scopes: [...scopeIndices], filters: filters.map(item => ({ index: item.index, filters: item.filters.map(filter => ({ ...filter })) })), ...(framePath ? { framePath: [...framePath] } : {}), ...(css ? { css } : {}), ...(role ? { role } : {}) });
    }
    /** @internal */
    async resolveFramePath(path, snapshotId, expectedFrames) {
        const frames = await this.frameTree();
        const checkSnapshot = () => { if ((snapshotId && (!this.#observation || this.#observation.id !== snapshotId || JSON.stringify(this.#observation.frames) !== JSON.stringify(frames))) || (expectedFrames && JSON.stringify(expectedFrames) !== JSON.stringify(frames)))
            throw new RetryablePreflightError("Frame tree changed; observe again"); };
        checkSnapshot();
        let parent = frames[0];
        for (const selector of path) {
            const matched = [];
            const children = frames.filter(item => item.parentId === parent.id);
            const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: parent.id, worldName: "open-browser-use-selector" }, { sessionId: parent.sessionId });
            const contextId = isObject(world) ? world.executionContextId : undefined;
            if (typeof contextId !== "number" || !Number.isSafeInteger(contextId))
                throw new RetryablePreflightError("Frame selector context is unavailable; observe again");
            if (!children.length) {
                const result = await this.browser.cdp.call(this.id, "Runtime.evaluate", { contextId, returnByValue: true, expression: `(() => { try { document.createElement('iframe').matches(${JSON.stringify(selector)}); return true; } catch { return false; } })()` }, { sessionId: parent.sessionId });
                const valid = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                if (valid === false)
                    throw new Error("Invalid frame selector");
                if (valid !== true)
                    throw new RetryablePreflightError("Frame selector is unavailable; observe again");
            }
            for (const frame of children) {
                const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: frame.id }, { sessionId: parent.sessionId });
                if (!isObject(owner) || typeof owner.backendNodeId !== "number")
                    throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId, executionContextId: contextId }, { sessionId: parent.sessionId });
                const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                try {
                    const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: selector }], functionDeclaration: `function(selector) { if (!this.isConnected) return null; return this.matches(selector); }` }, { sessionId: parent.sessionId });
                    if (isObject(result) && result.exceptionDetails)
                        throw new Error("Invalid frame selector");
                    const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                    if (typeof value !== "boolean")
                        throw new RetryablePreflightError("Frame owner changed; observe again");
                    if (value)
                        matched.push(frame);
                }
                finally {
                    await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId: parent.sessionId }).catch(() => { });
                }
            }
            if (matched.length > 1)
                throw new Error(`Frame selector matched ${matched.length} frames; expected exactly one`);
            if (!matched.length) {
                if (JSON.stringify(await this.frameTree()) !== JSON.stringify(frames))
                    throw new RetryablePreflightError("Frame tree changed; observe again");
                checkSnapshot();
                return null;
            }
            parent = matched[0];
        }
        if (JSON.stringify(await this.frameTree()) !== JSON.stringify(frames))
            throw new RetryablePreflightError("Frame tree changed; observe again");
        checkSnapshot();
        return parent.id;
    }
    /** @internal */
    async queryCss(step, framePath, scopes = [], semanticScope, base, explicitFrame) {
        const selector = step.selector;
        if (typeof selector !== "string" || !selector.trim() || selector.length > 4096)
            throw new Error("Invalid CSS selector");
        const documentId = await this.documentId();
        const crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
        const frames = await this.frameTree();
        if (framePath && !crossProcess)
            throw new Error("Frame routing is unavailable");
        const baseNode = base?.observation.nodes.find(node => node.index === base.index);
        if (base && (!baseNode || !base.observation.frames || semanticScope))
            throw new RetryablePreflightError("Filter scope is unavailable; observe again");
        const semantic = semanticScope ? await semanticScope.detachedRoots() : base && baseNode ? { documentId: base.observation.documentId, frames: base.observation.frames, roots: [{ backendNodeId: baseNode.backendNodeId, frameId: baseNode.frameId ?? "" }] } : undefined;
        if (semantic && (semantic.documentId !== documentId || JSON.stringify(semantic.frames) !== JSON.stringify(frames)))
            throw new RetryablePreflightError("Semantic scope changed; observe again");
        if (semantic && semantic.roots.length > 1000)
            throw new Error("Semantic scope matched more than 1000 elements");
        const semanticFrames = new Set(semantic?.roots.map(root => root.frameId || frames[0].id));
        if (semanticFrames.size > 1)
            throw new Error("Semantic CSS scope spans multiple frames; choose one frame");
        const semanticFrame = semanticFrames.values().next().value;
        if (explicitFrame && (framePath || semanticScope || base))
            throw new Error("Invalid explicit frame scope");
        const frameId = explicitFrame ?? (framePath ? await this.resolveFramePath(framePath) : semanticFrame ?? frames[0].id);
        if (semanticFrame && frameId && semanticFrame !== frameId)
            throw new Error("Semantic scope and CSS frame differ");
        if (!frameId) {
            if (await this.documentId() !== documentId || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames))
                throw new RetryablePreflightError("Frame tree changed; observe again");
            return { step, scopes, scopeIds: [], framePath, ...(explicitFrame ? { frameId: explicitFrame } : {}), ...(semanticScope && semantic ? { semantic: { scope: semanticScope, roots: semantic.roots } } : {}), frame: null, frames, documentId, ids: [] };
        }
        const frame = frames.find(item => item.id === frameId);
        if (!frame)
            throw new RetryablePreflightError("Frame tree changed; observe again");
        const needsVisibility = (steps) => steps.some(step => (step.union ? step.union.some(needsVisibility) : false) || [...(step.before ?? []), ...(step.after ?? [])].some(filter => filter.visible !== undefined || (filter.has ? needsVisibility(filter.has) : false) || (filter.hasNot ? needsVisibility(filter.hasNot) : false) || (filter.and ? needsVisibility(filter.and) : false)));
        const checkVisibility = needsVisibility([...scopes, step]);
        const frameVisible = checkVisibility ? await this.cssFrameVisible(frame, frames) : true;
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        const contextId = isObject(world) ? world.executionContextId : undefined;
        if (typeof contextId !== "number" || !Number.isSafeInteger(contextId))
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const expression = `(() => {
      const steps=${JSON.stringify([...scopes, step])}, output=[], frameVisible=${JSON.stringify(frameVisible)}; let total=0, visited=0;
      const guarded=steps.some(step=>step.union || [...(step.before || []),...(step.after || [])].some(filter=>filter.has || filter.hasNot || filter.and));
      const normalize=text=>text.replace(/\\s+/g,' ').trim();
      const textOf=element=>{let text='',stack=[element];while(stack.length){const node=stack.pop();if(node.nodeType===Node.TEXT_NODE){text+=node.nodeValue || '';if(text.length>30000)throw new Error('Filter text exceeds the 30000 character limit');continue;}if(node.nodeType===Node.ELEMENT_NODE && ['SCRIPT','STYLE','NOSCRIPT'].includes(node.tagName))continue;if(node.shadowRoot)stack.push(node.shadowRoot);const children=node.childNodes;for(let j=children.length-1;j>=0;j--)stack.push(children[j]);}return normalize(text);};
      const apply=(items,filters,initial)=>{if(!filters?.length)return items;const intersections=new Map();return items.filter(element=>filters.every(filter=>{
        if(filter.visible!==undefined){const r=element.getBoundingClientRect(),visible=frameVisible && getComputedStyle(element).visibility==='visible' && r.width>0 && r.height>0;if(visible!==filter.visible)return false;}
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
        const rootObjects = [];
        let evaluated;
        try {
            for (const root of semantic?.roots ?? []) {
                const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: root.backendNodeId, executionContextId: contextId }, { sessionId });
                const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Semantic scope is unavailable; observe again");
                rootObjects.push(objectId);
            }
            if (rootObjects.length)
                evaluated = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId: rootObjects[0], arguments: rootObjects.slice(1).map(objectId => ({ objectId })), returnByValue: false, functionDeclaration: `function(...others) { const roots=[this,...others].filter(root=>typeof root.querySelectorAll==='function'); return ${expression}; }` }, { sessionId });
            else
                evaluated = await this.browser.cdp.call(this.id, "Runtime.evaluate", { expression, contextId, returnByValue: false }, { sessionId });
        }
        finally {
            for (const objectId of rootObjects)
                await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
        if (isObject(evaluated) && evaluated.exceptionDetails) {
            const details = isObject(evaluated.exceptionDetails) && isObject(evaluated.exceptionDetails.exception) ? evaluated.exceptionDetails.exception.description : undefined;
            if (typeof details === "string" && details.includes("Selector matched more than 1000 elements"))
                throw new Error("Selector matched more than 1000 elements");
            if (typeof details === "string" && details.includes("Filter text exceeds the 30000 character limit"))
                throw new Error("Filter text exceeds the 30000 character limit");
            if (typeof details === "string" && details.includes("Locator filter search exceeds the 100000 element limit"))
                throw new Error("Locator filter search exceeds the 100000 element limit");
            throw new Error("Invalid CSS selector");
        }
        const arrayId = isObject(evaluated) && isObject(evaluated.result) ? evaluated.result.objectId : undefined;
        if (typeof arrayId !== "string")
            throw new RetryablePreflightError("Selector result is unavailable; observe again");
        const objectIds = [];
        try {
            const properties = await this.browser.cdp.call(this.id, "Runtime.getProperties", { objectId: arrayId, ownProperties: true }, { sessionId });
            if (!isObject(properties) || !Array.isArray(properties.result))
                throw new RetryablePreflightError("Selector result is unavailable; observe again");
            const entries = properties.result.filter(isObject).filter(item => typeof item.name === "string" && /^(0|[1-9][0-9]*)$/.test(item.name)).sort((a, b) => Number(a.name) - Number(b.name));
            for (const item of entries)
                if (isObject(item.value) && typeof item.value.objectId === "string")
                    objectIds.push(item.value.objectId);
            if (objectIds.length > 1000)
                throw new Error("Selector matched more than 1000 elements");
            const stages = [];
            for (const item of entries) {
                if (!isObject(item.value))
                    throw new RetryablePreflightError("Selector result is unavailable; observe again");
                if (typeof item.value.value === "number" && item.value.value === stages.length && stages.length <= scopes.length) {
                    stages.push([]);
                    continue;
                }
                if (typeof item.value.objectId !== "string" || !stages.length)
                    throw new RetryablePreflightError("Selector result is unavailable; observe again");
                const result = await this.browser.cdp.call(this.id, "DOM.describeNode", { objectId: item.value.objectId }, { sessionId });
                const node = isObject(result) && isObject(result.node) ? result.node : undefined;
                if (!node || typeof node.backendNodeId !== "number")
                    throw new RetryablePreflightError("Selector target changed; observe again");
                stages[stages.length - 1].push(node.backendNodeId);
            }
            if (checkVisibility && await this.cssFrameVisible(frame, frames) !== frameVisible)
                throw new RetryablePreflightError("Frame visibility changed; observe again");
            if (stages.length !== scopes.length + 1 || await this.documentId() !== documentId || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames))
                throw new RetryablePreflightError("Frame tree changed; observe again");
            return { step, scopes, scopeIds: stages.slice(0, -1), framePath, ...(explicitFrame ? { frameId: explicitFrame } : {}), ...(semanticScope && semantic ? { semantic: { scope: semanticScope, roots: semantic.roots } } : {}), frame, frames, documentId, ids: stages[stages.length - 1] };
        }
        finally {
            for (const objectId of objectIds)
                await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId: arrayId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async domFrames() {
        if (!await this.browser.cdp.enableFrameSessions(this.id))
            throw new Error("Frame routing is unavailable");
        return this.frameTree();
    }
    /** @internal */
    async domFrameInViewport(frame, frames) { return this.cssFrameVisible(frame, frames, true); }
    /** @internal */
    async domFrameClip(frame, frames) {
        const metrics = await this.browser.cdp.call(this.id, 'Page.getLayoutMetrics');
        const viewport = isObject(metrics) && isObject(metrics.cssVisualViewport) ? metrics.cssVisualViewport : null;
        if (!viewport || typeof viewport.clientWidth !== 'number' || typeof viewport.clientHeight !== 'number')
            throw new RetryablePreflightError('Viewport unavailable; observe again');
        let clip = { left: 0, top: 0, right: viewport.clientWidth, bottom: viewport.clientHeight };
        const chain = frameAncestry(frame, frames);
        for (let i = chain.length - 1; i >= 0; i--) {
            const child = chain[i], sessionId = chain[i + 1]?.sessionId;
            const owner = await this.browser.cdp.call(this.id, 'DOM.getFrameOwner', { frameId: child.id }, { sessionId });
            if (!isObject(owner) || typeof owner.backendNodeId !== 'number')
                throw new RetryablePreflightError('Frame owner unavailable; observe again');
            const world = await this.browser.cdp.call(this.id, 'Page.createIsolatedWorld', { frameId: child.parentId, worldName: 'open-browser-use-selector' }, { sessionId });
            if (!isObject(world) || typeof world.executionContextId !== 'number')
                throw new RetryablePreflightError('Frame context unavailable; observe again');
            const resolved = await this.browser.cdp.call(this.id, 'DOM.resolveNode', { backendNodeId: owner.backendNodeId, executionContextId: world.executionContextId }, { sessionId });
            const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
            if (typeof objectId !== 'string')
                throw new RetryablePreflightError('Frame owner unavailable; observe again');
            try {
                const result = await this.browser.cdp.call(this.id, 'Runtime.callFunctionOn', { objectId, returnByValue: true, functionDeclaration: `function(){if(!this.isConnected)return null;for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)){const t=getComputedStyle(el).transform;if(t!=='none'){const m=new DOMMatrixReadOnly(t);if(!m.is2D || m.b!==0 || m.c!==0 || m.a<=0 || m.d<=0)return {unsupported:true}}}const r=this.getBoundingClientRect();if(!this.offsetWidth || !this.offsetHeight)return null;const sx=r.width/this.offsetWidth,sy=r.height/this.offsetHeight;return {x:r.left+this.clientLeft*sx,y:r.top+this.clientTop*sy,width:this.clientWidth,height:this.clientHeight,sx,sy}}` }, { sessionId });
                const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                if (isObject(value) && value.unsupported === true)
                    throw new Error('DOM snapshot cannot map a rotated or skewed frame');
                if (!isObject(value) || !['x', 'y', 'width', 'height', 'sx', 'sy'].every(key => typeof value[key] === 'number' && Number.isFinite(value[key])))
                    throw new RetryablePreflightError('Frame geometry changed; observe again');
                const { x, y, width, height, sx, sy } = value;
                if (sx <= 0 || sy <= 0 || width <= 0 || height <= 0)
                    return null;
                clip = { left: Math.max(0, (clip.left - x) / sx), top: Math.max(0, (clip.top - y) / sy), right: Math.min(width, (clip.right - x) / sx), bottom: Math.min(height, (clip.bottom - y) / sy) };
                if (clip.right <= clip.left || clip.bottom <= clip.top)
                    return null;
            }
            finally {
                await this.browser.cdp.call(this.id, 'Runtime.releaseObject', { objectId }, { sessionId }).catch(() => { });
            }
        }
        return clip;
    }
    /** @internal */
    async domFramePoint(snapshot, point) {
        if (!snapshot.frame)
            throw new RetryablePreflightError("Frame is unavailable; observe again");
        const chain = frameAncestry(snapshot.frame, snapshot.frames), sessionId = snapshot.frame.sessionId;
        let inputPoint = point;
        for (let i = 0; i < chain.length; i++) {
            const ownerSession = chain[i + 1]?.sessionId;
            point = await this.framePoint(chain[i].id, point.x, point.y, ownerSession);
            if (ownerSession === sessionId)
                inputPoint = point;
        }
        await this.validateFrames(chain);
        return { point, inputPoint };
    }
    async cssFrameVisible(frame, frames, viewport = false) {
        const chain = frameAncestry(frame, frames);
        for (let i = 0; i < chain.length; i++) {
            const child = chain[i], ownerSession = chain[i + 1]?.sessionId;
            const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: child.id }, { sessionId: ownerSession });
            if (!isObject(owner) || typeof owner.backendNodeId !== "number")
                throw new RetryablePreflightError("Frame owner is unavailable; observe again");
            const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: child.parentId, worldName: "open-browser-use-selector" }, { sessionId: ownerSession });
            if (!isObject(world) || typeof world.executionContextId !== "number")
                throw new RetryablePreflightError("Selector context is unavailable; observe again");
            const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId, executionContextId: world.executionContextId }, { sessionId: ownerSession });
            const ownerId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
            if (typeof ownerId !== "string")
                throw new RetryablePreflightError("Frame owner is unavailable; observe again");
            try {
                const state = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId: ownerId, returnByValue: true, arguments: [{ value: viewport }], functionDeclaration: `function(viewport) { if(!this.isConnected)return null;const r=this.getBoundingClientRect();return getComputedStyle(this).visibility==='visible' && r.width>0 && r.height>0 && (!viewport || (r.right>0 && r.bottom>0 && r.left<innerWidth && r.top<innerHeight)); }` }, { sessionId: ownerSession });
                const value = isObject(state) && isObject(state.result) ? state.result.value : undefined;
                if (typeof value !== "boolean")
                    throw new RetryablePreflightError("Frame owner changed; observe again");
                if (!value)
                    return false;
            }
            finally {
                await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId: ownerId }, { sessionId: ownerSession }).catch(() => { });
            }
        }
        return true;
    }
    /** @internal */
    async readCss(snapshot, id, mode, attribute = "") {
        const frame = snapshot.frame;
        if (!frame || !snapshot.ids.includes(id))
            throw new RetryablePreflightError("Selector target changed; observe again");
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        const contextId = isObject(world) ? world.executionContextId : undefined;
        if (typeof contextId !== "number")
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: id, executionContextId: contextId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Selector target is unavailable; observe again");
        try {
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: mode }, { value: attribute }], functionDeclaration: `function(mode,name) { if (!this.isConnected) return null; if(mode==='visible'){const r=this.getBoundingClientRect();return {value:getComputedStyle(this).visibility==='visible' && r.width>0 && r.height>0};} if(mode==='checked'){if(this instanceof HTMLInputElement && ['checkbox','radio'].includes(this.type))return {value:this.indeterminate ? null : this.checked};const role=(this.getAttribute('role') || '').trim().split(/\\s+/)[0], checked=this.getAttribute('aria-checked');if(['checkbox','radio','switch','menuitemcheckbox','menuitemradio'].includes(role) && ['true','false'].includes(checked))return {value:checked==='true'};return {value:null};} if(mode==='enabled'){for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true')return {value:false};return {value:true};} const value=mode === 'attribute' ? this.getAttribute(name) : this[mode]; return {value:typeof value === 'string' ? value.slice(0,30001) : null}; }` }, { sessionId });
            const payload = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (isObject(payload) && mode === "checked" && payload.value === null)
                throw new Error("Target does not have a binary checked state");
            if (!isObject(payload) || (["visible", "enabled", "checked"].includes(mode) ? typeof payload.value !== "boolean" : typeof payload.value !== "string" && payload.value !== null))
                throw new RetryablePreflightError("Selector target is unavailable; observe again");
            if (typeof payload.value === "string" && payload.value.length > 30_000)
                throw new Error("Locator value exceeds the 30000 character limit");
            const frameVisible = mode === "visible" && payload.value === true ? await this.cssFrameVisible(frame, snapshot.frames) : true;
            const fresh = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
            if (fresh.documentId !== snapshot.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids) !== JSON.stringify(snapshot.ids))
                throw new RetryablePreflightError("Selector target changed; observe again");
            return mode === "visible" && payload.value === true ? frameVisible : payload.value;
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async actCss(snapshot, id, hover, key, text, doubleClick = false, checked, selection, append = false, mouse = { button: "left", buttons: 1, modifiers: 0 }, domIdentity, domConnectionGeneration) {
        if (key !== undefined)
            this.parseKey(key);
        const frame = snapshot.frame;
        if (!frame || !snapshot.ids.includes(id))
            throw new RetryablePreflightError("Selector target changed; observe again");
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        const contextId = isObject(world) ? world.executionContextId : undefined;
        if (typeof contextId !== "number")
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: id, executionContextId: contextId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Selector target is unavailable; observe again");
        let inputIssued = false;
        try {
            const chain = frameAncestry(frame, snapshot.frames);
            const measure = async () => {
                const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: hover }], functionDeclaration: `function(allowDisabled) {
          if (!this.isConnected) return null;
          if (!allowDisabled) for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return null;
          this.scrollIntoView({block:'center',inline:'center'});
          const r=this.getBoundingClientRect(), x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2, y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;
          if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
          let target=this, root=target.getRootNode();
          while (true) { const hit=root.elementFromPoint(x,y); if (!hit || (hit!==target && !target.contains(hit))) return null; if (!(root instanceof ShadowRoot)) return {x,y,width:r.width,height:r.height}; target=root.host; root=target.getRootNode(); }
        }` }, { sessionId });
                const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                if (!isObject(value) || ![value.x, value.y, value.width, value.height].every(v => typeof v === "number" && Number.isFinite(v)) || value.width <= 0 || value.height <= 0)
                    throw new RetryablePreflightError("Target is hidden, disabled, or covered; observe again");
                const geometry = { x: value.x, y: value.y, width: value.width, height: value.height };
                let point = { x: geometry.x, y: geometry.y }, inputPoint = point;
                for (let i = 0; i < chain.length; i++) {
                    const ownerSession = chain[i + 1]?.sessionId;
                    point = await this.framePoint(chain[i].id, point.x, point.y, ownerSession);
                    if (ownerSession === sessionId)
                        inputPoint = point;
                }
                await this.validateFrames(chain);
                if (await this.documentId() !== snapshot.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                return { geometry, point, inputPoint };
            };
            const first = await measure();
            await new Promise(resolve => setTimeout(resolve, 75));
            const second = await measure();
            const moving = (a, b) => Math.abs(a - b) > 0.25;
            if (moving(first.geometry.x, second.geometry.x) || moving(first.geometry.y, second.geometry.y) || moving(first.geometry.width, second.geometry.width) || moving(first.geometry.height, second.geometry.height) || moving(first.point.x, second.point.x) || moving(first.point.y, second.point.y))
                throw new RetryablePreflightError("Target is moving; observe again");
            const fresh = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
            if (fresh.documentId !== snapshot.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids) !== JSON.stringify(snapshot.ids))
                throw new RetryablePreflightError("Selector target changed; observe again");
            const checkedState = async () => {
                const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, functionDeclaration: `function() {
          if (!this.isConnected) return null;
          if (this instanceof HTMLInputElement && ['checkbox','radio'].includes(this.type)) return {value:this.indeterminate ? null : this.checked,radio:this.type==='radio'};
          const role=(this.getAttribute('role') || '').trim().split(/\\s+/)[0], checked=this.getAttribute('aria-checked');
          if (!['checkbox','radio','switch','menuitemcheckbox','menuitemradio'].includes(role) || !['true','false'].includes(checked)) return {value:null,radio:false};
          return {value:checked==='true',radio:role==='radio' || role==='menuitemradio'};
        }` }, { sessionId });
                const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                if (!isObject(value) || typeof value.value !== "boolean" || typeof value.radio !== "boolean")
                    throw new Error("Target does not have a binary checked state");
                return { value: value.value, radio: value.radio };
            };
            if (checked !== undefined) {
                const state = await checkedState();
                const latest = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                if (latest.documentId !== snapshot.documentId || JSON.stringify(latest.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids) !== JSON.stringify(snapshot.ids))
                    throw new RetryablePreflightError("Selector target changed; observe again");
                const current = await checkedState();
                if (current.value !== state.value || current.radio !== state.radio)
                    throw new RetryablePreflightError("Checked state changed; observe again");
                if (current.value === checked)
                    return;
                if (!checked && current.radio)
                    throw new Error("A selected radio cannot be unchecked directly");
            }
            if (selection !== undefined) {
                const inspected = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: selection }], functionDeclaration: `function(specs) {
          if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.matches(':disabled') || this.getAttribute('aria-disabled')==='true') return {status:'not-select'};
          if (!this.multiple && specs.length>1) return {status:'multiple'};
          const options=Array.from(this.options),chosen=[];
          for(const spec of specs) {
            const hits=options.map((option,index)=>({option,index})).filter(({option})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));
            if(!hits.length)return {status:'missing'};
            if(hits.length>1 || chosen.some(item=>item.index===hits[0].index))return {status:'ambiguous'};
            chosen.push({index:hits[0].index,value:hits[0].option.value,label:hits[0].option.label});
          }
          return {status:'ok',chosen};
        }` }, { sessionId });
                const found = isObject(inspected) && isObject(inspected.result) ? inspected.result.value : null;
                if (!isObject(found) || typeof found.status !== "string")
                    throw new Error("Invalid select options result");
                if (found.status === 'missing')
                    throw new RetryablePreflightError("Requested select option is unavailable");
                if (found.status === 'ambiguous')
                    throw new Error("Requested select option is ambiguous");
                if (found.status === 'multiple')
                    throw new Error("Multiple options require a multiple select");
                if (found.status !== 'ok' || !Array.isArray(found.chosen))
                    throw new Error("Target is not an enabled native select");
                const latest = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                if (latest.documentId !== snapshot.documentId || JSON.stringify(latest.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids) !== JSON.stringify(snapshot.ids))
                    throw new RetryablePreflightError("Selector target changed; observe again");
                this.#observation = undefined;
                inputIssued = true;
                const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: found.chosen }, { value: selection }], functionDeclaration: `function(chosen,specs) {
          if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.matches(':disabled') || this.getAttribute('aria-disabled')==='true' || (!this.multiple && chosen.length>1)) return null;
          for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true') return null;
          const options=Array.from(this.options);
          for(let i=0;i<specs.length;i++) {const spec=specs[i],hits=options.map((option,index)=>({option,index})).filter(({option})=>!option.disabled && !(option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled) && (spec.either ? option.value===spec.value || option.label===spec.label : (spec.value===undefined || option.value===spec.value) && (spec.label===undefined || option.label===spec.label)));if(hits.length!==1 || hits[0].index!==chosen[i]?.index)return null;}
          if(chosen.some(item=>{const o=options[item.index];return !o || o.value!==item.value || o.label!==item.label || o.disabled || (o.parentElement instanceof HTMLOptGroupElement && o.parentElement.disabled)}))return null;
          if(!this.multiple && !chosen.length)this.selectedIndex=-1;
          else {const indices=new Set(chosen.map(item=>item.index));for(let i=0;i<options.length;i++)options[i].selected=indices.has(i);}
          this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));this.dispatchEvent(new Event('change',{bubbles:true}));
          return this.isConnected ? Array.from(this.selectedOptions,option=>option.value) : null;
        }` }, { sessionId });
                const selected = isObject(applied) && isObject(applied.result) ? applied.result.value : null;
                const expected = found.chosen.map(item => isObject(item) ? item.value : null);
                if (!Array.isArray(selected) || selected.some(value => typeof value !== "string") || JSON.stringify([...selected].sort()) !== JSON.stringify([...expected].sort()))
                    throw new Error("Select did not retain the requested options");
                return selected;
            }
            if (text !== undefined) {
                const editable = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: text }, { value: append }], functionDeclaration: `function(value,append) {
          if (!this.isConnected || this.disabled || this.readOnly || this.getAttribute('aria-readonly') === 'true') return 'unsupported';
          if (this instanceof HTMLInputElement && ['date','time','month','week','datetime-local'].includes(this.type)) { if(append)return 'temporal-append';const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;return probe.value===value ? 'temporal' : 'invalid'; }
          if (!append && this instanceof HTMLInputElement && this.type==='number') {const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;if(probe.value!==value)return 'invalid-number';}
          return this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type)) ? 'text' : 'unsupported';
        }` }, { sessionId });
                const status = isObject(editable) && isObject(editable.result) ? editable.result.value : undefined;
                if (status === 'temporal-append')
                    throw new Error("Use fill for date and time inputs");
                if (status === 'invalid')
                    throw new Error("Invalid date or time value");
                if (status === 'invalid-number')
                    throw new Error("Invalid number value");
                if (status === 'temporal') {
                    const latest = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                    if (latest.documentId !== snapshot.documentId || JSON.stringify(latest.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids) !== JSON.stringify(snapshot.ids))
                        throw new RetryablePreflightError("Selector target changed; observe again");
                    this.#observation = undefined;
                    inputIssued = true;
                    const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: text }], functionDeclaration: `function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly || this.getAttribute('aria-readonly')==='true') return false; for(let el=this;el;el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if(el.matches(':disabled') || el.getAttribute('aria-disabled')==='true') return false; const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;if(probe.value!==value)return false; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;if(!setter)return false;setter.call(this,value);this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));this.dispatchEvent(new Event('change',{bubbles:true}));return this.isConnected && this.value===value; }` }, { sessionId });
                    if (!isObject(applied) || !isObject(applied.result) || applied.result.value !== true)
                        throw new Error("Date or time input did not retain the requested value");
                    return;
                }
                if (status !== 'text')
                    throw new Error("Target is not an editable text field");
            }
            const verifyDomIdentity = async () => {
                if (!domIdentity)
                    return;
                if (this.browser.client.connectionGeneration !== domConnectionGeneration)
                    throw new RetryablePreflightError('Connection changed; observe again');
                const result = await this.browser.cdp.call(this.id, 'Runtime.callFunctionOn', { objectId, returnByValue: true, functionDeclaration: domIdentityFunction }, { sessionId });
                const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                if (this.browser.client.connectionGeneration !== domConnectionGeneration || !isObject(value) || value.tag !== domIdentity.tag || value.role !== domIdentity.role || value.name !== domIdentity.name || value.type !== domIdentity.type || value.disabled !== domIdentity.disabled || value.checked !== domIdentity.checked)
                    throw new RetryablePreflightError('DOM target changed; observe again');
            };
            await verifyDomIdentity();
            this.#observation = undefined;
            const options = { sessionId, ...(sessionId ? { visualPoint: second.point } : {}), ...(domConnectionGeneration !== undefined ? { expectedGeneration: domConnectionGeneration } : {}) };
            inputIssued = true;
            if (key !== undefined || text !== undefined) {
                await this.browser.cdp.call(this.id, "DOM.focus", { objectId }, { sessionId });
                const verifyFocus = async () => {
                    const afterFocus = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                    if (afterFocus.documentId !== snapshot.documentId || JSON.stringify(afterFocus.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(afterFocus.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(afterFocus.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(afterFocus.ids) !== JSON.stringify(snapshot.ids))
                        throw new Error("Selector target changed after focus; observe again");
                    if ((await this.focusedInputFrame()).id !== frame.id)
                        throw new Error("Target frame lost focus; observe again");
                    const focused = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: text !== undefined }, { value: text ?? '' }, { value: append }], functionDeclaration: `function(editable,value,append) { if (!this.isConnected) return false; for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return false; if (editable && (this.readOnly || this.getAttribute('aria-readonly') === 'true' || !(this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type))))) return false; if(editable && !append && this instanceof HTMLInputElement && this.type==='number'){const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;if(probe.value!==value)return 'invalid-number';} let element=this; while (true) { const root=element.getRootNode(); if (root.activeElement!==element) return false; if (!(root instanceof ShadowRoot)) return true; element=root.host; } }` }, { sessionId });
                    if (isObject(focused) && isObject(focused.result) && focused.result.value === 'invalid-number')
                        throw new Error("Invalid number value");
                    if (!isObject(focused) || !isObject(focused.result) || focused.result.value !== true)
                        throw new Error("Target lost focus or is not editable; observe again");
                };
                await verifyFocus();
                if (key !== undefined) {
                    await this.sendKey(key, sessionId);
                    return;
                }
                if (text === undefined)
                    throw new Error("Text is unavailable");
                if (append) {
                    if (text)
                        await this.browser.cdp.call(this.id, "Input.insertText", { text }, { sessionId });
                    return;
                }
                await this.sendKey(process.platform === "darwin" ? "Meta+A" : "Control+A", sessionId);
                await verifyFocus();
                const selected = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, functionDeclaration: `function() { if (this.isContentEditable) { const selection=this.getRootNode().getSelection?.() ?? getSelection(); return !!selection && selection.toString()===this.innerText; } return this.selectionStart===null || (this.selectionStart===0 && this.selectionEnd===this.value.length); }` }, { sessionId });
                if (!isObject(selected) || !isObject(selected.result) || selected.result.value !== true)
                    throw new Error("Could not select the text field contents");
                if (text)
                    await this.browser.cdp.call(this.id, "Input.insertText", { text }, { sessionId });
                else
                    await this.sendKey("Backspace", sessionId);
                const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, arguments: [{ value: text }], functionDeclaration: `function(value) { return this.isConnected && (this.isContentEditable ? this.innerText : this.value)===value; }` }, { sessionId });
                if (!isObject(applied) || !isObject(applied.result) || applied.result.value !== true)
                    throw new Error("Text field did not retain the requested value");
                return;
            }
            if (hover)
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", ...second.inputPoint, button: "none", buttons: 0 }, options);
            else {
                await this.dispatchClick(second.inputPoint, mouse, 1, options);
                if (checked !== undefined) {
                    const latest = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                    if (latest.documentId !== snapshot.documentId || JSON.stringify(latest.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids) !== JSON.stringify(snapshot.ids) || (await checkedState()).value !== checked)
                        throw new Error("Target did not retain the requested checked state");
                }
                if (doubleClick) {
                    const after = await measure();
                    if (moving(second.geometry.x, after.geometry.x) || moving(second.geometry.y, after.geometry.y) || moving(second.geometry.width, after.geometry.width) || moving(second.geometry.height, after.geometry.height) || moving(second.point.x, after.point.x) || moving(second.point.y, after.point.y))
                        throw new Error("Target moved after the first click; observe again");
                    const latest = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
                    if (latest.documentId !== snapshot.documentId || JSON.stringify(latest.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(latest.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(latest.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(latest.ids) !== JSON.stringify(snapshot.ids))
                        throw new Error("Selector target changed after the first click; observe again");
                    await verifyDomIdentity();
                    await this.dispatchClick(second.inputPoint, mouse, 2, options);
                }
            }
        }
        catch (error) {
            if (inputIssued && error instanceof RetryablePreflightError)
                throw new Error(error.message, { cause: error });
            throw error;
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async triggerMediaDownload(backendNodeId, frame, verify) {
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        if (!isObject(world) || typeof world.executionContextId !== "number")
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId, executionContextId: world.executionContextId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Download target is unavailable; observe again");
        try {
            await verify();
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, userGesture: true, functionDeclaration: `function() {
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
      }` }, { sessionId });
            const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (value === 'stale')
                throw new RetryablePreflightError("Download target changed; observe again");
            if (value === 'missing')
                throw new Error("Target does not expose a media URL");
            if (value === 'invalid')
                throw new Error("Invalid media URL");
            if (value === 'cross-origin')
                throw new Error("Cross-origin media downloads are not supported");
            if (value !== 'ok')
                throw new Error("Media download outcome is unknown");
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async locatorRead(snapshotId, index, mode, attribute = "") {
        const observation = this.#observation;
        if (!observation || observation.id !== snapshotId)
            throw new RetryablePreflightError("Observation is stale; observe again");
        const target = observation.nodes.find(node => node.index === index);
        if (!target || await this.documentId() !== observation.documentId)
            throw new RetryablePreflightError("Page changed; observe again");
        if (target.frameChain)
            await this.validateFrames(target.frameChain);
        await this.verifyLocatorScope(observation, target);
        const sessionId = target.frameChain?.[0]?.sessionId;
        const tree = target.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: target.frameId }, { sessionId }) : await this.getAXState();
        const fresh = interactiveNodes(tree, 0, true).find(node => node.backendNodeId === target.backendNodeId && node.role === target.role);
        if (!fresh || fresh.name !== target.name || fresh.stateKey !== target.stateKey)
            throw new RetryablePreflightError("Target changed; observe again");
        if (mode === "checked") {
            if (typeof fresh.checked !== "boolean")
                throw new Error("Target does not have a binary checked state");
            if (await this.documentId() !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            if (target.frameChain)
                await this.validateFrames(target.frameChain);
            await this.verifyLocatorScope(observation, target);
            return fresh.checked;
        }
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: target.backendNodeId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Target is unavailable; observe again");
        try {
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                objectId, returnByValue: true, arguments: [{ value: mode }, { value: attribute }],
                functionDeclaration: `function(mode, name) { if (!this.isConnected) return null; if (mode === 'enabled' || mode === 'visible') { const element = this.nodeType === 3 ? this.parentElement : this; if (!(element instanceof Element)) return null; if (mode === 'visible') { const r = this.nodeType === 3 ? (() => {const range=document.createRange();range.selectNode(this);return range.getBoundingClientRect();})() : element.getBoundingClientRect(); return {value:getComputedStyle(element).visibility === 'visible' && r.width > 0 && r.height > 0}; } for (let el=element; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return {value:false}; return {value:true}; } const value = mode === 'attribute' ? (this.nodeType === 1 ? this.getAttribute(name) : null) : mode === 'textContent' || this.nodeType === 3 ? this.textContent : this.innerText; return {value: typeof value === 'string' ? value.slice(0, 30001) : null}; }`
            }, { sessionId });
            const payload = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (!isObject(payload) || (["enabled", "visible"].includes(mode) ? typeof payload.value !== "boolean" : typeof payload.value !== "string" && payload.value !== null))
                throw new RetryablePreflightError("Target value is unavailable; observe again");
            const value = payload.value;
            if (value === null && mode === "innerText")
                throw new RetryablePreflightError("Target text is unavailable; observe again");
            if (typeof value === "string" && value.length > 30_000)
                throw new Error("Locator value exceeds the 30000 character limit");
            if (await this.documentId() !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            if (target.frameChain)
                await this.validateFrames(target.frameChain);
            if (mode === "visible" && value === true) {
                let frameVisible = true;
                for (let i = 0; i < (target.frameChain?.length ?? 0); i++) {
                    const frame = target.frameChain[i], ownerSession = target.frameChain[i + 1]?.sessionId;
                    const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: frame.id }, { sessionId: ownerSession });
                    if (!isObject(owner) || typeof owner.backendNodeId !== "number")
                        throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                    const result = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId }, { sessionId: ownerSession });
                    const ownerId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
                    if (typeof ownerId !== "string")
                        throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                    try {
                        const visibility = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId: ownerId, returnByValue: true, functionDeclaration: `function() { if (!this.isConnected) return null; const r=this.getBoundingClientRect(); return getComputedStyle(this).visibility === 'visible' && r.width > 0 && r.height > 0; }` }, { sessionId: ownerSession });
                        const visible = isObject(visibility) && isObject(visibility.result) ? visibility.result.value : undefined;
                        if (typeof visible !== "boolean")
                            throw new RetryablePreflightError("Frame owner changed; observe again");
                        if (!visible) {
                            frameVisible = false;
                            break;
                        }
                    }
                    finally {
                        await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId: ownerId }, { sessionId: ownerSession }).catch(() => { });
                    }
                }
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                if (target.frameChain)
                    await this.validateFrames(target.frameChain);
                return frameVisible;
            }
            return mode === "enabled" ? value === true && !fresh.disabled : value;
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async scopeVisible(observation, index) {
        const node = observation.nodes.find(item => item.index === index);
        const frame = observation.frames?.find(item => item.id === (node?.frameId ?? observation.frames?.[0]?.id));
        if (!node || !frame || !observation.frames)
            throw new RetryablePreflightError("Filter scope is unavailable; observe again");
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        if (!isObject(world) || typeof world.executionContextId !== "number")
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId, executionContextId: world.executionContextId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Filter scope is unavailable; observe again");
        try {
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, functionDeclaration: `function() { if(!this.isConnected)return null;const element=this.nodeType===3 ? this.parentElement : this;if(!(element instanceof Element))return null;const r=this.nodeType===3 ? (()=>{const range=document.createRange();range.selectNode(this);return range.getBoundingClientRect()})() : element.getBoundingClientRect();return getComputedStyle(element).visibility==='visible' && r.width>0 && r.height>0; }` }, { sessionId });
            const visible = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (typeof visible !== "boolean")
                throw new RetryablePreflightError("Filter scope changed; observe again");
            const frameVisible = visible ? await this.cssFrameVisible(frame, observation.frames) : false;
            if (await this.documentId() !== observation.documentId || JSON.stringify(await this.frameTree()) !== JSON.stringify(observation.frames))
                throw new RetryablePreflightError("Frame tree changed; observe again");
            return visible && frameVisible;
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async scopeText(observation, index) {
        const scope = observation.nodes.find(node => node.index === index);
        if (!scope)
            throw new RetryablePreflightError("Scope changed; observe again");
        const seen = new Set();
        for (const item of observation.unindexedText) {
            if (item.backendNodeId === undefined)
                throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
            const key = `${item.frameId ?? "root"}:${item.backendNodeId}`;
            if (seen.has(key))
                continue;
            seen.add(key);
            if (scope.frameId === item.frameId && scope.backendNodeId === item.backendNodeId)
                throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
            const probe = { index: -1, role: "", name: "", stateKey: "", backendNodeId: item.backendNodeId, frameId: item.frameId, frameChain: item.frameChain };
            const withProbe = { ...observation, nodes: [...observation.nodes, probe] };
            if (await this.scopeContains(withProbe, index, -1) || await this.scopeContains(withProbe, -1, index))
                throw new Error("Some accessible text cannot be indexed; locator text results are incomplete");
        }
        const textNodes = observation.nodes.filter(node => node.name && node.role === "StaticText");
        const included = new Set();
        if (scope.role === "StaticText")
            included.add(scope.index);
        const sameFrame = textNodes.filter(node => node.index !== index && node.frameId === scope.frameId);
        if (sameFrame.length) {
            if (await this.documentId() !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            if (scope.frameChain)
                await this.validateFrames(scope.frameChain);
            const sessionId = scope.frameChain?.[0]?.sessionId;
            const objects = [];
            const resolve = async (node) => {
                const result = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId }, { sessionId });
                const objectId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Scope target is unavailable; observe again");
                return objectId;
            };
            try {
                const scopeObject = await resolve(scope);
                objects.push(scopeObject);
                for (let offset = 0; offset < sameFrame.length; offset += 32) {
                    const batch = sameFrame.slice(offset, offset + 32);
                    const resolved = await Promise.allSettled(batch.map(resolve));
                    for (const result of resolved)
                        if (result.status === "fulfilled")
                            objects.push(result.value);
                    const failure = resolved.find(result => result.status === "rejected");
                    if (failure?.status === "rejected")
                        throw failure.reason;
                    const targetObjects = resolved.map(result => result.value);
                    const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                        objectId: scopeObject, arguments: targetObjects.map(objectId => ({ objectId })), returnByValue: true,
                        functionDeclaration: `function(...targets) { return targets.map(target => { if (!this.isConnected || !target.isConnected) return null; if (target===this) return false; for (let node=target; node; node=node.parentNode || node.getRootNode()?.host) if (node===this) return true; return false; }); }`
                    }, { sessionId });
                    const values = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                    if (!Array.isArray(values) || values.length !== batch.length || values.some(value => typeof value !== "boolean"))
                        throw new RetryablePreflightError("Scope target changed; observe again");
                    for (let i = 0; i < batch.length; i++)
                        if (values[i])
                            included.add(batch[i].index);
                    await Promise.allSettled(targetObjects.map(objectId => this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId })));
                    objects.splice(1);
                }
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                if (scope.frameChain)
                    await this.validateFrames(scope.frameChain);
            }
            finally {
                await Promise.allSettled(objects.map(objectId => this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId })));
            }
        }
        const frameMembership = new Map();
        for (const node of textNodes) {
            if (node.frameId === scope.frameId)
                continue;
            const key = node.frameId ?? "root";
            if (!frameMembership.has(key))
                frameMembership.set(key, await this.scopeContains(observation, index, node.index));
            if (frameMembership.get(key))
                included.add(node.index);
        }
        const parts = [];
        let length = 0;
        for (const node of textNodes) {
            if (!included.has(node.index))
                continue;
            length += node.name.length + 1;
            if (length > 30_000)
                throw new Error("Locator text exceeds the 30000 character limit");
            parts.push(node.name);
        }
        return parts.join(" ").replace(/\s+/g, " ").trim();
    }
    /** @internal */
    async freshFilterObservation() {
        const documentId = await this.documentId();
        await this.browser.cdp.enableFrameSessions(this.id);
        const frames = await this.frameTree();
        const tree = await this.getAXState();
        const unindexedText = unindexedTextAncestors(tree).map(backendNodeId => ({ backendNodeId }));
        const nodes = interactiveNodes(tree, 0, true);
        for (const frame of frames.slice(1)) {
            const tree = await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: frame.id }, { sessionId: frame.sessionId });
            unindexedText.push(...unindexedTextAncestors(tree).map(backendNodeId => ({ backendNodeId, frameId: frame.id, frameChain: frameAncestry(frame, frames) })));
            nodes.push(...interactiveNodes(tree, nodes.length, true).map(node => ({ ...node, frameId: frame.id, frameChain: frameAncestry(frame, frames) })));
        }
        if (documentId !== await this.documentId() || JSON.stringify(frames) !== JSON.stringify(await this.frameTree()))
            throw new RetryablePreflightError("Page changed; observe again");
        return { id: "", documentId, nodes, unindexedText, frames, guards: new Map() };
    }
    /** @internal */
    async scopeContains(observation, scopeIndex, targetIndex) {
        const scope = observation.nodes.find(node => node.index === scopeIndex);
        const target = observation.nodes.find(node => node.index === targetIndex);
        if (!scope || !target)
            throw new RetryablePreflightError("Scope changed; observe again");
        if (scopeIndex === targetIndex)
            return false;
        if (await this.documentId() !== observation.documentId)
            throw new RetryablePreflightError("Page changed; observe again");
        if (scope.frameChain)
            await this.validateFrames(scope.frameChain);
        if (target.frameChain)
            await this.validateFrames(target.frameChain);
        const sessionId = scope.frameChain?.[0]?.sessionId;
        let backendNodeId = target.backendNodeId;
        if (scope.frameId !== target.frameId) {
            const chain = target.frameChain ?? [];
            const frame = scope.frameId ? chain.find(item => item.parentId === scope.frameId) : chain.at(-1);
            if (!frame)
                return false;
            const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: frame.id }, { sessionId });
            if (!isObject(owner) || typeof owner.backendNodeId !== "number")
                throw new RetryablePreflightError("Frame owner changed; observe again");
            backendNodeId = owner.backendNodeId;
        }
        const objects = [];
        try {
            for (const id of [scope.backendNodeId, backendNodeId]) {
                const result = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: id }, { sessionId });
                const objectId = isObject(result) && isObject(result.object) ? result.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Scope target is unavailable; observe again");
                objects.push(objectId);
            }
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                objectId: objects[0], arguments: [{ objectId: objects[1] }], returnByValue: true,
                functionDeclaration: `function(target) { if (!this.isConnected || !target.isConnected || target===this) return false; for (let node=target; node; node=node.parentNode || node.getRootNode()?.host) if (node===this) return true; return false; }`
            }, { sessionId });
            if (!isObject(result) || !isObject(result.result) || typeof result.result.value !== "boolean")
                throw new Error("Could not verify locator scope");
            if (await this.documentId() !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            if (scope.frameChain)
                await this.validateFrames(scope.frameChain);
            if (target.frameChain)
                await this.validateFrames(target.frameChain);
            return result.result.value;
        }
        finally {
            for (const objectId of objects)
                await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    /** @internal */
    async cssScopeContains(observation, snapshot, scopeId, targetIndex) {
        const frame = snapshot.frame, target = observation.nodes.find(node => node.index === targetIndex);
        if (!frame || !target || !snapshot.ids.includes(scopeId) || observation.documentId !== snapshot.documentId || JSON.stringify(observation.frames) !== JSON.stringify(snapshot.frames))
            throw new RetryablePreflightError("CSS scope changed; observe again");
        if ((target.frameId ?? snapshot.frames[0].id) !== frame.id)
            return false;
        const sessionId = frame.sessionId;
        const world = await this.browser.cdp.call(this.id, "Page.createIsolatedWorld", { frameId: frame.id, worldName: "open-browser-use-selector" }, { sessionId });
        if (!isObject(world) || typeof world.executionContextId !== "number")
            throw new RetryablePreflightError("Selector context is unavailable; observe again");
        const objects = [];
        try {
            for (const id of [scopeId, target.backendNodeId]) {
                const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: id, executionContextId: world.executionContextId }, { sessionId });
                const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Scope target is unavailable; observe again");
                objects.push(objectId);
            }
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId: objects[0], arguments: [{ objectId: objects[1] }], returnByValue: true, functionDeclaration: `function(target) {if(!this.isConnected || !target.isConnected)return null;if(target===this)return false;for(let node=target;node;node=node.parentNode || node.getRootNode()?.host)if(node===this)return true;return false;}` }, { sessionId });
            const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
            if (typeof value !== "boolean")
                throw new RetryablePreflightError("Scope target changed; observe again");
            if (await this.documentId() !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            return value;
        }
        finally {
            for (const objectId of objects)
                await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    async verifyLocatorScope(observation, target) {
        const guard = observation.guards.get(target.index);
        if (guard?.css) {
            const { snapshot, scopeId } = guard.css, fresh = await this.queryCss(snapshot.step, snapshot.framePath, snapshot.scopes, snapshot.semantic?.scope, undefined, snapshot.frameId);
            if (fresh.documentId !== snapshot.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(fresh.semantic?.roots) !== JSON.stringify(snapshot.semantic?.roots) || JSON.stringify(fresh.scopeIds) !== JSON.stringify(snapshot.scopeIds) || JSON.stringify(fresh.ids) !== JSON.stringify(snapshot.ids) || !await this.cssScopeContains(observation, snapshot, scopeId, guard.scopes[0] ?? target.index))
                throw new RetryablePreflightError("CSS scope changed; observe again");
        }
        if (guard?.framePath && await this.resolveFramePath(guard.framePath) !== target.frameId)
            throw new RetryablePreflightError("Frame selector changed; observe again");
        const scopes = guard?.scopes ?? [];
        for (let i = 0; i < scopes.length; i++) {
            const scope = observation.nodes.find(node => node.index === scopes[i]);
            if (!scope)
                throw new RetryablePreflightError("Scope changed; observe again");
            const sessionId = scope.frameChain?.[0]?.sessionId;
            const tree = scope.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: scope.frameId }, { sessionId }) : await this.getAXState();
            const current = interactiveNodes(tree, 0, true).find(node => node.backendNodeId === scope.backendNodeId && node.role === scope.role);
            if (!current || current.name !== scope.name || current.stateKey !== scope.stateKey)
                throw new RetryablePreflightError("Scope changed; observe again");
            if (!await this.scopeContains(observation, scope.index, scopes[i + 1] ?? target.index))
                throw new RetryablePreflightError("Target moved outside scope; observe again");
        }
        if (guard?.filters.length) {
            const fresh = await this.freshFilterObservation();
            if (fresh.documentId !== observation.documentId)
                throw new RetryablePreflightError("Page changed; observe again");
            for (const item of guard.filters) {
                const original = observation.nodes.find(node => node.index === item.index);
                const current = original && fresh.nodes.find(node => node.backendNodeId === original.backendNodeId && node.frameId === original.frameId && node.role === original.role);
                if (!original || !current || current.name !== original.name || current.stateKey !== original.stateKey)
                    throw new RetryablePreflightError("Filtered target changed; observe again");
                const textFilters = item.filters.filter(filter => filter.hasText !== undefined || filter.hasNotText !== undefined);
                if (textFilters.length && !matchesTextFilters(await this.scopeText(fresh, current.index), textFilters))
                    throw new RetryablePreflightError("Locator text changed; observe again");
            }
        }
        if (guard?.role)
            await guard.role.locator.verifyMatches(observation, guard.role.expected);
    }
    async prepareBrowserEvent(method, readyMethod, timeoutMs) {
        const waitId = randomUUID(), client = this.browser.client;
        let remove = () => { };
        const ready = new Promise(resolve => {
            remove = client.onNotification(event => {
                if (event.method === readyMethod && isObject(event.params) && event.params.waitId === waitId)
                    resolve();
            });
        });
        const result = Promise.resolve().then(() => client.request(method, { tabId: this.id, timeoutMs, waitId }, undefined, Math.max(client.timeoutMs, timeoutMs + 2000)));
        void result.catch(() => { });
        try {
            await Promise.race([ready, result.then(() => { throw new Error("Event wait ended before registration was confirmed"); })]);
            return { result };
        }
        finally {
            remove();
        }
    }
    async prepareDownload(options = {}) {
        const timeoutMs = options.timeoutMs ?? 10_000;
        if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000)
            throw new Error("Invalid download timeout");
        const prepared = await this.prepareBrowserEvent("waitForDownload", "onDownloadWaitReady", timeoutMs);
        return new OpenBrowserUseDownloadWait(this.browser.client, prepared.result);
    }
    async prepareFileChooser(options = {}) {
        const timeoutMs = options.timeoutMs ?? 10_000;
        if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 120_000)
            throw new Error("Invalid file chooser timeout");
        await this.browser.cdp.enableFrameSessions(this.id);
        const prepared = await this.prepareBrowserEvent("waitForFileChooser", "onFileChooserWaitReady", timeoutMs);
        return new OpenBrowserUseFileChooserWait(this.browser.client, prepared.result);
    }
    async watchDialogs() { await this.browser.cdp.enableDialogs(this.id); }
    currentDialog() {
        const info = this.browser.cdp.currentDialog(this.id);
        return info ? new OpenBrowserUseDialog(this.browser.cdp, this.id, info) : null;
    }
    async waitForDialog(options = {}) {
        const timeoutMs = options.timeoutMs ?? 10_000;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid dialog timeout");
        let dialog = this.currentDialog();
        if (dialog)
            return dialog;
        await this.watchDialogs();
        dialog = this.currentDialog();
        if (dialog)
            return dialog;
        await this.browser.cdp.waitForEvent(this.id, notification => {
            if (notification.method !== "onCDPEvent" || !isObject(notification.params))
                return false;
            const source = notification.params.source;
            return isObject(source) && source.tabId === this.id && notification.params.method === "Page.javascriptDialogOpening";
        }, { timeoutMs, timeoutMessage: "Timed out waiting for a JavaScript dialog" });
        dialog = this.currentDialog();
        if (!dialog)
            throw new Error("Dialog closed before it could be observed");
        return dialog;
    }
    async click(index, snapshotId, mouse) {
        await this.act(index, snapshotId, undefined, false, undefined, undefined, false, undefined, false, mouse);
    }
    async dblclick(index, snapshotId, mouse) {
        await this.act(index, snapshotId, undefined, false, undefined, undefined, false, undefined, true, mouse);
    }
    async hover(index, snapshotId) {
        await this.act(index, snapshotId, undefined, false, undefined, undefined, true);
    }
    async press(index, snapshotId, key) {
        this.parseKey(key);
        await this.act(index, snapshotId, undefined, false, undefined, undefined, false, key);
    }
    async hoverAt(x, y, modifiers = 0) {
        this.#observation = undefined;
        if (!Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15)
            throw new Error("Invalid mouse modifiers");
        await this.checkPoint(x, y);
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers });
    }
    async dispatchClick(point, mouse, clickCount, options = {}) {
        const release = { type: "mouseReleased", ...point, button: mouse.button, buttons: 0, modifiers: mouse.modifiers, clickCount };
        let pending = true;
        try {
            await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { ...release, type: "mousePressed", buttons: mouse.buttons }, options);
            await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", release, options);
            pending = false;
        }
        finally {
            if (pending)
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", release, options).catch(() => { });
        }
    }
    async clickAt(x, y, options = {}) {
        this.#observation = undefined;
        const buttons = [{ name: "left", mask: 1 }, { name: "middle", mask: 4 }, { name: "right", mask: 2 }, { name: "back", mask: 8 }, { name: "forward", mask: 16 }];
        const button = buttons[(options.button ?? 1) - 1], modifiers = options.modifiers ?? 0;
        if (!Number.isInteger(options.button ?? 1) || !button || !Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15 || (options.double !== undefined && typeof options.double !== "boolean"))
            throw new Error("Invalid mouse options");
        await this.checkPoint(x, y);
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers });
        for (let count = 1; count <= (options.double ? 2 : 1); count++) {
            let pressed = true;
            try {
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: button.name, buttons: button.mask, clickCount: count, modifiers });
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: button.name, buttons: 0, clickCount: count, modifiers });
                pressed = false;
            }
            finally {
                if (pressed)
                    await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: button.name, buttons: 0, clickCount: count, modifiers }).catch(() => { });
            }
        }
    }
    async dragPath(path, modifiers = 0) {
        this.#observation = undefined;
        if (!Array.isArray(path) || path.length < 2 || path.length > 1000 || !Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15)
            throw new Error("Invalid drag path");
        path = path.map(point => ({ x: point?.x, y: point?.y }));
        const viewport = await this.getViewport();
        for (const point of path)
            if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.y < 0 || point.x >= viewport.width || point.y >= viewport.height)
                throw new Error("Drag point is outside the viewport");
        let { x, y } = path[0], pressed = false;
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers });
        try {
            pressed = true;
            await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1, modifiers });
            for (const point of path.slice(1)) {
                x = point.x;
                y = point.y;
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "left", buttons: 1, modifiers });
            }
            await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1, modifiers });
            pressed = false;
        }
        finally {
            if (pressed)
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1, modifiers }).catch(() => { });
        }
    }
    async drag(from, to) {
        this.#observation = undefined;
        if (!Array.isArray(from) || from.length !== 2 || !Array.isArray(to) || to.length !== 2)
            throw new Error("Drag requires two coordinate pairs");
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
        }
        finally {
            if (pressed)
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 }).catch(() => { });
        }
    }
    async scrollAt(x, y, deltaX, deltaY, modifiers = 0, expectedGeneration, frame) {
        this.#observation = undefined;
        if (!Number.isFinite(deltaX) || !Number.isFinite(deltaY))
            throw new Error("Scroll deltas must be finite numbers");
        if (!Number.isInteger(modifiers) || modifiers < 0 || modifiers > 15)
            throw new Error("Invalid mouse modifiers");
        await this.checkPoint(x, y);
        const options = { ...(expectedGeneration === undefined ? {} : { expectedGeneration }), ...(frame ? { sessionId: frame.sessionId, visualPoint: { x, y } } : {}) };
        if (frame)
            ({ x, y } = frame.inputPoint);
        await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0, modifiers }, options);
        if (modifiers || frame) {
            try {
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX, deltaY, modifiers }, options);
            }
            catch (error) {
                if (error instanceof Error && /Timed out after \d+ms waiting for CDP command/.test(error.message))
                    throw new Error("Wheel outcome unknown after timeout; inspect the page before retrying", { cause: error });
                throw error;
            }
        }
        else
            await this.browser.cdp.call(this.id, "Input.synthesizeScrollGesture", { x, y, xDistance: -deltaX, yDistance: -deltaY, gestureSourceType: "mouse", preventFling: true }, options);
        if (frame) {
            try {
                const result = await this.browser.cdp.call(this.id, "Runtime.evaluate", { contextId: frame.contextId, expression: "Promise.race([new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))),new Promise(r=>setTimeout(r,1000))])", awaitPromise: true }, { sessionId: frame.sessionId, timeoutMs: 3000, ...(expectedGeneration === undefined ? {} : { expectedGeneration }) });
                if (isObject(result) && result.exceptionDetails)
                    throw new Error("Frame rendering wait failed");
            }
            catch (error) {
                throw new Error("Wheel was sent but its completion could not be observed; inspect the page before retrying", { cause: error });
            }
        }
    }
    parseKey(key) {
        if (typeof key !== "string")
            throw new Error("Key must be a string");
        const definitions = {
            Enter: ["Enter", 13], Tab: ["Tab", 9], Escape: ["Escape", 27], Backspace: ["Backspace", 8],
            Delete: ["Delete", 46], ArrowLeft: ["ArrowLeft", 37], ArrowUp: ["ArrowUp", 38],
            ArrowRight: ["ArrowRight", 39], ArrowDown: ["ArrowDown", 40], Home: ["Home", 36], End: ["End", 35],
            PageUp: ["PageUp", 33], PageDown: ["PageDown", 34], Space: ["Space", 32],
            Alt: ["AltLeft", 18], Control: ["ControlLeft", 17], Meta: ["MetaLeft", 91], Shift: ["ShiftLeft", 16]
        };
        const parts = key === "+" ? ["+"] : key.split("+");
        const rawName = parts.pop() ?? "";
        const name = rawName === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : rawName;
        const modifierBits = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };
        const modifiers = parts.map(part => part === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : part);
        if (new Set(modifiers).size !== modifiers.length || modifiers.includes(name) || modifiers.some(modifier => !Object.hasOwn(modifierBits, modifier)))
            throw new Error("Invalid keyboard modifiers");
        const pairs = [
            ...Array.from({ length: 10 }, (_, digit) => [String(digit), ")!@#$%^&*("[digit], `Digit${digit}`, 48 + digit]),
            ["-", "_", "Minus", 189], ["=", "+", "Equal", 187], ["[", "{", "BracketLeft", 219],
            ["]", "}", "BracketRight", 221], ["\\", "|", "Backslash", 220], [";", ":", "Semicolon", 186],
            ["'", '"', "Quote", 222], [",", "<", "Comma", 188], [".", ">", "Period", 190],
            ["/", "?", "Slash", 191], ["`", "~", "Backquote", 192]
        ];
        const printablePair = pairs.find(([plain, shifted]) => name === plain || name === shifted);
        if (printablePair && name === printablePair[1] && !modifiers.includes("Shift"))
            modifiers.push("Shift");
        const definition = (Object.hasOwn(definitions, name) ? definitions[name] : undefined) ?? (printablePair ? [printablePair[2], printablePair[3]] : /^[a-zA-Z]$/.test(name) ? [`Key${name.toUpperCase()}`, name.toUpperCase().charCodeAt(0)] : undefined);
        if (!definition)
            throw new Error("Unsupported key");
        return { name, modifiers, modifierBits, definition, printablePair };
    }
    async pressKey(key) {
        this.parseKey(key);
        this.#observation = undefined;
        await this.sendKey(key, (await this.focusedInputFrame()).sessionId);
    }
    async typeAtFocus(text) {
        if (typeof text !== "string")
            throw new Error("Text must be a string");
        this.#observation = undefined;
        const sessionId = (await this.focusedInputFrame()).sessionId;
        if (text)
            await this.browser.cdp.call(this.id, "Input.insertText", { text }, { sessionId });
    }
    async focusedInputFrame() {
        const documentId = await this.documentId();
        const crossProcess = await this.browser.cdp.enableFrameSessions(this.id);
        const frames = await this.frameTree();
        if (!crossProcess && frames.length > 1)
            throw new Error("Focused frame routing is unavailable");
        const focusedFrame = async () => {
            let current = frames[0];
            while (true) {
                let focused;
                for (const child of frames.filter(frame => frame.parentId === current.id)) {
                    const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId: child.id }, { sessionId: current.sessionId });
                    if (!isObject(owner) || typeof owner.backendNodeId !== "number")
                        throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                    const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId }, { sessionId: current.sessionId });
                    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                    if (typeof objectId !== "string")
                        throw new RetryablePreflightError("Frame owner is unavailable; observe again");
                    try {
                        const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true, functionDeclaration: `function() { if (!this.isConnected) return null; let element=this; while (true) { const root=element.getRootNode(); if (root.activeElement !== element) return false; if (!(root instanceof ShadowRoot)) return true; element=root.host; } }` }, { sessionId: current.sessionId });
                        const value = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                        if (typeof value !== "boolean")
                            throw new RetryablePreflightError("Frame focus is unavailable; observe again");
                        if (value) {
                            if (focused)
                                throw new RetryablePreflightError("Frame focus changed; observe again");
                            focused = child;
                        }
                    }
                    finally {
                        await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId: current.sessionId }).catch(() => { });
                    }
                }
                if (!focused)
                    return current;
                current = focused;
            }
        };
        const target = await focusedFrame();
        if ((await focusedFrame()).id !== target.id || JSON.stringify(await this.frameTree()) !== JSON.stringify(frames) || await this.documentId() !== documentId)
            throw new RetryablePreflightError("Frame focus changed; observe again");
        return target;
    }
    async sendKey(key, sessionId) {
        const { name, modifiers, modifierBits, definition, printablePair } = this.parseKey(key);
        const modifierCodes = { Alt: ["AltLeft", 18], Control: ["ControlLeft", 17], Meta: ["MetaLeft", 91], Shift: ["ShiftLeft", 16] };
        let mask = 0;
        const pressed = [];
        let activeKey;
        try {
            for (const modifier of modifiers) {
                mask |= modifierBits[modifier];
                const [code, windowsVirtualKeyCode] = modifierCodes[modifier];
                pressed.push(modifier);
                await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { type: "rawKeyDown", key: modifier, code, windowsVirtualKeyCode, modifiers: mask }, { sessionId });
            }
            const actualKey = name === "Space" ? " " : printablePair ? printablePair[mask & 8 ? 1 : 0] : /^[a-zA-Z]$/.test(name) ? (mask & 8 ? name.toUpperCase() : name.toLowerCase()) : name;
            const params = { key: actualKey, code: definition[0], windowsVirtualKeyCode: definition[1], modifiers: mask | (Object.hasOwn(modifierBits, name) ? modifierBits[name] : 0) };
            const selectAll = actualKey === "a" && (mask === 2 || mask === 4);
            const printable = (name === "Space" || !!printablePair || /^[a-zA-Z]$/.test(name)) && !(mask & 7);
            activeKey = params;
            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, type: printable ? "keyDown" : "rawKeyDown", ...(printable ? { text: actualKey, unmodifiedText: name === "Space" ? " " : printablePair ? printablePair[0] : name.toLowerCase() } : {}), ...(selectAll ? { commands: ["selectAll"] } : {}) }, { sessionId });
            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...params, modifiers: mask, type: "keyUp" }, { sessionId });
            activeKey = undefined;
        }
        finally {
            if (activeKey)
                await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...activeKey, modifiers: mask, type: "keyUp" }, { sessionId }).catch(() => { });
            for (const modifier of pressed.reverse()) {
                mask &= ~modifierBits[modifier];
                const [code, windowsVirtualKeyCode] = modifierCodes[modifier];
                await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { type: "keyUp", key: modifier, code, windowsVirtualKeyCode, modifiers: mask }, { sessionId }).catch(() => { });
            }
        }
    }
    async checkPoint(x, y) {
        if (!Number.isFinite(x) || !Number.isFinite(y))
            throw new Error("Coordinates must be finite numbers");
        const viewport = await this.getViewport();
        if (x < 0 || y < 0 || x >= viewport.width || y >= viewport.height)
            throw new Error("Coordinates are outside the viewport");
    }
    async getViewport() {
        const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
        const viewport = isObject(metrics) ? metrics.cssVisualViewport : null;
        if (!isObject(viewport) || typeof viewport.clientWidth !== "number" || !Number.isFinite(viewport.clientWidth) || viewport.clientWidth <= 0 || typeof viewport.clientHeight !== "number" || !Number.isFinite(viewport.clientHeight) || viewport.clientHeight <= 0)
            throw new Error("Browser viewport is unavailable");
        return { width: viewport.clientWidth, height: viewport.clientHeight };
    }
    async typeText(index, snapshotId, text) {
        if (typeof text !== "string")
            throw new Error("Text must be a string");
        await this.act(index, snapshotId, text);
    }
    async fill(index, snapshotId, text) {
        if (typeof text !== "string")
            throw new Error("Text must be a string");
        await this.act(index, snapshotId, text, true);
    }
    async setChecked(index, snapshotId, checked) {
        if (typeof checked !== "boolean")
            throw new Error("Checked state must be boolean");
        await this.act(index, snapshotId, undefined, false, checked);
    }
    async selectOption(index, snapshotId, values) {
        const specs = selectSpecs(values);
        const result = await this.act(index, snapshotId, undefined, false, undefined, specs);
        if (!Array.isArray(result) || result.some(value => typeof value !== "string"))
            throw new Error("Invalid selected options result");
        return result;
    }
    async act(index, snapshotId, text, replace = false, checked, selection, hover = false, key, doubleClick = false, mouse = { button: "left", buttons: 1, modifiers: 0 }) {
        const observation = this.#observation;
        this.#observation = undefined;
        const node = observation?.nodes.find((item) => item.index === index);
        if (!observation || observation.id !== snapshotId || !node)
            throw new RetryablePreflightError("Observation is stale or index is invalid; observe again");
        if (text !== undefined && !["textbox", "searchbox", "spinbutton", "Date", "DateTime", "InputTime"].includes(node.role))
            throw new Error("Target is not a text field");
        if (text !== undefined && !replace && ["Date", "DateTime", "InputTime"].includes(node.role))
            throw new Error("Use fill for date and time inputs");
        if (selection !== undefined && !["combobox", "listbox"].includes(node.role))
            throw new Error("Target is not a select control");
        if (await this.documentId() !== observation.documentId)
            throw new RetryablePreflightError("Page changed; observe again");
        if (node.frameChain)
            await this.validateFrames(node.frameChain);
        const targetSession = node.frameChain?.[0]?.sessionId;
        const targetTree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
        const current = interactiveNodes(targetTree, 0, supplementalRoles.includes(node.role)).find((item) => item.backendNodeId === node.backendNodeId && item.role === node.role);
        if (!current || current.role !== node.role || current.name !== node.name || current.stateKey !== node.stateKey)
            throw new RetryablePreflightError("Target changed; observe again");
        if (current.disabled && !hover)
            throw new RetryablePreflightError("Target is disabled; observe again");
        await this.verifyLocatorScope(observation, node);
        if (checked !== undefined) {
            if (!["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(node.role) || typeof current.checked !== "boolean")
                throw new Error("Target does not have a binary checked state");
            if (current.checked === checked) {
                const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId }, { sessionId: targetSession });
                const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                if (typeof objectId !== "string")
                    throw new RetryablePreflightError("Target is unavailable; observe again");
                try {
                    const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", { objectId, returnByValue: true,
                        functionDeclaration: `function() { if (!(this instanceof Element) || !this.isConnected) return 'unavailable'; for (let el=this; el; el=el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null)) if (el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return 'disabled'; return 'enabled'; }`
                    }, { sessionId: targetSession });
                    const status = isObject(result) && isObject(result.result) ? result.result.value : undefined;
                    if (status === "disabled")
                        throw new RetryablePreflightError("Target is disabled; observe again");
                    if (status !== "enabled")
                        throw new RetryablePreflightError("Target is unavailable; observe again");
                    if (await this.documentId() !== observation.documentId)
                        throw new RetryablePreflightError("Page changed; observe again");
                    if (node.frameChain)
                        await this.validateFrames(node.frameChain);
                    await this.verifyLocatorScope(observation, node);
                    const tree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
                    const latest = interactiveNodes(tree).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
                    if (!latest || latest.name !== node.name || latest.stateKey !== node.stateKey)
                        throw new RetryablePreflightError("Target changed; observe again");
                    return;
                }
                finally {
                    await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId: targetSession }).catch(() => { });
                }
            }
            if (!checked && ["radio", "menuitemradio"].includes(node.role))
                throw new Error("A selected radio cannot be unchecked directly");
        }
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: node.backendNodeId }, { sessionId: targetSession });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Target is unavailable; observe again");
        let inputIssued = false;
        try {
            const measure = async () => {
                const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: hover }],
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
                if (!isObject(point) || typeof point.x !== "number" || !Number.isFinite(point.x) || typeof point.y !== "number" || !Number.isFinite(point.y) || typeof point.width !== "number" || !Number.isFinite(point.width) || point.width <= 0 || typeof point.height !== "number" || !Number.isFinite(point.height) || point.height <= 0)
                    throw new RetryablePreflightError("Target is hidden, disabled, or covered; observe again");
                const geometry = { x: point.x, y: point.y, width: point.width, height: point.height };
                let inputPoint = point;
                if (node.frameChain) {
                    for (let i = 0; i < node.frameChain.length; i++) {
                        const frame = node.frameChain[i];
                        const ownerSession = node.frameChain[i + 1]?.sessionId;
                        point = await this.framePoint(frame.id, point.x, point.y, ownerSession);
                        if (ownerSession === targetSession)
                            inputPoint = point;
                    }
                    await this.validateFrames(node.frameChain);
                }
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                return { point, inputPoint, geometry };
            };
            const first = await measure();
            await new Promise(resolve => setTimeout(resolve, 75));
            const second = await measure();
            const moving = (a, b) => Math.abs(a - b) > 0.25;
            if (moving(first.geometry.x, second.geometry.x) || moving(first.geometry.y, second.geometry.y) ||
                moving(first.geometry.width, second.geometry.width) || moving(first.geometry.height, second.geometry.height) ||
                moving(first.point.x, second.point.x) || moving(first.point.y, second.point.y))
                throw new RetryablePreflightError("Target is moving; observe again");
            const finalTree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
            const finalNode = interactiveNodes(finalTree, 0, supplementalRoles.includes(node.role)).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
            if (!finalNode || finalNode.name !== node.name || finalNode.stateKey !== node.stateKey)
                throw new RetryablePreflightError("Target changed; observe again");
            await this.verifyLocatorScope(observation, node);
            let { point, inputPoint } = second;
            if (text !== undefined && replace && ["Date", "DateTime", "InputTime"].includes(node.role)) {
                const temporal = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: text }],
                    functionDeclaration: `function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly) return 'unsupported'; const probe=this.ownerDocument.createElement('input');probe.type=this.type;probe.value=value;return probe.value === value ? 'ok' : 'invalid'; }`
                }, { sessionId: targetSession });
                const status = isObject(temporal) && isObject(temporal.result) ? temporal.result.value : null;
                if (status === "invalid")
                    throw new Error("Invalid date or time value");
                if (status !== "ok")
                    throw new Error("Target is not an editable native date or time input");
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
                await this.verifyLocatorScope(observation, node);
                inputIssued = true;
                const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: text }],
                    functionDeclaration: `function(value) { if (!(this instanceof HTMLInputElement) || !['date','time','month','week','datetime-local'].includes(this.type) || !this.isConnected || this.disabled || this.readOnly) return false; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set; if (!setter) return false; setter.call(this,value); this.dispatchEvent(new Event('input',{bubbles:true,composed:true})); this.dispatchEvent(new Event('change',{bubbles:true})); return this.isConnected && this.value===value; }`
                }, { sessionId: targetSession });
                if (!isObject(applied) || !isObject(applied.result) || applied.result.value !== true)
                    throw new Error("Date or time input did not retain the requested value");
                return;
            }
            if (text !== undefined && node.role === "spinbutton") {
                const checkedNumber = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: text }, { value: replace }],
                    functionDeclaration: `function(value, replace) { if (!(this instanceof HTMLInputElement) || this.type !== 'number' || !this.isConnected || this.disabled || this.readOnly) return 'unsupported'; if (!replace) return 'ok'; const probe=this.ownerDocument.createElement('input');probe.type='number';probe.value=value;return probe.value === value ? 'ok' : 'invalid'; }`
                }, { sessionId: targetSession });
                const status = isObject(checkedNumber) && isObject(checkedNumber.result) ? checkedNumber.result.value : null;
                if (status === "invalid")
                    throw new Error("Invalid number value");
                if (status !== "ok")
                    throw new Error("Target is not an editable native number input");
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
            }
            if (selection !== undefined) {
                const options = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: selection }],
                    functionDeclaration: `function(specs) {
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
                }, { sessionId: targetSession });
                const found = isObject(options) && isObject(options.result) ? options.result.value : null;
                if (!isObject(found) || typeof found.status !== "string")
                    throw new Error("Invalid select options result");
                if (found.status === "missing")
                    throw new RetryablePreflightError("Requested select option is unavailable");
                if (found.status === "ambiguous")
                    throw new Error("Requested select option is ambiguous");
                if (found.status === "multiple")
                    throw new Error("Multiple options require a multiple select");
                if (found.status !== "ok" || !Array.isArray(found.chosen))
                    throw new Error("Target is not an enabled native select");
                if (await this.documentId() !== observation.documentId)
                    throw new RetryablePreflightError("Page changed; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
                await this.verifyLocatorScope(observation, node);
                inputIssued = true;
                const applied = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true, arguments: [{ value: found.chosen }],
                    functionDeclaration: `function(chosen) {
            if (!(this instanceof HTMLSelectElement) || !this.isConnected || this.disabled || (!this.multiple && chosen.length > 1)) return null;
            const options=Array.from(this.options);
            if (chosen.some(item=>{const o=options[item.index]; return !o || o.value!==item.value || o.label!==item.label || o.disabled || (o.parentElement instanceof HTMLOptGroupElement && o.parentElement.disabled);})) return null;
            if (!this.multiple && !chosen.length) this.selectedIndex=-1;
            else { const indices=new Set(chosen.map(item=>item.index)); for (let i=0;i<options.length;i++) options[i].selected=indices.has(i); }
            this.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
            this.dispatchEvent(new Event('change',{bubbles:true}));
            return this.isConnected ? Array.from(this.selectedOptions, option=>option.value) : null;
          }`
                }, { sessionId: targetSession });
                const selected = isObject(applied) && isObject(applied.result) ? applied.result.value : null;
                const expected = found.chosen.map(item => isObject(item) ? item.value : null);
                if (!Array.isArray(selected) || JSON.stringify([...selected].sort()) !== JSON.stringify([...expected].sort()))
                    throw new Error("Select did not retain the requested options");
                return selected;
            }
            if (key !== undefined) {
                inputIssued = true;
                await this.browser.cdp.call(this.id, "DOM.focus", { objectId }, { sessionId: targetSession });
                const focused = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true,
                    functionDeclaration: `function() { return this.isConnected && this.getRootNode().activeElement === this; }`
                }, { sessionId: targetSession });
                if (!isObject(focused) || !isObject(focused.result) || focused.result.value !== true || await this.documentId() !== observation.documentId)
                    throw new Error("Target lost focus; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
                await this.verifyLocatorScope(observation, node);
                await this.sendKey(key, targetSession);
                return;
            }
            const inputOptions = { sessionId: targetSession, ...(targetSession ? { visualPoint: { x: point.x, y: point.y } } : {}) };
            inputIssued = true;
            if (hover) {
                await this.browser.cdp.call(this.id, "Input.dispatchMouseEvent", { type: "mouseMoved", x: inputPoint.x, y: inputPoint.y, button: "none", buttons: 0 }, inputOptions);
                return;
            }
            await this.dispatchClick({ x: inputPoint.x, y: inputPoint.y }, mouse, 1, inputOptions);
            if (doubleClick) {
                const after = await measure();
                if (moving(second.geometry.x, after.geometry.x) || moving(second.geometry.y, after.geometry.y) || moving(second.geometry.width, after.geometry.width) || moving(second.geometry.height, after.geometry.height) || moving(point.x, after.point.x) || moving(point.y, after.point.y))
                    throw new Error("Target moved after the first click; observe again");
                const tree = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
                const latest = interactiveNodes(tree, 0, supplementalRoles.includes(node.role)).find(item => item.backendNodeId === node.backendNodeId && item.role === node.role);
                if (!latest || latest.name !== node.name || latest.stateKey !== node.stateKey)
                    throw new Error("Target changed after the first click; observe again");
                await this.verifyLocatorScope(observation, node);
                await this.dispatchClick({ x: inputPoint.x, y: inputPoint.y }, mouse, 2, inputOptions);
            }
            if (checked !== undefined) {
                if (await this.documentId() !== observation.documentId)
                    throw new Error("Page changed after input; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
                const result = node.frameId ? await this.browser.cdp.call(this.id, "Accessibility.getFullAXTree", { frameId: node.frameId }, { sessionId: targetSession }) : await this.getAXState();
                if (interactiveNodes(result).find(item => item.backendNodeId === node.backendNodeId)?.checked !== checked)
                    throw new Error("Target did not retain the requested checked state");
            }
            if (text !== undefined) {
                const checkFocus = () => this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                    objectId, returnByValue: true,
                    functionDeclaration: `function() { return this.isConnected && !this.disabled && !this.readOnly && this.getAttribute('aria-readonly') !== 'true' && this.getRootNode().activeElement === this && (this.isContentEditable || this instanceof HTMLTextAreaElement || (this instanceof HTMLInputElement && ['text','search','email','url','tel','password','number'].includes(this.type))); }`
                }, { sessionId: targetSession });
                const focused = await checkFocus();
                if (!isObject(focused) || !isObject(focused.result) || focused.result.value !== true || await this.documentId() !== observation.documentId)
                    throw new Error("Text field lost focus or is not editable; observe again");
                if (node.frameChain)
                    await this.validateFrames(node.frameChain);
                if (replace) {
                    const modifier = process.platform === "darwin" ? { key: "Meta", code: "MetaLeft", windowsVirtualKeyCode: 91, modifiers: 4 } : { key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, modifiers: 2 };
                    const key = { key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: modifier.modifiers };
                    let modifierDown = false, keyDown = false;
                    try {
                        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...modifier, type: "rawKeyDown" }, { sessionId: targetSession });
                        modifierDown = true;
                        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "rawKeyDown", commands: ["selectAll"] }, { sessionId: targetSession });
                        keyDown = true;
                        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "keyUp" }, { sessionId: targetSession });
                        keyDown = false;
                    }
                    finally {
                        if (keyDown)
                            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "keyUp" }, { sessionId: targetSession }).catch(() => { });
                        if (modifierDown)
                            await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...modifier, type: "keyUp", modifiers: 0 }, { sessionId: targetSession }).catch(() => { });
                    }
                    const stillFocused = await checkFocus();
                    if (!isObject(stillFocused) || !isObject(stillFocused.result) || stillFocused.result.value !== true || await this.documentId() !== observation.documentId)
                        throw new Error("Text field changed during fill; observe again");
                    if (node.frameChain)
                        await this.validateFrames(node.frameChain);
                    const selected = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                        objectId, returnByValue: true,
                        functionDeclaration: `function() { if (this.isContentEditable) { const selection=this.getRootNode().getSelection?.() ?? getSelection(); return !!selection && selection.toString() === this.innerText; } return this.selectionStart === null || (this.selectionStart === 0 && this.selectionEnd === this.value.length); }`
                    }, { sessionId: targetSession });
                    if (!isObject(selected) || !isObject(selected.result) || selected.result.value !== true)
                        throw new Error("Could not select the text field contents");
                }
                if (text)
                    await this.browser.cdp.call(this.id, "Input.insertText", { text }, { sessionId: targetSession });
                else if (replace) {
                    const key = { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 };
                    await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "rawKeyDown" }, { sessionId: targetSession });
                    try {
                        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "keyUp" }, { sessionId: targetSession });
                    }
                    catch (error) {
                        await this.browser.cdp.call(this.id, "Input.dispatchKeyEvent", { ...key, type: "keyUp" }, { sessionId: targetSession }).catch(() => { });
                        throw error;
                    }
                }
                if (replace) {
                    const check = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                        objectId, returnByValue: true, arguments: [{ value: text }],
                        functionDeclaration: `function(value) { return this.isConnected && (this.isContentEditable ? this.innerText : this.value) === value; }`
                    }, { sessionId: targetSession });
                    if (!isObject(check) || !isObject(check.result) || check.result.value !== true)
                        throw new Error("Text field did not retain the requested value");
                }
            }
        }
        catch (error) {
            if (inputIssued && error instanceof RetryablePreflightError)
                throw new Error(error.message, { cause: error });
            throw error;
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId: targetSession }).catch(() => { });
        }
    }
    async documentId() {
        const result = await this.browser.cdp.call(this.id, "DOM.getDocument", { depth: 0 });
        const root = isObject(result) ? result.root : null;
        if (!isObject(root) || typeof root.backendNodeId !== "number")
            throw new Error("Could not identify page document");
        return root.backendNodeId;
    }
    async frameTree() {
        const frames = [];
        const visit = (tree, sessionId, parentId) => {
            if (!isObject(tree) || !isObject(tree.frame) || typeof tree.frame.id !== "string" || typeof tree.frame.loaderId !== "string" || typeof tree.frame.url !== "string")
                throw new Error("Invalid frame tree");
            const frame = { id: tree.frame.id, loaderId: tree.frame.loaderId, url: tree.frame.url, ...(parentId ? { parentId } : {}), ...(sessionId ? { sessionId } : {}) };
            frames.push(frame);
            if (Array.isArray(tree.childFrames))
                for (const child of tree.childFrames)
                    visit(child, sessionId, frame.id);
        };
        const root = await this.browser.cdp.call(this.id, "Page.getFrameTree");
        if (!isObject(root) || !isObject(root.frameTree))
            throw new Error("Invalid frame tree");
        visit(root.frameTree);
        const pending = await this.browser.cdp.frameSessions(this.id);
        while (pending.length) {
            const index = pending.findIndex(child => frames.some(frame => frame.id === child.parentFrameId));
            if (index < 0)
                throw new RetryablePreflightError("Frame sessions changed; observe again");
            const child = pending.splice(index, 1)[0];
            const tree = await this.browser.cdp.call(this.id, "Page.getFrameTree", {}, { sessionId: child.sessionId });
            if (!isObject(tree) || !isObject(tree.frameTree) || !isObject(tree.frameTree.frame) || tree.frameTree.frame.id !== child.frameId)
                throw new RetryablePreflightError("Frame session changed; observe again");
            visit(tree.frameTree, child.sessionId, child.parentFrameId);
        }
        return frames;
    }
    async validateFrames(chain) {
        const current = await this.frameTree();
        if (chain.some(frame => !current.some(item => item.id === frame.id && item.loaderId === frame.loaderId && item.parentId === frame.parentId && item.sessionId === frame.sessionId)))
            throw new RetryablePreflightError("Frame changed; observe again");
    }
    async framePoint(frameId, x, y, sessionId) {
        const owner = await this.browser.cdp.call(this.id, "DOM.getFrameOwner", { frameId }, { sessionId });
        if (!isObject(owner) || typeof owner.backendNodeId !== "number")
            throw new RetryablePreflightError("Frame owner is unavailable");
        const resolved = await this.browser.cdp.call(this.id, "DOM.resolveNode", { backendNodeId: owner.backendNodeId }, { sessionId });
        const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
        if (typeof objectId !== "string")
            throw new RetryablePreflightError("Frame owner is unavailable");
        try {
            const result = await this.browser.cdp.call(this.id, "Runtime.callFunctionOn", {
                objectId, returnByValue: true, arguments: [{ value: x }, { value: y }],
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
            }, { sessionId });
            const point = isObject(result) && isObject(result.result) ? result.result.value : null;
            if (!isObject(point) || typeof point.x !== "number" || !Number.isFinite(point.x) || typeof point.y !== "number" || !Number.isFinite(point.y))
                throw new RetryablePreflightError("Frame is hidden, covered or has an unsupported transform");
            return { x: point.x, y: point.y };
        }
        finally {
            await this.browser.cdp.call(this.id, "Runtime.releaseObject", { objectId }, { sessionId }).catch(() => { });
        }
    }
    async getScreenshot(options = {}) {
        if (options.fullPage !== undefined && typeof options.fullPage !== "boolean")
            throw new Error("Invalid fullPage option");
        const fullPage = options.fullPage === true;
        if (fullPage && options.clip !== undefined)
            throw new Error("Full-page screenshot cannot use a clip");
        let clip;
        if (fullPage) {
            const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
            const content = isObject(metrics) ? metrics.cssContentSize : null;
            if (!isObject(content) || ![content.x, content.y, content.width, content.height].every(value => typeof value === "number" && Number.isFinite(value)))
                throw new Error("Page dimensions are unavailable");
            const { x, y, width, height } = content;
            if (width <= 0 || height <= 0 || width > 32767 || height > 32767 || width * height > 32_000_000)
                throw new Error("Page is too large for a full-page screenshot");
            clip = { x, y, width, height, scale: 1 };
        }
        else if (options.clip !== undefined) {
            const rect = { ...options.clip };
            if (![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) || rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0)
                throw new Error("Invalid screenshot clip");
            const metrics = await this.browser.cdp.call(this.id, "Page.getLayoutMetrics");
            const viewport = isObject(metrics) ? metrics.cssVisualViewport : null;
            if (!isObject(viewport) || ![viewport.pageX, viewport.pageY, viewport.clientWidth, viewport.clientHeight].every(value => typeof value === "number" && Number.isFinite(value)))
                throw new Error("Browser viewport is unavailable");
            const { pageX, pageY, clientWidth, clientHeight } = viewport;
            if (rect.x + rect.width > clientWidth || rect.y + rect.height > clientHeight)
                throw new Error("Screenshot clip is outside the viewport");
            clip = { x: pageX + rect.x, y: pageY + rect.y, width: rect.width, height: rect.height, scale: 1 };
        }
        const result = await this.browser.cdp.call(this.id, "Page.captureScreenshot", { format: "png", ...(clip ? { clip, captureBeyondViewport: fullPage } : {}) });
        if (!isObject(result) || typeof result.data !== "string" || !result.data) {
            throw new Error("Browser returned an invalid screenshot");
        }
        return Buffer.from(result.data, "base64");
    }
    evaluate(expression, options = {}) {
        return this.browser.cdp.evaluate(this.id, expression, options);
    }
    close() {
        return this.browser.cdp.call(this.id, "Page.close");
    }
}
export class OpenBrowserUseImage extends Uint8Array {
    toBase64() { return Buffer.from(this).toString("base64"); }
}
function cuaModifiers(keys = []) {
    if (!Array.isArray(keys))
        throw new Error("Invalid mouse modifiers");
    const bits = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };
    const normalized = keys.map(key => key === "ControlOrMeta" ? (process.platform === "darwin" ? "Meta" : "Control") : key);
    if (new Set(normalized).size !== normalized.length || normalized.some(key => typeof key !== "string" || !Object.hasOwn(bits, key)))
        throw new Error("Invalid mouse modifiers");
    return normalized.reduce((mask, key) => mask | bits[key], 0);
}
export class OpenBrowserUseTabCUA {
    tab;
    constructor(tab) {
        this.tab = tab;
    }
    click(options) { return this.tab.clickAt(options.x, options.y, { button: options.button, modifiers: cuaModifiers(options.keypress) }); }
    double_click(options) { return this.tab.clickAt(options.x, options.y, { double: true, modifiers: cuaModifiers(options.keypress) }); }
    move(options) { return this.tab.hoverAt(options.x, options.y, cuaModifiers(options.keys)); }
    scroll(options) { return this.tab.scrollAt(options.x, options.y, options.scrollX, options.scrollY, cuaModifiers(options.keypress)); }
    drag(options) { return this.tab.dragPath(options.path, cuaModifiers(options.keys)); }
    type(options) { return this.tab.typeAtFocus(options.text); }
    keypress(options) {
        if (!Array.isArray(options.keys) || !options.keys.length || options.keys.some(key => typeof key !== "string" || !key))
            throw new Error("Invalid key combination");
        const aliases = { ctrl: "ControlOrMeta", control: "Control", controlormeta: "ControlOrMeta", cmd: "Meta", meta: "Meta", alt: "Alt", option: "Alt", shift: "Shift", esc: "Escape", return: "Enter", del: "Delete", space: "Space", left: "ArrowLeft", right: "ArrowRight", up: "ArrowUp", down: "ArrowDown" };
        const keys = options.keys.map(key => Object.hasOwn(aliases, key.toLowerCase()) ? aliases[key.toLowerCase()] : key);
        if (keys.length > 1 && keys.at(-1) === "+") {
            keys[keys.length - 1] = "=";
            if (!keys.includes("Shift"))
                keys.splice(keys.length - 1, 0, "Shift");
        }
        return this.tab.pressKey(keys.join("+"));
    }
    async get_visible_screenshot() { return new OpenBrowserUseImage(await this.tab.getScreenshot()); }
}
export class OpenBrowserUseTabDomCUA {
    tab;
    snapshot = false;
    generation = 0;
    connectionGeneration = -1;
    busy = false;
    ids = new Map();
    constructor(tab) {
        this.tab = tab;
    }
    invalidate() { this.generation++; this.snapshot = false; this.ids.clear(); }
    beginAction() {
        if (this.busy)
            throw new Error('DOM CUA action is already in progress');
        this.busy = true;
        this.invalidate();
        return () => { this.invalidate(); this.busy = false; };
    }
    async get_visible_dom() {
        if (this.busy)
            throw new Error('DOM CUA action is already in progress');
        this.invalidate();
        const generation = this.generation;
        const ids = new Map();
        const step = { selector: 'a[href],button,input,textarea,select,summary,details,label,img,video,audio,[role],[onclick],[contenteditable="true"],[tabindex]', before: [{ visible: true }] };
        const frames = await this.tab.domFrames(), connectionGeneration = this.tab.browser.client.connectionGeneration;
        const nodes = [];
        let total = 0, visibilityIncomplete = false;
        const frameVisibility = new Map(), frameClips = new Map();
        for (const frame of frames) {
            const inViewport = await this.tab.domFrameInViewport(frame, frames);
            frameVisibility.set(frame.id, inViewport);
            const clip = inViewport ? await this.tab.domFrameClip(frame, frames) : null;
            frameClips.set(frame.id, clip);
            if (!clip)
                continue;
            const snapshot = await this.tab.queryCss(step, undefined, [], undefined, undefined, frame.id);
            if (JSON.stringify(snapshot.frames) !== JSON.stringify(frames))
                throw new RetryablePreflightError("Frame tree changed; observe again");
            total += snapshot.ids.length;
            if (total > 1000)
                throw new Error("DOM snapshot matched more than 1000 elements");
            if (!snapshot.frame)
                throw new RetryablePreflightError('DOM frame unavailable; observe again');
            const sessionId = snapshot.frame.sessionId;
            const world = await this.tab.browser.cdp.call(this.tab.id, 'Page.createIsolatedWorld', { frameId: snapshot.frame.id, worldName: 'open-browser-use-selector' }, { sessionId });
            if (!isObject(world) || typeof world.executionContextId !== 'number')
                throw new RetryablePreflightError('DOM context unavailable; observe again');
            const objects = [];
            try {
                for (const id of snapshot.ids) {
                    const resolved = await this.tab.browser.cdp.call(this.tab.id, 'DOM.resolveNode', { backendNodeId: id, executionContextId: world.executionContextId }, { sessionId });
                    const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                    if (typeof objectId !== 'string')
                        throw new RetryablePreflightError('DOM target changed; observe again');
                    objects.push({ id, objectId });
                }
                const observeIntersections = async () => {
                    if (!objects.length)
                        return [];
                    if (visibilityIncomplete)
                        return objects.map(() => true);
                    const observed = await this.tab.browser.cdp.call(this.tab.id, 'Runtime.callFunctionOn', { objectId: objects[0].objectId, arguments: objects.slice(1).map(item => ({ objectId: item.objectId })), returnByValue: true, awaitPromise: true, functionDeclaration: `async function(...others){const nodes=[this,...others];return await new Promise((resolve,reject)=>{const indices=new Map(nodes.map((node,index)=>[node,index])),values=Array(nodes.length),seen=new Set();const timer=setTimeout(()=>{observer.disconnect();reject(new Error('Intersection observation timed out'))},3000);const observer=new IntersectionObserver(entries=>{for(const entry of entries){const index=indices.get(entry.target);if(index===undefined)continue;values[index]=entry.isIntersecting && entry.intersectionRect.width>0 && entry.intersectionRect.height>0;seen.add(index)}if(seen.size===nodes.length){clearTimeout(timer);observer.disconnect();resolve(values)}});for(const node of nodes)observer.observe(node)})}` }, { sessionId });
                    const exception = isObject(observed) && isObject(observed.exceptionDetails) && isObject(observed.exceptionDetails.exception) ? observed.exceptionDetails.exception.description : undefined;
                    if (typeof exception === 'string' && exception.includes('Intersection observation timed out')) {
                        visibilityIncomplete = true;
                        return objects.map(() => true);
                    }
                    const values = isObject(observed) && isObject(observed.result) ? observed.result.value : null;
                    if (!Array.isArray(values) || values.length !== objects.length || values.some(value => typeof value !== 'boolean'))
                        throw new RetryablePreflightError('DOM visibility unavailable; observe again');
                    return values;
                };
                const intersections = await observeIntersections();
                for (let i = 0; i < objects.length; i++) {
                    if (!intersections[i])
                        continue;
                    const { id, objectId } = objects[i];
                    const result = await this.tab.browser.cdp.call(this.tab.id, 'Runtime.callFunctionOn', { objectId, returnByValue: true, arguments: [{ value: clip }], functionDeclaration: `function(clip){if(!this.isConnected)return null;const r=this.getBoundingClientRect();if(r.right<=clip.left || r.bottom<=clip.top || r.left>=clip.right || r.top>=clip.bottom)return {outside:true};return (${domIdentityFunction}).call(this)}` }, { sessionId });
                    const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                    if (!isObject(value))
                        throw new RetryablePreflightError('DOM target changed; observe again');
                    if (value.outside === true)
                        continue;
                    if (typeof value.tag !== 'string' || (value.role !== null && typeof value.role !== 'string') || (value.name !== null && typeof value.name !== 'string') || (value.type !== null && typeof value.type !== 'string') || typeof value.disabled !== 'boolean' || ![true, false, 'mixed', null].includes(value.checked))
                        throw new RetryablePreflightError('DOM target changed; observe again');
                    const node_id = randomUUID(), identity = { tag: value.tag, role: value.role, name: value.name, type: value.type, disabled: value.disabled, checked: value.checked };
                    ids.set(node_id, { snapshot, id, identity });
                    nodes.push({ node_id, frame_id: frame.id, ...identity });
                }
                const beforeIncomplete = visibilityIncomplete, latestIntersections = await observeIntersections();
                if (!beforeIncomplete && !visibilityIncomplete && JSON.stringify(latestIntersections) !== JSON.stringify(intersections))
                    throw new RetryablePreflightError('DOM visibility changed; observe again');
            }
            finally {
                for (const { objectId } of objects)
                    await this.tab.browser.cdp.call(this.tab.id, 'Runtime.releaseObject', { objectId }, { sessionId }).catch(() => { });
            }
            const fresh = await this.tab.queryCss(step, undefined, [], undefined, undefined, frame.id);
            if (fresh.documentId !== snapshot.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(snapshot.frames) || JSON.stringify(fresh.ids) !== JSON.stringify(snapshot.ids)) {
                throw new RetryablePreflightError('DOM changed; observe again');
            }
        }
        if (JSON.stringify(await this.tab.domFrames()) !== JSON.stringify(frames))
            throw new RetryablePreflightError("Frame tree changed; observe again");
        for (const frame of frames) {
            const visible = await this.tab.domFrameInViewport(frame, frames);
            if (visible !== frameVisibility.get(frame.id) || JSON.stringify(visible ? await this.tab.domFrameClip(frame, frames) : null) !== JSON.stringify(frameClips.get(frame.id)))
                throw new RetryablePreflightError("Frame visibility changed; observe again");
        }
        if (this.busy || this.generation !== generation || this.tab.browser.client.connectionGeneration !== connectionGeneration)
            throw new RetryablePreflightError('DOM snapshot superseded; observe again');
        this.ids = ids;
        this.connectionGeneration = connectionGeneration;
        this.snapshot = true;
        return { nodes, ...(visibilityIncomplete ? { visibility_incomplete: true } : {}) };
    }
    target(node_id) {
        const target = this.ids.get(node_id);
        if (!this.snapshot || !target || this.tab.browser.client.connectionGeneration !== this.connectionGeneration)
            throw new Error('Unknown or stale DOM node id');
        return target;
    }
    async clickNode(node_id, double) {
        const { snapshot, id, identity } = this.target(node_id), finish = this.beginAction();
        try {
            if (!snapshot.frame || !await this.tab.domFrameInViewport(snapshot.frame, snapshot.frames))
                throw new RetryablePreflightError('DOM frame is outside the viewport; observe again');
            await this.tab.actCss(snapshot, id, false, undefined, undefined, double, undefined, undefined, false, undefined, identity, this.connectionGeneration);
        }
        finally {
            finish();
        }
    }
    click(options) { return this.clickNode(options.node_id, false); }
    double_click(options) { return this.clickNode(options.node_id, true); }
    async keypress(options) { const finish = this.beginAction(); try {
        await this.tab.cua.keypress(options);
    }
    finally {
        finish();
    } }
    async type(options) { const finish = this.beginAction(); try {
        await this.tab.cua.type(options);
    }
    finally {
        finish();
    } }
    async scroll(options) {
        const target = options.node_id !== undefined ? this.target(options.node_id) : undefined, finish = this.beginAction();
        try {
            let point, frame;
            if (options.node_id !== undefined) {
                const { snapshot, id, identity } = target;
                if (!snapshot.frame || !await this.tab.domFrameInViewport(snapshot.frame, snapshot.frames))
                    throw new RetryablePreflightError('DOM frame is outside the viewport; observe again');
                if (await this.tab.readCss(snapshot, id, 'visible') !== true)
                    throw new RetryablePreflightError('DOM target is hidden; observe again');
                const world = await this.tab.browser.cdp.call(this.tab.id, 'Page.createIsolatedWorld', { frameId: snapshot.frame.id, worldName: 'open-browser-use-selector' }, { sessionId: snapshot.frame?.sessionId });
                if (!isObject(world) || typeof world.executionContextId !== 'number')
                    throw new RetryablePreflightError('DOM context unavailable; observe again');
                const resolved = await this.tab.browser.cdp.call(this.tab.id, 'DOM.resolveNode', { backendNodeId: id, executionContextId: world.executionContextId }, { sessionId: snapshot.frame?.sessionId });
                const objectId = isObject(resolved) && isObject(resolved.object) ? resolved.object.objectId : undefined;
                if (typeof objectId !== 'string')
                    throw new RetryablePreflightError('DOM target changed; observe again');
                try {
                    const result = await this.tab.browser.cdp.call(this.tab.id, 'Runtime.callFunctionOn', { objectId, returnByValue: true, arguments: [{ value: identity }], functionDeclaration: `function(expected){if(!this.isConnected)return null;const actual=(${domIdentityFunction}).call(this);if(!actual || Object.keys(expected).some(key=>actual[key]!==expected[key]))return null;const r=this.getBoundingClientRect(),x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;let target=this,root=target.getRootNode();while(true){const hit=root.elementFromPoint(x,y);if(!hit || (hit!==target && !target.contains(hit)))return null;if(!(root instanceof ShadowRoot))return {x,y};target=root.host;root=target.getRootNode()}}` }, { sessionId: snapshot.frame?.sessionId });
                    const value = isObject(result) && isObject(result.result) ? result.result.value : null;
                    if (!isObject(value) || typeof value.x !== 'number' || typeof value.y !== 'number')
                        throw new RetryablePreflightError('DOM target changed; observe again');
                    const mapped = await this.tab.domFramePoint(snapshot, { x: value.x, y: value.y });
                    point = mapped.point;
                    if (snapshot.frame.sessionId)
                        frame = { sessionId: snapshot.frame.sessionId, contextId: world.executionContextId, inputPoint: mapped.inputPoint };
                    await this.tab.readCss(snapshot, id, 'visible');
                }
                finally {
                    await this.tab.browser.cdp.call(this.tab.id, 'Runtime.releaseObject', { objectId }, { sessionId: snapshot.frame?.sessionId }).catch(() => { });
                }
            }
            else {
                const metrics = await this.tab.browser.cdp.call(this.tab.id, 'Page.getLayoutMetrics');
                const viewport = isObject(metrics) && isObject(metrics.cssVisualViewport) ? metrics.cssVisualViewport : null;
                if (!viewport || typeof viewport.clientWidth !== 'number' || typeof viewport.clientHeight !== 'number')
                    throw new Error('Browser viewport is unavailable');
                point = { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 };
            }
            if (target && this.tab.browser.client.connectionGeneration !== this.connectionGeneration)
                throw new RetryablePreflightError('Connection changed; observe again');
            await this.tab.scrollAt(point.x, point.y, options.x, options.y, 0, target ? this.connectionGeneration : undefined, frame);
        }
        finally {
            finish();
        }
    }
}
export class OpenBrowserUseTabClipboard {
    tab;
    constructor(tab) {
        this.tab = tab;
    }
    async readText() {
        const result = await this.tab.browser.client.readClipboardText(this.tab.id);
        if (!isObject(result) || typeof result.text !== "string")
            throw new Error("Browser returned invalid clipboard text");
        return result.text;
    }
    async writeText(text) {
        if (typeof text !== "string")
            throw new Error("Clipboard text must be a string");
        await this.tab.browser.client.writeClipboardText(this.tab.id, text);
    }
    async read() {
        const result = await this.tab.browser.client.readClipboard(this.tab.id);
        if (!isObject(result) || !Array.isArray(result.items))
            throw new Error("Browser returned invalid clipboard items");
        return result.items.map(item => {
            if (!isObject(item) || !Array.isArray(item.entries) || (item.presentation_style !== undefined && !["unspecified", "inline", "attachment"].includes(String(item.presentation_style))))
                throw new Error("Browser returned invalid clipboard item");
            const entries = item.entries.map(entry => {
                if (!isObject(entry) || typeof entry.mime_type !== "string" || !entry.mime_type || (entry.text !== undefined && typeof entry.text !== "string") || (entry.base64 !== undefined && typeof entry.base64 !== "string") || (typeof entry.text === "string") === (typeof entry.base64 === "string"))
                    throw new Error("Browser returned invalid clipboard entry");
                return { mimeType: entry.mime_type, ...(typeof entry.text === "string" ? { text: entry.text } : { base64: entry.base64 }) };
            });
            return { entries, ...(item.presentation_style !== undefined ? { presentationStyle: item.presentation_style } : {}) };
        });
    }
    async write(items) {
        if (!Array.isArray(items))
            throw new Error("Clipboard items must be an array");
        const wire = items.map(item => {
            if (!item || !Array.isArray(item.entries) || !item.entries.length || (item.presentationStyle !== undefined && !["unspecified", "inline", "attachment"].includes(item.presentationStyle)))
                throw new Error("Invalid clipboard item");
            const seen = new Set();
            const entries = item.entries.map(entry => {
                if (!entry || typeof entry.mimeType !== "string" || !entry.mimeType || seen.has(entry.mimeType) || (entry.text !== undefined && typeof entry.text !== "string") || (entry.base64 !== undefined && typeof entry.base64 !== "string") || (typeof entry.text === "string") === (typeof entry.base64 === "string"))
                    throw new Error("Invalid clipboard entry");
                if (entry.base64 !== undefined && !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}(?:==)?|[A-Za-z0-9+/]{3}=?)?$/.test(entry.base64))
                    throw new Error("Invalid clipboard base64");
                seen.add(entry.mimeType);
                return { mime_type: entry.mimeType, ...(typeof entry.text === "string" ? { text: entry.text } : { base64: entry.base64 }) };
            });
            return { entries, ...(item.presentationStyle !== undefined ? { presentation_style: item.presentationStyle } : {}) };
        });
        await this.tab.browser.client.writeClipboard(this.tab.id, wire);
    }
}
export class OpenBrowserUseTabDev {
    tab;
    constructor(tab) {
        this.tab = tab;
    }
    async watch() { await this.tab.browser.cdp.watchLogs(this.tab.id); }
    async logs(options = {}) {
        if (!options || typeof options !== "object" || (options.filter !== undefined && typeof options.filter !== "string") ||
            (options.limit !== undefined && (!Number.isSafeInteger(options.limit) || options.limit < 0 || options.limit > 500)) ||
            (options.levels !== undefined && (!Array.isArray(options.levels) || options.levels.some(level => !["debug", "info", "log", "warn", "warning", "error"].includes(level)))))
            throw new Error("Invalid log options");
        await this.watch();
        const levels = options.levels?.map(level => level === "warning" ? "warn" : level);
        const entries = this.tab.browser.cdp.logs(this.tab.id).filter(entry => (!levels || levels.includes(entry.level)) && (options.filter === undefined || entry.message.includes(options.filter)));
        return options.limit === undefined ? entries : options.limit === 0 ? [] : entries.slice(-options.limit);
    }
}
export class OpenBrowserUseTabPlaywright {
    tab;
    constructor(tab) {
        this.tab = tab;
    }
    waitForLoadState(options = {}) {
        return this.tab.waitForLoadState(options);
    }
    expectNavigation(action, options = {}) {
        return this.tab.expectNavigation(action, options);
    }
    waitForURL(url, options = {}) {
        return this.tab.waitForURL(url, options);
    }
    domSnapshot() {
        return this.tab.domSnapshot();
    }
    async screenshot(options = {}) {
        return new OpenBrowserUseImage(await this.tab.getScreenshot(options));
    }
    waitForTimeout(timeoutMs) {
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid timeout");
        return new Promise(resolve => setTimeout(resolve, timeoutMs));
    }
    waitForEvent(event, options = {}) {
        if (event !== "download" && event !== "filechooser")
            throw new Error("Unsupported browser event");
        const preparing = event === "download" ? this.tab.prepareDownload(options) : this.tab.prepareFileChooser(options);
        this.tab.browser.cdp.blockUntilPrepared(this.tab.id, preparing);
        return preparing.then(async (wait) => await wait.wait());
    }
    frameLocator(selector) {
        return new OpenBrowserUseFrameLocator(this.tab, []).frameLocator(selector);
    }
    locator(selector, options) { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab, selector), options); }
    getByTestId(testId) { return this.locator(testIdSelector(testId)); }
    getByRole(role, options = {}) {
        if (typeof role !== "string" || !role || !options || typeof options !== "object" || Array.isArray(options) ||
            Object.keys(options).some(key => !["name", "exact", "level", "checked", "disabled", "pressed", "selected", "expanded"].includes(key)) ||
            (options.name !== undefined && typeof options.name !== "string" && !types.isRegExp(options.name)) ||
            (options.level !== undefined && (role !== "heading" || !Number.isSafeInteger(options.level) || options.level < 1)) ||
            [options.exact, options.checked, options.disabled, options.pressed, options.selected, options.expanded].some(value => value !== undefined && typeof value !== "boolean"))
            throw new Error("Invalid role locator");
        return new OpenBrowserUseRoleLocator(this.tab, [role === "img" ? "image" : role], { ...options, ...(options.name !== undefined ? { name: copyMatcher(options.name) } : {}) });
    }
    getByLabel(name, options = {}) {
        if ((typeof name !== "string" && !types.isRegExp(name)) || (options.exact !== undefined && typeof options.exact !== "boolean"))
            throw new Error("Invalid label locator");
        return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "switch", "slider", "spinbutton", "Date", "DateTime", "InputTime"], { name: copyMatcher(name), ...options });
    }
    getByText(text, options = {}) {
        if ((typeof text !== "string" && !types.isRegExp(text)) || (options.exact !== undefined && typeof options.exact !== "boolean"))
            throw new Error("Invalid text locator");
        return new OpenBrowserUseRoleLocator(this.tab, ["StaticText"], { name: copyMatcher(text), ...options }, undefined, true);
    }
    getByAltText(altText, options = {}) {
        if ((typeof altText !== "string" && !types.isRegExp(altText)) || (options.exact !== undefined && typeof options.exact !== "boolean"))
            throw new Error("Invalid alt text locator");
        return new OpenBrowserUseRoleLocator(this.tab, ["image", "button", "link"], { name: copyMatcher(altText), ...options }, undefined, false, "altText");
    }
    getByPlaceholder(placeholder, options = {}) {
        if ((typeof placeholder !== "string" && !types.isRegExp(placeholder)) || (options.exact !== undefined && typeof options.exact !== "boolean"))
            throw new Error("Invalid placeholder locator");
        return new OpenBrowserUseRoleLocator(this.tab, ["textbox", "searchbox", "combobox", "spinbutton"], { name: copyMatcher(placeholder), ...options }, undefined, false, "placeholder");
    }
}
export class OpenBrowserUseFrameLocator {
    tab;
    path;
    constructor(tab, path) {
        this.tab = tab;
        this.path = path;
    }
    frameLocator(selector) {
        if (typeof selector !== "string" || !selector.trim() || selector.length > 4096 || this.path.length >= 32)
            throw new Error("Invalid frame selector");
        return new OpenBrowserUseFrameLocator(this.tab, [...this.path, selector]);
    }
    locator(selector, options) { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab, selector, this.path), options); }
    getByTestId(testId) { return this.locator(testIdSelector(testId)); }
    getByRole(role, options = {}) { return this.tab.playwright.getByRole(role, options).withinFrame(this.path); }
    getByLabel(name, options = {}) { return this.tab.playwright.getByLabel(name, options).withinFrame(this.path); }
    getByText(text, options = {}) { return this.tab.playwright.getByText(text, options).withinFrame(this.path); }
    getByAltText(text, options = {}) { return this.tab.playwright.getByAltText(text, options).withinFrame(this.path); }
    getByPlaceholder(text, options = {}) { return this.tab.playwright.getByPlaceholder(text, options).withinFrame(this.path); }
}
export class OpenBrowserUseCssLocator {
    tab;
    selector;
    framePath;
    position;
    scopes;
    before;
    after;
    union;
    semanticScope;
    constructor(tab, selector, framePath, position, scopes = [], before = [], after = [], union, semanticScope) {
        this.tab = tab;
        this.selector = selector;
        this.framePath = framePath;
        this.position = position;
        this.scopes = scopes;
        this.before = before;
        this.after = after;
        this.union = union;
        this.semanticScope = semanticScope;
        if (typeof selector !== "string" || !selector.trim() || selector.length > 4096)
            throw new Error("Invalid CSS selector");
    }
    nth(index) {
        if (!Number.isSafeInteger(index) || index < 0)
            throw new Error("Locator index must be a non-negative integer");
        return new OpenBrowserUseCssLocator(this.tab, this.selector, this.framePath, this.position === undefined ? index : index === 0 ? this.position : Number.MAX_SAFE_INTEGER, this.scopes, this.before, this.after, this.union, this.semanticScope);
    }
    first() { return this.nth(0); }
    last() { return this.position === undefined ? new OpenBrowserUseCssLocator(this.tab, this.selector, this.framePath, -1, this.scopes, this.before, this.after, this.union, this.semanticScope) : this; }
    locator(selector, options) {
        if (this.scopes.length >= 31)
            throw new Error("CSS locator nesting exceeds 32 levels");
        return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab, selector, this.framePath, undefined, [...this.scopes, this.step()], [], [], undefined, this.semanticScope), options);
    }
    /** @internal */
    getFramePath() { return this.framePath; }
    /** @internal */
    isRelativeTo(tab, framePath) {
        return this.tab.browser === tab.browser && this.tab.id === tab.id && JSON.stringify(this.framePath ?? null) === JSON.stringify(framePath ?? null) && !this.semanticScope;
    }
    /** @internal */
    async countWithin(observation, index) {
        return (await this.tab.queryCss(this.step(), this.framePath, this.scopes, undefined, { observation, index })).ids.length;
    }
    getByTestId(testId) { return this.locator(testIdSelector(testId)); }
    getByRole(role, options = {}) { return this.tab.playwright.getByRole(role, options).withinCss(this); }
    getByLabel(name, options = {}) { return this.tab.playwright.getByLabel(name, options).withinCss(this); }
    getByText(text, options = {}) { return this.tab.playwright.getByText(text, options).withinCss(this); }
    getByAltText(text, options = {}) { return this.tab.playwright.getByAltText(text, options).withinCss(this); }
    getByPlaceholder(text, options = {}) { return this.tab.playwright.getByPlaceholder(text, options).withinCss(this); }
    /** @internal */
    snapshot() { return this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope); }
    step() { return { selector: this.selector, ...(this.position !== undefined ? { position: this.position } : {}), before: this.before, after: this.after, ...(this.union ? { union: this.union } : {}) }; }
    innerSteps(value) {
        if (!(value instanceof OpenBrowserUseCssLocator) || (value.tab.browser !== this.tab.browser || value.tab.id !== this.tab.id) || JSON.stringify(value.framePath ?? null) !== JSON.stringify(this.framePath ?? null))
            throw new Error("Filter locator must belong to the same tab and frame");
        if (value.semanticScope && value.semanticScope !== this.semanticScope)
            throw new Error("Filter locator must share the semantic scope");
        const steps = [...value.scopes, value.step()];
        const depth = (items, level) => {
            if (level > 8)
                throw new Error("Locator filter nesting exceeds 8 levels");
            for (const step of items) {
                if (step.union) {
                    depth(step.union[0], level + 1);
                    depth(step.union[1], level + 1);
                }
                for (const filter of [...(step.before ?? []), ...(step.after ?? [])]) {
                    if (filter.has)
                        depth(filter.has, level + 1);
                    if (filter.hasNot)
                        depth(filter.hasNot, level + 1);
                    if (filter.and)
                        depth(filter.and, level + 1);
                }
            }
        };
        depth(steps, 2);
        return steps;
    }
    and(locator) {
        if (locator?.semanticScope !== this.semanticScope)
            throw new Error("Intersection locators must share a semantic scope");
        const filter = { and: this.innerSteps(locator) };
        return new OpenBrowserUseCssLocator(this.tab, this.selector, this.framePath, this.position, this.scopes, this.position === undefined ? [...this.before, filter] : this.before, this.position === undefined ? this.after : [...this.after, filter], this.union, this.semanticScope);
    }
    or(locator) {
        if (locator?.semanticScope !== this.semanticScope)
            throw new Error("Union locators must share a semantic scope");
        return new OpenBrowserUseCssLocator(this.tab, "*", this.framePath, undefined, [], [], [], [this.innerSteps(this), this.innerSteps(locator)], this.semanticScope);
    }
    filter(options) {
        if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["hasText", "hasNotText", "has", "hasNot", "visible"].includes(key)) ||
            (options.hasText === undefined && options.hasNotText === undefined && options.has === undefined && options.hasNot === undefined && options.visible === undefined) || (options.visible !== undefined && typeof options.visible !== "boolean") || [options.hasText, options.hasNotText].some(value => value !== undefined && (typeof value === "string" ? value.length > 30_000 : !types.isRegExp(value))))
            throw new Error("Invalid locator filter");
        const encode = (value) => typeof value === "string" ? value : { source: value.source, flags: value.flags };
        const filter = { ...(options.hasText !== undefined ? { hasText: encode(options.hasText) } : {}), ...(options.hasNotText !== undefined ? { hasNotText: encode(options.hasNotText) } : {}), ...(options.has !== undefined ? { has: this.innerSteps(options.has) } : {}), ...(options.hasNot !== undefined ? { hasNot: this.innerSteps(options.hasNot) } : {}), ...(options.visible !== undefined ? { visible: options.visible } : {}) };
        return new OpenBrowserUseCssLocator(this.tab, this.selector, this.framePath, this.position, this.scopes, this.position === undefined ? [...this.before, filter] : this.before, this.position === undefined ? this.after : [...this.after, filter], this.union, this.semanticScope);
    }
    async count() { return (await this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope)).ids.length; }
    async all() { return Array.from({ length: await this.count() }, (_, i) => this.nth(i)); }
    async allTextContents(options = {}) {
        const timeoutMs = options.timeoutMs ?? 5000;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            try {
                const snapshot = await this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope), values = [];
                let total = 0;
                for (const id of snapshot.ids) {
                    const value = await this.tab.readCss(snapshot, id, "textContent");
                    if (typeof value !== "string")
                        throw new RetryablePreflightError("Target text is unavailable; observe again");
                    total += value.length;
                    if (total > 1_000_000)
                        throw new Error("Locator values exceed the 1000000 character limit");
                    values.push(value);
                }
                return values;
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError) || performance.now() >= deadline)
                    throw error;
                await new Promise(resolve => setTimeout(resolve, Math.min(100, deadline - performance.now())));
            }
        }
    }
    async perform(action, timeoutMs = 5000) {
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            try {
                const snapshot = await this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope);
                const ids = snapshot.ids;
                if (ids.length > 1)
                    throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
                if (ids.length)
                    return await action(snapshot, ids[0]);
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError))
                    throw error;
            }
            const remaining = deadline - performance.now();
            if (remaining <= 0)
                throw new Error(`Locator target unavailable before timeout (${timeoutMs} ms)`);
            await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
        }
    }
    read(mode, name = "", timeoutMs = 5000) {
        return this.perform(async (snapshot, id) => await this.tab.readCss(snapshot, id, mode, name), timeoutMs);
    }
    isEnabled() { return this.perform(async (snapshot, id) => await this.tab.readCss(snapshot, id, "enabled")); }
    isChecked() { return this.perform(async (snapshot, id) => await this.tab.readCss(snapshot, id, "checked")); }
    async isVisible() {
        const snapshot = await this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope), ids = snapshot.ids;
        if (!ids.length)
            return false;
        if (ids.length > 1)
            throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
        return await this.tab.readCss(snapshot, ids[0], "visible");
    }
    async waitFor(options) {
        if (!options || !["attached", "detached", "visible", "hidden"].includes(options.state))
            throw new Error("Invalid locator wait state");
        const timeoutMs = options.timeoutMs ?? 5000;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            try {
                const snapshot = await this.tab.queryCss(this.step(), this.framePath, this.scopes, this.semanticScope), ids = snapshot.ids;
                if (ids.length > 1)
                    throw new Error(`Locator matched ${ids.length} elements; expected exactly one`);
                const matched = options.state === 'attached' || options.state === 'detached' ? ids.length > 0 : ids.length > 0 && await this.tab.readCss(snapshot, ids[0], "visible") === true;
                if (matched === (options.state === 'attached' || options.state === 'visible'))
                    return;
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError))
                    throw error;
            }
            const remaining = deadline - performance.now();
            if (remaining <= 0)
                throw new Error(`Timed out waiting for locator to become ${options.state}`);
            await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
        }
    }
    downloadMedia(options = {}) {
        return this.first().perform(async (snapshot, id) => { if (!snapshot.frame)
            throw new RetryablePreflightError("Download target is unavailable; observe again"); await this.tab.triggerMediaDownload(id, snapshot.frame, () => this.tab.readCss(snapshot, id, "attribute", "src")); }, options.timeoutMs);
    }
    click(options = {}) { const mouse = locatorClickOptions(options); return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, undefined, undefined, false, undefined, undefined, false, mouse); }, options.timeoutMs); }
    dblclick(options = {}) { const mouse = locatorClickOptions(options); return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, undefined, undefined, true, undefined, undefined, false, mouse); }, options.timeoutMs); }
    hover(options = {}) { return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, true); }, options.timeoutMs); }
    check(options = {}) { return this.setChecked(true, options); }
    uncheck(options = {}) { return this.setChecked(false, options); }
    setChecked(checked, options = {}) {
        if (typeof checked !== "boolean")
            throw new Error("Checked state must be a boolean");
        return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, undefined, undefined, false, checked); }, options.timeoutMs);
    }
    press(key, options = {}) {
        if (typeof key !== "string")
            throw new Error("Invalid key");
        return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, key); }, options.timeoutMs);
    }
    fill(text, options = {}) {
        if (typeof text !== "string")
            throw new Error("Text must be a string");
        return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, undefined, text); }, options.timeoutMs);
    }
    type(text, options = {}) {
        if (typeof text !== "string")
            throw new Error("Text must be a string");
        return this.perform(async (snapshot, id) => { await this.tab.actCss(snapshot, id, false, undefined, text, false, undefined, undefined, true); }, options.timeoutMs);
    }
    async selectOption(values, options = {}) {
        const specs = selectSpecs(values);
        const result = await this.perform((snapshot, id) => this.tab.actCss(snapshot, id, false, undefined, undefined, false, undefined, specs), options.timeoutMs);
        if (!Array.isArray(result))
            throw new Error("Invalid selected options result");
        return result;
    }
    async innerText(options = {}) {
        const value = await this.read("innerText", "", options.timeoutMs);
        if (value === null)
            throw new Error("Target text is unavailable");
        return value;
    }
    textContent(options = {}) { return this.read("textContent", "", options.timeoutMs); }
    getAttribute(name, options = {}) {
        if (typeof name !== "string" || !name || name.length > 256)
            throw new Error("Invalid attribute name");
        return this.read("attribute", name, options.timeoutMs);
    }
}
export class OpenBrowserUseRoleLocator {
    tab;
    roles;
    options;
    position;
    textMatch;
    field;
    scope;
    filtersBefore;
    filtersAfter;
    framePath;
    cssScope;
    constructor(tab, roles, options, position, textMatch = false, field = "name", scope, filtersBefore = [], filtersAfter = [], framePath, cssScope) {
        this.tab = tab;
        this.roles = roles;
        this.options = options;
        this.position = position;
        this.textMatch = textMatch;
        this.field = field;
        this.scope = scope;
        this.filtersBefore = filtersBefore;
        this.filtersAfter = filtersAfter;
        this.framePath = framePath;
        this.cssScope = cssScope;
    }
    /** @internal */
    withinFrame(path) {
        return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, this.position, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter, [...path], this.cssScope);
    }
    /** @internal */
    withinCss(scope) {
        return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, this.position, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter, this.framePath ?? scope.getFramePath(), scope);
    }
    nth(index) {
        if (!Number.isSafeInteger(index) || index < 0)
            throw new Error("Locator index must be a non-negative integer");
        if (this.position !== undefined)
            return index === 0 ? this : new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, Number.MAX_SAFE_INTEGER, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter, this.framePath, this.cssScope);
        return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, index, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter, this.framePath, this.cssScope);
    }
    first() { return this.nth(0); }
    last() {
        return this.position !== undefined ? this : new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, -1, this.textMatch, this.field, this.scope, this.filtersBefore, this.filtersAfter, this.framePath, this.cssScope);
    }
    locator(selector, options) { return applyLocatorOptions(new OpenBrowserUseCssLocator(this.tab, selector, this.framePath, undefined, [], [], [], undefined, this), options); }
    getByTestId(testId) { return this.locator(testIdSelector(testId)); }
    child(locator) {
        return new OpenBrowserUseRoleLocator(this.tab, locator.roles, locator.options, locator.position, locator.textMatch, locator.field, this, locator.filtersBefore, locator.filtersAfter, this.framePath);
    }
    getByRole(role, options = {}) { return this.child(this.tab.playwright.getByRole(role, options)); }
    getByLabel(name, options = {}) { return this.child(this.tab.playwright.getByLabel(name, options)); }
    getByText(text, options = {}) { return this.child(this.tab.playwright.getByText(text, options)); }
    getByAltText(text, options = {}) { return this.child(this.tab.playwright.getByAltText(text, options)); }
    getByPlaceholder(text, options = {}) { return this.child(this.tab.playwright.getByPlaceholder(text, options)); }
    filter(options) {
        if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => !["hasText", "hasNotText", "has", "hasNot", "visible"].includes(key)) ||
            (options.hasText === undefined && options.hasNotText === undefined && options.has === undefined && options.hasNot === undefined && options.visible === undefined) ||
            (options.visible !== undefined && typeof options.visible !== "boolean") ||
            (options.hasText !== undefined && (typeof options.hasText === "string" ? options.hasText.length > 30_000 : !types.isRegExp(options.hasText))) ||
            (options.hasNotText !== undefined && (typeof options.hasNotText === "string" ? options.hasNotText.length > 30_000 : !types.isRegExp(options.hasNotText))))
            throw new Error("Invalid locator filter");
        const check = (locator, level) => {
            if (level > 8)
                throw new Error("Locator filter nesting exceeds 8 levels");
            if (locator instanceof OpenBrowserUseCssLocator) {
                if (!locator.isRelativeTo(this.tab, this.framePath))
                    throw new Error("Filter locator must belong to the same tab and frame without a semantic scope");
                return;
            }
            if (!(locator instanceof OpenBrowserUseRoleLocator) || locator.tab.browser !== this.tab.browser || locator.tab.id !== this.tab.id || JSON.stringify(locator.framePath ?? null) !== JSON.stringify(this.framePath ?? null))
                throw new Error("Filter locator must belong to the same tab and frame");
            if (locator.cssScope)
                throw new Error("Semantic filter locator cannot use a CSS scope yet");
            if (locator.scope)
                check(locator.scope, level);
            for (const filter of [...locator.filtersBefore, ...locator.filtersAfter]) {
                if (filter.has)
                    check(filter.has, level + 1);
                if (filter.hasNot)
                    check(filter.hasNot, level + 1);
            }
        };
        if (options.has !== undefined)
            check(options.has, 2);
        if (options.hasNot !== undefined)
            check(options.hasNot, 2);
        const filter = { ...(options.visible !== undefined ? { visible: options.visible } : {}), ...(options.hasText !== undefined ? { hasText: copyMatcher(options.hasText) } : {}), ...(options.hasNotText !== undefined ? { hasNotText: copyMatcher(options.hasNotText) } : {}), ...(options.has !== undefined ? { has: options.has } : {}), ...(options.hasNot !== undefined ? { hasNot: options.hasNot } : {}) };
        return new OpenBrowserUseRoleLocator(this.tab, this.roles, this.options, this.position, this.textMatch, this.field, this.scope, this.position === undefined ? [...this.filtersBefore, filter] : this.filtersBefore, this.position === undefined ? this.filtersAfter : [...this.filtersAfter, filter], this.framePath, this.cssScope);
    }
    needsText() {
        return this.filtersBefore.length > 0 || this.filtersAfter.length > 0 || this.roles.some(role => supplementalRoles.includes(role)) || !!this.scope?.needsText();
    }
    async matches(observation, baseIndex) {
        const frameId = this.framePath ? await this.tab.resolveFramePath(this.framePath, undefined, observation.frames) : undefined;
        if (this.framePath && !frameId)
            return [];
        const base = baseIndex === undefined ? undefined : observation.nodes.find(node => node.index === baseIndex);
        if (baseIndex !== undefined && !base)
            throw new RetryablePreflightError("Filter scope changed; observe again");
        const inFrame = (node) => (!this.framePath || node.frameId === frameId) && (!base || node.frameId === base.frameId);
        if (this.field === "placeholder" && observation.nodes.some(node => inFrame(node) && this.roles.includes(node.role) && node.placeholderTruncated))
            throw new Error("Some placeholders were truncated; locator results are incomplete");
        if (this.field === "altText" && observation.nodes.some(node => inFrame(node) && this.roles.includes(node.role) && node.altTextTruncated))
            throw new Error("Some alt text was truncated; locator results are incomplete");
        const normalize = (value) => this.textMatch ? value.replace(/\s+/g, " ").trim() : value;
        const candidates = observation.nodes.filter(node => {
            const value = node[this.field];
            return inFrame(node) && this.roles.includes(node.role) && typeof value === "string" &&
                (this.options.level === undefined || node.level === this.options.level) &&
                (this.options.checked === undefined || node.checked === this.options.checked) &&
                (this.options.disabled === undefined || !!node.disabled === this.options.disabled) &&
                (this.options.pressed === undefined || node.pressed === this.options.pressed) &&
                (this.options.selected === undefined || node.selected === this.options.selected) &&
                (this.options.expanded === undefined || node.expanded === this.options.expanded) &&
                (this.options.name === undefined || (typeof this.options.name !== "string" ? new RegExp(this.options.name.source, this.options.name.flags).test(normalize(value)) : this.options.exact ? normalize(value) === normalize(this.options.name) : normalize(value).toLowerCase().includes(normalize(this.options.name).toLowerCase())));
        });
        const matches = [];
        if (!this.scope && this.cssScope) {
            const snapshot = await this.cssScope.snapshot();
            for (const node of candidates)
                for (const scopeId of snapshot.ids) {
                    if (await this.tab.cssScopeContains(observation, snapshot, scopeId, node.index)) {
                        matches.push({ node, path: [], filters: [], css: { snapshot, scopeId } });
                        break;
                    }
                }
        }
        else if (!this.scope) {
            for (const node of candidates)
                if (!base || await this.tab.scopeContains(observation, base.index, node.index))
                    matches.push({ node, path: [], filters: [] });
        }
        else {
            const scopes = await this.scope.matches(observation, baseIndex);
            for (const node of candidates)
                for (const scope of scopes) {
                    if (await this.tab.scopeContains(observation, scope.node.index, node.index)) {
                        matches.push({ node, path: [...scope.path, scope.node.index], filters: [...scope.filters], ...(scope.css ? { css: scope.css } : {}) });
                        break;
                    }
                }
        }
        const apply = async (items, filters) => {
            if (!filters.length)
                return items;
            const accepted = [];
            for (const item of items) {
                const textFilters = filters.filter(filter => filter.hasText !== undefined || filter.hasNotText !== undefined);
                if (textFilters.length && !matchesTextFilters(await this.tab.scopeText(observation, item.node.index), textFilters))
                    continue;
                const visibilityFilters = filters.filter(filter => filter.visible !== undefined);
                if (visibilityFilters.length) {
                    const visible = await this.tab.scopeVisible(observation, item.node.index);
                    if (visibilityFilters.some(filter => filter.visible !== visible))
                        continue;
                }
                let matched = true;
                const count = (locator) => locator instanceof OpenBrowserUseCssLocator ? locator.countWithin(observation, item.node.index) : locator.matches(observation, item.node.index).then(matches => matches.length);
                for (const filter of filters) {
                    if (filter.has && !(await count(filter.has))) {
                        matched = false;
                        break;
                    }
                    if (filter.hasNot && await count(filter.hasNot)) {
                        matched = false;
                        break;
                    }
                }
                if (matched)
                    accepted.push({ ...item, filters: [...item.filters, { index: item.node.index, filters }] });
            }
            return accepted;
        };
        const before = await apply(matches, this.filtersBefore);
        return apply(this.position === undefined ? before : this.position === -1 ? before.slice(-1) : before.slice(this.position, this.position + 1), this.filtersAfter);
    }
    identities(observation, matches) {
        return matches.map(match => {
            const node = observation.nodes.find(item => item.index === match.node.index);
            if (!node)
                throw new RetryablePreflightError("Locator target changed; observe again");
            return { backendNodeId: node.backendNodeId, frameId: node.frameId ?? "" };
        });
    }
    /** @internal */
    async detachedRoots() {
        const observation = await this.tab.freshFilterObservation();
        const matches = await this.matches(observation);
        if (!observation.frames)
            throw new Error("Frame information is unavailable");
        return { documentId: observation.documentId, frames: observation.frames, roots: this.identities(observation, matches) };
    }
    guard(snapshotId, matches) {
        return { locator: this, expected: this.identities(this.tab.currentObservation(snapshotId), matches) };
    }
    /** @internal */
    async verifyMatches(original, expected) {
        const fresh = await this.tab.freshFilterObservation();
        if (fresh.documentId !== original.documentId || JSON.stringify(fresh.frames) !== JSON.stringify(original.frames))
            throw new RetryablePreflightError("Page changed; observe again");
        const actual = this.identities(fresh, await this.matches(fresh));
        if (JSON.stringify(actual) !== JSON.stringify(expected))
            throw new RetryablePreflightError("Locator matches changed; observe again");
    }
    async find() {
        const state = await this.tab.observe({ includeFrames: true, ...(this.needsText() ? { includeText: true } : {}) });
        if (state.unavailableFrames?.length)
            throw new Error("Some frames could not be observed; locator results are incomplete");
        const observation = this.tab.currentObservation(state.snapshotId);
        const matches = await this.matches(observation);
        this.tab.currentObservation(state.snapshotId);
        return { state, matches };
    }
    async count() { return (await this.find()).matches.length; }
    async all() { return Array.from({ length: await this.count() }, (_, index) => this.nth(index)); }
    async allTextContents(options = {}) {
        const timeoutMs = options.timeoutMs ?? 5_000;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            try {
                const { state, matches } = await this.find();
                const values = [];
                let total = 0;
                for (const match of matches) {
                    this.tab.bindLocatorScope(state.snapshotId, match.node.index, match.path, match.filters, this.framePath ? [...this.framePath] : undefined, match.css, this.guard(state.snapshotId, matches));
                    const value = await this.tab.locatorRead(state.snapshotId, match.node.index, "textContent");
                    if (typeof value !== "string")
                        throw new RetryablePreflightError("Target text is unavailable; observe again");
                    total += value.length;
                    if (total > 1_000_000)
                        throw new Error("Locator values exceed the 1000000 character limit");
                    values.push(value);
                }
                return values;
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError) || performance.now() >= deadline)
                    throw error;
                await new Promise(resolve => setTimeout(resolve, Math.min(100, deadline - performance.now())));
            }
        }
    }
    async innerText(options = {}) { return this.perform(async (node, id) => (await this.tab.locatorRead(id, node.index, "innerText")), options.timeoutMs); }
    async textContent(options = {}) { return this.perform(async (node, id) => (await this.tab.locatorRead(id, node.index, "textContent")), options.timeoutMs); }
    async isEnabled() { return this.perform(async (node, id) => (await this.tab.locatorRead(id, node.index, "enabled"))); }
    async isChecked() { return this.perform(async (node, id) => (await this.tab.locatorRead(id, node.index, "checked"))); }
    async isVisible() {
        const { state, matches } = await this.find();
        if (!matches.length)
            return false;
        if (matches.length > 1)
            throw new Error(`Locator matched ${matches.length} elements; expected exactly one`);
        const match = matches[0];
        this.tab.bindLocatorScope(state.snapshotId, match.node.index, match.path, match.filters, this.framePath ? [...this.framePath] : undefined, match.css, this.guard(state.snapshotId, matches));
        return await this.tab.locatorRead(state.snapshotId, match.node.index, "visible");
    }
    async waitFor(options) {
        if (!options || !["visible", "hidden"].includes(options.state))
            throw new Error("Locator wait supports visible and hidden states");
        const timeoutMs = options.timeoutMs ?? 5_000;
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        while (true) {
            try {
                if (await this.isVisible() === (options.state === "visible"))
                    return;
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError))
                    throw error;
            }
            const remaining = deadline - performance.now();
            if (remaining <= 0)
                throw new Error(`Timed out waiting for locator to become ${options.state}`);
            await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
        }
    }
    async getAttribute(name, options = {}) {
        if (typeof name !== "string" || !name || name.length > 256)
            throw new Error("Invalid attribute name");
        return this.perform(async (node, id) => (await this.tab.locatorRead(id, node.index, "attribute", name)), options.timeoutMs);
    }
    async perform(action, timeoutMs = 5_000) {
        if (!Number.isFinite(timeoutMs) || timeoutMs < 0 || timeoutMs > 120_000)
            throw new Error("Invalid locator timeout");
        const deadline = performance.now() + timeoutMs;
        let lastError = new Error(`Locator matched 0 elements before timeout (${timeoutMs} ms)`);
        while (true) {
            try {
                const { state, matches } = await this.find();
                if (matches.length > 1)
                    throw new Error(`Locator matched ${matches.length} elements; expected exactly one`);
                if (matches.length === 1) {
                    this.tab.bindLocatorScope(state.snapshotId, matches[0].node.index, matches[0].path, matches[0].filters, this.framePath ? [...this.framePath] : undefined, matches[0].css, this.guard(state.snapshotId, matches));
                    return await action(matches[0].node, state.snapshotId);
                }
                lastError = new Error(`Locator matched 0 elements before timeout (${timeoutMs} ms)`);
            }
            catch (error) {
                if (!(error instanceof RetryablePreflightError))
                    throw error;
                lastError = error;
            }
            const remaining = deadline - performance.now();
            if (remaining <= 0)
                throw lastError;
            await new Promise(resolve => setTimeout(resolve, Math.min(100, remaining)));
        }
    }
    async downloadMedia(options = {}) {
        const locator = this.first();
        await locator.perform(async (node, id) => {
            const observation = this.tab.currentObservation(id), target = observation.nodes.find(item => item.index === node.index);
            const frame = observation.frames?.find(item => item.id === (target?.frameId ?? observation.frames?.[0]?.id));
            if (!target || !frame)
                throw new RetryablePreflightError("Download target is unavailable; observe again");
            await this.tab.triggerMediaDownload(target.backendNodeId, frame, () => this.tab.locatorRead(id, node.index, "attribute", "src"));
        }, options.timeoutMs);
    }
    async click(options = {}) { const mouse = locatorClickOptions(options); await this.perform((node, id) => this.tab.click(node.index, id, mouse), options.timeoutMs); }
    async dblclick(options = {}) { const mouse = locatorClickOptions(options); await this.perform((node, id) => this.tab.dblclick(node.index, id, mouse), options.timeoutMs); }
    async hover(options = {}) { await this.perform((node, id) => this.tab.hover(node.index, id), options.timeoutMs); }
    async press(key, options = {}) { await this.perform((node, id) => this.tab.press(node.index, id, key), options.timeoutMs); }
    async fill(text, options = {}) { await this.perform((node, id) => this.tab.fill(node.index, id, text), options.timeoutMs); }
    async type(text, options = {}) { await this.perform((node, id) => this.tab.typeText(node.index, id, text), options.timeoutMs); }
    async check(options = {}) { await this.perform((node, id) => this.tab.setChecked(node.index, id, true), options.timeoutMs); }
    async uncheck(options = {}) { await this.perform((node, id) => this.tab.setChecked(node.index, id, false), options.timeoutMs); }
    async setChecked(checked, options = {}) {
        if (typeof checked !== "boolean")
            throw new Error("Checked state must be a boolean");
        await this.perform((node, id) => this.tab.setChecked(node.index, id, checked), options.timeoutMs);
    }
    async selectOption(values, options = {}) { return this.perform((node, id) => this.tab.selectOption(node.index, id, values), options.timeoutMs); }
}
export class OpenBrowserUseCdp {
    client;
    #frames = new Map();
    #pending = new Map();
    #failure = new Map();
    #generations = new Map();
    #dialogs = new Map();
    #dialogEnabled = new Map();
    #logs = new Map();
    #eventPreparations = new Map();
    constructor(client) {
        this.client = client;
        client.onDisconnect(() => this.#logs.clear());
        client.onNotification(notification => {
            if (["onDebuggerDetach", "onTabClosed"].includes(notification.method) && isObject(notification.params) && typeof notification.params.tabId === "number") {
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
            if (notification.method !== "onCDPEvent" || !isObject(notification.params))
                return;
            const { source, method, params } = notification.params;
            if (!isObject(source) || typeof source.tabId !== "number" || !isObject(params))
                return;
            const capture = this.#logs.get(source.tabId);
            if (capture && capture.generation === this.client.connectionGeneration && (method === "Runtime.consoleAPICalled" || method === "Runtime.exceptionThrown" || method === "Log.entryAdded")) {
                const entry = browserLogEntry(method, params);
                if (entry) {
                    capture.entries.push(entry);
                    if (capture.entries.length > 500)
                        capture.entries.shift();
                }
            }
            if (method === "Page.javascriptDialogOpening" && typeof params.type === "string" && ["alert", "confirm", "prompt", "beforeunload"].includes(params.type) && typeof params.message === "string" && typeof params.url === "string") {
                const info = { id: randomUUID(), type: params.type, message: params.message, url: params.url, ...(typeof params.defaultPrompt === "string" ? { defaultPrompt: params.defaultPrompt } : {}) };
                this.#dialogs.set(source.tabId, { info, generation: this.client.connectionGeneration, ...(typeof source.sessionId === "string" ? { sessionId: source.sessionId } : {}), issued: false });
            }
            else if (method === "Page.javascriptDialogClosed") {
                const dialog = this.#dialogs.get(source.tabId);
                if (dialog && (dialog.sessionId === source.sessionId || typeof source.sessionId !== "string"))
                    this.#dialogs.delete(source.tabId);
            }
            const frames = this.#frames.get(source.tabId);
            if (!frames)
                return;
            if (method === "Target.detachedFromTarget" && typeof params.sessionId === "string") {
                const remove = (id) => {
                    frames.delete(id);
                    capture?.sessions.delete(id);
                    for (const child of frames.values())
                        if (child.parentSessionId === id)
                            remove(child.sessionId);
                };
                remove(params.sessionId);
            }
            if (method !== "Target.attachedToTarget" || typeof params.sessionId !== "string" || !isObject(params.targetInfo))
                return;
            const info = params.targetInfo;
            if (info.type !== "iframe" || typeof info.targetId !== "string" || typeof info.parentFrameId !== "string")
                return;
            if (typeof source.sessionId === "string" && !frames.has(source.sessionId))
                return;
            const sessionId = params.sessionId;
            const tabId = source.tabId;
            const pending = this.#pending.get(tabId) ?? new Set();
            this.#pending.set(tabId, pending);
            frames.set(sessionId, { sessionId, frameId: info.targetId, parentFrameId: info.parentFrameId, ...(typeof source.sessionId === "string" ? { parentSessionId: source.sessionId } : {}) });
            const task = this.call(tabId, "Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true, filter: [{ type: "iframe", exclude: false }, { exclude: true }] }, { sessionId })
                .then(async () => { if (capture && this.#logs.get(tabId) === capture)
                await this.enableLogSession(tabId, capture, sessionId); })
                .then(() => { }, error => { if (frames.has(sessionId))
                this.#failure.set(tabId, error instanceof Error ? error : new Error(String(error))); })
                .finally(() => pending.delete(task));
            pending.add(task);
        });
    }
    enableLogSession(tabId, capture, sessionId) {
        const key = sessionId ?? "";
        const existing = capture.sessions.get(key);
        if (existing)
            return existing;
        const pending = this.call(tabId, "Runtime.enable", {}, { sessionId, expectedGeneration: capture.generation })
            .then(() => this.call(tabId, "Log.enable", {}, { sessionId, expectedGeneration: capture.generation })).then(() => { });
        capture.sessions.set(key, pending);
        void pending.catch(() => { if (capture.sessions.get(key) === pending)
            capture.sessions.delete(key); });
        return pending;
    }
    /** @internal */
    async watchLogs(tabId) {
        await this.ensureAttached(tabId);
        let capture = this.#logs.get(tabId);
        if (capture?.generation !== this.client.connectionGeneration) {
            capture = { generation: this.client.connectionGeneration, entries: [], sessions: new Map() };
            this.#logs.set(tabId, capture);
        }
        if (!capture.ready) {
            const current = capture;
            const ready = (async () => {
                await this.enableFrameSessions(tabId);
                await this.enableLogSession(tabId, current);
                for (const frame of await this.frameSessions(tabId))
                    await this.enableLogSession(tabId, current, frame.sessionId);
            })();
            current.ready = ready;
            void ready.catch(() => { if (current.ready === ready)
                current.ready = undefined; });
        }
        await capture.ready;
        for (const frame of await this.frameSessions(tabId))
            await this.enableLogSession(tabId, capture, frame.sessionId);
    }
    /** @internal */
    logs(tabId) {
        const capture = this.#logs.get(tabId);
        return capture?.generation === this.client.connectionGeneration ? capture.entries.map(entry => ({ ...entry })) : [];
    }
    /** @internal */
    async enableDialogs(tabId) {
        if (this.#dialogEnabled.get(tabId) === this.client.connectionGeneration)
            return;
        await this.call(tabId, "Page.enable");
        this.#dialogEnabled.set(tabId, this.client.connectionGeneration);
    }
    /** @internal */
    currentDialog(tabId) {
        const dialog = this.#dialogs.get(tabId);
        if (!dialog || dialog.generation !== this.client.connectionGeneration) {
            this.#dialogs.delete(tabId);
            return null;
        }
        return { ...dialog.info };
    }
    /** @internal */
    async resolveDialog(tabId, id, accept, promptText) {
        if (promptText !== undefined && typeof promptText !== "string")
            throw new Error("Prompt text must be a string");
        const dialog = this.#dialogs.get(tabId);
        if (!dialog || dialog.info.id !== id || dialog.generation !== this.client.connectionGeneration)
            throw new Error("Dialog is no longer open");
        if (dialog.issued)
            throw new Error("Dialog decision has already been issued; observe again");
        if (promptText !== undefined && (!accept || dialog.info.type !== "prompt"))
            throw new Error("Prompt text requires an accepted prompt dialog");
        dialog.issued = true;
        await this.call(tabId, "Page.handleJavaScriptDialog", { accept, ...(promptText !== undefined ? { promptText } : {}) }, { sessionId: dialog.sessionId, expectedGeneration: dialog.generation });
        if (this.#dialogs.get(tabId)?.info.id === id)
            this.#dialogs.delete(tabId);
    }
    async enableFrameSessions(tabId) {
        await this.ensureAttached(tabId);
        if (this.#generations.get(tabId) !== this.client.connectionGeneration) {
            this.#frames.get(tabId)?.clear();
            this.#frames.delete(tabId);
            this.#failure.delete(tabId);
            this.#generations.set(tabId, this.client.connectionGeneration);
        }
        const first = !this.#frames.has(tabId);
        if (first)
            this.#frames.set(tabId, new Map());
        try {
            if (first)
                await this.call(tabId, "Target.setAutoAttach", { autoAttach: false, waitForDebuggerOnStart: false, flatten: true });
            await this.call(tabId, "Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true, filter: [{ type: "iframe", exclude: false }, { exclude: true }] });
            await this.frameSessions(tabId);
            return true;
        }
        catch (error) {
            if (error instanceof Error && error.message.includes("IAB CDP command is outside page permissions")) {
                this.#frames.delete(tabId);
                return false;
            }
            throw error;
        }
    }
    async frameSessions(tabId) {
        const pending = this.#pending.get(tabId);
        while (pending?.size)
            await Promise.all([...pending]);
        const failure = this.#failure.get(tabId);
        if (failure) {
            this.#failure.delete(tabId);
            throw failure;
        }
        return [...(this.#frames.get(tabId)?.values() ?? [])];
    }
    /** @internal */
    blockUntilPrepared(tabId, preparation) {
        const barrier = preparation.then(() => { });
        let pending = this.#eventPreparations.get(tabId);
        if (!pending) {
            pending = new Set();
            this.#eventPreparations.set(tabId, pending);
        }
        pending.add(barrier);
        const cleanup = () => { pending.delete(barrier); if (!pending.size && this.#eventPreparations.get(tabId) === pending)
            this.#eventPreparations.delete(tabId); };
        void barrier.then(cleanup, cleanup);
    }
    async call(tabId, method, commandParams = {}, options = {}) {
        const preparations = this.#eventPreparations.get(tabId);
        // Frame attachment and log setup must finish before a chooser can be registered.
        if (preparations?.size && !["Target.setAutoAttach", "Runtime.enable", "Log.enable"].includes(method))
            await Promise.all([...preparations]);
        await this.ensureAttached(tabId);
        if (options.expectedGeneration !== undefined && options.expectedGeneration !== this.client.connectionGeneration)
            throw new Error("Connection changed; observe again");
        const result = await this.client.request("executeCdp", {
            target: { tabId, ...(options.sessionId ? { sessionId: options.sessionId } : {}) },
            method,
            commandParams,
            ...(options.visualPoint ? { visualPoint: options.visualPoint } : {}),
            ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs })
        }, options.expectedGeneration);
        if (method === "Page.disable" && !options.sessionId)
            this.#dialogEnabled.delete(tabId);
        if (method === "Runtime.disable" || method === "Log.disable") {
            const capture = this.#logs.get(tabId);
            capture?.sessions.delete(options.sessionId ?? "");
            if (capture)
                capture.ready = undefined;
        }
        return result;
    }
    async evaluate(tabId, expression, options = {}) {
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
    async navigate(tabId, url, options = {}) {
        if (!url) {
            throw new Error("goto requires a URL");
        }
        const waitUntil = options.waitUntil ?? "load";
        assertSupportedLoadState(waitUntil);
        const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
        await this.call(tabId, "Page.enable");
        const controller = new AbortController();
        const wait = this.waitForLoadEvent(tabId, waitUntil, timeoutMs, controller.signal);
        let waitError;
        void wait.catch(error => { waitError = error; });
        try {
            const result = await this.call(tabId, "Page.navigate", { url }, { timeoutMs });
            if (isObject(result) && typeof result.errorText === "string" && result.errorText) {
                throw new Error(`Browser failed to navigate tab ${tabId}: ${result.errorText}`);
            }
            if (isObject(result) && typeof result.loaderId !== "string") {
                const state = await this.readDocumentState(tabId);
                if (state?.href && documentStateMatches(state, waitUntil)) {
                    let target;
                    try {
                        target = new URL(url, state.href).href;
                    }
                    catch { /* Page.navigate validates the URL. */ }
                    if (target === state.href) {
                        if (waitError !== undefined)
                            throw waitError;
                        return result;
                    }
                }
            }
            await wait;
            return result;
        }
        finally {
            controller.abort();
        }
    }
    async waitForLoadState(tabId, options = {}) {
        const state = options.state ?? "load";
        assertSupportedLoadState(state);
        await this.call(tabId, "Page.enable");
        const controller = new AbortController();
        const wait = this.waitForLoadEvent(tabId, state, options.timeoutMs ?? defaultNavigationTimeoutMs, controller.signal);
        try {
            const ready = await Promise.race([
                wait.then(() => true),
                this.readDocumentState(tabId).then(documentState => documentStateMatches(documentState, state))
            ]);
            if (!ready)
                await wait;
        }
        finally {
            controller.abort();
        }
    }
    async readDocumentState(tabId) {
        try {
            const value = await this.evaluate(tabId, "({ href: window.location.href, readyState: document.readyState })");
            return isObject(value) ? { href: stringValue(value.href), readyState: stringValue(value.readyState) } : undefined;
        }
        catch {
            return undefined;
        }
    }
    waitForEvent(tabId, predicate, options = {}) {
        if (options.signal?.aborted)
            return Promise.reject(new Error("Event wait cancelled"));
        const timeoutMs = options.timeoutMs ?? defaultNavigationTimeoutMs;
        return new Promise((resolve, reject) => {
            let settled = false;
            let removeHandler = null;
            let removeDisconnect = null;
            let timer;
            const finish = () => {
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
            const onAbort = () => { if (finish())
                reject(new Error("Event wait cancelled")); };
            timer = setTimeout(() => {
                if (finish()) {
                    reject(new Error(options.timeoutMessage ?? `Timed out waiting for tab ${tabId} event`));
                }
            }, timeoutMs);
            options.signal?.addEventListener("abort", onAbort, { once: true });
            removeDisconnect = this.client.onDisconnect(error => { if (finish())
                reject(error); });
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
                }
                catch (error) {
                    if (finish()) {
                        reject(error instanceof Error ? error : new Error(String(error)));
                    }
                }
            });
        });
    }
    waitForLoadEvent(tabId, state, timeoutMs, signal) {
        return this.waitForEvent(tabId, (notification) => {
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
        }, {
            timeoutMs,
            signal,
            timeoutMessage: `Timed out waiting for ${state} in tab ${tabId}`
        }).then(() => undefined);
    }
    async ensureAttached(tabId) {
        await this.client.attach(tabId);
    }
}
export function encodeFrame(value) {
    const payload = Buffer.from(JSON.stringify(value), "utf8");
    const frame = Buffer.alloc(headerBytes + payload.length);
    if (endianness() === "LE") {
        frame.writeUInt32LE(payload.length, 0);
    }
    else {
        frame.writeUInt32BE(payload.length, 0);
    }
    payload.copy(frame, headerBytes);
    return frame;
}
function isObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function frameAncestry(frame, frames) {
    const chain = [];
    let current = frame;
    while (current?.parentId) {
        chain.push(current);
        current = frames.find(item => item.id === current?.parentId);
        if (!current || chain.length > frames.length)
            throw new Error("Invalid frame ancestry");
    }
    return chain;
}
function interactiveNodes(tree, offset = 0, includeText = false) {
    if (!isObject(tree) || !Array.isArray(tree.nodes))
        throw new Error("Invalid accessibility tree");
    const roles = new Set(["button", "link", "checkbox", "radio", "switch", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "combobox", "listbox", "textbox", "searchbox", "slider", "spinbutton", "Date", "DateTime", "InputTime", ...(includeText ? supplementalRoles : [])]);
    const nodes = [];
    const byId = new Map(tree.nodes.filter(isObject).filter(node => typeof node.nodeId === "string").map(node => [node.nodeId, node]));
    const temporalAncestor = (node) => {
        const seen = new Set();
        let parent = node.parentId;
        while (typeof parent === "string" && !seen.has(parent)) {
            seen.add(parent);
            const ancestor = byId.get(parent);
            if (!ancestor)
                break;
            if (isObject(ancestor.role) && ["Date", "DateTime", "InputTime"].includes(String(ancestor.role.value)))
                return true;
            parent = ancestor.parentId;
        }
        return false;
    };
    for (const node of tree.nodes) {
        if (!isObject(node) || node.ignored === true || typeof node.backendDOMNodeId !== "number" || !isObject(node.role))
            continue;
        const role = node.role.value;
        if (typeof role !== "string" || !roles.has(role) || temporalAncestor(node))
            continue;
        const name = isObject(node.name) && typeof node.name.value === "string" ? node.name.value : "";
        const state = (name) => {
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
        const placeholder = typeof rawPlaceholder === "string" ? rawPlaceholder.slice(0, 512) : undefined;
        const placeholderTruncated = typeof rawPlaceholder === "string" && rawPlaceholder.length > 512;
        const altSource = sources.find(source => isObject(source) && source.attribute === "alt" && isObject(source.attributeValue) && typeof source.attributeValue.value === "string");
        const rawAlt = isObject(altSource) && isObject(altSource.attributeValue) ? altSource.attributeValue.value : undefined;
        const altText = typeof rawAlt === "string" ? rawAlt.slice(0, 512) : undefined;
        const altTextTruncated = typeof rawAlt === "string" && rawAlt.length > 512;
        const states = axProperties(node);
        if (placeholder !== undefined)
            states.push(`placeholder=${JSON.stringify(placeholder)}${placeholderTruncated ? createHash("sha256").update(rawPlaceholder).digest("hex") : ""}`);
        if (altText !== undefined)
            states.push(`alt=${JSON.stringify(altText)}${altTextTruncated ? createHash("sha256").update(rawAlt).digest("hex") : ""}`);
        nodes.push({ index: offset + nodes.length + 1, role, name, backendNodeId: node.backendDOMNodeId, stateKey: JSON.stringify(states), ...(level !== undefined ? { level } : {}), ...(checked !== undefined ? { checked } : {}), ...(disabled ? { disabled: true } : {}), ...(pressed !== undefined ? { pressed } : {}), ...(selected !== undefined ? { selected } : {}), ...(expanded !== undefined ? { expanded } : {}), ...(placeholder !== undefined ? { placeholder } : {}), ...(placeholderTruncated ? { placeholderTruncated: true } : {}), ...(altText !== undefined ? { altText } : {}), ...(altTextTruncated ? { altTextTruncated: true } : {}) });
    }
    return nodes;
}
function axProperties(node) {
    return Array.isArray(node.properties) ? node.properties.flatMap(property => {
        if (!isObject(property) || typeof property.name !== "string" || !["checked", "selected", "expanded", "disabled", "pressed", "required", "readonly", "level"].includes(property.name) || !isObject(property.value))
            return [];
        const value = property.value.value;
        return typeof value === "boolean" || typeof value === "string" || (property.name === "level" && typeof value === "number" && Number.isSafeInteger(value) && value > 0) ? [`${property.name}=${JSON.stringify(value)}`] : [];
    }).sort() : [];
}
function appendUnplacedFrames(base, frames) {
    const extra = frames.map(frame => `[frame placement unavailable]\nframe ${JSON.stringify(frame.url)}${frame.text ? `\n${frame.text}` : ""}`).join("\n");
    const text = [base.text, extra].filter(Boolean).join("\n");
    return { text: text.slice(0, 30_000), truncated: base.truncated || frames.some(frame => frame.truncated) || text.length > 30_000 };
}
function renderAXState(tree, targets, embedded = new Map()) {
    if (!isObject(tree) || !Array.isArray(tree.nodes))
        throw new Error("Invalid accessibility tree");
    const indexed = new Map(targets.map(node => [node.backendNodeId, node]));
    const nodes = tree.nodes.filter(isObject);
    const byId = new Map(nodes.flatMap((node, index) => typeof node.nodeId === "string" ? [[node.nodeId, index]] : []));
    const children = new Map();
    const roots = [];
    for (let i = 0; i < nodes.length; i++) {
        const parent = typeof nodes[i].parentId === "string" ? byId.get(nodes[i].parentId) : undefined;
        if (parent === undefined || parent === i)
            roots.push(i);
        else {
            const list = children.get(parent) ?? [];
            list.push(i);
            children.set(parent, list);
        }
    }
    const lines = [];
    const visited = new Set();
    const remaining = new Map(embedded);
    let length = 0, truncated = false;
    const append = (line) => {
        if (length + line.length + 1 > 30_000) {
            const available = 30_000 - length - 1;
            if (available > 1)
                lines.push(`${line.slice(0, available - 1)}…`);
            return false;
        }
        lines.push(line);
        length += line.length + 1;
        return true;
    };
    const pending = roots.reverse().map(index => ({ index, depth: 0 }));
    let next = 0;
    while (pending.length || next < nodes.length) {
        if (!pending.length) {
            while (next < nodes.length && visited.has(next))
                next++;
            if (next < nodes.length)
                pending.push({ index: next, depth: 0 });
        }
        const current = pending.pop();
        if (!current || visited.has(current.index))
            continue;
        visited.add(current.index);
        const node = nodes[current.index];
        const target = typeof node.backendDOMNodeId === "number" ? indexed.get(node.backendDOMNodeId) : undefined;
        const show = node.ignored !== true && isObject(node.role) && typeof node.role.value === "string" && ((isObject(node.name) && typeof node.name.value === "string" && !!node.name.value) || target !== undefined);
        const descendants = children.get(current.index) ?? [];
        for (let i = descendants.length - 1; i >= 0; i--)
            pending.push({ index: descendants[i], depth: current.depth + (show ? 1 : 0) });
        if (show && isObject(node.role)) {
            const role = node.role.value;
            const name = isObject(node.name) && typeof node.name.value === "string" ? node.name.value : "";
            const index = target?.index;
            const properties = axProperties(node);
            if (target?.altText !== undefined)
                properties.push(`alt=${JSON.stringify(target.altText)}${target.altTextTruncated ? "…" : ""}`);
            if (target?.placeholder !== undefined)
                properties.push(`placeholder=${JSON.stringify(target.placeholder)}${target.placeholderTruncated ? "…" : ""}`);
            if (target?.valueRedacted)
                properties.push("value=[redacted]");
            else if (target?.valueUnavailable)
                properties.push("value=[unavailable]");
            else if (target?.value !== undefined)
                properties.push(`value=${JSON.stringify(target.value)}${target.valueTruncated ? "…" : ""}`);
            else if (target?.valueTruncated)
                properties.push("value=[truncated]");
            const line = `${"  ".repeat(Math.min(current.depth, 80))}${index === undefined ? "" : `[${index}] `}${role}${name ? ` ${JSON.stringify(name)}` : ""}${properties.length ? ` ${properties.join(" ")}` : ""}`;
            if (!append(line))
                return { text: lines.join("\n"), truncated: true };
        }
        const owner = typeof node.backendDOMNodeId === "number" ? node.backendDOMNodeId : undefined;
        const frames = owner === undefined ? undefined : remaining.get(owner);
        if (owner !== undefined && frames)
            remaining.delete(owner);
        for (const frame of frames ?? []) {
            const indent = "  ".repeat(Math.min(current.depth + (show ? 1 : 0), 80));
            if (!append(`${indent}frame ${JSON.stringify(frame.url)}`))
                return { text: lines.join("\n"), truncated: true };
            for (const line of frame.text ? frame.text.split("\n") : [])
                if (!append(`${indent}  ${line}`))
                    return { text: lines.join("\n"), truncated: true };
            truncated ||= frame.truncated;
        }
    }
    const rendered = { text: lines.join("\n"), truncated };
    return remaining.size ? appendUnplacedFrames(rendered, [...remaining.values()].flat()) : rendered;
}
function diffAXState(before, after) {
    const oldLines = before ? before.split("\n") : [];
    const newLines = after ? after.split("\n") : [];
    let start = 0;
    while (start < oldLines.length && start < newLines.length && oldLines[start] === newLines[start])
        start++;
    let oldEnd = oldLines.length, newEnd = newLines.length;
    while (oldEnd > start && newEnd > start && oldLines[oldEnd - 1] === newLines[newEnd - 1]) {
        oldEnd--;
        newEnd--;
    }
    const text = [...oldLines.slice(start, oldEnd).map(line => `- ${line}`), ...newLines.slice(start, newEnd).map(line => `+ ${line}`)].join("\n");
    return text.length > 30_000 ? { text: `${text.slice(0, 29_999)}…`, truncated: true } : { text, truncated: false };
}
function tabIdFromValue(value, label) {
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
function assertSupportedLoadState(state) {
    if (state !== "domcontentloaded" && state !== "load") {
        throw new Error(`Unsupported load state "${state}". Use "domcontentloaded" or "load".`);
    }
}
function documentStateMatches(documentState, state) {
    if (documentState?.readyState === "complete") {
        return true;
    }
    return state === "domcontentloaded" && documentState?.readyState === "interactive";
}
function cdpEventForTab(notification, tabId) {
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
function stringValue(value) {
    return typeof value === "string" ? value : undefined;
}
