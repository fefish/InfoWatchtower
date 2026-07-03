# 目标态实现规格：可部署、可扩展、账户完整的多工作台情报系统

本文是写给实现者（人或 AI 编码代理）的**实现级规格**。读完本文加引用文档后，
应当能够在不追问的情况下完成实现。规格分三个工作包（WP1 账户与登录、WP2 可扩展
作业桌面、WP3 开箱即用部署），每个工作包有数据模型、API、前端行为和**可执行的验
收标准**。

## 0. 使用方式

阅读顺序：`AGENTS.md` → `docs/00-system-design.md`（总纲）→
`docs/architecture-capability-map.md`（能力分块与现状）→ 本文。

规则：

1. 本文只定义**要新做的部分**；已实现能力以能力地图为准，不要重做。
2. 实现前先读对应现有代码；本文给出的现状文件路径是准确的锚点。
3. 每完成一个工作包：跑通该包验收标准、后端 `pytest` 全绿、前端
   `npm run build` 通过、按 `AGENTS.md` 同步文档与 `config/contracts/*.json`、
   独立提交。
4. 第 6 节不变式在任何情况下不可破坏。

## 1. 目标系统一页图

```text
用户视角（目标态）：
  拿到仓库 → 一条命令部署 → 首次访问进入 Setup 向导（建管理员）
  → 管理员邀请同事（邀请码绑定角色与工作台）
  → 任何管理员可新建工作台（向导：基本信息→选源→标签策略）
  → 每个工作台共享同一条流水线：
     采集 → raw → news → 去重 → 评分推荐 → 生成 → 采信编审 → 多版成稿 → SQL/MD/HTML
  → 每日 scheduler 自动出报，成品直接可读，编审是幕后工序

现状标注：流水线/成稿/建台/自建源 ✅ 已实现；
账户生命周期 🔨 WP1；建台向导与成员管理 🔨 WP2；一键部署与 Setup 🔨 WP3。
```

## 2. 现状基线（实现者必须知道的事实）

技术栈：FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL（生产）/SQLite（测试）、
Redis/RQ worker + scheduler、Vue 3 + TS + Vite + Pinia、Docker Compose 部署。

登录现状（`backend/app/api/routes/auth.py`、`backend/app/auth/`）：

- 已有：`POST /api/auth/login`（public_password 模式，签名 cookie 会话）、
  `POST /api/auth/logout`、`GET /api/auth/me`；`intranet_header` 可信头模式；
  `GET /api/users`、`GET /api/roles`、`PATCH /api/users/{id}/roles`（super_admin）。
- 用户来源：仅启动时 env `AUTH_BOOTSTRAP_ADMIN_*` 创建的单个管理员。
- **没有**：创建用户 API、邀请、注册、改密、忘记密码、登录限流、会话过期策略、
  首次运行向导、workspace membership 权限执行（`workspace_memberships` 表已存在
  但任何 API 都不检查它）。
- `users` 表字段（`backend/app/models/identity.py`）：external_provider/external_id、
  employee_no、username（unique）、display_name、department、email、password_hash、
  status、last_login_at、is_active、roles（多对多）。

工作台与扩展现状（`backend/app/models/workspace.py`、`app/api/routes/workspaces.py`）：

- 已有：`POST /api/workspaces` 建台（自动配齐核心分区/标签策略/内置成稿格式/超管
  owner 成员）；`POST /api/sources` 自建源入共享池；标签策略 API；成稿格式注册表；
  分组导航（`workspace_sections.config_json.group`）。
- **没有**：建台向导式前端（当前是单步弹窗）、工作台停用/改名 API、
  membership 管理界面、domain pack 第二板块样例。

部署现状（`deploy/`）：

- 已有：`docker-compose.local.yml`、`docker-compose.prod.yml`（pg/redis/api/worker/
  scheduler/caddy）、`env.production.example`、部署检查脚本。
