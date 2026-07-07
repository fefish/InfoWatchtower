# Archive / Knowledge 资料库与知识沉淀设计

> 状态：目标态设计稿。本文是历史报告、实体大事记、质量归档、旧系统资产导入和
> 长期知识沉淀的后端模块事实源。Tech Insight Loop 迁移细节附录见
> `docs/backend/tech-insight-loop-fusion-plan.md`，当前系统实体事件机器契约见
> `config/contracts/archive_knowledge.json`，历史导入机器契约见
> `config/contracts/tech_insight_loop_legacy_import.json`。

## 1. 模块定位

Archive / Knowledge 负责保存和查询长期资产：

- 旧系统历史报告。
- 旧系统历史素材。
- 实体和大事记。
- 历史反馈、质量反馈和旧任务。
- 当前系统未来沉淀出的实体事件、结论和知识条目。

它的第一原则是无损归档和可追溯，不是把历史资产直接塞进当前推荐或 SQL。

## 2. 边界

Archive / Knowledge 负责：

- 历史资产导入 dry-run、execute、check-only 和 accepted gaps。
- 只读查询历史报告、实体大事记、质量归档。
- 保存旧行原始 payload 和引用解析缺口。
- 支持从新日报/周报持续沉淀实体事件。

它不负责：

- 当前抓取 adapter。
- 当前日报/周报采信状态。
- 公司 SQL 标准导出。
- 当前用户评论和评分。
- 旧系统运行入口。
- 本工作台已发布日报/周报的**日常按天/周回溯体验**（2026-07-08 R3 职责重定位）：
  时间线、按标签筛选、历史全量查询归 `/daily-reports`、`/weekly-reports` 页自身；
  本模块只以 `report-archive` 只读索引为报告页时间轴**供数**（§5.1），页面职责
  分工见 `docs/product/frontend-product-design.md` §13.4。

## 3. 核心对象

| 对象 | 来源 | 用途 |
|---|---|---|
| `historical_reports` | 旧 reports | 只读历史日报/周报归档 |
| `tracked_entities` | 旧 ai_entities / 当前人工新增 | 实体目录 |
| `entity_milestones` | 旧 entity_milestones / 当前人工新增 | 实体事件时间线 |
| `historical_feedback_items` | 旧 feedback / article_quality_feedback | 历史质量信号归档 |
| `historical_job_runs` | 旧 jobs | 旧任务统计和失败原因 |
| `raw_items` archive source | 旧 articles | 历史素材原始归档 |

所有旧系统原始行必须保存在 `raw_payload_json` 或 `metadata_json.legacy_tech_insight_loop`。

## 4. 导入流程

导入分四级，不允许跳过：

```text
inventory
-> dry-run
-> execute with explicit flag and DATABASE_URL
-> check-only / validation / accepted gaps
```

### 4.1 Inventory

只读旧 SQLite，输出：

- 表计数。
- 字段质量。
- 关键关系检查。
- 迁移预览。

不得写旧库或 InfoWatchtower 主库。

### 4.2 Dry-run

生成导入计划：

- 哪些 articles 可进历史 raw。
- 哪些 reports 可进 `historical_reports`。
- 引用能解析多少，缺口多少。
- 哪些记录跳过，原因是什么。

### 4.3 Execute

必须显式传入 `--execute` 和 `DATABASE_URL`。全量导入还必须有显式确认参数。

导入目标：

- 旧 articles -> 禁用归档源 + `raw_items`。
- 旧 daily/weekly reports -> `historical_reports`。
- 旧 entities/milestones -> `tracked_entities/entity_milestones`。
- 旧 feedback/jobs -> `historical_feedback_items/historical_job_runs`。

### 4.4 Check-only 与 accepted gaps

生产导入后必须跑 check-only：

- 覆盖率对齐冻结基线。
- 未解析引用清零，或写入 accepted gaps JSON。
- 确认归档资产没有进入当前日报、周报、推荐或公司 SQL。

## 5. API 与页面

