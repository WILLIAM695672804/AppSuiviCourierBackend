"""
Les regles d'ecriture du pilier activites.

**Tout passe par ici, jamais par `api.py`.** Une route ouvre l'enveloppe et
appelle un service ; le service decide.

Trois disciplines valent pour chaque fonction de ce module :

 1. **L'acteur est pose avant toute ecriture** (`with acteur(...)`). Le
    declencheur d'historisation refuse sinon, et le refus arrive parfois par
    ricochet sur une table qu'on ne touche pas. Voir docs/pieges.md.
 2. **Toute ecriture inscrit un evenement** — §18 pour les activites,
    `RNF-TRACE-01` pour le reste. C'est la fiche de vie qui se construit ainsi ;
    elle n'est pas une table.
 3. **On ne reecrit pas ce que le moteur tient.** Le code de l'activite,
    l'avancement calcule et l'etat de suspension viennent de declencheurs. Les
    recalculer ici ferait deux verites.

Ce que le service ajoute au moteur, c'est la **lisibilite du refus** : un
`check_violation` PostgreSQL sort en 500 s'il n'est pas traduit, et « erreur
serveur » n'apprend rien a l'agent qui declarait un avancement.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError
from django.utils import timezone

from activite.lecture import ORIGINES_VERS_FRONT, _visibles
from activite.modeles import (
    Activite,
    ActiviteIndicateur,
    ActiviteStructure,
    ActiviteSuspension,
    AxeStrategique,
    Exercice,
    IndicateurMesure,
    InstructionActivite,
    Obligation,
    PlanActions,
    Tache,
)
from noyau.erreurs import ErreurMetier, EtatInvalide, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur as contexte_acteur
from noyau.journal.service import inscrire
from noyau.notifications import services as notifications
from noyau.organisation.modeles import Structure
from noyau.organisation.tete import responsable_a_relancer, responsable_de

# =====================================================================
#  Acces
# =====================================================================


def _activite_ecrivable(agent: Utilisateur, activite_id: int) -> Activite:
    """
    L'activite, si l'agent la voit.

    **Le perimetre borne l'ecriture comme la lecture.** Une route d'ecriture qui
    chargerait l'objet sans passer par `_visibles()` permettrait de modifier ce
    qu'on ne peut pas lire — la faille est silencieuse et complete.
    """
    activite = _visibles(agent).filter(pk=activite_id).select_related("plan").first()
    if activite is None:
        raise HorsPerimetre("Activite introuvable.")
    return activite


def _refuser_si_suspendue(activite: Activite) -> None:
    """
    §19. Le moteur le refuse aussi, et c'est lui qui fait foi ; ce controle-ci
    ne sert qu'a rendre le refus intelligible avant que PostgreSQL ne le crie.
    """
    if activite.etat == Activite.SUSPENDUE:
        raise EtatInvalide(
            f"L'activite « {activite.intitule} » est suspendue : "
            "l'avancement ne peut pas etre modifie tant que la suspension n'est pas levee.",
            code="activite_suspendue",
        )


def _axe(libelle: str) -> AxeStrategique:
    """
    Le referentiel est **ferme** : trois axes, jamais de saisie libre. Un axe
    inconnu est une erreur de l'appelant, pas une valeur a creer.
    """
    axe = AxeStrategique.objects.filter(libelle_court=libelle, valide_au__isnull=True).first()
    if axe is None:
        connus = ", ".join(
            AxeStrategique.objects.filter(valide_au__isnull=True).values_list(
                "libelle_court", flat=True
            )
        )
        raise ErreurMetier(
            f"Axe strategique « {libelle} » inconnu. Les axes sont : {connus}.",
            code="axe_inconnu",
        )
    return axe


def _agent(identifiant: int | None) -> Utilisateur | None:
    """
    Le front designe le responsable par son **identifiant** — ADR 020.

    Il l'a designe par son nom jusqu'au 16 aout 2026, et le champ etait libre :
    le serveur comparait la saisie au `nom_complet` caractere par caractere, et
    refusait tout le reste en 409. Deux homonymes actifs etaient refuses aussi,
    sans qu'aucune saisie ne puisse les departager. L'identifiant supprime les
    deux cas d'un coup.

    Un compte inactif ou invalide reste refuse : designer comme responsable
    quelqu'un qui a quitte l'institution produit une echeance que personne ne
    tiendra.

    `None` en entree rend `None` : le point focal d'une activite est facultatif
    depuis l'ADR 047. Les appelants pour qui l'agent reste obligatoire — une
    instruction du DG — passent par `_agent_exige()`.
    """
    if identifiant is None:
        return None

    agent = Utilisateur.objects.actifs().filter(pk=identifiant).first()
    if agent is None:
        raise ErreurMetier(
            "L'agent designe n'existe pas ou n'est plus actif.", code="agent_inconnu"
        )
    return agent


def _agent_exige(identifiant: int) -> Utilisateur:
    """Meme chose, la ou l'agent reste obligatoire — une instruction du DG."""
    agent = _agent(identifiant)
    if agent is None:
        raise ErreurMetier("Aucun agent designe.", code="agent_absent")
    return agent


def _date(valeur: str, champ: str) -> date:
    try:
        return datetime.strptime(valeur, "%Y-%m-%d").date()
    except ValueError:
        raise ErreurMetier(
            f"La date « {valeur} » ({champ}) n'est pas au format AAAA-MM-JJ.",
            code="date_invalide",
        ) from None


def _mois(valeur: str, champ: str, *, borne: str) -> date:
    """
    La periode d'une activite se saisit au **mois**, pas au jour.

    Un plan d'actions annuel s'ecrit en mois : « de mars a decembre ». Demander
    un quantieme obligeait a inventer un chiffre — le 1er, le 15 — que personne
    ne tenait, et deux activites identiques se retrouvaient decalees de
    quatorze jours sans que cela veuille rien dire.

    La colonne reste une `DATE` : le retard, l'avancement attendu et les
    agregats se calculent au jour, et un mois stocke comme tel aurait oblige
    chaque consommateur a choisir sa propre convention. La conversion est donc
    faite **ici, une fois** — `debut` au premier jour du mois, `fin` au
    dernier, faute de quoi une activite de decembre serait en retard des le 2.

    `AAAA-MM-JJ` reste accepte en entree : les activites deja saisies gardent
    leur quantieme, et l'appelant qui en fournit un sait ce qu'il fait.
    """
    if len(valeur) == 10:
        return _date(valeur, champ)

    try:
        premier = datetime.strptime(valeur, "%Y-%m").date()
    except ValueError:
        raise ErreurMetier(
            f"La periode « {valeur} » ({champ}) n'est pas au format AAAA-MM.",
            code="mois_invalide",
        ) from None

    if borne == "debut":
        return premier
    # `monthrange` plutot que `relativedelta` : `dateutil` n'est qu'une
    # dependance transitive du depot, et le dernier jour du mois se calcule
    # sans elle.
    return premier.replace(day=monthrange(premier.year, premier.month)[1])


