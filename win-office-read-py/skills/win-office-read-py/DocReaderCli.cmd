@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PROJECT_DIR=%SCRIPT_DIR%..\..\DocReaderCliPy"

if not exist "%VENV_PY%" (
    >&2 echo Error: virtual environment not found. Run setup.ps1 first.
    exit /b 9009
)

set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"
"%VENV_PY%" -m docreader_cli %*
exit /b %ERRORLEVEL%
