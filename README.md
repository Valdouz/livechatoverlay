# LiveChat

Partage de médias entre proches, affiché en overlay transparent sur le bureau de chaque
participant. Un média posté dans un salon Discord — ou envoyé directement depuis l'appli —
apparaît en temps réel sur tous les écrans du groupe.

---

**Libre, gratuit, auto-hébergeable.** Sous licence AGPL-3.0 : quiconque en propose une
version modifiée en ligne doit en publier le code. Personne ne peut refermer ce projet.

## Installer

```bash
git clone https://github.com/Valdouz/livechatoverlay.git
cd livechatoverlay
cp .env.example .env      # six valeurs à remplir
docker compose up -d
```

Le guide complet, en partant de zéro : **[INSTALL.md](INSTALL.md)**.

Vos participants n'ont besoin que d'une chose : **l'adresse de votre serveur**. Ils se
connectent avec Discord, et s'ils sont membres de votre serveur, ça marche.

## Pour les participants

Récupérez l'exécutable auprès de votre hébergeur, lancez-le, saisissez l'adresse du
serveur, connectez-vous avec Discord. C'est tout : ni fichier de configuration, ni
adresse IP, ni port à ouvrir.

Depuis les sources :

```bash
pip install -r requirements-client.txt
python -m client
```

Pour produire l'exécutable à distribuer :

```bash
python build_client.py
```

## État d'avancement

| | |
|---|---|
| **Serveur** | ✅ auth Discord, envoi de fichiers, rétention, administration |
| **Client** | ✅ overlay peint, panneau complet, envoi par glisser-déposer |
| **Spécification** | [SPEC_V2.md](SPEC_V2.md) |
| **État des lieux de la v1** | [NOTES_V2.md](NOTES_V2.md) |
| **Code de la v1** | branche [`v1`](../../tree/v1) · release [`v1.0.0`](../../releases/tag/v1.0.0) |

---

## Ce que sera la v2

**Client natif PySide6**, Windows / macOS / Linux. Fenêtre unique transparente et
click-through, tout le rendu dans un seul `paintEvent`.

**Deux sources de médias** — un salon Discord, et l'envoi direct d'un fichier depuis l'appli,
jusqu'à 5 Go, sans passer par la limite de Discord.

**Authentification Discord.** Seuls les membres du serveur peuvent recevoir et envoyer. Plus
d'API admin ouverte, plus d'adresses IP exposées.

**Un panneau qui sert à quelque chose** — écran, coin d'ancrage, taille, police, opacité, son.
Les réglages appartiennent au participant, le serveur ne fournit que des valeurs par défaut.

**Auto-hébergeable.** `docker compose up`, un `.env` à remplir une fois, et c'est tout : PC de
bureau, VPS ou serveur perso, au choix.

**Un vrai système d'administration.** Un owner déclaré à l'installation, des admins qu'il promeut
depuis l'appli, et des réglages serveur — quota disque, taille max, rétention, salon surveillé —
modifiables à chaud depuis le panneau, sans accès à la machine ni redémarrage.

Le détail, les arbitrages et ce qui a été explicitement écarté sont dans
[SPEC_V2.md](SPEC_V2.md).

---

## Développement

```bash
pip install -r requirements.txt

python -m tests.test_server     # 33 vérifications, sans connexion Discord
python -m tests.test_client     # 33 vérifications, sans écran ni serveur

python -m server                # nécessite un .env rempli
python -m client
```

Les tests du client construisent et peignent réellement la fenêtre, dans une image
mémoire : les erreurs de `paintEvent` sont attrapées, pas seulement les imports.

## Licence

[AGPL-3.0](LICENSE). Vous pouvez l'utiliser, le modifier et le redistribuer librement, y
compris commercialement. La seule contrainte : si vous en proposez une version modifiée à
d'autres, par un service en ligne compris, vous devez en publier le code source.
