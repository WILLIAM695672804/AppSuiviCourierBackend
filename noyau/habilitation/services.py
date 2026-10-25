"""
Regles de l'habilitation.

Les routes valident, appellent, serialisent. **Tout ce qui decide est ici** —
c'est ce qui rend ces regles testables sans HTTP, et reutilisables par une
tache planifiee le jour ou la revocation des delegations echues sera
automatisee.

Trois regles gouvernent ce module, et aucune n'est negociable :

 1. **On ne delegue que ce qu'on possede.** Sinon la delegation devient une
    escalade de privileges : il suffirait de deleguer a soi-meme.
 2. **Un profil systeme ne se retire pas du catalogue.** Ses droits, eux, se
    modifient : le referentiel livre est une proposition, pas une camisole. Voir
    l'ADR 041.
 3. **Toute ecriture inscrit un evenement.** Distribuer des droits sans trace
    est exactement ce que RNF-TRACE-01 interdit.
"""

from __future__ import annotations

from datetime import date, datetime, time

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.habilitation.dependances import PERM
from noyau.habilitation.modeles import (
    Delegation,
    DelegationPermission,
    Permission,
    Profil,
    ProfilPermission,
    UtilisateurProfil,
)
from noyau.habilitation.resolution import permissions_de
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.journal.service import inscrire
from noyau.organisation import services as organisation
from noyau.organisation.modeles import Poste, Structure
from noyau.perimetre.modeles import (
    PORTEE_PROPRE,
    PORTEE_SOUS_ARBRE,
    PORTEE_STRUCTURE,
    PORTEE_TOUTES,
    Perimetre,
)

# ---------------------------------------------------------------------
#  Les etendues delegables.
#
#  RF-BPM-04 exige « la delegation temporaire de taches et de signature,
#  avec tracabilite de la periode et du perimetre ». Il ne dit pas quels
#  gestes se delèguent ensemble, et aucun autre document ne le dit.
#
#  Ces regroupements sont donc une **hypothese de conception**. Ils ont
#  ete repris des libelles que les ecrans affichent deja, faute de
#  meilleure source. Voir docs/questions-ouvertes.md, A15.
#
#  Ce qui n'est pas une hypothese, en revanche : une delegation
#  n'accorde QUE les permissions enumerees ici, jamais celles du
#  titulaire en bloc (decision d'architecture 002).
# ---------------------------------------------------------------------
#  Chaque regroupement a ete confronte aux profils livres : au moins un
#  profil porte l'integralite de chacun. Un regroupement que personne ne
#  detient en entier n'est delegable par personne — il figurerait dans la
#  liste sans jamais etre proposable, ce qui est pire que son absence.
#  C'est arrive a la premiere redaction : « Signature » y valait
#  (VAL, CLO), or le Directeur General porte VAL et non CLO. Cloturer un
#  courrier n'est pas le signer, et c'est le Service Courrier Central qui
#  cloture.
# ---------------------------------------------------------------------
ETENDUES: dict[str, tuple[str, ...]] = {
    "Cotation": ("COT",),
    "Saisie du retour DG": ("COT_DEL",),
    "Affectation": ("AFF",),
    # Le bureau d'ordre part avec l'affectation, jamais seul : accuser reception
    # sans pouvoir remettre au collaborateur laisse le courrier sur la table du
    # remplacant. C'est le geste entier du point focal, ou rien.
    "Bureau d'ordre de la structure": ("BO_STR", "AFF"),
    "Traitement": ("TRA",),
    "Signature": ("VAL",),
    "Cloture du courrier": ("CLO",),
    "Relance": ("REL",),
    "Instruction des dossiers": ("DOS_INS", "DOS_VAL"),
    "Suivi des activites": ("ACT_SAI",),
    "Validation des plans d'actions": ("ACT_VAL",),
    # Le seul profil DSR la porte. La deleguer reste possible — c'est le
    # mecanisme prevu pour l'absence, borne et trace (ADR 002) — mais elle ne
    # part jamais avec un autre geste : contredire une structure sur ses
    # realisations n'accompagne rien d'autre.
    "Recalibrage de l'avancement": ("ACT_REC",),
    "Decisions et instructions": ("DEC", "INST"),
}


# =====================================================================
#  Comptes
# =====================================================================


