# 第一版实现计划

本文是 InfoWatchtower 第一版的施工计划。它不重新定义架构；架构以 `docs/00-system-design.md`、`docs/implementation-handoff.md` 和 `config/contracts/*.json` 为准。

如果说 `docs/implementation-handoff.md` 回答“要实现什么”，本文回答“按什么顺序实现、每一步交付什么、怎么验收、什么时候能进入下一步”。

## 1. 文档结构复核结论

当前文档体系已经可以开始开发：

- `docs/00-system-design.md` 是唯一总纲，覆盖愿景、边界、主数据流、登录、部署、同步和 SQL 导出。
- `docs/implementation-handoff.md` 是任务书，覆盖后端实施顺序、前端页面、最低测试和第一版完成定义。
- `config/contracts/*.json` 是机器契约，覆盖字段、adapter、SQL、登录、扩展点和同步。
- 模块文档负责展开细节，不应成为另一套架构。

需要补强的地方：

- 开发阶段边界要更清楚。
- 每阶段交付物要落到目录和命令。
- 每阶段验收要能被工程师或 AI 直接执行。
- 前端、后端、部署不要并行散开，先跑通端到端主链路。

本文补齐这些执行细节。

## 2. 开发总原则

- 先做可运行骨架，再做业务闭环，再做体验增强。
- 每个阶段结束都必须能演示一个真实动作，不交付只有模型没有流程的代码。
- 数据库迁移、后端模型、API schema、前端类型和测试必须同步更新。
- 所有业务对象必须保留追溯链路，不能为了前端展示压扁数据。
- adapter 可插拔，新增数据源类型不应修改 dedupe/report/export 主链路。
- 工作台可插拔，但必须共享数据源管理、候选池、日报、周报和导出主链路。
- 新工作台不复制数据源定义；通过 `workspace_source_links` 启用共享源并配置权重、默认板块、日限和抓取相关信息。一级/二级标题由 `workspaces.config_json.label_policy` 统一管理，不在单个源配置。
- 工具目录、工具任务、独立专题等只能作为数据库注册的插件模块接入，第一版默认不显示。
- `workspace_code` 是产品桌面和权限边界，`domain_code` 是内容主题板块，不得混用。
- 标签体系统一走 `label_sets/labels/content_labels`，不在每个工作台写一套自定义字段。
- 公网和内网共用一套代码，差异只通过配置、认证 adapter 和同步策略控制。
- 密钥、token、cookie、`.env` 不进入 Git，不进入同步包，不写入日志。
- 当前开发默认每轮只形成一个逻辑 commit；临时提交在推送前 squash。

## 3. 第一版总交付

第一版完成时必须跑通：

```text
管理员登录
-> 导入旧种子源
-> 抓取至少一个 RSS 源
-> raw_items 入库
-> news_items 标准化
-> 去重
-> 推荐
-> 生成日报草稿
-> 管理员编辑并发布
-> 用户点赞/评分/评论/回复
-> 导出公司 SQL
-> 从 SQL 导出记录追溯回 raw_items.raw_payload_json
-> Docker Compose 部署到单台服务器
```

第一版允许轻实现但必须预留：

- wiseflow adapter 骨架。
- page monitor adapter 骨架。
- paper_rss/paper_api/paper_page 骨架。
- weekly report 草稿骨架。
- sync outbox/inbox 同步包骨架。
- domain pack 扩展目录和注册点。
- workspace/module 扩展，支持规划部情报工作台之外的新工作范围；附加模块默认关闭。

## 4. 阶段 0：仓库可运行骨架

目标：从设计交接仓变成可以本地启动的 monorepo。

交付目录：

```text
backend/
  app/main.py
  app/core/config.py
  app/core/database.py
  pyproject.toml
  alembic/
  tests/
frontend/
  package.json
  src/
deploy/
  docker-compose.local.yml
  docker-compose.prod.yml
  Caddyfile or nginx.conf
.github/workflows/
```

建议默认实现：

- 后端：FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 + pytest。
- 数据库：PostgreSQL。
- 任务：Redis + RQ worker；scheduler 服务定时投递任务。
- 前端：Vue 3 + TypeScript + Vite + Vue Router + Pinia + Element Plus。
- 本地开发：Docker Compose 起 PostgreSQL/Redis，后端和前端可本地热启动。

验收命令：

```text
cd backend && pytest
cd backend && alembic upgrade head
cd frontend && npm run build
docker compose -f deploy/docker-compose.local.yml up --build
curl http://localhost:8000/healthz
```

通过标准：

- `/healthz` 返回应用、数据库和版本信息。
- Alembic 能创建空基础 schema。
- 前端能打开登录页或占位工作台。
- Docker Compose 本地能启动 backend、frontend、postgres、redis。

## 5. 阶段 1：数据库模型与追溯链路

目标：先把主数据骨架和外键链路建稳。

当前实现状态：已完成。代码位于 `backend/app/models/`，初始迁移为 `backend/alembic/versions/f65224efb871_create_stage_1_schema.py`，追溯链路测试位于 `backend/tests/test_stage1_models.py`。

优先表：

