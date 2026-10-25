"""
Schema du pilier gouvernance.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_gouvernance.sql`.

Elle porte le renommage decide par l'ADR 006 : `decision_reunion`, livree avec
le pilier activites pour le §19, devient `engagement` et accueille les trois
origines — decision d'instance, prescription de filiale, recommandation externe.
D'ou la dependance a `activite.0004` : la table doit exister, et le pilier
activites doit avoir fini d'ecrire dessus, avant qu'elle ne change de nom.

Le retrait du modele `DecisionReunion` de l'etat d'`activite` suit dans
`activite.0005`, qui depend de celle-ci. L'ordre est impose : renommer la table
avant que Django n'apprenne que le modele a demenage.

Ce que l'ORM ne saurait pas exprimer et qu'il serait absurde de perdre : deux
declencheurs (reference sous verrou d'avis, avancement moyen des structures
chargees), une contrainte d'exclusion GiST sur le chevauchement des absences,
la vue `v_engagement_etat`, des index partiels et une colonne generee.

Ce fichier est assemble par `scripts/assembler_migration_pilier.py`.
"""

import uuid
from pathlib import Path

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("noyau", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("activite", "0004_parametres_traitements"),
    ]

    operations = [
        # 1. Le schema livre, a l'identique. Irreversible : on ne defait pas la
        #    creation d'un schema, on la recree.
        migrations.RunSQL(sql=_lire("0001_gouvernance.sql"), reverse_sql=migrations.RunSQL.noop),
        # 2. Enregistrement de l'etat seul : aucune table n'est creee ici.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='VueEngagementEtat',
                    fields=[
                        ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                        ('origine', models.TextField()),
                        ('instance', models.TextField(null=True)),
                        ('etat_affiche', models.TextField()),
                        ('avancement', models.DecimalField(decimal_places=2, max_digits=5)),
                        ('relances', models.IntegerField()),
                        ('jalon_echu', models.BooleanField()),
                    ],
                    options={
                        'verbose_name': "etat affiche d'un engagement",
                        'verbose_name_plural': 'etats affiches des engagements',
                        'db_table': 'v_engagement_etat',
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='AgregatGouvernanceJour',
                    fields=[
                        ('pk', models.CompositePrimaryKey('jour', 'origine', 'instance', blank=True, editable=False, primary_key=True, serialize=False)),
                        ('jour', models.DateField()),
                        ('origine', models.TextField()),
                        ('instance', models.TextField(default='')),
                        ('nb_total', models.IntegerField(default=0)),
                        ('nb_a_lancer', models.IntegerField(default=0)),
                        ('nb_en_cours', models.IntegerField(default=0)),
                        ('nb_executes', models.IntegerField(default=0)),
                        ('nb_en_retard', models.IntegerField(default=0)),
                        ('nb_suspendus', models.IntegerField(default=0)),
                        ('depots_en_souffrance', models.IntegerField(default=0)),
                        ('absences_sans_interim', models.IntegerField(default=0)),
                        ('calcule_le', models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        'verbose_name': 'agregat de gouvernance du jour',
                        'verbose_name_plural': 'agregats de gouvernance du jour',
                        'db_table': 'agregat_gouvernance_jour',
                    },
                ),
                migrations.CreateModel(
                    name='EntiteExterne',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('sigle', models.TextField(unique=True)),
                        ('libelle', models.TextField()),
                        ('nature', models.TextField(choices=[('filiale', 'Filiale'), ('succursale', 'Succursale')])),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'verbose_name': 'entite exterieure',
                        'verbose_name_plural': 'entites exterieures',
                        'db_table': 'entite_externe',
                        'ordering': ['sigle'],
                    },
                ),
                migrations.CreateModel(
                    name='OrganisationExterne',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('sigle', models.TextField(unique=True)),
                        ('libelle', models.TextField()),
                        ('nature', models.TextField(choices=[('comite_national', 'Comite national'), ('organisation_portuaire', 'Organisation portuaire'), ('association_professionnelle', 'Association professionnelle'), ('groupement', 'Groupement')])),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'verbose_name': 'organisation exterieure',
                        'verbose_name_plural': 'organisations exterieures',
                        'db_table': 'organisation_externe',
                        'ordering': ['sigle'],
                    },
                ),
                migrations.CreateModel(
                    name='CongeDroit',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('annee', models.SmallIntegerField()),
                        ('droits_jours', models.SmallIntegerField(default=30)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='conges', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'droit a conges',
                        'verbose_name_plural': 'droits a conges',
                        'db_table': 'conge_droit',
                        'ordering': ['-annee'],
                    },
                ),
                migrations.CreateModel(
                    name='CongePeriode',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('du', models.DateField()),
                        ('au', models.DateField()),
                        ('etat', models.TextField(choices=[('souhaite', 'Souhaite'), ('arbitre', 'Arbitre'), ('valide', 'Valide'), ('reporte', 'Reporte')], default='souhaite')),
                        ('motif_report', models.TextField(blank=True, null=True)),
                        ('arbitre_le', models.DateTimeField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('arbitre_par', models.ForeignKey(blank=True, db_column='arbitre_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='conges_arbitres', to=settings.AUTH_USER_MODEL)),
                        ('conge_droit', models.ForeignKey(db_column='conge_droit_id', on_delete=django.db.models.deletion.CASCADE, related_name='periodes', to='gouvernance.congedroit')),
                    ],
                    options={
                        'verbose_name': 'periode de conges',
                        'verbose_name_plural': 'periodes de conges',
                        'db_table': 'conge_periode',
                        'ordering': ['du'],
                    },
                ),
                migrations.CreateModel(
                    name='Disponibilite',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('type_absence', models.TextField(choices=[('conge_annuel', 'Conge annuel'), ('mission', 'Mission'), ('interim', 'Interim'), ('formation', 'Formation'), ('absence_exceptionnelle', 'Absence exceptionnelle')])),
                        ('du', models.DateField()),
                        ('au', models.DateField()),
                        ('motif', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('interimaire', models.ForeignKey(blank=True, db_column='interimaire_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='interims', to=settings.AUTH_USER_MODEL)),
                        ('saisi_par', models.ForeignKey(db_column='saisi_par', on_delete=django.db.models.deletion.PROTECT, related_name='absences_saisies', to=settings.AUTH_USER_MODEL)),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='absences', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'disponibilite',
                        'ordering': ['-du'],
                    },
                ),
                migrations.CreateModel(
                    name='Engagement',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('reference', models.TextField(blank=True, editable=False, null=True, unique=True)),
                        ('origine', models.TextField(choices=[('instance', "Decision d'instance"), ('organe_filiale', "Prescription d'un organe de filiale"), ('organisation_externe', "Recommandation d'une organisation exterieure")], default='instance')),
                        ('instance', models.TextField(blank=True, choices=[('conseil_administration', "Conseil d'administration"), ('codir', 'CODIR'), ('directeur_general', 'Directeur general'), ('assemblee_generale', 'Assemblee generale')], null=True)),
                        ('date_engagement', models.DateField()),
                        ('objet', models.TextField()),
                        ('texte', models.TextField(blank=True, null=True)),
                        ('contexte', models.TextField(blank=True, null=True)),
                        ('echeance', models.DateField(blank=True, null=True)),
                        ('avancement', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                        ('suspendu_le', models.DateTimeField(blank=True, null=True)),
                        ('motif_suspension', models.TextField(blank=True, null=True)),
                        ('execute_le', models.DateTimeField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('execute_par', models.ForeignKey(blank=True, db_column='execute_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='engagements_executes', to=settings.AUTH_USER_MODEL)),
                        ('prise_par', models.ForeignKey(db_column='prise_par', on_delete=django.db.models.deletion.PROTECT, related_name='engagements_pris', to=settings.AUTH_USER_MODEL)),
                        ('saisie_par', models.ForeignKey(db_column='saisie_par', on_delete=django.db.models.deletion.PROTECT, related_name='engagements_saisis', to=settings.AUTH_USER_MODEL)),
                        ('suspendu_par', models.ForeignKey(blank=True, db_column='suspendu_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='engagements_suspendus', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'engagement',
                        'ordering': ['-date_engagement'],
                    },
                ),
                migrations.CreateModel(
                    name='EngagementJalon',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('libelle', models.TextField()),
                        ('echeance', models.DateField()),
                        ('fait_le', models.DateField(blank=True, null=True)),
                        ('ordre', models.SmallIntegerField(default=1)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('engagement', models.ForeignKey(db_column='engagement_id', on_delete=django.db.models.deletion.CASCADE, related_name='jalons', to='gouvernance.engagement')),
                        ('structure', models.ForeignKey(blank=True, db_column='structure_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': "jalon d'engagement",
                        'verbose_name_plural': "jalons d'engagement",
                        'db_table': 'engagement_jalon',
                        'ordering': ['engagement', 'ordre'],
                    },
                ),
                migrations.CreateModel(
                    name='EngagementObservation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('texte', models.TextField()),
                        ('relance', models.BooleanField(default=False)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('auteur', models.ForeignKey(db_column='auteur_id', on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                        ('engagement', models.ForeignKey(db_column='engagement_id', on_delete=django.db.models.deletion.CASCADE, related_name='observations', to='gouvernance.engagement')),
                    ],
                    options={
                        'verbose_name': "observation d'engagement",
                        'verbose_name_plural': "observations d'engagement",
                        'db_table': 'engagement_observation',
                        'ordering': ['-cree_le'],
                    },
                ),
                migrations.CreateModel(
                    name='EngagementStructure',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('rang', models.SmallIntegerField()),
                        ('pilote', models.BooleanField(editable=False)),
                        ('avancement', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('engagement', models.ForeignKey(db_column='engagement_id', on_delete=django.db.models.deletion.CASCADE, related_name='structures', to='gouvernance.engagement')),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': 'structure chargee',
                        'verbose_name_plural': 'structures chargees',
                        'db_table': 'engagement_structure',
                        'ordering': ['engagement', 'rang'],
                    },
                ),
                migrations.CreateModel(
                    name='OrganeGestion',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('organe', models.TextField(choices=[('conseil_administration', "Conseil d'administration"), ('assemblee_generale', 'Assemblee generale'), ('comite_gestion', 'Comite de gestion')])),
                        ('prochaine_session', models.DateField(blank=True, null=True)),
                        ('etat_preparation', models.TextField(choices=[('a_preparer', 'A preparer'), ('dossier_en_cours', 'Dossier en cours'), ('dossier_transmis', 'Dossier transmis'), ('tenue', 'Tenue')], default='a_preparer')),
                        ('documents_attendus', models.SmallIntegerField(default=0)),
                        ('documents_recus', models.SmallIntegerField(default=0)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('entite_externe', models.ForeignKey(db_column='entite_externe_id', on_delete=django.db.models.deletion.PROTECT, related_name='organes', to='gouvernance.entiteexterne')),
                    ],
                    options={
                        'verbose_name': 'organe de gestion',
                        'verbose_name_plural': 'organes de gestion',
                        'db_table': 'organe_gestion',
                    },
                ),
                migrations.AddField(
                    model_name='engagement',
                    name='organe_gestion',
                    field=models.ForeignKey(blank=True, db_column='organe_gestion_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='prescriptions', to='gouvernance.organegestion'),
                ),
                migrations.AddField(
                    model_name='engagement',
                    name='organisation_externe',
                    field=models.ForeignKey(blank=True, db_column='organisation_externe_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='recommandations', to='gouvernance.organisationexterne'),
                ),
                migrations.CreateModel(
                    name='Representation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('mandat_du', models.DateField()),
                        ('mandat_au', models.DateField()),
                        ('reunions_tenues', models.SmallIntegerField(default=0)),
                        ('reunions_participees', models.SmallIntegerField(default=0)),
                        ('apport', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('organisation_externe', models.ForeignKey(db_column='organisation_externe_id', on_delete=django.db.models.deletion.PROTECT, related_name='representations', to='gouvernance.organisationexterne')),
                        ('representant', models.ForeignKey(db_column='representant_id', on_delete=django.db.models.deletion.PROTECT, related_name='representations', to=settings.AUTH_USER_MODEL)),
                        ('suppleant', models.ForeignKey(blank=True, db_column='suppleant_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='suppleances', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'representation',
                        'ordering': ['organisation_externe'],
                    },
                ),
                migrations.CreateModel(
                    name='Seance',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('reference', models.TextField(unique=True)),
                        ('type_seance', models.TextField(choices=[('reunion_dg', 'Reunion presidee par le DG'), ('session_ca', "Session du Conseil d'administration"), ('assemblee_generale', 'Assemblee generale'), ('codir', 'CODIR'), ('rapport_activite', "Rapport d'activite"), ('rapport_sectoriel', 'Rapport sectoriel')])),
                        ('intitule', models.TextField()),
                        ('date_seance', models.DateField()),
                        ('echeance_depot', models.DateField()),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('president', models.ForeignKey(blank=True, db_column='president_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='seances_presidees', to=settings.AUTH_USER_MODEL)),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'db_table': 'seance',
                        'ordering': ['-date_seance'],
                    },
                ),
                migrations.AddField(
                    model_name='engagement',
                    name='seance',
                    field=models.ForeignKey(blank=True, db_column='seance_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='engagements', to='gouvernance.seance'),
                ),
                migrations.CreateModel(
                    name='SeanceDocument',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nature', models.TextField(choices=[('ordre_du_jour', 'Ordre du jour'), ('compte_rendu', 'Compte rendu'), ('proces_verbal', 'Proces-verbal'), ('dossier_seance', 'Dossier de seance'), ('rapport', 'Rapport')])),
                        ('libelle', models.TextField()),
                        ('depose_le', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('depose_par', models.ForeignKey(blank=True, db_column='depose_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documents_deposes', to=settings.AUTH_USER_MODEL)),
                        ('piece_jointe', models.ForeignKey(blank=True, db_column='piece_jointe_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.piecejointe')),
                        ('seance', models.ForeignKey(db_column='seance_id', on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='gouvernance.seance')),
                    ],
                    options={
                        'verbose_name': 'document de seance',
                        'verbose_name_plural': 'documents de seance',
                        'db_table': 'seance_document',
                    },
                ),
                migrations.CreateModel(
                    name='SeanceParticipant',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('present', models.BooleanField(default=True)),
                        ('excuse', models.BooleanField(default=False)),
                        ('seance', models.ForeignKey(db_column='seance_id', on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='gouvernance.seance')),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'participant a une seance',
                        'verbose_name_plural': 'participants aux seances',
                        'db_table': 'seance_participant',
                    },
                ),
                migrations.CreateModel(
                    name='SeancePoint',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('rang', models.SmallIntegerField()),
                        ('point', models.TextField()),
                        ('rapporteur', models.ForeignKey(blank=True, db_column='rapporteur_id', null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                        ('seance', models.ForeignKey(db_column='seance_id', on_delete=django.db.models.deletion.CASCADE, related_name='points', to='gouvernance.seance')),
                    ],
                    options={
                        'verbose_name': "point d'ordre du jour",
                        'verbose_name_plural': "points d'ordre du jour",
                        'db_table': 'seance_point',
                        'ordering': ['seance', 'rang'],
                    },
                ),
            ]
        ),
    ]
