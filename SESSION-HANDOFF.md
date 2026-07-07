# InfoWatchtower · 用户 Journal

> 更新时间：2026-07-07。
> 本文件用于跨 session 快速恢复上下文，记录用户当前口径、已完成实现、
> 验证结果和下一步。权威事实仍以 `docs/00-system-design.md`、
> `docs/implementation/implementation-handoff.md`、`docs/implementation/01-implementation-plan.md`
> 和 `config/contracts/*.json` 为准。

---

## 0. 当前一句话

InfoWatchtower 的目标态已经从“单一 RSS + AI 日报系统”校正为：

**可本地一键 Docker 部署、可公网 SSO 采集发布、可内网 iframe 嵌入消费、
可云主机官方部署的多形态产业情报操作系统。**

本轮已经按这个目标刷新设计文档、机器契约、后端能力、前端用例和同步链路。
代码与文档目前在 `feat/deployment-topology` 工作区内，已验证通过，尚未提交。

---

## 1. 用户明确过的目标口径

用户认为之前的误解在于：**内网部署不是一个完整采集系统的小号版本**。

目标态是：

- 用户一次拉取代码，本地 Docker 启动，配置能力后即可部署运行。
- 用户可以在云主机上部署官方版本；非管理员只能看管理员拉取后的数据。
- 外网部署用于接入业界标准 SSO、运行采集能力、生成成品，并开放同步 feed。
- 内网部署要便捷接入内网门户，页面可被现有内网页面 iframe 嵌入。
- 内网外层页面已有工号和部门，评论、点赞、评分等协作行为应复用外层登录身份。
- 内网环境不方便运行 wx cli 等采集能力，所以内网版本最好只能拉取，不能采集。
- 外网部署后开放一个接口，内网部署版本直接通过 GET/pull 拉取外网成品与基础数据。

这不是前端显示开关问题，而是部署拓扑、权限、同步、安全和测试的系统级设计问题。

---

## 2. 四种部署形态

| 形态 | 用途 | 采集 | 同步角色 | 登录 | 备注 |
|---|---|---:|---|---|---|
| `standalone` | 本地一键 Docker，自用或小团队 | 是 | 可不启用 | local / public_password | 默认自给自足 |
| `cloud` | 官方云主机部署 | 是 | 可不启用 | public_password / oidc | 非管理员只读或受限 |
| `extranet` | 公网部署，采集与发布 | 是 | publisher | oidc 优先 | 向内网开放 feed |
| `intranet` | 内网嵌入门户 | 否 | consumer | intranet_header | 只拉取，不采集 |

硬不变式：

- `intranet` 不能采集，不能靠 env 打开 ingestion。
- 内网评论、评分、点赞等用户交互默认留在内网，不回流公网。
- 外网到内网同步以 service token + cursor feed 为主，zip 同步包只是 fallback。
- iframe 推荐同站反代嵌入，避免跨站 cookie 复杂度。
- 公网登录走 OIDC；内网嵌入走 header identity。

---

## 3. 本轮已经完成的实现

### 3.1 后端能力

- 新增部署能力开关和启动自检，覆盖 `DEPLOY_MODE`、ingestion、sync publisher、sync consumer 等。
- 新增安全中间件：CSP `frame-ancestors`、CSRF double-submit cookie。
- OIDC 登录链路已从预留升级为可用：
  - `GET /api/auth/oidc/start`
  - `GET /api/auth/oidc/callback`
  - discovery / explicit endpoints、state、nonce、PKCE、userinfo 解析。
- 新增 runtime meta，前端可按部署能力隐藏采集、导入、导出等操作。
- 新增数据源导入预览：
  - `GET /api/sources/import-preview?catalog=legacy|tech`
  - 导入前返回 total / would_create / would_update / samples。
- 修复“秒 0 成功”语义：
  - `limit=0` 后端直接 422。
  - 筛选不到启用源时 run 记为 `no_sources`。
  - selected sources 为空不再标记绿色 completed。