def _sigles_associes(saisie) -> list[str]:
    """
    Les sigles co-responsables de la saisie, absents des appelants anterieurs.

    Le semis de demonstration imite les schemas Ninja avec des `SimpleNamespace`
    nus, qui n'ont pas les valeurs par defaut d'un `Schema`. Lire l'attribut
    sans precaution y ferait tomber la creation d'activite sur un
    `AttributeError` que rien n'annonce.
    """
    return list(getattr(saisie, "structuresAssociees", None) or [])


# =====================================================================
#  Taches — ADR 049
# =====================================================================

#: RG-3. La somme exacte, au centieme : les colonnes sont en NUMERIC(5,2).
CENT = Decimal("100.00")
CENTIEME = Decimal("0.01")


@dataclass
class TacheValide:
    """Une ligne de saisie de tache, controlee et convertie."""

    id: int | None
    libelle: str
    valeur_prevue: Decimal
    date_debut: date
    date_fin: date


def _valeur(valeur: float, champ: str) -> Decimal:
    """
    Un nombre de points, au centieme — la precision de la colonne.

    `Decimal(str(...))` et non `Decimal(valeur)` : `Decimal(0.1)` porte les
    cinquante decimales binaires du flottant, et la somme de trois tiers ne
    tomberait jamais sur 100. Une saisie plus fine que le centieme est refusee
    plutot qu'arrondie : l'arrondi silencieux est exactement ce qui fait qu'une
    somme affichee a 100 vaut 99,99 en base.
    """
    try:
        montant = Decimal(str(valeur))
    except InvalidOperation:
        raise ErreurMetier(
            f"« {valeur} » n'est pas un nombre ({champ}).", code="valeur_invalide"
        ) from None
    if not montant.is_finite() or montant.quantize(CENTIEME) != montant:
        raise ErreurMetier(
            f"« {valeur} » ({champ}) se saisit au centieme de point.", code="valeur_trop_precise"
        )
    return montant.quantize(CENTIEME)


def _points(valeur: Decimal | float) -> str:
    """« 15,5 » plutot que « 15.50 » : ce libelle part dans la fiche de vie."""
    return f"{Decimal(valeur):.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _mois_de_tache(valeur: str, champ: str, *, borne: str) -> date:
    """
    RG-8. Une tache se situe au **mois**, sans quantieme.

    `_mois()` accepte encore `AAAA-MM-JJ` pour les activites deja saisies ;
    une tache n'a pas cet heritage, et un jour saisi ici serait tronque sans
    que l'appelant le sache.
    """
    if len(valeur or "") != 7:
        raise ErreurMetier(
            f"La periode « {valeur} » ({champ}) n'est pas au format AAAA-MM.",
            code="mois_invalide",
        )
    return _mois(valeur, champ, borne=borne)


def _dans_la_periode(debut: date, fin: date, activite_debut: date, activite_fin: date) -> bool:
    """
    RG-9, au mois. Une activite saisie avant le passage au mois peut porter un
    quantieme (le 15 mars) ; sa tache de mars n'en sort pas pour autant.
    """
    return (debut.year, debut.month) >= (activite_debut.year, activite_debut.month) and (
        fin.year,
        fin.month,
    ) <= (activite_fin.year, activite_fin.month)


def _taches_valides(saisies, activite_debut: date, activite_fin: date) -> list[TacheValide]:
    """
    Controle la liste des taches d'une activite, **entiere** — ADR 049.

    Porte les trois regles qui ne tiennent pas dans une ligne, et donc pas dans
    une contrainte `CHECK` : RG-1 (au moins une), RG-3 (somme a 100), RG-9
    (dans la periode de l'activite, qui est une autre table). Les bornes de
    chaque ligne (RG-2, RG-8) sont aussi au moteur ; elles sont redites ici pour
    que le refus nomme la tache fautive.
    """
    if not saisies:
        raise ErreurMetier(
            "Une activite se decoupe en au moins une tache (RG-1).", code="taches_absentes"
        )

    valides: list[TacheValide] = []
    for rang, saisie in enumerate(saisies, start=1):
        libelle = (saisie.libelle or "").strip()
        nom = f"« {libelle} »" if libelle else f"n° {rang}"
        if not libelle:
            raise ErreurMetier(f"La tache {nom} n'a pas de libelle.", code="libelle_exige")

        prevue = _valeur(saisie.valeurPrevue, f"valeur prevue de la tache {nom}")
        if not Decimal("0") < prevue <= CENT:
            raise ErreurMetier(
                f"La tache {nom} doit valoir plus de 0 et au plus 100 points (RG-2).",
                code="valeur_prevue_hors_borne",
            )

        debut = _mois_de_tache(saisie.moisDebut, f"mois de debut de la tache {nom}", borne="debut")
        fin = _mois_de_tache(saisie.moisFin, f"mois de fin de la tache {nom}", borne="fin")
        if fin < debut:
            raise ErreurMetier(
                f"Le mois de fin de la tache {nom} precede son mois de debut.",
                code="periode_invalide",
            )
        if not _dans_la_periode(debut, fin, activite_debut, activite_fin):
            raise ErreurMetier(
                f"La tache {nom} ({saisie.moisDebut} a {saisie.moisFin}) sort de la periode "
                f"de l'activite ({activite_debut:%Y-%m} a {activite_fin:%Y-%m}) (RG-9).",
                code="tache_hors_periode",
            )

        valides.append(
            TacheValide(
                id=getattr(saisie, "id", None),
                libelle=libelle,
                valeur_prevue=prevue,
                date_debut=debut,
                date_fin=fin,
            )
        )

    identifiants = [t.id for t in valides if t.id is not None]
    if len(identifiants) != len(set(identifiants)):
        raise ErreurMetier("Une meme tache figure deux fois dans la liste.", code="tache_en_double")

    total = sum((t.valeur_prevue for t in valides), Decimal("0"))
    if total != CENT:
        raise ErreurMetier(
            f"Les valeurs prevues des taches totalisent {_points(total)} points : "
            "elles doivent faire exactement 100 (RG-3).",
            code="somme_taches",
        )
    return valides


def _creer_taches(agent: Utilisateur, activite: Activite, taches: list[TacheValide]) -> None:
    for rang, tache in enumerate(taches, start=1):
        Tache.objects.create(
            activite=activite,
            intitule=tache.libelle,
            valeur_prevue=tache.valeur_prevue,
            date_debut=tache.date_debut,
            date_fin=tache.date_fin,
            ordre=rang,
            cree_par=agent.pk,
        )


def _decrire_taches(taches: list[TacheValide]) -> list[dict]:
    """La liste telle qu'elle part dans `donnees` : relisible sans jointure."""
    return [
        {
            "libelle": t.libelle,
            "valeurPrevue": float(t.valeur_prevue),
            "moisDebut": f"{t.date_debut:%Y-%m}",
            "moisFin": f"{t.date_fin:%Y-%m}",
        }
        for t in taches
    ]


def _tache(activite: Activite, tache_id: int) -> Tache:
    """La tache en vigueur, si elle appartient bien a l'activite lue."""
    tache = activite.taches.filter(pk=tache_id, invalide_le__isnull=True).first()
    if tache is None:
        raise HorsPerimetre("Tache introuvable.")
    return tache


# =====================================================================
#  Activite
# =====================================================================