def creer_compte(
    acteur: Utilisateur,
    *,
    identifiant: str,
    prenom: str,
    nom: str,
    structure_id: int,
    poste_id: int,
    profil_id: int,
    portee: str,
    perimetre_structure_id: int | None = None,
    courriel: str | None = None,
    telephone: str | None = None,
    matricule: str | None = None,
    mot_de_passe: str | None = None,
) -> Utilisateur:
    """
    Cree un compte, lui donne un profil et pose son perimetre — en un seul geste.

    **Le profil et la portee ne sont pas optionnels**, et c'est le point le plus
    important de cette fonction. Un compte sans profil ne peut rien ; un compte
    sans perimetre ne voit rien (regle 3 de `noyau/perimetre/portee.py`).
    Autoriser un compte « nu » produirait un agent qui se connecte, n'obtient
    que des listes vides, et fait chercher la panne partout ailleurs.

    Les trois ecritures sont donc atomiques : un compte a moitie cree est
    exactement ce qu'on ne veut pas avoir a rattraper a la main.

    Le `mot_de_passe` est **facultatif et provisoire**. RF-ADM-02 delegue
    l'authentification a l'annuaire ; tant que la bascule n'est pas faite, un
    administrateur doit pouvoir ouvrir un acces. Sans lui, le compte existe et
    attend le SSO — il ne peut pas se connecter. Voir
    docs/architecture/004-session-cookie-sans-jeton.md.
    """
    identifiant = (identifiant or "").strip()
    if not identifiant:
        raise ErreurMetier("L'identifiant d'annuaire est obligatoire.", code="identifiant_requis")

    _refuser_doublon(
        "identifiant_annuaire", identifiant, "Cet identifiant d'annuaire est deja pris"
    )
    _refuser_doublon("courriel", courriel, "Cette adresse est deja rattachee a un compte")
    _refuser_doublon("matricule", matricule, "Ce matricule est deja rattache a un compte")

    structure, poste = _structure_et_poste(structure_id, poste_id)

    with transaction.atomic():
        agent = Utilisateur.objects.create(
            identifiant_annuaire=identifiant,
            prenom=prenom.strip(),
            nom=nom.strip(),
            courriel=courriel or None,
            telephone=telephone or None,
            matricule=matricule or None,
            structure=structure,
            poste=poste,
            cree_par=acteur.pk,
        )
        if mot_de_passe:
            agent.set_password(mot_de_passe)
            agent.save(update_fields=["mot_de_passe"])

        inscrire(
            objet_type="utilisateur",
            objet_id=agent.pk,
            type_evenement="compte_cree",
            libelle=f"Compte « {identifiant} » cree pour {agent.nom_complet}",
            acteur=acteur,
            donnees={
                "utilisateur": agent.pk,
                "identifiant": identifiant,
                "structure": structure.pk,
                # Un acces ouvert d'emblee ou un compte en attente d'annuaire ne
                # sont pas la meme chose au regard d'un audit.
                "acces_local": bool(mot_de_passe),
            },
        )

        # L'occupation est datee des le premier jour (F-04) : un compte cree
        # sans ligne d'affectation ferait croire, six mois plus tard, que
        # personne n'a jamais tenu ce poste avant la premiere mutation.
        organisation.affecter(
            acteur,
            utilisateur_id=agent.pk,
            poste_id=poste.pk,
            motif="Affectation initiale a la creation du compte.",
        )

        attribuer_profil(acteur, agent.pk, profil_id)
        # `toutes` ne se borne a rien et refuse une structure ; les trois autres
        # se rattachent par defaut a celle de l'agent, qui est le cas courant.
        definir_perimetre(
            acteur,
            agent.pk,
            portee=portee,
            structure_id=(
                None if portee == PORTEE_TOUTES else (perimetre_structure_id or structure.pk)
            ),
        )

    return agent


def modifier_compte(
    acteur: Utilisateur,
    utilisateur_id: int,
    *,
    prenom: str | None = None,
    nom: str | None = None,
    courriel: str | None = None,
    telephone: str | None = None,
    structure_id: int | None = None,
    poste_id: int | None = None,
) -> Utilisateur:
    """
    Corrige l'etat civil d'un compte, ou l'affecte ailleurs.

    Seuls les champs fournis sont touches ; les autres restent. Le journal ne
    retient que ce qui a reellement change — enregistrer « modifie » sans dire
    quoi ne sert a personne.

    **Le changement de poste ne s'ecrit pas ici** : il passe par
    `organisation.services.affecter`, qui date l'occupation (F-04). Ecrire
    `agent.poste` directement, comme cette fonction le faisait, effacait
    l'occupant precedent sans laisser de trace — et la hierarchie du circuit se
    lit par le poste. Voir l'ADR 015,
    `backend/docs/architecture/015-l-affectation-a-un-poste-est-datee.md`.
    """
    agent = _agent_administrable(utilisateur_id)
    modifications: dict[str, object] = {}

    for champ, valeur in (
        ("prenom", prenom.strip() if prenom else None),
        ("nom", nom.strip() if nom else None),
        ("courriel", courriel),
        ("telephone", telephone),
    ):
        if valeur is None or getattr(agent, champ) == valeur:
            continue
        if champ == "courriel":
            _refuser_doublon(
                "courriel", valeur, "Cette adresse est deja rattachee a un compte", sauf=agent.pk
            )
        setattr(agent, champ, valeur)
        modifications[champ] = valeur

    #: Le poste a changer, s'il change. L'affectation est ecrite **apres** la
    #: sauvegarde de l'etat civil : `affecter()` ouvre sa propre transaction et
    #: relit l'agent, et poser le poste avant lui ferait clore une affectation
    #: pour une modification de courriel qui pourrait encore echouer.
    poste_a_pourvoir = None

    if structure_id is not None or poste_id is not None:
        structure, poste = _structure_et_poste(
            structure_id if structure_id is not None else agent.structure_id,
            poste_id if poste_id is not None else agent.poste_id,
        )
        if agent.structure_id != structure.pk:
            _refuser_affectation_qui_laisse_le_perimetre_derriere(agent, structure)
            modifications["structure"] = structure.pk
            agent.structure = structure
        if agent.poste_id != poste.pk:
            modifications["poste"] = poste.pk
            poste_a_pourvoir = poste

    if not modifications:
        return agent

    agent.modifie_le = timezone.now()
    agent.modifie_par = acteur.pk
    agent.save()

    if poste_a_pourvoir is not None:
        organisation.affecter(
            acteur,
            utilisateur_id=agent.pk,
            poste_id=poste_a_pourvoir.pk,
            motif="Mutation saisie depuis la fiche du compte.",
        )
        agent.refresh_from_db(fields=["poste", "structure"])

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="compte_modifie",
        libelle=f"Compte de {agent.nom_complet} modifie ({', '.join(sorted(modifications))})",
        acteur=acteur,
        donnees={"utilisateur": agent.pk, "modifications": modifications},
    )
    return agent


