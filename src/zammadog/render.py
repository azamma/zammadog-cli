"""Table formatters for CLI output and evidence blocks."""
from __future__ import annotations
import html as _html
import json
from collections import Counter
from datetime import datetime, timezone
from .compact import AggregateRow, CompactLog, CompactSpan

_COL_SEP = "  "

_HTTP_OPS = {"servlet.request", "okhttp.request", "spring.handler"}
_DB_OPS = {"mysql.query", "redis.query", "repository.operation", "database.connection", "resilience4j"}


def _classify_op(op: str) -> str:
    if op in _HTTP_OPS:
        return "HTTP Calls"
    if op in _DB_OPS:
        return "DB / Cache"
    return "Other"


def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return "-"
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def render_logs_table(rows: list[CompactLog]) -> str:
    if not rows:
        return "(no results)"
    header = f"{'TS':<22}{_COL_SEP}{'SVC':<12}{_COL_SEP}{'STATUS':<8}{_COL_SEP}{'TRACE_ID':<18}{_COL_SEP}MSG"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{_truncate(r.ts, 22):<22}{_COL_SEP}"
            f"{_truncate(r.svc, 12):<12}{_COL_SEP}"
            f"{_truncate(r.status, 8):<8}{_COL_SEP}"
            f"{_truncate(r.trace_id, 18):<18}{_COL_SEP}"
            f"{_truncate(r.msg, 80)}"
        )
    return "\n".join(lines)


def render_spans_table(rows: list[CompactSpan]) -> str:
    if not rows:
        return "(no results)"
    header = f"{'TS':<22}{_COL_SEP}{'SVC':<12}{_COL_SEP}{'RESOURCE':<24}{_COL_SEP}{'DUR_MS':<8}{_COL_SEP}{'STATUS':<8}{_COL_SEP}{'TRACE_ID':<18}{_COL_SEP}ERROR_TYPE"
    lines = [header, "-" * len(header)]
    for r in rows:
        dur = str(r.duration_ms) if r.duration_ms is not None else "-"
        lines.append(
            f"{_truncate(r.ts, 22):<22}{_COL_SEP}"
            f"{_truncate(r.svc, 12):<12}{_COL_SEP}"
            f"{_truncate(r.resource, 24):<24}{_COL_SEP}"
            f"{dur:<8}{_COL_SEP}"
            f"{_truncate(r.status, 8):<8}{_COL_SEP}"
            f"{_truncate(r.trace_id, 18):<18}{_COL_SEP}"
            f"{_truncate(r.error_type, 50)}"
        )
    return "\n".join(lines)


def render_trace_summary(spans: list[CompactSpan]) -> str:
    if not spans:
        return "(no spans)"
    counts: Counter[tuple[str, str, str]] = Counter()
    for s in spans:
        counts[(s.svc or "-", s.op or "-", s.resource or "-")] += 1
    total = sum(counts.values())
    lines = [f"Total spans: {total}", f"{'COUNT':<7}  {'SVC':<20}  {'OP':<30}  RESOURCE", "-" * 100]
    for (svc, op, res), c in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"[{c:<4}]  {svc:<20}  {op:<30}  {res[:60]}")
    return "\n".join(lines)


def render_trace_stats(spans: list[CompactSpan]) -> str:
    if not spans:
        return "(no spans)"
    groups: dict[tuple[str, str, str], list[int]] = {}
    for s in spans:
        key = (s.svc or "-", s.op or "-", s.resource or "-")
        groups.setdefault(key, [])
        if s.duration_ms is not None:
            groups[key].append(s.duration_ms)
        else:
            groups.setdefault(key, [])
    total = len(spans)
    hdr = f"Total spans: {total}\n{'SVC':<22}  {'OP':<30}  {'RESOURCE':<48}  {'N':>4}  {'MIN_ms':>7}  {'MAX_ms':>7}  {'AVG_ms':>7}"
    lines = [hdr, "-" * 130]
    for (svc, op, res), durs in sorted(groups.items(), key=lambda x: -len(x[1])):
        n = len(durs)
        mn = str(min(durs)) if durs else "-"
        mx = str(max(durs)) if durs else "-"
        av = str(int(sum(durs) / len(durs))) if durs else "-"
        lines.append(f"{svc:<22}  {op:<30}  {res[:48]:<48}  {n:>4}  {mn:>7}  {mx:>7}  {av:>7}")
    return "\n".join(lines)


