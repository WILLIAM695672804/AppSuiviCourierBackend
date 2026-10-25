"""
L'affectation d'un agent a un poste devient datee — F-04.

**Ce qui manquait.** `utilisateur.poste` dit qui occupe quel poste
*aujourd'hui*, et rien d'autre. La question « qui tenait le poste de chef de la
DSR le 12 mars ? » n'avait aucune reponse : muter un agent ecrasait la colonne,
et l'occupant precedent disparaissait sans laisser de trace.

C'est le meme trou que `utilisateur_profil` a comble pour les droits
(RNF-TRACE-01), et il compte davantage ici : la hierarchie du circuit se lit
par le poste (principe 2 de `modeles.py`). Un courrier valide en mars par « le
chef de la DSR » se relit avec l'occupant de decembre tant que l'histoire n'est
pas ecrite quelque part.

**La colonne reste.** Elle n'est pas remplacee par une jointure : sept ecrans
la lisent, le perimetre `poste` s'appuie dessus, et une jointure sur intervalle
a chaque requete de liste couterait sans rien apprendre. La colonne est le
present, la table est l'histoire, et `organisation.services.affecter` ecrit les
deux dans la meme transaction — c'est le seul point qui touche l'une ou
l'autre.

**Le semis de l'existant.** Chaque agent deja en poste recoit une ligne ouverte,
datee de la creation de son compte. C'est une approximation, et elle est
assumee : la seule autre option honnete etait de laisser l'histoire vide, ce qui
aurait fait croire que personne n'a jamais occupe de poste avant aujourd'hui.
Une date fausse se corrige ; une absence se lit comme un fait.
"""

import django.db.models.deletion
from django.db import migrations, models


def semer_les_affectations_en_cours(apps, schema_editor):
    """Ouvre une ligne pour chaque agent deja en poste."""
    Utilisateur = apps.get_model("noyau", "Utilisateur")
    AffectationPoste = apps.get_model("noyau", "AffectationPoste")

    lignes = [
        AffectationPoste(
            utilisateur_id=agent.pk,
            poste_id=agent.poste_id,
            # La date de creation du compte, faute de mieux. Voir la docstring.
            debut=agent.cree_le.date(),
            fin=None,
            motif=None,
        )
        for agent in Utilisateur.objects.filter(poste__isnull=False).only("id", "poste_id")
    ]
    AffectationPoste.objects.bulk_create(lignes)


def oublier_les_affectations(apps, schema_editor):
    apps.get_model("noyau", "AffectationPoste").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("noyau", "0008_parametres_portail_supervision")]

    operations = [
        migrations.CreateModel(
            name="AffectationPoste",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("debut", models.DateField()),
                ("fin", models.DateField(blank=True, null=True)),
                ("motif", models.TextField(blank=True, null=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("cree_par", models.BigIntegerField(blank=True, null=True)),
                ("modifie_le", models.DateTimeField(blank=True, null=True)),
                ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                (
                    "poste",
                    models.ForeignKey(
                        db_column="poste_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="affectations",
                        to="noyau.poste",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        db_column="utilisateur_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="affectations",
                        to="noyau.utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "affectation a un poste",
                "verbose_name_plural": "affectations aux postes",
                "db_table": "affectation_poste",
                "ordering": ["-debut", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="affectationposte",
            index=models.Index(fields=["poste", "-debut"], name="idx_affectation_poste"),
        ),
        migrations.AddConstraint(
            model_name="affectationposte",
            constraint=models.CheckConstraint(
                condition=models.Q(("fin__isnull", True))
                | models.Q(("fin__gte", models.F("debut"))),
                name="affectation_fin_apres_debut",
            ),
        ),
        migrations.AddConstraint(
            model_name="affectationposte",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fin__isnull", True)),
                fields=("utilisateur",),
                name="une_seule_affectation_ouverte_par_agent",
            ),
        ),
        migrations.RunPython(semer_les_affectations_en_cours, oublier_les_affectations),
    ]
