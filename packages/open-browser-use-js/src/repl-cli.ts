#!/usr/bin/env node
import { runReplMcp } from "./repl-mcp.js";

void runReplMcp().catch((error) => { console.error(error); process.exitCode = 1; });
