# 报告多版成稿与格式注册表设计（Report Renditions）

本文是多版成稿和格式注册表细节附录。日报/周报采信、编辑覆盖、发布、锁定和版本的
目标态事实源是 `docs/backend/reports-editorial-design.md`。

状态：P1-P4 已实施（2026-07-02）。机器契约见 `config/contracts/report_renditions.json`。
P4 的模型产出（insight prompt v2）已随生成链路接入，配置 MiniMax key 后自动生效；
未配 key 时成稿走规则降级并在条目上标注「规则降级稿」。
§10 模板驱动生成（generation_template）为 2026-07-07 设计已定稿待实现。

## 1. 背景与目标

当前内网的真实工作流是人肉双版本：同事系统生成技术洞察快报（14 业务板块 + 头条 +
要点/总结格式），用户再用 AI 转换成内网版本（10 类 + 五段 content_json），两个版本
同时挂在内网。

目标：把这个流程搬进 InfoWatchtower——**一次采信，多版成稿**。编辑只做一次采信决
策，系统按注册的格式同时产出多份成稿（rendition），内网版继续走公司 SQL 合同，技
术洞察版对齐同事快报的结构，后续任意新格式通过注册表配置产生，不改代码。

用户已拍板的四个决策：

1. 技术洞察版每条的要点/总结正文：**生成时额外产出**（MiniMax prompt 扩展，独立
   字段存放，不进 SQL content_json；未配 key 时降级为五段字段映射）。
2. 定制程度：**直接做格式注册表**（分组维度/字段清单/头条区/导出目标可配）。
3. 技术洞察版导出：**Markdown + HTML 双导出**，样式对齐 `周报文件/技术洞察日报-*.{md,html}`。
4. 头条区：**自动 Top6（推荐分）+ 编辑可调**（勾选/取消）。

## 2. 概念模型

```text
daily_reports / weekly_reports        采信事实源（一天/一周一份，不变）
  └─ daily_report_items               采信状态 + 编辑覆盖 + is_headline（新增）
       └─ generated_news              五段 content_json + category（不变）
                                      + insight_json（新增：板块/要点/总结/标签行）

report_formats                        格式注册表（workspace 级）
report_renditions                     某报告按某格式渲染出的成稿（视图层，可重生成）
```

核心不变式：

- rendition 是**视图层**。删除或重生成任何 rendition 不影响采信状态、
  `generated_news`、推荐链路和公司 SQL。
- 公司 SQL 合同一字不动：仍只导出已发布日报中 `adoption_status=2`、
  `generation_status=ready`、`generated_by` 非 `rule_v1` 的条目，category 只认
  10 类，`content_json` 只含五段字段。
- 业务板块只存在于 `insight_json.board` 和格式分组里，**永不写入
  `generated_news.category` 或 SQL category**。

## 3. 数据模型

### 3.1 `report_formats`（格式注册表）

| 字段 | 说明 |
|---|---|
| workspace_code | 所属工作台 |
| format_code | 工作台内唯一，如 `company_sql_v1` / `tech_insight_v1` / 自定义 |
| name / description | 展示名与说明 |
| builtin / locked | 内置格式标记；locked=true 时结构不可改、不可删（company_sql_v1） |
| group_by | `category`（十分类）\| `board`（业务板块）\| `none`（平铺） |
| headline_enabled / headline_auto_top_n | 头条区开关与自动条数（默认 6） |
| item_fields | 有序字段清单，可选值：`tag_line`（标签行）、`bullet_points`（📋要点）、`takeaway`（📌总结）、`five_fields`（五段正文）、`summary`、`source_link`、`score` |
| export_targets | `[]` \| `["md"]` \| `["md","html"]`（SQL 导出不在此配置，仍走原出口） |
| enabled / sort_order | 启用与排序 |
| generation_template / generation_template_source | 自定义格式的生成模板（规范形 + 上传原文，nullable；内置格式恒 null）——设计已定稿待实现，见 §10 |

内置种子（每个工作台自动注册）：

| format_code | group_by | 头条区 | item_fields | export |
|---|---|---|---|---|
| `company_sql_v1`（locked） | category | 关 | five_fields | —（走公司 SQL） |
| `tech_insight_v1` | board | 开，auto 6 | tag_line, bullet_points, takeaway, source_link | md + html |

### 3.2 `report_renditions`

| 字段 | 说明 |
|---|---|
| report_type / report_id | `daily` \| `weekly` + 对应报告 id |
| format_code | 引用格式注册表 |
| status | `draft` / `ready`；报告 publish 时全部 rendition 定稿 |
| title / summary_json | 标题、开头摘要块（板块分布、头条摘要、关键亮点、summary_text，对齐快报头部） |
| body_json | 渲染后的结构化正文（分组 → 条目 id 顺序 → 每条选用字段的快照） |
| generated_at / generated_by | 生成时间与方式（model / rule_fallback） |

