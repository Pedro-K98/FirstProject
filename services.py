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
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import closing
import hashlib
import hmac
import os
import secrets
import sqlite3

import config
import db
import migrations

DEVISE = config.DEVISE
TYPE_RAPPEL_RETARD = "Retard de paiement"
STATUT_RAPPEL_EN_ATTENTE = "En attente"
STATUT_RAPPEL_ENVOYE = "Envoye"
_utilisateur_connecte = None
_jeton_session = None


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
    _exiger_admin()
    mettre_a_jour_statuts()
    lignes = db.lister_paiements()
    return [ligne[:4] + tuple(en_montant(v) for v in ligne[4:7]) + ligne[7:]
            for ligne in lignes]


def enregistrer_paiement(coproprietaire_id, mois, date_paiement, montant_du,
                         montant_paye, mode_paiement, date_echeance):
    """Enregistre un paiement ; le statut est calculé automatiquement (plus de saisie manuelle)."""
    acteur = _exiger_admin()
    db.ajouter_paiement(coproprietaire_id, mois, date_paiement,
                        en_centimes(montant_du), en_centimes(montant_paye),
                        "Impaye", mode_paiement, date_echeance)
    mettre_a_jour_statuts()
    _journal(acteur, "ajout_paiement", f"Copropriétaire {coproprietaire_id}, mois {mois}")


# ------------------------------------------------------------------
# TABLEAU DE BORD
# ------------------------------------------------------------------
def tableau_de_bord():
    """Toutes les statistiques du tableau de bord dans un dictionnaire."""
    _exiger_admin()
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
    acteur = _exiger_admin()
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
    if rappels:
        _journal(acteur, "generation_rappels", f"{len(rappels)} rappel(s)")
    return len(rappels)


def marquer_rappel_envoye(rappel_id):
    # Point d'extension : c'est ici que l'on branchera l'envoi réel
    # (e-mail, SMS, WhatsApp, notification push) le moment venu.
    acteur = _exiger_admin()
    db.changer_statut_rappel(rappel_id, STATUT_RAPPEL_ENVOYE)
    _journal(acteur, "modification_rappel", str(rappel_id))


# ------------------------------------------------------------------
# DEPENSES
# ------------------------------------------------------------------
def enregistrer_depense(date_depense, type_depense, montant, description, valide_par):
    acteur = _exiger_admin()
    db.ajouter_depense(date_depense, type_depense, en_centimes(montant),
                       description, valide_par)
    _journal(acteur, "ajout_depense", f"{type_depense}: {description}")


def lister_depenses():
    _exiger_admin()
    return [ligne[:3] + (en_montant(ligne[3]),) + ligne[4:]
            for ligne in db.lister_depenses()]


# ------------------------------------------------------------------
# AUTHENTIFICATION ET DROITS
# ------------------------------------------------------------------
ITERATIONS_PBKDF2 = 200_000


def _verifier_admin(acteur):
    if not acteur or acteur[5] != "Admin" or not acteur[6]:
        raise ErreurMetier("Seul un administrateur actif peut effectuer cette action.")


def _acteur(acteur=None):
    return acteur or _utilisateur_connecte


def _exiger_admin(acteur=None):
    acteur = _acteur(acteur)
    _verifier_admin(acteur)
    return acteur


def _empreinte(mot_de_passe, sel):
    return hashlib.pbkdf2_hmac(
        "sha256", mot_de_passe.encode("utf-8"), sel, ITERATIONS_PBKDF2)


def _valider_identifiants(identifiant, mot_de_passe):
    if not identifiant or len(identifiant.strip()) < 3:
        raise ErreurMetier("L'identifiant doit contenir au moins 3 caractères.")
    if not mot_de_passe or len(mot_de_passe) < 8:
        raise ErreurMetier("Le mot de passe doit contenir au moins 8 caractères.")


def _journal(acteur, action, details):
    acteur = _acteur(acteur)
    if acteur:
        db.journaliser(acteur[0], action, details, datetime.now().isoformat(timespec="seconds"))


def definir_utilisateur_connecte(utilisateur):
    global _utilisateur_connecte
    _utilisateur_connecte = utilisateur


def definir_jeton_session(jeton):
    global _jeton_session
    _jeton_session = jeton


def utilisateur_connecte():
    return _utilisateur_connecte


def _maintenant_utc():
    return datetime.now(timezone.utc)


