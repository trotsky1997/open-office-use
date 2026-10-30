# Open Browser Use JavaScript SDK

JavaScript/TypeScript client for controlling a real Chrome profile through
Open Browser Use. The SDK keeps the low-level JSON-RPC/CDP surface available and
also provides higher-level browser/tab helpers for common agent workflows.

## Prerequisites

- The `open-browser-use` CLI and Chrome extension are installed and connected.
- `open-browser-use ping` returns `"pong"`.
- The native host has written an active socket registry at
  `/tmp/open-browser-use/active.json`.

```sh
open-browser-use ping
open-browser-use info
```

## Installation

To use the current fork's source build, follow the [repository source setup](../../README.md#run-this-branch-from-source). The REPL entry point is `dist/repl-cli.js` in this package directory; configure its absolute path as shown there. The following npm command installs the published upstream package, whose feature set may differ.

```sh
npm install open-browser-use-sdk
```

## High-Level Browser API

Use `connectOpenBrowserUse` when you want a Playwright-like flow in a normal
Node runtime.

```js
import { readFile } from "node:fs/promises";
import { connectOpenBrowserUse } from "open-browser-use-sdk";

const registry = JSON.parse(
  await readFile("/tmp/open-browser-use/active.json", "utf8")
);

const browser = await connectOpenBrowserUse({
  socketPath: registry.socketPath,
  sessionId: "github-issue-scan",
  turnId: `turn-${Date.now()}`,
  timeoutMs: 20000,
});

let tab;

try {
  await browser.client.nameSession("GitHub issue scan - OBU");

  tab = await browser.newTab();

  await tab.goto("https://github.com/iFurySt/open-codex-computer-use/issues", {
    waitUntil: "domcontentloaded",
    timeoutMs: 15000,
  });

  await tab.playwright.waitForLoadState({
    state: "domcontentloaded",
    timeoutMs: 15000,
  });

  const snapshot = await tab.playwright.domSnapshot();
  const relevant = snapshot
    .split("\n")
    .filter((line) =>
      /Open|Closed|Issues|issue|No results|open-codex-computer-use|Pull requests|Starred/.test(line)
    );

  console.log(relevant.slice(0, 160).join("\n"));
} finally {
  await browser.client.finalizeTabs([]);
  browser.close();
}
```

The same tab helpers are available without the `playwright` alias:

```js
await tab.goto(url, { waitUntil: "load", timeoutMs: 15000 });
await tab.waitForLoadState({ state: "domcontentloaded", timeoutMs: 15000 });
const text = await tab.domSnapshot();
const value = await tab.evaluate("document.title");
const axTree = await tab.getAXState(); // CDP accessibility tree
const png = await tab.getScreenshot(); // PNG Buffer
```

`domSnapshot()` returns a bounded accessibility snapshot with roles, names,
states and readable frame content. Indentation follows the reported accessibility
parent-child tree, capped at 80 levels; readable frame documents appear under
their iframe when the browser exposes the owner node. A frame whose location
cannot be established appears in a separate section marked `frame placement
unavailable`. It marks truncated output and inaccessible
frames, does not explicitly read form values, and replaces the previous
`observe()` result; call `observe()` again before using an observation index.
Page-provided accessible names and text can still contain sensitive data.

The accessibility tree is the raw CDP response. It does not provide stable
interaction indices or state diffs; request a fresh tree after page changes.

For indexed interaction, call `observe` immediately before choosing a target:

```js
const state = await tab.observe();
nodeRepl.write(state.text);
const button = state.nodes.find(node => node.role === "button" && node.name === "Save");
if (button) await tab.click(button.index, state.snapshotId);

const next = await tab.observe();
const field = next.nodes.find(node => node.role === "textbox" && node.name === "Message");
if (field) await tab.typeText(field.index, next.snapshotId, "Hello");
```

`state.text` contains named accessibility nodes in the order returned by CDP;
interactive nodes include their index and available checked, selected, expanded,
disabled, pressed, required and readonly states. It is capped at 30,000 characters and
`state.truncated` indicates when content was cut. `state.nodes` lists the
interactive targets independently. An observation is single-use. Clicking rechecks the document and accessible
role, name and listed state, scrolls the target into view, and rejects disabled, hidden or covered
targets. It sends a real CDP mouse click. Observe again after an action or a
rejected click. This initial interface lists common interactive accessibility
roles. Hit testing checks nested open and closed shadow roots and their hosts.
Text input inserts at the clicked caret in a focused editable
textbox; it does not replace existing content. Page changes can still race the
final input event.