唯一键：`(report_type, report_id, format_code)`。重生成 = 覆盖同键 rendition。

### 3.3 既有表的增量

- `generated_news.insight_json`（新 JSON 列）：`board`（14 板块之一）、
  `bullet_points[]`（📋要点，3-5 条）、`takeaway`（📌总结一段）、`tag_line[]`
  （【板块】【主体】【方向】【价值】标签）。**独立于 content_json**，SQL 导出不读。
- `daily_report_items.is_headline`（bool）：日报草稿生成时按推荐分 Top6 初始化，
  编审页可勾选/取消；仅 headline_enabled 的格式使用。

### 3.4 板块 taxonomy

新增 `config/taxonomy/business_boards.json`：14 个启用板块（源自 Tech Insight Loop
`business_board_rules`），含每板块的 `suggested_categories`（板块→十分类的映射建
议，来自融合方案 §6），供生成兜底和覆盖分析使用。

## 4. 生成链路扩展

1. MiniMax prompt v2：在现有五段 + category 输出之外，额外要求输出
   `board / bullet_points / takeaway / tag_line`，写入 `insight_json`。
   现有五段结构和 category 约束不变，SQL 兼容性零影响。
2. 规则降级（未配 MiniMax key 或生成失败）：
   - `board`：按来源 `board_relevance_json` 最高项，缺省按 category 反查
     `business_boards.json` 的映射。
   - `bullet_points`：eventSummary + technologyAndInnovation 切分。
   - `takeaway`：valueAndImpact（缺省 effects）。
   - `tag_line`：板块 + 一级分类 + 专家路由首项。
3. rendition 渲染是纯投影：读采信条目 + insight_json + 格式配置，产出 body_json；
   不回写任何生成稿字段。
4. 周报摘要段 v1：后端按当前周报采信/候选条目生成 `weekly_reports.summary`，并在
   `report_renditions.summary_json` 中写入 `summary_text`、`key_highlights`、
   `top_groups` 和 `summary_generated_by=rule_weekly_summary_v1`。这是一条稳定的规则投影，
   不是前端拼文案；后续 LLM 周报摘要模型必须复用同一字段结构。

## 5. 导出

- Markdown：对齐 `周报文件/技术洞察日报-*.md` 结构——标题/覆盖周期头部、
  `:::summary` 摘要块（摘要、板块分布、关键亮点、头条摘要）、`## 今日头条` 锚点列表、
  按板块 `##` 分组、每条 `###` 标题 + 标签行 + 📋要点 + 📌总结 + 来源链接。
- HTML：复刻同目录 `.html` 的版式（自包含单文件，便于内网直挂）。
- 出口：`GET /api/reports/{report_id}/renditions/{format_code}/export?target=md|html`，
  同时落 `outputs/renditions/`（不进 Git）。公司 SQL 出口不变。

## 6. API

```text
GET    /api/report-formats?workspace_code=...
POST   /api/report-formats                      （super_admin；builtin 不可建同名）
PATCH  /api/report-formats/{id}                 （locked 格式仅允许 enabled 开关）
DELETE /api/report-formats/{id}                 （builtin 禁删）

GET    /api/daily-reports/{id}/renditions
POST   /api/daily-reports/{id}/renditions/{format_code}/regenerate
GET    /api/reports/{report_id}/renditions/{format_code}/export?target=md|html

PATCH  /api/daily-report-items/{id}             （增加 is_headline）
```

## 7. UI

- 日报编审页：顶部增加成稿切换 tab（内网版 / 技术洞察版 / 自定义格式…）。
  - 内网版视图 = 现状（十分类平铺，五段正文）。
  - 技术洞察版视图 = 头条区置顶（可勾选调整）+ 按板块分组 + 要点/总结排版。
  - 采信/剔除/编辑操作在两个视图共享，改一处两版联动。
  - 「导出 MD / 导出 HTML」按钮在技术洞察视图出现。
- 格式管理：不新增导航页（遵守"配置类不加页面"规则），入口放日报编审页
  「格式」按钮 → 玻璃滑出面板：格式列表、启停、新建自定义格式（分组维度/字段/
  头条区/导出目标）。
- 周报编审：第二阶段按同一机制接入（快报周报同构）。

## 8. 分阶段实施

