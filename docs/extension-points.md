# 可插拔扩展点设计

本文档固定 InfoWatchtower 后续加能力的位置，避免新功能直接侵入主链路。

机器可读契约：

- `config/contracts/extension_points.json`

## 1. 核心原则

主链路保持稳定：

```text
data_sources
-> source_adapter
-> raw_items
-> content_extractor
-> normalizer
-> news_items
-> dedupe_strategy
-> scoring_strategy
-> generated_news
-> report_builder
-> exporter
```

新增能力走注册，不改主链路。

## 2. 数据源扩展

新增数据源时，只新增 adapter：

```python
class SourceAdapter:
    source_type: str

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        ...
```

注册示例：

```python
adapter_registry.register("rss", RssFeedAdapter())
adapter_registry.register("wiseflow", WiseflowReadInfoAdapter())
adapter_registry.register("paper_api", PaperApiAdapter())
```

adapter 必须输出 `raw_items` 最低字段，后续模块只认统一字段，不关心来源是 RSS、wiseflow、页面、论文 API 还是内部源。

## 3. 内容抽取扩展

正文抽取是可选增强，不是数据源 adapter 的硬职责。

例子：

- RSS 只有摘要时，可用 `source_url` 抽取正文。
- 页面源可以抽详情页正文。
- 论文源可以补 DOI、PDF、作者、机构、引用数。

抽取结果写入：

- `raw_items.raw_content`
- `raw_items.source_specific_json`
- 未来的 `paper_metadata` 扩展表

不能修改 `raw_items.raw_payload_json`。

## 4. 标准化扩展

默认 normalizer 负责：

- URL canonicalize。
- 时间解析。
- 内容优先级选择。
- `focus_id` 继承。
- `dedupe_key` 生成。

只有特殊源才写 source_type hook。比如论文源可以额外归一作者、DOI、PDF URL。

## 5. 去重扩展

第一版固定硬去重：

- URL canonical 去重。
- 没 URL 时标题 + 日期兜底。

第二阶段可新增软聚类：

- embedding 相似度。
- 同公司/产品/模型名。
- 同日期窗口。

软聚类只辅助周报、专题和编辑提示，不替代第一版硬去重。

## 6. 推荐扩展

推荐策略通过 `algorithm_version` 注册。

第一版必须输出这些分数：

- `quality_score`
- `topic_score`
- `freshness_score`
- `feedback_score`
- `diversity_score`
- `source_score`
- `heat_score`
- `final_score`

后续想加热度算法、来源评分、人工权重，不改日报和 SQL 导出，只新增评分策略或调整参数。

## 7. 生成扩展

模型生成作为 provider 注册：

```text
model_provider + model_name + prompt_version
```

无论模型返回什么，最终 `source_url`、`created_at` 都必须从 `news_items/raw_items` 强制回填，不能信模型生成的链接和时间。

## 8. 报告扩展

日报、周报、专题都走 report builder。

第一版：

- `daily`
- `weekly`
- `topic`

报告层的编辑只写 `*_report_items.editor_*` 字段，不修改原始数据和模型原稿。

## 9. 导出扩展

第一版导出：

- `company_daily_sql`

后续可以加：

- `company_weekly_sql`
- `csv`
- `json`
- `internal_api_push`

导出器只读已发布、已采信的报告条目。导出动作写入 `export_jobs` 和 `export_job_items`，保证可追溯。

## 10. 登录扩展

认证通过 `AUTH_MODE` 选择 adapter。

第一版：

- `local`
- `public_password`
- `intranet_header`

后续：

- `public_oidc`
- `intranet_oidc`
- `intranet_saml`

所有 adapter 都输出同一个 `ExternalIdentity`。业务系统只绑定本地 `users.id`，所以从公网迁到内网时，不需要重写日报、评论、权限、数据源管理等业务模块。

## 11. 板块扩展

新增业务板块不要改主链路，新增 domain pack：

```text
config/domain_packs/{domain_code}.json
```

也可以在后续需要更多文件时扩展成目录：

```text
config/domain_packs/{domain_code}/
  sources.json
  taxonomy.json
  scoring.json
  report_templates.json
  export_mapping.json
```

例子：

- `ai`
- `hardware`
- `semiconductor`
- `robotics`
- `policy_market`
- `competitor`

每个板块可以有自己的信息源、标签、评分权重、报告模板和导出映射，但仍进入统一 `raw_items/news_items/report/export` 主模型。

当前仓库已提供 flat JSON 样例 `config/domain_packs/hardware.json`，启动 seed 会注册
`hardware_categories` label set；这证明新增板块只需要配置和 seed loader，不需要 fork 主链路。

## 12. 同步扩展

公网、内网、开发环境之间通过 sync adapter 同步。

第一版支持：

- 手工导出/导入同步包。
- 应用层 outbox/inbox。

原则：

- 公网采集到的公开信号可以同步到内网。
- 内网用户、评论、需求、任务默认不向公网同步。
- 数据源密钥不通过同步包传递。