```text
users / roles / permissions / user_roles
data_sources
raw_items
news_items
dedupe_groups / dedupe_group_items
recommendation_runs / recommendation_items
generated_news
daily_reports / daily_report_items
reactions / ratings / comments
editorial_actions / audit_logs
export_jobs / export_job_items
sync_outbox / sync_inbox / sync_runs / sync_conflicts
insights / strategic_implications / requirements / requirement_source_links / topic_tasks
```

实现要求：

- 每个可同步对象都有 `global_id`、`origin_instance_id`、`revision`、`content_hash`。
- `data_sources/raw_items/news_items/generated_news` 都有 `domain_code`、`visibility_scope`、`sync_policy`。
- `raw_items.raw_payload_json` 用 PostgreSQL `JSONB` 保存完整原始 payload。
- `comments` 支持 `parent_id` 和 `root_id`，第一版即可支持楼中楼。
- `daily_report_items` 保存 editor override，不覆盖 `generated_news`。

验收：

- 任意 `daily_report_items` 可以沿外键查到 `raw_items.raw_payload_json`。
- 删除或编辑日报条目不影响 raw 原始记录。
- 迁移能从空库完整执行到最新版本。
- 关键外键有测试覆盖。

已验证：

```text
cd backend && DATABASE_URL="" pytest
cd backend && DATABASE_URL="sqlite:///./stage1_upgrade.sqlite" alembic upgrade head
make migration-check
make migrate
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:5173/healthz
```

## 6. 阶段 2：登录、身份适配和 RBAC

目标：公网能登录，内网能快速接 header 身份。

当前实现状态：已完成最小闭环。后端代码位于 `backend/app/auth/` 和 `backend/app/api/routes/auth.py`，前端登录与用户权限页面位于 `frontend/src/pages/LoginPage.vue` 和 `frontend/src/pages/UsersPage.vue`，迁移为 `backend/alembic/versions/21c4a64d4e6b_add_stage_2_auth_fields.py`。

实现：

```text
AuthAdapter
-> ExternalIdentity
-> IdentityResolver
-> users
-> session/JWT
-> RBAC
```

必须支持：

- `local`
- `public_password`
- `intranet_header`

API：

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/users
GET  /api/roles
PATCH /api/users/{id}/roles
```

验收：

- 公网模式下用户名密码能登录。
- 内网模式下可信 header 自动 provision 用户。
- 业务代码只使用本地 `user_id`、角色和权限。
- 角色至少有 `super_admin`、`editor_admin`、`analyst`、`viewer`。
- 登录、登出、授权变更写 `audit_logs`。

已验证：

```text
make test
make migration-check
make migrate
POST /api/auth/login
GET  /api/auth/me
GET  /api/users
GET  /api/roles
PATCH /api/users/{id}/roles
```

后续加固计划：

- 公网部署前补登录限流、CSRF、服务端 session、HTTPS Secure Cookie 和默认密码禁用。
- 新增 `public_oidc`，优先实现 Google OIDC。
- 新增 `intranet_oidc`，通过公司 IDaaS code flow 换取工号、姓名、部门和邮箱。
- 保持所有外部身份只映射到 `ExternalIdentity`，业务层继续只认本地 `user_id` 和 `roles`。

## 7. 阶段 3：数据源导入与 adapter 框架

目标：旧种子源进入数据库，adapter 注册机制固定。

前置调整：工作台模型按共享主链路收束。`workspaces/workspace_sections/workspace_memberships` 管工作范围、页面和权限；`workspace_source_links` 管工作台启用哪些共享数据源；`domain_code` 继续只表达情报主题板块。

当前实现状态：导入、工作台统一标签/新闻结构策略、adapter 框架、RSS/paper RSS/page_manual/page_monitor 抓取到 raw 入库、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口已完成。`backend/app/adapters/` 已有统一 `SourceAdapter`、RSS adapter、页面源 adapter 和 wiseflow/paper/manual 等骨架；`/api/sources/import-legacy-seeds` 可以导入旧 113 个种子源和 `information_source_registry_20260511.csv` 补充台账，361 条导入记录按 URL 去重后形成 294 个共享源，规划部工作台 v1 默认全部启用；`/api/sources/import-tech-insight-loop` 可以导入 `sources_full_zh.csv` 的 386 行 Tech Insight Loop 源治理记录，355 行有入口、31 行待补入口，去重后形成 363 个共享源，并把源等级、渠道类型、专家路由、板块相关度和评分拆解保存为源侧 metadata；`/api/sources?workspace_code=...` 可以展示共享源池及当前工作台配置；`/api/workspaces/{workspace_code}/label-policy` 可以增删改工作台统一新闻一级/二级标签策略，并返回/保存 `news_format_code`、`export_category_mode` 与 `required_content_fields`；`planning_intel` 默认 `ai_sql_categories + company_sql_v1 + news_primary`，`ai_tools` 默认 `ai_tools_categories + tool_intel_v1`；数据源侧方向标签来自 `planning_source_tags/source_tags.json`，只用于源管理和评分先验；`/api/sources/{source_id}/workspace-link` 可以更新当前工作台对单源的启用状态、权重和日限；`/api/sources/{source_id}/fetch` 可以触发单个 RSS/paper RSS/page_manual/page_monitor 源抓取并幂等写入 `raw_items`；`/api/ingestion/runs` 可以按工作台创建同步执行的抓取 run，默认处理该工作台已启用的 `rss/paper_rss/page_manual/page_monitor/wiseflow` 源并写入 `ingestion_runs` 摘要；抓取 run 支持并发池和单源超时，默认 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`；完整日报流水线通过 `/api/pipeline/daily-runs` 默认覆盖同一套全量源类型。scheduler 可按环境变量定时把每日完整流水线入队给 worker 执行，默认关闭自动任务；`workspace_source_links` 会为规划部工作台建立全量启用链接。

