---
name: zammadog
description: >
  Use zammadog to query Datadog Logs and APM from the CLI or Python. Invoke this skill
  whenever the user wants to investigate production incidents, query Datadog logs or
  traces, parse Datadog URLs from specs/tickets, or fetch evidence from Datadog for
  debugging — even if they just paste a Datadog link and ask "what's happening here?"
  Also trigger when the user asks to "grep Datadog", "check the logs in DD", or "look
  at the APM traces" without specifying a tool.
---

# zammadog

`zammadog` is the token-friendly Datadog CLI/library built into this repo. It fetches
logs and APM spans, compacts them aggressively (~150 B per event), and outputs
column-aligned tables that are easy to read or pipe into further analysis.

## When to reach for it

- A Datadog URL appears in a spec, ticket, or user message → `zammadog from-url <url>`
- User wants log counts/patterns → `zammadog logs aggregate`
- User wants recent error samples → `zammadog logs search`
- User wants slow traces or a specific trace → `zammadog apm trace <id>` / `from-url`
- User wants N+1 queries, repeated calls, or timing breakdown of a trace → `zammadog apm trace <id> --stats`
- User wants to analyze what a specific endpoint calls internally (across multiple traces) → `zammadog apm endpoint-report <resource> --service <svc>`
- Orchestrator pre-fetches evidence: see `src/zammadog/evidence.py:gather_evidence()`

## Auth

Reads from environment. Must be set before any call:

```bash
export DD_API_KEY=...
export DD_APP_KEY=...
export DD_SITE=datadoghq.com   # or datadoghq.eu
```

If keys are missing, `zammadog` exits 1 with a clear message. Check with:

```bash
zammadog --version   # confirms install; no auth needed
```

## CLI quick reference

### From a Datadog URL (most common)

```bash
zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-foo+status%3Aerror&from_ts=now-1h&to_ts=now"
```

Parses the URL, classifies it (logs / apm-search / apm-trace / apm-services), fetches
aggregate + sample, prints a compact evidence block. Works for any Datadog app URL.

`apm-services` (Watchdog/services view) and `unknown` kinds are skipped automatically — no actionable query to run.

### Log search

```bash
zammadog logs search --query "service:ms-foo status:error" --from now-30m --limit 10
zammadog logs search --query "service:ms-foo" --from 2026-05-05T10:00:00Z --to 2026-05-05T11:00:00Z --json
```

### Log aggregation (counts)

```bash
zammadog logs aggregate --query "service:ms-payments" --group-by "service,status" --from now-1h
zammadog logs aggregate --query "@http.status_code:[500 TO 599]" --group-by "service,@http.path" --from now-2h
# Non-default aggregation (sum, avg, min, max, pc95, etc.)
zammadog logs aggregate --query "service:ms-payments" --group-by "service" --compute "avg:@duration"
```

Each facet returns up to 20 buckets (top-N by the chosen aggregation). Narrow the query if you need detail past the top 20.

### APM span search

```bash
zammadog apm search --query "service:ms-orders @duration:>1000000000" --from now-1h --limit 25
zammadog apm search --query "trace_id:abc123def456" --limit 50
```

### APM full trace analysis (auto-paginates all spans)

```bash
# Grouped count — spot N+1 queries and repeated calls
zammadog apm trace <trace_id> --from now-24h

# + min/max/avg duration per group — spot slow repeated calls
zammadog apm trace <trace_id> --from now-24h --stats

# Raw JSON for custom processing
zammadog apm trace <trace_id> --from now-24h --json
```

Fetches up to 500 spans across all pages automatically. No curl needed.

### APM endpoint report (cross-trace analysis)

Samples N recent traces for an endpoint and shows what it calls internally, with call frequency and timing stats.

```bash
# Text table (default)
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10

# Self-contained HTML — sortable table grouped by HTTP Calls / DB+Cache / Other, CSS charts, dark mode
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --html --out report.html

# AI-friendly markdown — writes to ~/.claude/tmp/er_<hash>.md, prints path, delete after read
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --ai

# Multiple endpoints in one run
zammadog apm endpoint-report \
  --service my-svc --from now-24h --sample 5 \
  --endpoints \
    "POST /my-svc/v1/foo" \
    "POST /my-svc/v1/bar"
```

Output columns: `CALLS/TR` (avg calls per trace), `TOTAL`, `SVC`, `OP`, `RESOURCE`, `MIN`, `MAX`, `AVG` (ms).
`CALLS/TR > 1` = N+1 candidate.

