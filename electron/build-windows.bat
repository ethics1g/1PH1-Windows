@echo off
REM ==============================================================
REM  1PH1 Pharmacy POS - Windows build script
REM  Requires: Node.js 18+, Yarn, Windows 10/11 (x64)
REM ==============================================================
setlocal
cd /d "%~dp0"

echo.
echo === 1PH1 Pharmacy POS - Build Script ===
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed. Download from https://nodejs.org/
    exit /b 1
)
where yarn >nul 2>&1
if errorlevel 1 (
    echo [INFO] Yarn missing - installing globally...
    call npm install -g yarn
    if errorlevel 1 exit /b 1
)

echo [1/3] Installing dependencies...
call yarn install --frozen-lockfile
if errorlevel 1 exit /b 1

echo.
echo [2/3] Checking syntax...
call yarn check
if errorlevel 1 exit /b 1

echo.
echo [3/3] Building Windows installer + portable exe...
call yarn dist
if errorlevel 1 exit /b 1

echo.
echo ==============================================================
echo   Build complete!  See the 'dist' folder:
dir /b dist\*.exe
echo ==============================================================
endlocal
