"""
Qui voit quel courrier.

**C'est la piece la plus sensible du pilier.** Une erreur ici ne provoque aucun
plantage : elle montre a un agent un courrier qu'il n'a pas a lire, et personne
ne s'en apercoit. Toute lecture du pilier passe par `visibles()` — jamais par un
filtre recopie a la main.

La regle metier, telle que le client l'a enoncee le 11 aout 2026 :

    « On voit ce a quoi on est rattache — sa structure, plus ce sur quoi on a ete
      cote ou designe. Tout le reste est invisible, sauf permission explicite de
      consolidation. »

`noyau.perimetre.portee.restreindre()` ne tient **qu'une** de ces portes : le
rattachement par la structure. Les deux autres sont particulieres au courrier et
sont ecrites ici, avec les tables qu'elles interrogent. C'est ce que la docstring
de `noyau/perimetre/designation.py` annoncait.

Quatre portes, et non trois : la **session** en est une, et elle n'est pas dans
la phrase du client parce qu'elle ne releve pas de la meme question. Voir
l'[ADR 022].

    | Porte          | Ce qu'elle ouvre                                        |
    |----------------|---------------------------------------------------------|
    | Session        | le registre de sa session — c'est ce qu'est un registre  |
    | Rattachement   | ce que porte sa structure, selon la portee              |
    | Cotation       | ce courrier precis, meme venu d'ailleurs                |
    | Designation    | ce qu'on suit ou ce qui nous est affecte, hors structure |

Et **une serrure** par-dessus, qui ne s'ouvre pas par les portes :
`courrier.confidentiel` exige la permission `CONF` — « Acceder aux courriers
confidentiels », c'est le libelle de la permission au socle. Un courrier
confidentiel disparait donc des listes de qui ne la porte pas, y compris en
portee `toutes` : la consolidation ne vaut pas levee du secret (decision D5).

**Une exception, et une seule** : l'agent rattache au registre confidentiel lit
ce registre. Le rattachement y est l'acte d'habilitation. Sans cette exception
il enregistrerait un courrier qu'il ne peut plus relire — voir l'ADR 024,
`la serrure du confidentiel ne ferme pas son propre registre`.

**Un courrier hors perimetre repond 404, jamais 403.** Repondre « interdit »
confirmerait l'existence du courrier et celle de son expediteur a qui n'a pas a
les connaitre. Decision D5, et c'est pour cela que `fiche()` leve
`HorsPerimetre`.

[ADR 022]: ../backend/docs/architecture/022-le-registre-est-une-porte-de-visibilite.md
"""

from django.db import models

from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.perimetre.modeles import PORTEE_PROPRE, PORTEE_TOUTES
from noyau.perimetre.portee import perimetre_en_vigueur, structures_visibles

# Le code de la session confidentielle, tel que la contrainte
# `session_code_valide` du socle l'enumere.
CODE_SESSION_CONFIDENTIEL = "confidentiel"


def session_en_cours(utilisateur: Utilisateur) -> SessionCourrier | None:
    """
    La session a laquelle l'agent est rattache aujourd'hui, s'il en a une.

    **La plupart des agents n'en ont aucune**, et c'est normal : la session est le
    registre du service courrier, pas un axe d'habilitation general. Un directeur
    n'est rattache a aucune session et voit pourtant les courriers cotes a sa
    direction — par une autre porte.

    Le rattachement est exclusif, garanti par une contrainte d'exclusion du
    moteur. `first()` ne masque donc pas un choix : il n'y a qu'une ligne.
    """
    rattachement = (
        UtilisateurSession.objects.filter(utilisateur=utilisateur, retire_le__isnull=True)
        .select_related("session")
        .first()
    )
    return rattachement.session if rattachement else None


def visibles(requete: models.QuerySet, utilisateur: Utilisateur) -> models.QuerySet:
    """
    Restreint une requete de courriers a ce que l'agent peut voir.

    L'ordre des trois etapes n'est pas indifferent : la serrure du confidentiel
    est posee **avant** les portes, pour qu'aucune porte ne puisse l'ouvrir.

    `distinct()` est indispensable et non cosmetique : les portes traversent
    `cotation_structure` et `affectation`, et un courrier cote a trois structures
    visibles sortirait trois fois — donc compte trois fois dans le total du
    registre.
    """
    perimetre = perimetre_en_vigueur(utilisateur)
    session = session_en_cours(utilisateur)

    requete = _serrure_du_confidentiel(requete, utilisateur, session)

    # Aucun perimetre et aucune session : on ne montre rien. C'est la regle 3 de
    # `portee.py` — en cas de doute, ne rien montrer — et elle vaut ici aussi.
    if perimetre is None and session is None:
        return requete.none()

    # La consolidation. `restreindre()` la traite de la meme facon : la portee
    # `toutes` ne pose aucun filtre de structure. La serrure du confidentiel,
    # elle, reste posee.
    if perimetre is not None and perimetre.portee == PORTEE_TOUTES:
        return requete

    portes = _porte_session(session) | _porte_designation(utilisateur)

    if perimetre is not None and perimetre.portee != PORTEE_PROPRE:
        structures = structures_visibles(utilisateur)
        # `None` signifie « aucun filtre » et n'arrive qu'en portee `toutes`,
        # traitee plus haut. Le test reste, parce qu'un `__in=None` passerait
        # silencieusement.
        if structures is not None:
            portes |= _porte_rattachement(structures) | _porte_cotation(structures)

    return requete.filter(portes).distinct()


def voit(utilisateur: Utilisateur, courrier_id: int) -> bool:
    """
    L'agent voit-il ce courrier precis ?

    Ecrit avec `visibles()` et non avec une seconde regle : deux regles
    divergeraient, et c'est celle qui protege le moins qui finirait par
    s'appliquer.
    """
    from courrier.modeles import Courrier

    return visibles(Courrier.objects.filter(pk=courrier_id), utilisateur).exists()


