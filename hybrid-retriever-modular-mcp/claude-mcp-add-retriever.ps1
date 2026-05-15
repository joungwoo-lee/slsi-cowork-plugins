$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
claude mcp add retriever_mcp "py -3.12 $ScriptDir\server.py"

