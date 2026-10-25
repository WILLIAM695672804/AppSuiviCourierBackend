"""
La corbeille de celui qui instruit — C-01, et la recherche avancee A-14.

**Distinct du registre, et la nuance est tout l'ecran.** Le registre decrit le
courrier pour tous ; le dossier decrit ce que *moi* j'ai a faire. Meme donnee,
deux lectures, et c'est pour cela que le front a toujours separe `/courriers` de
`/suivi`.

Trois questions, dans l'ordre ou l'agent se les pose :

    qu'est-ce qu'on me demande   -> l'instruction de son affectation
    ou en suis-je                -> ses taches et ses notes
    combien de temps me reste-t-il -> le delai, et la demande de report

Ce que ce module ne fait pas : il n'ecrit rien. Les quatre gestes du pilier —
cocher une tache, prendre une note, demander un delai, conserver une recherche —
sont dans `services.py`, avec leurs regles et leurs evenements.

**Le dossier n'est pas reserve a l'agent affecte.** Un responsable ouvre le
dossier de son agent : c'est ainsi qu'il sait ou en est le travail avant de le
relancer. Ce qui est reserve, ce sont les **notes privees**, et
`_notes_lisibles()` porte cette regle a lui seul.

La visibilite du courrier lui-meme passe par `visibles()`, comme partout. Un
dossier hors perimetre repond 404 et jamais 403 — decision D5.
"""

from datetime import date

from django.db import models

from courrier.lecture import _delai, _resumes
from courrier.modeles import (
    DEMANDE_EN_ATTENTE,
    STATUT_CLOTURE,
    STATUT_CREE,
    STATUT_EN_COURS,
    STATUT_TRAITE,
    Affectation,
    Courrier,
    DemandeDelai,
    NoteTraitement,
    RechercheEnregistree,
    TacheTraitement,
    Traitement,
)
from courrier.visibilite import visibles, voit
from noyau.erreurs import HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.perimetre.portee import structures_visibles

#: Combien de resultats une recherche avancee rend au plus. Le meme plafond que
#: l'export du registre : au-dela, ce n'est plus une recherche, c'est un export,
#: et l'ecran d'a cote sait le faire.
PLAFOND_RECHERCHE = 500

#: Combien de recherches enregistrees un agent peut conserver. La carte de
#: l'ecran en montre une liste, pas un catalogue — et chaque ligne coute un
#: `count()` pour afficher son nombre de resultats.
PLAFOND_RECHERCHES_ENREGISTREES = 20


# =====================================================================
#  Le portefeuille — ce que j'ai sur les bras
# =====================================================================


def portefeuille(utilisateur: Utilisateur) -> dict:
    """
    Les dossiers affectes a l'agent, et les trois nombres qui les resument.

    « Affectes a lui » et non « visibles par lui » : c'est la difference entre sa
    corbeille et le registre. Un directeur qui voit deux cents courriers en a
    trois sur les bras, et ce sont ces trois-la que cet ecran doit montrer.

    `enVisa` compte ce qui est **parti chez le responsable** : le dossier n'est
    plus dans les mains de l'agent, mais il n'est pas clos et continue de peser
    sur son delai. L'oublier ferait croire un travail perdu.
    """
    dossiers = list(
        _mes_dossiers(utilisateur).select_related("nature", "priorite")[:PLAFOND_RECHERCHE]
    )

    en_visa = set(
        Traitement.objects.filter(
            courrier__in=dossiers,
            redacteur=utilisateur,
            invalide_le__isnull=True,
            statut=Traitement.STATUT_SOUMIS,
        ).values_list("courrier_id", flat=True)
    )

    hors_delai = sum(1 for courrier in dossiers if _en_depassement(courrier))

    return {
        "dossiers": _resumes(dossiers),
        # « A rendre » est tout ce qui n'est pas encore parti : soustraire ce qui
        # attend un visa evite de compter deux fois le meme dossier dans deux
        # cartes qui se lisent cote a cote.
        "aRendre": len(dossiers) - len(en_visa),
        "horsDelai": hors_delai,
        "enVisa": len(en_visa),
    }


