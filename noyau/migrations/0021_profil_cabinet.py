"""
Le profil « Cabinet du Directeur general », et le rattrapage des comptes.

**L'arbitrage.** 28 aout 2026, par l'utilisateur, en toutes lettres : « c'est
chez moi que l'on enregistre et que l'on cote les ordres du directeur, car le
directeur ne le fait pas ». Il tranche la question A75 de
`docs/questions-ouvertes.md`, ouverte le matin meme, ou le cabinet ne voyait
aucun des 61 courriers du registre.

Le cabinet n'assiste pas le Directeur general : il fait le geste a sa place.
D'ou `ENR` et `COT_DEL`, qu'un responsable de structure n'a pas — et d'ou la
portee `toutes`, parce qu'on ne prepare pas la cotation d'un courrier qu'on ne
voit pas.

**Le rattrapage est cible et non general.** `RunPython` ne touche que les
comptes rattaches a la structure `CAB` elle-meme, et qui portent deja un profil.
Pas son sous-arbre : le Service du courrier central et les deux secretariats y
sont rattaches, et ce sont des agents de session, dont le perimetre doit rester
borne. Poser la
donnee dans le semis aurait suffi pour une base neuve, mais aurait laisse la
base de developpement — et demain la base reelle — dans l'etat qui a motive
l'arbitrage. Le semis porte la meme regle, pour les bases a venir.

Le profil `RESP` n'est pas retire : le chef de service du cabinet reste
responsable de sa structure, et les permissions s'additionnent. Lui oter `COT`
lui interdirait de coter en propre ce qui releve du cabinet lui-meme.

`reverse_sql` en `noop` : defaire une habilitation accordee se decide et
s'ecrit dans une migration a soi.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"

#: La structure du cabinet, **elle seule**.
#:
#: Pas son sous-arbre : le Service du courrier central et les deux secretariats
#: y sont rattaches, et ce sont des agents de session. Leur habilitation est le
#: rattachement a un registre (ADR 024), pas la portee ; leur ouvrir le registre
#: entier aurait echange une regle de securite contre une autre, sans que
#: personne ne l'ait demande. Un premier jet l'a fait, et il a fallu le defaire.
CODE_CABINET = "CAB"

PORTEE_TOUTES = "toutes"


def poser_le_cabinet(apps, schema_editor):
    """
    Attribue `CABINET` aux comptes du cabinet, et ouvre leur perimetre.

    Sans elargissement du perimetre, la permission ne servirait a rien : `ENR`
    dit ce que l'agent a le droit de faire, la portee dit sur quoi. Le cabinet
    en portee `sous_arbre` aurait pu enregistrer un courrier qu'il n'aurait pas
    revu ensuite — c'est exactement l'ecran vide qui a motive l'arbitrage.
    """
    Structure = apps.get_model("noyau", "Structure")
    Utilisateur = apps.get_model("noyau", "Utilisateur")
    Profil = apps.get_model("noyau", "Profil")
    UtilisateurProfil = apps.get_model("noyau", "UtilisateurProfil")
    Perimetre = apps.get_model("noyau", "Perimetre")

    cabinet = Structure.objects.filter(code=CODE_CABINET, valide_au__isnull=True).first()
    profil = Profil.objects.filter(code="CABINET").first()
    if cabinet is None or profil is None:
        return

    for utilisateur in Utilisateur.objects.filter(structure_id=cabinet.pk, actif=True):
        deja = UtilisateurProfil.objects.filter(
            utilisateur=utilisateur, profil=profil, retire_le__isnull=True
        ).exists()
        # Un compte sans aucun profil n'est pas un compte du cabinet a qui l'on
        # ouvre le registre : c'est un compte que personne n'a encore habilite.
        porte_un_profil = UtilisateurProfil.objects.filter(
            utilisateur=utilisateur, retire_le__isnull=True
        ).exists()
        if deja or not porte_un_profil:
            continue

        UtilisateurProfil.objects.create(utilisateur=utilisateur, profil=profil)
        Perimetre.objects.filter(utilisateur=utilisateur, valide_au__isnull=True).update(
            portee=PORTEE_TOUTES, structure=None
        )


class Migration(migrations.Migration):
    dependencies = [("noyau", "0020_recherche_correspondant_hybride")]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0021_profil_cabinet.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(poser_le_cabinet, migrations.RunPython.noop),
    ]
