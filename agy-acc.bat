@echo off
chcp 65001 >nul
where py >nul 2>nul && (py -3 "%~dp0usage_bar.py" acc %*) || (python "%~dp0usage_bar.py" acc %*)
