"""
Routes du pilotage — `/api/pilotage/*`, `/api/direction/*`, `/api/comite/*`.

**Que des lectures.** Le pilotage ne decide rien et n'ecrit rien : il restitue
ce que les autres piliers ont enregistre. Aucun evenement n'est donc inscrit au
journal, et c'est conforme a `RNF-TRACE-01`, qui trace les **ecritures
metier** — journaliser chaque ouverture d'un tableau de bord aurait noye le
journal sous des lignes que personne n'aurait relues.

**Deux exceptions, et les deux sortent un fichier** :
`GET /pilotage/rapports/export` et `GET /pilotage/synthese/export` tracent un
acces de type `export`. Ce n'est pas une consultation de plus, c'est une donnee
qui sort du systeme — le §3.12 le signale quel que soit son volume, et le
journal des acces est fait pour cela (A23).

Quatre gardes, quatre publics :

 * `COCKPIT` — le cockpit executif et la note de synthese. Le Directeur
   general, le CODIR et la DSR la portent.
 * `ACT_LEC` — le tableau de bord d'une structure. Tout responsable qui lit un
   plan d'actions lit le tableau de bord de sa structure.
 * `ACT_LEC`, `DOS_LEC` **ou** `LEC` — le tableau de bord general. C'est
   l'**ecran d'accueil par defaut** de qui n'en a pas de plus specifique
   (`app/layout/Accueil.tsx`), et une garde etroite y aurait accueilli un
   archiviste par un 401 le matin de sa premiere connexion. Garde large,
   contenu filtre : le perimetre applique est celui de la portee, jamais celui
   qui est demande (ADR 009).
 * `STAT` — statistiques, analyses croisees, indicateurs du programme. Le
   controle de gestion.
 * `ACT_LEC` **ou** `STAT` — les rapports periodiques et leur export. Ils se
   lisent a deux niveaux : le controle de gestion sort celui de l'institution,
   un responsable celui de sa structure. C'est le perimetre qui fait la
   difference, pas la garde.

`restreindre()` n'est pas appele ici, et plusieurs routes s'en passent
**deliberement** :

 * `/pilotage/structures`, `/pilotage/tableau-de-bord` et `/pilotage/rapports`
   filtrent au perimetre, mais dans `structure.py`, `tableau.py` et
   `rapports.py` — la restriction porte sur la *structure demandee*, pas sur
   une requete, et un sigle hors perimetre rend 404 (D5) plutot qu'une liste
   vide.
 * `/pilotage/analyses`, `/direction/vue-ensemble`, `/comite/vue-ensemble` et
   l'export de la note de synthese sont **institutionnels par nature**.
   Comparer sa structure a elle-meme n'apprend rien, et un conseil de
   directeurs qui ne verrait pas les directions ne delibererait sur rien. La
   derogation tient parce que ces reponses n'exposent que des agregats de
   structure : aucun objet nominatif, aucun courrier, aucun agent. Elle est
   bornee par la garde — `STAT`, `VUE_DG`, `VUE_CODIR` et `COCKPIT` ne sont
   portees que par les profils concernes.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

import unicodedata

from django.http import HttpResponse
from ninja import Router

from noyau.documents import sortie
from noyau.habilitation.dependances import PERM, exige
from noyau.journal.service import tracer_acces
from pilotage import analyses as calcul_analyses
from pilotage import cockpit as calcul_cockpit
from pilotage import programme as calcul_programme
from pilotage import rapports as calcul_rapports
from pilotage import structure as calcul_structure
from pilotage import synthese as calcul_synthese
from pilotage import tableau as calcul_tableau
from pilotage import vue_comite, vue_direction
from pilotage.schemas import (
    AnalysesCroisees,
    Cockpit,
    Rapport,
    Statistiques,
    SuiviProgramme,
    SyntheseInstance,
    TableauDeBord,
    TableauStructure,
    VueEnsembleComite,
    VueEnsembleDirection,
)

routeur = Router()
routeur_direction = Router()
routeur_comite = Router()


# =====================================================================
#  Niveau 1 — le Directeur general
# =====================================================================


@routeur.get("/cockpit", response=Cockpit, auth=exige(PERM.COCKPIT))
def cockpit(request):
    """
    Le cockpit executif — §3.1.

    Le classement est celui du dernier mois clos, et non du mois en cours : un
    chiffre dont il faudrait expliquer qu'il ne veut encore rien dire n'a pas sa
    place sur un ecran qui doit se lire en trente secondes.
    """
    return calcul_cockpit.cockpit(request.auth)


@routeur.get("/synthese", response=SyntheseInstance, auth=exige(PERM.COCKPIT))
def synthese(request):
    """
    La note de synthese de la prochaine instance — §3.1 et §3.2.

    Un document, pas un tableau de bord : les faits marquants sont des phrases,
    parce qu'un lecteur en seance ne recompose pas deux chiffres en une
    evolution.
    """
    return calcul_synthese.synthese(request.auth)


@routeur.get("/synthese/export", auth=exige(PERM.COCKPIT))
def exporter_synthese(request, format: str = "pdf"):
    """
    La note de synthese en Word ou en PDF — §3.1, §3.2, §3.12, ADR 023.

    **Un document, pas une capture d'ecran.** Le serveur ouvre le gabarit Word
    officiel de la DSR, y verse la note, et LibreOffice en tire le PDF : une
    source, deux formats, aucune divergence possible entre les deux fichiers.

    **Pas de `restreindre()`**, et c'est delibere : la note releve de la
    derogation ecrite en tete de ce module pour `/pilotage/analyses` et
    `/comite/vue-ensemble`. Une note d'instance amputee des directions hors
    perimetre du lecteur ne serait pas la note de l'instance. Elle n'expose que
    des agregats de structure — aucun objet nominatif, aucun agent — et la
    garde `COCKPIT` la borne. Le contenu servi est exactement celui de
    `GET /pilotage/synthese`, ni plus ni moins.

    La trace est posee **apres** la production (§3.12, RNF-TRACE-01) : un
    document qui echoue n'a rien exporte, et une ligne de journal pour un
    fichier jamais produit ferait chercher une fuite qui n'a pas eu lieu.
    """
    document = calcul_synthese.synthese_document(request.auth)

    # Le rendu, la conversion et leurs deux pannes sont portes par
    # `noyau.documents.sortie` : ces quarante lignes etaient ici, et le second
    # document du depot — le registre des courriers — les aurait recopiees.
    contenu, mime = sortie.produire(document, format)

    tracer_acces(
        acteur=request.auth,
        objet_type="note_synthese",
        action="export",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    reponse = HttpResponse(contenu, content_type=mime)
    reponse["Content-Disposition"] = (
        f'attachment; filename="{_nom_du_fichier(document.reference, format)}"'
    )
    return reponse


def _nom_du_fichier(reference: str, format: str) -> str:
    """« note-synthese-codir-2026-09-03.docx » — nommable, triable, sans accent."""
    sans_accent = (
        unicodedata.normalize("NFKD", reference).encode("ascii", "ignore").decode().lower()
    )
    return f"note-synthese-{sans_accent.removeprefix('note-')}.{format}"


# =====================================================================
#  Niveaux 2 et 3 — les structures
# =====================================================================


@routeur.get("/structures", response=TableauStructure, auth=exige(PERM.ACT_LEC))
def tableau_structure(request, sigle: str = ""):
    """
    Le tableau de bord d'une structure du perimetre — §3.4 et §3.5.

    Sans sigle, celle de rattachement de l'agent. Un sigle hors perimetre rend
    **404** et non 403 : repondre « vous n'avez pas le droit » confirmerait
    l'existence de la structure et de ses chiffres a qui n'a pas a les
    connaitre (D5).
    """
    return calcul_structure.tableau_structure(request.auth, sigle)


@routeur.get(
    "/tableau-de-bord",
    response=TableauDeBord,
    auth=exige(PERM.ACT_LEC, PERM.DOS_LEC, PERM.LEC),
)
def tableau_de_bord(request, perimetre: str = "institution", periode: str = "mois"):
    """
    Le tableau de bord, dans l'un de ses trois perimetres — §3.4, §3.5.

    Un perimetre demande plus large que la portee n'est pas une erreur : le
    serveur le ramene a ce que la portee permet et le dit dans
    `perimetreApplique`. Repondre 403 aurait casse l'ecran d'un agent dont
    l'habilitation vient de changer (ADR 009).
    """
    return calcul_tableau.tableau_de_bord(request.auth, perimetre=perimetre, periode=periode)


# =====================================================================
#  Les rapports periodiques — D-03
# =====================================================================


@routeur.get("/rapports", response=Rapport, auth=exige(PERM.ACT_LEC, PERM.STAT))
def rapport_periodique(
    request,
    periode: str = "mois",
    annee: int | None = None,
    rang: int | None = None,
    structure: str = "",
    perimetre: str = "",
):
    """
    Le rapport d'une periode close, sur un perimetre — D-03 et §3.11.

    Garde large a dessein : un rapport periodique se lit a deux niveaux. Le
    controle de gestion (`STAT`) sort celui de l'institution, un responsable de
    structure (`ACT_LEC`) sort celui de la sienne — et c'est le perimetre, non
    la garde, qui fait la difference. Le sigle demande est verifie contre la
    portee dans `structure.py` : hors perimetre, 404 (D5).

    Une periode non close est **ramenee** a la derniere close plutot que
    refusee ; la reponse porte `periodeRamenee` et l'ecran le dit.
    """
    return calcul_rapports.rapport(
        request.auth,
        granularite=periode,
        annee=annee,
        rang=rang,
        sigle=structure,
        perimetre=perimetre,
    )


@routeur.get("/rapports/export", auth=exige(PERM.ACT_LEC, PERM.STAT))
def exporter_rapport(
    request,
    periode: str = "mois",
    annee: int | None = None,
    rang: int | None = None,
    structure: str = "",
    perimetre: str = "",
):
    """
    Le meme rapport, en CSV, servi par le serveur — §3.12.

    Servi par le serveur et non assemble par le navigateur : sortir une donnee
    du systeme est un **acte**, pas une navigation, et un tableur fabrique cote
    client n'aurait laisse aucune trace. C'est la seule lecture du pilotage qui
    passe par `tracer_acces` — les tableaux de bord, eux, se consultent cent
    fois par jour sans rien sortir.

    La trace est posee **apres** le calcul : un rapport qui echoue n'a rien
    exporte, et une ligne de journal pour un fichier jamais produit ferait
    chercher une fuite qui n'a pas eu lieu.
    """
    donnees = calcul_rapports.rapport(
        request.auth,
        granularite=periode,
        annee=annee,
        rang=rang,
        sigle=structure,
        perimetre=perimetre,
    )

    tracer_acces(
        acteur=request.auth,
        objet_type="rapport_pilotage",
        action="export",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    reponse = HttpResponse(
        calcul_rapports.csv_du_rapport(donnees),
        content_type="text/csv; charset=utf-8",
    )
    reponse["Content-Disposition"] = (
        f'attachment; filename="{calcul_rapports.nom_du_fichier(donnees)}"'
    )
    return reponse


# =====================================================================
#  Le controle de gestion
# =====================================================================


@routeur.get("/statistiques", response=Statistiques, auth=exige(PERM.STAT))
def statistiques(request, annee: int | None = None, structure: str = ""):
    """
    Les statistiques annuelles — §3.11.

    **Filtrees au perimetre**, contrairement aux analyses croisees : elles
    descendent au detail d'une structure, et le §3.5 interdit au point focal de
    voir celles des autres.
    """
    return calcul_analyses.statistiques(request.auth, annee=annee, structure=structure)


@routeur.get("/analyses", response=AnalysesCroisees, auth=exige(PERM.STAT))
def analyses(request):
    """
    Les analyses croisees — §3.11.

    Quatre mesures attendues, deux disponibles : le courrier et les dossiers
    sortent a `null`, la dispersion et les moyennes se renormalisent sur ce qui
    reste, et les constats disent l'absence en toutes lettres (ADR 011).
    """
    return calcul_analyses.analyses(request.auth)


@routeur.get("/programme", response=SuiviProgramme, auth=exige(PERM.STAT))
def programme(request, annee: int | None = None):
    """
    Les indicateurs cibles du programme, N vs N-1 — §3.11 et §9.

    Une valeur rapportee prime sur une valeur calculee : c'est le rapporteur qui
    engage sa signature devant l'instance, pas le serveur.
    """
    return calcul_programme.programme(annee)


# =====================================================================
#  Les vues d'ensemble
# =====================================================================


@routeur_direction.get("/vue-ensemble", response=VueEnsembleDirection, auth=exige(PERM.VUE_DG))
def vue_ensemble_direction(request):
    """
    La vue d'ensemble du Directeur general — cinq graphiques, aucun tableau.

    Les blocs `chenal` et `recouvrements` sortent a `null` quand la session ne
    porte pas `EXP_LEC` : un bloc absent ne fuit pas, un bloc masque a
    l'affichage fuit des qu'on ouvre les outils du navigateur.
    """
    return vue_direction.vue_ensemble(request.auth)


@routeur_comite.get("/vue-ensemble", response=VueEnsembleComite, auth=exige(PERM.VUE_CODIR))
def vue_ensemble_comite(request):
    """
    La vue d'ensemble du Comite de direction — le college vu par agregats, et la
    place du membre dedans.

    Le classement ne sort plus direction par direction : au-dela de quelques
    colonnes l'histogramme n'etait plus lisible. Le membre y voit son score et
    son rang ; le mouvement du college se lit dans la moyenne et la dispersion.
    Le Comite reste le conseil des directeurs, pas un poste.
    """
    return vue_comite.vue_ensemble(request.auth)
