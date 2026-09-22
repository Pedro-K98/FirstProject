# Construire la version Windows

## Préparer l'environnement

```powershell
python -m pip install -r requirements.txt
```

## Générer l'exécutable

Depuis la racine du projet :

```powershell
python -m PyInstaller --onefile --windowed --name SyndicApp main.py
```

L'exécutable est créé dans `dist/SyndicApp.exe`. Au premier lancement, il crée
`syndic.db` et `sauvegardes/` dans le même dossier que l'exécutable.

## Distribution

Pour cette version, distribuez `dist/SyndicApp.exe`. Le dossier doit être accessible
en écriture car la base et les sauvegardes sont placées à côté de l'exécutable.

Les exécutables PyInstaller peuvent être signalés par certains antivirus et sont
généralement volumineux, car ils embarquent Python. Une signature numérique est
recommandée pour une distribution publique.
