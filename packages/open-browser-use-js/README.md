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

`tab.playwright.expectPopup(() => action(), {timeoutMs})` returns a newly
created session tab whose reported opener is `tab`; the action is sent once.
The tab can be returned before navigation finishes, so its URL may initially
be empty; wait for the destination before relying on it.

```js
const popup = await tab.playwright.expectPopup(
  () => tab.playwright.getByRole("link", {name: "Open details"}).click(),
  {timeoutMs: 15000},
);
await popup.playwright.waitForURL(/\/details(?:[?#]|$)/, {timeoutMs: 15000});
```

`browser.tabs.list()` exposes an `openerTabId` when both tabs are in the
same session and the backend knows the opener.
It polls owned tabs, so a popup closed before observation or without an opener
can time out. Concurrent matching popups are rejected as ambiguous, and only one popup
expectation per opener can run in a browser instance. The timeout includes
tab-list preparation. If preparation times out, the action is not issued;
a timeout after the action starts means it may still be running, so inspect
the session before retrying. Chrome popups with
no recorded session origin are released rather than closed by finalization;
close a popup explicitly when appropriate. Electron finalization closes unkept
popups when they have no pending operation.

`browser.newTab({url})` closes the newly created tab when navigation fails. If
cleanup also fails, it reports both errors so the session can be inspected.

`goto(url, {timeoutMs})` includes navigation preparation and loading in one
timeout. A preparation timeout occurs before dispatch; after navigation begins,
a timeout means the outcome can be unknown. Already issued browser commands
cannot be cancelled, so inspect the tab before retrying.


The same tab helpers are available without the `playwright` alias:

```js
await tab.goto(url, { waitUntil: "load", timeoutMs: 15000 });
await tab.waitForLoadState({ state: "domcontentloaded", timeoutMs: 15000 });
const text = await tab.domSnapshot();
const value = await tab.evaluate("document.title");
const heading = await tab.playwright.evaluate(selector => document.querySelector(selector)?.textContent, "h1");
const axTree = await tab.getAXState(); // CDP accessibility tree
const png = await tab.getScreenshot(); // PNG Buffer
```

Screenshot results are checked for canonical Base64 and PNG framing before they
are returned; this does not fully decode the image or verify every chunk.

`playwright.evaluate` accepts a function with one JSON-serializable argument or
an expression string, awaits promises, and returns a JSON value. Non-finite
numbers, negative zero, nested undefined values, functions, symbols and BigInts
are rejected before sending the request. Objects with `toJSON` follow their JSON
conversion. `undefined` is
returned as `null`; non-JSON CDP results such as `NaN` and `BigInt` raise an error.
The function
runs in the page context without access to its caller’s closures. Chromium
rejects operations it considers to have side effects; some otherwise harmless
expressions may also be rejected. Its default timeout is five seconds; an optional
third argument accepts `timeoutMs`. A preparation timeout prevents late dispatch;
already issued reads may finish after the caller times out. For explicit page
mutation, use `tab.evaluate`.

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

To obtain accessibility text and a screenshot together, call
`const view = await tab.getAXStateAndScreenshot()` and emit `view.screenshot`
with `nodeRepl.emitImage(view.screenshot)`. `view.observation` contains the
indexed targets and snapshot ID. The SDK captures the state and image in
sequence, then rejects the result if navigation, the frame tree, the connection,
or the active observation changed during capture. Frame-tree checking applies
when frames are included. Dynamic content can still change between the two captures.

To scroll at an observed target, call `tab.scroll(index, snapshotId, direction,
pages)`. Directions are `up`, `down`, `left`, and `right` (or their initial
letters); one page is 80% of the corresponding viewport dimension. Fractional
page counts are supported. The SDK checks target identity, visibility and frame
routing, and can scroll the target into view during preparation. The wheel may
scroll an ancestor. After an uncertain result, observe before retrying. Use
`includeText:true` when the scrollable region has a supplemental accessible
role such as `group` or `region`.

For indexed interaction, call `observe` immediately before choosing a target:

