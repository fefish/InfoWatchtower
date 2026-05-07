# 旧系统关键规格总结

本文档把旧参考资料里对新项目实现有约束意义的信息整理成历史兼容清单，尤其是内网 SQL、旧新闻结构和一级标签。新系统实现以 `docs/00-system-design.md` 和 `config/contracts/*.json` 为准；当旧候选层字段和新业务模型冲突时，保留旧事实用于迁移和校验，不直接照搬旧表设计。

参考来源：

- `references/legacy-auto-sync-20260412/docs/legacy_pipeline_notes.md`
- `references/legacy-auto-sync-20260412/pipelines/generate_ai_sql.py`
- `references/legacy-auto-sync-20260412/pipelines/prepare_sql_candidates.py`
- `references/legacy-auto-sync-20260412/apps/local_hub/README.md`
- `references/legacy-auto-sync-20260412/outputs/sql/`
- `references/legacy-auto-sync-20260412/outputs/deliverables/`

## 1. 旧主链路

旧系统已经跑通的主链路是：

1. wiseflow 本地接口提供原始新闻。
2. `sync_to_remote.py` 使用 `POST /read_info` 分页拉取原始新闻，并同步到远端镜像。
3. `rss_ingest.py` 抓 RSS。
4. `page_ingest.py` 抓没有稳定 RSS 的官方页面。
5. RSS/page 统一写入 `rss_raw.sqlite3`。
6. `prepare_sql_candidates.py` 合并 wiseflow + RSS + page，做保守去重和推荐判断。
7. `generate_ai_sql.py` 读取候选层，抽取 `source_url` 正文，调用模型生成结构化新闻。
8. 标准导出时，只把进入日报推荐的新闻写成 4 条公司内网可导入 SQL。
9. 用户手动把 SQL 文件导入内网数据库。

重要约束：

- 全量同步不能使用 `list_info`，因为旧 wiseflow 的 `/list_info` 每个 focus 最多只返回 12 条；必须走 `POST /read_info`。
- SQL 生成不再做日期重分配，`created_at` 保留原始抓取时间。
- 日报/周报时间口径按北京时间 `Asia/Shanghai` 生成 day/week key，避免 UTC 跨天。
- SQL 生成默认基于 `source_url` 抽正文，不默认 web search。

## 2. 候选层规则

候选层核心表 `candidates`：

```sql
CREATE TABLE candidates (
  candidate_key TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_title TEXT NOT NULL,
  content TEXT NOT NULL,
  created TEXT NOT NULL,
  focus_id INTEGER NOT NULL,
  adoption_status INTEGER NOT NULL,
  recommendation_reason TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  duplicate_of TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  raw_json TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  prepared_at TEXT NOT NULL
);
```

旧规则含义：

- `active = 1`：去重后的 winner。
- `active = 0`：重复项或 loser。
- `adoption_status = 2`：日报推荐/采信状态；标准内网 SQL 导出只导出这类日报条目。
- `adoption_status = 0`：保留但不推荐。
- `duplicate_of`：重复项指向代表项。
- `recommendation_reason`：推荐或降权原因，必须保留可解释性。

旧系统在 2026-04-23 之后的候选层采用“全量去重 + 推荐截断”：

- 去重后的所有 winner 都保留。
- 每天最多 15 条 winner 标为 `adoption_status = 2`。
- 其他 winner 不删除，只降为 `adoption_status = 0`。
- 同一天同一来源最多 2 条推荐，按 URL host 优先计算。

新系统要把“候选保留”和“日报导出”分开：候选层可以保留未推荐 winner，但公司内网 SQL 标准导出从已发布日报条目出发，只导出推荐到日报里的新闻。

## 3. 新闻生成 JSON 格式

旧模型生成的完整新闻对象必须包含这些顶层字段：

```json
{
  "category": "AI Infra",
  "content": {
    "background": "...",
    "effects": "...",
    "eventSummary": "...",
    "technologyAndInnovation": "...",
    "valueAndImpact": "..."
  },
  "keyPoints": "关键词1, 关键词2, 关键词3, 关键词4",
  "sourceUrl": "https://example.com/news",
  "summary": "高度凝练的2-3句话核心洞察",
  "title": "适合资讯站展示的标题"
}
```

字段要求：

