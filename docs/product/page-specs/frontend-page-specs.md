# 前端逐页规格与完成标记

> 状态：目标态 + 当前实现标记。本文是前端逐页 PM 规格、已做/未做标记和测试看护清单。
> 前端总体架构见 `docs/product/frontend-product-design.md`；后端模块边界见
> `docs/backend/backend-module-design.md`；测试治理见 `docs/backend/contract-test-governance-design.md`。

本文只定义页面职责和交互验收，不定义后端字段事实源。字段、枚举、权限和部署形态仍以
`config/contracts/*.json`、后端专题文档和 API schema 为准。

## 1. 标记规则

| 标记 | 含义 |
|---|---|
| 已做 | 已有真实页面/API 接入或文档/代码快照明确完成 |
| 部分 | 主流程可用，但关键状态、权限、测试或体验仍缺 |
| 未做 | 没有真实后端闭环或不应显示 |
| 禁显 | 在对应后端能力完成前，前端不能展示入口 |

每个页面必须保留四类笔记：

- 目标态：这个页面给谁用、完成什么任务。
- 已做：当前已经可用或已有测试看护的内容。
- 未做：不能假装完成的内容。
- 测试看护：至少需要哪些组件/E2E/权限/部署形态测试。

### 1.1 布局模板标注（2026-07 起强制）

每个页面必须在 §3 逐页总表声明所属布局模板（`list` 列表页 / `detail` 详情页 /
`dashboard` 仪表盘 / `settings` 设置页，定义见
`docs/product/frontend-product-design.md` §9.3）。没有模板标注的新页面不得合入；
页面间距只允许引用 §9.1 spacing tokens。`/login`、`/setup`、`/invite/:code`
在 AppShell 之外，标注为 `auth` 居中窄卡布局，不占用四模板。

## 2. 全局壳 AppShell

### 2.1 目标态

工作台壳负责跨页面上下文，不负责业务模块本身：

- 当前工作台。
- 数据库驱动分组导航。
- 部署形态和能力开关提示。
- 账号入口。
- 搜索和通知的快捷入口。

### 2.2 已做

- 液态玻璃视觉基线已落到全局壳和主题层。
- 左侧导航按 `workspace_sections` 分组渲染。
- 工作台切换和新建工作台入口已接入。
- 窄屏响应式和图标栏模式已有设计约束。
- `GET /api/meta/runtime` 已作为部署能力来源。
- 顶部搜索已恢复为真实 `/api/search` 结果面板；只在 `capabilities.search=true` 时显示，
  不搜索页面菜单名；结果面板已按对象类型分组，支持上下键移动、回车打开当前选中结果和 ESC 关闭；
  空搜索框聚焦时展示按用户和工作台隔离的本地最近打开结果。
- 通知铃铛已接入真实未读数 API，点击进入 `/notifications`。
- 顶部用户胶囊已改为 `/account` 真实账号入口。
- 工作台切换器底部已有「发现工作台」入口（独立组件
  `frontend/src/components/WorkspaceDiscovery.vue`，AppShell 只挂一行）：抽屉列出
  `visibility=internal_public` 的可订阅工作台（名称/描述/成员数/已加入标识），
  支持自助订阅（viewer）与退订；角色高于 viewer 显示「由管理员管理」；游客会话
  隐藏订阅按钮并提示注册后可订阅。
- 新建工作台向导已迁居中 Modal（2026-07，产品设计 §10.3 第 1 项）：md 档
  `components/AppModal.vue`，三步向导不变；脏表单遮罩/Esc 先弹确认、完成页与
  干净表单直接关闭。
- `frontend/src/layouts/AppShell.spec.ts` 已覆盖真实搜索结果跳转、搜索结果类型分组、键盘选择、本地最近打开结果、真实通知入口、账号入口和禁采集部署隐藏采集导航，以及建台向导居中 Modal 结构（role=dialog/aria-modal/md 档）与脏表单 Esc 确认；发现抽屉行为由 `frontend/src/components/WorkspaceDiscovery.spec.ts` 看护。

### 2.3 未做 / 禁显

| 项 | 标记 | 处理 |
|---|---|---|
| 顶部搜索 | 已做 v1 | `capabilities.search=true` 时显示；调用 `/api/search`，结果面板可分组并跳真实业务对象，支持键盘选择和本地近期结果，已有 AppShell 测试 |
| 通知铃铛 | 已做 | 真实未读数 API 已完成并恢复入口，已有 AppShell 测试 |
| 用户胶囊账号入口 | 已做 | 已跳转 `/account`，已有 AppShell 测试 |
| 部署能力解释 | 部分 | intranet 禁采集等状态需在页面入口和按钮处一致体现 |
| 新建工作台向导迁居中 Modal | 已做 | 2026-07 已迁 `components/AppModal.vue`（md 档，向导三步不变）；脏表单 Esc/遮罩先确认、干净直接关闭均有 AppShell.spec 断言 |
| 发现工作台迁居中 Modal + 搜索 + 凭码加入 | 已做 | 2026-07-08（WP3-G）已迁 `components/AppModal.vue` md 档：顶部 `discover?q=` 去抖搜索框，底部「凭码加入」（`POST /api/workspaces/join-by-code`，失效统一 400、限流 429 文案透传）；`WorkspaceDiscovery.spec.ts` 看护 |
| 全局壳测试 | 部分 | 已覆盖 search 结果跳转、真实 notification 入口、账号入口、禁采集导航；还需更多 runtime capability 场景 |

### 2.4 测试看护

- AppShell 顶部搜索只显示真实 `/api/search` 结果和按用户/工作台隔离的本地近期结果，按类型分组并支持键盘选择；通知只显示真实后端未读数。
- 用户胶囊点击进入 `/account`。
- `DEPLOY_MODE=intranet` 时采集入口隐藏或禁用并解释。
- 非成员工作台不出现在切换器。
- 新建工作台向导以 `role="dialog" aria-modal="true"` 居中 Modal（md 档）渲染，
  不再出现 config-panel 浮层；Esc/遮罩点击关闭且脏表单先确认（已实施，
  AppShell.spec 断言）。发现工作台同样居中 Modal 渲染（已实施，WP3-G）；发现
  Modal 搜索只过滤 `internal_public`；凭码加入成功后切换到目标工作台，游客提交
  显示注册提示；均有 `WorkspaceDiscovery.spec.ts` 断言。

## 3. 逐页总表

模板列含义见 §1.1；`list*` 表示 list 模板的双列变体（允许两类固定侧栏：`/sources`
标签策略面板、日报/周报页 ReportTimeline 时间轴侧栏，见产品设计 §13）。

| 页面 | 模板 | 当前标记 | 关键未做 |
|---|---|---|---|
| `/dashboard` | dashboard | 部分 | 点击跳转 E2E 和源健康长期趋势（§4.1 主列+固定侧栏重排与侧栏第 6 位调度心跳卡已实施，WP3-D/H）；头条候选 final_score 降序看护断言与空指标隐藏（§4.4，R3 设计） |
| `/sources` | list* | 部分 | 标签策略错误态和更多 E2E（新增源/导入预览已迁居中 Modal，2026-07） |
| `/sources/:id` | detail | 部分 | 采信贡献趋势和更细评分贡献 |
| `/ingestion-runs` | list | 部分 | 更多补采 provider、邮件/外部告警通道和更长周期趋势 |
| `/news` | list | 部分 | 跨页联动深化和 E2E |
| `/recommendations` | list | 部分 | 评分器策略编辑/批量重算、观察池运营深化 |
| `/daily-reports` | list* | 部分 | 报告页 IA 重设计（ReportTimeline 时间轴/顶部筛选条/详情区 spacing 修正/文案违例清理，§10.1，R3 设计）、富文本/差异、更多对象通知、完整 E2E |
| `/daily-reports/:id` / `:id/edit` | detail | 部分 | 编辑体验、版本/差异、权限态测试 |
| `/weekly-reports` | list* | 部分 | 报告页 IA 重设计（同日报页，§12.1，R3 设计）、LLM 周报摘要模型、热度排序、分页 |
| `/historical-reports` | list | 部分 | 归档职责重定位（跨来源归档/月份导航降级/已发布条目深链跳报告页，§13.1，R3 设计）、生产主库导入验收证据和更多 E2E |
| `/entity-milestones` | list | 部分 | 更多 E2E |
| `/quality-archive` | list | 部分 | 更多当前反馈/推荐反馈分解释关系和 E2E |
| `/insights` | list | 部分 | insight 到 requirement 联动抽屉、批量转需求和当前反馈/归档聚合解释 |
| `/requirements` | list | 部分 | 需求与评论/任务联动深化 |
| `/tasks` | list | 部分 | 跨对象联动体验、评论和更多归档对象解释关系 |
| `/sync` | list | 部分 | 端到端实机证据、生产告警投递/runbook、更多对象 manual_merge |
| `/exports` | list | 部分 | 真实内网平台生产联调证据 |
| `/workspace-settings` | settings | 部分 | E2E（自动化/生成模型/可见性与加入码三卡已实施，WP3-G/H） |
| `/users` | settings | 部分 | 真实 provider/内网门户验收 |
| `/audit-logs` | list | 部分 | action taxonomy、告警/运行证据联动 |
| `/login` | auth | 部分 | 真实 provider 验收 |
| `/setup` | auth | 部分 | 真实空库端到端证据 |
| `/invite/:code` | auth | 已做 | pending/expired/revoked/accepted 状态体验、前端校验和错误文案已覆盖 |
| `/account` | settings | 部分 | 会话列表、踢下线；资料编辑卡片（§25，WP3-F）与顶部账号入口已完成 |
| `/notifications` | list | 部分 | 邮件、更多对象通知生成/提及 |
| 顶部搜索面板 | —（壳内浮层） | 部分 | v1 已接 `/api/search`，覆盖类型分组、键盘选择、本地近期结果、周报条目、导出任务/trace 条目、同步运行/冲突等主要对象锚点；仍缺 E2E |

### 3.1 弹窗迁移清单（2026-07 定稿，WP3-E/G 已全部实施）

全站弹窗规范与判定规则见 `docs/product/frontend-product-design.md` §10；
契约扫描面见 `config/contracts/frontend_control_governance.json` `modal_rule`
（扫描器已在 `scripts/validate_frontend_controls.py` 生效：config-panel 只允许
白名单两处且必须带 `context-panel` 正式化标记类；modal-backdrop 组件必须带
`role="dialog" aria-modal="true"`）。迁移状态在此跟踪：

