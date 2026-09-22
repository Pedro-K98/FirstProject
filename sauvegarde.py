"""Sauvegardes de la base avant migration et une fois par jour."""
from datetime import date, datetime
from pathlib import Path
import shutil

import config


def sauvegarder(chemin_base=None, force=False):
    source = Path(chemin_base or config.CHEMIN_BASE)
    if not source.exists():
        return None
    destination_dir = config.DOSSIER_SAUVEGARDES
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"syndic-{date.today().isoformat()}.db"
    if force or not destination.exists():
        shutil.copy2(source, destination)
    return destination


def sauvegarde_quotidienne(chemin_base=None):
    return sauvegarder(chemin_base)


def sauvegarde_securite(chemin_base=None):
    source = Path(chemin_base or config.CHEMIN_BASE)
    if not source.exists():
        return None
    config.DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = config.DOSSIER_SAUVEGARDES / f"syndic-securite-{horodatage}.db"
    shutil.copy2(source, destination)
    return destination


def lister_sauvegardes():
    config.DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    return sorted(
        (f for f in config.DOSSIER_SAUVEGARDES.glob("*.db") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
