# 部署拓扑与联动同步规格（deployment-topology）

本文是写给实现者（人或 AI 编码代理）的**实现级规格**，定义 InfoWatchtower 的
四种部署形态、能力开关、嵌入与认证矩阵、内外网联动同步协议，以及同事系统
（tech-insight-loop）采集能力的融合方式。它是 `feat/deployment-topology`
分支及其后续工作的唯一验收基准。当前 P0 与 C 系工件（部署样例、TLS profile、
离线升级脚本、Playwright 脚手架）均已进入可验收实现态；剩余为实机验收动作
（见 `SESSION-HANDOFF.md` E 系清单）。四形态的必跑测试矩阵与禁用能力断言清单见
`docs/backend/backend-capability-test-matrix.md`。

本文只负责部署、运行时能力开关、网关安全和 extranet/intranet 联动同步协议。
它不定义前端页面布局，不定义用户权限运营页面，也不定义评论/通知的业务语义。

相关文档归属：

- 前端按部署形态隐藏/展示页面能力：`docs/product/frontend-product-design.md`
- 用户、SSO、内网 header、membership：`docs/backend/identity-access-design.md`
- 内外网同步数据边界和手工包 fallback：`docs/deployment/multi-environment-sync.md`
- 同步对象、字段和策略：`config/contracts/sync_strategy.json`
- 部署模式合法组合：`config/contracts/deployment_modes.json`

阅读顺序：`AGENTS.md` → `docs/00-system-design.md` → `docs/architecture/target-state-spec.md`
（WP1-WP3 已完成的账户/扩展/部署基线）→ 本文。

关联契约：`config/contracts/deployment_modes.json`（新增）、
`config/contracts/sync_strategy.json`（修订）、`config/contracts/auth_modes.json`（修订）。

## 0. 背景：为什么需要这份规格

用户目标态是同一套代码支撑四种部署，而现状只有 `AUTH_MODE` +
`INGESTION_SCHEDULER_ENABLED` 两个正交开关，"部署形态"没有一等抽象：

1. **本地一次拉取一键部署**：`git clone` → `deploy/install.sh --local` → 配好
   能力（含 wx 公众号等同事系统采集能力）即可用。当时现状：install 流程已通，
   但 11 个 source_type 只有 4 个有真实适配器，wechat 采集零迁入
   （2026-07 已收口：12 类全部真适配器，含 wechat，见 §5；install 预设见 §1.1）。
2. **云主机官方部署**：管理员采集，非管理员只读消费。现状：viewer 角色与
   membership 门已实现，缺形态定义与 TLS 收口。
3. **内网部署**：被内网门户 iframe 嵌入，外层已有工号+部门登录态，评论等
   交互复用外层登录；内网不便跑爬虫。现状：`intranet_header` 免密透传已实现，
   但 iframe 承载（frame-ancestors/CSRF/同站代理）零设计，且没有"禁采集"模式。
4. **外网部署**：业界标准 SSO（OIDC）登录，并开放数据下发接口。当前已实现通用
   OIDC authorization code flow + PKCE，以及机器对机器 feed 下发接口。
5. **联动**：内网实例 pull-only，定期 GET 外网实例的已采集/已成稿数据。
   现状：sync outbox/inbox 四表和手工同步包已实现，但生产代码从不写 outbox
   （导出恒空包）、无定时拉取、无机器鉴权、成稿对象不可同步。

## 1. 四种部署形态矩阵（总表）

引入单一环境变量 `DEPLOY_MODE`，由它派生一组能力开关（capability flags）。
**三层同时 gate：API 层按开关 403、scheduler 按开关投任务、前端按开关隐藏入口。**
只关其中一层都算未完成。

| 维度 | `standalone`（本地） | `cloud`（云官方） | `intranet`（内网嵌入） | `extranet`（外网发布者） |
|---|---|---|---|---|
| 场景 | 个人/团队本地 Docker 一键部署 | 云主机官方站，多人只读 | 内网门户 iframe 嵌入，pull-only | 公网站，SSO 登录，对内网下发数据 |
| 采集（API+scheduler+UI） | ✅ 开 | ✅ 开（仅 workspace admin+ 可触发） | ❌ **关**（API 403 + UI 隐藏 + scheduler 不投采集任务） | ✅ 开 |
| wx 桥接采集 | ✅ 可配 | ⚠️ 可配（合规自评后） | ❌ | ⚠️ 可配（合规自评后） |
| AUTH_MODE 合法值 | `local` / `public_password` | `public_password` / `oidc` | `intranet_header` | `oidc` / `public_password` |
| 会话与嵌入 | SameSite=lax | lax + TLS | lax + **同站反代承载 iframe** + CSP frame-ancestors 白名单 + CSRF | lax + TLS + CSRF |
| sync 角色 | 无（可选 publisher，便于本地调试联动） | 无 | **consumer**：pull worker 定时 GET extranet feed | **publisher**：`GET /api/sync/feed`，service token 鉴权 |
| 数据流向 | 自采自用 | 自采自用 | **只进不出**：评论/采信留本地，不回流（不变式，见 §7） | 采集 + 对 intranet 下发 |
| 默认角色策略 | 首管即超管 | 邀请制，默认 viewer | header 自动建号（`AUTH_AUTO_PROVISION=true`），默认 viewer | OIDC/邀请建号，默认 viewer |
| 网络 | 端口全暴露（本机） | 仅 443（TLS 收口） | backend 仅网关可达（部署强制），代理白名单兜底 | 443 + feed 端点 |
| 升级 | `upgrade.sh`（git pull） | 同左（后续补 GHCR 镜像） | **离线包/镜像导入**：`scripts/export_offline_bundle.sh` 出包 + `scripts/upgrade_offline.sh` 导入 | `upgrade.sh` |

