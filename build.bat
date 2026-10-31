@echo off
rem Builds dist\Launcher.exe (one file, no console window).
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name Launcher --icon mcd_loader\assets\launcher.ico --collect-data mcd_loader --collect-all vgamepad --hidden-import PIL._tkinter_finder launcher.py || exit /b 1
echo.
echo Done: dist\Launcher.exe
