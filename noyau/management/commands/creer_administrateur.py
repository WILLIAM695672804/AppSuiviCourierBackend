"""
Ouvre le premier compte d'administrateur fonctionnel d'une base.

    ./.venv/bin/python manage.py creer_administrateur \
        --identifiant admin --prenom Aline --nom Nkodo --structure DSI

**Le probleme qu'elle resout.** Une base fraichement migree, chargee de
l'organigramme reel, ne contient **aucun compte**. Les ecrans qui creent des
comptes exigent `ADM_HAB` ; personne ne la porte ; personne ne peut donc en
donner. La commande casse cet oeuf et la poule, et rien d'autre.

**Elle ne sert qu'une fois.** Les comptes suivants se creent a l'ecran
d'administration, sous le nom de quelqu'un, avec un evenement au journal. La
commande refuse d'ailleurs de tourner si un compte porte deja `ADM_HAB` —
ouvrir un second administrateur en ligne de commande, c'est contourner la trace
que le premier a justement pour role de garantir.

**Ce qu'elle pose, et pourquoi chacun est indispensable.** Un compte sans l'un
des quatre ne fonctionne pas, et le defaut est silencieux :

  1. un **poste** dans une structure — sans lui, le compte apparait au tableau
     d'administration comme « sans structure de rattachement », et la hierarchie
     du circuit ne sait pas ou le placer ;
  2. une **affectation datee** a ce poste — `utilisateur.poste` dit le present,
     `affectation_poste` dit l'histoire, et les deux s'ecrivent ensemble
     (ADR 015) ;
  3. le **profil** `ADMIN`, qui porte `ADM_ORG`, `ADM_HAB` et `ADM_PAR` ;
  4. un **perimetre** — un agent sans perimetre ne voit rien, regle 3 de
     `noyau/perimetre/portee.py`, et le referentiel le signale comme anomalie.

Le mot de passe est un ecart assume a `RF-ADM-02`, qui veut l'authentification
deleguee a l'annuaire. Tant que la bascule n'a pas eu lieu, il faut bien ouvrir
une session. Voir ADR 004.
"""

from __future__ import annotations

import secrets
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from noyau.habilitation.modeles import Profil, UtilisateurProfil
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import AffectationPoste, NiveauHierarchique, Poste, Structure
from noyau.perimetre.modeles import PORTEE_TOUTES, Perimetre

#: Le profil de l'administrateur fonctionnel, seme par le socle.
PROFIL = "ADMIN"

#: La permission qui fait de ce compte le premier : tant que personne ne la
#: porte, aucun compte ne peut en creer un autre.
PERMISSION_FONDATRICE = "ADM_HAB"

#: L'etage du poste. Le plus bas de l'organigramme : administrer l'application
#: n'est pas diriger une structure, et poser l'administrateur au rang de
#: directeur lui donnerait dans les circuits une place qu'il n'a pas.
NIVEAU = "SERV"


