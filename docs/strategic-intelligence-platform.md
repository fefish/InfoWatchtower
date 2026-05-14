# 规划部产业情报操作系统愿景

本文是愿景展开附录，不是项目入口。项目唯一总纲是 `docs/00-system-design.md`；如果两者表述有冲突，以总纲为准。

InfoWatchtower 不能只被设计成 AI 新闻日报工具。它的长期定位是规划部的产业情报操作系统：持续收集外部产业信号，形成判断，沉淀专题，再内化成公司内部需求、任务和决策依据。

## 1. 长期目标

系统要支撑三类工作：

- 持续感知：自动收集业界动态、技术演进、产品变化、政策市场、供应链和竞品信号。
- 组织判断：把零散新闻聚合成趋势、专题、风险、机会和战略含义。
- 内化行动：把外部信号转成内部需求、调研任务、产品建议、能力建设项和管理层材料。

第一阶段先从 AI 板块开始，但底层模型必须允许扩展到：

- 硬件与终端
- 半导体与算力
- 云与基础设施
- 机器人与具身智能
- 政策与市场
- 竞品与生态
- 未来新增的任何规划部关注板块

## 2. 新闻一级标签与源侧方向标签分离

当前 `planning_intel` 成品新闻一级标签是 `config/taxonomy/news_categories.json` 里的 AI 十分类。这是日报展示、`generated_news.category` 和公司 SQL category 的事实源。

`config/taxonomy/source_tags.json` 是数据源侧方向标签，用来描述源可能覆盖的业务方向、做覆盖分析和评分先验。它不是成品新闻分类。

长期分类分两层：

```text
domain / board          业务板块：AI、硬件、半导体、政策、竞品等
news taxonomy           成品新闻分类，如规划部 AI 十分类
source tags             数据源覆盖方向，如 AI工程能力、核心网/通信系统等
```

机器配置：

- `config/taxonomy/news_categories.json`
- `config/taxonomy/source_tags.json`
- `config/taxonomy/intelligence_domains.json`

这样当前 SQL 使用 AI 十分类，数据源可以按更大的方向做管理；后续硬件板块可以新增自己的 domain pack，不需要改主流程。

## 3. Domain Pack

每个板块都可以是一套 domain pack：

```text
config/domain_packs/{domain_code}/
  sources.json
  taxonomy.json
  scoring.json
  report_templates.json
  export_mapping.json
```

例如硬件板块可以新增：

- 硬件媒体、供应链网站、厂商新闻、专利/论文/展会源。
- 硬件自己的一级/二级标签。
- 对供应链、量产、成本、渠道、政策风险更敏感的评分权重。
- 硬件周报模板。
- 如果公司内部平台有硬件表，再加硬件 SQL/API 映射。

主链路不变：

```text
source_adapter -> raw_items -> news_items -> dedupe -> scoring -> report -> export
```

## 4. 从新闻到内部需求

系统不能止步于“看到新闻”。规划部真正要的是：

```text
外部信号
-> 新闻候选
-> 去重推荐
-> 编辑判断
-> 洞察 insight
-> 战略含义 implication
-> 机会/风险 opportunity_or_risk
-> 内部需求 requirement
-> 指派任务 task
-> 反馈给推荐和来源评分
```

机器契约：

- `config/contracts/strategic_loop.json`

建议新增业务表：

```text
insights
strategic_implications
opportunities
requirements
requirement_source_links
topic_tasks
```

关键原则：任何内部需求都必须能追溯回外部信号和原始来源。

## 5. 看板不是单一日报页

长期看板建议分层：

- 总览：今天/本周各板块热度、风险、机会、未处理任务。
- 板块：AI、硬件、半导体、政策等 domain 工作台。
- 数据源：来源质量、覆盖范围、抓取状态、采信贡献。
- 日报：每日推荐、采信、编辑、发布。
- 周报：趋势归纳、重点变化、采信管理。
- 专题：围绕一个技术/产品/竞品/政策持续追踪。
- 需求：由情报转出的内部需求和指派任务。
- 导出：公司 SQL、管理层材料、内部平台格式。

## 6. 第一版仍然要收敛

长期愿景很大，但第一版不要铺太散。

第一版要把“扩展能力”做好：

- domain 字段和 domain pack 目录预留。
- 数据源、标签、评分、报告、导出全部注册化。
- 需求和任务表先建最小闭环。
- AI 板块先跑通端到端。

等 AI 板块稳定后，再复制 domain pack 扩硬件、半导体和其他板块。
