# 公网与内网统一登录设计

InfoWatchtower 要同时支持公网部署和公司内网部署。两边都要登录，但不能写两套业务权限系统。

本文是身份接入专题，说明不同外部认证方式如何映射到本地用户。完整用户、角色、
邀请、membership、权限矩阵和验收设计见 `docs/backend/identity-access-design.md`。
部署形态合法组合见 `docs/deployment/deployment-topology.md`。

机器可读配置在：

- `config/contracts/auth_modes.json`

公网安全加固、Google SSO 和公司 IDaaS code flow 的后续计划见：

- `docs/deployment/auth-security-roadmap.md`

## 1. 核心原则

- 外部认证只回答“这个人是谁”。
- InfoWatchtower 本地 RBAC 回答“这个人能做什么”。
- 所有业务表只绑定本地 `user_id`。
- 审计日志额外保存工号、姓名、外部身份快照。
- 公网登录和内网登录共用同一张 `users`、同一套 `roles/permissions`、同一套 session/JWT 发行逻辑。

## 2. 统一身份模型

本地用户表建议字段：

- `id`
- `external_provider`
- `external_id`
- `employee_no`
- `email`
- `username`
- `display_name`
- `department`
- `status`
- `is_active`
- `last_login_at`

统一身份对象：

```python
class ExternalIdentity:
    provider: str
    external_id: str
    employee_no: str | None
    email: str | None
    username: str | None
    display_name: str
    department: str | None
    raw_claims: dict
```

`external_provider + external_id` 是外部身份唯一键。公司内网一般用工号作为 `external_id`；公网账号可以用 email、OAuth subject 或 username。

## 3. 支持模式

第一阶段至少实现：

- `local`：本地开发账号。
- `public_password`：公网账号密码登录。
- `intranet_header`：内网可信网关传工号姓名。

预留（契约中标注 `status: planned`，零实现，不是合法 `AUTH_MODE` 取值）：

- `public_oidc`
- `intranet_oidc`
- `intranet_saml`

当前代码已实现通用 `AUTH_MODE=oidc`（当前合法 `AUTH_MODE` 集合为
`local/public_password/oidc/intranet_header`）：`GET /api/auth/oidc/start` 生成
state/nonce/PKCE code verifier 并跳转 IdP，`GET /api/auth/oidc/callback` 校验 state、
交换 token、校验 id_token（一旦返回即整体校验：拒绝 `alg=none`；配置
`OIDC_JWKS_URI` 或 discovery 有 `jwks_uri` 时验签 RS256/384/512，否则强校验
iss/aud/exp/nonce）、读取 userinfo（或 id_token payload 兜底）、映射成本地
`ExternalIdentity` 后签发现有 session cookie。需要配置 `OIDC_CLIENT_ID`，以及
`OIDC_ISSUER` 或显式 `OIDC_AUTHORIZATION_ENDPOINT/OIDC_TOKEN_ENDPOINT`；可选
`OIDC_JWKS_URI/OIDC_USERINFO_ENDPOINT/OIDC_PROVIDER/OIDC_POST_LOGIN_REDIRECT_URL`。当前已支持
`OIDC_CLAIM_*` 配置化 claim 映射、`AUTH_DEFAULT_WORKSPACE_CODES` 默认工作台
membership、`AUTH_DEPARTMENT_WORKSPACE_MAP` 部门到工作台 membership 映射，以及
`/api/auth/oidc/start?next=/path` 站内相对路径回跳。OIDC 浏览器流失败统一回跳
`/login?auth_error=<code>`，覆盖未配置、provider error、state 缺失/不匹配、token 交换失败、
claims 解析失败和 membership 映射失败；登录页只展示固定友好文案，不暴露 provider 或后端
原始错误。实现级规格见 `docs/deployment/deployment-topology.md` §4.4。

`AUTH_MODE` 的合法取值还受部署形态约束：`DEPLOY_MODE=intranet` 强制
`intranet_header`，四种形态的合法组合见 `config/contracts/deployment_modes.json`。

## 4. 同源接入流程

所有模式统一走这一条后端流程：

1. `AuthAdapter` 从请求、账号密码、OIDC claim、SAML attribute 或可信 header 中解析 `ExternalIdentity`。
2. `IdentityResolver` 使用 `external_provider + external_id` 查 `users`。
3. 不存在且允许自动开通时创建用户。
4. 同步姓名、邮箱、部门等展示字段。
5. 不自动覆盖角色。
6. 按默认工作台和部门映射补写缺失的 `workspace_memberships`，只新增或升级，不降级人工已有角色。
7. 统一签发 InfoWatchtower 自己的 session/JWT。
8. 后续业务接口只看 session/JWT 里的本地 `user_id`。
9. 权限判断走本地 RBAC。

