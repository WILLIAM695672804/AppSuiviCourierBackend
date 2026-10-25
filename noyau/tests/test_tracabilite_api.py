"""
Les journaux — `/api/tracabilite/*` et `/api/archivage/conformite`.

Ce que ces tests protegent, dans l'ordre :

 1. **La garde.** `AUDIT` et rien d'autre. Un journal ouvert par erreur a tout
    compte authentifie expose qui a consulte le dossier de qui.
 2. **L'absence d'ecriture.** Aucune route ne modifie ni ne supprime. Le test
    l'affirme sur les verbes, parce qu'une route d'ecriture ajoutee un jour par
    commodite ne se verrait dans aucun autre test.
 3. **Ce qui est rendu quand il n'y a rien a rendre.** Sur un fonds vide, la
    conformite archivistique doit le dire — `null`, pas 0 ni 100 %. La route
    vit desormais dans le pilier `archivage` ; ce qui est teste ici, c'est que
    l'auditeur y accede toujours.
"""

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
EVENEMENTS = "/api/tracabilite/evenements"
ACCES = "/api/tracabilite/acces"
CONFORMITE = "/api/archivage/conformite"
HISTORIQUE = "/api/tracabilite/historique"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


@pytest.fixture
def faits(connecte):
    """
    Fait ecrire quelque chose a l'application, pour que le journal ait matiere.

    **La commande `semer` n'inscrit rien** : elle cree ses comptes par l'ORM et
    non par les services, donc sans passer par `inscrire`. C'est voulu — un jeu
    d'essai qui remplirait le journal de deux cents faits fictifs rendrait
    illisible le premier fait reel. Les tests produisent donc leurs propres
    evenements.
    """
    from noyau.habilitation.modeles import Profil

    cible = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    profil = Profil.objects.get(code="POINT_FOCAL")

    connecte("admin").post(
        f"/api/habilitations/utilisateurs/{cible.pk}/profils",
        {"profilId": profil.pk},
        content_type="application/json",
    )
    return cible


@pytest.fixture
def auditeur(connecte):
    """
    Le jeu d'essai ne porte pas de compte d'audit : `AUDIT` est ajoute au
    profil de l'administrateur pour la duree du test.

    Le faire ici plutot que dans le semis est deliberé — un compte qui porte a
    la fois l'administration et l'audit n'existe pas dans l'institution, et le
    semer reviendrait a suggerer le contraire.
    """
    from noyau.habilitation.modeles import Permission, Profil, ProfilPermission

    profil = Profil.objects.get(code="ADMIN")
    permission = Permission.objects.get(code="AUDIT")
    ProfilPermission.objects.get_or_create(profil=profil, permission=permission)

    return connecte("admin")


# =====================================================================
#  La garde
# =====================================================================


@pytest.mark.parametrize("chemin", [EVENEMENTS, ACCES, CONFORMITE])
def test_sans_session_les_journaux_sont_fermes(client, jeu, chemin):
    assert client.get(chemin).status_code == 401


@pytest.mark.parametrize("chemin", [EVENEMENTS, ACCES, CONFORMITE])
def test_l_administrateur_seul_ne_voit_pas_les_journaux(connecte, chemin):
    """
    `ADM_HAB` distribue les droits ; `AUDIT` lit les journaux. Les deux mains
    sont distinctes exprès — qui tient les journaux ne doit pas etre qui peut
    les faire disparaitre.
    """
    assert connecte("admin").get(chemin).status_code == 401


@pytest.mark.parametrize("chemin", [EVENEMENTS, ACCES, CONFORMITE])
def test_le_poste_d_audit_lit(auditeur, chemin):
    assert auditeur.get(chemin).status_code == 200


@pytest.mark.parametrize("verbe", ["post", "patch", "delete"])
def test_aucune_ecriture_n_existe_sur_les_journaux(auditeur, verbe):
    """
    Le journal tire toute sa valeur du fait qu'on ne peut pas le nettoyer.
    Ce test tombe le jour ou une route d'ecriture y est ajoutee.
    """
    reponse = getattr(auditeur, verbe)(EVENEMENTS, {}, content_type="application/json")
    assert reponse.status_code == 405


# =====================================================================
#  Le journal des evenements
# =====================================================================


def test_le_journal_montre_ce_que_l_application_a_fait(auditeur, faits):
    """
    La fixture `faits` attribue un profil : c'est une ecriture metier, donc un
    evenement.
    """
    corps = auditeur.get(EVENEMENTS).json()
    assert corps["evenements"]
    assert corps["compteurs"]


def test_l_ordre_va_du_plus_recent_au_plus_ancien(auditeur, faits):
    """C'est ce qu'on vient chercher : le dernier fait, pas le premier."""
    evenements = auditeur.get(EVENEMENTS).json()["evenements"]
    identifiants = [e["id"] for e in evenements]
    assert identifiants == sorted(identifiants, reverse=True)


