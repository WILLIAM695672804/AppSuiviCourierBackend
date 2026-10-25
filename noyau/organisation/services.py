"""
Ecritures sur l'organigramme — structures, niveaux, postes, affectations.

Toute l'ossature releve de l'administrateur fonctionnel (§3.9) et de lui seul :
les structures (F-01), les niveaux (F-02), les postes (F-03) et l'affectation
datee des agents aux postes (F-04). Les structures s'ecrivaient auparavant dans
`gouvernance.services`, sous une permission a part tenue par la DSR ; l'ADR 021
a reuni les deux — creer une structure ouvre un poste, et pourvoir ce poste
etait deja ici.

Le principe 3 de `modeles.py` gouverne ce fichier : **les niveaux ne sont pas
ecrits dans le code**. L'administrateur en cree, en modifie, et le nombre
d'etapes de cotation en decoule. Aucune constante `NIVEAU_DIRECTION = 2` ne doit
apparaitre ici — ni ailleurs.

Et une regle qui vaut pour tout le depot : **`affecter()` est le seul point qui
ecrit `utilisateur.poste`**. La colonne dit le present, `affectation_poste` dit
l'histoire, et les deux s'ecrivent ensemble. Un second appelant qui poserait la
colonne directement trouerait l'histoire sans qu'aucune erreur ne le signale —
c'est exactement ce que faisait `habilitation.services.modifier_compte` avant
l'ADR 015.
"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from noyau.erreurs import ErreurMetier
from noyau.habilitation.modeles import Profil
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur as contexte_acteur
from noyau.journal.service import inscrire
from noyau.organisation.modeles import (
    AffectationPoste,
    NiveauHierarchique,
    Poste,
    Structure,
)

#: Les proprietes qu'un niveau porte et qu'un administrateur peut changer.
#: Regroupees pour que le journal n'ait pas a les enumerer une seconde fois.
AUTORISATIONS = (
    "peut_coter",
    "peut_recevoir_cotation",
    "porte_signature",
    "ligne_statistiques",
)

#: Au-dela, l'effectif prevu d'un poste est tenu pour une faute de frappe.
#: **Hypothese** : aucun document ne dit combien d'agents un poste peut
#: compter. Voir A22 dans `docs/questions-ouvertes.md`.
PLAFOND_EFFECTIF = 10


def creer_niveau(
    acteur: Utilisateur,
    *,
    code: str,
    libelle: str,
    rang: int,
    niveau_parent_id: int | None = None,
    peut_coter: bool = False,
    peut_recevoir_cotation: bool = True,
    porte_signature: bool = False,
    ligne_statistiques: bool = True,
) -> NiveauHierarchique:
    """
    Ouvre un etage dans l'organigramme.

    Le rang doit etre libre : le socle porte un index unique partiel sur
    `(rang) WHERE invalide_le IS NULL`, et laisser passer un doublon rendrait
    l'ordre du referentiel indefini — deux etages « 2 » se departageraient par
    l'ordre d'insertion, qui n'est pas une regle.

    Inserer un etage **entre** deux autres suppose donc de renumeroter d'abord.
    L'ecran ne le fait pas a la place de l'administrateur : decaler
    silencieusement trois niveaux, c'est modifier la place de toutes leurs
    structures sans que personne ne l'ait demande.
    """
    _refuser_code_pris(code)
    _refuser_rang_pris(rang)
    parent = _parent(niveau_parent_id)

    with transaction.atomic():
        niveau = NiveauHierarchique.objects.create(
            code=code,
            libelle=libelle,
            rang=rang,
            niveau_parent=parent,
            peut_coter=peut_coter,
            peut_recevoir_cotation=peut_recevoir_cotation,
            porte_signature=porte_signature,
            ligne_statistiques=ligne_statistiques,
        )
        inscrire(
            acteur=acteur,
            type_evenement="niveau_cree",
            objet_type="niveau_hierarchique",
            objet_id=niveau.pk,
            libelle=f"Niveau hierarchique « {libelle} » cree au rang {rang}",
            donnees={
                "code": code,
                "libelle": libelle,
                "rang": rang,
                **{nom: getattr(niveau, nom) for nom in AUTORISATIONS},
            },
        )

    return niveau


def modifier_niveau(
    acteur: Utilisateur,
    niveau_id: int,
    *,
    libelle: str | None = None,
    niveau_parent_id: int | None = None,
    peut_coter: bool | None = None,
    peut_recevoir_cotation: bool | None = None,
    porte_signature: bool | None = None,
    ligne_statistiques: bool | None = None,
) -> NiveauHierarchique:
    """
    Change ce qu'un etage autorise.

    **Le rang ne se modifie pas ici.** Il ordonne le referentiel entier ; le
    changer deplace toutes les structures de l'etage d'un coup, et se fait par
    une renumerotation assumee, pas par un champ au milieu d'un formulaire.

    Seuls les champs fournis sont touches, et le journal ne retient que ce qui
    a reellement change — un evenement qui enregistre huit valeurs identiques
    ne dit plus rien de ce qui s'est passe.
    """
    niveau = _niveau(niveau_id)

    ecarts: dict[str, object] = {}
    if libelle is not None and libelle != niveau.libelle:
        ecarts["libelle"] = libelle
        niveau.libelle = libelle

    if niveau_parent_id is not None and niveau_parent_id != niveau.niveau_parent_id:
        if niveau_parent_id == niveau.pk:
            raise ErreurMetier(
                "Un niveau ne peut pas se rattacher a lui-meme.",
                code="niveau_parent_reflexif",
            )
        niveau.niveau_parent = _parent(niveau_parent_id)
        ecarts["niveauParentId"] = niveau_parent_id

    for nom, valeur in (
        ("peut_coter", peut_coter),
        ("peut_recevoir_cotation", peut_recevoir_cotation),
        ("porte_signature", porte_signature),
        ("ligne_statistiques", ligne_statistiques),
    ):
        if valeur is not None and valeur != getattr(niveau, nom):
            setattr(niveau, nom, valeur)
            ecarts[nom] = valeur

    if not ecarts:
        return niveau

    with transaction.atomic():
        niveau.save()
        inscrire(
            acteur=acteur,
            type_evenement="niveau_modifie",
            objet_type="niveau_hierarchique",
            objet_id=niveau.pk,
            libelle=(f"Niveau « {niveau.libelle} » modifie ({', '.join(sorted(ecarts))})"),
            donnees={"code": niveau.code, **ecarts},
        )

    return niveau


# =====================================================================
#  Les postes — F-03
# =====================================================================


def creer_poste(
    acteur: Utilisateur,
    *,
    structure_id: int,
    libelle: str,
    niveau_id: int,
    poste_superieur_id: int | None = None,
    profil_par_defaut_id: int | None = None,
    effectif_prevu: int = 1,
) -> Poste:
    """
    Ouvre un poste dans une structure.

    Le poste est l'unite de la hierarchie, pas l'agent (principe 2 de
    `modeles.py`) : c'est pour cela qu'il se cree independamment de son
    occupant, et qu'un poste vacant est un objet normal — c'est meme ce que
    l'ecran cherche a rendre visible.

    `poste_superieur` peut relever d'une **autre structure**, et c'est le cas
    ordinaire : le superieur d'un directeur est le Directeur general, qui ne
    releve pas de la direction. Le refuser aurait casse la remontee au sommet.
    """
    structure = _structure_en_vigueur(structure_id)
    niveau = _niveau(niveau_id)
    superieur = _poste_en_vigueur(poste_superieur_id) if poste_superieur_id else None
    _refuser_effectif_absurde(effectif_prevu)

    with transaction.atomic():
        poste = Poste.objects.create(
            structure=structure,
            libelle=libelle,
            niveau_hierarchique=niveau,
            poste_superieur=superieur,
            profil_par_defaut_id=profil_par_defaut_id,
            effectif_prevu=effectif_prevu,
            valide_du=timezone.localdate(),
            cree_par=acteur.pk,
        )
        inscrire(
            acteur=acteur,
            type_evenement="poste_cree",
            objet_type="poste",
            objet_id=poste.pk,
            libelle=f"Poste « {libelle} » ouvert a {structure.code}",
            donnees={
                "structure": structure.code,
                "niveau": niveau.libelle,
                "effectifPrevu": effectif_prevu,
            },
        )

    return poste


def modifier_poste(
    acteur: Utilisateur,
    poste_id: int,
    *,
    libelle: str | None = None,
    niveau_id: int | None = None,
    poste_superieur_id: int | None = None,
    profil_par_defaut_id: int | None = None,
    effectif_prevu: int | None = None,
) -> Poste:
    """
    Corrige un poste en place.

    **La structure n'est pas modifiable.** Deplacer un poste d'une direction a
    une autre n'est pas une correction : c'est une reorganisation, qui clot le
    poste ici et en ouvre un la-bas. Le faire par un champ ferait suivre
    l'historique des affectations dans la nouvelle direction, comme si les
    agents y avaient toujours travaille.

    Le rattachement hierarchique, lui, se corrige : `None` veut dire « ne
    touche pas ». Detacher un poste du sommet suppose donc une route dediee, et
    il n'y en a pas — aucun ecran ne l'a demande.
    """
    poste = _poste_en_vigueur(poste_id)

    ecarts: dict[str, object] = {}

    if libelle is not None and libelle != poste.libelle:
        ecarts["libelle"] = libelle
        poste.libelle = libelle

    if niveau_id is not None and niveau_id != poste.niveau_hierarchique_id:
        poste.niveau_hierarchique = _niveau(niveau_id)
        ecarts["niveau"] = poste.niveau_hierarchique.libelle

    if poste_superieur_id is not None and poste_superieur_id != poste.poste_superieur_id:
        if poste_superieur_id == poste.pk:
            raise ErreurMetier(
                "Un poste ne peut pas etre son propre superieur.",
                code="poste_superieur_reflexif",
            )
        superieur = _poste_en_vigueur(poste_superieur_id)
        _refuser_cycle_hierarchique(poste, superieur)
        poste.poste_superieur = superieur
        ecarts["posteSuperieurId"] = poste_superieur_id

    if profil_par_defaut_id is not None and profil_par_defaut_id != poste.profil_par_defaut_id:
        poste.profil_par_defaut_id = profil_par_defaut_id
        ecarts["profilParDefautId"] = profil_par_defaut_id

    if effectif_prevu is not None and effectif_prevu != poste.effectif_prevu:
        _refuser_effectif_absurde(effectif_prevu)
        poste.effectif_prevu = effectif_prevu
        ecarts["effectifPrevu"] = effectif_prevu

    if not ecarts:
        return poste

    with transaction.atomic():
        poste.modifie_le = timezone.now()
        poste.modifie_par = acteur.pk
        poste.save()
        inscrire(
            acteur=acteur,
            type_evenement="poste_modifie",
            objet_type="poste",
            objet_id=poste.pk,
            libelle=f"Poste « {poste.libelle} » modifie ({', '.join(sorted(ecarts))})",
            donnees=ecarts,
        )

    return poste


def cloturer_poste(acteur: Utilisateur, poste_id: int, *, motif: str) -> Poste:
    """
    Ferme un poste. **La ligne n'est jamais effacee** (principe 1).

    Deux refus, et tous deux protegent l'organigramme d'un trou silencieux :

     1. un poste **occupe** ne se clot pas — l'agent se retrouverait rattache a
        un poste hors vigueur, invisible de tous les selecteurs, et son
        perimetre `poste` ne rendrait plus rien sans qu'aucune erreur ne le
        dise ;
     2. un poste dont **des subordonnes dependent** ne se clot pas non plus :
        la remontee au superieur s'arreterait sur une ligne close, et le
        circuit de validation perdrait son etage sans le signaler.

    Le motif est exige. Une cloture sans raison est indistinguable d'une
    fausse manoeuvre six mois plus tard.
    """
    poste = _poste_en_vigueur(poste_id)

    occupants = Utilisateur.objects.actifs().filter(poste_id=poste.pk).count()
    if occupants:
        raise ErreurMetier(
            f"« {poste.libelle} » est occupe par {occupants} agent(s). "
            "Mettez fin aux affectations avant de clore le poste.",
            code="poste_occupe",
        )

    subordonnes = Poste.objects.en_vigueur().filter(poste_superieur_id=poste.pk).count()
    if subordonnes:
        raise ErreurMetier(
            f"{subordonnes} poste(s) dependent de « {poste.libelle} ». "
            "Rattachez-les ailleurs avant de clore celui-ci.",
            code="poste_avec_subordonnes",
        )

    with transaction.atomic():
        poste.valide_au = timezone.localdate()
        poste.invalide_le = timezone.now()
        poste.invalide_par = acteur.pk
        poste.save()
        inscrire(
            acteur=acteur,
            type_evenement="poste_clos",
            objet_type="poste",
            objet_id=poste.pk,
            libelle=f"Poste « {poste.libelle} » clos",
            detail=motif,
            donnees={"structure": poste.structure.code},
        )

    return poste


# =====================================================================
#  Les affectations — F-04
# =====================================================================


def affecter(
    acteur: Utilisateur,
    *,
    utilisateur_id: int,
    poste_id: int,
    debut: date | None = None,
    motif: str | None = None,
) -> AffectationPoste:
    """
    Affecte un agent a un poste, a une date donnee.

    **Le seul point qui touche `utilisateur.poste`.** La colonne dit le
    present, la table dit l'histoire, et les deux s'ecrivent dans la meme
    transaction — voir `AffectationPoste`. Tout autre appelant qui ecrirait la
    colonne directement trouerait l'histoire sans qu'aucune erreur ne le
    signale.

    L'affectation en cours, s'il y en a une, est **close la veille** du nouveau
    debut. Les deux occupations ne se recouvrent donc pas, et une lecture datee
    rend un titulaire et un seul.

    **Une exception, et elle est structurelle** : quand l'affectation en cours a
    commence le jour meme du changement, la veille serait anterieure a son propre
    debut. Elle se clot alors sur son jour d'ouverture, et l'agent apparait sur
    les deux postes ce jour-la. C'est exact — il les a tenus tous les deux dans
    la journee — et c'est la limite de la granularite au jour. Descendre a
    l'horodatage reglerait ce cas et n'en vaut pas le prix : aucun ecran ne
    saisit une heure de prise de fonction.

    `structure` suit le poste. La laisser diverger produirait un agent affiche
    a la DAF et cote a la DSI, sans qu'aucune des deux vues n'ait tort.
    """
    debut = debut or timezone.localdate()
    agent = _agent(utilisateur_id)
    poste = _poste_en_vigueur(poste_id)

    en_cours = AffectationPoste.objects.filter(utilisateur_id=agent.pk, fin__isnull=True).first()
    if en_cours is not None:
        if en_cours.poste_id == poste.pk:
            raise ErreurMetier(
                f"{agent.nom_complet} occupe deja « {poste.libelle} ».",
                code="affectation_inchangee",
            )
        if debut < en_cours.debut:
            raise ErreurMetier(
                f"L'affectation en cours a commence le {en_cours.debut:%d/%m/%Y} : "
                "une nouvelle ne peut pas prendre effet avant.",
                code="affectation_anterieure",
            )

    with transaction.atomic():
        if en_cours is not None:
            # La veille du nouveau debut — sauf si l'affectation en cours a
            # commence ce jour-la meme, auquel cas la veille serait anterieure a
            # son propre debut. Elle se clot alors sur son jour d'ouverture :
            # l'agent a bien tenu les deux postes dans la meme journee, et c'est
            # la limite de la granularite au jour, pas une approximation.
            en_cours.fin = max(debut - timedelta(days=1), en_cours.debut)
            en_cours.motif = motif
            en_cours.modifie_le = timezone.now()
            en_cours.modifie_par = acteur.pk
            en_cours.save()

        affectation = AffectationPoste.objects.create(
            utilisateur=agent,
            poste=poste,
            debut=debut,
            motif=motif,
            cree_par=acteur.pk,
        )

        agent.poste = poste
        agent.structure = poste.structure
        agent.save(update_fields=["poste", "structure"])

        inscrire(
            acteur=acteur,
            type_evenement="agent_affecte",
            objet_type="utilisateur",
            objet_id=agent.pk,
            libelle=f"{agent.nom_complet} affecte a « {poste.libelle} » ({poste.structure.code})",
            detail=motif,
            donnees={
                "posteId": poste.pk,
                "structure": poste.structure.code,
                "debut": debut.isoformat(),
            },
        )

    return affectation


def terminer_affectation(
    acteur: Utilisateur, affectation_id: int, *, fin: date | None = None, motif: str
) -> AffectationPoste:
    """
    Met fin a une affectation sans lui donner de suite.

    C'est le depart, la retraite, la mise a disposition — pas la mutation, qui
    passe par `affecter()` et enchaine les deux lignes elle-meme.

    L'agent se retrouve **sans poste**, et c'est exact : il n'en occupe plus.
    Le tableau de bord de l'administration compte alors le poste comme vacant,
    ce qui est precisement ce qu'on veut voir.
    """
    fin = fin or timezone.localdate()
    affectation = (
        AffectationPoste.objects.select_related("utilisateur", "poste")
        .filter(pk=affectation_id)
        .first()
    )
    if affectation is None:
        raise ErreurMetier("Cette affectation n'existe pas.", code="affectation_inconnue")
    if affectation.fin is not None:
        raise ErreurMetier(
            f"Cette affectation est deja close depuis le {affectation.fin:%d/%m/%Y}.",
            code="affectation_close",
        )
    if fin < affectation.debut:
        raise ErreurMetier(
            f"L'affectation a commence le {affectation.debut:%d/%m/%Y} : "
            "elle ne peut pas se terminer avant.",
            code="fin_avant_debut",
        )

    with transaction.atomic():
        affectation.fin = fin
        affectation.motif = motif
        affectation.modifie_le = timezone.now()
        affectation.modifie_par = acteur.pk
        affectation.save()

        agent = affectation.utilisateur
        agent.poste = None
        agent.save(update_fields=["poste"])

        inscrire(
            acteur=acteur,
            type_evenement="affectation_terminee",
            objet_type="utilisateur",
            objet_id=agent.pk,
            libelle=f"{agent.nom_complet} quitte « {affectation.poste.libelle} »",
            detail=motif,
            donnees={"posteId": affectation.poste_id, "fin": fin.isoformat()},
        )

    return affectation


# =====================================================================
#  Refus
# =====================================================================


def _agent(utilisateur_id: int) -> Utilisateur:
    agent = Utilisateur.objects.filter(pk=utilisateur_id).first()
    if agent is None:
        raise ErreurMetier("Ce compte n'existe pas.", code="compte_inconnu")
    return agent


def _structure_en_vigueur(structure_id: int) -> Structure:
    structure = Structure.objects.en_vigueur().filter(pk=structure_id).first()
    if structure is None:
        raise ErreurMetier(
            "Cette structure n'existe pas ou n'est plus en vigueur.",
            code="structure_inconnue",
        )
    return structure


def _poste_en_vigueur(poste_id: int) -> Poste:
    poste = Poste.objects.en_vigueur().select_related("structure").filter(pk=poste_id).first()
    if poste is None:
        raise ErreurMetier(
            "Ce poste n'existe pas ou n'est plus en vigueur.",
            code="poste_inconnu",
        )
    return poste


def _refuser_effectif_absurde(effectif: int) -> None:
    """
    Un poste compte au moins un agent.

    Le plafond a dix est une **hypothese** : rien dans les documents ne dit
    combien d'agents un poste peut compter (A22). Il existe pour arreter la
    faute de frappe — « 100 » saisi pour « 10 » rendrait tous les postes de la
    direction vacants a l'ecran, et personne ne saurait pourquoi.
    """
    if effectif < 1:
        raise ErreurMetier(
            "Un poste compte au moins un agent.",
            code="effectif_nul",
        )
    if effectif > PLAFOND_EFFECTIF:
        raise ErreurMetier(
            f"Un poste de plus de {PLAFOND_EFFECTIF} agents est probablement une "
            "faute de frappe. Ouvrez plusieurs postes, ou faites trancher A22.",
            code="effectif_invraisemblable",
        )


def _refuser_cycle_hierarchique(poste: Poste, superieur: Poste) -> None:
    """
    Un poste ne peut pas devenir le superieur de son propre superieur.

    Sans ce refus, la remontee au sommet boucle indefiniment : le circuit de
    validation tournerait entre deux etages jusqu'a epuiser la pile, et l'erreur
    apparaitrait a la validation d'un courrier, pas a la saisie qui l'a causee.
    """
    vu = {poste.pk}
    courant: Poste | None = superieur
    while courant is not None:
        if courant.pk in vu:
            raise ErreurMetier(
                f"« {superieur.libelle} » depend deja de « {poste.libelle} » : "
                "ce rattachement ferait une boucle.",
                code="cycle_hierarchique",
            )
        vu.add(courant.pk)
        courant = (
            Poste.objects.filter(pk=courant.poste_superieur_id).first()
            if courant.poste_superieur_id
            else None
        )


def _niveau(niveau_id: int) -> NiveauHierarchique:
    niveau = NiveauHierarchique.objects.filter(pk=niveau_id).first()
    if niveau is None:
        raise ErreurMetier("Ce niveau hierarchique n'existe pas.", code="niveau_inconnu")
    return niveau


def _parent(niveau_parent_id: int | None) -> NiveauHierarchique | None:
    if niveau_parent_id is None:
        return None
    return _niveau(niveau_parent_id)


def _refuser_code_pris(code: str) -> None:
    """Sans ce refus, l'index unique du socle rend une `IntegrityError` — un 500
    sur une faute de frappe."""
    if NiveauHierarchique.objects.filter(code=code).exists():
        raise ErreurMetier(
            f"Le code « {code} » designe deja un niveau hierarchique.",
            code="code_niveau_pris",
        )


def _refuser_rang_pris(rang: int) -> None:
    occupant = NiveauHierarchique.objects.filter(rang=rang, invalide_le__isnull=True).first()
    if occupant is not None:
        raise ErreurMetier(
            f"Le rang {rang} est deja tenu par « {occupant.libelle} ». "
            "Renumerotez d'abord, ou choisissez un autre rang.",
            code="rang_pris",
        )


# =====================================================================
#  Lecture — ce que l'ecran d'administration affiche
# =====================================================================


def registre_niveaux() -> list[dict]:
    """
    Les niveaux, avec le poids de chacun.

    `nombreStructures` et `nombrePostes` ne sont pas decoratifs : ce sont eux
    qui empechent la suppression a l'aveugle, et l'ecran les affiche en
    avertissement — « 4 structures utilisent ce niveau, modifier ce qu'il
    autorise change le circuit de tous leurs courriers en cours ».

    Les deux comptes ne retiennent que les lignes **en vigueur**. Une direction
    dissoute n'empeche pas de modifier son ancien etage.
    """
    niveaux = NiveauHierarchique.objects.all().order_by("rang")

    structures = _compter(Structure.objects.en_vigueur(), "niveau_hierarchique_id")
    postes = _compter(Poste.objects.en_vigueur(), "niveau_hierarchique_id")

    return [
        {
            "id": niveau.pk,
            "rang": niveau.rang,
            "libelle": niveau.libelle,
            "nombreStructures": structures.get(niveau.pk, 0),
            "nombrePostes": postes.get(niveau.pk, 0),
            "peutCoter": niveau.peut_coter,
            "peutRecevoirCotation": niveau.peut_recevoir_cotation,
            "porteSignature": niveau.porte_signature,
            "ligneStatistiques": niveau.ligne_statistiques,
            "niveauParentId": niveau.niveau_parent_id,
        }
        for niveau in niveaux
    ]


def registre_postes() -> list[dict]:
    """
    Les postes de travail, avec leur occupation.

    `titulaires` compte les agents **actifs** en poste, pas les lignes
    `utilisateur` : un compte suspendu n'occupe plus le poste, et le compter
    masquerait la vacance que l'ecran doit precisement montrer.

    `niveau` rend le **libelle** et non le rang — c'est un tableau
    d'administration, ou « Service » se lit mieux que « 4 ». Le referentiel de
    saisie (`/referentiels/postes`), lui, rend le rang : il alimente des
    selecteurs, pas une lecture.

    Les identifiants accompagnent les libelles depuis que le poste se modifie :
    le formulaire de correction doit pouvoir preselectionner le niveau et le
    superieur, et un libelle ne se compare pas — deux etages peuvent porter le
    meme mot dans deux organigrammes successifs.
    """
    postes = (
        Poste.objects.en_vigueur()
        .select_related("structure", "niveau_hierarchique", "profil_par_defaut")
        .order_by("structure__code", "niveau_hierarchique__rang", "libelle")
    )

    titulaires = _compter(Utilisateur.objects.actifs().filter(poste__isnull=False), "poste_id")

    return [
        {
            "id": poste.pk,
            "libelle": poste.libelle,
            "structure": poste.structure.code,
            "structureId": poste.structure_id,
            "niveau": poste.niveau_hierarchique.libelle,
            "niveauId": poste.niveau_hierarchique_id,
            "posteSuperieurId": poste.poste_superieur_id,
            "profilParDefaut": (
                poste.profil_par_defaut.libelle if poste.profil_par_defaut else "Non defini"
            ),
            "profilParDefautId": poste.profil_par_defaut_id,
            "titulaires": titulaires.get(poste.pk, 0),
            "postesPrevus": poste.effectif_prevu,
        }
        for poste in postes
    ]


def registre_affectations(
    *, poste_id: int | None = None, utilisateur_id: int | None = None
) -> list[dict]:
    """
    Qui a occupe quoi, et quand — F-04.

    Sans filtre, la liste rendrait l'histoire entiere de l'institution ; l'ecran
    en demande toujours une tranche, par poste ou par agent. Les deux filtres se
    combinent, ce qui repond a « depuis quand cet agent tient-il ce poste ».

    `enCours` est calcule et non stocke : c'est `fin IS NULL`, et une colonne de
    plus se serait desynchronisee le jour ou une fin est saisie a la main
    (ADR 010 — l'etat se deduit).
    """
    lignes = AffectationPoste.objects.select_related(
        "utilisateur", "poste", "poste__structure"
    ).all()
    if poste_id is not None:
        lignes = lignes.filter(poste_id=poste_id)
    if utilisateur_id is not None:
        lignes = lignes.filter(utilisateur_id=utilisateur_id)

    return [
        {
            "id": ligne.pk,
            "utilisateurId": ligne.utilisateur_id,
            "agent": ligne.utilisateur.nom_complet,
            "posteId": ligne.poste_id,
            "poste": ligne.poste.libelle,
            "structure": ligne.poste.structure.code,
            "debut": ligne.debut,
            "fin": ligne.fin,
            "enCours": ligne.fin is None,
            "motif": ligne.motif,
        }
        for ligne in lignes
    ]


def _compter(lot, colonne: str) -> dict[int, int]:
    """Un `GROUP BY` rendu en dictionnaire — une requete plutot que N."""
    from django.db.models import Count

    return {
        ligne[colonne]: ligne["total"]
        for ligne in lot.values(colonne).annotate(total=Count("*"))
        if ligne[colonne] is not None
    }


# =====================================================================
#  Referentiel des structures
# =====================================================================


def creer_structure(agent: Utilisateur, saisie) -> Structure:
    """
    Inscrit une structure a l'organigramme — permission `ADM_ORG`.

    Ecrire une structure, c'est ecrire l'ossature : elle ouvre un poste, ce
    poste prend rang sous celui de la structure mere, et un agent y sera
    affecte. C'est le meme geste que creer un niveau ou un poste, sous la meme
    garde et dans le meme ecran — voir ADR 021.

    Le sigle est unique parmi les structures **en vigueur** seulement : une
    direction dissoute libere son sigle, et l'histoire garde la ligne close.

    `saisie.responsable` n'est pas ecrit : nommer quelqu'un a la tete d'une
    structure passe par un **poste**, avec sa date d'effet et sa fin de mandat.
    La creation ouvre donc le poste sommet de la structure, vacant. Poser une
    colonne « responsable » sur la structure aurait cree une seconde verite a
    cote de `poste`, et c'est elle qui aurait vieilli.
    """
    if Structure.objects.filter(code=saisie.sigle, valide_au__isnull=True).exists():
        raise ErreurMetier(
            f"Une structure en vigueur porte deja le sigle « {saisie.sigle} ».",
            code="sigle_pris",
        )

    natures = [code for code, _ in Structure.NATURES]
    if saisie.nature not in natures:
        raise ErreurMetier(
            f"Nature « {saisie.nature} » inconnue. Les natures sont : {', '.join(natures)}.",
            code="nature_inconnue",
        )

    niveau = NiveauHierarchique.objects.filter(rang=saisie.niveau, actif=True).first()
    if niveau is None:
        rangs = ", ".join(
            str(r)
            for r in NiveauHierarchique.objects.filter(actif=True).values_list("rang", flat=True)
        )
        raise ErreurMetier(
            f"Niveau hierarchique {saisie.niveau} inconnu. Les rangs sont : {rangs}.",
            code="niveau_inconnu",
        )

    parent = _structure_parente(saisie.parentId)
    _refuser_parent_incoherent(parent, niveau)
    poste_superieur = _poste_responsable(parent) if parent else None
    profil = _profil_responsable(saisie.profilResponsableId, niveau)
    libelle_poste = _libelle_poste_responsable(saisie)

    with transaction.atomic(), contexte_acteur(agent):
        structure = Structure.objects.create(
            code=saisie.sigle,
            libelle=saisie.libelle,
            parent=parent,
            niveau_hierarchique=niveau,
            nature=saisie.nature,
            valide_du=date.today(),
            cree_par=agent.pk,
        )
        inscrire(
            objet_type="structure",
            objet_id=structure.pk,
            type_evenement="structure_creee",
            libelle=f"Structure « {structure.code} » inscrite a l'organigramme",
            detail=structure.libelle,
            acteur=agent,
            donnees={"sigle": structure.code, "niveau": saisie.niveau},
        )
        creer_poste(
            agent,
            structure_id=structure.pk,
            libelle=libelle_poste,
            niveau_id=niveau.pk,
            poste_superieur_id=poste_superieur.pk if poste_superieur else None,
            profil_par_defaut_id=profil.pk if profil else None,
            effectif_prevu=1,
        )
    return structure


def _structure_parente(parent_id: int | None) -> Structure | None:
    if parent_id is None:
        return None
    parent = Structure.objects.en_vigueur().filter(pk=parent_id).first()
    if parent is None:
        raise ErreurMetier(
            "La structure parente n'existe pas ou n'est plus en vigueur.",
            code="structure_parente_inconnue",
        )
    return parent


def _refuser_parent_incoherent(parent: Structure | None, niveau: NiveauHierarchique) -> None:
    if parent is None:
        return
    if parent.niveau_hierarchique.rang >= niveau.rang:
        raise ErreurMetier(
            "La structure parente doit etre situee a un rang superieur.",
            code="structure_parente_incoherente",
        )


def _poste_responsable(parent: Structure) -> Poste:
    poste = (
        Poste.objects.en_vigueur()
        .filter(structure=parent)
        .select_related("niveau_hierarchique")
        .order_by(
            F("poste_superieur_id").asc(nulls_first=True),
            "niveau_hierarchique__rang",
            "libelle",
        )
        .first()
    )
    if poste is None:
        raise ErreurMetier(
            "La structure parente n'a pas de poste responsable. Creez son poste "
            "sommet avant de lui rattacher une nouvelle structure.",
            code="poste_parent_absent",
        )
    return poste


def _profil_responsable(profil_id: int | None, niveau: NiveauHierarchique) -> Profil | None:
    if profil_id is not None:
        profil = Profil.objects.filter(pk=profil_id, invalide_le__isnull=True).first()
        if profil is None:
            raise ErreurMetier(
                "Le profil propose pour le poste responsable n'existe pas.",
                code="profil_responsable_inconnu",
            )
        return profil

    code = "DG" if niveau.rang == 1 else "RESP"
    profil = Profil.objects.filter(code=code, invalide_le__isnull=True).first()
    if profil is None:
        raise ErreurMetier(
            f"Le profil systeme « {code} » est introuvable.",
            code="profil_responsable_absent",
        )
    return profil


def _libelle_poste_responsable(saisie) -> str:
    explicite = (saisie.posteResponsableLibelle or "").strip()
    if explicite:
        return explicite

    sigle = (saisie.sigle or saisie.libelle).strip()
    if saisie.nature == "Direction":
        return f"Directeur de {sigle}"
    if saisie.nature == "Service":
        return f"Chef de service {sigle}"
    if saisie.nature == "Division":
        return f"Chef de division {sigle}"
    return f"Responsable de {sigle}"
