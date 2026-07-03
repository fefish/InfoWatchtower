# InfoWatchtower 能力地图与目标态架构

状态：2026-07-02 按目标态刷新。本文回答三件事：系统有哪些能力分块、每块能力分布在哪
（后端/前端/数据/配置）、距离目标态还差什么。字段与流程契约仍以
`docs/00-system-design.md`（总纲）和 `config/contracts/*.json` 为准。

## 1. 目标态一句话

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

硬边界（全局不变式，见 AGENTS.md）：raw 原始报文永不覆盖；去重在 news 之后推荐之前；
`adoption_status` 只属于采信层；公司 SQL 只导出已发布日报中 `adoption_status=2` 且
MiniMax ready 的条目、category 十分类、`content_json` 五段；业务板块只存
`insight_json`，永不写 category；rendition 是投影不是副本。

## 3. 能力分块与分布架构

### A. 信息源与采集

| 层 | 位置 |
|---|---|
| 后端 | `app/ingestion/`（runs/fetch/jobs/source_seeds）、`app/adapters/`（rss/page/base 浏览器 UA） |
| API | `POST/PATCH /api/sources*`（自建/补入口/工作台链接）、`/api/ingestion/runs`（并发/超时/`max_items_per_source`）、`/api/ingestion/backfill-runs`、`/api/ingestion/coverage` |
| 前端 | `/sources`（信息流源列表+标签策略+自建源）、`/ingestion-runs`（抓取与覆盖、目标日漏斗） |
| 数据 | `data_sources`（共享池）、`workspace_source_links`（工作台启用/权重/日限）、`ingestion_runs` |
| 配置 | `config/seeds/`（旧种子 294 + Tech 386）、`contracts/source_fields.json`、`taxonomy/source_tags.json` |

现状：✅ 663 治理记录去重成共享池；自建源/补入口界面化；浏览器 UA 对齐旧系统；单源上限
参数化；覆盖率漏斗可解释"为什么当天候选少"。
**Gap**：① 31 个 `wx://` 公众号源无 adapter（P1，需微信渠道方案）② 失败源自动重试与
告警（P2）③ 超出 RSS 窗口的深度历史补采（归档页分页/sitemap 深挖，P1）④ scheduler
默认窗口/上限参数化到生产 env（P1，一次配置动作）。

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
| API | `POST/GET /api/recommendation/runs` |
| 前端 | `/recommendations`（分数拆解）、`/news` 与今日速览的准入徽章 |
| 数据 | `recommendation_runs/items`（admission_level/pool、noise_types、scorer_breakdown、expert_routes） |
| 配置 | `config/scoring/content_scorer_v2.json`（阈值/权重/噪声规则/专家路由） |

现状：✅ P0-P3/R 准入、噪声降权、技术情报优先策略稳定输出（0-100 分口径）。
**Gap**：评分器运营页（配置查看/校验/预览/重算，旧系统质量闭环的实时化，P2）；
P2/P3 观察池的复核工作流（P2）。

### D. 生成与成稿（一次采信，多版成稿）

| 层 | 位置 |
|---|---|
| 后端 | `app/llm/`（MiniMax 五段+category+insight prompt v2）、`app/reports/renditions.py`（格式注册/投影/MD）、`app/reports/rendition_html.py` |
| API | `GET/POST/PATCH/DELETE /api/report-formats`、`/api/{daily,weekly}-reports/{id}/renditions/{format}/regenerate|export` |
| 前端 | 日报/周报页成稿 tab（默认技术洞察版）、格式管理滑出面板、MD/HTML 导出 |
| 数据 | `generated_news`（content_json 五段 + `insight_json` 板块/要点/总结/标签行）、`report_formats`（company_sql_v1 locked + tech_insight_v1 + 自定义）、`report_renditions` |
| 配置 | `taxonomy/business_boards.json`（14 板块，辅助维度）、`contracts/report_renditions.json` |

