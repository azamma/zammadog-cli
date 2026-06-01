"""Compact dataclass representations — strips raw event bloat."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

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


@dataclass(frozen=True)
class CompactMetric:
    ts: str       # ISO8601 datapoint time
    label: str    # metric label (truncated)
    value: float


@dataclass(frozen=True)
class CompactLogGroup:
    name: str               # log group name
    stored_mb: float        # stored bytes converted to MB
    retention_days: int | None  # retention in days, None = never expire


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


def compact_cw_log(row: dict) -> CompactLog:
    """Map a CloudWatch Insights row or filter_log_events event to a CompactLog.

    Args:
        row: A dict from Insights results (field:value pairs) or a
            filter_log_events event dict.

    Returns:
        CompactLog with best-effort field extraction.
    """
    # Insights returns fields as a list of {field,value} — already flattened by
    # CloudWatchClient before calling us. filter_log_events returns nested dicts.
    msg = str(row.get("@message") or row.get("message") or "")
    if len(msg) > MSG_MAX:
        msg = msg[:MSG_MAX] + "…"

    raw_ts = row.get("@timestamp") or row.get("timestamp")
    if raw_ts is None:
        ts = ""
    elif isinstance(raw_ts, int):
        ts = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        ts = str(raw_ts)

    # Insights @log is "<account-id>:<log-group-name>" — keep just the group name,
    # which is the most useful "service" label when searching across groups.
    log_group = row.get("@log")
    if log_group and ":" in log_group:
        log_group = log_group.split(":", 1)[1]

    return CompactLog(
        ts=ts,
        svc=row.get("service") or log_group or row.get("@logStream") or row.get("logStreamName"),
        status=row.get("level") or row.get("status"),
        msg=msg,
        trace_id=row.get("trace_id"),
        error_kind=None,
    )
