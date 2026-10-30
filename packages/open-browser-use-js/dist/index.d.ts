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
export type OpenBrowserUseWaitUntil = OpenBrowserUseLoadState | "commit";
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
    level?: number;
    checked?: boolean | "mixed";
    disabled?: boolean;
    pressed?: boolean | "mixed";
    selected?: boolean;
    expanded?: boolean;
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
    index?: number;
};
export type OpenBrowserUseDialogInfo = {
    id: string;
    type: "alert" | "confirm" | "prompt" | "beforeunload";
    message: string;
    url: string;
    defaultPrompt?: string;
};
export type OpenBrowserUseLogEntry = {
    level: "debug" | "info" | "log" | "warn" | "error";
    message: string;
    timestamp: string;
    url?: string;
};
export type OpenBrowserUseClipboardEntry = {
    mimeType: string;
    text?: string;
    base64?: string;
};
export type OpenBrowserUseClipboardItem = {
    entries: OpenBrowserUseClipboardEntry[];
    presentationStyle?: "unspecified" | "inline" | "attachment";
};
export type OpenBrowserUseTabPresentation = {
    backend: "chrome" | "electron";
    selected: boolean;
    visible: boolean | null;
    windowFocused: boolean | null;
};
export type TextMatcher = string | RegExp;
export type LocatorLocatorOptions = {
    hasText?: TextMatcher;
    hasNotText?: TextMatcher;
    has?: OpenBrowserUseCssLocator;
    hasNot?: OpenBrowserUseCssLocator;
};
export type RoleLocatorOptions = {
    name?: TextMatcher;
    exact?: boolean;
    level?: number;
    checked?: boolean;
    disabled?: boolean;
    pressed?: boolean;
    selected?: boolean;
    expanded?: boolean;
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
type LocatorClickOptions = {
    timeoutMs?: number;
    button?: "left" | "middle" | "right";
    modifiers?: Array<"Alt" | "Control" | "ControlOrMeta" | "Meta" | "Shift">;
    force?: boolean;
};
type LocatorCheckOptions = {
    timeoutMs?: number;
    force?: boolean;
};
type MouseClick = {
    button: "left" | "middle" | "right";
    buttons: number;
    modifiers: number;
    force?: boolean;
};
type CssMatcher = string | {
    source: string;
    flags: string;
};
type CssTextFilter = {
    title?: {
        matcher: CssMatcher;
        exact: boolean;
    };
    hasText?: CssMatcher;
    hasNotText?: CssMatcher;
    has?: readonly CssStep[];
    hasNot?: readonly CssStep[];
    and?: readonly CssStep[];
    visible?: boolean;
};
type CssStep = {
    selector: string;
    position?: number;
    before?: readonly CssTextFilter[];
    after?: readonly CssTextFilter[];
    union?: readonly [readonly CssStep[], readonly CssStep[]];
};
type DomIdentity = {
    tag: string;
    role: string | null;
    name: string | null;
    type: string | null;
    disabled: boolean;
    checked: boolean | "mixed" | null;
};
type TextFilter = {
    visible?: boolean;
    hasText?: TextMatcher;
    hasNotText?: TextMatcher;
    has?: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator;
    hasNot?: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator;
};
export declare class OpenBrowserUseClient {
    #private;
    readonly socketPath: string;
    readonly sessionId: string;
    readonly turnId: string;
    readonly timeoutMs: number;
    get connectionGeneration(): number;
    get isConnected(): boolean;
    constructor(options: OpenBrowserUseClientOptions);
    connect(): Promise<this>;
    close(): void;
    onDisconnect(handler: (error: Error) => void): () => void;
    protected emitDisconnect(error: Error): void;
    onNotification(handler: NotificationHandler): () => void;
    request(method: string, params?: BrowserUseRequestParams, expectedGeneration?: number, requestTimeoutMs?: number, signal?: AbortSignal): Promise<JsonValue>;
    getInfo(): Promise<JsonValue>;
    createTab(): Promise<JsonValue>;
    getTabs(): Promise<JsonValue>;
    getUserTabs(): Promise<JsonValue>;
    getUserHistory(params?: BrowserUseRequestParams): Promise<JsonValue>;
    claimUserTab(tabId: number): Promise<JsonValue>;
    finalizeTabs(keep: JsonValue[]): Promise<JsonValue>;
    nameSession(name: string): Promise<JsonValue>;
    attach(tabId: number, requestTimeoutMs?: number, signal?: AbortSignal): Promise<JsonValue>;
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
type BrowserTabInfo = {
    id: string;
    title?: string;
    url?: string;
    active?: boolean;
    openerTabId?: string;
};
type BrowserUserTabInfo = {
    id: string;
    title?: string;
    url?: string;
    lastOpened?: string;
    tabGroup?: string;
};
export type BrowserHistoryEntry = {
    url: string;
    dateVisited: string;
    title?: string;
};
export declare class OpenBrowserUseBrowser {
    #private;
    readonly client: OpenBrowserUseClient;
    readonly cdp: OpenBrowserUseCdp;
    browserId?: string;
    readonly tabs: OpenBrowserUseTabs;
    readonly capabilities: OpenBrowserUseCapabilities;
    readonly user: OpenBrowserUseBrowserUser;
    constructor(options: OpenBrowserUseBrowserOptions);
    connect(): Promise<this>;
    close(): void;
    nameSession(name: string): Promise<void>;
    newTab(options?: OpenBrowserUseGotoOptions & {
        url?: string;
    }): Promise<OpenBrowserUseTab>;
    tab(tabId: number): OpenBrowserUseTab;
    getTabs(): Promise<JsonValue>;
    getUserTabs(): Promise<JsonValue>;
    claimTab(tabId: number): Promise<OpenBrowserUseTab>;
}
export declare class OpenBrowserUseTabs {
    private browser;
    constructor(browser: OpenBrowserUseBrowser);
    list(): Promise<BrowserTabInfo[]>;
    get(id: string | number): Promise<OpenBrowserUseTab>;
    getByUrl(url: string): Promise<OpenBrowserUseTab>;
    new(): Promise<OpenBrowserUseTab>;
    selected(): Promise<OpenBrowserUseTab | undefined>;
    finalize(options?: {
        keep?: Array<{
            status: 'handoff' | 'deliverable';
            tab: string | number | OpenBrowserUseTab | BrowserTabInfo;
        }>;
    }): Promise<void>;
}
export declare class OpenBrowserUseBrowserUser {
    private browser;
    constructor(browser: OpenBrowserUseBrowser);
    openTabs(): Promise<BrowserUserTabInfo[]>;
    claimTab(tab: string | number | BrowserUserTabInfo): Promise<OpenBrowserUseTab>;
    history(options?: {
        from?: string | Date;
        to?: string | Date;
        limit?: number;
        query?: string;
    }): Promise<BrowserHistoryEntry[]>;
}
export type OpenBrowserUseCapabilityInfo = {
    id: string;
    description: string;
};
export type OpenBrowserUseWebMcpTool = {
    name: string;
    registration_id: string;
    input_schema: JsonValue;
    title?: string;
    description?: string;
    annotations?: JsonValue;
    origin?: string;
    pageUrl?: string;
};
export declare class OpenBrowserUseCapabilities {
    private browser;
    private tab?;
    constructor(browser: OpenBrowserUseBrowser, tab?: OpenBrowserUseTab | undefined);
    list(): Promise<OpenBrowserUseCapabilityInfo[]>;
    get(id: 'webmcp'): Promise<OpenBrowserUseWebMcp>;
    get(id: string): Promise<unknown>;
}
export declare class OpenBrowserUseWebMcp {
    private tab;
    constructor(tab: OpenBrowserUseTab);
    listTools(): Promise<OpenBrowserUseWebMcpTool[]>;
    invokeTool(tool: OpenBrowserUseWebMcpTool, input: JsonValue, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
}
export declare class OpenBrowserUseDialog {
    private cdp;
    private tabId;
    readonly info: OpenBrowserUseDialogInfo;
    constructor(cdp: OpenBrowserUseCdp, tabId: number, info: OpenBrowserUseDialogInfo);
    accept(promptText?: string): Promise<void>;
    dismiss(): Promise<void>;
}
export declare class OpenBrowserUseDownload {
    private client;
    readonly id: string;
    readonly url: string | null;
    readonly attribution: "tab" | "browser" | "unknown";
    constructor(client: OpenBrowserUseClient, id: string, url?: string | null, attribution?: "tab" | "browser" | "unknown");
    path(timeoutMs?: number): Promise<string | null>;
}
export type OpenBrowserUseDownloadStart = {
    guid: string;
    url: string;
    frameId: string;
    suggestedFilename: string;
    sessionId?: string;
};
export declare class OpenBrowserUseDownloadStartWait {
    private result;
    constructor(result: Promise<OpenBrowserUseDownloadStart>);
    wait(): Promise<OpenBrowserUseDownloadStart>;
}
export declare class OpenBrowserUseDownloadWait {
    private client;
    private result;
    constructor(client: OpenBrowserUseClient, result: Promise<JsonValue>);
    wait(): Promise<OpenBrowserUseDownload>;
}
export declare class OpenBrowserUseFileChooser {
    #private;
    private client;
    readonly id: string;
    private multiple;
    constructor(client: OpenBrowserUseClient, id: string, multiple: boolean);
    isMultiple(): boolean;
    setFiles(files: string | string[]): Promise<void>;
}
export declare class OpenBrowserUseFileChooserWait {
    #private;
    private client;
    private result;
    constructor(client: OpenBrowserUseClient, result: Promise<JsonValue>);
    wait(): Promise<OpenBrowserUseFileChooser>;
}
export declare class OpenBrowserUseTab {
    #private;
    readonly browser: OpenBrowserUseBrowser;
    readonly id: number;
    readonly playwright: OpenBrowserUseTabPlaywright;
    readonly capabilities: OpenBrowserUseCapabilities;
    readonly cua: OpenBrowserUseTabCUA;
    readonly dom_cua: OpenBrowserUseTabDomCUA;
    readonly dev: OpenBrowserUseTabDev;
    readonly clipboard: OpenBrowserUseTabClipboard;
    constructor(browser: OpenBrowserUseBrowser, id: number);
    goto(url: string, options?: OpenBrowserUseGotoOptions): Promise<JsonValue>;
    title(): Promise<string | undefined>;
    url(): Promise<string | undefined>;
    back(): Promise<void>;
    forward(): Promise<void>;
    bringToFront(): Promise<void>;
    getPresentation(): Promise<OpenBrowserUseTabPresentation>;
    private moveHistory;
    reload(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    waitForLoadState(options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    expectNavigation<T>(action: () => Promise<T>, options?: {
        timeoutMs?: number;
        url?: string | RegExp;
        waitUntil?: OpenBrowserUseLoadState;
    }): Promise<T>;
    waitForURL(url: string | RegExp, options?: {
        waitUntil?: OpenBrowserUseWaitUntil;
        timeoutMs?: number;
    }): Promise<void>;
    domSnapshot(): Promise<string>;
    getAXState(): Promise<JsonValue>;
    getAXStateAndScreenshot(options?: {
        diff?: boolean;
        includeFrames?: boolean;
        includeValues?: boolean;
        includeText?: boolean;
    }): Promise<{
        state: string;
        screenshot: OpenBrowserUseImage;
        observation: InteractiveState;
    }>;
    observe(options?: {
        diff?: boolean;
        includeFrames?: boolean;
        includeValues?: boolean;
        includeText?: boolean;
    }): Promise<InteractiveState>;
    private readAXValues;
    private frameGeometry;
    private cssFrameVisible;
    private scopeContext;
    private verifyLocatorScope;
    private prepareBrowserEvent;
    prepareDownloadStart(options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseDownloadStartWait>;
    prepareDownload(options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseDownloadWait>;
    prepareFileChooser(options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseFileChooserWait>;
    watchDialogs(): Promise<void>;
    currentDialog(): OpenBrowserUseDialog | null;
    waitForDialog(options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseDialog>;
    click(index: number, snapshotId: string, mouse?: MouseClick, markClick?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    dblclick(index: number, snapshotId: string, mouse?: MouseClick, markClick?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    scroll(index: number, snapshotId: string, direction: "up" | "down" | "left" | "right" | "u" | "d" | "l" | "r", pages?: number): Promise<void>;
    hover(index: number, snapshotId: string, mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    selectText(index: number, snapshotId: string, text: string, options?: {
        prefix?: string;
        suffix?: string;
        selectionType?: "text" | "cursor_before" | "cursor_after";
    }): Promise<void>;
    press(index: number, snapshotId: string, key: string, expectedGeneration?: number, mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    hoverAt(x: number, y: number, modifiers?: number): Promise<void>;
    private dispatchClick;
    clickAt(x: number, y: number, options?: {
        button?: number;
        modifiers?: number;
        double?: boolean;
    }): Promise<void>;
    dragPath(path: Array<{
        x: number;
        y: number;
    }>, modifiers?: number): Promise<void>;
    drag(from: [number, number], to: [number, number]): Promise<void>;
    scrollAt(x: number, y: number, deltaX: number, deltaY: number, modifiers?: number, expectedGeneration?: number, frame?: {
        sessionId: string;
        contextId: number;
        inputPoint: {
            x: number;
            y: number;
        };
    }): Promise<void>;
    private parseKey;
    pressKey(key: string, expectedGeneration?: number): Promise<void>;
    paste(index: number | null, text: string, options?: {
        snapshotId?: string;
        format?: "text" | "md" | "html";
        plainText?: string;
    }): Promise<void>;
    typeAtFocus(text: string): Promise<void>;
    private focusedInputFrame;
    private targetFrameFocused;
    private sendSequentialText;
    private sendKey;
    private checkPoint;
    getViewport(): Promise<{
        width: number;
        height: number;
    }>;
    typeText(index: number, snapshotId: string, text: string, mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    fill(index: number, snapshotId: string, text: string, mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    setChecked(index: number, snapshotId: string, checked: boolean, force?: boolean, mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<void>;
    selectOption(index: number, snapshotId: string, values: SelectOption | SelectOption[], mark?: () => AbortSignal | undefined, signal?: AbortSignal, check?: () => void): Promise<string[]>;
    private act;
    private documentId;
    private frameTree;
    private validateFrames;
    private framePoint;
    getScreenshot(options?: {
        clip?: {
            x: number;
            y: number;
            width: number;
            height: number;
        };
        fullPage?: boolean;
    }): Promise<Buffer>;
    evaluate(expression: string, options?: {
        awaitPromise?: boolean;
    }): Promise<JsonValue>;
    close(): Promise<JsonValue>;
}
export declare class OpenBrowserUseImage extends Uint8Array {
    toBase64(): string;
}
export declare class OpenBrowserUseTabCUA {
    private tab;
    constructor(tab: OpenBrowserUseTab);
    click(options: {
        x: number;
        y: number;
        button?: number;
        keypress?: string[];
    }): Promise<void>;
    double_click(options: {
        x: number;
        y: number;
        keypress?: string[];
    }): Promise<void>;
    move(options: {
        x: number;
        y: number;
        keys?: string[];
    }): Promise<void>;
    scroll(options: {
        x: number;
        y: number;
        scrollX: number;
        scrollY: number;
        keypress?: string[];
    }): Promise<void>;
    drag(options: {
        path: Array<{
            x: number;
            y: number;
        }>;
        keys?: string[];
    }): Promise<void>;
    type(options: {
        text: string;
    }): Promise<void>;
    keypress(options: {
        keys: string[];
    }): Promise<void>;
    get_visible_screenshot(): Promise<OpenBrowserUseImage>;
}
export declare class OpenBrowserUseTabDomCUA {
    private tab;
    private snapshot;
    private generation;
    private connectionGeneration;
    private busy;
    private ids;
    constructor(tab: OpenBrowserUseTab);
    private invalidate;
    private beginAction;
    get_visible_dom(): Promise<{
        nodes: Array<{
            node_id: string;
            frame_id: string;
        } & DomIdentity>;
        visibility_incomplete?: boolean;
    }>;
    private target;
    private clickNode;
    click(options: {
        node_id: string;
    }): Promise<void>;
    double_click(options: {
        node_id: string;
    }): Promise<void>;
    keypress(options: {
        keys: string[];
    }): Promise<void>;
    type(options: {
        text: string;
    }): Promise<void>;
    scroll(options: {
        node_id?: string;
        x: number;
        y: number;
    }): Promise<void>;
}
export declare class OpenBrowserUseTabClipboard {
    private tab;
    constructor(tab: OpenBrowserUseTab);
    readText(): Promise<string>;
    writeText(text: string): Promise<void>;
    read(): Promise<OpenBrowserUseClipboardItem[]>;
    write(items: OpenBrowserUseClipboardItem[]): Promise<void>;
}
export declare class OpenBrowserUseTabDev {
    private tab;
    constructor(tab: OpenBrowserUseTab);
    watch(): Promise<void>;
    logs(options?: {
        filter?: string;
        levels?: Array<OpenBrowserUseLogEntry["level"] | "warning">;
        limit?: number;
    }): Promise<OpenBrowserUseLogEntry[]>;
}
export declare class OpenBrowserUseTabPlaywright {
    readonly tab: OpenBrowserUseTab;
    constructor(tab: OpenBrowserUseTab);
    waitForLoadState(options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    expectNavigation<T>(action: () => Promise<T>, options?: {
        timeoutMs?: number;
        url?: string | RegExp;
        waitUntil?: OpenBrowserUseLoadState;
    }): Promise<T>;
    waitForURL(url: string | RegExp, options?: {
        waitUntil?: OpenBrowserUseWaitUntil;
        timeoutMs?: number;
    }): Promise<void>;
    expectPopup(action: () => Promise<unknown>, options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseTab>;
    domSnapshot(): Promise<string>;
    evaluate<T extends JsonValue = JsonValue>(pageFunction: string | ((arg: T) => unknown), arg?: T, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
    screenshot(options?: {
        clip?: {
            x: number;
            y: number;
            width: number;
            height: number;
        };
        fullPage?: boolean;
    }): Promise<OpenBrowserUseImage>;
    waitForTimeout(timeoutMs: number): Promise<void>;
    waitForEvent(event: "download", options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseDownload>;
    waitForEvent(event: "filechooser", options?: {
        timeoutMs?: number;
    }): Promise<OpenBrowserUseFileChooser>;
    frameLocator(selector: string): OpenBrowserUseFrameLocator;
    locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator;
    getByTestId(testId: string): OpenBrowserUseCssLocator;
    getByTitle(title: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseCssLocator;
    getByRole(role: string, options?: RoleLocatorOptions): OpenBrowserUseRoleLocator;
    getByLabel(name: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByAltText(altText: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByPlaceholder(placeholder: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
}
export declare class OpenBrowserUseFrameLocator {
    private tab;
    private path;
    constructor(tab: OpenBrowserUseTab, path: readonly string[]);
    frameLocator(selector: string): OpenBrowserUseFrameLocator;
    locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator;
    getByTestId(testId: string): OpenBrowserUseCssLocator;
    getByTitle(title: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseCssLocator;
    getByRole(role: string, options?: RoleLocatorOptions): OpenBrowserUseRoleLocator;
    getByLabel(name: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByAltText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByPlaceholder(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
}
export declare class OpenBrowserUseCssLocator {
    private tab;
    private selector;
    private framePath?;
    private position?;
    private scopes;
    private before;
    private after;
    private union?;
    private semanticScope?;
    constructor(tab: OpenBrowserUseTab, selector: string, framePath?: readonly string[] | undefined, position?: number | undefined, scopes?: readonly CssStep[], before?: readonly CssTextFilter[], after?: readonly CssTextFilter[], union?: readonly [readonly CssStep[], readonly CssStep[]] | undefined, semanticScope?: OpenBrowserUseRoleLocator | undefined);
    nth(index: number): OpenBrowserUseCssLocator;
    first(): OpenBrowserUseCssLocator;
    last(): OpenBrowserUseCssLocator;
    locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator;
    getByTestId(testId: string): OpenBrowserUseCssLocator;
    getByTitle(title: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseCssLocator;
    getByRole(role: string, options?: RoleLocatorOptions): OpenBrowserUseRoleLocator;
    getByLabel(name: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByAltText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByPlaceholder(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    private step;
    private innerSteps;
    and(locator: OpenBrowserUseCssLocator): OpenBrowserUseCssLocator;
    and(locator: OpenBrowserUseRoleLocator): OpenBrowserUseRoleLocator;
    or(locator: OpenBrowserUseCssLocator): OpenBrowserUseCssLocator;
    filter(options: {
        hasText?: TextMatcher;
        hasNotText?: TextMatcher;
        has?: OpenBrowserUseCssLocator;
        hasNot?: OpenBrowserUseCssLocator;
        visible?: boolean;
    }): OpenBrowserUseCssLocator;
    count(): Promise<number>;
    all(): Promise<OpenBrowserUseCssLocator[]>;
    allTextContents(options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
    allInnerTexts(options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
    private readAllText;
    private perform;
    evaluate<T extends JsonValue = JsonValue>(pageFunction: string | ((element: Element, arg: T) => unknown), arg?: T, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
    evaluateAll<T extends JsonValue = JsonValue>(pageFunction: string | ((elements: Element[], arg: T) => unknown), arg?: T, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
    private read;
    isEnabled(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isChecked(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isEditable(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    boundingBox(options?: {
        timeoutMs?: number;
    }): Promise<{
        x: number;
        y: number;
        width: number;
        height: number;
    } | null>;
    inputValue(options?: {
        timeoutMs?: number;
    }): Promise<string>;
    isVisible(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isHidden(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isDisabled(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    waitFor(options?: {
        state?: "attached" | "detached" | "visible" | "hidden";
        timeoutMs?: number;
    }): Promise<void>;
    downloadMedia(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    click(options?: LocatorClickOptions): Promise<void>;
    dblclick(options?: LocatorClickOptions): Promise<void>;
    hover(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    check(options?: LocatorCheckOptions): Promise<void>;
    uncheck(options?: LocatorCheckOptions): Promise<void>;
    setChecked(checked: boolean, options?: LocatorCheckOptions): Promise<void>;
    focus(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    press(key: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    clear(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    fill(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    type(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    pressSequentially(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    selectOption(values: SelectOption | SelectOption[], options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
    innerText(options?: {
        timeoutMs?: number;
    }): Promise<string>;
    textContent(options?: {
        timeoutMs?: number;
    }): Promise<string | null>;
    getAttribute(name: string, options?: {
        timeoutMs?: number;
    }): Promise<string | null>;
}
export declare class OpenBrowserUseRoleLocator {
    private tab;
    private roles;
    private options;
    private position?;
    private textMatch;
    private field;
    private scope?;
    private filtersBefore;
    private filtersAfter;
    private framePath?;
    private cssScope?;
    private combination?;
    constructor(tab: OpenBrowserUseTab, roles: readonly string[], options: RoleLocatorOptions, position?: number | undefined, textMatch?: boolean, field?: "name" | "placeholder" | "altText", scope?: OpenBrowserUseRoleLocator | undefined, filtersBefore?: TextFilter[], filtersAfter?: TextFilter[], framePath?: readonly string[] | undefined, cssScope?: OpenBrowserUseCssLocator | undefined, combination?: {
        kind: "and" | "or";
        left: OpenBrowserUseRoleLocator;
        right: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator;
    } | undefined);
    nth(index: number): OpenBrowserUseRoleLocator;
    first(): OpenBrowserUseRoleLocator;
    last(): OpenBrowserUseRoleLocator;
    locator(selector: string, options?: LocatorLocatorOptions): OpenBrowserUseCssLocator;
    getByTestId(testId: string): OpenBrowserUseCssLocator;
    getByTitle(title: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseCssLocator;
    private child;
    getByRole(role: string, options?: RoleLocatorOptions): OpenBrowserUseRoleLocator;
    getByLabel(name: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByAltText(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    getByPlaceholder(text: TextMatcher, options?: {
        exact?: boolean;
    }): OpenBrowserUseRoleLocator;
    private combine;
    and(other: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator): OpenBrowserUseRoleLocator;
    or(other: OpenBrowserUseRoleLocator): OpenBrowserUseRoleLocator;
    filter(options: {
        hasText?: TextMatcher;
        hasNotText?: TextMatcher;
        has?: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator;
        hasNot?: OpenBrowserUseRoleLocator | OpenBrowserUseCssLocator;
        visible?: boolean;
    }): OpenBrowserUseRoleLocator;
    private needsText;
    private matches;
    private identities;
    private guard;
    private find;
    count(): Promise<number>;
    all(): Promise<OpenBrowserUseRoleLocator[]>;
    allTextContents(options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
    allInnerTexts(options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
    private readAllText;
    evaluate<T extends JsonValue = JsonValue>(pageFunction: string | ((element: Element, arg: T) => unknown), arg?: T, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
    evaluateAll<T extends JsonValue = JsonValue>(pageFunction: string | ((elements: Element[], arg: T) => unknown), arg?: T, options?: {
        timeoutMs?: number;
    }): Promise<JsonValue>;
    innerText(options?: {
        timeoutMs?: number;
    }): Promise<string>;
    textContent(options?: {
        timeoutMs?: number;
    }): Promise<string | null>;
    isEnabled(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isChecked(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isEditable(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    boundingBox(options?: {
        timeoutMs?: number;
    }): Promise<{
        x: number;
        y: number;
        width: number;
        height: number;
    } | null>;
    inputValue(options?: {
        timeoutMs?: number;
    }): Promise<string>;
    isVisible(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isHidden(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    isDisabled(options?: {
        timeoutMs?: number;
    }): Promise<boolean>;
    waitFor(options?: {
        state?: "visible" | "hidden";
        timeoutMs?: number;
    }): Promise<void>;
    getAttribute(name: string, options?: {
        timeoutMs?: number;
    }): Promise<string | null>;
    private perform;
    downloadMedia(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    click(options?: LocatorClickOptions): Promise<void>;
    dblclick(options?: LocatorClickOptions): Promise<void>;
    hover(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    focus(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    press(key: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    clear(options?: {
        timeoutMs?: number;
    }): Promise<void>;
    fill(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    type(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    pressSequentially(text: string, options?: {
        timeoutMs?: number;
    }): Promise<void>;
    check(options?: LocatorCheckOptions): Promise<void>;
    uncheck(options?: LocatorCheckOptions): Promise<void>;
    setChecked(checked: boolean, options?: LocatorCheckOptions): Promise<void>;
    selectOption(values: SelectOption | SelectOption[], options?: {
        timeoutMs?: number;
    }): Promise<string[]>;
}
export declare class OpenBrowserUseCdp {
    #private;
    readonly client: OpenBrowserUseClient;
    constructor(client: OpenBrowserUseClient);
    private enableLogSession;
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
        expectedGeneration?: number;
        signal?: AbortSignal;
    }): Promise<JsonValue>;
    evaluate(tabId: number, expression: string, options?: {
        awaitPromise?: boolean;
        throwOnSideEffect?: boolean;
        timeoutMs?: number;
        signal?: AbortSignal;
    }): Promise<JsonValue>;
    navigate(tabId: number, url: string, options?: OpenBrowserUseGotoOptions): Promise<JsonValue>;
    waitForLoadState(tabId: number, options?: OpenBrowserUseWaitForLoadStateOptions): Promise<void>;
    readDocumentStateStrict(tabId: number): Promise<{
        href?: string;
        readyState?: string;
    }>;
    readDocumentState(tabId: number): Promise<{
        href?: string;
        readyState?: string;
    } | undefined>;
    waitForEvent(tabId: number, predicate: (notification: OpenBrowserUseNotification) => boolean, options?: {
        timeoutMs?: number;
        timeoutMessage?: string;
        signal?: AbortSignal;
    }): Promise<OpenBrowserUseNotification>;
    waitForLoadEvent(tabId: number, state: OpenBrowserUseLoadState, timeoutMs: number, signal?: AbortSignal): Promise<void>;
    ensureAttached(tabId: number, requestTimeoutMs?: number, signal?: AbortSignal): Promise<void>;
}
export declare function encodeFrame(value: JsonValue | Record<string, unknown>): Buffer;
export {};