| 阶段 | 内容 | 交付判定 |
|---|---|---|
| P1 后端骨架 | business_boards taxonomy、insight_json + is_headline 模型、格式注册表模型/种子/API、rendition 生成（规则降级路径）、MD 导出 | pytest 全绿；对已导入的演示周数据能生成技术洞察版 MD，结构对齐样例文件 |
| P2 编审体验 | 编审页双版 tab、头条勾选、HTML 导出 | 两版在页面可切换阅读，导出 HTML 可直接内网挂载 |
| P3 自定义格式 | 格式管理面板（新建/编辑/启停自定义格式） | 不改代码注册第三种格式并出稿 |
| P4 周报 + 生成升级 | 周报双版；配 MiniMax key 后 insight 字段切换为模型产出；周报摘要段先走 `rule_weekly_summary_v1`，后续可替换为模型摘要 | 周报双版可导出；模型产出的要点/总结质量对齐快报；摘要字段结构保持兼容 |

## 9. 风险与控制

| 风险 | 控制 |
|---|---|
| 未配 MiniMax key 时要点/总结文风偏机械 | 规则降级只作过渡，P4 切模型产出；rendition 标记 generated_by 供识别 |
| 板块判定质量 | 优先用源侧 board_relevance 先验；编审页允许改条目板块（存 insight_json，不碰 category） |
| 格式注册表被配坏 | company_sql_v1 locked；导出目标只影响 MD/HTML，SQL 出口硬编码走原链路 |
| 双版信息不同步 | rendition 是投影不是副本；重生成幂等，publish 时统一定稿 |

## 10. generation_template 模板驱动生成（设计已定稿待实现，2026-07-07）

事实源级规则（数据流位点、投影/生成判定、company_sql_v1 不变式）见
`docs/backend/reports-editorial-design.md` §8.1；本节是实现级细节。契约：
`config/contracts/report_renditions.json` `generation_template`。

### 10.1 数据模型增量

- `report_formats.generation_template`（JSON 列，nullable）：解析后的模板
  规范形（canonical form）。内置格式恒为 null。
- `report_formats.generation_template_source`（TEXT，nullable）：用户上传原文
  （JSON 或 XML），仅用于回显编辑，运行时只读规范形。
- `generated_news.template_extras_json`（JSON 列，默认 `{}`）：按 format_code
  分桶的增量字段产出：

```json
{
  "exec_brief_v1": {
    "values": { "one_liner": "……", "risk_flags": ["……"] },
    "generated_by": "minimax:MiniMax-M2.7-highspeed",
    "generated_at": "2026-07-07T12:03:00+08:00",
    "template_version": 3
  }
}
```

### 10.2 模板规范形 schema

```json
{
  "carrier": "json",
  "version": 3,
  "item_schema": {
    "fields": [
      {
        "key": "one_liner",
        "label": "一句话结论",
        "type": "string",
        "required": true,
        "max_length": 80,
        "map_from": null,
        "example": "X 公司开源 Y 推理框架，单卡吞吐提升。",
        "guidance": "面向高管的一句话，不带技术细节"
      },
      {
        "key": "background",
        "label": "背景",
        "type": "text",
        "required": true,
        "max_length": 2000,
        "map_from": "content_json.background",
        "example": "……"
      }
    ]
  }
}
```

字段约束（上传时逐条校验，违规 422 并逐条报错）：

| 约束 | 规则 |
|---|---|
| `carrier` | `json` \| `xml`；XML 上传解析为同一规范形后按 JSON 存储（见 10.3） |
| `fields[].key` | `^[a-z][a-z0-9_]*$`，模板内唯一，≤32 字符，最多 24 个字段 |
| `fields[].type` | `string`（≤500 单行）\| `text`（多行）\| `string_list`（元素 ≤200，最多 10 条）\| `url` |
| `fields[].max_length` | 1..4000；`required` 缺省 false |
| `fields[].map_from` | null 或基稿字段超集路径之一：`title` / `summary` / `key_points` / `category` / `content_json.background|effects|eventSummary|technologyAndInnovation|valueAndImpact` / `insight_json.board|bullet_points|takeaway|tag_line` / `source_link` / `published_at` / `score` |
| 模板总大小 | 规范形序列化 ≤ 32KB，`example/guidance/label` 不得含 `<script`/`<style`/HTML 标签 |
| `version` | 服务端维护的自增整数，每次 PATCH 模板 +1，用于 extras 失效判断 |

投影/生成判定（确定性算法，实现必须与此逐条一致）：

```text
对模板每个 field：
  map_from 非空                      -> 投影字段（从基稿超集取值）
  map_from 为空且 key 命中超集路径尾名 -> 投影字段（隐式映射，如 key=summary）
  其余                              -> 增量字段（追加生成）
增量字段集合为空 -> 该格式是纯投影格式，零额外模型调用
```

### 10.3 XML 载体

- 目的：兼容旧系统"XML 板式"心智；能力与 JSON 载体一一等价，不多不少。
- 上传时用禁 DTD/禁外部实体/禁实体展开的安全解析器解析（defusedxml 语义），
  解析失败或含 DTD/PI 一律 422。
- 结构约定：`<template version=""><item><field key="" type="" required=""
  max-length="" map-from=""><label/><example/><guidance/></field>…</item></template>`；
  解析后转 10.2 规范形存储，`generation_template_source` 保留原文。
