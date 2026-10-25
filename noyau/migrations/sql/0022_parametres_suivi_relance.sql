-- Trois reglages du tableau de relance, poses en `hypothese` — A76, A77, A78.
--
-- Le pilier suivi s'ouvre par son tableau de relance (C-02). Trois valeurs y
-- decident de ce que l'ecran montre, et **aucune n'est ecrite nulle part** :
--
-- 1. Le seuil du retard grave.
--
--    L'ecran annonce « dont N au-dela de 5 jours ». Les cinq jours etaient en
--    dur dans le composant React, sans qu'aucun document ne les soutienne. Les
--    deplacer ici ne les rend pas vrais : cela les rend visibles et corrigibles.
--
-- 2. Le nombre de relances qui fait monter d'un niveau d'escalade.
--
--    L'ecran affiche « Niveau 1 », « Niveau 2 », « Niveau 3 » sans que rien ne
--    dise ce qu'est un niveau. Une relance par niveau est le choix le plus
--    simple qui rende la colonne lisible : relance une fois, niveau 1.
--
-- 3. La fenetre du taux de respect des delais.
--
--    Un taux se calcule sur une periode, et personne ne l'a fixee. Douze mois
--    glissants parce que c'est l'horizon d'un rapport annuel, et parce qu'une
--    periode plus courte ferait bondir le taux a chaque semaine creuse.
--
-- Le seuil vise, lui, existe deja : `pilotage.seuil_respect_echeances`, pose en
-- hypothese le 6 (A31). On ne le duplique pas.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('suivi.retard_grave_jours',
   'Depassement, en jours ouvres, au-dela duquel un retard est dit grave',
   '5', 'entier', 'courrier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)'),
  ('suivi.relances_par_niveau_escalade',
   'Nombre de relances emises qui fait monter le dossier d''un niveau d''escalade',
   '1', 'entier', 'courrier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)'),
  ('suivi.fenetre_taux_respect_jours',
   'Profondeur, en jours, sur laquelle se calcule le taux de respect des delais',
   '365', 'entier', 'courrier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)')
ON CONFLICT (cle) DO NOTHING;
