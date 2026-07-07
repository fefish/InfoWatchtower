# Collaboration / Feedback / Notifications 协作通知模块设计

> 状态：目标态设计稿。本文是评论、点赞、评分、活动事件和通知模块的后端设计事实源。
> 顶部铃铛、消息入口和页面呈现见 `docs/product/frontend-product-design.md`。

## 1. 模块定位

协作通知模块负责把用户对情报对象的反馈沉淀成可追溯的数据流：

```text
阅读/采编行为
-> reaction / rating / comment / editorial action
-> activity_event
-> notification
-> 用户回到对象继续处理
```

它不是“顶部铃铛”。顶部铃铛只是通知模块完成后在前端壳里的快捷入口。

## 2. 模块拆分

| 子模块 | 职责 |
|---|---|
| Feedback | 点赞、收藏、评分等轻反馈 |
| Comments | 评论、回复、@ 提及、对象讨论 |
| Activity Events | 记录发生过的协作事实，作为通知和热度的来源 |
| Notifications | 面向用户的未读消息、已读、归档和跳转 |
| Feedback Policy | 控制 viewer/member/admin 在工作台内能否反馈 |

## 3. 当前状态

已实现最小反馈 API：

```text
POST /api/daily-report-items/{id}/reactions
POST /api/daily-report-items/{id}/ratings
GET  /api/daily-report-items/{id}/comments
POST /api/daily-report-items/{id}/comments
```

已补工作台反馈策略薄片：

```text
GET   /api/workspaces/{code}/feedback-policy
PATCH /api/workspaces/{code}/feedback-policy
```

`feedback_policy` 已写入 `workspaces.config_json` 和 `config/contracts/workspace_model.json`；
日报条目的点赞、评分、评论写入会读取该策略：viewer 在 `viewer_can_*` 打开时可反馈，
策略关闭时仍需 workspace member+。前端 `/daily-reports` 已读取策略并禁用 viewer 不可用入口。

已实现站内通知最小闭环：

```text
GET  /api/activity-events?workspace_code=...
GET  /api/notifications?status=unread|read|archived|all
GET  /api/notifications/unread-count
POST /api/notifications/{notification_id}/read
POST /api/notifications/{notification_id}/archive
POST /api/notifications/read-all
GET  /api/notification-preferences?workspace_code=...
PATCH /api/notification-preferences
GET  /api/object-watchers?object_type=...&object_id=...
PATCH /api/object-watchers
```

`activity_events` 与 `notifications` 已落库，契约见 `config/contracts/notifications.json`。
日报条目的点赞和评分会写 activity event，但不产生逐条通知；日报条目评论会写
`comment.created/comment.replied` activity event，并给同一条目已有可见评论参与者和被回复人生成
`in_app` unread notification（排除操作者本人）；日报条目关注者也会收到同条目评论通知，若同一评论已触发
`comment.mentioned` 则不重复生成普通评论通知。前端已提供 `/notifications` 页面，并在
AppShell 顶部恢复真实未读数铃铛；未读数来自后端 API，失败时只降级为 0，不渲染假红点。
同步冲突创建时会写 `sync_conflict.created` activity event，并给 active `super_admin` 以及目标
工作台 owner/admin 生成 `important` 站内未读通知。
失败源自动重试队列到期或达到最大尝试次数时会写
`ingestion.failed_source_retry_due/ingestion.failed_source_retry_blocked` activity event，并给
active `super_admin` 以及目标工作台 owner/admin 生成 `important` 站内未读通知；通知跳转由后端
解析为 `/ingestion-runs?run_id=...`，用于直接查看对应抓取 run。
日报/周报发布时会在 `feedback_policy.notify_on_publish=true` 的工作台写
`daily_report.published/weekly_report.published` activity event，并给同一工作台除操作者外的活跃成员生成
站内通知；重复发布已发布报告不会重复推送。
周报条目 PATCH 发生真实采信或编辑快照变化时，会写 `weekly_report_item.updated` activity event，
记录 `changed_fields/before/after`，并给同一工作台除操作者外的活跃成员和周报条目关注者生成站内通知；
无实际变化的 PATCH 不生成通知。
`object_watchers` 已作为本地对象订阅表落地，v1 支持 `daily_report_item`、`weekly_report_item`
和 `dedupe_group`；
日报详情抽屉和周报条目动作区可以读取当前用户关注状态和关注人数，并通过 `PATCH /api/object-watchers`
关注或取消关注。候选池 `/news` 的候选详情区也可以读取 `dedupe_group` 关注状态；当被关注候选通过
候选池批量采信或批量剔除产生真实 `daily_report_item` 新增/采信状态变化时，后端写
`dedupe_group.adoption_changed` activity event，并给该候选关注者生成站内通知。
通知 API 已在 `NotificationRead` 中返回后端统一解析的 `target_label/target_path`。前端消息页只渲染
这两个字段，不再根据 event type 自己拼 query。当前 target resolver 覆盖日报条目、评论、日报报告、
周报报告、周报 item、同步冲突、任务和需求：日报条目通知会生成
`/daily-reports?item_id=...`，评论通知额外带 `comment_id` query，日报页会给命中的评论行添加高亮和
`aria-current` 标记；发布通知会分别跳到 `/daily-reports?report_id=...` 和
`/weekly-reports?report_id=...`；周报 item 通知会跳到 `/weekly-reports?item_id=...` 并由周报页高亮命中条目；
同步冲突通知会跳到 `/sync?conflict_id=...`，同步页会高亮对应 open conflict 行。
`notification_preferences` 已实现为当前用户、工作台、事件类型的偏好表；缺省为站内通知开启。
后端生成通知前会检查收件人的 `in_app_enabled`，关闭后只影响未来通知，不删除既有未读消息。
前端 `/notifications` 已提供当前工作台的站内通知偏好开关。`email_enabled` 字段目前只存储，
邮件投递通道尚未启用。
通知支持单条归档：`POST /api/notifications/{id}/archive` 会把 unread/read 转为 `archived`，
归档后的通知不再出现在 unread/read/all active 收件箱，但可在 `/notifications` 的“归档”筛选中查看。

