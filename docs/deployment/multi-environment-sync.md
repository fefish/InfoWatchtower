# 多环境与多数据库同步方案

本文档回答：公网和内网如何快速部署，是否能复用同一个数据库，如果未来有两套数据库，数据源和数据如何同步。

本文是同步边界专题，不是部署形态总规格。四种部署形态、能力开关、iframe 承载、
CSRF 和 service token 详见 `docs/deployment/deployment-topology.md`。本文只说明多库边界、
哪些对象能同步、哪些对象必须留在本地，以及 feed/pull 与手工包 fallback 的关系。

前端同步页如何呈现见 `docs/product/frontend-product-design.md`；同步对象和字段契约见
`config/contracts/sync_strategy.json`。
同步冲突、resolve、inbox 重试和人工包处置的目标态事实源是
`docs/backend/sync-conflict-distribution-design.md`。

机器契约：

- `config/contracts/sync_strategy.json`

## 1. 快速部署目标

InfoWatchtower 要做到同一套代码在不同环境快速上线：

```text
GitHub repo
-> Docker image / Docker Compose
-> .env.production 切环境
-> alembic upgrade head
-> 服务启动
```

公网和内网不应该分叉成两套代码。差异只放在：

- `.env.production`
- 域名和 HTTPS
- 登录模式 `AUTH_MODE`
- 数据源密钥
- 是否启用公网/内网同步任务

## 2. 内网部署能否复用同一个数据库

可以，但要看网络边界。

### 方案 A：同一个数据库

公网应用和内网应用都连接同一个 PostgreSQL。

适合：

- 早期只有一个可信环境。
- 公网服务和内网服务能通过 VPN 或专线访问同一个数据库。
- 你希望运维最简单。

注意：

- 数据库端口不要暴露到公网。
- 只能通过内网 IP、VPN、专线或 Docker 内网访问。
- 公网应用拿到的数据库账号权限要收窄。
- 如果内网有敏感评论、需求、任务，不建议直接让公网应用同库读写。

### 方案 B：公网和内网各一套数据库

公网负责开放信息采集，内网负责内部协作、评论、评分、需求、SQL 导出。

这是长期更推荐的方案，因为边界清晰：

```text
public DB      外部数据采集、raw/news/recommendation
intranet DB    内部用户、评论、采信、需求、任务、公司 SQL 导出
```

两边通过应用层同步，不直接互相开放数据库。

## 3. 不建议一开始做双写数据库

不要让公网和内网两个系统同时写同一批业务对象然后靠数据库层自动合并。

问题：

- 用户、评论、采信、需求容易冲突。
- 数据库复制会把敏感内网数据带出去。
- schema 迁移和回滚复杂。

更稳妥的是：明确每类数据的 owner。

## 4. 推荐同步边界

### 公网同步到内网

可以同步：

- 非密钥数据源配置。
- 公网抓到的 `raw_items`。
- `news_items`。
- 去重组。
- 推荐结果。
- 模型生成稿，如果不含敏感信息。
- 处理 run 元数据。

### 只留在内网

默认不同步出去：

- 内网用户。
- 角色权限。
- 评论、评分、点赞。
- 管理员采信和编辑意见。
- 内部需求。
- 指派任务。
- 公司 SQL 导出记录。
- 内网专属数据源密钥。

### 内网同步到公网

**硬不变式：机器同步方向单向 extranet → intranet，内网用户反馈（评论、点赞、评分、
采信、需求、任务、通知）在任何条件下永不回流公网**（`config/contracts/deployment_modes.json`
invariants 与 `sync_strategy.json` direction_invariant）。

以下配置/聚合类回流通道当前状态为 **planned（未实现，明确不进 feed）**：如果未来
确有需要，只能以人工导出包 + 管理员显式审批的形式设计，且范围仅限：

- 非敏感数据源配置变更。
- taxonomy/domain pack 更新。
- 脱敏后的来源质量聚合分。

## 5. 应用层 feed/pull 同步与手工包 fallback

2026-07 后主路径是 extranet feed 下发、intranet pull-only 拉取；outbox/zip 包保留为
网络隔离时的人工导出通道。推荐保留这些表：

```text
sync_outbox
sync_inbox
sync_runs
sync_conflicts
sync_cursors
```

每个可同步对象带：

```text
global_id
origin_instance_id
revision
content_hash
updated_at
deleted_at
```

同步流程：

