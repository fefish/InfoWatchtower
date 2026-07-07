# Audit / Ops / Observability 审计运维可观测设计

> 状态：目标态设计稿。本文是审计日志、运行状态、告警、备份恢复和验收证据的
> 横切模块事实源。部署执行细节见 `docs/deployment/deployment-ops.md` 和
> `docs/deployment/deployment-topology.md`。

## 1. 模块定位

Audit / Ops / Observability 负责回答：

- 谁在什么时候做了什么关键操作。
- 系统当前是否健康。
- 抓取、生成、同步、导出是否失败。
- 生产环境能否备份和恢复。
- 一次发布或修复是否有证据可查。

它不是业务页面，也不是日志文件堆放处。它是运行可信度的后端模块。

## 2. 审计事件分类

审计事件使用稳定 action 命名：

| 分类 | 示例 |
|---|---|
| `auth.*` | login.success、login.failed、logout、password.change、oidc.callback |
| `user.*` | invite.create、invite.accept、role.update、membership.add |
| `workspace.*` | workspace.create、label_policy.update、section.enable |
| `source.*` | source.create、source.update、source.import、source.fetch |
| `ingestion.*` | run.create、run.complete、run.failed、backfill.create |
| `recommendation.*` | run.create、item.score |
| `report.*` | daily.publish、weekly.publish、item.adopt、item.edit |
| `collab.*` | comment.create、reaction.create、rating.create |
| `strategy.*` | requirement.create、task.assign、task.status_update |
| `sync.*` | feed.read、pull.run、package.import、conflict.resolve |
| `export.*` | company_sql.create、download、trace.view |
| `security.*` | csrf.reject、secret_redaction.reject、trusted_header.reject |
| `ops.*` | backup.create、restore.verify、deploy.check |

机器契约见 `config/contracts/audit_ops.json`。审计记录至少包含：

- actor user id 和身份快照。
- workspace_code。
- action。
- object_type / object_id。
- request_id。
- ip / user_agent。
- before/after 摘要或 metadata。
- created_at。

不得把 token、cookie、密码、OIDC code、`.env` 内容写入审计。

当前 v1 已补显式 `audit_logs.workspace_code`：`write_audit` 会从 `detail_json.workspace_code`
提取工作台，否则写 `global`。`GET /api/audit-logs` 不传 `workspace_code` 时只允许
`super_admin` 查询全局审计；传入 `workspace_code` 时，`super_admin` 或该工作台 admin 可查，
workspace viewer 返回 403。前端 `/audit-logs` 固定按当前工作台请求，不再默认拉取全局审计。

## 3. 运行状态

运行状态分四类：

| 类型 | 来源 |
|---|---|
| 应用健康 | `/healthz`、数据库、Redis、版本 |
| 部署能力 | `/api/meta/runtime`、`DEPLOY_MODE`、capabilities |
| 业务任务 | ingestion_runs、recommendation_runs、export_jobs、sync_runs |
| 安全事件 | login_attempts、csrf rejects、sync secret rejects |

前端页面：

- `/audit-logs`：审计查询。
- `/ingestion-runs`：抓取和覆盖。
- `/sync`：同步 run、水位、冲突。
- `/exports`：导出任务和 trace。
- 未来 Ops 面板：健康、备份、失败趋势。

## 4. 指标

目标态应有可查询指标：

| 指标 | 用途 |
|---|---|
| source success rate | 发现坏源 |
| fetched/created/updated counts | 判断抓取质量 |
| raw/news/winner/recommendation/daily funnel | 判断候选减少原因 |
| generation ready/fallback/failed | 判断模型生成健康 |
| sync pull lag | 判断内网是否滞后 |
| export preflight failures | 判断 SQL 合规风险 |
| login failure rate | 判断攻击或配置错误 |
| backup age | 判断恢复风险 |

第一阶段可以由数据库查询和页面统计承担，不强制引入 Prometheus。

## 5. 告警规则

至少需要以下告警：

| 告警 | 触发 |
|---|---|
| 抓取失败源过多 | 最近 N 次 run 中失败率超过阈值 |
| 每日流水线失败 | scheduler job failed 或日报未生成 |
| MiniMax 生成 fallback 激增 | fallback 比例超过阈值 |
| sync pull lag 过大 | 内网 cursor 长时间不前进 |
| sync conflict 未处置 | open conflict 超过阈值 |
| OIDC 登录连续失败 | provider 或 claim 映射异常 |
| 备份过期 | 超过计划时间没有成功备份 |

告警可以先在系统内生成 activity event 和通知，后续再扩展 email/webhook。

## 6. 备份与恢复

备份对象：

- PostgreSQL。
- `.env.production`。
- 上传文件目录。
- 本地导出和验收证据目录。

恢复验收必须包含：

```text
restore backup
-> migrate
-> /healthz ok
-> login ok
-> workspace list ok
-> one report read ok
-> company SQL validator ok when export exists
```

生产备份恢复不能只停留在文档流程，必须留下演练证据。

## 7. 权限

| 操作 | 最低权限 |
|---|---|
| 查看自己相关审计 | 当前暂不开放 |
| 查看工作台审计 | workspace admin |
| 查看全局审计 | super_admin |
| 查看部署健康 | super_admin |
| 执行备份恢复 | 运维权限，不通过普通前端页面 |
| 查看 sync conflict | super_admin 或 workspace owner |

## 8. 部署形态

| 部署形态 | 行为 |
|---|---|
| standalone | 本地健康和任务状态 |
| cloud | 登录、采集、导出、备份重点监控 |
| extranet | feed read、service token、同步滞后重点监控 |
| intranet | pull lag、header auth、iframe 安全重点监控 |

内网审计日志留在内网本地，不回流外网。

审计详情隐私：

- `write_audit` 必须复用 `backend/app/core/privacy.py` 脱敏 `detail_json`。
- `token/secret/password/cookie/authorization/api_key/.env/client_secret/session` 等字段值写为
  `[REDACTED]`。
- 审计日志保留 workspace scope、action、object id 和安全摘要，不保存原始 secret-like payload。

## 9. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 审计 action taxonomy 不统一 | 所有模块使用稳定 action 命名 |
| 长期覆盖趋势缺失 | 可按天/源查看趋势 |
| 告警没有收件箱闭环 | 告警生成 activity event/notification |
| 生产备份恢复演练缺证据 | 有一次真实恢复报告 |
| sync conflict 处置审计深化 | 查询、resolve 和 UI 已有；后续补稳定 action taxonomy、处置趋势和告警联动 |

## 10. 验收标准

- 登录、权限、采集、发布、导出、同步、策略变更都写审计。
- 审计 `detail_json` 不包含原始 secret-like 值。
- `/audit-logs` 能按 action、工作台、对象过滤；用户过滤仍为后续详情增强。
- 失败任务有状态、错误和重试/处置路径。
- 备份恢复演练有命令输出和健康检查证据。
- 审计和日志不包含 secret-like 字段。
