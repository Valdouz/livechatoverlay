# Installer LiveChat

Ce guide part de zéro. Aucune connaissance en programmation n'est nécessaire, mais il faut
pouvoir taper quelques commandes dans un terminal.

Comptez une vingtaine de minutes, dont l'essentiel sur le site de Discord.

---

## En une commande

Si vous avez déjà une application Discord et un nom de domaine, tout tient dans ceci :

```bash
curl -fsSL https://raw.githubusercontent.com/Valdouz/livechatoverlay/main/install.sh | bash
```

Le script installe Docker au besoin, pose les questions une par une, écrit la configuration
et démarre tout. Le relancer plus tard met l'instance à jour sans rien redemander.

Le reste de ce guide détaille chaque étape, notamment la création de l'application Discord.

---

## Ce qu'il vous faut

- Un serveur Discord dont vous êtes administrateur
- Une machine qui reste allumée : un PC, un Raspberry Pi, un VPS, peu importe
- [Docker](https://docs.docker.com/get-docker/) — le script l'installe si besoin
- Un nom de domaine. **Un tunnel Cloudflare évite d'ouvrir le moindre port** et fonctionne
  même derrière une box que vous ne contrôlez pas

---

## 1. Activer le mode développeur de Discord

Vous en aurez besoin pour copier des identifiants.

Discord → **Paramètres utilisateur** → **Avancés** → activez **Mode développeur**.

Désormais, un clic droit sur un serveur, un salon ou une personne propose **Copier
l'identifiant**.

---

## 2. Créer l'application Discord

Rendez-vous sur [discord.com/developers/applications](https://discord.com/developers/applications)
et cliquez **New Application**. Donnez-lui le nom que vous voulez.

### Onglet « Bot »

1. Cliquez **Reset Token**, puis copiez le jeton affiché.
   → c'est votre `DISCORD_TOKEN`. **Il ne s'affiche qu'une fois.**
2. Plus bas, dans **Privileged Gateway Intents**, activez **Message Content Intent**.
   Sans ça, le bot ne verra pas ce qui est posté.

### Onglet « OAuth2 »

1. Copiez le **Client ID** → `DISCORD_CLIENT_ID`
2. Cliquez **Reset Secret**, copiez-le → `DISCORD_CLIENT_SECRET`
3. Dans **Redirects**, ajoutez exactement :

   ```
   https://votre-domaine.fr/auth/callback
   ```

   Cette adresse doit correspondre **au caractère près** à ce que vous mettrez dans
   `PUBLIC_URL`. C'est la cause numéro un des échecs de connexion.

### Inviter le bot sur votre serveur

Toujours dans **OAuth2**, section **URL Generator** :

- **Scopes** : cochez `bot`
- **Bot Permissions** : cochez `Read Messages/View Channels` et `Read Message History`

Copiez l'URL générée en bas, ouvrez-la, choisissez votre serveur.

---

## 3. Récupérer les deux derniers identifiants

- **Votre serveur Discord** : clic droit sur son icône → Copier l'identifiant
  → `DISCORD_GUILD_ID`
- **Vous-même** : clic droit sur votre pseudo → Copier l'identifiant → `OWNER_ID`

`OWNER_ID` fait de vous le propriétaire de l'instance. C'est vous, et vous seul, qui
nommerez les administrateurs — depuis l'application, sans jamais retoucher un fichier.

---

## 4. Installer le serveur

```bash
git clone https://github.com/Valdouz/livechatoverlay.git
cd livechatoverlay
cp .env.example .env
```

Ouvrez `.env` dans un éditeur de texte et collez vos six valeurs, plus votre domaine :

```ini
DISCORD_TOKEN=...
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...
DISCORD_GUILD_ID=...
OWNER_ID=...
PUBLIC_URL=https://votre-domaine.fr
DOMAIN=votre-domaine.fr
```

Puis démarrez, selon la façon dont vos amis vous atteindront :

```bash
docker compose --profile cloudflare up -d   # tunnel Cloudflare, aucun port ouvert
docker compose --profile caddy up -d        # Caddy + Let's Encrypt, ports 80 et 443
docker compose up -d                        # derrière votre propre reverse proxy
```

### Tunnel Cloudflare — recommandé

Aucun port entrant à ouvrir : le tunnel se connecte **sortant** vers Cloudflare, qui se
charge du certificat. C'est la seule méthode qui marche derrière une box ou un pare-feu
que vous ne maîtrisez pas.

Sur [one.dash.cloudflare.com](https://one.dash.cloudflare.com) → **Networks** → **Tunnels** :

1. **Create a tunnel** → Cloudflared, donnez-lui un nom
2. copiez le **jeton** affiché — la longue chaîne qui suit `--token`
3. onglet **Public Hostname** → **Add** :
   - *Subdomain / Domain* : votre domaine, par exemple `livechat.exemple.fr`
   - *Service* : **HTTP** → `livechat:3000`

Puis dans `.env` :

```ini
COMPOSE_PROFILES=cloudflare
CLOUDFLARE_TUNNEL_TOKEN=le-jeton-copié
```

### Caddy

Certificat Let's Encrypt automatique, mais il faut que les ports **80 et 443** soient
ouverts et que le domaine pointe sur la machine.

Pour vérifier que ça tourne :

```bash
curl https://votre-domaine.fr/health
# {"service": "livechat", "version": 2, "connected": 0}
```

Et dans un navigateur, `https://votre-domaine.fr` affiche la **page d'accueil** : l'adresse
du serveur avec un bouton pour la copier, et le lien de téléchargement du client. C'est la
seule chose que vous avez à partager.

Et pour suivre les journaux :

```bash
docker compose logs -f livechat
```

---

## 5. Choisir le salon à surveiller

Au premier démarrage, aucun salon n'est surveillé — le journal vous le signale.

Ouvrez le client LiveChat, connectez-vous avec votre compte Discord : vous êtes reconnu
comme propriétaire, le panneau admin apparaît. Choisissez-y le salon, et réglez au passage
le quota disque, la taille maximale des fichiers et la durée d'affichage.

Ces réglages prennent effet immédiatement, sans redémarrage.

---

## 6. Distribuer le client

```bash
pip install -r requirements-client.txt
python build_client.py
```

Vous obtenez un exécutable autonome dans `dist/`. Il ne fonctionne que sur le système qui
l'a compilé : relancez le script sur Windows, macOS et Linux si vous voulez couvrir les
trois.

### Ce que vous donnez aux autres

**Une seule chose : l'adresse de votre serveur.**

Ils l'ouvrent dans un navigateur, la page leur propose le téléchargement du client et
affiche l'adresse à y coller. Ils se connectent avec Discord — s'ils sont membres de votre
serveur, ça marche ; sinon c'est refusé.

### Comment le client sait sur quel serveur il est

L'exécutable est le même pour tout le monde : l'adresse n'est pas compilée dedans. Quatre
façons de la lui donner, par ordre de priorité :

| | |
|---|---|
| `LiveChat --server https://…` | pour un raccourci ou un script de lancement |
| un fichier `server.txt` à côté de l'exécutable | le host distribue deux fichiers, ses amis n'ont **rien à saisir** |
| la variable `LIVECHAT_SERVER` | pour un déploiement automatisé |
| la saisie au premier lancement | le cas normal — l'adresse vient de la page d'accueil |

Une adresse imposée au lancement l'emporte sur celle enregistrée : c'est ce qui permet de
faire basculer tout le monde sur un nouveau serveur sans que personne n'ait à toucher à ses
réglages.

### Sur Linux

Le client force son passage par XWayland (`QT_QPA_PLATFORM=xcb`). C'est nécessaire : sous
Wayland, une application ordinaire ne peut ni se positionner en coordonnées globales ni
rester au premier plan. Tous les overlays qui fonctionnent sous GNOME font la même chose.

---

## Sans nom de domaine

Un nom de domaine coûte quelques euros par an, et c'est le plus simple. Mais si vous n'en
voulez pas :

**En réseau local**, tout le monde sur la même box. Dans `docker-compose.yml`, supprimez le
service `caddy` et décommentez le bloc `ports` du service `livechat`. Puis dans `.env` :

```ini
PUBLIC_URL=http://192.168.1.42:3000
```

en remplaçant par l'adresse locale de la machine. Déclarez la même adresse suivie de
`/auth/callback` dans les redirections OAuth2 du portail Discord.

**Par un tunnel.** [Tailscale](https://tailscale.com) ou
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
exposent votre machine sans ouvrir le moindre port sur votre box. Utilisez l'adresse fournie
par le tunnel comme `PUBLIC_URL`.

---

## Sans Docker

```bash
pip install -r requirements-server.txt
python -m server
```

Les variables du `.env` doivent être présentes dans l'environnement. Mettez le serveur
derrière un reverse proxy en HTTPS : Discord refuse les redirections OAuth2 en HTTP simple,
sauf sur `localhost`.

---

## En cas de problème

**« Discord a refusé la connexion »** — l'URL de redirection déclarée dans le portail ne
correspond pas exactement à `PUBLIC_URL` + `/auth/callback`. Vérifiez `http` contre `https`,
et l'absence de barre oblique finale.

**« Vous n'êtes pas membre du serveur Discord »** — le compte utilisé n'est pas dans le
serveur désigné par `DISCORD_GUILD_ID`, ou bien le bot n'y a pas été invité.

**Rien ne s'affiche quand on poste dans Discord** — soit aucun salon n'est sélectionné dans
le panneau admin, soit **Message Content Intent** n'est pas activé dans l'onglet Bot.

**« Espace insuffisant sur le serveur »** — le quota est atteint. Augmentez-le dans le
panneau admin : les médias étant supprimés peu après leur réception, quelques dizaines de
gigaoctets suffisent largement.
