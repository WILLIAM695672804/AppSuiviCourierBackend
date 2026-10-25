-- ---------------------------------------------------------------------
--  La tete de structure, et le poste qui la dirige.
--
--  Jusqu'ici, rien en base ne disait que DEXP-OP appartient a DEXP.
--  `structure.parent_id` porte l'arbre et `Structure.descendants()` le
--  descend, mais **l'arbre ne se remonte pas** : d'un service, aucune
--  requete ne nommait la direction sous laquelle il se compte. Chaque
--  agregation du tableau de bord avait donc besoin d'un etage qui
--  n'existait pas.
--
--  Une tete de structure est un **enfant direct de la racine**. Sur la
--  planche du Port elles sont dix-neuf : dix directions, cinq divisions
--  (DQDD, DSR, DAI, DAPC, DCRP), le Cabinet et trois representations. Le
--  rang ne suffit pas a les designer — le Cabinet est au rang SERV, les
--  representations au rang DIR_ADJ, les directions au rang DIR. Seul
--  l'arbre les separe, d'ou la definition par l'arbre.
--
--  Et elle est **materialisee**, pas calculee a la lecture : toute
--  agregation du tableau de bord regroupe par tete, et poser une CTE
--  recursive sous chaque GROUP BY couterait une remontee d'arbre par
--  ligne agregee. La colonne est tenue par un declencheur, ce qui la rend
--  juste sans demander a personne d'y penser.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
--  1. La colonne.
--
--  Nullable, et il faut qu'elle le reste : la racine n'a pas de tete, et
--  le Conseil d'administration — nature « Organe », hors ligne
--  hierarchique — non plus. Un NOT NULL aurait force a inventer une
--  valeur pour deux lignes qui n'en ont pas.
-- ---------------------------------------------------------------------
ALTER TABLE structure ADD COLUMN IF NOT EXISTS tete_id BIGINT REFERENCES structure(id);

COMMENT ON COLUMN structure.tete_id IS
  'Ancetre enfant direct de la racine. Une tete est sa propre tete. NULL pour la racine et pour les organes hors ligne hierarchique.';

