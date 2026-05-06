"""Datadog HTTP client — stdlib urllib only, no third-party deps."""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .compact import AggregateRow, CompactLog, CompactSpan, compact_log, compact_span

MAX_LIMIT = 50
MAX_WINDOW_HOURS = 24
DEFAULT_LIMIT = 25
HTTP_TIMEOUT_S = 15.0
RETRY_5XX = 2


class DatadogError(Exception):
    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _rel_to_epoch_ms(t: str) -> int:
    """Convert relative ('now-15m') or RFC3339 to epoch ms."""
    if t.startswith("now"):
        suffix = t[3:]
        if not suffix:
            return int(time.time() * 1000)
        unit = suffix[-1]
        amount = int(suffix[1:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        if unit not in multipliers:
            raise DatadogError(f"Unknown time unit '{unit}' in '{t}'")
        return int((time.time() - amount * multipliers[unit]) * 1000)
    # Try RFC3339 / ISO 8601
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise DatadogError(f"Cannot parse time spec: {t!r}")


def _window_guard(from_ts: str, to_ts: str) -> None:
    f_ms = _rel_to_epoch_ms(from_ts)
    t_ms = _rel_to_epoch_ms(to_ts)
    hours = (t_ms - f_ms) / 3_600_000
    if hours > MAX_WINDOW_HOURS:
        raise DatadogError(
            f"Window {hours:.1f}h exceeds max {MAX_WINDOW_HOURS}h. Narrow the time range."
        )


@dataclass
class DatadogClient:
    site: str = "datadoghq.com"
    api_key: str = ""
    app_key: str = ""
    timeout_s: float = HTTP_TIMEOUT_S

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("DD-API-KEY", self.api_key)
        req.add_header("DD-APPLICATION-KEY", self.app_key)
        req.add_header("Content-Type", "application/json")

        def _call() -> bytes:
            resp = urllib.request.urlopen(req, timeout=self.timeout_s)
            return resp.read()

        for attempt in range(RETRY_5XX):
            try:
                body_bytes = _call()
                return json.loads(body_bytes.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code >= 500 and attempt < RETRY_5XX - 1:
                    time.sleep(2 ** attempt)
                    continue
                body = e.read().decode("utf-8", errors="replace")
                raise DatadogError(
                    f"Datadog {method} {url} failed: {e.code}", status=e.code, body=body
                ) from e
            except urllib.error.URLError as e:
                raise DatadogError(f"Datadog {method} {url} unreachable: {e.reason}") from e
        raise DatadogError("Unreachable")  # pragma: no cover

    def _base(self) -> str:
        return f"https://api.{self.site}"

    def logs_search(
        self, query: str, from_ts: str, to_ts: str, *, limit: int = DEFAULT_LIMIT
    ) -> list[CompactLog]:
        limit = min(limit, MAX_LIMIT)
        _window_guard(from_ts, to_ts)
        payload = {
            "filter": {
                "query": query,
                "from": from_ts,
                "to": to_ts,
            },
            "page": {"limit": limit},
            "sort": "-timestamp",
        }
        resp = self._request("POST", f"{self._base()}/api/v2/logs/events/search", payload)
        return [compact_log(e) for e in (resp.get("data") or [])]

    def logs_aggregate(
        self,
        query: str,
        from_ts: str,
        to_ts: str,
        *,
        group_by: list[str],
        compute: str = "count",
    ) -> list[AggregateRow]:
        _window_guard(from_ts, to_ts)
        payload = {
            "filter": {"query": query, "from": from_ts, "to": to_ts},
            "compute": [{"aggregation": compute, "type": "total"}],
            "group_by": [{"facet": f, "limit": 20, "sort": {"type": "measure", "order": "desc", "aggregation": compute}} for f in group_by],
        }
        resp = self._request("POST", f"{self._base()}/api/v2/logs/analytics/aggregate", payload)
        return _parse_aggregate(resp)

    def apm_search(
        self, query: str, from_ts: str, to_ts: str, *, limit: int = DEFAULT_LIMIT
    ) -> list[CompactSpan]:
        limit = min(limit, MAX_LIMIT)
        _window_guard(from_ts, to_ts)
        # Spans v2 uses JSON:API envelope (data.attributes), unlike logs which is flat
        payload = {
            "data": {
                "attributes": {
                    "filter": {"query": query, "from": from_ts, "to": to_ts},
                    "page": {"limit": limit},
                    "sort": "-timestamp",
                },
                "type": "search_request",
            }
        }
        resp = self._request("POST", f"{self._base()}/api/v2/spans/events/search", payload)
        return [compact_span(e) for e in (resp.get("data") or [])]

    def apm_search_all(
        self, query: str, from_ts: str, to_ts: str, *, max_spans: int = 500
    ) -> list[CompactSpan]:
        """Fetch all pages of spans up to max_spans (default 500 = 10 pages)."""
        _window_guard(from_ts, to_ts)
        url = f"{self._base()}/api/v2/spans/events/search"
        results: list[CompactSpan] = []
        cursor: str | None = None

        while len(results) < max_spans:
            page: dict[str, int | str] = {"limit": MAX_LIMIT}
            if cursor:
                page["cursor"] = cursor
            payload = {
                "data": {
                    "attributes": {
                        "filter": {"query": query, "from": from_ts, "to": to_ts},
                        "page": page,
                        "sort": "-timestamp",
                    },
                    "type": "search_request",
                }
            }
            resp = self._request("POST", url, payload) or {}
            batch = resp.get("data") or []
            results.extend(compact_span(e) for e in batch)
            cursor = ((resp.get("meta") or {}).get("page") or {}).get("after")
            if not cursor or len(batch) < MAX_LIMIT:
                break

        return results

    def endpoint_report_spans(
        self,
        resource: str,
        from_ts: str,
        to_ts: str,
        *,
        service: str | None = None,
        sample: int = 5,
    ) -> tuple[list[CompactSpan], int]:
        query = f'resource_name:"{resource}"'
        if service:
            query += f" service:{service}"
        entry_spans = self.apm_search(query, from_ts, to_ts, limit=MAX_LIMIT)
        trace_ids = list(dict.fromkeys(s.trace_id for s in entry_spans if s.trace_id))[:sample]
        if not trace_ids:
            return [], 0
        all_spans: list[CompactSpan] = []
        for tid in trace_ids:
            all_spans.extend(self.apm_search_all(f"trace_id:{tid}", from_ts, to_ts))
        return all_spans, len(trace_ids)

    def apm_aggregate(
        self,
        query: str,
        from_ts: str,
        to_ts: str,
        *,
        group_by: list[str],
        compute: str = "count",
    ) -> list[AggregateRow]:
        _window_guard(from_ts, to_ts)
        payload = {
            "data": {
                "attributes": {
                    "filter": {"query": query, "from": from_ts, "to": to_ts},
                    "compute": [{"aggregation": compute, "type": "total"}],
                    "group_by": [{"facet": f, "limit": 20, "sort": {"type": "measure", "order": "desc", "aggregation": compute}} for f in group_by],
                },
                "type": "aggregate_request",
            }
        }
        resp = self._request("POST", f"{self._base()}/api/v2/spans/analytics/aggregate", payload)
        return _parse_aggregate(resp)

    @classmethod
    def from_env(cls) -> "DatadogClient":
        site = os.getenv("DD_SITE", "datadoghq.com")
        api_key = os.getenv("DD_API_KEY", "")
        app_key = os.getenv("DD_APP_KEY", "")
        if not api_key:
            raise DatadogError("DD_API_KEY not set. Export it before using zammadog.")
        if not app_key:
            raise DatadogError("DD_APP_KEY not set. Export it before using zammadog.")
        return cls(site=site, api_key=api_key, app_key=app_key)


def _parse_aggregate(resp: dict) -> list[AggregateRow]:
    """Parse both logs aggregate (data.buckets) and spans aggregate (data[].attributes) formats."""
    data = resp.get("data") or {}
    rows = []

    if isinstance(data, list):
        # Spans aggregate: data is a list of {type, id, attributes: {by, compute}}
        for item in data:
            attrs = item.get("attributes") or {}
            by = {k: str(v) for k, v in (attrs.get("by") or {}).items()}
            computes = attrs.get("compute") or {}
            value = float(list(computes.values())[0]) if computes else 0.0
            rows.append(AggregateRow(groups=by, value=value))
    else:
        # Logs aggregate: data is {buckets: [{by, computes}]}
        for bucket in (data.get("buckets") or []):
            by = {k: str(v) for k, v in (bucket.get("by") or {}).items()}
            computes = bucket.get("computes") or {}
            value = float(list(computes.values())[0]) if computes else 0.0
            rows.append(AggregateRow(groups=by, value=value))

    return rows
