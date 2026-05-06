"""Compact dataclass representations — strips raw event bloat."""
from __future__ import annotations
from dataclasses import dataclass

MSG_MAX = 400


@dataclass(frozen=True)
class CompactLog:
    ts: str
    svc: str | None
    status: str | None
    msg: str
    trace_id: str | None
    error_kind: str | None


@dataclass(frozen=True)
class CompactSpan:
    ts: str
    svc: str | None
    op: str | None
    resource: str | None
    duration_ms: int | None
    status: str | None
    trace_id: str | None
    error_type: str | None


@dataclass(frozen=True)
class AggregateRow:
    groups: dict[str, str]
    value: float


def _parse_tags(tags) -> dict[str, str]:
    """Datadog returns tags as list of 'key:value' strings."""
    if isinstance(tags, dict):
        return tags
    if not isinstance(tags, list):
        return {}
    result: dict[str, str] = {}
    for t in tags:
        if ":" in t:
            k, _, v = t.partition(":")
            result.setdefault(k, v)
    return result


def compact_log(raw: dict) -> CompactLog:
    attrs = raw.get("attributes") or {}
    tags = _parse_tags(attrs.get("tags") or [])
    msg = str(attrs.get("message") or attrs.get("msg") or "")
    if len(msg) > MSG_MAX:
        msg = msg[:MSG_MAX] + "…"
    return CompactLog(
        ts=attrs.get("timestamp") or raw.get("id", ""),
        svc=attrs.get("service") or tags.get("service"),
        status=attrs.get("status") or tags.get("status"),
        msg=msg,
        trace_id=attrs.get("trace_id") or tags.get("trace_id"),
        error_kind=attrs.get("error", {}).get("kind") if isinstance(attrs.get("error"), dict) else None,
    )


def compact_span(raw: dict) -> CompactSpan:
    attrs = raw.get("attributes") or {}
    custom = attrs.get("custom") or {}
    tags = _parse_tags(attrs.get("tags") or [])
    # duration is nanoseconds, stored under custom.duration in DD v2 spans API
    duration_raw = custom.get("duration") or attrs.get("duration")
    try:
        duration_ms = int(duration_raw) // 1_000_000 if duration_raw is not None else None
    except (TypeError, ValueError):
        duration_ms = None
    meta = attrs.get("meta") or {}
    trace_id = tags.get("trace_id") or attrs.get("trace_id") or meta.get("trace_id")
    err = custom.get("error") or attrs.get("error") or {}
    error_type = err.get("type") if isinstance(err, dict) else None
    return CompactSpan(
        ts=attrs.get("start_timestamp") or attrs.get("start") or raw.get("id", ""),
        svc=attrs.get("service"),
        op=attrs.get("operation_name"),
        resource=attrs.get("resource_name") or attrs.get("resource"),
        duration_ms=duration_ms,
        status=str(attrs.get("status", "")) or None,
        trace_id=trace_id,
        error_type=error_type,
    )
