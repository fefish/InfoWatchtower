# Generation Provider 生成模型配置与连通性设计

> 状态：§1-§7 基线已实现（2026-07-07 设计定稿，2026-07-08 实现落地；验收断言由
> `backend/tests/test_generation_provider.py` 看护）。
> **§8-§10 R2 修订已实现（2026-07-08 设计定稿、同日 WP4-B 实现落地）：Provider
> 预设目录（`config/contracts/llm_providers.json`，`GET /api/generation/providers`
> 投影）+ 密钥 UI 落库（`llm_provider_credentials`，迁移 `f2b3c4d5e6a7`，加密在
> `backend/app/core/crypto.py`，含决策变更记录 D-2026-07-08-KEY）；§10 验收断言由
> `backend/tests/test_credentials_api.py` 逐条看护。**
> 本文是 LLM 生成 provider 配置、工作台生成策略（`generation_policy`）和连通性
> 自检的后端模块事实源。
> 生成 prompt/字段结构仍以 `docs/backend/report-renditions-design.md` 与
> `config/contracts/report_renditions.json` 为准；模板驱动生成见
> `docs/backend/reports-editorial-design.md` §8.1。密钥治理边界见
> `docs/backend/security-secrets-privacy-design.md`。

## 1. 模块定位与用户问题

用户原话（第一轮）："我在哪里配置用的这个 ai 的 base url 和 key 呢？？"
用户原话（R2 追加）："市面上常用的都提供，最后有个兜底的 baseurl 和 key 的填法"
——即 **UI 里可以直接选 provider、填 base_url 和 key**。

本文的直接回答（R2 修订后目标态）：

- **首选路径：工作台配置中心「生成模型」卡里配**——provider 预设下拉（市面常用
  9 家，§8）→ base_url 预填可改 → key 输入（加密落库 `llm_provider_credentials`，
  §9，写后只回显 masked 后 4 位）→ 模型下拉 + 自定义 → 一键测试连通。
- **兜底路径：实例级 `.env`（`GENERATION_*` 族）**，用于自动化部署与"不想让
  key 进数据库"的场景；`MINIMAX_*` 兼容链保留。
- 解析优先级：工作台 `generation_policy.credential_id` 选中的落库凭据 →
  实例 env（§9.4）。
- 配没配对，用 `POST /api/generation/ping` 一键自检（支持按 credential 测试），
  结果直接显示在卡片上。

## 2. 现状事实（2026-07-08 R2 侦查结论，设计差距基于此）

- 生成客户端只有一条 OpenAI-compatible `chat/completions` 链路：
  `backend/app/llm/provider.py` 的 `request_chat_completion`（`minimax.py` 的
  基稿生成与 `reports/generation_template.py` 的模板增量生成都走它）。
- provider 值域只有两个：`backend/app/core/config.py` `GENERATION_PROVIDERS =
  ("openai_compatible", "minimax")`；没有市面常用 provider 的预设目录，
  用户想换 OpenAI/DeepSeek/Moonshot 必须手工拼 env。
- key 只能放实例 env：`GENERATION_API_KEY` / `GENERATION_API_KEY_REF`
  （`env:VAR`/`file:/path`，`backend/app/core/credentials.py`）回退
  `MINIMAX_API_KEY`；**没有任何 UI 能填 key**——「生成模型」卡只能显示
  "已配置/未配置"（`frontend/src/pages/WorkspaceSettingsPage.vue`）。
- 数据库没有凭据表；`workspaces.config_json.generation_policy` 明确禁止
  key/base_url/provider 字段（PATCH 遇 secret-like 字段 422）。
- 启动 fail-fast（`backend/app/core/deploy_checks.py`，契约
  `config/contracts/deployment_modes.json` `startup_failfast_rules`）：
  `GENERATION_ENABLED=true` 且 key 为空即拒启——与"运行期在 UI 里补配 key"
  的目标态直接冲突，R2 要修订（§9.6）。
- `AUTH_SESSION_SECRET` 已支持轮换列表 `AUTH_SESSION_SECRETS`（逗号分隔，
  首个为当前签名 secret，`Settings.auth_session_secret_list`）——§9.3 的
  Fernet 派生复用该轮换语义。
