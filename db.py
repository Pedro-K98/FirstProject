"""
db.py — Gestion de la base de données du projet Syndic
Contient : connexion, création des tables, fonctions CRUD.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

import config

# La base est toujours créée/lue à côté de ce fichier, même si l'on lance
# le programme depuis un autre dossier.
DB_NAME = config.DB_NAME

# Colonnes de Coproprietaires que l'on a le droit de modifier
# (liste blanche : évite toute injection SQL via le nom de colonne)
CHAMPS_COPROPRIETAIRE = {
    "TypePersonne", "Nom", "Prenom", "Email", "Telephone",
    "Appartement", "SituationFamiliale", "DateInscription", "Actif",
}


def connexion():
    conn = sqlite3.connect(DB_NAME)
    # SQLite n'applique pas les clés étrangères par défaut
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialiser_base():
    """Crée les 5 tables si elles n'existent pas."""
    with closing(connexion()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS Coproprietaires (
            CoproprietaireID   INTEGER PRIMARY KEY AUTOINCREMENT,
            TypePersonne       TEXT,                -- Coproprietaire / Locataire
            Nom                TEXT NOT NULL,
            Prenom             TEXT,
            Email              TEXT,
            Telephone          TEXT,
            Appartement        TEXT,
            SituationFamiliale TEXT,
            DateInscription    TEXT,
            Actif              INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS Paiements (
            PaiementID       INTEGER PRIMARY KEY AUTOINCREMENT,
            CoproprietaireID INTEGER NOT NULL,
            Mois             TEXT,
            DatePaiement     TEXT,
            MontantDu        INTEGER CHECK (MontantDu >= 0),
            MontantPaye      INTEGER CHECK (MontantPaye >= 0),
            Statut           TEXT,                -- Paye / En retard / Impaye
            ModePaiement     TEXT,
            DateEcheance     TEXT,
            FOREIGN KEY (CoproprietaireID) REFERENCES Coproprietaires(CoproprietaireID)
        );

        CREATE TABLE IF NOT EXISTS Depenses (
            DepenseID   INTEGER PRIMARY KEY AUTOINCREMENT,
            DateDepense TEXT,
            TypeDepense TEXT,
            Montant     INTEGER CHECK (Montant >= 0),
            Description TEXT,
            ValidePar   TEXT
        );

        CREATE TABLE IF NOT EXISTS Reclamations (
            ReclamationID    INTEGER PRIMARY KEY AUTOINCREMENT,
            CoproprietaireID INTEGER NOT NULL,
            DateReclamation  TEXT,
            Objet            TEXT,
            Description      TEXT,
            Statut           TEXT DEFAULT 'En attente',
            FOREIGN KEY (CoproprietaireID) REFERENCES Coproprietaires(CoproprietaireID)
        );

        CREATE TABLE IF NOT EXISTS Rappels (
            RappelID         INTEGER PRIMARY KEY AUTOINCREMENT,
            CoproprietaireID INTEGER NOT NULL,
            DateRappel       TEXT,
            TypeRappel       TEXT,
            Message          TEXT,
            StatutEnvoi      TEXT DEFAULT 'En attente',
            FOREIGN KEY (CoproprietaireID) REFERENCES Coproprietaires(CoproprietaireID)
        );
        """)
        # Migration : un rappel peut être rattaché au paiement en retard qui l'a déclenché
        # (évite de générer deux fois le même rappel). Sans effet si la colonne existe déjà.
        colonnes = [r[1] for r in conn.execute("PRAGMA table_info(Rappels)")]
        if "PaiementID" not in colonnes:
            conn.execute("ALTER TABLE Rappels ADD COLUMN PaiementID INTEGER "
                         "REFERENCES Paiements(PaiementID) ON DELETE SET NULL")
        conn.commit()


# ------------------------------------------------------------------
# COPROPRIÉTAIRES
# ------------------------------------------------------------------
def ajouter_coproprietaire(type_personne, nom, prenom, email, telephone,
                           appartement, situation_familiale, date_inscription, actif=1):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO Coproprietaires
                (TypePersonne, Nom, Prenom, Email, Telephone,
                 Appartement, SituationFamiliale, DateInscription, Actif)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (type_personne, nom, prenom, email, telephone,
              appartement, situation_familiale, date_inscription, actif))
        conn.commit()


def lister_coproprietaires():
    with closing(connexion()) as conn:
        return conn.execute(
            "SELECT * FROM Coproprietaires ORDER BY Nom"
        ).fetchall()


def modifier_coproprietaire(coproprietaire_id, champ, valeur):
    """Modifie une seule colonne d'un copropriétaire (ex. champ='Email')."""
    if champ not in CHAMPS_COPROPRIETAIRE:
        raise ValueError(f"Champ non modifiable : {champ}")
    with closing(connexion()) as conn:
        # Le nom de colonne vient de la liste blanche ci-dessus, pas de l'utilisateur
        conn.execute(
            f"UPDATE Coproprietaires SET {champ} = ? WHERE CoproprietaireID = ?",
            (valeur, coproprietaire_id))
        conn.commit()


def compter_coproprietaires():
    """Renvoie (nombre d'actifs, nombre total)."""
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT COALESCE(SUM(COALESCE(Actif, 1) != 0), 0), COUNT(*)
            FROM Coproprietaires
        """).fetchone()


def supprimer_coproprietaire(coproprietaire_id):
    with closing(connexion()) as conn:
        conn.execute("DELETE FROM Coproprietaires WHERE CoproprietaireID = ?",
                     (coproprietaire_id,))
        conn.commit()


# ------------------------------------------------------------------
# PAIEMENTS
# ------------------------------------------------------------------
def ajouter_paiement(coproprietaire_id, mois, date_paiement, montant_du,
                     montant_paye, statut, mode_paiement, date_echeance):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO Paiements
                (CoproprietaireID, Mois, DatePaiement, MontantDu,
                 MontantPaye, Statut, ModePaiement, DateEcheance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (coproprietaire_id, mois, date_paiement, montant_du,
              montant_paye, statut, mode_paiement, date_echeance))
        conn.commit()


def lister_paiements():
    """Jointure : on affiche le nom du copropriétaire, pas juste son ID."""
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT p.PaiementID, c.Nom || ' ' || COALESCE(c.Prenom, ''),
                   p.Mois, p.DatePaiement, p.MontantDu, p.MontantPaye,
                   ROUND(p.MontantDu - p.MontantPaye, 2) AS Impaye,
                   p.Statut, p.ModePaiement, p.DateEcheance
            FROM Paiements p
            JOIN Coproprietaires c ON c.CoproprietaireID = p.CoproprietaireID
            ORDER BY p.DatePaiement DESC
        """).fetchall()


def supprimer_paiement(paiement_id):
    with closing(connexion()) as conn:
        conn.execute("DELETE FROM Paiements WHERE PaiementID = ?", (paiement_id,))
        conn.commit()


def recalculer_statuts_paiements(aujourdhui):
    """Règle unique du statut, appliquée à tous les paiements en une seule requête :
       payé >= dû -> Paye | échéance dépassée -> En retard | sinon -> Impaye."""
    with closing(connexion()) as conn:
        conn.execute("""
            UPDATE Paiements SET Statut = CASE
                WHEN COALESCE(MontantPaye, 0) >= COALESCE(MontantDu, 0) THEN 'Paye'
                WHEN COALESCE(DateEcheance, '') != '' AND DateEcheance < ? THEN 'En retard'
                ELSE 'Impaye'
            END
        """, (aujourdhui,))
        conn.commit()


def totaux_paiements():
    """Renvoie (total dû, total payé, reste à payer, nombre de paiements en retard)."""
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT COALESCE(SUM(MontantDu), 0),
                   COALESCE(SUM(MontantPaye), 0),
                   COALESCE(SUM(MAX(COALESCE(MontantDu, 0) - COALESCE(MontantPaye, 0), 0)), 0),
                   COALESCE(SUM(Statut = 'En retard'), 0)
            FROM Paiements
        """).fetchone()


def top_debiteurs(limite=5):
    """Copropriétaires ayant le plus de reste à payer : (id, nom, appartement, reste)."""
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT c.CoproprietaireID,
                   c.Nom || ' ' || COALESCE(c.Prenom, ''),
                   c.Appartement,
                   ROUND(SUM(MAX(COALESCE(p.MontantDu, 0) - COALESCE(p.MontantPaye, 0), 0)), 2) AS Reste
            FROM Paiements p
            JOIN Coproprietaires c ON c.CoproprietaireID = p.CoproprietaireID
            GROUP BY c.CoproprietaireID
            HAVING Reste > 0
            ORDER BY Reste DESC
            LIMIT ?
        """, (limite,)).fetchall()


