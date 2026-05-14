$ErrorActionPreference = 'Stop'

$scriptDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$serverPath = (Resolve-Path -LiteralPath (Join-Path $scriptDir 'server.py')).Path

claude mcp add email -- py -3.9 "$serverPath" --env EMAIL_MCP_PATH="$scriptDir"
