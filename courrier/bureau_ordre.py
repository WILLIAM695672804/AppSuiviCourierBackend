"""
Le bureau d'ordre de structure — entree, accuse de reception, sortie.

**Au Port, le bureau d'ordre d'une structure est son point focal.** Le profil
existait deja et ne portait aucune permission du domaine courrier : il alimentait
les activites et la disponibilite, rien de plus. C'est ce module qui lui donne
son registre, et la permission `BO_STR` qui lui en ouvre les gestes.

Trois moments, et un seul est saisi par quelqu'un :

 1. **l'entree** — posee par le declencheur `cotation_structure_passage` au
    moment ou la cotation nomme la structure. Elle ne se saisit pas, et ce n'est
    pas un detail : mesuree a partir de l'accuse de reception, la duree de
    detention aurait toujours ete flatteuse — une structure lente a ouvrir son
    courrier serait apparue rapide a le traiter ;
 2. **l'accuse** — le tampon du bureau d'ordre. L'ecart avec l'entree est le
    temps mort que personne ne voyait, parce que rien ne le mesurait ;
 3. **la sortie** — l'acte par lequel la structure rend le courrier. Elle dit
    toujours par ou : reponse transmise, retour au central, transmission a une
    autre structure, cloture. Une sortie sans motif se lirait « le courrier a
    disparu de nos ecrans », ce qui n'est pas un fait de registre.

Les deux ecritures inscrivent des **jalons publics** : l'entree et la sortie
d'une structure sont le trajet du courrier, et le trajet regarde toute structure
cotee comme il regarde la DSR. Ce qui reste cloisonne est ce qui se passe *entre*
les deux — qui a ete mis dessus, avec quelle consigne. Voir
`courrier/cloisonnement.py`.
"""

from django.db.models import Q, QuerySet
from django.utils import timezone

from courrier.modeles import PassageStructure
from courrier.visibilite import visibles
from noyau.erreurs import ErreurMetier, EtatInvalide, HorsPerimetre
from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.journal.service import inscrire
from noyau.perimetre.portee import structures_visibles

#: Les motifs de sortie, tels que le modele les enumere. Repris ici pour la
#: validation de la saisie : le front envoie un code, et un code inconnu doit
#: echouer en 422 nomme plutot qu'en violation de CHECK.
MOTIFS = {code for code, _ in PassageStructure.MOTIFS}


# =====================================================================
#  Lecture
# =====================================================================


def passages_visibles(utilisateur: Utilisateur) -> QuerySet:
    """
    Les passages que l'agent a le droit de lire.

    **Deux filtres, et il faut les deux.** Celui du courrier — un passage decrit
    un courrier, et un courrier hors perimetre ne se laisse pas deviner par le
    registre d'entree d'une structure. Celui de la structure — le bureau d'ordre
    d'une direction n'est pas le registre du Port : un point focal qui lirait les
    entrees de sa voisine y verrait exactement ce que le cloisonnement lui
    refuse par ailleurs.

    La portee `toutes` ne pose pas le second : consolider suppose de lire, et
    c'est ce que l'exigence reconnait a la DSR.
    """
    from courrier.modeles import Courrier

    lisibles = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)
    passages = PassageStructure.objects.filter(courrier__in=lisibles)

    structures = structures_visibles(utilisateur)
    if structures is None:
        return passages
    return passages.filter(Q(structure__in=structures) | Q(structure_id=utilisateur.structure_id))