- 每日预算闸门已实现：`generation_daily_usage` 表 +
  `backend/app/llm/budget.py` `GenerationRuntime.try_acquire_call`
  （按 `(workspace_code, day_key)` 计数，成功+失败都计）。
  R1 推荐轨的设计延伸（待实现，契约
  `config/contracts/recommendation_ranking.json` `budget_and_degradation`）：
  该表增加 `purpose` 列分桶（`generation | rerank | rubric_compile`），
  `daily_generation_budget` 只管 `purpose=generation` 桶（基稿 + 逐条模板
  格式化），精排与导向编译各有独立配额、互不挤占。

## 3. 分层配置模型（R2 修订：新增凭据层）

```text
第 0 层 Provider 预设目录（config/contracts/llm_providers.json，随代码发布）
  9 家 provider 的默认 base_url、鉴权 header 形态、常用模型清单；
  只是 UI 预填与下拉数据，不是安全边界（§8）

第 1 层 实例 env（兜底密钥存放处，改动需重启进程）
  GENERATION_PROVIDER / GENERATION_BASE_URL / GENERATION_API_KEY(_REF) /
  GENERATION_MODEL 等实例默认值

第 1.5 层 落库凭据 llm_provider_credentials（instance 级 DB 表，super_admin
  在 UI 管理，运营期可改，无需重启；§9）
  provider + base_url + key_encrypted（Fernet at rest）+ label；
  被工作台 generation_policy.credential_id 引用时优先于第 1 层

第 2 层 工作台 generation_policy（存 workspaces.config_json.generation_policy，
  运营可改）
  credential_id（凭据引用，R2 新增）、模型名、温度、max_tokens、超时、
  每日预算、fallback 行为；**key 明文永不出现在这一层**（credential_id
  只是指针，secret-like 字段 PATCH 仍 422）

第 3 层 单次调用 resolved 参数
  credential_id 命中 → provider/base_url/key 取凭据行；否则取实例 env；
  generation_policy 非 null 字段覆盖模型参数默认 → 传给 provider client
```

### 3.1 实例级 env 规格

| env | 取值/默认 | 语义 |
|---|---|---|
| `GENERATION_ENABLED` | bool，默认 false | 模型生成总闸；false 时全链路规则降级（现 `MINIMAX_GENERATION_ENABLED` 语义不变） |
| `GENERATION_PROVIDER` | R2 修订：值域扩展为 §8 目录全部 code（`openai / anthropic / deepseek / moonshot / zhipu_glm / minimax / openrouter / ollama / custom`），旧值 `openai_compatible` 保留为 `custom` 的 deprecated 别名；默认 `minimax` | provider 预设。全部共用同一 OpenAI-compatible chat/completions 客户端；除 `custom`（及别名 `openai_compatible`）外都自带目录默认 base_url，`custom` 必须显式给 `GENERATION_BASE_URL` |
| `GENERATION_BASE_URL` | url | provider 基地址；`/chat/completions` 自动补全沿用现有 `_chat_completions_url` 规则 |
| `GENERATION_API_KEY` | str | Bearer key 明文（仅 env） |
| `GENERATION_API_KEY_REF` | `env:VAR` \| `file:/path` | credential_ref 语法（复用 `backend/app/core/credentials.py`）；与 `GENERATION_API_KEY` 同配时 REF 优先 |
| `GENERATION_MODEL` | str，默认 `MiniMax-M2.7-highspeed` | 实例默认模型名 |
| `GENERATION_MAX_TOKENS` | int，默认 3200 | 实例默认 |
| `GENERATION_TEMPERATURE` | float，默认 0.4 | 实例默认 |
| `GENERATION_TIMEOUT_SECONDS` | float，默认 45 | 单条生成超时实例默认（现 pipeline 传 45.0 的参数化） |
| `GENERATION_RETRY_TIMES` / `GENERATION_RETRY_BACKOFF_SECONDS` | 3 / 8.0 | provider HTTP 层重试（529 等），与 run 级重试（pipeline-jobs §6）无关 |

兼容规则（一个发布周期的过渡期）：

- `GENERATION_*` 未配置时逐字段回退读同名 `MINIMAX_*`（`GENERATION_ENABLED` ←
  `MINIMAX_GENERATION_ENABLED`，`GENERATION_API_KEY` ← `MINIMAX_API_KEY`，……）；
  两者都配时 `GENERATION_*` 优先。`MINIMAX_*` 标记 deprecated，样例 env 全部
  切到 `GENERATION_*`。
