# MODOP — Host (toi)

## Ce que tu fais une seule fois

### 1. Configurer le bot

Copie `config.example.json` en `config.json`, puis remplis :

```json
{
  "discord_token": "TON_TOKEN_DISCORD",
  "channel_id": 123456789,
  "port": 3000,
  "image_duration_seconds": 8
}
```

- `discord_token` → ton token bot depuis discord.com/developers
- `channel_id` → l'ID du salon Discord à surveiller (clic droit sur le salon → Copier l'identifiant)

### 2. Ouvrir le port 3000

Les autres doivent pouvoir se connecter à ton PC via le port 3000.

**Option A — réseau local (LAN, même box) :**
Rien à faire, ça marche directement.

**Option B — internet (gens chez eux) :**
Dans ta box/routeur, crée une règle de **redirection de port** :
- Port externe : `3000`
- Port interne : `3000`
- IP interne : l'IP locale de ton PC (ex: `192.168.1.XX`)

### 3. Préparer le config.json des autres

Copie `overlay/config.example.json` en `overlay/config.json` et mets **ton IP** :

```json
{
  "server": "http://TON_IP:3000"
}
```

- **LAN** → ton IP locale : ouvre un terminal, tape `ipconfig`, prends l'IPv4 (ex: `192.168.1.42`)
- **Internet** → ton IP publique : cherche "mon ip" sur Google (ex: `90.XX.XX.XX`)

### 4. Compiler le .exe pour les autres

Lance :
```
overlay/build.bat
```

Ça génère `overlay/dist/LiveChatOverlay.exe`.

---

## Ce que tu fais à chaque session

1. Lance `start.bat` → le bot démarre
2. Lance ton propre overlay : `overlay/start.bat` (ou ton `LiveChatOverlay.exe`)
3. Les autres lancent leur `LiveChatOverlay.exe`
4. Quand quelqu'un poste une image/vidéo dans le salon Discord, elle apparaît sur tous les écrans

---

## Ce que tu donnes aux autres

```
LiveChatOverlay.exe   ← depuis overlay/dist/
config.json           ← depuis overlay/  (avec ton IP dedans)
```

Ces 2 fichiers seulement. Ne donne JAMAIS ton `config.json` principal (il contient ton token Discord).
