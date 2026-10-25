"""
Lit le classeur du plan d'actions DFC 2026 et rend le tableau a viser.

    python activite/reprises/plan_dfc_2026/extraire.py \
        ~/Telechargements/PLAN_ACTIONS_2026_DFC.xlsx

Il ecrit `activites.csv` a cote de ce fichier : une ligne par activite, les
champs du modele d'un cote, la valeur d'origine de l'autre, et une colonne
`a_completer` qui nomme, ligne a ligne, ce qui n'a pas pu etre rapproche.
C'est ce fichier que l'import lit — jamais le classeur.

`a_completer` **ne bloque pas** : l'activite est creee malgre tout, avec le
champ laisse vide, et se complete ensuite a l'ecran (arbitrage du
9 septembre 2026). La colonne est la liste de travail de cette reprise.

Aucune dependance : un `.xlsx` est une archive de XML, et `openpyxl` n'est
pas au projet. Le format lu est volontairement minimal (chaines partagees et
valeurs), ce qui suffit ici et ne suffirait pas a un classeur quelconque.
"""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from activite.reprises.plan_dfc_2026 import correspondances as C

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXERCICE = 2026

#: Ordre des colonnes du classeur. Fige ici : un decalage silencieux
#: produirait un tableau credible et faux.
OBJECTIF, NUMERO, ETAT_LIEUX, INDICATIONS, CODE_LIBELLE = 0, 1, 2, 3, 4
TACHES, RESPONSABLES, INDICATEURS, BUDGET, CIBLE, PERIODE = 5, 6, 7, 8, 9, 10


def _index(reference: str) -> int:
    """« BC12 » -> 54. La colonne est en base 26 sans zero."""
    lettres = re.match(r"[A-Z]+", reference)
    if lettres is None:
        # Une reference de cellule commence toujours par des lettres. Si ce
        # n'est pas le cas, le classeur n'est pas celui qu'on croit : mieux
        # vaut s'arreter que decaler une colonne en silence.
        raise ValueError(f"Reference de cellule illisible : {reference!r}")
    n = 0
    for caractere in lettres.group(0):
        n = n * 26 + ord(caractere) - 64
    return n - 1


def lignes_du_classeur(chemin: Path) -> list[list[str]]:
    archive = zipfile.ZipFile(chemin)
    chaines = [
        "".join(t.text or "" for t in si.iter(f"{NS}t"))
        for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall(f"{NS}si")
    ]
    feuille = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    lignes = []
    for rang in feuille.iter(f"{NS}row"):
        cellules: dict[int, str] = {}
        for cellule in rang.findall(f"{NS}c"):
            valeur = cellule.find(f"{NS}v")
            reference = cellule.get("r")
            # Une cellule sans valeur, sans texte ou sans reference ne porte
            # rien qu'on sache placer : elle est ignoree, comme l'etait deja
            # celle depourvue de `<v>`.
            if valeur is None or valeur.text is None or reference is None:
                continue
            brut = chaines[int(valeur.text)] if cellule.get("t") == "s" else valeur.text
            cellules[_index(reference)] = brut
        if cellules:
            lignes.append([cellules.get(i, "") for i in range(max(cellules) + 1)])
    return lignes


def _champ(ligne: list[str], rang: int) -> str:
    return (ligne[rang] if len(ligne) > rang else "").strip()


def _taches(texte: str) -> list[str]:
    """
    Eclate « 1. Faire ceci ; 2. Faire cela » en taches distinctes.

    Le classeur numerote tantot « 1. », tantot « 1- », et separe tantot par
    un retour a la ligne, tantot par un point-virgule. Une cellule sans
    numerotation reste une tache unique — la decouper sur la ponctuation
    hacherait des phrases.
    """
    if not texte.strip():
        return []
    morceaux = re.split(r"(?:^|\n|\s)\d+\s*[.\-)]\s*", texte)
    morceaux = [m.strip(" ;\n\t") for m in morceaux if m.strip(" ;\n\t")]
    return morceaux or [texte.strip()]


def _structures(texte: str) -> tuple[list[str], list[str]]:
    """Rend les sigles resolus, et ceux qui restent sans cible."""
    resolues, en_suspens = [], []
    for brut in re.split(r"[/,]", texte):
        sigle = brut.strip()
        if not sigle:
            continue
        regle = C.STRUCTURES.get(sigle)
        if regle is None:
            en_suspens.append(f"sigle inconnu du fichier de correspondance : {sigle}")
        elif regle[0] is None:
            if regle[1] == C.A_VALIDER:
                en_suspens.append(f"structure a trancher : {sigle} ({regle[2]})")
        else:
            resolues.append(regle[0])
    return resolues, en_suspens


