# 前端运行态检查结果（2026-07-08）

本文只记录本轮识别到的前端不合适处，不包含修复实现方案。

检查口径：

- 运行入口：已启动前端 `http://127.0.0.1:5173`，本地账号 `admin/password`。
- 页面范围：`AppShell` 内所有导航页、登录/邀请/初始化、账号、通知、顶部搜索入口和主要弹层。
- 视口范围：桌面 `1440x900`、平板 `1024x768`、窄屏 `390x844`。
- 交互范围：只打开页面、筛选/搜索入口和弹层；未执行发布、导出、导入、创建、删除等会改变数据的提交动作。
- 对照口径：用户已审批的 Liquid Glass 视觉基线、`frontend-product-design.md` 的布局/弹层强约束、`frontend-page-specs.md` 的逐页目标态。

## 1. P0 问题

### 1.1 `/workspace-settings` 三个能力卡已露出，但真实接口不可用

工作台配置页已展示「自动化」「生成模型」「可见性与加入码」三块目标态能力，但当前运行服务返回：

- `GET /api/workspaces/planning_intel/schedule-policy` -> `404 Not Found`
- `GET /api/workspaces/planning_intel/generation-policy` -> `404 Not Found`
- `GET /api/workspaces/planning_intel/join-code` -> `404 Not Found`

页面里三个卡片直接显示红色 `Not Found`，同时下方仍继续展示公开开关、加入码说明等控件，用户会误以为能力可配置但实际不可完成。该问题违反“页面上不能存在点击无效果/未闭合能力入口”的前端验收口径。

### 1.2 `/dashboard` 调度心跳能力未闭合

今日速览页会请求 `GET /api/pipeline/scheduler/status`，当前运行服务返回 `404 Not Found`。设计里调度心跳应作为右侧固定侧栏第 6 张运营卡展示 scheduler 在线/离线、下次运行和最近 run；当前用户看不到这张卡，也无法判断自动调度是否正常。

### 1.3 全局窄屏 AppShell 仍有不稳定横向溢出

在 `390x844` 下，全局工作台选择、新建工作台、发现工作台、导航条和右侧全局入口会跑出视口。`/recommendations` 出现页面级横向滚动，实测 `document.body.scrollWidth` 为 `585px`，比 `390px` 视口宽 `195px`。

同类越界元素在多页可见：右侧圆形图标被裁切、`发现工作台` 文字进入视口外、导航列表整体宽度远超视口。它不是单个业务页问题，而是全局壳在窄屏断点上的适配不稳定。

### 1.4 设置类页面未完全收敛到移动端单列体验

`/users`、`/account`、`/workspace-settings` 在窄屏下仍有设置页模板不一致的问题：

- `/users` 用户表格操作列和角色复选框被裁到右侧，无法完整看到角色操作。
- `/account` 资料和改密表单仍保持两列，输入框过窄，`PROFILE` 区块边缘有裁切感。
- `/workspace-settings` 粘性顶部区域占据较大高度，滚动到能力卡时页面内容被顶部壳压住，问题卡片不容易被用户发现。

这些问题不符合“settings 模板单列窄容器、移动端可完整操作”的用户 journal。

## 2. P1 页面布局与显示问题

| 页面 | 问题 |
|---|---|
| 全局 AppShell | 窄屏顶部壳高度过大，第一屏业务内容被明显下压；右侧全局图标和发现入口存在裁切。 |
| `/sources` | 移动端首屏统计卡和四个主操作按钮占比过高，真实源列表需要明显下滑；429 个源以长信息流一次性铺开，浏览和性能压力都偏大。 |
| `/sources` 导入预览 Modal | 移动端样本列表把名称、类型和 URL 挤在一起，例如 `Anthropic NewsRSShttps://...`，缺少清晰分隔，长 URL 可读性差。 |
| `/sources/:id` | 空态只显示“暂无 raw 趋势 / 暂无错误日志 / 暂无 raw 入库记录”，没有说明下一步检查动作。 |
| `/users` | 窄屏下用户表格仍是宽表结构，角色和操作列显示不完整。 |
| `/audit-logs` | 审计详情以原始 JSON 片段直接铺在卡片内，移动端阅读压力大，action taxonomy 和运行证据关联不足。 |
| `/account` | 资料卡内又嵌套白底表单块，移动端两列字段显得拥挤；会话管理区域缺失。 |
| 新建工作台 Modal | 移动端首步仍显示“上一步”按钮，状态语义不够准确。 |

