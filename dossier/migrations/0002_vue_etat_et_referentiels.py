"""
La vue de l'etat affiche, et les deux referentiels du pilier.

**Ce qui est seme et pourquoi.**

Les *modeles de courrier* (RF-SUI-05) sont semes parce que la bibliotheque
vide n'est pas un etat de depart acceptable : « Generer un courrier » sur une
bibliotheque vide se lit comme une panne, et le premier reflexe d'un agent est
alors de reprendre son traitement de texte — c'est-a-dire de sortir de l'outil
qu'on vient d'installer. Les corps semes sont **plausibles et non officiels** :
ils sont a confronter au formalisme du courrier du PAD avant la mise en
service. Voir A35.

Les *regles d'affectation* (RF-BPM-02) ne sont **pas** semees avec une
structure. Elles ne le peuvent pas : l'organigramme d'essai ne porte ni service
du domaine, ni service du contentieux, et rattacher l'instruction des
autorisations domaniales a la DSI parce qu'elle existe aurait ouvert un circuit
a une structure qui n'a rien a y faire. C'est le meme constat que pour les
points du chenal (A27). Un dossier ouvert sans regle applicable arrive donc
**a la structure de l'agent qui l'ouvre**, et la fiche le dit en toutes
lettres. Voir A36.

`RunSQL` pour la vue et les modeles, comme les autres semis de reference du
depot : les melanger avec du `RunPython` obligerait a chercher dans deux
endroits ce qui peuple une table.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("dossier", "0001_initial"),
        # La vue lit `complement_dossier` et `evenement` : la seconde vient du
        # socle, et sans cette dependance l'ordre des migrations n'est pas
        # garanti sur une base neuve.
        ("noyau", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0002_vue_etat.sql"),
            reverse_sql="DROP VIEW IF EXISTS v_dossier_etat;",
        ),
        migrations.RunSQL(
            sql=_lire("0002_modeles_courrier.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
