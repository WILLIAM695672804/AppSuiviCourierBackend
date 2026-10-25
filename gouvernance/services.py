"""
Les regles d'ecriture du pilier gouvernance.

**Tout passe par ici, jamais par `api.py`.** Une route ouvre l'enveloppe et
appelle un service ; le service decide.

Les trois disciplines du pilier activites valent mot pour mot :

 1. **L'acteur est pose avant toute ecriture** (`with contexte_acteur(...)`).
    Le declencheur d'historisation refuse sinon, et le refus arrive parfois par
    ricochet — ici, consigner l'avancement d'une structure chargee met a jour
    `engagement`, qui est historise. Voir docs/pieges.md.
 2. **Toute ecriture inscrit un evenement** — `RNF-TRACE-01`.
 3. **On ne reecrit pas ce que le moteur tient.** La reference de l'engagement
    et son avancement viennent de declencheurs. Les recalculer ici ferait deux
    verites.

Une quatrieme, propre a ce pilier : **le perimetre borne l'ecriture comme la
lecture.** Un service qui chargerait l'engagement sans passer par
`_engagements_visibles()` permettrait de faire avancer une decision qu'on ne
peut pas lire.
"""

from datetime import date, datetime

from django.utils import timezone

from gouvernance.lecture import (
    ETATS_CONGE_VERS_FRONT,
    INSTANCES_VERS_FRONT,
    NATURES_DOCUMENT_VERS_FRONT,
    TYPES_ABSENCE_VERS_FRONT,
    TYPES_SEANCE_VERS_FRONT,
    _engagements_visibles,
    _seances_visibles,
)
from gouvernance.modeles import (
    CongeDroit,
    CongePeriode,
    Disponibilite,
    Engagement,
    EngagementObservation,
    EngagementStructure,
    Seance,
    SeanceDocument,
    SeancePoint,
)
from noyau.erreurs import ErreurMetier, EtatInvalide, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur as contexte_acteur
from noyau.journal.service import inscrire
from noyau.notifications import services as notifications
from noyau.organisation.modeles import Structure
from noyau.organisation.tete import responsable_a_relancer
from noyau.perimetre.portee import restreindre

# =====================================================================
#  Traductions et acces
# =====================================================================


def _code(table: dict[str, str], libelle: str, quoi: str) -> str:
    """
    Le code de base derriere un libelle du front.

    Un libelle inconnu est une **erreur de l'appelant**, pas une valeur a creer :
    les referentiels de ce pilier sont fermes par des contraintes CHECK, et
    laisser passer produirait un refus PostgreSQL illisible.
    """
    for code, affiche in table.items():
        if affiche == libelle:
            return code
    connus = ", ".join(table.values())
    raise ErreurMetier(
        f"{quoi} « {libelle} » inconnu. Les valeurs admises sont : {connus}.",
        code="valeur_inconnue",
    )


def _date(valeur: str, champ: str) -> date:
    try:
        return datetime.strptime(valeur, "%Y-%m-%d").date()
    except ValueError:
        raise ErreurMetier(
            f"La date « {valeur} » ({champ}) n'est pas au format AAAA-MM-JJ.",
            code="date_invalide",
        ) from None


def _agent(identifiant: int) -> Utilisateur:
    """
    Le front designe les personnes par leur **identifiant** — ADR 020.

    Meme fonction et meme histoire que dans `activite/services.py` : le champ
    etait libre, la comparaison portait sur le `nom_complet`, et deux homonymes
    actifs etaient refuses sans recours. Les deux modules restent distincts —
    un service ne s'importe pas d'un pilier a l'autre.
    """
    agent = Utilisateur.objects.actifs().filter(pk=identifiant).first()
    if agent is None:
        raise ErreurMetier(
            "L'agent designe n'existe pas ou n'est plus actif.", code="agent_inconnu"
        )
    return agent


