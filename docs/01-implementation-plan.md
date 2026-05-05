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

当前实现状态：导入、工作台统一标签策略、adapter 框架和手动 RSS 抓取到 raw 入库的最小链路已完成，抓取调度待继续。`backend/app/adapters/` 已有统一 `SourceAdapter`、RSS adapter 和 wiseflow/page/paper/manual 等骨架；`/api/sources/import-legacy-seeds` 可以导入 113 个旧源；`/api/sources?workspace_code=...` 可以展示共享源池及当前工作台配置；`/api/workspaces/{workspace_code}/label-policy` 可以增删改工作台统一一级/二级标签策略；`planning_intel` 默认 `ai_sql_categories`，`ai_tools` 默认 `ai_tools_categories`；`/api/sources/{source_id}/workspace-link` 可以更新当前工作台对单源的启用状态、权重和日限；`/api/sources/{source_id}/fetch` 可以触发单个 RSS/paper RSS 源抓取并幂等写入 `raw_items`；`workspace_source_links` 会为所有已启用默认工作台建立链接。

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

- `RssFeedAdapter` 可真实抓取。
- `ManualNewsAdapter` 可手工录入。
- `WiseflowReadInfoAdapter` 骨架，接口按旧 `/read_info` 预留。
- `PageListingAdapter` 骨架。
- `PaperMetadataEnricher` 骨架。

验收：

- 数据源导入数量与 contract 的 seed counts 对齐。
- 旧 wiseflow 不被混成 RSS。
- `planning_intel` 和 `ai_tools` 都能看到 113 个共享源链接，其中 79 个启用。
- 单个 RSS 源可以手动触发抓取，首次创建 `raw_items`，重复抓取更新已有 raw 记录而不重复插入。
- 前端首页显示阶段 3，数据源页显示数据源管理能力，并能增删改工作台统一一级/二级标签策略、通过“配置”修改单源启用/权重/日限、通过“抓取”按钮触发单源抓取。
- 新增 source_type 只需注册 adapter。
- adapter 输出满足 `adapter_pipeline.json` 的 raw 字段要求。

## 8. 阶段 4：raw 入库、标准化与去重

目标：把不同来源统一进 `raw_items -> news_items -> dedupe_groups`。

实现：

- 抓取任务写 `raw_items`，完整保存 `raw_payload_json`。
- `normalize_to_news_item(raw_item)` 映射成 `news_items`。
- `canonical_url` 统一规范化。
- `dedupe_key` 在 news 标准层生成。
- 去重发生在 `news_items` 之后、推荐之前。

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

## 9. 阶段 5：推荐、日报草稿和反馈链路

目标：形成可解释推荐，并能进入日报编辑。

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
```

实现：

- 推荐 run 可重跑。
- 推荐只处理 active winner。
- 每日推荐上限默认 15。
- 同源每日上限默认 2。
- 推荐结果写 `recommendation_items`。
- 生成 `generated_news` 作为日报候选。
- 生成 `daily_reports/daily_report_items` 草稿。

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

实现要求：

- 字段映射完全遵守 `config/contracts/news_sql_mapping.json`。
- category 默认兼容 `config/taxonomy/news_categories.json` 的 10 个一级标签。
- `source_url` 必须来自 `news_items.source_url`，不能信任模型生成的 URL。
- 导出任务写 `export_jobs` 和 `export_job_items`。
- 导出文件可下载，且能追溯到 daily item/news/raw/source。

验收：

- 一条日报新闻生成 4 条 SQL，顺序正确。
- 只导出已发布且采信状态为 2 的日报条目。
- SQL 字段和旧系统格式一致。
- 单条 SQL 失败不影响整批审计记录。

## 11. 阶段 7：前端工作台

目标：让主链路变成可操作看板，不做营销首页。

当前实现状态：浅色工作台壳、登录页、用户权限页和数据源管理页已可用。工作台列表与左侧导航已从后端 `workspaces/workspace_sections` 读取，不再前端硬编码；第一版默认不显示工具目录、工具任务、独立热点专题等插件页。数据源页采用信息流式共享源列表，展示共享源池、当前工作台启用数、源类型分布、工作台启用状态和抓取状态；右侧标签面板展示工作台统一一级/二级标签策略。单个源配置只包含启用、权重和日限，不维护标签。

页面顺序：

```text
/login
/dashboard
/sources
/sources/:id
/news
/recommendations
/daily-reports
/daily-reports/:id
/daily-reports/:id/edit
/weekly-reports
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
- 数据源页能看到当前工作台启用 79 个源，并能区分共享源定义和工作台配置。
- `planning_intel` 默认展示旧公司 SQL 兼容的 10 个一级标签；`ai_tools` 默认展示“工具新功能、工具新案例、工具新技术”，且每个一级下有 `cursor/claude code/opencode/codex` 二级标签。
- 数据源页和其他占位页在常见桌面宽度下不应出现横向截断；标签策略不应依赖难发现的内部滚动条。
- 可以触发一次抓取和推荐。
- 可以查看 winner/loser 和推荐原因。
- 可以编辑并发布日报。
- 可以点赞、评分、评论和回复。
- 可以生成并下载公司 SQL。

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

## 14. 第一轮编码任务

下一次开始写代码时，按这个顺序做，不要跳到业务 UI：

1. 创建 `backend/`、`frontend/`、`deploy/` 骨架。
2. 后端实现 `/healthz`、配置读取、数据库连接、Alembic。
3. 前端实现 Vite/Vue/Router/Pinia 基础骨架和登录占位页。
4. Docker Compose 本地启动 PostgreSQL、Redis、backend、frontend。
5. 写最小 CI 或本地验证脚本。
6. 提交前跑通阶段 0 验收命令。

阶段 0 完成后，再进入数据库模型和主链路实现。

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
