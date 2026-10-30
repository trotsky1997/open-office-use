import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
import { endianness, tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
const pngFixture=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==","base64");

import { OpenBrowserUseClient, OpenBrowserUseCdp, connectOpenBrowserUse, encodeFrame } from "../dist/index.js";

test("encodes native-endian length-prefixed JSON frames", () => {
  const frame = encodeFrame({ id: 1, method: "getInfo" });
  const length = endianness() === "LE" ? frame.readUInt32LE(0) : frame.readUInt32BE(0);
  assert.equal(length, frame.length - 4);
  assert.deepEqual(JSON.parse(frame.subarray(4).toString("utf8")), {
    id: 1,
    method: "getInfo"
  });
});

test("dispatches JSON-RPC notifications from the native socket", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-sdk-js-"));
  const socketPath = join(directory, "obu.sock");
  const server = createServer((socket) => {
    socket.write(
      encodeFrame({
        jsonrpc: "2.0",
        method: "onDownloadChange",
        params: { id: "1", status: "started" }
      })
    );
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });

  const client = new OpenBrowserUseClient({ socketPath });
  try {
    const notification = await new Promise((resolve) => {
      client.onNotification(resolve);
      void client.connect();
    });
    assert.deepEqual(notification, {
      method: "onDownloadChange",
      params: { id: "1", status: "started" }
    });
  } finally {
    client.close();
    server.close();
    await new Promise((resolve) => server.once("close", resolve));
    await rm(directory, { recursive: true, force: true });
  }
});

test("reconnects after failed connection and remote disconnect", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-reconnect-"));
  const socketPath = join(directory, "obu.sock");
  const client = new OpenBrowserUseClient({ socketPath });
  await assert.rejects(client.connect());
  let connections = 0;
  let firstClosed;
  const server = createServer((socket) => {
    const number = ++connections;
    if (number === 1) firstClosed = once(socket, "close");
    socket.once("data", (chunk) => {
      const length = endianness() === "LE" ? chunk.readUInt32LE(0) : chunk.readUInt32BE(0);
      const request = JSON.parse(chunk.subarray(4, 4 + length));
      socket.write(encodeFrame({ jsonrpc: "2.0", id: request.id, result: { connection: number } }));
      if (number === 1) socket.end();
    });
  });
  server.listen(socketPath);
  await once(server, "listening");
  try {
    assert.deepEqual(await client.getInfo(), { connection: 1 });
    await firstClosed;
    assert.deepEqual(await client.getInfo(), { connection: 2 });
  } finally {
    client.close();
    server.close();
    await once(server, "close");
    await rm(directory, { recursive: true, force: true });
  }
});

test("connection-bound requests reject after a socket reconnect", async () => {
  const directory=await mkdtemp(join(tmpdir(),"obu-generation-")), socketPath=join(directory,"obu.sock");
  const sockets=[], received=[];
  const server=createServer(socket=>{sockets.push(socket);socket.on('data',data=>received.push(data));});
  server.listen(socketPath); await once(server,'listening');
  const client=new OpenBrowserUseClient({socketPath});
  try {
    await client.connect();
    const generation=client.connectionGeneration;
    const waiting=new OpenBrowserUseCdp(client).waitForEvent(1,()=>false,{timeoutMs:5000});
    const rejection=assert.rejects(waiting,/socket closed/);
    const closed=once(sockets[0],'close');sockets[0].destroy();await closed;await rejection;
    for(let i=0;i<50 && client.connectionGeneration===generation;i++)await new Promise(resolve=>setTimeout(resolve,5));
    assert.notEqual(client.connectionGeneration,generation);
    await assert.rejects(client.request('executeCdp',{},generation),/Connection changed/);
    assert.equal(received.length,0);
  } finally {
    client.close();for(const socket of sockets)socket.destroy();server.close();await once(server,'close');
    await rm(directory,{recursive:true,force:true});
  }
});

