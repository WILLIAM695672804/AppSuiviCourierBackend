"""
Les rapports periodiques — D-03, §3.11.

Ce que les tableaux de bord ne font pas. Un tableau de bord repond a « ou en
sommes-nous aujourd'hui » et change chaque matin ; un rapport periodique repond
a « qu'a-t-on fait entre ces deux dates » et **ne doit plus changer une fois la
periode close**. Les deux ecrans se ressemblent, leurs chiffres non : les
mesures d'un rapport sont bornees par `pilotage/periodes.py`, jamais par la
date du jour.

Trois consequences tenues ici :

 * une periode non close est ramenee a la derniere close, et le serveur le dit
   (`periodeRamenee`) — meme raisonnement que l'ADR 009 pour le perimetre ;
 * le perimetre est resolu par `structure.py`, et pas autrement : deux ecrans
   qui repondraient differemment au meme sigle donneraient deux verites sur la
   meme structure. Un sigle hors perimetre rend 404 (D5) ;
 * ce qui n'est pas mesurable sort a « Non mesuré » avec sa raison, jamais a
   zero (ADR 011). Le courrier reste la ligne vide de tous les rapports du
   Port tant que son pilier n'existe pas.

L'export est le meme contenu, dans le meme ordre, en CSV. Il est **servi par le
serveur** et non fabrique par le navigateur : un tableur assemble cote client
n'aurait laisse aucune trace, alors que sortir une donnee du systeme est un
acte au sens du §3.12. `api.py` inscrit donc un acces `export` — c'est le seul
endroit du pilotage ou une lecture se trace.
"""

from datetime import date

from dossier.lecture import instruction_dans_le_delai
from noyau import documents
from noyau.calendrier import en_toutes_lettres
from noyau.feu import feu
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.perimetre.modeles import PORTEE_TOUTES
from noyau.perimetre.portee import perimetre_en_vigueur
from pilotage import mesures, periodes
from pilotage.structure import structure_cible, structures_accessibles

INSTITUTION = "institution"
STRUCTURE = "structure"


def rapport(
    utilisateur: Utilisateur,
    *,
    granularite: str = periodes.MOIS,
    annee: int | None = None,
    rang: int | None = None,
    sigle: str = "",
    perimetre: str = "",
    aujourd_hui: date | None = None,
) -> dict:
    """
    Le rapport periodique d'un perimetre, sur une periode close.

    `perimetre` vaut `institution` ou `structure`. Vide, il vaut `institution`
    pour qui voit tout et `structure` pour les autres : demander a un point
    focal de choisir son propre perimetre chaque fois n'apprend rien a
    personne, et lui proposer « institution » pour lui rendre sa seule
    structure aurait ete un mensonge d'affichage.
    """
    jour = aujourd_hui or date.today()
    periode, ramenee = periodes.resoudre(granularite, annee, rang, aujourd_hui=jour)
    precedente = periodes.precedente(periode)

    accessibles = structures_accessibles(utilisateur)
    etendue = _perimetre_applique(utilisateur, perimetre)

    if etendue == INSTITUTION:
        cible = None
        structures: list[Structure] | None = None
        libelle_perimetre = "Ensemble de l'institution"
    else:
        cible = structure_cible(utilisateur, accessibles, sigle)
        structures = [cible]
        libelle_perimetre = f"{cible.code} — {cible.libelle}"

    return {
        "periode": {
            "granularite": periode.granularite,
            "annee": periode.annee,
            "rang": periode.rang,
            "code": periode.code,
            "libelle": periode.libelle,
            "debut": periode.debut.isoformat(),
            "fin": periode.fin.isoformat(),
        },
        # La demande n'a pas ete honoree telle quelle : l'ecran doit le dire,
        # sans quoi l'agent croit a un bogue.
        "periodeRamenee": ramenee,
        "comparaison": precedente.libelle,
        "perimetre": etendue,
        "perimetreLibelle": libelle_perimetre,
        "structureSigle": cible.code if cible is not None else "",
        "structuresAccessibles": [
            {"sigle": structure.code, "libelle": structure.libelle} for structure in accessibles
        ],
        "peutVoirInstitution": _voit_l_institution(utilisateur),
        "editeLe": en_toutes_lettres(jour),
        "editePar": utilisateur.nom_complet,
        "sections": _sections(structures, periode, precedente),
        # Le courrier est sorti de cette liste le 27 aout 2026 : il se mesure.
        # La liste reste, parce que ce qui n'est pas mesure doit continuer de se
        # dire — et parce qu'elle se remplira de nouveau au prochain pilier.
        "nonMesure": [],
    }


