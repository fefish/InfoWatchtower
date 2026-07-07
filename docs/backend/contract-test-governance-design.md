# 契约与测试治理设计

> 状态：目标态设计稿。本文是 InfoWatchtower 的契约、测试和验收治理事实源。
> 它不定义某个业务字段的具体含义；字段以 `config/contracts/*.json` 和对应模块文档为准。

本文回答一个问题：怎样防止“前端看起来成功、后端没有真实能力”的假闭环。

## 1. 模块定位

契约与测试治理是横切能力，连接四层事实源：

```text
设计文档
-> 机器契约 / API schema
-> 前后端实现
-> 自动化测试 / 验收证据
```

它不归属于某个页面，也不归属于某个后端业务模块。任何新能力进入开发前，
必须先能回答：

- 属于哪个后端模块。
- 出现在哪些前端页面或全局壳位置。
- 是否需要新增或修改 contract。
- 前端、后端、部署形态如何测试。
- 如何证明空态、禁用态和错误态不是假成功。

## 2. 权威关系

| 层 | 事实源 | 职责 |
|---|---|---|
| 架构分层 | `docs/architecture/design-governance.md` | 说明设计怎么分层 |
| 文档地图 | `docs/README.md` | 说明改什么同步哪些文档 |
| 业务总纲 | `docs/00-system-design.md` | 定义目标态和不可破坏边界 |
| 后端模块 | `docs/backend/backend-module-design.md` + 专题文档 | 定义数据、API、任务、事件、权限 |
| 前端页面 | `docs/product/frontend-product-design.md` | 定义页面任务、控件出现规则、状态 |
| 机器契约 | `config/contracts/*.json` | 固定字段、枚举、流程、同步对象 |
| 前端控件治理契约 | `config/contracts/frontend_control_governance.json` | 固定全局控件、按钮/路由入口、假控件扫描和测试证据 |
| 代码 schema | Pydantic schema / TS API type | 固定 request/response shape |
| 测试 | backend pytest / frontend Vitest / Playwright | 证明实现符合契约 |

如果这些层冲突，不能静默选择其中一个实现。必须先修正文档和 contract，再开发。

## 3. 能力进入开发门禁

任何新增能力必须先形成一个最小设计包：

| 项 | 必填内容 |
|---|---|
| 后端模块 | 所属模块、主责表、状态机、事件、权限 |
| 前端位置 | 页面、弹层、顶部栏或侧边栏入口，含空态和禁用态 |
| Contract | 字段、枚举、错误码、部署形态开关 |
| 后端测试 | happy path、权限、错误语义、幂等或并发语义 |
| 前端测试 | 控件触发、加载态、错误态、空态、部署形态隐藏 |
| 验收证据 | 命令输出、截图、SQL 校验或同步包 trace |

缺少任一项时，只能写设计，不能写“看起来可用”的 UI。

## 4. 契约类型

### 4.1 JSON contract

`config/contracts/*.json` 用于固定跨模块不可漂移的结构：

- source 字段和 adapter pipeline。
- auth mode 和 membership 规则。
- workspace 和 section 模型。
- sync 对象、feed、package 和 conflict 规则。
- SQL 导出映射。
- extension point。
- strategic loop。
- legacy archive import 边界。
- frontend control governance：全局搜索、通知、账号入口、按钮动作、RouterLink 目标和测试证据。

修改字段、枚举、状态机或同步对象时，必须同步 contract。

### 4.2 API schema

API schema 是前后端之间的调用合同，至少需要覆盖：

- request body。
- query 参数。
- response 字段。
- error code 和 error body。
- 权限错误和部署能力禁用错误。

前端不能根据页面需要临时猜字段。

### 4.3 前端行为契约

页面行为也要被测试固定：

- 点击按钮前是否必须先打开确认或导入预览。
- 成功数量为 0 时是否能显示为成功。
- `DEPLOY_MODE=intranet` 下采集按钮是否隐藏或禁用。
- 顶部搜索、通知、用户胶囊是否有真实承接页面。
- 空态是否给出下一步，而不是只显示“暂无”。

## 5. 后端测试矩阵

每个后端模块至少覆盖：