def changer_etat_compte(acteur: Utilisateur, utilisateur_id: int, *, actif: bool) -> Utilisateur:
    """
    Suspend un compte ou le retablit.

    Suspendre n'efface rien : le compte, ses profils, son perimetre et tout ce
    qu'il a signe restent en place. C'est la seule facon de fermer un acces sans
    trouer les pistes d'audit — d'ou l'absence de toute route de suppression.

    Les sessions ouvertes ne sont pas fermees ici. `SessionAuth` verifie
    `is_active` a chaque requete : le compte suspendu est refuse au prochain
    appel, sans qu'il faille aller fouiller la table des sessions.
    """
    agent = _agent_administrable(utilisateur_id)

    # Se suspendre soi-meme ferme la porte de l'exterieur, la clef a l'interieur.
    if agent.pk == acteur.pk and not actif:
        raise ErreurMetier(
            "Vous ne pouvez pas suspendre votre propre compte : vous ne pourriez plus "
            "le retablir. Faites-le faire par un autre administrateur.",
            code="suspension_de_soi",
        )

    if agent.actif == actif:
        return agent

    agent.actif = actif
    agent.modifie_le = timezone.now()
    agent.modifie_par = acteur.pk
    agent.save(update_fields=["actif", "modifie_le", "modifie_par"])

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="compte_retabli" if actif else "compte_suspendu",
        libelle=f"Compte de {agent.nom_complet} {'retabli' if actif else 'suspendu'}",
        acteur=acteur,
        donnees={"utilisateur": agent.pk, "actif": actif},
    )
    return agent


def _refuser_doublon(champ: str, valeur: str | None, message: str, *, sauf: int | None = None):
    """
    Les trois colonnes concernees sont UNIQUE en base. Sans ce controle, le
    doublon remonte en `IntegrityError`, donc en 500 : une saisie ordinaire
    passerait pour une panne du serveur.
    """
    if not valeur:
        return
    doublons = Utilisateur.objects.filter(**{champ: valeur})
    if sauf is not None:
        doublons = doublons.exclude(pk=sauf)
    if doublons.exists():
        raise ErreurMetier(f"{message} : « {valeur} ».", code="doublon")


def _structure_et_poste(structure_id: int | None, poste_id: int | None) -> tuple[Structure, Poste]:
    """
    Le poste doit relever de la structure. Un « Chef de service » de la DAF
    rattache a la DSI ne serait refuse par aucune contrainte, et fausserait
    silencieusement tout perimetre `structure`.
    """
    # Les deux peuvent arriver a None quand `modifier_compte` reprend la valeur
    # d'un compte qui n'en portait pas : c'est bien un « introuvable ».
    structure = (
        Structure.objects.filter(pk=structure_id, valide_au__isnull=True).first()
        if structure_id is not None
        else None
    )
    if structure is None:
        raise HorsPerimetre("Structure introuvable.")

    poste = (
        Poste.objects.filter(pk=poste_id, valide_au__isnull=True).first()
        if poste_id is not None
        else None
    )
    if poste is None:
        raise HorsPerimetre("Poste introuvable.")

    if poste.structure_id != structure.pk:
        raise ErreurMetier(
            f"Le poste « {poste.libelle} » releve de {poste.structure}, pas de {structure}.",
            code="poste_hors_structure",
        )
    return structure, poste


def _refuser_affectation_qui_laisse_le_perimetre_derriere(
    agent: Utilisateur, structure: Structure
) -> None:
    """
    Garde-fou technique, non une regle metier.

    Muter un agent sans toucher a son perimetre le laisse voir son ancien
    service et pas le nouveau. Rien ne le signale : les ecrans repondent, ils
    repondent simplement sur les mauvaises donnees. Plutot que de deplacer le
    perimetre d'office — ce qui reviendrait a decider d'un droit a la place de
    l'administrateur — on exige le geste explicite, dans l'ordre qu'il veut.
    """
    courant = Perimetre.objects.filter(utilisateur=agent, valide_au__isnull=True).first()
    if courant is None or courant.structure_id in (None, structure.pk):
        return
    raise ErreurMetier(
        f"Le perimetre de {agent.nom_complet} est borne sur {courant.structure} : l'affecter "
        f"a {structure} sans le redefinir lui laisserait la vue de son ancien service. "
        "Redefinissez son perimetre, puis reprenez cette affectation.",
        code="perimetre_a_redefinir",
    )


# =====================================================================
#  Profils
# =====================================================================


def creer_profil(
    acteur: Utilisateur,
    *,
    code: str,
    libelle: str,
    description: str | None = None,
    depuis_profil_id: int | None = None,
) -> Profil:
    """
    Cree un profil — G-02.

    **C'est la sortie que `basculer_permission` promet depuis le premier jour.**
    Son refus dit « creez un profil derive si vous devez en changer les droits »,
    et il n'y avait aucune route pour le faire : l'administrateur lisait une
    consigne qu'il ne pouvait pas suivre.

    `depuis_profil_id` copie les permissions d'un profil existant, y compris
    d'un profil systeme — c'est precisement l'usage vise. La copie est faite
    **une fois** : les deux profils divergent ensuite, et le derive ne suit pas
    les evolutions de son modele. Un heritage vivant aurait fait bouger les
    droits d'un profil sans que personne ne touche a ce profil.

    Le profil cree n'est **jamais** `systeme`. Le drapeau n'est pas un parametre
    de cette fonction, et ce n'est pas un oubli : il designe le referentiel
    livre, et un profil cree a l'ecran n'en fait pas partie, quoi qu'on veuille.
    """
    code = (code or "").strip().upper()
    if not code:
        raise ErreurMetier("Le code du profil est obligatoire.", code="code_profil_requis")
    if Profil.objects.filter(code=code).exists():
        raise ErreurMetier(
            f"Le code « {code} » designe deja un profil.",
            code="code_profil_pris",
        )

    modele = None
    if depuis_profil_id is not None:
        modele = Profil.objects.filter(pk=depuis_profil_id, invalide_le__isnull=True).first()
        if modele is None:
            raise ErreurMetier("Le profil a copier n'existe pas.", code="profil_modele_inconnu")

    with transaction.atomic():
        profil = Profil.objects.create(
            code=code,
            libelle=libelle.strip(),
            description=(description or None),
            systeme=False,
            cree_par=acteur.pk,
        )

        heritees: list[str] = []
        if modele is not None:
            ProfilPermission.objects.bulk_create(
                ProfilPermission(profil=profil, permission=permission)
                for permission in modele.permissions.all()
            )
            heritees = sorted(p.code for p in modele.permissions.all())

        inscrire(
            objet_type="profil",
            objet_id=profil.pk,
            type_evenement="profil_cree",
            libelle=f"Profil « {profil.libelle} » cree",
            acteur=acteur,
            detail=(f"Derive de « {modele.libelle} »." if modele else None),
            donnees={
                "code": code,
                "deriveDe": modele.code if modele else None,
                "permissions": heritees,
            },
        )

    return profil