- 启动自检（当前已实现行为）：`GENERATION_ENABLED=true` 且 key（含 REF 解析后）
  为空 → 启动失败并给修复指引；`GENERATION_PROVIDER=openai_compatible` 且
  `GENERATION_BASE_URL` 为空 → 启动失败。已实现于
  `backend/app/core/deploy_checks.py`，规则登记在
  `config/contracts/deployment_modes.json` `startup_failfast_rules`
  （该清单与已实现自检保持 1:1；2026-07-08 已从
  `planned_startup_failfast_rules` 迁入）。
  **R2 修订（随 §9 落库凭据一起实现）**：key 可能在运行期通过 UI 落库，启动时
  无法断言最终配置，"enabled 且 env key 为空"从拒启降级为启动 WARNING +
  「生成模型」卡引导（§9.6）；`custom`（含别名 `openai_compatible`）缺
  `GENERATION_BASE_URL` 与 provider 值不在目录内两条 fail-fast 保留。实现落地时
  同步 `deployment_modes.json` `startup_failfast_rules`（保持与已实现自检 1:1）。

### 3.2 工作台 `generation_policy` 字段规格

存放：`workspaces.config_json.generation_policy`（与 label/feedback/report/
schedule policy 同级）。契约：`config/contracts/workspace_model.json`
`generation_policy`。

```json
{
  "credential_id": null,
  "model": null,
  "temperature": null,
  "max_tokens": null,
  "timeout_seconds": null,
  "daily_generation_budget": null,
  "fallback_behavior": "rule_fallback"
}
```

| 字段 | 取值 | 语义 |
|---|---|---|
| `credential_id` | `null\|str(global_id)`（R2 新增，已实现） | 引用 `llm_provider_credentials` 一行（§9）；`null`=用实例 env 链。只是指针不是密钥：PATCH 校验该 id 存在且 `enabled=true`，否则 422；引用的凭据被禁用/删除后按"未配置 key"降级（§9.4），不报错阻塞 |
| `model` | `null\|str(≤64)` | 本工作台模型名；`null`=实例默认（凭据不携带模型名，模型参数仍走本层/env 分层） |
| `temperature` | `null\|float(0..2)` | 同上 |
| `max_tokens` | `null\|int(256..8192)` | 同上 |
| `timeout_seconds` | `null\|float(5..300)` | 单条生成超时 |
| `daily_generation_budget` | `null\|int(1..1000)` | 本工作台每日模型调用条数上限；`null`=不限。计数按 `(workspace_code, day_key)` 统计当日模型调用（成功+失败都计），超出后本日剩余条目按 `fallback_behavior` 处理，run summary 记 `generation_budget_exhausted` 计数 |
| `fallback_behavior` | `rule_fallback`（默认）\| `fail` | provider 不可用/超时/预算尽时：`rule_fallback`=产 rule_v1 降级稿（`fallback_needs_review`，现状语义，不进公司 SQL）；`fail`=不产降级稿，generation step 记 failed，条目留待 `regenerate-generated-news` 重跑 |

## 4. API 设计（R2 修订：凭据 CRUD + 目录 + ping by credential）

```text
GET   /api/workspaces/{code}/generation-policy    workspace viewer+ 读
PATCH /api/workspaces/{code}/generation-policy    workspace admin+ 或 super_admin 写；
                                                  取值域校验 422；
                                                  审计 workspace.generation_policy.update（before/after）

POST  /api/generation/ping                        super_admin 或 editor_admin

# R2 新增（已实现，backend/app/api/routes/credentials.py + generation.py）
GET   /api/generation/providers                   登录即可读；返回 §8 预设目录
                                                  （llm_providers.json 原样投影，无任何密钥字段）
GET   /api/generation/credentials                 super_admin 或 editor_admin；
                                                  列表永只含 masked 视图（§9.5）
POST  /api/generation/credentials                 super_admin；body {provider, base_url?,
                                                  api_key, label}；base_url 缺省取目录默认，
                                                  custom 必填；审计 generation.credential.create
PATCH /api/generation/credentials/{id}            super_admin；label/base_url/enabled/api_key
                                                  可改（api_key 传新值即整体替换重加密）；
                                                  审计 generation.credential.update
DELETE /api/generation/credentials/{id}           super_admin；软删（enabled=false +
                                                  disabled_at），被引用时仍可禁用（§9.4 降级）；
                                                  审计 generation.credential.disable
```

