"""
Le fonds : regles de conservation et versements — RF-GED-06, RF-GED-09,
RF-ADM-05.

Deux gestes distincts, et la demonstration doit montrer qu'ils le sont : celui
qui **saisit** une regle de conservation ne la rend pas applicable ; c'est le
service des archives qui la **vise**. Une regle sans visa bloque le versement,
et c'est voulu — verser un dossier dont aucune regle visee ne dit la duree de
conservation reviendrait a le perdre proprement.

D'ou une regle laissee **sans visa** dans ce jeu : sans elle, l'anomalie
bloquante n'apparaitrait sur aucun ecran, et rien ne prouverait que le visa
sert a quelque chose.

Une autre regle attend des pieces que les dossiers ne portent pas — le
televersement reel est celui de `POST /api/pieces` (ADR 017), et le semis ne
fabrique pas de faux fichiers. L'anomalie qui en resulte n'est **pas**
bloquante : elle se passe outre avec une observation, et c'est cette phrase que
l'archiviste tiendra devant un auditeur.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection

from archivage import services
from archivage.modeles import RegleConservation, Versement
from dossier.modeles import Dossier
from noyau.erreurs import ErreurMetier
from noyau.identite.modeles import Utilisateur

#: Les regles de conservation : (typologie, description, DUA en annees, sort
#: final, fondement juridique, pieces attendues, visee).
#:
#: La typologie reprend **exactement** le libelle du type de dossier : c'est par
#: lui que `verser` retrouve la regle, et un libelle approchant n'aurait
#: rattache aucune regle a aucun dossier.
REGLES = [
    (
        "Réclamation",
        "Réclamations d'usagers et pièces de l'instruction contradictoire.",
        5,
        "Destruction",
        "Instruction générale sur les archives administratives, art. 12.",
        0,
        True,
    ),
    (
        "Demande",
        "Demandes d'information, de document ou de prestation.",
        3,
        "Destruction",
        "Instruction générale sur les archives administratives, art. 9.",
        0,
        True,
    ),
    (
        "Autorisation",
        "Autorisations d'occupation, de travaux et d'accès au domaine portuaire.",
        10,
        "Conservation définitive",
        "Code du domaine public maritime, art. 47 — pièces du domaine concédé.",
        0,
        True,
    ),
    (
        "Acte",
        "Conventions, avenants et actes engageant l'établissement.",
        30,
        "Conservation définitive",
        "Loi portant régime des archives, art. 5 — actes constitutifs.",
        2,
        True,
    ),
    (
        # Volontairement **non visee** : c'est elle qui montre l'anomalie
        # bloquante, et le versement d'une requête reste impossible tant que le
        # service des archives ne s'est pas prononce (RF-ADM-05).
        "Requête",
        "Requêtes en révision d'une décision de l'établissement.",
        5,
        "Tri",
        "Instruction générale sur les archives administratives, art. 15.",
        0,
        False,
    ),
]

#: L'observation portee quand on verse malgre une anomalie non bloquante. Le
#: service l'exige — verser malgre une anomalie suppose de dire laquelle.
OBSERVATION = (
    "Versé sans les pièces attendues : les originaux papier sont conservés au "
    "service émetteur et seront numérisés lors de la campagne de reprise."
)


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose les regles, les vise, puis verse les dossiers clos."""
    if Versement.objects.exists():
        ecrire(f"  {Versement.objects.count()} versements deja en base — passe")
        return 0

    archiviste = annuaire["archiviste"]
    _regles(archiviste, annuaire, ecrire)
    return _verser(archiviste, ecrire)


def _regles(archiviste: Utilisateur, annuaire: dict, ecrire) -> None:
    """
    Le referentiel des durees. La table n'est pas videe par la remise a zero :
    c'est un referentiel, et le semis passe son tour si elle est deja garnie.

    **Le visa n'est pas donne par qui saisit** : la regle est ecrite par
    l'administratrice fonctionnelle, visee par l'archiviste. Les faire
    coincider aurait efface la separation que RF-ADM-05 impose.
    """
    saisie_par = annuaire.get("admin", archiviste)
    posees = 0

    for typologie, description, dua, sort, fondement, pieces, visee in REGLES:
        if RegleConservation.objects.filter(typologie=typologie).exists():
            continue
        regle = services.creer_regle(
            saisie_par,
            typologie=typologie,
            description=description,
            dua=dua,
            sort_final=sort,
            fondement_juridique=fondement,
            pieces_attendues=pieces,
        )
        if visee:
            services.viser_regle(archiviste, regle_id=regle.pk)
        posees += 1

    if posees:
        ecrire(f"  {posees} regles de conservation, une laissee sans visa")
    else:
        ecrire("  referentiel de conservation deja en place — conserve")


def _verser(archiviste: Utilisateur, ecrire) -> int:
    """
    Verse les dossiers clos que le referentiel permet de verser.

    Les autres restent dans la file « à verser », avec leur anomalie affichee.
    C'est l'etat normal d'un fonds : la file n'est jamais vide, et ce qu'elle
    contient dit ce qui manque au referentiel.
    """
    verses = 0
    refuses = 0

    for dossier in Dossier.objects.filter(
        etape="clos", clos_le__isnull=False, invalide_le__isnull=True
    ).order_by("clos_le"):
        try:
            versement = services.verser(
                archiviste,
                dossier_id=dossier.pk,
                observation=OBSERVATION,
                anomalies_acceptees=True,
            )
        except ErreurMetier:
            # L'anomalie bloquante — regle absente ou non visee. Le dossier
            # reste dans la file, ce qui est exactement ce que l'ecran doit
            # montrer. On ne force rien : forcer reviendrait a verser sans
            # savoir combien de temps on garde.
            refuses += 1
            continue
        assert dossier.clos_le is not None
        _retrodater(versement, dossier.clos_le)
        verses += 1

    ecrire(f"  {verses} dossiers verses, {refuses} bloques par une anomalie")
    return verses


def _retrodater(versement: Versement, clos_le: date) -> None:
    """
    Date le versement de quelques jours apres la cloture du dossier.

    Un fonds ou tout aurait ete verse le meme jour ne montre aucun delai de
    versement — or c'est precisement ce delai que le §3.12 suit.
    """
    from noyau.demonstration.courriers import _horodatage

    jour = min(clos_le + timedelta(days=6), date.today() - timedelta(days=1))
    horodatage = _horodatage(jour)
    with connection.cursor() as curseur:
        curseur.execute(
            "UPDATE versement SET verse_le = %s, cree_le = %s WHERE id = %s",
            [horodatage, horodatage, versement.pk],
        )
        curseur.execute(
            "UPDATE maillon_integrite SET horodatage = %s WHERE versement_id = %s",
            [horodatage, versement.pk],
        )
        curseur.execute(
            """
            UPDATE evenement SET survenu_le = %s
             WHERE objet_type = 'versement' AND objet_id = %s
            """,
            [horodatage, versement.pk],
        )
