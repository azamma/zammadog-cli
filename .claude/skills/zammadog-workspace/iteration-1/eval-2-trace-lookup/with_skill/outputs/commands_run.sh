#!/bin/bash
# Trace lookup for trace ID: abc123def456789
# Service: ms-orders
# Time: ~20 minutes ago

zammadog apm search --query "service:ms-orders trace_id:abc123def456789" --from now-30m --limit 50