```text
extranet 写入业务表
-> GET /api/sync/feed 按业务表 updated_at/id 生成可重放 envelope
-> intranet 定时 GET feed
-> intranet sync_inbox 去重校验
-> upsert 到本地表
-> sync_cursors 推进每类对象水位
-> 记录 sync_runs
```

同步包可以是：

- JSONL + manifest + checksum。
- 压缩文件。
- 内网 API 拉取。
- 对象存储中转。
- 手工上传导入，适合网络隔离场景。

### 5.1 表结构

当前实现保留 outbox 四表，并新增 `sync_cursors` 支撑 pull-only 水位。

`sync_outbox`：

```text
id
instance_id
event_id
object_type              data_source / raw_item / news_item / dedupe_group / recommendation_item / generated_news
object_global_id
operation                upsert / delete
payload_json             jsonb，脱敏后的同步对象
payload_hash
visibility_scope
sync_policy
target_environment       intranet / public / manual
status                   pending / exported / acknowledged / failed
created_at
exported_at
error_message
```

`sync_inbox`：

```text
id
source_instance_id
event_id
object_type
object_id
payload_hash
record_json              脱敏后的完整 envelope，用于 failed 本地重放
status                   pending / applied / skipped / conflict / failed
error_message
attempt_count
last_attempt_at
created_at
updated_at
```

`sync_runs`：

```text
id
direction                public_to_intranet / intranet_to_public / manual_import
mode                     package / api_pull / api_push
status                   running / succeeded / failed / partial
source_instance_id
target_instance_id
manifest_json            jsonb
started_at
finished_at
created_by
```

`sync_conflicts`：

```text
id
sync_run_id
object_type
object_global_id
local_revision
incoming_revision
local_json               jsonb
incoming_json            jsonb
conflict_reason
resolution_status        open / resolved / use_incoming / manual_merge / ignored / retry_after_dependency
resolved_by
resolved_at
```

`sync_cursors`：

```text
object_type
cursor
last_pulled_at
last_status
last_error
```

### 5.2 同步对象字段

所有可能跨环境同步的业务对象必须有：

```text
global_id
origin_instance_id
revision
content_hash
visibility_scope
sync_policy
created_at
updated_at
deleted_at
```

当前 feed/pull 主线支持这些对象：

```text
data_sources
raw_items
news_items
generated_news
daily_reports
weekly_reports
```

当前冲突处置已支持：

- `keep_local`：仅记录处置，保留本地对象。
- `ignored`：记录忽略原因。
- `retry_after_dependency`：等待依赖补齐后重试。
- `use_incoming`：把传入 payload 重新交给对象 apply handler。
- `manual_merge`：对 `data_sources/daily_reports/weekly_reports` 使用人工合并 JSON 写新 revision。

内网专属表默认不参与公网同步：

```text
users
roles
comments
ratings
editorial_actions
daily_report_items editor overrides
insights
requirements
topic_tasks
export_jobs
```

### 5.3 同步包格式

同步包建议是 zip：

```text
infowatchtower_sync_{source}_{target}_{timestamp}.zip
  manifest.json
  records.jsonl
```

第一版实现把不同对象统一放入 `records.jsonl` envelope；后续如果单包过大，再拆成
`data_sources.jsonl/raw_items.jsonl/news_items.jsonl` 等分表文件。

`manifest.json`：

```json
{
  "format_version": "sync_package_v1",
  "package_id": "sync_20260504_120000_public_to_intranet",
  "source_instance_id": "public-prod",
  "target_instance_id": "intranet-prod",
  "direction": "public_to_intranet",
  "created_at": "2026-05-04T12:00:00+08:00",
  "record_count": 100,
  "records_sha256": "..."
}
```

每行 JSONL 是一个 envelope：

```json
{
  "event_id": "evt_...",
  "object_type": "raw_item",
  "object_global_id": "raw_...",
  "operation": "upsert",
  "revision": 3,
  "content_hash": "sha256:...",
  "visibility_scope": "public",
  "sync_policy": "public_to_intranet",
  "payload": {}
}
```

### 5.4 导出任务

公网导出同步包时：

1. 查询 `sync_outbox.status = pending`。
2. 过滤 `visibility_scope = public`。
3. 过滤 `sync_policy in (public_to_intranet, manual_only)`。
4. 移除 token、cookie、password、secret 等敏感字段。
5. 写 JSONL 和 manifest。
6. 计算 checksum。
7. 标记 outbox 为 `exported`。
8. 记录 `sync_runs`。

