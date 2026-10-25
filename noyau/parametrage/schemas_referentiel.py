"""
Formes echangees par les referentiels de saisie.

Miroir de `frontend/src/lib/referentiel.ts` — `Nature`, `MentionType`,
`Correspondant`. Ce fichier-la est deja consomme par l'ecran d'enregistrement
d'un courrier et par la modale de cotation : la forme n'est pas negociable.

Distinct de `schemas.py`, qui porte les formes de `GET /parametrage` : celui-la
sert un administrateur et rend tout ce qui s'administre — usage, doublons
presumes, comportement, niveaux autorises. Celui-ci sert un agent qui remplit un
formulaire, et ne rend que ce qu'il faut pour choisir. Les fondre aurait fait
sortir la colonne « doublon presume » du carnet d'adresses dans un selecteur.

Convention posee dans `config/api.py` : **sortie en camelCase**.
"""

from datetime import date

from ninja import Schema


class NatureRef(Schema):
    """Une nature de courrier, et le delai qu'elle propose."""

    id: int
    libelle: str
    #: `nature.delai_defaut_jours`, en **jours ouvres**. Le front dit
    #: « delaiParDefaut » : c'est une proposition, pas une contrainte, et l'agent
    #: peut en retenir un autre a l'enregistrement.
    delaiParDefaut: int | None


class MentionRef(Schema):
    """
    Une mention de cotation, reduite a ce que la modale affiche.

    Ni `comportement` ni `niveauxAutorises` : ce que la mention declenche n'est
    pas tranche (A25), et le rendre ici l'aurait fait passer pour une regle
    appliquee. L'ecran de parametrage, lui, le montre comme ce qu'il est — une
    ligne administree, souvent vide.
    """

    id: int
    libelle: str


class CorrespondantRef(Schema):
    """
    Une entree du carnet d'adresses, telle que la lit le selecteur d'expediteur.

    `nombreCourriers` et `dernierCourrier` ne sont pas decoratifs : ils
    permettent a l'agent de reconnaitre en un coup d'oeil le correspondant qu'il
    cherche parmi deux entrees de nom voisin. C'est ce qui evite qu'un meme
    ministere finisse ecrit de six manieres — et donc que les statistiques par
    correspondant deviennent fausses.
    """

    id: int
    #: La raison sociale, ou « Nom Prenom » pour une personne physique. Voir
    #: `Correspondant.designation`.
    libelle: str
    #: « MINFI », « APN ». `None` quand l'entree n'en a pas — beaucoup n'en ont
    #: pas, et afficher une chaine vide a cote du nom ferait un trou.
    sigle: str | None = None
    #: « Externe », « Interne », « Usager », « Administration ».
    categorie: str
    #: Deux lettres au plus, pour la pastille. Calculees, jamais stockees.
    initiales: str
    nombreCourriers: int
    #: La date de reception du dernier courrier recu de lui. `None` quand il n'en
    #: a envoye aucun — un correspondant tout juste cree, ou un destinataire.
    dernierCourrier: date | None


class SaisieCorrespondant(Schema):
    """
    Creation d'une entree du carnet d'adresses, depuis l'ecran A-01.

    Miroir de `frontend/src/features/courrier/components/ModaleCorrespondant.tsx`.

    Un seul des deux champs d'identite est exige — `raisonSociale` pour une
    organisation, `nom` pour une personne physique — parce que la contrainte
    `correspondant_identite` du socle dit exactement cela. Le service tranche,
    pas le schema : la regle est metier, et son message doit etre lisible par
    un agent de session.
    """

    #: `externe`, `interne`, `usager` ou `administration`.
    type: str = "externe"
    raisonSociale: str = ""
    nom: str = ""
    prenom: str = ""
    #: Le sigle usuel. Mis en capitales et debarrasse de ses espaces par le
    #: service : « min fi » et « MINFI » ne font pas deux ministeres.
    sigle: str = ""
    adresse: str = ""
    ville: str = ""
    courriel: str = ""
    telephone: str = ""
