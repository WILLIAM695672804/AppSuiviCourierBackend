"""
Point de montage de l'API.

Un seul objet `NinjaAPI`, sur lequel chaque pilier vient accrocher son
routeur. L'ordre de montage n'a pas d'importance : les chemins ne se
recouvrent pas d'un pilier a l'autre.

Deux conventions y sont posees une fois pour toutes, et valent pour tous
les piliers :

 1. **Sortie en camelCase.** Le front porte des interfaces TypeScript ecrites
    a la main (`avancementAttendu`, `structureSigle`). La base, elle, est en
    snake_case. Les schemas Ninja sont le seul endroit ou les deux se
    croisent — et il vaut mieux que ce soit un seul endroit.

 2. **Erreurs uniformes.** `frontend/src/lib/erreurApi.ts` attend un corps
    JSON portant `message`. Toute erreur qui n'a pas cette forme s'affiche
    a l'agent comme « Le serveur n'a pas pu traiter la demande. », ce qui ne
    lui apprend rien.
"""

from django.http import HttpRequest, JsonResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from noyau.erreurs import ErreurMetier

api = NinjaAPI(
    title="Plateforme de suivi — Port autonome de Douala",
    version="0.1.0",
    description=(
        "Suivi des courriers, des activites des structures et de la gouvernance. "
        "Les codes d'exigence cites dans les descriptions renvoient au cahier des "
        "charges fonctionnel (§) et au BRD (RF-/RNF-)."
    ),
    # La protection CSRF n'est pas un reglage de l'API : depuis Ninja 1.0,
    # elle est portee par la classe d'authentification. `SessionAuth` — dont
    # herite notre garde `ExigePermission` — l'active par defaut. Le front
    # envoie le cookie de session ; le jeton CSRF est donc exige.
)


@api.exception_handler(ErreurMetier)
def erreur_metier(requete: HttpRequest, exc: ErreurMetier) -> JsonResponse:
    """
    Une regle de gestion refuse l'ecriture.

    Ce n'est pas un defaut de saisie mais un etat du systeme : declarer un
    avancement sur une activite suspendue, soumettre un plan deja soumis. Le
    front affiche le message tel quel — il doit donc etre ecrit pour l'agent,
    pas pour le journal.
    """
    return JsonResponse({"message": str(exc), "code": exc.code}, status=exc.statut)


@api.exception_handler(AuthenticationError)
def non_authentifie(requete: HttpRequest, exc: Exception) -> JsonResponse:
    # 401 et non 403 : le garde `ExigeSession` du front renvoie a l'ecran de
    # connexion en retenant la destination. Un 403 le ferait echouer sans le dire.
    return JsonResponse({"message": "Session expiree ou absente."}, status=401)


@api.exception_handler(ValidationError)
def saisie_invalide(requete: HttpRequest, exc: ValidationError) -> JsonResponse:
    return JsonResponse(
        {"message": "La saisie comporte des erreurs.", "details": exc.errors},
        status=422,
    )


# ---------------------------------------------------------------------
#  Montage des routeurs
#
#  Chaque pilier expose un `routeur` dans son `api.py`. On l'ajoute ici,
#  et nulle part ailleurs.
# ---------------------------------------------------------------------
from activite.api import routeur as routeur_activite  # noqa: E402
from archivage.api import routeur as routeur_archivage  # noqa: E402
from courrier.api import routeur as routeur_courrier  # noqa: E402
from courrier.api import (  # noqa: E402
    routeur_accuses,
    routeur_compteurs,
    routeur_signalements,
    routeur_suivi,
)
from dossier.api import routeur as routeur_dossier  # noqa: E402
from exploitation.api import routeur as routeur_exploitation  # noqa: E402
from gouvernance.api import routeur as routeur_gouvernance  # noqa: E402
from noyau.administration.api import routeur as routeur_administration  # noqa: E402
from noyau.habilitation.api import routeur as routeur_habilitation  # noqa: E402
from noyau.identite.api import routeur as routeur_identite  # noqa: E402
from noyau.notifications.api import routeur as routeur_notifications  # noqa: E402
from noyau.organisation.api import routeur as routeur_referentiel  # noqa: E402
from noyau.organisation.api_administration import routeur as routeur_organisation  # noqa: E402
from noyau.parametrage.api import routeur as routeur_parametrage  # noqa: E402
from noyau.parametrage.api_referentiel import (  # noqa: E402
    routeur as routeur_referentiel_metier,
)
from noyau.pieces.api import routeur as routeur_pieces  # noqa: E402
from noyau.tracabilite.api import routeur as routeur_tracabilite  # noqa: E402
from performance.api import routeur as routeur_performance  # noqa: E402
from pilotage.api import routeur as routeur_pilotage  # noqa: E402
from pilotage.api import routeur_comite, routeur_direction  # noqa: E402
from portail.api import routeur as routeur_portail  # noqa: E402
from supervision.api import routeur as routeur_supervision  # noqa: E402