# =====================================================================
#  Les portes, une par une
# =====================================================================


def _serrure_du_confidentiel(
    requete: models.QuerySet, utilisateur: Utilisateur, session: SessionCourrier | None
) -> models.QuerySet:
    """
    Ecarte les courriers confidentiels de qui ne porte pas `CONF`.

    Le filtrage se fait **en base**, jamais a l'affichage : c'est exactement ce
    que dit la decision D5, et la raison vaut au-dela du courrier — un total
    calcule sur des lignes qu'on masque ensuite reste faux.

    `sens` et `confidentiel` sont deux colonnes distinctes : un courrier
    confidentiel entrant est a la fois arrive et confidentiel. La serrure porte
    sur la seconde, jamais sur la premiere.

    **La serrure ne ferme pas son propre registre.** L'agent rattache a la
    session confidentielle lit les courriers de cette session, meme sans porter
    `CONF` : sans cela il enregistrerait un courrier qu'il ne peut plus relire —
    le registre confidentiel serait intenable, et aucun profil du socle ne cumule
    `ENR` et `CONF`. Le rattachement a ce registre **est** l'acte d'habilitation ;
    il est exclusif, administre, et le socle lui accorde deja `lit_toutes_sessions`.
    Voir l'ADR 024, qui complete l'ADR 022 sans la contredire.

    Ce que la serrure continue d'interdire est exactement ce qu'elle visait : la
    portee `toutes` consolide sans lever le secret, et un agent d'un autre
    registre ne voit rien.
    """
    if possede(utilisateur, PERM.CONF):
        return requete
    if session is not None and session.code == CODE_SESSION_CONFIDENTIEL:
        return requete.exclude(models.Q(confidentiel=True) & ~models.Q(session_id=session.pk))
    return requete.exclude(confidentiel=True)


def _porte_session(session: SessionCourrier | None) -> models.Q:
    """
    Le registre de sa session — la porte du service courrier.

    Un agent rattache au registre « Arrivee » voit les arrivees : c'est ce qu'est
    un registre, et sans cette porte le courrier qu'il vient d'enregistrer lui
    serait invisible jusqu'a sa cotation. L'onglet « Non cotes » serait vide par
    construction.

    `lit_toutes_sessions` leve le cloisonnement — la session confidentielle est
    la seule a le porter au socle. La propriete est en **donnee** et non en code
    pour pouvoir etre retiree sans developpement (§4.2 : « selon les habilitations
    definies »).

    Les deux Q extremes sont ecrits **en dur** et non avec `Q()` vide :

    - `Q(pk__in=[])` ferme la porte sans fermer les autres — faux, neutre dans
      un `|` ;
    - `Q(pk__isnull=False)` l'ouvre en grand. `Q()` vide aurait paru plus
      naturel, mais Django l'**absorbe** : `Q() | Q(x=1)` vaut `Q(x=1)`, et non
      « tout ». La porte grande ouverte se serait donc refermee en silence des
      qu'une autre porte figurait dans le meme `|` — c'est exactement ce qui
      rendait le registre confidentiel invisible a l'agent qui le tient.
    """
    if session is None:
        return models.Q(pk__in=[])
    if session.lit_toutes_sessions:
        return models.Q(pk__isnull=False)
    return models.Q(session_id=session.pk)


def _porte_rattachement(structures: models.QuerySet) -> models.Q:
    """
    Le chef de file releve d'une structure visible.

    `structure_chef_file_id` est denormalise depuis `cotation_structure` de
    rang 1 par un declencheur du socle. La porte l'utilise pour ce qu'il est —
    un raccourci de tri — et la porte suivante couvre les co-traitantes, que
    cette colonne ne nomme pas.
    """
    return models.Q(structure_chef_file__in=structures)


def _porte_cotation(structures: models.QuerySet) -> models.Q:
    """
    Une structure visible a ete cotee, a n'importe quel rang.

    Le rang n'entre pas dans la condition : une co-traitante de rang 3 lit le
    courrier qu'elle doit traiter aussi bien que le chef de file. Ce que le rang
    decide est **qui coordonne**, pas qui voit.

    Une cotation invalidee n'ouvre plus rien : elle reste au registre comme trace
    de la decision, elle ne donne plus a lire.
    """
    return models.Q(
        cotations__invalide_le__isnull=True,
        cotations__structures__structure__in=structures,
    )


def _porte_designation(utilisateur: Utilisateur) -> models.Q:
    """
    Ce que l'agent suit, et ce qui lui est affecte — **meme hors de sa structure**.

    C'est la raison d'etre de cette porte. La personne de la cotation pour suivi
    coordonne au-dessus du chef de file et rend compte au Directeur general ; elle
    vient souvent d'une autre direction, et aucune autre porte ne l'ouvrirait.
    Meme chose pour l'agent affecte : c'est lui qui traite.

    Seules les designations et affectations **ouvertes** ouvrent un acces. Une
    designation retiree laisse sa trace au registre — savoir qui suivait le
    courrier le jour ou une relance est partie est tout l'objet de la table — mais
    elle ne donne plus a voir. Sans quoi un agent qui a suivi un courrier il y a
    trois ans le verrait encore.
    """
    suivi = models.Q(
        cotations__invalide_le__isnull=True,
        cotations__suivis__utilisateur=utilisateur,
        cotations__suivis__retire_le__isnull=True,
    )
    affectation = models.Q(
        cotations__invalide_le__isnull=True,
        cotations__structures__affectations__utilisateur=utilisateur,
        cotations__structures__affectations__retire_le__isnull=True,
    )
    return suivi | affectation