def _mes_dossiers(utilisateur: Utilisateur) -> models.QuerySet:
    """
    Les courriers en cours affectes a l'agent, sans doublon.

    `distinct()` n'est pas cosmetique : un courrier cote a deux structures et
    affecte deux fois au meme agent sortirait deux fois, et le compte des cartes
    serait faux.
    """
    return (
        Courrier.objects.filter(
            invalide_le__isnull=True,
            cotations__invalide_le__isnull=True,
            cotations__structures__affectations__utilisateur=utilisateur,
            cotations__structures__affectations__retire_le__isnull=True,
        )
        .exclude(statut_courrier=STATUT_CLOTURE)
        .distinct()
    )


def _en_depassement(courrier: Courrier) -> bool:
    delai = _delai(courrier)
    return bool(delai and delai["joursDepassement"] > 0)


# =====================================================================
#  Le dossier — C-01
# =====================================================================


def dossier(utilisateur: Utilisateur, courrier_id: int) -> dict:
    """
    Un dossier, vu du cote de celui qui le traite.

    Leve `HorsPerimetre` — donc 404 — quand le courrier n'est pas visible.
    Repondre « interdit » confirmerait son existence a qui n'a pas a la
    connaitre : decision D5, comme la fiche.
    """
    if not voit(utilisateur, courrier_id):
        raise HorsPerimetre("Courrier introuvable.")

    courrier = Courrier.objects.select_related("nature", "priorite").get(pk=courrier_id)
    affectation = _mon_affectation(utilisateur, courrier_id)

    autres = [
        autre
        for autre in _mes_dossiers(utilisateur).select_related("nature", "priorite")[:20]
        if autre.pk != courrier_id
    ]

    return {
        "courrier": _resumes([courrier])[0],
        "instruction": _instruction(affectation),
        "echeance": courrier.date_limite,
        "delai": _delai(courrier),
        "taches": _taches(utilisateur, courrier_id),
        "notes": _notes_lisibles(utilisateur, courrier_id),
        "autresDossiers": _resumes(autres),
        "actionsPossibles": _actions_possibles(utilisateur, courrier, affectation),
    }


def _mon_affectation(utilisateur: Utilisateur, courrier_id: int) -> Affectation | None:
    """
    L'affectation vivante de cet agent sur ce courrier, s'il en a une.

    `None` pour le responsable qui ouvre le dossier de son agent : il lit alors
    le dossier sans instruction ni action, ce qui est exact — l'instruction est
    celle qu'il a lui-meme donnee.
    """
    return (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier_id=courrier_id,
            cotation_structure__cotation__invalide_le__isnull=True,
            utilisateur=utilisateur,
            retire_le__isnull=True,
        )
        .select_related("affecte_par", "affecte_par__poste")
        .order_by("-affecte_le")
        .first()
    )


def _instruction(affectation: Affectation | None) -> dict | None:
    """
    Ce qu'on demande a l'agent, avec qui le demande.

    **L'auteur compte autant que le texte** : « traiter en urgence » n'a pas le
    meme poids selon qu'il vient du chef de service ou du Directeur general, et
    c'est ce que l'ecran montre en tete.

    `None` quand l'affectation ne porte aucune orientation — l'ecran ecrit alors
    « aucune instruction particuliere », ce qui est un fait et non un manque.
    """
    orientations = (affectation.orientations or "").strip() if affectation else ""
    if affectation is None or not orientations:
        return None

    auteur = affectation.affecte_par
    return {
        "texte": orientations,
        "auteur": auteur.nom_complet if auteur else "Non renseigné",
        "initiales": auteur.initiales if auteur else "—",
        "fonction": (auteur.poste.libelle if auteur and auteur.poste else "") or "",
        "horodatage": affectation.affecte_le,
    }


def _taches(utilisateur: Utilisateur, courrier_id: int) -> list[dict]:
    """La liste que l'agent se donne — la sienne, jamais celle d'un autre."""
    return [
        {
            "id": tache.pk,
            "libelle": tache.libelle,
            "faite": tache.faite_le is not None,
            "faiteLe": tache.faite_le,
        }
        for tache in TacheTraitement.objects.filter(
            courrier_id=courrier_id, utilisateur=utilisateur, invalide_le__isnull=True
        )
    ]


