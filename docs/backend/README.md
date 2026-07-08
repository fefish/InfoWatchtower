# Backend 文档索引

本目录按后端领域模块组织。`backend-module-design.md` 是总图；每个业务模块有一个
事实源文档；更细的历史、映射、扩展说明只作为附录，不能反向覆盖模块事实源。

## 总图

| 文档 | 定位 |
|---|---|
| `backend-module-design.md` | 后端领域模块总图、数据归属、API/任务/事件边界和模块状态索引 |

## 模块事实源

| 模块 | 事实源 |
|---|---|
| Identity & Access | `identity-access-design.md` |
| Collaboration / Notifications | `collaboration-notification-design.md` |
| Sources / Ingestion / Content Pipeline / Storage | `data-ingestion-flow-storage-design.md` |
| Recommendation & Scoring | `recommendation-scoring-design.md` |
| Pipeline & Jobs | `pipeline-jobs-design.md` |
| Generation Provider | `generation-provider-design.md`（LLM 生成 provider 配置、工作台 generation_policy、连通性自检；基线 2026-07-08 已实现，§8-§11 Provider 预设目录 + 密钥落库 R2 修订待实现） |
| Reports & Editorial | `reports-editorial-design.md` |
| Workspace Configuration | `workspace-configuration-design.md` |
| Strategy Loop | `strategy-loop-design.md` |
| Archive / Knowledge | `archive-knowledge-design.md` |
| Sync Conflict & Distribution | `sync-conflict-distribution-design.md` |
| Export Compliance | `export-compliance-design.md` |
| Audit / Ops / Observability | `audit-ops-observability-design.md` |
| Search | `search-design.md` |
| Security / Secrets / Privacy | `security-secrets-privacy-design.md` |
| Extension Governance | `extension-governance-design.md` |
| Contract & Test Governance | `contract-test-governance-design.md` |

## 细节附录

| 附录 | 归属模块 | 用途 |
|---|---|---|
| `backend-capability-test-matrix.md` | Contract & Test Governance / 部署 | 看护矩阵：四种 DEPLOY_MODE × 能力开关 × 必跑测试、每形态禁用能力断言清单、11 类 adapter 实现状态、前端测试与 e2e 现状 |
| `ingestion-adapter-dedup-spec.md` | Sources / Ingestion / Content Pipeline | adapter、raw/news 映射和去重细节 |
| `data-lineage-and-storage.md` | Sources / Ingestion / Content Pipeline | 存储、追溯、审计链路细节 |
| `data-format-mapping.md` | Export Compliance | 三层数据映射和公司 SQL 字段映射 |
| `report-renditions-design.md` | Reports & Editorial | 多版成稿、格式注册表和渲染投影细节 |
| `feedback-heat-scoring.md` | Collaboration / Recommendation | 反馈、热度和来源评分细节 |
| `workspace-module-model.md` | Workspace Configuration | 工作台、共享源和标签模型细节 |
| `tech-insight-loop-fusion-plan.md` | Archive / Knowledge | 旧 Tech Insight Loop 融合和历史导入细节 |
| `extension-points.md` | Extension Governance | 扩展点接口边界 |
| `extension-recipes.md` | Extension Governance | 新 domain pack / adapter / report format 示例 |

## 修改规则

- 改模块目标态：先改对应“模块事实源”，再同步 `backend-module-design.md` 的状态索引。
- 改附录细节：同步对应模块事实源，避免附录成为另一套目标态。
- 改字段、枚举、接口边界：同步 `config/contracts/*.json`、Pydantic schema、TypeScript API type 和测试。
- 改页面呈现：只在 `docs/product/` 和 `docs/implementation/api-and-ui-implementation.md` 里落页面事实；后端文档只记录 API、数据、权限和事件。
