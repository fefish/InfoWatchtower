# Domain Packs

Domain pack 用于新增关注领域，例如硬件、半导体、政策、竞品，而不修改主链路。

当前 loader 支持 flat JSON：

```text
config/domain_packs/{domain_code}.json
```

可参考 `hardware.json`，字段包含 `domain_code`、`boards`（含
`suggested_categories`）、`fallback_board`、`label_sets`、
`category_keywords` 和 `scoring.prior_keywords` / `source_weight_hints`。

## 消费方式（不再只是 seed 落库）

1. 启动 seed（`backend/app/auth/service.py`）注册 pack 的 `label_sets/labels`。
2. `GET /api/domain-packs` 列出可用 pack 及其 boards / label sets / scoring
   概要，供建台向导选择。
3. 关联方式：把 pack 的 `domain_code` 写入 `workspace.default_domain_code`
   （建台或 PATCH workspace 均可）。
4. 策略解析（`backend/app/workspaces/policy.py`）按
   「workspace 标签策略 -> 关联 domain pack -> 内置 AI 默认」的顺序真正消费
   pack 配置：
   - `scoring.prior_keywords`：非 AI 口径工作台的推荐评分/准入先验关键词。
   - `category_keywords`：LLM 不可用时的分类降级关键词映射。
   - `boards` + `fallback_board`：tech_insight 成稿的看板分组 taxonomy；
     `suggested_categories` 决定 category 到看板的归组。
   - `label_sets.secondary_labels_by_primary`：二级标签会 1) 作为分类降级与
     评分先验关键词；2) 参与看板归组（命中二级标签的 category 归入其一级
     分类对应的看板）。工作台自定义 `label_set_code` 会在推荐链路运行时
     upsert 成 LabelSet/Label 记录。

`config/taxonomy/news_categories.json` 是规划部成品新闻和公司 SQL 的默认
一级标签；`config/taxonomy/source_tags.json` 是数据源侧方向标签，只用于源
管理、覆盖分析和评分先验。

新增 domain pack 时必须保持：

- 仍走统一 `data_sources -> raw_items -> news_items -> dedupe -> recommendation -> report -> export` 主链路。
- 数据源必须有 `domain_code`。
- 不同板块可以有不同 taxonomy、评分权重、报告模板和导出映射。
- planning_intel 永远锁定内置 AI 默认口径，不受同名 pack 影响。
- 非公司 SQL 口径（非 AI 十分类）的工作台不允许走标准公司 SQL 导出。
- 不要 fork 后端或前端代码。
