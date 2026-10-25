"""
Le parametrage metier entre au modele — H-01 a H-06.

**Deux moities, et elles n'ont pas le meme statut.**

La premiere enregistre l'etat de huit tables **qui existent depuis le socle** et
qu'aucun modele ne couvrait : `nature`, `mention_type`, `priorite`,
`correspondant`, `circuit`, `circuit_version`, `circuit_etape`,
`circuit_regle`. Elles appartiennent au pilier courrier, qui n'est pas commence.
Rien n'est cree en base ici — `SeparateDatabaseAndState`, exactement comme pour
le socle.

La seconde cree deux tables neuves, `rubrique_classement` (RF-GED-07) et
`seuil_alerte` (RF-BI-05, RF-ADM-04), et celles-la, **Django les cree
reellement** : elles n'ont aucune construction que l'ORM ne sache exprimer, et
l'ADR 003 dit qu'a partir de 0002 Django reprend la main. Ecrire leur SQL a la
main aurait ajoute un second endroit ou les chercher.

**Aucune des dix tables n'est peuplee ici.** Un plan de classement invente
serait recopie tel quel par la premiere direction qui l'ouvrirait ; il n'a
aucune source dans les documents de cadrage. Les onglets sortiront vides, ce
qui est l'etat vrai. Voir A24.

Cette migration est ecrite a la main, comme les precedentes.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0004_parametres_tracabilite"),
    ]

    operations = [
        # -------------------------------------------------------------
        #  1. Les huit tables du socle : etat seul, aucune creation.
        # -------------------------------------------------------------
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Nature",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("code", models.TextField(unique=True)),
                        ("libelle", models.TextField()),
                        ("delai_defaut_jours", models.SmallIntegerField(blank=True, null=True)),
                        ("actif", models.BooleanField(default=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("modifie_le", models.DateTimeField(blank=True, null=True)),
                        ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={"db_table": "nature", "ordering": ["libelle"]},
                ),
                migrations.CreateModel(
                    name="MentionType",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("code", models.TextField(unique=True)),
                        ("libelle", models.TextField()),
                        ("ordre", models.SmallIntegerField(default=0)),
                        ("actif", models.BooleanField(default=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("modifie_le", models.DateTimeField(blank=True, null=True)),
                        ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={"db_table": "mention_type", "ordering": ["ordre", "libelle"]},
                ),
                migrations.CreateModel(
                    name="Priorite",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("code", models.TextField(unique=True)),
                        ("libelle", models.TextField()),
                        ("rang", models.SmallIntegerField()),
                        ("couleur", models.TextField(blank=True, null=True)),
                        ("actif", models.BooleanField(default=True)),
                    ],
                    options={"db_table": "priorite", "ordering": ["rang"]},
                ),
                migrations.CreateModel(
                    name="Correspondant",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "type",
                            models.TextField(
                                choices=[
                                    ("externe", "Externe"),
                                    ("interne", "Interne"),
                                    ("usager", "Usager"),
                                    ("administration", "Administration"),
                                ]
                            ),
                        ),
                        ("raison_sociale", models.TextField(blank=True, null=True)),
                        ("nom", models.TextField(blank=True, null=True)),
                        ("prenom", models.TextField(blank=True, null=True)),
                        ("adresse", models.TextField(blank=True, null=True)),
                        ("ville", models.TextField(blank=True, null=True)),
                        ("courriel", models.TextField(blank=True, null=True)),
                        ("telephone", models.TextField(blank=True, null=True)),
                        ("actif", models.BooleanField(default=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("modifie_le", models.DateTimeField(blank=True, null=True)),
                        ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "structure",
                            models.ForeignKey(
                                blank=True,
                                db_column="structure_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.structure",
                            ),
                        ),
                    ],
                    options={"db_table": "correspondant", "ordering": ["raison_sociale", "nom"]},
                ),
                migrations.CreateModel(
                    name="Circuit",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("code", models.TextField(unique=True)),
                        ("libelle", models.TextField()),
                        ("actif", models.BooleanField(default=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("modifie_le", models.DateTimeField(blank=True, null=True)),
                        ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={"db_table": "circuit", "ordering": ["libelle"]},
                ),
                migrations.CreateModel(
                    name="CircuitVersion",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("version", models.SmallIntegerField()),
                        (
                            "mode_cotation",
                            models.TextField(
                                choices=[("directe", "Directe"), ("cascade", "Cascade")],
                                default="cascade",
                            ),
                        ),
                        ("definition_bpmn", models.TextField(blank=True, null=True)),
                        ("publie_le", models.DateTimeField(blank=True, null=True)),
                        ("publie_par", models.BigIntegerField(blank=True, null=True)),
                        ("motif_modification", models.TextField(blank=True, null=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "circuit",
                            models.ForeignKey(
                                db_column="circuit_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="versions",
                                to="noyau.circuit",
                            ),
                        ),
                        (
                            "niveau_max",
                            models.ForeignKey(
                                blank=True,
                                db_column="niveau_max_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.niveauhierarchique",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "circuit_version",
                        "ordering": ["circuit_id", "-version"],
                        "unique_together": {("circuit", "version")},
                    },
                ),
                migrations.CreateModel(
                    name="CircuitEtape",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("rang", models.SmallIntegerField()),
                        ("libelle", models.TextField()),
                        ("profil_id", models.BigIntegerField(blank=True, null=True)),
                        ("permission_requise_id", models.BigIntegerField(blank=True, null=True)),
                        ("delai_jours", models.SmallIntegerField(blank=True, null=True)),
                        ("bloquante", models.BooleanField(default=True)),
                        ("condition_regle", models.JSONField(blank=True, null=True)),
                        (
                            "circuit_version",
                            models.ForeignKey(
                                db_column="circuit_version_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="etapes",
                                to="noyau.circuitversion",
                            ),
                        ),
                        (
                            "escalade_vers_poste",
                            models.ForeignKey(
                                blank=True,
                                db_column="escalade_vers_poste_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="etapes_escalade",
                                to="noyau.poste",
                            ),
                        ),
                        (
                            "poste",
                            models.ForeignKey(
                                blank=True,
                                db_column="poste_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="etapes_circuit",
                                to="noyau.poste",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "circuit_etape",
                        "ordering": ["circuit_version_id", "rang"],
                        "unique_together": {("circuit_version", "rang")},
                    },
                ),
                migrations.CreateModel(
                    name="CircuitRegle",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "sens",
                            models.TextField(
                                blank=True,
                                choices=[
                                    ("arrive", "Arrivée"),
                                    ("depart", "Départ"),
                                    ("interne", "Interne"),
                                ],
                                null=True,
                            ),
                        ),
                        ("confidentiel", models.BooleanField(blank=True, null=True)),
                        ("priorite", models.SmallIntegerField(default=100)),
                        ("actif", models.BooleanField(default=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "circuit",
                            models.ForeignKey(
                                db_column="circuit_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="regles",
                                to="noyau.circuit",
                            ),
                        ),
                        (
                            "nature",
                            models.ForeignKey(
                                blank=True,
                                db_column="nature_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.nature",
                            ),
                        ),
                        (
                            "structure",
                            models.ForeignKey(
                                blank=True,
                                db_column="structure_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.structure",
                            ),
                        ),
                    ],
                    options={"db_table": "circuit_regle", "ordering": ["priorite", "id"]},
                ),
            ],
        ),
        # -------------------------------------------------------------
        #  2. Cinq colonnes neuves sur trois tables du socle.
        #
        #  Django les cree reellement — ce sont des colonnes qui n'existaient
        #  pas. Toutes disent la meme chose sous trois formes : le socle
        #  portait le delai cible et jamais le moment de la premiere alerte.
        #  Un delai qu'on decouvre le jour de son expiration ne sert a rien.
        # -------------------------------------------------------------
        migrations.AddField(
            model_name="nature",
            name="alerte_avant_jours",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="circuitetape",
            name="alerte_avant_jours",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mentiontype",
            name="delai_jours",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mentiontype",
            name="comportement",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mentiontype",
            name="niveaux_autorises",
            field=models.JSONField(blank=True, default=list),
        ),
        # -------------------------------------------------------------
        #  3. Les deux tables neuves, creees par Django.
        # -------------------------------------------------------------
        migrations.CreateModel(
            name="RubriqueClassement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.TextField(unique=True)),
                ("libelle", models.TextField()),
                ("typologies", models.JSONField(blank=True, default=list)),
                ("ordre", models.SmallIntegerField(default=0)),
                ("actif", models.BooleanField(default=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                ("modifie_le", models.DateTimeField(blank=True, null=True)),
                ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        db_column="parent_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="noyau.rubriqueclassement",
                    ),
                ),
            ],
            options={"db_table": "rubrique_classement", "ordering": ["ordre", "code"]},
        ),
        migrations.CreateModel(
            name="SeuilAlerte",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("indicateur", models.TextField()),
                ("perimetre", models.TextField(default="Toutes structures")),
                (
                    "operateur",
                    models.TextField(
                        choices=[("superieur", "supérieur à"), ("inferieur", "inférieur à")]
                    ),
                ),
                ("valeur", models.DecimalField(decimal_places=2, max_digits=12)),
                ("unite", models.TextField(default="")),
                ("destinataire_libelle", models.TextField(blank=True, null=True)),
                (
                    "canal",
                    models.TextField(
                        choices=[
                            ("notification", "Notification interne"),
                            ("courriel", "Courriel"),
                            ("les_deux", "Les deux"),
                        ],
                        default="notification",
                    ),
                ),
                ("actif", models.BooleanField(default=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                ("modifie_le", models.DateTimeField(blank=True, null=True)),
                ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                (
                    "destinataire",
                    models.ForeignKey(
                        blank=True,
                        db_column="destinataire_poste_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="seuils",
                        to="noyau.poste",
                    ),
                ),
            ],
            options={"db_table": "seuil_alerte", "ordering": ["indicateur"]},
        ),
    ]