### 1.1 启动预设（install.sh --preset，形态之上的 env 组合）

`deploy/install.sh --local|--domain <d> [--preset rss-only|full|mirror]`（默认 `full`）
在 `DEPLOY_MODE` 之上生成三种预设 env 组合（契约
`config/contracts/deployment_modes.json` 的 `install_presets`；三预设注释块见
`deploy/env.production.example` 顶部）：

| 预设 | env 组合 | 语义 |
|---|---|---|
| `full` | 不写 `INGESTION_SOURCE_TYPES`（空 = 全部允许） | 全量能力，默认值 |
| `rss-only` | `INGESTION_SOURCE_TYPES=rss,paper_rss` | 平台只抓 RSS 类信息源；run 内按允许清单过滤启用源，不在清单的源计入 run 摘要 `skipped_type_disabled`（非成功也非失败）；清单值必须是 `source_fields.json` 12 类 source_type 的子集，拼错启动拒绝 |
| `mirror` | `CAPABILITY_INGESTION=false` + `CAPABILITY_SYNC_CONSUMER=true` + `SYNC_PULL_ENABLED=true` + `SYNC_REMOTE_BASE_URL/SYNC_REMOTE_TOKEN`（必填）+ `INGESTION_SCHEDULER_ENABLED=false` | 本地不采集，只从我们的外部部署拉取成果；是 standalone/cloud 形态叠加 consumer override 的合法组合（启动自检与 `check_prod_deploy.py` 均校验），完整样例 `deploy/env.mirror.example`。install.sh 未提供远端地址/token 时写 `REPLACE_WITH_*` 占位并提示补填后重跑，不带占位值启动 |

### 1.2 部署事实：自动调度依赖 redis + worker + scheduler 三进程

任何形态要让"每日自动流水线/定时同步拉取"真实生效，都必须运行 redis、worker、
scheduler 三个进程；API 进程自身不投递也不执行定时任务。Docker Compose 部署
（`deploy/docker-compose.*.yml`）自带这三个服务，`install.sh` 起来即全量；
standalone 宿主机**裸跑**（不经 compose）必须手动起齐三进程，启动命令见
`docs/deployment/development-quickstart.md` §2.1。只跑 `uvicorn` 时手动触发可用、
自动调度静默失效；调度是否在跑必须可在界面自证（scheduler 心跳与下次运行，
设计见 `docs/backend/pipeline-jobs-design.md` §8.5-§8.6）。

## 2. WP4：DEPLOY_MODE 与能力开关

### 2.1 配置模型（`backend/app/core/config.py`）

```text
DEPLOY_MODE = standalone | cloud | intranet | extranet   # 默认 standalone

派生只读属性（Settings 上的 property，可被显式 env 覆盖）：
  capability_ingestion       bool  # standalone/cloud/extranet=True, intranet=False
                                   # 显式覆盖：CAPABILITY_INGESTION
  capability_sync_publisher  bool  # extranet=True, 其余=False
                                   # 显式覆盖：CAPABILITY_SYNC_PUBLISHER（standalone 调试用）
  capability_sync_consumer   bool  # intranet=True, 其余=False
                                   # 显式覆盖：CAPABILITY_SYNC_CONSUMER
  capability_embedding       bool  # intranet=True, 其余=False（信息性标识，仅经 /api/meta/runtime 下发；
                                   # frame-ancestors 恒由 EMBED_FRAME_ANCESTORS 控制，CSRF 默认由独立的
                                   # 形态表 MODE_CSRF_DEFAULTS 决定，均不从本开关派生）
  capability_search          bool  # 所有形态=True；只读检索，结果仍按 membership/部署能力过滤
```

新增同步/嵌入相关 env（详见 §3、§4）：

```text
INSTANCE_ID                    # 实例标识，默认按 DEPLOY_MODE 取 standalone|cloud|intranet|extranet
SYNC_SERVICE_TOKENS            # 逗号分隔的 service token 列表（publisher 侧校验用）
SYNC_REMOTE_BASE_URL           # consumer 侧：远端 extranet 实例地址
SYNC_REMOTE_TOKEN              # consumer 侧：携带的 Bearer token
SYNC_PULL_ENABLED              # consumer 侧定时拉取开关，intranet 默认 true
SYNC_PULL_INTERVAL_SECONDS     # 默认 900
SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED   # consumer 侧 failed inbox 自动 backoff，默认跟随 sync pull
SYNC_FAILED_INBOX_RETRY_BASE_SECONDS   # 默认 300
SYNC_FAILED_INBOX_RETRY_MAX_SECONDS    # 默认 3600
SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS   # 默认 5
SYNC_FAILED_INBOX_RETRY_LIMIT          # 默认 50
EMBED_FRAME_ANCESTORS          # CSP frame-ancestors 白名单，默认 'self'
AUTH_CSRF_ENABLED              # CSRF 强校验开关；intranet/extranet/cloud 默认 true，standalone 默认 false
AUTH_TRUSTED_PROXY_CIDRS       # 可信反代网段（逗号分隔 CIDR）。非空时身份头/限流 XFF 只信白名单直连 peer
AUTH_SESSION_SECRETS           # session secret 轮换列表（逗号分隔）：第一个签名、全部可验签，配置后覆盖单值
                               # AUTH_SESSION_SECRET；换密钥把新 secret 放第一位、旧的留尾部即可不掉线
INGESTION_SOURCE_TYPES         # 部署级采集类型允许清单（rss-only 预设用；空 = 全部允许）。run 内过滤启用源，
                               # 不在清单的源计入 run 摘要 skipped_type_disabled；非法值启动拒绝
OIDC_JWKS_URI                  # OIDC id_token 验签 JWKS 地址（缺省时用 issuer discovery 的 jwks_uri）
```