- 新增同步 feed / pull：
  - `GET /api/sync/feed/manifest`
  - `GET /api/sync/feed`
  - `POST /api/sync/pull-runs`
  - `sync_cursors` 记录 consumer 水位。
  - service token bearer 鉴权。
  - apply 支持 `data_sources/raw_items/news_items/generated_news/daily_reports/weekly_reports`。
- scheduler 已支持 intranet 只跑 sync pull，不跑采集。

### 3.2 前端能力

- 新增 Vitest 测试基建：`vitest`、`@vue/test-utils`、`jsdom`。
- `SourcesPage.vue`：
  - 导入前必须打开 preview 面板。
  - preview 确认后才真正 POST 导入。
  - read-only / no-ingestion 模式隐藏新增源、导入源、抓取按钮。
  - 0 条抓取结果提示为 info/warning，不再绿色成功。
- `IngestionRunsPage.vue`：
  - runtime capability gate 控制抓取按钮。
  - `limit < 1` 前端本地拦截。
  - 没有启用源时本地提示，不发起抓取。
  - `no_sources` 状态显示为 warning。

### 3.3 文档和契约

已同步刷新：

- `docs/00-system-design.md`
- `docs/implementation/implementation-handoff.md`
- `docs/implementation/01-implementation-plan.md`
- `docs/implementation/api-and-ui-implementation.md`
- `docs/deployment/deployment-topology.md`
- `docs/deployment/deployment-ops.md`
- `docs/deployment/multi-environment-sync.md`
- `docs/deployment/auth-unified-login.md`
- `docs/deployment/auth-security-roadmap.md`
- `docs/architecture/capability-map.md`
- `docs/deployment/development-quickstart.md`
- `docs/architecture/software-design-description.md`
- `docs/architecture/target-state-spec.md`
- `config/contracts/deployment_modes.json`
- `config/contracts/sync_strategy.json`
- `config/contracts/auth_modes.json`
- `config/contracts/source_fields.json`
- `config/contracts/adapter_pipeline.json`

---

### 3.4 2026-07-07 全量差距收口轮（多 agent 并行）

按目标态审计出的 confirmed gaps 分簇修复完成：

- **认证与信任边界**：四形态 `allowed_auth_modes` 白名单启动自检（cloud/extranet
  配 intranet_header 拒启）；`AUTH_SESSION_SECRET` 全 auth_mode、API/scheduler/worker
  三入口自检；`AUTH_TRUSTED_PROXY_CIDRS` 真正生效（身份头只信白名单直连 peer、
  登录限流 XFF 采信共用同一判定、非法 CIDR 拒启）；OIDC id_token 验签/强校验
  （新增 `OIDC_JWKS_URI`，拒绝 alg=none）；CSRF 邀请豁免收窄为仅匿名 accept；
  `next` 回跳拒反斜杠变体。新增 `tests/test_trusted_proxy.py` 等回归。
- **同步游标语义**：consumer 回看窗口重放（`SYNC_PULL_REPLAY_LOOKBACK_SECONDS=300`）
  补偿 publisher 长事务漏发；conflict 成 inbox 终态不卡水位（open 冲突按对象幂等
  去重）；传输失败落 `status=failed` 的 SyncRun + cursor `last_status=failed`；
  feed 支持 `name:token` 命名消费者且访问写审计。
- **多工作台策略中枢**：`backend/app/workspaces/policy.py` 按「标签策略 → domain
  pack（default_domain_code 关联）→ 内置 AI 默认」解析评分/分类降级/成稿看板/降级
  文案/公司 SQL gating；`GET /api/domain-packs` 列出可消费 pack；planning_intel
  行为逐字节不变，非 AI 工作台不再被 AI 噪声规则误杀；公司 SQL 出口对非适配工作台
  400 + `workspace_not_company_sql`。
- **全量 adapter**：wiseflow/crawler/csv/paper_page/manual/internal 六类由真适配器
  替换 stub，11 类 source_type 全部可用；`skipped_unimplemented` 语义保留为安全网。
