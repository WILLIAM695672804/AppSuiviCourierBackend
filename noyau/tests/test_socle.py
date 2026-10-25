"""
Tests du socle.

Trois d'entre eux sont des **filets** : ils ne verifient pas une
fonctionnalite mais une regle de projet qu'un ajout futur pourrait enfreindre
sans que personne ne s'en apercoive. Ce sont les plus importants du fichier.
"""

import re
from pathlib import Path

import pytest
from django.utils import timezone

from noyau.habilitation.dependances import PERM, ExigePermission
from noyau.habilitation.modeles import Permission, Profil, ProfilPermission, UtilisateurProfil
from noyau.habilitation.resolution import permissions_de, possede
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import NiveauHierarchique, Poste, Structure
from noyau.perimetre.modeles import Perimetre
from noyau.perimetre.portee import restreindre, structures_visibles


@pytest.fixture
def organigramme(db):
    """
    Une direction, un service sous elle, et une direction voisine.

    Les niveaux hierarchiques ne sont pas crees : ils sont livres par les
    donnees initiales du schema (DG, DIR, DEP, SERV). Un test qui recreerait
    son propre referentiel testerait un organigramme qui n'existe pas.
    """
    niveau_direction = NiveauHierarchique.objects.get(code="DIR")
    niveau_service = NiveauHierarchique.objects.get(code="SERV")

    daf = Structure.objects.create(
        code="DAF",
        libelle="Direction des affaires financieres",
        niveau_hierarchique=niveau_direction,
        valide_du=timezone.now().date(),
    )
    compta = Structure.objects.create(
        code="CPT",
        libelle="Service comptabilite",
        parent=daf,
        niveau_hierarchique=niveau_service,
        valide_du=timezone.now().date(),
    )
    dsi = Structure.objects.create(
        code="DSI",
        libelle="Direction des systemes d'information",
        niveau_hierarchique=niveau_direction,
        valide_du=timezone.now().date(),
    )
    poste = Poste.objects.create(
        structure=compta,
        libelle="Chef de service comptabilite",
        niveau_hierarchique=niveau_service,
        valide_du=timezone.now().date(),
    )
    return {"daf": daf, "compta": compta, "dsi": dsi, "poste": poste}


@pytest.fixture
def agent(db, organigramme):
    return Utilisateur.objects.create(
        identifiant_annuaire="s.bamba",
        nom="Bamba",
        prenom="Sekou",
        poste=organigramme["poste"],
        structure=organigramme["compta"],
    )


# ---------------------------------------------------------------------
#  Habilitation
# ---------------------------------------------------------------------


def test_les_permissions_viennent_des_profils(agent):
    profil = Profil.objects.create(code="FOCAL", libelle="Point focal")
    for code in (PERM.ACT_LEC, PERM.ACT_SAI):
        ProfilPermission.objects.create(profil=profil, permission=Permission.objects.get(code=code))
    UtilisateurProfil.objects.create(utilisateur=agent, profil=profil)

    assert permissions_de(agent) == {PERM.ACT_LEC, PERM.ACT_SAI}
    assert possede(agent, PERM.ACT_SAI)
    # `possede` accepte plusieurs codes : au moins un suffit, comme cote front.
    assert possede(agent, PERM.ACT_VAL, PERM.ACT_SAI)
    assert not possede(agent, PERM.ACT_VAL)


def test_un_agent_sans_profil_n_a_rien(agent):
    assert permissions_de(agent) == set()


# ---------------------------------------------------------------------
#  Perimetre — la couche a ne jamais casser
# ---------------------------------------------------------------------


def test_sans_perimetre_on_ne_voit_rien(agent):
    """
    Regle 3 de `noyau/perimetre/portee.py` : en cas de doute, on ne montre
    rien. L'inverse — tout voir faute de restriction — est la faille classique
    de ce type de couche.
    """
    assert structures_visibles(agent).count() == 0
    assert restreindre(Structure.objects.all(), agent, champ_agent="pk").count() == 0


def test_portee_structure_borne_a_la_sienne(agent, organigramme):
    Perimetre.objects.create(
        utilisateur=agent,
        structure=organigramme["compta"],
        portee="structure",
        valide_du=timezone.now().date(),
    )
    visibles = {s.code for s in structures_visibles(agent)}
    assert visibles == {"CPT"}


