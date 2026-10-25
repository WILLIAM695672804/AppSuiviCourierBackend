"""
Les axes strategiques portent leurs accents.

Le script livre ecrit « Port competitif et fluide » ; le front ecrit « Port
compétitif et fluide », et c'est **ce libelle qui circule** comme clef d'axe
(`Activite.axe` est typee `LibelleAxe`, pas un code). Un accent de difference
suffisait a faire echouer tout rattachement a la creation.

Corriger la base plutot que le front, pour deux raisons :

 * la regle du projet distingue les **identifiants** — sans accent, pour ne
   dependre d'aucun encodage — de la **prose**, qui les porte. `libelle_court`
   et `libelle` sont de la prose affichee a l'agent, pas des identifiants ;
   `code` (`A1`, `A2`, `A3`) reste l'identifiant, et il ne change pas ;
 * le referentiel est ferme et communique par la Direction generale le 11 aout
   2026. C'est son ecriture qui fait foi, pas la transcription du script.

Les identifiants et les codes sont inchanges : aucune activite ne perd son axe.
"""

from django.db import migrations

LIBELLES = {
    "A1": (
        "Port attractif et performant",
        "Port attractif et performant à l'aide des services sûrs et de qualité",
    ),
    "A2": (
        "Port compétitif et fluide",
        "Port compétitif par la fluidité du passage portuaire à travers "
        "l'amélioration et la densification de l'outil de production",
    ),
    "A3": (
        "Port innovant et responsable",
        "Port innovant, digital et sociétalement responsable",
    ),
}

SANS_ACCENT = {
    "A1": (
        "Port attractif et performant",
        "Port attractif et performant a l'aide des services surs et de qualite",
    ),
    "A2": (
        "Port competitif et fluide",
        "Port competitif par la fluidite du passage portuaire a travers "
        "l'amelioration et la densification de l'outil de production",
    ),
    "A3": (
        "Port innovant et responsable",
        "Port innovant, digital et societalement responsable",
    ),
}


def _appliquer(apps, textes) -> None:
    AxeStrategique = apps.get_model("activite", "AxeStrategique")
    for code, (court, complet) in textes.items():
        AxeStrategique.objects.filter(code=code).update(libelle_court=court, libelle=complet)


def accentuer(apps, schema_editor) -> None:
    _appliquer(apps, LIBELLES)


def desaccentuer(apps, schema_editor) -> None:
    _appliquer(apps, SANS_ACCENT)


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0002_definition_retard"),
    ]

    operations = [
        migrations.RunPython(accentuer, desaccentuer),
    ]
