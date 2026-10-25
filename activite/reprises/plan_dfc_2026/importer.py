"""
Verse `activites.csv` dans le plan d'actions DFC 2026, par l'API.

    python activite/reprises/plan_dfc_2026/importer.py            # simulation
    python activite/reprises/plan_dfc_2026/importer.py --reel     # ecrit

    # Rattrapage d'une colonne omise, sur des activites deja creees :
    python activite/reprises/plan_dfc_2026/importer.py --indications --reel
    python activite/reprises/plan_dfc_2026/importer.py --structures --reel

Par l'API et non par l'ORM : ce sont les regles de `services.py` qui doivent
s'appliquer — perimetre, journal des evenements, code d'activite pose par le
declencheur, plan cree s'il n'existe pas. Un import qui ecrit en base court-
circuite tout cela et produit des lignes que l'application ne sait pas relire.

Le mot de passe se donne par l'environnement, jamais en argument : la ligne de
commande figure dans l'historique du shell et dans `ps`.

    export MOT_DE_PASSE_IMPORT='...'

**Reprise possible a tout moment.** Avant d'ecrire, le script lit le plan et
saute les activites dont l'intitule y figure deja. Un import interrompu se
relance sans creer de doublon. Le prix de cette simplicite : deux activites
homonymes ne peuvent pas coexister dans le plan.

Aucune dependance : `urllib` suffit, et le script tourne hors conteneur.
"""

from __future__ import annotations

import csv
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ADRESSE = "https://william-latitude-5580.taild78551.ts.net"
IDENTIFIANT = "focal.dfc"
STRUCTURE = "DFC"
EXERCICE = 2026


class Client:
    """Session authentifiee : cookies portes, jeton CSRF renvoye."""

    def __init__(self, adresse: str):
        self.adresse = adresse.rstrip("/")
        self.bocal = http.cookiejar.CookieJar()
        self.ouvreur = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.bocal))

    def _jeton(self) -> str:
        for biscuit in self.bocal:
            if biscuit.name == "suivi_csrf":
                # `value` est optionnel dans la bibliotheque standard ; un
                # biscuit sans valeur vaut ici l'absence de jeton.
                return biscuit.value or ""
        return ""

    def appeler(self, methode: str, chemin: str, corps: dict | None = None) -> dict:
        url = f"{self.adresse}/api{chemin}"
        donnees = json.dumps(corps).encode() if corps is not None else None
        requete = urllib.request.Request(url, data=donnees, method=methode)
        requete.add_header("Content-Type", "application/json")
        if methode != "GET":
            # Django refuse une ecriture HTTPS sans en-tete d'origine, avant
            # meme de regarder le jeton — l'erreur parle alors de « Referer »
            # et non de CSRF, ce qui envoie chercher au mauvais endroit.
            requete.add_header("X-CSRFToken", self._jeton())
            requete.add_header("Referer", self.adresse + "/")
            requete.add_header("Origin", self.adresse)
        try:
            with self.ouvreur.open(requete, timeout=30) as reponse:
                brut = reponse.read().decode()
                return json.loads(brut) if brut else {}
        except urllib.error.HTTPError as erreur:
            detail = erreur.read().decode()
            try:
                detail = json.loads(detail).get("message", detail)
            except json.JSONDecodeError:
                detail = detail[:200]
            raise Refus(f"{erreur.code} — {detail}") from None

    def connexion(self, identifiant: str, mot_de_passe: str) -> dict:
        # Un GET prealable pose le cookie CSRF : la connexion est une ecriture,
        # elle est donc elle-meme protegee.
        try:
            self.appeler("GET", "/moi")
        except Refus:
            pass
        return self.appeler(
            "POST", "/connexion", {"identifiant": identifiant, "motDePasse": mot_de_passe}
        )


class Refus(Exception):
    pass


#: Le libelle de la tache unique d'une activite que le classeur ne decoupe
#: pas — le meme que la reprise SQL de l'ADR 049.
TACHE_UNIQUE = "Exécution de l'activité"


def _taches(ligne: dict, debut: str, fin: str) -> list[dict]:
    """
    Les taches de la ligne, saisies avec l'activite (RG-1, ADR 049).

    **Parts egales, supposees** : le classeur ne pondere pas ses taches, et
    RG-3 exige une somme de 100. Le calcul se fait en centiemes entiers pour
    que la somme tombe juste ; le reliquat d'arrondi va a la derniere tache,
    comme dans la reprise SQL. Chaque tache couvre la periode de l'activite :
    le classeur ne date pas les taches. Les parts se corrigent a l'ecran.
    """
    libelles = [t for t in ligne["taches"].split(" || ") if t] or [TACHE_UNIQUE]
    base = 10000 // len(libelles)
    centiemes = [base] * (len(libelles) - 1) + [10000 - base * (len(libelles) - 1)]
    return [
        {"libelle": libelle, "valeurPrevue": part / 100, "moisDebut": debut, "moisFin": fin}
        for libelle, part in zip(libelles, centiemes, strict=True)
    ]


