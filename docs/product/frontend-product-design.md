# 前端产品与页面设计

> 状态：目标态整理稿。本文只描述前端信息架构、页面职责、用户旅程和交互边界；
> 不定义后端数据模型。后端能力归属见 `docs/backend/backend-module-design.md`。

本文是前端用户界面的产品设计权威。用户、权限、SSO、评论事件和通知收件箱的后端
设计分别见 `docs/backend/identity-access-design.md` 和
`docs/backend/collaboration-notification-design.md`。全局检索后端设计见
`docs/backend/search-design.md`。顶部栏、侧边栏、页面出现规则由本文定义；
它们不能替代后端模块设计。

逐页 PM 规格、已做/未做标记和测试看护见 `docs/product/page-specs/frontend-page-specs.md`。本文只维护
前端总体信息架构和出现规则，不承载每个页面的完整交互清单。

## 1. 前端设计目标

InfoWatchtower 前端不是后台表格集合，而是一个产业情报工作台。

前端的职责是：

- 让用户清楚知道当前在哪个工作台。
- 让用户按业务链路完成“采集、筛选、编审、成稿、分发、协作、管理”。
- 清晰表达哪些能力在当前部署形态下可用，哪些被禁用。
- 不展示没有真实业务后端支撑的控件。
- 每个页面都有明确任务、数据来源、空态和下一步动作。

## 2. 前端信息架构

当前前端采用“工作台壳 + 左侧分组导航 + 页面内容区”的结构。

导航分组：

| 分组 | 页面 | 用户任务 |
|---|---|---|
| 今日 | 今日速览 | 快速了解今天情报生产状态 |
| 情报采集 | 数据源管理、抓取与覆盖 | 管源、跑抓取、看覆盖 |
| 编审工作流 | 候选池、推荐运行、日报、周报 | 判断、采信、编辑、发布 |
| 资料库 | 历史报告库、实体大事记、质量归档 | 查历史资产和质量证据 |
| 协作 | 洞察研判、需求、任务 | 把情报转成洞察、内部需求和任务 |
| 系统 | 同步、SQL 导出、工作台配置、用户权限、审计 | 管理、导出、同步、配置、审计 |

页面入口来自后端 `workspace_sections`，前端不能硬编码一个与工作台配置冲突的页面集合。

## 3. 全局壳设计

全局壳只承载跨页面上下文和已经闭环的快捷入口。任何全局控件进入 AppShell 前，
必须同时满足：

- 有明确用户任务。
- 有对应后端模块和 API/contract。
- 有前端页面或弹层承接完整操作。
- 有空态、禁用态和权限态。

### 3.1 侧边栏

侧边栏是主导航，不是装饰：

- 品牌。
- 工作台切换。
- 新建工作台入口，仅有权限用户可见。
- 「发现工作台」入口（工作台切换器底部，`frontend/src/components/WorkspaceDiscovery.vue`）：
  列出 `visibility=internal_public` 的可订阅工作台，支持自助订阅（viewer）与退订；
  角色高于 viewer 显示「由管理员管理」，游客隐藏订阅按钮并提示注册。
  目标态（2026-07 体验系统轨道定稿）：该入口迁为居中 Modal（md 档，§10），顶部增
  名称/描述搜索框（`GET /api/workspaces/discover?q=`），底部增「凭码加入」区
  （`POST /api/workspaces/join-by-code`，§12.2）。
- 六组业务导航（按当前工作台有效角色和 `section.config_json.min_role` 过滤）。
- 侧边栏底部账号快捷操作。

侧边栏已经覆盖所有页面入口，因此不需要“页面搜索”补充导航。

### 3.2 顶部栏

顶部栏只显示跨页面上下文，不承担未落地能力：

当前阶段建议：

| 元素 | 状态 | 说明 |
|---|---|---|
| 工作台名称 | 保留 | 当前上下文 |
| 工作台描述 | 保留 | 一行省略 |
| 部署形态 badge | 保留 | cloud/intranet/extranet 影响操作可用性 |
| 窄屏工作台切换 | 保留 | 侧边栏坍缩后的必要入口 |
| 搜索框 | 已恢复 v1 | 只在 `capabilities.search=true` 时显示，调用 `/api/search` 检索真实情报对象，结果按对象类型分组并支持键盘选择；空搜索框展示本地近期结果 |
| 通知铃铛 | 已恢复 | 后端已有未读数和通知列表 API；只显示真实未读数 |
| 用户胶囊 | 已改为明确账号入口 | 进入 `/account`；下拉菜单需后续设计确认 |

