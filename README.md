# InfoWatchtower

规划部全自动热点追踪与情报生产系统。

当前状态：阶段 0-6 已完成可回填闭环。阶段 3 已完成旧种子源导入、共享数据源池、默认工作台源链接、工作台统一标签策略、adapter 框架、RSS/paper RSS/页面源抓取到 `raw_items`、工作台级 ingestion run API，以及 Redis/RQ worker + scheduler 调度入口。阶段 4 已完成 `raw_items -> news_items -> dedupe_groups`：可按工作台标准化 raw、生成 canonical URL 与 dedupe key、执行工作台隔离硬去重，并查询 winner/loser。阶段 5 已完成按 `day_key` 的推荐 run、可解释推荐分、可选 MiniMax 结构化生成、`generated_news`、日报草稿、发布、日报条目编辑和点赞/评分/评论最小 API；`planning_intel` 推荐默认技术情报优先，提升论文、研究机构、AI 软件、AI 基础设施、模型工程、推理/训练、RAG、多智能体和 Agent 工程信号，降权泛商业新闻。阶段 6 已完成已发布日报的公司 SQL 标准导出，导出只取 `adoption_status = 2` 的采信项，`content_json` 只保留旧系统五段字段，`ai_journal.source_title/content` 导出前会清洗为纯文本。前端 `/daily-reports` 已可按日期触发完整流水线，并支持日报正文展示、采信切换、编辑、点赞、评分、评论和追溯查看。scheduler 开启后默认执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿。`planning_intel` 与 `ai_tools` 的标签策略已在后端隔离。下一步进入候选池页面、SQL 导出前端页和公网/内网同步骨架。

## 接手入口

任何工程师或 AI 接手时，先读：

1. `AGENTS.md`：开发准则和修改同步规则。
2. `docs/00-system-design.md`：唯一总纲，包含愿景、主链路、扩展方式、部署方向。
3. `docs/implementation-handoff.md`：第一版开发任务书和验收标准。
4. `docs/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
5. `docs/README.md`：文档地图和修改规则。
6. `config/contracts/README.md`：解释 contracts 和 AGENTS 的区别。
7. `config/contracts/*.json`：机器可读契约，写代码时必须遵守。

其他 `docs/*.md` 是专题附录，按需阅读；`references/legacy-auto-sync-20260412/` 是旧系统参考资料，不是新系统运行入口。

完整旧系统参考资料不提交主仓，放在私有仓 `InfoWatchtower-References`。需要旧资料时看 `references/README.md`。

## 仓库内容

- `config/seeds/legacy/`：新系统可导入的旧种子源。
- `config/taxonomy/`：AI 兼容标签和长期产业情报板块。
- `config/contracts/`：数据源、adapter、SQL、登录、工作台、标签、扩展点、战略闭环、同步策略契约。
- `config/domain_packs/`：后续扩展硬件、半导体、政策、竞品等板块的配置包。
- `docs/`：总纲和专题附录。
- `references/README.md`：私有参考仓拉取说明。
- `config/env.example`：环境变量样例。
- `docs/development-quickstart.md`：当前工程骨架的本地启动说明。

本地旧 `.env` 已复制到 `config/.env` 以便复用，但不会进入 Git。

当前种子源统计：wiseflow 1 个、RSS 108 个、页面源 4 个，合并索引 113 个。

当前数据库骨架：40 张业务表，覆盖用户/RBAC、工作台、共享数据源、标签、raw/news、去重、推荐、日报/周报、互动反馈、SQL 导出、同步回流和战略需求闭环。任意日报条目应能沿外键追回 `raw_items.raw_payload_json`。

当前登录能力：支持 `local/public_password/intranet_header` 三种入口，统一落到本地 `users` 和 `roles`；本地 Docker 默认开发账号为 `admin/password`，生产环境必须替换 `AUTH_SESSION_SECRET` 和 `AUTH_BOOTSTRAP_ADMIN_PASSWORD`。

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

更多说明见 `docs/development-quickstart.md`。

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
- 数据源页显示共享源 113、当前工作台启用 79。
- 数据源列表和右侧标签策略在桌面宽度下不应被横向截断；其他占位页应使用统一内容容器，不出现显示不全。
- 对任意启用的 `rss`、`paper_rss`、`page_manual` 或 `page_monitor` 源点击“抓取”，成功后会提示拉取、新增、更新数量。
- 重复抓取同一个 RSS 源时，`raw_items` 不重复插入，应表现为新增 0、更新大于 0。
- `POST /api/ingestion/runs` 可创建工作台级抓取 run；scheduler/worker 默认关闭，设置 `INGESTION_SCHEDULER_ENABLED=true` 后按环境变量定时执行每日完整流水线。
- `POST /api/news-items/normalize` 可把当前工作台已启用源的 raw 标准化为 news，并重建去重组。
- `GET /api/news-items?workspace_code=planning_intel` 可看到标准化新闻和 `raw_item_id` 追溯 ID。
- `GET /api/dedupe-groups?workspace_code=planning_intel` 可看到去重 winner/loser。
- `/daily-reports` 页面可选择日期并点击“生成日报草稿”，调用 `POST /api/pipeline/daily-runs`，执行抓取、标准化/去重、推荐、结构化稿和日报草稿。
- `/daily-reports` 页面可按日报正文阅读，支持发布、采信/备选/剔除切换、编辑标题/摘要/要点、点赞、评分、评论和查看 raw/news/source 追溯 ID。
