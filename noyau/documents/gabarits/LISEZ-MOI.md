# Le gabarit des documents

`pad-officiel.docx` n'est pas écrit à la main. Il est **produit** depuis
`frontend/public/Entête DSR à utiliser.docx` — la pièce remise par la Division
du suivi et de la relance, qui fait foi et qu'on ne modifie pas — par :

    cd backend && ./.venv/bin/python scripts/preparer_gabarit.py

Le script est la documentation de ce que le gabarit contient de plus que le
modèle : l'en-tête déplacé du corps vers `header1.xml` pour qu'il se répète, la
re-liaison des images qui va avec, « Page X sur Y » en pied, et les styles
nommés qu'emploie `noyau/documents/rendu_docx.py`.

**À refaire quand la DSR remet un nouveau modèle**, et à cette occasion
seulement. Le fichier produit est versionné : c'est lui que le serveur ouvre.

Le bilinguisme de l'en-tête n'est pas décoratif — c'est la forme officielle des
actes au Cameroun. La colonne anglaise ne se retire jamais.