顶部栏不是功能堆放区。凡是“点击后没有真实业务闭环”的控件都不应出现。
用户胶囊只是账号入口，不定义用户模型；用户模型和权限策略以
`docs/backend/identity-access-design.md` 为准。通知铃铛只是消息快捷入口，不定义通知系统；
通知系统以 `docs/backend/collaboration-notification-design.md` 为准。

### 3.3 搜索入口的恢复条件

只有当后端提供统一检索模块时，顶部搜索才恢复。当前 v1 已恢复为 AppShell 顶部结果面板，
不建设单独 `/search` 页面，也不搜索左侧页面名。

前端搜索体验目标：

- 搜索对象：日报、日报条目、周报、周报条目、候选新闻、生成稿、report rendition 成稿快照、数据源、实体、需求、任务、评论、导出任务/trace 条目、同步运行/冲突（管理员）。
- v1 结果按对象类型分组，支持上下键选择、回车打开和 ESC 关闭。
- v1 保留最近打开过的搜索结果，只存浏览器本地，按用户和工作台隔离。
- 每个结果能跳到真实详情位置。
- 搜索范围受当前工作台、用户权限、`visibility_scope` 限制。

如果只是搜索左侧页面名，不做顶部搜索。

### 3.4 通知入口的恢复条件

后端提供通知模块和未读状态后，铃铛才恢复。当前已满足最小恢复条件：顶部铃铛显示
`GET /api/notifications/unread-count` 返回的真实未读数，点击进入 `/notifications`。

前端通知体验目标：

- 顶部铃铛显示未读数。
- “查看全部”进入我的消息页；当前第一版直接进入 `/notifications`，不做未设计的下拉。
- 点击通知能跳到后端 `target_path` 指定的具体对象，例如日报条目评论、周报 item、任务、同步冲突；
  当前日报条目通知已跳 `/daily-reports?item_id=...&comment_id=...` 并打开对应条目、突出命中评论。
  周报条目更新通知已跳 `/weekly-reports?item_id=...` 并高亮命中条目；日报详情和周报条目可关注对象，
  关注后由后端通知模块决定后续评论/更新提醒；后续补更多对象的通知生成和提及。
- 点赞/评分默认不逐条弹通知，避免噪音。

没有 `notifications` 后端数据前，不显示假红点；API 失败时未读数只降级为 0。

## 4. 页面设计总表

| 页面 | 前端任务 | 后端模块 |
|---|---|---|
| `/dashboard` 今日速览 | 看今日漏斗、头条候选、最新日报/周报、源健康；调度心跳/下次运行运营卡已实现（侧栏第 6 位，`docs/backend/pipeline-jobs-design.md` §8.5） | pipeline/reports/sources |
| `/sources` 数据源管理 | 管共享源、工作台启用、标签策略 | sources/workspaces |
| `/ingestion-runs` 抓取与覆盖 | 运行抓取/补采、看覆盖漏斗和每源结果 | ingestion |
| `/news` 候选池 | 查看去重代表、评分、来源、日报状态、批量采信 | content/dedupe/recommendation/reports |
| `/recommendations` 推荐运行 | 运行或查看推荐、评分策略摘要、分数拆解 | recommendation |
| `/daily-reports` 日报 | 生成、编审、成稿、评论、采信、发布 | reports/collaboration |
| `/weekly-reports` 周报 | 周度组稿、后端摘要段、板块采信、发布 | reports |
| `/historical-reports` 历史报告库 | 查看旧报告、导入验收缺口 | archive |
| `/entity-milestones` 实体大事记 | 查看实体事件时间线 | archive/entity |
| `/quality-archive` 质量归档 | 查看旧反馈、旧任务、质量缺口，并把历史反馈显式转为需求来源 | archive/quality |
| `/insights` 洞察研判 | 管洞察判断和战略影响 | strategy |
| `/requirements` 需求 | 管内部需求 | strategy |
| `/tasks` 任务 | 管专题任务 | strategy |
| `/notifications` 我的消息 | 查看和处理当前用户站内通知 | collaboration/notifications |
| `/sync` 同步 | 看同步 run、水位、冲突、立即拉取 | sync |
| `/exports` SQL 导出 | 选择日报、导出、预览、追溯 | exports |
| `/workspace-settings` 工作台配置 | 工作台内配置中心：基本信息、导航分区启停、标签策略、报告策略（自动发布）、成员、报告格式、可见性与加入码（§12）、自动化（调度时刻/重试/周报节拍/下次运行预览）与生成模型（模型参数/预算/连通状态，key 只显示已配置|未配置）——三卡已实现（2026-07-08，`docs/backend/pipeline-jobs-design.md` §8.4、`docs/backend/generation-provider-design.md` §5）（admin/owner 可见；viewer 反馈策略仍在 `/users` 策略视图） | workspaces |
| `/users` 用户权限 | 管用户、邀请、用户组、工作台成员、权限策略 | identity/access |
| `/audit-logs` 审计 | 查询关键操作 | audit |
| `/login` 登录 | 根据认证模式展示正确入口 | identity/access |
| `/setup` 首次设置 | 创建首个管理员 | identity/setup |
| `/invite/:code` 邀请接受 | 受邀用户建号并进入工作台 | identity/invite |
| `/account` 账号 | 当前用户资料查看与编辑（本地账号可改 display_name/department/email，§11）、本地账号改密、外部身份只读说明、会话状态 | identity/account |

