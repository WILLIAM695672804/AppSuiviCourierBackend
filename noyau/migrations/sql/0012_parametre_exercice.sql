-- Le premier mois de l'exercice — A52, hypothese.
--
-- Les rapports periodiques decoupent le temps en mois, trimestres, semestres
-- et exercices. Ce decoupage part d'un mois d'ouverture, que personne n'a
-- fourni : le cahier des charges parle d'« exercice » sans jamais le borner.
--
-- Pose a 1, l'annee civile. C'est l'usage le plus courant et c'est ce que le
-- reste du depot suppose deja (les statistiques annuelles, le suivi du
-- programme N vs N-1). Mais ce n'est **pas une source** : si le Port ouvre son
-- exercice en juillet, tous les rapports trimestriels sont decales d'un
-- trimestre, et le rapport annuel ne couvre pas la bonne annee.
--
-- En base plutot qu'en dur pour cette raison exactement : la correction est un
-- geste d'administration, pas une livraison. Une valeur hors de 1..12 est
-- ramenee a janvier par le code, qui refuse de fabriquer des bornes qui
-- n'existent pas.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('pilotage.mois_debut_exercice',
   'Premier mois de l''exercice (1 = janvier)',
   '1', 'entier', 'pilotage', 'hypothese',
   NULL,
   'Direction du controle de gestion — exercice budgetaire du Port')
ON CONFLICT (cle) DO NOTHING;
