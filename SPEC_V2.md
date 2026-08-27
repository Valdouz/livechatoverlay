# LiveChat v2 — Spécification

> Décisions arrêtées en session du 2026-08-27. L'état des lieux de la v1 qui a mené à ces
> choix est dans [NOTES_V2.md](NOTES_V2.md).

---

## 1. Objectif de la v2

Un panneau de contrôle réellement fonctionnel, moins de bugs, et un affichage que le participant
maîtrise : **où** ça s'affiche, **quelle taille**, **quelle police**, et une présentation
retravaillée de **qui a posté**.

S'y ajoute une seconde source de médias : l'**envoi direct depuis le client**, pour ne plus être
plafonné par la limite de taille de Discord (§8).

---

## 2. Décisions techniques

| Sujet | Décision |
|---|---|
| Client | **PySide6** (Qt6) — Windows / macOS / Linux |
| Rendu | **Une seule fenêtre top-level**, tout est peint dans un `paintEvent` |
| Vidéo | `QVideoSink` → `videoFrameChanged` → peinture manuelle |
| Transport | Serveur public + TLS, **authentification Discord** (OAuth2, scope `identify`) |
| Autorisation | Le bot vérifie l'appartenance au serveur Discord et lit les rôles |
| Linux | Client X11 forcé (`QT_QPA_PLATFORM=xcb`) pour passer sous XWayland |
| File d'attente | **Aucune.** Un nouveau média remplace le précédent (comportement v1 conservé) |

### Pourquoi une seule fenêtre

La v1 crée cinq fenêtres top-level (`Overlay`, `auth`, `caption`, `vid_view`, `panel`) qui se
disputent le z-order de l'OS entre elles — d'où les `hide()/show()` de colmatage dans
`_show_auth()` et `_show_caption()`. En fusionnant tout dans une seule fenêtre, ce conflit
disparaît, et le maintien au premier plan devient une seule opération à réaffirmer.

Ce découpage n'était pas un choix : en Qt5, un `QAbstractVideoSurface` dans une fenêtre
`WA_TranslucentBackground` composite mal et `frame.image()` renvoie null selon le format.
Qt6 rend `QVideoSink` fiable, y compris sur les frames matérielles — l'architecture propre
redevient possible.

---

## 3. Le panneau de contrôle

**Le client gagne, toujours.** Les réglages vivent côté client et sont persistés localement ;
le serveur ne fournit plus que des valeurs par défaut, utilisées tant que le participant n'a touché
à rien. En v1 `media_scale` et `image_duration_seconds` étaient poussés dans *chaque* message et
écrasaient tout — c'est ce qui rendait un panneau de réglages inutile.

