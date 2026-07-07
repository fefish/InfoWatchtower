# AI 情报官工作台 · 系统全量蓝图

本文是**全量实现规格**：一个具备工程能力的实现者（人或 AI 编码代理）只依据本仓文档，
应能从零实现整套系统，或在现有代码上完成任意模块的重写与扩展。

与其他文档的关系：

- 本文 = 系统级蓝图（产品定义、领域模型、管线、API 面、**每个页面的元素级规格与
  修改指南**、扩展模型、视觉系统）。
- `docs/architecture/capability-map.md` = 现状与差距对照（哪些已实现，避免重做）。
- `docs/architecture/target-state-spec.md` = 账户/部署/扩展加固三个增量工作包的实施细则。
- `config/contracts/*.json` = 字段与流程的机器合同，冲突时以合同为准。

## 1. 产品定义与租户模型

**产品**：AI 情报官工作台（InfoWatchtower）——团队自部署的产业情报操作系统。
交付形态是一个可开箱部署的多租户工作台产品，而不是某个部门的定制系统。

**租户 = 工作台（workspace）**。每个工作台拥有独立的：启用源集合、标签策略、
成稿格式集合、报告流水线产物、成员关系；共享的：全局源池、用户账户、处理管线代码。

**可塑性原则（用户拿到产品后不改代码能做的事）**：

| 用户想要 | 实现途径（全部是数据/配置，非代码） |
|---|---|
| 用自己的信息源 | 界面自建源（POST /api/sources）、启用共享池已有源、批量导入种子 CSV |
| 自己的日报/周报格式 | 格式注册表（report_formats）：分组维度/字段/头条区/导出目标界面可配 |
| 自己的分类口径 | 工作台标签策略（label-policy API）：一级/二级标签、新闻结构字段 |
| 自己的板块体系 | taxonomy 配置文件 + domain pack（无主链路代码改动） |
| 自己的调度节奏 | env：调度时间/时区/日偏移/单源上限 |
| 新的工作范围 | 界面新建工作台，自动配齐上述全部默认值 |

**首个租户 `planning_intel`（规划部）只是一组预置配置**：十分类标签集、
company_sql_v1 锁定格式、公司 SQL 导出合同。任何页面、服务、文案都不得把
"规划部/Tech Insight Loop"写成产品级假设；旧系统资产导入是历史报告库的
**一种导入器**，不是页面的定义。

## 2. 领域模型（表族与职责）

详细字段见 `config/contracts/*.json` 与 `docs/backend/data-lineage-and-storage.md`。
按能力族分组（表名 = SQLAlchemy `backend/app/models/` 中的定义）：

```text
身份：users / roles / permissions / user_roles / role_permissions / audit_logs
     （目标态补 user_invites / password_reset_tokens / login_attempts，见 target-state-spec §3）
租户：workspaces（config_json.label_policy）/ workspace_sections（config_json.group）
     / workspace_memberships / workspace_source_links
源与采集：data_sources（共享池，metadata_json 治理字段）/ ingestion_runs
内容主链：raw_items（raw_payload_json 不可覆盖）→ news_items → dedupe_groups/items
推荐：recommendation_runs / recommendation_items（admission_* 结构化准入）
生成：generated_news（content_json 五段 + insight_json 板块/要点/总结/标签行）
报告：daily_reports/items（adoption_status、is_headline）/ weekly_reports/items
成稿：report_formats（builtin+locked 语义）/ report_renditions（投影快照）
导出：export_jobs/items；同步：sync_outbox/inbox/runs
归档：historical_reports / tracked_entities / entity_milestones
     / historical_feedback_items / historical_job_runs
战略：insights / requirements / topic_tasks
```

关系铁律：`ScopeMixin`（workspace_code/domain_code/visibility_scope/sync_policy）
贯穿内容表族；`SyncMixin`（global_id/revision）支撑多环境同步；全部主键 uuid 字符串。

## 3. 处理管线（输入/输出/幂等/失败语义）

