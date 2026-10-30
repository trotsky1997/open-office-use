# Browser harness modernization

## 目标

基于现有 Chrome 和 Electron 路线，提供适合持续多轮操作的浏览器 harness，逐步对齐当前 Codex 的可观测性和交互体验。

## 范围与现状

- 复用已有 extension、session/tab ownership、Electron scope 和 SDK。
- 当前 Codex 的统一入口提供持久 JavaScript 会话、浏览器发现、标签页绑定、可访问性状态、截图与基于状态的操作。具体支持依 backend 而异。
- 本仓库已有 Chrome 和 Electron 传输、会话与底层 CDP；JavaScript SDK 的 `domSnapshot` 通过可访问性树返回角色、名称、状态及可读取 frame。Electron MCP 已提供原始 AX tree 和截图。
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
- [x] getByRole 支持 checked、disabled、pressed、selected、expanded 状态筛选，并拒绝未知选项；禁用目标可观察和悬停，修改前检查目标及祖先。
- [x] 观察包括勾选、展开等控件状态；动作前重新核对状态，防止对变化后的控件执行旧操作。
- [x] 在嵌套 open/closed Shadow DOM 中校验目标和各层宿主的命中；隔离 Chromium 验证可信点击与覆盖拒绝。
- [x] 可选观察同进程 iframe，换算嵌套 frame 坐标并拒绝导航后的旧目标；macOS Chromium 原生消息链路和 Electron 页面验证可信点击。
- [x] Chrome 跨进程 iframe：附着子 session、跨进程和同进程嵌套坐标换算、观察、可信点击和文本输入；隔离原生消息链路验证导航与遮挡拒绝。
- [x] Electron 受授权范围约束的跨进程 iframe：macOS Electron 强制站点隔离页面验证可信点击、文本、导航失效及遮挡拒绝；会话仅限所属标签和 iframe。
- [x] Linux ARM64 隔离 Chromium 150：原生消息链路验证跨进程与嵌套 frame 的可信输入、导航、遮挡和重连。
- [ ] 跨进程 iframe 的其他平台与动态 frame 场景验收。 Linux ARM64 Chromium 150 原生链路已验证跨站 frame 同一元素导航后旧观察拒绝输入，新定位器可可信点击；替换整个 frame 后旧观察拒绝输入；frameLocator 读取宿主布局后，Linux 隔离 headless 三次实验及 macOS Electron 同进程 frame 验证新定位器可信点击。Linux 隔离 headless 的直接索引和全局语义定位路径各连续三次验证通过；其他平台待验证。
- [x] 同一文档支持有序文本差异；导航和截断后回到完整基线。
- [x] domSnapshot 使用有界的可访问性状态与 frame 内容，标出截断或不可读取的 frame；输出不直接暴露可操作索引。
- [x] 可访问性观察和 domSnapshot 按父子关系排列并缩进；Linux 隔离 Chromium 与 Electron 44 验证容器和后代关系。
- [x] 可读取 frame 通过 DOM.getFrameOwner 定位并嵌入所属可访问节点；无法确定位置的内容保留在明确标记的独立段落。
- [x] 语义定位器支持批量读取匹配节点的原始文本，保留作用域与 frame 校验；Linux 隔离 Chromium 原生消息和 Electron 44 socket 验证，Electron 覆盖跨进程 frame。
- [x] 按 CSS viewport 坐标点击和滚动；本机隔离 Chrome 验证真实鼠标和滚轮行为。
- [x] 语义定位器与 CSS viewport 坐标悬停；macOS/Linux Chromium 与 macOS Electron 跨进程 frame 验证可信 mouseenter，Electron 验证坐标悬停。
- [x] `frameLocator` 按 iframe 元素的原生 CSS 选择器限定语义定位，支持逐层嵌套；重核 frame 树和选择器，歧义时报错。Linux Chromium 与 Electron 44 跨进程实测。
- [x] frame 选择器在命名隔离 world 执行；Electron 限制所属 frame、world 配置与准备超时。Linux 实测页面篡改 matches 后选择仍正确。
- [x] CSS viewport 拖拽；隔离 Chromium 和 macOS Electron 页面验证可信滑块输入。
- [x] US 键盘数字和常见标点，包括 Shift 和快捷键组合；真实输入产生可信事件。
- [x] 定位器按键先聚焦并校验目标，在跨进程 frame 中路由可信按键；输入失败后尝试释放按键。
- [x] 当前焦点按键通过 frame 宿主链识别调试会话，发送前重核焦点和 frame；Linux Chromium 与 Electron 44 验证跨进程 frame 可信输入。
- [x] 当前焦点 Unicode 文本输入复用 frame 路由校验，发送文本后由调用方验证目标结果。
- [x] `tab.cua` 提供坐标鼠标、路径拖拽、滚动、按键、文本与截图；Electron 44 实页验证鼠标修饰键及跨 frame 输入。
- [x] Chrome 显式 `bringToFront()` 可呈现任务标签；隔离 Linux ARM64 Chromium 150 headless 与 Xvfb 前台标签验证普通及修饰键滚动、位移和截图。
- [x] Chrome 与 Electron 暴露所属标签的物理选择和窗口状态；Chrome 即使页面焦点模拟改变 visibilityState 也读取浏览器实际标签状态。
- [ ] 修复隔离 Linux ARM64 Chromium 150 后台标签的 wheel 超时、嵌套滚动未生效及截图超时；常规桌面仍需验证。
- [x] 常用按键与修饰键组合；Chrome 和 Electron 真实页面验证可信 Enter 和全选。
- [x] Electron 已呈现的隐藏窗口通过可信 wheel 事件滚动，并限制等待时间；超时后恢复队列。
- [x] macOS Electron 可见宿主窗口坐标滚动通过真实页面验证。
- [x] Electron 输入预备与截图的有界超时；超时释放队列并阻止迟到输入。
- [ ] Electron 未呈现页面滚动，以及其他系统与最小化窗口的实机验证。
- [x] Chrome 用户标签发现与显式接管，以及 socket 断开后的后续连接恢复。
- [x] Chrome REPL 探测 socket；多连接或探测结果未知时要求显式选择，避免误用最近活跃 profile。
- [x] 隔离 Chromium 中，真实扩展后台、Go relay 和 SDK/REPL 完成观察、可信点击、差异、截图及清理；扩展和 relay 间使用测试 CDP 桥。
- [x] Linux ARM64 隔离 Chromium 150：真实原生消息清单、扩展和 Go host 启动链路，SDK/REPL 可信点击、差异、截图与清理通过。
- [x] Linux ARM64 隔离 Chromium 150 完整原生消息 smoke：近期导航、下载 URL、正则定位、标题层级、动态等待、双击和跨进程 frame 检查通过。
- [x] Linux ARM64 Electron 44.7：Xvfb 和原生 socket 验证语义读取、同文档导航、下载 URL，以及宿主显示后隐藏的跨进程 frame 标题、可信双击和文件传输。
- [x] Chrome 与 Electron 44 提供文本和结构化剪贴板；Electron 宿主分别授予读写权限。Linux ARM64 隔离 Chromium 与 Electron/Xvfb 验证文本、HTML 和 PNG。
- [x] macOS ARM64 隔离 Chromium 141：临时 profile 原生清单和临时复制的 Go host 经 SDK/REPL 完成可信点击、差异、截图与清理。
- [x] Chrome 与 Electron REPL 共用浏览器状态入口和基于浏览器 ID 的连接；Electron 仅暴露宿主授权 scope。
- [x] 宿主显式启用时，同一 REPL 发现并按 ID 路由 Electron 和 Chrome；真实 Chrome 原生链路与 host 授权 fixture 验证独立撤销。
- [x] 定位器按可访问后代文字筛选，支持 hasText 和 hasNotText；输入前及聚焦后重核，限制缺失和过长文本。
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