- `category`：必须属于一级标签列表。
- `content.background`：背景，旧 prompt 要求不少于 120 字。
- `content.effects`：效果总结，旧 prompt 要求不少于 150 字。
- `content.eventSummary`：事件总结，旧 prompt 要求不少于 120 字。
- `content.technologyAndInnovation`：技术和创新点总结，旧 prompt 要求不少于 220 字。
- `content.valueAndImpact`：价值和影响，旧 prompt 要求不少于 180 字。
- `keyPoints`：4-6 个核心关键词，逗号分隔。
- `sourceUrl`：必须回填真实 `source_url`。
- `summary`：2-3 句话核心洞察。
- `title`：最终展示标题。

旧系统会做容错：

- 如果模型把 `title/summary/keyPoints/sourceUrl/category` 混进 `content`，会提升到顶层。
- 如果 `category` 不合法，标题或内容含 agent/智能体时兜底为 `智能体`，否则兜底为 `AI 应用`。
- `sourceUrl` 和 `created` 最终强制使用原始新闻里的 `source_url` 和 `created`，不信任模型输出。

## 4. 一级标签

旧系统允许的一级标签只有 10 个：

```text
AI Infra
AI 应用
测评技术
大厂动态
模型
算法
推理加速
训练技术
智能体
基础竞争力
```

旧别名归一：

- `AI应用` -> `AI 应用`
- `AI Agent` -> `智能体`
- `AI 智能体` -> `智能体`
- `AI智能体` -> `智能体`

新系统可以扩展标签体系，但内网 SQL 导出必须默认兼容这 10 个一级标签，除非内部平台字段和展示规则明确升级。

## 5. 内网 SQL 固定格式

旧系统每条导出的新闻固定生成 4 条 SQL，顺序不能乱。新系统标准导出范围是日报推荐新闻：

- `daily_reports.status = published`
- `daily_report_items.adoption_status = 2`
- 已有关联 `generated_news`

顺序：

1. `ai_journal`
2. `ai_journal_focus`
3. `ai_journal_analysis`
4. `t_news_data_info`

每条新闻前有注释：

```sql
-- [写入数据 Focus_ID: 1]
```

### 5.1 ai_journal

```sql
INSERT IGNORE INTO ai_journal
  (source_url, source_title, content, created_at)
VALUES
  (:source_url, :source_title, :raw_content, :created_at);
```

字段来源：

- `source_url`：原始新闻 URL。
- `source_title`：原始标题，不是生成后的标题。
- `content`：原始摘要/正文材料。
- `created_at`：原始发布时间，转 MySQL `YYYY-MM-DD HH:MM:SS`；解析失败时为 `NULL`。

### 5.2 ai_journal_focus

```sql
INSERT IGNORE INTO ai_journal_focus
  (journal_id, focus_id)
SELECT id, :focus_id
FROM ai_journal
WHERE source_url = :source_url
LIMIT 1;
```

旧 RSS 源默认 `focus_id = 1`。

### 5.3 ai_journal_analysis

```sql
INSERT INTO ai_journal_analysis
  (journal_id, category, title, summary, key_points, content_json, source_url, created_at)
SELECT
  id,
  :category,
  :title,
  :summary,
  :key_points,
  :content_json,
  :source_url,
  :created_at
FROM ai_journal
WHERE source_url = :source_url
LIMIT 1;
```

字段来源：

- `category`：一级标签。
- `title`：生成后的资讯标题。
- `summary`：生成后的 2-3 句话摘要。
- `key_points`：关键词字符串。
- `content_json`：只存 `analysis.content` 对象的 JSON 字符串，也就是 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact`。
- `source_url`：原始 URL。
- `created_at`：原始发布时间。

### 5.4 t_news_data_info

```sql
INSERT INTO t_news_data_info
  (catalog_id, journal_id, data, adoption_status, category, title, summary, key_points, content_json, source_url)
SELECT
  NULL,
  id,
  NULL,
  :adoption_status,
  :category,
  :title,
  :summary,
  :key_points,
  :content_json,
  :source_url
