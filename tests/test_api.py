import importlib
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import anyio
import httpx

import db
import services


class TestApiResident:
    def setup_method(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = Path(self.dossier.name) / "api.db"
        self.sauvegardes = Path(self.dossier.name) / "sauvegardes"
        self.patches = [
            patch.object(db, "DB_NAME", str(self.chemin)),
            patch("config.CHEMIN_BASE", self.chemin),
            patch("config.DOSSIER_SAUVEGARDES", self.sauvegardes),
        ]
        for correctif in self.patches:
            correctif.start()
        services.initialiser_base()
        self.coproprietaire_a = db.ajouter_coproprietaire(
            "Coproprietaire", "Alpha", "Resident", "", "", "A1", "", "2026-01-01", 1)
        self.coproprietaire_b = db.ajouter_coproprietaire(
            "Coproprietaire", "Beta", "Resident", "", "", "B1", "", "2026-01-01", 1)
        ids = [ligne[0] for ligne in db.lister_coproprietaires()]
        self.coproprietaire_a, self.coproprietaire_b = ids[0], ids[1]
        admin = services.verifier_identifiants("admin", "admin")
        self.resident_a = services.creer_utilisateur(
            "resident_a", "motdepasse-a", "Resident", self.coproprietaire_a, admin)
        self.resident_b = services.creer_utilisateur(
            "resident_b", "motdepasse-b", "Resident", self.coproprietaire_b, admin)
        services.definir_utilisateur_connecte(admin)
        db.ajouter_paiement(self.coproprietaire_a, "2026-01", "2026-01-10",
                            10000, 2500, "Impaye", "Virement", "2026-01-31")
        db.ajouter_reclamation(self.coproprietaire_b, "2026-01-10", "Privée", "B", "En attente")
        import api.app as module
        self.module = importlib.reload(module)

    def teardown_method(self):
        for correctif in reversed(self.patches):
            correctif.stop()
        self.dossier.cleanup()

    def _request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return anyio.run(send)

    def _get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def _post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def _token(self, identifiant="resident_a", mot_de_passe="motdepasse-a"):
        response = self._post("/auth/login", json={
            "identifiant": identifiant, "mot_de_passe": mot_de_passe,
        })
        assert response.status_code == 200
        return response.json()["access_token"]

    def test_login_me_et_cors(self):
        response = self._post(
            "/auth/login",
            json={"identifiant": "resident_a", "mot_de_passe": "motdepasse-a"},
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        token = response.json()["access_token"]
        me = self._get("/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["lots"] == [{"appartement": "A1"}]

    def test_endpoints_resident_et_isolation(self):
        token_a = self._token()
        headers_a = {"Authorization": f"Bearer {token_a}"}
        db.ajouter_reclamation(self.coproprietaire_a, "2026-02-01", "A", "Texte", "En attente", "Haute")
        db.ajouter_rappel(self.coproprietaire_a, "2026-02-02", "Information", "Message", "En attente")
        for chemin in ("/appels-de-fonds", "/paiements", "/reclamations", "/rappels"):
            response = self._get(chemin, headers=headers_a)
            assert response.status_code == 200
            assert all("Privée" not in str(element) for element in response.json())
        created = self._post(
            "/reclamations", json={"objet": "A", "description": "Demande", "priorite": "Urgente"},
            headers=headers_a,
        )
        assert created.status_code == 201

    def test_auth_obligatoire_sur_toutes_les_routes_protegees(self):
        for chemin in ("/me", "/appels-de-fonds", "/paiements", "/reclamations", "/rappels"):
            assert self._get(chemin).status_code == 401
        assert self._post("/reclamations", json={"objet": "A", "description": "B"}).status_code == 401

    def test_mauvais_mot_de_passe_bloque_apres_trois_echecs(self):
        for _ in range(3):
            assert self._post("/auth/login", json={
                "identifiant": "resident_a", "mot_de_passe": "mauvais",
            }).status_code == 401
        assert self._post("/auth/login", json={
            "identifiant": "resident_a", "mot_de_passe": "motdepasse-a",
        }).status_code == 401

    def test_prix_et_reclamations_en_centimes(self):
        token = self._token()
        response = self._get("/paiements", headers={"Authorization": f"Bearer {token}"})
        assert response.json()[0]["montant_du_centimes"] == 10000
        assert response.json()[0]["impaye_centimes"] == 7500
