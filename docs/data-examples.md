# 数据流样例

本文档用简化样例说明：RSS 源拿到的数据长什么样，进入 InfoWatchtower 后如何变成统一新闻，最后如何进入日报和公司 SQL。

## 1. RSS 源拿到的原始数据

RSS adapter 从 feed 里拿到的单条 entry 通常类似这样：

```json
{
  "source_name": "OpenAI News",
  "feed_url": "https://openai.com/news/rss.xml",
  "entry_key": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "title": "Introducing workspace agents in ChatGPT",
  "link": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "canonical_link": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "author": "",
  "summary": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "content": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "created": "2026-04-22T10:00:00Z",
  "focus_id": 1,
  "raw_json": {
    "feedparser_entry": "完整原始 entry 放这里，字段按源保留"
  }
}
```

不同 RSS 源字段可能不一样，有的叫 `guid`，有的叫 `id`，有的只有 `summary` 没有 `content`。adapter 的职责就是把这些差异收进统一 raw 结构。

## 2. 进入 raw_items

`raw_items` 是“关键字段列化 + 原始 payload JSONB 完整保留”。

```json
{
  "id": "raw_001",
  "data_source_id": "src_openai_news",
  "domain_code": "ai",
  "visibility_scope": "public",
  "sync_policy": "public_to_intranet",
  "source_type": "rss",
  "source_name": "OpenAI News",
  "entry_key": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "source_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "canonical_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "source_title": "Introducing workspace agents in ChatGPT",
  "raw_summary": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "raw_content": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "published_at": "2026-04-22T10:00:00Z",
  "fetched_at": "2026-05-03T10:00:00Z",
  "raw_payload_json": {
    "source_name": "OpenAI News",
    "feed_url": "https://openai.com/news/rss.xml",
    "entry_key": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
    "title": "Introducing workspace agents in ChatGPT",
    "link": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
    "summary": "Workspace agents in ChatGPT are Codex-powered agents..."
  },
  "source_specific_json": {
    "rss_author": "",
    "rss_tags": []
  },
  "extract_status": "pending"
}
```

这里不删原始字段。将来如果要排查、重跑、改 adapter，都能看 `raw_payload_json`。

## 3. 标准化成 news_items

`news_items` 是统一标准化新闻。不同源都会变成这个结构后再去重，去重 winner 进入候选池，再进入推荐和日报/周报采信。

```json
{
  "id": "news_001",
  "workspace_code": "planning_intel",
  "raw_item_id": "raw_001",
  "domain_code": "ai",
  "visibility_scope": "public",
  "sync_policy": "public_to_intranet",
  "source_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "canonical_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "source_title": "Introducing workspace agents in ChatGPT",
  "normalized_title": "introducing workspace agents in chatgpt",
  "summary": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "content": "Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...",
  "published_at": "2026-04-22T10:00:00Z",
  "focus_id": 1,
  "source_type": "rss",
  "source_name": "OpenAI News",
  "dedupe_key": "url:https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "duplicate_of_id": null,
  "active": true,
  "normalization_status": "normalized"
}
```

如果没有 URL，`dedupe_key` 会退化成：

```text
title:introducing workspace agents in chatgpt|date:2026-04-22
```

## 4. 去重结果

假设另一个页面源也抓到了同一 URL：

```json
{
  "id": "news_002",
  "workspace_code": "planning_intel",
  "source_type": "page_monitor",
  "source_name": "OpenAI Official Pages",
  "canonical_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "dedupe_key": "url:https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "active": false,
  "duplicate_of_id": "news_001"
}
```

去重组：

```json
{
  "dedupe_group": {
    "id": "dedupe_001",
    "workspace_code": "planning_intel",
    "dedupe_key": "url:https://openai.com/index/introducing-workspace-agents-in-chatgpt",
    "winner_news_item_id": "news_001",
    "item_count": 2,
    "status": "active"
  },
  "items": [
    {"news_item_id": "news_001", "is_winner": true, "duplicate_reason": "winner"},
    {"news_item_id": "news_002", "is_winner": false, "duplicate_reason": "same canonical URL"}
  ]
}
```

原始 `raw_items` 都保留，不物理删除。

阶段 4 可用这些接口验收：

```text
POST /api/news-items/normalize
GET  /api/news-items?workspace_code=planning_intel
GET  /api/dedupe-groups?workspace_code=planning_intel
```

## 5. 推荐评分

推荐只对 `active = true` 的 winner 做。

```json
{
  "id": "rec_item_001",
  "recommendation_run_id": "rec_run_2026_04_22",
  "news_item_id": "news_001",
  "dedupe_group_id": "dedupe_001",
  "quality_score": 82,
  "topic_score": 88,
  "freshness_score": 76,
  "feedback_score": 0,
  "diversity_score": 4,
  "source_score": 90,
  "heat_score": 0,
  "final_score": 82.1,
  "recommended": true,
  "recommendation_reason": "official_source; agent_topic; trusted_domain=openai.com",
  "rank": 3
}
```

