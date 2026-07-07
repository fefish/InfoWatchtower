# 部署与运维设计

本文档回答：系统怎么部署，数据库放在哪里，公网和内网如何隔离，代码推到 GitHub 后如何自动发布到云服务器。
审计日志、运行状态、告警、备份恢复演练和验收证据的模块事实源是
`docs/backend/audit-ops-observability-design.md`；本文保留部署执行细节。

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
- `DEPLOY_MODE`
- `AUTH_MODE`
- 数据源密钥
- 域名/证书
- 是否启用同步任务

因此内网快速上线的目标是：拉同一个 Git 仓库，换一份内网 `.env.production`，执行迁移和 Compose 启动。

### 1.1 四种部署拓扑与 env 矩阵

2026-07 起部署形态由单一环境变量 `DEPLOY_MODE` 定义，四种拓扑复用同一套 Compose，
差异全部落在 env 组合。实现级规格见 `docs/deployment/deployment-topology.md`，机器契约见
`config/contracts/deployment_modes.json`：

| env / 维度 | `standalone`（本地） | `cloud`（云官方） | `intranet`（内网嵌入） | `extranet`（外网发布者） |
|---|---|---|---|---|
| `DEPLOY_MODE` | `standalone`（默认） | `cloud` | `intranet` | `extranet` |
| `AUTH_MODE` 合法值 | `local` / `public_password` | `public_password` / `oidc` | `intranet_header`（强制） | `oidc` / `public_password` |
| `AUTH_AUTO_PROVISION` | `false` | `false`（邀请制，默认 viewer） | `true`（header 自动建号，默认 viewer） | 按 provider，默认 `false` |
| `AUTH_CSRF_ENABLED` 默认 | `false` | `true` | `true` | `true` |
| `SYNC_SERVICE_TOKENS` | 不需要 | 不需要 | 不需要 | **必填**（为空启动失败） |
| `SYNC_REMOTE_BASE_URL` / `SYNC_REMOTE_TOKEN` | 不需要 | 不需要 | **必填**（`SYNC_PULL_ENABLED=true` 时） | 不需要 |
| `SYNC_PULL_ENABLED` / `SYNC_PULL_INTERVAL_SECONDS` | — | — | 默认 `true` / `900` | — |
| `SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED` / retry 参数 | — | — | 默认跟随 sync pull；base=300/max=3600/max attempts=5/limit=50 | — |
| `SEMANTIC_SCHOLAR_API_KEY` | 可选 | 可选 | 不需要（禁采集） | 可选 |
| `EMBED_FRAME_ANCESTORS` | `'self'`（默认） | `'self'` | 门户域白名单 | `'self'` |
| 采集能力（`CAPABILITY_INGESTION`） | 开 | 开（仅 workspace admin+ 可触发） | **关**（不可覆盖打开） | 开 |
| 搜索能力 | 开 | 开 | 开（不返回禁采集对象） | 开 |
| sync 角色 | 无（调试可 `CAPABILITY_SYNC_PUBLISHER=true`） | 无 | consumer（定时拉取 extranet feed） | publisher（`GET /api/sync/feed`） |
| TLS/网络 | 本机端口全暴露 | 仅 443（TLS 收口：`docker compose --profile tls` 启用 caddy 自动签证书） | backend 仅网关可达 | 443 + feed 端点（同 cloud 走 tls profile） |
| 升级 | `upgrade.sh` | `upgrade.sh`（后续 GHCR 镜像） | 离线包：`scripts/export_offline_bundle.sh` + `scripts/upgrade_offline.sh` | `upgrade.sh` |

分节要点：

- **standalone**：`deploy/install.sh --local` 一键起，默认 `DEPLOY_MODE=standalone`；
  本地调试联动时可显式 `CAPABILITY_SYNC_PUBLISHER=true`。
- **cloud**：邀请制建号、默认全局角色 viewer；env 样例 `deploy/env.production.example`
  （已含 `DEPLOY_MODE=cloud` 与拓扑段）。TLS 收口：`docker compose --profile tls up -d`
  启用可选 caddy 服务（`CADDY_DOMAIN` 自动 ACME 签发/续期，前端 nginx 端口让位
  `FRONTEND_HTTP_PORT=127.0.0.1:8080`）。
