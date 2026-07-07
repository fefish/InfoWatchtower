# Workspace Configuration 工作台配置模块设计

> 状态：目标态设计稿。本文是工作台、页面分区、成员、标签策略、反馈策略、成稿格式和
> domain pack 关系的后端模块事实源。旧的 `docs/backend/workspace-module-model.md` 作为细节
> 附录保留。

## 1. 模块定位

Workspace Configuration 负责定义一个团队在同一套情报主链上看到什么、能做什么、用什么配置。

工作台不是分叉产品，不复制主链表，不复制数据源定义。

```text
shared pipeline code
shared data_sources
shared users
workspace-specific:
  source links
  label policy
  feedback policy
  report formats
  sections
  memberships
```

## 2. 三个边界

```text
workspace_code          工作范围和权限边界
domain_code             内容主题板块
section/module          前端页面和可选能力入口
```

规则：

- 一个 workspace 可覆盖多个 domain。
- 一个 domain 可被多个 workspace 使用。
- section 只控制入口，不改变主链事实。

## 3. 领域对象

```text
workspaces
  code
  name
  description
  workspace_type
  default_domain_code
  enabled
  config_json

workspace_sections
  workspace_code
  section_key
  module_key
  group_key
  enabled
  sort_order
  config_json

workspace_memberships
  workspace_code
  user_id
  workspace_role
  enabled

workspace_source_links
  workspace_code
  data_source_id
  enabled
  domain_code
  source_weight
  daily_limit
  config_json
```

`workspaces.config_json` 建议包含：

```json
{
  "label_policy": {},
  "feedback_policy": {},
  "default_report_formats": [],
  "capability_overrides": {},
  "ui_preferences": {}
}
```

## 4. 工作台创建目标态

`POST /api/workspaces` 创建工作台时自动：

- 创建 `workspaces`。
- 注册核心 `workspace_sections`。
- 写默认 `label_policy`。
- 写默认 `feedback_policy`。
- 注册内置 report formats。
- 给创建者或 super_admin 加 owner。

不得：

- 复制 `data_sources`。
- 复制历史 raw/news/report 数据。
- 写死规划部标签到所有工作台且不可改。
- 自动启用所有插件页面。

## 5. 核心 sections

核心页面默认可用：

```text
dashboard
sources
ingestion-runs
news
recommendations
daily-reports
weekly-reports
exports
sync
users
audit-logs
```

资料库和协作页面可默认启用或按工作台类型启用：

```text
historical-reports
entity-milestones
quality-archive
requirements
tasks
```

插件规则：

- 插件 section 默认 `enabled=false`，除非 domain pack 明确启用。
- 前端导航必须读后端 sections。
- 插件只能做加法，不能改变数据主链。

## 6. 标签策略

`label_policy` 控制：

- 一级标签。
- 二级标签。
- 默认/兜底标签。
- 新闻结构格式。
- 模型打标阶段。
- SQL category 模式。

规则：

- 成品新闻 category 来自工作台 label policy。
- 数据源方向标签只是评分先验，不写入 `generated_news.category`。
- `planning_intel` 默认 AI 十分类和 `company_sql_v1`。
- 新工作台可复制已有策略或从空白策略开始。

## 7. 反馈策略

`feedback_policy` 控制 viewer/member 的反馈能力：

```json
{
  "viewer_can_react": true,
  "viewer_can_rate": true,
  "viewer_can_comment": true,
  "viewer_can_edit": false,
  "notify_on_comment": true,
  "notify_on_publish": false
}
```

这是 Workspace 模块和 Collaboration 模块的交界。Workspace 保存策略，
Collaboration 执行策略。

当前实现：

- 新建/seed 工作台会写入默认 `feedback_policy`。
- `GET /api/workspaces/{code}/feedback-policy` 允许 workspace viewer+ 读取。
- `PATCH /api/workspaces/{code}/feedback-policy` 允许 workspace admin/owner 或 `super_admin` 修改，并写
  `audit_logs.action = workspace.feedback_policy.update`。
- 日报条目的点赞、评分、评论已读取策略；viewer 只在对应 `viewer_can_*` 打开时可写。
- 前端 `/daily-reports` 已按当前用户工作台角色和策略禁用 viewer 不可用的反馈入口。
- 前端 `/users` 策略页已提供 `feedback_policy` 可视化编辑，保存前必须确认影响范围；
  `viewer_can_edit` 固定为 false，保存后刷新身份权限审计摘要；`GET /api/identity/permission-changes`
  会把 `workspace.feedback_policy.update` 的 before/after 解释为可读 diff，
  `POST /api/identity/permission-rollbacks` 可恢复上一版策略并写回滚审计。

## 8. report formats

工作台拥有自己的格式注册表：

```text
company_sql_v1 locked
tech_insight_v1
custom formats
```

规则：

- `company_sql_v1` 结构 locked。
- 自定义格式只影响 rendition，不影响公司 SQL 出口。
- 创建工作台时注册默认格式。