`GET generation-policy` 响应除策略本身外必须带只读的 resolved 状态，供
「生成模型」卡不打 ping 也能展示；R2 增加凭据指针与可选凭据清单
（workspace admin+ 才返回 `credential_options`，viewer 只见 resolved）：

```json
{
  "policy": { "...": "..." },
  "resolved": {
    "provider": "minimax",
    "model": "MiniMax-M2.7-highspeed",
    "base_url_host": "api.minimaxi.com",
    "enabled": true,
    "key_configured": true,
    "key_source": "credential",
    "credential_id": "…",
    "credential_label": "规划部共享 MiniMax"
  },
  "credential_options": [
    { "id": "…", "label": "规划部共享 MiniMax", "provider": "minimax",
      "base_url_host": "api.minimaxi.com", "key_masked": "****abcd" }
  ]
}
```

`key_source` 值域（R2 修订）：`credential`（落库凭据）| `credential_ref`
（env REF）| `env` | `credential_missing`（policy 指了凭据但已禁用/解密失败，
按未配置降级）| 空串（未配置）。

`POST /api/generation/ping`：

- 请求体：`{"workspace_code": "planning_intel", "credential_id": null}`
  （两者皆可选）。给 `workspace_code` 用该工作台 resolved 参数测试；给
  `credential_id`（R2 新增）则用该凭据的 provider/base_url/key + 实例默认模型
  参数测试（两者都给时 credential_id 优先，供「保存后立即试连」）。
- 行为：向 provider 发一次最小 chat/completions（`max_tokens=1`，固定探针
  prompt），硬超时 10s；不落任何业务表；写审计 `generation.ping`
  （detail 只含 provider/model/base_url_host/status/latency_ms/credential_id，
  无 key）。
- 响应：

```json
{
  "status": "ok",
  "provider": "minimax",
  "model": "MiniMax-M2.7-highspeed",
  "base_url_host": "api.minimaxi.com",
  "key_configured": true,
  "latency_ms": 812,
  "error_code": null,
  "error_message": null
}
```

- 失败分类：`key_missing`（未配 key，直接返回不外呼）、`dns_or_connect_failed`、
  `auth_failed`（401/403）、`timeout`、`http_{status}`、`bad_response`。
  `error_message` 必须截断且脱敏（不回显请求头）。

## 5. UI 落位（R2 改造；页面细节归 `docs/product/`，此处只定后端供给与交互合同）

工作台配置中心 `/workspace-settings`「生成模型」卡（现状只有状态行 + 策略表单，
R2 改造为完整配置流）：

1. **provider 下拉**：选项来自 `GET /api/generation/providers`（§8 预设目录，
   顺序按目录 `sort_order`；`custom` 恒在最后，文案"自定义（兜底 base_url + key）"）。
2. **base_url 输入**：选中 provider 后自动预填目录 `default_base_url`，可改；
   `custom` 无预填、必填。`ollama` 预填本机默认并提示无需 key。
3. **key 输入**：write-only 密码框；保存调 `POST /api/generation/credentials`
   落库（super_admin；非 super_admin 只能选已有凭据，看不到新建入口）。
   保存成功后输入框清空，状态行显示 `label + key_masked`（`****` + 后 4 位），
   **永不回显明文**。
4. **模型下拉 + 自定义**：下拉项 = 目录 `common_models`，末项"自定义模型名…"
   切换为文本输入（写 `generation_policy.model`）。
5. **凭据选择**：workspace admin+ 从 `credential_options` 选一条写
   `generation_policy.credential_id`（"跟随实例 env"= null 选项恒在首位）。
6. **「测试连通」按钮**（super_admin/editor_admin）：保存后自动触发一次
   `POST /api/generation/ping {credential_id}`；手动点击按当前选择测试，展示
   延迟或错误分类。
