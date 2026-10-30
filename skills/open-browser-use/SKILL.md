---
name: open-browser-use
description: Platform-neutral guidance for using Open Browser Use, the open-source Chrome automation stack for AI agents. Use when an agent needs to install, verify, troubleshoot, or operate Open Browser Use through its browser extension, native CLI, JavaScript SDK, Python SDK, Go SDK, or Browser Use style JSON-RPC methods; use for tasks involving real Chrome tabs, user tab claiming, CDP commands, downloads, file choosers, clipboard helpers, or session cleanup.
---

# Open Browser Use

## Overview

Open Browser Use connects an MV3 Chrome extension, a local native messaging host, a CLI, SDKs, and an optional stdio MCP server so agents can automate a real Chrome profile. It is not Codex.app-specific; adapt the commands, MCP config, and SDK examples to the agent runtime you are operating in.

## Core Workflow

1. For this fork, use the source-built persistent JavaScript MCP when available. Its `js` tool retains bindings across calls and provides `agent.browsers`, `nodeRepl.write`, and `nodeRepl.emitImage`. For setup, read [references/installation.md](references/installation.md); registry packages and store releases are upstream and can have different capabilities.
2. Pick the intended browser/profile from `await agent.browsers.list()` or the connected CLI profiles. See "Browser and profile handling" below before issuing browser commands. Select a listed browser ID when discovery is ambiguous or incomplete.
3. Choose a unique browser session id for the current agent task before opening or claiming tabs. Prefer the surrounding runtime's conversation/session id when available; otherwise create a short unique id such as `obu-<task-slug>-<timestamp>`. Reuse that same id for every Open Browser Use command in this task.
4. Name the current browser task group before opening or claiming tabs. Use a short task label followed by ` - OBU`; if no better task label is available, use `Task - OBU`.
5. Before opening a new tab, run `user-tabs` / `user_tabs` and check whether the task continues from an existing tab, including tabs in `✅ Open Browser Use` or an earlier `handoff` task group. If the URL/title/group clearly matches the current task, claim that tab and continue from it instead of opening a duplicate. When verifying or accepting a local change, this also covers a dev server tab the user already has open (for example `localhost`, `127.0.0.1`, or a `*.local` / `*.test` host): claim and reuse it rather than opening a second copy of the same app.
6. For multi-step work, use the persistent `js` tool: select a browser with `await agent.browsers.get(id)`, then reuse `browser` and its tab handles. Inspect current state before selecting or interacting; use fresh observations after changes.
7. Use the CLI, action-plan MCP, or language SDKs when they fit the runtime or task. The newer Playwright-style, DOM CUA and visual interfaces are in this fork's JavaScript source build. Read [references/sdk-and-protocol.md](references/sdk-and-protocol.md) for other transports.
8. Before ending browser work, release or keep the task's session tabs using `browser.tabs.finalize({keep:[...]})` or the matching CLI/SDK finalization operation. The keep statuses are `handoff` and `deliverable`; omitting keep closes the session's owned tabs.
9. If communication fails after setup, read [references/troubleshooting.md](references/troubleshooting.md).

## Operating Rules

