# 开发启动说明

本文说明当前工程骨架如何本地运行。业务实现顺序仍以 `docs/implementation/01-implementation-plan.md` 为准。

## 1. 当前状态

当前已完成阶段 0、阶段 1、阶段 2、阶段 3、阶段 4 和阶段 5 可回填闭环：

- 后端 FastAPI 骨架。
- `/healthz` 健康检查。
- SQLAlchemy 业务模型。
- Alembic 初始迁移。
- 前端 Vue/Vite 工作台骨架。
- 本地和生产 Docker Compose 草案。
- GitHub Actions CI 草案。
- PostgreSQL 中已能创建 40 张业务表。
- 测试已覆盖 `daily_report_items -> generated_news -> recommendation_items -> dedupe_group_items -> news_items -> raw_items.raw_payload_json` 追溯链路。
- 登录已接入 `local/public_password/oidc/intranet_header`，本地开发账号为 `admin/password`。
- 部署形态由 `DEPLOY_MODE`（standalone/cloud/intranet/extranet）派生能力开关，
  本地默认 standalone；本地模拟其他形态见 §4.1。
- 用户权限页面已能读取用户、读取角色并保存用户角色。
- 公网安全和 SSO 后续计划见 `docs/deployment/auth-security-roadmap.md`。
- 工作台模型按共享主链路实现；工作台列表来自 `workspaces`，页面来自 `workspace_sections`，所有工作台共享数据源管理、候选池、日报、周报和导出能力。差异配置通过 `workspaces.config_json.label_policy` 的工作台统一一级/二级标签策略、`workspace_source_links` 的源启用/权重/日限和可选插件模块完成。
- 阶段 3 已有共享数据源导入 API、数据源页面、工作台统一标签策略 API、工作台源链接配置 API、工作台级 ingestion run API、多模式历史补采 API、Redis/RQ worker + scheduler 调度入口、adapter registry、RSS/paper RSS/page_manual/page_monitor/arXiv-OpenAlex-Semantic Scholar paper API/wiseflow/crawler/csv/paper_page/manual/internal 全部 11 类 source_type 真适配器（run 层保留 `skipped_unimplemented` 显式语义作为未来未实现 adapter 的安全网）；旧种子源导入后会为所有已启用默认工作台创建源链接；RSS/paper RSS/paper_api/page_manual/page_monitor 源可通过手动 API 抓取并幂等写入 `raw_items`，也可通过 ingestion run 按工作台批量触发；ingestion run 支持 `concurrency` 和 `source_timeout_seconds`，默认并发 8、单源 25 秒超时；历史补采支持 `rss_window/paper_api/archive_page/sitemap/manual_import`，其中 `paper_api` 可走 arXiv submittedDate、OpenAlex publication_date 或 Semantic Scholar publicationDateOrYear 日期窗口，`manual_import` 已支持前端 CSV/SQL 上传或粘贴、`POST /api/ingestion/manual-import-preview` 后端预览、0 accepted 阻断和错误报告下载。前端已切到浅色工作台壳、数据库驱动导航、信息流式数据源列表和紧凑工作台标签策略面板。
- 阶段 4 已有 raw 到 news 标准化与硬去重 API：`POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups`。同一共享 raw 可以被不同工作台各自标准化；去重组按 `workspace_code + dedupe_key` 隔离；winner/loser 会回写到 `news_items.active` 和 `duplicate_of_id`。
- 阶段 5 已有按日期回填的完整流水线、推荐 run、可解释推荐分、可选 MiniMax `generated_news`、日报草稿、发布、条目编辑和点赞/评分/评论最小 API；MiniMax 单条默认 45 秒超时，失败会落到 `fallback_needs_review` 并可在草稿日报重跑生成稿；前端 `/daily-reports` 可选择日期并触发完整流水线，支持正文展示、采信切换、编辑、点赞、评分、评论、追溯查看和生成状态展示；scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿。

业务流程 API 当前已具备：候选池、日报、周报、SQL 导出、需求、任务、同步运行和审计页面。后续重点是候选池增强、SQL 逐条追溯、完整同步包导出/导入和生产部署硬化。

## 2. 后端本地运行

建议使用 Python 3.11+。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
DATABASE_URL="" pytest
DATABASE_URL="" uvicorn app.main:app --reload
```

访问：

```text
http://localhost:8000/healthz
```

如果要连接 PostgreSQL，把 `DATABASE_URL` 指向本地或 Compose 里的数据库。

## 3. 前端本地运行

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://localhost:5173
```