注：consumer 侧 pull 还有一个代码内固定回看窗口
`SYNC_PULL_REPLAY_LOOKBACK_SECONDS = 300`（`backend/app/sync/pull.py`，非 env），
用于补偿 publisher 侧长事务晚提交造成的水位漏发，见 §3.5。

### 2.2 启动自检（`backend/app/core/deploy_checks.py`，API/scheduler/worker 三入口共用）

非法组合必须**启动失败**（fail-fast，不是 warning）：

- `AUTH_MODE` 不在契约 `modes[DEPLOY_MODE].allowed_auth_modes` 白名单内
  （全矩阵校验：intranet 只允许 `intranet_header`；cloud/extranet 等公网形态拒绝
  `intranet_header`，否则等于开放请求头伪造登录）。
- `AUTH_SESSION_SECRET` 与 `AUTH_SESSION_SECRETS` 轮换列表同时为空（所有 auth_mode
  都签发签名 session cookie，缺 secret 必须启动失败而不是运行期每请求 500；
  任一非空即通过，轮换列表第一个即当前签名 secret）。
- `AUTH_TRUSTED_PROXY_CIDRS` 非空但含非法 CIDR（fail-closed）。
- `DEPLOY_MODE=intranet` 且 `CAPABILITY_INGESTION=true`（不允许覆盖打开）。
- `DEPLOY_MODE=extranet` 且 `SYNC_SERVICE_TOKENS` 为空（发布者必须有机器鉴权）。
- `capability_sync_consumer=true` 且 `SYNC_PULL_ENABLED=true` 但
  `SYNC_REMOTE_BASE_URL`/`SYNC_REMOTE_TOKEN` 缺失。
- `INGESTION_SOURCE_TYPES` 含未知 source_type（合法值为
  `config/contracts/source_fields.json` 的 12 类；清单拼错等于静默漏采，必须拒启）。
- `DEPLOY_MODE` 不在四值枚举内。

启动 warning（不拒启）：`AUTH_MODE=intranet_header` 但未配置
`AUTH_TRUSTED_PROXY_CIDRS`——此时身份头对任何直连 peer 可信，信任边界完全交给
网络拓扑（既有网关独占部署可继续启动，但日志会给出配置建议）。

### 2.3 API 门（`backend/app/api/deps.py` 或 auth 路由邻近处）

新增 dependency：

```python
def require_capability(name: str):  # 用法 Depends(require_capability("ingestion"))
    # 关闭时 raise HTTPException(403, detail={"code": "capability_disabled", "capability": name})
```

必须挂上 `ingestion` 门的端点（**在既有权限检查之外叠加**）：

- `POST /api/ingestion/runs`、`POST /api/ingestion/backfill-runs`
- `POST /api/sources/{id}/fetch`
- `POST /api/sources/import-legacy-seeds`、`POST /api/sources/import-tech-insight-loop`
- `POST /api/pipeline/daily-runs`（含采集阶段；intranet 消费的是远端成稿，不本地跑管线）

挂 `sync_publisher` 门的端点：`GET /api/sync/feed*`（§3）。
挂 `sync_consumer` 门的端点：`POST /api/sync/pull-runs`（手动触发一次拉取，§3.5）。

### 2.4 运行时能力下发（前端消费）

新增 `GET /api/meta/runtime`（免登录，无敏感信息）：

```json
{
  "deploy_mode": "intranet",
  "instance_id": "intranet",
  "capabilities": {"ingestion": false, "sync_publisher": false, "sync_consumer": true, "embedding": true, "search": true},
  "auth_mode": "intranet_header",
  "auth_membership_mapping": {
    "status": "configured",
    "default_workspaces": [{"workspace_code": "planning_intel", "workspace_role": "viewer"}],
    "department_workspaces": [{"department": "规划部", "workspace_code": "ai_tools", "workspace_role": "member"}]
  },
  "app_version": "0.1.0"
}
```

前端启动时拉取一次存入 Pinia（`useRuntimeStore`）：

- `capabilities.ingestion=false` 时：导航隐藏「抓取与覆盖」，数据源页隐藏
  「导入数据/导入 Tech 源/抓取」按钮与新增源入口（只读呈现源台账）。
- `capabilities.sync_consumer=true` 时：「同步运行」页展示同步健康、拉取水位、
  缺失/失败/滞后告警、上次拉取时间和手动「立即拉取」按钮。
- `auth_membership_mapping` 只下发默认工作台和部门 membership 映射摘要，供
  `/users` 策略页只读展示；不得包含 provider secret、token 或 cookie。
- 顶栏显示部署形态徽标（standalone 不显示，其余显示 cloud/内网/外网）。

## 3. WP5：联动同步（extranet 下发 / intranet 拉取）

### 3.1 路线判断（务必遵守，不要走回 outbox）

**下发接口基于业务表水位直查，不给主管线补 outbox 生产者。**理由：

1. outbox 的 pending→exported 独占消费语义与"无副作用可重放的 GET"冲突，
   也无法支持多个消费者。
2. 业务表已带 `global_id/revision/content_hash/updated_at`
   （`backend/app/models/common.py` IdMixin/ScopeMixin），直查零侵入主管线。
3. 同事系统已用同构协议（`updated_since + high_watermark + Bearer + 分页`，
   `references/参考工具/insight_loop/remote_api.py`）在真实数据上验证过。

