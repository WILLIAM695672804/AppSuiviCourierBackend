"""
Racine des URL.

Tout passe par `/api`, sans prefixe de version : `frontend/src/lib/api.ts`
fixe `BASE_URL = "/api"` et appelle `/activites`. Une route en `/api/v1/...`
casserait chaque appel du front.
"""

from django.urls import path

from config.api import api

urlpatterns = [
    path("api/", api.urls),
]
