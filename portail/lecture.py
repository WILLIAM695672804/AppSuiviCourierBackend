"""
Lectures du portail usagers.

**La regle qui gouverne ce module : l'usager ne voit que ce qui lui appartient.**
Elle ne s'obtient pas par `restreindre()`, qui restreint par structure et par
agent — un usager n'appartient a aucune structure du port, et le laisser passer
par la aurait ouvert tout le portail au premier compte externe rattache par
megarde a une direction. Le filtre est ici `deposant=utilisateur` et
`partenaire=utilisateur`, ecrit dans chaque requete. Voir ADR 013.

Consequence directe : une demande qui n'est pas la sienne repond **404** et non
403. C'est la decision D5 du cadrage — dire « ce dossier existe mais pas pour
vous » est deja une fuite, et sur un portail public elle permettrait d'enumerer
les demandes de l'institution une reference a la fois.

**Rien de calculable n'est stocke** (ADR 010). L'etat d'une demande, celui d'un
echange, la frise des etapes et le compte des pieces se deduisent des faits ;
aucune colonne ne les double.

**Le vocabulaire est celui de l'usager.** Les libelles d'etape sont ecrits ici,
en clair, avec leur explication : « votre demande est arrivee, elle a une
reference » plutot que « cotation initiale enregistree ».
"""

from datetime import date

from django.db.models import Count, Q

from noyau.erreurs import HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.parametres import service as parametres
from portail.modeles import (
    CANAL_COURRIEL,
    DemandeUsager,
    EchangeDematerialise,
    EvenementNotifiable,
    PreferenceNotification,
)

#: Les cinq etats qu'un usager peut lire sur sa demande. Ils ne sont pas
#: stockes : `etat_demande()` les deduit.
ETAT_DEPOSEE = "Déposée"
ETAT_ETUDE = "À l'étude"
ETAT_COMPLEMENT = "Complément attendu"
ETAT_DECISION = "Décision rendue"
ETAT_CLOSE = "Close"


def delai_reponse_jours() -> int:
    """
    Le delai annonce a l'usager **avant** qu'il ne depose.

    Trente jours par defaut, sans source : c'est un usage administratif
    courant, pas une regle ecrite du Port autonome de Douala. La valeur vit en
    base en `hypothese` (`portail.delai_reponse_jours`) pour qu'une direction
    puisse la corriger sans livraison — voir A43.

    Elle n'est lue qu'au depot : la date promise est ensuite figee sur la
    demande. Un delai raccourci ne doit pas mettre en retard, retroactivement,
    des demandes deposees sous l'ancien regime.
    """
    return int(parametres.valeur("portail.delai_reponse_jours", 30))


# =====================================================================
#  Mes demandes
# =====================================================================


def demandes_de(utilisateur: Utilisateur):
    """
    Les demandes vivantes d'un usager. **Le seul point d'entree** : aucune autre
    fonction de ce module ne part de `DemandeUsager.objects` directement.
    """
    return (
        DemandeUsager.objects.filter(invalide_le__isnull=True, deposant=utilisateur)
        .select_related("service_instructeur")
        .prefetch_related("complements")
    )


def etat_demande(demande: DemandeUsager, *, complement_en_attente: bool) -> str:
    """
    L'etat, deduit de quatre faits et dans cet ordre.

    L'ordre n'est pas indifferent : une demande close dont un complement n'a
    jamais ete satisfait est **close**, pas « complement attendu ». Reclamer une
    piece pour un dossier termine est le genre de message qui fait perdre
    confiance dans l'outil entier.
    """
    if demande.clos_le is not None:
        return ETAT_CLOSE
    if demande.decision_le is not None:
        return ETAT_DECISION
    if complement_en_attente:
        return ETAT_COMPLEMENT
    if demande.service_instructeur_id is not None:
        return ETAT_ETUDE
    return ETAT_DEPOSEE


def _complement_en_attente(demande: DemandeUsager):
    """Le dernier complement reclame et non satisfait, ou `None`."""
    for complement in demande.complements.all():
        if complement.satisfait_le is None:
            return complement
    return None


def _service(demande: DemandeUsager) -> str:
    """
    Le service instructeur, en clair.

    « En cours d'orientation » est la verite quand rien n'est designe. Choisir un
    service par defaut aurait envoye l'usager telephoner au mauvais guichet, et
    le guichet en question aurait decouvert un dossier qu'il n'a pas.
    """
    if demande.service_instructeur is None:
        return "En cours d'orientation"
    return demande.service_instructeur.libelle


