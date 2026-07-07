# InfoWatchtower（AI情报官）

**多工作台的产业情报操作系统。** 一套代码把「信息源接入 → 原始数据入库 → 标准化去重 →
可解释推荐准入 → 结构化成稿 → 日报/周报编审发布 → 多格式分发」做成共享流水线：任何团队
可以自助开一个工作台、接自己的信息源、配自己的标签策略，产出可追溯的日报、周报、洞察、
需求和任务；规划部是第一个租户（对接公司内网 SQL 硬合同），同一套系统支持本地一键
Docker、云主机官方站、公网采集发布和内网门户 iframe 嵌入四种部署形态，不分叉代码。

## 15 分钟上手

前置：Docker（含 docker compose）和 openssl。

```bash
# 1. 拉代码
git clone <this-repo> && cd <repo-dir>

# 2. 一键安装（生成 env + 构建 + 起容器，默认 full 预设）
cd deploy && ./install.sh --local

# 3. 打开 http://localhost:5173 ，首次访问进入 /setup 创建第一个管理员

# 4. 建工作台：侧边栏「新建工作台」三步向导（或直接用内置 planning_intel，
#    默认已启用 294 个共享源）

# 5. 抓一轮数据：进入「抓取与覆盖」页点抓取（或等 scheduler 按
#    INGESTION_SCHEDULER_DAILY_TIME 每天自动跑完整流水线：
#    抓取 → 标准化/去重 → 推荐 → 成稿 → 日报自动发布）

# 6. 看日报：进入「日报」页直接读当天成稿；管理员可继续采信/编辑/修订，
#    viewer 打开即是阅读视角
```

日常起停（安装过一次之后，在仓库根）：

```bash
make up      # 启动（复用 deploy/.env）
make down    # 停止
make build   # 改依赖后重建镜像
make logs    # 跟日志
```

## 四种部署形态 × 三种启动预设

同一套代码按 `DEPLOY_MODE` 收敛能力，差异只由环境变量、认证 adapter、同步角色和网关
决定（契约：`config/contracts/deployment_modes.json`；规格：
`docs/deployment/deployment-topology.md`）：

| 形态 | 用途 | 采集 | 同步角色 | 登录 |
|---|---|---:|---|---|
| `standalone` | 本地一键 Docker，自用或小团队 | 是 | 可不启用 | local / public_password |
| `cloud` | 云主机官方站，团队看结果 | 是 | 可不启用 | public_password / oidc |
| `extranet` | 公网采集发布者 | 是 | publisher（开放 `GET /api/sync/feed`） | oidc 优先 |
| `intranet` | 内网门户同站反代 iframe 嵌入 | 否 | consumer（pull-only） | intranet_header |

安装入口都是 `deploy/install.sh`，并支持三种启动预设：

```bash
cd deploy
./install.sh --local                       # 本地，默认 --preset full（全量能力）
./install.sh --local  --preset rss-only    # 只抓 RSS 类信息源（INGESTION_SOURCE_TYPES=rss,paper_rss）
./install.sh --local  --preset mirror      # 镜像站：本地不采集，只从外部部署拉取成果
./install.sh --domain example.com          # 生产（cloud 形态），同样支持 --preset
```

`mirror` 预设需要外部部署的 `SYNC_REMOTE_BASE_URL/SYNC_REMOTE_TOKEN`；intranet/extranet
形态按 `deploy/env.intranet.example` / `deploy/env.extranet.example` 手工准备 env 后使用
对应 compose 文件。预设与 env 组合矩阵见 `docs/deployment/deployment-ops.md` §1.1/§1.2。

## 能力速览

