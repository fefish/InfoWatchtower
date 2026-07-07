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
| 系统 | 同步、SQL 导出、用户权限、审计 | 管理、导出、同步、审计 |

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
- 六组业务导航。
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
| `/dashboard` 今日速览 | 看今日漏斗、头条候选、最新日报/周报、源健康 | pipeline/reports/sources |
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
| `/users` 用户权限 | 管用户、邀请、工作台成员、权限策略 | identity/access |
| `/audit-logs` 审计 | 查询关键操作 | audit |
| `/login` 登录 | 根据认证模式展示正确入口 | identity/access |
| `/setup` 首次设置 | 创建首个管理员 | identity/setup |
| `/invite/:code` 邀请接受 | 受邀用户建号并进入工作台 | identity/invite |
| `/account` 账号 | 当前用户资料、本地账号改密、外部身份只读说明、会话状态 | identity/account |

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

逐页缺口、当前标记和测试优先级以 `docs/product/page-specs/frontend-page-specs.md` 为准。

## 8. 前端验收规则

- 页面上不能存在点击无效果的控件。
- 页面入口必须能解释业务任务。
- 空态必须告诉用户下一步。
- 按部署形态禁用的能力必须隐藏或解释原因。
- 新增页面必须能说明后端模块、API 契约和测试。
- 假控件、假成功和 0 结果语义的回归要求见 `docs/backend/contract-test-governance-design.md`。
