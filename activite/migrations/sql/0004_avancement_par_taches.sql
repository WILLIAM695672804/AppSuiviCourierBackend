-- =====================================================================
--  L'avancement d'une activite est la somme de ses taches
--
--  Demande du 11/09/2026, regles RG-1 a RG-9. Voir ADR 049.
--
--  Jusqu'ici deux regimes coexistaient (arbitrage n° 1) : une activite
--  sans tache portait l'avancement que la structure declarait ; une
--  activite a taches le recevait du declencheur, pondere par un poids
--  de 1 a 10 et une case « faite ». L'activite devient une grandeur
--  DERIVEE, et un seul regime subsiste :
--
--    * chaque tache porte une VALEUR PREVUE, sa part de l'activite en
--      points de pourcentage (RG-2) ; la somme vaut 100 (RG-3) ;
--    * la structure declare, tache par tache, une VALEUR OBTENUE,
--      exprimee dans la meme echelle et plafonnee par la valeur prevue
--      (RG-5, RG-6) ;
--    * l'avancement de l'activite est la somme brute des valeurs
--      obtenues (RG-7).
--
--  La declaration est CUMULATIVE, comme l'etait celle de l'activite :
--  chaque declaration remplace la valeur precedente de la tache, elle
--  ne s'y ajoute pas. C'est le mecanisme en place, conserve.
--
--  Le recalibrage de la DSR (ADR 030) descend avec elle : la DSR retient
--  une valeur PAR TACHE, et le taux retenu de l'activite est la somme
--  des valeurs retenues. Arbitrage de l'utilisateur, 11/09/2026 : « il
--  faut que la somme des valeurs obtenues soit egale a la valeur de
--  l'activite ».
--
--  Ce qui vit au moteur : les bornes de chaque ligne (RG-2, RG-6, RG-8,
--  motif du recalibrage) et le calcul de l'activite. Ce qui vit dans le
--  service : les invariants qui portent sur PLUSIEURS lignes ou sur deux
--  tables — la somme a 100 (RG-3), l'existence d'au moins une tache
--  (RG-1), l'inclusion de la periode de la tache dans celle de
--  l'activite (RG-9). Le pourquoi est dans l'ADR 049.
-- =====================================================================

-- Les mises a jour de reprise ne sont le fait de personne : la
-- migration est elle-meme la trace. Meme convention que les traitements
-- nocturnes (noyau/journal/contexte.py).
SELECT set_config('app.contexte', 'migration_avancement_par_taches', true);