def creer_activite(agent: Utilisateur, saisie) -> Activite:
    """
    Inscrit une activite au plan de la structure de l'agent.

    Le plan de l'exercice en cours est cree s'il n'existe pas : demander a un
    point focal d'ouvrir un plan vide avant sa premiere activite serait une
    etape administrative sans objet.

    **Les taches se saisissent avec l'activite** (RG-1, ADR 049) : l'activite
    n'a pas d'avancement propre, et une activite sans tache n'aurait aucun
    moyen d'en recevoir un. Tout est controle avant la premiere ecriture — une
    somme a 90 ne laisse pas derriere elle une activite a moitie creee.
    """
    debut = _mois(saisie.debut, "debut", borne="debut")
    fin = _mois(saisie.fin, "fin", borne="fin")
    if fin < debut:
        raise ErreurMetier("Le mois de fin precede le mois de debut.", code="periode_invalide")

    # `getattr` : un appelant anterieur a l'ADR 049 recoit le refus de RG-1,
    # et non un `AttributeError` qui sortirait en 500.
    taches = _taches_valides(getattr(saisie, "taches", None), debut, fin)
    responsable = _agent(saisie.responsableId)
    plan = _plan_de_travail(agent)
    associees = _structures_a_associer(agent, plan, _sigles_associes(saisie))

    with contexte_acteur(agent):
        activite = Activite.objects.create(
            plan=plan,
            axe_strategique=_axe(saisie.axe),
            intitule=saisie.intitule,
            objectif=saisie.objectif,
            etat_reference=saisie.etatReferenceGeneral,
            resultats_attendus=saisie.resultatsAttendus,
            budget_valide=saisie.budgetValide,
            responsable=responsable,
            date_debut=debut,
            date_fin=fin,
            cree_par=agent.pk,
        )
        # Le code vient d'un declencheur BEFORE INSERT : Django ne relit pas la
        # ligne, et l'objet en memoire porte la chaine vide. Voir pieges.md.
        activite.refresh_from_db()
        ActiviteStructure.objects.bulk_create(
            [
                ActiviteStructure(activite=activite, structure=structure, cree_par=agent.pk)
                for structure in associees
            ]
        )
        _creer_taches(agent, activite, taches)
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="activite_creee",
            libelle=f"Activite « {activite.intitule} » inscrite au plan",
            detail=(
                f"Reference {activite.code}, portee par {plan.structure.code}"
                + (f" avec {', '.join(s.code for s in associees)}" if associees else " seule")
                + f", decoupee en {len(taches)} tache(s)"
                + (f". Point focal : {responsable.nom_complet}." if responsable else ".")
            ),
            acteur=agent,
            donnees={
                "reference": activite.code,
                "axe": saisie.axe,
                "structurePorteuse": plan.structure.code,
                "structuresAssociees": [s.code for s in associees],
                "taches": _decrire_taches(taches),
            },
        )
    return activite


def _structures_a_associer(
    agent: Utilisateur, plan: PlanActions, sigles: list[str]
) -> list[Structure]:
    """
    Les structures co-responsables designees, verifiees — ADR 047.

    Deux refus seulement :

     * un sigle inconnu ou une structure abrogee : le rattachement s'ouvrirait
       sur rien, et l'agent croirait avoir associe quelqu'un ;
     * la structure porteuse : elle repond deja de l'activite par son plan.
       L'inscrire ici ferait exister deux verites — le defaut que l'entete du
       modele `Activite` proscrit.

    **Le perimetre de l'agent ne borne pas ce choix**, et c'est delibere : une
    activite transverse associe une autre direction, precisement une que le
    point focal ne lit pas. Meme raison qu'a l'ADR 020 pour l'annuaire des
    agents — designer n'est pas lire. Associer une structure lui **ouvre** la
    visibilite ; c'est le geste, pas un effet de bord a prevenir.

    `agent` sert a la trace, pas au filtrage : c'est lui qui repondra du
    rattachement dans la fiche de vie.
    """
    demandes = list(dict.fromkeys(sigle.strip() for sigle in sigles if sigle.strip()))
    if not demandes:
        return []

    if plan.structure.code in demandes:
        raise ErreurMetier(
            f"{plan.structure.code} porte deja l'activite par son plan : "
            "elle n'a pas a figurer parmi les structures associees.",
            code="structure_porteuse_associee",
        )

    trouvees = {
        structure.code: structure
        for structure in Structure.objects.filter(code__in=demandes, valide_au__isnull=True)
    }
    inconnues = [sigle for sigle in demandes if sigle not in trouvees]
    if inconnues:
        raise ErreurMetier(
            f"Structure inconnue ou abrogee : {', '.join(inconnues)}.",
            code="structure_inconnue",
        )

    return [trouvees[sigle] for sigle in demandes]


def _rapprocher_structures(
    agent: Utilisateur, activite: Activite, voulues: list[Structure]
) -> tuple[list[Structure], list[Structure]]:
    """
    Aligne les rattachements en vigueur sur la liste soumise.

    La liste fait foi : ce qui s'y ajoute est cree, ce qui n'y figure plus est
    **invalide** et non supprime — savoir qui repondait de l'activite au
    trimestre precedent fait partie de ce que la fiche de vie doit montrer.

    Un rattachement retire puis redemande produit une ligne neuve : l'unicite
    au moteur est partielle, et l'historique du retrait reste lisible.
    """
    en_vigueur = {
        rattachement.structure.code: rattachement
        for rattachement in activite.structures_associees.filter(
            invalide_le__isnull=True
        ).select_related("structure")
    }
    demandes = {structure.code: structure for structure in voulues}

    ajoutees = [structure for code, structure in demandes.items() if code not in en_vigueur]
    retirees = [
        rattachement.structure for code, rattachement in en_vigueur.items() if code not in demandes
    ]

    ActiviteStructure.objects.bulk_create(
        [
            ActiviteStructure(activite=activite, structure=structure, cree_par=agent.pk)
            for structure in ajoutees
        ]
    )
    if retirees:
        activite.structures_associees.filter(
            invalide_le__isnull=True, structure__in=retirees
        ).update(invalide_le=timezone.now(), invalide_par=agent.pk)

    return ajoutees, retirees


def _plan_de_travail(agent: Utilisateur) -> PlanActions:
    """
    Le plan de la structure de l'agent pour l'exercice ouvert.

    **Un plan valide n'accepte plus d'activite.** Le cycle du plan n'est pas
    arbitre (A5) : faute de mecanisme d'avenant, ajouter une activite a un plan
    valide reviendrait a modifier apres coup ce que la DCG a approuve.
    """
    if agent.structure is None:
        raise ErreurMetier(
            "Votre compte n'est rattache a aucune structure : "
            "impossible de savoir a quel plan inscrire l'activite.",
            code="sans_structure",
        )

    exercice = Exercice.objects.filter(ouvert=True).order_by("-annee").first()
    if exercice is None:
        raise EtatInvalide(
            "Aucun exercice n'est ouvert. Un exercice clos n'accepte plus de saisie.",
            code="exercice_clos",
        )

    plan, cree = PlanActions.objects.get_or_create(
        structure=agent.structure, exercice=exercice, defaults={"cree_par": agent.pk}
    )
    if not cree and plan.statut == PlanActions.VALIDE:
        raise EtatInvalide(
            f"Le plan {exercice.annee} de {agent.structure} est valide : "
            "il ne peut plus recevoir d'activite. Voir docs/questions-ouvertes.md, A5.",
            code="plan_valide",
        )
    return plan


