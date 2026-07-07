# 后端能力与测试看护矩阵

> 状态：看护矩阵附录（2026-07-07 建立），不是新的目标态事实源。部署形态与能力开关的
> 事实源是 `docs/deployment/deployment-topology.md` 与
> `config/contracts/deployment_modes.json`；adapter 事实源是
> `docs/backend/ingestion-adapter-dedup-spec.md`。本文回答三个运营问题：
> 改了某个形态/能力后必须跑哪些测试、每个形态哪些能力必须被断言禁用、
> 12 类 source_type adapter 的实现状态。

测试命令纪律（跑错目录会误收集参考仓测试）：

```bash
# 后端：必须在 backend/ 目录内执行
cd backend && .venv/bin/python -m pytest tests/<file> -q
cd backend && .venv/bin/python -m pytest -q          # 全量

# 前端
cd frontend && npx vitest run                         # 全量组件/单元测试
cd frontend && npx vitest run <pattern>               # 定向
cd frontend && npx playwright test                    # e2e（首次先 npx playwright install chromium）

# 一条命令全门禁（与 CI 同口径：docs/契约治理 + 后端 pytest + 前端 vitest + 前端 build）
make test
```

## 1. 四种 DEPLOY_MODE × 能力开关 × 必跑测试矩阵

能力开关取值来自契约 `config/contracts/deployment_modes.json`（代码镜像
`backend/app/core/config.py` 的 `MODE_CAPABILITIES/MODE_CSRF_DEFAULTS/
MODE_ALLOWED_AUTH_MODES`，一致性由 `tests/test_deployment_modes.py` 看护）。

| 维度 | standalone | cloud | intranet | extranet |
|---|---|---|---|---|
| ingestion | ✅ | ✅ | ❌（不可 env 覆盖打开） | ✅ |
| sync_publisher | ❌（可 env 覆盖调试） | ❌ | ❌ | ✅ |
| sync_consumer | ❌ | ❌ | ✅ | ❌ |
| embedding（信息性标识） | ❌ | ❌ | ✅ | ❌ |
| search | ✅ | ✅ | ✅ | ✅ |
| CSRF 默认 | ❌ | ✅ | ✅ | ✅ |
| 合法 AUTH_MODE | local / public_password | public_password / oidc | intranet_header | oidc / public_password |

改动与必跑测试文件的映射（均为 `backend/tests/` 下文件；改动涉及多行时全部跑）：

