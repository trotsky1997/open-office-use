import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { __browserClientInternals } from "../browser-client.mjs";

const commandPrefix = /^(browser_user|close_tab|create_tab|cua|dom_cua|finalize_tabs|list_tabs|name_session|navigate_tab|playwright|selected_tab|tab_)/;
const nonCommands = new Set(["tab_id"]);

test("browser-client rewrite covers generated Browser Use command strings", async () => {
  const metadata = JSON.parse(
    await readFile(new URL("../../../docs/generated/browser-client-metadata.json", import.meta.url), "utf8"),
  );
  const handlers = new Set(__browserClientInternals.commandHandlers.map((handler) => handler.type));
  const missing = metadata.commandStrings
    .filter((command) => commandPrefix.test(command))
    .filter((command) => !nonCommands.has(command))
    .filter((command) => !handlers.has(command));

  assert.deepEqual(missing, []);
});

test('download commands use scoped host requests', async () => {
  const calls=[];const api={async sendSessionRequest(method,params){calls.push({method,params});return method==='waitForDownload' ? {downloadId:'download-1'} : {path:'/tmp/result'};}};
  const downloads=new __browserClientInternals.Downloads(api);
  assert.deepEqual(await downloads.waitForDownload({tabId:7,timeoutMs:1234}),{download_id:'download-1'});
  assert.deepEqual(await downloads.path({downloadId:'download-1',timeoutMs:2345}),{path:'/tmp/result'});
  assert.deepEqual(calls,[{method:'waitForDownload',params:{tabId:7,timeoutMs:1234}},{method:'downloadPath',params:{downloadId:'download-1',timeoutMs:2345}}]);
});