| 段 | 入口 | 输入→输出 | 幂等键 | 失败语义 |
|---|---|---|---|---|
| 抓取 | `POST /api/ingestion/runs`；scheduler | 启用源→raw_items | (data_source_id, entry_key) | 单源失败记录 last_error，不阻塞其他源；run 状态 partial |
| 补采 | `POST /api/ingestion/backfill-runs` | 模式化历史恢复→raw | 同上 | 同上，窗口外条目计数不入库 |
| 标准化 | `POST /api/news-items/normalize`；管线内 | raw→news（canonical url、dedupe key） | news 由 raw 一对一派生 | 失败落 normalization_notes |
| 去重 | 标准化尾部 | news→dedupe_groups，winner/loser 回写 | workspace_code+dedupe_key | 重建幂等 |
| 推荐 | `POST /api/recommendation/runs`；管线 | 目标日 winner→评分/准入→选中 | run 内排序 | 评分器异常=该条 R 级+原因 |
| 生成 | 推荐尾部 | 选中项→generated_news（模型或 rule_v1 兜底） | recommendation_item 一对一 | 超时/失败→fallback_needs_review，可重跑 |
| 日报 | 管线尾部/手动 | 选中项→daily_report(+items, 采信=2) | (workspace,domain,day_key) 唯一 | 已发布日不可重跑（409） |
| 成稿 | 打开/导出/重生成时 | 采信项→rendition 投影 | (report_type,report_id,format_code) | 可随时重建，不回写上游 |
| 周报 | `POST /api/weekly-reports` | 周内日报采信项→周报候选 | (workspace,domain,week_key) | include_unpublished_daily 可选 |
| SQL 导出 | `POST /api/exports/...` | 已发布日报采信 ready 项→4 表 SQL | export_job | 必须过 validate_company_sql.py |

一条完整日更 = 抓取→标准化→去重→推荐→生成→日报草稿（`POST /api/pipeline/daily-runs`
一次触发；scheduler 每日定时执行同逻辑）。

## 4. API 面

全部端点清单与语义见 `docs/implementation/api-and-ui-implementation.md` §2（保持为唯一 API 目录）。
分组速览：auth（+目标态 invites/password/setup）、workspaces（列表/创建/分区/标签策略）、
sources（列表/自建/编辑/工作台链接/导入/抓取）、ingestion（runs/backfill/coverage）、
news（normalize/list/dedupe-groups）、recommendation、reports（daily/weekly CRUD+publish+
条目采信编辑）、report-formats + renditions（regenerate/export）、exports（SQL+trace）、
sync、历史归档族（historical-reports/entities/quality/legacy-import）、
requirements/topic-tasks、users/roles/audit。

通用约定：登录 cookie 会话；写操作 super_admin（目标态细化到 membership 角色，
规则见 target-state-spec §3.5）；列表接口支持 workspace_code 过滤；错误返回
`{"detail": string}`；管理操作写 audit_logs。

## 5. 页面规格（元素级）

通用约定（适用所有页面，修改 UI 前必读）：

- **文件位置**：页面 `frontend/src/pages/*.vue`（script setup + template，无 scoped
  style）；全部样式在 `frontend/src/styles/base.css`；API 客户端 `frontend/src/api/*.ts`；
  跨页状态只有 `stores/session.ts` 与 `stores/workspace.ts`。
- **修改样式的规则**：改颜色/圆角/阴影/玻璃参数 → 改 `:root` token；改某类表面
  （卡片/按钮/输入）→ 改文件末尾「Liquid Glass 主题层」对应选择器；改单页布局 →
  改该页面的布局区块（每个布局只允许一处定义）。禁止新增第二处同选择器覆盖。
- **工作台响应**：每个页面必须 `watch(workspace.currentCode)` 重载数据；
  空态必须解释"这是什么+下一步动作"，不允许裸"暂无"。
- **文案**：不得出现租户专属词（规划部/Tech Insight Loop）作为能力定义；
  租户词只允许出现在数据本身（如工作台名称、导入器说明）。

### 5.1 今日速览 `/dashboard`（DashboardPage.vue）

使命：10 秒回答"今天跑得怎么样/有什么等我处理/最近产出了什么"。只读。

