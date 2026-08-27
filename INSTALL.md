# Installer LiveChat

Ce guide part de zéro. Aucune connaissance en programmation n'est nécessaire, mais il faut
pouvoir taper quelques commandes dans un terminal.

Comptez une vingtaine de minutes, dont l'essentiel sur le site de Discord.

---

## Ce qu'il vous faut

- Un serveur Discord dont vous êtes administrateur
- Une machine qui reste allumée : un PC, un Raspberry Pi, un VPS, peu importe
- [Docker](https://docs.docker.com/get-docker/) installé sur cette machine
- Un nom de domaine pointant vers elle (voir [Sans nom de domaine](#sans-nom-de-domaine) si
  vous n'en avez pas)

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

Puis lancez :

```bash
docker compose up -d
```

C'est tout. Caddy obtient le certificat HTTPS tout seul, en général en moins d'une minute.

Pour vérifier que ça tourne :

```bash
curl https://votre-domaine.fr
# {"service": "livechat", "version": 2, "connected": 0}
```

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

## Ce que vous donnez aux autres

Une seule chose : **l'adresse de votre serveur**, `https://votre-domaine.fr`.

Ils installent le client, collent l'adresse, se connectent avec Discord. S'ils sont membres
de votre serveur Discord, ça marche. Sinon, c'est refusé.

Aucun fichier de configuration à distribuer, aucune adresse IP à mettre à jour, aucun port
à ouvrir sur leur box.

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
pip install -r requirements.txt
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
