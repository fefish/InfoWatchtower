# Tech Insight Loop 与 InfoWatchtower 融合方案

> 定位：本文是 Tech Insight Loop 融合过程和旧资产迁移细节附录，不是资料库模块总设计。
> Archive / Knowledge 模块事实源是 `docs/backend/archive-knowledge-design.md`；
> 机器契约是 `config/contracts/tech_insight_loop_legacy_import.json`。
> 如果本文与事实源冲突，先同步修正后再实现。

## 1. 当前输入和结论

当前根目录只发现一个压缩包：

- `tech-insight-loop-clean-20260525-234356.zip`

全目录补充扫描还发现了 `references/private/wiseflow-5x` 下的测试 fixtures 压缩包，以及 `backend/.venv` 依赖包。这些不是系统交付包，不纳入本次融合输入。

相邻目录 `/Users/feiyu/notes/260414 openclaw点单/release/` 下另有 `openclaw-hushangayi-kit.zip`，但该包只有 24K，内容是 OpenClaw 点单/CLI 安装脚本，不在当前仓根目录，也不是技术情报系统本体。`references/参考工具/` 目录结构与 `Tech Insight Loop` 压缩包一致，可视为同一系统的参考副本，不作为第三套系统。

因此本方案基于两个已确认系统：

- 当前主仓：`InfoWatchtower`
- 压缩包系统：`Tech Insight Loop`

如果后续确实还有第二个压缩包，需要先补一次资产盘点，再增补本方案的差异分析。当前不假设不存在的包。

结论：融合不应采用“双后端并行运行”或“直接拷贝覆盖”的方式。`InfoWatchtower` 应作为唯一主系统，继续承担登录、RBAC、工作台、PostgreSQL、调度、日报、周报、SQL 导出、公网/内网同步等主链路。`Tech Insight Loop` 应作为能力和历史资产来源，迁入其信息源治理、内容评分器、质量闭环、实体大事记、报告资产和导出能力。

## 2. 两个系统定位

### InfoWatchtower

当前主仓是可部署的工程化平台：

- 后端：FastAPI、SQLAlchemy、Alembic、PostgreSQL、Redis/RQ、scheduler。
- 前端：Vue 3、TypeScript、Vite、工作台式浅色界面。
- 已有主链路：数据源、抓取、raw/news、去重、推荐、MiniMax 结构化生成、日报、周报、SQL 导出、用户权限、同步和审计。
- 已有关键约束：规划部成品新闻一级分类必须保持当前 10 类，`config/taxonomy/news_categories.json` 是公司 SQL category 的事实源。

### Tech Insight Loop

压缩包系统更像一个高密度洞察原型和历史资产库：

- 后端：单文件 `app.py`，基于 Python 标准库 `http.server` 和 SQLite。
- 前端：`static/` 静态页面。
- 数据：`data/insight_loop.sqlite3`，包含 386 个源、14834 条素材、66 份报告、275 条实体大事记、257 个任务记录。
- 强项：信息源质量治理、内容评分器、P0/P1/P2/P3/R 准入、噪声规则、专家路由、实体大事记、报告导出、GitHub PR、快报 PPT。

## 3. 融合原则

1. 保留 `InfoWatchtower` 作为唯一运行主系统。
2. 不把 `Tech Insight Loop` 的 SQLite 表结构直接复制到主库。
3. 不让两个系统各自产生日报、周报和 SQL，以免口径分裂。
4. 迁移数据必须先进入 `raw_items` 或对应业务表，保留原始 SQLite 行到 `raw_payload_json` 或 `metadata_json`。
5. 压缩包中的 14/17 个业务板块不替换当前成品新闻 10 个一级标签。
6. 压缩包业务板块用于三个位置：数据源标签、评分维度、周报板块。
7. 公司 SQL 合同不改，`created_at`、`content_json` 五段字段和 category 仍按现有校验脚本执行。
8. 先迁移配置和规则，再迁移历史数据，最后迁移高级导出和质量闭环页面。

### 第一轮已完成范围

当前第一轮只完成“源治理 + 推荐评分”融合：

