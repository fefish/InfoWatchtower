# Product 文档索引

本目录只放前端产品、信息架构、页面规格和用户旅程设计。它不定义后端表结构、
权限数据模型或通知事件生成规则。

| 文档 | 定位 |
|---|---|
| `frontend-product-design.md` | 前端信息架构、导航、顶部栏、用户旅程和页面能力出现规则 |
| `page-specs/frontend-page-specs.md` | 逐页目标态、已做/未做、测试看护和页面审查笔记 |

修改页面、顶部栏、空态、错误态或权限态时，必须同步以上两个文件；如果页面行为依赖
后端能力，再同步对应 `docs/backend/*.md` 和 `config/contracts/*.json`。
