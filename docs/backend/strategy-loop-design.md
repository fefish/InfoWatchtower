# Strategy Loop 战略闭环设计

> 状态：目标态设计稿。本文是 insight、strategic implication、requirement 和 task 的
> 后端模块事实源。长期愿景附录见 `docs/architecture/strategic-intelligence-platform.md`，
> 机器契约见 `config/contracts/strategic_loop.json`。

## 1. 模块定位

Strategy Loop 把外部情报变成内部行动：

```text
raw/news/report item
-> insight
-> strategic implication
-> opportunity_or_risk
-> requirement
-> topic task
-> feedback to scoring/source governance
```

它不是日报页面，也不是任务看板插件。它是规划部情报系统的行动闭环模块。

## 2. 不负责什么

Strategy Loop 不负责：

- 抓取外部数据。
- 生成日报/周报正文。
- 维护评论通知收件箱。
- 替代审计日志。
- 做项目管理系统的全量替代。

它只负责把“为什么这条情报重要”和“内部要做什么”结构化，并保留外部信号追溯。

## 3. 核心对象

| 对象 | 含义 | 主责 |
|---|---|---|
| `insights` | 对一条或多条外部信号的判断 | Strategy Loop |
| `strategic_implications` | 对公司战略、产品、能力、竞争或风险的含义 | Strategy Loop |
| `requirements` | 内部需求、调研题、产品建议或能力建设项 | Strategy Loop |
| `requirement_source_links` | requirement 到 report item、entity milestone、historical report/feedback、news/raw 的追溯关系 | Strategy Loop |
| `topic_tasks` | 指派给人的后续任务 | Strategy Loop |

`raw_items`、`news_items`、`daily_report_items`、`weekly_report_items` 仍由各自主模块拥有。

## 4. 最小追溯链

任何 requirement 必须能追溯到外部信号：

```text
topic_tasks.requirement_id
-> requirements.source_implication_id
-> strategic_implications.insight_id
-> insights.news_item_id / insights.raw_item_id
-> news_items.raw_item_id
-> raw_items.data_source_id
```

当 insight 从日报/周报条目创建时，还要保留：

```text
insight.source_report_type
insight.source_report_id
insight.source_report_item_id
```

这样用户能从内部任务回到日报判断，再回到原始来源。

## 5. 状态机

### 5.1 Insight

```text
draft -> confirmed -> linked_to_requirement -> archived
```

- `draft`：模型或编辑初稿。
- `confirmed`：编辑确认其判断有效。
- `linked_to_requirement`：已经沉淀出内部需求。
- `archived`：保留追溯，不再推动行动。

### 5.2 Requirement

```text
draft -> triaged -> accepted -> in_progress -> resolved -> closed
                       \-> rejected
```

- `draft`：由 insight 创建，尚未分派。
- `triaged`：管理员已初审。
- `accepted`：确认进入内部跟进。
- `in_progress`：已有任务或负责人。
- `resolved`：需求已有结论或输出。
- `closed`：归档。
- `rejected`：不纳入跟进，但保留理由。

### 5.3 Topic Task

```text
todo -> doing -> blocked -> done -> canceled
```

每次状态变化写审计，并可生成 activity event。

## 6. API 设计

目标态 API：

```text
POST /api/insights
GET  /api/insights
GET  /api/insights/{id}
PATCH /api/insights/{id}

GET  /api/strategic-implications
GET  /api/strategic-implications/{id}
POST /api/strategic-implications
PATCH /api/strategic-implications/{id}

POST /api/requirements
GET  /api/requirements
GET  /api/requirements/{id}
PATCH /api/requirements/{id}
POST /api/requirements/{id}/source-links

POST /api/topic-tasks
GET  /api/topic-tasks
GET  /api/topic-tasks/{id}
PATCH /api/topic-tasks/{id}
POST /api/topic-tasks/batch

POST /api/daily-report-items/{id}/insights
POST /api/weekly-report-items/{id}/insights
```