7. **无任何配置时的引导文案**（`key_configured=false` 且无可选凭据）：
   卡片顶部显示三步引导"① 选择 provider → ② 填入 API key 并保存 →
   ③ 测试连通"；非 super_admin 显示"请联系平台管理员在此配置生成模型，
   或由运维在实例 env 配置（见部署手册 §2.2）"；并链接
   `docs/deployment/development-quickstart.md` §2.2。未配置期间生成链路走
   规则降级稿（`fallback_needs_review`，不进公司 SQL），文案必须说明这是
   预期行为不是故障。

实例级引导（env 怎么配）继续写在 `docs/deployment/development-quickstart.md`
§2.2 与 `deploy/env.production.example` 注释块。

## 6. 安全不变式（R2 修订）

- key 明文只存在于三处：env 变量值、credential_ref 目标文件、请求 provider 时的
  Authorization 头。**落库仅允许密文**（`llm_provider_credentials.key_encrypted`，
  Fernet at rest，§9.3）；明文不进 Git、不进同步 feed/手工包、不进审计 detail、
  不进任何 API 响应（含错误信息与 ping 的 error_message 脱敏）。
- 任何 API 对 key 的回显上限是 masked 视图：`****` + 后 4 位（存
  `key_last4` 列，展示不需要解密）。
- `llm_provider_credentials` 整表排除在 sync feed / 手工同步包 / 导出 /备份外的
  同步链路之外（secret-like 表，复用 `contains_secret_like_key` 边界；§9.5）。
- `generation_policy` 里出现 secret-like 字段（`key/token/secret/...`）时
  PATCH 直接 422——复用 `backend/app/core/privacy.py` 的 secret-like 检测；
  `credential_id` 是白名单指针字段，不在拦截范围。
- ping 是唯一主动外呼的自检入口，权限收敛 super_admin/editor_admin，且写审计。
- provider 切换/凭据切换不改变生成质量门禁：`_passes_generation_quality`、
  category 十分类约束、`insight_json` 校验、公司 SQL gating 对任何 provider
  一视同仁。

## 7. 验收标准（基线，已实现并由 `test_generation_provider.py` 看护）

1. 仅配 `MINIMAX_*`（不配 `GENERATION_*`）时，resolved 配置与现状字节一致，
   现有 MiniMax 生成/降级测试全部不改仍绿（兼容回归）。
2. `GENERATION_ENABLED=true` 且 key 为空（REF 解析失败同理）→ API/worker/
   scheduler 三入口启动失败，错误信息含修复指引；`GENERATION_API_KEY_REF=env:X`
   且 env X 存在时启动通过。
3. `PATCH /api/workspaces/{code}/generation-policy` admin 写
   `{"model":"gpt-4o-mini","temperature":0.2}` 后：落库、审计
   `workspace.generation_policy.update`、下一次生成调用的请求体 model/
   temperature 为工作台值（用 fixture provider 断言请求体）；viewer PATCH 403；
   `temperature=3` 422；payload 含 `"api_key"` 字段 422。
4. `GET generation-policy` 响应任何字段不含 key 明文；`key_configured` 在配/
   未配两种 env 下分别为 true/false。
5. `POST /api/generation/ping`：fixture provider 200 → `status=ok` 且有
   `latency_ms`；401 → `error_code=auth_failed`；不可达 →
   `dns_or_connect_failed`；未配 key → `key_missing` 且**无外呼**；
   非 admin 调用 403；每次调用写 `generation.ping` 审计且 detail 无 key。
6. `daily_generation_budget=2` 时，当日第 3 条起不再外呼 provider，按
   `fallback_behavior` 处理，run summary `generation_budget_exhausted>=1`。
7. `fallback_behavior=fail` 时 provider 超时不产生 rule_v1 降级稿，
   generation step 记 failed，`regenerate-generated-news` 可补跑；
   `rule_fallback`（默认）行为与现状一致。
8. 同步与导出边界：sync feed/手工包导出内容 grep 不到 key；公司 SQL 导出
   gating（ready + 非 rule_v1）在两种 provider 下断言一致。

## 8. Provider 预设目录（R2 新增，契约 `config/contracts/llm_providers.json`）

用户要求："市面上常用的都提供，最后有个兜底的 baseurl 和 key 的填法"。