- **部署工件**：`deploy/env.{intranet,extranet}.example`、
  `docker-compose.{intranet,extranet}.yml`、`nginx.portal.example.conf` 门户反代
  样例；`VITE_BASE_PATH` 子路径部署（vite/router/API 前缀三处联动）；前端 nginx
  envsubst 模板输出 frame-ancestors CSP 并清洗身份头；cloud/extranet caddy TLS
  profile；intranet 离线升级脚本（`scripts/export_offline_bundle.sh` /
  `upgrade_offline.sh`）；`/readyz` 就绪探针；`check_prod_deploy.py` 按
  DEPLOY_MODE 校验工件。
- **测试看护**：前端 Vitest 已进 `make test` 与 CI（Test frontend 先于 build）；
  Playwright 脚手架（config + API 打桩 smoke）交付；
  新增《后端能力与测试看护矩阵》`docs/backend/backend-capability-test-matrix.md`
  （形态 × 能力 × 必跑测试、禁用能力断言清单、adapter 状态表、前端测试/e2e 现状）。
- **文档与契约全量刷新**：deployment_modes/auth_modes/sync_strategy/workspace_model/
  label_model 契约与新实现对齐；SDD 补四形态章节并删过期宣称；总纲 §10 补 oidc；
  contracts README 补 deployment_modes/report_renditions 索引；target-state-spec
  细节对齐代码（密码 8 位、`AUTH_SESSION_TTL_SECONDS`）；单向 extranet→intranet
  写成硬不变式（intranet_to_public 标注 planned_manual_only）；quickstart 补
  DEPLOY_MODE/runtime meta/CSRF/双实例联调指引；`ModuleRoadmapPage.vue`
  死代码删除（R-015）。

遗留前端待办：建台向导第 3 步接 `GET /api/domain-packs` 动态列 pack；
~~manual/internal 推入式源在 UI/导入时的语义提示~~（已完成，见 §3.5）。
后端遗留：`backend/app/llm/minimax.py` 的重复 SQL_EFFECTS_FALLBACK 常量与
prompt 内「规划部」措辞、`models/common.py` ScopeMixin workspace_code 默认值
（多工作台策略轮未覆盖的文件）。

### 3.5 2026-07-07 第二轮：部署预设 + wechat + 阅读体验 + 文档收口（多 agent 并行）

**P0 事故复盘（前新后旧版本错位）**：用户实测遇到全站能力被禁用——前端热更到
新代码、后端容器仍跑旧镜像，新前端调 `/api/meta/runtime` 得 404，runtime store
按 fail-closed 保守禁用全部能力，表现为「什么都点不了」。三层修复：
① `deploy/docker-compose.local.yml` 对 backend/worker/scheduler 只读挂载
`backend/app`/`backend/alembic`/`config`，backend 以 `--reload` 运行，`make up`
即运行工作区当前代码；② 前端 `runtime.ts` 把 meta 失败分类为
`stale-backend`（404，提示重启/重建后端）/`unreachable`/`http-error`，AppShell
横幅给出可诊断文案与手动重试；③ 文档写入
`docs/deployment/development-quickstart.md` §4。教训：能力开关 fail-closed 是
对的，但失败必须可诊断，否则用户对着「加载失败」抓瞎。

本轮新能力清单：

- **wechat adapter（第 12 类 source_type）**：`backend/app/adapters/wechat.py`
  自研实现，不依赖同事 wx 二进制——rsshub 主路径（feed_url/rsshub_route/账号
  标识推导，复用 rss.py 解析）+ article_urls 定点抓取（og meta/正文/发布时间/
  合集页枚举，风控验证页记失败不落 raw）；wx 桥 sidecar 降级为可选增强。
  契约：`source_fields.json`（source_types 12 类 + fetch_config_conventions.wechat）、
  `adapter_pipeline.json`（wechat_discovery_rule）。
- **credential_ref 凭据解析落地**：`backend/app/core/credentials.py` 支持
  `env:VAR_NAME` / `file:/absolute/path`，非法/缺失降级匿名并记 WARNING；adapter
  取 token 顺序 `credential_ref → auth_token_env → auth_token`。
