#!/usr/bin/env bash
# Installation de LiveChat sur un serveur Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/Valdouz/livechatoverlay/main/install.sh | bash
#
# Relancer le script sur une instance existante la met à jour sans rien redemander.

set -euo pipefail

REPO="https://github.com/Valdouz/livechatoverlay.git"
DIR="${LIVECHAT_DIR:-$HOME/livechat}"

BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; OFF=$'\e[0m'

say()  { printf '%s\n' "$*"; }
step() { printf '\n%s==>%s %s%s\n' "$GREEN" "$OFF" "$BOLD" "$*"; printf '%s' "$OFF"; }
warn() { printf '%s!!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '\n%serreur :%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

# Le script se lit souvent par « curl | bash » : stdin est alors le script
# lui-même. Toutes les saisies passent donc par /dev/tty.
[ -e /dev/tty ] || die "Aucun terminal disponible. Clonez le dépôt et lancez bash install.sh."

# -- prérequis ---------------------------------------------------------------

step "Vérification des prérequis"

command -v git >/dev/null 2>&1 || die "git n'est pas installé.  sudo apt install git"

if ! command -v docker >/dev/null 2>&1; then
  warn "Docker n'est pas installé."
  read -rp "L'installer maintenant ? [O/n] " answer < /dev/tty
  if [[ "${answer:-o}" =~ ^[OoYy]?$ ]]; then
    curl -fsSL https://get.docker.com | sh || die "Installation de Docker échouée."
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    warn "Docker installé. Si la suite refuse l'accès, déconnectez-vous puis reconnectez-vous."
  else
    die "Docker est nécessaire.  https://docs.docker.com/engine/install/"
  fi
fi

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if sudo docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
    warn "Docker nécessite sudo sur cette machine, le script l'utilisera."
  else
    die "Docker est installé mais ne répond pas. Démarrez-le :  sudo systemctl start docker"
  fi
fi

$DOCKER compose version >/dev/null 2>&1 \
  || die "Le plugin 'docker compose' est absent.  https://docs.docker.com/compose/install/"

say "  git, Docker et Compose sont là."

# -- code source -------------------------------------------------------------

if [ -d "$DIR/.git" ]; then
  step "Mise à jour de $DIR"
  git -C "$DIR" pull --ff-only || warn "Mise à jour impossible, on garde la version en place."
else
  step "Récupération du code dans $DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

# -- configuration -----------------------------------------------------------

ask() {  # ask <variable> <question> [valeur-actuelle]
  local var="$1" question="$2" current="${3:-}" answer
  if [ -n "$current" ]; then
    read -rp "  $question [$current] : " answer < /dev/tty
    printf -v "$var" '%s' "${answer:-$current}"
  else
    while :; do
      read -rp "  $question : " answer < /dev/tty
      [ -n "$answer" ] && break
      say "    ${DIM}Cette valeur est obligatoire.${OFF}"
    done
    printf -v "$var" '%s' "$answer"
  fi
}

ask_secret() {  # ask_secret <variable> <question> [valeur-actuelle]
  local var="$1" question="$2" current="${3:-}" answer
  local hint=""
  [ -n "$current" ] && hint=" [inchangé si vide]"
  read -rsp "  $question$hint : " answer < /dev/tty; echo
  printf -v "$var" '%s' "${answer:-$current}"
  [ -n "${!var}" ] || die "$question est obligatoire."
}

if [ -f .env ]; then
  step "Configuration existante trouvée"
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
  say "  Serveur : ${PUBLIC_URL:-?}"
  read -rp "  La modifier ? [o/N] " change < /dev/tty
  [[ "${change:-n}" =~ ^[OoYy]$ ]] && NEED_CONFIG=1 || NEED_CONFIG=0
else
  NEED_CONFIG=1
fi

if [ "$NEED_CONFIG" = "1" ]; then
  step "Configuration"
  cat <<'EXPLAIN'
  Tout se trouve sur https://discord.com/developers/applications
  Le guide détaillé est dans INSTALL.md. Activez le mode développeur de Discord
  (Paramètres > Avancés) pour pouvoir copier les identifiants.

EXPLAIN
  ask_secret DISCORD_TOKEN         "Token du bot (onglet Bot > Reset Token)" "${DISCORD_TOKEN:-}"
  ask        DISCORD_CLIENT_ID     "Client ID (onglet OAuth2)"               "${DISCORD_CLIENT_ID:-}"
  ask_secret DISCORD_CLIENT_SECRET "Client Secret (onglet OAuth2)"           "${DISCORD_CLIENT_SECRET:-}"
  ask        DISCORD_GUILD_ID      "Identifiant de votre serveur Discord"    "${DISCORD_GUILD_ID:-}"
  ask        OWNER_ID              "Votre identifiant Discord (vous serez propriétaire)" "${OWNER_ID:-}"
  ask        DOMAIN                "Nom de domaine du service (ex. livechat.exemple.fr)" "${DOMAIN:-}"

  DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
  PUBLIC_URL="https://$DOMAIN"

  step "Comment vos amis atteindront-ils ce serveur ?"
  cat <<'CHOICES'
    1) Tunnel Cloudflare  — aucun port à ouvrir, TLS géré par Cloudflare.
                            Le plus simple, et le seul qui marche derrière une
                            box ou un pare-feu que vous ne contrôlez pas.
    2) Caddy              — certificat Let's Encrypt automatique, mais il faut
                            que les ports 80 et 443 soient ouverts et que le
                            domaine pointe sur cette machine.
    3) Aucun              — vous avez déjà un reverse proxy devant.

