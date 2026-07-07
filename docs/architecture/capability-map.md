# InfoWatchtower 能力地图

状态：2026-07-07 按部署拓扑收口第三轮刷新（wechat adapter/三预设/自动发布与发布后修订/
归档 v2/viewer 阅读视角/credential_ref/工作台可见性与订阅/用户组与指派/游客登录/
工作台配置中心）。四形态 × 能力 × 必跑测试矩阵见 `docs/backend/backend-capability-test-matrix.md`。

本文是“状态和差距地图”，不是新的总纲。它回答三件事：

1. 目标态能力分块目前分布在哪些后端、前端、数据和配置位置。
2. 哪些能力已完成或已有证据。
3. 距离目标态还差什么、按什么标准判定完成。

目标架构和硬约束仍以 `docs/00-system-design.md` 为准；前端页面设计以
`docs/product/frontend-product-design.md` 为准；后端模块边界以
`docs/backend/backend-module-design.md` 和对应模块专题文档为准；字段与流程契约以
`config/contracts/*.json` 为准。

本文允许记录“现状”和“Gap”，但不得通过状态描述反向修改目标架构。

## 1. 能力地图目标态摘要

**一个多工作台的产业情报操作系统**：任何团队可自助开一个工作台、自助接信息源，共享同
一条「采集 → 处理 → 评分 → 生成 → 编审 → 多版成稿 → 分发」流水线；规划部是第一个也
是口径最严的租户（公司 SQL 合同），技术洞察快报（原同事系统）的源治理、评分器、板块
组织和成稿格式已全部融合进主链路。

## 2. 总架构

```text
                ┌────────────────────────────────────────────────────────┐
                │  H 平台底座：工作台模型 / 登录RBAC / 审计 / 调度 / 部署 / 设计系统  │
                └────────────────────────────────────────────────────────┘
 A 信息源与采集        B 处理主链           C 推荐与评分         D 生成与成稿
 共享源池+自建源   →   raw_items        →   ContentScorer v2 →  MiniMax 五段+insight
 抓取/补采/覆盖率      news_items           准入 P0-P3/R        rendition 格式注册表
                       dedupe_groups        推荐 run             MD / HTML 导出
                                                  │
                E 编审与发布 ←────────────────────┘
                日报/周报采信 · 头条 · 双版视图 · 发布
                       │                          │
 F 分发与集成 ←────────┘          G 资料库与知识沉淀
 公司 SQL 4表合同+校验+追溯        历史报告库 / 实体大事记 / 质量归档
 多环境同步包                      insight → requirement → task 战略闭环
```

硬边界（全局不变式，见 AGENTS.md）：raw 原始报文只被同源同 entry_key 重抓刷新为
最新抓取快照，下游环节永不回写；去重在 news 之后推荐之前；
`adoption_status` 只属于采信层；公司 SQL 只导出已发布日报中 `adoption_status=2` 且
MiniMax ready 的条目、category 十分类、`content_json` 五段；业务板块只存
`insight_json`，永不写 category；rendition 是投影不是副本。

## 3. 能力分块与分布架构

### A. 信息源与采集

| 层 | 位置 |
|---|---|
| 后端 | `app/ingestion/`（runs/fetch/jobs/source_seeds）、`app/adapters/`（rss/page/base 浏览器 UA） |
| API | `POST/PATCH /api/sources*`（自建/补入口/工作台链接）、`/api/ingestion/runs`（并发/超时/`max_items_per_source`）、`POST /api/ingestion/runs/{run_id}/retry-failed-sources`、`/api/ingestion/backfill-runs`、`/api/ingestion/coverage` |
| 前端 | `/sources`（信息流源列表+标签策略+自建源）、`/ingestion-runs`（抓取与覆盖、目标日漏斗） |
| 数据 | `data_sources`（共享池）、`workspace_source_links`（工作台启用/权重/日限）、`ingestion_runs` |
| 配置 | `config/seeds/`（旧种子 294 + Tech 386）、`contracts/source_fields.json`、`taxonomy/source_tags.json` |

现状：✅ 663 治理记录去重成共享池；自建源/补入口界面化；浏览器 UA 对齐旧系统；单源上限
参数化；覆盖率漏斗可解释"为什么当天候选少"；`GET /api/ingestion/coverage/trends`
和抓取页近 14 日趋势卡可解释最近是否持续失败或持续 0 产出；`GET /api/ingestion/scheduler` + 抓取页
「自动调度」卡展示调度配置；`RSSHUB_BASE_URL` 配自建 RSSHub 后，`rsshub.app` 前缀源
自动改走自建实例（X/部分公众号路由的可用通道）；失败源手动重试 v1 已能只重试上一轮
`summary_json.sources.status=failed` 的启用源，并记录 `retry_of_run_id/source_ids`；`paper_api`
arXiv v1 已支持自建源、目标日期 submittedDate 查询和论文元数据 raw payload，OpenAlex Works v1
已支持 `api.openalex.org/works` 源、目标日期 publication_date filter、abstract inverted index 还原和完整 work payload 保留，Semantic Scholar v1
已支持 `api.semanticscholar.org/graph/v1/paper/search/bulk` 源、目标日期 `publicationDateOrYear` filter、optional `SEMANTIC_SCHOLAR_API_KEY` 和完整 paper payload 保留；12 类 source_type 已全部有真适配器
（wiseflow=对接 wiseflow 4.x `POST /read_info` 分页、crawler=通用列表页爬虫、csv=本地/远程 CSV、
paper_page=论文列表页、manual/internal=推入式语义，internal 配 `api_url` 后升级为通用 JSON API
拉取器，wechat=自研微信公众号 adapter：rsshub 主路径 + `article_urls` 定点抓取，不依赖
wx 二进制，风控验证页记失败不落 raw；实现状态表见 `docs/backend/backend-capability-test-matrix.md` §3），run 层
`skipped_unimplemented` 显式语义保留为未来未实现 adapter 的安全网；`manual_import` 已有
上传/粘贴 CSV/SQL、后端预览、逐行校验、错误报告下载和 0 accepted 阻断，要求归属已启用源并保留原始行 payload，不再空导入显示成功；源详情
`GET /api/sources/{id}` 已返回安全投影，前端 `/sources/:id` 可查看工作台启用、最近 raw、
run 错误日志和 raw 趋势，且不暴露 `raw_payload_json/fetch_config/credential_ref`；`/sources`
已用组件测试锁住标签策略保存失败错误态，避免权限/网络失败被显示成保存成功；失败源自动重试队列 v1
已支持 `INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED`、到期/阻塞摘要、scheduler 投递和同一 ingestion/backfill 服务重放；
到期/阻塞失败源会生成 `ingestion.failed_source_retry_due/blocked` 站内 important 通知并跳回
`/ingestion-runs?run_id=...`；adapter 凭据统一走 `credential_ref`（`env:VAR` / `file:/path`，
`backend/app/core/credentials.py`，非法/缺失降级匿名并记 WARNING），取 token 顺序
`credential_ref → auth_token_env → auth_token`；部署级采集类型允许清单
`INGESTION_SOURCE_TYPES`（`install.sh --preset rss-only` 写入）在 run 内过滤启用源，
不在清单的源计入 `skipped_type_disabled` 并在前端显示「类型停用」语义。
**Gap**：① wechat 采集增强（原 C-1 范围已缩小）：`wechat` adapter 已自研落地；剩余为
可选增强——wx 桥接 sidecar（`WX_BRIDGE_URL/WX_BRIDGE_TOKEN`，契约见
`docs/deployment/deployment-topology.md` §5.1）参考实现、向同事确认 wx 二进制事实，
以及自建 RSSHub/桥的实机抓取验收。
② 超出 RSS 窗口的深度历史补采（P1）
③ 自建 RSSHub 实例部署与 `RSSHUB_BASE_URL` 配置（P1 运维动作，X 源可用的前提）
④ 更多论文 API provider（OpenReview 等，C-3 后续 provider 扩展）
⑤ 手工导入更复杂 SQL dialect 和大文件分片治理
⑥ 邮件/外部告警通道和生产 runbook。

### B. 处理主链（raw → news → 去重）

| 层 | 位置 |
|---|---|
| 后端 | `app/normalization/news.py`、`app/dedupe/` |
| API | `POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups` |
| 前端 | `/news` 候选池（winner/loser、重复来源、追溯链） |
| 数据 | `news_items`、`dedupe_groups`、`dedupe_group_items`（rank_score 为内部去重权重，非 0-100 分） |

现状：✅ 工作台隔离去重、winner/loser 回写、全链路追溯。
**Gap**：页面监控源的深度抽取与增量差异识别仍是轻实现（P2）。

### C. 推荐与评分（Tech Insight Loop 评分器已融合）

