"""Parametres centralises de l'application."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CHEMIN_BASE = BASE_DIR / "syndic.db"
DOSSIER_SAUVEGARDES = BASE_DIR / "sauvegardes"
DEVISE = "MAD"

# L'ancien nom reste disponible pour les modules existants.
DB_NAME = str(CHEMIN_BASE)
