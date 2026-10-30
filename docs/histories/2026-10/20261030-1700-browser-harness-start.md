# Browser harness modernization: initial observation APIs

用户希望在现有个人 fork 上推进浏览器 harness，使其跟上当前 Codex 的浏览器交互能力。

JavaScript SDK 为 tab 增加原始 CDP 可访问性树与 PNG 截图读取，供持续任务观察页面结构和视觉内容。相关用法和能力限制记录在 SDK README；后续工作与验证要求记录在 active execution plan。

后续增加独立 `obu-repl-mcp`：持久 Node REPL、同一 browser session、文本和图片输出、异常后的会话恢复，以及 stdin 结束时关闭连接。该入口执行本地代码，仅供可信客户端使用；当前连接 Chrome extension socket。

Electron 新增 `obu-iab-repl-mcp`，复用同一 REPL、宿主 FD 3 引导和既有 scope/租约授权。子进程测试覆盖授权、跨 scope 拒绝和撤销；真实 Electron smoke 增加 private/socket 测试路径。

真实 Electron 验证发现内置 Node 24 的 REPL 将部分异常写到内部输出而不调用求值回调；修复错误处理后，使用 Electron 自带 Node 验证两个授权通道的异常恢复。

macOS Electron 44 的完整 smoke 最终通过。页面观察同时输出有限长度的可访问性文字，提供上下文与控件索引，并明确标记截断。

增加可选有序观察文本差异；导航、缺失基线或截断时重新输出完整状态。控件索引与 snapshot id 始终来自最新观察。

观察文字补充 checked、selected、expanded 等可访问性状态；操作前重新核对这些状态。隔离 Chromium 扩展 bridge smoke 验证复选框切换及差异输出。

点击命中检查逐层穿过 Shadow DOM，验证目标及宿主没有被覆盖。隔离 Chromium 扩展 bridge smoke 覆盖嵌套 open/closed shadow 目标和外层遮挡；macOS 原生消息 smoke 也验证了嵌套目标的可信点击。

增加可选同进程 iframe 观察和索引交互：校验 frame loader、逐层换算坐标并检查遮挡。macOS Chromium 原生消息 smoke 验证嵌套 frame 点击，Electron 真实页面验证 frame 点击；跨进程 frame 仍待支持。

SDK 增加以 CSS viewport 为坐标的点击和滚动，校验坐标边界并使旧观察失效；隔离 Chrome 验证鼠标与滚轮事件。同步更新 agent skill 入口和高 DPI 坐标说明。

SDK 增加坐标拖拽，路径中途失败时尽力释放鼠标。隔离 Chromium 扩展 bridge smoke 和 macOS Electron 页面验证滑块收到可信输入。

Electron 在隐藏或最小化窗口中拒绝滚动手势，防止 Chromium 未完成的输入占住标签命令队列；macOS 真实可见窗口已验证坐标滚动。

SDK 支持向焦点控件发送常用按键和修饰键组合。隔离 Chrome 验证可信 Enter 事件与跨平台全选；文字插入继续通过独立的文本输入 API。

SDK 提供用户标签发现和显式接管，并修复连接失败或远端断线后无法重新连接的问题。每次 CDP 调用重新确认 debugger 附着，减少重启或脱离后的失效缓存；断线中未确认的操作由调用方决定是否重试。

Chrome REPL 增加活跃 socket 发现：单个连接可自动选择，多个连接要求显式 socket，profile 名称通过现有 CLI 映射。连接建立时被关闭也会立即失败。

发现过程保留无响应 socket 的未知状态；只要有未知连接，自动选择会拒绝并要求显式指定，防止探测超时造成误路由。新增无响应 socket 的实际进程测试。

增加隔离 Chromium bridge smoke：真实扩展后台、Go relay、SDK 和持久 REPL 验证观察、可信点击、文本差异、截图与标签清理。扩展和 relay 之间由测试专用 CDP 桥接，原生消息注册链路仍待单独验证。

在 Linux ARM64 隔离环境中，Chromium 150 使用临时 profile 中的原生消息清单启动实际 Go host；扩展、host、SDK 和 REPL 的可信点击、差异、截图及清理通过。可重复运行脚本为 `scripts/chromium-native-smoke.mjs`；该环境使用禁用 sandbox 的一次性浏览器进程。

macOS ARM64 Chromium 141 同一原生消息 smoke 通过。仓库目录中的 host 由 Chromium 启动时曾停在系统动态加载阶段；将相同构建复制到临时测试目录后通过。实际安装路径仍需单独验证。

