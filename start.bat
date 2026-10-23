@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0usage_bar.py" & exit /b)
start "" pythonw "%~dp0usage_bar.py"
