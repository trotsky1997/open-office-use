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

按键支持 US 键盘数字、常见 ASCII 标点及 Shift 映射；可直接输入 @、+，修饰键与字符键按对应物理码派发。macOS Chromium 与 Electron 跨进程输入框验证可信输入。

新增可链式组合的语义定位器，按容器后代范围消除重复匹配；使用 DOM 包含关系穿过 Shadow DOM 和 iframe，输入前重核容器角色、名称及包含关系，聚焦后再次检查。macOS Chromium 验证 closed Shadow DOM 与跨进程 iframe，Electron 验证重复按钮及多层容器。

Linux ARM64 Chromium 150 隔离原生消息链路验证作用域跨 closed Shadow DOM、多层容器及嵌套跨进程 iframe；复用的临时浏览器使用 --no-sandbox。

扩展作用域角色，涵盖分组、列表、表格、导航等可访问结构；macOS/Linux Chromium 与 macOS Electron 验证 group/list/listitem 四层定位，Electron 验证 table/row。Linux 测试使用隔离浏览器和 --no-sandbox。

新增基于可访问静态文字的 hasText/hasNotText 筛选：支持多层作用域、closed Shadow DOM 与跨进程 frame；输入前及聚焦后重新读取文字。可能属于当前作用域的不可索引文字、无法判定归属的文字或超长内容会报错，防止遗漏使排除筛选产生错误结果；可证明不相关的文字不会阻断筛选。macOS/Linux Chromium 与 macOS Electron 实机验证；Linux 使用隔离浏览器与 --no-sandbox。

文字筛选将同 frame 的包含关系按最多 32 个节点批量检查，跨 frame 按页面复用包含结果；失败时释放已解析对象。macOS 隔离 Chromium 单次 12 项筛选由约 1422 ms 降至 419 ms，测量仅代表该 fixture。

getByRole 新增 checked、pressed、selected、expanded 状态筛选，观察输出暴露这些状态；未知选项显式报错，mixed 与未提供状态不会匹配布尔条件。状态改变后拒绝旧目标。macOS/Linux Chromium 与 macOS Electron 的跨进程 iframe 验证状态选择及可信操作。Linux 使用隔离浏览器与 --no-sandbox。

禁用控件保留在观察中并支持 disabled 状态筛选；可悬停以查看提示，点击、按键与状态修改会检查禁用状态和 DOM 祖先。幂等 check 也验证 DOM 祖先和最新状态。macOS/Linux Chromium 与 macOS Electron 跨进程 frame 验证原生 disabled、fieldset、aria-disabled 继承和可信悬停；Linux 使用隔离浏览器与 --no-sandbox。

加入 JavaScript 原生对话框监听与显式处理；Electron 对话框处理绕过阻塞的页面命令队列，仍检查作用域权限。断线重连会使旧句柄失效。Linux ARM64 Chromium 原生消息链路验证 prompt、confirm、跨进程 frame 与持久 REPL；macOS Electron 验证 alert、confirm 与跨进程 frame。Electron 的 prompt 不受支持，原生对话框可能显示隐藏宿主窗口。Linux 使用隔离浏览器与 --no-sandbox。

截图支持以 CSS 视口坐标指定裁剪矩形；按当前可视视口偏移转换到页面坐标并拒绝越界区域。macOS Electron 与 macOS/Linux Chromium 实页验证页面滚动后裁剪像素；Linux 使用隔离浏览器与 --no-sandbox。截图期间页面滚动或窗口尺寸变化时需重新截图。

新增 waitForURL：精确字符串或正则匹配主文档 URL，同时检查所需加载状态；支持 history API 路由和跨文档跳转。仅在执行上下文被导航销毁时重试，权限和连接错误直接返回；REPL 的跨上下文正则可使用。macOS Electron 与 macOS/Linux Chromium 实页验证两种导航；Linux 使用隔离浏览器与 --no-sandbox。该方法以约 100 ms 间隔采样，短暂中间 URL 可能错过。

对话框和页面加载事件等待监听所属标签关闭、调试器断开及客户端连接关闭，并及时释放监听器；其他标签的事件不会中断等待。导航仅在等待超时后尝试读取当前加载状态，不吞掉连接断开等错误。macOS Electron 与 macOS/Linux Chromium 实页验证关闭标签后等待结束，真实本地 socket 验证远端断开与 IAB 授权撤销。Linux 使用隔离浏览器与 --no-sandbox。

修复加载等待的事件订阅竞态：先订阅主页面事件，再检查文档状态；跨进程 iframe 的事件不会使主页面等待提前结束。导航失败或已满足加载状态后取消等待并释放监听器。回归覆盖状态读取期间完成加载、iframe 事件、导航报错和资源释放；macOS Electron、macOS/Linux Chromium 完成现有真实页面回归。Linux 使用隔离浏览器与 --no-sandbox。

修复 goto 超时后把旧的已加载页面视为成功的问题。CDP 不返回 loaderId 时，只有当前 URL 与目标一致且文档达到加载状态才结束同文档导航；已发生的调试器断开仍会返回错误。测试覆盖旧页面超时、同文档片段跳转和断开竞态；macOS Electron、macOS/Linux Chromium 实页验证片段跳转。Linux 使用隔离浏览器与 --no-sandbox。

SDK 增加标签页 back、forward、reload。历史边界直接返回，导航动作不自动重试；reload 等待主页面 load 事件并在失败时清理监听。后退和前进返回时命令已发送，调用方核验目的地。macOS Electron、macOS/Linux Chromium 实页验证 history API 路由往返与重新加载；Linux 使用隔离浏览器与 --no-sandbox。

新增 fullPage 截图，使用 CSS 内容尺寸捕获视口外区域，与局部裁剪互斥；限制单边 32767 CSS 像素及 3200 万 CSS 平方像素。Electron 对接近 8 MiB 传输上限的截图直接报错，保留连接和页面队列。macOS Electron、macOS/Linux Chromium 实页验证视口外像素；未滚动触发的懒加载内容可能尚未出现。Linux 使用隔离浏览器与 --no-sandbox。

修复 Chrome waitForDownload 返回历史缓存的问题：现在等待注册后的下一次 started 事件，downloadPath 仍可查询已完成下载。macOS/Linux Chromium 隔离 profile 连续两次真实下载、读取临时文件并验证旧下载不会提前结束新等待；Linux 使用 --no-sandbox。Chrome 下载事件目前没有可靠标签归属，且等待注册没有确认信号，并发下载与立即触发存在关联或时序限制；文档明确说明，后续需设计可靠的事件关联协议。

Chrome 下载等待新增注册确认：`tab.prepareDownload()` 等扩展实际安装监听器后返回句柄，触发页面动作后可通过 `wait()` 和 `path()` 获取结果；长等待的客户端请求超时覆盖服务端等待。macOS/Linux Chromium 原生消息链路连续两次真实下载，确认后立即点击，无人为延时；Linux 使用 --no-sandbox。Chrome 下载事件仍缺少可靠标签归属，Electron 下载未开放。

Chrome SDK 新增文件选择器准备握手：监听与拦截就绪后返回句柄，支持单文件或多文件绝对路径；同一个选择器只允许一次文件决策。页面 frame 导航或调试器断开会清除旧句柄，发送前再次核实并消费句柄，未知结果不重复提交。macOS/Linux Chromium 隔离 profile 通过真实本地文件选择；跨进程 frame 的会话路由有单元覆盖，尚未实机验证。Electron 未开放文件上传；Linux 使用 --no-sandbox。

Chrome 文件选择器覆盖已附着的跨进程 iframe 会话：准备阶段启用 frame 会话并逐个开启拦截，文件决策发送到来源会话。等待期间 frame 树变化会中止并清理；拦截关闭完成前拒绝第二个等待，设置拦截失败也尝试关闭。macOS/Linux Chromium 实页验证跨进程多文件选择和本地测试文件；Linux 使用 --no-sandbox。iframe 后续动态变化时需重新准备。

Electron 新增显式授权的文件选择：宿主通过 scope.files.authorize 设置允许的现有常规文件，客户端需同时持有 page.control 与 files.upload 权限；文件路径在授权和决策时解析校验，授权替换或撤销会阻止尚未发送的决策。主页面和已附着跨进程 frame 使用 SDK 的 prepareFileChooser；选择器句柄一次性消费，导航或断连失效，准备超时会释放队列并阻止迟发命令。macOS Electron 实页验证主页面单文件与跨进程 frame 多文件；本机套接字集成与单元测试覆盖作用域、拒绝、符号链接改向、撤权和超时。路径授权不固定文件内容；Linux/Windows Electron 尚未实测。

