-- ---------------------------------------------------------------------
--  Les trois derniers gestes du pilier courrier : l'acceptation par
--  l'agent, le fil d'observations, le signalement d'ecart.
--
--  Une seule migration parce que les trois viennent du meme entretien
--  du 26 aout 2026, ou le Port a enfin decrit le trajet reel d'un
--  courrier arrive :
--
--      le bureau d'ordre central enregistre
--      -> le cabinet du Directeur general cote aux structures
--      -> le responsable de structure (ou son secretariat) affecte
--         a un ou plusieurs agents
--      -> l'agent traite
--      -> l'agent restitue au responsable, qui cloture.
--
--  **Ce trajet n'est pas un circuit, et rien ici ne peuple
--  `circuit_etape`.** Il ne comporte ni validation hierarchique, ni
--  signature, ni escalade automatique : c'est exactement la chaine
--  cotation -> cotation_structure -> affectation -> traitement que le
--  socle porte deja. La seule chose qui lui manquait est la **decharge**
--  — au Port, l'agent cote signe un cahier pour prouver qu'il a recu le
--  courrier. Voir ADR 034 et ADR 035.
--
--  Les delais restent fixes a la main, a la cotation puis a
--  l'affectation. Aucun delai standard par etape n'a ete communique, et
--  aucun n'est invente ici.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
--  1. L'affectation porte sa decharge.
--
--  Quatre colonnes plutot qu'une table : une affectation vaut pour un
--  agent et un seul, et sa decharge aussi. Une table `accuse_reception`
--  a part aurait ajoute une jointure a chaque lecture du dossier pour
--  n'y ranger qu'un fait par ligne mere.
--
--  `remis_par` et `reference_cahier` gardent la trace du **support
--  papier** : le cahier de decharge existe au Port et continue d'etre
--  tenu. Les deux sont facultatifs — un courrier remis en main propre
--  n'a pas de coursier, et une structure qui a cesse de tenir le cahier
--  ne doit pas etre empechee d'accuser a l'ecran.
--
--  Pas de colonne de refus. Le Port n'a pas decrit de refus d'un agent
--  cote (A70) : l'agent qui estime que le courrier ne le concerne pas
--  passe par le **signalement d'ecart**, dont c'est precisement l'un des
--  cinq types (DESTINATAIRE_ERRONE). Ouvrir deux voies pour le meme fait
--  aurait produit deux registres a reconcilier.
-- ---------------------------------------------------------------------
ALTER TABLE affectation ADD COLUMN IF NOT EXISTS accepte_le        TIMESTAMPTZ;
ALTER TABLE affectation ADD COLUMN IF NOT EXISTS accepte_par       BIGINT REFERENCES utilisateur(id);
ALTER TABLE affectation ADD COLUMN IF NOT EXISTS remis_par         TEXT;
ALTER TABLE affectation ADD COLUMN IF NOT EXISTS reference_cahier  TEXT;

COMMENT ON COLUMN affectation.accepte_le IS
  'Decharge : l''agent cote reconnait avoir recu le courrier. Aucun traitement n''est depose avant.';
COMMENT ON COLUMN affectation.accepte_par IS
  'Qui a signe la decharge. Normalement l''agent affecte lui-meme ; le point focal peut signer pour lui, et la colonne le dit.';
COMMENT ON COLUMN affectation.remis_par IS
  'Le coursier, ou le mode de remise. Trace du support papier — facultatif.';
COMMENT ON COLUMN affectation.reference_cahier IS
  'Page ou numero du cahier de decharge tenu par la structure — facultatif.';

-- Une decharge sans signataire ne prouve rien, un signataire sans date
-- ne se relit pas. Meme regle que `passage_accuse_complet`.
ALTER TABLE affectation DROP CONSTRAINT IF EXISTS affectation_acceptation_complete;
ALTER TABLE affectation ADD CONSTRAINT affectation_acceptation_complete
  CHECK ((accepte_le IS NULL) = (accepte_par IS NULL));