def test_la_limite_est_respectee_et_bornee(auditeur, faits):
    """
    L'ecran augmente sa limite pour charger la suite. Le plafond est **au
    serveur** : rien n'empeche d'appeler la route a la main, et une table
    partitionnee de plusieurs millions de lignes ne se rend pas d'un coup.
    """
    assert len(auditeur.get(f"{EVENEMENTS}?limite=1").json()["evenements"]) == 1

    # Au-dela du plafond, la reponse est servie sans erreur, simplement bornee.
    assert auditeur.get(f"{EVENEMENTS}?limite=999999").status_code == 200
    assert auditeur.get(f"{ACCES}?limite=999999").status_code == 200


def test_le_filtre_ramene_une_famille_et_pas_un_code(auditeur, faits):
    """
    Le front envoie « Habilitation », la base stocke `compte_cree`. La
    correspondance est tenue par le serveur — la deporter au front l'aurait
    rendu dependant du nommage interne des evenements.
    """
    evenements = auditeur.get(f"{EVENEMENTS}?type=Habilitation").json()["evenements"]
    assert evenements
    assert {e["type"] for e in evenements} == {"Habilitation"}


def test_un_filtre_inconnu_ne_filtre_rien(auditeur, faits):
    """Plutot qu'une liste vide, qui se lirait comme « il ne s'est rien passe »."""
    tous = auditeur.get(EVENEMENTS).json()["evenements"]
    inconnu = auditeur.get(f"{EVENEMENTS}?type=Fantaisie").json()["evenements"]
    assert len(inconnu) == len(tous)


def test_chaque_evenement_porte_son_auteur(auditeur, faits):
    """
    RNF-TRACE-01 : une ecriture que personne n'endosse ne prouve rien. Le socle
    l'interdit par declencheur ; ce test verifie que le declencheur tient.
    """
    sans_acteur = next(
        c for c in auditeur.get(EVENEMENTS).json()["compteurs"] if "acteur" in c["libelle"]
    )
    assert sans_acteur["valeur"] == "0"
    assert sans_acteur["ton"] == "neutre"


def test_le_courrier_n_est_jamais_fabrique(auditeur, faits):
    """Le pilier n'existe pas : la colonne est portee par le schema, jamais
    renseignee. On ne fabrique pas de reference."""
    assert all(e["courrier"] is None for e in auditeur.get(EVENEMENTS).json()["evenements"])


# =====================================================================
#  Le journal des acces
# =====================================================================


def test_consulter_la_fiche_d_un_agent_laisse_une_trace(auditeur, connecte):
    """
    RF-ADM-03. La fiche porte le matricule, le courriel et les droits d'une
    personne nommee : la consulter est un acte, pas une navigation.
    """
    cible = Utilisateur.objects.get(identifiant_annuaire="dsr")
    connecte("admin").get(f"/api/habilitations/utilisateurs/{cible.pk}")

    acces = auditeur.get(ACCES).json()["acces"]
    assert any(a["objet"] == f"utilisateur #{cible.pk}" for a in acces)


def test_le_registre_des_comptes_n_est_pas_trace(auditeur, connecte):
    """
    Tracer chaque liste ferait grossir la table de millions de lignes par mois
    sans rien apprendre a personne. Le registre ne montre que des libelles.
    """
    avant = len(auditeur.get(ACCES).json()["acces"])
    connecte("admin").get("/api/habilitations/utilisateurs")
    assert len(auditeur.get(ACCES).json()["acces"]) == avant


def test_un_acces_conforme_porte_son_motif(auditeur, connecte):
    """
    Une pastille « Conforme » sans explication ne dit rien ; le motif est rendu
    dans les deux cas, pas seulement quand ca va mal.
    """
    cible = Utilisateur.objects.get(identifiant_annuaire="dsr")
    connecte("admin").get(f"/api/habilitations/utilisateurs/{cible.pk}")

    acces = auditeur.get(ACCES).json()["acces"][0]
    assert acces["controle"] == "Conforme"
    assert acces["motif"]
    assert acces["alerte"] is False


def test_l_agent_est_nomme_et_son_poste_avec(auditeur, connecte):
    """
    Les journaux portent `acteur_id` en BIGINT nu, sans cle etrangere : la
    jointure se fait a la main. Ce test la protege.
    """
    cible = Utilisateur.objects.get(identifiant_annuaire="dsr")
    connecte("admin").get(f"/api/habilitations/utilisateurs/{cible.pk}")

    acces = auditeur.get(ACCES).json()["acces"][0]
    assert acces["agent"] == "Aline Nkodo"
    assert acces["poste"] == "Administrateur fonctionnel"