早期没有用户反馈时，`feedback_score` 和 `heat_score` 可以为 0。上线后会由点赞、评论、评分、采信行为反哺。

## 6. 模型生成稿 generated_news

模型基于原始标题、原始摘要、原始 URL、抽取正文生成结构化稿。

```json
{
  "id": "gen_001",
  "news_item_id": "news_001",
  "category": "智能体",
  "title": "OpenAI 推出 ChatGPT 工作区智能体：Codex 驱动复杂工作流自动化",
  "summary": "OpenAI 的 workspace agents 将 Codex 能力引入 ChatGPT 工作区，面向团队自动执行跨工具复杂任务。这一变化意味着 ChatGPT 正从对话界面扩展为可运行长流程任务的协作平台。",
  "key_points": "workspace agents, Codex, 工作流自动化, 团队协作, 云端执行",
  "content_json": {
    "background": "随着企业用户把 ChatGPT 用于更多工作场景，单轮问答已经难以覆盖复杂协作需求...",
    "effects": "工作区智能体会改变团队使用 AI 的方式...",
    "eventSummary": "OpenAI 发布 workspace agents...",
    "technologyAndInnovation": "该能力以 Codex-powered agents 为核心...",
    "valueAndImpact": "对企业用户而言，这类智能体降低了跨工具自动化门槛..."
  },
  "source_url": "https://openai.com/index/introducing-workspace-agents-in-chatgpt",
  "created_at": "2026-04-22T10:00:00Z"
}
```

## 7. 进入日报 daily_report_items

管理员采信后，日报条目这样存：

```json
{
  "id": "daily_item_001",
  "daily_report_id": "daily_2026_04_22",
  "news_item_id": "news_001",
  "generated_news_id": "gen_001",
  "recommendation_item_id": "rec_item_001",
  "position": 1,
  "adoption_status": 2,
  "editor_title": null,
  "editor_summary": null,
  "editor_content_json": null,
  "locked": false
}
```

如果管理员改了标题，不改 `generated_news` 原稿，而是在日报条目里覆盖：

```json
{
  "editor_title": "ChatGPT 工作区智能体发布：从对话助手走向团队任务执行平台"
}
```

阶段 5 当前会在推荐 run 中为 selected 项自动创建 `generated_news` 和日报草稿条目。草稿条目默认：

```json
{
  "adoption_status": 2,
  "sort_order": 1,
  "editor_title": null,
  "editor_summary": null
}
```

注意：`adoption_status = 2` 只是表示它已进入日报草稿的采信集合；标准 SQL 导出仍然要求日报本身 `status = published`。

所以仍能追溯回模型原稿和原始数据。

## 8. 公司 SQL 导出

标准导出只取：

```text
daily_reports.status = published
daily_report_items.adoption_status = 2
```

一条日报新闻导出 4 条 SQL：

```sql
INSERT IGNORE INTO ai_journal (source_url, source_title, content, created_at)
VALUES ('https://openai.com/index/introducing-workspace-agents-in-chatgpt',
        'Introducing workspace agents in ChatGPT',
        'Workspace agents in ChatGPT are Codex-powered agents that automate complex workflows...',
        '2026-04-22 10:00:00');

INSERT IGNORE INTO ai_journal_focus (journal_id, focus_id)
SELECT id, 1 FROM ai_journal
WHERE source_url = 'https://openai.com/index/introducing-workspace-agents-in-chatgpt'
LIMIT 1;

INSERT INTO ai_journal_analysis
  (journal_id, category, title, summary, key_points, content_json, source_url, created_at)
SELECT id, '智能体',
       'OpenAI 推出 ChatGPT 工作区智能体：Codex 驱动复杂工作流自动化',
       'OpenAI 的 workspace agents 将 Codex 能力引入 ChatGPT 工作区...',
       'workspace agents, Codex, 工作流自动化, 团队协作, 云端执行',
       '{"background":"...","effects":"...","eventSummary":"...","technologyAndInnovation":"...","valueAndImpact":"..."}',
       'https://openai.com/index/introducing-workspace-agents-in-chatgpt',
       '2026-04-22 10:00:00'
FROM ai_journal
WHERE source_url = 'https://openai.com/index/introducing-workspace-agents-in-chatgpt'
LIMIT 1;

INSERT INTO t_news_data_info
  (catalog_id, journal_id, data, adoption_status, category, title, summary, key_points, content_json, source_url)
SELECT NULL, id, NULL, 2, '智能体',
       'OpenAI 推出 ChatGPT 工作区智能体：Codex 驱动复杂工作流自动化',
       'OpenAI 的 workspace agents 将 Codex 能力引入 ChatGPT 工作区...',
       'workspace agents, Codex, 工作流自动化, 团队协作, 云端执行',
       '{"background":"...","effects":"...","eventSummary":"...","technologyAndInnovation":"...","valueAndImpact":"..."}',
       'https://openai.com/index/introducing-workspace-agents-in-chatgpt'
FROM ai_journal
WHERE source_url = 'https://openai.com/index/introducing-workspace-agents-in-chatgpt'
LIMIT 1;
```
