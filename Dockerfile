# ---------------------------------------------------------------------
#  Image applicative — web, ouvrier et horloge sortent tous d'ici.
#
#  Une seule image pour les trois services : le worker Celery importe les
#  memes modules que l'API, et deux images divergeraient au premier oubli
#  de reconstruction. Ce qui les distingue est la commande, pas le contenu.
#
#  Base Debian et non Alpine : LibreOffice n'existe pas en paquet Alpine
#  utilisable, et `psycopg[binary]` y perdrait ses roues precompilees.
# ---------------------------------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.reglages.preprod

# ---------------------------------------------------------------------
#  LibreOffice sans interface convertit le .docx en PDF (ADR 023). En son
#  absence, la route sert le .docx et refuse le PDF — l'application
#  fonctionne, amputee d'un format. Le paquet `-writer` suffit : ni Calc,
#  ni Impress, ni Java, ce qui epargne environ 400 Mo.
#
#  `fonts-dejavu` n'est pas decoratif : sans police, la conversion rend un
#  PDF aux caracteres manquants, et les accents du francais disparaissent
#  les premiers.
# ---------------------------------------------------------------------
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libreoffice-writer \
        fonts-dejavu \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Les dependances avant le code : une modification de `courrier/api.py` ne
# doit pas relancer l'installation de Django.
COPY pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -m pip install "Django>=5.2,<6.0" "django-ninja>=1.3" "psycopg[binary]>=3.2" \
       "celery>=5.4" "redis>=5.2" "django-environ>=0.11" "structlog>=24.4" \
       "gunicorn>=23.0" "python-docx>=1.1"

COPY . .
RUN python -m pip install --no-deps -e .

# ---------------------------------------------------------------------
#  Compte non privilegie. Le volume des pieces jointes lui appartient :
#  un `chown` au demarrage serait a refaire a chaque montage.
#
#  /etat recoit le fichier de planification de celery beat. Il doit
#  exister ET appartenir a `suivi` AVANT le montage du volume : Docker
#  recopie la propriete du point de montage sur le volume vide qu'il
#  cree. Absent de l'image, le volume naitrait root et beat boucherait
#  sur « Permission denied: celerybeat-schedule ».
# ---------------------------------------------------------------------
RUN useradd --uid 1000 --create-home suivi \
    && mkdir -p /app/media /app/static /etat \
    && chown -R suivi:suivi /app/media /app/static /etat

USER suivi

# `collectstatic` au build et non au demarrage : le resultat ne depend
# d'aucune variable d'environnement, et le refaire a chaque relance
# retarderait le service sans rien changer.
RUN DJANGO_SETTINGS_MODULE=config.reglages.base SECRET_KEY=construction \
    python manage.py collectstatic --noinput

EXPOSE 8000