- 运行时（生成/投影/校验）只读规范形，不存在"XML 分支逻辑"。

### 10.4 生成与投影链路

1. 增量生成时机：daily pipeline 的 generation step 在产出基稿后，对该工作台
   `enabled=true` 且含增量字段的格式逐一追加生成；rendition
   `regenerate` 时对缺失/过期（`template_version` 落后）的 extras 惰性补齐。
2. 增量生成 prompt：复用 `_build_user_prompt` 的 JSON-in-JSON 风格，把模板
   字段的 `key/label/type/max_length/required/example/guidance` 作为
   `outputSchema` 数据传入，来源仍是同一 news_item + 基稿；模型输出按模板
   逐字段校验（类型/长度/required），不合格字段按 `map_from` 兜底或置空。
   现有 `_passes_generation_quality`、category、insight 校验不因模板放宽。
3. 预算与降级：增量生成调用计入工作台 `generation_policy.daily_generation_budget`
   （见 `docs/backend/generation-provider-design.md` §3.2）；provider 不可用/
   超时/预算尽 → extras 缺失，body_json 条目标记
   `"template_fallback": true, "missing_fields": [...]`，投影不阻塞。
4. 投影：rendition 渲染读采信条目 + 基稿 + `template_extras_json[format_code]`
   + 模板字段顺序产出 body_json；带模板的格式其 `item_fields` 由模板字段序
   派生，MD/HTML 导出按模板 label 渲染小节。
5. 编辑覆盖优先级不变：`editor override -> template_extras/generated_news ->
   news_items`；编辑覆盖仍只写 `daily_report_items.editor_*`，不写 extras。

### 10.5 API 增量

```text
POST  /api/report-formats                      # body 增加 generation_template（json 或 xml 原文 + carrier）
PATCH /api/report-formats/{id}                 # 同上；locked/builtin 格式提交模板一律 400
POST  /api/report-formats/validate-template    # 干跑校验 + 示例预览（workspace admin+）
```

`validate-template` 行为：不落库；返回
`{valid, errors[], normalized_template, projection_fields[], generated_fields[],
preview_item}`，其中 `preview_item` 用一条内置示例基稿按模板投影出的样例条目
（增量字段填 example 值），供上传界面所见即所得预览。

### 10.6 安全边界

- 模板是纯声明式数据：渲染层只做字段投影，**不做任何模板字符串求值**
  （无 Jinja/Liquid/eval 语义），MD/HTML 导出对模板 label/值统一转义。
- 模板不含可执行内容：上传校验拒绝 script/style/HTML 标签与超长字段；
  XML 走安全解析（10.3）。
- prompt 注入控制：模板文本以 JSON 数据字段进入 prompt（不拼接进系统指令），
  模型输出仍过逐字段 schema 校验和既有质量门禁。
- 增量字段永不进入：`content_json`、`insight_json`、`generated_news.category`、
  公司 SQL、dedupe/推荐输入。

### 10.7 验收标准（可执行断言级）

1. 注册含 `map_from` 全覆盖字段的自定义格式：生成 step 零额外模型调用
   （fixture provider 断言调用次数不变），rendition body_json 按模板字段序投影。
2. 注册含 1 个增量字段（如 `one_liner`）的格式：pipeline 后
   `generated_news.template_extras_json[format_code].values.one_liner` 存在，
   rendition/MD/HTML 展示该字段；`content_json`、`insight_json`、`category`
   与不带模板时逐字节一致。
3. 同一模板 XML 载体与 JSON 载体上传后规范形完全相等（canonical JSON 相等断言）；
   含 DTD/外部实体的 XML 422。
4. 非法模板逐条报错：重复 key、`key=1abc`、`type=script`、字段 >24、
   `example` 含 `<script>` 均 422 且错误定位到字段。
5. `validate-template` 不写任何表（前后行数断言），返回
   projection/generated 字段划分和 preview_item。
6. locked（company_sql_v1）与 builtin（tech_insight_v1）提交
   `generation_template` 返回 400；两者行为回归测试不变。
7. provider 关闭时带增量字段的格式：rendition 照常产出，条目带
   `template_fallback=true`；开启 provider 后 `regenerate` 补齐 extras 且
   `adoption_status`、`is_headline` 不变（投影不变式回归）。
8. 模板 PATCH 后 `version+1`，旧 extras 判定过期，`regenerate` 按新模板重生；
   删除该格式不影响采信与其他格式（现有 rendition 不变式回归）。
9. 周报：`report_type=weekly` 的模板格式跑通 2/7 两条断言（同机制）。
10. 全程 `scripts/validate_company_sql.py` 基准通过；模板任何配置组合下
    公司 SQL 导出输出与无模板时逐字节一致。
