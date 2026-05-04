# 公网与内网统一登录设计

InfoWatchtower 要同时支持公网部署和公司内网部署。两边都要登录，但不能写两套业务权限系统。

机器可读配置在：

- `config/contracts/auth_modes.json`

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

预留：

- `public_oidc`
- `intranet_oidc`
- `intranet_saml`

## 4. 同源接入流程

所有模式统一走这一条后端流程：

1. `AuthAdapter` 从请求、账号密码、OIDC claim、SAML attribute 或可信 header 中解析 `ExternalIdentity`。
2. `IdentityResolver` 使用 `external_provider + external_id` 查 `users`。
3. 不存在且允许自动开通时创建用户。
4. 同步姓名、邮箱、部门等展示字段。
5. 不自动覆盖角色。
6. 统一签发 InfoWatchtower 自己的 session/JWT。
7. 后续业务接口只看 session/JWT 里的本地 `user_id`。
8. 权限判断走本地 RBAC。

## 5. 公网部署

公网部署建议：

- 默认 `AUTH_MODE=public_password`。
- 后续可切 `AUTH_MODE=public_oidc` 接入企业微信、飞书、GitHub、Microsoft Entra ID 等。
- 管理员后台创建初始超级管理员。
- 注册可以默认关闭，由管理员邀请或手动创建用户。

公网环境变量示例：

```text
AUTH_MODE=public_password
AUTH_SESSION_SECRET=...
AUTH_AUTO_PROVISION=false
AUTH_DEFAULT_ROLE=viewer
```

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
- 网关必须覆盖并清洗这些身份 header，不能允许客户端自带 header 穿透。

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
