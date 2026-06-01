#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing zammadog from $RepoDir..."

if (Get-Command uv -ErrorAction SilentlyContinue) {
    # Install as an isolated uv tool so the `zammadog` command and its deps
    # (boto3, ...) live together. --force reinstalls/updates an existing tool.
    $env:UV_LINK_MODE = "copy"
    uv tool install --force --editable "$RepoDir"
} elseif (Get-Command pip -ErrorAction SilentlyContinue) {
    pip install -e "$RepoDir"
} elseif (Get-Command pip3 -ErrorAction SilentlyContinue) {
    pip3 install -e "$RepoDir"
} else {
    Write-Error @"
no pip or uv found. Install one first:
  pip:  https://pip.pypa.io
  uv:   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
"@
    exit 1
}

Write-Host ""
Write-Host "Verifying..."
zammadog --version

Write-Host ""
Write-Host "Done. Set credentials before use:"
Write-Host "  Datadog:    `$env:DD_API_KEY, `$env:DD_APP_KEY, `$env:DD_SITE"
Write-Host "  CloudWatch: uses default AWS credential/region chain (aws configure / `$env:AWS_REGION)"