## 5. 用户旅程

### 5.1 管理员首次部署

```text
打开系统
-> /setup 创建首个管理员
-> 新建或选择工作台
-> 导入/自建数据源
-> 配置标签策略
-> 跑抓取
-> 生成日报
-> 发布/导出
-> 邀请用户
```

### 5.2 采编成员日常工作

```text
登录
-> 今日速览看状态
-> 抓取与覆盖确认数据是否进来
-> 候选池/推荐运行看候选质量
-> 日报页采信、编辑、评论
-> 周报页组稿
-> 需求/任务页沉淀后续动作
```

### 5.3 普通浏览用户（viewer 阅读视角 / 游客旅程，2026-07 已实现）

```text
登录或从内部门户进入（工作台角色 viewer）
-> 默认落地 /daily-reports 直接读当天成稿（自动发布策略下发布即可读）
-> 日报 / 周报 / 历史报告库 / 实体大事记 四个阅读分区
-> 根据工作台反馈策略点赞、评分、评论
-> 查看与自己相关的消息、/account 账号页
```

viewer（游客）阅读视角的实现规则：

- **导航数据驱动过滤**：`workspace_sections` 的阅读分区（daily_reports/
  weekly_reports/historical_reports/entity_milestones）min_role=viewer，其余管理
  分区默认 member 起（可被 `section.config_json.min_role` 覆盖）；AppShell 按当前
  工作台有效角色过滤整组导航（super_admin/editor_admin 全局角色视同 owner）。
- **路由守卫**：非全局管理员且当前工作台角色为 viewer 时，默认落地
  `/daily-reports`；访问管理路由（数据源/抓取/候选池/推荐/导出/用户/审计/同步等）
  一律重定向回 `/daily-reports`；`/account`、`/notifications` 保留可达。
- **页面内编审操作整组隐藏**：日报/周报页的生成/发布/重跑/采信/编辑/头条/格式
  管理等操作只对 member+ 渲染；viewer 读成稿走发布时已投影的 rendition 快照
  （`GET` 列表），不触发 member 权限的 regenerate。
- **反馈仍按 `feedback_policy`**：viewer 能否点赞/评分/评论由工作台策略决定，
  不写死。

看护：`router/index.spec.ts`（viewer 重定向）、`AppShell.spec.ts`（导航过滤）、
`DailyReportsPage.spec.ts` / `WeeklyReportsPage.spec.ts`（编审操作隐藏与
viewer 成稿只读回退）。

### 5.4 内网嵌入用户

```text
公司门户登录
-> iframe 打开 InfoWatchtower
-> 网关注入工号/部门
-> 系统映射本地用户
-> 浏览外网同步来的成品
-> 评论/点赞/评分留在内网本地
```

## 6. 页面能力出现规则

前端能力必须由三个条件共同决定：