def _agent_du_perimetre(acteur: Utilisateur, identifiant: int) -> Utilisateur:
    """
    L'agent designe, **borne au perimetre de celui qui ecrit**.

    `_agent()` ne pose aucune borne : tant que `DISPO` n'appartenait qu'a la DSR
    et au Directeur general, tous deux en portee `toutes`, la question ne se
    posait pas. Depuis que le profil `RESP` la porte (migration 0024), un
    directeur pourrait declarer l'absence d'un agent d'une autre direction.

    `HorsPerimetre` et non une erreur de droit : l'agent hors perimetre
    n'existe pas, et la route rend 404 (decision D5).
    """
    agent = _agent(identifiant)
    visibles = restreindre(
        Utilisateur.objects.filter(pk=agent.pk),
        acteur,
        champ_structure="structure",
        champ_agent="id",
    )
    if not visibles.exists():
        raise HorsPerimetre("L'agent designe n'est pas dans votre perimetre.")
    return agent


def _structure(sigle: str) -> Structure:
    structure = Structure.objects.filter(code=sigle, valide_au__isnull=True).first()
    if structure is None:
        raise ErreurMetier(f"Structure « {sigle} » inconnue.", code="structure_inconnue")
    return structure


def _engagement_ecrivable(agent: Utilisateur, engagement_id: int) -> Engagement:
    """L'engagement, si l'agent le voit. Le perimetre borne l'ecriture."""
    engagement = _engagements_visibles(agent).filter(pk=engagement_id).first()
    if engagement is None:
        raise HorsPerimetre("Decision introuvable.")
    return engagement


def _refuser_si_suspendu(engagement: Engagement) -> None:
    """
    Une decision suspendue n'avance pas.

    Meme regle que pour une activite suspendue — §19 : consigner un avancement
    sur ce qu'une autorite a arrete reviendrait a passer outre la suspension
    sans jamais la lever.
    """
    if engagement.suspendu_le is not None:
        raise EtatInvalide(
            f"La decision « {engagement.reference} » est suspendue : "
            "l'avancement ne peut pas etre modifie tant que la suspension n'est pas levee.",
            code="engagement_suspendu",
        )


# =====================================================================
#  Engagements
# =====================================================================


def creer_engagement(agent: Utilisateur, saisie) -> Engagement:
    """
    Consigne une decision d'instance et designe les structures chargees.

    **Au moins une structure**, et la premiere est pilote. Deux raisons, dans cet
    ordre : un engagement sans structure chargee n'est visible de personne
    (`_engagements_visibles()` passe par elles), et surtout personne ne repond
    quand l'instance demande ou cela en est. Meme regle que le chef de file
    d'une cotation.

    La reference — `DEC-2026-0001` — vient d'un declencheur BEFORE INSERT, sous
    verrou d'avis. Ne pas la saisir, ne pas la deviner : Django ne relit pas la
    ligne, d'ou le `refresh_from_db()`.
    """
    if not saisie.structures:
        raise ErreurMetier(
            "Une decision doit charger au moins une structure. La premiere est pilote.",
            code="structure_absente",
        )

    instance = _code(INSTANCES_VERS_FRONT, saisie.instance, "Instance")
    date_decision = _date(saisie.dateDecision, "dateDecision")
    echeance = _date(saisie.echeance, "echeance") if saisie.echeance else None
    if echeance and echeance < date_decision:
        raise ErreurMetier("L'echeance precede la date de la decision.", code="periode_invalide")

    chargees = _chargees(agent, saisie.structures)
    seance = _seance_citee(agent, saisie.seance)

    with contexte_acteur(agent):
        engagement = Engagement.objects.create(
            origine=Engagement.INSTANCE,
            instance=instance,
            seance=seance,
            date_engagement=date_decision,
            objet=saisie.objet,
            contexte=saisie.contexte or None,
            echeance=echeance,
            # `prise_par` est l'autorite qui decide, `saisie_par` l'agent qui
            # consigne. Les confondre effacerait la distinction que le §17 pose
            # entre le DG qui instruit et la DSR qui inscrit. Faute de nom
            # d'autorite dans la saisie du front, le president de la seance fait
            # foi ; sans seance, l'agent repond de sa propre inscription.
            prise_par=seance.president if seance and seance.president else agent,
            saisie_par=agent,
            cree_par=agent.pk,
        )
        engagement.refresh_from_db()

        for rang, structure in enumerate(chargees, start=1):
            EngagementStructure.objects.create(
                engagement=engagement,
                structure=structure,
                rang=rang,
                cree_par=agent.pk,
            )

        inscrire(
            objet_type="engagement",
            objet_id=engagement.pk,
            type_evenement="engagement_consigne",
            libelle=f"Decision {engagement.reference} consignee",
            detail=f"{INSTANCES_VERS_FRONT[instance]} — {engagement.objet}",
            acteur=agent,
            donnees={
                "reference": engagement.reference,
                "instance": instance,
                "structures": [s.code for s in chargees],
            },
        )
    return engagement


