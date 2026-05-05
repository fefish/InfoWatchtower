# 开发启动说明

本文说明当前工程骨架如何本地运行。业务实现顺序仍以 `docs/01-implementation-plan.md` 为准。

## 1. 当前状态

当前已完成阶段 0、阶段 1、阶段 2、阶段 3、阶段 4 和阶段 5 最小闭环：

- 后端 FastAPI 骨架。
- `/healthz` 健康检查。
- SQLAlchemy 业务模型。
- Alembic 初始迁移。
- 前端 Vue/Vite 工作台骨架。
- 本地和生产 Docker Compose 草案。
- GitHub Actions CI 草案。
- PostgreSQL 中已能创建 40 张业务表。
- 测试已覆盖 `daily_report_items -> generated_news -> recommendation_items -> dedupe_group_items -> news_items -> raw_items.raw_payload_json` 追溯链路。
- 登录已接入 `local/public_password/intranet_header`，本地开发账号为 `admin/password`。
- 用户权限页面已能读取用户、读取角色并保存用户角色。
- 公网安全和 SSO 后续计划见 `docs/auth-security-roadmap.md`。
- 工作台模型按共享主链路实现；工作台列表来自 `workspaces`，页面来自 `workspace_sections`，所有工作台共享数据源管理、候选池、日报、周报和导出能力。差异配置通过 `workspaces.config_json.label_policy` 的工作台统一一级/二级标签策略、`workspace_source_links` 的源启用/权重/日限和可选插件模块完成。
- 阶段 3 已有共享数据源导入 API、数据源页面、工作台统一标签策略 API、工作台源链接配置 API、工作台级 ingestion run API、Redis/RQ worker + scheduler 调度入口、adapter registry、RSS adapter 和 wiseflow/page/paper/manual 骨架；旧种子源导入后会为所有已启用默认工作台创建源链接；RSS/paper RSS 源可通过手动 API 抓取并幂等写入 `raw_items`，也可通过 ingestion run 按工作台批量触发。前端已切到浅色工作台壳、数据库驱动导航、信息流式数据源列表和紧凑工作台标签策略面板。
- 阶段 4 已有 raw 到 news 标准化与硬去重 API：`POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups`。同一共享 raw 可以被不同工作台各自标准化；去重组按 `workspace_code + dedupe_key` 隔离；winner/loser 会回写到 `news_items.active` 和 `duplicate_of_id`。
- 阶段 5 已有推荐 run、可解释推荐分、`generated_news`、日报草稿、发布、条目编辑和点赞/评分/评论最小 API；前端 `/daily-reports` 可点击生成日报草稿并展示条目；scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿。

业务流程 API 还未实现：候选池完整页面、日报深度编辑页面、周报和 SQL 导出会在后续阶段逐步补齐。

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

## 5. 阶段 0 验收

阶段 0 应至少通过：

```bash
cd backend && DATABASE_URL="" pytest
cd frontend && npm run build
```

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
5. 数据源页右侧应显示工作台统一标签策略，规划部默认含旧系统兼容的 10 个一级标签；AI 工具桌面默认含“工具新功能、工具新案例、工具新技术”，且每个一级标签下都有 `cursor/claude code/opencode/codex` 二级标签；一级/二级标签都支持新增、重命名、删除，且单个源配置里不出现标签维护。
6. 数据源页应显示共享源 113、当前工作台启用 79。
7. 点击任意源的“配置”，应出现数据源配置面板，可设置启用状态、权重和日限，启用开关文案为“启用”。
8. 对启用的 `rss` 或 `paper_rss` 源点击“抓取”，页面应提示拉取、新增、更新数量。
9. 数据源页在桌面宽度下不应横向截断；右侧标签策略不应依赖难发现的内部滚动条；候选池、日报、周报、SQL 导出、用户权限和审计占位页应使用统一内容容器。

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
  -d '{"label_set_code":"ai_sql_categories","allowed_primary_categories":["AI Infra","AI 应用","测评技术","大厂动态","模型","算法","推理加速","训练技术","智能体","基础竞争力"],"secondary_labels_by_primary":{},"default_category":"AI 应用","fallback_category":"AI 应用"}'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X PATCH 'http://127.0.0.1:8000/api/sources/{source_id}/workspace-link' \
  -d '{"workspace_code":"planning_intel","enabled":true,"source_weight":1.2,"daily_limit":3}'

curl -fsS -b /tmp/iw_cookie.txt \
  -X POST 'http://127.0.0.1:8000/api/sources/{source_id}/fetch'

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/ingestion/runs' \
  -d '{"workspace_code":"planning_intel","source_types":["rss","paper_rss"],"limit":0}'

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
  -d '{"workspace_code":"planning_intel","source_types":["rss","paper_rss"],"limit":50}'

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

本阶段已经做到：从去重 winner 生成推荐 run、推荐分、`generated_news` 和日报草稿，并支持发布、条目编辑、点赞、评分、评论。

前端验收：

1. 确保至少已有 raw 标准化和去重 winner。
2. 打开 `http://127.0.0.1:5173/daily-reports`。
3. 点击“生成日报草稿”。
4. 页面应显示最新日报，条目展示分类、标题、摘要、来源 URL、采信状态、点赞和评论数。

API 验收：

```bash
curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X POST 'http://127.0.0.1:8000/api/recommendation/runs' \
  -d '{"workspace_code":"planning_intel","limit":15,"source_daily_limit":2,"create_daily_draft":true}'

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

- 推荐只处理 `active=true` 的去重 winner。
- selected 数量不超过每日上限，且单源数量不超过同源日限。
- 日报编辑写 `daily_report_items.editor_*`，不覆盖 `generated_news`。
- 日报可沿 `daily_report_items -> generated_news -> recommendation_items -> news_items -> raw_items` 追溯。
- `planning_intel` 和 `ai_tools` 同一天都能生成自己的日报草稿。

## 6. 下一阶段

阶段 5 已完成推荐、日报草稿和反馈链路的最小闭环。下一步进入候选池/日报编辑体验增强和阶段 6 公司 SQL 导出。
