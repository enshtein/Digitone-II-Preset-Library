@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV=%SCRIPT_DIR%.venv"

where py >nul 2>nul
if %errorlevel% equ 0 (
    if not exist "%VENV%\Scripts\python.exe" py -3 -m venv "%VENV%"
    goto run_app
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"
    goto run_app
)

echo Python 3 was not found. Install it from https://www.python.org/downloads/
goto failed

:run_app
"%VENV%\Scripts\python.exe" -c "import textual" >nul 2>nul
if errorlevel 1 (
    "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
    if errorlevel 1 goto dependency_error
)
"%VENV%\Scripts\python.exe" "%SCRIPT_DIR%digitone_preset_library.py"
goto finished

:dependency_error
echo.
echo Could not install the Windows terminal dependency.
echo Check your internet connection and try again.

:failed
pause
exit /b 1

:finished
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