def modifier_activite(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    Le motif alimente la fiche de vie : sans lui, la modification s'oublie.

    **RG-9 joue dans les deux sens.** Resserrer la periode de l'activite sur
    des taches qui en sortiraient est refuse : la tache devrait etre
    redecoupee d'abord, par `remplacer_taches()`. Les deplacer d'office
    reviendrait a reecrire un calendrier que personne n'a saisi.
    """
    activite = _activite_ecrivable(agent, activite_id)
    debut = _mois(saisie.debut, "debut", borne="debut")
    fin = _mois(saisie.fin, "fin", borne="fin")
    if fin < debut:
        raise ErreurMetier("Le mois de fin precede le mois de debut.", code="periode_invalide")

    hors_periode = [
        tache.intitule
        for tache in activite.taches.filter(invalide_le__isnull=True)
        if not _dans_la_periode(tache.date_debut, tache.date_fin, debut, fin)
    ]
    if hors_periode:
        raise ErreurMetier(
            "La nouvelle periode exclurait des taches : "
            + ", ".join(f"« {intitule} »" for intitule in hors_periode)
            + ". Modifiez leurs mois avant de resserrer l'activite (RG-9).",
            code="tache_hors_periode",
        )

    with contexte_acteur(agent):
        activite.axe_strategique = _axe(saisie.axe)
        activite.intitule = saisie.intitule
        activite.objectif = saisie.objectif
        activite.etat_reference = saisie.etatReferenceGeneral
        activite.resultats_attendus = saisie.resultatsAttendus
        activite.budget_valide = saisie.budgetValide
        activite.responsable = _agent(saisie.responsableId)
        activite.date_debut = debut
        activite.date_fin = fin
        activite.modifie_le = timezone.now()
        activite.modifie_par = agent.pk
        activite.save()

        voulues = _structures_a_associer(agent, activite.plan, _sigles_associes(saisie))
        ajoutees, retirees = _rapprocher_structures(agent, activite, voulues)

        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="activite_modifiee",
            libelle=f"Activite « {activite.intitule} » modifiee",
            detail=saisie.motif,
            acteur=agent,
        )
        # Un evenement distinct, et non une ligne du motif : changer qui repond
        # d'une activite change qui la voit et qui la declare (ADR 047). Cela se
        # relit dans la fiche de vie sans avoir a lire les motifs un par un.
        if ajoutees or retirees:
            _inscrire_rattachements(agent, activite, ajoutees, retirees)
    return activite


def _inscrire_rattachements(
    agent: Utilisateur,
    activite: Activite,
    ajoutees: list[Structure],
    retirees: list[Structure],
) -> None:
    """La trace du changement de co-responsabilite — RNF-TRACE-01."""
    parts = []
    if ajoutees:
        parts.append(f"Associee(s) : {', '.join(s.code for s in ajoutees)}")
    if retirees:
        parts.append(f"Retiree(s) : {', '.join(s.code for s in retirees)}")

    inscrire(
        objet_type="activite",
        objet_id=activite.pk,
        type_evenement="activite_structures_modifiees",
        libelle=f"Structures responsables de « {activite.intitule} » modifiees",
        detail=". ".join(parts) + ".",
        acteur=agent,
        donnees={
            "ajoutees": [s.code for s in ajoutees],
            "retirees": [s.code for s in retirees],
        },
    )


def declarer_avancement(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    La declaration d'avancement — le geste le plus frequent du pilier.

    **Elle porte sur une tache, jamais sur l'activite** (RG-4, ADR 049). La
    structure declare la valeur obtenue par la tache, en points de l'activite
    (RG-5) ; le declencheur `maj_avancement_activite()` en fait la somme
    (RG-7). Il n'y a plus d'avancement d'activite a saisir, donc plus rien a
    ecrire par-dessus la somme des taches.

    **Cumulative, comme l'etait l'avancement de l'activite** : la valeur
    declaree remplace la precedente. Elle peut redescendre — une declaration
    trop optimiste se corrige par la meme voie, avec sa justification.

    **La justification est exigee.** Le §15 demande « pourcentage + observation »,
    et c'est sur cette observation que la DSR s'appuie pour recalibrer
    (ADR 030) : un taux declare sans un mot ne se conteste pas, il se subit.
    """
    activite = _activite_ecrivable(agent, activite_id)
    _refuser_si_suspendue(activite)
    tache = _tache(activite, saisie.tacheId)

    valeur = _valeur(saisie.valeurObtenue, "valeur obtenue")
    if not Decimal("0") <= valeur <= tache.valeur_prevue:
        raise ErreurMetier(
            f"La tache « {tache.intitule} » vaut {_points(tache.valeur_prevue)} points : "
            f"sa valeur obtenue se declare entre 0 et {_points(tache.valeur_prevue)} (RG-6).",
            code="valeur_obtenue_hors_borne",
        )

    observation = (saisie.observation or "").strip()
    if not observation:
        raise ErreurMetier(
            "Une declaration d'avancement s'accompagne de sa justification.",
            code="observation_exigee",
        )

    precedente = tache.valeur_obtenue
    with contexte_acteur(agent):
        try:
            Tache.objects.filter(pk=tache.pk).update(
                valeur_obtenue=valeur, modifie_le=timezone.now(), modifie_par=agent.pk
            )
        except IntegrityError as erreur:
            raise _traduire(erreur, activite) from erreur

        activite.refresh_from_db()
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="avancement_declare",
            libelle=(
                f"Avancement declare : « {tache.intitule} » a {_points(valeur)} "
                f"sur {_points(tache.valeur_prevue)} points"
            ),
            detail=observation,
            acteur=agent,
            donnees={
                "tache": tache.pk,
                "valeurObtenue": float(valeur),
                "valeurPrecedente": float(precedente),
                "avancement": float(activite.avancement_calcule),
            },
        )
    return activite


