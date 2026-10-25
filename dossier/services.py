"""
Ecritures du pilier dossiers.

Cinq gestes : ouvrir, demander un complement, enregistrer sa reception,
retourner a une etape anterieure, fusionner un courrier-type.

**Ce qui n'est pas negociable ici.**

 * *Le motif de retour est obligatoire* — RF-BPM-06. Un dossier qui revient
   sans motif oblige l'etape precedente a deviner ce qu'on lui reproche, et
   c'est la premiere cause d'aller-retours en boucle. Le motif est refuse s'il
   est vide ou trop court : « à revoir » n'est pas un motif.
 * *Le retour ne perd rien de l'historique* — RF-BPM-06 encore. Le journal
   garde l'etape d'ou l'on vient et celle ou l'on retourne ; c'est cette paire
   qui permet, six mois plus tard, de reconstituer le chemin reel du dossier et
   pas seulement son etat final.
 * *La regle d'affectation est figee a l'ouverture.* Voir `Dossier`.
 * *L'echeance ne se suspend jamais.* Aucune ecriture de ce module ne repousse
   `Dossier.echeance` — pas meme la demande de complement. Le demandeur qui ne
   repond pas ne dispense pas l'institution de son obligation de reponse.

Toute ecriture inscrit un evenement : c'est la regle du depot, et ici elle fait
double emploi utile — le journal **est** l'historique de la fiche (ADR 012).
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from dossier.lecture import LIBELLE_ETAPE, variables_du_corps
from dossier.modeles import (
    CRITICITES,
    ETAPE_CLOS,
    RANG_ETAPES,
    TYPES,
    Complement,
    Dossier,
    ModeleCourrier,
    RegleAffectation,
)
from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.parametres import service as parametres


def longueur_minimale_motif() -> int:
    """
    Ce qu'on exige d'un motif de retour, en caracteres.

    RF-BPM-06 exige un motif ; il ne dit pas ce qui compte comme motif. Quinze
    caracteres ecartent « ok » et « a revoir » sans pretendre juger du fond.
    **Aucune source** : la valeur vit en base, en `hypothese` — voir A38.
    """
    return int(parametres.valeur("dossier.longueur_minimale_motif", 15))


def delai_instruction_defaut() -> int:
    """
    Le delai d'instruction applique quand aucune echeance n'est saisie.

    Trente jours est le delai administratif le plus courant ; personne ne l'a
    confirme pour le Port autonome de Douala, et il varie tres probablement
    selon la typologie. **Aucune source** — voir A38.
    """
    return int(parametres.valeur("dossier.delai_instruction_defaut_jours", 30))


# =====================================================================
#  Ouvrir un dossier
# =====================================================================


def ouvrir(
    acteur: Utilisateur,
    *,
    type_dossier: str,
    objet: str,
    demandeur: str,
    echeance: str = "",
    contexte: str = "",
    criticite: str = "standard",
    montant: int | None = None,
    courrier_id: int | None = None,
    courrier_reference: str = "",
) -> Dossier:
    """
    Ouvre un dossier a instruire — §3.6.

    « Declencher, le cas echeant, la creation automatique d'un dossier a
    instruire a partir d'un courrier entrant. » Le courrier d'origine n'est
    qu'une reference : le courrier poursuit son propre circuit, ouvrir un
    dossier ne le clot pas.

    L'ouverture **fait courir un delai dont l'institution repond**. C'est pour
    cela qu'elle refuse une echeance passee : un dossier ne s'ouvre pas deja en
    retard, sinon le registre demarre avec une alerte que personne n'a causee.
    """
    libelle_type = _code(TYPES, type_dossier, "type de dossier")
    libelle_criticite = _code(CRITICITES, criticite, "criticité")

    if len(objet.strip()) < 10:
        raise ErreurMetier(
            "L'objet du dossier doit dire ce qui est demandé — dix caractères au moins.",
            code="objet_trop_court",
        )
    if not demandeur.strip():
        raise ErreurMetier(
            "Indiquez le demandeur : c'est lui qui recevra la notification.",
            code="demandeur_absent",
        )

    aujourd_hui = date.today()
    terme = _echeance(echeance, aujourd_hui)

    if acteur.structure_id is None:
        raise ErreurMetier(
            "Votre compte n'est rattaché à aucune structure : le dossier n'aurait "
            "personne pour l'instruire.",
            code="agent_sans_structure",
        )

    regle, phrase = affectation(
        type_dossier=libelle_type,
        criticite=libelle_criticite,
        montant=montant,
        structure_par_defaut=acteur.structure_id,
    )

    with transaction.atomic():
        dossier = Dossier.objects.create(
            reference=_reference_libre(aujourd_hui),
            objet=objet.strip(),
            type_dossier=libelle_type,
            demandeur=demandeur.strip(),
            contexte=contexte.strip() or None,
            montant=montant,
            criticite=libelle_criticite,
            structure_id=regle.structure_id if regle else acteur.structure_id,
            # L'instructeur nomme n'est pas devine : la regle designe une
            # structure, pas une personne. Le nommer au hasard aurait fait
            # porter un delai a quelqu'un qui l'ignore.
            instructeur=None,
            regle_affectation=regle,
            regle_affectation_texte=phrase,
            ouvert_le=aujourd_hui,
            echeance=terme,
            courrier_origine_id=courrier_id or None,
            courrier_origine_reference=courrier_reference.strip() or None,
            cree_par=acteur.pk,
        )
        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_ouvert",
            libelle=f"Dossier {dossier.reference} ouvert — {dossier.objet}",
            acteur=acteur,
            detail=(
                f"Échéance d'instruction au {terme.isoformat()}. "
                + (
                    f"Issu du courrier {courrier_reference.strip()}."
                    if courrier_reference.strip()
                    else "Dépôt direct, sans courrier d'origine."
                )
            ),
            donnees={"etapeApres": "qualification", "reference": dossier.reference},
        )
        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_affecte",
            libelle=f"Affecté à {dossier.structure.code}",
            acteur=acteur,
            detail=phrase,
        )
    return dossier


def affectation(
    *,
    type_dossier: str,
    criticite: str,
    montant: int | None,
    structure_par_defaut: int,
) -> tuple[RegleAffectation | None, str]:
    """
    Quelle regle s'applique, et la phrase qui l'explique — RF-BPM-02.

    **La plus specifique l'emporte**, la priorite departageant le reste : c'est
    la mecanique de `circuit_regle` au socle, et il n'y avait pas de raison d'en
    inventer une seconde.

    Une regle a seuil ne s'applique **pas** quand le dossier ne porte pas de
    montant. La reputer satisfaite aurait envoye au comite des engagements des
    dossiers dont personne n'a chiffre l'enjeu.

    Sans regle applicable, le dossier reste a la structure de celui qui
    l'ouvre, et la phrase le dit en toutes lettres. C'est moins bien qu'une
    regle, et c'est **visible** — ce qui vaut mieux qu'un rattachement invente.
    """
    candidates = [
        regle
        for regle in RegleAffectation.objects.filter(actif=True).select_related("structure")
        if (regle.type_dossier is None or regle.type_dossier == type_dossier)
        and (regle.criticite is None or regle.criticite == criticite)
        and (
            regle.montant_minimum is None
            or (montant is not None and montant >= regle.montant_minimum)
        )
    ]

    if not candidates:
        return (
            None,
            "Aucune règle d'affectation ne couvre ce dossier : il reste à la "
            "structure qui l'a ouvert. Le référentiel des règles se complète "
            "par l'administration.",
        )

    candidates.sort(key=lambda regle: (-regle.specificite, regle.priorite, regle.pk))
    retenue = candidates[0]
    return (retenue, retenue.libelle)


def _echeance(saisie: str, aujourd_hui: date) -> date:
    if not saisie:
        return aujourd_hui + timedelta(days=delai_instruction_defaut())
    try:
        terme = date.fromisoformat(saisie)
    except ValueError as erreur:
        raise ErreurMetier(
            "L'échéance est illisible : elle s'écrit AAAA-MM-JJ.",
            code="echeance_illisible",
        ) from erreur

    if terme < aujourd_hui:
        raise ErreurMetier(
            "L'échéance d'instruction est déjà passée : un dossier ne s'ouvre pas en retard.",
            code="echeance_passee",
        )
    return terme


def _reference_libre(jour: date) -> str:
    """
    La reference du dossier — `DOS-2026-0001`.

    Le compteur est celui de l'**exercice**, pas de la table : la numerotation
    d'un registre recommence chaque annee, c'est ce qu'attend l'agent qui
    cherche « le 47 de cette annee ». Le calcul se fait sous verrou de
    transaction par l'appelant ; deux ouvertures simultanees restent possibles
    en theorie, et la contrainte d'unicite de `reference` les arrete. Voir A39.
    """
    prefixe = f"DOS-{jour.year}-"
    derniere = (
        Dossier.objects.filter(reference__startswith=prefixe)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    rang = int(derniere.rsplit("-", 1)[1]) + 1 if derniere else 1
    return f"{prefixe}{rang:04d}"


def _code(referentiel: list[tuple[str, str]], demande: str, quoi: str) -> str:
    """
    Le code interne d'un libelle d'ecran, ou le code lui-meme s'il est deja
    interne. Les deux sont acceptes : le front envoie « Réclamation », un
    script d'import enverra `reclamation`, et refuser l'un des deux aurait
    oblige a un convertisseur de plus quelque part.
    """
    codes = {code for code, _ in referentiel}
    if demande in codes:
        return demande
    for code, libelle in referentiel:
        if libelle == demande:
            return code
    attendus = ", ".join(libelle for _, libelle in referentiel)
    raise ErreurMetier(
        f"Le {quoi} « {demande} » n'existe pas. Valeurs attendues : {attendus}.",
        code="valeur_hors_referentiel",
    )


# =====================================================================
#  Les complements
# =====================================================================


def demander_complement(
    acteur: Utilisateur, *, dossier_id: int, objet: str, echeance: str
) -> Complement:
    """
    Reclame une piece au demandeur.

    **Sans repousser l'echeance du dossier.** L'echeance saisie ici est celle
    donnee au demandeur ; les confondre offrirait a l'instructeur un moyen
    simple de n'etre jamais en retard, et le §3.7 dit l'inverse.
    """
    dossier = _dossier_ouvrable(acteur, dossier_id)

    if len(objet.strip()) < 5:
        raise ErreurMetier(
            "Précisez ce qui est demandé au demandeur.",
            code="complement_imprecis",
        )

    try:
        terme = date.fromisoformat(echeance)
    except ValueError as erreur:
        raise ErreurMetier(
            "L'échéance donnée au demandeur est illisible : elle s'écrit AAAA-MM-JJ.",
            code="echeance_illisible",
        ) from erreur

    with transaction.atomic():
        complement = Complement.objects.create(
            dossier=dossier,
            objet=objet.strip(),
            demande_le=date.today(),
            demande_par=acteur,
            echeance=terme,
            cree_par=acteur.pk,
        )
        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_complement_demande",
            libelle=f"Complément demandé — {complement.objet}",
            acteur=acteur,
            detail=(
                f"Réponse attendue du demandeur avant le {terme.isoformat()}. "
                f"L'échéance d'instruction du dossier reste fixée au "
                f"{dossier.echeance.isoformat()}."
            ),
            donnees={"complement": complement.pk},
        )
    return complement


def enregistrer_complement(acteur: Utilisateur, *, dossier_id: int, complement_id: int):
    """Note qu'une piece reclamee est arrivee."""
    dossier = _dossier_ouvrable(acteur, dossier_id)
    complement = dossier.complements.filter(pk=complement_id).first()
    if complement is None:
        raise ErreurMetier(
            "Ce complément n'appartient pas à ce dossier.",
            code="complement_etranger",
        )
    if complement.recu_le is not None:
        raise ErreurMetier(
            "Ce complément est déjà enregistré comme reçu.",
            code="complement_deja_recu",
        )

    with transaction.atomic():
        complement.recu_le = date.today()
        complement.save(update_fields=["recu_le"])
        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_complement_recu",
            libelle=f"Complément reçu — {complement.objet}",
            acteur=acteur,
            detail=(
                "Reçu hors délai."
                if complement.recu_le > complement.echeance
                else "Reçu dans le délai donné au demandeur."
            ),
        )
    return complement


