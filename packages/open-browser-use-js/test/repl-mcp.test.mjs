import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { endianness, tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { encodeFrame } from "../dist/index.js";

test("MCP REPL retains bindings, uses one browser session and emits images", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-repl-"));
  const socketPath = join(directory, "browser.sock");
  const requests = [];
  const handleConnection = (socket) => {
    let data = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      data = Buffer.concat([data, chunk]);
      while (data.length >= 4) {
        const length = endianness() === "LE" ? data.readUInt32LE(0) : data.readUInt32BE(0);
        if (data.length < length + 4) return;
        const request = JSON.parse(data.subarray(4, length + 4));
        data = data.subarray(length + 4);
        requests.push(request);
        const result = request.method === "createTab" ? { id: 42 } : request.method === "getTabs" ? [{id:42,title:"Fixture"}] :
          request.params.method === "Page.captureScreenshot" ? { data: Buffer.from("image").toString("base64") } : {};
        socket.write(encodeFrame({ jsonrpc: "2.0", id: request.id, result }));
      }
    });
  };
  const server = createServer(handleConnection);
  const other = createServer(handleConnection);
  server.listen(socketPath);
  await once(server, "listening");
  other.listen(join(directory, "other.sock"));
  await once(other, "listening");
  let otherOpen = true;
  const child = spawn(process.execPath, [fileURLToPath(new URL("../dist/repl-cli.js", import.meta.url))], { stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, OBU_SOCKET_DIR: directory } });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  let id = 0;
  async function call(method, params) {
    const expected = ++id;
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: expected, method, params }) + "\n");
    const response = JSON.parse((await lines.next()).value);
    assert.equal(response.id, expected);
    assert.equal(response.error, undefined);
    return response.result;
  }
  const js = (code) => call("tools/call", { name: "js", arguments: { code } });
  try {
    assert.equal((await call("tools/list")).tools[0].name, "js");
    assert.equal((await js("nodeRepl.write((await discoverBrowsers()).length)")).content[0].text, "2");
    assert.equal((await js("nodeRepl.write((await agent.browsers.list()).length)")).content[0].text,"2");
    assert.equal((await js("await agent.browsers.get('extension')")).isError,true);
    assert.equal((await js("nodeRepl.write((await getBrowserState()).available.length)")).content[0].text, "2");
    assert.equal((await js("await connectBrowser({browserId:'a',socketPath:'b'})")).isError,true);
    assert.equal((await js("await connectBrowser()")).isError, true);
    const otherClosed = once(other, "close");
    other.close();
    await otherClosed;
    otherOpen = false;
    const stalled = createServer(socket => { socket.on("error", () => {}); socket.resume(); });
    stalled.listen(join(directory, "stalled.sock"));
    await once(stalled, "listening");
    try {
      assert.equal((await js("nodeRepl.write((await discoverBrowsers()).some(b => b.status === 'unresponsive'))")).content[0].text, "true");
      assert.equal((await js("await connectBrowser()")).isError, true);
    } finally {
      const stopped = once(stalled, "close");
      stalled.close();
      await stopped;
    }
    assert.equal((await js("const selected = await connectBrowser(); nodeRepl.write(await selected.client.getInfo())")).isError, undefined);
    assert.equal((await js("nodeRepl.write((await agent.browsers.get('extension')) === selected)")).content[0].text,'true');
    assert.equal((await js("nodeRepl.write((await agent.browsers.get('extension')).browserId)")).content[0].text,socketPath);
    assert.equal((await js(`const browser = await connectBrowser({ browserId: ${JSON.stringify(socketPath)} }); const tab = await browser.newTab()`)).isError, undefined);
    assert.equal((await js("nodeRepl.write(tab.id)")).content[0].text, "42");
    assert.equal((await js("nodeRepl.write((await getBrowserState()).sessions.some(session => session.tabs?.[0]?.title === 'Fixture'))")).content[0].text, "true");
    assert.equal((await js("selected.close(); nodeRepl.write((await getBrowserState()).sessions.length)")).content[0].text,"1");
    const image = (await js("nodeRepl.emitImage(await tab.getScreenshot())")).content[0];
    assert.deepEqual(image, { type: "image", mimeType: "image/png", data: Buffer.from("image").toString("base64") });
    const playwrightImage = (await js("nodeRepl.emitImage(await tab.playwright.screenshot({fullPage:false}))")).content[0];
    assert.deepEqual(playwrightImage,image);
    assert.equal((await js("nodeRepl.write((await tab.playwright.screenshot()).toBase64())")).content[0].text,Buffer.from("image").toString("base64"));
    assert.equal((await js("await tab.playwright.waitForTimeout(0)")).isError,undefined);
    assert.equal((await js("await tab.playwright.waitForTimeout(-1)")).isError,true);
    const cuaImage = (await js("nodeRepl.emitImage(await tab.cua.get_visible_screenshot())")).content[0];
    assert.deepEqual(cuaImage,image);
    assert.equal((await js("throw new Error('failure')")).isError, true);
    assert.equal((await js("await Promise.reject(new Error('async failure'))")).isError, true);
    await js("setTimeout(() => nodeRepl.write('late output'), 10)");
    const isolated = await js("await new Promise(resolve => setTimeout(resolve, 30)); nodeRepl.write('current output')");
    assert.deepEqual(isolated.content, [{ type: "text", text: "current output" }]);
    assert.equal((await js("nodeRepl.write(tab.id)")).content[0].text, "42");
    assert.equal(new Set(requests.map((request) => request.params.session_id)).size, 1);
  } finally {
    child.stdin.end();
    await once(child, "exit");
    const closed = [once(server, "close")];
    server.close();
    if (otherOpen) { closed.push(once(other, "close")); other.close(); }
    await Promise.all(closed);
    await rm(directory, { recursive: true, force: true });
  }
});
