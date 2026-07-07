# 文档地图与治理规则

本文档只回答两件事：

1. InfoWatchtower 的设计文档谁是事实源。
2. 修改某类能力时必须同步哪些文档和契约。

它不承载目标架构本身，不承载实现状态流水账，也不替代
`config/contracts/*.json` 的机器契约。

## 1. 文档权威关系

物理目录必须与设计层级一致：

```text
docs/
  README.md                         文档地图和治理规则
  00-system-design.md               目标态总纲，只放业务架构和硬约束

  architecture/
    README.md                         架构目录索引和主次关系
    design-governance.md            设计分层、评审门禁
    capability-map.md               已实现/缺口/证据
    software-design-description.md  正式 SDD 总装版
    target-state-spec.md            目标态增量工作包
    strategic-intelligence-platform.md  长期愿景展开

  product/
    README.md                         前端产品目录索引
    frontend-product-design.md      前端信息架构、页面地图、顶部栏、用户旅程
    page-specs/
      frontend-page-specs.md        前端逐页规格、已做/未做、测试看护

  backend/
    README.md                         后端模块目录索引、事实源和附录关系
    backend-module-design.md        后端领域模块总图
    identity-access-design.md       登录、SSO、用户、权限、邀请、membership
    collaboration-notification-design.md  评论、点赞、评分、消息通知
    data-ingestion-flow-storage-design.md
    recommendation-scoring-design.md
    pipeline-jobs-design.md
    generation-provider-design.md
    reports-editorial-design.md
    workspace-configuration-design.md
    strategy-loop-design.md
    archive-knowledge-design.md
    sync-conflict-distribution-design.md
    export-compliance-design.md
    audit-ops-observability-design.md
    search-design.md
    security-secrets-privacy-design.md
    extension-governance-design.md
    contract-test-governance-design.md
    ingestion-adapter-dedup-spec.md
    backend-capability-test-matrix.md
    data-lineage-and-storage.md
    data-format-mapping.md
    report-renditions-design.md
    feedback-heat-scoring.md
    workspace-module-model.md
    tech-insight-loop-fusion-plan.md
    extension-points.md
    extension-recipes.md

  deployment/
    README.md                         部署目录索引
    deployment-topology.md
    auth-unified-login.md
    auth-security-roadmap.md
    multi-environment-sync.md
    deployment-ops.md
    development-quickstart.md

  implementation/
    README.md                         实施目录索引
    implementation-handoff.md
    01-implementation-plan.md
    api-and-ui-implementation.md
    technical-debt-and-refactor-log.md

  reference/
    README.md                         参考材料目录索引
    data-examples.md
    legacy-system-spec.md
    system-blueprint.md
    ai-collaboration-engineering-case.md
```

子目录索引文件固定为：`architecture/README.md`、`product/README.md`、
`backend/README.md`、`deployment/README.md`、`implementation/README.md`、
`reference/README.md`。这些索引只说明目录内主次关系，不承载新的业务规则。

新增或移动设计文档时，先判断它属于哪个目录；不要把专题文档重新放回
`docs/` 根目录。根目录只保留本文和总纲。各子目录的 `README.md` 只做索引和主次关系说明，
不是新的业务事实源。目录内也不能继续形成无主散文档：每个 `docs/**/*.md` 都必须被最近一层
`README.md` 索引收住，并标明它是事实源、附录、状态图还是运行手册。移动文档或新增专题后必须
运行 `make docs-check`，该命令会检查 `docs/` 根目录是否只保留 `README.md` 和
`00-system-design.md`、每份文档是否已被所在层级索引，以及仓库内 `docs/...md` 引用是否指向真实文件。