def _notes_lisibles(utilisateur: Utilisateur, courrier_id: int) -> list[dict]:
    """
    Les notes du dossier que cet agent peut lire.

    **C'est la seule regle de confidentialite propre a ce module.** Une note
    privee se lit par son auteur et par sa hierarchie — c'est ce que l'ecran
    promet en toutes lettres : « Note privee · visible par ma hierarchie ».

    « Sa hierarchie » se lit avec l'outil du socle : les structures que le
    lecteur voit. Un directeur en portee `sous_arbre` couvre la structure de son
    agent ; un agent d'a cote ne la couvre pas. En portee `toutes`
    (`structures_visibles` rend `None`), tout est lisible — la consolidation vaut
    ici, contrairement au confidentiel : une note de travail n'est pas un secret,
    c'est un brouillon.
    """
    notes = NoteTraitement.objects.filter(courrier_id=courrier_id).select_related("auteur")

    structures = structures_visibles(utilisateur)
    if structures is not None:
        notes = notes.filter(
            models.Q(privee=False)
            | models.Q(auteur=utilisateur)
            | models.Q(auteur__structure__in=structures)
        )

    return [
        {
            "id": note.pk,
            "texte": note.texte,
            "horodatage": note.publiee_le,
            "privee": note.privee,
        }
        for note in notes
    ]


def _actions_possibles(
    utilisateur: Utilisateur, courrier: Courrier, affectation: Affectation | None
) -> list[str]:
    """
    Ce que l'ecran a le droit de proposer, dit par le serveur.

    Le front s'en sert pour montrer ou cacher deux boutons. Le calculer ici et
    non la-bas evite la panne la plus commune de cet ecran : un bouton propose,
    puis un refus a l'envoi.

    Un dossier clos n'accepte plus rien, et un lecteur qui n'y est pas affecte
    n'a aucune action — il regarde, ce qui est le cas du responsable.
    """
    if courrier.statut_courrier == STATUT_CLOTURE or affectation is None:
        return []

    actions = ["traiter"]
    # Demander un report suppose une echeance a reporter, et qu'aucune demande
    # ne soit deja pendante : redemander n'est pas relancer.
    if (
        courrier.date_limite is not None
        and not DemandeDelai.objects.filter(
            courrier=courrier, demandeur=utilisateur, etat=DEMANDE_EN_ATTENTE
        ).exists()
    ):
        actions.append("demanderDelai")
    return actions


# =====================================================================
#  La recherche avancee — A-14
# =====================================================================

#: Les statuts que l'ecran propose, traduits en filtres. `archive` n'est pas un
#: statut du courrier mais un fonds : il est traite avec `inclureArchives`.
STATUTS_RECHERCHE = ("enCours", "cloture", "horsDelai", "archive")


def rechercher(utilisateur: Utilisateur, criteres: dict) -> dict:
    """
    La recherche avancee, sur le registre visible de l'agent.

    Les criteres se **cumulent** — mots-cles ET periode ET structure : c'est ce
    qu'un formulaire a dix champs laisse attendre. Seuls les statuts et les
    sessions s'additionnent entre eux, parce que cocher deux cases y veut dire
    « l'un ou l'autre ».

    Un critere vide ne filtre pas. Un formulaire ou tout est vide rend donc le
    registre entier, plafonne : c'est la reponse juste a « cherche tout ».
    """
    requete = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)

    requete = _par_mots_cles(requete, criteres.get("motsCles") or "")
    requete = _par_periode(requete, criteres.get("du"), criteres.get("au"))
    requete = _par_sessions(requete, criteres.get("sessions") or [])
    requete = _par_statuts(requete, criteres.get("statuts") or [])

    structure_id = _entier(criteres.get("structureId"))
    if structure_id is not None:
        requete = requete.filter(
            models.Q(structure_chef_file_id=structure_id)
            | models.Q(
                cotations__invalide_le__isnull=True,
                cotations__structures__structure_id=structure_id,
            )
        )

    nature_id = _entier(criteres.get("natureId"))
    if nature_id is not None:
        requete = requete.filter(nature_id=nature_id)

    requete = requete.distinct()

    total = requete.count()
    lignes = list(
        requete.select_related("nature", "priorite").order_by("-date_reception", "-id")[
            :PLAFOND_RECHERCHE
        ]
    )
    return {"lignes": _resumes(lignes), "total": total}


def _par_mots_cles(requete: models.QuerySet, terme: str) -> models.QuerySet:
    """
    Le meme moteur que le registre, et pour la meme raison.

    `_appliquer_recherche` cherche le numero par prefixe et le reste par le
    vecteur plein texte `fr_unaccent` : « delegation » trouve « délégation ».
    Deux recherches ecrites deux fois auraient fini par ne pas trouver les memes
    courriers, et l'agent aurait conclu que l'un des deux ecrans ment.
    """
    from courrier.lecture import _appliquer_recherche

    return _appliquer_recherche(requete, terme)


