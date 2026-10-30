# Open Office Use

[English](README.md) · [简体中文](README.zh-CN.md)

A local Office authoring harness for agents and people. Create, inspect, edit and review DOCX, XLSX and PPTX files through a CLI, a local MCP server and a revision-aware browser viewer. This is an early project; supported operations and fidelity limits are documented in the [Office guide](office/README.md).

- **Agent interface:** MCP tools for structured inspection, targeted edits, spreadsheet grids, search, rendering and visual review. An [agent skill](skills/open-office-use/SKILL.md) provides format-specific guidance.
- **Versioned drafts:** work from a saved file or a blank document, create revisions, compare and restore them, and export to a new file.
- **Visual review:** render to PDF and page images; the local viewer offers revision previews, selections and selected editing controls.
- **Structured operations:** use the installed [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) for richer document operations and schema discovery.

## Quick start

Python 3.10+ is required. From a clone of this repository:

```sh
python3 -m pip install './office[mcp]'
office-use doctor
```

Create and inspect a small Word document:

```sh
printf '%s\n' '{"paragraphs":["Hello, Office!"]}' > hello.json
office-use author --spec hello.json --out hello.docx
office-use inspect hello.docx
```

Output paths must be new. The `doctor` report identifies optional system dependencies: OfficeCLI for structured operations, LibreOffice for PDF rendering, and Poppler for page images and selected-text extraction. Install those separately for the workflows you need. See [installation and usage](office/README.md) for commands and format-specific limits.

## Agent setup

Install the skill separately:

```sh
npx skills add trotsky1997/open-office-use -g -a codex --skill open-office-use -y
```

For a local stdio MCP client, such as Codex:

```toml
[mcp_servers.open_office_use]
command = "office-use"
args = ["mcp"]
```

The server accesses local files with its process permissions. Configure it in a trusted environment. The [Office guide](office/README.md#mcp-for-agents) lists the tools and explains revision, rendering and fidelity constraints.

## Project history

Forked from [iFurySt/open-browser-use](https://github.com/iFurySt/open-browser-use). The inherited browser tooling is still in this checkout; see its [English](BROWSER.md) and [Chinese](BROWSER.zh-CN.md) documentation. Office work also draws on [OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) and [GenOffice](https://github.com/genspark-ai/genoffice).

[MIT license](LICENSE)
