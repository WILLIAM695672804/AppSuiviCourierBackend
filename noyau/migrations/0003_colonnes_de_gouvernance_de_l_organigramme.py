"""
Ce que chaque etage de l'organigramme autorise — F-02 / F-03.

L'ecran `/organisation` administre depuis le premier jour quatre proprietes du
niveau hierarchique — coter, recevoir une cotation, porter la signature,
apparaitre au tableau statistique — et un rattachement entre niveaux. Aucune
n'existait en base : la table `niveau_hierarchique` du socle porte un code, un
libelle et un rang, rien d'autre.

**Pourquoi le niveau et non la structure.** Que l'etage « Direction » porte la
signature des courriers depart est une regle d'institution ; que la DAF la porte
est une consequence. Poser ces booleens sur `structure` aurait oblige a les
recopier sur chaque direction, avec la certitude qu'une nouvelle direction
serait creee sans, et signerait — ou ne signerait pas — sans que personne ne
l'ait decide.

**Les valeurs initiales sont une hypothese**, consignee en A21. Trois sont
deduites du descriptif : la signature appartient a la Direction generale (B-04),
tout etage recoit une cotation, et le rattachement des niveaux suit le rang. La
quatrieme — qui peut coter — retient « tout etage sauf la feuille », ce qui
n'est ecrit nulle part. Elle est modifiable a l'ecran ; elle n'est encore lue
par rien, le pilier courrier n'existant pas.

`profil_par_defaut` et `effectif_prevu` completent le poste. Le premier est une
**proposition** a la creation d'un compte, jamais une attribution : un profil
qui suivrait l'organigramme tout seul donnerait des droits que personne n'a
decides. Le second rend visible le poste vacant, qui est un trou dans le
circuit.
"""

import django.db.models.deletion
from django.db import migrations, models

#: Le rang de chaque niveau, dans l'ordre du socle. Sert au chainage.
RANGS = ["DG", "DIR", "DEP", "SERV"]


def poser_les_valeurs_initiales(apps, schema_editor):
    """
    Chaine les niveaux et pose ce qu'ils autorisent.

    Le chainage suit le rang parce que c'est ainsi que le socle les a semes —
    un etage se place sous celui qui le precede. Ce n'est vrai que du semis
    initial : un administrateur qui insere un etage entre deux autres devra
    reprendre le rattachement lui-meme, et l'ecran le lui demande.
    """
    Niveau = apps.get_model("noyau", "NiveauHierarchique")

    precedent = None
    for code in RANGS:
        niveau = Niveau.objects.filter(code=code).first()
        if niveau is None:
            # Le socle a ete modifie : on ne devine pas a sa place.
            continue

        niveau.niveau_parent = precedent
        niveau.peut_coter = code != "SERV"
        niveau.peut_recevoir_cotation = True
        niveau.porte_signature = code == "DG"
        niveau.ligne_statistiques = True
        niveau.save(
            update_fields=[
                "niveau_parent",
                "peut_coter",
                "peut_recevoir_cotation",
                "porte_signature",
                "ligne_statistiques",
            ]
        )
        precedent = niveau


def rien_a_defaire(apps, schema_editor):
    """Les colonnes disparaissent avec le `RemoveField` : rien a remettre."""


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0002_cotation_suivi"),
    ]

    operations = [
        migrations.AddField(
            model_name="niveauhierarchique",
            name="niveau_parent",
            field=models.ForeignKey(
                blank=True,
                db_column="niveau_parent_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="niveaux_enfants",
                to="noyau.niveauhierarchique",
            ),
        ),
        migrations.AddField(
            model_name="niveauhierarchique",
            name="peut_coter",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="niveauhierarchique",
            name="peut_recevoir_cotation",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="niveauhierarchique",
            name="porte_signature",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="niveauhierarchique",
            name="ligne_statistiques",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="poste",
            name="effectif_prevu",
            field=models.SmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="poste",
            name="profil_par_defaut",
            field=models.ForeignKey(
                blank=True,
                db_column="profil_par_defaut_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="postes",
                to="noyau.profil",
            ),
        ),
        migrations.RunPython(poser_les_valeurs_initiales, rien_a_defaire),
    ]
