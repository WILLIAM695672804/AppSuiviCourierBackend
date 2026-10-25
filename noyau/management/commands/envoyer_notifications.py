"""
Depile la file des notifications sortantes.

    ./.venv/bin/python manage.py envoyer_notifications

**A appeler par un ordonnanceur** — cron, ou un battement Celery. Pas par la
requete qui a produit la notification : un serveur de messagerie lent rendrait
lente la route qui cote un courrier, et une panne de messagerie ferait echouer
la cotation elle-meme. Une notification qui part une minute plus tard est un
inconvenient ; une cotation qui echoue parce que SMTP ne repond pas est un
incident.

La commande est sans effet tant qu'aucun transport n'est branche : les envois
passent en `sans_transport`, avec la raison, et le compte rendu le dit. C'est
voulu — voir `noyau/notifications/transports.py`.

Elle ne relance pas indefiniment : un envoi echoue est repris tant que ses
tentatives restent sous `notifications.tentatives_max` (hypothese, A51).
"""

from django.core.management.base import BaseCommand

from noyau.notifications import services


class Command(BaseCommand):
    help = "Passe aux transports les notifications en attente de sortie."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--lot",
            type=int,
            default=None,
            help=(
                "Nombre maximal d'envois traites en un passage. "
                "Par defaut, la regle « notifications.lot_depilement »."
            ),
        )

    def handle(self, *args, **options):
        compte = services.depiler(limite=options.get("lot"))

        self.stdout.write(
            f"{compte['traites']} envoi(s) traite(s) : "
            f"{compte['envoyes']} parti(s), "
            f"{compte['echoues']} en echec, "
            f"{compte['sans_transport']} sans transport."
        )

        # Le cas qui compte, et qu'un ordonnanceur silencieux ferait manquer :
        # une file qui « tourne » sans que rien ne sorte.
        if compte["sans_transport"]:
            self.stdout.write(
                self.style.WARNING(
                    "Des notifications n'ont aucun canal de sortie branche. "
                    "Voir A48 (passerelle SMS) et A51 (courriel)."
                )
            )
