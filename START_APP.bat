@echo off
echo ==========================================
echo    ABSENSI PESERTA PORTABLE STARTER
echo ==========================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak ditemukan! 
    echo Silakan install Python terlebih dahulu di komputer ini.
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
if not exist venv (
    echo [INFO] Membuat Virtual Environment (pertama kali saja)...
    python -m venv venv
)

:: Activate venv and install requirements
echo [INFO] Memeriksa dependensi...
call venv\Scripts\activate
pip install -r requirements.txt --quiet

:: Run the application
echo.
echo [SUKSES] Aplikasi siap dijalankan!
echo [INFO] Jangan tutup jendela ini selama aplikasi berjalan.
echo.
python app.py

pause
