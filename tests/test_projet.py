import sqlite3
import tempfile
import unittest
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import db
import services
import sauvegarde


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

    def test_historique_reclamation_est_enregistre(self):
        reclamation_id = db.ajouter_reclamation(
            self.coproprietaire_id, "2026-01-15", "Plomberie", "Fuite", "En attente")
        services.definir_utilisateur_connecte(self.admin)
        services.changer_statut_reclamation(reclamation_id, "En cours")
        historique = db.lister_historique_statuts("Reclamation", reclamation_id)
        self.assertEqual(len(historique), 1)
        self.assertEqual(historique[0][3:5], ("En attente", "En cours"))

    def test_migrations_appliquees(self):
        connexion = sqlite3.connect(self.chemin)
        try:
            version = connexion.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                ligne[0] for ligne in connexion.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            connexion.close()
        self.assertEqual(version, 13)
        self.assertTrue({"Utilisateurs", "JournalActions", "Sessions", "HistoriqueStatuts"} <= tables)

    def test_tracabilite_financiere_et_index(self):
        services.definir_utilisateur_connecte(self.admin)
        services.enregistrer_paiement(
            self.coproprietaire_id, "2026-04", "2026-04-10", 100, 50,
            "Virement", "2026-04-30", self.admin)
        services.enregistrer_depense(
            "2026-04-11", "Entretien", 25, "Nettoyage", "Syndic", self.admin)
        connexion = sqlite3.connect(self.chemin)
        try:
            paiement_user = connexion.execute(
                "SELECT UtilisateurID FROM Paiements").fetchone()[0]
            depense_user = connexion.execute(
                "SELECT UtilisateurID FROM Depenses").fetchone()[0]
            index = {
                ligne[1] for ligne in connexion.execute(
                    "SELECT name, tbl_name FROM sqlite_master "
                    "WHERE type = 'index' AND sql IS NOT NULL")
            }
        finally:
            connexion.close()
        self.assertEqual(paiement_user, self.admin[0])
        self.assertEqual(depense_user, self.admin[0])
        self.assertTrue({"Paiements", "Reclamations"} <= index)

    def test_priorite_reclamation_validee(self):
        services.definir_utilisateur_connecte(self.admin)
        reclamation_id = services.ajouter_reclamation(
            self.coproprietaire_id, "2026-02-01", "Urgence", "Ascenseur en panne",
            "En attente", "Urgente")
        ligne = db.lister_reclamations()[0]
        self.assertEqual(ligne[0], reclamation_id)
        self.assertEqual(ligne[6], "Urgente")
        with self.assertRaises(services.ErreurMetier):
            services.ajouter_reclamation(
                self.coproprietaire_id, "2026-02-01", "Test", "Test",
                "En attente", "Critique")

    def test_statuts_paiements_automatiques(self):
        db.ajouter_paiement(self.coproprietaire_id, "2026-01", "2026-01-10",
                            10000, 10000, "Paye", "Virement", "2026-01-31")
        db.ajouter_paiement(self.coproprietaire_id, "2026-02", "2026-02-10",
                            10000, 0, "Impaye", "Virement", "2026-02-01")
        db.ajouter_paiement(self.coproprietaire_id, "2026-03", "2026-03-10",
                            10000, 0, "Impaye", "Virement", "2026-12-31")
        db.recalculer_statuts_paiements("2026-03-01")
        statuts = [ligne[7] for ligne in db.lister_paiements()]
        self.assertEqual(statuts, ["Impaye", "En retard", "Paye"])

    def test_sauvegarde_forcee_cree_un_fichier(self):
        destination = sauvegarde.sauvegarder(force=True)
        self.assertIsNotNone(destination)
        self.assertTrue(destination.exists())
        self.assertGreater(destination.stat().st_size, 0)

    def test_restauration_cree_une_securite(self):
        destination = sauvegarde.sauvegarder(force=True)
        db.ajouter_coproprietaire(
            "Locataire", "Temporaire", "Test", "", "", "Z9", "", "2026-01-01", 1)
        services.definir_utilisateur_connecte(self.admin)
        securite = services.restaurer_sauvegarde(destination.name)
        noms = [ligne[2] for ligne in db.lister_coproprietaires()]
        self.assertNotIn("Temporaire", noms)
        self.assertTrue((self.sauvegardes / securite).exists())

    def test_restauration_refuse_resident(self):
        destination = sauvegarde.sauvegarder(force=True)
        resident = services.creer_utilisateur(
            "resident2", "motdepasse-solide", "Resident", self.coproprietaire_id, self.admin)
        services.definir_utilisateur_connecte(resident)
        with self.assertRaises(services.ErreurMetier):
            services.restaurer_sauvegarde(destination.name)

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

    def test_rappel_manuel_enregistre(self):
        services.definir_utilisateur_connecte(self.admin)
        services.enregistrer_rappel(
            self.coproprietaire_id, "2026-02-10", "Information",
            "Réunion de copropriété le 15 février.", "En attente")
        rappels = db.lister_rappels()
        self.assertEqual(len(rappels), 1)
        self.assertEqual(rappels[0][3], "Information")
        self.assertEqual(rappels[0][5], "En attente")

    @patch("smtplib.SMTP")
    def test_envoi_email_rappel(self, smtp_mock):
        services.definir_utilisateur_connecte(self.admin)
        db.ajouter_paiement(self.coproprietaire_id, "2026-01", "2026-01-10",
                            10000, 0, "Impaye", "Virement", "2026-01-31")
        services.generer_rappels("2026-02-05")
        rappel = db.lister_rappels()[0]
        with patch("config.ENVOI_EMAIL_REEL", True):
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