| 区块 | 元素 | 数据 |
|---|---|---|
| briefing-hero | 日期行、标题、健康胶囊（`.briefing-health`）、流水线漏斗（6 个 `.funnel-stage`：启用源/抓取成功/今日新增/去重代表/入选推荐/已采信 + 可点击的日报状态胶囊 `.funnel-result`） | `GET /api/ingestion/coverage?day_key=今天` |
| briefing-headlines | 头条候选 Top6：排名（`.headline-rank`，前 3 高亮）、两行截断标题、准入徽章（`.admission-tag` data-tone=p0/p1/p2）、推荐分、来源；空态给"先跑一次抓取 →" | `GET /api/dedupe-groups`（过滤 P0-P2、当日优先、final_score 降序） |
| briefing-side | 最新日报卡（day_key、状态徽章、采信数、分类分布 chips、"阅读日报"CTA）、最新周报卡、近七日采信趋势条（`.trend-bar`，已发布高亮） | reports API |
| briefing-foot | 源健康（失败源 Top3 + 待补入口黄条链接数据源页）、快捷入口三磁贴（抓取与覆盖/新增信息源/SQL 导出） | sources API |

修改指南：新增指标卡→在 `.briefing-side` 加 `article.briefing-report-card`；调漏斗
阶段→改 `funnelStages` computed；样式 token 见 `.briefing-*` 区块（base.css 搜
"晨报式首页"）。

### 5.2 数据源管理 `/sources`（SourcesPage.vue）

使命：共享源池治理 + 当前工作台的源启用配置 + 工作台标签策略。唯一"改源"的地方。

| 区块 | 元素 |
|---|---|
| source-stats-card | 总数/启用数/类型分布 pills；动作：新增源、刷新、导入种子、导入治理源 |
| source-feed（左） | 每源一行：类型图标、名称、URL、启停徽章、meta 行（类型/源等级/渠道/质量分/待补入口/domain/方向标签/最近成功/专家路由/错误）；行动作：配置、抓取 |
| control-rail（右） | 标签策略面板：一级/二级/新闻结构三个 tab、默认与兜底标签、保存/恢复默认 |
| config-panel（滑出） | 上：工作台链接配置（启用开关/权重/日限）；下：源定义编辑（名称/回溯天数/URL 补入口） |
| create-panel（滑出） | 自建源表单：名称/类型/主题域/回溯/URL；说明"同 URL 自动复用共享池" |

修改指南：加治理字段展示→`_source_to_read`（后端）+ `DataSourceRecord`（api/sources.ts）
+ meta 行 chip；策略面板结构受 AGENTS.md 保护（保留 tab 化右栏）。

### 5.3 抓取与覆盖 `/ingestion-runs`（IngestionRunsPage.vue）

使命：运行抓取/补采、解释覆盖链路。唯一"跑抓取"的地方。

| 区块 | 元素 |
|---|---|
| module-hero | 标题、说明、刷新 + 运行按钮（随 tab 切换文案） |
| ingestion-command | 常规/补采两个 tab；常规：源类型**胶囊多选**（`.type-toggle-group`，至少保留一个选中）、源数量上限；补采：日期区间、补采模式下拉、源类型胶囊、上限、无日期开关；说明行 muted-line |
| coverage-overview | 目标日漏斗（8 格 stage + run/窗口/推荐/日报状态 pills）、日期选择 |
| run-list（左） | 运行历史 tab 列表（run_key、类型、状态、时间） |
| run-detail（右） | run 概览（fetched/raw±）、每源行：图标、名称、状态徽章、九项计数 pills、错误行（红条，长错误截断） |

修改指南：新增抓取参数→schemas/ingestion.py + api/ingestion.ts + command 区加
`.run-field`；错误展示要折叠优先（红条一行，title 提示全文）。

### 5.4 候选池 `/news`（NewsPage.vue）

使命：阅读去重后的候选代表项，理解"为什么是它/它到哪一步了"。采信入口在日报页。

元素：统计行（组数/活跃 winner）、候选卡列表（meta 行：来源数/类型/日期/推荐状态/
日报状态；标题+摘要；右侧评分区 `.candidate-judge`——推荐分(0-100)或"待推荐评分"，
**禁止把内部 rank_score 当分数展示**（只在重复来源明细里标"去重权重"）；展开区：
分数拆解格、准入等级/噪声/拒绝原因、重复来源云、追溯 ID 链）。

### 5.5 日报 `/daily-reports`（DailyReportsPage.vue）

使命：**打开即成品**（默认技术洞察版），编审是其中一个视图。