When the source build provides the persistent `js` tool, use
`nodeRepl.write(await agent.browsers.list())` to discover browsers, then bind
`const browser = await agent.browsers.get(id)`. Inspect `browser.user.openTabs()`
and claim a relevant tab with `browser.user.claimTab(id)`. The REPL maintains a
unique session and reuses its connections; pass an explicit browser ID when
more than one backend or profile is available. `tab.playwright.domSnapshot()` returns bounded
roles, names, states and readable frame content, indented by accessibility
parent-child relationships. Frames with unknown placement are marked; heed truncation and unavailable
frame markers. It replaces any previous observation. Call `await tab.observe()` after page changes;
use its snapshot id and index with `tab.click` or `tab.typeText`. Use
`tab.scroll(index, snapshotId, "down", pages)` to send a wheel at an observed
target; set `includeText:true` to expose named groups and regions. One page is
80% of the viewport dimension, the wheel can scroll an ancestor, and an
uncertain outcome requires a fresh observation. Use `tab.fill` to replace a
text field's contents. For semantic selection, use
`tab.playwright.getByRole(role, {name, exact:true}).click()`, `.dblclick()`, `.hover()`, `.innerText()`, `.textContent()`, `.getAttribute(name)`, `.isEnabled()`, `.isVisible()`, `.isChecked()`, `.inputValue()`, `.boundingBox()` or `.fill(text)`;
use `.waitFor({state:"visible"})` or `.waitFor({state:"hidden"})` for semantic visibility changes. CSS locators additionally support `attached` and `detached`.
`tab.playwright.getByLabel(name, {exact:true}).check()` and `.uncheck()` set
binary controls without toggling an already-correct state. `getByRole` accepts boolean `checked`, `disabled`, `pressed`, `selected` and `expanded` filters when the accessibility tree exposes those states. Disabled controls remain observable and can be hovered; actions that modify them require an enabled target. Actions require a
unique match. Text matchers and text filters also accept regular expressions. Use `.last()` for the final match; `await locator.all()` returns positional locators that resolve again when used, and `await locator.allTextContents()` reads raw text from current matches. Chain locators, such as `dialog.getByRole("button", {name:"Save"})`, to select descendants within a container, including nested frames. Accessible lists, list items, groups, tables and rows also support scoped queries. Use `.filter({hasText:"Apples"})` or `.filter({hasNotText:"Sold out"})` to select by accessible descendant text. For a native select use `.selectOption(value)` or
`.selectOption({label})`; its DOM-dispatched events have `isTrusted === false`.
Use `tab.playwright.frameLocator('iframe#payment').getByLabel(...)` to restrict
semantic queries to a direct child frame; chain `.frameLocator(...)` for nested
frames. Each selector must match the frame element, and ambiguous frames fail.
Frame selector matching runs in an isolated world; page scripts can still change
frame elements between observations.
`fill` handles native number and date/time inputs; date/time events are
DOM-dispatched with `isTrusted === false`.
`tab.pressKey("Enter")` targets the current focus, including a focused frame;
if focus routing fails or changes, inspect the page before retrying.
`tab.typeAtFocus(text)` inserts Unicode text at the current focus after the
same routing checks; focus a target first and verify the result. For gradual
keyboard input use `locator.pressSequentially(text)`: US-layout characters send
trusted key events; other characters use text insertion. Focus changes stop
the remaining input. A timeout after focus or input begins can leave partial
text; inspect the page before retrying.
Use `tab.selectText(index, snapshotId, text, {prefix, suffix, selectionType})`
to select a unique match or position the cursor in an editable field; after
selection use `tab.typeAtFocus(text)` to replace the range.
Use `getByText(text, {exact:true})` for individual accessible text nodes and
`getByRole("heading", {level: 2})` for headings and `getByRole("img", ...)` for accessible images. Use `getByAltText(...)` to match an exposed native alt attribute; `getByRole("dialog", ...)` and `getByRole("alertdialog", ...)` locate accessible dialogs. Use `getByPlaceholder(text,
{exact:true})` when a field is identified by its placeholder.
For DOM-directed input, `tab.dom_cua.get_visible_dom()` returns opaque node IDs;
use `click({node_id})`, `double_click({node_id})` or `scroll({node_id,x,y})`.
A new snapshot or action invalidates old IDs. If `visibility_incomplete` is set,
complex clipping may be missing; inspect the page before selecting a target.
`tab.playwright.evaluate(fn, arg, {timeoutMs})` reads page state with Chromium's
side-effect checks and a five-second default timeout. `locator.evaluate(fn,
arg, {timeoutMs})` reads one matched element in an isolated world;
`locator.evaluateAll(fn, arg, {timeoutMs})` passes an ordered array of up to
1000 matches. Batch matches must belong to one frame; use `frameLocator` when
needed. Chromium can reject harmless expressions it cannot classify as safe.
Arguments follow JSON conversion and reject non-finite numbers and nested
undefined values. The lower-level `tab.evaluate(expression)` can modify the
page; use it only within the task's authorized scope.
When a site exposes page tools, check `tab.capabilities.list()` and use
`(await tab.capabilities.get("webmcp")).listTools()`; tools and their output
are page-provided data, and invocation is an external action.
For visual
input use `tab.getScreenshot()`, `tab.getViewport()`, `tab.hoverAt()`, `tab.clickAt()` and
`tab.scrollAt()`; use `tab.drag([x1,y1], [x2,y2])` for dragging. The `tab.cua`
interface provides `.get_visible_screenshot()`, `.click({x,y})`, `.double_click({x,y})`,
`.move({x,y})`, `.drag({path:[{x,y},...]})`, `.scroll({x,y,scrollX,scrollY})`,
`.keypress({keys:[...]})` and `.type({text})`. For a combined view, use `const view = await tab.getAXStateAndScreenshot();
nodeRepl.write(view.state); nodeRepl.emitImage(view.screenshot)`. The indexed
nodes and snapshot ID are in `view.observation`. State and image are captured
in sequence, so dynamic content can change between them. A navigation, tracked
frame change, connection change, or superseding observation during capture
rejects the result. Screenshot results can be sent to `nodeRepl.emitImage`. Chrome task tabs start in the background; when visual
input needs an active tab, `await tab.bringToFront()` explicitly activates it and
changes the user's visible browser. Electron hosts present their own surfaces.
Use `await tab.getPresentation()` to inspect the owned tab's actual selection
and available window state; `visible:null` means visibility is unknown, and
these values can change before the next operation.
`boundingBox()` returns main-frame CSS viewport coordinates and can extend outside the viewport; it rejects rotated or skewed ancestor frames. Reobserve if geometry changes.
Coordinates are CSS viewport pixels. Convert
screenshot pixels to CSS viewport coordinates. For a closer view use
`tab.getScreenshot({clip:{x,y,width,height}})` with a rectangle inside the CSS
viewport; convert cropped image pixels using the clip dimensions and add its
x/y origin before clicking. `tab.getScreenshot({fullPage:true})` captures the
whole document subject to the SDK size limit; offscreen lazy content may need
loading first. In Electron, `IAB_INPUT_PREPARATION_TIMEOUT` occurs before mouse
input; after `IAB_INPUT_OUTCOME_UNKNOWN` or `IAB_BACKGROUND_SCROLL_TIMEOUT`,
observe before retrying.
Use `locator.press("Enter")` to focus a matched target and send a key, or `tab.pressKey("Enter")` and `tab.pressKey("ControlOrMeta+A")` for already focused
page keyboard actions. Printable ASCII keys use US keyboard mappings; use `tab.typeAtFocus(text)` for arbitrary text at the current focus, or `tab.typeText(index, snapshotId, text)` for an observed target.
Use `tab.back()`, `tab.forward()` and `tab.reload()` for tab history actions.
Back and forward return after command dispatch; reload waits for the load event.
Verify the resulting page before further interaction. If the action fails after
dispatch, inspect before retrying.
After navigation or a history API route change, use
`tab.waitForURL("https://example.com/target")` or a regular expression to wait
for the main document URL and load state. Sampling can miss transient URLs.
For a user-authorized action that opens a tab, use `tab.playwright.expectPopup(() => locator.click())` and inspect the returned tab. It matches new session tabs by opener; a popup closed too quickly or lacking opener metadata may time out. After an uncertain outcome, inspect the session before retrying.
For an action that should navigate, use `tab.playwright.expectNavigation(() =>
locator.click(), {url: "https://example.com/target"})` to arm the main-frame
navigation listener before the action.
For subsequent observations, `tab.observe({diff:true})` reports text changes;
always use the newly returned `nodes` and `snapshotId` for actions.
Use `await tab.dev.watch()` before an action, then `await tab.dev.logs({levels:["error"]})` to inspect captured console errors, uncaught exceptions and browser resource-load errors.
Tabs expose `tab.clipboard.readText()`, `writeText(text)`, `read()` and `write(items)` when permitted. Electron 44 requires explicit `clipboard.read` or `clipboard.write` grants with `page.control`.
Use `tab.paste(index, text, {snapshotId, format})` for an observed target or
`tab.paste(null, text, {format})` at the current focus. Formats are `text`,
`md` and `html`; Markdown stays plain text. For HTML, provide `plainText` when
the destination may need a text fallback. Paste replaces the system clipboard
and does not restore it. Other processes can change the clipboard before the
shortcut; inspect the page after an error before retrying. Electron requires
`clipboard.write` and `page.control` for paste.
When current field values are needed, request `includeValues:true`; native
password values are redacted and truncated values are flagged.
Use `tab.observe({includeFrames:true})` to include iframe controls. Chrome and
Electron support scoped cross-process frames.
Check `frameCoverage` and `unavailableFrames`, and use a fresh screenshot for
visual targets that are absent from the observed tree.
Return text with `nodeRepl.write` and images with `nodeRepl.emitImage`.
This MCP tool runs local JavaScript with the agent's process permissions; use
it only with trusted clients. Electron hosts supply the scope and launch
`obu-iab-repl-mcp` through `launchClient`; do not scan for an IAB socket.
Use `getBrowserState()` for available browsers and tabs in connected sessions.
The Electron inventory is limited to its host-authorized scope. A host may
explicitly enable Chrome discovery; select the intended browser ID when both
backends are available.
For Chrome, `discoverBrowsers()` lists live sockets and their metadata. With
multiple connections, select the socket corresponding to the chosen profile
from `obu profiles --connected --json`; `connectBrowser()` without a socket
only proceeds when exactly one browser is connected.