| 层 | 位置 |
|---|---|
| 后端 | `app/recommendations/service.py`（准入引擎）、`app/scoring/content_scorer.py` |
| API | `POST/GET /api/recommendation/runs`、`GET /api/recommendation/scorer-policy`、`POST /api/recommendation/scorer-preview` |
| 前端 | `/recommendations`（分数拆解 + 评分策略摘要 + 单条评分预览 + P2/P3 观察池复核）、`/news` 与今日速览的准入徽章 |
| 数据 | `recommendation_runs/items`（admission_level/pool、noise_types、scorer_breakdown、expert_routes） |
| 配置 | `config/scoring/content_scorer_v2.json`（阈值/权重/噪声规则/专家路由） |

现状：✅ P0-P3/R 准入、噪声降权、技术情报优先策略稳定输出（0-100 分口径）；评分器
运营页 v1 已能只读展示当前配置版本、阈值、日报/周报准入层、权重 TopN、主题 TopN 和噪声规则摘要，
并提供不落库的单条候选 scorer preview；推荐 run 详情已回显 `daily_report` 采信 trace，
`/recommendations` 可对 P2/P3 未入选观察池候选执行真实采信/剔除到日报草稿；
`EditorialAction(requirement.feedback_to_recommendation)` 已进入 `feedback_score` 和
`recommendation_reason`。
**Gap**：评分器策略编辑、批量重算影响评估（旧系统质量闭环的实时化，P2）；
观察池排序策略、复核备注、抽检队列和生产抽样验收（P2）。

### D. 生成与成稿（一次采信，多版成稿）

| 层 | 位置 |
|---|---|
| 后端 | `app/llm/`（MiniMax 五段+category+insight prompt v2）、`app/reports/renditions.py`（格式注册/投影/MD）、`app/reports/rendition_html.py` |
| API | `GET/POST/PATCH/DELETE /api/report-formats`、`/api/{daily,weekly}-reports/{id}/renditions/{format}/regenerate|export` |
| 前端 | 日报/周报页成稿 tab（默认技术洞察版）、格式管理滑出面板、MD/HTML 导出 |
| 数据 | `generated_news`（content_json 五段 + `insight_json` 板块/要点/总结/标签行）、`report_formats`（company_sql_v1 locked + tech_insight_v1 + 自定义）、`report_renditions` |
| 配置 | `taxonomy/business_boards.json`（14 板块，辅助维度）、`contracts/report_renditions.json` |

现状：✅ P1-P4 已实施：双内置格式、头条自动 Top6+可调、板块分组、MD/HTML 导出对齐快报
样式、自定义格式注册表、周报双版、周报摘要段规则投影 v1；未配 MiniMax key 时 insight 走规则降级并标注；
`scripts/validate_minimax_generation_acceptance.py` 已提供真实 key 结构验收和 fixture pytest。
真实 MiniMax 验收已通过并归档到 `outputs/minimax/minimax_generation_acceptance.json`；
validator 会拒绝来源未给出的百分比、P95/P99、倍数、延迟/显存数值，避免模型成稿编造指标。
**Gap**：① 模型版 insight/成稿在真实生产日报流水线中持续抽检（P0 运维动作）
② LLM 周报摘要模型生成（当前已有规则投影 v1，P1）③ 快报 PPT 导出（旧系统能力，
可选插件，P2）。

### E. 编审与发布

| 层 | 位置 |
|---|---|
| 后端 | `app/api/routes/reports.py`、`app/pipeline/daily.py`、`app/reports/weekly.py` |
| API | 日报/周报 CRUD、publish、条目采信/编辑/头条、候选池批量采信、`regenerate-generated-news`、点赞/评分/评论 |
| 前端 | `/daily-reports`（成品优先，内网版=编审 tab）、`/weekly-reports`、`/news` 批量采信和采信状态 |
| 数据 | `daily_reports/items`（is_headline）、`weekly_reports/items`、feedback 表族 |

现状：✅ 自动生成草稿→成品直读→编审微调的心智对齐快报；候选池批量采信到日报草稿、服务端筛选排序、批量剔除、候选 watch 和完整 trace 复核 + 业务解释 v1 已完成；
scheduler 打开即每日自动跑（代码默认 12:00，中午汇总昨天）。
每日自动发布 + 发布后修订已落地：工作台 `report_policy.auto_publish_daily`（默认 true，
`GET/PATCH /api/workspaces/{code}/report-policy`）控制流水线出稿即发布（actor=system，
审计 `daily_report.auto_publish`）；published 日报报告层字段允许 admin+ 修订，写
`post_publish_revision` 审计并重投影 renditions，raw/`generated_news` 与公司 SQL 契约
不动（`docs/backend/reports-editorial-design.md` §7.1/§7.2）。viewer（游客）阅读视角
已落地：阅读分区 min_role=viewer、管理路由重定向、编审操作整组隐藏、成稿读发布时
投影快照（`docs/product/frontend-product-design.md` §5.3）。
**Gap**：① 候选池跨页联动继续增强（P2）② 编辑器体验（富文本/差异对比，P2）③ 流水线重
计算移出事件循环（已建后台任务卡片，P1 技术债）。

### F. 分发与集成

| 层 | 位置 |
|---|---|
| 后端 | `app/exports/company_sql.py`、`app/sync/` |
| API | `/api/exports*`（含 trace）、`/api/sync*`（包导出/下载/导入幂等） |
| 前端 | `/exports`、`/sync` |
| 数据 | `export_jobs/items`、`sync_outbox/inbox/runs` |
| 校验 | `scripts/validate_company_sql.py`（0505 基准） |

现状：✅ 4 表合同+逐字段校验+导出前 preflight 摘要+语句级追溯；同步包可导出/下载/导入，`data_sources/raw_items/news_items/generated_news/daily_reports/weekly_reports`
已按 `object_global_id/global_id` 幂等 apply，revision/hash 冲突写 `sync_conflicts`。
联动同步已实现（`docs/deployment/deployment-topology.md` §3）：extranet
`GET /api/sync/feed(/manifest)` service token 下发 + intranet `sync_cursors` 定时拉取，
inbox failed 可通过本地 `POST /api/sync/inbox/retry-failed` 重放；`GET /api/sync/conflicts` 和 `POST /api/sync/conflicts/{id}/resolve`
已提供 open conflict 查询与 `keep_local/ignored/retry_after_dependency/use_incoming/manual_merge` 人工处置，
`GET /api/sync/health` 已汇总 `sync_cursors` 水位、缺失水位、失败水位、failed inbox、自动 backoff 到期/阻塞状态、最近失败 run 和 open conflict 告警；
同步游标语义 P0 已收口：consumer 每轮对每类对象第一页回退 300s 回看窗口重放（补偿 publisher 长事务漏发，重复事件由 inbox event_id 终态吸收）、
conflict 为 inbox 终态不卡水位（冲突页照常推进 cursor，open 冲突按对象幂等去重不重复发通知）、
manifest/feed 传输失败落 `status=failed` 的 SyncRun 并置 cursor `last_status=failed`；
feed 鉴权支持 `name:token` 命名消费者且 manifest/page 读取写审计（`sync_feed.manifest/read`）；
前端 `/sync` 已展示 runtime 发布者/消费者能力、同步健康、水位/failed inbox 告警、failed inbox 手动重试、自动 backoff 策略、内网「立即拉取」、外网「导出同步包」、本地/传入 JSON 预览、使用传入和人工合并动作；
outbox 手工包降级为人工通道；公司 SQL 导出已提供服务端流式下载端点，下载由 workspace admin/super_admin
保护，普通 viewer 只能查看历史和 trace，不能下载 SQL 文件；大文件下载策略 v1 已补 `sql_text_bytes`、
截断预览和 `X-InfoWatchtower-Download-Strategy=server_streaming` 响应头，前端不会把截断预览当完整 SQL；
trace 详情 v1 已展示 SQL 片段、标题/摘要/关键点来源、五段正文来源、编辑覆盖字段和导出/编辑/生成/raw 字段差异预览；导入回执 v1
已能记录内网导入状态、失败 SQL 序号/表、错误码和错误原因，并把失败项回链到 `export_job_items`；内网 importer 自动回调 v1
已支持 `SYNC_SERVICE_TOKENS` Bearer 鉴权、不走用户 cookie、CSRF 精确豁免；批量导出治理 v1
已提供 batch manifest、逐日成功/失败结果、validation summary 和成功日独立下载/trace。
**Gap**：① extranet->intranet 端到端实机同步证据和生产备份恢复演练（P0 运维）
② 生产级同步监控告警投递深化（P1）
③ 更多对象 `manual_merge` 范围深化（P2）
④ 公司 SQL 真实内网平台生产联调证据（P1，当前已有人工/API 回执和 service token 回调接口）。

### G. 资料库与知识沉淀

