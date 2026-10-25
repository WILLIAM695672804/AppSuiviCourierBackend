"""
Ecritures sur les referentiels de saisie — pour l'instant, le carnet d'adresses.

**Pourquoi une creation depuis l'ecran d'enregistrement.** Le selecteur
d'expediteur ne laisse pas taper un nom au clavier : c'est ainsi qu'un meme
ministere finit ecrit de six manieres et que les statistiques par correspondant
deviennent fausses. Mais un carnet ferme arrete l'agent devant un courrier qu'il
tient en main, quand l'expediteur n'y figure pas encore. La creation est donc
ouverte a qui enregistre — et **tracee**, ce qui est la contrepartie : le
referentiel grossit sous le controle de l'administrateur fonctionnel, qui voit
au journal qui a cree quoi.

Le doublon est refuse sur la designation, accents et casse ignores : c'est la
seule chose que le referentiel existe pour empecher, et l'ecran de recherche ne
suffit pas — `to_tsvector` n'indexe pas les prefixes, donc « minis » ne trouve
pas « Ministere », et l'agent conclut de bonne foi que l'entree manque.
"""

import re

from django.db import connection, transaction

from noyau.erreurs import ErreurMetier
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.parametrage.modeles import Correspondant

#: Les quatre types du socle (`correspondant_type_valide`). La liste est ici et
#: non deduite du modele : une valeur hors de cette liste est refusee par le
#: moteur, avec un message que l'agent ne peut pas lire.
TYPES = {code for code, _ in Correspondant.TYPES}


def creer_correspondant(
    acteur: Utilisateur,
    *,
    type: str,
    raison_sociale: str = "",
    nom: str = "",
    prenom: str = "",
    sigle: str = "",
    adresse: str = "",
    ville: str = "",
    courriel: str = "",
    telephone: str = "",
) -> Correspondant:
    """
    Inscrit une entree au carnet d'adresses.

    `raison_sociale` **ou** `nom` : la contrainte `correspondant_identite` du
    socle exige l'un des deux. Une administration n'a pas de prenom, une
    personne physique n'a pas de raison sociale, et forcer les deux aurait
    produit des lignes remplies de tirets.
    """
    if type not in TYPES:
        raise ErreurMetier(
            f"Type de correspondant inconnu : « {type} ».", code="type_inconnu", statut=422
        )

    raison_sociale = _normaliser(raison_sociale)
    nom = _normaliser(nom)
    prenom = _normaliser(prenom)
    sigle = _normaliser(sigle).upper().replace(" ", "")

    if not raison_sociale and not nom:
        # 422 et non 409 : ce n'est pas l'etat du systeme qui refuse, c'est la
        # saisie qui est incomplete. Le front corrige dans le formulaire.
        raise ErreurMetier(
            "Un correspondant se designe par une raison sociale ou par un nom.",
            code="identite_manquante",
            statut=422,
        )

    designation = raison_sociale or f"{nom} {prenom}".strip()
    _refuser_doublon(designation, sigle)

    with transaction.atomic():
        correspondant = Correspondant.objects.create(
            type=type,
            raison_sociale=raison_sociale or None,
            nom=nom or None,
            prenom=prenom or None,
            sigle=sigle or None,
            adresse=_normaliser(adresse) or None,
            ville=_normaliser(ville) or None,
            courriel=_normaliser(courriel).lower() or None,
            telephone=_normaliser(telephone) or None,
            cree_par=acteur.pk,
        )

        # Journalise sous `correspondant` et non sous `courrier` : le carnet
        # d'adresses n'appartient a aucun courrier, meme lorsque c'est en
        # enregistrant l'un d'eux que l'entree a ete creee (RNF-TRACE-01).
        inscrire(
            acteur=acteur,
            objet_type="correspondant",
            objet_id=correspondant.pk,
            type_evenement="correspondant_cree",
            libelle=f"Correspondant « {designation} » cree au referentiel",
            donnees={"type": type, "designation": designation, "sigle": sigle or None},
        )

    return correspondant


#: Les espaces de toute nature, y compris insecables, reduits a un seul.
_ESPACES = re.compile(r"\s+")

#: Les apostrophes typographiques que produisent les traitements de texte, d'ou
#: viennent la plupart des noms colles ici. Ramenees a l'apostrophe droite : deux
#: caracteres differents feraient deux correspondants pour « N'Djamena ».
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "`": "'"})


def _normaliser(texte: str) -> str:
    """
    Ce qui est ecrit une fois est lu mille fois.

    La normalisation sert autant la detection de doublon que la recherche : deux
    entrees qui ne different que par une espace double ou une apostrophe courbe
    sont le meme correspondant, et rien a l'ecran ne le montrerait.
    """
    return _ESPACES.sub(" ", texte.translate(_APOSTROPHES)).strip()


def _refuser_doublon(designation: str, sigle: str) -> None:
    """
    Deux entrees de meme nom feraient deux histoires pour un seul
    correspondant : chacune porterait la moitie de ses courriers, et le compte
    « 14 courriers recus » que l'agent lit dans le selecteur serait faux pour les
    deux.

    **La comparaison passe par `texte_recherche()`, la fonction du socle qui
    sert la recherche.** C'est la meme aplatissement — minuscules, sans accent,
    sans apostrophe — des deux cotes. Comparer autrement ici que la ou l'agent
    cherche produirait le pire des cas : une entree refusee comme doublon,
    introuvable par la recherche.

    Le sigle compte comme un nom : deux « MINFI » sont un seul ministere.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT id,
                   coalesce(raison_sociale,
                            btrim(coalesce(nom, '') || ' ' || coalesce(prenom, '')))
              FROM correspondant
             WHERE invalide_le IS NULL
               AND (
                    texte_recherche(coalesce(raison_sociale,
                        btrim(coalesce(nom, '') || ' ' || coalesce(prenom, ''))))
                        = texte_recherche(%s)
                 OR (%s <> '' AND texte_recherche(sigle) = texte_recherche(%s))
               )
             LIMIT 1
            """,
            [designation, sigle, sigle],
        )
        existant = curseur.fetchone()

    if existant is not None:
        raise ErreurMetier(
            f"« {existant[1]} » figure deja au referentiel. "
            "Cherchez-le plutot que d'en creer un second.",
            code="doublon_correspondant",
        )