Linux ARM64 的 Electron 44.7 在临时 Xvfb、独立 profile 和 no-sandbox 进程中通过原生 socket 授权的文件选择实测：主页面可见时及宿主窗口显示后隐藏时的跨进程 iframe 均选中本地 fixture。新增 upload-smoke.mjs 便于复现。完整 scroll-smoke 在从未显示的隐藏宿主窗口遇到输入预备截图超时并断开调试器；该平台限制待修复，Xvfb 实验不覆盖普通桌面环境。

Linux ARM64 Xvfb 中，从未显示的宿主窗口验证了输入准备截图超时；禁用宿主节流、改变窗口大小和截取宿主页面均未恢复输入，绕过准备截图则点击事件未到达页面。保留保护并新增 hidden-input-probe：Linux 真正授权 socket 返回 IAB_INPUT_PREPARATION_TIMEOUT 且未发生点击，macOS 隐藏窗口产生可信点击。传输层仅公开固定的安全错误，其他异常继续隐藏细节；截图准备超时与输入发送后的 IAB_INPUT_OUTCOME_UNKNOWN 分开，后者需先观察。已显示后隐藏的窗口仍可用，从未显示窗口的根本修复未完成；Linux 实验使用隔离虚拟显示、--no-sandbox 和禁用 GPU。

Electron 新增作用域下载：宿主显式配置现有私有目录与大小上限，客户端需同时持有 page.control 与 files.download；仅接受已准备等待且来源 WebContents 匹配的下载，随机文件名写入授权目录。授权撤销或 scope 关闭会取消进行中的下载；总大小已知时预检，流式超限时在事件返回后取消以避免 Electron 回调重入，部分文件可能暂留。macOS Electron 隐藏窗口实测主页面下载；Linux ARM64 Xvfb 通过原生 socket 实测主页面与跨进程 iframe 下载及超限取消，使用 --no-sandbox、禁用 GPU。完成句柄保留五分钟，文件由宿主管理；Windows Electron 尚未实测。

Chrome 下载并发检查补充原生链路验证：macOS 隔离 Chromium profile 中，第二个等待请求被拒绝，首个等待仍可完成，随后下一次下载也成功。调研中启用 Page 域后，主页面下载产生带来源 tab、frameId 和 GUID 的 Page.downloadWillBegin；chrome.downloads.onCreated 则使用独立数字 ID，当前观察到 URL 相同但缺少跨接口的共同标识。两个连续样本不能证明事件排序或同 URL 并发时的关联，仍需研究可靠匹配方案。

Chrome 下载等待现随所属会话 turnEnded、所属标签关闭或调试器断开取消，释放唯一的下载等待槽；其他会话结束不会取消该等待。扩展测试 27 项通过，macOS 隔离 Chromium 经原生消息链路实测 turnEnded 取消等待及后续重新注册。

修复下载等待注册与会话清理的竞态：在异步校验标签前记录等待，若会话清理期间取消，则校验完成后直接结束，既不注册监听也不发送准备通知。扩展测试 28 项通过；macOS 隔离 Chromium 的真实下载、并发拒绝及会话取消检查通过。

下载句柄新增浏览器报告的 URL，Chrome 扩展及 Electron 后端均提供，未提供时为 null。macOS 隔离 Chromium 原生消息链路及 Electron 44 页面分别验证下载 URL 与文件内容；SDK 53 项、Electron 45 项及扩展下载测试通过。Chrome 的 URL 有助于人工或调用方核对，但同 URL 并发仍无法可靠判定标签归属。隔离 Chromium 141 实验中，页面调试目标拒绝 Browser.setDownloadBehavior，Page.downloadProgress 不含保存路径。

语义定位器增加 innerText()：等待唯一匹配，读取前核对目标、作用域及 frame，限定 30000 字符并释放 CDP 对象。SDK 54 项通过；macOS 隔离 Chromium 原生消息及 Electron 44 页面实测主页面和跨进程 iframe 读取，后者包含作用域定位。

语义定位器增加 getAttribute(name)，返回单个匹配元素的原始属性或 null，并复用 innerText 的目标、作用域、frame 与长度校验。macOS 隔离 Chromium 原生消息链路实测主页面 href、缺失属性和跨进程 frame 属性；Electron 44 页面实测 href。真实链路发现 null CDP 参数会变化，已改为空字符串哨兵并重新验证；SDK 54 项通过。

语义定位器新增 textContent()：读取唯一匹配节点的原始 DOM 内容，复用作用域、frame 和长度校验。macOS 隔离 Chromium 原生消息链路验证隐藏后代与 innerText 的差异及跨进程 frame；Electron 44 页面实测主页面。SDK 54 项通过。

定位器新增 isEnabled() 和 setChecked(boolean)。isEnabled 结合可访问状态、原生 :disabled 与跨 Shadow DOM 的 aria-disabled 祖先；setChecked 复用已有幂等可信输入路径。SDK 54 项通过；macOS 隔离 Chromium 原生消息和 Electron 44 验证可用控件、跨进程 frame 禁用祖先及可信勾选。

语义定位器新增 isVisible()：检查匹配节点的 CSS visibility、非零尺寸和各级 frame 宿主，缺少可访问匹配时返回 false，重复匹配报错。SDK 54 项通过；macOS 隔离 Chromium 原生链路验证主页面、跨进程 frame 与零尺寸 frame，Electron 44 页面验证主页面和跨进程 frame。遮挡和视口外位置不影响该状态；可访问树未收录的节点不可由语义定位器查询。

语义定位器新增 last() 与 all()；last 在过滤和位置操作的既定顺序中选择最后一项，all 按当前数量返回位置定位器，各定位器使用时重新观察。SDK 54 项通过，覆盖过滤顺序与列表重排；macOS 隔离 Chromium 原生链路和 Electron 44 实测跨进程 frame 列表读取。

新增 expectNavigation(action, options)，在动作执行前监听主 frame 导航，支持文档导航与同文档路由，随后检查指定 URL 和 load/domcontentloaded 状态；动作错误或超时会清理监听，子 frame 事件不会满足等待。SDK 55 项通过；macOS 隔离 Chromium 原生消息链路与 Electron 44 页面实测真实链接跳转和 History API 路由。

修复 expectNavigation 的整体等待超时：即使主 frame 导航事件已到而动作回调未返回，超时仍会结束等待并清理监听；迟到回调不会继续启动后续加载检查，已发出的动作无法撤回。SDK 55 项通过，macOS 隔离 Chromium 原生链路实测同文档导航后回调挂起的超时。

语义定位器和观察索引新增 dblclick：发送 clickCount 1 和 2 的可信输入，第一次点击后重新核对目标、frame、作用域及位置，变化时停止且不自动重试。SDK 56 项通过；macOS 隔离 Chromium 原生消息链路与 Electron 44 验证主页面及跨进程 frame 的可信 dblclick 事件。

语义定位器新增 waitFor({state:'visible'|'hidden'})：轮询现有可见状态，重复匹配报错并限制等待时间。SDK 57 项通过；macOS 隔离 Chromium 原生消息链路验证主页面和跨进程 frame 中异步出现、隐藏和移除，Electron 44 验证主页面。匹配范围为可访问树；DOM attached/detached 尚不支持，隐藏状态包含无可访问匹配。

语义定位器的 role name、label、text、placeholder、alt 及 hasText/hasNotText 新增 RegExp 匹配；字符串保持原有规则，正则采用自身标志并为每次匹配独立处理游标。SDK 57 项通过，涵盖跨 realm 正则与全局标志；macOS 隔离 Chromium 原生链路和 Electron 44 验证跨进程 frame 的正则作用域与文本过滤。

观察结果保留浏览器提供的 AX level，并允许 heading 定位器按正整数 level 筛选；level 纳入目标状态，变化后拒绝旧观察。SDK 57 项通过；macOS 隔离 Chromium 原生链路验证同名不同层级与跨进程 frame 标题，Electron 44 验证主页面标题。