- **intranet**：env 样例 `deploy/env.intranet.example`，compose 为
  `deploy/docker-compose.intranet.yml`（前端/backend 只绑门户主机回环，不映射到外网卡）。
  内网门户以同站路径反向代理承载 iframe，门户侧样例配置见
  `deploy/nginx.portal.example.conf`（同站反代 + 注入
  `X-Employee-No/X-Employee-Name/X-Department/X-Email` 身份头）。
  `AUTH_TRUSTED_PROXY_CIDRS` 兜底校验**已实现**：非空时身份头只信白名单直连 peer
  （不受信 peer 视为未登录 401），登录限流取 IP 也只在受信 peer 时采信
  X-Forwarded-For；未配置时保持旧行为并打启动 warning，非法 CIDR 直接拒启。
  intranet env 样例默认给出该配置项。
- **extranet**：env 样例 `deploy/env.extranet.example`，compose 为
  `deploy/docker-compose.extranet.yml`；`GET /api/sync/feed*` 只走
  `SYNC_SERVICE_TOKENS` Bearer 鉴权（条目支持 `name:token` 命名消费者，访问写审计），
  向 intranet 下发已采集/已成稿数据。

非法组合会启动失败（fail-fast，不是 warning），完整规则见
`config/contracts/deployment_modes.json` 的 `startup_failfast_rules`。前端通过免登录的
`GET /api/meta/runtime` 感知当前形态与能力开关。

当前 scheduler 已接入每日完整流水线，默认关闭自动任务。开启后可按固定墙上时间执行：

```text
ingestion -> normalize/dedupe -> recommendation -> daily_report_draft
```

生产环境推荐每天北京时间 09:00 生成昨天的规划部日报，避免早上任务误生成当天未完成数据：

```text
INGESTION_SCHEDULER_ENABLED=true
INGESTION_SCHEDULER_DAILY_TIME=09:00
INGESTION_SCHEDULER_TIMEZONE=Asia/Shanghai
INGESTION_SCHEDULER_WORKSPACE_CODE=planning_intel
INGESTION_SCHEDULER_SOURCE_TYPES=rss,paper_rss,page_manual,page_monitor,wiseflow
INGESTION_CONCURRENCY=8
INGESTION_SOURCE_TIMEOUT_SECONDS=25
SCHEDULER_JOB_MODE=daily_pipeline
DAILY_PIPELINE_RUN_INGESTION=true
DAILY_PIPELINE_CREATE_DAILY_DRAFT=true
DAILY_PIPELINE_RECOMMENDATION_LIMIT=15
DAILY_PIPELINE_SOURCE_DAILY_LIMIT=2
DAILY_PIPELINE_DAY_OFFSET_DAYS=-1
MINIMAX_GENERATION_ENABLED=false
# MINIMAX_BASE_URL=https://api.minimaxi.com/v1
```

若不设置 `INGESTION_SCHEDULER_DAILY_TIME`，scheduler 会保留旧的 interval 模式：启动后立即入队一次，然后按 `INGESTION_SCHEDULER_INTERVAL_SECONDS` 间隔重复。固定生产任务优先使用 `INGESTION_SCHEDULER_DAILY_TIME`，减少容器重启导致的时间漂移。

如果要限制单次调度处理源数量，可设置 `INGESTION_SCHEDULER_LIMIT=10`。