`AUTH_DEFAULT_WORKSPACE_CODES` 和 `AUTH_DEPARTMENT_WORKSPACE_MAP` 的脱敏摘要会通过
`GET /api/meta/runtime.auth_membership_mapping` 下发给前端，只用于 `/users` 策略页只读展示，
不包含 provider secret、token 或 cookie。

## 5. 公网部署

公网部署建议：

- 当前最小闭环支持 `AUTH_MODE=public_password`。
- 正式公网推荐切到 OIDC provider，接入 Google、企业微信、飞书、GitHub、Microsoft Entra ID 等。
- 首个超级管理员仍可由 `AUTH_BOOTSTRAP_ADMIN_*` 创建；已有用户时 seed 不覆盖。
- 没有 bootstrap 密码且 `users` 表为空时，前端会进入 `/setup`，由 `POST /api/setup`
  创建首个 `super_admin`；已有任意用户后 `/api/setup` 返回 410。
- 注册默认关闭，由超级管理员创建邀请链接。
- 已实现登录限流（取 IP 只在直连 peer 属于 `AUTH_TRUSTED_PROXY_CIDRS` 时才采信
  `X-Forwarded-For`，默认伪造 XFF 不能绕过限流窗口）、签名 cookie max-age、改密后旧
  cookie 失效和 `AUTH_SESSION_SECRET` 启动自检（覆盖全部 auth mode，API/scheduler/
  worker 三入口共用）；`APP_ENV=production` 还要求 `DATABASE_URL`。公网仍应由
  HTTPS/Caddy 提供 Secure Cookie 传输环境。

公网环境变量示例：

```text
AUTH_MODE=public_password
AUTH_SESSION_SECRET=...
AUTH_SESSION_COOKIE_SECURE=true
AUTH_AUTO_PROVISION=false
AUTH_DEFAULT_ROLE=viewer
```

### 5.1 账户生命周期

已实现的公网账号流程：

- `POST /api/auth/invites`：超级管理员创建邀请，必须显式指定全局角色和工作台角色，
  服务层不会给未指定目标兜底到任何默认租户。
- `GET /api/auth/invites/{code}`：公开查询邀请状态，只返回 email hint。
- `POST /api/auth/invites/{code}/accept`：匿名用户建号，接受后直接写本地用户、
  全局角色和 `workspace_memberships`，并签发 session。
- `POST /api/auth/invites/{code}/revoke`：撤销未接受邀请。
- `POST /api/auth/password/change`：本地用户改密；`must_change_password` 用户只允许
  访问 `/api/auth/me`、`/api/auth/logout` 和该改密接口。
- `POST /api/auth/password/forgot`：恒定 200。无 SMTP 时只写审计，不创建 token。
- `POST /api/auth/password/reset`：校验哈希 token；当前无 SMTP 时主要供后续 provider 接入。
- `POST /api/users/{id}/reset-password`：超级管理员生成一次性临时密码，用户状态置
  `must_change_password`。
- `PATCH /api/users/{id}`：超级管理员启停用户或修改展示字段。

登录限流使用 `login_attempts` 表：同一 `username + ip` 在 15 分钟窗口内 5 次失败后
返回 429；成功登录会切断当前失败窗口。session payload 带 `users.updated_at` 版本，
改密或管理员代重置后旧 cookie 失效。

### 5.2 工作台 membership 权限

全局角色仍用于系统级能力，`super_admin` 可绕过工作台 membership。带
`workspace_code` 的业务 API 需要 `workspace_memberships`：

```text
viewer -> 只读
member -> 采信/编辑等工作台写操作
admin  -> 工作台管理
owner  -> 工作台所有者
```

当前后端已把集中 helper 接入主要工作台业务入口：

- `viewer`：工作台 sections/label policy 读取、数据源列表、news/dedupe、ingestion/
  recommendation 运行记录、日报/周报读取、成稿格式列表、rendition 导出、导出历史与
  trace。
- `member`：日报/周报发布、日报/周报条目编辑、点赞/评分/评论、日报生成稿重跑、
  周报草稿创建、rendition 重生成、公司 SQL 导出。
- `admin`：工作台标签策略更新、自建源创建/编辑/链接、news normalize、ingestion/
  backfill/recommendation/pipeline run、成稿格式创建/更新/删除。

