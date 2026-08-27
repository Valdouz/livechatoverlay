"""Compile le client en exécutable autonome.

    python build_client.py

Fonctionne tel quel sur Windows, macOS et Linux — l'exécutable produit ne tourne que
sur le système qui l'a compilé, il faut donc relancer ce script sur chaque plateforme
à distribuer.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "client" / "assets"
NAME = "LiveChat"

# Qt embarque beaucoup de choses dont un overlay n'a aucun usage. Les écarter
# divise la taille de l'exécutable par deux à trois.
EXCLUDED = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtOpcUa",
    "tkinter", "unittest", "pydoc_data",
]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller manquant. Installation…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    if not (ASSETS / "Inter-Variable.ttf").exists():
        print("ERREUR : la police embarquée est absente de client/assets/.")
        print("Sans elle, chaque participant verrait une police différente.")
        return 1

    separator = ";" if sys.platform == "win32" else ":"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onefile",
        "--name", NAME,
        "--add-data", f"{ASSETS}{separator}assets",
        "--collect-submodules", "PySide6.QtMultimedia",
    ]
    for module in EXCLUDED:
        command += ["--exclude-module", module]
    # Le point d'entrée est livechat.py, pas client/__main__.py : PyInstaller
    # exécuterait ce dernier comme un script isolé et tous les imports relatifs
    # du paquet échoueraient au démarrage.
    command += [str(ROOT / "livechat.py")]

    print("Compilation en cours, comptez quelques minutes…\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\nLa compilation a échoué, les détails sont ci-dessus.")
        return result.returncode

    produced = next((p for p in (ROOT / "dist").glob(f"{NAME}*") if p.is_file()), None)
    if produced is None:
        produced = ROOT / "dist" / NAME
    size = produced.stat().st_size / (1024 ** 2) if produced.exists() else 0

    print(f"\nOK : {produced}  ({size:.0f} Mio)")
    print("\nÀ distribuer : ce seul fichier. Les participants n'ont besoin de rien")
    print("d'autre — ni configuration, ni adresse IP : ils saisissent l'adresse du")
    print("serveur au premier lancement et se connectent avec Discord.")
    return 0


def clean() -> None:
    for path in (ROOT / "build", ROOT / "dist", ROOT / f"{NAME}.spec"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
        print("Artefacts de compilation supprimés.")
        sys.exit(0)
    sys.exit(main())