**inbox 侧全部保留复用**：event_id 幂等、global_id upsert、revision/content_hash
冲突检测、密钥过滤（`backend/app/sync/apply.py` 的 `apply_sync_records` 系列，
feed pull 与手工包导入共用同一套 handler）是现成资产。
outbox/手工同步包保留为人工导出通道，不再扩展。

### 3.2 机器鉴权（service token）

- publisher 侧配置 `SYNC_SERVICE_TOKENS`（逗号分隔，允许多消费者/轮换重叠期）。
  条目支持 `name:token` 命名消费者（name 进审计日志，轮换/追责按名定位），也兼容
  纯 token（消费者名按位置记为 `token-<序号>`）。
- feed 侧 dependency `require_sync_feed_consumer`：校验 `Authorization: Bearer <token>`，
  `hmac.compare_digest` 逐一比对；失败 401。**不走 cookie session。**
- feed 端点仅受 service token + `sync_publisher` 能力门保护，与用户 RBAC 无关。
- **feed 访问审计**：manifest/page 每次读取都会写审计日志（action
  `sync_feed.manifest` / `sync_feed.read`），记录消费者身份、object_type、
  cursor 范围、record_count 和 has_more（cursor 是不透明水位，不含密钥）。
- 收紧存量：`GET /api/sync/packages/{id}/download` 从"任意登录用户"改为
  `require_super_admin`（外网部署下现状等于向所有用户开放全量 payload）。

### 3.3 下发端点（publisher 侧，extranet）

```text
GET /api/sync/feed/manifest
  → {"instance_id": "...", "object_types": [...按 §3.4 顺序...],
     "watermarks": {"data_sources": "<iso>", ...}, "server_time": "<iso>"}

GET /api/sync/feed?object_type=<t>&cursor=<c>&limit=<n=200,max 500>
  → {"object_type": "...",
     "records": [<envelope>...],          # 与 sync 包 records.jsonl 同构
     "next_cursor": "<opaque>" | null,    # 基于本页扫描到的最后一行生成（含被密钥/可见性
                                          # 红线过滤掉的行），records 可能为空而 next_cursor 非 null；
                                          # null 仅表示本次请求没有扫描到任何行
     "has_more": bool,
     "server_time": "<iso>"}
```

- **游标**：keyset 分页，`(updated_at, id)` 复合排序；cursor 为
  `base64(updated_at_iso + "|" + id)` 的不透明串。同一 cursor 重复请求返回
  相同结果（无副作用、可重放）。
- **过滤**：`visibility_scope != 'restricted'` 且 `sync_policy` 属于可导出集合
  （沿用 `EXPORTABLE_SYNC_POLICIES`）；envelope 生成复用同步包的记录构造逻辑，
  **含密钥字段过滤**（含 secret/token/password/cookie/.env 的 payload 不下发）。
- **禁止对象**：`requirements/topic_tasks/comments/reactions/ratings/activity_events/notifications`、
  `notification_preferences/export_jobs` 不属于 feed object types。`requirements/topic_tasks`
  和本地协作/通知对象已有负向测试，即使误设为 `public_to_intranet` 或 `sync_allowed`
  也不能通过 feed 下发。
- envelope 的 `event_id` 用确定性生成：`sha256(object_type|global_id|revision)`，
  保证"同一对象同一版本"重放幂等、新版本产生新 event_id。

### 3.4 同步对象与顺序（扩展 apply handler）

对象类型清单及**必须保证的应用顺序**（外键依赖）：

```text
1. data_sources
2. raw_items          （依赖 data_sources）
3. news_items         （依赖 raw_items, data_sources）
4. generated_news     （依赖 news_items）
5. daily_reports      （payload 内嵌 items：daily_report_items 含 adoption_status/is_headline）
6. weekly_reports     （payload 内嵌 items）
```

- apply handler（`app/sync/apply.py`）支持全部 6 类；5/6 的 items 随父对象整体 upsert
  （按 item 的 global_id 对齐，父对象 revision 冲突时整体进 sync_conflicts）。
- 前置迁移检查：确认 `generated_news/daily_reports/weekly_reports` 及 items 表
  已挂 IdMixin/ScopeMixin 同步字段；缺列则出 alembic 迁移。
- **红线**：公司 SQL 出口合同（十分类/五段字段/validate_company_sql.py）一字不动；
  同步只是把成稿数据搬到 intranet 库，不改变任何导出语义。

### 3.5 拉取执行（consumer 侧，intranet）

- 新表 `sync_cursors`：`object_type (pk) / cursor / last_pulled_at / last_status /
  last_error`。
- 拉取过程（`backend/app/sync/pull.py`）：按 §3.4 顺序逐对象类型分页
  GET → 每批喂 `app/sync/apply.py` 的 `apply_sync_records` 幂等落库 →
  批成功后持久化 cursor → 记入 `sync_runs`
  （mode=`api_pull`，counts 记 applied/skipped/failed/conflicts）。
- **回看窗口重放**（并发漏发补偿）：publisher 的 `updated_at` 在 ORM flush 时生成、
  事务 commit 后才对 feed 可见，长事务晚提交的行会落在 consumer 已推进的水位之前，
  严格大于过滤将永久漏发。补偿方案在消费端：每轮 pull 对每类对象的**第一页**把
  已持久化水位回退 `SYNC_PULL_REPLAY_LOOKBACK_SECONDS`（300 秒）重放重叠区间；
  重复事件由 inbox `event_id` 幂等终态（applied/skipped/conflict）吸收。翻页游标
  不回退，单轮内严格前进，不会死循环。publisher feed 保持无状态严格大于过滤，
  同 cursor 可重放语义不变。
