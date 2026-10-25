-- ---------------------------------------------------------------------
--  Le bureau d'ordre de structure, le cloisonnement des instructions
--  internes, et le routage direct.
--
--  Trois manques constates sur le module Courrier, et une seule
--  migration parce qu'ils tiennent au meme fait : jusqu'ici, un courrier
--  entrait dans une structure sans que rien ne l'inscrive, et en
--  ressortait sans que rien ne le dise. Faute de cette entree et de
--  cette sortie, ni la structure ne tenait son registre, ni la DSR ne
--  savait ou le courrier attendait, ni le cloisonnement n'avait de
--  frontiere ou se poser.
--
--  Le bureau d'ordre d'une structure, au Port, c'est son point focal.
--  Le profil existait deja (POINT_FOCAL) mais ne portait aucune
--  permission du domaine courrier : il alimentait les activites et la
--  disponibilite, rien d'autre.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
--  1. L'evenement dit desormais DANS QUELLE STRUCTURE il s'est produit.
--
--  Sans cette colonne, `fiche_de_vie()` rendait a toute structure cotee
--  la totalite du journal du courrier — donc les instructions internes
--  de sa voisine. Le filtre n'avait aucune frontiere sur laquelle
--  s'appuyer : l'auteur d'un evenement ne dit pas au nom de quelle
--  structure il agit, un agent de la DSR pouvant ecrire dans le dossier
--  d'une direction sans y etre rattache.
--
--  NULL signifie **jalon public** : enregistre, cote, entre, sorti,
--  cloture. C'est ce que toute structure cotee a le droit de lire, et
--  c'est la valeur par defaut — un evenement qu'on oublie de qualifier
--  reste donc visible, jamais fuit-il davantage qu'avant.
--
--  Pas de REFERENCE : aucune colonne de `evenement` n'en porte
--  (`acteur_id`, `agit_pour_id` sont de simples BIGINT). Le journal ne
--  doit jamais refuser une ecriture parce qu'une ligne de reference a
--  bouge — RNF-TRACE-01 veut la trace, pas l'integrite referentielle.
-- ---------------------------------------------------------------------
ALTER TABLE evenement ADD COLUMN IF NOT EXISTS structure_id BIGINT;

COMMENT ON COLUMN evenement.structure_id IS
  'Structure a l''interieur de laquelle le geste a eu lieu. NULL = jalon public, lisible par toute structure cotee.';

CREATE INDEX IF NOT EXISTS evenement_structure
    ON evenement (courrier_id, structure_id, survenu_le);


-- ---------------------------------------------------------------------
--  2. passage_structure — le registre d'entree et de sortie du bureau
--     d'ordre de la structure.
--
--  Une ligne par (courrier, structure cotee). L'entree n'est pas saisie
--  par quelqu'un : elle est **posee par le declencheur** au moment ou la
--  cotation nomme la structure. C'est la seule facon d'obtenir une date
--  d'entree qui ne depende pas de la diligence du point focal — sans
--  quoi le temps passe dans une structure se mesurerait a partir du
--  moment ou elle a bien voulu le reconnaitre.
--
--  L'accuse de reception est distinct de l'entree, et c'est tout
--  l'interet : l'ecart entre `entre_le` et `accuse_le` est le temps mort
--  du bureau d'ordre, celui que personne ne voyait.
--
--  Deux cotations successives vers la meme structure font deux
--  passages : un courrier renvoye a la DAF y entre une seconde fois.
--  L'unicite porte donc sur `cotation_structure_id`, jamais sur le
--  couple (courrier, structure).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS passage_structure (
    id                    BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id           BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    structure_id          BIGINT      NOT NULL REFERENCES structure(id),
    cotation_structure_id BIGINT      NOT NULL UNIQUE
                                      REFERENCES cotation_structure(id) ON DELETE CASCADE,
    entre_le              TIMESTAMPTZ NOT NULL DEFAULT now(),
    accuse_le             TIMESTAMPTZ,
    accuse_par            BIGINT      REFERENCES utilisateur(id),
    sorti_le              TIMESTAMPTZ,
    sorti_par             BIGINT      REFERENCES utilisateur(id),
    motif_sortie          TEXT,
    note_sortie           TEXT,
    -- Un accuse sans son auteur ne prouve rien, et un auteur sans date
    -- ne se relit pas. Les deux vont ensemble ou aucun.
    CONSTRAINT passage_accuse_complet
      CHECK ((accuse_le IS NULL) = (accuse_par IS NULL)),
    CONSTRAINT passage_sortie_complete
      CHECK ((sorti_le IS NULL) = (sorti_par IS NULL)),
    -- Une sortie dit toujours par ou : c'est ce qui distingue « la
    -- reponse est partie » de « on nous l'a repris ».
    CONSTRAINT passage_sortie_motivee
      CHECK (sorti_le IS NULL OR motif_sortie IS NOT NULL),
    CONSTRAINT passage_motif_valide
      CHECK (motif_sortie IS NULL
             OR motif_sortie IN ('reponse','retour','transmission','cloture','autre')),
    CONSTRAINT passage_sortie_apres_entree
      CHECK (sorti_le IS NULL OR sorti_le >= entre_le)
);