| 弹层 | 处置 | 档位 | 状态 |
|---|---|---|---|
| 新建工作台向导（AppShell） | 迁居中 Modal | md | 已做（2026-07，AppModal + 脏表单确认，AppShell.spec 看护） |
| 发现工作台（WorkspaceDiscovery，含搜索 + 凭码加入） | 迁居中 Modal | md | 已做（2026-07-08，WP3-G 随搜索/凭码功能一并迁移，WorkspaceDiscovery.spec 看护） |
| 新增信息源（SourcesPage） | 迁居中 Modal | md | 已做（2026-07，AppModal + 脏表单确认，SourcesPage.spec 看护） |
| 数据源导入预览（SourcesPage） | 迁居中 Modal | sm | 已做（2026-07，确认类 AppModal，SourcesPage.spec 看护） |
| 单源配置（SourcesPage） | 保留上下文面板 | — | 已正式化（`config-panel context-panel` 标记类，保留理由断言在 SourcesPage.spec） |
| 成稿格式管理（DailyReportsPage） | 保留上下文面板 | — | 已正式化（`config-panel context-panel` 标记类，保留理由断言在 DailyReportsPage.spec） |
| 日报条目详情（DailyReportsPage） | 归入 Modal lg 档 | lg | 已收编 AppModal（Wave1 迁移样例） |
| 任务详情（TopicTasksPage） | 归入 Modal lg 档 | lg | 已收编 AppModal（2026-07，旧 report-modal-backdrop 私有基座随之删除） |

## 4. 今日速览 `/dashboard`

### 4.1 目标态

10 秒内回答：

- 今天流水线跑到哪一步。
- 哪些候选需要处理。
- 最新日报/周报是否可读。
- 源健康是否异常。

信息架构重排（2026-07 定稿，线框级描述见
`docs/product/frontend-product-design.md` §9.4）：dashboard 模板，分区顺序与归属固定——

- 页头结论行（全宽单行卡）：日期 + 系统健康点 + 今日日报状态 CTA。
- 主列（`minmax(0,1fr)`）：① 今日头条候选 Top6 ② 最新日报卡。只放「今天要处理的内容」。
- 固定侧栏（340px，顺序固定）：① 流水线漏斗（竖排紧凑）② 快捷入口 ③ 最新周报卡
  ④ 近七日采信趋势 ⑤ 源健康（无异常折叠为一行「源健康正常」，异常展开失败 Top3 + 待补入口）
  ⑥ 调度心跳卡（已实施，读 `GET /api/pipeline/scheduler/status`，见 §4.2）。
- ≤1120px 单列堆叠：页头 → 头条候选 → 最新日报卡 → 侧栏各卡按序。
- 重排只动布局归属，除侧栏第 6 位调度心跳卡（自动化轨道新增，读
  `GET /api/pipeline/scheduler/status`）外不引入新后端能力；其余数据来源不变。

### 4.2 已做

- 晨报式首页已设计并实现为今日速览。
- 展示流水线漏斗、头条候选、报告卡、趋势侧栏、源健康和快捷入口。
- 数据来自 coverage、dedupe、daily/weekly report 等真实 API。
- 页面只读，不承担写操作。
- `frontend/src/pages/DashboardPage.spec.ts` 已覆盖正常数据聚合、空态、核心 API 错误态、
  后端 health/coverage 降级和 read-only 部署隐藏采集入口。
- §4.1 信息架构重排已实施（2026-07-08，WP3-D）：主列头条候选+最新日报卡、固定侧栏
  六卡顺序固定、漏斗竖排收进侧栏、源健康无异常折叠为一行；分区归属与折叠/展开有
  DashboardPage.spec 断言。
- 调度心跳运营卡已实施（2026-07-08，WP3-H，侧栏第 6 位）：读
  `GET /api/pipeline/scheduler/status` 展示在线/离线（心跳 stale 判定）、下次运行、
  最近 run 与重试状态；查询失败/心跳过期渲染离线态而非在线绿色，有
  DashboardPage.spec 假成功回归断言。

### 4.3 未做

- 头条候选和报告卡的点击跳转需要 E2E 验证。
- 源健康 TopN 与失败趋势还需接入长期观测。
- 头条候选排序看护断言与空指标隐藏规则（2026-07-08 R3 定稿，见 §4.4）尚未落测试/实现。

### 4.4 测试看护

- 无抓取数据时显示下一步动作；read-only 部署不显示“跑抓取”类动作。
- 有失败源时展示源健康异常；跳转数据源或抓取页仍需 E2E。
- health 或 coverage 失败时降级展示，不把后端不可用渲染成绿色正常。
- 主列只含头条候选与最新日报卡；漏斗/快捷入口/周报/趋势/源健康/调度心跳卡在固定
  侧栏；无失败源且无待补入口时源健康渲染折叠单行，有异常时展开（已实施，
  DashboardPage.spec 断言）。
- scheduler 心跳过期或 status API 失败渲染为离线/不可用态，不得显示在线绿色
  （假成功回归；已实施，DashboardPage.spec 断言）。
- 头条候选集合与排序一致性（R3 设计并经交叉评审对齐，排序事实源是
  `config/contracts/recommendation_ranking.json` `ordering_consistency`
  `dashboard_headline_candidates`，键名一字不差）：`DashboardPage.spec.ts` 用乱序
  fixture 断言——集合只含 `day_key=今日` 且 `admission_level ∈ {P0,P1,P2}` 的候选
  top 6，按 `final_score` 严格降序（并列按 `news_item_id` 升序）；含非今日候选的
  fixture 断言其**不被渲染**；无今日候选 fixture 断言渲染空态而非历史候选。
  现实现 `DashboardPage.vue` topCandidates 的「今日优先、历史混排」两层排序是
  契约废除对象，随 WP4-E 改造并加此看护；契约排序键变更时本断言必须同步。
- 空指标隐藏（R3 设计）：均值/比率类指标无样本时不渲染占位 `0.0`——本页涉及
  近七日采信趋势等比率展示；同一规则约束日报页 `平均评分`（`averageRating` 现在
  rated 为空时返回 "0.0" 并渲染「0.0 平均评分」，目标改为隐藏该 span，§10.4）
  和归档页平均采信率。断言：无评分样本 fixture 下页面不出现文本 `0.0`。

## 5. 数据源管理 `/sources`

### 5.1 目标态

管理员管理共享源池和当前工作台启用关系：

- 查看共享源。
- 导入种子和治理源。
- 自建源。
- 配置工作台源启用、权重、日限。
- 管理工作台统一标签策略。

### 5.2 已做

- 信息流式源列表和右侧标签策略面板已落地。
- `GET /api/sources?workspace_code=...` 接入共享源池和工作台启用关系。
- `GET /api/sources/import-preview` 已要求前端先预览再导入。
- Tech Insight Loop 源等级、渠道、质量分、专家路由、待补入口已展示。
- 自建源和待补入口补 URL 已接入。
- 自建源已支持 `paper_api` 类型；新增面板会提示 arXiv、OpenAlex 或 Semantic Scholar API URL，源列表/抓取按钮识别“论文 API”。
- 已有组件测试覆盖导入预览优先和 read-only 部署隐藏采集控件。
- 已有组件测试覆盖 `total=0` 警告态、`created=0 updated>0` 信息态、`paper_api` 自建源创建，避免导入/拉取 0 条被渲染成绿色成功。
- 已有组件测试覆盖工作台标签策略保存失败：权限/网络错误显示错误态，不显示“已保存”成功提示。
- 未实现 stub 适配器的 `skipped_unimplemented` 状态已在抓取覆盖页显示为“尚未实现”，不会渲染成绿色成功。
- 数据源列表提供详情入口，进入 `/sources/:id` 查看单源配置、raw、run 错误和趋势。
- 统一弹窗迁移已实施（2026-07，产品设计 §10.3 第 3/4 项）：新增信息源迁居中
  Modal md 档（脏表单遮罩/Esc 先确认）、导入预览迁居中 Modal sm 档（确认类，
  Esc 直接关闭）；单源配置按 §10.2 三条判定保留为上下文面板并带
  `config-panel context-panel` 正式化标记类。组件测试覆盖 Modal 结构
  （role=dialog/aria-modal/档位）、脏表单确认与上下文面板保留理由断言。

### 5.3 未做

- 标签策略错误态已有组件测试；仍需 Playwright 覆盖导入预览、标签策略保存和详情跳转的整段旅程。

### 5.4 测试看护

- 点击导入必须先 preview。
- `total=0` 显示警告，不显示成功。
- `created=0 updated>0` 显示信息态。
- intranet 模式隐藏导入、新增源、抓取按钮。
- 单源配置不允许维护成品新闻一级/二级标签。
- 标签策略保存失败时只显示错误，不显示成功提示或假保存。
- 新增信息源/导入预览以 `role="dialog" aria-modal="true"` 居中 Modal 渲染；
  新增源脏表单 Esc/遮罩先弹确认；单源配置保留 `config-panel context-panel`
  上下文面板形态（`scripts/validate_frontend_controls.py` modal_rule 扫描）。

## 6. 数据源详情 `/sources/:id`

### 6.1 目标态

展示单个源的配置、抓取状态、最近 raw、错误日志、质量评分趋势和工作台启用关系。

### 6.2 已做

- 路由和页面文件已存在。
- 数据源列表可进入详情。
- `GET /api/sources/{id}?workspace_code=...` 已提供安全详情投影。
- 页面展示工作台启用关系、抓取状态、raw/news 累计、最近 raw、最近运行错误和 raw 趋势。
- 只读部署隐藏抓取按钮。
- 不存在或无权限时显示可恢复错误态。
- 组件测试覆盖安全详情、workspace-scoped 抓取、只读部署隐藏抓取和 404 错误态。

### 6.3 未做

- 评分贡献和采信贡献趋势仍需从推荐/日报链路深化。

### 6.4 测试看护

- 无权限或不存在源显示可恢复错误态。
- 待补入口补 URL 后能回到可抓取状态。
- 源详情不暴露 secret-like 配置。

## 7. 抓取与覆盖 `/ingestion-runs`

### 7.1 目标态

让管理员发起抓取/补采，并解释目标日为什么有或没有候选。

### 7.2 已做

- 常规抓取、历史补采、run 历史、目标日覆盖漏斗和每源详情已接入。
- 支持 `rss_window/paper_api/archive_page/sitemap/manual_import` 模式；`paper_api` 已有 arXiv submittedDate、OpenAlex publication_date 和 Semantic Scholar publicationDateOrYear 日期窗口 v1。
- `manual_import` 已提供页面级上传/粘贴 + 后端预览 v1：选择归属数据源，上传或粘贴 CSV/SQL，
  先调用预览 API 获取 accepted/rejected 和错误报告，再把 accepted rows 提交为 `manual_items`，
  后端保留 raw payload 追溯。
