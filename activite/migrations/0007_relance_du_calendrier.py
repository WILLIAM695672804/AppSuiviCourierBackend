"""
Le calendrier de production apprend a relancer — §3.3.

« Piloter le calendrier officiel de production : qui alimente quoi, a quelle
frequence, **avec relances automatiques en cas de non-saisie**. » La table
disait les trois premiers points et pas le quatrieme.

Deux colonnes et non un reglage global : un rapport mensuel et un rapport
annuel ne se relancent pas au meme rythme, et une valeur unique aurait force
l'un des deux a etre faux.

`relance_automatique` vaut `true` par defaut, y compris sur les lignes
existantes. C'est deliberé — le defaut inverse aurait installe un calendrier
qui ne relance personne, ce qui est precisement l'etat que le §3.3 corrige.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0006_uid_cote_python"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendrierproduction",
            name="relance_automatique",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="calendrierproduction",
            name="jours_avant_relance",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
    ]