# Les routes de session sont montees a la RACINE de l'API, et non sous
# `/auth` : le front appelle `/api/connexion`, `/api/deconnexion` et
# `/api/moi`. Le prefixe eut ete plus joli ; il aurait aussi fallu le
# corriger le jour du branchement, et un decalage de chemin ne se voit
# qu'a l'execution.
api.add_router("", routeur_identite, tags=["Identite"])
api.add_router("/habilitations", routeur_habilitation, tags=["Habilitation"])

# Le referentiel de l'organigramme n'appartient a aucun pilier : sept ecrans de
# quatre domaines le lisent. Il est monte a part, et sa garde est large — ADR 007.
api.add_router("/referentiels", routeur_referentiel, tags=["Referentiels"])

# Second routeur sur le meme prefixe, et non trois routes de plus dans le
# precedent : natures, mentions et correspondants relevent du **parametrage
# metier**, dont l'ecriture reste sous `ADM_PAR`. Leur lecture est large pour une
# raison qui leur est propre — un agent qui enregistre un courrier doit choisir
# sa nature et son expediteur — et non par extension de l'ADR 007.
api.add_router("/referentiels", routeur_referentiel_metier, tags=["Referentiels"])

# L'administration de l'organigramme est un autre routeur sur les memes tables :
# la lecture est large (ADR 007), l'ecriture exige `ADM_ORG`. Les monter ensemble
# aurait ouvert l'ecriture a toute session authentifiee.
api.add_router("/organisation", routeur_organisation, tags=["Organisation"])

# La tracabilite est en lecture seule, sous `AUDIT`. La conformite
# archivistique part avec elle mais se monte sous `/archivage` : l'auditeur et
# l'archiviste regardent la meme matiere, et le front ne doit pas dependre du
# domaine de l'autre pour l'obtenir.
# L'accueil de l'administration lit les journaux, l'annuaire et l'organigramme
# a la fois. Sa garde accepte l'une quelconque des permissions d'administration
# ou d'audit, et c'est le contenu de la reponse qui est filtre selon ce que le
# compte porte — un seul ecran d'accueil pour quatre postes distincts.
api.add_router("/administration", routeur_administration, tags=["Administration"])

# Le parametrage metier est en lecture seule sous `ADM_PAR`. Une seule route
# pour huit onglets : les referentiels sont petits et l'administrateur passe de
# l'un a l'autre sans arret.
api.add_router("/parametrage", routeur_parametrage, tags=["Parametrage"])

api.add_router("/tracabilite", routeur_tracabilite, tags=["Tracabilite"])

# Les pieces jointes sont **generiques** : une seule route de depot sert tous
# les piliers. Sa garde ne peut pas s'ecrire dans le decorateur — la permission
# depend de l'objet auquel on rattache — et est portee en entier par le service.
# Voir ADR 017.
api.add_router("/pieces", routeur_pieces, tags=["Pieces jointes"])

# Les notifications d'un agent ne dependent d'aucune permission : elles lui sont
# adressees. Le filtre est le destinataire, comme le portail filtre par
# deposant (ADR 013). Seul l'etat de la file, qui est de l'exploitation, exige
# `ADM_PAR`.
api.add_router("/notifications", routeur_notifications, tags=["Notifications"])

# La matrice de scoring se lit sous `SCORE` et s'administre sous `SCORE_ADM` :
# consulter un classement et changer la regle qui le produit ne sont pas le
# meme geste. Les deux gardes vivent dans le meme routeur, route par route.
api.add_router("/performance", routeur_performance, tags=["Performance"])

# Le pilier courrier. Sa restriction de perimetre ne passe pas par
# `restreindre()` seul : `courrier.visibilite.visibles()` l'englobe et y ajoute
# trois portes — la session d'enregistrement, la cotation et la designation
# (ADR 022). C'est le seul pilier dans ce cas, parce que c'est le seul dont un
# objet circule d'une structure a l'autre.
api.add_router("/courriers", routeur_courrier, tags=["Courriers"])

