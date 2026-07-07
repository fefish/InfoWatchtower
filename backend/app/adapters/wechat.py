"""微信公众号（mp.weixin.qq.com）自研适配器：第 12 类 source_type=wechat。

不依赖同事的 wx 二进制，参考 wiseflow 4.x 的公众号页面解析
（references/private/wiseflow-4x/core/wis/markdown_generation_strategy.py
WeixinArticleMarkdownGenerator）与旧系统正文抽取正则
（references/参考工具/app.py fetch_wechat_article_content）自行实现两条路径：

1. **rsshub 模式（主路径，账号级增量）**：
   - fetch_config.feed_url：完整 RSS 地址（自建 RSSHub / 微信转 RSS 桥输出），
     `rsshub.app` 前缀会按 rss.py 的 resolve_feed_url 约定自动改走
     `RSSHUB_BASE_URL` 指定的自建实例；
   - fetch_config.rsshub_route：RSSHub 路由（如 `/wechat/mp/gh_xxx`，建议值，
     具体路由取决于自建 RSSHub/桥的路由表），instance base 依次取
     fetch_config.rsshub_base → rsshub_base_env 指向的环境变量（与 wiseflow
     adapter 的 *_env 间接引用模式一致，不新增全局 settings 字段）→ 全局
     `RSSHUB_BASE_URL`（经 resolve_feed_url）→ 公共 rsshub.app（多数公众号路由
     403，仅兜底）；
   - 只给 account 标识（account_name / account_username / wx_account）时按
     fetch_config.rsshub_route_template（默认 `/wechat/mp/{account}`，建议值）
     推导路由。
   拿到 RSS 后复用 rss.py 的 feedparser 解析（RssFeedAdapter._entry_to_raw_item），
   不复制解析逻辑。

2. **article_urls 模式（定点抓取）**：fetch_config.article_urls 给定
   mp.weixin.qq.com 文章 URL 列表（或 `{"url": ..., "created_hint": ...}` 字典，
   与 page_manual 的 articles 形态兼容），直接抓文章页解析
   og:title/og:description/h1 标题/a#js_name 账号名/em#publish_time 与
   `var ct = "epoch"` 发布时间/div#js_content 正文（含图文/视频分享页
   js_image_desc / js_common_share_desc 回落），raw_payload_json 保留全部解析
   字段；合集页（mp/appmsgalbum）自动按 li.album__list-item 枚举文章链接。

**发现能力边界**：无登录态时公众号历史目录不可直接枚举——mp.weixin.qq.com 没有
公开的账号级文章列表接口，账号级增量发现依赖 rsshub 模式（自建 RSSHub/微信转
RSS 桥）或未来 wx 桥（docs/deployment/deployment-topology.md §5.1 的
WX_BRIDGE_URL/WX_BRIDGE_TOKEN sidecar 契约）。config 设计不排斥未来桥接：
account_name/account_username/wx_account 与 window_days 字段与桥接契约共用，
桥落地后可在不改源配置的前提下升级主路径。

风控说明：mp 文章页可能返回「环境异常/去验证」验证页，此时正文为空并显式抛
RuntimeError 让 run 层记为失败，而不是把验证页存成 raw_items。
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.adapters.rss import PUBLIC_RSSHUB_PREFIX, RssFeedAdapter, _json_safe, resolve_feed_url
from app.core.credentials import resolve_source_token
from app.models.content import DataSource

DEFAULT_MAX_ITEMS = 50
MAX_ITEMS_CEILING = 200
# rsshub_route 建议值模板：具体路由取决于自建 RSSHub/微信转 RSS 桥的路由表，
# 可用 fetch_config.rsshub_route / rsshub_route_template 覆盖。
DEFAULT_RSSHUB_ROUTE_TEMPLATE = "/wechat/mp/{account}"
# 公众号页面时间均为北京时间；`var ct` 为绝对 epoch 秒。
CST = timezone(timedelta(hours=8))
ARTICLE_TEXT_LIMIT = 8000

_ALBUM_URL_MARKERS = ("mp/appmsgalbum", "action=getalbum")
# 与 wiseflow async_crawler_strategy 的微信验证页特征（button 去验证）和
# 旧系统 is_crawl_error_material 对齐的风控页标记。
_VERIFICATION_MARKERS = ("去验证", "环境异常", "完成验证后即可继续访问")
_CT_PATTERN = re.compile(r"""\bct\s*=\s*["'](\d{9,11})["']""")
_CREATE_TIME_PATTERN = re.compile(r"""createTime\s*=\s*["'](\d{4}-\d{2}-\d{2}[^"']*)["']""")
_CN_DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?")
_ISO_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")
# 旧系统同款正文 HTML 抽取正则（references/参考工具/app.py fetch_wechat_article_content）。
_JS_CONTENT_HTML_PATTERNS = (
    re.compile(
        r"<div[^>]+id=[\"']js_content[\"'][^>]*>(?P<body>.*?)(?:</div>\s*<script|</div>\s*</div>)",
        re.I | re.S,
    ),
    re.compile(
        r"<div[^>]+class=[\"'][^\"']*rich_media_content[^\"']*[\"'][^>]*>(?P<body>.*?)</div>",
        re.I | re.S,
    ),
)


class WeChatMpAdapter:
    """source_type=wechat 真适配器（rsshub 主路径 + article_urls 定点抓取）。"""

    source_type = "wechat"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        max_items = _bounded_int(
            config.get("max_items"),
            default=DEFAULT_MAX_ITEMS,
            maximum=MAX_ITEMS_CEILING,
        )
        account_name = str(config.get("account_name") or "").strip()
        account_username = str(
            config.get("account_username") or config.get("wx_account") or "",
        ).strip()
        account = {"account_name": account_name, "account_username": account_username}
        # 自建 RSSHub / 微信转 RSS 桥可能要求 Bearer 认证；推荐顺序
        # credential_ref → auth_token_env → auth_token（core/credentials.py）。
        token = resolve_source_token(data_source, config)

        explicit_feed = bool(
            str(config.get("feed_url") or "").strip()
            or str(config.get("rsshub_route") or "").strip(),
        )
        feed_url, rsshub_route = _resolve_feed_entry(config, data_source, account)
        article_urls = _article_url_entries(config, data_source)
        # rsshub 是主路径；但只凭 account 标识推导的路由是建议值，
        # 不覆盖显式配置的 article_urls 定点抓取。
        if feed_url and (explicit_feed or not article_urls):
            return await self._fetch_feed(feed_url, rsshub_route, account, max_items, token)
        if article_urls:
            return await self._fetch_articles(article_urls, account, max_items, token)

        raise ValueError(
            "wechat source is missing fetch entry: set fetch_config.feed_url, "
            "rsshub_route (+ rsshub_base/rsshub_base_env or RSSHUB_BASE_URL), "
            "account_name/account_username, or article_urls",
        )

    async def _fetch_feed(
        self,
        feed_url: str,
        rsshub_route: str,
        account: dict[str, str],
        max_items: int,
        token: str = "",
    ) -> list[RawItemInput]:
        async with self._client(timeout=20.0, token=token) as client:
            response = await client.get(feed_url)
            response.raise_for_status()
        parsed = feedparser.parse(response.content)
        # 复用 rss.py 的 entry 解析，不复制逻辑；只补 wechat 语义标注。
        rss_parser = RssFeedAdapter()
        items: list[RawItemInput] = []
        for entry in parsed.entries[:max_items]:
            item = rss_parser._entry_to_raw_item(entry)
            items.append(
                replace(
                    item,
                    source_specific_json={
                        **item.source_specific_json,
                        "wechat_mode": "rsshub",
                        # 只记录路由不记录完整 feed URL，避免自建实例地址进入同步 payload。
                        "rsshub_route": rsshub_route,
                        **account,
                    },
                ),
            )
        return items

    async def _fetch_articles(
        self,
        entries: list[dict[str, str]],
        account: dict[str, str],
        max_items: int,
        token: str = "",
    ) -> list[RawItemInput]:
        async with self._client(timeout=20.0, token=token) as client:
            expanded: list[dict[str, str]] = []
            for entry in entries:
                if len(expanded) >= max_items:
                    break
                url = entry["url"]
                if _is_album_url(url):
                    album_links = await self._expand_album(client, url)
                    for link_url, link_title in album_links:
                        if len(expanded) >= max_items:
                            break
                        expanded.append(
                            {
                                "url": link_url,
                                "title_hint": link_title,
                                "created_hint": "",
                                "album_url": url,
                            },
                        )
                else:
                    expanded.append(entry)
            return [await self._fetch_article(client, entry, account) for entry in expanded]

    async def _expand_album(
        self,
        client: httpx.AsyncClient,
        album_url: str,
    ) -> list[tuple[str, str]]:
        response = await client.get(album_url)
        response.raise_for_status()
        extractor = _AlbumLinkExtractor()
        extractor.feed(response.text)
        if not extractor.links and _looks_like_verification_page(response.text):
            raise RuntimeError(
                f"mp.weixin.qq.com returned a verification page (risk control) for {album_url}",
            )
        return extractor.links

    async def _fetch_article(
        self,
        client: httpx.AsyncClient,
        entry: dict[str, str],
        account: dict[str, str],
    ) -> RawItemInput:
        url = entry["url"]
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

        extractor = _MpArticleExtractor()
        extractor.feed(html)
        meta = extractor.meta
        content_text = " ".join(" ".join(extractor.content_parts).split())
        share_desc = " ".join(" ".join(extractor.fields.get("share_desc", [])).split())
        if not content_text and not share_desc and _looks_like_verification_page(html):
            raise RuntimeError(
                f"mp.weixin.qq.com returned a verification page (risk control) for {url}",
            )

        h1_title = " ".join(" ".join(extractor.fields.get("h1_title", [])).split())
        page_account = " ".join(" ".join(extractor.fields.get("account_name", [])).split())
        publish_time_text = " ".join(
            " ".join(extractor.fields.get("publish_time_text", [])).split(),
        )
        canonical_url = _canonical_article_url(
            str(meta.get("og:url") or "").strip() or str(response.url) or url,
        )
        title = (
            str(meta.get("og:title") or "").strip()
            or h1_title
            or entry.get("title_hint", "")
            or canonical_url
        )
        description = str(meta.get("og:description") or meta.get("description") or "").strip()
        account_name = page_account or account["account_name"]
        author = str(meta.get("og:article:author") or "").strip() or account_name
        published_at = _parse_publish_datetime(
            html,
            publish_time_text,
            entry.get("created_hint", ""),
        )
        content_html = _extract_content_html(html)
        raw_content = content_text or share_desc or description or title

        payload: dict[str, Any] = {
            "url": url,
            "final_url": str(response.url),
            "canonical_url": canonical_url,
            "title": title,
            "h1_title": h1_title,
            "account_name": account_name,
            "author": author,
            "publish_time_text": publish_time_text,
            "published_at": published_at.isoformat() if published_at else None,
            "meta": meta,
            "description": description,
            "content_text": content_text,
            "share_desc": share_desc,
            "content_html": content_html,
        }
        if entry.get("album_url"):
            payload["album_url"] = entry["album_url"]
        if entry.get("title_hint"):
            payload["link_text"] = entry["title_hint"]

        return RawItemInput(
            entry_key=canonical_url,
            source_title=title,
            source_url=canonical_url,
            raw_content=raw_content[:ARTICLE_TEXT_LIMIT],
            published_at=published_at,
            raw_payload_json=_json_safe(payload),
            source_specific_json={
                "wechat_mode": "article_urls",
                "account_name": account_name,
                "account_username": account["account_username"],
            },
        )

    def _client(self, timeout: float, token: str = "") -> httpx.AsyncClient:
        headers = dict(BROWSER_FETCH_HEADERS)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        )