| 页面 | API | 语义 |
|---|---|---|
| `/historical-reports` | `/api/report-archive*`、`/api/historical-reports*`、`/api/legacy-import/*` | 跨来源归档（2026-07-08 R3 重定位）：legacy 导入资产唯一阅读入口 + 导入验收 + 跨来源统计对比；合并检索里的已发布条目经 `detail_kind/detail_id` 深链跳报告页，不在本页读当前正文；月份导航降级为 legacy 视图筛选（页面规格见 page-specs §13） |
| `/daily-reports`、`/weekly-reports`（时间轴供数） | `GET /api/report-archive`（`report_type` + `origin=published` + `month/offset/limit`）、`GET /api/report-archive/summary`（months 桶） | 报告页 ReportTimeline 的已发布层轻量索引与跳月锚点（§5.1）；归档层只读供数，不因此获得编审语义 |
| `/entity-milestones` | `/api/tracked-entities*`（含 POST/PATCH/DELETE 与 `GET /{id}/timeline`）、`/api/entity-milestones*`（含 POST 手工补录）、`PATCH /api/entity-milestones/{id}`、`GET /api/entity-timeline/summary` | 实体目录管理、按月分组时间线、候选确认/驳回与当前事件治理、工作台级大事记总览统计 |
| `/daily-reports`、`/weekly-reports` | `POST /api/daily-report-items/{id}/entity-milestones`、`POST /api/weekly-report-items/{id}/entity-milestones` | 从当前采信条目登记实体事件 |
| `/quality-archive` | `/api/quality-archive/*`、`/api/historical-feedback-items`、`/api/historical-job-runs` | 历史反馈和旧任务 |

### 5.1 报告页时间轴的数据供给（2026-07-08 R3 定稿）

`/daily-reports`、`/weekly-reports` 的 ReportTimeline（组件规范见
`docs/product/frontend-product-design.md` §13.1）复用本模块的统一归档索引作为
**已发布层**，v1 零新增后端：

- 已发布层：`GET /api/report-archive?workspace_code=&report_type=daily|weekly&origin=published&month=&offset=&limit=`
  （viewer+，`ReportArchiveListItem` 已含 `date_key/month/status/published_at/
  item_count/detail_kind/detail_id`，足够渲染节点并深链回当前报告 API）。
- 跳月锚点：`GET /api/report-archive/summary` 的 `months` 桶（当前为
  daily+weekly+legacy 合并计数，v1 仅作为跳转锚点使用；每月精确分型计数由该月
  分页结果长度得出）。
- 草稿层不走本模块：草稿是编审层对象，时间轴草稿节点由
  `GET /api/daily-reports` / `GET /api/weekly-reports`（member+）提供；
  归档索引不暴露草稿，viewer 时间轴因此天然只含已发布节点。

边界重申：时间轴消费只是只读投影复用，报告页不因此把采信/发布语义下放到归档层；
归档层也不因供数而提前收录草稿。

后续增量（实现按需做，做时同步 `config/contracts/archive_knowledge.json` 的
`apis` 描述）：

1. `GET /api/report-archive/summary` 增加 `report_type`/`origin` 过滤，
   让跳月桶按报告类型精确计数。
2. 性能降级路径：`_report_archive_entries` 当前为全量内存聚合，工作台报告数
   超过约 1000 份时列表接口延迟上升；届时把月桶与分页下推到 SQL 聚合，
   API 形状不变，前端无感。

历史归档查询页面默认只读。任何导入动作只能由命令行或明确的运维流程触发，不能在普通查询页面隐藏执行。
当前日报/周报页允许 workspace member 从条目登记新的实体事件，但该写入只进入
`tracked_entities/entity_milestones`，不触发历史导入、不改 raw/news/report、不进入推荐或公司 SQL。
`/quality-archive` 允许 workspace admin 把单条历史反馈/质量反馈转成当前 requirement 来源，
但该动作只写 `requirements` 和 `requirement_source_links.historical_feedback_item_id`，
不把历史反馈改写成当前 comments/ratings，不触发当前抓取任务，不直接进入推荐、日报/周报采信或公司 SQL。

## 6. 当前系统持续沉淀

目标态不只导入旧资产，还要让当前系统持续沉淀知识：

```text
published daily/weekly item
-> entity mention / model / company / technology
-> curated entity milestone
-> linked source report item and raw/news
```

新增实体事件必须记录：

