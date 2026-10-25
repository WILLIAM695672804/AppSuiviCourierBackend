"""
Ecritures du portail usagers.

Trois gestes de l'usager — deposer, repondre, regler ses notifications — et les
refus qui les encadrent. Les refus comptent ici plus qu'ailleurs : ce sont les
seules routes du depot qu'un tiers exterieur a l'institution peut atteindre.

**Ce que le portail refuse.**

 * Ecrire sur une demande qui n'est pas la sienne — 404, jamais 403 (D5).
 * Repondre a une demande close : le dossier est termine, et un message qui
   s'y perdrait ferait croire a l'usager qu'il a agi.
 * Couper une notification obligatoire. La demande de complement et la decision
   rendue ouvrent l'une un delai de forclusion, l'autre un delai de recours.
   L'ecran grise les deux cases ; le serveur, lui, refuse.
 * Choisir le canal SMS sans numero de telephone. Basculer silencieusement sur
   le courriel aurait laisse l'usager croire qu'il est prevenu par SMS.

Chaque ecriture inscrit un evenement au journal du noyau. Un depot d'usager fait
courir un delai dont l'institution repond : « quand est-ce arrive, et qu'a-t-on
promis » est la premiere question posee le jour ou le delai est conteste.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.notifications import services as notifications
from portail.lecture import delai_reponse_jours, demandes_de
from portail.modeles import (
    CANAL_SMS,
    CANAUX,
    TYPES_DEMANDE,
    ComplementDemande,
    DemandeUsager,
    EvenementNotifiable,
    MessagePortail,
    PieceDemande,
    PreferenceEvenement,
    PreferenceNotification,
)

#: Longueurs minimales du formulaire de depot. Elles doublent celles du front,
#: et c'est voulu : une validation qui ne vit que dans le navigateur n'en est
#: pas une. Les valeurs sont les memes des deux cotes — si elles divergent, le
#: serveur a raison.
OBJET_MINIMUM = 10
CONTEXTE_MINIMUM = 30
#: Un message vide n'apporte rien au dossier ; « ok » non plus.
MESSAGE_MINIMUM = 5


def deposer_demande(
    acteur: Utilisateur,
    *,
    type_demande: str,
    objet: str,
    contexte: str,
    pieces: list[dict] | None = None,
) -> DemandeUsager:
    """
    Depose une demande — §3.13, premier point.

    **La date de reponse est calculee au depot et figee.** Elle est ce que
    l'institution a promis ce jour-la ; un delai raccourci le mois suivant ne
    doit pas mettre en retard, retroactivement, des demandes deja deposees, et
    un delai rallonge ne doit pas effacer un retard constitue.

    Le service instructeur n'est **pas** devine. Le type oriente vers un metier,
    pas vers une structure : sans regle d'affectation ecrite pour les demandes
    du portail, choisir une direction reviendrait a inventer. L'usager lit « en
    cours d'orientation », ce qui est la verite. Voir A44.
    """
    if type_demande not in {code for code, _ in TYPES_DEMANDE}:
        raise ErreurMetier(
            f"« {type_demande} » n'est pas un type de demande proposé.",
            code="type_inconnu",
        )
    if len(objet.strip()) < OBJET_MINIMUM:
        raise ErreurMetier(
            "L'objet doit dire ce que vous demandez — dix caractères au moins.",
            code="objet_trop_court",
        )
    if len(contexte.strip()) < CONTEXTE_MINIMUM:
        raise ErreurMetier(
            "Décrivez votre demande en quelques mots — trente caractères au moins.",
            code="contexte_trop_court",
        )

    aujourd_hui = date.today()
    promesse = aujourd_hui + timedelta(days=delai_reponse_jours())

    with transaction.atomic():
        demande = DemandeUsager.objects.create(
            reference=_reference_libre(aujourd_hui),
            type=type_demande,
            objet=objet.strip(),
            contexte=contexte.strip(),
            deposant=acteur,
            deposee_le=aujourd_hui,
            reponse_attendue_le=promesse,
            cree_par=acteur.pk,
        )
        for piece in pieces or []:
            _joindre(demande, piece, acteur, aujourd_hui, message=None)

        inscrire(
            objet_type="demande_usager",
            objet_id=demande.pk,
            type_evenement="demande_deposee",
            libelle=f"Demande {demande.reference} déposée — {demande.objet}",
            acteur=acteur,
            detail=(
                f"Type {demande.type}. Réponse promise pour le "
                f"{promesse.isoformat()} ({delai_reponse_jours()} jours)."
            ),
            donnees={
                "reference": demande.reference,
                "type": demande.type,
                "reponseAttendueLe": promesse.isoformat(),
            },
        )

        # L'accuse de reception — evenement `depot` du referentiel. C'est la
        # seule notification qu'un usager s'adresse a lui-meme, et elle est
        # legitime : elle ne lui apprend pas ce qu'il vient de faire, elle lui
        # confirme que l'institution l'a recu, avec la date promise. Sans elle,
        # le depot n'a pour trace qu'un ecran qu'il aura ferme.
        notifications.notifier(
            acteur,
            type_notification="depot",
            libelle=f"Demande {demande.reference} enregistrée",
            detail=(
                f"« {demande.objet} ». Réponse promise pour le {promesse.strftime('%d/%m/%Y')}."
            ),
            objet_type="demande_usager",
            objet_id=demande.pk,
            lien=f"/portail/demandes/{demande.pk}",
            acteur=acteur,
            accuse_de_reception=True,
        )
    return demande


def repondre(
    acteur: Utilisateur,
    *,
    demande_id: int,
    texte: str,
    pieces: list[dict] | None = None,
) -> MessagePortail:
    """
    Depose un message sur une demande, avec ses pieces eventuelles.

    C'est le formulaire place **en haut** de l'ecran de suivi : ce qu'on attend
    de l'usager passe avant ce qu'on lui raconte. Le message qui accompagne une
    piece reclamee **satisfait** le complement — sans quoi l'usager aurait
    depose sa piece et continue de lire « pièce attendue », ce qui l'aurait fait
    deposer deux fois.
    """
    if len(texte.strip()) < MESSAGE_MINIMUM:
        raise ErreurMetier(
            "Écrivez quelques mots : un message vide n'apporte rien à votre dossier.",
            code="message_vide",
        )

    demande = demandes_de(acteur).filter(pk=demande_id).first()
    if demande is None:
        raise HorsPerimetre("Cette demande n'existe pas ou ne vous appartient pas.")

    if demande.clos_le is not None:
        raise ErreurMetier(
            "Cette demande est close : votre message ne serait lu par personne. "
            "Déposez une nouvelle demande en rappelant la référence "
            f"{demande.reference}.",
            code="demande_close",
        )

    aujourd_hui = date.today()

    with transaction.atomic():
        message = MessagePortail.objects.create(
            demande=demande,
            auteur=acteur,
            texte=texte.strip(),
        )
        for piece in pieces or []:
            _joindre(demande, piece, acteur, aujourd_hui, message=message)

        satisfait = _satisfaire_complement(demande, aujourd_hui, avec_piece=bool(pieces))

        inscrire(
            objet_type="demande_usager",
            objet_id=demande.pk,
            type_evenement="message_usager",
            libelle=f"Message de l'usager — {demande.reference}",
            acteur=acteur,
            detail=(
                f"{len(pieces or [])} pièce(s) jointe(s)."
                + (f" Complément « {satisfait.objet} » satisfait." if satisfait else "")
            ),
            donnees={
                "reference": demande.reference,
                "pieces": len(pieces or []),
                "complementSatisfait": satisfait.objet if satisfait else None,
            },
        )
    return message


def _satisfaire_complement(
    demande: DemandeUsager, jour: date, *, avec_piece: bool
) -> ComplementDemande | None:
    """
    Marque satisfait le complement en attente, si une piece accompagne le
    message.

    **Une piece est exigee.** Un message seul ne satisfait pas une reclamation
    de piece : « je vous l'envoie demain » n'est pas la piece, et fermer
    l'attente sur cette phrase aurait fait passer le dossier pour complet aupres
    du service instructeur.
    """
    if not avec_piece:
        return None

    complement = (
        ComplementDemande.objects.filter(demande=demande, satisfait_le__isnull=True)
        .order_by("demande_le")
        .first()
    )
    if complement is None:
        return None

    complement.satisfait_le = jour
    complement.save(update_fields=["satisfait_le"])
    return complement


def enregistrer_preferences(
    acteur: Utilisateur,
    *,
    courriel: str,
    telephone: str | None,
    canal: str,
    evenements: list[str],
) -> PreferenceNotification:
    """
    Enregistre le canal et les evenements retenus — RF-SUI-03.

    `evenements` porte les cles **retenues**. Celles qui n'y figurent pas sont
    coupees, sauf les obligatoires : le serveur les rallume sans le dire au
    client, parce qu'il n'y a rien a negocier.
    """
    if canal not in {code for code, _ in CANAUX}:
        raise ErreurMetier(f"« {canal} » n'est pas un canal de notification.", code="canal_inconnu")

    adresse = courriel.strip()
    if "@" not in adresse:
        raise ErreurMetier(
            "Indiquez une adresse de courriel valide : c'est elle qui reçoit "
            "l'accusé de réception de vos dépôts.",
            code="courriel_invalide",
        )

    numero = (telephone or "").strip() or None
    if canal == CANAL_SMS and numero is None:
        raise ErreurMetier(
            "Le canal SMS demande un numéro de téléphone. Sans numéro, vous ne "
            "recevriez rien du tout.",
            code="sms_sans_numero",
        )

    retenues = set(evenements)

    with transaction.atomic():
        reglage, _ = PreferenceNotification.objects.get_or_create(
            utilisateur=acteur,
            defaults={"courriel": adresse, "telephone": numero, "canal": canal},
        )
        reglage.courriel = adresse
        reglage.telephone = numero
        reglage.canal = canal
        reglage.modifie_le = timezone.now()
        reglage.save(update_fields=["courriel", "telephone", "canal", "modifie_le"])

        coupees = []
        for evenement in EvenementNotifiable.objects.filter(actif=True):
            actif = True if evenement.obligatoire else evenement.cle in retenues
            PreferenceEvenement.objects.update_or_create(
                preference=reglage,
                evenement=evenement,
                defaults={"actif": actif},
            )
            if not actif:
                coupees.append(evenement.cle)

        inscrire(
            objet_type="preference_notification",
            objet_id=reglage.pk,
            type_evenement="preferences_enregistrees",
            libelle=f"Préférences de notification — canal {canal}",
            acteur=acteur,
            detail=(
                f"Coupé : {', '.join(coupees)}." if coupees else "Tous les événements sont actifs."
            ),
            donnees={"canal": canal, "coupees": coupees},
        )
    return reglage


# =====================================================================
#  Ecritures de l'institution, appelees par les autres piliers
# =====================================================================


def reclamer_complement(
    acteur: Utilisateur,
    *,
    demande_id: int,
    objet: str,
    avant_le: date,
) -> ComplementDemande:
    """
    Reclame une piece a l'usager.

    Ce geste n'est pas expose au portail : il vient de l'institution. Il vit ici
    parce que la regle qu'il porte — un delai qui court, une notification qui ne
    se coupe pas — est une regle du portail, et qu'elle ne doit exister qu'une
    fois.
    """
    demande = DemandeUsager.objects.filter(pk=demande_id, invalide_le__isnull=True).first()
    if demande is None:
        raise HorsPerimetre("Cette demande n'existe pas.")

    aujourd_hui = date.today()
    if avant_le < aujourd_hui:
        raise ErreurMetier(
            "La date limite est déjà passée : l'usager n'aurait aucun délai pour répondre.",
            code="delai_passe",
        )

    with transaction.atomic():
        complement = ComplementDemande.objects.create(
            demande=demande,
            objet=objet.strip(),
            demande_le=aujourd_hui,
            avant_le=avant_le,
            cree_par=acteur.pk,
        )
        inscrire(
            objet_type="demande_usager",
            objet_id=demande.pk,
            type_evenement="complement_reclame",
            libelle=f"Complément réclamé — {demande.reference}",
            acteur=acteur,
            detail=f"« {complement.objet} », avant le {avant_le.isoformat()}.",
            donnees={"objet": complement.objet, "avantLe": avant_le.isoformat()},
        )

        # L'evenement `complement` est **obligatoire** : l'usager ne peut pas le
        # couper, et le service passe outre son refus s'il en a enregistre un.
        # Ce delai est un delai de forclusion — le silence coute le dossier.
        notifications.notifier(
            demande.deposant,
            type_notification="complement",
            libelle=f"Pièce complémentaire demandée — {demande.reference}",
            detail=f"« {complement.objet} », à déposer avant le {avant_le.strftime('%d/%m/%Y')}.",
            importance="alerte",
            objet_type="demande_usager",
            objet_id=demande.pk,
            lien=f"/portail/demandes/{demande.pk}",
            acteur=acteur,
        )
    return complement


# =====================================================================
#  Outils
# =====================================================================


def _joindre(
    demande: DemandeUsager,
    piece: dict,
    acteur: Utilisateur,
    jour: date,
    *,
    message: MessagePortail | None,
) -> PieceDemande:
    """
    Enregistre une piece annoncee par le client.

    Le fichier lui-meme n'est pas stocke par ce pilier : le portail enregistre
    ce qui a ete depose, son nom et sa taille declaree. Le stockage binaire et
    l'analyse antivirale sont un sujet a part, ouvert — voir A45. Ne pas le
    resoudre a moitie vaut mieux que de laisser croire que le fichier est en
    lieu sur.
    """
    nom = str(piece.get("nom", "")).strip()
    if not nom:
        raise ErreurMetier(
            "Une pièce sans nom ne peut pas être enregistrée.", code="piece_sans_nom"
        )

    return PieceDemande.objects.create(
        demande=demande,
        message=message,
        nom=nom,
        taille=str(piece.get("taille", "")).strip() or "taille inconnue",
        deposee_le=jour,
        depose_par=acteur,
    )


def _reference_libre(jour: date) -> str:
    """
    La reference d'une demande — `DEM-2026-0001`.

    Meme forme et meme reserve que pour les dossiers : le compteur est celui de
    l'exercice, le calcul se fait sous verrou de transaction, et la contrainte
    d'unicite arrete deux depots simultanes. Le format n'est pas valide par le
    Port autonome de Douala — voir A39, qui vaut pour les deux.
    """
    prefixe = f"DEM-{jour.year}-"
    derniere = (
        DemandeUsager.objects.filter(reference__startswith=prefixe)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    rang = int(derniere.rsplit("-", 1)[1]) + 1 if derniere else 1
    return f"{prefixe}{rang:04d}"
