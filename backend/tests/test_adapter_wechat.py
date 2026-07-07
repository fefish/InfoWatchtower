import json
from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.wechat import WeChatMpAdapter, _canonical_article_url
from app.models.content import DataSource

# RSSHub 风格公众号 feed（自建实例 /wechat/* 路由的典型输出）。
FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>机智流</title>
  <link>https://mp.weixin.qq.com/</link>
  <description>机智流 - Made with love by RSSHub</description>
  <item>
    <title>Agent 记忆系统综述</title>
    <link>https://mp.weixin.qq.com/s/FeedItem001</link>
    <guid isPermaLink="false">https://mp.weixin.qq.com/s/FeedItem001</guid>
    <pubDate>Mon, 06 Jul 2026 10:00:00 GMT</pubDate>
    <description><![CDATA[<p>正文摘要一。</p>]]></description>
  </item>
  <item>
    <title>顶会论文速递</title>
    <link>https://mp.weixin.qq.com/s/FeedItem002</link>
    <guid isPermaLink="false">https://mp.weixin.qq.com/s/FeedItem002</guid>
    <pubDate>Sun, 05 Jul 2026 09:00:00 GMT</pubDate>
    <description><![CDATA[<p>正文摘要二。</p>]]></description>
  </item>
</channel>
</rss>
"""

# 渲染后的 mp 文章页结构（wiseflow WeixinArticleMarkdownGenerator 解析目标同款：
# og meta / h1#activity-name / a#js_name / em#publish_time / div#js_content）。
ARTICLE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta property="og:title" content="大模型推理优化实践" />
<meta property="og:description" content="一文看懂 KV Cache 与投机解码。" />
<meta property="og:article:author" content="机智流" />
<meta property="og:url" content="https://mp.weixin.qq.com/s/AbCdEfGh123" />
<meta name="description" content="一文看懂 KV Cache 与投机解码。" />
<title>大模型推理优化实践</title>
</head>
<body>
<div class="rich_media_wrp">
<h1 class="rich_media_title" id="activity-name">
    大模型推理优化实践
</h1>
<div id="meta_content" class="rich_media_meta_list">
  <span class="rich_media_meta rich_media_meta_text">原创</span>
  <span class="rich_media_meta rich_media_meta_nickname" id="profileBt">
    <a href="javascript:void(0);" id="js_name">机智流</a>
  </span>
  <em id="publish_time" class="rich_media_meta rich_media_meta_text">2026年7月1日 08:30</em>
</div>
<div class="rich_media_content" id="js_content" style="visibility: hidden;">
  <p>KV Cache 是推理加速的第一性优化。</p>
  <div><p>投机解码可以再降一半时延。</p></div>
  <script type="text/javascript">var leaked = "script text must not leak";</script>
</div>
<script>var ct = "1751330000";</script>
</div>
</body>
</html>
"""

# 未渲染的 mp 文章页：em#publish_time 为空，发布时间只在脚本变量 var ct 中。
RAW_ARTICLE_HTML = """<html>
<head>
<meta property="og:title" content="液冷数据中心拆解" />
<meta property="og:description" content="液冷 TCO 拆解。" />
</head>
<body>
<h1 class="rich_media_title" id="activity-name">液冷数据中心拆解</h1>
<a href="javascript:void(0);" id="js_name">新智元</a>
<em id="publish_time" class="rich_media_meta rich_media_meta_text"></em>
<div id="js_content"><p>浸没式与冷板式的成本曲线不同。</p></div>
<script>var ct = "1751328000";</script>
</body>
</html>
"""

# 图片分享页：无 js_content，正文回落 js_image_desc，账号名回落 js_wx_follow_nickname。
PHOTO_SHARE_HTML = """<html>
<head><meta property="og:description" content="分享图集" /></head>
<body>
<span id="js_wx_follow_nickname">量子位</span>
<div id="js_image_desc">GTC 现场实拍：新一代推理芯片首秀。</div>
</body>
</html>
"""

ALBUM_HTML = """<html>
<body>
<ul>
<li class="album__list-item js_album_item"
    data-title="合集第一篇"
    data-link="http://mp.weixin.qq.com/s?__biz=MzA1&amp;mid=101&amp;idx=1&amp;sn=aaa&amp;chksm=x1#rd"></li>
<li class="album__list-item js_album_item"
    data-title="合集第二篇"
    data-link="https://mp.weixin.qq.com/s?__biz=MzA1&amp;mid=102&amp;idx=1&amp;sn=bbb&amp;chksm=x2#rd"></li>
</ul>
</body>
</html>
"""

