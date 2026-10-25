-- A partir de combien de lignes un tableau part-il en annexe ? — A58
--
-- La note de synthese se lit en seance, une fois, sur papier. Un classement de
-- vingt-quatre structures au milieu du corps repousse les points d'arbitrage en
-- page trois, et personne ne les lit. Au-dela du seuil, le corps garde les
-- premieres et les dernieres lignes et renvoie a l'annexe.
--
-- Douze parce qu'il faut une valeur, et parce que c'est ce qui tient sous les
-- chiffres d'ensemble sans pousser la section suivante a la page suivante.
-- Aucun document de cadrage ne le fixe : ni le CDC, ni le BRD, ni les
-- decisions. Le poser en base ne le rend pas vrai — il le rend visible et
-- corrigible sans redeploiement (ADR 016, ADR 005).

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('pilotage.lignes_avant_annexe',
   'Nombre de lignes au-dela duquel un tableau de la note de synthese part en annexe',
   '12', 'entier', 'pilotage', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)')
ON CONFLICT (cle) DO NOTHING;