-- Partiel sur les lignes en vigueur : le regroupement par tete ne porte
-- jamais sur les lignes closes, et l'historique de l'organigramme est
-- volumineux (rien n'est supprime, on clot et on reinsere).
CREATE INDEX IF NOT EXISTS structure_tete ON structure (tete_id) WHERE valide_au IS NULL;


-- ---------------------------------------------------------------------
--  2. Le calcul, ecrit UNE fois.
--
--  Le remplissage initial et le declencheur ont besoin de la meme
--  reponse. Deux formulations auraient diverge au premier deplacement de
--  structure, et rien n'aurait signale la divergence : une tete fausse ne
--  leve aucune erreur, elle deplace juste des chiffres d'un etage a
--  l'autre. Une seule fonction, donc.
--
--  **La racine de l'arbre n'est pas la Direction generale.** La planche
--  inscrit le Conseil d'administration au-dessus d'elle, et c'est lui qui
--  n'a pas de parent. Definir la tete comme « enfant direct de la racine »
--  aurait donc designe la Direction generale, et fait remonter les
--  soixante-seize structures du Port sous une tete unique. Le jeu d'essai
--  masquait la faute : sa Direction generale est la racine.
--
--  La racine qui compte est celle de la **ligne hierarchique** :
--  l'ancetre non deliberant le plus haut. Le Conseil d'administration se
--  reconnait a sa nature — « Organe » — et cette nature dit deja ce
--  qu'il faut : il delibere, il ne dirige pas, il ne recoit pas de
--  cotation et ne porte aucun poste (voir A60 dans
--  `noyau/organisation/donnees/organigramme_pad.py`).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION structure_tete_de(cible BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE remontee AS (
        SELECT id, parent_id, nature, 0 AS profondeur
          FROM structure
         WHERE id = cible
        UNION ALL
        SELECT s.id, s.parent_id, s.nature, r.profondeur + 1
          FROM structure s
          JOIN remontee r ON r.parent_id = s.id
    ),
    -- Le sommet de la ligne hierarchique : l'ancetre dirigeant le plus
    -- haut. `profondeur DESC` et non `parent_id IS NULL` — sans quoi on
    -- retomberait sur le Conseil d'administration.
    racine AS (
        SELECT id FROM remontee
         WHERE nature <> 'Organe'
         ORDER BY profondeur DESC
         LIMIT 1
    )
    -- L'ancetre dont le parent est ce sommet. Si la cible est deja une
    -- tete, elle se rend elle-meme — une tete est sa propre tete. Si la
    -- cible EST le sommet, ou le Conseil d'administration, rien ne
    -- correspond et la fonction rend NULL.
    SELECT r.id
      FROM remontee r
      JOIN racine ON r.parent_id = racine.id
     ORDER BY r.profondeur
     LIMIT 1;
$$;

COMMENT ON FUNCTION structure_tete_de(BIGINT) IS
  'La tete de structure : l''ancetre enfant direct du sommet de la ligne hierarchique. NULL pour ce sommet et pour les organes deliberants.';


-- ---------------------------------------------------------------------
--  3. `tete_id` sort de l'historisation des champs.
--
--  `structure_historique` (socle, 0001) inscrit dans `champ_historique`
--  toute colonne modifiee, et **refuse l'ecriture** quand aucun acteur
--  n'est pose — RNF-TRACE-01. C'est juste pour `code`, `libelle`,
--  `parent_id` : ce sont des decisions, quelqu'un les prend.
--
--  `tete_id` n'en est pas une. Elle se **deduit** de `parent_id`, qui est
--  deja historisee, et se recalcule seule. L'inscrire ecrirait une ligne
--  d'historique par descendant a chaque reorganisation — la DSI et ses
--  deux services en produiraient trois pour un seul geste — sans rien
--  apprendre que `parent_id` ne dise deja.
--
--  L'exclure regle du meme coup deux choses qui, autrement, auraient
--  demande chacune leur rustine :
--
--   * le remplissage initial ci-dessous, qui n'a pas d'acteur a offrir ;
--   * l'UPDATE que le declencheur de la section 5 emet a chaque
--     deplacement, qui en aurait exige un a son tour.
--
--  Le mecanisme est celui, deja en place, de `modifie_le` et
--  `recherche` : la colonne est retiree des deux `to_jsonb`, les objets
--  compares deviennent egaux, et la fonction sort par son premier `IF`
--  — avant le controle d'acteur.
--
--  La fonction est redefinie **en entier** : `CREATE OR REPLACE` ne
--  connait pas de correctif partiel. Toute evolution ulterieure de
--  `historiser_champs()` doit repartir de cette version-ci.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION historiser_champs() RETURNS TRIGGER AS $$
DECLARE
    v_acteur BIGINT := nullif(current_setting('app.utilisateur_id', true), '')::BIGINT;
    v_avant_json JSONB := to_jsonb(OLD) - 'modifie_le' - 'recherche' - 'tete_id';
    v_apres_json JSONB := to_jsonb(NEW) - 'modifie_le' - 'recherche' - 'tete_id';
    v_contexte TEXT := nullif(current_setting('app.contexte', true), '');
    v_col    TEXT;
    v_avant  TEXT;
    v_apres  TEXT;
BEGIN
    IF v_avant_json = v_apres_json THEN
        RETURN NEW;
    END IF;

    IF v_acteur IS NULL AND v_contexte IS NULL THEN
        RAISE EXCEPTION
            'Modification de % sans acteur identifie. Positionner SET LOCAL app.utilisateur_id, ou SET LOCAL app.contexte pour un traitement non nominatif.',
            TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
    END IF;

    FOR v_col, v_apres IN SELECT * FROM jsonb_each_text(v_apres_json)
    LOOP
        v_avant := v_avant_json ->> v_col;
        IF v_avant IS DISTINCT FROM v_apres THEN
            INSERT INTO champ_historique
                (table_cible, ligne_id, colonne, valeur_avant, valeur_apres, acteur_id)
            VALUES (TG_TABLE_NAME, NEW.id, v_col, v_avant, v_apres, v_acteur);
        END IF;
    END LOOP;
    RETURN NEW;
END $$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------------
--  4. Le remplissage initial.
--
--  Avant que le declencheur ne soit pose : il ne tire qu'a l'ecriture et
--  ne rattraperait pas les lignes deja en base.
-- ---------------------------------------------------------------------
UPDATE structure SET tete_id = structure_tete_de(id);


-- ---------------------------------------------------------------------
--  5. Le declencheur.
--
--  Deplacer une structure deplace tout son sous-arbre : rattacher DEXP-OP
--  ailleurs change la tete de DEXP-OP-ECD sans que la ligne de ce dernier
--  soit touchee. On recalcule donc le noeud ET ses descendants.
--
--  **`pg_trigger_depth() = 0`, et surtout pas `= 1`.** La clause WHEN est
--  evaluee AVANT que la profondeur ne s'incremente : elle vaut 0 pour un
--  declencheur tire par une ecriture ordinaire, et 1 seulement une fois
--  entre dans la fonction. Ecrire `= 1` produit un declencheur qui ne
--  tire jamais — sans erreur, sans avertissement, et sans qu'aucune
--  requete ne le signale : `tete_id` reste simplement NULL partout.
--  Voir docs/pieges.md.
--
--  La garde tient donc bien son role : l'UPDATE que la fonction emet
--  ne porte que sur `tete_id`, et ne rentrerait de toute facon pas dans
--  un declencheur arme sur `UPDATE OF parent_id` ; si le jour vient ou
--  il le ferait, la profondeur vaudra 1 et la clause coupera.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION structure_recalculer_tete()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    WITH RECURSIVE sous_arbre AS (
        SELECT id FROM structure WHERE id = NEW.id
        UNION ALL
        SELECT s.id FROM structure s JOIN sous_arbre a ON s.parent_id = a.id
    )
    UPDATE structure
       SET tete_id = structure_tete_de(id)
     WHERE id IN (SELECT id FROM sous_arbre);
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS structure_tete_apres_ecriture ON structure;
CREATE TRIGGER structure_tete_apres_ecriture
    AFTER INSERT OR UPDATE OF parent_id ON structure
    FOR EACH ROW
    WHEN (pg_trigger_depth() = 0)
    EXECUTE FUNCTION structure_recalculer_tete();


-- ---------------------------------------------------------------------
--  6. Le poste qui dirige une structure.
--
--  La relance s'adresse a quelqu'un, et personne n'etait designe. Le
--  deviner par « son poste superieur est hors de sa structure » etait
--  vrai du semis et maintenu par rien : bien trop faible pour porter une
--  decision de relance.
--
--  Un seul responsable en vigueur par structure, tenu par un index unique
--  partiel — et partiel sur `valide_au IS NULL`, sans quoi le
--  predecesseur d'un chef de service interdirait la nomination de son
--  successeur.
-- ---------------------------------------------------------------------
ALTER TABLE poste ADD COLUMN IF NOT EXISTS est_responsable BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN poste.est_responsable IS
  'Le poste de tete de la structure : celui a qui la relance est adressee.';

CREATE UNIQUE INDEX IF NOT EXISTS poste_un_responsable_par_structure
    ON poste (structure_id) WHERE est_responsable AND valide_au IS NULL;


-- ---------------------------------------------------------------------
--  7. Les deux habilitations.
--
--  Aucun code de permission nouveau : DISPO repond a « quel geste », le
--  perimetre repond a « sur quelles donnees » (ADR 002). Un
--  `DISPO_DE_MA_TETE` aurait melange les deux questions dans un code.
--
--  RESP ne gagne PAS `REL` : la demande porte sur le **destinataire** de
--  la relance, pas sur son emetteur — relancer reste le geste de la DSR.
-- ---------------------------------------------------------------------
INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id FROM profil p, permission x
 WHERE (p.code = 'RESP' AND x.code = 'DISPO')
    OR (p.code = 'DG'   AND x.code = 'DISPO')
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------
--  8. Les deux regles sans source, posees en `hypothese` — A80 et A81.
--
--  1. Le Cabinet et les representations comptent-ils comme tetes ?
--
--     L'arbre dit oui — ce sont des enfants directs de la Direction
--     generale. Mais un tableau de bord qui aligne le Cabinet a cote de
--     la DAF suppose que l'institution les compare, et rien ne le dit.
--     Le parametre rend le choix visible et corrigible sans redeploiement.
--
--  2. Emettre la relance quand aucun poste de tete n'est pourvu ?
--
--     Une structure sans responsable en vigueur n'a pas de destinataire.
--     Emettre quand meme produirait une relance qui ne part nulle part et
--     que personne ne verra ; ne pas emettre fait disparaitre le retard du
--     tableau. `false` par defaut, parce qu'une relance fantome se compte
--     dans les statistiques d'escalade et fausse le niveau.
-- ---------------------------------------------------------------------
INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('organisation.tetes_incluent_cabinet_et_representations',
   'Le Cabinet et les representations comptent comme tetes de structure, au meme titre que les directions',
   'true', 'booleen', 'organisation', 'hypothese',
   NULL,
   'Direction generale — arbitrage a demander (voir A80)'),
  ('relance.emettre_sans_destinataire',
   'Emettre la relance meme quand aucun poste de tete n''est pourvu',
   'false', 'booleen', 'courrier', 'hypothese',
   NULL,
   'Division du Suivi et de la Relance (§3.3) — voir A81')
ON CONFLICT (cle) DO NOTHING;
