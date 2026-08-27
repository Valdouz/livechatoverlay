# LiveChat

Partage de médias entre proches, affiché en overlay transparent sur le bureau de chaque
participant. Un média posté dans un salon Discord — ou envoyé directement depuis l'appli —
apparaît en temps réel sur tous les écrans du groupe.

---

## 🚧 Refonte en cours

La v1 est **archivée** et le code est reparti de zéro pour la v2. Ce dépôt ne contient pour
l'instant que la spécification.

| | |
|---|---|
| **Spécification de la v2** | [SPEC_V2.md](SPEC_V2.md) |
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

Le détail, les arbitrages et ce qui a été explicitement écarté sont dans
[SPEC_V2.md](SPEC_V2.md).