**Affichage**
- Écran cible (liste des moniteurs détectés) — voir §5
- Coin d'ancrage : les 4 coins + centre
- Marge par rapport aux bords
- Taille du média (% de l'écran)
- Opacité
- Durée d'affichage des images

**Texte / légende**
- Police, taille, couleur, contour
- La police retenue est **embarquée dans le binaire** : sans ça, un participant qui ne l'a pas
  installée voit une substitution et l'affichage diffère d'une machine à l'autre.
- Remplace le `font: 24px Impact` codé en dur de la v1.

**Auteur**
- Style d'affichage retravaillé : **avatar Discord + pseudo**, avatar cerclé d'un **anneau vert**
  (couleur fixe, constante de thème — pas la couleur du rôle Discord).
- Le bot transmet `display_avatar.url` dans la diffusion, déjà disponible dans l'objet message,
  aucun appel API supplémentaire.
- Position configurable (au-dessus du média par défaut, cf. §4 / sur le média / masqué)

**Son** — volume, mute

**Système** — lancement au démarrage (Windows / macOS / Linux)

**Admin** — visible uniquement si le serveur reconnaît le compte comme admin (§7)

**Fenêtre** — le panneau est un petit flottant sans cadre, agrandissable en fenêtre système
ordinaire : barre de titre, redimensionnement, barre des tâches. L'état est retenu.

---

## 4. Composition visuelle

Référence : capture fournie le 2026-08-27 — style « alerte media-share ».
Le bloc est composé **verticalement** et ancré dans le coin choisi :

```
   (avatar)  PSEUDO                 ← ligne auteur, AU-DESSUS du média
  ╭─────────────────────────────╮
  │                             │
  │            média            │   ← coins arrondis
  │                             │
  ╰─────────────────────────────╯
```

**Ligne auteur** — au-dessus du média, alignée à gauche. Rupture avec la v1, où le tag auteur
était posé *sur* le média, en bas.
- Avatar Discord découpé en cercle, entouré d'un **anneau vert** (couleur fixe)
- Pseudo en gros, gras, blanc, avec un **contour noir épais** — lisible sur n'importe quel fond
- Rendu : `QPainterPath.addText()` → `strokePath()` en noir épais → `fillPath()` en blanc.
  Trivial une fois tout dans un seul `paintEvent` (§2) ; impossible proprement en v1, où le
  tag auteur était une fenêtre séparée maintenue de force au-dessus de la vidéo.

**Média** — coins arrondis, taille en % de l'écran, réglable dans le panneau (§3).

Rien d'autre : **pas de bandeau coloré** sous le média, pas de barre de progression. La
composition se limite à la ligne auteur et au média.

---

## 5. Choix de l'écran — arbitré

Le participant choisit son moniteur dans le panneau. **Pas de commande admin.**

Si le client détecte un plein écran **exclusif** sur le moniteur sélectionné — DWM court-circuité,
aucune fenêtre ne peut composer par-dessus (cf. NOTES_V2 §3) — il **rejoue la même configuration
sur un autre moniteur** : mêmes coin d'ancrage, taille, marge, police. Rien d'autre ne change,
et rien n'est mis en attente.

Sur une seule sortie vidéo, il n'y a pas de repli possible : l'overlay est simplement masqué le
temps du plein écran exclusif.

## 6. Authentification Discord

```
client      →  GET /auth/start            → URL Discord + state
navigateur  →  Discord → /auth/callback   → le serveur échange le code (secret côté serveur)
serveur     →  bot.guild.get_member(id)   → appartenance + rôles
client      →  GET /auth/poll?state=…     → jeton de session opaque
client      →  wss://…/ws  (jeton)        → connexion authentifiée
```

Scope `identify` seul : le bot étant déjà dans le serveur, il résout lui-même le membre et ses
rôles. Le `client_secret` ne quitte jamais le serveur.

Conséquences directes sur les failles de la v1 :
- `/admin/*` passe d'ouvert à tous à réservé à un rôle Discord
- la liste des clients affiche des **pseudos Discord au lieu d'IP + hostname** — la fuite disparaît
- `overlay/config.json` ne contient plus qu'un nom de domaine stable

**Prérequis infra :** un nom de domaine, TLS (Caddy + Let's Encrypt), une redirect URI déclarée
dans le portail Discord.

---

## 7. Administration

L'admin cesse d'être une case à cocher dans le fichier de config du client. En v1,
`IS_ADMIN = config.get("admin", False) or _is_local_server()` ne faisait que **masquer des
boutons** : n'importe qui pouvait appeler `/admin/*` à la main. En v2 l'autorisation est décidée
par le **serveur** à partir de l'identité Discord, et chaque action admin est revérifiée côté
serveur — le client ne fait qu'afficher ou non l'interface.

### Qui est admin

| Rôle | Comment il est défini | Ce qu'il peut faire |
|---|---|---|
| **Owner** | `OWNER_ID` dans la config d'installation, posé une fois (§9) | tout, dont promouvoir et révoquer des admins |
| **Admin** | promu par l'owner depuis le panneau, ou porteur du rôle Discord configuré | tous les réglages serveur et la modération |
| **Participant** | membre du serveur Discord | recevoir et envoyer des médias |

L'owner est déclaré à l'installation pour résoudre l'**amorçage** : sur une instance neuve,
personne ne pourrait se promouvoir. Ensuite tout se gère depuis le panneau, sans jamais
retoucher un fichier ni redémarrer le serveur.

### Réglages serveur, modifiables à chaud

Le panneau admin lit et écrit les réglages du serveur — plus besoin d'un accès à la machine :

| Réglage | Défaut |
|---|---|
| **Quota disque total** | 30 Go |
| Taille maximale par fichier | 5 Go |
| Délai de suppression après réception | 10 min |
| Plafond absolu de rétention | 1 h |
| Durée d'affichage par défaut des images | 8 s |
| Taille par défaut des médias | 30 % de l'écran |
| Animation des médias venus de Discord | `fade` |
| Salon Discord surveillé | — |
| Qui peut envoyer | tout le monde / porteurs d'un rôle donné |
| Liste des admins | — |

```
GET   /admin/settings     → réglages courants
PATCH /admin/settings     → modification, admins uniquement
```

Ces réglages sont persistés côté serveur dans un fichier de données, **séparé de la config
d'installation** (§9) qui, elle, ne contient que les secrets et l'URL publique.

### Modération

Les actions de la v1, désormais authentifiées : retirer le média en cours, couper le son de tout
le monde, lister les participants connectés — par **pseudo Discord**, plus par IP. S'y ajoutent
le bannissement d'un participant et la suppression manuelle d'un fichier.

---

## 8. Ingestion : Discord **et** upload depuis le client

La v1 n'a qu'une source : une pièce jointe postée dans le salon Discord. La v2 en ajoute une
seconde — **l'envoi direct d'un fichier depuis le client** — pour dépasser la limite de taille
de Discord (500 Mo même avec Nitro). Les deux sources convergent sur la même diffusion.

```
   Discord (pièce jointe)  ─┐
                            ├─→  serveur  ─→  diffusion WebSocket  ─→  overlays
   Upload client (fichier) ─┘
```

### Ce que ça change pour le serveur

Il devient **hébergeur de fichiers**, ce qu'il n'était pas : la v1 ne relayait qu'une URL du CDN
Discord, et c'est Discord qui servait le média à tous les participants. Désormais chaque participant
télécharge depuis la machine du host.

### Dimensionnement — mesuré le 2026-08-27

Connexion du host : **928 Mbps descendant / 575 Mbps montant** (fibre).

575 Mbps ≈ 72 Mo/s théoriques, ~60 Mo/s en débit soutenu réaliste. En gardant ~75 Mbps de marge
pour les à-coups et le reste de l'usage de la machine, il reste **~500 Mbps pour servir les
médias**. Si le serveur tourne sur la machine qui diffuse un flux vers Twitch/YouTube, compter
6 à 20 Mbps de plus — négligeable à cette échelle.

Grâce au service en Range (§ ci-dessous), les overlays tirent au **débit de la vidéo**, pas à la
taille du fichier. C'est le débit qui dimensionne, et la taille devient presque indifférente :

| Débit du média | Participants simultanés tenables |
|---|---|
| 10 Mbps (1080p courant) | ~50 |
| 25 Mbps (1080p/1440p haut débit) | ~20 |
| 50 Mbps (4K) | ~10 |

Même en supposant le pire — tous les participants téléchargent le fichier entier à pleine vitesse
sans streaming — 1 Go × 10 participants passe en moins de 3 minutes.

**Conclusion : le débit du host n'est pas un facteur limitant** pour un usage entre proches. Les
deux vraies limites qui restent sont l'espace disque du serveur, et le **débit montant de celui
qui envoie** : un participant en ADSL (~1 Mbps montant) mettra plus de 2 h à téléverser 1 Go. C'est
précisément ce que l'upload reprenable par morceaux rend supportable.

### Protocole d'upload

HTTP, pas WebSocket — découpé en morceaux et reprenable, sinon une coupure à 90 % d'un fichier
de 1 Go fait tout recommencer.

```
POST /upload/init                → { id, chunk_size }
PUT  /upload/{id}?offset=N       → envoi d'un morceau (rejouable)
POST /upload/{id}/complete       → le serveur valide et diffuse
```

Le média n'est diffusé qu'une fois l'upload **terminé** — pas de relais en cours de transfert,
et donc pas de file d'attente à gérer (cf. §11).

### Service des fichiers

`GET /media/{id}` avec **support des requêtes Range**, pour que les overlays lisent en streaming
au lieu de télécharger 1 Go avant d'afficher la première image. `FileResponse` d'aiohttp le gère
nativement.

### Autorisation

L'upload est réservé aux comptes authentifiés (§6). Un endpoint d'upload ouvert sur un serveur
public, c'est un disque dur offert au premier venu.

### Types acceptés

Images, vidéos, et **fichiers audio** : mp3, wav, m4a, flac, ogg, opus, aac. Un audio n'a
rien à montrer : l'overlay dessine une **carte de lecture** — pastille verte, nom du fichier
et barre d'avancement — au lieu d'un cadre vide.

Le type est déduit du MIME annoncé, avec repli sur l'extension. L'extension prime pour l'audio :
`mimetypes` ignore `.flac` et `.opus` sur certains systèmes, et Discord annonce parfois ces
conteneurs en `video/*`.

### Animation d'apparition

**Choisie par l'expéditeur**, pas par ceux qui reçoivent : c'est son envoi, c'est son entrée
en scène. Le nom voyage avec le média ; le serveur vérifie seulement qu'il existe.

| | |
|---|---|
| `fade` | fondu (défaut) |
| `slide-up` / `slide-down` | monte du bas / descend du haut |
| `slide-left` / `slide-right` | entre par la droite / par la gauche |
| `zoom` | grandit depuis 72 % |
| `bounce` | dépasse puis revient |
| `none` | apparition immédiate |

L'animation transforme le **bloc entier** autour de son centre : média, ligne auteur et légende
restent solidaires. Les médias venus de Discord n'ont pas d'expéditeur pour choisir — ils
prennent `default_animation`, réglable dans le panneau admin.

### Destinataire

Par défaut un média part sur **tous les écrans**. Le panneau permet aussi de **viser une seule
personne** : le serveur ne diffuse alors qu'aux connexions de ce compte Discord, et n'attend
d'accusé de réception que de celles-là.

Un média ciblé arrive marqué `private` : l'overlay affiche « *auteur* → vous » à la place du
seul pseudo. Sans ce repère, le destinataire n'aurait aucun moyen de savoir que les autres ne
l'ont pas vu.

`GET /participants` liste les personnes en ligne, accessible à tout membre authentifié — il ne
révèle que ce que les intéressés voient déjà les uns des autres sur Discord, et jamais d'IP.
On ne peut pas se viser soi-même.

### Interface

Glisser-déposer un fichier **sur le panneau**, plus un bouton « Parcourir ». Le glisser-déposer
ne peut pas viser la fenêtre d'overlay, qui est click-through par construction. Barre de
progression pendant le transfert, et un choix de destinataire au-dessus.

L'auteur affiché est le compte Discord authentifié du client qui envoie — avatar et pseudo
fonctionnent à l'identique quelle que soit la source (§4).

### Rétention — arbitré

| Point | Valeur |
|---|---|
| Taille maximale par fichier | **5 Go** |
| Suppression | **10 min après que tous les participants ont fini de recevoir le média** |
| Plafond absolu | 1 h après la diffusion, quoi qu'il arrive |
| Purge au démarrage | oui — le dossier des médias est vidé au lancement du serveur |
| Quota disque total | 30 Go par défaut, refus d'upload au-delà |
| Débit montant du host | ✅ mesuré, non limitant (voir ci-dessus) |

Toutes ces valeurs sont des **défauts modifiables à chaud depuis le panneau admin** (§7), pas
des constantes de fichier de config.

**Comment le serveur sait qu'un média est « reçu » :** chaque overlay envoie un accusé sur le
WebSocket quand il en a terminé avec le média — image affichée jusqu'au bout, ou vidéo lue
jusqu'à la fin. Un simple suivi des octets servis sur `GET /media/{id}` ne suffirait pas : avec
les requêtes Range, un média est tiré en dizaines de morceaux partiels et « fini » n'y a pas de
définition claire.

Le compte à rebours de 10 min démarre à l'accusé du **dernier** participant connecté au moment
de la diffusion. Deux garde-fous indispensables :

- **Plafond absolu à 1 h.** Sans lui, un participant qui coupe son PC en pleine réception laisse
  le fichier sur le disque indéfiniment.
- **Aucun participant connecté** au moment de la diffusion → le compte à rebours démarre
  immédiatement.

Avec 10 min de rétention, l'occupation disque est bornée par le débit d'envoi, pas par
l'accumulation : le quota ne sert plus qu'à encaisser plusieurs uploads simultanés — trois
fichiers de 5 Go en parallèle, c'est 15 Go.

---

## 9. Auto-hébergement

Le serveur doit pouvoir tourner **n'importe où** : la machine du host, un VPS, un serveur perso.
La v1 supposait un PC Windows de bureau, au point que `_is_local_server()` accordait les droits
admin à quiconque lançait le client sur la même machine que le serveur. Cette heuristique
disparaît : c'est l'identité Discord qui décide (§7), jamais l'adresse réseau.

### Déploiement

```
docker compose up -d
```

Un `.env` pour ce qui ne change plus après l'installation :

| Variable | Rôle |
|---|---|
| `DISCORD_TOKEN` | token du bot |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | application OAuth2 |
| `DISCORD_GUILD_ID` | serveur Discord dont les membres sont autorisés |
| `OWNER_ID` | identifiant Discord de l'administrateur initial |
| `PUBLIC_URL` | URL publique, pour la redirection OAuth2 |
| `DATA_DIR` | volume des médias et des réglages |

**Tout le reste se règle depuis le panneau admin** (§7). Un fichier à remplir une fois, puis
plus rien.

### TLS

Caddy en frontal, certificat Let's Encrypt automatique. Pour qui a déjà un reverse proxy, le
serveur écoute en HTTP simple derrière et n'impose rien.

### Ce que le client a besoin de savoir

Une seule valeur : **l'URL du serveur**. Plus d'IP à redistribuer à chaque changement, plus de
redirection de port à expliquer, et le fichier de config du client ne contient plus rien de
sensible.

---

## 10. Bugs de la v1 à corriger au passage

1. `gethostbyaddr()` bloquant dans la boucle asyncio du serveur → supprimé (plus d'IP du tout)
2. Double reconnexion WebSocket (`disconnected` **et** `error`) → un seul point + backoff
3. `_mp4_rotation()` et son heuristique WMF → supprimés, Qt6 gère la rotation
4. `QT_MULTIMEDIA_PREFERRED_PLUGINS=windowsmediafoundation` inconditionnel → supprimé
5. Maintien au premier plan : `WS_EX_NOACTIVATE` + réaffirmation périodique du topmost

---

## 11. Hors scope, explicitement

- **File d'attente des médias** — écarté, un nouveau média remplace le précédent
- **Historique / replay**
- **Injection de DLL** pour dessiner sur le plein écran exclusif — risque de bannissement
  anti-cheat (EAC, BattlEye) disproportionné pour l'usage