# =====================================================================
#  Le perimetre
# =====================================================================


def _voit_l_institution(utilisateur: Utilisateur) -> bool:
    """
    Seule une portee « toutes » consolide l'institution.

    Une portee bornee a une branche verrait un total qui n'est pas celui de
    l'institution mais qui en porterait le nom — et un rapport signe « ensemble
    de l'institution » se transmet.
    """
    portee = perimetre_en_vigueur(utilisateur)
    return portee is not None and portee.portee == PORTEE_TOUTES


def _perimetre_applique(utilisateur: Utilisateur, demande: str) -> str:
    if not _voit_l_institution(utilisateur):
        return STRUCTURE
    if demande == STRUCTURE:
        return STRUCTURE
    return INSTITUTION


# =====================================================================
#  Le contenu
# =====================================================================


def _sections(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    return [
        {"titre": "Activités", "lignes": _activites(structures, periode, precedente)},
        {"titre": "Dossiers instruits", "lignes": _dossiers(structures, periode, precedente)},
        {"titre": "Rituels de production", "lignes": _rituels(structures, periode, precedente)},
        {"titre": "Décisions d'instance", "lignes": _decisions(structures, periode, precedente)},
        {"titre": "Courrier", "lignes": _courrier(structures, periode, precedente)},
    ]


def _ligne(
    libelle: str,
    valeur: str,
    note: str,
    *,
    feu_ligne: str = "inconnu",
    variation: str | None = None,
) -> dict:
    return {
        "libelle": libelle,
        "valeur": valeur,
        "note": note,
        "feu": feu_ligne,
        "variation": variation,
    }


def _taux(numerateur: int, denominateur: int) -> float | None:
    """Un taux, ou `None` quand il n'y a rien a diviser — jamais zero (ADR 011)."""
    return round(numerateur / denominateur * 100, 1) if denominateur else None


def _activites(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    ouvertes = mesures.activites_ouvertes_periode(structures, debut=periode.debut, fin=periode.fin)
    achevees = mesures.activites_achevees_periode(structures, debut=periode.debut, fin=periode.fin)

    # L'avancement se lit **a la fin de la periode**, et non aujourd'hui : c'est
    # ce qui rend le rapport reproductible six mois plus tard.
    execution = mesures.execution_activites(structures, a_la_date=periode.fin)
    execution_avant = mesures.execution_activites(structures, a_la_date=precedente.fin)

    a_l_heure, commencees = mesures.activites_a_l_heure(structures, a_la_date=periode.fin)
    ponctualite = _taux(a_l_heure, commencees)

    return [
        _ligne(
            "Activités ouvertes dans la période",
            str(ouvertes),
            "activités dont la date de début tombe dans la période",
        ),
        _ligne(
            "Activités achevées dans la période",
            str(achevees),
            "avancement à 100 % et date de fin dans la période",
        ),
        _ligne(
            "Avancement moyen à la clôture",
            f"{execution} %" if execution is not None else "Non mesuré",
            "moyenne des avancements des activités commencées",
            feu_ligne=feu(execution),
            variation=mesures.variation(execution, execution_avant),
        ),
        _ligne(
            "Activités à l'heure à la clôture",
            f"{a_l_heure} / {commencees}" if commencees else "Aucune",
            "activités commencées et non en retard",
            feu_ligne=feu(ponctualite),
        ),
    ]


def _dossiers(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    dans_le_delai, clos = instruction_dans_le_delai(
        structures, a_la_date=periode.fin, depuis=periode.debut
    )
    avant, clos_avant = instruction_dans_le_delai(
        structures, a_la_date=precedente.fin, depuis=precedente.debut
    )

    taux = _taux(dans_le_delai, clos)
    taux_avant = _taux(avant, clos_avant)

    return [
        _ligne(
            "Dossiers clos dans la période",
            str(clos),
            "dossiers dont la clôture tombe dans la période",
        ),
        _ligne(
            "Dossiers instruits dans le délai",
            f"{taux} %" if taux is not None else "Non mesuré",
            (f"{dans_le_delai} sur {clos} dossier(s) clos" if clos else mesures.SANS_DOSSIERS_CLOS),
            feu_ligne=feu(taux),
            variation=mesures.variation(taux, taux_avant),
        ),
    ]


def _rituels(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    a_temps, echues = mesures.obligations_de_la_periode(
        structures, debut=periode.debut, fin=periode.fin
    )
    avant, echues_avant = mesures.obligations_de_la_periode(
        structures, debut=precedente.debut, fin=precedente.fin
    )
    jamais = mesures.obligations_non_deposees(structures, debut=periode.debut, fin=periode.fin)

    taux = _taux(a_temps, echues)

    return [
        _ligne(
            "Productions attendues",
            str(echues),
            "obligations du calendrier officiel échues dans la période",
        ),
        _ligne(
            "Déposées à l'échéance",
            f"{a_temps} / {echues}" if echues else "Aucune attendue",
            "dépôt intervenu au plus tard le jour de l'échéance",
            feu_ligne=feu(taux),
            variation=mesures.variation(taux, _taux(avant, echues_avant)),
        ),
        _ligne(
            "Jamais déposées à ce jour",
            str(jamais),
            "échéance de la période passée, aucun dépôt enregistré",
            # Un comptage d'anomalies : zero est vert, une seule est rouge.
            # Le passer par `feu()` aurait exige d'en faire un taux, qui ne veut
            # rien dire ici.
            feu_ligne="vert" if jamais == 0 else "rouge",
        ),
    ]


def _decisions(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    executees = mesures.decisions_executees_periode(
        structures, debut=periode.debut, fin=periode.fin
    )
    echues = mesures.decisions_echues_periode(structures, debut=periode.debut, fin=periode.fin)
    executees_avant = mesures.decisions_executees_periode(
        structures, debut=precedente.debut, fin=precedente.fin
    )
    echues_avant = mesures.decisions_echues_periode(
        structures, debut=precedente.debut, fin=precedente.fin
    )

    taux = _taux(executees, echues)

    return [
        _ligne(
            "Décisions échues dans la période",
            str(echues),
            "engagements d'instance dont l'échéance tombe dans la période",
        ),
        _ligne(
            "Décisions exécutées",
            str(executees),
            "exécution enregistrée dans la période",
        ),
        _ligne(
            "Taux d'exécution des décisions",
            f"{taux} %" if taux is not None else "Non mesuré",
            (
                f"{executees} exécutée(s) pour {echues} échue(s)"
                if echues
                else "aucune décision échue dans la période"
            ),
            feu_ligne=feu(taux),
            variation=mesures.variation(taux, _taux(executees_avant, echues_avant)),
        ),
    ]


def _courrier(
    structures: list[Structure] | None,
    periode: periodes.Periode,
    precedente: periodes.Periode,
) -> list[dict]:
    """
    La section courrier — **mesuree depuis le 27 aout 2026**.

    Elle etait servie vide jusque-la, avec sa raison : un rapport a quatre
    sections chez l'un et cinq chez l'autre se lit comme une panne. Elle porte
    desormais trois lignes, dont deux volumes et un taux.

    Un volume rend zero sans etat d'ame ; le taux rend « Non mesuré » quand
    aucun courrier n'a ete cloture, jamais zero pour cent (ADR 011).
    """
    enregistres = mesures.courriers_enregistres(periode.debut, periode.fin, structures)
    taux, dans_le_delai, clos = mesures.courrier_dans_le_delai(
        periode.debut, periode.fin, structures
    )
    taux_avant, _, _ = mesures.courrier_dans_le_delai(precedente.debut, precedente.fin, structures)
    delai = mesures.delai_moyen_courrier(periode.debut, periode.fin, structures)

    return [
        _ligne(
            "Courriers enregistrés",
            str(enregistres),
            "courriers entrés au registre sur la période",
        ),
        _ligne(
            "Courriers clôturés",
            str(clos),
            (
                f"délai moyen de {delai} jour(s) entre l'arrivée et la clôture"
                if delai is not None
                else "aucune clôture sur la période"
            ),
        ),
        _ligne(
            "Courriers traités dans le délai",
            f"{taux} %" if taux is not None else "Non mesuré",
            (
                f"{dans_le_delai} sur {clos} courrier(s) clôturé(s)"
                if clos
                else mesures.SANS_COURRIER_CLOS
            ),
            feu_ligne=feu(taux),
            variation=mesures.variation(taux, taux_avant),
        ),
    ]


# =====================================================================
#  L'export
# =====================================================================

#: Le separateur. Le point-virgule et non la virgule : un tableur configure en
#: francais ouvre le premier en colonnes et le second en une seule colonne — et
#: l'agent qui recoit un fichier illisible conclut que l'export est casse.
SEPARATEUR = ";"


def csv_du_rapport(donnees: dict) -> str:
    """
    Le rapport en CSV, dans l'ordre exact de l'ecran.

    Ecrit a la main plutot qu'avec le module `csv` : il faut un en-tete de
    document (perimetre, periode, date d'edition) avant les colonnes, et
    `csv.writer` n'aurait servi qu'a echapper des champs dont on maitrise le
    contenu. L'echappement est fait ici, sur le seul caractere qui compte.

    Le fichier commence par un **BOM UTF-8**. Sans lui, Excel lit le fichier en
    ANSI et affiche « ActivitÃ©s » : le rapport parait faux alors qu'il est
    juste, et personne ne le rouvre.
    """
    # L'en-tete institutionnel ouvre le fichier, comme il ouvre le papier : un
    # rapport exporte circule hors de l'application, et rien d'autre ne dira
    # d'ou il vient. Voir `noyau/documents/entete.py`.
    lignes: list[str] = [_csv_ligne([fr, en]) for fr, en in documents.entete_lignes()]
    lignes += [
        "",
        _csv_ligne(["Rapport périodique", donnees["perimetreLibelle"]]),
        _csv_ligne(["Période", donnees["periode"]["libelle"]]),
        _csv_ligne(["Du", donnees["periode"]["debut"], "au", donnees["periode"]["fin"]]),
        _csv_ligne(["Comparaison", donnees["comparaison"]]),
        _csv_ligne(["Édité le", donnees["editeLe"], "par", donnees["editePar"]]),
        "",
        _csv_ligne(["Section", "Indicateur", "Valeur", "Évolution", "Précision"]),
    ]

    for section in donnees["sections"]:
        for ligne in section["lignes"]:
            lignes.append(
                _csv_ligne(
                    [
                        section["titre"],
                        ligne["libelle"],
                        ligne["valeur"],
                        ligne["variation"] or "",
                        ligne["note"],
                    ]
                )
            )

    # CRLF : c'est ce qu'attend la norme RFC 4180, et ce que les tableurs sous
    # Windows ouvrent sans poser de question.
    return "﻿" + "\r\n".join(lignes) + "\r\n"


def nom_du_fichier(donnees: dict) -> str:
    """« rapport-DSI-2026-T2.csv » — nommable, triable, sans espace."""
    perimetre = donnees["structureSigle"] or "institution"
    return f"rapport-{perimetre}-{donnees['periode']['code']}.csv"


def _csv_ligne(champs: list[str]) -> str:
    return SEPARATEUR.join(_champ(champ) for champ in champs)


def _champ(valeur: str) -> str:
    texte = str(valeur)
    if SEPARATEUR in texte or '"' in texte or "\n" in texte:
        return '"' + texte.replace('"', '""') + '"'
    return texte
