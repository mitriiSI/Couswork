@echo off
chcp 65001 >nul
rem Builds dist\ScreenRecorder-Setup.exe (installer) and dist\ScreenRecorder.exe (portable).
rem Needs Python 3.10+ from python.org and Inno Setup 6 from jrsoftware.org (for the installer).
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name ScreenRecorder --icon icon.ico --add-data "icon.ico;." ^
  --collect-data soundcard --collect-data imageio_ffmpeg ^
  --distpath dist/app --workpath build/app ^
  main.py || goto :error
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name ScreenRecorder --icon icon.ico --add-data "icon.ico;." ^
  --collect-data soundcard --collect-data imageio_ffmpeg ^
  --distpath dist --workpath build/onefile ^
  main.py || goto :error
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo.
  echo Inno Setup 6 не найден - установщик не собран. Переносная версия: dist\ScreenRecorder.exe
  pause
  exit /b 0
)
"%ISCC%" installer.iss || goto :error
echo.
echo Готово: dist\ScreenRecorder-Setup.exe и dist\ScreenRecorder.exe
pause
exit /b 0
:error
echo Сборка не удалась.
pause
exit /b 1
