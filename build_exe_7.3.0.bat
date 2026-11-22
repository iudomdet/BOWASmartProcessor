@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "SCRIPT=BOWASmartProcessor7.3.0.py"
set "VENV=.buildenv"

echo ==========================================
echo   Build BOWA Smart Processor to EXE
echo ==========================================

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher "py" not found. Install Python 3.10+ first.
    pause & exit /b 1
)
if not exist "%SCRIPT%" (
    echo [ERROR] %SCRIPT% not found in this folder.
    pause & exit /b 1
)

rem Read VERSION from the script so the EXE name always matches
set "VER="
for /f "tokens=3 delims= " %%V in ('findstr /b /c:"VERSION = " "%SCRIPT%"') do set "VER=%%~V"
if not defined VER set "VER=unknown"
set "APPNAME=BOWASmartProcessor%VER%"

echo.
echo [1/3] Preparing clean build environment (only required libraries)...
if not exist "%VENV%\Scripts\python.exe" py -m venv "%VENV%"
set "PY=%VENV%\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install pyinstaller pymupdf pyzbar pillow reportlab
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause & exit /b 1
)

echo.
echo [2/3] Building EXE...
set "OPTS=--noconfirm --clean --onefile --windowed --name %APPNAME%"
if exist "bowa.ico" set "OPTS=!OPTS! --icon bowa.ico --add-data bowa.ico;."
if exist "portable_fonts" set "OPTS=!OPTS! --add-data portable_fonts;portable_fonts"
set "OPTS=!OPTS! --collect-all pyzbar"
set "OPTS=!OPTS! --collect-submodules reportlab.graphics.barcode"
set "OPTS=!OPTS! --exclude-module numpy --exclude-module pandas --exclude-module cv2 --exclude-module matplotlib --exclude-module scipy --exclude-module IPython --exclude-module pytest --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide6"

"%PY%" -m PyInstaller !OPTS! "%SCRIPT%"
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause & exit /b 1
)

echo.
echo [3/3] Done.
echo EXE: %~dp0dist\%APPNAME%.exe
for %%F in ("dist\%APPNAME%.exe") do echo Size: %%~zF bytes

set "SHA="
for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath 'dist\%APPNAME%.exe').Hash"') do set "SHA=%%H"
echo SHA256: !SHA!
> "dist\update_manifest.json" (
echo {
echo   "version": "%VER%",
echo   "url": "https://github.com/iudomdet/BOWASmartProcessor/releases/download/v%VER%/%APPNAME%.exe",
echo   "notes": "",
echo   "sha256": "!SHA!"
echo }
)
echo Manifest: %~dp0dist\update_manifest.json  ^(edit notes, upload to GitHub^)
if exist "dist\%APPNAME%.exe" explorer /select,"%~dp0dist\%APPNAME%.exe"
pause
endlocal
