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
        check("sans droit d'envoi, la selection est refusee",
              not panel._may_upload)

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

        # -- l'envoi se fait en deux temps --------------------------------------
        emitted = []
        panel.upload_requested.connect(
            lambda p, c, t, a, ds, de: emitted.append((p.name, c, t, a, ds, de)))

        sample = Path(tmp) / "image.png"
        sample.write_bytes(png_bytes(32, 32))
        panel.select_file(sample)
        check("choisir un fichier n'envoie rien", emitted == [], str(emitted))
        check("on passe a l'ecran de confirmation",
              panel._send_stack.currentIndex() == 1, str(panel._send_stack.currentIndex()))
        check("le nom du fichier est rappele", "image.png" in panel._file_label.text(),
              panel._file_label.text())

        panel._caption_field.setText("coucou")
        panel._send()
        check("le bouton envoie avec la legende saisie apres coup",
              emitted == [("image.png", "coucou", "3", "fade", 0, 0)], str(emitted))

        emitted.clear()
        panel.select_file(sample)
        panel._clear_selection()
        check("abandonner revient au choix du fichier",
              panel._send_stack.currentIndex() == 0 and panel._pending is None)
        panel._send()
        check("sans fichier retenu, rien ne part", emitted == [], str(emitted))

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
        panel.select_file(sample)
        panel._send()
        check("l'animation accompagne l'envoi",
              emitted and emitted[0][3] == "bounce", str(emitted))
        panel._clear_selection()

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

        # Un média qui en remplace un autre doit réanimer : c'est le cas courant,
        # puisqu'un nouvel envoi chasse le précédent sans file d'attente.
        overlay._animation = "zoom"
        overlay._progress = 1.0
        replacing = payload("m10", "image", "http://x/y.png", "Alice")
        replacing["media"]["animation"] = "zoom"
        overlay.show_media(replacing)
        check("un média qui en remplace un autre repart de zéro",
              overlay._progress == 0.0, str(overlay._progress))
        # Le remplacement a vidé le bloc : les décalages de glissement se
        # calculent sur sa taille, il faut lui redonner une image.
        overlay._on_image(png_bytes(400, 300))

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

        # -- une trame en retard est abandonnee, pas mise en file --------------
        class Piege:
            """Si on la touche, c'est que la trame n'a pas ete sautee."""
            def isValid(self):
                raise AssertionError("trame traitee alors qu'une autre attendait")

        overlay._frame_dirty = True
        overlay._on_frame(Piege())          # ne doit rien faire
        check("une trame recue trop tot est ignoree", True)

        overlay._frame_dirty = False
        try:
            overlay._on_frame(Piege())
            check("une trame est bien traitee quand l'affichage suit", False,
                  "le piege n'a pas ete declenche")
        except AssertionError:
            check("une trame est bien traitee quand l'affichage suit", True)

        # Peindre libere le verrou, sinon la video se figerait sur une image.
        overlay.show_media(payload("m11", "image", "http://x/y.png", "Alice"))
        overlay._on_image(png_bytes(320, 240))
        overlay._frame_dirty = True
        overlay._progress = 1.0
        overlay.render(QImage(200, 200, QImage.Format_ARGB32))
        check("peindre libere le verrou de trame", overlay._frame_dirty is False)

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

        # -- une adresse mal saisie ne doit pas casser le chargement -------------
        from client.settings import normalise_server_url as norm

        for raw, want in (("https://exemple.fr/", "https://exemple.fr"),
                          ("exemple.fr", "https://exemple.fr"),
                          ("  https://exemple.fr  ", "https://exemple.fr"),
                          ("http://192.168.1.4:3000", "http://192.168.1.4:3000"),
                          ("", "")):
            check(f"adresse {raw!r} normalisee", norm(raw) == want, norm(raw))

        # C'est ce qui decide si le jeton accompagne la requete : une barre finale
        # ou un schema oublie et le media ne se chargeait que chez certains.
        settings.set("server_url", norm("https://livechat.test/"))
        settings.set("token", "SECRET")
        check("le jeton suit malgre une barre oblique finale",
              overlay._authorized("https://livechat.test/media/abc").endswith("?token=SECRET"),
              overlay._authorized("https://livechat.test/media/abc"))

        # -- un echec de chargement doit se signaler ----------------------------
        for status, attendu in ((401, "reconnectez"), (403, "reconnectez"),
                                (404, "supprimé"), (None, "injoignable"),
                                (500, "erreur 500")):
            message = Overlay.failure_message(status)
            check(f"echec {status} explique la cause",
                  attendu in message, f"{status} -> {message}")

        signale = []
        overlay.media_failed.connect(signale.append)
        overlay.media_failed.emit(Overlay.failure_message(404))
        check("l'echec remonte bien au panneau", len(signale) == 1, str(signale))

        # -- sortie audio -------------------------------------------------------
        from PySide6.QtMultimedia import QMediaDevices

        check("par defaut, la sortie du systeme",
              settings["audio_device"] == "" and panel._audio_box.currentData() == "",
              repr(panel._audio_box.currentData()))
        check("la premiere entree annonce le peripherique par defaut",
              "Par défaut du système" in panel._audio_box.itemText(0),
              panel._audio_box.itemText(0))

        available = [d.description() for d in QMediaDevices.audioOutputs()]
        listed = [panel._audio_box.itemData(i) for i in range(panel._audio_box.count())]
        check("toutes les sorties sont proposees",
              all(name in listed for name in available),
              f"{len(available)} attendues, {len(listed) - 1} listees")

        if available:
            panel._audio_box.setCurrentIndex(listed.index(available[0]))
            check("choisir une sortie l'enregistre",
                  settings["audio_device"] == available[0], settings["audio_device"])
            overlay.apply_volume()
            check("l'overlay bascule sur la sortie choisie",
                  overlay._audio.device().description() == available[0],
                  overlay._audio.device().description())

        # Un peripherique disparu ne doit ni etre perdu, ni rendre le son muet.
        settings.set("audio_device", "Casque qui n'existe pas")
        panel.refresh_audio_devices()
        check("une sortie absente reste selectionnee",
              panel._audio_box.currentData() == "Casque qui n'existe pas",
              repr(panel._audio_box.currentData()))
        check("elle est signalee comme absente",
              "(absent)" in panel._audio_box.currentText(), panel._audio_box.currentText())
        overlay.apply_volume()
        check("le son retombe sur la sortie du systeme",
              overlay._audio.device().description()
              == QMediaDevices.defaultAudioOutput().description(),
              overlay._audio.device().description())

        settings.set("audio_device", "")
        panel.refresh_audio_devices()
        overlay.apply_volume()

        # -- decoupe avant envoi ------------------------------------------------
        from client.editor import RangeBar, clock
        from client.panel import TRIMMABLE

        for name, trimmable in (("clip.mp4", True), ("son.mp3", True),
                                ("photo.png", False), ("dessin.gif", False)):
            check(f"{name} {'se decoupe' if trimmable else 'ne se decoupe pas'}",
                  (Path(name).suffix.lower() in TRIMMABLE) is trimmable)

        check("les durees sont lisibles", clock(65400) == "1:05.4", clock(65400))

        barre = RangeBar()
        barre.resize(400, 46)
        vus = []
        barre.changed.connect(lambda a, b: vus.append((a, b)))
        barre.set_duration(60000)
        check("tout est retenu au depart",
              (barre.start, barre.end) == (0, 60000), f"{barre.start}-{barre.end}")

        barre._start, barre._end = 10000, 20000
        barre._grabbed = "start"
        barre._end = 20000
        check("un extrait garde ses bornes",
              (barre.start, barre.end) == (10000, 20000), f"{barre.start}-{barre.end}")

        # Les poignees ne doivent jamais se croiser : un extrait vide n'a pas de sens.
        barre._start = 19950
        barre._start = min(30000, max(0, barre._end - 100))
        check("le debut ne depasse pas la fin", barre.start <= barre.end - 100,
              f"{barre.start}-{barre.end}")

        # La selection complete equivaut a « tout garder ».
        sample_video = Path(tmp) / "clip.mp4"
        sample_video.write_bytes(b"x" * 2048)
        panel.select_file(sample_video)
        check("le bouton Decouper apparait pour une video",
              panel._trim_button.isVisible() or not panel.isVisible())
        check("aucun extrait par defaut", panel._trim == (0, 0), str(panel._trim))

        panel._trim = (2000, 9000)
        panel._describe_pending(2048)
        check("l'extrait choisi est rappele",
              "0:02.0" in panel._file_label.text()
              and "0:09.0" in panel._file_label.text(), panel._file_label.text())

        emitted.clear()
        panel._send()
        check("les points de coupe accompagnent l'envoi",
              emitted and emitted[0][4] == 2000 and emitted[0][5] == 9000, str(emitted))

        panel._clear_selection()
        check("abandonner oublie l'extrait", panel._trim == (0, 0), str(panel._trim))

        panel.select_file(sample)
        check("une image ne propose pas la decoupe",
              not panel._trim_button.isVisible())
        panel._clear_selection()

        # L'overlay ne doit lire que l'extrait recu.
        decoupe = payload("m13", "video", "http://x/clip.mp4", "Alice")
        decoupe["media"]["trim_start"] = 3000
        decoupe["media"]["trim_end"] = 8000
        overlay.show_media(decoupe)
        check("l'overlay retient les points de coupe",
              (overlay._trim_start, overlay._trim_end) == (3000, 8000),
              f"{overlay._trim_start}-{overlay._trim_end}")
        overlay.show_media(payload("m14", "video", "http://x/clip.mp4", "Alice"))
        check("sans decoupe, la lecture est entiere",
              (overlay._trim_start, overlay._trim_end) == (0, 0),
              f"{overlay._trim_start}-{overlay._trim_end}")

        # -- comparaison de versions -------------------------------------------
        from client.updates import Updater, asset_name, parse_version

        for older, newer in (("2.0.0", "2.1.0"), ("2.0.9", "2.1.0"),
                             ("1.9.9", "2.0.0"), ("2.0.0", "10.0.0"),
                             ("2.1.0-rc1", "2.1.0"), ("2.0.0-dev", "2.0.0")):
            check(f"{older} est anterieur a {newer}",
                  parse_version(older) < parse_version(newer),
                  f"{parse_version(older)} vs {parse_version(newer)}")

        for a, b in (("2.1.0", "v2.1.0"), ("2.1.0", "2.1.0")):
            check(f"{a} et {b} sont la meme version",
                  parse_version(a) == parse_version(b))

        check("une version illisible passe pour ancienne",
              parse_version("n'importe quoi") < parse_version("0.0.1"),
              str(parse_version("n'importe quoi")))
        check("le fichier de release depend du systeme",
              asset_name() in ("LiveChat.exe", "LiveChat-macos-apple-silicon.zip",
                               "LiveChat-macos-intel.zip", "LiveChat-linux"),
              asset_name())
        check("depuis les sources, pas de remplacement automatique",
              Updater.can_replace_itself() is False)

        check("l'installation manuelle explique sa raison",
              Updater.why_manual() == "lancé depuis les sources",
              Updater.why_manual())

        # -- conversion des trames video ----------------------------------------
        # Sur macOS les trames vivent sur le GPU : sans mappage, toImage() renvoie
        # une image nulle et la video se reduit au son.
        journal = []

        class TrameMappable:
            def map(self, mode):
                journal.append("map")
                return True

            def unmap(self):
                journal.append("unmap")

            def toImage(self):
                journal.append("toImage")
                img = QImage(4, 4, QImage.Format_ARGB32)
                img.fill(Qt.red)
                return img

        result = Overlay._frame_to_image(TrameMappable())
        check("la trame est mappee avant conversion", journal[0] == "map", str(journal))
        check("elle est demappee ensuite", "unmap" in journal, str(journal))
        check("l'image obtenue est exploitable",
              not result.isNull() and result.width() == 4, str(result))

        class TrameNonMappable(TrameMappable):
            def map(self, mode):
                journal.append("map-refuse")
                return False

        journal.clear()
        result = Overlay._frame_to_image(TrameNonMappable())
        check("un refus de mappage tente quand meme la conversion",
              journal == ["map-refuse", "toImage"] and not result.isNull(), str(journal))

        # -- bandeau de mise a jour --------------------------------------------
        check("le bandeau est cache par defaut", not panel._update_banner.isVisible())
        panel.show_update("9.9.9")
        check("une version disponible affiche le bandeau",
              "9.9.9" in panel._update_label.text(), panel._update_label.text())
        panel.update_progress(50, 100)
        check("la progression s'affiche", panel._update_progress.value() == 50,
              str(panel._update_progress.value()))
        panel.hide_update()
        check("a jour, le bandeau disparait", not panel._update_banner.isVisible())

        asked = []
        panel.update_requested.connect(lambda: asked.append(1))
        panel.show_update("9.9.9")
        panel._on_update_clicked()
        check("le bouton demande la mise a jour", asked == [1], str(asked))
        check("le bouton se verrouille pendant le telechargement",
              not panel._update_button.isEnabled())
        panel.update_finished("boum", error=True)
        check("un echec propose de reessayer",
              panel._update_button.text() == "Réessayer" and panel._update_button.isEnabled(),
              panel._update_button.text())
        panel.hide_update()

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