这些能力支撑“日报条目评论参与者/关注者被提醒”“日报评论 @ 提及提醒被提及用户”
“同步冲突提醒管理员”“失败源自动重试到期/阻塞提醒管理员”“报告发布提醒工作台成员”
“周报条目更新提醒工作台成员/关注者”和“任务指派提醒被指派人”的第一阶段闭环，
尚未覆盖邮件投递和更多对象的通知生成/提及。

## 4. 反馈对象范围

目标态反馈对象不应只绑定日报条目。需要支持：

| 对象 | 反馈类型 |
|---|---|
| `daily_report_item` | 点赞、评分、评论、回复、@ 提及 |
| `weekly_report_item` | 点赞、评分、评论、回复、@ 提及 |
| `news_item` / `dedupe_group` | 运营复核、噪声反馈、候选讨论 |
| `requirement` | 评论、状态讨论、@ 提及 |
| `topic_task` | 评论、指派、状态变更通知 |
| `sync_conflict` | 处置讨论、管理员通知 |

第一阶段可以优先完成日报/周报条目，数据模型要能扩展到其他对象。

## 5. 工作台反馈策略

普通浏览用户是否能点赞、评分、评论，不应写死在角色里。建议放入
`workspaces.config_json.feedback_policy`。

```json
{
  "feedback_policy": {
    "viewer_can_react": true,
    "viewer_can_rate": true,
    "viewer_can_comment": true,
    "viewer_can_edit": false,
    "notify_on_comment": true,
    "notify_on_publish": false
  }
}
```

默认建议：

| 部署形态 | viewer 反馈策略 |
|---|---|
| standalone | 管理员配置，默认可反馈 |
| cloud | 可点赞、评分、评论，不可编辑 |
| extranet | 默认只读，可由管理员打开反馈 |
| intranet | 可点赞、评分、评论，反馈留内网本地 |

## 6. 数据模型目标态

当前已有 `reactions`、`ratings`、`comments` 等表时，应优先复用并扩展，不重复建表。

建议新增或补齐：

```text
activity_events
  id
  workspace_code
  domain_code
  actor_user_id
  event_type
  object_type
  object_id
  target_object_type
  target_object_id
  summary
  metadata_json
  sync_policy
  created_at

notifications
  id
  user_id
  workspace_code
  activity_event_id
  status          unread / read / archived
  priority        normal / important
  delivery_channel in_app
  read_at
  created_at

notification_preferences
  id
  user_id
  workspace_code
  event_type
  in_app_enabled
  email_enabled

object_watchers
  id
  user_id
  workspace_code
  object_type       daily_report_item / weekly_report_item / dedupe_group in v1
  object_id
  active
```