Linux ARM64 更新验证：隔离 Chromium 150 使用真实原生消息清单、临时 profile、Go host 和 no-sandbox 完整运行当前 chromium-native-smoke，包含近期导航、下载 URL、正则定位、标题层级、动态等待、双击及跨进程 frame。Electron 44.7 在临时 Xvfb、原生 socket、no-sandbox 和禁用 GPU 下验证主页面语义读取、等待、同文档导航及文件传输，并在已显示后隐藏的宿主中验证跨进程 frame 标题、可信双击与文件传输。从未显示的 Linux 宿主窗口输入问题仍待解决；实验不覆盖常规 Linux 桌面和 Windows。

新增 tab.dev.watch()/logs()：按标签捕获控制台调用及未捕获异常，支持级别、文本和条数筛选；动态跨进程 frame 启用 Runtime 域，断连、调试器分离或标签关闭清理记录。每标签最多保留 500 条，消息和来源 URL 各限 4096 字符；较早历史取决于浏览器 Runtime.enable 的缓存。SDK 58 项通过；macOS 隔离 Chromium 原生链路与 Electron 44 验证主页面和动态跨进程 frame 日志，Linux ARM64 Electron/Xvfb 经授权 socket 验证主页面和 frame 日志，使用 no-sandbox、禁用 GPU。

页面开发日志增加 CDP Log 域，记录资源加载失败等浏览器日志；Electron 授权页面 CDP 白名单增加 Log.enable/disable。重新启用时恢复采集，动态 frame 延续作用域。SDK 58 项、Electron 45 项通过；macOS 隔离 Chromium 原生链路及 Electron 44 实测主页面和跨进程 frame 的 404 日志及来源 URL，Linux ARM64 Electron/Xvfb 原生 socket 实测主页面 404，使用 no-sandbox、禁用 GPU。

首页与 SDK 文档新增本 fork 的源码接入路径，区分上游已发布包：构建 SDK 和 Go host、加载源码扩展、使用扩展 ID 注册 host、以绝对路径配置持久 REPL；说明注册会更新已有 host 链接。pnpm 8.15.9 离线验证 frozen lockfile，SDK/Go 构建与 MCP initialize 通过；真实用户浏览器注册未改动，Windows 安装仍待端到端验证。

源码 host 注册补充隔离实测：Linux ARM64 使用临时挂载命名空间和临时用户目录，执行真实 install-manifest，以临时扩展 ID 注册后启动 Chromium 150，SDK 经原生消息连接并读取页面。自定义 user-data-dir 分别验证标准注册清单的链接和 --output 指向该目录的清单；使用 no-sandbox。测试未修改宿主用户的真实浏览器配置，普通桌面及 Windows 安装仍未覆盖。

JavaScript SDK 新增 tab.clipboard 的 readText/writeText/read/write，映射原有 Chrome 协议的 MIME 文本和 base64 格式，写入前验证结构；Electron 仍明确不支持。Chrome clipboard 执行错误现在返回限长异常首行，实际权限拒绝可显示 NotAllowedError。SDK 59 项、扩展 29 项通过；Linux ARM64 隔离 Chromium 150 headless 临时 profile 中显式授予本地 fixture 站点权限，原生消息链路验证文本、HTML 和 PNG；无权限场景验证错误。剪贴板 smoke 需显式启用并使用隔离剪贴板；macOS/Windows 和 Electron 尚未验证或实现。

Electron 44 新增系统剪贴板访问，客户端需持有 page.control 及独立的 clipboard.read 或 clipboard.write 授权；限制数据量并在异步操作前后检查租约。Linux ARM64 Electron 44.7 在隔离 Xvfb 中经原生 socket 验证文本、HTML、PNG；47 项 Electron 测试通过。写入一经发出可能在撤权后完成，macOS/Windows 实际剪贴板及旧版 Electron 暂未覆盖。

语义定位器新增 allTextContents()，按一次观察中的匹配顺序逐项读取原始文本，沿用作用域、frame 和变化校验；空匹配返回空数组，并限制单项及总长度。SDK 59 项通过；Linux ARM64 隔离 Chromium 原生消息和 Electron 44/Xvfb socket 验证容器中多个元素及隐藏后代文本，Electron 还验证同一结果中的跨进程 frame。读取期间页面可能变化，结果没有原子快照保证。

domSnapshot 从页面正文文本改为有界可访问性快照，包含角色、名称、状态和可读取 frame；截断或读取失败明确标注，并刷新已有观察。SDK 60 项通过；Linux ARM64 隔离 Chromium 原生消息及 Electron 44/Xvfb socket 验证跨进程 frame 控件，Chromium 验证密码样本未出现在输出。快照不主动读取字段值，页面提供的可访问名称和文本可能包含敏感内容。

可访问性观察改为按 AX parentId 深度优先排列并缩进，忽略节点的可见后代仍保留，缩进上限为 80 层；domSnapshot 去除操作索引时保留层级。SDK 61 项通过；Linux ARM64 隔离 Chromium 原生消息和 Electron 44/Xvfb socket 实测容器与按钮层级、跨 frame 和原有交互。frame 文档仍分节显示。

可读取 frame 的内容通过 DOM.getFrameOwner 嵌入宿主可访问节点下，支持多层嵌套；宿主位置不可用时保留内容并明确标记。SDK 61 项通过，覆盖嵌套和位置回退；Linux ARM64 隔离 Chromium 原生消息验证跨进程容器及其嵌套 frame，Electron 44/Xvfb socket 验证跨进程 frame 位于宿主容器下。macOS 和 Windows 尚未实测此次变更。

pressKey 根据当前焦点逐层检查 iframe 宿主并选择对应调试会话，发送前重核 frame 树和焦点；检查失败时不发出按键。SDK 62 项通过，覆盖焦点变化拒绝；Linux ARM64 隔离 Chromium 原生消息与 Electron 44/Xvfb socket 实测跨进程 frame 的可信键盘输入。最终检查后页面仍可能改变焦点，macOS 和 Windows 尚未实测此次变更。

新增 typeAtFocus，复用焦点 frame 路由检查后调用文本插入，支持 Unicode；焦点变化时不发送。SDK 62 项通过；Linux ARM64 隔离 Chromium 原生消息和 Electron 44/Xvfb socket 实测跨进程 frame 中的中文、emoji 和可信 input 事件。调用方需要先聚焦并检查结果；文本插入不逐个发送键盘事件。

新增 tab.cua，提供坐标移动、1–5 鼠标按钮、双击、带修饰键滚动、路径拖拽、焦点按键/文本及带 toBase64 的截图；拖拽失败尝试释放按钮，wheel 超时报告结果未知。SDK 63 项通过，包括 REPL 图片输出；Linux ARM64 Electron 44/Xvfb 实测修饰键移动、双击、右键、滚轮、拖拽、PNG 和跨进程文本输入。隔离 Chromium 150 的原生消息常规链路验证 CUA 按键和文本；该环境中直接带修饰键 wheel 超时，固定嵌套容器的滚动手势返回但未滚动且后续截图超时，单独测试入口需显式启用。正常 Chromium 桌面、macOS 和 Windows 尚未验证。

定位 Chromium 滚轮问题与后台标签呈现状态有关：新增显式 tab.bringToFront，调用方自行决定是否激活标签。Linux ARM64 隔离 Chromium 150 的 headless 原生消息完整 smoke 和 Xvfb 前台短测均验证标签从 hidden 变 visible、固定嵌套容器实际滚动、带 Shift 的可信 wheel 及后续 PNG 截图；SDK 63 项通过。后台标签仍可能失败，Electron 的窗口呈现由宿主控制，macOS/Windows 和普通桌面尚未覆盖。

新增所属标签 getPresentation：Chrome 读取浏览器真实标签选中及窗口状态，Electron 读取所属 surface 和宿主窗口状态，未知可见性显式返回 null。Chrome 在宿主查询前后校验 session，Electron 要求 page.control；SDK 63 项、Electron 47 项和扩展相关测试 13 项通过。Linux ARM64 隔离 Chromium 原生消息与 Xvfb 实测后台、前台和焦点模拟伪装，Electron 44/Xvfb socket 实测呈现与隐藏窗口。焦点模拟、禁用后台节流、screencast 和设备视口模拟均未恢复该 Chromium 环境的后台嵌套滚动；后台限制继续保留。

新增 frameLocator，按原生 CSS 匹配直接子 frame 元素并逐层选择，可与已有语义定位器、过滤和位置选择组合；观察后及读取、输入前重新验证 frame 树和选择器，多个匹配立即报错。SDK 63 项通过，覆盖选择器变化、frame 导航及歧义；Linux ARM64 Chromium 原生消息实测跨进程和嵌套 frame、缺失与非法选择器，Electron 44/Xvfb socket 实测跨进程 frame 查询、可信双击和按键。通用 CSS 元素定位仍待实现，macOS/Windows 尚未实测。