```js
const state = await tab.observe();
nodeRepl.write(state.text);
const button = state.nodes.find(node => node.role === "button" && node.name === "Save");
if (button) await tab.click(button.index, state.snapshotId);

const next = await tab.observe();
const field = next.nodes.find(node => node.role === "textbox" && node.name === "Message");
if (field) await tab.typeText(field.index, next.snapshotId, "Hello");

const selectionState = await tab.observe();
const editor = selectionState.nodes.find(node => node.role === "textbox" && node.name === "Message");
if (editor) await tab.selectText(editor.index, selectionState.snapshotId, "Hello", {selectionType: "cursor_after"});
```

`selectText` selects a unique exact match in an editable input, textarea or
contenteditable target. `prefix` and `suffix` disambiguate adjacent text;
`selectionType` can select the text or place the cursor before or after it.
The operation focuses the target, so its focus handlers can run. Selection is
limited to text content of at most 1 MiB and input types that support native
text selection. Use `tab.typeAtFocus(text)` to replace the selected range; indexed
`typeText` clicks its target before typing.

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

`locator.evaluate((element, argument) => ..., argument, {timeoutMs})` reads one
matched element in an isolated browser world. The locator must resolve uniquely;
its target and scope are checked before and after evaluation. Chromium rejects
operations it considers to have side effects, and the execution deadline stops
long-running code. Text-node matches provide their parent element. The page's
JavaScript variables are unavailable in this isolated world.
`locator.evaluateAll((elements, argument) => ..., argument, {timeoutMs})`
reads the ordered matches as an array, including an empty array when nothing
matches. Up to 1000 matches are supported. Matches must belong to one frame;
use `frameLocator` when a semantic locator matches elements in multiple frames.
The target set is checked before and after execution, with the same read-only
and timeout rules as `evaluate`.

`innerText()` reads the matched DOM node, including in supported frames. It
requires one match and rejects text longer than 30,000 characters.
Heading locators can filter by positive integer `level`; observations expose
the browser-reported level when available.
`textContent()` reads the raw DOM text, including hidden descendants, with the
same match and length checks.
`getByTitle()` finds elements with a matching `title` attribute or direct SVG
`<title>` child from the page,
frame, CSS or semantic scope. String matching normalizes whitespace and ignores
case for substring matching; `{exact: true}` uses case-sensitive equality.
Regular expressions match normalized titles and retain their flags.
`allTextContents()` and `allInnerTexts()` read raw text and rendered inner text
from all current semantic matches in one
observation, returning an empty array when there are none. Each value is limited
to 30000 characters and the total to 1000000. The page can change between reads;
stale targets are retried within the optional `timeoutMs`. A positive deadline
also bounds each browser read; timed-out reads may finish later.
`focus()` focuses the matched element without dispatching mouse or keyboard
input. It rechecks the match and focus chain; focus handlers can change the page,
and a changed target causes an error without repeating the focus. A positive
`timeoutMs` covers focus preparation and dispatch: preparation timeout prevents
late dispatch, while a timeout once dispatch begins reports an unknown outcome. Target and frame
focus checks use an isolated world so page scripts cannot replace those DOM methods. Semantic input target
checks also run in an isolated world; unavailable contexts fail before input.
`clear()` fills the matched editable control with an empty string, using the
same focus, validation and timeout behavior as `fill()`.
`pressSequentially(text)` focuses the editable control and enters characters one
at a time. US-layout printable characters use trusted key events; characters
outside that layout use text insertion, which does not emit key events. Newline
and tab send Enter and Tab. The operation stops if the target loses focus, and a
positive timeout stops further input; once focus or input is issued, a timeout
reports an unknown outcome and may leave a partial value. Inspect the page before
retrying.
Editable text inputs exposed as `combobox` support `fill()` and `type()`;
noneditable comboboxes reject text before mouse input.
`inputValue()` reads the current value of an input, textarea or select (up to
30,000 characters); password values are redacted. Multiple-select values follow
the browser’s single `value` property.
`boundingBox()` on a CSS or semantic locator returns `{x,y,width,height}` in
main-frame CSS viewport coordinates, or `null` for a hidden target. Offscreen
coordinates can be negative; rotated or skewed ancestor frames are rejected.
The locator and frame geometry are rechecked, but can change after the call.
`isChecked()` reads a binary checked state from the accessibility tree and rejects
mixed or unsupported states.
Single-target text, attribute, state, value and bounding-box reads use the same
positive deadline for target lookup and reading. A timed-out read may finish later.
Other locator action timeouts bound the initial target query; a timed-out query cannot
issue a late action. Later action preparation and issued input may take longer.
`waitFor()` bounds browser reads when `timeoutMs` is positive. Timed-out reads may finish later; `timeoutMs: 0` performs one read.
`isEditable()` checks enabled and readonly states for native inputs, textarea,
select, contenteditable elements, and supported ARIA roles, including implicit
roles reported by the browser accessibility tree. Other elements raise an error. This state check does not guarantee that every input
method supports the target control.
`isVisible()`, `isHidden()`, `isEnabled()`, `isDisabled()`, `isChecked()` and
`isEditable()` accept `timeoutMs` for their browser reads. `isVisible()` and
`isHidden()` inspect the current match without waiting for it to appear.
`isHidden()` returns the inverse of `isVisible()`, including for an absent match;
`isDisabled()` returns the inverse of `isEnabled()` and waits for a match.
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
`click()` and `dblclick()` accept `button` (left, middle, or right) and
`modifiers` (Alt, Control, ControlOrMeta, Meta, Shift). `force: true` skips
hit-testing while retaining target, geometry, stability and disabled-state
checks. Input is dispatched at the target's main-page coordinate, so a covering
element can receive the click. `dblclick()` rechecks the target and its position between clicks. If the first
click changes the page or a later input fails, inspect the result before retrying.
If a mouse press or release fails, the SDK attempts a release and reports the
original error; the page may already have received the click.

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
frame position; this catches movement visible between those samples. Before
input and scoped reads, a separate accessibility observation re-evaluates the
locator and its position; changed matches trigger a fresh attempt before input.
The recheck leaves the active operation's observation intact.
For `click`, `dblclick`, `hover`, `focus`, and `pressSequentially`, a positive timeout also bounds preparation and reports
when the input outcome is unknown. A timed-out click or double click may still release an already
pressed mouse button; preparation may have scrolled the page. Other actions can
finish a slow browser request after the deadline. Multiple matches fail immediately.
An issued input action is not retried after an error. This initial locator API does not include every
Playwright locator method.

