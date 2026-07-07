# Sync Conflict & Distribution 同步分发与冲突处置设计

> 状态：目标态设计稿。本文是 extranet/intranet 数据分发、同步冲突、人工处置和同步审计
> 的后端模块事实源。部署形态和能力开关见 `docs/deployment/deployment-topology.md`，同步数据边界
> 见 `docs/deployment/multi-environment-sync.md`。

## 1. 模块定位

Sync Conflict & Distribution 负责让不同部署实例之间按边界同步数据，并在冲突时可解释、
可处置、可审计。

目标主路径：

```text
extranet publisher
-> GET /api/sync/feed
-> intranet consumer pull
-> sync_inbox
-> apply handlers
-> sync_conflicts, if needed
-> local readable reports and records
```

人工 fallback：

```text
export zip package
-> download
-> intranet upload/import
-> same apply handlers
```

## 2. 数据 owner 边界

| 数据 | 默认 owner | 是否下发 |
|---|---|---|
| 公网数据源非密钥定义 | extranet | 是 |
| 公网 raw/news/generated/daily/weekly | extranet | 是 |
| 内网用户、角色、membership | intranet | 否 |
| 内网评论、点赞、评分 | intranet | 否 |
| 内网采信、编辑意见 | intranet | 默认否 |
| 内网需求、任务 | intranet | 否 |
| 公司 SQL 导出记录 | intranet | 否 |
| 同步冲突处置记录 | 当前实例 | 否，除非明确设计 |

规则：

- 同步默认是 public/extranet -> intranet。
- intranet 是 pull-only，不向 extranet 回流业务反馈。
- 密钥、cookie、token、`.env` 不进入 feed、包或 inbox payload。

## 3. 同步对象顺序

应用顺序必须保证外键依赖：

```text
1 data_sources
2 raw_items
3 news_items
4 generated_news
5 daily_reports(+items)
6 weekly_reports(+items)
```

后续可扩展：

```text
report_formats
report_renditions
historical_reports
tracked_entities / entity_milestones
```

但每新增对象必须先定义 owner、可见性、外键顺序和冲突策略。

## 4. Envelope 契约

feed 和 package 使用同构 envelope：

```text
event_id
source_instance_id
object_type
object_global_id
operation          upsert / delete
revision
content_hash
updated_at
payload_json
visibility_scope
sync_policy
```

`event_id` 应由 `object_type + global_id + revision` 确定性生成，保证重放幂等。

## 5. sync_inbox 语义

```text
new envelope -> applied
new envelope -> skipped
new envelope -> conflict
new envelope -> failed
failed -> retry -> applied/skipped/conflict/failed
```

规则：

- 已 `applied/skipped/conflict` 终态的 event 重放应跳过。`conflict` 也是终态：
  event_id 是 `object_type|global_id|revision` 确定性哈希，同对象同版本只判一次冲突，
  冲突已完整落库 `sync_conflicts`（含 incoming 快照），处置走 resolve API 而不是重拉。
- `failed` 必须允许重试，不能永久 skip。
- apply 失败要保留错误、payload hash 和完整脱敏 envelope（`record_json`）。
- 每次 apply/retry 都要更新 `attempt_count` 和 `last_attempt_at`；成功重试会把同一 inbox 行改为
  `applied/skipped/conflict` 等新状态。
- cursor 按页推进：冲突不卡水位（冲突页照常推进 cursor，也不中断后续对象类型）；
  只有传输层失败会把 `sync_cursors.last_status` 置 `failed` 并落 `status=failed`
  的 `sync_runs`（不裸抛，保证健康端点可见）。
- 每轮 pull 对每类对象第一页把已持久化水位回退 `SYNC_PULL_REPLAY_LOOKBACK_SECONDS`
  （300 秒）重放重叠区间，补偿 publisher 侧长事务晚提交的漏发；重复事件由本节
  幂等终态吸收，翻页游标不回退。

## 6. 冲突判定

冲突来源：

| 类型 | 判定 |
|---|---|
| revision conflict | incoming revision <= local revision，但 content_hash 不同 |
| hash conflict | 同 revision 下内容 hash 不一致 |
| owner conflict | incoming 尝试覆盖本地 owner 数据 |
| dependency missing | 外键依赖对象不存在且不能延迟 |
| restricted payload | payload 含 restricted 或 secret-like 字段 |
| policy conflict | sync_policy 不允许当前方向 |