## 9. domain pack 关系（已落地为运行时策略消费）

domain pack 提供主题配置模板：

```text
domain code
label sets（shared 标签集，seed 注册）
boards + fallback_board（成稿看板）
category_keywords（分类降级关键词）
scoring.prior_keywords（评分先验）
suggested_categories
```

当前实现（`backend/app/workspaces/policy.py` + `GET /api/domain-packs`）：

- `GET /api/domain-packs` 列出可消费 pack（boards/label_sets/category_keywords/
  scoring 概要），关联方式是 `workspaces.default_domain_code`（响应含
  `associate_by` 字段）。
- 工作台内容策略按「workspace 标签策略（DB）→ 关联 domain pack →
  内置 AI 默认（= planning_intel 规则）」顺序解析，pack 的
  scoring/boards/category_keywords 分别在推荐评分先验、成稿看板 taxonomy
  （`body_json.board_taxonomy_source`）和分类降级三处被真实消费；
  消费语义详见 `config/domain_packs/README.md` 和
  `config/contracts/workspace_model.json` 的 `content_policy_resolution`。
- `config/domain_packs/hardware.json` 是完整可用样例（含 boards、
  category_keywords、中文先验关键词）。
- 自定义 `label_set_code` 会在推荐链路运行时被幂等 upsert 成
  LabelSet + 一级/二级 Label；二级标签被看板归组、分类降级关键词和评分先验
  三处消费。

pack 是解析时读取的模板而非一次性快照：工作台标签策略（DB）始终优先于 pack，
后续 pack 更新只影响未被 DB 策略覆盖的解析位点，不自动覆盖人工配置。

前端建台向导第 3 步动态加载 `GET /api/domain-packs` 属前端待办
（见 `docs/backend/backend-capability-test-matrix.md` 后续任务清单）。

## 10. 权限

| 操作 | 权限 |
|---|---|
| 查看工作台 | membership viewer+ |
| 创建工作台 | super_admin 或 editor_admin（与 `workspace_model.json` `workspace_creation` 和 `workspaces.py` `WORKSPACE_CREATOR_ROLES` 一致；editor_admin 创建者自动获得 owner membership） |
| 更新名称/描述 | owner/admin 或 super_admin |
| 停用工作台 | super_admin，内置工作台需保护 |
| 管理 sections | owner/admin |
| 管理 members | owner/admin 或 super_admin |
| 修改 label_policy | admin/owner |
| 修改 feedback_policy | admin/owner |
| 管理 source links | admin/owner |
| 管理加入码（§14） | owner/admin 或 super_admin |
| 凭码加入（§14） | 任意已登录用户（游客 403） |

## 11. API 目标态

```text
GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{code}
PATCH /api/workspaces/{code}

GET  /api/workspaces/{code}/sections
PATCH /api/workspaces/{code}/sections

GET  /api/workspaces/{code}/label-policy
PATCH /api/workspaces/{code}/label-policy

GET  /api/workspaces/{code}/feedback-policy
PATCH /api/workspaces/{code}/feedback-policy

GET    /api/workspaces/{code}/members
POST   /api/workspaces/{code}/members
DELETE /api/workspaces/{code}/members/{user_id}

GET    /api/workspaces/discover?q=...      # 发现搜索（§14.1，待实现）
GET    /api/workspaces/{code}/join-code    # 加入码（§14.2，待实现）
POST   /api/workspaces/{code}/join-code
DELETE /api/workspaces/{code}/join-code
POST   /api/workspaces/join-by-code
```

## 12. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| feedback_policy 管理入口仍需增强 | contract/API/后端权限/日报页禁用、`/users` 可视化编辑、影响确认、差异解释和回滚已完成；后续补更多对象联动 |
| sections 管理不完整 | 后端可启停 section，前端完全数据驱动 |
| 建台向导第 3 步未接 `GET /api/domain-packs` | 向导可动态列出 pack 并按 pack 初始化标签策略（前端待办） |
| 工作台配置审计不足 | 策略、成员、源 link 修改都写 audit |
| 内网部门映射工作台 | Identity 按部门自动 membership 使用本模块配置 |
| 发现搜索与加入码未实现 | `discover?q=` 与 join-code/join-by-code 按 §14 验收标准通过 |
| visibility 页面入口缺失 | `/workspace-settings` 「可见性与加入码」卡可切换 visibility 并带影响确认 |

## 13. 验收设计

- 新建工作台后自动有核心 sections、owner、label policy、feedback policy、report formats。
- 新工作台不复制数据源定义。
- 前端切工作台后页面和策略来自当前 workspace。
- viewer 反馈入口受 `feedback_policy` 控制。
- 停用工作台后不出现在普通列表，历史数据不删除。
- 修改 label policy 不影响其他工作台。
- 发现搜索与加入码按 §14.4 验收。

## 14. 发现搜索与工作台加入码（2026-07 定稿，待实现）

