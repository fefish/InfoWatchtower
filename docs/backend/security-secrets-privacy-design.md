# Security / Secrets / Privacy 安全、密钥与隐私设计

> 状态：目标态设计稿。本文是安全横切事实源。身份登录细节见
> `docs/backend/identity-access-design.md` 和 `docs/deployment/auth-unified-login.md`；部署执行细节见
> `docs/deployment/deployment-topology.md` 和 `docs/deployment/deployment-ops.md`。

## 1. 模块定位

Security / Secrets / Privacy 负责横切约束：

- 密钥、token、cookie、`.env` 不进 Git、不进同步包、不进日志。
- 外部身份只证明“是谁”，本地 RBAC 决定“能做什么”。
- 内网 header 只在可信网关后生效。
- 公网/extranet/intranet 的数据边界可验证。
- 同步和导出不泄露内部数据。

它不替代 Identity & Access，也不替代部署文档。

## 2. 密钥分类

| 类型 | 示例 | 存放 |
|---|---|---|
| 应用 session secret | `AUTH_SESSION_SECRET` | env / secret manager |
| 数据库密码 | `POSTGRES_PASSWORD` | env / secret manager |
| OIDC client secret | `OIDC_CLIENT_SECRET` | env / secret manager |
| Sync service token | `SYNC_SERVICE_TOKENS`、`SYNC_REMOTE_TOKEN` | env / secret manager |
| LLM API key | `GENERATION_API_KEY` / `GENERATION_API_KEY_REF`（`env:VAR`/`file:/path`）；旧名 `MINIMAX_API_KEY` 兼容期保留 | env / secret manager（兜底路径）+ `llm_provider_credentials` 表**密文**（决策变更 D-2026-07-08-KEY：Fernet at rest，密钥自 `AUTH_SESSION_SECRET` HKDF 派生，super_admin UI 管理，任何 API 只回显 masked 后 4 位，整表排除在同步/导出外；工作台 `generation_policy` 仍永不含 key，见 `docs/backend/generation-provider-design.md` §9 与 `config/contracts/llm_providers.json`） |
| Paper API key | `SEMANTIC_SCHOLAR_API_KEY` | env / secret manager |
| WX bridge token | `WX_BRIDGE_TOKEN` | env / secret manager |

禁止：

- 写入 Git。
- 写入 `config/contracts`。
- 写入 sync feed 或 sync package。
- 写入 audit metadata。
- 在前端 bundle 中出现。

## 3. Secret-like 字段拦截

同步、导出、日志和审计都必须拒绝或脱敏以下字段名：

```text
token
secret
password
cookie
authorization
api_key
.env
client_secret
session
```

实现态 v1：

- 统一工具：`backend/app/core/privacy.py` 定义 `contains_secret_like_key` 和
  `redact_secret_like_values`。
- 同步 feed、手工同步包导出和同步 apply 共用 `contains_secret_like_key`：feed/package 不序列化
  secret-like payload；apply/import 遇到 secret-like payload 失败并记录错误。
- 审计入口 `write_audit` 共用 `redact_secret_like_values`：`detail_json` 中的 secret-like 值写为
  `[REDACTED]`，但保留安全字段和 workspace scope。
- 当前应用运行时日志不记录业务 payload；如果后续引入结构化日志 sink，必须复用同一个 redactor，
  不能另写规则。

同步 apply handler 如果发现 payload 含 secret-like 字段，应拒绝记录并写 `sync_inbox` 错误，
而不是静默清洗后继续导入。

## 4. Session 与 CSRF

目标态：

- session cookie 为 HttpOnly；`AUTH_SESSION_SECRET` 非空是全部 auth mode 的启动
  硬条件（API/scheduler/worker 三入口共用自检）。
- 生产默认 Secure。
- 生产默认启用 CSRF。
- CSRF 采用双提交 cookie：非 HttpOnly CSRF cookie + `X-CSRF-Token`。
- CSRF 豁免是精确端点清单，不做路径前缀泛化：邀请链路只豁免匿名
  `POST /api/auth/invites/{code}/accept`（匿名用户拿不到 CSRF cookie），
  `revoke` 等其余邀请端点照常校验。
- 改密或管理员代重置后旧 cookie 失效。
- 后续支持 session 列表、踢下线和 secret rotation。

前端不能把 session token 存入 localStorage。

## 5. OIDC 与外部身份

OIDC 必须使用 authorization code flow + PKCE。

