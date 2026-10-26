@echo off
chcp 65001 >nul
rem Builds dist\ScreenRecorder.exe. Needs Python 3.10+ from python.org.
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ScreenRecorder --icon icon.ico --add-data "icon.ico;." ^
  --collect-data soundcard --collect-data imageio_ffmpeg ^
  main.py || goto :error
echo.
echo Готово: dist\ScreenRecorder.exe
pause
exit /b 0
:error
echo Сборка не удалась.
pause
exit /b 1
