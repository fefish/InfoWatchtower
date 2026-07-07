# Pipeline & Jobs 流水线编排与任务可靠性设计

> 状态：目标态设计稿。本文是日更流水线、后台任务、scheduler、worker、重试、幂等和
> 失败恢复的后端模块事实源。抓取/流转/存储见
> `docs/backend/data-ingestion-flow-storage-design.md`，推荐评分见
> `docs/backend/recommendation-scoring-design.md`，报告编审见
> `docs/backend/reports-editorial-design.md`。

## 1. 模块定位

Pipeline & Jobs 负责把多个后端能力模块编排成可重复、可追踪、可恢复的业务流水线。

它回答：

- 一次日更到底包含哪些步骤。
- 每个步骤失败后如何恢复。
- 哪些任务能重跑，哪些对象不能覆盖。
- API、worker、scheduler 如何协同。
- standalone/cloud/extranet/intranet 下哪些任务可运行。

它不负责：

- Adapter 具体抓取字段。
- 推荐评分公式。
- 日报条目编辑和成稿渲染。
- SQL 字段映射。

## 2. 核心流水线

标准日更流水线：

```text
pipeline_run
-> ingestion
-> normalize
-> dedupe
-> recommendation
-> generation
-> daily_report_draft
-> renditions(optional/on read or explicit regenerate)
```

入口：

```text
POST /api/pipeline/daily-runs
scheduler daily job
manual admin run
```

目标：

- 手动触发和定时触发走同一条编排逻辑。
- 每一步有开始、结束、状态、计数和错误信息。
- 任意一步失败后能知道停在哪、是否可重试。
- 已发布日报不可被流水线覆盖。

## 3. 领域对象

建议将 pipeline run 和 job run 概念从具体业务 run 中抽象出来。

```text
pipeline_runs
  id
  workspace_code
  domain_code
  pipeline_type        daily_report / backfill / sync_pull / export_preflight
  day_key
  status               queued / running / succeeded / partial / failed / cancelled
  trigger_type         manual / scheduler / api / retry
  triggered_by
  parameters_json
  summary_json
  started_at
  finished_at
  created_at

pipeline_steps
  id
  pipeline_run_id
  step_key             ingestion / normalize / dedupe / recommendation / generation / daily_report
  status
  input_json
  output_json
  error_code
  error_message
  started_at
  finished_at

job_runs
  id
  queue_name
  job_key
  job_type
  status
  attempts
  max_attempts
  idempotency_key
  payload_json
  result_json
  error_message
  enqueued_at
  started_at
  finished_at
```

如果现阶段不新建完整表，也必须让现有 `ingestion_runs`、`recommendation_runs`、
`sync_runs`、`export_jobs` 保留等价状态和追溯字段。

## 4. 幂等键

| 任务 | 幂等键 |
|---|---|
| daily pipeline | `workspace_code + domain_code + day_key + pipeline_type` |
| ingestion regular | `workspace_code + source_types + started window` |
| historical backfill | `workspace_code + mode + date_window + source_types` |
| normalize/dedupe | `workspace_code + affected raw/news ids` |
| recommendation | `workspace_code + domain_code + day_key + params hash` |
| generation | `recommendation_item_id + prompt_version + format policy` |
| daily report draft | `workspace_code + domain_code + day_key` |
| sync pull | `instance_id + object_type + cursor` |
| export preflight | `daily_report_id + contract_version` |

幂等不是“什么都不做”。它意味着重复请求必须返回已有 run、重放安全结果或明确 409。

## 5. 状态机

通用状态：

```text
queued
running
succeeded
partial
failed
cancelled
skipped
```

规则：

- `partial` 表示部分对象失败，但整体可继续，例如单源失败。
- `failed` 表示流水线无法继续，例如数据库不可用、已发布日报冲突、必需配置缺失。
- `skipped` 表示部署形态或前置条件禁止，例如 intranet 禁采集。
- 所有失败都必须有 `error_code` 和可诊断 `error_message`。

## 6. 重试策略

