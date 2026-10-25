"""
Les trois reglages du tableau de relance (C-02).

Le pilier suivi n'avait aucune route servie : trois ecrans appelaient huit
adresses inexistantes. Il s'ouvre par le tableau de relance, et ce tableau pose
trois valeurs qu'aucun document ne fixe — le seuil du retard grave, ce qu'est un
niveau d'escalade, et la fenetre du taux de respect.

Elles vont en base et non en constantes Python pour la raison habituelle : une
valeur inventee doit etre **visible et corrigible** sans redeploiement, et son
statut `hypothese` dit a qui la lit qu'elle attend un arbitrage. Voir A76, A77 et
A78 de `docs/questions-ouvertes.md`.

Aucun changement de schema : la table `parametre` existe depuis `0001`, et les
lignes ne sont pas un etat que Django enregistre. `RunSQL` seul, donc, sans
`SeparateDatabaseAndState`.

`reverse_sql` en `noop` : supprimer un parametre que l'exploitation a pu corriger
entre-temps effacerait une decision. Cela s'ecrit dans une migration a soi.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


class Migration(migrations.Migration):
    dependencies = [("noyau", "0021_profil_cabinet")]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0022_parametres_suivi_relance.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