frameLocator 的选择器验证与匹配改在命名隔离 world 中执行，降低页面修改 DOM 原型对目标选择的影响。Electron 只允许指定 world 名称，校验 frame 属于当前 debugger session，拒绝通用跨域访问与额外配置；准备超时或撤销授权会阻止迟发，超时释放队列。SDK 63 项、Electron 49 项通过；Linux ARM64 Chromium 原生消息与 Electron 44/Xvfb socket 验证页面篡改 matches 后仍能正确选择，Electron 还验证跨进程内的嵌套 frame。Chromium 实测同一文档重复请求复用上下文；其他平台和通用 CSS 元素定位仍待覆盖。

新增只读 CSS locator：在隔离 world 查询当前文档和开放 shadow root，支持 frame 作用域、数量、位置及文本/属性读取，读取后重新校验文档、frame 与匹配集合。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证隐藏元素、开放 shadow root、跨进程与嵌套 frame、选择器错误和页面篡改原型，Electron 44/Xvfb socket 验证跨进程及嵌套 frame 读取。CSS locator 的交互和链式作用域仍待实现；macOS/Windows 本轮未测。

CSS locator 增加可信点击和悬停：隔离 world 内检查可交互状态、遮挡和稳定几何，发送前重新检查 frame 树及完整匹配集合；输入发出后不自动重试。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证开放 shadow root 可信点击与悬停、禁用拒绝、选择器在准备期间变化时不点击以及跨进程 frame 点击；Electron 44/Xvfb socket 验证跨进程 frame 可信点击。CSS 填写、键盘操作和链式作用域仍待实现；macOS/Windows 本轮未测。

CSS locator 增加 press，聚焦后复核匹配集合、实际焦点 frame、shadow 焦点链与禁用状态；焦点操作已发出后遇到变化直接报错，不重复执行。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证开放 shadow root 可信按键、聚焦回调改变选择器时停止按键、跨进程 frame 按键，Electron 44/Xvfb socket 验证跨进程可信 Enter。CSS 填写与链式作用域仍待实现；macOS/Windows 本轮未测。

CSS locator 增加 fill，支持文本类与数字 input、textarea 和 contenteditable，聚焦和全选后重新检查匹配、焦点、可编辑状态及选区，输入后检查结果。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证开放 shadow root 的 Unicode、清空、contenteditable、只读拒绝及全选回调更换目标时停止，另验证跨进程 frame 可信 input；Electron 44/Xvfb socket 验证跨进程 Unicode 与清空。日期时间 CSS 填写、链式作用域等仍待实现；macOS/Windows 本轮未测。

CSS locator fill 增加原生 date、time、month、week、datetime-local 类型，使用浏览器解析器验证格式并在修改前复核定位及禁用状态；input/change 为合成事件。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证五种类型、无效日期不产生事件及跨进程 frame，Electron 44/Xvfb socket 验证跨进程日期填写。CSS 链式作用域等仍待实现；macOS/Windows 本轮未测。

CSS locator 支持链式后代作用域和中间 first/last/nth，查询开放 shadow root 并在读取或输入前复核每级作用域及目标集合；链深上限 32、累计匹配上限 1000。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证多容器定位、shadow 内链式可信鼠标事件、空作用域非法选择器及作用域变化时拒绝点击；Electron 44/Xvfb socket 验证跨进程 frame 内链式查询。语义和 CSS 混合链及其他 CSS locator API 仍待实现；macOS/Windows 本轮未测。

CSS locator 增加 isVisible、isEnabled 和 waitFor（attached/detached/visible/hidden），可见性检查目标及各层 frame 的样式和尺寸，使用隔离 world 并复核匹配。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证隐藏元素、动态出现、禁用、无目标、多个匹配拒绝及零宽跨进程 frame；Electron 44/Xvfb socket 验证跨进程状态读取。可见性查询不做遮挡命中测试，输入操作另有命中校验；macOS/Windows 本轮未测。

CSS locator 增加 dblclick 与 allTextContents，双击第一次输入后重新检查目标、作用域及几何，批量文本限制总输出并逐项复核目标。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证开放 shadow root 的可信双击、首次点击改变选择器时停止第二次点击、隐藏元素的批量文本；Electron 44/Xvfb socket 验证跨进程 frame 可信双击。批量读取逐项进行，页面可在读取期间改变文本；macOS/Windows 本轮未测。

CSS locator 增加 isChecked、check、uncheck 和 setChecked，支持原生 checkbox/radio 及二态 ARIA 控件；检查已有状态避免重复输入，点击后复核目标与最终状态。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证 shadow root 中可信变更、重复操作、ARIA switch、radio 限制、混合状态拒绝、事件回调改回状态时停止，以及跨进程 checkbox；Electron 44/Xvfb socket 验证跨进程勾选和取消。macOS/Windows 本轮未测。

CSS locator 增加 selectOption，支持原生单选/多选及按值和标签选择，修改前复核定位、选项身份和唯一性，修改后检查结果；input/change 为合成事件。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证 shadow root 链式选择、重复选项拒绝、跨进程单选/多选、禁用选项、事件回调覆盖结果和不重复修改；Electron 44/Xvfb socket 验证跨进程单选。macOS/Windows 本轮未测。

新增 getByTestId 精确匹配 data-testid，支持 tab、frame 和 CSS 链式作用域，特殊字符按 CSS 转义，限制长度并拒绝 NUL 与未配对代理项。SDK 63 项通过；Linux ARM64 Chromium 原生消息验证空值、引号、反斜杠、换行、emoji、shadow root 可信点击与跨进程 frame；Electron 44/Xvfb socket 验证跨进程 frame。语义定位器作用域下的混合链仍待实现；macOS/Windows 本轮未测。

新增 tab.playwright.screenshot 与 waitForTimeout；截图复用既有 viewport、裁剪和全页约束，返回支持 toBase64 的图像，可直接传给 REPL 图片输出。SDK 63 项通过，包含 REPL 图片和计时参数检查；Linux ARM64 Chromium 原生消息验证裁剪和全页 PNG，Electron 44/Xvfb socket 验证 viewport PNG。状态等待仍是优先选择；macOS/Windows 本轮未测。

新增 tab.playwright.waitForEvent("download")；同步登记准备屏障，使后续 SDK CDP 操作等到宿主确认监听注册，失败时阻止排队输入。SDK 64 项通过，包含延迟确认与注册失败的竞态；Linux ARM64 Chromium 原生消息和 Electron 44/Xvfb socket 实测先启动等待、立即点击并读取下载文件。Chrome 下载事件仍缺少可靠标签关联，低层 client 和外部操作绕过屏障；macOS/Windows 本轮未测。

新增 tab.playwright.waitForEvent("filechooser")，等待注册时放行 frame 自动附着与日志初始化命令，其余页面操作等待监听就绪，防止初始化和屏障相互等待。SDK 65 项通过，包含子 frame 附着及输入等待的竞态；Linux ARM64 Chromium 原生消息验证立即点击后设置文件，Electron 44/Xvfb socket 验证主页面及跨进程 frame 文件选择。低层 client 与 SDK 外操作绕过屏障；macOS/Windows 本轮未测。

CSS locator 增加 hasText/hasNotText 筛选，支持字符串及正则、链式作用域和位置选择前后顺序；按规范化 DOM 文本（含开放 shadow root 与隐藏文本）匹配，单个候选文本限制 30000 字符，读取和输入前重新求值。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证正则、排除条件、nth 顺序、shadow root、跨进程 frame 以及作用域文本改变时停止点击；Electron 44/Xvfb socket 验证跨进程筛选。has/hasNot 与语义/CSS 混合链仍待实现；macOS/Windows 本轮未测。

CSS filter 增加 has/hasNot，接受同一 browser、tab 和 frame 的 CSS 定位器，并相对候选元素解析内层链；支持嵌套筛选，输入前重新求值，限制嵌套层数和元素遍历量。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证同标签不同句柄、嵌套条件、位置顺序、跨 frame 拒绝和条件变化后停止点击；Electron 44/Xvfb socket 验证跨进程 frame。语义定位器作为内层条件仍待实现；macOS/Windows 本轮未测。