同步原则：

- v1 协作与通知对象是本地用户/工作台状态，不进入 extranet feed object types。
- `comments`、`reactions`、`ratings`、`activity_events`、`notifications`、
  `notification_preferences`、`object_watchers` 直接请求 `GET /api/sync/feed` 必须返回 400。
- 当前日报反馈产生的 activity event 默认 `sync_policy=local_only`；即便某条
  activity event 被误标为 `sync_allowed`，也不能通过 feed 下发。
- `notifications` 是本地用户收件箱，不跨实例同步。
- extranet 下发到 intranet 的成稿对象可以在 intranet 本地产生新的反馈和通知。

## 7. 事件类型

建议事件枚举：

```text
comment.created
comment.replied
comment.mentioned
reaction.created
rating.created
report_item.adoption_changed
report_item.editor_override_changed
daily_report.published
weekly_report.published
weekly_report_item.updated
dedupe_group.adoption_changed
requirement.created
requirement.status_changed
task.assigned
task.status_changed
sync_conflict.created
ingestion.failed_source_retry_due
ingestion.failed_source_retry_blocked
```

点赞和评分默认只进入 activity event，不逐条生成通知，避免噪音。评论、@ 提及、任务指派、
同步冲突默认生成通知。当前日报评论 `@username` 会解析同工作台启用成员的
`username/employee_no/external_id`，生成 `comment.mentioned` important 通知。当前 `task.assigned` 已落地：
创建或更新任务负责人时，负责人必须是同工作台启用成员；
后端生成 `task.assigned` activity event，并给非操作者本人发站内通知。当前
`requirement.status_changed` 已落地：需求 owner 必须是同工作台启用成员，状态变化会通知 owner。

## 8. 通知生成规则

| 事件 | 收件人 |
|---|---|
| 一级评论 | 既有可见评论参与者、被 @ 用户、日报条目关注者 |
| 回复评论 | 被回复人、楼主、被 @ 用户 |
| @ 提及 | 被提及用户，priority=important |
| 采信状态变更 | 条目相关协作者、report owner |
| 编辑覆盖字段变更 | 条目相关协作者 |
| 周报条目更新 | 同工作台活跃成员和周报条目关注者，排除操作者 |
| 候选采信/剔除 | dedupe group 关注者，排除操作者 |
| 日报/周报发布 | 可配置通知工作台成员 |
| 需求状态变化 | 需求 owner |
| 任务指派 | 被指派人 |
| 同步冲突 | `super_admin`、工作台 owner/admin |
| 失败源自动重试到期/阻塞 | `super_admin`、工作台 owner/admin |

收件人必须过滤：

- 当前工作台 membership。
- 用户是否仍 active。
- notification_preferences。
- 对象 `visibility_scope`。

失败源告警幂等规则：

- `ingestion.failed_source_retry_due` 按 base `ingestion_run_id + attempt_count` 只发一次，避免同一轮到期重复打扰。
- `ingestion.failed_source_retry_blocked` 在达到最大尝试次数时只发一次，提示人工检查源配置、网络、凭证或 adapter。
- 告警不携带 credential、fetch config、cookie、token 或完整 raw payload，只包含 run id、run key、
  run type、失败源数量、尝试次数、下一次重试时间和最近 retry run。

## 9. API 目标态

反馈与评论：

```text
POST /api/{object_type}/{id}/reactions
POST /api/{object_type}/{id}/ratings
GET  /api/{object_type}/{id}/comments
POST /api/{object_type}/{id}/comments
POST /api/comments/{id}/replies
PATCH /api/comments/{id}
DELETE /api/comments/{id}
```

活动与通知：

```text
GET  /api/activity-events
GET  /api/notifications
GET  /api/notifications/unread-count
POST /api/notifications/{id}/read
POST /api/notifications/read-all
GET  /api/notification-preferences
PATCH /api/notification-preferences
GET  /api/object-watchers
PATCH /api/object-watchers
```

前端顶部铃铛恢复的最低 API：

```text
GET /api/notifications/unread-count
GET /api/notifications?limit=10
POST /api/notifications/{id}/read
POST /api/notifications/{id}/archive
```

