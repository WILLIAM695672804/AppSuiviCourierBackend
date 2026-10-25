"""
Le middleware qui mesure — RNF-PERF-01, RNF-DISP-01.

Il compte, pour chaque requete de l'API : sa duree, son issue, et il range le
tout dans l'agregat horaire de son chemin normalise. C'est la seule source de la
supervision : sans lui, l'ecran « disponibilite et performance » n'aurait que
des chiffres inventes a montrer (ADR 014).

**Trois regles, dans l'ordre de leur importance.**

 1. **La mesure ne casse jamais la requete.** Toute erreur d'ecriture est
    avalee. Une plateforme qui tombe parce que son thermometre est casse est
    pire qu'une plateforme sans thermometre.
 2. **Le chemin est normalise avant d'etre stocke.** `/api/dossiers/412`
    devient `/api/dossiers/{id}`. Une ligne par identifiant aurait rendu la
    table ingerable et la mesure illisible.
 3. **Seule l'API est mesuree.** Les fichiers statiques et l'administration de
    Django ne sont pas ce que le BRD engage.

**Ce qu'il ne mesure pas, et qu'il faut savoir en lisant l'ecran.** Une panne
totale n'emet aucune requete : la disponibilite calculee ici est celle du
service **rendu**, pas celle du service **offert**. Une plateforme injoignable
pendant deux heures ne laisse aucune trace dans cette table. Le dire est le
minimum ; y remedier demande une sonde exterieure, qui n'est pas de ce depot.
"""

import re
import time

from django.db.models import F
from django.utils import timezone

from supervision.modeles import MesureRequete

#: Ce qui n'est pas mesure. L'administration de Django et les fichiers
#: statiques ne portent aucun engagement du BRD.
IGNORES = ("/static/", "/media/", "/admin/")

#: Un segment d'identifiant : nombre, UUID, ou reference du depot
#: (`DOS-2026-0001`, `DEM-2026-0001`). Les trois se remplacent par `{id}`.
SEGMENT_VARIABLE = re.compile(
    r"^(?:-?\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Z]{2,4}-\d{4}-\d+)$"
)


def normaliser(chemin: str) -> str:
    """
    Le chemin, identifiants remplaces par `{id}`.

    « /api/dossiers/412/complements/7/reception » devient
    « /api/dossiers/{id}/complements/{id}/reception ». C'est ce que lit
    l'administrateur technique, et c'est ce qui correspond a une route.
    """
    segments = [
        "{id}" if SEGMENT_VARIABLE.match(segment) else segment for segment in chemin.split("/")
    ]
    return "/".join(segments)


def tranche(duree_ms: int) -> str:
    """La colonne de tranche qui accueille cette duree."""
    if duree_ms < 200:
        return "sous_200"
    if duree_ms < 500:
        return "sous_500"
    if duree_ms < 1000:
        return "sous_1000"
    if duree_ms < 2000:
        return "sous_2000"
    if duree_ms < 5000:
        return "sous_5000"
    return "au_dela"


def enregistrer(methode: str, chemin: str, duree_ms: int, statut: int) -> None:
    """
    Ajoute une requete a l'agregat de son heure.

    `UPDATE ... SET appels = appels + 1` d'abord, `INSERT` ensuite si aucune
    ligne n'existait : c'est l'ordre qui tient sous la concurrence. L'inverse
    aurait multiplie les collisions sur la contrainte d'unicite a chaque
    premiere requete d'une heure.
    """
    heure = timezone.now().replace(minute=0, second=0, microsecond=0)
    colonne = tranche(duree_ms)
    echec = 1 if statut >= 500 else 0

    increments = {
        "appels": F("appels") + 1,
        "echecs": F("echecs") + echec,
        "duree_totale_ms": F("duree_totale_ms") + duree_ms,
        colonne: F(colonne) + 1,
    }

    lignes = MesureRequete.objects.filter(methode=methode, chemin=chemin, heure=heure).update(
        **increments
    )
    if lignes == 0:
        MesureRequete.objects.create(
            methode=methode,
            chemin=chemin,
            heure=heure,
            appels=1,
            echecs=echec,
            duree_totale_ms=duree_ms,
            duree_max_ms=duree_ms,
            **{colonne: 1},
        )
        return

    # La duree maximale ne se met a jour que si elle est depassee. Une requete
    # de plus n'a pas a reecrire la colonne pour rien.
    MesureRequete.objects.filter(
        methode=methode, chemin=chemin, heure=heure, duree_max_ms__lt=duree_ms
    ).update(duree_max_ms=duree_ms)


class MesureRequetes:
    """
    Le middleware. Il n'a besoin de rien d'autre que d'un chronometre.

    `time.monotonic` et non `time.time` : un ajustement d'horloge pendant une
    requete produirait une duree negative, et une duree negative rangee dans une
    tranche fausse le p95 sans qu'on sache pourquoi.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chemin = request.path
        if not chemin.startswith("/api") or chemin.startswith(IGNORES):
            return self.get_response(request)

        debut = time.monotonic()
        reponse = self.get_response(request)
        duree_ms = int((time.monotonic() - debut) * 1000)

        try:
            enregistrer(request.method, normaliser(chemin), duree_ms, reponse.status_code)
        except Exception:
            # Volontairement muet, et volontairement large : voir la regle 1 du
            # module. La mesure ne casse jamais la requete qu'elle mesure.
            pass

        return reponse
