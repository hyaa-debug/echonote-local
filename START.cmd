@echo off
setlocal
cd /d "%~dp0"
title EchoNote Local
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not finish. See data\logs\setup.log and retry START.cmd.
  pause
)
