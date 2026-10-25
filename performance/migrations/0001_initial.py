"""
Le pilier performance entre au modele — §2 et §3.3.

**Quatre tables, et aucune ne stocke un score.** La matrice se recalcule a
chaque lecture (ADR 010) : stocker le resultat d'un agregat aurait cree une
seconde verite, et une activite corrigee apres coup aurait laisse un score faux
jusqu'au prochain calcul.

Le semis pose les **trois criteres du §2** et les quatre indicateurs qui les
alimentent. Les indicateurs semes decrivent le calcul reellement mis en oeuvre :
ils ne sont pas un voeu, ils sont la documentation de ce que le code fait, et
c'est ce qui permet a un directeur de contester un chiffre.

Ce qui n'est **pas** seme : la grille de cotation des risques. Le §3.3 la
mentionne, aucun document ne la definit, et une grille inventee serait appliquee
telle quelle. Voir A26.

Cette migration est ecrite a la main, comme les precedentes du depot.
"""

import django.db.models.deletion
from django.db import migrations, models

#: Les trois axes cites par le §2 : « les resultats lies a l'execution des
#: activites, au traitement du courrier et des dossiers, ainsi qu'a la
#: conformite aux rituels ».
#:
#: Trois et non quatre : le commentaire du contrat front en annonce quatre sans
#: dire lequel serait le dernier. On s'en tient au texte. Voir A26.
CRITERES = [
    (
        "ACT",
        "Exécution des activités",
        34,
        1,
        "Ce que la structure a inscrit à son plan d'actions annuel et ce qu'elle en a fait.",
    ),
    (
        "COUR",
        "Traitement du courrier et des dossiers",
        33,
        2,
        "Les délais tenus sur les courriers cotés à la structure et les dossiers instruits.",
    ),
    (
        "RIT",
        "Conformité aux rituels",
        33,
        3,
        "Les productions attendues au calendrier officiel, déposées à l'échéance.",
    ),
]

#: Les indicateurs qui alimentent la matrice, avec la formule **reellement**
#: appliquee par `performance/matrice.py`. Un dictionnaire qui decrirait autre
#: chose que le calcul serait pire que pas de dictionnaire du tout.
INDICATEURS = [
    (
        "ACT-HEURE",
        "Activités menées à l'heure",
        "Part des activités du plan en cours qui ne sont pas en retard à la fin du mois observé.",
        "activités non en retard ÷ activités du plan × 100",
        "Pilier activités — vue v_activite_etat",
        "DSR — contrôle de gestion",
        "%",
        "ACT",
    ),
    (
        "ACT-AVANCE",
        "Avancement moyen du plan d'actions",
        (
            "Moyenne des avancements calculés des activités de la structure. "
            "L'avancement d'une activité est recalculé par déclencheur depuis ses tâches, "
            "pondéré par leur poids."
        ),
        "moyenne(avancement_calculé) des activités du plan",
        "Pilier activités — table activite",
        "DSR — contrôle de gestion",
        "%",
        "ACT",
    ),
    (
        "COUR-DELAI",
        "Courriers traités dans le délai",
        (
            "Part des courriers cotés à la structure dont le traitement s'est achevé avant "
            "l'échéance portée par leur nature."
        ),
        "courriers traités avant échéance ÷ courriers cotés × 100",
        "Pilier courrier — non disponible à ce jour",
        "Courrier central",
        "%",
        "COUR",
    ),
    (
        "RIT-DEPOT",
        "Productions déposées à l'échéance",
        (
            "Part des obligations du calendrier officiel déposées au plus tard le jour de "
            "leur échéance. Une obligation non déposée compte pour zéro, jamais comme absente."
        ),
        "obligations déposées à temps ÷ obligations dues × 100",
        "Pilier activités — table obligation",
        "DSR",
        "%",
        "RIT",
    ),
]


