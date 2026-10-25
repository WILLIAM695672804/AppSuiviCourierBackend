-- =====================================================================
--  cotation_suivi — la personne designee au suivi d'un courrier
--
--  Complement au socle, 12 aout 2026. Le modele de donnees v2 ne portait
--  que la cotation operationnelle : des structures, dont l'une est chef
--  de file (rang 1). Le client a decrit le 11 aout 2026 une SECONDE
--  cotation, que rien ne modelisait :
--
--      « Un courrier porte deux cotations : operationnelle avec chef de
--        file, et pour suivi confiee a une PERSONNE qui coordonne
--        au-dessus du chef de file et rend compte au Directeur general. »
--
--          Cotation pour suivi     <- coordonne tout, rend compte au DG
--                   ^
--            Chef de file          <- coordonne les co-traitantes
--          ^        ^       ^
--       Struct.  Struct.  Struct.  <- traitent
--
--  Consequence pratique : les relances passent par la personne de suivi,
--  pas par le chef de file.
--
--  POURQUOI UNE TABLE ET NON UNE COLONNE SUR cotation.
--  La designation change : un agent part, un autre reprend le suivi. Une
--  colonne ecraserait, et on ne saurait plus qui suivait le courrier au
--  moment ou une relance est partie. Le suivi est une PERIODE, comme le
--  perimetre et le rattachement a une session.
--
--  POURQUOI SUR cotation ET NON SUR courrier.
--  Parce que c'est une cotation. Le geste est le meme — le Directeur
--  general decide qui suit en meme temps qu'il decide qui traite — et le
--  rattacher a la cotation conserve le lien avec la decision qui l'a
--  produite : qui a designe, quand, et sur quelle annotation.
--
--  Voir docs/questions-ouvertes.md, A7 (tranchee), et
--  docs/accueil/02-le-domaine.md.
-- =====================================================================

CREATE TABLE cotation_suivi (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cotation_id    BIGINT      NOT NULL REFERENCES cotation(id) ON DELETE CASCADE,
    -- Une PERSONNE, jamais une structure. C'est ce qui distingue cette
    -- cotation de l'autre, et la contrainte est ici : aucune colonne
    -- structure_id n'existe, et il ne faut pas en ajouter.
    utilisateur_id BIGINT      NOT NULL REFERENCES utilisateur(id),
    motif          TEXT,
    designe_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    designe_par    BIGINT      NOT NULL REFERENCES utilisateur(id),
    retire_le      TIMESTAMPTZ,
    retire_par     BIGINT      REFERENCES utilisateur(id),
    -- Rien n'est efface : une designation se date. Savoir qui suivait le
    -- courrier le jour ou la relance est partie est tout l'objet de la table.
    CONSTRAINT cotation_suivi_retrait_complet
      CHECK ((retire_le IS NULL AND retire_par IS NULL)
          OR (retire_le IS NOT NULL AND retire_par IS NOT NULL)),
    CONSTRAINT cotation_suivi_retrait_posterieur
      CHECK (retire_le IS NULL OR retire_le >= designe_le)
);

-- Une seule personne suit un courrier a la fois. Deux designations
-- ouvertes rendraient la question « qui rend compte au DG ? » sans
-- reponse, et aucun code applicatif ne tient cette garantie sous
-- concurrence. Meme raisonnement que activite_suspension.
CREATE UNIQUE INDEX cotation_suivi_unique_en_cours
    ON cotation_suivi (cotation_id) WHERE retire_le IS NULL;

-- La porte « designation » de la regle de visibilite : ce que je suis, je
-- le vois, meme hors de ma structure. Index partiel, car seules les
-- designations ouvertes ouvrent un acces.
CREATE INDEX cotation_suivi_utilisateur
    ON cotation_suivi (utilisateur_id) WHERE retire_le IS NULL;

COMMENT ON TABLE cotation_suivi IS
  'Cotation pour suivi : la personne qui coordonne au-dessus du chef de file et rend compte au DG. Decision client du 11 aout 2026.';
COMMENT ON COLUMN cotation_suivi.utilisateur_id IS
  'Une personne nommee, jamais une structure. C''est ce qui distingue cette cotation de la cotation operationnelle.';
COMMENT ON COLUMN cotation_suivi.designe_par IS
  'L''autorite qui designe. Meme distinction que cotation.decide_par / cotation.saisi_par.';

CREATE TRIGGER cotation_suivi_historique
    AFTER UPDATE ON cotation_suivi
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();
