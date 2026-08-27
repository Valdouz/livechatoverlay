# LiveChat — partage de médias en overlay

Affiche en temps réel les images et vidéos postées dans un salon Discord, en overlay transparent
sur le bureau de chaque participant.

> **La v2 est en préparation.** Périmètre et décisions : [SPEC_V2.md](SPEC_V2.md).
> État des lieux de la v1 : [NOTES_V2.md](NOTES_V2.md).

---

## Architecture

```
Discord channel
      │
      ▼
  bot/bot.py          ← écoute Discord + serveur WebSocket   (machine du host)
      │
      ▼ WebSocket
  overlay/overlay.py  ← fenêtre transparente click-through   (machine de chaque participant)
```

Le bot et l'overlay tournent dans deux processus séparés, sur deux machines différentes ou sur
la même.

---

## Installation

**Prérequis :** Python 3.x. L'overlay est click-through sur Windows, macOS et Linux/X11.

Côté host (le bot) :

```bash
install.bat
```

Côté participant (l'overlay), depuis les sources :

```bash
overlay/install.bat
```

---

## Configuration

Les fichiers de configuration réels ne sont **pas** dans le dépôt : ils contiennent le token
Discord et l'adresse du serveur. Partir des exemples fournis.

### Bot — `config.json` à la racine

```bash
cp config.example.json config.json
```

| Champ | Description |
|-------|-------------|
| `discord_token` | Token du bot (Discord Developer Portal) |
| `channel_id` | ID du salon Discord à surveiller |
| `port` | Port du serveur WebSocket (défaut : `3000`) |
| `image_duration_seconds` | Durée d'affichage des images en secondes (défaut : `8`) |
| `media_scale` | Taille du média en % de l'écran (défaut : `30`) |

### Overlay — `overlay/config.json`

```bash
cp overlay/config.example.json overlay/config.json
```

| Champ | Description |
|-------|-------------|
| `server` | Adresse du serveur, ex. `http://192.168.1.42:3000` |
| `admin` | Affiche la section admin du panneau (défaut : `false`) |

---

## Lancement

**Machine du host :**
```bash
start.bat
```

**Machine de chaque participant :**
```bash
overlay/start.bat
```

---

## Compiler l'overlay en .exe

Pour distribuer l'overlay aux participants sans installer Python :

```bash
overlay/build.bat        # Windows  → overlay/dist/LiveChatOverlay.exe
overlay/build_mac.sh     # macOS    (non fonctionnel en l'état, cf. NOTES_V2.md)
```

Distribuer l'exécutable **avec** un `config.json` contenant l'adresse du serveur.

---

## Fonctionnement

1. Le bot Discord surveille le salon configuré
2. Quand une image, une vidéo ou un gif Tenor y est posté, le bot le diffuse par WebSocket
3. L'overlay l'affiche en bas à droite, avec le pseudo de l'auteur et le texte du message
4. Les images disparaissent après `image_duration_seconds`, les vidéos en fin de lecture
5. La fenêtre est click-through : les clics passent au travers

Le panneau de l'overlay (icône dans la zone de notification) donne accès au volume et au
lancement au démarrage. En mode admin, il permet aussi de lister les clients connectés et de
retirer un média ou couper le son pour tout le monde.

---

## Fichiers principaux

| Fichier | Rôle |
|---------|------|
| `bot/bot.py` | Bot Discord + serveur WebSocket + API admin |
| `overlay/overlay.py` | Client overlay (fenêtre transparente PyQt5) |
| `config.example.json` | Modèle de configuration du bot |
| `overlay/config.example.json` | Modèle de configuration du client |
| `overlay/build.bat` | Compilation en .exe |
| `start.bat` | Lancement du bot |
| `overlay/start.bat` | Lancement de l'overlay depuis les sources |

---

## Obtenir un token Discord

1. Aller sur [discord.com/developers/applications](https://discord.com/developers/applications)
2. Créer une application → onglet **Bot** → **Reset Token**
3. Activer **Message Content Intent** dans les Privileged Gateway Intents
4. Inviter le bot sur le serveur avec la permission `Read Messages`