def _resolve_feed_entry(
    config: dict[str, Any],
    data_source: DataSource,
    account: dict[str, str],
) -> tuple[str, str]:
    """返回 (feed_url, rsshub_route)；无 RSS 入口时返回 ("", "")。"""
    explicit = str(config.get("feed_url") or "").strip()
    if explicit:
        return resolve_feed_url(explicit), ""

    route = str(config.get("rsshub_route") or "").strip()
    if not route:
        account_ref = account["account_username"] or account["account_name"]
        if account_ref:
            template = str(
                config.get("rsshub_route_template") or DEFAULT_RSSHUB_ROUTE_TEMPLATE,
            ).strip()
            route = template.format(account=quote(account_ref, safe=""))
    if route:
        route = "/" + route.lstrip("/")
        base = str(
            config.get("rsshub_base") or _env_value(config.get("rsshub_base_env")) or "",
        ).strip().rstrip("/")
        if base:
            return f"{base}{route}", route
        # 无实例级 base 时借用 rss.py 的 rsshub.app 前缀改写约定：
        # 配置了全局 RSSHUB_BASE_URL 则改走自建实例，否则落到公共 rsshub.app。
        return resolve_feed_url(f"{PUBLIC_RSSHUB_PREFIX.rstrip('/')}{route}"), route

    url = str(data_source.url or "").strip()
    if url.startswith(("http://", "https://")) and "mp.weixin.qq.com" not in url:
        return resolve_feed_url(url), ""
    return "", ""


