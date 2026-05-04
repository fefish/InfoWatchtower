# InfoWatchtower

规划部全自动热点追踪与情报生产系统。

当前状态：设计交接仓，可以开始全量开发第一版；还不是可运行项目。

## 接手入口

任何工程师或 AI 接手时，先读：

1. `AGENTS.md`：开发准则和修改同步规则。
2. `docs/00-system-design.md`：唯一总纲，包含愿景、主链路、扩展方式、部署方向。
3. `docs/implementation-handoff.md`：第一版开发任务书和验收标准。
4. `docs/README.md`：文档地图和修改规则。
5. `config/contracts/README.md`：解释 contracts 和 AGENTS 的区别。
6. `config/contracts/*.json`：机器可读契约，写代码时必须遵守。

其他 `docs/*.md` 是专题附录，按需阅读；`references/legacy-auto-sync-20260412/` 是旧系统参考资料，不是新系统运行入口。

完整旧系统参考资料不提交主仓，放在私有仓 `InfoWatchtower-References`。需要旧资料时看 `references/README.md`。

## 仓库内容

- `config/seeds/legacy/`：新系统可导入的旧种子源。
- `config/taxonomy/`：AI 兼容标签和长期产业情报板块。
- `config/contracts/`：数据源、adapter、SQL、登录、扩展点、战略闭环、同步策略契约。
- `config/domain_packs/`：后续扩展硬件、半导体、政策、竞品等板块的配置包。
- `docs/`：总纲和专题附录。
- `references/README.md`：私有参考仓拉取说明。
- `config/env.example`：环境变量样例。

本地旧 `.env` 已复制到 `config/.env` 以便复用，但不会进入 Git。

当前种子源统计：wiseflow 1 个、RSS 108 个、页面源 4 个，合并索引 113 个。