实现：

- 导入 `config/seeds/legacy/wiseflow_sources.json`。
- 导入 `config/seeds/legacy/rss_sources.json`。
- 导入 `config/seeds/legacy/page_sources.json`。
- 按 `config/contracts/source_fields.json` 映射字段。
- `folo_metadata.info_category = 学术论文` 的 RSS 源导入为 `paper_rss`。
- 导入后默认写入共享数据源池，并为所有已启用默认工作台创建 `workspace_source_links`。

adapter 接口：

```python
class SourceAdapter:
    source_type: str

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        ...
```

第一版实现：

- `RssFeedAdapter` 和 `PaperRssFeedAdapter` 可真实抓取。
- `PageListingAdapter` 和 `ManualPageAdapter` 可真实抓取页面列表和手工页面。
- `WiseflowReadInfoAdapter` 骨架，接口按旧 `/read_info` 预留。
- `ManualNewsAdapter` 骨架。
- `PaperMetadataEnricher` 骨架。

验收：

- 数据源导入数量与 contract 的 seed counts 对齐。
- 旧 wiseflow 不被混成 RSS。
- `planning_intel` 和 `ai_tools` 都能看到 294 个共享源链接；规划部工作台默认 294 个全部启用。
- 单个 RSS/paper RSS/page_manual/page_monitor 源可以手动触发抓取，首次创建 `raw_items`，重复抓取更新已有 raw 记录而不重复插入。
- 可以创建工作台级 ingestion run，run 记录 source 成功/失败、拉取数、raw 新增数和 raw 更新数；`limit=0` 可用于无网络验收 API。
- 可以启动 worker/scheduler 容器；默认 `INGESTION_SCHEDULER_ENABLED=false` 不会自动执行，设为 `true` 后按 `INGESTION_SCHEDULER_INTERVAL_SECONDS` 入队完整日报流水线；如需旧的只抓取行为，设置 `SCHEDULER_JOB_MODE=ingestion_only`。
- 前端首页当前显示阶段 5；数据源页仍可验收阶段 3 的数据源管理能力，并能通过右侧 tab 面板增删改工作台统一一级/二级标签策略、查看和保存工作台新闻结构字段、通过“配置”修改单源启用/权重/日限、通过“抓取”按钮触发 RSS/paper RSS/page_manual/page_monitor 单源抓取。
- 新增 source_type 只需注册 adapter。
- adapter 输出满足 `adapter_pipeline.json` 的 raw 字段要求。

## 8. 阶段 4：raw 入库、标准化与去重

目标：把不同来源统一进 `raw_items -> news_items -> dedupe_groups`。

当前实现状态：已完成最小闭环。服务位于 `backend/app/normalization/news.py`，API 位于 `backend/app/api/routes/news.py`，schema 位于 `backend/app/schemas/news.py`；`dedupe_groups` 已改为按 `workspace_code + dedupe_key` 唯一，迁移为 `backend/alembic/versions/d7e8f9a0b1c2_scope_dedupe_groups_by_workspace.py`。同一个共享 raw 可以被不同工作台各自标准化，winner/loser 状态不会跨工作台互相污染。

实现：

- 抓取任务写 `raw_items`，完整保存 `raw_payload_json`。
- `normalize_to_news_item(raw_item)` 映射成 `news_items`。
- `canonical_url` 统一规范化。
- `dedupe_key` 在 news 标准层生成。
- 去重发生在 `news_items` 之后、推荐之前。
- `POST /api/news-items/normalize` 按工作台处理该工作台已启用源的 raw，幂等创建或更新 news，并重建受影响的 dedupe group。
- `GET /api/news-items` 查看标准化 news 和 raw 追溯 ID。
- `GET /api/dedupe-groups` 查看去重组、winner、loser 和重复原因。

硬去重规则：

- 有 URL：`dedupe_key = "url:" + canonical_url`。
- 无 URL：`dedupe_key = "title:" + normalized_title + "|date:" + yyyy-mm-dd`。
- URL、标题和时间都缺失的 raw item 不能进入推荐链路。

winner 选择顺序：

1. 有 URL。
2. wiseflow legacy bonus。
3. 官方源/可信源。
4. 正文更完整。
5. 发布时间更新。

验收：

- 同 canonical URL 的两条新闻只有一个 active winner。
- loser 写入 `duplicate_of`，但 raw 不删除。
- 不同 URL 的相似主题第一版不自动删除。
- `docs/data-examples.md` 中的 RSS 样例能转成 news item。
- 同一条共享 raw 在 `planning_intel` 和 `ai_tools` 下可各自生成 news item 和 dedupe group。

