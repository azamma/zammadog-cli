#!/bin/bash
# Commands run to answer: "Cuántos errores está tirando cada servicio en los últimos 30 minutos"

# Install zammadog (if not already installed)
uv tool install /mnt/c/repos/zammadog-cli

# Auth is set in environment (DD_API_KEY and DD_APP_KEY)
# Run log aggregation: error count grouped by service, last 30 minutes
zammadog logs aggregate --query "status:error" --group-by "service" --from now-30m