class Command(BaseCommand):
    help = "Ouvre le premier compte d'administrateur fonctionnel. Ne sert qu'une fois."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--identifiant", required=True, help="Identifiant d'annuaire.")
        parser.add_argument("--prenom", required=True)
        parser.add_argument("--nom", required=True)
        parser.add_argument(
            "--structure",
            required=True,
            help="Sigle de la structure de rattachement, tel qu'il est en base (ex. DSI).",
        )
        parser.add_argument(
            "--poste",
            default="Administrateur fonctionnel",
            help="Libelle du poste ouvert pour ce compte.",
        )
        parser.add_argument(
            "--courriel",
            default=None,
            help="Adresse professionnelle. Deduite de l'identifiant si absente.",
        )
        parser.add_argument(
            "--mot-de-passe",
            default=None,
            help="Mot de passe initial. Engendre au hasard et affiche si absent.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Passe outre le refus d'ouvrir un second administrateur.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        self._refuser_un_second(options["force"])

        structure = self._structure(options["structure"])
        profil = self._profil()
        niveau = self._niveau()

        if Utilisateur.objects.filter(identifiant_annuaire=options["identifiant"]).exists():
            raise CommandError(f"L'identifiant « {options['identifiant']} » est deja pris.")

        poste = self._ouvrir_le_poste(structure, options["poste"], niveau)
        mot_de_passe = options["mot_de_passe"] or secrets.token_urlsafe(12)

        agent = Utilisateur.objects.create(
            identifiant_annuaire=options["identifiant"],
            prenom=options["prenom"],
            nom=options["nom"],
            structure=structure,
            poste=poste,
            courriel=options["courriel"] or f"{options['identifiant']}@pad.cm",
        )
        agent.set_password(mot_de_passe)
        agent.save(update_fields=["mot_de_passe"])

        AffectationPoste.objects.create(utilisateur=agent, poste=poste, debut=date.today())
        UtilisateurProfil.objects.create(utilisateur=agent, profil=profil)
        # Portee `toutes`, et sans structure : elle ne borne rien. Ce n'est pas
        # un blanc-seing sur le courrier — le perimetre ne s'applique qu'apres
        # la garde de permission, et le profil ADMIN n'en porte aucune de
        # lecture metier. Il administre le referentiel, il ne lit pas les
        # dossiers.
        Perimetre.objects.create(
            utilisateur=agent, portee=PORTEE_TOUTES, structure=None, valide_du=date.today()
        )

        self.stdout.write(self.style.SUCCESS(f"\nCompte « {options['identifiant']} » ouvert."))
        self.stdout.write(f"  structure   {structure.code} — {structure.libelle}")
        self.stdout.write(f"  poste       {poste.libelle}")
        self.stdout.write(f"  profil      {profil.code} — {profil.libelle}")
        self.stdout.write(f"  perimetre   {PORTEE_TOUTES}")
        if not options["mot_de_passe"]:
            self.stdout.write(self.style.WARNING(f"\n  mot de passe  {mot_de_passe}"))
            self.stdout.write("  Il n'est affiche qu'ici. Changez-le a la premiere connexion.")

    # -----------------------------------------------------------------
    def _refuser_un_second(self, force: bool) -> None:
        deja = UtilisateurProfil.objects.filter(
            retire_le__isnull=True,
            utilisateur__actif=True,
            profil__permissions__code=PERMISSION_FONDATRICE,
        ).exists()
        if deja and not force:
            raise CommandError(
                f"Un compte porte deja « {PERMISSION_FONDATRICE} » : les suivants "
                "se creent a l'ecran d'administration, sous le nom de quelqu'un. "
                "Relancez avec --force si le premier compte est perdu."
            )

    def _structure(self, sigle: str) -> Structure:
        structure = Structure.objects.en_vigueur().filter(code=sigle).first()
        if structure is None:
            raise CommandError(
                f"Aucune structure en vigueur au sigle « {sigle} ». "
                "L'organigramme a-t-il ete charge ?"
            )
        return structure

    def _profil(self) -> Profil:
        profil = Profil.objects.filter(code=PROFIL).first()
        if profil is None:
            raise CommandError(
                f"Profil « {PROFIL} » absent. Le referentiel seme par les migrations "
                "a-t-il ete modifie ?"
            )
        return profil

    def _niveau(self) -> NiveauHierarchique:
        niveau = NiveauHierarchique.objects.filter(code=NIVEAU).first()
        if niveau is None:
            raise CommandError(f"Niveau « {NIVEAU} » absent du referentiel.")
        return niveau

    def _ouvrir_le_poste(
        self, structure: Structure, libelle: str, niveau: NiveauHierarchique
    ) -> Poste:
        """
        Le poste de l'administrateur, sous le responsable de sa structure.

        Il ne remonte pas au Directeur general : l'administrateur travaille dans
        une structure et en releve, meme si ce qu'il administre depasse la
        sienne. La hierarchie se lit par le poste, jamais par les droits.
        """
        # Le poste de tete d'une structure est celui qui porte le rang de la
        # structure elle-meme — c'est ainsi que `charger_organigramme` les
        # ouvre. Absent, on laisse le poste sans superieur plutot que d'en
        # inventer un : un chainage faux se lit comme un chainage vrai.
        superieur = (
            Poste.objects.en_vigueur()
            .filter(structure=structure, niveau_hierarchique=structure.niveau_hierarchique)
            .first()
        )

        return Poste.objects.create(
            structure=structure,
            libelle=libelle,
            niveau_hierarchique=niveau,
            poste_superieur=superieur,
            effectif_prevu=1,
            valide_du=date.today(),
        )
