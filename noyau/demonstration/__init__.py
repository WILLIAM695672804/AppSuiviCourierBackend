"""
Le jeu de demonstration — des donnees metier sur l'organigramme reel.

**A ne jamais charger en production.** Les comptes ont un mot de passe commun,
les correspondants sont inventes, et les courriers racontent une histoire qui
n'a pas eu lieu.

Ce paquet est distinct de `noyau/management/commands/semer.py`, et la
distinction est le fond du sujet :

 * `semer` pose un organigramme **fictif** — quinze structures inventees, du
   temps ou celui du Port n'avait pas ete communique. Il ne sert plus qu'aux
   bases neuves.
 * `demonstration` ne cree **aucune structure** : il travaille sur les 77
   structures reelles chargees par `charger_organigramme`, et refuse de tourner
   si elles ne sont pas la. Semer un second organigramme a cote du vrai aurait
   produit deux arbres concurrents, dont les tableaux de bord auraient additionne
   les chiffres.

Chaque module sait remplir un pilier et **rien d'autre** ; l'ordre de leur appel
est celui des dependances, pose une fois dans la commande. Deux regles tenues
partout :

 1. **Passer par les services metier quand ils existent.** `courrier.services`
    inscrit les evenements, pose les declencheurs, applique les regles. Des
    `INSERT` directs auraient rempli les tables sans remplir le journal — et la
    fiche de vie, la tracabilite et les indicateurs se lisent dans le journal.
    La demonstration doit etre une **repetition du parcours reel**, pas une
    imitation de son resultat.
 2. **Idempotence.** Relancer ne duplique pas. Chaque module reconnait ce qu'il
    a deja pose, a une marque stable — la reference d'un courrier, le code d'un
    correspondant — et passe son tour.

Ce que la demonstration **ne peut pas** montrer, et pourquoi : tout ce qui
s'ancre sur `circuit_etape`, qui est vide (A24). Ni transmission, ni validation
hierarchique, ni relance automatique : les etapes `TRANSMIS`, `SIGNE` et `PARTI`
ne seront donc jamais atteintes, quel que soit le volume seme. Un jeu qui les
simulerait par des ecritures directes ferait croire le circuit livre.
"""
