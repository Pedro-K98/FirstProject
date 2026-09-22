"""Parametres centralises de l'application."""
import os
import sys
from pathlib import Path

BASE_DIR = (Path(sys.executable).resolve().parent
			if getattr(sys, "frozen", False)
			else Path(__file__).resolve().parent)
CHEMIN_BASE = BASE_DIR / "syndic.db"
DOSSIER_SAUVEGARDES = BASE_DIR / "sauvegardes"
DEVISE = "MAD"

# L'envoi réel reste désactivé tant que le serveur SMTP n'est pas configuré.
ENVOI_EMAIL_REEL = os.environ.get("ENVOI_EMAIL_REEL", "0") == "1"
SMTP_SERVEUR = os.environ.get("SMTP_SERVEUR", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_UTILISATEUR = os.environ.get("SMTP_UTILISATEUR", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_EXPEDITEUR = os.environ.get("SMTP_EXPEDITEUR", "syndic@syndic.local")
PWA_ORIGINES = tuple(
	origine.strip() for origine in os.environ.get(
		"PWA_ORIGINES", "http://localhost:5173,http://127.0.0.1:5173"
	).split(",") if origine.strip()
)
# Compatibilité avec les intégrations qui lisent encore ce nom singulier.
PWA_ORIGINE = PWA_ORIGINES[0]

# L'ancien nom reste disponible pour les modules existants.
DB_NAME = str(CHEMIN_BASE)