| 层级 | 主文档 | 回答的问题 | 不负责 |
|---|---|---|---|
| 设计治理 | `docs/architecture/design-governance.md` | 产品、前端、后端、契约、部署、验收如何分层 | 具体业务字段 |
| 产品/业务总纲 | `docs/00-system-design.md` | 系统目标态、主链路、硬约束、部署目标 | 当前实现进度清单 |
| 前端产品与页面 | `docs/product/frontend-product-design.md` | 页面地图、导航、顶部栏、用户旅程、页面能力出现规则 | 后端表结构和权限模型 |
| 前端逐页规格 | `docs/product/page-specs/frontend-page-specs.md` | 每个页面的目标态、已做/未做、测试看护 | 后端字段和状态机事实源 |
| 后端模块总图 | `docs/backend/backend-module-design.md` | 后端领域模块、数据归属、API/任务/事件边界 | 页面布局和视觉细节 |
| 数据抓取/流转/存储 | `docs/backend/data-ingestion-flow-storage-design.md` | 数据源、抓取 run、raw、news、去重、覆盖率和追溯 | 推荐分和采信成稿 |
| 推荐评分模块 | `docs/backend/recommendation-scoring-design.md` | 准入、评分、推荐 run、分数解释和反馈反哺 | 原始反馈写入和通知 |
| 流水线与任务 | `docs/backend/pipeline-jobs-design.md` | 日更流水线、worker、scheduler、工作台调度策略、重试、幂等和任务状态 | 单个业务步骤的字段规则 |
| 生成模型 provider | `docs/backend/generation-provider-design.md` | LLM provider 实例 env 配置、工作台 generation_policy、连通性自检 | 生成 prompt 字段结构（归 renditions） |
| 报告编审发布 | `docs/backend/reports-editorial-design.md` | 日报/周报、采信、编辑覆盖、发布、锁定、版本 | 多版成稿渲染细节 |
| 工作台配置 | `docs/backend/workspace-configuration-design.md` | 工作台、sections、成员、label/feedback policy、domain pack | 数据主链实现 |
| 身份权限模块 | `docs/backend/identity-access-design.md` | 用户、角色、SSO、邀请、membership、部署认证 | 顶部用户胶囊 UI |
| 协作通知模块 | `docs/backend/collaboration-notification-design.md` | 点赞、评分、评论、活动事件、通知收件箱 | 顶部铃铛视觉 |
| 战略闭环模块 | `docs/backend/strategy-loop-design.md` | insight、战略含义、需求、任务和外部信号追溯 | 日报/周报正文生成 |
| 资料库与知识沉淀 | `docs/backend/archive-knowledge-design.md` | 历史报告、实体大事记、质量归档、旧资产导入验收 | 当前推荐和公司 SQL |
| 审计运维可观测 | `docs/backend/audit-ops-observability-design.md` | 审计日志、健康、告警、备份恢复和运行证据 | 业务字段合同 |
| 全局检索 | `docs/backend/search-design.md` | 检索对象、权限过滤、结果跳转和顶部搜索恢复条件 | 左侧导航 |
| 同步冲突分发 | `docs/backend/sync-conflict-distribution-design.md` | sync feed/pull、inbox、conflict、resolve、人工包 fallback | 部署拓扑矩阵 |
| 导出合规 | `docs/backend/export-compliance-design.md` | SQL 导出预检、门禁、任务、trace、下载权限 | SQL 字段映射明细 |
| 安全密钥隐私 | `docs/backend/security-secrets-privacy-design.md` | secrets、cookie、CSRF、trusted header、sync redaction 和隐私边界 | 用户角色业务模型 |
| 扩展治理 | `docs/backend/extension-governance-design.md` | adapter、domain pack、report format、auth provider 和可选页面的治理 | 扩展点接口细节 |
| 契约与测试治理 | `docs/backend/contract-test-governance-design.md` | contract、schema、前后端测试、假控件拦截和 CI 门禁 | 单个模块字段定义 |
| API/UI 对照 | `docs/implementation/api-and-ui-implementation.md` | 已有 API、页面与实现落点的对应关系 | 产品目标态定义 |
| 部署拓扑 | `docs/deployment/deployment-topology.md` | standalone/cloud/extranet/intranet、能力开关、iframe、feed/pull | 前端页面信息架构 |
| 同步专题 | `docs/deployment/multi-environment-sync.md` | 多库数据边界、feed/pull、手工包 fallback | 部署形态总矩阵 |
| 能力地图 | `docs/architecture/capability-map.md` | 已实现、缺口、证据和优先级 | 重新定义目标架构 |
| 实施任务 | `docs/implementation/implementation-handoff.md`、`docs/implementation/01-implementation-plan.md` | 开发顺序、验收命令、交接清单 | 覆盖总纲或模块设计 |
| 机器契约 | `config/contracts/*.json` | 字段、枚举、流程、映射、接口边界 | 背景说明和产品叙事 |

任何新增能力都必须先落到正确层级，再进入开发。前端控件不能单独定义后端能力，
后端模块不能单独决定页面布局，contract 是二者之间的可测试边界。

### 1.1 子目录主次关系

每个子目录允许有一个 `README.md` 作为目录索引。索引只回答“这个目录有哪些文件、谁是事实源、
谁是附录”，不得承载新的业务规则。

