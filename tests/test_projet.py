import sqlite3
import tempfile
import unittest
import hashlib
from datetime import datetime, timedelta, timezone
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

    def test_reclamation_peut_changer_de_statut(self):
        reclamation_id = db.ajouter_reclamation(
            self.coproprietaire_id, "2026-01-15", "Plomberie", "Fuite", "En attente")
        self.assertIsNotNone(reclamation_id)
        services.changer_statut_reclamation(reclamation_id, "En cours")
        services.changer_statut_reclamation(reclamation_id, "Résolue")
        reclamation = db.lister_reclamations()[0]
        self.assertEqual(reclamation[5], "Résolue")

    def test_escalade_des_rappels_generes(self):
        services.definir_utilisateur_connecte(self.admin)
        db.ajouter_paiement(self.coproprietaire_id, "2026-01", "2026-01-10",
                            10000, 0, "Impaye", "Virement", "2026-01-31")
        services.generer_rappels("2026-02-05")
        self.assertEqual(len(db.lister_rappels()), 1)
        services.escalader_rappels("2026-02-20")
        rappels = db.lister_rappels()
        self.assertEqual(len(rappels), 2)
        self.assertEqual(rappels[0][3], "Retard de paiement")
        self.assertTrue(any("relance" in rappel[4].lower() for rappel in rappels))

    @patch("smtplib.SMTP")
    def test_envoi_email_rappel(self, smtp_mock):
        services.definir_utilisateur_connecte(self.admin)
        db.ajouter_paiement(self.coproprietaire_id, "2026-01", "2026-01-10",
                            10000, 0, "Impaye", "Virement", "2026-01-31")
        services.generer_rappels("2026-02-05")
        rappel = db.lister_rappels()[0]
        avec_email = services.envoyer_rappel_par_email(rappel[0], "test@example.com")
        self.assertTrue(avec_email)
        smtp_mock.return_value.sendmail.assert_called_once()

    def test_action_journalisee(self):
        services.definir_utilisateur_connecte(self.admin)
        services.ajouter_coproprietaire(
            "Locataire", "Journal", "Test", "", "", "C1", "", "2026-01-01", 1)
        self.assertTrue(db.lister_journal())

    def test_validation_mot_de_passe_court(self):
        with self.assertRaises(services.ErreurMetier):
            services.creer_utilisateur("admin", "court", "Admin")

    def test_session_valide_et_jeton_non_stocke(self):
        jeton = services.creer_session(self.admin, appareil="test")
        self.assertIsNotNone(services.verifier_session(jeton))
        connexion = sqlite3.connect(self.chemin)
        try:
            stocke = connexion.execute("SELECT JetonHash FROM Sessions").fetchone()[0]
        finally:
            connexion.close()
        self.assertNotEqual(stocke, jeton.encode("utf-8"))

    def test_session_revoquee_et_jeton_falsifie(self):
        jeton = services.creer_session(self.admin)
        self.assertIsNone(services.verifier_session(jeton + "x"))
        services.revoquer_session(jeton)
        self.assertIsNone(services.verifier_session(jeton))

    def test_session_expiree_refusee(self):
        jeton = services.creer_session(self.admin)
        expiration = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        connexion = sqlite3.connect(self.chemin)
        try:
            connexion.execute(
                "UPDATE Sessions SET DateExpiration = ?", (expiration,))
            connexion.commit()
        finally:
            connexion.close()
        self.assertIsNone(services.verifier_session(jeton))


if __name__ == "__main__":
    unittest.main()
