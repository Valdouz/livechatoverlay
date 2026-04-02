@echo off
echo Installation de PyInstaller...
python -m pip install pyinstaller

echo.
echo Compilation de l'overlay en .exe...
python -m PyInstaller --onefile --windowed ^
  --name LiveChatOverlay ^
  --collect-all PyQt5 ^
  --hidden-import PyQt5.QtMultimedia ^
  --hidden-import PyQt5.QtMultimediaWidgets ^
  --hidden-import PyQt5.QtWebSockets ^
  --hidden-import PyQt5.QtNetwork ^
  --hidden-import win32gui ^
  --hidden-import win32con ^
  overlay.py

echo.
if exist dist\LiveChatOverlay.exe (
    echo OK  : dist\LiveChatOverlay.exe genere avec succes
    echo.
    echo Distribuez ces 2 fichiers ensemble :
    echo   - dist\LiveChatOverlay.exe
    echo   - config.json  ^(avec l'IP du bot^)
) else (
    echo ERREUR : la compilation a echoue, consultez les logs ci-dessus.
)
pause
