import subprocess
import sys
import os

def install_dependencies():
    print("Installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def start_app():
    print("Starting the application...")
    from app import init_db
    init_db()
    subprocess.Popen([sys.executable, "app.py"])
    print("\nApplication is running!")
    print("Admin Dashboard (Home): http://127.0.0.1:5000")
    print("Halaman Absensi Peserta: http://127.0.0.1:5000/presensi")

if __name__ == "__main__":
    if not os.path.exists("database.db"):
        install_dependencies()
    start_app()