**`--ai` workflow**: run with `--ai`, read the returned path, parse Issues + Service Breakdown sections first, then All Groups if needed. Delete file after reading: `rm <path>`.

`--html`, `--ai`, and `--json` are mutually exclusive — picking more than one exits with code 2.

### APM aggregation

```bash
zammadog apm aggregate --query "service:ms-foo" --group-by "service,resource" --from now-1h
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--from` | `now-1h` | Start time (relative or RFC3339) |
| `--to` | `now` | End time |
| `--limit` | `25` | Max rows (capped at 50) |
| `--group-by` | required | Comma-separated facets for aggregate |
| `--json` | off | Emit compact JSON instead of table |
| `--compute` | `count` | `logs/apm aggregate` — aggregation expression (e.g. `avg:@duration`, `sum:@bytes`) |
| `--stats` | off | `apm trace` only — show min/max/avg duration per group |
| `--service` | none | `apm endpoint-report` — filter by service |
| `--sample` | `5` | `apm endpoint-report` — number of traces to sample |
| `--endpoints` | none | `apm endpoint-report` — multiple resources in one run |
| `--html` | off | `apm endpoint-report` — self-contained sortable HTML report |
| `--ai` | off | `apm endpoint-report` — compact markdown to `~/.claude/tmp/`, prints path |
| `--out PATH` | stdout | `apm endpoint-report` — write to file instead of stdout |

## Output format

Default (table) — low token cost, human-readable:

```
TS                      SVC           STATUS    TRACE_ID            MSG
2026-05-05T12:34:56Z    ms-foo        error     abc123…             NullPointerException at FooService.bar:42…
```

`--json` — structured, pipeable, useful for `jq` post-processing.

## Python API

Import directly for orchestrator or scripting use:

```python
from zammadog import DatadogClient, extract_datadog_links, gather_evidence, DatadogError

# From env
client = DatadogClient.from_env()

# Or explicit
client = DatadogClient(site="datadoghq.com", api_key="...", app_key="...")

# Search
logs = client.logs_search("service:ms-foo status:error", "now-30m", "now", limit=10)
for log in logs:
    print(log.ts, log.svc, log.status, log.msg)

# Aggregate
rows = client.logs_aggregate("service:ms-foo", "now-1h", "now", group_by=["service", "status"])
for row in rows:
    print(row.groups, row.value)

# Full trace — auto-paginates (default cap: 500 spans)
spans = client.apm_search_all("trace_id:abc123", "now-24h", "now")
spans = client.apm_search_all("trace_id:abc123", "now-24h", "now", max_spans=1000)

# From a URL string (orchestrator pattern)
links = extract_datadog_links(spec_text)
for i, link in enumerate(links, 1):
    block = gather_evidence(client, link, link_num=i)
    print(block)
```

## Nota: error details en spans

La tabla de spans incluye columna `ERROR_TYPE` (ej. `com.example.rest.exception.ApiRestException`). El stack trace completo no se muestra — si lo necesitás, buscá los logs del mismo `trace_id`:

```bash
zammadog logs search --query "trace_id:<id>" --from now-1h --limit 10
```

## Hard limits (enforced by client)

| Limit | Value |
|-------|-------|
| Max rows per search | 50 |
| Max time window | 24 h |
| HTTP timeout | 15 s |
| 5xx retries | 2 attempts, exponential backoff |

Requests that exceed the window limit raise `DatadogError` immediately — narrow the `--from`/`--to` range.

## Typical investigation workflow

1. **Get the big picture** — aggregate to see where errors concentrate:
   ```bash
   zammadog logs aggregate --query "status:error" --group-by "service,status" --from now-2h
   ```

2. **Drill into the noisy service** — sample recent errors:
   ```bash
   zammadog logs search --query "service:ms-foo status:error" --from now-30m --limit 25
   ```

3. **Full trace analysis** — all spans grouped, with timing breakdown:
   ```bash
   zammadog apm trace <id> --from now-24h --stats
   ```

4. **Endpoint internals** — what does this endpoint call, how often, how slow:
   ```bash
   zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h
   ```

5. **Follow error details** — get full message from logs:
   ```bash
   zammadog logs search --query "trace_id:<id>" --from now-1h --limit 10
   ```

6. **Paste a URL from a ticket** — let `from-url` do the routing:
   ```bash
   zammadog from-url "<url-from-jira-or-slack>"
   ```

## Install

```bash
# One-liner (detects uv or pip automatically)
cd /path/to/zammadog-cli && ./install.sh

# Manual
pip install -e /path/to/zammadog-cli
# or
uv pip install /path/to/zammadog-cli
```

No runtime dependencies — stdlib only.
