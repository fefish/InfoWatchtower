# Identity & Access 身份权限模块设计

> 状态：目标态设计稿。本文是用户、登录、SSO、权限和工作台 membership 的后端模块
> 事实源。前端账号入口和用户页面布局见 `docs/product/frontend-product-design.md`。

## 1. 模块定位

Identity & Access 负责回答两个问题：

1. 这个请求是谁发起的。
2. 这个人在当前实例和当前工作台能做什么。

它不负责顶部栏怎么展示头像，不负责通知铃铛，也不负责日报/周报页面布局。

## 2. 模块边界

拥有的数据：

- `users`
- `roles`
- `permissions`
- `user_roles`
- `role_permissions`
- `workspace_memberships`
- `user_invites`
- `password_reset_tokens`
- `login_attempts`
- 与登录、权限变更相关的 `audit_logs`

拥有的能力：

- 本地账号密码登录。
- 管理员邀请、接受邀请、撤销邀请。
- 改密、忘记密码、管理员代重置。
- `must_change_password` 强制改密。
- 登录限流和会话失效。
- 通用 OIDC authorization code flow + PKCE。
- 内网可信 header 自动建号。
- 全局角色和工作台角色鉴权。
- 部署形态下的合法认证模式校验。

不拥有的能力：

- 前端账号胶囊、下拉菜单、账号页视觉。
- 评论、点赞、评分和通知收件箱。
- 同步对象 apply 逻辑。
- 工作台标签策略和页面分区。

## 3. 身份模型

所有外部身份最终都必须落到本地 `users.id`。

统一对象：

```text
ExternalIdentity
  provider
  external_id
  employee_no
  username
  display_name
  department
  email
  raw_claims
```

唯一性规则：

```text
external_provider + external_id
```

业务表只保存本地 `user_id`，不直接保存 OIDC subject、公司工号 header 或第三方 token。
审计日志可以保存外部身份快照，用于排查。

## 4. 认证模式

| 模式 | 场景 | 用户来源 | 是否自动建号 |
|---|---|---|---|
| `local` | 本地开发 | seed 或手工账号 | 可配置 |
| `public_password` | standalone/cloud 最小闭环 | 管理员邀请或 setup 首管 | 默认关闭开放注册 |
| `oidc` | cloud/extranet 标准 SSO | provider claims | 按 `AUTH_AUTO_PROVISION` |
| `intranet_header` | intranet iframe 同站反代 | 网关注入工号/姓名/部门 | 默认开启 |

四种部署形态的合法组合见 `config/contracts/deployment_modes.json`。

### 4.1 OIDC 目标态

OIDC 是外网部署和标准 SSO 的主路径。

```text
/login 展示 SSO 登录
-> GET /api/auth/oidc/start
-> provider authorization endpoint
-> GET /api/auth/oidc/callback
-> token endpoint + userinfo
-> ExternalIdentity
-> users/session
-> workspace membership 解析
-> redirect 到原目标页或 /dashboard
```

必需配置：

```text
OIDC_CLIENT_ID
OIDC_CLIENT_SECRET
OIDC_ISSUER
OIDC_SCOPES
OIDC_REDIRECT_URL
OIDC_PROVIDER
```

目标态 claims 映射：

```text
OIDC_CLAIM_EXTERNAL_ID=sub
OIDC_CLAIM_EMPLOYEE_NO=employee_no
OIDC_CLAIM_USERNAME=preferred_username
OIDC_CLAIM_DISPLAY_NAME=name
OIDC_CLAIM_DEPARTMENT=department
OIDC_CLAIM_EMAIL=email
```

自动 membership 策略：

```text
AUTH_DEFAULT_WORKSPACE_CODES=planning_intel:viewer,ai_tools:viewer
AUTH_DEPARTMENT_WORKSPACE_MAP=规划部:planning_intel:viewer,硬件部:hardware_intel:viewer
```

规则：

- 自动建号只创建本地用户和默认 membership，不自动授予 `super_admin`。
- 已存在用户再次登录时可以同步展示字段，但不自动覆盖角色。
- provider 缺少必要 claim 时应登录失败并给出可排查错误。
- 真实 provider 接入必须留存验收证据。

当前实现状态：