回答「工作台怎么搜索」「管理员邀请有没有平替」。产品设计见
`docs/product/frontend-product-design.md` §12，契约见
`config/contracts/workspace_model.json` 的 `discovery_and_subscription` 与
`join_code`。加入码与全局邀请码（`user_invites`）互补：邀请码面向未注册的具体
个人（建号 + 全局角色 + 多工作台），加入码面向已注册用户的团队自助入台
（不建号、不改全局角色、只授 viewer/member）。

### 14.1 发现搜索

- `GET /api/workspaces/discover` 增加可选 `q` 参数：对 `name` 与 `description`
  做大小写不敏感 contains 过滤；过滤范围仍严格限于 enabled 且
  `visibility=internal_public` 的工作台，private 工作台对任何关键词都不出现
  （不泄露存在性）。
- 响应结构不变（name/description/member_count/joined/workspace_role）。

### 14.2 数据模型增量（新增 alembic 迁移，不改已有列）

```text
workspace_join_codes
  id / global_id / created_at / updated_at（沿用 IdMixin/TimestampMixin 风格）
  workspace_id    fk workspaces.id
  code            str(16) unique       # 8 位大写字母+数字，剔除易混字符 0/O/1/I
  default_role    str(16)              # viewer | member，默认 viewer
  expires_at      datetime(tz) nullable  # null = 长期有效
  max_uses        int nullable           # null = 不限次数
  use_count       int default 0
  status          str(16)              # active | disabled
  created_by_id   fk users.id
  disabled_at     datetime(tz) nullable
```

约束：每个工作台同一时刻至多一个 `status=active` 的加入码；「轮换」= 单事务内
将旧 active 码置 disabled 并生成新码。历史码保留不删（审计追溯）。

### 14.3 API 与语义

```text
GET    /api/workspaces/{code}/join-code    (workspace admin/owner；super_admin 绕过)
  → 当前 active 码 {code, default_role, expires_at, max_uses, use_count,
    created_at, created_by} 或 null

POST   /api/workspaces/{code}/join-code    (workspace admin/owner；super_admin 绕过)
  body: {default_role?=viewer, expires_in_days?, max_uses?}
  → 新码；已有 active 码时视为轮换（旧码同事务置 disabled）
  default_role 只允许 viewer|member；admin/owner 必须走成员管理单人流程

DELETE /api/workspaces/{code}/join-code    (workspace admin/owner；super_admin 绕过)
  → 204，幂等停用当前 active 码

POST   /api/workspaces/join-by-code        (任意已登录用户；游客中央门 403)
  body: {code}
  → {workspace_code, workspace_name, workspace_role, joined}
```

`join-by-code` 语义：

- 码不存在 / disabled / 过期 / 达到 `max_uses`：统一 400「加入码无效或已失效」，
  同一响应体，不区分原因、不泄露目标工作台存在性（防枚举）。
- 成功：幂等 upsert membership——已有 enabled membership 保持原角色不降级
  （响应 `joined=false`）；disabled membership 以码上 `default_role` 重新启用；
  非成员按 `default_role` 建 membership。仅真实新增或重新启用时 `use_count += 1`。
- private 与 internal_public 工作台都可凭码加入；停用（enabled=false）的工作台
  按码无效处理。
- 失败尝试按「用户 + IP」限流：15 分钟窗口内 10 次失败后同窗口 429
  （复用 `login_attempts` 表机制或同构实现），防止码枚举。
- 审计动作（含 before/after membership 快照，纳入
  `config/contracts/auth_modes.json` `identity_audit_actions`）：
  `workspace.join_code.create`（生成与轮换均记此动作，轮换在 detail 中标注
  rotated_from）、`workspace.join_code.disable`、`workspace.member.join_by_code`。
- 加入码只是 membership 入口，不改变任何全局角色、RBAC 或部署形态语义；
  intranet/extranet 形态下同样可用（属工作台运营配置，不属采集/同步能力）。

前端入口：`/workspace-settings` 「可见性与加入码」设置卡（规格见
`docs/product/page-specs/frontend-page-specs.md` §19.5）与发现工作台 Modal 的
「凭码加入」区（§2 AppShell 与产品设计 §12.2）。

### 14.4 验收标准

- `discover?q=` 命中 name/description，任何关键词都不返回 private 工作台。
- admin 生成码 → 另一用户凭码加入 private 工作台成功、角色等于 default_role、
  `use_count=1`；重复加入幂等且不再计数、不降级已有角色。
- 轮换后旧码立即 400；停用后 400；过期与用尽同文案 400。
- default_role 传 admin/owner 返回 422。
- 游客凭码加入 403 并提示注册。
- 连续失败触发 429 限流。
- 生成/轮换/停用/加入全部可在 `/audit-logs` 查到；`workspace.member.join_by_code`
  审计含 before/after membership 快照（与 `workspace.member.subscribe` 同口径，
  不进入 permission-rollback 支持清单）。
