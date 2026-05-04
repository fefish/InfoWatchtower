# Domain Packs

Domain pack 用于新增规划部关注板块，例如硬件、半导体、政策、竞品，而不修改主链路。

建议结构：

```text
config/domain_packs/{domain_code}/
  sources.json
  taxonomy.json
  scoring.json
  report_templates.json
  export_mapping.json
```

当前第一版从 `ai` 板块开始。`config/taxonomy/news_categories.json` 是 AI 兼容公司 SQL 的历史标签，不是所有板块的长期上限。

新增 domain pack 时必须保持：

- 仍走统一 `data_sources -> raw_items -> news_items -> dedupe -> recommendation -> report -> export` 主链路。
- 数据源必须有 `domain_code`。
- 不同板块可以有不同 taxonomy、评分权重、报告模板和导出映射。
- 不要 fork 后端或前端代码。