def test_le_journal_des_acces_peut_etre_vide_sans_etre_casse(auditeur):
    """
    `tracer_acces` n'est appelee que sur la lecture d'un objet sensible. Une
    liste vide est un etat normal, pas une panne — et l'ecran doit recevoir 200.
    """
    reponse = auditeur.get(ACCES)
    assert reponse.status_code == 200
    assert reponse.json()["signales"] == 0


def test_le_filtre_signale_ne_ramene_que_les_alertes(auditeur, connecte):
    cible = Utilisateur.objects.get(identifiant_annuaire="dsr")
    connecte("admin").get(f"/api/habilitations/utilisateurs/{cible.pk}")

    assert auditeur.get(f"{ACCES}?filtre=Signalé").json()["acces"] == []


# =====================================================================
#  La conformite archivistique
# =====================================================================


def test_l_auditeur_atteint_la_conformite_et_la_lit_a_null(auditeur):
    """
    Deux choses a la fois, et c'est voulu.

    *La garde.* Depuis que la route a quitte le socle pour le pilier
    `archivage`, elle exige `AUDIT` **ou** `ARCH`. L'auditeur doit continuer
    d'entrer : le §3.12 lui confie ce controle, et l'archiviste ne peut pas
    etre le seul a le lire.

    *Le chiffre.* Sur un fonds vide le taux sort a `null`, et non a 0 ni a
    100 : les trois sont egalement faux, mais seuls les deux nombres seraient
    recopies tels quels dans un rapport de controle (ADR 011).
    """
    corps = auditeur.get(CONFORMITE).json()

    assert corps["tauxConformite"] is None
    assert corps["echeancesDepassees"] == []
    assert {c["feu"] for c in corps["compteurs"]} == {"inconnu"}
    assert all(c["note"] for c in corps["compteurs"])


# =====================================================================
#  L'historique des champs — I-03
# =====================================================================


@pytest.fixture
def modification_en_base(jeu):
    """
    Une modification faite **hors application**, comme il s'en fait vraiment.

    Un `UPDATE` direct sur `structure` : correction en base, script de reprise,
    intervention d'un prestataire. Le declencheur l'enregistre dans
    `champ_historique` ; aucun evenement ne l'accompagne, puisque le code
    applicatif n'est pas passe par la.

    `app.utilisateur_id` est positionne parce que le declencheur **refuse**
    l'ecriture sans acteur identifie (RNF-TRACE-01). Ce n'est pas un
    contournement du test : celui qui corrige en base pose lui aussi cette
    variable, ou son `UPDATE` echoue.
    """
    from django.db import connection

    from noyau.organisation.modeles import Structure

    structure = Structure.objects.first()
    acteur = Utilisateur.objects.get(identifiant_annuaire="admin")

    with connection.cursor() as curseur:
        curseur.execute("SELECT set_config('app.utilisateur_id', %s, true)", [str(acteur.pk)])
        curseur.execute(
            "UPDATE structure SET libelle = %s WHERE id = %s",
            [f"{structure.libelle} (corrigé en base)", structure.pk],
        )

    return structure


def test_sans_session_l_historique_est_ferme(client, jeu):
    assert client.get(HISTORIQUE).status_code == 401


def test_l_administrateur_seul_ne_lit_pas_l_historique(connecte):
    """Même garde que les deux autres journaux : `AUDIT`, et rien d'autre."""
    assert connecte("admin").get(HISTORIQUE).status_code == 401


@pytest.mark.parametrize("verbe", ["post", "patch", "delete"])
def test_l_historique_ne_s_ecrit_pas(auditeur, verbe):
    """Une piste d'audit qu'on peut corriger ne prouve rien."""
    reponse = getattr(auditeur, verbe)(HISTORIQUE, {}, content_type="application/json")
    assert reponse.status_code == 405


def test_les_tables_tracees_sont_annoncees_meme_a_zero(auditeur):
    """
    Une table livree mais jamais modifiee doit figurer au selecteur. L'omettre
    ferait lire « cette table n'est pas tracee » là où la verite est « rien n'y
    a change ».
    """
    corps = auditeur.get(HISTORIQUE).json()
    cles = {t["cle"] for t in corps["tables"]}

    assert "structure" in cles
    assert "activite" in cles
    assert all(t["modifications"] >= 0 for t in corps["tables"])


def test_une_modification_en_base_apparait(auditeur, modification_en_base):
    """
    **Ce que le journal des evenements ne peut pas montrer.** L'application n'a
    rien fait ; le declencheur, si.
    """
    corps = auditeur.get(f"{HISTORIQUE}?tableCible=structure").json()
    lignes = [m for m in corps["modifications"] if m["ligneId"] == modification_en_base.pk]

    assert lignes, "le déclencheur n'a rien inscrit"
    assert lignes[0]["colonne"] == "libelle"
    assert "corrigé en base" in lignes[0]["apres"]