1. 当前部署形态能力：`GET /api/meta/runtime`。
2. 当前用户全局角色和工作台 membership。
3. 该功能后端模块是否已完成并有契约。

例子：

- `DEPLOY_MODE=intranet`：不显示数据源导入、抓取运行按钮。
- 工作台角色 viewer：只见阅读分区导航，管理路由重定向回日报（§5.3）。
- 没有 notification 后端模块：不显示通知铃铛；当前已由真实未读数 API 恢复。
- 没有 search 后端模块或 `capabilities.search=false`：不显示顶部搜索；当前 v1 已由
  `/api/search`、权限过滤和 AppShell 测试恢复。
- viewer 能否评论：看工作台 `feedback_policy`，不是写死。

## 7. 当前前端设计缺口

| 缺口 | 归属 | 说明 |
|---|---|---|
| Search 深化 | 前端壳/Search | 顶部搜索 v1 已恢复为真实 `/api/search` 结果面板，已覆盖类型分组、键盘选择、本地近期结果、周报条目、导出任务/trace 条目、report rendition 成稿锚点、同步运行/冲突等主要对象锚点；仍缺 E2E 证据 |
| Notifications 目标态未完整 | 前端壳/Notifications | 顶部铃铛和 `/notifications` 已接真实未读/已读/归档 API；日报评论、日报评论 @ 提及、日报/周报条目关注入口、同步冲突通知、日报/周报发布通知、周报条目更新通知、任务指派通知、需求状态通知、后端 target_path、日报条目级跳转、评论高亮、报告级跳转、周报 item 锚点、同步冲突锚点、任务锚点、需求锚点和站内通知偏好已接入，仍缺邮件投递和更多对象通知生成/提及 |
| 登录页真实 provider 体验未验收 | 登录页 | auth mode 入口、redirect query 和 OIDC provider/callback 错误文案已覆盖；仍需真实 provider 登录/建号/membership/登出体验证据 |
| `/users` 权限策略深化 | 用户权限页 | 用户、邀请、成员、策略入口、自动开通规则展示、当前工作台部门 membership 映射编辑、权限审计摘要、成员角色影响提示、owner 危险变更确认、最后 owner 前后端守护、viewer 反馈策略编辑、权限变更 diff 解释和批量回滚已补；仍缺真实 provider/内网门户验收 |
| “我的消息”深化 | 通知 UX | 页面已可列表/已读/全部已读/归档，按后端 `target_path` 打开日报条目、高亮命中评论、打开日报/周报报告、定位周报条目更新、定位同步冲突、定位被指派任务和定位需求，并能设置站内偏好；后续补更多对象通知生成/提及 |
| 布局模板与间距收敛未实施 | 全站布局 | §9 已定稿：spacing tokens、页面容器、四模板、Dashboard 重排；实现待落 `base.css` token 层与逐页迁移 |
| 统一弹窗系统未实施 | 全站弹窗 | §10 已定稿：居中 Modal 规范、尺寸档位、迁移清单、上下文面板判定规则；实现待迁移 5 处 config-panel 弹层 |
| 账号资料编辑未实施 | 账号页 | §11 已定稿：本地账号 `PATCH /api/auth/me` 改 display_name/department/email，外部身份只读 |
| 发现搜索与加入码未实施 | 工作台发现 | §12 已定稿：discover 搜索、workspace join_code、公开形态矩阵；后端契约见 `config/contracts/workspace_model.json` |

逐页缺口、当前标记和测试优先级以 `docs/product/page-specs/frontend-page-specs.md` 为准。

## 8. 前端验收规则

- 页面上不能存在点击无效果的控件。
- 页面入口必须能解释业务任务。
- 空态必须告诉用户下一步。
- 按部署形态禁用的能力必须隐藏或解释原因。
- 新增页面必须能说明后端模块、API 契约和测试。
- 新增页面必须在 `docs/product/page-specs/frontend-page-specs.md` 声明布局模板归属（§9.3），
  间距只允许引用 §9.1 spacing tokens。
- 新增弹窗必须使用 §10 的居中 Modal 规范或满足上下文面板判定规则，不得再新建第三种弹层形态。
- 假控件、假成功和 0 结果语义的回归要求见 `docs/backend/contract-test-governance-design.md`。

## 9. 布局模板与间距系统（强约束，2026-07 定稿）

