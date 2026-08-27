"""Le bot Discord : surveille un salon et relaie ce qui y est posté.

Les médias venus d'ici ne sont pas stockés — on relaie l'URL du CDN Discord, qui se
charge de les servir. Seuls les envois faits depuis le client occupent du disque.
"""

from __future__ import annotations

import logging
import mimetypes

import discord
from discord import app_commands

log = logging.getLogger(__name__)

RELEASES = "https://github.com/Valdouz/livechatoverlay/releases/latest"


#: Certains conteneurs audio sont annoncés en video/* ou en application/* selon
#: le navigateur qui a servi le fichier — on retombe alors sur l'extension.
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga",
                    ".opus", ".aac", ".wma", ".aiff", ".aif")


def _from_mime(content_type: str) -> str | None:
    for prefix in ("audio", "image", "video"):
        if content_type.startswith(f"{prefix}/"):
            return prefix
    return None


def kind_of(content_type: str, filename: str = "") -> str | None:
    """Image, vidéo, audio, ou rien du tout.

    L'extension prime pour l'audio : `mimetypes` ignore `.flac` ou `.opus` sur
    certains systèmes, et Discord annonce parfois ces conteneurs en `video/*`.
    Pour le reste on croit le type déclaré, puis on retombe sur l'extension —
    un envoi sans type annoncé reste ainsi exploitable.
    """
    if filename.lower().endswith(AUDIO_EXTENSIONS):
        return "audio"
    kind = _from_mime(content_type)
    if kind:
        return kind
    guessed, _ = mimetypes.guess_type(filename)
    return _from_mime(guessed or "")


class LiveChatBot(discord.Client):
    def __init__(self, config, settings, on_media):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._config = config
        self._settings = settings
        self._on_media = on_media
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    # -- découverte depuis Discord --------------------------------------------

    def _register_commands(self) -> None:
        """La commande /livechat donne l'adresse du serveur depuis Discord même.

        C'est la réponse au problème de l'amorçage : l'application compilée est la
        même pour tout le monde et ne sait pas à quelle instance elle appartient.
        Plutôt que de distribuer un second fichier de configuration, on récupère
        l'adresse là où le groupe se trouve déjà.
        """

        @app_commands.command(
            name="livechat",
            description="Adresse LiveChat de ce serveur et lien de téléchargement",
        )
        async def livechat(interaction: discord.Interaction) -> None:
            url = self._config.public_url
            embed = discord.Embed(
                title="LiveChat",
                description=(
                    "Les médias postés ici s'affichent en direct sur l'écran de "
                    "tous ceux qui ont l'application ouverte."
                ),
                colour=0x3DDC84,
            )
            embed.add_field(name="Adresse de ce serveur", value=f"`{url}`", inline=False)
            embed.add_field(
                name="Installation",
                value=(
                    f"1. [Télécharger l'application]({RELEASES})\n"
                    "2. La lancer, coller l'adresse ci-dessus\n"
                    "3. Se connecter avec Discord"
                ),
                inline=False,
            )
            embed.set_footer(text="Réponse visible de vous seul.")
            # Éphémère : le salon reste propre, et chacun peut la redemander.
            await interaction.response.send_message(embed=embed, ephemeral=True)

        self.tree.add_command(livechat)

    async def setup_hook(self) -> None:
        # Synchronisation sur le serveur configuré : une commande de guilde est
        # disponible aussitôt, là où une commande globale met jusqu'à une heure.
        guild = discord.Object(id=self._config.guild_id)
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Commande /livechat enregistrée sur le serveur Discord.")
        except discord.HTTPException as exc:
            log.warning(
                "Enregistrement de /livechat impossible (%s). Le bot a-t-il été "
                "invité avec la portée « applications.commands » ?", exc,
            )

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
            kind = kind_of(content_type, attachment.filename)
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