test("CDP request timeout follows the command timeout", async () => {
  const directory=await mkdtemp(join(tmpdir(),"obu-cdp-timeout-")),socketPath=join(directory,"obu.sock");
  const server=createServer(socket=>{let pending=Buffer.alloc(0);socket.on("data",chunk=>{
    pending=Buffer.concat([pending,chunk]);while(pending.length>=4){const length=endianness()==="LE" ? pending.readUInt32LE(0) : pending.readUInt32BE(0);if(pending.length<4+length)return;
      const request=JSON.parse(pending.subarray(4,4+length));pending=pending.subarray(4+length);
      const send=()=>socket.write(encodeFrame({jsonrpc:"2.0",id:request.id,result:{ok:true}}));
      if(request.method==="executeCdp" || request.method==="attach")setTimeout(send,350);else send();
    }
  });});
  server.listen(socketPath);await once(server,"listening");const client=new OpenBrowserUseClient({socketPath,timeoutMs:100});
  try {assert.deepEqual(await new OpenBrowserUseCdp(client).call(1,"Runtime.enable",{},{timeoutMs:1000}),{ok:true});}
  finally {client.close();server.close();await once(server,"close");await rm(directory,{recursive:true,force:true});}
});

test("high-level browser tabs can goto, wait for load state, and read a DOM snapshot", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-sdk-js-"));
  const socketPath = join(directory, "obu.sock");
  const calls = [];
  let ownerAvailable = true;
  const server = createServer((socket) => {
    let pending = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      pending = Buffer.concat([pending, chunk]);
      while (pending.length >= 4) {
        const length = endianness() === "LE" ? pending.readUInt32LE(0) : pending.readUInt32BE(0);
        if (pending.length < 4 + length) {
          return;
        }
        const request = JSON.parse(pending.subarray(4, 4 + length).toString("utf8"));
        pending = pending.subarray(4 + length);
        calls.push([request.method, request.params.method ?? null]);
        let result = {};
        if (request.method === "createTab") {
          result = { id: 123 };
        } else if (request.method === "getTabPresentation") {
          result = {backend:"chrome",selected:false,visible:false,windowFocused:true};
        } else if (request.method === "executeCdp" && request.params.method === "Page.navigate") {
          socket.write(
            encodeFrame({
              jsonrpc: "2.0",
              method: "onCDPEvent",
              params: {
                source: { tabId: 123 },
                method: "Page.domContentEventFired",
                params: {}
              }
            })
          );
          result = { frameId: "frame-1", loaderId: "navigation-1" };
        } else if (request.method === "executeCdp" && request.params.method === "Runtime.evaluate") {
          const expression = request.params.commandParams.expression;
          result = expression.includes("readyState")
            ? { result: { value: { href: "https://example.test/issues", readyState: "interactive" } } }
            : { result: { value: "Open\nClosed\nIssues\nStarred" } };
        } else if (request.params.method === "DOM.getDocument") {
          result = { root: { backendNodeId: 1 } };
        } else if (request.params.method === "Page.getFrameTree") {
          result = { frameTree: { frame: { id: "main", loaderId: "one", url: "https://example.test/" }, childFrames: [{ frame: { id: "child", loaderId: "two", url: "https://child.test/" }, childFrames:[{frame:{id:"grandchild",loaderId:"three",url:"https://nested.test/"}}] }] } };
        } else if (request.params.method === "DOM.getFrameOwner") {
          result = ownerAvailable ? {backendNodeId:request.params.commandParams.frameId === "child" ? 9 : 19} : {};
        } else if (request.params.method === "Accessibility.getFullAXTree") {
          result = request.params.commandParams?.frameId === "grandchild" ? {nodes:[{nodeId:"nested-button",role:{value:"button"},name:{value:"Nested action"},backendDOMNodeId:5}]}
            : request.params.commandParams?.frameId === "child"
            ? {nodes:[{nodeId:"child-button",role:{value:"button"},name:{value:"Frame action"},backendDOMNodeId:4},{nodeId:"nested-frame",ignored:true,backendDOMNodeId:19}]}
            : {nodes:[{nodeId:"group",role:{value:"group"},name:{value:"Form"},backendDOMNodeId:3},{nodeId:"main-button",parentId:"group",role:{value:"button"},name:{value:"Submit"},backendDOMNodeId:2},{nodeId:"iframe",parentId:"group",ignored:true,backendDOMNodeId:9}]};
        } else if (request.params.method === "Page.captureScreenshot") {
          result = { data: pngFixture.toString("base64") };
        }
        socket.write(encodeFrame({ jsonrpc: "2.0", id: request.id, result }));
      }
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });

  const browser = await connectOpenBrowserUse({ socketPath });
  try {
    const tab = await browser.newTab();
    assert.deepEqual(await tab.getPresentation(),{backend:"chrome",selected:false,visible:false,windowFocused:true});
    await tab.goto("https://example.test/issues", { waitUntil: "domcontentloaded", timeoutMs: 1000 });
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 1000 });
    assert.equal(await tab.playwright.domSnapshot(), 'group "Form"\n  button "Submit"\n  frame "https://child.test/"\n    button "Frame action"\n    frame "https://nested.test/"\n      button "Nested action"');
    ownerAvailable = false;
    assert.match(await tab.playwright.domSnapshot(), /\[frame placement unavailable\]\nframe "https:\/\/child.test\/"\nbutton "Frame action"/);
    assert.equal((await tab.getAXState()).nodes[1].name.value, "Submit");
    assert.deepEqual(await tab.getScreenshot(), pngFixture);
    assert.ok(calls.some(([method,command])=>method === "executeCdp" && command === "Page.getFrameTree"));
  } finally {
    browser.close();
    server.close();
    await new Promise((resolve) => server.once("close", resolve));
    await rm(directory, { recursive: true, force: true });
  }
});