Locators can be chained to search descendants of matching accessible containers.
For example, `getByRole("dialog", {name: "Settings"}).getByRole("button",
{name: "Save"})` narrows a repeated button name to that dialog. Descendant
checks cross shadow roots and iframe boundaries. Scope roles and containment are
checked again before input; a focus handler can also change the scope, so
`press()` checks it after focusing. This API follows the accessible tree and
requires all observed frames to be readable.

Use `frameLocator` to restrict semantic queries to a particular iframe:

```js
const payment = tab.playwright.frameLocator('iframe[name="payment"]');
await payment.getByLabel("Card number", {exact: true}).fill("...");
const nested = payment.frameLocator('iframe[name="verification"]');
await nested.getByRole("button", {name: "Continue", exact: true}).click();
```

Each selector is native CSS matched against direct child frame elements of its
parent document with `Element.matches` in a named isolated world; a selector
must match the iframe itself. Page scripts can change the DOM but cannot replace
the selector implementation used in that world.
Nested calls select one frame level at a time. Missing frames yield no matches;
multiple matching frames produce an error. Frame identity and selector matching
are rechecked before reads and input, and inaccessible observed frames cause
an incomplete-results error. Semantic targets still come from the accessibility
tree.

Native CSS element queries are available for reading DOM content:

```js
const items = tab.playwright.locator("[data-item]");
console.log(await items.count(), await items.first().textContent());
await tab.playwright.getByTestId("save-button").click();
await tab.playwright.locator(".product").getByTestId("price").textContent();
await tab.playwright.locator(".product").first().locator("button.buy").click();
const books = tab.playwright.locator(".catalog").locator(".product", {hasText: "Book"});
console.log(await payment.locator("input[name=card]").getAttribute("name"));
```

