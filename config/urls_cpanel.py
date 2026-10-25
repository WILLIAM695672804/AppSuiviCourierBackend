"""
Racine des URL en hebergement mutualise.

Sur cPanel, l'application Python est montee sur une URI — `/api` — et
Passenger lui transmet le chemin **ampute de ce prefixe** : une requete sur
`https://domaine/api/courriers` arrive avec `SCRIPT_NAME=/api` et
`PATH_INFO=/courriers`.

Avec `config.urls`, qui declare `path("api/", …)`, il faudrait donc appeler
`/api/api/courriers`. Le front, lui, appelle `/api/courriers` et n'a aucune
raison de changer : c'est la meme origine, le meme chemin relatif, quel que
soit l'hebergement.

D'ou ce second fichier, designe par `ROOT_URLCONF` dans
`config/reglages/cpanel.py`. Il monte l'API a la racine de ce que Passenger
transmet. `config/urls.py` reste intact pour tous les autres deploiements.
"""

from django.urls import path

from config.api import api

urlpatterns = [
    path("", api.urls),
]
