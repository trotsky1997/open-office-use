import { randomBytes, randomUUID, createHash, timingSafeEqual } from 'node:crypto';
import { createServer, type Server, type Socket } from 'node:net';
import { mkdtemp, chmod, lstat, rmdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { performance } from 'node:perf_hooks';
import type { Duplex } from 'node:stream';
import { FramedChannel, type Message } from './wire.js';
import { processIdentity, peerIdentity, sameIdentity, type ProcessIdentity } from './peer.js';

const publicErrors = new Set([
  'IAB_INPUT_PREPARATION_TIMEOUT', 'IAB_INPUT_OUTCOME_UNKNOWN', 'IAB_BACKGROUND_SCROLL_TIMEOUT', 'IAB_SCREENSHOT_TIMEOUT',
  'IAB_SCROLL_REQUIRES_PRESENTED_SURFACE', 'IAB_BACKGROUND_SCROLL_UNSUPPORTED_GESTURE',
  'IAB_SCREENSHOT_TOO_LARGE', 'IAB_OPERATION_DENIED', 'IAB_AUTH_REVOKED', 'IAB_SCOPE_CLOSED',
  'Frame tree changed while waiting for file chooser', 'File chooser debugger detached',
  'File chooser tab closed', 'Timed out waiting for file chooser',
  'File chooser is unavailable', 'Upload file is not authorized',
  'IAB_DOWNLOAD_NOT_CONFIGURED', 'IAB_DOWNLOAD_WAIT_PENDING', 'IAB_DOWNLOAD_UNAVAILABLE',
  'IAB_DOWNLOAD_SIZE_LIMIT', 'IAB_DOWNLOAD_LIMIT', 'IAB_DOWNLOAD_FAILED',
  'IAB_DOWNLOAD_TIMEOUT', 'IAB_DOWNLOAD_TAB_CLOSED',
]);

export type Operation = 'tabs.read' | 'tabs.create' | 'page.control' | 'files.upload' | 'files.download';
export type IabEvent = { scopeId: string; method: string; params: Record<string, any> };
export interface Backend {
  readonly instanceId: string;
  hasScope(id: string): boolean;
  dispatch(scope: string, method: string, params: Record<string, any>, operations: readonly Operation[], authorized?: () => boolean, signal?: AbortSignal): Promise<any>;
  subscribe(handler: (event: IabEvent) => void): () => void;
}
export type Bootstrap = {
  authVersion: 1; transport: 'private' | 'socket'; instanceId: string; scopeId: string;
  grantId: string; secret: string; endpoint?: string; serverIdentity?: ProcessIdentity;
};
type Grant = {
  id: string; scope: string; transport: Bootstrap['transport']; peer?: ProcessIdentity;
  operations: Operation[]; hash: Buffer; deadline: number; timer: NodeJS.Timeout;
  channels: Set<FramedChannel>; maxConnections: number; abort: AbortController;
};
export type GrantOptions = { ttlMs: number; operations?: Operation[]; maxConnections?: number };
const hash = (secret: string): Buffer => createHash('sha256').update(secret).digest();

export class IabConnections {
  private grants = new Map<string, Grant>();
  private channels = new Set<FramedChannel>();
  private server?: Server;
  private endpoint?: string;
  private root?: string;
  private rootIdentity?: { dev: number; ino: number };
  private closed = false;
  private opening?: Promise<string>;
  private disposing?: Promise<void>;
  constructor(private backend: Backend) {}

  async openSocket(): Promise<string> {
    if (this.closed) throw new Error('IAB_DISPOSED');
    if (this.endpoint) return this.endpoint;
    if (!this.opening) this.opening = this.startSocket().finally(() => { this.opening = undefined; });
    return this.opening;
  }
  private async startSocket(): Promise<string> {
    const identity = processIdentity(); // Required before opening any listener.
    this.root = await mkdtemp(join(tmpdir(), 'obu-iab-'));
    await chmod(this.root, 0o700);
    const dir = await lstat(this.root);
    if (!dir.isDirectory() || dir.isSymbolicLink() || dir.uid !== identity.uid || (dir.mode & 0o777) !== 0o700) throw new Error('AUTH_UNAVAILABLE: unsafe runtime directory');
    this.rootIdentity = { dev: dir.dev, ino: dir.ino };
    const endpoint = join(this.root, 'rpc.sock');
    if (Buffer.byteLength(endpoint) > 100) { await this.cleanupDirectory(); throw new Error('AUTH_UNAVAILABLE: socket path is too long'); }
    const server = createServer({ pauseOnConnect: true }, socket => this.accept(socket));
    this.server = server;
    try {
      await new Promise<void>((resolve, reject) => {
        server.once('error', reject);
        server.listen(endpoint, () => { server.removeListener('error', reject); resolve(); });
      });
      server.on('error', () => { void this.dispose(); });
      await chmod(endpoint, 0o600);
      if (this.closed) throw new Error('IAB_DISPOSED');
      this.endpoint = endpoint; return endpoint;
    } catch (error) {
      await new Promise<void>(resolve => server.close(() => resolve()));
      this.server = undefined; await this.cleanupDirectory(); throw error;
    }
  }
  private accept(socket: Socket): void {
    try {
      if (this.closed || this.channels.size >= 128) throw new Error('Connection limit');
      const peer = peerIdentity(socket);
      if (![...this.grants.values()].some(g => g.transport === 'socket' && this.valid(g) && g.peer && sameIdentity(g.peer, peer))) throw new Error('Unknown peer');
      this.bind(socket, { peer }); socket.resume();
    } catch { socket.destroy(); }
  }
  grant(scopeId: string, transport: Bootstrap['transport'], options: GrantOptions, pid?: number): Bootstrap {
    if (this.closed || !this.backend.hasScope(scopeId)) throw new Error('IAB_SCOPE_CLOSED');
    if (!Number.isFinite(options.ttlMs) || options.ttlMs <= 0 || options.ttlMs > 86_400_000) throw new Error('ttlMs must be between 1 and 86400000');
    if (this.grants.size >= 256) throw new Error('IAB_GRANT_LIMIT');
    const operations = options.operations ?? ['tabs.read', 'tabs.create', 'page.control'];
    if (operations.some(op => !['tabs.read', 'tabs.create', 'page.control', 'files.upload', 'files.download'].includes(op))) throw new Error('Unsupported operation');
    const maxConnections = options.maxConnections ?? 1;
    if (!Number.isInteger(maxConnections) || maxConnections < 1 || maxConnections > 16) throw new Error('Invalid maxConnections');
    const peer = transport === 'socket' ? processIdentity(pid) : undefined;
    if (transport === 'socket' && (!this.endpoint || !pid)) throw new Error('Open the socket and register a client PID first');
    const id = randomUUID(), secret = randomBytes(32).toString('base64url');
    const grant: Grant = {
      id, scope: scopeId, transport, peer, operations: [...operations], hash: hash(secret),
      deadline: performance.now() + options.ttlMs, channels: new Set(), maxConnections, abort: new AbortController(),
      timer: setTimeout(() => this.revoke(id), options.ttlMs),
    };
    grant.timer.unref(); this.grants.set(id, grant);
    return {
      authVersion: 1, transport, instanceId: this.backend.instanceId, scopeId, grantId: id, secret,
      ...(transport === 'socket' ? { endpoint: this.endpoint, serverIdentity: processIdentity() } : {}),
    };
  }
  servePrivate(stream: Duplex, scopeId: string, options: GrantOptions): { grantId: string; revoke: () => void } {
    const bootstrap = this.grant(scopeId, 'private', options);
    const channel = this.bind(stream, { privateGrantId: bootstrap.grantId });
    channel.send({ jsonrpc: '2.0', method: 'iab.bootstrap', params: bootstrap });
    return { grantId: bootstrap.grantId, revoke: () => this.revoke(bootstrap.grantId) };
  }
  revoke(id: string): void {
    const grant = this.grants.get(id);
    if (!grant) return;
    this.grants.delete(id); clearTimeout(grant.timer); grant.abort.abort();
    for (const channel of grant.channels) channel.close();
    grant.channels.clear();
  }
  revokeScope(scope: string): void { for (const g of [...this.grants.values()]) if (g.scope === scope) this.revoke(g.id); }
  private valid(grant: Grant): boolean {
    return !this.closed && this.grants.get(grant.id) === grant && performance.now() < grant.deadline && this.backend.hasScope(grant.scope);
  }
  private bind(stream: Duplex, source: { peer?: ProcessIdentity; privateGrantId?: string }): FramedChannel {
    const channel = new FramedChannel(stream);
    this.channels.add(channel);
    const privateGrant = source.privateGrantId ? this.grants.get(source.privateGrantId) : undefined;
    privateGrant?.channels.add(channel);
    let grant: Grant | undefined, inFlight = 0;
    let unsubscribe: (() => void) | undefined;
    const timeout = setTimeout(() => channel.close(), 5000); timeout.unref();
    channel.on('closed', () => {
      clearTimeout(timeout); unsubscribe?.(); grant?.channels.delete(channel); privateGrant?.channels.delete(channel); this.channels.delete(channel);
      if (source.privateGrantId) this.revoke(source.privateGrantId);
    });
    channel.on('message', (message: Message) => {
      if (!grant) {
        const p = message.params;
        const candidate = p && typeof p.grantId === 'string' ? this.grants.get(p.grantId) : undefined;
        const ok = message.method === 'auth.connect' && (typeof message.id === 'string' || typeof message.id === 'number') &&
          p?.authVersion === 1 && p.instanceId === this.backend.instanceId && candidate && this.valid(candidate) &&
          typeof p.secret === 'string' && /^[A-Za-z0-9_-]{43}$/.test(p.secret) &&
          timingSafeEqual(candidate.hash, hash(p.secret)) &&
          candidate.channels.size - (candidate.channels.has(channel) ? 1 : 0) < candidate.maxConnections &&
          (candidate.transport === 'private'
            ? source.privateGrantId === candidate.id
            : source.peer && candidate.peer && sameIdentity(source.peer, candidate.peer));
        if (!ok) { channel.close(); return; }
        grant = candidate;
        grant.channels.add(channel); clearTimeout(timeout); channel.maxFrame = 8 * 1024 * 1024;
        channel.send({ jsonrpc: '2.0', id: message.id, result: { authenticated: true, scopeId: grant.scope } });
        unsubscribe = this.backend.subscribe(event => {
          if (grant && this.valid(grant) && event.scopeId === grant.scope &&
              (['onFileChooserWaitReady','onDownloadWaitReady'].includes(event.method) ? grant.operations.includes(event.method === 'onFileChooserWaitReady' ? 'files.upload' : 'files.download') && grant.operations.includes('page.control') : grant.operations.includes(['onCDPEvent','onDebuggerDetach'].includes(event.method) ? 'page.control' : 'tabs.read'))) {
            channel.send({ jsonrpc: '2.0', method: event.method, params: event.params });
          }
        });
        return;
      }
      if (!this.valid(grant) || typeof message.method !== 'string' ||
          (typeof message.id !== 'string' && typeof message.id !== 'number') || inFlight >= 64) { channel.close(); return; }
      const params = message.params ?? {};
      if (typeof params !== 'object' || Array.isArray(params) || params.session_id !== grant.scope) { channel.close(); return; }
      const current = grant;
      inFlight++;
      void this.backend.dispatch(current.scope, message.method, params, current.operations, () => this.valid(current), current.abort.signal).then(result => {
        if (this.valid(current)) channel.send({ jsonrpc: '2.0', id: message.id, result });
      }, error => {
        const messageText = error instanceof Error && publicErrors.has(error.message) ? error.message : 'IAB request rejected';
        if (this.valid(current)) channel.send({ jsonrpc: '2.0', id: message.id, error: { code: -32001, message: messageText } });
      }).finally(() => { inFlight--; });
    });
    return channel;
  }
  private async cleanupDirectory(): Promise<void> {
    if (!this.root || !this.rootIdentity) return;
    const info = await lstat(this.root).catch(() => undefined);
    if (info?.dev === this.rootIdentity.dev && info.ino === this.rootIdentity.ino) {
      // Never recursively delete a directory that another same-UID process can modify.
      await rmdir(this.root).catch(() => {});
    }
  }
  dispose(): Promise<void> {
    if (!this.disposing) this.disposing = this.finishDispose();
    return this.disposing;
  }
  private async finishDispose(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    for (const id of [...this.grants.keys()]) this.revoke(id);
    for (const c of this.channels) c.close();
    if (this.opening) await this.opening.catch(() => {});
    if (this.server) await new Promise<void>(resolve => this.server!.close(() => resolve()));
    this.server = undefined; this.endpoint = undefined; await this.cleanupDirectory();
  }
}