| 改动面 | 必跑测试文件 | 看护点 |
|---|---|---|
| DEPLOY_MODE 派生/能力门/启动自检/CSRF/runtime meta | `test_deployment_modes.py`（38 用例） | 能力表与契约一致、`allowed_auth_modes` 全矩阵拒启（9 组非法 + 4 组合法）、缺 `AUTH_SESSION_SECRET` 拒启、intranet 采集 403 清单、feed 能力门与对象边界、CSRF 双提交、`GET /api/meta/runtime` |
| intranet 身份头信任边界（AUTH_TRUSTED_PROXY_CIDRS） | `test_trusted_proxy.py`（9 用例） | 受信/不受信 peer、伪造 XFF 假装网关、未配置 CIDR 旧行为、限流取 IP 判定 |
| intranet 端到端写闭环（header 建号 + CSRF + 本地留存） | `test_intranet_write_paths.py` | 门户身份头首访建号 → 评论/点赞/评分（带 CSRF token 成功、缺 token 403）→ 写入不进 sync feed 面 |
| 登录/邀请/OIDC/限流/session | `test_auth.py`（28 用例）、`test_account_lifecycle.py` | OIDC id_token 验签/强校验/nonce/alg=none、`next` 反斜杠开放重定向、邀请 CSRF 豁免仅匿名 accept、限流窗口 |
| sync feed publisher 侧 | `test_sync_feed.py`、`test_deployment_modes.py` | token 鉴权/命名消费者审计、游标可重放、密钥红线、禁止对象负向 |
| sync pull consumer 侧 | `test_sync_feed_pull.py` | 水位前进/幂等、回看窗口重放、冲突不卡水位、传输失败落 failed run、failed inbox 重试 |
| 同步冲突/健康/人工包 | `test_operations_api.py` | conflict resolve 策略、`GET /api/sync/health` 告警、包导出/导入审计 |
| 工作台内容策略（评分/看板/导出 gating） | `test_workspace_policy.py`（10 用例）、`test_recommendations.py`、`test_report_renditions.py`、`test_company_sql_export.py` | 策略解析顺序、非 AI 工作台中性准入、看板 taxonomy 来源、公司 SQL gating 与字节级契约 |
| 公司 SQL 契约 | `test_company_sql_export.py` + `python3 scripts/validate_company_sql.py` | 4 表字段字节级不变、`workspace_not_company_sql` gating、export_category_mode 锁死 |
| adapter / 抓取 run | `test_adapters.py`、`test_adapter_{wiseflow,crawler,csv,paper_page,push_based,wechat}.py`、`test_ingestion_runs.py`、`test_ingestion_fetch.py` | 各 adapter fetch 契约、raw 幂等刷新、`skipped_unimplemented` 语义、失败源重试 |
| 部署级采集类型允许清单（INGESTION_SOURCE_TYPES / rss-only 预设） | `test_deployment_modes.py`、`test_ingestion_runs.py` | 非法清单值启动拒绝、run 内过滤与 `skipped_type_disabled` 摘要语义、空清单=全部允许 |
| session secret 轮换（AUTH_SESSION_SECRETS） | `test_auth.py`、`test_deployment_modes.py` | 第一个签名/全列表验签、换密钥不掉线、移出列表即失效、两变量任一非空过启动自检 |
| credential_ref 凭据解析 | `test_credentials.py`、`test_adapters.py` | env:/file: 两种 scheme、非法/缺失降级匿名并告警、credential_ref → auth_token_env → auth_token 顺序 |
| 健康探针 | `test_health.py`（5 用例） | `/healthz` 永 200 存活、`/readyz` 数据库失联 503 |
| 部署工件 | `python3 scripts/check_prod_deploy.py --env-file deploy/env.production.example`（CI 已跑） | 形态 compose/env/nginx/Caddy 工件与契约 fail-fast 对齐 |

## 2. 每形态禁用能力断言清单

这是回归时必须保持红线的**负向断言**清单（对应测试都已存在）。

### intranet（禁采集、pull-only）

以下写端点在 `DEPLOY_MODE=intranet` 下必须 403
`{"code": "capability_disabled", "capability": "ingestion"}`
（`test_deployment_modes.py` 的 `INGESTION_GATED_PATHS`）：

```text
POST /api/ingestion/runs
POST /api/ingestion/runs/{run_id}/retry-failed-sources
POST /api/ingestion/backfill-runs
POST /api/sources/{id}/fetch
POST /api/sources/import-legacy-seeds
POST /api/sources/import-tech-insight-loop
POST /api/pipeline/daily-runs
```

以及：

- `DEPLOY_MODE=intranet` + `CAPABILITY_INGESTION=true` → 启动失败（不变式）。
- `GET /api/sync/feed*` → 403（intranet 无 sync_publisher 能力）。
- scheduler 不投递采集/流水线任务，只投 `sync_pull`（及 failed inbox auto retry）。
- 前端按 `GET /api/meta/runtime` 隐藏抓取/导入/建源入口（`SourcesPage.spec.ts`、
  `IngestionRunsPage.spec.ts`）。
- 评论/点赞/评分/采信/需求/任务只写本地库；feed 对象类型永不包含
  `requirements/topic_tasks/comments/reactions/ratings/activity_events/
  notifications/notification_preferences/object_watchers/export_jobs`
  （`test_deployment_modes.py` 两条 excludes 负向测试）。

### standalone / cloud（无同步角色）

- `GET /api/sync/feed*` → 403（无 sync_publisher；standalone 可显式
  `CAPABILITY_SYNC_PUBLISHER=true` 调试）。
- `POST /api/sync/pull-runs` → 403（无 sync_consumer）。
- cloud/extranet 配 `AUTH_MODE=intranet_header` → 启动失败（请求头伪造登录红线）。

### extranet（发布者）

