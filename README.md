# InfoWatchtower

规划部全自动热点追踪与情报生产系统。

当前状态：阶段 0-6 已完成可回填闭环。阶段 3 已完成旧种子源导入、补充信息源台账导入、共享数据源池、默认工作台源链接、工作台统一标签策略、adapter 框架、RSS/paper RSS/页面源抓取到 `raw_items`、工作台级 ingestion run API，以及 Redis/RQ worker + scheduler 调度入口；规划部工作台 v1 默认 294 个共享源全部启用。阶段 4 已完成 `raw_items -> news_items -> dedupe_groups`：可按工作台标准化 raw、生成 canonical URL 与 dedupe key、执行工作台隔离硬去重，并查询 winner/loser。阶段 5 已完成完整日报流水线、内容准入等级、可解释推荐分、可选 MiniMax 结构化生成、`generated_news`、日报草稿、发布、日报条目编辑和点赞/评分/评论最小 API；日报评论站内通知、消息页和顶部真实未读数已补最小闭环；`planning_intel` 推荐默认技术情报优先，提升 AI 软件、AI 基础设施、模型工程、推理/训练、Agent、硬件厂商技术路线和通信系统信号，降权泛商业新闻、营销、财报、消费硬件和弱相关内容。阶段 6 已完成已发布日报的公司 SQL 标准导出，导出只取 `adoption_status = 2`、`generation_status = ready` 且非 `rule_v1` 的采信项，`content_json` 只保留旧系统五段字段，`created_at` 使用旧内网可导入的 `'YYYY-MM-DD HH:MM:SS'` 字面量并在缺失发布时间时兜底到日报 `day_key 09:00:00`。所有 SQL 预览必须通过 `scripts/validate_company_sql.py`，0505 预览是字段校验基准。前端已包含浅色工作台壳、数据源管理、候选池、推荐运行、抓取覆盖率、日报、消息通知、SQL 导出和用户权限页面。scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿。`planning_intel` 与 `ai_tools` 的标签策略已在后端隔离。下一步进入候选质量治理、历史补采、周报摘要、通知偏好/@/跨对象协作、公网/内网同步深化和部署硬化。

## 接手入口

任何工程师或 AI 接手时，先读：