- **部署启动预设**：`deploy/install.sh --preset rss-only|full|mirror`（默认 full）；
  `INGESTION_SOURCE_TYPES` 部署级采集类型允许清单（run 内过滤，摘要记
  `skipped_type_disabled`，非法值拒启）；mirror = standalone/cloud +
  `CAPABILITY_INGESTION=false` + sync consumer pull（`deploy/env.mirror.example`）。
  `INGESTION_SCHEDULER_DAILY_TIME` 代码默认改为 12:00（中午汇总昨天）。
- **AUTH_SESSION_SECRETS 轮换**：逗号列表，第一个签名、全部可验签；换密钥不掉线，
  移出列表即失效；启动自检两变量任一非空即过。
- **日报自动发布 + 发布后修订**：工作台 `report_policy.auto_publish_daily`
  （默认 true，`GET/PATCH /api/workspaces/{code}/report-policy`）；流水线出稿即
  自动发布（actor=system，audit `daily_report.auto_publish`）；published 日报的
  报告层字段允许 admin+ 修订，写 `post_publish_revision` 审计并重投影
  renditions，raw/generated_news 与公司 SQL 契约不动
  （`docs/backend/reports-editorial-design.md` §7.1/§7.2）。
- **报告归档与实体大事记 v2**：`GET /api/report-archive(/summary)` 统一归档、
  `GET /api/entity-timeline/summary` 总览、tracked_entities 增删改 + 手工补录 +
  候选确认/驳回、发布即沉淀候选里程碑；`/historical-reports`、`/entity-milestones`
  页面大改版（`docs/backend/archive-knowledge-design.md`、
  `config/contracts/archive_knowledge.json`）。
- **viewer（游客）阅读视角**：workspace_sections 阅读分区 min_role=viewer，
  AppShell 按有效角色过滤导航，路由守卫把 viewer 从管理路由重定向回
  `/daily-reports`，日报/周报页编审操作整组隐藏、成稿读发布时投影快照
  （`docs/product/frontend-product-design.md` §5.3）。
- **推入式/类型停用 UI 语义**：SourcesPage「推入式」「待配置」徽标 + 导入预览按
  source_type 分组小计；IngestionRunsPage `skipped_type_disabled`「类型停用」标签
  与语义分组提示条（`backend-capability-test-matrix.md` §3.1 已完成态）。
- **401 统一登出跳转**：`http.ts` 暴露 `onUnauthorized` 注册点（豁免登录密码错误
  与 `/api/auth/me` 探活），`session.ts` 提供 `installUnauthorizedRedirect(router)`
  （清 session + 跳 `/login?redirect=`），`main.ts` 最小装配。
- **Playwright 真跑**：chromium 下载并实跑 3 条 smoke 全绿；修复 `**/api/**` glob
  误拦 vite 源码模块 URL 的脚手架 bug（非 `/api/` pathname `route.fallback()`
  放行）；新增 `make e2e` 可选 target（不进 CI 门禁，原因 chromium 下载耗时），
  坑记录在 `frontend/e2e/README.md`。

本轮验证：backend pytest 定向文件全绿、frontend vitest 29 spec/231 用例全绿、
`npm run build` 通过、Playwright 3/3、docs/契约治理校验通过。

本轮遗留（除 E 系外）：

- `deploy/install.sh` 生成 env 仍写 `INGESTION_SCHEDULER_DAILY_TIME=09:00`，与
  代码默认 12:00 不一致（显式值合法可跑，但口径待统一到 12:00 或删掉该行走默认）。
- `GET /api/entity-timeline/summary` 未做 workspace membership 断言（仅要求登录），
  与契约标注的 viewer 门槛存在差距，待补 `assert_workspace_member`。
- IngestionRunsPage 的 internal 可拉取判定以 url 入口作代理信号（API 未暴露
  `fetch_config.api_url`），后续 API 暴露安全投影后可改为精确判定。

### 3.6 2026-07-07 第三轮：工作台协作边界 + README/文档终稿（多 agent 并行）

新能力（代码已在工作树，读最新代码为准）：