第一版可以先做管理后台按钮：

```text
生成公网到内网同步包
```

2026-07 定位更新：outbox/手工同步包降级为人工导出通道（适合网络隔离场景），不再
扩展；机器对机器的定时同步走 §5.8 的 api_pull feed 协议，不给主管线补 outbox
生产者。

当前实现：

- `POST /api/sync/packages/export` 从 `sync_outbox` 读取 pending 事件，过滤 `restricted` 和不可同步策略。
- 导出后把对应 outbox 状态标记为 `exported`。
- `sync_runs.counts_json` 保存 `package_manifest` 和 `package_records`，用于审计和下载。
- `GET /api/sync/packages/{package_id}/download` 返回 zip，包含 `manifest.json` 和 `records.jsonl`。
- 旧 `/api/sync-runs` 仍保留，内部复用同步包导出逻辑。

### 5.5 导入任务

内网导入同步包时：

1. 校验 manifest schema 和 checksum。
2. 逐行读取 JSONL。
3. 用 `event_id` 查 `sync_inbox`，已处理则跳过。
4. 再次检查 `visibility_scope` 和 `sync_policy`。
5. 按 `object_global_id` upsert。
6. 如果本地 revision 和 incoming revision 冲突，写 `sync_conflicts`。
7. 成功后写 `sync_inbox.status = applied`。
8. 记录 `sync_runs`。

第一版冲突处理可以保守：

- `raw_items`：相同 `global_id + content_hash` 跳过；不同 hash 保留新 revision。
- `news_items`：incoming revision 更高则更新。
- `data_sources`：如果两边都改过同一字段，进入 `sync_conflicts`，人工处理。

当前实现：

- `POST /api/sync/packages/import` 接收 manifest 和 records，先校验 `records_sha256`。
- 用 `event_id` 写入 `sync_inbox`，重复导入会跳过，不重复写。
- 对 `data_sources`、`raw_items`、`news_items`、`generated_news`、`daily_reports`、`weekly_reports` 执行 `object_global_id/global_id` 幂等 upsert。
- 如果本地 revision 更新，或同 revision 的 `content_hash` 不一致，写 `sync_conflicts`，不静默覆盖本地对象。
- `restricted` 或带 secret-like 字段的 payload 不落业务表；字段判定复用
  `backend/app/core/privacy.py`，覆盖 token、secret、password、cookie、authorization、api_key、
  `.env`、client_secret 和 session。
- 导入动作写 `sync_runs`、`sync_inbox.status`、冲突摘要和审计日志；暂不支持的 `object_type` 会在本次 run 的 errors 中显式失败。

### 5.6 API 形态

当前 API 分两组。机器拉取主路径：

```text
GET  /api/sync/feed/manifest
GET  /api/sync/feed
POST /api/sync/pull-runs
```

手工包 fallback：

```text
POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import
GET  /api/sync/runs
GET  /api/sync/conflicts
POST /api/sync/conflicts/{id}/resolve
```

网络隔离时，不开放 feed API 也可以。直接在外网生成 zip，同步到内网后手工导入。

### 5.7 第一版验收

同步功能第一版验收：

- extranet 无 token 访问 feed 返回 401，合法 token 可读 manifest/page。
- intranet 执行 `POST /api/sync/pull-runs` 后 `sync_runs` 记录 `api_pull`，`sync_cursors` 水位前进。
- feed/同步包不包含密钥、token、cookie、`.env`。
- 内网导入或拉取后可以看到 `sync_inbox` 幂等记录和运行审计。
- 内网用户、评论、采信、需求、任务不会被同步到公网。
- 重复导入同一同步包或重复拉取同一 cursor 不会重复写数据。
- 冲突能进入 `sync_conflicts`，不会静默覆盖。

### 5.8 api_pull 定时拉取（已实现方向）

2026-07 定稿：extranet（公网发布者）与 intranet（内网消费者）之间的机器对机器同步
不再走 outbox 手工包，而是「业务表水位直查 + 定时拉取」。实现级规格见
`docs/deployment/deployment-topology.md` §3，部署形态与能力开关见
`config/contracts/deployment_modes.json`。

feed 端点契约（publisher 侧，`DEPLOY_MODE=extranet`，`sync_publisher` 能力门）：