针对用户反馈「每页依然有页边距的问题」「模块也都是飘的四处都是」的顶层修正：
全站布局收敛为一套 spacing tokens + 一个页面容器 + 四个布局模板。任何业务页面
不得再自由摆放模块或自定间距。本节是强约束：与本节冲突的存量 CSS 属于技术债，
迁移期逐页收敛；新增页面立即适用。

### 9.1 spacing tokens（固定档位）

Token 统一定义在 `frontend/src/styles/base.css` 的 `:root`；业务 CSS 只允许引用
token，新增样式不允许再出现魔法数字间距：

| Token | 值 | 用途 |
|---|---|---|
| `--space-page-x` | 28px（≤860px 窄屏降为 16px） | 页面容器左右内边距（页面外边距的唯一来源） |
| `--space-page-y` | 24px | 页面容器上下内边距 |
| `--space-section` | 32px | 页内分区之间的垂直间距 |
| `--space-card` | 20px | 同一分区内卡片之间的间距（grid/flex gap） |
| `--space-card-pad` | 20px（compact 卡 16px） | 卡片内边距 |
| `--space-inline` | 12px | 卡片内元素之间的间距 |
| `--space-control` | 8px | 控件内部间距（图标与文字、徽章内） |

规则：

- 页面左右留白只由页面容器提供；页面根元素和卡片不得再叠加自己的外层 margin。
- 卡片间距只用容器 gap（`--space-card`），禁止用 margin 逐卡手调。
- 分区间距固定为 `--space-section`，不因页面不同而变化。

### 9.2 页面容器规范

- 所有 AppShell 内业务页面共用同一页面容器：`max-width: 1200px`（与现有 1200px
  口径一致，不引入第二种宽度）、水平居中、内边距
  `var(--space-page-y) var(--space-page-x)`。
- 页面内容网格只允许两种列结构：
  - **单列**：`minmax(0, 1fr)`。
  - **主列 + 固定侧栏**：`minmax(0, 1fr) 340px`，gap `--space-card`；≤1120px 时
    侧栏移到主列下方单列堆叠，顺序保持「主列在前、侧栏在后」。
- 禁止模块自由漂浮：业务模块必须落位在声明的网格列内，按声明顺序排布；
  `position: fixed/absolute` 只允许全局壳（侧边栏/顶栏）、弹窗层（§10）和
  上下文面板（§10.2）使用，业务卡片一律不允许。

### 9.3 四个布局模板

每个页面必须在 `docs/product/page-specs/frontend-page-specs.md` §3 声明所属模板；
没有模板标注的新页面不得合入。

| 模板 | 结构（自上而下） | 列结构 | 适用示例 |
|---|---|---|---|
| `list` 列表页 | 页头（标题 + 主操作）→ 工具条（筛选/统计，单行卡）→ 主列列表 | 单列；唯一允许的固定侧栏例外是 `/sources` 的标签策略面板（AGENTS 保护线） | 候选池、抓取与覆盖、日报/周报列表、导出、同步、审计 |
| `detail` 详情页 | 页头（返回 + 标题 + 状态徽章）→ 详情主体 | 主列（正文/明细）+ 固定侧栏（元数据/追溯/操作） | 源详情、日报详情/编辑 |
| `dashboard` 仪表盘 | 页头结论行 → 内容区 | 主列 + 固定侧栏（§9.4） | 今日速览 |
| `settings` 设置页 | 垂直分组设置卡（每卡一个主题 + 该卡的保存动作） | 单列窄容器（内容 max-width 860px，居中） | 工作台配置、账号、用户权限 |

登录 `/login`、首次设置 `/setup`、邀请接受 `/invite/:code` 在 AppShell 之外，
沿用现有居中窄卡授权布局，不占用四模板。

### 9.4 今日速览信息架构重排（线框级）

针对「今日速览模块太分散了」：`/dashboard` 固定为 dashboard 模板，
分区顺序与归属如下，不允许模块在两列之间随意漂移。