-- La liste « ce que je dois accuser » et la liste « ce qui n'est pas
-- revenu » sont les deux seules lectures frequentes de ces colonnes.
CREATE INDEX IF NOT EXISTS affectation_a_accuser
    ON affectation (utilisateur_id, affecte_le) WHERE accepte_le IS NULL AND retire_le IS NULL;


-- ---------------------------------------------------------------------
--  2. observation_courrier — le fil d'observations de la fiche.
--
--  `courrier.observations` existait deja, mais c'est une **zone de
--  saisie du formulaire d'enregistrement** : un seul texte, sans auteur
--  ni horodatage. La rendre comme un fil aurait attribue a l'agent de
--  session une observation qu'il n'a peut-etre pas ecrite.
--
--  **Aucune colonne de modification, aucune d'invalidation, et c'est la
--  regle elle-meme.** Le Port a tranche le 26 aout 2026 : tout lecteur
--  ecrit, tout lecteur lit, jamais modifiable. L'immuabilite est donc
--  posee par le schema plutot que par le service — un fil ou l'on
--  reecrit son propre message apres coup ne vaut pas comme trace.
--
--  Pas de `structure_id` : le fil est **commun a toutes les structures
--  cotees**, a la difference du journal (0018). C'est le sens de « tout
--  lecteur lit » — une observation qui ne sortirait pas de sa structure
--  ne serait pas un fil, mais cinq fils paralleles.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observation_courrier (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    auteur_id   BIGINT      NOT NULL REFERENCES utilisateur(id),
    texte       TEXT        NOT NULL,
    publie_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Un fil se lit ; une ligne vide ne se lit pas. La borne haute evite
    -- qu'un copier-coller de piece jointe passe pour une observation.
    CONSTRAINT observation_texte_non_vide
      CHECK (length(btrim(texte)) BETWEEN 1 AND 4000)
);

COMMENT ON TABLE observation_courrier IS
  'Fil d''observations d''un courrier — tout lecteur ecrit, tout lecteur lit, jamais modifiable.';

CREATE INDEX IF NOT EXISTS observation_courrier_fil
    ON observation_courrier (courrier_id, publie_le);


-- ---------------------------------------------------------------------
--  3. signalement_ecart — l'incident du circuit papier.
--
--  Pli incomplet, mal dirige, jamais recu, endommage, enregistre deux
--  fois. Sans registre, l'ecart se regle par telephone et le delai
--  continue de courir contre une structure qui n'a rien recu.
--
--  Le signalement **vise une structure** et non une personne :
--  l'emetteur choisit son destinataire (arbitrage du 26 aout 2026), et
--  c'est le responsable de cette structure qui le prend en charge. Une
--  personne nommee serait absente le jour ou l'ecart arrive.
--
--  Trois etats et deux seules transitions, dans un seul sens : ouvert ->
--  pris_en_compte -> clos. Rien ne revient en arriere — un ecart rouvert
--  est un nouvel ecart, sans quoi la duree de prise en charge se remet a
--  zero a chaque hesitation.
--
--  Les cinq types et les trois gravites sont ceux que l'ecran A-12
--  portait deja. Ils sont contraints ici plutot que laisses libres : un
--  type inconnu ne se voit qu'au moment de compter les ecarts par type,
--  c'est-a-dire six mois trop tard.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signalement_ecart (
    id                        BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id               BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    type_ecart                TEXT        NOT NULL,
    gravite                   TEXT        NOT NULL DEFAULT 'NOTABLE',
    description               TEXT        NOT NULL,
    destinataire_structure_id BIGINT      NOT NULL REFERENCES structure(id),
    -- La structure de l'emetteur au moment du signalement. Figee, parce
    -- qu'une mutation ne doit pas reecrire qui avait signale.
    emetteur_structure_id     BIGINT      REFERENCES structure(id),
    etat                      TEXT        NOT NULL DEFAULT 'ouvert',
    emis_le                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    emis_par                  BIGINT      NOT NULL REFERENCES utilisateur(id),
    pris_en_compte_le         TIMESTAMPTZ,
    pris_en_compte_par        BIGINT      REFERENCES utilisateur(id),
    clos_le                   TIMESTAMPTZ,
    clos_par                  BIGINT      REFERENCES utilisateur(id),
    -- Ce que la structure destinataire repond. Obligatoire a la
    -- cloture : un ecart clos sans un mot ne se distingue pas d'un ecart
    -- oublie.
    suite_donnee              TEXT,
    CONSTRAINT signalement_type_valide
      CHECK (type_ecart IN ('PIECE_MANQUANTE','PLI_ENDOMMAGE','DESTINATAIRE_ERRONE',
                            'PLI_NON_RECU','DOUBLON')),
    CONSTRAINT signalement_gravite_valide
      CHECK (gravite IN ('MINEURE','NOTABLE','BLOQUANTE')),
    CONSTRAINT signalement_etat_valide
      CHECK (etat IN ('ouvert','pris_en_compte','clos')),
    CONSTRAINT signalement_description_non_vide
      CHECK (length(btrim(description)) BETWEEN 10 AND 4000),
    CONSTRAINT signalement_prise_en_compte_complete
      CHECK ((pris_en_compte_le IS NULL) = (pris_en_compte_par IS NULL)),
    CONSTRAINT signalement_cloture_complete
      CHECK ((clos_le IS NULL) = (clos_par IS NULL)),
    -- L'etat et les horodatages disent la meme chose : ils ne peuvent
    -- pas se contredire. `clos` sans date de cloture, c'est un ecart que
    -- personne ne saura dater.
    CONSTRAINT signalement_etat_horodate
      CHECK ((etat = 'ouvert'         AND pris_en_compte_le IS NULL AND clos_le IS NULL)
          OR (etat = 'pris_en_compte' AND pris_en_compte_le IS NOT NULL AND clos_le IS NULL)
          OR (etat = 'clos'           AND clos_le IS NOT NULL AND suite_donnee IS NOT NULL))
);

