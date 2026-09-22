import sqlite3
import tempfile
import unittest
import hashlib
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
        db.ajouter_coproprietaire(
            "Coproprietaire", "Autre", "Resident", "", "", "B1", "", "2026-01-01", 1)
        self.autre_coproprietaire_id = db.lister_coproprietaires()[0][0]
        self.admin = services.verifier_identifiants("admin", "admin")
        services.definir_utilisateur_connecte(None)

    def tearDown(self):
        for correctif in reversed(self.patches):
            correctif.stop()
        self.dossier.cleanup()

    def test_creation_et_connexion_correcte(self):
        resident = services.creer_utilisateur(
            "resident1", "motdepasse-solide", "Resident", self.coproprietaire_id, self.admin)
        self.assertEqual(resident[5], "Resident")
        utilisateur = services.verifier_identifiants("resident1", "motdepasse-solide")
        self.assertIsNotNone(utilisateur)
        self.assertEqual(utilisateur[2], "resident1")

    def test_mot_de_passe_incorrect(self):
        self.assertIsNone(services.verifier_identifiants("admin", "mauvais-pass"))

    def test_compte_desactive_refuse(self):
        resident = services.creer_utilisateur(
            "resident1", "motdepasse-solide", "Resident", self.coproprietaire_id, self.admin)
        services.desactiver_utilisateur(resident[0], self.admin)
        self.assertIsNone(services.verifier_identifiants("resident1", "motdepasse-solide"))
        services.activer_utilisateur(resident[0], self.admin)
        self.assertIsNotNone(services.verifier_identifiants("resident1", "motdepasse-solide"))

    def test_mot_de_passe_jamais_stocke_en_clair(self):
        mot_de_passe = "motdepasse-solide"
        services.changer_mot_de_passe(self.admin[0], mot_de_passe, self.admin)
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

    def test_admin_initial_et_changement_obligatoire(self):
        admin = services.verifier_identifiants("admin", "admin")
        self.assertIsNotNone(admin)
        self.assertEqual(admin[8], 1)
        nouveau = "admin-nouveau-mot"
        services.changer_mot_de_passe(admin[0], nouveau, admin)
        admin = services.verifier_identifiants("admin", nouveau)
        self.assertEqual(admin[8], 0)

    def test_sel_et_hash_pbkdf2_200000(self):
        admin = services.verifier_identifiants("admin", "admin")
        hash_stocke, sel = admin[3], admin[4]
        attendu = hashlib.pbkdf2_hmac("sha256", b"admin", sel, 200_000)
        self.assertEqual(hash_stocke, attendu)
        self.assertNotEqual(hash_stocke, b"admin")

    def test_permissions_resident_filtrees_par_coproprietaire(self):
        resident = services.creer_utilisateur(
            "resident1", "motdepasse-solide", "Resident", self.coproprietaire_id, self.admin)
        db.ajouter_paiement(self.coproprietaire_id, "2026-01", "2026-01-10",
                            10000, 5000, "Impaye", "Virement", "2026-01-31")
        db.ajouter_paiement(self.autre_coproprietaire_id, "2026-01", "2026-01-10",
                            20000, 0, "Impaye", "Virement", "2026-01-31")
        db.ajouter_reclamation(self.coproprietaire_id, "2026-01-15", "Plomberie", "Fuite", "En attente")
        db.ajouter_reclamation(self.autre_coproprietaire_id, "2026-01-15", "Bruit", "Nuisance", "En attente")
        db.ajouter_rappel(self.coproprietaire_id, "2026-01-20", "Information", "Message 1", "En attente")
        db.ajouter_rappel(self.autre_coproprietaire_id, "2026-01-20", "Information", "Message 2", "En attente")
        self.assertEqual(len(services.lister_paiements_pour_utilisateur(resident)), 1)
        self.assertEqual(len(services.lister_reclamations_pour_utilisateur(resident)), 1)
        self.assertEqual(len(services.lister_rappels_pour_utilisateur(resident)), 1)
        imposteur = resident[:1] + (self.autre_coproprietaire_id,) + resident[2:]
        self.assertEqual(len(services.lister_paiements_pour_utilisateur(imposteur)), 1)
        self.assertEqual(len(services.lister_reclamations_pour_utilisateur(imposteur)), 1)
        self.assertEqual(len(services.lister_rappels_pour_utilisateur(imposteur)), 1)

    def test_action_journalisee(self):
        services.definir_utilisateur_connecte(self.admin)
        services.ajouter_coproprietaire(
            "Locataire", "Journal", "Test", "", "", "C1", "", "2026-01-01", 1)
        self.assertTrue(db.lister_journal())

    def test_validation_mot_de_passe_court(self):
        with self.assertRaises(services.ErreurMetier):
            services.creer_utilisateur("admin", "court", "Admin")


if __name__ == "__main__":
    unittest.main()