现状：✅ P1-P4 已实施：双内置格式、头条自动 Top6+可调、板块分组、MD/HTML 导出对齐快报
样式、自定义格式注册表、周报双版；未配 MiniMax key 时 insight 走规则降级并标注；
`scripts/validate_minimax_generation_acceptance.py` 已提供真实 key 结构验收和 fixture pytest。
真实 MiniMax 验收已通过并归档到 `outputs/minimax/minimax_generation_acceptance.json`；
validator 会拒绝来源未给出的百分比、P95/P99、倍数、延迟/显存数值，避免模型成稿编造指标。
**Gap**：① 模型版 insight/成稿在真实生产日报流水线中持续抽检（P0 运维动作）
② 周报开头摘要段（板块分布/关键亮点）的模型生成（P1）③ 快报 PPT 导出（旧系统能力，
可选插件，P2）。

### E. 编审与发布

| 层 | 位置 |
|---|---|
| 后端 | `app/api/routes/reports.py`、`app/pipeline/daily.py`、`app/reports/weekly.py` |
| API | 日报/周报 CRUD、publish、条目采信/编辑/头条、`regenerate-generated-news`、点赞/评分/评论 |
| 前端 | `/daily-reports`（成品优先，内网版=编审 tab）、`/weekly-reports`、`/news` 采信状态 |
| 数据 | `daily_reports/items`（is_headline）、`weekly_reports/items`、feedback 表族 |

现状：✅ 自动生成草稿→成品直读→编审微调的心智对齐快报；scheduler 打开即每日自动跑。
**Gap**：① 候选池批量采信/筛选（P2）② 编辑器体验（富文本/差异对比，P2）③ 流水线重
计算移出事件循环（已建后台任务卡片，P1 技术债）。

### F. 分发与集成

| 层 | 位置 |
|---|---|
| 后端 | `app/exports/company_sql.py`、`app/sync/` |
| API | `/api/exports*`（含 trace）、`/api/sync*`（包导出/下载/导入幂等） |
| 前端 | `/exports`、`/sync` |
| 数据 | `export_jobs/items`、`sync_outbox/inbox/runs` |
| 校验 | `scripts/validate_company_sql.py`（0505 基准） |

现状：✅ 4 表合同+逐字段校验+语句级追溯；同步包可导出/下载/导入，`data_sources/raw_items/news_items`
已按 `object_global_id/global_id` 幂等 apply，revision/hash 冲突写 `sync_conflicts`。
**Gap**：① 更多同步 object_type 与冲突解决 UI（P1）② 导出前字段长度/URL/HTML 污染校验摘要（P1）
③ 生产备份恢复演练（P0 运维）。

### G. 资料库与知识沉淀

| 层 | 位置 |
|---|---|
| 后端 | `app/ingestion/tech_insight_loop_legacy.py`、`scripts/tech_insight_loop_*.py`（inventory/dry-run/import/verify） |
| API | `/api/historical-reports*`、`/api/tracked-entities`、`/api/entity-milestones*`、`/api/quality-archive*`、`/api/legacy-import/*` |
| 前端 | `/historical-reports`（含导入验收面板）、`/entity-milestones`、`/quality-archive` |
| 数据 | `historical_reports`、`tracked_entities/entity_milestones`、`historical_feedback_items/historical_job_runs`、`insights/requirements/topic_tasks` |

现状：✅ 旧库 14834 素材/66 报告/275 大事记的导入脚本、只读页、验收摘要、引用缺口全链
就绪（默认 no-write）；`scripts/validate_tech_import_acceptance.py` 可对生产 `--check-only`
报告做机器验收，覆盖率、只读边界和已归档缺口不满足时直接失败。本地隔离 PostgreSQL 全量导入
证据已归档到 `outputs/tech_insight_loop/postgres_full_import_20260703T050653Z/`，7 项覆盖率 complete，
30 个旧库断链引用已通过 `tech_insight_loop_import_accepted_gaps.json` 归档；旧 PDF/二进制文本中的
NUL byte 会转义为 `\u0000` 标记并写入 `legacy_import.nul_sanitized_fields` 审计。
**Gap**：① 生产主库执行同一套全量导入验收（P0，一条命令级动作+机器验收+缺口人工复核）② 从新日报/周报持
续沉淀实体大事记（编辑入口，P1）③ insight→requirement→task 与外部信号的完整追溯闭环
（P1）。

### H. 平台底座