# =====================================================================
#  Le retour a une etape anterieure
# =====================================================================


def retourner(acteur: Utilisateur, *, dossier_id: int, etape_cible: str, motif: str) -> Dossier:
    """
    Fait remonter le dossier a une etape anterieure — RF-BPM-06, §3.7.

    Trois refus, et chacun evite une facon de vider la regle de son sens :

     * *un motif vide ou trop court* laisse l'etape precedente deviner ;
     * *une etape qui n'est pas anterieure* n'est pas un retour, c'est une
       avancee deguisee — et l'avancee se decide a l'etape courante ;
     * *un dossier clos* ne se rouvre pas par cette porte. Rouvrir un dossier
       est une decision distincte, qui doit se voir comme telle.
    """
    dossier = _dossier_ouvrable(acteur, dossier_id)
    cible = _code_etape(etape_cible)

    minimum = longueur_minimale_motif()
    if len(motif.strip()) < minimum:
        raise ErreurMetier(
            "Le motif du retour doit dire ce qui manque ou ce qui est à reprendre — "
            f"{minimum} caractères au moins. « À revoir » n'en est pas un.",
            code="motif_insuffisant",
        )

    rang_courant = RANG_ETAPES[dossier.etape]
    if RANG_ETAPES[cible] >= rang_courant:
        raise ErreurMetier(
            f"« {LIBELLE_ETAPE[cible]} » n'est pas antérieure à "
            f"« {LIBELLE_ETAPE[dossier.etape]} » : ce ne serait pas un retour.",
            code="etape_non_anterieure",
        )

    etape_avant = dossier.etape

    with transaction.atomic():
        dossier.etape = cible
        dossier.modifie_par = acteur.pk
        dossier.modifie_le = timezone.now()
        dossier.save(update_fields=["etape", "modifie_par", "modifie_le"])

        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_retour_etape",
            libelle=(f"Retour de « {LIBELLE_ETAPE[etape_avant]} » à « {LIBELLE_ETAPE[cible]} »"),
            acteur=acteur,
            detail=motif.strip(),
            # Les deux etapes ensemble : c'est cette paire qui permet, six mois
            # plus tard, de reconstituer le chemin reel du dossier.
            donnees={"etapeAvant": etape_avant, "etapeApres": cible, "motif": motif.strip()},
        )
    return dossier