这些最低 API 已实现，因此顶部铃铛可以显示真实未读数；未来新增下拉扩展或更多跨对象跳转前，
仍必须先补对应后端 API 和契约，不得用前端本地状态模拟。

## 10. 前端协作边界

前端可以做：

- 在日报/周报对象上展示评论、点赞、评分。
- 根据 `feedback_policy` 隐藏或禁用反馈入口。
- 在日报/周报条目和候选 dedupe group 上展示真实关注状态，并调用 object watcher API 关注/取消关注。
- 通知模块完成后，在顶部展示未读数。
- 点击通知跳转到具体对象和评论位置。

前端不能做：

- 自己判断谁应该收到通知。
- 用本地数组模拟未读消息。
- 用红点表示不存在的后端状态。
- 把点赞默认当作逐条消息提醒。

## 11. 与热度评分的关系

反馈数据有两个消费者：

1. Collaboration / Notifications：用于协作流转和用户提醒。
2. Recommendation / Scoring：用于后续 `heat_score`、`feedback_score`。

推荐评分可以读取聚合后的反馈特征，但不能修改原始评论、评分和通知状态。
评分细节仍见 `docs/backend/feedback-heat-scoring.md`。

## 12. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| viewer 反馈策略深化 | 已有 contract/API/后端检查/日报页禁用规则和 `/users` 策略编辑入口；后续补更多对象和部署形态差异验证 |
| 反馈对象范围过窄 | 日报/周报条目以外对象有统一扩展方式 |
| activity event 覆盖不足 | 已覆盖日报条目点赞/评分/评论、同步冲突、日报/周报发布；后续采信、编辑、任务也会写 activity event |
| 通知模块深化 | 已有未读/已读/归档 API、未读数、全部已读、日报评论通知、日报评论 @ 提及通知、日报条目关注者通知、同步冲突通知、日报/周报发布通知、周报条目更新通知、周报条目关注者通知、候选采信/剔除通知、任务指派通知、需求状态通知、后端 target_path、日报条目级锚点、周报 item 锚点、候选池 dedupe_group 锚点、报告级锚点、同步冲突锚点、任务锚点、需求锚点、object watcher API 和站内通知偏好；后续补邮件投递和更多对象的通知生成/提及 |
| 前端消息页深化 | `/notifications` 已可查看和处理站内通知，按后端 `target_path` 打开对应对象；日报条目通知和提及通知可打开对应条目并高亮命中评论，日报/周报发布通知可打开对应报告，周报条目更新通知可打开并高亮命中条目，同步冲突通知可打开并高亮 open conflict，任务指派通知可打开并高亮命中任务，需求状态通知可打开并高亮命中需求，可归档单条通知，并能设置站内通知偏好；后续补更多对象通知生成/提及 |
| 内外网反馈边界 | `comments/reactions/ratings/activity_events/notifications/notification_preferences/object_watchers` 不进入 feed manifest，直接请求 feed 返回 400；后续补端到端实机同步证据 |

## 13. 验收设计

- viewer 在允许策略下可评论、点赞、评分；关闭策略后返回 403 或前端隐藏入口。
- 用户 A 评论并 @ 用户 B，B 获得 unread notification。
- 用户 A 关注日报条目后，其他用户评论该条目，A 获得 unread notification；取消关注后不再收到该对象关注通知。
- 用户 A 关注周报条目后，其他用户更新该条目，A 获得 `weekly_report_item.updated` unread notification。
- 用户 A 关注候选 dedupe group 后，其他用户批量采信或剔除该候选，A 获得
  `dedupe_group.adoption_changed` unread notification，目标路径为 `/news?dedupe_group_id=...`。
- 用户 B 点击通知能定位到后端 `target_path` 指定对象；任务指派通知进入 `/tasks?task_id=...` 并高亮命中任务，周报 item 通知进入 `/weekly-reports?item_id=...` 并高亮命中条目。
- 顶部铃铛未读数来自 `GET /api/notifications/unread-count`，没有后端返回时不能显示假红点。
- 点赞和评分只写 activity event，不默认产生逐条通知。
- 日报发布可按工作台策略通知成员。
- sync conflict 创建后通知管理员。
- `DEPLOY_MODE=intranet` 下产生的评论、点赞、评分、通知和对象关注关系不会进入 sync feed；负向回归测试为
  `backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_local_collaboration_notifications`。
- 通知已读后 unread count 减少。