| 区块 | 元素 |
|---|---|
| report-command | 标题、日期选择、刷新、生成日报草稿 |
| report-timeline（左） | 日期列表（day_key、状态、条数） |
| daily-report-card（右） | 标题行（标题+重跑生成稿+发布）、指标行（入稿/采信/评分）、**成稿切换条 `.rendition-bar`**（格式 tab：技术洞察版默认、内网版·编审、自定义…；右侧导出 MD/HTML/格式按钮） |
| 成品视图 `.rendition-view` | 头条区（蓝左边框卡，序号列表）、板块分组（组标题+条数）、条目（序号标题+头条星标切换 `.headline-toggle`+标签行+📋要点+📌总结+来源行+规则降级徽标）；行长限制 78ch |
| 编审视图 `.daily-item-list` | 现有条目列表：分类徽章、采信/剔除、编辑抽屉（五段字段+关键词）、点赞/评分/评论、详情弹窗含追溯 |
| format-panel（滑出） | 格式列表（名称/code/分组/导出/锁定；启停开关、删除）+ 注册自定义格式表单（标识/名称/分组维度/头条条数/头条开关/字段勾选/导出目标） |

修改指南：成稿条目字段增删→`REPORT_FORMAT_ITEM_FIELDS`（前后端各一处）+ 渲染器
（renditions.py 的 markdown、rendition_html.py、页面模板三处按 fields 条件渲染）；
新增内置格式→`BUILTIN_REPORT_FORMATS`。

### 5.6 周报 `/weekly-reports`（WeeklyReportsPage.vue）

使命：周度组稿：从周内日报采信项聚合候选，按板块采信/排序/发布；同样支持双版成稿
（标题行提供 技术洞察版 MD/HTML 导出链接与发布）。

元素：生成命令行（周次选择+include_unpublished 开关）、周报列表（左）、详情（右：
板块 tab 行可换行、板块卡网格 auto-fill ≥240px、条目行：标题/来源（可断行）/采信
切换/排序/编辑）。空态解释"先发布日报并采信"。

### 5.7 历史报告库 `/historical-reports`（HistoricalReportsPage.vue）

使命：**通用报告资产库**——任何旧系统/历史批次导入的报告长期可查、可追溯。
旧系统导入验收面板是其一个组件（Import QA），不是页面定义。

元素：验收面板（指标格+缺口列表，空缺口给解释）、汇总卡（归档数/类型/未解析引用/
时间范围）、筛选行（类型/状态/日期/关键词/仅未解析）、报告列表+正文查看（右）。
空态必须给"怎么导入"指引（脚本命令）。

### 5.8 实体大事记 `/entity-milestones`

使命：实体（公司/组织/项目）事件时间线。当前来源=旧系统导入；目标态补"从日报采信
项登记事件"（capability map P1）。元素：汇总卡、实体列表（左）、事件时间线（右：
时间/标题/重要度/板块/来源链接/旧引用状态）、详情面板。

### 5.9 质量归档 `/quality-archive`

使命：质量运营档案（历史反馈/质量复核/任务运行统计）。元素：五张汇总卡、四个分布
卡（反馈类型/质量原因/任务类型/任务状态——空态"暂无"必须附一句来源解释）、反馈与
任务筛选列表、引用缺口抽查。

### 5.10 协作与系统组

- `/requirements`、`/tasks`：需求/任务列表+创建+状态流转（战略闭环 v1）。
- `/exports`：选已发布日报→生成/预览/下载 SQL→历史+语句级追溯。
- `/sync`：同步 run 列表、包导出/下载/导入。
- `/users`：用户列表/角色调整；目标态+邀请管理 tab 与成员管理（target-state-spec）。
- `/audit-logs`：审计流水筛选。
- `/login`（玻璃卡居中）；目标态 `/setup`、`/invite/:code`、`/account`。

### 5.11 全局壳（AppShell.vue）

侧边栏（品牌、工作台切换器+新建工作台、六组导航、用户区）、顶栏（单行：工作台名+
描述省略号、窄屏工作台下拉、搜索、通知、用户胶囊）、≤1120px 图标栏模式、
新建工作台滑出面板（目标态升级为三步向导，见 target-state-spec §4.2.1）。

## 6. 扩展模型（用户拿到后的改造点）

### 6.1 自带数据源