当前已有 requirements 和 topic tasks 的列表、创建、owner/负责人、状态更新、需求状态通知、
任务指派通知和审计；列表按 workspace viewer gate，创建/指派按 workspace admin gate，
被指派人可更新自己的任务状态和 `metadata_json.blocked_reason`。`POST /api/requirements` 已支持携带来源快捷字段，
`POST /api/requirements/{id}/source-links` 已支持给既有 requirement 追加来源证据；
`GET /api/requirements` 返回 `source_links`，可展示 daily report item、weekly report item、
entity milestone、historical report、historical feedback、news、raw、source title、source url
和 data source name。传入 report item、entity milestone 或 historical feedback 时，后端会尽量派生
相关 `news_item_id/raw_item_id`，并拒绝跨工作台或互相矛盾的显式来源 ID；传入 historical report
时只保存报告引用，不把历史报告或历史反馈改写成当前新闻。
`POST /api/daily-report-items/{id}/insights` 和
`POST /api/weekly-report-items/{id}/insights` 已完成 v1：管理员可从日报/周报条目创建
`insight -> strategic_implication -> requirement`，并在 `create_task=true` 时同步创建
`topic_task`。接口会从 report item 的 `generated_news -> news_items -> raw_items` 链路派生
来源，并写入 `requirement_source_links`；周报条目如果引用日报条目，会同时保留 weekly 与 daily
条目 ID。`GET /api/topic-tasks` 已返回 requirement 的 source links，让任务列表可以回到
requirement、report item、news、raw 和数据源；任务列表已支持 `assigned_to_me`、
`assignee_user_id`、`due=overdue|due_today` 和 `status=blocked` 筛选，响应返回 `is_overdue`
和 `blocked_reason`，用于负责人视图、逾期处理和阻塞说明。
任务批量处理 v1 已完成：`POST /api/topic-tasks/batch` 允许 workspace admin 批量处理 overdue/blocked
队列，被指派人可批量更新自己名下任务；批量接口只允许更新 `status` 和
`metadata_json.blocked_reason`，不能批量改负责人、标题、截止日期、需求关联或任意 metadata。
当批量置为 `blocked` 时必须提供阻塞原因，并写入 `topic_task.batch_update` 审计。
任务详情 v1 已设计为 `GET /api/topic-tasks/{id}`：workspace viewer 可读取本工作台任务详情，
返回 `TopicTaskRead` 同构字段，包括 requirement、assignee、`is_overdue`、`blocked_reason`
和 `requirement_source_links`，让前端详情抽屉可从 task 回到 requirement、report item、news、raw
和数据源，不需要页面自行拼接追溯。
`GET/POST/PATCH /api/insights` 与 `GET/POST/PATCH /api/strategic-implications` 已完成 v1：
workspace viewer 可读，workspace member 可创建和编辑洞察/战略影响；创建 insight 必须绑定同工作台
`news_item_id`，后端会派生 `raw_item_id` 并拒绝冲突 raw；创建 implication 会继承 insight 的
workspace/domain。`/insights` 页面已可检索、筛选、创建、编辑、确认和归档 insight，并管理战略影响，
同时展示 source title、source url 和 data source name。

需求结论反哺推荐 v1 已完成：`PATCH /api/requirements/{id}` 可通过
`metadata_json.recommendation_feedback` 写入 `outcome/reason/score_delta`；未显式传入时，
`resolved/closed` 默认映射为正向，`rejected/canceled` 默认映射为负向。后端会从
`requirement_source_links`、report item、insight 或 raw 派生目标 `news_item_id`，写入
`EditorialAction(action_type=requirement.feedback_to_recommendation)` 和审计日志，不覆盖
`raw_items/news_items/comments`。推荐模块读取该 action 进入 `feedback_score` 与
`recommendation_reason`。

至此，Strategy Loop P1 行动闭环的后端主路径已覆盖：来源追溯、洞察/战略影响、需求、任务、
负责人视图、批量状态处理、内外网同步边界、历史报告/实体事件/历史反馈来源引用和需求结论反哺推荐。

## 7. 权限

| 操作 | 最低权限 |
|---|---|
| 查看 insight/requirement/task | workspace viewer |
| 创建 insight | workspace member |
| 创建 requirement | workspace admin |
| 接受/拒绝 requirement | workspace admin |
| 创建/指派 task | workspace admin |
| 更新自己的 task 状态和 blocked reason | assignee |
| 批量更新 task 状态和 blocked reason | workspace admin 或 task assignee 自己 |
| 关闭 requirement | workspace admin |

`super_admin` 可跨工作台排查，但普通用户只能访问自己有 membership 的工作台。

## 8. 部署与同步边界