- **没有**：一键安装脚本、启动自动迁移、env 缺失时的启动自检、备份/恢复脚本、
  首次运行 Setup 向导。scheduler 生产参数未在 env 模板中给出推荐值。

## 3. WP1 账户与登录系统

### 3.1 原则

- 私有部署优先：默认**关闭开放注册**，账户通过「管理员邀请」进入。
- 无外部依赖可用：没有 SMTP 也必须能完成全部账户流程（邀请码人工分发、
  管理员代重置密码）；配置 SMTP 后自动升级为邮件链接。
- 所有账户变更写 `audit_logs`（复用 `app.auth.service.write_audit`）。
- 密码规则：最小 10 位，禁止与 username 相同；哈希沿用现有
  `app/auth/passwords.py`（bcrypt）。

### 3.2 数据模型增量（新增 alembic 迁移，不改已有列）

```text
user_invites
  id / global_id / created_at / updated_at（沿用 IdMixin/TimestampMixin 风格）
  code            str(64) unique      # URL 安全随机串
  email           str(255) nullable   # 可选，仅作提示
  role_code       str(64)             # 接受后赋予的全局角色
  workspace_codes json                # 接受后加入的工作台列表（含 workspace_role）
  invited_by_id   fk users.id
  expires_at      datetime(tz)        # 默认 7 天
  accepted_by_id  fk users.id nullable
  accepted_at     datetime(tz) nullable
  revoked_at      datetime(tz) nullable

password_reset_tokens
  id / created_at
  user_id         fk users.id
  token_hash      str(128)            # 只存哈希，不存明文
  expires_at      datetime(tz)        # 默认 30 分钟
  used_at         datetime(tz) nullable

login_attempts                         # 限流与审计双用途
  id / created_at
  username        str(128) index
  ip              str(64) index
  success         bool
```

### 3.3 API（全部带 request/response 与权限）

前缀 `/api/auth`，除注明外无需登录：

| Endpoint | 行为 |
|---|---|
| `POST /invites`（super_admin） | body `{email?, role_code, workspaces: [{code, workspace_role}], expires_in_days=7}` → `{code, invite_url, expires_at}`；写审计 `invite.create` |
| `GET /invites`（super_admin） | 列表含状态（pending/accepted/expired/revoked） |
| `POST /invites/{code}/revoke`（super_admin） | 置 revoked_at |
| `GET /invites/{code}` | 公开查询邀请是否有效（不泄露 email 全文） |
| `POST /invites/{code}/accept` | body `{username, display_name, password}` → 创建用户（status=active、赋 role、建 memberships）、标记 accepted、直接登录返回会话 cookie；username 冲突 409；过期/撤销 410 |
| `POST /password/change`（登录后） | body `{current_password, new_password}`；intranet_header 用户 400 |
| `POST /password/forgot` | body `{username}`；**恒定 200**（不泄露用户存在性）。有 SMTP：发重置链接；无 SMTP：仅写审计，提示走管理员代重置 |
| `POST /password/reset` | body `{token, new_password}`；校验 token_hash 未用未过期；成功后使该用户全部会话失效 |
| `POST /users/{id}/reset-password`（super_admin，路径在 admin router） | 生成一次性临时密码返回给管理员（仅返回一次），置 `users.status=must_change_password`；该状态用户登录后除改密接口外一律 403 |
| `PATCH /users/{id}`（super_admin） | 启停用户 `{is_active}`、改 display_name/department/email |

登录限流（改造现有 `POST /login`）：

- 每 `username+ip` 15 分钟窗口内 5 次失败 → 之后同窗口一律 429
  `{"detail": "too many attempts"}`，成功登录清零；实现用 `login_attempts` 表
  count 查询（无 Redis 依赖），窗口外记录由每日清理任务或查询条件自然过滤。
- 所有登录成功/失败写 `login_attempts`。

会话硬化：

- 启动自检：`AUTH_MODE=public_password` 时 `AUTH_SESSION_SECRET` 为空 → 进程
  拒绝启动并打印明确错误（在 `app/main.py` lifespan 中校验）。
