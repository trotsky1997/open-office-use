#!/usr/bin/env node
import { runReplMcp } from 'open-browser-use-sdk/repl';
import { connectPrivateIab } from './client.js';

void (async () => {
  const args = process.argv.slice(2);
  if (args.some(arg => arg !== '--allow-extension-discovery') || args.length > 1) throw new Error('Unknown REPL option');
  const connection = await connectPrivateIab();
  await runReplMcp(async () => connection.browser(), () => connection.close(), {allowExtensionDiscovery: args.includes('--allow-extension-discovery')});
})().catch(error => { console.error(error); process.exitCode = 1; });