已验证：

```text
cd backend && DATABASE_URL="" pytest tests/test_news_normalization.py tests/test_news_api.py
cd backend && ruff check app/normalization app/schemas/news.py app/api/routes/news.py tests/test_news_normalization.py tests/test_news_api.py
```

## 9. 阶段 5：推荐、日报草稿和反馈链路

目标：形成可解释推荐，并能进入日报编辑。

当前实现状态：已完成可回填闭环，并新增内容准入层。服务位于 `backend/app/recommendations/service.py`，完整流水线 API 位于 `backend/app/api/routes/pipeline.py`，推荐/日报 API 位于 `backend/app/api/routes/recommendations.py` 和 `backend/app/api/routes/reports.py`。`POST /api/pipeline/daily-runs` 会按工作台和 `day_key` 执行抓取、标准化/去重、推荐、结构化生成和日报草稿；`POST /api/recommendation/runs` 仍可只重跑推荐层。推荐读取当前工作台目标日期 active winner，先按主题相关性、专家影响、证据强度、新颖性、技术成熟度/实现细节、时效性和噪声惩罚计算 `P0/P1/P2/P3/R` 准入等级，再生成可解释推荐分，写入 `recommendation_items`，为 selected 项生成 `generated_news`，并创建或替换日报草稿。`backend/app/scoring/content_scorer.py` 已接入 `config/scoring/content_scorer_v2.json`，在保留现有候选选择和日报生成逻辑的基础上，为 `recommendation_items` 追加 `admission_level`、`admission_score`、`admission_pool`、`noise_types_json`、`reject_reasons_json`、`scorer_breakdown_json` 和 `expert_routes_json`；配置缺失时回退现有评分口径。`planning_intel` 评分默认技术情报优先：AI 软件、AI 基础设施、模型工程、推理/训练、RAG、多智能体、Agent 记忆、硬件厂商技术路线、友商技术动态、AI 芯片、GPU 集群、数据中心架构、通信系统和标准进展加分；但源侧方向标签只是弱先验，厂商源/硬件源必须叠加内容里的架构、推理、模型服务、芯片、数据中心、通信系统、标准或工程实现证据才会进入强准入。融资、财报、股价、采购/中标/集采、消费硬件、活动预告、宣传推广会/品牌行动、泛商业合作、纯营销、航天火箭等离题工程新闻、纯市场新闻、法律/版权元讨论、标题党、社会/教育离题内容和离题生物医学/纯学术论文降权。日报选择先选 `P0/P1`，再用无噪声且有明确技术信号的 `P2` 补足；`P2 paper_rss`、带噪声 `P2`、`P3/R` 默认不进日报；单源、`paper_rss` 和单一内容池都有占比控制，避免内容过度集中。`generated_news` 优先使用 MiniMax 中国区 OpenAI-compatible `https://api.minimaxi.com/v1/chat/completions`（`MINIMAX_GENERATION_ENABLED=true` 且有 key）；prompt 强制简体中文、短关键词和旧系统五段正文。失败或未启用时使用 `rule_v1:fallback` 待复核草稿，不再标记为可发布成品，标准公司 SQL 导出会拒绝这类条目。`backend/app/pipeline/daily.py` 提供同一套每日完整流水线，scheduler 开启后自动执行。`daily_reports` 已按 `workspace_code + domain_code + day_key` 唯一，避免多个工作台同一天同板块互相覆盖。前端 `/daily-reports` 已接入按日期生成日报草稿，列表展示 brief，点击打开详情弹窗后完成正文查看、采信切换、条目编辑、点赞、评分、评论和追溯查看。

推荐字段：

```text
quality_score
topic_score
freshness_score
feedback_score
diversity_score
source_score
heat_score
final_score
recommendation_reason
admission_level
admission_score
admission_pool
noise_types_json
reject_reasons_json
scorer_breakdown_json
expert_routes_json
```

实现：

- 推荐 run 可重跑。
- 推荐只处理目标 `day_key` 的 active winner。
- 每日推荐上限默认 15。
- 同源每日上限默认 2。
- 推荐结果写 `recommendation_items`。
- 生成 `generated_news` 作为日报候选。
- 生成 `daily_reports/daily_report_items` 草稿。
- `daily_report_items.adoption_status = 2` 表示进入日报草稿且未来发布后可被 SQL 导出；草稿未发布前不进入标准 SQL 导出。

反馈：

- `reactions` 保存点赞/取消。
- `ratings` 保存用户评分。
- `comments` 支持评论和回复。
- `editorial_actions` 保存采信、剔除、排序、编辑。

验收：

- 推荐结果能解释每个分数来源。
- 管理员可以把推荐项采信进日报。
- 日报编辑只写 `daily_report_items.editor_*`。
- 点赞、评分、评论会影响后续 `feedback_score/heat_score/source_score` 的计算输入。
- `planning_intel` 和 `ai_tools` 同一天都能生成自己的日报草稿。

已验证：

```text
cd backend && DATABASE_URL="" pytest tests/test_recommendations.py
cd backend && DATABASE_URL="" pytest tests/test_daily_pipeline.py
cd backend && DATABASE_URL="" pytest tests/test_adapters.py
cd frontend && npm run build
make migration-check
```

