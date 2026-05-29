@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan di PATH.
    echo Install Python dulu, lalu jalankan ulang file ini.
    pause
    exit /b 1
)

if exist "venv" (
    echo [INFO] Folder venv sudah ada. Hapus/rename venv kalau mau bikin ulang dari nol.
    pause
    exit /b 0
)

python -m venv venv
if errorlevel 1 goto error

"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error

"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto error

echo [OK] venv selesai dibuat.
pause
exit /b 0

:error
echo [ERROR] Setup venv gagal.
pause
exit /b 1