CSS filter 增加 visible 条件，组合文本、后代及位置条件，并在隔离 world 内检查元素与 frame 的可见样式和非零尺寸；frame 可见性查询前后发生变化时重试。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证显示/隐藏元素、嵌套条件、顺序、输入前隐藏及跨进程零宽 frame；Electron 44/Xvfb socket 验证跨进程 frame 隐藏和异步恢复。可见性筛选不检查遮挡；macOS/Windows 本轮未测。

CSS 作用域新增 getByRole/getByLabel/getByText/getByAltText/getByPlaceholder，语义目标通过隔离 world 检查同 frame 后代关系，并在读取和输入前复核 CSS 匹配、筛选结果与包含关系；支持语义后续链和位置选择。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证 shadow root 混合链可信点击、作用域改变后停止、跨进程 role/label/placeholder/alt；Electron 44/Xvfb socket 验证跨进程语义读取。语义作用域到 CSS 和语义内层 has 条件仍待实现；macOS/Windows 本轮未测。

CSS locator 增加 and 交集，接受同一 browser/tab/frame 的 CSS 定位器，保留位置与筛选顺序，并支持在 has/hasNot 内相对候选元素求值；操作前重新计算交集。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证 shadow root、嵌套条件、位置顺序、跨 frame 拒绝和条件改变时停止点击，Electron 44/Xvfb socket 验证跨进程 frame。语义定位器参与交集、or 和语义作用域到 CSS 仍待实现；macOS/Windows 本轮未测。

CSS locator 增加 or 并集，对同一 browser/tab/frame 的结果按文档及开放 shadow root 遍历顺序去重，支持后续位置选择、筛选和嵌套 has；输入前重新计算。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证顺序、去重、严格匹配、位置、嵌套、跨 frame 拒绝和目标改变时停止点击；Electron 44/Xvfb socket 验证跨进程 frame。语义定位器组合和语义作用域到 CSS 仍待实现；macOS/Windows 本轮未测。

修复 CSS fill 对数字输入缺少预校验的问题：使用浏览器原生 number 解析器在聚焦前验证，并在聚焦及全选后重新核对类型和值，避免对非法数字执行文本替换。SDK 65 项通过；Linux ARM64 Chromium 原生消息验证跨进程无效值保持原值且无 input 事件、有效数值可信输入、聚焦和全选回调改变类型；Electron 44/Xvfb socket 验证跨进程无效与有效数字。macOS/Windows 本轮未测。

语义定位器匹配改为使用显式观察对象，并在读取/输入前独立重算匹配集合及位置，保留当前操作快照；可检测新增歧义或 first/nth 目标改变，且输入已发出后不重试。SDK 66 项通过，覆盖独立复核不替换快照及新增匹配；Linux ARM64 Chromium 原生消息验证滚动准备期间新增同名按钮、改变 first 目标时不发送点击，Electron 44/Xvfb socket 验证原有跨进程上传/下载与定位流程。语义到 CSS 的反向混合链仍待实现；macOS/Windows 本轮未测。

语义定位器新增 locator/getByTestId，独立重算语义容器并在隔离 world 中查询 CSS 后代；作用域身份纳入读写复核，支持同 frame 多容器、CSS 链和继续语义查询。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证多容器与位置、交并集、作用域变更阻止点击、跨多个 frame 明确报错；Electron 44/Xvfb socket 验证跨进程语义容器内 CSS 可信点击。跨多个 frame 的语义容器集合需先缩小范围；macOS/Windows 本轮未测。

CSS locator 增加 type，在当前光标/选区插入文本并复核目标、焦点与 frame；不全选现有内容，日期时间控件提示使用 fill。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证开放 shadow root 的 Unicode 插入、空文本及跨进程可信输入，Electron 44/Xvfb socket 验证跨进程追加。实现使用单次文本插入，不逐字符发送键盘事件；跨多 frame 的语义作用域集合仍待完善，macOS/Windows 本轮未测。

locator(selector, options) 现在实际应用 hasText/hasNotText/has/hasNot，空选项保持原查询，未知键直接拒绝；语义与 CSS 混合链保留 frame 路径，支持同 frame 内相对筛选。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证混合链中的筛选点击、文本/后代条件与无效参数；Electron 44/Xvfb socket 验证跨进程语义容器内文本和后代排除。内层 has/hasNot 目前接受 CSS 定位器，跨多 frame 的语义容器集合仍待完善；macOS/Windows 本轮未测。

语义 locator filter 增加 has/hasNot，内层语义定位相对每个候选容器和同一 frame 求值，位置、嵌套筛选参与独立重查；限制嵌套深度并拒绝不同 tab/frame 或 CSS 根作用域的内层语义定位器。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证每容器 nth、排除筛选、条件变化后阻止点击及跨 frame 检查；Electron 44/Xvfb socket 验证跨进程 frame。CSS/语义混合内层筛选及跨多 frame 的语义 CSS 容器仍待完善；macOS/Windows 本轮未测。

语义 locator 的 has/hasNot 支持同 tab、同 frame 的 CSS 内层定位器，相对每个语义候选执行 CSS 查询，并在读取与输入前复核条件。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证 CSS 条件、相对 nth、frame 边界和条件变化时停止点击；Electron 44/Xvfb socket 验证跨进程 frame。CSS 外层的语义内层筛选和跨多 frame 的语义 CSS 容器仍待实现；macOS/Windows 本轮未测。

语义 locator filter 增加 visible 条件，在隔离 world 检查候选元素或文本范围和 frame 宿主的可见性及非零尺寸，并在操作前重算。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证可见容器、跨进程 frame 零宽、非法选项和准备点击期间尺寸变化时停止输入；Electron 44/Xvfb socket 验证跨进程 frame。语义定位候选受可访问性树覆盖范围约束；macOS/Windows 本轮未测。

语义和 CSS locator 的 click/dblclick 增加左、中、右键及 Alt/Control/ControlOrMeta/Meta/Shift 修饰键，拒绝未知参数与 force:true，保留目标重查和输入后不重试。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证可信左右键、组合修饰、中键双击及跨进程 frame；Electron 44/Xvfb socket 验证跨进程右键与 Shift。语义查询仍依赖可访问性树，macOS/Windows 本轮未测。

语义与 CSS locator 的单击和双击共用鼠标按下/释放路径；按下或释放结果未知时尝试释放同一按钮和修饰键，保留原错误且不重发点击或双击后半段。SDK 66 项通过，故障注入覆盖释放失败与右键 Shift 参数；Linux ARM64 Chromium 原生消息及 Electron 44/Xvfb socket 实页回归通过。释放重试可能发生在页面已响应之后；macOS/Windows 本轮未测。

语义与 CSS locator 新增 downloadMedia，定位首个匹配并在隔离 world 内触发媒体链接下载；使用现有下载等待、scope 授权和操作前重查，失败后不重发。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证链接下载与跨来源拒绝，隔离测试 profile 显式允许自动下载；Electron 44/Xvfb 验证两类 locator、data GIF 和跨进程 frame 实际落盘。HTTP(S) 媒体暂限同来源，重定向与自动下载策略由浏览器处理；macOS/Windows 本轮未测。

新增 tab.dom_cua 主文档和开放 shadow root 可见节点快照、节点单击/双击、焦点输入/按键及节点或视口滚动。节点 ID 绑定快照，点击前重核文本、角色、标签、CSS 匹配、位置及命中；节点动作后失效。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证可信点击、旧 ID 和文本变化拒绝；Electron 44/Xvfb 验证节点点击、焦点输入及滚动。当前仅主 frame，匹配数上限 1000，子 frame 快照仍待实现；macOS/Windows 本轮未测。

DOM CUA 快照扩展到可读取的同进程和跨进程 frame，每个节点携带 frame_id 和所属 frame 快照；点击前复核 frame、目标和名称，节点滚动通过 frame 链换算坐标。SDK 66 项通过；Linux ARM64 Chromium 原生消息验证跨进程节点可信点击；Electron 44/Xvfb 验证跨进程节点点击和滚动。每个 frame 按自身视口筛选，视口外的 frame 可能仍有节点；总匹配上限 1000，macOS/Windows 本轮未测。

DOM CUA 可见快照检查每层 frame 宿主与父视口相交；快照期间 frame 可见性变化时要求重新观察，节点点击和滚动前重新检查 frame 是否在视口中。SDK 66 项通过；Linux ARM64 Chromium 原生消息和 Electron 44/Xvfb 均验证移出视口的跨进程 frame 被排除、旧 ID 被拒绝、恢复后可信点击。部分裁剪尚未完整反映在快照中；macOS/Windows 本轮未测。