预设目录**写死在 `config/contracts/llm_providers.json`**（随代码发布，不落库、
不可被 API 修改），由 `GET /api/generation/providers` 原样投影给前端下拉。
它只是 UI 预填与提示数据，**不是安全边界也不是能力开关**——base_url 可改、
模型名可自定义，最终能不能用由 ping 与生成链路的真实响应决定。

9 个 provider（code 即 `GENERATION_PROVIDER` / `llm_provider_credentials.provider`
的值域；default_base_url / 常用模型全量清单以契约 JSON 为准，本表是语义说明）：

| code | 默认 base_url | 鉴权 header 形态 | 说明 |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `Authorization: Bearer` | |
| `anthropic` | `https://api.anthropic.com/v1` | `Authorization: Bearer` | 走 Anthropic 的 OpenAI 兼容端点，仍是同一 chat/completions 客户端；原生 `x-api-key` 形态不做第二条客户端分支 |
| `deepseek` | `https://api.deepseek.com/v1` | `Authorization: Bearer` | |
| `moonshot` | `https://api.moonshot.cn/v1` | `Authorization: Bearer` | |
| `zhipu_glm` | `https://open.bigmodel.cn/api/paas/v4` | `Authorization: Bearer` | |
| `minimax` | `https://api.minimaxi.com/v1` | `Authorization: Bearer` | 现状默认 provider，默认模型 `MiniMax-M2.7-highspeed` 不变 |
| `openrouter` | `https://openrouter.ai/api/v1` | `Authorization: Bearer` | 模型名带命名空间（如 `openai/gpt-4o-mini`） |
| `ollama` | `http://localhost:11434/v1` | 无需 key（`key_required=false`） | 本地/内网自托管；key 输入框可留空 |
| `custom` | —（必填） | `Authorization: Bearer` | **兜底**：base_url + key 自由填；任何 OpenAI-compatible 网关/代理都从这里进 |

目录条目字段（契约 schema）：`code / name / default_base_url / auth_header
（枚举，v1 只有 authorization_bearer）/ key_required / common_models[] /
notes / sort_order`。

规则：

- 所有 preset 共用 `backend/app/llm/provider.py` 的同一 OpenAI-compatible
  `chat/completions` 客户端与 `/chat/completions` URL 补全规则；目录**不引入
  任何 provider 专属代码分支**（`anthropic` 原生协议、非 chat/completions
  协议一律不做，需要时走 `custom` + 网关）。
- `common_models` 只是下拉提示，不做服务端校验（模型名最终由
  `generation_policy.model` / `GENERATION_MODEL` 决定，允许任意自定义值）。
- 目录变更 = 改契约 JSON + 发版；不提供运行期编辑接口。

## 9. 密钥 UI 落库：`llm_provider_credentials`（R2 新增，已实现）

### 9.1 决策变更记录 D-2026-07-08-KEY（显式推翻旧决策）

| | 内容 |
|---|---|
| 旧决策（2026-07-07，本文 §1 原文） | "base_url 和 key 只在实例级 `.env` 配置……是唯一密钥存放处；不进数据库" |
| 新决策（2026-07-08） | key 允许**加密后**存入 instance 级新表 `llm_provider_credentials`，由 super_admin 在 UI 管理；env 链降级为兜底路径并完整保留 |
| 变更理由 | ① 用户明确要求 UI 配置（"市面上常用的都提供，最后有个兜底的 baseurl 和 key 的填法"）；② 市面同类产品（Dify/OneAPI/LobeChat/NewAPI 等）的通行惯例即 provider 目录 + key 落库 + masked 回显；③ env-only 使非运维角色完全无法自助接入模型，与"工作台配置中心自助运营"的产品定位冲突 |
| 不变的底线 | 明文 key 仍然不进 Git、不进同步包、不进审计、不进任何 API 响应；`generation_policy` 仍不含 key |
| 风险与缓解 | 见 §9.7 |

### 9.2 表结构

```text
llm_provider_credentials            （instance 级，无 workspace_code——凭据是
                                      实例资产，工作台通过 policy 引用）
  id / global_id / created_at / updated_at
  provider          str32，§8 目录 code（含 custom）
  base_url          str512，落库时已解析（目录默认或用户改写；custom 必填）
  key_encrypted     text，Fernet token（§9.3）；ollama 等免 key 场景允许空串
  key_last4         str8，明文后 4 位（少于 4 位取全部），供 masked 展示，
                    展示路径永不解密
  label             str64，运营命名（默认 "{provider} 凭据"）
  enabled           bool，默认 true；DELETE = enabled=false + disabled_at（软删）
  disabled_at       datetime nullable
  created_by_id     fk users.id
```

