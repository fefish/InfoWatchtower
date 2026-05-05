# InfoWatchtower

规划部全自动热点追踪与情报生产系统。

当前状态：阶段 1 已完成数据库模型、初始迁移和追溯链路测试；业务流程 API、登录、抓取、推荐和 SQL 导出仍在开发中。

## 接手入口

任何工程师或 AI 接手时，先读：

1. `AGENTS.md`：开发准则和修改同步规则。
2. `docs/00-system-design.md`：唯一总纲，包含愿景、主链路、扩展方式、部署方向。
3. `docs/implementation-handoff.md`：第一版开发任务书和验收标准。
4. `docs/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
5. `docs/README.md`：文档地图和修改规则。
6. `config/contracts/README.md`：解释 contracts 和 AGENTS 的区别。
7. `config/contracts/*.json`：机器可读契约，写代码时必须遵守。

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
- `docs/development-quickstart.md`：当前工程骨架的本地启动说明。

本地旧 `.env` 已复制到 `config/.env` 以便复用，但不会进入 Git。

当前种子源统计：wiseflow 1 个、RSS 108 个、页面源 4 个，合并索引 113 个。

当前数据库骨架：33 张业务表，覆盖用户/RBAC、数据源、raw/news、去重、推荐、日报/周报、互动反馈、SQL 导出、同步回流和战略需求闭环。任意日报条目应能沿外键追回 `raw_items.raw_payload_json`。

## 当前启动方式

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
DATABASE_URL="" pytest
DATABASE_URL="" uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

更多说明见 `docs/development-quickstart.md`。

Docker 本地启动：

```bash
make up
```

首次构建或改依赖：

```bash
make build
```