- 已把 `references/参考工具/data/sources_full_zh.csv` 固化为 `config/seeds/tech_insight_loop/sources_full_zh.csv`，并通过 `POST /api/sources/import-tech-insight-loop` 导入。386 行源治理记录全部识别；355 行有 RSS/URL/RSSHub 入口，31 行无入口作为 `metadata_only/needs_entry` 待补入口；按 URL/RSS 去重后形成 363 个共享源。
- 已把 `content_scorer_config.v3-enhanced-no-new-boards.json` 固化为 `config/scoring/content_scorer_v2.json`，后端 `ContentScorer` 输出 `admission_level`、`admission_score`、`admission_pool`、`noise_types`、`reject_reasons`、`scorer_breakdown` 和 `expert_routes`，推荐 API 和前端候选池/推荐运行页/新闻详情页可展示这些字段。
- 未在真实主库执行旧 SQLite 的 14834 条历史素材、66 份历史报告、275 条实体大事记、反馈和旧任务记录导入；未运行 `Tech Insight Loop` 的 `app.py`；未新增周报正文生成；未修改公司 SQL 合同、成品新闻十分类和五段 `content_json`。

### 第二轮已完成范围：阶段 0 只读盘点

当前第二轮已完成“资产冻结和迁移基线”的只读盘点，不写主库：

- 新增 `scripts/tech_insight_loop_inventory.py`，通过 SQLite `mode=ro` 读取 `references/参考工具/data/insight_loop.sqlite3`，输出 `outputs/tech_insight_loop/tech_insight_loop_inventory.json` 和 `outputs/tech_insight_loop/tech_insight_loop_inventory.md`。
- 新增 `config/contracts/tech_insight_loop_legacy_import.json`，固化旧库核心计数、目标映射、只读边界和后续导入禁区。
- 已验证旧库核心数量：386 个源、14834 条素材、66 份报告、23 个实体、275 条实体大事记、4 条反馈、4 条质量反馈和 257 个旧任务记录。
- 已校验日期、URL、JSON 字段和关键关系；`entity_milestones` 到实体/素材/报告的外键关系完整，`reports.source_article_ids_json` 共 2773 个引用，其中 30 个未能解析到旧 `articles.id/article_id`，后续报告导入必须记录为缺口而不是静默丢弃。
- 该阶段只生成盘点和迁移预览，仍不迁移 articles/reports/entity_milestones，不触发推荐，不进入公司 SQL。

### 第三轮已完成范围：历史素材和报告归档脚本

当前第三轮已完成真实归档导入脚本和模型迁移。本地隔离 PostgreSQL 已完成一次全量导入验收，
生产主库执行仍需显式运维动作：

- 新增 `historical_reports` 档案表，用于无损保存旧 `reports` 正文、周期、状态、引用映射和旧行 metadata。
- 新增 `scripts/tech_insight_loop_legacy_import.py`，默认 no-write；只有传入 `--execute` 且配置目标 `DATABASE_URL` 时才写入 InfoWatchtower 主库。
- 旧 `articles` 写入禁用的 `legacy_tech_insight_loop` 档案源和 `raw_items.raw_payload_json.legacy_tech_insight_loop`，用 metadata 标记 `recommendation_eligible=false` 和 `company_sql_eligible=false`，不进入当前推荐和日报。
- 旧 `reports` 写入 `historical_reports`，记录 `source_article_ids_json` 的 resolved/unresolved 映射；30 个未解析引用保留为缺口。
- 真实导入幂等键为 `raw_items(data_source_id, entry_key)` 和 `historical_reports(legacy_system, legacy_table, legacy_id)`。
- 本地隔离 PostgreSQL 全量证据位于 `outputs/tech_insight_loop/postgres_full_import_20260703T050653Z/`：14834 条素材、58 份 importable 报告、23 个实体、275 条大事记、4 条反馈、4 条质量反馈和 257 条旧任务记录覆盖率均为 complete；30 个旧库断链 source_article_ids 已写入 `outputs/tech_insight_loop/tech_insight_loop_import_accepted_gaps.json` 并通过 validator；旧 PDF/二进制文本中的 NUL byte 会转义为 `\u0000` 标记并记录到 `legacy_import.nul_sanitized_fields`。

