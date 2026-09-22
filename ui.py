"""Interface Tkinter - Application Syndic (version optimisée, adaptée à db.py)."""
import re
import secrets
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import date, datetime
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

import services
import sauvegarde


# ---------------------------------------------------------------
# Validateurs / convertisseurs de saisie
# Chacun reçoit le texte du champ et renvoie la valeur convertie,
# ou lève ValueError avec un message court.
# ---------------------------------------------------------------
def texte(obligatoire=True):
    def conv(v):
        v = v.strip()
        if obligatoire and not v:
            raise ValueError("obligatoire")
        return v
    return conv


def email(obligatoire=False):
    def conv(v):
        v = v.strip()
        if not v:
            if obligatoire:
                raise ValueError("obligatoire")
            return ""
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("adresse invalide")
        return v
    return conv


def montant(v):
    try:
        n = float(v.strip().replace(",", "."))
    except ValueError:
        raise ValueError("doit être un nombre") from None
    if n < 0:
        raise ValueError("doit être positif")
    return n


def actif(v):
    v = v.strip()
    if v not in ("0", "1"):
        raise ValueError("doit être 1 ou 0")
    return int(v)


def id_du_choix(v):
    """Extrait l'ID d'un choix du type '12 - Alaoui Ahmed'."""
    m = re.match(r"\s*(\d+)", v)
    if not m:
        raise ValueError("sélectionnez une valeur dans la liste")
    return int(m.group(1))


def date_iso(obligatoire=True, defaut_aujourdhui=False):
    def conv(v):
        v = v.strip()
        if not v:
            if defaut_aujourdhui:
                return date.today().isoformat()
            if obligatoire:
                raise ValueError("obligatoire")
            return ""
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("format attendu : AAAA-MM-JJ") from None
        return v
    return conv


def _texte(valeur):
    return "" if valeur is None else str(valeur)


# ---------------------------------------------------------------
# Description d'un champ de formulaire
#   cle      : identifiant interne
#   label    : texte affiché
#   col      : colonne du tableau correspondante
#   conv     : validateur / convertisseur
#   valeurs  : liste (ou fonction renvoyant une liste) -> menu déroulant
#   defaut   : valeur affichée à l'ouverture / après réinitialisation
#   champ_db : nom de la colonne SQL (utilisé par db.modifier_*)
# ---------------------------------------------------------------
@dataclass(frozen=True)
class Champ:
    cle: str
    label: str
    col: str
    conv: Callable = texte()
    valeurs: object = None
    defaut: str = ""
    champ_db: str = ""


