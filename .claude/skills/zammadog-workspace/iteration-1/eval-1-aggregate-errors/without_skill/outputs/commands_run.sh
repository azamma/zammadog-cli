#!/usr/bin/env bash
# Query Datadog for errors per service in the last 30 minutes

NOW=$(date +%s)
FROM=$((NOW - 1800))  # 30 minutes ago

# Option 1: Using Datadog Metrics API (APM trace errors by service)
curl -s -X GET "https://api.datadoghq.com/api/v1/query" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -G \
  --data-urlencode "from=${FROM}" \
  --data-urlencode "to=${NOW}" \
  --data-urlencode "query=sum:trace.web.request.errors{*} by {service}.as_count()" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Errors per service (last 30 min):')
print('=' * 50)
for series in data.get('series', []):
    service = series.get('scope', 'unknown')
    points = series.get('pointlist', [])
    total = sum(p[1] for p in points if p[1] is not None)
    print(f'  {service}: {int(total)} errors')
"

# Option 2: Using Datadog Logs API (if you use log-based error tracking)
curl -s -X POST "https://api.datadoghq.com/api/v2/logs/analytics/aggregate" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"filter\": {
      \"query\": \"status:error\",
      \"from\": \"now-30m\",
      \"to\": \"now\"
    },
    \"group_by\": [
      {
        \"facet\": \"service\",
        \"sort\": { \"type\": \"measure\", \"order\": \"desc\", \"aggregation\": \"count\" },
        \"limit\": 50
      }
    ],
    \"compute\": [
      { \"aggregation\": \"count\" }
    ]
  }" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Errors per service (last 30 min) - Logs:')
print('=' * 50)
for bucket in data.get('data', {}).get('buckets', []):
    service = bucket.get('by', {}).get('service', 'unknown')
    count = bucket.get('computes', {}).get('c0', 0)
    print(f'  {service}: {int(count)} errors')
"