def _group_spans_for_report(spans: list[CompactSpan], n_traces: int) -> list[dict]:
    """Group spans by (svc, op, resource) and compute per-group stats."""
    groups: dict[tuple[str, str, str], list[int]] = {}
    per_trace: dict[tuple[str, str, str], set[str | None]] = {}
    for s in spans:
        key = (s.svc or "-", s.op or "-", s.resource or "-")
        groups.setdefault(key, [])
        per_trace.setdefault(key, set())
        if s.duration_ms is not None:
            groups[key].append(s.duration_ms)
        per_trace[key].add(s.trace_id)

    rows = []
    for key, durs in sorted(groups.items(), key=lambda x: -len(x[1])):
        svc, op, res = key
        total = len(durs)
        cpt = round(total / n_traces, 1) if n_traces else 0
        rows.append({
            "svc": svc,
            "op": op,
            "resource": res,
            "total": total,
            "cpt": cpt,
            "min": min(durs) if durs else None,
            "max": max(durs) if durs else None,
            "avg": int(sum(durs) / len(durs)) if durs else None,
            "group": _classify_op(op),
        })
    return rows


def render_endpoint_report(
    spans: list[CompactSpan], n_traces: int, endpoint: str, service: str | None
) -> str:
    if not spans:
        return f"(no spans found for {endpoint!r})"
    svc_line = f"  service: {service}" if service else ""
    header = f"Endpoint: {endpoint}{svc_line}  |  {n_traces} trace(s) sampled  |  {len(spans)} total spans\n"
    header += f"{'CALLS/TR':>8}  {'TOTAL':>5}  {'SVC':<20}  {'OP':<28}  {'RESOURCE':<46}  {'MIN':>6}  {'MAX':>6}  {'AVG':>6}"
    lines = [header, "-" * 135]

    for row in _group_spans_for_report(spans, n_traces):
        cpt = f"{row['cpt']:.1f}" if n_traces else "-"
        mn = str(row["min"]) if row["min"] is not None else "-"
        mx = str(row["max"]) if row["max"] is not None else "-"
        av = str(row["avg"]) if row["avg"] is not None else "-"
        lines.append(
            f"{cpt:>8}  {row['total']:>5}  {row['svc']:<20}  {row['op']:<28}  {row['resource'][:46]:<46}  {mn:>6}  {mx:>6}  {av:>6}"
        )
    return "\n".join(lines)


