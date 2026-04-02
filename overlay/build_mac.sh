#!/bin/bash
echo "Installation des dépendances..."
pip3 install pyinstaller PyQt5 PyQtWebEngine

echo ""
echo "Compilation de l'overlay en .app..."
python3 -m PyInstaller --onefile --windowed \
  --name LiveChatOverlay \
  --collect-all PyQt5 \
  --hidden-import PyQt5.QtMultimedia \
  --hidden-import PyQt5.QtMultimediaWidgets \
  --hidden-import PyQt5.QtWebSockets \
  --hidden-import PyQt5.QtNetwork \
  overlay.py

echo ""
if [ -f "dist/LiveChatOverlay" ] || [ -d "dist/LiveChatOverlay.app" ]; then
    echo "OK : dist/LiveChatOverlay compilé avec succès"
    echo ""
    echo "Distribuez ces 2 fichiers ensemble :"
    echo "  - dist/LiveChatOverlay  (ou LiveChatOverlay.app)"
    echo "  - config.json  (avec l'IP du bot)"
else
    echo "ERREUR : la compilation a échoué, consultez les logs ci-dessus."
fi
