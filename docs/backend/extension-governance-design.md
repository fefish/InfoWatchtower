# Extension Governance 扩展治理设计

> 状态：目标态设计稿。本文是新增 adapter、domain pack、report format、exporter、
> auth provider 和可选页面模块的治理事实源。扩展点接口细节见 `docs/backend/extension-points.md`，
> 机器契约见 `config/contracts/extension_points.json`。

## 1. 模块定位

InfoWatchtower 必须支持扩展，但扩展不能破坏主链路。

扩展治理回答：

- 谁可以新增能力。
- 新能力注册在哪里。
- 是否需要 contract、迁移、测试和 UI。
- 如何启用、回滚和监控。
- 如何避免把系统分叉成多套应用。

## 2. 可扩展类型

| 类型 | 注册键 | 示例 |
|---|---|---|
| source adapter | `source_type` | rss、paper_api、wechat、wiseflow |
| content extractor | `extractor_name` | article_body、pdf_metadata |
| normalizer hook | `source_type` | paper DOI normalization |
| dedupe strategy | `strategy_name` | hard_url_then_title_date |
| scoring strategy | `algorithm_version` | content_scorer_v2 |
| generator provider | provider + model + prompt | minimax prompt v2 |
| report format | `format_code` | company_sql_v1、tech_insight_v1 |
| exporter | `export_type` | company_daily_sql |
| auth adapter | `AUTH_MODE` | oidc、intranet_header |
| workspace section | `section_key` | sync、exports、users |
| domain pack | `domain_code` | hardware、semiconductor |
| sync adapter | `sync_mode` | feed_pull、manual_package |

## 3. 扩展生命周期

```text
proposal
-> design
-> contract/schema
-> implementation
-> tests
-> gated enablement
-> monitoring
-> deprecation if needed
```

### 3.1 Proposal

必须说明：

- 用户任务。
- 所属模块。
- 为什么不能用已有扩展点。
- 是否影响部署形态。
- 是否影响安全和同步边界。

### 3.2 Design

必须更新：

- 对应模块设计文档。
- `docs/backend/backend-module-design.md` 摘要，如新增一级模块。
- `docs/product/frontend-product-design.md`，如新增页面或控件。
- `docs/README.md` 的同步规则，如新增文档类别。

### 3.3 Contract / Schema

以下情况必须改 contract：

- 新字段。
- 新枚举。
- 新 source_type。
- 新 sync object。
- 新 auth mode。
- 新 report format 内置约束。
- 新部署 capability。

### 3.4 Implementation

实现必须通过注册表接入，不能在主链路里写死特殊分支。

### 3.5 Tests

扩展最少测试：

- 注册成功。
- 输入输出符合 contract。
- 失败语义明确。
- 不破坏默认工作台。
- 部署能力开关生效。

## 4. Domain Pack 治理

Domain pack 是新增业务板块的推荐方式。

一个 domain pack 可以包含：

- sources。
- taxonomy。
- scoring。
- report templates。
- export mapping。

规则：

- 不复制后端服务。
- 不复制前端应用。
- 不改变 `raw -> news -> dedupe -> scoring -> report` 主链路。
- 不把源侧标签写入成品新闻 category。
- 新 SQL 合同必须新增 exporter，不得改规划部公司 SQL。

## 5. Workspace Section 治理

新增页面必须先进入 `workspace_sections`：

- 默认 disabled，除非是核心模块。
- 有明确 route。
- 有权限策略。
- 有后端模块和 API。
- 有空态和测试。

禁止为了展示而硬编码导航项。

## 6. Report Format 治理

report format 是投影，不是数据副本。

规则：

- `company_sql_v1` locked，不用于 MD/HTML 成稿。
- 自定义格式通过注册表创建。
- 渲染失败不应污染原始 report items。
- 导出权限由 Reports/Export 模块共同控制。

## 7. Adapter 治理

source adapter 只负责抓取或接收 raw。

禁止：

- 在 adapter 内做最终去重。
- 在 adapter 内决定日报采信。
- 在 adapter 内生成公司 SQL。
- 覆盖 `raw_payload_json`。
- 把密钥写入 source metadata 或 sync payload。

未实现 adapter 必须返回明确的 `skipped_unimplemented` 或保持不可选，不能显示成功 0 条。

## 8. Auth Adapter 治理

auth adapter 只输出 `ExternalIdentity`。

规则：

- 业务权限只看本地 RBAC。
- 新 provider 必须有 claims 映射设计。
- 自动开通必须有默认 role 和 workspace membership 策略。
- OIDC/SAML 失败语义必须明确。
- 真实 provider 上线前要有验收证据。

## 9. 版本与回滚

扩展应记录：

- `version`。
- `enabled`。
- `created_by`。
- `updated_at`。
- `migration_required`。
- `compatibility_notes`。

禁用扩展不能删除历史数据。回滚策略优先是禁用注册项，而不是删除表或字段。

## 10. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| extension registry 和 contract 未自动校验 | 注册表枚举与 `extension_points.json` 一致 |
| domain pack 样例不足 | 至少 hardware/semiconductor 有可验收样例 |
| adapter 未实现语义不统一 | 已补 stub adapter `skipped_unimplemented` 显式状态；后续新增 adapter 必须复用该规则 |
| 可选 workspace section 缺测试 | disabled section 不出现在导航 |
| 扩展启停缺审计 | enable/disable 写 audit log |

## 11. 验收标准

- 新 source adapter 不改 report/export 主链路。
- 新 domain pack 能创建工作台并跑通默认 pipeline。
- 新 report format 可生成 rendition，不影响 company SQL。
- 新 auth provider 只映射身份，不直接授予业务权限。
- 新页面只在 workspace section enabled 且有权限时出现。
