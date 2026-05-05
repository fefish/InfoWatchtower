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

改登录：

- 更新 `config/contracts/auth_modes.json`
- 更新 `docs/auth-unified-login.md`
- 更新 `docs/deployment-ops.md`

改公网/内网同步：

- 更新 `config/contracts/sync_strategy.json`
- 更新 `docs/multi-environment-sync.md`

## 不可破坏的设计原则

- 不要把系统写死成 RSS + AI 日报。
- `domain_code`、`visibility_scope`、`sync_policy` 必须贯穿数据源、raw、news 和同步链路。
- 原始数据必须完整保存在 `raw_items.raw_payload_json`。
- 去重发生在 `news_items` 之后、推荐之前。
- `adoption_status` 属于日报/周报采信层，不属于 `news_items`。
- 日报编辑不覆盖 `raw_items` 和 `generated_news`。
- 标准公司 SQL 只导出已发布日报中 `daily_report_items.adoption_status = 2` 的条目。
- 一级/二级标签由工作台统一策略管理，不在单个数据源配置，因为一个数据源可能覆盖多个关注方向。
- 密钥、token、cookie 和 `.env` 不进入 Git，不进入同步包。
- 私有参考仓 `InfoWatchtower-References` 是参考资料，不是新系统运行入口。
