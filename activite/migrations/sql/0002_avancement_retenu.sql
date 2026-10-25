-- =====================================================================
--  Le taux declare et le taux retenu sont deux choses
--
--  Exigence : « la structure declare son avancement (pourcentage +
--  justification dans l'observation qui alimente la fiche de vie), mais
--  seule la DSR dispose du droit de modifier ou de recalibrer ce
--  pourcentage si les realisations ne sont pas justifiees ».
--
--  Le schema livre n'avait qu'une colonne, avancement_calcule, ecrite
--  par la structure ou par le declencheur des taches. Y laisser la DSR
--  ecrire aurait detruit la seule chose qui rend le recalibrage utile :
--  savoir ce que la structure avait declare. Le desaccord serait devenu
--  invisible le jour meme ou il se produit.
--
--  D'ou trois colonnes et une quatrieme, generee :
--
--    * avancement_calcule   - ce que la structure declare, ou ce que ses
--                             taches produisent. Inchangee.
--    * avancement_recalibre - ce que la DSR retient. NULL tant qu'elle
--                             n'a pas contredit la structure.
--    * recalibrage_motif    - pourquoi. Obligatoire des que le
--                             precedent est non nul.
--    * avancement_retenu    - GENEREE : COALESCE des deux. C'est elle
--                             que lisent les tableaux de bord, les
--                             scores et les agregats.
--
--  La colonne generee est le point d'appui : sans elle, chacun des six
--  consommateurs de l'avancement aurait ecrit son propre COALESCE, et
--  il aurait suffi qu'un seul l'oublie pour qu'un ecran continue
--  d'afficher un taux que la DSR a rejete.
-- =====================================================================

ALTER TABLE activite
    ADD COLUMN avancement_recalibre NUMERIC(5,2),
    ADD COLUMN recalibrage_motif    TEXT,
    ADD COLUMN recalibre_le         TIMESTAMPTZ,
    ADD COLUMN recalibre_par        BIGINT;

ALTER TABLE activite
    ADD CONSTRAINT activite_recalibrage_borne
      CHECK (avancement_recalibre IS NULL
             OR avancement_recalibre BETWEEN 0 AND 100),
    -- Meme regle que paa_retour_motive : contredire une structure sans
    -- ecrire pourquoi ne se corrige pas, cela se conteste.
    ADD CONSTRAINT activite_recalibrage_motive
      CHECK (avancement_recalibre IS NULL
             OR (recalibrage_motif IS NOT NULL
                 AND length(btrim(recalibrage_motif)) > 0));

-- STORED et non VIRTUAL : PostgreSQL 16 ne connait que STORED, et le
-- taux retenu est lu bien plus souvent qu'il n'est ecrit.
ALTER TABLE activite
    ADD COLUMN avancement_retenu NUMERIC(5,2)
    GENERATED ALWAYS AS (COALESCE(avancement_recalibre, avancement_calcule)) STORED;

COMMENT ON COLUMN activite.avancement_calcule IS
  'Ce que la structure declare, ou ce que ses taches produisent (arbitrage n° 1). Jamais ecrit par la DSR.';
COMMENT ON COLUMN activite.avancement_recalibre IS
  'Le taux que la DSR retient quand les realisations ne sont pas justifiees. NULL = pas de desaccord.';
COMMENT ON COLUMN activite.recalibrage_motif IS
  'Pourquoi la DSR a contredit la structure. Obligatoire des que avancement_recalibre est pose.';
COMMENT ON COLUMN activite.avancement_retenu IS
  'Le taux qui fait foi : COALESCE(avancement_recalibre, avancement_calcule). C''est lui que lisent tableaux de bord, scores et agregats.';


-- ---------------------------------------------------------------------
--  Une activite suspendue ne se recalibre pas davantage qu'elle ne se
--  declare. Le declencheur livre ne surveillait que avancement_calcule ;
--  laisser passer le recalibrage aurait rouvert par la fenetre ce que
--  le §19 ferme par la porte.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION refuser_avancement_si_suspendue() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.etat = 'suspendue'
       AND (NEW.avancement_calcule   IS DISTINCT FROM OLD.avancement_calcule
         OR NEW.avancement_recalibre IS DISTINCT FROM OLD.avancement_recalibre) THEN
        RAISE EXCEPTION
            'Activite % suspendue : l''avancement ne peut pas etre modifie tant que la suspension n''est pas levee.',
            OLD.code
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------------
--  La vue de l'etat affiche sert desormais le taux retenu.
--
--  Elle continue de servir avancement_calcule a cote : un ecran qui
--  montre le desaccord a besoin des deux, et la fiche de vie doit
--  pouvoir dire « declare 80, retenu 50 ».
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_activite_etat;

CREATE VIEW v_activite_etat AS
SELECT a.id,
       a.paa_id,
       p.structure_id,
       a.etat AS etat_stocke,
       CASE
           WHEN a.etat = 'suspendue'                    THEN 'suspendue'
           WHEN a.etat = 'realisee'                     THEN 'realisee'
           WHEN a.date_debut > CURRENT_DATE             THEN 'programmee'
           WHEN a.date_fin   < CURRENT_DATE             THEN 'en_retard'
           ELSE 'en_cours'
       END AS etat_affiche,
       a.avancement_calcule,
       a.avancement_recalibre,
       a.avancement_retenu,
       -- Une contrainte exterieure echue : instruction non levee ou
       -- tache non faite. C'est la seconde condition de la criticite du
       -- §20 - le retard seul ne suffit pas, sans quoi la moitie du
       -- plan serait critique et le mot ne trierait plus rien.
       EXISTS (
           SELECT 1 FROM instruction_activite i
            WHERE i.activite_id = a.id AND i.levee_le IS NULL
              AND i.echeance < CURRENT_DATE AND i.invalide_le IS NULL
       ) OR EXISTS (
           SELECT 1 FROM tache t
            WHERE t.activite_id = a.id AND t.etat <> 'faite'
              AND t.date_echeance < CURRENT_DATE AND t.invalide_le IS NULL
       ) AS contrainte_echue
  FROM activite a
  JOIN paa p ON p.id = a.paa_id
 WHERE a.invalide_le IS NULL;

COMMENT ON VIEW v_activite_etat IS
  'Etat affiche, contrainte echue et taux retenu. La criticite du §20 se lit ici : etat_affiche = ''en_retard'' ET contrainte_echue.';


-- ---------------------------------------------------------------------
--  La permission du recalibrage.
--
--  Une permission neuve, et non ACT_VAL : le controle de gestion porte
--  ACT_VAL lui aussi, et l'exigence dit « seule la DSR ». Une permission
--  qui donnerait le geste a deux profils ne serait pas la regle
--  demandee, ce serait une autre regle.
--
--  Elle n'est donnee ni a ATT_DSR, ni a l'administrateur : l'attache
--  exerce le suivi de portefeuille et la relance (CDC §12), contredire
--  une structure sur ses realisations est un autre geste. Voir
--  docs/questions-ouvertes.md.
-- ---------------------------------------------------------------------
INSERT INTO permission (code, libelle, domaine) VALUES
  ('ACT_REC', 'Recalibrer l''avancement declare', 'activite')
ON CONFLICT (code) DO NOTHING;

INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id
  FROM profil p, permission x
 WHERE p.code = 'DSR' AND x.code = 'ACT_REC'
ON CONFLICT DO NOTHING;
