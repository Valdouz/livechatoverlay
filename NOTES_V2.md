# LiveChat — Notes pour la V2

> État des lieux du code actuel (v1), relevé le 2026-08-27. Sert de base au chantier v2.

---

## 1. Ce que fait le projet aujourd'hui

Un bot Discord écoute un salon. Dès qu'une image / vidéo / gif Tenor y est postée, il la
diffuse en WebSocket à N clients « overlay » (fenêtre transparente click-through) qui
l'affichent en bas à droite de l'écran, avec le pseudo de l'auteur et éventuellement le
texte du message en légende style meme.

Chaîne réelle : `bot/bot.py` (Discord + aiohttp + WS) → `overlay/overlay.py` (PyQt5).

---

## 2. Cartographie — ce qui est vivant / mort

| Fichier | État | Note |
|---|---|---|
| `bot/bot.py` | **VIVANT** — le vrai serveur | lit `config.json` de la **racine** (`BASE_DIR = dirname(dirname(__file__))`) |
| `overlay/overlay.py` | **VIVANT** — le vrai client (854 l.) | PyQt5, `QMediaPlayer` + `QGraphicsVideoItem` |
| `main.py` | **MORT** | all-in-one pywebview, jamais lancé, en retard de plusieurs features, contient un bug fatal (§3) |
| `overlay.html` (racine) | **MORT** | servi par `/` mais plus aucun client ne l'utilise |
| `bot/overlay.html` | **MORT** | quasi-copie de la racine (2 diffs : `location.host` vs `{{PORT}}`) |
| `overlay_old.py` | **MORT** | ancienne version (rendu par `QAbstractVideoSurface` + `QGraphicsDropShadowEffect`) |
| `bot/config.json` | **MORT** | jamais lu, `bot.py` lit celui de la racine |
| `bot/{install,start}.bat`, `bot/requirements.txt` | doublons de la racine | |
| `start.bat` (racine) | lance `python bot/bot.py` | **contredit le README** qui annonce le mode all-in-one `main.py` |

**Décision v2 :** supprimer `main.py`, `overlay_old.py`, les 2 `overlay.html`, `bot/config.json`
et les doublons `bot/*.bat`. Un seul chemin de code.

---

## 3. Bugs et fragilités identifiés

1. **`main.py:30` — `UnboundLocalError`.** `ws_clients -= dead` est une affectation augmentée
   sur une globale sans `global` → crash à la première déconnexion client. (Fichier à supprimer,
   mais ne pas recopier le pattern : `bot.py` fait ça correctement avec une liste `dead`.)
2. **`bot/bot.py:85` — `socket.gethostbyaddr()` bloquant dans `ws_handler`.** Reverse DNS
   synchrone dans la boucle asyncio → gèle tout le serveur (bot Discord compris) pendant
   plusieurs secondes si le résolveur traîne. → `loop.getaddrinfo` / thread / supprimer.
3. **Double reconnexion WS** (`overlay.py`) : `disconnected` **et** `error` branchent chacun un
   `QTimer.singleShot(2000, self._connect)`. Une erreur qui déclenche aussi une déconnexion
   ouvre 2 sockets. → un seul point de reconnexion + backoff exponentiel + jitter.
4. **Rotation MP4 maison** (`_mp4_rotation`) : parsing manuel des boîtes `moov/trak/tkhd` sur
   les 128 premiers Ko via un header `Range`, puis heuristique `needs_rotation = rotation in
   (90,270) and nw > nh` parce que Windows Media Foundation applique parfois la rotation
   lui-même. Fragile par construction. → à régler en changeant de backend vidéo (§5).
5. **Pas de file d'attente.** Un nouveau média écrase instantanément celui en cours. Sur un
   salon actif, la moitié des médias sont invisibles.
6. **Mac cassé malgré `build_mac.sh`.** `os.environ['QT_MULTIMEDIA_PREFERRED_PLUGINS'] =
   'windowsmediafoundation'` est posé au niveau module, inconditionnellement.
7. **Mono-écran.** `primaryScreen()` en dur, position figée bas-droite, `MARGIN = 40`.
8. **Réglages non pilotables côté client.** `duration` et `scale` sont poussés par le serveur
   dans *chaque* message ; le panneau client ne règle que le volume et l'autostart.

