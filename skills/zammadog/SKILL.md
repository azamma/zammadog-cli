---
name: zammadog
description: >
  Token-friendly CLI/library to query observability backends — Datadog Logs & APM AND
  AWS CloudWatch Logs/Metrics — for production debugging. Use this skill whenever the user
  investigates a production incident, wants logs/errors/traces from a service or microservice,
  or pastes a Datadog link and asks "what's happening here?" — even if they don't name a tool.
  Trigger for Datadog phrasing ("grep Datadog", "check the logs in DD", "look at the APM traces")
  AND for CloudWatch/AWS phrasing: "errors in <service> in prod", "logs de <service> en producción",
  "buscá/ver los logs de <service>", "trace this request across services", "tracear este trace id",
  "grep CloudWatch", "what log group has X", "follow this trace through the microservices". When the
  user wants a service's logs or to trace a request across services, reach for this skill before
  falling back to raw aws/curl commands.
---

# zammadog

`zammadog` is the token-friendly Datadog/CloudWatch CLI/library built into this repo. It fetches
logs and APM spans from Datadog, and logs/metrics from AWS CloudWatch, compacts them aggressively (~150 B per event), and outputs
column-aligned tables that are easy to read or pipe into further analysis.

## When to reach for it

- A Datadog URL appears in a spec, ticket, or user message → `zammadog from-url <url>`
- User wants log counts/patterns → `zammadog logs aggregate`
- User wants recent error samples → `zammadog logs search`
- User wants slow traces or a specific trace → `zammadog apm trace <id>` / `from-url`
- User wants N+1 queries, repeated calls, or timing breakdown of a trace → `zammadog apm trace <id> --stats`
- User wants to analyze what a specific endpoint calls internally (across multiple traces) → `zammadog apm endpoint-report <resource> --service <svc>`
- User wants CloudWatch logs or metrics (AWS-only environments) → `zammadog cw logs-search`, `zammadog cw logs-filter`, `zammadog cw metrics`. Don't know the log group name? → `zammadog cw log-groups -p <substring>` first.
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

### CloudWatch auth

CloudWatch uses the boto3 default credential + region chain (`aws configure`, `AWS_REGION`, `AWS_PROFILE`, etc.). If the region is unresolved, zammadog exits with a clear error — do not retry, surface the error to the user.