不带 `workspace_code` 的全局列表（例如全局 ingestion/recommendation/export 列表）仍只允许
`super_admin`。后续新增业务路由必须复用同一 helper，不要散落手写判断。

## 6. 公司内网部署

如果公司内部已有门户/网关可以拿到工号和姓名，最轻接入方式是 `intranet_header`：

```text
AUTH_MODE=intranet_header
AUTH_HEADER_EMPLOYEE_NO=X-Employee-No
AUTH_HEADER_DISPLAY_NAME=X-Employee-Name
AUTH_HEADER_DEPARTMENT=X-Department
AUTH_HEADER_EMAIL=X-Email
AUTH_AUTO_PROVISION=true
AUTH_DEFAULT_ROLE=viewer
```

安全要求：

- `intranet_header` 只能部署在可信网关后面。
- 后端服务不能直接暴露给用户绕过网关访问。
- 网关必须覆盖并清洗这些身份 header，不能允许客户端自带 header 穿透
  （门户侧样例见 `deploy/nginx.portal.example.conf`；系统自带的
  `frontend/nginx.conf` 也会在 `/api/` 反代处把外部传入的身份头置空）。
- 进程内兜底（已实现）：`AUTH_TRUSTED_PROXY_CIDRS` 非空时身份头只信白名单直连
  peer，不受信 peer 的请求按未登录处理（401）；未配置保持旧行为并打启动
  warning，非法 CIDR 拒启。登录限流取 IP 共用同一判定，只有受信 peer 递来的
  `X-Forwarded-For` 才被采信。

### 6.1 内网门户 iframe 嵌入（已定稿）

内网部署（`DEPLOY_MODE=intranet`）被公司门户 iframe 嵌入的方案已定稿，实现级规格见
`docs/deployment/deployment-topology.md` §4：

- **承载方式**：门户 nginx 同站路径反向代理（`https://portal.example.com/watchtower/`
  代理到前端容器，`/watchtower/api/` 代理到 backend），iframe 的 src 与门户同源
  （同站），SameSite=lax cookie 原样可用；**禁止**放开 SameSite=None。门户侧样例
  配置见 `deploy/nginx.portal.example.conf`。
- **frame-ancestors**：`EMBED_FRAME_ANCESTORS`（默认 `'self'`）经
  SecurityHeadersMiddleware 输出 `Content-Security-Policy: frame-ancestors <白名单>`，
  前端 nginx 镜像输出同一 header。
- **CSRF 双提交 cookie**：登录成功/`GET /api/auth/me` 时下发非 HttpOnly 的
  `infowatchtower_csrf` cookie；`AUTH_CSRF_ENABLED=true` 时非安全方法必须携带一致的
  `X-CSRF-Token` 头，否则 403。豁免清单是精确列表：`/api/auth/login`、`/api/setup`、
  `/api/sync/feed*`、`/api/exports/{id}/import-receipts/callback` 等 token 鉴权端点，
  以及邀请链路里**仅匿名 accept 一个端点**
  （`POST /api/auth/invites/{code}/accept`，匿名用户拿不到 CSRF cookie）；
  `POST /api/auth/invites/{code}/revoke` 等其余邀请端点走正常 double-submit 校验，
  不因路径前缀被整体豁免。intranet/extranet/cloud 默认开启，standalone 默认关闭。
- **外层登录态复用**：iframe 同站承载后，`intranet_header` 的「网关注入工号/姓名/
  部门头 → 自动建号 → 签发本地 cookie」链路原样可用，评论/点赞/评分自然携带外层
  身份；评论数据留在 intranet 库，不回流公网。

如果公司内部是 IDaaS，推荐后续接 `intranet_oidc`：

```text
前端跳转公司 IDaaS
-> 回调 code 到后端
-> 后端换 token
-> 后端请求 userinfo 或员工接口拿工号姓名
-> 映射 ExternalIdentity
-> 落到本地 users/roles
```

这部分只需要新增 `CompanyIdaasAdapter`，业务权限体系不用重写。

## 7. 权限角色

统一角色建议：

- `super_admin`
- `editor_admin`
- `analyst`
- `viewer`

公网和内网共用这些角色。区别只在身份来源，不在业务权限模型。

## 8. 审计

所有关键行为写 `audit_logs`：

- 登录
- 数据源增删改
- 日报/周报编辑、发布、锁定
- SQL 导出
- 专题任务指派
- 权限调整

审计字段至少包含：

- `user_id`
- `external_provider`
- `external_id_snapshot`
- `employee_no_snapshot`
- `display_name_snapshot`
- `action`
- `object_type`
- `object_id`
- `before_json`
- `after_json`
- `created_at`