- `OIDC_CLAIM_*` 已支持配置化映射，支持简单 `a.b` 嵌套 claim 路径。
- 缺少 `OIDC_CLAIM_EXTERNAL_ID` 指定字段时返回可诊断错误。
- `GET /api/auth/oidc/start?next=/path` 已支持受保护的站内相对路径回跳；本地密码登录也读取
  `/login?redirect=...`。
- OIDC 浏览器流失败时已统一安全回跳 `/login?auth_error=<code>`：覆盖未配置、
  provider error、state 缺失/不匹配、token 交换失败、claims 解析失败和 membership 映射失败；
  登录页只展示固定友好文案，不暴露 provider/backend 原始细节。
- OIDC 与 `intranet_header` 自动建号后都会按
  `AUTH_DEFAULT_WORKSPACE_CODES` 和 `AUTH_DEPARTMENT_WORKSPACE_MAP` 补写
  `workspace_memberships`；规则是新增缺失 membership、必要时升级到更高工作台角色，不降级人工已有角色。
- `/users` 策略页已补当前工作台的 DB 部门映射编辑：`GET/PATCH
  /api/workspaces/{code}/auth-membership-mapping` 由 `super_admin` 管理，存入
  `workspaces.config_json.auth_membership_mapping.department_workspaces`；OIDC 和
  `intranet_header` 自动建号时会合并 env 映射和 DB 映射，同工作台取更高角色，仍不降级人工角色。
- 后端测试覆盖配置化 claim、redirect、默认/部门 membership 以及 OIDC start/callback 错误回跳。

### 4.1.1 密码管理边界

- 只有 `external_provider = local` 的本地账号可以调用 `POST /api/auth/password/change`。
- OIDC、内网 header 等外部身份的密码、MFA 和会话策略由外部身份系统管理；后端返回
  `Password is managed externally`，前端 `/account` 不展示本地改密表单。
- 管理员代重置同样只允许本地账号；外部身份只能通过 provider 或门户侧处理密码。
- `/account` 仍展示本地映射后的用户、角色、部门和工作台权限上下文，但不把外部身份资料编辑伪装成本地能力。

### 4.2 内网 header 目标态

内网部署由门户同站反向代理 iframe 承载，门户注入可信身份 header。

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

- backend 不直接暴露给最终用户。
- 网关必须覆盖并清洗身份 header。
- 进程内兜底（已实现）：`AUTH_TRUSTED_PROXY_CIDRS` 非空时身份头只信白名单内的
  直连 peer（`backend/app/core/security.py` `peer_in_trusted_proxies` 是单一信任
  判定点），不受信 peer 按未登录处理（401）；未配置保持旧行为并打启动 warning，
  非法 CIDR 启动失败。登录限流取 IP 共用同一判定，仅受信 peer 递来的
  `X-Forwarded-For` 才被采信，默认伪造 XFF 不能绕过限流。
- `DEPLOY_MODE=intranet` 必须启用 `AUTH_CSRF_ENABLED=true`。CSRF 豁免是精确
  清单：邀请链路只豁免匿名 `POST /api/auth/invites/{code}/accept`，`revoke` 等
  其余邀请端点照常 double-submit 校验。
- 内网用户评论、点赞、评分、采信、需求和任务只写内网库，不回流外网。

## 5. 权限模型

权限分两层：

```text
global role      实例级能力
workspace role   工作台内能力
```

全局角色：

| 角色 | 能力 |
|---|---|
| `super_admin` | 实例级管理、用户权限、部署同步 token、全局审计 |
| `editor_admin` | 内容生产管理者，可被加入多个工作台 |
| `analyst` | 分析成员，可参与内容研判 |
| `viewer` | 浏览者，默认只读 |

工作台角色：

| 角色 | 能力 |
|---|---|
| `owner` | 工作台最高权限，可管理成员和策略 |
| `admin` | 工作台配置、源管理、抓取、推荐、发布 |
| `member` | 采编协作、评论、评分、日报/周报编辑 |
| `viewer` | 只读；反馈能力由 `feedback_policy` 决定 |

`super_admin` 可以绕过工作台 membership，但业务页面仍应显示当前工作台上下文。
非 `super_admin` 访问带 `workspace_code` 的业务 API 时必须检查
`workspace_memberships`。