- `workspace_code`
- `domain_code`
- `tracked_entity_id`
- `event_type`
- `event_time`
- `importance_level`
- `source_report_item_id`
- `source_news_item_id`
- `source_raw_item_id`
- `created_by`

当前 v1 已实现：

- `POST /api/daily-report-items/{id}/entity-milestones`
- `POST /api/weekly-report-items/{id}/entity-milestones`
- `PATCH /api/entity-milestones/{id}`

当前 v2（2026-07）新增发布即沉淀与实体目录管理：

- 发布日报（`POST /api/daily-reports/{id}/publish`）时由
  `app/archive/milestones.py::extract_candidate_milestones_for_daily_report` 自动扫描
  `adoption_status = 2` 的已采信条目，标题/摘要命中 `tracked_entities` 名称或
  `aliases_json` 别名即生成 `curation_status = candidate`、`selected_for_timeline = false`
  的候选里程碑；按 (tracked_entity, news_item) 幂等（`legacy_table =
  published_report_candidate_milestones`，`legacy_id = entity_id:news_item_id`），
  人工已登记同一实体+素材时不再重复生成；可追溯 `metadata_json.current_refs`
  （news/raw/generated_news/日报条目）。抽取只写归档层，不改报告、推荐、公司 SQL。
- `POST /api/tracked-entities`（admin，工作台内名称大小写不敏感唯一）、
  `PATCH /api/tracked-entities/{id}`、`DELETE /api/tracked-entities/{id}`
  （仅 `legacy_system=current`；有里程碑的实体不可删除）。
- `GET /api/tracked-entities/{id}/timeline`（viewer 可读）：按事件月份倒序分组返回时间线，
  无时间事件归入「未标注时间」组，附候选/已确认计数。
- `POST /api/entity-milestones`（admin 手工补录）：`legacy_table = manual_entity_milestones`，
  创建即 `confirmed` 并进入时间线，可选 `news_item_id` 保留素材追溯。
- 候选确认/驳回复用 `PATCH /api/entity-milestones/{id}`（`curation_status`
  取值增加 `candidate`；确认写 `confirmed` 并展示，驳回写 `revoked` 并移出时间线）。
- 统一报告归档 `GET /api/report-archive` 与 `GET /api/report-archive/summary`
  （viewer 可读）：合并已发布日报/周报与 legacy `historical_reports`，
  支持月份/关键词/类型/来源过滤，每条附条目数、采信数、头条数、来源 top3；
  legacy 条目的条目数以引用数近似。只读，不产生写操作。
- 大事记总览 `GET /api/entity-timeline/summary?workspace_code=...`（viewer 可读）：
  工作台级实体/事件计数、精选事件数、按实体类型/事件类型/重要度分布、最早/最晚
  事件时间与未解析引用统计，供 `/entity-milestones` 页头总览。只读。

用户逻辑（阅读视角）：历史报告库与实体大事记是 viewer（游客）可见的四个阅读分区
之二（另两个是日报/周报，见 `docs/product/frontend-product-design.md` §5.3）。
普通读者的旅程是「报告归档按月/关键词回溯 → 打开某天报告读成稿 → 从条目关注的
实体跳转实体时间线看长期脉络」；候选里程碑由日报发布自动沉淀（上文发布即沉淀），
读者看到的时间线只含 `confirmed` 精选事件，候选确认/驳回是 admin 的治理动作。

写入规则：

- `entity_name` 必填；未传 `tracked_entity_id` 时按当前工作台和实体名复用或创建
  `legacy_system=current` 的 `tracked_entities`。
- 同一个日报/周报条目对同一实体重复登记时更新同一条 `entity_milestones`，不制造重复事件。
- 后端从 report item 自动补齐 `generated_news_id`、`news_item_id`、`raw_item_id`、
  `data_source_id`、daily/weekly report item id，并写入 `metadata_json.current_refs`。
- `created_by_user_id` 和 `updated_by_user_id` 写入 metadata；操作写 `audit_logs`。
- 前端 `/daily-reports` 和 `/weekly-reports` 只提供“登记事件”入口；完整时间线查看仍回到
  `/entity-milestones`。
- 当前事件支持 workspace admin 编辑、确认和撤销；确认会写 `curation_status=confirmed` 并保留在
  时间线，撤销会写 `curation_status=revoked` 并从时间线精选中移除。
