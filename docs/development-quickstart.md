# 开发启动说明

本文说明当前工程骨架如何本地运行。业务实现顺序仍以 `docs/01-implementation-plan.md` 为准。

## 1. 当前状态

当前已完成阶段 0 和阶段 1：

- 后端 FastAPI 骨架。
- `/healthz` 健康检查。
- SQLAlchemy 业务模型。
- Alembic 初始迁移。
- 前端 Vue/Vite 工作台骨架。
- 本地和生产 Docker Compose 草案。
- GitHub Actions CI 草案。
- PostgreSQL 中已能创建 33 张业务表。
- 测试已覆盖 `daily_report_items -> generated_news -> recommendation_items -> dedupe_group_items -> news_items -> raw_items.raw_payload_json` 追溯链路。

业务流程 API 还未实现：登录、数据源导入、RSS 抓取任务、去重执行、推荐执行、日报编辑页面和 SQL 导出会在后续阶段逐步补齐。

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

## 6. 下一阶段

阶段 2 开始实现登录、身份适配和 RBAC。先做 `local/public_password/intranet_header` 三种模式的后端闭环，再接前端登录页面。