# Les compteurs de la barre laterale sont montes a la RACINE : le front appelle
# `/api/compteurs`. Meme raison que les routes de session — le chemin qu'appelle
# le front n'est pas negociable, et un decalage ne se voit qu'a l'execution.
api.add_router("", routeur_compteurs, tags=["Courriers"])

# Le cahier de decharge (A-11) et le registre des ecarts (A-12), a la racine
# eux aussi : le front appelle `/api/accuses` et `/api/signalements`. Ils ne
# vivent pas sous `/courriers` parce qu'ils ne portent pas sur UN courrier — ce
# sont deux registres transverses, l'un des plis remis, l'autre des incidents.
api.add_router("", routeur_accuses, tags=["Courriers"])
api.add_router("", routeur_signalements, tags=["Courriers"])

# Le pilier suivi — la corbeille de celui qui instruit et le tableau de celui
# qui relance. Distinct de `/courriers`, qui est le registre, et de `/dossiers`,
# qui est le registre des dossiers a instruire. Seul `GET /suivi/relance` est
# servi a ce jour ; les sept autres routes que le front appelle sont enumerees
# dans `docs/etat-de-l-application.md`.
api.add_router("/suivi", routeur_suivi, tags=["Suivi et relance"])

api.add_router("/activites", routeur_activite, tags=["Activites"])
api.add_router("/gouvernance", routeur_gouvernance, tags=["Gouvernance"])

# L'exploitation mesure le port lui-meme — des metres et des francs — la ou les
# autres piliers mesurent le travail administratif. Un domaine a part pour cette
# raison : rien ne se calcule de l'un vers l'autre, et les confondre aurait fini
# par faire entrer une profondeur de chenal dans une moyenne de delais.
api.add_router("/exploitation", routeur_exploitation, tags=["Exploitation"])

# Les dossiers a instruire — le perimetre pilote du BRD (§6.1). Monte a la
# racine sous `/dossiers` et non sous un prefixe de pilier : c'est le chemin
# qu'appelle le front, et un decalage de chemin ne se voit qu'a l'execution.
api.add_router("/dossiers", routeur_dossier, tags=["Dossiers"])

# L'archivage suit les dossiers, et il est monte apres eux : un versement porte
# un dossier clos. `/archivage/conformite` a longtemps vecu dans le socle, qui
# rendait des compteurs vides faute de pilier ; la route est ici depuis que le
# fonds existe.
api.add_router("/archivage", routeur_archivage, tags=["Archivage"])

# Le pilotage n'ecrit rien : il restitue ce que les autres piliers enregistrent.
# Trois gardes y cohabitent — `COCKPIT`, `ACT_LEC`, `STAT` — parce que le
# cockpit du Directeur general, le tableau de bord d'un chef de service et les
# analyses du controle de gestion ne s'ouvrent pas aux memes.
api.add_router("/pilotage", routeur_pilotage, tags=["Pilotage"])

# Deux domaines a part, et non deux routes de plus dans `pilotage` : ces
# restitutions n'appartiennent qu'a une instance chacune. Les ranger ensemble
# aurait fini par les faire evoluer ensemble, ce qui est exactement ce qu'on
# veut eviter — la vue du Directeur general repond a « ou en est
# l'institution ? », celle du Comite a « ou se situent les directions ? ».
api.add_router("/direction", routeur_direction, tags=["Direction generale"])
api.add_router("/comite", routeur_comite, tags=["Comite de direction"])

# Le portail usagers est le seul domaine atteint par des comptes exterieurs a
# l'institution. Sa garde est `EXT`, portee par le seul profil `EXTERNE` : un
# agent du port n'ouvre pas le portail, il lit la meme demande du cote
# instruction, avec les mots de l'institution et le perimetre qui va avec.
api.add_router("/portail", routeur_portail, tags=["Portail usagers"])

# La supervision technique est montee sur `/supervision` — et sa route
# principale porte le chemin vide, `GET /api/supervision`. C'est ce qu'appelle
# le front. Elle ne restreint rien : la plateforme n'appartient a aucune
# structure, et sa disponibilite ne se decline pas par direction.
api.add_router("/supervision", routeur_supervision, tags=["Supervision"])
