@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 -m pip install --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
    if errorlevel 1 goto dependency_error
    py -3 "%SCRIPT_DIR%digitone_preset_library.py"
    goto finished
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    python -m pip install --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
    if errorlevel 1 goto dependency_error
    python "%SCRIPT_DIR%digitone_preset_library.py"
    goto finished
)

echo Python 3 was not found. Install it from https://www.python.org/downloads/
goto failed

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