def test_portee_sous_arbre_descend(agent, organigramme):
    Perimetre.objects.create(
        utilisateur=agent,
        structure=organigramme["daf"],
        portee="sous_arbre",
        valide_du=timezone.now().date(),
    )
    visibles = {s.code for s in structures_visibles(agent)}
    assert visibles == {"DAF", "CPT"}
    # La direction voisine n'y est pas, et c'est tout l'objet du perimetre.
    assert "DSI" not in visibles


def test_portee_toutes_ne_pose_aucun_filtre(agent):
    Perimetre.objects.create(utilisateur=agent, portee="toutes", valide_du=timezone.now().date())
    # `None` et non une liste : l'appelant doit ne poser aucun filtre. Une
    # liste de toutes les structures produirait un IN de plusieurs centaines
    # d'identifiants a chaque requete.
    assert structures_visibles(agent) is None
    assert restreindre(Structure.objects.all(), agent).count() == 3


def test_portee_propre_sans_champ_agent_leve(agent, organigramme):
    """
    Omettre `champ_agent` en portee « propre » degraderait silencieusement la
    restriction au niveau « structure ». On leve plutot que de laisser passer.
    """
    Perimetre.objects.create(
        utilisateur=agent,
        structure=organigramme["compta"],
        portee="propre",
        valide_du=timezone.now().date(),
    )
    with pytest.raises(ValueError, match="propre"):
        restreindre(Structure.objects.all(), agent)


# ---------------------------------------------------------------------
#  Filets — regles de projet
# ---------------------------------------------------------------------


#: La racine du depot, deux niveaux au-dessus de `noyau/tests/`.
DEPOT = Path(__file__).resolve().parents[2]

#: Les deux copies front de la liste des permissions. La premiere est la source
#: de verite du typage, la seconde ce que l'ecran des profils sait cocher.
TYPES_FRONT = DEPOT / "frontend/src/types/habilitation.ts"
LIBELLES_FRONT = DEPOT / "frontend/src/features/habilitation/libellesPermissions.ts"


def test_codes_de_permission_alignes(db):
    """
    Filet. `PERM` doit refleter exactement la table `permission`.
    """
    en_base = set(Permission.objects.values_list("code", flat=True))
    dans_le_code = {
        valeur
        for nom, valeur in vars(PERM).items()
        if not nom.startswith("_") and isinstance(valeur, str)
    }
    assert dans_le_code == en_base, (
        f"Manquent au code : {sorted(en_base - dans_le_code)} · "
        f"Absentes de la base : {sorted(dans_le_code - en_base)}"
    )


def test_le_front_connait_les_memes_permissions(db):
    """
    Filet. Les deux copies front de la liste doivent refleter la table.

    `types/habilitation.ts` type les gardes d'ecran ; `libellesPermissions.ts`
    est ce que l'ecran des profils sait **cocher**. Une permission absente de la
    seconde ne s'accorde par aucun ecran : elle devient un droit que seul un
    `INSERT` distribue, ce qui etait le cas de `BO_STR` et `ACT_REC`, ajoutees au
    socle et jamais reportees.

    Le test lit les fichiers TypeScript plutot que de les compiler : une
    expression reguliere sur des constantes en majuscules suffit, et rien
    d'autre du depot ne ressemble a `PERMISSIONS.XXX`.

    Le test est saute si le front n'est pas la — le backend doit rester
    verifiable seul, en conteneur ou en integration continue.
    """
    if not TYPES_FRONT.exists() or not LIBELLES_FRONT.exists():
        pytest.skip("Le front n'est pas dans ce depot.")

    en_base = set(Permission.objects.values_list("code", flat=True))

    types = set(re.findall(r'^\s+([A-Z][A-Z_]*):\s*"', TYPES_FRONT.read_text("utf-8"), re.M))
    assert types == en_base, (
        f"Manquent a types/habilitation.ts : {sorted(en_base - types)} · "
        f"Absentes de la base : {sorted(types - en_base)}"
    )

    coches = set(re.findall(r"PERMISSIONS\.([A-Z][A-Z_]*)", LIBELLES_FRONT.read_text("utf-8")))
    assert coches == en_base, (
        f"Manquent a l'ecran des profils : {sorted(en_base - coches)} · "
        f"Inconnues de la base : {sorted(coches - en_base)}"
    )


