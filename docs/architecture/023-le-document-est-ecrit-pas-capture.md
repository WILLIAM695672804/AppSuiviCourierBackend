# 023 — Le document est écrit, pas capturé

*Statut : acceptée — 18 août 2026*

## Contexte

Tout « Exporter en PDF » de l'application appelait `window.print()` sur l'écran
React. Les règles d'impression de `frontend/src/index.css` masquaient la
navigation et libéraient les zones défilantes, et
`frontend/src/components/EnTeteDocument.tsx` posait l'en-tête institutionnel en
surcouche, invisible à l'écran et présent sur le papier (journal du 17 août).

C'était une capture de l'interface mise au propre, et cela se voyait :

- **la mise en page appartenait au navigateur de chaque agent** — marges, sauts
  de page et échelle changeaient d'un poste à l'autre, pour un document qui
  circule sous la signature du Directeur général ;
- **l'en-tête ne sortait qu'en page 1.** Une note de trois pages partait avec
  deux pages anonymes. Ni pagination, ni référence de document — donc rien à
  citer en séance, rien à classer ;
- **aucune trace de l'édition.** Une donnée qui sort du système se signale quel
  que soit son volume (§3.12) ; `window.print()` ne passe par aucun serveur et
  n'inscrit rien ;
- **aucun format éditable**, alors que le secrétariat retouche la note de
  synthèse avant la séance. Il la reprenait à la main dans un Word vierge ;
- **le contenu ne variait pas avec les données.** Un tableau à zéro ligne
  s'imprimait vide au lieu de dire qu'il n'y avait rien à montrer, et un
  classement de vingt-quatre structures repoussait les points d'arbitrage en
  page trois.

La note de synthèse du CODIR (§3.1, §3.2) est le premier document dont ces cinq
défauts se paient en séance. Le bordereau de transmission, la fiche de cotation
et le registre imprimable viendront ensuite, avec les mêmes exigences.

## Décision

**L'application cesse d'imprimer un écran ; elle écrit un document.**

1. **Le serveur produit le fichier.** `backend/noyau/documents/` ouvre le
   gabarit Word officiel de la DSR (`gabarits/pad-officiel.docx`), y verse le
   contenu, et rend le `.docx`.
2. **Le PDF est ce même `.docx`, converti** par LibreOffice sans interface.
   **Une source, deux formats** : il n'existe qu'un gabarit, il ne peut donc pas
   diverger entre le Word et le PDF.
3. **Trois couches étanches**, parce que le document survivra à ses outils :
   `structure.py` tient le document en objets neutres et ne connaît ni Word ni
   le pilier qui l'a composé ; `rendu_docx.py` est le seul module du dépôt à
   importer python-docx ; `conversion.py` est le seul à connaître `soffice`. Un
   pilier métier compose une `structure.Document` et se teste sans écrire un
   seul fichier.
4. **Le gabarit est fabriqué, pas édité à la main.**
   `backend/scripts/preparer_gabarit.py` le reconstruit depuis
   `frontend/public/Entête DSR à utiliser.docx`, qui n'est jamais modifié : le
   modèle remis par la DSR reste la pièce qui fait foi, et l'on peut rejouer la
   fabrication quand elle en remet une nouvelle version.
5. **Le rendu n'écrit aucune mise en forme directe.** Chaque paragraphe reçoit
   un style nommé du gabarit — y compris le style de tableau, créé par le
   script. Le trait vit dans le gabarit, le rendu s'y réfère par son nom : c'est
   ce qui permet à la DSR de changer une police sans livraison.
6. **La sortie de fichier se trace.** `GET /pilotage/synthese/export` inscrit un
   accès de type `export` par `noyau.journal.service.tracer_acces`, comme
   `GET /pilotage/rapports/export` — et non un événement métier : le pilotage
   n'écrit rien (§3.12, `RNF-TRACE-01`). La trace est posée **après**
   la production : un document qui échoue n'a rien exporté.
7. **La route ne passe pas par `restreindre()`**, et c'est la dérogation
   institutionnelle déjà écrite en tête de `pilotage/api.py` pour
   `/pilotage/analyses` et `/comite/vue-ensemble` : une note d'instance amputée
   des directions hors périmètre du lecteur ne serait pas la note de l'instance.
   Elle n'expose que des agrégats de structure, et la garde `COCKPIT` la borne
   (D5 reste appliquée au niveau des données ailleurs).

