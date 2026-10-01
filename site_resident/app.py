import os
import secrets

from flask import Flask, flash, redirect, render_template, request, session, url_for

import db
import services

services.initialiser_base()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)
if not os.environ.get("FLASK_SECRET_KEY"):
    print(
        "ATTENTION : FLASK_SECRET_KEY n'est pas défini. "
        "Les sessions Flask seront invalidées à chaque redémarrage. "
        "Fixez cette variable avant la mise en ligne réelle."
    )


# TODO: ajouter une protection CSRF avant toute mise en ligne publique.


def _utilisateur_connecte():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    try:
        utilisateur = services.Session.depuis_utilisateur_id(user_id)
    except services.ErreurMetier:
        session.clear()
        return None
    if utilisateur.role == "Admin":
        return utilisateur
    if not utilisateur.actif:
        session.clear()
        return None
    return utilisateur


def _rediriger_si_non_autorise():
    utilisateur = _utilisateur_connecte()
    if utilisateur is None:
        return None
    if utilisateur.role == "Admin":
        session.clear()
        flash("Ce site est réservé aux résidents, utilisez l'application de bureau.", "error")
        return None
    return utilisateur


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        identifiant = (request.form.get("identifiant") or "").strip()
        mot_de_passe = request.form.get("mot_de_passe") or ""
        utilisateur = services.verifier_identifiants(identifiant, mot_de_passe)
        if utilisateur is None:
            flash("Identifiant ou mot de passe incorrect.", "error")
            return render_template("connexion.html")
        if utilisateur[5] == "Admin":
            flash("Ce site est réservé aux résidents, utilisez l'application de bureau.", "error")
            return render_template("connexion.html")
        session["user_id"] = utilisateur[0]
        return redirect(url_for("dashboard"))
    if "user_id" in session:
        utilisateur = _utilisateur_connecte()
        if utilisateur and utilisateur.role != "Admin":
            return redirect(url_for("dashboard"))
    return render_template("connexion.html")


@app.route("/")
def dashboard():
    utilisateur = _rediriger_si_non_autorise()
    if utilisateur is None:
        flash("Veuillez vous connecter pour accéder à votre espace résident.", "error")
        return redirect(url_for("connexion"))
    tableau = services.mon_tableau_de_bord(utilisateur)
    return render_template("dashboard.html", utilisateur=utilisateur, tableau=tableau)


@app.route("/appels")
def appels():
    utilisateur = _rediriger_si_non_autorise()
    if utilisateur is None:
        flash("Veuillez vous connecter pour accéder à votre espace résident.", "error")
        return redirect(url_for("connexion"))
    appels_liste = services.mes_appels(utilisateur)
    return render_template("appels.html", utilisateur=utilisateur, appels=appels_liste)


@app.route("/reclamations", methods=["GET", "POST"])
def reclamations():
    utilisateur = _rediriger_si_non_autorise()
    if utilisateur is None:
        flash("Veuillez vous connecter pour accéder à votre espace résident.", "error")
        return redirect(url_for("connexion"))
    if request.method == "POST":
        objet = request.form.get("objet", "")
        description = request.form.get("description", "")
        priorite = request.form.get("priorite", "Normale")
        try:
            services.deposer_reclamation(utilisateur, objet, description, priorite)
            flash("Votre réclamation a bien été enregistrée.", "success")
        except services.ErreurMetier as exc:
            flash(str(exc), "error")
        return redirect(url_for("reclamations"))
    reclamations_liste = services.mes_reclamations(utilisateur)
    return render_template("reclamations.html", utilisateur=utilisateur, reclamations=reclamations_liste)


@app.route("/rappels")
def rappels():
    utilisateur = _rediriger_si_non_autorise()
    if utilisateur is None:
        flash("Veuillez vous connecter pour accéder à votre espace résident.", "error")
        return redirect(url_for("connexion"))
    rappels_liste = services.mes_rappels(utilisateur)
    return render_template("rappels.html", utilisateur=utilisateur, rappels=rappels_liste)


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    flash("Vous êtes déconnecté.", "success")
    return redirect(url_for("connexion"))


@app.route("/mot-de-passe", methods=["GET", "POST"])
def mot_de_passe():
    utilisateur = _rediriger_si_non_autorise()
    if utilisateur is None:
        flash("Veuillez vous connecter pour accéder à votre espace résident.", "error")
        return redirect(url_for("connexion"))
    if request.method == "POST":
        ancien = request.form.get("ancien_mot_de_passe") or ""
        nouveau = request.form.get("nouveau_mot_de_passe") or ""
        confirmation = request.form.get("confirmation") or ""
        try:
            if not ancien or not nouveau or not confirmation:
                raise services.ErreurMetier("Tous les champs sont obligatoires.")
            if nouveau != confirmation:
                raise services.ErreurMetier("La confirmation ne correspond pas au nouveau mot de passe.")
            services.changer_mot_de_passe(
                utilisateur.utilisateur_id,
                nouveau,
                acteur=utilisateur.as_tuple(),
                ancien_mot_de_passe=ancien,
            )
            flash("Votre mot de passe a bien été modifié.", "success")
            return redirect(url_for("dashboard"))
        except services.ErreurMetier as exc:
            flash(str(exc), "error")
    return render_template("mot_de_passe.html", utilisateur=utilisateur)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
