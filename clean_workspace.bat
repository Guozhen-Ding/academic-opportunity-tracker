@echo off
setlocal

set "ROOT=%~dp0"
pushd "%ROOT%" >nul

echo Cleaning temporary workspace files...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Test-Path '.tmp') { Get-ChildItem -LiteralPath '.tmp' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue } ; New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath 'output' -Filter 'dashboard_session*.json' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; " ^
  "Get-ChildItem -LiteralPath 'output' -Filter '*.log' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; " ^
  "Get-ChildItem -LiteralPath 'output' -Filter '*.db-journal' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; " ^
  "$reports = Get-ChildItem -LiteralPath 'output' -Filter 'report-*.md' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending; $reports | Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue; " ^
  "$backups = Get-ChildItem -LiteralPath 'output\status_backups' -Filter 'statuses-*.csv' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending; $backups | Select-Object -Skip 20 | Remove-Item -Force -ErrorAction SilentlyContinue; " ^
  "$logs = Get-ChildItem -LiteralPath 'output\logs' -Filter '*.log*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending; $logs | Select-Object -Skip 10 | Remove-Item -Force -ErrorAction SilentlyContinue"

echo Safe cleanup completed.
echo Kept virtual environments, runtime databases, exported CSVs, and dashboard assets.

popd >nul
endlocal