def _par_periode(requete: models.QuerySet, du: str | None, au: str | None) -> models.QuerySet:
    """
    La periode porte sur la **reception**, pas sur la cloture.

    C'est la date que l'agent a en tete quand il cherche : « le courrier du
    ministere, arrive en mars ». La date de cloture ne lui dit rien, et il ne la
    connait pas.
    """
    debut = _date(du)
    fin = _date(au)
    if debut is not None:
        requete = requete.filter(date_reception__gte=debut)
    if fin is not None:
        requete = requete.filter(date_reception__lte=fin)
    return requete


def _par_sessions(requete: models.QuerySet, sessions: list[str]) -> models.QuerySet:
    """
    Les cases « Arrivé », « Départ », « Interne », « Confidentiel ».

    Les trois premieres sont des **sens** ; la quatrieme est une session, et
    l'ecran a raison de les melanger — l'agent, lui, coche « ce que je cherche ».
    Le confidentiel reste ferme a qui n'a pas la permission : la serrure est
    posee par `visibles()` en amont, et ce filtre-ci ne l'ouvre pas.
    """
    if not sessions:
        return requete

    from courrier.lecture import SENS_DEPUIS_FRONT

    condition = models.Q(pk__in=[])
    for code in sessions:
        if code == "CONFIDENTIEL":
            condition |= models.Q(confidentiel=True)
            continue
        sens = SENS_DEPUIS_FRONT.get(code) or SENS_DEPUIS_FRONT.get(f"{code}E")
        if sens is not None:
            condition |= models.Q(sens=sens)
    return requete.filter(condition)


def _par_statuts(requete: models.QuerySet, statuts: list[str]) -> models.QuerySet:
    """
    « En cours », « Clôturé », « Hors délai », « Archivé ».

    Ce ne sont pas quatre valeurs d'une meme colonne : « hors delai » se lit sur
    l'echeance, « archive » sur le fonds. Cocher plusieurs cases veut dire
    « l'un ou l'autre », d'ou le `|`.

    `archive` ne filtre rien tant que l'archivage ne marque pas le courrier : le
    pilier archivage verse des dossiers, il ne pose aucun drapeau sur la ligne.
    Ecarter tout le registre aurait ete pire qu'ignorer la case — l'agent aurait
    conclu a une panne.
    """
    connus = [statut for statut in statuts if statut in STATUTS_RECHERCHE]
    if not connus or ("archive" in connus and len(connus) == 1):
        return requete

    condition = models.Q(pk__in=[])
    for statut in connus:
        if statut == "enCours":
            condition |= ~models.Q(statut_courrier=STATUT_CLOTURE)
        elif statut == "cloture":
            condition |= models.Q(statut_courrier=STATUT_CLOTURE)
        elif statut == "horsDelai":
            condition |= models.Q(
                date_limite__lt=date.today(),
                statut_courrier__in=[STATUT_CREE, STATUT_EN_COURS, STATUT_TRAITE],
            )
    return requete.filter(condition)


def _entier(valeur) -> int | None:
    """Le front envoie `""` pour « aucun choix » : `int("")` leverait."""
    try:
        return int(valeur) if valeur not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(valeur) -> date | None:
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


# =====================================================================
#  Les recherches enregistrees
# =====================================================================


def recherches_enregistrees(utilisateur: Utilisateur) -> list[dict]:
    """
    Ce que l'agent a conserve, avec le nombre de resultats **d'aujourd'hui**.

    Le nombre est recalcule a chaque listing et non stocke : une recherche
    enregistree est une question, pas une reponse — « les courriers hors delai de
    la DAF » n'a pas le meme compte lundi et vendredi, et c'est precisement ce
    que l'agent vient voir.

    Le cout est borne par `PLAFOND_RECHERCHES_ENREGISTREES` : vingt `count()` sur
    un index, a l'ouverture d'un ecran.
    """
    return [
        {
            "id": enregistree.pk,
            "libelle": enregistree.libelle,
            "nombre": rechercher(utilisateur, enregistree.criteres)["total"],
            "criteres": enregistree.criteres,
        }
        for enregistree in RechercheEnregistree.objects.filter(utilisateur=utilisateur)[
            :PLAFOND_RECHERCHES_ENREGISTREES
        ]
    ]
