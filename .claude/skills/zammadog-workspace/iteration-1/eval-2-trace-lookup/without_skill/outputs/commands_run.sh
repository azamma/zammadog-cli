#!/bin/bash
# Commands to look up trace abc123def456789 in Datadog APM
# Service: ms-orders, ~20 minutes ago

# Step 1: Calculate time window
NOW=$(date +%s)
FROM=$((NOW - 1800))  # 30 minutes back for margin

FROM_ISO=$(date -u -d @$FROM +%Y-%m-%dT%H:%M:%SZ)
TO_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "Querying spans from $FROM_ISO to $TO_ISO"

# Step 2: Fetch all spans for the trace
curl -s -X GET "https://api.datadoghq.com/api/v2/spans/events" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -G \
  --data-urlencode "filter[query]=trace_id:abc123def456789 service:ms-orders" \
  --data-urlencode "filter[from]=${FROM_ISO}" \
  --data-urlencode "filter[to]=${TO_ISO}" \
  --data-urlencode "page[limit]=100" \
  | jq '.data[] | {
      span_id: .id,
      service: .attributes.service,
      resource: .attributes.resource,
      duration_ms: (.attributes.duration / 1000000),
      status: .attributes.status,
      start: .attributes.timestamp
    }'
