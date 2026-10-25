"""
De quoi accueillir l'organigramme reel du Port — F-01, F-02.

La planche A3 « Organigramme du PAD Propose », dressee par la Direction
generale le 10 novembre 2025, a ete communiquee. C'est le document que les
decisions de cadrage classaient parmi les trois reellement bloquants : « sans
lui, les perimetres restent theoriques ». Le jeu d'essai de `semer.py` disait
lui-meme qu'il tenait lieu d'approximation en attendant.

La transcription a bute sur deux limites du socle, et cette migration les leve.
Elle n'ecrit aucune structure : le chargement est un geste d'exploitation, pas
une migration — voir [ADR 025](../docs/architecture/025-l-organigramme-reel-se-charge-il-ne-se-migre-pas.md).

**Les natures.** Cinq valeurs etaient admises ; la planche en dessine douze.
Une cellule n'est pas une division, un departement n'est pas un service, et le
Conseil d'administration n'est ni l'un ni l'autre.

**Les rangs.** La legende de la planche nomme quatre rangs de responsable —
directeur, directeur adjoint, sous-directeur, chef de service. Le socle avait
seme DG, DIR, DEP, SERV : le directeur adjoint et le sous-directeur manquaient,
c'est-a-dire precisement les deux etages qui dirigent les divisions internes,
les departements et les cellules. Sans eux, les deux tiers de l'organigramme
n'avaient pas d'etage ou se poser.

`RunSQL` et non `RunPython` : les niveaux et les contraintes sont des donnees de
reference, semees en SQL depuis `0001_socle.sql`, et le fichier voisin dit
pourquoi mieux qu'un script Python ne le ferait.

`reverse_sql` en `noop` : retirer un rang que des structures occupent deja
casserait leur cle etrangere. Revenir en arriere se decide, se prepare, et
s'ecrit dans une migration a soi — ce n'est pas un `migrate 0016`.
"""

from pathlib import Path

from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0016_parametre_annexe"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0017_organigramme_reel.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Django ne pose aucune contrainte a partir de `choices` : la garde
        # reelle est le CHECK ci-dessus. Cette operation ne touche pas la base,
        # elle accorde l'etat de l'ORM au schema — sans quoi le prochain
        # `makemigrations` proposerait de le refaire, et le prochain
        # formulaire d'administration refuserait « Cellule ».
        migrations.AlterField(
            model_name="structure",
            name="nature",
            field=models.TextField(
                choices=[
                    ("Direction", "Direction"),
                    ("Division", "Division"),
                    ("Departement", "Departement"),
                    ("Service", "Service"),
                    ("Cellule", "Cellule"),
                    ("Centre", "Centre"),
                    ("Cabinet", "Cabinet"),
                    ("Secteur", "Secteur"),
                    ("Representation", "Representation"),
                    ("Filiale", "Filiale"),
                    ("Succursale", "Succursale"),
                    ("Organe", "Organe"),
                ],
                default="Direction",
            ),
        ),
    ]