def modifier_profil(
    acteur: Utilisateur,
    profil_id: int,
    *,
    libelle: str | None = None,
    description: str | None = None,
) -> Profil:
    """
    Corrige le libelle ou la description d'un profil.

    **Le code ne se modifie pas.** Il est la clef par laquelle le semis, les
    tests et les migrations designent un profil ; le renommer casserait ces
    references sans qu'aucune erreur ne se produise avant le prochain semis.

    Les permissions ne se touchent pas ici non plus : elles ont leur route
    (`PATCH /profils/{id}/permissions`), qui inscrit un evenement par droit
    accorde ou retire. Un formulaire qui les enverrait en bloc rendrait
    illisible la question « qui a donne ce droit, et quand ».
    """
    profil = _profil_vivant(profil_id)

    ecarts: dict[str, object] = {}
    if libelle is not None and libelle.strip() != profil.libelle:
        profil.libelle = libelle.strip()
        ecarts["libelle"] = profil.libelle
    if description is not None and (description or None) != profil.description:
        profil.description = description or None
        ecarts["description"] = profil.description

    if not ecarts:
        return profil

    with transaction.atomic():
        profil.modifie_le = timezone.now()
        profil.modifie_par = acteur.pk
        profil.save()
        inscrire(
            objet_type="profil",
            objet_id=profil.pk,
            type_evenement="profil_modifie",
            libelle=f"Profil « {profil.libelle} » modifie ({', '.join(sorted(ecarts))})",
            acteur=acteur,
            donnees={"code": profil.code, **ecarts},
        )

    return profil


def invalider_profil(acteur: Utilisateur, profil_id: int, *, motif: str) -> Profil:
    """
    Retire un profil du catalogue. **La ligne n'est pas effacee.**

    Un profil porte est refuse : invalider un profil que des agents detiennent
    leur oterait tous leurs droits d'un coup, sans qu'aucun d'eux ne soit
    prevenu ni qu'aucune erreur ne se produise. Ils se connecteraient a une
    application vide et chercheraient la panne ailleurs — c'est la regle 3 du
    perimetre, appliquee aux droits.
    """
    profil = _profil_retirable(profil_id)

    porteurs = UtilisateurProfil.objects.filter(profil=profil, retire_le__isnull=True).count()
    if porteurs:
        raise ErreurMetier(
            f"{porteurs} agent(s) portent « {profil.libelle} ». "
            "Retirez-leur le profil avant de le sortir du catalogue.",
            code="profil_porte",
        )

    with transaction.atomic():
        profil.invalide_le = timezone.now()
        profil.invalide_par = acteur.pk
        profil.save(update_fields=["invalide_le", "invalide_par"])
        inscrire(
            objet_type="profil",
            objet_id=profil.pk,
            type_evenement="profil_invalide",
            libelle=f"Profil « {profil.libelle} » retire du catalogue",
            acteur=acteur,
            detail=motif,
            donnees={"code": profil.code},
        )

    return profil


def _profil_vivant(profil_id: int) -> Profil:
    """
    Le profil, s'il existe et n'a pas ete retire du catalogue.

    **Ne refuse plus les profils systeme.** Jusqu'au 28 aout 2026 c'etait le cas,
    et la consequence tenait en une phrase de l'utilisateur : « deverrouille les
    profils, je dois pouvoir modifier les habilitations ». Le referentiel livre
    decrit l'organisation telle qu'on l'a comprise ; celui qui administre le Port
    la connait mieux. Voir l'ADR 041.
    """
    profil = Profil.objects.filter(pk=profil_id, invalide_le__isnull=True).first()
    if profil is None:
        raise HorsPerimetre("Profil introuvable.")
    return profil


def _profil_retirable(profil_id: int) -> Profil:
    """
    Le profil, s'il peut sortir du catalogue.

    **Le seul verrou qui reste sur les profils systeme.** Modifier les droits d'un
    profil livre est reversible d'un clic ; le sortir du catalogue ne l'est pas :
    le semis, les migrations et les tests le citent par son code, et rien
    n'echouerait avant le deploiement suivant.
    """
    profil = _profil_vivant(profil_id)
    if profil.systeme:
        raise ErreurMetier(
            f"Le profil « {profil.libelle} » fait partie du referentiel livre et ne peut "
            "pas etre retire du catalogue. Ses droits, eux, se modifient case par case.",
            code="profil_systeme",
        )
    return profil


