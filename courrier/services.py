"""
Les ecritures du pilier courrier.

**Toute la regle metier est ici, aucune dans `api.py`.** La raison n'est pas
esthetique : une regle ecrite dans une route ne s'applique qu'a cette route, et
la deuxieme voie d'ecriture — un import, une reprise, une commande de gestion —
la contournera sans que rien ne le signale.

Trois obligations pesent sur chaque fonction de ce module :

 1. **`acteur()` autour de l'ecriture.** `courrier` et `cotation` sont
    historisees par le declencheur `historiser_champs()`, qui **refuse**
    l'ecriture quand `app.utilisateur_id` n'est pas pose. L'oubli ne passe donc
    pas inapercu ici — c'est une des rares regles que le moteur fait respecter
    tout seul.
 2. **Un evenement au journal**, via `noyau.journal.service.inscrire`. Le journal
    est l'histoire du courrier (ADR 012) et la seule source de sa fiche de vie :
    une ecriture sans evenement est une ecriture qui n'a pas eu lieu, pour
    l'agent qui relit.
 3. **La verification de visibilite avant toute ecriture.** Un agent ne cote pas
    un courrier qu'il n'a pas le droit de lire, et l'objet de courrier renvoye
    dans un message d'erreur serait deja la fuite. `visibles()` sert donc aussi a
    l'ecriture, et l'echec sort en **404** (decision D5).

Ce que ce module ne fait pas, et pourquoi : il ne deroule aucun circuit. Ni
`instance_circuit`, ni `instance_etape`, ni `validation`, ni relance automatique,
ni escalade. Les trois premieres tables sont ancrees sur `circuit_etape`, qui est
vide : le trajet reel d'un courrier au Port n'a jamais ete communique (A24).
Ecrire un acheminement inventé aurait produit une application qui fonctionne et
qui a tort.
"""

from datetime import date, datetime

from django.db import models
from django.utils import timezone

from courrier import routage
from courrier.lecture import (
    CODE_PRIORITE_NORMALE,
    CODE_PRIORITE_URGENT,
    SENS_DEPUIS_SESSION,
    SESSION_DEPUIS_FRONT,
)
from courrier.modeles import (
    DEMANDE_ACCORDEE,
    DEMANDE_EN_ATTENTE,
    DEMANDE_REFUSEE,
    RELANCE_MANUELLE,
    STATUT_CLOTURE,
    STATUT_CREE,
    STATUT_EN_COURS,
    Affectation,
    Cotation,
    CotationStructure,
    CotationSuivi,
    Courrier,
    DemandeDelai,
    NoteTraitement,
    Observation,
    RechercheEnregistree,
    Relance,
    SignalementEcart,
    TacheTraitement,
    Traitement,
    TraitementVersion,
)
from courrier.suivi import PLAFOND_RECHERCHES_ENREGISTREES
from courrier.visibilite import session_en_cours, visibles
from noyau.calendrier import ajouter_jours_ouvres, jours_ouvres_entre
from noyau.erreurs import ErreurMetier, EtatInvalide, HorsPerimetre
from noyau.identite.modeles import SessionCourrier, Utilisateur
from noyau.journal.contexte import acteur
from noyau.journal.service import inscrire
from noyau.notifications import services as notifications
from noyau.organisation.lecture import responsables_comptes
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, MentionType, Nature, Priorite
from noyau.parametres import service as parametres

#: La decharge de l'agent conditionne le traitement. Le parametre permet de
#: l'eteindre sans redeploiement : une structure qui n'a jamais tenu de cahier ne
#: doit pas voir ses agents bloques le premier jour. Statut `acte` — le Port a
#: decrit le cahier lui-meme (entretien du 26 aout 2026).
CLE_ACCEPTATION_OBLIGATOIRE = "courrier.acceptation_obligatoire"

#: Le delai retenu quand ni la saisie ni la nature n'en donnent. Cinq jours
#: ouvres, valeur par defaut de l'ecran A-01 ; le vrai delai reglementaire par
#: nature s'administre dans `nature.delai_defaut_jours`.
DELAI_DE_SECOURS = 5


# =====================================================================
#  Enregistrement — A-01
# =====================================================================


def enregistrer(saisie: dict, utilisateur: Utilisateur) -> Courrier:
    """
    Inscrit un courrier au registre.

    **Le numero n'est pas calcule ici.** Le courrier est insere avec
    `numero=""`, et le declencheur `courrier_numero` (BEFORE INSERT) le compose
    sous verrou de ligne avant que la ligne n'existe. Le service **relit** ensuite
    la ligne pour connaitre le numero attribue. Le predire cote Python serait le
    seul moyen d'en produire deux identiques.

    L'agent enregistre **dans son registre**, jamais dans celui d'un autre
    service : le rattachement `utilisateur_session` est exclusif et garanti par
    une contrainte d'exclusion du moteur, et un agent du registre « Arrivée » qui
    inscrirait dans le registre confidentiel consommerait un numero du cahier
    d'autrui.
    """
    session = _session_de_saisie(saisie["typeSession"], utilisateur)
    nature = _nature(saisie["natureId"])
    correspondant = _correspondant(saisie["correspondantId"])

    aujourd_hui = date.today()
    date_lettre = _date_iso(saisie.get("dateLettre")) or aujourd_hui

    delai = saisie.get("delaiJours") or nature.delai_defaut_jours or DELAI_DE_SECOURS
    echeance = ajouter_jours_ouvres(aujourd_hui, delai)

    with acteur(utilisateur):
        courrier = Courrier.objects.create(
            numero="",
            numero_origine=saisie.get("referenceExpediteur") or None,
            sens=SENS_DEPUIS_SESSION[session.code],
            # La confidentialite vient du **registre**, pas d'une case a cocher :
            # un courrier inscrit au cahier confidentiel est confidentiel, et
            # l'ecran A-01 n'offre d'ailleurs aucune case pour cela.
            confidentiel=session.code == "confidentiel",
            session=session,
            nature=nature,
            date_courrier=date_lettre,
            date_reception=aujourd_hui,
            expediteur=correspondant,
            # Fige a l'arrivee. Le referentiel peut changer de raison sociale
            # ensuite ; le registre doit continuer de dire sous quel nom le
            # courrier est arrive.
            expediteur_libelle=correspondant.designation,
            objet=saisie["objet"],
            nombre_pieces=saisie.get("nombrePages") or 1,
            priorite=_priorite(bool(saisie.get("urgent"))),
            delai_reglementaire_jours=delai,
            date_limite=echeance,
            cree_par=utilisateur.pk,
        )
        # Le numero vient du declencheur : sans cette relecture, l'objet rendu au
        # front porterait la chaine vide qu'on a inseree.
        courrier.refresh_from_db(fields=["numero"])

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.enregistre",
            libelle=f"Courrier {courrier.numero} enregistré",
            detail=f"Registre « {session.libelle} » — {courrier.expediteur_libelle}",
            acteur=utilisateur,
            donnees={
                "sens": courrier.sens,
                "nature": nature.libelle,
                "delaiJours": delai,
                "echeance": echeance.isoformat(),
                # Une reponse attendue n'a **aucune colonne** : ni `courrier` ni
                # `traitement` ne portent cette intention. Elle est consignee au
                # journal plutot que devinee, faute de quoi la case cochee par
                # l'agent disparaitrait sans trace. Voir
                # `docs/questions-ouvertes.md`.
                "reponseAttendue": bool(saisie.get("reponseAttendue")),
                # Suite d'ecran, sans effet en base : la cotation immediate est
                # une navigation, pas une ecriture. Consignee pour que la trace
                # dise ce que l'agent a demande — la cotation elle-meme, si elle
                # a lieu, inscrira son propre evenement.
                "coterMaintenant": bool(saisie.get("coterMaintenant")),
            },
        )

        _router_directement(courrier, utilisateur)

    return courrier


def _router_directement(courrier: Courrier, utilisateur: Utilisateur) -> None:
    """
    Cote d'office le courrier, quand une regle de routage direct le prevoit.

    « Les factures vont directement chez le DFC, sans passer par le DG. » La
    cotation produite est une **vraie cotation** — meme fonction, meme journal,
    meme passage en structure : une voie d'ecriture parallele aurait produit des
    courriers routes qui n'apparaissent dans aucun registre de bureau d'ordre.

    **L'autorite inscrite est l'agent qui enregistre**, et non le Directeur
    general. Ce n'est pas un pis-aller : l'exigence dit precisement que le
    courrier ne passe pas par lui, et lui attribuer la decision aurait ete un
    faux au journal. Ce qui distingue cette cotation d'une autre est l'evenement
    `courrier.routage_direct`, qui nomme la regle appliquee.

    Aucune regle, aucun effet — c'est le cas ordinaire, pas un echec.
    """
    regle = routage.regle_applicable(courrier)
    if regle is None:
        return

    coter(
        courrier.pk,
        {
            "structureIds": [regle.structure_id],
            "decideParId": utilisateur.pk,
            "mentionTypeId": regle.mention_type_id,
            "annotation": None,
        },
        utilisateur,
    )

    inscrire(
        objet_type="courrier",
        objet_id=courrier.pk,
        courrier_id=courrier.pk,
        type_evenement="courrier.routage_direct",
        libelle=f"Routage direct vers {regle.structure.code}",
        detail=regle.libelle,
        acteur=utilisateur,
        # Jalon : le trajet du courrier regarde toute structure cotee, et une
        # cotation d'office se justifie d'autant plus qu'elle se voit.
        donnees={
            "regle": regle.code,
            "structure": regle.structure.code,
            # Une regle en « hypothese » est une regle que personne n'a
            # confirmee. Le journal doit le dire, faute de quoi la relecture
            # d'un routage conteste ne pourra pas distinguer la decision du
            # Port de l'invention de la conception (A69).
            "statutRegle": regle.statut,
        },
    )


def _session_de_saisie(type_session: str, utilisateur: Utilisateur) -> SessionCourrier:
    """
    Le registre dans lequel l'agent a le droit d'inscrire.

    `lit_toutes_sessions` ouvre la **lecture** de tous les registres, pas
    l'ecriture dans chacun : l'agent du registre confidentiel voit les arrivees,
    il ne consomme pas leur numerotation. La distinction est dans le nom de la
    colonne, et la confondre aurait troue la sequence du registre des arrivees.
    """
    code = SESSION_DEPUIS_FRONT.get(type_session)
    if code is None:
        raise ErreurMetier(f"Registre inconnu : « {type_session} ».")

    rattachee = session_en_cours(utilisateur)
    if rattachee is None:
        raise ErreurMetier(
            "Votre compte n'est rattaché à aucun registre : l'enregistrement d'un "
            "courrier n'aurait pas de numéro."
        )
    if rattachee.code != code:
        raise ErreurMetier(
            f"Vous êtes rattaché au registre « {rattachee.libelle} » : "
            "vous ne pouvez pas enregistrer dans un autre."
        )
    return rattachee


def _nature(identifiant: int) -> Nature:
    nature = Nature.objects.filter(pk=identifiant, actif=True).first()
    if nature is None:
        raise ErreurMetier("La nature de courrier choisie n'existe pas ou n'est plus active.")
    return nature


def _correspondant(identifiant: int) -> Correspondant:
    correspondant = Correspondant.objects.filter(
        pk=identifiant, actif=True, invalide_le__isnull=True
    ).first()
    if correspondant is None:
        raise ErreurMetier("Le correspondant choisi n'existe pas ou n'est plus actif.")
    return correspondant


