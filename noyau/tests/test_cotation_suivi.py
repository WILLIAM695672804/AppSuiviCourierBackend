"""
La cotation pour suivi — A7.

Ce que ces tests doivent prouver tient en trois points :

 * la designation vise une **personne**, et une seule a la fois ;
 * elle se **date**, elle ne s'efface pas — savoir qui suivait le courrier le
   jour ou la relance est partie est tout l'objet de la table ;
 * elle **ouvre un acces hors de sa structure**, ce qui est la raison d'etre de
   la troisieme porte de la regle de visibilite.

Les insertions passent par du SQL direct : aucun modele ne couvre `cotation` ni
`courrier` tant que le pilier courrier n'est pas commence.
"""

import pytest
from django.db import IntegrityError, connection, transaction

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import NiveauHierarchique, Structure
from noyau.perimetre.designation import courriers_suivis, suit, suiveur


@pytest.fixture
def courrier(db):
    """
    Un courrier enregistre et cote, le minimum pour qu'un suivi existe.

    Tout est en SQL : c'est le prix a payer pour eprouver une table du pilier
    courrier avant que le pilier n'existe. Le jour ou il existera, cette
    fixture deviendra trois appels d'ORM.
    """
    niveau = NiveauHierarchique.objects.get(code="DIR")
    dsi = Structure.objects.create(
        code="DSI",
        libelle="Systemes d'information",
        niveau_hierarchique=niveau,
        valide_du="2026-01-01",
    )
    daf = Structure.objects.create(
        code="DAF",
        libelle="Affaires financieres",
        niveau_hierarchique=niveau,
        valide_du="2026-01-01",
    )
    dg = Utilisateur.objects.create(nom="Kingue", prenom="Emmanuel")
    # Le suiveur est a la DAF, le courrier cote a la DSI : c'est exactement le
    # cas que la porte « designation » doit rendre visible.
    suiveur_ = Utilisateur.objects.create(nom="Etoa", prenom="Nadege", structure=daf)
    traitant = Utilisateur.objects.create(nom="Manga", prenom="Yves", structure=dsi)

    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO courrier (numero, sens, session_id, date_courrier,
                                  expediteur_libelle, objet, statut_courrier, cree_par)
            VALUES ('ARR-2026-0001', 'arrive',
                    (SELECT id FROM session WHERE code = 'arrive'),
                    CURRENT_DATE, 'Societe ABC', 'Demande de raccordement',
                    'en_cours', %s)
            RETURNING id
            """,
            [dg.pk],
        )
        courrier_id = curseur.fetchone()[0]

        curseur.execute(
            """
            INSERT INTO cotation (courrier_id, decide_par, decide_le, saisi_par)
            VALUES (%s, %s, now(), %s) RETURNING id
            """,
            [courrier_id, dg.pk, dg.pk],
        )
        cotation_id = curseur.fetchone()[0]

    return {
        "courrier": courrier_id,
        "cotation": cotation_id,
        "dg": dg,
        "suiveur": suiveur_,
        "traitant": traitant,
    }


def _designer(cotation_id: int, utilisateur: Utilisateur, designe_par: Utilisateur) -> int:
    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO cotation_suivi (cotation_id, utilisateur_id, designe_par)
            VALUES (%s, %s, %s) RETURNING id
            """,
            [cotation_id, utilisateur.pk, designe_par.pk],
        )
        return curseur.fetchone()[0]


# =====================================================================
#  Ce que le modele garantit
# =====================================================================


def test_le_suivi_est_confie_a_une_personne_et_non_a_une_structure(courrier):
    """
    C'est ce qui distingue cette cotation de l'autre. La table ne porte
    volontairement **aucune** colonne `structure_id` — en ajouter une ferait
    du suivi une seconde cotation operationnelle.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'cotation_suivi'
            """
        )
        colonnes = {ligne[0] for ligne in curseur.fetchall()}

    assert "utilisateur_id" in colonnes
    assert "structure_id" not in colonnes


def test_un_seul_suiveur_a_la_fois(courrier):
    """
    Deux designations ouvertes laisseraient sans reponse la question « qui rend
    compte au DG ? ». La contrainte est au moteur : aucun code applicatif ne la
    tient sous concurrence.
    """
    _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])
    with pytest.raises(IntegrityError), transaction.atomic():
        _designer(courrier["cotation"], courrier["traitant"], courrier["dg"])


def test_retirer_une_designation_la_date_sans_l_effacer(courrier):
    """
    RNF-TRACE-01. Savoir qui suivait le courrier le jour ou la relance est
    partie est tout l'objet de la table.
    """
    designation = _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])
    with connection.cursor() as curseur:
        # `app.utilisateur_id` : la table est historisee, comme les six autres.
        curseur.execute(
            "SELECT set_config('app.utilisateur_id', %s, true)", [str(courrier["dg"].pk)]
        )
        curseur.execute(
            "UPDATE cotation_suivi SET retire_le = now(), retire_par = %s WHERE id = %s",
            [courrier["dg"].pk, designation],
        )
        curseur.execute("SELECT count(*) FROM cotation_suivi WHERE id = %s", [designation])
        assert curseur.fetchone()[0] == 1  # datee, pas supprimee


def test_un_retrait_sans_auteur_est_refuse(courrier):
    """Qui a retire la designation compte autant que qui l'a posee."""
    designation = _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as curseur:
        curseur.execute(
            "SELECT set_config('app.utilisateur_id', %s, true)", [str(courrier["dg"].pk)]
        )
        curseur.execute("UPDATE cotation_suivi SET retire_le = now() WHERE id = %s", [designation])


# =====================================================================
#  La troisieme porte de la visibilite
# =====================================================================


def test_le_suiveur_voit_le_courrier_hors_de_sa_structure(courrier):
    """
    **La raison d'etre de cette porte.** Le suiveur est a la DAF, le courrier
    est cote a la DSI. Sans la designation, son perimetre ne lui montrerait
    rien — et il ne pourrait pas coordonner ce dont il rend compte au DG.
    """
    _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])

    assert suit(courrier["suiveur"], courrier["courrier"]) is True
    assert courriers_suivis(courrier["suiveur"]) == {courrier["courrier"]}
    # Le traitant, lui, ne suit rien : il traite. Deux gestes distincts.
    assert suit(courrier["traitant"], courrier["courrier"]) is False


def test_une_designation_retiree_ne_donne_plus_a_voir(courrier):
    """Sans quoi un agent qui a suivi un courrier il y a trois ans le verrait
    encore."""
    designation = _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT set_config('app.utilisateur_id', %s, true)", [str(courrier["dg"].pk)]
        )
        curseur.execute(
            "UPDATE cotation_suivi SET retire_le = now(), retire_par = %s WHERE id = %s",
            [courrier["dg"].pk, designation],
        )

    assert courriers_suivis(courrier["suiveur"]) == set()
    assert suiveur(courrier["courrier"]) is None


def test_la_relance_part_vers_le_suiveur(courrier):
    """
    Consequence pratique de la regle : les relances passent par la personne de
    suivi, **pas par le chef de file**. Un commentaire de code qui dit
    l'inverse est perime.
    """
    _designer(courrier["cotation"], courrier["suiveur"], courrier["dg"])
    assert suiveur(courrier["courrier"]) == courrier["suiveur"].pk


def test_un_courrier_sans_designation_n_a_pas_de_suiveur(courrier):
    """La cotation pour suivi n'est pas obligatoire : tous les courriers ne
    demandent pas une coordination au-dessus du chef de file."""
    assert suiveur(courrier["courrier"]) is None
