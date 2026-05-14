# InfoWatchtower 总纲

本文档是 InfoWatchtower 的唯一总纲。任何工程师或 AI 接手时，先读本文；写代码时遵守 `config/contracts/*.json` 和 `config/taxonomy/*.json`。其他 `docs/*.md` 只是专题附录。

如果只能读一个文档，读本文。

## 1. 产品定位

InfoWatchtower 是规划部的产业情报操作系统，不是单纯新闻站，也不是只服务 AI 板块的日报工具。

它要持续接入外部公开信息、内部补充信息和未来公司内网源，把原始信号保存下来，统一成可去重、可推荐、可编辑、可追溯的情报对象，再沉淀成日报、周报、专题、洞察、内部需求和指派任务。

第一阶段从 AI 板块和公司内部 SQL 导出切入，但底层必须支持后续扩展到硬件、半导体、云基础设施、机器人、政策市场、竞品生态等板块。

长期工作闭环：

```text
外部信号
-> 标准化新闻/情报
-> 去重推荐
-> 编辑判断
-> 洞察 insight
-> 战略含义 implication
-> 机会/风险 opportunity_or_risk
-> 内部需求 requirement
-> 指派任务 task
-> 用户反馈反哺来源和推荐
```

## 2. 当前仓库状态

当前仓库已完成阶段 0-6 可回填闭环。阶段 3 完成旧种子源导入、共享数据源池、默认工作台源链接、工作台统一标签策略、adapter 框架、RSS/paper RSS/页面源抓取到 `raw_items`、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口。阶段 4 已完成 `raw_items -> news_items -> dedupe_groups`：`POST /api/news-items/normalize` 可按工作台把已启用源的 raw 标准化成 news，生成 canonical URL、normalized title 和 dedupe key，并按工作台隔离重建硬去重组；`GET /api/news-items` 与 `GET /api/dedupe-groups` 可验收 winner/loser 和追溯 ID。阶段 5 已完成 `POST /api/pipeline/daily-runs`、`POST /api/recommendation/runs`、`GET /api/daily-reports`、日报发布、日报条目编辑和点赞/评分/评论最小 API；推荐按 `day_key` 只选目标日 winner，`planning_intel` 默认采用技术情报优先策略，优先论文、研究机构、AI 软件、AI 基础设施、模型工程、推理/训练、RAG、多智能体、Agent 记忆和工程实践，降权融资、财报、宏观产业收入数据、传闻曝光、消费硬件和泛商业市场新闻。`generated_news` 可通过旧参考脚本已验证的 MiniMax 中国区 OpenAI-compatible `chat/completions` 生成；未启用或失败时只生成 `rule_v1:fallback` 草稿并标记 `fallback_needs_review`，不能直接进入标准公司 SQL。阶段 6 已完成标准公司 SQL 导出：已发布日报中 `adoption_status = 2` 且 `generated_news.generation_status = ready`、`generated_by` 非 `rule_v1` 的条目会写出旧系统兼容的 4 表 SQL，`content_json` 只保留五段旧字段，`ai_journal.source_title/content` 导出前清洗为纯文本，原始 HTML 保留在 `raw_items` 追溯层。`planning_intel` 成品新闻一级标签和公司 SQL category 仍使用旧系统约定的 10 个 AI 标签，来源为 `config/taxonomy/news_categories.json`；`config/taxonomy/source_tags.json` 只作为数据源侧方向标签，用于源管理、覆盖分析和评分先验，不写入 `generated_news.category`。前端 `/daily-reports` 可按日期触发完整流水线并查看日报草稿。scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿；如需旧行为可设置 `SCHEDULER_JOB_MODE=ingestion_only`。`planning_intel` 和 `ai_tools` 的默认标签策略已在后端隔离。下一步进入内容准入层、事件聚类、抓取覆盖率/历史补采、公网/内网同步骨架和部署硬化。

