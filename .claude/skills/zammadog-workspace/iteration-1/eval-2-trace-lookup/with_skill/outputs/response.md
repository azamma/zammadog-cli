# Trace Lookup — ms-orders / abc123def456789

## Task

The user reported a user-facing error with:
- **Trace ID**: `abc123def456789`
- **Service**: `ms-orders`
- **When**: ~20 minutes ago

They want to see **all spans** of that trace.

---

## Command

Per the zammadog skill's "Follow a trace" workflow (step 3), the correct command is:

```bash
zammadog apm search --query "service:ms-orders trace_id:abc123def456789" --from now-30m --limit 50
```

### Why this command

| Decision | Rationale |
|----------|-----------|
| `apm search` | Fetches APM spans, not logs — traces live in APM |
| `trace_id:abc123def456789` | Filters to exactly this trace |
| `service:ms-orders` | Scopes to the reported service (also speeds up the query) |
| `--from now-30m` | Covers "~20 minutes ago" with margin for clock drift |
| `--limit 50` | Maximum allowed rows — a distributed trace can have many spans |

---

## Expected output

zammadog will print a column-aligned table of all spans belonging to this trace:

```
TS                      SVC           STATUS    TRACE_ID              RESOURCE / MSG
2026-05-05T...Z         ms-orders     error     abc123def456789       POST /orders
2026-05-05T...Z         ms-orders     ok        abc123def456789       db.query orders_insert
2026-05-05T...Z         ms-payments   error     abc123def456789       charge_card
...
```

Each row is one span. Sorting by TS gives the execution timeline of the request.

---

## Next steps (if needed)

If the trace spans multiple services and you want more context on the error:

```bash
# Sample logs correlated to the same trace
zammadog logs search --query "trace_id:abc123def456789" --from now-30m --limit 25
```

If `zammadog` returns 0 results, widen the window (the event may have been indexed with delay):

```bash
zammadog apm search --query "service:ms-orders trace_id:abc123def456789" --from now-1h --limit 50
```
