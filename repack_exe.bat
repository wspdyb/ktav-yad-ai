@echo off
cd /d "%~dp0"
echo ============================================
echo Repack for release: sync accumulated data, then rebuild EXE
echo ============================================
if exist "%LOCALAPPDATA%\KtavYadAI\models" (
  echo Syncing models from packaged-app data folder...
  robocopy "%LOCALAPPDATA%\KtavYadAI\models" "models" *.pt /XO >nul
)
if exist "%LOCALAPPDATA%\KtavYadAI\data\writers" (
  echo Syncing writers data from packaged-app data folder...
  robocopy "%LOCALAPPDATA%\KtavYadAI\data\writers" "data\writers" /E /XO >nul
)
call build_exe.bat