| 目录 | 主事实源 | 附录或状态 |
|---|---|---|
| `docs/architecture/` | `design-governance.md`、`software-design-description.md` | `capability-map.md` 只记状态；`target-state-spec.md` 和 `strategic-intelligence-platform.md` 是附录 |
| `docs/product/` | `frontend-product-design.md`、`page-specs/frontend-page-specs.md` | 目录 README 只索引页面设计 |
| `docs/backend/` | `backend-module-design.md` 和各模块 `*-design.md` | `data-format-mapping.md`、`report-renditions-design.md`、`workspace-module-model.md` 等是模块附录 |
| `docs/deployment/` | `deployment-topology.md`、`multi-environment-sync.md`、`auth-unified-login.md` | `deployment-ops.md` 和 `development-quickstart.md` 是运行手册 |
| `docs/implementation/` | `implementation-handoff.md`、`01-implementation-plan.md` | `api-and-ui-implementation.md` 是实现对照；技术债单独记录 |
| `docs/reference/` | 无目标态事实源 | 旧系统事实、历史蓝图和样例只作为参考 |

## 2. 阅读顺序

开发者或 AI 接手时：

1. 读 `AGENTS.md`，理解开发准则和不可破坏原则。
2. 读 `docs/00-system-design.md`，理解系统目标态和主链路。
3. 读 `docs/architecture/design-governance.md`，确认本次修改属于哪一层设计。
4. 做前端页面/交互：读 `docs/product/frontend-product-design.md` 和 `docs/product/page-specs/frontend-page-specs.md`，必要时读 `docs/reference/system-blueprint.md` 的页面规格历史材料。
5. 做后端模块：读 `docs/backend/backend-module-design.md`，并读对应模块设计文档。
6. 做数据源、抓取、raw/news、去重、覆盖率：读 `docs/backend/data-ingestion-flow-storage-design.md`、`docs/backend/ingestion-adapter-dedup-spec.md`、`docs/backend/data-lineage-and-storage.md`。
7. 做推荐、准入、评分、候选池解释：读 `docs/backend/recommendation-scoring-design.md`、`docs/backend/feedback-heat-scoring.md`。
8. 做流水线、任务、scheduler、worker、工作台调度策略：读 `docs/backend/pipeline-jobs-design.md`；做生成模型 provider 配置或连通性自检：再读 `docs/backend/generation-provider-design.md`。
9. 做日报/周报编审发布：读 `docs/backend/reports-editorial-design.md`、`docs/backend/report-renditions-design.md`。
10. 做工作台配置：读 `docs/backend/workspace-configuration-design.md`、`docs/backend/workspace-module-model.md`。
11. 做登录、SSO、用户权限：读 `docs/backend/identity-access-design.md`、`docs/deployment/auth-unified-login.md`、`config/contracts/auth_modes.json`。
12. 做评论、点赞、评分、通知：读 `docs/backend/collaboration-notification-design.md`、`docs/backend/feedback-heat-scoring.md`、`config/contracts/notifications.json`。
13. 做洞察、需求、任务：读 `docs/backend/strategy-loop-design.md`、`config/contracts/strategic_loop.json`。
14. 做历史归档、实体大事记、质量归档或旧资产导入：读 `docs/backend/archive-knowledge-design.md`、`docs/backend/tech-insight-loop-fusion-plan.md`、`config/contracts/archive_knowledge.json`、`config/contracts/tech_insight_loop_legacy_import.json`。
15. 做审计、运行状态、告警、备份恢复：读 `docs/backend/audit-ops-observability-design.md`、`docs/deployment/deployment-ops.md`、`config/contracts/audit_ops.json`。
16. 做顶部搜索或统一检索：读 `docs/backend/search-design.md`。
17. 做公网/内网部署或联动同步：读 `docs/deployment/deployment-topology.md`、`docs/deployment/multi-environment-sync.md`、`docs/backend/sync-conflict-distribution-design.md`、`config/contracts/deployment_modes.json`、`config/contracts/sync_strategy.json`。
18. 做安全、密钥、cookie、CSRF、trusted header 或同步脱敏：读 `docs/backend/security-secrets-privacy-design.md`。
19. 做新 adapter、domain pack、report format、exporter、auth provider 或可选页面：读 `docs/backend/extension-governance-design.md`、`docs/backend/extension-points.md`、`config/contracts/extension_points.json`。
20. 做公司 SQL 导出：读 `docs/backend/export-compliance-design.md`、`docs/backend/data-format-mapping.md`、`config/contracts/news_sql_mapping.json`。
21. 写测试、修假控件、改 contract/schema/type：读 `docs/backend/contract-test-governance-design.md`。
22. 查当前完成度和缺口：读 `docs/architecture/capability-map.md`。
23. 写代码前读 `config/contracts/README.md` 和相关 `config/contracts/*.json`、`config/taxonomy/*.json`。

## 3. 文档归位规则

### 3.1 总纲只放目标态

