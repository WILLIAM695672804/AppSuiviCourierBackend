"""
Ecritures du pilier archivage.

Quatre gestes : creer une regle de conservation, la viser, verser un dossier,
produire une preuve d'integrite.

**Aucun ne supprime quoi que ce soit.** Le sort final se propose, il ne
s'execute pas : la destruction d'archives publiques suppose un visa que le
logiciel n'a pas a donner. Un module d'archivage qui saurait detruire finirait
par detruire.

Deux refus structurent le reste :

 * *on ne verse pas sans regle visee.* Verser un dossier sans regle de
   conservation reviendrait a le deposer sans dire combien de temps on le
   garde ; et une regle non visee par le service des archives ne decide de rien
   (RF-ADM-05). Ces deux anomalies sont **bloquantes** ;
 * *on ne vise pas sa propre regle sans que cela se voie.* Le visa porte le nom
   de qui l'a donne et sa date. C'est ce qui rend la regle opposable — et ce
   qui permet de savoir a qui la question se pose quand elle est contestee.
"""

import hashlib
from datetime import date

from django.db import transaction
from django.utils import timezone

from archivage.lecture import LIBELLE_TYPE, anomalies_de, echeance_sort
from archivage.modeles import (
    ALGORITHME,
    ETAT_VERSE,
    SORTS,
    MaillonIntegrite,
    RegleConservation,
    Versement,
)
from dossier.modeles import ETAPE_CLOS, Dossier
from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire

# =====================================================================
#  Le referentiel de conservation
# =====================================================================


def creer_regle(
    acteur: Utilisateur,
    *,
    typologie: str,
    description: str,
    dua: int,
    sort_final: str,
    fondement_juridique: str,
    pieces_attendues: int = 0,
) -> RegleConservation:
    """
    Pose une duree d'utilite administrative et un sort final — RF-GED-06.

    La regle est creee **sans visa** : c'est le service des archives qui la
    rend applicable, pas celui qui la saisit. La creer deja visee aurait retire
    au service des archives sa competence par voie logicielle, ce que
    RF-ADM-05 interdit exactement.
    """
    sort = _code_sort(sort_final)

    if not fondement_juridique.strip():
        raise ErreurMetier(
            "Le fondement juridique est obligatoire : sans texte, la règle n'est "
            "pas opposable — un archiviste répond par un texte, pas par une "
            "capture d'écran.",
            code="fondement_absent",
        )
    if dua < 1 or dua > 100:
        raise ErreurMetier(
            "La durée d'utilité administrative se compte en années, entre 1 et 100. "
            "Zéro année signifierait « détruire le jour de la clôture », ce qui n'est "
            "pas une durée de conservation.",
            code="dua_invraisemblable",
        )

    if RegleConservation.objects.filter(typologie=typologie.strip()).exists():
        raise ErreurMetier(
            f"Une règle existe déjà pour « {typologie.strip()} ». "
            "Deux durées pour la même typologie voudraient dire deux dates "
            "d'élimination, et personne ne saurait laquelle appliquer.",
            code="typologie_deja_reglee",
        )

    with transaction.atomic():
        regle = RegleConservation.objects.create(
            typologie=typologie.strip(),
            description=description.strip(),
            dua=dua,
            sort_final=sort,
            fondement_juridique=fondement_juridique.strip(),
            pieces_attendues=max(pieces_attendues, 0),
            cree_par=acteur.pk,
        )
        inscrire(
            objet_type="regle_conservation",
            objet_id=regle.pk,
            type_evenement="regle_conservation_creee",
            libelle=f"Règle de conservation — {regle.typologie}",
            acteur=acteur,
            detail=(
                f"DUA {dua} an(s), sort final « {dict(SORTS)[sort]} ». "
                f"Fondement : {regle.fondement_juridique}. "
                "En attente du visa du service des archives."
            ),
            donnees={"typologie": regle.typologie, "dua": dua, "sortFinal": sort},
        )
    return regle


def viser_regle(acteur: Utilisateur, *, regle_id: int) -> RegleConservation:
    """
    Le visa du service des archives — RF-ADM-05.

    C'est le geste qui rend la regle applicable. Une regle deja visee n'est pas
    revisee : le second visa ecraserait le nom du premier signataire, et c'est
    ce nom qu'on cherche quand la duree est contestee.
    """
    regle = RegleConservation.objects.filter(pk=regle_id).first()
    if regle is None:
        raise HorsPerimetre("Cette règle de conservation n'existe pas.")

    # `regle.visee` est exactement `validee_le is not None` ; on teste la date
    # elle-meme pour que le message qui la cite soit sur de la trouver.
    if regle.validee_le is not None:
        raise ErreurMetier(
            f"Cette règle est déjà visée, le {regle.validee_le.isoformat()}. "
            "Un second visa effacerait le nom du premier signataire.",
            code="regle_deja_visee",
        )

    with transaction.atomic():
        regle.validee_par = acteur
        regle.validee_le = date.today()
        regle.modifie_par = acteur.pk
        regle.modifie_le = timezone.now()
        regle.save(update_fields=["validee_par", "validee_le", "modifie_par", "modifie_le"])
        inscrire(
            objet_type="regle_conservation",
            objet_id=regle.pk,
            type_evenement="regle_conservation_visee",
            libelle=f"Visa des archives — {regle.typologie}",
            acteur=acteur,
            detail=(
                f"La règle devient applicable : DUA {regle.dua} an(s), "
                f"sort final « {dict(SORTS)[regle.sort_final]} »."
            ),
        )
    return regle