#: La colonne « INDICATIONS » du classeur n'a pas d'equivalent au modele et
#: contredit parfois la valeur cible. Elle est reportee telle quelle, precedee
#: de sa provenance : sans elle, personne ne saurait dans six mois d'ou sort
#: ce « 100% ».
PREFIXE_INDICATIONS = "Indications du classeur : "


def _resultats(ligne: dict) -> str:
    indications = ligne.get("indications", "").strip()
    return f"{PREFIXE_INDICATIONS}{indications}" if indications else ""


def _charge(ligne: dict) -> dict:
    """La ligne du tableau, telle que `SaisieActivite` l'attend."""
    return {
        "intitule": ligne["intitule"],
        "axe": ligne["axe_propose"],
        "objectif": ligne["objectif"],
        "etatReferenceGeneral": ligne["etat_reference"],
        "resultatsAttendus": _resultats(ligne),
        "debut": ligne["date_debut"],
        "fin": ligne["date_fin"],
        "budgetValide": float(ligne["budget_valide"]) if ligne["budget_valide"] else None,
        # Le point focal ne se devine pas : la colonne du classeur nomme des
        # structures, pas des agents. Il se pose a l'ecran (ADR 047 : ce qui
        # repond de l'activite, ce sont les structures).
        "responsableId": None,
        "structuresAssociees": [s for s in ligne["structures_associees"].split() if s != STRUCTURE],
        "taches": _taches(ligne, ligne["date_debut"][:7], ligne["date_fin"][:7]),
    }


def verser(client: Client, lignes: list[dict], *, reel: bool) -> int:
    plan = client.appeler("GET", f"/activites/plan?annee={EXERCICE}&structure={STRUCTURE}")
    deja = {a["intitule"].strip() for a in plan["activites"]}
    print(f"Plan {STRUCTURE} {EXERCICE} : etat « {plan['etat']} », {len(deja)} activite(s).\n")

    creees = sautees = refusees = 0
    for ligne in lignes:
        intitule = ligne["intitule"]
        if intitule in deja:
            print(f"  = {intitule[:70]}")
            sautees += 1
            continue

        charge = _charge(ligne)
        taches = charge["taches"]
        indicateur = (
            {
                "libelle": ligne["indicateur"] or intitule,
                "unite": ligne["unite"],
                "etatReference": "",
                "cible": ligne["valeur_cible"],
            }
            if ligne["valeur_cible"]
            else None
        )

        if not reel:
            print(f"  + {intitule[:70]}")
            print(
                f"      axe {charge['axe']} | {charge['debut']} -> {charge['fin']}"
                f" | {len(taches)} tache(s) a parts egales"
                f" | {'1' if indicateur else '0'} indicateur"
                f" | associees : {', '.join(charge['structuresAssociees']) or 'aucune'}"
            )
            creees += 1
            continue

        try:
            identifiant = client.appeler("POST", "/activites", charge)["id"]
        except Refus as refus:
            print(f"  ! {intitule[:60]} — {refus}")
            refusees += 1
            continue

        if indicateur:
            try:
                client.appeler("POST", f"/activites/{identifiant}/indicateurs", indicateur)
            except Refus as refus:
                print(f"    ! indicateur de « {intitule[:40]} » — {refus}")

        print(f"  + [{identifiant}] {intitule[:60]}")
        creees += 1

    verbe = "creees" if reel else "a creer"
    print(f"\n{creees} {verbe}, {sautees} deja presentes, {refusees} refusees.")
    return 1 if refusees else 0


def main() -> int:
    reel = "--reel" in sys.argv
    mot_de_passe = os.environ.get("MOT_DE_PASSE_IMPORT", "")
    if not mot_de_passe:
        print("Renseignez MOT_DE_PASSE_IMPORT dans l'environnement.")
        return 2

    tableau = Path(__file__).with_name("activites.csv")
    with tableau.open(encoding="utf-8") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))

    client = Client(ADRESSE)
    try:
        moi = client.connexion(IDENTIFIANT, mot_de_passe)
    except Refus as refus:
        print(f"Connexion refusee : {refus}")
        return 1
    print(f"Connecte : {moi['nomComplet']} ({moi.get('structureSigle') or '?'})")
    print("Mode : " + ("ECRITURE REELLE" if reel else "simulation, rien n'est ecrit") + "\n")

    if "--structures" in sys.argv:
        return completer_structures(client, lignes, reel=reel)
    if "--indications" in sys.argv:
        return completer_indications(client, lignes, reel=reel)
    return verser(client, lignes, reel=reel)


