# Browser harness modernization

## 目标

基于现有 Chrome 和 Electron 路线，提供适合持续多轮操作的浏览器 harness，逐步对齐当前 Codex 的可观测性和交互体验。

## 范围与现状

- 复用已有 extension、session/tab ownership、Electron scope 和 SDK。
- 当前 Codex 的统一入口提供持久 JavaScript 会话、浏览器发现、标签页绑定、可访问性状态、截图与基于状态的操作。具体支持依 backend 而异。
- 本仓库已有 Chrome 和 Electron 传输、会话与底层 CDP；JavaScript SDK 的 `domSnapshot` 当前只返回页面文本。Electron MCP 已提供原始 AX tree 和截图。
- 第一阶段先暴露 JavaScript SDK 的 AX tree 和截图，保持原始 CDP 语义；不宣称具备元素索引、增量树或 Codex 的完整能力。

## 后续里程碑

1. 建立持久 JavaScript 工具会话，支持连接、状态保持和图像输出，定义会话结束及错误恢复行为。
2. 为 Chrome 和 Electron 建立统一浏览器发现、标签页绑定与生命周期接口，维持现有授权边界。
3. 实现可操作的页面状态、更新后的索引失效规则及视觉交互，覆盖页面导航、跨 frame 和动态更新。
4. 使用真实 Chrome 与 Electron 的多轮任务验证交互、恢复和资源清理；逐项记录平台限制。

## 风险与验证

- 页面内容视为不可信数据；现有权限和 session/scope 隔离必须贯穿新入口。
- 原始 CDP AX tree 的节点并非稳定操作句柄；跨 frame 和变化检测仍需专项设计与真实浏览器验证。
- 每个阶段运行涉及包的类型检查和针对性测试；端到端能力须在真实浏览器中验收。

## 进度