- **工作台可见性与自助订阅**：`workspaces.visibility`（private/internal_public，
  迁移 `d8e9f0a1b2c3`，种子只设初值）、`GET /api/workspaces/discover`、
  `POST/DELETE /api/workspaces/{code}/subscribe`（幂等、不降级、保护最后 owner）、
  `PATCH /api/workspaces/{code}/visibility`（admin+，暂无页面入口）；前端
  「发现工作台」抽屉 `WorkspaceDiscovery.vue` 挂在工作台切换器底部。
- **用户组与批量入台/指派**：`user_groups/user_group_members`（迁移
  `d0e1f2a3b4c5`，组≠权限层），组 CRUD 权限门 super_admin/editor_admin
  （`/api/user-groups*`）；`POST /api/workspaces/{code}/members/bulk` 按组幂等
  批量入台（审计 `workspace.member.bulk_upsert`）；任务指派通知 `task.assigned`、
  `GET /api/topic-tasks?assignee=me`；`/users` 页新增用户组入口。
- **游客登录**：`AUTH_GUEST_ENABLED`（仅 standalone/cloud，fail-fast）+
  `POST /api/auth/guest-login`；共享只读账号、无 membership、隐式 viewer 浏览
  internal_public 工作台、写操作 `get_current_user` 单点 403（仅放行 logout）。
- **工作台配置中心**：`workspace_settings` 核心分区（system 组，
  `config_json.min_role=admin`，不可停用）+ `/workspace-settings` 页面：基本信息、
  导航分区启停（`GET /api/workspaces/{code}/sections/manage` +
  `PATCH .../sections/{key}`，用户决定持久化 `config_json.user_enabled`）、标签
  策略、报告策略（自动发布）、成员、报告格式；viewer 反馈策略仍在 `/users`。

文档与契约终稿（本任务 J）：

- `README.md` 重写为对外首页：一段话定位、15 分钟上手、四形态 × 三预设矩阵、
  能力速览表、文档导航、开发/测试命令、硬边界摘录；删除过期的
  「admin/password 默认账号」「当前阶段为阶段 5」等旧验收叙述（本地一键装完走
  `/setup` 创建首管）。
- 总纲 `docs/00-system-design.md`：§7 adapter 清单更新为 12 类（补 csv/wechat +
  credential_ref 规则）；§6 补工作台可见性/订阅、配置中心、用户组；§10 补游客
  开关；§11 补 install.sh 三预设。
- SDD `docs/architecture/software-design-description.md`：§5.1 wechat/credential_ref、
  §5.4 自动发布/发布后修订/viewer 视角、§5.6 三预设与 guest fail-fast、§5.7 游客/
  订阅/用户组/配置中心、§10 wx 行改为「已落地，剩余可选增强」。
- 产品文档：`frontend-product-design.md` 页面地图补 `/workspace-settings` 与
  「发现工作台」侧边栏入口；`frontend-page-specs.md` 新增 §19.5 工作台配置页
  规格与逐页总表行。
- 契约：`workspace_model.json` core_sections/section_groups 对齐播种（17 个核心
  分区，含 strategic_insights/sync/workspace_settings）、新增 `section_min_role`/
  `section_management`/`report_policy`；`auth_modes.json` 新增 `user_groups` 契约、
  `identity_audit_actions` 补 guest/用户组/订阅/visibility/bulk 动作；
  `strategic_loop.json` 补 `assignee=me` 过滤参数（Wave1 已补 guest_access、
  visibility/订阅、deployment fail-fast 与三份测试矩阵行）。
- 能力地图 `capability-map.md`：A 块 12 类 adapter/credential_ref/类型停用语义，
  E 块自动发布/发布后修订/viewer 视角，G 块归档 v2 与 entity-timeline membership
  已知差距，H 块新增预设/订阅/用户组/游客/配置中心五段，P1 wx 差距改写为实机
  验收 + 可选增强。