| 类型 | 要求 |
|---|---|
| 模型测试 | 外键、唯一键、状态字段、追溯链 |
| API 测试 | request/response、权限、错误语义 |
| Contract 测试 | contract 中的枚举和代码注册表一致 |
| 幂等测试 | 导入、同步、导出、重复请求不产生脏数据 |
| 部署形态测试 | capability disabled 时 API 拒绝且语义明确 |
| 回归测试 | 用户已指出的问题必须变成测试 |

关键语义不能只靠前端阻止。例如内网部署禁采集，后端也必须拒绝采集 API。

## 6. 前端测试矩阵

前端测试分三层：

| 层 | 工具 | 覆盖 |
|---|---|---|
| API client / store | Vitest | 字段解析、错误处理、runtime capability |
| 页面组件 | Vitest + Testing Library | 弹窗、按钮、空态、禁用态、0 结果语义 |
| 用户旅程 | Playwright | 登录、导入预览、抓取、日报、同步、导出 |

必须重点覆盖：

- 数据源导入先 preview，再明确确认 import。
- 抓取 run 返回 `no_sources` 时不能显示“成功 0 条”。
- `limit=0` 前端不能发出，后端也返回 422。
- 顶部栏隐藏没有后端闭环的搜索和通知。
- 用户胶囊必须跳转 `/account` 或打开真实账号菜单。
- viewer 角色只能看到策略允许的反馈入口。
- 今日速览这类聚合页必须覆盖真实 API 聚合、空态、错误态和部署能力禁显，不得把
  `health/coverage` 降级渲染成绿色正常。

## 7. 假控件拦截规则

以下情况视为设计或实现失败：

- 点击后没有行为的按钮、图标、头像或通知铃铛。
- 显示成功但没有真实对象被创建、更新或明确解释 0 结果。
- 前端直接 mock 成功而没有 API 或 contract。
- 顶部搜索只搜索页面名，却放在全局情报搜索位置。
- 通知红点没有后端 unread state。
- 登录页不按 `AUTH_MODE` 展示正确入口。

允许存在的轻实现必须明确标注为：

- 后端返回 `skipped_unimplemented`。
- 前端展示“当前部署形态不可用”。
- 文档列入当前缺口和验收标准。

## 8. CI 与本地门禁

提交前按改动范围执行：

| 改动 | 最低门禁 |
|---|---|
| 后端模块 | `pytest` 对应测试 + migration check |
| 前端页面 | `npm run build` + 相关 Vitest |
| SQL 导出 | `scripts/validate_company_sql.py` |
| 部署 | `scripts/check_prod_deploy.py` |
| 合同字段 | contract/schema/type/test 同步检查 |
| 前端控件/假入口 | `python3 scripts/validate_frontend_controls.py` |
| 文档治理 | `git diff --check -- docs config/contracts` |

完整发布验收使用 `scripts/run_full_acceptance.py`，证据归档到 `outputs/acceptance/`。

## 9. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| Contract 与 API schema 没有自动生成关系 | contract 枚举和 schema/TS type 有漂移检测 |
| 前端 E2E 覆盖不足 | `/setup` router guard 已有组件级路由测试；关键旅程仍需 Playwright 证据 |
| 假控件扫描深化 | `scripts/validate_frontend_controls.py` v1 已能扫描页面/壳按钮、RouterLink、占位文案和 AppShell 全局入口的 API/contract/test 证据；后续补更多页面级业务入口映射和 Playwright evidence |
| 部署形态测试仍偏后端 | AppShell、Dashboard、Sources、Source Detail、Ingestion Runs 等前端 runtime capability 已有组件测试；继续补 Playwright 关键旅程 |
| 测试证据分散 | 能按能力块找到最新验收命令和输出路径 |

## 10. 验收标准

- 每个一级后端模块都有专题设计、contract 或明确“不需要 contract”的说明。
- 每个全局前端控件都有真实后端模块和承接页面。
- 用户指出过的假成功问题都变成自动化测试。
- 新增 API 有权限、错误语义和部署形态测试。
- 新增页面有空态、禁用态、错误态测试。
- 文档、contract、schema、测试不出现两套口径。