冲突写入按 `(object_type, object_id, status=open)` 幂等去重：同对象重复判定只刷新
既有 open 记录（`resolution_json` 内 seen_count/last_seen_at），不重复插入，也不
重复发管理员通知。

冲突写入：

```text
sync_conflicts
  sync_run_id
  object_type
  object_id
  local_revision
  incoming_revision
  field_name
  local_value_json
  incoming_value_json
  conflict_reason
  status
  resolution_json
  resolved_by_user_id
  resolved_at
```

## 7. 冲突处置策略

| 策略 | 含义 | 适用 |
|---|---|---|
| use_incoming | 接受外来版本覆盖本地可同步字段 | extranet owner 对象 |
| use_local | 保留本地版本，跳过 incoming | intranet 本地 owner 对象 |
| manual_merge | 人工合并字段后写新 revision | 可编辑配置类对象 |
| ignored | 明确忽略并记录原因 | 非关键历史对象 |
| retry_after_dependency | 等依赖对象同步后重试 | 外键缺失 |

默认：

- extranet owner 的公开内容，intranet 应优先 `use_incoming`。
- intranet 本地评论、采信、需求、任务，永不被 extranet 覆盖。
- secret/restricted payload 直接拒绝，不进入人工合并。

当前 v1 已实现可审计处置策略：

- `keep_local`：状态写为 `resolved`，保留本地版本，不改业务对象。
- `ignored`：状态写为 `ignored`，记录忽略原因。
- `retry_after_dependency`：状态写为 `retry_after_dependency`，供后续依赖补齐后重试。
- `use_incoming`：通过原同步 apply handler 应用 `incoming_value_json`，只跳过当前冲突的
  revision/hash 检查，仍保留对象级外键、secret、visibility 和字段规则。
- `manual_merge`：当前开放给 `data_sources`、`daily_reports`、`weekly_reports`；必须传
  `merged_json`，后端以 `incoming_value_json + merged_json` 形成合并 payload，写入
  `max(local_revision, incoming_revision)+1` 的新修订，并继续走原对象 apply handler。

`manual_merge` 暂不开放给 `raw_items/news_items/generated_news` 等事实链对象；这些对象可用
`use_incoming` 接受外网 owner 版本，或继续 `keep_local/ignored/retry_after_dependency`。

## 8. API 目标态

```text
GET  /api/sync/feed/manifest
GET  /api/sync/feed
POST /api/sync/pull-runs
GET  /api/sync/health
POST /api/sync/inbox/retry-failed

GET  /api/sync-runs
GET  /api/sync-cursors

GET  /api/sync/conflicts
GET  /api/sync/conflicts/{id}
POST /api/sync/conflicts/{id}/resolve

POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import
```

`resolve` body：

```json
{
  "strategy": "keep_local",
  "merged_json": null,
  "reason": "local version reviewed"
}
```

`GET /api/sync/health` 汇总已有运行事实，不创建新的同步状态源：

- 输入：runtime sync role、`sync_cursors.last_pulled_at/last_status/last_error`、最近
  `sync_runs`、open `sync_conflicts`、failed `sync_inbox`。
- 输出：`ok/warning/critical/inactive`、每类对象 cursor 水位、缺失水位、过期水位、失败水位、
  failed inbox 数量与对象分布、最近失败 run、open conflict 计数和告警列表。
- 阈值：`warning_after_seconds = max(60, SYNC_PULL_INTERVAL_SECONDS) * 2`；
  `critical_after_seconds = max(60, SYNC_PULL_INTERVAL_SECONDS) * 6`。cursor `last_status=failed`
  或 `last_error` 非空直接 critical；failed inbox 是 critical；open conflict 是 warning；
  consumer 开启但缺少对象 cursor 是 warning。
- 权限：cookie session + `super_admin`。该端点面向本实例管理员，不使用 service token，也不泄露
  `SYNC_REMOTE_TOKEN`、`SYNC_SERVICE_TOKENS` 或 provider secret。

`POST /api/sync/inbox/retry-failed` 是本地 operator 修复动作：

- 权限：cookie session + `super_admin`，不使用 sync service token。
- 输入：可选 `object_type`、`limit`。
- 行为：读取 `sync_inbox.status=failed` 且保存了 `record_json` 的记录，按 `source_instance_id`
  分组，复用同一套 apply handler 重放；无 `record_json` 的旧失败行保留为失败并写明原因。