def _chargees(agent: Utilisateur, identifiants: list[int]) -> list[Structure]:
    """
    Les structures chargees, **dans l'ordre recu** : le front envoie le pilote en
    premier, et cet ordre est la designation.

    Un doublon est refuse plutot qu'ignore : la contrainte d'unicite du moteur
    le refuserait de toute facon, mais avec un message que personne ne lit.
    """
    if len(set(identifiants)) != len(identifiants):
        raise ErreurMetier(
            "Une structure est citee deux fois parmi les structures chargees.",
            code="structure_dupliquee",
        )
    connues = {s.pk: s for s in Structure.objects.filter(pk__in=identifiants)}
    manquantes = [i for i in identifiants if i not in connues]
    if manquantes:
        raise ErreurMetier(f"Structure(s) inconnue(s) : {manquantes}.", code="structure_inconnue")
    return [connues[i] for i in identifiants]


def _seance_citee(agent: Utilisateur, libelle: str) -> Seance | None:
    """
    La seance dont la decision est issue, si le libelle en designe une.

    Le front envoie un texte libre — « CODIR du 12 juin 2026 » ou « Instruction
    verbale du 3 aout ». **Une decision sans seance est le cas ordinaire**, pas
    une anomalie : le §17 traite l'instruction verbale du DG comme une source
    de plein droit. On rattache quand la reference correspond exactement, on
    laisse vide sinon — deviner produirait un rattachement faux et invisible.
    """
    if not libelle:
        return None
    return _seances_visibles(agent).filter(reference=libelle).first()


def consigner_avancement(agent: Utilisateur, engagement_id: int, saisie) -> Engagement:
    """
    L'avancement declare par une structure chargee, et les jalons franchis.

    **L'avancement de l'engagement n'est pas ecrit ici** : le declencheur le
    recalcule comme la moyenne des structures chargees. Ce service ecrit la
    ligne de la structure de l'agent, et rien d'autre.

    Une observation accompagne la declaration : un chiffre qui bouge sans
    explication ne se relit pas six mois plus tard.
    """
    engagement = _engagement_ecrivable(agent, engagement_id)
    _refuser_si_suspendu(engagement)

    if not 0 <= saisie.avancement <= 100:
        raise ErreurMetier("L'avancement se declare entre 0 et 100.", code="avancement_hors_bornes")

    charge = _charge_de_l_agent(agent, engagement)

    with contexte_acteur(agent):
        charge.avancement = saisie.avancement
        charge.modifie_par = agent.pk
        charge.modifie_le = timezone.now()
        charge.save()

        for jalon in engagement.jalons.filter(pk__in=saisie.jalonsFaits, fait_le__isnull=True):
            jalon.fait_le = date.today()
            jalon.modifie_par = agent.pk
            jalon.modifie_le = timezone.now()
            jalon.save()

        if saisie.observation:
            EngagementObservation.objects.create(
                engagement=engagement,
                texte=saisie.observation,
                relance=False,
                auteur=agent,
            )

        # Relu apres coup : le declencheur a recalcule la moyenne, et l'objet en
        # memoire porte encore l'ancienne.
        engagement.refresh_from_db()
        inscrire(
            objet_type="engagement",
            objet_id=engagement.pk,
            type_evenement="avancement_consigne",
            libelle=f"{charge.structure.code} declare {saisie.avancement} %",
            detail=saisie.observation or None,
            acteur=agent,
            donnees={
                "structure": charge.structure.code,
                "avancement": saisie.avancement,
                "moyenne": float(engagement.avancement),
            },
        )
    return engagement