def mes_demandes(utilisateur: Utilisateur) -> dict:
    """
    L'ecran « Mes demandes ».

    Les demandes qui attendent quelque chose de l'usager passent en tete : c'est
    la seule hierarchie qui compte sur cet ecran. Une liste antichronologique
    aurait enterre sous trois dossiers termines la piece a fournir avant
    vendredi.
    """
    lignes = []
    for demande in demandes_de(utilisateur):
        complement = _complement_en_attente(demande)
        lignes.append(
            {
                "id": demande.pk,
                "reference": demande.reference,
                "objet": demande.objet,
                "type": demande.type,
                "deposeeLe": demande.deposee_le.isoformat(),
                "reponseAttendueLe": demande.reponse_attendue_le.isoformat(),
                "etat": etat_demande(demande, complement_en_attente=complement is not None),
                "actionAttendue": complement is not None,
                "serviceInstructeur": _service(demande),
            }
        )

    lignes.sort(key=lambda ligne: (not ligne["actionAttendue"], ligne["deposeeLe"]), reverse=False)
    lignes.sort(key=lambda ligne: not ligne["actionAttendue"])

    return {
        "demandes": lignes,
        "identite": utilisateur.nom_complet,
        "delaiReponseJours": delai_reponse_jours(),
    }


# =====================================================================
#  Le suivi d'une demande
# =====================================================================


def _frise(demande: DemandeUsager, complement) -> list[dict]:
    """
    La frise, expliquee sans jargon.

    Quatre etapes, pas cinq : l'usager n'a que faire de la distinction entre
    qualification et instruction, qui est une affaire d'organisation interne.
    Ce qu'il veut savoir est plus simple — c'est parti, quelqu'un s'en occupe,
    on m'a repondu, c'est fini.

    Chaque etape porte son **explication**, parce qu'une frise sans texte se lit
    comme un compte a rebours dont on ignore la duree.
    """
    orientee = demande.service_instructeur_id is not None
    decidee = demande.decision_le is not None
    close = demande.clos_le is not None

    etapes = [
        {
            "libelle": "Demande reçue",
            "franchie": True,
            "date": demande.deposee_le.isoformat(),
            "explication": (
                "Votre demande est enregistrée sous la référence "
                f"{demande.reference}. Conservez-la : elle suffit à retrouver "
                "votre dossier."
            ),
        },
        {
            "libelle": "Prise en charge",
            "franchie": orientee,
            "date": None,
            "explication": (
                f"Votre demande est étudiée par : {_service(demande)}."
                if orientee
                else "Votre demande est en cours d'orientation vers le service compétent."
            ),
        },
        {
            "libelle": "Réponse",
            "franchie": decidee,
            # `demande.decision_le` plutot que `decidee` : mypy ne suit pas le
            # rapprochement de type a travers une variable intermediaire.
            "date": (demande.decision_le.isoformat() if demande.decision_le else None),
            "explication": (
                demande.decision
                if decidee
                else (
                    "La réponse vous est promise pour le "
                    f"{demande.reponse_attendue_le.isoformat()}. Vous serez "
                    "averti dès qu'elle est rendue."
                )
            ),
        },
        {
            "libelle": "Dossier clos",
            "franchie": close,
            "date": (demande.clos_le.isoformat() if demande.clos_le else None),
            "explication": (
                "Votre dossier est clos et conservé."
                if close
                else "Le dossier reste ouvert tant que la réponse ne vous a pas été notifiée."
            ),
        },
    ]

    # L'attente d'une piece s'intercale la ou elle bloque : apres la prise en
    # charge. La placer en fin de frise aurait laisse croire que le dossier
    # avance pendant qu'il attend.
    if complement is not None:
        etapes.insert(
            2,
            {
                "libelle": "Pièce attendue de votre part",
                "franchie": False,
                "date": None,
                "explication": (
                    f"Il manque : {complement.objet}. À déposer avant le "
                    f"{complement.avant_le.isoformat()}, faute de quoi votre "
                    "dossier pourra être clos sans suite."
                ),
            },
        )
    return etapes


