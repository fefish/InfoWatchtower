# InfoWatchtower 架构设计分层

> 状态：设计体系整理稿。本文说明“设计应该怎么分层”，避免把页面控件、
> 后端模块、接口契约和部署策略混成一份补丁式文档。

## 1. 业界通常怎么分

一个复杂业务系统通常不会只靠一份“全量设计文档”承载所有信息。
更常见的分层是：

1. **产品/业务架构**
   - 回答：系统给谁用、解决什么业务问题、有哪些角色、核心闭环是什么。
   - 产物：PRD、业务蓝图、用户旅程、业务对象图。

2. **前端产品与交互设计**
   - 回答：用户从哪里进入、看到哪些页面、每个页面完成什么任务、控件什么时候出现。
   - 产物：信息架构、页面地图、用户流程、状态设计、空态/错误态、视觉系统。

3. **后端领域模块设计**
   - 回答：系统有哪些能力模块、每个模块拥有哪些数据、提供哪些 API/任务/事件、如何保证权限和一致性。
   - 产物：领域模块图、数据模型、服务边界、权限矩阵、异步任务、事件模型。

4. **前后端契约设计**
   - 回答：前端如何调用后端、字段是什么、枚举是什么、错误语义是什么。
   - 产物：OpenAPI、JSON contract、TypeScript type、Pydantic schema、测试用例。

5. **部署/安全/运维设计**
   - 回答：系统怎么部署、怎么登录、怎么同步、怎么备份、如何审计和故障恢复。
   - 产物：部署拓扑、认证方案、密钥策略、监控、备份恢复、运行手册。

6. **验收与测试设计**
   - 回答：怎样证明这个能力真的完成。
   - 产物：验收脚本、单测、集成测试、端到端测试、证据目录。

这些层之间可以互相引用，但不能互相替代。

## 2. InfoWatchtower 的设计分层

当前仓库应按下面结构维护。各子目录的 `README.md` 只做索引和主次关系说明，不承载新的
业务规则或字段契约：

| 层 | 主文档 | 作用 |
|---|---|---|
| 产品/业务架构 | `docs/00-system-design.md` | 唯一总纲，定义目标态、主链路、硬约束 |
| 前端产品与页面设计 | `docs/product/frontend-product-design.md` | 页面地图、导航、顶部栏、每页任务、前端状态与验收 |
| 前端逐页规格 | `docs/product/page-specs/frontend-page-specs.md` | 每页目标态、已做/未做、测试看护和审查笔记 |
| 后端功能模块设计 | `docs/backend/backend-module-design.md` | 后端领域模块、数据归属、API/事件/任务、权限与缺口 |
| 数据主链模块设计 | `docs/backend/data-ingestion-flow-storage-design.md` | 数据源、抓取、raw/news、去重、覆盖率和追溯 |
| 推荐评分模块设计 | `docs/backend/recommendation-scoring-design.md` | 准入、分数、推荐 run、多样性和反馈反哺 |
| 流水线任务模块设计 | `docs/backend/pipeline-jobs-design.md` | 日更编排、worker、scheduler、重试和失败恢复 |
| 报告编审模块设计 | `docs/backend/reports-editorial-design.md` | 采信、编辑覆盖、发布、锁定和报告版本 |
| 工作台配置模块设计 | `docs/backend/workspace-configuration-design.md` | 工作台、sections、成员、label/feedback policy 和 domain pack |
| 身份权限模块设计 | `docs/backend/identity-access-design.md` | 用户、登录、SSO、角色、邀请、工作台 membership |
| 协作通知模块设计 | `docs/backend/collaboration-notification-design.md` | 点赞、评分、评论、活动事件、通知和反馈策略 |
| 战略闭环模块设计 | `docs/backend/strategy-loop-design.md` | insight、战略含义、需求、任务和外部信号追溯 |
| 资料库知识模块设计 | `docs/backend/archive-knowledge-design.md` | 历史报告、实体大事记、质量归档和旧资产导入验收 |
| 同步冲突模块设计 | `docs/backend/sync-conflict-distribution-design.md` | feed/pull、inbox、冲突、resolve 和人工包 fallback |
| 导出合规模块设计 | `docs/backend/export-compliance-design.md` | SQL 导出预检、门禁、trace 和下载权限 |
| 审计运维可观测设计 | `docs/backend/audit-ops-observability-design.md` | 审计日志、运行状态、告警、备份恢复和验收证据 |
| 全局检索模块设计 | `docs/backend/search-design.md` | 检索对象、权限过滤、结果跳转和顶部搜索恢复条件 |
| 安全密钥隐私设计 | `docs/backend/security-secrets-privacy-design.md` | secrets、cookie、CSRF、trusted header、同步脱敏和隐私边界 |
| 扩展治理设计 | `docs/backend/extension-governance-design.md` | adapter、domain pack、report format、auth provider 和可选页面治理 |
| 契约测试治理设计 | `docs/backend/contract-test-governance-design.md` | contract、schema、测试、假控件拦截和 CI 门禁 |
| 前后端 API 与 UI 对照 | `docs/implementation/api-and-ui-implementation.md` | API 面、页面实现快照、前后端落点 |
| 机器契约 | `config/contracts/*.json` | 字段、枚举、流程、映射、可测试合同 |
| 部署与同步 | `docs/deployment/deployment-topology.md`、`docs/deployment/multi-environment-sync.md` | 部署形态、能力开关、内网 iframe、extranet feed / intranet pull |
| 身份接入专题 | `docs/deployment/auth-unified-login.md`、`docs/deployment/auth-security-roadmap.md` | 外部认证如何映射到本地身份 |
| 能力现状与差距 | `docs/architecture/capability-map.md` | 哪些已实现、哪些缺口还在 |
| 实施任务 | `docs/implementation/implementation-handoff.md`、`docs/implementation/01-implementation-plan.md` | 工程交付顺序和验收命令 |