## 10. 阶段 6：公司 SQL 导出

目标：从已发布日报导出公司内网可导入 SQL。

导出范围：

```text
daily_reports.status = published
daily_report_items.adoption_status = 2
```

每条新闻固定导出 4 条 SQL：

1. `ai_journal`
2. `ai_journal_focus`
3. `ai_journal_analysis`
4. `t_news_data_info`

当前实现状态：阶段 6 标准日报 SQL 导出已落地。`backend/app/exports/company_sql.py` 从已发布日报读取采信且 `generated_news.generation_status = ready`、`generated_by` 非 `rule_v1` 的条目，按旧 `generate_ai_sql.py` 顺序生成四张表 SQL，并写入 `export_jobs/export_job_items`；`POST /api/exports/company-sql/daily-reports/{daily_report_id}` 返回完整 SQL 文本。导出的 `content_json` 严格投影为 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact`，不会把新系统追溯字段混入公司内网字段。`ai_journal.source_title/content` 导出前清洗为纯文本，避免 RSS/网页 HTML 的 `<span>`、`<p>`、script/style 等污染公司 SQL；`created_at` 必须严格对齐旧脚本和已验证合集 SQL 的列顺序与字面量样式，导出为 `'YYYY-MM-DD HH:MM:SS'`，来源缺失发布时间时兜底为日报 `day_key 09:00:00`，不得改成 `STR_TO_DATE`、`CAST`，也不得省略 `ai_journal_analysis.created_at`；SQL 文件头统一为 `InfoWatchtower Company SQL Preview`；所有预览 SQL 必须先通过 `scripts/validate_company_sql.py`，脚本以 `outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql` 为基准逐字段校验四表顺序、列名、URL 串联、日期、五段正文 JSON、HTML 污染和禁用写法；原始抓取内容仍保存在 `raw_items`。

补充约定：公司 SQL 的 `created_at` 字面量时间值按北京时间 `Asia/Shanghai` 渲染，和 `day_key` 推荐归属口径一致；内部仍可 UTC 存储，导出时不得把 UTC 16:00 之后的条目显示成日报前一天。

本地已验证 `2026-04-30` 单日日报 SQL 预览，以及 `2026-05-01` 到 `2026-05-07` 批量日报和合并 SQL 预览。预览文件在 `outputs/sql/previews/`，不进 Git。批量结果中，日报条目均按 `day_key` 对齐；公司 SQL 输出只包含已发布日报里 `adoption_status = 2` 的采信项。

实现要求：

- 字段映射完全遵守 `config/contracts/news_sql_mapping.json`。
- category 默认使用 `config/taxonomy/news_categories.json` 的 10 个 AI 一级标签；`config/taxonomy/source_tags.json` 的源侧方向标签不得导出为 SQL category。
- `source_url` 必须来自 `news_items.source_url`，不能信任模型生成的 URL。
- 导出任务写 `export_jobs` 和 `export_job_items`。
- 导出文件可下载，且能追溯到 daily item/news/raw/source。
- 每次导出或手工整理 SQL 后必须运行 `scripts/validate_company_sql.py`；需要统一标题时先运行 `scripts/validate_company_sql.py --fix-headers`。

验收：

- 一条日报新闻生成 4 条 SQL，顺序正确。
- 只导出已发布且采信状态为 2 的日报条目。
- SQL 字段和旧系统格式一致。
- `scripts/validate_company_sql.py` 全量通过。
- 单条 SQL 失败不影响整批审计记录。

## 11. 阶段 7：前端工作台

目标：让主链路变成可操作看板，不做营销首页。

当前实现状态：浅色工作台壳、登录页、用户权限页、数据源管理页、候选池页、推荐运行页、抓取覆盖率页、周报页、历史归档页、实体大事记页、质量归档页、SQL 导出页、需求页、任务页、同步运行页、审计页、数据源详情页和日报详情/编辑路由已可用。工作台列表与左侧导航已从后端 `workspaces/workspace_sections` 读取，不再前端硬编码；第一版默认不显示工具目录、工具任务、独立热点专题等插件页。数据源页采用参考高保真风格的信息流式共享源列表，展示共享源池、当前工作台启用数、源类型分布、工作台启用状态和抓取状态，已补 Tech Insight Loop 源等级、渠道类型、专家路由、质量分和待补入口状态；右侧标签面板用一级/二级/新闻结构 tab 管理工作台统一策略。单个源配置只包含启用、权重和日限，不维护标签。候选池页接入 `GET /api/dedupe-groups` 和 `GET /api/news-items`，展示 winner、重复来源、来源排序、推荐分、准入等级、噪声/剔除原因、推荐状态、日报采信状态和追溯 ID；推荐运行页接入 `GET/POST /api/recommendation/runs`，展示分数拆解、结构化准入字段和是否进入日报；抓取覆盖率页接入 `GET/POST /api/ingestion/runs`、`POST /api/ingestion/backfill-runs` 和 `GET /api/ingestion/coverage`，支持常规抓取、`rss_window/paper_api/archive_page/sitemap/manual_import` 补采、目标日覆盖漏斗和每源链路详情；SQL 导出页接入 `GET /api/daily-reports`、`GET /api/exports` 和 `POST /api/exports/company-sql/daily-reports/{daily_report_id}`，支持预览和下载 SQL。日报页采用 brief 列表 + 详情处理弹窗，避免正文和处理区互相遮挡，并支持生成稿 ready/fallback 状态展示和草稿重跑。周报页接入 `GET/POST /api/weekly-reports`、发布和条目编辑 API，支持从已发布日报采信项生成候选草稿，并按成品新闻一级标签形成周报板块；默认只展示板块统计、短摘要和采信动作，五段正文只在编辑态出现。历史归档页接入 `GET /api/historical-reports/summary`、`GET /api/historical-reports`、`GET /api/historical-reports/{id}`、`GET /api/legacy-import/summary` 和 `GET /api/legacy-import/gaps`，只读展示旧日报/周报正文、筛选条件、导入覆盖率和引用解析缺口。质量归档页接入 `GET /api/quality-archive/summary`、`GET /api/historical-feedback-items` 和 `GET /api/historical-job-runs`，只读展示旧反馈、质量反馈、旧任务统计和反馈引用缺口。需求、任务、同步和审计页面已从模块化路线页升级为真实 API 页面。

页面顺序：

```text
/login
/dashboard
/sources
/sources/:id
/ingestion-runs
/news
/recommendations
/daily-reports
/daily-reports/:id
/daily-reports/:id/edit
/weekly-reports
/historical-reports
/requirements
/tasks
/exports
/sync
/users
/audit-logs
```

第一批必须可用页面：

- 登录页。
- 工作台首页。
- 数据源列表和详情。
- 候选池列表。
- 推荐 run 页面。
- 日报时间线页。
- 日报编辑页。
- SQL 导出页。
- 用户与角色页。

前端验收：

- 登录后进入工作台。
- 可以导入旧种子源并看到数据源列表。
- 切换工作台后左侧导航仍来自后端 section 配置，且不会默认出现工具目录、工具任务或独立热点专题。
- 数据源页能看到 294 个共享源、当前工作台启用 294 个源，并能区分共享源定义和工作台配置。
- `planning_intel` 默认展示 AI 十分类新闻一级标签；数据源行可展示源侧方向标签；`ai_tools` 默认展示“工具新功能、工具新案例、工具新技术”，且每个一级下有 `cursor/claude code/opencode/codex` 二级标签。
- 数据源页和其他业务页在常见桌面宽度下不应出现横向截断；标签策略的一级/二级/新闻结构应通过显式 tab 切换，避免用户不知道还有隐藏内容。
- 可以触发一次抓取和推荐。
- 可以查看 winner/loser 和推荐原因。
- 可以编辑并发布日报。
- 可以点赞、评分、评论和回复。
- 可以生成并下载公司 SQL。

当前已验证：

```text
cd frontend && npm run build
浏览器打开 /news、/recommendations、/exports、/ingestion-runs、/weekly-reports、/requirements、/tasks、/sync、/audit-logs
```

以上页面不再落入通用 `PlaceholderPage`。`/weekly-reports`、`/requirements`、`/tasks`、`/sync`、`/audit-logs` 已是真实 API 页面；其中 `/sync` 已支持同步包导出、下载、导入和 `data_sources/raw_items/news_items` 幂等 apply，后续阶段继续扩展更多 object_type、冲突解决 UI 和导入摘要。

## 12. 阶段 8：同步、部署和自动发布

目标：公网可部署，内网可复用同一套代码。

实现：

- `deploy/docker-compose.prod.yml`。
- Caddy 或 Nginx 反向代理。
- PostgreSQL 数据卷不暴露公网端口。
- Redis 不暴露公网端口。
- `.env.production` 放服务器，不进 Git。
- GitHub Actions 通过 SSH 部署。
- `sync_outbox/sync_inbox/sync_runs/sync_conflicts` 骨架。
- 公网导出同步包，内网导入同步包。

验收：

- 单台服务器 Docker Compose 能启动完整系统。
- `80/443` 可访问网站。
- `/healthz` 可被部署脚本检查。
- `postgres:5432` 只在 Docker 内网访问。
- 同步包不包含 token、cookie、password、secret、`.env`。
- 重复导入同一同步包不会重复写数据。

## 13. 阶段 9：硬化与第一版发布

目标：从能跑变成能稳定试运行。

必须补齐：

- 备份脚本和恢复演练。
- 日志脱敏。
- 关键任务重试。
- 后台任务失败可见。
- 审计日志可查询。
- 数据源抓取失败率统计。
- SQL 导出前字段长度和 URL 过长校验。
- 最小端到端测试。

发布验收：

```text
pytest
frontend build
alembic upgrade head
docker compose prod build
seed import
RSS ingest
normalize
dedupe
recommend
daily publish
comment/rating/reaction
company SQL export
trace SQL -> raw_payload_json
backup restore smoke test
```

## 14. 下一轮编码任务

阶段 0-7 的主页面已经有可操作骨架。`2026-05-21` 到 `2026-05-27` 的规划部日报已经补齐、发布并导出公司 SQL；`2026-05-21` 到 `2026-05-26` 每天 10 条采信项，`2026-05-27` 通过 RSS/paper RSS 当前窗口补采新增 72 条 raw/news 后生成 6 条采信项，单日 SQL 和合集 SQL 均已通过 `scripts/validate_company_sql.py`。演示/恢复库可使用 `scripts/import_company_sql_preview_to_reports.py` 从已校验单日 SQL 预览回填日报和周报工作台数据；本地已用 `2026-05-28` 到 `2026-06-12` 的 14 个单日预览回填 512 条日报采信项，并生成 3 个已发布周报草稿。

当前已实现快照：

- 主链路：抓取、raw 入库、news 标准化、工作台隔离去重、推荐、MiniMax 结构化生成、日报发布和标准公司 SQL 导出已跑通。
- 源治理：`/api/sources/import-tech-insight-loop` 已支持导入 Tech Insight Loop 的 386 行源治理记录，其中 355 行有可抓取入口、31 行作为待补入口 metadata-only，按 URL/RSS 去重后形成 363 个共享源且不覆盖既有人工启用关系。
- 融合迁移基线：`scripts/tech_insight_loop_inventory.py` 已只读盘点旧 SQLite，确认 14834 条素材、66 份报告、23 个实体、275 条实体大事记、反馈和旧任务记录；`scripts/tech_insight_loop_legacy_dry_run.py` 已生成历史素材/报告导入 dry-run，确认 14834 条素材可归档、58 份 daily/weekly 报告可归档、报告引用 2773 个中 30 个缺口；`scripts/tech_insight_loop_legacy_import.py` 已提供默认 no-write、`--execute` 才写库的真实导入脚本，旧素材进入禁用的 `legacy_tech_insight_loop` 档案源和 `raw_items.raw_payload_json.legacy_tech_insight_loop`，旧报告进入 `historical_reports`，不进入当前推荐、日报和公司 SQL；`tracked_entities/entity_milestones` 归档模型、`scripts/tech_insight_loop_entity_import.py` 和 `/entity-milestones` 只读页面已提供旧实体/大事记导入与查看能力，旧引用缺口写入 `metadata_json.legacy_refs`；`historical_feedback_items/historical_job_runs` 归档模型、`scripts/tech_insight_loop_quality_import.py` 和 `/quality-archive` 只读页面已提供旧反馈、质量反馈和旧任务统计导入/查看能力，不创建当前反馈或当前抓取任务；`GET /api/legacy-import/summary`、`GET /api/legacy-import/gaps` 和 `/historical-reports` 顶部验收面板已提供导入覆盖率、未解析引用和缺口样例查看；`scripts/tech_insight_loop_import_verify.py` 已提供 check-only、小批量执行和全量确认执行的统一验收报告，历史反馈和旧任务归档通过 `--include-quality-archive` 显式纳入；`scripts/validate_tech_import_acceptance.py` 已把生产 `--check-only` 报告的覆盖率、只读 guardrail 和 accepted-gaps 归档做成机器验收。
- 可观测：`/ingestion-runs` 已展示常规抓取、多模式补采、每源覆盖统计和目标日 raw/news/winner/recommendation/daily 漏斗；`/news` 已展示候选推荐分、推荐状态、日报采信状态和追溯 ID。
- 内容运营：日报已支持 brief 列表、详情弹窗、采信、编辑、点赞、评分、评论和生成稿重跑；已校验单日公司 SQL 预览可以回填为完整追溯链路的已发布日报；周报 v1 已支持从已发布日报采信项生成候选、按一级标签分板块、条目采信/剔除、排序、编辑和发布。
- 管理页面：数据源、推荐运行、SQL 导出、用户权限、需求、任务、历史归档、实体大事记、质量归档、同步和审计均已从占位页升级为真实 API 页面。
- 自动化：scheduler 可按北京时间固定触发每日完整流水线，生产推荐每天早上生成昨天日报。

下一轮编码按这个顺序做：

1. Tech Insight Loop 历史归档执行验收：配置真实数据库 `DATABASE_URL` 后，先跑 `python3 scripts/tech_insight_loop_import_verify.py --execute --article-limit 20 --report-limit 5 --entity-limit 5 --milestone-limit 20` 小批量；如需同步验收历史反馈和旧任务，加 `--include-quality-archive --feedback-limit 4 --quality-feedback-limit 4 --job-limit 10`；再跑 `--execute --confirm-full-import` 全量。全量后再跑 `python3 scripts/tech_insight_loop_import_verify.py --check-only`，并用 `python3 scripts/validate_tech_import_acceptance.py outputs/tech_insight_loop/tech_insight_loop_import_execution_report.json` 判定覆盖率、只读 guardrail 和未解析引用归档。用输出报告、`GET /api/legacy-import/summary`、`GET /api/legacy-import/gaps`、`/historical-reports` 顶部验收面板和 `/quality-archive` 核对覆盖率、未解析报告/反馈引用、旧任务失败原因和跳过原因。
2. Tech Insight Loop 实体大事记执行验收：同一验收脚本会在历史导入后执行实体/事件导入；也可用原子脚本 `scripts/tech_insight_loop_entity_import.py --execute` 单独重跑，并用导入验收面板和 `/entity-milestones` 核对实体事件覆盖率、未解析旧引用和跳过原因。
3. SQL 导出增强：补导出前字段长度、URL 长度、HTML 污染校验；把 SQL 条目追溯到 daily item、generated news、news item、raw item 和 source。
4. 部署和登录安全：补公网登录限流、默认密码治理、Google OIDC 预留、公司 IDaaS code flow adapter 预留、生产 Compose 和反向代理配置。
5. 公网/内网同步骨架：当前已有 `sync-runs` 运行记录页；下一步做同步包导出/导入、下载、幂等导入和冲突审计，不做实时双写。
6. 周报增强：当前周报 v1 管理采信项和板块；下一步补热度/反馈排序、自动周报正文、周报导出和必要的 weekly section 映射。
7. 战略闭环深化：当前已有 requirements、topic tasks 的列表/创建/状态更新和审计；下一步从已发布日报/周报条目沉淀 insight、requirement 和 task，并补追溯关系。
8. 历史补采深化：补更完整的论文 provider、分页归档 crawler、失败源长超时重试策略和手工 CSV 导入页面，覆盖超出当前 RSS 窗口的历史缺口。

每一轮提交前都要重新跑对应后端测试、前端 build，并确认 `docs/00-system-design.md`、本文和相关模块文档没有出现两套口径。

## 15. 不能延期的底线

这些事项如果第一版偷懒，后面会付出很大迁移成本，因此不能延期：

- `raw_items.raw_payload_json` 完整保存原始数据。
- `domain_code`、`visibility_scope`、`sync_policy` 横贯主链路。
- `adoption_status` 只在报告采信层，不放进 `news_items`。
- `daily_report_items` 编辑不覆盖 `generated_news` 和 `raw_items`。
- SQL 导出只从已发布日报采信条目出发。
- 公网和内网登录同源，只替换 `AuthAdapter`。
- adapter 注册机制一开始就存在，不能只写 RSS 特例。
- 数据库不暴露到公网。

## 16. 当前能力与远景差距

当前已经做到“从多源抓取到日报/SQL”的最小闭环，但还没有达到规划部长期运转平台的远景。差距按优先级拆成：

| 差距 | 当前状态 | 下一步交付 | 验收方式 |
| --- | --- | --- | --- |
| 日报生成恢复 | 已支持 MiniMax 单条超时、失败 fallback、推荐 run 生成状态汇总、草稿生成稿重跑和前端状态展示；`2026-05-21` 到 `2026-05-27` 已补齐发布和 SQL；`scripts/import_company_sql_preview_to_reports.py` 可把已校验单日 SQL 预览回填为日报/周报工作台数据 | 后续沉淀为定时任务/运维按钮，减少手工补跑 | 每天自动生成昨天日报，失败条目不会阻塞整天，标准 SQL 只导出 ready |
| 候选池运营 | 前端已展示 winner/loser、重复来源、推荐分、推荐状态、日报采信状态和追溯 ID | 补筛选、采信入口和更清晰的质量治理字段 | 管理员能判断一条日报候选来自哪些源，为什么被推荐 |
| 抓取覆盖率 | 前端已展示 ingestion run 摘要、每源明细、补采窗口统计和目标日 raw/news/winner/recommendation/daily 漏斗 | 补失败源重试、长期覆盖趋势和异常告警 | 能解释“294 个源全启用为什么当天仍只有少量候选” |
| 历史补采 | 已有 `rss_window/paper_api/archive_page/sitemap/manual_import` API、job 和前端入口，可按日期窗口过滤条目入 raw | 补更完整的论文 provider、分页归档 crawler、失败源重试和手工 CSV 页面 | 能补齐超出 RSS 当前窗口的目标日期缺失候选，并说明每源命中情况 |
| SQL 前端 | 前端已能选择已发布日报、生成、预览和下载 SQL | 补复制、字段校验和逐条追溯 | 管理员不进后端也能拿到内网可导入 SQL |
| 周报 | 前后端已能从已发布日报采信条目生成周报候选草稿，前端按一级标签形成周报板块，并支持条目编辑、板块内排序、采信和发布 | 补热度/反馈排序、自动周报正文和周报导出；必要时增加 weekly section 映射层 | 一周日报采信能汇总成周报草稿，管理员能按板块调整采信后发布 |
| 战略闭环 | requirement/task 已有真实 API 页面和审计，insight/source_links 仍需串起来 | 从日报新闻沉淀洞察、影响、需求和指派任务 | 任一内部需求能追溯到外部原始信号 |
| 公网部署 | 本地/Compose 骨架具备 | 生产 Compose、Caddy/Nginx、GitHub Actions SSH 部署 | 云服务器可滚动部署，数据库不暴露公网 |
| 内网适配 | `intranet_header` 已有，IDaaS 仍是计划 | `intranet_oidc` code flow adapter | 公司登录拿到工号/姓名后能映射本地用户 |
| 多环境同步 | 表结构、策略设计和 `sync-runs` 记录页已有 | sync package 导出/导入 | 公网公开信号能同步到内网，敏感数据不回流 |
| 板块扩展 | domain pack 目录和概念已设计 | 硬件/半导体等 domain pack 样例 | 新板块不改主链路即可接入源、标签、评分和导出 |
