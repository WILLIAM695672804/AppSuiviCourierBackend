"""
Routes du portail usagers — `/api/portail/*`.

Quatre lectures et trois ecritures, toutes gardees par `EXT` — la permission du
profil `EXTERNE`, et d'aucun autre. Un agent du port n'ouvre pas le portail : ce
qu'il a a savoir d'une demande, il le lit du cote instruction, avec les mots de
l'institution et le perimetre qui va avec.

**`restreindre()` n'apparait pas, et c'est deliberé.** La restriction du socle
porte sur la structure et l'agent ; un usager n'appartient a aucune structure du
port. Le filtre est `deposant=utilisateur`, ecrit dans `lecture.demandes_de()`,
par ou passe **toute** lecture de ce pilier. Voir ADR 013 — c'est la seule
derogation a la regle « une route qui rend des donnees appelle `restreindre()` »,
et elle est plus stricte que la regle, pas plus laxiste.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige
from portail import lecture, services
from portail.schemas import (
    Creation,
    DemandeUsagerDetail,
    Echanges,
    MesDemandes,
    Preferences,
    SaisieDemande,
    SaisieMessage,
    SaisiePreferences,
)

routeur = Router()


@routeur.get("/demandes", response=MesDemandes, auth=exige(PERM.EXT))
def mes_demandes(request):
    """
    « Mes demandes », en cartes.

    Ce qu'on attend de l'usager passe en tete. Le delai de reponse voyage avec
    la liste : c'est lui que le formulaire de depot annonce, et il n'a pas a
    etre ecrit deux fois.
    """
    return lecture.mes_demandes(request.auth)


@routeur.get("/demandes/{int:identifiant}", response=DemandeUsagerDetail, auth=exige(PERM.EXT))
def suivi_demande(request, identifiant: int):
    """
    Le suivi d'une demande : frise expliquee, messages, pieces.

    404 quand la demande appartient a quelqu'un d'autre. Un 403 confirmerait son
    existence, et sur un portail ouvert au public cela permettrait d'enumerer
    les demandes de l'institution une reference a la fois (D5).
    """
    return lecture.demande(request.auth, identifiant)


@routeur.post("/demandes", response={201: Creation}, auth=exige(PERM.EXT))
def deposer(request, saisie: SaisieDemande):
    """
    Depose une demande — cinq champs, pas un de plus.

    La date de reponse est calculee ici et figee sur la demande : c'est ce que
    l'institution a promis ce jour-la.
    """
    demande = services.deposer_demande(
        request.auth,
        type_demande=saisie.type,
        objet=saisie.objet,
        contexte=saisie.contexte,
        pieces=[piece.dict() for piece in saisie.pieces],
    )
    return 201, {"id": demande.pk}


@routeur.post(
    "/demandes/{int:identifiant}/messages", response={201: Creation}, auth=exige(PERM.EXT)
)
def repondre(request, identifiant: int, saisie: SaisieMessage):
    """
    Repond sur une demande, avec ses pieces eventuelles.

    Le chemin porte l'identifiant et le corps le porte aussi : c'est le chemin
    qui fait foi. Le front construit les deux, et faire confiance au corps
    aurait permis d'ecrire sur une demande en en nommant une autre.
    """
    message = services.repondre(
        request.auth,
        demande_id=identifiant,
        texte=saisie.texte,
        pieces=[piece.dict() for piece in saisie.pieces],
    )
    return 201, {"id": message.pk}


@routeur.get("/preferences", response=Preferences, auth=exige(PERM.EXT))
def preferences(request):
    """
    Le canal de notification et les evenements retenus.

    Une consultation n'ecrit rien : l'absence de reglage rend les valeurs par
    defaut, elle ne les cree pas.
    """
    return lecture.preferences(request.auth)


@routeur.post("/preferences", response={201: Creation}, auth=exige(PERM.EXT))
def enregistrer_preferences(request, saisie: SaisiePreferences):
    """
    Enregistre le canal et les evenements — RF-SUI-03.

    Les deux notifications obligatoires sont rallumees par le serveur, quoi que
    porte la requete.
    """
    reglage = services.enregistrer_preferences(
        request.auth,
        courriel=saisie.courriel,
        telephone=saisie.telephone,
        canal=saisie.canal,
        evenements=saisie.evenements,
    )
    return 201, {"id": reglage.pk}


@routeur.get("/echanges", response=Echanges, auth=exige(PERM.EXT))
def echanges(request):
    """Marches publics, conventions et reportings ouverts a ce partenaire."""
    return lecture.echanges(request.auth)
