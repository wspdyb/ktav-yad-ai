@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================
echo Building distribution EXE (PyInstaller)
echo Bundled models: base + general ONLY (no personal models,
echo no writers data - users start with a clean personal profile).
echo Data folder on target machines: %%LOCALAPPDATA%%\KtavYadAI
echo ============================================
venv\Scripts\pip.exe install pyinstaller

set EXTRA=
if exist "models\general.pt" set EXTRA=!EXTRA! --add-data "models\general.pt;models"
if exist "models\typed.pt" set EXTRA=!EXTRA! --add-data "models\typed.pt;models"
if exist "data\config.json" set EXTRA=!EXTRA! --add-data "data\config.json;data"
if exist "data\fixes_general.tsv" set EXTRA=!EXTRA! --add-data "data\fixes_general.tsv;data"
if exist "data\.lm_counts.pkl" set EXTRA=!EXTRA! --add-data "data\.lm_counts.pkl;data"
if exist "data\.lm_bigrams.pkl" set EXTRA=!EXTRA! --add-data "data\.lm_bigrams.pkl;data"
if exist "data\.lm_trigrams.pkl" set EXTRA=!EXTRA! --add-data "data\.lm_trigrams.pkl;data"

REM Ships the LITE corpus (for synth training/templates) + LM caches (the
REM language model works from caches, not the 320MB full corpus).
venv\Scripts\pyinstaller.exe --noconfirm --onedir --noconsole --name "KtavYadAI" --add-data "data\corpus_lite.txt;data" --add-data "models\base_synth.pt;models" !EXTRA! --collect-all torch --collect-all pypdfium2 --collect-all certifi --collect-all truststore --hidden-import paths --hidden-import charset --hidden-import model --hidden-import synth --hidden-import dataset --hidden-import train --hidden-import segment --hidden-import infer --hidden-import make_template --hidden-import postfix --hidden-import gates --hidden-import fixes --hidden-import app main.py

echo.
echo Done: dist\KtavYadAI\KtavYadAI.exe
pause