- Treat the browser as the user's real Chrome profile. Do not inspect cookies, passwords, session stores, or unrelated browser data.
- Follow the user’s requested scope and the host’s permission controls for browser actions. An explicit request can authorize the corresponding interaction; ask when its scope is unclear or a required human confirmation is unavailable.
- Use `agent.browsers` and `nodeRepl` only within this fork’s persistent `js` tool. Other runtimes can use the CLI or SDKs.
- Do not guess tab ids. List tabs first, then use ids returned by `tabs`, `user-tabs`, `open-tab`, or SDK calls.
- Prefer `claim-tab` / `claimUserTab` for existing user tabs. Claiming should be based on the current `user-tabs` result and visible evidence such as URL, title, recency, or group.
- For follow-up tasks, inspect `user-tabs` before opening a tab and reuse a matching tab from `✅ Open Browser Use` or a previous handoff group. A deliverable tab can be claimed back into the new task session, worked on, and finalized as `deliverable` again when it remains the user-facing result. This keeps repeated work on the same page converged to one live tab.
- Do not claim unrelated deliverable tabs just because they are in `✅ Open Browser Use`. If several tabs plausibly match, prefer the most recent exact URL/title match; ask the user when the match is ambiguous.
- When verifying or accepting a local code change, prefer reusing a dev server tab the user already has open (matching host, port, and app, such as `localhost:<port>`) over opening a new one. Match on host, port, and path or title; if several plausibly match or the match is ambiguous, ask the user instead of opening a duplicate.
- Use `--socket` only when the user or runtime provides an explicit socket. Otherwise let the CLI and SDKs discover the active socket registry.
- Do not rely on the CLI fallback session `obu-cli` for agent tasks. Always pass a task-unique `--session-id` to CLI and MCP commands, or set `sessionId` / `session_id` / `SessionID` in SDK clients. The fallback exists for quick manual use and can reuse stale task groups across unrelated agent sessions.
- Direct CLI subcommands and `open-browser-use run` can share the same browser session only when they use the same explicit `--session-id`. Finalize that same session before ending browser work.
- Use `call --method <method> --params '<json>'` only when no safer convenience command or SDK wrapper exists.

