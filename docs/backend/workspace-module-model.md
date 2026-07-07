# 工作台、数据源共享与标签模型

本文说明 InfoWatchtower 如何支持多个工作台，同时保持一套简洁、共享、可插拔的情报主链路。

当前工作台、sections、成员、label/feedback policy、report formats 和 domain pack 的
目标态事实源是 `docs/backend/workspace-configuration-design.md`。本文保留为共享源、标签模型
和工作台概念的细节附录。

机器契约见：

- `config/contracts/workspace_model.json`
- `config/contracts/source_fields.json`
- `config/contracts/label_model.json`

## 1. 核心结论

工作台不是不同产品线，也不是两套系统。每个工作台默认都使用同一套核心情报能力：

```text
数据源管理
候选池
日报
周报
SQL 导出
用户权限
审计
```

工作台只做三件事：

- 决定用户进入哪个工作范围。
- 决定这个工作台启用哪些共享数据源、使用哪套统一一级/二级标签策略、聚类推荐配置和评分配置。
- 决定哪些插件模块开启；第一版默认不开启工具目录、工具任务、独立专题等附加页面。

不要给每个工作台做一套自定义数据结构。

当前前端导航里如果出现硬编码页面，只能视为阶段性实现。目标态必须由数据库驱动：

```text
workspaces             工作台列表
workspace_sections     工作台显示哪些核心页面或插件页面
workspace_source_links 工作台启用哪些共享源以及源级权重、日限、抓取配置
label_sets / labels    一级标题、二级标题和导出分类
```

## 2. 三个概念

三层边界必须分清：

```text
workspace_code          工作范围和权限边界
section_key/module_key  数据库注册的核心页面或可选插件页面
domain_code             情报主题板块
```

例子：

- `planning_intel`：规划部情报工作台。
- `ai_tools`：可以作为另一个工作范围，但不默认额外出现工具目录或工具任务。
- `domain_code=ai`：AI 主题内容。
- `domain_code=hardware`：未来硬件主题内容。

## 3. 数据源共享池

数据源应先进入全局共享池：

```text
data_sources
```

工作台通过链接表启用共享源：

```text
workspace_source_links
  workspace_id
  data_source_id
  domain_code
  enabled
  source_weight
  daily_limit
  config_json
```

含义：

- `data_sources` 保存源的真实定义，例如 RSS 地址、wiseflow 配置、页面抓取规则。
- `workspace_source_links` 保存某个工作台是否启用该源，以及该工作台下的权重、默认板块、日限和抓取相关差异配置。
- 同一个源可以被多个工作台复用，不复制数据源定义。
- adapter 只看 `data_sources` 和链接配置后抓取，不关心日报或周报采信。

## 4. 候选池是什么

候选池不是一个新数据源，也不是日报。它是日报/周报采信前的工作池：

```text
data_sources
-> adapter fetch
-> raw_items
-> news_items
-> dedupe_groups
-> candidate pool
-> recommendation_items
-> daily_report_items / weekly_report_items
```

候选池页面展示的是去重后的代表项，同时必须能展开追溯：

```text
候选项
-> dedupe_group
-> news_items
-> raw_items
-> data_sources
```

候选池要回答：

- 这条候选来自哪些原始源。
- 为什么它是 winner。
- 它命中了哪些标签。
- 推荐分、热度、来源分如何。
- 它是否已被采信、剔除、待观察。

## 5. 标签配置

标签统一用配置模型，不在每个工作台硬编码：

```text
label_sets
labels
content_labels
```

第一版内置规划部成品新闻一级标题，来自：

```text
config/taxonomy/news_categories.json
```

数据源侧方向标签来自 `config/taxonomy/source_tags.json`。它们可以描述源覆盖范围，但不能替代成品新闻一级标题，也不能写入 SQL category。

一级标题就是第一版的“工具目录”式配置入口。数据源管理页面应允许管理员配置：

- 每个工作台启用哪些共享数据源。
- 每个工作台的统一一级标签列表。
- 每个一级标签下有哪些二级标签。
- 每个工作台的新闻生成格式 `news_format_code` 和必填内容字段。
- 默认标签、兜底标签和模型打标阶段。
- 每个共享源在当前工作台的启用状态、权重、日限和抓取相关配置。

第一版不要在单个数据源上维护标签映射。一个源可能同时覆盖多个关注方向，标签应在 raw 到 news 结构化和去重后标签定稿阶段，基于新闻内容和工作台统一标签策略生成。

`planning_intel` 第一版使用 `company_sql_v1` 新闻结构，必须保留 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五个内容字段，后续 SQL 导出才可以从 `generated_news.content_json` 稳定映射到公司内网表。AI 工具桌面可以使用独立 `tool_intel_v1`，但仍复用相同主链路。

后续硬件、半导体、政策等板块可以增加新的 label set；但仍通过 `label_sets/labels/content_labels` 扩展，不新建一套工具目录表。

## 6. 权限规则

两层权限：

```text
global role      super_admin/editor_admin/analyst/viewer
workspace role   owner/admin/member/viewer
```

第一版先以 global role 为主。后续做真正多团队协作时：

- 先检查用户是否属于 workspace。
- 再检查 global role 是否允许这个动作。
- 再检查 workspace role 是否允许访问该工作台模块。

## 7. 插件模块规则

第一版不默认显示工具目录、工具任务、独立热点专题等附加模块。

如果后续确实要新增插件模块，必须满足：

1. 在数据库 `workspace_sections` 注册，默认 `enabled=false`。
2. 前端从后端读取 enabled sections 后再显示，不允许硬编码默认显示。
3. 插件模块只能做加法，不能改变数据源、候选池、日报、周报、导出主链路。
4. 如果只是一级标题/二级标题/聚类推荐配置，应放在数据源管理和标签配置里，不新增页面。

## 8. 工作台自助扩展

工作台可以由超级管理员在界面上直接创建，不需要改代码或种子：

```text
POST /api/workspaces
  code                英文小写标识，全局唯一
  name / description  展示名称和说明
  workspace_type      默认 intelligence_workspace
  default_domain_code 默认 ai，可填 hardware/policy 等
```

创建时自动完成：

- 注册全部核心页面分区（数据源管理、候选池、日报、周报、历史归档、实体大事记、质量归档、导出、用户、审计）。
- 写入默认标签策略（`ai_sql_categories` 起步），随后在数据源管理页右侧策略面板改成该工作台自己的一级/二级标签和新闻结构。
- 给现有超管加 owner 成员关系，`sort_order` 排在现有工作台之后。

启动 seed 只维护内置 `planning_intel/ai_tools` 定义，不会停用或覆盖自建工作台。

新工作台整合信息源走共享池，两条路都不复制源定义：

- 启用已有共享源：数据源列表按当前工作台展示启停状态，单源配置面板写 `workspace_source_links` 的启用/权重/日限。
- 自建新源：`POST /api/sources` 传 `workspace_code + name + source_type + url`，源进入共享池并自动在该工作台启用；同 URL 源自动复用已有定义，不产生重复源。`PATCH /api/sources/{source_id}` 可编辑源定义，给 Tech Insight Loop 待补入口源补 URL 后即可抓取。

机器契约见 `config/contracts/workspace_model.json` 的 `workspace_creation` 和 `config/contracts/source_fields.json` 的 `custom_source_api`。

## 9. 和 domain pack 的关系

domain pack 仍然解决主题扩展：

```text
ai
hardware
semiconductor
robotics
policy
```

workspace 解决产品桌面：

```text
planning_intel
ai_tools
```

同一个 workspace 可以展示多个 domain；同一个 domain 可以被多个 workspace 引用。