To include current accessible field values, request
`await tab.observe({includeValues:true, includeFrames:true})`. Values appear in
the returned nodes and text when their element type can be verified. Native
password inputs are marked `valueRedacted`; unknown or inaccessible element
types are marked `valueUnavailable`. Each value is limited to 512 characters,
with an 8,000-character total budget; `valueTruncated` and `valuesTruncated`
report omissions. Switching `includeValues` resets the diff baseline. Ordinary
text field contents are returned when requested, so use this on authorized
pages. Page text itself can also contain sensitive information.

Use `await tab.fill(index, snapshotId, text)` to replace the content of an
observed text field. It focuses the target, selects its existing contents,
sends trusted keyboard/text input, and checks the resulting value. An empty
string clears the field. Selection verification for `contenteditable` uses
rendered text; unusual rich-text selection or value normalization can cause the
operation to report an error.

`fill` also supports native number, date, time, month, week and
`datetime-local` inputs. Number fields use keyboard/text input; an invalid
replacement is rejected before editing. Date and time values must use the
browser's native value format, such as `2026-12-31` or `09:45`. Those fields
are set through the DOM and dispatch `input` and `change` events with
`isTrusted === false`. The browser's min, max and step constraints remain the
page's responsibility.

For semantic selection, the REPL and SDK also accept:

```js
const save = tab.playwright.getByRole("button", { name: "Save", exact: true });
const saveOrSubmit = tab.playwright.getByRole("button", { name: /^(save|submit)$/i });
const sectionTitle = tab.playwright.getByRole("heading", { name: "Details", level: 2 });
console.log(await save.innerText());
console.log(await save.getAttribute("type")); // null if the attribute is absent
console.log(await save.isEnabled());
console.log(await save.isVisible());
await save.hover(); // move the pointer over the matched control
await save.click();
// await save.dblclick(); // when the page requires a double click
await tab.playwright.getByRole("textbox", { name: "Message" }).fill("Hello");
await tab.playwright.getByRole("textbox", { name: "Message" }).press("Enter");
await tab.playwright.getByPlaceholder("Email address", { exact: true }).fill("user@example.com");
await tab.playwright.getByLabel("Email updates", { exact: true }).check();
await tab.playwright.getByLabel("Email updates", { exact: true }).setChecked(false);
await tab.playwright.getByRole("checkbox", { name: "Alerts", checked: false }).check();
await tab.playwright.getByLabel("Colour", { exact: true }).selectOption({ label: "Blue" });
await tab.playwright.getByText("Continue", { exact: true }).click();
await tab.playwright.getByRole("img", { name: "Product photo", exact: true }).click();
await tab.playwright.getByAltText("Product photo", { exact: true }).click();
const dialog = tab.playwright.getByRole("dialog", { name: "Sign in", exact: true });
await dialog.hover();
await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
await tab.playwright.getByRole("listitem").filter({ hasText: "Apples" })
  .getByRole("button", { name: "Add", exact: true }).click();
```

`innerText()` reads the matched DOM node, including in supported frames. It
requires one match and rejects text longer than 30,000 characters.
Heading locators can filter by positive integer `level`; observations expose
the browser-reported level when available.
`textContent()` reads the raw DOM text, including hidden descendants, with the
same match and length checks.
`allTextContents()` reads raw text from all current semantic matches in one
observation, returning an empty array when there are none. Each value is limited
to 30000 characters and the total to 1000000. The page can change between reads;
stale targets are retried within the optional `timeoutMs`.
`isVisible()` checks CSS visibility and nonzero bounds for the matched node and
its frame owners; an absent accessible match returns `false`. Offscreen or
covered elements can still be visible. Locator matching uses the accessibility
tree, so elements omitted from that tree cannot be detected by this method.
`waitFor({state: "visible" | "hidden", timeoutMs})` polls the same semantic
visibility check. `hidden` includes absent accessible matches; `attached` and
`detached` are not supported because accessibility matching does not expose
every DOM node. Polling may miss transient changes, and a slow browser request
can finish after the timeout.
`getAttribute(name)` reads the raw attribute from one match and returns `null`
when absent; it applies the same size limit. Text-node matches do not have
attributes; select their containing element to read its attributes.
`last()` selects the last current match. `all()` returns positional locators
for the current match count; each locator resolves again when used, so page
changes can alter which element occupies a position.
Role names, labels, text, placeholders, alt text and text filters accept strings
or `RegExp` objects. Regular expressions retain their own case-sensitivity;
the `exact` option applies to string matching.
`dblclick()` rechecks the target and its position between clicks. If the first
click changes the page or a later input fails, inspect the result before retrying.

