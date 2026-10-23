@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Usage (Windows) o'rnatish ===
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python topilmadi. https://www.python.org/downloads/ dan o'rnating ^(Add to PATH belgilang^). & pause & exit /b 1)
%PY% -m pip install --user -r requirements.txt || (echo pip xatosi. & pause & exit /b 1)
rem agy-acc buyrug'i istalgan terminalda ishlashi uchun shu papkani foydalanuvchi PATH'iga qo'shamiz
powershell -NoProfile -Command "$d='%~dp0'.TrimEnd('\'); $p=[Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) {$p=''}; if (($p -split ';') -notcontains $d) { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $d).TrimStart(';'), 'User'); Write-Host 'PATH ga qo''shildi:' $d }"
echo.
echo O'rnatildi. Ishga tushirilmoqda...
call "%~dp0start.bat"
echo.
echo Soat yonidagi halqa ikonkasini qidiring ^(^^ strelka ichida bo'lishi mumkin^).
echo Gmail akkauntlarni ulash: YANGI terminal oching va  agy-acc  deb yozing.
pause
