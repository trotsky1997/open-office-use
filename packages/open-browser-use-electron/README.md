# Open Browser Use Electron

Embed a multi-tab browser in an Electron app. A named profile supplies shared
login storage; each task scope owns independent tabs. The host controls where
tabs are displayed and which tool processes can operate them.

This package is available in this workspace; npm publication is a separate step.
Electron is a peer dependency supplied by the host. Node clients import the
`/client` entry point, which does not initialize Electron.

## Run the reference app

From the repository root:

```sh
pnpm install
pnpm example:iab
pnpm smoke:iab
```

The [Electron example](../../examples/electron-iab/README.md) visibly demonstrates
Electron main + CLI + private channel through five manual or automated actions,
retaining all three tabs for inspection afterward.
Node/CLI × private/socket reference integrations remain in code and smoke tests.

Requirements: Node 22+, pnpm 8.15.9, Go 1.25.10+ for the example CLI, and a C++
toolchain plus Python for the Node-API addon. The example pins Electron 44.7.0.
The declared Electron range is 30–44; the local smoke matrix currently covers
macOS arm64 with Electron 44.7.0 and Node 24.19.0.

## Main-process integration

```ts
import { app, BrowserWindow } from 'electron';
import { createIabRuntime } from 'open-browser-use-electron';

app.whenReady().then(async () => {
  const iab = createIabRuntime({ appId: 'my-app' });
  iab.profiles.open({ id: 'work', persistent: true });
  const task = iab.scopes.open({ id: 'task-a', profileId: 'work' });
  const first = await task.tabs.create({ url: 'https://example.com' });
  const second = await task.tabs.create({ url: 'https://example.org' });

  const window = new BrowserWindow({ width: 1200, height: 800 });
  const surface = iab.surfaces.register({
    id: 'browser-panel', window, owner: window.webContents,
  });
  surface.setBounds({ x: 400, y: 80, width: 780, height: 680 });
  surface.present(first.id);

  // The target remains explicit even when another tab is displayed.
  await task.call('executeCdp', {
    target: { tabId: second.id }, method: 'Runtime.evaluate',
    commandParams: { expression: 'document.title', returnByValue: true },
  });
  // Hidden/removed surfaces do not close pages.
  surface.hide();
  // During host shutdown: await iab.dispose();
});
```

Use a unique appId per host integration. Different scopes can use the same
profile; different accounts should use different profiles. Scope ownership
isolates API access, while shared profile cookies and storage remain shared.
Each scope can hold 32 tabs; one runtime can hold 128.