- `SYNC_SERVICE_TOKENS` 为空 → 启动失败。
- feed 端点只认 Bearer service token，携带 cookie session 不放行；无 token 401。
- `POST /api/sync/pull-runs` → 403（无 sync_consumer）。

### 全形态

- 缺 `AUTH_SESSION_SECRET` → API/scheduler/worker 三入口全部拒启。
- 密钥红线：含 secret-like 字段的 payload 不进 feed/包/审计明文
  （`test_operations_api.py` redaction 用例）。

## 3. 12 类 source_type adapter 实现状态

原审计口径「6 个 stub adapter」已在 2026-07 由真实现替换完毕，规划中的第 12 类
`wechat` 也已落地：`backend/app/adapters/stubs.py` 仅保留给 `skipped_unimplemented`
语义的回归测试显式注册（模块 docstring 明确禁止进默认注册表）；
`create_default_registry`（`backend/app/adapters/__init__.py`）注册的 12 类全部为真适配器。

| source_type | 实现 | 状态 | 说明 / 测试 |
|---|---|---|---|
| rss | `rss.py RssFeedAdapter` | ✅ 稳定 | 普通 RSS/Atom；`test_adapters.py` |
| paper_rss | `rss.py PaperRssFeedAdapter` | ✅ 稳定 | 论文 RSS；`test_adapters.py` |
| page_monitor | `page.py PageListingAdapter` | ✅ 稳定 | 列表页抓链接再抓详情；深度抽取仍是轻实现（P2） |
| page_manual | `page.py ManualPageAdapter` | ✅ 稳定 | 手工 seed URL |
| paper_api | `paper.py PaperApiAdapter` | ✅ v1 | arXiv / OpenAlex Works / Semantic Scholar bulk search；OpenReview 等 provider 待扩展 |
| wiseflow | `wiseflow.py WiseflowReadInfoAdapter` | ✅ 新实现 | 对接 wiseflow 4.x `POST /read_info` 分页；`test_adapter_wiseflow.py` |
| crawler | `crawler.py CustomCrawlerAdapter` | ✅ 新实现 | 通用列表页爬虫（href 规则筛链接 + 正文抽取）；`test_adapter_crawler.py` |
| csv | `csv_file.py CsvFileAdapter` | ✅ 新实现 | 本地/远程 CSV，列映射与 manual-import 约定一致；`test_adapter_csv.py` |
| paper_page | `paper_page.py PaperPageAdapter` | ✅ 新实现 | 会议 accepted papers / 实验室 publications 页；`test_adapter_paper_page.py` |
| manual | `push_based.py ManualNewsAdapter` | ✅ 推入式 | 条目由 manual-import 写入；定时抓取如实返回 0 条新增（成功、非失败）；`test_adapter_push_based.py` |
| internal | `push_based.py InternalSourceAdapter` | ✅ 推入式/可拉取 | 默认推入式；配置 `fetch_config.api_url` 后升级为通用 JSON API 拉取器；凭据已支持 `credential_ref → auth_token_env → auth_token` 顺序 |
| wechat | `wechat.py WeChatMpAdapter` | ✅ 新实现 | 公众号自研适配器：rsshub 主路径（feed_url / rsshub_route / 账号标识推导，RSS 解析复用 rss.py）+ article_urls 定点抓取（og meta/正文/发布时间，合集页枚举，风控验证页记失败不落 raw）；不依赖 wx 二进制，wx 桥 sidecar 为可选增强（`deployment-topology.md` §5.1）；`test_adapter_wechat.py` |

凭据机制：`credential_ref`（`env:VAR_NAME` / `file:/absolute/path`，
`backend/app/core/credentials.py`）已落地为首选凭据指针，`*_env` 间接引用保留兼容；
非法/缺失降级为匿名请求并记 WARNING（`test_credentials.py`）。

### 3.1 推入式/低产出源在 UI 与导入时的提示（已完成，2026-07-07）

六类新 adapter 落地后遗留的产品侧任务已实现（前端）：

- `SourcesPage.vue`：`manual/internal`（未配拉取入口）显示「推入式」徽标 + tooltip
  （定时抓取恒 0 条是正常行为）；`wechat` 未配 RSSHub/文章入口显示「待配置」徽标。