def _refuser_la_derniere_clef(profil: Profil) -> None:
    """
    Empeche de retirer `ADM_HAB` du dernier profil vivant qui la porte.

    Le compte se fait sur les profils et non sur les agents : un profil qui porte
    le droit mais que personne ne detient reste une clef — il suffit de
    l'attribuer. Compter les porteurs aurait bloque des situations parfaitement
    rattrapables.

    Les delegations n'entrent pas dans le compte : elles s'eteignent a une date,
    et une clef qui expire n'en est pas une.
    """
    autres = (
        ProfilPermission.objects.filter(permission__code=PERM.ADM_HAB)
        .exclude(profil=profil)
        .filter(profil__invalide_le__isnull=True)
        .exists()
    )
    if not autres:
        raise ErreurMetier(
            f"« {profil.libelle} » est le dernier profil a porter le droit d'administrer "
            "les habilitations. Le lui retirer fermerait l'administration a tout le monde. "
            "Accordez d'abord ce droit a un autre profil.",
            code="derniere_clef_administration",
        )


def basculer_permission(acteur: Utilisateur, profil_id: int, code: str, accordee: bool) -> None:
    """
    Accorde ou retire une permission a un profil, **y compris systeme**.

    Le referentiel livre decrit l'organisation telle que le descriptif l'a dite ;
    l'administrateur du Port la connait mieux, et le lui refuser ne protegeait
    rien — il pouvait deja creer un profil derive, l'attribuer et retirer
    l'ancien. Le verrou n'ajoutait donc que des gestes. ADR 041.

    **Une seule serrure demeure, et elle n'est pas une opinion** : on ne retire
    pas `ADM_HAB` du dernier profil qui la porte. Ce geste-la ferme
    l'administration a tout le monde, y compris a celui qui vient de le faire, et
    aucun ecran ne permet de revenir en arriere — il faudrait un `INSERT` en base.
    Tout le reste se reprend d'un clic.
    """
    profil = _profil_vivant(profil_id)

    permission = Permission.objects.filter(code=code).first()
    if permission is None:
        raise ErreurMetier(f"Permission « {code} » inconnue.", code="permission_inconnue")

    if not accordee and code == PERM.ADM_HAB:
        _refuser_la_derniere_clef(profil)

    if accordee:
        _, cree = ProfilPermission.objects.get_or_create(profil=profil, permission=permission)
        if not cree:
            return
    else:
        supprimees, _ = ProfilPermission.objects.filter(
            profil=profil, permission=permission
        ).delete()
        if not supprimees:
            return

    inscrire(
        objet_type="profil",
        objet_id=profil.pk,
        type_evenement="permission_accordee" if accordee else "permission_retiree",
        libelle=(
            f"Permission {code} {'accordee a' if accordee else 'retiree de'} « {profil.libelle} »"
        ),
        acteur=acteur,
        donnees={"profil": profil.code, "permission": code, "accordee": accordee},
    )


def attribuer_profil(acteur: Utilisateur, utilisateur_id: int, profil_id: int) -> None:
    """
    Donne un profil a un agent.

    Un agent peut en porter plusieurs — la table `utilisateur_profil` le
    permet, et la route `/utilisateurs` joint deja les libelles. Attribuer
    n'ecrase donc rien : cela ajoute.

    Idempotent : reattribuer un profil deja porte ne cree ni doublon ni
    evenement. Un journal qui enregistre des non-evenements devient illisible,
    et c'est un journal illisible qu'on cesse de consulter.
    """
    agent = _agent_administrable(utilisateur_id)
    profil = Profil.objects.filter(pk=profil_id, invalide_le__isnull=True).first()
    if profil is None:
        raise HorsPerimetre("Profil introuvable.")

    _, cree = UtilisateurProfil.objects.get_or_create(
        utilisateur=agent,
        profil=profil,
        retire_le__isnull=True,
        defaults={"attribue_par": acteur.pk},
    )
    if not cree:
        return

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="profil_attribue",
        libelle=f"Profil « {profil.libelle} » attribue a {agent.nom_complet}",
        acteur=acteur,
        donnees={"profil": profil.code, "utilisateur": agent.pk},
    )


def retirer_profil(acteur: Utilisateur, utilisateur_id: int, profil_id: int) -> None:
    """
    Retire un profil a un agent.

    Le rattachement n'est pas supprime mais date (`retire_le`) : savoir qu'un
    agent a porte tel profil entre deux dates est precisement ce qu'un audit
    demande. Une piste qu'on peut effacer ne prouve rien.
    """
    agent = _agent_administrable(utilisateur_id)
    attribution = UtilisateurProfil.objects.filter(
        utilisateur=agent, profil_id=profil_id, retire_le__isnull=True
    ).first()
    if attribution is None:
        raise HorsPerimetre("Ce profil n'est pas attribue a cet agent.")

    _refuser_de_se_desadministrer(acteur, agent, attribution.profil)

    attribution.retire_le = timezone.now()
    attribution.retire_par = acteur.pk
    attribution.save(update_fields=["retire_le", "retire_par"])

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="profil_retire",
        libelle=f"Profil « {attribution.profil.libelle} » retire a {agent.nom_complet}",
        acteur=acteur,
        donnees={"profil": attribution.profil.code, "utilisateur": agent.pk},
    )


