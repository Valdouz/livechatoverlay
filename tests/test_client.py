"""Tests du client, sans serveur ni écran.

Qt tourne en mode « offscreen » : la fenêtre est réellement construite et réellement
peinte, dans une image mémoire. Cela attrape les erreurs d'exécution que de simples
imports laisseraient passer — notamment dans paintEvent.

    python -m tests.test_client
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LIVECHAT_KEEP_PLATFORM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client import platform  # noqa: E402
from client.overlay import Overlay  # noqa: E402
from client.panel import Panel, human  # noqa: E402
from client.settings import ClientSettings  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  ECHEC {label}  {detail}")


def png_bytes(width: int, height: int, color: str = "#c04060") -> bytes:
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def payload(media_id: str | None, kind: str, url: str, name: str, caption: str = "") -> dict:
    return {
        "type": "media",
        "media": {"id": media_id, "url": url, "kind": kind, "content_type": "image/png"},
        "author": {"id": "1", "display_name": name, "avatar_url": ""},
        "caption": caption,
        "defaults": {"image_duration_seconds": 8, "media_scale_percent": 30},
    }


def run() -> None:
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen().geometry()

    with tempfile.TemporaryDirectory() as tmp:
        settings = ClientSettings(Path(tmp) / "settings.json")

        # -- priorite au client -------------------------------------------
        check("sans choix local, la valeur du serveur s'applique",
              settings.scale_percent == 30 and settings.image_duration == 8)
        settings.apply_server_defaults({"media_scale_percent": 50, "image_duration_seconds": 20})
        check("le serveur peut changer ses defauts",
              settings.scale_percent == 50 and settings.image_duration == 20)
        settings.set("scale_percent", 25)
        settings.apply_server_defaults({"media_scale_percent": 80})
        check("un reglage local resiste aux defauts du serveur",
              settings.scale_percent == 25, f"recu {settings.scale_percent}")
        check("le client sait qu'il ne suit plus le serveur",
              not settings.follows_server("scale_percent")
              and settings.follows_server("image_duration_seconds"))

        reloaded = ClientSettings(Path(tmp) / "settings.json")
        check("reglages relus depuis le disque", reloaded.scale_percent == 25)

        # -- overlay --------------------------------------------------------
        settings.set("scale_percent", 30)
        settings.set("margin", 40)
        settings.set("corner", "bottom-right")
        overlay = Overlay(settings)
        overlay.resize(screen.size())

        check("l'overlay est traverse par les clics",
              bool(overlay.windowFlags() & Qt.WindowTransparentForInput))
        check("l'overlay ne prend pas le focus",
              bool(overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus))

        overlay.show_media(payload("m1", "image", "http://x/y.png", "PotatoZY", "Allez terra"))
        overlay._on_image(png_bytes(800, 450))

        block = overlay._block
        check("le bloc est calcule", not block.isEmpty(), str(block))
        expected_w = int(screen.width() * 0.30)
        check("largeur du media conforme au reglage",
              abs(block.width() - expected_w) <= 2, f"{block.width()} vs {expected_w}")
        check("ancre en bas a droite",
              abs(block.right() - (screen.width() - 40)) <= 2
              and abs(block.bottom() - (screen.height() - 40)) <= 2, str(block))
        check("la ligne auteur est au-dessus du media",
              block.height() > int(expected_w * 450 / 800), str(block))

        # -- chaque coin ----------------------------------------------------
        settings.set("corner", "top-left")
        overlay._relayout()
        block = overlay._block
        check("ancre en haut a gauche",
              block.left() == 40 and block.top() == 40, str(block))

        settings.set("corner", "center")
        overlay._relayout()
        block = overlay._block
        check("ancre au centre",
              abs(block.center().x() - screen.width() // 2) <= 2, str(block))

        settings.set("corner", "bottom-right")
        overlay._relayout()

        # -- peinture reelle -------------------------------------------------
        overlay._opacity = 1.0
        canvas = QImage(screen.width(), screen.height(), QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        overlay.render(canvas)

        block = overlay._block
        inside = canvas.pixelColor(block.center())
        check("le media est reellement peint", inside.alpha() > 0, str(inside))
        outside = canvas.pixelColor(5, 5)
        check("le reste de l'ecran reste transparent", outside.alpha() == 0, str(outside))

        # -- legende longue --------------------------------------------------
        overlay.show_media(payload("m2", "image", "http://x/y.png", "Quelqu'un",
                                   "Une legende assez longue pour devoir passer a la ligne "
                                   "au moins une fois dans le cadre"))
        overlay._on_image(png_bytes(600, 600))
        with_caption = overlay._block.height()
        overlay.show_media(payload("m3", "image", "http://x/y.png", "Quelqu'un"))
        overlay._on_image(png_bytes(600, 600))
        without_caption = overlay._block.height()
        check("la legende agrandit le bloc", with_caption > without_caption,
              f"{with_caption} vs {without_caption}")

        # -- un pseudo plus large que le media ne doit pas sortir de l'ecran ---
        settings.set("corner", "bottom-right")
        settings.set("name_size", 46)
        settings.set("scale_percent", 12)
        overlay.show_media(payload("m5", "image", "http://x/y.png",
                                   "UnPseudoVraimentTresTresLong"))
        overlay._on_image(png_bytes(400, 300))
        overlay._on_avatar(png_bytes(64, 64, "#40c080"))
        block = overlay._block
        check("le bloc s'elargit pour le pseudo",
              block.width() > int(screen.width() * 0.12), str(block))
        check("le bloc reste dans l'ecran",
              block.left() >= 0 and block.right() <= screen.width(), str(block))
        settings.set("name_size", 30)
        settings.set("scale_percent", 30)

        # -- accuse de reception ---------------------------------------------
        acked: list[str] = []
        overlay.acknowledged.connect(acked.append)
        overlay.show_media(payload("m4", "image", "http://x/y.png", "Toto"))
        overlay._on_image(png_bytes(320, 240))
        check("l'affichage declenche l'accuse de reception", acked == ["m4"], str(acked))

        # -- jeton ajoute aux seuls medias du serveur -------------------------
        settings.set("server_url", "https://livechat.test")
        settings.set("token", "SECRET")
        ours = overlay._authorized("https://livechat.test/media/abc")
        theirs = overlay._authorized("https://cdn.discordapp.com/attachments/1/2/x.png")
        check("le jeton est ajoute aux medias du serveur", ours.endswith("?token=SECRET"), ours)
        check("le jeton n'est pas envoye a Discord", "SECRET" not in theirs, theirs)

        # -- son -------------------------------------------------------------
        settings.set("volume", 40)
        settings.set("muted", True)
        overlay.apply_volume()
        check("volume et sourdine appliques",
              overlay._audio.isMuted() and abs(overlay._audio.volume() - 0.4) < 0.01)

        # -- panneau ----------------------------------------------------------
        panel = Panel(settings)
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("onglets de base presents",
              titles == ["Connexion", "Envoyer", "Affichage", "Texte"], str(titles))

        panel.set_identity({"user": {"display_name": "Toto", "is_admin": False,
                                     "is_owner": False, "may_upload": True},
                            "limits": {"max_file_bytes": 5 * 1024 ** 3}, "defaults": {}})
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("un membre simple n'a pas l'onglet Admin", "Admin" not in titles, str(titles))

        panel.set_identity({"user": {"display_name": "Chef", "is_admin": True,
                                     "is_owner": True, "may_upload": True},
                            "limits": {"max_file_bytes": 5 * 1024 ** 3}, "defaults": {}})
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("l'admin obtient l'onglet Admin", "Admin" in titles, str(titles))

        panel.set_connected(True)
        check("le role est affiche", "propriétaire" in panel._subtitle.text(),
              panel._subtitle.text())

        panel.show_admin_clients([{"display_name": "Alice"}, {"display_name": "Bob"}])
        listed = panel._clients_label.text()
        check("les participants sont listes par pseudo",
              "Alice" in listed and "Bob" in listed, listed)
        check("aucune adresse IP dans la liste",
              "." not in listed.replace("•", ""), listed)

        panel.show_admin_settings({"settings": {"disk_quota_bytes": 42 * 1024 ** 3,
                                                "max_file_bytes": 5 * 1024 ** 3,
                                                "channel_id": 12345},
                                   "disk": {"used_bytes": 1024 ** 3,
                                            "quota_bytes": 42 * 1024 ** 3}})
        check("le quota remonte dans le panneau", panel._quota.value() == 42,
              str(panel._quota.value()))
        check("le salon surveille est affiche", panel._channel_field.text() == "12345")

        # -- divers -----------------------------------------------------------
        check("tailles lisibles", human(5 * 1024 ** 3) == "5.0 Gio", human(5 * 1024 ** 3))
        check("detection plein ecran sans erreur",
              isinstance(platform.exclusive_fullscreen_active(), bool))
        check("commande de relance non vide", len(platform.launch_command()) >= 1)

        panel.close()
        overlay.close()


def main() -> int:
    print("Tests du client LiveChat\n")
    run()
    print()
    if failures:
        print(f"{len(failures)} echec(s) : " + ", ".join(failures))
        return 1
    print("Tout est passe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