### 第四轮已完成范围：作业界面融合与工作台自助扩展

当前第四轮把融合能力落到规划部作业界面，并让其他工作台可以自助扩展：

- 规划部作业界面（工作台首页、数据源管理、候选池、推荐、历史归档、实体大事记、质量归档）全部由数据库注册的 `workspace_sections` 驱动，工作台首页随工作台切换刷新，不再固定读 `planning_intel`。
- 新增 `POST /api/workspaces`（super_admin）：界面上直接创建新工作台，自动注册全部核心页面分区、默认标签策略和超管 owner 成员；启动 seed 只维护内置 `planning_intel/ai_tools`，不会停用或覆盖自建工作台。侧边栏工作台切换器下方提供“新建工作台”入口。
- 新增 `POST /api/sources`（super_admin）：任何工作台可在数据源管理页自建信息源（rss/paper_rss/page_manual/page_monitor），源进入共享池并自动在发起工作台启用；同 URL 源复用共享池已有定义，不产生重复源。
- 新增 `PATCH /api/sources/{source_id}`：编辑源名称/URL/启用/回溯天数；给 Tech Insight Loop 的 31 个 `metadata_only/needs_entry` 待补入口源补 URL 后自动清除待补标记（`fetch_entry_status=manual_entry_added`），即可进入抓取。
- 契约同步：`config/contracts/workspace_model.json` 新增 `workspace_creation`，`config/contracts/source_fields.json` 新增 `custom_source_api`。
- 不变的边界：新工作台仍复用同一条主链路（抓取、raw、news、去重、推荐、日报、周报、导出），不复制源定义，不改公司 SQL 合同，不动成品新闻十分类。

## 4. 能力融合目标架构

```text
InfoWatchtower
  登录/RBAC/工作台/同步/部署
  数据源池 + workspace_source_links
  adapter 抓取
  raw_items -> news_items -> dedupe_groups
  推荐/准入/评分
  generated_news
  historical_reports
  company SQL export
        ^
        |
Tech Insight Loop 迁入资产
  sources_full_zh.csv / sources 表
  content_scorer_config
  business_board_rules
  articles 历史素材
  reports 历史报告归档
  ai_entities / entity_milestones
  source health / feedback / jobs
```

## 5. 数据映射方案

| Tech Insight Loop | 当前数量 | 迁入目标 | 处理规则 |
|---|---:|---|---|
| `sources` / `sources_full_zh.csv` | 386 | `data_sources` + `workspace_source_links` | 按 URL、RSS、公众号账号去重。`source_tier`、渠道类型、专家路由、板块相关性进入 `metadata_json`，综合分写 `source_score`。 |
| `articles` | 14834 | `raw_items`，后续可选历史 `news_items/generated_news` 草稿 | 每条素材先生成一条 `raw_item`，完整原行保存到 `raw_payload_json.legacy_tech_insight_loop`。已有模型标题、摘要、效果总结可在后续批次转为历史草稿，但默认不进入推荐、日报或 SQL。 |
| `reports` | 66 | `historical_reports`，后续可选日报/周报视图 | 本批先无损归档 daily/weekly 报告正文和引用映射；旧库存在同一天/同周多份报告，不能直接挤进当前一日/一周一份的 `daily_reports/weekly_reports` 唯一键。 |
| `business_board_rules` | 17 | `config/domain_packs` 或新评分配置 | 启用板块作为周报板块和评分维度。禁用的聚合板块保留为别名，不进入 SQL category。 |
| `content_scorer_config` | 1 | `config/scoring` + 后端评分服务 | 作为 v2 评分规则包迁入，保留阈值、权重、source channel score、source tier score、噪声规则和专家路由。 |
| `ai_entities` | 23 | 新实体表或 `insights` 扩展 | 建议新增 `tracked_entities`，避免把实体影响分塞进通用 insight。 |
| `entity_milestones` | 275 | 新 `entity_milestones` 模块 | 保留事件标题、时间、实体、来源、影响、重要等级和去重 key。 |
| `feedback` / `article_quality_feedback` | 8 | `historical_feedback_items` | 作为历史反馈归档导入，尽量解析到历史 raw；不反向污染当前 `comments/ratings` 和用户权限。 |
| `jobs` | 257 | `historical_job_runs` | 只迁移统计摘要、消息、details 和失败原因，不创建当前 `ingestion_runs`，不迁移旧任务执行状态机。 |