def demande(utilisateur: Utilisateur, identifiant: int) -> dict:
    """
    Le suivi d'une demande.

    404 quand elle appartient a quelqu'un d'autre, quand elle n'existe pas, et
    quand elle est invalidee : les trois cas se lisent pareil de l'exterieur, et
    c'est le but (D5).
    """
    cible = demandes_de(utilisateur).filter(pk=identifiant).first()
    if cible is None:
        raise HorsPerimetre("Cette demande n'existe pas ou ne vous appartient pas.")

    complement = _complement_en_attente(cible)

    messages = [
        {
            "id": message.pk,
            "auteur": "Vous" if message.auteur_id == utilisateur.pk else "Institution",
            "nom": message.auteur.nom_complet,
            "date": message.cree_le.date().isoformat(),
            "texte": message.texte,
            "pieces": [
                {"nom": piece.nom, "taille": piece.taille} for piece in message.pieces.all()
            ],
        }
        for message in cible.messages.select_related("auteur").prefetch_related("pieces")
    ]

    pieces = [
        {
            "id": piece.pk,
            "nom": piece.nom,
            "taille": piece.taille,
            "deposeeLe": piece.deposee_le.isoformat(),
            "parVous": piece.depose_par_id == utilisateur.pk,
        }
        for piece in cible.pieces.all()
    ]

    return {
        "id": cible.pk,
        "reference": cible.reference,
        "objet": cible.objet,
        "type": cible.type,
        "deposeeLe": cible.deposee_le.isoformat(),
        "reponseAttendueLe": cible.reponse_attendue_le.isoformat(),
        "etat": etat_demande(cible, complement_en_attente=complement is not None),
        "actionAttendue": complement is not None,
        "serviceInstructeur": _service(cible),
        "contexte": cible.contexte,
        "etapes": _frise(cible, complement),
        "messages": messages,
        "pieces": pieces,
        "complementAttendu": (
            None
            if complement is None
            else {"objet": complement.objet, "avantLe": complement.avant_le.isoformat()}
        ),
    }


# =====================================================================
#  Preferences de notification
# =====================================================================


def preferences(utilisateur: Utilisateur) -> dict:
    """
    Le canal choisi et les evenements retenus.

    Aucune ligne en base n'est une reponse valide : c'est le reglage par defaut
    — courriel, tous les evenements actifs — et non une erreur. La ligne se cree
    a la premiere modification, pas a la premiere lecture : une consultation ne
    doit rien ecrire.

    Les evenements **obligatoires** sortent toujours a `actif: true`, quoi que
    porte la base. Une ligne qui les aurait coupes, arrivee par une importation
    ou une migration, ne doit pas priver l'usager de la demande de complement.
    """
    reglage = PreferenceNotification.objects.filter(utilisateur=utilisateur).first()
    choix = {}
    if reglage is not None:
        choix = {ligne.evenement_id: ligne.actif for ligne in reglage.evenements.select_related()}

    evenements = [
        {
            "cle": evenement.cle,
            "libelle": evenement.libelle,
            "actif": True if evenement.obligatoire else choix.get(evenement.pk, True),
            "obligatoire": evenement.obligatoire,
        }
        for evenement in EvenementNotifiable.objects.filter(actif=True)
    ]

    return {
        "courriel": (reglage.courriel if reglage else utilisateur.courriel) or "",
        "telephone": (reglage.telephone if reglage else utilisateur.telephone) or None,
        "canal": reglage.canal if reglage else CANAL_COURRIEL,
        "evenements": evenements,
    }


# =====================================================================
#  Echanges dematerialises
# =====================================================================


def echanges(utilisateur: Utilisateur) -> dict:
    """
    Les marches, conventions et reportings ouverts a ce partenaire.

    L'etat se calcule : clos, en attente d'un depot, ou simplement ouvert. Un
    echange dont toutes les pieces sont deposees mais qui n'est pas clos reste
    « Ouvert » — c'est a l'institution de le fermer, et l'usager doit voir qu'il
    n'a plus rien a faire sans croire pour autant que l'affaire est reglee.
    """
    lignes = []
    requete = (
        EchangeDematerialise.objects.filter(partenaire=utilisateur)
        .annotate(deposes=Count("pieces", filter=Q(pieces__isnull=False)))
        .order_by("clos_le", "echeance", "-ouvert_le")
    )

    for echange in requete:
        if echange.clos_le is not None:
            etat = "Clos"
        elif echange.deposes < echange.attendus:
            etat = "En attente de votre dépôt"
        else:
            etat = "Ouvert"

        lignes.append(
            {
                "id": echange.pk,
                "reference": echange.reference,
                "intitule": echange.intitule,
                "nature": echange.nature,
                "ouvertLe": echange.ouvert_le.isoformat(),
                "echeance": echange.echeance.isoformat() if echange.echeance else None,
                "attendus": echange.attendus,
                "deposes": echange.deposes,
                "etat": etat,
            }
        )

    # Ce qui attend un depot d'abord ; le reste ensuite. Meme raison que sur
    # « Mes demandes » : ce que l'usager doit faire ne se cherche pas.
    lignes.sort(key=lambda ligne: ligne["etat"] != "En attente de votre dépôt")
    return {"echanges": lignes}


def jours_restants(echeance: date | None, *, a_la_date: date | None = None) -> int | None:
    """
    Le nombre de jours avant une echeance, ou `None` quand il n'y en a pas.

    `None` n'est pas zero : une convention sans echeance n'est pas une
    convention echue aujourd'hui. C'est l'ADR 011 applique a une date.
    """
    if echeance is None:
        return None
    return (echeance - (a_la_date or date.today())).days
