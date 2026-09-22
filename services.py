"""
services.py — Règles métier du Syndic.

Architecture en 3 couches :
    db.py        -> accès aux données (SQL uniquement)
    services.py  -> règles métier : statuts, tableau de bord, rappels   (ce fichier)
    ui.py        -> affichage (Tkinter aujourd'hui, mobile / web demain)

Ce fichier n'importe ni Tkinter ni rien de graphique : une API ou une application
mobile pourra l'utiliser telle quelle. Toutes les fonctions renvoient des types
simples (int, float, str, list, dict), faciles à convertir en JSON.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import closing
import hashlib
import hmac
import os

import config
import db
import migrations

DEVISE = config.DEVISE
TYPE_RAPPEL_RETARD = "Retard de paiement"
STATUT_RAPPEL_EN_ATTENTE = "En attente"
STATUT_RAPPEL_ENVOYE = "Envoye"
_utilisateur_connecte = None


class ErreurMetier(ValueError):
    """Erreur de validation ou de droit lisible par l'interface."""


def en_centimes(valeur):
    try:
        montant = Decimal(str(valeur).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise ErreurMetier("Le montant doit être un nombre.") from None
    if not montant.is_finite() or montant < 0:
        raise ErreurMetier("Le montant doit être positif.")
    return int((montant * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def en_montant(centimes):
    return float(Decimal(int(centimes)) / Decimal(100))


def aujourdhui():
    return date.today().isoformat()


# ------------------------------------------------------------------
# PAIEMENTS
# ------------------------------------------------------------------
def mettre_a_jour_statuts(jour=None):
    """Recalcule le statut de tous les paiements (Paye / En retard / Impaye).
    À appeler avant tout affichage ou calcul qui dépend de la date du jour."""
    db.recalculer_statuts_paiements(jour or aujourdhui())


def lister_paiements():
    """Liste des paiements avec des statuts à jour (un retard peut apparaître avec le temps)."""
    mettre_a_jour_statuts()
    lignes = db.lister_paiements()
    return [ligne[:4] + tuple(en_montant(v) for v in ligne[4:7]) + ligne[7:]
            for ligne in lignes]


def enregistrer_paiement(coproprietaire_id, mois, date_paiement, montant_du,
                         montant_paye, mode_paiement, date_echeance):
    """Enregistre un paiement ; le statut est calculé automatiquement (plus de saisie manuelle)."""
    db.ajouter_paiement(coproprietaire_id, mois, date_paiement,
                        en_centimes(montant_du), en_centimes(montant_paye),
                        "Impaye", mode_paiement, date_echeance)
    mettre_a_jour_statuts()


# ------------------------------------------------------------------
# TABLEAU DE BORD
# ------------------------------------------------------------------
def tableau_de_bord():
    """Toutes les statistiques du tableau de bord dans un dictionnaire."""
    mettre_a_jour_statuts()

    total_du, total_paye, reste, nb_retard = db.totaux_paiements()
    depenses = db.total_depenses()
    actifs, total_copro = db.compter_coproprietaires()
    par_statut = db.reclamations_par_statut()

    return {
        "coproprietaires_actifs": actifs,
        "coproprietaires_total": total_copro,
        "total_du": en_montant(total_du),
        "total_paye": en_montant(total_paye),
        "reste_a_payer": en_montant(reste),
        # part du montant dû effectivement couverte
        "taux_recouvrement": round(100 * (total_du - reste) / total_du, 1) if total_du else 0.0,
        "paiements_en_retard": nb_retard,
        "total_depenses": en_montant(depenses),
        "solde": en_montant(total_paye - depenses),
        "reclamations_en_attente": dict(par_statut).get("En attente", 0),
        "rappels_en_attente": db.compter_rappels_en_attente(),
        "top_debiteurs": [ligne[:3] + (en_montant(ligne[3]),)
                  for ligne in db.top_debiteurs(5)],
        "depenses_par_type": [(type_, en_montant(total))
                       for type_, total in db.depenses_par_type()],
        "reclamations_par_statut": par_statut,
    }


# ------------------------------------------------------------------
# RAPPELS
# ------------------------------------------------------------------
def _message_retard(prenom, nom, mois, reste, echeance):
    return (f"Bonjour {prenom} {nom}".strip() + ", "
            f"votre cotisation de {mois} (reste à payer : {reste:.2f} {DEVISE}) "
            f"était due le {echeance}. Merci de régulariser votre situation.")


def generer_rappels(jour=None):
    """Crée un rappel pour chaque paiement en retard qui n'en a pas encore.
    Peut être relancée sans risque : aucun doublon. Renvoie le nombre de rappels créés."""
    jour = jour or aujourdhui()
    mettre_a_jour_statuts(jour)

    rappels = [
        (cid, jour, TYPE_RAPPEL_RETARD,
         _message_retard(prenom, nom, mois, en_montant(reste), echeance),
         STATUT_RAPPEL_EN_ATTENTE, paiement_id)
        for paiement_id, cid, nom, prenom, mois, reste, echeance
        in db.paiements_en_retard_sans_rappel()
    ]
    db.ajouter_rappels_en_masse(rappels)
    return len(rappels)


def marquer_rappel_envoye(rappel_id):
    # Point d'extension : c'est ici que l'on branchera l'envoi réel
    # (e-mail, SMS, WhatsApp, notification push) le moment venu.
    db.changer_statut_rappel(rappel_id, STATUT_RAPPEL_ENVOYE)


# ------------------------------------------------------------------
# DEPENSES
# ------------------------------------------------------------------
def enregistrer_depense(date_depense, type_depense, montant, description, valide_par):
    db.ajouter_depense(date_depense, type_depense, en_centimes(montant),
                       description, valide_par)


def lister_depenses():
    return [ligne[:3] + (en_montant(ligne[3]),) + ligne[4:]
            for ligne in db.lister_depenses()]


# ------------------------------------------------------------------
# AUTHENTIFICATION ET DROITS
# ------------------------------------------------------------------
ITERATIONS_PBKDF2 = 310_000


def _verifier_admin(acteur):
    if not acteur or acteur[5] != "Admin" or not acteur[6]:
        raise ErreurMetier("Seul un administrateur actif peut effectuer cette action.")


def _empreinte(mot_de_passe, sel):
    return hashlib.pbkdf2_hmac(
        "sha256", mot_de_passe.encode("utf-8"), sel, ITERATIONS_PBKDF2)


def _valider_identifiants(identifiant, mot_de_passe):
    if not identifiant or len(identifiant.strip()) < 3:
        raise ErreurMetier("L'identifiant doit contenir au moins 3 caractères.")
    if not mot_de_passe or len(mot_de_passe) < 8:
        raise ErreurMetier("Le mot de passe doit contenir au moins 8 caractères.")


def _journal(acteur, action, details):
    acteur = acteur or _utilisateur_connecte
    if acteur:
        db.journaliser(acteur[0], action, details, datetime.now().isoformat(timespec="seconds"))


def definir_utilisateur_connecte(utilisateur):
    global _utilisateur_connecte
    _utilisateur_connecte = utilisateur


def utilisateur_connecte():
    return _utilisateur_connecte


def lister_coproprietaires():
    return db.lister_coproprietaires()


def ajouter_coproprietaire(*args):
    resultat = db.ajouter_coproprietaire(*args)
    _journal(None, "ajout_coproprietaire", str(args[1]))
    return resultat


def supprimer_coproprietaire(coproprietaire_id):
    resultat = db.supprimer_coproprietaire(coproprietaire_id)
    _journal(None, "suppression_coproprietaire", str(coproprietaire_id))
    return resultat


def modifier_coproprietaire(coproprietaire_id, champ, valeur):
    resultat = db.modifier_coproprietaire(coproprietaire_id, champ, valeur)
    _journal(None, "modification_coproprietaire", f"{coproprietaire_id}: {champ}")
    return resultat


def supprimer_paiement(paiement_id):
    resultat = db.supprimer_paiement(paiement_id)
    _journal(None, "suppression_paiement", str(paiement_id))
    return resultat


def supprimer_depense(depense_id):
    resultat = db.supprimer_depense(depense_id)
    _journal(None, "suppression_depense", str(depense_id))
    return resultat


def lister_reclamations():
    return db.lister_reclamations()


def lister_rappels():
    return db.lister_rappels()


def creer_utilisateur(identifiant, mot_de_passe, role="Resident",
                      coproprietaire_id=None, acteur=None):
    """Crée un compte sans jamais persister le mot de passe en clair."""
    identifiant = identifiant.strip()
    _valider_identifiants(identifiant, mot_de_passe)
    if role not in ("Admin", "Resident"):
        raise ErreurMetier("Le rôle choisi est invalide.")
    if role == "Resident" and coproprietaire_id is None:
        raise ErreurMetier("Un compte résident doit être lié à un copropriétaire.")
    if role == "Admin" and db.compter_administrateurs() and acteur is not None:
        _verifier_admin(acteur)
    if role == "Resident" and acteur is not None:
        _verifier_admin(acteur)
    sel = os.urandom(16)
    try:
        utilisateur_id = db.creer_utilisateur(
            coproprietaire_id, identifiant, _empreinte(mot_de_passe, sel), sel,
            role, datetime.now().isoformat(timespec="seconds"))
    except db.sqlite3.IntegrityError as err:
        if "Identifiant" in str(err) or "UNIQUE" in str(err):
            raise ErreurMetier("Cet identifiant est déjà utilisé.") from None
        raise
    _journal(acteur, "creation_compte", f"Compte {identifiant} ({role}) créé")
    return db.utilisateur_par_id(utilisateur_id)


def verifier_identifiants(identifiant, mot_de_passe):
    utilisateur = db.utilisateur_par_identifiant(identifiant.strip())
    if not utilisateur or not utilisateur[6]:
        return None
    empreinte = _empreinte(mot_de_passe, utilisateur[4])
    return utilisateur if hmac.compare_digest(empreinte, utilisateur[3]) else None


def changer_mot_de_passe(utilisateur_id, nouveau_mot_de_passe, acteur=None):
    _valider_identifiants("compte", nouveau_mot_de_passe)
    utilisateur = db.utilisateur_par_id(utilisateur_id)
    if not utilisateur:
        raise ErreurMetier("Compte introuvable.")
    if acteur is not None and acteur[0] != utilisateur_id:
        _verifier_admin(acteur)
    sel = os.urandom(16)
    db.modifier_mot_de_passe(utilisateur_id, _empreinte(nouveau_mot_de_passe, sel), sel)
    _journal(acteur or utilisateur, "changement_mot_de_passe", utilisateur[2])


def desactiver_utilisateur(utilisateur_id, acteur=None):
    _verifier_admin(acteur)
    if acteur[0] == utilisateur_id:
        raise ErreurMetier("Vous ne pouvez pas désactiver votre propre compte.")
    if not db.utilisateur_par_id(utilisateur_id):
        raise ErreurMetier("Compte introuvable.")
    db.desactiver_utilisateur(utilisateur_id)
    _journal(acteur, "desactivation_compte", str(utilisateur_id))


def initialiser_base():
    db.initialiser_base()
    with closing(db.connexion()) as conn:
        migrations.appliquer(conn, db.DB_NAME)


def compter_administrateurs():
    return db.compter_administrateurs()
