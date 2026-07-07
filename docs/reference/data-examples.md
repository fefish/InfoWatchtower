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

实现约束：`entry_key` 入库列长为 255。若 RSS/页面源把超长跳转 URL 当作 entry id，系统会将入库 `entry_key` 确定性缩短为“前缀 + hash 后缀”，但 `raw_payload_json.entry_key` 继续保留源侧原值。

Tech Insight Loop 历史素材导入也遵循同一条规则，但它是归档源，不是当前抓取源：

```json
{
  "source_type": "legacy_tech_insight_loop",
  "source_name": "Tech Insight Loop Legacy Archive",
  "entry_key": "legacy_tech_insight_loop:article:123",
  "workspace_code": "legacy_tech_insight_loop",
  "raw_payload_json": {
    "legacy_tech_insight_loop": {
      "id": 123,
      "title": "旧系统文章标题",
      "url": "https://example.com/article",
      "published_at": "2026-05-20T09:00:00+08:00"
    },
    "legacy_import": {
      "company_sql_eligible": false,
      "recommendation_eligible": false,
      "source_system": "tech_insight_loop"
    }
  }
}
```

旧素材进入禁用的 `legacy_tech_insight_loop` 档案源，默认不参与当前推荐、日报生成和标准公司 SQL 导出。

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

实现约束：`dedupe_key` 入库列长为 512。超长 `url:` 或 `title/date` key 会确定性缩短为“前缀 + hash 后缀”；完整 `canonical_url`、`source_url` 和原始 payload 不会被截断。

## 3.1 历史报告归档 historical_reports

Tech Insight Loop 旧 `reports` 不直接写入当前 `daily_reports/weekly_reports`。旧库存在同一天/同周多份报告，直接写入当前唯一键会丢信息，因此先无损进入 `historical_reports`：

```json
{
  "legacy_system": "tech_insight_loop",
  "legacy_table": "reports",
  "legacy_id": 45,
  "workspace_code": "legacy_tech_insight_loop",
  "report_type": "daily",
  "status": "published_imported",
  "period_start_at": "2026-05-20T00:00:00+08:00",
  "period_end_at": "2026-05-20T23:59:59+08:00",
  "title": "技术洞察日报 2026-05-20",
  "source_refs_json": {
    "legacy_source_article_ids": [123, 456, 999],
    "resolved": [
      {"legacy_article_id": 123, "raw_entry_key": "legacy_tech_insight_loop:article:123"},
      {"legacy_article_id": 456, "raw_entry_key": "legacy_tech_insight_loop:article:456"}
    ],
    "unresolved": [999]
  },
  "metadata_json": {
    "legacy_import": {
      "company_sql_eligible": false,
      "recommendation_eligible": false,
      "target": "historical_reports"
    }
  }
}
```

后续如果要按日报/周报方式阅读旧内容，应从 `historical_reports` 做只读查询或投影视图，不把它混成当前日报事实源。

## 3.2 实体大事记归档 tracked_entities / entity_milestones

Tech Insight Loop 旧 `ai_entities/entity_milestones` 进入实体时间线归档，不写 `news_items`，不改当前日报/周报，也不进入标准公司 SQL：

```json
{
  "tracked_entity": {
    "legacy_system": "tech_insight_loop",
    "legacy_table": "ai_entities",
    "legacy_id": "1",
    "workspace_code": "legacy_tech_insight_loop",
    "name": "OpenAI",
    "entity_type": "AI模型厂商",
    "rank": "A",
    "aliases_json": ["GPT", "ChatGPT"],
    "influence_score": 95,
    "metadata_json": {
      "legacy_import": {
        "company_sql_eligible": false,
        "recommendation_eligible": false,
        "target": "tracked_entities"
      }
    }
  },
  "entity_milestone": {
    "legacy_system": "tech_insight_loop",
    "legacy_table": "entity_milestones",
    "legacy_id": "1999",
    "legacy_entity_id": "3",
    "legacy_article_id": "16167",
    "legacy_report_id": null,
    "event_time": "2026-05-17T12:00:00+00:00",
    "event_type": "产品/模型发布",
    "title": "Google 发布 Gemini Omni 模型，强化多模态能力",
    "source_url": "https://example.com/source",
    "board": "AI模型",
    "importance_score": 92,
    "importance_level": "major",
    "metadata_json": {
      "legacy_refs": {
        "raw_item_id": "resolved raw item id when articles have been imported",
        "historical_report_id": null,
        "article_ref_resolved": true,
        "report_ref_resolved": null
      },
      "legacy_import": {
        "company_sql_eligible": false,
        "recommendation_eligible": false,
        "target": "entity_milestones"
      }
    }
  }
}
```

如果历史素材/报告还没有先导入，实体事件仍可保留旧 `article_id/report_id`，并在 `metadata_json.legacy_refs` 记录未解析状态；后续重跑实体导入可幂等补齐新库引用。

## 3.3 历史反馈和旧任务归档

Tech Insight Loop 旧 `feedback/article_quality_feedback/jobs` 只作为历史质量参考，不写当前 `comments/ratings/ingestion_runs`：