CSS locators support `count`, `all`, `first`, `last`, `nth`, `innerText`,
`textContent`, `allTextContents`, `allInnerTexts`, `getAttribute`, `isVisible`, `isHidden`, `isEnabled`, `isDisabled`,
`isChecked`, `isEditable`, `inputValue`, `boundingBox`, `waitFor`, `click`, `dblclick`, `hover`, `press`, `focus`, `fill`, `clear`, `type`, `check`,
`uncheck`, `setChecked` and `selectOption`. They search the selected document and its open
shadow roots, including hidden elements; they do not cross frames unless a
`frameLocator` is selected. Matches are limited to 1,000 elements and single
reads require a unique match. Selector evaluation uses an isolated world, and
reads recheck document, frame and match identity. Click and hover also check
visibility, hit testing and stable geometry before issuing trusted mouse input.
`press` checks the selected frame, target identity and focus again after focusing.
`fill` supports text-like and number inputs, textareas, contenteditable elements,
and native date, time, month, week and datetime-local inputs. Text input rechecks
focus and selection before inserting. Number inputs are checked with the native
number parser before focus and again after focus and selection; an invalid
value is rejected before text insertion. `type()` inserts the supplied text at the
current caret or selection without selecting all; it sends one text insertion
rather than individual key events. Native date/time inputs use `fill()`. Double-click checks the target again after
the first click. Check operations support native checkbox and radio inputs and
binary ARIA checkbox, radio, switch and menuitem variants; an already selected
radio cannot be unchecked directly. `selectOption` supports native single and
multiple selects, matching enabled options by value or label; its `input` and
`change` events are synthetic. Batched text is limited to 1,000,000 characters. Date and time
values are validated using
the native input parser; their `input` and `change` events are synthetic
(`isTrusted` is false). `locator()` chains descendant queries, and `first`,
`last` and `nth` can select an intermediate scope. Each chain is limited to
32 selectors and 1,000 matched elements in total; the identity of each selected
scope is rechecked along with the final matches before reads and input. CSS locators support
`filter({hasText: ...})` and `filter({hasNotText: ...})` with strings or regular
expressions, before or after `first`/`last`/`nth`. Filters use normalized DOM
text including open shadow roots and hidden text, excluding script, style and
noscript; they stay within the selected frame. A filtered element's collected
text is limited to 30,000 characters. Filters are re-evaluated before input. `locator(selector, options)` also accepts
`hasText`, `hasNotText`, `has` and `hasNot`, applying them to the newly
selected descendants; unsupported option keys are rejected. CSS `filter({has: inner})`
and `filter({hasNot: inner})` accept CSS locators from the same browser tab and
frame, evaluated relative to each candidate, including open shadow roots.
Nested locator filters are limited to eight levels and 100,000 element visits. `and(other)` intersects two CSS locators
from the same browser tab and frame. It preserves the order of position and
filter operations and can be used inside `has` and `hasNot` filters. `or(other)`
combines CSS locator matches in document and open-shadow traversal order,
removes duplicates, and supports subsequent position selection and chaining.
Both operands must refer to the same browser tab and frame.
Semantic locators also support `and(other)` and `or(other)` with semantic
locators in the same tab and frame. They combine the observed target set,
deduplicate unions in observation order, and recheck matches before input.
Position selection and filters can follow the combination. Combination nesting
is limited to eight levels. `and()` also accepts one CSS and one semantic
locator, in either order; the CSS operand must have no semantic root scope.
The intersection contains observable semantic targets in the CSS result.
Mixed CSS and semantic `or()` is not supported.
Semantic locators are not yet supported as inner filters. CSS locators can scope
`getByRole`, `getByLabel`, `getByText`, `getByAltText` and `getByPlaceholder`;
the first semantic target is resolved in the CSS locator's selected frame.
The CSS scope, its filters and containment are rechecked before reads and input. A semantic locator can also scope `locator()`
and `getByTestId()`; matching semantic containers are re-evaluated before
reads and input. Their matched containers must be in one frame; select a frame
or refine the semantic locator when they span multiple frames. Multiple
containers are traversed in accessibility-observation order, with duplicate
CSS descendants removed. A semantic text node has no CSS descendants. CSS
`and`/`or` operands rooted in semantic scopes must share the same semantic
locator object. `filter({visible: true})` and
`filter({visible: false})` check CSS visibility and nonzero element and frame
bounds. They can be combined with text and descendant filters; occlusion is
checked by pointer actions. `waitFor`
supports attached, detached, visible and hidden states. Visibility checks CSS
visibility and nonzero element and frame bounds; it does not test occlusion.