Vite 会把 `/healthz` 和 `/api` 代理到 `http://localhost:8000`。

如果前端跑在 Docker Compose 里，`deploy/docker-compose.local.yml` 会设置：

```text
VITE_API_PROXY_TARGET=http://backend:8000
```

这是因为容器内的 `localhost` 指向前端容器自己，不是后端容器。

## 4. Docker Compose

本机已经配置 Docker Compose plugin 后，可以直接用：

```bash
make up
make migrate
```

首次构建或改过 Dockerfile/依赖时：

```bash
make build
```

查看容器：

```bash
make ps
```

查看日志：

```bash
make logs
```

等价原生命令：

```bash
docker compose -f deploy/docker-compose.local.yml up --build
```

日常开发不要每次都加 `--build`。改普通 Python/Vue 代码后，优先用 `make up` 或 `make restart`。

WSL2 建议把仓库放在 Linux 文件系统内，例如 `~/projects/InfoWatchtower`，不要放在 `/mnt/c/...`，否则前端热更新和 `node_modules` 会明显变慢。

## 4.1 部署形态本地联调（DEPLOY_MODE / runtime meta / CSRF / sync feed）

四种部署形态是同一套代码（契约 `config/contracts/deployment_modes.json`，规格
`docs/deployment/deployment-topology.md`）。本地开发默认 `DEPLOY_MODE=standalone`
（CSRF 默认关）；以下是不起 Docker 的最小联调方式。

验证 runtime 能力下发与形态自检：

```bash
cd backend
DATABASE_URL="" DEPLOY_MODE=cloud AUTH_MODE=public_password \
  AUTH_SESSION_SECRET=dev-secret \
  .venv/bin/uvicorn app.main:app --port 8000

curl -s http://127.0.0.1:8000/api/meta/runtime   # deploy_mode/capabilities/auth_mode
curl -s http://127.0.0.1:8000/readyz             # 就绪探针：数据库失联时 503

# 非法组合应直接拒启（fail-fast），例如公网形态配 header 登录：
DATABASE_URL="" DEPLOY_MODE=cloud AUTH_MODE=intranet_header \
  AUTH_SESSION_SECRET=dev-secret .venv/bin/uvicorn app.main:app --port 8001
# → RuntimeError: DEPLOY_MODE=cloud requires AUTH_MODE in [public_password, oidc]
```

验证 CSRF 行为（cloud/intranet/extranet 默认开启，standalone 默认关闭）：

```bash
# DEPLOY_MODE=cloud 下：登录后未带 X-CSRF-Token 的 POST 应 403 {"code":"csrf_failed"}
# 登录响应会下发非 HttpOnly 的 infowatchtower_csrf cookie；
# 前端统一 http client（frontend/src/api/http.ts）对 unsafe 方法自动附头。
curl -s -c /tmp/iw.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"password"}' http://127.0.0.1:8000/api/auth/login
curl -s -b /tmp/iw.txt -X POST http://127.0.0.1:8000/api/sync-runs -d '{}' \
  -H 'Content-Type: application/json'          # → 403 csrf_failed
```

本地起 extranet publisher + intranet consumer 两个实例联调 sync feed/pull：

```bash
# 实例 A（publisher，端口 8000）：
DATABASE_URL=<pgA> DEPLOY_MODE=extranet AUTH_MODE=public_password \
  AUTH_SESSION_SECRET=dev-secret SYNC_SERVICE_TOKENS=intranet-a:dev-token \
  .venv/bin/uvicorn app.main:app --port 8000

# 实例 B（consumer，端口 8010）：
DATABASE_URL=<pgB> DEPLOY_MODE=intranet AUTH_MODE=intranet_header \
  AUTH_SESSION_SECRET=dev-secret SYNC_PULL_ENABLED=true \
  SYNC_REMOTE_BASE_URL=http://127.0.0.1:8000 SYNC_REMOTE_TOKEN=dev-token \
  .venv/bin/uvicorn app.main:app --port 8010

# 手工验证 feed（service token，不走 cookie）：
curl -s -H 'Authorization: Bearer dev-token' \
  'http://127.0.0.1:8000/api/sync/feed/manifest'
# B 侧手动拉取一轮（super_admin cookie）：POST /api/sync/pull-runs
```

对应测试锚点：`backend/tests/test_deployment_modes.py`（形态/门/CSRF/feed 边界）、
`backend/tests/test_sync_feed_pull.py`（pull 水位/幂等/冲突）、
`backend/tests/test_trusted_proxy.py`（身份头信任边界）；完整矩阵见
`docs/backend/backend-capability-test-matrix.md`。

