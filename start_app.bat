@echo off
cd /d "%~dp0"
rem Clean launch - no console window (pythonw)
start "" venv\Scripts\pythonw.exe app.py
