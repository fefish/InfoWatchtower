# 文档地图

本文档说明 InfoWatchtower 文档如何阅读、如何维护，避免出现“总纲一套实现、模块文档另一套实现”。

## 1. 阅读顺序

开发者或 AI 接手时：

1. 先读 `AGENTS.md`。
2. 再读 `docs/00-system-design.md`。
3. 再读 `docs/implementation-handoff.md`。
4. 再读 `docs/01-implementation-plan.md`。
5. 先读 `config/contracts/README.md`，理解 contracts 是什么。
6. 写代码时查相关 `config/contracts/*.json` 和 `config/taxonomy/*.json`。
7. 只在需要模块细节时阅读对应专题附录。
8. 旧系统事实从私有参考仓查询；主仓说明见 `references/README.md`，不从旧代码直接继承新架构。

当前进度：阶段 0-5 已完成可回填闭环。阶段 3 已完成旧种子源导入、共享数据源池、默认工作台源链接、工作台统一标签策略、adapter 框架、RSS/paper RSS/页面源抓取到 `raw_items`、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口；阶段 4 已完成 raw 到 news 标准化、canonical URL、dedupe key、工作台隔离硬去重、winner/loser 回写和查询 API；阶段 5 已完成完整流水线 API、按 `day_key` 推荐 run、可解释推荐分、可选 MiniMax 中国区 OpenAI-compatible `generated_news`、日报草稿、发布、条目编辑和点赞/评分/评论最小 API。scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿。前端首页必须显示阶段 5；工作台壳和导航必须来自后端工作台配置；数据源页采用信息流式共享源列表，日报页可按日期生成日报草稿，并支持正文展示、采信切换、编辑、点赞、评分、评论和追溯查看。`planning_intel` 与 `ai_tools` 的默认标签策略必须保持后端隔离。下一步进入候选池页面和阶段 6 公司 SQL 导出。

## 2. 单一事实源

- 总体目标、主链路、第一版边界：`docs/00-system-design.md`
- 开发顺序和验收：`docs/implementation-handoff.md`
- 阶段施工计划和验收命令：`docs/01-implementation-plan.md`
- 开发准则和修改同步规则：`AGENTS.md`
- 机器可读字段和流程：`config/contracts/*.json`
- contracts 目录说明：`config/contracts/README.md`
- AI 兼容标签和长期板块：`config/taxonomy/*.json`
- 旧系统事实：`docs/legacy-system-spec.md` 与私有参考仓 `InfoWatchtower-References`

如果模块文档和总纲冲突，以总纲为准；如果自然语言文档和 JSON 契约冲突，开发前必须同时更新两者。

## 3. 模块文档

- `docs/data-examples.md`：数据流样例。
- `docs/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
- `docs/ingestion-adapter-dedup-spec.md`：采集、标准化和去重。
- `docs/data-format-mapping.md`：信息源、业务字段、公司 SQL 三层映射。
- `docs/data-lineage-and-storage.md`：存储、追溯、审计。
- `docs/feedback-heat-scoring.md`：点赞、评论、评分、热度和来源评分。
- `docs/api-and-ui-implementation.md`：后端 API、前端页面和验收。
- `docs/auth-unified-login.md`：公网/内网统一登录。
- `docs/auth-security-roadmap.md`：公网登录安全、Google SSO、公司 IDaaS 接入计划。
- `docs/workspace-module-model.md`：工作台、共享数据源、候选池、标签和情报板块设计。
- `docs/deployment-ops.md`：部署、备份、自动发布。
- `docs/development-quickstart.md`：当前工程骨架的本地启动说明。
- `docs/multi-environment-sync.md`：公网/内网多数据库同步。
- `docs/extension-points.md`：可插拔扩展点。
- `docs/strategic-intelligence-platform.md`：愿景展开附录。

## 4. 修改规则

改设计时按影响范围同步：

- 改主链路：更新 `docs/00-system-design.md`、`docs/implementation-handoff.md` 和相关 `config/contracts/*.json`。
- 改某个模块：更新对应模块文档和相关 contract。
- 改字段：更新 contract、模块文档、数据样例。
- 改 SQL 导出：更新 `config/contracts/news_sql_mapping.json`、`docs/data-format-mapping.md`、`docs/data-examples.md`。
- 改登录：更新 `config/contracts/auth_modes.json`、`docs/auth-unified-login.md`、`docs/auth-security-roadmap.md`、`docs/deployment-ops.md`。
- 改工作台/模块/共享源：更新 `config/contracts/workspace_model.json`、`config/contracts/source_fields.json`、`docs/workspace-module-model.md`、`docs/00-system-design.md`。
- 改标签体系：更新 `config/contracts/label_model.json`、`config/taxonomy/*.json`、对应模块文档和数据样例。
- 改公网/内网同步：更新 `config/contracts/sync_strategy.json`、`docs/multi-environment-sync.md`。

不要只改一处，让另一个文档保留旧逻辑。