## 5. 阶段 0 验收

阶段 0 应至少通过：

```bash
cd backend && DATABASE_URL="" pytest
cd frontend && npx vitest run
cd frontend && npm run build
```

以上三步（外加文档/前端控件治理校验）已收敛为 `make test` 一条命令，CI 同口径。

如果 Docker Compose 可用，再补：

```bash
docker compose -f deploy/docker-compose.local.yml up --build
curl http://localhost:8000/healthz
```

阶段 1 应补充通过：

```bash
cd backend && DATABASE_URL="" pytest
cd backend && DATABASE_URL="sqlite:///./stage1_upgrade.sqlite" alembic upgrade head
make migration-check
make migrate
curl http://localhost:8000/healthz
curl http://localhost:5173/healthz
```

## 5.1 阶段 3 能力验收

本阶段已经做到：旧种子源导入、工作台源链接、工作台统一一级/二级标签策略、数据库驱动导航、单源 RSS 抓取到 `raw_items`、工作台级 ingestion run API、worker/scheduler 调度入口。

前端验收：

1. 打开 `http://127.0.0.1:5173/sources`。
2. 使用 `admin/password` 登录。
3. 首页应显示当前阶段为阶段 5；本节验收的是仍然可用的数据源与抓取能力。
4. 数据源页标题应为“数据源管理”，共享源列表标题应为“活跃数据源”。
5. 数据源页右侧应显示工作台统一新闻标签策略，规划部默认含旧系统 AI 十分类；数据源行可显示源侧方向标签，但这些标签不能成为成品新闻 category；AI 工具桌面默认含“工具新功能、工具新案例、工具新技术”，且每个一级标签下都有 `cursor/claude code/opencode/codex` 二级标签；一级/二级标签都支持新增、重命名、删除。
6. 数据源页应显示共享源 294、当前工作台启用 294。
7. 点击任意源的“配置”，应出现数据源配置面板，可设置启用状态、权重和日限，启用开关文案为“启用”。
8. 对启用的 `rss` 或 `paper_rss` 源点击“抓取”，页面应提示拉取、新增、更新数量。
9. 数据源页在桌面宽度下不应横向截断；右侧标签策略不应依赖难发现的内部滚动条；候选池、日报、周报、SQL 导出、用户权限、同步和审计页应使用统一内容容器。

API 验收：

```bash
rm -f /tmp/iw_cookie.txt
curl -fsS -c /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"password"}' \
  http://127.0.0.1:8000/api/auth/login

curl -fsS -b /tmp/iw_cookie.txt \
  'http://127.0.0.1:8000/api/sources?workspace_code=planning_intel'

curl -fsS -b /tmp/iw_cookie.txt \
  http://127.0.0.1:8000/api/workspaces/planning_intel/label-policy

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X PATCH 'http://127.0.0.1:8000/api/workspaces/planning_intel/label-policy' \
  -d '{"label_set_code":"ai_sql_categories","news_format_code":"company_sql_v1","export_category_mode":"news_primary","allowed_primary_categories":["AI Infra","AI 应用","测评技术","大厂动态","模型","算法","推理加速","训练技术","智能体","基础竞争力"],"secondary_labels_by_primary":{},"default_category":"AI 应用","fallback_category":"AI 应用"}'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X PATCH 'http://127.0.0.1:8000/api/sources/{source_id}/workspace-link' \
  -d '{"workspace_code":"planning_intel","enabled":true,"source_weight":1.2,"daily_limit":3}'

curl -fsS -b /tmp/iw_cookie.txt \
  -X POST 'http://127.0.0.1:8000/api/sources/{source_id}/fetch'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/ingestion/runs' \
  -d '{"workspace_code":"planning_intel","source_types":["rss","paper_rss","page_manual","page_monitor","wiseflow"],"limit":1}'

# 负向验收：limit=0 应返回 422；如果所选 source_types 没有启用源，应返回 no_sources 而非 completed。

curl -fsS -b /tmp/iw_cookie.txt \
  'http://127.0.0.1:8000/api/ingestion/runs?workspace_code=planning_intel'
```

数据库验收：

```bash
docker compose -p infowatchtower -f deploy/docker-compose.local.yml exec -T postgres \
  psql -U infowatchtower -d infowatchtower \
  -c "select count(*) from raw_items where data_source_id = '{source_id}';"
```

同一个 RSS 源重复抓取时，第一次应新增 raw 记录；第二次应更新已有记录，不应重复插入。

## 5.2 当前阶段 4 验收