This locator covers the interactive roles exposed by `observe`, including
accessible frames, plus headings, accessible text, images, dialogs and
structural roles such as group, list, listitem, table, row, cell and navigation. The `img` role
uses the accessibility name, including an image alt attribute when it supplies
that name. It reobserves on every `count`, `click`, `fill`, or `type`
call and refuses incomplete frame results. Actions require exactly one match;
use `first()` or `nth(n)` to choose among multiple matches. Name matching is a
case-insensitive substring by default; `exact: true` matches the whole name
case-sensitively. Actions wait up to 5 seconds when a match is missing,
temporarily covered, moving or changed before input; pass
`{timeoutMs: 0}` for one attempt or another timeout up to 120 seconds. Target
geometry is sampled twice 75 ms apart before input, including the translated
frame position; this catches movement visible between those samples.
The limit controls when another observation starts; a slow browser request can
finish after it. Multiple matches fail immediately. An issued input action is
not retried after an error. This initial locator API does not include every
Playwright locator method.

Locators can be chained to search descendants of matching accessible containers.
For example, `getByRole("dialog", {name: "Settings"}).getByRole("button",
{name: "Save"})` narrows a repeated button name to that dialog. Descendant
checks cross shadow roots and iframe boundaries. Scope roles and containment are
checked again before input; a focus handler can also change the scope, so
`press()` checks it after focusing. This API follows the accessible tree and
requires all observed frames to be readable.

`filter({hasText: "..."})` and `filter({hasNotText: "..."})` narrow a
locator by its accessible static-text descendants. Matching is a case-insensitive
substring after whitespace normalization; text fragments are joined with spaces.
This includes readable child frames and shadow roots. The filter uses indexed
accessibility text, so `aria-label` alone does not count as descendant text.
The operation rejects a candidate when unindexed text may belong to it or
the text relationship cannot be determined, when frames are inaccessible, or
when the candidate contains more than 30,000 characters. Text is checked again before input and after focus; pages with many
text nodes can require many browser requests. Only string filters are supported.

`getByText` matches individual accessible static-text nodes after collapsing
whitespace; text split across multiple elements is matched separately. Text
clicks target the visible text rectangle, checking disabled ancestors and
hit-testing shadow roots and frames. `getByRole("heading", ...)` supports
accessible headings; `getByRole("img", ...)` supports accessible images.
`getByRole("dialog", ...)` and `getByRole("alertdialog", ...)` support
accessible dialog containers. To include these nodes in an indexed observation directly,
use `includeText: true`; switching it resets the diff baseline.

`getByRole` also accepts boolean `checked`, `disabled`, `pressed`, `selected` and
`expanded` filters. A filter matches when the corresponding state is explicitly
present in the accessibility tree; a mixed state does not match either boolean.
For `disabled`, the absence of the accessibility flag is treated as enabled.
Observations expose disabled targets and their state. Hover can target a disabled
control; clicks, keyboard input and state changes check the target and its
ancestors for disability before input. Even an already-correct check validates
its enabled state. State changes invalidate old targets, and unsupported role
options are rejected.

`getByLabel` matches the accessible name of supported form controls and accepts
the same `exact` option. `check()` and `uncheck()` check the current state,
click only when a change is needed, and verify the resulting state. The
observation's nodes include `checked` when available. Mixed states and clearing
a selected radio directly are rejected; choose another radio to change a group.

`getByAltText` matches the native `alt` attribute exposed by the accessibility
tree, including when `aria-label` supplies a different accessible name. It
covers accessible images and image inputs or links with an exposed `alt`
source. Observations expose `altText` up to 512 characters and mark longer
values with `altTextTruncated`; an alt locator rejects incomplete results.

