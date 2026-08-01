@echo off
REM ==============================================================
REM  1PH1 Pharmacy POS - Windows build script (v1.2.0+)
REM  Bakes the production URL into the frontend, then packages
REM  everything into a self-contained .exe installer.
REM ==============================================================
setlocal
cd /d "%~dp0"

set "PRODUCTION_URL=https://pharma-checkout-8.emergent.host"

echo.
echo === 1PH1 Pharmacy POS - Build Script ===
echo   Backend (production): %PRODUCTION_URL%
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not installed. Download from https://nodejs.org/
    exit /b 1
)
where yarn >nul 2>&1
if errorlevel 1 (
    echo [INFO] Yarn missing - installing globally...
    call npm install -g yarn
    if errorlevel 1 exit /b 1
)

echo [1/5] Installing Electron dependencies...
call yarn install --frozen-lockfile
if errorlevel 1 exit /b 1

echo.
echo [2/5] Installing frontend dependencies...
pushd ..\frontend
call yarn install --frozen-lockfile
if errorlevel 1 (popd & exit /b 1)

echo.
echo [3/5] Exporting Expo web bundle with production URL baked in...
if exist dist rmdir /s /q dist
set "EXPO_PUBLIC_BACKEND_URL=%PRODUCTION_URL%"
call npx expo export --platform web --output-dir dist --clear
if errorlevel 1 (popd & exit /b 1)
popd

echo.
echo [4/6] Copying frontend bundle into Electron...
if exist webapp rmdir /s /q webapp
xcopy /E /I /Q /Y "..\frontend\dist" "webapp"
if errorlevel 1 exit /b 1

echo.
echo [5/6] Applying post-export fix (rename node_modules -^> _pkg_)...
REM electron-builder prunes any folder literally named 'node_modules', even
REM deep inside a whitelisted directory. Expo exports vendored icon-fonts
REM under webapp/assets/node_modules/@expo/vector-icons/.../*.ttf and those
REM files vanish from the packaged app.asar unless we rename the segment.
REM Result before this step: every icon renders as a  box on the desktop.
call node post-export-fix.js
if errorlevel 1 exit /b 1

echo.
echo [6/6] Building Windows .exe (NSIS + portable)...
call yarn dist
if errorlevel 1 exit /b 1

echo.
echo ==============================================================
echo   Build complete!  See the 'dist' folder:
dir /b dist\*.exe
echo ==============================================================
endlocal