def render_endpoint_report_ai(
    spans: list[CompactSpan],
    n_traces: int,
    endpoint: str,
    service: str | None,
    from_ts: str,
    to_ts: str,
) -> str:
    if not spans:
        return f"# Endpoint Report: {endpoint}\n\n> No spans found.\n"

    rows = _group_spans_for_report(spans, n_traces)
    total_spans = len(spans)

    root = next(
        (r for r in rows if r["resource"] == endpoint and r["op"] == "servlet.request"), None
    )
    endpoint_ms = root["avg"] if root and root["avg"] is not None else "?"
    svc_str = f" · service: {service}" if service else ""

    lines = [
        f"# Endpoint Report: {endpoint}",
        f"**{from_ts} → {to_ts}** · {n_traces} trace(s) · {total_spans} spans · {endpoint_ms}ms{svc_str}",
        "",
    ]

    n1_rows = sorted(
        [r for r in rows if r["cpt"] > 1],
        key=lambda r: -(r["cpt"] * (r["avg"] or 0)),
    )
    slow_rows = sorted(
        [r for r in rows if r["cpt"] <= 1 and (r["avg"] or 0) >= 50],
        key=lambda r: -(r["avg"] or 0),
    )

    if n1_rows or slow_rows:
        lines.append("## Issues")

    if n1_rows:
        lines.append("\n### N+1 Calls (calls/trace > 1)")
        lines.append("| calls/tr | impact_ms | svc | op | resource |")
        lines.append("|----------|-----------|-----|----|----------|")
        for r in n1_rows:
            impact = round(r["cpt"] * (r["avg"] or 0))
            lines.append(f"| {r['cpt']} | {impact} | {r['svc']} | {r['op']} | {r['resource'][:100]} |")

    if slow_rows:
        lines.append("\n### Slow Single Calls (avg ≥ 50ms)")
        lines.append("| avg_ms | max_ms | svc | op | resource |")
        lines.append("|--------|--------|-----|----|----------|")
        for r in slow_rows[:15]:
            lines.append(f"| {r['avg']} | {r['max']} | {r['svc']} | {r['op']} | {r['resource'][:100]} |")

    svc_totals: dict[str, dict] = {}
    for r in rows:
        s = r["svc"]
        if s not in svc_totals:
            svc_totals[s] = {"spans": 0, "impact": 0}
        svc_totals[s]["spans"] += r["total"]
        svc_totals[s]["impact"] += round(r["cpt"] * (r["avg"] or 0))

    lines.append("\n## Service Breakdown")
    lines.append("| svc | total_spans | est_impact_ms |")
    lines.append("|-----|-------------|---------------|")
    for svc, data in sorted(svc_totals.items(), key=lambda x: -x[1]["impact"]):
        lines.append(f"| {svc} | {data['spans']} | {data['impact']} |")

    lines.append("\n## All Groups")
    lines.append("| calls/tr | total | svc | op | resource | min | max | avg |")
    lines.append("|----------|-------|-----|----|----------|-----|-----|-----|")
    for r in rows:
        mn = str(r["min"]) if r["min"] is not None else "-"
        mx = str(r["max"]) if r["max"] is not None else "-"
        av = str(r["avg"]) if r["avg"] is not None else "-"
        lines.append(
            f"| {r['cpt']} | {r['total']} | {r['svc']} | {r['op']} | {r['resource'][:100]} | {mn} | {mx} | {av} |"
        )

    return "\n".join(lines)


def render_endpoint_report_html(
    spans: list[CompactSpan],
    n_traces: int,
    endpoint: str,
    service: str | None,
    from_ts: str,
    to_ts: str,
) -> str:
    from zammadog.cli import VERSION as _ver

    e = _html.escape
    rows = _group_spans_for_report(spans, n_traces)
    total_spans = len(spans)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # KPI calculations
    n_plus_one = sum(1 for r in rows if r["cpt"] > 1)
    slowest = max(rows, key=lambda r: r["avg"] or 0, default=None)
    total_fanout = sum((r["avg"] or 0) * r["cpt"] for r in rows)
    svc_set = {r["svc"] for r in rows if r["svc"] != "-"}
    external_svc_count = len(svc_set - ({service} if service else set()))

    # Prepare JSON for client-side table
    PAGE_THRESHOLD = 500
    agg_json = json.dumps([{
        "svc": r["svc"], "op": r["op"], "resource": r["resource"],
        "total": r["total"], "cpt": r["cpt"],
        "min": r["min"], "max": r["max"], "avg": r["avg"],
        "group": r["group"],
    } for r in rows])

    raw_json = json.dumps([{
        "ts": s.ts, "svc": s.svc or "-", "op": s.op or "-",
        "resource": s.resource or "-",
        "dur_ms": s.duration_ms, "status": s.status or "-",
        "trace_id": s.trace_id or "", "error_type": s.error_type or "",
    } for s in spans])

    n_plus_badge = f'<span class="badge badge-red">{n_plus_one}</span>' if n_plus_one else '<span class="badge badge-ok">0</span>'
    slowest_txt = f"{e(slowest['resource'][:40])} ({slowest['avg']} ms)" if slowest and slowest["avg"] is not None else "—"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Endpoint Report: {e(endpoint)}</title>