- 导入种子（legacy/tech）预览按 source_type 分组小计，并附推入式/微信语义提示
  （31 个 `wx://` 待补入口 metadata-only 源明示需先补配 RSSHub/文章入口）。
- `IngestionRunsPage.vue`：新增 `skipped_type_disabled`「类型停用」标签、run 提交后的
  类型停用分组 info 文案、run 详情「类型停用跳过 N 源 / 推入式 0 条 N 源」语义分组
  提示条与每源推入式徽标（API 未暴露 `fetch_config.api_url`，internal 以 url 入口
  作为可拉取代理信号，代码内有注释）。
- run 摘要中的 `skipped_unimplemented` 前端文案保留（未来新增未实现类型时的安全网）。

看护：`SourcesPage.spec.ts` / `IngestionRunsPage.spec.ts` 已覆盖对应组件测试。

## 4. 前端测试清单与 e2e 现状

前端测试基建：Vitest + @vue/test-utils + jsdom（`frontend/vitest.config.ts`）。
**已实际接入 `make test` 与 CI**（`.github/workflows/ci.yml` frontend job 的
Test frontend 步骤先于 build）。

当前 29 个 spec、231 个用例全绿（2026-07-07 实跑，`npx vitest run`）。
覆盖面（`frontend/src/**/*.spec.ts`）：

- 页面组件（24）：Account/AuditLogs/DailyReportDetail/DailyReports/Dashboard/
  EntityMilestones/Exports/HistoricalReports/IngestionRuns/Insights/Invite/Login/
  News/Notifications/QualityArchive/Recommendations/Requirements/Setup/
  SourceDetail/Sources/SyncRuns/TopicTasks/Users/WeeklyReports
- 壳与基建（5）：`layouts/AppShell.spec.ts`（顶部搜索/通知/部署徽标）、
  `router/index.spec.ts`（路由守卫/section 驱动/viewer 阅读视角重定向）、
  `stores/runtime.spec.ts`（能力降级默认值与 stale-backend 诊断分类）、
  `stores/session.spec.ts`（401 统一登出跳转 `installUnauthorizedRedirect`）、
  `api/http.spec.ts`（CSRF 自动附头、`BASE_URL=/watchtower/` 子路径前缀拼接、
  `onUnauthorized` 注册点与豁免路径）。

部署形态相关的前端看护点：runtime gate 关闭采集时隐藏入口、`limit<1` 本地拦截、
`no_sources` 警示、导入必须先 preview、read-only 隐藏写按钮、推入式徽标与
`skipped_type_disabled` 类型停用语义（§3.1）。

e2e 现状（2026-07-07 已真跑）：Playwright chromium 已下载并实跑
`frontend/e2e/smoke.e2e.ts`，3 条 smoke 全绿（<1s，复用已运行 dev server）。
用例统一 `*.e2e.ts` 命名与 Vitest 收集规则分离；smoke 用 `page.route` 打桩
`/api/**`，不依赖真实后端。首跑暴露并修复脚手架 bug：`**/api/**` glob 误拦
vite 源码模块 URL（如 `/src/api/http.ts`）导致整页白屏，stubApi 已对非 `/api/`
pathname 走 `route.fallback()` 放行（坑记录在 `frontend/e2e/README.md`）。
`make e2e` 为可选 target，不进 CI 门禁（chromium ~100MB 下载耗时，ci.yml 有注释）。
**尚未覆盖**真实后端的关键旅程（登录 → 导入预览 → 抓取 → 日报 → 同步 → 导出），
列为 P1 后续任务（`docs/architecture/capability-map.md` §4.2）。

## 5. 修改规则

- 改部署形态/能力开关：先改契约与 `deployment-topology.md`，再同步本文 §1/§2 矩阵。
- 新增 adapter：按 `docs/backend/extension-recipes.md` R2 配方，落地后更新本文 §3 状态表。
- 新增前端 spec 或 e2e 旅程：更新本文 §4 与
  `docs/product/page-specs/frontend-page-specs.md` 的页面测试看护标注。
