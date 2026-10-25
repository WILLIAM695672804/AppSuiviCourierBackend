"""
Les mesures rapportees du programme — §3.11.

Le tableau du programme lit deux origines, dans cet ordre : la mesure
**rapportee** si elle existe, la mesure **calculee** sinon. Le semis ne rapporte
donc que ce que l'application ne peut pas calculer elle-meme :

  * l'**exercice precedent**, que rien ne calcule — la base ne contient pas
    l'annee 2025, et sans ces quatre lignes la colonne « N-1 » serait vide et
    la comparaison que le §3.11 demande, impossible ;
  * rien pour l'exercice en cours : les trois indicateurs calculables se
    calculent sur les courriers, les activites et les decisions que ce meme
    semis vient de poser. Les rapporter aurait masque le calcul, donc masque
    toute erreur du calcul.

`PROG-COUR` reste **non mesuré** pour l'exercice en cours, et c'est voulu :
l'application ne sait pas le calculer et personne ne l'a rapporte. C'est la
distinction que le §3.11 demande de tenir — « nous ne savons pas où nous en
sommes » n'est pas « zéro ».
"""

from __future__ import annotations

from datetime import date

from noyau.identite.modeles import Utilisateur
from pilotage.modeles import IndicateurProgramme, MesureProgramme

#: Les valeurs de l'exercice precedent : (code de l'indicateur, valeur,
#: commentaire du rapporteur).
#:
#: Elles sont **rapportees**, c'est-a-dire signees : c'est le rapporteur qui
#: engage sa signature devant l'instance, pas le serveur.
MESURES_N1 = [
    (
        "PROG-ACT",
        62.5,
        "Taux arrêté au 31 décembre, hors activités reportées sur l'exercice suivant.",
    ),
    (
        "PROG-RIT",
        71.0,
        "Productions déposées à l'échéance, toutes structures classées confondues.",
    ),
    (
        "PROG-DEC",
        18.0,
        "Décisions du CODIR et du Conseil d'administration exécutées dans l'année.",
    ),
    (
        "PROG-COUR",
        58.0,
        "Mesure établie manuellement sur le registre papier, avant la plateforme.",
    ),
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose les mesures rapportees de l'exercice precedent."""
    annee = date.today().year - 1
    if MesureProgramme.objects.filter(annee=annee).exists():
        ecrire(f"  mesures {annee} deja rapportees — passe")
        return 0

    indicateurs = {i.code: i for i in IndicateurProgramme.objects.all()}
    dsr = annuaire["dsr"]
    posees = 0

    for code, valeur, commentaire in MESURES_N1:
        indicateur = indicateurs.get(code)
        if indicateur is None:
            continue
        MesureProgramme.objects.create(
            indicateur=indicateur,
            annee=annee,
            valeur=valeur,
            commentaire=commentaire,
            cree_par=dsr.pk,
        )
        posees += 1

    ecrire(f"  {posees} mesures rapportees pour {annee}")
    return posees
