# 工作台、数据源共享与标签模型

本文说明 InfoWatchtower 如何支持多个工作台，同时保持一套简洁、共享、可插拔的情报主链路。

机器契约见：

- `config/contracts/workspace_model.json`
- `config/contracts/source_fields.json`
- `config/contracts/label_model.json`

## 1. 核心结论

工作台不是不同产品线，也不是两套系统。每个工作台默认都使用同一套核心情报能力：

```text
数据源
候选池
日报
周报
热点专题
SQL 导出
用户权限
审计
```

工作台只做三件事：

- 决定用户进入哪个工作范围。
- 决定这个工作台启用哪些共享数据源、默认标签集和评分配置。
- 可选叠加少量附加模块，例如 AI 工具目录和工具任务。

不要给每个工作台做一套自定义数据结构。

## 2. 三个概念

三层边界必须分清：

```text
workspace_code          工作范围和权限边界
section_key/module_key  页面或可选附加模块
domain_code             情报主题板块
```

例子：

- `planning_intel`：规划部情报工作台。
- `ai_tools`：同一套情报能力下，额外叠加 AI 工具入口的工作台。
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
- `workspace_source_links` 保存某个工作台是否启用该源，以及该工作台下的权重、默认板块、限制和标签策略。
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

第一版内置 AI SQL 导出的 10 个一级标签，来自：

```text
config/taxonomy/news_categories.json
```

后续硬件、半导体、政策等板块可以增加新的 label set。数据源配置页应允许选择该工作台启用哪些 label set、默认标签策略和自动打标规则。

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

## 7. 新增 AI 工具入口的方式

不要新建另一个仓库。

推荐流程：

1. 新增 `workspaces` 记录：`code=ai_tools`。
2. 保留核心情报模块：数据源、候选池、日报、周报、专题、导出。
3. 新增可选模块：工具目录、工具运行、工具产物。
4. 工具运行结果如果能沉淀为情报，再通过标准链路写入 `raw_items/news_items/insights`。

## 8. 和 domain pack 的关系

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
