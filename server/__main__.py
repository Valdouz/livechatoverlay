"""Point d'entrée : assemble le bot Discord et le serveur web, puis les fait tourner ensemble."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web

from .app import add_routes
from .auth import DiscordAuth
from .config import Config, ConfigError
from .discordbot import LiveChatBot
from .hub import Hub
from .identity import Authorizer, Sessions
from .settings import Settings
from .store import MediaStore, human

log = logging.getLogger("livechat")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def build_app(config: Config, *, start_bot: bool = True) -> web.Application:
    settings = Settings(config.data_dir / "settings.json")
    sessions = Sessions(config.data_dir / "sessions.json")
    authorizer = Authorizer(config.owner_id, settings)
    store = MediaStore(config, settings)
    hub = Hub(store)

    async def broadcast_media(media: dict, author: dict, caption: str) -> None:
        """Diffuse un média et, s'il est hébergé ici, arme sa suppression."""
        payload = {
            "type": "media",
            "media": media,
            "author": author,
            "caption": caption,
            "defaults": {
                "image_duration_seconds": settings["image_duration_seconds"],
                "media_scale_percent": settings["media_scale_percent"],
            },
        }
        # Les destinataires sont figés au moment de la diffusion : ceux qui se
        # connecteront après ne sont pas attendus, sans quoi le compte à rebours
        # ne se déclencherait jamais sur un groupe qui va et vient.
        recipients = hub.client_ids()
        if media.get("id"):
            store.track(media["id"], recipients)
        delivered = await hub.broadcast(payload)
        log.info(
            "Diffusé : %s de %s -> %d participant(s)",
            media["kind"], author["display_name"], delivered,
        )

    bot = LiveChatBot(config, settings, broadcast_media)
    auth = DiscordAuth(config, sessions, bot.lookup_member)

    # 0 lève le plafond sur le corps des requêtes : les morceaux d'envoi sont lus
    # en flux, et c'est le store qui contrôle taille et quota.
    app = web.Application(client_max_size=0)
    app["config"] = config
    app["settings"] = settings
    app["sessions"] = sessions
    app["authorizer"] = authorizer
    app["store"] = store
    app["hub"] = hub
    app["bot"] = bot
    app["auth"] = auth
    app["broadcast_media"] = broadcast_media
    add_routes(app)

    async def on_startup(_: web.Application) -> None:
        await store.start()
        if start_bot:
            app["bot_task"] = asyncio.create_task(bot.start(config.discord_token))

    async def on_cleanup(_: web.Application) -> None:
        await store.close()
        if start_bot:
            await bot.close()
        task = app.get("bot_task")
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> int:
    configure_logging()
    try:
        config = Config.from_env()
    except ConfigError as exc:
        log.error("Configuration incomplète.\n\n%s\n", exc)
        return 1

    app = build_app(config)
    settings = app["settings"]

    log.info("Dossier de données : %s", config.data_dir)
    log.info("URL publique       : %s", config.public_url)
    log.info("Redirection OAuth2 : %s", config.redirect_uri)
    log.info(
        "Quota disque       : %s  (max %s par fichier)",
        human(settings["disk_quota_bytes"]), human(settings["max_file_bytes"]),
    )
    log.info("Écoute sur %s:%s", config.host, config.port)

    web.run_app(app, host=config.host, port=config.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
