@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Yangi agy (Gemini) akkaunt qo'shiladi. Nom bering (bo'sh qoldirsangiz: agy2, agy3, ...):
set /p NAME=Nomi: 
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% "%~dp0usage_bar.py" --add-agy %NAME%
echo.
echo Ochilgan oynada BOSHQA Google akkaunt bilan kiring, keyin /quit yozing.
echo So'ng tray ikonkasi - ... - "Sozlamalarni qayta yuklash".
pause
