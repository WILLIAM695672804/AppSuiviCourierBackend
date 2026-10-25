# ADR 008 — Le serveur de démonstration est débranché

*Statut : accepté — 13 août 2026*

## Contexte

Le front a été construit avant le backend. Pour que les écrans existent avant
les endpoints, `frontend/src/lib/api.ts` détournait vers un serveur simulé
(`src/lib/demo/serveur.ts`) toute requête dont le chemin n'était pas dans une
liste de domaines réellement servis :

```ts
const DOMAINES_REELS = ["/connexion", "/moi", "/habilitations", "/activites", "/gouvernance"];
const EXCEPTIONS_DEMO = ["/gouvernance/structures"];  // l'écran existait, pas la route
```

Cette bascule a fait son travail : elle a permis de dessiner et de faire
valider trente écrans sans attendre une ligne de Django. Elle a aussi trois
défauts qui, au fil des piliers livrés, sont devenus plus coûteux que le
service rendu.

**Le repli est silencieux.** Une route mal orthographiée, un préfixe oublié au
montage, une erreur 500 côté serveur : dans tous ces cas l'écran affichait des
données. Justes, cohérentes, complètes — et fausses. Le seul symptôme était que
tout marchait un peu trop bien.

**La liste devient une seconde vérité.** `DOMAINES_REELS` et `EXCEPTIONS_DEMO`
décrivaient l'état du backend depuis le front. Chaque endpoint livré supposait
de penser à les modifier ; l'oubli ne cassait rien, il faisait juste continuer
la simulation. `/gouvernance/structures` a vécu deux semaines en exception.

**Les deux mondes divergent.** Les comptes du serveur simulé (`codir`, `resp`,
`focal`, mot de passe « demo ») n'ont jamais existé en base. Les droits
qu'appliquait `serveur.ts` étaient une réécriture approximative de
`restreindre()`. Tester la visibilité sur la démonstration ne prouvait rien sur
l'application.

## Décision

Le détour est retiré. `api.ts` envoie **toute** requête au backend, sans liste
ni exception. Le drapeau `VITE_MODE_DEMO` disparaît des trois fichiers `.env`.

Un domaine non encore livré répond **404**. C'est le comportement recherché :
visible, immédiat, et impossible à confondre avec une donnée réelle.

Trois bornes accompagnent la décision :

1. **Les fichiers de `src/lib/demo/` restent sur le disque.** Plus rien ne les
   importe, ils sont donc élagués du bundle. Ils valent comme spécification des
   piliers qui restent à écrire : les jeux de données y disent la forme
   attendue de chaque réponse, écran par écran. Ils seront supprimés quand le
   dernier pilier les aura rendus faux.
2. **L'écran de connexion ne lit plus `demo/comptes.ts`.** Il liste désormais
   les comptes de `manage.py semer` — `frontend/src/features/authentification/
   comptesJeuEssai.ts`, miroir à tenir à la main. Le panneau ne s'affiche
   qu'en développement (`import.meta.env.DEV`), constante repliée à la
   compilation : le module entier sort du bundle de production.
3. **Aucun repli ne revient par une autre porte.** Ni valeur par défaut sur une
   requête en erreur, ni jeu de données « de secours » dans un composant. Une
   absence de backend se voit à l'écran, ou elle ne se voit nulle part.

## Conséquences

Les domaines sans backend — courrier, performance, dossiers, portail, suivi,
archivage, supervision, pilotage, organisation, comité, direction, départ,
traçabilité, paramétrage, accusés, bordereaux, signalements, compteurs —
affichent désormais une erreur au lieu de données simulées. C'est une
régression visible de la démonstration, et un gain de vérité : l'état réel de
l'application redevient lisible sans ouvrir le code.

`npm run dev` exige maintenant que le backend tourne. `.env.production` porte
l'avertissement correspondant : ne mettre en ligne cette construction qu'avec
un serveur joignable derrière `VITE_API_URL`.

Ce que l'on perd et qu'il faudra retrouver autrement : la capacité de montrer
la plateforme complète à un décideur. Elle reposait sur une fiction ; la
remplacer suppose de livrer les piliers, pas de rebrancher le détour.

## Ce qui invaliderait cette décision

Une échéance de démonstration institutionnelle — comité de direction, bailleur,
recette utilisateur — tombant avant la livraison des piliers restants. Si une
présentation doit montrer des écrans qu'aucun backend ne sert, le repli
redeviendrait défendable. Il devrait alors revenir sous une forme qui ne peut
pas se confondre avec la production : une construction séparée, un bandeau
permanent à l'écran, et jamais un drapeau que l'on oublie de repasser à faux.

## Alternatives écartées

**Garder la bascule et discipliner la liste.** C'est ce qui a été tenté :
`DOMAINES_REELS` tenu à jour endpoint par endpoint. L'exception
`/gouvernance/structures` a survécu deux semaines sans que personne ne
s'en aperçoive, parce que l'oubli n'a aucun symptôme. Une garde qui ne signale
pas ses propres manquements ne se discipline pas.

**Inverser la liste** — simuler seulement ce qui est explicitement nommé.
L'oubli devient bruyant, ce qui est mieux. Mais la seconde vérité subsiste, et
avec elle l'écart entre les droits de `serveur.ts` et ceux de `restreindre()`.
Le coût du repli n'était pas dans le sens de la liste.

**Supprimer `src/lib/demo/` dans le même diff.** Écarté par la borne 1 : les
jeux de données décrivent la forme de réponse attendue par chaque écran non
livré. Les perdre obligerait à relire les composants pour retrouver un contrat
déjà écrit. Le répertoire est versionné, il ne coûte rien tant qu'il n'est
importé nulle part.
