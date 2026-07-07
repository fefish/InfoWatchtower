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
- `company_sql_baseline_20260505.sql`：0505 legacy 基准的锁列夹具，`scripts/validate_company_sql.py` 在无 `outputs/` 本地基准（如 CI 全新 checkout）时回落加载；列顺序与本地完整 0505 预览必须一致。
- `auth_modes.json`：公网/内网登录模式和统一身份字段。
- `deployment_modes.json`：四种部署形态（standalone/cloud/intranet/extranet）、能力开关、合法登录组合、启动 fail-fast 规则和 `GET /api/meta/runtime`。
- `workspace_model.json`：工作台、共享源启用、工作台内模块和情报板块边界。
- `notifications.json`：协作活动事件、站内通知、未读/已读 API 和前端铃铛出现条件。
- `search.json`：全局检索 API、对象类型、权限过滤、runtime capability 和顶部搜索出现条件。
- `frontend_control_governance.json`：全局前端控件、按钮/RouterLink 行为、假控件扫描和测试证据规则。
- `label_model.json`：可配置标签集、标签和内容标签绑定。
- `report_renditions.json`：成稿格式注册表、rendition 投影字段和导出边界（rendition 是投影不是副本）。
- `extension_points.json`：数据源、推荐、生成、导出、登录、板块、同步的扩展点。
- `strategic_loop.json`：外部信号到洞察、需求、任务的规划部闭环。
- `sync_strategy.json`：公网/内网多环境同步策略、同步表和同步包格式。
- `audit_ops.json`：审计日志字段、工作台过滤、查询权限和审计页前端调用规则。
- `archive_knowledge.json`：当前系统实体目录、实体事件、从日报/周报条目登记实体事件的 API 和追溯规则。
- `tech_insight_loop_legacy_import.json`：Tech Insight Loop 旧 SQLite 资产盘点、历史导入 dry-run、历史导入边界和目标映射。

## 什么时候改 contracts

- 改字段、枚举、表结构、数据流顺序时，要改 contracts。
- 只改解释文字、背景说明、业务愿景时，通常不需要改 contracts。
- 如果模块文档和 contracts 冲突，先修冲突，再写代码。
