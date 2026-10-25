"""
Charge un jeu de demonstration sur l'organigramme reel.

    ./.venv/bin/python manage.py demonstration

**Ces donnees sont fictives et ne doivent jamais etre chargees en production.**
Les comptes portent un mot de passe commun et public.

A la difference de `semer`, cette commande ne cree **aucune structure** : elle
travaille sur l'organigramme reel charge par `charger_organigramme`, et refuse
de tourner sans lui. Voir `noyau/demonstration/__init__.py` pour le detail.

Elle est idempotente : la relancer ne cree pas de doublons.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from noyau.demonstration import (
    activites,
    archivage,
    comptes,
    correspondants,
    courriers,
    dossiers,
    exploitation,
    gouvernance,
    performance,
    pilotage,
    portail,
    remise_a_zero,
)
from noyau.organisation.modeles import Structure

#: En dessous, l'organigramme reel n'est manifestement pas charge : il compte 77
#: structures. Le seuil est bas exprès — il ne verifie pas une version, il
#: attrape le cas « base neuve ou jeu d'essai fictif ».
STRUCTURES_ATTENDUES = 40


class Command(BaseCommand):
    help = "Charge un jeu de demonstration (comptes et donnees metier) sur l'organigramme reel."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--mot-de-passe",
            default=comptes.MOT_DE_PASSE_DEFAUT,
            help=f"Mot de passe commun (defaut : {comptes.MOT_DE_PASSE_DEFAUT}).",
        )
        parser.add_argument(
            "--courriers",
            type=int,
            default=60,
            help="Nombre de courriers a poser sur les trois derniers mois (defaut : 60).",
        )
        parser.add_argument(
            "--refaire",
            action="store_true",
            help=(
                "Efface les donnees de demonstration avant de les reposer. "
                "L'organigramme, les referentiels et les comptes sont conserves."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Passer outre le refus de s'executer hors developpement.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        # Un jeu de demonstration charge en production, c'est un compte « dg »
        # dont le mot de passe est ecrit dans le depot. Le garde-fou est
        # volontairement penible a contourner.
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG est faux : cette base ressemble a une production. "
                "Ces comptes ont un mot de passe commun et public. "
                "Relancez avec --force si vous savez ce que vous faites."
            )

        nombre_structures = Structure.objects.filter(valide_au__isnull=True).count()
        if nombre_structures < STRUCTURES_ATTENDUES:
            raise CommandError(
                f"Seulement {nombre_structures} structures en base. Cette commande "
                "pose des donnees sur l'organigramme reel du Port ; chargez-le "
                "d'abord :\n    manage.py charger_organigramme"
            )

        if options["refaire"]:
            remise_a_zero.vider(self.stdout.write)

        annuaire = comptes.semer(options["mot_de_passe"], self.stdout.write)
        referentiel = correspondants.semer(self.stdout.write)
        courriers.semer(annuaire, referentiel, options["courriers"], self.stdout.write)
        activites.semer(annuaire, self.stdout.write)
        dossiers.semer(annuaire, self.stdout.write)
        gouvernance.semer(annuaire, self.stdout.write)
        exploitation.semer(annuaire, self.stdout.write)
        portail.semer(annuaire, self.stdout.write)
        performance.semer(annuaire, self.stdout.write)
        archivage.semer(annuaire, self.stdout.write)
        pilotage.semer(annuaire, self.stdout.write)

        self.stdout.write(self.style.SUCCESS(f"\n{len(annuaire)} comptes."))
        self.stdout.write(f"Mot de passe commun : {options['mot_de_passe']}")