`getByPlaceholder` matches the native or ARIA placeholder exposed in the
accessibility tree, including when a label supplies a different accessible name.
Observations expose `placeholder` and flag `placeholderTruncated` above 512
characters. A truncated placeholder makes placeholder locator results
incomplete, so the locator rejects the query. Action support still depends on
the control type.

`selectOption` accepts a value or label, `{value, label}`, or an array for a
multiple select, and returns selected values. It waits for available options
and rejects ambiguous matches. This operation updates a native `<select>` via
the DOM and dispatches bubbling `input` and `change` events; those events have
`isTrusted === false`. Custom ARIA combobox widgets should be operated through
their own controls.

Use `await tab.observe({ includeFrames: true })` to include iframe controls.
Their entries include `frameId`, and `click`/`typeText` translate coordinates
through ancestor frames and reject stale, covered, rotated or otherwise
unsupported geometry. Chrome and Electron attach scoped iframe debugger sessions
for cross-process frames and report `frameCoverage: "cross-process"`.
`unavailableFrames`
lists known frames whose trees could not be read. Debugger attachment and frame
navigation can change during an operation; observe again if validation fails.

For later observations on the same tab object, `await tab.observe({ diff: true })`
returns changed text lines prefixed with `-` or `+` and `textMode: "diff"`.
Unchanged text yields an empty string. `nodes` and `snapshotId` always describe
the latest full observation; use those indexes for subsequent actions. A first
observation, navigation, or a truncated baseline returns `textMode: "full"`.
The line diff preserves order and may include unchanged lines between edits.
If a diff itself is truncated, the next observation returns a full baseline.

For visual interaction, `await tab.getViewport()` returns the CSS viewport size;
`await tab.clickAt(x, y)` clicks, `await tab.hoverAt(x, y)` moves the pointer,
and `await tab.scrollAt(x, y, deltaX, deltaY)` sends a wheel event at CSS
viewport coordinates. These reject coordinates outside
the viewport and invalidate any prior observation. Screenshot pixels can differ
from CSS coordinates on high-density displays: scale the coordinates using the
image dimensions and `getViewport()` before sending input. Observe or capture a
fresh screenshot after page changes. To capture a region, call
`await tab.getScreenshot({clip: {x, y, width, height}})` with a rectangle in
CSS viewport coordinates. The region must fit inside the viewport. Its PNG
pixel dimensions depend on the display scale. To click a point in the cropped
image, scale it by the clip dimensions and add the clip's x/y origin. If the
page scrolls or resizes
while the screenshot is being captured, capture it again. Use
`await tab.getScreenshot({fullPage:true})` to capture the document beyond the
viewport. Full-page capture and `clip` cannot be combined. The CSS content area
is limited to 32 million square pixels and each dimension to 32767 CSS pixels;
larger pages return an error. Electron also rejects screenshot results near its
8 MiB encoded transport limit. Offscreen lazy content may need to be loaded
before capture. Electron requires the target tab to be
presented in a host window for wheel gestures; detached tabs return
`IAB_SCROLL_REQUIRES_PRESENTED_SURFACE`. Hidden or minimized windows temporarily
disable background throttling while dispatching a trusted wheel event.
`IAB_INPUT_PREPARATION_TIMEOUT` means mouse input was not sent;
`IAB_INPUT_OUTCOME_UNKNOWN` and `IAB_BACKGROUND_SCROLL_TIMEOUT` require observing
the page before retrying.

`await tab.drag([startX, startY], [endX, endY])` sends a left-button drag
through intermediate points. Both endpoints use CSS viewport coordinates;
the SDK attempts to release the button if a move fails.

The `tab.cua` interface exposes the same visual workflow with Codex-style
options:

```js
const image = await tab.cua.get_visible_screenshot(); // Uint8Array with toBase64()
nodeRepl.emitImage(image);
await tab.cua.click({x: 120, y: 80});
await tab.cua.double_click({x: 120, y: 80, keypress: ["Shift"]});
await tab.cua.move({x: 140, y: 90});
await tab.cua.drag({path: [{x: 140, y: 90}, {x: 180, y: 90}, {x: 200, y: 120}]});
await tab.cua.scroll({x: 200, y: 120, scrollX: 0, scrollY: 300});
await tab.cua.keypress({keys: ["ControlOrMeta", "a"]});
await tab.cua.type({text: "Hello"});
```