## Browser and profile handling

Some users run several supported browsers (for example Google Chrome, Google
Chrome Beta, or BitBrowser) and may also have multiple profiles inside them.
Installed targets remain visible even when their browser/profile is closed, so
use the `CONNECTED` state—not the number of installed targets—to decide whether
the agent needs to ask which target this task should operate on.

1. Before any browser command, list installed browser/profile targets:

   ```sh
   open-browser-use profiles --connected
   ```

   Columns include `BROWSER`, `DIRECTORY` (stable profile id like `Default`,
   `Profile 1`), `DISPLAY NAME` (what the user sees in the browser avatar
   menu), `VERSION`, and `CONNECTED` (whether that target's host is currently
   reachable). JSON output is available via `--json` and includes a stable
   `target` such as `chrome:Default`, `chrome-beta:Default`, or
   `bitbrowser:<instance>:Default`.

2. If the user already specified a browser/profile, use that target. If it is
   not connected, ask the user to open it before retrying. Do not silently fall
   back to another connected target.

3. If the user did not specify a target, count the connected targets. If exactly
   one target is connected, proceed without asking, even when other installed
   targets are listed as disconnected. Pass that connected target's selectors
   to subsequent commands so the task remains pinned to it.

4. If multiple targets are connected, ask which one to use before the first
   browser command. List each connected target's browser name, directory name,
   and display name so the user can recognize it.

