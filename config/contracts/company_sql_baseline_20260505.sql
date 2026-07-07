-- InfoWatchtower Company SQL Preview
-- 工作台: planning_intel
-- 日期范围: 2026-05-05
-- 生成时间: 2026-05-07 10:30:40
-- 导出规则: 已发布日报；仅 adoption_status = 2；generated_news.generation_status = ready；非 rule_v1 fallback。
-- 表顺序: ai_journal -> ai_journal_focus -> ai_journal_analysis -> t_news_data_info
-- 日期规则: created_at 使用北京时间 'YYYY-MM-DD HH:MM:SS'；缺失发布时间兜底为日报 day_key 09:00:00；禁止 NULL/STR_TO_DATE。
-- 校验基准: outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql
-- 汇总: 1 条新闻，4 条 SQL 语句。
--
-- 本文件是 2026-05-05 legacy 基准的锁列夹具（schema-lock fixture）：只承载四张表的
-- 列顺序契约，供 scripts/validate_company_sql.py 在全新 checkout（无 outputs/ 本地基准）
-- 时回落加载。完整 0505 预览仍在本地 outputs/，两者列顺序必须一致；改列顺序=破坏公司 SQL 合同。

-- ===== 2026-05-05 规划部情报工作台 日报 =====
-- [写入数据 Focus_ID: 1]
INSERT IGNORE INTO ai_journal (source_url, source_title, content, created_at) VALUES ('https://example.com/baseline', '基准样例标题', '基准样例正文。', '2026-05-05 09:00:00');
INSERT IGNORE INTO ai_journal_focus (journal_id, focus_id) SELECT id, 1 FROM ai_journal WHERE source_url = 'https://example.com/baseline';
INSERT INTO ai_journal_analysis (journal_id, category, title, summary, key_points, content_json, source_url, created_at) SELECT id, '算法', '基准样例标题', '基准样例摘要。', '要点一;要点二', '{}', 'https://example.com/baseline', '2026-05-05 09:00:00' FROM ai_journal WHERE source_url = 'https://example.com/baseline';
INSERT INTO t_news_data_info (catalog_id, journal_id, data, adoption_status, category, title, summary, key_points, content_json, source_url) SELECT NULL, id, NULL, 2, '算法', '基准样例标题', '基准样例摘要。', '要点一;要点二', '{}', 'https://example.com/baseline' FROM ai_journal WHERE source_url = 'https://example.com/baseline';
