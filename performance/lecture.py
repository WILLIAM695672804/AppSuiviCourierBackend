"""
Le dictionnaire et le calendrier — §3.3.

Deux restitutions qui n'ont pas la meme nature et qu'il ne faut pas confondre :

 * le **dictionnaire** dit comment on mesure. Il ne mesure rien lui-meme ;
 * le **calendrier** dit qui depose quoi, et **ce qui est arrive** au dernier
   cycle clos. Lui, il mesure.

Le second est le contrat de service entre la DSR et les structures : sans lui,
la matrice se calcule sur des donnees incompletes et ne vaut rien.
"""

from collections import defaultdict

from django.db import connection

from activite.modeles import CalendrierProduction
from noyau.feu import feu
from performance.modeles import Critere, Indicateur, NiveauRisque

PERIODICITES = {
    "mensuelle": "Mensuelle",
    "trimestrielle": "Trimestrielle",
    "semestrielle": "Semestrielle",
    "annuelle": "Annuelle",
}

#: L'echeance, formulee comme on la dit a l'oral. Le front l'affiche telle
#: quelle : lui envoyer `jour_echeance = 5` l'aurait oblige a reconstruire la
#: phrase, et deux ecrans auraient fini par la formuler differemment.
ECHEANCES = {
    "mensuelle": "le {jour} du mois suivant",
    "trimestrielle": "le {jour} du mois suivant la fin du trimestre",
    "semestrielle": "le {jour} du mois suivant la fin du semestre",
    "annuelle": "le {jour} janvier de l'année suivante",
}


# =====================================================================
#  Dictionnaire
# =====================================================================


def dictionnaire() -> dict:
    """
    Definition, formule, source, periodicite, responsable — §3.3.

    Ces cinq champs sont ce qui empeche deux directions de calculer le meme
    indicateur de deux facons. La formule est rendue **en clair**, telle
    qu'elle est saisie : c'est un texte lisible, pas une expression evaluee.
    Voir `performance/modeles.py::Indicateur`.
    """
    return {
        # Les criteres partent avec le dictionnaire : le formulaire de creation
        # doit offrir les axes **existants**, et une liste ecrite dans le front
        # se serait desynchronisee au premier critere ajoute par la DSR — la
        # saisie serait alors refusee sans que l'agent comprenne pourquoi.
        "criteres": [
            {"code": critere.code, "libelle": critere.libelle, "poids": critere.poids}
            for critere in Critere.objects.filter(actif=True)
        ],
        "indicateurs": [
            {
                "id": indicateur.pk,
                "code": indicateur.code,
                "libelle": indicateur.libelle,
                "definition": indicateur.definition,
                "formule": indicateur.formule,
                "source": indicateur.source,
                "periodicite": PERIODICITES.get(indicateur.periodicite, "Mensuelle"),
                "responsable": indicateur.responsable,
                "unite": indicateur.unite,
                "seuilVert": indicateur.seuil_vert,
                "seuilOrange": indicateur.seuil_orange,
                "critere": indicateur.critere.libelle if indicateur.critere else None,
                "actif": indicateur.actif,
            }
            for indicateur in Indicateur.objects.select_related("critere")
        ],
        "risques": [
            {
                "niveau": risque.niveau,
                "libelle": risque.libelle,
                "description": risque.description,
                "conduite": risque.conduite,
                "feu": risque.feu,
            }
            for risque in NiveauRisque.objects.all()
        ],
    }


# =====================================================================
#  Calendrier officiel de production
# =====================================================================


