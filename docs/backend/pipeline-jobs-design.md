# Pipeline & Jobs 流水线编排与任务可靠性设计

> 状态：目标态设计稿。本文是日更流水线、后台任务、scheduler、worker、重试、幂等和
> 失败恢复的后端模块事实源。抓取/流转/存储见
> `docs/backend/data-ingestion-flow-storage-design.md`，推荐评分见
> `docs/backend/recommendation-scoring-design.md`，报告编审见
> `docs/backend/reports-editorial-design.md`。
>
> 2026-07-07 增量：§6.1/§6.2 pipeline 级自动重试、§8 分层调度模型
> （实例 env 基线 → 工作台 `schedule_policy` → scheduler DB 驱动触发）、
> §8.5 调度心跳与可观测、§9 新增 schedule-policy 与 scheduler status API。
> 这些小节已于 2026-07-08 实现落地（`backend/tests/test_scheduler_policy.py`、
> `backend/tests/test_pipeline_retry.py` 看护）；契约见
> `config/contracts/workspace_model.json` 的 `schedule_policy`。生成模型 provider
> 配置见 `docs/backend/generation-provider-design.md`。

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

### 3.1 数据模型增量（2026-07-07 定稿，2026-07-08 已实现）

pipeline run 记录（无论落在新 `pipeline_runs` 表还是现有 run 表的等价字段）增加
run 级重试链字段：

```text
attempt              int   # 本次是第几次尝试，首跑=1
max_attempts         int   # 解析自工作台 schedule_policy.retry.max_attempts + 1（首跑含在内）
retry_of_run_id      fk    # 指向被重试的失败 run；首跑为空
next_retry_at        datetime(tz) nullable  # failed 且未达上限时由 worker 写入；到期由 scheduler 扫描重投
retry_reason         str nullable           # 触发重试的 error_code
```

新增调度心跳表（scheduler 进程写、API 读，避免 API 直连 scheduler 进程）：

```text
scheduler_heartbeats
  id
  scheduler_instance    str    # settings.effective_instance_id + 进程标识
  job_kind              str    # daily_pipeline / weekly_report / sync_pull /
                               # ingestion_auto_retry / sync_auto_retry / pipeline_retry
  workspace_code        str nullable   # per-workspace 节拍行；实例级任务为空
  last_tick_at          datetime(tz)   # 每个调度循环 tick 结束时 upsert
  last_enqueued_at      datetime(tz) nullable
  last_enqueued_job_id  str nullable
  next_run_at           datetime(tz) nullable  # 计算出的下一次投递时刻
  detail_json           json           # 最近投递参数摘要（workspace/day_key/attempt），不含密钥
```

唯一键：`(scheduler_instance, job_kind, workspace_code)`。心跳行是运行状态快照，
可随时重建，不参与同步（`sync_policy=none`）。

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

### 6.1 两级重试的分工（已实现，2026-07-08）

系统里存在两种"自动重试"，边界必须清晰，不能互相顶替：

| 级别 | 处理对象 | 触发条件 | 现状 |
|---|---|---|---|
| 对象级：ingestion failed-source auto-retry | run **内**的单个失败源 | run 整体 `partial`，`summary_json.sources.status=failed` 的源到期 | 已实现（`INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED`，指数退避，复用同一 ingestion/backfill 服务） |
| run 级：pipeline auto-retry | **整条** daily pipeline run | run 状态 `failed`（不是 `partial`）且 `error_code` 属于可重试类 | 本节新设计 |

规则：

- `partial` 永不触发 run 级重试——单源失败交给对象级重试，重复整条流水线只会
  浪费配额并制造重复 run。
- run 级重试只处理"流水线无法继续"类失败：数据库/Redis 闪断、生成 provider
  整体不可用、worker 崩溃导致 job failed。
