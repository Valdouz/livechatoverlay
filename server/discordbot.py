"""Le bot Discord : surveille un salon et relaie ce qui y est posté.

Les médias venus d'ici ne sont pas stockés — on relaie l'URL du CDN Discord, qui se
charge de les servir. Seuls les envois faits depuis le client occupent du disque.
"""

from __future__ import annotations

import logging

import discord

log = logging.getLogger(__name__)


def kind_of(content_type: str) -> str | None:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    return None


class LiveChatBot(discord.Client):
    def __init__(self, config, settings, on_media):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._config = config
        self._settings = settings
        self._on_media = on_media

    # -- cycle de vie ---------------------------------------------------------

    async def on_ready(self) -> None:
        guild = self.get_guild(self._config.guild_id)
        if guild is None:
            log.error(
                "Le bot n'est pas membre du serveur Discord %s. "
                "Invitez-le, sinon personne ne pourra se connecter.",
                self._config.guild_id,
            )
        else:
            log.info("Bot connecté : %s — serveur « %s »", self.user, guild.name)

        channel_id = self._settings["channel_id"]
        if channel_id is None:
            log.warning(
                "Aucun salon surveillé. Choisissez-en un depuis le panneau admin."
            )
        else:
            log.info("Salon surveillé : %s", channel_id)

    # -- appartenance ---------------------------------------------------------

    async def lookup_member(self, user_id: int):
        """Résout un membre du serveur. `None` s'il n'en fait pas partie.

        Passe par l'API REST plutôt que par le cache : cela évite d'exiger l'intent
        privilégié « Server Members ».
        """
        guild = self.get_guild(self._config.guild_id)
        if guild is None:
            return None
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException as exc:
            log.warning("Recherche du membre %s impossible : %s", user_id, exc)
            return None

    # -- écoute ---------------------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        channel_id = self._settings["channel_id"]
        if channel_id is None or message.channel.id != channel_id:
            return
        if message.author.bot:
            return

        media = self._extract(message)
        if media is None:
            return

        author = {
            "id": str(message.author.id),
            "display_name": message.author.display_name,
            "avatar_url": str(message.author.display_avatar.url),
        }
        try:
            await self._on_media(media, author, message.content.strip())
        except Exception:
            log.exception("Diffusion du message Discord impossible.")

    def _extract(self, message: discord.Message) -> dict | None:
        for attachment in message.attachments:
            content_type = attachment.content_type or ""
            kind = kind_of(content_type)
            if kind:
                return {
                    "id": None,
                    "url": attachment.url,
                    "kind": kind,
                    "content_type": content_type,
                    "filename": attachment.filename,
                    "source": "discord",
                }

        for embed in message.embeds:
            if embed.type == "gifv" and embed.video and embed.video.url:
                return {
                    "id": None,
                    "url": embed.video.url,
                    "kind": "video",
                    "content_type": "video/mp4",
                    "filename": "tenor.mp4",
                    "source": "discord",
                }
        return None