- cookie 增加过期（env `AUTH_SESSION_TTL_HOURS`，默认 72）；签名 payload 加入
  `password_changed_at` 类似 nonce（可用 user.updated_at）实现改密后旧会话失效。

OIDC 预留（只做接口不做 provider）：`app/auth/oidc.py` 定义
`OidcAdapter` Protocol（`authorize_url() / exchange_code() / identity()`），
`AUTH_MODE=oidc` 时返回 501 与文档指引；不引入第三方依赖。

### 3.4 前端

- `/login`：失败区分 401/429 文案；「忘记密码」入口（提交 username，恒定成功提示）。
- `/invite/:code`：公开页。展示邀请有效性 → 表单（username/display_name/密码
  双输入）→ 成功后直接进入工作台。
- `/account`：当前用户改密页（导航头像下拉进入）。
- `/users` 扩展：邀请管理 tab（生成邀请：选角色+工作台，展示邀请链接一键复制；
  列表与撤销）；用户行操作：启停、代重置密码（弹出一次性临时密码）。
- `must_change_password` 状态用户登录后强制跳转 `/account` 改密。

### 3.5 workspace membership 权限执行

规则表（在 `config/contracts/auth_modes.json` 增补 machine-readable 版本）：

```text
第一层 global role（现有 require_super_admin 等）保持不变。
第二层 membership：请求带 workspace_code 的业务 API（sources 列表/链接、
ingestion、news、recommendation、reports、renditions、exports），在
global role 非 super_admin 时必须校验 workspace_memberships 中存在
(user, workspace, enabled) 记录，否则 403 "not a workspace member"。
workspace_role：owner/admin 可写（采信/发布/建源/改策略），member 可读写采信，
viewer 只读。super_admin 绕过 membership。
```

实现方式：新增依赖 `require_workspace_member(min_role)`，
在上述路由把 `get_current_user` 替换为组合依赖；用一张
`ROUTE_MIN_ROLE` 常量表集中声明，避免散落判断。

### 3.6 WP1 验收标准（写成 pytest，文件 `backend/tests/test_account_lifecycle.py`）

1. 管理员创建邀请 → 匿名用 code 注册 → 新用户登录成功且出现在指定工作台
   membership；过期/撤销邀请返回 410。
2. 连续 5 次错误密码 → 第 6 次 429；正确密码在新窗口成功。
3. 忘记密码在无 SMTP 时恒定 200 且不创建 token 泄露；管理员代重置后旧密码失效、
   新用户处于 must_change_password，改密前访问 `/api/sources` 得 403，改密后恢复。
4. viewer 成员对 `PATCH /api/daily-report-items/{id}` 得 403，member 成功；
   非成员对该工作台任何业务 API 得 403；super_admin 不受限。
5. 缺 `AUTH_SESSION_SECRET` 启动 → 进程报错退出（用 subprocess 断言）。
6. 改密后携带旧 cookie 的请求 401。

## 4. WP2 可扩展作业桌面

### 4.1 已有扩展点（不要重做）

建台 API、自建源、成稿格式注册表、标签策略、分组导航、liquid glass 主题层。
扩展配方以文档形式固化（见 4.3 R 系列），配方本身也是交付物。

### 4.2 需要实现

1. **建台向导**（前端改造 `AppShell` 现有弹窗 → 三步向导组件）：
   - 第 1 步 基本信息（code/name/描述/domain）；
   - 第 2 步 选源：列出共享池（复用 `GET /api/sources`），勾选启用 + 可现场自建
     一个源（复用 `POST /api/sources`）；
   - 第 3 步 标签策略：预设三选一（复制规划部十分类 / 复制 ai_tools / 空白自定义），
     写 `PATCH /api/workspaces/{code}/label-policy`；
   - 完成页给出「下一步做什么」清单（跑抓取/看候选池/配调度）。
   - 全部复用现有 API，不新增后端接口（批量启用源可循环调用 workspace-link）。
