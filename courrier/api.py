"""
Routes du pilier courrier — §3.4 a §3.6, §10.

**Aucune regle metier ici.** Chaque route valide sa garde, delegue a `lecture.py`
ou a `services.py`, et rend. Une regle ecrite dans une route ne s'applique qu'a
cette route ; la deuxieme voie d'ecriture la contournerait sans que rien ne le
signale.

**La restriction de perimetre passe par `visibilite.visibles()`, et elle est
posee dans `lecture.py`.** C'est la seule entorse apparente a la consigne « une
route appelle `restreindre()` des qu'elle renvoie des donnees » : `visibles()`
englobe `restreindre()` et y ajoute trois portes (ADR 022). L'appeler ici en plus
n'ajouterait rien et donnerait a croire qu'une lecture peut s'en passer.

Ce qui n'est **pas** monte, et pourquoi :

 * `GET /courriers/import` et la file d'interception d'e-mails — le Port a dit
   le 26 aout 2026 : « pas d'import d'e-mail pour le moment ». L'ecran a ete
   retire du front le meme jour plutot que laisse en 404 ;
 * toute route de **validation hierarchique** ou de transmission de circuit —
   elles sont ancrees sur `circuit_etape`, qui reste vide. Le trajet decrit par
   le Port n'en comporte aucune : le responsable de structure cloture, et
   l'ADR 034 dit pourquoi cela ne se paramètre pas.

Ce qui a ete monte le 26 aout 2026, et qui repondait 404 jusque-la : le cahier
de decharge (`GET /accuses`, `POST …/affectations/{id}/accuse`), le fil
d'observations (`POST …/observations`) et le signalement d'ecart
(`GET /signalements`, `POST …/signalements`, `POST /signalements/{id}/etat`).

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from django.http import HttpResponse
from ninja import Router

from courrier import bureau_ordre, documents, lecture, relance, services, suivi, supervision
from courrier.schemas import (
    BilanRelance,
    CarteBlocages,
    Compteurs,
    ContexteEnregistrement,
    CourrierDetail,
    CriteresRecherche,
    DossierTraitement,
    FicheVie,
    IndicateursRegistre,
    LigneDecharge,
    LignePassage,
    NoteDossier,
    PageCourriers,
    PortefeuilleAgent,
    RechercheEnregistreeLue,
    ResultatRecherche,
    SaisieAffectation,
    SaisieAvancementSignalement,
    SaisieBasculeTache,
    SaisieCloture,
    SaisieCorrection,
    SaisieCotation,
    SaisieDecharge,
    SaisieDecisionDelai,
    SaisieDemandeDelai,
    SaisieEnregistrement,
    SaisieNote,
    SaisieObservation,
    SaisieProlongation,
    SaisieRechercheEnregistree,
    SaisieRelance,
    SaisieRetourTraitement,
    SaisieSignalement,
    SaisieSortie,
    SaisieTache,
    SaisieTraitement,
    SignalementLu,
    TableauRelance,
    TacheDossier,
)
from noyau.documents import sortie
from noyau.habilitation.dependances import PERM, exige, session_seule
from noyau.journal.service import tracer_acces

routeur = Router()

#: Le cahier de decharge et le registre des ecarts sont montes a la **racine** de
#: l'API : le front appelle `/api/accuses` et `/api/signalements`. Meme raison que
#: pour les compteurs — le chemin qu'appelle le front n'est pas negociable, et un
#: decalage de chemin ne se voit qu'a l'execution.
routeur_accuses = Router()
routeur_signalements = Router()

#: Les compteurs de la barre laterale sont montes a la **racine** de l'API :
#: le front appelle `/api/compteurs`. Un routeur a part pour cette seule raison —
#: le chemin qu'appelle le front n'est pas negociable, et un decalage de chemin ne
#: se voit qu'a l'execution.
routeur_compteurs = Router()

#: Le pilier suivi, monte sur `/api/suivi`. Il porte la **corbeille de celui qui
#: instruit ou qui relance**, la ou `/courriers` porte le registre : deux
#: questions differentes sur la meme matiere, et le front les a toujours
#: separees. A ne pas confondre avec `/dossiers`, qui est le registre des
#: dossiers a instruire.
#:
#: Le pilier est **entier depuis le 28 aout 2026** : tableau de relance (C-02),
#: portefeuille et dossier de traitement (C-01), recherche avancee et recherches
#: conservees (A-14). Il repondait 404 en bloc jusque-la — le front appelait onze
#: routes qui n'existaient pas, et l'ecran de portefeuille affichait « les delais
#: sont tenus » sur l'erreur.
routeur_suivi = Router()


# ---------------------------------------------------------------------
#  Registre — A-02
# ---------------------------------------------------------------------


@routeur.get("", response=PageCourriers, auth=exige(PERM.LEC))
def lister_courriers(
    request,
    sens: str = "ARRIVEE",
    vue: str = "tous",
    q: str = "",
    page: int = 1,
):
    """
    Le registre des courriers, filtre et pagine.

    Les sept valeurs de `vue` sont des **filtres, pas des etapes** : « Non cotés »
    et « Hors délai » peuvent designer le meme courrier, ce qu'une suite d'etapes
    interdirait.

    `aAffecter` est la file du responsable de structure : cote a l'une de ses
    structures, et pas encore affecte a une personne chez lui.

    `q` cherche dans le numero, l'expediteur et l'objet, sans sensibilite aux
    accents — « delegation » trouve « délégation ».
    """
    return lecture.registre(request.auth, sens=sens, vue=vue, recherche=q, page=page)


@routeur.get("/indicateurs", response=IndicateursRegistre, auth=exige(PERM.LEC))
def indicateurs_registre(request, sens: str = "ARRIVEE"):
    """
    Les quatre indicateurs du bandeau du registre.

    Tous bornes au perimetre de l'appelant : un compteur calcule hors perimetre
    est une fuite discrete — le nombre dit quelque chose meme quand la liste est
    fermee.

    `variation` et `serie` sortent a « Non mesuré » et vides : la variation
    suppose une periode de reference et la serie un historique que rien n'archive.
    ADR 011.
    """
    return lecture.indicateurs(request.auth, sens=sens)


# ---------------------------------------------------------------------
#  Enregistrement — A-01
# ---------------------------------------------------------------------


@routeur.get("/contexte", response=ContexteEnregistrement, auth=exige(PERM.ENR))
def contexte_enregistrement(request):
    """
    Le numero prevu et l'horodatage d'arrivee, avant toute saisie.

    Le numero est **predit, jamais reserve** : il est lu dans
    `sequence_numerotation` sans l'incrementer. Reserver un numero a l'ouverture
    d'un formulaire aurait troue la sequence des le premier abandon de saisie — et
    un registre a trous est un registre qu'on ne peut plus certifier.

    Declaree **avant** `/{identifiant}` : l'ordre de declaration est celui de la
    resolution, et `contexte` n'est pas un entier — mais ne pas dependre de cette
    coincidence coute une ligne de commentaire.
    """
    return lecture.contexte_enregistrement(request.auth)


@routeur.post("", response={201: CourrierDetail}, auth=exige(PERM.ENR))
def enregistrer_courrier(request, saisie: SaisieEnregistrement):
    """
    Inscrit un courrier au registre — §4.2.

    Rend la **fiche complete** et non le seul identifiant : l'ecran A-01 redirige
    vers la fiche, et un second aller-retour aurait affiche un ecran vide le temps
    de la charger.
    """
    courrier = services.enregistrer(saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, courrier.pk)


# ---------------------------------------------------------------------
#  Fiche — A-03
# ---------------------------------------------------------------------


@routeur.get("/{int:identifiant}", response=CourrierDetail, auth=exige(PERM.LEC))
def lire_courrier(request, identifiant: int):
    """
    La fiche d'un courrier.

    Un courrier hors perimetre repond **404**, jamais 403 : repondre « interdit »
    confirmerait l'existence du courrier et celle de son expediteur a qui n'a pas
    a les connaitre. Decision de cadrage D5.
    """
    return lecture.fiche(request.auth, identifiant)


@routeur.get("/{int:identifiant}/fiche-de-vie", response=FicheVie, auth=exige(PERM.LEC))
def lire_fiche_de_vie(request, identifiant: int):
    """
    La fiche de vie — A-06. Le journal du courrier, redige pour etre lu.

    Sous `LEC` et non sous `AUDIT` : ce n'est pas de la tracabilite technique mais
    une piece du dossier, que l'agent qui traite le courrier joint a sa reponse.
    Le journal complet, lui, reste sous `AUDIT` dans `/tracabilite`.
    """
    return lecture.fiche_de_vie(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Cotation — A-04
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/cotations",
    response={201: CourrierDetail},
    auth=exige(PERM.COT, PERM.COT_DEL),
)
def coter_courrier(request, identifiant: int, saisie: SaisieCotation):
    """
    Enregistre une cotation — §3.4.

    Deux permissions ouvrent la route, et c'est voulu : `COT` est portee par
    l'autorite qui cote, `COT_DEL` par l'agent de session qui saisit la cotation
    d'un autre. Le service, lui, distingue `decide_par` de `saisi_par` — la
    permission dit qui peut taper, la colonne dit qui a decide.

    La cotation pour suivi part avec l'acte quand `suiviParId` est donne : c'est
    la **seconde** cotation, celle d'une personne qui coordonne au-dessus du chef
    de file (A7, tranchée le 11 août 2026).
    """
    services.coter(identifiant, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Affectation — A-05
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/affectations",
    response={201: CourrierDetail},
    auth=exige(PERM.AFF),
)
def affecter_courrier(request, identifiant: int, saisie: SaisieAffectation):
    """
    Affecte le courrier a un agent d'une structure cotee — §3.5.

    La cotation va vers une **structure**, l'affectation vers une **personne** :
    le service refuse un agent dont la structure n'est pas cotee, faute de quoi
    l'affectation contournerait la decision de l'autorite.
    """
    services.affecter(identifiant, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Delai et correction
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/prolongation",
    response={201: CourrierDetail},
    auth=exige(PERM.COT, PERM.COT_DEL),
)
def prolonger_delai(request, identifiant: int, saisie: SaisieProlongation):
    """
    Reporte l'echeance d'un courrier — le bouton « Prolonger le délai » de A-03.

    Sous les permissions de **cotation** : le delai est impose en cotant, et le
    reporter revient a modifier cette decision. `TRA` ne suffit donc pas — un
    agent ne s'accorde pas son propre delai.

    Le report part de l'echeance en vigueur et non d'aujourd'hui, faute de quoi
    prolonger effacerait le retard deja constate. La regle est dans
    `services.prolonger`.
    """
    services.prolonger(identifiant, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


@routeur.patch("/{int:identifiant}", response=CourrierDetail, auth=exige(PERM.ENR))
def corriger_courrier(request, identifiant: int, saisie: SaisieCorrection):
    """
    Corrige une erreur de saisie — §4.2.

    `PATCH` et non `PUT` : les champs omis restent inchanges. Un `PUT` aurait
    impose au front d'envoyer la fiche entiere, et le premier ecran partiel
    aurait efface ce qu'il n'affiche pas.

    Sous `ENR`, la permission qui inscrit : celui qui tient le registre corrige
    sa saisie. Les mentions du registre — numero, session, sens, confidentialite,
    date de reception — ne sont pas corrigeables ; voir
    `services.CHAMPS_CORRIGEABLES`.
    """
    services.corriger(identifiant, saisie.dict(), request.auth)
    return lecture.fiche(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Editions — le registre et la fiche de cotation
# ---------------------------------------------------------------------


@routeur.get("/export", auth=exige(PERM.LEC))
def exporter_registre(
    request,
    format: str = "pdf",
    sens: str = "ARRIVEE",
    vue: str = "tous",
    q: str = "",
):
    """
    Le registre en Word ou en PDF — §10, ADR 023.

    **Un document, pas une capture d'ecran.** Le serveur ouvre le gabarit Word
    officiel de la DSR, y verse le registre tel que l'ecran le filtre, et
    LibreOffice en tire le PDF.

    Les trois parametres sont ceux de `GET /courriers`, aux memes noms : le
    bouton « Exporter » edite **ce que l'agent regarde**, jamais le registre
    entier. Un document qui ne correspond pas a l'ecran d'ou il sort ne se
    defend pas devant un controle.

    La garde est `LEC` ; la permission d'**editer** (`IMP`) est verifiee dans
    `documents.registre_document`, avec les autres regles. Lire a l'ecran et
    sortir un fichier signable sont deux gestes.

    La trace est posee **apres** la production (§3.12, RNF-TRACE-01), et par
    `tracer_acces` et non par un evenement metier : editer ne modifie rien, mais
    fait sortir des donnees du systeme.
    """
    document = documents.registre_document(request.auth, sens=sens, vue=vue, recherche=q)
    contenu, mime = sortie.produire(document, format)

    tracer_acces(
        acteur=request.auth,
        objet_type="registre_courrier",
        action="export",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    reponse = HttpResponse(contenu, content_type=mime)
    reponse["Content-Disposition"] = (
        f'attachment; filename="{sortie.nom_de_fichier(document.reference, format)}"'
    )
    return reponse


@routeur.get("/{int:identifiant}/fiche-cotation/export", auth=exige(PERM.LEC))
def exporter_fiche_de_cotation(request, identifiant: int, format: str = "pdf"):
    """
    La fiche de cotation — B-03, le bordereau qui accompagne le pli.

    Elle porte la decharge que le recepteur signe a la main : c'est la piece qui
    fait foi quand le systeme est indisponible, et un accuse a l'ecran ne
    remplace pas une signature sur le registre du coursier.

    Meme garde et meme trace que l'export du registre. Un courrier hors
    perimetre sort en 404 par `lecture.fiche` — jamais en 403 (D5).
    """
    document = documents.fiche_de_cotation_document(request.auth, identifiant)
    contenu, mime = sortie.produire(document, format)

    tracer_acces(
        acteur=request.auth,
        objet_type="courrier",
        objet_id=identifiant,
        action="export",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    reponse = HttpResponse(contenu, content_type=mime)
    reponse["Content-Disposition"] = (
        f'attachment; filename="{sortie.nom_de_fichier(document.reference, format)}"'
    )
    return reponse


# ---------------------------------------------------------------------
#  Bureau d'ordre de structure — A-02b
#
#  Au Port, le bureau d'ordre d'une structure est son **point focal**. Les
#  trois routes ci-dessous sont son registre : ce qui est arrive, ce qui est
#  chez lui, ce qui est reparti.
#
#  Le convertisseur `int` de `/{int:identifiant}` ne capture pas
#  « bureau-ordre » : l'ordre de declaration n'a donc pas a etre surveille ici,
#  a la difference d'un chemin a segment libre.
# ---------------------------------------------------------------------


@routeur.get("/bureau-ordre", response=list[LignePassage], auth=exige(PERM.BO_STR))
def registre_bureau_ordre(request, structure: int | None = None, etat: str = "en_cours"):
    """
    Le registre d'entree et de sortie d'une structure — A-02b.

    Trois etats, et ce sont les trois piles d'un bureau d'ordre reel :
    `a_accuser` (arrive, pas encore tamponne), `en_cours` (chez nous), `sortis`
    (parti, et par ou).

    `structure` a vide prend toutes les structures lisibles : un point focal n'en
    a qu'une, la DSR les a toutes, et l'ecran n'a pas a savoir lequel des deux
    l'ouvre.
    """
    return bureau_ordre.registre(request.auth, structure_id=structure, etat=etat)


@routeur.post(
    "/passages/{int:passage_id}/accuse",
    response={201: LignePassage},
    auth=exige(PERM.BO_STR),
)
def accuser_reception(request, passage_id: int):
    """
    Le bureau d'ordre reconnait avoir recu le courrier.

    **Une seule fois** : un second accuse ecraserait l'heure du premier, et
    l'ecart entre l'entree et le tampon — la seule mesure du temps mort d'un
    bureau d'ordre — se remettrait a zero a chaque clic. Le service repond 409.
    """
    passage = bureau_ordre.accuser_reception(request.auth, passage_id)
    return 201, bureau_ordre.ligne_de(passage)


@routeur.post(
    "/passages/{int:passage_id}/sortie",
    response={201: LignePassage},
    auth=exige(PERM.BO_STR),
)
def prononcer_sortie(request, passage_id: int, saisie: SaisieSortie):
    """
    La structure rend le courrier — reponse transmise, retour, transmission,
    cloture.

    Le motif n'est pas facultatif : une sortie sans motif se lirait « le courrier
    a disparu de nos écrans », et le registre existe pour dire par ou les choses
    sont parties.
    """
    passage = bureau_ordre.prononcer_sortie(request.auth, passage_id, saisie.dict())
    return 201, bureau_ordre.ligne_de(passage)


# ---------------------------------------------------------------------
#  Supervision des delais — le mapping de la DSR
# ---------------------------------------------------------------------


@routeur.get("/supervision", response=CarteBlocages, auth=exige(PERM.REL))
def carte_des_blocages(request, structure: int | None = None, seuil: int = 0):
    """
    Ou est bloque chaque courrier, et depuis quand — le mapping complet.

    Sous `REL`, la permission de **relancer**, et non sous `STAT` : ce n'est pas
    une statistique mais la liste de travail de celui qui relance. La meme
    permission ouvre le dossier interne dans `cloisonnement.py`, et il faut que
    les deux tiennent la frontiere au meme endroit — un ecran qui nommerait un
    detenteur que la fiche masque serait une fuite par la bande.
    """
    return supervision.carte_des_blocages(request.auth, structure_id=structure, seuil_jours=seuil)


# ---------------------------------------------------------------------
#  Le cahier de decharge — A-11
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/affectations/{int:affectation_id}/accuse",
    response={201: CourrierDetail},
    auth=exige(PERM.LEC),
)
def accuser_affectation(request, identifiant: int, affectation_id: int, saisie: SaisieDecharge):
    """
    L'agent cote signe la decharge — « j'ai bien reçu ce courrier ».

    Sous `LEC` et non sous `TRA` : accuser reception est le geste de celui qui
    **recoit** le pli, pas de celui qui le traite. Exiger `TRA` aurait empeche
    d'accuser un courrier mal dirige — c'est-a-dire exactement le cas ou le
    cahier sert. Le service, lui, verifie la qualite du signataire : l'agent
    affecte, ou quelqu'un de sa structure.

    La fiche complete est rendue plutot que l'affectation seule : l'etape du
    courrier change avec la decharge (`AFFECTE` devient `ACCEPTE`), et l'ecran
    doit la relire de toute facon.
    """
    services.accepter(identifiant, affectation_id, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


@routeur_accuses.get("/accuses", response=list[LigneDecharge], auth=exige(PERM.LEC))
def cahier_de_decharge(request, vue: str = "tous"):
    """
    Le cahier de decharge de l'agent et de sa structure — A-11.

    Trois vues, qui sont les trois questions qu'on pose a un cahier : `tous`,
    `attente` (pas encore signe), `nonRetourne` (pas signe depuis trop
    longtemps). Le seuil s'administre — `courrier.decharge_delai_alerte_jours`,
    **hypothese** (A73).

    Une vue inconnue ne filtre rien plutot que de vider la liste : c'est la
    convention du registre, et un filtre mal orthographie qui vide l'ecran se lit
    comme une panne.
    """
    return lecture.decharges(request.auth, vue=vue)


# ---------------------------------------------------------------------
#  Les ecarts signales — A-12
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/signalements",
    response={201: SignalementLu},
    auth=exige(PERM.LEC),
)
def signaler_ecart(request, identifiant: int, saisie: SaisieSignalement):
    """
    Ouvre un ecart sur le circuit papier d'un courrier — A-12.

    Sous `LEC` : l'agent qui constate un pli incomplet n'a pas de raison de porter
    une permission d'ecriture pour le dire. C'est aussi la seule facon pour un
    agent mal cote de se signaler — il ne porte, par definition, aucun droit sur
    ce courrier-la.
    """
    signalement = services.signaler_ecart(identifiant, saisie.dict(), request.auth)
    lignes = lecture.signalements(request.auth, signalement.courrier)
    return 201, next(ligne for ligne in lignes if ligne["id"] == signalement.pk)


@routeur_signalements.get("/signalements", response=list[SignalementLu], auth=exige(PERM.LEC))
def registre_des_ecarts(request):
    """
    Les ecarts qu'un agent a le droit de suivre — ceux qu'il a emis, et ceux qui
    visent sa structure.

    Pas de troisieme titre : un registre d'ecarts lisible de tous devient un
    registre ou plus personne ne signale.
    """
    return lecture.signalements(request.auth)


@routeur_signalements.post(
    "/signalements/{int:signalement_id}/etat",
    response={201: SignalementLu},
    auth=exige(PERM.AFF),
)
def avancer_signalement(request, signalement_id: int, saisie: SaisieAvancementSignalement):
    """
    Fait passer l'ecart a l'etat suivant — `ouvert`, `pris_en_compte`, `clos`.

    Sous `AFF`, la permission d'affecter : c'est elle qui, dans le socle, designe
    le responsable d'une structure — celui qui distribue le courrier a ses agents
    et que le point focal porte aussi. **C'est une hypothese** (A71) : aucun
    document ne dit qui traite un ecart. Une permission dediee aurait fait pire —
    une permission que personne ne porte, donc un registre que personne n'ouvre.

    La permission ne suffit pas : le service verifie que l'agent appartient bien
    a la structure **visee**. Porter `AFF` ailleurs ne donne aucun droit ici.
    """
    signalement = services.avancer_signalement(signalement_id, saisie.dict(), request.auth)
    lignes = lecture.signalements(request.auth, signalement.courrier)
    return 201, next(ligne for ligne in lignes if ligne["id"] == signalement.pk)


# ---------------------------------------------------------------------
#  Le fil d'observations
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/observations",
    response={201: CourrierDetail},
    auth=exige(PERM.LEC),
)
def publier_observation(request, identifiant: int, saisie: SaisieObservation):
    """
    Porte une observation au dossier — **tout lecteur ecrit, tout lecteur lit**.

    Arbitrage du Port du 26 aout 2026. Il n'y a donc ni `PATCH` ni `DELETE` sur
    cette ressource, et la table ne porte pas les colonnes qui les rendraient
    possibles : une observation ne se reecrit pas apres coup.

    La fiche complete est rendue : le fil y vit, et l'ecran la relit de toute
    facon.
    """
    services.publier_observation(identifiant, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Le traitement, la restitution, le retour et la cloture
# ---------------------------------------------------------------------


@routeur.post(
    "/{int:identifiant}/traitement",
    response={201: CourrierDetail},
    auth=exige(PERM.TRA),
)
def rediger(request, identifiant: int, saisie: SaisieTraitement):
    """
    L'agent cote enregistre ce qu'il a fait du courrier.

    Un seul traitement par agent et par courrier, repris a chaque
    enregistrement : d'ou un `POST` sur une ressource au singulier plutot qu'une
    collection. Le service refuse tant que la decharge n'est pas signee
    (ADR 035) — c'est la que `exiger_la_decharge()` trouve son appelant.
    """
    services.rediger(identifiant, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


@routeur.post(
    "/{int:identifiant}/restitution",
    response={201: CourrierDetail},
    auth=exige(PERM.TRA),
)
def restituer(request, identifiant: int, saisie: SaisieTraitement | None = None):
    """
    L'agent rend son traitement au responsable de structure — l'etape RESTITUE.

    Ce n'est pas une soumission a validation : le Port ne connait aucun visa sur
    le courrier arrive (ADR 034). Le responsable lit, puis cloture ou retourne.
    """
    services.restituer(identifiant, saisie.dict() if saisie else {}, request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


@routeur.post(
    "/{int:identifiant}/traitements/{int:traitement_id}/retour",
    response={201: CourrierDetail},
    auth=exige(PERM.CLO),
)
def retourner(request, identifiant: int, traitement_id: int, saisie: SaisieRetourTraitement):
    """
    Le responsable rend le traitement a son auteur, avec un motif.

    Sous `CLO`, la permission de celui qui referme : retourner et cloturer sont
    les deux issues du meme geste de lecture, et les separer aurait fait porter
    a un autre agent la moitie d'une decision. **Hypothese** — A74.
    """
    services.retourner(identifiant, traitement_id, saisie.dict(), request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


@routeur.post(
    "/{int:identifiant}/cloture",
    response={201: CourrierDetail},
    auth=exige(PERM.CLO),
)
def clore(request, identifiant: int, saisie: SaisieCloture | None = None):
    """
    Le responsable de structure referme le dossier — la fin du trajet.

    « Le responsable cloture, fin » (Port, 26 aout 2026). Il n'y a pas de route
    de reouverture, et ce n'est pas un oubli : un courrier rouvert aurait deux
    dates de fin, et le delai de traitement n'en mesurerait plus aucune.

    La permission ne suffit pas : le service exige que l'agent releve d'une
    structure **cotee** sur ce courrier, ou du bureau d'ordre qui l'a
    enregistre.
    """
    services.clore(identifiant, saisie.dict() if saisie else {}, request.auth)
    return 201, lecture.fiche(request.auth, identifiant)


# ---------------------------------------------------------------------
#  Compteurs de la navigation
# ---------------------------------------------------------------------


@routeur_compteurs.get("/compteurs", response=Compteurs, auth=session_seule)
def compteurs(request):
    """
    Les trois pastilles de la barre laterale.

    `session_seule` et non `exige(PERM.LEC)` : la barre laterale est montee pour
    **tout** compte connecte, y compris celui qui ne porte aucune permission de
    courrier. Exiger `LEC` aurait fait remonter un 403 a chaque chargement de
    l'application pour ces comptes — et le front n'a aucun moyen de distinguer un
    403 attendu d'une panne.

    La garde est donc portee par `lecture.compteurs()`, qui rend trois zeros a qui
    ne possede pas `LEC`. Un compteur juste rendu a qui ne peut pas ouvrir la
    liste apprendrait quelque chose du registre : c'est une fuite discrete, et
    c'est pour cela que le controle existe malgre la garde large.
    """
    return lecture.compteurs(request.auth)


# ---------------------------------------------------------------------
#  Suivi et relance — C-02
# ---------------------------------------------------------------------


@routeur_suivi.get("/relance", response=TableauRelance, auth=exige(PERM.LEC))
def tableau_de_relance(request, vue: str = "horsDelai"):
    """
    Ce qui ne se fait pas, classe par retard decroissant.

    **Sous `LEC` et non sous `REL`**, contrairement a la supervision, et la
    difference tient a ce que chaque ecran montre. La carte des blocages est
    transverse : elle traverse le cloisonnement pour que la DSR voie ce qu'une
    direction ne montrerait pas, et `REL` est ce qui l'autorise. Ce tableau-ci
    est borne par `visibles()` : il ne dit rien qu'on ne lise deja dans le
    registre, seulement classe par ce qui deborde. Un directeur doit pouvoir
    ouvrir « qu'est-ce qui ne se fait pas chez moi » — c'est une question de
    responsable, pas un privilege de la Division du suivi.

    Le geste de relancer, lui, restera sous `REL` : le front garde deja son
    bouton ainsi, et ce module ne fait que lire.

    Les cinq valeurs de `vue` sont des **filtres, pas des etapes** : un dossier
    hors delai peut aussi etre sans accuse. Une vue inconnue ne filtre rien
    plutot que de vider l'ecran — convention du registre.
    """
    return relance.tableau(request.auth, vue=vue)


# ---------------------------------------------------------------------
#  Le dossier de traitement — C-01
# ---------------------------------------------------------------------


@routeur_suivi.get("/portefeuille", response=PortefeuilleAgent, auth=exige(PERM.LEC))
def portefeuille(request):
    """
    La corbeille personnelle de l'agent.

    **Pas de parametre, et c'est le point.** Cette route ne repond qu'a une
    question — « qu'est-ce que j'ai sur les bras » — et la reponse ne depend que
    de qui appelle. Un filtre par structure en ferait un registre de plus.
    """
    return suivi.portefeuille(request.auth)


@routeur_suivi.get("/dossiers/{int:identifiant}", response=DossierTraitement, auth=exige(PERM.LEC))
def dossier(request, identifiant: int):
    """
    Un dossier, vu du cote de celui qui le traite.

    Ouvert a tout lecteur du courrier et non au seul agent affecte : c'est ainsi
    qu'un responsable sait ou en est le travail avant de relancer. Ce qui reste
    ferme, ce sont les notes privees — la regle est dans `suivi._notes_lisibles`.

    404 hors perimetre, jamais 403 : decision D5.

    Pas de `tracer_acces` : le journal des acces sert aux lectures **sensibles**
    et aux exports (ADR 012). Ouvrir sa propre corbeille cent fois par jour y
    noierait les lectures qui, elles, meritent d'etre retrouvees.
    """
    return suivi.dossier(request.auth, identifiant)


@routeur_suivi.post(
    "/dossiers/{int:identifiant}/taches", response=TacheDossier, auth=exige(PERM.LEC)
)
def ajouter_tache(request, identifiant: int, saisie: SaisieTache):
    """Ajoute une etape a la liste de l'agent. Elle n'engage que lui."""
    return suivi_dossier_tache(services.ajouter_tache(identifiant, saisie.dict(), request.auth))


@routeur_suivi.patch(
    "/dossiers/{int:identifiant}/taches/{int:tache_id}", response=TacheDossier, auth=exige(PERM.LEC)
)
def basculer_tache(request, identifiant: int, tache_id: int, saisie: SaisieBasculeTache):
    """
    Coche ou decoche une etape.

    Decocher est permis : une case cochee par erreur se corrige. Ce n'est pas une
    trace opposable, c'est un pense-bete.
    """
    tache = services.basculer_tache(identifiant, tache_id, saisie.dict(), request.auth)
    return suivi_dossier_tache(tache)


def suivi_dossier_tache(tache) -> dict:
    """Met une tache en forme pour le front. Deux routes la rendent, une seule
    mise en forme : deux copies auraient fini par diverger sur `faiteLe`."""
    return {
        "id": tache.pk,
        "libelle": tache.libelle,
        "faite": tache.faite_le is not None,
        "faiteLe": tache.faite_le,
    }


@routeur_suivi.post("/dossiers/{int:identifiant}/notes", response=NoteDossier, auth=exige(PERM.LEC))
def publier_note(request, identifiant: int, saisie: SaisieNote):
    """
    Porte une note de travail au dossier.

    Sous `LEC` comme le fil d'observations : qui lit le courrier peut y noter.
    Ce qui distingue les deux, ce n'est pas le droit d'ecrire, c'est qui lira.
    """
    note = services.publier_note(identifiant, saisie.dict(), request.auth)
    return {
        "id": note.pk,
        "texte": note.texte,
        "horodatage": note.publiee_le,
        "privee": note.privee,
    }


@routeur_suivi.post("/dossiers/{int:identifiant}/demandes-delai", auth=exige(PERM.LEC))
def demander_delai(request, identifiant: int, saisie: SaisieDemandeDelai):
    """
    L'agent demande un report a son responsable.

    **Sous `LEC` et non sous `COT`** : demander n'est pas accorder. C'est meme la
    raison d'etre de cette route — celui qui n'a pas `COT` n'avait aucun moyen de
    faire connaitre qu'il ne tiendra pas le delai.
    """
    demande = services.demander_delai(identifiant, saisie.dict(), request.auth)
    return {"id": demande.pk, "etat": demande.etat}


@routeur_suivi.post("/demandes-delai/{int:demande_id}", auth=exige(PERM.COT))
def decider_delai(request, demande_id: int, saisie: SaisieDecisionDelai):
    """
    Le responsable tranche.

    **Sous `COT`** : qui fixe un delai le reporte. Accorder appelle `prolonger()`
    et modifie donc reellement l'echeance — d'ou la meme permission que la
    prolongation directe.
    """
    demande = services.decider_demande_delai(demande_id, saisie.dict(), request.auth)
    return {"id": demande.pk, "etat": demande.etat}


# ---------------------------------------------------------------------
#  La recherche avancee — A-14
# ---------------------------------------------------------------------


@routeur_suivi.post("/recherche", response=ResultatRecherche, auth=exige(PERM.LEC))
def rechercher(request, criteres: CriteresRecherche):
    """
    La recherche avancee, sur le registre visible de l'agent.

    **En POST alors qu'elle lit**, ce qui se justifie : dix criteres dont deux
    listes ne tiennent pas lisiblement dans une URL, et les mots-cles d'une
    recherche n'ont rien a faire dans les journaux d'acces d'un proxy.
    """
    return suivi.rechercher(request.auth, criteres.dict())


@routeur_suivi.get("/recherches", response=list[RechercheEnregistreeLue], auth=exige(PERM.LEC))
def recherches_enregistrees(request):
    """
    Ce que l'agent a conserve, avec le nombre de resultats **d'aujourd'hui**.

    Le nombre est recalcule et jamais stocke : « les courriers hors delai de la
    DAF » n'a pas le meme compte lundi et vendredi, et c'est ce que l'agent
    revient voir.
    """
    return suivi.recherches_enregistrees(request.auth)


@routeur_suivi.post("/recherches", response=RechercheEnregistreeLue, auth=exige(PERM.LEC))
def enregistrer_recherche(request, saisie: SaisieRechercheEnregistree):
    """
    Conserve des criteres sous un nom. Le meme nom ecrase : l'agent qui affine
    sa recherche et la resauvegarde veut la remplacer, pas lire une erreur.
    """
    enregistree = services.enregistrer_recherche(saisie.dict(), request.auth)
    return {
        "id": enregistree.pk,
        "libelle": enregistree.libelle,
        "nombre": suivi.rechercher(request.auth, enregistree.criteres)["total"],
        "criteres": enregistree.criteres,
    }


@routeur_suivi.delete("/recherches/{int:recherche_id}", auth=exige(PERM.LEC))
def oublier_recherche(request, recherche_id: int):
    """Supprime une recherche conservee. Ce n'est pas une trace, c'est un confort."""
    services.oublier_recherche(recherche_id, request.auth)
    return {"ok": True}


# ---------------------------------------------------------------------
#  La relance — C-02, le geste
# ---------------------------------------------------------------------


@routeur_suivi.post("/relances", response=BilanRelance, auth=exige(PERM.REL))
def emettre_relances(request, saisie: SaisieRelance):
    """
    Relance les detenteurs d'un lot de dossiers.

    **Sous `REL` et non sous `LEC`**, contrairement au tableau qui la prepare.
    Lire « qu'est-ce qui ne se fait pas chez moi » est une question de
    responsable ; ecrire a quatorze agents pour le leur rappeler est un acte de
    la Division du suivi, et le front garde deja son bouton derriere cette
    permission.

    Rend le bilan et non la liste des relances : ce que l'ecran doit dire, c'est
    combien sont parties, a qui, et pourquoi les autres ne le sont pas.
    """
    bilan = services.emettre_relances(saisie.identifiants, saisie.dict(), request.auth)
    return {
        "emises": len(bilan["emises"]),
        # Dedoublonne : relancer trois dossiers du meme agent lui ecrit trois
        # fois, mais l'ecran doit dire « à Rita Owona », pas trois fois son nom.
        "destinataires": sorted({relance.destinataire.nom_complet for relance in bilan["emises"]}),
        "ecartes": [ecart["raison"] for ecart in bilan["ecartes"]],
    }
