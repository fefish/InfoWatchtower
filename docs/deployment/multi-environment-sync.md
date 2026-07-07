# 多环境与多数据库同步方案

本文档回答：公网和内网如何快速部署，是否能复用同一个数据库，如果未来有两套数据库，数据源和数据如何同步。

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

默认不做。只有明确批准时，才同步：

- 非敏感数据源配置变更。
- taxonomy/domain pack 更新。
- 脱敏后的来源质量聚合分。

## 5. 应用层 outbox/inbox 同步

推荐实现四张表：

```text
sync_outbox
sync_inbox
sync_runs
sync_conflicts
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
public 写入业务表
-> public sync_outbox 记录事件
-> 定时生成同步包
-> intranet 拉取或接收同步包
-> intranet sync_inbox 去重校验
-> upsert 到本地表
-> 记录 sync_runs
```

同步包可以是：

- JSONL + manifest + checksum。
- 压缩文件。
- 内网 API 拉取。
- 对象存储中转。
- 手工上传导入，适合网络隔离场景。

### 5.1 表结构

第一版按这四张表实现即可。

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
object_global_id
payload_hash
status                   received / applied / skipped / conflicted / failed
received_at
applied_at
error_message
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
resolution_status        open / use_local / use_incoming / manual_merge / ignored
resolved_by
resolved_at
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

第一版可以先在这些表上落字段：

```text
data_sources
raw_items
news_items
dedupe_groups
dedupe_group_items
recommendation_runs
recommendation_items
generated_news
```

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

后续再做定时任务。

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
- 对 `data_sources`、`raw_items`、`news_items` 执行 `object_global_id/global_id` 幂等 upsert。
- 如果本地 revision 更新，或同 revision 的 `content_hash` 不一致，写 `sync_conflicts`，不静默覆盖本地对象。
- `restricted` 或带 token/password/secret/cookie/.env 等疑似密钥字段的 payload 不落业务表。
- 导入动作写 `sync_runs`、`sync_inbox.status`、冲突摘要和审计日志；暂不支持的 `object_type` 会在本次 run 的 errors 中显式失败。

### 5.6 API 形态

如果网络允许内网主动拉取公网，可以预留 API：

```text
POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import
GET  /api/sync/runs
GET  /api/sync/conflicts
POST /api/sync/conflicts/{id}/resolve
```

网络隔离时，不开放公网 API 也可以。直接在公网生成 zip，同步到内网后手工导入。

### 5.7 第一版验收

同步功能第一版验收：

- 公网生成一个同步包。
- 同步包不包含密钥、token、cookie、`.env`。
- 内网导入后可以看到 `sync_inbox` 幂等记录和导入运行审计。
- 内网用户、评论、采信、需求、任务不会被同步到公网。
- 重复导入同一同步包不会重复写数据。
- 后续业务 apply handler 完成后，冲突能进入 `sync_conflicts`，不会静默覆盖。

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