## 6. 分类和板块口径

当前系统必须继续保持两套口径：

- 成品新闻一级分类：当前 10 类，用于日报、公司 SQL 和内网展示。
- 洞察业务板块：Tech Insight Loop 的 14/17 个板块，用于源治理、周报组织、评分、覆盖率分析和专家路由。

映射建议：

| 洞察业务板块 | 成品新闻 category 建议 |
|---|---|
| AI模型 | 模型 |
| 模型训练 | 训练技术 |
| 模型评测 | 测评技术 |
| 智能体平台、协议与执行系统 | 智能体 |
| AI推理与服务加速 | 推理加速 |
| AI应用与产品化场景 | AI 应用 |
| AI安全、可信与治理 | 测评技术 或 基础竞争力 |
| 云与AI基础设施 | AI Infra |
| AI与通算硬件 | AI Infra 或 基础竞争力 |
| 核心网与通信系统架构 | 基础竞争力 |
| 标准、协议与产业联盟 | 基础竞争力 |
| 通信设备供应商 | 大厂动态 或 基础竞争力 |
| 通信服务提供商 | 大厂动态 或 基础竞争力 |
| 基础竞争力 | 基础竞争力 |

实际生成时仍由 `generated_news.category` 落到 10 类，业务板块只作为辅助字段，不能直接写入公司 SQL category。

## 7. 分阶段实施计划

### 阶段 0：资产冻结和迁移基线

目标：先把压缩包资产变成可重复导入的输入。

交付：

- 新增 `references/tech-insight-loop-20260525/README.md`，记录压缩包来源、文件 hash、表统计。
- 新增只读导入脚本雏形：读取 SQLite 和 CSV，输出 mapping preview，不写主库。
- 建立迁移 ID 映射规则：`legacy_table + legacy_id -> new_global_id`。

当前已落地：

- `scripts/tech_insight_loop_inventory.py`：只读读取 SQLite，输出表统计、字段质量、关系检查和迁移预览。
- `config/contracts/tech_insight_loop_legacy_import.json`：机器可读迁移边界。
- `outputs/tech_insight_loop/tech_insight_loop_inventory.{json,md}`：本地盘点产物，不进 Git。

验收：

- 能列出 386 个源、14834 条素材、66 份报告、275 条实体大事记。
- 能输出重复源候选和字段缺失统计。
- 能通过 `backend/.venv/bin/python -m pytest backend/tests/test_tech_insight_loop_inventory.py`。

### 阶段 1：信息源治理融合

目标：把 386 个源和当前 294 个源做合并，不改变现有抓取主链路。

交付：

- 源合并脚本：按 RSS URL、原始 URL、规范化 host/path、公众号账号去重。
- 将 `source_tier`、`source_channel_type`、`expert_routes_json`、`board_relevance_json`、`source_score_breakdown_json` 写入 `data_sources.metadata_json`。
- 将高质量源的 `source_quality_score` 映射到 `data_sources.source_score`。
- 前端数据源详情补展示源等级、渠道类型、专家路由、最近失败原因。

验收：

- 合并后源数量、重复源数量、停用源数量有报告。
- 当前 294 个源不会被压缩包数据误停用。
- 同一个 RSS 不重复抓取。

### 阶段 2：评分器和准入规则融合

目标：把 Tech Insight Loop 的评分能力迁入当前推荐服务。

交付：

- 新增评分配置文件，例如 `config/scoring/content_scorer_v2.json`。
- 后端新增可测试评分模块，吸收以下维度：
  - source tier
  - source channel score
  - topic relevance
  - maturity
  - impact
  - evidence
  - competition
  - expert route
  - noise penalty