def _charge_de_l_agent(agent: Utilisateur, engagement: Engagement) -> EngagementStructure:
    """
    La ligne que l'agent a le droit d'ecrire.

    **On ne declare que pour sa propre structure** — son rattachement et ce qui
    en depend. Laisser une direction declarer l'avancement d'une autre ferait de
    la moyenne un chiffre sans auteur, et la structure ainsi creditee ne le
    saurait jamais.

    Le rattachement, et **non le perimetre de lecture**. La distinction est
    exactement le defaut qu'un test a rattrape ici : la DSR voit toutes les
    structures, et se serait donc trouvee habilitee a declarer pour chacune.
    Voir une decision et en repondre sont deux choses — elle tient le registre,
    elle n'execute pas.

    Consequence assumee : la DSR ne consigne pas un avancement a la place d'une
    direction. Si le besoin apparait, c'est une delegation qu'il faudra poser
    — le socle en a une — et non cette garde qu'il faudra relacher.
    """
    charge = (
        engagement.structures.filter(structure_id__in=_rattachement(agent))
        .select_related("structure")
        .order_by("rang")
        .first()
    )
    if charge is None:
        raise ErreurMetier(
            "Votre structure n'est pas chargee de cette decision : "
            "elle ne peut pas en declarer l'avancement.",
            code="structure_non_chargee",
            statut=403,
        )
    return charge


def _rattachement(agent: Utilisateur):
    """
    La structure de l'agent et celles qui en dependent.

    Les descendantes sont incluses : une directrice repond de ses divisions, et
    l'exclure obligerait chaque chef de division a se connecter pour un chiffre
    que sa direction consolide deja.
    """
    if agent.structure is None:
        return Structure.objects.none()
    return agent.structure.descendants()


def relancer(agent: Utilisateur, engagement_id: int, saisie) -> EngagementObservation:
    """
    La relance de la DSR — l'escalade humaine du §1.1.

    **Ce n'est pas une observation ordinaire** : elle se compte, et la vue
    `v_engagement_etat` la fait remonter. Une decision relancee trois fois est
    un signal qui doit se voir sans ouvrir la fiche.

    On ne relance pas une decision executee : la relance perdrait tout sens, et
    le compteur ferait paraitre defaillante une structure qui a livre.
    """
    engagement = _engagement_ecrivable(agent, engagement_id)
    if engagement.execute_le is not None:
        raise EtatInvalide(
            f"La decision « {engagement.reference} » est executee : elle ne se relance pas.",
            code="engagement_execute",
        )

    structure_visee = _structure_relancee(engagement, saisie.structureId)

    # **Le directeur de la tete, pas la structure chargee.** Une decision
    # confiee a un departement se relance chez le directeur qui en repond
    # devant l'instance — c'est le sens de l'escalade du §1.1.
    destinataire = responsable_a_relancer(structure_visee)
    if destinataire is None:
        raise ErreurMetier(
            f"Aucun poste de tete n'est pourvu au-dessus de {structure_visee.code} : "
            "il n'y a personne a relancer.",
            code="relance_sans_destinataire",
        )

    with contexte_acteur(agent):
        observation = EngagementObservation.objects.create(
            engagement=engagement,
            texte=saisie.motif,
            relance=True,
            auteur=agent,
        )
        inscrire(
            objet_type="engagement",
            objet_id=engagement.pk,
            type_evenement="relance_emise",
            libelle=f"Relance adressee a {destinataire.nom_complet} ({structure_visee.code})",
            detail=saisie.motif,
            acteur=agent,
            donnees={"structure": structure_visee.code, "reference": engagement.reference},
        )

        # Une relance qu'il faut aller chercher dans la fiche n'escalade rien.
        notifications.notifier(
            destinataire,
            type_notification="relance_engagement",
            libelle=f"Relance sur la decision « {engagement.reference} »",
            detail=saisie.motif,
            importance="alerte",
            objet_type="engagement",
            objet_id=engagement.pk,
            lien=f"/gouvernance/decisions/{engagement.pk}",
            acteur=agent,
        )
    return observation


