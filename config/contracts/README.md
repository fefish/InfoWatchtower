# Contracts 说明

`config/contracts/*.json` 不是开发准则，也不是另一套设计文档。

它们是给代码、测试和 AI 实现者读取的“机器契约”：把字段、枚举、流程顺序、映射关系写成结构化 JSON，避免只靠自然语言理解。

## 和 AGENTS.md 的区别

```text
AGENTS.md
  给人和 AI 看的工作规则：
  先读什么、改设计要同步哪些文件、哪些原则不能破坏。

config/contracts/*.json
  给实现和测试看的机器契约：
  有哪些字段、哪些 source_type、SQL 怎么映射、登录模式有哪些、同步表有哪些。
```

一句话：

```text
AGENTS.md 管“怎么改”
contracts 管“代码必须长什么样”
```

## 当前契约

- `source_fields.json`：数据源配置字段、旧源如何导入新系统。
- `adapter_pipeline.json`：采集 adapter、raw_items、news_items、去重阶段的字段和顺序。
- `news_sql_mapping.json`：内部新闻对象如何导出为公司 SQL。
- `auth_modes.json`：公网/内网登录模式和统一身份字段。
- `workspace_model.json`：工作台、共享源启用、工作台内模块和情报板块边界。
- `label_model.json`：可配置标签集、标签和内容标签绑定。
- `extension_points.json`：数据源、推荐、生成、导出、登录、板块、同步的扩展点。
- `strategic_loop.json`：外部信号到洞察、需求、任务的规划部闭环。
- `sync_strategy.json`：公网/内网多环境同步策略、同步表和同步包格式。

## 什么时候改 contracts

- 改字段、枚举、表结构、数据流顺序时，要改 contracts。
- 只改解释文字、背景说明、业务愿景时，通常不需要改 contracts。
- 如果模块文档和 contracts 冲突，先修冲突，再写代码。