# ---------------------------------------------------------------------
#  Rattrapage : reporter les indications sur des activites deja creees.
#
#  La colonne « INDICATIONS » a ete omise du premier import. Recreer les
#  activites ferait perdre les corrections deja saisies a l'ecran ; la
#  charge de modification est donc construite depuis **la fiche en base**,
#  et non depuis le tableau. Seuls les resultats attendus changent.
# ---------------------------------------------------------------------
def completer_indications(client: Client, lignes: list[dict], *, reel: bool) -> int:
    plan = client.appeler("GET", f"/activites/plan?annee={EXERCICE}&structure={STRUCTURE}")
    par_intitule = {a["intitule"].strip(): a["id"] for a in plan["activites"]}

    touchees = absentes = 0
    for ligne in lignes:
        attendu = _resultats(ligne)
        if not attendu:
            continue
        identifiant = par_intitule.get(ligne["intitule"])
        if identifiant is None:
            print(f"  ? absente du plan : {ligne['intitule'][:60]}")
            absentes += 1
            continue

        fiche = client.appeler("GET", f"/activites/{identifiant}")
        if fiche["resultatsAttendus"].strip():
            print(f"  = deja renseigne : {fiche['reference']}")
            continue

        if not reel:
            print(f"  ~ {fiche['reference']} <- {attendu}")
            touchees += 1
            continue

        client.appeler(
            "POST",
            f"/activites/{identifiant}",
            {
                "intitule": fiche["intitule"],
                "axe": fiche["axe"],
                "objectif": fiche["objectif"],
                "etatReferenceGeneral": fiche["etatReferenceGeneral"],
                "resultatsAttendus": attendu,
                "debut": fiche["debut"],
                "fin": fiche["fin"],
                "budgetValide": fiche["budgetValide"],
                "responsableId": fiche["responsableId"],
                "structuresAssociees": [s["sigle"] for s in fiche["structuresAssociees"]],
                "motif": "Report de la colonne « INDICATIONS » du classeur, omise a l'import.",
            },
        )
        print(f"  ~ {fiche['reference']} <- {attendu}")
        touchees += 1

    verbe = "completees" if reel else "a completer"
    print(f"\n{touchees} {verbe}, {absentes} introuvables.")
    return 1 if absentes else 0


# ---------------------------------------------------------------------
#  Rattrapage : ajouter des structures associees a des activites deja
#  creees, sans toucher au reste.
#
#  Quatre sigles du classeur etaient absents de l'organigramme et ont ete
#  tranches apres l'import. La liste soumise **fait foi** (ADR 047) : ce
#  qui n'y figure plus est retire. Elle est donc construite par union de
#  ce que porte la fiche et de ce que le tableau prevoit — jamais par
#  remplacement, faute de quoi une association ajoutee a l'ecran depuis
#  l'import disparaitrait sans trace.
# ---------------------------------------------------------------------
def completer_structures(client: Client, lignes: list[dict], *, reel: bool) -> int:
    plan = client.appeler("GET", f"/activites/plan?annee={EXERCICE}&structure={STRUCTURE}")
    par_intitule = {a["intitule"].strip(): a["id"] for a in plan["activites"]}

    touchees = 0
    for ligne in lignes:
        attendues = {s for s in ligne["structures_associees"].split() if s != STRUCTURE}
        identifiant = par_intitule.get(ligne["intitule"])
        if identifiant is None or not attendues:
            continue

        fiche = client.appeler("GET", f"/activites/{identifiant}")
        portees = {s["sigle"] for s in fiche["structuresAssociees"]}
        manquantes = attendues - portees
        if not manquantes:
            continue

        union = sorted(portees | attendues)
        print(f"  ~ {fiche['reference']} + {', '.join(sorted(manquantes))}  -> {', '.join(union)}")
        touchees += 1
        if not reel:
            continue

        client.appeler(
            "POST",
            f"/activites/{identifiant}",
            {
                "intitule": fiche["intitule"],
                "axe": fiche["axe"],
                "objectif": fiche["objectif"],
                "etatReferenceGeneral": fiche["etatReferenceGeneral"],
                "resultatsAttendus": fiche["resultatsAttendus"],
                "debut": fiche["debut"],
                "fin": fiche["fin"],
                "budgetValide": fiche["budgetValide"],
                "responsableId": fiche["responsableId"],
                "structuresAssociees": union,
                "motif": "Rattachement des sigles du classeur absents de l'organigramme.",
            },
        )

    verbe = "completees" if reel else "a completer"
    print(f"\n{touchees} {verbe}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
