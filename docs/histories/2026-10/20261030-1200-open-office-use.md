# Open Office Use foundation

Forked the browser project locally and added an independent Python CLI for basic DOCX, XLSX and PPTX inspection, creation, copy editing and LibreOffice PDF rendering. Output creation refuses overwrites. Added an agent skill, examples and an end-to-end smoke script. The current CLI is a foundation and does not claim fidelity or feature parity with Codex office tools.

Reference review: documented GenOffice and OfficeCLI capabilities and licensing boundaries. Locally exercised OfficeCLI 1.0.147 with basic create, edit, outline and schema-validation operations for all three formats. Recorded engine evaluation and session lifecycle as next steps; no integration or fidelity claim has been made.

Added optional OfficeCLI structured reads and isolated batch authoring, with exclusive output publication and session closure. Added per-page PNG preview through LibreOffice and Poppler. Verified basic paths for all three formats, including failures and source preservation.

Added optional MCP stdio access to the office workbench with image delivery for page inspection. Verified discovery, authoring, structured reads, visual output and error propagation with the official MCP client.

Added bounded spreadsheet formula/cache inspection and explicit LibreOffice recalculation through CLI and MCP. Verified basic formulas, errors, empty ranges and source protection with a real local calculation engine.

Added bounded saved-file comparison through CLI and MCP, reporting textual excerpts and changed OOXML parts. Verified three formats and formatting-only change detection.

Added audit commands for OfficeCLI schema validation and issue checks with a saved snapshot. Validated real schema errors, formula issues and MCP access.

Added file-backed versioned draft sessions with conflict detection and export via CLI and MCP. Verified all formats, failure and concurrent write handling.

Added loopback browser preview for the latest session revision with random URL access and automatic refresh. Tested real rendering, route restrictions and Chrome revision updates.

Added revision-bound visual area selection in the session viewer and MCP access to metadata and rendered crops. Tested browser interaction, origin restrictions and stale revisions.

Added selected-region PDF text and word geometry through CLI and MCP, retaining revision and staleness context. Verified three formats and narrow-region selection.

Added text-based OfficeCLI candidate paths for visual selections with explicit uncertainty and revision context. Verified duplicate matches in three formats and stale selections.

Added historical revision restoration as a new version through CLI, MCP and the local viewer, with conflict detection. Verified all three formats, MCP and browser interaction.

Added historical revision previews to the local viewer, with latest-version status and selection restricted to current content. Verified concurrent Chrome views and restoration.

Added limited version-bound element editing in the local viewer and MCP. Verified three formats, formula mode, conflict checks and browser interaction.

Connected viewer selection to candidate lookup and explicit element loading. Verified access checks, stale/changed selection handling and browser interaction.

Added range-based spreadsheet formula, value and cache comparison through CLI and MCP. Verified real recalculation and bounded output.

Added side-by-side visual review of a historical and latest revision in the viewer, with live latest-side refresh. Verified browser interaction and two-tab updates.

Connected bounded text and OOXML part comparison to the side-by-side viewer; verified browser display and clearing on a newer revision.

Added version-bound XLSX grid editing in viewer and MCP. Verified real formula and cell changes, stale input retention and origin checks.

Added formula-range protection for array, data-table and shared formula spans during grid editing, including anchors outside the displayed range.

Added version-bound grid formatting for bold, RGB fill and number formats, with protected formula ranges and preservation of pending edits.

Extended bounded cell comparison to direct formatting, resolving workbook-local style IDs for font, fill, border, alignment, protection and number formats.

Connected bounded worksheet cell and formatting diffs to the visual revision comparison, including stale-result rejection and clearing.

Protected unsaved grid and element input during reload and navigation; stale element text remains selectable and in-flight editor actions are serialized.

Added rectangular TSV paste to the worksheet grid, with all-or-nothing bounds and formula-range checks.

Added bounded workbook-wide scanning of stored formula caches and error cells through CLI and MCP, including hidden worksheets and explicit completeness indicators.

Added versioned, run-preserving Word text replacement for simple direct-body paragraphs through CLI, MCP and the viewer, with package preservation and explicit structural rejection.

Extended run-preserving Word replacement to physical table-cell paths, nested tables and saved paragraph IDs; fixed preservation of the XML standalone declaration.

Added run-preserving PowerPoint replacement with relationship-based slide resolution, shape and group paths, and shared atomic single-part package editing.

Extended Word run-preserving replacement to ordinary hyperlinks, bookmark and comment regions, while rejecting matches crossing their boundaries.

Extended PowerPoint run-preserving replacement to table cells, merged origins, explicit paragraphs and grouped tables; table cell whole-text editing stays disabled.

Added versioned, run-preserving XLSX text-cell replacement with shared-string isolation, merged and formula-range safeguards, and atomic multi-part writes.

Added version-bound XLSX formula scanning and LibreOffice recalculation through session CLI, MCP and the viewer, with atomic publication and concurrent-write protection.

Added bounded PowerPoint off-slide and text-overlap geometric inspection, including group transforms and revision-specific viewer reports.

- Word 修订插入和替换支持已有的页眉、页脚及表格段落路径；插入结果返回修订所在部件，预览继续展示共享节影响。覆盖范围检查、跨部件修订 ID、接受与拒绝和浏览器操作。