def registre(
    utilisateur: Utilisateur,
    *,
    structure_id: int | None = None,
    etat: str = "en_cours",
) -> list[dict]:
    """
    Le registre du bureau d'ordre — A-02b.

    Trois etats, et ce sont les trois piles d'un bureau d'ordre reel :

     * `a_accuser` — arrive, pas encore tamponne. C'est la pile du matin ;
     * `en_cours` — tamponne, pas encore ressorti. C'est ce qui est « chez
        nous », et la duree affichee justifie une relance ;
     * `sortis` — l'archive du registre, ce qui est parti et par ou.

    `structure_id` a `None` prend toutes les structures lisibles : un point focal
    n'en a qu'une, la DSR les a toutes, et l'ecran n'a pas a savoir lequel des
    deux le consulte.
    """
    lignes = passages_visibles(utilisateur).select_related(
        "courrier", "courrier__nature", "structure", "accuse_par", "sorti_par"
    )
    if structure_id is not None:
        lignes = lignes.filter(structure_id=structure_id)

    if etat == "a_accuser":
        lignes = lignes.filter(accuse_le__isnull=True, sorti_le__isnull=True).order_by("entre_le")
    elif etat == "sortis":
        lignes = lignes.filter(sorti_le__isnull=False).order_by("-sorti_le")
    else:
        lignes = lignes.filter(sorti_le__isnull=True).order_by("entre_le")

    return [ligne_de(passage) for passage in lignes[:200]]