`filter({hasText: "..."})` and `filter({hasNotText: "..."})` narrow a
locator by its accessible static-text descendants. Matching is a case-insensitive
substring after whitespace normalization; text fragments are joined with spaces.
This includes readable child frames, shadow roots, and generated text whose
accessible ancestry identifies its scope. `aria-label` alone does not count as
descendant text. Semantic locators also
support `filter({has: inner})` and `filter({hasNot: inner})` with semantic or
CSS locators from the same tab and frame. Each inner locator is evaluated relative
to the candidate, including its position and nested filters; descendant frame
documents are outside that inner match. Inner semantic locators rooted in CSS
scopes and inner CSS locators rooted in semantic scopes are not supported. Filter
nesting is limited to eight levels. Semantic `filter({visible: true/false})`
checks candidate and frame bounds; the accessibility tree may omit hidden elements.
The operation rejects a candidate when the text relationship cannot be
determined, when frames are inaccessible, or when the candidate contains more
than 30,000 characters. Text is checked again before input and after focus; pages
with many text nodes can require many browser requests. String and regular
expression filters are supported.

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
For CSS and semantic locators, `force: true` skips hit-testing; the browser
still delivers input to whatever is at that coordinate. Check operations verify
the requested state afterward and report failure if it did not change.

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

`selectOption` accepts a value or label, a descriptor containing `value`,
`label`, or a zero-based `index`, or an array for a multiple select. When a
descriptor supplies multiple fields, all must match the same option. It returns
selected values, waits for available options
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

`await tab.playwright.screenshot({fullPage:false})` returns an image object with
`toBase64()` that can also be passed to `nodeRepl.emitImage`; `clip` and
`fullPage` follow the same limits as `tab.getScreenshot`. The Playwright-style
`waitForTimeout(ms)` accepts 0–120,000 ms; prefer page and locator state waits
when waiting for a specific condition.

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
this method through their page grant. `await tab.getPresentation()` reports
the owned tab's physical selection and host-window state:

```js
const {backend, selected, visible, windowFocused} = await tab.getPresentation();
```

For Chrome, `selected` is the browser's selected tab in its window, independent
of the session's logical active tab. `visible` is `false` for an unselected tab
or minimized window and `null` when actual visibility is unknown. For Electron,
`selected` means a host surface presents the tab; `visible` reflects whether
that host window reports visible and non-minimized. These values do not detect
occlusion or guarantee rendering, and can change immediately after the call.
`windowFocused` reports host-window focus when available and can be `null`.
In isolated Linux ARM64 Chromium 150,
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
expected destination. `await tab.reload({timeoutMs: 15000})` waits for the main
page load event; its default timeout is 10 seconds and includes preparation.
A preparation timeout occurs before dispatch. If a command fails or times out
after dispatch, inspect the page before deciding whether to try again.

## Waiting for a URL

`await tab.waitForURL("https://example.com/done")` waits for an exact URL.
`await tab.playwright.waitForURL(/\/done(?:\?|$)/, {waitUntil: "domcontentloaded", timeoutMs: 15000})`
accepts a regular expression. Both forms inspect the current main document and
work with history API route changes as well as document navigation. Use
`{waitUntil: "commit"}` to return once the current document URL matches, even
while the document is loading. The default load state is `load` and the default
timeout is 10 seconds; `timeoutMs: 0`
checks once. URLs are sampled roughly every 100 ms, so transient intermediate
URLs can be missed. Positive timeouts bound each browser read; a read already
issued can finish later. A zero-timeout single check waits for its browser read.

`networkidle` is not currently supported by these waits. Wait for the URL,
load state, or a specific page element instead. Chrome can replay an old
network-idle lifecycle event while a later request remains in flight, so that
event alone cannot establish the current network state.

URL and readiness checks read the main document in an isolated browser world,
so page scripts cannot replace the getters used by these waits.

