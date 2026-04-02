# LiveChat Bot — Overlay Discord pour stream

Affiche en temps réel les images et vidéos postées dans un salon Discord sous forme d'overlay transparent sur ton bureau (ou en stream).

---

## Architecture

```
Discord channel
      │
      ▼
  bot/bot.py          ← écoute les messages Discord + serveur WebSocket
      │
      ▼ WebSocket
  overlay/overlay.py  ← fenêtre transparente click-through (Windows)
```

Il y a deux modes de lancement :

| Mode | Description |
|------|-------------|
| **All-in-one** (`main.py`) | Bot + overlay dans le même processus |
| **Séparé** | Bot sur une machine, overlay sur une autre |

---

## Installation

```bash
install.bat
```

Installe toutes les dépendances Python depuis `requirements.txt`.

**Prérequis :** Python 3.x, Windows (pour l'overlay click-through)

---

## Configuration

### Bot + all-in-one (`config.json` à la racine)

```json
{
  "discord_token": "TON_TOKEN_ICI",
  "channel_id": 123456789,
  "port": 3000,
  "image_duration_seconds": 8
}
```

| Champ | Description |
|-------|-------------|
| `discord_token` | Token du bot (Discord Developer Portal) |
| `channel_id` | ID du salon Discord à surveiller |
| `port` | Port du serveur WebSocket (défaut : `3000`) |
| `image_duration_seconds` | Durée d'affichage des images en secondes (défaut : `8`) |

### Overlay client (`overlay/config.json`)

```json
{
  "server": "http://IP_DU_BOT:3000"
}
```

---

## Lancement

### Mode all-in-one (bot + overlay sur la même machine)

```bash
start.bat
```

### Mode séparé

**Sur la machine streamer (bot) :**
```bash
bot/start.bat
```

**Sur la machine overlay :**
```bash
overlay/start.bat
```

---

## Compiler l'overlay en .exe

Pour distribuer l'overlay sans Python :

```bash
overlay/build.bat
```

Génère `overlay/dist/LiveChatOverlay.exe`. Distribuer avec le fichier `config.json` contenant l'adresse IP du bot.

---

## Fonctionnement

1. Le bot Discord surveille le salon configuré
2. Quand une image ou vidéo est postée, le bot la diffuse via WebSocket
3. L'overlay l'affiche en bas à droite avec le nom de l'auteur
4. Les images disparaissent après `image_duration_seconds` secondes
5. Les vidéos disparaissent à la fin de leur lecture
6. La fenêtre est click-through (les clics passent à travers)

---

## Fichiers principaux

| Fichier | Rôle |
|---------|------|
| `main.py` | All-in-one (bot + overlay + serveur) |
| `bot/bot.py` | Bot seul + serveur WebSocket |
| `overlay/overlay.py` | Client overlay (fenêtre transparente) |
| `overlay.html` | UI frontend (WebSocket + animations CSS) |
| `config.json` | Configuration principale |
| `overlay/config.json` | Config du client overlay |
| `install.bat` | Installation des dépendances |
| `start.bat` | Lancement all-in-one |
| `overlay/build.bat` | Compilation en .exe |

---

## Obtenir un token Discord

1. Aller sur [discord.com/developers/applications](https://discord.com/developers/applications)
2. Créer une application → onglet **Bot** → **Reset Token**
3. Activer **Message Content Intent** dans les Privileged Gateway Intents
4. Inviter le bot sur ton serveur avec la permission `Read Messages`