VERIFICATION_HTML = """<html>
<body>
<div class="weui-msg">
  <p>当前环境异常，完成验证后即可继续访问。</p>
  <button>去验证</button>
</div>
</body>
</html>
"""


def make_source(
    fetch_config: dict,
    url: str | None = None,
    credential_ref: str | None = None,
) -> DataSource:
    return DataSource(
        source_type="wechat",
        name="公众号源",
        url=url,
        fetch_config=fetch_config,
        credential_ref=credential_ref,
    )


def routing_transport(routes: dict[str, str], calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        for prefix, body in routes.items():
            if url.startswith(prefix):
                return httpx.Response(200, text=body)
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_wechat_rsshub_route_with_instance_base_reuses_rss_parsing():
    calls: list[str] = []
    adapter = WeChatMpAdapter(
        transport=routing_transport({"http://rsshub.internal:1200/": FEED_XML}, calls),
    )
    items = await adapter.fetch(
        make_source(
            {
                "rsshub_route": "wechat/mp/gh_6b5001ccae4b",
                "rsshub_base": "http://rsshub.internal:1200",
                "account_name": "机智流",
                "account_username": "gh_6b5001ccae4b",
            },
        ),
    )

    assert calls == ["http://rsshub.internal:1200/wechat/mp/gh_6b5001ccae4b"]
    assert len(items) == 2
    first = items[0]
    assert first.entry_key == "https://mp.weixin.qq.com/s/FeedItem001"
    assert first.source_title == "Agent 记忆系统综述"
    assert first.source_url == "https://mp.weixin.qq.com/s/FeedItem001"
    assert first.raw_content == "<p>正文摘要一。</p>"
    assert first.published_at == datetime(2026, 7, 6, 10, tzinfo=UTC)
    # 复用 rss.py 解析：raw_payload_json 是完整 feed entry
    assert first.raw_payload_json["title"] == "Agent 记忆系统综述"
    assert first.source_specific_json["wechat_mode"] == "rsshub"
    assert first.source_specific_json["account_name"] == "机智流"
    assert first.source_specific_json["account_username"] == "gh_6b5001ccae4b"
    assert first.source_specific_json["rsshub_route"] == "/wechat/mp/gh_6b5001ccae4b"


@pytest.mark.asyncio
async def test_wechat_rsshub_base_env_indirection(monkeypatch):
    monkeypatch.setenv("WECHAT_RSSHUB_BASE", "http://rsshub.lan:1200/")
    calls: list[str] = []
    adapter = WeChatMpAdapter(
        transport=routing_transport({"http://rsshub.lan:1200/": FEED_XML}, calls),
    )
    items = await adapter.fetch(
        make_source({"rsshub_route": "/wechat/mp/gh_x", "rsshub_base_env": "WECHAT_RSSHUB_BASE"}),
    )

    assert calls == ["http://rsshub.lan:1200/wechat/mp/gh_x"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_wechat_account_only_derives_route_and_uses_global_rsshub_base(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("RSSHUB_BASE_URL", "https://rsshub.internal.example:1200")
    get_settings.cache_clear()
    calls: list[str] = []
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://rsshub.internal.example:1200/": FEED_XML}, calls),
    )
    try:
        items = await adapter.fetch(make_source({"account_username": "gh_6b5001ccae4b"}))
    finally:
        monkeypatch.delenv("RSSHUB_BASE_URL", raising=False)
        get_settings.cache_clear()

    assert calls == ["https://rsshub.internal.example:1200/wechat/mp/gh_6b5001ccae4b"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_wechat_route_without_any_base_falls_back_to_public_rsshub(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.delenv("RSSHUB_BASE_URL", raising=False)
    get_settings.cache_clear()
    calls: list[str] = []
    adapter = WeChatMpAdapter(transport=routing_transport({"https://rsshub.app/": FEED_XML}, calls))
    items = await adapter.fetch(make_source({"rsshub_route": "/wechat/mp/gh_x"}))

    assert calls == ["https://rsshub.app/wechat/mp/gh_x"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_wechat_credential_ref_adds_bearer_header_for_private_bridge(monkeypatch):
    """自建 RSSHub/微信转 RSS 桥的 Bearer 认证：credential_ref → auth_token_env → auth_token。"""
    monkeypatch.setenv("WX_BRIDGE_TOKEN", "bridge-token")
    headers_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        return httpx.Response(200, text=FEED_XML)

    adapter = WeChatMpAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source(
            {
                "feed_url": "https://wx-bridge.lan/feeds/gh_x.xml",
                "auth_token": "inline-token",
            },
            credential_ref="env:WX_BRIDGE_TOKEN",
        ),
    )

    assert len(items) == 2
    assert headers_seen[0]["authorization"] == "Bearer bridge-token"


@pytest.mark.asyncio
async def test_wechat_without_credentials_sends_no_authorization_header():
    headers_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        return httpx.Response(200, text=FEED_XML)

    adapter = WeChatMpAdapter(transport=httpx.MockTransport(handler))
    await adapter.fetch(make_source({"feed_url": "https://wx-bridge.lan/feeds/gh_x.xml"}))

    assert "authorization" not in headers_seen[0]


@pytest.mark.asyncio
async def test_wechat_feed_url_takes_priority_and_max_items_caps_entries():
    calls: list[str] = []
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://wx-bridge.lan/feeds/gh_x.xml": FEED_XML}, calls),
    )
    items = await adapter.fetch(
        make_source(
            {
                "feed_url": "https://wx-bridge.lan/feeds/gh_x.xml",
                "rsshub_route": "/wechat/mp/gh_x",
                "max_items": 1,
            },
        ),
    )

    assert calls == ["https://wx-bridge.lan/feeds/gh_x.xml"]
    assert len(items) == 1
    assert items[0].entry_key == "https://mp.weixin.qq.com/s/FeedItem001"


@pytest.mark.asyncio
async def test_wechat_article_urls_parses_mp_article_structure():
    calls: list[str] = []
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://mp.weixin.qq.com/s": ARTICLE_HTML}, calls),
    )
    messy_url = "https://mp.weixin.qq.com/s?__biz=MzA1&mid=2247&idx=1&sn=abcd&chksm=fe11aa#rd"
    items = await adapter.fetch(
        make_source({"article_urls": [messy_url], "account_username": "gh_6b5001ccae4b"}),
    )

    assert len(items) == 1
    item = items[0]
    # og:url 规整为稳定 entry_key，chksm 分享参数不进 key
    assert item.entry_key == "https://mp.weixin.qq.com/s/AbCdEfGh123"
    assert item.source_url == "https://mp.weixin.qq.com/s/AbCdEfGh123"
    assert item.source_title == "大模型推理优化实践"
    # 2026年7月1日 08:30（北京时间）→ UTC
    assert item.published_at == datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
    assert "KV Cache 是推理加速的第一性优化。" in item.raw_content
    assert "投机解码可以再降一半时延。" in item.raw_content
    assert "script text must not leak" not in item.raw_content

    payload = item.raw_payload_json
    assert payload["url"] == messy_url
    assert payload["canonical_url"] == "https://mp.weixin.qq.com/s/AbCdEfGh123"
    assert payload["title"] == "大模型推理优化实践"
    assert payload["h1_title"] == "大模型推理优化实践"
    assert payload["account_name"] == "机智流"
    assert payload["author"] == "机智流"
    assert payload["publish_time_text"] == "2026年7月1日 08:30"
    assert payload["meta"]["og:title"] == "大模型推理优化实践"
    assert payload["meta"]["og:description"] == "一文看懂 KV Cache 与投机解码。"
    assert "<p>KV Cache 是推理加速的第一性优化。</p>" in payload["content_html"]
    assert payload["description"] == "一文看懂 KV Cache 与投机解码。"
    # json 可序列化（raw_payload_json 不覆盖原则的前置要求）
    json.dumps(payload)

    assert item.source_specific_json["wechat_mode"] == "article_urls"
    assert item.source_specific_json["account_name"] == "机智流"
    assert item.source_specific_json["account_username"] == "gh_6b5001ccae4b"


@pytest.mark.asyncio
async def test_wechat_article_uses_ct_epoch_when_publish_time_not_rendered():
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://mp.weixin.qq.com/s/RawPage01": RAW_ARTICLE_HTML}, []),
    )
    items = await adapter.fetch(
        make_source({"article_urls": ["https://mp.weixin.qq.com/s/RawPage01"]}),
    )

    assert len(items) == 1
    assert items[0].published_at == datetime.fromtimestamp(1751328000, tz=UTC)
    assert items[0].source_title == "液冷数据中心拆解"
    assert items[0].raw_payload_json["account_name"] == "新智元"
    # og:url 缺失时回落请求 URL 本身
    assert items[0].entry_key == "https://mp.weixin.qq.com/s/RawPage01"


@pytest.mark.asyncio
async def test_wechat_photo_share_page_falls_back_to_image_desc():
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://mp.weixin.qq.com/s/Photo01": PHOTO_SHARE_HTML}, []),
    )
    items = await adapter.fetch(
        make_source({"article_urls": ["https://mp.weixin.qq.com/s/Photo01"]}),
    )

    assert len(items) == 1
    assert items[0].raw_content == "GTC 现场实拍：新一代推理芯片首秀。"
    assert items[0].raw_payload_json["account_name"] == "量子位"
    assert items[0].raw_payload_json["share_desc"] == "GTC 现场实拍：新一代推理芯片首秀。"