2. **工作台管理 API**：`PATCH /api/workspaces/{code}`（super_admin）支持
   `{name?, description?, enabled?, default_domain_code?}`；停用后工作台从列表消失
   但数据保留；禁止停用 `planning_intel`（400）。
3. **成员管理**：`GET/POST/DELETE /api/workspaces/{code}/members`
   （owner/admin 或 super_admin），body `{user_id, workspace_role}`；
   前端 `/users` 增加「工作台成员」tab 或工作台侧滑面板。
4. **domain pack 样例 `hardware`**：新增
   `config/domain_packs/hardware.json`（板块、标签集、评分先验关键词），
   加载逻辑读取 domain_packs 目录注册 label_sets；以「不改主链路代码、仅加配置」
   为验收核心。
5. **扩展配方文档** `docs/extension-recipes.md`：R1 新建工作台（界面/API）、
   R2 新增 SourceAdapter（实现 `app/adapters/base.py` 的 Protocol → 注册到
   `create_default_registry` → 契约测试模板）、R3 新增成稿格式（界面注册 vs 代码内置）、
   R4 新增导航分区（workspace_sections 注册 + 前端路由 + 图标映射）、
   R5 新增 domain pack。每个配方 = 前置条件 + 步骤 + 验证命令。

### 4.3 WP2 验收标准

1. 通过向导创建 `hardware_intel` 工作台：选中 ≥3 个共享源 + 自建 1 个 RSS 源 +
   套用空白标签策略，完成后该工作台可跑通抓取→候选→日报草稿→技术洞察版导出。
2. 停用/启用工作台生效且 `planning_intel` 不可停用。
3. owner 可把另一用户加为 member，该用户登录后仅见其所属工作台。
4. `hardware` domain pack 仅靠配置文件生效（git diff 无主链路 `.py` 改动，
   加载器与测试除外）。
5. 按 R2 配方新增一个 `dummy` 测试 adapter 的示例测试通过（作为配方正确性的证明）。

## 5. WP3 开箱即用部署

### 5.1 目标体验

```text
git clone → cd deploy && ./install.sh --domain example.internal
→ 脚本生成 .env（随机 secret）、docker compose up -d、等待健康检查
→ 浏览器打开 → /setup 向导（创建管理员、改默认口径、可选导入种子源）
→ 15 分钟内完成：邀请用户、建台、跑一轮流水线、导出成稿
```

### 5.2 需要实现

1. `deploy/install.sh`：生成 `.env`（`openssl rand` 生成 `AUTH_SESSION_SECRET`、
   PG 密码；写入域名）、`docker compose -f docker-compose.prod.yml up -d`、
   轮询 `/healthz` 直到 ok、打印首访地址与后续步骤；`--local` 走 local compose。
2. **启动自动迁移**：API 容器 entrypoint 先 `alembic upgrade head` 再启 uvicorn；
   worker/scheduler 等待 API 健康后启动（compose healthcheck + depends_on）。
3. **/setup 首次运行向导**（替代 env bootstrap admin 的强依赖）：
   - 后端：`GET /api/setup/status` → `{needs_setup: bool}`（users 表为空即 true）；
     `POST /api/setup` → 创建 super_admin（username/display_name/password），
     仅在 needs_setup 时可调用，调用后永久 410；
   - 前端：路由守卫在 needs_setup 时全站重定向 `/setup`；
     向导第 2 步可选执行 `POST /api/sources/import-legacy-seeds` 与
     `import-tech-insight-loop`；
   - 兼容：`AUTH_BOOTSTRAP_ADMIN_*` env 仍生效（无人值守部署场景），
     有用户时 /setup 永远 410。
4. **env 启动自检**：`app/main.py` lifespan 校验必需变量
   （DATABASE_URL、AUTH_SESSION_SECRET when public_password），缺失即抛出
   带修复指引的 RuntimeError；`deploy/env.production.example` 补全所有变量并给
   生产推荐值（`INGESTION_SCHEDULER_ENABLED=true`、`DAILY_TIME=09:00`、
   `TIMEZONE=Asia/Shanghai`、`DAY_OFFSET_DAYS=-1`、`MAX_ITEMS_PER_SOURCE=100`）。
