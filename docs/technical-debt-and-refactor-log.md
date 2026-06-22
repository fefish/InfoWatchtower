# 技术债务与微重构台账

本文记录 AI情报官在重构过程中的技术债务、处理方案和代码证据。台账只记录会影响维护、测试、部署或后续扩展的事项，普通需求不放入本文。

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

## 3. 当前技术债务

| 编号 | 等级 | 内容 | 风险 | 计划 |
| --- | --- | --- | --- | --- |
| D-001 | P0 | SQL 条目级追溯还不完整 | 导出后人工排查字段来源成本高 | 增加导出记录和 SQL 行到 source/raw/news/generated 的跳转 |
| D-002 | P0 | 生产部署配置仍需定稿 | 外部演示环境和内网部署口径不一致 | 补生产 Compose、反向代理、备份恢复和启动检查 |
| D-003 | P0 | 同步包只有设计和运行记录，实质导出/导入未完成 | 公网到内网交付仍依赖手工文件 | 实现同步包生成、下载、导入、幂等和审计 |
| D-004 | P1 | 深度历史补采还依赖 RSS 当前窗口 | 老日期日报可能缺候选 | 增加归档页分页、sitemap 深挖、论文 provider 和 CSV 导入 |
| D-005 | P1 | 周报正文自动生成未实现 | 周报仍需人工整理长文 | 在现有采信项版本基础上增加周报生成服务 |
| D-006 | P1 | 覆盖率工具链刚补门禁，正式报告还需归档 | 白盒举证缺少可下载报告 | 生成 coverage HTML/XML 并放入 CI 产物 |
| D-007 | P2 | 领域包样例不足 | 证明跨板块复用时证据不够 | 增加硬件或半导体 domain pack 样例 |

## 4. 后续微重构计划

### 4.1 导出追溯重构

目标：让每一条 SQL 行能追到日报条目、生成稿、标准化新闻、原始 raw 和数据源。

计划：

1. 在导出历史中保存 daily item 和 generated news 映射。
2. 前端 SQL 导出页增加“查看来源链路”。
3. 校验脚本输出字段来源摘要。
4. 增加导出追溯测试。

### 4.2 同步包重构

目标：把公网到内网同步从人工 SQL 文件转为可审计同步包。

计划：

1. 设计同步包 manifest。
2. 导出数据、附件和校验摘要。
3. 内网导入时做幂等检查和冲突报告。
4. 同步运行写审计日志。

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
