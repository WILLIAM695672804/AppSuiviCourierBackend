"""
Etat Django des tables du domaine courrier.

**Cette migration ne cree rien.** Les onze tables du domaine — `courrier`,
`cotation`, `cotation_structure`, `affectation`, `traitement`, `transmission`,
`relance`, les trois du circuit et `sequence_numerotation` — existent depuis
`noyau/migrations/sql/0001_socle.sql`, avec leurs declencheurs. Ce qui manquait
est l'etat : Django ignorait leur existence, et aucun modele ne les couvrait.

`SeparateDatabaseAndState` sert donc a **enregistrer l'etat** sans rien creer,
comme `noyau/0001_initial` l'a fait pour le socle. C'est l'ADR 003 : une seule
source de verite pour le schema.

Sept modeles pour onze tables. Ce qui n'est pas declare :

 * `instance_circuit`, `instance_etape`, `validation` — ancrees sur
   `circuit_etape`, qui est vide : le trajet reel d'un courrier n'a pas ete
   communique (A24) ;
 * `transmission`, `relance`, `traitement_version` — le pilier depart et les
   relances ne sont pas commences. Les declarer d'avance n'ouvre aucun ecran.

Elles se declareront par une migration ulterieure, `state_operations` de meme
forme. Le contenu genere ci-dessous a ete produit par `makemigrations courrier`
puis enveloppe a la main ; un `makemigrations` relance seul reecrirait un fichier
plat, sans l'enveloppe, et tenterait de creer les tables une seconde fois.
"""