# ---------------------------------------------------------------
# Onglet générique : formulaire + boutons + tableau
# ---------------------------------------------------------------
class Onglet(ttk.Frame):
    def __init__(self, parent, colonnes, lister, nom="élément",
                 champs=(), ajouter=None, supprimer=None, modifier=None, actions=()):
        """actions : boutons supplémentaires, liste de (libellé, fonction, avec_selection).
        Si avec_selection est vrai, la fonction reçoit la ligne sélectionnée."""
        super().__init__(parent, padding=10)
        self.colonnes = tuple(colonnes)
        self.lister = lister
        self.nom = nom
        self.champs = tuple(champs)
        self.ajouter = ajouter
        self.supprimer = supprimer
        self.modifier = modifier
        self.actions = tuple(actions)
        self.entrees = {}
        self.lignes = {}  # iid -> ligne d'origine (valeurs non altérées par Tk)
        self.idx = {c.cle: self.colonnes.index(c.col) for c in self.champs}
        self.texte_filtre = tk.StringVar()
        self.statut_filtre = tk.StringVar(value="Tous")

        if self.champs:
            self._creer_formulaire()
        elif self.actions:
            barre = ttk.Frame(self)
            barre.pack(fill="x")
            self._boutons_perso(barre, side="left", padx=(0, 6))
        self._creer_tableau()
        self.rafraichir()

    def _boutons_perso(self, conteneur, **options_pack):
        for libelle, fonction, avec_selection in self.actions:
            ttk.Button(
                conteneur, text=libelle,
                command=lambda f=fonction, s=avec_selection: self._action_perso(f, s),
            ).pack(**options_pack)

    # ---------- construction ----------
    def _creer_formulaire(self):
        haut = ttk.Frame(self)
        haut.pack(fill="x")

        for i, ch in enumerate(self.champs):
            ttk.Label(haut, text=ch.label).grid(row=i, column=0, sticky="w", padx=5, pady=3)
            if ch.valeurs is None:
                entree = ttk.Entry(haut, width=30)
            else:
                entree = ttk.Combobox(haut, width=28, state="readonly")
            entree.grid(row=i, column=1, padx=5, pady=3)
            self.entrees[ch.cle] = entree

        boutons = ttk.Frame(haut)
        boutons.grid(row=0, column=2, rowspan=len(self.champs), padx=20, sticky="n")
        actions = [
            ("Enregistrer", self._ajouter, self.ajouter),
            ("Modifier", self._modifier, self.modifier),
            ("Supprimer", self._supprimer, self.supprimer),
            ("Réinitialiser", self._vider, True),
        ]
        for libelle, commande, disponible in actions:
            if disponible:
                ttk.Button(boutons, text=libelle, command=commande).pack(fill="x", pady=2)
        self._boutons_perso(boutons, fill="x", pady=2)

        self._remplir_defauts()

    def _creer_tableau(self):
        filtres = ttk.Frame(self)
        filtres.pack(fill="x", pady=(8, 0))
        ttk.Label(filtres, text="Rechercher :").pack(side="left", padx=(0, 5))
        recherche = ttk.Entry(filtres, textvariable=self.texte_filtre, width=32)
        recherche.pack(side="left")
        self.texte_filtre.trace_add("write", lambda *_: self._afficher_lignes())

        if "Statut" in self.colonnes:
            statuts = ("Tous", "En attente", "En cours", "Résolue", "Fermée")
            if "Type" in self.colonnes and "Message" in self.colonnes:
                statuts = ("Tous", "En attente", "Envoye")
            ttk.Label(filtres, text="Statut :").pack(side="left", padx=(18, 5))
            statut = ttk.Combobox(
                filtres, textvariable=self.statut_filtre,
                values=statuts,
                state="readonly", width=16,
            )
            statut.pack(side="left")
            statut.bind("<<ComboboxSelected>>", lambda _event: self._afficher_lignes())

        ttk.Button(filtres, text="Effacer", command=self._effacer_filtres).pack(
            side="left", padx=8)

        zone = ttk.Frame(self)
        zone.pack(fill="both", expand=True, pady=(10, 0))

        self.table = ttk.Treeview(zone, columns=self.colonnes, show="headings", selectmode="browse")
        for col in self.colonnes:
            etroite = col in ("ID", "Actif")
            self.table.heading(col, text=col)
            self.table.column(col, width=50 if etroite else 100, anchor="w", stretch=not etroite)

        barre = ttk.Scrollbar(zone, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=barre.set)
        self.table.pack(side="left", fill="both", expand=True)
        barre.pack(side="right", fill="y")

        if self.modifier:
            self.table.bind("<<TreeviewSelect>>", self._charger_selection)

    # ---------- formulaire ----------
    def _ecrire(self, ch, valeur):
        entree = self.entrees[ch.cle]
        if ch.valeurs is None:
            entree.delete(0, "end")
            entree.insert(0, valeur)
        else:
            entree.set(valeur)

    def _remplir_defauts(self):
        for ch in self.champs:
            self._ecrire(ch, ch.defaut)

    def _maj_listes(self):
        """Recharge les menus déroulants (ex. liste des copropriétaires)."""
        for ch in self.champs:
            if ch.valeurs is not None:
                choix = ch.valeurs() if callable(ch.valeurs) else ch.valeurs
                self.entrees[ch.cle]["values"] = list(choix)

    def _vider(self):
        self._remplir_defauts()
        self.table.selection_remove(self.table.selection())

    def _lire_formulaire(self):
        valeurs = {}
        for ch in self.champs:
            try:
                valeurs[ch.cle] = ch.conv(self.entrees[ch.cle].get())
            except ValueError as err:
                messagebox.showerror("Saisie invalide", f"{ch.label.rstrip(' :')} : {err}")
                self.entrees[ch.cle].focus_set()
                return None
        return valeurs

    # ---------- données ----------
    def rafraichir(self):
        try:
            donnees = self.lister()
            self._maj_listes()
        except Exception as err:
            messagebox.showerror("Erreur base de données", str(err))
            return
        # On garde les lignes d'origine : Treeview convertit "0612..." en 612...
        self.lignes = {str(ligne[0]): tuple(ligne) for ligne in donnees}
        self._afficher_lignes()

    def _effacer_filtres(self):
        self.texte_filtre.set("")
        self.statut_filtre.set("Tous")

    def _afficher_lignes(self):
        if not hasattr(self, "table"):
            return
        self.table.delete(*self.table.get_children())
        for iid, ligne in self.lignes.items():
            texte = " ".join(_texte(valeur) for valeur in ligne).lower()
            recherche = self.texte_filtre.get().strip().lower()
            if recherche and recherche not in texte:
                continue
            if "Statut" in self.colonnes:
                statut = _texte(ligne[self.colonnes.index("Statut")])
                if self.statut_filtre.get() != "Tous" and statut != self.statut_filtre.get():
                    continue
            self.table.insert("", "end", iid=iid, values=ligne)

    def _ligne_selectionnee(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showwarning("Sélection", f"Sélectionnez {self.nom}.")
            return None
        return self.lignes[selection[0]]

    def _appeler_service(self, fonction, *args):
        try:
            fonction(*args)
            return True
        except services.ErreurMetier as err:
            messagebox.showerror("Opération impossible", str(err))
        except Exception as err:
            messagebox.showerror("Opération impossible", "L'opération n'a pas pu être effectuée.")
        return False

    # ---------- actions ----------
    def _ajouter(self):
        valeurs = self._lire_formulaire()
        if valeurs is None:
            return
        if self._appeler_service(self.ajouter, *valeurs.values()):
            self._vider()
            self.rafraichir()

    def _supprimer(self):
        ligne = self._ligne_selectionnee()
        if ligne and messagebox.askyesno("Confirmation", f"Supprimer {self.nom} n° {ligne[0]} ?"):
            if self._appeler_service(self.supprimer, ligne[0]):
                self._vider()
                self.rafraichir()

    def _action_perso(self, fonction, avec_selection):
        args = ()
        if avec_selection:
            ligne = self._ligne_selectionnee()
            if ligne is None:
                return
            args = (ligne,)
        if self._appeler_service(fonction, *args):
            self.rafraichir()

    def _charger_selection(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        ligne = self.lignes[selection[0]]
        for ch in self.champs:
            self._ecrire(ch, _texte(ligne[self.idx[ch.cle]]))

    def _modifier(self):
        ligne = self._ligne_selectionnee()
        if ligne is None:
            return
        valeurs = self._lire_formulaire()
        if valeurs is None:
            return

        # On ne met à jour que les champs réellement modifiés
        modifies = [
            (ch.champ_db, valeurs[ch.cle]) for ch in self.champs
            if _texte(valeurs[ch.cle]) != _texte(ligne[self.idx[ch.cle]])
        ]
        if not modifies:
            messagebox.showinfo("Modification", "Aucune modification détectée.")
            return
        for champ_db, valeur in modifies:
            if not self._appeler_service(self.modifier, ligne[0], champ_db, valeur):
                break
        self.rafraichir()


# ---------------------------------------------------------------
# Tableau de bord : affiche simplement ce que renvoie services.tableau_de_bord()
# ---------------------------------------------------------------
def argent(valeur):
    return f"{valeur:,.2f}".replace(",", " ") + f" {services.DEVISE}"


def _montant(cle):
    return lambda d: argent(d[cle])


def _nombre(cle):
    return lambda d: str(d[cle])


class TableauDeBord(ttk.Frame):
    # (clé du dictionnaire, titre de la carte, mise en forme, rouge si > 0)
    INDICATEURS = [
        ("coproprietaires_actifs", "Copropriétaires actifs",
         lambda d: f"{d['coproprietaires_actifs']} / {d['coproprietaires_total']}", False),
        ("total_du", "Total dû", _montant("total_du"), False),
        ("total_paye", "Total encaissé", _montant("total_paye"), False),
        ("reste_a_payer", "Reste à payer", _montant("reste_a_payer"), True),
        ("taux_recouvrement", "Taux de recouvrement",
         lambda d: f"{d['taux_recouvrement']} %", False),
        ("paiements_en_retard", "Paiements en retard", _nombre("paiements_en_retard"), True),
        ("total_depenses", "Dépenses", _montant("total_depenses"), False),
        ("solde", "Solde (encaissé - dépenses)", _montant("solde"), False),
        ("reclamations_en_attente", "Réclamations en attente", _nombre("reclamations_en_attente"), True),
        ("rappels_en_attente", "Rappels en attente", _nombre("rappels_en_attente"), True),
    ]
    PAR_LIGNE = 5

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.police = tkfont.nametofont("TkDefaultFont").copy()
        self.police.configure(size=14, weight="bold")
        self.valeurs = {}

        cartes = ttk.Frame(self)
        cartes.pack(fill="x")
        for i, (cle, titre, _fmt, _alerte) in enumerate(self.INDICATEURS):
            carte = ttk.LabelFrame(cartes, text=titre, padding=(10, 6))
            carte.grid(row=i // self.PAR_LIGNE, column=i % self.PAR_LIGNE,
                       sticky="nsew", padx=4, pady=4)
            etiquette = ttk.Label(carte, text="-", font=self.police)
            etiquette.pack(anchor="w")
            self.valeurs[cle] = etiquette
        for c in range(self.PAR_LIGNE):
            cartes.columnconfigure(c, weight=1, uniform="kpi")

        bas = ttk.Frame(self)
        bas.pack(fill="both", expand=True, pady=(10, 0))
        bas.rowconfigure(0, weight=1)
        for c in range(3):
            bas.columnconfigure(c, weight=1, uniform="listes")
        self.t_debiteurs = self._mini_tableau(bas, "Top débiteurs",
                                              ("Copropriétaire", "Appartement", "Reste à payer"), 0)
        self.t_depenses = self._mini_tableau(bas, "Dépenses par type", ("Type", "Total"), 1)
        self.t_reclamations = self._mini_tableau(bas, "Réclamations par statut", ("Statut", "Nombre"), 2)

        ttk.Button(self, text="Actualiser", command=self.rafraichir).pack(anchor="e", pady=(6, 0))
        self.rafraichir()

    @staticmethod
    def _mini_tableau(parent, titre, colonnes, colonne_grille):
        cadre = ttk.LabelFrame(parent, text=titre, padding=6)
        cadre.grid(row=0, column=colonne_grille, sticky="nsew", padx=4)
        table = ttk.Treeview(cadre, columns=colonnes, show="headings", height=8, selectmode="none")
        for col in colonnes:
            table.heading(col, text=col)
            table.column(col, width=100, anchor="w")
        table.pack(fill="both", expand=True)
        return table

    @staticmethod
    def _remplir(table, lignes):
        table.delete(*table.get_children())
        for ligne in lignes:
            table.insert("", "end", values=ligne)

    def rafraichir(self):
        try:
            d = services.tableau_de_bord()
        except Exception as err:
            messagebox.showerror("Erreur base de données", str(err))
            return

        for cle, _titre, formater, alerte in self.INDICATEURS:
            rouge = alerte and d[cle] > 0
            self.valeurs[cle].configure(text=formater(d), foreground="#c0392b" if rouge else "black")

        self._remplir(self.t_debiteurs,
                      [(nom, appt, argent(reste)) for _id, nom, appt, reste in d["top_debiteurs"]])
        self._remplir(self.t_depenses,
                      [(type_, argent(total)) for type_, total in d["depenses_par_type"]])
        self._remplir(self.t_reclamations, d["reclamations_par_statut"])


# ---------------------------------------------------------------
# Liste déroulante des copropriétaires : "12 - Nom Prénom"
# ---------------------------------------------------------------
def choix_coproprietaires():
    return [
        f"{c[0]} - {c[2]} {c[3] or ''}".strip()
        for c in services.lister_coproprietaires() if c[9] != 0
    ]


def generer_rappels_ui():
    nb = services.generer_rappels()
    messagebox.showinfo(
        "Rappels",
        f"{nb} rappel(s) créé(s)." if nb else "Aucun nouveau rappel à créer.")


def escalader_rappels_ui():
    nb = services.escalader_rappels()
    messagebox.showinfo(
        "Relances",
        f"{nb} relance(s) créée(s)." if nb else "Aucune relance supplémentaire à créer.")


def envoyer_rappel_email_ui(ligne):
    email_dest = simpledialog.askstring(
        "Email du destinataire",
        "Adresse e-mail du bénéficiaire pour l'envoi du rappel :",
        initialvalue="",
        parent=None,
    )
    if email_dest is None:
        return
    ok = services.envoyer_rappel_par_email(ligne[0], email_dest.strip() or None)
    if ok:
        messagebox.showinfo("Email envoyé", "Le rappel a bien été envoyé par e-mail.")
    else:
        messagebox.showwarning("Email non envoyé", "Impossible d'envoyer ce rappel : aucun destinataire valide.")


def changer_statut_reclamation_ui(ligne):
    statuts = ("En attente", "En cours", "Résolue", "Fermée")
    nouveau = simpledialog.askstring(
        "Nouveau statut",
        "Choisissez le nouveau statut :",
        initialvalue=ligne[5],
        parent=None,
    )
    if nouveau is None:
        return
    if nouveau not in statuts:
        messagebox.showerror("Statut invalide", "Le statut choisi n'est pas valide.")
        return
    try:
        services.changer_statut_reclamation(ligne[0], nouveau)
        messagebox.showinfo("Statut mis à jour", f"La réclamation n° {ligne[0]} est maintenant en statut : {nouveau}.")
    except services.ErreurMetier as err:
        messagebox.showerror("Statut refusé", str(err))

class Parametres(ttk.Frame):
    def __init__(self, parent, actualiser):
        super().__init__(parent, padding=20)
        ttk.Label(self, text="Paramètres de l'application",
                  font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Label(self, text="Actions d'administration rapides").pack(anchor="w", pady=(0, 8))
        commandes = ttk.Frame(self)
        commandes.pack(anchor="w")
        ttk.Button(commandes, text="Créer une sauvegarde",
                   command=self._sauvegarder).pack(side="left", padx=(0, 8))
        ttk.Button(commandes, text="Actualiser l'onglet actif",
                   command=actualiser).pack(side="left")
        ttk.Label(
            self,
            text="Les sauvegardes sont enregistrées dans le dossier sauvegardes/.\n"
                 "La configuration SMTP pourra être ajoutée ici ultérieurement.",
        ).pack(anchor="w", pady=(18, 0))

    def _sauvegarder(self):
        chemin = sauvegarde.sauvegarder(force=True)
        if chemin:
            messagebox.showinfo("Sauvegarde", f"Sauvegarde créée :\n{chemin.name}")
        else:
            messagebox.showwarning("Sauvegarde", "La base de données est introuvable.")


def creer_compte_resident_ui(ligne):
    identifiant = f"{ligne[2].lower()}_{ligne[0]}".replace(" ", "")
    mot_de_passe = secrets.token_urlsafe(9)
    try:
        services.creer_utilisateur(
            identifiant, mot_de_passe, role="Resident",
            coproprietaire_id=ligne[0], acteur=services.utilisateur_connecte())
    except services.ErreurMetier as err:
        messagebox.showerror("Compte résident", str(err))
        return
    messagebox.showinfo(
        "Compte résident créé",
        f"Identifiant : {identifiant}\n\nMot de passe provisoire : {mot_de_passe}\n\n"
        "Notez-le maintenant : il ne sera plus affiché.")


def demander_connexion(parent):
    resultat = []
    fenetre = tk.Toplevel()
    fenetre.title("Connexion administrateur")
    fenetre.geometry("430x190")
    fenetre.resizable(False, False)
    fenetre.protocol("WM_DELETE_WINDOW", fenetre.destroy)
    identifiant = tk.StringVar()
    mot_de_passe = tk.StringVar()
    cadre = ttk.Frame(fenetre, padding=20)
    cadre.pack()
    ttk.Label(cadre, text="Connexion à l'application Syndic",
              font=("TkDefaultFont", 12, "bold")).grid(
                  row=0, column=0, columnspan=2, pady=(0, 10))
    ttk.Label(cadre, text="Identifiant :").grid(row=1, column=0, sticky="w", pady=4)
    entree_identifiant = ttk.Entry(cadre, textvariable=identifiant, width=28)
    entree_identifiant.grid(row=1, column=1, pady=4)
    ttk.Label(cadre, text="Mot de passe :").grid(row=2, column=0, sticky="w", pady=4)
    entree_mot_de_passe = ttk.Entry(cadre, textvariable=mot_de_passe, show="*", width=28)
    entree_mot_de_passe.grid(row=2, column=1, pady=4)

    def connecter():
        utilisateur = services.verifier_identifiants(identifiant.get(), mot_de_passe.get())
        if not utilisateur:
            messagebox.showerror("Connexion refusée", "Identifiant ou mot de passe incorrect.", parent=fenetre)
            return
        if utilisateur[8]:
            nouveau = simpledialog.askstring(
                "Changement obligatoire",
                "Ce mot de passe est provisoire. Choisissez un nouveau mot de passe :",
                show="*", parent=fenetre)
            if nouveau is None:
                messagebox.showwarning(
                    "Changement obligatoire",
                    "Le changement de mot de passe est obligatoire pour continuer.",
                    parent=fenetre)
                return
            try:
                services.changer_mot_de_passe(utilisateur[0], nouveau, utilisateur)
            except services.ErreurMetier as err:
                messagebox.showerror("Mot de passe invalide", str(err), parent=fenetre)
                return
            utilisateur = services.verifier_identifiants(identifiant.get(), nouveau)
        resultat.append(utilisateur)
        fenetre.destroy()

    ttk.Button(cadre, text="Se connecter", command=connecter).grid(
        row=3, column=0, columnspan=2, sticky="ew", pady=(10, 4))
    cadre.columnconfigure(1, weight=1)
    fenetre.update_idletasks()
    largeur_fenetre = fenetre.winfo_width()
    hauteur_fenetre = fenetre.winfo_height()
    x = max(0, (fenetre.winfo_screenwidth() - largeur_fenetre) // 2)
    y = max(0, (fenetre.winfo_screenheight() - hauteur_fenetre) // 2)
    fenetre.geometry(f"{largeur_fenetre}x{hauteur_fenetre}+{x}+{y}")
    entree_identifiant.focus_set()
    fenetre.grab_set()
    fenetre.deiconify()
    fenetre.lift()
    fenetre.attributes("-topmost", True)
    fenetre.after(250, lambda: fenetre.attributes("-topmost", False))
    fenetre.focus_force()
    parent.wait_window(fenetre)
    return resultat[0] if resultat else None


class TableauResident(ttk.Frame):
    """Vue en lecture seule dont les données sont filtrées par services.py."""
    def __init__(self, parent, utilisateur):
        super().__init__(parent, padding=10)
        self.utilisateur = utilisateur
        ttk.Label(self, text=f"Espace résident - {utilisateur[2]}",
                  font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 8))
        contenu = ttk.Notebook(self)
        contenu.pack(fill="both", expand=True)
        donnees = services.tableau_resident(utilisateur)
        self._table(contenu, "Mes appels et paiements",
                     ("ID", "Mois", "Date", "Dû", "Payé", "Statut", "Mode", "Échéance"),
                     donnees["paiements"])
        self._table(contenu, "Mes réclamations",
                     ("ID", "Date", "Objet", "Description", "Statut"),
                     donnees["reclamations"])
        self._table(contenu, "Mes rappels",
                     ("ID", "Date", "Type", "Message", "Statut"),
                     donnees["rappels"])

    @staticmethod
    def _table(parent, titre, colonnes, lignes):
        cadre = ttk.Frame(parent, padding=8)
        parent.add(cadre, text=titre)
        table = ttk.Treeview(cadre, columns=colonnes, show="headings", selectmode="none")
        for colonne in colonnes:
            table.heading(colonne, text=colonne)
            table.column(colonne, width=120, anchor="w")
        for ligne in lignes:
            table.insert("", "end", values=ligne)
        table.pack(side="left", fill="both", expand=True)
        barre = ttk.Scrollbar(cadre, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=barre.set)
        barre.pack(side="right", fill="y")


def desactiver_utilisateur_ui(ligne):
    services.desactiver_utilisateur(ligne[0])
    messagebox.showinfo("Compte désactivé", f"Le compte {ligne[2]} est désactivé.")


def activer_utilisateur_ui(ligne):
    services.activer_utilisateur(ligne[0])
    messagebox.showinfo("Compte activé", f"Le compte {ligne[2]} est activé.")


def supprimer_utilisateur_ui(ligne):
    if messagebox.askyesno("Confirmation", f"Supprimer le compte {ligne[2]} ?"):
        services.supprimer_utilisateur(ligne[0])


def reinitialiser_mot_de_passe_ui(ligne):
    mot_de_passe = services.reinitialiser_mot_de_passe(ligne[0])
    messagebox.showinfo(
        "Mot de passe provisoire",
        f"Compte : {ligne[2]}\n\nNouveau mot de passe : {mot_de_passe}\n\n"
        "Notez-le maintenant : il ne sera plus affiché.")


# ---------------------------------------------------------------
# Interface principale
# ---------------------------------------------------------------
def lancer():
    services.initialiser_base()

    root = tk.Tk()
    root.title("Application Syndic")

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    largeur = min(1400, max(1000, int(screen_width * 0.85)))
    hauteur = min(900, max(650, int(screen_height * 0.82)))
    x = max(0, (screen_width - largeur) // 2)
    y = max(0, (screen_height - hauteur) // 2)
    root.geometry(f"{largeur}x{hauteur}+{x}+{y}")
    root.minsize(900, 550)

    root.withdraw()
    utilisateur = demander_connexion(root)
    if utilisateur is None:
        root.destroy()
        return
    services.definir_utilisateur_connecte(utilisateur)
    jeton_session = services.creer_session(utilisateur, appareil="Tkinter")
    services.definir_jeton_session(jeton_session)

    def fermer_application():
        services.revoquer_session(jeton_session)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", fermer_application)
    root.deiconify()

    if utilisateur[5] == "Resident":
        TableauResident(root, utilisateur).pack(fill="both", expand=True, padx=10, pady=10)
        root.mainloop()
        return

    aujourdhui = date.today().isoformat()
    tabs = ttk.Notebook(root)
    tabs.pack(fill="both", expand=True, padx=10, pady=10)

    tabs.add(TableauDeBord(tabs), text="Tableau de bord")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Type", "Nom", "Prénom", "Email", "Téléphone",
                  "Appartement", "Situation", "Date", "Actif"),
        lister=services.lister_coproprietaires,
        nom="un copropriétaire",
        champs=[
            Champ("type", "Type :", "Type", valeurs=("Coproprietaire", "Locataire"),
                  defaut="Coproprietaire", champ_db="TypePersonne"),
            Champ("nom", "Nom :", "Nom", champ_db="Nom"),
            Champ("prenom", "Prénom :", "Prénom", texte(False), champ_db="Prenom"),
            Champ("email", "Email :", "Email", email(), champ_db="Email"),
            Champ("tel", "Téléphone :", "Téléphone", texte(False), champ_db="Telephone"),
            Champ("apt", "Appartement :", "Appartement", champ_db="Appartement"),
            Champ("situation", "Situation familiale :", "Situation", texte(False),
                  champ_db="SituationFamiliale"),
            Champ("date", "Date inscription (AAAA-MM-JJ) :", "Date",
                  date_iso(defaut_aujourdhui=True), defaut=aujourdhui, champ_db="DateInscription"),
            Champ("actif", "Actif (1 = oui, 0 = non) :", "Actif", actif,
                  valeurs=("1", "0"), defaut="1", champ_db="Actif"),
        ],
        ajouter=services.ajouter_coproprietaire,
        supprimer=services.supprimer_coproprietaire,
        modifier=services.modifier_coproprietaire,
        actions=[("Créer un accès résident", creer_compte_resident_ui, True)],
    ), text="Copropriétaires")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire", "Mois", "Date", "Montant dû", "Montant payé",
                  "Reste à payer", "Statut", "Mode", "Échéance"),
        lister=services.lister_paiements,
        nom="un paiement",
        champs=[
            Champ("cid", "Copropriétaire :", "Copropriétaire", id_du_choix,
                  valeurs=choix_coproprietaires),
            Champ("mois", "Mois :", "Mois"),
            Champ("date", "Date paiement :", "Date", date_iso(obligatoire=False)),
            Champ("du", "Montant dû :", "Montant dû", montant),
            Champ("paye", "Montant payé :", "Montant payé", montant),
            Champ("mode", "Mode :", "Mode", valeurs=("Espèce", "Virement", "Chèque"),
                defaut="Virement"),
            Champ("echeance", "Échéance (AAAA-MM-JJ) :", "Échéance", date_iso(obligatoire=False)),
        ],
        # Le statut (Paye / En retard / Impaye) est calculé automatiquement
        ajouter=services.enregistrer_paiement,
        supprimer=services.supprimer_paiement,
    ), text="Paiements")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Date", "Type", "Montant", "Description", "Validé par"),
        lister=services.lister_depenses,
        nom="une dépense",
        champs=[
            Champ("date", "Date dépense :", "Date", date_iso(defaut_aujourdhui=True),
                  defaut=aujourdhui),
            Champ("type", "Type :", "Type", valeurs=(
                "Entretien", "Réparation", "Électricité", "Eau", "Nettoyage",
                "Assurance", "Honoraires", "Autre"), defaut="Entretien"),
            Champ("montant", "Montant :", "Montant", montant),
            Champ("desc", "Description :", "Description", texte(False)),
            Champ("valide", "Validé par :", "Validé par", texte(False)),
        ],
        ajouter=services.enregistrer_depense,
        supprimer=services.supprimer_depense,
    ), text="Dépenses")

    # Onglets en lecture seule : pas de formulaire
    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire", "Date", "Objet", "Description", "Statut"),
        lister=services.lister_reclamations,
        nom="une réclamation",
        champs=[
            Champ("cid", "Copropriétaire :", "Copropriétaire", id_du_choix,
                  valeurs=choix_coproprietaires),
            Champ("date", "Date de la réclamation (AAAA-MM-JJ) :", "Date",
                  date_iso(defaut_aujourdhui=True), defaut=aujourdhui),
            Champ("objet", "Objet :", "Objet"),
            Champ("description", "Description :", "Description", texte(False)),
            Champ("statut", "Statut :", "Statut",
                  valeurs=("En attente", "En cours", "Résolue", "Fermée"),
                  defaut="En attente"),
        ],
        ajouter=services.ajouter_reclamation,
        supprimer=services.supprimer_reclamation,
        modifier=lambda reclamation_id, champ, valeur: services.changer_statut_reclamation(reclamation_id, valeur),
        actions=[("Changer le statut", changer_statut_reclamation_ui, True)],
    ), text="Réclamations")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire", "Date", "Type", "Message", "Statut"),
        lister=services.lister_rappels,
        nom="un rappel",
          champs=[
            Champ("cid", "Copropriétaire :", "Copropriétaire", id_du_choix,
                valeurs=choix_coproprietaires),
            Champ("date", "Date du rappel (AAAA-MM-JJ) :", "Date",
                date_iso(defaut_aujourdhui=True), defaut=aujourdhui),
            Champ("type", "Type :", "Type", valeurs=(
                "Rappel de paiement", "Relance", "Information", "Autre"),
                defaut="Rappel de paiement"),
            Champ("message", "Message :", "Message", texte()),
            Champ("statut", "Statut :", "Statut", valeurs=("En attente", "Envoye"),
                defaut="En attente"),
          ],
          ajouter=services.enregistrer_rappel,
          supprimer=None,
        actions=[
            ("Générer les rappels de retard", generer_rappels_ui, False),
            ("Escalader les relances", escalader_rappels_ui, False),
            ("Marquer comme envoyé", lambda ligne: services.marquer_rappel_envoye(ligne[0]), True),
            ("Envoyer par e-mail", envoyer_rappel_email_ui, True),
        ],
    ), text="Rappels")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire ID", "Identifiant", "Rôle", "Actif",
                  "Date création", "Changement requis", "Copropriétaire"),
        lister=services.lister_utilisateurs,
        nom="un utilisateur",
        actions=[
            ("Activer", activer_utilisateur_ui, True),
            ("Désactiver", desactiver_utilisateur_ui, True),
            ("Supprimer", supprimer_utilisateur_ui, True),
            ("Réinitialiser le mot de passe", reinitialiser_mot_de_passe_ui, True),
        ],
    ), text="Utilisateurs")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Utilisateur", "Rôle", "Action", "Détails", "Date/heure"),
        lister=services.lister_journal,
    ), text="Journal")

    def actualiser_onglet_actif():
        widget = root.nametowidget(tabs.select())
        if hasattr(widget, "rafraichir"):
            widget.rafraichir()

    tabs.add(Parametres(tabs, actualiser_onglet_actif), text="Paramètres")

    # Recharge l'onglet affiché à chaque changement d'onglet
    # (nouveaux copropriétaires dans la liste déroulante, données à jour…)
    tabs.bind("<<NotebookTabChanged>>", lambda _e: actualiser_onglet_actif())

    root.mainloop()


if __name__ == "__main__":
    lancer()