若生产环境希望日报结构化稿调用 MiniMax，设置 `MINIMAX_GENERATION_ENABLED=true`、`MINIMAX_API_KEY`，并使用旧参考脚本已验证的中国区 OpenAI-compatible 地址 `MINIMAX_BASE_URL=https://api.minimaxi.com/v1`；未显式设置 `MINIMAX_BASE_URL` 时也会默认走该地址。旧 `.env` 中可能残留的 `MINIMAX_ANTHROPIC_BASE_URL` 只保留兼容读取，不会覆盖主链路。单条生成默认 45 秒超时；未启用、超时或调用失败时会使用规则 fallback，不阻塞日报流水线；但 fallback 会标记为 `fallback_needs_review`，标准公司 SQL 导出会拒绝，必须通过日报草稿重跑 MiniMax 或人工编辑后再导出。

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
AUTH_SESSION_SECRET=<long random value>
AUTH_SESSION_COOKIE_SECURE=true
AUTH_SESSION_TTL_SECONDS=43200
AUTH_AUTO_PROVISION=false
AUTH_DEFAULT_ROLE=viewer
```

所有 auth mode（`local/public_password/oidc/intranet_header`）都签发签名 session
cookie，因此启动自检对全部模式检查 `AUTH_SESSION_SECRET`；为空时 API、scheduler、
worker 三个进程入口都会直接退出并给出修复指引（compose 三个服务共用同一份 env file，
无需额外配置）。建议由 `openssl rand -hex 32` 生成。公网建号默认走管理员邀请：超级管理员登录
`/users` 生成邀请链接；用户接受邀请后会写入本地用户、全局角色和工作台 membership。
用户忘记密码且未接 SMTP 时，管理员可在 `/users` 对该用户执行重置，系统只返回一次性临时
密码，并强制用户下次登录后先到 `/account` 修改密码。

公网服务器安全组建议只开放：

- `22`：SSH，最好只允许你的固定 IP。
- `80`：HTTP，用于证书签发和跳转。
- `443`：HTTPS。

不开放：

- `5432` PostgreSQL。
- `6379` Redis。
- 后端内部端口。

## 5. 内网部署

公司内网部署可以复用同一套代码，形态为 `DEPLOY_MODE=intranet`（禁采集、pull-only、
iframe 嵌入），env 组合见 §1.1；同站反代与 CSRF 规格见 `docs/deployment/deployment-topology.md`
§4，门户侧样例配置为 `deploy/nginx.portal.example.conf`。

如果内网网关能直接给工号和姓名，使用：

```text
DEPLOY_MODE=intranet
AUTH_MODE=intranet_header
AUTH_HEADER_EMPLOYEE_NO=X-Employee-No
AUTH_HEADER_DISPLAY_NAME=X-Employee-Name
AUTH_HEADER_DEPARTMENT=X-Department
AUTH_HEADER_EMAIL=X-Email
# 建议配置：身份头只信任门户网关所在网段的直连 peer（未配置会打启动 warning）
AUTH_TRUSTED_PROXY_CIDRS=10.0.0.0/24
AUTH_AUTO_PROVISION=true
AUTH_DEFAULT_ROLE=viewer
SYNC_REMOTE_BASE_URL=https://extranet.example.com
SYNC_REMOTE_TOKEN=...
SYNC_PULL_ENABLED=true
SYNC_PULL_INTERVAL_SECONDS=900
SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED=true
SYNC_FAILED_INBOX_RETRY_BASE_SECONDS=300
SYNC_FAILED_INBOX_RETRY_MAX_SECONDS=3600
SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS=5
SYNC_FAILED_INBOX_RETRY_LIMIT=50
```

关键要求：

- 后端必须放在可信网关后面。
- 可信网关负责覆盖身份 header。
- 用户不能绕过网关直接访问后端。
- 业务权限仍然走本地 RBAC，不由 header 直接决定管理员权限。

数据库可以有两种选择：

- 复用同一个 PostgreSQL：适合早期或可信网络，运维最简单。
- 内网单独 PostgreSQL：适合长期正式运行，内部评论、需求、任务和权限边界更清晰。

如果公网和内网各自一套数据库，同步策略见 `docs/deployment/multi-environment-sync.md`。

外网发布者对应最小同步 env：

```text
DEPLOY_MODE=extranet
AUTH_MODE=oidc
AUTH_AUTO_PROVISION=true
AUTH_DEFAULT_ROLE=viewer
OIDC_ISSUER=https://idp.example.com
# 可选：id_token 验签 JWKS 地址；缺省时用 issuer discovery 的 jwks_uri，
# 两者都没有时退化为 iss/aud/exp/nonce 强校验（拒绝 alg=none）。
# OIDC_JWKS_URI=https://idp.example.com/.well-known/jwks.json
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_REDIRECT_URL=https://watchtower.example.com/api/auth/oidc/callback
OIDC_POST_LOGIN_REDIRECT_URL=https://watchtower.example.com/
OIDC_CLAIM_EXTERNAL_ID=sub
OIDC_CLAIM_EMPLOYEE_NO=employee_no
OIDC_CLAIM_USERNAME=preferred_username
OIDC_CLAIM_DISPLAY_NAME=name
OIDC_CLAIM_DEPARTMENT=department
OIDC_CLAIM_EMAIL=email
AUTH_DEFAULT_WORKSPACE_CODES=planning_intel:viewer
AUTH_DEPARTMENT_WORKSPACE_MAP=规划部:planning_intel:viewer,硬件部:hardware_intel:viewer
SYNC_SERVICE_TOKENS=token-for-intranet-rollover-a,token-for-rollover-b
```

`SYNC_SERVICE_TOKENS` 为空时 extranet 必须启动失败；feed 端点只接受 Bearer token，
不走登录 cookie。
`AUTH_DEFAULT_WORKSPACE_CODES` 和 `AUTH_DEPARTMENT_WORKSPACE_MAP` 只补写本地
membership，不授予 `super_admin`，也不会降级管理员手工授予的更高工作台角色。

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

首次部署优先使用仓库脚本生成环境文件、随机密钥并启动 Compose：

```text
cd deploy
./install.sh --domain your-domain.example
```

本地演练：

```text
cd deploy
./install.sh --local
```

脚本会生成 `.env`（生产默认 `/srv/infowatchtower/.env.production`，本地默认
`deploy/.env`）、随机 `POSTGRES_PASSWORD` 和 `AUTH_SESSION_SECRET`，执行
`docker compose up -d --build`，等待 `/healthz` 通过并打印访问地址。默认不写
`AUTH_BOOTSTRAP_ADMIN_PASSWORD`；首次访问会进入 `/setup` 创建首个超级管理员。生产域名
安装默认 `AUTH_SESSION_COOKIE_SECURE=true`，`--local` 默认 `false`，方便本地 HTTP 验收。

如果本机端口冲突，本地演练可以显式指定端口和 env 文件：

```text
cd deploy
INFOWATCHTOWER_ENV_FILE=/tmp/infowatchtower-local.env \
POSTGRES_PORT=55432 \
REDIS_PORT=56379 \
BACKEND_PORT=18080 \
FRONTEND_PORT=15173 \
  ./install.sh --local