@pytest.mark.asyncio
async def test_wechat_album_url_expands_article_links_and_respects_max_items():
    routes = {
        "https://mp.weixin.qq.com/mp/appmsgalbum": ALBUM_HTML,
        "https://mp.weixin.qq.com/s?": ARTICLE_HTML,
    }
    calls: list[str] = []
    adapter = WeChatMpAdapter(transport=routing_transport(routes, calls))
    album_url = "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzA1&action=getalbum&album_id=9"
    items = await adapter.fetch(make_source({"article_urls": [album_url]}))

    assert len(items) == 2
    # data-link 规整：http → https、只保留 __biz/mid/idx/sn 身份参数
    assert calls[1] == "https://mp.weixin.qq.com/s?__biz=MzA1&mid=101&idx=1&sn=aaa"
    assert calls[2] == "https://mp.weixin.qq.com/s?__biz=MzA1&mid=102&idx=1&sn=bbb"
    assert all(item.raw_payload_json["album_url"] == album_url for item in items)
    assert items[0].raw_payload_json["link_text"] == "合集第一篇"

    capped = await adapter.fetch(make_source({"article_urls": [album_url], "max_items": 1}))
    assert len(capped) == 1


@pytest.mark.asyncio
async def test_wechat_verification_page_raises_runtime_error():
    adapter = WeChatMpAdapter(
        transport=routing_transport(
            {"https://mp.weixin.qq.com/s/Blocked01": VERIFICATION_HTML},
            [],
        ),
    )
    with pytest.raises(RuntimeError, match="verification page"):
        await adapter.fetch(make_source({"article_urls": ["https://mp.weixin.qq.com/s/Blocked01"]}))


