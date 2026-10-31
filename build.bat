@echo off
rem Builds dist\MCDLoader.exe (one file, no console window).
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name MCDLoader --collect-all vgamepad --hidden-import PIL._tkinter_finder launcher.py || exit /b 1
echo.
echo Done: dist\MCDLoader.exe