def _date_session(valeur):
    return valeur.isoformat(timespec="seconds")


def _hash_jeton(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).digest()


def creer_session(utilisateur, duree_minutes=60, appareil="Tkinter"):
    if not utilisateur or not utilisateur[6]:
        raise ErreurMetier("Le compte est inactif ou la session est invalide.")
    if duree_minutes <= 0 or duree_minutes > 24 * 30:
        raise ErreurMetier("La durée de session est invalide.")
    maintenant = _maintenant_utc()
    expiration = maintenant + timedelta(minutes=duree_minutes)
    jeton = secrets.token_urlsafe(32)
    db.creer_session(
        utilisateur[0], _hash_jeton(jeton), _date_session(maintenant),
        _date_session(expiration), appareil)
    return jeton


def _utilisateur_depuis_session(ligne):
    return (ligne[1], ligne[7], ligne[8], ligne[9], ligne[10], ligne[11],
            ligne[12], ligne[13], ligne[14])


def verifier_session(jeton):
    if not jeton or not isinstance(jeton, str):
        return None
    ligne = db.session_par_jeton(_hash_jeton(jeton))
    if not ligne or ligne[4] is not None or not ligne[12]:
        return None
    try:
        expiration = datetime.fromisoformat(ligne[3]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if expiration <= _maintenant_utc():
        return None
    db.actualiser_session(ligne[0], _date_session(_maintenant_utc()))
    return _utilisateur_depuis_session(ligne)


def revoquer_session(jeton):
    ligne = db.session_par_jeton(_hash_jeton(jeton)) if jeton else None
    if ligne:
        db.revoquer_session(ligne[0], _date_session(_maintenant_utc()))


def revoquer_sessions_utilisateur(utilisateur_id, acteur=None):
    acteur = _exiger_admin(acteur)
    if not db.utilisateur_par_id(utilisateur_id):
        raise ErreurMetier("Compte introuvable.")
    db.revoquer_sessions_utilisateur(utilisateur_id, _date_session(_maintenant_utc()))
    _journal(acteur, "revocation_sessions", str(utilisateur_id))


def nettoyer_sessions_expirees():
    return db.supprimer_sessions_expirees(_date_session(_maintenant_utc()))


def lister_coproprietaires():
    _exiger_admin()
    return db.lister_coproprietaires()


def ajouter_coproprietaire(*args):
    acteur = _exiger_admin()
    resultat = db.ajouter_coproprietaire(*args)
    _journal(acteur, "ajout_coproprietaire", str(args[1]))
    return resultat


def supprimer_coproprietaire(coproprietaire_id):
    acteur = _exiger_admin()
    resultat = db.supprimer_coproprietaire(coproprietaire_id)
    _journal(acteur, "suppression_coproprietaire", str(coproprietaire_id))
    return resultat


def modifier_coproprietaire(coproprietaire_id, champ, valeur):
    acteur = _exiger_admin()
    resultat = db.modifier_coproprietaire(coproprietaire_id, champ, valeur)
    _journal(acteur, "modification_coproprietaire", f"{coproprietaire_id}: {champ}")
    return resultat


def supprimer_paiement(paiement_id):
    acteur = _exiger_admin()
    resultat = db.supprimer_paiement(paiement_id)
    _journal(acteur, "suppression_paiement", str(paiement_id))
    return resultat


def supprimer_depense(depense_id):
    acteur = _exiger_admin()
    resultat = db.supprimer_depense(depense_id)
    _journal(acteur, "suppression_depense", str(depense_id))
    return resultat


def lister_reclamations():
    _exiger_admin()
    return db.lister_reclamations()


def lister_rappels():
    _exiger_admin()
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
    if db.compter_administrateurs():
        acteur = _exiger_admin(acteur)
    elif role == "Resident":
        raise ErreurMetier("Un administrateur doit d'abord être créé.")
    sel = os.urandom(16)
    try:
        utilisateur_id = db.creer_utilisateur(
            coproprietaire_id, identifiant, _empreinte(mot_de_passe, sel), sel,
            role, datetime.now().isoformat(timespec="seconds"))
    except sqlite3.IntegrityError as err:
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
    if not acteur or not acteur[6]:
        raise ErreurMetier("Le compte est inactif ou la session est invalide.")
    acteur = _acteur(acteur)
    if acteur is None or acteur[0] != utilisateur_id:
        _verifier_admin(acteur)
    sel = os.urandom(16)
    db.modifier_mot_de_passe(utilisateur_id, _empreinte(nouveau_mot_de_passe, sel), sel)
    _journal(acteur or utilisateur, "changement_mot_de_passe", utilisateur[2])


def desactiver_utilisateur(utilisateur_id, acteur=None):
    acteur = _exiger_admin(acteur)
    if acteur[0] == utilisateur_id:
        raise ErreurMetier("Vous ne pouvez pas désactiver votre propre compte.")
    if not db.utilisateur_par_id(utilisateur_id):
        raise ErreurMetier("Compte introuvable.")
    db.desactiver_utilisateur(utilisateur_id)
    _journal(acteur, "desactivation_compte", str(utilisateur_id))


def activer_utilisateur(utilisateur_id, acteur=None):
    acteur = _exiger_admin(acteur)
    if not db.utilisateur_par_id(utilisateur_id):
        raise ErreurMetier("Compte introuvable.")
    db.activer_utilisateur(utilisateur_id)
    _journal(acteur, "activation_compte", str(utilisateur_id))


def supprimer_utilisateur(utilisateur_id, acteur=None):
    acteur = _exiger_admin(acteur)
    if acteur[0] == utilisateur_id:
        raise ErreurMetier("Vous ne pouvez pas supprimer votre propre compte.")
    if not db.utilisateur_par_id(utilisateur_id):
        raise ErreurMetier("Compte introuvable.")
    db.supprimer_utilisateur(utilisateur_id)
    _journal(acteur, "suppression_compte", str(utilisateur_id))


def lister_utilisateurs():
    _exiger_admin()
    return db.lister_utilisateurs()


def lister_journal():
    _exiger_admin()
    return db.lister_journal()


def reinitialiser_mot_de_passe(utilisateur_id, acteur=None):
    acteur = _exiger_admin(acteur)
    mot_de_passe = os.urandom(9).hex()
    changer_mot_de_passe(utilisateur_id, mot_de_passe, acteur)
    _journal(acteur, "reinitialisation_mot_de_passe", str(utilisateur_id))
    return mot_de_passe


def lister_paiements_pour_utilisateur(utilisateur=None):
    utilisateur = utilisateur or _acteur()
    if not utilisateur or not utilisateur[6]:
        raise ErreurMetier("Le compte est inactif ou la session est invalide.")
    if utilisateur[5] == "Admin":
        return lister_paiements()
    if utilisateur[5] != "Resident" or utilisateur[1] is None:
        raise ErreurMetier("Ce compte ne peut pas consulter ces données.")
    lignes = db.lister_paiements_pour_coproprietaire(utilisateur[1])
    return [ligne[:3] + tuple(en_montant(v) for v in ligne[3:5]) + ligne[5:]
            for ligne in lignes]


def lister_appels_pour_utilisateur(utilisateur=None):
    return lister_paiements_pour_utilisateur(utilisateur)


def lister_reclamations_pour_utilisateur(utilisateur=None):
    utilisateur = utilisateur or _acteur()
    if not utilisateur or not utilisateur[6] or utilisateur[5] != "Resident":
        raise ErreurMetier("Seul un résident actif peut consulter ses réclamations.")
    return db.lister_reclamations_pour_coproprietaire(utilisateur[1])


def lister_rappels_pour_utilisateur(utilisateur=None):
    utilisateur = utilisateur or _acteur()
    if not utilisateur or not utilisateur[6] or utilisateur[5] != "Resident":
        raise ErreurMetier("Seul un résident actif peut consulter ses rappels.")
    return db.lister_rappels_pour_coproprietaire(utilisateur[1])


def tableau_resident(utilisateur=None):
    utilisateur = utilisateur or _acteur()
    if not utilisateur or not utilisateur[6] or utilisateur[5] != "Resident":
        raise ErreurMetier("Accès résident refusé.")
    return {
        "paiements": lister_paiements_pour_utilisateur(utilisateur),
        "reclamations": lister_reclamations_pour_utilisateur(utilisateur),
        "rappels": lister_rappels_pour_utilisateur(utilisateur),
    }


def initialiser_base():
    db.initialiser_base()
    with closing(db.connexion()) as conn:
        migrations.appliquer(conn, db.DB_NAME)


def compter_administrateurs():
    return db.compter_administrateurs()
