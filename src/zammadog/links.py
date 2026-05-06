"""Parse Datadog URLs into structured DatadogLink objects."""
from __future__ import annotations
import re
import urllib.parse
from dataclasses import dataclass
from typing import Literal

_DD_PATTERN = re.compile(
    r"https://app\.(?:[a-z0-9-]+\.)?datadoghq\.(com|eu)/[^\s\"'<>]+"
)

LinkKind = Literal["logs", "apm-search", "apm-trace", "apm-services", "unknown"]


@dataclass(frozen=True)
class DatadogLink:
    kind: LinkKind
    site: str
    query: str | None
    from_ts: str | None
    to_ts: str | None
    env: str | None
    service: str | None
    trace_id: str | None
    raw_url: str


def _classify(path: str, qs: dict[str, list[str]]) -> LinkKind:
    if path.startswith("/logs"):
        return "logs"
    if path.startswith("/apm/trace/") or qs.get("traceId"):
        return "apm-trace"
    if path.startswith("/apm"):
        trace_query = (qs.get("traceQuery") or [""])[0]
        if trace_query:
            return "apm-search"
        view = (qs.get("view") or [""])[0]
        recommendation = qs.get("recommendationId")
        if view == "services" or recommendation:
            return "apm-services"
        return "apm-search"
    return "unknown"


def _extract_link(url: str) -> DatadogLink:
    parsed = urllib.parse.urlparse(url)
    # site from hostname: app.datadoghq.com → datadoghq.com
    host = parsed.netloc  # e.g. app.datadoghq.com
    site = ".".join(host.split(".")[-2:])  # datadoghq.com or datadoghq.eu

    qs = urllib.parse.parse_qs(parsed.query)

    def first(key: str) -> str | None:
        vals = qs.get(key)
        return vals[0] if vals else None

    kind = _classify(parsed.path, qs)

    # trace_id: from path /apm/trace/<id> or ?traceId=
    trace_id: str | None = None
    if parsed.path.startswith("/apm/trace/"):
        parts = parsed.path.split("/")
        trace_id = parts[-1] if parts[-1] else None
    elif first("traceId"):
        trace_id = first("traceId")

    query = first("query") or first("q") or first("traceQuery")
    from_ts = first("from_ts") or first("start") or first("from")
    to_ts = first("to_ts") or first("end") or first("to")

    return DatadogLink(
        kind=kind,
        site=site,
        query=query,
        from_ts=from_ts,
        to_ts=to_ts,
        env=first("env"),
        service=first("service"),
        trace_id=trace_id,
        raw_url=url,
    )


def extract_datadog_links(text: str) -> list[DatadogLink]:
    """Find all Datadog app URLs in text and parse them."""
    seen: set[str] = set()
    links: list[DatadogLink] = []
    for m in _DD_PATTERN.finditer(text):
        url = m.group(0).rstrip(".,;)")
        if url in seen:
            continue
        seen.add(url)
        links.append(_extract_link(url))
    return links