- [x] 确定使用 iFurySt 上游的现有个人 fork。
- [x] 添加 SDK 原始 AX tree 和 PNG 截图入口。
- [x] Chrome 路线提供持久 JavaScript MCP、图片输出及连接清理；本地代码执行仅供可信客户端使用。
- [x] SDK 支持基于单次观察的控件索引和鼠标点击，检查文档、角色、名称和遮挡。
- [x] SDK 支持在已观察的文本框中插入、替换和清空文本，检查可编辑状态、焦点、选择结果和最终值。macOS/Linux Chromium 以及 macOS Electron 验证可信输入。
- [x] 隔离的本机 Chrome headless 页面通过直接 CDP 验证 SDK 索引点击、文本输入、可信事件及旧快照拒绝。
- [x] Electron REPL 复用 host bootstrap、scope 和租约；private/socket 子进程测试覆盖撤销和跨 scope 请求拒绝。
- [x] macOS Electron 44 真实页面完成观察、可信点击/输入，以及 private/socket REPL 观察、截图和撤销检查。
- [x] macOS Electron 44 完整 smoke 通过，包括保留标签、人工接管与清理。
- [x] 观察结果包含有限长度的页面可访问性文字，并显式报告截断。
- [x] 观察包括勾选、展开等控件状态；动作前重新核对状态，防止对变化后的控件执行旧操作。
- [x] 在嵌套 open/closed Shadow DOM 中校验目标和各层宿主的命中；隔离 Chromium 验证可信点击与覆盖拒绝。
- [x] 可选观察同进程 iframe，换算嵌套 frame 坐标并拒绝导航后的旧目标；macOS Chromium 原生消息链路和 Electron 页面验证可信点击。
- [x] Chrome 跨进程 iframe：附着子 session、跨进程和同进程嵌套坐标换算、观察、可信点击和文本输入；隔离原生消息链路验证导航与遮挡拒绝。
- [x] Electron 受授权范围约束的跨进程 iframe：macOS Electron 强制站点隔离页面验证可信点击、文本、导航失效及遮挡拒绝；会话仅限所属标签和 iframe。
- [x] Linux ARM64 隔离 Chromium 150：原生消息链路验证跨进程与嵌套 frame 的可信输入、导航、遮挡和重连。
- [ ] 跨进程 iframe 的其他平台与动态 frame 场景验收。
- [x] 同一文档支持有序文本差异；导航和截断后回到完整基线。
- [x] 按 CSS viewport 坐标点击和滚动；本机隔离 Chrome 验证真实鼠标和滚轮行为。
- [x] 语义定位器与 CSS viewport 坐标悬停；macOS/Linux Chromium 与 macOS Electron 跨进程 frame 验证可信 mouseenter，Electron 验证坐标悬停。
- [x] CSS viewport 拖拽；隔离 Chromium 和 macOS Electron 页面验证可信滑块输入。
- [x] US 键盘数字和常见标点，包括 Shift 和快捷键组合；真实输入产生可信事件。
- [x] 定位器按键先聚焦并校验目标，在跨进程 frame 中路由可信按键；输入失败后尝试释放按键。
- [x] 常用按键与修饰键组合；Chrome 和 Electron 真实页面验证可信 Enter 和全选。
- [x] Electron 已呈现的隐藏窗口通过可信 wheel 事件滚动，并限制等待时间；超时后恢复队列。
- [x] macOS Electron 可见宿主窗口坐标滚动通过真实页面验证。
- [x] Electron 输入预备与截图的有界超时；超时释放队列并阻止迟到输入。
- [ ] Electron 未呈现页面滚动，以及其他系统与最小化窗口的实机验证。
- [x] Chrome 用户标签发现与显式接管，以及 socket 断开后的后续连接恢复。
- [x] Chrome REPL 探测 socket；多连接或探测结果未知时要求显式选择，避免误用最近活跃 profile。
- [x] 隔离 Chromium 中，真实扩展后台、Go relay 和 SDK/REPL 完成观察、可信点击、差异、截图及清理；扩展和 relay 间使用测试 CDP 桥。
- [x] Linux ARM64 隔离 Chromium 150：真实原生消息清单、扩展和 Go host 启动链路，SDK/REPL 可信点击、差异、截图与清理通过。
- [x] macOS ARM64 隔离 Chromium 141：临时 profile 原生清单和临时复制的 Go host 经 SDK/REPL 完成可信点击、差异、截图与清理。
- [x] Chrome 与 Electron REPL 共用浏览器状态入口和基于浏览器 ID 的连接；Electron 仅暴露宿主授权 scope。
- [x] 宿主显式启用时，同一 REPL 发现并按 ID 路由 Electron 和 Chrome；真实 Chrome 原生链路与 host 授权 fixture 验证独立撤销。
- [x] group、list、listitem、table、row 等结构角色支持作用域；Chromium 和 Electron 验证重复按钮消歧。
- [x] 语义定位器支持多层容器作用域；跨 Shadow DOM 和 iframe 检查包含关系，输入前重核作用域。
- [x] 按角色和名称语义定位可交互节点；每次操作重新观察，严格处理重复和不可读取的 frame。
- [x] 语义定位对尚未出现、暂时遮挡或输入前变化的控件进行有界等待，歧义立即报错；输入已发出后不自动重试。macOS/Linux Chrome 与 macOS Electron 实机验证。
- [x] 可访问名称定位表单控件、checked 状态与幂等 check/uncheck；真实 Chrome 和 Electron 跨进程表单验证可信事件。
- [x] 原生 select 的单选、多选及选项等待；明确记录 DOM 事件的 isTrusted 为 false，并验证跨进程 frame。
- [x] 可选输出当前可访问字段值，原生密码框遮蔽并限制单值与总量；跨 frame 验证和差异基线隔离。
- [x] 支持 dialog 和 alertdialog 角色定位；macOS Electron 模态窗口及 Chromium 跨进程 frame 验证。
- [x] 支持图像 alt 文本定位，包括名称被 aria-label 覆盖时的原始 alt；长文本截断与变化有检查。macOS/Linux Chromium 与 macOS Electron 跨进程 frame 验证。
- [x] 支持按可访问名称定位图像角色；macOS Chromium 和 Electron 验证跨进程 frame 的可信点击。
- [x] 支持静态文本及标题定位；按可见文字范围点击并检查禁用祖先和遮挡。
- [x] 输入前两次采样目标及 frame 位置，重核语义；移动目标等候，已发出输入不重放。
- [x] placeholder 与 aria-placeholder 语义定位，包含不同 accessible name、动态变化和截断处理。
- [x] 原生数字与日期时间字段填充，修改前校验格式，隐藏日期控件内部 AX 分段。
- [ ] 完整的可交互状态、更丰富的定位器及更多 backend 的统一路由。
- [ ] Windows 原生消息注册和端到端传输验收；macOS 实际安装路径验证。
