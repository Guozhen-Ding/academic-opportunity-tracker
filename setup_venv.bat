@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PY="

for %%P in (py.exe python.exe python3.exe) do (
    where %%P >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=%%P"
        goto :found_python
    )
)

echo Could not find a system Python installation.
echo.
echo Install Python on this computer first, then run this script again.
echo Recommended: install Python 3.12+ from python.org or the Microsoft Store.
exit /b 1

:found_python
echo Using system Python launcher: %BOOTSTRAP_PY%

if exist "%VENV_DIR%" (
    echo Removing existing broken virtual environment...
    rmdir /s /q "%VENV_DIR%" >nul 2>&1
)

echo Creating virtual environment...
"%BOOTSTRAP_PY%" -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo Failed to create virtual environment.
    exit /b 1
)

echo Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    exit /b 1
)

echo Installing project dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies from requirements.txt.
    exit /b 1
)

echo Virtual environment is ready:
echo %PYTHON_EXE%
exit /b 0