def _structure_relancee(engagement: Engagement, structure_id: int | None) -> Structure:
    """
    La structure **visee** par la relance : la pilote par defaut, c'est elle
    qui rend compte.

    Elle n'est pas le destinataire — celui-la est le directeur de sa tete, et
    `relancer()` le calcule. Le nom precedent, `_destinataire_relance`, faisait
    croire qu'une structure recevait une relance ; c'est un agent qui la recoit.

    Relancer une co-chargee reste possible — le front l'offre — mais relancer
    tout le monde par defaut diluerait la responsabilite que le rang 1 designe.
    """
    charges = list(engagement.structures.select_related("structure").order_by("rang"))
    if not charges:
        raise ErreurMetier(
            "Cette decision ne charge aucune structure : il n'y a personne a relancer.",
            code="structure_absente",
        )
    if structure_id is None:
        return charges[0].structure
    choisie = next((c for c in charges if c.structure_id == structure_id), None)
    if choisie is None:
        raise ErreurMetier(
            "La structure visee n'est pas chargee de cette decision.",
            code="structure_non_chargee",
        )
    return choisie.structure


# =====================================================================
#  Seances
# =====================================================================


def creer_seance(agent: Utilisateur, saisie) -> Seance:
    """
    Inscrit une seance au registre, avec son ordre du jour.

    **La reference est composee ici, pas par le moteur** — contrairement a celle
    d'un engagement. La raison est que rien ne la rend concurrente : une seance
    s'inscrit apres coup, par le secretariat, jamais par deux mains a la fois.
    Y poser un declencheur et un verrou d'avis aurait coute un mecanisme pour
    un risque qui n'existe pas.
    """
    type_seance = _code(TYPES_SEANCE_VERS_FRONT, saisie.type, "Type de seance")
    jour = _date(saisie.date, "date")
    echeance = _date(saisie.echeanceDepot, "echeanceDepot")
    if echeance < jour:
        raise ErreurMetier("L'echeance de depot precede la seance.", code="periode_invalide")

    structure = _structure(saisie.structure)
    president = _agent(saisie.presidentId) if saisie.presidentId else None

    with contexte_acteur(agent):
        seance = Seance.objects.create(
            reference=_reference_seance(type_seance, jour),
            type_seance=type_seance,
            intitule=saisie.intitule,
            date_seance=jour,
            president=president,
            structure=structure,
            echeance_depot=echeance,
            cree_par=agent.pk,
        )
        for rang, point in enumerate(saisie.ordreDuJour, start=1):
            SeancePoint.objects.create(
                seance=seance,
                rang=rang,
                point=point.point,
                rapporteur=_agent(point.rapporteurId) if point.rapporteurId else None,
            )
        inscrire(
            objet_type="seance",
            objet_id=seance.pk,
            type_evenement="seance_inscrite",
            libelle=f"Seance {seance.reference} inscrite au registre",
            detail=f"{TYPES_SEANCE_VERS_FRONT[type_seance]} — {seance.intitule}",
            acteur=agent,
            donnees={"reference": seance.reference, "points": len(saisie.ordreDuJour)},
        )
    return seance


#: Le prefixe de reference par type de seance. Fixe et non parametrable : ces
#: sigles figurent sur les convocations papier depuis longtemps.
PREFIXES_SEANCE = {
    "session_ca": "CA",
    "assemblee_generale": "AG",
    "codir": "CODIR",
    "reunion_dg": "RDG",
    "rapport_activite": "RA",
    "rapport_sectoriel": "RS",
}


def _reference_seance(type_seance: str, jour: date) -> str:
    """
    « CODIR-2026-003 » — le rang dans l'annee, par type.

    Le rang se calcule sur les references existantes plutot que par un
    compteur : une seance annulee et supprimee ne doit pas creer de trou que
    personne ne saura expliquer.
    """
    prefixe = PREFIXES_SEANCE[type_seance]
    debut = f"{prefixe}-{jour.year}-"
    rang = Seance.objects.filter(reference__startswith=debut).count() + 1
    return f"{debut}{rang:03d}"