def convertir(chemin: Path) -> list[dict]:
    lignes = lignes_du_classeur(chemin)
    programme = action = activite_budgetaire = ""
    sorties = []

    for ligne in lignes:
        tete = _champ(ligne, OBJECTIF).upper()
        if tete.startswith("PROGRAMME"):
            programme = _champ(ligne, OBJECTIF)
            continue
        if tete.startswith("ACTION "):
            action = _champ(ligne, OBJECTIF)
            continue
        if tete.startswith("ACTIVITE"):
            activite_budgetaire = _champ(ligne, OBJECTIF)
            continue
        if not _champ(ligne, NUMERO).isdigit():
            continue

        a_completer: list[str] = []
        code_libelle = _champ(ligne, CODE_LIBELLE)
        numero = re.match(r"(\d+)", code_libelle)
        code = numero.group(1) if numero else ""
        intitule = code_libelle[len(code) :].strip() or code_libelle

        # Axe : l'exception de ligne l'emporte sur la regle d'activite.
        rang_budgetaire = re.search(r"ACTIVITE\s+(\d+)", activite_budgetaire)
        cle_budget = rang_budgetaire.group(1) if rang_budgetaire else ""
        axe, motif_axe = C.AXE_PAR_LIGNE.get(code) or C.AXE_PAR_ACTIVITE_BUDGETAIRE.get(
            cle_budget, ("", "aucune regle")
        )
        libelle_axe = C.LIBELLES_AXES.get(axe, "")
        if not libelle_axe:
            # `axe_strategique` est non nul : sans axe, pas d'activite. Le
            # referentiel n'en compte que trois ; A1 porte les activites de
            # gestion courante, qui sont le gros du plan.
            axe, libelle_axe = "A1", C.LIBELLES_AXES["A1"]
            motif_axe = "aucune regle, repli sur A1"
        a_completer.append(f"axe {axe} propose ({motif_axe}) — modifiable a l'ecran")

        structures, suspens_structures = _structures(_champ(ligne, RESPONSABLES))
        a_completer += suspens_structures

        periode = _champ(ligne, PERIODE)
        regle_periode = C.PERIODES.get(periode)
        if regle_periode is None:
            # `date_debut` et `date_fin` sont non nulles : l'activite couvre
            # l'exercice, ce qui est vrai par defaut et se resserre a l'ecran.
            debut = f"{EXERCICE}-{C.PERIODE_PAR_DEFAUT[0]}"
            fin = f"{EXERCICE}-{C.PERIODE_PAR_DEFAUT[1]}"
            libelle = periode or "cellule vide"
            a_completer.append(f"periode « {libelle} » non reconnue — exercice entier retenu")
        else:
            debut = f"{EXERCICE}-{regle_periode[0]}"
            fin = f"{EXERCICE}-{regle_periode[1]}"
            if regle_periode[2] == C.A_VALIDER:
                a_completer.append(f"periode « {periode} » lue comme {regle_periode[3]}")

        cible_brute = _champ(ligne, CIBLE)
        regle_cible = C.CIBLES.get(cible_brute)
        if cible_brute and regle_cible is None:
            valeur = unite = ""
            a_completer.append(
                f"valeur cible « {cible_brute} » non convertie — indicateur non cree"
            )
        elif regle_cible and regle_cible[0] is None:
            valeur = unite = ""
            a_completer.append(f"valeur cible « {cible_brute} » ambigue — indicateur non cree")
        else:
            valeur = (regle_cible or ("", None, ""))[0] or ""
            unite = (regle_cible or ("", None, ""))[1] or ""

        if not _champ(ligne, OBJECTIF):
            a_completer.append("objectif absent du classeur")

        # « INDICATIONS » : colonne distincte des valeurs cibles, et qui les
        # contredit parfois — n° 17 porte « 100% » en indication et « 9 » en
        # cible. Elle vaut « 100% » sur dix-sept lignes, du texte libre sur
        # deux, « / » sur une. Sa semantique n'est pas etablie : elle est
        # reportee telle quelle dans les resultats attendus, sans conversion.
        indications = _champ(ligne, INDICATIONS)
        if indications == "/":
            indications = ""
        if indications:
            a_completer.append(f"indication du classeur « {indications} » — sens a preciser")

        sorties.append(
            {
                "numero": _champ(ligne, NUMERO),
                "code_budgetaire": code,
                "programme": programme,
                "action": action,
                "activite_budgetaire": activite_budgetaire,
                "intitule": intitule,
                "objectif": _champ(ligne, OBJECTIF),
                "etat_reference": _champ(ligne, ETAT_LIEUX),
                "indications": indications,
                "axe_propose": libelle_axe,
                "structures_associees": " ".join(structures),
                "responsables_origine": _champ(ligne, RESPONSABLES),
                "date_debut": debut,
                "date_fin": fin,
                "periode_origine": periode,
                "indicateur": _champ(ligne, INDICATEURS),
                "valeur_cible": valeur,
                "unite": unite,
                "cible_origine": cible_brute,
                "budget_valide": _champ(ligne, BUDGET),
                "taches": " || ".join(_taches(_champ(ligne, TACHES))),
                "nombre_taches": str(len(_taches(_champ(ligne, TACHES)))),
                "a_completer": " ; ".join(a_completer),
            }
        )
    return sorties


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1]).expanduser()
    if not source.exists():
        print(f"Classeur introuvable : {source}")
        return 1

    lignes = convertir(source)
    destination = Path(__file__).with_name("activites.csv")
    with destination.open("w", newline="", encoding="utf-8") as f:
        graveur = csv.DictWriter(f, fieldnames=list(lignes[0]), delimiter=";")
        graveur.writeheader()
        graveur.writerows(lignes)

    # L'axe est toujours signale : il est propose, jamais lu. On ne compte
    # donc que les lignes qui portent autre chose que lui.
    a_completer = sum(1 for ligne in lignes if len(ligne["a_completer"].split(" ; ")) > 1)
    sans_indicateur = sum(1 for ligne in lignes if not ligne["valeur_cible"])
    sans_structure = sum(1 for ligne in lignes if not ligne["structures_associees"])
    print(f"{len(lignes)} activites ecrites dans {destination}")
    print(f"{a_completer} portent un champ a completer a l'ecran, dont :")
    print(f"  {sans_indicateur} sans indicateur (valeur cible absente ou ambigue)")
    print(f"  {sans_structure} sans structure associee")
    print("L'axe de toutes est propose, et modifiable a l'ecran.")
    print("\nL'import lit ce CSV, jamais le classeur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