```text
GET /api/sync/feed/manifest
  → {"instance_id": "...", "object_types": [...按下方顺序...],
     "watermarks": {"data_sources": "<iso>", ...}, "server_time": "<iso>"}

GET /api/sync/feed?object_type=<t>&cursor=<c>&limit=<n=200,max 500>
  → {"object_type": "...",
     "records": [<envelope>...],          # 与 §5.3 records.jsonl 同构
     "next_cursor": "<opaque>" | null,    # 基于本页扫描到的最后一行生成（含被密钥/可见性红线
                                          # 过滤掉的行），records 为空时 next_cursor 也可能非 null；
                                          # null 仅表示本次请求没有扫描到任何行
     "has_more": bool,
     "server_time": "<iso>"}
```

机器鉴权（service token）：

- publisher 侧配置 `SYNC_SERVICE_TOKENS`（逗号分隔，支持多消费者/轮换重叠期）；
  条目支持 `name:token` 命名消费者（name 进审计日志），也兼容纯 token
  （消费者名按位置记为 `token-<序号>`）。
- 请求携带 `Authorization: Bearer <token>`，`hmac.compare_digest` 逐一比对，失败 401。
- feed 端点只走 service token + `sync_publisher` 能力门，不走 cookie session，
  与用户 RBAC 无关。
- feed 访问审计：manifest/page 每次读取写审计日志（`sync_feed.manifest` /
  `sync_feed.read`），记录消费者身份、object_type、cursor 范围和 record_count。

游标与幂等：

- keyset 分页，`(updated_at, id)` 复合排序；cursor 为
  `base64(updated_at_iso + "|" + id)` 的不透明串。
- 同一 cursor 重复请求返回相同结果：feed 端点无副作用、可重放。
- envelope 的 `event_id` 确定性生成：`sha256(object_type|global_id|revision)`，
  同一对象同一版本重放幂等，新版本产生新 event_id。
- 过滤沿用同步包规则：`visibility_scope != restricted`、`sync_policy` 属于可导出
  集合、含 secret/token/password/cookie/.env 的 payload 不下发。
- 禁止对象：`requirements/topic_tasks/comments/reactions/ratings/activity_events/notifications`、
  `notification_preferences/export_jobs` 不进入 feed object types。`requirements/topic_tasks`
  的负向回归测试为
  `backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_strategy_loop_private_objects`；
  本地协作/通知对象的负向回归测试为
  `backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_local_collaboration_notifications`。

对象类型顺序（外键依赖，consumer 必须按序应用；相对第一版扩展了成稿三类）：

```text
1. data_sources
2. raw_items          （依赖 data_sources）
3. news_items         （依赖 raw_items, data_sources）
4. generated_news     （依赖 news_items）
5. daily_reports      （payload 内嵌 items：daily_report_items 含 adoption_status/is_headline）
6. weekly_reports     （payload 内嵌 items）
```

consumer 侧（`DEPLOY_MODE=intranet`，`sync_consumer` 能力门）：

- 新表 `sync_cursors`：`object_type (pk) / cursor / last_pulled_at / last_status /
  last_error`，记录每类对象的拉取水位。
- 拉取过程（`backend/app/sync/pull.py`）：按上述顺序逐对象类型分页 GET → 每批喂
  `app/sync/apply.py` 的 `apply_sync_records` 幂等落库 → 批成功后持久化 cursor →
  记入 `sync_runs`（mode=`api_pull`，counts 记 applied/skipped/failed/conflicts）。
- 回看窗口重放：每轮 pull 对每类对象第一页把已持久化水位回退
  `SYNC_PULL_REPLAY_LOOKBACK_SECONDS`（300 秒，代码常量），补偿 publisher 侧
  长事务晚提交造成的 keyset 水位漏发；重叠区间的重复事件由 inbox `event_id`
  幂等终态（`applied/skipped/conflict`）吸收。翻页游标不回退，单轮严格前进。
- 冲突不卡水位：`conflict` 是 inbox 终态（event_id 是对象+版本的确定性哈希，
  同对象同版本只判一次），冲突页照常推进 cursor 且不中断后续对象类型；open 冲突按
  `(object_type, object_id)` 幂等去重，重复判定只刷新既有记录，不重复发通知。
- 传输失败落 run：manifest/feed 页传输异常不裸抛，落成 `status=failed` 的
  `sync_runs`（errors 摘要 + per_object `transport_failed`），feed 页级失败同时把
  `sync_cursors.last_status` 置 `failed`，健康端点立刻可见。
