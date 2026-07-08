# 前端运行态检查结果（2026-07-08，代码更新后复查）

本文只记录本轮重新识别到的前端不合适处，不包含修复实现方案。

检查口径：

- 运行入口：已启动前端 `http://127.0.0.1:5173`，本地账号 `admin/password`。
- 页面范围：`AppShell` 内全部导航页、数据源详情、日报详情/编辑、登录/邀请/初始化、账号、通知、顶部搜索入口和主要弹层。
- 视口范围：桌面 `1440x900`、平板 `1024x768`、窄屏 `390x844`。
- 交互范围：只打开页面、筛选/搜索入口和弹层；未执行发布、导出、导入、创建、删除、运行抓取等会改变数据的提交动作。
- 对照口径：用户已审批的 Liquid Glass 视觉基线、`frontend-product-design.md` 的布局/弹层约束、`frontend-page-specs.md` 的逐页目标态。

## 0. 本次复查结论

- 旧文档中的两个能力类 P0 已不再成立：`/api/pipeline/scheduler/status`、`/api/workspaces/planning_intel/schedule-policy`、`/generation-policy`、`/join-code` 本轮均返回 `200`，`/dashboard` 调度心跳和 `/workspace-settings` 三张能力卡已能加载。
- 全路由运行巡检未发现登录后页面触发新的后端 `4xx/5xx`；仅登录前会有一次当前用户态探测的 `401 Unauthorized`，本轮不列为前端问题。
- 当前高优先级问题已经从“接口 404”转为“用户 journal 不顺、工程字段外露、窄屏可操作性不足”。这些问题会直接影响情报编审人员在移动端阅读、复核、配置和采信。

## 1. P0 问题

### 1.1 全局移动端 AppShell 仍像桌面导航被压缩，不符合用户 journal

在 `390x844` 下，所有业务页顶部仍展示横向工作台/导航集合，右侧入口被裁切。自动检测到 `.nav-list` 可见宽度约 `2178px`，`发现工作台` 按钮右边界到 `468px`，超出 `390px` 视口；页面通过隐藏溢出避免了部分横向滚动，但用户看到的是右侧图标和入口被截断。

影响：

- 第一屏被全局壳占掉较多空间，日报、候选、推荐等核心内容被明显下压。
- 移动端用户无法确信右侧还有多少入口，也难以稳定进入发现工作台、系统入口和完整导航。
- 这不是单页问题，`/dashboard`、`/sources`、`/recommendations`、`/users`、`/account` 等页面均复现。

### 1.2 `/recommendations` 移动端存在页面级横向滚动

`/recommendations` 是推荐复核主链路，但在 `390x844` 下 `document.scrollWidth = 585px`，比视口宽 `195px`。首屏里评分器版本号 `content-scorer-2026-05-11-v3-enhanced-no-new-boards+strategic-20260519`、策略卡和全局顶栏共同撑开页面。

影响：

- 推荐运行页是编辑采信前的核心复核页，横向滚动会干扰 P0/P1/P2 判断、推荐理由阅读和观察池复核。
- 当前表现更像工程配置台，而不是情报编辑的移动工作流。

### 1.3 多个页面直接暴露工程字段和原始枚举，不符合业务用户语言

当前页面中仍有大量实现层字段直接可见，影响业务用户理解和信任。

| 页面 | 当前外露内容 |
|---|---|
| `/workspace-settings` | `provider`、`base_url`、`env`、`internal_public`、`viewer/member/admin/owner`、`domain pack`、`company_sql_v1`、`ai_sql_categories` 等直接展示。 |
| `/ingestion-runs` | 自动调度卡出现“在部署 .env 中调整 `INGESTION_SCHEDULER_*` 后重启 scheduler 服务生效”，这是运维实现说明，不是工作台配置语言。 |
| `/insights` | 状态和类型展示为 `draft/confirmed/linked_to_requirement/archived`、`trend/risk/opportunity/competitor_move`、`capability_gap/competitive_pressure`。 |
| `/requirements` | 优先级展示为 `high/medium/low`，来源字段是 `日报条目 ID`、`实体事件 ID`。 |
| `/tasks` | 状态展示为 `open/doing/blocked/done/canceled`，统计展示 `0 tasks`。 |
| `/sync` | 角色和说明直接出现 `standalone`、`sync_publisher`、`sync_consumer`、`consumer`。 |
| `/audit-logs` | 审计记录正文直接铺 JSON，例如 `{"actor":"admin","day_key":"2026-06-30","workspace_code":"planning_intel"}`。 |