1. **界面自建**（零代码）：数据源页「新增源」→ 共享池 + 当前工作台启用。
2. **批量种子**：按 `config/seeds/tech_insight_loop/sources_full_zh.csv` 的列约定
   准备 CSV → 复制一个 import 端点/脚本注册（`app/ingestion/source_seeds.py` 的
   import 函数是模板，幂等按 URL 去重）。
3. **新源类型**：实现 `app/adapters/base.py` 的 `SourceAdapter` Protocol
   （`source_type` + `async fetch(data_source) -> list[RawItemInput]`）→ 注册进
   `create_default_registry()` → `source_fields.json` 增补类型 → 前端类型标签/图标
   两个映射。约束：adapter 只产 RawItemInput，不写库不评分。

### 6.2 自定义报告格式（含周报）

格式对象（report_formats）字段语义：`group_by`（category/board/none）、
`headline_enabled + headline_auto_top_n`、`item_fields`（tag_line/bullet_points/
takeaway/five_fields/summary/source_link/score 的有序子集）、`export_targets`
（md/html）。**每个格式同时作用于日报与周报**。用户路径：日报页「格式」面板注册 →
所有报告立即多出一个成稿 tab 与导出项。代码级定制点：Markdown/HTML 模板段落顺序在
`renditions.py::render_markdown` / `rendition_html.py`，按 fields 驱动，新增字段时
三处同步（见 5.5 修改指南）。locked 的 company_sql_v1 不受注册表编辑影响。

### 6.3 自定义分类/板块/评分

- 一级/二级标签与新闻结构：工作台标签策略（界面配置，存 workspaces.config_json）。
- 业务板块：`config/taxonomy/business_boards.json`（板块列表/顺序/兜底/建议映射）。
- 评分先验与准入：`config/scoring/content_scorer_v2.json`（阈值/权重/噪声规则/专家
  路由）。改配置即生效，不改代码。
- 新主题包：`config/domain_packs/*.json`（目标态样例见 target-state-spec §4.2.4）。

### 6.4 新工作台 checklist（租户开通）

界面新建（自动得到：核心分区+分组导航、默认标签策略、两个内置成稿格式、超管成员）
→ 数据源页启用/自建源 → 标签策略改成自己的口径 → 跑一次流水线 → 需要的话注册
自定义格式 → （目标态）邀请成员并配 membership 角色。

## 7. 视觉系统（Liquid Glass）

Token（base.css `:root`）：主色 `#0A84FF`、文本 `#1d1d1f/#6e6e73`、玻璃
`--glass-bg/--glass-blur/--glass-stroke`、圆角 `--radius-card:18px /
--radius-control:11px`、三级阴影 soft/panel/float。层次：柔光渐变底 → 半透明卡片
（不加 blur）→ 玻璃 chrome（侧栏/顶栏/浮层，真 blur）。组件语言：胶囊按钮与导航、
iOS 开关、彩色语义胶囊（准入/状态）、等宽大数字。修改规则见 §5 通用约定；基线受
`AGENTS.md` 与 `api-and-ui-implementation.md` §3.1 保护。响应式：≥1440 舒适 /
≤1120 图标栏+顶栏工作台下拉 / ≤860 单列。

## 8. 非功能与部署

单机 Docker Compose（pg/redis/api×N workers/worker/scheduler/caddy）；开箱部署、
首次运行向导、备份恢复、env 自检见 `target-state-spec.md` §5。调度：
`INGESTION_SCHEDULER_*` env，生产推荐每日 09:00 Asia/Shanghai、day_offset=-1、
`max_items_per_source=100`。已知技术债：日报管线为同步重计算，多 worker 缓解，
根治方案=线程池/队列化（capability map P1）。安全目标态（限流/邀请制/membership）
见 target-state-spec §3。

## 9. 全量实现的验收

1. `docs/architecture/capability-map.md` §4 差距清单全部关闭或明确豁免。
2. `docs/architecture/target-state-spec.md` §8 端到端走查通过（部署→建号→邀请→建台→自建源→
   流水线→双版成稿导出→SQL 校验→备份）。
3. 本文 §5 每个页面的元素清单与空态要求逐页核对。
4. 后端 pytest 全绿；前端 build 通过；公司 SQL 校验脚本通过。