DOM CUA 使用独立临时节点表和代次控制快照发布；同一实例的后续快照或输入使未完成观察失效，输入期间拒绝新的观察和输入，结束后清理节点。SDK 67 项通过，定向覆盖并发观察及观察与输入交错；Linux ARM64 Chromium 原生消息与 Electron 44/Xvfb 实页回归通过。该并发协调限定单个 DOM CUA 实例；macOS/Windows 本轮未测。

同一 browser 内相同 tab ID 的句柄共享 DOM CUA 节点表和并发状态；快照绑定连接代次，重连后旧 ID 失效，鼠标和节点滚动派发使用相同代次检查。SDK 68 项通过；Linux ARM64 Chromium 原生消息验证多句柄共享、断线重连后拒绝旧节点；Electron 44/Xvfb 实页回归通过。不同 browser 实例之间的协调仍依赖调用方；macOS/Windows 本轮未测。

DOM CUA 快照沿 frame 链逐层换算主视口与 frame 内容区域的交集，过滤 frame 部分露出时落在可见区域外的节点，并在输出前重查裁剪几何；旋转或倾斜 frame 显式报错。SDK 68 项通过；Linux ARM64 Chromium 原生消息与 Electron 44/Xvfb 验证部分露出的跨进程 frame，Electron 验证旋转拒绝。嵌套 frame 裁剪及普通 overflow 祖先裁剪仍需专项实测；macOS/Windows 本轮未测。

DOM CUA 在每个 frame 批量使用浏览器 IntersectionObserver 排除被 overflow 祖先完全裁掉的节点，并重查观察结果；后台标签三秒内无法完成观察时回退几何筛选并标记 visibility_incomplete。SDK 68 项通过；Linux ARM64 Chromium 原生消息与 Electron 44/Xvfb 均验证普通 overflow、跨进程内嵌套 frame 的部分裁剪；Chromium 验证后台回退。IO 不检测遮挡，输入仍检查命中；macOS/Windows 本轮未测。

DOM CUA 节点摘要加入关联 label、aria-labelledby、控件类型、禁用与勾选状态；输入前重核这些字段，避免状态变化后对旧节点操作，摘要不输出表单值。SDK 68 项通过；Linux ARM64 Chromium 原生消息和 Electron 44/Xvfb 验证多段标签、禁用、密码值排除与勾选状态变化拒绝。名称依据 DOM 属性近似计算，完整可访问名称规则仍待覆盖；macOS/Windows 本轮未测。

新增 Codex 风格 browser.tabs、browser.user 和 nameSession；支持会话内列表、查询、创建、选择、保留/清理，用户标签列表与显式接管，以及历史查询；tab 增加 title/url。SDK 69 项通过，覆盖权限范围、重复保留项和跨 realm 日期；Linux ARM64 Chromium 原生消息验证 session 标签入口和 REPL 清理，Electron 44/Xvfb 验证 scope 内选择、创建与保留。Chrome selected 使用 session 逻辑活动标签，Electron 使用呈现状态；Electron 历史不可用，macOS/Windows 本轮未测。

持久 JS REPL 新增 agent.browsers.list/get，按公开 ID 或唯一 extension/iab 类型发现和选择浏览器，复用默认会话连接并保留宿主授权范围；无法响应或歧义时报错，宿主失效时仍可选择独立扩展。SDK 69 项通过，覆盖多连接歧义和复用；Linux ARM64 Chromium 原生消息与混合 REPL 验证真实扩展、嵌入式授权通道、独立撤销，Electron 44/Xvfb 实页回归通过。能力元数据沿用后端格式，macOS/Windows 本轮未测。

JS SDK 增加 browser/tab capabilities.list/get 和 WebMCP 高层工具列表/调用，复用 Chrome 的功能开关、标签归属和 registration_id 快照校验，工具调用不重放。SDK 70 项通过；Linux ARM64 Chromium 原生消息验证页面注册、调用和重新列举后旧 ID 失效；Electron 44/Xvfb 验证 WebMCP 未提供时明确拒绝。Electron WebMCP 尚未实现，macOS/Windows 本轮未测。

Electron scope 新增默认关闭的 webmcp 选项，复用 Chrome 页面桥接源码，在新建标签导航前安装；page.control 授权的 scope 可发现并调用当前页面工具，注册快照变化或导航后旧 ID 失效，排队调用在授权撤销后不执行。SDK 70 项和 Electron 50 项检查通过；Linux ARM64 Electron 44/Xvfb 实页验证启动脚本注册、调用、重新列举和导航失效。Popup 在初次使用时安装桥，初始加载注册的工具可能不可用；子 frame 工具、macOS/Windows 本轮未测。

Electron WebMCP opt-in scope 为标准 adapter 的标签和 popup 配置 sandbox preload，在页面脚本前通过 contextBridge 初始化桥；未启用的 scope 不配置 preload。Electron 51 项检查通过，Linux ARM64 Electron 44/Xvfb 实测 popup 初始脚本注册工具、发现及调用。使用实验性 executeInMainWorld，自定义 adapter 需接入 preload，子 frame 工具及 macOS/Windows 本轮未测。

Electron WebMCP 增加独立可复跑 smoke；pnpm pack 确认分发包含 preload，macOS ARM64 对解包产物本机重建原生 addon 后验证主页面与 popup 初始化、发现和调用，Linux ARM64 使用既有原生 addon 验证相同解包产物。Electron 51 项检查通过。macOS 完整 upload smoke 两次在首个 CUA move 返回 IAB_INPUT_OUTCOME_UNKNOWN，鼠标输入结果和原因仍待排查；Windows 未测。

Electron 鼠标准备与滚轮现在同时检查宿主窗口状态和 WebFrameMain.visibilityState；macOS 窗口可见但主 frame 隐藏时临时解除后台节流并恢复。Electron 52 项通过；Linux ARM64 Electron 44/Xvfb 完整 smoke 通过；macOS ARM64 Electron 44 完整 smoke 越过原先首次 CUA move 超时，并完成后续多项交互，最终在跨进程 frame 内 DOM 滚动未发生位移处失败。后台快照可返回 visibility_incomplete，测试按标记处理；macOS 跨 frame 滚动仍待排查，Windows 未测。

DOM CUA 跨进程 frame 的节点滚动沿 frame 会话派发可信滚轮，沿用点击的坐标换算和主视口校验；滚轮后等待子 frame 绘制，后台绘制受限时最多等待一秒。SDK 70 项通过；macOS Electron 44 和 Linux ARM64 Electron 44 的完整 socket 场景通过，覆盖跨进程 frame 的实际滚动；Linux ARM64 Chromium 原生扩展回归通过。Windows 未测，绘制等待超时后仍需由调用方观察实际滚动结果。

跨进程 DOM 滚动的绘制等待使用目标 frame 的隔离 world，页面覆盖 requestAnimationFrame 时仍能完成；等待命令限制为三秒，异常时提示滚轮已发送并要求先观察。SDK 70 项通过；macOS 和 Linux ARM64 Electron 44 socket 实页，以及 Linux ARM64 Chromium 原生扩展实页均验证滚动和页面覆盖。隔离 Linux Chromium 150 后台标签探针中，焦点模拟后截图可返回且 wheel 事件可信，但滚动位移仍为零，合成手势三秒超时；仍需解决后台呈现。

语义定位器新增 isChecked，读取经过目标、状态及作用域重核的可访问性勾选状态；混合状态和无二元勾选状态的目标报错。SDK 70 项通过；Linux ARM64 Chromium 原生扩展验证跨进程复选框变化、混合状态与非勾选控件，macOS 和 Linux ARM64 Electron 44 socket 实页验证跨进程复选框。Windows 未测。

DOM CUA 在 frame 文档报告 hidden 时直接采用既有几何回退并标记 visibility_incomplete，跳过可能因后台节流延迟三秒的 IntersectionObserver；可见文档保持原有观察和变化检查。SDK 70 项通过；Linux ARM64 Chromium 原生扩展后台专项验证无交叉观察调用及不完整标记，完整原生 smoke 通过；macOS 与 Linux ARM64 Electron 44 完整 socket smoke 通过。后台回退仍无法过滤 overflow 祖先裁剪，Windows 未测。

