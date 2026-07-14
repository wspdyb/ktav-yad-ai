@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ממשיך את אימון מודל הבסיס (אפשר לעצור עם Ctrl+C — ההתקדמות נשמרת)...
venv\Scripts\python.exe train.py base --steps 30000 --resume
pause
