# Raccourcis du quotidien. `make` seul affiche la liste.
.DEFAULT_GOAL := aide
PY := ./.venv/bin/python
PIP := ./.venv/bin/pip

.PHONY: aide installer base migrer semer organigramme administrateur dev test lint format verifier types api

aide:  ## Affiche cette aide
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

installer:  ## Cree l'environnement et installe les dependances
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env

base:  ## Demarre PostgreSQL, Redis et MinIO
	docker compose up -d

migrer:  ## Applique les migrations
	$(PY) manage.py migrate

semer:  ## Charge le jeu d'essai : organigramme fictif, comptes, perimetres
	$(PY) manage.py semer

organigramme:  ## Charge l'organigramme REEL du Port (aucun compte cree)
	$(PY) manage.py charger_organigramme --verifier
	@echo "Passage a blanc. Pour ecrire : manage.py charger_organigramme"

administrateur:  ## Rappelle comment ouvrir le premier compte d'administration
	@echo "$(PY) manage.py creer_administrateur --identifiant admin \\"
	@echo "    --prenom PRENOM --nom NOM --structure DSI"

dev:  ## Lance le serveur de developpement
	$(PY) manage.py runserver

test:  ## Lance la suite de tests
	./.venv/bin/pytest

lint:  ## Verifie le style
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .

format:  ## Reformate le code
	./.venv/bin/ruff format .
	./.venv/bin/ruff check --fix .

types:  ## Verifie les annotations
	./.venv/bin/mypy noyau config activite gouvernance courrier performance exploitation pilotage dossier archivage portail supervision

migrations:  ## Refuse une derive entre les modeles et les migrations
	$(PY) manage.py makemigrations --check --dry-run

verifier: lint types migrations test  ## Tout, dans l'ordre ou la chaine d'integration le fait

api:  ## Exporte le contrat OpenAPI dans openapi.json
	$(PY) manage.py export_openapi_schema --api config.api.api --output openapi.json
