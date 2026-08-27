"""Tests du serveur, sans connexion Discord réelle.

Les identités sont injectées directement dans le magasin de sessions : c'est le seul
raccourci pris, tout le reste — autorisation, envoi, service en Range, rétention —
passe par les vraies routes.

    python -m tests.test_server
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import Config  # noqa: E402
from server.identity import Identity  # noqa: E402
from server.__main__ import build_app  # noqa: E402

OWNER_ID = 111
ADMIN_ID = 222
MEMBER_ID = 333

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  ECHEC {label}  {detail}")


def make_config(data_dir: Path) -> Config:
    os.environ.update(
        DISCORD_TOKEN="jeton-de-test",
        DISCORD_CLIENT_ID="1",
        DISCORD_CLIENT_SECRET="secret",
        DISCORD_GUILD_ID="42",
        OWNER_ID=str(OWNER_ID),
        PUBLIC_URL="http://localhost:3000",
        DATA_DIR=str(data_dir),
    )
    return Config.from_env()


def identity(user_id: int, name: str, roles: list[int] | None = None) -> Identity:
    return Identity(
        user_id=user_id,
        username=name,
        display_name=name,
        avatar_url=f"https://cdn.example/{user_id}.png",
        role_ids=roles or [],
    )


async def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = make_config(Path(tmp))
        app = build_app(config, start_bot=False)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        sessions = app["sessions"]
        owner = sessions.create(identity(OWNER_ID, "Owner")).token
        admin = sessions.create(identity(ADMIN_ID, "Admin")).token
        member = sessions.create(identity(MEMBER_ID, "Membre")).token

        def auth(token: str) -> dict:
            return {"Authorization": f"Bearer {token}"}

        # -- état public ---------------------------------------------------
        response = await client.get("/")
        body = await response.json()
        check("GET / repond", response.status == 200 and body["service"] == "livechat")

        # -- authentification ----------------------------------------------
        response = await client.get("/me")
        check("GET /me sans jeton -> 401", response.status == 401, f"recu {response.status}")

        response = await client.get("/me", headers=auth("jeton-bidon"))
        check("GET /me avec faux jeton -> 401", response.status == 401)

        response = await client.get("/me", headers=auth(owner))
        body = await response.json()
        check("owner reconnu comme owner et admin",
              body["user"]["is_owner"] and body["user"]["is_admin"])

        response = await client.get("/me", headers=auth(member))
        body = await response.json()
        check("membre simple n'est pas admin",
              not body["user"]["is_admin"] and body["user"]["may_upload"])

        # -- l'autorisation est cote serveur -------------------------------
        response = await client.get("/admin/settings", headers=auth(member))
        check("membre simple sur /admin/settings -> 403", response.status == 403,
              f"recu {response.status}")

        response = await client.get("/admin/settings", headers=auth(owner))
        check("owner sur /admin/settings -> 200", response.status == 200)

        # -- promotion par l'owner uniquement ------------------------------
        response = await client.post("/admin/admins", headers=auth(admin),
                                     json={"user_id": ADMIN_ID, "add": True})
        check("un non-owner ne peut pas promouvoir -> 403", response.status == 403,
              f"recu {response.status}")

        response = await client.post("/admin/admins", headers=auth(owner),
                                     json={"user_id": ADMIN_ID, "add": True})
        check("l'owner promeut un admin", response.status == 200)

        response = await client.get("/admin/settings", headers=auth(admin))
        check("l'admin promu accede aux reglages", response.status == 200)

        # -- reglages a chaud, avec bornes ---------------------------------
        response = await client.patch("/admin/settings", headers=auth(admin),
                                      json={"disk_quota_bytes": 1})
        check("quota hors bornes refuse -> 400", response.status == 400,
              f"recu {response.status}")

        response = await client.patch("/admin/settings", headers=auth(admin),
                                      json={"image_duration_seconds": 12,
                                            "max_file_bytes": 4 * 1024 * 1024})
        check("reglages valides acceptes", response.status == 200)
        check("reglage applique en memoire", app["settings"]["image_duration_seconds"] == 12)

        reloaded_path = Path(tmp) / "settings.json"
        check("reglages persistes sur disque",
              reloaded_path.exists() and "12" in reloaded_path.read_text(encoding="utf-8"))

        response = await client.patch("/admin/settings", headers=auth(admin),
                                      json={"reglage_invente": 3})
        check("reglage inconnu refuse -> 400", response.status == 400)

        # -- envoi de fichier ----------------------------------------------
        payload = b"\x89PNG\r\n\x1a\n" + b"livechat" * 4096
        response = await client.post("/upload/init", headers=auth(member),
                                     json={"filename": "photo.png", "size": len(payload),
                                           "content_type": "image/png"})
        check("ouverture d'envoi acceptee", response.status == 200, f"recu {response.status}")
        upload = await response.json()

        half = len(payload) // 2
        response = await client.put(f"/upload/{upload['id']}?offset=0",
                                    headers=auth(member), data=payload[:half])
        state = await response.json()
        check("premier morceau ecrit", response.status == 200 and state["offset"] == half,
              str(state))

        # Reprise : on redemande la position, puis on renvoie le morceau deja recu.
        response = await client.get(f"/upload/{upload['id']}", headers=auth(member))
        state = await response.json()
        check("position de reprise correcte", state["offset"] == half, str(state))

        response = await client.put(f"/upload/{upload['id']}?offset=0",
                                    headers=auth(member), data=payload[:half])
        check("renvoi d'un morceau deja recu tolere", response.status == 200)

        response = await client.put(f"/upload/{upload['id']}?offset={half}",
                                    headers=auth(member), data=payload[half:])
        state = await response.json()
        check("dernier morceau ecrit", state["offset"] == len(payload), str(state))

        response = await client.post(f"/upload/{upload['id']}/complete",
                                     headers=auth(member), json={"caption": "coucou"})
        body = await response.json()
        check("envoi finalise", response.status == 200, str(body))
        media_id = body["media"]["id"]

        # -- un autre membre ne peut pas toucher l'envoi d'autrui ----------
        response = await client.post("/upload/init", headers=auth(admin),
                                     json={"filename": "x.png", "size": 32,
                                           "content_type": "image/png"})
        other = await response.json()
        response = await client.get(f"/upload/{other['id']}", headers=auth(member))
        check("envoi d'autrui inaccessible -> 404", response.status == 404,
              f"recu {response.status}")

        # -- taille refusee au-dela du reglage ------------------------------
        response = await client.post("/upload/init", headers=auth(member),
                                     json={"filename": "gros.mp4", "size": 8 * 1024 * 1024,
                                           "content_type": "video/mp4"})
        check("fichier au-dela du maximum refuse -> 400", response.status == 400,
              f"recu {response.status}")

        # -- ciblage d'une personne -------------------------------------------
        response = await client.get("/participants", headers=auth(member))
        listed = await response.json()
        check("liste des participants accessible a tous", response.status == 200, str(listed))
        check("personne de connecte pour l'instant", listed == [], str(listed))

        response = await client.get("/participants")
        check("liste des participants sans jeton -> 401", response.status == 401)

        # Deux ecrans : un pour le membre, un pour l'admin.
        hub, store_ = app["hub"], app["store"]

        class FakeWS:
            def __init__(self): self.sent = []
            async def send_str(self, text): self.sent.append(text)

        ws_member, ws_admin = FakeWS(), FakeWS()
        c_member = hub.add(ws_member, identity(MEMBER_ID, "Membre"))
        c_admin = hub.add(ws_admin, identity(ADMIN_ID, "Admin"))

        response = await client.get("/participants", headers=auth(member))
        listed = await response.json()
        check("les deux participants apparaissent", len(listed) == 2, str(listed))
        check("le demandeur est marque comme etant lui-meme",
              any(p["is_you"] for p in listed if p["id"] == str(MEMBER_ID)), str(listed))

        sent = await app["broadcast_media"]({"id": None, "kind": "image", "url": "u"},
                                            {"display_name": "Membre"}, "")
        check("diffusion globale : tous les ecrans", sent == 2, str(sent))

        before = len(ws_member.sent)
        sent = await app["broadcast_media"]({"id": None, "kind": "image", "url": "u"},
                                            {"display_name": "Admin"}, "", ADMIN_ID)
        check("diffusion ciblee : un seul ecran", sent == 1, str(sent))
        check("l'ecran vise a recu", len(ws_admin.sent) == 2, str(len(ws_admin.sent)))
        check("l'ecran non vise n'a rien recu", len(ws_member.sent) == before,
              str(len(ws_member.sent)))

        import json as _json
        marked = _json.loads(ws_admin.sent[-1])
        check("le media cible est marque prive", marked["private"] is True, str(marked))
        check("un media global n'est pas marque prive",
              _json.loads(ws_admin.sent[0])["private"] is False)

        # La retention n'attend que les ecrans vises.
        payload2 = b"x" * 2048
        response = await client.post("/upload/init", headers=auth(member),
                                     json={"filename": "prive.png", "size": len(payload2),
                                           "content_type": "image/png"})
        up = await response.json()
        await client.put(f"/upload/{up['id']}?offset=0", headers=auth(member), data=payload2)
        response = await client.post(f"/upload/{up['id']}/complete", headers=auth(member),
                                     json={"target_user_id": str(ADMIN_ID)})
        result = await response.json()
        check("envoi cible accepte", response.status == 200 and result["private"], str(result))
        tracked = {e["media_id"]: e for e in store_.tracked()}
        check("un seul destinataire attendu",
              tracked[result["media"]["id"]]["pending"] == 1,
              str(tracked[result["media"]["id"]]))
        store_.delete(result["media"]["id"])

        response = await client.post(f"/upload/{up['id']}/complete", headers=auth(member),
                                     json={"target_user_id": "pas-un-nombre"})
        check("destinataire invalide refuse", response.status in (400, 404),
              f"recu {response.status}")

        hub.remove(c_member)
        hub.remove(c_admin)

        # -- service du media, avec Range ------------------------------------
        response = await client.get(f"/media/{media_id}")
        check("media sans jeton -> 401", response.status == 401, f"recu {response.status}")

        response = await client.get(f"/media/{media_id}?token={member}")
        served = await response.read()
        check("media servi en entier", response.status == 200 and served == payload)
        check("Accept-Ranges annonce", response.headers.get("Accept-Ranges") == "bytes")

        response = await client.get(f"/media/{media_id}?token={member}",
                                    headers={"Range": "bytes=0-99"})
        chunk = await response.read()
        check("requete Range honoree -> 206",
              response.status == 206 and chunk == payload[:100], f"recu {response.status}")

        # -- audio et animations ----------------------------------------------
        from server.discordbot import kind_of
        for name, expected in (("son.mp3", "audio"), ("voix.wav", "audio"),
                               ("piste.flac", "audio"), ("extrait.m4a", "audio"),
                               ("boucle.ogg", "audio"), ("photo.png", "image"),
                               ("clip.mp4", "video"), ("archive.zip", None)):
            check(f"type reconnu pour {name}", kind_of("", name) == expected,
                  f"{kind_of('', name)} au lieu de {expected}")
        check("type MIME audio reconnu sans extension",
              kind_of("audio/mpeg", "sans-extension") == "audio")

        await client.patch("/admin/settings", headers=auth(admin),
                           json={"max_file_bytes": 8 * 1024 * 1024})
        son = b"ID3" + bytes(4096)
        response = await client.post("/upload/init", headers=auth(member),
                                     json={"filename": "chanson.mp3", "size": len(son),
                                           "content_type": "application/octet-stream"})
        up = await response.json()
        await client.put(f"/upload/{up['id']}?offset=0", headers=auth(member), data=son)
        response = await client.post(f"/upload/{up['id']}/complete", headers=auth(member),
                                     json={"animation": "bounce"})
        result = await response.json()
        check("un mp3 est accepte", response.status == 200, str(result))
        check("il est classe comme audio", result["media"]["kind"] == "audio",
              str(result["media"]))
        check("l'animation choisie est transmise",
              result["media"]["animation"] == "bounce", str(result["media"]))
        store_.delete(result["media"]["id"])

        response = await client.post("/upload/init", headers=auth(member),
                                     json={"filename": "autre.mp3", "size": len(son),
                                           "content_type": "audio/mpeg"})
        up = await response.json()
        await client.put(f"/upload/{up['id']}?offset=0", headers=auth(member), data=son)
        response = await client.post(f"/upload/{up['id']}/complete", headers=auth(member),
                                     json={"animation": "n-importe-quoi"})
        result = await response.json()
        check("une animation inconnue retombe sur le defaut",
              result["media"]["animation"] == "fade", str(result["media"]))
        store_.delete(result["media"]["id"])

        response = await client.patch("/admin/settings", headers=auth(admin),
                                      json={"default_animation": "zoom"})
        check("l'animation par defaut est reglable", response.status == 200)
        response = await client.patch("/admin/settings", headers=auth(admin),
                                      json={"default_animation": "inexistante"})
        check("une animation par defaut inconnue est refusee", response.status == 400,
              f"recu {response.status}")

        await client.patch("/admin/settings", headers=auth(admin),
                           json={"max_file_bytes": 4 * 1024 * 1024,
                                 "default_animation": "fade"})

        # -- retention --------------------------------------------------------
        store = app["store"]
        store.track(media_id, {"client-a", "client-b"})
        tracked = {entry["media_id"]: entry for entry in store.tracked()}
        check("media suivi avec 2 destinataires", tracked[media_id]["pending"] == 2)

        store.ack(media_id, "client-a")
        store.forget_client("client-b")
        entry = store._retention[media_id]
        check("compte a rebours arme une fois tout le monde servi",
              not entry.pending and entry.all_acked_at is not None)

        app["settings"].update({"retention_after_ack_seconds": 0})
        store._sweep()
        check("media supprime apres le delai", store.resolve(media_id) is None)
        check("disque libere", store.usage_bytes() < len(payload))

        # -- bannissement -----------------------------------------------------
        response = await client.post("/admin/bans", headers=auth(admin),
                                     json={"user_id": MEMBER_ID, "add": True})
        check("bannissement applique", response.status == 200)

        response = await client.get("/me", headers=auth(member))
        check("le banni perd l'acces -> 401 ou 403", response.status in (401, 403),
              f"recu {response.status}")

        await client.close()


def main() -> int:
    print("Tests du serveur LiveChat\n")
    asyncio.run(run())
    print()
    if failures:
        print(f"{len(failures)} echec(s) : " + ", ".join(failures))
        return 1
    print("Tout est passe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