- `recommendation_items` 增加结构化字段或写入 `summary_json`：
  - `admission_level`
  - `info_pool`
  - `noise_types`
  - `reject_reasons`
  - `scorer_breakdown`
  - `expert_routes`
- 前端候选池展示准入等级、噪声原因和推荐依据。

验收：

- 同一批样例在新评分器下能稳定输出 P0/P1/P2/P3/R。
- 泛商业、财报、活动预告、纯营销内容被降级或拒绝。
- 评分结果不改变公司 SQL 字段合同。

### 阶段 3：历史素材和报告迁移

目标：把旧系统历史数据作为可追溯历史资产导入，而不是直接污染当前日报。

当前已落地：

- `scripts/tech_insight_loop_legacy_dry_run.py`：只读生成 `articles/reports` 历史导入 dry-run，不写旧 SQLite，不写 InfoWatchtower 主库。
- `scripts/tech_insight_loop_legacy_import.py`：默认 no-write，只在显式传入 `--execute` 时写 InfoWatchtower 主库；导入过程不运行旧 `app.py`，也不把旧 SQLite 同名表搬进新库。
- `historical_reports`：旧 `reports` 的无损归档表。旧库存在同一天/同周多份报告，不能直接写入当前一日/一周唯一的 `daily_reports/weekly_reports`。
- `outputs/tech_insight_loop/tech_insight_loop_legacy_dry_run.{json,md}`：本地 dry-run 产物，不进 Git。
- dry-run 确认 14834 条旧素材全部可作为历史 raw 归档候选，14713 条具备模型字段可作为后续历史 news 草稿候选；66 份报告中 45 份 daily 和 13 份 weekly 可作为 `historical_reports` 归档候选，3 份 brief 和 5 份 brief_ppt 暂不进入本批归档。
- 报告引用保持和盘点一致：2773 个引用中 2743 个可解析到旧 `articles.id/article_id`，30 个未解析，后续真实导入必须记录缺口。

交付：

- `articles -> raw_items` 归档导入脚本。旧素材使用禁用的 `legacy_tech_insight_loop` 档案源，原始行完整写入 `raw_payload_json.legacy_tech_insight_loop`，默认不进入当前推荐和日报。
- `reports -> historical_reports` 归档导入脚本；后续如需在 UI 里按日报/周报阅读，再从 `historical_reports` 做视图或投影。
- `source_article_ids_json` 到新条目的映射。
- 历史报告默认状态为 `imported` 或 `published_imported`，和新系统生成状态区分。

验收：

- 任意导入报告条目可以追溯到旧 SQLite 原行。
- 历史导入不会自动触发公司 SQL 导出。
- 可以按日期查看旧日报/周报正文。

### 阶段 4：实体大事记融合

目标：迁入实体和实体事件，补齐当前系统的“公司/组织/项目时间线”能力。

当前已落地：

- 新增 `tracked_entities` 和 `entity_milestones` 归档表，分别保存旧 `ai_entities` 和 `entity_milestones`。
- 新增 `scripts/tech_insight_loop_entity_import.py`，默认 no-write；只有传入 `--execute` 且配置目标 `DATABASE_URL` 时才写入 InfoWatchtower 主库。
- 旧实体和事件完整原行进入 `metadata_json.legacy_tech_insight_loop`；事件会尽量解析到已导入的 `raw_items` 和 `historical_reports`，未解析旧 `article_id/report_id` 保留在 `metadata_json.legacy_refs`。
- 导入幂等键为 `legacy_system + legacy_table + legacy_id`，不会修改 `raw_items/news_items/historical_reports`，也不会进入当前推荐、日报或公司 SQL。
- 新增 API 和前端入口：`GET /api/entity-timeline/summary`、`GET /api/tracked-entities`、`GET /api/entity-milestones`、`GET /api/entity-milestones/{id}` 和 `/entity-milestones`，用于查看实体列表、事件时间线、重要等级、板块和旧引用解析缺口；`PATCH /api/entity-milestones/{id}` 只治理当前系统新登记事件。
- `/entity-milestones` 不触发导入、不写推荐、日报/周报采信或标准公司 SQL。旧导入事件只读；当前日报/周报条目登记出的 `legacy_system=current` 事件可编辑、确认、撤销，并可转成 requirement 来源。
- 新增导入验收 API 和前端入口：`GET /api/legacy-import/summary`、`GET /api/legacy-import/gaps` 和 `/historical-reports` 顶部验收面板，用于核对历史 raw、报告、实体、事件覆盖率和未解析旧引用。
- 新增命令行执行验收包装：`scripts/tech_insight_loop_import_verify.py`，复用同一套导入摘要和缺口统计；默认不写库，`--check-only` 只读核对当前库，`--execute` 配合 limit 做小批量导入，全量必须显式 `--confirm-full-import`。

