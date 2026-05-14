$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
claude mcp add email -- py -3.9 "$scriptDir\server.py" --env EMAIL_MCP_PATH="$scriptDir"
