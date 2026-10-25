"""
Les traitements de nuit, sans Celery.

Sur un hebergement mutualise, aucun processus ne survit a la requete qui
l'a lance : ni ouvrier Celery, ni horloge. Les sept taches du calendrier
(`CELERY_BEAT_SCHEDULE`) doivent alors etre appelees par un ordonnanceur
externe — le « cron job » du panneau (ADR 046).

    python manage.py traitements                    # les sept, dans l'ordre
    python manage.py traitements --seulement agregats-des-activites

**L'ordre n'est pas decoratif.** Il reprend celui des heures du calendrier :
les obligations sont engendrees avant que les relances ne cherchent des
retards, et les agregats sont calcules en dernier pour refleter ce que les
deux precedents ont ecrit. Un agregat calcule avant sa relance la manquerait
de vingt-quatre heures.

Les taches restent des fonctions Python ordinaires : `@shared_task` ne les
transforme pas, il leur ajoute un moyen d'etre appelees a distance. Les
invoquer directement est donc exact, et non un contournement.

Chaque tache est independante : l'echec de l'une n'annule pas les
precedentes et n'empeche pas les suivantes. Le compte rendu dit laquelle a
echoue, et la commande sort en erreur pour que le cron du panneau le
signale.
"""

import traceback

from django.core.management.base import BaseCommand
from django.utils import timezone

#: Les sept taches, dans l'ordre des heures de `CELERY_BEAT_SCHEDULE`.
#: Le nom court est celui qu'attend `--seulement` ; il reprend la clef du
#: calendrier, pour qu'un seul vocabulaire serve aux deux modes de
#: deploiement.
CALENDRIER: list[tuple[str, str, str]] = [
    ("obligations-du-jour", "activite.taches", "engendrer_obligations"),
    ("relances-des-retards", "activite.taches", "relancer_les_retards"),
    ("relances-des-engagements", "gouvernance.taches", "relancer_les_engagements"),
    ("depots-en-souffrance", "gouvernance.taches", "signaler_les_depots"),
    ("agregats-des-activites", "activite.taches", "recalculer_agregats"),
    ("agregats-de-gouvernance", "gouvernance.taches", "recalculer_agregats"),
    # Idempotente : elle se retire elle-meme hors decembre. L'appeler tous
    # les jours est donc sans effet onze mois sur douze — et c'est ce qui
    # la rend sure a poser dans un cron quotidien, la ou une planification
    # annuelle unique n'aurait aucun rattrapage.
    ("ouverture-de-l-exercice", "activite.taches", "ouvrir_exercice_suivant"),
]


class Command(BaseCommand):
    help = "Execute les traitements de nuit sans Celery (hebergement mutualise)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seulement",
            choices=[nom for nom, _, _ in CALENDRIER],
            help="N'execute qu'un seul traitement, au lieu des sept.",
        )

    def handle(self, *args, **options):
        from importlib import import_module

        demandee = options.get("seulement")
        a_faire = [t for t in CALENDRIER if demandee is None or t[0] == demandee]

        debut = timezone.now()
        self.stdout.write(f"{debut:%Y-%m-%d %H:%M:%S} — {len(a_faire)} traitement(s)")

        echecs = 0
        for nom, module, fonction in a_faire:
            try:
                resultat = getattr(import_module(module), fonction)()
                self.stdout.write(self.style.SUCCESS(f"  {nom} : {resultat}"))
            except Exception as erreur:
                echecs += 1
                self.stderr.write(self.style.ERROR(f"  {nom} : ECHEC — {erreur}"))
                self.stderr.write(traceback.format_exc())

        duree = (timezone.now() - debut).total_seconds()
        self.stdout.write(f"Termine en {duree:.1f} s, {echecs} echec(s)")

        if echecs:
            # Sortie non nulle : le cron du panneau envoie alors un courriel
            # d'alerte. Sans cela, une nuit qui echoue passerait inapercue.
            raise SystemExit(1)
