# Documentation technique du backend

Elle vit ici parce qu'elle décrit le code d'à côté. Ce qui concerne le projet
entier — accueil, domaine, pièges, questions ouvertes — est dans
[`../../docs/`](../../docs/README.md).

| Dossier | Contenu | Nature |
|---|---|---|
| [architecture/](architecture/README.md) | les décisions, numérotées et datées | **écrite une fois** |
| [modules/](modules/) | un document par pilier métier | maintenue |
| [regles/](regles/) | les règles de gestion et leur statut | maintenue |
| [guides/](guides/) | comment faire les gestes courants | maintenue |
| [exploitation/](exploitation/runbook.md) | déploiement, sauvegarde, incidents | maintenue |
| [exploitation/mise-en-ligne.md](exploitation/mise-en-ligne.md) | la mise en ligne sur le VPS, de bout en bout | maintenue |
| [recette/](recette/) | ce qu'il faut vérifier avant de livrer | maintenue |
| [tracabilite.md](tracabilite.md) | ce qui est tracé, où, et pourquoi | maintenue |

## Ce qui n'est pas ici

**L'API.** Elle est générée depuis les annotations de type et publiée sur
`/api/docs`. On ne la recopie pas : une copie est fausse le lendemain.

**Le dictionnaire de données.** Il est dans la base, en `COMMENT ON`. La
commande qui l'extrait est dans le [runbook](exploitation/runbook.md).

**Le fonctionnement d'un module.** Il est dans les docstrings de module, au plus
près du code, et modifié dans le même diff. Un document qui répéterait
`portee.py` divergerait de `portee.py`.

## La règle

Un changement de comportement se documente **dans le même diff**. Pas après, pas
dans un ticket de suivi.

Et si la question vous a été posée en direct, c'est qu'il manque une page :
écrivez-la avant de passer à autre chose.