def remplacer_taches(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    Redecoupe une activite : la liste soumise fait foi — ADR 049.

    RG-3 se controle ici, sur la liste entiere, parce qu'elle ne se controle
    pas tache par tache : passer de 50/50 a 30/70 transite forcement par une
    somme fausse.

    Deux refus protegent ce qui a deja ete declare :

     * **retirer une tache qui porte un avancement.** La retirer ferait
       disparaitre des points de l'activite sans declaration ni justification.
       La structure la ramene a zero par une declaration, qui s'explique dans
       la fiche de vie, puis la retire ;
     * **ramener une valeur prevue sous ce qui est obtenu ou retenu.** RG-6 le
       refuse, et le moteur aussi ; le refus nomme la tache.

    Une tache retiree est **invalidee**, pas supprimee : `decision_effet` peut
    la citer, et savoir comment l'activite etait decoupee au trimestre
    precedent fait partie de sa vie.

    L'ordre des ecritures n'est pas indifferent : invalider, puis mettre a
    jour, puis creer. A aucun moment la somme des valeurs obtenues ne monte,
    et `activite_avancement_borne` ne peut pas crier en cours de route.
    """
    activite = _activite_ecrivable(agent, activite_id)

    motif = (saisie.motif or "").strip()
    if not motif:
        raise ErreurMetier(
            "Un redecoupage de l'activite s'ecrit avec son motif.", code="motif_exige"
        )

    valides = _taches_valides(saisie.taches, activite.date_debut, activite.date_fin)
    en_vigueur = {t.pk: t for t in activite.taches.filter(invalide_le__isnull=True)}

    for valide in valides:
        if valide.id is not None and valide.id not in en_vigueur:
            raise HorsPerimetre("Tache introuvable.")

    gardees = {t.id for t in valides if t.id is not None}
    retirees = [tache for pk, tache in en_vigueur.items() if pk not in gardees]
    avancees = [tache for tache in retirees if tache.valeur_obtenue > 0 or tache.valeur_retenue > 0]
    if avancees:
        raise EtatInvalide(
            "Une tache qui porte un avancement ne se retire pas : "
            + ", ".join(
                f"« {t.intitule} » ({_points(max(t.valeur_obtenue, t.valeur_retenue))} points)"
                for t in avancees
            )
            + ". Ramenez-la a zero par une declaration, puis retirez-la.",
            code="tache_avancee_retiree",
        )

    for valide in valides:
        if valide.id is None:
            continue
        existante = en_vigueur[valide.id]
        plancher = max(existante.valeur_obtenue, existante.valeur_recalibree or Decimal("0"))
        if valide.valeur_prevue < plancher:
            raise ErreurMetier(
                f"La tache « {valide.libelle} » a deja obtenu {_points(plancher)} points : "
                "sa valeur prevue ne peut pas descendre en dessous (RG-6).",
                code="valeur_prevue_sous_obtenue",
            )

    maintenant = timezone.now()
    with contexte_acteur(agent):
        try:
            if retirees:
                activite.taches.filter(pk__in=[t.pk for t in retirees]).update(
                    invalide_le=maintenant, invalide_par=agent.pk
                )
            for rang, valide in enumerate(valides, start=1):
                if valide.id is None:
                    continue
                existante = en_vigueur[valide.id]
                existante.intitule = valide.libelle
                existante.valeur_prevue = valide.valeur_prevue
                existante.date_debut = valide.date_debut
                existante.date_fin = valide.date_fin
                existante.ordre = rang
                existante.modifie_le = maintenant
                existante.modifie_par = agent.pk
                existante.save(
                    update_fields=[
                        "intitule",
                        "valeur_prevue",
                        "date_debut",
                        "date_fin",
                        "ordre",
                        "modifie_le",
                        "modifie_par",
                    ]
                )
            for rang, valide in enumerate(valides, start=1):
                if valide.id is None:
                    Tache.objects.create(
                        activite=activite,
                        intitule=valide.libelle,
                        valeur_prevue=valide.valeur_prevue,
                        date_debut=valide.date_debut,
                        date_fin=valide.date_fin,
                        ordre=rang,
                        cree_par=agent.pk,
                    )
        except IntegrityError as erreur:
            raise _traduire(erreur, activite) from erreur

        activite.refresh_from_db()
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="activite_taches_modifiees",
            libelle=f"Taches de « {activite.intitule} » redecoupees",
            detail=motif,
            acteur=agent,
            donnees={
                "taches": _decrire_taches(valides),
                "retirees": [t.intitule for t in retirees],
            },
        )
    return activite


def recalibrer(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    La DSR retient, sur une tache, une autre valeur que celle declaree —
    ADR 030, descendu a la tache par l'ADR 049.

    Le recalibrage portait sur l'activite. Depuis que l'avancement de
    l'activite est la somme des valeurs obtenues de ses taches (RG-7), un taux
    d'activite pose d'en haut aurait fait deux verites : la somme des taches
    d'un cote, le taux retenu de l'autre, sans rien pour les reconcilier. La
    DSR recalibre donc une tache ; le declencheur fait la somme des valeurs
    retenues, et `avancement_retenu` suit.

    Elle n'ecrit pas `valeur_obtenue` : la declaration de la structure reste
    telle qu'elle a ete faite, et c'est ce qui rend le desaccord lisible.

    **Le recalibrage tient jusqu'a ce que la DSR le leve** (`valeur` a `None`),
    y compris si la structure re-declare entre-temps. L'inverse — une nouvelle
    declaration qui efface le recalibrage — aurait rendu l'exigence sans
    effet : il aurait suffi de redeclarer pour se donner raison. Voir
    docs/questions-ouvertes.md.

    La permission `ACT_REC` n'est portee que par le profil DSR. Le perimetre
    borne quand meme l'acces : recalibrer ce qu'on ne peut pas lire n'aurait
    aucun sens.
    """
    activite = _activite_ecrivable(agent, activite_id)
    _refuser_si_suspendue(activite)
    tache = _tache(activite, saisie.tacheId)

    motif = (saisie.motif or "").strip()
    if not motif:
        raise ErreurMetier("Un recalibrage s'ecrit avec son motif.", code="motif_exige")

    valeur = None if saisie.valeur is None else _valeur(saisie.valeur, "valeur retenue")
    if valeur is not None and not Decimal("0") <= valeur <= tache.valeur_prevue:
        raise ErreurMetier(
            f"La tache « {tache.intitule} » vaut {_points(tache.valeur_prevue)} points : "
            f"la valeur retenue se situe entre 0 et {_points(tache.valeur_prevue)}.",
            code="avancement_hors_borne",
        )

    declare = tache.valeur_obtenue

    with contexte_acteur(agent):
        try:
            Tache.objects.filter(pk=tache.pk).update(
                valeur_recalibree=valeur,
                recalibrage_motif=motif,
                recalibre_le=timezone.now(),
                recalibre_par=agent.pk,
                modifie_le=timezone.now(),
                modifie_par=agent.pk,
            )
        except IntegrityError as erreur:
            raise _traduire(erreur, activite) from erreur

        activite.refresh_from_db()
        if valeur is None:
            libelle = f"Recalibrage de « {tache.intitule} » leve"
            detail = f"La valeur declaree ({_points(declare)} points) fait de nouveau foi — {motif}"
            evenement = "avancement_recalibrage_leve"
        else:
            libelle = f"« {tache.intitule} » recalibree a {_points(valeur)} points"
            detail = (
                f"Valeur retenue {_points(valeur)} points au lieu des {_points(declare)} "
                f"declares, sur {_points(tache.valeur_prevue)} prevus — {motif}"
            )
            evenement = "avancement_recalibre"

        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement=evenement,
            libelle=libelle,
            detail=detail,
            acteur=agent,
            donnees={
                "tache": tache.pk,
                "declare": float(declare),
                "retenu": float(declare if valeur is None else valeur),
                "avancementRetenu": float(activite.avancement_retenu),
            },
        )

        # La structure doit l'apprendre : un taux retenu plus bas change ce que
        # son tableau de bord affiche, et le lui laisser decouvrir seule serait
        # la meilleure facon de transformer un arbitrage en incident.
        _notifier_recalibrage(agent, activite, libelle, detail)
    return activite