## Conséquences

- **LibreOffice devient une dépendance du serveur applicatif.** C'est le seul
  point de ce chantier qui dépend de l'exploitation, et il est nommé dans
  `.env.example` (`LIBREOFFICE_BINAIRE`, `LIBREOFFICE_DELAI`). En son absence, la
  route sert le `.docx` et refuse le PDF en **503** — un serveur incomplet, pas
  un bogue de la note — avec un message qui dit de télécharger le Word.
- **La conversion est synchrone**, dans la requête. Un travail d'une à deux
  secondes ne justifiait pas une route de scrutation et un stockage
  intermédiaire. Deux risques en découlent, et `conversion.py` les porte tous
  les deux : un **délai de garde** au-delà duquel le processus est tué, pour
  qu'un `soffice` bloqué n'immobilise pas un ouvrier gunicorn ; et un **profil
  LibreOffice isolé par appel** (`-env:UserInstallation` dans le répertoire
  temporaire), parce que deux processus qui partagent un profil se bloquent
  mutuellement. Si la latence devenait un sujet, le passage en tâche différée ne
  toucherait ni le rendu ni les piliers : `conversion` est le seul module
  concerné.
- **Les règles `@media print` de `index.css` restent en place**, et l'en-tête en
  surcouche avec elles. Elles ne servent plus les documents officiels, mais un
  agent imprimera toujours son écran — un tableau de bord consulté, une liste
  filtrée — et une page imprimée sans elles part avec sa navigation et ses
  boutons.
- **Le contenu devient une décision métier.** `pilotage/synthese.py` compose la
  note en fonction des données : un classement long bascule en annexe au-delà
  d'un seuil paramétré (`pilotage.lignes_avant_annexe`, hypothèse — A58), et le
  renvoi à l'annexe est écrit dans le corps. `synthese()` reste inchangée pour
  l'écran : l'export ne l'a pas remplacée, il s'ajoute à côté.
- **Le front ne rend plus le document.** Les deux boutons d'export de
  `SyntheseInstance.tsx` sont des liens de téléchargement, et `Bouton` accepte
  désormais `href` pour rendre un `<a download>` aux mêmes styles.

## Ce qui invaliderait cette décision

**Un refus d'installer LibreOffice en production.** L'alternative écartée
ci-dessous — deux rendus depuis le modèle commun — redevient alors le repli, et
`structure.py` a précisément été isolé pour que ce repli ne coûte qu'un module :
un `rendu_pdf.py` en face de `rendu_docx.py`, sans toucher aux piliers.

**Une latence qui se voit.** Si la conversion dépassait régulièrement quelques
secondes — documents plus longs, serveur chargé —, la production dans la requête
ne tiendrait plus, et il faudrait produire le fichier en différé plutôt
qu'allonger le délai de garde.

**Un modèle Word remis autrement par la DSR** — avec un vrai en-tête de page,
ou sans le tableau bilingue. `preparer_gabarit.py` échoue franchement dans ce
cas plutôt que de produire un gabarit muet, et c'est voulu.

## Alternatives écartées

**Deux rendus depuis un modèle commun : HTML → PDF par WeasyPrint, et DOCX par
python-docx.** Meilleure maîtrise typographique du PDF, et aucune dépendance
système à installer. Écartée pour une raison unique et suffisante : **deux
gabarits à tenir alignés**. L'en-tête institutionnel aurait été redessiné en
HTML au lieu d'être celui du modèle officiel, et la divergence entre le PDF et
le Word n'aurait été qu'une question de temps — le premier changement de police
de la DSR l'aurait ouverte. C'est le repli si LibreOffice est refusé en
production ; ce n'est pas le premier choix.

**Une page « document » React, imprimée par le navigateur.** Elle aurait corrigé
la mise en page à l'écran et rien d'autre : ni pagination fiable, ni en-têtes
répétés sur toutes les pages, ni format éditable pour le secrétariat, ni trace
d'export côté serveur. Elle déplaçait le problème sans en régler un seul.

**Rendre le `.docx` seul, et laisser chacun l'imprimer en PDF.** Le plus simple,
et il aurait supprimé la dépendance système. Mais le PDF est le format qui
circule — pièce jointe d'un courrier, dépôt dans un dossier de séance — et le
laisser produire par le poste de chaque agent aurait ramené exactement la
variabilité que ce chantier corrige.
