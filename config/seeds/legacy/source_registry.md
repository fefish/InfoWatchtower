# 订阅源清单

这个文件用于人工查看和维护当前项目接入的数据源概况。

真正生效的机器配置文件是：
- `/Users/feiyu/notes/260412 自动同步任务/config/rss_sources.json`
- `/Users/feiyu/notes/260412 自动同步任务/config/page_sources.json`

如果你要新增、停用、修改源，优先改上面两个 JSON；这里作为人工可读清单保留。

## 当前启用的 RSS 源

全部默认 `focus_id = 1`。

1. `OpenAI News`
   - `https://openai.com/news/rss.xml`
2. `Google Cloud AI`
   - `https://cloud.google.com/blog/products/ai-machine-learning/rss/`
3. `Google Research Blog`
   - `https://research.google/blog/rss/`
4. `Google DeepMind Blog`
   - `https://deepmind.google/blog/rss.xml`
5. `AWS ML Blog`
   - `https://aws.amazon.com/blogs/machine-learning/feed/`
6. `NVIDIA Developer AI`
   - `https://developer.nvidia.com/blog/feed/`
7. `Google Blog AI`
   - `https://blog.google/technology/ai/rss/`
8. `Hugging Face Blog`
   - `https://huggingface.co/blog/feed.xml`
9. `Meta Engineering AI`
   - `https://engineering.fb.com/feed/`
10. `LangChain Blog`
    - `https://blog.langchain.com/rss.xml`
11. `Stanford HAI News`
    - `https://hai.stanford.edu/news/rss.xml`
12. `MIT News AI`
    - `https://news.mit.edu/rss/topic/artificial-intelligence2`

## 当前停用的 RSS 源

这些源保留在配置里，但当前没有启用。常见原因包括：
- RSS 地址失效
- 站点返回 `403/404`
- 内容质量不稳定
- 需要后续改成页面抓取而不是 RSS

1. `Anthropic News`
   - `https://www.anthropic.com/news/rss.xml`
2. `Microsoft Azure AI`
   - `https://azure.microsoft.com/en-us/blog/topics/ai-machine-learning/feed/`
3. `Mistral News`
   - `https://mistral.ai/news/rss.xml`
4. `Cohere Blog`
   - `https://cohere.com/blog/rss.xml`
5. `Perplexity Blog`
   - `https://www.perplexity.ai/hub/blog/rss.xml`
6. `Databricks AI`
   - `https://www.databricks.com/blog/category/artificial-intelligence/feed`
7. `LlamaIndex Blog`
   - `https://www.llamaindex.ai/blog/rss.xml`
8. `vLLM Blog`
   - `https://blog.vllm.ai/rss.xml`

## 当前启用的官方页面源

这些源不是标准 RSS，而是通过页面抓取补进来的。

### 1. Anthropic Official Pages
- 类型：`listing`
- 列表页：`https://www.anthropic.com/news`
- 抓取规则：只收 `/news/` 下的文章链接，排除列表页本身
- 最大抓取：`8`

### 2. Mistral Official Pages
- 类型：`listing`
- 列表页：`https://mistral.ai/news`
- 抓取规则：只收 `/news/` 下的文章链接，排除列表页本身
- 最大抓取：`8`

### 3. Qwen Official Pages
- 类型：`manual`
- 当前手工维护文章：
  - `https://qwen.ai/blog?id=qwen3.6-27b`
  - `https://qwen.ai/blog?id=qwen3.6`

### 4. Moonshot/Kimi Official Pages
- 类型：`manual`
- 当前手工维护文章：
  - `https://www.kimi.com/blog/kimi-k2-6`

## 维护建议

1. 如果只是新增普通 RSS，优先改 `config/rss_sources.json`
2. 如果站点没有稳定 RSS，但有新闻列表页，优先改 `config/page_sources.json`
3. 如果站点既没有稳定 RSS，也不好自动抓列表页，就先用 `manual` 方式补文章
4. 每次改完源后，建议重新跑一次：
   - `pipelines/rss_ingest.py`
   - `pipelines/page_ingest.py`
   - `pipelines/prepare_sql_candidates.py`
5. 如果某个源持续产出低质量内容，不要硬留，直接停用或转为更严格过滤