| 层 | 位置 |
|---|---|
| 工作台模型 | `app/models/workspace.py` + `POST /api/workspaces`（自助建台：核心分区/标签策略/格式/成员自动配齐）+ 分组导航（today/collect/curate/library/collab/system） |
| 身份与审计 | `app/auth/`（public_password/intranet_header）、RBAC 四角色、`audit_logs` |
| 调度 | `app/workers/`（RQ worker + scheduler，`INGESTION_SCHEDULER_*` env） |
| 部署 | `deploy/docker-compose.{local,prod}.yml`（PG+Redis+API+worker+scheduler+Caddy） |
| 设计系统 | Apple Liquid Glass（`base.css` :root token + 唯一主题层）、晨报式今日速览、≤1120px 图标栏响应式 |

现状：✅ 工作台模型、导航/分区/格式数据库驱动；✅ 登录限流、邀请建号、改密/重置、会话密钥自检、OIDC Protocol 预留和主要业务 API membership gate 已落地。
**Gap**：① 真实备份恢复演练和首次运行 Setup（P0/WP3）② membership 管理界面（P1/WP2）③ 长期覆盖趋势与异常告警（P2）④ 硬件/半导体 domain pack 样例（P2，证明扩展性）。

## 4. 差距汇总（按优先级）

| 级 | 差距 | 所属块 | 判定标准 |
|---|---|---|---|
| P0 | 生产库执行 Tech 历史资产全量导入验收 | G | 本地隔离 PostgreSQL 全量证据已通过；生产库仍需 `--check-only` 覆盖率对齐冻结基线，`validate_tech_import_acceptance.py` 通过，缺口清零或用 accepted-gaps JSON 归档 |
| P1 | 更多同步 object_type 与冲突解决 UI | F | `data_sources/raw_items/news_items` 已落业务表；后续扩展 generated_news/report 等对象并提供人工冲突处理 |
| P0 | 备份恢复演练 + 首次运行 Setup | H/F | 演练记录入 docs/deployment-ops.md；干净环境首访可创建首个管理员 |
| P0 | MiniMax key 配置后模型版 insight/成稿验收 | D | ✅ `validate_minimax_generation_acceptance.py` live 通过，技术洞察版结构、五段 content_json、短关键词和无编造数值门禁已归档；后续保留生产日报抽检 |
| P1 | wx:// 公众号 adapter 或替代入口 | A | 31 个待补源可抓取或明确豁免 |
| P1 | 深度历史补采（归档页/sitemap 深挖） | A | 指定历史日期可恢复候选 |
| P1 | 周报摘要段模型生成 | D | 周报 rendition 头部自动产出板块分布+亮点 |
| P1 | 实体大事记从新报告持续沉淀 | G | 采信条目可一键登记实体事件并追溯 |
| P1 | membership 管理界面 | H | 工作台 admin/owner 可增删成员且不依赖 super_admin |
| P1 | 流水线计算移出事件循环 | E | 导入期间 API P99 不劣化 |
| P2 | 评分器运营页 / 观察池复核 | C | 管理员可解释"谁被拒、为什么" |
| P2 | 候选池批量操作、失败源重试告警、覆盖趋势 | A/E/H | 页面可批量采信；失败源有重试记录 |
| P2 | domain pack 样例（硬件/半导体）、快报 PPT 插件 | H/D | 不改主链路完成一个新板块端到端 |

## 5. 能力块 ↔ 专题文档映射

| 块 | 契约 | 专题文档 |
|---|---|---|
| A | source_fields / adapter_pipeline / workspace_model | ingestion-adapter-dedup-spec.md、workspace-module-model.md、tech-insight-loop-fusion-plan.md |
| B | adapter_pipeline / label_model | ingestion-adapter-dedup-spec.md、data-lineage-and-storage.md |
| C | —（评分配置即契约） | feedback-heat-scoring.md、tech-insight-loop-fusion-plan.md |
| D | report_renditions | report-renditions-design.md |
| E | label_model / workspace_model | api-and-ui-implementation.md |
| F | news_sql_mapping / sync_strategy | data-format-mapping.md、multi-environment-sync.md |
| G | tech_insight_loop_legacy_import / strategic_loop | tech-insight-loop-fusion-plan.md、strategic-intelligence-platform.md |
| H | workspace_model / auth_modes / extension_points | workspace-module-model.md、auth-unified-login.md、deployment-ops.md、api-and-ui-implementation.md §3.1 |