Tab snapshots from `scope.tabs.list()`, `getTabs`, and `onTabUpdated` include
`loading` (Electron's loading lifecycle), optional `pendingUrl` during main-frame
navigation/redirect, and optional `loadError: { code, description, url }`.
A new main-frame navigation clears the previous error; iframe failures and
aborted/replaced navigations do not mark the whole tab as failed. Hosts can
render loading immediately from these snapshots without awaiting a page command.
The example separately normalizes user-entered addresses; the runtime still
requires an explicit permitted URL.

## Opt-in WebMCP page tools

The host can opt a scope into page-provided WebMCP tools when creating it:

```ts
const task = iab.scopes.open({ id: 'web-task', profileId: 'work', webmcp: true });
const tab = await task.tabs.create({ url: 'https://example.com' });
// Grant tabs.read and page.control to a trusted agent connection.
```

The runtime installs the page bridge before navigation for tabs created through
`scope.tabs.create` or the SDK. A `page.control` grant can discover and invoke
page-provided tools through `tab.capabilities.get('webmcp')`; tool results are
untrusted page data. The scope option defaults to false and cannot be changed
after the scope is created. A tool invocation may have taken effect if its
result times out or the grant is revoked, so inspect the page before retrying.

For the standard Electron adapter, opted-in tabs and popups install a sandboxed
preload that initializes the page bridge before page scripts run. Custom
`IabRuntime` adapters must supply `webMcpPreload` and honor the `webmcp`
argument to `createView` to provide the same popup behavior. The preload uses
Electron's experimental `contextBridge.executeInMainWorld`; Electron 44 is
covered by real-page checks on macOS and Linux ARM64. Run the focused check with
`packages/open-browser-use-electron/node_modules/.bin/electron examples/electron-iab/webmcp-smoke.mjs`
from the repository root. Set `OBU_IAB_PACKAGE_DIR` to an unpacked package to
check its distribution files. The bridge reports tools from the main document;
child-frame tools are not included. Tool errors are reduced to scoped error
codes across the socket.

## Explicit file upload authorization

Uploads are disabled by default. The host can authorize specific existing
regular files for a scope and grant `files.upload` together with `page.control`
to a trusted client:

```ts
await task.files.authorize(['/absolute/path/to/report.pdf']);
const worker = await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/node',
  args: ['/absolute/path/to/worker.mjs'],
  transport: 'private',
  ttlMs: 60_000,
  operations: ['tabs.read', 'page.control', 'files.upload'],
});
```

The list replaces the scope's previous list; `await task.files.authorize([])`
revokes it. Paths are resolved to regular files both when authorized and before
each selection. Authorization is scope-wide and applies to any client in that
scope with both grants. The host should authorize only files and clients chosen
for the task and keep approved files stable until the decision completes; path
authorization does not freeze file contents. The worker uses `tab.prepareFileChooser()` and the SDK chooser
handle. File decisions are one-use, and navigation or debugger detachment
invalidates them. Revoking the list or grant prevents a not-yet-issued decision.
An already issued decision can have an unknown outcome; inspect the page.

## Explicit download authorization

Downloads are disabled by default. The host can authorize an existing, private
scope directory and maximum download size, then grant `files.download` with
`page.control`:

```ts
await task.downloads.configure({directory: '/absolute/private/downloads', maxBytes: 10_000_000});
const worker = await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/node',
  args: ['/absolute/path/to/worker.mjs'],
  transport: 'private',
  ttlMs: 60_000,
  operations: ['tabs.read', 'page.control', 'files.download'],
});
```

`await task.downloads.configure(null)` disables downloads and cancels active
ones. Each waiting request accepts a download only from its own tab; unarmed or
unauthorized downloads are denied. Files are written under randomized names in
the authorized directory. Use `tab.prepareDownload()`, trigger the page action,
then use `(await ready.wait()).path()` to wait for completion. Completed
handles are retained for five minutes; the files remain under host management.
The host must control the directory and keep it stable. The size limit cancels
when the reported total or received bytes exceed it; allowed values range from
1 to 1,000,000,000 bytes. It is not an instantaneous filesystem quota, and
partial files can remain after cancellation. Revoking a
grant cancels downloads still in progress.

## Explicit clipboard grants

Electron 44 hosts can grant system clipboard access separately for reading and
writing. These permissions are excluded from default grants:

```ts
const worker = await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/node',
  args: ['/absolute/path/to/worker.mjs'],
  transport: 'private',
  ttlMs: 60_000,
  operations: ['tabs.read', 'page.control', 'clipboard.read', 'clipboard.write'],
});
```

Clients use `tab.clipboard.readText()`, `writeText()`, `read()` and `write()`.
Each operation requires an owned tab, `page.control` and its corresponding
clipboard grant. The clipboard belongs to the host system and is shared across
scopes and applications. A revoked read cannot return its result; a write
already issued to Electron can still finish, so inspect before retrying.
`getInfo` exposes `clipboardRead` and `clipboardWrite` for the grant. Electron
versions without the modern `ClipboardItem` interface report clipboard as
unavailable.

Structured items support standard MIME types and `web` custom MIME types;
Electron-specific native formats are omitted on read and rejected on write.
Presentation style is `unspecified`. The per-call limit is 3 MiB of raw data
and 4 MiB of encoded JSON, with at most 16 items and 64 formats per item.

## Private tool process

Host main:

```ts
const worker = await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/node',
  args: ['/absolute/path/to/worker.mjs'],
  transport: 'private', // default; no listener is opened
  ttlMs: 60_000,
  operations: ['tabs.read', 'tabs.create', 'page.control'],
});
worker.child.stdout?.on('data', chunk => console.log(String(chunk)));
// worker.revoke() immediately closes its authorized connections.
```

Worker:

```ts
import { connectPrivateIab } from 'open-browser-use-electron/client';

const client = await connectPrivateIab(); // inherited duplex FD 3
try {
  const browser = client.browser(); // existing Browser Use SDK helpers
  const tab = await browser.newTab({ url: 'https://example.com' });
  console.log(await tab.domSnapshot());
} finally {
  client.close();
}
```

The client receives a small allowlist of actionable IAB failure messages,
including `IAB_INPUT_PREPARATION_TIMEOUT`, `IAB_INPUT_OUTCOME_UNKNOWN`,
`IAB_BACKGROUND_SCROLL_TIMEOUT`, `IAB_SCREENSHOT_TIMEOUT`, `IAB_SCREENSHOT_TOO_LARGE` and
`IAB_OPERATION_DENIED`. Other backend errors remain generic to avoid exposing
host details. A background scroll timeout or `IAB_INPUT_OUTCOME_UNKNOWN` can
leave the input outcome unknown; inspect the page before retrying. A mouse
preparation timeout occurs before input is sent.

FD 3 carries a private bootstrap followed by framed JSON-RPC. The bootstrap
fixes instance, scope, grant and credential. Credentials are not passed in
argv, environment variables or discovery files. The tool must never log its
bootstrap. The host is responsible for choosing trustworthy commands/scripts;
possession or deliberate forwarding of the private channel delegates its grant.

## Authenticated socket

Change the host launch option to `transport: 'socket'`. The worker still calls
`connectPrivateIab()`: it receives private bootstrap, verifies the socket server
identity, then connects and authenticates. Standalone socket clients can use
`connectSocketIab(bootstrap)` only when a trusted host privately supplied that
bootstrap.

Socket mode requires the native adapter and currently supports macOS/Linux.
macOS uses the kernel audit token; Linux uses SO_PEERCRED. Both bind PID, UID
and process start time to a host-registered process, then require a 256-bit
expiring lease. This first version uses managed process registration, rather
than a signing-identifier allowlist. Unsupported platforms fail closed with
AUTH_UNAVAILABLE. Windows private-descriptor behavior has not been smoke tested.

The socket is created in a new 0700 directory with 0600 permissions, outside
Chrome discovery. Peer authorization happens before frame parsing. Same-UID
processes may establish an OS connection but cannot use browser methods without
the registered identity and grant. Clients also check server identity before
sending a secret. Secret comparisons use constant-time digests.

Grants require an explicit ttlMs up to 24 hours, default to one simultaneous
connection and allow at most 16. Expiry, revoke, scope disposal and managed
process exit terminate access. Each request/event checks scope and operation
permissions; queued CDP input rechecks authorization before execution. Previously
completed side effects cannot be rolled back by revocation.

## IAB CLI

The host launches the built CLI exactly like a worker:

```ts
await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/obu',
  args: ['iab', 'tabs'],
  transport: 'socket', // or 'private'
  ttlMs: 30_000,
});
```

Commands: `info`, `ping`, `tabs`, `open-tab [url]`, `navigate <tab-id> <url>`,
`close-tab <tab-id>`, `cdp <tab-id> <method> [params-json]`,
`call <method> [params-json]`, and `turn-ended`.
`--channel-fd` selects the inherited bootstrap descriptor; `--turn-id` is
bookkeeping, not authorization. Without host bootstrap, commands fail rather
than scan or fall back to Chrome. Go IAB transport is tested on macOS and
cross-compiled for Linux/Windows; Windows IAB socket mode remains disabled.

## IAB MCP for agents

For a persistent JavaScript session, start the package's `obu-iab-repl-mcp`
executable through `iab.launchClient`, with `stdin: 'pipe'` and either private
or socket transport. Give the returned stdin/stdout pipes to the MCP client, as
in the example below. Its `js` tool exposes `connectBrowser()`, which returns a
browser bound to the host's authorized scope; see the
[JavaScript SDK REPL guide](../open-browser-use-js/README.md#persistent-javascript-mcp).
This tool executes local Node code with the process user's permissions and is
for trusted agents. Starting it without host bootstrap fails closed.

To route both the authorized Electron scope and Chrome extension connections
from the same REPL, the host can explicitly add
`args: ['--allow-extension-discovery']` to `launchClient`. Set `OBU_SOCKET_DIR`
in its `env` if the extension host uses a custom socket directory. Without the
flag, the REPL only exposes its host-selected scope. With the flag,
`getBrowserState()` lists both kinds; choose one with
`connectBrowser({browserId: entry.id})`. If any Chrome socket is present,
`connectBrowser()` requires an explicit browser ID. The Electron grant and the
Chrome session have separate lifecycles and permissions.

`obu iab mcp` exposes this IAB task as an MCP stdio server. It is separate from
`obu mcp`, which controls the Chrome extension route. Start it from Electron
main using the same managed authorization as other IAB clients:

```ts
const { child, revoke } = await iab.launchClient({
  scopeId: task.id,
  command: '/absolute/path/to/obu',
  args: ['iab', 'mcp'],
  transport: 'private', // 'socket' uses the same MCP interface
  stdin: 'pipe',       // opt-in; ordinary launchClient defaults to 'ignore'
  ttlMs: 10 * 60_000,
  operations: ['tabs.read', 'tabs.create', 'page.control'],
});
// Give child.stdin (requests) and child.stdout (responses) to the host's MCP
// client transport. Consume child.stderr separately for process diagnostics.
// Finish with child.stdin.end(); revoke() immediately removes browser access.
```

The agent's MCP client must use these already-launched pipes. A static config
that independently spawns `obu iab mcp` has no host bootstrap and fails closed.
FD 3 carries only browser bootstrap/private RPC; stdin/stdout carry only MCP.
Never forward FD 3 or bootstrap credentials to model-visible tool arguments.
See [`integrations.mjs`](../../examples/electron-iab/integrations.mjs) and the
dependency-free [reference MCP client](../../examples/electron-iab/mcp.mjs) for
an end-to-end example without additional packages.

| Tool | Arguments | Result |
| --- | --- | --- |
| `ping`, `info`, `tabs` | `{}` | Connection, capabilities, or current task's tabs |
| `open_tab` | `{ url? }` | New tab snapshot; omitted URL opens about:blank |
| `close_tab` | `{ tab_id }` | Close just this tab |
| `navigate` | `{ tab_id, url }` | Start page navigation |
| `page_info` | `{ tab_id }` | Title, URL, readyState and up to 20000 body-text characters |
| `snapshot` | `{ tab_id }` | CDP accessibility tree, without stable locator references |
| `screenshot` | `{ tab_id }` | PNG as MCP image content |
| `click` | `{ tab_id, x, y }` | Trusted left click at CSS viewport coordinates |
| `type_text` | `{ tab_id, text }` | Insert text into the focused editable element |
| `cdp` | `{ tab_id, method, params? }` | Host-allowlisted page CDP command |

All page tools require explicit numeric `tab_id`; no implicit active-tab target,
scope override, Chrome discovery, history, file or browser-global tools are
exposed. The host enforces the grant on every browser request, including custom
CDP. Tools may still be listed under a restricted grant; unauthorized operations
return MCP tool errors. Page content remains untrusted input for the agent.
`open_tab` creates a page but does not choose a host surface; the host decides
which tab to present. Input tools trigger the SDK's configured feedback pulse.

The server handles newline-delimited MCP requests sequentially, using the same
protocol-version negotiation as Chrome MCP. Each browser RPC gets a fresh
`--timeout` deadline; idle time does not consume the next request's timeout.
Host lease expiry remains independent and requires relaunch/reauthorization.
Navigation completion should be checked via `page_info` rather than assuming
`navigate` waited for the document. EOF closes the authorized connection and
exits without closing tabs or implicitly calling `turnEnded`/`finalizeTabs`.
Task/runtime disposal remains the host's responsibility.

## Optional operation feedback

Feedback is off by default. The host can enable the Browser Use cursor and a
soft blue glow on all four inward edges independently:

```ts
const iab = createIabRuntime({
  appId: 'my-app',
  visualFeedback: { cursor: true, edgeGlow: true, edgeGlowColor: '#4f8fe8' },
});
// Mark the full operation, including work between individual input commands.
await task.visualFeedback.setActive(first.id, true);
try {
  // Run the authorized CLI/worker actions targeting first.id.
} finally {
  await task.visualFeedback.setActive(first.id, false);
}
// Toggle the edge independently, or recolor active pages without reloading.
await iab.visualFeedback.configure({ edgeGlow: false });
await iab.visualFeedback.configure({ edgeGlow: true, edgeGlowColor: '#8b5cf6' });
await iab.visualFeedback.configure({ cursor: false, edgeGlow: false });
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cursor` | `false` | Show the original Browser Use cursor and click ripple. |
| `edgeGlow` | `false` | Show the inward edge glow, independently of the cursor. |
| `edgeGlowColor` | `'#4f8fe8'` | One base color for all four edges, fading to transparent; accepts `#RGB` or `#RRGGBB`. |

The same options work in `createIabRuntime({ visualFeedback: ... })` and
`iab.visualFeedback.configure(...)`. Updates only replace supplied, defined
fields; setting a color does not enable the effect, and disabling/re-enabling
the edge preserves its color. Color updates apply to active tabs in this runtime
immediately, including pages with strict CSP. Hex values are normalized to
lowercase `#rrggbb`; invalid values reject the whole update without changing
existing options. `iab.visualFeedback.getOptions()` returns a copy of the
current options. Edge color does not change the original cursor or click ripple.

Accepted CDP `Input.*` calls also trigger a 1.2-second activity pulse. Mouse
coordinates come from the real input, with presses snapping to the actual point.
Indexed cross-process iframe input sends frame-local coordinates to Chromium and
uses the translated viewport coordinates for the cursor and activity pulse.
Raw child-session mouse commands can provide `visualPoint` in viewport coordinates.
Activity belongs to the explicit target tab; selecting a surface does not move
that activity to another page. The host must finish explicit activity in a
`finally` block. Navigation resets pointer coordinates; deactivation, disable
and page disposal remove decorations and cancel animation. Reduced-motion
preferences disable travel, click-ring and border animation.

Both effects are implemented and shipped by `open-browser-use-electron`,
including the cursor bitmap, motion and edge rendering. The host only configures
them and marks the target tab's operation lifecycle; no example CSS or cursor
code needs to be copied. The edge glow uses blurred inset shadows of the same
configured color, with a wide transparent falloff and subtle breathing. There is no hard
outline or four overlapping gradient strips to form blocks at the corners.

The original extension's `cursor-chat.png`, 23×24 display size, geometry and
spring renderer are reused. `scripts/generate-cursor.mjs` creates the standalone
artifact from that source; build checks freshness. Run the generator after
changing the Chrome cursor. The only image-carrier adaptation draws the original
PNG pixels on canvas, allowing strict image CSP without weakening site policy.

Rendering uses an isolated guest world and closed shadow DOM, with no host IPC
or credentials. Pointer events pass through. This is a visual hint, not a secure
trust indicator: sites can remove or imitate it. The example's “操作提示” checkbox
enables/disables both effects during manual steps or automatic playback.

## Lifecycle and capability limits

- `tabs.create/list/close`, `scope.call/dispose`, `surfaces.register` with
  `present/setBounds/hide/dispose`, and `runtime.launchClient/dispose` are the
  current main API. `runtime.connections` also provides explicit socket/grant
  methods for advanced trusted-host integrations.
- `attach`, `detach`, `executeCdp`, `markTab`, `turnEnded`, `finalizeTabs` and
  session metadata methods are implemented. Temporary tabs are tracked by turn;
  handoff/deliverable marks preserve them. Preserving a tab does not revoke its
  scope's control; revoke the client grant explicitly when handing control back.
- CDP commands are limited to the owned page and its registered iframe
  sessions. The allowed Target operation attaches iframe sessions only;
  browser-global operations, cookie-jar APIs and WebMCP are unavailable. File
  uploads and downloads require explicit scope authorization and their respective
  grants. Clipboard access requires explicit read or write grants. Browser
  permission requests are denied by default.
- Frame selector matching uses one named isolated world. The host validates the
  target frame against the owned debugger session and rejects universal access
  and additional world options. A stalled context request returns
  `IAB_SELECTOR_CONTEXT_TIMEOUT` and releases the tab queue.
- `tab.getPresentation()` requires `page.control` and reports whether an owned
  tab is selected in a host surface, whether its window reports visible and
  non-minimized, and the window focus state when available. It is a momentary
  status; window occlusion is not measured.
- Navigation accepts http, https and about:blank. The host UI's preload is
  never loaded in remote guest pages; guests enforce sandbox, context isolation,
  disabled Node integration and enabled web security.
- Hidden mouse input prepares compositor hit-test data with an internal screenshot
  before the first event, and again after navigation, layout bounds or presentation
  changes. When the host window is hidden or minimized, or Electron reports the
  main frame as hidden despite a visible window, preparation temporarily disables
  background throttling. The screenshot is discarded. Text and mouse events are verified as
  trusted on the example fixture; IME, cross-origin frames and minimized windows
  require further validation. A Linux ARM64 virtual-display run encountered a
  screenshot timeout when the host window had never been shown. File selection
  passed with the window visible and after showing then hiding it. A stalled preparation or screenshot returns a
  three-second timeout and releases the tab queue. Timeout detaches the debugger
  and invalidates iframe sessions; observe a timed-out input before retrying.
- JavaScript `alert` and `confirm` dialogs can be observed and handled with
  the SDK dialog API. A native dialog may make a hidden host window visible.
  Electron does not implement `window.prompt()`.
- Scroll requires a presented surface. A hidden or minimized host temporarily
  disables background throttling and sends a trusted wheel event, then restores
  the previous setting. This can temporarily change page visibility and affects
  frame scheduling in the host window. An `IAB_BACKGROUND_SCROLL_TIMEOUT`
  leaves the input outcome unknown; the caller should observe before retrying.
- Screenshot responses that exceed the encoded transport size limit fail without
  closing the client connection; use a smaller viewport clip when needed.
- A surface is a native view, not a DOM element. Position it with integer DIP
  bounds and handle resizing in the host. The sample validates IPC sender,
  main frame, local UI URL and allowed actions before using main-only APIs.
- Profiles retain browser data until the host manages their storage. Closing
  a scope destroys pages, not its persistent login profile.

When packaging with ASAR, unpack the native `.node` addon and preserve its
`build/Release/iab_peer.node` path. The install script builds from source using
Node-API 8; no multi-platform prebuilt addon distribution or npm release is
included in this change. Host signing policy and more Electron/OS combinations
need their own validation.
