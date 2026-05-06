"""Orchestrator-friendly evidence fetcher: one DatadogLink → text block."""
from __future__ import annotations
from .client import DatadogClient, DatadogError
from .links import DatadogLink
from .render import render_aggregate, render_logs_table, render_spans_table

_DEFAULT_FROM = "now-1h"
_DEFAULT_TO = "now"
_SAMPLE_LIMIT = 25
_TRACE_LIMIT = 50


def gather_evidence(client: DatadogClient, link: DatadogLink, link_num: int = 1) -> str:
    """Fetch Datadog evidence for one link; return compact text block."""
    from_ts = link.from_ts or _DEFAULT_FROM
    to_ts = link.to_ts or _DEFAULT_TO
    url_short = link.raw_url[:120] + ("…" if len(link.raw_url) > 120 else "")

    header = (
        f"# Datadog evidence — link {link_num} ({link.kind})\n"
        f"URL: {url_short}\n"
        f"Window: {from_ts} → {to_ts}  Site: {link.site}"
    )
    if link.query:
        header += f"  Query: {link.query}"

    if link.kind in ("apm-services", "unknown"):
        return (
            f"{header}\n"
            f"Kind: {link.kind} (Watchdog/services view); skipped — no actionable query."
        )

    sections = [header, ""]

    if link.kind == "logs":
        query = link.query or "*"
        try:
            agg = client.logs_aggregate(query, from_ts, to_ts, group_by=["service", "status"])
            sections.append("## Aggregate (count by service,status)")
            sections.append(render_aggregate(agg))
        except DatadogError as e:
            sections.append(f"## Aggregate\n(failed: {e})")

        try:
            samples = client.logs_search(query, from_ts, to_ts, limit=_SAMPLE_LIMIT)
            sections.append(f"\n## Sample ({len(samples)} most recent)")
            sections.append(render_logs_table(samples))
        except DatadogError as e:
            sections.append(f"## Sample\n(failed: {e})")

    elif link.kind == "apm-search":
        query = link.query or "*"
        try:
            agg = client.apm_aggregate(query, from_ts, to_ts, group_by=["service", "resource"])
            sections.append("## Aggregate (count by service,resource)")
            sections.append(render_aggregate(agg))
        except DatadogError as e:
            sections.append(f"## Aggregate\n(failed: {e})")

        try:
            samples = client.apm_search(query, from_ts, to_ts, limit=_SAMPLE_LIMIT)
            sections.append(f"\n## Sample ({len(samples)} most recent)")
            sections.append(render_spans_table(samples))
        except DatadogError as e:
            sections.append(f"## Sample\n(failed: {e})")

    elif link.kind == "apm-trace":
        if not link.trace_id:
            return f"{header}\nNo trace_id found in URL — cannot fetch."
        query = f"trace_id:{link.trace_id}"
        try:
            spans = client.apm_search(query, from_ts, to_ts, limit=_TRACE_LIMIT)
            sections.append(f"## Spans for trace {link.trace_id} ({len(spans)} found)")
            sections.append(render_spans_table(spans))
        except DatadogError as e:
            sections.append(f"## Spans\n(failed: {e})")

    return "\n".join(sections)