FROM ai_journal
WHERE source_url = :source_url
LIMIT 1;
```

字段来源：

- `catalog_id`：旧系统固定 `NULL`。
- `journal_id`：从 `ai_journal` 按 `source_url` 查。
- `data`：旧系统固定 `NULL`。
- `adoption_status`：候选层推荐状态，推荐为 `2`，非推荐为 `0`。
- 其余结构化字段与 `ai_journal_analysis` 保持一致。

### 5.5 安全写法原因

旧系统曾遇到 `journal_id cannot be null`。因此现在必须使用：

- `ai_journal` 先 `INSERT IGNORE`。
- 后面三张表用 `INSERT ... SELECT id FROM ai_journal WHERE source_url = ... LIMIT 1`。

这样如果某条 `ai_journal` 因长度或约束失败，只跳过这条新闻的后续写入，不会让整份 SQL 全部中断。

仍然存在的风险：

- 如果内网库 `ai_journal.source_url` 字段过短，超长 URL 可能导致这条新闻整体缺失。
- 新系统 SQL 导出前必须增加字段长度校验和 URL 过长告警。

## 6. 展示库内容字段

旧 local hub 的 `content_items` 表说明了看板展示需要吸收候选层和 SQL 成品两类信息：

```sql
CREATE TABLE content_items (
  source_url TEXT PRIMARY KEY,
  day_key TEXT NOT NULL,
  week_key TEXT NOT NULL,
  created TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_title TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  focus_id INTEGER NOT NULL,
  active INTEGER NOT NULL,
  adoption_status INTEGER NOT NULL,
  recommendation_reason TEXT NOT NULL,
  category TEXT NOT NULL,
  analysis_title TEXT NOT NULL,
  summary TEXT NOT NULL,
  key_points TEXT NOT NULL,
  content_json TEXT NOT NULL,
  duplicate_of TEXT NOT NULL,
  sql_file TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  refreshed_at TEXT NOT NULL
);
```

新系统不一定照搬这个表，但需要覆盖这些业务语义。

## 7. 旧信息源事实

旧 `rss_sources.json`：

- 共 108 个 RSS 源。
- 74 个启用。
- 34 个停用。
- `default_focus_id` 基本为 1。

旧 `page_sources.json`：

- 共 4 个页面源。
- 2 个 listing：Anthropic Official Pages、Mistral Official Pages。
- 2 个 manual：Qwen Official Pages、Moonshot/Kimi Official Pages。

论文源：

- `folo_metadata.info_category = 学术论文` 的 RSS 源共 17 个，其中 14 个启用。
- 典型启用源包括 arXiv `cs.AI/cs.CL/cs.CV/cs.LG/cs.NE/cs.RO`、Amazon Science、Apple Machine Learning Research、IBM Research、Google Research、Nature、Nature Communications、PNAS、Science。
- 旧导入逻辑对 `学术论文` 和 `技术博客` 至少使用 60 天回填窗口。

## 8. 旧环境变量

旧 `.env` 已本地复制，可复用但不入仓。变量名包括：

```text
SOURCE_API_BASE
SOURCE_READ_INFO_URL
INITIAL_SYNC_START_TIME
REMOTE_SYNC_URL
SYNC_API_TOKEN
SYNC_STATE_PATH
SYNC_CHUNK_SIZE
SYNC_LOOKBACK_SECONDS
READ_INFO_PAGE_SIZE
SYNC_SERVER_DB_PATH
RSS_SOURCES_PATH
PAGE_SOURCES_PATH
RSS_RAW_DB_PATH
PAGE_RAW_DB_PATH
SQL_CANDIDATE_DB_PATH
INITIAL_PROCESS_START_TIME
OUTPUT_SQL_BASENAME
OUTPUT_SQL_DIR
PROCESS_STATE_DB
SQL_BATCH_SIZE
PROCESS_LOOKBACK_SECONDS
MODEL_REQUEST_INTERVAL_SECONDS
ARTICLE_TEXT_MAX_CHARS
RAW_CONTENT_MAX_CHARS
MINIMAX_BASE_URL
MINIMAX_ANTHROPIC_BASE_URL
MINIMAX_MODEL
MINIMAX_MAX_TOKENS
MINIMAX_TEMPERATURE
```

注意：文档里只记录变量名，不记录密钥值。旧生成脚本实际读取 `MINIMAX_BASE_URL`，未设置时默认使用中国区 OpenAI-compatible `https://api.minimaxi.com/v1/chat/completions`；旧 `.env` 中残留的 `MINIMAX_ANTHROPIC_BASE_URL` 不参与旧脚本生成调用。真实密钥值只保留在本地被 `.gitignore` 忽略的 `.env` 文件中。
