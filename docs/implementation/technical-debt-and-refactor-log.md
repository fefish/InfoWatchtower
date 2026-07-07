# 技术债务与微重构台账

本文记录 AI情报官在重构过程中的技术债务、处理方案和代码证据。台账只记录会影响维护、测试、部署或后续扩展的事项，普通需求不放入本文。

本文是技术债台账，不是模块设计事实源。缺口的归属和目标态设计分别以
`docs/backend/backend-module-design.md`、对应专题文档和 `docs/architecture/capability-map.md` 为准。

## 1. 当前原则

- 不把旧系统作为运行入口，只保留字段合同、样例和历史资料。
- 不把历史资产自动进入当前推荐和公司 SQL。
- 不把数据源方向标签写入成品新闻一级分类。
- 不在前端复制后端字段规则，字段合同由后端和 `config/contracts` 维护。
- 不为了短期页面效果破坏浅色工作台和共享源池设计。

## 2. 已完成微重构

| 编号 | 问题 | 处理方式 | 代码证据 |
| --- | --- | --- | --- |
| R-001 | 数据源启用关系和源本体混在一起，后续多工作台扩展困难 | 拆分共享源池和 `workspace_source_links`，单个工作台只维护启用和权重 | `backend/app/models/workspace.py`、`backend/app/api/routes/sources.py` |
| R-002 | 抓取串行执行时，单个慢源会拖慢整批任务 | 抓取运行支持并发数和单源超时，结果仍按源写入运行摘要 | `backend/app/ingestion/runs.py`、`backend/app/core/config.py` |
| R-003 | 直接从 raw 进入推荐会导致重复和不可追溯 | 增加 `news_items` 标准化和 `dedupe_groups`，推荐只处理 winner | `backend/app/normalization/news.py`、`backend/app/api/routes/news.py` |
| R-004 | 推荐原因只有文本，不便于前端解释和后续复盘 | 新增结构化准入字段，保存分数、噪声、拒绝原因和专家路由 | `backend/app/recommendations/service.py`、`backend/app/scoring/content_scorer.py` |
| R-005 | 日报生成失败会阻塞整天草稿 | 生成服务失败时落为 fallback 草稿，并标记需要复核 | `backend/app/pipeline/daily.py`、`backend/app/llm/minimax.py` |
| R-006 | 公司 SQL 日期和字段格式容易漂移 | 固化 SQL 映射合同和校验脚本，导出前统一清洗内容和时间 | `backend/app/exports/company_sql.py`、`config/contracts/news_sql_mapping.json`、`scripts/validate_company_sql.py` |
| R-007 | 周报曾是占位页，无法管理采信项 | 周报改为从已发布日报采信项生成候选，支持板块、排序、编辑和发布 | `backend/app/reports/weekly.py`、`frontend/src/pages/WeeklyReportsPage.vue` |
| R-008 | 历史参考系统资料容易和当前主链路混用 | 历史资料进入只读归档表和归档页面，不进入当前推荐或 SQL | `backend/app/models/legacy.py`、`scripts/tech_insight_loop_legacy_import.py` |
| R-009 | SQL 导出后人工排查字段来源成本高 | 增加导出 trace API 和前端追溯入口，每条 SQL 语句可回到日报条目、生成稿、news、raw 和数据源 | `backend/app/api/routes/exports.py`、`frontend/src/pages/ExportsPage.vue` |
| R-010 | 同步页面只有运行记录，无法形成内外网交付包 | 增加同步包导出、zip 下载和导入幂等骨架，manifest 与 records 写入审计运行 | `backend/app/api/routes/operations.py`、`frontend/src/pages/SyncRunsPage.vue` |
| R-011 | 生产部署口径缺少可执行检查 | 增加生产 env 模板、部署检查脚本和 CI 检查，覆盖 compose 服务、反代、默认密钥和 docs 开关 | `deploy/env.production.example`、`scripts/check_prod_deploy.py`、`.github/workflows/ci.yml` |
| R-012 | 覆盖率门禁有了但缺少可下载报告 | CI 生成 `coverage.xml` 和 `htmlcov` 并上传 artifact，便于白盒评审取证 | `.github/workflows/ci.yml` |
| R-013 | `alembic check` 因历史 index/nullable 漂移导致 `make migration-check` 不再可信 | 新增尾部 schema 对齐迁移，统一唯一索引、推荐字段 nullable、report format/rendition mixin 索引和 tracked entity name 索引差异 | `backend/alembic/versions/b0c1d2e3f4a5_align_schema_indexes_and_nullability.py`、`make migration-check` |
| R-014 | 同步导入侧停留在 inbox 幂等记录，无法真正落业务对象 | 增加 `data_sources/raw_items/news_items/generated_news/daily_reports/weekly_reports` apply handler、revision/hash 冲突写入和人工处置入口 | `backend/app/sync/apply.py`、`backend/tests/test_sync_feed_pull.py`、`frontend/src/pages/SyncRunsPage.vue` |
| R-015 | `ModuleRoadmapPage.vue` 无路由引用、无 spec、不受 section gating，属游离死代码 | 确认全仓无 import/路由/测试引用后删除该文件（2026-07-07）；后续如需路线页，必须由 `workspace_sections` 显式启用并补 spec | `frontend/src/router/index.ts`（路由表无引用）、`docs/product/page-specs/frontend-page-specs.md` §28 |