def _notifier_recalibrage(
    agent: Utilisateur, activite: Activite, libelle: str, detail: str
) -> None:
    """
    Le point focal quand il y en a un, le responsable de la structure porteuse
    sinon.

    Depuis l'ADR 047 le point focal est facultatif, et une activite sans point
    focal aurait fait tomber la notification dans le vide. La porteuse repond
    de l'activite dans tous les cas : c'est elle qui a declare le taux
    recalibre. Poste de tete vacant : personne n'est notifie, et l'evenement
    inscrit plus haut reste la trace du recalibrage.
    """
    destinataire = activite.responsable or responsable_de(activite.plan.structure)
    if destinataire is None:
        return

    notifications.notifier(
        destinataire,
        type_notification="avancement_recalibre",
        libelle=f"{activite.code} — {libelle}",
        detail=detail,
        importance="alerte",
        objet_type="activite",
        objet_id=activite.pk,
        lien=f"/activites/{activite.pk}",
        acteur=agent,
    )


def _traduire(erreur: IntegrityError, activite: Activite) -> ErreurMetier:
    """
    Traduit le refus du moteur en refus lisible.

    Laissee telle quelle, une `IntegrityError` sort en 500 et l'agent lit « Le
    serveur n'a pas pu traiter la demande », ce qui ne lui apprend rien.
    """
    if "suspendue" in str(erreur):
        return EtatInvalide(
            f"L'activite « {activite.intitule} » est suspendue : "
            "l'avancement ne peut pas etre modifie.",
            code="activite_suspendue",
        )
    # Les bornes des taches (ADR 049). Le service les controle avant d'ecrire ;
    # arriver ici suppose une ecriture concurrente entre la lecture et l'ecriture.
    if "tache_valeur_obtenue_plafonnee" in str(erreur) or "tache_recalibrage_plafonne" in str(
        erreur
    ):
        return ErreurMetier(
            "La valeur depasse la part prevue de la tache (RG-6).",
            code="valeur_obtenue_hors_borne",
        )
    if "activite_avancement_borne" in str(erreur):
        return ErreurMetier(
            "L'avancement de l'activite depasserait 100 : les valeurs prevues de ses taches "
            "ne totalisent plus 100 (RG-3).",
            code="somme_taches",
        )
    return ErreurMetier("L'ecriture a ete refusee par la base.", code="refus_moteur")


# =====================================================================
#  Indicateurs
# =====================================================================


def ajouter_indicateur(agent: Utilisateur, activite_id: int, saisie) -> ActiviteIndicateur:
    """
    La cible est numerique, et cela se refuse plutot que de se contourner : un
    indicateur non chiffrable ne donne aucun taux d'atteinte, et le §16 comme le
    §20 en demandent un.
    """
    activite = _activite_ecrivable(agent, activite_id)
    with contexte_acteur(agent):
        indicateur = ActiviteIndicateur.objects.create(
            activite=activite,
            libelle=saisie.libelle,
            unite=saisie.unite,
            valeur_reference=_decimal(saisie.etatReference, "etat de reference", requis=False),
            valeur_cible=_decimal(saisie.cible, "cible"),
            ordre=activite.indicateurs.count() + 1,
            cree_par=agent.pk,
        )
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="activite_modifiee",
            libelle=f"Indicateur « {indicateur.libelle} » ajoute",
            detail=f"Cible : {saisie.cible} {saisie.unite}".strip(),
            acteur=agent,
        )
    return indicateur


def _decimal(valeur: str, champ: str, *, requis: bool = True):
    texte = (valeur or "").replace(",", ".").strip()
    if not texte:
        if requis:
            raise ErreurMetier(f"Le champ « {champ} » est obligatoire.", code="valeur_requise")
        return None
    try:
        return Decimal(texte)
    except InvalidOperation:
        raise ErreurMetier(
            f"« {valeur} » n'est pas un nombre ({champ}). Un indicateur non chiffrable "
            "ne permet aucun taux d'atteinte.",
            code="valeur_non_chiffrable",
        ) from None


def relever_indicateur(
    agent: Utilisateur, activite_id: int, indicateur_id: int, saisie
) -> IndicateurMesure:
    """
    Un releve date. **On n'ecrase jamais la valeur precedente** : c'est la suite
    des mesures qui montre une progression. Deux releves le meme jour sont une
    correction — elle remplace, elle ne s'ajoute pas.
    """
    activite = _activite_ecrivable(agent, activite_id)
    indicateur = activite.indicateurs.filter(pk=indicateur_id, invalide_le__isnull=True).first()
    if indicateur is None:
        raise HorsPerimetre("Indicateur introuvable.")

    valeur = _decimal(saisie.realise, "releve")
    with contexte_acteur(agent):
        mesure, _ = IndicateurMesure.objects.update_or_create(
            activite_indicateur=indicateur,
            date_mesure=date.today(),
            defaults={"valeur_atteinte": valeur, "saisie_par": agent},
        )
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="avancement_declare",
            libelle=f"Indicateur « {indicateur.libelle} » releve a {saisie.realise}",
            acteur=agent,
            donnees={"indicateur": indicateur.pk, "valeur": str(valeur)},
        )
    return mesure


#  Il y a eu ici un `ajouter_tache()` — une tache a la fois, avec un poids de 1
#  a 10. Il est remplace par `remplacer_taches()` (ADR 049) : une tache ajoutee
#  seule rompt la somme a 100 (RG-3) des qu'elle est creee, et la regle ne se
#  controle que sur la liste entiere. Les taches se saisissent sans
#  attributaire depuis l'ADR 048.


# =====================================================================
#  Pieces
#
#  **Ce pilier ne cree plus de piece jointe.** Il y a eu ici un `_verser_piece`
#  qui inscrivait un nom et un poids sans binaire — `empreinte_sha256=""`,
#  `chemin_stockage=""` — parce que la modale de declaration d'avancement
#  n'envoyait que ces deux champs. Les lignes produites etaient listees par
#  `GET /pieces` comme les autres, et le telechargement echouait sur
#  « le fichier est enregistre mais introuvable sur le volume » : un message qui
#  renvoie a l'exploitation pour un fichier n'ayant jamais existe.
#
#  Le televersement reel est celui de `POST /api/pieces` (ADR 017) : il lit le
#  fichier, calcule son empreinte, l'ecrit sur le volume et inscrit
#  `donnees["pieceUid"]` a l'evenement — ce que la fiche de vie relit ici meme,
#  dans `lecture._fiche_de_vie`. Un seul chemin d'ecriture, donc une seule
#  facon d'avoir tort.
#
#  Les lignes deja produites restent en base : rien ne se supprime (RF-GED-09),
#  et `PieceSortie.telechargeable` les rend honnetes a l'ecran plutot que
#  cliquables pour rien. Voir `docs/pieges.md`.
# =====================================================================


# =====================================================================
#  Suspension, instructions, relance — gestes d'autorite
# =====================================================================


