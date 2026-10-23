@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Usage (Windows) o'rnatish ===
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python topilmadi. https://www.python.org/downloads/ dan o'rnating ^(Add to PATH belgilang^). & pause & exit /b 1)
%PY% -m pip install --user -r requirements.txt || (echo pip xatosi. & pause & exit /b 1)
echo.
echo O'rnatildi. Ishga tushirilmoqda...
call "%~dp0start.bat"
echo Soat yonidagi ^(^^ belgisi ichida bo'lishi mumkin^) halqa ikonkasini qidiring.
echo Windows bilan birga ochilishi uchun: ikonka - ... - "Windows bilan birga ishga tushirish".
pause
