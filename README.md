# Application Syndic

Application de bureau pour gérer les copropriétaires, les paiements, les dépenses,
les réclamations et les rappels d'un syndic. Elle utilise Python, Tkinter et SQLite.

## Prérequis

- Windows
- Python 3.11 ou plus récent
- `pip` pour installer les outils de développement

Le fonctionnement de l'application utilise uniquement la bibliothèque standard Python.
Les tests utilisent `pytest`.

## Installation

```powershell
git clone https://github.com/Pedro-K98/FirstProject.git
cd FirstProject
python -m pip install -r requirements.txt
```

## Premier lancement

```powershell
python main.py
```

La base `syndic.db` et le dossier `sauvegardes/` sont créés à côté de l'application.
Le compte administrateur initial est `admin` / `admin`. Le changement du mot de passe
est obligatoire lors de la première connexion.

## Onglets principaux

- **Tableau de bord** : statistiques et synthèse financière.
- **Copropriétaires** : créer, modifier et désactiver des personnes.
- **Paiements** : enregistrer les paiements, choisir le mode de paiement et consulter le reste à payer.
- **Dépenses** : enregistrer les dépenses par type.
- **Réclamations** : créer une réclamation, changer son statut et consulter son historique.
- **Rappels** : créer un rappel, générer les rappels de retard, les escalader et les envoyer par e-mail.
- **Utilisateurs** : gérer les comptes.
- **Journal** : consulter les actions enregistrées.
- **Paramètres** : créer ou restaurer une sauvegarde.

Les tableaux disposent d'une recherche locale et de filtres par statut lorsque c'est pertinent.

## Tests

```powershell
python -m pytest -q
```

Un résultat correct affiche actuellement `24 passed`.

## Sauvegardes

Depuis **Paramètres**, utilisez les boutons de création ou de restauration. En ligne de commande :

```powershell
python -c "import sauvegarde; print(sauvegarde.sauvegarder(force=True))"
```

Une restauration crée d'abord une copie de sécurité horodatée, puis remplace la base après double confirmation.

## Configuration SMTP

L'envoi réel est désactivé par défaut. Définissez les variables dans l'environnement Windows :

```powershell
$env:ENVOI_EMAIL_REEL = "1"
$env:SMTP_SERVEUR = "smtp.example.com"
$env:SMTP_PORT = "587"
$env:SMTP_UTILISATEUR = "adresse@example.com"
$env:SMTP_PASSWORD = "votre-mot-de-passe"
$env:SMTP_EXPEDITEUR = "adresse@example.com"
python main.py
```

Ne commitez jamais un fichier `.env` ou un mot de passe SMTP. En cas d'échec SMTP,
le rappel reste `En attente` et l'échec est journalisé.

## Structure du projet

- `main.py` : point d'entrée.
- `config.py` : chemins, devise et paramètres SMTP.
- `migrations.py` : migrations SQLite versionnées.
- `sauvegarde.py` : sauvegardes et copies de sécurité.
- `db.py` : accès SQLite et opérations CRUD.
- `services.py` : règles métier, permissions et sessions.
- `ui.py` : interface Tkinter.
- `tests/` : tests automatisés.

## API résident Amana

La maquette Amana reste statique dans cette phase. L'API est séparée dans `api/` et
utilise des tokens de session opaques révoquables, déjà compatibles avec les sessions
de l'application. Les montants JSON sont toujours des entiers en centimes de MAD.

Lancer le serveur :

```powershell
python -m uvicorn api.app:app --reload --port 8000
```

Origine autorisée par défaut : `http://localhost:5173`. Elle peut être changée avec
la variable `PWA_ORIGINE`.

Endpoints résident :

- `POST /auth/login` : obtenir un token avec `identifiant` et `mot_de_passe`.
- `GET /me` : identité et lots/appartements associés.
- `GET /appels-de-fonds` : obligations de paiement du résident et `impaye_centimes`.
- `GET /paiements` : historique des paiements, en centimes.
- `POST /reclamations` : créer une réclamation avec `priorite` optionnelle.
- `GET /reclamations` : réclamations du résident connecté uniquement.
- `GET /rappels` : rappels liés à ses paiements.

Exemple :

```powershell
$login = Invoke-RestMethod http://localhost:8000/auth/login -Method Post `
	-ContentType 'application/json' -Body '{"identifiant":"resident_a","mot_de_passe":"motdepasse-a"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod http://localhost:8000/me -Headers $headers
Invoke-RestMethod http://localhost:8000/paiements -Headers $headers
```

Après trois échecs de connexion, le compte résident est bloqué pendant 15 minutes.
Un résident ne peut jamais lire les données d'un autre résident : le contrôle est
effectué dans `services.py`, pas seulement dans les routes HTTP.

## Faire évoluer la base

Ajoutez une nouvelle fonction de migration à `migrations.py`, avec un numéro supérieur
au dernier existant, puis ajoutez-la à `MIGRATIONS`. Ne modifiez jamais une migration
déjà publiée. La base est sauvegardée avant chaque migration.