`waitForLoadState({state, timeoutMs})` includes setup and state reads in a
positive timeout and removes its event listener on timeout. With `timeoutMs: 0`
it checks the current state once and waits for that read to finish. A read
already issued can complete after a positive timeout.

To observe navigation triggered by an action, register the wait before the
action runs:

```js
await tab.playwright.expectNavigation(
  () => tab.playwright.getByRole("link", {name: "Continue", exact: true}).click(),
  {url: "https://example.com/done", timeoutMs: 15000}
);
```

This watches main-frame document and same-document navigation, then waits for
the requested URL and load state. The timeout includes preparation: if that
phase times out or the connection changes, the action is not issued. A timeout
or action error after the action starts can occur after it has taken effect;
inspect the page before retrying. The timeout bounds a pending action callback;
it cannot cancel a command already issued.

## Clipboard

Tabs expose clipboard operations when their backend permits them:

```js
await tab.clipboard.writeText("hello");
const text = await tab.clipboard.readText();
await tab.clipboard.write([{entries: [{mimeType: "text/plain", text: "hello"}]}]);
const items = await tab.clipboard.read(); // entries contain text or base64
```

To paste into an observed target, use its current index and snapshot ID:

```js
await tab.paste(field.index, "Hello", {snapshotId: state.snapshotId});
await tab.paste(null, "**Markdown**", {format: "md"}); // current focus
await tab.paste(null, "<b>Hello</b>", {format: "html", plainText: "Hello"});
```