- 错误码显式分类：`error_code` 必须标记 `retryable=true/false`。
  不可重试类（重试也必然失败，直接终态）：`published_report_conflict`（409）、
  `capability_disabled`（部署形态禁用）、`invalid_parameters`、`workspace_not_found`。

### 6.2 run 级自动重试语义（已实现，2026-07-08）

- 策略来源：工作台 `schedule_policy.retry`（见 §8.2），字段
  `max_attempts`（失败后最大自动重试次数，不含首跑，默认 1，取值 0-5）和
  `backoff_seconds`（首个退避间隔，默认 900，取值 60-21600）。
- 执行方式：worker 在 daily pipeline run 落 `failed` 终态时，若
  `attempt <= max_attempts` 且 `error_code` 可重试，写
  `next_retry_at = finished_at + backoff_seconds * 2^(attempt-1)`；
  scheduler 每 tick 扫描 `next_retry_at <= now` 的失败 run，投递新 run：
  `trigger_type=retry`、`attempt=attempt+1`、`retry_of_run_id` 指向上一次 run。
- 追溯：重试链沿 `retry_of_run_id` 可回溯到首跑；每次投递写
  `scheduler_heartbeats(job_kind=pipeline_retry)` 和审计
  `pipeline.run.auto_retry`（detail 含 run id 链、attempt、error_code）。
- 终止：达到上限后不再写 `next_retry_at`，产生
  `ingestion.pipeline_retry_exhausted` important 站内通知（复用失败源告警通道），
  锚点跳 `/ingestion-runs?run_id=...`。
- 幂等：重试 run 与首跑共用 §4 的 daily pipeline 幂等键；若首跑失败后管理员已
  手动重跑成功（同 day_key 已有 succeeded run 或已发布日报），重试投递必须让位，
  落 `skipped` 并记 `skip_reason=superseded`。
- 手动触发的 `POST /api/pipeline/daily-runs` 同样吃工作台 retry 策略；请求级
  `retry_max_attempts` 参数可覆盖（null=跟随工作台策略，0=本次不自动重试）。

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

用户问题的直接回答（本节是"每天固定任务从哪里设置"的唯一事实源）：

- 触发时间/周期/重试**不需要手动触发，也不靠人肉记忆 env**——配置分两层：
  实例 env 基线（部署时定一次，管总闸和默认值）+ 工作台
  `schedule_policy`（运营期在工作台配置中心随时改，存 DB，改完下一个
  tick 生效，无需重启）。
- "数据流是不是自动的"必须在界面可自证：工作台配置中心「自动化」卡显示
  下次运行时间预览；今日速览/抓取页运营卡显示 scheduler 心跳、下次运行和
  最近 run 结果（§8.5）。

### 8.1 分层配置模型（已实现，2026-07-08）

```text
第 1 层 实例 env 基线（部署边界，改动需重启 scheduler 进程）
  INGESTION_SCHEDULER_ENABLED        调度总闸；false 时不投任何 pipeline 任务，
                                     工作台策略不能越过总闸
  INGESTION_SCHEDULER_DAILY_TIME     实例默认触发时刻（HH:MM）
  INGESTION_SCHEDULER_TIMEZONE       实例统一时区（工作台不可覆盖，避免跨时区审计混乱）
  INGESTION_SCHEDULER_WORKSPACE_CODE 兼容默认工作台（见 8.3 兼容规则）
  DAILY_PIPELINE_DAY_OFFSET_DAYS     实例默认 day_key 偏移（生产推荐 -1=昨天）
  SCHEDULER_JOB_MODE                 daily_pipeline / ingestion_only

第 2 层 工作台 schedule_policy（运营边界，存 workspaces.config_json.schedule_policy，
  改动立即生效，无需重启）
  见 8.2 字段规格

第 3 层 resolved schedule（scheduler 每 tick 现算，不落库）
  对每个 enabled 工作台：schedule_policy 非 null 字段覆盖实例基线 → 得出
  该工作台今天的触发时刻和 day_key
```