| 层 | 位置 |
|---|---|
| 后端 | `app/ingestion/tech_insight_loop_legacy.py`、`scripts/tech_insight_loop_*.py`（inventory/dry-run/import/verify） |
| API | `/api/historical-reports*`、`/api/tracked-entities`、`/api/entity-milestones*`、`/api/quality-archive*`、`/api/legacy-import/*` |
| 前端 | `/historical-reports`（含导入验收面板）、`/entity-milestones`、`/quality-archive`；质量归档页测试 `frontend/src/pages/QualityArchivePage.spec.ts` |
| 数据 | `historical_reports`、`tracked_entities/entity_milestones`、`historical_feedback_items/historical_job_runs`、`insights/requirements/topic_tasks` |

现状：✅ 旧库 14834 素材/66 报告/275 大事记的导入脚本、只读页、验收摘要、引用缺口全链
就绪（默认 no-write）；`scripts/validate_tech_import_acceptance.py` 可对生产 `--check-only`
报告做机器验收，覆盖率、只读边界和已归档缺口不满足时直接失败。本地隔离 PostgreSQL 全量导入
证据已归档到 `outputs/tech_insight_loop/postgres_full_import_20260703T050653Z/`，7 项覆盖率 complete，
30 个旧库断链引用已通过 `tech_insight_loop_import_accepted_gaps.json` 归档；旧 PDF/二进制文本中的
NUL byte 会转义为 `\u0000` 标记并写入 `legacy_import.nul_sanitized_fields` 审计。
Strategy Loop 已补 requirement source links v1：`POST /api/requirements` 支持来源快捷字段，
`POST /api/requirements/{id}/source-links` 可追加 daily/weekly report item、news 或 raw 证据，
列表会返回 source title、source url 和 data source name，前端 `/requirements` 已展示真实来源追溯。
report item strategy loop v1 已补齐：`GET/POST/PATCH /api/insights`、
`GET/POST/PATCH /api/strategic-implications` 可独立管理洞察和战略影响，并保留 news/raw/source
追溯；`POST /api/daily-report-items/{id}/insights` 和
`POST /api/weekly-report-items/{id}/insights` 可从日报/周报条目创建 insight、implication、
requirement 和可选 task，并把任务列表回链到 requirement/source links。task owner view v1
已补齐：`GET /api/topic-tasks` 支持 `assigned_to_me`、`assignee_user_id`、`due=overdue|due_today`
和 `status=blocked` 筛选，响应返回 `is_overdue/blocked_reason`，`/tasks` 可展示我的/逾期/阻塞视图并由负责人提交 blocked reason。
task batch update v1 已补齐：`POST /api/topic-tasks/batch` 可批量更新 `status/blocked_reason`，
workspace admin 可处理 overdue/blocked 队列，被指派人只能处理自己名下任务，前端 `/tasks`
提供选择当前可更新任务、批量状态和批量阻塞原因提交。
task detail v1 已补齐：`GET /api/topic-tasks/{id}` 按 workspace viewer gate 返回任务、负责人、
阻塞原因、requirement 和 source links；前端 `/tasks` 从列表行或通知锚点打开只读详情抽屉，
并可跳回 requirement、report item、news/raw 和数据源证据。
Strategy Loop sync boundary v1 已补齐：extranet feed object types 只允许公开源、raw/news、成稿和报告六类对象，`requirements/topic_tasks`
负向请求返回 400，避免内网需求/任务回流。
协作/通知 sync boundary v1 已补齐：`comments/reactions/ratings/activity_events/notifications/notification_preferences`
不进入 feed manifest，直接请求 feed 返回 400，避免本地用户反馈和收件箱状态跨实例泄露。
需求结论反哺推荐 v1 已补齐：`PATCH /api/requirements/{id}` 可写
`metadata_json.recommendation_feedback`，后端派生目标 news item 并写
`EditorialAction(requirement.feedback_to_recommendation)`，推荐 run 读取该信号进入
`feedback_score/recommendation_reason`，前端 `/requirements` 可提交正向/负向/中性反哺。
实体事件登记 v1 已补齐：`POST /api/daily-report-items/{id}/entity-milestones` 和
`POST /api/weekly-report-items/{id}/entity-milestones` 可从当前日报/周报条目登记
`entity_milestones`，后端复用/创建 `legacy_system=current` 的 tracked entity，并保留
report item、generated news、news、raw 和 data source current refs；前端日报/周报页有
workspace member “登记事件”入口。
实体事件治理 v1 已补齐：`PATCH /api/entity-milestones/{id}` 可编辑、确认和撤销当前系统新登记事件，
旧导入事件不可编辑；`requirement_source_links.entity_milestone_id` 和
`source_entity_milestone_id` 可把实体事件转成需求来源，前端 `/entity-milestones` 已有编辑、
确认、撤销和转需求入口。
历史报告到 requirement 引用 v1 已补齐：`requirement_source_links.historical_report_id` 和
`source_historical_report_id` 可把旧日报/周报作为需求来源，`/historical-reports` 详情页管理员可
转需求，`/requirements` 与 `/tasks` 可展示并跳回历史报告。
历史反馈到 requirement 引用 v1 已补齐：`requirement_source_links.historical_feedback_item_id` 和
`source_historical_feedback_item_id` 可把旧反馈/质量反馈作为需求来源，`/quality-archive` 管理员可
转需求，`/requirements` 与 `/tasks` 可展示并跳回 `/quality-archive?feedback_id=...`；该链路只保存历史反馈引用，
不创建当前 comments/ratings，不让历史反馈进入推荐、日报/周报采信或公司 SQL。
报告归档与实体大事记 v2 已落地：`GET /api/report-archive(/summary)` 统一归档当前
日报/周报与旧导入报告，`GET /api/entity-timeline/summary` 实体时间线总览；
tracked_entities 支持增删改、手工补录里程碑、发布即沉淀候选里程碑和候选确认/驳回；
`/historical-reports`、`/entity-milestones` 页面已按真实用户闭环改版
（`docs/backend/archive-knowledge-design.md`、`config/contracts/archive_knowledge.json`）。
**Gap**：① 生产主库执行同一套全量导入验收（P0，一条命令级动作+机器验收+缺口人工复核）② 跨对象体验和更多协作对象解释关系深化（P2）③ `GET /api/entity-timeline/summary` 补 workspace membership 断言（当前仅要求登录，低危已知差距）。

### H. 平台底座

| 层 | 位置 |
|---|---|
| 工作台模型 | `app/models/workspace.py` + `POST /api/workspaces`（自助建台：核心分区/标签策略/格式/成员自动配齐）+ 分组导航（today/collect/curate/library/collab/system） |
| 身份与审计 | `app/auth/`（public_password/intranet_header/OIDC）、RBAC 四角色、workspace membership、`audit_logs`；目标设计见 `docs/backend/identity-access-design.md` 和 `docs/backend/audit-ops-observability-design.md`，审计契约见 `config/contracts/audit_ops.json` |
| 调度 | `app/workers/`（RQ worker + scheduler，`INGESTION_SCHEDULER_*` env） |
| 部署 | `deploy/docker-compose.{local,prod,intranet,extranet}.yml` + `env.{production,intranet,extranet}.example` + `nginx.portal.example.conf`（PG+Redis+API+worker+scheduler+前端 nginx；cloud/extranet 可选 caddy TLS profile；intranet 离线升级 `scripts/export_offline_bundle.sh`/`upgrade_offline.sh`） |
| 工作台策略 | `app/workspaces/policy.py`（策略解析：标签策略→domain pack→内置 AI 默认）+ `GET /api/domain-packs` |
| 设计系统 | Apple Liquid Glass（`base.css` :root token + 唯一主题层）、晨报式今日速览、≤1120px 图标栏响应式 |

