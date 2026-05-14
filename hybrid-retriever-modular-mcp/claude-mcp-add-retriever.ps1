$ErrorActionPreference = 'Stop'

$scriptDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$serverPath = (Resolve-Path -LiteralPath (Join-Path $scriptDir 'server.py')).Path
$command = "py -3 `"$serverPath`""

claude mcp add retriever_mcp "$command"