CHOICES
  read -rp "  Votre choix [1] : " exposure < /dev/tty
  case "${exposure:-1}" in
    1) COMPOSE_PROFILES="cloudflare" ;;
    2) COMPOSE_PROFILES="caddy" ;;
    3) COMPOSE_PROFILES="" ;;
    *) die "Choix invalide." ;;
  esac

  if [ "$COMPOSE_PROFILES" = "cloudflare" ]; then
    cat <<EOF

  Sur ${BOLD}https://one.dash.cloudflare.com${OFF} > Networks > Tunnels :
    1. ${BOLD}Create a tunnel${OFF} > Cloudflared, donnez-lui un nom
    2. copiez le ${BOLD}jeton${OFF} affiché (la longue chaîne après --token)
    3. onglet ${BOLD}Public Hostname${OFF} > Add :
         Subdomain / Domain : ${BOLD}$DOMAIN${OFF}
         Service            : ${BOLD}HTTP${OFF}  →  ${BOLD}livechat:3000${OFF}

EOF
    ask_secret CLOUDFLARE_TUNNEL_TOKEN "Jeton du tunnel" "${CLOUDFLARE_TUNNEL_TOKEN:-}"
  fi

  umask 077
  cat > .env <<EOF
# Écrit par install.sh — ne pas versionner, ne pas partager.
DISCORD_TOKEN=$DISCORD_TOKEN
DISCORD_CLIENT_ID=$DISCORD_CLIENT_ID
DISCORD_CLIENT_SECRET=$DISCORD_CLIENT_SECRET
DISCORD_GUILD_ID=$DISCORD_GUILD_ID
OWNER_ID=$OWNER_ID
PUBLIC_URL=$PUBLIC_URL
DOMAIN=$DOMAIN
DATA_DIR=/data
HOST=0.0.0.0
PORT=3000

# Mode d'exposition retenu : les commandes docker compose suivantes le reprennent
# toutes seules, sans avoir à repasser --profile.
COMPOSE_PROFILES=$COMPOSE_PROFILES
CLOUDFLARE_TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
EOF
  chmod 600 .env
  say "  ${GREEN}.env écrit${OFF} (lisible par vous seul)"
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

# -- redirection OAuth2 ------------------------------------------------------

step "À déclarer dans le portail Discord"
cat <<EOF
  Onglet ${BOLD}OAuth2${OFF} > section ${BOLD}Redirects${OFF}, ajoutez exactement :

      ${BOLD}$PUBLIC_URL/auth/callback${OFF}

  Au caractère près. C'est la première cause d'échec de connexion.
EOF
read -rp "  Fait ? [Entrée pour continuer] " _ < /dev/tty

# -- démarrage ---------------------------------------------------------------

step "Construction et démarrage"
$DOCKER compose up -d --build

step "Attente de la mise en ligne"
case "${COMPOSE_PROFILES:-}" in
  cloudflare) say "  ${DIM}Le tunnel s'établit vers Cloudflare.${OFF}" ;;
  caddy)      say "  ${DIM}Caddy demande le certificat à Let's Encrypt.${OFF}" ;;
  *)          say "  ${DIM}En attente de votre reverse proxy.${OFF}" ;;
esac
ready=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 4 "$PUBLIC_URL/health" >/dev/null 2>&1; then ready=1; break; fi
  printf '.'; sleep 3
done
echo

if [ "$ready" = "1" ]; then
  cat <<EOF

${GREEN}${BOLD}LiveChat tourne.${OFF}

  Adresse à donner à vos amis :  ${BOLD}$PUBLIC_URL${OFF}

  Ils ouvrent cette adresse dans un navigateur : la page leur propose le
  téléchargement du client et l'adresse à y coller. Rien d'autre à distribuer.

  ${DIM}Journaux      :${OFF} cd $DIR && $DOCKER compose logs -f livechat
  ${DIM}Redémarrer    :${OFF} cd $DIR && $DOCKER compose restart
  ${DIM}Mettre à jour :${OFF} bash $DIR/install.sh

  Lancez le client, connectez-vous : vous serez reconnu comme propriétaire.
  Choisissez alors le salon Discord à surveiller dans l'onglet Admin.
EOF
else
  warn "Le serveur ne répond pas encore sur $PUBLIC_URL"
  cat <<EOF

  Le serveur lui-même répond-il en local ?
       ${DIM}curl -s localhost:3000/health${OFF}
  Si oui, le problème est dans l'exposition :

    ${BOLD}Tunnel Cloudflare${OFF}
      ${DIM}cd $DIR && $DOCKER compose logs cloudflared${OFF}
      Vérifiez que le Public Hostname pointe sur ${BOLD}livechat:3000${OFF} en HTTP,
      et que le nom $DOMAIN est bien celui déclaré dans le tunnel.

    ${BOLD}Caddy${OFF}
      ${DIM}dig +short $DOMAIN${OFF}                        le domaine pointe ici ?
      ${DIM}sudo ss -tlnp | grep -E ':(80|443)'${OFF}       les ports sont libres ?
      ${DIM}cd $DIR && $DOCKER compose logs caddy${OFF}

  Les conteneurs tournent, tout repartira dès que le chemin sera ouvert.
EOF
fi
