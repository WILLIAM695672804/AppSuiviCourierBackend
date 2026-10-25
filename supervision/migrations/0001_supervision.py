"""
La supervision entre au modele — §3.10.

Deux tables. `mesure_requete` est vide a la creation et se remplit d'elle-meme,
requete apres requete, par le middleware `supervision.mesure` : rien a semer,
et un ecran vide le premier jour est la verite — la plateforme vient d'etre
demarree.

`integration` est semee ici, avec les branchements que le BRD **exige** et qui
ne sont pas livres. Les afficher « Non connecté » est exact ; ne pas les
afficher aurait laisse croire qu'il n'y a rien a brancher. Chaque ligne porte
l'exigence qui la demande — une integration sans source est une integration que
personne n'a demandee.

Le portail usagers fait exception : il est livre, et sa ligne le dit. Ce n'est
pas un systeme tiers au sens strict, mais c'est bien une integration au sens du
§3.10 — le point par ou l'exterieur entre.
"""

from django.db import migrations, models

#: (systeme, type, protocole, etat, exigence, note, ordre)
INTEGRATIONS = [
    (
        "Annuaire d'entreprise",
        "Annuaire",
        "LDAP / SAML 2.0 — à trancher",
        "Non connecté",
        "RF-ADM-02",
        "L'authentification se fait encore par mot de passe applicatif. "
        "Ni le fournisseur ni le protocole ne sont arrêtés (A47).",
        1,
    ),
    (
        "Messagerie institutionnelle",
        "Messagerie",
        "SMTP",
        "Non connecté",
        "RF-SUI-03",
        "Les notifications par courriel sont réglables par l'usager mais "
        "aucune n'est envoyée : rien n'est branché en sortie.",
        2,
    ),
    (
        "Passerelle SMS",
        "Messagerie",
        "HTTP",
        "Non connecté",
        "RF-SUI-03",
        "Le canal SMS est proposé au portail. Sans passerelle, un usager qui "
        "le choisit ne reçoit rien — le service refuse d'ailleurs le canal "
        "sans numéro.",
        3,
    ),
    (
        "Système financier",
        "Système financier",
        "À définir",
        "Non connecté",
        "§3.10",
        "Les recouvrements sont saisis à la main par les structures qui les "
        "constatent. Aucun rapprochement automatique.",
        4,
    ),
    (
        "Portail usagers",
        "Portail usagers",
        "HTTPS — interne",
        "Connecté",
        "§3.13",
        "Dépôt, suivi, échanges dématérialisés et préférences de notification. "
        "Livré le 14 août 2026.",
        5,
    ),
]


def semer_integrations(apps, schema_editor):
    Integration = apps.get_model("supervision", "Integration")
    for systeme, type_, protocole, etat, exigence, note, ordre in INTEGRATIONS:
        Integration.objects.update_or_create(
            systeme=systeme,
            defaults={
                "type": type_,
                "protocole": protocole,
                "etat": etat,
                "exigence": exigence,
                "note": note,
                "ordre": ordre,
            },
        )


def oublier_integrations(apps, schema_editor):
    Integration = apps.get_model("supervision", "Integration")
    Integration.objects.filter(systeme__in=[ligne[0] for ligne in INTEGRATIONS]).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Integration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('systeme', models.TextField(unique=True)),
                ('type', models.TextField(choices=[('Annuaire', "Annuaire d'entreprise"), ('Messagerie', 'Messagerie et SMS'), ('Système financier', 'Système financier'), ('ERP', 'Progiciel de gestion'), ('Portail usagers', 'Portail usagers')])),
                ('protocole', models.TextField()),
                ('etat', models.TextField(choices=[('Connecté', 'Connecté'), ('Dégradé', 'Dégradé'), ('Non connecté', 'Non connecté'), ('En construction', 'En construction')], default='Non connecté')),
                ('note', models.TextField(blank=True, null=True)),
                ('exigence', models.TextField(blank=True, null=True)),
                ('derniere_synchronisation', models.DateTimeField(blank=True, null=True)),
                ('latence_ms', models.IntegerField(blank=True, null=True)),
                ('volume_dernier_passage', models.IntegerField(blank=True, null=True)),
                ('erreurs_24h', models.IntegerField(default=0)),
                ('ordre', models.SmallIntegerField(default=0)),
                ('actif', models.BooleanField(default=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'intégration',
                'verbose_name_plural': 'intégrations',
                'db_table': 'integration',
                'ordering': ['ordre', 'systeme'],
            },
        ),
        migrations.CreateModel(
            name='MesureRequete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('methode', models.CharField(max_length=10)),
                ('chemin', models.TextField()),
                ('heure', models.DateTimeField()),
                ('appels', models.IntegerField(default=0)),
                ('echecs', models.IntegerField(default=0)),
                ('duree_totale_ms', models.BigIntegerField(default=0)),
                ('duree_max_ms', models.IntegerField(default=0)),
                ('sous_200', models.IntegerField(default=0)),
                ('sous_500', models.IntegerField(default=0)),
                ('sous_1000', models.IntegerField(default=0)),
                ('sous_2000', models.IntegerField(default=0)),
                ('sous_5000', models.IntegerField(default=0)),
                ('au_dela', models.IntegerField(default=0)),
            ],
            options={
                'verbose_name': 'mesure de requête',
                'verbose_name_plural': 'mesures de requêtes',
                'db_table': 'mesure_requete',
                'ordering': ['-heure', 'chemin'],
                'indexes': [models.Index(fields=['-heure'], name='idx_mesure_heure')],
                'constraints': [models.UniqueConstraint(fields=('methode', 'chemin', 'heure'), name='unicite_mesure_par_heure')],
            },
        ),
        migrations.RunPython(semer_integrations, oublier_integrations),
    ]