def ligne_de(passage: PassageStructure) -> dict:
    """Une ligne du registre, telle que l'ecran la lit."""
    from courrier.lecture import etape_de

    courrier = passage.courrier
    fin = passage.sorti_le or timezone.now()
    return {
        "id": passage.pk,
        "courrierId": courrier.pk,
        "numero": courrier.numero,
        "objet": courrier.objet,
        "correspondant": courrier.expediteur_libelle,
        "nature": courrier.nature.libelle if courrier.nature else None,
        "structure": passage.structure.code,
        "structureId": passage.structure_id,
        "etape": etape_de(courrier),
        "entreLe": passage.entre_le,
        "accuseLe": passage.accuse_le,
        "accusePar": _nom(passage.accuse_par),
        "sortiLe": passage.sorti_le,
        "sortiPar": _nom(passage.sorti_par),
        "motifSortie": passage.motif_sortie,
        "noteSortie": passage.note_sortie,
        # Le temps passe dans la structure, arrete a la sortie. C'est le chiffre
        # que le bureau d'ordre doit pouvoir opposer : « le dossier est chez nous
        # depuis onze jours » n'a de sens que compte depuis l'entree.
        "joursDansLaStructure": max(0, (fin - passage.entre_le).days),
        # Le temps mort du bureau d'ordre : entre l'arrivee et le tampon. Nul
        # quand l'accuse n'a pas encore ete pose — le compteur court toujours,
        # et l'afficher comme une duree acquise serait faux.
        "heuresAvantAccuse": (
            int((passage.accuse_le - passage.entre_le).total_seconds() // 3600)
            if passage.accuse_le
            else None
        ),
    }


def _nom(agent: Utilisateur | None) -> str | None:
    return f"{agent.prenom} {agent.nom}" if agent else None


# =====================================================================
#  Ecriture
# =====================================================================


def accuser_reception(utilisateur: Utilisateur, passage_id: int) -> PassageStructure:
    """
    Le bureau d'ordre reconnait avoir recu le courrier.

    **Une seule fois.** Un second accuse ecraserait l'heure du premier, et
    l'ecart entre l'entree et le tampon — la seule mesure du temps mort — se
    remettrait a zero a chaque clic.
    """
    passage = _passage_ecrivable(utilisateur, passage_id)
    if passage.accuse_le is not None:
        raise EtatInvalide("La réception de ce courrier est déjà accusée.")
    if passage.sorti_le is not None:
        raise EtatInvalide("Ce courrier est déjà sorti de la structure.")

    maintenant = timezone.now()
    with acteur(utilisateur):
        PassageStructure.objects.filter(pk=passage.pk).update(
            accuse_le=maintenant, accuse_par=utilisateur
        )
        inscrire(
            objet_type="courrier",
            objet_id=passage.courrier_id,
            courrier_id=passage.courrier_id,
            type_evenement="courrier.entre_structure",
            libelle=f"Reçu au bureau d'ordre — {passage.structure.code}",
            detail=_attente(passage, maintenant),
            acteur=utilisateur,
            # **Jalon public.** L'entree d'un courrier dans une structure est son
            # trajet : la DSR doit la voir pour suivre les delais, et les autres
            # structures cotees pour savoir ou en est l'affaire. Ce qui reste
            # cloisonne est ce qui se passe ensuite a l'interieur.
            donnees={"structure": passage.structure.code, "passageId": passage.pk},
        )

    passage.refresh_from_db()
    return passage


def prononcer_sortie(utilisateur: Utilisateur, passage_id: int, saisie: dict) -> PassageStructure:
    """
    La structure rend le courrier.

    **Le motif n'est pas facultatif** — le CHECK `passage_sortie_motivee` le
    tient aussi en base. Une sortie sans motif se lirait « le courrier a disparu
    de nos ecrans », et le registre d'un bureau d'ordre existe precisement pour
    dire par ou les choses sont parties.

    La sortie n'exige pas l'accuse prealable, et c'est voulu : un courrier
    aussitot renvoye au central — coté par erreur, par exemple — sort sans
    jamais avoir ete pris en charge. L'obliger a un tampon d'abord aurait produit
    un accuse de complaisance, donc une fausse mesure.
    """
    passage = _passage_ecrivable(utilisateur, passage_id)
    if passage.sorti_le is not None:
        raise EtatInvalide("Ce courrier est déjà sorti de la structure.")

    motif = (saisie.get("motif") or "").strip()
    if motif not in MOTIFS:
        raise ErreurMetier(
            "Une sortie dit toujours par où : réponse, retour, transmission, clôture ou autre.",
            code="motif_sortie_exige",
        )

    note = (saisie.get("note") or "").strip() or None
    maintenant = timezone.now()

    with acteur(utilisateur):
        PassageStructure.objects.filter(pk=passage.pk).update(
            sorti_le=maintenant,
            sorti_par=utilisateur,
            motif_sortie=motif,
            note_sortie=note,
        )
        libelles = dict(PassageStructure.MOTIFS)
        inscrire(
            objet_type="courrier",
            objet_id=passage.courrier_id,
            courrier_id=passage.courrier_id,
            type_evenement="courrier.sorti_structure",
            libelle=f"Sorti de {passage.structure.code} — {libelles[motif]}",
            detail=note,
            acteur=utilisateur,
            # Jalon public, meme raison que l'entree.
            donnees={
                "structure": passage.structure.code,
                "motif": motif,
                "passageId": passage.pk,
                "joursDansLaStructure": max(0, (maintenant - passage.entre_le).days),
            },
        )

    passage.refresh_from_db()
    return passage


def _passage_ecrivable(utilisateur: Utilisateur, passage_id: int) -> PassageStructure:
    """
    Le passage, si l'agent tient ce bureau d'ordre.

    `visibles()` sert a l'ecriture comme a la lecture, et l'echec sort en
    **404** : repondre « interdit » confirmerait qu'un courrier est bien coté a
    telle structure, ce qui est deja l'information (decision D5).
    """
    passage = (
        passages_visibles(utilisateur)
        .select_related("courrier", "structure")
        .filter(pk=passage_id)
        .first()
    )
    if passage is None:
        raise HorsPerimetre("Ce passage n'existe pas ou ne relève pas de votre périmètre.")
    if not possede(utilisateur, PERM.BO_STR):
        # Ceinture et bretelles : la route porte deja la garde. Le second
        # controle couvre la voie d'ecriture qui ne passerait pas par elle — une
        # reprise, une commande de gestion.
        raise HorsPerimetre("Ce passage n'existe pas ou ne relève pas de votre périmètre.")
    return passage


def _attente(passage: PassageStructure, accuse_le) -> str:
    """Le temps mort, en clair, pour le journal."""
    heures = int((accuse_le - passage.entre_le).total_seconds() // 3600)
    if heures < 1:
        return "Reçu dans l'heure"
    if heures < 24:
        return f"Reçu après {heures} h d'attente"
    return f"Reçu après {heures // 24} j d'attente"
