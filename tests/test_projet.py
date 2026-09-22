import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import services


class TestComptesUtilisateurs(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = Path(self.dossier.name) / "test.db"
        self.sauvegardes = Path(self.dossier.name) / "sauvegardes"
        self.patches = [
            patch.object(db, "DB_NAME", str(self.chemin)),
            patch("config.CHEMIN_BASE", self.chemin),
            patch("config.DOSSIER_SAUVEGARDES", self.sauvegardes),
        ]
        for correctif in self.patches:
            correctif.start()
        services.initialiser_base()
        db.ajouter_coproprietaire(
            "Coproprietaire", "Test", "Resident", "", "", "A1", "", "2026-01-01", 1)
        self.coproprietaire_id = db.lister_coproprietaires()[0][0]
        services.definir_utilisateur_connecte(None)

    def tearDown(self):
        for correctif in reversed(self.patches):
            correctif.stop()
        self.dossier.cleanup()

    def test_creation_et_connexion_correcte(self):
        admin = services.creer_utilisateur("admin", "motdepasse-solide", "Admin")
        resident = services.creer_utilisateur(
            "resident1", "motdepasse-solide", "Resident", self.coproprietaire_id, admin)
        self.assertEqual(resident[5], "Resident")
        utilisateur = services.verifier_identifiants("resident1", "motdepasse-solide")
        self.assertIsNotNone(utilisateur)
        self.assertEqual(utilisateur[2], "resident1")

    def test_mot_de_passe_incorrect(self):
        services.creer_utilisateur("admin", "motdepasse-solide", "Admin")
        self.assertIsNone(services.verifier_identifiants("admin", "mauvais-pass"))

    def test_compte_desactive_refuse(self):
        admin = services.creer_utilisateur("admin", "motdepasse-solide", "Admin")
        resident = services.creer_utilisateur(
            "resident1", "motdepasse-solide", "Resident", self.coproprietaire_id, admin)
        services.desactiver_utilisateur(resident[0], admin)
        self.assertIsNone(services.verifier_identifiants("resident1", "motdepasse-solide"))

    def test_mot_de_passe_jamais_stocke_en_clair(self):
        mot_de_passe = "motdepasse-solide"
        services.creer_utilisateur("admin", mot_de_passe, "Admin")
        connexion = sqlite3.connect(self.chemin)
        try:
            hash_stocke, sel = connexion.execute(
                "SELECT MotDePasseHache, Sel FROM Utilisateurs WHERE Identifiant = 'admin'"
            ).fetchone()
        finally:
            connexion.close()
        self.assertNotEqual(hash_stocke, mot_de_passe.encode("utf-8"))
        self.assertNotEqual(hash_stocke, mot_de_passe)
        self.assertGreater(len(hash_stocke), 0)
        self.assertGreater(len(sel), 0)

    def test_validation_mot_de_passe_court(self):
        with self.assertRaises(services.ErreurMetier):
            services.creer_utilisateur("admin", "court", "Admin")


if __name__ == "__main__":
    unittest.main()