COMMENT ON TABLE signalement_ecart IS
  'Ecart constate sur le circuit papier d''un courrier — A-12. Ouvert par tout lecteur, pris en charge par la structure visee.';

-- « Ce que ma structure doit traiter » est la lecture qui compte, et
-- elle porte sur ce qui n'est pas clos.
CREATE INDEX IF NOT EXISTS signalement_a_traiter
    ON signalement_ecart (destinataire_structure_id, emis_le DESC) WHERE etat <> 'clos';
CREATE INDEX IF NOT EXISTS signalement_courrier
    ON signalement_ecart (courrier_id, emis_le DESC);
CREATE INDEX IF NOT EXISTS signalement_emetteur
    ON signalement_ecart (emis_par, emis_le DESC);


-- ---------------------------------------------------------------------
--  4. Qui prend en charge un signalement ?
--
--  `AFF` — la permission d'affecter. Elle est ce qui, dans le socle,
--  designe le responsable d'une structure : c'est lui qui distribue le
--  courrier a ses agents, et le point focal la porte aussi (0018).
--
--  **C'est une hypothese** (A71) : aucun document ne dit qui traite un
--  ecart. Creer une permission dediee aurait fait pire — une permission
--  que personne ne porte, donc un registre que personne n'ouvre.
--
--  Aucune ligne de `profil_permission` n'est ajoutee ici : les profils
--  qui portent `AFF` la portent deja.
-- ---------------------------------------------------------------------
INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('courrier.acceptation_obligatoire',
   'Exiger la decharge de l''agent avant tout traitement',
   'true', 'booleen', 'courrier', 'acte',
   'Entretien client du 26 aout 2026 — « le port tient un cahier ou chaque agent cote signe »',
   NULL),
  -- Au-dela de ce delai, une decharge non signee passe de « en attente » a
  -- « non retourne » sur l'ecran A-11. **Hypothese** : le Port a decrit le
  -- cahier, jamais le moment ou son absence devient anormale (A73). Trois
  -- jours ouvres est le delai que l'ecran affichait deja par defaut.
  ('courrier.decharge_delai_alerte_jours',
   'Jours ouvres au-dela desquels une decharge manquante est signalee',
   '3', 'entier', 'courrier', 'hypothese', NULL,
   'Direction des services rattaches — au bout de combien de temps un pli non decharge est-il perdu ?')
ON CONFLICT (cle) DO NOTHING;