COMMENT ON TABLE passage_structure IS
  'Registre d''entree et de sortie du bureau d''ordre d''une structure — tenu par son point focal.';

-- L'ecran du bureau d'ordre lit « ce qui est chez moi » : la structure,
-- puis l'ordre d'arrivee. L'index partiel sert la file d'attente, qui
-- est la seule liste consultee plusieurs fois par jour.
CREATE INDEX IF NOT EXISTS passage_structure_registre
    ON passage_structure (structure_id, entre_le DESC);
CREATE INDEX IF NOT EXISTS passage_structure_en_cours
    ON passage_structure (structure_id, entre_le) WHERE sorti_le IS NULL;
CREATE INDEX IF NOT EXISTS passage_structure_courrier
    ON passage_structure (courrier_id, entre_le);


-- ---------------------------------------------------------------------
--  L'entree se pose toute seule.
--
--  AFTER INSERT plutot que BEFORE : la ligne de `cotation_structure`
--  doit exister pour etre referencee. Et un seul sens — il n'existe pas
--  de declencheur de sortie, parce qu'une sortie est un acte du bureau
--  d'ordre, pas une consequence mecanique.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION passage_structure_entree() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO passage_structure (courrier_id, structure_id, cotation_structure_id)
    SELECT c.courrier_id, NEW.structure_id, NEW.id
      FROM cotation c
     WHERE c.id = NEW.cotation_id
    ON CONFLICT (cotation_structure_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cotation_structure_passage ON cotation_structure;
CREATE TRIGGER cotation_structure_passage
    AFTER INSERT ON cotation_structure
    FOR EACH ROW EXECUTE FUNCTION passage_structure_entree();

-- Rattrapage des cotations deja en base : sans lui, tout courrier cote
-- avant cette migration serait absent du registre de sa structure, et
-- le bureau d'ordre s'ouvrirait sur une liste vide le premier jour.
INSERT INTO passage_structure (courrier_id, structure_id, cotation_structure_id, entre_le)
SELECT c.courrier_id, cs.structure_id, cs.id, c.decide_le
  FROM cotation_structure cs
  JOIN cotation c ON c.id = cs.cotation_id
ON CONFLICT (cotation_structure_id) DO NOTHING;


-- ---------------------------------------------------------------------
--  3. Le routage direct.
--
--  « Les factures vont directement chez le DFC, sans passer par le DG. »
--  C'est une regle de cotation d'office, et non un circuit : elle ne
--  decrit aucun trajet de validation, elle dit vers qui le courrier part
--  des l'enregistrement.
--
--  D'ou une table a elle plutot qu'un usage de `circuit_regle` :
--  `circuit_regle` designe un circuit, et les circuits sont ancres sur
--  `circuit_etape`, qui est vide faute d'avoir jamais recu le trajet
--  reel du Port (A24). Y brancher le routage direct aurait fait dependre
--  une regle connue d'une regle qui ne l'est pas.
--
--  La selection : la regle **la plus specifique** l'emporte, la
--  specificite se comptant en criteres renseignes. A specificite egale,
--  `priorite` croissante tranche. Une regle sans aucun critere coterait
--  tout le courrier du Port a une seule structure : le CHECK l'interdit.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regle_routage (
    id               BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             TEXT        NOT NULL UNIQUE,
    libelle          TEXT        NOT NULL,
    nature_id        BIGINT      REFERENCES nature(id),
    sens             TEXT,
    correspondant_id BIGINT      REFERENCES correspondant(id),
    -- La structure cotee d'office, et la mention portee sur la cotation.
    structure_id     BIGINT      NOT NULL REFERENCES structure(id),
    mention_type_id  BIGINT      REFERENCES mention_type(id),
    priorite         SMALLINT    NOT NULL DEFAULT 100,
    actif            BOOLEAN     NOT NULL DEFAULT true,
    -- Meme distinction que dans `parametre` : une regle inventee par la
    -- conception ne se confond pas avec une regle transmise par le Port.
    statut           TEXT        NOT NULL DEFAULT 'hypothese',
    source           TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par         BIGINT,
    modifie_le       TIMESTAMPTZ,
    modifie_par      BIGINT,
    invalide_le      TIMESTAMPTZ,
    invalide_par     BIGINT,
    CONSTRAINT regle_routage_sens_valide
      CHECK (sens IS NULL OR sens IN ('arrive','depart','interne')),
    CONSTRAINT regle_routage_statut_valide
      CHECK (statut IN ('acte','hypothese')),
    CONSTRAINT regle_routage_a_un_critere
      CHECK (nature_id IS NOT NULL OR correspondant_id IS NOT NULL)
);