DOM CUA 后台几何回退沿祖先滚动容器边界做保守矩形裁剪；处理绝对和固定定位跨越祖先容器，复杂裁剪继续标记 visibility_incomplete。SDK 70 项通过；Linux ARM64 Chromium 原生扩展后台专项验证裁掉的节点与越出容器的固定节点，完整原生 smoke 通过；macOS 和 Linux ARM64 Electron 44 实页回归通过。圆角、clip-path 和遮挡仍不由该回退完整表示，Windows 未测。

CSS 与语义定位器新增 inputValue，使用隔离 world 读取 input、textarea 和 select 的当前值，密码字段明确拒绝，单值限制 30000 字符；多选 select 返回浏览器 value 属性。SDK 70 项通过；Linux ARM64 Electron 44 实页验证跨进程文本框、文本域、下拉框、密码及不支持的控件；macOS Electron 44 和 Linux ARM64 Chromium 原生扩展验证跨进程文本框及拒绝情况。Windows 未测。

Playwright 风格入口新增 evaluate，接受函数和单个 JSON 参数或表达式字符串，等待 Promise 并返回页面结果；函数执行于页面上下文，可修改页面且不能访问调用侧闭包。SDK 70 项通过；macOS 和 Linux ARM64 Electron 44，以及 Linux ARM64 Chromium 原生扩展实页验证异步返回、特殊字符参数与错误传播。Windows 未测。

直线拖拽在鼠标按下请求结果未知时尝试释放按钮，保留原错误；普通滚动、修饰键滚动和 Electron 后台滚动超时统一提示结果未知并要求观察后再操作，不重发滚轮。SDK 70 项通过，覆盖按下失败、普通滚动与 Electron 超时；Linux ARM64 Chromium 原生扩展和 Electron 44 完整实页回归通过。释放请求本身可能失败；macOS 和 Windows 本轮未测。

页面 evaluate 检查 CDP 远程值：undefined 返回 null，NaN、BigInt 等 CDP 标记为不可序列化的结果明确报错，缺失结果的协议响应也报错。SDK 70 项通过；macOS 和 Linux ARM64 Electron 44 以及 Linux ARM64 Chromium 原生扩展实页验证 undefined、NaN、BigInt 和正常异步对象。Windows 未测；嵌套对象采用浏览器 CDP 的按值序列化规则。

Playwright evaluate 的 JSON 参数使用带计算属性的安全字面量编码，页面覆盖 JSON.parse 时参数保持原值，__proto__ 作为普通数据键保留。SDK 70 项通过；macOS 和 Linux ARM64 Electron 44 及 Linux ARM64 Chromium 原生扩展实页均验证页面篡改、特殊键和异步求值。参数依旧遵循 JSON.stringify 转换规则，Windows 未测。

Playwright evaluate 参数在请求发送前拒绝非有限数、负零、嵌套 undefined、稀疏数组、函数、符号和 BigInt，防止 JSON 转换静默改变这些值；对象的 toJSON 仍按 JSON 转换执行。SDK 71 项通过，专项验证拒绝时零浏览器请求；Linux ARM64 Chromium 原生扩展与 Electron 44 完整实页回归通过。macOS 和 Windows 本轮未测。

browser.newTab({url}) 在导航失败时关闭刚创建的标签；清理失败时以 AggregateError 同时保留导航和清理错误，便于重新检查会话。SDK 72 项通过；macOS 和 Linux ARM64 Electron 44 与 Linux ARM64 Chromium 原生扩展实页验证无效地址失败后会话标签数量恢复。清理结果未知时仍可能留有标签；Windows 未测。

更新仓库随附 skill：优先使用 fork 的持久 JS REPL、浏览器发现及标签生命周期，补充 DOM CUA、页面求值和 WebMCP 的使用边界；安装参考区分源码与上游发布包，SDK 参考明确发布包能力可能不同。skill 格式验证、打包检查及当前 CLI install-manifest 参数核对通过；未更改用户现有浏览器注册或 MCP 配置。

调整随附 skill 的授权提示：已明确请求的浏览器交互遵循用户授权与宿主权限，需要用户亲自完成或范围不明确时再请求协助。skill 格式和打包检查通过；浏览器权限与运行时代码未更改。

截图结果在输出前校验 Base64、PNG 签名、IHDR 尺寸和 IEND 结束标记；无效数据直接报错，测试桩改用真实 PNG。SDK 72 项通过，覆盖无效编码、错误格式和截断；macOS 与 Linux ARM64 Electron 44、Linux ARM64 Chromium 原生扩展实页截图及完整回归通过。该检查不完整解码图像或校验所有 chunk；Windows 未测。

CSS 和语义定位器新增 boundingBox，返回主 frame CSS 视口坐标，跨 frame 逐层换算边框与缩放；读取前后重查目标与 frame 几何，隐藏目标返回 null，旋转或倾斜 frame 报错。复用 DOM 快照的 frame 几何逻辑。SDK 72 项通过；macOS 与 Linux ARM64 Electron 44 及 Linux ARM64 Chromium 原生扩展实页验证跨进程 frame 缩放，Linux Electron 额外验证嵌套 frame、隐藏目标与旋转拒绝。结果可能在返回后变化；Windows 未测。

语义输入支持可编辑 combobox；原生 select 或只读组合框在鼠标输入前拒绝文本。隔离 Linux ARM64 Chromium 原生扩展完成 MDN 真实页面观察、标题定位、截图、搜索框填写并读取结果、跳转、返回和标签清理；此前搜索框因 combobox 角色被拒绝。SDK 72 项通过；macOS 和 Linux ARM64 Electron 44、Linux ARM64 Chromium 原生扩展实页验证跨进程可编辑 combobox 可信输入及原生 select 无鼠标输入拒绝。页面布局可能变化，Windows 未测。

语义 hasText/hasNotText 筛选按可访问性树顺序纳入祖先归属明确的生成文字，并保留归属无法确定时的拒绝。隔离 Linux ARM64 Chromium 原生扩展完成 TodoMVC React 真实页面新增、勾选、筛选、编辑和清理；原实现遇到生成文字时拒绝列表项筛选。SDK 72 项通过；macOS 和 Linux ARM64 Electron 44 与 Linux ARM64 Chromium 原生扩展验证跨进程 frame 伪元素文字、组合匹配和动态变化。部分无法确定祖先的文本仍会报错；Windows 未测。

DOM CUA 单击和双击在目标仍位于可见匹配集时允许无关节点变化，继续重核文档、frame、目标身份、状态、稳定位置和命中；普通 CSS 定位器仍要求匹配集合一致。隔离 Linux ARM64 Chromium 原生扩展在 TodoMVC React 实页完成全选、取消、DOM 双击编辑、旧 ID 拒绝和键盘输入；此前滚动导致无关按钮出现使双击失败。SDK 72 项通过；macOS 与 Linux ARM64 Electron 44、Linux ARM64 Chromium 原生扩展实页验证双击期间无关节点出现及旧目标拒绝。目标语义上下文仍可能在重查后变化；Windows 未测。

Chrome 与 Electron 的会话标签列表提供作用域内 openerTabId；新增 tab.playwright.expectPopup，动作前记录已有标签，轮询匹配打开者，动作完成后复核结果，同一 browser 实例同一打开者只允许一个等待。SDK 73 项与 Electron 52 项通过，覆盖歧义、并发、超时和关闭；Chrome 扩展专项验证不暴露其他会话的 opener，Linux ARM64 Chromium 原生扩展及 macOS/Linux Electron 44 实页验证新标签导航与关闭。快速关闭或缺少 opener 元数据的标签可能超时；Chrome 来源未知的新标签在最终清理时释放而非关闭，Windows 未测。

隔离 Linux ARM64 Chromium 原生扩展在 MDN HTML 文档点击“View this page on GitHub”，expectPopup 识别新标签，随后确认目标 GitHub URL 并关闭标签。新标签返回时 URL 曾为空，导航完成后才可读取；SDK 文档已说明这一时序。

同一真实 MDN 到 GitHub 新标签路径进一步验证 expectPopup 后立即调用 waitForURL，等待导航完成成功；SDK 文档补充串联示例。

浏览器历史高层接口返回具名 BrowserHistoryEntry 类型并校验后端数据，支持 TypeScript 直接使用 url、dateVisited 和可选 title。隔离 Linux ARM64 Chromium 在真实 MDN 访问后查询其历史记录成功；Electron 不提供历史记录。

