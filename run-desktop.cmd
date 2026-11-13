@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
 start "" "runtime\pythonw.exe" -X utf8 "scripts\desktop_modern.py" %*
) else if exist ".venv\Scripts\pythonw.exe" (
 start "" ".venv\Scripts\pythonw.exe" -X utf8 "scripts\desktop_modern.py" %*
) else (
 pyw -3.12 -X utf8 "scripts\desktop_modern.py" %*
)