交付：

- 配置 `DATABASE_URL` 后真实数据库小批量/全量执行历史和实体导入，并用现有导入验收入口和输出报告核对导入摘要、未解析旧引用和跳过原因。
- 实体大事记页面已补当前事件编辑、确认、撤销和从日报/周报采信项继续沉淀实体事件；历史导入事件仍用于核对旧库导入质量和引用缺口，不允许覆盖旧行。

验收：

- 275 条旧大事记可导入。
- 每条事件保留来源 URL、实体、事件时间、重要等级。
- 后续删除或编辑事件不得影响原始新闻、历史报告、推荐、日报或公司 SQL。

### 阶段 5：质量闭环和高级导出

目标：迁入 Tech Insight Loop 的质量运营能力。

当前已落地：

- 新增 `historical_feedback_items` 和 `historical_job_runs` 归档表，分别保存旧 `feedback/article_quality_feedback` 和旧 `jobs`。
- 新增 `scripts/tech_insight_loop_quality_import.py`，默认 no-write；只有传入 `--execute` 且配置目标 `DATABASE_URL` 时才写入 InfoWatchtower 主库。
- 旧反馈和质量反馈完整原行进入 `metadata_json.legacy_tech_insight_loop`，并尽量解析到已导入的历史 `raw_items`；未解析旧 `article_id` 保留在 `metadata_json.legacy_refs`。
- 旧任务只作为统计型历史运行记录保存，不创建当前 `ingestion_runs`，不迁移旧任务状态机。
- 导入验收摘要已扩展历史反馈和旧任务指标，`GET /api/legacy-import/gaps` 可展示历史反馈未解析素材引用。
- 新增 `GET /api/quality-archive/summary`、`GET /api/historical-feedback-items`、`GET /api/historical-job-runs` 和前端 `/quality-archive`，用于查看旧反馈、质量反馈、旧任务统计和反馈引用缺口；查询保持只读，workspace admin 可把单条历史反馈通过 `source_historical_feedback_item_id` 登记为当前 requirement 来源。
- `scripts/tech_insight_loop_import_verify.py` 可通过 `--include-quality-archive` 显式把历史反馈和旧任务归档纳入小批量/全量执行验收。

交付：

- 内容评分器页面：查看配置、校验、预览、重算。
- 质量闭环页：源失败、模型处理进度、评分进度、反馈统计。
- 报告 Markdown/PDF 导出。
- GitHub PR 和快报 PPT 接口作为可选插件，默认关闭。

验收：

- 管理员可以看到“哪些源噪声高、哪些规则导致拒绝、哪些内容需要复核”。
- 外部导出能力不影响公司 SQL 导出。
- 没有密钥写入数据库和同步包。

## 8. 不建议做的事情

- 不建议把 `app.py` 挂成第二个后端服务。
- 不建议把 SQLite 直接转换成 PostgreSQL 同名表。
- 不建议让旧系统 reports 和新系统 daily_reports 同时作为日报事实源。
- 不建议把业务板块直接改成公司 SQL category。
- 不建议迁移旧系统的任务状态机，只迁移运行记录摘要。
- 不建议先做复杂双向同步，迁移期只做一次性导入和可回滚校验。

## 9. 最小可落地路线

如果目标是尽快提升质量和数据覆盖，建议先做三件事：

