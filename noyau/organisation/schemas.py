"""
Formes echangees par le referentiel de l'organisation.

Miroir de `frontend/src/lib/referentiel.ts`. Ce fichier-la est lu par sept
ecrans — cotation, enregistrement, redaction d'un depart, recherche,
statistiques, signalement d'ecart et le referentiel lui-meme : la forme n'est
donc pas negociable, elle est deja consommee.

Convention posee dans `config/api.py` : **sortie en camelCase**.

`niveau` vaut le **rang** du niveau hierarchique, pas une profondeur calculee
dans l'arbre. C'est deja ce que `POST /organisation/structures` recoit en entree
(voir `noyau.organisation.services.creer_structure`) : lecture et ecriture parlent du
meme nombre, sans quoi une structure creee au niveau 2 se relirait au niveau 1.
Rang 1 = Direction Generale.
"""

from ninja import Schema


class StructureRef(Schema):
    """Une structure en vigueur, telle que la lisent les selecteurs du front."""

    id: int
    libelle: str
    #: `structure.code` — le front dit « sigle », la base dit « code ».
    sigle: str
    nature: str
    #: Rang du niveau hierarchique. 1 = Direction Generale.
    niveau: int
    #: La structure de rattachement. `None` au sommet — et au sommet seulement.
    #:
    #: **C'est ce champ qui fait l'organigramme.** `niveau` ne dit que la
    #: profondeur : deux directions de rang 2 rattachees a deux directions
    #: differentes s'affichaient au meme retrait, cote a cote, comme si elles
    #: etaient soeurs. Le rang indente, le parent rattache.
    parentId: int | None
    #: Deduit du poste occupe, jamais d'une colonne. Voir `lecture.responsables()`.
    responsable: str | None
    #: Sans source tant que le pilier courrier n'existe pas — voir
    #: `docs/questions-ouvertes.md`.
    delaiMoyenJours: int | None
    courriersEnCours: int


class AgentRef(Schema):
    """
    Un agent actif, tel que le lisent les selecteurs de responsable.

    **Trois champs et pas un de plus.** L'annuaire est lu sans perimetre
    (ADR 020) : ce qui en sort est visible de toute session authentifiee. Le
    matricule, le courriel et le telephone n'y sont donc pas — designer
    quelqu'un ne suppose pas de savoir comment le joindre.

    `poste` et `structure` ne sont pas decoratifs : ils departagent deux
    homonymes a l'ecran. Le serveur, lui, les departage par `id`.
    """

    id: int
    #: `f"{prenom} {nom}"` — la forme que les schemas de sortie affichent.
    nomComplet: str
    #: Vide pour un compte sans poste : le cas existe et ne doit pas masquer
    #: l'agent, sans quoi il deviendrait indesignable.
    poste: str
    #: `structure.code` — le sigle.
    structure: str
    structureId: int | None


class PosteRef(Schema):
    """
    Un poste en vigueur, tel que le lit le formulaire de creation d'un compte.

    `structureId` accompagne `structure` : le front en a besoin pour verifier
    lui-meme la coherence avant d'envoyer, et le sigle seul ne se compare pas.
    """

    id: int
    libelle: str
    structureId: int
    #: `structure.code` — le sigle, pour desambiguiser deux postes homonymes.
    structure: str
    #: Rang du niveau hierarchique. 1 = Direction Generale.
    niveau: int
    #: Le poste sous lequel celui-ci se trouve — jamais l'agent.
    #:
    #: C'est le principe 2 de `modeles.py` : la remontee au superieur reste
    #: juste quand l'occupant change. Le front s'en sert pour l'organigramme
    #: nominatif, et le referentiel pour designer le sommet local d'une
    #: structure (`lecture.responsables()`).
    posteSuperieurId: int | None
