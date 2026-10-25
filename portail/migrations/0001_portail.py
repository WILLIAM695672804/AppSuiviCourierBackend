"""
Le portail usagers entre au modele — §3.13.

Neuf tables, et un referentiel seme ici : les evenements dont un usager peut
etre prevenu. Il etait ecrit dans le front
(`lib/demo/donneesPortail.ts` et la constante `OBLIGATOIRES` de l'ecran des
preferences) ; une liste de choix dans un formulaire est un referentiel qui
s'ignore, et celui-ci decidait de ce qu'un usager a le droit de couper.

`obligatoire` est la colonne qui compte. Deux evenements ne se desactivent pas :
la demande de piece complementaire, qui ouvre un delai de forclusion, et la
decision rendue, qui ouvre un delai de recours. La regle vit en base et le
serveur la fait respecter ; l'ecran ne fait que la refleter.

Ce qui n'est **pas** seme : aucune demande, aucun echange. Ils viennent des
usagers, et un jeu d'essai depose sous le nom d'un compte fictif aurait fait
croire a un portail deja en service.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

#: Les cinq evenements notifiables, et lesquels ne se coupent pas.
#: Repris de `frontend/src/lib/demo/donneesPortail.ts`, qui les portait jusqu'ici.
EVENEMENTS = [
    ("depot", "Accusé de réception de mes dépôts", False, 1),
    ("complement", "Demande de pièce complémentaire", True, 2),
    ("decision", "Décision rendue sur ma demande", True, 3),
    ("echeance", "Rappel avant une échéance qui me concerne", False, 4),
    ("cloture", "Clôture et archivage de mon dossier", False, 5),
]


def semer_evenements(apps, schema_editor):
    Evenement = apps.get_model("portail", "EvenementNotifiable")
    for cle, libelle, obligatoire, ordre in EVENEMENTS:
        Evenement.objects.update_or_create(
            cle=cle,
            defaults={"libelle": libelle, "obligatoire": obligatoire, "ordre": ordre},
        )


def oublier_evenements(apps, schema_editor):
    Evenement = apps.get_model("portail", "EvenementNotifiable")
    Evenement.objects.filter(cle__in=[cle for cle, _, _, _ in EVENEMENTS]).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('noyau', '0007_parametres_dossier'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EvenementNotifiable',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cle', models.TextField(unique=True)),
                ('libelle', models.TextField()),
                ('obligatoire', models.BooleanField(default=False)),
                ('ordre', models.SmallIntegerField(default=0)),
                ('actif', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'événement notifiable',
                'verbose_name_plural': 'événements notifiables',
                'db_table': 'evenement_notifiable',
                'ordering': ['ordre', 'cle'],
            },
        ),
        migrations.CreateModel(
            name='DemandeUsager',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.TextField(unique=True)),
                ('type', models.TextField(choices=[('Demande', 'Demande — autorisation, information, document'), ('Réclamation', 'Réclamation — contestation, litige'), ('Autorisation', 'Autorisation — occupation, travaux, accès'), ('Requête', "Requête — révision d'une décision")], default='Demande')),
                ('objet', models.TextField()),
                ('contexte', models.TextField()),
                ('deposee_le', models.DateField()),
                ('reponse_attendue_le', models.DateField()),
                ('decision_le', models.DateField(blank=True, null=True)),
                ('decision', models.TextField(blank=True, null=True)),
                ('clos_le', models.DateField(blank=True, null=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('cree_par', models.BigIntegerField(blank=True, null=True)),
                ('modifie_le', models.DateTimeField(blank=True, null=True)),
                ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                ('invalide_le', models.DateTimeField(blank=True, null=True)),
                ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                ('deposant', models.ForeignKey(db_column='deposant_id', on_delete=django.db.models.deletion.PROTECT, related_name='demandes_portail', to=settings.AUTH_USER_MODEL)),
                ('service_instructeur', models.ForeignKey(blank=True, db_column='service_instructeur_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='demandes_portail', to='noyau.structure')),
            ],
            options={
                'verbose_name': "demande d'usager",
                'verbose_name_plural': "demandes d'usagers",
                'db_table': 'demande_usager',
                'ordering': ['-deposee_le', '-id'],
            },
        ),
        migrations.CreateModel(
            name='ComplementDemande',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('objet', models.TextField()),
                ('demande_le', models.DateField()),
                ('avant_le', models.DateField()),
                ('satisfait_le', models.DateField(blank=True, null=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('cree_par', models.BigIntegerField(blank=True, null=True)),
                ('demande', models.ForeignKey(db_column='demande_id', on_delete=django.db.models.deletion.CASCADE, related_name='complements', to='portail.demandeusager')),
            ],
            options={
                'verbose_name': 'complément demandé',
                'verbose_name_plural': 'compléments demandés',
                'db_table': 'complement_demande',
                'ordering': ['-demande_le', '-id'],
            },
        ),
        migrations.CreateModel(
            name='EchangeDematerialise',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.TextField(unique=True)),
                ('intitule', models.TextField()),
                ('nature', models.TextField(choices=[('Marché public', 'Marché public'), ('Convention', 'Convention'), ('Reporting réglementaire', 'Reporting réglementaire')], default='Marché public')),
                ('ouvert_le', models.DateField()),
                ('echeance', models.DateField(blank=True, null=True)),
                ('attendus', models.SmallIntegerField(default=1)),
                ('clos_le', models.DateField(blank=True, null=True)),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('cree_par', models.BigIntegerField(blank=True, null=True)),
                ('partenaire', models.ForeignKey(db_column='partenaire_id', on_delete=django.db.models.deletion.PROTECT, related_name='echanges_portail', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'échange dématérialisé',
                'verbose_name_plural': 'échanges dématérialisés',
                'db_table': 'echange_dematerialise',
                'ordering': ['-ouvert_le', '-id'],
            },
        ),
        migrations.CreateModel(
            name='MessagePortail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('texte', models.TextField()),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('auteur', models.ForeignKey(db_column='auteur_id', on_delete=django.db.models.deletion.PROTECT, related_name='messages_portail', to=settings.AUTH_USER_MODEL)),
                ('demande', models.ForeignKey(db_column='demande_id', on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='portail.demandeusager')),
            ],
            options={
                'verbose_name': 'message du portail',
                'verbose_name_plural': 'messages du portail',
                'db_table': 'message_portail',
                'ordering': ['cree_le', 'id'],
            },
        ),
        migrations.CreateModel(
            name='PieceDemande',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.TextField()),
                ('taille', models.TextField()),
                ('deposee_le', models.DateField()),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('demande', models.ForeignKey(db_column='demande_id', on_delete=django.db.models.deletion.CASCADE, related_name='pieces', to='portail.demandeusager')),
                ('depose_par', models.ForeignKey(db_column='depose_par_id', on_delete=django.db.models.deletion.PROTECT, related_name='pieces_portail', to=settings.AUTH_USER_MODEL)),
                ('message', models.ForeignKey(blank=True, db_column='message_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pieces', to='portail.messageportail')),
            ],
            options={
                'verbose_name': "pièce d'une demande",
                'verbose_name_plural': 'pièces des demandes',
                'db_table': 'piece_demande',
                'ordering': ['-deposee_le', '-id'],
            },
        ),
        migrations.CreateModel(
            name='PieceEchange',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.TextField()),
                ('taille', models.TextField()),
                ('deposee_le', models.DateField()),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('depose_par', models.ForeignKey(db_column='depose_par_id', on_delete=django.db.models.deletion.PROTECT, related_name='pieces_echange', to=settings.AUTH_USER_MODEL)),
                ('echange', models.ForeignKey(db_column='echange_id', on_delete=django.db.models.deletion.CASCADE, related_name='pieces', to='portail.echangedematerialise')),
            ],
            options={
                'verbose_name': "pièce d'un échange",
                'verbose_name_plural': 'pièces des échanges',
                'db_table': 'piece_echange',
                'ordering': ['-deposee_le', '-id'],
            },
        ),
        migrations.CreateModel(
            name='PreferenceNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('courriel', models.EmailField(max_length=254)),
                ('telephone', models.TextField(blank=True, null=True)),
                ('canal', models.TextField(choices=[('Courriel', 'Courriel'), ('SMS', 'SMS'), ('Portail seulement', 'Portail seulement')], default='Courriel')),
                ('cree_le', models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(blank=True, null=True)),
                ('utilisateur', models.OneToOneField(db_column='utilisateur_id', on_delete=django.db.models.deletion.CASCADE, related_name='preference_portail', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'préférence de notification',
                'verbose_name_plural': 'préférences de notification',
                'db_table': 'preference_notification',
            },
        ),
        migrations.CreateModel(
            name='PreferenceEvenement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actif', models.BooleanField(default=True)),
                ('evenement', models.ForeignKey(db_column='evenement_id', on_delete=django.db.models.deletion.CASCADE, related_name='preferences', to='portail.evenementnotifiable')),
                ('preference', models.ForeignKey(db_column='preference_id', on_delete=django.db.models.deletion.CASCADE, related_name='evenements', to='portail.preferencenotification')),
            ],
            options={
                'verbose_name': 'préférence par événement',
                'verbose_name_plural': 'préférences par événement',
                'db_table': 'preference_evenement',
                'ordering': ['evenement__ordre'],
            },
        ),
        migrations.AddIndex(
            model_name='demandeusager',
            index=models.Index(fields=['deposant', '-deposee_le'], name='idx_demande_deposant'),
        ),
        migrations.AddConstraint(
            model_name='demandeusager',
            constraint=models.CheckConstraint(condition=models.Q(('reponse_attendue_le__gte', models.F('deposee_le'))), name='reponse_attendue_apres_depot'),
        ),
        migrations.AddConstraint(
            model_name='demandeusager',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('decision__isnull', True), ('decision_le__isnull', True)), models.Q(('decision__isnull', False), ('decision_le__isnull', False)), _connector='OR'), name='decision_datee_et_motivee'),
        ),
        migrations.AddConstraint(
            model_name='complementdemande',
            constraint=models.CheckConstraint(condition=models.Q(('avant_le__gte', models.F('demande_le'))), name='complement_delai_positif'),
        ),
        migrations.AddConstraint(
            model_name='echangedematerialise',
            constraint=models.CheckConstraint(condition=models.Q(('attendus__gte', 1)), name='echange_attend_au_moins_une_piece'),
        ),
        migrations.AddConstraint(
            model_name='preferenceevenement',
            constraint=models.UniqueConstraint(fields=('preference', 'evenement'), name='unicite_preference_evenement'),
        ),
        migrations.RunPython(semer_evenements, oublier_evenements),
    ]