```bash
export AWS_REGION=us-east-1
# or rely on ~/.aws/config default profile
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

### CloudWatch

**Discover the log group** when you don't know the exact name (case-sensitive substring):

```bash
zammadog cw log-groups -p my-service          # confirm the exact name
zammadog cw log-groups -p my-service --limit 50
```

**Filter a single group** (simple substring/pattern match). To grep a **trace id** the term must
be quoted — CloudWatch treats `"..."` as a substring match; unquoted it tokenises and misses:

```bash
zammadog cw logs-filter -g /aws/ecs/my-service -p ERROR --from now-1h
zammadog cw logs-filter -g /aws/ecs/my-service -p '"6a1ccbe6...trace..."' --from now-2h
```

**Trace a request across all services** — the most powerful command. One Insights query over many
groups at once, time-ordered, so the **first line is the origin service** and you can read the call
chain (cross-service HTTP hops show inline). You don't need to know the group names:

```bash
zammadog cw trace <trace_id> -G <group-substring> --from now-2h
# Output: `ts | log-group | message`, sorted ascending. Returns the FULL trace (default 300
# lines, up to 1000) — unlike the 50-row search cap, a trace is one ordered stream so it
# isn't truncated; the failing line is often deep in a long flow. Cap: 50 *groups* per query
# (Insights limit) — always pass -G to scope, or it grabs the first 50 arbitrarily.
```

If a `cw trace` looks suspiciously short or stops before the error, the trace id likely aged out of
the window (CloudWatch times are UTC and traces recur fast with new ids) — grab a fresh id and widen
`--from`. To zoom into one service's slice of a trace, `cw logs-filter -g <group> -p '"<trace_id>"'`.

**Logs Insights** — full query language (filter + stats). A `stats` query returns an aggregate table:

```bash
zammadog cw logs-search -q 'fields @timestamp,@message | filter @message like /ERROR/' -g /aws/ecs/my-service --from now-1h
zammadog cw logs-search -q 'stats count(*) by level' -g /aws/ecs/my-service --from now-1h
```

**Metrics**:

```bash
zammadog cw metrics -n AWS/Lambda -m Errors -d FunctionName=my-fn --stat Sum --period 300 --from now-3h
```

**`--parser <name>` (optional, local).** CloudWatch log output can be passed through a parser that
compacts verbose framework lines (e.g. strip MDC/trace prefixes, collapse logger FQCNs) into a lean
`ts | trace_id | msg`. The only committed parser is `example` (a template). To add your own, copy
`src/zammadog/parsers/example_parser.py` to `<name>_parser.py` in that folder, implement
`parse(rows) -> rows`, and call `register("<name>", MyParser())` — it is auto-loaded and git-ignored.

**`--report <name>` (parser-driven HTML report).** On `cw logs-filter` / `cw logs-search`, builds a
self-contained HTML report (KPIs, charts, sortable/filterable tables) **deterministically — no LLM,
no tokens**. The chosen parser drives it: a parser may implement an optional `report(rows) ->
ReportModel` hook for business analysis (top error codes, failing endpoints, warn clusters…); parsers
without the hook fall back to generic message-signature clustering (mask digits/hex/UUIDs, count).

```bash
# HTML to a file
zammadog cw logs-filter -g /aws/ecs/my-service -p ERROR --from now-1h --report my-parser --out report.html
# Report model as JSON (also token-lean, machine-readable)
zammadog cw logs-search -q 'fields @timestamp,@message' -g /aws/ecs/my-service --from now-1h --report my-parser --json
```

The report path fetches up to **1000 rows** (not the 50-row search cap) so clustering has real volume.
`--report` and `--parser` are mutually exclusive (exit 2); `stats` Insights queries are not supported
with `--report` (exit 2 — use `--json` on the plain query instead).

> Parser report hook depends on field shape: CloudWatch logs carry no structured `level`, so a parser
> that gates on `status`/level must lift it from the raw message itself (e.g. the leading `ERROR`/`WARN`
> token) inside `parse()` — otherwise error/warn counts come back 0.

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
| `--out PATH` | stdout | `apm endpoint-report` / `cw logs-* --report` — write to file instead of stdout |
| `--report NAME` | off | `cw logs-filter`/`logs-search` — parser-driven HTML report (JSON with `--json`); excl. with `--parser`; fetches up to 1000 rows |
| `-g/--log-group` | required | `cw logs-search` (repeatable) / `cw logs-filter` (single) — log group name |
| `-p/--pattern` | — | `cw log-groups` name substring / `cw logs-filter` filter pattern (quote `"<trace>"` for substring) |
| `-G/--groups-pattern` | first 50 | `cw trace` — substring to scope which groups to search |
| `--parser` | none | `cw` logs/trace — optional local business log parser (see parsers/example_parser.py) |
| `-n/-m/-d` | — | `cw metrics` — namespace / metric-name / dimension `K=V` (repeatable) |
| `--stat`,`--period` | `Average`,`300` | `cw metrics` — statistic and granularity (seconds) |

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
| Max rows per search | 50 (`cw trace` and `cw logs-* --report` exempt: up to 1000) |
| Max log groups per `cw trace` query | 50 (Insights limit; scope with `-G`) |
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

### CloudWatch workflow (AWS-only environments)

1. **Resolve the log group** from the service name:
   ```bash
   zammadog cw log-groups -p my-service
   ```
2. **See recent errors** in that service:
   ```bash
   zammadog cw logs-filter -g /aws/ecs/my-service -p ERROR --from now-1h
   ```
3. **Trace one request across all services** — origin first, full call chain:
   ```bash
   zammadog cw trace <trace_id> -G <group-substring> --from now-2h
   ```
   The first line is the entry-point service; cross-service HTTP hops mark the call chain and their
   latency, so the slowest call jumps out. The full trace is returned (not capped at 50), so the
   failing line deep in a long flow is included — pipe through `grep` to jump to it:
   ```bash
   zammadog cw trace <id> -G <group-substring> --from now-15m | grep -iE "error|exception"
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

Datadog client is stdlib-only. CloudWatch support requires `boto3>=1.34`.
