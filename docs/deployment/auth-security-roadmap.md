# 登录安全与 SSO 改进计划

本文说明当前登录实现、上线风险、Google SSO 和公司 IDaaS 接入方式。它补充
`docs/deployment/auth-unified-login.md`，不替代机器契约 `config/contracts/auth_modes.json`。
安全、密钥、cookie、CSRF、trusted header、同步脱敏和隐私边界的横切事实源是
`docs/backend/security-secrets-privacy-design.md`。

## 1. 当前实现状态

阶段 2 + WP1 已实现：

- `local/public_password`：账号密码登录。
- `intranet_header`：可信网关传工号和姓名，允许自动开通本地用户。
- 统一本地身份：所有外部身份都映射到 `users.external_provider + users.external_id`。
- 统一本地权限：业务授权只看 `users`、`roles`、`permissions`。
- 会话：后端签发 HttpOnly signed cookie。
- 会话过期：`AUTH_SESSION_TTL_SECONDS` 控制 cookie max-age。
- 会话失效：session payload 带 `users.updated_at` 版本，改密或管理员代重置后旧 cookie 失效。
- 密码：PBKDF2 hash，不存明文。
- 账户生命周期：管理员邀请建号、撤销邀请、改密、忘记密码恒定响应、管理员代重置临时密码。
- 登录限流：`login_attempts` 记录同一账号+IP 成功/失败，15 分钟 5 次失败后返回 429。
- 启动自检：`AUTH_MODE=public_password` 且缺 `AUTH_SESSION_SECRET` 时 API 启动失败。
- OIDC：`AUTH_MODE=oidc` 已实现通用 authorization code flow + PKCE；未配置 `OIDC_CLIENT_ID` 或 issuer/显式端点时启动/请求失败。当前身份解析优先使用 provider userinfo，id_token payload 仅作为兜底。
- 审计：登录、登出、角色变更写入 `audit_logs`。

本地 Docker 开发账号：

```text
admin / password
```

生产部署必须替换：

```text
AUTH_SESSION_SECRET
AUTH_BOOTSTRAP_ADMIN_PASSWORD
POSTGRES_PASSWORD
```

## 2. 当前公网风险

当前实现可以支撑本地开发和受保护内网试用，但还不是最终公网安全版。

公网继续补强：

- CSRF：cookie session 下，所有非 GET 请求需要 CSRF token。方案已定稿为双提交
  cookie 模式（非 HttpOnly `infowatchtower_csrf` cookie + `X-CSRF-Token` 头一致性
  校验，`AUTH_CSRF_ENABLED` 按 `DEPLOY_MODE` 取默认值），见
  `docs/deployment/deployment-topology.md` §4.3，随 P0-6 落地。
- 服务端 session：signed cookie 无法主动踢下线，建议改成 Redis/DB session。
- session 管理：补 session 列表和主动踢下线。
- 密钥轮换：支持 `AUTH_SESSION_SECRET` 多版本轮换。
- HTTPS：生产必须使用 HTTPS，cookie 必须 `Secure`，反代开启 HSTS。
- CORS：只允许正式域名。
- 后端端口：公网只暴露反向代理，不直接暴露 backend。
- 默认管理员：首次初始化后禁用 bootstrap 密码，或者要求管理员立刻改密。

## 3. Google SSO 接入方案

2026-07 升级：通用 `AUTH_MODE=oidc` 的 authorization code flow + PKCE 已实现，
id_token 校验也已落地（如实描述：拒绝 `alg=none`；配置 `OIDC_JWKS_URI` 或
discovery 有 `jwks_uri` 时对 RS256/384/512 验签，无 JWKS 时强校验
iss/aud/exp/nonce；userinfo 主路径下 id_token nonce 依然强制校验）；
本节与 §4 保留 provider 配置和 claims 字段映射说明。

统一端点与流程（provider 无关）：

```text
GET  /api/auth/oidc/start      生成 state/nonce/PKCE code_verifier，302 到 IdP
GET  /api/auth/oidc/callback   校验 state/nonce
                               -> code + code_verifier 换 token
                               -> 调 provider userinfo 获取 sub/email/name/department
                               -> ExternalIdentity(provider=oidc, external_id=sub)
                               -> 复用 AUTH_AUTO_PROVISION/AUTH_DEFAULT_ROLE 查/建用户
                               -> 签发既有本地 session cookie
```

统一 env：

```text
OIDC_ISSUER
OIDC_CLIENT_ID
OIDC_CLIENT_SECRET
OIDC_SCOPES
OIDC_REDIRECT_URL
OIDC_PROVIDER
OIDC_POST_LOGIN_REDIRECT_URL
OIDC_AUTHORIZATION_ENDPOINT
OIDC_TOKEN_ENDPOINT
OIDC_USERINFO_ENDPOINT
```