## 3. P1/P2 能力未完全实现

| 页面 | 未闭合能力 |
|---|---|
| `/dashboard` | 头条候选和报告卡点击跳转缺少端到端验证；源健康只有 TopN 异常，长期失败趋势未闭合；调度心跳接口当前 404。 |
| `/sources` | 导入预览、标签策略保存和详情跳转仍缺 Playwright 级整段旅程验证。 |
| `/sources/:id` | 采信贡献趋势和更细评分贡献未完成。 |
| `/ingestion-runs` | 本页调度卡仍未升级为 pipeline scheduler 状态；OpenReview 等深度补采 provider、复杂 SQL dialect、大文件分片、邮件/外部告警和生产 runbook 未闭合。 |
| `/news` | 候选池跨页联动和 E2E 仍不足。 |
| `/recommendations` | 评分器策略编辑、配置变更影响预览、批量重算、观察池排序/备注/抽检队列未完成；窄屏还存在页面级横向滚动。 |
| `/daily-reports` | 富文本、编辑差异、更多对象通知和完整 E2E 未完成。 |
| `/daily-reports/:id` / `/daily-reports/:id/edit` | 编辑体验、版本/差异和权限态测试仍不足。 |
| `/weekly-reports` | LLM 周报摘要模型、热度/反馈排序、超过 200 条分页/分批管理和周报长文自动生成未完成。 |
| `/historical-reports` | 生产主库导入验收证据和更多 E2E 未补齐。 |
| `/entity-milestones` | 更多 E2E 未补齐。 |
| `/quality-archive` | 当前反馈、推荐反馈分解释关系和 E2E 仍不足。 |
| `/insights` | insight 到 requirement 联动抽屉、批量转需求、当前反馈/归档聚合解释未完成。 |
| `/requirements` | 需求与评论、任务的联动体验仍不够完整。 |
| `/tasks` | 跨对象联动、评论和更多归档对象解释关系未闭合。 |
| `/sync` | extranet -> intranet 端到端实机证据、生产告警投递/runbook 和更多对象 `manual_merge` 未闭合。 |
| `/exports` | 真实内网平台生产联调证据未补齐。 |
| `/workspace-settings` | 自动化、生成模型、加入码三卡当前运行态接口 404；即使页面已设计出入口，用户仍不能完成配置。 |
| `/users` | 真实 provider / 内网门户验收缺失；移动端角色操作显示不完整。 |
| `/audit-logs` | action taxonomy、告警/运行证据联动不足。 |
| `/login` | 真实 OIDC / intranet header provider 登录、建号、membership 和登出体验证据不足。 |
| `/setup` | 当前环境会从 `/setup` 重定向到登录页；真实空库端到端证据未补齐。 |
| `/invite/:code` | 第一版只做最小密码长度和确认一致性校验，没有复杂密码强度仪表。 |
| `/account` | 会话列表和主动踢下线未完成。 |
| `/notifications` | 邮件投递、更多对象通知生成和提及仍未完成。 |
| 顶部搜索 | v1 结果面板已恢复，但关键旅程 Playwright E2E 仍未补齐。 |

## 4. 本轮未列为问题的点

- 新建工作台、发现工作台、新增信息源、导入预览当前均已是居中 Modal，不再按旧右抽屉问题记录。
- `/sources` 保留单源配置上下文面板、`/daily-reports` 保留成稿格式上下文面板，符合当前产品文档的白名单判定。
- 登录页、邀请失效页在当前运行态没有发现明显错位；它们的问题主要是真实 provider / 空库 / 邀请全状态验收证据不足。