## 3. 当前技术债务

| 编号 | 等级 | 内容 | 风险 | 计划 |
| --- | --- | --- | --- | --- |
| D-004 | P1 | 深度历史补采还依赖 RSS 当前窗口 | 老日期日报可能缺候选 | arXiv/OpenAlex/Semantic Scholar paper_api v1、manual_import CSV/SQL 上传或粘贴、后端预览、逐行校验和错误报告已补；继续增加归档页分页、sitemap 深挖、OpenReview 等更多论文 provider、复杂 SQL dialect 和大文件分片 |
| D-005 | P1 | 周报正文自动生成未实现 | 周报摘要段规则投影 v1 已完成；整篇周报长文、LLM 摘要模型和热度/反馈排序仍需后续补齐 | 在现有采信项版本基础上增加周报生成服务 |
| D-007 | P2 | 领域包样例仍偏少 | 现有 hardware 样例能证明扩展路径，但跨更多产业板块的证据不够 | 增加半导体、云基础设施或政策市场等 domain pack 样例 |
| D-009 | P1 | 生产备份恢复还缺真实演练记录 | 部署文档有流程，但没有服务器恢复证据 | 在正式环境执行一次备份、恢复和健康检查演练 |

## 4. 后续微重构计划

### 4.1 导出追溯重构

目标：让每一条 SQL 行能追到日报条目、生成稿、标准化新闻、原始 raw 和数据源。

已完成：

1. 导出历史中已保存 daily item、generated news 和 news item 映射。
2. `GET /api/exports/{export_job_id}/trace` 已返回 SQL 语句到 raw/source 的链路。
3. 前端 SQL 导出页已增加“查看追溯”。
4. 已增加导出追溯测试。

后续可选：校验脚本输出字段来源摘要。

### 4.2 同步包重构

目标：把公网到内网同步从人工 SQL 文件转为可审计同步包。

已完成：

1. 设计同步包 manifest。
2. 从 `sync_outbox` 导出 records，下载 zip 包含 `manifest.json` 和 `records.jsonl`。
3. 内网导入接口已做 `sync_inbox` 幂等检查。
4. 同步运行写审计日志。

后续：按 `object_type` 增加业务表 upsert 和冲突报告。

### 4.3 补采链路重构

目标：让抓取覆盖率页面能解释缺口，也能触发可控补采。

计划：

1. 自动失败源重试队列、退避策略和告警投递。
2. 归档页和 sitemap provider。
3. 复杂 SQL dialect 和大文件分片。
4. 覆盖率趋势统计。

已完成：手动失败源重试 v1，入口为 `POST /api/ingestion/runs/{run_id}/retry-failed-sources`，仅重试原 run 的失败源并记录 `retry_of_run_id/source_ids`；manual_import 已支持 CSV/SQL 上传或粘贴、`POST /api/ingestion/manual-import-preview` 后端预览、逐行校验、0 accepted 阻断和错误报告下载，提交时只把预览通过的条目写入 `manual_items`，并保留 raw payload 追溯。

## 5. 验收方式

- 微重构必须有测试或校验脚本。
- 涉及字段时同步 `config/contracts`。
- 涉及页面结构时同步 `docs/implementation/api-and-ui-implementation.md`。
- 涉及 SQL 导出时运行 `scripts/validate_company_sql.py`。
- 涉及测试覆盖率时运行 coverage 并保持门禁不低于 `80%`。
