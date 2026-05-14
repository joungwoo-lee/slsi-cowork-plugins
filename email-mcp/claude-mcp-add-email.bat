@echo off
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
claude mcp add email -- py -3.9 "%SCRIPT_DIR%\server.py" --env EMAIL_MCP_PATH="%SCRIPT_DIR%"