Coordinates are CSS viewport pixels. Click buttons 1–5 map to left, middle,
right, back and forward; mouse modifiers accept Alt, Control, ControlOrMeta,
Meta and Shift. Drag uses the supplied path, limited to 1000 points, and
attempts to release the button on failure. Coordinate actions do not verify
the identity of the element under the pointer; observe the page again after
an uncertain outcome. Typing targets the current focus and does not verify the
result. Pointer modifiers set the event's modifier flags. Electron scrolling
requires a presented surface. Chrome task tabs start in the background. When
visual rendering or scrolling requires an active tab, explicitly call
`await tab.bringToFront()`; this activates the tab and can change the user's
visible browser. Electron surfaces are presented by the host and do not expose
this method through their page grant. In isolated Linux ARM64 Chromium 150,
background wheel input timed out or failed to move a fixed nested scroller;
activating the task tab allowed ordinary and modified wheel input and a
subsequent screenshot. An input timeout can have an unknown outcome; inspect
the page before retrying. Other desktop and operating-system configurations
need validation.

A locator’s `press("Enter")` focuses its matched target, verifies focus and
then sends the key; focus handlers can change the page. Frame targets use their
own debugger session. Letters, digits, Space and common ASCII punctuation
produce text in editable targets. `Shift+B`, `Shift+1` and `@` use US keyboard
key mappings. A focus or key event that has
been issued is not retried after an error.

`await tab.pressKey("Enter")` sends a key press to the currently focused
element. It checks the focused frame chain and routes to its debugger session;
if frame ownership or focus cannot be checked, or changes before dispatch,
it fails before sending the key. Focus can still change after the final check.
Supported keys include Enter, Tab, Escape, Backspace, Delete, arrows,
Home, End, PageUp, PageDown, Space, letters, digits and common ASCII punctuation.
Prefix modifiers with `+`, for example `ControlOrMeta+A` selects all on the
host platform. `+` is supported alone; use `Shift+=` with other modifiers.

`await tab.typeAtFocus("你好 🙂")` inserts text at the current focus, using the
same frame routing checks as `pressKey`. It does not select a target or verify
that the focused element accepted the text. It uses text insertion rather than
individual key events; inspect the page after an error before retrying.
For arbitrary Unicode text, use `typeText`. Pressing a key invalidates the previous
observation.

## Browser history

`await tab.back()` and `await tab.forward()` move through the tab's session
history; at either boundary they return without navigating. These methods return
after the browser accepts the command, so use `waitForURL` for a distinct
expected destination. `await tab.reload()` waits for the main page load event,
with a 10-second timeout. If a command fails after dispatch, inspect the page
before deciding whether to try again.

## Waiting for a URL

`await tab.waitForURL("https://example.com/done")` waits for an exact URL.
`await tab.playwright.waitForURL(/\/done(?:\?|$)/, {waitUntil: "domcontentloaded", timeoutMs: 15000})`
accepts a regular expression. Both forms inspect the current main document and
work with history API route changes as well as document navigation. The default
load state is `load` and the default timeout is 10 seconds; `timeoutMs: 0`
checks once. URLs are sampled roughly every 100 ms, so transient intermediate
URLs can be missed. A slow browser request can finish after the timeout.

To observe navigation triggered by an action, register the wait before the
action runs:

```js
await tab.playwright.expectNavigation(
  () => tab.playwright.getByRole("link", {name: "Continue", exact: true}).click(),
  {url: "https://example.com/done", timeoutMs: 15000}
);
```

This watches main-frame document and same-document navigation, then waits for
the requested URL and load state. A timeout or action error can occur after
the action has taken effect; inspect the page before retrying. The timeout also
bounds a pending action callback; it cannot cancel a command already issued.

## Clipboard

Tabs expose clipboard operations when their backend permits them:

```js
await tab.clipboard.writeText("hello");
const text = await tab.clipboard.readText();
await tab.clipboard.write([{entries: [{mimeType: "text/plain", text: "hello"}]}]);
const items = await tab.clipboard.read(); // entries contain text or base64
```