- **冲突不卡水位**：`conflict` 是 inbox 终态（feed event_id 是
  `object_type|global_id|revision` 确定性哈希，同对象同版本只判一次冲突），
  出现冲突的页照常推进 cursor，也不中断后续对象类型；冲突处置走
  `/api/sync/conflicts` 闭环而不是重拉。open 冲突按 `(object_type, object_id)`
  幂等去重，重复判定只刷新既有 open 记录（seen_count/last_seen_at），
  不重复发通知。
- **传输失败落 run**：manifest/feed 页的传输异常（extranet 不可达、token 失效、
  4xx/5xx、非法 JSON）不裸抛——裸抛会让事务回滚连 run 一起丢。失败会落成
  `status=failed` 的 `sync_runs`（errors 摘要 + per_object `transport_failed`），
  feed 页级失败同时把 `sync_cursors.last_status` 置 `failed`，
  `GET /api/sync/health` 立刻可见。
- 健康摘要：`GET /api/sync/health`（super_admin + cookie session）基于
  `sync_cursors`、最近 `sync_runs` 和 open `sync_conflicts` 汇总 `ok/warning/critical/inactive`，
  告警缺失水位、滞后水位、失败水位、最近失败 run 和待处理冲突；阈值按
  `SYNC_PULL_INTERVAL_SECONDS` 的 2 倍/6 倍派生。
- 调度：`workers/scheduler.py` 在 `capability_sync_consumer && SYNC_PULL_ENABLED`
  时按 `SYNC_PULL_INTERVAL_SECONDS` 投递 `sync_pull` 任务到 RQ（复用现有队列）。
- 手动触发：`POST /api/sync/pull-runs`（super_admin + `sync_consumer` 门），
  同步执行一轮并返回摘要，供页面「立即拉取」。
- **inbox 幂等语义**：`apply_sync_records` 仅当既有 inbox 记录状态为终态
  `applied/skipped/conflict` 时跳过；`failed` 记录保留 `record_json`，允许通过
  `POST /api/sync/inbox/retry-failed` 重放重试（外键顺序失败可自愈，不会永久卡死）。

## 4. WP6：内网 iframe 嵌入与安全底座

### 4.1 承载方式：同站反向代理（架构决策，不走 SameSite=None）

内网门户以**同站路径反代**承载本系统：门户 nginx 把
`https://portal.example.com/watchtower/` 代理到 InfoWatchtower 前端容器，
`/watchtower/api/` 代理到 backend。iframe 的 src 与门户同源（同站），
SameSite=lax cookie 原样可用，**禁止**放开 SameSite=None（等于在无 CSRF
防护的系统上打开跨站写攻击面）。

四项配套改动均已实现：

1. **前端 base path 可配**（已实现）：`VITE_BASE_PATH`（默认 `/`）在构建期注入，
   `frontend/vite.config.ts` 的 `base`、vue-router
   `createWebHistory(import.meta.env.BASE_URL)` 与统一 http client
   （`frontend/src/api/http.ts` 的 `apiUrl`）三处同时生效；镜像构建用
   `docker build --build-arg VITE_BASE_PATH=/watchtower/`，intranet compose
   默认透传该 build arg。
2. **CSP frame-ancestors**（已实现）：`EMBED_FRAME_ANCESTORS`（默认 `'self'`）。
   backend SecurityHeadersMiddleware 对所有响应设
   `Content-Security-Policy: frame-ancestors <值>`；`frontend/nginx.conf` 是
   nginx 官方镜像的 envsubst 模板（Dockerfile 拷到
   `/etc/nginx/templates/default.conf.template`），HTML 文档响应处输出同一
   header（浏览器真正执行点），值由容器 env 运行期注入。
3. **部署样例**（已实现）：`deploy/nginx.portal.example.conf` 演示门户侧
   同站反代 + 注入 `X-Employee-No/X-Employee-Name/X-Department/X-Email` 头；
   `deploy/docker-compose.intranet.yml` 默认把前端/backend 只绑门户主机回环。
4. **网关信任边界**（已实现）：intranet 形态 backend 不得绕过网关直连（intranet
   compose 不映射 backend 端口到宿主机外网卡）。进程内兜底
   `AUTH_TRUSTED_PROXY_CIDRS` 已生效：非空时身份头只信白名单直连 peer（不受信
   peer 按未登录 401），未配置保持旧行为并打启动 warning，非法 CIDR 拒启；
   登录限流取 IP 共用同一判定（只有受信 peer 递来的 X-Forwarded-For 才采信）。
   同时 `frontend/nginx.conf` 反代 `/api/` 时会把外部传入的身份头置空清洗，
   防止 standalone/cloud/extranet 直连入口被伪造工号穿透。

### 4.2 外层登录态复用（评论等交互）

`intranet_header` 模式已实现"网关注入工号/姓名/部门头 → 自动建号 → 签发本地
cookie"。iframe 同站承载后该链路原样可用：用户在门户登录一次，iframe 内所有
API 请求经门户网关注入身份头，评论/点赞/评分自然携带外层身份（落到本地
`users` 表，`department` 字段已有）。**评论数据留在 intranet 库，不回流**（§7）。

### 4.3 CSRF（双提交 cookie 模式）

- 登录成功/`GET /api/auth/me` 时下发非 HttpOnly 的 `infowatchtower_csrf` cookie
  （随机值，与 session 无关联即可，双提交模式）。
