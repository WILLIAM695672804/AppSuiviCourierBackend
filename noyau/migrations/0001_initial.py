"""
Socle du schema.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_socle.sql`, copie fidele du
script livre avec le modele de donnees, puis adaptees par
`sql/0002_adaptations.sql`.

La raison est que le schema utilise des constructions que l'ORM ne sait pas
exprimer et qu'il serait absurde de perdre : partitionnement declaratif par
annee sur `evenement` et `champ_historique`, partitionnement mensuel sur
`journal_acces`, contrainte d'exclusion GiST sur le rattachement a une session,
index BRIN, index partiels, declencheurs d'historisation et de numerotation,
configuration de recherche plein texte sans accents.

`SeparateDatabaseAndState` sert donc a **enregistrer l'etat** sans rien creer :
Django apprend l'existence des modeles, les tables existent deja. A partir de la
migration 0002, Django reprend la main normalement — c'est la decision 003 :
une seule source de verite pour le schema.

Ce fichier est assemble par `scripts/assembler_migration_socle.py`. Un
`makemigrations` lance seul regenererait un fichier plat, sans le
`SeparateDatabaseAndState` ni les deux `RunSQL`, et la base serait creee deux
fois.
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

    dependencies = []

    operations = [
        # 1. Le schema livre, a l'identique. Irreversible : on ne defait pas la
        #    creation d'une base, on la recree.
        migrations.RunSQL(sql=_lire("0001_socle.sql"), reverse_sql=migrations.RunSQL.noop),
        # 2. Les adaptations du backend, isolees pour rester visibles au diff.
        migrations.RunSQL(sql=_lire("0002_adaptations.sql"), reverse_sql=migrations.RunSQL.noop),
        # 3. Enregistrement de l'etat seul : aucune table n'est creee ici.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ChampHistorique',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('table_cible', models.TextField()),
                        ('ligne_id', models.BigIntegerField()),
                        ('colonne', models.TextField()),
                        ('valeur_avant', models.TextField(blank=True, null=True)),
                        ('valeur_apres', models.TextField(blank=True, null=True)),
                        ('acteur_id', models.BigIntegerField(blank=True, null=True)),
                        ('survenu_le', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'champ_historique',
                        'ordering': ['-survenu_le'],
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='Evenement',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('objet_type', models.TextField(help_text='« activite », « courrier », « plan_actions »…')),
                        ('objet_id', models.BigIntegerField()),
                        ('courrier_id', models.BigIntegerField(blank=True, null=True)),
                        ('type_evenement', models.TextField()),
                        ('libelle', models.TextField()),
                        ('detail', models.TextField(blank=True, null=True)),
                        ('acteur_id', models.BigIntegerField(blank=True, null=True)),
                        ('agit_pour_id', models.BigIntegerField(blank=True, null=True)),
                        ('survenu_le', models.DateTimeField(auto_now_add=True)),
                        ('donnees', models.JSONField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'evenement',
                        'ordering': ['survenu_le'],
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='JournalAcces',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('acteur_id', models.BigIntegerField()),
                        ('objet_type', models.TextField()),
                        ('objet_id', models.BigIntegerField(blank=True, null=True)),
                        ('action', models.TextField(choices=[('consultation', 'Consultation'), ('liste', 'Liste'), ('impression', 'Impression'), ('export', 'Export'), ('telechargement', 'Telechargement')])),
                        ('adresse_ip', models.GenericIPAddressField(blank=True, null=True)),
                        ('agent_utilisateur', models.TextField(blank=True, null=True)),
                        ('survenu_le', models.DateTimeField()),
                        ('empreinte', models.TextField(blank=True, null=True)),
                        ('empreinte_precedente', models.TextField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'journal_acces',
                        'ordering': ['-survenu_le'],
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='Utilisateur',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('identifiant_annuaire', models.TextField(blank=True, null=True, unique=True)),
                        ('matricule', models.TextField(blank=True, null=True, unique=True)),
                        ('nom', models.TextField()),
                        ('prenom', models.TextField()),
                        ('courriel', models.EmailField(blank=True, max_length=254, null=True, unique=True)),
                        ('telephone', models.TextField(blank=True, null=True)),
                        ('actif', models.BooleanField(default=True)),
                        ('derniere_connexion', models.DateTimeField(blank=True, null=True)),
                        ('mot_de_passe', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'utilisateur',
                        'ordering': ['nom', 'prenom'],
                    },
                ),
                migrations.CreateModel(
                    name='NiveauHierarchique',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('code', models.TextField(unique=True)),
                        ('libelle', models.TextField()),
                        ('rang', models.SmallIntegerField(help_text="1 = sommet de l'organigramme.")),
                        ('actif', models.BooleanField(default=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'verbose_name': 'niveau hierarchique',
                        'verbose_name_plural': 'niveaux hierarchiques',
                        'db_table': 'niveau_hierarchique',
                        'ordering': ['rang'],
                    },
                ),
                migrations.CreateModel(
                    name='Parametre',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('cle', models.TextField(help_text='activite.seuil_retard_points', unique=True)),
                        ('libelle', models.TextField()),
                        ('valeur', models.TextField()),
                        ('type_valeur', models.TextField(choices=[('entier', 'Entier'), ('decimal', 'Decimal'), ('texte', 'Texte'), ('booleen', 'Booleen')], default='entier')),
                        ('domaine', models.TextField(help_text='Pilier concerne : activite, courrier…')),
                        ('statut', models.TextField(choices=[('acte', 'Acte par le metier'), ('hypothese', 'Hypothese de travail — sans source documentaire')], default='hypothese', help_text="Une hypothese n'est pas une decision : elle attend une reponse du metier.")),
                        ('source', models.TextField(blank=True, help_text='Reference documentaire — « CDC §15 », « Decision D8 ». Vide si aucune.', null=True)),
                        ('a_trancher_par', models.TextField(blank=True, help_text='DSR, contrôle de gestion, Direction generale…', null=True)),
                        ('modifie_le', models.DateTimeField(auto_now=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'parametre',
                        'ordering': ['domaine', 'cle'],
                    },
                ),
                migrations.CreateModel(
                    name='Permission',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('code', models.TextField(unique=True)),
                        ('libelle', models.TextField()),
                        ('domaine', models.TextField()),
                    ],
                    options={
                        'db_table': 'permission',
                        'ordering': ['domaine', 'code'],
                    },
                ),
                migrations.CreateModel(
                    name='Profil',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('code', models.TextField(unique=True)),
                        ('libelle', models.TextField()),
                        ('description', models.TextField(blank=True, null=True)),
                        ('systeme', models.BooleanField(default=False, help_text="Profils initiaux, non supprimables. L'administrateur en cree d'autres.")),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'profil',
                        'ordering': ['libelle'],
                    },
                ),
                migrations.CreateModel(
                    name='SessionCourrier',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('code', models.TextField(choices=[('arrive', 'Courrier arrive'), ('depart', 'Courrier depart'), ('interne', 'Courrier interne'), ('confidentiel', 'Courrier confidentiel')], unique=True)),
                        ('libelle', models.TextField()),
                        ('sens', models.TextField()),
                        ('lit_toutes_sessions', models.BooleanField(default=False)),
                        ('actif', models.BooleanField(default=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'verbose_name': "session d'enregistrement",
                        'verbose_name_plural': "sessions d'enregistrement",
                        'db_table': 'session',
                    },
                ),
                migrations.CreateModel(
                    name='Delegation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nature', models.TextField(choices=[('remplacement', 'Remplacement'), ('delegation', 'Delegation')])),
                        ('debut', models.DateTimeField()),
                        ('fin', models.DateTimeField()),
                        ('motif', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('beneficiaire', models.ForeignKey(db_column='beneficiaire_id', on_delete=django.db.models.deletion.PROTECT, related_name='delegations_recues', to=settings.AUTH_USER_MODEL)),
                        ('titulaire', models.ForeignKey(db_column='titulaire_id', on_delete=django.db.models.deletion.PROTECT, related_name='delegations_accordees', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'delegation',
                    },
                ),
                migrations.CreateModel(
                    name='DelegationPermission',
                    fields=[
                        ('pk', models.CompositePrimaryKey('delegation_id', 'permission_id', blank=True, editable=False, primary_key=True, serialize=False)),
                        ('delegation', models.ForeignKey(db_column='delegation_id', on_delete=django.db.models.deletion.CASCADE, to='noyau.delegation')),
                        ('permission', models.ForeignKey(db_column='permission_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.permission')),
                    ],
                    options={
                        'db_table': 'delegation_permission',
                    },
                ),
                migrations.AddField(
                    model_name='delegation',
                    name='permissions',
                    field=models.ManyToManyField(related_name='delegations', through='noyau.DelegationPermission', to='noyau.permission'),
                ),
                migrations.CreateModel(
                    name='PieceJointe',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('objet_type', models.TextField(blank=True, null=True)),
                        ('objet_id', models.BigIntegerField(blank=True, null=True)),
                        ('courrier_id', models.BigIntegerField(blank=True, null=True)),
                        ('nom_fichier', models.TextField()),
                        ('nom_original', models.TextField()),
                        ('extension', models.TextField(blank=True, null=True)),
                        ('taille_octets', models.BigIntegerField()),
                        ('type_mime', models.TextField(blank=True, null=True)),
                        ('empreinte_sha256', models.TextField()),
                        ('chemin_stockage', models.TextField()),
                        ('categorie', models.TextField(choices=[('original', 'Original'), ('annexe', 'Annexe'), ('reponse', 'Reponse'), ('accuse', 'Accuse de reception'), ('justificatif', 'Justificatif')], default='annexe')),
                        ('version', models.SmallIntegerField(default=1)),
                        ('texte_reconnu', models.TextField(blank=True, help_text="Sortie de l'OCR — RF-IA-01.", null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('piece_precedente', models.ForeignKey(blank=True, db_column='piece_precedente_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='versions_suivantes', to='noyau.piecejointe')),
                    ],
                    options={
                        'verbose_name': 'piece jointe',
                        'verbose_name_plural': 'pieces jointes',
                        'db_table': 'piece_jointe',
                        'ordering': ['-cree_le'],
                    },
                ),
                migrations.CreateModel(
                    name='Poste',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('libelle', models.TextField()),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('niveau_hierarchique', models.ForeignKey(db_column='niveau_hierarchique_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.niveauhierarchique')),
                        ('poste_superieur', models.ForeignKey(blank=True, db_column='poste_superieur_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='subordonnes', to='noyau.poste')),
                    ],
                    options={
                        'db_table': 'poste',
                    },
                ),
                migrations.AddField(
                    model_name='utilisateur',
                    name='poste',
                    field=models.ForeignKey(blank=True, db_column='poste_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.poste'),
                ),
                migrations.CreateModel(
                    name='ProfilPermission',
                    fields=[
                        ('pk', models.CompositePrimaryKey('profil_id', 'permission_id', blank=True, editable=False, primary_key=True, serialize=False)),
                        ('permission', models.ForeignKey(db_column='permission_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.permission')),
                        ('profil', models.ForeignKey(db_column='profil_id', on_delete=django.db.models.deletion.CASCADE, to='noyau.profil')),
                    ],
                    options={
                        'db_table': 'profil_permission',
                    },
                ),
                migrations.AddField(
                    model_name='profil',
                    name='permissions',
                    field=models.ManyToManyField(related_name='profils', through='noyau.ProfilPermission', to='noyau.permission'),
                ),
                migrations.CreateModel(
                    name='Structure',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                        ('code', models.TextField(help_text='Sigle : DAF, DSI, DSR…')),
                        ('libelle', models.TextField()),
                        ('nature', models.TextField(choices=[('Direction', 'Direction'), ('Service', 'Service'), ('Division', 'Division'), ('Filiale', 'Filiale'), ('Succursale', 'Succursale')], default='Direction')),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('niveau_hierarchique', models.ForeignKey(db_column='niveau_hierarchique_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.niveauhierarchique')),
                        ('parent', models.ForeignKey(blank=True, db_column='parent_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'db_table': 'structure',
                        'ordering': ['code'],
                    },
                ),
                migrations.AddField(
                    model_name='poste',
                    name='structure',
                    field=models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure'),
                ),
                migrations.CreateModel(
                    name='Perimetre',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('portee', models.TextField(choices=[('propre', "Ce que l'agent traite lui-meme"), ('structure', 'Sa structure'), ('sous_arbre', 'Sa structure et ses descendants'), ('toutes', "Toute l'institution")])),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='perimetres', to=settings.AUTH_USER_MODEL)),
                        ('structure', models.ForeignKey(blank=True, db_column='structure_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'db_table': 'perimetre',
                    },
                ),
                migrations.AddField(
                    model_name='delegation',
                    name='perimetre_structure',
                    field=models.ForeignKey(blank=True, db_column='perimetre_structure_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.structure'),
                ),
                migrations.AddField(
                    model_name='utilisateur',
                    name='structure',
                    field=models.ForeignKey(blank=True, db_column='structure_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.structure'),
                ),
                migrations.CreateModel(
                    name='UtilisateurProfil',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('attribue_le', models.DateTimeField(auto_now_add=True)),
                        ('attribue_par', models.BigIntegerField(blank=True, null=True)),
                        ('retire_le', models.DateTimeField(blank=True, null=True)),
                        ('retire_par', models.BigIntegerField(blank=True, null=True)),
                        ('profil', models.ForeignKey(db_column='profil_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.profil')),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, related_name='profils', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'utilisateur_profil',
                    },
                ),
                migrations.CreateModel(
                    name='UtilisateurSession',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('attribue_le', models.DateTimeField(auto_now_add=True)),
                        ('attribue_par', models.BigIntegerField(blank=True, null=True)),
                        ('retire_le', models.DateTimeField(blank=True, null=True)),
                        ('retire_par', models.BigIntegerField(blank=True, null=True)),
                        ('session', models.ForeignKey(db_column='session_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.sessioncourrier')),
                        ('utilisateur', models.ForeignKey(db_column='utilisateur_id', on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'utilisateur_session',
                    },
                ),
            ]
        ),
    ]
