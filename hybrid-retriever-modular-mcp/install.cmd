@echo off
REM hybrid-retriever-modular-mcp installer — double-click this on Windows.
REM Bypasses PowerShell ExecutionPolicy (Restricted by default on some installs).
REM %~dp0 = directory containing this .cmd, so cwd doesn't matter.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set INSTALL_RC=%errorlevel%

echo.
if "%INSTALL_RC%"=="0" (
    echo Done.
) else (
    echo Install failed with exit code %INSTALL_RC%.
)
echo.
pause
exit /b %INSTALL_RC%