- `AUTH_CSRF_ENABLED=true` 时，middleware 对非安全方法（POST/PUT/PATCH/DELETE）
  校验 `X-CSRF-Token` 头与 cookie 一致，不一致 403（豁免：`/api/auth/login`、
  `/api/setup`、`/api/sync/feed*`、`/api/exports/{id}/import-receipts/callback`
  等 token 鉴权端点）。
- 默认值按形态：intranet/extranet/cloud 默认 true，standalone 默认 false。
- **前端配套**：把 11 个 api 模块各自复制的 `requestJson` 收敛到统一
  `frontend/src/api/http.ts`，unsafe 方法自动从 cookie 读 CSRF 值附头。
  这也是后续 OIDC/嵌入登录改造的唯一挂点。

### 4.4 外网 SSO（OIDC，已实现通用 code flow）

`AUTH_MODE=oidc` 走标准 authorization code flow + PKCE：
`GET /api/auth/oidc/start` 生成 `state/nonce/code_verifier` 并跳 IdP；
`GET /api/auth/oidc/callback` 校验 state、交换 token、读取 userinfo（或 id_token
payload 兜底）、按 `external_provider=<OIDC_PROVIDER> + sub` 查/建用户（复用
`AUTH_AUTO_PROVISION`/`AUTH_DEFAULT_ROLE`），最后签发既有本地 cookie。

env：`OIDC_ISSUER/OIDC_CLIENT_ID/OIDC_CLIENT_SECRET/OIDC_SCOPES/OIDC_REDIRECT_URL/
OIDC_PROVIDER/OIDC_POST_LOGIN_REDIRECT_URL`；也可显式给
`OIDC_AUTHORIZATION_ENDPOINT/OIDC_TOKEN_ENDPOINT/OIDC_USERINFO_ENDPOINT` 跳过 discovery。
`AUTH_MODE=oidc` 缺 `OIDC_CLIENT_ID` 或 issuer/显式端点时启动失败。

id_token 校验（已实现，`backend/app/auth/oidc.py` `verify_id_token`）：token 端点一旦
返回 id_token 即整体校验——拒绝 `alg=none`；有 JWKS（`OIDC_JWKS_URI` env 或 issuer
discovery 的 `jwks_uri`）时用纯标准库 RSASSA-PKCS1-v1_5 验签 RS256/384/512（按 kid
匹配 JWK，配置了 JWKS 但 alg 非 RS* 时拒绝）；无 JWKS 时强校验 iss/aud/exp/nonce
（nonce 必须存在且匹配）。userinfo 主路径下 id_token nonce 依然强制校验；userinfo
本身不需 nonce（服务端直连 TLS 通道 + PKCE 绑定）。

## 5. WP7：同事系统采集能力融合（tech-insight-loop）

定位不变：InfoWatchtower 是唯一主系统，**按能力逐块移植，不运行旧 app.py**。
前四轮已完成资产迁移（386 源台账、content_scorer_v2 配置、历史数据、界面融合）。
本节补齐**能力迁移**：

| 能力 | 进入形式 | 状态 |
|---|---|---|
| wx 公众号采集 | **wechat 自研 adapter 已落地**（rsshub 主路径 + article_urls 定点抓取，§5.1）；wx 桥接 sidecar 降级为可选增强 | adapter 已完成（2026-07）；wx 桥（C-1）待同事确认二进制事实 |
| 论文 API 日期窗回填 | `paper_api` arXiv v1、OpenAlex Works v1、Semantic Scholar bulk search v1 真适配器已替换 stub；更多论文 provider 后续扩展 | 已完成 v1 |
| content_scorer/quality_gate | 纯函数移植，挂 news 归一化后可选评分阶段 | C-2 |
| 远程增量同步协议 | 已吸收为 §3 feed 协议蓝本（不搬代码） | 本规格 |
| RSS/RSSHub/去重/报告 | 不引入（InfoWatchtower 已有且更好） | 关闭 |
| brief-PPT / GitHub PR 推送 | 不搬（硬编码同事内网 IP/个人仓） | 关闭 |

### 5.1 wechat adapter（已落地）与 wx 桥接契约（可选增强）

**2026-07 更新**：第 12 类 `wechat` source_type 已由自研 `WeChatMpAdapter`
（`backend/app/adapters/wechat.py`，契约 `config/contracts/source_fields.json`
fetch_config_conventions.wechat 与 `adapter_pipeline.json` wechat_discovery_rule）
落地，**不依赖同事的 wx 二进制**，两条路径：

1. **rsshub 模式（主路径，账号级增量）**：`fetch_config.feed_url` 完整 RSS 地址，
   或 `rsshub_route`（实例 base 依次取 `rsshub_base` → `rsshub_base_env` → 全局
   `RSSHUB_BASE_URL` → 公共 rsshub.app 兜底），或仅给账号标识
   （`account_name/account_username/wx_account`）按 `rsshub_route_template`
   （默认 `/wechat/mp/{account}`）推导路由；RSS 解析复用 `rss.py`，不复制逻辑。
2. **article_urls 模式（定点抓取）**：给定 mp.weixin.qq.com 文章 URL 列表直接抓
   文章页解析（og meta/正文/发布时间/账号名，合集页自动枚举），URL 规整成稳定
   entry_key；风控验证页显式抛错记失败，不落 raw_items。

发现边界：无登录态时公众号历史目录不可直接枚举，账号级增量发现依赖自建
RSSHub/微信转 RSS 桥（rsshub 模式）或下述 wx 桥。凭据走
`credential_ref → auth_token_env → auth_token`。台账里 31 个「微信公众号(wx-cli)」
metadata_only 源补配任一入口后即可启用。能力边界不变：wechat adapter 只在
`capability_ingestion=true` 的形态可用；extranet/cloud 启用前须自评公众号非官方
抓取的合规风险（默认建议仅 standalone）。