工作台级抓取已经支持并发池和单源超时：默认 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`，API 可用 `concurrency` 和 `source_timeout_seconds` 覆盖。这样几百个数据源不会因为少数慢源被串行阻塞，抓取结果仍按源顺序串行入库，保留幂等写入和运行摘要。

文档维护规则见 `docs/README.md`。修改设计时必须同步总纲、对应模块文档和相关 `config/contracts/*.json`，不要形成两套实现口径。

仓库分层：

```text
config/
  contracts/             机器可读契约
  domain_packs/          后续板块扩展配置包
  seeds/legacy/          旧系统种子源，可导入新系统
  taxonomy/              新闻一级标签、数据源方向标签与长期产业情报板块
docs/
  00-system-design.md    唯一总纲
  *.md                   专题附录
references/
  README.md              私有参考仓拉取说明
```

旧 `.env` 已复制到本地 `config/.env`，但被 `.gitignore` 忽略，不提交 Git。

### 2.1 当前已验证输出

当前本地库已经能生成规划部工作台的日报草稿、发布日报并导出公司 SQL 预览。已验证过的本地输出包括：

- `2026-04-30` 单日日报与公司 SQL 预览。
- `2026-05-01` 到 `2026-05-07` 批量日报与合并 SQL 预览。
- 生成稿字段固定为 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact`。
- SQL 导出每条采信新闻固定生成 `ai_journal`、`ai_journal_focus`、`ai_journal_analysis`、`t_news_data_info` 四类语句，category 写入 `generated_news.category`，即规划部 AI 十分类。
- 导出的 `focus_id` 第一版默认 `1`，`adoption_status` 默认 `2`，日期按日报 `day_key` 对齐。
- 导出前会清洗 `ai_journal.source_title/content` 的 HTML；原始 HTML 仍保留在 `raw_items` 追溯层。
- SQL 文件头统一为 `InfoWatchtower Company SQL Preview`；所有预览 SQL 导入内网前必须运行 `python3 scripts/validate_company_sql.py`，该脚本以 `2026-05-05` 预览为基准逐字段校验。

本地 SQL 预览文件放在 `outputs/sql/previews/`，该目录被 `.gitignore` 忽略，不随主仓提交。主仓只提交生成逻辑、字段契约和文档。

### 2.2 当前明确缺口

“规划部工作台全量启用 294 个共享源”和“某一天有多少候选”不是同一个指标。候选数量经过这些过滤：

```text
工作台启用源
-> 抓取成功
-> feed 当前窗口里有条目
-> 条目发布时间落在目标 day_key
-> raw 标准化成 news
-> 去重后保留 active winner
-> 推荐层选择
```

因此，如果某天只有少量候选，首先要排查抓取覆盖率、失败源、源本身是否当天发布、RSS 是否保留历史条目，以及历史补采是否可用，而不是直接归因于推荐器漏选。

下一阶段必须补齐：

- 抓取覆盖率看板：展示启用源数、成功源数、失败源数、每源 raw 新增/更新数量、失败原因和最近成功时间。
- 历史补采/backfill：针对 RSS 当前窗口之外的日期，补页面归档、API 或专用 crawler；不能假设今天拉一次 RSS 就能还原过去所有日期。
- 历史补采优先级：先做论文/API 类可按日期回查的源，再做厂商技术博客归档页和 sitemap，最后做通用网页搜索/手工 CSV 补录。补采 run 必须写入 `ingestion_runs`，并在参数中记录 `target_day_start/target_day_end/backfill_mode`，方便解释“某天为什么少”和回放同一补采任务。
- 候选池前端：当前已展示去重 winner、loser 和来源覆盖；下一步补推荐分、日报采信状态和完整追溯。
- SQL 导出前端页：当前已支持选择已发布日报、查看导出历史、预览和下载 SQL；下一步补复制、字段校验和 SQL 条目级追溯。
- 公网/内网同步骨架、部署硬化、备份恢复和登录安全加固。

## 3. 第一版范围

第一版必须跑通：

- 公网账号密码登录。
- 内网可信 header 登录预留。
- 旧种子源导入。
- RSS 抓取。
- raw 原始数据入库。
- `news_items` 标准化。
- URL/标题日期去重。
- 推荐评分。
- 日报草稿。
- 管理员采信、编辑、发布。
- 点赞、评分、评论。
- 公司 SQL 导出。
- 最小 insight / requirement / task 闭环。
- 单台服务器 Docker Compose 部署。

第一版可以只做骨架或轻实现：

- wiseflow adapter。
- 页面监控 adapter 的深度抽取和增量差异识别。
- 论文 API / 论文页面源。
- 周报自动生成。
- 多环境同步。
- domain pack 扩展。

这些骨架必须预留，不能把系统写死成 RSS + AI 日报。

## 4. 技术选型

定稿选型：

- 后端：Python FastAPI。
- 数据库：PostgreSQL。
- ORM / 迁移：SQLAlchemy + Alembic。
- 前端：Vue 3 + TypeScript + Vite。
- 部署：单仓 monorepo + Docker Compose。
- 后台任务：第一版可用 APScheduler 或 RQ/Celery + Redis。

建议代码目录：

```text
backend/
  app/
    adapters/
    auth/
    core/
    dedupe/
    exports/
    ingestion/
    models/
    reports/
    scoring/
    workers/
  alembic/
  tests/
frontend/
  src/
deploy/
  docker-compose.prod.yml
  Caddyfile or nginx.conf
```

## 5. 主数据流

统一主链路：

```text
data_sources 共享源池
-> workspace_source_links 工作台启用和配置
-> SourceAdapter.fetch()
-> raw_items
-> content extraction
-> news_items
-> dedupe_groups / dedupe_group_items
-> candidate pool
-> recommendation_runs / recommendation_items
-> generated_news
-> daily_reports / daily_report_items
-> feedback / comments / ratings
-> insights / requirements / tasks
-> company SQL export
```

关键原则：

- adapter 只负责接入和保存原始数据，不做最终推荐和日报采信。
- 原始 payload 必须完整进入 `raw_items.raw_payload_json`。
- 去重在 `news_items` 之后、推荐之前。
- `dedupe_groups` 按 `workspace_code + dedupe_key` 隔离；同一条共享 raw 可以被不同工作台各自标准化和去重。
- 候选池是去重后的代表项工作池，不是新数据源，也不是日报。
- 推荐只处理去重 winner。
- 日报编辑不覆盖 `raw_items` 和 `generated_news`，只写报告层 editor override。
- 标准公司 SQL 只导出已发布日报中 `daily_report_items.adoption_status = 2` 的条目。
- 任意内部需求必须能追溯回触发它的外部原始信号。

## 6. 核心对象

核心表族：

```text
workspaces / workspace_sections / workspace_memberships
data_sources / workspace_source_links
label_sets / labels / content_labels
raw_items
news_items
dedupe_groups / dedupe_group_items
recommendation_runs / recommendation_items
generated_news
daily_reports / daily_report_items
weekly_reports / weekly_report_items
reactions / ratings / comments / editorial_actions
insights / strategic_implications / requirements / topic_tasks
export_jobs / export_job_items
users / roles / permissions / audit_logs
```

支持长期扩展的核心横切字段：

```text
workspace_code          所属工作台，如 planning_intel
domain_code             所属板块，如 ai/hardware/semiconductor
visibility_scope        public/internal/restricted
sync_policy             none/public_to_intranet/two_way_config/manual_only
global_id               跨环境同步稳定 ID
origin_instance_id      首次创建实例
revision/content_hash   同步和冲突处理
```

工作台、板块、模块和数据源共享是四个不同概念：

```text
workspace_code          选择工作范围和权限边界
section_key/module_key  数据库注册的核心页面或可选插件页面
domain_code             选择情报内容的主题板块
data_sources            全局共享源池
workspace_source_links  某工作台启用了哪些共享源以及如何配置
```

示例：

- 工作台列表来自 `workspaces`，不是前端写死。
- 工作台页面来自 `workspace_sections`，默认只启用数据源管理、候选池、日报、周报、SQL 导出、用户权限、审计。
- 多个工作台可以复用同一个 RSS、wiseflow 或论文源；复用关系写在 `workspace_source_links`。
- 每个工作台的数据源管理页配置工作台统一一级/二级标签策略；单个源只配置启用、权重、日限和抓取相关信息。
- `domain_code=ai` 和 `domain_code=hardware` 是内容板块，不是工作台。

规则：

- 不要把 `domain_code` 当成 UI 工作台边界。
- 不要为了任何新工作台另起一个前后端仓库。
- 不要给每个工作台复制一套数据源或标签结构。
- 不要默认显示工具目录、工具任务或独立热点专题页面；这些只有在 `workspace_sections.enabled=true` 后才可出现。
- 第一版的“工具目录”含义由一级/二级标题配置承担，不新增工具管理页面。
- 新工作范围走 `workspaces`；共享源复用走 `workspace_source_links`；新主题板块走 domain pack；新标签体系走 `label_sets`。

最小追溯链路：

```text
daily_report_items
-> generated_news
-> recommendation_items
-> dedupe_group_items
-> news_items
-> raw_items
-> data_sources
```

战略闭环追溯：

```text
requirements
-> strategic_implications
-> insights
-> news_items
-> raw_items
```

## 7. Adapter 契约

每种数据源通过 adapter 接入。第一版源类型：

```text
wiseflow
rss
paper_rss
page_monitor
page_manual
crawler
paper_api
paper_page
manual
internal
```

每条进入系统的原始记录，adapter 至少输出：

```text
data_source_id
domain_code
visibility_scope
sync_policy
source_type
source_name
entry_key
source_title
fetched_at
raw_payload_json
```

进入去重推荐链路时，`news_items` 至少满足：

```text
source_url / canonical_url
```

或：

```text
source_title + published_at/created_at
```

缺 URL、标题和时间的记录只能进入 `raw_items`，不能进入推荐。

## 8. 去重与推荐

第一版只做保守硬去重：

- 有 URL 时：`dedupe_key = "url:" + canonical_url`。
- 无 URL 时：`dedupe_key = "title:" + normalized_title + "|date:" + yyyy-mm-dd`。

canonical URL 规则：

- scheme 和 host 小写。
- 去掉 fragment。
- path 去掉末尾 `/`。
- 去掉 `utm_*`、`spm`、`ref`、`ref_src`、`fbclid`、`gclid` 等追踪参数。

winner 选择顺序：

1. 有 URL。
2. wiseflow legacy bonus。
3. 官方源/可信源。
4. 正文更完整。
5. 发布时间更新。

当前实现 API：

```text
POST /api/news-items/normalize
GET  /api/news-items
GET  /api/dedupe-groups
```

推荐分数必须可解释：

```text
quality_score
topic_score
freshness_score
feedback_score
diversity_score
source_score
heat_score
final_score
recommendation_reason
```

`planning_intel` 的默认推荐口径是“AI 技术能力和 AI 工程能力优先”，不是商业资讯优先。推荐层先做内容准入，再做日报选择：

- P0/P1：强相关技术信号，优先进入日报。
- P2：中价值观察信号，可在日报预算未满时进入，也可用于周报/观察池。
- P3：低价值或背景信息，默认只检索可见。
- R：噪声或离题内容，默认不进入日报。

评分会提升 AI 软件与基础设施、模型工程、推理/训练、RAG、多智能体、Agent 记忆、评测基准、开源框架、硬件厂商技术路线、友商技术动态、AI 芯片、GPU 集群、数据中心架构、通信系统和标准进展等信号。数据源侧方向标签只能作为弱先验，不能因为“这个源是厂商源/硬件源”就直接入日报；单条内容仍必须出现架构、推理、模型服务、芯片、数据中心、通信系统、标准或工程实现证据。融资、财报、股价、采购/中标/集采、消费硬件、活动预告、宣传推广会/品牌行动、泛商业合作、纯营销、航天火箭等离题工程新闻、纯市场新闻、法律/版权元讨论、标题党、社会/教育离题内容和离题生物医学/纯学术论文默认降权。日报选择还会限制单源、论文源（默认约 10%）和单一内容池的占比，`P2` 只作为无噪声且有明确技术信号的补位项，`P2 paper_rss` 默认不进入日报，避免内容被某一类来源刷屏。用户反馈和管理员采信后续仍可反哺 `heat_score/feedback_score/source_score`。

## 9. 分类与板块扩展

`planning_intel` 当前成品新闻一级标签必须沿用旧系统约定的 AI 十分类，来源是 `config/taxonomy/news_categories.json`。这 10 个标签进入模型生成稿 `generated_news.category`、日报展示和公司 SQL category。

新的方向/板块标签只在数据源侧使用，来源是 `config/taxonomy/source_tags.json`。它们用于描述一个信息源可能覆盖哪些方向，服务于源过滤、覆盖分析、推荐先验和后续内容准入，但不能替代成品新闻一级标签。长期领域扩展由 `config/taxonomy/intelligence_domains.json` 和 domain pack 承载：

```text
config/domain_packs/{domain_code}/
  sources.json
  taxonomy.json
  scoring.json
  report_templates.json
  export_mapping.json
```

新增硬件、半导体、政策、竞品板块时，加 domain pack，不改主链路。

每个 `data_sources`、`raw_items`、`news_items` 都必须带 `domain_code`。旧系统导入默认 `domain_code = ai`。

## 10. 登录与权限

公网和内网共用一套本地用户、角色、权限和审计模型。外部认证只证明“这个人是谁”，InfoWatchtower 的 RBAC 决定“这个人能做什么”。

第一版认证模式：

```text
local
public_password
intranet_header
```

统一流程：

```text
AuthAdapter
-> ExternalIdentity
-> IdentityResolver
-> users
-> session/JWT
-> RBAC
```

公网默认：

```text
AUTH_MODE=public_password
AUTH_AUTO_PROVISION=false
```

内网快速接入：

```text
AUTH_MODE=intranet_header
AUTH_HEADER_EMPLOYEE_NO=X-Employee-No
AUTH_HEADER_DISPLAY_NAME=X-Employee-Name
AUTH_AUTO_PROVISION=true
```

`intranet_header` 只能部署在可信网关后面，后端不能被用户绕过网关直接访问。

## 11. 部署与同步

第一版推荐单台服务器 Docker Compose：

```text
reverse_proxy
frontend static files
backend FastAPI
worker
scheduler
postgres
redis
```

数据库不放 GitHub。单机部署时 PostgreSQL 数据在服务器磁盘或 Docker volume，例如：

```text
/srv/infowatchtower/postgres_data
```

默认不暴露数据库端口。公网只开放：

```text
22 / 80 / 443
```

公网和内网不分叉代码，差异通过 `.env.production`、`AUTH_MODE`、域名、密钥和同步开关控制。

长期两库方案：

```text
public DB      公开信息采集、raw/news/recommendation
intranet DB    内部用户、评论、采信、需求、任务、公司 SQL 导出
```

推荐应用层 outbox/inbox 同步，不做混乱双写。公网可以向内网同步公开信号；内网用户、评论、需求、任务默认不回流公网。

同步前必须检查 `visibility_scope` 和 `sync_policy`。密钥、token、cookie 只允许用 `credential_ref` 引用，不进入同步包和 Git。

## 12. 公司 SQL 导出

标准导出范围：

```text
daily_reports.status = published
daily_report_items.adoption_status = 2
```

每条日报新闻固定导出 4 条 SQL，顺序不可变：

1. `ai_journal`
2. `ai_journal_focus`
3. `ai_journal_analysis`
4. `t_news_data_info`

字段映射以 `config/contracts/news_sql_mapping.json` 为准。标准模式 `export_category_mode = news_primary`，`ai_journal_analysis.category` 与 `t_news_data_info.category` 直接使用 `generated_news.category`，而 `planning_intel` 的 `generated_news.category` 必须属于旧系统约定的 10 个 AI 一级标签。

当前实现入口是 `backend/app/exports/company_sql.py` 和
`POST /api/exports/company-sql/daily-reports/{daily_report_id}`。导出前必须发布日报；导出时可使用日报编辑层覆盖标题、摘要、关键词和五段正文，但公司 SQL 的 `content_json` 只包含旧系统五段正文，不包含 InfoWatchtower 自己的追溯字段。

日期字段是内网导入硬契约。`ai_journal.created_at` 与
`ai_journal_analysis.created_at` 必须保留旧系统同款列顺序和日期字面量样式，输出为
`'YYYY-MM-DD HH:MM:SS'`。优先使用原始发布时间；如果来源缺失发布时间，标准日报 SQL
导出兜底为 `daily_reports.day_key 09:00:00`，不写 `NULL`。不要改成
`STR_TO_DATE(...)`、`CAST(...)`，也不要省略 `ai_journal_analysis.created_at`；如果内网前端触发
`.strftime()` 报错，应排查内网表字段类型、ORM 类型和导入后实际行值，而不是擅自改变 SQL 导出契约。

导出到 `ai_journal.source_title` 和 `ai_journal.content` 前必须做纯文本清洗，去除 HTML 标签和 script/style 内容；`raw_items.raw_payload_json` 与 `raw_items.raw_content` 仍保留原始抓取内容，用于回溯和重新处理。

## 13. 旧系统事实

当前已归档的旧系统事实：

- Wiseflow 原始源：1 个。
- RSS 源：108 个，其中 74 个启用、34 个停用。
- 页面源：4 个。
- 合并索引：113 个。
- 论文 RSS 源：17 个，其中 14 个启用。
- 用户补充信息源台账：`config/seeds/legacy/source_catalog/information_source_registry_20260511.csv`，351 行，其中 248 条标准 RSS 记录可导入。
- 当前导入器合并旧种子和补充台账后处理 361 条记录，按 URL 去重后形成 294 个共享数据源；规划部工作台 v1 默认全部启用。补充台账里的状态/纳入建议保留在源元数据里做评分先验，不作为初始停用开关。
- 成品新闻一级标签：10 个，见 `config/taxonomy/news_categories.json`。
- 数据源方向标签：见 `config/taxonomy/source_tags.json`，只作为源侧标签化和评分先验。
- 每条公司 SQL 导出新闻固定写 4 类 SQL。

完整旧系统参考资料放在私有仓 `InfoWatchtower-References`，只用于查旧系统事实，不作为新代码运行入口。主仓后续可以公开，私有参考资料不随主仓发布。

## 14. 接下来怎么开发

先读：

1. `docs/implementation-handoff.md`
2. `docs/01-implementation-plan.md`
3. `docs/data-examples.md`
4. `docs/README.md`
5. `config/contracts/*.json`

第一批代码目标：

```text
FastAPI healthz
PostgreSQL + Alembic
users/auth/RBAC
data_sources import
RSS adapter
raw_items/news_items
dedupe
daily report draft
company SQL export
Docker Compose local/prod skeleton
```

## 15. 附录索引

- `docs/implementation-handoff.md`：开发任务书和验收标准。
- `docs/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
- `docs/README.md`：文档地图、单一事实源和修改规则。
- `docs/data-examples.md`：数据流样例。
- `docs/ingestion-adapter-dedup-spec.md`：采集和去重细节。
- `docs/data-format-mapping.md`：三层数据映射和 SQL 映射。
- `docs/data-lineage-and-storage.md`：存储、追溯和审计。
- `docs/api-and-ui-implementation.md`：后端 API、前端页面和验收。
- `docs/auth-unified-login.md`：公网/内网统一登录。
- `docs/deployment-ops.md`：部署、自动发布和备份。
- `docs/multi-environment-sync.md`：多环境与多数据库同步。
- `docs/extension-points.md`：扩展点。
- `docs/feedback-heat-scoring.md`：反馈、热度和来源评分。
- `docs/legacy-system-spec.md`：旧系统关键规格。
- `docs/strategic-intelligence-platform.md`：愿景展开附录。
