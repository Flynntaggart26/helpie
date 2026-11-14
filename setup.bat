@echo off
cd /d "%~dp0"
echo Installing Helpie dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo.
  echo ERROR: Some dependencies failed to install.
  echo If PyAudio fails, try: pip install pipwin && pipwin install pyaudio
  echo If pvporcupine fails, you can skip it (wake word will be disabled).
  pause
  exit /b 1
)
echo.
echo Dependencies installed successfully.
echo.
echo To start Helpie, double-click basla.bat
pause