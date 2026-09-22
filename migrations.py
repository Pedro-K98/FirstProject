"""Migrations SQLite versionnees. Une migration publiee ne doit jamais etre modifiee."""
from datetime import datetime
import hashlib
import os

import sauvegarde


def _migration_utilisateurs(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS Utilisateurs (
        UtilisateurID INTEGER PRIMARY KEY AUTOINCREMENT,
        CoproprietaireID INTEGER,
        Identifiant TEXT NOT NULL UNIQUE,
        MotDePasseHache BLOB NOT NULL,
        Sel BLOB NOT NULL,
        Role TEXT NOT NULL CHECK (Role IN ('Admin', 'Resident')),
        Actif INTEGER NOT NULL DEFAULT 1 CHECK (Actif IN (0, 1)),
        DateCreation TEXT NOT NULL,
        FOREIGN KEY (CoproprietaireID) REFERENCES Coproprietaires(CoproprietaireID)
    );
    CREATE TABLE IF NOT EXISTS JournalActions (
        JournalActionID INTEGER PRIMARY KEY AUTOINCREMENT,
        UtilisateurID INTEGER NOT NULL,
        Action TEXT NOT NULL,
        Details TEXT,
        DateHeure TEXT NOT NULL,
        FOREIGN KEY (UtilisateurID) REFERENCES Utilisateurs(UtilisateurID)
    );
    CREATE INDEX IF NOT EXISTS idx_journal_utilisateur
        ON JournalActions(UtilisateurID);
    """)


def _migration_centimes(conn):
    # Les anciennes versions utilisaient des montants en monnaie flottante.
    # La conversion est faite une seule fois, dans la migration versionnee.
    conn.execute("""
        UPDATE Paiements
        SET MontantDu = CAST(ROUND(COALESCE(MontantDu, 0) * 100) AS INTEGER),
            MontantPaye = CAST(ROUND(COALESCE(MontantPaye, 0) * 100) AS INTEGER)
    """)
    conn.execute("""
        UPDATE Depenses
        SET Montant = CAST(ROUND(COALESCE(Montant, 0) * 100) AS INTEGER)
    """)


def _migration_comptes_phase_3(conn):
    colonnes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(Utilisateurs)")}
    if "ChangementMotDePasseObligatoire" not in colonnes:
        conn.execute("""
            ALTER TABLE Utilisateurs ADD COLUMN ChangementMotDePasseObligatoire
            INTEGER NOT NULL DEFAULT 0 CHECK (ChangementMotDePasseObligatoire IN (0, 1))
        """)

    if conn.execute("SELECT 1 FROM Utilisateurs WHERE Role = 'Admin' LIMIT 1").fetchone():
        return
    sel = os.urandom(16)
    empreinte = hashlib.pbkdf2_hmac(
        "sha256", b"admin", sel, 200_000)
    conn.execute("""
        INSERT INTO Utilisateurs
            (CoproprietaireID, Identifiant, MotDePasseHache, Sel, Role,
             Actif, DateCreation, ChangementMotDePasseObligatoire)
        VALUES (NULL, 'admin', ?, ?, 'Admin', 1, ?, 1)
    """, (empreinte, sel, datetime.now().isoformat(timespec="seconds")))


MIGRATIONS = (
    (1, "comptes utilisateurs et journal", _migration_utilisateurs),
    (2, "conversion des montants en centimes", _migration_centimes),
    (9, "comptes administrateur et changement de mot de passe obligatoire",
     _migration_comptes_phase_3),
)


def appliquer(conn, chemin_base):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for numero, _description, migration in MIGRATIONS:
        if numero <= version:
            continue
        sauvegarde.sauvegarder(chemin_base, force=True)
        migration(conn)
        conn.execute(f"PRAGMA user_version = {numero}")
        conn.commit()
    sauvegarde.sauvegarde_quotidienne(chemin_base)