```text
┌ 页头结论行（全宽，单行卡）─────────────────────────────┐
│ 日期 · 系统健康点 · 「今日日报：已发布/草稿/未生成」CTA   │
└──────────────────────────────────────────────────────┘
┌ 主列 minmax(0,1fr) ────────────────┐ ┌ 固定侧栏 340px ─┐
│ ① 今日头条候选（Top 6，第一屏主体） │ │ ① 流水线漏斗    │
│    准入徽章/推荐分/多源数/点击去候选池│ │   （竖排紧凑）  │
│ ② 最新日报卡（状态/采信数/进入编审） │ │ ② 快捷入口      │
│                                    │ │ ③ 最新周报卡    │
│                                    │ │ ④ 近七日采信趋势 │
│                                    │ │ ⑤ 源健康        │
│                                    │ │ ⑥ 调度心跳      │
└────────────────────────────────────┘ └────────────────┘
```

规则：

- 主列只放「今天要处理的内容」：头条候选和最新日报卡；其余全部收进固定侧栏。
- 现有全宽漏斗 hero 改为侧栏第 1 位的竖排紧凑漏斗（阶段名 + 数值一行一级），
  页头只保留一行结论（日期 + 健康点 + 日报状态 CTA）。
- 源健康默认折叠：无失败源且无待补入口时收为一行「源健康正常」；有异常时展开
  失败 Top3 + 待补入口提醒。
- 调度心跳卡固定为侧栏第 6 位（与自动化轨道 §8.5 同批实现）：读
  `GET /api/pipeline/scheduler/status` 展示 scheduler 在线/离线、下次运行时间与
  最近 run 结果；后端能力落地前不渲染该卡，不做假数据占位。
- ≤1120px 单列堆叠顺序：页头结论行 → 头条候选 → 最新日报卡 → 侧栏各卡按序。
- 页面保持只读，数据来源与现实现一致（coverage/dedupe/daily/weekly API），
  重排不引入新后端能力。

### 9.5 验收标准

- 任意两个业务页面的页面左右留白、分区间距、卡片间距一致，值等于 §9.1 token。
- `docs/product/page-specs/frontend-page-specs.md` §3 逐页总表有完整模板标注列。
- `/dashboard` 按 §9.4 分区渲染：主列只有头条候选与最新日报卡；漏斗/快捷入口/
  周报/趋势/源健康（及实现后的调度心跳卡）全部在固定侧栏；无异常时源健康折叠
  为单行（组件测试看护）。
- 业务卡片无 `position: fixed/absolute`；`base.css` 中同一页面布局属性只有一处
  定义（AGENTS CSS 规则）。
- 窄屏（≤1120px/≤860px）断点行为与 §9.2 一致。

## 10. 统一弹窗系统（强约束，2026-07 定稿）

针对用户反馈「新建工作台、发现工作台的弹窗都放在中间吧，我希望所有的类似弹窗都
在中间」：全站只允许两种弹层形态——**居中模态 Modal**（默认）和**右侧上下文面板**
（受限保留）。现有右上角浮层 `config-panel` 形态不再新增。
契约扫描面见 `config/contracts/frontend_control_governance.json` 的 `modal_rule`。

### 10.1 居中 Modal 规范

- 结构：`.modal-backdrop`（`position: fixed; inset: 0`，遮罩
  `rgba(15,23,42,0.36)`，`display: grid; place-items: center`，z-index 40）
  + `.modal` 容器（`role="dialog" aria-modal="true" aria-labelledby`）。
  与现有 `report-modal-backdrop/report-detail-modal` 同构，本节将其正式化为
  全站唯一 Modal 基座；表面材质在 `base.css` Liquid Glass 主题层统一覆盖。
- 尺寸档位（宽度上限，实际 `min(档位, calc(100vw - 48px))`）：
  - `sm` 480px：确认类、单字段表单（凭码加入、危险操作确认、导入预览确认）。
  - `md` 720px：多字段表单和向导（新建工作台向导、发现工作台、新增信息源）。
  - `lg` 1120px：富内容详情（日报条目详情、任务详情，即现 report-detail-modal）。
  - 高度统一 `max-height: calc(100vh - 56px)`，超出部分容器内滚动。
- 遮罩与关闭：点击遮罩关闭、Esc 关闭、右上角显式关闭按钮三者必须同时可用；
  当 Modal 含表单且已有未保存输入（脏状态）时，遮罩点击与 Esc 必须先弹 `sm`
  确认（「放弃未保存的修改？」），不允许静默丢输入。
