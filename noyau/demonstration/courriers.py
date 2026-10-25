"""
Le registre des courriers, sur trois mois — le pilier central de la demonstration.

**Tout passe par `courrier.services`.** Le numero vient du declencheur, chaque
ecriture inscrit son evenement, la cotation calcule son echeance en jours
ouvres. Des `INSERT` directs auraient rempli `courrier` sans remplir
`evenement` — et la fiche de vie, la tracabilite et les indicateurs se lisent
dans `evenement`. Un registre sans journal aurait ete un decor.

**La retro-datation vient apres.** Les services datent du jour, ce qui est leur
travail : un courrier s'enregistre a son arrivee. Trois mois d'historique
demandent donc de reculer les dates apres coup, ce que `_retrodater` fait en une
requete par courrier — sur `courrier`, sur ses cotations, ses affectations et
ses evenements. Sans cela, cent courriers seraient arrives le meme jour et
toutes les series des tableaux de bord auraient montre un pic unique.

Les etats sont **repartis**, pas aleatoires : un registre de demonstration ou
tout serait clos ne montrerait aucune file d'attente, et un registre ou rien ne
le serait ne montrerait aucun delai tenu. La repartition est en tete de fichier,
et c'est elle qu'on regle pour changer ce que les ecrans racontent.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.db import connection
from django.utils import timezone

from courrier import services
from courrier.modeles import STATUT_EN_COURS, Cotation, Courrier
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure

#: La graine. Fixe, pour que deux chargements racontent la meme histoire : une
#: demonstration qu'on refait doit montrer les memes chiffres, sinon la capture
#: d'ecran de la veille ne se retrouve pas.
GRAINE = 20260819

#: La profondeur d'historique, en jours. Trois mois : de quoi remplir les series
#: mensuelles des tableaux de bord et les moyennes glissantes, sans peupler des
#: partitions d'evenements que la base n'a pas.
PROFONDEUR_JOURS = 92

#: La courbe des arrivees. Un exposant superieur a 1 **concentre les courriers
#: sur les semaines recentes**, et c'est ce qu'il faut : une repartition
#: uniforme laissait quatre courriers de moins d'une semaine sur soixante, donc
#: aucun courrier non cote, donc la file du bureau d'ordre vide et l'indicateur
#: « En attente de cotation » a zero.
#:
#: Ce n'est pas une deformation du reel : le flux d'arrivee est constant, mais
#: ce qui est vieux est **clos**, et ne se voit plus dans aucune file. Ce que la
#: courbe reproduit, c'est la population que les ecrans montrent.
COURBE = 1.8

#: L'etat d'un courrier selon son **age**, en parts : (age maximal, repartition).
#:
#: Repartir les etats sur toute la periode donnait un registre absurde — 34
#: courriers hors delai sur 60, parce qu'un courrier de mai avec cinq jours de
#: delai est forcement en retard s'il n'est pas clos. Un service qui laisserait
#: trois mois de courrier ouvert n'existe pas, et un tableau de bord entierement
#: rouge n'apprend rien a personne.
#:
#: Le bareme ci-dessous dit ce qu'un registre reel montre : ce qui est vieux est
#: solde, ce qui attend vient d'arriver, et **une minorite de vieux dossiers
#: traine** — ce sont eux, et eux seuls, que la vue « Hors délai » doit sortir.
#:
#:  * `clos`       — termine.
#:  * `restitue`   — l'agent a rendu son traitement, le responsable n'a pas clos.
#:  * `en_cours`   — un brouillon de traitement existe.
#:  * `accepte`    — l'agent a signe la decharge, il n'a pas commence a ecrire.
#:  * `affecte`    — un agent le tient, la decharge n'est pas signee.
#:  * `cote`       — cote, pas encore affecte. La file des chefs de service.
#:  * `enregistre` — arrive, pas encore cote. La file du bureau d'ordre.
#:
#: `accepte` et `restitue` sont apparus le 27 aout 2026 avec les gestes qui les
#: produisent. Sans eux, deux des sept etapes du trajet (ADR 034) n'etaient
#: atteintes par aucun courrier de demonstration — et une etape que le jeu
#: d'essai ne montre pas est une etape que personne ne verifie.
#: Une colonne par etat, dans l'ordre du trajet, pour que les repartitions se
#: lisent verticalement : c'est en les comparant ligne a ligne qu'on regle ce
#: que les ecrans racontent.
ETATS = ["enregistre", "cote", "affecte", "accepte", "en_cours", "restitue", "clos"]

BAREME = [
    #  age    enr.  cote  aff.  acc.  trai. rest. clos
    (45, [0, 0, 2, 2, 7, 5, 84]),
    (20, [0, 4, 6, 8, 18, 8, 56]),
    (7, [0, 16, 20, 14, 24, 8, 18]),
    (0, [44, 34, 14, 8, 0, 0, 0]),
]


def _au_moins(etat: str, seuil: str) -> bool:
    """
    Vrai si `etat` est ce seuil ou au-dela dans le trajet.

    L'ordre du trajet lu une seule fois, au lieu des listes `etat in (...)` qui
    se desynchronisent des qu'un etat s'ajoute — c'est ce qui serait arrive en
    ajoutant `accepte` et `restitue` le 27 aout 2026.
    """
    return ETATS.index(etat) >= ETATS.index(seuil)


#: (objet, code nature, part d'urgence)
#:
#: Les objets sont ecrits comme un agent les tape : une phrase, pas un mot-clef.
#: C'est ce qui rend la recherche plein texte demontrables — « demande »,
#: « redevance », « chenal » doivent ramener quelque chose.
SUJETS = [
    ("Demande d'agrément pour l'exercice de la profession de transitaire", "DEMANDE", 0),
    ("Réclamation sur la facturation des redevances de stationnement", "RECLAMATION", 0),
    ("Invitation à la session ordinaire du Comité de facilitation", "INVITATION", 0),
    ("Rapport trimestriel sur le trafic conteneurisé", "RAPPORT", 0),
    ("Note de service relative aux horaires de la période des fêtes", "NOTE", 0),
    ("Demande de report d'échéance sur la redevance domaniale", "DEMANDE", 0),
    ("Réclamation pour avarie survenue sur le terre-plein n° 4", "RECLAMATION", 1),
    ("Demande d'autorisation d'occupation temporaire du domaine portuaire", "DEMANDE", 0),
    ("Transmission du projet de budget d'investissement", "RAPPORT", 0),
    ("Mise en demeure avant recouvrement forcé", "AUTRE", 1),
    ("Demande d'accès aux installations pour une mission d'inspection", "DEMANDE", 1),
    ("Convocation à la réunion de coordination du passage portuaire", "INVITATION", 0),
    ("Rapport d'audit sur la chaîne de facturation", "RAPPORT", 0),
    ("Réclamation relative aux délais de mise à disposition des conteneurs", "RECLAMATION", 0),
    ("Demande de renseignements sur les tarifs de remorquage", "DEMANDE", 0),
    ("Notification de contrôle de la Chambre des comptes", "AUTRE", 1),
    ("Demande de partenariat pour la formation des dockers", "DEMANDE", 0),
    ("Signalement d'un ensablement du chenal au point kilométrique 12", "AUTRE", 1),
    ("Transmission des états financiers certifiés de l'exercice écoulé", "RAPPORT", 0),
    ("Note d'orientation sur la dématérialisation des procédures", "NOTE", 0),
    ("Demande de badge d'accès permanent pour le personnel navigant", "DEMANDE", 0),
    ("Réclamation sur le calcul des pénalités de retard", "RECLAMATION", 0),
    ("Invitation au forum économique du Golfe de Guinée", "INVITATION", 0),
    ("Demande de dérogation aux horaires d'ouverture des guichets", "DEMANDE", 0),
    ("Rapport sur l'état des équipements de manutention", "RAPPORT", 0),
    ("Recours gracieux contre la décision de résiliation du bail", "AUTRE", 1),
    ("Demande d'attestation de non-redevance", "DEMANDE", 0),
    ("Note relative à la sécurisation des zones sous douane", "NOTE", 1),
    ("Demande de visite guidée des installations portuaires", "DEMANDE", 0),
    ("Réclamation pour surestaries indûment facturées", "RECLAMATION", 0),
]

#: Les directions vers lesquelles un courrier se cote, et ce qu'elles traitent.
#: Le chef de file est le premier de la liste ; les suivantes sont co-traitantes.
ORIENTATIONS = [
    ["DEXP", "DFC"],
    ["DFC"],
    ["DAJ"],
    ["DEXP"],
    ["DAG", "DFC"],
    ["DRH"],
    ["DSI"],
    ["DDLM"],
    ["DAMP", "DEXP"],
    ["DCAP"],
    ["DCG"],
    ["DAPC"],
]

#: Les consignes portees a l'affectation. Une consigne vide fait un ecran vide.
#: Ce que l'agent ecrit du courrier. Une phrase de compte rendu, et non un
#: projet de reponse : la reponse releve du pilier depart, le traitement dit ce
#: qui a ete fait (ADR 036).
CONTENU_TRAITEMENT = (
    "Courrier examiné. Les pièces jointes ont été vérifiées et le dossier est "
    "complet. Un projet de réponse a été préparé et soumis à la signature ; "
    "l'expéditeur a été informé par téléphone du délai d'instruction."
)

CONSIGNES = [
    "Préparer un projet de réponse sous huitaine, avec les pièces justificatives.",
    "Vérifier la situation du compte avant toute réponse.",
    "Me rendre compte avant transmission au Directeur général.",
    "Traiter en liaison avec la Direction des affaires juridiques.",
    "Établir une note de synthèse pour la prochaine séance du Comité.",
    "Répondre directement à l'expéditeur et me mettre en copie.",
]

#: Les annotations de cotation, telles qu'une autorite les porte a la main.
ANNOTATIONS = [
    "Pour attribution et suite à donner.",
    "Pour avis motivé sous quinzaine.",
    "À traiter en priorité, l'expéditeur relance depuis un mois.",
    "Pour information et classement.",
    "M'en rendre compte après instruction.",
    "Voir avec les services concernés et me proposer une réponse.",
]


def semer(annuaire: dict[str, Utilisateur], correspondants: list, nombre: int, ecrire) -> int:
    """
    Pose `nombre` courriers repartis sur les trois derniers mois.

    Rend le nombre de courriers reellement crees — zero au deuxieme passage,
    puisque la marque d'idempotence est le volume deja en base.
    """
    deja = Courrier.objects.count()
    if deja >= nombre:
        ecrire(f"  {deja} courriers deja en base — passe")
        return 0

    tirage = random.Random(GRAINE)
    structures = {s.code: s for s in Structure.objects.filter(valide_au__isnull=True)}

    agents_session = {
        "ARRIVE": annuaire["agent.scc"],
        "INTERNE": annuaire["agent.int"],
        "CONFIDENTIEL": annuaire["agent.conf"],
    }

    crees = 0
    for rang in range(deja, nombre):
        jour = _jour_ouvre(tirage, rang, nombre)
        etat = _etat_selon_age(jour, tirage)
        type_session = _type_de_session(tirage, rang)

        courrier = _enregistrer(
            agents_session[type_session],
            type_session,
            correspondants[tirage.randrange(len(correspondants))],
            SUJETS[rang % len(SUJETS)],
            tirage,
        )
        _retrodater_enregistrement(courrier, jour)

        if etat != "enregistre":
            visees = ORIENTATIONS[rang % len(ORIENTATIONS)]
            cotation = _coter(
                courrier,
                agents_session[type_session],
                annuaire,
                [structures[code] for code in visees if code in structures],
                tirage,
                jour,
            )
            traitant = None
            if _au_moins(etat, "affecte"):
                traitant = _affecter(
                    courrier, cotation, annuaire, structures, visees[0], tirage, jour
                )
            if traitant is not None and _au_moins(etat, "accepte"):
                _signer_la_decharge(courrier, traitant)
            if traitant is not None and _au_moins(etat, "en_cours"):
                _rediger(courrier, traitant)
            if traitant is not None and _au_moins(etat, "restitue"):
                _restituer(courrier, traitant)
            if traitant is not None and etat == "clos":
                _clore(courrier, annuaire, structures, visees[0])
            elif _au_moins(etat, "affecte"):
                _mettre_en_cours(courrier)

            _retrodater_le_trajet(courrier, jour, tirage)

        crees += 1

    ecrire(f"  {crees} courriers, repartis sur {PROFONDEUR_JOURS} jours")
    return crees


# ---------------------------------------------------------------------
#  Les cinq gestes
# ---------------------------------------------------------------------


def _enregistrer(agent, type_session: str, correspondant, sujet, tirage) -> Courrier:
    objet, nature_code, urgent_par_defaut = sujet
    # Un courrier sur cinq environ. Au-dela, l'urgence ne veut plus rien dire —
    # ni a l'ecran, ni pour l'agent qui trie sa file.
    urgent = bool(urgent_par_defaut) or tirage.random() < 0.05

    from noyau.parametrage.modeles import Nature

    nature = Nature.objects.filter(code=nature_code).first() or Nature.objects.first()
    assert nature is not None

    return services.enregistrer(
        {
            "typeSession": type_session,
            "natureId": nature.pk,
            "correspondantId": correspondant.pk,
            "referenceExpediteur": f"{tirage.randrange(100, 999)}/{tirage.randrange(10, 99)}/CAB",
            "dateLettre": "",
            "nombrePages": tirage.randrange(1, 12),
            "objet": objet,
            "delaiJours": tirage.choice([3, 5, 5, 10, 15]),
            "urgent": urgent,
            "reponseAttendue": tirage.random() < 0.7,
            "coterMaintenant": False,
        },
        agent,
    )


def _coter(courrier, agent, annuaire, structures, tirage, jour) -> Cotation:
    """
    La cotation, decidee par le Directeur general et saisie par l'agent.

    C'est la distinction que le socle impose et que la demonstration doit
    montrer : `decide_par` n'est pas `saisi_par`. Un jeu ou les deux
    coincideraient laisserait croire que la colonne est en double.

    Une cotation sur cinq porte un **suivi** — la seconde cotation, celle d'une
    personne qui coordonne au-dessus du chef de file (A7).
    """
    from noyau.parametrage.modeles import MentionType

    mentions = list(MentionType.objects.filter(actif=True))
    autorite = annuaire["dg"]
    # La cotation est decidee un a trois jours apres l'arrivee : le parapheur ne
    # remonte pas au DG le jour meme, et un delai nul aurait rendu l'indicateur
    # « delai moyen de cotation » plat a zero.
    #
    # Bornee a aujourd'hui : `services._horodatage` refuse une decision datee
    # dans le futur, et un courrier arrive ce matin serait sinon cote apres-demain.
    decide_le = _horodatage(min(jour + timedelta(days=tirage.randrange(0, 3)), date.today()))

    saisie = {
        "mentionTypeId": mentions[tirage.randrange(len(mentions))].pk if mentions else None,
        "annotation": ANNOTATIONS[tirage.randrange(len(ANNOTATIONS))],
        "delaiFixe": None,
        "delaiJours": tirage.choice([3, 5, 10]),
        "decideParId": autorite.pk,
        "decideLe": decide_le.isoformat(),
        "structureIds": [s.pk for s in structures],
        "suiviParId": annuaire["att.dsr"].pk if tirage.random() < 0.2 else None,
        "motifSuivi": "Dossier signalé par la Division du suivi et de la relance.",
    }
    return services.coter(courrier.pk, saisie, agent)


def _affecter(
    courrier, cotation, annuaire, structures, code_chef_de_file, tirage, jour
) -> Utilisateur | None:
    """
    L'affectation, prononcee par le responsable de la structure chef de file.

    Rend l'agent affecte, ou `None` si l'affectation n'a pas pu etre prononcee :
    tout le reste du trajet pend a cette personne, et la deviner une seconde fois
    dans chaque geste suivant aurait fini par donner deux agents differents.

    Elle ne peut pas l'etre par l'agent de session : `services.affecter` exige
    que la structure de l'agent designe soit cotee, et l'agent de session ne
    voit le courrier que par la porte de son registre. C'est bien la regle qu'on
    veut montrer — la cotation vise une structure, l'affectation une personne.
    """
    agent_traitant = _traitant(annuaire, structures, code_chef_de_file)
    if agent_traitant is None:
        return None

    prononcant = _responsable(structures.get(code_chef_de_file)) or annuaire["dg"]
    try:
        services.affecter(
            courrier.pk,
            {
                "utilisateurId": agent_traitant.pk,
                "consigne": CONSIGNES[tirage.randrange(len(CONSIGNES))],
            },
            prononcant,
        )
    except Exception:
        # Une affectation refusee n'arrete pas le semis : la structure du
        # traitant peut ne pas etre cotee si l'organigramme a bouge. Le courrier
        # reste a l'etat « cote », ce qui est un etat legitime du registre.
        return None

    return agent_traitant


def _signer_la_decharge(courrier, traitant) -> None:
    """
    L'agent signe le cahier de decharge — l'etape ACCEPTE (ADR 035).

    Elle etait absente du semis jusqu'au 27 aout 2026, et l'etape avec elle : la
    demonstration montrait un courrier affecte, puis un courrier en traitement,
    sans jamais montrer le geste qui autorise le second. `rediger()` le refuse
    desormais, ce qui rend l'oubli impossible a reproduire.
    """
    affectation = _affectation_de(courrier, traitant)
    if affectation is None:
        return
    services.accepter(courrier.pk, affectation.pk, {}, traitant)


def _rediger(courrier, traitant) -> None:
    """
    Le brouillon de traitement — `services.rediger`.

    Ecrit en `INSERT` direct jusqu'au 26 aout 2026, faute de route. Le commentaire
    d'alors disait que la redaction relevait du pilier depart ; c'etait faux, et
    l'ADR 036 l'a tranche : ce que l'agent ecrit du courrier arrive est un
    traitement, pas une reponse. Le service existe, le semis l'appelle.
    """
    services.rediger(courrier.pk, {"contenu": CONTENU_TRAITEMENT}, traitant)


def _restituer(courrier, traitant) -> None:
    """L'agent rend son traitement au responsable — l'etape RESTITUE."""
    services.restituer(courrier.pk, {"contenu": CONTENU_TRAITEMENT}, traitant)


def _clore(courrier, annuaire, structures, code_chef_de_file) -> None:
    """
    La cloture, prononcee par le responsable de la structure chef de file.

    Ecrite en `UPDATE` direct jusqu'au 26 aout 2026, quand la permission `CLO`
    n'avait pas de route. Le service la porte depuis (ADR 036), et l'ecrire a la
    main aurait laisse le courrier sans son evenement `courrier.cloture` — donc
    hors de la fiche de vie, alors que la cloture est le jalon public qui la
    termine (ADR 032).

    `malgreLesBrouillons` : le semis clot des courriers dont le traitement est
    reste brouillon, ce qui est un cas reel — la reponse est partie autrement.
    Sans ce drapeau, le service refuserait, et c'est ce qu'on veut qu'il fasse a
    l'ecran.
    """
    responsable = _responsable(structures.get(code_chef_de_file)) or annuaire["dg"]
    try:
        services.clore(
            courrier.pk,
            {
                "observation": "Réponse adressée à l'expéditeur, dossier soldé.",
                "malgreLesBrouillons": True,
            },
            responsable,
        )
    except Exception:
        # Le responsable de la structure chef de file peut ne pas etre cote si
        # l'organigramme a bouge : `_exiger_la_qualite_pour_clore` refuse alors,
        # et le courrier reste ouvert. C'est un etat legitime du registre.
        return


def _affectation_de(courrier, traitant):
    """L'affectation en cours de cet agent sur ce courrier."""
    from courrier.modeles import Affectation

    return (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier=courrier,
            cotation_structure__cotation__invalide_le__isnull=True,
            utilisateur=traitant,
            retire_le__isnull=True,
        )
        .order_by("-affecte_le")
        .first()
    )


