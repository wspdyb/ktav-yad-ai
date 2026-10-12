@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo Building portable single-file EXE
echo User data will be stored beside the EXE in data\ and models\
echo ============================================
echo Select how the application should display its interface:
echo   E - Open a standalone Edge/Chrome app window (recommended; no browser bundled)
echo   I - Use the embedded Qt WebEngine window (installs additional packages)
choice /C EI /N /D E /T 10 /M "Choose [E/I] (default E)"
if errorlevel 2 (
  set "KTAVYADAI_EMBEDDED_BROWSER=1"
  echo Building with embedded Qt WebEngine.
) else (
  set "KTAVYADAI_EMBEDDED_BROWSER=0"
  echo Building with a standalone Edge/Chrome app window.
)
if not exist "icon.ico" (
  echo ERROR: Required application icon is missing: icon.ico.
  exit /b 1
)

for %%F in ("data\corpus_lite.txt" "data\config.json" "data\fixes_general.tsv" "data\.lm_counts.pkl" "data\.lm_bigrams.pkl" "data\.lm_trigrams.pkl" "models\base_synth.pt" "models\general.pt" "models\typed.pt") do (
  if not exist "%%~F" (
    echo ERROR: Required bundled asset is missing: %%~F.
    exit /b 1
  )
)

if not exist "venv\Scripts\python.exe" (
  set "PYTHON_CMD="
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.13 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.13"
    if not defined PYTHON_CMD (
      py -3.14 --version >nul 2>nul
      if not errorlevel 1 set "PYTHON_CMD=py -3.14"
    )
  )
  if not defined PYTHON_CMD (
    where python >nul 2>nul
    if errorlevel 1 goto :python_missing
    python -c "import sys; raise SystemExit(0 if (3,13) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>nul
    if errorlevel 1 goto :python_version
    set "PYTHON_CMD=python"
  )
  echo Creating project virtual environment...
  %PYTHON_CMD% -m venv venv
  if errorlevel 1 goto :venv_error
)

echo Installing or verifying required Python packages...
venv\Scripts\python.exe -m ensurepip --upgrade
if errorlevel 1 goto :dependency_error
venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :dependency_error

if "%KTAVYADAI_EMBEDDED_BROWSER%"=="1" (
  echo Installing optional embedded browser packages...
  venv\Scripts\python.exe -m pip install --disable-pip-version-check "pywebview[qt]"
  if errorlevel 1 goto :dependency_error
)

if not exist "venv\Scripts\pyinstaller.exe" (
  echo ERROR: PyInstaller was not installed from requirements.txt.
  exit /b 1
)

venv\Scripts\pyinstaller.exe --noconfirm --clean --distpath release --workpath build KtavYadAI.spec
if errorlevel 1 exit /b 1
if not exist "release\KtavYadAI.exe" (
  echo ERROR: PyInstaller reported success but release\KtavYadAI.exe was not created.
  exit /b 1
)

echo.
echo Done: release\KtavYadAI.exe
echo Running startup diagnostic with a log...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$exe = (Resolve-Path 'release\KtavYadAI.exe').Path; $timer = [Diagnostics.Stopwatch]::StartNew(); $p = Start-Process -FilePath $exe -ArgumentList '--diagnose-startup' -WorkingDirectory (Get-Location).Path -Wait -PassThru; $timer.Stop(); Add-Content -Path 'release\data\startup.log' -Value ('build_process_total_seconds={0:N2}' -f $timer.Elapsed.TotalSeconds); exit $p.ExitCode"
if errorlevel 1 (
  echo ERROR: Startup diagnostic failed. See release\data\startup.log
  exit /b 1
)
echo Startup diagnostic passed. Log: release\data\startup.log
exit /b 0

:python_missing
echo ERROR: Install Python 3.13 or 3.14 and enable the Python launcher or PATH.
exit /b 1

:python_version
echo ERROR: Python 3.13 or 3.14 is required to build this application.
exit /b 1

:venv_error
echo ERROR: Could not create the project virtual environment.
exit /b 1

:dependency_error
echo ERROR: Dependency installation failed. Check your internet connection and retry.
exit /b 1
