from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import (
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    NewsItem,
    RawItem,
    RecommendationItem,
)
from app.models.workspace import Workspace, WorkspaceSourceLink

TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src", "spm"}


@dataclass(frozen=True)
class NewsNormalizationRequest:
    workspace_code: str
    source_types: list[str]
    limit: int | None = None


@dataclass(frozen=True)
class NewsNormalizationResult:
    workspace_code: str
    raw_scanned: int
    news_created: int
    news_updated: int
    raw_skipped: int
    dedupe_groups_updated: int
    winners: int
    losers: int


class WorkspaceNotFoundError(ValueError):
    pass


def normalize_workspace_raw_items(
    session: Session,
    request: NewsNormalizationRequest,
) -> NewsNormalizationResult:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    rows = _workspace_raw_rows(
        session=session,
        workspace=workspace,
        source_types=_normalize_source_types(request.source_types),
        limit=request.limit,
    )
    changed_keys: set[str] = set()
    old_keys: set[str] = set()
    created = 0
    updated = 0
    skipped = 0

    for raw_item, source, source_link in rows:
        normalized = _normalized_payload(raw_item)
        news_item = _find_existing_news_item(session, workspace, raw_item)
        if normalized.dedupe_key is None:
            skipped += 1
            if news_item is not None:
                old_keys.add(news_item.dedupe_key)
                news_item.active = False
                news_item.duplicate_of_id = None
                news_item.normalization_status = "skipped"
                news_item.normalization_notes = normalized.normalization_notes
                updated += 1
            continue

        if news_item is None:
            news_item = NewsItem(
                raw_item=raw_item,
                data_source=source,
                workspace_code=workspace.code,
                raw_item_id=raw_item.id,
                data_source_id=source.id,
                source_type=raw_item.source_type,
                source_name=raw_item.source_name,
                dedupe_key=normalized.dedupe_key,
            )
            session.add(news_item)
            created += 1
        else:
            if news_item.dedupe_key != normalized.dedupe_key:
                old_keys.add(news_item.dedupe_key)
            updated += 1

        _apply_normalized_payload(
            news_item=news_item,
            raw_item=raw_item,
            source=source,
            source_link=source_link,
            workspace=workspace,
            normalized=normalized,
        )
        changed_keys.add(normalized.dedupe_key)

    session.flush()

    groups_updated = 0
    for dedupe_key in sorted(changed_keys | old_keys):
        groups_updated += _rebuild_dedupe_group(session, workspace, dedupe_key)

    session.flush()
    counts = _winner_loser_counts(session, workspace.code)
    return NewsNormalizationResult(
        workspace_code=workspace.code,
        raw_scanned=len(rows),
        news_created=created,
        news_updated=updated,
        raw_skipped=skipped,
        dedupe_groups_updated=groups_updated,
        winners=counts[0],
        losers=counts[1],
    )


def _find_existing_news_item(
    session: Session,
    workspace: Workspace,
    raw_item: RawItem,
) -> NewsItem | None:
    return session.scalar(
        select(NewsItem)
        .where(
            NewsItem.workspace_code == workspace.code,
            NewsItem.raw_item_id == raw_item.id,
        )
        .order_by(NewsItem.created_at),
    )


@dataclass(frozen=True)
class NormalizedPayload:
    canonical_url: str | None
    normalized_title: str
    summary: str
    content: str
    author: str
    dedupe_key: str | None
    normalization_notes: str


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    value = url.strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.rstrip("/") or None

    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")

    query_pairs = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_key(key)
    ]
    query_pairs.sort(key=lambda item: (item[0], item[1]))
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(query_pairs, doseq=True),
            "",
        ),
    )


def normalize_title(title: str | None) -> str:
    text = _clean_text(title or "")
    pieces: list[str] = []
    for char in text.lower():
        category = unicodedata.category(char)
        if char.isspace() or category.startswith(("P", "S")):
            pieces.append(" ")
        else:
            pieces.append(char)
    return " ".join("".join(pieces).split())


def _workspace_raw_rows(
    session: Session,
    workspace: Workspace,
    source_types: list[str],
    limit: int | None,
) -> list[tuple[RawItem, DataSource, WorkspaceSourceLink]]:
    statement = (
        select(RawItem, DataSource, WorkspaceSourceLink)
        .join(DataSource, RawItem.data_source_id == DataSource.id)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
        )
        .order_by(RawItem.fetched_at.desc(), RawItem.id)
    )
    if source_types:
        statement = statement.where(DataSource.source_type.in_(source_types))
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.execute(statement).all())


