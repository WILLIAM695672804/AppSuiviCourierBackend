"""
Routes de tracabilite — `/api/tracabilite/*`.

**Ces routes lisent, et rien d'autre.** Aucune n'ecrit, aucune ne supprime, et
il ne faut jamais en ajouter : le journal tire toute sa valeur du fait qu'on ne
peut pas le nettoyer. C'est ce que dit l'ecran, et ce doit rester vrai du code.

`AUDIT` et non `ADM_TEC` : le §3.12 confie ces journaux a un poste d'audit, qui
n'administre pas la plateforme. Les deux permissions sont distinctes exprès —
qui tient les journaux ne doit pas etre qui peut les faire disparaitre.

`restreindre()` n'est pas appele, et c'est le seul cas du depot avec l'ADR 007 :
un journal reduit au perimetre de son lecteur ne prouve rien. La garde est donc
entierement portee par la permission — un compte sans `AUDIT` ne voit rien du
tout, un compte avec `AUDIT` voit l'institution entiere.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige
from noyau.tracabilite import lecture
from noyau.tracabilite.schemas import HistoriqueChamps, JournalAcces, JournalEvenements

routeur = Router()

# `/archivage/conformite` a vecu ici tant que le pilier archivage n'existait
# pas : la route rendait des compteurs vides en le disant. Elle est desormais
# servie par `archivage/api.py`, sur des dossiers et un referentiel reels. Le
# socle n'importe aucun pilier — c'est ce qui interdisait de la completer sur
# place, et ce qui a decide du deplacement plutot que d'un import.


#: Ce qu'un ecran peut demander d'un coup. Au-dela, ce n'est plus de la
#: consultation mais de l'extraction, et l'extraction se fait autrement — la
#: table est partitionnee et compte des millions de lignes en regime etabli.
PLAFOND = 1000


@routeur.get("/evenements", response=JournalEvenements, auth=exige(PERM.AUDIT))
def evenements(request, type: str = "Tous", limite: int = 200):
    """
    Ce que l'application a fait, du plus recent au plus ancien.

    Le parametre s'appelle `type` parce que c'est ce que le front envoie, et
    qu'il porte le **libelle affiche** (« Habilitation ») et non le code de
    l'evenement (`profil_attribue`). La correspondance est tenue dans
    `lecture.FAMILLES` : la deporter au front l'aurait rendu dependant du
    nommage interne des evenements.

    `limite` est **bornee au serveur** : un front qui demanderait tout ne
    s'afficherait jamais, et rien n'empeche d'appeler la route a la main.
    """
    return lecture.journal_evenements(type, min(max(limite, 1), PLAFOND))


@routeur.get("/acces", response=JournalAcces, auth=exige(PERM.AUDIT))
def acces(request, filtre: str = "Tous", limite: int = 200):
    """
    Qui a seulement regarde.

    **Peut rendre une liste vide sans que rien ne soit casse.**
    `tracer_acces` n'est appelee que sur la lecture d'un objet sensible ;
    tracer chaque liste ferait grossir la table de millions de lignes par mois
    sans rien apprendre a personne.
    """
    return lecture.journal_acces(filtre, min(max(limite, 1), PLAFOND))


@routeur.get("/historique", response=HistoriqueChamps, auth=exige(PERM.AUDIT))
def historique(
    request,
    tableCible: str | None = None,
    ligneId: int | None = None,
    horsApplication: bool = False,
    limite: int = 200,
):
    """
    Ce qui a change, colonne par colonne — I-03.

    **La route qui montre ce que le journal des evenements ne peut pas voir.**
    `champ_historique` est alimentee par declencheur PostgreSQL ; une
    modification faite en SQL direct y figure et n'a **aucun** evenement
    correspondant. `horsApplication=true` ne rend que celles-la.

    `tableCible` n'est pas valide contre une liste blanche, et n'a pas a
    l'etre : c'est un parametre de filtre passe en requete parametree, et une
    valeur inconnue rend simplement zero ligne. Le selecteur de l'ecran est
    peuple par le champ `tables` de la reponse.

    `limite` est bornee au serveur, comme les deux autres routes : la table
    compte des millions de lignes par an en regime etabli.
    """
    return lecture.historique_champs(
        table_cible=tableCible,
        ligne_id=ligneId,
        hors_application=horsApplication,
        limite=min(max(limite, 1), PLAFOND),
    )