- [ ] 完成通用 CSS locator 的完整 API；已实现有界链式作用域、查询、读取、可信点击、悬停、按键及文本填写，覆盖开放 shadow root 和 frame。

- [x] CSS 和语义 locator 的 click 正数超时覆盖输入前准备；输入开始后报告结果未知，保留鼠标释放。macOS Electron 实页验证。
- [x] CSS 和语义 locator 的 dblclick 在同一正数期限内停止迟到的第二次按下；过期后停止新的滚动测量。macOS Electron 实页验证。
- [x] CSS 和语义 locator 的 hover 正数期限覆盖准备和鼠标移动；超时后禁止迟到的移动，已发出时报告结果未知。macOS Electron 实页验证。
- [x] 观察索引支持编辑框文本选择，含前后文消歧、光标位置和富文本；macOS Electron 验证主文档及跨进程 frame。
- [x] 文本选择检查只读祖先；macOS Electron 实页验证只读目标、Shadow DOM 富文本及跨进程 frame 选择后可信替换。
- [x] CSS 与语义 locator 支持 pressSequentially，逐键检查焦点、超时后停止后续输入；macOS Electron 实页覆盖 Unicode、焦点变化及跨进程 frame。
- [x] Linux ARM64 Chromium 150 原生消息实测文本选择、焦点内替换及逐字符输入，覆盖主文档与跨进程 frame；修复空上下文参数传输。
- [x] playwright.evaluate 启用 Chromium 副作用检查与有界执行；macOS Electron 和 Linux ARM64 Chromium 原生链路验证 DOM 读取、同步/异步修改拒绝及执行超时。
- [x] playwright.evaluate 的准备超时阻止连接恢复后的迟到执行；macOS Electron 与 Linux Chromium 原生消息链路验证。
- [x] CSS 与语义 locator.evaluate 支持只读元素求值、身份重核和可中止执行；macOS Electron 与 Linux Chromium 验证主文档及跨进程 frame。
- [x] 单 frame 的 CSS 与语义 locator.evaluateAll 支持有序批量、空数组、身份重核和可中止执行；macOS Electron 与 Linux Chromium 原生链路验证。
- [ ] 只读 locator.evaluateAll 的跨 frame 统一元素数组；当前明确拒绝跨 frame 匹配。
- [x] getAXStateAndScreenshot 一次返回有索引状态与 PNG；捕获期间重核文档、frame、连接及观察，失败时清除差异基线。macOS Electron 与 Linux Chromium 原生链路验证。
- [x] 观察索引支持方向与页数滚动，发送前检查目标及 frame，复用可信滚轮和连接代际校验；macOS Electron 与 Linux ARM64 Chromium 主文档及跨进程 frame 验证。
- [x] 索引或当前焦点支持纯文本、Markdown 源码和 HTML 粘贴，可选纯文本回退；Linux ARM64 Chromium 原生消息及 Electron 虚拟显示实测可信 paste 与跨进程 frame。Electron 私有通道连接状态与剪贴板拒绝路径通过测试。
- [x] Chromium 清空富文本保留单个 BR 占位时按空内容校验；macOS Electron 与 Linux Chromium 实页验证。
- [x] Electron 客户端取消和超时通知宿主，阻止排队中的迟到输入；已派发操作报告结果可能未知。
- [x] Electron 文件选择等待响应取消并释放拦截；队列中尚未开始的等待取消时保留其他命令。macOS Electron 实页验证取消、重试与授权上传。
- [x] CSS 和语义 locator 的 check/uncheck 正数期限覆盖点击准备；派发后提示结果未知。macOS Electron 实页验证超时后无迟到点击及正常恢复。
- [x] CSS 和语义 locator 的 press 正数期限覆盖准备、聚焦与按键；超时停止后续按键并释放已按下按键。macOS Electron 实页验证延迟聚焦后无迟到输入。
- [x] CSS 与语义 locator 的 fill、clear、type 正数期限覆盖准备与写入；已派发时报告结果未知。macOS Electron 实页验证全选延迟后无迟到文本。
- [x] CSS 与语义 locator 的 selectOption 正数期限覆盖准备与提交；macOS Electron 实页验证迟到提交被取消及正常结果。
- [x] Linux ARM64 Chromium 150 原生消息链路验证 CSS 与语义 locator 的 fill、press、check、selectOption 期限及恢复；跨进程 frame 验证 press 超时与后续 fill。
- [x] Chrome relay 丢弃无匹配请求的扩展响应，防止连接断开后的迟到响应跨客户端传播；双客户端回归及 Linux 原生消息链路验证通过。
- [x] Chrome SDK、relay 和扩展贯穿 CDP 请求取消；扩展准备阶段检查取消，已提交浏览器的操作报告结果可能未知。Linux ARM64 原生消息链路注入扩展延迟验证通过。
- [ ] Chrome 非 CDP 请求的扩展端取消与资源清理，以及 Windows 实机验收。
- [x] Chrome 文件选择与下载开始等待响应请求取消，释放等待槽并清理选择器拦截；Linux ARM64 原生消息链路验证取消后可重新等待。
- [x] Chrome 下载完成路径等待响应取消并移除监听器；Linux ARM64 原生消息链路通过测试探针验证。
- [x] Chrome WebMCP 桥接准备响应取消，已调用页面工具收到 AbortSignal；Linux ARM64 原生消息链路实测。页面工具可忽略信号，已派发效果可能未知。
- [x] Chrome WebMCP 延迟或已取消的旧列表不会覆盖新工具注册；Linux ARM64 原生消息实测新注册仍可调用。
- [x] Electron WebMCP 同步 Chrome 页面桥，取消时向已调用工具发送 AbortSignal 并释放标签队列；macOS Electron 实页验证。
- [x] Linux ARM64 Electron 44.7 socket 实测 WebMCP 工具取消及挂起列表取消后的新注册调用。
- [x] Chrome WebMCP 内容桥及后台内部等待超时向页面传播取消；Linux ARM64 原生消息实测挂起列表超时与恢复。
- [x] Chrome 调试器事件按所属会话路由，未标记事件丢弃；Linux ARM64 原生消息实测两个会话的调试事件隔离。
- [x] Chrome 停止广播无来源标签归属的下载变化；命令层通过显式下载等待和路径查询工作。Linux ARM64 原生消息实测下载完成且另一会话未收到路径。
- [ ] Chrome 下载等待目前匹配浏览器内下一个下载，需研究可靠的来源标签归属；当前 session_id 用于路由，本地 socket 负责接入控制。
- [x] Chrome 文件选择与下载等待就绪事件按发起会话路由；Linux ARM64 原生消息双会话实测。
- [x] Chrome 下载路径句柄绑定发起等待的会话；Linux ARM64 原生消息双会话实测跨会话查询被拒绝。
- [x] 下载结果显式报告来源归属范围：tab、browser 或 unknown；macOS/Linux Electron 与 Linux Chromium 实际下载验证。
- [ ] 研究 Chrome Page.downloadWillBegin GUID 与 downloads 记录 ID 的可靠关联；实测前者提供来源标签和 frame，扩展记录使用独立 ID。
- [x] Chrome 对外下载句柄使用随机 UUID，扩展内部映射原生数字 ID 和所属会话；Linux ARM64 原生消息实测。
- [x] 新增按标签观察下载开始的 CDP 入口，返回 GUID、frame、URL 和建议文件名；Linux Chromium 实测主文档及已附着跨进程 frame，macOS Electron 实测主文档。
- [x] 下载开始观察为后续附着的跨进程 frame 启用 Page 事件；Linux Chromium 与 macOS Electron 实页验证，附着到启用之间仍有短暂遗漏窗口。
- [ ] 下载事件 GUID 与 Chrome 文件路径句柄的可靠关联仍待解决。
- [x] 下载开始观察期间，新 frame 的 Page.enable 阻挡后续 SDK CDP 动作直至准备结束；Linux Chromium 与 macOS Electron 实页注入延迟验证。
- [x] 下载开始观察成功后释放其他仍在准备的 frame 屏障；macOS Electron 实页验证并发情况。
- [x] SDK CDP 调用等待准备屏障和调试器附着时可取消；Chrome attach 授权后复核取消。Linux ARM64 原生消息实测屏障取消及无迟到输入。
- [x] Chrome 标签关闭事件按所属会话转发；Linux ARM64 Chromium 原生消息双会话实测等待退出和事件隔离。
- [x] Chrome 手动跨会话移组时撤销旧事件路由并通知 SDK，过滤延迟的旧组查询；Linux ARM64 原生消息双会话实测移动与关闭。
- [x] Chrome 标签移组时立即结束进行中的页面工具、剪贴板与文件选择请求；页面工具收到取消信号，剪贴板派发前与读取返回前复核归属。Linux ARM64 Chromium 原生消息实测页面工具取消；扩展测试覆盖剪贴板竞态。
- [x] Chrome 鼠标提示层准备期间复核标签归属及取消状态，移组时立即终止请求并释放动画等待；Linux ARM64 Chromium 原生消息实测延迟准备期间的移组。
- [x] Chrome 标签移组后清理旧会话的活动标签与鼠标提示状态，并通知页面刷新提示；Linux ARM64 Chromium 原生消息双会话验证旧状态清理。
- [x] CSS 与语义定位器的 waitFor() 默认等待可见，支持只指定超时；Linux ARM64 Chromium 实页验证两个定位器等待隐藏元素出现。
- [x] URL 等待和导航预期支持包含星号的全 URL glob，涵盖单星、双星、分组、转义与字面问号；导航动作前验证模式。Linux ARM64 Chromium 原生消息实测 history 路由。
- [x] URL 等待及导航预期接受同步 URL 条件函数，支持路径、查询参数等匹配；Linux ARM64 Chromium 原生消息实测 history 路由。
- [x] URL glob 改用有限状态匹配并限制模式与匹配规模，防止复杂星号组合阻塞等待；Linux ARM64 Chromium 原生消息实测路由匹配。
- [x] Chrome 后台滚轮超时错误明确提示重新呈现后可能迟到执行，要求呈现后再检查。Linux ARM64 Chromium 153 原生消息实测隐藏时滚轮超时，呈现后触发可信事件及滚动；背景截图成功，screencast 未解决滚轮。
- [x] JavaScript 对话框等待的正数超时覆盖监听准备及事件等待，超时取消尚未派发的准备；Linux ARM64 Chromium 原生消息验证超时后继续处理 confirm。
- [x] JavaScript 对话框监听准备绑定标签生命周期及连接代际；移组、关闭、调试器断开或 Page.disable 后，迟到准备无法恢复旧状态。Linux ARM64 Chromium 原生消息双会话验证移组后新会话可处理 confirm。
- [x] 弹窗绑定的子调试会话或其祖先会话脱离时失效；合成 CDP 事件覆盖不同会话的隔离，真实 frame 弹窗事件归属仍需更多平台验证。
- [x] 对话框事件带有来源 frame 时，frame 脱离后保留 frameDetached 状态并拒绝发送决定；Linux ARM64 Chromium 153 跨进程 frame 实测阻止决定派发，恢复过程仍待研究。