COMMENT ON TABLE regle_routage IS
  'Cotation d''office a l''enregistrement — ex. une facture arrivee part au DFC sans passer par le DG.';

CREATE INDEX IF NOT EXISTS regle_routage_selection
    ON regle_routage (priorite) WHERE actif AND invalide_le IS NULL;


-- La nature manquante. Sans elle, aucune facture n'est enregistrable en
-- tant que telle, et la regle de routage n'a rien a reconnaitre.
-- Delai de 30 jours : c'est celui du RAPPORT, faute de source propre.
INSERT INTO nature (code, libelle, delai_defaut_jours) VALUES
  ('FACTURE', 'Facture', 30)
ON CONFLICT (code) DO NOTHING;

-- La regle d'exemple, **hypothese**. Le principe vient du client (« les
-- factures vont directement chez le DFC ») ; le sigle exact de la
-- structure d'arrivee, lui, n'a pas ete confirme, et rien ne dit si les
-- factures de depart suivent la meme voie. A69.
--
-- Le SELECT ne pose la regle que si la structure existe : l'organigramme
-- se charge par un geste d'exploitation, pas par une migration
-- (ADR 025), et une base fraiche n'a pas encore de DFC.
INSERT INTO regle_routage (code, libelle, nature_id, sens, structure_id,
                           mention_type_id, priorite, statut, source)
SELECT 'FACTURE_DFC',
       'Facture arrivée — cotation d''office à la DFC',
       n.id, 'arrive', s.id, m.id, 10, 'hypothese',
       'Entretien client — « les factures vont directement chez le DFC »'
  FROM structure s
  JOIN nature n ON n.code = 'FACTURE'
  LEFT JOIN mention_type m ON m.code = 'SUITE'
 WHERE s.code = 'DFC'
ON CONFLICT (code) DO NOTHING;

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('courrier.routage_direct_actif',
   'Appliquer les regles de routage direct a l''enregistrement',
   'true', 'booleen', 'courrier', 'hypothese',
   NULL,
   'Direction generale — le bureau d''ordre central cote-t-il d''office ?')
ON CONFLICT (cle) DO NOTHING;


-- ---------------------------------------------------------------------
--  4. Le point focal devient le bureau d'ordre de sa structure.
--
--  `BO_STR` couvre les deux gestes du registre : accuser reception d'une
--  entree, et prononcer une sortie. `AFF` lui permet de distribuer a
--  l'interieur — un bureau d'ordre qui recoit sans pouvoir remettre au
--  collaborateur n'a de bureau d'ordre que le nom.
--
--  Pas de `COT` : distribuer dans sa structure n'est pas coter vers une
--  autre. Pas de `CONF` : le secret ne s'ouvre pas par la fonction.
-- ---------------------------------------------------------------------
INSERT INTO permission (code, libelle, domaine) VALUES
  ('BO_STR', 'Tenir le bureau d''ordre de sa structure', 'courrier')
ON CONFLICT (code) DO NOTHING;

INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id FROM profil p, permission x
 WHERE p.code = 'POINT_FOCAL' AND x.code IN ('BO_STR', 'AFF')
ON CONFLICT DO NOTHING;

-- Le responsable de structure tient aussi ce registre : dans les
-- structures ou aucun point focal n'est designe, sans cette ligne le
-- bureau d'ordre n'aurait personne pour l'ouvrir.
INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id FROM profil p, permission x
 WHERE p.code IN ('RESP', 'DSR') AND x.code = 'BO_STR'
ON CONFLICT DO NOTHING;
