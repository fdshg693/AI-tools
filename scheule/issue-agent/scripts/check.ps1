#Requires -Version 5.1
<#
    tools/schedule のinterval jobから呼ばれる薄いラッパー。
    実処理は issue_agent.check（1周期分だけ処理して終了する）に委ねる。
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

uv run python -m issue_agent.check
exit $LASTEXITCODE