- 焦点管理：打开时焦点移入 Modal（标题或第一个可聚焦元素），Tab 焦点圈定在
  Modal 内（focus trap），关闭后焦点归还触发控件；打开期间锁定 body 滚动。
- 移动端（≤640px）：sm/md/lg 一律全屏化（inset 0、圆角 0、顶部标题栏带关闭
  按钮），内容区滚动。
- 层叠：业务 Modal 最多叠一层确认 Modal（sm）；不允许 Modal 内再开业务 Modal。

### 10.2 上下文面板（config-panel 处置决策）

右侧滑出面板不废除，但收敛为「上下文面板」并且只有一种合法场景。

判定规则（同时满足才允许用上下文面板，否则一律居中 Modal）：

1. 操作对象是**页面列表中当前选中的一项**（编辑上下文）；
2. 用户需要**同时看到背后列表**以便对照或连续切换选中项；
3. 提交是**可反复保存的配置编辑**，不是创建新对象、不是不可逆决策。

处置结论：创建类（新建工作台、新增信息源）、决策确认类（导入预览）、
浏览加入类（发现工作台）都不满足条件 1/3，迁居中 Modal；
单源配置、成稿格式管理满足三条，保留为上下文面板。

### 10.3 现有弹层迁移清单

| 现有弹层 | 现形态 | 处置 | 目标档位 |
|---|---|---|---|
| 新建工作台向导（`AppShell.vue` config-panel） | 右上浮层 | 迁居中 Modal（三步向导） | md |
| 发现工作台（`WorkspaceDiscovery.vue` config-panel） | 右侧抽屉 | 迁居中 Modal（含搜索框 + 凭码加入区，§12.2） | md |
| 新增信息源（`SourcesPage.vue` create panel） | 右上浮层 | 迁居中 Modal | md |
| 数据源导入预览（`SourcesPage.vue` import-preview-panel） | 右上浮层 | 迁居中 Modal（确认类） | sm |
| 单源配置（`SourcesPage.vue` config-panel，选中源） | 右上浮层 | 保留，正式化为上下文面板（§10.2） | — |
| 成稿格式管理（`DailyReportsPage.vue` format-panel） | 右上浮层 | 保留，正式化为上下文面板 | — |
| 日报条目详情（`DailyReportsPage.vue` report-detail-modal） | 已居中 | 保持，归入 Modal lg 档 | lg |
| 任务详情（`TopicTasksPage.vue` task-detail-modal） | 已居中 | 保持，归入 Modal lg 档 | lg |

页面内联确认（owner 危险变更勾选、批量回滚确认等）v1 保留内联形态；
后续新增的确认交互一律用 Modal sm，不再新增内联确认样式。

### 10.4 验收标准

- 新建工作台向导与发现工作台以居中 Modal 渲染（组件测试断言 `role="dialog"`、
  `aria-modal="true"` 与居中基座 class），不再使用右上浮层定位。
- 每个 Modal：Esc 关闭、遮罩点击关闭、关闭后焦点归还触发按钮均有测试看护；
  脏表单遮罩/Esc 触发确认而非直接关闭。
- ≤640px 视口 Modal 全屏化。
- 迁移完成后，`config-panel` class 只出现在 §10.2 判定通过的上下文面板
  （单源配置、成稿格式管理，均带 `context-panel` 正式化标记类）；
  `scripts/validate_frontend_controls.py` 已按 `modal_rule` 扩展扫描
  （2026-07 实施：扫描面 layouts/pages/components，config-panel 白名单 + 标记类、
  modal-backdrop 组件必须带 `role="dialog" aria-modal="true"`）。

## 11. 账号资料编辑边界（2026-07 定稿）

针对用户反馈「账号没有修改姓名等的地方」。产品边界如下，后端事实源见
`docs/backend/identity-access-design.md` §4.4，契约见
`config/contracts/auth_modes.json` 的 `profile_self_service`：

- 本地账号（`external_provider=local`）可在 `/account` 的「资料」卡片自助编辑
  `display_name`（姓名）、`department`（部门）、`email`（邮箱），调用
  `PATCH /api/auth/me`；`username` 是登录标识，不可改；角色与权限不经此入口变更。
- 外部身份（OIDC / intranet_header）资料卡片只读，显示「资料由外部身份系统管理，
  登录时自动同步」；不展示必然失败的编辑表单（与改密边界同一语义）。
