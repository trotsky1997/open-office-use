# Open Browser Use

> This branch is the [open-office-use fork](https://github.com/trotsky1997/open-office-use/tree/codex/browser-harness), based on [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use). Its newer browser harness is available from this source tree. The npm, PyPI, Homebrew and Chrome Web Store links below refer to upstream releases and may contain different code.

[![English](https://img.shields.io/badge/English-Click-yellow)](./README.md)
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-orange)](./README.zh-CN.md)
[![Release](https://img.shields.io/github/v/release/iFurySt/open-browser-use)](https://github.com/iFurySt/open-browser-use/releases)
[![npm SDK](https://img.shields.io/npm/v/open-browser-use-sdk?label=npm%20SDK)](https://www.npmjs.com/package/open-browser-use-sdk)
[![PyPI SDK](https://img.shields.io/pypi/v/open-browser-use-sdk?label=PyPI%20SDK)](https://pypi.org/project/open-browser-use-sdk/)
[![Go SDK](https://pkg.go.dev/badge/github.com/ifuryst/open-browser-use/packages/open-browser-use-go.svg)](https://pkg.go.dev/github.com/ifuryst/open-browser-use/packages/open-browser-use-go)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/iFurySt/open-browser-use)

---

> [!TIP]
> Interested in Computer Use? Check out [open-computer-use](https://github.com/iFurySt/open-codex-computer-use).

`open-browser-use` is a browser automation layer that stays neutral across
agent runtimes. It is also an open-source alternative to the Chrome Browser Use
capability recently shipped in Codex.app. For the story behind it, see the
[Browser Use Deep Dive](https://www.ifuryst.com/en/blog/2026/open-browser-use/).

Under the hood, it pairs a browser extension with the `open-browser-use` CLI.
You can integrate it through the JavaScript SDK, Python SDK, Go SDK, or the CLI.

For an embedded Electron browser, the workspace now includes
[`open-browser-use-electron`](packages/open-browser-use-electron/README.md):
multi-tab task scopes, named profiles, private tool channels and authenticated
local sockets. Run `pnpm install && pnpm example:iab` to try the
[reference app](examples/electron-iab/README.md), or `pnpm smoke:iab` for real
Electron integration checks. This source feature is not yet published to npm.

https://github.com/user-attachments/assets/bcfba878-f6a8-44b9-b84b-29c7e0285687

## Run this branch from source

Requirements: Node.js 22+, pnpm 8.15.9, Go 1.25.10+ and a native C++ build
toolchain for the Electron workspace dependency. From a checkout of the
`codex/browser-harness` branch:

```bash
git clone --branch codex/browser-harness https://github.com/trotsky1997/open-office-use.git
cd open-office-use
pnpm install --frozen-lockfile
pnpm --filter open-browser-use-sdk build
mkdir -p build
go build -o build/open-browser-use ./cmd/open-browser-use
```

For Chrome, open `chrome://extensions`, enable Developer mode, choose **Load
unpacked**, and select this checkout's `apps/chrome-extension` directory.
Copy the resulting extension ID and register the source-built native host:

```bash
./build/open-browser-use install-manifest --extension-id YOUR_EXTENSION_ID --path "$PWD/build/open-browser-use"
```

Reload the unpacked extension and check `./build/open-browser-use ping`. The
registration updates the browser's Open Browser Use native-host manifest and
stable host link, so an existing installation using that host name will use
this binary and extension ID. Keep the checkout and binary at their paths; if
the unpacked extension ID changes, register it again. Use `--browser` to
select a supported non-default browser. Windows registration is present in
the source and has not yet received end-to-end validation.

For a Chromium instance launched with a custom `--user-data-dir`, its native
host lookup can use that directory instead of the standard browser location.
On macOS or Linux, register directly into that directory with the same command
and an additional flag:

```bash
--output "/absolute/path/to/user-data/NativeMessagingHosts/com.ifuryst.open_browser_use.extension.json"
```

This also updates the stable host link. Verify the lookup location for the
specific browser build and profile you run.

Configure the persistent JavaScript MCP with the absolute path to the built
file:

```toml
[mcp_servers.open_browser_use_repl]
command = "node"
args = ["/absolute/path/to/open-office-use/packages/open-browser-use-js/dist/repl-cli.js"]
```

Use the [local skill](skills/open-browser-use/SKILL.md) and the
[SDK guide](packages/open-browser-use-js/README.md) for browser discovery,
interaction and cleanup. For embedded Electron, follow the
[host integration guide](packages/open-browser-use-electron/README.md); it
provides its own authorized REPL connection.

## Upstream published packages

```bash
npm i -g open-browser-use
open-browser-use setup
```

### Install the CLI

```bash
# npm (macOS, Linux, Windows)
npm i -g open-browser-use

# Homebrew (macOS, Linux)
brew tap iFurySt/open-browser-use && brew install open-browser-use

# Upgrade
npm update -g open-browser-use
```

### Set Up Chrome

Register the native host for the extension. The setup command also opens the
Chrome Web Store page so you can install or enable the matching Chrome
extension, then restart Chrome if needed.

```bash
open-browser-use setup
```

If the Chrome Web Store item is temporarily unavailable, use
`open-browser-use setup beta` to prepare a keyed release ZIP for manual
installation from `chrome://extensions/`.

To use an extension ZIP that is already available locally, pass its path
directly to setup. This skips the GitHub Release download while keeping the
same keyed manual-install flow:

```bash
open-browser-use setup --zip /absolute/path/to/open-browser-use-chrome-extension.zip
```

### Use It

#### SDK

```bash
# JavaScript / TypeScript
npm install open-browser-use-sdk

# Python
pip install open-browser-use-sdk

# Go
go get github.com/ifuryst/open-browser-use/packages/open-browser-use-go
```

The SDK package name is `open-browser-use-sdk` on both npm and PyPI. Python
code imports it as `open_browser_use`; Go code imports the SDK package as
`obu`.

#### Skill

Install the skill directly:

```bash
# Install for Codex
npx skills add iFurySt/open-browser-use -g -a codex --skill open-browser-use -y
npx skills ls -g -a codex | rg 'open-browser-use'
codex exec --skip-git-repo-check "Use open-browser-use to check today’s Hacker News and summarize the most worth-reading posts."

# Install for Claude Code
npx skills add iFurySt/open-browser-use -g -a claude-code --skill open-browser-use -y
```

Update an existing global install, including the Codex install created above:

```bash
npx skills update open-browser-use -g -y

# `upgrade` is an alias for `update`
npx skills upgrade open-browser-use -g -y
```

You can also manually download and install the
[`open-browser-use` skill](./skills/open-browser-use), then start using it from
your agent.

Downloadable `.skill` and `.zip` packages are available in
[GitHub Releases](https://github.com/iFurySt/open-browser-use/releases).

#### MCP

Install the MCP server into all supported global agent configs:

```bash
npx add-mcp "obu mcp" --name open_browser_use --all -g -y
npx add-mcp list -g
```

You can also configure an agent runtime with local MCP stdio support manually:

```toml
[mcp_servers.open_browser_use]
command = "obu"
args = ["mcp"]
```

The server exposes browser tools for tab listing, opening, claiming,
navigation, CDP, action plans, and cleanup.

For a persistent JavaScript session with text and image output, the JavaScript
SDK also includes [`obu-repl-mcp`](packages/open-browser-use-js/README.md#persistent-javascript-mcp).
It executes local Node.js code and is intended for trusted MCP clients.

For an embedded Electron browser, use the host-authorized **`obu iab mcp`**
route instead. See the [Electron IAB MCP integration](packages/open-browser-use-electron/README.md#iab-mcp-for-agents)
for private/socket authorization, tools and managed stdio setup.

## License

[MIT](./LICENSE)