1. `AGENTS.md`：开发准则和修改同步规则。
2. `docs/00-system-design.md`：唯一总纲，包含愿景、主链路、扩展方式、部署方向。
3. `docs/implementation/implementation-handoff.md`：第一版开发任务书和验收标准。
4. `docs/implementation/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
5. `docs/README.md`：文档地图和修改规则。
6. `docs/architecture/design-governance.md`：设计分层和新增能力进入开发的门禁。
7. 相关目录的 `README.md`：确认该目录内谁是事实源、谁是附录。
8. `config/contracts/README.md`：解释 contracts 和 AGENTS 的区别。
9. `config/contracts/*.json`：机器可读契约，写代码时必须遵守。

其他设计文档已经按 `docs/architecture/`、`docs/product/`、`docs/backend/`、
`docs/deployment/`、`docs/implementation/`、`docs/reference/` 分层归位，按
`docs/README.md` 的文档地图阅读；`references/legacy-auto-sync-20260412/`
是旧系统参考资料，不是新系统运行入口。

完整旧系统参考资料不提交主仓，放在私有仓 `InfoWatchtower-References`。需要旧资料时看 `references/README.md`。

## 仓库内容

- `config/seeds/legacy/`：新系统可导入的旧种子源。
- `config/taxonomy/`：AI 兼容标签和长期产业情报板块。
- `config/contracts/`：数据源、adapter、SQL、登录、工作台、标签、扩展点、战略闭环、同步策略契约。
- `config/domain_packs/`：后续扩展硬件、半导体、政策、竞品等板块的配置包。
- `docs/`：总纲、文档地图和分层设计文档。
- `references/README.md`：私有参考仓拉取说明。
- `config/env.example`：环境变量样例。
- `docs/deployment/development-quickstart.md`：当前工程骨架的本地启动说明。

本地旧 `.env` 已复制到 `config/.env` 以便复用，但不会进入 Git。

当前种子源统计：旧 113 个种子源 + 补充 CSV 台账 248 条导入记录，按 `source_type + url` 去重后形成 294 个共享源；规划部工作台 v1 默认全部启用。`config/taxonomy/source_tags.json` 是数据源侧方向标签，只用于源管理、覆盖分析和评分先验，不进入成品新闻一级标签或公司 SQL category。

当前数据库骨架：40 张业务表，覆盖用户/RBAC、工作台、共享数据源、标签、raw/news、去重、推荐、日报/周报、互动反馈、SQL 导出、同步回流和战略需求闭环。任意日报条目应能沿外键追回 `raw_items.raw_payload_json`。

当前登录能力：支持 `local/public_password/oidc/intranet_header` 四种入口，统一落到本地 `users` 和 `roles`；合法组合按部署形态由 `config/contracts/deployment_modes.json` 白名单约束。本地 Docker 默认开发账号为 `admin/password`，生产环境必须替换 `AUTH_SESSION_SECRET` 和 `AUTH_BOOTSTRAP_ADMIN_PASSWORD`。

当前工作台模型：工作台列表和页面已由数据库 `workspaces/workspace_sections` 控制；所有工作台复用数据源管理、候选池、日报、周报和导出主链路。工作台自己的 `config_json.label_policy` 是模型生成新闻结构和去重后标签定稿的统一标签策略；`planning_intel` 默认使用旧公司 SQL 的 10 个一级标签，`ai_tools` 默认使用“工具新功能、工具新案例、工具新技术”以及每个一级下的 `cursor/claude code/opencode/codex` 二级标签。`workspace_source_links` 只决定每个工作台如何启用某个共享源，以及该源在当前工作台的权重和日限。

## 当前启动方式

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
DATABASE_URL="" pytest
DATABASE_URL="" uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

更多说明见 `docs/deployment/development-quickstart.md`。

Docker 本地启动：

```bash
make up
```

首次构建或改依赖：

```bash
make build
```

## 当前能力验收

```bash
make test
make migration-check
make build
```

浏览器访问 `http://127.0.0.1:5173/sources`，使用 `admin/password` 登录。验收点：

- 首页显示当前阶段为阶段 5。
- 数据源页标题为“数据源管理”，共享源列表标题为“活跃数据源”。
- 数据源页右侧展示工作台统一标签策略，规划部默认使用旧系统兼容的 10 个一级标签，AI 工具桌面默认使用独立工具标签；一级/二级标签都支持新增、重命名、删除，且不在单个源里维护标签。
- 数据源页每个源都有“配置”入口，可设置当前工作台启用状态、权重和日限；配置开关文案为“启用”。
- 左侧导航来自数据库，不出现工具目录、工具任务或独立热点专题。
- 数据源页显示共享源 294、规划部工作台默认全部启用。
- 数据源列表和右侧标签策略在桌面宽度下不应被横向截断；其他占位页应使用统一内容容器，不出现显示不全。
- 对任意启用的 `rss`、`paper_rss`、`page_manual` 或 `page_monitor` 源点击“抓取”，成功后会提示拉取、新增、更新数量。
- 重复抓取同一个 RSS 源时，`raw_items` 不重复插入，应表现为新增 0、更新大于 0。
- `POST /api/ingestion/runs` 可创建工作台级抓取 run；scheduler/worker 默认关闭，设置 `INGESTION_SCHEDULER_ENABLED=true` 后按环境变量定时执行每日完整流水线。
- `POST /api/news-items/normalize` 可把当前工作台已启用源的 raw 标准化为 news，并重建去重组。
- `GET /api/news-items?workspace_code=planning_intel` 可看到标准化新闻和 `raw_item_id` 追溯 ID。
- `GET /api/dedupe-groups?workspace_code=planning_intel` 可看到去重 winner/loser。
- `/daily-reports` 页面可选择日期并点击“生成日报草稿”，调用 `POST /api/pipeline/daily-runs`，执行抓取、标准化/去重、推荐、结构化稿和日报草稿。
- `/daily-reports` 页面可按日报正文阅读，支持发布、采信/备选/剔除切换、编辑标题/摘要/要点、点赞、评分、评论和查看 raw/news/source 追溯 ID。
- `/exports` 页面可选择已发布日报，生成、预览和下载公司 SQL。
- 所有本地 SQL 预览导入内网前必须通过 `scripts/validate_company_sql.py`；需要统一标题时先运行 `scripts/validate_company_sql.py --fix-headers`。
