# Deployment 文档索引

本目录放部署、登录接入、多环境同步和运维手册。它说明同一套代码在不同部署形态下
如何启停能力，不重新定义业务主链路。

| 文档 | 定位 |
|---|---|
| `deployment-topology.md` | standalone、cloud、extranet、intranet 四种部署拓扑和能力开关 |
| `multi-environment-sync.md` | extranet feed、intranet pull、同步对象边界和手工包 fallback |
| `auth-unified-login.md` | local、public password、OIDC、intranet header 的统一身份接入 |
| `auth-security-roadmap.md` | 认证安全加固路线 |
| `deployment-ops.md` | 安装、升级、备份、恢复、运行检查和生产证据 |
| `development-quickstart.md` | 本地开发启动说明 |

内网部署不是另一套产品；它是同一代码在 `DEPLOY_MODE=intranet` 下禁用采集、启用
trusted header 登录和 pull-only 同步。