def semer(apps, schema_editor):
    """Pose les criteres et les indicateurs. Idempotent : `get_or_create`."""
    Critere = apps.get_model("performance", "Critere")
    Indicateur = apps.get_model("performance", "Indicateur")

    criteres = {}
    for code, libelle, poids, ordre, description in CRITERES:
        critere, _ = Critere.objects.get_or_create(
            code=code,
            defaults={
                "libelle": libelle,
                "poids": poids,
                "ordre": ordre,
                "description": description,
            },
        )
        criteres[code] = critere

    for (
        code,
        libelle,
        definition,
        formule,
        source,
        responsable,
        unite,
        critere_code,
    ) in INDICATEURS:
        Indicateur.objects.get_or_create(
            code=code,
            defaults={
                "libelle": libelle,
                "definition": definition,
                "formule": formule,
                "source": source,
                "periodicite": "mensuelle",
                "responsable": responsable,
                "unite": unite,
                "critere": criteres[critere_code],
            },
        )


def rien_a_defaire(apps, schema_editor):
    """
    Le retour arriere supprime les tables : vider leur contenu d'abord serait
    du travail perdu. Et un critere dont la DSR aurait corrige le poids ne doit
    pas disparaitre parce qu'on defait une migration.
    """


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("noyau", "0005_parametrage_metier"),
    ]

    operations = [
        migrations.CreateModel(
            name="Critere",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.TextField(unique=True)),
                ("libelle", models.TextField()),
                ("poids", models.SmallIntegerField()),
                ("ordre", models.SmallIntegerField(default=0)),
                ("description", models.TextField(blank=True, null=True)),
                ("actif", models.BooleanField(default=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                ("modifie_le", models.DateTimeField(blank=True, null=True)),
                ("modifie_par", models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "critere de la matrice",
                "verbose_name_plural": "criteres de la matrice",
                "db_table": "critere_matrice",
                "ordering": ["ordre", "code"],
            },
        ),
        migrations.CreateModel(
            name="NiveauRisque",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("niveau", models.SmallIntegerField(unique=True)),
                ("libelle", models.TextField()),
                ("description", models.TextField()),
                ("conduite", models.TextField()),
                ("feu", models.TextField(default="orange")),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "niveau de risque",
                "verbose_name_plural": "grille de cotation des risques",
                "db_table": "niveau_risque",
                "ordering": ["niveau"],
            },
        ),
        migrations.CreateModel(
            name="Indicateur",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.TextField(unique=True)),
                ("libelle", models.TextField()),
                ("definition", models.TextField()),
                ("formule", models.TextField()),
                ("source", models.TextField()),
                (
                    "periodicite",
                    models.TextField(
                        choices=[
                            ("mensuelle", "Mensuelle"),
                            ("trimestrielle", "Trimestrielle"),
                            ("semestrielle", "Semestrielle"),
                            ("annuelle", "Annuelle"),
                        ],
                        default="mensuelle",
                    ),
                ),
                ("responsable", models.TextField()),
                ("unite", models.TextField(default="%")),
                ("seuil_vert", models.SmallIntegerField(default=85)),
                ("seuil_orange", models.SmallIntegerField(default=60)),
                ("actif", models.BooleanField(default=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                ("modifie_le", models.DateTimeField(blank=True, null=True)),
                ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                (
                    "critere",
                    models.ForeignKey(
                        blank=True,
                        db_column="critere_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="indicateurs",
                        to="performance.critere",
                    ),
                ),
            ],
            options={
                "verbose_name": "indicateur du dictionnaire",
                "verbose_name_plural": "dictionnaire des indicateurs",
                "db_table": "indicateur_dictionnaire",
                "ordering": ["code"],
            },
        ),
        migrations.CreateModel(
            name="RelanceProduction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("calendrier_production_id", models.BigIntegerField()),
                ("periode_libelle", models.TextField()),
                ("echeance", models.DateField()),
                ("envoyee_le", models.DateTimeField(auto_now_add=True)),
                ("canal", models.TextField(default="notification")),
                (
                    "structure",
                    models.ForeignKey(
                        db_column="structure_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        to="noyau.structure",
                    ),
                ),
            ],
            options={
                "verbose_name": "relance de production",
                "verbose_name_plural": "relances de production",
                "db_table": "relance_production",
                "ordering": ["-envoyee_le"],
            },
        ),
        migrations.RunPython(semer, rien_a_defaire),
    ]