`docs/00-system-design.md` 是产品/业务总纲，只定义：

- 系统定位和长期闭环。
- 主数据流和硬约束。
- 四种部署形态的目标行为。
- 第一版范围和不可破坏边界。

它不再承载详细实现状态、验收输出和每页 UI 元素。状态和证据归
`docs/architecture/capability-map.md`，页面细节归 `docs/product/frontend-product-design.md`
或 `docs/reference/system-blueprint.md` 的页面规格段。

### 3.2 前端设计只管用户体验

`docs/product/frontend-product-design.md` 只定义：

- 信息架构、导航分组、顶部栏职责。
- 每个页面的用户任务、空态、权限态、部署形态可用性。
- 搜索、通知、账号入口等全局控件什么时候出现。

它不能单独定义通知数据模型、SSO claims、viewer 是否能评论等后端策略。

### 3.3 后端设计按领域模块组织

`docs/backend/backend-module-design.md` 是后端模块总图。模块细节拆到专题文档：

- `docs/backend/data-ingestion-flow-storage-design.md`
- `docs/backend/recommendation-scoring-design.md`
- `docs/backend/pipeline-jobs-design.md`
- `docs/backend/reports-editorial-design.md`
- `docs/backend/workspace-configuration-design.md`
- `docs/backend/identity-access-design.md`
- `docs/backend/collaboration-notification-design.md`
- `docs/backend/sync-conflict-distribution-design.md`
- `docs/backend/export-compliance-design.md`
- `docs/backend/strategy-loop-design.md`
- `docs/backend/archive-knowledge-design.md`
- `docs/backend/audit-ops-observability-design.md`
- `docs/backend/search-design.md`
- `docs/backend/security-secrets-privacy-design.md`
- `docs/backend/extension-governance-design.md`
- `docs/backend/contract-test-governance-design.md`
- 采集、成稿、同步、导出等既有细节附录

后端模块设计不能决定卡片、tab、顶部栏按钮等页面布局。

### 3.4 部署同步要和业务能力解耦

`docs/deployment/deployment-topology.md` 定义部署形态和能力开关；
`docs/deployment/multi-environment-sync.md` 定义数据边界和同步协议。

内网部署不是另一套产品。它是同一代码在 `DEPLOY_MODE=intranet` 下禁用采集、
启用 header 登录和 pull-only 同步。内网评论、点赞、评分、采信、需求、任务默认留在内网本地。

## 4. 修改同步规则

改主链路：

- 更新 `docs/00-system-design.md`
- 更新相关模块文档
- 更新相关 `config/contracts/*.json`
- 更新 `docs/architecture/capability-map.md` 的状态/缺口

改前端页面或顶部栏：

- 更新 `docs/product/frontend-product-design.md`
- 更新 `docs/product/page-specs/frontend-page-specs.md` 的对应页面已做/未做和测试看护
- 如果涉及 API 或页面实现落点，更新 `docs/implementation/api-and-ui-implementation.md`
- 如果涉及后端能力，先更新对应后端模块文档和 contract

改后端模块：

- 更新 `docs/backend/backend-module-design.md`
- 更新对应专题模块文档
- 更新相关 contract、schema、测试

改数据抓取、流转、存储：

- 更新 `docs/backend/data-ingestion-flow-storage-design.md`
- 更新 `docs/backend/ingestion-adapter-dedup-spec.md` 或 `docs/backend/data-lineage-and-storage.md` 中的细节附录
- 更新 `config/contracts/source_fields.json`、`config/contracts/adapter_pipeline.json`
- 更新覆盖率、补采和追溯相关测试

改推荐评分：

- 更新 `docs/backend/recommendation-scoring-design.md`
- 更新 `docs/backend/feedback-heat-scoring.md` 中的热度/来源评分细节
- 更新评分配置、API schema 和前端解释字段

改流水线/任务：

- 更新 `docs/backend/pipeline-jobs-design.md`
- 更新涉及的 run API、worker、scheduler、部署配置和测试
- 如涉及工作台 `schedule_policy`，同步 `config/contracts/workspace_model.json`
- 确认部署形态能力开关仍覆盖 API、scheduler 和前端

改生成模型 provider/生成策略：

- 更新 `docs/backend/generation-provider-design.md`
- 更新 `config/contracts/workspace_model.json` 的 `generation_policy`
- 新增实例级 env 时同步 `config/contracts/deployment_modes.json` 的 `related_env`
  与启动自检规则位
- 密钥治理边界同步 `docs/backend/security-secrets-privacy-design.md`

改报告编审发布：

