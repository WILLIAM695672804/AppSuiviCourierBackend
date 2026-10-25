"""
La file des notifications et ses envois — RF-SUI-03, RF-ADM-04.

Deux tables, parce que le message et sa sortie n'ont pas la meme duree de vie
ni les memes causes de panne. Le raisonnement complet est dans
`noyau/notifications/modeles.py`.

Trois regles accompagnent la file, toutes en **hypothese** (A51) : l'envoi par
courriel est coupe, les tentatives sont bornees a trois, le lot de depilement a
deux cents. Le SQL dit ce que chacune coute si elle est mal posee.

Aucun semis de notifications : une file d'essai remplie de messages inventes
ferait croire, sur un environnement de recette, que le systeme previent
quelqu'un.
"""

from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [("noyau", "0010_parametres_pieces")]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("type_notification", models.TextField()),
                ("libelle", models.TextField()),
                ("detail", models.TextField(default="")),
                (
                    "importance",
                    models.TextField(
                        choices=[("information", "Information"), ("alerte", "Alerte")],
                        default="information",
                    ),
                ),
                ("objet_type", models.TextField(blank=True, null=True)),
                ("objet_id", models.BigIntegerField(blank=True, null=True)),
                ("lien", models.TextField(blank=True, null=True)),
                ("lu_le", models.DateTimeField(blank=True, null=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                (
                    "destinataire",
                    models.ForeignKey(
                        db_column="destinataire_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="noyau.utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "notification",
                "verbose_name_plural": "notifications",
                "db_table": "notification",
                "ordering": ["-cree_le", "-id"],
            },
        ),
        migrations.CreateModel(
            name="EnvoiNotification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "canal",
                    models.TextField(
                        choices=[
                            ("interne", "Notification interne"),
                            ("courriel", "Courriel"),
                            ("sms", "SMS"),
                        ]
                    ),
                ),
                ("adresse", models.TextField(default="")),
                (
                    "etat",
                    models.TextField(
                        choices=[
                            ("en_attente", "En attente"),
                            ("envoye", "Envoyé"),
                            ("echoue", "Échoué"),
                            ("sans_transport", "Sans transport"),
                        ],
                        default="en_attente",
                    ),
                ),
                ("tentatives", models.SmallIntegerField(default=0)),
                ("envoye_le", models.DateTimeField(blank=True, null=True)),
                ("erreur", models.TextField(blank=True, null=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                (
                    "notification",
                    models.ForeignKey(
                        db_column="notification_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="envois",
                        to="noyau.notification",
                    ),
                ),
            ],
            options={
                "verbose_name": "envoi de notification",
                "verbose_name_plural": "envois de notification",
                "db_table": "envoi_notification",
                "ordering": ["cree_le", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["destinataire", "lu_le"], name="notification_destinataire_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="envoinotification",
            index=models.Index(fields=["etat", "cree_le"], name="envoi_notification_file_idx"),
        ),
        migrations.AddConstraint(
            model_name="envoinotification",
            constraint=models.UniqueConstraint(
                fields=("notification", "canal"),
                name="envoi_notification_unique_par_canal",
            ),
        ),
        migrations.RunSQL(
            sql=_lire("0011_parametres_notifications.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
