import electron from 'electron';
import { fileURLToPath } from 'node:url';
import { IabRuntime } from './runtime.js';
import type { VisualFeedbackOptions } from './feedback.js';
export type { VisualFeedbackOptions } from './feedback.js';
export { IabRuntime, IabScope } from './runtime.js';
export type { GrantOptions, Operation, Bootstrap } from './transport.js';
export function createIabRuntime(options: { appId: string; visualFeedback?: VisualFeedbackOptions }): IabRuntime {
  if (!electron.app?.isReady()) throw new Error('createIabRuntime must run in Electron main after app.whenReady()');
  const webMcpPreload=fileURLToPath(new URL('./webmcp-preload.cjs',import.meta.url));
  const runtime = new IabRuntime({
    webMcpPreload,
    createSession: partition => electron.session.fromPartition(partition),
    createView: (session, contents, webmcp) => new electron.WebContentsView({
      ...(contents ? { webContents: contents } : {}),
      webPreferences: { session, ...(webmcp ? {preload:webMcpPreload} : {}), sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, webviewTag: false },
    }),
    ...(typeof electron.ClipboardItem === 'function' && typeof electron.clipboard?.read === 'function' ? {clipboard: {
      readText: () => electron.clipboard.readText(),
      writeText: (text: string) => electron.clipboard.writeText(text),
      read: () => electron.clipboard.read(),
      write: (items: Array<Record<string,Blob>>) => electron.clipboard.write(items.map(item => new electron.ClipboardItem(item))),
    }} : {}),
  }, options.appId,options.visualFeedback);
  return runtime;
}
