# MODOP — Utilisateur (les autres)

## Ce dont tu as besoin

Demande au host ces 2 fichiers :
```
LiveChatOverlay.exe
config.json
```

## Installation

1. Crée un dossier sur ton PC, par exemple `C:\LiveChatOverlay\`
2. Mets les 2 fichiers dans ce dossier :
   ```
   C:\LiveChatOverlay\
   ├── LiveChatOverlay.exe
   └── config.json
   ```

## Lancement

1. Lance `LiveChatOverlay.exe`
2. Une fenêtre transparente s'ouvre sur tout ton écran — c'est normal, elle est invisible
3. Les clics de souris passent à travers, tu peux utiliser ton PC normalement

## Utilisation

- Quand quelqu'un poste une image ou vidéo dans le salon Discord désigné, elle apparaît en bas à droite de ton écran
- Les images disparaissent automatiquement après quelques secondes
- Les vidéos disparaissent à la fin de leur lecture

## Fermer l'overlay

Cherche `LiveChatOverlay` dans la barre des tâches (icône dans la zone de notification) ou via le Gestionnaire des tâches (`Ctrl+Shift+Échap`).

---

## En cas de problème

**L'overlay ne se connecte pas / écran noir :**
- Vérifie que le host a bien lancé le bot (`start.bat`)
- Vérifie que tu as bien les 2 fichiers dans le même dossier
- Demande au host son IP actuelle (elle peut changer)

**Windows bloque le .exe (avertissement SmartScreen) :**
- Clique sur "Informations complémentaires" → "Exécuter quand même"
- C'est normal pour un .exe non signé
