"""Point d'entrée de l'exécutable compilé.

PyInstaller exécute son script de départ comme un programme isolé, pas comme un
module de paquet : lui donner `client/__main__.py` directement casse tous les
imports relatifs qui s'y trouvent. Ce fichier importe le paquet normalement, ce
qui rétablit `client` comme parent.

    python livechat.py        équivaut à  python -m client
"""

import sys

from client.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
