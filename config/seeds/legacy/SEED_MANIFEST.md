# Legacy Seed Manifest

这些文件是新项目自己的种子配置，不只是 `references/` 下的参考副本。后续导入器应优先读取本目录。

## 文件

- `rss_sources.json`：旧系统全量 RSS 源，108 个。
- `page_sources.json`：旧系统页面源，4 个。
- `wiseflow_sources.json`：旧系统 wiseflow 原始 API 源，1 个。
- `all_sources.index.json`：轻量索引，合并 wiseflow、RSS 和页面源，113 个。
- `source_registry.md`：旧人工源清单。
- `source_catalog/folo-rss-link-classification-unified-folo-cli-supplemented.csv`：Folo 分类与复核原始清单，197 行。
- `source_catalog/information_source_registry_20260511.csv`：用户补充的桌面信息源台账，351 行；导入器只读取其中有标准 `http/https` RSS URL 且状态不是“暂停/非文章页”的记录。

## 统计

- RSS 源：108
- RSS 启用：74
- RSS 停用：34
- 页面源：4
- Wiseflow 源：1
- 全量索引：113
- 全量索引启用：79
- 论文 RSS 源：17
- 论文 RSS 启用：14
- 补充台账行数：351
- 补充台账可导入 RSS 行：248
- 合并导入记录：361
- URL 去重后共享源：294
- URL 去重后规划部默认启用源：294

## 使用约定

- `rss_sources.json` 和 `page_sources.json` 保留旧字段，不在这里直接改结构。
- `all_sources.index.json` 只做快速浏览和导入预检，不能替代原始配置。
- `source_catalog/information_source_registry_20260511.csv` 是补充源台账：用于新增数据源、源侧方向标签和源质量评分；CSV 里的状态/纳入建议只作为运营元数据和评分先验，规划部工作台 v1 默认全量启用 294 个共享源。它不能修改成品新闻一级标签，也不能覆盖公司 SQL category。
- 新系统标准字段见 `config/contracts/source_fields.json`。
- 导入后应写入正式数据库表 `data_sources` 和 `data_source_versions`。