def _refuser_de_se_desadministrer(acteur: Utilisateur, agent: Utilisateur, profil: Profil) -> None:
    """
    Personne ne se retire a soi-meme son dernier acces d'administration.

    Ce n'est pas une regle metier — aucun document ne la porte — mais un
    garde-fou technique : l'administration des habilitations n'est accessible
    que par elle-meme. Qui s'en exclut ne peut plus s'y readmettre, et il faut
    alors une intervention en base.
    """
    if agent.pk != acteur.pk:
        return
    if "ADM_HAB" not in set(profil.permissions.values_list("code", flat=True)):
        return

    restants = UtilisateurProfil.objects.filter(
        utilisateur=agent, retire_le__isnull=True, profil__permissions__code="ADM_HAB"
    ).exclude(profil_id=profil.pk)
    if not restants.exists():
        raise ErreurMetier(
            "Ce retrait vous oterait votre dernier acces a l'administration des "
            "habilitations, et personne ne pourrait vous le rendre. Faites-le faire "
            "par un autre administrateur.",
            code="desadministration_de_soi",
        )


def _agent_administrable(utilisateur_id: int) -> Utilisateur:
    """
    404 et non 403 pour un compte inexistant ou invalide — decision D5 : un 403
    confirmerait l'existence de ce qu'on n'a pas le droit de voir.
    """
    agent = Utilisateur.objects.filter(pk=utilisateur_id, invalide_le__isnull=True).first()
    if agent is None:
        raise HorsPerimetre("Agent introuvable.")
    return agent


# =====================================================================
#  Perimetres
# =====================================================================
#
#  Le « catalogue de perimetres » des ecrans n'est pas une table : c'est le
#  referentiel ferme des quatre portees, presente avec un libelle. La preuve
#  est dans le front lui-meme — `demo/comptes.ts` porte pour chaque compte
#  `perimetre: { portee, structureId }`, soit exactement la table `perimetre`.
#  Les quatre entrees de l'ecran d'administration sont ces quatre portees.
#
#  L'identifiant ci-dessous est donc un identifiant de REFERENTIEL, stable et
#  numerote une fois pour toutes, et non une clef de ligne. Le front le declare
#  `number` ; c'est ce qui impose qu'il en soit un.
# ---------------------------------------------------------------------
CATALOGUE_PORTEES: list[tuple[int, str, str, str]] = [
    (4, PORTEE_TOUTES, "Institution", "Institution"),
    (3, PORTEE_SOUS_ARBRE, "Structure et descendantes", "Structure de rattachement"),
    (2, PORTEE_STRUCTURE, "Structure seule", "Structure de rattachement"),
    (1, PORTEE_PROPRE, "Poste", "Poste de travail"),
]

#: Les options que l'ecran affiche sur une carte de perimetre ne sont pas des
#: proprietes du perimetre : ce sont des permissions. On les rapporte donc aux
#: agents concernes — vrai si TOUS portent la permission —, ce qui decrit sans
#: rien inventer.
#:
#: `lectureClotures` n'y figure pas : aucune permission ne correspond. `CLO`
#: est « cloturer un courrier », un geste, pas une lecture. Le champ est renvoye
#: a faux et la question reste ouverte — voir docs/questions-ouvertes.md, A14.
OPTIONS_PERIMETRE: dict[str, str] = {
    "voirConfidentiel": "CONF",
    "statistiquesAgregees": "STAT",
}


def catalogue_perimetres() -> list[dict]:
    """Les quatre portees, avec le nombre d'agents et les options constatees."""
    etendues = dict(Perimetre.PORTEES)
    lignes = []

    for identifiant, portee, libelle, assise in CATALOGUE_PORTEES:
        agents = set(
            Perimetre.objects.filter(valide_au__isnull=True, portee=portee).values_list(
                "utilisateur_id", flat=True
            )
        )
        ligne = {
            "id": identifiant,
            "libelle": libelle,
            "assise": assise,
            "etendue": etendues[portee],
            "nombreAgents": len(agents),
            "inclureDescendants": portee in (PORTEE_SOUS_ARBRE, PORTEE_TOUTES),
            "lectureClotures": False,
        }
        for champ, code in OPTIONS_PERIMETRE.items():
            ligne[champ] = _tous_portent(agents, code)
        lignes.append(ligne)

    return lignes


def _tous_portent(agents: set[int], code: str) -> bool:
    if not agents:
        return False
    porteurs = set(
        UtilisateurProfil.objects.filter(
            utilisateur_id__in=agents, retire_le__isnull=True, profil__permissions__code=code
        ).values_list("utilisateur_id", flat=True)
    )
    return agents <= porteurs


def definir_perimetre(
    acteur: Utilisateur, utilisateur_id: int, *, portee: str, structure_id: int | None
) -> None:
    """
    Pose la portee d'un agent.

    L'ancien perimetre n'est pas modifie : il est **clos** (`valide_au`) et un
    nouveau est ouvert. Le perimetre est une donnee datee — savoir ce qu'un
    agent avait le droit de voir le mois dernier fait partie de ce que l'audit
    demande, et une mise a jour sur place l'effacerait.

    Un agent **sans perimetre ne voit rien** (regle 3 de
    `noyau/perimetre/portee.py`). Cette route ne peut donc pas en retirer un
    sans en poser un autre : il n'y a pas de « portee vide ».
    """
    if portee not in dict(Perimetre.PORTEES):
        raise ErreurMetier(f"Portee « {portee} » inconnue.", code="portee_inconnue")

    agent = _agent_administrable(utilisateur_id)
    structure = _structure_de_portee(portee, structure_id)

    courant = Perimetre.objects.filter(utilisateur=agent, valide_au__isnull=True).first()
    if courant is not None:
        if courant.portee == portee and courant.structure_id == (
            structure.pk if structure else None
        ):
            return
        courant.valide_au = date.today()
        courant.save(update_fields=["valide_au"])

    Perimetre.objects.create(
        utilisateur=agent,
        portee=portee,
        structure=structure,
        valide_du=date.today(),
        cree_par=acteur.pk,
    )

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="perimetre_defini",
        libelle=(
            f"Perimetre de {agent.nom_complet} porte a « {dict(Perimetre.PORTEES)[portee]} »"
            + (f" — {structure}" if structure else "")
        ),
        acteur=acteur,
        donnees={
            "utilisateur": agent.pk,
            "portee": portee,
            "structure": structure.pk if structure else None,
        },
    )


