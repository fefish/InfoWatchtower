# 扩展配方

本文给实现者一个可执行清单：新增工作台、SourceAdapter、成稿格式、导航分区和
domain pack 时，按这里做，不 fork 主链路。

## R1 新建工作台

前置条件：登录用户是 `super_admin` 或 `editor_admin`。

步骤：

1. 前端侧边栏点击“新建工作台”。
2. 填写 `code/name/description/default_domain_code`。
3. 在选源步骤勾选共享源；可填写一个 RSS/paper RSS/page 源，源会进入共享池并链接到新工作台。
4. 在标签策略步骤选择复制规划部十分类、复制 `ai_tools`，或填写空白自定义一级标签。
5. 完成后进入 `/sources` 检查启用源和标签策略。

API 等价路径：

```bash
curl -X POST /api/workspaces
curl -X PATCH /api/sources/{source_id}/workspace-link
curl -X POST /api/sources
curl -X PATCH /api/workspaces/{code}/label-policy
```

验证：

```bash
cd backend && DATABASE_URL="" .venv/bin/python -m pytest tests/test_workspaces_api.py
cd frontend && npm run build
```

## R2 新增 SourceAdapter

前置条件：新来源能输出 `RawItemInput` 的最小字段。

步骤：

1. 在 `backend/app/adapters/` 新增 adapter，实现 `source_type` 和 `async fetch(data_source)`。
2. 输出 `RawItemInput(entry_key/source_title/source_url/raw_content/raw_payload_json/published_at/source_specific_json)`。
3. 在 `backend/app/adapters/__init__.py:create_default_registry()` 注册。
4. 在 `config/contracts/adapter_pipeline.json` 记录 source_type、必填字段和不可覆盖 `raw_payload_json` 的约束。
5. 写契约测试，至少证明 adapter 可注册、可 fetch、返回 JSON-safe payload。

仓库已保留 `dummy` 配方证明：`backend/tests/test_adapters.py::test_dummy_adapter_recipe_contract_example`。

验证：

```bash
cd backend && DATABASE_URL="" .venv/bin/python -m pytest tests/test_adapters.py
```

## R3 新增成稿格式

前置条件：格式只是 report item 的投影，不复制 raw/news/generated_news。

步骤：

1. 非 locked 格式优先在界面注册：`/api/report-formats?workspace_code={code}`。
2. 如需内置格式，更新 `app/reports/renditions.py` 和 `config/contracts/report_renditions.json`。
3. 确保 `company_sql_v1` locked，不被自定义格式覆盖。
4. 生成日报/周报 rendition，导出 MD/HTML。

验证：

```bash
cd backend && DATABASE_URL="" .venv/bin/python -m pytest tests/test_report_renditions.py
cd frontend && npm run build
```

## R4 新增导航分区

前置条件：新增页面是加法模块，不改变数据源、候选池、日报、周报、导出主链路。

步骤：

1. 在 seed 或迁移中写 `workspace_sections`，默认按目标工作台显式启用。
2. `config_json.group` 使用 `today/collect/curate/library/collab/system` 之一。
3. 前端路由新增页面，并在 `AppShell.vue` 的 `sectionIcons` 增加图标映射。
4. 页面权限按 workspace membership 校验。

验证：

```bash
cd backend && DATABASE_URL="" .venv/bin/python -m pytest tests/test_auth.py tests/test_workspaces_api.py
cd frontend && npm run build
```

## R5 新增 Domain Pack

前置条件：新增板块是主题域，不是新工作台；工作台仍走 `workspaces`。

步骤：

1. 新增 `config/domain_packs/{domain_code}.json`。
2. 至少包含 `domain_code`、`boards`、`label_sets`、`scoring.prior_keywords`。
3. 启动 seed 会读取 flat JSON 并注册 `label_sets/labels`。
4. 工作台向导中可把 `default_domain_code` 填成该 `domain_code`，再选择空白或复制策略。

验证：

```bash
cd backend && DATABASE_URL="" .venv/bin/python -m pytest tests/test_auth.py
```

当前样例：`config/domain_packs/hardware.json` 注册 `hardware_categories`，并把板块和评分先验保存在
`label_sets.config_json`。
