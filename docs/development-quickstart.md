# 开发启动说明

本文说明当前工程骨架如何本地运行。业务实现顺序仍以 `docs/01-implementation-plan.md` 为准。

## 1. 当前状态

当前已完成阶段 0、阶段 1、阶段 2，并完成阶段 3 的导入、工作台级标签配置、adapter 框架和手动 RSS raw 入库部分：

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
- 工作台模型按共享主链路实现；工作台列表来自 `workspaces`，页面来自 `workspace_sections`，所有工作台共享数据源管理、候选池、日报、周报和导出能力。差异配置通过 `workspace_source_links` 的一级/二级标题、聚类推荐配置和可选插件模块完成。
- 阶段 3 已有共享数据源导入 API、数据源页面、工作台源链接配置 API、adapter registry、RSS adapter 和 wiseflow/page/paper/manual 骨架；旧种子源导入后会为所有已启用默认工作台创建源链接；RSS/paper RSS 源可通过手动 API 抓取并幂等写入 `raw_items`。

业务流程 API 还未实现：RSS 抓取任务调度、raw 到 news 标准化、去重执行、推荐执行、日报编辑页面和 SQL 导出会在后续阶段逐步补齐。

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

## 5.1 当前阶段 3 验收

本阶段已经做到：旧种子源导入、工作台源链接、工作台级一级/二级标签配置、数据库驱动导航、单源 RSS 抓取到 `raw_items`。

前端验收：

1. 打开 `http://127.0.0.1:5173/sources`。
2. 使用 `admin/password` 登录。
3. 首页应显示当前阶段为阶段 3。
4. 数据源页标题应为“数据源、标签配置与 RSS raw 入库”。
5. 数据源页应显示共享源 113、当前工作台启用 79。
6. 点击任意源的“配置”，应出现工作台配置面板，可设置启用状态、权重、日限、标签集和一级/二级标签路径。
7. 对启用的 `rss` 或 `paper_rss` 源点击“抓取”，页面应提示拉取、新增、更新数量。

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
  http://127.0.0.1:8000/api/sources/label-options

curl -fsS -b /tmp/iw_cookie.txt \
  -H 'Content-Type: application/json' \
  -X PATCH 'http://127.0.0.1:8000/api/sources/{source_id}/workspace-link' \
  -d '{"workspace_code":"planning_intel","enabled":true,"source_weight":1.2,"daily_limit":3,"label_set_codes":["ai_sql_categories"],"default_label_paths":["模型/闭源模型"],"clustering_config":{}}'

curl -fsS -b /tmp/iw_cookie.txt \
  -X POST 'http://127.0.0.1:8000/api/sources/{source_id}/fetch'
```

数据库验收：

```bash
docker compose -p infowatchtower -f deploy/docker-compose.local.yml exec -T postgres \
  psql -U infowatchtower -d infowatchtower \
  -c "select count(*) from raw_items where data_source_id = '{source_id}';"
```

同一个 RSS 源重复抓取时，第一次应新增 raw 记录；第二次应更新已有记录，不应重复插入。

## 6. 下一阶段

阶段 3 已完成工作台级标签配置和手动 RSS 抓取到 raw 入库的最小链路。下一步先补抓取调度，再进入阶段 4 的 raw 到 news 标准化与去重。
