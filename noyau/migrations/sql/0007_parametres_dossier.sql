-- Trois reglages sans source du pilier dossiers — A37 et A38.
--
-- Ils gouvernent ce que l'instructeur voit et ce que le systeme lui refuse.
-- Aucun document de cadrage ne les fixe : ils sont inventes, et c'est
-- precisement pour cela qu'ils sont ici et non dans le code. En `hypothese`,
-- visibles, corrigibles sans redeploiement.
--
-- 1. Le seuil d'alerte du registre.
--
--    A partir de combien de jours restants un dossier passe-t-il a l'orange ?
--    Trois, parce qu'il en faut un et parce que c'est l'ordre de grandeur d'un
--    delai de reaction utile : en dessous, l'instructeur n'a plus le temps de
--    reclamer une piece. Ce chiffre decide de la couleur d'une ligne dans le
--    registre d'un responsable ; il ne se devine pas.
--
-- 2. Le delai d'instruction par defaut.
--
--    Applique quand celui qui ouvre le dossier ne saisit pas d'echeance.
--    Trente jours est le delai de reponse administratif le plus courant ; il
--    n'a ete confirme par personne pour le Port autonome de Douala, et il
--    varie tres probablement selon la typologie — une autorisation d'occupation
--    du domaine et une reclamation ne s'instruisent pas dans le meme temps.
--
-- 3. La longueur minimale du motif de retour.
--
--    RF-BPM-06 exige un motif ; il ne dit pas ce qui compte comme motif.
--    Quinze caracteres ecartent « ok », « a revoir » et « non » sans pretendre
--    juger du fond. C'est un garde-fou, pas un controle de qualite : aucun
--    nombre de caracteres ne rend une explication utile.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('dossier.seuil_alerte_jours',
   'Jours restants en deca desquels un dossier passe en alerte au registre',
   '3', 'entier', 'dossier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)'),
  ('dossier.delai_instruction_defaut_jours',
   'Delai d''instruction applique quand aucune echeance n''est saisie',
   '30', 'entier', 'dossier', 'hypothese',
   NULL,
   'Direction generale, sur proposition des directions instructrices'),
  ('dossier.longueur_minimale_motif',
   'Nombre de caracteres au-dessous duquel un motif de retour est refuse',
   '15', 'entier', 'dossier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3)')
ON CONFLICT (cle) DO NOTHING;