def deposer_document(agent: Utilisateur, seance_id: int, saisie) -> SeanceDocument:
    """
    Le depot d'une piece de seance — ordre du jour, compte rendu, proces-verbal.

    Le fichier vit dans `piece_jointe`, comme partout ailleurs. Le contenu n'est
    pas gere ici : le front n'envoie qu'un nom et un poids, le televersement
    reel viendra avec `noyau/pieces`.

    **Un depot ne s'ecrase pas.** Redeposer un compte rendu deja servi effacerait
    la date qui prouve la ponctualite — et « hors delai » se deduit d'elle.
    """
    seance = _seances_visibles(agent).filter(pk=seance_id).first()
    if seance is None:
        raise HorsPerimetre("Seance introuvable.")

    nature = _code(NATURES_DOCUMENT_VERS_FRONT, saisie.nature, "Nature de document")
    deja = seance.documents.filter(nature=nature, depose_le__isnull=False).first()
    if deja is not None:
        raise EtatInvalide(
            f"Un document « {saisie.nature} » a deja ete depose le {deja.depose_le}.",
            code="deja_depose",
        )

    with contexte_acteur(agent):
        piece = _verser_piece(agent, seance, saisie.nomFichier, saisie.poids, saisie.libelle)
        document = SeanceDocument.objects.create(
            seance=seance,
            nature=nature,
            libelle=saisie.libelle,
            piece_jointe=piece,
            depose_le=date.today(),
            depose_par=agent,
            cree_par=agent.pk,
        )
        hors_delai = document.depose_le > seance.echeance_depot
        inscrire(
            objet_type="seance",
            objet_id=seance.pk,
            type_evenement="document_depose",
            libelle=f"{saisie.nature} de {seance.reference} depose",
            detail=f"{saisie.libelle}"
            + (f" — hors delai, echeance du {seance.echeance_depot}." if hors_delai else ""),
            acteur=agent,
            donnees={"nature": nature, "horsDelai": hors_delai},
        )
    return document


def _verser_piece(agent: Utilisateur, seance: Seance, nom: str, poids: str, motif: str):
    """
    La piece pend a l'**evenement**, pas a la seance : un document depose sans
    savoir ce qu'il justifie ne prouve rien. C'est la meme regle que pour les
    pieces des activites, et pour la meme raison.
    """
    from noyau.journal.modeles import Evenement
    from noyau.pieces.modeles import PieceJointe

    inscrire(
        objet_type="seance",
        objet_id=seance.pk,
        type_evenement="piece_versee",
        libelle=f"Piece « {nom} » versee",
        detail=motif,
        acteur=agent,
    )
    evenement = (
        Evenement.objects.filter(objet_type="seance", objet_id=seance.pk)
        .order_by("-survenu_le")
        .first()
    )
    return PieceJointe.objects.create(
        objet_type="evenement",
        objet_id=evenement.pk if evenement else None,
        nom_fichier=nom,
        nom_original=nom,
        taille_octets=_octets(poids),
        empreinte_sha256="",
        chemin_stockage="",
        categorie="justificatif",
        cree_par=agent.pk,
    )


def _octets(poids: str) -> int:
    """« 1.2 Mo » vers un nombre d'octets. Le front n'envoie pas le fichier."""
    texte = (poids or "").strip().lower().replace(",", ".")
    facteurs = {"mo": 1024 * 1024, "ko": 1024, "o": 1}
    for suffixe, facteur in facteurs.items():
        if texte.endswith(suffixe):
            try:
                return int(float(texte[: -len(suffixe)].strip()) * facteur)
            except ValueError:
                return 0
    return 0


# =====================================================================
#  Disponibilite
# =====================================================================


