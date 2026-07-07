# Generation Provider 生成模型配置与连通性设计

> 状态：设计已定稿待实现（2026-07-07）。本文是 LLM 生成 provider 配置、
> 工作台生成策略（`generation_policy`）和连通性自检的后端模块事实源。
> 生成 prompt/字段结构仍以 `docs/backend/report-renditions-design.md` 与
> `config/contracts/report_renditions.json` 为准；模板驱动生成见
> `docs/backend/reports-editorial-design.md` §8.1。密钥治理边界见
> `docs/backend/security-secrets-privacy-design.md`。

## 1. 模块定位与用户问题

用户原话："我在哪里配置用的这个 ai 的 base url 和 key 呢？？"

本文的直接回答：

- **base_url 和 key 只在实例级 `.env` 配置**（部署时一次），是唯一密钥存放处；
  不进数据库、不进 Git、不进同步包、不在任何 API 回显。
- **模型名、温度、超时、预算、降级行为在工作台配置中心「生成模型」卡配置**
  （存 DB，运营期可改，无需重启）。
- 配没配对，用 `POST /api/generation/ping` 一键自检，结果直接显示在卡片上。

## 2. 现状事实（2026-07 侦查结论）

- 生成链路只有 MiniMax 一条：`backend/app/llm/minimax.py` 的
  `generate_news_with_minimax` 走 OpenAI-compatible `chat/completions`
  （默认 `https://api.minimaxi.com/v1`），由 `MINIMAX_GENERATION_ENABLED` +
  `MINIMAX_API_KEY` 开启，未配 key 时全链路规则降级
  （`fallback_needs_review` / rule_v1，不进公司 SQL）。
- 相关 env（`backend/app/core/config.py`）：`MINIMAX_GENERATION_ENABLED /
  MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_ANTHROPIC_BASE_URL /
  MINIMAX_MODEL / MINIMAX_MAX_TOKENS / MINIMAX_TEMPERATURE /
  MINIMAX_RETRY_TIMES / MINIMAX_RETRY_BACKOFF_SECONDS`。
- 没有任何界面能看到"生成模型配置了没有、通不通"；这是本设计要消灭的盲区。

## 3. 分层配置模型

```text
第 1 层 实例 env（唯一密钥存放处，改动需重启进程）
  GENERATION_PROVIDER / GENERATION_BASE_URL / GENERATION_API_KEY(_REF) /
  GENERATION_MODEL 等实例默认值

第 2 层 工作台 generation_policy（存 workspaces.config_json.generation_policy，
  运营可改）
  模型名、温度、max_tokens、超时、每日预算、fallback 行为；
  永不包含 key/base_url/provider——网络出口与密钥是实例级安全边界

第 3 层 单次调用 resolved 参数
  generation_policy 非 null 字段覆盖实例默认 → 传给 provider client
```

### 3.1 实例级 env 规格

| env | 取值/默认 | 语义 |
|---|---|---|
| `GENERATION_ENABLED` | bool，默认 false | 模型生成总闸；false 时全链路规则降级（现 `MINIMAX_GENERATION_ENABLED` 语义不变） |
| `GENERATION_PROVIDER` | `openai_compatible` \| `minimax`，默认 `minimax` | provider 预设。两者共用同一 OpenAI-compatible chat/completions 客户端；`minimax` 只是带默认 base_url（`https://api.minimaxi.com/v1`）与默认模型名的预设，`openai_compatible` 必须显式给 `GENERATION_BASE_URL` |
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
- 启动自检：`GENERATION_ENABLED=true` 且 key（含 REF 解析后）为空 →
  启动失败并给修复指引；`GENERATION_PROVIDER=openai_compatible` 且
  `GENERATION_BASE_URL` 为空 → 启动失败。规则已登记在
  `config/contracts/deployment_modes.json` `planned_startup_failfast_rules`；
  实现落地 `backend/app/core/deploy_checks.py` 时移入 `startup_failfast_rules`
  （该清单与已实现自检保持 1:1）。

### 3.2 工作台 `generation_policy` 字段规格

