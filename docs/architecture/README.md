# Architecture 文档索引

本目录只放架构治理、能力状态和高层目标态装配文档。它不承载字段契约、
页面逐项设计或某个后端模块的实现细节。

## 主文档

| 文档 | 定位 |
|---|---|
| `design-governance.md` | 设计分层、评审门禁和新增能力进入开发的规则 |
| `capability-map.md` | 当前已实现能力、缺口、证据和优先级 |
| `software-design-description.md` | 正式 SDD 总装版，面向完整设计审查 |
| `workspace-report-knowledge-chat-plan.md` | 工作台取数、报告发布发现、知识库与 Chat 架构纠偏的跨模块评审入口和施工索引 |

## 附录

| 文档 | 定位 |
|---|---|
| `target-state-spec.md` | 目标态增量工作包和实现级补充 |
| `strategic-intelligence-platform.md` | 长期愿景展开，不作为第一版实现入口 |

更新规则：目标架构和硬约束先改 `docs/00-system-design.md`；实现状态只改
`capability-map.md`；设计分层和门禁只改 `design-governance.md`。