def declarer_absence(agent: Utilisateur, saisie) -> Disponibilite:
    """
    Enregistre une absence decidee — §3.3.

    **Le chevauchement est refuse par le moteur** (contrainte d'exclusion GiST),
    et c'est bien lui qui fait foi : aucun controle applicatif ne tient cette
    garantie sous concurrence. Le service ne fait que rendre le refus lisible
    avant que PostgreSQL ne le crie.

    Une absence **sans interimaire** est acceptee. C'est meme le cas que la DSR
    doit voir : le refuser obligerait a inventer un interimaire pour pouvoir
    saisir, et le registre ne signalerait plus rien.
    """
    du = _date(saisie.du, "du")
    au = _date(saisie.au, "au")
    if au < du:
        raise ErreurMetier("La date de fin precede la date de debut.", code="periode_invalide")

    absent = _agent_du_perimetre(agent, saisie.responsableId)
    interimaire = _agent_du_perimetre(agent, saisie.interimaireId) if saisie.interimaireId else None
    if interimaire is not None and interimaire.pk == absent.pk:
        raise ErreurMetier(
            "Un responsable ne peut pas assurer son propre interim.",
            code="interimaire_identique",
        )

    _refuser_chevauchement(absent, du, au)

    with contexte_acteur(agent):
        absence = Disponibilite.objects.create(
            utilisateur=absent,
            type_absence=_code(TYPES_ABSENCE_VERS_FRONT, saisie.type, "Type d'absence"),
            du=du,
            au=au,
            interimaire=interimaire,
            saisi_par=agent,
            cree_par=agent.pk,
        )
        inscrire(
            objet_type="disponibilite",
            objet_id=absence.pk,
            type_evenement="absence_declaree",
            libelle=f"{absent.nom_complet} absent du {du} au {au}",
            detail=f"Interim assure par {interimaire.nom_complet}."
            if interimaire
            else "Aucun interimaire designe.",
            acteur=agent,
            donnees={"type": saisie.type, "sansInterim": interimaire is None},
        )
    return absence


def _refuser_chevauchement(absent: Utilisateur, du: date, au: date) -> None:
    chevauchante = (
        Disponibilite.objects.filter(utilisateur=absent, invalide_le__isnull=True, du__lte=au)
        .filter(au__gte=du)
        .first()
    )
    if chevauchante is not None:
        raise EtatInvalide(
            f"{absent.nom_complet} est deja declare absent du {chevauchante.du} "
            f"au {chevauchante.au}. Deux absences simultanees rendraient la question "
            "« qui le remplace ? » sans reponse.",
            code="absence_chevauchante",
        )


# =====================================================================
#  Conges
# =====================================================================
#
#  **A ne pas confondre avec la disponibilite.** `declarer_absence` enregistre
#  une absence decidee ; ces trois services arbitrent des souhaits avant
#  qu'ils ne le deviennent.
#
#  Qui planifie pour qui : le directeur de la tete de structure, pour tout son
#  sous-arbre. La sous-structure n'existe pas au-dessus de son chef, et un
#  arbitrage a deux etages aurait produit deux plannings concurrents. La borne
#  est le perimetre, posee par `_agent_du_perimetre`.
# =====================================================================


def ouvrir_droit_conges(agent: Utilisateur, saisie) -> CongeDroit:
    """
    Les droits a conges d'un agent pour une annee.

    **Le nombre de jours vient de la DRH.** L'anciennete, les reports et les
    majorations sont son affaire ; les calculer ici redirait une regle dont ce
    systeme n'est pas depositaire. Le service se contente d'enregistrer ce
    qu'on lui donne.
    """
    beneficiaire = _agent_du_perimetre(agent, saisie.agentId)
    if saisie.droitsJours < 0:
        raise ErreurMetier("Un droit a conges ne peut pas etre negatif.", code="droits_invalides")

    with contexte_acteur(agent):
        droit, cree = CongeDroit.objects.get_or_create(
            utilisateur=beneficiaire,
            annee=saisie.annee,
            defaults={"droits_jours": saisie.droitsJours, "cree_par": agent.pk},
        )
        if not cree:
            droit.droits_jours = saisie.droitsJours
            droit.modifie_par = agent.pk
            droit.modifie_le = timezone.now()
            droit.save(update_fields=["droits_jours", "modifie_par", "modifie_le"])
        inscrire(
            objet_type="conge_droit",
            objet_id=droit.pk,
            type_evenement="droit_conges_pose" if cree else "droit_conges_modifie",
            libelle=(
                f"{saisie.droitsJours} jours de conges pour {beneficiaire.nom_complet} "
                f"au titre de {saisie.annee}"
            ),
            acteur=agent,
        )
    return droit