5. If no target is connected, ask the user to open one before running browser
   commands. When multiple installed targets are listed, ask which target they
   want to open; when exactly one is listed, name it directly. If none are
   installed, follow the installation guidance.

6. After the target has been selected, pass `--browser <selector>` and, when
   needed, `--profile <selector>` to every CLI / MCP command for the rest of the task.
   Browser selectors accept ids such as `chrome`, `chrome-beta`, `bitbrowser`,
   browser display names, or a BitBrowser instance id. Profile selectors accept
   either the directory name (`Default`, `Profile 1`) or the display name
   (`Eva`, `cookiy.com`), case-insensitive. Do not switch browser/profile
   mid-task.

7. If `--browser` / `--profile` does not match any running host, the CLI prints
   which targets are currently connected. Ask the user to open the chosen
   browser/profile, then retry; do not silently fall back to a different target.

8. For MCP, lock the browser/profile at server start:

   ```toml
   [mcp_servers.open_browser_use]
   command = "obu"
   args = ["mcp", "--session-id", "obu-<task-id>", "--browser", "<browser>", "--profile", "<profile>"]
   ```

   Do not pass browser/profile as per-tool-call arguments — the MCP server
   applies the start-time selectors to every call.

9. Do not remember the user's browser/profile choice across unrelated tasks. A
   future task may belong to a different target; ask again rather than assuming.

## Common CLI Actions

```sh
export OBU_SESSION_ID="obu-docs-scan-$(date +%Y%m%d%H%M%S)"
open-browser-use ping --session-id "$OBU_SESSION_ID"
open-browser-use info --session-id "$OBU_SESSION_ID"
open-browser-use name-session --session-id "$OBU_SESSION_ID" --name "Task - OBU"
open-browser-use tabs --session-id "$OBU_SESSION_ID"
open-browser-use user-tabs --session-id "$OBU_SESSION_ID"
open-browser-use history --session-id "$OBU_SESSION_ID" --query "example" --limit 20
open-browser-use open-tab --session-id "$OBU_SESSION_ID" --url https://example.com
open-browser-use navigate --session-id "$OBU_SESSION_ID" --tab-id <tab-id> --url https://example.com
open-browser-use cdp --session-id "$OBU_SESSION_ID" --tab-id <tab-id> --method Runtime.evaluate --params '{"expression":"document.title"}'
open-browser-use finalize-tabs --session-id "$OBU_SESSION_ID" --keep '[]'
```

For CLI-level orchestration without writing SDK code, use a line-oriented
action plan:

```sh
open-browser-use run --session-id "$OBU_SESSION_ID" -c '
name-session "Docs scan - OBU"
open-tab https://docs.browser-use.com
wait-load domcontentloaded
page-info
finalize-tabs []
'
```

Each action line shares one session/turn. `open-tab` and `claim-tab` set the
default tab for later tab-scoped actions such as `wait-load`, `page-info`,
`navigate`, `cdp`, `move-mouse`, and `wait-file-chooser`.