5. **备份/恢复**：`scripts/backup_db.sh`（pg_dump 到时间戳文件 + 保留 N 份）、
   `scripts/restore_db.sh <file>`（确认交互 + 恢复 + 提示重启）；写入
   `docs/deployment-ops.md` 演练步骤。
6. **升级路径**：`deploy/upgrade.sh` = `git pull` → build → 迁移 → 滚动重启；
   文档注明回滚 = 恢复备份 + checkout 旧 tag。

### 5.3 WP3 验收标准

1. 干净环境（无 .env、无容器）执行 `install.sh --local` 一条命令后：
   `/healthz` ok、首访跳 `/setup`、完成向导后可登录。
2. 杀掉容器重启后数据仍在；`backup_db.sh` + 删库 + `restore_db.sh` 后数据恢复。
3. 缺 `AUTH_SESSION_SECRET` 启动 API 容器 → 容器日志给出明确修复指引并退出非 0。
4. `docker compose ps` 全部 healthy；scheduler 按 env 生效（日志可见 next run）。
5. 已有用户时访问 `/setup` → 410 并跳转登录。

## 6. 不变式（实现期间不可破坏）

1. 公司 SQL 合同：只导出已发布日报 `adoption_status=2` + `generation_status=ready`
   + `generated_by` 非 `rule_v1`；category 十分类；`content_json` 五段；
   必须通过 `scripts/validate_company_sql.py`（0505 基准）。
2. `raw_items.raw_payload_json` 永不覆盖；去重在 news 之后推荐之前；
   `adoption_status` 只属于采信层。
3. 业务板块只存 `insight_json`/成稿分组，不写 `generated_news.category`。
4. rendition 是投影不是副本；`company_sql_v1` 格式 locked。
5. 密钥/token/.env 不进 Git、不进同步包；新表一律走 alembic。
6. 前端视觉基线 Liquid Glass（`api-and-ui-implementation.md` §3.1）；
   表面样式只在 `base.css` 主题层覆盖；导航由数据库 sections 驱动。
7. 启动 seed 只维护内置 `planning_intel/ai_tools`，不得覆盖/停用自建工作台。

## 7. 实施顺序

```text
WP1 账户与登录（3.2 → 3.3 → 3.5 → 3.4 → 3.6 验收）
  ↓（WP3 的 /setup 依赖 WP1 的用户创建逻辑）
WP3 开箱部署（5.2.2 迁移入口 → 5.2.3 setup → 5.2.1 install.sh → 5.2.4-6 → 5.3 验收）
WP2 扩展桌面（可与 WP3 并行；4.2.2/4.2.3 后端先行 → 向导前端 → domain pack → 配方文档）
```

每个 WP 一个特性分支与独立 PR；提交信息用 `feat(wp1): ...` 风格；
文档/契约同步遵循 `AGENTS.md` 修改同步规则（改登录必须同步
`config/contracts/auth_modes.json`、`docs/auth-unified-login.md`、
`docs/deployment-ops.md`）。

## 8. 端到端完成定义（全局验收）

在干净 Docker 环境执行一次完整走查并留下记录（截图或脚本输出）：

1. `install.sh --local` → `/setup` 建管理员。
2. 邀请一个 `editor_admin` 用户并以其登录。
3. 通过向导新建 `hardware_intel` 工作台（选源+自建源+空白标签策略）。
4. 手动触发一次抓取与日报流水线；日报页打开即技术洞察版成品。
5. 导出技术洞察版 HTML 与公司 SQL 预览；SQL 通过
   `python3 scripts/validate_company_sql.py`。
6. `backup_db.sh` 成功产出备份文件。
7. 后端 `pytest` 全绿；前端 `npm run build` 通过。