### 8.2 工作台 `schedule_policy` 字段规格

存放：`workspaces.config_json.schedule_policy`（与 label_policy / feedback_policy /
report_policy 同级）。契约：`config/contracts/workspace_model.json` `schedule_policy`。

```json
{
  "enabled": null,
  "daily_time": null,
  "day_offset": null,
  "source_types": null,
  "retry": { "max_attempts": 1, "backoff_seconds": 900 },
  "weekly": { "enabled": false, "weekly_day": 5, "weekly_time": "17:00" }
}
```

| 字段 | 类型/取值 | 语义 |
|---|---|---|
| `enabled` | `null\|bool` | `null`=跟随实例总闸；`false`=本工作台退出自动调度；`true` 仅在实例总闸开时有效（**不能**在总闸关时打开） |
| `daily_time` | `null\|"HH:MM"` | 本工作台每日流水线触发时刻；`null`=跟随 `INGESTION_SCHEDULER_DAILY_TIME` |
| `day_offset` | `null\|int(-7..0)` | 目标 day_key 偏移；`null`=跟随 `DAILY_PIPELINE_DAY_OFFSET_DAYS` |
| `source_types` | `null\|string[]` | 本工作台调度请求的 source_type 列表；`null`=跟随实例；仍受部署级 `INGESTION_SOURCE_TYPES` 允许清单过滤 |
| `retry.max_attempts` | `int(0..5)`，默认 1 | run 级失败自动重试次数（§6.2） |
| `retry.backoff_seconds` | `int(60..21600)`，默认 900 | 首个退避间隔，指数翻倍 |
| `weekly.enabled` | `bool`，默认 false | 周报草稿自动组稿节拍开关 |
| `weekly.weekly_day` | `int(1..7)`，ISO 星期，默认 5（周五） | 周报组稿触发日 |
| `weekly.weekly_time` | `"HH:MM"`，默认 `"17:00"` | 周报组稿触发时刻 |

API（与 report_policy 完全同构）：

```text
GET   /api/workspaces/{code}/schedule-policy    workspace viewer+ 读（返回策略 + resolved 生效值 + next_run_at 预览）
PATCH /api/workspaces/{code}/schedule-policy    workspace admin+ 或 super_admin 写；
                                                校验字段取值域，非法值 422；
                                                写审计 workspace.schedule_policy.update（before/after 快照）
```

周报节拍语义：到点从最近 7 天**已发布**日报的 adopted 条目创建/刷新本周
`weekly_reports` 草稿（复用现有周报候选聚合服务，幂等键
`workspace_code + week_key`），不自动发布周报；周报发布仍是编辑决策。

### 8.3 scheduler 循环行为（已实现，2026-07-08）

- tick 周期固定 60s。每个 tick：
  1. 读实例总闸与 `DEPLOY_MODE` 能力开关；采集被禁（intranet）时跳过全部
     pipeline 投递，只保留 sync 类任务。
  2. 查询 enabled 工作台 + 各自 `schedule_policy`，解析出每个工作台的
     `next_run_at`（实例时区）。
  3. `wall_now >= next_run_at` 且该 `(workspace, day_key)` 今日未投递过
     （先查 `scheduler_heartbeats.last_enqueued_at`，再靠 §4 幂等键兜底）
     → 投递 daily pipeline job，upsert 心跳行。
  4. 扫描 §6.2 到期失败 run 投递重试。
  5. 扫描 `weekly.enabled` 工作台的周报节拍。
  6. 每个 tick 结束 upsert 所有心跳行的 `last_tick_at`。
- 兼容规则：所有工作台都没配 `schedule_policy` 时，行为与现状完全一致
  （只按实例 env 调度 `INGESTION_SCHEDULER_WORKSPACE_CODE`）；一旦任一工作台
  配了策略，scheduler 切换为"遍历 enabled 工作台"模式，
  `INGESTION_SCHEDULER_WORKSPACE_CODE` 只作为无策略工作台是否参与调度的
  判据（策略缺失=只有该兼容工作台参与）。