def _article_url_entries(config: dict[str, Any], data_source: DataSource) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    raw_entries = list(config.get("article_urls") or [])
    if not raw_entries:
        # 与 page_manual 的 articles 形态兼容
        raw_entries = list(config.get("articles") or [])
    for raw in raw_entries:
        if isinstance(raw, dict):
            url = str(raw.get("url") or "").strip()
            created_hint = str(raw.get("created_hint") or "").strip()
            title_hint = str(raw.get("title") or raw.get("title_hint") or "").strip()
        else:
            url = str(raw or "").strip()
            created_hint = ""
            title_hint = ""
        if url.startswith(("http://", "https://")):
            entries.append({"url": url, "created_hint": created_hint, "title_hint": title_hint})
    source_url = str(data_source.url or "").strip()
    if not entries and "mp.weixin.qq.com" in source_url:
        entries.append({"url": source_url, "created_hint": "", "title_hint": ""})
    return entries


def _is_album_url(url: str) -> bool:
    return any(marker in url for marker in _ALBUM_URL_MARKERS)


def _looks_like_verification_page(html: str) -> bool:
    return any(marker in html for marker in _VERIFICATION_MARKERS)


def _canonical_article_url(url: str) -> str:
    """mp 文章 URL 规整成稳定 entry_key：/s/<id> 保留路径；/s?__biz=... 只保留
    __biz/mid/idx/sn 身份参数（chksm 等校验参数每次分享都变，wiseflow 同款处理）。"""
    parts = urlsplit(url)
    if "mp.weixin.qq.com" in parts.netloc.lower():
        if parts.path.startswith("/s/") and len(parts.path) > len("/s/"):
            return urlunsplit(("https", "mp.weixin.qq.com", parts.path, "", ""))
        if parts.path == "/s":
            params = parse_qs(parts.query)
            identity_keys = ("__biz", "mid", "idx", "sn")
            keep = [(key, params[key][0]) for key in identity_keys if params.get(key)]
            if keep:
                return urlunsplit(("https", "mp.weixin.qq.com", "/s", urlencode(keep), ""))
    cut = url.find("chksm=")
    if cut != -1:
        url = url[: cut - 1]
    return url.split("#", 1)[0]