现状：✅ 工作台模型、三步建台向导、成员管理、导航/分区/格式数据库驱动和 hardware domain pack 样例已落地；✅ `feedback_policy` 已成为工作台配置，支持读写 API、审计、日报条目后端权限检查、日报页禁用规则和 `/users` 影响确认编辑；✅ 登录限流、邀请建号、`/invite` pending/expired/revoked/accepted 状态体验、改密/重置、会话密钥自检、通用 OIDC code flow + PKCE、OIDC claims 配置映射、OIDC/local redirect 回跳、OIDC provider/callback 错误安全回跳、默认/部门 membership 自动映射、工作台 DB 部门映射编辑、登录页 auth mode 分流和主要业务 API membership gate 已落地；✅ `/users` 已形成用户、邀请、工作台成员、策略四块入口，非 `super_admin` 不显示全局用户/邀请操作，并补充邀请状态展示、自动开通规则展示/编辑、身份权限审计摘要、成员角色影响提示、owner 数量提示、最后 owner 前后端守护、owner 移出/降权二次确认、viewer 反馈策略编辑、权限变更 diff 解释和批量回滚；✅ `audit_logs.workspace_code`、工作台审计查询权限、审计 secret-like 统一脱敏、`/audit-logs` 工作台过滤页面和组件测试已落地；✅ sync feed/package/apply 已共用 secret-like 拦截规则，含密钥 payload 不进入同步包或业务表；✅ `install.sh`、启动自动迁移、`/setup`、生产自检（`/healthz` 存活 + `/readyz` 数据库就绪探针）、备份/恢复脚本和 §9 全量业务验收脚本已落地。干净 Docker 证据已归档到 `outputs/acceptance/20260703T062259Z/`。
✅ 部署拓扑信任边界已收口（2026-07-07）：四形态 `allowed_auth_modes` 白名单启动自检、
`AUTH_SESSION_SECRET` 全 auth_mode 三入口自检、`AUTH_TRUSTED_PROXY_CIDRS` 生效
（身份头/限流 XFF 只信白名单 peer）、OIDC id_token 验签/强校验（`OIDC_JWKS_URI`）、
CSRF 邀请豁免收窄为仅匿名 accept、`_safe_relative_redirect` 拒反斜杠变体；
`VITE_BASE_PATH` 子路径部署（vite base + router base + API 前缀三处联动）、前端 nginx
envsubst 模板输出 frame-ancestors CSP 并清洗身份头、`deploy/nginx.portal.example.conf`
门户反代样例、intranet/extranet compose 与 env 样例、cloud/extranet caddy TLS profile、
intranet 离线升级脚本、`scripts/check_prod_deploy.py` 按 DEPLOY_MODE 校验工件。
✅ 多工作台策略中枢（`app/workspaces/policy.py`）：评分/分类降级/成稿看板/降级文案/
公司 SQL gating 按「标签策略→domain pack→内置 AI 默认」解析，planning_intel 行为
逐字节不变，非 AI 工作台不再被 AI 噪声规则误杀；`hardware.json` 成为可用 pack 样例。
✅ 部署预设与凭据治理（2026-07-07）：`deploy/install.sh --preset rss-only|full|mirror`
（默认 full，契约 `config/contracts/deployment_modes.json` `install_presets`）；
`INGESTION_SOURCE_TYPES` 采集类型允许清单（非法值拒启）；`AUTH_SESSION_SECRETS`
逗号列表密钥轮换（第一个签名、全部可验签，换密钥不掉线）；`credential_ref` 凭据解析；
`http.ts` `onUnauthorized` 注册点 + `session.ts` 401 统一清会话跳 `/login?redirect=`。
✅ 工作台可见性与自助订阅（2026-07-07）：`workspaces.visibility`
（private/internal_public，种子只设初值不覆盖 API 决定）、`GET /api/workspaces/discover`
不泄露 private、`POST/DELETE /api/workspaces/{code}/subscribe` 幂等订阅/退订（viewer，
不降级已有角色、保护最后 owner）、`PATCH /api/workspaces/{code}/visibility`（admin+，
暂无页面入口）；前端「发现工作台」抽屉组件 `WorkspaceDiscovery.vue`；证据：
`backend/tests/test_workspace_subscription.py`、`frontend/src/components/WorkspaceDiscovery.spec.ts`、
`config/contracts/workspace_model.json` `discovery_and_subscription`。
✅ 用户组与批量入台/任务指派（2026-07-07）：`user_groups/user_group_members` 运营分组
（非第三层权限），组 CRUD 权限门 super_admin/editor_admin；
`POST /api/workspaces/{code}/members/bulk` 按组幂等批量入台（不升降级已有角色、停用
账号跳过、owner 走单人危险确认，审计 `workspace.member.bulk_upsert`）；任务指派要求
被指派人是同工作台成员并触发 `task.assigned` 站内通知，`GET /api/topic-tasks` 支持
`assignee=me`；证据：`backend/tests/test_user_groups.py`、`backend/tests/test_operations_api.py`、
`frontend/src/pages/UsersPage.spec.ts`、`config/contracts/auth_modes.json` `user_groups`、
`config/contracts/strategic_loop.json` `task_assignment_v1`。
✅ 游客登录（2026-07-07）：`AUTH_GUEST_ENABLED` 叠加开关（仅 standalone/cloud，
fail-fast），`POST /api/auth/guest-login` 共享只读账号、无 membership、隐式 viewer
浏览 internal_public 工作台，写操作 `get_current_user` 单点 403（仅放行 logout），
关闭开关存量会话立即失效；证据：`backend/tests/test_auth.py` guest 段、
`frontend/src/pages/LoginPage.spec.ts`、`config/contracts/auth_modes.json` `guest_access`。
✅ 工作台配置中心（2026-07-07）：`workspace_settings` system 分组核心分区
（`config_json.min_role=admin`，不可停用），`/workspace-settings` 页面收敛基本信息、
导航分区启停（`GET /sections/manage` + `PATCH /sections/{key}`，决定持久化
`config_json.user_enabled`）、标签策略、报告策略（自动发布）、成员与报告格式；证据：
`backend/tests/test_workspaces_api.py`、`frontend/src/pages/WorkspaceSettingsPage.spec.ts`、
`config/contracts/workspace_model.json` `section_management`。
✅ 测试看护：前端 Vitest 已实际接入 `make test` 与 CI（Test frontend 步骤先于 build）；
Playwright e2e 脚手架（`frontend/playwright.config.ts` + `e2e/smoke.e2e.ts`）已交付并
实跑 3 条 smoke 全绿（`make e2e` 可选 target，不进 CI 门禁）。
**Gap**：① OIDC 真实 provider 验收证据（Identity，E 系）
② 邮件投递和反馈对象扩展（Collaboration）
③ 长期覆盖趋势与异常告警（P2）④ 快报 PPT 插件（P2）
⑤ 建台向导第 3 步接 `GET /api/domain-packs` 动态列 pack（前端待办）
⑥ 双实例网络演练/prod TLS 证书/门户真实 iframe 联调/离线升级演练（E 系实机动作）。

## 4. 状态与差距汇总

### 4.1 已闭环重点能力