@pytest.mark.asyncio
async def test_wechat_feed_http_error_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="rsshub route forbidden")

    adapter = WeChatMpAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(
            make_source({"rsshub_route": "/wechat/mp/gh_x", "rsshub_base": "http://rsshub.lan:1200"}),
        )


@pytest.mark.asyncio
async def test_wechat_article_http_error_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    adapter = WeChatMpAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source({"article_urls": ["https://mp.weixin.qq.com/s/Err01"]}))


@pytest.mark.asyncio
async def test_wechat_timeout_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    adapter = WeChatMpAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(
            make_source({"rsshub_route": "/wechat/mp/gh_x", "rsshub_base": "http://rsshub.lan:1200"}),
        )


@pytest.mark.asyncio
async def test_wechat_entry_key_stable_across_refetch():
    adapter = WeChatMpAdapter(
        transport=routing_transport({"https://mp.weixin.qq.com/s": ARTICLE_HTML}, []),
    )
    source = make_source(
        {
            "article_urls": [
                "https://mp.weixin.qq.com/s?__biz=MzA1&mid=2247&idx=1&sn=abcd&chksm=changes#rd",
            ],
        },
    )

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert [item.entry_key for item in first] == [item.entry_key for item in second]


@pytest.mark.asyncio
async def test_wechat_missing_fetch_entry_raises_config_error():
    adapter = WeChatMpAdapter()
    with pytest.raises(ValueError, match="missing fetch entry"):
        await adapter.fetch(make_source({}))


def test_wechat_canonical_url_keeps_identity_params_only():
    assert (
        _canonical_article_url(
            "http://mp.weixin.qq.com/s?__biz=MzA1&mid=101&idx=1&sn=aaa&chksm=x&scene=21#wechat_redirect",
        )
        == "https://mp.weixin.qq.com/s?__biz=MzA1&mid=101&idx=1&sn=aaa"
    )
    assert (
        _canonical_article_url("https://mp.weixin.qq.com/s/AbCdEfGh123?from=timeline")
        == "https://mp.weixin.qq.com/s/AbCdEfGh123"
    )
