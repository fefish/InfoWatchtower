# Domain Packs

Domain pack 用于新增规划部关注板块，例如硬件、半导体、政策、竞品，而不修改主链路。

当前 seed loader 支持 flat JSON：

```text
config/domain_packs/{domain_code}.json
```

可参考 `hardware.json`，至少包含 `domain_code`、`boards`、`label_sets` 和
`scoring.prior_keywords`。启动时会注册 `label_sets/labels`，不会改主流水线。

后续板块配置变复杂时，可扩展为目录结构：

```text
config/domain_packs/{domain_code}/
  sources.json
  taxonomy.json
  scoring.json
  report_templates.json
  export_mapping.json
```

当前第一版从 `ai` 板块开始。`config/taxonomy/news_categories.json` 是规划部成品新闻和公司 SQL 的默认一级标签；`config/taxonomy/source_tags.json` 是数据源侧方向标签，只用于源管理、覆盖分析和评分先验。

新增 domain pack 时必须保持：

- 仍走统一 `data_sources -> raw_items -> news_items -> dedupe -> recommendation -> report -> export` 主链路。
- 数据源必须有 `domain_code`。
- 不同板块可以有不同 taxonomy、评分权重、报告模板和导出映射。
- 不要 fork 后端或前端代码。
