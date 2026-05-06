# 部署与运维设计

本文档回答：系统怎么部署，数据库放在哪里，公网和内网如何隔离，代码推到 GitHub 后如何自动发布到云服务器。

## 1. 推荐部署形态

第一版推荐单台云服务器 + Docker Compose。

服务组成：

```text
internet / intranet
-> Caddy or Nginx
-> frontend static files
-> backend FastAPI
-> worker
-> scheduler
-> PostgreSQL
-> Redis
```

容器建议：

- `reverse_proxy`：Caddy 或 Nginx，负责 HTTPS、反向代理、静态文件。
- `frontend`：Vue build 后的静态文件，也可以直接由 reverse proxy 托管。
- `backend`：FastAPI API 服务。
- `worker`：抓取、去重、推荐、日报生成、SQL 导出等后台任务。
- `scheduler`：每天定时触发处理任务。
- `postgres`：主数据库。
- `redis`：任务队列和缓存。

同一套部署形态适用于公网和内网。差异不靠改代码解决，而靠：

- `.env.production`
- `AUTH_MODE`
- 数据源密钥
- 域名/证书
- 是否启用同步任务

因此内网快速上线的目标是：拉同一个 Git 仓库，换一份内网 `.env.production`，执行迁移和 Compose 启动。

当前 scheduler 已接入每日完整流水线，默认关闭自动任务。开启后默认执行：

```text
ingestion -> normalize/dedupe -> recommendation -> daily_report_draft
```

需要开启时在生产环境变量中设置：

```text
INGESTION_SCHEDULER_ENABLED=true
INGESTION_SCHEDULER_INTERVAL_SECONDS=86400
INGESTION_SCHEDULER_WORKSPACE_CODE=planning_intel
INGESTION_SCHEDULER_SOURCE_TYPES=rss,paper_rss,page_manual,page_monitor
SCHEDULER_JOB_MODE=daily_pipeline
DAILY_PIPELINE_RUN_INGESTION=true
DAILY_PIPELINE_CREATE_DAILY_DRAFT=true
DAILY_PIPELINE_RECOMMENDATION_LIMIT=15
DAILY_PIPELINE_SOURCE_DAILY_LIMIT=2
MINIMAX_GENERATION_ENABLED=false
# MINIMAX_BASE_URL=https://api.minimaxi.com/v1
```

如果要限制单次调度处理源数量，可设置 `INGESTION_SCHEDULER_LIMIT=10`。

若生产环境希望日报结构化稿调用 MiniMax，设置 `MINIMAX_GENERATION_ENABLED=true`、`MINIMAX_API_KEY`，并使用旧参考脚本已验证的中国区 OpenAI-compatible 地址 `MINIMAX_BASE_URL=https://api.minimaxi.com/v1`；未显式设置 `MINIMAX_BASE_URL` 时也会默认走该地址。旧 `.env` 中可能残留的 `MINIMAX_ANTHROPIC_BASE_URL` 只保留兼容读取，不会覆盖主链路。未启用或调用失败时会使用规则生成，不阻塞日报流水线。

如果只想执行抓取、不生成日报草稿，可设置 `SCHEDULER_JOB_MODE=ingestion_only`。

## 2. 数据库放在哪里

PostgreSQL 数据库不放在 GitHub 仓库里。

单台服务器部署时，数据库数据存在云服务器本机磁盘上，推荐路径：

```text
/srv/infowatchtower/postgres_data
```

如果使用 Docker volume，可以叫：

```text
infowatchtower_postgres_data
```

本质上它仍然落在服务器磁盘，不会进入 Git。

需要备份的内容：

- PostgreSQL 数据目录或 `pg_dump` 备份。
- `/srv/infowatchtower/.env.production`。
- 上传文件目录，如果后续有附件。
- 导出的 SQL 文件目录，如果选择落盘保存。

## 3. 数据库会不会暴露

默认不暴露。

推荐网络：

```text
外网只开放 80/443/22
backend 通过 Docker 内网访问 postgres:5432
postgres 不映射宿主机 5432
```

也就是：

- 用户只能访问网站。
- 后端能访问数据库。
- 外部无法直接连数据库。

如果你愿意在公司内网暴露数据库，也可以把 `5432` 只绑定到内网 IP，例如：

```text
10.x.x.x:5432:5432
```

不要绑定到 `0.0.0.0:5432`，除非你明确知道安全组、防火墙和密码策略都已经配置好。

## 4. 公网部署

公网环境建议：

```text
AUTH_MODE=public_password
AUTH_AUTO_PROVISION=false
```

公网服务器安全组建议只开放：

- `22`：SSH，最好只允许你的固定 IP。
- `80`：HTTP，用于证书签发和跳转。
- `443`：HTTPS。

不开放：

- `5432` PostgreSQL。
- `6379` Redis。
- 后端内部端口。

## 5. 内网部署

公司内网部署可以复用同一套代码。

如果内网网关能直接给工号和姓名，使用：