---

## 4. Sécurité — à traiter en priorité v2

1. **🔴 Le token Discord est en clair dans `config.json` à la racine** — et c'est un vrai
   token, pas un placeholder. À **révoquer** sur le Developer Portal, puis passer en variable
   d'environnement / `.env` non versionné. (Le MODOP dit « ne donne JAMAIS ton config.json »,
   ce qui est exactement le symptôme du problème : le secret et la config partagent un fichier.)
2. **🔴 `/admin/*` n'est pas authentifié.** N'importe qui atteignant le port peut
   `POST /admin/clear|mute|unmute`. Le « mode admin » côté client (`config.admin` ou
   `_is_local_server()`) ne masque que des boutons — c'est cosmétique, pas une autorisation.
3. **🟠 `GET /admin/clients` fuite l'IP + le hostname de tous les viewers**, sans auth.
4. **🟠 Le MODOP_HOST recommande d'ouvrir le port 3000 sur internet** (redirection de port),
   en HTTP/WS clair. Or `overlay/config.json` pointe déjà sur une IP en `100.64.0.0/10` = plage
   **Tailscale** → le tunnel existe déjà, autant l'imposer et arrêter le port forwarding.
   (`overlay/dist/config.json`, lui, contient encore une IP publique en dur.)
5. **Aucun garde-fou sur le contenu** : pas de taille max, pas de rate-limit par auteur,
   pas de liste d'autorisation, pas de filtre NSFW. Le bot relaie l'URL Discord telle quelle.

---

## 5. Dette technique de fond

- **PyQt5 + `QMediaPlayer` est en fin de vie.** Qt5 est EOL ; le backend WMF est la cause
  directe des bricolages de rotation et de la non-portabilité. Options v2 :
  - **PySide6 / PyQt6** — `QtMultimedia` réécrit, rotation gérée nativement, LGPL pour PySide6 ;
  - **WebView2** — cohérent avec le `.cab` FixedVersionRuntime (251 Mo) qui traîne à la racine,
    et permettrait de réutiliser un vrai front HTML/CSS (animations gratuites) ;
  - **libmpv** — le plus robuste sur les formats, mais une DLL à embarquer.
- **`.exe` de 126 Mo** (`--onefile --collect-all PyQt5`) → à réduire (`--onedir`, exclusion des
  modules Qt inutiles, ou changement de stack).
- **Pas de dépôt git.** À initialiser avant de toucher à quoi que ce soit.
- **~1 Go de déchets à la racine** : `overlay.zip` (378 Mo), `overlay (2).zip` (378 Mo),
  `Microsoft.WebView2.FixedVersionRuntime...cab` (251 Mo), `overlay/dist.zip` (120 Mo),
  `overlay/build/` (127 Mo), `overlay/dist/` (121 Mo), 2 `.mov` de test. → `.gitignore` + purge.
- **Aucun test, aucun log structuré** (des `print`), aucune gestion d'erreur côté réseau
  au-delà du `try/except` global de `on_message`.

---

## 6. Pistes de features v2 (à arbitrer)

- File d'attente des médias + durée d'affichage adaptative.
- Panneau client complet : coin d'affichage, écran cible, taille, durée, opacité, mute.
- Panneau admin séparé (web ou app) authentifié : voir les clients, kick, clear, mute global.
- Historique / replay des N derniers médias.
- Support des URLs directes postées en texte, des stickers, des liens YouTube/Twitch clips.
- Modération : allow-list d'auteurs, taille max, cooldown par utilisateur, bouton « bannir ce média ».
- Auto-update du client (aujourd'hui il faut redistribuer l'`.exe` à la main).
- Découverte du serveur (Tailscale MagicDNS) pour ne plus éditer d'IP dans `config.json`.

---

## 7. Environnement constaté

Python 3.13.14 · PyQt5 5.15.11 · Windows 11 Pro 26200 · pas de git · `overlay/config.json`
pointe sur une IP Tailscale, `overlay/dist/config.json` sur une IP publique (désynchronisés).