<style>
:root {{
  --bg: #0f1117; --bg2: #1a1d27; --bg3: #252836;
  --border: #2e3149; --text: #e2e8f0; --muted: #6b7280;
  --red: #ef4444; --amber: #f59e0b; --green: #22c55e; --blue: #3b82f6;
  --accent: #818cf8;
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #f8fafc; --bg2: #ffffff; --bg3: #f1f5f9;
    --border: #e2e8f0; --text: #1e293b; --muted: #64748b;
  }}
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: ui-sans-serif,system-ui,-apple-system,sans-serif; font-size: 14px; line-height: 1.5; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* header */
.header {{ background: var(--bg2); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
.header h1 {{ font-size: 18px; font-weight: 700; flex: 1; min-width: 200px; word-break: break-all; }}
.badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
.badge-red {{ background: rgba(239,68,68,.15); color: var(--red); border: 1px solid rgba(239,68,68,.3); }}
.badge-amber {{ background: rgba(245,158,11,.15); color: var(--amber); border: 1px solid rgba(245,158,11,.3); }}
.badge-ok {{ background: rgba(34,197,94,.15); color: var(--green); border: 1px solid rgba(34,197,94,.3); }}
.badge-blue {{ background: rgba(59,130,246,.15); color: var(--blue); border: 1px solid rgba(59,130,246,.3); }}
.meta {{ color: var(--muted); font-size: 12px; }}

/* layout */
.main {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

/* KPI cards */
.cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 12px; margin-bottom: 24px; }}
.card {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.card-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 6px; }}
.card-value {{ font-size: 20px; font-weight: 700; }}

/* section titles */
.section-title {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 8px; margin-top: 24px; }}