def paiements_en_retard_sans_rappel():
    """Paiements 'En retard' d'un copropriétaire actif qui n'ont pas encore de rappel.
       Renvoie (paiement_id, coproprietaire_id, nom, prenom, mois, reste, echeance)."""
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT p.PaiementID, p.CoproprietaireID, c.Nom, COALESCE(c.Prenom, ''),
                   p.Mois, ROUND(p.MontantDu - COALESCE(p.MontantPaye, 0), 2), p.DateEcheance
            FROM Paiements p
            JOIN Coproprietaires c ON c.CoproprietaireID = p.CoproprietaireID
            WHERE p.Statut = 'En retard'
              AND COALESCE(c.Actif, 1) != 0
              AND NOT EXISTS (SELECT 1 FROM Rappels r WHERE r.PaiementID = p.PaiementID)
            ORDER BY p.DateEcheance
        """).fetchall()


# ------------------------------------------------------------------
# DÉPENSES
# ------------------------------------------------------------------
def ajouter_depense(date_depense, type_depense, montant, description, valide_par):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO Depenses (DateDepense, TypeDepense, Montant, Description, ValidePar)
            VALUES (?, ?, ?, ?, ?)
        """, (date_depense, type_depense, montant, description, valide_par))
        conn.commit()


def lister_depenses():
    with closing(connexion()) as conn:
        return conn.execute(
            "SELECT * FROM Depenses ORDER BY DateDepense DESC"
        ).fetchall()


