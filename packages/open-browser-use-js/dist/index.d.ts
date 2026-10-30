export type JsonValue = null | boolean | number | string | JsonValue[] | {
    [key: string]: JsonValue;
};
export type BrowserUseRequestParams = {
    [key: string]: JsonValue;
};
export type OpenBrowserUseClientOptions = {
    socketPath: string;
    sessionId?: string;
    turnId?: string;
    timeoutMs?: number;
};
export type OpenBrowserUseNotification = {
    method: string;
    params?: JsonValue;
};
export type NotificationHandler = (notification: OpenBrowserUseNotification) => void;
export type OpenBrowserUseLoadState = "domcontentloaded" | "load";
export type OpenBrowserUseGotoOptions = {
    waitUntil?: OpenBrowserUseLoadState;
    timeoutMs?: number;
};
export type OpenBrowserUseWaitForLoadStateOptions = {
    state?: OpenBrowserUseLoadState;
    timeoutMs?: number;
};
export type OpenBrowserUseBrowserOptions = OpenBrowserUseClientOptions | {
    client: OpenBrowserUseClient;
};
export type InteractiveNode = {
    index: number;
    role: string;
    name: string;
    frameId?: string;
    checked?: boolean | "mixed";
    placeholder?: string;
    placeholderTruncated?: boolean;
    altText?: string;
    altTextTruncated?: boolean;
    value?: string | number;
    valueRedacted?: boolean;
    valueUnavailable?: boolean;
    valueTruncated?: boolean;
};
export type SelectOption = string | {
    value?: string;
    label?: string;
};
export type InteractiveState = {
    snapshotId: string;
    nodes: InteractiveNode[];
    text: string;
    textMode: "full" | "diff";
    truncated: boolean;
    frameCoverage?: "same-process" | "cross-process";
    unavailableFrames?: string[];
    valuesTruncated?: boolean;
};
export declare class OpenBrowserUseClient {
    #private;
    readonly socketPath: string;
    readonly sessionId: string;
    readonly turnId: string;
    readonly timeoutMs: number;
    get connectionGeneration(): number;
    constructor(options: OpenBrowserUseClientOptions);
    connect(): Promise<this>;
    close(): void;
    onNotification(handler: NotificationHandler): () => void;
    request(method: string, params?: BrowserUseRequestParams): Promise<JsonValue>;
    getInfo(): Promise<JsonValue>;
    createTab(): Promise<JsonValue>;
    getTabs(): Promise<JsonValue>;
    getUserTabs(): Promise<JsonValue>;
    getUserHistory(params?: BrowserUseRequestParams): Promise<JsonValue>;
    claimUserTab(tabId: number): Promise<JsonValue>;
    finalizeTabs(keep: JsonValue[]): Promise<JsonValue>;
    nameSession(name: string): Promise<JsonValue>;
    attach(tabId: number): Promise<JsonValue>;
    detach(tabId: number): Promise<JsonValue>;
    executeCdp(tabId: number, method: string, commandParams?: BrowserUseRequestParams): Promise<JsonValue>;
    moveMouse(tabId: number, x: number, y: number, waitForArrival?: boolean): Promise<JsonValue>;
    waitForFileChooser(tabId: number, timeoutMs?: number): Promise<JsonValue>;
    setFileChooserFiles(fileChooserId: string, files: string[]): Promise<JsonValue>;
    waitForDownload(tabId: number, timeoutMs?: number): Promise<JsonValue>;
    downloadPath(downloadId: string, timeoutMs?: number): Promise<JsonValue>;
    browserUserHistory(params?: BrowserUseRequestParams): Promise<JsonValue>;
    readClipboardText(tabId: number): Promise<JsonValue>;
    writeClipboardText(tabId: number, text: string): Promise<JsonValue>;
    readClipboard(tabId: number): Promise<JsonValue>;
    writeClipboard(tabId: number, items: JsonValue[]): Promise<JsonValue>;
    turnEnded(): Promise<JsonValue>;
}
export declare function connectOpenBrowserUse(options: OpenBrowserUseBrowserOptions): Promise<OpenBrowserUseBrowser>;
export declare class OpenBrowserUseBrowser {
    readonly client: OpenBrowserUseClient;
    readonly cdp: OpenBrowserUseCdp;
    constructor(options: OpenBrowserUseBrowserOptions);
    connect(): Promise<this>;
    close(): void;
    newTab(options?: OpenBrowserUseGotoOptions & {
        url?: string;
    }): Promise<OpenBrowserUseTab>;
    tab(tabId: number): OpenBrowserUseTab;
    getTabs(): Promise<JsonValue>;
    getUserTabs(): Promise<JsonValue>;
    claimTab(tabId: number): Promise<OpenBrowserUseTab>;
}
export declare class OpenBrowserUseTab {
    #private;
    readonly browser: OpenBrowserUseBrowser;
    readonly id: number;
    readonly playwright: OpenBrowserUseTabPlaywright;
    constructor(browser: OpenBrowserUseBrowser, id: number);
    goto(url: string, options?: OpenBrowserUseGotoOptions): Promise<JsonValue>;
    waitForLoadState(options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    domSnapshot(): Promise<string>;
    getAXState(): Promise<JsonValue>;
    observe(options?: {
        diff?: boolean;
        includeFrames?: boolean;
        includeValues?: boolean;
        includeText?: boolean;
    }): Promise<InteractiveState>;
    private readAXValues;
    click(index: number, snapshotId: string): Promise<void>;
    hover(index: number, snapshotId: string): Promise<void>;
    hoverAt(x: number, y: number): Promise<void>;
    clickAt(x: number, y: number): Promise<void>;
    drag(from: [number, number], to: [number, number]): Promise<void>;
    scrollAt(x: number, y: number, deltaX: number, deltaY: number): Promise<void>;
    pressKey(key: string): Promise<void>;
    private checkPoint;
    getViewport(): Promise<{
        width: number;
        height: number;
    }>;
    typeText(index: number, snapshotId: string, text: string): Promise<void>;
    fill(index: number, snapshotId: string, text: string): Promise<void>;
    setChecked(index: number, snapshotId: string, checked: boolean): Promise<void>;
    selectOption(index: number, snapshotId: string, values: SelectOption | SelectOption[]): Promise<string[]>;
    private act;
    private documentId;
    private frameTree;
    private validateFrames;
    private framePoint;
    getScreenshot(): Promise<Buffer>;
    evaluate(expression: string, options?: {
        awaitPromise?: boolean;
    }): Promise<JsonValue>;
    close(): Promise<JsonValue>;
}
export declare class OpenBrowserUseTabPlaywright {
    readonly tab: OpenBrowserUseTab;
    constructor(tab: OpenBrowserUseTab);
    waitForLoadState(options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    domSnapshot(): Promise<string>;
    getByRole(role: string, options?: {
        name?: string;
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByLabel(name: string, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByText(text: string, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByAltText(altText: string, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByPlaceholder(placeholder: string, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
}
export declare class OpenBrowserUseRoleLocator {
    private tab;
    private roles;
    private options;
    private position?;
    private textMatch;
    private field;
    constructor(tab: OpenBrowserUseTab, roles: readonly string[], options: {
        name?: string;
        exact?: boolean;
    }, position?: number | undefined, textMatch?: boolean, field?: "name" | "placeholder" | "altText");
    nth(index: number): OpenBrowserUseRoleLocator;
    first(): OpenBrowserUseRoleLocator;
    private find;
    count(): Promise<number>;
    private perform;
    click(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    hover(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    fill(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    type(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    check(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    uncheck(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    selectOption(values: SelectOption | SelectOption[], options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
}
export declare class OpenBrowserUseCdp {
    #private;
    readonly client: OpenBrowserUseClient;
    constructor(client: OpenBrowserUseClient);
    enableFrameSessions(tabId: number): Promise<boolean>;
    frameSessions(tabId: number): Promise<Array<{
        sessionId: string;
        frameId: string;
        parentFrameId: string;
    }>>;
    call(tabId: number, method: string, commandParams?: BrowserUseRequestParams, options?: {
        timeoutMs?: number;
        sessionId?: string;
        visualPoint?: {
            x: number;
            y: number;
        };
    }): Promise<JsonValue>;
    evaluate(tabId: number, expression: string, options?: {
        awaitPromise?: boolean;
    }): Promise<JsonValue>;
    navigate(tabId: number, url: string, options?: OpenBrowserUseGotoOptions): Promise<JsonValue>;
    waitForLoadState(tabId: number, options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    readDocumentState(tabId: number): Promise<{
        href?: string;
        readyState?: string;
    } | undefined>;
    waitForEvent(tabId: number, predicate: (notification: OpenBrowserUseNotification) => boolean, options?: {
        timeoutMs?: number;
        timeoutMessage?: string;
    }): Promise<OpenBrowserUseNotification>;
    waitForLoadEvent(tabId: number, state: OpenBrowserUseLoadState, timeoutMs: number): Promise<void>;
    ensureAttached(tabId: number): Promise<void>;
}
export declare function encodeFrame(value: JsonValue | Record<string, unknown>): Buffer;
