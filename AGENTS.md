# InfoWatchtower 开发准则

本文档是给工程师和 AI coding agent 的开发准则。它管“怎么改代码和文档”，不是字段契约。

接手任务前必须先读：

1. `docs/00-system-design.md`
2. `docs/implementation-handoff.md`
3. `docs/01-implementation-plan.md`
4. `docs/README.md`
5. `config/contracts/README.md`
6. 相关 `config/contracts/*.json`

## 单一事实源

- 总纲：`docs/00-system-design.md`
- 开发任务书：`docs/implementation-handoff.md`
- 第一版施工计划：`docs/01-implementation-plan.md`
- 文档地图和修改规则：`docs/README.md`
- 机器契约：`config/contracts/*.json`
- 标签和板块：`config/taxonomy/*.json`
- 旧系统事实：`docs/legacy-system-spec.md` 和私有参考仓 `InfoWatchtower-References`

如果总纲、模块文档和 contract 冲突，不要擅自选一边实现。先同步修正冲突，再写代码。

`AGENTS.md` 和 `config/contracts/*.json` 的关系：

```text
AGENTS.md 管怎么工作、怎么同步修改。
contracts 管字段、流程、映射和接口边界。
```

## 修改同步规则

改主链路：

- 更新 `docs/00-system-design.md`
- 更新 `docs/implementation-handoff.md`
- 更新对应 `config/contracts/*.json`

改某个模块：

- 更新对应模块文档
- 更新对应 contract

改字段：

- 更新对应 contract
- 更新模块文档
- 更新 `docs/data-examples.md`

改 SQL 导出：

- 更新 `config/contracts/news_sql_mapping.json`
- 更新 `docs/data-format-mapping.md`
- 更新 `docs/data-examples.md`
- 更新 `scripts/validate_company_sql.py` 或确认现有校验仍覆盖新字段
- 运行 `scripts/validate_company_sql.py`

改登录：

- 更新 `config/contracts/auth_modes.json`
- 更新 `docs/auth-unified-login.md`
- 更新 `docs/deployment-ops.md`

改公网/内网同步：

- 更新 `config/contracts/sync_strategy.json`
- 更新 `docs/multi-environment-sync.md`

改前端工作台样式或页面结构：

- 更新 `docs/api-and-ui-implementation.md`
- 保留 `frontend/src/layouts/AppShell.vue` 的浅色 indigo/slate 工作台壳
- 保留 `frontend/src/pages/SourcesPage.vue` 的信息流式数据源列表和右侧标签策略面板
- 清理冲突 CSS，避免同一页面布局在 `frontend/src/styles/base.css` 里被多处重复定义

## 不可破坏的设计原则

- 不要把系统写死成 RSS + AI 日报。
- `domain_code`、`visibility_scope`、`sync_policy` 必须贯穿数据源、raw、news 和同步链路。
- 原始数据必须完整保存在 `raw_items.raw_payload_json`。
- 去重发生在 `news_items` 之后、推荐之前。
- `adoption_status` 属于日报/周报采信层，不属于 `news_items`。
- 日报编辑不覆盖 `raw_items` 和 `generated_news`。
- 标准公司 SQL 只导出已发布日报中 `daily_report_items.adoption_status = 2`、`generated_news.generation_status = ready` 且 `generated_by` 非 `rule_v1` 的条目。
- 标准公司 SQL 必须通过 `scripts/validate_company_sql.py`；SQL 预览标题统一为 `InfoWatchtower Company SQL Preview`，0505 预览是字段校验基准。
- `planning_intel` 成品新闻的一级标签必须是旧系统约定的 10 个 AI 标签，默认来自 `config/taxonomy/news_categories.json`；数据源侧可以使用 `config/taxonomy/source_tags.json` 的方向标签，但这些标签只是源管理、覆盖分析和评分先验，不能写入 `generated_news.category` 或公司 SQL category。
- 一级/二级标签由工作台统一策略管理，不在单个数据源配置，因为一个数据源可能覆盖多个关注方向。
- 前端数据源页的设计基线是浅色商务工作台、indigo 主色、slate 中性色、信息流式数据源列表、右侧 tab 化标签策略面板；不要回退成深色壳、宽表格、绿色/青色主调或单源标签配置。
- 密钥、token、cookie 和 `.env` 不进入 Git，不进入同步包。
- 私有参考仓 `InfoWatchtower-References` 是参考资料，不是新系统运行入口。