-- ---------------------------------------------------------------------
--  1. Les colonnes de la tache
--
--  Ajoutees nullables : elles se remplissent a l'etape 2, et le NOT
--  NULL se pose une fois la reprise faite.
-- ---------------------------------------------------------------------
ALTER TABLE tache
    ADD COLUMN valeur_prevue     NUMERIC(5,2),
    ADD COLUMN valeur_obtenue    NUMERIC(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN valeur_recalibree NUMERIC(5,2),
    ADD COLUMN recalibrage_motif TEXT,
    ADD COLUMN recalibre_le      TIMESTAMPTZ,
    ADD COLUMN recalibre_par     BIGINT,
    ADD COLUMN date_debut        DATE,
    ADD COLUMN date_fin          DATE;


-- ---------------------------------------------------------------------
--  2. Reprise de l'existant
--
--  Les declencheurs de la tache sont suspendus le temps de la reprise :
--  l'ancien calcul d'avancement se serait relance a chaque ligne, et
--  l'historisation aurait inscrit des milliers de changements que
--  personne n'a faits. L'activite est recalculee une seule fois, a
--  l'etape 5.
-- ---------------------------------------------------------------------
ALTER TABLE tache DISABLE TRIGGER tache_avancement;
ALTER TABLE tache DISABLE TRIGGER tache_historique;

-- 2a. Les activites a taches : le poids devient une part.
--
-- part = poids / somme des poids, arrondie au centieme. Le reliquat
-- d'arrondi va a la derniere tache de l'activite, pour que la somme
-- tombe exactement a 100 (RG-3). Une tache faite obtient toute sa part,
-- une autre zero : c'est ce que l'ancien calcul lui faisait deja valoir.
--
-- Les taches invalidees sont reprises sur la meme regle, dans leur
-- propre partition : elles ne comptent plus, mais leurs lignes doivent
-- satisfaire les contraintes posees plus bas.
WITH parts AS (
    SELECT t.id,
           t.activite_id,
           (t.invalide_le IS NULL) AS en_vigueur,
           round(100.0 * t.poids
                 / sum(t.poids) OVER (PARTITION BY t.activite_id, (t.invalide_le IS NULL)), 2)
               AS part,
           row_number() OVER (PARTITION BY t.activite_id, (t.invalide_le IS NULL)
                              ORDER BY t.ordre DESC, t.id DESC) AS rang_depuis_la_fin
      FROM tache t
),
reliquats AS (
    SELECT activite_id, en_vigueur, 100 - sum(part) AS reliquat
      FROM parts
     GROUP BY activite_id, en_vigueur
)
UPDATE tache t
   SET valeur_prevue = p.part + CASE WHEN p.rang_depuis_la_fin = 1 THEN r.reliquat ELSE 0 END
  FROM parts p
  JOIN reliquats r ON r.activite_id = p.activite_id AND r.en_vigueur = p.en_vigueur
 WHERE t.id = p.id;

UPDATE tache
   SET valeur_obtenue = CASE WHEN etat = 'faite' THEN valeur_prevue ELSE 0 END;

-- La periode : du mois de debut de l'activite au mois de l'echeance,
-- ramenee dans la periode de l'activite (RG-9). Sans echeance, la tache
-- court jusqu'a la fin de l'activite.
UPDATE tache t
   SET date_debut = date_trunc('month', a.date_debut)::date,
       date_fin   = (date_trunc('month',
                         LEAST(GREATEST(COALESCE(t.date_echeance, a.date_fin), a.date_debut),
                               a.date_fin))
                     + interval '1 month' - interval '1 day')::date
  FROM activite a
 WHERE a.id = t.activite_id;

-- 2b. Les activites sans tache en vigueur : une tache unique, a 100 %,
-- qui reprend l'avancement declare. C'est la seule reprise qui ne perde
-- rien ; une regularisation manuelle aurait laisse tout le plan en
-- violation de RG-3 jusqu'a ce que chaque structure repasse.
--
-- `fait_le` n'est pose que pour une activite deja declaree a 100 % : la
-- date de sa derniere modification est la meilleure approximation du
-- jour ou elle l'a ete.
--
-- `etat` est encore renseigne : la contrainte tache_faite_datee tient
-- jusqu'a l'etape 3, qui la retire avec la colonne.
INSERT INTO tache (activite_id, intitule, valeur_prevue, valeur_obtenue,
                   date_debut, date_fin, etat, fait_le, ordre, cree_le)
SELECT a.id,
       'Exécution de l''activité',
       100,
       a.avancement_calcule,
       date_trunc('month', a.date_debut)::date,
       (date_trunc('month', a.date_fin) + interval '1 month' - interval '1 day')::date,
       CASE WHEN a.avancement_calcule >= 100 THEN 'faite' ELSE 'a_faire' END,
       CASE WHEN a.avancement_calcule >= 100
            THEN COALESCE(a.modifie_le, a.cree_le)::date END,
       1,
       now()
  FROM activite a
 WHERE NOT EXISTS (
        SELECT 1 FROM tache t WHERE t.activite_id = a.id AND t.invalide_le IS NULL
       );

-- 2c. Le recalibrage de l'activite descend sur ses taches.
--
-- Un taux retenu unique ne dit pas quelle tache la DSR contestait. Il
-- est donc reparti dans l'ordre des taches, chacune a hauteur de sa
-- valeur prevue, jusqu'a epuisement : la somme des valeurs retenues
-- vaut exactement le taux que la DSR avait retenu, et aucune ne depasse
-- sa part (RG-6). Le motif est recopie sur chacune, avec la mention de
-- la reprise : la repartition est une convention, pas un constat.
WITH cumuls AS (
    SELECT t.id,
           t.valeur_prevue,
           a.avancement_recalibre AS retenu,
           a.recalibrage_motif,
           a.recalibre_le,
           a.recalibre_par,
           COALESCE(sum(t.valeur_prevue) OVER (PARTITION BY t.activite_id
                                               ORDER BY t.ordre, t.id
                                               ROWS BETWEEN UNBOUNDED PRECEDING
                                                        AND 1 PRECEDING), 0) AS avant
      FROM tache t
      JOIN activite a ON a.id = t.activite_id
     WHERE t.invalide_le IS NULL
       AND a.avancement_recalibre IS NOT NULL
)
UPDATE tache t
   SET valeur_recalibree = LEAST(c.valeur_prevue, GREATEST(c.retenu - c.avant, 0)),
       recalibrage_motif = COALESCE(NULLIF(btrim(c.recalibrage_motif), ''), 'Recalibrage')
                           || ' (reparti sur les taches lors de la reprise du 11/09/2026)',
       recalibre_le      = c.recalibre_le,
       recalibre_par     = c.recalibre_par
  FROM cumuls c
 WHERE t.id = c.id;


-- ---------------------------------------------------------------------
--  3. Les colonnes remplacees
--
--  poids devient valeur_prevue, etat se lit sur valeur_obtenue,
--  date_echeance devient date_fin. Les garder aurait laisse deux
--  verites, et la premiere requete a lire poids aurait calcule un
--  avancement que plus rien ne produit.
--
--  La vue d'etat depend de etat et de date_echeance : elle tombe avant
--  eux, et se recree a l'etape 6.
-- ---------------------------------------------------------------------
DROP VIEW v_activite_etat;

DROP INDEX IF EXISTS tache_activite;
DROP INDEX IF EXISTS tache_echue;

ALTER TABLE tache
    DROP CONSTRAINT tache_etat_valide,
    DROP CONSTRAINT tache_poids_positif,
    DROP CONSTRAINT tache_faite_datee,
    DROP COLUMN etat,
    DROP COLUMN poids,
    DROP COLUMN date_echeance;

ALTER TABLE tache
    ALTER COLUMN valeur_prevue SET NOT NULL,
    ALTER COLUMN date_debut    SET NOT NULL,
    ALTER COLUMN date_fin      SET NOT NULL;

-- Le taux retenu de la tache : ce que la DSR retient, a defaut ce que
-- la structure declare. Meme construction que activite.avancement_retenu.
ALTER TABLE tache
    ADD COLUMN valeur_retenue NUMERIC(5,2)
    GENERATED ALWAYS AS (COALESCE(valeur_recalibree, valeur_obtenue)) STORED;


-- ---------------------------------------------------------------------
--  4. Les bornes de chaque ligne
-- ---------------------------------------------------------------------
ALTER TABLE tache
    -- RG-2. Strictement positive : une tache de valeur nulle ne peut
    -- rien obtenir (RG-6), ne se realise jamais, et son avancement propre
    -- serait une division par zero.
    ADD CONSTRAINT tache_valeur_prevue_bornee
      CHECK (valeur_prevue > 0 AND valeur_prevue <= 100),
    -- RG-6. La valeur obtenue cumulee ne depasse pas la part de la tache.
    ADD CONSTRAINT tache_valeur_obtenue_plafonnee
      CHECK (valeur_obtenue >= 0 AND valeur_obtenue <= valeur_prevue),
    -- La DSR est tenue par la meme borne que la structure.
    ADD CONSTRAINT tache_recalibrage_plafonne
      CHECK (valeur_recalibree IS NULL
             OR (valeur_recalibree >= 0 AND valeur_recalibree <= valeur_prevue)),
    -- ADR 030 : contredire une structure sans ecrire pourquoi ne se
    -- corrige pas, cela se conteste.
    ADD CONSTRAINT tache_recalibrage_motive
      CHECK (valeur_recalibree IS NULL
             OR (recalibrage_motif IS NOT NULL AND length(btrim(recalibrage_motif)) > 0)),
    -- RG-8. Des mois entiers : premier jour au debut, dernier a la fin.
    ADD CONSTRAINT tache_periode_au_mois
      CHECK (date_debut = date_trunc('month', date_debut)::date
             AND date_fin = (date_trunc('month', date_fin)
                             + interval '1 month' - interval '1 day')::date
             AND date_debut <= date_fin),
    -- Une tache est realisee quand elle a obtenu toute sa part, et
    -- seulement alors elle porte une date de realisation.
    ADD CONSTRAINT tache_realisee_datee
      CHECK ((valeur_obtenue >= valeur_prevue) = (fait_le IS NOT NULL));

CREATE INDEX tache_activite ON tache (activite_id) WHERE invalide_le IS NULL;

-- Les taches echues non realisees : l'une des deux contraintes qui
-- rendent une activite critique au tableau de bord du DG (§20).
CREATE INDEX tache_echue
    ON tache (date_fin)
    WHERE valeur_retenue < valeur_prevue AND invalide_le IS NULL;

COMMENT ON COLUMN tache.valeur_prevue IS
  'RG-2. Part de la tache dans l''activite, en points de pourcentage. La somme des taches en vigueur d''une activite vaut 100 (RG-3, controle par le service). ADR 049.';
COMMENT ON COLUMN tache.valeur_obtenue IS
  'RG-5. Ce que la structure declare, dans l''echelle de l''activite. Cumulative : chaque declaration remplace la precedente. Plafonnee par valeur_prevue (RG-6).';
COMMENT ON COLUMN tache.valeur_recalibree IS
  'Ce que la DSR retient pour cette tache quand la declaration n''est pas justifiee. NULL = pas de desaccord. ADR 030, ADR 049.';
COMMENT ON COLUMN tache.valeur_retenue IS
  'GENEREE : COALESCE(valeur_recalibree, valeur_obtenue). La somme des taches donne activite.avancement_retenu.';
COMMENT ON COLUMN tache.date_debut IS
  'RG-8. Premier jour du mois de debut. Comprise dans la periode de l''activite (RG-9, controle par le service).';
COMMENT ON COLUMN tache.date_fin IS
  'RG-8. Dernier jour du mois de fin. Tient lieu d''echeance pour la criticite du §20.';


-- ---------------------------------------------------------------------
--  5. Le calcul de l'activite
--
--  RG-7 : avancement = somme brute des valeurs obtenues, sans
--  normalisation. La borne a 100 decoule de RG-3 et RG-6 ; elle n'est
--  pas imposee ici, et la contrainte activite_avancement_borne crie si
--  un jour elle ne tient plus — un LEAST() l'aurait masque.
--
--  Le taux retenu suit la meme regle sur les valeurs retenues. Il reste
--  NULL tant qu'aucune tache n'est recalibree : c'est ce qui permet a la
--  fiche de dire qu'il n'y a pas de desaccord.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_avancement_activite() RETURNS TRIGGER AS $$
DECLARE
    v_activite  BIGINT := COALESCE(NEW.activite_id, OLD.activite_id);
    v_declare   NUMERIC(5,2);
    v_retenu    NUMERIC(5,2);
BEGIN
    SELECT COALESCE(sum(valeur_obtenue), 0),
           CASE WHEN bool_or(valeur_recalibree IS NOT NULL)
                THEN sum(valeur_retenue) END
      INTO v_declare, v_retenu
      FROM tache
     WHERE activite_id = v_activite AND invalide_le IS NULL;

    -- La clause finale evite de reecrire la ligne quand rien ne change :
    -- sans elle, chaque enregistrement de tache declencherait
    -- l'historisation complete de l'activite pour un resultat identique.
    UPDATE activite
       SET avancement_calcule   = v_declare,
           avancement_recalibre = v_retenu
     WHERE id = v_activite
       AND (avancement_calcule   IS DISTINCT FROM v_declare
         OR avancement_recalibre IS DISTINCT FROM v_retenu);

    RETURN NULL;
END $$ LANGUAGE plpgsql;

-- La date de realisation suit la valeur obtenue : posee le jour ou la
-- tache atteint sa part, conservee tant qu'elle y reste, effacee si une
-- declaration la fait redescendre.
CREATE OR REPLACE FUNCTION dater_realisation_tache() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.valeur_obtenue < NEW.valeur_prevue THEN
        NEW.fait_le := NULL;
    ELSIF TG_OP = 'UPDATE' AND OLD.fait_le IS NOT NULL
          AND OLD.valeur_obtenue >= OLD.valeur_prevue THEN
        NEW.fait_le := OLD.fait_le;
    ELSE
        NEW.fait_le := COALESCE(NEW.fait_le, CURRENT_DATE);
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER tache_realisation
    BEFORE INSERT OR UPDATE OF valeur_obtenue, valeur_prevue ON tache
    FOR EACH ROW EXECUTE FUNCTION dater_realisation_tache();

-- Le recalibrage de l'activite n'a plus de motif propre : il est la
-- somme de recalibrages de taches, chacun motive. Les trois colonnes
-- tombent avec la contrainte qui les liait.
ALTER TABLE activite
    DROP CONSTRAINT activite_recalibrage_motive;

-- Le recalcul unique de l'etape 2. La garde de suspension est levee le
-- temps de cette seule instruction : l'arrondi de la reprise peut
-- deplacer d'un centieme l'avancement d'une activite suspendue, et le
-- declencheur le refuserait alors que personne ne declare rien.
ALTER TABLE activite DISABLE TRIGGER activite_avancement_suspendue;
ALTER TABLE activite DISABLE TRIGGER activite_historique;

UPDATE activite a
   SET avancement_calcule   = s.declare,
       avancement_recalibre = s.retenu
  FROM (
        SELECT activite_id,
               sum(valeur_obtenue) AS declare,
               CASE WHEN bool_or(valeur_recalibree IS NOT NULL)
                    THEN sum(valeur_retenue) END AS retenu
          FROM tache
         WHERE invalide_le IS NULL
         GROUP BY activite_id
       ) s
 WHERE a.id = s.activite_id
   AND (a.avancement_calcule   IS DISTINCT FROM s.declare
     OR a.avancement_recalibre IS DISTINCT FROM s.retenu);

ALTER TABLE activite ENABLE TRIGGER activite_historique;
ALTER TABLE activite ENABLE TRIGGER activite_avancement_suspendue;
ALTER TABLE tache ENABLE TRIGGER tache_historique;
ALTER TABLE tache ENABLE TRIGGER tache_avancement;

ALTER TABLE activite
    DROP COLUMN recalibrage_motif,
    DROP COLUMN recalibre_le,
    DROP COLUMN recalibre_par;

COMMENT ON COLUMN activite.avancement_calcule IS
  'RG-7. Somme des valeurs obtenues des taches en vigueur, posee par maj_avancement_activite(). Jamais saisie. ADR 049.';
COMMENT ON COLUMN activite.avancement_recalibre IS
  'Somme des valeurs retenues des taches, des qu''au moins une est recalibree par la DSR. NULL = pas de desaccord. ADR 049.';


-- ---------------------------------------------------------------------
--  6. La vue d'etat
--
--  Memes colonnes qu'avant : pilotage et performance la lisent. Seule la
--  contrainte echue change de forme — une tache non realisee est une
--  tache dont la valeur RETENUE n'atteint pas sa part, et son echeance
--  est la fin de son dernier mois. Retenue et non declaree : une tache
--  que la structure dit finie et que la DSR conteste n'est pas finie.
-- ---------------------------------------------------------------------
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
       EXISTS (
           SELECT 1 FROM instruction_activite i
            WHERE i.activite_id = a.id AND i.levee_le IS NULL
              AND i.echeance < CURRENT_DATE AND i.invalide_le IS NULL
       ) OR EXISTS (
           SELECT 1 FROM tache t
            WHERE t.activite_id = a.id AND t.invalide_le IS NULL
              AND t.valeur_retenue < t.valeur_prevue
              AND t.date_fin < CURRENT_DATE
       ) AS contrainte_echue
  FROM activite a
  JOIN paa p ON p.id = a.paa_id
 WHERE a.invalide_le IS NULL;

COMMENT ON VIEW v_activite_etat IS
  'Etat affiche, contrainte echue et taux retenu. La criticite du §20 se lit ici : etat_affiche = ''en_retard'' ET contrainte_echue.';
