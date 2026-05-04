# 文档地图

本文档说明 InfoWatchtower 文档如何阅读、如何维护，避免出现“总纲一套实现、模块文档另一套实现”。

## 1. 阅读顺序

开发者或 AI 接手时：

1. 先读 `AGENTS.md`。
2. 再读 `docs/00-system-design.md`。
3. 再读 `docs/implementation-handoff.md`。
4. 先读 `config/contracts/README.md`，理解 contracts 是什么。
5. 写代码时查相关 `config/contracts/*.json` 和 `config/taxonomy/*.json`。
6. 只在需要模块细节时阅读对应专题附录。
7. 旧系统事实从私有参考仓查询；主仓说明见 `references/README.md`，不从旧代码直接继承新架构。

## 2. 单一事实源

- 总体目标、主链路、第一版边界：`docs/00-system-design.md`
- 开发顺序和验收：`docs/implementation-handoff.md`
- 开发准则和修改同步规则：`AGENTS.md`
- 机器可读字段和流程：`config/contracts/*.json`
- contracts 目录说明：`config/contracts/README.md`
- AI 兼容标签和长期板块：`config/taxonomy/*.json`
- 旧系统事实：`docs/legacy-system-spec.md` 与私有参考仓 `InfoWatchtower-References`

如果模块文档和总纲冲突，以总纲为准；如果自然语言文档和 JSON 契约冲突，开发前必须同时更新两者。

## 3. 模块文档

- `docs/data-examples.md`：数据流样例。
- `docs/ingestion-adapter-dedup-spec.md`：采集、标准化和去重。
- `docs/data-format-mapping.md`：信息源、业务字段、公司 SQL 三层映射。
- `docs/data-lineage-and-storage.md`：存储、追溯、审计。
- `docs/feedback-heat-scoring.md`：点赞、评论、评分、热度和来源评分。
- `docs/api-and-ui-implementation.md`：后端 API、前端页面和验收。
- `docs/auth-unified-login.md`：公网/内网统一登录。
- `docs/deployment-ops.md`：部署、备份、自动发布。
- `docs/multi-environment-sync.md`：公网/内网多数据库同步。
- `docs/extension-points.md`：可插拔扩展点。
- `docs/strategic-intelligence-platform.md`：愿景展开附录。

## 4. 修改规则

改设计时按影响范围同步：

- 改主链路：更新 `docs/00-system-design.md`、`docs/implementation-handoff.md` 和相关 `config/contracts/*.json`。
- 改某个模块：更新对应模块文档和相关 contract。
- 改字段：更新 contract、模块文档、数据样例。
- 改 SQL 导出：更新 `config/contracts/news_sql_mapping.json`、`docs/data-format-mapping.md`、`docs/data-examples.md`。
- 改登录：更新 `config/contracts/auth_modes.json`、`docs/auth-unified-login.md`、`docs/deployment-ops.md`。
- 改公网/内网同步：更新 `config/contracts/sync_strategy.json`、`docs/multi-environment-sync.md`。

不要只改一处，让另一个文档保留旧逻辑。
