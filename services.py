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
from datetime import date

import db

DEVISE = "MAD"  # à adapter
TYPE_RAPPEL_RETARD = "Retard de paiement"
STATUT_RAPPEL_EN_ATTENTE = "En attente"
STATUT_RAPPEL_ENVOYE = "Envoye"


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
    return db.lister_paiements()


def enregistrer_paiement(coproprietaire_id, mois, date_paiement, montant_du,
                         montant_paye, mode_paiement, date_echeance):
    """Enregistre un paiement ; le statut est calculé automatiquement (plus de saisie manuelle)."""
    # Statut provisoire : la règle réelle est appliquée juste après, en un seul endroit.
    db.ajouter_paiement(coproprietaire_id, mois, date_paiement, montant_du,
                        montant_paye, "Impaye", mode_paiement, date_echeance)
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
        "total_du": round(total_du, 2),
        "total_paye": round(total_paye, 2),
        "reste_a_payer": round(reste, 2),
        # part du montant dû effectivement couverte
        "taux_recouvrement": round(100 * (total_du - reste) / total_du, 1) if total_du else 0.0,
        "paiements_en_retard": nb_retard,
        "total_depenses": round(depenses, 2),
        "solde": round(total_paye - depenses, 2),  # encaissé - dépensé
        "reclamations_en_attente": dict(par_statut).get("En attente", 0),
        "rappels_en_attente": db.compter_rappels_en_attente(),
        "top_debiteurs": db.top_debiteurs(5),
        "depenses_par_type": db.depenses_par_type(),
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
         _message_retard(prenom, nom, mois, reste, echeance),
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