```json
{
  "historical_feedback_item": {
    "legacy_system": "tech_insight_loop",
    "legacy_table": "article_quality_feedback",
    "legacy_id": "601",
    "workspace_code": "legacy_tech_insight_loop",
    "legacy_article_id": "16167",
    "raw_item_id": "resolved raw item id when articles have been imported",
    "feedback_kind": "quality_feedback",
    "user_name": "试点用户",
    "feedback_type": "无价值",
    "reason": "和我们无关",
    "comment": "泛商业",
    "feedback_at": "2026-05-30T09:00:00+08:00",
    "metadata_json": {
      "legacy_refs": {
        "article_id": "16167",
        "article_identity": "legacy article_id when available",
        "raw_item_id": "resolved raw item id when articles have been imported",
        "article_ref_resolved": true
      },
      "legacy_import": {
        "company_sql_eligible": false,
        "recommendation_eligible": false,
        "mutates_current_feedback": false,
        "target": "historical_feedback_items"
      }
    }
  },
  "historical_job_run": {
    "legacy_system": "tech_insight_loop",
    "legacy_table": "jobs",
    "legacy_id": "701",
    "workspace_code": "legacy_tech_insight_loop",
    "job_type": "rss_ingest",
    "status": "finished_with_errors",
    "message": "inserted=24, failed=1",
    "total_sources": 25,
    "processed_sources": 25,
    "inserted_count": 24,
    "failed_count": 1,
    "details_json": {
      "failed_source": "Example",
      "error": "timeout"
    },
    "metadata_json": {
      "legacy_import": {
        "statistics_only": true,
        "migrates_old_task_state_machine": false,
        "target": "historical_job_runs"
      }
    }
  }
}
```

旧反馈如果无法解析到历史素材，仍保留归档记录，并在 `metadata_json.legacy_refs.article_ref_resolved=false` 中暴露缺口；导入验收面板会展示这类未解析反馈素材引用。

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
  "admission_level": "P1",
  "admission_score": 78.4,
  "admission_pool": "core_ai_infra",
  "noise_types_json": ["marketing"],
  "reject_reasons_json": [],
  "scorer_breakdown_json": {
    "mode": "content_scorer_v2",
    "config_version": "v3-enhanced-no-new-boards",
    "source_tier_score": 8,
    "source_channel_score": 6,
    "topic_score": 36,
    "noise_penalty": -4
  },
  "expert_routes_json": ["AI Infra", "推理加速"],
  "rank": 3
}
```

早期没有用户反馈时，`feedback_score` 和 `heat_score` 可以为 0。上线后会由点赞、评论、评分、采信行为反哺。

`planning_intel` 当前默认使用技术情报优先策略：`paper_rss`、研究机构、AI 软件、AI 基础设施、模型工程、推理/训练、RAG、多智能体、Agent 记忆和工程实践会加分；融资、财报、股价、市值、消费硬件、泛商业合作等新闻默认降权。商业信号仍可保留在候选池，但不应挤占每日 10 条左右的技术日报名额。

Tech Insight Loop 第一轮融合后，`ContentScorer` 会读取 `config/scoring/content_scorer_v2.json`，结合源侧 `metadata_json` 中的源等级、渠道类型、专家路由、板块相关度和评分拆解，输出结构化准入字段。`recommendation_reason` 仍保留给人工阅读，结构化字段用于前端筛选、运行解释和后续质量治理；这些字段不进入公司 SQL，也不改变 `generated_news.content_json` 五段结构。

## 6. 模型生成稿 generated_news

生成前会读取工作台策略。规划部默认：

```json
{
  "workspace_code": "planning_intel",
  "label_set_code": "ai_sql_categories",
  "news_format_code": "company_sql_v1",
  "export_category_mode": "news_primary",
  "allowed_primary_categories": [
    "AI Infra",
    "AI 应用",
    "测评技术",
    "大厂动态",
    "模型",
    "算法",
    "推理加速",
    "训练技术",
    "智能体",
    "基础竞争力"
  ],
  "required_content_fields": [
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact"
  ]
}
```

`company_sql_v1` 的字段不能随意删除，否则后续阶段 6 无法稳定导出公司内网 SQL。

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

注意：`adoption_status = 2` 只是表示它已进入日报草稿的采信集合；标准 SQL 导出仍然要求日报本身 `status = published`，并且对应 `generated_news.generation_status = ready`、`generated_by` 不能是 `rule_v1`。规则 fallback 草稿只用于人工复核，不直接导出。

所以仍能追溯回模型原稿和原始数据。

日报条目编辑层可以覆盖导出的 `title`、`summary`、`key_points` 和五段正文。导出时的优先级是：

```text
daily_report_items.editor_* > generated_news.*
```

但公司 SQL 的 `content_json` 仍然只导出旧系统五段正文，不导出 InfoWatchtower 自己的追溯字段：

```json
{
  "background": "背景",
  "effects": "效果总结",
  "eventSummary": "事件总结",
  "technologyAndInnovation": "技术和创新点总结",
  "valueAndImpact": "价值和影响"
}
```

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

-- ai_journal.content 使用导出前清洗后的纯文本；原始 HTML 仍保留在 raw_items，不写入公司 SQL。

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

导出后必须运行：

```bash
python3 scripts/validate_company_sql.py outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql
```

该脚本以 2026-05-05 预览为字段基准，校验 4 表顺序、列名、每个字段值、日期、URL 串联、五段正文 JSON 和禁用写法。需要统一标题时先运行：

```bash
python3 scripts/validate_company_sql.py --fix-headers
```
