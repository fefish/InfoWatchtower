# 报告多版成稿与格式注册表设计（Report Renditions）

状态：P1-P4 已实施（2026-07-02）。机器契约见 `config/contracts/report_renditions.json`。
P4 的模型产出（insight prompt v2）已随生成链路接入，配置 MiniMax key 后自动生效；
未配 key 时成稿走规则降级并在条目上标注「规则降级稿」。

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
| title / summary_json | 标题、开头摘要块（板块分布、头条摘要、关键亮点，对齐快报头部） |
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
   配置真实 key 后运行 `python3 scripts/validate_minimax_generation_acceptance.py`
   做结构验收；pytest 使用 `--fixture-response-json` 复用同一套断言。
2. 规则降级（未配 MiniMax key 或生成失败）：
   - `board`：按来源 `board_relevance_json` 最高项，缺省按 category 反查
     `business_boards.json` 的映射。
   - `bullet_points`：eventSummary + technologyAndInnovation 切分。
   - `takeaway`：valueAndImpact（缺省 effects）。
   - `tag_line`：板块 + 一级分类 + 专家路由首项。
3. rendition 渲染是纯投影：读采信条目 + insight_json + 格式配置，产出 body_json；
   不回写任何生成稿字段。

## 5. 导出

- Markdown：对齐 `周报文件/技术洞察日报-*.md` 结构——标题/覆盖周期头部、
  `:::summary` 摘要块（板块分布、日报内容、关键亮点）、`## 今日头条` 锚点列表、
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
| P4 周报 + 生成升级 | 周报双版；配 MiniMax key 后 insight 字段切换为模型产出 | 周报双版可导出；`validate_minimax_generation_acceptance.py` 通过；模型产出的要点/总结质量对齐快报 |

## 9. 风险与控制

| 风险 | 控制 |
|---|---|
| 未配 MiniMax key 时要点/总结文风偏机械 | 规则降级只作过渡，P4 切模型产出；rendition 标记 generated_by 供识别 |
| 板块判定质量 | 优先用源侧 board_relevance 先验；编审页允许改条目板块（存 insight_json，不碰 category） |
| 格式注册表被配坏 | company_sql_v1 locked；导出目标只影响 MD/HTML，SQL 出口硬编码走原链路 |
| 双版信息不同步 | rendition 是投影不是副本；重生成幂等，publish 时统一定稿 |
```
