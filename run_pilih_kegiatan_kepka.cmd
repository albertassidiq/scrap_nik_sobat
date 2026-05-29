@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv tidak ditemukan di folder ini.
    echo Pastikan folder venv ikut saat folder ini dizip/dibagikan.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" "pilih_kegiatan_kepka.py" %*
pause