SDK 增加单次观察、索引点击和文本插入：操作前复核文档和控件语义，检查遮挡后发送 CDP 鼠标事件，输入前检查焦点及可编辑状态。新增协议模拟测试和 Electron 页面 smoke 验证入口；本机 Chrome headless 通过直接 CDP 验证可信点击和输入。

影响范围：JavaScript SDK、Electron 集成、测试和文档。状态差异、统一浏览器路由和真实浏览器端到端验收仍在后续计划中。

隔离 Chromium 使用站点隔离验证跨进程 iframe：父 session 的 frame tree 不包含该 iframe；自动附着产生子 session 后，可在子 session 获取对应 frame tree 和 AX tree。集成前还需要完成嵌套 session 的生命周期、跨进程坐标与授权边界设计。

Chrome 路线已接入 iframe 子 session，观察及交互跨越嵌套 frame；后台 frame 的鼠标与文本输入发送到目标进程 session。macOS Chromium 原生消息 smoke 验证跨进程可信点击、文本、嵌套 iframe、导航失效及遮挡拒绝。Electron 维持原有 page scope，跨进程 iframe 待实现。

Electron host 对 iframe 子 session 按标签登记并执行 page.control 授权校验；只读租约不接收 CDP 事件。macOS Electron 44 的站点隔离页面验证跨进程 iframe 可信点击、文本、导航失效与遮挡拒绝；子 session 局部坐标暂不更新宿主视口光标反馈。

Electron 的 private 与 socket REPL 进程也验证跨进程 frame 观察和可信点击；只具备 page.control 的租约可接收调试事件，仅有 tabs.read 的租约不会接收。

跨进程 frame 索引操作现传递父页面 viewport 视觉坐标给 Electron host，子 session 输入继续使用其局部坐标；真实页面对比了光标与 frame 内按钮的坐标。

Linux ARM64 隔离 Chromium 150 的原生消息链路也通过跨进程及嵌套 frame、可信点击和输入、导航、遮挡与重连检查；该一次性浏览器使用 --no-sandbox。

REPL 增加 getBrowserState()：返回当前 backend 的可选浏览器及已连接会话的标签，支持以 browserId 路由；Electron 限于宿主授权的 scope。Chrome 原生消息链路验证发现、按 ID 连接和标签状态。

macOS Electron 的 private/socket REPL 通过状态清单、按浏览器 ID 连接和已授权标签读取验证；显式关闭的连接会从会话清单移除，撤销后的会话返回错误。

Electron host 可通过 --allow-extension-discovery 显式启用同一 REPL 的 Chrome 发现及按 ID 路由；默认仍仅提供 host scope。混合 smoke 使用真实 Chrome 扩展、原生 host 和 Electron 授权通道 fixture，验证不同 backend 的会话与撤销互不影响。

混合路由 smoke 已在 macOS ARM64 和 Linux ARM64 运行：真实 Chromium 扩展和原生 host，配合 Electron 授权传输 fixture，验证发现、选路以及宿主撤销后 Chrome 仍可用。Linux 浏览器在一次性环境中使用 --no-sandbox。

macOS 上同时运行真实 Electron 宿主和真实 Chrome 扩展；private 与 socket REPL 均从同一清单按 ID 连接两者并检查各自标签。完整示例 smoke 其余流程继续运行。

SDK 增加 fill：对已观察文本框执行可信全选和文本输入或清空，验证焦点、可检查的选择范围及最终内容。macOS/Linux Chromium 的跨进程 frame 和 contenteditable 页面通过，macOS Electron 的跨进程文本框通过。

增加 getByRole 语义定位，覆盖交互控件及可访问 frame，支持 count、click、fill、type、first 和 nth；每次重新观察，重复匹配或 frame 信息缺失时拒绝操作。macOS/Linux 原生 Chrome 验证跨进程点击及 contenteditable 填充，macOS Electron 验证跨进程填充。

语义定位的 click、fill 和 type 增加可配置目标出现等待；重复匹配立即拒绝，已发送输入失败不重复执行。macOS/Linux Chromium 包括跨进程 frame 的延迟控件和 macOS Electron 页面通过真实点击验证。

定位器等待扩展到输入前临时遮挡和状态变化；用独立错误类型区分可重试的预检与已发出的输入，后者一律不重放。真实 Chrome 验证顶层与跨进程 frame 的遮挡消失，Electron 验证顶层遮挡消失；单测覆盖点击后 frame 变化不重复点击。

增加 getByLabel 与 check/uncheck；观察结果包含可用的 checked 状态，操作前复核状态、仅在需要改变时点击并核对结果。mixed 状态和直接取消已选 radio 暂不支持。macOS/Linux Chrome 与 macOS Electron 的跨进程表单验证可信事件及重复 check 不产生额外事件。