- scheduler 只读配置卡已设计。
- 失败源手动重试 v1 已接入：有失败源的 run 显示“重试失败源”，调用 `POST /api/ingestion/runs/{run_id}/retry-failed-sources`，并把新 run 选中展示。
- 失败源自动重试队列 v1 已接入：调度卡读取 `GET /api/ingestion/failed-source-retry-summary`，
  展示自动重试是否开启、到期 run、阻塞 run 和尝试上限。
- 长期覆盖趋势 v1 已接入：调用 `GET /api/ingestion/coverage/trends`，展示近 14 日 raw 新增、失败源趋势和 Top 失败源。
- 失败源站内告警锚点 v1 已接入：通知模块返回 `/ingestion-runs?run_id=...` 后，页面会选中对应 run 并刷新该 run 覆盖率。
- 已有组件测试覆盖 `limit=0` 前端拒绝、无启用源不发请求、read-only 部署隐藏运行入口、失败源重试、无失败源不显示重试入口、自动重试策略展示、通知 run 锚点选中、`skipped_unimplemented` 状态展示、`manual_import` 预览后提交、0 accepted 阻断、错误报告展示和覆盖趋势渲染。

### 7.3 未做

- 深度历史补采 provider 不完整：arXiv v1、OpenAlex Works v1 和 Semantic Scholar v1 已完成，OpenReview 等仍待补。
- `manual_import` 文件上传、导入预览、SQL v1 解析、逐行校验和错误报告下载已完成；后续仍需更复杂 SQL dialect 和大文件分片。
- 邮件/外部告警通道和生产 runbook 未闭环；站内告警投递 v1 已完成。
- 调度卡升级（后端 `GET /api/pipeline/scheduler/status` 已实现且已被 `/dashboard`
  侧栏心跳卡消费，本页面卡仍未升级）：从只读 env 快照（`GET /api/ingestion/scheduler`）
  升级为读 `GET /api/pipeline/scheduler/status`，展示心跳、per-workspace 下次运行、
  最近 run 与 run 级重试状态；env 快照保留为"实例基线"展示并注明工作台级策略
  入口在 `/workspace-settings` 自动化卡（`docs/backend/pipeline-jobs-design.md` §8.4）。

### 7.4 测试看护

- `limit=0` 不发请求，后端 422 也有测试。
- 无启用源显示警告而不是成功 0 条。
- backfill 模式说明不能把 RSS 窗口宣传成全站历史抓取。
- `manual_import` 没有上传/粘贴内容时不发请求；预览 accepted 为 0 时不能提交；提交时必须携带预览生成的 `manual_items`。
- intranet 模式隐藏运行按钮。

## 8. 候选池 `/news`

### 8.1 目标态

编辑查看去重 winner、重复来源、推荐状态、日报采信状态和追溯链。

### 8.2 已做

- 已展示 winner、loser、来源覆盖、推荐分、推荐状态、日报采信状态和追溯 ID。
- 已接入 `GET /api/news-items` 和 `GET /api/dedupe-groups`。
- 结构化准入字段可在候选中展示。
- 已接入 `POST /api/daily-reports/bulk-adopt-from-candidates`，支持选择已推荐候选并批量采信到目标日报草稿。
- `GET /api/dedupe-groups` 已接入关键词、推荐状态、日报状态、准入等级、来源类型筛选和排序。
- 已接入 `POST /api/daily-reports/bulk-reject-from-candidates`，支持选择已推荐候选并批量剔除到目标日报草稿。
- viewer 工作台角色下不渲染候选复选框、目标日期、批量采信和批量剔除写操作。
- 展开区已展示 `dedupe_group_id`、winner news、raw item、data source、recommendation item 和 daily report item 的基础追溯字段。
- 展开区已接入 `lineage.nodes` 完整 trace 复核 v1，按数据源、Raw、News、去重组、推荐、成稿、日报条目显示状态、
  后端 `review_note` 业务解释、安全元数据和可点击定位；支持 `/news?news_item_id=...`、`/news?raw_item_id=...`、
  `/news?dedupe_group_id=...` 高亮候选。
- 候选详情区已接入 `GET/PATCH /api/object-watchers` 的 `dedupe_group` 关注状态；候选被批量采信/剔除后，
  关注者会收到后端 `dedupe_group.adoption_changed` 通知，并可从 `/news?dedupe_group_id=...` 高亮回到候选。

### 8.3 未做

- 批量采信、批量剔除、筛选排序和候选 watch v1 已完成。
- 候选池默认排序切分数序未实施（2026-07-08 R1 定稿，契约
  `config/contracts/recommendation_ranking.json` `ordering_consistency`
  `candidate_pool`）：`GET /api/news-items/dedupe-groups` 默认 `sort` 由
  `updated_desc` 改为 `score_desc`（`final_score` 降序），其他排序仅显式选择时
  生效；随 WP4-E 实施。
- 质量治理字段和候选复核流还需增强。
- 完整 trace 复核和 trace 节点业务解释 v1 已完成；后续继续增强跨页联动体验。
- E2E 不足。

### 8.4 测试看护

- 候选池只展示去重 winner，不直接拿 raw 流当候选。
- `frontend/src/pages/NewsPage.spec.ts` 覆盖搜索锚点、raw trace 锚点、dedupe group 锚点、lineage trace 展示、
  候选池筛选排序、批量采信、批量剔除、候选关注和 viewer 写操作隐藏。
- 默认排序一致性（R1 设计，WP4-E 实施时落 `NewsPage.spec.ts`）：不带显式排序
  参数时列表按 `final_score` 降序渲染；`final_score` 缺失的历史候选显示「未评分」
  而非 `0.0`（契约 `ordering_consistency` `empty_metrics`）。
- 工程字段不占第一屏。
- 采信状态与日报条目一致。
- viewer 不显示采信/剔除写操作。

## 9. 推荐运行 `/recommendations`

### 9.1 目标态

管理员查看推荐 run、分数拆解、准入等级、噪声原因和是否进入日报。

### 9.2 已做

- 推荐 run 历史、创建 run、详情分数拆解已接入。
- `ContentScorer` 的 P0-P3/R、噪声、专家路由已展示。
- 已接 `GET /api/recommendation/scorer-policy`，显示当前评分器版本、阈值、日报/周报准入层、
  权重 TopN、主题 TopN 和噪声规则摘要。
- 已接 `POST /api/recommendation/scorer-preview`，管理员可输入单条临时候选做评分预览，展示准入等级、
  噪声、专家路由、日报可入选和 `not_persisted` 不落库提示。
- 已接 P2/P3 观察池复核 v1：从当前推荐 run 筛出未入选观察池候选，调用日报批量采信/剔除 API
  写入日报草稿，并根据 run 详情回显“未处理/已采信/已剔除”。
- 默认不误触发日报草稿。

### 9.3 未做

- 评分器策略编辑、配置变更影响预览和批量重算未完成；当前只支持只读策略摘要和单条候选预览。
- P2/P3 观察池排序策略、复核备注、抽检队列和批量重算联动未完成。
- 更多筛选和跳转测试不足。

### 9.4 测试看护

- 创建推荐 run 不应默认创建日报。
- `frontend/src/pages/RecommendationsPage.spec.ts` 覆盖评分器策略摘要展示。
- `frontend/src/pages/RecommendationsPage.spec.ts` 覆盖评分预览不创建 recommendation run 或日报草稿。
- `frontend/src/pages/RecommendationsPage.spec.ts` 覆盖观察池复核调用日报采信 API 并回显日报状态。
- 分数拆解字段缺失时有降级显示。
- 无权限用户不可触发重算。

## 10. 日报 `/daily-reports`

### 10.1 目标态

采编生成、阅读、编辑、采信、发布日报，并能评论、评分、追溯来源。
本页自身承担本工作台日报的**时间线、按标签筛选和历史全量查询**能力
（2026-07-08 R3 定稿，IA/组件/分工见产品设计 §13；历史全量回溯不再依赖
`/historical-reports`）：

- **左侧 ReportTimeline 时间轴**（组件规范见产品设计 §13.1）：按月分组竖向
  时间轴，月份组头吸顶，节点显示日期/发布状态点/条数徽章，无限滚动加载全量
  历史，顶部快速跳月；已发布层走 `GET /api/report-archive?report_type=daily&origin=published`
  轻量索引（viewer+），草稿层走现有 `GET /api/daily-reports`（member+ 才渲染
  草稿节点）。替代现左侧仅 20 份的 `report-tab` 平铺列表。
- **顶部筛选条**：一级标签胶囊（十分类，多选，取自条目 `generated_news.category`）、
  板块下拉（当前成稿格式分组标题）、关键词输入（标题/摘要包含匹配）；纯前端
  过滤当前报告条目与成稿分组显示，显示「N/M 条」，0 命中给清除入口，不发新请求、
  不改采信状态。
- **详情区 spacing 修正**（逐元素 token 表见产品设计 §13.3）：详情卡补
  `--space-card-pad` 四边内边距（根因：`.daily-report-card` 现无 padding 且
  `.editorial` 强制 `padding-right: 0`，文字贴卡边）；标题区/统计行/格式 tab 行
  逐项对齐 spacing tokens。
- **文案违例清理**（清单见产品设计 §14.2）：本页页头「SQL 预览回填」描述与
  空态「内网版视图」为违例 #1/#2，按清单替换。

### 10.2 已做

- 可按日期触发完整流水线生成日报草稿。
- 支持日报列表、详情、采信切换、条目编辑、发布。
- 支持点赞、评分、评论最小闭环。
- 已读取工作台 `feedback_policy`；当当前用户只是 viewer 且策略关闭时，日报详情禁用点赞、评分和评论入口。
- 支持 MiniMax 失败 fallback 展示和生成稿重跑。
- 支持多版成稿 tab、MD/HTML 导出和技术洞察版。
- 可消费 `/daily-reports?report_id=...&rendition_id=...&format_code=...`，从搜索结果切到对应成稿格式并高亮成稿视图。
- 管理员可在条目详情中点击“沉淀需求”，从日报条目创建 insight、implication 和 requirement。
- 日报条目详情可显示当前用户关注状态和关注人数，点击关注/取消关注调用 `GET/PATCH /api/object-watchers`。
- `frontend/src/pages/DailyReportsPage.spec.ts` 已覆盖 viewer 策略关闭时反馈入口不可用、日报 report 锚点、report rendition 成稿锚点、日报条目沉淀需求入口和日报条目关注切换。

### 10.3 未做

- 报告页 IA 重设计未实施（2026-07-08 R3 定稿）：ReportTimeline 时间轴（现左侧只有
  最近 `limit=20` 份的平铺 tab，没有月份分组/全量历史/跳月）、顶部筛选条（现无
  任何条目筛选）、详情区 spacing 修正、文案违例 #1/#2 替换、
  「0.0 平均评分」空指标隐藏（`averageRating` 无样本时返回 "0.0" 仍渲染）。
