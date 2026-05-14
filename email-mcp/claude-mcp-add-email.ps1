$ErrorActionPreference = 'Stop'

$scriptDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$serverPath = (Resolve-Path -LiteralPath (Join-Path $scriptDir 'server.py')).Path
$command = "py -3.9 `"$serverPath`""

claude mcp add email "$command" --env EMAIL_MCP_PATH="$scriptDir"