本轮已知小差距（延续 §3.5 遗留）：`install.sh` 生成 env 仍写
`INGESTION_SCHEDULER_DAILY_TIME=09:00`（代码默认 12:00）；
`GET /api/entity-timeline/summary` 缺 workspace membership 断言；
`PATCH /api/workspaces/{code}/visibility` 暂无页面入口。

## 4. 用户发现的问题与闭环状态

### 问题 1：数据源引入没弹窗，直接显示成功 0 个

判断：不是单纯 UI 文案问题，而是导入动作缺少 preview / confirm 语义，
同时缺少 0 结果测试。

当前闭环：

- 后端已有 import-preview API。
- 前端导入必须先展示 preview。
- 确认后才会真正执行导入。
- 已补 SourcesPage 测试，覆盖“未确认不 POST”和“read-only 隐藏导入”。

### 问题 2：数据源拉取秒成功 0 条

判断：暴露了前后端共同问题：

- 前端测试没有覆盖无源、0 limit、无采集能力等负向路径。
- 后端把“没有选到源”和“真实抓取完成但 0 条”混在 completed 里。

当前闭环：

- `limit=0` 后端 422。
- 空源 run 状态为 `no_sources`。
- 前端没有启用源时不发起抓取。
- read-only/intranet 模式隐藏抓取入口。
- 已补 IngestionRunsPage 测试。

---

## 5. 验证结果

已执行并通过：

```bash
# contracts JSON
for f in config/contracts/*.json; do backend/.venv/bin/python -m json.tool "$f" >/tmp/$(basename "$f").valid || exit 1; done

# targeted backend tests
backend/.venv/bin/python -m pytest \
  backend/tests/test_auth.py \
  backend/tests/test_sources_api.py \
  backend/tests/test_ingestion_runs.py \
  backend/tests/test_deployment_modes.py \
  backend/tests/test_sync_feed_pull.py \
  backend/tests/test_operations_api.py -q
# 54 passed

# full backend tests, correct cwd
cd backend && .venv/bin/python -m pytest -q
# 151 passed

# frontend tests
cd frontend && npm test -- SourcesPage IngestionRunsPage
# 5 passed

# frontend build
cd frontend && npm run build
# passed

# whitespace check
git diff --check
# passed
```

注意：从仓库根目录直接跑 `backend/.venv/bin/python -m pytest -q`
会误收集 `references/private/wiseflow-4x/test` 的参考仓测试，并解析到 venv
里旧的 `app` 包。正确后端入口是 `cd backend && .venv/bin/python -m pytest -q`。

---

## 6. 当前工作区状态

当前分支：`feat/deployment-topology`。

本轮核心新增文件：

- `backend/app/api/routes/sync.py`
- `backend/app/core/security.py`
- `backend/app/core/deploy_checks.py`
- `backend/app/sync/`
- `backend/alembic/versions/c3d4e5f6a7b8_add_sync_cursors_and_feed_support.py`
- `backend/tests/test_deployment_modes.py`
- `backend/tests/test_sync_feed_pull.py`
- `config/contracts/deployment_modes.json`
- `docs/deployment/deployment-topology.md`
- `frontend/src/api/http.ts`
- `frontend/src/api/meta.ts`
- `frontend/src/stores/runtime.ts`
- `frontend/src/pages/SourcesPage.spec.ts`
- `frontend/src/pages/IngestionRunsPage.spec.ts`
- `frontend/vitest.config.ts`

还有较多既有改动和本轮同步改动混在同一工作区，提交前需要按能力分块检查：

1. deployment/auth/security
2. sync feed/pull
3. source import preview + ingestion no_sources
4. frontend runtime gate + tests
5. docs/contracts refresh

---

## 7. 尚未完成或需要后续实机验收（E 系清单）

代码、部署工件、文档和测试看护均已本地闭环；剩余为需要真实环境的验收动作：

- **E-1 真实 OIDC provider 验收**：对接一个真实 IdP（含 `OIDC_JWKS_URI` 验签路径），
  留存登录/建号/membership/登出与 auth_error 回跳证据。
