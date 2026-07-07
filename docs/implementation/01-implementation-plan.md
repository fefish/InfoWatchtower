# 第一版实现计划

本文是 InfoWatchtower 第一版的施工计划。它不重新定义架构；架构以 `docs/00-system-design.md`、`docs/implementation/implementation-handoff.md` 和 `config/contracts/*.json` 为准。

如果说 `docs/implementation/implementation-handoff.md` 回答“要实现什么”，本文回答“按什么顺序实现、每一步交付什么、怎么验收、什么时候能进入下一步”。

## 1. 文档结构复核结论

当前文档体系已经按“总纲、前端页面、后端模块、部署同步、契约测试、能力地图”分层：

- `docs/00-system-design.md` 是唯一总纲，覆盖愿景、边界、主数据流、登录、部署、同步和 SQL 导出。
- `docs/README.md` 是文档地图和修改同步规则。
- `docs/product/frontend-product-design.md` 是前端页面、顶部栏和用户旅程事实源。
- `docs/backend/backend-module-design.md` 是后端领域模块总图；每个一级模块必须有专题事实源。
- `docs/backend/contract-test-governance-design.md` 是 contract、schema、前后端测试、假控件拦截和 CI 门禁事实源。
- `config/contracts/*.json` 是机器契约，覆盖字段、adapter、SQL、登录、扩展点和同步。

本文只回答“按什么顺序施工、每一步交付什么、怎么验收”，不再补充新的目标架构。

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
- paper_rss/paper_page 骨架；paper_api 已有 arXiv v1、OpenAlex Works v1 和 Semantic Scholar bulk search v1，后续扩展更多论文 provider。
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
- `oidc`

API：

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/users
GET  /api/roles
PATCH /api/users/{id}/roles
GET  /api/identity/permission-changes
POST /api/identity/permission-rollbacks
```

验收：

- 公网模式下用户名密码能登录。
- 内网模式下可信 header 自动 provision 用户。
- 业务代码只使用本地 `user_id`、角色和权限。
- 角色至少有 `super_admin`、`editor_admin`、`analyst`、`viewer`。
- 登录、登出、授权变更写 `audit_logs`；权限变更可解释 diff，并可受保护地回滚上一版。

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
GET  /api/identity/permission-changes
POST /api/identity/permission-rollbacks
```

后续加固计划：

- 公网部署前持续验证 CSRF、HTTPS Secure Cookie 和默认密码禁用。
- 保留真实 OIDC provider 登录、建号、membership 和登出验收证据。
- 后续如需 `intranet_oidc` 或 SAML，仍通过 `ExternalIdentity` 接入工号、姓名、部门和邮箱。
- 保持所有外部身份只映射到 `ExternalIdentity`，业务层继续只认本地 `user_id` 和 `roles`。

## 7. 阶段 3：数据源导入与 adapter 框架

目标：旧种子源进入数据库，adapter 注册机制固定。

前置调整：工作台模型按共享主链路收束。`workspaces/workspace_sections/workspace_memberships` 管工作范围、页面和权限；`workspace_source_links` 管工作台启用哪些共享数据源；`domain_code` 继续只表达情报主题板块。

