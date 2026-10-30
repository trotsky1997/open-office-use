# Open Office Use

[English](README.md) · [简体中文](README.zh-CN.md)

面向 Agent 和用户的本地 Office 创作工具，支持通过 CLI、本地 MCP 服务和带版本的浏览器界面创建、读取、编辑和审阅 DOCX、XLSX、PPTX。项目仍处于早期阶段，具体能力与保真限制见 [Office 使用指南](office/README.md)。

- **Agent 接口：**提供结构化读取、定点编辑、表格网格、搜索、渲染与视觉审阅工具，以及按文档类型组织的 [Agent skill](skills/open-office-use/SKILL.md)。
- **版本化草稿：**从已保存的文件或空白文档开始，创建、比较和恢复版本，再导出到新文件。
- **视觉审阅：**渲染 PDF 和页面图片；本地查看器支持版本预览、区域选择和部分编辑操作。
- **结构化操作：**调用已安装的 [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI)，查询可用属性并执行更丰富的文档操作。

## 快速开始

需要 Python 3.10 或更高版本。在仓库目录中运行：

```sh
python3 -m pip install './office[mcp]'
office-use doctor
```

创建并检查一个简单的 Word 文档：

```sh
printf '%s\n' '{"paragraphs":["Hello, Office!"]}' > hello.json
office-use author --spec hello.json --out hello.docx
office-use inspect hello.docx
```

输出路径需要是新路径。`doctor` 会报告可选系统依赖：OfficeCLI 用于结构化操作，LibreOffice 用于 PDF 渲染，Poppler 用于页面图片与选区文本提取。按所需功能分别安装；详细命令和格式限制见 [Office 使用指南](office/README.md)。

## Agent 接入

单独安装 skill：

```sh
npx skills add trotsky1997/open-office-use -g -a codex --skill open-office-use -y
```

在支持本地 stdio MCP 的客户端中配置，例如 Codex：

```toml
[mcp_servers.open_office_use]
command = "office-use"
args = ["mcp"]
```

服务以自身进程权限访问本地文件，请在可信环境中配置。[Office 使用指南](office/README.md#mcp-for-agents) 列出了工具以及版本、渲染和保真方面的限制。

## 项目来源

本项目 fork 自 [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use)，仓库中保留了上游浏览器工具及其[英文](BROWSER.md)和[中文](BROWSER.zh-CN.md)说明。Office 部分也参考了 [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) 和 [GenOffice](https://github.com/genspark-ai/genoffice)。

[MIT 许可证](LICENSE)