| 步骤 | 是否自动重试 | 策略 |
|---|---|---|
| ingestion 单源 | 手动 v1；自动 backoff v1 | 已有 `POST /api/ingestion/runs/{run_id}/retry-failed-sources` 只重试失败源并记录来源 run；自动队列由 `INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED` 开启，按指数退避选择到期失败 run 并复用同一 ingestion/backfill 服务 |
| normalize/dedupe | 可重试 | 幂等重建受影响对象 |
| recommendation | 可重试 | 新 run 或同参数重放，旧快照不覆盖 |
| generation | 可重试 | 非 ready/fallback 草稿可重跑，记录 prompt_version |
| daily report draft | 谨慎 | 未发布可重建；已发布返回 409 |
| sync pull | 是 | failed inbox 允许重放；cursor 只在批成功后推进 |
| export | 可重试 | 同一 report 生成新 export_job 或复用通过的预检 |

## 7. 部署形态门禁

| 部署形态 | Pipeline 行为 |
|---|---|
| standalone | 可运行完整流水线 |
| cloud | 可运行完整流水线，写操作按 workspace role gate |
| extranet | 可运行完整流水线，并作为 sync publisher |
| intranet | 禁止 ingestion 和外网 crawler；允许 sync pull、阅读、评论、本地采信和本地导出 |

三层同时 gate：

- API dependency。
- scheduler 不投递禁用任务。
- 前端隐藏或解释禁用入口。

## 8. Scheduler 设计

scheduler 只负责投递任务，不直接执行重业务。

配置：

```text
INGESTION_SCHEDULER_ENABLED
INGESTION_SCHEDULER_DAILY_TIME
INGESTION_SCHEDULER_TIMEZONE
INGESTION_SCHEDULER_WORKSPACE_CODE
DAILY_PIPELINE_DAY_OFFSET_DAYS
SCHEDULER_JOB_MODE
```

规则：

- 固定墙上时间优先于 interval 模式。
- 生产默认生成昨天日报，避免当天数据未完整。
- scheduler 启动时不能重复投递同一个 day_key 的同一 pipeline。
- scheduler 必须尊重 `DEPLOY_MODE` 能力开关。

## 9. API 目标态

```text
POST /api/pipeline/daily-runs
GET  /api/pipeline/runs
GET  /api/pipeline/runs/{id}
POST /api/pipeline/runs/{id}/retry
POST /api/pipeline/runs/{id}/cancel
GET  /api/jobs
GET  /api/jobs/{id}
GET  /api/ingestion/scheduler
```

当前可以先让具体 run API 承担一部分能力，但目标态需要统一 pipeline 视图，
供今日速览、抓取覆盖和运维排错使用。

## 10. 审计与观测

关键事件必须写审计或运行记录：

- 手动触发 pipeline。
- scheduler 投递。
- 任务失败和重试。
- 已发布日报冲突。
- 生成 fallback。
- sync pull 失败。
- export preflight 失败。

指标：

```text
pipeline duration
step duration
queue latency
source failure count
generation timeout count
retry count
daily success/failure by workspace
```

## 11. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| pipeline run 视图不统一 | 可跨 ingestion/recommendation/generation/report 查看一步日更 |
| 任务状态机分散 | 统一状态、错误码、重试语义 |
| scheduler 可靠性不足 | 不重复投递、尊重部署能力、留存投递证据 |
| 失败恢复不足 | 支持按 step 重试或给出不可重试原因 |
| API 事件循环压力 | 长任务进入 worker，API 只创建/查询 run |

## 12. 验收设计

- 手动和 scheduler 触发同一天同参数 pipeline 不产生重复日报。
- 已发布日报再次跑 pipeline 返回明确 409 或 skipped。
- 单源失败时 pipeline 可 partial 继续。
- MiniMax 超时只影响 generation step，日报草稿标记 fallback，不进入 SQL。
- `DEPLOY_MODE=intranet` 下 ingestion step skipped，sync pull 可运行。
- worker 重启后已入队任务可继续或标记 failed，不静默丢失。
