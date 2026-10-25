"""
Les indicateurs cibles du programme entrent au modele — §3.11, §9 du BRD.

Le semis pose les quatre indicateurs **que l'application sait rapporter**, avec
la description du calcul reellement mis en oeuvre. Il ne pose **aucune cible** :
les valeurs cibles du programme n'ont pas ete communiquees, et une cible
inventee aurait ete lue comme un engagement de l'institution. L'ecran affiche
alors « cible non fixée », ce qui se corrige par l'administration. Voir A32.

Le quatrieme indicateur est volontairement non mesurable : le courrier figure au
programme et l'ecran doit le montrer « non mesuré » plutot que l'omettre. Une
liste ou l'indicateur manquant a disparu se lit comme une liste complete.
"""

import django.db.models.deletion
from django.db import migrations, models

#: (code, libelle, mode de calcul, source, unite, cible maximum, echeance, ordre)
INDICATEURS = [
    (
        "PROG-ACT",
        "Taux d'exécution des activités du plan",
        "Moyenne des avancements calculés des activités commencées, tous plans confondus.",
        "Pilier activités — table activite",
        "%",
        False,
        "fin d'exercice",
        1,
    ),
    (
        "PROG-RIT",
        "Productions déposées à l'échéance",
        "Obligations échues déposées au plus tard le jour de leur échéance ÷ obligations échues.",
        "Pilier activités — table obligation",
        "%",
        False,
        "fin d'exercice",
        2,
    ),
    (
        "PROG-DEC",
        "Décisions d'instance exécutées dans l'année",
        "Nombre d'engagements dont la date d'exécution tombe dans l'exercice.",
        "Pilier gouvernance — table engagement",
        "décisions",
        False,
        "fin d'exercice",
        3,
    ),
    (
        "PROG-COUR",
        "Courriers traités dans le délai",
        "Courriers clos avant l'échéance portée par leur nature ÷ courriers enregistrés.",
        "Pilier courrier — non disponible à ce jour",
        "%",
        False,
        "fin d'exercice",
        4,
    ),
]


def semer(apps, schema_editor):
    """Pose les indicateurs, sans cible. Idempotent : `get_or_create`."""
    IndicateurProgramme = apps.get_model("pilotage", "IndicateurProgramme")

    for code, libelle, mode, source, unite, maximum, echeance, ordre in INDICATEURS:
        IndicateurProgramme.objects.get_or_create(
            code=code,
            defaults={
                "libelle": libelle,
                "mode_calcul": mode,
                "source": source,
                "unite": unite,
                "cible": None,
                "cible_maximum": maximum,
                "echeance": echeance,
                "ordre": ordre,
            },
        )


def rien_a_defaire(apps, schema_editor):
    """
    Le retour arriere supprime les tables. Et une cible que la Direction
    generale aurait fixee ne doit pas disparaitre parce qu'on defait une
    migration.
    """


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='IndicateurProgramme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.TextField(unique=True)),
                ('libelle', models.TextField()),
                ('mode_calcul', models.TextField()),
                ('source', models.TextField()),
                ('unite', models.TextField(default='%')),
                ('cible', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('cible_maximum', models.BooleanField(default=False)),
                ('echeance', models.TextField(default="fin d'exercice")),
                ('ordre', models.SmallIntegerField(default=0)),
                ('actif', models.BooleanField(default=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('cree_par', models.BigIntegerField(blank=True, null=True)),
                ('modifie_le', models.DateTimeField(blank=True, null=True)),
                ('modifie_par', models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'indicateur cible du programme',
                'verbose_name_plural': 'indicateurs cibles du programme',
                'db_table': 'indicateur_programme',
                'ordering': ['ordre', 'code'],
            },
        ),
        migrations.CreateModel(
            name='MesureProgramme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('annee', models.SmallIntegerField()),
                ('valeur', models.DecimalField(decimal_places=2, max_digits=12)),
                ('commentaire', models.TextField(blank=True, null=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('cree_par', models.BigIntegerField(blank=True, null=True)),
                ('indicateur', models.ForeignKey(db_column='indicateur_programme_id', on_delete=django.db.models.deletion.PROTECT, related_name='mesures', to='pilotage.indicateurprogramme')),
            ],
            options={
                'verbose_name': "mesure d'un indicateur du programme",
                'verbose_name_plural': 'mesures des indicateurs du programme',
                'db_table': 'mesure_programme',
                'ordering': ['-annee'],
                'constraints': [models.UniqueConstraint(fields=('indicateur', 'annee'), name='unicite_mesure_programme_annee')],
            },
        ),
        migrations.RunPython(semer, rien_a_defaire),
    ]