def _extract_content_html(html: str) -> str:
    for pattern in _JS_CONTENT_HTML_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group("body").strip()
    return ""


def _parse_publish_datetime(
    html: str,
    publish_time_text: str,
    created_hint: str,
) -> datetime | None:
    parsed = _parse_datetime_text(publish_time_text)
    if parsed is not None:
        return parsed
    ct_match = _CT_PATTERN.search(html)
    if ct_match:
        try:
            return datetime.fromtimestamp(int(ct_match.group(1)), tz=UTC)
        except (OverflowError, OSError, ValueError):
            pass
    create_match = _CREATE_TIME_PATTERN.search(html)
    if create_match:
        parsed = _parse_datetime_text(create_match.group(1))
        if parsed is not None:
            return parsed
    return _parse_datetime_text(created_hint)


def _parse_datetime_text(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    cn_match = _CN_DATE_PATTERN.search(text)
    if cn_match:
        year, month, day, hour, minute = cn_match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            tzinfo=CST,
        ).astimezone(UTC)
    iso_match = _ISO_DATE_PATTERN.search(text)
    if iso_match:
        date_part, hour, minute, second = iso_match.groups()
        year, month, day = (int(part) for part in date_part.split("-"))
        try:
            return datetime(
                year,
                month,
                day,
                int(hour or 0),
                int(minute or 0),
                int(second or 0),
                tzinfo=CST,
            ).astimezone(UTC)
        except ValueError:
            return None
    return None