- scheduler 重启不补跑错过窗口超过 `SCHEDULER_MISSED_WINDOW_SECONDS`
  （新 env，默认 3600）的任务，只从下一个触发点继续；错过的日期由管理员用
  `POST /api/pipeline/daily-runs` 手动补。

### 8.4 UI 落位（页面细节归 `docs/product/`，此处只定后端供给）

- 工作台配置中心 `/workspace-settings` 新增「自动化」卡：读/写
  schedule-policy API；展示 resolved 生效值来源（"跟随实例默认 12:00" vs
  "本工作台 09:30"）、下次运行时间预览、重试策略、周报节拍。
- 今日速览 `/dashboard` 与抓取页 `/ingestion-runs` 的调度卡升级为读
  `GET /api/pipeline/scheduler/status`（§8.5）：scheduler 心跳、下次运行、
  最近 N 次 run 结果与失败重试状态。现有
  `GET /api/ingestion/scheduler`（纯 env 快照）保留为实例基线展示，标注
  "工作台级策略见自动化卡"。

### 8.5 心跳与可观测（已实现，2026-07-08）

```text
GET /api/pipeline/scheduler/status    登录用户可读；workspaces 数组按调用者
                                      membership 过滤（super_admin 全量）
```

响应：

```json
{
  "instance_enabled": true,
  "deploy_mode": "standalone",
  "capability_ingestion": true,
  "timezone": "Asia/Shanghai",
  "heartbeat_at": "2026-07-07T12:00:05+08:00",
  "heartbeat_stale": false,
  "workspaces": [
    {
      "workspace_code": "planning_intel",
      "effective_enabled": true,
      "effective_daily_time": "12:00",
      "effective_day_offset": -1,
      "policy_source": "workspace",
      "next_run_at": "2026-07-08T12:00:00+08:00",
      "last_runs": [
        { "run_id": "...", "day_key": "2026-07-06", "status": "succeeded",
          "trigger_type": "scheduler", "attempt": 1, "finished_at": "..." }
      ],
      "pending_retry": null
    }
  ]
}
```

规则：

- `heartbeat_stale = now - max(last_tick_at) > 3 * tick`（180s）；前端据此显示
  「调度器在线/离线」，不允许把查询失败渲染成在线。
- `last_runs` 取该工作台最近 5 次 daily pipeline run（含手动触发），
  `pending_retry` 回显 §6.2 的 `next_retry_at/attempt`。
- 本 API 只读 DB（心跳表 + run 表 + 策略解析），不与 scheduler 进程通信；
  scheduler 未部署（心跳表空）时 `heartbeat_at=null, heartbeat_stale=true`。

### 8.6 部署事实

standalone/cloud/extranet 要跑通自动调度，必须有 **redis + worker + scheduler
三个进程**，API 进程自身不投也不执行定时任务：

- Docker Compose 部署（推荐）自带：`deploy/docker-compose.*.yml` 已含
  `redis/worker/scheduler` 服务，`install.sh` 起来即全量。
- 宿主机裸跑（不经 compose）必须手动起三个进程，启动命令见
  `docs/deployment/development-quickstart.md` §2.1；只跑 `uvicorn` 时手动
  触发可用、自动调度静默不生效——这是过去"以为配置了但没跑"的根因，
  §8.5 的心跳卡就是为暴露这种状态而设计。

旧规则保留：