- 富文本编辑、差异对比和版本修订规则未完成。
- 日报评论已接入 activity event 和站内未读通知；点赞/评分按设计只写 activity event，不逐条提醒。
- 日报评论 @ 提及、requirement 状态通知、周报条目更新通知和日报条目关注者通知已支持页面锚点；邮件和更多对象通知生成仍未完成。
- 已发布后修订 UI 和审计提示需要增强。
- 页面级 E2E 不足。
- 格式管理面板模板能力（后端已实现：`POST /api/report-formats/validate-template`
  与 `report-formats` 模板读写见 `backend/tests/test_generation_template.py`；
  本页 UI 未接入。设计 `docs/backend/report-renditions-design.md` §10，契约
  `config/contracts/report_renditions.json` `generation_template`）：新建/编辑
  自定义格式时可上传或粘贴 JSON/XML 生成模板，先调
  `POST /api/report-formats/validate-template` 展示逐字段校验错误、
  投影/增量字段划分和示例预览（preview_item），校验不通过不能保存；
  locked/builtin 格式不显示模板入口；带模板格式的成稿视图对
  `template_fallback=true` 条目显示"模板字段降级"标记而非空白。

### 10.4 测试看护

- 编辑日报不覆盖 raw 和 generated_news。
- fallback 生成稿不能导出标准公司 SQL。
- viewer 是否可评论由 `feedback_policy` 决定。
- viewer 反馈策略关闭时，点赞、评分、评论输入和发送按钮不可用。
- report rendition 搜索锚点必须切换到指定成稿格式，并高亮成稿视图。
- 发布后状态、锁定和修订写审计。
- 日报条目详情以 AppModal lg 档渲染（Wave1 迁移样例）；成稿格式管理按 §10.2
  三条判定保留为 `config-panel context-panel` 上下文面板，保留理由断言在
  `DailyReportsPage.spec.ts`（`scripts/validate_frontend_controls.py` modal_rule 扫描）。
- ReportTimeline（R3 设计，实施时落 `DailyReportsPage.spec.ts` +
  `ReportTimeline.spec.ts`）：按月分组渲染、无限滚动触底加载下一页
  （offset 递增）、跳月定位、加载失败显示可重试行不静默；viewer fixture 不渲染
  草稿节点，member fixture 渲染草稿节点。
- 顶部筛选条（R3 设计）：标签/板块/关键词过滤只影响显示且不发写请求；0 命中
  渲染清除入口；筛选态下批量操作只作用于可见条目或明确提示范围。
- 空指标隐藏（R3 设计）：无评分样本时统计行不渲染「0.0 平均评分」span。
- 界面文案审计（R3 设计，`backend/tests/test_blueprint_page_audit.py` 扩展断言
  `test_blueprint_user_copy_bans_implementation_terms`）：扫描
  `frontend/src/{pages,layouts,components}` 的 `.vue` `<template>` 段可见文本与
  `title/placeholder/aria-label` 属性，断言不出现
  `config/contracts/frontend_control_governance.json` `copy_audit_rule` 的
  `banned_terms`/`banned_patterns`（豁免按契约 `exemptions` 的 file+marker 白名单
  放行）；违例修复完成前该断言以契约 `known_violations` 为临时基线（只准减不准增），
  清零后收紧为全量禁止。

## 11. 日报详情和编辑 `/daily-reports/:id`、`/daily-reports/:id/edit`

### 11.1 目标态

详情页偏阅读和协作，编辑路由偏采编处理。两者可复用组件，但权限态必须不同。

### 11.2 已做

- 路由已存在，复用 `DailyReportDetailPage.vue`。
- 支持详情查看、编辑处理、评论和追溯。

### 11.3 未做

- 详情/编辑模式的视觉和权限边界需要更清楚。
- 字段级差异、版本历史和发布后修订还未完整。
- 详情页深链接到具体条目/评论未完善。

### 11.4 测试看护

- viewer 进入编辑路由不能看到写操作。
- `must_change_password` 用户被引导到账户页。
- 深链接 item id 能定位到条目。

## 12. 周报 `/weekly-reports`

### 12.1 目标态

从已发布日报采信项生成周报候选，按板块采信、排序、编辑、发布和成稿。
与日报页同构承担本工作台周报的时间线、筛选和历史全量查询（2026-07-08 R3 定稿，
产品设计 §13）：

- 左侧替换为 ReportTimeline（weekly 变体，节点主标 `2026-W27`）：已发布层走
  `GET /api/report-archive?report_type=weekly&origin=published`，草稿层走现有
  `GET /api/weekly-reports`；替代现 `module-split.weekly-layout` 的 `run-list` 左栏。
- 顶部筛选条：板块（周报条目 section）、一级标签、关键词，纯前端过滤当前周报
  条目显示。
- 详情卡标题区/统计行按产品设计 §13.3 token 对齐（`module-card.weekly-detail`
  已有卡内边距，只需内部行距对齐）。
- 文案违例清理：本页违例 #3/#4/#5（「采信状态为 2」「本阶段」「SQL 预览回填」
  「adoption_status = 2」），按产品设计 §14.2 清单替换。

### 12.2 已做

- 可按 ISO week 创建周报候选草稿。
- 支持周报条目采信/剔除、排序、编辑、发布。
- 支持技术洞察版和公司 SQL 之外的 MD/HTML rendition。
- 第一屏避免堆叠五段正文。
- 周报详情已显示后端 `weekly_reports.summary` 生成的摘要段；前端不再本地拼摘要。
- 可消费 `/weekly-reports?report_id=...&item_id=...`，从搜索结果定位到对应周报条目并高亮。
- 可消费 `/weekly-reports?report_id=...&rendition_id=...&format_code=...`，从搜索结果定位到目标周报并高亮对应成稿导出入口。
- 管理员可在周报条目上点击“沉淀需求”，从周报条目创建 insight、implication 和 requirement。
- 周报条目动作区可显示当前用户关注状态和关注人数，点击关注/取消关注调用 `GET/PATCH /api/object-watchers`。

### 12.3 未做

- 报告页 IA 重设计未实施（2026-07-08 R3 定稿，§12.1）：ReportTimeline weekly 变体
  （现左栏为 `run-list` 平铺、仅最近 `limit=20` 份）、顶部筛选条、文案违例
  #3/#4/#5 替换。
- LLM 周报摘要模型未完成；当前为后端规则投影 v1。
- 热度/反馈排序未完成。
- 超过 200 条的分页/分批管理未完成。
- 周报长文自动生成未完成。

### 12.4 测试看护

- 周报只从已发布日报采信项生成。
- 周报采信状态不反向污染日报采信状态。
- 五段正文只在编辑态展开。
- `frontend/src/pages/WeeklyReportsPage.spec.ts` 覆盖报告锚点、周报条目锚点、report rendition 成稿导出锚点、周报条目沉淀需求入口、周报条目关注切换和后端周报摘要段展示。
- ReportTimeline weekly 变体（R3 设计，实施时与日报页共用 `ReportTimeline.spec.ts`
  组件断言）：按月分组、无限滚动、跳月、viewer 不渲染草稿节点；周报页断言时间轴
  节点点击加载对应周报详情。
- 顶部筛选条（R3 设计）：板块/标签/关键词过滤只影响显示，0 命中渲染清除入口。
- 文案审计（R3 设计）：本页空态/说明行不出现 `采信状态为 2`、`adoption_status`、
  `本阶段`、`SQL 预览回填`（由 `test_blueprint_page_audit.py` 扩展断言统一看护，
  §10.4）。

## 13. 历史报告库 `/historical-reports`

### 13.1 目标态

**跨来源归档**（2026-07-08 R3 重定位，分工表见产品设计 §13.4，后端边界见
`docs/backend/archive-knowledge-design.md` §5.1）：本工作台日报/周报的时间线、
按标签筛选和历史全量查询能力归 `/daily-reports`、`/weekly-reports` 页自身；
本页只保留报告页给不了的三件事——

1. **旧系统导入资产**：legacy 历史报告列表/正文/引用缺口的唯一阅读入口，
   以及导入验收面板（覆盖率、accepted gaps）。
2. **跨来源统计对比**：summary 卡强化为 current（已发布日报/周报）与 legacy
   的产量、采信率、来源 Top 对比视图；平均采信率无样本时隐藏，不渲染占位 0。
3. **跨来源检索**：合并检索仍可返回已发布报告条目（统计与检索需要），但打开
   动作改为深链跳转 `/daily-reports?report_id=...` / `/weekly-reports?report_id=...`，
   本页不再内嵌当前报告正文阅读；legacy 条目仍在页内读正文。
   跨工作台聚合检索为目标态 v2（按 membership 过滤，未做，先补后端设计）。

页头一句话重写为：「跨来源报告资产库：旧系统导入资产的归档、验收与跨来源统计
对比；日常按天/周回溯请直接用日报/周报页的时间轴。」

月份导航处置决策：`archive-month-nav` 降级为「旧系统资产」视图内的 legacy 筛选
（legacy 报告不进报告页时间轴，按月回溯仍需要）；对已发布报告不再提供按月浏览
（该职责已移交报告页 ReportTimeline），避免与报告页重复。

### 13.2 已做

- 历史报告列表、详情、summary 和 legacy import gaps 已接入。
- 导入验收面板覆盖历史 raw、报告、实体、事件、反馈和旧任务。
- 页面不触发导入、推荐、采信或 SQL。
- 历史报告转需求 v1 已接入：管理员可在详情页用默认标题/来源说明创建 requirement，
  payload 带 `source_historical_report_id`，需求页和任务页可回跳历史报告。
- 统一报告归档视图（合并已发布 + legacy、月份导航、关键词检索）已实现——
  R3 重定位后其中「已发布报告的按月浏览 + 页内读当前报告正文」部分降级/移交，
  见 §13.3。

### 13.3 未做

- 归档职责重定位未实施（2026-07-08 R3 定稿，§13.1）：页头一句话重写、
  已发布条目打开动作改深链跳报告页、月份导航收敛到 legacy 视图、summary 卡
  改跨来源对比形态、平均采信率空样本隐藏。
- 生产主库全量导入验收证据未完成。
- 跨工作台聚合检索（目标态 v2）未做：需先在 `docs/backend/archive-knowledge-design.md`
  补 API 设计（多 workspace_code + membership 过滤），不得先做前端入口。
- 顶部搜索可返回历史报告路由；页面已按 `id` 精确选中/高亮。
- 历史反馈已可通过 `/quality-archive` 转成 requirement 来源；更多当前反馈/推荐反馈分解释关系仍需深化。