这些内容对于开发者可理解，但不符合情报团队的 journal。页面应该表达“公开可发现、只读成员、编辑成员、同步发布端、同步接收端、待转需求”等业务语义，而不是让用户阅读 schema、枚举和环境变量。

### 1.4 设置/账号/权限类页面在移动端仍不可完整操作

`/users`、`/account`、`/workspace-settings` 是管理入口，但窄屏下仍有明显可操作性问题。

| 页面 | 当前问题 |
|---|---|
| `/users` | 用户表仍是宽表结构，角色复选框和操作列被裁到右侧，只能看到部分控件，无法完整确认“保存/重置/停用”等动作和对应角色。 |
| `/account` | `PROFILE` 标题左侧被裁切，资料表单和改密表单仍按两列排布，输入框过窄，卡片内又嵌套白底表单块，移动端不像可稳定填写的账号页。 |
| `/workspace-settings` | 页面高度约 `6610px`，所有设置能力线性堆叠；生成模型、可见性、加入码、反馈回哺都在同一长页里，移动端发现和完成一个配置项成本过高。 |

## 2. P1 页面布局与显示问题

| 页面 | 问题 |
|---|---|
| 全局 AppShell | 窄屏顶部壳高度和横向入口过重；虽然多数页面没有 body 级横向滚动，但右侧导航/发现入口实际被裁切。 |
| `/sources` | 移动端把 397 个启用源、429 个共享源作为长信息流一次铺开，实测页面高度约 `130566px`；缺少分页、虚拟列表或按方向/状态折叠，阅读和性能压力都偏大。 |
| `/sources` 导入预览 Modal | 移动端样本行仍把名称、类型、URL 挤在一起，例如 `Anthropic NewsRSShttps://...`，缺少清晰分隔，长 URL 可读性差。 |
| `/sources/:id` | 多个空态仍只呈现“暂无 raw 趋势 / 暂无错误日志 / 暂无 raw 入库记录”，没有给出下一步动作，例如运行抓取、检查源 URL、查看最近 run。 |
| `/daily-reports` | 移动端页面高度约 `16806px`，时间轴、筛选、日报正文和导出动作堆叠较长；作为阅读页可用，但首屏信息密度和回到指定条目效率仍偏低。 |
| `/daily-reports/:id` / `/edit` | 详情和编辑页在移动端基本是同一长列表，编辑态只是条目旁出现“编辑”，缺少版本差异、变更提示和更明确的编辑工作区。 |
| `/weekly-reports` | 移动端页面高度约 `19762px`，50 条候选直接长列表展开；周报长文、分页/分批管理和热度/反馈排序仍未形成高效编审体验。 |
| `/ingestion-runs` | 调度卡已出现，但页面仍把覆盖漏斗、趋势、失败源、运行历史、raw 明细全部堆在长页内，移动端定位“失败原因”和“要处理的源”成本较高。 |
| `/audit-logs` | 审计日志直接展示 action code、对象 UUID 和 JSON details，缺少面向管理员的事件摘要、关键字段折叠和关联对象入口。 |
| 新建工作台 Modal | 第 1 步仍显示“上一步”按钮；虽然不产生溢出，但状态语义不准确。 |
| `/historical-reports` | “旧系统导入 0 份 / 暂无导入验收数据”已经有说明，但缺少导入验收缺口的明确入口或待办提示。 |

## 3. P1/P2 能力未完全实现

