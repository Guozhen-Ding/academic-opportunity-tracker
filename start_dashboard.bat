@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "BOOTSTRAP_BAT=%SCRIPT_DIR%setup_venv.bat"
set "PYTHONPATH=%SCRIPT_DIR%src"
set "DASHBOARD_LOG=%SCRIPT_DIR%output\dashboard_server.log"

if not exist "%PYTHON_EXE%" (
    echo Python virtual environment not found at:
    echo %PYTHON_EXE%
    echo.
    echo Attempting to create a fresh .venv on this computer...
    call "%BOOTSTRAP_BAT%"
    if errorlevel 1 (
        echo.
        echo Failed to create the virtual environment automatically.
        echo Check the setup output above.
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" -V >nul 2>&1
if errorlevel 1 (
    echo Python virtual environment exists but is not runnable:
    echo %PYTHON_EXE%
    echo.
    echo This usually means the .venv folder was copied from another machine
    echo and its base Python installation path no longer exists here.
    echo.
    echo Attempting to recreate the virtual environment on this computer...
    call "%BOOTSTRAP_BAT%"
    if errorlevel 1 (
        echo.
        echo Failed to recreate the virtual environment automatically.
        echo Check the setup output above.
        pause
        exit /b 1
    )
)

echo Closing old dashboard server processes...
powershell -NoProfile -Command "$base = [regex]::Escape((Resolve-Path '%SCRIPT_DIR%').Path); $portPids = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); $dashPids = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dashboard_server.py*' -and $_.CommandLine -match $base } | Select-Object -ExpandProperty ProcessId -Unique); ($portPids + $dashPids | Select-Object -Unique) | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Starting academic dashboard server...
if exist "%DASHBOARD_LOG%" del /f /q "%DASHBOARD_LOG%" >nul 2>&1
start "Academic Dashboard Server" cmd /k ""%PYTHON_EXE%" serve_dashboard.py --output-dir output --port 8000 --refresh-on-start --config config.json 1>>"%DASHBOARD_LOG%" 2>>&1"
timeout /t 4 /nobreak >nul

powershell -NoProfile -Command ^
  "$ok = $false; try { $resp = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if ($resp.StatusCode -eq 200) { $ok = $true } } catch { $ok = $false }; if (-not $ok) { Write-Host ''; Write-Host 'Dashboard server did not start successfully.' -ForegroundColor Red; Write-Host 'Check this log:' -ForegroundColor Yellow; Write-Host '  %DASHBOARD_LOG%' -ForegroundColor Yellow; Write-Host ''; if (Test-Path '%DASHBOARD_LOG%') { Get-Content '%DASHBOARD_LOG%' -Tail 40 }; exit 1 }"
if errorlevel 1 (
    echo.
    echo Dashboard server failed to start.
    echo Review the log above or open:
    echo %DASHBOARD_LOG%
    echo.
    pause
    exit /b 1
)

set "DASHBOARD_URL=http://127.0.0.1:8000/dashboard.html?v=%RANDOM%%RANDOM%"
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" "%DASHBOARD_URL%"
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" "%DASHBOARD_URL%"
) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" "%DASHBOARD_URL%"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" "%DASHBOARD_URL%"
) else (
    start "" "%DASHBOARD_URL%"
)

endlocal