def _structure_de_portee(portee: str, structure_id: int | None) -> Structure | None:
    """
    `toutes` ne borne rien et ne porte donc pas de structure ; les trois autres
    n'ont aucun sens sans elle. Accepter l'un ou l'autre en silence produirait
    un perimetre qui ne filtre pas — la panne la plus discrete de tout le
    projet.
    """
    if portee == PORTEE_TOUTES:
        if structure_id is not None:
            raise ErreurMetier(
                "La portee « toute l'institution » ne se rattache a aucune structure.",
                code="structure_superflue",
            )
        return None

    if structure_id is None:
        raise ErreurMetier(
            "Cette portee s'appuie sur une structure : precisez laquelle.",
            code="structure_requise",
        )

    structure = Structure.objects.filter(pk=structure_id, valide_au__isnull=True).first()
    if structure is None:
        raise HorsPerimetre("Structure introuvable.")
    return structure


# =====================================================================
#  Sessions courrier
# =====================================================================


def rattacher_session(acteur: Utilisateur, session_id: int, utilisateur_id: int) -> None:
    """
    Rattache un agent a une session d'enregistrement.

    Le rattachement est **exclusif** : un agent n'appartient qu'a une session.
    Le controle ci-dessous ne remplace pas la contrainte d'exclusion GiST — qui
    seule tient face a deux ecritures concurrentes — il sert a rendre le refus
    intelligible plutot que de laisser remonter une violation de contrainte.
    """
    agent = _agent_administrable(utilisateur_id)
    session = SessionCourrier.objects.filter(
        pk=session_id, invalide_le__isnull=True, actif=True
    ).first()
    if session is None:
        raise HorsPerimetre("Session introuvable.")

    ouvert = (
        UtilisateurSession.objects.filter(utilisateur=agent, retire_le__isnull=True)
        .select_related("session")
        .first()
    )
    if ouvert is not None:
        if ouvert.session_id == session.pk:
            return
        raise ErreurMetier(
            f"{agent.nom_complet} est deja rattache a la session "
            f"« {ouvert.session.libelle} ». Detachez-l'en d'abord.",
            code="session_deja_attribuee",
        )

    UtilisateurSession.objects.create(utilisateur=agent, session=session, attribue_par=acteur.pk)

    inscrire(
        objet_type="utilisateur",
        objet_id=agent.pk,
        type_evenement="session_rattachee",
        libelle=f"{agent.nom_complet} rattache a « {session.libelle} »",
        acteur=acteur,
        donnees={"utilisateur": agent.pk, "session": session.code},
    )


def detacher_session(acteur: Utilisateur, session_id: int, utilisateur_id: int) -> None:
    """Clot le rattachement, sans l'effacer : il reste au registre."""
    rattachement = (
        UtilisateurSession.objects.filter(
            session_id=session_id, utilisateur_id=utilisateur_id, retire_le__isnull=True
        )
        .select_related("session", "utilisateur")
        .first()
    )
    if rattachement is None:
        raise HorsPerimetre("Rattachement introuvable.")

    rattachement.retire_le = timezone.now()
    rattachement.retire_par = acteur.pk
    rattachement.save(update_fields=["retire_le", "retire_par"])

    inscrire(
        objet_type="utilisateur",
        objet_id=rattachement.utilisateur_id,
        type_evenement="session_detachee",
        libelle=(
            f"{rattachement.utilisateur.nom_complet} detache de « {rattachement.session.libelle} »"
        ),
        acteur=acteur,
        donnees={
            "utilisateur": rattachement.utilisateur_id,
            "session": rattachement.session.code,
        },
    )


# =====================================================================
#  Delegations
# =====================================================================


def etat_delegation(delegation: Delegation) -> str:
    """
    « active », « programmee » ou « close ».

    Deduit, jamais stocke : une colonne d'etat serait fausse le lendemain de
    son ecriture, sans qu'aucune ecriture ne survienne.
    """
    maintenant = timezone.now()
    if delegation.invalide_le is not None or delegation.fin < maintenant:
        return "close"
    if delegation.debut > maintenant:
        return "programmee"
    return "active"


def etendue_de(delegation: Delegation) -> str:
    """
    Retrouve le nom de l'etendue depuis les permissions enumerees.

    L'etendue n'est pas stockee : ce sont les permissions qui font foi. Si
    aucun regroupement ne correspond exactement — parce que la liste
    `ETENDUES` a change depuis —, on montre les codes plutot que de mentir
    sur ce qui a ete delegue.
    """
    codes = set(delegation.permissions.values_list("code", flat=True))
    for nom, attendus in ETENDUES.items():
        if codes == set(attendus):
            return nom
    return ", ".join(sorted(codes)) or "(aucune)"


def etendues_delegables(utilisateur: Utilisateur) -> list[str]:
    """
    Les etendues que cet utilisateur peut deleguer.

    Une etendue n'est proposee que si le titulaire porte **toutes** les
    permissions qu'elle recouvre. En proposer une qu'il ne detient qu'a moitie
    produirait une delegation amputee, et personne ne comprendrait pourquoi.
    """
    detenues = permissions_de(utilisateur)
    return [nom for nom, codes in ETENDUES.items() if set(codes) <= detenues]