```

升级脚本：

```text
cd deploy
./upgrade.sh
```

本地升级演练使用 `./upgrade.sh --local`。回滚流程是恢复升级前备份，并 checkout 旧 tag。

如果仍由 GitHub Actions 在 `main` 分支 push 后 SSH 触发，动作可以简化为：

```text
ssh deploy@$DEPLOY_HOST
cd /srv/infowatchtower/app
git fetch --prune
git reset --hard origin/main
INFOWATCHTOWER_ENV_FILE=/srv/infowatchtower/.env.production \
  docker compose --env-file /srv/infowatchtower/.env.production \
  -f deploy/docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f
```

API 镜像入口会先执行 `alembic upgrade head` 再启动 uvicorn；worker、scheduler 和
reverse proxy 会等 backend healthcheck 通过后再启动。
这不是严格零停机蓝绿发布，但对第一版足够简单可靠。后端重启通常只有短暂停顿，前端静态文件基本无感。

### 8.4 生产配置检查

仓库提供三份形态 env 模板和部署检查脚本：

```text
deploy/env.production.example   # standalone/cloud（默认 DEPLOY_MODE=cloud）
deploy/env.intranet.example     # intranet
deploy/env.extranet.example     # extranet
scripts/check_prod_deploy.py
```

上线前先复制对应模板并替换真实密钥：

```text
cp deploy/env.production.example /srv/infowatchtower/.env.production
```

检查命令：

```text
python3 scripts/check_prod_deploy.py --env-file deploy/env.production.example
python3 scripts/check_prod_deploy.py --env-file /srv/infowatchtower/.env.production
```

检查内容包括：

- `DEPLOY_MODE` 必填且合法，并按形态选择对应 compose 工件校验
  （intranet → `docker-compose.intranet.yml`，extranet → `docker-compose.extranet.yml`）。
- 生产 compose 必须包含 PostgreSQL、Redis、backend、worker、scheduler 和 reverse proxy。
- PostgreSQL 和 Redis 不直接暴露主机端口；intranet compose 不允许宿主机直接绑 80。
- 前端 nginx 模板必须把 `/api/` 转发到 backend、保留 Vue history fallback、输出
  `frame-ancestors ${EMBED_FRAME_ANCESTORS}` CSP，并清洗外部传入的身份头。
- cloud/extranet 的 compose 必须带可选 caddy TLS profile，Caddyfile 从
  `CADDY_DOMAIN` 读域名并转发到前端 nginx。
- `APP_ENV=production`，`ENABLE_DOCS=false`；`AUTH_SESSION_SECRET` 等必填。
- 拓扑组合校验对齐契约 `startup_failfast_rules`（如 extranet 缺
  `SYNC_SERVICE_TOKENS` 直接报错）。
- 生产密钥不能使用 `change_me`、`password`、`secret` 等开发默认值。
- 规划部日报定时任务时区必须是 `Asia/Shanghai`。
- backend 必须有 `/healthz` healthcheck；worker、scheduler、reverse proxy 依赖 backend healthy。

健康探针分两个：`/healthz` 是存活探针（进程活着即 200）；`/readyz` 是就绪探针
（数据库 `SELECT 1` 失败/未配置返回 503，body 附带 deploy_mode 与能力位供巡检定位），
compose/网关健康检查应指向 `/readyz`。

CI 也会运行该检查，避免生产部署文件和文档口径漂移。

### 8.5 intranet 离线升级

内网无 git pull / 本机构建能力，升级走离线包：

```text
# 在有外网与构建能力的机器上出包（docker save 全部镜像 + 迁移清单 + compose/env 样例 +
# 门户反代样例 + sha256 校验和；前端默认以 VITE_BASE_PATH=/watchtower/ 构建）
./scripts/export_offline_bundle.sh --version <tag>