迁移：新增表一张，无既有表变更；不回填任何数据（env 配置不自动导入 DB，
避免密钥在未经用户确认下改变存放位置）。

### 9.3 加密 at rest（Fernet + HKDF 派生）与轮换含义

- 加密算法：`cryptography` Fernet（AES128-CBC + HMAC-SHA256，自带时间戳与
  完整性校验）。
- **密钥派生**：不新增 env。Fernet key = HKDF-SHA256(
  ikm=`AUTH_SESSION_SECRET`（utf-8），salt=`"infowatchtower/llm-credentials/v1"`，
  info=`"fernet-key"`，length=32) 后 urlsafe-base64。派生实现放
  `backend/app/core/crypto.py`（新模块），启动时构造一次。
- **轮换含义（必须写清）**：`AUTH_SESSION_SECRETS` 轮换列表（首个=当前签名
  secret，`Settings.auth_session_secret_list`）逐个派生 Fernet key，组成
  MultiFernet——**加密永远用第一个**，解密按序尝试全部。因此：
  - 换 session secret 时把旧值保留在 `AUTH_SESSION_SECRETS` 尾部（现有轮换
    操作规程不变），落库凭据即可继续解密；"能用旧 key 解密"的行在首次解析
    使用时自动用新 key 重加密（幂等；实现落点 `resolve_credential_for_config`）。
  - 若直接丢弃旧 secret（不走轮换列表），已存凭据解密失败——**行为定义为
    按"未配置 key"降级**（`key_source=credential_missing`，生成走规则降级稿，
    ping 报 `key_missing`），不崩溃、不删行；「生成模型」卡提示"凭据不可用，
    请重新录入 key"。审计记 `generation.credential.decrypt_failed`（无明文）。
- 派生用途隔离：salt/info 固定串保证该 Fernet key 与 session 签名用途分离，
  同一 secret 不会以相同形态出现在两类用途里。

### 9.4 解析优先级（单一判定点，落在 `resolve_generation_config`）

```text
1. workspace generation_policy.credential_id 非 null
   → 查 llm_provider_credentials（enabled=true）
     → 命中且解密成功：provider/base_url/key 取凭据行，key_source=credential
     → 已禁用/不存在/解密失败：按未配置 key 降级，key_source=credential_missing
       （不回落 env——工作台显式选了凭据，静默换 key 属于安全事故）
2. credential_id 为 null → 实例 env 链（现状语义逐字节保留）：
   GENERATION_API_KEY_REF → GENERATION_API_KEY → MINIMAX_API_KEY；
   provider/base_url 同理走 GENERATION_*/MINIMAX_* 兼容链
3. 模型参数（model/temperature/max_tokens/timeout）与预算、fallback_behavior
   仍走 policy 覆盖 env 的既有分层，与凭据来源无关
```

### 9.5 回显、审计与同步边界

- 任何 API（含列表、详情、policy resolved、ping、错误信息）只回显
  `key_masked = "****" + key_last4`；`key_encrypted` 密文本身也不出现在
  API 响应里。
- 审计 `generation.credential.create/update/disable` 的 detail 只含
  provider/base_url_host/label/key_masked/enabled before-after；
  `write_audit` 的 secret-like redactor 兜底。
- `llm_provider_credentials` 不进 sync feed、不进手工同步包、不进任何导出
  （公司 SQL/离线包）；表名登记进同步链路的排除清单，秘钥表跨环境不同步——
  每个环境自己录 key（intranet pull-only 拓扑下这是唯一正确语义）。
- 前端 bundle 与页面状态永不持有明文 key：输入框 write-only，提交后即清。

### 9.6 启动自检修订（随本节实现一起落地）

- `GENERATION_ENABLED=true` 且 env key 为空：**从拒启改为启动 WARNING**
  （"key 未在 env 配置；若未在 UI 录入凭据，生成将走规则降级稿"）。理由：
  key 可在运行期落库，启动断言会阻止"先启动、再进 UI 配 key"的正常路径。
