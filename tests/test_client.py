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
        overlay._progress = 1.0
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
        check("deconnecte : ecran de connexion, pas d'onglets",
              panel._stack.currentIndex() == 0, str(panel._stack.currentIndex()))
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("onglets de base presents", titles == ["Envoyer", "Apparence"], str(titles))

        panel.set_identity({"user": {"display_name": "Toto", "is_admin": False,
                                     "is_owner": False, "may_upload": True},
                            "limits": {"max_file_bytes": 5 * 1024 ** 3}, "defaults": {}})
        check("connecte : on bascule sur les onglets",
              panel._stack.currentIndex() == 1, str(panel._stack.currentIndex()))
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("un membre simple n'a pas l'onglet Admin", "Admin" not in titles, str(titles))

        panel.set_identity({"user": {"display_name": "Sans", "is_admin": False,
                                     "is_owner": False, "may_upload": False},
                            "limits": {"max_file_bytes": 1024}, "defaults": {}})
        check("sans droit d'envoi, la zone de depot est desactivee",
              not panel._drop.isEnabled())

        panel.set_identity({"user": {"display_name": "Chef", "is_admin": True,
                                     "is_owner": True, "may_upload": True},
                            "limits": {"max_file_bytes": 5 * 1024 ** 3}, "defaults": {}})
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        check("l'admin obtient l'onglet Admin", "Admin" in titles, str(titles))

        panel.set_connected(True)
        check("le role est affiche", "propriétaire" in panel._subtitle.text(),
              panel._subtitle.text())
        check("pastille verte quand connecte", panel._dot.objectName() == "dot_on",
              panel._dot.objectName())
        panel.set_connected(False)
        check("pastille orange en reconnexion", panel._dot.objectName() == "dot_wait",
              panel._dot.objectName())
        panel.set_connected(True)

        # -- petit panneau ou vraie fenetre -----------------------------------
        compact_flags = panel.windowFlags()
        check("compact : sans cadre et au premier plan",
              bool(compact_flags & Qt.FramelessWindowHint)
              and bool(compact_flags & Qt.WindowStaysOnTopHint))
        check("compact : largeur figee",
              panel.minimumWidth() == panel.maximumWidth() == 360,
              f"{panel.minimumWidth()}-{panel.maximumWidth()}")

        panel.set_expanded(True)
        check("agrandi : cadre systeme rendu",
              not (panel.windowFlags() & Qt.FramelessWindowHint), str(panel.windowFlags()))
        check("agrandi : largeur redimensionnable",
              panel.maximumWidth() > panel.minimumWidth(),
              f"{panel.minimumWidth()}-{panel.maximumWidth()}")
        check("agrandi : la croix maison disparait", not panel._close_button.isVisible())
        check("agrandi : etat retenu", settings["panel_expanded"] is True)

        panel.set_expanded(False)
        check("retour au compact", bool(panel.windowFlags() & Qt.FramelessWindowHint)
              and panel.minimumWidth() == panel.maximumWidth() == 360)
        check("retour au compact : etat retenu", settings["panel_expanded"] is False)

        panel.set_identity({"user": {"display_name": "Chef", "is_admin": True,
                                     "is_owner": True, "may_upload": True},
                            "limits": {"max_file_bytes": 5 * 1024 ** 3}, "defaults": {}})
        panel.set_connected(True)

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

        # -- choix du destinataire --------------------------------------------
        check("par defaut, envoi a tout le monde",
              panel._target_box.currentData() == "" and panel.target_name() == "",
              panel._target_box.currentText())

        panel.show_participants([
            {"id": "1", "display_name": "Alice", "avatar_url": "", "is_you": False},
            {"id": "2", "display_name": "Chef", "avatar_url": "", "is_you": True},
            {"id": "3", "display_name": "Bob", "avatar_url": "", "is_you": False},
        ])
        options = [panel._target_box.itemText(i) for i in range(panel._target_box.count())]
        check("on ne peut pas se viser soi-meme", "Seulement Chef" not in options, str(options))
        check("les autres sont proposes",
              options == ["Tout le monde", "Seulement Alice", "Seulement Bob"], str(options))

        panel._target_box.setCurrentIndex(2)
        check("le pseudo du destinataire est isole",
              panel.target_name() == "Bob", panel.target_name())

        # Un rafraichissement ne doit pas perdre la selection.
        panel.show_participants([
            {"id": "1", "display_name": "Alice", "avatar_url": "", "is_you": False},
            {"id": "3", "display_name": "Bob", "avatar_url": "", "is_you": False},
        ])
        check("la selection survit au rafraichissement",
              panel._target_box.currentData() == "3", panel._target_box.currentText())

        emitted = []
        panel.upload_requested.connect(
            lambda p, c, t, a: emitted.append((p.name, c, t, a)))
        panel._caption_field.setText("coucou")
        panel._on_file_chosen(Path("image.png"))
        check("la cible accompagne l'envoi",
              emitted == [("image.png", "coucou", "3", "fade")], str(emitted))

        panel._target_box.setCurrentIndex(0)
        check("retour a tout le monde", panel.target_name() == "")

        # -- un media prive se signale sur l'overlay ---------------------------
        private = payload("m6", "image", "http://x/y.png", "Alice")
        private["private"] = True
        overlay.show_media(private)
        overlay._on_image(png_bytes(300, 200))
        check("le media prive l'annonce", overlay._name_text() == "Alice → vous",
              overlay._name_text())
        overlay.show_media(payload("m7", "image", "http://x/y.png", "Alice"))
        overlay._on_image(png_bytes(300, 200))
        check("un media global ne l'annonce pas", overlay._name_text() == "Alice",
              overlay._name_text())

        # -- animations -------------------------------------------------------
        from client import theme as th

        options = [panel._animation_box.itemData(i)
                   for i in range(panel._animation_box.count())]
        check("toutes les animations sont proposees",
              options == list(th.ANIMATIONS), str(options))

        panel._animation_box.setCurrentIndex(options.index("bounce"))
        check("le choix d'animation est retenu", settings["animation"] == "bounce",
              settings["animation"])
        emitted.clear()
        panel._on_file_chosen(Path("clip.mp4"))
        check("l'animation accompagne l'envoi",
              emitted and emitted[0][3] == "bounce", str(emitted))

        settings.set("scale_percent", 30)
        overlay.show_media(payload("m8", "image", "http://x/y.png", "Alice"))
        overlay._on_image(png_bytes(400, 300))
        base = overlay._block

        for name in th.ANIMATIONS:
            overlay._animation = name
            overlay._progress = 0.0
            start_offset, start_scale, start_opacity = overlay._animation_state()
            overlay._progress = 1.0
            end_offset, end_scale, end_opacity = overlay._animation_state()
            check(f"animation « {name} » : etat final neutre",
                  end_offset.manhattanLength() < 1.0
                  and abs(end_scale - 1.0) < 0.02 and end_opacity > 0.98,
                  f"{end_offset} {end_scale:.3f} {end_opacity:.3f}")
            if name != "none":
                moved = (start_offset.manhattanLength() > 1.0
                         or abs(start_scale - 1.0) > 0.02 or start_opacity < 0.5)
                check(f"animation « {name} » : etat initial distinct", moved,
                      f"{start_offset} {start_scale:.3f} {start_opacity:.3f}")

        overlay._animation = "slide-up"
        overlay._progress = 0.0
        offset, _, _ = overlay._animation_state()
        check("« monte du bas » demarre plus bas", offset.y() > 0, str(offset))
        overlay._animation = "slide-left"
        offset, _, _ = overlay._animation_state()
        check("« entre par la droite » demarre a droite", offset.x() > 0, str(offset))

        overlay._animation = "fade"
        overlay._progress = 1.0
        check("la zone repeinte deborde du bloc",
              overlay._paint_region().contains(base), str(overlay._paint_region()))

        # -- audio -------------------------------------------------------------
        audio = payload("m9", "audio", "http://x/son.mp3", "Alice", "écoute ça")
        audio["media"]["filename"] = "un_morceau_vraiment_long.mp3"
        audio["media"]["content_type"] = "audio/mpeg"
        overlay.show_media(audio)
        check("l'audio produit une carte", not overlay._block.isEmpty(), str(overlay._block))
        size = overlay._media_size()
        check("la carte audio est large et basse",
              size.width() > size.height() * 2, f"{size.width()}x{size.height()}")
        check("la hauteur reste dans les bornes",
              th.AUDIO_HEIGHT_MIN <= size.height() <= th.AUDIO_HEIGHT_MAX, str(size.height()))
        check("l'audio accuse reception sans attendre d'image",
              "m9" in acked, str(acked))

        canvas2 = QImage(screen.width(), screen.height(), QImage.Format_ARGB32)
        canvas2.fill(Qt.transparent)
        overlay._progress = 1.0
        overlay.render(canvas2)
        painted = canvas2.pixelColor(overlay._block.center())
        check("la carte audio est reellement peinte", painted.alpha() > 0, str(painted))

        # -- le logo doit vraiment porter l'anneau vert -----------------------
        from client.panel import logo
        from client.__main__ import make_icon
        mark = logo(64).toImage()
        ring = sum(1 for y in range(64) for x in range(64)
                   if mark.pixelColor(x, y).green() > 150
                   and mark.pixelColor(x, y).red() < 140)
        check("le logo porte l'anneau vert", ring > 100, f"{ring} pixels verts")
        tray = make_icon().pixmap(64, 64).toImage()
        ring = sum(1 for y in range(64) for x in range(64)
                   if tray.pixelColor(x, y).green() > 150
                   and tray.pixelColor(x, y).red() < 140)
        check("l'icone de notification aussi", ring > 100, f"{ring} pixels verts")

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