Google（本节）与公司 IDaaS（§4）是该通用 adapter 的两个 provider 特化，差异只在
字段映射和 userinfo 获取方式。

Google SSO 应使用 OpenID Connect Authorization Code Flow，避免前端直接持有长期 token。

后端新增：

```text
GET  /api/auth/google/start
GET  /api/auth/google/callback
```

流程：

```text
前端点击 Google 登录
-> 后端生成 state、nonce、PKCE
-> 重定向到 Google
-> Google 回调 code
-> 后端校验 state
-> 后端用 code 换 token
-> 校验 ID token（已实现：有 JWKS 验签 RS256/384/512；无 JWKS 强校验
   issuer/audience/expiry/nonce；拒绝 alg=none）
-> 生成 ExternalIdentity
-> 查找或创建本地 user
-> 签发 InfoWatchtower session
```

Google 字段映射：

```text
external_provider = google
external_id       = id_token.sub
email             = id_token.email
display_name      = id_token.name
```

如果只允许公司 Google Workspace，必须额外校验：

```text
email_verified = true
email domain allowlist
hosted domain claim, if configured
```

参考官方文档：

- https://developers.google.com/identity/openid-connect/openid-connect
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://www.rfc-editor.org/rfc/rfc9700.html

## 4. 公司 IDaaS 接入方案

你描述的“跳到公司内部登录，拿到 code，再请求拿工号和姓名”属于标准 OIDC/OAuth code flow。

后端新增：

```text
GET  /api/auth/idaas/start
GET  /api/auth/idaas/callback
```

配置：

```text
AUTH_MODE=intranet_oidc
IDAAS_AUTHORIZATION_URL=...
IDAAS_TOKEN_URL=...
IDAAS_USERINFO_URL=...
IDAAS_CLIENT_ID=...
IDAAS_CLIENT_SECRET=...
IDAAS_REDIRECT_URI=...
IDAAS_SCOPES=openid profile email
```

流程：

```text
前端点击公司登录
-> 后端重定向到公司 IDaaS
-> 公司 IDaaS 回调 code
-> 后端用 code 换 token
-> 后端请求 userinfo 或公司员工信息接口
-> 得到 employee_no/display_name/department/email
-> ExternalIdentity(provider=company_idaas, external_id=employee_no)
-> 本地 users/roles
-> InfoWatchtower session
```

字段映射：

```text
external_provider = company_idaas
external_id       = employee_no
employee_no       = employee_no
display_name      = name
department        = department
email             = email
```

如果公司 IDaaS 不返回标准 OIDC userinfo，可以只在 `CompanyIdaasAdapter` 里定制“token -> 工号姓名”的几次请求；后面的本地用户、角色、审计、业务逻辑不需要改。

## 5. 推荐迭代顺序

### 5.1 公网安全加固

第一批先做：

- Redis/DB session。
- CSRF token。
- Redis/DB session 与踢下线。
- `AUTH_SESSION_SECRET` 多版本密钥轮换。
- 禁止生产默认密码。

### 5.2 OAuth/OIDC 抽象

新增统一 adapter：

```python
class AuthAdapter:
    provider: str

    def start_login(self) -> RedirectResponse:
        ...

    def resolve_callback(self, request) -> ExternalIdentity:
        ...
```

第一批 provider：

- `GoogleOidcAdapter`
- `CompanyIdaasAdapter`

### 5.3 权限运营增强

继续补：

- session 列表和踢下线。
- 角色变更后强制刷新 session。
- 审计页展示登录和角色变更记录。

## 6. 部署策略

公网推荐：

```text
AUTH_MODE=public_oidc
AUTH_PASSWORD_LOGIN_ENABLED=false
```

保留一个应急管理员入口，但默认不开放普通密码登录。

公司内网推荐：

```text
AUTH_MODE=intranet_oidc
AUTH_AUTO_PROVISION=true
AUTH_DEFAULT_ROLE=viewer
```

如果短期只能由网关传 header，可以先用：

```text
AUTH_MODE=intranet_header
```

但必须保证：

- backend 不直连用户。
- 网关覆盖并清洗身份 header。
- 用户自带 header 不能穿透。

内网门户 iframe 嵌入方案已定稿（不再是零设计）：同站反向代理承载 + CSP
frame-ancestors 白名单（`EMBED_FRAME_ANCESTORS`）+ CSRF 双提交 cookie，禁止放开
SameSite=None；见 `docs/deployment/deployment-topology.md` §4 与
`docs/deployment/auth-unified-login.md` §6.1。
