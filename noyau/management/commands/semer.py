"""
Jeu d'essai : organigramme, comptes, profils et perimetres.

    ./.venv/bin/python manage.py semer

**Ces donnees sont fictives et ne doivent jamais etre chargees en
production.** L'organigramme reel du Port autonome de Douala n'a pas ete
communique — les decisions de cadrage le classent parmi les trois documents
reellement bloquants : « sans lui, les perimetres restent theoriques ».
L'arbre ci-dessous est donc une approximation de travail, concue pour
exercer les quatre portees de perimetre, et rien d'autre.

Pourquoi une commande plutot qu'une migration de donnees : une migration
s'applique partout, y compris en production, et il faudrait ensuite l'en
empecher. Une commande ne s'execute que si quelqu'un la lance.

La commande est **idempotente** : la relancer ne cree pas de doublons et ne
detruit rien. Les mots de passe, eux, sont reinitialises a chaque passage —
c'est un jeu d'essai, pas un annuaire.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from noyau.habilitation.modeles import Profil, UtilisateurProfil
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.organisation.modeles import (
    AffectationPoste,
    NiveauHierarchique,
    Poste,
    Structure,
)
from noyau.parametrage.modeles import MentionType, Nature, RegleRoutage
from noyau.perimetre.modeles import Perimetre

MOT_DE_PASSE_DEFAUT = "demonstration"

# ---------------------------------------------------------------------
#  L'organigramme d'essai.
#
#  (code, libelle, code du parent, niveau, nature)
#
#  Il est volontairement peu profond mais ramifie : la DSI porte deux
#  services, ce qui est le seul moyen d'eprouver la portee
#  « sous_arbre » — celle qui distingue un directeur d'un chef de
#  service, et celle dont une erreur ne se voit pas.
# ---------------------------------------------------------------------
ORGANIGRAMME = [
    ("DG", "Direction Generale", None, "DG", "Direction"),
    ("DSR", "Division du Suivi et de la Relance", "DG", "DIR", "Direction"),
    ("DCG", "Direction du Controle de Gestion", "DG", "DIR", "Direction"),
    ("DSI", "Direction des Systemes d'Information", "DG", "DIR", "Direction"),
    ("DAF", "Direction des Affaires Financieres", "DG", "DIR", "Direction"),
    ("SCC", "Service du Courrier Central", "DG", "SERV", "Service"),
    ("DSI-ET", "Service des Etudes", "DSI", "SERV", "Service"),
    ("DSI-IN", "Service Infrastructure", "DSI", "SERV", "Service"),
    ("DAF-CP", "Service Comptabilite", "DAF", "SERV", "Service"),
    # Les trois structures qui mesurent le port lui-meme. Elles sont ici pour
    # que l'ecran des relevés d'exploitation soit demontrable : sans structure
    # responsable, aucun point du chenal ne se releve — c'est la regle, et un
    # jeu d'essai qui la montrerait comme une panne n'apprendrait rien.
    ("DDLM", "Direction du Domaine et du Littoral Maritime", "DG", "DIR", "Direction"),
    ("RDR", "Regie du Dragage", "DDLM", "SERV", "Service"),
    ("DE", "Direction de l'Exploitation", "DG", "DIR", "Direction"),
    # Le service qui tient le fonds. Il est distinct du Service du Courrier
    # Central : enregistrer un courrier qui arrive et conserver un dossier
    # clos ne sont pas le meme metier, et le referentiel de conservation
    # releve du second. Sa place reelle dans l'organigramme du PAD reste a
    # confirmer — voir A42.
    ("SAD", "Service des Archives et de la Documentation", "DG", "SERV", "Service"),
]

# ---------------------------------------------------------------------
#  Les comptes.
#
#  (identifiant, prenom, nom, structure, poste, profil, portee, session)
#
#  La liste couvre les cinq roles que le pilier « activites » met en jeu —
#  qui declare, qui arbitre, qui relance, qui valide, qui lit — et les
#  quatre portees. Deux points focaux de structures differentes sont
#  indispensables : c'est la seule facon de verifier qu'un agent ne voit
#  pas le plan du voisin.
# ---------------------------------------------------------------------
COMPTES = [
    ("dg", "Emmanuel", "Kingue", "DG", "Directeur General", "DG", "toutes", None),
    ("admin", "Aline", "Nkodo", "DG", "Administrateur fonctionnel", "ADMIN", "toutes", None),
    ("dsr", "Serge", "Mbarga", "DSR", "Chef de division", "DSR", "toutes", None),
    ("att.dsr", "Nadege", "Etoa", "DSR", "Attachee de suivi", "ATT_DSR", "toutes", None),
    ("dcg", "Paul", "Ndongo", "DCG", "Controleur de gestion", "DCG", "toutes", None),
    ("dir.dsi", "Rita", "Owona", "DSI", "Directrice", "RESP", "sous_arbre", None),
    ("focal.dsi", "Yves", "Manga", "DSI", "Point focal", "POINT_FOCAL", "structure", None),
    ("focal.daf", "Clarisse", "Belinga", "DAF", "Point focal", "POINT_FOCAL", "structure", None),
    ("agent.dsi", "Joseph", "Ateba", "DSI-ET", "Charge d'etudes", "COLLAB", "propre", None),
    # Un membre du Comite de direction. Le profil CODIR porte VUE_CODIR, et
    # aucun compte ne le portait : la vue d'ensemble du Comite n'etait donc
    # ouvrable par personne dans le jeu de demonstration. Le Comite est le
    # conseil des directeurs — un directeur qui y siege sans cesser de repondre
    # de sa branche, d'ou la portee `sous_arbre`.
    (
        "dir.daf",
        "Estelle",
        "Mbida",
        "DAF",
        "Directrice des affaires financieres",
        "CODIR",
        "sous_arbre",
        None,
    ),
    # Les deux structures d'exploitation qui saisissent. Le profil EXPLOITATION
    # porte EXP_SAI et **pas** EXP_LEC : chacune voit ce qu'elle mesure, et rien
    # des chiffres de l'autre. C'est la regle du socle, et ces deux comptes sont
    # ce qui permet de la verifier autrement que par un test.
    (
        "chef.rdr",
        "Blaise",
        "Ngoma",
        "RDR",
        "Chef de la Regie du dragage",
        "EXPLOITATION",
        "structure",
        None,
    ),
    (
        "dir.expl",
        "Solange",
        "Tchouta",
        "DE",
        "Directrice de l'exploitation",
        "EXPLOITATION",
        "structure",
        None,
    ),
    (
        "agent.scc",
        "Marthe",
        "Fouda",
        "SCC",
        "Agent d'enregistrement",
        "AGENT_SESS",
        "structure",
        "arrive",
    ),
    # L'archiviste. Le profil ARCHIVISTE porte `ARCH`, et aucun compte ne le
    # portait : le referentiel de conservation et la file des versements
    # n'etaient ouvrables par personne dans le jeu de demonstration. Portee
    # `toutes` : un fonds d'archives ne se tient pas par branche — c'est la
    # derogation ecrite dans `archivage/api.py`, et le compte doit la rendre
    # verifiable.
    (
        "archiviste",
        "Bertrand",
        "Nnomo",
        "SAD",
        "Chef du service des archives",
        "ARCHIVISTE",
        "toutes",
        None,
    ),
    # L'administrateur technique. Le profil ADMIN_TECH porte `ADM_TEC`, et
    # aucun compte ne le portait : les deux ecrans de supervision — plateforme
    # et integrations — n'etaient ouvrables par personne. Portee `toutes` : la
    # supervision porte sur la plateforme entiere, pas sur une branche.
    (
        "admin.tech",
        "Hervé",
        "Njoya",
        "DSI",
        "Administrateur technique",
        "ADMIN_TECH",
        "toutes",
        None,
    ),
]

# ---------------------------------------------------------------------
#  Les comptes du portail — (identifiant, prenom, nom, courriel)
#
#  Ils sont a part et non dans COMPTES, pour une raison qui est le fond du
#  pilier portail : **un usager n'a ni structure, ni poste, ni perimetre**.
#  Le tableau ci-dessus impose les trois. Les lui donner aurait fait entrer
#  un compte exterieur dans l'organigramme du port, et un perimetre pose sur
#  lui aurait ouvert `restreindre()` a quelqu'un qui ne travaille pas ici.
#
#  Deux comptes et non un seul : c'est la seule facon d'eprouver que l'usager
#  A ne voit pas la demande de l'usager B. Un portail teste avec un seul
#  compte ne prouve rien du cloisonnement.
# ---------------------------------------------------------------------
USAGERS = [
    ("usager.sotrapal", "Aïcha", "Bello", "contact@sotrapal.cm"),
    ("usager.camtrans", "Didier", "Essomba", "direction@camtrans.cm"),
]

# ---------------------------------------------------------------------
#  Le sommet de chaque structure.
#
#  Le semis donne a tous les postes d'une structure le rang de cette
#  structure : rien ne distingue alors le Directeur General de
#  l'administrateur fonctionnel, qui relevent tous deux de la DG. Le sommet
#  est donc **declare**, et non deduit.
#
#  Il sert a chainer `poste_superieur` : dans une structure, tout poste
#  remonte a son sommet ; le sommet, lui, remonte au sommet de la structure
#  parente. C'est le principe 2 de `organisation/modeles.py` — la hierarchie
#  est portee par le poste, jamais par l'agent, et elle reste juste quand
#  l'occupant change.
#
#  Une structure absente de cette table n'a pas de sommet declare : ses
#  postes ne remontent nulle part, ce qui est visible a l'ecran plutot que
#  devine de travers.
#
#  Le sommet declare porte aussi `poste.est_responsable` (migration 0024).
#  Ce drapeau est ce que lit `noyau/organisation/tete.py` pour designer le
#  destinataire d'une relance : sans lui, une structure n'a pas de tete
#  joignable, et la relance ne part vers personne. Il remplace la regle
#  implicite « le poste de tete est celui dont le superieur est hors de sa
#  structure » — vraie du semis, ecrite nulle part, maintenue par rien. Un
#  index unique partiel garantit un seul poste de tete en vigueur par
#  structure.
# ---------------------------------------------------------------------
SOMMETS = {
    "DG": "Directeur General",
    "DSR": "Chef de division",
    "DCG": "Controleur de gestion",
    "DSI": "Directrice",
    # La DAF a desormais sa directrice : le point focal lui est rattache, et
    # non plus directement a la Direction generale.
    "DAF": "Directrice des affaires financieres",
    "SCC": "Agent d'enregistrement",
    "DSI-ET": "Charge d'etudes",
    "RDR": "Chef de la Regie du dragage",
    "DE": "Directrice de l'exploitation",
    "SAD": "Chef du service des archives",
}


class Command(BaseCommand):
    help = "Charge un jeu d'essai : organigramme fictif, comptes, profils et perimetres."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--mot-de-passe",
            default=MOT_DE_PASSE_DEFAUT,
            help=f"Mot de passe commun a tous les comptes (defaut : {MOT_DE_PASSE_DEFAUT}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Passer outre le refus de s'executer hors developpement.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        # Un jeu d'essai charge en production, c'est un compte « dg » avec un
        # mot de passe connu de tous. Le garde-fou est volontairement penible
        # a contourner.
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG est faux : cette base ressemble a une production. "
                "Ces comptes ont un mot de passe commun et public. "
                "Relancez avec --force si vous savez ce que vous faites."
            )

        niveaux = {n.code: n for n in NiveauHierarchique.objects.all()}
        if not niveaux:
            raise CommandError(
                "Aucun niveau hierarchique en base. Appliquez d'abord les migrations."
            )

        structures = self._semer_organigramme(niveaux)
        postes = self._semer_postes(structures, niveaux)
        nombre = self._semer_comptes(structures, postes, options["mot_de_passe"])
        nombre += self._semer_usagers(options["mot_de_passe"])
        self._rattacher_exploitation(structures)
        self._semer_routage(structures)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{len(structures)} structures, {len(postes)} postes, {nombre} comptes."
            )
        )
        self.stdout.write(
            f"Mot de passe commun : {options['mot_de_passe']}  — jeu d'essai, organigramme fictif."
        )

    # -----------------------------------------------------------------
    #  Organigramme
    # -----------------------------------------------------------------
    def _semer_organigramme(self, niveaux: dict) -> dict[str, Structure]:
        structures: dict[str, Structure] = {}

        # L'ordre de la liste garantit qu'un parent est cree avant ses
        # enfants. Il n'est donc pas decoratif : ne le triez pas.
        for code, libelle, parent, niveau, nature in ORGANIGRAMME:
            structure, cree = Structure.objects.get_or_create(
                code=code,
                valide_au__isnull=True,
                defaults={
                    "libelle": libelle,
                    "parent": structures[parent] if parent else None,
                    "niveau_hierarchique": niveaux[niveau],
                    "nature": nature,
                    "valide_du": date.today(),
                },
            )
            structures[code] = structure
            self._dire(cree, f"structure {code}")

        return structures

    def _semer_routage(self, structures: dict) -> None:
        """
        La regle de routage direct, sur l'organigramme fictif.

        La migration `0018` pose la meme regle vers **DFC**, le sigle reel du
        Port. Cet organigramme d'essai n'a pas de DFC : sa direction financiere
        s'appelle DAF, et la regle serait restee sans effet — l'ecran du routage
        direct se serait ouvert sur une table vide, ce qui se lit « la
        fonctionnalite n'est pas livree ».

        Meme statut `hypothese` que la vraie : le principe vient du client, le
        sigle exact et le sort des factures au depart ne sont pas confirmes (A69).
        """
        if "DAF" not in structures:
            return

        nature = Nature.objects.filter(code="FACTURE").first()
        if nature is None:
            return

        _, cree = RegleRoutage.objects.get_or_create(
            code="FACTURE_DAF",
            defaults={
                "libelle": "Facture arrivée — cotation d'office à la DAF",
                "nature": nature,
                "sens": "arrive",
                "structure": structures["DAF"],
                "mention_type": MentionType.objects.filter(code="SUITE").first(),
                "priorite": 10,
                "statut": "hypothese",
                "source": "Entretien client — « les factures vont directement chez le DFC »",
            },
        )
        self._dire(cree, "routage direct FACTURE → DAF")

    def _semer_postes(self, structures: dict, niveaux: dict) -> dict[str, Poste]:
        postes: dict[str, Poste] = {}

        for identifiant, _, _, code_structure, libelle_poste, _, _, _ in COMPTES:
            structure = structures[code_structure]
            poste, cree = Poste.objects.get_or_create(
                structure=structure,
                libelle=libelle_poste,
                valide_au__isnull=True,
                defaults={
                    "niveau_hierarchique": structure.niveau_hierarchique,
                    "valide_du": date.today(),
                },
            )
            postes[identifiant] = poste
            self._dire(cree, f"poste {libelle_poste} ({code_structure})")

        self._chainer_les_postes(structures, postes)
        return postes

    def _chainer_les_postes(self, structures: dict, postes: dict) -> None:
        """
        Pose `poste_superieur` — sans quoi l'organigramme n'a pas d'arbre.

        Deux regles, dans cet ordre : un poste qui n'est pas le sommet de sa
        structure remonte a ce sommet ; le sommet remonte au sommet de la
        structure parente. La seconde est celle qui franchit les structures —
        un directeur ne rend pas compte a un autre directeur, mais au
        Directeur general.

        Le chainage se fait en second temps, apres que tous les postes
        existent : le superieur d'un poste de la DSI est un poste de la DG, qui
        n'est pas forcement cree avant.
        """
        # Le sommet declare de chaque structure, retrouve parmi les postes semes.
        sommets: dict[str, Poste] = {}
        for identifiant, _, _, code_structure, libelle_poste, _, _, _ in COMPTES:
            if SOMMETS.get(code_structure) == libelle_poste:
                sommets[code_structure] = postes[identifiant]

        # Le sommet declare est le poste de tete de sa structure. `SOMMETS` ne
        # le dit qu'ici, dans une commande ; le drapeau le dit en base, et
        # c'est lui que `noyau/organisation/tete.py` interroge pour designer le
        # destinataire d'une relance.
        for sommet in sommets.values():
            if not sommet.est_responsable:
                sommet.est_responsable = True
                sommet.save(update_fields=["est_responsable"])

        for identifiant, _, _, code_structure, _, _, _, _ in COMPTES:
            poste = postes[identifiant]
            sommet_local = sommets.get(code_structure)
            superieur: Poste | None

            if sommet_local is not None and sommet_local.pk != poste.pk:
                superieur = sommet_local
            else:
                parent = structures[code_structure].parent
                superieur = sommets.get(parent.code) if parent else None

            if superieur is not None and poste.poste_superieur_id != superieur.pk:
                poste.poste_superieur = superieur
                poste.save(update_fields=["poste_superieur"])

    # -----------------------------------------------------------------
    #  Comptes, profils, perimetres
    # -----------------------------------------------------------------
    def _semer_comptes(self, structures: dict, postes: dict, mot_de_passe: str) -> int:
        profils = {p.code: p for p in Profil.objects.all()}
        sessions = {s.code: s for s in SessionCourrier.objects.all()}

        for (
            identifiant,
            prenom,
            nom,
            code_structure,
            _,
            code_profil,
            portee,
            code_session,
        ) in COMPTES:
            if code_profil not in profils:
                raise CommandError(
                    f"Profil « {code_profil} » absent. Le referentiel seme par la "
                    "migration a-t-il ete modifie ?"
                )

            utilisateur, cree = Utilisateur.objects.get_or_create(
                identifiant_annuaire=identifiant,
                defaults={
                    "prenom": prenom,
                    "nom": nom,
                    "structure": structures[code_structure],
                    "poste": postes[identifiant],
                    "courriel": f"{identifiant}@pad.cm",
                },
            )
            # Toujours reinitialise : sur un jeu d'essai, un mot de passe
            # qu'on ne connait plus est un compte perdu.
            utilisateur.set_password(mot_de_passe)
            utilisateur.save(update_fields=["mot_de_passe"])
            self._dire(cree, f"compte {identifiant}")

            self._attribuer_profil(utilisateur, profils[code_profil])
            self._poser_perimetre(utilisateur, portee, structures[code_structure])
            self._ouvrir_affectation(utilisateur, postes[identifiant])

            if code_session:
                self._rattacher_session(utilisateur, sessions[code_session])

        return len(COMPTES)

    def _ouvrir_affectation(self, utilisateur: Utilisateur, poste: Poste) -> None:
        """
        Date l'occupation du poste — F-04, ADR 015.

        Sans elle, l'histoire des affectations commencerait a la premiere
        mutation saisie, et ferait croire que personne n'a jamais occupe de
        poste auparavant. Le jeu d'essai doit ressembler a une institution qui
        fonctionne depuis un moment, pas a une base neuve.

        La date de debut est celle d'ouverture du poste (`valide_du`), qui est
        ce que le semis connait de plus proche d'une prise de fonction.
        """
        # Pas de `get_or_create` : la clef d'unicite est « une seule ligne
        # ouverte par agent », qui s'ecrit `fin IS NULL` — un filtre, pas une
        # valeur, et `defaults` ne sait pas le poser a la creation.
        deja = AffectationPoste.objects.filter(utilisateur=utilisateur, fin__isnull=True).exists()
        if not deja:
            AffectationPoste.objects.create(
                utilisateur=utilisateur, poste=poste, debut=poste.valide_du
            )

    def _semer_usagers(self, mot_de_passe: str) -> int:
        """
        Les comptes du portail — **sans structure, sans poste, sans perimetre**.

        L'absence de perimetre n'est pas un oubli : c'est ce qui rend le jeu
        d'essai probant. Un usager qui verrait ses demandes grace a un perimetre
        pose sur lui prouverait le contraire de ce que le portail affirme —
        que sa restriction est `deposant = moi`, ecrite dans `portail/lecture.py`
        et independante du perimetre du socle (ADR 013).

        Le courriel est celui de l'entreprise, pas un `@pad.cm` : un usager
        n'est pas un agent, et le portail lui ecrit chez lui.
        """
        profil = Profil.objects.filter(code="EXTERNE").first()
        if profil is None:
            raise CommandError(
                "Profil « EXTERNE » absent. Le referentiel seme par la migration "
                "a-t-il ete modifie ?"
            )

        for identifiant, prenom, nom, courriel in USAGERS:
            utilisateur, cree = Utilisateur.objects.get_or_create(
                identifiant_annuaire=identifiant,
                defaults={"prenom": prenom, "nom": nom, "courriel": courriel},
            )
            utilisateur.set_password(mot_de_passe)
            utilisateur.save(update_fields=["mot_de_passe"])
            self._dire(cree, f"usager {identifiant}")
            self._attribuer_profil(utilisateur, profil)

        return len(USAGERS)

    def _attribuer_profil(self, utilisateur: Utilisateur, profil: Profil) -> None:
        UtilisateurProfil.objects.get_or_create(
            utilisateur=utilisateur, profil=profil, retire_le__isnull=True
        )

    def _poser_perimetre(self, utilisateur: Utilisateur, portee: str, structure: Structure) -> None:
        """
        Un agent **sans perimetre ne voit rien** — c'est la regle 3 de
        `noyau/perimetre/portee.py`, et c'est voulu. Un jeu d'essai qui
        oublierait cette ligne produirait dix comptes qui se connectent et
        n'affichent aucune donnee, ce qu'on prendrait pour un bug ailleurs.

        La portee `toutes` ne porte pas de structure : elle ne borne rien.
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

    def _rattacher_exploitation(self, structures: dict) -> None:
        """
        Designe qui releve le chenal et qui constate les recettes.

        La migration seme le referentiel **sans rattachement** : la DDLM et la
        Regie du dragage n'existent pas dans un organigramme reel qui n'a pas
        ete communique, et un rattachement invente en migration se serait
        applique partout, production comprise. Le jeu d'essai, lui, ne
        s'execute que si quelqu'un le lance — c'est donc ici que la designation
        a sa place.

        L'import est local : le noyau n'importe aucun pilier, et ce serait le
        seul endroit ou il le ferait a l'ouverture du module.
        """
        from exploitation.modeles import PointChenal, SecteurRecouvrement

        regie = structures.get("RDR")
        exploitation = structures.get("DE")
        finances = structures.get("DAF")

        if regie is not None:
            PointChenal.objects.filter(structure_responsable__isnull=True).update(
                structure_responsable=regie
            )

        # La coupure demandee par le Directeur general le 11 aout 2026 : ce qui
        # vient de l'exploitation d'un cote, les autres recettes de l'autre.
        if exploitation is not None:
            SecteurRecouvrement.objects.filter(
                origine="exploitation", structure_source__isnull=True
            ).update(structure_source=exploitation)

        if finances is not None:
            SecteurRecouvrement.objects.filter(
                origine="autres", structure_source__isnull=True
            ).update(structure_source=finances)

    def _rattacher_session(self, utilisateur: Utilisateur, session: SessionCourrier) -> None:
        """
        Le rattachement est **exclusif** : une contrainte d'exclusion GiST
        interdit deux sessions ouvertes pour un meme agent. `get_or_create`
        sur le seul utilisateur, donc, et non sur le couple.
        """
        UtilisateurSession.objects.get_or_create(
            utilisateur=utilisateur, retire_le__isnull=True, defaults={"session": session}
        )

    def _dire(self, cree: bool, quoi: str) -> None:
        if cree:
            self.stdout.write(f"  cree   {quoi}")
