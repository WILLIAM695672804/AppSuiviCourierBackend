"""
Charge l'organigramme reel du Port autonome de Douala.

    ./.venv/bin/python manage.py charger_organigramme --verifier
    ./.venv/bin/python manage.py charger_organigramme

Source des donnees : `noyau/organisation/donnees/organigramme_pad.py`, qui
transcrit la planche « Organigramme du PAD Propose » du 10 novembre 2025.

**Ce n'est pas `semer`.** `semer` charge un jeu d'essai fictif, avec des comptes
dont le mot de passe est public, et refuse de tourner hors developpement. Cette
commande-ci charge un referentiel reel, et elle a vocation a tourner en
production. Les deux ne doivent jamais peupler la meme base : voir
`--cloturer-absentes`.

**Elle ne cree aucun compte et ne nomme personne.** Tous les postes ouverts
sont vacants. Affecter un agent releve de la DRH, par l'ecran d'administration
ou par `services.affecter()` — qui est le seul point du depot autorise a ecrire
`utilisateur.poste`.

------------------------------------------------------------------------
  Ce qu'elle fait, et ce qu'elle refuse de faire
------------------------------------------------------------------------

Elle **cree** ce qui manque : une structure par ligne de la transcription, un
poste de responsable par structure, et les postes lateraux que la planche
dessine a part.

Elle ne **modifie** rien. C'est le principe 1 de `organisation/modeles.py` :
une structure ne se modifie pas, on clot la ligne en vigueur et on en insere
une nouvelle — et cette reprise entraine ses postes, ses affectations et la
relecture des cotations passees. Une commande de chargement qui ferait cela en
silence deplacerait l'histoire sans que personne ne l'ait decide. Quand une
structure en vigueur diverge de la transcription, la commande le **signale** et
laisse la correction a l'ecran d'administration, qui sait clore proprement.

Relancer la commande est donc sans danger : elle est idempotente, et le second
passage ne fait qu'annoncer « rien a faire ».
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from noyau.journal.contexte import traitement_automatique
from noyau.organisation.donnees.organigramme_pad import (
    POSTES,
    SANS_RESPONSABLE,
    STRUCTURES,
    libelle_du_responsable,
)
from noyau.organisation.modeles import (
    AffectationPoste,
    NiveauHierarchique,
    Poste,
    Structure,
)
from noyau.parametrage.modeles import MentionType, Nature, RegleRoutage

#: Inscrit dans `app.contexte` pour le declencheur `historiser_champs()`.
#: Nommer le traitement est le seul moyen de savoir, six mois plus tard,
#: lequel a touche la ligne — ecrire « batch » ne tracerait rien.
CONTEXTE = "chargement_organigramme"


class Command(BaseCommand):
    help = "Charge l'organigramme reel du Port depuis la transcription de la planche officielle."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--verifier",
            action="store_true",
            help="N'ecrit rien. Dit ce qui serait cree, et ce qui diverge.",
        )
        parser.add_argument(
            "--date-effet",
            default=None,
            help="Entree en vigueur des structures creees (AAAA-MM-JJ). Defaut : ce jour.",
        )
        parser.add_argument(
            "--cloturer-absentes",
            action="store_true",
            help=(
                "Clot les structures en vigueur qui ne figurent pas dans la "
                "transcription — typiquement celles du jeu d'essai fictif. "
                "Refuse de clore une structure dont un poste est pourvu."
            ),
        )

    def handle(self, *args, **options) -> None:
        date_effet = self._date_effet(options["date_effet"])
        niveaux = self._niveaux()

        if options["verifier"]:
            # Une transaction quand meme : la verification lit des tables que
            # le chargement modifie, et une lecture eparpillee sur plusieurs
            # transactions pourrait annoncer un etat qui n'a jamais existe.
            with transaction.atomic():
                self._verifier(niveaux, options["cloturer_absentes"])
            return

        # `traitement_automatique` et non `acteur` : aucun agent n'est
        # derriere ce chargement. Le declencheur `historiser_champs()` refuse
        # une modification de `structure` sans l'un ni l'autre, et poser un
        # utilisateur au hasard reviendrait a lui attribuer un geste qu'il n'a
        # pas fait. Voir `docs/pieges.md`.
        with traitement_automatique(CONTEXTE):
            structures = self._charger_structures(niveaux, date_effet)
            responsables = self._ouvrir_les_responsables(structures, niveaux, date_effet)
            self._ouvrir_les_postes_lateraux(structures, responsables, niveaux, date_effet)
            closes = (
                self._cloturer_absentes(structures, date_effet)
                if options["cloturer_absentes"]
                else 0
            )
            self._poser_les_routages(structures)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{len(structures)} structures, {len(responsables)} postes de responsable"
                + (f", {closes} structures closes." if closes else ".")
            )
        )
        self.stdout.write(
            "Tous les postes sont vacants : l'affectation des agents releve de la DRH."
        )

    def _poser_les_routages(self, structures: dict) -> None:
        """
        La regle de routage direct des factures — « directement chez le DFC ».

        **Elle est ici et non dans la migration**, ou plutot : elle est aux deux
        endroits, et il faut les deux. La migration `0018` la pose pour une base
        ou la DFC existe deja ; mais sur une base neuve, les migrations tournent
        **avant** le chargement de l'organigramme (ADR 025 : l'organigramme se
        charge, il ne se migre pas), et son `INSERT … SELECT … WHERE code = 'DFC'`
        n'inserait alors rien. La regle serait restee absente sans qu'aucune
        erreur ne le signale — le pire des cas, puisque le routage direct
        n'aurait simplement jamais eu lieu.

        Idempotente, comme le reste de la commande : le second passage ne fait
        rien.
        """
        cible = structures.get("DFC")
        if cible is None:
            return

        nature = Nature.objects.filter(code="FACTURE").first()
        if nature is None:
            # La migration `0018` la seme. Son absence signale une base dont les
            # migrations ne sont pas appliquees : ce n'est pas a cette commande
            # de la creer, elle n'est pas proprietaire du referentiel.
            self.stdout.write(
                self.style.WARNING("  routage     nature « FACTURE » absente : regle non posee.")
            )
            return

        _, cree = RegleRoutage.objects.get_or_create(
            code="FACTURE_DFC",
            defaults={
                "libelle": "Facture arrivée — cotation d'office à la DFC",
                "nature": nature,
                "sens": "arrive",
                "structure": cible,
                "mention_type": MentionType.objects.filter(code="SUITE").first(),
                "priorite": 10,
                # `hypothese` : le principe vient du client, le sigle exact de la
                # structure d'arrivee et le sort des factures au depart ne sont
                # pas confirmes (A69).
                "statut": "hypothese",
                "source": "Entretien client — « les factures vont directement chez le DFC »",
            },
        )
        if cree:
            self.stdout.write("  routage     FACTURE arrivée → DFC (hypothèse)")

    # -----------------------------------------------------------------
    #  Preliminaires
    # -----------------------------------------------------------------
    def _date_effet(self, brut: str | None) -> date:
        if brut is None:
            return date.today()
        try:
            return date.fromisoformat(brut)
        except ValueError as erreur:
            raise CommandError(f"Date d'effet illisible : {brut} (attendu AAAA-MM-JJ).") from erreur

    def _niveaux(self) -> dict[str, NiveauHierarchique]:
        niveaux = {n.code: n for n in NiveauHierarchique.objects.all()}
        if not niveaux:
            raise CommandError(
                "Aucun niveau hierarchique en base. Appliquez d'abord les migrations."
            )

        attendus = {niveau for _, _, _, niveau, _ in STRUCTURES}
        attendus |= {niveau for _, _, niveau, _ in POSTES}
        manquants = sorted(attendus - set(niveaux))
        if manquants:
            raise CommandError(
                f"Niveaux absents du referentiel : {', '.join(manquants)}. "
                "La migration 0017 les seme — elle n'a pas ete appliquee."
            )
        return niveaux

    # -----------------------------------------------------------------
    #  Verification a blanc
    # -----------------------------------------------------------------
    def _verifier(self, niveaux: dict, dire_les_absentes: bool) -> None:
        existantes = {s.code: s for s in Structure.objects.en_vigueur()}
        a_creer, divergentes = [], []

        for code, libelle, parent, niveau, nature in STRUCTURES:
            existante = existantes.get(code)
            if existante is None:
                a_creer.append(code)
                continue

            ecarts = self._ecarts(existante, libelle, parent, niveau, nature, existantes, niveaux)
            if ecarts:
                divergentes.append((code, ecarts))

        for code in a_creer:
            self.stdout.write(f"  a creer     {code}")
        for code, ecarts in divergentes:
            self.stdout.write(self.style.WARNING(f"  diverge     {code} : {'; '.join(ecarts)}"))

        if dire_les_absentes:
            attendues = {code for code, _, _, _, _ in STRUCTURES}
            for code in sorted(set(existantes) - attendues):
                self.stdout.write(f"  a clore     {code} — absente de la transcription")

        self.stdout.write(
            f"\n{len(a_creer)} structure(s) a creer, {len(divergentes)} divergente(s). "
            "Rien n'a ete ecrit."
        )
        if divergentes:
            self.stdout.write(
                "Une divergence se corrige a l'ecran d'administration : la structure "
                "en vigueur se clot, la nouvelle s'inscrit, et les postes suivent."
            )

    def _ecarts(
        self,
        existante: Structure,
        libelle: str,
        parent: str | None,
        niveau: str,
        nature: str,
        existantes: dict,
        niveaux: dict,
    ) -> list[str]:
        """Ce qui separe une structure en base de sa ligne dans la transcription."""
        ecarts = []
        if existante.libelle != libelle:
            ecarts.append(f"libelle « {existante.libelle} » au lieu de « {libelle} »")
        if existante.nature != nature:
            ecarts.append(f"nature « {existante.nature} » au lieu de « {nature} »")
        if existante.niveau_hierarchique_id != niveaux[niveau].pk:
            ecarts.append(f"niveau autre que {niveau}")

        parent_attendu = existantes[parent].pk if parent and parent in existantes else None
        if parent_attendu is not None and existante.parent_id != parent_attendu:
            ecarts.append(f"rattachement autre que {parent}")
        return ecarts

    # -----------------------------------------------------------------
    #  Structures
    # -----------------------------------------------------------------
    def _charger_structures(self, niveaux: dict, date_effet: date) -> dict[str, Structure]:
        """
        Cree les structures manquantes, dans l'ordre de la transcription.

        L'ordre garantit qu'un parent existe avant ses enfants — il n'est pas
        decoratif, et la transcription le dit aussi.
        """
        structures: dict[str, Structure] = {
            s.code: s for s in Structure.objects.en_vigueur().select_related("parent")
        }
        divergentes = 0

        for code, libelle, parent, niveau, nature in STRUCTURES:
            if code in structures:
                ecarts = self._ecarts(
                    structures[code], libelle, parent, niveau, nature, structures, niveaux
                )
                if ecarts:
                    divergentes += 1
                    self.stdout.write(
                        self.style.WARNING(f"  inchangee   {code} : {'; '.join(ecarts)}")
                    )
                continue

            structures[code] = Structure.objects.create(
                code=code,
                libelle=libelle,
                parent=structures[parent] if parent else None,
                niveau_hierarchique=niveaux[niveau],
                nature=nature,
                valide_du=date_effet,
            )
            self.stdout.write(f"  creee       {code} — {libelle}")

        if divergentes:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{divergentes} structure(s) en vigueur divergent de la transcription "
                    "et n'ont pas ete touchees. Corrigez-les a l'ecran d'administration."
                )
            )
        return {code: structures[code] for code, _, _, _, _ in STRUCTURES}

    # -----------------------------------------------------------------
    #  Postes
    # -----------------------------------------------------------------
    def _ouvrir_les_responsables(
        self, structures: dict, niveaux: dict, date_effet: date
    ) -> dict[str, Poste]:
        """
        Un poste de tete par structure, vacant, chaine sur la structure mere.

        Ce poste porte `est_responsable` : c'est le drapeau que lit
        `noyau/organisation/tete.py` pour designer le destinataire d'une
        relance. Un index unique partiel n'en tolere qu'un seul en vigueur
        par structure.

        Le chainage se fait en second temps, apres que tous les postes
        existent : le superieur du directeur de la DSI est le Directeur
        general, dont le poste n'est pas forcement cree avant.
        """
        responsables: dict[str, Poste] = {}

        for code, libelle, _, niveau, _ in STRUCTURES:
            if code in SANS_RESPONSABLE:
                continue

            structure = structures[code]
            poste, cree = Poste.objects.get_or_create(
                structure=structure,
                libelle=libelle_du_responsable(libelle, niveau),
                valide_au__isnull=True,
                defaults={
                    "niveau_hierarchique": niveaux[niveau],
                    "effectif_prevu": 1,
                    "est_responsable": True,
                    "valide_du": date_effet,
                },
            )
            # La commande est idempotente : un poste ouvert avant la migration
            # 0024 existe sans le drapeau, et doit le recevoir au passage
            # suivant. Sans cette reprise, un organigramme charge hier
            # n'aurait aucun destinataire de relance, et rien ne le dirait.
            if not cree and not poste.est_responsable:
                poste.est_responsable = True
                poste.save(update_fields=["est_responsable"])
            responsables[code] = poste
            if cree:
                self.stdout.write(f"  poste       {poste.libelle}")

        self._chainer(responsables)
        return responsables

    def _chainer(self, responsables: dict[str, Poste]) -> None:
        """
        Le responsable d'une structure rend compte au responsable de sa mere.

        Quand la mere n'en a pas — le Conseil d'administration n'en porte
        pas — on remonte d'un cran de plus. Le Directeur general se retrouve
        ainsi sans superieur, ce qui est exact.
        """
        parents = {code: parent for code, _, parent, _, _ in STRUCTURES}

        for code, poste in responsables.items():
            superieur = None
            remonte = parents.get(code)
            while remonte is not None:
                if remonte in responsables:
                    superieur = responsables[remonte]
                    break
                remonte = parents.get(remonte)

            if poste.poste_superieur_id != (superieur.pk if superieur else None):
                poste.poste_superieur = superieur
                poste.save(update_fields=["poste_superieur"])

    def _ouvrir_les_postes_lateraux(
        self, structures: dict, responsables: dict, niveaux: dict, date_effet: date
    ) -> None:
        """
        Les boites que la planche dessine a cote d'une structure sans en etre une.

        « Attaches (02) », « Auditeurs principaux (03) » : un libelle, un
        effectif, et un rattachement au responsable de la structure.
        """
        for code_structure, libelle, niveau, effectif in POSTES:
            poste, cree = Poste.objects.get_or_create(
                structure=structures[code_structure],
                libelle=libelle,
                valide_au__isnull=True,
                defaults={
                    "niveau_hierarchique": niveaux[niveau],
                    "effectif_prevu": effectif,
                    "poste_superieur": responsables.get(code_structure),
                    "valide_du": date_effet,
                },
            )
            if cree:
                self.stdout.write(f"  poste       {poste.libelle} ({effectif})")

    # -----------------------------------------------------------------
    #  Bascule depuis le jeu d'essai
    # -----------------------------------------------------------------
    def _cloturer_absentes(self, structures: dict, date_effet: date) -> int:
        """
        Clot les structures en vigueur que la transcription ne contient pas.

        Aucun `DELETE` : une cotation de l'an dernier doit rester lisible avec
        la structure de l'an dernier. La ligne est close la veille de la date
        d'effet, pour qu'aucun jour ne se retrouve sans organigramme.

        **Une structure dont un poste est pourvu n'est pas close.** L'agent se
        retrouverait rattache a une structure qui n'existe plus, et son
        perimetre ne rendrait plus rien — une panne silencieuse, celle que le
        socle passe son temps a eviter. La commande le dit et passe son tour.
        """
        attendues = {s.pk for s in structures.values()}
        candidates = Structure.objects.en_vigueur().exclude(pk__in=attendues)
        veille = date_effet - timedelta(days=1)
        closes = 0

        for structure in candidates:
            pourvus = AffectationPoste.objects.filter(
                poste__structure=structure, fin__isnull=True
            ).count()
            if pourvus:
                self.stdout.write(
                    self.style.WARNING(
                        f"  conservee   {structure.code} — {pourvus} agent(s) en poste. "
                        "Mutez-les avant de clore la structure."
                    )
                )
                continue

            Poste.objects.en_vigueur().filter(structure=structure).update(valide_au=veille)
            structure.valide_au = veille
            structure.save(update_fields=["valide_au"])
            closes += 1
            self.stdout.write(f"  close       {structure.code} — {structure.libelle}")

        return closes