def supprimer_depense(depense_id):
    with closing(connexion()) as conn:
        conn.execute("DELETE FROM Depenses WHERE DepenseID = ?", (depense_id,))
        conn.commit()


def total_depenses():
    with closing(connexion()) as conn:
        return conn.execute("SELECT COALESCE(SUM(Montant), 0) FROM Depenses").fetchone()[0]


def depenses_par_type():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT COALESCE(NULLIF(TypeDepense, ''), '(non renseigné)'),
                   ROUND(SUM(Montant), 2) AS Total
            FROM Depenses
            GROUP BY 1
            ORDER BY Total DESC
        """).fetchall()


# ------------------------------------------------------------------
# RÉCLAMATIONS
# ------------------------------------------------------------------
def ajouter_reclamation(coproprietaire_id, date_reclamation, objet, description, statut):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO Reclamations
                (CoproprietaireID, DateReclamation, Objet, Description, Statut)
            VALUES (?, ?, ?, ?, ?)
        """, (coproprietaire_id, date_reclamation, objet, description, statut))
        conn.commit()


def lister_reclamations():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT r.ReclamationID, c.Nom, r.DateReclamation, r.Objet,
                   r.Description, r.Statut
            FROM Reclamations r
            JOIN Coproprietaires c ON c.CoproprietaireID = r.CoproprietaireID
            ORDER BY r.DateReclamation DESC
        """).fetchall()


def changer_statut_reclamation(reclamation_id, nouveau_statut):
    with closing(connexion()) as conn:
        conn.execute("UPDATE Reclamations SET Statut = ? WHERE ReclamationID = ?",
                     (nouveau_statut, reclamation_id))
        conn.commit()


def reclamations_par_statut():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT COALESCE(Statut, '(sans statut)'), COUNT(*)
            FROM Reclamations
            GROUP BY 1
            ORDER BY 2 DESC
        """).fetchall()


# ------------------------------------------------------------------
# RAPPELS
# ------------------------------------------------------------------
def ajouter_rappel(coproprietaire_id, date_rappel, type_rappel, message,
                   statut_envoi, paiement_id=None):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO Rappels
                (CoproprietaireID, DateRappel, TypeRappel, Message, StatutEnvoi, PaiementID)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (coproprietaire_id, date_rappel, type_rappel, message,
              statut_envoi, paiement_id))
        conn.commit()


def ajouter_rappels_en_masse(rappels):
    """rappels : liste de tuples
       (coproprietaire_id, date_rappel, type_rappel, message, statut_envoi, paiement_id).
       Une seule connexion et une seule transaction pour tout le lot."""
    if not rappels:
        return
    with closing(connexion()) as conn:
        conn.executemany("""
            INSERT INTO Rappels
                (CoproprietaireID, DateRappel, TypeRappel, Message, StatutEnvoi, PaiementID)
            VALUES (?, ?, ?, ?, ?, ?)
        """, rappels)
        conn.commit()


def changer_statut_rappel(rappel_id, nouveau_statut):
    with closing(connexion()) as conn:
        conn.execute("UPDATE Rappels SET StatutEnvoi = ? WHERE RappelID = ?",
                     (nouveau_statut, rappel_id))
        conn.commit()


def compter_rappels_en_attente():
    with closing(connexion()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM Rappels WHERE StatutEnvoi = 'En attente'"
        ).fetchone()[0]


def lister_rappels():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT r.RappelID, c.Nom, r.DateRappel, r.TypeRappel,
                   r.Message, r.StatutEnvoi
            FROM Rappels r
            JOIN Coproprietaires c ON c.CoproprietaireID = r.CoproprietaireID
            ORDER BY r.DateRappel DESC
        """).fetchall()


# ------------------------------------------------------------------
# UTILISATEURS ET JOURNAL
# ------------------------------------------------------------------
def creer_utilisateur(coproprietaire_id, identifiant, mot_de_passe_hache,
                      sel, role, date_creation):
    with closing(connexion()) as conn:
        curseur = conn.execute("""
            INSERT INTO Utilisateurs
                (CoproprietaireID, Identifiant, MotDePasseHache, Sel,
                 Role, Actif, DateCreation)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (coproprietaire_id, identifiant, mot_de_passe_hache, sel,
              role, date_creation))
        conn.commit()
        return curseur.lastrowid


