-- =====================================================================
--  L'activite est portee par des STRUCTURES, pas par un agent
--
--  Exigence de l'utilisateur (arbitrage du 09/09/2026) : « on n'affecte
--  pas un agent a une activite, c'est la structure qui est affectee a
--  une activite. Par defaut c'est la structure qui enregistre, mais il
--  peut y avoir plusieurs structures ». Voir ADR 047.
--
--  Deux mouvements, et un seul principe : la responsabilite d'une
--  activite est institutionnelle.
--
--    1. activite_structure — les structures ASSOCIEES. La table ne
--       porte QUE celles-la. La structure porteuse reste paa.structure_id
--       et n'est pas dupliquee ici : le modele proscrit deja d'ecrire
--       deux fois la meme verite, et c'est la visibilite de l'activite
--       qui en depend (voir l'entete du modele Activite).
--
--    2. activite.responsable_id devient nullable. Le point focal reste
--       utile — quelqu'un decroche le telephone — mais il ne fonde plus
--       la responsabilite. Les activites existantes gardent le leur :
--       aucune reprise de donnees, la colonne se contente de s'ouvrir.
--
--  L'inscription au PAA ne bouge pas : une activite reste inscrite au
--  SEUL plan de sa structure porteuse. Les agregats (agregat_activite_jour),
--  le taux du plan et les tableaux de bord continuent de compter par
--  paa.structure_id, sans double comptage.
-- =====================================================================

-- ---------------------------------------------------------------------
--  Les structures associees
--
--  Invalidation logique (invalide_le) et non DELETE : retirer une
--  structure d'une activite est un geste qui se justifie et se relit
--  dans la fiche de vie. Un DELETE effacerait la question de savoir qui
--  en repondait au trimestre precedent.
--
--  L'unicite est PARTIELLE : une structure retiree puis rattachee de
--  nouveau produit deux lignes, dont une seule en vigueur. Une unicite
--  pleine interdirait le second rattachement.
-- ---------------------------------------------------------------------
CREATE TABLE activite_structure (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_id  BIGINT      NOT NULL REFERENCES activite(id) ON DELETE CASCADE,
    structure_id BIGINT      NOT NULL REFERENCES structure(id),
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par     BIGINT,
    invalide_le  TIMESTAMPTZ,
    invalide_par BIGINT
);

CREATE UNIQUE INDEX activite_structure_unique
    ON activite_structure (activite_id, structure_id)
    WHERE invalide_le IS NULL;

-- La lecture dominante : « quelles structures pour cette activite ».
CREATE INDEX activite_structure_activite
    ON activite_structure (activite_id)
    WHERE invalide_le IS NULL;

-- La lecture inverse, celle du perimetre : « quelles activites pour ces
-- structures ». Elle passe dans le filtre de visibilite de chaque
-- registre et de chaque fiche ; sans index, chaque ouverture d'ecran
-- balaierait la table.
CREATE INDEX activite_structure_structure
    ON activite_structure (structure_id)
    WHERE invalide_le IS NULL;

COMMENT ON TABLE activite_structure IS
  'Structures ASSOCIEES a une activite, en sus de la structure porteuse (paa.structure_id) qui n''y figure jamais. ADR 047.';
COMMENT ON COLUMN activite_structure.invalide_le IS
  'Retrait logique. Une structure retiree reste lisible dans la fiche de vie : c''est elle qui en repondait avant.';

-- ---------------------------------------------------------------------
--  Le point focal cesse d'etre obligatoire
--
--  Le NOT NULL disait « une activite a un responsable nomme ». Ce n'est
--  plus la regle : elle a des structures responsables, et eventuellement
--  un point focal. L'index sur responsable_id reste utile — la portee
--  « propre » filtre dessus — mais il devient partiel : indexer les NULL
--  n'apporterait rien a une requete qui cherche un identifiant precis.
-- ---------------------------------------------------------------------
ALTER TABLE activite
    ALTER COLUMN responsable_id DROP NOT NULL;

DROP INDEX IF EXISTS activite_responsable;
CREATE INDEX activite_responsable
    ON activite (responsable_id)
    WHERE responsable_id IS NOT NULL;

COMMENT ON COLUMN activite.responsable_id IS
  'Point focal facultatif. La responsabilite de l''activite est portee par les structures : paa.structure_id et activite_structure. ADR 047.';