wx 桥接 sidecar 降级为**可选增强**（提升账号级发现能力，非前置）。物理约束：
wx CLI 依赖登录微信的 Windows 机器 + 本地数据库文件，**不可进容器**。
融合方式是"外部桥 + 契约"：

- **桥（bridge）**：跑在有微信登录态的宿主机上的小 HTTP 服务（C-1 交付一个
  `scripts/wx_bridge/` 参考实现，Python 标准库即可），包装
  `wx biz-articles --account <a> --since <d> --until <d> -n <N> --json`：

```text
POST {WX_BRIDGE_URL}/fetch   Authorization: Bearer <WX_BRIDGE_TOKEN>
  {"account": "公众号名", "since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "limit": 50}
  → {"articles": [{"account","title","url","digest","timestamp","cover_url",
                   "content_html"?}]}
```

- **桥接入 adapter 的方式**：wechat adapter 的 config 设计不排斥桥——
  `wx_account/account_name/account_username` 与 `window_days` 字段与桥接契约共用，
  桥地址与 token 用实例级 env（`WX_BRIDGE_URL/WX_BRIDGE_TOKEN`）；桥落地后可在
  **不改源配置**的前提下把主路径从 rsshub 升级为桥拉取。桥返回缺 `content_html`
  时 adapter 直接抓 `mp.weixin.qq.com` 文章页抽正文兜底（该正则已随
  article_urls 模式落地）。产出走标准 `raw_items` upsert。
- **未决前置（仅针对桥）**：wx 二进制的获取方式/登录态维持/是否可跑 Linux，
  文档缺失，写桥前必须先向同事确认（C-1 的外部阻塞点；adapter 本体已不被阻塞）。

### 5.2 全部 12 类 source_type 已有真适配器 + stub 显式语义保留

原 6 个 EmptyAdapter 桩（wiseflow/crawler/csv/paper_page/manual/internal）已全部由
真适配器替换，第 12 类 `wechat` 也已落地（`backend/app/adapters/` 的
wiseflow.py/crawler.py/csv_file.py/paper_page.py/push_based.py/wechat.py；
实现状态表见 `docs/backend/backend-capability-test-matrix.md` §3）。其中
`manual/internal` 是推入式语义：条目由 manual-import / 内部系统写入，定时抓取
如实返回 0 条新增（成功、非失败）；`internal` 配置 `api_url` 后升级为通用 JSON
API 拉取器。`paper_api` 由 arXiv v1、OpenAlex Works v1 和 Semantic Scholar bulk
search v1 承接。前端已对推入式源展示「推入式」徽标与导入预览分组语义提示
（`backend-capability-test-matrix.md` §3.1，已完成）。

run 层的 `skipped_unimplemented` 显式语义保留为安全网：任何未来注册但未实现的
adapter 参与 run 时，该源 outcome 记 `skipped_unimplemented`（不算成功也不算失败），
run 摘要写 `source_skipped_unimplemented`，前端明示"N 个源类型尚未实现采集"
（`app/adapters/stubs.py` 仅供该语义的回归测试注册，禁止进默认注册表）。
与之并列的 `skipped_type_disabled`（部署级 `INGESTION_SOURCE_TYPES` 允许清单
过滤，rss-only 预设）语义见 §1.1 与 `adapter_pipeline.json` type_allowlist_rule，
前端在 run 详情以「类型停用」标签与分组提示条呈现。

## 6. 采集"0 结果"语义修复（配合前端测试补齐）

这是用户实测暴露问题的修复规格，前后端必须一致实现：

1. **run 无源即警示**：`run_workspace_ingestion` 选中 0 个源时，run 状态记
   `no_sources`（新枚举，非 completed），响应带
   `hint`（"当前工作台无启用源或类型过滤后为空"）。前端把
   `no_sources` 渲染为警告样式并给出排查指引。
2. **limit 语义**：`POST /api/ingestion/runs` 的 `limit` 改为 `ge=1 | null`
   （null=全量）；`limit=0` 直接 422。测试必须覆盖 `limit=0` 负向用例和
   源类型筛选后无启用源的 `no_sources` 用例。
3. **引入需要确认与预览**：新增 `GET /api/sources/import-preview?catalog=legacy|tech`
   （super_admin），返回 `{total, would_create, would_update, samples: [前10条
   name/type/url]}`，**不落库**。前端"导入数据/导入 Tech 源"点击后先弹预览
   对话框（显示将新增/更新数），确认后才 POST 导入。
4. **引入结果文案区分**：`created>0` 成功绿；`created==0 && updated>0` 信息蓝
   （"源已全部存在，本次更新 N 条元数据"）；`total==0` 警告黄（提示种子路径/
   环境排查）。
5. **发起抓取前置校验**：抓取页发起 run 前拉当前工作台启用源计数
   （SourcesPage 已有 `enabledInWorkspaceCount` 逻辑），为 0 时直接本地警告
   不发请求。

## 7. 不变式（新增，与 AGENTS.md 既有不变式并列生效）

1. 同步方向单向：extranet → intranet。intranet 的评论/点赞/评分/采信/需求
   **永不回流**公网实例。
2. intranet 形态不采集：`capability_ingestion=false` 不可被 env 覆盖打开。
3. feed 端点无副作用、可重放；只走 service token，不走 cookie session。
4. 同步不改变公司 SQL 出口合同：十分类、五段字段、validate_company_sql.py
   校验、`adoption_status=2` 过滤规则在 intranet 侧原样成立。