### 13.4 测试看护

- 页面不出现导入执行按钮。
- 未解析引用可见且不被静默吞掉。
- 历史资产不进入当前推荐和公司 SQL。
- 转需求必须通过 `source_historical_report_id` 保留来源，不允许复制标题后丢失引用。
- 重定位断言（R3 设计，实施时落 `HistoricalReportsPage.spec.ts`）：已发布条目
  点击产生报告页深链跳转而非页内正文渲染；legacy 条目仍页内渲染正文；月份导航
  只在 legacy 视图出现；页头文案为跨来源定位句；无发布样本时不渲染 `0.0`/`0%`
  占位均值。

## 14. 实体大事记 `/entity-milestones`

### 14.1 目标态

查看实体列表、事件时间线、重要等级、板块和旧引用解析状态；日报/周报采信条目可登记新的实体事件，
完整时间线仍在本页查看。

### 14.2 已做

- 实体列表、事件时间线、详情和旧引用解析面板已接入。
- 旧实体事件只读；页面不触发导入、推荐或采信。
- `/daily-reports` 和 `/weekly-reports` 已提供“登记事件”入口，workspace member 输入实体名后调用
  `POST /api/daily-report-items/{id}/entity-milestones` 或
  `POST /api/weekly-report-items/{id}/entity-milestones`，成功后返回实体名和事件标题。
- 当前实体事件由后端保留 report item、generated news、news、raw 和 data source 追溯。
- `frontend/src/pages/DailyReportsPage.spec.ts` 和 `frontend/src/pages/WeeklyReportsPage.spec.ts`
  已覆盖登记入口、实体名输入和 API payload。
- 当前事件治理 v1 已接入：`/entity-milestones` 对 `legacy_system=current` 的事件显示编辑、确认、撤销和转需求入口；
  旧系统导入事件不显示治理入口。
- `PATCH /api/entity-milestones/{id}` 可编辑当前事件并写 `curation_status=confirmed/revoked`；
  `POST /api/requirements` 支持 `source_entity_milestone_id`。
- `frontend/src/pages/EntityMilestonesPage.spec.ts` 覆盖事件编辑、确认、撤销和转需求；
  `frontend/src/pages/RequirementsPage.spec.ts` 覆盖实体事件来源展示。

### 14.3 未做

- 顶部搜索可返回实体/事件路由；页面已按 `entity_id` / `milestone_id` 精确选中/高亮。
- Playwright E2E 未覆盖实体事件登记、治理和转需求整段旅程。

### 14.4 测试看护

- 旧实体事件只读。
- 当前事件新增必须保留 report item/news/raw 追溯。
- 当前事件编辑/确认/撤销必须只对 `legacy_system=current` 显示。
- 转需求必须通过 `source_entity_milestone_id` 保留 requirement 来源。
- 报告页登记事件必须要求实体名，不允许静默自动猜实体后直接成功。
- 未解析旧引用可见。

## 15. 质量归档 `/quality-archive`

### 15.1 目标态

查看旧反馈、质量反馈、旧任务统计和反馈引用缺口；workspace admin 可将单条历史反馈显式转为
当前 requirement 来源，用于源质量复盘。该写入只保存来源链接，不把旧反馈改写成当前评论、评分或抓取任务。

### 15.2 已做

- summary、historical feedback、historical job runs 已接入。
- 查询和筛选只读，不执行历史导入，不创建当前 comments/ratings/ingestion_runs。
- 管理员“转需求”调用 `POST /api/requirements`，payload 带 `source_historical_feedback_item_id`；
  `/requirements` 和 `/tasks` 可回跳 `/quality-archive?feedback_id=...`。
- `frontend/src/pages/QualityArchivePage.spec.ts` 覆盖 summary/feedback/jobs/gaps 加载、反馈和任务筛选、转需求来源 payload、query anchor 高亮、空态边界与错误态。

### 15.3 未做

- 当前反馈与长期质量归档之间的聚合展示关系仍需设计。
- 与推荐反馈分的解释闭环还不完整。

### 15.4 测试看护

- 历史反馈不创建当前评论或评分；页面测试验证没有评论/评分写入口。
- 历史反馈转需求必须使用 `source_historical_feedback_item_id`，不能只复制标题或原因文本。
- 旧任务不创建当前 ingestion run；页面只展示旧任务统计。
- 引用缺口固定调用 `legacy-import/gaps` 的 `historical_feedback` 类型并展示缺口抽查。
- 筛选只作用于归档查询 API，不改变当前 feedback/comment/rating 对象。

## 15.5 洞察研判 `/insights`

### 15.5.1 目标态

集中管理从外部情报沉淀出的洞察判断和战略影响，并保留 report item、news、raw 和 source 追溯。

### 15.5.2 已做

- 页面已接入真实 `GET/POST/PATCH /api/insights` 和 `GET/POST/PATCH /api/strategic-implications`。
- workspace viewer 可读；workspace member+ 可创建和编辑洞察/战略影响。
- 支持按状态和关键词筛选 insight。
- 支持从 `news_item_id` 创建 insight，展示 source title、source URL、data source、report item trace。
- 支持创建和编辑 strategic implication。
- 支持确认、退回和归档 insight。
- `frontend/src/pages/InsightsPage.spec.ts` 已覆盖来源追溯、创建洞察、创建/编辑战略影响、状态更新和 viewer 禁写。

### 15.5.3 未做

- insight 到 requirement 的联动抽屉和批量转需求仍需深化。
- 质量归档和当前反馈之间的聚合解释关系仍需设计。

### 15.5.4 测试看护

- insight 必须显示真实来源，而不是只显示 ID。
- viewer 只能读，不能看到创建/编辑/归档控件。
- 归档 insight 不丢失 report/news/raw/source trace。

## 16. 需求 `/requirements`

### 16.1 目标态

把外部情报判断沉淀为内部需求，并能追溯到 report item、entity milestone、historical report/feedback、news 和 raw。

### 16.2 已做

- 列表、创建、状态更新和审计已接入真实 API。
- owner 选择已接入工作台成员；owner 必须是当前工作台启用成员。
- 状态变化会通知 owner，点击通知进入 `/requirements?requirement_id=...` 并高亮命中需求。
- workspace viewer 可读；workspace admin 可创建、指定 owner 和更新状态。
- requirement source links v1 已展示真实来源追溯：daily report item、weekly report item、
  entity milestone、historical report、historical feedback、news、raw、source title、source URL
  和 data source name；管理员创建需求时可选填来源日报条目 ID，归档页可通过专用来源字段转需求。
- 从日报/周报条目沉淀的需求会保留 report item、news、raw 和数据源追溯。
- 管理员可在有来源链路的需求上提交推荐反哺：正向/负向/中性结论和原因会写入
  `metadata_json.recommendation_feedback`，后端再转为可审计的 recommendation feedback action。
- `frontend/src/pages/RequirementsPage.spec.ts` 已覆盖来源追溯渲染、历史反馈回跳、创建 payload 和推荐反哺 payload。

### 16.3 未做

- 需求与评论、任务之间的联动和更多来源解释仍需深化。

### 16.4 测试看护

- requirement 必须能追溯外部信号。
- viewer 可读但不可指派或关闭。
- 推荐反哺必须有来源链路，不允许把无来源需求伪装成可反馈样本。
- intranet requirement/task 不进入 extranet feed；该项由 `backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_strategy_loop_private_objects` 看护。

## 17. 任务 `/tasks`

### 17.1 目标态

管理由 requirement 派生的专题任务、负责人、状态和截止日期。

### 17.2 已做

- 列表、创建、状态更新和审计已接入真实 API。
- 任务创建和列表内负责人选择已接入工作台成员，指派后会生成任务通知。
- 从任务通知进入 `/tasks?task_id=...` 会高亮命中任务。
- workspace admin 可创建、指派和关闭任务；被指派人可更新自己的任务状态，不能改负责人或标题。
- 任务列表已展示 requirement/source trace 链接，可回到需求、report item、历史报告、历史反馈、news、raw 和数据源。
- 任务列表已接入全部/我的/逾期/阻塞视图，真实调用 `GET /api/topic-tasks` 的
  `assigned_to_me`、`due=overdue` 和 `status=blocked` 筛选。
- 任务行已展示 `is_overdue`、`blocked_reason`，被指派人可提交 `blocked_reason` 并把任务置为 `blocked`。
- 页面已接入批量任务处理：可选择当前用户有权更新的任务，调用
  `POST /api/topic-tasks/batch` 批量更新状态和阻塞原因；workspace admin 可处理当前视图任务，
  被指派人只能处理自己名下任务。
- 任务详情已接入 `GET /api/topic-tasks/{id}`：从列表行或 `/tasks?task_id=...` 打开，
  只读展示任务说明、负责人、截止日期、阻塞原因、关联需求和来源证据，并能跳转到需求、日报/周报条目、
  news/raw 锚点。
- 任务详情已归入 AppModal lg 档（2026-07，产品设计 §10.3 第 8 项）：旧
  `report-modal-backdrop/report-detail-modal` 私有基座随之从 base.css 删除；
  只读详情非脏表单，Esc/遮罩直接关闭。
- `frontend/src/pages/TopicTasksPage.spec.ts` 已覆盖任务来源追溯、历史反馈回跳、负责人视图筛选、
  逾期/阻塞展示、blocked reason 更新、批量更新 payload 和任务详情 AppModal lg 档结构与 Esc 关闭。

### 17.3 未做

- 与评论和更多归档对象之间的解释关系仍需深化。

### 17.4 测试看护

- 被指派人只可更新自己的任务状态。
- 被指派人只可提交 `metadata_json.blocked_reason`，不能写任意 metadata。
- 批量更新必须走 `POST /api/topic-tasks/batch`，不能在前端循环调用单条接口伪装批量能力。
- 任务详情必须调用 `GET /api/topic-tasks/{id}`，不能只复用列表行数据伪装详情。
- workspace admin 可指派和关闭。
- task 能回到 requirement 和外部信号。

## 18. 同步 `/sync`

### 18.1 目标态

外网发布者和内网消费者之间可查看 feed/pull、水位、同步包、导入结果和冲突处置。

### 18.2 已做

- sync run 页面和审计入口已接入。
- 同步包导出、下载、导入和 inbox 幂等已有后端能力。
- feed/pull、`sync_cursors` 和 intranet 定时拉取已按目标态实现。
- 页面已读取 runtime `sync_publisher/sync_consumer` 能力：外网发布者展示“导出同步包”，内网消费者展示“立即拉取”，无同步角色实例只保留记录和能力说明。
- `sync_conflicts` 查询和人工处置 UI 已接入：展示 open conflicts、本地/传入 JSON 预览，并支持
  `keep_local`、`ignored`、`retry_after_dependency`、`use_incoming` 和 `manual_merge` 可审计处置；
  manual merge 当前对 `data_sources/daily_reports/weekly_reports` 显示合并 JSON 编辑框。