## 2.1 目录内主次关系

分层不是把文件搬进同一个目录后继续平铺。目录内必须继续区分：

- **总图**：说明领域边界和文档导航，例如 `docs/backend/backend-module-design.md`。
- **模块事实源**：定义一个可实现后端模块的目标态、状态机、API、任务、事件和权限。
- **附录**：保存映射、旧系统兼容、渲染格式、扩展示例或历史融合细节；附录不能覆盖模块事实源。
- **状态图**：只记录已做/未做、证据和优先级，例如 `docs/architecture/capability-map.md`。

如果附录、状态图和模块事实源冲突，先修模块事实源和 contract，再更新附录或状态。

## 3. 不同设计层的边界

### 3.1 前端页面设计不定义后端能力

前端页面设计可以说：

- 顶部栏应该显示哪些入口。
- 某个控件什么时候出现、什么时候隐藏。
- 用户点击后进入哪个页面。
- 空态、加载态、错误态怎么表达。

前端页面设计不能单独决定：

- 是否存在通知系统。
- 评论是否生成未读消息。
- viewer 是否能评论。
- OIDC claims 如何映射到本地用户。

这些属于后端功能模块或部署/认证设计。

### 3.2 后端模块设计不决定页面布局

后端模块设计可以说：

- 用户、角色、权限、工作台成员归属哪个模块。
- 评论、点赞、评分写哪些表。
- 通知事件如何生成、如何标记已读。
- SSO 登录如何落到本地用户。

后端模块设计不能单独决定：

- 顶部栏放几个按钮。
- 页面卡片怎么排。
- 哪个 tab 默认展开。

这些属于前端产品与交互设计。

### 3.3 契约是前后端之间的桥

当一个设计被用户确认并进入开发，必须落到契约：

- 字段、枚举、状态机：写入 `config/contracts/*.json`。
- API request/response：写入 schema、API client 和测试。
- 页面行为：写入前端测试或 E2E 验收。

没有契约的控件不能开发成“看起来可用”的假功能。

## 4. 新能力进入开发的规则

任何新增能力必须回答四个问题：

1. **它属于哪个后端模块？**
   - 例如：通知属于“协作与通知模块”，不是 AppShell 的局部状态。

2. **它在哪些前端页面出现？**
   - 例如：通知的主页面是“我的消息”，顶部铃铛只是快捷入口。

3. **它的契约是什么？**
   - 例如：`GET /api/notifications` 返回哪些字段，未读状态如何更新。

4. **它如何验收？**
   - 例如：A 评论并 @ B，B 收到未读通知，点击能跳到对应评论。

这四个问题没有答案前，不写代码。

如果新增或移动设计文档，还必须运行 `make docs-check`。该门禁检查三件事：
`docs/` 根目录只能保留 `README.md` 和 `00-system-design.md`；每份 `docs/**/*.md`
必须被最近一层目录的 `README.md` 索引；仓库内所有 `docs/...md` 引用都必须指向真实文件。

## 5. 对当前问题的修正

之前把“用户模块、顶部栏、消息通知”写成一份文档是错误分层：

- 用户、权限、SSO、通知事件生成属于后端功能模块设计。
- 顶部栏、消息入口、页面呈现属于前端产品与页面设计。
- 二者通过 API/contract 连接。

因此，后续改为：

- `docs/product/frontend-product-design.md`：整理顶部栏、导航、页面信息架构和前端用户旅程。
- `docs/product/page-specs/frontend-page-specs.md`：整理逐页目标态、已做/未做和测试看护。
- `docs/backend/backend-module-design.md`：整理后端领域模块总图。
- `docs/backend/data-ingestion-flow-storage-design.md`：整理抓取、流转、存储、去重和覆盖率。
- `docs/backend/recommendation-scoring-design.md`：整理准入、评分、推荐和反馈反哺。
- `docs/backend/pipeline-jobs-design.md`：整理流水线编排、任务状态、重试和调度。
- `docs/backend/reports-editorial-design.md`：整理采信、编辑、发布、锁定和版本。
- `docs/backend/workspace-configuration-design.md`：整理工作台配置、sections、成员和策略。
- `docs/backend/identity-access-design.md`：整理用户、权限、SSO、邀请和 membership。
- `docs/backend/collaboration-notification-design.md`：整理评论、点赞、评分、activity event 和通知。
- `docs/backend/strategy-loop-design.md`：整理 insight、需求、任务和外部信号追溯。
- `docs/backend/archive-knowledge-design.md`：整理历史报告、实体大事记、质量归档和旧资产导入验收。
- `docs/backend/sync-conflict-distribution-design.md`：整理同步冲突、resolve 和分发边界。
- `docs/backend/export-compliance-design.md`：整理导出预检、合规门禁和 trace。
- `docs/backend/audit-ops-observability-design.md`：整理审计、运行状态、告警、备份恢复和证据。
- `docs/backend/search-design.md`：整理全局检索和顶部搜索恢复条件。
- `docs/backend/security-secrets-privacy-design.md`：整理安全、密钥、隐私和脱敏边界。
- `docs/backend/extension-governance-design.md`：整理扩展进入系统的治理规则。
- `docs/backend/contract-test-governance-design.md`：整理契约、测试、假控件拦截和验收门禁。