Chrome pages must satisfy the browser's secure-context, focus and permission
requirements. Electron 44 requires explicit host grants; see the
[Electron guide](../open-browser-use-electron/README.md#explicit-clipboard-grants).
These calls can read or replace the system clipboard; an error after a write may
leave its outcome unknown. For an isolated Chromium clipboard smoke, use
`OBU_TEST_CLIPBOARD=1` with `scripts/chromium-native-smoke.mjs`; the smoke grants
clipboard permission only in its temporary test profile and writes fixture data
to its clipboard. Run it where the clipboard is isolated from your desktop.

## Page developer logs

Call `await tab.dev.watch()` before the action to capture console calls,
uncaught JavaScript exceptions and browser log entries such as resource-load
errors, including supported cross-process frames.
Read them with `await tab.dev.logs({levels: ["error", "warning"], filter: "save", limit: 20})`.
Calling `logs()` starts capture if necessary. Capture retains up to 500 entries
per tab, with messages and source URLs capped at 4,096 characters; arguments
are rendered from CDP values or descriptions. Entries are cleared on debugger
detach, tab closure or client disconnect. Earlier console history depends on
what the browser supplies when the runtime is enabled.

## JavaScript dialogs

Call `watchDialogs()` before triggering a JavaScript dialog. Start the action
without awaiting it, then wait for and explicitly handle the dialog:

```js
await tab.watchDialogs();
const waiting = tab.waitForDialog({ timeoutMs: 5000 });
const action = tab.evaluate("confirm('Continue?')");
void action.catch(() => {});
const dialog = await waiting;
console.log(dialog.info.type, dialog.info.message, dialog.info.url);
await dialog.dismiss(); // or await dialog.accept()
console.log(await action);
```

A pending dialog or load-event wait fails promptly when its tab closes, its
debugger detaches, or the client connection closes. A different tab's lifecycle
events do not interrupt the wait.

`currentDialog()` returns the active dialog or `null`. Prompt dialogs expose
`info.defaultPrompt` and can be answered with `dialog.accept('text')`. A dialog
handle permits one decision; a disconnect invalidates it. If a decision fails
with an unknown outcome, inspect the page before trying another action. Chrome
supports prompt dialogs; Electron does not implement `window.prompt()`.
Electron may show a hidden host window when a native dialog opens.

## Persistent JavaScript MCP

The source build provides `dist/repl-cli.js`, an MCP stdio server for trusted
local agents. Configure it using the absolute-path example in the
[source setup](../../README.md#run-this-branch-from-source). When using a
published package that includes the `obu-repl-mcp` executable, its config is:

```toml
[mcp_servers.open_browser_use_repl]
command = "obu-repl-mcp"
```

Its `js` tool evaluates code in one persistent Node REPL, including top-level
`await`. Bind a browser and tab once, then reuse them across tool calls:

```js
const browser = await connectBrowser();
const tab = await browser.newTab();
await tab.goto("https://example.com");
nodeRepl.write(await tab.getAXState());
nodeRepl.emitImage(await tab.getScreenshot());
```

`discoverBrowsers()` probes sockets in `/tmp/open-browser-use` and returns
their paths and status, with browser metadata for responsive connections.
`getBrowserState()` provides a common inventory in Chrome and the Electron
host: `available` identifies selectable browsers, and `sessions` lists the
tabs belonging to browser sessions already connected in the REPL. Electron
always restricts its embedded browser to the host-authorized scope. A host can
also explicitly enable Chrome discovery with `--allow-extension-discovery`; see
the [Electron REPL guide](../open-browser-use-electron/README.md#iab-mcp-for-agents).
A session that cannot list tabs returns an `error` in that entry.
Select an inventory entry with `await connectBrowser({ browserId: entry.id })`.
The Electron entry is `host` and reuses its authorized connection. When the
host has enabled Chrome discovery and any Chrome socket is present, an explicit
browser ID is required.
`connectBrowser()` selects the sole responsive connection when no socket is
unresponsive; when several are available or a probe fails, pass `{ socketPath, sessionId }`
to select one explicitly. Use `obu profiles --connected --json` to map sockets
to installed browser profiles. Set `OBU_SOCKET_DIR` when the host uses a
different socket directory. `nodeRepl.write`
emits text, and `nodeRepl.emitImage(bytes, mimeType)` emits PNG (the default),
JPEG or WebP bytes. Tool calls run sequentially. Closing MCP stdin closes the
SDK connections while preserving browser tabs; use the existing session
finalization APIs when tabs should be cleaned up.

For an isolated Chromium integration check (Node 22+ and a Chromium executable
that supports unpacked extensions), run from the repository root:

```sh
go build -o build/obu-bridge-smoke ./cmd/open-browser-use
OBU_CHROMIUM_PATH=/path/to/chromium node scripts/chromium-bridge-smoke.mjs
```

The smoke uses a temporary extension copy and a CDP test bridge between its
background worker and the Go relay. It exercises the extension backend, relay,
SDK and REPL, while native-messaging registration needs separate verification.

On Linux or macOS, the native messaging path can be checked with an isolated temporary
profile and host manifest:

```sh
go build -o build/obu-native-smoke ./cmd/open-browser-use
OBU_CHROMIUM_PATH=/path/to/chromium node scripts/chromium-native-smoke.mjs
```

Set `OBU_MIXED_SMOKE=1` to additionally exercise mixed-backend routing using a
host authorization fixture and the real Chrome extension and native host.
On a machine with Electron installed, `OBU_MIXED_ELECTRON=1` also runs the full
Electron example smoke while that isolated Chrome connection is active.

For a disposable environment where Chromium's sandbox cannot run, set
`OBU_CHROMIUM_NO_SANDBOX=1`. This is intended for isolated test environments.
The test removes its temporary browser profile after exit.
It copies the built host into the temporary directory before Chromium launches it.

This tool executes arbitrary local Node.js code with the MCP server user's
permissions. Connect it only to trusted local agents. It currently supports the
Chrome extension socket. Electron hosts can launch the same REPL through the
host-authorized `obu-iab-repl-mcp` entry point; see the
[Electron integration guide](../open-browser-use-electron/README.md#iab-mcp-for-agents).

## Multi-Tab Workflows

For Chrome, inspect existing tabs before claiming one for the current session:

```js
const tabs = await browser.getUserTabs();
const match = tabs.find(tab => tab.url === "https://example.com/");
if (match) {
  const tab = await browser.claimTab(match.id);
  nodeRepl.write(await tab.observe());
}
```

Claiming changes the tab's task group. In Electron, `getUserTabs()` returns
only the authorized scope's tabs; use `browser.tab(id)` for an existing scoped
tab. Electron does not implement Chrome's `claimTab` operation. SDK connections
reconnect on a subsequent request after a socket closes; retry the failed
operation explicitly, since it may have reached the browser before disconnect.

For multiple pages, create tabs first, then run navigation and extraction in
parallel. This avoids backend session races while still parallelizing the slow
page work.

```js
const targets = [
  ["repo", "https://github.com/iFurySt/open-codex-computer-use"],
  ["issues", "https://github.com/iFurySt/open-codex-computer-use/issues"],
  ["pulls", "https://github.com/iFurySt/open-codex-computer-use/pulls"],
];

const tabs = [];
for (const [kind] of targets) {
  tabs.push([kind, await browser.newTab()]);
}

await Promise.all(
  targets.map(([_, url], index) =>
    tabs[index][1].goto(url, { waitUntil: "load", timeoutMs: 25000 })
  )
);

const results = await Promise.all(
  tabs.map(async ([kind, tab]) => ({
    kind,
    tabId: tab.id,
    text: await tab.playwright.domSnapshot(),
  }))
);
```

## Low-Level Client API

Use `OpenBrowserUseClient` when you need direct Browser Use JSON-RPC methods or
raw CDP commands.

```js
import { readFile } from "node:fs/promises";
import { OpenBrowserUseClient } from "open-browser-use-sdk";

const { socketPath } = JSON.parse(
  await readFile("/tmp/open-browser-use/active.json", "utf8")
);

const client = new OpenBrowserUseClient({
  socketPath,
  sessionId: "raw-cdp-example",
});

try {
  await client.connect();
  await client.nameSession("Raw CDP example - OBU");

  const tab = await client.createTab();
  await client.attach(tab.id);
  await client.executeCdp(tab.id, "Page.navigate", {
    url: "https://example.com",
  });

  const title = await client.executeCdp(tab.id, "Runtime.evaluate", {
    expression: "document.title",
    returnByValue: true,
  });

  console.log(title.result.value);
} finally {
  await client.finalizeTabs([]);
  client.close();
}
```

The unrestricted escape hatch is `request(method, params)`:

```js
await client.request("executeCdp", {
  target: { tabId: 123 },
  method: "Runtime.evaluate",
  commandParams: {
    expression: "document.body.innerText",
    returnByValue: true,
  },
});
```

## File chooser

On Chrome or an explicitly authorized Electron scope, register the chooser
before opening it:

```js
const ready = await tab.prepareFileChooser({timeoutMs: 30000});
const choosing = ready.wait();
const click = tab.clickAt(x, y);
void click.catch(() => {});
const chooser = await choosing;
console.log(chooser.isMultiple());
await chooser.setFiles("/absolute/path/to/file.txt");
await click;
```

`prepareFileChooser` returns after the extension enables interception. `setFiles`
accepts an absolute path or an array of absolute paths and permits one decision
per chooser. Frame navigation or debugger detachment invalidates outstanding
chooser handles. An error after issuing a decision can leave the outcome
unknown; inspect the page before another action. Cross-process iframe sessions
already attached at preparation are intercepted. If the frame tree changes
while waiting, the wait fails; prepare a new one after observing the page.
Electron hosts must authorize the exact files and grant `files.upload` and
`page.control` first; see the Electron integration guide.

## Waiting for a download

On Chrome or an explicitly authorized Electron scope, register the listener
before triggering the page action:

```js
const ready = await tab.prepareDownload({timeoutMs: 30000});
await tab.playwright.getByRole("link", {name: "Download", exact: true}).click();
const download = await ready.wait();
const path = await download.path(30000); // null if the download failed or was cancelled
```

`prepareDownload` returns after the extension confirms registration. The
result is the next Chrome download started after registration; the extension's
download event currently has no reliable tab association, so another tab's
concurrent download may satisfy the wait. Verify the download identity before
using its path. Electron matches the originating tab and requires the host to
configure a directory and grant `files.download` with `page.control`.

## Notifications

The JS SDK can subscribe to JSON-RPC notifications from the native socket. This
is useful for downloads and CDP events.

```js
const unsubscribe = client.onNotification((event) => {
  if (event.method === "onDownloadChange") {
    console.log("download", event.params);
  }
  if (event.method === "onCDPEvent") {
    console.log("cdp", event.params);
  }
});

// Later:
unsubscribe();
```

## Common Methods

- Browser/session: `getInfo`, `nameSession`, `turnEnded`
- Tabs: `createTab`, `getTabs`, `getUserTabs`, `claimUserTab`, `finalizeTabs`
- CDP: `attach`, `detach`, `executeCdp`, `request`
- Input: `moveMouse`
- File chooser: `waitForFileChooser`, `setFileChooserFiles`
- Downloads: `waitForDownload`, `downloadPath`. Chrome's download wait returns
  the next download started after the wait is registered. Chrome download events
  currently lack a reliable tab association here, so a concurrent download from
  another tab can satisfy the wait; verify the result before using its path.
  The download handle exposes `url`, when the browser supplies it; URLs may
  contain credentials or signed query parameters, so handle them as page data.
  Only one Chrome download-start wait can be active at a time; a second wait
  fails immediately. Ending its session, closing its tab, or detaching its
  debugger cancels the pending wait.
  The low-level wait has no registration acknowledgement; use
  `tab.prepareDownload()` when the page action follows immediately.
- Clipboard: `readClipboardText`, `writeClipboardText`, `readClipboard`,
  `writeClipboard`

## Cleanup

Always finish browser work by finalizing tabs and closing the socket:

```js
try {
  // Browser work here.
} finally {
  await browser.client.finalizeTabs([]);
  browser.close();
}
```

Use `finalizeTabs([])` unless the user explicitly needs a tab left open. To keep
a tab, pass a keep item such as:

```js
await browser.client.finalizeTabs([{ tabId: tab.id, status: "handoff" }]);
```

## Notes

- The browser is the user's real Chrome profile. Do not inspect unrelated data.
- The SDK does not include Codex-specific site policy or approval prompts; add
  policy in your own runtime if needed.
- If connection fails, run `open-browser-use ping` and `open-browser-use info`.
- If there is no active socket, open Chrome with the extension enabled or rerun
  setup according to the Open Browser Use installation guide.