def _normalize_source_types(source_types: list[str]) -> list[str]:
    normalized: list[str] = []
    for source_type in source_types:
        value = source_type.strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalized_payload(raw_item: RawItem) -> NormalizedPayload:
    canonical_url = canonicalize_url(raw_item.source_url)
    normalized_title = normalize_title(raw_item.source_title)
    content = _clean_text(raw_item.raw_content) or _clean_text(raw_item.source_title)
    summary = _summary(content)
    dedupe_key = _dedupe_key(canonical_url, normalized_title, raw_item.published_at)
    notes = "" if dedupe_key else "missing_url_or_title_date"
    return NormalizedPayload(
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        summary=summary,
        content=content,
        author=_extract_author(raw_item.raw_payload_json or {}),
        dedupe_key=dedupe_key,
        normalization_notes=notes,
    )


def _apply_normalized_payload(
    news_item: NewsItem,
    raw_item: RawItem,
    source: DataSource,
    source_link: WorkspaceSourceLink,
    workspace: Workspace,
    normalized: NormalizedPayload,
) -> None:
    news_item.workspace_code = workspace.code
    news_item.domain_code = (
        source_link.domain_code
        or source.domain_code
        or workspace.default_domain_code
    )
    news_item.visibility_scope = raw_item.visibility_scope or source.visibility_scope
    news_item.sync_policy = raw_item.sync_policy or source.sync_policy
    news_item.raw_item = raw_item
    news_item.data_source = source
    news_item.raw_item_id = raw_item.id
    news_item.data_source_id = source.id
    news_item.source_type = raw_item.source_type
    news_item.source_name = raw_item.source_name
    news_item.source_url = raw_item.source_url
    news_item.canonical_url = normalized.canonical_url
    news_item.source_title = raw_item.source_title
    news_item.normalized_title = normalized.normalized_title
    news_item.summary = normalized.summary
    news_item.content = normalized.content
    news_item.author = normalized.author
    news_item.published_at = raw_item.published_at
    news_item.focus_id = source.default_focus_id
    news_item.dedupe_key = normalized.dedupe_key or ""
    news_item.normalization_status = "normalized"
    news_item.normalization_notes = normalized.normalization_notes


def _dedupe_key(
    canonical_url: str | None,
    normalized_title: str,
    published_at: datetime | None,
) -> str | None:
    if canonical_url:
        return f"url:{canonical_url}"
    if normalized_title and published_at:
        return f"title:{normalized_title}|date:{published_at.date().isoformat()}"
    return None


def _rebuild_dedupe_group(session: Session, workspace: Workspace, dedupe_key: str) -> int:
    news_items = list(
        session.scalars(
            select(NewsItem)
            .where(
                NewsItem.workspace_code == workspace.code,
                NewsItem.dedupe_key == dedupe_key,
                NewsItem.normalization_status == "normalized",
            )
            .order_by(NewsItem.created_at, NewsItem.id),
        ).all(),
    )
    group = session.scalar(
        select(DedupeGroup).where(
            DedupeGroup.workspace_code == workspace.code,
            DedupeGroup.dedupe_key == dedupe_key,
        ),
    )
    if group is None:
        group = DedupeGroup(
            workspace_code=workspace.code,
            domain_code=workspace.default_domain_code,
            dedupe_key=dedupe_key,
        )
        session.add(group)
        session.flush()

    _delete_stale_group_items(session, group, news_items)

    if not news_items:
        group.item_count = 0
        group.winner_news_item_id = None
        group.status = "empty"
        return 1

    winner = max(news_items, key=_winner_sort_key)
    reason = "same canonical URL" if dedupe_key.startswith("url:") else "same normalized title/date"

    group.domain_code = winner.domain_code
    group.visibility_scope = winner.visibility_scope
    group.sync_policy = winner.sync_policy
    group.item_count = len(news_items)
    group.winner_news_item = winner
    group.status = "active"

    for news_item in news_items:
        is_winner = news_item.id == winner.id
        news_item.active = is_winner
        news_item.duplicate_of_id = None if is_winner else winner.id
        group_item = _ensure_group_item(session, group, news_item)
        group_item.is_winner = is_winner
        group_item.duplicate_reason = "winner" if is_winner else reason
        group_item.rank_score = _rank_score(news_item)
    return 1