语义定位器支持同标签、同 frame 的 and/or 组合，按观察顺序去重并支持后续位置与筛选，输入前沿用匹配复核；组合限八层。SDK 75 项通过；隔离 Linux ARM64 Chromium 原生扩展验证跨 frame 观察结果组合、可信点击和页面变化后的重算。CSS 与语义定位器混合组合、Windows 和 Electron 本轮未测。

CSS 与语义定位器支持双向 and 交集，按 frame 和后端节点身份求交，沿用输入前重新匹配；语义根作用域的 CSS 操作数暂不支持。SDK 76 项通过；隔离 Linux ARM64 Chromium 原生扩展验证双向交集、可信点击及页面变化后的结果。混合 or、Electron 与 Windows 本轮未验证。

macOS Electron 44.7 socket 实测跨进程 frame 的语义 or 与 CSS/语义双向 and；匹配后移除 CSS 属性时，操作前复核拒绝点击，页面没有收到点击事件。SDK 76 项通过，覆盖交集变化的复核。Windows 与 Linux Electron 本轮未测。

expectPopup 的时间预算覆盖动作前标签读取，准备超时或连接变化时不会发出动作；动作开始后的超时仍提示结果未知。SDK 77 项通过；隔离 Linux ARM64 Chromium 原生扩展在真实 MDN 到 GitHub 新标签路径验证正常行为。Electron 与 Windows 本轮未测。

expectNavigation 的超时覆盖监听准备和 frame 查询；准备期间超时或连接变化不会发出动作，动作开始后超时标明结果未知。SDK 78 项通过；隔离 Linux ARM64 Chromium 原生扩展验证真实点击、导航及目标页面。Electron 与 Windows 本轮未测。

waitForURL 正数超时覆盖单次浏览器读取，零超时仍执行一次检查；超时后已发出的只读请求可能继续完成。真实 MDN 到 GitHub 新标签验证发现关闭标签与 Chrome 会话清理竞争，现逐个清理并只忽略对应标签已消失的错误，其余错误继续上报。SDK 79 项和 Chrome 清理专项通过；隔离 Linux ARM64 Chromium 完成等待、超时、关闭及清理。Electron 与 Windows 本轮未测。

waitForLoadState 正数期限覆盖启用事件与状态读取，超时清理监听；零超时检查一次当前状态。修正 expectNavigation 与 expectPopup 的首次按需连接代次检查。SDK 80 项通过；隔离 Linux ARM64 Chromium 实测真实 MDN 加载、按需连接的新标签与同页面导航。Electron 与 Windows 本轮未测。

goto 的时间预算覆盖准备、导航与页面加载；准备超时不会导航，调试器连接阶段超时会阻止迟到的命令，已开始的导航超时提示结果未知。SDK 82 项通过；隔离 Linux ARM64 Chromium 原生扩展验证按需连接访问真实 MDN 与同页面片段导航。Electron 与 Windows 本轮未测。

CDP 命令的显式超时同步用于 socket 请求及调试器附着，并保留 2 秒响应余量；goto 准备阶段传递剩余预算，外层仍按原期限结束。SDK 83 项通过，真实 Unix socket 测试覆盖慢附着和慢响应；隔离 Linux ARM64 Chromium 原生扩展访问 MDN 并等待加载成功。Electron 与 Windows 本轮未测。

reload 支持显式超时，统一限制准备、刷新命令和加载等待；准备超时不发送刷新，命令连接阶段超时会阻止迟到发送，已发送命令的超时提示结果未知。SDK 84 项通过；隔离 Linux ARM64 Chromium 对真实 MDN 页面验证刷新和页面状态重置。Electron 与 Windows 本轮未测。

selectOption 增加零起始 index 描述符，可与 value、label 同时约束；CSS 与语义定位器沿用选项复核和合成 input/change 事件，非法索引及禁用选项被拒绝。SDK 84 项通过；隔离 Linux ARM64 Chromium 验证普通页面与跨进程 frame，macOS Electron 44.7 socket smoke 验证跨进程 frame 的两类定位器。Windows 未测。

CSS 与语义 locator 的 check/uncheck/setChecked 校验 force 和未知参数；force:false 可用，force:true 在任何浏览器输入前明确拒绝，避免参数被静默忽略。SDK 85 项通过；隔离 Linux ARM64 Chromium 验证两类定位器的可信勾选与拒绝后状态不变。Electron、Windows 与强制勾选功能仍未验证或实现。

语义 selectOption 在修改前重新匹配完整选项条件并检查祖先禁用状态；期间新增同值选项或祖先变为禁用时停止且不派发事件。SDK 85 项通过；隔离 Linux ARM64 Chromium 原生扩展验证两种变化并通过跨进程 frame 完整 smoke，回归场景保留在 smoke 中。Electron 与 Windows 本轮未测。

CSS 与语义 locator 的 click、dblclick、check、uncheck、setChecked 支持 force:true：跳过命中检查，保留目标、位置、稳定性和禁用检查；从主页面坐标派发可信鼠标事件，遮挡物可收到事件，勾选后仍复核状态。SDK 86 项通过；Linux ARM64 Chromium 验证遮挡层、跨进程 frame 和勾选失败；macOS Electron 44.7 socket smoke 验证跨进程 frame 的遮挡层接收事件。Windows 未测。

waitForURL 支持 waitUntil:commit，匹配当前主文档 URL 后无需等待 DOM 或加载完成；保留 load、domcontentloaded 与单次检查行为。SDK 87 项通过；隔离 Linux ARM64 Chromium 对分段加载页面验证 loading 阶段可返回且 load 阶段继续等待。Electron、Windows 与 networkidle 本轮未覆盖。

networkidle 实测：隔离 Linux ARM64 Chromium 在已加载页面发起 4 秒 fetch 后再启用 Network 与生命周期事件，浏览器重放旧 networkIdle，未重放进行中请求的 requestWillBeSent，随后仅出现 loadingFinished。因此单独使用 lifecycle 或延迟启用 Network 会提前判定空闲；SDK 继续拒绝该状态，错误和文档明确说明。后续实现需从可确认的基线持续跟踪请求、处理连接与 frame 生命周期，并对无法确定的既有请求保持明确状态。

URL 与加载状态检查改用主 frame 的隔离 world，避免页面脚本篡改 document.readyState 使等待提前返回；连接代次在 frame 查询后固定。SDK 88 项通过；隔离 Linux ARM64 Chromium 分段加载并伪造 complete 的实测确认加载前拒绝、加载后通过，完整原生扩展 smoke 与 macOS Electron 44.7 socket smoke 通过。完整 smoke 中同步更新已支持 force 的旧断言。Windows 未测。

持久 JavaScript MCP 的 js 工具支持 timeout_ms（默认 30 秒、上限 10 分钟）和 title；异步执行超时后提示可能仍有副作用，在其完成前拒绝新执行，完成后保留会话并隔离迟到输出。SDK 88 项通过；隔离 Linux ARM64 Chromium 原生扩展通过真实浏览器连接、超时、忙碌保护及恢复操作。同步无限循环阻塞 Node 事件循环，需要重启进程；Electron 与 Windows 本轮未测。

持久 JavaScript MCP 新增 js_reset，清空绑定并恢复浏览器帮助对象，已连接的浏览器会话与标签保留；执行仍活跃时拒绝重置。SDK 88 项通过；隔离 Linux ARM64 Chromium 原生扩展通过绑定清除、重新发现同一标签及继续操作。后台任务不会被取消，同步阻塞仍需重启 MCP；Electron 与 Windows 本轮未测。

持久 JavaScript MCP 用 Acorn 识别顶层 const/let 与具名 class 声明并转为可重复声明的绑定；块级作用域保持原样，同一段代码中的重复声明仍报错。顶层变量可被重新赋值，解析失败时交由原 Node REPL 处理。SDK 88 项通过；隔离 Linux ARM64 Chromium 验证重复绑定后复用浏览器标签，打包并在独立 npm 目录验证运行时依赖导入。Electron 与 Windows 本轮未测。

修复 REPL 类声明转换后相邻括号表达式被误当成调用的问题，并补充边界回归；SDK 88 项、Electron 52 项通过。macOS Electron 44.7 真宿主通过私有通道与 socket 的重复绑定、类语句、重置与标签复用；完整 example smoke 在早期后台输入返回 IAB_INPUT_OUTCOME_UNKNOWN，未到达 REPL 检查。Windows 未测。
