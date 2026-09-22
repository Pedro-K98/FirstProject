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
            ("Ajouter", self._ajouter, self.ajouter),
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
        self.table.delete(*self.table.get_children())
        for iid, ligne in self.lignes.items():
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


def creer_compte_resident_ui(ligne):
    identifiant = f"{ligne[2].lower()}_{ligne[0]}".replace(" ", "")
    mot_de_passe = simpledialog.askstring(
        "Compte résident",
        f"Identifiant généré : {identifiant}\nMot de passe (vide = générer) :",
        show="*",
    )
    if mot_de_passe is None:
        return
    mot_de_passe = mot_de_passe or secrets.token_urlsafe(9)
    try:
        services.creer_utilisateur(
            identifiant, mot_de_passe, role="Resident",
            coproprietaire_id=ligne[0], acteur=services.utilisateur_connecte())
    except services.ErreurMetier as err:
        messagebox.showerror("Compte résident", str(err))
        return
    messagebox.showinfo(
        "Compte résident créé",
        f"Identifiant : {identifiant}\nMot de passe : {mot_de_passe}")


def _creer_premier_admin(parent):
    identifiant = simpledialog.askstring("Premier administrateur", "Identifiant :", parent=parent)
    mot_de_passe = simpledialog.askstring(
        "Premier administrateur", "Mot de passe (8 caractères minimum) :",
        show="*", parent=parent)
    if identifiant is None or mot_de_passe is None:
        return False
    try:
        services.creer_utilisateur(identifiant, mot_de_passe, role="Admin")
    except services.ErreurMetier as err:
        messagebox.showerror("Création du compte", str(err), parent=parent)
        return False
    messagebox.showinfo("Compte créé", "Le premier compte administrateur est prêt.", parent=parent)
    return True


def demander_connexion(parent):
    resultat = []
    fenetre = tk.Toplevel(parent)
    fenetre.title("Connexion administrateur")
    fenetre.resizable(False, False)
    fenetre.protocol("WM_DELETE_WINDOW", fenetre.destroy)
    identifiant = tk.StringVar()
    mot_de_passe = tk.StringVar()
    cadre = ttk.Frame(fenetre, padding=20)
    cadre.pack()
    ttk.Label(cadre, text="Identifiant :").grid(row=0, column=0, sticky="w", pady=4)
    entree_identifiant = ttk.Entry(cadre, textvariable=identifiant, width=28)
    entree_identifiant.grid(row=0, column=1, pady=4)
    ttk.Label(cadre, text="Mot de passe :").grid(row=1, column=0, sticky="w", pady=4)
    entree_mot_de_passe = ttk.Entry(cadre, textvariable=mot_de_passe, show="*", width=28)
    entree_mot_de_passe.grid(row=1, column=1, pady=4)

    def connecter():
        utilisateur = services.verifier_identifiants(identifiant.get(), mot_de_passe.get())
        if not utilisateur or utilisateur[5] != "Admin":
            messagebox.showerror("Connexion refusée", "Identifiant ou mot de passe incorrect.", parent=fenetre)
            return
        resultat.append(utilisateur)
        fenetre.destroy()

    ttk.Button(cadre, text="Se connecter", command=connecter).grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(10, 4))
    if services.compter_administrateurs() == 0:
        ttk.Button(cadre, text="Créer le premier administrateur",
                   command=lambda: _creer_premier_admin(fenetre)).grid(
                       row=3, column=0, columnspan=2, sticky="ew")
    entree_identifiant.focus_set()
    fenetre.transient(parent)
    fenetre.grab_set()
    parent.wait_window(fenetre)
    return resultat[0] if resultat else None


# ---------------------------------------------------------------
# Interface principale
# ---------------------------------------------------------------
def lancer():
    services.initialiser_base()

    root = tk.Tk()
    root.title("Application Syndic")
    root.geometry("1100x650")
    root.minsize(900, 550)

    root.withdraw()
    utilisateur = demander_connexion(root)
    if utilisateur is None:
        root.destroy()
        return
    services.definir_utilisateur_connecte(utilisateur)
    root.deiconify()

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
        actions=[("Créer un compte résident", creer_compte_resident_ui, True)],
    ), text="Copropriétaires")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire", "Mois", "Date", "Montant dû", "Montant payé",
                  "Impayé", "Statut", "Mode", "Échéance"),
        lister=services.lister_paiements,
        nom="un paiement",
        champs=[
            Champ("cid", "Copropriétaire :", "Copropriétaire", id_du_choix,
                  valeurs=choix_coproprietaires),
            Champ("mois", "Mois :", "Mois"),
            Champ("date", "Date paiement :", "Date", date_iso(obligatoire=False)),
            Champ("du", "Montant dû :", "Montant dû", montant),
            Champ("paye", "Montant payé :", "Montant payé", montant),
            Champ("mode", "Mode :", "Mode", texte(False)),
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
            Champ("type", "Type :", "Type"),
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
    ), text="Réclamations")

    tabs.add(Onglet(
        tabs,
        colonnes=("ID", "Copropriétaire", "Date", "Type", "Message", "Statut"),
        lister=services.lister_rappels,
        nom="un rappel",
        actions=[
            ("Générer les rappels de retard", generer_rappels_ui, False),
            ("Marquer comme envoyé", lambda ligne: services.marquer_rappel_envoye(ligne[0]), True),
        ],
    ), text="Rappels")

    # Recharge l'onglet affiché à chaque changement d'onglet
    # (nouveaux copropriétaires dans la liste déroulante, données à jour…)
    tabs.bind("<<NotebookTabChanged>>",
              lambda _e: root.nametowidget(tabs.select()).rafraichir())

    root.mainloop()


if __name__ == "__main__":
    lancer()