def utilisateur_par_identifiant(identifiant):
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT UtilisateurID, CoproprietaireID, Identifiant,
                   MotDePasseHache, Sel, Role, Actif, DateCreation,
                   ChangementMotDePasseObligatoire
            FROM Utilisateurs WHERE Identifiant = ?
        """, (identifiant,)).fetchone()


def utilisateur_par_id(utilisateur_id):
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT UtilisateurID, CoproprietaireID, Identifiant,
                   MotDePasseHache, Sel, Role, Actif, DateCreation,
                   ChangementMotDePasseObligatoire
            FROM Utilisateurs WHERE UtilisateurID = ?
        """, (utilisateur_id,)).fetchone()


def modifier_mot_de_passe(utilisateur_id, mot_de_passe_hache, sel):
    with closing(connexion()) as conn:
        conn.execute("""
            UPDATE Utilisateurs SET MotDePasseHache = ?, Sel = ?,
                ChangementMotDePasseObligatoire = 0
            WHERE UtilisateurID = ?
        """, (mot_de_passe_hache, sel, utilisateur_id))
        conn.commit()


def desactiver_utilisateur(utilisateur_id):
    with closing(connexion()) as conn:
        conn.execute("UPDATE Utilisateurs SET Actif = 0 WHERE UtilisateurID = ?",
                     (utilisateur_id,))
        conn.commit()


def activer_utilisateur(utilisateur_id):
    with closing(connexion()) as conn:
        conn.execute("UPDATE Utilisateurs SET Actif = 1 WHERE UtilisateurID = ?",
                     (utilisateur_id,))
        conn.commit()


def supprimer_utilisateur(utilisateur_id):
    with closing(connexion()) as conn:
        conn.execute("DELETE FROM JournalActions WHERE UtilisateurID = ?", (utilisateur_id,))
        conn.execute("DELETE FROM Utilisateurs WHERE UtilisateurID = ?", (utilisateur_id,))
        conn.commit()


def compter_administrateurs():
    with closing(connexion()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM Utilisateurs WHERE Role = 'Admin'"
        ).fetchone()[0]


def journaliser(utilisateur_id, action, details, date_heure):
    with closing(connexion()) as conn:
        conn.execute("""
            INSERT INTO JournalActions (UtilisateurID, Action, Details, DateHeure)
            VALUES (?, ?, ?, ?)
        """, (utilisateur_id, action, details, date_heure))
        conn.commit()


def lister_utilisateurs():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT u.UtilisateurID, u.CoproprietaireID, u.Identifiant,
                   u.Role, u.Actif, u.DateCreation,
                   u.ChangementMotDePasseObligatoire,
                   COALESCE(c.Nom || ' ' || COALESCE(c.Prenom, ''), '')
            FROM Utilisateurs u
            LEFT JOIN Coproprietaires c ON c.CoproprietaireID = u.CoproprietaireID
            ORDER BY u.Identifiant
        """).fetchall()


def lister_journal():
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT j.JournalActionID, u.Identifiant, u.Role,
                   j.Action, j.Details, j.DateHeure
            FROM JournalActions j
            JOIN Utilisateurs u ON u.UtilisateurID = j.UtilisateurID
            ORDER BY j.DateHeure DESC, j.JournalActionID DESC
        """).fetchall()


def lister_paiements_pour_coproprietaire(coproprietaire_id):
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT p.PaiementID, p.Mois, p.DatePaiement, p.MontantDu,
                   p.MontantPaye, p.Statut, p.ModePaiement, p.DateEcheance
            FROM Paiements p
            WHERE p.CoproprietaireID = ?
            ORDER BY p.DatePaiement DESC
        """, (coproprietaire_id,)).fetchall()


def lister_reclamations_pour_coproprietaire(coproprietaire_id):
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT ReclamationID, DateReclamation, Objet, Description, Statut
            FROM Reclamations WHERE CoproprietaireID = ?
            ORDER BY DateReclamation DESC
        """, (coproprietaire_id,)).fetchall()


def lister_rappels_pour_coproprietaire(coproprietaire_id):
    with closing(connexion()) as conn:
        return conn.execute("""
            SELECT RappelID, DateRappel, TypeRappel, Message, StatutEnvoi
            FROM Rappels WHERE CoproprietaireID = ?
            ORDER BY DateRappel DESC
        """, (coproprietaire_id,)).fetchall()
