-- =====================================================================
--  0017 — De quoi accueillir l'organigramme reel du Port.
--
--  Deux manques, tous deux constates en transcrivant la planche A3
--  « Organigramme du PAD Propose » du 10 novembre 2025.
-- =====================================================================

-- ---------------------------------------------------------------------
--  1. Les natures manquantes.
--
--  Le socle en connaissait cinq — Direction, Service, Division, Filiale,
--  Succursale. La planche en dessine sept de plus : une cellule n'est pas
--  une division, un departement n'est pas un service, et le Conseil
--  d'administration n'est rien de tout cela.
--
--  Les cinq d'origine sont conservees telles quelles. Filiale et
--  Succursale ne figurent pas sur la planche mais restent : le §3.3 du
--  descriptif fonctionnel confie a la DSR le suivi de leurs organes de
--  gestion, et le Port en a.
-- ---------------------------------------------------------------------
ALTER TABLE structure DROP CONSTRAINT structure_nature_valide;
ALTER TABLE structure ADD CONSTRAINT structure_nature_valide
  CHECK (nature IN (
    'Direction', 'Service', 'Division', 'Filiale', 'Succursale',
    'Departement', 'Cellule', 'Centre', 'Cabinet', 'Representation',
    'Secteur', 'Organe'
  ));

-- ---------------------------------------------------------------------
--  2. Les deux rangs manquants.
--
--  La legende de la planche nomme quatre rangs : directeur, directeur
--  adjoint, sous-directeur, chef de service. Le socle en avait seme
--  quatre autres — DG, DIR, DEP, SERV — dont deux seulement coincident.
--  Il manque le directeur adjoint, qui dirige les divisions internes aux
--  directions metier, et le sous-directeur, qui dirige les departements
--  et les cellules.
--
--  DEP reste. Rien ne le porte dans l'organigramme reel — un departement
--  est dirige par un sous-directeur, pas par un « rang departement » —
--  mais le supprimer casserait les bases deja installees, et un etage
--  inutilise ne coute rien. Il descend simplement sous SOUS_DIR.
--
--  Les rangs sont renumerotes pour laisser la place. L'ordre relatif des
--  quatre etages d'origine est preserve : aucun code ne lit un rang en
--  dur (principe 3 de `modeles.py`), seul l'ordre compte.
--
--      avant              apres
--      1  DG              1  DG
--      2  DIR             2  DIR
--                         3  DIR_ADJ    (nouveau)
--                         4  SOUS_DIR   (nouveau)
--      3  DEP             5  DEP
--      4  SERV            6  SERV
-- ---------------------------------------------------------------------

-- Faire de la place avant d'inserer. L'index `niveau_rang_unique` du socle
-- interdit deux etages au meme rang : il faut donc pousser SERV puis DEP
-- vers le bas AVANT d'inserer, et dans cet ordre — commencer par DEP le
-- ferait entrer en collision avec SERV.
UPDATE niveau_hierarchique SET rang = 6 WHERE code = 'SERV';
UPDATE niveau_hierarchique SET rang = 5 WHERE code = 'DEP';

INSERT INTO niveau_hierarchique
    (code, libelle, rang, actif, peut_coter, peut_recevoir_cotation,
     porte_signature, ligne_statistiques)
VALUES
    ('DIR_ADJ',  'Directeur Adjoint', 3, true, true, true, false, true),
    ('SOUS_DIR', 'Sous-Directeur',    4, true, true, true, false, true)
ON CONFLICT (code) DO NOTHING;

-- Rechainer les six etages dans l'ordre du rang. Le socle chainait
-- DG → DIR → DEP → SERV ; les deux nouveaux s'inserent au milieu, et le
-- chainage doit suivre, sinon l'ecran d'administration proposerait de
-- placer un departement sous une direction en sautant deux etages.
--
-- Le chainage par le rang n'est vrai que du semis : un administrateur qui
-- intercale un etage plus tard reprend le rattachement lui-meme.
UPDATE niveau_hierarchique n
   SET niveau_parent_id = p.id
  FROM niveau_hierarchique p
 WHERE p.rang = n.rang - 1
   AND p.invalide_le IS NULL
   AND n.invalide_le IS NULL;

-- Un etage qui ne peut pas coter est celui qui n'a personne en dessous.
-- SERV etait la feuille ; il l'est reste.
UPDATE niveau_hierarchique SET peut_coter = false WHERE code = 'SERV';
