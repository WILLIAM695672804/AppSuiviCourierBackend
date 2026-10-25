"""
Point d'entree de Passenger — hebergement mutualise cPanel uniquement.

cPanel (« Setup Python App ») cherche ce fichier a la racine du repertoire
de l'application et y attend un objet nomme `application`. Aucun autre
deploiement ne le lit : ailleurs, c'est Gunicorn qui charge
`config.wsgi:application` directement.

Deux precautions, chacune payee une fois :

 1. **Le repertoire est ajoute a `sys.path`.** Passenger demarre depuis un
    repertoire de travail qui n'est pas garanti etre celui-ci, et
    l'installation en mode editable n'est pas toujours possible sur un
    mutualise. Sans cette ligne, `import config` echoue — et l'erreur
    s'affiche dans le journal de Passenger, pas dans celui de
    l'application, qui n'a pas encore ete configuree.

 2. **Les reglages sont imposes, pas suggeres.** `setdefault` laisserait
    une variable d'environnement du panneau en decider ; ici, le module de
    reglages fait partie du deploiement.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["DJANGO_SETTINGS_MODULE"] = "config.reglages.cpanel"

from config.wsgi import application

__all__ = ["application"]
