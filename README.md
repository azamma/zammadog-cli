# zammadog

Token-friendly Datadog Logs/APM CLI for AI agents and humans.

Fetches logs and spans, compacts them aggressively (~150 B per event), and outputs column-aligned tables. Stdlib only — no third-party runtime deps.

## Claude Code skill

Skill `zammadog` lives in parent `.claude/skills/zammadog/` (one level up from this repo). Auto-triggers when investigating prod incidents, parsing Datadog URLs, or fetching evidence from logs/APM.

## Install

```bash
# Local dev (from repo root)
pip install -e .

# Alongside global-backend-agent
pip install -e ../zammadog-cli
```

## Auth

```bash
export DD_API_KEY=...
export DD_APP_KEY=...
export DD_SITE=datadoghq.com   # or datadoghq.eu
```

## CLI usage

### From a Datadog URL

```bash
zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-foo+status%3Aerror&from_ts=now-1h&to_ts=now"
```

Parses the URL, classifies it, fetches aggregate + samples, prints a compact evidence block.

### Logs

```bash
zammadog logs search --query "service:ms-foo status:error" --from now-30m --limit 25
zammadog logs aggregate --query "status:error" --group-by "service,status" --from now-1h
# Non-default aggregation (default is "count")
zammadog logs aggregate --query "service:ms-foo" --group-by "service" --compute "avg:@duration"
```

Aggregations return up to 20 buckets per facet (top-N by the chosen `--compute`).

### APM

```bash
zammadog apm search --query "service:ms-foo" --from now-30m --limit 25
zammadog apm search --query "trace_id:abc123def456" --from now-1h --limit 50
zammadog apm aggregate --query "status:error" --group-by "service,resource" --from now-1h

# Full trace analysis — fetches all pages automatically (up to 500 spans)
zammadog apm trace <trace_id> --from now-24h           # grouped count summary
zammadog apm trace <trace_id> --from now-24h --stats   # + min/max/avg duration per group
zammadog apm trace <trace_id> --from now-24h --json    # raw JSON

# Endpoint report — cross-trace internal call analysis
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --html --out report.html
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --ai
```

### Flags

| Flag | Default | |
|------|---------|---|
| `--from` | `now-1h` | Start time (relative or RFC3339) |
| `--to` | `now` | End time |
| `--limit` | `25` | Max rows (capped at 50) |
| `--group-by` | required | Comma-separated facets (top 20 buckets per facet) |
| `--compute` | `count` | `logs/apm aggregate` — aggregation expr (e.g. `avg:@duration`, `sum:@bytes`) |
| `--json` | off | JSON output instead of table |
| `--stats` | off | `apm trace` only — show min/max/avg duration |
| `--html` | off | `endpoint-report` — self-contained HTML report |
| `--ai` | off | `endpoint-report` — compact markdown to `~/.claude/tmp/`, prints path |
| `--out PATH` | stdout | `endpoint-report` — write to file instead of stdout |
| `--service` | none | `endpoint-report` — filter by service name |
| `--sample N` | `5` | `endpoint-report` — traces to sample |
| `--endpoints` | none | `endpoint-report` — multiple resources in one run |

`endpoint-report` flags `--html`, `--ai`, and `--json` are mutually exclusive.

## Output

```
TS                      SVC           RESOURCE                  DUR_MS    STATUS    TRACE_ID            ERROR_TYPE
------------------------------------------------------------------------------------------------------------------
2026-05-05T12:34:56Z    ms-foo        FooController.handle…     10        error     69fa76b2000000004…  com.example.rest.exception.ApiRestException
```

## Python API

```python
from zammadog import DatadogClient, extract_datadog_links, gather_evidence, DatadogError

client = DatadogClient.from_env()

logs = client.logs_search("service:ms-foo status:error", "now-30m", "now", limit=10)
rows = client.logs_aggregate("service:ms-foo", "now-1h", "now", group_by=["service", "status"])
spans = client.apm_search("service:ms-foo", "now-30m", "now", limit=25)

# Full trace — auto-paginates all pages (default cap: 500 spans)
all_spans = client.apm_search_all("trace_id:abc123", "now-24h", "now")
all_spans = client.apm_search_all("trace_id:abc123", "now-24h", "now", max_spans=1000)

# From a URL (orchestrator pattern)
links = extract_datadog_links(spec_text)
for i, link in enumerate(links, 1):
    print(gather_evidence(client, link, link_num=i))
```

## Hard limits

| | |
|-|-|
| Max rows per search | 50 |
| Max time window | 24 h |
| HTTP timeout | 15 s |
| 5xx retries | 2 (exponential backoff) |

## Typical investigation workflow

```bash
# 1. Big picture — where are errors concentrated?
zammadog apm aggregate --query "status:error" --group-by "service,status" --from now-1h

# 2. Drill into noisy service
zammadog apm search --query "service:ms-foo status:error" --from now-30m --limit 25

# 3. Full trace analysis — all spans, grouped, with timing stats
zammadog apm trace <id> --from now-24h --stats

# 4. Endpoint internals — N+1 detection, latency breakdown, service fan-out
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10

# 4a. Share with team as HTML (sortable table, CSS charts, dark mode)
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --html --out report.html

# 4b. Feed to AI for analysis (compact markdown → ~/.claude/tmp/, auto-deleted after read)
zammadog apm endpoint-report "POST /my-svc/v1/foo" --service my-svc --from now-24h --sample 10 --ai

# 5. Check logs for full error message
zammadog logs search --query "trace_id:<id>" --from now-1h --limit 10
```

## Tests

```bash
pytest tests/ -v
```

## Integración con global-backend-agent

Cuando `datadog.enabled: true` en `config.yaml`, el orchestrator pre-fetcha evidencia de Datadog URLs en specs antes de pasarlos al investigador. Ver `backend-agent-workspace/lib/investigator.py`.