- 游客会话不显示资料卡片（中央 guest 门拒绝一切写操作）。
- 保存成功后前端刷新 session store，顶部用户胶囊与评论署名同步显示新姓名。
- 页面规格见 `docs/product/page-specs/frontend-page-specs.md` §25。

## 12. 工作台发现、加入码与公开形态矩阵（2026-07 定稿）

针对用户三问：「我这个情报工作台怎么搜索，是有个码吗」「部署服务以后，有没有可以
公开的一个平台？」「不公开的、只能团队看的，有没有管理员邀请平替啊？」。
后端事实源见 `docs/backend/workspace-configuration-design.md` §14，契约见
`config/contracts/workspace_model.json` 的 `discovery_and_subscription` 与
`join_code`。

### 12.1 发现面板搜索

- 发现工作台 Modal 顶部提供搜索框，按名称/描述过滤
  （`GET /api/workspaces/discover?q=<keyword>`，仍只返回 `internal_public`）。
- 输入去抖后请求；空结果显示「没有匹配的公开工作台，若你有工作台加入码可在下方
  凭码加入」。

### 12.2 工作台加入码（管理员邀请的轻量平替）

- 每个工作台可由 admin/owner 生成**一个**当前有效加入码：8 位大写字母+数字
  （去除易混字符），可设默认角色（viewer|member）、有效期和使用次数上限；
  可轮换（生成新码即刻作废旧码）与停用。
- 已登录用户在发现面板「凭码加入」输入码即成为该工作台成员（含 private 工作台，
  这就是「不公开、只能团队看」的自助入口）；已是成员则幂等不降级。
- 与全局邀请码（`user_invites`）互补：邀请码面向**未注册的具体个人**（绑定全局
  角色 + 建号），加入码面向**已注册用户的团队自助入台**（只授 viewer/member）；
  加入码不建号、不改全局角色。
- 管理入口在 `/workspace-settings` 新增「可见性与加入码」设置卡（§19.5 规格见
  page-specs）；凭码加入入口在发现工作台 Modal。

### 12.3 公开形态矩阵：谁能看到什么

| 工作台形态 × 部署开关 | 未登录访客 | 游客会话（`AUTH_GUEST_ENABLED=true`，仅 standalone/cloud） | 登录非成员 | 工作台成员 |
|---|---|---|---|---|
| `private`（默认） | 不可见 | 不可见（不出现在任何列表，直访 404） | 发现列表不可见、直访 404；**凭加入码可入** | 按 workspace role 正常使用 |
| `internal_public` | 不可见（必须先登录或走游客入口） | 只读已发布内容（隐式 viewer，一切写操作 403 并提示注册） | 发现列表可见，可自助订阅为 viewer；凭加入码可按码的默认角色加入 | 按 workspace role 正常使用 |
| `AUTH_GUEST_ENABLED=false`（默认） | 只见登录页 | 无游客入口 | 同上两行 | 同上两行 |

对用户三问的直接回答：

- **可以公开的平台**：`internal_public` 工作台 + `AUTH_GUEST_ENABLED=true` =
  站内公开 + 游客免注册只读。系统不提供完全匿名的互联网公开写入；公开的上限是
  「游客只读」。
- **不公开、只能团队看**：`private` 工作台；团队进入方式按优先级为
  ① 工作台加入码（已注册用户自助）② 管理员邀请码（未注册个人）
  ③ 成员管理直加 / 用户组批量入台。
- **搜索**：发现面板搜索只覆盖 `internal_public` 工作台；private 工作台不可被
  搜索，只能凭码或被管理员加入（不泄露存在性）。

### 12.4 验收标准

- `GET /api/workspaces/discover?q=` 只按名称/描述过滤 `internal_public`，
  private 工作台任何关键词都不出现。
- admin 生成加入码后，另一登录用户凭码加入 private 工作台成功并获得码上默认
  角色；轮换后旧码立即失效（统一失效文案，不泄露原因细节）；停用后不可加入。
- 已是成员的用户凭码加入幂等，不降级已有角色。
- 游客会话凭码加入返回 403 并提示注册。
- 加入码失败按用户+IP 限流，防止枚举爆破。
- 加入、生成、轮换、停用全部写审计（动作清单见 `config/contracts/auth_modes.json`
  `identity_audit_actions`）。