def _code_etape(demande: str) -> str:
    for code, libelle in LIBELLE_ETAPE.items():
        if demande in (code, libelle):
            return code
    raise ErreurMetier(
        f"L'étape « {demande} » n'existe pas dans le circuit d'instruction.",
        code="etape_inconnue",
    )


# =====================================================================
#  La fusion d'un courrier-type
# =====================================================================


def fusionner(
    acteur: Utilisateur, *, dossier_id: int, modele_id: int, valeurs: dict[str, str]
) -> dict:
    """
    Produit un projet de courrier a partir d'un modele — RF-SUI-05.

    **Une variable non fournie arrete la fusion.** Laisser `{demandeur}` en
    clair dans un courrier signe par le Directeur general est le genre
    d'incident qu'on ne repare pas ; refuser est desagreable une fois,
    l'inverse est humiliant une fois pour toutes.

    Le texte produit n'est pas stocke : il est rendu a l'ecran, qui en fait ce
    que l'agent decide. Le stocker aurait cree un document de plus dont
    personne n'aurait dit s'il est un projet ou un envoi.
    """
    dossier = _dossier_ouvrable(acteur, dossier_id)
    modele = ModeleCourrier.objects.filter(pk=modele_id, actif=True).first()
    if modele is None:
        raise ErreurMetier(
            "Ce modèle de courrier n'existe pas ou n'est plus en service.",
            code="modele_inconnu",
        )

    fournies = {cle: (valeur or "").strip() for cle, valeur in valeurs.items()}
    manquantes = [
        variable for variable in variables_du_corps(modele.corps) if not fournies.get(variable)
    ]
    if manquantes:
        raise ErreurMetier(
            "Le courrier ne peut pas être produit : "
            + ", ".join(manquantes)
            + " — chaque variable doit être renseignée, sinon elle partirait en clair.",
            code="variables_manquantes",
        )

    texte = modele.corps
    for variable, valeur in fournies.items():
        texte = texte.replace("{" + variable + "}", valeur)

    with transaction.atomic():
        modele.utilisations += 1
        modele.save(update_fields=["utilisations"])
        inscrire(
            objet_type="dossier",
            objet_id=dossier.pk,
            type_evenement="dossier_courrier_fusionne",
            libelle=f"Projet de réponse — {modele.libelle}",
            acteur=acteur,
            detail=f"Modèle {modele.code} fusionné avec {len(fournies)} variable(s).",
            donnees={"modele": modele.code},
        )

    return {"id": dossier.pk, "texte": texte, "modele": modele.code}


# =====================================================================
#  Le garde commun
# =====================================================================


def _dossier_ouvrable(acteur: Utilisateur, dossier_id: int) -> Dossier:
    """
    Le dossier, s'il est dans le perimetre **et** encore ouvert.

    404 et non 403 sur le perimetre : repondre « vous n'avez pas le droit »
    confirmerait l'existence du dossier et de son demandeur a qui n'a pas a les
    connaitre (D5).
    """
    from dossier.lecture import dossiers_visibles

    dossier = dossiers_visibles(acteur).filter(pk=dossier_id).first()
    if dossier is None:
        raise HorsPerimetre("Ce dossier n'existe pas ou n'est pas dans votre périmètre.")

    if dossier.etape == ETAPE_CLOS:
        raise ErreurMetier(
            "Ce dossier est clos : son instruction ne se reprend pas par ce geste.",
            code="dossier_clos",
        )
    return dossier
