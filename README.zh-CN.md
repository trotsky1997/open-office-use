# Open Browser Use

> 本分支是基于 [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use) 的 [open-office-use fork](https://github.com/trotsky1997/open-office-use/tree/codex/browser-harness)。新版 browser harness 从本分支源码构建；下方 npm、PyPI、Homebrew 和 Chrome Web Store 链接指向上游发布版本，代码可能不同。

[![English](https://img.shields.io/badge/English-Click-yellow)](./README.md)
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-orange)](./README.zh-CN.md)
[![Release](https://img.shields.io/github/v/release/iFurySt/open-browser-use)](https://github.com/iFurySt/open-browser-use/releases)
[![npm SDK](https://img.shields.io/npm/v/open-browser-use-sdk?label=npm%20SDK)](https://www.npmjs.com/package/open-browser-use-sdk)
[![PyPI SDK](https://img.shields.io/pypi/v/open-browser-use-sdk?label=PyPI%20SDK)](https://pypi.org/project/open-browser-use-sdk/)
[![Go SDK](https://pkg.go.dev/badge/github.com/ifuryst/open-browser-use/packages/open-browser-use-go.svg)](https://pkg.go.dev/github.com/ifuryst/open-browser-use/packages/open-browser-use-go)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/iFurySt/open-browser-use)

---

> [!TIP]
> 对 Computer Use 感兴趣的话，可以看看 [open-computer-use](https://github.com/iFurySt/open-codex-computer-use)。

`open-browser-use` 是平台中立的浏览器操作方案，也是Codex.app最新发布的Chrome Browser Use的开源替代方案。背后的故事可以看这篇[Browser Use详解](https://www.ifuryst.com/blog/2026/open-browser-use/)文章。 技术方案采用的是浏览器插件和open-browser-use cli结合，可通过 JS/Python/Go SDK 或 CLI 的方式接入。

Electron app 可以接入仓库中的
[`open-browser-use-electron`](packages/open-browser-use-electron/README.md)，
支持会话多 tab、命名 profile、私有通道、经过鉴权的 socket 和 `obu iab`
命令。运行 `pnpm install && pnpm example:iab` 启动
[参考 app](examples/electron-iab/README.md)，`pnpm smoke:iab` 执行真实 Electron
集成验证。该首版功能已落源码，尚未发布 npm 包。

https://github.com/user-attachments/assets/bcfba878-f6a8-44b9-b84b-29c7e0285687

## 从本分支源码运行

需要 Node.js 22+、pnpm 8.15.9、Go 1.25.10+ 和用于 Electron 工作区依赖的本地 C++ 构建工具。在 `codex/browser-harness`
分支的工作目录中执行：

```bash
git clone --branch codex/browser-harness https://github.com/trotsky1997/open-office-use.git
cd open-office-use
pnpm install --frozen-lockfile
pnpm --filter open-browser-use-sdk build
mkdir -p build
go build -o build/open-browser-use ./cmd/open-browser-use
```

打开 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，
加载本工作目录的 `apps/chrome-extension`。复制扩展 ID，注册源码构建的 host：

```bash
./build/open-browser-use install-manifest --extension-id YOUR_EXTENSION_ID --path "$PWD/build/open-browser-use"
```

重新加载扩展，再用 `./build/open-browser-use ping` 检查连接。注册会更新浏览器的
Open Browser Use 原生 host 清单和稳定链接，使用同一 host 名称的已有安装会切换到
此二进制文件和扩展 ID。请保留工作目录与二进制文件路径；扩展 ID 变化后重新注册。
可通过 `--browser` 选择受支持的其他浏览器。Windows 注册代码已有实现，端到端验证待完成。

使用自定义 `--user-data-dir` 启动的 Chromium 实例可能从该目录查找 native host，
而标准注册路径对应默认浏览器位置。macOS 或 Linux 上可在上述命令后增加：

```bash
--output "/absolute/path/to/user-data/NativeMessagingHosts/com.ifuryst.open_browser_use.extension.json"
```

此操作同样会更新稳定 host 链接；请核对所用浏览器及配置目录的实际查找位置。

持久 JavaScript MCP 可使用构建产物的绝对路径配置：

```toml
[mcp_servers.open_browser_use_repl]
command = "node"
args = ["/absolute/path/to/open-office-use/packages/open-browser-use-js/dist/repl-cli.js"]
```

浏览器发现、操作和清理方法见 [SDK 指南](packages/open-browser-use-js/README.md)
与[本地 skill](skills/open-browser-use/SKILL.md)。Electron 内嵌场景使用
[宿主接入指南](packages/open-browser-use-electron/README.md)配置授权连接。

## 上游发布版本
第一次安装可以无脑运行：
```bash
npm i -g open-browser-use
open-browser-use setup
```

### 安装 CLI
```bash
# npm安装（macOS、Linux、Windows）
npm i -g open-browser-use

# Homebrew安装（macOS、Linux）
brew tap iFurySt/open-browser-use && brew install open-browser-use

# 升级
npm update -g open-browser-use
```

### 配置 Chrome
注册绑定到该插件的 native host。setup 也会打开 Chrome Web Store 页面，你需要在
页面里安装或启用对应的浏览器插件，必要时再重启 Chrome。

```bash
open-browser-use setup
```

如果 Chrome Web Store 暂时不可用，可以运行 `open-browser-use setup beta`
准备带固定 key 的 release ZIP，再到 `chrome://extensions/` 手动安装。

如果本地已经有扩展 ZIP，可以直接把路径传给 setup。该方式不会从 GitHub Release
下载插件包，仍会准备带固定 key 的手动安装包：

```bash
open-browser-use setup --zip /absolute/path/to/open-browser-use-chrome-extension.zip
```

### 使用

#### SDK

```bash
# JavaScript / TypeScript
npm install open-browser-use-sdk

# Python
pip install open-browser-use-sdk

# Go
go get github.com/ifuryst/open-browser-use/packages/open-browser-use-go
```

SDK 在 npm 和 PyPI 上统一叫 `open-browser-use-sdk`。Python 代码里的 import
模块名保持 `open_browser_use`；Go 代码通常把 SDK import 为 `obu`。

#### Skill

一键安装 skill：

```bash
# 安装到codex
npx skills add iFurySt/open-browser-use -g -a codex --skill open-browser-use -y
npx skills ls -g -a codex | rg 'open-browser-use'
codex exec --skip-git-repo-check "用open-browser-use查看下今天Hacker News有什么值得关注的"

# 安装到claude code
npx skills add iFurySt/open-browser-use -g -a claude-code --skill open-browser-use -y
```

更新已有的全局安装，包括上面安装到 Codex 的那份：

```bash
npx skills update open-browser-use -g -y

# `upgrade` 是 `update` 的别名
npx skills upgrade open-browser-use -g -y
```

也可以手动下载`open-browser-use`的[skill](./skills/open-browser-use)并安装，就可以愉快的开始使用了🚀

*[GitHub Releases](https://github.com/iFurySt/open-browser-use/releases)里有可下载的.skill/.zip包*

#### MCP

一键安装 MCP server 到所有支持的全局 Agent 配置：

```bash
npx add-mcp "obu mcp" --name open_browser_use --all -g -y
npx add-mcp list -g
```

也可以手动配置到支持本地 stdio MCP 的 Agent runtime：

```toml
[mcp_servers.open_browser_use]
command = "obu"
args = ["mcp"]
```

这个 MCP server 会暴露标签页列表、打开/接管标签页、导航、CDP、action plan
和清理等浏览器工具。

嵌入 Electron 的浏览器使用宿主授权的 **`obu iab mcp`**，接法与上面的
Chrome MCP 配置不同。私有通道/socket 鉴权、工具列表和受管理 stdio 示例见
[Electron IAB MCP 接入](packages/open-browser-use-electron/README.md#iab-mcp-for-agents)。

## License

[MIT](./LICENSE)