/* filter bar */
.filter-bar {{ display: flex; gap: 8px; margin-bottom: 8px; }}
.filter-bar input {{ flex: 1; background: var(--bg3); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
.filter-bar input:focus {{ outline: 2px solid var(--accent); }}
.filter-bar button {{ background: var(--bg3); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px; white-space: nowrap; }}
.filter-bar button:hover {{ border-color: var(--accent); color: var(--accent); }}

/* group header row */
.group-hdr td {{ background: var(--bg3); padding: 8px 10px; font-size: 12px; cursor: pointer; border-top: 2px solid var(--border); user-select: none; }}
.group-hdr:hover td {{ background: var(--bg2); }}

/* table */
.tbl-wrap {{ overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead th {{ background: var(--bg3); padding: 8px 10px; text-align: left; font-weight: 600; white-space: nowrap; cursor: pointer; user-select: none; border-bottom: 1px solid var(--border); }}
thead th:hover {{ color: var(--accent); }}
thead th::after {{ content: " "; }}
thead th.asc::after {{ content: " ↑"; }}
thead th.desc::after {{ content: " ↓"; }}
tbody tr {{ border-bottom: 1px solid var(--border); transition: background .1s; }}
tbody tr:last-child {{ border-bottom: none; }}
tbody tr:hover {{ background: var(--bg3); }}
tbody td {{ padding: 7px 10px; white-space: nowrap; max-width: 320px; overflow: hidden; text-overflow: ellipsis; }}
.row-n1 {{ background: rgba(239,68,68,.06); }}
.row-slow {{ background: rgba(245,158,11,.06); }}

/* pagination */
.pagination {{ display: flex; gap: 8px; margin-top: 8px; align-items: center; }}
.pagination button {{ background: var(--bg3); border: 1px solid var(--border); color: var(--text); border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; }}
.pagination button:disabled {{ opacity: .4; cursor: default; }}
.pagination .page-info {{ color: var(--muted); font-size: 12px; }}

/* charts */
.charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; margin-bottom: 8px; }}
.chart-card {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.chart-card h3 {{ font-size: 13px; font-weight: 600; margin-bottom: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
canvas {{ max-width: 100%; }}

/* details/summary */
details {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
details summary {{ padding: 12px 16px; cursor: pointer; font-weight: 600; user-select: none; }}
details summary:hover {{ background: var(--bg3); }}
details[open] summary {{ border-bottom: 1px solid var(--border); }}
.raw-wrap {{ padding: 12px 16px; }}

/* footer */
footer {{ text-align: center; color: var(--muted); font-size: 11px; padding: 24px; border-top: 1px solid var(--border); margin-top: 24px; }}

@media print {{
  .filter-bar, .pagination {{ display: none; }}
  details {{ display: block; }}
}}
</style>
</head>
<body>

<div class="header">
  <div style="flex:1">
    <h1>{e(endpoint)}</h1>
    <div class="meta">
      {"<span class='badge badge-blue'>" + e(service) + "</span>&nbsp;&nbsp;" if service else ""}
      {e(from_ts)} → {e(to_ts)} &nbsp;·&nbsp; {n_traces} trace(s) sampled &nbsp;·&nbsp; {total_spans} spans
    </div>
  </div>
  <button onclick="window.print()" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px;">Print</button>
</div>

<div class="main">

<!-- KPI cards -->
<div class="cards">
  <div class="card">
    <div class="card-label">N+1 Candidates</div>
    <div class="card-value">{n_plus_badge}</div>
    <div class="meta" style="margin-top:4px">spans where CALLS/TR &gt; 1</div>
  </div>
  <div class="card">
    <div class="card-label">Slowest Call (avg)</div>
    <div class="card-value" style="font-size:14px;word-break:break-all">{e(slowest_txt)}</div>
  </div>
  <div class="card">
    <div class="card-label">Total Time Fan-out</div>
    <div class="card-value">{int(total_fanout)} ms</div>
    <div class="meta" style="margin-top:4px">Σ avg × calls/tr (endpoint cost proxy)</div>
  </div>
  <div class="card">
    <div class="card-label">External Services</div>
    <div class="card-value">{external_svc_count}</div>
    <div class="meta" style="margin-top:4px">distinct services ≠ {e(service or "—")}</div>
  </div>
</div>

<!-- Aggregated table -->
<div class="section-title">Aggregated span breakdown</div>
<div class="filter-bar">
  <input type="text" id="agg-filter" placeholder="Filter rows…" oninput="filterTable('agg',this.value)">
  <button id="group-toggle" onclick="toggleGroupMode()">Flat view</button>
</div>
<div class="tbl-wrap">
  <table id="agg-table">
    <thead>
      <tr>
        <th onclick="sortTable('agg',0,'num')">CALLS/TR</th>
        <th onclick="sortTable('agg',1,'num')">TOTAL</th>
        <th onclick="sortTable('agg',2,'str')">SVC</th>
        <th onclick="sortTable('agg',3,'str')">OP</th>
        <th onclick="sortTable('agg',4,'str')">RESOURCE</th>
        <th onclick="sortTable('agg',5,'num')">MIN ms</th>
        <th onclick="sortTable('agg',6,'num')">MAX ms</th>
        <th onclick="sortTable('agg',7,'num')">AVG ms</th>
      </tr>
    </thead>
    <tbody id="agg-tbody"></tbody>
  </table>
</div>
<div class="pagination" id="agg-pag"></div>

<!-- Charts -->
<div class="section-title">Latency &amp; call volume</div>
<div class="charts-grid">
  <div class="chart-card">
    <h3>Latency breakdown — top 15 by avg (ms)</h3>
    <div id="chart-latency"></div>
  </div>
  <div class="chart-card">
    <h3>Calls per trace — top 15</h3>
    <div id="chart-cpt"></div>
  </div>
  <div class="chart-card">
    <h3>Spans by service</h3>
    <div id="chart-svc"></div>
  </div>
</div>

<!-- Raw spans -->
<details>
  <summary>Raw spans ({total_spans} total{" — paginated 50/page" if total_spans > PAGE_THRESHOLD else ""})</summary>
  <div class="raw-wrap">
    <div class="filter-bar">
      <input type="text" id="raw-filter" placeholder="Filter raw spans…" oninput="filterTable('raw',this.value)">
    </div>
    <div class="tbl-wrap">
      <table id="raw-table">
        <thead>
          <tr>
            <th onclick="sortTable('raw',0,'str')">TS</th>
            <th onclick="sortTable('raw',1,'str')">SVC</th>
            <th onclick="sortTable('raw',2,'str')">OP</th>
            <th onclick="sortTable('raw',3,'str')">RESOURCE</th>
            <th onclick="sortTable('raw',4,'num')">DUR_MS</th>
            <th onclick="sortTable('raw',5,'str')">STATUS</th>
            <th onclick="sortTable('raw',6,'str')">TRACE_ID</th>
            <th onclick="sortTable('raw',7,'str')">ERROR_TYPE</th>
          </tr>
        </thead>
        <tbody id="raw-tbody"></tbody>
      </table>
    </div>
    <div class="pagination" id="raw-pag"></div>
  </div>
</details>

<footer>
  Generated by zammadog {e(_ver)} &nbsp;·&nbsp; {e(generated_at)}
</footer>

</div><!-- /main -->

<script type="application/json" id="agg-data">{agg_json}</script>
<script type="application/json" id="raw-data">{raw_json}</script>

<script>
// ── data ────────────────────────────────────────────────────────────────────
const AGG = JSON.parse(document.getElementById('agg-data').textContent);
const RAW = JSON.parse(document.getElementById('raw-data').textContent);
const PAGE = 50;
const GROUP_ORDER = ['HTTP Calls', 'DB / Cache', 'Other'];

// ── table state ─────────────────────────────────────────────────────────────
const state = {{
  agg: {{ data: AGG.slice(), filtered: AGG.slice(), page: 0, sortCol: -1, sortDir: 1 }},
  raw: {{ data: RAW.slice(), filtered: RAW.slice(), page: 0, sortCol: -1, sortDir: 1 }},
}};
let groupedMode = true;
const collapsedGroups = new Set();

// ── rendering ────────────────────────────────────────────────────────────────
function esc(s) {{
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function renderAggRow(r, extraAttr) {{
  const n1 = r.cpt > 1;
  const slow = r.avg != null && r.avg > 500;
  const cls = n1 ? 'row-n1' : slow ? 'row-slow' : '';
  return `<tr class="${{cls}}" ${{extraAttr || ''}}>
    <td>${{r.cpt}}</td><td>${{r.total}}</td>
    <td>${{esc(r.svc)}}</td><td>${{esc(r.op)}}</td><td title="${{esc(r.resource)}}">${{esc(r.resource)}}</td>
    <td>${{r.min ?? '-'}}</td><td>${{r.max ?? '-'}}</td><td>${{r.avg ?? '-'}}</td>
  </tr>`;
}}

function renderRawRow(r) {{
  const tid = r.trace_id
    ? `<a href="https://app.datadoghq.com/apm/trace/${{esc(r.trace_id)}}" target="_blank" rel="noopener">${{esc(r.trace_id.slice(0,16))}}</a>`
    : '-';
  return `<tr>
    <td>${{esc(r.ts)}}</td><td>${{esc(r.svc)}}</td><td>${{esc(r.op)}}</td>
    <td title="${{esc(r.resource)}}">${{esc(r.resource)}}</td>
    <td>${{r.dur_ms ?? '-'}}</td><td>${{esc(r.status)}}</td>
    <td>${{tid}}</td><td>${{esc(r.error_type)}}</td>
  </tr>`;
}}

// ── grouped rendering (agg only) ─────────────────────────────────────────────
function renderGroupedAgg(data) {{
  const tbody = document.getElementById('agg-tbody');
  document.getElementById('agg-pag').innerHTML = '';
  const buckets = {{}};
  GROUP_ORDER.forEach(g => buckets[g] = []);
  data.forEach(r => {{ const g = r.group || 'Other'; (buckets[g] = buckets[g] || []).push(r); }});
  let html = '';
  GROUP_ORDER.forEach(g => {{
    const rows = buckets[g];
    if (!rows || !rows.length) return;
    const collapsed = collapsedGroups.has(g);
    const gid = 'gc-' + g.replace(/ [/] /g,'_').replace(/ /g,'_');
    html += `<tr class="group-hdr" onclick="toggleGroupCollapse('${{g}}','${{gid}}')">
      <td colspan="8"><span id="${{gid}}">${{collapsed ? '▶' : '▼'}}</span> <strong>${{g}}</strong> <span style="color:var(--muted);font-size:12px">(${{rows.length}} rows)</span></td>
    </tr>`;
    rows.forEach(r => {{
      const display = collapsed ? ' style="display:none"' : '';
      html += renderAggRow(r, `data-grp="${{esc(g)}}"${{display}}`);
    }});
  }});
  tbody.innerHTML = html;
}}

function toggleGroupCollapse(g, gid) {{
  if (collapsedGroups.has(g)) collapsedGroups.delete(g);
  else collapsedGroups.add(g);
  const collapsed = collapsedGroups.has(g);
  const icon = document.getElementById(gid);
  if (icon) icon.textContent = collapsed ? '▶' : '▼';
  document.querySelectorAll(`[data-grp="${{g}}"]`).forEach(row => {{
    row.style.display = collapsed ? 'none' : '';
  }});
}}

function toggleGroupMode() {{
  groupedMode = !groupedMode;
  const btn = document.getElementById('group-toggle');
  if (btn) btn.textContent = groupedMode ? 'Flat view' : 'Group by type';
  state.agg.page = 0;
  if (groupedMode) renderGroupedAgg(state.agg.filtered);
  else renderTable('agg');
}}

// ── flat rendering ────────────────────────────────────────────────────────────
function renderTable(name) {{
  if (name === 'agg' && groupedMode) {{ renderGroupedAgg(state.agg.filtered); return; }}
  const s = state[name];
  const tbody = document.getElementById(name + '-tbody');
  const pag = document.getElementById(name + '-pag');
  const start = s.page * PAGE;
  const slice = s.filtered.slice(start, start + PAGE);
  const fn = name === 'agg' ? renderAggRow : renderRawRow;
  tbody.innerHTML = slice.map(r => fn(r)).join('');
  const pages = Math.ceil(s.filtered.length / PAGE);
  if (pages <= 1) {{ pag.innerHTML = ''; return; }}
  pag.innerHTML = `
    <button onclick="goPage('${{name}}',${{s.page-1}})" ${{s.page===0?'disabled':''}}>← Prev</button>
    <span class="page-info">Page ${{s.page+1}} / ${{pages}} (${{s.filtered.length}} rows)</span>
    <button onclick="goPage('${{name}}',${{s.page+1}})" ${{s.page>=pages-1?'disabled':''}}>Next →</button>
  `;
}}

function goPage(name, p) {{
  state[name].page = p;
  renderTable(name);
}}

// ── filter ────────────────────────────────────────────────────────────────────
function filterTable(name, q) {{
  q = q.toLowerCase();
  state[name].filtered = state[name].data.filter(r =>
    Object.values(r).some(v => String(v ?? '').toLowerCase().includes(q))
  );
  state[name].page = 0;
  renderTable(name);
}}

// ── sort (switches to flat mode) ──────────────────────────────────────────────
function sortTable(name, col, type) {{
  if (name === 'agg' && groupedMode) {{
    groupedMode = false;
    const btn = document.getElementById('group-toggle');
    if (btn) btn.textContent = 'Group by type';
  }}
  const s = state[name];
  const keys = name === 'agg'
    ? ['cpt','total','svc','op','resource','min','max','avg']
    : ['ts','svc','op','resource','dur_ms','status','trace_id','error_type'];
  if (s.sortCol === col) s.sortDir *= -1;
  else {{ s.sortCol = col; s.sortDir = 1; }}
  const k = keys[col];
  s.filtered.sort((a, b) => {{
    let av = a[k] ?? '', bv = b[k] ?? '';
    if (type === 'num') {{ av = Number(av) || 0; bv = Number(bv) || 0; }}
    else {{ av = String(av).toLowerCase(); bv = String(bv).toLowerCase(); }}
    return av < bv ? -s.sortDir : av > bv ? s.sortDir : 0;
  }});
  s.page = 0;
  document.querySelectorAll('#' + name + '-table thead th').forEach((th, i) => {{
    th.className = i === col ? (s.sortDir === 1 ? 'asc' : 'desc') : '';
  }});
  renderTable(name);
}}

// ── charts (HTML bars — no canvas sizing issues) ─────────────────────────────
const SWATCH = ['#818cf8','#34d399','#f59e0b','#ef4444','#38bdf8','#a78bfa','#fb923c','#4ade80','#f472b6','#facc15'];

function hbar(label, value, maxVal, color, annotation, fullLabel) {{
  const pct = Math.max(2, Math.round((value || 0) / maxVal * 100));
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:12px">
    <div style="width:150px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);text-align:right" title="${{esc(fullLabel || label)}}">${{esc(label)}}</div>
    <div style="flex:1;min-width:60px;background:var(--bg3);border-radius:3px;height:16px;overflow:hidden">
      <div style="width:${{pct}}%;background:${{color}};height:100%;border-radius:3px;opacity:.85"></div>
    </div>
    <div style="width:150px;flex-shrink:0;font-size:11px;color:var(--muted)">${{annotation}}</div>
  </div>`;
}}

function shorten(s, n) {{ return s && s.length > n ? s.slice(0, n-1) + '…' : (s || '-'); }}

function drawLatencyChart() {{
  const el = document.getElementById('chart-latency');
  if (!el) return;
  const top = AGG.filter(r => r.avg != null).sort((a,b) => b.avg - a.avg).slice(0,15);
  if (!top.length) {{ el.innerHTML = '<p style="color:var(--muted);font-size:12px">No data</p>'; return; }}
  const maxVal = Math.max(...top.map(r => r.max || 0), 1);
  const legend = `<div style="font-size:11px;color:var(--muted);margin-bottom:10px;display:flex;gap:14px">
    <span><span style="display:inline-block;width:10px;height:10px;background:#818cf8;border-radius:2px;margin-right:4px;vertical-align:middle"></span>avg (bar width)</span>
    <span style="color:#ef4444">red = N+1</span>
    <span style="color:#f59e0b">amber = avg &gt;500ms</span>
  </div>`;
  el.innerHTML = legend + top.map(r => {{
    const color = r.cpt > 1 ? '#ef4444' : (r.avg > 500 ? '#f59e0b' : '#818cf8');
    const ann = `min <strong>${{r.min ?? '-'}}</strong> / avg <strong>${{r.avg}}</strong> / max <strong>${{r.max ?? '-'}}</strong> ms`;
    return hbar(shorten(r.resource, 22), r.avg, maxVal, color, ann, r.resource);
  }}).join('');
}}

function drawCptChart() {{
  const el = document.getElementById('chart-cpt');
  if (!el) return;
  const top = AGG.slice().sort((a,b) => b.cpt - a.cpt).slice(0,15);
  if (!top.length) {{ el.innerHTML = '<p style="color:var(--muted);font-size:12px">No data</p>'; return; }}
  const maxVal = Math.max(...top.map(r => r.cpt), 1);
  const legend = `<div style="font-size:11px;color:var(--muted);margin-bottom:10px"><span style="color:#ef4444">red = N+1 (&gt;1 call/trace)</span></div>`;
  el.innerHTML = legend + top.map(r => {{
    const color = r.cpt > 1 ? '#ef4444' : '#818cf8';
    return hbar(shorten(r.resource, 22), r.cpt, maxVal, color, `${{r.cpt}} calls/tr · ${{r.total}} total`, r.resource);
  }}).join('');
}}

function drawSvcChart() {{
  const el = document.getElementById('chart-svc');
  if (!el) return;
  const svcTotals = {{}};
  AGG.forEach(r => {{ svcTotals[r.svc] = (svcTotals[r.svc] || 0) + r.total; }});
  const entries = Object.entries(svcTotals).sort((a,b) => b[1] - a[1]);
  if (!entries.length) {{ el.innerHTML = '<p style="color:var(--muted);font-size:12px">No data</p>'; return; }}
  const maxVal = entries[0][1];
  const totalAll = entries.reduce((s,[,v]) => s+v, 0);
  el.innerHTML = entries.map(([svc, count], i) => {{
    const pct = Math.round(count/totalAll*100);
    return hbar(svc, count, maxVal, SWATCH[i % SWATCH.length], `${{count}} spans (${{pct}}%)`, svc);
  }}).join('');
}}

// ── init ──────────────────────────────────────────────────────────────────────
renderTable('agg');
renderTable('raw');
drawLatencyChart();
drawCptChart();
drawSvcChart();
</script>
</body>
</html>"""


def render_aggregate(rows: list[AggregateRow]) -> str:
    if not rows:
        return "(no results)"
    # Collect group key names
    if not rows[0].groups:
        lines = [f"{r.value:.0f}" for r in rows]
        return "\n".join(lines)
    keys = list(rows[0].groups.keys())
    col_widths = {k: max(len(k), max(len(r.groups.get(k, "-")) for r in rows)) for k in keys}
    header_parts = [f"{k:<{col_widths[k]}}" for k in keys] + ["COUNT"]
    header = _COL_SEP.join(header_parts)
    lines = [header, "-" * len(header)]
    for r in rows:
        parts = [f"{r.groups.get(k, '-'):<{col_widths[k]}}" for k in keys]
        parts.append(f"{r.value:.0f}")
        lines.append(_COL_SEP.join(parts))
    return "\n".join(lines)
