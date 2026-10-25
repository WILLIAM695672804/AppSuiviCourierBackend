"""
Les comptes de demonstration, poses sur les **postes reels**.

Un compte sans perimetre ne voit rien, un compte sans poste n'a pas de
hierarchie, et un compte sans affectation datee n'a jamais pris ses fonctions.
Les trois sont posees ici, faute de quoi la demonstration livrerait des comptes
qui se connectent et n'affichent aucune donnee — ce qu'on prendrait pour une
panne ailleurs.

**Aucun poste n'est cree.** `charger_organigramme` en a pose 82, un par
structure au moins ; les comptes s'y installent. Creer un poste « Directeur »
a cote de celui de l'organigramme aurait donne deux sommets a la meme structure,
et `responsables_comptes()` en aurait designe un au hasard.

La couverture vise les **profils**, pas les personnes : chaque profil qui ouvre
un ecran a au moins un titulaire, sinon l'ecran n'est ouvrable par personne et
se lit comme un 403. Deux points focaux de directions differentes sont
indispensables — c'est la seule facon de verifier qu'un agent ne voit pas le
plan du voisin.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import CommandError

from noyau.habilitation.modeles import Profil, UtilisateurProfil
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.organisation.modeles import AffectationPoste, Poste, Structure
from noyau.perimetre.modeles import Perimetre

MOT_DE_PASSE_DEFAUT = "demonstration"

#: (identifiant, prenom, nom, code structure, profil(s), portee, session courrier)
#:
#: Le champ « profil » accepte un code ou un tuple de codes. Un seul compte en
#: porte deux — le chef de cabinet, qui est a la fois responsable de sa
#: structure et cabinet du Directeur general. Le prevoir pour tous plutot que de
#: traiter ce cas a part evite la ligne d'exception qu'on oublie de deplacer.
#:
#: Le poste n'est pas nomme : il est **retrouve** dans la structure, par la
#: meme regle que `responsables_comptes()` — le poste sans superieur, du rang le
#: plus eleve. Le nommer aurait fige dans ce fichier des libelles que
#: l'organigramme peut reecrire, et le semis aurait casse au premier
#: rechargement.
#:
#: Quand plusieurs comptes visent la meme structure, le premier prend le poste
#: de responsable et les suivants un poste secondaire de cette structure, s'il
#: en existe un.
COMPTES = [
    # --- La Direction generale et son cabinet -------------------------
    ("dg", "Emmanuel", "Kingue", "DG", "DG", "toutes", None),
    ("admin", "Aline", "Nkodo", "DG", "ADMIN", "toutes", None),
    # Deux profils, et une portee `toutes`. Arbitrage du 28 aout 2026 : « c'est
    # chez moi que l'on enregistre et que l'on cote les ordres du directeur, car
    # le directeur ne le fait pas ». `CABINET` porte `ENR` et `COT_DEL` — la
    # frappe au nom du Directeur general ; `RESP` reste pour ce que le cabinet
    # decide en propre. Voir ADR 039.
    ("chef.cab", "Georges", "Eyenga", "CAB", ("RESP", "CABINET"), "toutes", None),
    # Le Service du courrier central : deux agents de session, sur deux
    # registres. Un seul aurait laisse le registre confidentiel sans tenue —
    # et le rattachement a ce registre **est** l'acte d'habilitation (ADR 024).
    ("agent.scc", "Marthe", "Fouda", "SCC", "AGENT_SESS", "structure", "arrive"),
    ("agent.conf", "Pauline", "Abega", "CAB-SEC-DG", "AGENT_SESS", "structure", "confidentiel"),
    ("agent.int", "Andre", "Kamdem", "CAB-SEC-DGA", "AGENT_SESS", "structure", "interne"),
    # --- Le suivi, le controle, l'audit -------------------------------
    ("dsr", "Serge", "Mbarga", "DSR", "DSR", "toutes", None),
    ("att.dsr", "Nadege", "Etoa", "DSR", "ATT_DSR", "toutes", None),
    ("dcg", "Paul", "Ndongo", "DCG", "DCG", "toutes", None),
    ("focal.dcg", "Irene", "Ngo Bell", "DCG-MPE", "POINT_FOCAL", "structure", None),
    ("auditeur", "Michel", "Onana", "DAI", "AUDITEUR", "toutes", None),
    # --- Les directions du Comite de direction ------------------------
    #
    # Le CODIR est le conseil des directeurs : chacun y siege sans cesser de
    # repondre de sa branche, d'ou la portee `sous_arbre` et non `toutes`.
    ("dir.dfc", "Estelle", "Mbida", "DFC", "CODIR", "sous_arbre", None),
    ("dir.dexp", "Solange", "Tchouta", "DEXP", "CODIR", "sous_arbre", None),
    ("dir.dsi", "Rita", "Owona", "DSI", "CODIR", "sous_arbre", None),
    ("dir.drh", "Alphonse", "Bikoi", "DRH", "CODIR", "sous_arbre", None),
    ("dir.daj", "Christine", "Meka", "DAJ", "CODIR", "sous_arbre", None),
    ("dir.dag", "Roger", "Tchoumi", "DAG", "CODIR", "sous_arbre", None),
    ("dir.damp", "Vincent", "Ekedi", "DAMP", "CODIR", "sous_arbre", None),
    ("dir.dcap", "Armand", "Nyobe", "DCAP", "CODIR", "sous_arbre", None),
    # --- Les points focaux, qui saisissent les activites --------------
    #
    # Trois directions differentes : le cloisonnement ne se verifie qu'a
    # plusieurs.
    ("focal.dsi", "Yves", "Manga", "DSI-GL", "POINT_FOCAL", "structure", None),
    ("focal.dfc", "Clarisse", "Belinga", "DFC-CPT", "POINT_FOCAL", "structure", None),
    ("focal.dexp", "Bernard", "Sone", "DEXP-OP", "POINT_FOCAL", "structure", None),
    ("focal.drh", "Sylvie", "Atangana", "DRH-GP", "POINT_FOCAL", "structure", None),
    # --- Ceux qui traitent ---------------------------------------------
    ("agent.dsi", "Joseph", "Ateba", "DSI-ISI", "COLLAB", "propre", None),
    ("agent.dfc", "Thierry", "Njike", "DFC-FIN-CR", "COLLAB", "propre", None),
    ("agent.daj", "Laure", "Ombga", "DAJ-EJC", "COLLAB", "propre", None),
    # --- L'exploitation, qui releve et qui recouvre ---------------------
    #
    # Le profil EXPLOITATION porte `EXP_SAI` et **pas** `EXP_LEC` : chacune voit
    # ce qu'elle mesure et rien des chiffres de l'autre. Deux comptes, donc.
    ("chef.ddlm", "Blaise", "Ngoma", "DDLM", "EXPLOITATION", "structure", None),
    ("chef.dexp", "Honore", "Mvondo", "DEXP-CFM", "EXPLOITATION", "structure", None),
    # --- Le fonds et la plateforme --------------------------------------
    ("archiviste", "Bertrand", "Nnomo", "CDA", "ARCHIVISTE", "toutes", None),
    ("admin.tech", "Herve", "Njoya", "DSI-SSI", "ADMIN_TECH", "toutes", None),
]

#: Les usagers du portail — **sans structure, sans poste, sans perimetre**.
#:
#: Ce n'est pas un oubli : la restriction du portail est `deposant = moi`, ecrite
#: dans `portail/lecture.py` et independante du perimetre du socle (ADR 013). Un
#: perimetre pose sur un usager ouvrirait `restreindre()` a quelqu'un qui ne
#: travaille pas ici, et prouverait le contraire de ce que le portail affirme.
#:
#: Deux comptes, parce qu'un portail eprouve avec un seul ne prouve rien du
#: cloisonnement.
USAGERS = [
    ("usager.sotrapal", "Aicha", "Bello", "contact@sotrapal.cm"),
    ("usager.camtrans", "Didier", "Essomba", "direction@camtrans.cm"),
    ("usager.maersk", "Frank", "Diedhiou", "douala@maersk-cm.com"),
]


def semer(mot_de_passe: str, ecrire) -> dict[str, Utilisateur]:
    """
    Pose les comptes et rend l'annuaire de la demonstration, par identifiant.

    Les modules suivants s'en servent pour designer un acteur : c'est le seul
    endroit qui sait quel agent joue quel role, et le passer de main en main
    evite que chacun le retrouve par une requete a lui.
    """
    profils = {p.code: p for p in Profil.objects.all()}
    sessions = {s.code: s for s in SessionCourrier.objects.all()}
    structures = {s.code: s for s in Structure.objects.filter(valide_au__isnull=True)}

    annuaire: dict[str, Utilisateur] = {}
    pris: set[int] = set()

    for identifiant, prenom, nom, code_structure, codes_profil, portee, code_session in COMPTES:
        structure = structures.get(code_structure)
        if structure is None:
            raise CommandError(
                f"Structure « {code_structure} » absente. L'organigramme reel "
                "est-il charge ? (manage.py charger_organigramme)"
            )
        attendus = (codes_profil,) if isinstance(codes_profil, str) else codes_profil
        for code_profil in attendus:
            if code_profil not in profils:
                raise CommandError(f"Profil « {code_profil} » absent du referentiel.")

        poste = _poste_libre(structure, pris)
        utilisateur, cree = Utilisateur.objects.get_or_create(
            identifiant_annuaire=identifiant,
            defaults={
                "prenom": prenom,
                "nom": nom,
                "structure": structure,
                "poste": poste,
                "courriel": f"{identifiant}@pad.cm",
            },
        )
        # Le poste peut avoir change entre deux passages — l'organigramme est
        # rechargeable. Le compte suit, sinon il resterait rattache a un poste
        # clos et disparaitrait des selecteurs sans qu'on sache pourquoi.
        if utilisateur.poste_id != poste.pk or utilisateur.structure_id != structure.pk:
            utilisateur.poste = poste
            utilisateur.structure = structure
            utilisateur.save(update_fields=["poste", "structure"])

        # Toujours reinitialise : sur un jeu de demonstration, un mot de passe
        # qu'on ne connait plus est un compte perdu.
        utilisateur.set_password(mot_de_passe)
        utilisateur.save(update_fields=["mot_de_passe"])

        pris.add(poste.pk)
        annuaire[identifiant] = utilisateur

        for code_profil in attendus:
            _attribuer_profil(utilisateur, profils[code_profil])
        _poser_perimetre(utilisateur, portee, structure)
        _ouvrir_affectation(utilisateur, poste)
        if code_session:
            _rattacher_session(utilisateur, sessions[code_session])

        if cree:
            ecrire(f"  compte {identifiant} — {structure.code}")

    for identifiant, prenom, nom, courriel in USAGERS:
        utilisateur, cree = Utilisateur.objects.get_or_create(
            identifiant_annuaire=identifiant,
            defaults={"prenom": prenom, "nom": nom, "courriel": courriel},
        )
        utilisateur.set_password(mot_de_passe)
        utilisateur.save(update_fields=["mot_de_passe"])
        _attribuer_profil(utilisateur, profils["EXTERNE"])
        annuaire[identifiant] = utilisateur
        if cree:
            ecrire(f"  usager {identifiant}")

    return annuaire


def _poste_libre(structure: Structure, pris: set[int]) -> Poste:
    """
    Un poste de la structure, celui de responsable en priorite.

    Le tri reprend celui de `responsables_comptes()` — poste sans superieur
    d'abord, puis rang hierarchique — pour que le **premier** compte pose sur
    une structure en devienne le responsable. Deux tris differents auraient
    designe deux responsables selon qu'on lise l'annuaire ou qu'on notifie.

    A defaut de poste libre, le poste de responsable est repris : plusieurs
    agents sur un poste a `effectif_prevu` superieur a un est le cas normal —
    « Attache de suivi » en compte deux, « Auditeur principal » trois.
    """
    postes = list(
        Poste.objects.filter(structure=structure, valide_au__isnull=True)
        .select_related("niveau_hierarchique")
        .order_by("poste_superieur_id", "niveau_hierarchique__rang", "libelle")
    )
    if not postes:
        raise CommandError(
            f"La structure « {structure.code} » n'a aucun poste ouvert : "
            "un compte ne peut pas s'y rattacher."
        )
    for poste in postes:
        if poste.pk not in pris:
            return poste
    return postes[0]


def _attribuer_profil(utilisateur: Utilisateur, profil: Profil) -> None:
    UtilisateurProfil.objects.get_or_create(
        utilisateur=utilisateur, profil=profil, retire_le__isnull=True
    )


def _poser_perimetre(utilisateur: Utilisateur, portee: str, structure: Structure) -> None:
    """
    Un agent **sans perimetre ne voit rien** — regle 3 de
    `noyau/perimetre/portee.py`. La portee `toutes` ne porte pas de structure :
    elle ne borne rien.
    """
    Perimetre.objects.get_or_create(
        utilisateur=utilisateur,
        valide_au__isnull=True,
        defaults={
            "portee": portee,
            "structure": None if portee == "toutes" else structure,
            "valide_du": date.today(),
        },
    )


def _ouvrir_affectation(utilisateur: Utilisateur, poste: Poste) -> None:
    """
    Date l'occupation du poste — F-04, ADR 015.

    Sans elle, l'histoire des affectations commencerait a la premiere mutation
    saisie. La date de debut est celle d'ouverture du poste, ce que le semis
    connait de plus proche d'une prise de fonction.
    """
    deja = AffectationPoste.objects.filter(utilisateur=utilisateur, fin__isnull=True).exists()
    if not deja:
        AffectationPoste.objects.create(utilisateur=utilisateur, poste=poste, debut=poste.valide_du)


def _rattacher_session(utilisateur: Utilisateur, session: SessionCourrier) -> None:
    """
    Le rattachement est **exclusif** : une contrainte d'exclusion GiST interdit
    deux sessions ouvertes pour un meme agent. `get_or_create` sur le seul
    utilisateur, donc, et non sur le couple.
    """
    UtilisateurSession.objects.get_or_create(
        utilisateur=utilisateur, retire_le__isnull=True, defaults={"session": session}
    )