- 输出：一条 `direction=inbox_retry` 的 `sync_runs`，`counts_json` 记录 selected/applied/skipped/failed/conflicts、
  重试 inbox/event id、按来源分组统计和错误。
- 审计：写 `sync_inbox.retry_failed`。

自动 backoff 重试是 consumer 本地调度能力，不是另一条 apply 通道：

- 开关：`SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED`，默认跟随 `sync_pull_effective`，即 intranet consumer
  默认开启，其他部署默认关闭。
- 参数：`SYNC_FAILED_INBOX_RETRY_BASE_SECONDS` 默认 300，
  `SYNC_FAILED_INBOX_RETRY_MAX_SECONDS` 默认 3600，
  `SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS` 默认 5，
  `SYNC_FAILED_INBOX_RETRY_LIMIT` 默认 50。
- 到期规则：只选择 `status=failed`、`attempt_count < max_attempts`，且
  `last_attempt_at + min(max_delay, base_delay * 2^(attempt_count-1)) <= now` 的 inbox 行；
  没有 `last_attempt_at` 的历史 failed 行视为到期。
- 行为：生成 `direction=inbox_auto_retry` 的 `sync_runs`，复用手动 retry 的分组和 apply handler，
  不绕过 secret/restricted/conflict 检查。手动 `POST /api/sync/inbox/retry-failed` 仍是 operator
  override，可立即重试 selected failed 行。
- 健康：`GET /api/sync/health` 返回 retry policy、到期可自动重试数量、达到最大尝试次数的 blocked 数量和
  下一次预计重试时间；达到最大尝试次数的行仍保持 critical，必须人工检查或手动重试。

## 9. 前端同步页边界

前端 `/sync` 应展示：

- 当前实例 sync role。
- feed/pull 配置摘要。
- cursor 水位、缺失/过期/失败告警和最近同步健康摘要。
- failed inbox 数量、对象分布和本地重试入口。
- failed inbox 自动 backoff 策略、当前到期数量、最大尝试次数阻塞数量和下一次自动重试时间。
- 最近 sync runs。
- open conflicts、local/incoming JSON 预览和人工处置动作。
- 手动立即拉取。
- 人工包导入/导出 fallback。

前端不能：

- 展示敏感 token。
- 本地决定冲突合并策略。
- 把 failed inbox 永久隐藏。

## 10. 审计与安全

必须审计：

- service token feed 访问摘要。
- pull run 开始/结束/失败。
- package download/import。
- conflict resolve。
- restricted/secret payload 拒绝。

安全：

- feed 只走 service token，不走用户 cookie。
- package download 仅 `super_admin`。
- intranet 不暴露 sync publisher。
- payload 生成前做 secret-like 字段过滤，规则复用 `backend/app/core/privacy.py`。

## 11. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 实机联动证据不足 | extranet -> intranet 端到端 pull 有证据 |
| failed inbox 自动重试策略深化 | 自动 backoff、健康字段和 scheduler 投递已补；后续仍需告警投递和实机 runbook |
| package fallback 处置不完整 | zip manifest/checksum/import report 完整 |
| owner 边界需测试 | intranet 本地反馈不会被覆盖或回流 |
| manual_merge 范围深化 | 更多配置对象开放前必须接入对象级 apply handler 和测试 |

## 12. 验收设计

- 同一 feed page 重放不重复 apply。
- 外键缺失或临时失败导致 failed 后，依赖补齐可通过 `POST /api/sync/inbox/retry-failed` retry 成功。
- 到期 failed inbox 可由 scheduler 生成 `direction=inbox_auto_retry` 的 run，未到期或达到最大尝试次数的行不会被自动反复打爆。
- revision/hash 冲突写 `sync_conflicts`。
- `keep_local/ignored/retry_after_dependency/use_incoming/manual_merge` 处置均有测试；
  新增对象开放 `manual_merge` 前必须补对象级合并测试。
- `GET /api/sync/health` 能在 cursor 失败、cursor 滞后、缺少水位、failed inbox、open conflict 和最近失败 run
  时给出可测试告警；`/sync` 页面展示这些告警而不是只显示“运行列表”。
- intranet 评论、点赞、评分、通知、需求和任务不出现在 extranet feed；对应负向测试覆盖
  `requirements/topic_tasks` 和 `comments/reactions/ratings/activity_events/notifications/notification_preferences`。
- secret-like payload 被拒绝或从 feed/package 排除；审计详情统一脱敏。
- service token 错误返回 401。