- 页面已接入 `GET /api/sync/health`，展示同步健康、缺失水位、失败水位、failed inbox、待处理冲突、
  告警列表和每类 cursor 最近拉取状态；严重/提醒状态来自后端，不由页面自行判断。
- 内网 consumer 在存在 failed inbox 时展示对象分布，并通过 `POST /api/sync/inbox/retry-failed`
  触发本地重放；该入口只修复本地失败 envelope，不替代“立即拉取”。
- 页面可消费 `/sync?sync_run_id=...` 和 `/sync?conflict_id=...`，从搜索/通知定位到同步运行或冲突并高亮。
- `frontend/src/pages/SyncRunsPage.spec.ts` 已覆盖发布者/消费者按钮分流、冲突列表、
  keep local/use incoming/manual merge 处置 API 调用、同步健康告警渲染、failed inbox 重试、同步运行锚点和冲突锚点。

### 18.3 未做

- extranet -> intranet 端到端实机证据未补齐。
- failed inbox 自动 backoff 策略、到期数量、最大尝试次数阻塞数量和下一次自动重试时间已可在健康卡展示；
  生产告警投递和实机 runbook 仍需深化。
- `manual_merge` 只开放给 `data_sources/daily_reports/weekly_reports`；更多对象需先补后端 apply handler 测试。

### 18.4 测试看护

- intranet 不显示 publisher 操作。
- feed 端点不走用户 cookie。
- secret-like payload 被拒绝并可见。
- conflict resolve 写审计。
- `manual_merge` 提交非法 JSON 时不能调用后端。

## 19. SQL 导出 `/exports`

### 19.1 目标态

管理员选择已发布日报，导出标准公司 SQL，预览、下载、查看 trace 和预检摘要。

### 19.2 已做

- 已发布日报选择、导出历史、SQL 生成、预览和下载已接入；生成后下载和历史下载都走服务端
  `GET /api/exports/{id}/download`，不会再用前端本地假下载替代。
- 标准 SQL 由 `scripts/validate_company_sql.py` 固定合同。
- 已接入导出前 preflight：展示通过/未通过、可导出/阻断/跳过、report-level 和 item-level
  errors/warnings；生成 SQL 前会先跑 preflight，失败则不生成。
- 后端 trace API 可从 SQL 回到 export job item、daily item、generated news、news、raw 和 source。
- 页面可消费 `/exports?export_job_id=...&export_job_item_id=...`，从搜索结果定位并高亮具体 trace 行。
- trace 详情 v1 已展示 SQL 片段、标题/摘要/关键点来源、五段正文来源、编辑覆盖字段和导出/编辑/生成/raw 字段差异预览，能区分日报编辑覆盖与生成稿，且不暴露 `raw_payload_json`。
- 下载失败会展示后端错误；普通 viewer 无下载权限，workspace admin/super_admin 可下载。
- SQL 预览支持一键复制，复制失败展示真实错误。
- 大文件下载策略 v1 已接入：页面展示完整 SQL 文件大小和当前预览大小；当后端返回
  `sql_text_truncated=true` 时禁用复制预览，并提示使用服务端下载获取完整文件。
- 批量导出治理 v1 已接入：页面可勾选多份已发布日报，调用 batch API 生成 manifest，
  展示成功/失败/SQL 总大小、逐日失败原因，并对成功日继续走服务端下载端点。
- 导入回执 v1 已接入：导出历史展示最新导入状态，回执区可加载历史回执并登记
  `pending/imported/failed/partial`、目标系统、导入/失败语句数、失败 SQL 序号/表、错误码和错误原因。
- 内网 importer 回调 v1 已接入：回执区展示 `POST /api/exports/{id}/import-receipts/callback`
  配置入口，后端只接受 `SYNC_SERVICE_TOKENS` Bearer token，不展示 token。

### 19.3 未做

- 生产实机导入证据仍需补；真实导入反馈不能改变公司 SQL 字段契约，只能作为导出任务的验收/审计附属信息。

### 19.4 测试看护

- 只能导出已发布日报中采信且 MiniMax ready 的条目。
- rule fallback 不能导出。
- SQL category 来自 `generated_news.category` AI 十分类。
- SQL 预览必须通过 validator。
- preflight 失败不能调用生成 SQL。
- 截断预览不能被当作完整 SQL 复制；完整文件必须从服务端下载端点获取。
- batch manifest 必须展示逐日成功/失败，不允许把部分失败渲染成全成功。
- `frontend/src/pages/ExportsPage.spec.ts` 覆盖导出任务锚点、trace 条目锚点、SQL 片段、字段来源、字段差异预览、preflight 摘要、preflight 失败阻断和批量 manifest。
- 导入回执必须走真实 API，能展示历史回执、登记新回执，并把失败语句记录到导出任务；callback 无 token 必须失败，合法 service token 可写入回执。

## 19.5 工作台配置 `/workspace-settings`

### 19.5.1 目标态

当前工作台的配置中心：admin/owner 在工作台内完成基本信息、导航分区、标签策略、
报告策略、成员和报告格式的运营配置，不再依赖全局管理员或分散入口。

### 19.5.2 已做

- 分区注册：`workspace_settings` 是 system 分组核心分区（`config_json.min_role=admin`，
  不可停用），路由 `/workspace-settings`；AppShell 按有效角色过滤后仅 admin/owner
  （含全局 super_admin/editor_admin）可见，无权限访问渲染拒绝态说明。
- 基本信息：名称/描述/默认板块编辑（`PATCH /api/workspaces/{code}`）。
- 导航分区：`GET /api/workspaces/{code}/sections/manage` 列出分区，
  `PATCH /api/workspaces/{code}/sections/{section_key}` 启停可选分区，核心分区锁定。
- 标签策略：一级/二级/降级标签完整编辑器（与原 `/sources` 侧策略面板同一 API 口径）。
- 报告策略：`report_policy.auto_publish_daily` 自动发布开关
  （`GET/PATCH /api/workspaces/{code}/report-policy`）。
- 成员与角色：成员列表、添加/移除、角色调整（复用 members API 及 owner 守护规则）。
- 报告格式：自定义 report format 启停与新建（复用 `/api/report-formats`）。
- 「自动化」设置卡（2026-07-08 实施，WP3-H；后端供给
  `docs/backend/pipeline-jobs-design.md` §8.2/§8.4，契约
  `config/contracts/workspace_model.json` `schedule_policy`）：读写
  `GET/PATCH /api/workspaces/{code}/schedule-policy`，展示触发时刻、day_offset、
  run 级重试（max_attempts/backoff）、周报节拍与下次运行时间预览；每个字段标注
  生效值来源（"跟随实例默认" vs "本工作台"）；实例总闸关闭或 intranet 禁采集时
  整卡只读并解释原因；保存写审计 `workspace.schedule_policy.update`。
- 「生成模型」设置卡（2026-07-08 实施，WP3-H；后端供给
  `docs/backend/generation-provider-design.md` §4/§5，契约
  `config/contracts/workspace_model.json` `generation_policy`）：状态行展示
  provider、模型、key 只显示"已配置/未配置"永不回显、最近连通状态；可编辑模型名、
  温度、超时、每日预算、fallback 行为（`GET/PATCH generation-policy`）；「测试连通」
  按钮（仅 super_admin/editor_admin 可见）调 `POST /api/generation/ping`，展示延迟
  或分类错误，失败不渲染成成功。
- 「可见性与加入码」设置卡（2026-07-08 实施，WP3-G/H；契约
  `config/contracts/workspace_model.json` `join_code`）：可见性
  `private | internal_public` 切换（`PATCH /api/workspaces/{code}/visibility`）前
  必须确认「任何登录用户可发现并以 viewer 订阅」影响提示；加入码显示当前有效码
  （一键复制，8 位大写字母+数字）、默认角色（viewer|member）、有效期、已用次数/
  上限；生成/轮换（轮换先确认旧码立即失效）与停用调用 join-code 三端点；无有效码
  时显示生成引导与用途说明。

### 19.5.3 未做

- viewer 反馈策略编辑仍在 `/users` 策略视图，不在本页。

### 19.5.4 测试看护

- `frontend/src/pages/WorkspaceSettingsPage.spec.ts` 覆盖五块设置卡的 admin 渲染、
  member/viewer 隐藏、基本信息保存、标签策略保存与失败错误态、自动发布开关、
  报告格式启停/新建、可选分区启停与核心分区锁定、成员角色调整。
- 后端 `workspace_settings` 分区播种、min_role=admin、不可停用和 sections manage
  权限门由 `backend/tests/test_workspaces_api.py` 看护。
- 自动化卡：生效值来源标注、下次运行预览、总闸关闭只读态与保存审计由
  `WorkspaceSettingsPage.spec.ts` 看护；生成模型卡：key 只显示已配置/未配置、
  测试连通失败不渲染成功同样有 spec 断言（假成功回归）。
- 加入码卡（已实施）：生成/轮换/停用调用真实 API 并刷新展示；轮换必须先确认；
  member/viewer 不渲染该卡；码值以只读文本 + 复制按钮呈现，复制失败显示真实错误；
  `WorkspaceSettingsPage.spec.ts` 看护。

## 20. 用户权限 `/users`

### 20.1 目标态

管理员管理用户、邀请、角色、工作台成员和权限策略。

### 20.2 已做

- 用户、角色、邀请、membership gate 和成员管理已有基础 API/页面。
- 工作台 membership 已作为业务 API 权限边界。
- 页面已形成“用户、邀请、工作台成员、策略”四个入口；`super_admin` 可看全局用户/邀请，
  非 `super_admin` 只看工作台成员和当前工作台策略上下文。
- 邀请列表已把 `pending/accepted/revoked/expired` 显示为可读状态，并只允许撤销 pending 邀请。
- 策略页展示 `auth_mode`、部署实例、全局角色、工作台角色矩阵和后续治理项；
  viewer 反馈策略和当前工作台部门自动开通规则可编辑，危险批量权限策略不提供未设计的编辑按钮。
- 策略页已读取 runtime 下发的只读自动开通规则，展示默认工作台和部门到工作台 membership
  映射；配置无效时显示后端解析错误。
- 策略页已读取并编辑当前工作台 DB 部门 membership 映射，保存前必须勾选影响确认；
  OIDC/header 自动建号时后端会合并部署 env 规则和 DB 规则，同工作台取更高角色。
- 策略页已展示最近的身份权限审计摘要，覆盖邀请、用户、密码、工作台成员和
  feedback_policy 变更动作。