def _env_value(name: object) -> str:
    env_name = str(name or "").strip()
    if not env_name:
        return ""
    return os.environ.get(env_name, "").strip()


def _bounded_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


class _MpArticleExtractor(HTMLParser):
    """mp 文章页字段抽取（stdlib HTMLParser，结构对齐 wiseflow 的解析目标）：

    - meta：og:title/og:description/og:article:author/og:url/description 等
    - h1_title：首个 <h1>（rich_media_title / activity-name）
    - account_name：a#js_name（分享/图文页回落 js_wx_follow_nickname、
      wx_follow_nickname class）
    - publish_time_text：em#publish_time（渲染后的页面才有文本）
    - content：div#js_content 正文文本（跳过 script/style）
    - share_desc：js_image_desc / js_common_share_desc / js_text_desc
      （图片/视频分享页无 js_content 时的正文回落）
    """

    CAPTURE_IDS = {
        "js_name": "account_name",
        "js_wx_follow_nickname": "account_name",
        "publish_time": "publish_time_text",
        "activity-name": "h1_title",
        "js_image_desc": "share_desc",
        "js_common_share_desc": "share_desc",
        "js_text_desc": "share_desc",
    }
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.fields: dict[str, list[str]] = {}
        self.content_parts: list[str] = []
        self._active_field: tuple[str, str] | None = None
        self._content_depth = 0
        self._skip_depth = 0
        self._h1_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key: (value or "") for key, value in attrs}
        if tag == "meta":
            key = attr.get("property") or attr.get("name") or ""
            content = attr.get("content", "")
            if key and content and key not in self.meta:
                self.meta[key] = content
            return
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self.VOID_TAGS:
            return
        element_id = attr.get("id", "")
        if element_id == "js_content" and self._content_depth == 0:
            self._content_depth = 1
            return
        if self._content_depth > 0:
            if tag == "div":
                self._content_depth += 1
            return
        field = self.CAPTURE_IDS.get(element_id)
        if field is None and tag == "h1" and not self._h1_seen:
            field = "h1_title"
        if field is None and "wx_follow_nickname" in attr.get("class", ""):
            field = "account_name"
        if tag == "h1":
            self._h1_seen = True
        if field is not None and self._active_field is None:
            self._active_field = (tag, field)
            self.fields.setdefault(field, [])

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._content_depth > 0:
            self.content_parts.append(text)
            return
        if self._active_field is not None:
            self.fields[self._active_field[1]].append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(self._skip_depth - 1, 0)
            return
        if self._content_depth > 0:
            if tag == "div":
                self._content_depth -= 1
            return
        if self._active_field is not None and tag == self._active_field[0]:
            self._active_field = None


class _AlbumLinkExtractor(HTMLParser):
    """合集页（mp/appmsgalbum）文章链接枚举：li.album__list-item 的
    data-link/data-title（wiseflow WeixinArticleMarkdownGenerator 同款约定）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "li":
            return
        attr = {key: (value or "") for key, value in attrs}
        if "album__list-item" not in attr.get("class", ""):
            return
        link = attr.get("data-link", "").strip().replace("http://", "https://", 1)
        if not link or link.startswith(("javascript", "about:blank")):
            return
        link = _canonical_article_url(link)
        if link in self._seen:
            return
        self._seen.add(link)
        self.links.append((link, attr.get("data-title", "").strip()))
