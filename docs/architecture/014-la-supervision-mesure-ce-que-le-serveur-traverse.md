# ADR 014 — La supervision mesure ce que le serveur traverse, et déclare le reste

*14 août 2026 — acceptée*

## Contexte

Le §3.10 confie à l'administrateur technique de « superviser la disponibilité de
la plateforme et la performance des tableaux de bord ». Le BRD chiffre ces deux
missions : 99,5 % de disponibilité en heures ouvrées (RNF-DISP-01), 2 secondes
au 95ᵉ centile pour 95 % des transactions (RNF-PERF-01), reprise en moins de
quatre heures après incident majeur (RNF-DISP-02).

Ce sont des engagements contractuels. L'écran ne peut donc pas se contenter
d'afficher des chiffres : il doit dire **si l'engagement est tenu**. Or au moment
d'écrire ce pilier, la plateforme ne mesurait rien d'elle-même — aucune sonde,
aucun agrégat, aucune trace de durée.

Trois voies se présentaient : inventer des chiffres plausibles, tout rendre à
« non mesuré », ou instrumenter le serveur.

## Décision

**Le serveur se mesure lui-même.** Un middleware
(`supervision/mesure.MesureRequetes`) chronomètre chaque requête de l'API et
range le résultat dans un **agrégat horaire** : une ligne par (méthode, chemin
normalisé, heure), portant le nombre d'appels, le nombre d'erreurs serveur, la
somme et le maximum des durées, et la répartition par **tranches** — moins de
200 ms, 500, 1 000, 2 000, 5 000, au-delà.

**Le p95 est la borne haute de la tranche qui contient le 95ᵉ centile.** Pas une
interpolation, pas une moyenne.

**La disponibilité est le taux de requêtes servies sans erreur serveur.** Les
4xx n'en sont pas.

**Il n'y a pas de table d'incidents.** Un incident est *déduit* des heures dont
le taux d'erreur dépasse le seuil.

**Ce qui n'est pas mesurable est déclaré, et l'écran dit qu'il est déclaré** :
l'état des intégrations tierces (table `integration`), et le plan de reprise, qui
sort à `null` faute d'avoir jamais été testé.

## Pourquoi

### Des tranches plutôt que des durées

Conserver la durée de chaque requête aurait permis un p95 exact, au prix d'une
table qui grossit à la vitesse du trafic — des dizaines de millions de lignes
par an pour répondre à une question binaire : *l'engagement de deux secondes est
tenu, oui ou non ?* Six compteurs par heure et par chemin y répondent, et les
bornes ont été choisies **autour de l'engagement** : 2 000 ms est une borne de
tranche, donc une requête est d'un côté ou de l'autre. Aucune approximation ne
porte sur la seule valeur qui compte.

### Un majorant, jamais une estimation flatteuse

Si 96 % des appels passent sous 500 ms, le p95 rendu est 500 — pas la valeur
exacte, qui serait plus basse. L'arrondi va toujours **contre** l'engagement.
C'est la seule façon honnête d'arrondir un chiffre qui sert à dire si un contrat
est respecté : un p95 sous-estimé transforme une plateforme hors engagement en
plateforme conforme, et personne ne s'en aperçoit avant l'audit.

Corollaire assumé : quand le 95ᵉ centile tombe dans la tranche ouverte
(au-delà de 5 secondes), le p95 sort à `null` et non à 5 000. On ne majore pas
ce qui n'a pas de borne.

### Un 404 n'est pas une panne

Le portail usagers rend 404 chaque fois qu'un usager demande la demande d'un
autre — c'est le système qui fonctionne (ADR 013). Une règle métier qui refuse
une écriture rend 409. Compter ces réponses comme des échecs aurait fait chuter
la disponibilité à chaque refus légitime, et rendu le chiffre inutilisable : plus
le système protège, plus il aurait paru en panne.

### Pas de table d'incidents

Une table d'incidents aurait porté un second récit de la même réalité, alimenté
par personne : le dépôt n'expose aucun écran pour l'écrire, et un écran
d'incidents perpétuellement vide se lit comme une plateforme sans panne. Les
heures dégradées, elles, sont déduites des mêmes mesures que le reste — une
seule source, un seul récit. L'écran dit explicitement que ces incidents n'ont
« été déclarés par personne » : un incident déduit et un incident constaté n'ont
pas la même valeur dans une réunion d'exploitation.

