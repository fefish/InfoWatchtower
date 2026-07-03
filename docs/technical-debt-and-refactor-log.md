# 技术债务与微重构台账

本文记录 AI情报官在重构过程中的技术债务、处理方案和代码证据。台账只记录会影响维护、测试、部署或后续扩展的事项，普通需求不放入本文。

AI情报官的重构分两层：整体是一次 SDD 驱动的从 0 到 1 重构（在旧系统字段合同和已验证 SQL 基础上重建主链路），局部是开发过程中对具体功能做的微重构。本文是局部微重构的记录，下面的微重构编号 R-00x 都对应整体重构内部的一次自规划功能改造，含问题、处理方式、代码证据和验收方式。

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

## 3. 当前技术债务

| 编号 | 等级 | 内容 | 风险 | 计划 |
| --- | --- | --- | --- | --- |
| D-004 | P1 | 深度历史补采还依赖 RSS 当前窗口 | 老日期日报可能缺候选 | 增加归档页分页、sitemap 深挖、论文 provider 和 CSV 导入 |
| D-005 | P1 | 周报正文自动生成未实现 | 周报仍需人工整理长文 | 在现有采信项版本基础上增加周报生成服务 |
| D-007 | P2 | 领域包样例不足 | 证明跨板块复用时证据不够 | 增加硬件或半导体 domain pack 样例 |
| D-008 | P2 | 同步包 apply handler 只覆盖核心公开信号对象 | 更多 object_type、冲突解决 UI 和人工处理流还不完整 | 扩展 apply handler 到更多对象，并补冲突处理页面 |
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
4. `data_sources/raw_items/news_items` 已按 `object_global_id/global_id` 执行业务表 apply。
5. revision/hash 冲突会写入 `sync_conflicts`，不静默覆盖本地对象。
6. 同步运行写审计日志。

后续：扩展更多 `object_type`，增加冲突解决 API/UI 和同步审计摘要。

### 4.3 补采链路重构

目标：让抓取覆盖率页面能解释缺口，也能触发可控补采。

计划：

1. 失败源重试。
2. 归档页和 sitemap provider。
3. 手工 CSV 导入入口。
4. 覆盖率趋势统计。

## 5. 验收方式

- 微重构必须有测试或校验脚本。
- 涉及字段时同步 `config/contracts`。
- 涉及页面结构时同步 `docs/api-and-ui-implementation.md`。
- 涉及 SQL 导出时运行 `scripts/validate_company_sql.py`。
- 涉及测试覆盖率时运行 coverage 并保持门禁不低于 `80%`。