def _priorite(urgent: bool) -> Priorite | None:
    """
    La priorite ecrite en base depuis la case « Urgent » de l'ecran A-01.

    **La base a quatre niveaux, l'ecran une case a cocher.** Cocher ecrit
    `URGENT`, ne pas cocher ecrit `NORMALE` ; `ELEVEE` et `BASSE` restent
    inatteignables par cet ecran. Ce n'est pas un oubli : rien dans les documents
    sources ne dit ce qui distingue `URGENT` de `ELEVEE`, et repartir une case a
    cocher sur quatre niveaux aurait invente la regle. Voir
    `docs/questions-ouvertes.md`.
    """
    code = CODE_PRIORITE_URGENT if urgent else CODE_PRIORITE_NORMALE
    return Priorite.objects.filter(code=code, actif=True).first()


def _date_iso(valeur: str | None) -> date | None:
    """Une date ISO envoyee par le front, ou `None` quand le champ est vide."""
    if not valeur:
        return None
    try:
        return date.fromisoformat(valeur[:10])
    except ValueError as erreur:
        raise ErreurMetier(f"Date illisible : « {valeur} ».") from erreur


# =====================================================================
#  Cotation — A-04
# =====================================================================


def coter(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Cotation:
    """
    Enregistre une cotation : l'acte, les structures visees, et le suivi s'il y en a.

    **Une decision, une ligne de `cotation`.** Le Directeur general cote une fois,
    eventuellement vers cinq structures : les structures sont dans
    `cotation_structure`, avec leur rang. Cinq lignes de `cotation` auraient dit
    cinq decisions.

    **Le rang 1 est chef de file.** L'ordre de `structureIds` n'est donc pas un
    ordre d'affichage : il est ecrit en base, un declencheur du socle recopie le
    rang 1 sur `courrier.structure_chef_file_id`, et le registre trie dessus.

    **`decide_par` n'est pas `saisi_par`.** Le DG decide, l'agent de session tape.
    Une seule colonne aurait attribue a l'agent une decision qu'il n'a pas prise,
    ce qui vide le journal de sa valeur probante.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : il ne se cote plus.")

    structures = _structures_ordonnees(saisie["structureIds"])
    autorite = _agent(saisie["decideParId"], "L'autorité qui cote")
    mention = _mention(saisie.get("mentionTypeId"))
    decide_le = _horodatage(saisie.get("decideLe"))
    suivi = (
        _agent(saisie["suiviParId"], "La personne désignée au suivi")
        if saisie.get("suiviParId")
        else None
    )

    parente = _cotation_parente(courrier, autorite)

    with acteur(utilisateur):
        cotation = Cotation.objects.create(
            courrier=courrier,
            mention_type=mention,
            annotation=saisie.get("annotation") or None,
            delai_fixe=_delai_de_cotation(saisie, decide_le),
            decide_par=autorite,
            decide_le=decide_le,
            saisi_par=utilisateur,
            # La cascade : le DG cote une direction (niveau 1), qui cote l'un de
            # ses services (niveau 2). Une cotation de niveau 2 sans parente
            # serait orpheline — le service verrait le courrier sans que rien ne
            # dise qui l'y a mis.
            niveau_cotation=(parente.niveau_cotation + 1) if parente else 1,
            cotation_parente=parente,
            cree_par=utilisateur.pk,
        )

        CotationStructure.objects.bulk_create(
            [
                CotationStructure(cotation=cotation, structure=structure, rang=rang)
                for rang, structure in enumerate(structures, start=1)
            ]
        )

        if suivi is not None:
            # La seconde cotation — A7, tranchée par le client le 11 août 2026.
            # Une **personne**, jamais une structure : elle coordonne au-dessus du
            # chef de file et rend compte au Directeur general. Consequence
            # pratique : la relance lui part, pas au chef de file.
            CotationSuivi.objects.create(
                cotation=cotation,
                utilisateur=suivi,
                motif=saisie.get("motifSuivi") or None,
                designe_par=autorite,
            )

        if courrier.statut_courrier == STATUT_CREE:
            courrier.statut_courrier = STATUT_EN_COURS
            courrier.modifie_par = utilisateur.pk
            courrier.modifie_le = timezone.now()
            courrier.save(update_fields=["statut_courrier", "modifie_par", "modifie_le"])

        sigles = ", ".join(structure.code for structure in structures)
        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.cote",
            libelle=f"Coté à {sigles}",
            detail=(mention.libelle if mention else None),
            acteur=utilisateur,
            # La cotation de **niveau 1** est un jalon : le Directeur general
            # cote, et toutes les structures visees ont a savoir qui d'autre est
            # sur l'affaire. Celles de niveau superieur sont la **cascade
            # interne** d'une direction vers ses services — l'instruction qu'un
            # directeur ecrit a son chef de service ne regarde pas la direction
            # voisine, cotee au meme rang que lui. ADR 031.
            structure_id=(autorite.structure_id if cotation.niveau_cotation > 1 else None),
            # `agit_pour` porte l'autorite : c'est ce qui distingue « l'agent a
            # saisi » de « le Directeur general a decide », et le journal doit
            # dire les deux.
            agit_pour=autorite if autorite != utilisateur else None,
            donnees={
                "chefDeFile": structures[0].code,
                "coTraitantes": [structure.code for structure in structures[1:]],
                "niveau": cotation.niveau_cotation,
                "suiviPar": suivi.pk if suivi else None,
                # L'annotation de l'autorite, citee telle quelle : la chronologie
                # de la fiche la relit sous le nom `instruction`, et une consigne
                # reformulee n'engage plus son auteur.
                "instruction": saisie.get("annotation") or None,
            },
        )

        _prevenir_les_cotes(courrier, structures, suivi, utilisateur, autorite)

    return cotation


def _prevenir_les_cotes(
    courrier: Courrier,
    structures: list[Structure],
    suivi: Utilisateur | None,
    saisi_par: Utilisateur,
    autorite: Utilisateur,
) -> None:
    """
    Previent ceux que la cotation engage — RF-SUI-03.

    **Ce n'est pas une option de l'ecran.** Une cotation que le responsable
    apprend en ouvrant le registre est une cotation papier : le courrier attend
    le temps qu'il faut pour que quelqu'un pense a regarder. La case a cocher
    « Notifier les responsables » a donc ete retiree de la fenetre de cotation,
    et non branchee.

    Le destinataire est le **responsable de la structure**, deduit du poste
    occupe (`noyau.organisation.lecture`) — il n'existe pas de colonne
    « responsable », et en inventer une aurait cree une seconde verite.

    Une structure sans responsable en poste ne recoit rien, et c'est le seul
    silence acceptable : ecrire a tous ses agents ferait d'une cotation une
    circulaire.

    L'autorite qui cote n'est pas prevenue de sa propre decision, ni l'agent qui
    saisit de sa propre saisie — une notification qu'on s'envoie a soi-meme
    n'apprend rien et use les autres.
    """
    chefs = responsables_comptes(Structure.objects.filter(pk__in=[s.pk for s in structures]))
    chef_de_file = structures[0]

    for structure in structures:
        destinataire = chefs.get(structure.pk)
        if destinataire is None or destinataire.pk in {saisi_par.pk, autorite.pk}:
            continue
        notifications.notifier(
            destinataire,
            type_notification="courrier_cote",
            libelle=f"Courrier {courrier.numero} coté à {structure.code}",
            detail=courrier.objet,
            # « Alerte » est reserve a l'urgence reelle : mettre toute cotation
            # en alerte reviendrait a n'en signaler aucune. Le code, et non la
            # presence d'une priorite — `NORMALE` en est une.
            importance=(
                "alerte"
                if courrier.priorite and courrier.priorite.code == CODE_PRIORITE_URGENT
                else None
            ),
            objet_type="courrier",
            objet_id=courrier.pk,
            lien=f"/courriers/{courrier.pk}",
            acteur=saisi_par,
        )

    if suivi is not None and suivi.pk not in {saisi_par.pk, autorite.pk}:
        # La cotation pour suivi est la **seconde** cotation : elle coordonne
        # au-dessus du chef de file (A7). Son libelle le dit, sans quoi la
        # personne designee lirait la meme phrase que les responsables et
        # croirait avoir a traiter.
        notifications.notifier(
            suivi,
            type_notification="courrier_suivi",
            libelle=f"Suivi du courrier {courrier.numero}",
            detail=f"Chef de file : {chef_de_file.libelle}. {courrier.objet}",
            objet_type="courrier",
            objet_id=courrier.pk,
            lien=f"/courriers/{courrier.pk}",
            acteur=saisi_par,
        )


def _delai_de_cotation(saisie: dict, decide_le: datetime) -> date | None:
    """
    L'echeance que l'autorite impose en cotant, quand elle en impose une.

    Deux formes acceptees, et **une seule regle** : `delaiFixe` est une date deja
    choisie ; `delaiJours` est un nombre de jours **ouvres** que le serveur
    convertit. La conversion est ici et non a l'ecran parce que compter les jours
    ouvres est une regle metier — le calendrier des feries est en base, et un
    client qui compterait lui-meme donnerait une echeance differente de celle que
    le registre affiche.

    Le point de depart est la date de la **decision**, pas celle de la saisie :
    une cotation signee le matin et tapee le lendemain n'accorde pas un jour de
    plus.
    """
    if saisie.get("delaiFixe"):
        return _date_iso(saisie["delaiFixe"])

    jours = saisie.get("delaiJours")
    if not jours:
        return None
    if jours < 0:
        raise ErreurMetier("Un delai ne se compte pas en jours negatifs.")
    return ajouter_jours_ouvres(timezone.localtime(decide_le).date(), jours)


def _cotation_parente(courrier: Courrier, autorite: Utilisateur) -> Cotation | None:
    """
    La cotation qui autorise celle-ci, quand il s'agit d'une cascade.

    Une cotation est en cascade quand la structure de l'autorite qui cote a
    **elle-meme ete cotee** : le directeur d'une direction cotee repartit vers ses
    services. Sinon c'est une cotation de premier niveau.

    La plus recente est retenue lorsqu'il y en a plusieurs : c'est la decision en
    vigueur, et rattacher a une cotation plus ancienne aurait fait remonter la
    cascade sous une decision deja depassee.
    """
    if autorite.structure_id is None:
        return None
    return (
        Cotation.objects.filter(
            courrier=courrier,
            invalide_le__isnull=True,
            structures__structure_id=autorite.structure_id,
        )
        .order_by("-niveau_cotation", "-decide_le")
        .first()
    )


def _structures_ordonnees(identifiants: list[int]) -> list[Structure]:
    """
    Les structures visees, **dans l'ordre recu**.

    Le tri n'est pas celui de la base : `filter(pk__in=…)` rend les lignes dans
    l'ordre que le moteur juge commode, et le premier element de la liste designe
    le chef de file. Un tri par identifiant aurait donc designe le mauvais.
    """
    if not identifiants:
        raise ErreurMetier("Une cotation vise au moins une structure.")
    if len(set(identifiants)) != len(identifiants):
        raise ErreurMetier("Une même structure ne peut pas être cotée deux fois.")

    par_identifiant = {
        structure.pk: structure
        for structure in Structure.objects.filter(pk__in=identifiants, invalide_le__isnull=True)
    }
    manquantes = [str(pk) for pk in identifiants if pk not in par_identifiant]
    if manquantes:
        raise ErreurMetier(f"Structures inconnues : {', '.join(manquantes)}.")
    return [par_identifiant[pk] for pk in identifiants]


def _mention(identifiant: int | None) -> MentionType | None:
    if identifiant is None:
        return None
    mention = MentionType.objects.filter(pk=identifiant, actif=True).first()
    if mention is None:
        raise ErreurMetier("La mention choisie n'existe pas ou n'est plus active.")
    return mention


# =====================================================================
#  Affectation — A-05
# =====================================================================


def affecter(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Affectation:
    """
    Affecte le courrier a un agent d'une structure cotee.

    **L'affectation pend a la cotation, pas au courrier.** La cotation va vers une
    structure, l'affectation vers une personne : affecter un agent dont la
    structure n'est pas cotee reviendrait a contourner la decision de l'autorite,
    et c'est pour cela que la verification ci-dessous n'est pas une politesse.

    Une affectation ouverte du meme agent n'est pas dupliquee : deux lignes
    ouvertes pour le meme agent sur le meme courrier feraient partir deux
    relances.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : il ne s'affecte plus.")

    agent = _agent(saisie["utilisateurId"], "L'agent à affecter")
    visee = _structure_cotee_de(courrier, agent)

    deja = Affectation.objects.filter(
        cotation_structure__cotation__courrier=courrier,
        utilisateur=agent,
        retire_le__isnull=True,
    ).exists()
    if deja:
        raise EtatInvalide(f"{agent.prenom} {agent.nom} est déjà affecté à ce courrier.")

    with acteur(utilisateur):
        affectation = Affectation.objects.create(
            cotation_structure=visee,
            utilisateur=agent,
            # Le front dit « consigne », la base dit `orientations`. La traduction
            # se fait ici, une seule fois.
            orientations=saisie.get("consigne") or None,
            affecte_par=utilisateur,
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.affecte",
            libelle=f"Affecté à {agent.prenom} {agent.nom}",
            detail=visee.structure.libelle,
            acteur=utilisateur,
            # **Geste interne.** Qui la DAF met sur un dossier, et avec quelle
            # consigne, ne regarde pas la DSI cotee sur le meme courrier. La
            # DSR et le Directeur general continuent de le lire — c'est leur
            # mission de suivi. Voir `courrier/cloisonnement.py`.
            structure_id=visee.structure_id,
            donnees={
                "utilisateurId": agent.pk,
                "structure": visee.structure.code,
                "instruction": saisie.get("consigne") or None,
            },
        )

        # L'agent affecte doit l'apprendre de l'application, pas d'un parapheur
        # qui passe : c'est a partir de cet instant que son delai court. Il n'y
        # a pas de case a cocher pour cela — voir `_prevenir_les_cotes`.
        if agent.pk != utilisateur.pk:
            notifications.notifier(
                agent,
                type_notification="courrier_affecte",
                libelle=f"Courrier {courrier.numero} à traiter",
                detail=(saisie.get("consigne") or courrier.objet),
                importance=(
                    "alerte"
                    if courrier.priorite and courrier.priorite.code == CODE_PRIORITE_URGENT
                    else None
                ),
                objet_type="courrier",
                objet_id=courrier.pk,
                lien=f"/courriers/{courrier.pk}",
                acteur=utilisateur,
            )

    return affectation


def _structure_cotee_de(courrier: Courrier, agent: Utilisateur) -> CotationStructure:
    """
    La ligne de cotation qui autorise l'affectation de cet agent.

    L'agent doit relever d'une structure cotee — **par cotation ouverte**. Une
    cotation invalidee reste au registre comme trace de la decision, elle
    n'autorise plus rien.

    Le rang le plus faible est retenu quand la structure est visee par plusieurs
    cotations : rattacher l'affectation au chef de file plutot qu'a une
    co-traitance est ce qui fait remonter le travail au bon coordinateur.
    """
    if agent.structure_id is None:
        raise ErreurMetier(
            f"{agent.prenom} {agent.nom} n'est rattaché à aucune structure : "
            "aucune cotation ne peut porter son affectation."
        )

    visee = (
        CotationStructure.objects.filter(
            cotation__courrier=courrier,
            cotation__invalide_le__isnull=True,
            structure_id=agent.structure_id,
        )
        .select_related("structure")
        .order_by("rang")
        .first()
    )
    if visee is None:
        raise EtatInvalide(
            f"La structure de {agent.prenom} {agent.nom} n'est pas cotée sur ce "
            "courrier : il faut coter avant d'affecter."
        )
    return visee


# =====================================================================
#  Prolongation du delai
# =====================================================================


def prolonger(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Courrier:
    """
    Reporte l'echeance d'un courrier, avec son motif.

    **Le report part de l'echeance en vigueur, pas d'aujourd'hui.** Accorder
    « trois jours de plus » a un courrier deja en retard de huit jours en le
    replacant a trois jours d'aujourd'hui effacerait le retard : la prolongation
    deviendrait un moyen d'assainir un indicateur, et c'est exactement ce qu'une
    prolongation motivee ne doit pas permettre.

    Deux formes, la meme regle que pour la cotation : `nouvelleEcheance` est une
    date choisie, `delaiJours` un nombre de jours **ouvres** que le serveur
    convertit — le calendrier des feries est en base.

    Le motif est **obligatoire**. Un report sans raison ne se defend pas devant
    un controle, et l'echeance initiale ne survit que dans l'evenement inscrit
    ici : la colonne, elle, est ecrasee.

    Ce que cette fonction ne fait pas : elle ne cree aucune ligne de
    prolongation. Le schema n'en porte pas de table, et l'historique du report
    tient dans le journal (ADR 012) plus `champ_historique`, que le declencheur
    alimente sur `courrier.date_limite`.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : son délai ne se prolonge plus.")
    if courrier.date_limite is None:
        raise EtatInvalide(
            "Ce courrier n'a pas d'échéance : il n'y a rien à prolonger. "
            "Fixez d'abord un délai en le cotant."
        )

    motif = (saisie.get("motif") or "").strip()
    if not motif:
        raise ErreurMetier("Une prolongation se motive.")

    ancienne = courrier.date_limite
    nouvelle = _echeance_prolongee(saisie, ancienne)
    if nouvelle <= ancienne:
        raise ErreurMetier(
            "Une prolongation reporte l'échéance : la nouvelle date doit être "
            "postérieure à l'actuelle. Raccourcir un délai est un autre acte."
        )

    with acteur(utilisateur):
        courrier.date_limite = nouvelle
        # `delai_reglementaire_jours` compte les jours accordes depuis la
        # reception. Le laisser inchange ferait mentir la barre de la fiche, qui
        # divise les jours consommes par les jours alloues.
        courrier.delai_reglementaire_jours = (
            courrier.delai_reglementaire_jours or 0
        ) + jours_ouvres_entre(ancienne, nouvelle)
        courrier.modifie_par = utilisateur.pk
        courrier.modifie_le = timezone.now()
        courrier.save(
            update_fields=["date_limite", "delai_reglementaire_jours", "modifie_le", "modifie_par"]
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.delai_prolonge",
            libelle=f"Délai prolongé au {nouvelle.strftime('%d/%m/%Y')}",
            detail=motif,
            acteur=utilisateur,
            donnees={
                "ancienneEcheance": ancienne.isoformat(),
                "nouvelleEcheance": nouvelle.isoformat(),
                "motif": motif,
            },
        )

        _prevenir_du_report(courrier, ancienne, nouvelle, motif, utilisateur)

    return courrier


def _echeance_prolongee(saisie: dict, echeance: date) -> date:
    """La nouvelle echeance, quelle que soit la forme recue."""
    if saisie.get("nouvelleEcheance"):
        nouvelle = _date_iso(saisie["nouvelleEcheance"])
        if nouvelle is None:
            raise ErreurMetier("Nouvelle échéance illisible.")
        return nouvelle

    jours = saisie.get("delaiJours")
    if not jours:
        raise ErreurMetier("Indiquez la nouvelle échéance, ou le nombre de jours accordés.")
    if jours < 0:
        raise ErreurMetier("Un délai ne se compte pas en jours négatifs.")
    return ajouter_jours_ouvres(echeance, jours)


def _prevenir_du_report(
    courrier: Courrier, ancienne: date, nouvelle: date, motif: str, auteur: Utilisateur
) -> None:
    """
    Previent qui travaille sur le courrier — c'est leur echeance qui bouge.

    Les agents affectes, pas les structures cotees : la cotation designe un
    service, l'affectation designe la personne dont le delai court reellement.
    """
    destinataires = (
        Utilisateur.objects.filter(
            affectations_courrier__cotation_structure__cotation__courrier=courrier,
            affectations_courrier__retire_le__isnull=True,
            actif=True,
        )
        .exclude(pk=auteur.pk)
        .distinct()
    )
    for agent in destinataires:
        notifications.notifier(
            agent,
            type_notification="courrier_delai_prolonge",
            libelle=f"Courrier {courrier.numero} : délai reporté",
            detail=(
                f"Du {ancienne.strftime('%d/%m/%Y')} au {nouvelle.strftime('%d/%m/%Y')}. {motif}"
            ),
            objet_type="courrier",
            objet_id=courrier.pk,
            lien=f"/courriers/{courrier.pk}",
            acteur=auteur,
        )


# =====================================================================
#  Correction de la saisie
# =====================================================================

#: Ce qu'une correction peut toucher, en face du nom de la colonne.
#:
#: **Le numero, le registre, le sens, la confidentialite et la date de reception
#: n'y sont pas, et n'y seront pas** : ce sont les mentions du cahier. Les
#: corriger reviendrait a reecrire le registre apres coup, ce qui lui ote toute
#: valeur probante. Une piece inscrite au mauvais cahier s'annule et se
#: reinscrit — geste qui, lui, reste a arbitrer (A65).
CHAMPS_CORRIGEABLES = {
    "objet": "objet",
    "referenceExpediteur": "numero_origine",
    "dateLettre": "date_courrier",
    "nombrePages": "nombre_pieces",
}
#: `courrier.observations` n'y figure pas : la colonne existe mais **aucun ecran
#: ne l'ecrit** (`SaisieEnregistrement` ne la porte pas), et corriger un champ
#: que rien ne remplit aurait ouvert une seconde facon de saisir la meme chose.


def corriger(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Courrier:
    """
    Corrige une erreur de saisie — §4.2.

    Une faute de frappe sur l'objet, un expediteur choisi une ligne trop bas, une
    nature mal lue : sans ce geste, l'erreur est definitive et l'agent n'a que le
    reenregistrement, qui consomme un second numero et fait deux courriers d'un
    seul.

    **Seuls les champs descriptifs se corrigent** — voir `CHAMPS_CORRIGEABLES`.

    La correction **ne recalcule pas l'echeance**, meme quand la nature change :
    le delai a pu etre impose par l'autorite en cotant, et le recalculer
    silencieusement effacerait sa decision. Pour reporter l'echeance, il y a
    `prolonger()`, qui exige un motif.

    Chaque champ touche laisse son avant et son apres dans l'evenement : une
    correction dont on ne peut plus lire la valeur d'origine n'est plus une
    correction, c'est une reecriture.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : sa saisie ne se corrige plus.")

    differences: dict[str, dict[str, str | None]] = {}

    def noter(colonne: str, avant, apres) -> None:
        if avant == apres:
            return
        setattr(courrier, colonne, apres)
        differences[colonne] = {
            "avant": None if avant is None else str(avant),
            "apres": None if apres is None else str(apres),
        }

    for champ, colonne in CHAMPS_CORRIGEABLES.items():
        if saisie.get(champ) is None:
            continue
        valeur = saisie[champ]
        if colonne == "date_courrier":
            # Vide vaut « non corrigé » : la colonne est NOT NULL, et une
            # correction ne se transmet pas en effacant un champ.
            if not valeur:
                continue
            valeur = _date_iso(valeur)
        elif colonne == "numero_origine":
            valeur = (valeur or "").strip() or None
        noter(colonne, getattr(courrier, colonne), valeur)

    if saisie.get("correspondantId") is not None:
        correspondant = _correspondant(saisie["correspondantId"])
        noter("expediteur_id", courrier.expediteur_id, correspondant.pk)
        # Le libelle fige suit l'expediteur corrige : il dit sous quel nom le
        # courrier est arrive, et l'ancien nom designait le mauvais tiers.
        noter("expediteur_libelle", courrier.expediteur_libelle, correspondant.designation)

    if saisie.get("natureId") is not None:
        nature = _nature(saisie["natureId"])
        noter("nature_id", courrier.nature_id, nature.pk)

    if saisie.get("urgent") is not None:
        priorite = _priorite(bool(saisie["urgent"]))
        noter("priorite_id", courrier.priorite_id, priorite.pk if priorite else None)

    if not differences:
        raise ErreurMetier("Aucune modification : la correction n'a rien à inscrire.")

    motif = (saisie.get("motif") or "").strip()

    with acteur(utilisateur):
        courrier.modifie_par = utilisateur.pk
        courrier.modifie_le = timezone.now()
        courrier.save(update_fields=[*differences, "modifie_le", "modifie_par"])

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.corrige",
            libelle=f"Saisie corrigée — {', '.join(sorted(differences))}",
            detail=motif or None,
            acteur=utilisateur,
            donnees={"motif": motif or None, "differences": differences},
        )

    return courrier


# =====================================================================
#  Garde commune
# =====================================================================


def _courrier_visible(identifiant: int, utilisateur: Utilisateur) -> Courrier:
    """
    Le courrier, s'il est visible de cet agent — **404 sinon, jamais 403**.

    Repondre « vous n'avez pas le droit » confirmerait l'existence du courrier et
    celle de son expediteur a qui n'a pas a les connaitre. Decision de cadrage D5.

    La verification passe par `visibles()` et non par une seconde regle : deux
    regles divergeraient, et c'est celle qui protege le moins qui finirait par
    s'appliquer.
    """
    courrier = visibles(
        Courrier.objects.filter(pk=identifiant, invalide_le__isnull=True), utilisateur
    ).first()
    if courrier is None:
        raise HorsPerimetre("Ce courrier n'existe pas ou ne relève pas de votre périmètre.")
    return courrier


def _agent(identifiant: int, role: str) -> Utilisateur:
    agent = Utilisateur.objects.filter(pk=identifiant, actif=True, invalide_le__isnull=True).first()
    if agent is None:
        raise ErreurMetier(f"{role} n'existe pas ou son compte est désactivé.")
    return agent


def _horodatage(valeur: str | None) -> datetime:
    """
    Le moment de la decision, tel que l'ecran le transmet.

    Il est distinct de l'heure de saisie : une cotation signee le matin peut etre
    tapee l'apres-midi, et c'est la date de la decision qui compte pour le delai.
    Vide, l'heure de saisie fait foi — c'est le cas ou l'autorite cote elle-meme.
    """
    if not valeur:
        return timezone.now()
    try:
        moment = datetime.fromisoformat(valeur)
    except ValueError as erreur:
        raise ErreurMetier(f"Horodatage illisible : « {valeur} ».") from erreur
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    if moment > timezone.now():
        raise ErreurMetier("Une décision ne se date pas dans le futur.")
    return moment


# =====================================================================
#  La decharge — l'agent cote accuse reception
# =====================================================================


def accepter(
    identifiant: int, affectation_id: int, saisie: dict, utilisateur: Utilisateur
) -> Affectation:
    """
    L'agent cote reconnait avoir recu le courrier — le cahier de decharge.

    Au Port, l'agent signe un cahier quand le pli lui est remis (entretien du
    26 aout 2026). C'est ce geste que la colonne `accepte_le` porte, et c'est
    lui qui ouvre le traitement : `_exiger_la_decharge()` refuse tout depot tant
    qu'il n'a pas eu lieu (ADR 035).

    **Une seule fois.** Un second accuse ecraserait l'heure du premier, et
    l'ecart entre l'affectation et la decharge — la seule mesure du temps de
    remise — se remettrait a zero a chaque clic. Meme regle que l'accuse du
    bureau d'ordre.

    **Qui signe.** L'agent affecte, ou le point focal de sa structure, qui tient
    le cahier et signe pour lui quand le pli arrive en son absence. La colonne
    `accepte_par` garde la difference : elle ne vaut la preuve que parce qu'elle
    ne dit pas toujours la meme personne que `utilisateur_id`.

    Il n'y a **pas de refus** : l'agent qui estime que le courrier ne le concerne
    pas ouvre un signalement d'ecart de type `DESTINATAIRE_ERRONE`. Deux voies
    pour le meme fait auraient produit deux registres a reconcilier — A70.
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    affectation = (
        Affectation.objects.filter(
            pk=affectation_id,
            cotation_structure__cotation__courrier=courrier,
            retire_le__isnull=True,
        )
        .select_related("utilisateur", "cotation_structure__structure")
        .first()
    )
    if affectation is None:
        raise HorsPerimetre("Cette affectation n'existe pas ou ne relève pas de ce courrier.")

    if affectation.accepte_le is not None:
        raise EtatInvalide("Cette décharge est déjà signée.")

    _exiger_la_qualite_pour_signer(affectation, utilisateur)

    agent = affectation.utilisateur
    structure = affectation.cotation_structure.structure

    with acteur(utilisateur):
        affectation.accepte_le = timezone.now()
        affectation.accepte_par = utilisateur
        affectation.remis_par = (saisie.get("remisPar") or "").strip() or None
        affectation.reference_cahier = (saisie.get("referenceCahier") or "").strip() or None
        affectation.save(
            update_fields=["accepte_le", "accepte_par", "remis_par", "reference_cahier"]
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.accepte",
            libelle=f"Reçu par {agent.prenom} {agent.nom}",
            detail=affectation.remis_par,
            acteur=utilisateur,
            # **Geste interne** : la decharge d'un agent de la DAF ne regarde
            # pas la DSI cotee sur le meme courrier. Meme frontiere que
            # l'affectation — ADR 032.
            structure_id=structure.pk,
            donnees={
                "affectationId": affectation.pk,
                "utilisateurId": agent.pk,
                "remisPar": affectation.remis_par,
                "referenceCahier": affectation.reference_cahier,
            },
        )

        # Le responsable qui a affecte apprend que le pli est arrive : c'est ce
        # qu'il attend du cahier, et c'est ce qui lui evite de le redemander.
        if affectation.affecte_par_id not in (utilisateur.pk, None):
            notifications.notifier(
                affectation.affecte_par,
                type_notification="courrier_accepte",
                libelle=f"Courrier {courrier.numero} reçu",
                detail=f"{agent.prenom} {agent.nom} a signé la décharge.",
                objet_type="courrier",
                objet_id=courrier.pk,
                lien=f"/courriers/{courrier.pk}",
                acteur=utilisateur,
            )

    return affectation


def _exiger_la_qualite_pour_signer(affectation: Affectation, utilisateur: Utilisateur) -> None:
    """
    Qui peut signer la decharge d'un agent.

    L'agent lui-meme, ou quelqu'un de **sa structure**. La restriction n'est pas
    decorative : une decharge que n'importe quel lecteur du courrier pourrait
    signer ne prouverait plus que le pli est arrive quelque part.

    Le controle porte sur la structure et non sur une permission : le point focal
    porte `BO_STR`, le directeur porte `AFF`, et le collegue qui recoit le
    parapheur pour un absent ne porte ni l'un ni l'autre. C'est la structure qui
    les reunit tous les trois, et c'est elle qui tient le cahier.
    """
    if affectation.utilisateur_id == utilisateur.pk:
        return
    if utilisateur.structure_id == affectation.cotation_structure.structure_id:
        return
    raise HorsPerimetre("La décharge se signe par l'agent affecté ou par sa structure.")


def exiger_la_decharge(affectation: Affectation) -> None:
    """
    Refuse le traitement tant que la decharge manque — ADR 035.

    Appelee par `rediger()` : on n'ecrit pas sur un courrier qu'on n'a pas
    reconnu avoir recu. La garde a ete ecrite le 26 aout 2026, sans appelant,
    le jour ou la decharge est nee ; l'ecran de redaction est arrive le
    lendemain et l'a trouvee la, ce qui etait exactement l'idee.

    Le parametre `courrier.acceptation_obligatoire` permet de l'eteindre sans
    redeploiement : une structure qui n'a jamais tenu de cahier ne doit pas voir
    ses agents bloques le premier jour.
    """
    if not parametres.valeur(CLE_ACCEPTATION_OBLIGATOIRE, True):
        return
    if affectation.accepte_le is None:
        raise EtatInvalide(
            "Signez d'abord la décharge : un courrier se traite après avoir été reçu."
        )


# =====================================================================
#  Le fil d'observations
# =====================================================================


def publier_observation(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Observation:
    """
    Porte une observation au dossier du courrier.

    **Tout lecteur ecrit, tout lecteur lit, jamais modifiable** — arbitrage du
    Port, 26 aout 2026. Il n'y a donc ni `modifier_observation` ni
    `supprimer_observation` dans ce module, et la table ne porte pas les colonnes
    qui les rendraient possibles. Ce n'est pas un manque : c'est la regle.

    La garde de lecture suffit a la garde d'ecriture, ce qui est rare et se dit :
    `_courrier_visible()` refuse en 404 quiconque ne voit pas le courrier, et
    quiconque le voit peut observer. Aucune permission supplementaire n'est
    exigee — `LEC` ouvre la route.

    Aucune notification. Un fil qui previent tout le monde a chaque ligne cesse
    d'etre lu au bout d'une semaine, et personne n'a demande d'alerte sur les
    observations (A72).
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    texte = (saisie.get("texte") or "").strip()
    if not texte:
        raise ErreurMetier("Une observation vide ne se publie pas.")
    if len(texte) > 4000:
        raise ErreurMetier("Une observation ne dépasse pas 4 000 caractères.")

    with acteur(utilisateur):
        observation = Observation.objects.create(
            courrier=courrier,
            auteur=utilisateur,
            texte=texte,
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.observation",
            libelle="Observation portée au dossier",
            # Le texte n'est pas recopie dans le journal : il vit dans sa table,
            # et une observation retranscrite deux fois se contredit un jour.
            detail=None,
            acteur=utilisateur,
            # **Jalon public.** Le fil est commun a toutes les structures cotees
            # (ADR 034) : cloisonner l'evenement alors que l'observation, elle,
            # se lit de partout aurait produit une fiche de vie qui ment par
            # omission.
            structure_id=None,
            donnees={"observationId": observation.pk},
        )

    return observation


# =====================================================================
#  Le signalement d'ecart — A-12
# =====================================================================


def signaler_ecart(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> SignalementEcart:
    """
    Ouvre un ecart sur le circuit papier d'un courrier.

    **L'emetteur choisit la structure destinataire** (arbitrage du 26 aout 2026)
    et c'est son responsable qui prend l'ecart en charge. Viser une personne
    aurait bloque le registre le jour de son absence.

    Ouvert par tout lecteur, sous `LEC` : l'agent qui constate un pli incomplet
    n'a pas de raison de porter une permission d'ecriture pour le dire.

    La structure de l'emetteur est **figee** a l'emission : une mutation ne doit
    pas reecrire d'ou venait l'alerte.
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    type_ecart = saisie.get("type")
    if type_ecart not in dict(SignalementEcart.TYPES):
        raise ErreurMetier(f"Type d'écart inconnu : « {type_ecart} ».")

    gravite = saisie.get("gravite") or "NOTABLE"
    if gravite not in dict(SignalementEcart.GRAVITES):
        raise ErreurMetier(f"Gravité inconnue : « {gravite} ».")

    description = (saisie.get("description") or "").strip()
    if len(description) < 10:
        raise ErreurMetier(
            "Décrivez l'écart en quelques mots : « pli incomplet » ne se traite pas."
        )

    cible = saisie.get("destinataireStructureId")
    if not isinstance(cible, int):
        raise ErreurMetier("Indiquez la structure qui doit prendre l'écart en charge.")

    destinataire = Structure.objects.filter(pk=cible, invalide_le__isnull=True).first()
    if destinataire is None:
        raise ErreurMetier("La structure destinataire n'existe pas.")

    with acteur(utilisateur):
        signalement = SignalementEcart.objects.create(
            courrier=courrier,
            type_ecart=type_ecart,
            gravite=gravite,
            description=description,
            destinataire_structure=destinataire,
            emetteur_structure_id=utilisateur.structure_id,
            emis_par=utilisateur,
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.ecart_signale",
            libelle=f"Écart signalé : {dict(SignalementEcart.TYPES)[type_ecart]}",
            detail=destinataire.libelle,
            acteur=utilisateur,
            # **Jalon public.** Un ecart concerne deux structures — celle qui
            # signale et celle qui recoit. Le cloisonner sur l'une des deux
            # l'aurait rendu invisible a l'autre, qui est justement celle qui
            # doit agir.
            structure_id=None,
            donnees={
                "signalementId": signalement.pk,
                "type": type_ecart,
                "gravite": gravite,
                "destinataire": destinataire.code,
            },
        )

        _prevenir_du_signalement(signalement, destinataire, courrier, utilisateur)

    return signalement


def avancer_signalement(
    signalement_id: int, saisie: dict, utilisateur: Utilisateur
) -> SignalementEcart:
    """
    Fait passer un ecart a l'etat suivant — `ouvert` puis `pris_en_compte` puis
    `clos`.

    **Un seul sens.** Rien ne revient en arriere : un ecart rouvert est un nouvel
    ecart. Sans cette regle, la duree de prise en charge — la seule chose que ce
    registre mesure — se remettrait a zero a chaque hesitation.

    La cloture exige une suite donnee. Un ecart clos sans un mot ne se distingue
    pas d'un ecart oublie, et c'est precisement ce que le registre existe pour
    empecher.

    La garde de perimetre est ici et non dans la route : seule la **structure
    visee** fait avancer l'ecart. L'emetteur, lui, le suit sans le refermer — a
    quoi bon signaler si l'on clot soi-meme.
    """
    signalement = (
        SignalementEcart.objects.filter(pk=signalement_id)
        .select_related("courrier", "destinataire_structure", "emis_par")
        .first()
    )
    if signalement is None:
        raise HorsPerimetre("Ce signalement n'existe pas.")

    # Le courrier doit rester visible : un ecart n'ouvre pas une porte sur un
    # dossier que l'agent n'aurait pas le droit de lire.
    _courrier_visible(signalement.courrier_id, utilisateur)

    if utilisateur.structure_id != signalement.destinataire_structure_id:
        raise HorsPerimetre("Seule la structure destinataire fait avancer un signalement.")

    suivant = _etat_suivant(signalement.etat)
    if suivant is None:
        raise EtatInvalide("Ce signalement est clos : il n'avance plus.")

    # L'ecran envoie l'etat qu'il croit atteindre. Le comparer n'est pas une
    # politesse : deux agents qui ouvrent le meme signalement voient tous deux
    # « prendre en compte », et le second ne doit pas clore sans l'avoir voulu.
    vise = saisie.get("etat")
    if vise is not None and vise != suivant:
        raise EtatInvalide(
            f"Un signalement {dict(SignalementEcart.ETATS)[signalement.etat].lower()} "
            f"ne passe qu'à « {dict(SignalementEcart.ETATS)[suivant].lower()} »."
        )

    maintenant = timezone.now()
    champs = ["etat"]
    signalement.etat = suivant

    if suivant == SignalementEcart.ETAT_PRIS_EN_COMPTE:
        signalement.pris_en_compte_le = maintenant
        signalement.pris_en_compte_par = utilisateur
        champs += ["pris_en_compte_le", "pris_en_compte_par"]
    else:
        suite = (saisie.get("suiteDonnee") or "").strip()
        if not suite:
            raise ErreurMetier(
                "Dites ce qui a été fait : un écart clos sans un mot ne se relit pas."
            )
        signalement.clos_le = maintenant
        signalement.clos_par = utilisateur
        signalement.suite_donnee = suite
        champs += ["clos_le", "clos_par", "suite_donnee"]

    with acteur(utilisateur):
        signalement.save(update_fields=champs)

        inscrire(
            objet_type="courrier",
            objet_id=signalement.courrier_id,
            courrier_id=signalement.courrier_id,
            type_evenement=f"courrier.ecart_{suivant}",
            libelle=f"Écart {dict(SignalementEcart.ETATS)[suivant].lower()}",
            detail=signalement.suite_donnee,
            acteur=utilisateur,
            structure_id=None,
            donnees={"signalementId": signalement.pk, "etat": suivant},
        )

        # Celui qui a signale apprend ce qu'il est devenu de son alerte. C'est la
        # difference entre un registre et une boite aux lettres.
        if signalement.emis_par_id != utilisateur.pk:
            notifications.notifier(
                signalement.emis_par,
                type_notification="courrier_ecart_suivi",
                libelle=f"Écart {dict(SignalementEcart.ETATS)[suivant].lower()}",
                detail=signalement.suite_donnee or signalement.destinataire_structure.libelle,
                objet_type="courrier",
                objet_id=signalement.courrier_id,
                lien=f"/courriers/{signalement.courrier_id}",
                acteur=utilisateur,
            )

    return signalement


def _etat_suivant(etat: str) -> str | None:
    """L'etat qui suit, ou `None` quand l'ecart est clos."""
    return {
        SignalementEcart.ETAT_OUVERT: SignalementEcart.ETAT_PRIS_EN_COMPTE,
        SignalementEcart.ETAT_PRIS_EN_COMPTE: SignalementEcart.ETAT_CLOS,
    }.get(etat)


def _prevenir_du_signalement(
    signalement: SignalementEcart,
    destinataire: Structure,
    courrier: Courrier,
    utilisateur: Utilisateur,
) -> None:
    """
    Previent le responsable de la structure visee.

    Un ecart signale que personne ne lit vaut le coup de telephone qu'il devait
    remplacer. Le responsable est retrouve par `responsables_comptes()`, la meme
    fonction qui sert la cotation : deux facons de designer un responsable
    auraient fini par en designer deux differents.
    """
    responsable = responsables_comptes(Structure.objects.filter(pk=destinataire.pk)).get(
        destinataire.pk
    )
    if responsable is None or responsable.pk == utilisateur.pk:
        return

    notifications.notifier(
        responsable,
        type_notification="courrier_ecart_signale",
        libelle=f"Écart signalé sur le courrier {courrier.numero}",
        detail=signalement.description,
        importance="alerte" if signalement.gravite == "BLOQUANTE" else None,
        objet_type="courrier",
        objet_id=courrier.pk,
        lien=f"/courriers/{courrier.pk}",
        acteur=utilisateur,
    )


# =====================================================================
#  Le traitement, et la restitution au responsable
# =====================================================================


#: Le format du contenu d'un traitement. Le socle accepte `html`, l'ecran de
#: redaction n'offre pas d'editeur riche : ecrire `html` pour du texte brut
#: ferait rendre un jour, par un autre ecran, des chevrons comme du balisage.
FORMAT_TRAITEMENT = "texte"


def rediger(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Traitement:
    """
    L'agent cote ecrit ce qu'il a fait du courrier — le brouillon.

    C'est le geste que le Port a decrit en une phrase : « les agents traitent le
    courrier puis le restituent au responsable de structure » (26 aout 2026).
    `rediger()` porte la premiere moitie, `restituer()` la seconde.

    **Un traitement par agent et par courrier**, repris a chaque enregistrement.
    Le contraire — une ligne par sauvegarde — aurait rempli le registre de
    versions que personne n'a rendues, et rendu incomprehensible la question
    « qu'a-t-il ecrit ? ».

    La decharge conditionne l'ecriture (ADR 035) : on ne traite pas un courrier
    qu'on n'a pas reconnu avoir recu. C'est ici que `exiger_la_decharge()`
    trouve enfin son appelant.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : son traitement ne se modifie plus.")

    affectation = _mon_affectation(courrier, utilisateur)
    exiger_la_decharge(affectation)

    contenu = (saisie.get("contenu") or "").strip()
    if not contenu:
        raise ErreurMetier("Un traitement vide ne dit pas ce qui a ete fait du courrier.")

    traitement = _mon_traitement(courrier, utilisateur)
    premier = traitement is None

    with acteur(utilisateur):
        if traitement is None:
            traitement = Traitement.objects.create(
                cotation_structure=affectation.cotation_structure,
                courrier=courrier,
                redacteur=utilisateur,
                contenu=contenu,
                contenu_format=FORMAT_TRAITEMENT,
                statut=Traitement.STATUT_BROUILLON,
                cree_par=utilisateur.pk,
            )
        else:
            if traitement.statut == Traitement.STATUT_SOUMIS:
                raise EtatInvalide(
                    "Ce traitement est restitué : il attend son responsable. "
                    "Demandez-lui de vous le retourner pour le reprendre."
                )
            traitement.contenu = contenu
            # Un traitement retourne redevient un brouillon des la premiere
            # correction : sans cela, l'agent verrait « retourne » jusqu'a la
            # restitution suivante, alors qu'il a repris la main.
            traitement.statut = Traitement.STATUT_BROUILLON
            traitement.modifie_le = timezone.now()
            traitement.modifie_par = utilisateur.pk
            traitement.save(update_fields=["contenu", "statut", "modifie_le", "modifie_par"])

        # Un evenement a l'ouverture, **pas a chaque frappe**. Le journal est
        # l'histoire du courrier : « a commence a traiter » en est un chapitre,
        # « a enregistre son brouillon pour la neuvieme fois » n'en est pas un.
        if premier:
            inscrire(
                objet_type="courrier",
                objet_id=courrier.pk,
                courrier_id=courrier.pk,
                type_evenement="courrier.traitement_ouvert",
                libelle=f"Traitement ouvert par {utilisateur.prenom} {utilisateur.nom}",
                acteur=utilisateur,
                # Geste interne a la structure cotee — ADR 032. Le brouillon
                # d'un agent de la DAF ne regarde pas la DSI cotee a cote.
                structure_id=affectation.cotation_structure.structure_id,
                donnees={"traitementId": traitement.pk},
            )

    return traitement


def restituer(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Traitement:
    """
    L'agent rend son traitement au responsable de structure — l'etape RESTITUE.

    Le Port ne connait **pas de validation hierarchique** sur le courrier arrive
    (ADR 034) : ce qui suit n'est pas un visa, c'est une lecture. Le responsable
    cloture, ou retourne.

    Une version est figee a chaque restitution — jamais a l'enregistrement du
    brouillon. Ce qui merite d'etre garde est ce que l'agent a rendu.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : il n'y a plus rien a restituer.")

    traitement = _mon_traitement(courrier, utilisateur)
    if traitement is None:
        raise EtatInvalide("Ecrivez le traitement avant de le restituer.")
    if traitement.statut == Traitement.STATUT_SOUMIS:
        raise EtatInvalide("Ce traitement est deja restitué.")
    if not (traitement.contenu or "").strip():
        raise ErreurMetier("Un traitement vide ne se restitue pas.")

    affectation = _mon_affectation(courrier, utilisateur)
    structure = affectation.cotation_structure.structure

    with acteur(utilisateur):
        traitement.statut = Traitement.STATUT_SOUMIS
        traitement.soumis_le = timezone.now()
        traitement.modifie_le = traitement.soumis_le
        traitement.modifie_par = utilisateur.pk
        traitement.save(update_fields=["statut", "soumis_le", "modifie_le", "modifie_par"])

        TraitementVersion.objects.create(
            traitement=traitement,
            version=traitement.version,
            contenu=traitement.contenu,
            redacteur=utilisateur,
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.restitue",
            libelle=f"Restitué par {utilisateur.prenom} {utilisateur.nom}",
            detail=structure.libelle,
            acteur=utilisateur,
            structure_id=structure.pk,
            donnees={"traitementId": traitement.pk, "version": traitement.version},
        )

        _prevenir_de_la_restitution(courrier, affectation, utilisateur)

    return traitement


def retourner(
    identifiant: int, traitement_id: int, saisie: dict, utilisateur: Utilisateur
) -> Traitement:
    """
    Le responsable rend le traitement a son auteur, avec un motif.

    **HYPOTHESE** — le Port n'a pas decrit ce geste ; il a dit « le responsable
    cloture, fin ». Le statut `retourne` existe pourtant au socle depuis le
    premier jour, et un responsable qui ne peut que clore n'a d'autre recours,
    devant un traitement insuffisant, que de le clore quand meme ou de laisser
    le courrier ouvert sans rien dire. Le motif est obligatoire pour la meme
    raison que la suite donnee d'un ecart : un retour sans un mot ne se
    distingue pas d'un oubli. Voir A74.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos.")

    traitement = (
        Traitement.objects.filter(pk=traitement_id, courrier=courrier, invalide_le__isnull=True)
        .select_related("redacteur", "cotation_structure__structure")
        .first()
    )
    if traitement is None:
        raise HorsPerimetre("Ce traitement n'existe pas ou ne relève pas de ce courrier.")
    if traitement.statut != Traitement.STATUT_SOUMIS:
        raise EtatInvalide("Seul un traitement restitué se retourne.")

    _exiger_la_structure_cotee(traitement.cotation_structure.structure_id, utilisateur)

    motif = (saisie.get("motif") or "").strip()
    if len(motif) < 10:
        raise ErreurMetier(
            "Dites ce qui manque : un retour sans un mot ne se distingue pas d'un oubli."
        )

    with acteur(utilisateur):
        traitement.statut = Traitement.STATUT_RETOURNE
        # La version suivante appartient a la reprise : l'agent qui corrige rend
        # une version 2, et l'ecart avec la 1 est la seule trace de ce qui
        # n'allait pas.
        traitement.version += 1
        traitement.modifie_le = timezone.now()
        traitement.modifie_par = utilisateur.pk
        traitement.save(update_fields=["statut", "version", "modifie_le", "modifie_par"])

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.traitement_retourne",
            libelle=f"Traitement retourné à {traitement.redacteur.prenom} "
            f"{traitement.redacteur.nom}",
            detail=motif,
            acteur=utilisateur,
            structure_id=traitement.cotation_structure.structure_id,
            donnees={"traitementId": traitement.pk, "motif": motif},
        )

        if traitement.redacteur_id != utilisateur.pk:
            notifications.notifier(
                traitement.redacteur,
                type_notification="courrier_traitement_retourne",
                libelle=f"Courrier {courrier.numero} : traitement à reprendre",
                detail=motif,
                objet_type="courrier",
                objet_id=courrier.pk,
                lien=f"/courriers/{courrier.pk}",
                acteur=utilisateur,
            )

    return traitement


def _prevenir_de_la_restitution(
    courrier: Courrier, affectation: Affectation, auteur: Utilisateur
) -> None:
    """
    Previent celui qui attend le traitement : le responsable de la structure.

    Celui qui a **affecte** d'abord — c'est lui qui a mis l'agent sur l'affaire,
    et c'est a lui que le trajet decrit rend le courrier. A defaut (compte parti,
    affectation reprise), le responsable en poste de la structure cotee.
    """
    destinataire = affectation.affecte_par
    if destinataire is None:
        comptes = responsables_comptes(
            Structure.objects.filter(pk=affectation.cotation_structure.structure_id)
        )
        destinataire = comptes.get(affectation.cotation_structure.structure_id)
    if destinataire is None or destinataire.pk == auteur.pk:
        return

    notifications.notifier(
        destinataire,
        type_notification="courrier_restitue",
        libelle=f"Courrier {courrier.numero} restitué",
        detail=f"{auteur.prenom} {auteur.nom} a rendu son traitement.",
        objet_type="courrier",
        objet_id=courrier.pk,
        lien=f"/courriers/{courrier.pk}",
        acteur=auteur,
    )


def _mon_affectation(courrier: Courrier, utilisateur: Utilisateur) -> Affectation:
    """L'affectation ouverte de cet agent sur ce courrier, ou le refus."""
    affectation = (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier=courrier,
            utilisateur=utilisateur,
            retire_le__isnull=True,
        )
        .select_related("cotation_structure__structure", "affecte_par")
        .first()
    )
    if affectation is None:
        raise HorsPerimetre("Ce courrier ne vous est pas affecté.")
    return affectation


def _mon_traitement(courrier: Courrier, utilisateur: Utilisateur) -> Traitement | None:
    return (
        Traitement.objects.filter(
            courrier=courrier, redacteur=utilisateur, invalide_le__isnull=True
        )
        .order_by("-cree_le")
        .first()
    )


def _exiger_la_structure_cotee(structure_id: int, utilisateur: Utilisateur) -> None:
    """
    Le geste du responsable se fait **dans sa structure**.

    La permission dit ce que l'agent sait faire, pas ou il peut le faire : sans
    ce controle, un responsable de la DAF retournerait le traitement d'un agent
    de la DSI. Les portees larges — direction generale, suivi — passent par
    `visibles()` en amont et ne sont pas rattachees a la structure cotee : elles
    lisent, elles ne reprennent pas la main sur le travail d'autrui.
    """
    if utilisateur.structure_id != structure_id:
        raise HorsPerimetre("Ce traitement relève d'une autre structure.")


# =====================================================================
#  La cloture
# =====================================================================


def clore(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> Courrier:
    """
    Le responsable de structure cloture le courrier — la fin du trajet.

    « Le responsable cloture, fin » (arbitrage du Port, 26 aout 2026). Il n'y a
    ni visa, ni contreseing, ni retour au bureau d'ordre central : la cloture
    est le dernier geste, et elle est **definitive**. Ce qui suit ne se rouvre
    pas — un courrier reouvert aurait deux dates de fin, et le delai de
    traitement n'en mesurerait plus aucune.

    **Elle n'exige pas de traitement.** Beaucoup de courriers arrivent pour
    information et se closent sans que personne n'ecrive : exiger un traitement
    aurait force l'agent a ecrire « pour information » pour pouvoir refermer.
    Un traitement encore restitue, lui, est **valide** par la cloture : c'est ce
    que le responsable dit en cloturant.

    Un brouillon en cours, en revanche, arrete le geste. Clore sous les doigts
    de l'agent qui ecrit encore lui ferait perdre son travail sans un mot.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est déjà clos.")

    _exiger_la_qualite_pour_clore(courrier, utilisateur)

    en_cours = list(
        Traitement.objects.filter(
            courrier=courrier,
            statut__in=[Traitement.STATUT_BROUILLON, Traitement.STATUT_RETOURNE],
            invalide_le__isnull=True,
        ).select_related("redacteur")
    )
    if en_cours and not saisie.get("malgreLesBrouillons"):
        noms = ", ".join(f"{t.redacteur.prenom} {t.redacteur.nom}" for t in en_cours)
        raise EtatInvalide(
            f"Un traitement est encore en cours de rédaction ({noms}). "
            "Clôturez tout de même si la réponse est partie autrement."
        )

    observation = (saisie.get("observation") or "").strip() or None

    ferme_le = timezone.now()
    with acteur(utilisateur):
        # `cloture_le` n'est pas facultatif : le socle porte
        # `courrier_cloture_coherente`, qui exige que le statut « cloture » et
        # la date aillent ensemble. Poser le statut seul leve une IntegrityError
        # — c'est la contrainte qui a rattrape l'oubli, et c'est son role.
        courrier.statut_courrier = STATUT_CLOTURE
        courrier.cloture_le = ferme_le
        courrier.cloture_par_id = utilisateur.pk
        courrier.motif_cloture = observation
        courrier.modifie_le = ferme_le
        courrier.modifie_par = utilisateur.pk
        courrier.save(
            update_fields=[
                "statut_courrier",
                "cloture_le",
                "cloture_par",
                "motif_cloture",
                "modifie_le",
                "modifie_par",
            ]
        )

        Traitement.objects.filter(
            courrier=courrier, statut=Traitement.STATUT_SOUMIS, invalide_le__isnull=True
        ).update(statut=Traitement.STATUT_VALIDE, modifie_le=ferme_le, modifie_par=utilisateur.pk)

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.cloture",
            libelle=f"Clôturé par {utilisateur.prenom} {utilisateur.nom}",
            detail=observation,
            acteur=utilisateur,
            # **Jalon public** — ADR 032. La cloture est la fin du courrier, pas
            # un geste interne : le bureau d'ordre central, la DSR et les autres
            # structures cotees doivent la voir, sinon leur registre montre
            # encore un courrier ouvert que plus personne ne traite.
            structure_id=None,
            donnees={"observation": observation},
        )

        _prevenir_de_la_cloture(courrier, utilisateur, observation)

    return courrier


def _exiger_la_qualite_pour_clore(courrier: Courrier, utilisateur: Utilisateur) -> None:
    """
    Qui cloture : une structure **cotee** sur ce courrier.

    `CLO` dit que l'agent sait clore, pas quel courrier. Sans ce controle, le
    responsable d'une direction refermerait le dossier d'une autre — et le
    trajet decrit par le Port rend le courrier au responsable *de la structure
    qui l'a traite*, a personne d'autre.

    Le bureau d'ordre **central** en est exempte : il cote, il ne traite pas, et
    c'est lui qui referme les courriers qui n'ont jamais ete cotes a personne
    (classes sans suite, doublons reconnus apres coup). Sa qualite se lit a la
    session d'enregistrement, comme partout ailleurs (ADR 022).
    """
    session = session_en_cours(utilisateur)
    if session is not None and session.pk == courrier.session_id:
        return

    if utilisateur.structure_id is None:
        raise HorsPerimetre("Ce courrier n'est pas coté à votre structure.")

    cotee = CotationStructure.objects.filter(
        cotation__courrier=courrier,
        cotation__invalide_le__isnull=True,
        structure_id=utilisateur.structure_id,
    ).exists()
    if not cotee:
        raise HorsPerimetre("Ce courrier n'est pas coté à votre structure.")


def _prevenir_de_la_cloture(
    courrier: Courrier, auteur: Utilisateur, observation: str | None
) -> None:
    """
    Previent ceux qui travaillaient dessus : leur delai s'arrete.

    Les agents affectes, pas les structures cotees — c'est le meme choix que
    `_prevenir_du_report()`, et pour la meme raison : le delai court sur une
    personne.
    """
    destinataires = (
        Utilisateur.objects.filter(
            affectations_courrier__cotation_structure__cotation__courrier=courrier,
            affectations_courrier__retire_le__isnull=True,
            actif=True,
        )
        .exclude(pk=auteur.pk)
        .distinct()
    )
    for agent in destinataires:
        notifications.notifier(
            agent,
            type_notification="courrier_cloture",
            libelle=f"Courrier {courrier.numero} clôturé",
            detail=observation or "Le dossier est refermé.",
            objet_type="courrier",
            objet_id=courrier.pk,
            lien=f"/courriers/{courrier.pk}",
            acteur=auteur,
        )


# =====================================================================
#  Le pilier suivi — les quatre gestes du dossier (C-01, A-14)
# =====================================================================


def ajouter_tache(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> TacheTraitement:
    """
    Ajoute une etape a la liste que l'agent se donne sur un courrier.

    **La liste appartient a une personne.** Deux agents affectes au meme dossier
    tiennent deux listes ; celle-ci ne s'impose a personne et ne represente pas
    le circuit du courrier — l'ecran C-01 le dit dans ses propres termes.

    Aucun evenement au journal, et c'est delibere : le journal est l'histoire du
    **courrier** (ADR 012), pas le brouillon de celui qui le traite. Y verser
    chaque case cochee noierait la cotation et la cloture sous des lignes que
    personne ne relira. La regle « toute ecriture metier inscrit un evenement »
    vise les actes opposables ; une liste de courses n'en est pas un.
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    libelle = (saisie.get("libelle") or "").strip()
    if not libelle:
        raise ErreurMetier("Une étape sans libellé ne s'ajoute pas.")
    if len(libelle) > 300:
        raise ErreurMetier("Le libellé d'une étape ne dépasse pas 300 caractères.")

    # Le rang suivant, calcule sur la seule liste de cet agent : deux agents
    # numerotent leurs etapes chacun de leur cote.
    dernier = (
        TacheTraitement.objects.filter(
            courrier=courrier, utilisateur=utilisateur, invalide_le__isnull=True
        ).aggregate(rang=models.Max("ordre"))["rang"]
        or 0
    )

    with acteur(utilisateur):
        return TacheTraitement.objects.create(
            courrier=courrier,
            utilisateur=utilisateur,
            libelle=libelle,
            ordre=dernier + 1,
            cree_par=utilisateur.pk,
        )


def basculer_tache(
    identifiant: int, tache_id: int, saisie: dict, utilisateur: Utilisateur
) -> TacheTraitement:
    """
    Coche ou decoche une etape.

    Decocher est permis : une case cochee par erreur se corrige, et la date de
    realisation repart a `NULL`. Ce n'est pas une trace, c'est un pense-bete.

    La tache est cherchee **sur l'agent connecte** : personne ne coche la liste
    d'un autre, et un identifiant vole ne donne donc rien.
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    tache = TacheTraitement.objects.filter(
        pk=tache_id, courrier=courrier, utilisateur=utilisateur, invalide_le__isnull=True
    ).first()
    if tache is None:
        raise HorsPerimetre("Étape introuvable.")

    with acteur(utilisateur):
        tache.faite_le = timezone.now() if saisie.get("faite") else None
        tache.save(update_fields=["faite_le"])
    return tache


def publier_note(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> NoteTraitement:
    """
    Porte une note de travail au dossier.

    **A ne pas confondre avec l'observation.** Le fil d'observations est commun —
    « tout lecteur ecrit, tout lecteur lit », arbitrage du Port du 26 aout 2026 ;
    la note, elle, peut etre privee, et se lit alors par son auteur et sa
    hierarchie seulement. Deux tables, deux regles de lecture ; melanger les deux
    aurait defait l'arbitrage dans la table qui le porte.

    Non modifiable, comme l'observation : une note reecrite apres coup ne vaut
    pas comme trace de ce qu'on pensait ce jour-la.

    Aucun evenement au journal pour une note **privee** : l'inscrire y aurait
    annonce a toute la fiche de vie l'existence d'un texte que la fiche de vie ne
    montre pas — la trace aurait trahi ce que la note protege. Une note publique
    n'en inscrit pas davantage, pour rester coherente avec sa jumelle privee.
    """
    courrier = _courrier_visible(identifiant, utilisateur)

    texte = (saisie.get("texte") or "").strip()
    if not texte:
        raise ErreurMetier("Une note vide ne se publie pas.")
    if len(texte) > 4000:
        raise ErreurMetier("Une note ne dépasse pas 4 000 caractères.")

    with acteur(utilisateur):
        return NoteTraitement.objects.create(
            courrier=courrier,
            auteur=utilisateur,
            texte=texte,
            # Privee par defaut : le doute profite a la discretion. L'agent qui
            # veut ecrire a tous decoche, et il le fait sciemment.
            privee=bool(saisie.get("privee", True)),
        )


#: Le plafond d'une demande de report, en jours ouvres. Trois mois : au-dela, ce
#: n'est plus un report, c'est une requalification du delai, et elle se decide
#: ailleurs. Le schema porte la meme borne en CHECK.
REPORT_MAXIMAL_JOURS = 90


def demander_delai(identifiant: int, saisie: dict, utilisateur: Utilisateur) -> DemandeDelai:
    """
    L'agent demande a son responsable de reporter l'echeance.

    **Le geste qui manquait.** `prolonger()` existe depuis le debut : c'est celui
    de qui **accorde**, sous permission de cotation. Celui de qui demande passait
    par le telephone — sans trace, pendant que le delai courait contre l'agent.

    Une seule demande en attente par agent et par courrier : l'index unique
    partiel `demande_delai_une_seule_en_attente` le garantit, et la garde ci-
    dessous rend le refus lisible plutot que technique. Redemander n'est pas
    relancer.

    La demande **ne reporte rien**. Elle previent le responsable, et l'echeance
    ne bouge qu'a la decision — par `decider_demande_delai`, qui appelle
    `prolonger()`.
    """
    courrier = _courrier_visible(identifiant, utilisateur)
    if courrier.statut_courrier == STATUT_CLOTURE:
        raise EtatInvalide("Ce courrier est clos : son délai ne se reporte plus.")
    if courrier.date_limite is None:
        raise EtatInvalide(
            "Ce courrier n'a pas d'échéance : il n'y a rien à reporter. "
            "Un délai se fixe à la cotation."
        )

    jours = saisie.get("joursDemandes")
    if not isinstance(jours, int) or jours < 1 or jours > REPORT_MAXIMAL_JOURS:
        raise ErreurMetier(f"Un report se demande entre 1 et {REPORT_MAXIMAL_JOURS} jours ouvrés.")

    motif = (saisie.get("motif") or "").strip()
    if not motif:
        raise ErreurMetier("Une demande de report se motive.")
    if len(motif) > 2000:
        raise ErreurMetier("Le motif ne dépasse pas 2 000 caractères.")

    if DemandeDelai.objects.filter(
        courrier=courrier, demandeur=utilisateur, etat=DEMANDE_EN_ATTENTE
    ).exists():
        raise EtatInvalide(
            "Vous avez déjà une demande de report en attente sur ce courrier. "
            "Attendez la réponse de votre responsable."
        )

    with acteur(utilisateur):
        demande = DemandeDelai.objects.create(
            courrier=courrier,
            demandeur=utilisateur,
            jours_demandes=jours,
            motif=motif,
        )

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.delai_demande",
            libelle=f"Report de {jours} jours demandé",
            detail=motif,
            acteur=utilisateur,
            donnees={"demandeId": demande.pk, "joursDemandes": jours},
        )

        _prevenir_de_la_demande(courrier, demande, utilisateur)

    return demande


def _prevenir_de_la_demande(
    courrier: Courrier, demande: DemandeDelai, demandeur: Utilisateur
) -> None:
    """
    Previent le responsable de la structure du demandeur.

    **Une demande que personne ne lit ne vaut pas mieux que le telephone.**
    C'est la seule notification du pilier suivi, et elle porte tout son interet :
    l'agent sait que sa demande est partie a quelqu'un.

    Silence si l'agent n'a pas de structure ou si sa structure n'a pas de
    responsable connu : la demande reste en base et se voit dans la fiche de vie.
    Inventer un destinataire aurait ete pire.
    """
    structure_id = demandeur.structure_id
    if structure_id is None:
        return

    responsable = responsables_comptes(Structure.objects.filter(pk=structure_id)).get(structure_id)
    if responsable is None or responsable.pk == demandeur.pk:
        return

    notifications.notifier(
        responsable,
        type_notification="delai_demande",
        libelle=f"Report demandé sur le courrier {courrier.numero}",
        detail=f"{demandeur.nom_complet} demande {demande.jours_demandes} jours de plus.",
        objet_type="courrier",
        objet_id=courrier.pk,
        lien=f"/courriers/{courrier.pk}",
        acteur=demandeur,
    )


def decider_demande_delai(demande_id: int, saisie: dict, utilisateur: Utilisateur) -> DemandeDelai:
    """
    Le responsable accorde ou refuse le report.

    **Accorder prolonge reellement le courrier** : la fonction appelle
    `prolonger()` plutot que d'ecrire `date_limite` elle-meme. Deux chemins
    d'ecriture vers la meme colonne finissent toujours par diverger — l'un
    oublierait `delai_reglementaire_jours`, et la jauge de la fiche mentirait.

    Le refus se motive comme l'accord : l'agent qui se voit refuser un report
    doit savoir pourquoi, sinon il redemande.

    La permission est portee par la route (`PERM.COT` : qui fixe un delai le
    reporte). Ici on verifie seulement que le courrier reste visible — un
    responsable mute ne decide pas sur un dossier qu'il ne voit plus.
    """
    demande = DemandeDelai.objects.filter(pk=demande_id).select_related("courrier").first()
    if demande is None:
        raise HorsPerimetre("Demande introuvable.")

    courrier = _courrier_visible(demande.courrier_id, utilisateur)
    if demande.etat != DEMANDE_EN_ATTENTE:
        raise EtatInvalide("Cette demande a déjà été tranchée.")
    if demande.demandeur_id == utilisateur.pk:
        raise ErreurMetier("On ne s'accorde pas à soi-même le report qu'on demande.")

    accordee = bool(saisie.get("accordee"))
    reponse = (saisie.get("reponse") or "").strip()
    if not accordee and not reponse:
        raise ErreurMetier("Un refus se motive.")

    if accordee:
        # Le motif porte au journal de la prolongation cite la demande : relire
        # « prolonge de 3 jours » sans savoir qui l'a demande ne renseigne pas.
        defaut = f"Report demandé par {demande.demandeur.nom_complet} : {demande.motif}"
        prolonger(
            courrier.pk,
            {"delaiJours": demande.jours_demandes, "motif": reponse or defaut},
            utilisateur,
        )

    with acteur(utilisateur):
        demande.etat = DEMANDE_ACCORDEE if accordee else DEMANDE_REFUSEE
        demande.decidee_le = timezone.now()
        demande.decidee_par = utilisateur
        demande.reponse = reponse or None
        demande.save(update_fields=["etat", "decidee_le", "decidee_par", "reponse"])

        inscrire(
            objet_type="courrier",
            objet_id=courrier.pk,
            courrier_id=courrier.pk,
            type_evenement="courrier.delai_decide",
            libelle="Report accordé" if accordee else "Report refusé",
            detail=reponse or None,
            acteur=utilisateur,
            donnees={"demandeId": demande.pk, "accordee": accordee},
        )

        notifications.notifier(
            demande.demandeur,
            type_notification="delai_decide",
            libelle=(
                f"Report accordé sur le courrier {courrier.numero}"
                if accordee
                else f"Report refusé sur le courrier {courrier.numero}"
            ),
            detail=reponse or "Sans commentaire.",
            objet_type="courrier",
            objet_id=courrier.pk,
            lien=f"/courriers/{courrier.pk}",
            acteur=utilisateur,
        )

    return demande


def enregistrer_recherche(saisie: dict, utilisateur: Utilisateur) -> RechercheEnregistree:
    """
    Conserve les criteres d'une recherche sous un nom.

    Ce sont les **criteres** qui sont conserves, jamais les resultats : « les
    courriers hors delai de la DAF » n'a pas le meme compte lundi et vendredi, et
    c'est precisement ce que l'agent revient voir.

    Reenregistrer sous un nom deja pris **ecrase** les criteres au lieu de
    refuser : l'agent qui affine sa recherche et la resauvegarde du meme nom veut
    la remplacer, pas lire un message d'erreur. L'unicite en base sert alors de
    clef, non de barriere.
    """
    libelle = (saisie.get("libelle") or "").strip()
    if not libelle:
        raise ErreurMetier("Une recherche enregistrée porte un nom.")
    if len(libelle) > 120:
        raise ErreurMetier("Le nom d'une recherche ne dépasse pas 120 caractères.")

    criteres = saisie.get("criteres")
    if not isinstance(criteres, dict):
        raise ErreurMetier("Les critères de la recherche sont manquants.")

    existantes = RechercheEnregistree.objects.filter(utilisateur=utilisateur)
    if (
        not existantes.filter(libelle=libelle).exists()
        and existantes.count() >= PLAFOND_RECHERCHES_ENREGISTREES
    ):
        raise EtatInvalide(
            f"Vous conservez déjà {PLAFOND_RECHERCHES_ENREGISTREES} recherches. "
            "Supprimez-en une avant d'en ajouter une autre."
        )

    with acteur(utilisateur):
        enregistree, _ = RechercheEnregistree.objects.update_or_create(
            utilisateur=utilisateur,
            libelle=libelle,
            defaults={"criteres": criteres},
        )
    return enregistree


def oublier_recherche(recherche_id: int, utilisateur: Utilisateur) -> None:
    """
    Supprime pour de bon une recherche enregistree.

    **Le seul `delete()` du pilier courrier**, et il se defend : ce n'est pas une
    trace, c'est un confort. Une recherche « invalidee » qu'il faudrait ensuite
    filtrer partout aurait fait porter a l'application le poids d'un pense-bete.

    Cherchee sur l'agent connecte : personne ne supprime la liste d'un autre.
    """
    supprimees, _ = RechercheEnregistree.objects.filter(
        pk=recherche_id, utilisateur=utilisateur
    ).delete()
    if not supprimees:
        raise HorsPerimetre("Recherche introuvable.")


# =====================================================================
#  La relance — C-02, le geste que le tableau prepare
# =====================================================================

#: Le plafond d'un lot de relances. La relance se pratique par lots — on relance
#: les quatorze retards du lundi matin — mais un lot de cinq cents serait un
#: publipostage, et le destinataire cesserait de lire.
LOT_MAXIMAL = 50


def emettre_relances(identifiants: list[int], saisie: dict, utilisateur: Utilisateur) -> dict:
    """
    Relance les detenteurs d'un lot de courriers.

    **On ne relance pas un courrier, on relance quelqu'un.** La colonne
    `destinataire_id` est `NOT NULL` au socle depuis `0001`, et cette contrainte
    porte tout le geste : une relance sans destinataire n'est pas une relance,
    c'est une note. `_destinataire_de_la_relance` cherche donc l'agent affecte,
    puis a defaut le responsable de la structure cotee — et **refuse** quand il
    ne trouve ni l'un ni l'autre, plutot que d'inventer une cible.

    Le lot est **partiel par nature** : sur quatorze retards du lundi matin, deux
    seront hors perimetre ou sans detenteur. Refuser le lot entier pour deux
    lignes obligerait l'agent a deviner lesquelles ; on relance donc ce qui peut
    l'etre et on rend le compte des ecarts, que l'ecran affiche.

    Ce que cette fonction ne fait pas : aucune escalade. Le niveau d'escalade que
    le tableau affiche est **deduit** du nombre de relances (hypothese A77) ; le
    poser en base supposerait de savoir a qui l'on remonte, et le trajet du Port
    n'est pas un circuit (ADR 034).
    """
    if not identifiants:
        raise ErreurMetier("Aucun dossier sélectionné : il n'y a personne à relancer.")
    if len(identifiants) > LOT_MAXIMAL:
        raise ErreurMetier(
            f"Une relance porte sur {LOT_MAXIMAL} dossiers au plus. "
            "Au-delà, c'est un publipostage, et il cesse d'être lu."
        )

    motif = (saisie.get("motif") or "").strip()
    if len(motif) > 2000:
        raise ErreurMetier("Le motif d'une relance ne dépasse pas 2 000 caractères.")

    # Une seule requete de visibilite pour tout le lot : `_courrier_visible` par
    # ligne aurait fait cinquante fois le travail de `visibles()`.
    lisibles = {
        courrier.pk: courrier
        for courrier in visibles(
            Courrier.objects.filter(pk__in=identifiants, invalide_le__isnull=True), utilisateur
        ).select_related("structure_chef_file")
    }

    emises: list[Relance] = []
    ecartes: list[dict] = []

    with acteur(utilisateur):
        for identifiant in identifiants:
            courrier = lisibles.get(identifiant)
            if courrier is None:
                # Hors perimetre ou invalide, et on ne dit pas lequel : la
                # distinction confirmerait l'existence du courrier (D5). Un lot
                # entierement hors perimetre sort en 409 et non en 404 — c'est
                # le lot qui est refuse, pas une ressource qui manque — et le
                # message ne revele rien de plus qu'un 404 ne l'aurait fait.
                ecartes.append({"id": identifiant, "raison": "Dossier introuvable."})
                continue
            if courrier.statut_courrier == STATUT_CLOTURE:
                ecartes.append(
                    {"id": identifiant, "raison": f"{courrier.numero} est clos : rien à relancer."}
                )
                continue

            destinataire = _destinataire_de_la_relance(courrier)
            if destinataire is None:
                ecartes.append(
                    {
                        "id": identifiant,
                        "raison": (
                            f"{courrier.numero} n'est affecté à personne et sa structure n'a "
                            "pas de responsable connu : affectez-le d'abord."
                        ),
                    }
                )
                continue
            if destinataire.pk == utilisateur.pk:
                ecartes.append(
                    {"id": identifiant, "raison": f"{courrier.numero} vous est affecté à vous."}
                )
                continue

            emises.append(_emettre_une_relance(courrier, destinataire, motif, utilisateur))

    if not emises:
        # Tout le lot est ecarte : l'ecran doit dire pourquoi, et non afficher un
        # succes sur zero relance.
        raise EtatInvalide(
            ecartes[0]["raison"] if ecartes else "Aucun dossier ne pouvait être relancé."
        )

    return {"emises": emises, "ecartes": ecartes}


def _destinataire_de_la_relance(courrier: Courrier) -> Utilisateur | None:
    """
    Qui recoit la relance : l'agent qui detient le dossier, sinon le responsable.

    L'ordre n'est pas indifferent. Relancer le directeur pour un dossier confie a
    son agent le ferait remonter une information qu'il a deja deleguee ; relancer
    l'agent d'un dossier que personne n'a pris est impossible — et c'est
    precisement le motif de relance le plus frequent, celui ou le tableau affiche
    « Non affecté ».

    La derniere affectation vivante l'emporte : c'est le detenteur actuel, pas le
    premier a qui le dossier est passe.
    """
    affectation = (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier=courrier,
            cotation_structure__cotation__invalide_le__isnull=True,
            retire_le__isnull=True,
            utilisateur__actif=True,
        )
        .select_related("utilisateur")
        .order_by("-affecte_le")
        .first()
    )
    if affectation is not None:
        return affectation.utilisateur

    # A defaut, le responsable de la structure cotee en chef de file — celle qui
    # repond du dossier. Les structures cotees en appui ne repondent de rien.
    structures = Structure.objects.filter(
        pk__in=CotationStructure.objects.filter(
            cotation__courrier=courrier, cotation__invalide_le__isnull=True
        ).values("structure_id")
    )
    if courrier.structure_chef_file_id is not None:
        structures = Structure.objects.filter(pk=courrier.structure_chef_file_id)

    responsables = responsables_comptes(structures)
    return next(iter(responsables.values()), None)


def _emettre_une_relance(
    courrier: Courrier, destinataire: Utilisateur, motif: str, emetteur: Utilisateur
) -> Relance:
    """
    Une relance : la ligne, l'evenement, la notification.

    Les trois vont ensemble et dans cet ordre. La ligne compte au tableau — c'est
    elle qui fait avancer « Dernière relance » et le niveau d'escalade ;
    l'evenement la porte a la fiche de vie, ou le destinataire relira pourquoi on
    lui a ecrit ; la notification est le seul de ces trois gestes qu'il verra le
    jour meme.
    """
    relance = Relance.objects.create(
        courrier=courrier,
        nature=RELANCE_MANUELLE,
        emetteur=emetteur,
        destinataire=destinataire,
        motif=motif or None,
    )

    inscrire(
        objet_type="courrier",
        objet_id=courrier.pk,
        courrier_id=courrier.pk,
        type_evenement="courrier.relance",
        libelle=f"Relance adressée à {destinataire.nom_complet}",
        detail=motif or None,
        acteur=emetteur,
        donnees={"relanceId": relance.pk, "destinataireId": destinataire.pk},
    )

    notifications.notifier(
        destinataire,
        type_notification="courrier_relance",
        libelle=f"Relance sur le courrier {courrier.numero}",
        detail=motif or "Ce dossier dépasse son délai.",
        objet_type="courrier",
        objet_id=courrier.pk,
        lien=f"/suivi/{courrier.pk}",
        acteur=emetteur,
    )
    return relance