## 6. `/users` 后端能力

`/users` 页面只是前端运营入口。后端需要提供四组能力：

| 能力组 | 后端对象 | 最低操作 |
|---|---|---|
| 用户 | `users` | 查询、启停、展示字段更新、代重置密码 |
| 邀请 | `user_invites` | 创建、列表、撤销、接受 |
| 工作台成员 | `workspace_memberships` | 加入、移除、改角色；owner 移出/降权必须显式确认，最后 owner 后端禁止 |
| 权限策略 | `roles`、`permissions`、部署 auth config、工作台部门映射 | 角色矩阵只读，viewer 反馈策略和当前工作台部门映射可编辑 |

没有这四组闭环前，前端用户管理页不应展示“完整权限中心”的假象。

## 7. API 面

已实现或目标态应统一收敛到：

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/oidc/start
GET  /api/auth/oidc/callback

POST /api/auth/invites
GET  /api/auth/invites
GET  /api/auth/invites/{code}
POST /api/auth/invites/{code}/accept
POST /api/auth/invites/{code}/revoke

POST /api/auth/password/change
POST /api/auth/password/forgot
POST /api/auth/password/reset

GET   /api/users
POST  /api/users
PATCH /api/users/{id}
PATCH /api/users/{id}/roles
POST  /api/users/{id}/reset-password
GET   /api/roles

GET    /api/workspaces/{code}/members
POST   /api/workspaces/{code}/members
DELETE /api/workspaces/{code}/members/{user_id}
GET    /api/workspaces/{code}/auth-membership-mapping
PATCH  /api/workspaces/{code}/auth-membership-mapping

GET  /api/identity/permission-changes
POST /api/identity/permission-rollbacks
```

所有权限和账户变更必须写 `audit_logs`。

当前 `/api/identity/permission-changes` 读取 `audit_logs` 中的权限类动作，把
`users.roles.update`、`workspace.member.upsert/remove`、
`workspace.feedback_policy.update` 和 `workspace.auth_membership_mapping.update`
统一解释成 before/after 差异；`/api/identity/permission-rollbacks` 可按审计记录批量恢复上一版，
并再次写入 `identity.permission_rollback` 审计。回滚不绕过保护：最后一个 `super_admin`、最后一个
workspace `owner` 不会被回滚掉，owner 降权/移出仍需显式 `confirm_dangerous_change`。

## 8. 前端协作边界

前端只能消费 Identity & Access 输出的状态：

- 当前用户。
- 当前工作台 membership。
- 当前部署形态和认证模式。
- 当前用户能否看见某页面、某按钮。

前端不能自己推断：

- OIDC claims 如何映射。
- viewer 是否能评论。
- 某部门自动进入哪个工作台。
- 谁能成为管理员。

这些必须来自后端配置、contract 或 API。

## 9. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 真实 provider 证据缺失 | 至少一类 provider 完成登录、建号、membership、登出验收 |
| `/users` 策略运营深化 | 前端已有用户、邀请、成员、策略四块入口、部署层自动开通规则只读展示、当前工作台部门映射编辑、权限审计摘要、成员角色影响提示、最后 owner 前后端守护、owner 移出/降权二次确认、viewer 反馈策略编辑、权限变更 diff 解释和批量回滚；后续补真实 provider/内网门户实机验收 |

## 10. 验收设计

- public password 登录失败 5 次后返回 429。
- 邀请创建、接受、过期、撤销都有测试。
- 改密或管理员代重置后旧 cookie 失效。
- `must_change_password` 用户只能访问改密必要接口。
- 非工作台成员访问带 `workspace_code` 的业务 API 返回 403。
- viewer 对写操作返回 403，member/admin/owner 按矩阵通过。
- 权限变更审计可解释 before/after 差异，并能通过 `/api/identity/permission-rollbacks`
  恢复上一版；最后 `super_admin` 和最后 workspace `owner` 不能被回滚掉。
- OIDC 未配置 provider、provider error、state 异常、token/claims/membership 异常会回跳
  `/login?auth_error=<code>`，登录页展示固定文案，不暴露内部错误。
- intranet header 模式必须通过可信网关注入身份，直接伪造 header 不应成为生产路径。