- 调度：scheduler 在 `capability_sync_consumer && SYNC_PULL_ENABLED` 时按
  `SYNC_PULL_INTERVAL_SECONDS`（默认 900 秒）投递 `sync_pull` 任务到 RQ；
  `POST /api/sync/pull-runs`（super_admin + `sync_consumer` 门）可手动触发一轮。
- 健康摘要：`GET /api/sync/health`（super_admin + cookie session）读取
  `sync_cursors`、最近 `sync_runs`、failed `sync_inbox` 和 open `sync_conflicts`，返回
  `ok/warning/critical/inactive`、每类 cursor、缺失水位、失败水位、滞后水位、failed inbox
  数量/对象分布、最近失败 run 和 open conflict 告警。滞后阈值由 `SYNC_PULL_INTERVAL_SECONDS`
  派生：超过 2 个周期 warning，超过 6 个周期 critical；`last_status=failed`、`last_error`
  非空或存在 failed inbox 直接 critical。
- inbox 重试语义：`sync_inbox` 幂等判断仅当既有记录状态为终态
  `applied/skipped/conflict` 时跳过；`failed` 记录保留 `record_json`，允许通过
  `POST /api/sync/inbox/retry-failed`
  本地重放重试，外键顺序失败可自愈，不再永久卡死。该重试是内网本地 operator 动作，
  只走 cookie session + super_admin，不使用 feed service token，也不把内网反馈回流公网。
- failed inbox 自动 backoff：consumer 侧可用 `SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED`
  开关控制，默认跟随 intranet `sync_pull_effective` 开启。scheduler 在投递 sync pull 的同一循环里，
  对到期 failed inbox 生成 `direction=inbox_auto_retry` 的本地 run；退避参数为
  `SYNC_FAILED_INBOX_RETRY_BASE_SECONDS`、`SYNC_FAILED_INBOX_RETRY_MAX_SECONDS`、
  `SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS` 和 `SYNC_FAILED_INBOX_RETRY_LIMIT`。该能力只复用本地
  apply handler，不使用 service token，也不绕过 secret/restricted/conflict 检查。

定位说明：outbox/手工同步包（§5.3-§5.5）保留为网络隔离场景的人工导出降级通道，
不再要求主管线写 outbox producers；`GET /api/sync/packages/{package_id}/download` 收权为
`super_admin`。同步方向保持单向 extranet → intranet，内网评论/点赞/评分/通知/采信/需求
永不回流，同步不改变公司 SQL 出口合同；Strategy Loop 的 requirement/task feed 负向测试和
协作/通知本地对象 feed 负向测试已覆盖。

## 6. 数据源如何同步

数据源分两部分：

```text
公共配置：名称、URL、类型、标签、抓取频率、默认板块、非敏感规则
环境配置：token、cookie、内网地址、代理、启停状态、凭据
```

公共配置可以同步或放 Git：

```text
config/seeds/
config/domain_packs/
```

环境配置只留在各自数据库或 `.env.production`，不跨环境同步。

冲突策略：

- `data_sources.global_id` 相同则认为是同一个源。
- `revision` 更高者可以自动更新非敏感字段。
- 两边都改过同一个字段时，进入 `sync_conflicts`，管理员处理。
- token、cookie、密码永远不通过同步包传递。

## 7. 原始新闻如何同步

`raw_items` 按稳定键 upsert：

```text
global_id = hash(source_global_id + entry_key)
```

如果没有稳定 entry_key：

```text
global_id = hash(source_global_id + canonical_url)
```

如果 URL 也没有：

```text
global_id = hash(source_global_id + normalized_title + published_date)
```

`raw_payload_json` 作为原始证据保留。同步时可用 `content_hash` 判断是否变化。

## 8. 推荐落地路线

### 第一阶段：单库单环境

公网或内网先跑起来：

- 单台服务器。
- Docker Compose。
- 一个 PostgreSQL。
- 每日备份。

### 第二阶段：同代码内网快速上线

在内网新服务器部署同一代码：

- 修改 `.env.production`。
- 切 `AUTH_MODE=intranet_header`。
- 恢复数据库备份，或从公网导入初始同步包。
- 接内网网关工号姓名。

### 第三阶段：公网采集 + 内网协作

拆成两套数据库：

- 公网负责采集外部公开信息。
- 内网负责内部反馈、需求、SQL 导出。
- 公网向内网做单向应用层同步。

### 第四阶段：多板块多实例

按 domain pack 扩 AI、硬件、半导体、政策等板块。

需要时可以让不同板块有不同采集 worker，但仍进入同一个主数据模型。