1. 源融合：386 个源与当前 294 个源去重合并，保留源等级和专家路由。当前已完成第一轮导入能力。
2. 评分器融合：迁入 `content_scorer_config`，让候选池和日报选择更稳。当前已完成结构化准入字段落库和前端展示。
3. 历史报告和实体大事记导入：先能查历史日报/周报和实体时间线，不急着纳入 SQL 和新日报流水线。当前已完成只读盘点、dry-run、真实归档导入脚本、实体大事记导入脚本、`/historical-reports`、`/entity-milestones`、导入摘要/引用缺口只读查看入口、当前事件治理和执行验收脚本，下一步是在配置真实 `DATABASE_URL` 后执行生产验收。

这三步完成后，系统的可见收益最大：源更多、噪声更低、历史可查，同时不会破坏现有内网 SQL 合同。

## 10. 风险和控制点

| 风险 | 控制方式 |
|---|---|
| 分类口径混乱 | 成品新闻只认 10 类，业务板块只做辅助维度。 |
| 重复源变多 | 合并前生成重复源报告，人工确认后再导入。 |
| 历史素材污染新日报 | 历史导入默认 imported 状态，不自动进入推荐和 SQL。 |
| 评分器过强导致漏报 | P2/P3 保留观察池，不直接删除。 |
| 旧系统时间字段是字符串 | 导入脚本统一解析为 timezone-aware datetime，失败则记录错误，不写假时间。 |
| 密钥外泄 | 只迁移 credential_ref 和配置模板，不迁移 env、token、cookie。 |
| UI 变复杂 | 先把质量治理放到管理员页，不干扰普通日报/周报阅读。 |

## 11. 下一步建议

阶段 0 只读盘点、第一轮源/评分融合、历史素材/报告 dry-run、真实归档导入脚本、实体大事记导入脚本、当前实体事件治理、历史反馈/旧任务归档脚本、历史报告/实体大事记/质量归档查看入口、导入验收入口、执行验收脚本和验收报告断言器已经完成。本地隔离 PostgreSQL 全量验收已通过；下一步是在生产数据库复跑并留存同口径证据：

```text
读取 outputs/tech_insight_loop/tech_insight_loop_inventory.json
-> 读取 outputs/tech_insight_loop/tech_insight_loop_legacy_dry_run.json
-> 读取 Tech Insight Loop SQLite
-> python3 scripts/tech_insight_loop_import_verify.py --check-only
-> python3 scripts/tech_insight_loop_import_verify.py --execute --article-limit 20 --report-limit 5 --entity-limit 5 --milestone-limit 20
-> --execute 写 legacy_table + legacy_id 到 raw_items / historical_reports
-> 保留 legacy_tech_insight_loop 原始行
-> 标记 historical_imported / published_imported
-> 输出未解析报告引用和跳过原因
-> --execute 写 legacy_table + legacy_id 到 tracked_entities / entity_milestones
-> 输出未解析素材/报告引用和跳过原因
-> 可选加 --include-quality-archive --feedback-limit 4 --quality-feedback-limit 4 --job-limit 10
-> --execute 写 legacy_table + legacy_id 到 historical_feedback_items / historical_job_runs
-> 输出历史反馈未解析素材引用和旧任务统计摘要
-> 全量后再运行 python3 scripts/tech_insight_loop_import_verify.py --check-only
-> 运行 python3 scripts/validate_tech_import_acceptance.py outputs/tech_insight_loop/tech_insight_loop_import_execution_report.json
-> unresolved refs 未清零时，用 --accepted-gaps-json 归档缺口原因
-> 使用 /quality-archive 核对旧反馈类型、质量原因、任务状态和失败源
-> 人工确认
-> 在 /historical-reports 顶部导入验收面板核对覆盖率和 unresolved refs
-> 在 /historical-reports 核对正文、时间范围和 unresolved refs
-> 在 /entity-milestones 核对实体、事件时间线和 unresolved refs
```

真实导入仍必须保持四条禁区：不运行旧 `app.py`，不复制 SQLite 同名表，不自动进入当前推荐，不进入标准公司 SQL。
