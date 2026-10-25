"""
Schema du pilier activites.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_activite.sql`, copie fidele du
script livre avec le modele de donnees — seules les trois lignes propres a psql
(`ON_ERROR_STOP`, `BEGIN`, `COMMIT`) en ont ete retirees, Django ouvrant
lui-meme la transaction.

La raison est la meme qu'au socle : le schema porte des constructions que l'ORM
ne sait pas exprimer et qu'il serait absurde de perdre. Ici, cinq declencheurs
qui tiennent des regles metier (code de l'activite sous verrou de ligne,
avancement pondere, refus d'avancement sur activite suspendue, coherence de
l'etat de suspension, historisation des champs), une vue `v_activite_etat`, des
index partiels, un index unique partiel garantissant une seule suspension
ouverte, et l'extension de `relance` a une seconde cible.

`SeparateDatabaseAndState` sert donc a **enregistrer l'etat** sans rien creer :
Django apprend l'existence des modeles, les tables existent deja. C'est la
decision 003 — une seule source de verite pour le schema.

La dependance a `noyau.0001_initial` n'est pas decorative : ce fichier
reference `structure`, `utilisateur` et `piece_jointe`, et modifie `relance`.

Ce fichier est assemble par `scripts/assembler_migration_pilier.py`. Un
`makemigrations` lance seul regenererait un fichier plat, sans le
`SeparateDatabaseAndState` ni le `RunSQL`, et les tables seraient creees deux
fois.
"""

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
    ]

    operations = [
        # 1. Le schema livre, a l'identique. Irreversible : on ne defait pas la
        #    creation d'un schema, on la recree.
        migrations.RunSQL(sql=_lire("0001_activite.sql"), reverse_sql=migrations.RunSQL.noop),
        # 2. Enregistrement de l'etat seul : aucune table n'est creee ici.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='VueActiviteEtat',
                    fields=[
                        ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                        ('paa_id', models.BigIntegerField()),
                        ('structure_id', models.BigIntegerField()),
                        ('etat_stocke', models.TextField()),
                        ('etat_affiche', models.TextField()),
                        ('avancement_calcule', models.DecimalField(decimal_places=2, max_digits=5)),
                        ('contrainte_echue', models.BooleanField()),
                    ],
                    options={
                        'verbose_name': "etat affiche d'une activite",
                        'verbose_name_plural': 'etats affiches des activites',
                        'db_table': 'v_activite_etat',
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='AxeStrategique',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('code', models.TextField(unique=True)),
                        ('libelle_court', models.TextField()),
                        ('libelle', models.TextField()),
                        ('ordre', models.SmallIntegerField()),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'verbose_name': 'axe strategique',
                        'verbose_name_plural': 'axes strategiques',
                        'db_table': 'axe_strategique',
                        'ordering': ['ordre'],
                    },
                ),
                migrations.CreateModel(
                    name='Exercice',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('annee', models.SmallIntegerField(unique=True)),
                        ('ouvert', models.BooleanField(default=True)),
                        ('ouvert_le', models.DateTimeField(auto_now_add=True)),
                        ('clos_le', models.DateTimeField(blank=True, null=True)),
                        ('clos_par', models.BigIntegerField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={
                        'db_table': 'exercice',
                        'ordering': ['-annee'],
                    },
                ),
                migrations.CreateModel(
                    name='Activite',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(editable=False, unique=True)),
                        ('code', models.TextField(editable=False, unique=True)),
                        ('intitule', models.TextField()),
                        ('objectif', models.TextField(blank=True, null=True)),
                        ('etat_reference', models.TextField(blank=True, null=True)),
                        ('resultats_attendus', models.TextField(blank=True, null=True)),
                        ('cible', models.TextField(blank=True, null=True)),
                        ('budget_valide', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                        ('budget_consomme', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                        ('date_debut', models.DateField()),
                        ('date_fin', models.DateField()),
                        ('etat', models.TextField(choices=[('en_cours', 'En cours'), ('realisee', 'Realisee'), ('suspendue', 'Suspendue')], default='en_cours')),
                        ('avancement_calcule', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                        ('derniere_relance_le', models.DateTimeField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('responsable', models.ForeignKey(db_column='responsable_id', on_delete=django.db.models.deletion.PROTECT, related_name='activites_dont_responsable', to=settings.AUTH_USER_MODEL)),
                        ('axe_strategique', models.ForeignKey(db_column='axe_strategique_id', on_delete=django.db.models.deletion.PROTECT, to='activite.axestrategique')),
                    ],
                    options={
                        'db_table': 'activite',
                        'ordering': ['code'],
                    },
                ),
                migrations.CreateModel(
                    name='ActiviteIndicateur',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('libelle', models.TextField()),
                        ('unite', models.TextField(blank=True, null=True)),
                        ('valeur_reference', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                        ('valeur_cible', models.DecimalField(decimal_places=4, max_digits=18)),
                        ('sens_decroissant', models.BooleanField(default=False)),
                        ('ordre', models.SmallIntegerField(default=1)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('activite', models.ForeignKey(db_column='activite_id', on_delete=django.db.models.deletion.CASCADE, related_name='indicateurs', to='activite.activite')),
                    ],
                    options={
                        'verbose_name': "indicateur d'activite",
                        'verbose_name_plural': "indicateurs d'activite",
                        'db_table': 'activite_indicateur',
                        'ordering': ['activite', 'ordre'],
                    },
                ),
                migrations.CreateModel(
                    name='CalendrierProduction',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nature', models.TextField(choices=[('rapport_mensuel', "Rapport mensuel d'activite"), ('proces_verbal', 'Proces-verbal de reunion'), ('rapport_sectoriel', 'Rapport sectoriel')])),
                        ('intitule', models.TextField()),
                        ('periodicite', models.TextField(choices=[('mensuelle', 'Mensuelle'), ('trimestrielle', 'Trimestrielle'), ('semestrielle', 'Semestrielle'), ('annuelle', 'Annuelle')])),
                        ('jour_echeance', models.SmallIntegerField(default=5)),
                        ('actif', models.BooleanField(default=True)),
                        ('valide_du', models.DateField()),
                        ('valide_au', models.DateField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': 'ligne de calendrier de production',
                        'verbose_name_plural': 'calendrier de production',
                        'db_table': 'calendrier_production',
                    },
                ),
                migrations.CreateModel(
                    name='DecisionReunion',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('reference', models.TextField(blank=True, null=True, unique=True)),
                        ('reunion_date', models.DateField()),
                        ('objet', models.TextField()),
                        ('texte', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('prise_par', models.ForeignKey(db_column='prise_par', on_delete=django.db.models.deletion.PROTECT, related_name='decisions_prises', to=settings.AUTH_USER_MODEL)),
                        ('saisie_par', models.ForeignKey(db_column='saisie_par', on_delete=django.db.models.deletion.PROTECT, related_name='decisions_saisies', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'decision de reunion',
                        'verbose_name_plural': 'decisions de reunion',
                        'db_table': 'decision_reunion',
                        'ordering': ['-reunion_date'],
                    },
                ),
                migrations.CreateModel(
                    name='ActiviteSuspension',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('motif', models.TextField()),
                        ('suspendu_le', models.DateTimeField(auto_now_add=True)),
                        ('repris_le', models.DateTimeField(blank=True, null=True)),
                        ('motif_reprise', models.TextField(blank=True, null=True)),
                        ('activite', models.ForeignKey(db_column='activite_id', on_delete=django.db.models.deletion.CASCADE, related_name='suspensions', to='activite.activite')),
                        ('repris_par', models.ForeignKey(blank=True, db_column='repris_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='suspensions_levees', to=settings.AUTH_USER_MODEL)),
                        ('suspendu_par', models.ForeignKey(db_column='suspendu_par', on_delete=django.db.models.deletion.PROTECT, related_name='suspensions_prononcees', to=settings.AUTH_USER_MODEL)),
                        ('decision_reunion', models.ForeignKey(blank=True, db_column='decision_reunion_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='activite.decisionreunion')),
                    ],
                    options={
                        'verbose_name': "suspension d'activite",
                        'verbose_name_plural': "suspensions d'activite",
                        'db_table': 'activite_suspension',
                        'ordering': ['-suspendu_le'],
                    },
                ),
                migrations.CreateModel(
                    name='AgregatActiviteJour',
                    fields=[
                        ('pk', models.CompositePrimaryKey('structure_id', 'exercice_id', 'jour', blank=True, editable=False, primary_key=True, serialize=False)),
                        ('jour', models.DateField()),
                        ('nb_total', models.IntegerField(default=0)),
                        ('nb_realisees', models.IntegerField(default=0)),
                        ('nb_en_cours', models.IntegerField(default=0)),
                        ('nb_en_retard', models.IntegerField(default=0)),
                        ('nb_suspendues', models.IntegerField(default=0)),
                        ('nb_critiques', models.IntegerField(default=0)),
                        ('taux_execution', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                        ('budget_valide', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                        ('budget_consomme', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                        ('calcule_le', models.DateTimeField(auto_now_add=True)),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                        ('exercice', models.ForeignKey(db_column='exercice_id', on_delete=django.db.models.deletion.PROTECT, to='activite.exercice')),
                    ],
                    options={
                        'verbose_name': "agregat d'activites du jour",
                        'verbose_name_plural': "agregats d'activites du jour",
                        'db_table': 'agregat_activite_jour',
                    },
                ),
                migrations.CreateModel(
                    name='IndicateurMesure',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('date_mesure', models.DateField()),
                        ('valeur_atteinte', models.DecimalField(decimal_places=4, max_digits=18)),
                        ('commentaire', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('activite_indicateur', models.ForeignKey(db_column='activite_indicateur_id', on_delete=django.db.models.deletion.CASCADE, related_name='mesures', to='activite.activiteindicateur')),
                        ('saisie_par', models.ForeignKey(db_column='saisie_par', on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': "mesure d'indicateur",
                        'verbose_name_plural': "mesures d'indicateur",
                        'db_table': 'indicateur_mesure',
                        'ordering': ['-date_mesure'],
                    },
                ),
                migrations.CreateModel(
                    name='InstructionActivite',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('origine', models.TextField(choices=[('instruction_verbale', 'Instruction verbale'), ('decision_dg', 'Decision du Directeur General')], default='instruction_verbale')),
                        ('date_instruction', models.DateField()),
                        ('texte', models.TextField()),
                        ('echeance', models.DateField()),
                        ('levee_le', models.DateTimeField(blank=True, null=True)),
                        ('commentaire_levee', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('activite', models.ForeignKey(db_column='activite_id', on_delete=django.db.models.deletion.CASCADE, related_name='instructions', to='activite.activite')),
                        ('decision_reunion', models.ForeignKey(blank=True, db_column='decision_reunion_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='activite.decisionreunion')),
                        ('donnee_par', models.ForeignKey(blank=True, db_column='donnee_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='instructions_donnees', to=settings.AUTH_USER_MODEL)),
                        ('enregistree_par', models.ForeignKey(db_column='enregistree_par', on_delete=django.db.models.deletion.PROTECT, related_name='instructions_enregistrees', to=settings.AUTH_USER_MODEL)),
                        ('levee_par', models.ForeignKey(blank=True, db_column='levee_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='instructions_levees', to=settings.AUTH_USER_MODEL)),
                        ('responsable', models.ForeignKey(db_column='responsable_id', on_delete=django.db.models.deletion.PROTECT, related_name='instructions_dont_responsable', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'instruction sur activite',
                        'verbose_name_plural': 'instructions sur activite',
                        'db_table': 'instruction_activite',
                        'ordering': ['echeance'],
                    },
                ),
                migrations.CreateModel(
                    name='Obligation',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('intitule', models.TextField()),
                        ('periode_libelle', models.TextField()),
                        ('periode_debut', models.DateField()),
                        ('periode_fin', models.DateField()),
                        ('echeance', models.DateField()),
                        ('depose_le', models.DateField(blank=True, null=True)),
                        ('commentaire', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('calendrier_production', models.ForeignKey(db_column='calendrier_production_id', on_delete=django.db.models.deletion.PROTECT, related_name='obligations', to='activite.calendrierproduction')),
                        ('depose_par', models.ForeignKey(blank=True, db_column='depose_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='obligations_deposees', to=settings.AUTH_USER_MODEL)),
                        ('piece_jointe', models.ForeignKey(blank=True, db_column='piece_jointe_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='noyau.piecejointe')),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'db_table': 'obligation',
                        'ordering': ['-echeance'],
                    },
                ),
                migrations.CreateModel(
                    name='PlanActions',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('uid', models.UUIDField(editable=False, unique=True)),
                        ('version', models.SmallIntegerField(default=1)),
                        ('statut', models.TextField(choices=[('brouillon', 'Brouillon'), ('soumis', 'Soumis au controle de gestion'), ('valide', 'Valide'), ('retourne', 'Retourne')], default='brouillon')),
                        ('soumis_le', models.DateTimeField(blank=True, null=True)),
                        ('soumis_par', models.BigIntegerField(blank=True, null=True)),
                        ('valide_le', models.DateTimeField(blank=True, null=True)),
                        ('valide_par', models.BigIntegerField(blank=True, null=True)),
                        ('motif_retour', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('exercice', models.ForeignKey(db_column='exercice_id', on_delete=django.db.models.deletion.PROTECT, to='activite.exercice')),
                        ('structure', models.ForeignKey(db_column='structure_id', on_delete=django.db.models.deletion.PROTECT, to='noyau.structure')),
                    ],
                    options={
                        'verbose_name': "plan d'actions annuel",
                        'verbose_name_plural': "plans d'actions annuels",
                        'db_table': 'paa',
                    },
                ),
                migrations.AddField(
                    model_name='activite',
                    name='plan',
                    field=models.ForeignKey(db_column='paa_id', on_delete=django.db.models.deletion.PROTECT, related_name='activites', to='activite.planactions'),
                ),
                migrations.CreateModel(
                    name='PlanActionsVersion',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('version', models.SmallIntegerField()),
                        ('statut', models.TextField()),
                        ('motif', models.TextField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('plan', models.ForeignKey(db_column='paa_id', on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='activite.planactions')),
                    ],
                    options={
                        'verbose_name': 'version de plan',
                        'verbose_name_plural': 'versions de plan',
                        'db_table': 'paa_version',
                        'ordering': ['plan', 'version'],
                    },
                ),
                migrations.CreateModel(
                    name='Tache',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('intitule', models.TextField()),
                        ('date_echeance', models.DateField(blank=True, null=True)),
                        ('poids', models.SmallIntegerField(default=1)),
                        ('etat', models.TextField(choices=[('a_faire', 'A faire'), ('en_cours', 'En cours'), ('faite', 'Faite')], default='a_faire')),
                        ('fait_le', models.DateField(blank=True, null=True)),
                        ('ordre', models.SmallIntegerField(default=1)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('modifie_le', models.DateTimeField(blank=True, null=True)),
                        ('modifie_par', models.BigIntegerField(blank=True, null=True)),
                        ('invalide_le', models.DateTimeField(blank=True, null=True)),
                        ('invalide_par', models.BigIntegerField(blank=True, null=True)),
                        ('activite', models.ForeignKey(db_column='activite_id', on_delete=django.db.models.deletion.CASCADE, related_name='taches', to='activite.activite')),
                        ('responsable', models.ForeignKey(blank=True, db_column='responsable_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='taches_dont_responsable', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'tache',
                        'ordering': ['activite', 'ordre'],
                    },
                ),
                migrations.CreateModel(
                    name='DecisionEffet',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nature', models.TextField(choices=[('planning', 'Modification du planning'), ('priorite', 'Modification des priorites'), ('acceleration', 'Acceleration'), ('suspension', 'Suspension'), ('creation_tache', 'Creation de taches')])),
                        ('valeur_avant', models.JSONField(blank=True, null=True)),
                        ('valeur_apres', models.JSONField(blank=True, null=True)),
                        ('applique_le', models.DateTimeField(blank=True, null=True)),
                        ('cree_le', models.DateTimeField(auto_now_add=True)),
                        ('cree_par', models.BigIntegerField(blank=True, null=True)),
                        ('activite', models.ForeignKey(blank=True, db_column='activite_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='activite.activite')),
                        ('applique_par', models.ForeignKey(blank=True, db_column='applique_par', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='effets_appliques', to=settings.AUTH_USER_MODEL)),
                        ('decision_reunion', models.ForeignKey(db_column='decision_reunion_id', on_delete=django.db.models.deletion.CASCADE, related_name='effets', to='activite.decisionreunion')),
                        ('tache', models.ForeignKey(blank=True, db_column='tache_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='activite.tache')),
                    ],
                    options={
                        'verbose_name': 'effet de decision',
                        'verbose_name_plural': 'effets de decision',
                        'db_table': 'decision_effet',
                    },
                ),
            ]
        ),
    ]