def basculer_suspension(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    §19. Suspendre et reprendre.

    **On ecrit la suspension, jamais l'etat.** `activite.etat` suit par
    declencheur ; l'ecrire ici ferait exister deux verites, et un essai sur base
    neuve a deja produit une activite portant une suspension ouverte et l'etat
    « en cours ».
    """
    activite = _activite_ecrivable(agent, activite_id)
    ouverte = activite.suspensions.filter(repris_le__isnull=True).first()

    if saisie.action == "suspendre":
        if ouverte is not None:
            raise EtatInvalide("Cette activite est deja suspendue.", code="deja_suspendue")
        with contexte_acteur(agent):
            ActiviteSuspension.objects.create(
                activite=activite,
                motif=saisie.motif,
                suspendu_par=agent,
                decision_reunion=_decision(saisie.reference),
            )
            inscrire(
                objet_type="activite",
                objet_id=activite.pk,
                type_evenement="activite_suspendue",
                libelle=f"Activite « {activite.intitule} » suspendue",
                detail=saisie.motif,
                acteur=agent,
            )
    elif saisie.action == "reprendre":
        if ouverte is None:
            raise EtatInvalide("Cette activite n'est pas suspendue.", code="non_suspendue")
        with contexte_acteur(agent):
            ouverte.repris_le = timezone.now()
            ouverte.repris_par = agent
            ouverte.motif_reprise = saisie.motif
            ouverte.save()
            inscrire(
                objet_type="activite",
                objet_id=activite.pk,
                type_evenement="activite_reprise",
                libelle=f"Activite « {activite.intitule} » reprise",
                detail=saisie.motif,
                acteur=agent,
            )
    else:
        raise ErreurMetier(
            f"Action « {saisie.action} » inconnue : « suspendre » ou « reprendre ».",
            code="action_inconnue",
        )

    activite.refresh_from_db()
    return activite


def _decision(reference: str | None):
    """
    La reference d'une decision d'instance, quand le geste en decoule.

    Facultative : une suspension peut etre prononcee hors reunion. Mais une
    reference qui ne correspond a rien est une erreur, pas un silence.
    """
    from gouvernance.modeles import Engagement

    if not reference:
        return None
    decision = Engagement.objects.filter(reference=reference, invalide_le__isnull=True).first()
    if decision is None:
        raise ErreurMetier(
            f"Aucune decision ne porte la reference « {reference} ».",
            code="decision_inconnue",
        )
    return decision


def rattacher_instruction(agent: Utilisateur, activite_id: int, saisie) -> InstructionActivite:
    """
    §17. Une instruction est un **engagement date** — activite, date,
    responsable, delai — pas une ligne de commentaire.

    Le geste porte `DEC` et non `ACT_SAI` : laisser la structure inscrire
    elle-meme l'instruction qui la contraint aurait vide le §17 de son objet. Le
    DG decide, la DSR consigne.
    """
    activite = _activite_ecrivable(agent, activite_id)
    origines = {libelle: code for code, libelle in ORIGINES_VERS_FRONT.items()}
    if saisie.origine not in origines:
        raise ErreurMetier(f"Origine « {saisie.origine} » inconnue.", code="origine_inconnue")

    decision = _decision(saisie.reference)
    origine = origines[saisie.origine]
    if decision is not None and origine != InstructionActivite.DECISION_DG:
        raise ErreurMetier(
            "Une instruction verbale ne nait pas d'une reunion : "
            "une reference de decision suppose l'origine « Décision du DG ».",
            code="origine_incoherente",
        )

    with contexte_acteur(agent):
        instruction = InstructionActivite.objects.create(
            activite=activite,
            origine=origine,
            decision_reunion=decision,
            date_instruction=date.today(),
            texte=saisie.texte,
            responsable=_agent_exige(saisie.responsableId),
            echeance=_date(saisie.echeance, "echeance"),
            enregistree_par=agent,
            cree_par=agent.pk,
        )
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="instruction_rattachee",
            libelle=f"{saisie.origine} rattachee",
            detail=saisie.texte,
            acteur=agent,
            donnees={"echeance": saisie.echeance},
        )
    return instruction


def lever_instruction(
    agent: Utilisateur, activite_id: int, instruction_id: int, saisie
) -> InstructionActivite:
    """Tant que la levee n'est pas prononcee, l'instruction pese — et compte
    dans la criticite de l'activite (§20)."""
    activite = _activite_ecrivable(agent, activite_id)
    instruction = activite.instructions.filter(pk=instruction_id, invalide_le__isnull=True).first()
    if instruction is None:
        raise HorsPerimetre("Instruction introuvable.")
    if instruction.levee_le is not None:
        raise EtatInvalide("Cette instruction est deja levee.", code="deja_levee")

    with contexte_acteur(agent):
        instruction.levee_le = timezone.now()
        instruction.levee_par = agent
        instruction.commentaire_levee = saisie.commentaire
        instruction.modifie_le = timezone.now()
        instruction.modifie_par = agent.pk
        instruction.save()
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="instruction_levee",
            libelle="Instruction levee",
            detail=saisie.commentaire or None,
            acteur=agent,
        )
    return instruction


def relancer(agent: Utilisateur, activite_id: int, saisie) -> Activite:
    """
    L'escalade humaine du descriptif (§1.1), portee par `REL`.

    **La relance s'adresse au directeur de la structure chargee**, et non au
    responsable nomme de l'activite : c'est lui qui peut arbitrer, et c'est lui
    qui redescend en interne.

    Personne ne relance sa propre structure : le directeur qui recevrait la
    relance ne peut pas l'emettre. La relance passe par la table du socle —
    c'est la meme notion que pour le courrier, seule la cible change.
    """
    activite = _activite_ecrivable(agent, activite_id)

    destinataire = responsable_a_relancer(activite.plan.structure)
    if destinataire is None:
        raise ErreurMetier(
            "Aucun poste de tete n'est pourvu au-dessus de cette structure : "
            "il n'y a personne a relancer.",
            code="relance_sans_destinataire",
        )
    if destinataire.pk == agent.pk:
        raise ErreurMetier(
            "On ne relance pas sa propre structure : la relance est une escalade.",
            code="auto_relance",
        )

    with contexte_acteur(agent):
        _inscrire_relance(agent, activite, destinataire, saisie.texte)
        Activite.objects.filter(pk=activite.pk).update(derniere_relance_le=timezone.now())
        inscrire(
            objet_type="activite",
            objet_id=activite.pk,
            type_evenement="relance_emise",
            libelle=f"Relance adressee a {destinataire.nom_complet}",
            detail=saisie.texte,
            acteur=agent,
        )

        # Une relance qui n'arrive pas au relance n'est qu'une ligne de plus au
        # journal. C'est le geste d'escalade du §1.1 : le directeur doit
        # l'apprendre sans avoir a ouvrir la fiche.
        notifications.notifier(
            destinataire,
            type_notification="relance_activite",
            libelle=f"Relance sur « {activite.intitule} »",
            detail=saisie.texte,
            importance="alerte",
            objet_type="activite",
            objet_id=activite.pk,
            lien=f"/activites/{activite.pk}",
            acteur=agent,
        )
    activite.refresh_from_db()
    return activite