- 旧系统导入事件不可编辑；`PATCH /api/entity-milestones/{id}` 对 `legacy_system!=current` 的记录返回错误。
- requirement source link 已支持 `entity_milestone_id`，`POST /api/requirements` 可通过
  `source_entity_milestone_id` 从实体事件创建跟进需求。

## 7. 权限

| 操作 | 最低权限 |
|---|---|
| 查看历史归档 | workspace viewer |
| 查看统一报告归档 / 实体时间线 | workspace viewer |
| 查看导入验收缺口 | workspace admin 或 super_admin |
| 执行导入脚本 | 运维权限 + 数据库权限 |
| 新增当前实体事件（从报告条目登记） | workspace member |
| 实体目录增删改（tracked_entities） | workspace admin |
| 手工补录里程碑 | workspace admin |
| 编辑/确认/驳回/撤销当前实体事件 | workspace admin |
| 用实体事件创建需求来源 | workspace admin |
| 用历史反馈创建需求来源 | workspace admin |

历史旧资产默认不可编辑。若未来支持修订，必须写 revision 和 audit log，不能覆盖旧行。

## 8. 与当前主链隔离

历史资产必须遵守：

- 不进入当前 `recommendation_runs`。
- 不创建 SQL-ready `generated_news`。
- 不进入标准公司 SQL。
- 不创建当前 `comments/ratings`。
- 不创建当前 `ingestion_runs`。
- 不覆盖当前 raw/news/report。

如需将历史资产用于训练、检索或参考，必须通过只读投影或显式 curated link。当前 v1
允许 workspace admin 把历史报告作为 requirement 来源：`requirement_source_links.historical_report_id`
和 `source_historical_report_id` 只保存引用，不修改历史报告正文，不让历史报告进入推荐或公司 SQL。
当前 v1 也允许 workspace admin 把历史反馈/质量反馈作为 requirement 来源：
`requirement_source_links.historical_feedback_item_id` 和 `source_historical_feedback_item_id`
只保存引用并尽量派生 raw/source 追溯，不修改历史反馈，不创建当前评论/评分，不让历史反馈进入推荐或公司 SQL。

## 9. 部署与同步

| 部署形态 | 行为 |
|---|---|
| standalone | 可本地导入和查看 |
| cloud/extranet | 可保存公开历史资产 |
| intranet | 可接收外网同步来的历史可见资产，但本地反馈留本地 |

历史资产同步必须遵守 `visibility_scope` 和 `sync_policy`。旧系统中可能包含内部文本时，
导入前必须人工确认 visibility。

## 10. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 生产主库全量导入验收未留证 | `validate_tech_import_acceptance.py` 对生产 check-only 报告通过 |
| 历史知识跨对象体验仍需深化 | requirement/task 已可解释引用历史报告、实体事件和历史反馈；后续补更多对象联动体验和 E2E |
| 归档页重定位未实施（R3 设计） | `/historical-reports` 已发布条目改深链跳报告页、月份导航收敛 legacy 视图、页头跨来源定位文案；断言见 page-specs §13.4 |
| summary 跳月桶不分报告类型 | `GET /api/report-archive/summary` 支持 `report_type`/`origin` 过滤并同步 `config/contracts/archive_knowledge.json`（§5.1 后续增量 1） |
| 跨工作台聚合检索（目标态 v2）未设计 | 本文档补多 workspace_code + membership 过滤的 API 设计后才允许前端入口 |

## 11. 验收标准

- 旧资产导入脚本默认 no-write。
- 全量执行必须显式确认，且输出机器可验收报告。
- 历史报告、实体事件、质量归档页面的查询不产生写操作；显式“转需求”只写当前 requirement/source link。
- 任一历史报告引用缺口可在页面和 JSON 报告里看到。
- 历史资产不会出现在当前推荐 run、日报采信或标准公司 SQL 中。
- 历史反馈转需求必须保留 `historical_feedback_item_id`，并可从 `/requirements`、`/tasks` 回跳 `/quality-archive?feedback_id=...`。
- 报告页时间轴对归档索引的消费保持只读（§5.1）：`report-archive` 不因供数收录
  草稿、不新增写端点；legacy 报告不出现在报告页时间轴。