def calendrier() -> dict:
    """
    Qui alimente quoi, a quelle frequence, et ce qui est effectivement arrive.

    **Les lignes sont regroupees.** La table `calendrier_production` porte une
    ligne par structure et par production ; l'ecran, lui, presente une ligne par
    **production** avec le nombre de structures attendues. Sans ce regroupement,
    quinze directions produisant le meme rapport mensuel feraient quinze lignes
    identiques ou personne ne verrait qu'il en manque une.

    `recus` porte sur le **dernier cycle clos** et non sur le cycle en cours :
    une production due le 5 du mois prochain n'est pas en retard aujourd'hui, et
    la compter manquante donnerait un tableau rouge tous les mois.
    """
    groupes: dict[tuple, list[CalendrierProduction]] = defaultdict(list)
    for ligne in CalendrierProduction.objects.filter(
        actif=True, valide_au__isnull=True
    ).select_related("structure"):
        groupes[(ligne.intitule, ligne.nature, ligne.periodicite, ligne.jour_echeance)].append(
            ligne
        )

    resultats = _depots_du_dernier_cycle()

    lignes = []
    for (intitule, _nature, periodicite, jour), membres in groupes.items():
        # **Les lignes sans cycle clos ne comptent pas au denominateur.** Une
        # production inscrite la semaine derniere n'a encore rien a rendre ;
        # l'attendre aurait affiche un rouge le jour meme de sa creation.
        mesurees = [membre for membre in membres if membre.pk in resultats]
        attendues = len(membres)
        recus = sum(resultats[membre.pk] for membre in mesurees)
        # Le taux se calcule sur les structures **mesurees**, jamais sur celles
        # qui ont depose : une structure qui ne depose rien doit faire baisser
        # le taux, pas disparaitre du denominateur.
        taux = round(recus / len(mesurees) * 100, 1) if mesurees else None
        premiere = membres[0]

        lignes.append(
            {
                "id": premiere.pk,
                "production": intitule,
                "nature": premiere.get_nature_display(),
                "periodicite": PERIODICITES.get(periodicite, "Mensuelle"),
                "echeance": ECHEANCES.get(periodicite, "le {jour}").format(jour=jour),
                "structuresAttendues": attendues,
                "responsable": _responsable(membres),
                "relanceAutomatique": premiere.relance_automatique,
                "joursAvantRelance": premiere.jours_avant_relance,
                "recus": recus,
                "feu": feu(taux),
            }
        )

    lignes.sort(key=lambda ligne: ligne["production"])
    return {"lignes": lignes, "compteurs": _compteurs_calendrier(lignes)}


def _responsable(membres: list[CalendrierProduction]) -> str:
    """
    Qui repond de la production.

    Une seule structure : elle-meme. Plusieurs : la DSR, qui pilote le
    calendrier officiel — c'est elle qui relance, et c'est donc elle que la
    ligne designe. Nommer quinze directions dans une cellule n'aurait informe
    personne.
    """
    if len(membres) == 1:
        return membres[0].structure.code
    return "DSR"


def _depots_du_dernier_cycle() -> dict[int, int]:
    """
    Combien de depots par ligne de calendrier, sur le dernier cycle **clos**.

    Le cycle clos est celui dont l'echeance est passee : on retient la derniere
    echeance echue de chaque ligne, et on compte ce qui a ete depose pour elle.

    Une seule requete, avec `DISTINCT ON` — c'est la construction PostgreSQL qui
    dit exactement cela, « la premiere ligne de chaque groupe une fois trie ».
    La boucle equivalente en Python aurait fait une requete par ligne de
    calendrier, et le calendrier d'une institution en compte autant que de
    directions multipliees par ses productions.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT DISTINCT ON (calendrier_production_id)
                   calendrier_production_id,
                   count(*) FILTER (WHERE depose_le IS NOT NULL) OVER (
                       PARTITION BY calendrier_production_id, echeance
                   )
            FROM obligation
            WHERE echeance < current_date
            ORDER BY calendrier_production_id, echeance DESC
            """
        )
        return dict(curseur.fetchall())


def _compteurs_calendrier(lignes: list[dict]) -> list[dict]:
    """
    Trois chiffres de tete.

    Le troisieme est celui que la DSR vient chercher : combien de productions
    ne relancent personne. Une echeance sans relance est une echeance qui ne
    sera pas tenue, et c'est le §3.3 qui le dit.
    """
    # Les lignes sans cycle clos — feu « inconnu » — sortent du calcul du taux :
    # les compter attendues aurait fait baisser le taux global a chaque
    # production nouvellement inscrite, ce qui aurait dissuade d'en inscrire.
    mesurees = [ligne for ligne in lignes if ligne["feu"] != "inconnu"]
    attendues = sum(ligne["structuresAttendues"] for ligne in mesurees)
    recus = sum(ligne["recus"] for ligne in mesurees)
    sans_relance = sum(1 for ligne in lignes if not ligne["relanceAutomatique"])
    taux = round(recus / attendues * 100, 1) if attendues else None

    return [
        {
            "libelle": "Productions au calendrier",
            "valeur": len(lignes),
            "note": "Lignes actives du calendrier officiel",
            "feu": "inconnu" if not lignes else "vert",
        },
        {
            "libelle": "Taux de dépôt",
            "valeur": taux or 0,
            "note": (
                "Aucun cycle clos à ce jour"
                if taux is None
                else f"{recus} dépôts sur {attendues} attendus au dernier cycle clos"
            ),
            "feu": feu(taux),
        },
        {
            "libelle": "Sans relance automatique",
            "valeur": sans_relance,
            "note": (
                "Toutes les productions relancent"
                if not sans_relance
                else "Une échéance sans relance ne sera pas tenue — §3.3"
            ),
            "feu": "vert" if not sans_relance else "orange",
        },
    ]
