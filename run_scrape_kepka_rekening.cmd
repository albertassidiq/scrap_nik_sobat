@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" "scrape_kepka_rekening.py" --resume --delay-min 0 --delay-max 0 --pause-every 0 %*
) else (
    python "scrape_kepka_rekening.py" --resume --delay-min 0 --delay-max 0 --pause-every 0 %*
)

pause