当前实现状态：导入、工作台统一标签/新闻结构策略、adapter 框架、RSS/paper RSS/arXiv paper API/OpenAlex paper API/Semantic Scholar paper API/page_manual/page_monitor 抓取到 raw 入库、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口已完成。`backend/app/adapters/` 已有统一 `SourceAdapter`、RSS adapter、页面源 adapter、arXiv/OpenAlex/Semantic Scholar paper API adapter；wiseflow/crawler/csv/paper_page/manual/internal 等 stub adapter 已显式返回 `skipped_unimplemented`，不再显示成功 0 条；`/api/sources/import-legacy-seeds` 可以导入旧 113 个种子源和 `information_source_registry_20260511.csv` 补充台账，361 条导入记录按 URL 去重后形成 294 个共享源，规划部工作台 v1 默认全部启用；`/api/sources/import-tech-insight-loop` 可以导入 `sources_full_zh.csv` 的 386 行 Tech Insight Loop 源治理记录，355 行有入口、31 行待补入口，去重后形成 363 个共享源，并把源等级、渠道类型、专家路由、板块相关度和评分拆解保存为源侧 metadata；`/api/sources?workspace_code=...` 可以展示共享源池及当前工作台配置；`/api/workspaces/{workspace_code}/label-policy` 可以增删改工作台统一新闻一级/二级标签策略，并返回/保存 `news_format_code`、`export_category_mode` 与 `required_content_fields`；`planning_intel` 默认 `ai_sql_categories + company_sql_v1 + news_primary`，`ai_tools` 默认 `ai_tools_categories + tool_intel_v1`；数据源侧方向标签来自 `planning_source_tags/source_tags.json`，只用于源管理和评分先验；`/api/sources/{source_id}/workspace-link` 可以更新当前工作台对单源的启用状态、权重和日限；`/api/sources/{source_id}/fetch` 可以触发单个 RSS/paper RSS/paper_api/page_manual/page_monitor 源抓取并幂等写入 `raw_items`；`/api/ingestion/runs` 可以按工作台创建同步执行的抓取 run，默认处理该工作台已启用的 `rss/paper_rss/page_manual/page_monitor/wiseflow` 源并写入 `ingestion_runs` 摘要；抓取 run 支持并发池和单源超时，默认 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`；完整日报流水线通过 `/api/pipeline/daily-runs` 默认覆盖同一套全量源类型。scheduler 可按环境变量定时把每日完整流水线入队给 worker 执行，默认关闭自动任务；`workspace_source_links` 会为规划部工作台建立全量启用链接。

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
- 可以创建工作台级 ingestion run，run 记录 source 成功/失败、拉取数、raw 新增数和 raw 更新数；`limit` 必须为空或大于 0，`limit=0` 返回 422，筛选不到启用源时 run 状态为 `no_sources`。
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
- `docs/reference/data-examples.md` 中的 RSS 样例能转成 news item。
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

当前实现状态：浅色工作台壳、登录页、用户权限页、数据源管理页、候选池页、推荐运行页、抓取覆盖率页、周报页、历史归档页、实体大事记页、质量归档页、SQL 导出页、需求页、任务页、同步运行页、审计页、数据源详情页和日报详情/编辑路由已可用。工作台列表与左侧导航已从后端 `workspaces/workspace_sections` 读取，不再前端硬编码；第一版默认不显示工具目录、工具任务、独立热点专题等插件页。数据源页采用参考高保真风格的信息流式共享源列表，展示共享源池、当前工作台启用数、源类型分布、工作台启用状态和抓取状态，已补 Tech Insight Loop 源等级、渠道类型、专家路由、质量分和待补入口状态；右侧标签面板用一级/二级/新闻结构 tab 管理工作台统一策略。单个源配置只包含启用、权重和日限，不维护标签。候选池页接入 `GET /api/dedupe-groups` 和 `GET /api/news-items`，展示 winner、重复来源、来源排序、推荐分、准入等级、噪声/剔除原因、推荐状态、日报采信状态和追溯 ID；推荐运行页接入 `GET/POST /api/recommendation/runs`，展示分数拆解、结构化准入字段和是否进入日报；抓取覆盖率页接入 `GET/POST /api/ingestion/runs`、`POST /api/ingestion/backfill-runs`、`POST /api/ingestion/manual-import-preview` 和 `GET /api/ingestion/coverage`，支持常规抓取、`rss_window/paper_api/archive_page/sitemap/manual_import` 补采、manual_import CSV/SQL 上传或粘贴、后端预览、错误报告、目标日覆盖漏斗和每源链路详情；SQL 导出页接入 `GET /api/daily-reports`、`GET /api/exports`、`POST /api/exports/company-sql/daily-reports/{daily_report_id}/preflight`、`POST /api/exports/company-sql/daily-reports/{daily_report_id}`、`GET /api/exports/{export_job_id}/download` 和 `GET /api/exports/{export_job_id}/trace`，支持预检、截断预览保护、复制预览、服务端流式下载和 trace 锚点。日报页采用 brief 列表 + 详情处理弹窗，避免正文和处理区互相遮挡，并支持生成稿 ready/fallback 状态展示和草稿重跑。周报页接入 `GET/POST /api/weekly-reports`、发布和条目编辑 API，支持从已发布日报采信项生成候选草稿，并按成品新闻一级标签形成周报板块；默认只展示板块统计、短摘要和采信动作，五段正文只在编辑态出现。历史归档页接入 `GET /api/historical-reports/summary`、`GET /api/historical-reports`、`GET /api/historical-reports/{id}`、`GET /api/legacy-import/summary` 和 `GET /api/legacy-import/gaps`，只读展示旧日报/周报正文、筛选条件、导入覆盖率和引用解析缺口，并支持从旧报告转需求。实体大事记页接入实体列表、事件详情、旧引用解析、当前事件编辑/确认/撤销和转需求。质量归档页接入 `GET /api/quality-archive/summary`、`GET /api/historical-feedback-items` 和 `GET /api/historical-job-runs`，只读展示旧反馈、质量反馈、旧任务统计和反馈引用缺口，并支持管理员把单条历史反馈转为 requirement 来源。需求、任务、同步和审计页面已从模块化路线页升级为真实 API 页面；同步页已展示 failed inbox 告警、对象分布、本地重放重试入口和自动 backoff 到期/阻塞状态。

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

以上页面不再落入通用 `PlaceholderPage`。`/weekly-reports`、`/requirements`、`/tasks`、`/sync`、`/audit-logs` 已是真实 API 页面；其中 `/sync` 已接入同步包导出/下载/导入、feed/pull 运行、同步健康、水位/失败告警、立即拉取和冲突处置 UI。

## 12. 阶段 8：同步、部署和自动发布

目标：公网可部署，内网可复用同一套代码。

实现：

- `deploy/docker-compose.prod.yml`。
- Caddy 或 Nginx 反向代理。
- PostgreSQL 数据卷不暴露公网端口。
- Redis 不暴露公网端口。
- `.env.production` 放服务器，不进 Git。
- GitHub Actions 通过 SSH 部署。
- `sync_outbox/sync_inbox/sync_runs/sync_conflicts` 骨架和 `sync_cursors` 水位。
- 公网导出同步包，内网导入同步包；机器同步主线走 extranet feed / intranet pull。
- failed `sync_inbox` 保存可重放 envelope，并可通过 `POST /api/sync/inbox/retry-failed` 本地重试。

验收：

- 单台服务器 Docker Compose 能启动完整系统。
- `80/443` 可访问网站。
- `/healthz` 可被部署脚本检查。
- `postgres:5432` 只在 Docker 内网访问。
- 同步包不包含 token、cookie、password、secret、authorization、api_key、`.env`、
  client_secret、session 等 secret-like 字段。
- 审计详情不保存 secret-like 原值，只保存 `[REDACTED]`。
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
- SQL 导出前 preflight、字段长度、URL 和 HTML 污染校验。
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
- 融合迁移基线：`scripts/tech_insight_loop_inventory.py` 已只读盘点旧 SQLite，确认 14834 条素材、66 份报告、23 个实体、275 条实体大事记、反馈和旧任务记录；`scripts/tech_insight_loop_legacy_dry_run.py` 已生成历史素材/报告导入 dry-run，确认 14834 条素材可归档、58 份 daily/weekly 报告可归档、报告引用 2773 个中 30 个缺口；`scripts/tech_insight_loop_legacy_import.py` 已提供默认 no-write、`--execute` 才写库的真实导入脚本，旧素材进入禁用的 `legacy_tech_insight_loop` 档案源和 `raw_items.raw_payload_json.legacy_tech_insight_loop`，旧报告进入 `historical_reports`，不进入当前推荐、日报和公司 SQL；`tracked_entities/entity_milestones` 归档模型、`scripts/tech_insight_loop_entity_import.py` 和 `/entity-milestones` 已提供旧实体/大事记导入与查看能力，旧引用缺口写入 `metadata_json.legacy_refs`；旧导入事件只读，当前日报/周报条目登记出的实体事件支持编辑、确认、撤销和转 requirement 来源；`historical_feedback_items/historical_job_runs` 归档模型、`scripts/tech_insight_loop_quality_import.py` 和 `/quality-archive` 页面已提供旧反馈、质量反馈和旧任务统计导入/查看能力，管理员可把历史反馈登记为 requirement 来源，但不创建当前评论/评分或当前抓取任务；`GET /api/legacy-import/summary`、`GET /api/legacy-import/gaps` 和 `/historical-reports` 顶部验收面板已提供导入覆盖率、未解析引用和缺口样例查看；`scripts/tech_insight_loop_import_verify.py` 已提供 check-only、小批量执行和全量确认执行的统一验收报告，历史反馈和旧任务归档通过 `--include-quality-archive` 显式纳入。
- 可观测：`/ingestion-runs` 已展示常规抓取、多模式补采、每源覆盖统计和目标日 raw/news/winner/recommendation/daily 漏斗；`/news` 已展示候选推荐分、推荐状态、日报采信状态和追溯 ID。
- 内容运营：日报已支持 brief 列表、详情弹窗、采信、编辑、点赞、评分、评论和生成稿重跑；已校验单日公司 SQL 预览可以回填为完整追溯链路的已发布日报；周报 v1 已支持从已发布日报采信项生成候选、按一级标签分板块、条目采信/剔除、排序、编辑和发布。
- 管理页面：数据源、推荐运行、SQL 导出、用户权限、需求、任务、历史归档、实体大事记、质量归档、同步和审计均已从占位页升级为真实 API 页面。
- 自动化：scheduler 可按北京时间固定触发每日完整流水线，生产推荐每天早上生成昨天日报。

下一轮编码按这个顺序做：

1. Tech Insight Loop 历史归档执行验收：配置真实数据库 `DATABASE_URL` 后，先跑 `python3 scripts/tech_insight_loop_import_verify.py --execute --article-limit 20 --report-limit 5 --entity-limit 5 --milestone-limit 20` 小批量；如需同步验收历史反馈和旧任务，加 `--include-quality-archive --feedback-limit 4 --quality-feedback-limit 4 --job-limit 10`；再跑 `--execute --confirm-full-import` 全量。用输出报告、`GET /api/legacy-import/summary`、`GET /api/legacy-import/gaps`、`/historical-reports` 顶部验收面板和 `/quality-archive` 核对覆盖率、未解析报告/反馈引用、旧任务失败原因和跳过原因。
2. Tech Insight Loop 实体大事记执行验收：同一验收脚本会在历史导入后执行实体/事件导入；也可用原子脚本 `scripts/tech_insight_loop_entity_import.py --execute` 单独重跑，并用导入验收面板和 `/entity-milestones` 核对实体事件覆盖率、未解析旧引用和跳过原因。
3. 部署和登录安全：已补公网登录限流、默认密码治理、通用 OIDC code flow + PKCE、公司内网 header 登录、生产 Compose 和反向代理配置；后续只需按具体企业 IDaaS claims 做字段适配并留真实 provider 证据。
4. 公网/内网同步骨架：当前已有 feed/pull、同步包导出/导入、下载、幂等导入、open conflict 查询和人工处置；下一步补 `use_incoming/manual_merge` 对象级合并器和端到端实机证据。
5. SQL 导出深化：导出前 preflight、字段长度、URL、HTML 污染校验、SQL trace、trace 字段来源详情、trace 字段差异预览、导入回执、失败语句反馈、service token importer 回调、服务端流式下载端点、viewer 下载禁用、预览复制、截断预览保护和批量 manifest 已补；下一步补真实内网平台生产联调证据。
6. 周报增强：当前周报 v1 管理采信项和板块；下一步补热度/反馈排序、自动周报正文、周报导出和必要的 weekly section 映射。
7. 战略闭环深化：当前已有 insights、strategic implications、requirements、topic tasks 的列表/创建/状态更新和审计；insight/implication 独立管理 v1 已能在 `/insights` 创建、编辑、确认/归档洞察并管理战略影响；requirement source links v1 已能从 daily/weekly report item、entity milestone、historical report、historical feedback、news 或 raw 追溯外部信号，并在 `/requirements` 展示。report item strategy loop v1 已能从日报/周报条目沉淀 insight、implication、requirement 和可选 task，并在 `/tasks` 展示 requirement/source trace；task owner view v1 已支持我的/逾期/阻塞视图和 blocked reason 提交；task batch update v1 已支持 `POST /api/topic-tasks/batch` 批量处理状态和阻塞原因；task detail v1 已支持 `GET /api/topic-tasks/{id}` 和 `/tasks` 详情抽屉；sync boundary v1 已验证 requirements/topic_tasks 不进入 extranet feed；requirement feedback to recommendation v1 已把需求结论写入可审计 `EditorialAction` 并进入推荐 `feedback_score`。下一步补跨对象联动体验和更多协作对象解释关系。
8. 历史补采深化：arXiv paper_api v1、OpenAlex Works paper_api v1、Semantic Scholar bulk search paper_api v1、manual_import CSV/SQL 上传或粘贴、后端预览、错误报告、覆盖趋势 v1、失败源自动重试队列 v1 和站内告警投递 v1 已补；下一步补 OpenReview 等论文 provider、分页归档 crawler、邮件/外部告警通道、复杂 SQL dialect 和大文件分片，覆盖超出当前 RSS 窗口的历史缺口。

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
| 抓取覆盖率 | 前端已展示 ingestion run 摘要、每源明细、补采窗口统计、失败源手动重试、失败源自动重试策略、目标日 raw/news/winner/recommendation/daily 漏斗、近 14 日覆盖趋势、Top 失败源和站内告警通知 | 补邮件/外部告警通道、生产 runbook 和更长周期趋势分析 | 能解释“294 个源全启用为什么当天仍只有少量候选”，并能看到最近是否持续失败或持续 0 产出 |
| 历史补采 | 已有 `rss_window/paper_api/archive_page/sitemap/manual_import` API、job、前端入口、manual_import CSV/SQL 上传或粘贴、后端预览、错误报告下载、arXiv submittedDate 日期窗口 provider、OpenAlex publication_date 日期窗口 provider、Semantic Scholar publicationDateOrYear 日期窗口 provider、非 `manual_import` 失败源手动/自动重试和站内告警，可按日期窗口过滤条目入 raw | 补 OpenReview 等论文 provider、分页归档 crawler、邮件/外部告警通道、复杂 SQL dialect 和大文件分片 | 能补齐超出 RSS 当前窗口的目标日期缺失候选，并说明每源命中情况 |
| SQL 前端 | 前端已能选择已发布日报、运行预检、生成、截断预览保护、复制预览、服务端下载 SQL、查看 trace 锚点、字段来源、字段差异预览、登记导入回执、展示 importer 回调 endpoint 并生成批量 manifest | 补真实内网平台生产联调证据 | 管理员不进后端也能拿到内网可导入 SQL，并能把导入结果追溯回导出任务 |
| 周报 | 前后端已能从已发布日报采信条目生成周报候选草稿，前端按一级标签形成周报板块，并支持条目编辑、板块内排序、采信和发布 | 补热度/反馈排序、自动周报正文和周报导出；必要时增加 weekly section 映射层 | 一周日报采信能汇总成周报草稿，管理员能按板块调整采信后发布 |
| 战略闭环 | insight/implication 独立管理、requirement/task 页面和审计已落地，requirement source links v1 已能追溯 daily/weekly report item、entity milestone、historical report、historical feedback、news 和 raw；report item strategy loop v1 已能从日报/周报条目沉淀 insight、implication、requirement 和可选 task，任务列表可回链到来源；task owner view v1 已补我的/逾期/阻塞视图和 blocked reason；task batch update v1 已补批量状态/阻塞原因处理；task detail v1 已补详情 API 和 `/tasks` 抽屉；sync boundary v1 已补内网 requirement/task 不进 feed 的负向验收；requirement feedback to recommendation v1 已进入推荐反馈分 | 补跨对象联动体验和更多协作对象解释关系 | 任一内部任务能追溯到 requirement 和外部原始信号；洞察和需求结论能进入可审计的后续反馈链 |
| 公网部署 | 本地/Compose 骨架具备 | 生产 Compose、Caddy/Nginx、GitHub Actions SSH 部署 | 云服务器可滚动部署，数据库不暴露公网 |
| 内网适配 | `intranet_header` 已有，IDaaS 仍是计划 | `intranet_oidc` code flow adapter | 公司登录拿到工号/姓名后能映射本地用户 |
| 多环境同步 | 表结构、策略设计和 `sync-runs` 记录页已有 | sync package 导出/导入 | 公网公开信号能同步到内网，敏感数据不回流 |
| 板块扩展 | domain pack 目录和概念已设计 | 硬件/半导体等 domain pack 样例 | 新板块不改主链路即可接入源、标签、评分和导出 |

## 17. 第三轮实施工作包（2026-07-07 设计定稿 → 全量实现）

2026-07-07 设计轮（自动化/生成轨道 + 体验系统轨道）已把三大后端能力和五项体验能力
按实现级规格定稿（见 `docs/architecture/capability-map.md` §4.3 汇总表），本章把
它们拆成可并行领取的实施工作包。规则：

- 每个 WP 的唯一验收基准是「设计事实源 §号 + 契约键」，不得实现成与设计有出入的
  "看起来可用"版本；实现后把 `api-and-ui-implementation.md` 待实现端点块移入已实现表、
  把 capability-map §4.3 对应行移入 §4.1、把 page-specs 对应「未做」改「已做」。
- 契约状态位同步：实现落地时把对应 contract 里的
  `design_final_pending_implementation` 状态改为实现事实（如
  `deployment_modes.json` `planned_startup_failfast_rules` 条目移入
  `startup_failfast_rules`、`notifications.json` `planned_event_types` 移入
  `implemented_event_types_v1`）。
- 公共门禁（每个 WP 提交前必跑）：

```bash
cd backend && .venv/bin/python -m pytest -q        # 严禁在仓库根跑
cd frontend && npx vitest run && npm run build
python3 scripts/validate_docs_governance.py
python3 scripts/validate_frontend_controls.py
for f in config/contracts/*.json; do python3 -m json.tool "$f" > /dev/null; done
git diff --check
```

### WP3-A 工作台级调度策略 + run 级自动重试 + 调度心跳（后端）

- 范围：`schedule_policy` 读写 API（校验/审计/resolved 预览）；scheduler 60s tick
  per-workspace 触发与兼容规则；pipeline run 重试链字段（attempt/retry_of_run_id/
  next_retry_at）与 backoff 自动重试（partial 不触发、error_code 可重试分类、
  superseded 让位、耗尽通知 `ingestion.pipeline_retry_exhausted`）；
  `scheduler_heartbeats` 表与 `GET /api/pipeline/scheduler/status`；
  新 env `SCHEDULER_MISSED_WINDOW_SECONDS`。
- 事实源/契约：`docs/backend/pipeline-jobs-design.md` §3.1/§6.1-§6.2/§8；
  `config/contracts/workspace_model.json` `schedule_policy`；
  `config/contracts/notifications.json` `planned_event_types`。
- 文件域：`backend/app/workers/scheduler.py`、`backend/app/workers/worker.py`、
  `backend/app/api/routes/pipeline.py`、`backend/app/api/routes/workspaces.py`、
  `backend/app/models/`（run 字段 + 心跳表）、`backend/alembic/versions/`、
  `backend/app/core/config.py`、`backend/tests/`（新增调度策略/重试链/心跳测试）。
- 验收：pipeline-jobs-design §12「分层调度与 run 级重试」断言 1-10 全部有对应
  pytest；兼容回归（无策略工作台行为与现状字节一致）必须有专门用例。

### WP3-B 生成 provider 分层配置 + 连通性自检（后端）

- 范围：`GENERATION_*` env 族与 `MINIMAX_*` 逐字段兼容回退；启动 fail-fast 两条
  规则落 `deploy_checks.py`（同步契约状态位）；`generation_policy` 读写 API
  （resolved 状态、secret-like 422、审计）；`POST /api/generation/ping` 分类报错；
  `daily_generation_budget` 与 `fallback_behavior=fail` 语义。
- 事实源/契约：`docs/backend/generation-provider-design.md`；
  `config/contracts/workspace_model.json` `generation_policy`；
  `config/contracts/deployment_modes.json` `planned_startup_failfast_rules`/`related_env`。
- 文件域：`backend/app/llm/`（provider client 参数化）、`backend/app/core/config.py`、
  `backend/app/core/deploy_checks.py`、`backend/app/api/routes/`（generation-policy/
  ping）、`backend/tests/`。
- 验收：generation-provider-design §7 断言 1-8 全绿；仅配 `MINIMAX_*` 时现有生成/
  降级测试不改仍绿；任何 API 响应/审计 detail grep 不到 key。

### WP3-C 模板驱动生成 generation_template（后端）

- 范围：`report_formats.generation_template(+_source)` 列与迁移；JSON/XML 安全解析
  到规范形；投影/增量判定算法；`validate-template` 干跑 API；增量字段生成写
  `generated_news.template_extras_json`；rendition/MD/HTML 按模板投影；
  `template_fallback` 降级与 `regenerate` 补齐；weekly 同机制。
- 事实源/契约：`docs/backend/reports-editorial-design.md` §8.1、
  `docs/backend/report-renditions-design.md` §10；
  `config/contracts/report_renditions.json` `generation_template`。
- 文件域：`backend/app/models/`、`backend/alembic/versions/`、
  `backend/app/reports/renditions.py`、`backend/app/reports/rendition_html.py`、
  `backend/app/api/routes/reports.py`、生成链路模块、`backend/tests/`。
- 验收：report-renditions-design §10.7 断言 1-10 全绿；
  `scripts/validate_company_sql.py` 基准通过且模板任意配置下公司 SQL 逐字节不变
  （负向断言必须有用例）。依赖：预算/降级语义依赖 WP3-B 的 `generation_policy`
  （可先按无预算实现，接口留位）。

### WP3-D 布局模板与间距系统 + Dashboard 重排（前端）

- 范围：`base.css` `:root` spacing tokens 与统一页面容器；四布局模板落地与逐页
  收敛；`/dashboard` 按主列+固定侧栏重排（含源健康折叠态）；清理业务卡片
  `position: fixed/absolute` 与重复布局定义。
- 事实源：`docs/product/frontend-product-design.md` §9、
  `docs/product/page-specs/frontend-page-specs.md` §1.1/§3/§4.1。
- 文件域：`frontend/src/styles/base.css`、`frontend/src/pages/DashboardPage.vue`
  及各业务页容器层、`frontend/src/pages/*.spec.ts`。
- 验收：产品设计 §9.5 断言全绿；DashboardPage 组件测试覆盖分区归属与源健康
  折叠/展开；`npm run build` 通过。调度心跳卡（侧栏第 6 位）归 WP3-H，本 WP 不做。

### WP3-E 统一弹窗系统迁移（前端）

- 范围：居中 Modal 基座组件化（尺寸档位/遮罩/Esc/焦点圈定/脏表单确认/移动端全屏）；
  迁移 4 处弹层（建台向导、发现工作台、新增信息源、导入预览）；单源配置与格式管理
  正式化为上下文面板；`scripts/validate_frontend_controls.py` 按 `modal_rule`
  扩展扫描。
- 事实源/契约：`docs/product/frontend-product-design.md` §10、
  `docs/product/page-specs/frontend-page-specs.md` §3.1；
  `config/contracts/frontend_control_governance.json` `modal_rule`。
- 文件域：`frontend/src/components/`（Modal 基座）、`frontend/src/layouts/AppShell.vue`、
  `frontend/src/components/WorkspaceDiscovery.vue`、`frontend/src/pages/SourcesPage.vue`、
  `frontend/src/styles/base.css`、`scripts/validate_frontend_controls.py`、组件测试。
- 验收：产品设计 §10.4 断言全绿；`python3 scripts/validate_frontend_controls.py`
  含 modal_rule 扫描通过（config-panel 只剩白名单 2 处）。

### WP3-F 账号资料自助编辑（前后端）

- 范围：`PATCH /api/auth/me`（本地账号三字段、外部身份 400、游客 403、
  must_change_password 白名单不变、审计 `auth.profile.update`）；`/account`
  「资料」卡（本地可编辑、外部只读说明、保存后刷新胶囊）。
- 事实源/契约：`docs/backend/identity-access-design.md` §4.4、产品设计 §11、
  page-specs §25；`config/contracts/auth_modes.json` `profile_self_service`。
- 文件域：`backend/app/api/routes/auth.py`、`backend/app/schemas/auth.py`、
  `backend/tests/test_auth.py`（或新增）、`frontend/src/pages/AccountPage.vue`
  及 spec、`frontend/src/stores/session.ts`。
- 验收：identity-access-design §4.4 验收清单全绿（前后端各有测试）。

### WP3-G 发现搜索 + 工作台加入码（前后端）

- 范围：`discover?q=` 过滤；`workspace_join_codes` 表/迁移；join-code 三端点 +
  `join-by-code`（幂等不降级、统一失效 400、限流 429、四类审计动作）；
  发现工作台 Modal 的搜索框与凭码加入区（依赖 WP3-E 的 Modal 迁移，可先在现有
  抽屉内落功能）；`/workspace-settings`「可见性与加入码」卡（含 visibility 切换
  影响确认）。
- 事实源/契约：`docs/backend/workspace-configuration-design.md` §14、产品设计 §12、
  page-specs §19.5；`config/contracts/workspace_model.json`
  `join_code`/`discovery_and_subscription`、`config/contracts/auth_modes.json`
  `identity_audit_actions`。
- 文件域：`backend/app/api/routes/workspaces.py`、`backend/app/models/`、
  `backend/alembic/versions/`、`backend/tests/`、
  `frontend/src/components/WorkspaceDiscovery.vue`、
  `frontend/src/pages/WorkspaceSettingsPage.vue` 及 spec。
- 验收：workspace-configuration-design §14.4 验收清单全绿（含防枚举与限流用例）。

### WP3-H 工作台配置中心「自动化」「生成模型」卡 + 调度心跳卡（前端）

- 范围：`/workspace-settings` 自动化卡（读写 schedule-policy、生效值来源标注、
  下次运行预览、总闸关闭只读态）与生成模型卡（读写 generation-policy、key 只显
  已配置/未配置、测试连通按钮）；`/dashboard` 侧栏第 6 位调度心跳卡与
  `/ingestion-runs` 调度卡升级（读 scheduler/status，心跳 stale 渲染离线态）。
- 事实源：pipeline-jobs-design §8.4-§8.5、generation-provider-design §5、
  page-specs §4.1/§7.3/§19.5。依赖：WP3-A、WP3-B 的 API 先行。
- 文件域：`frontend/src/pages/WorkspaceSettingsPage.vue`、
  `frontend/src/pages/DashboardPage.vue`、`frontend/src/pages/IngestionRunsPage.vue`、
  `frontend/src/api/`、对应 spec。
- 验收：page-specs §19.5.4/§4.4 括注的实施后测试看护全绿；失败/离线态不得渲染
  成功绿色（假成功回归）。

### 并行与依赖关系

```text
WP3-A ──┐
        ├─→ WP3-H（依赖 A/B 的 API）
WP3-B ──┤
        └─→ WP3-C（预算/降级语义依赖 B，可留位先行）
WP3-D、WP3-E、WP3-F 完全独立可并行
WP3-G 的 Modal 落位依赖 WP3-E（功能可先行）
```

契约共享文件（`workspace_model.json` 被 A/B/G 同时修改状态位）合并时以
capability-map §4.3 行的迁移为准，避免互相覆盖。