test("sends file chooser wrapper requests", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-sdk-js-"));
  const socketPath = join(directory, "obu.sock");
  const server = createServer((socket) => {
    socket.once("data", (chunk) => {
      const length = endianness() === "LE" ? chunk.readUInt32LE(0) : chunk.readUInt32BE(0);
      const request = JSON.parse(chunk.subarray(4, 4 + length).toString("utf8"));
      assert.equal(request.method, "waitForFileChooser");
      assert.equal(request.params.tabId, 123);
      socket.write(
        encodeFrame({
          jsonrpc: "2.0",
          id: request.id,
          result: { fileChooserId: "chooser-1", isMultiple: false }
        })
      );
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });

  const client = new OpenBrowserUseClient({ socketPath });
  try {
    assert.deepEqual(await client.waitForFileChooser(123), {
      fileChooserId: "chooser-1",
      isMultiple: false
    });
  } finally {
    client.close();
    server.close();
    await new Promise((resolve) => server.once("close", resolve));
    await rm(directory, { recursive: true, force: true });
  }
});

test("sends download and clipboard wrapper requests", async () => {
  const directory = await mkdtemp(join(tmpdir(), "obu-sdk-js-"));
  const socketPath = join(directory, "obu.sock");
  const expected = [
    ["waitForDownload", { tabId: 123, timeoutMs: 5000 }],
    ["downloadPath", { downloadId: "download-1" }],
    ["readClipboardText", { tabId: 123 }],
    ["writeClipboardText", { tabId: 123, text: "hello" }]
  ];
  const server = createServer((socket) => {
    let index = 0;
    socket.on("data", (chunk) => {
      const length = endianness() === "LE" ? chunk.readUInt32LE(0) : chunk.readUInt32BE(0);
      const request = JSON.parse(chunk.subarray(4, 4 + length).toString("utf8"));
      const [method, params] = expected[index++];
      assert.equal(request.method, method);
      assert.deepEqual(
        Object.fromEntries(Object.entries(params).map(([key, value]) => [key, request.params[key]])),
        params
      );
      socket.write(encodeFrame({ jsonrpc: "2.0", id: request.id, result: {} }));
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });

  const client = new OpenBrowserUseClient({ socketPath });
  try {
    await client.waitForDownload(123, 5000);
    await client.downloadPath("download-1");
    await client.readClipboardText(123);
    await client.writeClipboardText(123, "hello");
    assert.equal(expected.length, 4);
  } finally {
    client.close();
    server.close();
    await new Promise((resolve) => server.once("close", resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