- 固定墙上时间优先于 interval 模式。
- 生产默认生成昨天日报（`day_offset=-1`），避免当天数据未完整。
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
GET  /api/ingestion/scheduler                       # 实例 env 基线只读快照（已实现）
GET  /api/pipeline/scheduler/status                 # 心跳/下次运行/最近 run（§8.5，待实现）
GET  /api/workspaces/{code}/schedule-policy         # §8.2（待实现）
PATCH /api/workspaces/{code}/schedule-policy        # §8.2，admin+，写审计（待实现）
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
| 工作台级调度策略（已实现，`backend/tests/test_scheduler_policy.py`） | §8.1-§8.3：schedule-policy API + per-workspace 触发 + 兼容规则测试通过 |
| run 级自动重试（已实现，`backend/tests/test_pipeline_retry.py`） | §6.2：failed run 按 backoff 自动重试、链路可追溯、终止告警 |
| 调度心跳可观测（已实现，`backend/tests/test_scheduler_policy.py`） | §8.5：`GET /api/pipeline/scheduler/status` 心跳/下次运行/最近 run 可自证 |

## 12. 验收设计

- 手动和 scheduler 触发同一天同参数 pipeline 不产生重复日报。
- 已发布日报再次跑 pipeline 返回明确 409 或 skipped。
- 单源失败时 pipeline 可 partial 继续。
- 生成 provider 超时只影响 generation step，日报草稿标记 fallback，不进入 SQL。
- `DEPLOY_MODE=intranet` 下 ingestion step skipped，sync pull 可运行。
- worker 重启后已入队任务可继续或标记 failed，不静默丢失。

分层调度与 run 级重试（对应 §6.1-§6.2、§8，可执行断言级）：

1. `PATCH /api/workspaces/{code}/schedule-policy` 由 workspace admin 提交
   `{"daily_time":"09:30","retry":{"max_attempts":2,"backoff_seconds":600}}`
   后：`workspaces.config_json.schedule_policy` 落库、审计出现
   `workspace.schedule_policy.update`（before/after 快照）、`GET` 返回
   `policy_source=workspace` 与正确 `next_run_at`；viewer PATCH 403；
   `daily_time="25:00"`、`retry.max_attempts=9` 等非法值 422。
2. 实例 `INGESTION_SCHEDULER_ENABLED=false` 时：工作台 `enabled=true` 也不投递
   任何 pipeline job；`GET /api/pipeline/scheduler/status` 返回
   `instance_enabled=false` 且各工作台 `effective_enabled=false`。
3. 两个工作台分别配置 `daily_time=09:00/21:00`，模拟时钟跨过两个时刻各得到
   恰好 1 个 `trigger_type=scheduler` 的 run；同一 tick 重放不产生第 2 个
   同 `(workspace, day_key)` run。
4. 所有工作台均无 `schedule_policy` 时，scheduler 投递行为与现状字节一致
   （只调度 `INGESTION_SCHEDULER_WORKSPACE_CODE`）——兼容回归测试。
5. daily run 落 `failed`（可重试 error_code）且 `retry.max_attempts=2`：
   backoff 到期后出现 `trigger_type=retry, attempt=2, retry_of_run_id=<首跑>`
   的新 run；再失败出现 `attempt=3`；第 3 次失败后不再产生新 run，且出现
   `ingestion.pipeline_retry_exhausted` 通知。
6. `published_report_conflict` / `capability_disabled` 类失败不写
   `next_retry_at`，不产生自动重试。
7. 首跑失败后同 day_key 手动重跑成功，再到 backoff 期：自动重试落
   `skipped` + `skip_reason=superseded`，不覆盖手动结果。
8. 停掉 scheduler 进程 >180s 后 `GET /api/pipeline/scheduler/status` 返回
   `heartbeat_stale=true`；前端调度卡显示离线态而非绿色。
9. `weekly.enabled=true` 到点后本周 `weekly_reports` 草稿存在且只有一份
   （幂等键 `workspace_code + week_key`），`status=draft` 未自动发布。
10. `DEPLOY_MODE=intranet` 下 status API 返回 `capability_ingestion=false`，
    scheduler 不投任何 daily/weekly pipeline job（现有能力开关回归）。