| 页面 | 未闭合能力 |
|---|---|
| `/dashboard` | 调度心跳已恢复，但头条候选为空时的下一步仍只给“先跑一次抓取”；源健康只有 TopN 异常，长期失败趋势、处理入口和跳转旅程仍需补齐。 |
| `/sources` | 导入预览、标签策略保存、详情跳转仍缺完整 Playwright 旅程验证；源列表还缺分页/虚拟化和更强的源治理分组。 |
| `/sources/:id` | 采信贡献趋势、评分贡献解释、最近抓取/错误的可行动入口仍不足。 |
| `/ingestion-runs` | OpenReview 等深度补采 provider、复杂 SQL dialect、大文件分片、邮件/外部告警、生产 runbook 仍未闭合；调度配置仍偏运维说明。 |
| `/news` | 候选池加载完成后可展示数据，但跨页联动、批量采信/剔除旅程和去重解释的端到端验证仍不足。 |
| `/recommendations` | 评分器策略编辑、配置变更影响预览、批量重算、观察池排序/备注/抽检队列仍未完成；移动端横向滚动需优先处理。 |
| `/daily-reports` | 富文本、编辑差异、更多对象通知和完整 E2E 未完成。 |
| `/daily-reports/:id` / `/daily-reports/:id/edit` | 编辑体验、版本/差异和权限态测试仍不足。 |
| `/weekly-reports` | LLM 周报摘要模型、热度/反馈排序、超过 200 条分页/分批管理和周报长文自动生成未完成。 |
| `/historical-reports` | 生产主库导入验收证据、跨来源对账和更多 E2E 未补齐。 |
| `/entity-milestones` | 当前实体为 0 时可解释，但从日报采信条目抽取候选、确认入库、人工补录的端到端旅程仍未补齐。 |
| `/quality-archive` | 当前反馈、推荐反馈分解释关系和导入验收 E2E 仍不足。 |
| `/insights` | insight 到 requirement 联动抽屉、批量转需求、当前反馈/归档聚合解释未完成，表单仍暴露 raw enum。 |
| `/requirements` | 需求与评论、任务、日报条目/实体事件的联动体验仍不完整。 |
| `/tasks` | 跨对象联动、评论、归档对象解释关系和状态中文化未闭合。 |
| `/sync` | extranet -> intranet 端到端实机证据、生产告警投递/runbook 和更多对象 `manual_merge` 仍未闭合。 |
| `/exports` | 真实内网平台生产联调证据、导出历史和批量 Manifest 验收仍未补齐。 |
| `/workspace-settings` | 自动化、生成模型、加入码接口已可用，但生成模型配置仍以 provider/key/base_url 视角呈现；“推荐设置（内容导向）”与反馈回哺的业务化配置仍不足。 |
| `/users` | 真实 provider / 内网门户验收缺失；移动端角色操作显示不完整。 |
| `/audit-logs` | action taxonomy、告警/运行证据联动和 JSON 业务化展示不足。 |
| `/login` | 真实 OIDC / intranet header provider 登录、建号、membership 和登出体验证据不足。 |
| `/setup` | 当前环境会从 `/setup` 重定向到登录页；真实空库端到端证据未补齐。 |
| `/invite/:code` | 第一版只做最小密码长度和确认一致性校验，没有复杂密码强度仪表和全状态验收。 |
| `/account` | 会话列表和主动踢下线未完成；移动端表单布局仍需修正。 |
| `/notifications` | 邮件投递、更多对象通知生成和提及仍未完成。 |
| 顶部搜索 | v1 结果面板已恢复，但关键旅程 Playwright E2E 仍未补齐。 |

## 4. 本轮不再列为问题的点

- `/dashboard` 调度心跳接口已返回 `200`，页面可显示调度器在线、自动调度、下次运行和最近运行。
- `/workspace-settings` 自动化、生成模型、可见性与加入码三块能力不再是 `404` 状态。
- 新建工作台、发现工作台、新增信息源、导入预览当前均为移动端全屏 Modal，未发现 Modal 自身横向溢出。
- `/news` 候选池在较短等待时会显示加载中，但等待约 6 秒后可正常展示候选数据，本轮不按“卡死”记录。