def _delete_stale_group_items(
    session: Session,
    group: DedupeGroup,
    news_items: list[NewsItem],
) -> None:
    current_ids = {item.id for item in news_items}
    existing_items = session.scalars(
        select(DedupeGroupItem).where(DedupeGroupItem.dedupe_group_id == group.id),
    ).all()
    for group_item in existing_items:
        if group_item.news_item_id not in current_ids:
            if _group_item_has_recommendation_history(session, group_item):
                group_item.is_winner = False
                group_item.duplicate_reason = "stale_after_rebuild"
                group_item.rank_score = 0.0
            else:
                session.delete(group_item)


def _group_item_has_recommendation_history(
    session: Session,
    group_item: DedupeGroupItem,
) -> bool:
    return (
        session.scalar(
            select(RecommendationItem.id)
            .where(RecommendationItem.dedupe_group_item_id == group_item.id)
            .limit(1),
        )
        is not None
    )


def _ensure_group_item(
    session: Session,
    group: DedupeGroup,
    news_item: NewsItem,
) -> DedupeGroupItem:
    group_item = session.scalar(
        select(DedupeGroupItem).where(
            DedupeGroupItem.dedupe_group_id == group.id,
            DedupeGroupItem.news_item_id == news_item.id,
        ),
    )
    if group_item is None:
        group_item = DedupeGroupItem(dedupe_group=group, news_item=news_item)
        session.add(group_item)
    return group_item


def _winner_sort_key(news_item: NewsItem) -> tuple[int, int, int, int, float]:
    return (
        1 if news_item.canonical_url or news_item.source_url else 0,
        1 if news_item.source_type == "wiseflow" else 0,
        _trusted_source_bonus(news_item),
        len(news_item.content or ""),
        _published_timestamp(news_item.published_at),
    )


def _rank_score(news_item: NewsItem) -> float:
    has_url, is_wiseflow, trusted, content_length, published = _winner_sort_key(news_item)
    return (
        has_url * 1000.0
        + is_wiseflow * 100.0
        + trusted * 10.0
        + min(content_length / 1000.0, 5.0)
        + published / 10_000_000_000.0
    )


def _trusted_source_bonus(news_item: NewsItem) -> int:
    source_name = (news_item.source_name or "").lower()
    source_url = (news_item.source_url or "").lower()
    trusted_markers = ["official", "science", "research", "blog", "news"]
    if any(marker in source_name or marker in source_url for marker in trusted_markers):
        return 1
    source = news_item.data_source
    metadata = source.metadata_json if source else {}
    if str(metadata.get("primary_category") or "").lower() in {"official", "research"}:
        return 1
    return 0


def _published_timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _winner_loser_counts(session: Session, workspace_code: str) -> tuple[int, int]:
    news_items = session.scalars(
        select(NewsItem).where(
            NewsItem.workspace_code == workspace_code,
            NewsItem.normalization_status == "normalized",
        ),
    ).all()
    winners = sum(1 for item in news_items if item.active)
    losers = sum(1 for item in news_items if not item.active)
    return winners, losers


def _is_tracking_query_key(key: str) -> bool:
    normalized = key.lower()
    return normalized.startswith("utm_") or normalized in TRACKING_QUERY_KEYS


def _clean_text(value: str) -> str:
    unescaped = html.unescape(value or "")
    unescaped = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        unescaped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    unescaped = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        unescaped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    without_tags = re.sub(r"<[^>]+>", " ", unescaped)
    return " ".join(without_tags.split())


def _summary(content: str) -> str:
    if len(content) <= 280:
        return content
    return f"{content[:277].rstrip()}..."


def _extract_author(payload: dict) -> str:
    for key in ("author", "creator", "dc_creator", "byline"):
        value = payload.get(key)
        author = _author_value_to_text(value)
        if author:
            return author[:255]
    author_detail = payload.get("author_detail")
    author = _author_value_to_text(author_detail)
    if author:
        return author[:255]
    authors = payload.get("authors")
    author = _author_value_to_text(authors)
    return author[:255] if author else ""


def _author_value_to_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, list):
        pieces = [_author_value_to_text(item) for item in value]
        return ", ".join(piece for piece in pieces if piece)
    return ""