存放：`workspaces.config_json.generation_policy`（与 label/feedback/report/
schedule policy 同级）。契约：`config/contracts/workspace_model.json`
`generation_policy`。

```json
{
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
| `model` | `null\|str(≤64)` | 本工作台模型名；`null`=实例默认 |
| `temperature` | `null\|float(0..2)` | 同上 |
| `max_tokens` | `null\|int(256..8192)` | 同上 |
| `timeout_seconds` | `null\|float(5..300)` | 单条生成超时 |
| `daily_generation_budget` | `null\|int(1..1000)` | 本工作台每日模型调用条数上限；`null`=不限。计数按 `(workspace_code, day_key)` 统计当日模型调用（成功+失败都计），超出后本日剩余条目按 `fallback_behavior` 处理，run summary 记 `generation_budget_exhausted` 计数 |
| `fallback_behavior` | `rule_fallback`（默认）\| `fail` | provider 不可用/超时/预算尽时：`rule_fallback`=产 rule_v1 降级稿（`fallback_needs_review`，现状语义，不进公司 SQL）；`fail`=不产降级稿，generation step 记 failed，条目留待 `regenerate-generated-news` 重跑 |

## 4. API 设计

```text
GET   /api/workspaces/{code}/generation-policy    workspace viewer+ 读
PATCH /api/workspaces/{code}/generation-policy    workspace admin+ 或 super_admin 写；
                                                  取值域校验 422；
                                                  审计 workspace.generation_policy.update（before/after）

POST  /api/generation/ping                        super_admin 或 editor_admin
```

`GET generation-policy` 响应除策略本身外必须带只读的 resolved 状态，供
「生成模型」卡不打 ping 也能展示：

```json
{
  "policy": { "...": "..." },
  "resolved": {
    "provider": "minimax",
    "model": "MiniMax-M2.7-highspeed",
    "base_url_host": "api.minimaxi.com",
    "enabled": true,
    "key_configured": true,
    "key_source": "env"
  }
}
```

`POST /api/generation/ping`：

- 请求体：`{"workspace_code": "planning_intel"}`（可选；给了就用该工作台
  resolved 模型参数测试）。
- 行为：向 provider 发一次最小 chat/completions（`max_tokens=1`，固定探针
  prompt），硬超时 10s；不落任何业务表；写审计 `generation.ping`
  （detail 只含 provider/model/base_url_host/status/latency_ms，无 key）。
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

## 5. UI 落位（页面细节归 `docs/product/`，此处只定后端供给）

- 工作台配置中心 `/workspace-settings` 新增「生成模型」卡：
  - 顶部状态行：provider、模型、`key_configured` 只显示"已配置/未配置"
    （**永不回显 key，任何字段不含 key 明文**）、连通状态（最近一次 ping 结果）。
  - 可编辑区：模型名、温度、超时、每日预算、fallback 行为（写 generation-policy）。
  - 「测试连通」按钮（仅 super_admin/editor_admin 可见）调 ping API，展示
    延迟或错误分类。
  - `key_configured=false` 时卡片显示实例级配置指引摘要，并链接
    `docs/deployment/development-quickstart.md` §2.2（env 怎么配）。
- 实例级引导（env 怎么配）写入 `docs/deployment/development-quickstart.md`
  §2.2 与 `deploy/env.production.example` 注释块。

## 6. 安全不变式

- key 只存在于 env / credential_ref 目标文件中：不进 DB、不进 Git、不进同步
  feed/包、不进审计 detail、不进任何 API 响应（含错误信息）。
- `generation_policy` 里出现 secret-like 字段（`key/token/secret/...`）时
  PATCH 直接 422——复用 `backend/app/core/privacy.py` 的 secret-like 检测。
- ping 是唯一主动外呼的自检入口，权限收敛 super_admin/editor_admin，且写审计。
- provider 切换不改变生成质量门禁：`_passes_generation_quality`、category
  十分类约束、`insight_json` 校验、公司 SQL gating 对任何 provider 一视同仁。

## 7. 验收标准（可执行断言级）

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