### Le trou qu'il faut nommer

**Une panne totale n'émet aucune requête et ne laisse aucune trace.** La
disponibilité calculée ici est celle du service *rendu*, pas celle du service
*offert* : une plateforme injoignable pendant deux heures ressort à 100 %. C'est
la limite structurelle de toute mesure interne, et la seule réponse est une
sonde extérieure, qui n'est pas de ce dépôt.

Cette limite est écrite **à l'écran**, dans la note du quatrième compteur, et pas
seulement ici. Un chiffre de disponibilité que son lecteur croit exhaustif est
plus dangereux qu'un chiffre absent.

## Conséquences

- **Le middleware est dans la chaîne de chaque requête.** Il est écrit pour ne
  jamais casser ce qu'il mesure : toute erreur d'écriture est avalée en silence.
  Une plateforme qui tombe parce que son thermomètre est cassé est pire qu'une
  plateforme sans thermomètre.
- **Une écriture de plus par requête d'API.** Un `UPDATE … SET appels =
  appels + 1` sur une ligne indexée, puis un `INSERT` seulement à la première
  requête de l'heure. L'ordre compte : l'inverse aurait multiplié les collisions
  d'unicité.
- **Les chemins sont normalisés avant stockage** : `/api/dossiers/412` devient
  `/api/dossiers/{id}`. Les identifiants négatifs et les références métier
  (`DOS-2026-0001`) le sont aussi — sans quoi une ligne par dossier aurait rendu
  la table ingérable.
- **La table `mesure_requete` croît d'environ une ligne par chemin et par
  heure.** Elle n'est purgée par rien pour l'instant : à surveiller, et à traiter
  par une rétention quand le volume le justifiera (A47).
- **Le premier jour, l'écran est presque vide.** C'est la vérité : la plateforme
  vient d'être démarrée. Aucun jeu d'essai ne le remplit.
- **Les connexions sont journalisées avec leur moyen.** Sans cette ligne dans
  `noyau/identite/api.py`, le compte des connexions encore faites par mot de
  passe applicatif — le chiffre qui dit si la bascule vers l'annuaire est
  achevée — serait resté à zéro, et un zéro se lit comme une réussite.

## Ce qui invaliderait cette décision

- **Une supervision d'infrastructure.** Le jour où un Prometheus, un Zabbix ou
  l'hébergeur fournit disponibilité et latence vues de l'extérieur, ces mesures
  deviennent secondaires : elles gardent leur intérêt (elles voient le détail par
  route) mais ne sont plus la source de la disponibilité annoncée.
- **Un volume qui pèse.** Si l'écriture du middleware devient sensible sous
  charge, l'agrégation en mémoire avec vidage périodique est le premier recours —
  au prix de perdre la dernière minute en cas d'arrêt brutal, ce qui est
  acceptable pour un compteur et ne le serait pas pour une écriture métier.
- **Une exigence de p95 exact.** Si un avenant impose de justifier le centile au
  millième de seconde, les tranches ne suffisent plus. Il faudra alors conserver
  les durées, avec une rétention courte.

## Alternatives écartées

**Des chiffres plausibles.** Écartée sans hésiter : une disponibilité inventée
sur un écran d'engagement contractuel est un faux, et elle serait citée en
réunion.

**Tout rendre à « non mesuré ».** Écartée : c'était honnête mais inutile, alors
que la mesure était à portée. L'ADR 011 impose de ne pas inventer, pas de
renoncer à mesurer.

**Une ligne par requête.** Écartée : le volume, pour une précision dont
l'engagement n'a pas besoin.

**Une table d'incidents saisis à la main.** Écartée : deux récits, dont un
alimenté par personne. Voir ci-dessus.

## Voir aussi

- [ADR 010](010-la-matrice-se-recalcule.md) — rien de calculable n'est stocké.
  Ici, seule la matière brute est stockée ; disponibilité, p95 et incidents se
  recalculent à chaque lecture.
- [ADR 011](011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) — la règle mère :
  une mesure absente sort à `null`, avec sa raison. Le plan de reprise en est
  l'application la plus nue.
- [ADR 013](013-le-portail-ne-passe-pas-par-restreindre.md) — livrée le même
  jour ; c'est son 404 par construction qui a imposé d'exclure les 4xx du calcul
  de disponibilité.