| 部署形态 | 行为 |
|---|---|
| standalone | 本地完整可用 |
| cloud | 可从云端情报沉淀需求和任务 |
| extranet | 默认只沉淀公开侧运营需求，不下发用户私有内容 |
| intranet | 需求、任务、评论留内网本地，不回流外网 |

同步默认规则：

- 外网 `raw/news/generated/report` 可下发内网。
- 内网 `requirements/topic_tasks/comments/ratings` 默认不回流。
- extranet feed 的 object types 固定为 `data_sources/raw_items/news_items/generated_news/daily_reports/weekly_reports`；
  即使误把 requirement/task 行设置成 `public_to_intranet`，feed 也必须拒绝 `requirements/topic_tasks`
  object_type。负向测试见
  `backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_strategy_loop_private_objects`。
- 如需回传聚合结论，必须设计脱敏聚合 contract。

## 9. 与其他模块关系

| 模块 | 关系 |
|---|---|
| Reports | 从采信条目创建 insight |
| Collaboration | 评论、@、任务指派产生 activity event；任务指派 event 已落地 |
| Notifications | 任务指派已通知被指派人；需求状态变化已通知 owner |
| Archive | 历史报告、实体事件和历史反馈可作为 requirement 来源；已关闭 requirement 后续可沉淀为长期知识 |
| Recommendation | 需求结论通过 `EditorialAction(requirement.feedback_to_recommendation)` 进入 `feedback_score`，不直接覆盖原始评分 |
| Audit | 状态变化、指派和关闭写审计 |

## 10. 前端页面

目标页面：

- `/requirements`：需求列表、状态筛选、来源追溯、创建/编辑。
- `/tasks`：任务列表、负责人、截止日期、状态更新、我的/逾期/阻塞筛选。
- 日报/周报详情：从条目创建 insight 或关联已有 requirement。
- `/insights`：集中管理洞察判断和战略影响。

页面不能在没有 source link 的情况下把 requirement 展示成“来源清楚”。
当前 `/requirements` 已展示真实 `source_links`，管理员创建 requirement 时可选填来源日报条目 ID；
日报/周报条目侧已提供管理员“沉淀需求”入口，创建 insight、implication 和 requirement；
后端接口同时支持 `create_task=true` 创建任务。`/requirements` 已提供推荐反哺控件，管理员可选择
正向/负向/中性结论并填写原因，提交后写入 requirement metadata 和可审计 feedback action。
`/historical-reports`、`/entity-milestones` 和 `/quality-archive` 可把历史报告、当前实体事件或历史反馈
转为 requirement 来源，`/requirements` 和 `/tasks` 必须展示来源类型并回跳原归档对象。
当前 `/tasks` 已展示 requirement/source trace 链接，
并接入我的任务、逾期和阻塞筛选；被指派人可在行内提交阻塞原因。
任务详情 v1 进入 `/tasks` 页内详情抽屉：用户可从列表行或 `/tasks?task_id=...` 查看任务详情、
负责人、截止日期、阻塞原因、需求和来源追溯；修改状态、指派和阻塞原因仍走既有行内动作和
`PATCH/POST batch` 接口。
当前 `/insights` 已展示真实外部信号追溯，workspace viewer 可读，workspace member+ 可创建和编辑
insight/implication。

## 11. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 跨对象体验仍需深化 | 从 insight 批量转 requirement、任务/评论/更多归档对象之间的解释关系完整，并补 E2E |

## 12. 验收标准

- 从一条已发布日报采信项创建 insight、requirement 和 task。
- 从 task 详情能一路追溯到 raw payload 和 source。
- `GET /api/topic-tasks/{id}` 受 workspace viewer gate 保护，前端详情抽屉使用该 API 展示 task -> requirement -> source links。
- viewer 可读但不能指派或关闭 requirement。
- 内网部署下 requirement/task 不进入 extranet feed，且 `requirements/topic_tasks` 直接请求 feed 返回 400。
- requirement 状态变化写 audit log，产生 `requirement.status_changed` activity event，并通知 owner。
- requirement 结论反哺推荐时写入 `EditorialAction(requirement.feedback_to_recommendation)`，后续推荐 run 的
  `feedback_score/recommendation_reason` 可见该信号。
- 批量任务处理只改 `status/blocked_reason`，写 `topic_task.batch_update` 审计；assignee 不能夹带非本人任务。