import django.contrib.postgres.search
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('noyau', '0013_permission_structures'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Enregistrement de l'etat seul : **aucune table n'est creee ici.**
        # Les onze tables du domaine courrier sont dans `sql/0001_socle.sql`,
        # avec leurs declencheurs — numerotation, plein texte, chef de file,
        # historisation. Meme forme que `noyau/0001_initial`, et pour la meme
        # raison : une seule source de verite pour le schema (ADR 003).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Cotation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('annotation', models.TextField(blank=True, null=True)),
                        ('delai_fixe', models.DateField(blank=True, null=True)),
                        ('decide_le', models.DateTimeField()),
                        ('saisi_le', models.DateTimeField(auto_now_add=True)),
                        ('niveau_cotation', models.SmallIntegerField(default=1)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('cotation_parente', models.ForeignKey(blank=True, db_column='cotation_parente_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cotations_filles', to='courrier.cotation')),
                        ('decide_par', models.ForeignKey(db_column='decide_par', on_delete=django.db.models.deletion.PROTECT, related_name='cotations_decidees', to=settings.AUTH_USER_MODEL)),
                        ('mention_type', models.ForeignKey(blank=True, db_column='mention_type_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cotations', to='noyau.mentiontype')),
                        ('saisi_par', models.ForeignKey(db_column='saisi_par', on_delete=django.db.models.deletion.PROTECT, related_name='cotations_saisies', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'cotation',
                        'verbose_name_plural': 'cotations',
                        'db_table': 'cotation',
                        'ordering': ['-decide_le', '-id'],
                    },
                ),
                migrations.CreateModel(
                    name='CotationStructure',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('rang', models.SmallIntegerField()),
                        ('cotation', models.ForeignKey(db_column='cotation_id', on_delete=django.db.models.deletion.CASCADE, related_name='structures', to='courrier.cotation')),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, related_name='cotations_recues', to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': 'structure cotee',
                        'verbose_name_plural': 'structures cotees',
                        'db_table': 'cotation_structure',
                        'ordering': ['rang'],
                    },
                ),
                migrations.CreateModel(
                    name='Affectation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('orientations', models.TextField(blank=True, null=True)),
                        ('delai_fixe', models.DateField(blank=True, null=True)),
                        ('affecte_le', models.DateTimeField(auto_now_add=True)),
                        ('retire_le', models.DateTimeField(blank=True, null=True)),
                        ('affecte_par', models.ForeignKey(db_column='affecte_par', on_delete=django.db.models.deletion.PROTECT, related_name='affectations_courrier_prononcees', to=settings.AUTH_USER_MODEL)),
                        ('retire_par', models.ForeignKey(blank=True, db_column='retire_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='affectations_courrier_retirees', to=settings.AUTH_USER_MODEL)),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='affectations_courrier', to=settings.AUTH_USER_MODEL)),
                        ('cotation_structure', models.ForeignKey(db_column='cotation_structure_id', on_delete=django.db.models.deletion.PROTECT, related_name='affectations', to='courrier.cotationstructure')),
                    ],
                    options={
                        'verbose_name': 'affectation',
                        'verbose_name_plural': 'affectations',
                        'db_table': 'affectation',
                        'ordering': ['-affecte_le'],
                    },
                ),
                migrations.CreateModel(
                    name='CotationSuivi',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('motif', models.TextField(blank=True, null=True)),
                        ('designe_le', models.DateTimeField(auto_now_add=True)),
                        ('retire_le', models.DateTimeField(blank=True, null=True)),
                        ('cotation', models.ForeignKey(db_column='cotation_id', on_delete=django.db.models.deletion.CASCADE, related_name='suivis', to='courrier.cotation')),
                        ('designe_par', models.ForeignKey(db_column='designe_par', on_delete=django.db.models.deletion.PROTECT, related_name='suivis_designes', to=settings.AUTH_USER_MODEL)),
                        ('retire_par', models.ForeignKey(blank=True, db_column='retire_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='suivis_retires', to=settings.AUTH_USER_MODEL)),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='courriers_suivis', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'cotation pour suivi',
                        'verbose_name_plural': 'cotations pour suivi',
                        'db_table': 'cotation_suivi',
                        'ordering': ['-designe_le'],
                    },
                ),
                migrations.CreateModel(
                    name='Courrier',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('numero', models.TextField()),
                        ('numero_origine', models.TextField(blank=True, null=True)),
                        ('sens', models.TextField(choices=[('arrive', 'Arrive'), ('depart', 'Depart'), ('interne', 'Interne')])),
                        ('confidentiel', models.BooleanField(default=False)),
                        ('date_courrier', models.DateField()),
                        ('date_reception', models.DateField()),
                        ('expediteur_libelle', models.TextField()),
                        ('destinataire_libelle', models.TextField(blank=True, null=True)),
                        ('objet', models.TextField()),
                        ('original_papier_recu', models.BooleanField(default=False)),
                        ('observations', models.TextField(blank=True, null=True)),
                        ('nombre_pieces', models.SmallIntegerField(default=0)),
                        ('statut_courrier', models.TextField(choices=[('cree', 'Cree'), ('en_cours', 'En cours'), ('traite', 'Traite'), ('cloture', 'Cloture')], default='cree')),
                        ('statut_reponse', models.TextField(choices=[('non_engagee', 'Non engagee'), ('en_cours', 'En cours'), ('en_signature', 'En signature'), ('signe', 'Signe')], default='non_engagee')),
                        ('delai_reglementaire_jours', models.SmallIntegerField(blank=True, null=True)),
                        ('date_limite', models.DateField(blank=True, null=True)),
                        ('date_signature', models.DateField(blank=True, null=True)),
                        ('cloture_le', models.DateTimeField(blank=True, null=True)),
                        ('motif_cloture', models.TextField(blank=True, null=True)),
                        ('recherche', django.contrib.postgres.search.SearchVectorField(editable=False, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('cloture_par', models.ForeignKey(blank=True, db_column='cloture_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers_clotures', to=settings.AUTH_USER_MODEL)),
                        ('courrier_lie', models.ForeignKey(blank=True, db_column='courrier_lie_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers_lies', to='courrier.courrier')),
                        ('destinataire', models.ForeignKey(blank=True, db_column='destinataire_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers_recus', to='noyau.correspondant')),
                        ('expediteur', models.ForeignKey(blank=True, db_column='expediteur_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers_emis', to='noyau.correspondant')),
                        ('nature', models.ForeignKey(blank=True, db_column='nature_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers', to='noyau.nature')),
                        ('priorite', models.ForeignKey(blank=True, db_column='priorite_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers', to='noyau.priorite')),
                        ('session', models.ForeignKey(db_column='session_id', on_delete=django.db.models.deletion.PROTECT, related_name='courriers', to='noyau.sessioncourrier')),
                        ('structure_chef_file', models.ForeignKey(blank=True, db_column='structure_chef_file_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courriers_pilotes', to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': 'courrier',
                        'verbose_name_plural': 'courriers',
                        'db_table': 'courrier',
                        'ordering': ['-date_reception', '-id'],
                    },
                ),
                migrations.AddField(
                    model_name='cotation',
                    name='courrier',
                    field=models.ForeignKey(db_column='courrier_id', on_delete=django.db.models.deletion.PROTECT, related_name='cotations', to='courrier.courrier'),
                ),
                migrations.CreateModel(
                    name='Traitement',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('version', models.SmallIntegerField(default=1)),
                        ('contenu', models.TextField(blank=True, null=True)),
                        ('contenu_format', models.TextField(default='html')),
                        ('statut', models.TextField(choices=[('brouillon', 'Brouillon'), ('soumis', 'Soumis'), ('retourne', 'Retourne'), ('valide', 'Valide')], default='brouillon')),
                        ('soumis_le', models.DateTimeField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('cotation_structure', models.ForeignKey(db_column='cotation_structure_id', on_delete=django.db.models.deletion.PROTECT, related_name='traitements', to='courrier.cotationstructure')),
                        ('courrier', models.ForeignKey(db_column='courrier_id', on_delete=django.db.models.deletion.PROTECT, related_name='traitements', to='courrier.courrier')),
                        ('redacteur', models.ForeignKey(db_column='redacteur_id', on_delete=django.db.models.deletion.PROTECT, related_name='traitements_rediges', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'traitement',
                        'verbose_name_plural': 'traitements',
                        'db_table': 'traitement',
                        'ordering': ['-cree_le'],
                    },
                ),
                migrations.CreateModel(
                    name='SequenceNumerotation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('annee', models.SmallIntegerField()),
                        ('dernier_numero', models.IntegerField(default=0)),
                        ('session', models.ForeignKey(db_column='session_id', on_delete=django.db.models.deletion.PROTECT, related_name='sequences', to='noyau.sessioncourrier')),
                    ],
                    options={
                        'verbose_name': 'sequence de numerotation',
                        'verbose_name_plural': 'sequences de numerotation',
                        'db_table': 'sequence_numerotation',
                        'ordering': ['-annee'],
                        'constraints': [models.UniqueConstraint(fields=('session', 'annee'), name='sequence_numerotation_session_id_annee_key')],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