- 保留 fail-fast：`GENERATION_PROVIDER` 值不在 §8 目录（含别名
  `openai_compatible`）；`custom`/`openai_compatible` 且 `GENERATION_BASE_URL`
  为空。
- 新增 fail-fast：`AUTH_SESSION_SECRET` 为空时本就拒启（既有规则），因此
  Fernet 派生无新增启动条件。
- 实现时同步 `config/contracts/deployment_modes.json` `startup_failfast_rules`
  （该清单与已实现自检保持 1:1）。

### 9.7 风险与缓解

| 风险 | 缓解 |
|---|---|
| DB 泄露导致 key 泄露 | Fernet at rest；派生密钥不落盘（仅内存）；拿到 DB 还需 `AUTH_SESSION_SECRET` 才能解密 |
| 备份文件带出密文 | 备份规程不变（受控目录、不进 Git）；密文无 secret 不可解；恢复到新环境若 secret 不同即自动降级为"未配置" |
| session secret 轮换打断解密 | MultiFernet + 启动重加密（§9.3）；操作规程与 session 轮换共用一份 |
| super_admin 之外的人读到 key | 明文永不回显（任何角色含 super_admin 都只见 masked）；credentials CRUD 收敛 super_admin，读列表放宽到 editor_admin 也只有 masked 视图 |
| 凭据被误删导致生成静默断链 | 软删；被引用时降级为 `credential_missing` 并在卡片/ping 显式暴露，run summary 照常出规则降级计数 |
| 同步/导出把表带到别的环境 | §9.5 排除清单 + 既有 secret-like 拦截双保险；验收断言 §10.6 看护 |

## 10. R2 验收标准（可执行断言级，已逐条转测试：`backend/tests/test_credentials_api.py`）

1. `GET /api/generation/providers` 返回 §8 目录全部 9 个 code，与
   `config/contracts/llm_providers.json` 逐字段一致；响应 grep 不到
   `key/secret/token` 字段名以外的凭据数据（纯静态目录）。
2. `POST /api/generation/credentials`（super_admin）录入
   `{provider:"deepseek", api_key:"sk-test-1234abcd", label:"测试"}` 后：
   DB 行 `key_encrypted` 非明文（不含 `sk-test`）、`key_last4="abcd"`、
   `base_url` 自动取目录默认；响应与随后任何 GET 只含 `key_masked="****abcd"`；
   `custom` 不带 `base_url` 提交 422；非 super_admin 提交 403。
3. `PATCH /api/workspaces/{code}/generation-policy` 写
   `{"credential_id": "<id>"}` 后：resolved `key_source=credential`、
   `base_url_host` 为凭据 host；下一次生成调用请求头 Authorization 携带该
   凭据 key（fixture transport 断言）；指向不存在/禁用凭据的 PATCH 422。
4. 凭据被 DELETE（软删）后：引用它的工作台 resolved
   `key_source=credential_missing`、生成走规则降级稿且 run summary 有降级
   计数，**不回落 env key**（env 配了 key 也不用）；ping 该工作台报
   `key_missing` 且无外呼。
5. `POST /api/generation/ping {credential_id}` 用该凭据外呼一次探针
   （fixture 200 → `status=ok`；401 → `auth_failed`）；审计
   `generation.ping` detail 含 credential_id、host、状态、延迟，grep 不到
   key 明文与密文。
6. 密钥轮换回归：用 secret A 录入凭据 → env 换成
   `AUTH_SESSION_SECRETS="B,A"` 重启 → 生成/ping 仍可解密使用，且该行被重
   加密（用 B 派生 key 可单独解密）；换成只有 `"B"`（丢弃 A）且未重加密过
   → resolved `key_source=credential_missing`、审计出现
   `generation.credential.decrypt_failed`、无异常抛出。
7. 同步与导出边界：开启凭据后导出 sync feed 与手工同步包，内容 grep 不到
   `llm_provider_credentials`、key 明文与密文；审计导出同理。
8. 兼容回归：不建任何凭据、`credential_id=null` 时，resolved 配置与 R2 之前
   逐字节一致（含仅配 MINIMAX_* 的老兼容断言），§7 全部基线断言不改仍绿；
   `GENERATION_ENABLED=true` 且 env 无 key 时进程可启动（WARNING 而非拒启），
   `custom` 缺 base_url 仍拒启。
