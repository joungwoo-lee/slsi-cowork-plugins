$ErrorActionPreference = 'Stop'

$scriptDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$serverPath = (Resolve-Path -LiteralPath (Join-Path $scriptDir 'server.py')).Path

claude mcp add retriever_mcp -- py -3 "$serverPath"
