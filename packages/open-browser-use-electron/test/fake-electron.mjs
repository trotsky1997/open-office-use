import { EventEmitter } from 'node:events';
export function fakeElectron() {
  const sessions = new Map();
  const views = [];
  let clipboardItems=[];
  return { views, sessions,
    clipboard: {
      async readText(){return clipboardItems[0]?.['text/plain'] ? await clipboardItems[0]['text/plain'].text() : '';},
      async writeText(text){clipboardItems=[{'text/plain':new Blob([text])}];},
      async read(){return clipboardItems.map(item=>({types:Object.keys(item),getType:async type=>item[type]}));},
      async write(items){clipboardItems=items;},
    },
    createSession(partition) {
      if (!sessions.has(partition)) sessions.set(partition, Object.assign(new EventEmitter(), {
        isPersistent: () => partition.startsWith('persist:'), setPermissionRequestHandler() {}, setPermissionCheckHandler() {},
      }));
      return sessions.get(partition);
    },
    createView(session, contents) {
      const debuggerApi = Object.assign(new EventEmitter(), {
        attached: false, attach() { this.attached = true; }, isAttached() { return this.attached; },
        detach() { this.attached = false; this.emit('detach'); },
        commands: [], async sendCommand(method, params, sessionId) { this.commands.push({ method, params, ...(sessionId ? {sessionId} : {}) }); return {}; },
      });
      const wc = contents ?? Object.assign(new EventEmitter(), {
        session, debugger: debuggerApi, url: 'about:blank', destroyed: false, backgroundThrottling: true,
        setBackgroundThrottling(value) { this.backgroundThrottling = value; },
        getTitle() { return this.url; }, getURL() { return this.url; }, isDestroyed() { return this.destroyed; },
        async loadURL(url) { this.url = url; }, close() { this.destroyed = true; this.emit('destroyed'); },
        isolatedCalls: [], async executeJavaScriptInIsolatedWorld(worldId,scripts) { this.isolatedCalls.push({worldId,scripts}); return true; },
        setWindowOpenHandler(handler) { this.popup = handler; },
      });
      const view = { webContents: wc, setBounds(bounds) { this.bounds = bounds; }, setVisible(visible) { this.visible = visible; } };
      views.push(view); return view;
    },
  };
}
