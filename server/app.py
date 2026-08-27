"""Les routes HTTP et le WebSocket.

L'autorisation est vérifiée ici à chaque appel, jamais déléguée au client : le panneau
admin du client ne fait que masquer des boutons, il n'accorde aucun droit.
"""

from __future__ import annotations

import json
import logging
from functools import wraps

from aiohttp import WSMsgType, web

from .auth import AuthError, DiscordAuth
from .identity import Authorizer, Sessions
from .settings import SettingsError
from .store import StoreError

log = logging.getLogger(__name__)

CALLBACK_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>LiveChat</title>
<style>
  body {{ background:#12121a; color:#e6e6f0; font:16px/1.6 system-ui, sans-serif;
         display:grid; place-items:center; height:100vh; margin:0; text-align:center; }}
  .card {{ max-width:26rem; padding:2rem; }}
  h1 {{ font-size:1.3rem; margin:0 0 .5rem; color:{color}; }}
  p {{ margin:0; color:#a0a0b8; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>"""


def _page(title: str, message: str, ok: bool, status: int = 200) -> web.Response:
    return web.Response(
        text=CALLBACK_PAGE.format(
            title=title, message=message, color="#4ade80" if ok else "#f87171"
        ),
        content_type="text/html",
        status=status,
    )


def _token_from(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    # Le lecteur vidéo ne peut pas poser d'en-tête sur ses requêtes Range :
    # le jeton en paramètre reste nécessaire pour /media et /ws.
    return request.query.get("token")


def requires_auth(handler):
    @wraps(handler)
    async def wrapper(request: web.Request):
        sessions: Sessions = request.app["sessions"]
        authorizer: Authorizer = request.app["authorizer"]
        session = sessions.get(_token_from(request))
        if session is None:
            raise web.HTTPUnauthorized(reason="Authentification requise")
        if authorizer.is_banned(session.identity):
            raise web.HTTPForbidden(reason="Accès révoqué")
        request["identity"] = session.identity
        return await handler(request)

    return wrapper


def requires_admin(handler):
    @wraps(handler)
    @requires_auth
    async def wrapper(request: web.Request):
        authorizer: Authorizer = request.app["authorizer"]
        if not authorizer.is_admin(request["identity"]):
            raise web.HTTPForbidden(reason="Réservé aux administrateurs")
        return await handler(request)

    return wrapper


def requires_owner(handler):
    @wraps(handler)
    @requires_auth
    async def wrapper(request: web.Request):
        authorizer: Authorizer = request.app["authorizer"]
        if not authorizer.is_owner(request["identity"]):
            raise web.HTTPForbidden(reason="Réservé au propriétaire de l'instance")
        return await handler(request)

    return wrapper


# -- état -------------------------------------------------------------------

RELEASES = "https://github.com/Valdouz/livechatoverlay/releases/latest"

LANDING_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LiveChat</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:2rem;
         background:#0e0e15; color:#e8e8f2;
         font:16px/1.6 system-ui, -apple-system, Segoe UI, sans-serif; }}
  .card {{ width:min(34rem, 100%); }}
  .ring {{ width:64px; height:64px; border-radius:50%; border:5px solid #3ddc84;
          background:#1a1a26; margin:0 auto 1.5rem; }}
  h1 {{ font-size:1.6rem; margin:0 0 .3rem; text-align:center; }}
  .sub {{ text-align:center; color:#8a8aa2; margin:0 0 2rem; }}
  .label {{ font-size:.72rem; letter-spacing:1.2px; text-transform:uppercase;
           color:#7f7f9c; margin-bottom:.5rem; }}
  .addr {{ display:flex; gap:.5rem; }}
  code {{ flex:1; background:#1a1a26; border:1px solid #30304a; border-radius:10px;
         padding:.85rem 1rem; font:15px ui-monospace, Consolas, monospace;
         overflow-x:auto; white-space:nowrap; }}
  button {{ background:#23232f; color:#e8e8f2; border:1px solid #30304a;
           border-radius:10px; padding:0 1rem; cursor:pointer; font-size:14px; }}
  button:hover {{ background:#2e2e3d; }}
  .dl {{ display:block; margin:2rem 0 1rem; background:#3ddc84; color:#0b0b12;
        text-align:center; text-decoration:none; font-weight:600;
        border-radius:10px; padding:.9rem; }}
  ol {{ color:#b8b8ce; padding-left:1.2rem; margin:1.5rem 0 0; }}
  li {{ margin:.4rem 0; }}
  .foot {{ margin-top:2rem; text-align:center; color:#55556a; font-size:.85rem; }}
  .foot a {{ color:#7f7f9c; }}
</style></head>
<body><div class="card">
  <div class="ring"></div>
  <h1>LiveChat</h1>
  <p class="sub">Les médias du groupe, en direct sur votre écran.</p>

  <div class="label">Adresse de ce serveur</div>
  <div class="addr">
    <code id="addr">{url}</code>
    <button onclick="navigator.clipboard.writeText('{url}');this.textContent='Copié'">Copier</button>
  </div>

  <a class="dl" href="{releases}">Télécharger LiveChat</a>

  <ol>
    <li>Téléchargez le client pour votre système.</li>
    <li>Lancez-le, collez l'adresse ci-dessus.</li>
    <li>Connectez-vous avec Discord — il faut être membre du serveur.</li>
  </ol>

  <p class="foot">{connected} en ligne ·
    <a href="https://github.com/Valdouz/livechatoverlay">code source</a> · AGPL-3.0</p>
</div></body></html>"""


async def landing(request: web.Request) -> web.Response:
    """Page d'accueil : l'adresse à coller dans le client, et le lien de
    téléchargement. C'est la seule chose que le host a besoin de partager."""
    count = len(request.app["hub"].clients())
    return web.Response(
        text=LANDING_PAGE.format(
            url=request.app["config"].public_url,
            releases=RELEASES,
            connected="Personne" if not count else
                      f"{count} participant{'s' if count > 1 else ''}",
        ),
        content_type="text/html",
    )


async def health(request: web.Request) -> web.Response:
    hub = request.app["hub"]
    return web.json_response(
        {"service": "livechat", "version": 2, "connected": len(hub.clients())}
    )


# -- authentification --------------------------------------------------------


async def auth_start(request: web.Request) -> web.Response:
    auth: DiscordAuth = request.app["auth"]
    return web.json_response(auth.start())


async def auth_callback(request: web.Request) -> web.Response:
    auth: DiscordAuth = request.app["auth"]
    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state:
        return _page("Connexion échouée", "Réponse incomplète de Discord.", ok=False, status=400)
    try:
        identity = await auth.complete(code, state)
    except AuthError as exc:
        return _page("Connexion refusée", str(exc), ok=False, status=403)
    return _page(
        "Connecté",
        f"Bonjour {identity.display_name}. Vous pouvez fermer cet onglet et revenir à LiveChat.",
        ok=True,
    )


async def auth_poll(request: web.Request) -> web.Response:
    auth: DiscordAuth = request.app["auth"]
    state = request.query.get("state", "")
    try:
        return web.json_response(auth.poll(state))
    except AuthError as exc:
        raise web.HTTPUnauthorized(reason=str(exc))


@requires_auth
async def whoami(request: web.Request) -> web.Response:
    authorizer: Authorizer = request.app["authorizer"]
    settings = request.app["settings"]
    return web.json_response(
        {
            "user": authorizer.describe(request["identity"]),
            "defaults": {
                "image_duration_seconds": settings["image_duration_seconds"],
                "media_scale_percent": settings["media_scale_percent"],
            },
            "limits": {"max_file_bytes": settings["max_file_bytes"]},
        }
    )


@requires_auth
async def logout(request: web.Request) -> web.Response:
    sessions: Sessions = request.app["sessions"]
    token = _token_from(request)
    if token:
        sessions.revoke(token)
    return web.json_response({"ok": True})


@requires_auth
async def participants(request: web.Request) -> web.Response:
    """Les participants connectés, pour choisir une cible d'envoi.

    Ouvert à tout membre authentifié — contrairement à /admin/clients, il ne
    révèle que ce que les intéressés voient déjà les uns des autres sur Discord.
    """
    hub = request.app["hub"]
    me = request["identity"].user_id
    seen: dict[int, dict] = {}
    for client in hub.clients():
        # Une même personne peut avoir plusieurs écrans : une seule entrée.
        seen.setdefault(client.identity.user_id, {
            **client.identity.public(),
            "is_you": client.identity.user_id == me,
        })
    return web.json_response(sorted(seen.values(), key=lambda p: p["display_name"].lower()))


# -- WebSocket ---------------------------------------------------------------


async def websocket(request: web.Request) -> web.WebSocketResponse:
    sessions: Sessions = request.app["sessions"]
    authorizer: Authorizer = request.app["authorizer"]
    hub = request.app["hub"]
    store = request.app["store"]

    session = sessions.get(_token_from(request))
    if session is None or authorizer.is_banned(session.identity):
        raise web.HTTPUnauthorized(reason="Authentification requise")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    client = hub.add(ws, session.identity)
    await hub.send_to(client, {"type": "welcome", "you": authorizer.describe(session.identity)})

    try:
        async for message in ws:
            if message.type is not WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(message.data)
            except json.JSONDecodeError:
                continue
            # Le seul message attendu d'un overlay : l'accusé de réception qui
            # déclenche le compte à rebours de suppression du fichier.
            if payload.get("type") == "ack" and payload.get("media_id"):
                store.ack(payload["media_id"], client.id)
    finally:
        hub.remove(client)
    return ws


# -- envoi de fichiers -------------------------------------------------------


@requires_auth
async def upload_init(request: web.Request) -> web.Response:
    authorizer: Authorizer = request.app["authorizer"]
    store = request.app["store"]
    identity = request["identity"]

    if not authorizer.may_upload(identity):
        raise web.HTTPForbidden(reason="Vous n'êtes pas autorisé à envoyer des médias")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Corps de requête invalide")

    try:
        upload = store.begin_upload(
            owner_id=identity.user_id,
            filename=str(body.get("filename", "media")),
            size=int(body.get("size", 0)),
            content_type=str(body.get("content_type", "")),
        )
    except (StoreError, TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(reason=str(exc))

    from .store import CHUNK_SIZE

    return web.json_response(
        {"id": upload.id, "chunk_size": CHUNK_SIZE, "offset": 0}
    )


@requires_auth
async def upload_state(request: web.Request) -> web.Response:
    """Position de reprise après une coupure."""
    store = request.app["store"]
    try:
        upload = store.get_upload(request.match_info["upload_id"], request["identity"].user_id)
    except StoreError as exc:
        raise web.HTTPNotFound(reason=str(exc))
    return web.json_response({"id": upload.id, "offset": upload.received})


@requires_auth
async def upload_chunk(request: web.Request) -> web.Response:
    store = request.app["store"]
    try:
        upload = store.get_upload(request.match_info["upload_id"], request["identity"].user_id)
        offset = int(request.query.get("offset", "0"))
        received = await store.write_chunk(upload, offset, request.content)
    except StoreError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    except ValueError:
        raise web.HTTPBadRequest(reason="Paramètre offset invalide")
    return web.json_response({"offset": received})


@requires_auth
async def upload_complete(request: web.Request) -> web.Response:
    store = request.app["store"]
    identity = request["identity"]
    try:
        upload = store.get_upload(request.match_info["upload_id"], identity.user_id)
        meta = store.complete_upload(upload)
    except StoreError as exc:
        raise web.HTTPBadRequest(reason=str(exc))

    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    from .discordbot import kind_of
    from .settings import ANIMATIONS

    kind = kind_of(meta["content_type"], meta["filename"])
    if kind is None:
        store.delete(meta["id"])
        raise web.HTTPBadRequest(
            reason="Seuls les images, vidéos et fichiers audio sont acceptés"
        )

    # L'animation est choisie par celui qui envoie, pas par ceux qui reçoivent.
    animation = str(body.get("animation") or request.app["settings"]["default_animation"])
    if animation not in ANIMATIONS:
        animation = request.app["settings"]["default_animation"]

    media = {
        "id": meta["id"],
        "url": f"{request.app['config'].public_url}/media/{meta['id']}",
        "kind": kind,
        "content_type": meta["content_type"],
        "filename": meta["filename"],
        "source": "upload",
        "animation": animation,
    }
    author = {
        "id": str(identity.user_id),
        "display_name": identity.display_name,
        "avatar_url": identity.avatar_url,
    }

    target = body.get("target_user_id")
    if target in ("", "all", None):
        target_user = None
    else:
        try:
            target_user = int(target)
        except (TypeError, ValueError):
            store.delete(meta["id"])
            raise web.HTTPBadRequest(reason="Destinataire invalide")

    delivered = await request.app["broadcast_media"](
        media, author, str(body.get("caption", "")).strip(), target_user
    )
    return web.json_response({"ok": True, "media": media, "delivered": delivered,
                              "private": target_user is not None})


@requires_auth
async def serve_media(request: web.Request) -> web.StreamResponse:
    store = request.app["store"]
    found = store.resolve(request.match_info["media_id"])
    if found is None:
        raise web.HTTPNotFound(reason="Média introuvable ou déjà supprimé")
    path, meta = found
    # FileResponse gère les requêtes Range : les overlays lisent en streaming au lieu
    # de télécharger le fichier entier avant d'afficher la première image.
    return web.FileResponse(
        path,
        headers={
            "Content-Type": meta["content_type"],
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        },
    )


# -- administration ----------------------------------------------------------


@requires_admin
async def admin_get_settings(request: web.Request) -> web.Response:
    settings = request.app["settings"]
    store = request.app["store"]
    from .settings import BOUNDS

    return web.json_response(
        {
            "settings": settings.as_dict(),
            "bounds": {k: {"min": lo, "max": hi} for k, (lo, hi) in BOUNDS.items()},
            "disk": {
                "used_bytes": store.usage_bytes(),
                "quota_bytes": settings["disk_quota_bytes"],
            },
        }
    )


@requires_admin
async def admin_patch_settings(request: web.Request) -> web.Response:
    settings = request.app["settings"]
    try:
        patch = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(reason="Corps de requête invalide")
    if not isinstance(patch, dict):
        raise web.HTTPBadRequest(reason="Un objet de réglages est attendu")

    # Les listes d'administrateurs ne se modifient pas ici : elles passent par des
    # routes dédiées, réservées au propriétaire.
    for reserved in ("admin_ids", "banned_ids"):
        patch.pop(reserved, None)

    try:
        applied = settings.update(patch)
    except SettingsError as exc:
        raise web.HTTPBadRequest(reason=str(exc))

    await request.app["hub"].broadcast({"type": "settings", "defaults": {
        "image_duration_seconds": settings["image_duration_seconds"],
        "media_scale_percent": settings["media_scale_percent"],
    }})
    return web.json_response({"ok": True, "applied": applied})


@requires_admin
async def admin_clients(request: web.Request) -> web.Response:
    hub = request.app["hub"]
    return web.json_response([client.public() for client in hub.clients()])


@requires_admin
async def admin_clear(request: web.Request) -> web.Response:
    delivered = await request.app["hub"].broadcast({"type": "clear"})
    return web.json_response({"ok": True, "notified": delivered})


@requires_admin
async def admin_mute(request: web.Request) -> web.Response:
    muted = request.match_info["state"] == "mute"
    delivered = await request.app["hub"].broadcast({"type": "mute", "muted": muted})
    return web.json_response({"ok": True, "notified": delivered})


@requires_admin
async def admin_delete_media(request: web.Request) -> web.Response:
    store = request.app["store"]
    store.delete(request.match_info["media_id"])
    await request.app["hub"].broadcast({"type": "clear"})
    return web.json_response({"ok": True})


@requires_admin
async def admin_overview(request: web.Request) -> web.Response:
    store = request.app["store"]
    settings = request.app["settings"]
    hub = request.app["hub"]
    return web.json_response(
        {
            "connected": len(hub.clients()),
            "disk": {
                "used_bytes": store.usage_bytes(),
                "quota_bytes": settings["disk_quota_bytes"],
            },
            "media_in_flight": store.tracked(),
        }
    )


async def _mutate_id_list(request: web.Request, field: str) -> web.Response:
    settings = request.app["settings"]
    try:
        body = await request.json()
        user_id = int(body["user_id"])
        add = bool(body.get("add", True))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(reason="Attendu : {\"user_id\": ..., \"add\": true|false}")

    current = set(settings[field])
    current.add(user_id) if add else current.discard(user_id)
    try:
        settings.update({field: sorted(current)})
    except SettingsError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    return web.json_response({"ok": True, field: sorted(current)})


@requires_owner
async def admin_set_admin(request: web.Request) -> web.Response:
    return await _mutate_id_list(request, "admin_ids")


@requires_admin
async def admin_set_ban(request: web.Request) -> web.Response:
    response = await _mutate_id_list(request, "banned_ids")
    try:
        user_id = int((await request.json())["user_id"])
    except Exception:
        return response
    if user_id in request.app["settings"]["banned_ids"]:
        request.app["sessions"].revoke_user(user_id)
        await request.app["hub"].disconnect_user(user_id, "Accès révoqué")
    return response


# -- assemblage --------------------------------------------------------------


def add_routes(app: web.Application) -> None:
    app.router.add_get("/", landing)
    app.router.add_get("/health", health)

    app.router.add_get("/auth/start", auth_start)
    app.router.add_get("/auth/callback", auth_callback)
    app.router.add_get("/auth/poll", auth_poll)
    app.router.add_get("/me", whoami)
    app.router.add_get("/participants", participants)
    app.router.add_post("/logout", logout)

    app.router.add_get("/ws", websocket)

    app.router.add_post("/upload/init", upload_init)
    app.router.add_get("/upload/{upload_id}", upload_state)
    app.router.add_put("/upload/{upload_id}", upload_chunk)
    app.router.add_post("/upload/{upload_id}/complete", upload_complete)
    app.router.add_get("/media/{media_id}", serve_media)

    app.router.add_get("/admin/overview", admin_overview)
    app.router.add_get("/admin/settings", admin_get_settings)
    app.router.add_patch("/admin/settings", admin_patch_settings)
    app.router.add_get("/admin/clients", admin_clients)
    app.router.add_post("/admin/clear", admin_clear)
    app.router.add_post("/admin/{state:mute|unmute}", admin_mute)
    app.router.add_delete("/admin/media/{media_id}", admin_delete_media)
    app.router.add_post("/admin/admins", admin_set_admin)
    app.router.add_post("/admin/bans", admin_set_ban)