Use `obu` as the short alias when available.

## MCP Usage

For runtimes that can launch local MCP servers over stdio, use:

```toml
[mcp_servers.open_browser_use]
command = "obu"
args = ["mcp", "--session-id", "obu-<task-or-conversation-id>"]
```

Use a fresh `--session-id` value per agent task or conversation. If the runtime
has a stable conversation/session id, derive the MCP `--session-id` from it.

The MCP server exposes tools including `user_tabs`, `open_tab`, `claim_tab`,
`navigate`, `wait_load`, `page_info`, `cdp`, `history`, `run_action_plan`,
`finalize_tabs`, and unrestricted `call`.

Use `run_action_plan` when the runtime wants to execute the same compact action
plan format available through `open-browser-use run` without shelling out for
each individual browser operation.

## Tab Lifecycle

- Session tabs are tabs Open Browser Use has created or claimed for the current agent workflow.
- Use one unique session id per agent task or conversation. Do not share the fallback `obu-cli` session across unrelated tasks.
- Task session groups should be named from the task, using the pattern `<short task> - OBU`. Use `Task - OBU` as the fallback name.
- At the start of a related follow-up task, list all user tabs and check `tabGroup`, `title`, and `url` before creating anything new. Claim an existing matching deliverable or handoff tab — or a local dev server page the user already has open — into the current session; only open a new tab when no suitable tab exists.
- Keep no tabs by default: `open-browser-use finalize-tabs --session-id "$OBU_SESSION_ID" --keep '[]'`.
- Keep a tab only when the user needs that live page after the turn. Omit research, source, search, intermediate, duplicate, blank, error, and login/navigation tabs after extracting what you need.
- Keep a tab with `status: "deliverable"` when the tab itself is the user-facing output or requested open page, such as a created or edited document, dashboard, checkout/cart, submitted form result, or a page the user explicitly asked to inspect directly.
- Keep a tab with `status: "handoff"` only when the task is still in progress and the user or a later turn should continue from the current task group, such as a page waiting for user input, login, approval, payment, CAPTCHA, or an unfinished workflow.
- Handoff tabs stay in the task session group. Deliverable tabs move to the shared `✅ Open Browser Use` tab group.
- Run finalization as the last Open Browser Use browser action for the turn. Do not call Open Browser Use browser tools after finalizing; if more browser work is needed, do it first and finalize once with the final tab disposition.

## File Choosers, Downloads, And Clipboard

- Use `await tab.prepareFileChooser()` to confirm interception before opening the chooser. Start `ready.wait()` and the page click concurrently, then set absolute local paths on the chooser and await the click. Inspect the page if the decision outcome is uncertain. Electron hosts must explicitly authorize the files and grant `files.upload` and `page.control`.
- `const start = await tab.prepareDownloadStart()` arms a tab-scoped CDP download-start observation; after the action, `await start.wait()` returns `guid`, `frameId`, `url`, and `suggestedFilename`. Existing attached cross-process frames are included; newly created frames can miss events. The GUID is separate from the file handle returned by `prepareDownload()`.
- `const ready = await tab.prepareDownload()` confirms registration before triggering a download; the result of `await ready.wait()` exposes `url` and `path()`. `download.attribution` is `"tab"` when the backend associates the download with the tab, `"browser"` for the next browser-wide download, or `"unknown"` when unspecified. Chrome allows one active download-start wait and observes the next download across tabs, so verify its identity. Electron matches the originating tab and requires the host to authorize a directory and grant `files.download` with `page.control`.
- Clipboard helpers operate through the current controlled tab and should be treated as sensitive user actions.

## References

- [references/installation.md](references/installation.md): one-time CLI and browser extension setup, including cases where user cooperation is required.
- [references/sdk-and-protocol.md](references/sdk-and-protocol.md): JavaScript, Python, Go, socket, and JSON-RPC usage details.
- [references/troubleshooting.md](references/troubleshooting.md): connection failures, stale sockets, extension/native host checks, and permission issues.