def _inscrire_relance(
    agent: Utilisateur, activite: Activite, destinataire: Utilisateur, texte: str
) -> None:
    """
    La table `relance` du socle, en SQL direct.

    Aucun modele ne la couvre : le pilier courrier n'est pas commence, et
    l'ouvrir pour une insertion serait disproportionne. La colonne
    `activite_id` a ete ajoutee par le schema du pilier — une relance reste une
    relance, la table n'est pas dupliquee.

    `nature = 'manuelle'` : la relance automatique viendra de la tache nocturne,
    pas d'un agent.
    """
    from django.db import connection

    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO relance (activite_id, nature, emetteur_id, destinataire_id, motif)
            VALUES (%s, 'manuelle', %s, %s, %s)
            """,
            # `destinataire_id` : le directeur de la tete, pas le
            # responsable nomme de l'activite.
            [activite.pk, agent.pk, destinataire.pk, texte],
        )


# =====================================================================
#  Plan d'actions
# =====================================================================


def changer_etat_plan(agent: Utilisateur, saisie) -> PlanActions:
    """
    Le cycle du plan : soumettre, valider, retourner.

    **Le cycle n'est pas arbitre** — retour arriere, avenant, modification d'un
    plan valide ne sont decrits par aucun document (A5). Ce qui est implemente
    est le strict minimum que les ecrans exigent, et rien de plus : inventer un
    retour arriere serait remplacer une absence par une invention.

    Les deux gestes ne portent pas la meme permission : soumettre releve de
    `ACT_SAI` — la structure —, valider et retourner de `ACT_VAL`, jamais de qui
    a soumis. La garde est sur la route ; la coherence d'etat est ici.
    """
    structure = Structure.objects.filter(code=saisie.structureSigle, valide_au__isnull=True).first()
    if structure is None:
        raise HorsPerimetre("Structure introuvable.")

    plan = (
        PlanActions.objects.filter(
            structure=structure, exercice__annee=saisie.annee, invalide_le__isnull=True
        )
        .select_related("structure", "exercice")
        .first()
    )
    if plan is None:
        raise HorsPerimetre("Aucun plan pour cette structure et cet exercice.")

    if saisie.action == "soumettre":
        return _soumettre(agent, plan)
    if saisie.action == "valider":
        return _valider(agent, plan)
    if saisie.action == "retourner":
        return _retourner(agent, plan, saisie.motif)
    raise ErreurMetier(
        f"Action « {saisie.action} » inconnue : « soumettre », « valider » ou « retourner ».",
        code="action_inconnue",
    )


def _soumettre(agent: Utilisateur, plan: PlanActions) -> PlanActions:
    if plan.statut == PlanActions.SOUMIS:
        raise EtatInvalide("Ce plan est deja soumis.", code="deja_soumis")
    if plan.statut == PlanActions.VALIDE:
        raise EtatInvalide(
            "Ce plan est valide : il ne se resoumet pas. "
            "Le mecanisme d'avenant n'est pas arbitre — voir A5.",
            code="plan_valide",
        )
    if not plan.activites.filter(invalide_le__isnull=True).exists():
        raise EtatInvalide("Un plan sans activite ne se soumet pas.", code="plan_vide")

    with contexte_acteur(agent):
        plan.statut = PlanActions.SOUMIS
        plan.soumis_le = timezone.now()
        plan.soumis_par = agent.pk
        # Le motif du renvoi precedent ne vaut plus : le laisser afficherait au
        # controle de gestion le reproche auquel la structure vient de repondre.
        plan.motif_retour = None
        plan.modifie_le = timezone.now()
        plan.modifie_par = agent.pk
        plan.save()
        _versionner(plan, agent, "Soumis au controle de gestion")
        inscrire(
            objet_type="plan_actions",
            objet_id=plan.pk,
            type_evenement="plan_soumis",
            libelle=f"Plan {plan.exercice.annee} de {plan.structure} soumis",
            acteur=agent,
        )
    return plan


def _valider(agent: Utilisateur, plan: PlanActions) -> PlanActions:
    if plan.statut != PlanActions.SOUMIS:
        raise EtatInvalide("Seul un plan soumis se valide.", code="plan_non_soumis")
    if plan.soumis_par == agent.pk:
        raise ErreurMetier("On ne valide pas le plan que l'on a soumis.", code="auto_validation")

    with contexte_acteur(agent):
        plan.statut = PlanActions.VALIDE
        plan.valide_le = timezone.now()
        plan.valide_par = agent.pk
        plan.modifie_le = timezone.now()
        plan.modifie_par = agent.pk
        plan.save()
        _versionner(plan, agent, "Valide")
        inscrire(
            objet_type="plan_actions",
            objet_id=plan.pk,
            type_evenement="plan_valide",
            libelle=f"Plan {plan.exercice.annee} de {plan.structure} valide",
            acteur=agent,
        )
    return plan


def _retourner(agent: Utilisateur, plan: PlanActions, motif: str | None) -> PlanActions:
    """Un plan renvoye sans motif n'est pas corrige : il est resoumis a
    l'identique. Le moteur le refuse aussi."""
    if plan.statut != PlanActions.SOUMIS:
        raise EtatInvalide("Seul un plan soumis se retourne.", code="plan_non_soumis")
    if not motif:
        raise ErreurMetier(
            "Un plan renvoye sans motif serait resoumis a l'identique : "
            "indiquez ce qui doit etre corrige.",
            code="motif_requis",
        )

    with contexte_acteur(agent):
        plan.statut = PlanActions.RETOURNE
        plan.motif_retour = motif
        plan.version += 1
        plan.modifie_le = timezone.now()
        plan.modifie_par = agent.pk
        plan.save()
        _versionner(plan, agent, "Retourne", motif)
        inscrire(
            objet_type="plan_actions",
            objet_id=plan.pk,
            type_evenement="plan_retourne",
            libelle=f"Plan {plan.exercice.annee} de {plan.structure} retourne",
            detail=motif,
            acteur=agent,
        )
    return plan


def _versionner(plan: PlanActions, agent: Utilisateur, statut: str, motif: str | None = None):
    """
    `champ_historique` dit quelle colonne a change ; ceci dit **pourquoi une
    version entiere a ete refaite**, et c'est cela que lit un controleur.
    """
    from activite.modeles import PlanActionsVersion

    PlanActionsVersion.objects.update_or_create(
        plan=plan,
        version=plan.version,
        defaults={"statut": statut, "motif": motif, "cree_par": agent.pk},
    )


# =====================================================================
#  Obligations
# =====================================================================


def deposer_obligation(agent: Utilisateur, obligation_id: int, saisie) -> Obligation:
    """
    Le depot de ce que la structure doit produire — §3.3.

    Un depot ne s'ecrase pas : redeposer sur une obligation deja servie
    effacerait la date qui prouve la ponctualite.
    """
    obligation = (
        Obligation.objects.filter(pk=obligation_id, structure__in=_structures_de(agent))
        .select_related("structure")
        .first()
    )
    if obligation is None:
        raise HorsPerimetre("Obligation introuvable.")
    if obligation.depose_le is not None:
        raise EtatInvalide(
            f"Cette obligation a deja ete deposee le {obligation.depose_le.isoformat()}.",
            code="deja_deposee",
        )

    with contexte_acteur(agent):
        obligation.depose_le = date.today()
        obligation.depose_par = agent
        obligation.commentaire = saisie.commentaire
        obligation.save()
        inscrire(
            objet_type="obligation",
            objet_id=obligation.pk,
            type_evenement="obligation_deposee",
            libelle=f"« {obligation.intitule} » deposee pour {obligation.periode_libelle}",
            detail=saisie.commentaire or None,
            acteur=agent,
            donnees={"fichier": saisie.nomFichier},
        )
    return obligation


def _structures_de(agent: Utilisateur):
    from activite.lecture import _structures_accessibles

    return _structures_accessibles(agent)