| 能力 | 所属块 | 证据 |
|---|---|---|
| 干净环境 §9 全量业务验收 | H/F | `scripts/run_full_acceptance.py` 已输出到 `outputs/acceptance/20260703T062259Z/`，覆盖 Setup、邀请、建台、共享源+自建源、标签策略、周报格式、流水线、日报/周报 MD/HTML、公司 SQL 校验和备份 |
| MiniMax key 配置后模型版 insight/成稿验收 | D | `outputs/minimax/minimax_generation_acceptance.json` 状态 `passed`；validator 覆盖技术洞察版结构、五段 `content_json`、短关键词和无编造数值门禁 |
| extranet feed / intranet pull 基础链路 | F | `backend/tests/test_sync_feed_pull.py`、`backend/tests/test_deployment_modes.py` 覆盖 feed token、manifest/page、pull 水位前进和对象 apply |
| failed inbox 本地重放与自动 backoff v1 | F | `sync_inbox.record_json/error_message/attempt_count/last_attempt_at` 保存失败 envelope 和尝试状态；`POST /api/sync/inbox/retry-failed` 复用 apply handler 重放 failed 行并写 `direction=inbox_retry`；scheduler 可按 `SYNC_FAILED_INBOX_*` 策略生成 `direction=inbox_auto_retry`，只重试到期且未达上限的 failed 行；`GET /api/sync/health` 返回 failed inbox 对象分布、到期数量、阻塞数量、下次重试时间和 critical 告警；前端 `/sync` 展示 failed inbox 对象分布、手动重试和自动 backoff 策略；证据：`backend/tests/test_sync_feed_pull.py::test_failed_sync_inbox_retry_replays_stored_record`、`backend/tests/test_sync_feed_pull.py::test_failed_sync_inbox_auto_retry_only_replays_due_records`、`backend/tests/test_operations_api.py::test_sync_failed_inbox_retry_api_replays_record`、`backend/tests/test_operations_api.py::test_sync_health_reports_cursor_failures_lag_and_conflicts`、`frontend/src/pages/SyncRunsPage.spec.ts`、`config/contracts/sync_strategy.json` |
| 登录页 auth mode 分流与 OIDC 错误承接 | H/Identity | `frontend/src/pages/LoginPage.spec.ts` 覆盖 public password、OIDC SSO、intranet header、redirect query、must_change_password 跳 `/account` 和 `auth_error` 文案；OIDC 按钮跳转 `/api/auth/oidc/start?next=...` |
| OIDC start/callback 错误安全回跳 | H/Identity | `backend/tests/test_auth.py` 覆盖未配置、provider error、state mismatch、token exchange 失败和 claims 解析失败回跳 `/login?auth_error=...` |
| `/users` 权限入口、邀请状态、自动开通规则、权限审计摘要、成员影响提示、部门映射编辑、反馈策略编辑、权限 diff 与回滚 | H/Identity | `backend/tests/test_auth.py::test_permission_changes_explain_and_rollback_roles_membership_and_policy` 覆盖角色、成员和反馈策略 diff/rollback；`frontend/src/pages/UsersPage.spec.ts` 覆盖 `super_admin` 四块入口、非 `super_admin` 权限收敛、邀请 pending/accepted/revoked/expired 状态、部署层自动开通规则、当前工作台部门映射编辑、权限审计摘要、反馈策略影响确认保存、成员角色影响提示、最后 owner 禁用态、owner 危险变更确认和回滚选中变更 |
| `/audit-logs` 工作台审计 v1 | H/Audit Ops | `audit_logs.workspace_code` 和 `config/contracts/audit_ops.json` 固化字段/API；`backend/tests/test_operations_api.py::test_audit_logs_are_workspace_scoped_for_workspace_admin` 覆盖 workspace admin scoped 查询、viewer 403 和全局 super_admin 查询；`frontend/src/pages/AuditLogsPage.spec.ts` 覆盖当前工作台请求、空态和错误态 |
| secret-like 统一拦截/脱敏 v1 | H/Security | `backend/app/core/privacy.py` 统一定义 secret-like key 检测和 `[REDACTED]` 脱敏；sync feed、手工同步包导出、sync apply/import 复用同一规则，含 `token/secret/password/cookie/authorization/api_key/.env/client_secret/session` 的 payload 不进入 feed/package 或业务表；`write_audit` 统一脱敏 `detail_json`；证据：`backend/tests/test_operations_api.py::test_audit_details_redact_secret_like_values`、`backend/tests/test_operations_api.py::test_sync_package_export_download_and_import_are_auditable`、`config/contracts/audit_ops.json`、`config/contracts/sync_strategy.json` |
| 工作台 feedback_policy 薄片 | H/Workspace/Collaboration | `config/contracts/workspace_model.json`、`backend/tests/test_workspaces_api.py`、`backend/tests/test_account_lifecycle.py`、`frontend/src/pages/DailyReportsPage.spec.ts` 和 `frontend/src/pages/UsersPage.spec.ts` 覆盖策略读写、viewer 后端权限、日报反馈入口禁用、`/users` 可视化编辑和影响确认 |
| 公司 SQL 导出 preflight | F/Export | `POST /api/exports/company-sql/daily-reports/{id}/preflight` 只读返回 report/item errors 与 warnings；direct export 复用 preflight，失败不写 `export_jobs`；证据：`backend/tests/test_company_sql_export.py`、`frontend/src/pages/ExportsPage.spec.ts`、`config/contracts/news_sql_mapping.json` |
| 公司 SQL 导出流式下载与大文件预览 v1 | F/Export | `GET /api/exports/{id}/download` 从 `export_jobs.result_json.sql_text` 以 `server_streaming` 返回 `text/sql` 附件和文件大小 header；workspace admin/super_admin 可下载，workspace viewer 403；生成响应返回 `sql_text_bytes/sql_text_preview_bytes/sql_text_truncated/download_url/download_filename`，前端截断预览禁用复制并引导服务端下载；证据：`backend/tests/test_company_sql_export.py::test_company_sql_export_download_requires_workspace_admin`、`backend/tests/test_company_sql_export.py::test_company_sql_export_response_truncates_large_inline_preview`、`frontend/src/pages/ExportsPage.spec.ts`、`config/contracts/news_sql_mapping.json` |
| 公司 SQL trace 字段来源与差异预览 v1 | F/Export | `GET /api/exports/{id}/trace` 返回每条 SQL 的 `sql_excerpt`、导出标题、字段来源、编辑覆盖字段和 `field_diffs`；前端 trace 行展示 SQL 片段、标题/摘要/关键点来源、五段正文来源，以及导出/编辑/生成/raw 来源预览，能区分日报编辑覆盖和生成稿；字段值只返回预览，不返回 `raw_payload_json`；证据：`backend/tests/test_company_sql_export.py::test_company_sql_export_trace_preserves_source_lineage`、`frontend/src/pages/ExportsPage.spec.ts`、`config/contracts/news_sql_mapping.json` |
| 公司 SQL 内网导入回执与 importer 回调 v1 | F/Export | `GET/POST /api/exports/{id}/import-receipts` 记录 `pending/imported/failed/partial`、目标系统、导入/失败语句数、失败 SQL 序号/表、错误码和错误原因；失败项可映射回 `export_job_items`，回执 `sync_policy=local_only`；`POST /api/exports/{id}/import-receipts/callback` 走 `SYNC_SERVICE_TOKENS` Bearer 鉴权，不走用户 cookie；前端 `/exports` 可查看最新状态、登记回执并展示回调 endpoint；证据：`backend/tests/test_company_sql_export.py::test_company_sql_import_receipt_records_intranet_feedback_with_viewer_read_gate`、`backend/tests/test_company_sql_export.py::test_company_sql_import_receipt_callback_uses_service_token_without_cookie_or_csrf`、`frontend/src/pages/ExportsPage.spec.ts`、`config/contracts/news_sql_mapping.json` |
| 公司 SQL batch manifest v1 | F/Export | `POST /api/exports/company-sql/daily-reports/batch` 限定单 workspace，逐日运行 preflight，成功日创建独立 `company_sql` export job，失败日只进入 batch manifest；前端可勾选多份已发布日报并展示成功/失败、SQL 总大小、逐日错误和成功日下载入口；证据：`backend/tests/test_company_sql_export.py::test_company_sql_batch_export_returns_manifest_and_per_day_results`、`frontend/src/pages/ExportsPage.spec.ts`、`config/contracts/news_sql_mapping.json` |
| requirement source links v1 | G/Strategy Loop | `POST /api/requirements` 支持来源快捷字段，`POST /api/requirements/{id}/source-links` 可追加证据，`GET /api/requirements` 返回 source links；后端从 daily/weekly report item 派生 news/raw 并拒绝跨工作台或冲突 ID，前端 `/requirements` 展示真实来源追溯；证据：`backend/tests/test_operations_api.py::test_requirement_source_links_trace_daily_item_to_external_signal`、`frontend/src/pages/RequirementsPage.spec.ts`、`config/contracts/strategic_loop.json` |
| insight/implication management v1 | G/Strategy Loop | `GET/POST/PATCH /api/insights` 和 `GET/POST/PATCH /api/strategic-implications` 支持独立列表、创建、编辑、确认/归档和来源追溯；`/insights` 页面展示 source title、source URL、data source 和战略影响；证据：`backend/tests/test_operations_api.py::test_insights_and_implications_have_independent_management_api`、`frontend/src/pages/InsightsPage.spec.ts`、`config/contracts/strategic_loop.json` |
| report item strategy loop v1 | G/Strategy Loop | `POST /api/daily-report-items/{id}/insights`、`POST /api/weekly-report-items/{id}/insights` 可创建 insight、implication、requirement 和可选 task；任务列表返回 requirement/source links；日报/周报页有管理员“沉淀需求”入口；证据：`backend/tests/test_operations_api.py::test_report_items_create_strategy_loop_with_requirement_and_task_trace`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/strategic_loop.json` |
| report item entity milestone v1 | G/Archive Knowledge | `POST /api/daily-report-items/{id}/entity-milestones`、`POST /api/weekly-report-items/{id}/entity-milestones` 可从当前报告条目登记实体事件；同一条目+实体幂等更新，metadata 保留 current refs；日报/周报页 member 可输入实体名登记；证据：`backend/tests/test_operations_api.py::test_report_items_create_entity_milestones_with_source_trace`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`docs/backend/archive-knowledge-design.md` |
| entity milestone governance v1 | G/Archive Knowledge | `PATCH /api/entity-milestones/{id}` 仅允许治理 `legacy_system=current` 事件；支持编辑、确认、撤销，旧导入事件不可编辑；`requirement_source_links.entity_milestone_id` 和 `source_entity_milestone_id` 保留实体事件到需求的来源追溯；证据：`backend/tests/test_operations_api.py::test_report_items_create_entity_milestones_with_source_trace`、`frontend/src/pages/EntityMilestonesPage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`config/contracts/archive_knowledge.json`、`config/contracts/strategic_loop.json` |
| historical report requirement link v1 | G/Archive Knowledge/Strategy Loop | `requirement_source_links.historical_report_id` 与 `source_historical_report_id` 保留旧报告到需求的来源追溯；`/historical-reports` 可从详情创建需求，`/requirements` 和 `/tasks` 可回跳 `/historical-reports?id=...`；证据：`backend/tests/test_operations_api.py::test_requirement_source_links_trace_historical_report`、`frontend/src/pages/HistoricalReportsPage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/strategic_loop.json` |
| historical feedback requirement link v1 | G/Archive Knowledge/Strategy Loop | `requirement_source_links.historical_feedback_item_id` 与 `source_historical_feedback_item_id` 保留旧反馈/质量反馈到需求的来源追溯；`/quality-archive` 可从历史反馈创建需求，`/requirements` 和 `/tasks` 可回跳 `/quality-archive?feedback_id=...`；证据：`backend/tests/test_operations_api.py::test_requirement_source_links_trace_historical_feedback`、`frontend/src/pages/QualityArchivePage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/archive_knowledge.json`、`config/contracts/strategic_loop.json` |
| task owner view v1 | G/Strategy Loop | `GET /api/topic-tasks` 支持 `assigned_to_me`、`assignee_user_id`、`due=overdue|due_today` 和 `status=blocked`；任务响应返回 `is_overdue` 与 `blocked_reason`；被指派人只能更新状态和 `metadata_json.blocked_reason`；`/tasks` 有全部/我的/逾期/阻塞视图和阻塞原因提交；证据：`backend/tests/test_operations_api.py::test_topic_task_owner_view_overdue_and_blocked_filters`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/strategic_loop.json` |
| task batch update v1 | G/Strategy Loop | `POST /api/topic-tasks/batch` 只允许批量更新 `status/blocked_reason`；workspace admin 可处理当前工作台任务，被指派人只能处理自己名下任务；`/tasks` 有可更新任务选择、批量状态和阻塞原因提交；证据：`backend/tests/test_operations_api.py::test_topic_task_batch_update_status_and_blocked_reason_permissions`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/strategic_loop.json` |
| task detail v1 | G/Strategy Loop | `GET /api/topic-tasks/{id}` 返回 `TopicTaskRead`、requirement、assignee、`is_overdue`、`blocked_reason` 和 `requirement_source_links`；workspace viewer 可读、非成员 403；`/tasks` 详情抽屉调用详情 API 并展示 task -> requirement -> source links；证据：`backend/tests/test_operations_api.py::test_topic_task_detail_exposes_requirement_source_trace_with_viewer_gate`、`frontend/src/pages/TopicTasksPage.spec.ts`、`config/contracts/strategic_loop.json` |
| Strategy Loop sync boundary v1 | G/F | extranet feed manifest 不包含 `requirements/topic_tasks`，直接请求这些 object_type 返回 400；即使内部需求/任务行被误设为 `public_to_intranet` 也不会出现在 feed；证据：`backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_strategy_loop_private_objects`、`config/contracts/sync_strategy.json`、`config/contracts/strategic_loop.json` |
| requirement feedback to recommendation v1 | G/C | requirement 结论通过 `metadata_json.recommendation_feedback` 或状态映射写入 `EditorialAction(requirement.feedback_to_recommendation)`；推荐 run 读取该 action 进入 `feedback_score` 并追加 `requirement_feedback_positive/negative` 原因；`/requirements` 有反哺控件；证据：`backend/tests/test_operations_api.py::test_requirement_conclusion_writes_recommendation_feedback`、`backend/tests/test_recommendations.py::test_requirement_feedback_enters_recommendation_feedback_score`、`frontend/src/pages/RequirementsPage.spec.ts`、`config/contracts/strategic_loop.json` |
| 评分策略只读运营摘要 v1 | C | `GET /api/recommendation/scorer-policy` 返回 content scorer 配置版本、阈值、日报/周报准入层、权重 TopN、主题 TopN、source tier/channel 摘要和噪声规则摘要；`/recommendations` 展示策略卡，前端不本地硬编码评分规则；证据：`backend/tests/test_recommendations.py::test_scorer_policy_api_exposes_operational_summary`、`frontend/src/pages/RecommendationsPage.spec.ts` |
| 评分器单条预览 v1 | C | `POST /api/recommendation/scorer-preview` 复用推荐 run 的 content admission scorer 对临时候选返回准入等级、准入分、日报可入选、噪声、拒绝原因、专家路由和分数拆解，返回 `persistence=not_persisted`，不创建 recommendation run 或日报草稿；`/recommendations` 提供管理员评分预览面板；证据：`backend/tests/test_recommendations.py::test_scorer_preview_api_scores_without_creating_recommendation_run`、`frontend/src/pages/RecommendationsPage.spec.ts`、`config/contracts/adapter_pipeline.json` |
| P2/P3 观察池复核 v1 | C/E | `GET /api/recommendation/runs/{id}` 返回 recommendation item 的最新 `daily_report` trace；`/recommendations` 从当前 run 中筛出未入选 P2/P3，调用 `POST /api/daily-reports/bulk-adopt-from-candidates` 或 `bulk-reject-from-candidates` 写入日报草稿并回显已采信/已剔除；证据：`backend/tests/test_recommendations.py::test_recommendation_run_detail_exposes_daily_report_review_trace`、`frontend/src/pages/RecommendationsPage.spec.ts`、`config/contracts/adapter_pipeline.json` |
| 前端假入口治理 | H/Search/Notifications/Contract Test | AppShell 顶部搜索已恢复为真实 `/api/search` 结果面板，不搜索页面菜单，结果按类型分组并支持键盘选择，空搜索框展示按用户/工作台隔离的本地近期结果；通知铃铛已恢复为真实未读数 API，用户胶囊进入 `/account`；今日速览已补真实 API 聚合、空态、核心 API 错误态、health/coverage 降级和 read-only 部署隐藏采集入口测试；`frontend_control_governance` v1 已自动扫描页面/壳按钮、RouterLink、占位文案和 AppShell 全局入口的 API/contract/test 证据；证据：`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/DashboardPage.spec.ts`、`scripts/validate_frontend_controls.py`、`backend/tests/test_frontend_control_governance.py`、`config/contracts/frontend_control_governance.json` |
| 全局搜索数据库查询 v1 | Search | `GET /api/search`、runtime `capabilities.search`、工作台权限过滤、数据源 link 过滤、日报条目/周报条目/数据源/导出任务/导出 trace 条目/report rendition/同步运行/同步冲突结果跳转、历史报告/实体事件/候选新闻/周报条目/导出任务/trace 条目/report rendition/同步运行/同步冲突页面锚点、搜索结果类型分组、键盘选择、本地近期结果、非成员 403 和同步运行/冲突非管理员 403 已覆盖；证据：`backend/tests/test_search_api.py`、`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/HistoricalReportsPage.spec.ts`、`frontend/src/pages/EntityMilestonesPage.spec.ts`、`frontend/src/pages/NewsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/ExportsPage.spec.ts`、`frontend/src/pages/SyncRunsPage.spec.ts`、`config/contracts/search.json` |
| 评论活动与站内通知最小闭环 | H/Collaboration | `activity_events`、`notifications`、`notification_preferences`、`object_watchers`、`GET /api/notifications*`、`POST /api/notifications/*/read`、`GET/PATCH /api/object-watchers`、偏好 API、`NotificationRead.target_label/target_path`、`/notifications` 页面和顶部未读数已接入；日报评论通知、日报评论提及、日报条目关注者通知、同步冲突管理员通知、失败源自动重试到期/阻塞通知、日报/周报发布通知、周报条目更新通知、周报条目关注者通知、候选采信/剔除通知、偏好过滤、日报条目级跳转、报告级跳转、周报 item 锚点、抓取 run 锚点和候选池 dedupe_group 锚点有测试覆盖；证据含 `backend/tests/test_account_lifecycle.py::test_object_watcher_receives_daily_report_comment_notifications`、`backend/tests/test_account_lifecycle.py::test_weekly_report_item_update_notifies_workspace_members_with_preference_filter`、`backend/tests/test_news_api.py::test_candidate_pool_filters_sort_and_bulk_reject_candidates`、`backend/tests/test_ingestion_runs.py::test_failed_source_auto_retry_emits_due_alert_notification`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/NewsPage.spec.ts`、`frontend/src/pages/NotificationsPage.spec.ts`、`frontend/src/pages/IngestionRunsPage.spec.ts` |
| 协作/通知 sync boundary v1 | H/F | extranet feed manifest 不包含 `comments/reactions/ratings/activity_events/notifications/notification_preferences/object_watchers`，直接请求这些 object_type 返回 400；即便 activity event 被误设为 `sync_allowed` 也不会出现在 feed；证据：`backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_local_collaboration_notifications`、`config/contracts/notifications.json`、`config/contracts/sync_strategy.json` |
| Alembic schema drift 清理 | Contract Test | 尾部迁移 `b0c1d2e3f4a5_align_schema_indexes_and_nullability.py` 对齐历史 index/nullable 漂移；`make migration-check` 已恢复为干净门禁，`alembic check` 输出 `No new upgrade operations detected.` |
| 数据源导入假成功治理 | A/Contract Test | `/sources` 导入必须先 preview，`total=0` 为警告、`created=0 updated>0` 为信息态；`frontend/src/pages/SourcesPage.spec.ts` 有回归测试 |
| 周报摘要段规则投影 v1 | D/E | 创建周报草稿和编辑周报条目后由后端刷新 `weekly_reports.summary`；rendition `summary_json` 写入 `summary_text`、`key_highlights`、`top_groups` 和 `summary_generated_by=rule_weekly_summary_v1`；Markdown/HTML 导出展示摘要和关键亮点，前端 `/weekly-reports` 显示后端摘要段；证据：`backend/tests/test_weekly_reports.py`、`backend/tests/test_report_renditions.py`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`config/contracts/report_renditions.json` |
| 候选池治理 v1 | B/E/H | `GET /api/dedupe-groups` 支持关键词、推荐状态、日报状态、准入等级、来源类型筛选和推荐分/发布时间/来源数排序；`POST /api/daily-reports/bulk-adopt-from-candidates` 将已推荐的 dedupe winner 批量加入或恢复采信到目标日报草稿；`POST /api/daily-reports/bulk-reject-from-candidates` 将已推荐候选写入或更新为 `adoption_status=0`，缺少推荐链候选会 skipped，不绕过推荐直接进日报；`/news` 支持选择候选、目标日期、批量采信/剔除、候选关注和 dedupe_group 通知锚点；证据：`backend/tests/test_news_api.py`、`frontend/src/pages/NewsPage.spec.ts`、`config/contracts/notifications.json` |
| 候选池完整 trace 复核与业务解释 v1 | B/E | `GET /api/dedupe-groups` 返回 `lineage.nodes`，以安全节点串起 data_source/raw_item/news_item/dedupe_group/recommendation/generated_news/daily_report_item；每个节点带后端生成的 `review_note` 说明复核含义；raw 只暴露 payload keys 等安全元数据，不返回完整 raw_payload_json；`/news` 展示 trace 链并支持 news/raw/dedupe query 锚点高亮；证据：`backend/tests/test_news_api.py::test_super_admin_can_normalize_and_list_news`、`frontend/src/pages/NewsPage.spec.ts`、`config/contracts/adapter_pipeline.json` |
| 工作台级调度策略 + run 级自动重试 + 调度心跳可观测 | H/E | `schedule-policy` 读写 API（取值域校验 422、审计 `workspace.schedule_policy.update`、resolved 生效值 + `next_run_at` 预览）；scheduler 60s tick per-workspace 触发，无策略工作台行为与既有单工作台调度兼容；pipeline run 重试链字段（`attempt/retry_of_run_id/next_retry_at`）与 backoff 自动重试（partial 不触发、不可重试 error_code 立即终止、superseded 让位、耗尽发 `ingestion.pipeline_retry_exhausted` important 通知）；`scheduler_heartbeats` 表与 `GET /api/pipeline/scheduler/status`；新 env `SCHEDULER_MISSED_WINDOW_SECONDS`；证据：`backend/tests/test_scheduler_policy.py`、`backend/tests/test_pipeline_retry.py`、`frontend/src/pages/WorkspaceSettingsPage.spec.ts`（自动化卡）、`frontend/src/pages/DashboardPage.spec.ts`（侧栏心跳卡）、`config/contracts/workspace_model.json` `schedule_policy`、`config/contracts/notifications.json` |
| LLM 生成 provider 分层配置 + 连通性自检 | D/H | `GENERATION_*` env 族与 `MINIMAX_*` 逐字段兼容回退；三条启动 fail-fast 规则落 `backend/app/core/deploy_checks.py`（契约已迁入 `startup_failfast_rules`）；`generation_policy` 读写（resolved provider/model/key_configured 永不回显 key、secret-like 422、审计 `workspace.generation_policy.update`）；`POST /api/generation/ping` 分类报错；`daily_generation_budget` 与 `fallback_behavior=fail` 语义；证据：`backend/tests/test_generation_provider.py`、`frontend/src/pages/WorkspaceSettingsPage.spec.ts`（生成模型卡）、`config/contracts/workspace_model.json` `generation_policy`、`config/contracts/deployment_modes.json` `startup_failfast_rules`。注：2026-07-08 决策变更 D-2026-07-08-KEY 在此基线上追加 provider 预设目录 + 密钥加密落库（§4.4，01-implementation-plan §18 WP4-B），env 链保持兼容 |
| 模板驱动生成 generation_template（JSON/XML 载体，后端全链路） | D/E | `report_formats.generation_template(+_source)` 列与迁移；JSON/XML 无 DTD/外部实体解析到规范形；投影优先/增量字段追加生成判定；`POST /api/report-formats/validate-template` 干跑校验+示例预览；增量字段写 `generated_news.template_extras_json`；rendition/MD/HTML 按模板投影；`template_fallback` 降级与 `regenerate` 补齐；weekly 同机制；公司 SQL 任意模板配置下逐字节不变（负向断言有用例）；证据：`backend/tests/test_generation_template.py`、`config/contracts/report_renditions.json` `generation_template`。前端格式管理面板的模板上传/校验/预览 UI 未落地（见 §4.3 遗留）。注：2026-07-08 决策变更 D-2026-07-08-TPL 已把语义修订为「逐条 × 逐格式全 AI 格式化、投影只排版」，本行的投影优先实现待重对齐（§4.4，01-implementation-plan §18 WP4-C） |
| 布局模板与间距系统 + Dashboard 信息架构重排 | H | `base.css` `:root` spacing tokens 与统一页面容器；四布局模板逐页收敛；`/dashboard` 主列+固定侧栏重排（含源健康折叠态与侧栏第 6 位调度心跳卡）；证据：`frontend/src/styles/base.css`、`frontend/src/pages/layout-templates.spec.ts`、`frontend/src/pages/DashboardPage.spec.ts` |
| 统一弹窗系统（居中 Modal + 受限上下文面板） | H | `AppModal` 基座（尺寸档位/遮罩/Esc/焦点圈定/脏表单确认/移动端全屏）；建台向导、发现工作台、新增信息源、导入预览 4 处弹层迁移；单源配置与格式管理正式化为上下文面板；`scripts/validate_frontend_controls.py` 按 `modal_rule` 扩展扫描（config-panel 只剩白名单 2 处）；证据：`frontend/src/components/AppModal.spec.ts`、`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/SourcesPage.spec.ts`、`config/contracts/frontend_control_governance.json` `modal_rule` |
| 账号资料自助编辑（PATCH /api/auth/me） | H | 本地账号 display_name/department/email 可改并审计 `auth.profile.update` before/after 快照；外部身份 400、游客 403、must_change_password 白名单不变；`/account` 资料卡（本地可编辑、外部只读说明、保存后刷新胶囊）；证据：`backend/tests/test_auth.py`、`frontend/src/pages/AccountPage.spec.ts`、`config/contracts/auth_modes.json` `profile_self_service` |
| 发现搜索 + 工作台加入码 + 公开形态矩阵 | H | `discover?q=` 名称/描述过滤且任何关键词不泄露 private；`workspace_join_codes` 表/迁移；join-code 三端点 + `join-by-code`（幂等不降级、统一失效 400、按用户+IP 限流 429、`workspace.join_code.create/disable` 等四类审计动作）；发现工作台 Modal 搜索框与凭码加入区；`/workspace-settings`「可见性与加入码」卡；证据：`backend/tests/test_workspace_join_codes.py`、`frontend/src/components/WorkspaceDiscovery.spec.ts`、`frontend/src/pages/WorkspaceSettingsPage.spec.ts`、`config/contracts/workspace_model.json` `join_code`/`discovery_and_subscription` |

### 4.2 待补差距（按优先级）

| 级 | 差距 | 所属块 | 判定标准 |
|---|---|---|---|
| P0 | 生产库执行 Tech 历史资产全量导入验收 | G | 本地隔离 PostgreSQL 全量证据已通过；生产库仍需 `--check-only` 覆盖率对齐冻结基线，`validate_tech_import_acceptance.py` 通过，缺口清零或用 accepted-gaps JSON 归档 |
| P0 | OIDC 真实 provider 证据 | H/Identity | claims 映射、自动 membership、redirect 和 provider/callback 错误承接已有测试；后续补真实 provider 登录/建号/membership/登出证据 |
| P0 | 生产备份恢复演练证据 | H/Ops | 用生产同构数据执行备份、恢复、healthz、核心查询和回滚记录，输出验收报告 |
| P1 | 通知模块深化与跨对象协作 | H/Collaboration | 日报评论 activity event、日报评论 @ 提及 important notification、日报/周报条目关注者通知、同步冲突管理员通知、失败源自动重试到期/阻塞通知、日报/周报发布通知、周报条目更新通知、任务指派通知、需求状态通知、消息页、顶部未读入口、后端 target_path、日报条目级跳转、评论高亮、报告级跳转、周报 item 锚点、同步冲突锚点、抓取 run 锚点、任务锚点、需求锚点、归档筛选、站内偏好和协作/通知 sync boundary 负向测试已完成；后续补邮件投递和更多对象通知生成/提及 |
| P1 | 同步实机联动证据和生产监控告警 | F | role capability、open conflicts 查询、`keep_local/ignored/retry_after_dependency/use_incoming/manual_merge` 处置 API、failed inbox 本地重放与自动 backoff、`GET /api/sync/health` 水位/failed inbox/失败 run 告警和 `/sync` UI 已落地；后续留存 extranet->intranet 端到端实机同步证据，并补告警投递/runbook |
| P1 | wechat 采集实机验收与 wx 桥可选增强 | A | `wechat` adapter 已落地（rsshub 主路径 + article_urls）；对 31 个待补公众号源完成实机抓取或明确豁免，wx 桥 sidecar 为可选增强 |
| P1 | 深度历史补采（归档页/sitemap 深挖） | A | 指定历史日期可恢复候选 |
| P1 | LLM 周报摘要模型生成 | D | 当前规则投影 v1 已产出板块分布+亮点；后续模型摘要必须复用既有 `summary_json` 字段并可被质量验收 |
| P1 | 流水线计算移出事件循环 | E | 导入期间 API P99 不劣化 |
| P1 | 前端关键旅程 E2E 和假控件治理深化 | Contract Test | 假控件扫描 v1、`/setup` router guard v1 和 Playwright 脚手架（配置 + API 打桩 smoke）已完成；后续补登录、导入预览、抓取、日报、同步、导出的真实后端 Playwright 旅程，并把更多页面级业务入口映射到后端能力或禁显规则 |
| P2 | 评分器策略编辑/批量重算与观察池运营深化 | C | 只读策略摘要 v1、单条 scorer preview v1 和 P2/P3 观察池复核 v1 已完成；后续管理员可预览配置变更影响、重算候选，并补观察池排序策略、复核备注和抽检队列 |
| P2 | 候选池跨页联动、覆盖趋势深化、外部告警通道 | A/E/H | 候选池筛选排序、批量采信、批量剔除、候选关注、通知锚点和完整 trace 复核 v1 已完成；失败源手动重试 v1、自动重试队列 v1、近 14 日覆盖趋势、Top 失败源聚合和站内告警投递 v1 已完成；后续增强跨页联动体验、邮件/外部告警通道和更长周期趋势分析 |
| P2 | 全局搜索深化 | Search | 顶部搜索 v1 已恢复，类型分组、键盘选择、本地近期结果、周报 item、export item、report rendition、sync run 锚点和 intranet 禁采集对象专项测试已补；后续补索引表和 Playwright E2E |
| P2 | 快报 PPT 插件 / 更多 domain pack 样例 | D/H | 不改主链路扩展新输出或新板块 |

### 4.3 2026-07-07 设计轮实施收口（2026-07-08）

2026-07-07 设计轮（自动化/生成轨道 + 体验系统轨道）的七项能力已于 2026-07-08
第三轮实施（`docs/implementation/01-implementation-plan.md` §17 WP3-A…H）全部落地，
对应行已移入 §4.1；契约状态位（`workspace_model.json` `schedule_policy`/
`generation_policy`/`join_code`、`auth_modes.json` `profile_self_service`、
`report_renditions.json` `generation_template`、`deployment_modes.json`
`startup_failfast_rules`、`notifications.json` `implemented_event_types_v1`、
`frontend_control_governance.json` `modal_rule`）已同步为实现事实。

本轮遗留（未实现，如实保留）：

- 格式管理面板的模板上传/校验/预览 UI：后端 `validate-template` API 与
  `report-formats` 模板读写已就绪，前端 `/reports` 格式管理面板尚未接入
  模板上传入口。
- `/ingestion-runs` 调度卡升级：读 `GET /api/pipeline/scheduler/status` 的
  心跳/离线态渲染已落 `/dashboard` 侧栏第 6 位心跳卡，抓取页调度卡仍读
  `GET /api/ingestion/scheduler` 旧摘要，未升级为心跳视图。

### 4.4 2026-07-08 第四轮设计定稿（待实现）

四轨设计 + 交叉评审已按实现级规格定稿，实施拆包见
`docs/implementation/01-implementation-plan.md` §18（WP4-A…WP4-F）；实现落地时
把下表行移入 §4.1 并迁移契约状态位。

| 能力 | 块 | 事实源 / 契约 | 实施包 |
|---|---|---|---|
| AI 推荐三层管线（规则粗排保留 + 可选语义层 + LLM listwise 精排）、内容导向 rubric 编译与版本化、`final_score` 融合、预算分桶（`generation_daily_usage.purpose`）、反馈周期再估计 | C | `docs/backend/recommendation-scoring-design.md`、`docs/backend/feedback-heat-scoring.md` §10；`config/contracts/recommendation_ranking.json`（`design_final_pending_implementation`） | WP4-A |
| Provider 预设目录（9 家 + custom 兜底）+ 密钥 Fernet 加密落库 `llm_provider_credentials`（决策变更 D-2026-07-08-KEY）+ 生成模型卡完整配置流 | D/H | `docs/backend/generation-provider-design.md` §8-§10；`config/contracts/llm_providers.json`（designed 待实现） | WP4-B |
| 逐条 × 逐格式模板 AI 格式化（决策变更 D-2026-07-08-TPL，推翻投影优先）、投影只排版、预算公式 | D/E | `docs/backend/reports-editorial-design.md` §8.1、`docs/backend/report-renditions-design.md` §10（§10.7 修订断言）；`config/contracts/report_renditions.json` `generation_template` | WP4-C |
| 报告页 ReportTimeline 时间轴 + 顶部筛选条 + 详情区 spacing 修正 | H | `docs/product/frontend-product-design.md` §13、page-specs §10/§12、`docs/backend/archive-knowledge-design.md` §5.1 | WP4-D |
| 排序一致性（头条候选今日集合 `final_score` 降序、候选池默认 `score_desc`）+ 空指标隐藏 + 界面文案审计看护 | C/H/Contract Test | `config/contracts/recommendation_ranking.json` `ordering_consistency`、`config/contracts/frontend_control_governance.json` `copy_audit_rule`、产品设计 §14 | WP4-E |
| `/historical-reports` 重定位为跨来源归档（深链跳报告页、月份导航收敛 legacy） | G/H | 产品设计 §13.4、page-specs §13、archive-knowledge-design §5.1 | WP4-F |

## 5. 能力块 ↔ 专题文档映射

| 块 | 契约 | 专题文档 |
|---|---|---|
| A | source_fields / adapter_pipeline / workspace_model | `docs/backend/data-ingestion-flow-storage-design.md`、`docs/backend/ingestion-adapter-dedup-spec.md`、`docs/backend/workspace-module-model.md`、`docs/backend/tech-insight-loop-fusion-plan.md` |
| B | adapter_pipeline / label_model | `docs/backend/data-ingestion-flow-storage-design.md`、`docs/backend/data-lineage-and-storage.md`、`docs/backend/ingestion-adapter-dedup-spec.md` |
| C | —（评分配置即契约） | `docs/backend/recommendation-scoring-design.md`、`docs/backend/feedback-heat-scoring.md`、`docs/backend/tech-insight-loop-fusion-plan.md` |
| D | report_renditions | `docs/backend/reports-editorial-design.md`、`docs/backend/report-renditions-design.md`、`docs/backend/pipeline-jobs-design.md` |
| E | label_model / workspace_model | `docs/backend/reports-editorial-design.md`、`docs/backend/workspace-configuration-design.md`、`docs/implementation/api-and-ui-implementation.md` |
| F | news_sql_mapping / sync_strategy | `docs/backend/export-compliance-design.md`、`docs/backend/sync-conflict-distribution-design.md`、`docs/backend/data-format-mapping.md`、`docs/deployment/multi-environment-sync.md` |
| G | archive_knowledge / tech_insight_loop_legacy_import / strategic_loop | `docs/backend/archive-knowledge-design.md`、`docs/backend/strategy-loop-design.md`、`docs/backend/tech-insight-loop-fusion-plan.md`、`docs/architecture/strategic-intelligence-platform.md` |
| H | workspace_model / auth_modes / notifications / audit_ops / extension_points / deployment_modes | `docs/backend/workspace-configuration-design.md`、`docs/backend/pipeline-jobs-design.md`、`docs/backend/workspace-module-model.md`、`docs/backend/identity-access-design.md`、`docs/backend/collaboration-notification-design.md`、`docs/backend/security-secrets-privacy-design.md`、`docs/backend/extension-governance-design.md`、`docs/backend/audit-ops-observability-design.md`、`docs/backend/search-design.md`、`docs/backend/contract-test-governance-design.md`、`docs/deployment/auth-unified-login.md`、`docs/deployment/deployment-topology.md`、`docs/deployment/deployment-ops.md`、`docs/implementation/api-and-ui-implementation.md` §3.1 |