def _code_sort(demande: str) -> str:
    for code, libelle in SORTS:
        if demande in (code, libelle):
            return code
    attendus = ", ".join(libelle for _, libelle in SORTS)
    raise ErreurMetier(
        f"Le sort final « {demande} » n'existe pas. Valeurs attendues : {attendus}.",
        code="sort_hors_referentiel",
    )


# =====================================================================
#  Le versement
# =====================================================================


def verser(
    acteur: Utilisateur,
    *,
    dossier_id: int,
    observation: str = "",
    anomalies_acceptees: bool = False,
) -> Versement:
    """
    Verse un dossier clos aux archives.

    L'identifiant recu par la route est celui de la **file** : negatif pour un
    dossier pas encore verse. C'est ici qu'il redevient un identifiant de
    dossier.

    Une anomalie **bloquante** arrete le versement, quoi qu'en dise
    `anomalies_acceptees` : accepter de verser un dossier dont aucune regle ne
    dit la duree de conservation reviendrait a le perdre proprement. Une
    anomalie non bloquante se passe outre, mais **avec une observation** : le
    fonds garde alors la trace de ce qui manquait, et c'est cette phrase que
    l'archiviste tiendra devant un auditeur.
    """
    dossier = _dossier_versable(dossier_id)

    if Versement.objects.filter(dossier=dossier).exists():
        raise ErreurMetier(
            f"Le dossier {dossier.reference} a déjà été versé.",
            code="dossier_deja_verse",
        )

    typologie = LIBELLE_TYPE.get(dossier.type_dossier, dossier.type_dossier)
    regle = RegleConservation.objects.filter(typologie=typologie, actif=True).first()
    anomalies = anomalies_de(dossier, regle, None)

    bloquantes = [anomalie for anomalie in anomalies if anomalie["bloquante"]]
    if bloquantes:
        raise ErreurMetier(
            "Le versement est impossible : "
            + " ".join(anomalie["precision"] for anomalie in bloquantes),
            code="anomalie_bloquante",
        )

    restantes = [anomalie for anomalie in anomalies if not anomalie["bloquante"]]
    if restantes and not anomalies_acceptees:
        raise ErreurMetier(
            "Ce dossier porte des anomalies : "
            + " ".join(anomalie["libelle"] for anomalie in restantes)
            + ". Le versement reste possible, mais il doit être motivé.",
            code="anomalies_non_acceptees",
        )
    if restantes and not observation.strip():
        raise ErreurMetier(
            "Verser malgré une anomalie suppose de dire laquelle et pourquoi : "
            "l'observation est obligatoire.",
            code="observation_absente",
        )

    assert regle is not None  # garanti par l'absence d'anomalie bloquante
    echeance = echeance_sort(dossier.clos_le, regle.dua)
    assert echeance is not None  # `clos_le` est non nul par `_dossier_versable`

    with transaction.atomic():
        versement = Versement.objects.create(
            dossier=dossier,
            regle=regle,
            # Figes au versement : la regle peut changer ensuite, ce qui a ete
            # verse l'a ete sous la regle d'alors.
            dua_appliquee=regle.dua,
            sort_final_applique=regle.sort_final,
            echeance_sort_final=echeance,
            etat=ETAT_VERSE,
            observation=observation.strip() or None,
            anomalies_acceptees=bool(restantes),
            verse_le=timezone.now(),
            verse_par=acteur,
            cree_par=acteur.pk,
        )
        sceller(versement, "Versement aux archives")
        inscrire(
            objet_type="versement",
            objet_id=versement.pk,
            type_evenement="dossier_verse",
            libelle=f"Dossier {dossier.reference} versé aux archives",
            acteur=acteur,
            detail=(
                f"DUA {regle.dua} an(s), sort final « {dict(SORTS)[regle.sort_final]} » "
                f"au {echeance.isoformat()}."
                + (f" Observation : {observation.strip()}" if observation.strip() else "")
            ),
            donnees={"dossier": dossier.reference, "echeanceSortFinal": echeance.isoformat()},
        )
    return versement