| 能力块 | 现状 |
|---|---|
| 信息源接入 | 12 类 `source_type` 全部有真适配器：`rss / paper_rss / page_monitor / page_manual / crawler / csv / paper_api（arXiv/OpenAlex/Semantic Scholar）/ paper_page / wiseflow / manual / internal / wechat`（微信公众号自研 adapter，rsshub 主路径 + 文章 URL 定点抓取）；共享源池 + 工作台启用/权重/日限；密钥只用 `credential_ref` 引用 |
| 处理主链 | `raw_items` 完整保留原始 payload → `news_items` 标准化 → 工作台隔离硬去重，全链路可追溯回原始报文 |
| 推荐评分 | ContentScorer v2 准入 P0-P3/R，分数可解释（质量/主题/新鲜度/反馈/来源/热度拆解），用户反馈和需求结论反哺评分 |
| 生成成稿 | MiniMax 五段结构化生成（未配 key 走规则降级并标注）；一次采信、多版成稿：`company_sql_v1` / `tech_insight_v1` / 自定义格式注册表，Markdown/HTML 导出 |
| 编审发布 | 日报/周报采信、头条、编辑覆盖（不污染生成稿）、每日自动发布（工作台 `report_policy.auto_publish_daily`）与发布后修订 |
| 协作 | 工作台可见性与自助订阅（`internal_public` 发现工作台）、用户组批量入台、任务指派与站内通知、评论/点赞/评分策略、游客只读浏览（`AUTH_GUEST_ENABLED`） |
| 分发集成 | 公司 SQL 4 表硬合同（`scripts/validate_company_sql.py` 校验 + 语句级追溯 + 内网导入回执）；extranet feed / intranet 定时 pull 单向同步，内网反馈永不回流 |
| 平台底座 | 四形态能力开关与启动自检、local/public_password/OIDC(PKCE)/intranet_header 统一登录、RBAC + workspace membership、工作台配置中心（标签/报告/反馈策略、导航分区、成员）、审计、备份/恢复脚本 |
| 资料库 | 历史报告库、实体大事记、质量归档、insight → requirement → task 战略闭环，旧系统 14834 素材/66 报告导入验收链路 |

## 文档导航

接手或深入之前，按这个顺序读：

1. `AGENTS.md` — 开发准则、修改同步规则、不可破坏的设计原则。
2. `docs/00-system-design.md` — 唯一总纲：愿景、主链路、硬约束、部署方向。
3. `docs/README.md` — 文档地图与权威关系（architecture/product/backend/deployment/implementation/reference 六层）。
4. `docs/architecture/capability-map.md` — 当前实现状态、证据路径和差距列表。
5. `docs/backend/backend-capability-test-matrix.md` — 四形态 × 能力 × 必跑测试矩阵。
6. `docs/deployment/development-quickstart.md` — 本地开发启动细节；`docs/deployment/deployment-ops.md` — 生产部署与运维。
7. `config/contracts/README.md` 与 `config/contracts/*.json` — 机器可读契约，写代码必须遵守。

旧系统完整参考资料在私有仓 `InfoWatchtower-References`（说明见 `references/README.md`），
不是新系统运行入口。

## 本地开发与测试

后端（Python 3.11+）：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
DATABASE_URL="" pytest            # sqlite 内存跑测试；严禁在仓库根跑 pytest
DATABASE_URL="" uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npx vitest run     # 组件/页面测试
```

全量门禁（与 CI 同口径）：

```bash
make test              # docs/前端控件治理校验 + 后端 pytest + 前端 vitest + 前端 build
make migration-check   # alembic 迁移干净门禁
make docs-check        # 文档治理校验
make e2e               # Playwright smoke（可选，首次需下载 chromium）
```

公司 SQL 导出预览在导入内网前必须通过：

```bash
python3 scripts/validate_company_sql.py
```

## 不可破坏的硬边界

完整清单见 `AGENTS.md`，最关键的几条：

- 原始数据完整保存在 `raw_items.raw_payload_json`，下游永不回写。
- 去重发生在 `news_items` 之后、推荐之前；`adoption_status` 只属于日报/周报采信层。
- 标准公司 SQL 只导出已发布日报中 `adoption_status=2`、生成稿 ready 且非规则兜底的条目，
  且必须通过 `scripts/validate_company_sql.py`。
- `planning_intel` 成品新闻一级标签必须是旧系统约定的 10 个 AI 标签。
- 密钥、token、cookie 和 `.env` 不进入 Git，不进入同步包。
- 内网用户评论、点赞、评分、需求和任务永不回流公网。