def planifier_conges(agent: Utilisateur, saisie) -> CongePeriode:
    """
    Une periode souhaitee.

    Elle ne peut pas recouvrir une absence deja prononcee : l'absence fait foi,
    et un souhait par-dessus ferait paraitre disponible un agent deja parti.
    Le chevauchement entre deux periodes souhaitees, lui, est **accepte** —
    c'est justement le conflit que l'ecran de planning sert a montrer.
    """
    droit = _droit_du_perimetre(agent, saisie.droitId)
    du = _date(saisie.du, "du")
    au = _date(saisie.au, "au")
    if au < du:
        raise ErreurMetier("La date de fin precede la date de debut.", code="periode_invalide")

    if Disponibilite.objects.filter(
        utilisateur=droit.utilisateur, invalide_le__isnull=True, du__lte=au, au__gte=du
    ).exists():
        raise EtatInvalide(
            "Une absence est deja prononcee sur cette periode.",
            code="chevauche_une_absence",
        )

    with contexte_acteur(agent):
        periode = CongePeriode.objects.create(
            conge_droit=droit,
            du=du,
            au=au,
            etat=CongePeriode.SOUHAITE,
            cree_par=agent.pk,
        )
        inscrire(
            objet_type="conge_periode",
            objet_id=periode.pk,
            type_evenement="conges_planifies",
            libelle=(
                f"Conges souhaites du {du.isoformat()} au {au.isoformat()} "
                f"pour {droit.utilisateur.nom_complet}"
            ),
            acteur=agent,
        )
    return periode


def arbitrer_conges(agent: Utilisateur, periode_id: int, saisie) -> CongePeriode:
    """
    Arbitrer, valider ou reporter une periode.

    **Un report sans motif ne se corrige pas** : l'agent resoumettra la meme
    periode. Meme regle que le renvoi d'un plan d'actions.
    """
    periode = _periode_du_perimetre(agent, periode_id)
    etat = _code(ETATS_CONGE_VERS_FRONT, saisie.etat, "Etat de la periode")

    if etat == CongePeriode.REPORTE and not (saisie.motif or "").strip():
        raise ErreurMetier(
            "Un report se motive : sans motif, la meme periode sera resoumise.",
            code="motif_requis",
        )

    with contexte_acteur(agent):
        periode.etat = etat
        periode.motif_report = (saisie.motif or "").strip() or None
        periode.arbitre_le = timezone.now()
        periode.arbitre_par = agent
        periode.modifie_par = agent.pk
        periode.modifie_le = timezone.now()
        periode.save(
            update_fields=[
                "etat",
                "motif_report",
                "arbitre_le",
                "arbitre_par",
                "modifie_par",
                "modifie_le",
            ]
        )
        inscrire(
            objet_type="conge_periode",
            objet_id=periode.pk,
            type_evenement="conges_arbitres",
            libelle=(
                f"Periode {saisie.etat.lower()} pour {periode.conge_droit.utilisateur.nom_complet}"
            ),
            detail=periode.motif_report,
            acteur=agent,
        )
    return periode


def _droit_du_perimetre(agent: Utilisateur, droit_id: int) -> CongeDroit:
    """Le droit a conges, borne au perimetre. 404 sinon — decision D5."""
    droit = (
        restreindre(
            CongeDroit.objects.filter(pk=droit_id),
            agent,
            champ_structure="utilisateur__structure",
            champ_agent="utilisateur_id",
        )
        .select_related("utilisateur")
        .first()
    )
    if droit is None:
        raise HorsPerimetre("Ce droit a conges n'existe pas ou n'est pas dans votre perimetre.")
    return droit


def _periode_du_perimetre(agent: Utilisateur, periode_id: int) -> CongePeriode:
    """La periode, bornee au perimetre. 404 sinon — decision D5."""
    periode = (
        restreindre(
            CongePeriode.objects.filter(pk=periode_id),
            agent,
            champ_structure="conge_droit__utilisateur__structure",
            champ_agent="conge_droit__utilisateur_id",
        )
        .select_related("conge_droit__utilisateur")
        .first()
    )
    if periode is None:
        raise HorsPerimetre("Cette periode n'existe pas ou n'est pas dans votre perimetre.")
    return periode