- **E-2 wx 桥接（范围已缩小）**：wechat adapter 已自研落地（rsshub 主路径 +
  article_urls 定点抓取，见 §3.5，不依赖 wx 二进制）；剩余为可选增强——向同事
  确认 wx 二进制事实（获取方式/登录态维持/可否跑 Linux）后做 `scripts/wx_bridge/`
  参考实现，以及自建 RSSHub/桥的实机抓取验收。
- **E-3 双实例网络演练**：extranet publisher → intranet consumer 跨网络实机同步
  （含冲突处置、failed inbox 自愈、回看窗口重放观察）。
- **E-4 prod TLS 证书**：真实域名启用 `--profile tls`，验证 ACME 签发/续期与
  80→443 跳转。
- **E-5 门户真实 iframe 联调**：按 `deploy/nginx.portal.example.conf` 在真实门户
  配同站反代 + 身份头注入，验证 `VITE_BASE_PATH=/watchtower/`、frame-ancestors、
  CSRF 与评论落本地库。
- **E-6 离线升级与备份恢复演练**：`export_offline_bundle.sh` → 拷入内网 →
  `upgrade_offline.sh` 全流程 + 生产备份/恢复演练证据归档。

已从本清单闭环的原待办：sync conflicts resolve API/UI（C-7 完成）、Playwright
脚手架（C-8 部分完成，真实后端旅程仍在 E 系之外的 P1）、后端看护矩阵文档
（`docs/backend/backend-capability-test-matrix.md` 已交付）、部署样例与 TLS/离线
升级工件（C-6 工件完成，演练在 E-4/E-6）。

---

## 8. 不可破坏的系统原则

- 不要把系统写死成 RSS + AI 日报。
- `domain_code`、`visibility_scope`、`sync_policy` 必须贯穿数据源、raw、news 和同步链路。
- 原始数据完整保存在 `raw_items.raw_payload_json`。
- 去重发生在 `news_items` 之后、推荐之前。
- `adoption_status` 属于日报/周报采信层，不属于 `news_items`。
- 日报编辑不覆盖 `raw_items` 和 `generated_news`。
- 标准公司 SQL 只导出已发布日报中 `adoption_status = 2`、
  `generation_status = ready` 且 `generated_by` 非 `rule_v1` 的条目。
- 标准公司 SQL 必须通过 `scripts/validate_company_sql.py`。
- `planning_intel` 成品新闻一级标签必须是旧系统约定的 10 个 AI 标签。
- 数据源侧方向标签只用于源管理、覆盖分析和评分先验，不能写入公司 SQL category。
- 密钥、token、cookie 和 `.env` 不进入 Git，不进入同步包。
- 私有参考仓 `InfoWatchtower-References` 是参考资料，不是新系统运行入口。
- 前端视觉基线保持 Apple Liquid Glass，不回退成深色壳、宽表格或绿色/青色主调。

---

## 9. 下一次 session 恢复建议

1. 先读本文件，再读 `AGENTS.md`、`docs/00-system-design.md`、
   `docs/implementation/implementation-handoff.md`、`docs/implementation/01-implementation-plan.md`、
   `docs/README.md` 和相关 contracts。
2. 运行 `git status --short`，确认工作区没有用户新增的无关变更被混入提交。
3. 重跑（与 CI 同口径的完整门禁是 `make test`）：

```bash
cd backend && .venv/bin/python -m pytest -q      # 严禁在仓库根跑，会误收集参考仓
cd ../frontend && npx vitest run
cd ../frontend && npm run build
cd .. && python3 scripts/validate_docs_governance.py
python3 scripts/validate_frontend_controls.py
for f in config/contracts/*.json; do python3 -m json.tool "$f" > /dev/null || echo "BROKEN $f"; done
python3 scripts/check_prod_deploy.py --env-file deploy/env.production.example
git diff --check
```

4. 若要发布代码，按第 6 节拆成小提交，不要把全部改动揉成一个无法审查的大提交。
5. 若要继续实现，按第 7 节 E 系清单做实机验收；测试矩阵与禁用能力断言见
   `docs/backend/backend-capability-test-matrix.md`。

