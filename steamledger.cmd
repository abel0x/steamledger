@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Copyright 2026 abel0x <https://github.com/abel0x>
rem Double-click for the menu, or run "steamledger.cmd <command>" from a terminal.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m steamledger %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is required: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    python -m steamledger %*
)
set code=%errorlevel%

rem Keep the window open when started by a double-click.
if "%~1"=="" pause
exit /b %code%