5. 密钥/token/cookie/.env 不进同步包、不进 feed（既有不变式在 feed 路径复述）。
6. iframe 嵌入只允许同站反代承载；不放开 SameSite=None。
7. raw_payload_json 完整性、去重时序、adoption 层归属等既有主链路不变式
   全部继续成立（见 `AGENTS.md`）。

## 8. 验收标准

### WP4（形态与开关）

- `DEPLOY_MODE=intranet` 启动：`POST /api/ingestion/runs` → 403
  `capability_disabled`；`GET /api/meta/runtime` 返回 ingestion=false；
  前端导航无「抓取与覆盖」，数据源页无导入/抓取按钮。
- `DEPLOY_MODE=intranet` + `CAPABILITY_INGESTION=true` → 启动失败。
- `DEPLOY_MODE=extranet` 无 `SYNC_SERVICE_TOKENS` → 启动失败。

### WP5（联动）

- extranet 实例：无 token GET `/api/sync/feed?object_type=data_sources` → 401；
  带合法 token → 200 且分页游标可重放（同 cursor 两次结果一致）。
- 端到端：extranet 实例造数（源→raw→news→generated→已发布日报）→ intranet
  实例执行一轮拉取 → 六类对象全部落库、`sync_runs` 记 api_pull、
  `sync_cursors` 水位前进；再拉一轮全部 skipped（幂等）。
- 外键顺序容错：故意先拉 news_items 失败后，`sync_inbox.record_json` 保留 envelope，
  依赖补齐后通过 `POST /api/sync/inbox/retry-failed` 本地重放可自愈。
- intranet 侧日报正文/成稿可读，公司 SQL 导出校验通过。

### WP6（嵌入与安全）

- 所有响应含 `Content-Security-Policy: frame-ancestors <配置值>`。
- `AUTH_CSRF_ENABLED=true` 时无 `X-CSRF-Token` 的 POST → 403；前端统一
  http client 自动附头后全流程正常。
- intranet_header 模式：带工号/部门头的请求自动建号并可评论，评论者
  display_name/department 来自外层头。

### §6（0 结果语义）

- 0 启用源工作台发起 run：后端 `no_sources`、前端警告文案（有测试看护）。
- `limit=0` → 422。
- 引入弹预览对话框、确认后导入、重复导入显示"更新 N"而非"新增 0"成功绿
  （组件测试看护）。

## 9. 实施分期

### P0（核心框架，当前已落地并有测试看护）

- P0-1 本规格 + 契约（`deployment_modes.json` 新增、`sync_strategy.json`/
  `auth_modes.json` 修订）。
- P0-2 DEPLOY_MODE + capability flags + 启动自检 + `require_capability` 门 +
  `GET /api/meta/runtime` + 前端 runtime store 与 UI gate。
- P0-3 service token + `GET /api/sync/feed(/manifest)` + 游标 + download 收权。
- P0-4 apply handler 扩到成稿三类（含迁移检查）+ failed inbox 本地重放重试。
- P0-5 `sync_cursors` + pull worker + `POST /api/sync/pull-runs` + scheduler 投递。
- P0-6 SecurityHeadersMiddleware（frame-ancestors）+ CSRF middleware +
  前端统一 http client。
- P0-7 §6 全部（后端语义 + 前端对话框/警示 + 双端测试）+ 前端测试基建
  （vitest + @vue/test-utils，纳入 `make test`）。

### C 系（交编码代理，见 `docs/implementation/implementation-handoff.md` 进度节）

- C-1 已部分完成：wechat adapter 已自研落地（rsshub 主路径 + article_urls
  定点抓取，§5.1，不依赖 wx 二进制）；剩余 wx 桥 sidecar 为可选增强
  （外部前置：向同事确认 wx 二进制事实）。
- C-2 content_scorer/quality_gate 纯函数移植。
- C-3 已完成：paper_api(arXiv/OpenAlex/Semantic Scholar) 真适配器 + §5.2 stub 显式语义；
  wiseflow/crawler/csv/paper_page/manual/internal 六类真适配器也已落地（§5.2）；
  后续只剩 OpenReview 等更多论文 provider。
- C-4 建台后补链共享源（向导步骤 + 批量链接 API）。
- C-5 已完成：通用 OIDC provider code flow + PKCE + id_token 验签/强校验（§4.4）；
  后续只剩具体企业 claims 字段适配与真实 provider 实机验收。
- C-6 已完成工件交付：prod TLS 收口走可选 caddy profile
  （`deploy/docker-compose.prod.yml` `--profile tls` + `deploy/Caddyfile` 按
  `CADDY_DOMAIN` 自动 ACME）；intranet 离线升级走
  `scripts/export_offline_bundle.sh`（docker save 全镜像 + 校验和）+
  `scripts/upgrade_offline.sh`（校验 → docker load → compose up 自动迁移）。
  剩余：真实域名证书签发与离线升级实机演练（E 系）。
- C-7 已完成：sync conflicts 查询/resolve 端点 + 前端处置 UI。
- C-8 脚手架已交付：Playwright 配置（`frontend/playwright.config.ts`）与
  `frontend/e2e/smoke.e2e.ts`（`page.route` 打桩 `/api/**`，与 Vitest 收集规则分离）；
  真实后端主流程旅程（登录→导入→抓取→日报→导出）仍待补。
- C-9 文档批量刷新收尾与验收证据归档（本轮完成文档面；实机证据见 SESSION-HANDOFF E 系清单）。

依赖：P0-2 → {P0-3 → P0-4 → P0-5, P0-6} → C 系全部；C-1 可并行启动调研。