- 策略页已接入权限差异解释与批量回滚：`GET /api/identity/permission-changes`
  把全局角色、工作台成员、viewer 反馈策略和部门自动开通规则的 before/after 渲染成可读 diff；
  `POST /api/identity/permission-rollbacks` 可回滚选中变更，并由后端继续保护最后 `super_admin`
  和最后 workspace `owner`。
- 策略页已读取并编辑工作台 `feedback_policy`，保存前必须勾选影响确认；`viewer_can_edit`
  固定为 false，保存后刷新审计摘要。
- 工作台成员页已展示角色变更影响、当前 owner 数量和审计动作提示；owner 降权或移出必须二次确认，
  最后一个 owner 的移出按钮会前端禁用，后端仍保留硬拦截。
- `frontend/src/pages/UsersPage.spec.ts` 已覆盖 `super_admin` 四块入口、非 `super_admin`
  权限收敛、自动开通规则、当前工作台部门映射编辑、权限审计摘要、角色影响提示、owner 危险变更确认、
  最后 owner 禁用态和反馈策略影响确认保存。

### 20.3 未做

- OIDC/header 自动开通后的默认工作台和部门 membership 已有部署 env 配置、runtime 只读展示、当前工作台
  DB 映射编辑和测试；部署层 env 规则仍只由运维配置管理。
- viewer 评论/点赞/评分策略已落到 `feedback_policy`、后端权限检查、日报页禁用测试和 `/users`
  可视化编辑；后续还需更多对象联动。
- owner 降权/移出已有二次确认和最后 owner 后端保护；权限变更 diff 和批量回滚已接入，跨实例/内网门户实机验收仍需补证据。
- 权限审计摘要已能看到最近身份权限动作；审计详情钻取仍需深化。

### 20.4 测试看护

- `super_admin` 能看到用户、邀请、工作台成员、策略四个 tab。
- 非 `super_admin` 不能看到全局用户和邀请 tab，只能进入成员和策略视角。
- 策略页只允许保存已实现的 viewer 反馈策略和当前工作台部门自动开通规则；批量危险权限策略不出现未实现保存动作。
- workspace admin 只能管理本工作台成员。
- super_admin 才能做全局用户/角色管理。
- 最后一个 owner 不能移除，前端禁用态和后端 400 都要有测试守护。
- 工作台成员页展示角色变更影响、owner 数量和审计动作提示。
- 策略页展示部署默认工作台规则和部门 membership 映射，不暴露 provider secret；当前工作台部门映射保存必须确认影响范围。
- 策略页展示身份权限审计摘要，且不混入非身份权限动作。
- 策略页展示权限变更 diff，可选择多条变更回滚；回滚必须调用
  `POST /api/identity/permission-rollbacks`，不能只在前端恢复状态。
- 邀请 pending、accepted、revoked、expired 状态正确显示，非 pending 邀请不能撤销。

## 21. 审计 `/audit-logs`

### 21.1 目标态

管理员查询登录、权限、采集、发布、导出、同步、策略变更等关键操作。

### 21.2 已做

- 审计页已从占位升级为真实 API 页面。
- 关键操作已有审计记录。
- `GET /api/audit-logs` 已支持 `workspace_code` 过滤和权限门禁；`/audit-logs` 页面按当前工作台请求。
- `frontend/src/pages/AuditLogsPage.spec.ts` 覆盖工作台过滤调用、审计详情展示、空态和错误态。

### 21.3 未做

- action taxonomy 需要统一。
- 与告警、失败趋势、备份恢复证据的联动未完成。
- 用户筛选、导出和详情体验需要增强。

### 21.4 测试看护

- 审计不包含 secret-like 值。
- workspace admin 只能查本工作台审计；viewer 查询返回 403。
- 登录、发布、导出、同步、权限变更均可查。

## 22. 登录 `/login`

### 22.1 目标态

根据 runtime auth mode 展示正确登录入口：

- public password。
- OIDC SSO。
- intranet header 自动登录提示。

### 22.2 已做

- public password 登录可用。
- 通用 OIDC authorization code flow + PKCE 已有后端基础。
- 前端已根据 `auth_mode=oidc` 显示 SSO 入口并跳转 `/api/auth/oidc/start`。
- 前端已在 `intranet_header` 模式隐藏本地密码登录并提示从门户进入。
- 密码登录和 OIDC start 已读取 router `redirect` query，登录后回到原目标页。
- 前端已承接 `/login?auth_error=...`，覆盖 OIDC 未配置、provider error、state 异常、
  token/claims/membership 失败等固定错误文案。
- session、登录限流、must_change_password 已接入；must_change_password 用户登录后直接进入
  `/account`。
- 游客登录入口已接入：`GET /api/meta/runtime.auth_guest_enabled=true` 时登录页显示
  「以游客身份浏览」按钮（`POST /api/auth/guest-login`），游客会话顶栏身份显示「游客」，
  只读浏览 internal_public 工作台的已发布内容。
- `frontend/src/pages/LoginPage.spec.ts` 已覆盖 public password、OIDC、intranet header 三种入口、
  redirect query、OIDC callback 错误提示，以及游客入口的条件渲染/登录跳转/失败文案。

### 22.3 未做

- 真实 OIDC provider 验收缺证据。
- intranet header 模式下的自动登录/错误提示体验不足。

### 22.4 测试看护

- `auth_mode=oidc` 时显示 SSO 入口且不显示普通密码表单。
- `auth_mode=intranet_header` 时不显示普通密码表单。
- 登录失败限流错误可读。
- must_change_password 登录后跳 `/account`。
- redirect query 登录后能回到原页面。
- `auth_error` query 会展示固定可读文案，且不暴露 backend/provider 原始细节。

## 23. 首次设置 `/setup`

### 23.1 目标态

空用户库时创建首个 super_admin，之后不可再次设置。

### 23.2 已做

- `GET /api/setup/status` 和 `POST /api/setup` 已有。
- router guard 会在 needs_setup 时强制进入 `/setup`。
- 页面已做密码长度/确认一致性校验、首管创建后写入 session/setup store、可选 legacy/Tech
  种子导入和成功后进入 `/dashboard`。
- setup 已完成的 410 错误已映射为友好文案。
- `frontend/src/pages/SetupPage.spec.ts` 已覆盖短密码不发请求、创建首管并按勾选导入种子源、
  setup 已完成错误态。
- `frontend/src/router/index.spec.ts` 已覆盖 `needs_setup` 强制进入 `/setup`、setup 已完成访问
  `/setup` 转登录、未登录访问保护页保留 redirect、已登录访问 `/login` 转首页，以及
  `must_change_password` 强制进入 `/account`。

### 23.3 未做

- 真实空库首次设置、bootstrap password 存在时不进入 setup 仍需端到端证据。
- 复杂密码强度仪表不做第一版，仅保留最小长度和确认一致性。

### 23.4 测试看护

- setup guard 必须持续覆盖 needs_setup、setup complete、未登录 redirect、已登录 redirect 和 must_change_password。
- 空用户库创建第一个 super_admin。
- bootstrap password 存在时不进入 setup。
- 组件层已覆盖短密码、可选种子导入、成功后跳转和 410 友好错误。

## 24. 邀请 `/invite/:code`

### 24.1 目标态

受邀用户设置账号并获得指定全局角色和工作台 membership。

### 24.2 已做

- 路由和页面存在。
- 邀请建号后进入本地身份和 membership 体系。
- pending 邀请会展示邮箱提示、全局角色、目标工作台 membership 和有效期，并允许用户设置账号。
- expired、revoked、accepted 邀请会显示可读原因和下一步，不展示创建账号表单。
- 前端已做账号/姓名/密码长度/确认密码校验，用户名冲突、邀请不存在、邀请过期/撤销/已接受等后端错误会映射为用户可读文案。
- `frontend/src/pages/InvitePage.spec.ts` 已覆盖 pending 接受、空账号校验、expired/revoked/accepted 状态、
  用户名冲突和无效链接。

### 24.3 未做

- 邀请接受页仍不做复杂密码强度仪表，只执行第一版最小长度和确认一致性校验。
- 邀请创建侧的角色权限不足体验归 `/users` 管理页和后端权限测试，不在公开接受页重复实现。

### 24.4 测试看护

- 过期邀请不能建号。
- 已撤销邀请不能建号。
- 接受后 membership 正确。
- 公开邀请页不能对非 pending 邀请展示创建账号表单。
- 用户名冲突和无效链接显示友好文案，不暴露原始后端异常。

## 25. 账号 `/account`

### 25.1 目标态

当前用户查看和编辑资料、修改密码、处理 must_change_password，未来管理会话。
settings 模板：垂直分组设置卡，顺序为「资料」「密码」「身份来源」「会话（未来）」。

「资料」卡片规格（2026-07 定稿，契约 `config/contracts/auth_modes.json`
`profile_self_service`，后端设计 `docs/backend/identity-access-design.md` §4.4）：

- 本地账号（`external_provider=local`）：可编辑 `display_name`（必填，1-128 字符）、
  `department`（可空）、`email`（可空，格式校验）三个字段 + 保存按钮，调用
  `PATCH /api/auth/me`；`username` 只读展示并注明「登录账号不可修改」；保存成功后
  刷新 session store，顶部用户胶囊立即显示新姓名；保存失败展示后端错误，不显示假成功。
- 外部身份（OIDC / intranet_header）：同一卡片只读展示字段，并说明「资料由外部身份
  系统管理，登录时自动同步」，不渲染编辑表单和保存按钮（与改密边界同一语义）。
- 游客会话：不渲染资料卡片。
- must_change_password 用户：先完成改密，改密前资料表单禁用。

### 25.2 已做

- 页面和路由存在。
- 改密、管理员重置后的 must_change_password 约束已接入。
- router guard 会把 must_change_password 用户引到账户页。
- 页面已展示当前用户资料摘要；本地账号显示改密表单，OIDC/header 等外部身份只显示只读身份来源说明，
  不展示必然失败的本地密码修改入口。
- 「资料」卡片编辑（§25.1）已实施（2026-07-08，WP3-F）：本地账号可编辑
  display_name/department/email 并保存到 `PATCH /api/auth/me`，保存后刷新
  session store 使顶部胶囊立即显示新名字；外部身份渲染只读说明不渲染表单；
  审计 `auth.profile.update`。
- `frontend/src/pages/AccountPage.spec.ts` 已覆盖本地改密、前端密码校验、外部身份隐藏改密表单，
  以及资料卡本地编辑保存、空 display_name 不发请求、外部身份只读、保存后胶囊刷新。

### 25.3 未做