# 拷入内网主机后导入并升级（校验 sha256 -> docker load -> compose up；
# backend 以 RUN_MIGRATIONS=true 启动自动执行 alembic upgrade）
./scripts/upgrade_offline.sh --bundle <解压目录> [--env-file /srv/infowatchtower/.env.intranet]
```

数据库数据在 `/srv/infowatchtower/postgres_data`，跨版本保留；回滚先恢复备份再导入旧包。

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

最低每天备份 PostgreSQL。仓库提供脚本：

```text
INFOWATCHTOWER_ENV_FILE=/srv/infowatchtower/.env.production \
  scripts/backup_db.sh
```

本地 Compose 演练可显式指定本地 env 和 compose 文件：

```text
INFOWATCHTOWER_ENV_FILE=deploy/.env \
INFOWATCHTOWER_COMPOSE_FILE=deploy/docker-compose.local.yml \
BACKUP_DIR="$(mktemp -d)" \
  scripts/backup_db.sh
```

脚本默认写入 `/srv/infowatchtower/backups/infowatchtower_YYYYMMDDTHHMMSSZ.sql.gz`，
默认保留最近 14 份，可用 `BACKUP_KEEP=30` 调整。脚本优先使用本机 `pg_dump`；
不可用时会通过 compose 中的 `postgres` 容器执行。应用侧
`postgresql+psycopg://...` URL 会在调用 `pg_dump/psql` 前规范化为 `postgresql://...`。

建议保留：

- 最近 7 天每日备份。
- 最近 8 周每周备份。
- 每次数据库迁移前临时备份。

备份文件不要提交 GitHub。

恢复脚本：

```text
INFOWATCHTOWER_ENV_FILE=/srv/infowatchtower/.env.production \
  scripts/restore_db.sh /srv/infowatchtower/backups/infowatchtower_YYYYMMDDTHHMMSSZ.sql.gz
```

恢复脚本会要求输入 `RESTORE` 确认；无人值守演练可设置 `RESTORE_CONFIRM=yes`。恢复后重启
backend、worker 和 scheduler，再访问 `/healthz` 和前端页面确认服务可用。

## 10.1 部署后全量验收

完成首次 `/setup` 或准备好管理员账号后，使用同一条脚本执行蓝图 §9 验收：

```text
python3 scripts/run_full_acceptance.py \
  --base-url http://127.0.0.1:8000 \
  --admin-username <admin> \
  --admin-password <password> \
  --rss-bind-host 0.0.0.0 \
  --rss-public-host host.docker.internal
```

本地 Docker 最新证据在 `outputs/acceptance/20260703T062259Z/`，包含 Setup/邀请/建台/
共享源+自建源/标签策略/成稿格式/流水线/日报周报导出/公司 SQL 校验/备份输出。

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