本阶段已经做到：按工作台把已启用源的 `raw_items` 标准化成 `news_items`，生成 canonical URL、normalized title 和 dedupe key，并在 `dedupe_groups/dedupe_group_items` 中记录 winner/loser。去重组按 `workspace_code + dedupe_key` 隔离。

API 验收：

```bash
rm -f /tmp/iw_cookie.txt
curl -fsS -c /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"password"}' \
  http://127.0.0.1:8000/api/auth/login

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/news-items/normalize' \
  -d '{"workspace_code":"planning_intel","source_types":["rss","paper_rss","page_manual","page_monitor","wiseflow"],"limit":50}'

curl -fsS -b /tmp/iw_cookie.txt \
  'http://127.0.0.1:8000/api/news-items?workspace_code=planning_intel&active=true'

curl -fsS -b /tmp/iw_cookie.txt \
  'http://127.0.0.1:8000/api/dedupe-groups?workspace_code=planning_intel'
```

通过标准：

- 同 canonical URL 的多条 news 只保留一个 `active=true`。
- loser 写入 `duplicate_of_id`，但关联的 `raw_items` 仍保留。
- 不同 URL 的相似标题第一版不自动合并。
- 列表返回中必须带 `raw_item_id`，后续日报和 SQL 导出可沿链路追溯回 `raw_items.raw_payload_json`。

## 5.3 当前阶段 5 验收

本阶段已经做到：从目标日期的去重 winner 生成推荐 run、推荐分、`generated_news` 和日报草稿，并支持发布、条目编辑、点赞、评分、评论。若设置 `MINIMAX_GENERATION_ENABLED=true` 且 `MINIMAX_API_KEY` 可用，结构化新闻优先由 MiniMax 中国区 OpenAI-compatible `https://api.minimaxi.com/v1/chat/completions` 生成；单条生成默认 45 秒超时。超时、未启用或调用失败时使用规则 fallback，状态为 `fallback_needs_review`，只能用于页面复核，标准公司 SQL 导出不会接受；草稿日报可重跑非 ready 生成稿。

前端验收：

1. 确保至少已有 raw 标准化和去重 winner。
2. 打开 `http://127.0.0.1:5173/daily-reports`。
3. 选择日报日期，点击“生成日报草稿”。
4. 页面应显示最新日报，条目展示分类、标题、摘要、正文片段、来源 URL、采信状态、点赞和评论数。
5. 点击日报条目后，右侧应能切换采信/备选/剔除，编辑标题/摘要/要点，点赞、评分、评论，并查看 news/raw/source 追溯 ID。

API 验收：

```bash
curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/pipeline/daily-runs' \
  -d '{"workspace_code":"planning_intel","day_key":"2026-04-30","source_types":["rss","paper_rss","page_manual","page_monitor","wiseflow"],"recommendation_limit":15,"source_daily_limit":2,"create_daily_draft":true,"run_ingestion":true}'

curl -fsS -b /tmp/iw_cookie.txt \
  'http://127.0.0.1:8000/api/daily-reports?workspace_code=planning_intel'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X PATCH 'http://127.0.0.1:8000/api/daily-report-items/{item_id}' \
  -d '{"editor_title":"编辑后的标题","adoption_status":2}'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/daily-report-items/{item_id}/ratings' \
  -d '{"score":5}'
```

通过标准：

- 推荐只处理目标日期 `active=true` 的去重 winner。
- selected 数量不超过每日上限，且单源数量不超过同源日限。
- 日报编辑写 `daily_report_items.editor_*`，不覆盖 `generated_news`。
- 日报可沿 `daily_report_items -> generated_news -> recommendation_items -> news_items -> raw_items` 追溯。
- `planning_intel` 和 `ai_tools` 同一天都能生成自己的日报草稿。

## 6. 下一阶段

阶段 5-6 已完成推荐、日报草稿、反馈链路和公司 SQL 标准导出的可回填闭环，并已本地验证 `2026-04-30`、`2026-05-01` 到 `2026-05-08`、`2026-05-09` 到 `2026-05-14`、`2026-05-15` 到 `2026-05-20`、`2026-05-21` 到 `2026-05-27` 的日报/SQL 预览。所有 SQL 预览导入内网前必须通过 `scripts/validate_company_sql.py`，需要统一标题时先运行 `scripts/validate_company_sql.py --fix-headers`。当前已补日报生成超时/重跑、多模式历史补采、周报前端、覆盖率详情、需求/任务/同步/审计页面。下一步优先做候选池增强、SQL 逐条追溯、完整同步包导出/导入和试运行稳定性。