```text
AUTH_MODE=intranet_header
AUTH_HEADER_EMPLOYEE_NO=X-Employee-No
AUTH_HEADER_DISPLAY_NAME=X-Employee-Name
AUTH_HEADER_DEPARTMENT=X-Department
AUTH_HEADER_EMAIL=X-Email
AUTH_AUTO_PROVISION=true
AUTH_DEFAULT_ROLE=viewer
```

关键要求：

- 后端必须放在可信网关后面。
- 可信网关负责覆盖身份 header。
- 用户不能绕过网关直接访问后端。
- 业务权限仍然走本地 RBAC，不由 header 直接决定管理员权限。

数据库可以有两种选择：

- 复用同一个 PostgreSQL：适合早期或可信网络，运维最简单。
- 内网单独 PostgreSQL：适合长期正式运行，内部评论、需求、任务和权限边界更清晰。

如果公网和内网各自一套数据库，同步策略见 `docs/multi-environment-sync.md`。

## 6. 服务器目录

建议服务器上固定目录：

```text
/srv/infowatchtower/
  app/                    Git 仓库
  .env.production          生产环境变量，不提交 Git
  postgres_data/           PostgreSQL 数据
  redis_data/              Redis 数据，可选
  backups/
  exports/
```

`app/` 可以从 GitHub clone：

```text
git clone git@github.com:fefish/InfoWatchtower.git /srv/infowatchtower/app
```

## 7. 环境变量

生产环境变量放服务器：

```text
/srv/infowatchtower/.env.production
```

不要提交到 GitHub。

最低需要：

```text
APP_ENV=production
APP_BASE_URL=https://your-domain.example
DATABASE_URL=postgresql+psycopg://infowatchtower:CHANGE_ME@postgres:5432/infowatchtower
REDIS_URL=redis://redis:6379/0
AUTH_MODE=public_password
AUTH_SESSION_SECRET=CHANGE_ME_LONG_RANDOM
AUTH_AUTO_PROVISION=false
AUTH_DEFAULT_ROLE=viewer
```

如果接入 OpenAI 或其他模型服务，再加对应 API key。所有 key 都只放服务器环境变量。

## 8. GitHub 推送后自动部署

第一版推荐 GitHub Actions 通过 SSH 登录服务器部署。

### 8.1 服务器准备

在服务器创建部署用户：

```text
adduser deploy
usermod -aG docker deploy
mkdir -p /srv/infowatchtower
chown -R deploy:deploy /srv/infowatchtower
```

安装：

- Git
- Docker
- Docker Compose plugin

### 8.2 SSH key

在本机生成给 GitHub Actions 用的部署 key：

```text
ssh-keygen -t ed25519 -C "github-actions-infowatchtower" -f ~/.ssh/infowatchtower_deploy
```

把公钥加入服务器：

```text
/home/deploy/.ssh/authorized_keys
```

把私钥内容配置到 GitHub 仓库 Secrets：

```text
DEPLOY_SSH_KEY
```

再加这些 Secrets：

```text
DEPLOY_HOST
DEPLOY_USER=deploy
DEPLOY_PATH=/srv/infowatchtower/app
```

### 8.3 部署动作

GitHub Actions 在 `main` 分支 push 后执行：

```text
ssh deploy@$DEPLOY_HOST
cd /srv/infowatchtower/app
git fetch --prune
git reset --hard origin/main
docker compose -f deploy/docker-compose.prod.yml --env-file /srv/infowatchtower/.env.production build
docker compose -f deploy/docker-compose.prod.yml --env-file /srv/infowatchtower/.env.production run --rm backend alembic upgrade head
docker compose -f deploy/docker-compose.prod.yml --env-file /srv/infowatchtower/.env.production up -d --remove-orphans
docker image prune -f
```

这不是严格零停机蓝绿发布，但对第一版足够简单可靠。后端重启通常只有短暂停顿，前端静态文件基本无感。

## 9. 真正滚动或蓝绿发布

如果后续要求尽量零停机，可以升级：

- GitHub Actions 构建 Docker image 并推送到 GHCR。
- 服务器只 pull image，不在服务器 build。
- 同时保留 `backend_blue` 和 `backend_green` 两组服务。
- 迁移数据库前先备份。
- 新服务健康检查通过后，reverse proxy 切流量。
- 旧服务延迟下线。

第一版不建议一开始就做复杂蓝绿。先把单机 Compose 自动部署跑稳定。

## 10. 备份

最低每天备份 PostgreSQL：

```text
pg_dump "$DATABASE_URL" > /srv/infowatchtower/backups/infowatchtower_YYYYMMDD.sql
```

建议保留：

- 最近 7 天每日备份。
- 最近 8 周每周备份。
- 每次数据库迁移前临时备份。

备份文件不要提交 GitHub。

## 11. 内网迁移

从公网迁到内网时：

1. 部署同一套代码。
2. 恢复 PostgreSQL 备份。
3. 修改 `.env.production`：
   - `APP_BASE_URL`
   - `AUTH_MODE`
   - 内网 header 或 OIDC 配置
4. 确认网关身份 header。
5. 管理员给自动创建的内网用户分配角色。

业务数据不需要改表。公网用户和内网用户通过 `external_provider + external_id` 区分。