- 会话列表和主动踢下线未完成。
- 顶部用户胶囊到账号页的明确入口已落实并有 AppShell 测试。

### 25.4 测试看护

- must_change_password 只能访问 `/account`、logout 和 me。
- 改密后旧 cookie 失效。
- OIDC/header 用户不应看到本地密码修改入口；该边界由 `AccountPage.spec.ts` 和后端
  `Password is managed externally` 共同看护。
- 资料卡（已实施）：本地账号保存调用 `PATCH /api/auth/me` 并刷新胶囊显示名；
  display_name 为空不发请求；外部身份不渲染编辑表单，后端对外部身份返回
  `Profile is managed externally`；游客 403；资料变更写 `auth.profile.update` 审计；
  前后端分别由 `AccountPage.spec.ts` 和 `backend/tests/test_auth.py` 看护。

## 26. 我的消息 `/notifications`

### 26.1 目标态

展示评论、@、任务指派、同步冲突、日报/周报发布等与当前用户有关的通知。

### 26.2 已做

- 后端目标设计已在 `docs/backend/collaboration-notification-design.md`，机器契约见
  `config/contracts/notifications.json`。
- 已有路由和页面：`frontend/src/pages/NotificationsPage.vue`。
- 页面读取真实 API：`GET /api/notifications/unread-count` 和 `GET /api/notifications`。
- 支持未读/全部/已读/归档筛选、单条已读、全部已读和单条归档。
- AppShell 顶部铃铛已恢复，未读数来自后端 API；API 失败时只降级为 0。
- 日报评论通知可跳 `/daily-reports?item_id=...&comment_id=...`，日报页会自动打开对应日报条目详情并高亮命中评论。
- 日报评论中的 `@username` 会生成 `comment.mentioned` important 通知，消息页偏好显示为“评论提及我”，点击仍定位到命中评论。
- 日报/周报发布通知可跳 `/daily-reports?report_id=...` 和 `/weekly-reports?report_id=...`，对应页面会选中目标报告。
- 页面已提供当前工作台的站内通知偏好开关；保存后只影响未来生成的通知。
- 同步冲突创建后会给管理员生成站内通知，列表页按同一通知 API 展示；点击通知可跳 `/sync?conflict_id=...` 并高亮 open conflict。
- 失败源自动重试到期或阻塞后会给管理员生成 `ingestion.failed_source_retry_due/blocked` 站内通知；
  点击通知可跳 `/ingestion-runs?run_id=...` 并选中对应抓取 run。
- 通知跳转目标已由后端 `NotificationRead.target_label/target_path` 统一解析；消息页不再本地猜路由。
- 周报条目更新通知已接入：`weekly_report_item.updated` 从周报条目 PATCH 生成；当通知目标是
  `weekly_report_item` 时跳 `/weekly-reports?item_id=...`，
  周报页会选中并高亮命中条目。
- 日报/周报条目关注入口已接入真实 object watcher API；关注后的提醒收件人由后端通知模块生成，前端不本地推断。
- `frontend/src/pages/NotificationsPage.spec.ts`、`DailyReportsPage.spec.ts`、
  `WeeklyReportsPage.spec.ts`、`IngestionRunsPage.spec.ts`、`SyncRunsPage.spec.ts` 和 `TopicTasksPage.spec.ts`
  覆盖通知列表、归档动作、后端 target_path 渲染、报告级跳转、周报 item 锚点、同步冲突锚点、
  抓取 run 锚点、任务锚点和页面锚点消费。

### 26.3 未做

- 邮件投递通道未启用，`email_enabled` 只在后端保存为预留字段。
- 点击通知已能定位到日报条目、命中评论、日报/周报报告、周报条目更新、同步冲突、失败源抓取 run、被指派任务和需求；
  更多对象提及仍未完成。
- 内网本地反馈/通知不进入 sync feed 已由后端专项负向测试看护；前端不单独承担同步出站判定。

### 26.4 恢复条件

- 顶部铃铛恢复条件已满足：未读数、列表和已读 API 均存在，AppShell 测试覆盖。
- 下一阶段恢复下拉/偏好/精确定位前，必须补对应后端 API、契约和页面测试。
- 组件和 E2E 后续覆盖周报/需求提及、回复和更多对象通知生成。

## 27. 全局搜索 `/search` 或顶部搜索面板

### 27.1 目标态

检索日报、周报、候选新闻、数据源、实体、需求、任务和评论，按权限过滤并跳转对象。

### 27.2 已做

- 目标设计已在 `docs/backend/search-design.md`。
- 后端 `GET /api/search` 已实现数据库查询 v1，按 workspace membership 和对象归属过滤。
- `GET /api/meta/runtime` 已下发 `capabilities.search`。
- 后端已覆盖 intranet/`capability_ingestion=false` 下默认搜索和显式 `types=data_source`
  都不返回数据源结果，避免内网消费端暴露采集对象。
- AppShell 顶部搜索已恢复为结果面板，输入 2 个字符以上触发，结果按类型分组，支持键盘选择，
  点击或回车可跳转业务对象；空搜索框可展示本地近期结果。
- `frontend/src/layouts/AppShell.spec.ts` 覆盖搜索 API 调用和结果跳转。
- 历史报告、实体/事件、候选新闻、周报条目、report rendition、导出任务/trace 条目、同步运行和同步冲突页面已消费搜索 query 并高亮命中对象。

### 27.3 未做 / 禁显

- 独立 `/search` 页面不做 v1；如后续需要，必须先补产品设计。
- Playwright E2E 尚未补齐。
- 后续新增对象锚点必须同步 Search contract、对应页面 query 承接和组件测试。

### 27.4 恢复条件

- 顶部搜索 v1 恢复条件已满足：后端 Search API、权限过滤、runtime capability、结果面板、
  空态/错误态/加载态和组件跳转测试均已存在。
- 进入 v2 前必须补 Playwright 关键旅程和更多对象锚点。

## 28. ModuleRoadmapPage（已删除）

### 28.1 定位

`ModuleRoadmapPage.vue` 曾是早期路线页遗留：无路由引用、无 spec、不受 section
gating，属游离死代码。

### 28.2 当前处理

- 文件已于 2026-07-07 删除（技术债台账 R-015）。
- 后续如需要路线/占位能力，必须新建页面并由 `workspace_sections` 显式启用，
  遵循“不可假控件”规则并补 spec。

## 29. 逐页测试优先级

| 优先级 | 页面 | 测试目标 |
|---|---|---|
| P0 | AppShell | 顶部真实搜索、结果分组、键盘选择、本地近期结果、通知铃铛和用户入口已覆盖；继续补更多 runtime capability 和 E2E |
| P0 | Frontend control governance | `scripts/validate_frontend_controls.py` 已扫描页面/壳按钮动作、RouterLink 目标、AppShell 搜索/通知/账号入口的 API/contract/test 证据；继续补更多页面级业务入口映射和 Playwright |
| P0 | Search anchors | 历史报告、实体/事件、候选新闻、周报条目、report rendition、导出任务/trace 条目、同步运行和同步冲突搜索锚点已覆盖；继续补 E2E |
| P0 | `/notifications` | 真实未读/列表/已读/归档 API、后端 target_path、日报条目跳转、评论高亮、日报/周报条目关注入口、周报条目更新通知、失败源抓取 run 锚点和站内偏好已覆盖；继续补更多对象通知生成和邮件 |
| P0 | `/sources` | import preview、0 结果语义、intranet 禁采集、详情入口、安全源详情和标签策略保存失败错误态已覆盖；继续补 E2E |
| P0 | `/ingestion-runs` | `limit=0`、`no_sources`、read-only deployment、失败源手动重试、长期趋势、自动重试策略和通知 run 锚点、arXiv/OpenAlex/Semantic Scholar paper_api 补采入口已覆盖；继续补更多 provider、邮件/外部告警通道和更长周期趋势 |
| P0 | `/login` | auth mode 入口、redirect、must_change_password 跳转和 OIDC 错误提示已覆盖；继续补真实 provider 证据 |
| P0 | `/users` | 四块入口、邀请状态、viewer 反馈策略编辑、自动开通规则、当前工作台部门映射编辑、权限审计摘要、owner 危险变更确认、最后 owner 前后端守护、权限变更影响、配置 diff 和批量回滚已覆盖；继续补真实 provider/内网门户验收 |
| P1 | `/dashboard` | 真实 API 聚合、空态、错误态和 read-only 部署隐藏采集入口已覆盖；继续补点击跳转 E2E 和源健康长期趋势 |
| P1 | `/setup` | 短密码、首管创建、可选种子导入、成功跳转、410 友好错误和 router guard 已覆盖；继续补真实空库 E2E |
| P1 | `/quality-archive` | 归档 summary、历史反馈、旧任务、引用缺口、筛选、历史反馈转需求来源、空态边界和错误态已覆盖；继续补当前反馈/推荐反馈分解释关系 |
| P1 | `/daily-reports` | feedback_policy 禁用态已覆盖；继续补 fallback、编辑不污染源数据、评论消息流转 |
| P1 | `/exports` | SQL gate、trace、trace 字段来源、trace 字段差异预览、导入回执、失败语句反馈、service token importer 回调、preflight、服务端下载、viewer 下载禁用、预览复制、截断预览保护和批量 manifest 已覆盖；继续补真实内网平台生产联调证据 |
| P1 | `/sync` | role capability、同步健康/水位/failed inbox 告警、failed inbox 重试、自动 backoff 状态、open conflict 查询/处置 UI、use_incoming/manual_merge 已覆盖；继续补实机证据、告警投递和更多对象 manual_merge |
| P1 | `/insights`、`/requirements`、`/tasks` | 洞察/战略影响独立管理、外部信号追溯、历史反馈来源追溯、需求结论反哺、任务负责人视图、blocked reason、批量处理和任务详情抽屉已覆盖；继续补跨对象联动体验、评论和更多归档对象解释关系 |
| P1 | 体验系统轨道（§1.1/§3.1/§4.1/§19.5/§25） | 布局模板与 spacing token 收敛、Dashboard 重排分区归属与源健康折叠、向导/发现/新增源/导入预览迁居中 Modal（含 Esc/遮罩/焦点/脏表单确认）、账号资料编辑边界、发现搜索与凭码加入 |
| P1 | 报告页 IA 轨道（R3 设计，§4.4/§10/§12/§13） | ReportTimeline 分组/无限滚动/跳月/草稿权限、顶部筛选条只读过滤、详情卡 spacing token、Dashboard 头条 final_score 降序断言、空指标隐藏、归档页重定位断言、`test_blueprint_page_audit.py` 文案审计扩展断言 |
| P2 | `/news`、`/recommendations` | 筛选跳转、观察池运营深化、策略编辑和批量重算解释 |