`paste` writes the clipboard and sends a trusted platform paste shortcut.
`text` and `md` use plain text; Markdown source is not converted to HTML.
HTML can include `plainText` for applications that cannot accept rich text;
without it those applications may ignore the paste. The clipboard is not
restored. A different process can change it between write and paste, and an
error after the write can leave the clipboard changed or the paste outcome
unknown; inspect the page before retrying. Indexed paste checks the observation
and connection before input. Electron requires `clipboard.write` as well as
`page.control`; current-focus paste uses whichever element is focused when the
shortcut is sent.

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
const available = await agent.browsers.list();
const browser = await agent.browsers.get('extension'); // or 'iab' / an explicit listed ID
const tab = await browser.tabs.new();
await tab.goto("https://example.com");
nodeRepl.write(await tab.getAXState());
nodeRepl.emitImage(await tab.getScreenshot());
```

Top-level `const`, `let`, and named `class` declarations can be redeclared in
later calls. Top-level variable declarations are stored as mutable `var`
bindings; block-scoped declarations keep their JavaScript scope. The server
uses a JavaScript parser for this transformation and falls back to Node's REPL
for syntax it cannot parse.

The `js` tool accepts `timeout_ms` (1–600,000 ms; default 30,000) and an
optional `title`. A timed-out asynchronous execution can continue and have
side effects. Further JavaScript calls are rejected until it settles; inspect
the browser before retrying. Restart the MCP process if it never settles. A
synchronous infinite loop blocks the Node event loop and cannot be interrupted
by this timer.

For `notifications/cancelled` on a `js` request, the server stops waiting and
suppresses its response. JavaScript already running is not interrupted and may
still have side effects; the session stays busy until execution settles. Once the REPL input closes and
accepted requests have settled, built-in browser connection helpers reject new
connections; already running arbitrary code can still have other effects.

Output emitted after an execution settles, times out or is cancelled is discarded.

Protocol requests can complete independently while asynchronous JavaScript is
running. `ping` remains responsive; additional `js` and `js_reset` calls report
that the session is busy. Synchronous JavaScript still blocks the event loop.

The `js_reset` tool clears JavaScript bindings and restores the built-in
helpers while retaining connected browser sessions and their tabs. Reacquire a
browser with `agent.browsers.get(...)` after reset. Reset is rejected while an
execution remains active; previously scheduled background work is not cancelled.

After selecting a browser, `await browser.tabs.getByUrl(url)` binds the single
session-owned tab with an exactly matching URL. Missing or duplicate matches
raise an error; the method does not claim user tabs outside the session. The URL is
checked at lookup time; the returned handle follows the tab ID after navigation.

`agent.browsers.list()` reports available browser IDs, types and capabilities.
`agent.browsers.get(id)` selects a listed ID or the unique `extension` / `iab`
type and reuses the REPL session connection. Ambiguous or unresponsive matches
fail explicitly; the embedded browser retains its host-authorized scope.

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
JPEG or WebP bytes; the file signature must match the MIME type. JavaScript evaluations run one at a time. Closing MCP stdin closes the
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

The Playwright-style event API also registers before subsequent SDK input:

```js
const choosing = tab.playwright.waitForEvent("filechooser", {timeoutMs: 30000});
const click = tab.playwright.locator('input[type="file"]').click();
void click.catch(() => {});
const chooser = await choosing;
await chooser.setFiles("/absolute/path/to/file.txt");
await click;
```

Keep the click in flight until the chooser decision is issued. Registration
failure rejects subsequent SDK CDP commands that are waiting on it; low-level
client requests and actions outside the SDK bypass this coordination.

`prepareFileChooser` returns after the extension enables interception. `setFiles`
accepts an absolute path or an array of absolute paths and permits one decision
per chooser. Frame navigation or debugger detachment invalidates outstanding
chooser handles. An error after issuing a decision can leave the outcome
unknown; inspect the page before another action. Cross-process iframe sessions
already attached at preparation are intercepted. If the frame tree changes
while waiting, the wait fails; prepare a new one after observing the page.
Electron hosts must authorize the exact files and grant `files.upload` and
`page.control` first; see the Electron integration guide.

## Browser tabs and user context

The high-level browser also exposes the Codex-style tab facade:

```js
await browser.nameSession('🔎 research');
const tabs = await browser.tabs.list();
const tab = await browser.tabs.get(tabs[0].id); // session-owned tabs only
const newTab = await browser.tabs.new();
const selected = await browser.tabs.selected();
const userTabs = await browser.user.openTabs();
const history = await browser.user.history({query: "example", limit: 10}); // Chrome history
// await browser.user.claimTab(userTabs[0]); // explicitly moves a Chrome user tab into this session
// await browser.tabs.finalize({keep: [{tab: newTab, status: 'handoff'}]});
```

`tabs.finalize()` closes or releases other session tabs according to the backend;
call it only when those effects are intended. `selected()` uses the backend's
reported active flag: Chrome reports session-logical selection and Electron
reports presented tabs. Multiple active tabs cause an explicit error. Tab-list
IDs are strings; tab handles retain their numeric `id`. Electron user tab
listing is limited to its authorized scope, and its history is unavailable.
History entries contain `url`, `dateVisited`, and an optional `title`; invalid
backend responses are rejected.

## Capabilities and WebMCP

`browser.capabilities.list()` and `tab.capabilities.list()` return advertised
capability IDs and descriptions. Chrome advertises `webmcp` for session-owned
tabs when its WebMCP gate is enabled. Electron advertises it for scopes that
the host explicitly opens with `webmcp: true` and grants `page.control`:

```js
if ((await tab.capabilities.list()).some(cap => cap.id === 'webmcp')) {
  const webmcp = await tab.capabilities.get('webmcp');
  const tools = await webmcp.listTools();
  // Inspect the page-provided tool and obtain authorization for its action.
  // const result = await webmcp.invokeTool(tools[0], { /* tool input */ });
}
```

Tools and results come from the page. Listing creates registration IDs tied to
that page's current tool snapshot; listing again, tool changes or navigation
can invalidate them. Invocation is sent once, so inspect the page before
retrying an uncertain result. Electron uses a page bridge for opted-in scopes; see the Electron guide for
popup and permission details. Capability metadata without an SDK implementation is listed but
`get()` reports it as unimplemented.

## DOM CUA

`tab.dom_cua.get_visible_dom()` returns `{nodes}` with opaque `node_id`,
`frame_id`, tag, role, short name, input type, disabled and checked state for
visible, viewport-intersecting interactive elements in readable frames and open shadow roots. Frame viewport
intersection is propagated through axis-aligned frame bounds. Rotated or skewed
frames make the snapshot fail explicitly. Browser intersection observations also
filter nodes clipped by overflow ancestors. If the document is hidden or an
intersection observation takes over three seconds, the result sets
`visibility_incomplete: true` and applies conservative rectangular overflow clipping.
Complex clipping and occlusion can remain unrepresented.
Occlusion is checked before input.
The underlying match set is limited to 1000 elements across frames. Names use
`aria-labelledby`, `aria-label`, associated labels and common text attributes;
they are a DOM-derived approximation of accessible names. Field values are not
included. Text and attributes are page data and may be incomplete.

Use `click({node_id})` or `double_click({node_id})` for a node, then
`type({text})` or `keypress({keys})` for the focused element. `scroll({x,y,
node_id?})` sends a wheel gesture at the node or viewport center. A new
snapshot or DOM CUA action invalidates old IDs. Tab handles from the same
browser share DOM CUA state; concurrent snapshots supersede earlier ones, and
reconnecting invalidates node IDs. New snapshots and actions are rejected while
a DOM CUA input is in progress. Before clicking, the SDK rechecks
node identity, form state, membership in the visible match set, geometry and hit target; an outdated or
changed target fails and requires another snapshot. Downloads use the separate download workflow.

## Waiting for a download

On Chrome or an explicitly authorized Electron scope, register the listener
before triggering the page action:

```js
const ready = await tab.prepareDownload({timeoutMs: 30000});
await tab.playwright.getByRole("link", {name: "Download", exact: true}).click();
const download = await ready.wait();
console.log(download.attribution); // "tab", "browser", or "unknown"
const path = await download.path(30000); // null if the download failed or was cancelled
```

The Playwright-style equivalent starts waiting before the action:

```js
const waiting = tab.playwright.waitForEvent("download", {timeoutMs: 30000});
await tab.playwright.getByRole("link", {name: "Download", exact: true}).click();
const download = await waiting;
```

`locator.downloadMedia()` triggers a download from the first match's image,
video, audio, source, or link URL. Register the download wait first, as above;
replace the click with `await locator.downloadMedia()`. The trigger uses a
synthetic anchor, and the browser can block automatic downloads. HTTP(S) media
must be same-origin; cross-origin URLs are rejected because the browser may
ignore the download attribute. Blob and data URLs are accepted; redirects remain
subject to browser behavior.
A returned trigger does not guarantee a completed download: await the download
event and its path, and inspect the result before retrying after an error.

SDK CDP page operations issued after `waitForEvent` wait for registration confirmation;
registration failure rejects those pending commands. Direct low-level client
requests and actions outside this SDK do not use that barrier. Attach a rejection
handler to the waiting promise if the triggering action may fail.

For a tab-scoped download-start observation, arm the CDP event before the action:

```js
const started = await tab.prepareDownloadStart({timeoutMs: 30000});
await tab.playwright.getByRole("link", {name: "Download", exact: true}).click();
const {guid, frameId, url, suggestedFilename} = await started.wait();
```

This reports the browser's download-start event and covers the main frame and
cross-process frames attached during preparation. New cross-process frames are
enabled after attachment; subsequent SDK CDP commands wait for that enablement.
Downloads initiated independently by the page before enablement can be missed. The GUID identifies the CDP download event; it is separate from the
opaque handle returned by `prepareDownload()` and does not provide a file path.
`Page.downloadWillBegin` is an experimental, deprecated CDP event.

`prepareDownload` returns after the extension confirms registration. The
result is the next Chrome download started after registration; the extension's
download event currently has no reliable tab association, so another tab's
concurrent download may satisfy the wait. Verify the download identity before
using its path. Chrome permits path lookup only in the session that received
the download handle; Chrome returns a random opaque handle held in extension
memory rather than its native numeric download ID. Electron matches
the originating tab and requires the host to configure a directory and grant
`files.download` with `page.control`. `download.attribution` reports `"tab"`
for a verified tab association, `"browser"` for the next browser-wide download,
and `"unknown"` when the backend does not report attribution.

## Notifications

The JS SDK can subscribe to JSON-RPC notifications from the native socket. This
is useful for session-scoped CDP events. Use `prepareDownload()` and
`download.path()` to wait for a download and its completed path.

```js
const unsubscribe = client.onNotification((event) => {
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