def test_toute_route_porte_une_authentification():
    """
    Filet. Un endpoint sans `auth=` est un endpoint ouvert.

    Le front porte des gardes, mais ils ne protegent rien : ils evitent
    d'ouvrir un ecran vide. La seule protection reelle est cote serveur.
    Seule `/connexion` est legitimement ouverte — on ne peut pas exiger une
    session pour en ouvrir une.
    """
    from config.api import api

    ouvertes = []
    for prefixe, routeur in api._routers:
        for chemin, vue in routeur.path_operations.items():
            for operation in vue.operations:
                complet = f"{prefixe}{chemin}"
                if not operation.auth_callbacks and complet != "/connexion":
                    ouvertes.append(f"{operation.methods} {complet}")

    assert ouvertes == [], f"Routes sans authentification : {ouvertes}"


def test_le_premier_parametre_de_chaque_route_s_appelle_request():
    """
    Filet. django-ninja ne reconnait le parametre de requete que par son NOM
    (`if name == "request"`). Nomme autrement — `requete`, par exemple, ce que
    la convention francaise du projet appelle naturellement —, il devient un
    parametre de requete HTTP obligatoire et la route repond 422 « Field
    required » a chaque appel.

    Rien ne le signale au demarrage : la route se monte, elle s'affiche dans
    l'OpenAPI, et elle echoue seulement quand on l'appelle. C'est arrive : les
    trois routes de session ont ete ecrites ainsi et personne ne s'en est
    apercu avant le premier test HTTP.
    """
    import inspect

    from config.api import api

    fautives = []
    for prefixe, routeur in api._routers:
        for chemin, vue in routeur.path_operations.items():
            for operation in vue.operations:
                parametres = list(inspect.signature(operation.view_func).parameters)
                if not parametres or parametres[0] != "request":
                    fautives.append(f"{prefixe}{chemin} — {parametres[:1] or 'aucun parametre'}")

    assert fautives == [], f"Premier parametre mal nomme : {fautives}"


def test_toute_route_d_ecriture_inscrit_un_evenement():
    """
    Filet. « Toute ecriture metier inscrit un evenement. Sans exception. »
    §18 pour les activites, §10 et §23 pour les courriers, RNF-TRACE-01 pour
    le reste.

    Une regle qui ne repose que sur la vigilance est une regle qui tombe au
    premier endpoint ecrit un vendredi soir. Le filet remonte la chaine des
    appels depuis chaque route de mutation et cherche `inscrire`.

    Il ne prouve pas que l'appel est atteint a l'execution — un test unitaire
    par geste s'en charge. Il prouve qu'on y a pense.
    """

    from config.api import api

    MUTATIONS = {"POST", "PATCH", "PUT", "DELETE"}
    #: `/connexion` et `/deconnexion` sont des mutations de session, pas des
    #: ecritures metier. La connexion est deja tracee par `journal_acces`.
    #: Ouvrir une notification n'est pas une ecriture metier : c'est faire
    #: disparaitre une pastille. L'acte qui a produit la notification est,
    #: lui, deja journalise — inscrire un evenement pour son echo ferait
    #: grossir l'histoire du dossier de lignes qui ne racontent rien de plus
    #: (ADR 012, ADR 018). Ce n'est pas non plus un acces au sens de
    #: `tracer_acces`, qui sert a savoir qui a regarde un dossier.
    #:
    #: Le pilier suivi ajoute quatre gestes qui ne sont pas des ecritures
    #: metier mais des outils personnels de l'agent :
    #:
    #:  * la **recherche avancee** est une lecture, postee parce que dix
    #:    criteres ne tiennent pas dans une URL et que les mots-cles d'une
    #:    recherche n'ont rien a faire dans les journaux d'un proxy ;
    #:  * les **recherches conservees** sont un confort d'affichage, comme un
    #:    signet — les inscrire ferait grossir l'histoire du dossier de lignes
    #:    qui ne disent rien de lui ;
    #:  * les **taches du dossier** sont un pense-bete qui n'engage que son
    #:    auteur : une case cochee par erreur se decoche, et ce n'est pas une
    #:    trace opposable ;
    #:  * les **notes de travail** sont dispensees par une decision ecrite —
    #:    [ADR 042](../../docs/architecture/042-la-note-de-travail-est-une-table-a-part.md).
    #:    Un evenement aurait annonce a toute la fiche de vie l'existence d'un
    #:    texte que la fiche de vie ne montre pas : la trace aurait trahi ce
    #:    que la note protege.
    DISPENSEES = {
        "/connexion",
        "/deconnexion",
        "/notifications/{notification_id}/lecture",
        "/notifications/lecture",
        "/suivi/recherche",
        "/suivi/recherches",
        "/suivi/recherches/{int:recherche_id}",
        "/suivi/dossiers/{int:identifiant}/taches",
        "/suivi/dossiers/{int:identifiant}/taches/{int:tache_id}",
        "/suivi/dossiers/{int:identifiant}/notes",
    }

    muettes = []
    for prefixe, routeur in api._routers:
        for chemin, vue in routeur.path_operations.items():
            for operation in vue.operations:
                complet = f"{prefixe}{chemin}"
                if not (set(operation.methods) & MUTATIONS) or complet in DISPENSEES:
                    continue

                source = _chaine_d_appels(operation.view_func)

                if "inscrire(" not in source:
                    muettes.append(f"{operation.methods} {complet}")

    assert muettes == [], f"Routes d'ecriture sans inscription au journal : {muettes}"