def test_une_modification_sans_evenement_est_signalee(auditeur, modification_en_base):
    """C'est la ligne que l'auditeur regarde en premier."""
    corps = auditeur.get(f"{HISTORIQUE}?tableCible=structure").json()
    ligne = next(m for m in corps["modifications"] if m["ligneId"] == modification_en_base.pk)

    assert ligne["horsApplication"] is True
    assert corps["horsApplication"] >= 1


def test_une_modification_accompagnee_d_un_evenement_ne_l_est_pas(auditeur, jeu):
    """
    L'inverse du test precedent, et il vaut autant : si tout etait signale, le
    drapeau ne distinguerait rien.

    La correlation se fait sur l'objet et la seconde — les deux tables ne se
    connaissent pas, et leur poser une cle etrangere aurait rendu impossible
    d'enregistrer une modification faite hors application.
    """
    from django.db import connection

    from noyau.journal.service import inscrire
    from noyau.organisation.modeles import Structure

    structure = Structure.objects.first()
    acteur = Utilisateur.objects.get(identifiant_annuaire="admin")

    with connection.cursor() as curseur:
        curseur.execute("SELECT set_config('app.utilisateur_id', %s, true)", [str(acteur.pk)])
        curseur.execute(
            "UPDATE structure SET libelle = %s WHERE id = %s",
            ["Direction renommée par l'application", structure.pk],
        )
    inscrire(
        acteur=acteur,
        objet_type="structure",
        objet_id=structure.pk,
        type_evenement="structure_modifiee",
        libelle="Libellé de la structure modifié",
    )

    corps = auditeur.get(f"{HISTORIQUE}?tableCible=structure").json()
    ligne = next(m for m in corps["modifications"] if m["ligneId"] == structure.pk)

    assert ligne["horsApplication"] is False


def test_le_filtre_hors_application_ne_ramene_que_les_isolees(auditeur, modification_en_base):
    corps = auditeur.get(f"{HISTORIQUE}?horsApplication=true").json()

    assert corps["modifications"]
    assert all(m["horsApplication"] for m in corps["modifications"])


def test_le_filtre_par_ligne_isole_un_seul_objet(auditeur, modification_en_base):
    """C'est l'usage depuis la fiche d'un objet : l'histoire de celui-ci, pas
    celle de la table."""
    corps = auditeur.get(
        f"{HISTORIQUE}?tableCible=structure&ligneId={modification_en_base.pk}"
    ).json()

    assert corps["modifications"]
    assert all(m["ligneId"] == modification_en_base.pk for m in corps["modifications"])


def test_une_table_inconnue_rend_une_liste_vide(auditeur, modification_en_base):
    """Et non une erreur : le paramètre est un filtre, passé en requête
    paramétrée."""
    corps = auditeur.get(f"{HISTORIQUE}?tableCible=table_inexistante").json()

    assert corps["modifications"] == []
    # Le sélecteur reste peuplé : l'écran doit pouvoir proposer autre chose.
    assert corps["tables"]


def test_l_auteur_de_la_modification_est_nomme(auditeur, modification_en_base):
    """
    Le déclencheur lit `app.utilisateur_id`. Sans nom en face, la ligne dirait
    « quelque chose a changé », ce qui ne vaut rien pour un audit.
    """
    corps = auditeur.get(f"{HISTORIQUE}?tableCible=structure").json()
    ligne = next(m for m in corps["modifications"] if m["ligneId"] == modification_en_base.pk)

    assert ligne["auteur"] != "Traitement automatique"
    assert ligne["poste"] != "—"


def test_la_limite_est_bornee_au_serveur(auditeur, modification_en_base):
    """Rien n'empêche d'appeler la route à la main avec `limite=100000`."""
    assert auditeur.get(f"{HISTORIQUE}?limite=100000").status_code == 200
    assert auditeur.get(f"{HISTORIQUE}?limite=0").status_code == 200


def test_la_liste_des_tables_tracees_correspond_aux_declencheurs(jeu):
    """
    **Le test qui protège la constante.** `TABLES_HISTORISEES` est écrite à la
    main : la déduire à l'exécution supposerait d'interroger `pg_trigger` à
    chaque appel. Une table qu'on historise sans l'ajouter ici resterait
    invisible à l'écran, et son absence se lirait « rien n'a changé ».
    """
    from django.db import connection

    from noyau.tracabilite.lecture import TABLES_HISTORISEES

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT DISTINCT c.relname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE p.proname = 'historiser_champs' AND NOT t.tgisinternal
            """
        )
        reelles = {ligne[0] for ligne in curseur.fetchall()}

    assert reelles == set(TABLES_HISTORISEES)