def delegataires_possibles(utilisateur: Utilisateur) -> list[Utilisateur]:
    """
    A qui l'on peut deleguer : les agents actifs, soi-meme excepte.

    Se deleguer a soi-meme n'ajouterait rien et brouillerait le journal, qui
    porterait « agit pour » sur la personne qui agit deja.
    """
    return list(
        Utilisateur.objects.actifs()
        .exclude(pk=utilisateur.pk)
        .select_related("poste")
        .order_by("nom", "prenom")
    )


def declarer_delegation(
    acteur: Utilisateur,
    *,
    delegataire_id: int,
    etendue: str,
    debut: date,
    fin: date,
    motif: str,
) -> Delegation:
    """Pose une delegation au nom de l'acteur, qui en est le titulaire."""
    if etendue not in ETENDUES:
        raise ErreurMetier(f"Etendue « {etendue} » inconnue.", code="etendue_inconnue")

    if fin < debut:
        raise ErreurMetier("La fin de la delegation precede son debut.", code="periode_invalide")

    codes = set(ETENDUES[etendue])
    if not codes <= permissions_de(acteur):
        # Sans ce controle, la delegation devient une escalade de privileges :
        # il suffirait de se deleguer ce qu'on n'a pas.
        raise ErreurMetier(
            f"Vous ne portez pas tous les droits que « {etendue} » recouvre : "
            "on ne delegue que ce que l'on possede.",
            code="delegation_hors_droits",
        )

    beneficiaire = Utilisateur.objects.actifs().filter(pk=delegataire_id).first()
    if beneficiaire is None:
        raise HorsPerimetre("Agent introuvable.")
    if beneficiaire.pk == acteur.pk:
        raise ErreurMetier("Se deleguer a soi-meme n'a pas de sens.", code="delegataire_invalide")

    # Les bornes couvrent les journees entieres : une delegation « du 1er au
    # 10 » vaut jusqu'a la fin du 10, pas jusqu'a son premier instant.
    debut_h = timezone.make_aware(datetime.combine(debut, time.min))
    fin_h = timezone.make_aware(datetime.combine(fin, time.max))

    _refuser_chevauchement(acteur, beneficiaire, debut_h, fin_h, codes)

    delegation = Delegation.objects.create(
        nature="delegation",
        titulaire=acteur,
        beneficiaire=beneficiaire,
        debut=debut_h,
        fin=fin_h,
        motif=motif,
        cree_par=acteur.pk,
    )
    for permission in Permission.objects.filter(code__in=codes):
        DelegationPermission.objects.create(delegation=delegation, permission=permission)

    inscrire(
        objet_type="delegation",
        objet_id=delegation.pk,
        type_evenement="delegation_posee",
        libelle=f"{etendue} deleguee a {beneficiaire.nom_complet} jusqu'au {fin:%d/%m/%Y}",
        detail=motif,
        acteur=acteur,
        donnees={"etendue": etendue, "beneficiaire": beneficiaire.pk, "permissions": sorted(codes)},
    )
    return delegation


def _refuser_chevauchement(
    titulaire: Utilisateur,
    beneficiaire: Utilisateur,
    debut,
    fin,
    codes: set[str],
) -> None:
    """
    Deux delegations concurrentes sur les memes droits rendraient la levee
    ambigue : retirer l'une laisserait l'autre en place sans que personne ne
    s'en apercoive.
    """
    concurrentes = Delegation.objects.filter(
        titulaire=titulaire,
        beneficiaire=beneficiaire,
        invalide_le__isnull=True,
        debut__lte=fin,
        fin__gte=debut,
    ).filter(permissions__code__in=codes)

    if concurrentes.exists():
        raise ErreurMetier(
            f"Une delegation couvrant deja ces droits est en cours pour "
            f"{beneficiaire.nom_complet} sur cette periode.",
            code="delegation_en_double",
        )


def interrompre_delegation(acteur: Utilisateur, delegation_id: int) -> None:
    """
    Clot une delegation avant son terme.

    Indispensable, et non un confort : une absence ecourtee laisserait sinon un
    agent signer au nom d'un autre revenu a son poste.

    La delegation n'est pas effacee — elle est invalidee, et reste au registre.
    Une piste d'audit qu'on peut effacer ne prouve rien.
    """
    delegation = (
        Delegation.objects.filter(pk=delegation_id, invalide_le__isnull=True)
        .select_related("beneficiaire")
        .first()
    )
    if delegation is None:
        raise HorsPerimetre("Delegation introuvable.")

    # Le titulaire retire les siennes sans demander a quiconque (§3.4) ;
    # l'administrateur des habilitations retire n'importe laquelle.
    if delegation.titulaire_id != acteur.pk and "ADM_HAB" not in permissions_de(acteur):
        raise HorsPerimetre("Delegation introuvable.")

    delegation.invalide_le = timezone.now()
    delegation.invalide_par = acteur.pk
    delegation.save(update_fields=["invalide_le", "invalide_par"])

    inscrire(
        objet_type="delegation",
        objet_id=delegation.pk,
        type_evenement="delegation_interrompue",
        libelle=f"Delegation a {delegation.beneficiaire.nom_complet} interrompue",
        acteur=acteur,
        donnees={"beneficiaire": delegation.beneficiaire_id},
    )


def delegations_visibles(utilisateur: Utilisateur, *, siennes: bool) -> list[Delegation]:
    """
    `siennes` distingue les deux ecrans : le responsable voit celles qu'il a
    posees (§3.4), l'administrateur voit l'ensemble. Le second n'est pas une
    version elargie du premier — ce sont deux besoins differents, et le
    responsable n'a pas a voir celles des autres.
    """
    requete = Delegation.objects.select_related("titulaire", "beneficiaire__poste")
    if siennes:
        requete = requete.filter(Q(titulaire=utilisateur), invalide_le__isnull=True)
    return list(requete.order_by("-debut"))