def _chaine_d_appels(depart, profondeur: int = 3) -> str:
    """
    Le code de la fonction, plus celui de ce qu'elle appelle, en cascade.

    Deux precautions apprises en branchant le pilier activites :

     * **deux ecritures d'appel** coexistent au depot — `declarer_delegation(...)`
       sur un service importe nommement, et `services.creer_activite(...)` sur un
       module importe en bloc. N'en reconnaitre qu'une declarerait muet tout un
       pilier qui trace pourtant chacune de ses ecritures ;
     * **plusieurs niveaux**. `changer_etat_plan` delegue a `_soumettre`, qui
       inscrit. S'arreter au premier niveau punirait la decomposition en
       sous-fonctions, c'est-a-dire le bon code.

    La profondeur est bornee : au-dela, le filet lirait la moitie du depot pour
    un gain nul.
    """
    import inspect
    import re

    vus: set = set()
    source = ""

    def _descendre(fonction, reste: int) -> None:
        nonlocal source
        if reste < 0 or fonction in vus:
            return
        vus.add(fonction)
        try:
            corps = inspect.getsource(fonction)
        except (OSError, TypeError):
            return
        source += corps
        module = inspect.getmodule(fonction)
        for prefixe, nom in re.findall(
            r"\b(?:([a-z_][a-z0-9_]*)\.)?([a-z_][a-z0-9_]*)\s*\(", corps
        ):
            porteur = getattr(module, prefixe, module) if prefixe else module
            cible = getattr(porteur, nom, None)
            if inspect.isfunction(cible):
                _descendre(cible, reste - 1)

    _descendre(depart, profondeur)
    return source


def test_les_gardes_verifient_bien_la_permission(agent, rf):
    """Filet. Une permission absente doit refuser, pas laisser passer."""
    garde = ExigePermission(PERM.ACT_VAL)
    requete = rf.get("/api/activites")
    requete.user = agent

    assert garde.authenticate(requete, "") is None

    UtilisateurProfil.objects.create(utilisateur=agent, profil=Profil.objects.get(code="DCG"))

    assert garde.authenticate(requete, "") == agent


def test_toute_tache_ecrite_est_planifiee():
    """
    Filet transverse. **Une tache ecrite mais jamais planifiee ne s'execute
    pas** — et l'echec est silencieux : le worker demarre, le code existe, et
    rien ne tourne jamais.

    La liste n'est pas enumeree a la main : elle se derive de ce que Celery a
    decouvert. Une version qui citait les taches d'un seul pilier a laisse
    passer trois taches de gouvernance non planifiees, ce qui est exactement le
    defaut que ce filet devait attraper.

    Si une tache doit un jour rester a la demande — un rattrapage lance par un
    exploitant, par exemple — inscrivez-la dans `A_LA_DEMANDE` avec sa raison.
    Le silence, lui, n'est pas une raison.
    """
    from django.conf import settings

    from config.celery import app

    #: Taches volontairement non planifiees, avec leur motif.
    A_LA_DEMANDE: set[str] = set()

    app.loader.import_default_modules()
    ecrites = {nom for nom in app.tasks if not nom.startswith("celery.")} - A_LA_DEMANDE
    planifiees = {entree["task"] for entree in settings.CELERY_BEAT_SCHEDULE.values()}

    assert ecrites == planifiees, (
        f"Ecrites mais non planifiees : {sorted(ecrites - planifiees)} ; "
        f"planifiees mais inexistantes : {sorted(planifiees - ecrites)}"
    )