- 增加页眉和页脚的分页文字搜索，覆盖表格、CLI、MCP 与预览；长清单后方的目标可按路径加载并检查共享节。

- 增加幻灯片渲染文字候选检查，贯通 CLI、MCP、审阅包和本地预览，报告映射与覆盖限制。

- 幻灯片渲染文字检查覆盖普通表格和合并单元格，按物理单元格返回可定位路径，并标记不支持的表格结构。

- 幻灯片渲染文字检查支持平移和缩放的嵌套组合，返回组合内文本框及表格单元格的定位路径。

- 版本化工作表网格增加字体、颜色、字号、下划线、对齐和换行设置，支持 CLI、MCP 和预览，并回读直接样式。

- 工作表网格支持读取保存的行列尺寸，并通过 CLI、MCP 与预览修改列宽和行高；验证分组列、保护和有歧义的范围。

- 工作表版本比较增加行列及默认尺寸属性，提供会话 CLI/MCP 和预览结果；记录 OfficeCLI 对公式缓存的潜在影响。

- 工作表尺寸调整改为直接更新目标 XML，保留公式缓存和其他部件，并检查行列结构与并发冲突。

- 网格格式使用 OfficeCLI 生成样式，并校验后将新增样式及目标引用合并回原文件，保留公式缓存和其他部件。

- XLSX 定向文本修改请求工作表重新计算，公式扫描和审阅包暴露请求状态；修复手动计算模式下 LibreOffice 沿用旧缓存的问题，并恢复原计算模式。

- 网格批量改值只合并目标单元格及经验证的样式，保留未修改公式缓存；新公式缓存失效并请求重算；公式变更时移除通过校验的计算链，复杂或有额外引用的链会被拒绝。

- 网格编辑新增显式文本类型，保留前导零和等号开头的文本；CLI、MCP 与浏览器均可使用，验证格式与无关公式缓存的保留。

- 网格使用多行字段并支持粘贴带引号的多行文本；浏览器检查加载、无改动判断、原值保留和批量保存。

- 网格为各单元格提供文本和自动类型覆盖，支持同批混合公式、文本及仅改变类型；版本变化时保留待提交输入并锁定控件。

- 新增 Word、Excel 和 PowerPoint 的原子批量定向文本替换，通过 CLI 和 MCP 在一次版本中顺序提交，并验证失败回滚及并发冲突。

- XLSX 单元素编辑复用网格的安全合并，保留无关公式缓存，报告重算请求并处理公式计算链；验证 MCP、界面和受保护单元格。

- XLSX 单元素编辑支持文字类型并识别已有文字；校验公式候选文本与请求一致，阻止意外改写后提交。

- XLSX 网格与单元素编辑支持可验证的动态数组元数据及常用公式，保留无关缓存和部件；实测 LibreOffice 未填充 SEQUENCE 溢出结果，目标应用互操作仍待验证。

- 公式扫描和审阅包识别动态数组元数据；LibreOffice 重算默认拦截已识别或无法检查的元数据，CLI、MCP 和界面提供明确的转换选项。

- 预览与版本比较显示动态数组渲染提示；结构化渲染结果返回元数据检查状态，帮助识别 LibreOffice 未显示完整溢出结果的情况。

- MCP 页面图、联系表、比较图和选区图同时返回图像及结构化元数据；包含动态数组预览提示、版本信息和选区状态。

- 选区文本和候选定位传播渲染提示，并报告处理完成时选区是否与起始时不同，便于判断定位结果是否仍对应当前操作。

- 渲染、预览提示及选区查询绑定同一文件快照并返回 SHA-256；预览与候选快照不一致时拒绝定位并刷新缓存。

- 已验证元数据且保存范围仅含锚点的动态数组可继续编辑或清除；多单元格溢出范围仍受保护。

- 动态公式校验支持多变量和嵌套 LET、LAMBDA 及局部函数调用，并按作用域拒绝潜在语义变化。

- Extend image-only XLSX metadata with a verified dynamic-array record, preserving existing rich-value records and rejecting pre-existing cell metadata references. Validated embedded images, subsequent anchor edits, metadata indices, and OfficeCLI package validation.

- Include the snapshot module in the installed distribution and verify an isolated installation through document creation, inspection, and an MCP handshake.

- Detect file replacement and ordinary concurrent writes during shared render and selection snapshot copying, remove incomplete copies, and verify both failure paths.

- Apply checked snapshots to Word, slide and cell search, tracked-change inventory and review bundles; verify concurrent-write rejection at each entry point.

- Check source stability before OfficeCLI batches and session creation, restore and export; concurrent writes abort publication, and session startup now shares the 128 MiB snapshot limit.

- Add versioned XLSX grid border formatting, individual side styles, all-side RGB colors, border readback, and viewer controls while retaining unrelated workbook parts and formula caches.

- Extend XLSX grid borders with range outline and interior placement, per-side RGB colors, viewer placement controls, and verification that untouched edges retain their existing styles.

- Reset viewer formatting controls after a successful commit and lock them during the request, retaining options on failure to prevent accidental reuse of prior formatting.