def _mettre_en_cours(courrier) -> None:
    Courrier.objects.filter(pk=courrier.pk).update(statut_courrier=STATUT_EN_COURS)


# ---------------------------------------------------------------------
#  Retro-datation
# ---------------------------------------------------------------------


def _retrodater_enregistrement(courrier: Courrier, jour: date) -> None:
    """
    Recule l'arrivee du courrier, et l'echeance avec elle.

    `date_limite` est **decalee du meme nombre de jours**, et non recalculee :
    le delai accorde est celui que le service a calcule en jours ouvres, et le
    recompter ici avec une autre regle aurait donne deux echeances differentes
    pour le meme courrier.

    Les evenements suivent — la fiche de vie les lit, et un enregistrement date
    d'aujourd'hui sous un courrier arrive en juin se remarque tout de suite.
    """
    ecart = (date.today() - jour).days
    if ecart <= 0:
        return

    horodatage = _horodatage(jour)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            UPDATE courrier
               SET date_reception = date_reception - %s * INTERVAL '1 day',
                   date_courrier  = date_courrier  - %s * INTERVAL '1 day',
                   date_limite    = date_limite    - %s * INTERVAL '1 day',
                   cree_le        = %s
             WHERE id = %s
            """,
            [ecart, ecart, ecart, horodatage, courrier.pk],
        )
        curseur.execute(
            "UPDATE evenement SET survenu_le = %s WHERE courrier_id = %s",
            [horodatage, courrier.pk],
        )
    courrier.refresh_from_db()


#: Le decalage de chaque geste par rapport a l'arrivee du courrier, en jours.
#:
#: Un trajet ne se joue pas en une journee, et un jeu d'essai ou tout porte le
#: meme horodatage ne montre aucun delai : « délai moyen de cotation », « temps
#: de remise » et « délai moyen de traitement » sortaient tous a zero.
#:
#: L'evenement porte le nom du geste ; la colonne qui le date porte souvent un
#: autre nom, d'ou les deux tables ci-dessous.
#: Les gestes du bureau d'ordre, en jours **apres le geste precedent**.
#:
#: Ils sont serres, et c'est necessaire : les delais accordes vont de trois a dix
#: jours ouvres, donc une decharge signee au huitieme jour ne laisse plus de
#: place a une cloture dans les temps. Le taux « traités dans le délai » tombait
#: a 30 % la ou le semis en visait 85.
#:
#: `routage_direct` porte le meme jour que `cote` — les deux sont exclusifs
#: (ADR 033), et l'avancer d'un cran de plus decalait tout le trajet d'un jour
#: pour un evenement qui n'existe pas.
DECALAGES = {
    "courrier.cote": 1,
    "courrier.routage_direct": 0,
    "courrier.affecte": 1,
    "courrier.accepte": 1,
}

#: La part des courriers clotures **dans le delai**. Le reste deborde.
#:
#: La cloture ne se place pas a un nombre de jours fixe de l'arrivee, mais par
#: rapport a **l'echeance du courrier**. Un decalage absolu ne pouvait pas
#: marcher : les delais accordes vont de trois a dix jours ouvres, donc une
#: cloture au quinzieme jour est en retard sur tous les courriers a la fois, et
#: le taux « traités dans le délai » sortait a zero pour cent sur toute
#: l'institution. Un tableau de bord entierement rouge n'apprend rien a personne.
PART_DANS_LE_DELAI = 0.85


def _dates_du_trajet(courrier: Courrier, jour: date, tirage: random.Random) -> dict[str, date]:
    """
    Le jour de chaque geste, dans l'ordre et sans chevauchement.

    Les quatre premiers pendent a l'arrivee, la cloture a l'echeance, et les deux
    du milieu se rangent entre les deux. Tirer sept dates independantes en aurait
    sorti une sur deux dans le desordre — une cloture prononcee avant le
    traitement qu'elle valide, et une fiche de vie que personne ne peut lire.
    """
    # `_retrodater_enregistrement` a decale `date_limite` en SQL : l'objet en
    # memoire porte encore l'echeance calculee a partir d'aujourd'hui, et placer
    # la cloture par rapport a elle l'aurait envoyee trois mois en avant.
    courrier.refresh_from_db(fields=["date_limite"])

    dates: dict[str, date] = {}
    decale = 0
    for type_evenement, pas in DECALAGES.items():
        # Un jour de flottement sur deux gestes, pas plus : c'est ce qui donne
        # au « délai moyen de cotation » une dispersion sans le rendre absurde.
        decale += pas + (1 if tirage.random() < 0.4 else 0)
        dates[type_evenement] = jour + timedelta(days=decale)

    if courrier.date_limite is not None:
        if tirage.random() < PART_DANS_LE_DELAI:
            ferme = courrier.date_limite - timedelta(days=tirage.randrange(4))
        else:
            ferme = courrier.date_limite + timedelta(days=tirage.randrange(1, 16))
    else:
        # Sans echeance, le courrier n'est ni a l'heure ni en retard : il sort du
        # taux, et sa date de cloture ne sert qu'a la moyenne des delais.
        ferme = jour + timedelta(days=tirage.randrange(5, 25))

    ferme = max(ferme, jour)

    # **Le trajet se comprime, il ne repousse pas la cloture.** Un delai de trois
    # jours ouvres laisse cinq jours pour tout faire ; forcer deux jours entre la
    # decharge et la cloture rejetait ces courriers-la hors delai quoi qu'il
    # arrive, et le taux visé de 85 % sortait a 57. Les gestes se tassent donc
    # sur la meme journee quand il le faut — ce qui arrive aussi au Port, un
    # courrier urgent se cotant, se signant et se traitant dans l'apres-midi.
    for type_evenement in DECALAGES:
        dates[type_evenement] = min(dates[type_evenement], ferme)

    dates["courrier.traitement_ouvert"] = min(dates["courrier.accepte"] + timedelta(days=1), ferme)
    dates["courrier.restitue"] = min(dates["courrier.traitement_ouvert"] + timedelta(days=1), ferme)
    dates["courrier.cloture"] = ferme
    return dates


def _retrodater_le_trajet(courrier: Courrier, jour: date, tirage: random.Random) -> None:
    """
    Recule chaque geste du trajet a sa place derriere l'arrivee du courrier.

    Sans cela, un courrier arrive en juin serait cote aujourd'hui, et
    l'indicateur « délai moyen de cotation » compterait deux mois sur chaque
    ligne — ce qui est faux et, surtout, ce qui rend l'ecran illisible.

    **Les services datent du jour, et c'est leur travail** : un courrier se cote
    quand on le cote. La retro-datation est donc un geste de semis, pas une
    option des services, et elle s'ecrit en SQL direct — passer par l'ORM
    reveillerait le declencheur `historiser_champs()` sur des colonnes qu'aucun
    agent n'a touchees.

    Etendue le 27 aout 2026 a la decharge, au traitement, a la restitution et a
    la cloture. Elle s'arretait a l'affectation, et poussait tous les evenements
    posterieurs a la date de cotation : la fiche de vie montrait une cloture
    prononcee avant le traitement qu'elle validait.
    """
    # Le rang donne l'heure : deux gestes du meme jour doivent rester dans
    # l'ordre, sinon la fiche de vie les affiche au hasard. C'est le cas courant
    # depuis que le trajet se comprime sous les echeances courtes.
    horodatages = {
        type_evenement: _horodatage(quand, rang)
        for rang, (type_evenement, quand) in enumerate(
            _dates_du_trajet(courrier, jour, tirage).items()
        )
    }

    with connection.cursor() as curseur:
        curseur.execute(
            "UPDATE cotation SET decide_le = %s, cree_le = %s WHERE courrier_id = %s",
            [horodatages["courrier.cote"], horodatages["courrier.cote"], courrier.pk],
        )
        curseur.execute(
            """
            UPDATE affectation
               SET affecte_le = %s,
                   accepte_le = CASE WHEN accepte_le IS NULL THEN NULL ELSE %s END
             WHERE cotation_structure_id IN (
                     SELECT cs.id FROM cotation_structure cs
                       JOIN cotation c ON c.id = cs.cotation_id
                      WHERE c.courrier_id = %s)
            """,
            [horodatages["courrier.affecte"], horodatages["courrier.accepte"], courrier.pk],
        )
        curseur.execute(
            """
            UPDATE traitement
               SET cree_le = %s,
                   modifie_le = %s,
                   soumis_le = CASE WHEN soumis_le IS NULL THEN NULL ELSE %s END
             WHERE courrier_id = %s
            """,
            [
                horodatages["courrier.traitement_ouvert"],
                horodatages["courrier.traitement_ouvert"],
                horodatages["courrier.restitue"],
                courrier.pk,
            ],
        )
        curseur.execute(
            "UPDATE traitement_version SET cree_le = %s WHERE traitement_id IN "
            "(SELECT id FROM traitement WHERE courrier_id = %s)",
            [horodatages["courrier.restitue"], courrier.pk],
        )
        curseur.execute(
            """
            UPDATE courrier
               SET cloture_le = %s, modifie_le = %s
             WHERE id = %s AND cloture_le IS NOT NULL
            """,
            [horodatages["courrier.cloture"], horodatages["courrier.cloture"], courrier.pk],
        )
        # Chaque evenement a sa date, et non celle de la cotation pour tous : la
        # fiche de vie les affiche dans l'ordre chronologique, et sept gestes au
        # meme horodatage s'y affichaient dans un ordre arbitraire.
        for type_evenement, horodatage in horodatages.items():
            curseur.execute(
                "UPDATE evenement SET survenu_le = %s "
                " WHERE courrier_id = %s AND type_evenement = %s",
                [horodatage, courrier.pk, type_evenement],
            )


# ---------------------------------------------------------------------
#  Petites decisions
# ---------------------------------------------------------------------


def _etat_selon_age(jour: date, tirage: random.Random) -> str:
    """
    L'etat d'un courrier, tire selon son age — voir `BAREME`.

    L'age et non le rang : c'est la date qui decide de l'echeance, donc du
    retard, donc de ce que les indicateurs affichent. Deduire l'etat d'autre
    chose que d'elle aurait produit des lignes incoherentes — un courrier clos
    la semaine derniere pour une lettre arrivee hier.
    """
    age = (date.today() - jour).days
    for age_minimal, repartition in BAREME:
        if age >= age_minimal:
            return _tirer(repartition, tirage)
    return "enregistre"


def _tirer(repartition: list[int], tirage: random.Random) -> str:
    """Un etat de `ETATS`, tire selon les parts de la ligne de `BAREME`."""
    seuil = tirage.randrange(sum(repartition))
    cumul = 0
    for etat, part in zip(ETATS, repartition, strict=True):
        cumul += part
        if seuil < cumul:
            return etat
    return ETATS[-1]


def _jour_ouvre(tirage: random.Random, rang: int, nombre: int) -> date:
    """
    Un jour ouvre des trois derniers mois, reparti sur toute la periode.

    Le rang donne la tendance et le tirage le desordre : un courrier par jour
    exactement aurait fait des series parfaitement plates, et un tirage pur
    aurait laisse des semaines vides.
    """
    part = (nombre - rang) / max(1, nombre)
    recul = int(PROFONDEUR_JOURS * part**COURBE)
    jour = date.today() - timedelta(days=recul + tirage.randrange(0, 3))
    while jour.weekday() >= 5:
        jour -= timedelta(days=1)
    return jour


def _type_de_session(tirage: random.Random, rang: int) -> str:
    """
    Le registre d'arrivee domine — c'est le cas au Port. Un courrier sur huit est
    interne, un sur vingt confidentiel : assez pour que les deux autres cahiers
    ne soient pas vides, assez peu pour qu'ils restent l'exception.
    """
    if rang % 20 == 7:
        return "CONFIDENTIEL"
    if rang % 8 == 3:
        return "INTERNE"
    return "ARRIVE"


def _horodatage(jour: date, rang: int = 0) -> datetime:
    """
    Un moment de la journee de travail, entre 8h et 16h — **jamais dans le
    futur**.

    Le `rang` est celui du geste dans le trajet : il decale l'heure d'une heure
    par cran, pour que deux gestes tombes le meme jour restent dans l'ordre.

    Le plafond n'est pas une precaution : `services._horodatage` refuse une
    decision datee en avant, et un semis lance a 9h aurait pose des cotations a
    15h le jour meme. C'est l'heure de la machine qui decide, pas le calendrier.

    La marge d'une heure, elle, repond a une contrainte du socle :
    `cotation_saisie_apres_decision` exige `decide_le <= cree_le`, et `cree_le`
    vaut le `now()` de PostgreSQL — c'est-a-dire l'heure d'**ouverture de la
    transaction**, figee, tandis que `timezone.now()` avance a chaque appel.
    Sans marge, une cotation posee vingt millisecondes trop tard viole la
    contrainte, et le semis entier est annule.
    """
    # L'heure croit avec le rang, sans repli modulo : sept gestes, huit heures
    # ouvrees, et le septieme doit rester apres le premier. Le desordre du jeu
    # d'essai tient a la minute, pas a l'heure.
    heure = time(hour=8 + min(rang, 7), minute=(jour.toordinal() * 7) % 60)
    moment = timezone.make_aware(datetime.combine(jour, heure))
    return min(moment, timezone.now() - timedelta(hours=1))


def _responsable(structure: Structure | None) -> Utilisateur | None:
    if structure is None:
        return None
    from noyau.organisation.lecture import responsables_comptes

    return responsables_comptes(Structure.objects.filter(pk=structure.pk)).get(structure.pk)


def _traitant(annuaire: dict, structures: dict, code_structure: str) -> Utilisateur | None:
    """
    L'agent a qui le courrier est confie : un collaborateur de la branche cotee,
    ou son responsable a defaut.

    `services.affecter` exige que la structure de l'agent soit **elle-meme
    cotee** — pas une de ses filles. Le traitant est donc cherche dans la
    structure visee avant tout.
    """
    structure = structures.get(code_structure)
    if structure is None:
        return None
    return Utilisateur.objects.actifs().filter(structure=structure).order_by("nom").first()