- 更新 `docs/backend/reports-editorial-design.md`
- 更新 `docs/backend/report-renditions-design.md` 中的成稿投影细节
- 更新采信、发布、锁定、版本和审计测试

改工作台配置：

- 更新 `docs/backend/workspace-configuration-design.md`
- 更新 `docs/backend/workspace-module-model.md` 和 `config/contracts/workspace_model.json`
- 同步 label/feedback policy、sections、members、source links 的前后端测试

改登录/用户/权限/SSO：

- 更新 `docs/backend/identity-access-design.md`
- 更新 `docs/deployment/auth-unified-login.md`
- 更新 `docs/deployment/deployment-topology.md` 中部署形态约束
- 更新 `config/contracts/auth_modes.json`

改评论/点赞/评分/通知：

- 更新 `docs/backend/collaboration-notification-design.md`
- 更新 `docs/backend/feedback-heat-scoring.md`
- 若新增通知 contract，更新 `config/contracts/notifications.json`
- 更新前端消息入口设计，避免出现无后端闭环的铃铛或红点

改洞察/需求/任务：

- 更新 `docs/backend/strategy-loop-design.md`
- 更新 `config/contracts/strategic_loop.json`
- 更新需求、任务、来源追溯和通知/审计测试

改历史归档/实体大事记/质量归档：

- 更新 `docs/backend/archive-knowledge-design.md`
- 更新 `config/contracts/archive_knowledge.json`
- 如涉及旧资产导入，再更新 `docs/backend/tech-insight-loop-fusion-plan.md` 或旧资产导入 contract
- 更新归档只读、导入验收和“不得进入当前推荐/SQL”的测试

改审计/运维/可观测：

- 更新 `docs/backend/audit-ops-observability-design.md`
- 更新 `config/contracts/audit_ops.json`
- 更新 `docs/deployment/deployment-ops.md` 或部署验收脚本
- 更新 audit action、健康检查、告警、备份恢复证据

改顶部搜索或统一检索：

- 更新 `docs/backend/search-design.md`
- 更新 `docs/product/frontend-product-design.md`
- 更新 `config/contracts/search.json`
- 更新权限过滤、结果跳转和空态测试；没有 Search 后端时顶部搜索不得显示

改公网/内网同步：

- 更新 `docs/deployment/deployment-topology.md`
- 更新 `docs/deployment/multi-environment-sync.md`
- 更新 `docs/backend/sync-conflict-distribution-design.md`
- 更新 `config/contracts/sync_strategy.json`

改安全、密钥、cookie、CSRF、trusted header 或同步脱敏：

- 更新 `docs/backend/security-secrets-privacy-design.md`
- 更新 `docs/deployment/deployment-topology.md`、`docs/deployment/auth-unified-login.md` 或相关 contract
- 更新 secret-like redaction、启动自检、CSRF、header 信任边界测试

改扩展点、domain pack、adapter、report format 或可选页面：

- 更新 `docs/backend/extension-governance-design.md`
- 更新 `docs/backend/extension-points.md`
- 更新 `config/contracts/extension_points.json` 或相关注册表测试

改 contract、schema、前端测试或假控件问题：

- 更新 `docs/backend/contract-test-governance-design.md`
- 更新相关 contract、Pydantic schema、TypeScript API type、Vitest/pytest/Playwright
- 已发现的假成功和点击无效问题必须进入回归测试

改字段：

- 更新对应 contract
- 更新模块文档
- 更新 `docs/reference/data-examples.md`

改 SQL 导出：

- 更新 `docs/backend/export-compliance-design.md`
- 更新 `config/contracts/news_sql_mapping.json`
- 更新 `docs/backend/data-format-mapping.md`
- 更新 `docs/reference/data-examples.md`
- 确认 `scripts/validate_company_sql.py` 仍覆盖新字段

## 5. 设计进入开发门禁

任何新增能力进入代码前必须回答：

1. 它属于哪个后端模块？
2. 它出现在哪些前端页面或全局壳位置？
3. 它是否需要新增或修改 contract？
4. 它如何验收，前端和后端各有哪些测试？
5. 它在 standalone/cloud/extranet/intranet 四种部署形态下是否一致可用？

以上问题没有明确答案前，不开发“看起来可用”的前端控件。

## 6. 旧文档处理

`docs/reference/system-blueprint.md` 仍保留为历史全量蓝图和页面规格来源，但不再作为唯一总纲。
当它与当前分层文档冲突时，先按本 README 的权威关系修正冲突，再开发。

旧系统事实仍以 `docs/reference/legacy-system-spec.md` 和私有参考仓 `InfoWatchtower-References`
为准。参考仓是事实来源，不是新系统运行入口。
