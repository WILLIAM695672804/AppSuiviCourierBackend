"""
Formes echangees par l'administration de l'organigramme — `/api/organisation/*`.

Miroir de `frontend/src/features/organisation/api.ts`.

**A ne pas confondre avec `schemas.py`**, qui sert le referentiel de saisie
(`/api/referentiels/*`). Les deux parlent des memes tables et n'en disent pas la
meme chose : le referentiel alimente des selecteurs — il lui faut des
identifiants et des rangs ; l'administration alimente une lecture — il lui faut
des libelles et des comptes. Fusionner les deux aurait donne un schema ou la
moitie des champs ne sert jamais a l'appelant qui les recoit.
"""

from datetime import date

from ninja import Schema


class Identifiant(Schema):
    """Ce que rend une creation : de quoi aller relire l'objet ecrit."""

    id: int


class NiveauAdmin(Schema):
    """Un etage de l'organigramme, avec son poids et ce qu'il autorise."""

    id: int
    rang: int
    libelle: str
    #: Structures **en vigueur** a cet etage. Une direction dissoute n'empeche
    #: rien : elle n'est pas comptee.
    nombreStructures: int
    nombrePostes: int
    peutCoter: bool
    peutRecevoirCotation: bool
    porteSignature: bool
    ligneStatistiques: bool
    niveauParentId: int | None


class PosteAdmin(Schema):
    """
    Un poste de travail et son occupation.

    `niveau` porte le **libelle** de l'etage, la ou `PosteRef` porte son rang :
    c'est un tableau qu'on lit, pas un selecteur qu'on ordonne.
    """

    id: int
    libelle: str
    #: Le sigle de la structure.
    structure: str
    structureId: int
    niveau: str
    niveauId: int
    #: Le poste sous lequel celui-ci se trouve — souvent hors de la structure.
    posteSuperieurId: int | None
    #: « Non defini » quand le poste n'en propose aucun — jamais une chaine vide.
    profilParDefaut: str
    profilParDefautId: int | None
    #: Agents **actifs** en poste. Un compte suspendu n'occupe plus le poste.
    titulaires: int
    postesPrevus: int


class SaisiePoste(Schema):
    """
    Ouverture d'un poste.

    `structureId` n'apparait qu'ici : deplacer un poste d'une direction a une
    autre n'est pas une correction mais une reorganisation, qui clot le poste
    ici et en ouvre un la-bas. Voir `services.modifier_poste`.
    """

    structureId: int
    libelle: str
    niveauId: int
    posteSuperieurId: int | None = None
    profilParDefautId: int | None = None
    #: Combien d'agents le poste doit compter. Un poste vacant est un trou dans
    #: le circuit : c'est l'ecart a cet effectif qui le rend visible.
    effectifPrevu: int = 1


class SaisieModificationPoste(Schema):
    """Correction d'un poste — `None` veut dire « ne touche pas »."""

    libelle: str | None = None
    niveauId: int | None = None
    posteSuperieurId: int | None = None
    profilParDefautId: int | None = None
    effectifPrevu: int | None = None


class SaisieCloturePoste(Schema):
    """Le motif est exige : une cloture sans raison est indistinguable d'une
    fausse manoeuvre six mois plus tard."""

    motif: str


class AffectationSortie(Schema):
    """
    Une occupation de poste, ouverte ou close — F-04.

    `enCours` est `fin is None`, calcule et jamais stocke : une colonne de plus
    se serait desynchronisee le jour ou une fin est saisie a la main.
    """

    id: int
    utilisateurId: int
    agent: str
    posteId: int
    poste: str
    #: Le sigle de la structure du poste, au moment de la lecture.
    structure: str
    debut: date
    fin: date | None
    enCours: bool
    motif: str | None


class SaisieAffectation(Schema):
    """
    Affectation d'un agent a un poste.

    `debut` est facultatif et vaut aujourd'hui : l'administrateur saisit le plus
    souvent le jour meme, et l'obliger a retaper la date du jour est le meilleur
    moyen d'en obtenir une fausse.
    """

    utilisateurId: int
    posteId: int
    debut: date | None = None
    #: Pourquoi. Facultatif a l'ouverture — il n'y a encore rien a motiver.
    motif: str | None = None


class SaisieFinAffectation(Schema):
    """Fin d'occupation sans suite : depart, retraite, mise a disposition. Une
    mutation passe par `POST /affectations`, qui enchaine les deux lignes."""

    fin: date | None = None
    motif: str


class SaisieNiveau(Schema):
    """
    Creation d'un etage.

    Le rang est exige a la creation et absent de la modification : il ordonne
    tout le referentiel, et le changer au milieu d'un formulaire deplacerait
    toutes les structures de l'etage sans que ce soit ce qu'on a demande.
    """

    code: str
    libelle: str
    rang: int
    niveauParentId: int | None = None
    peutCoter: bool = False
    peutRecevoirCotation: bool = True
    porteSignature: bool = False
    ligneStatistiques: bool = True


class SaisieModificationNiveau(Schema):
    """
    Modification d'un etage — tout est facultatif.

    `None` veut dire « ne touche pas », et non « mets a faux » : sans cette
    distinction, un formulaire qui n'envoie que le libelle decocherait les
    quatre autorisations au passage.
    """

    libelle: str | None = None
    niveauParentId: int | None = None
    peutCoter: bool | None = None
    peutRecevoirCotation: bool | None = None
    porteSignature: bool | None = None
    ligneStatistiques: bool | None = None


class SaisieStructure(Schema):
    """
    Inscription d'une structure a l'organigramme.

    Le formulaire vit dans l'ecran d'administration de l'organigramme depuis
    l'ADR 021 : c'est le meme geste que creer un poste, et il en ouvre un.
    """

    libelle: str
    sigle: str
    #: L'une des douze valeurs de `Structure.NATURES` — Direction, Division,
    #: Departement, Service, Cellule, Centre, Cabinet, Secteur,
    #: Representation, Filiale, Succursale, Organe. La garde est le CHECK
    #: `structure_nature_valide` en base, pas ce commentaire.
    nature: str
    niveau: int
    #: La structure mere dans l'organigramme. Le niveau donne le rang ; le parent
    #: donne le rattachement.
    parentId: int | None = None
    #: Non ecrit : nommer quelqu'un a la tete d'une structure passe par un poste.
    responsable: str | None = None
    #: Libelle du poste sommet cree avec la structure. Omis, le serveur compose
    #: un libelle depuis la nature et le sigle.
    posteResponsableLibelle: str | None = None
    #: Profil propose par defaut sur le poste responsable. Omis, `RESP` est
    #: utilise, sauf au sommet ou `DG` est propose.
    profilResponsableId: int | None = None