增加原生 selectOption：按 value/label 选择单项或多项，等待缺失选项，拒绝禁用和歧义，核对最终选择。操作派发非可信 DOM input/change 事件。macOS/Linux Chrome 与 macOS Electron 的跨进程下拉框验证通过。

观察支持显式 includeValues：读取可访问字段的当前值，核实控件类型并遮蔽原生 password，不可识别类型返回 unavailable；单值和总量有上限，切换选项后差异基线重置。macOS/Linux Chrome 与 macOS Electron 的跨进程字段和密码遮蔽验证通过。

增加 getByText、heading role 与 includeText 观察：对静态文本节点计算可见 range 并校验命中与禁用祖先，切换 includeText 重置差异基线。macOS/Linux Chrome 和 macOS Electron 的页面与跨进程 frame 验证通过，Chrome 覆盖文字内遮挡和禁用按钮拒绝。

输入前间隔 75ms 两次采样目标几何及顶层 frame 坐标，并在第二次采样后重核角色、名称和状态。macOS/Linux Chrome 验证移动按钮和移动 frame，macOS Electron 验证移动按钮。两次采样无法覆盖采样后或极慢的变化。

增加 getByPlaceholder 与观察中的 placeholder；即使标签覆盖 accessible name 仍可匹配原始提示。过长提示会标记截断并使定位查询拒绝，提示变化会使旧观察失效。macOS/Linux Chrome 和 macOS Electron 跨 frame 验证通过，Chrome 还验证 aria-placeholder 的 contenteditable。

fill 支持原生 number、date、time、month、week、datetime-local；修改前验证值格式，数字输入为可信事件，日期时间使用 DOM 派发事件。过滤日期控件内部 AX 分段以避免独立定位。macOS/Linux Chrome 验证全部类型，macOS Electron 验证 number、date、time。

Electron 已呈现但隐藏的窗口支持可信 wheel 滚动，暂时关闭后台节流并恢复原设置；等待有界，超时后解除调试器并释放队列。macOS Electron 隐藏窗口 smoke 验证滚动与后续页面读取；未呈现标签仍返回明确错误。隔离实验确认隐藏窗口节流恢复前需要等待渲染帧。

未呈现页面的临时原生窗口实验验证可信 wheel 可用，但关闭最后一个原生窗口触发宿主 window-all-closed；暂不在运行时引入该窗口。输入预备截图和显式截图增加有界超时，超时后释放队列并阻止延迟输入。新增独立真实 Electron 隐藏窗口滚动 smoke。

增加语义悬停和坐标悬停。复用定位、遮挡及稳定性检查，macOS Electron 真页面验证首次隐藏窗口输入产生可信 mouseenter 且不点击；准备首个鼠标事件时暂时关闭后台节流并恢复。

macOS 隔离 Chromium 原生消息完整链路及 Electron 44 跨进程 frame 验证语义悬停的可信 mouseenter 和无点击；Electron 另验证坐标悬停。

语义定位支持标准 img 角色，匹配可访问名称并复用图像节点的可见性与命中检查；includeText 观察包含图像索引。macOS Chromium 原生消息链路和 Electron 44 均验证跨进程 frame 图像的可信点击。

增加 getByAltText，读取可访问性来源中的原始 alt，即使 aria-label 覆盖名称也可匹配。长文本截断时拒绝不完整定位，完整内容的摘要用于识别截断后缀变化；placeholder 的截断变化也使用同样检查。macOS Chromium 和 Electron 跨进程 frame 验证可信点击。

Linux ARM64 Chromium 150 在隔离临时 profile 中复跑真实扩展、原生 host 与 SDK/REPL：跨进程 frame 可信悬停和被 aria-label 覆盖的 alt 定位通过；SDK 34 项测试通过。测试 Chromium 使用 --no-sandbox。

新增 dialog 与 alertdialog 语义角色。macOS Electron 验证原生模态 dialog 的定位和可信悬停；macOS Chromium 原生消息链路验证主页面 dialog 与跨进程 frame alertdialog。

新增定位器 press：输入前检查目标和焦点，DOM.focus 可能触发页面焦点处理器；跨 frame 将按键发送到对应会话。支持 Space，按下结果未知时尽力释放按键。macOS Chromium 与 Electron 的跨进程输入框验证可信 Enter，Electron 验证复选框 Space。

修复普通字母和 Space 按键无法输入文本：可打印按键使用包含 text 的 keyDown，组合键保留 rawKeyDown。macOS Chromium 与 Electron 的跨进程输入框验证小写、大写、空格及可信 input；Electron 复选框继续验证 Space。
