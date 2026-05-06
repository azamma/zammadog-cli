#!/usr/bin/env bash
# Commands actually run during this evaluation session

# 1. Check if zammadog is installed
zammadog --version

# 2. Check if Datadog credentials are set in the environment
echo "DD_API_KEY=${DD_API_KEY:-NOT_SET}"
echo "DD_APP_KEY=${DD_APP_KEY:-NOT_SET}"

# 3. Install zammadog from the local repo via pip3 (uv-backed)
pip3 install -e /mnt/c/repos/zammadog-cli

# 4. Verify install via venv binary
/mnt/c/repos/global-backend-agent/backend-agent-workspace/.venv/bin/zammadog --version
# Output: zammadog 0.1.0

# 5. Run the primary command from the skill — from-url with the incident URL
# This is the CORRECT approach per the skill when a Datadog URL is provided
/mnt/c/repos/global-backend-agent/backend-agent-workspace/.venv/bin/zammadog from-url \
  "https://app.datadoghq.com/logs?query=service%3Ams-payments+status%3Aerror&from_ts=now-1h&to_ts=now"
# Output: Error: DD_API_KEY not set. Export it before using zammadog.
# (Expected — credentials not configured in this environment)

# --- What you WOULD run with credentials configured ---

# export DD_API_KEY=<your-api-key>
# export DD_APP_KEY=<your-app-key>
# export DD_SITE=datadoghq.com

# Primary: parse URL, fetch aggregate + samples in one shot
# zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-payments+status%3Aerror&from_ts=now-1h&to_ts=now"

# Optional follow-up: broader error picture across all services
# zammadog logs aggregate --query "status:error" --group-by "service,status" --from now-1h

# Optional follow-up: more samples
# zammadog logs search --query "service:ms-payments status:error" --from now-30m --limit 25

# Optional follow-up: trace drill-down (replace trace_id with real value from samples)
# zammadog apm search --query "trace_id:<trace_id_from_sample>" --limit 50