校验（已实现，`backend/app/auth/oidc.py` `verify_id_token`）：

- state。
- nonce（userinfo 主路径下 id_token nonce 同样强制校验）。
- id_token 整体校验：拒绝 `alg=none`；有 JWKS（`OIDC_JWKS_URI` env 或 discovery
  的 `jwks_uri`）时验签 RS256/384/512（按 kid 匹配，非 RS* alg 拒绝）；
  无 JWKS 时强校验 issuer/audience/expiry/nonce。
- userinfo / id_token claims。

字段映射进入本地 `users`：

```text
external_provider
external_id
employee_no
email
display_name
department
```

权限仍由本地 roles 和 workspace membership 决定。

## 6. 内网可信 Header

`AUTH_MODE=intranet_header` 只能用于 `DEPLOY_MODE=intranet`，且必须位于可信网关后。

要求：

- 网关覆盖身份 header，不能透传用户自带 header。
- backend 不直接暴露给用户网络。
- `AUTH_TRUSTED_PROXY_CIDRS` 兜底校验已实现（`backend/app/core/security.py`
  `peer_in_trusted_proxies` 是单一信任判定点）：非空时身份头只信白名单直连 peer，
  不受信 peer 按未登录处理（401）；未配置保持旧行为并打启动 warning，非法 CIDR
  拒启。登录限流取 IP 共用同一判定，仅受信 peer 的 `X-Forwarded-For` 被采信。
- header 只用于身份解析，不直接授予管理员权限。

默认自动开通用户为 viewer，管理员权限由本地用户管理授予。

## 7. iframe 嵌入安全

内网 iframe 采用同站反向代理，不使用跨站 `SameSite=None` 放宽 cookie。

要求：

- `Content-Security-Policy: frame-ancestors` 限制门户域。
- 入口路径由门户统一代理。
- CSRF 仍启用。
- 外层注入工号、姓名、部门、邮箱 header。

## 8. 同步隐私边界

extranet -> intranet 允许：

- public-safe data_sources。
- raw_items from public sources。
- news_items。
- generated_news。
- daily/weekly reports。

intranet 永不回流（硬不变式，机器同步单向 extranet → intranet）：

- users。
- comments。
- ratings。
- editorial decisions。
- requirements。
- topic_tasks。
- internal source credentials。
- company SQL export jobs。

用户反馈类对象在任何条件下都不回流。配置/聚合类的 intranet -> extranet 回流通道
当前是 planned（未实现，明确不进 feed）；若未来设计，必须是显式审批的人工包 +
聚合或脱敏后的新 contract。

## 9. 日志和审计脱敏

日志和审计允许：

- user id。
- employee_no snapshot。
- display_name snapshot。
- action。
- object id。
- result。

禁止：

- 密码。
- OIDC code/token。
- cookie。
- sync service token。
- LLM API key。
- 原始 `.env`。
- 可能包含内部密钥的 payload 全量。

公司 SQL importer 回调 `POST /api/exports/{id}/import-receipts/callback` 只接受
`SYNC_SERVICE_TOKENS` Bearer token。该接口是机器回调，精确豁免 CSRF；人工导出、
下载和人工登记回执仍走 cookie session + RBAC + CSRF，不得把整个 `/api/exports`
泛化成 token/CSRF 豁免路径。

## 10. 备份安全

备份包含敏感数据，要求：

- 存放在受控目录。
- 不提交 Git。
- 传输加密。
- 恢复演练后清理临时副本。
- 备份访问权限不通过普通前端页面授予。

## 11. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| session rotation 未完整 | 多版本 secret 或服务端 session 支持 |
| session 管理页缺失 | 用户可查看/撤销会话 |
| 运行时结构化日志 redactor 待接入 | 当前没有业务 payload 日志 sink；后续若新增结构化日志必须复用 `app.core.privacy` |
| 真实 OIDC provider 验收缺失 | 有 provider 登录证据和 claims 映射记录 |
| 生产备份加密和权限策略需落地 | 备份目录权限和恢复演练有证据 |

## 12. 验收标准

- Git 中没有 `.env`、token、cookie、client secret。
- sync package 中没有 secret-like 字段。
- 审计详情中 secret-like 字段值写为 `[REDACTED]`。
- 生产缺 `AUTH_SESSION_SECRET` 时启动失败。
- intranet 模式不能绕过网关伪造 header。
- OIDC 登录只落本地用户和 membership，不直接越权。
- 审计日志不包含 secret-like 值。