def _dossier_versable(identifiant: int) -> Dossier:
    """Le dossier designe par la file, clos et vivant."""
    reel = -identifiant if identifiant < 0 else identifiant
    dossier = Dossier.objects.filter(pk=reel, invalide_le__isnull=True).first()

    if dossier is None:
        versement = Versement.objects.filter(pk=identifiant).select_related("dossier").first()
        dossier = versement.dossier if versement else None

    if dossier is None:
        raise HorsPerimetre("Ce dossier n'existe pas.")

    if dossier.etape != ETAPE_CLOS or dossier.clos_le is None:
        raise ErreurMetier(
            f"Le dossier {dossier.reference} n'est pas clos : "
            "la durée d'utilité administrative court à partir de la clôture, "
            "elle n'a pas de point de départ tant que l'instruction continue.",
            code="dossier_non_clos",
        )
    return dossier


# =====================================================================
#  La chaine d'integrite et la preuve
# =====================================================================


def sceller(versement: Versement, etape: str) -> MaillonIntegrite:
    """
    Ajoute un maillon a la chaine d'empreintes — RF-GED-09.

    Le maillon **inclut l'empreinte du precedent**. C'est ce chainage qui fait
    la preuve : une empreinte isolee prouve qu'un fichier n'a pas bouge, une
    chaine prouve qu'aucune etape n'a ete retiree entre deux autres.

    Le contenu scelle est l'etat du dossier a ce moment — sa reference, ses
    pieces et leurs empreintes. Sceller l'identifiant seul n'aurait rien
    prouve : il ne change jamais.
    """
    precedent = versement.maillons.order_by("-rang").first()
    rang = (precedent.rang + 1) if precedent else 1

    dossier = versement.dossier
    matiere = [
        dossier.reference,
        dossier.objet,
        dossier.clos_le.isoformat() if dossier.clos_le else "",
        str(versement.dua_appliquee),
        versement.sort_final_applique,
        versement.echeance_sort_final.isoformat(),
        etape,
    ]
    for piece in dossier.pieces.prefetch_related("versions").order_by("pk"):
        for version in piece.versions.order_by("version"):
            matiere.append(f"{piece.nom}#{version.version}:{version.empreinte}")

    if precedent is not None:
        matiere.append(precedent.empreinte)

    empreinte = hashlib.sha256("\n".join(matiere).encode("utf8")).hexdigest()

    return MaillonIntegrite.objects.create(
        versement=versement,
        rang=rang,
        etape=etape,
        empreinte=empreinte,
        empreinte_precedente=precedent.empreinte if precedent else None,
    )


def produire_preuve(
    acteur: Utilisateur, *, versement_id: int, motif: str, destinataire: str
) -> dict:
    """
    La preuve d'integrite remise a un tiers — RF-GED-09.

    Le motif et le destinataire sont **obligatoires et journalises**. Une
    preuve d'integrite sort de l'institution ; savoir a qui elle a ete remise
    et pourquoi fait partie de ce qu'elle prouve.

    L'« autorite » d'horodatage est l'application elle-meme. C'est une limite
    et elle est ecrite dans la reponse : un horodatage qualifie suppose un
    tiers de confiance que ce depot n'a pas. Voir A40.
    """
    versement = Versement.objects.filter(pk=versement_id).select_related("dossier").first()
    if versement is None:
        raise HorsPerimetre("Ce versement n'existe pas.")

    if not motif.strip():
        raise ErreurMetier(
            "Le motif est obligatoire : une preuve d'intégrité sort de "
            "l'institution, et savoir pourquoi fait partie de ce qu'elle prouve.",
            code="motif_absent",
        )
    if not destinataire.strip():
        raise ErreurMetier(
            "Indiquez à qui la preuve est destinée.",
            code="destinataire_absent",
        )

    with transaction.atomic():
        maillon = sceller(versement, f"Preuve remise à {destinataire.strip()}")
        dossier = versement.dossier
        pieces = dossier.pieces.count()
        octets = sum(
            version.taille_octets
            for piece in dossier.pieces.prefetch_related("versions")
            for version in piece.versions.all()
        )

        inscrire(
            objet_type="versement",
            objet_id=versement.pk,
            type_evenement="preuve_integrite_produite",
            libelle=f"Preuve d'intégrité — {dossier.reference}",
            acteur=acteur,
            detail=f"Remise à {destinataire.strip()}. Motif : {motif.strip()}",
            donnees={"empreinte": maillon.empreinte, "destinataire": destinataire.strip()},
        )

    return {
        "reference": dossier.reference,
        "objet": dossier.objet,
        "algorithme": ALGORITHME,
        "empreinte": maillon.empreinte,
        "horodatage": maillon.horodatage.isoformat(),
        # Voir la docstring : l'application n'est pas un tiers de confiance.
        "autorite": "Horodatage applicatif — sans tiers de confiance (A40)",
        "nombrePieces": pieces,
        "taille": _taille(octets),
        "produitePar": f"{acteur.prenom} {acteur.nom}".strip(),
    }


def _taille(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")
