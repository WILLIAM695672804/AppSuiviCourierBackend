-- ---------------------------------------------------------------------
--  Le pilier suivi : la corbeille de celui qui instruit.
--
--  Quatre objets, tous nes du meme constat : trois ecrans du front
--  appelaient huit adresses qui n'existaient pas. Le tableau de relance
--  a ete servi le 28 aout 2026 sans rien creer — il ne lit que des
--  tables existantes. Le reste du pilier demande du schema, parce qu'il
--  porte des gestes que rien ne portait :
--
--      la tache que l'agent se donne,
--      la note qu'il prend pour lui,
--      le delai qu'il demande a son responsable,
--      la recherche qu'il conserve.
--
--  **Aucun de ces quatre gestes n'est un circuit.** Ils n'engagent que
--  l'agent et, pour la demande de delai, son responsable. Rien ici ne
--  peuple `circuit_etape`, qui reste vide — ADR 034.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
--  1. tache_traitement — les etapes que l'agent se donne.
--
--  A ne pas confondre avec `tache`, qui pend a une activite et porte un
--  poids dans le calcul d'avancement. Celle-ci n'a **ni poids ni
--  echeance** : ce n'est pas un plan d'actions, c'est une liste de
--  courses. L'ecran le dit en toutes lettres — « ces etapes ne sont pas
--  le circuit du courrier : ce sont les taches que l'agent se donne.
--  Elles n'engagent que lui ».
--
--  D'ou `utilisateur_id` : la liste appartient a une personne sur un
--  courrier, et deux agents affectes au meme dossier tiennent deux
--  listes. Une liste partagee serait un circuit qui ne dit pas son nom.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tache_traitement (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id    BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    utilisateur_id BIGINT      NOT NULL REFERENCES utilisateur(id),
    libelle        TEXT        NOT NULL,
    -- Faite ou non : une seule colonne, et l'etat s'en deduit. Un booleen
    -- en plus de la date aurait permis « faite le 3, non faite ».
    faite_le       TIMESTAMPTZ,
    ordre          SMALLINT    NOT NULL DEFAULT 0,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT      REFERENCES utilisateur(id),
    invalide_le    TIMESTAMPTZ,
    invalide_par   BIGINT      REFERENCES utilisateur(id),
    CONSTRAINT tache_traitement_libelle_non_vide
      CHECK (length(btrim(libelle)) BETWEEN 1 AND 300)
);

COMMENT ON TABLE tache_traitement IS
  'Les etapes qu''un agent se donne sur un courrier — sa liste, pas le circuit.';

CREATE INDEX IF NOT EXISTS tache_traitement_liste
    ON tache_traitement (courrier_id, utilisateur_id, ordre, id)
    WHERE invalide_le IS NULL;


-- ---------------------------------------------------------------------
--  2. note_traitement — ce que l'agent note pour lui.
--
--  **Une table a part, et non un drapeau sur `observation_courrier`.**
--  Le Port a arbitre le 26 aout 2026 que le fil d'observations est
--  commun : « tout lecteur ecrit, tout lecteur lit, jamais modifiable ».
--  Y ajouter une colonne `privee` aurait defait cet arbitrage dans la
--  table meme qui le porte, et la premiere lecture qui aurait oublie le
--  filtre aurait montre a tous ce qu'un agent croyait garder.
--
--  Deux notions, deux tables : le fil est ce que le dossier retient, la
--  note est ce que l'agent se rappelle.
--
--  `privee` decide de qui lit : l'auteur et sa hierarchie, ou tout
--  lecteur du courrier. L'ecran C-01 n'ecrit aujourd'hui que des notes
--  privees — « Note privee · visible par ma hierarchie » — mais le
--  contrat front porte le drapeau, et une note de service partagee est
--  le meme geste avec un autre public.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS note_traitement (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    auteur_id   BIGINT      NOT NULL REFERENCES utilisateur(id),
    texte       TEXT        NOT NULL,
    privee      BOOLEAN     NOT NULL DEFAULT TRUE,
    publiee_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT note_traitement_texte_non_vide
      CHECK (length(btrim(texte)) BETWEEN 1 AND 4000)
);

COMMENT ON TABLE note_traitement IS
  'Note de traitement d''un agent sur un courrier — privee par defaut, jamais modifiable.';

CREATE INDEX IF NOT EXISTS note_traitement_fil
    ON note_traitement (courrier_id, publiee_le);


-- ---------------------------------------------------------------------
--  3. demande_delai — l'agent demande, le responsable accorde.
--
--  La prolongation existe deja (`services.prolonger`, sous les
--  permissions de cotation) : c'est le geste de **celui qui accorde**.
--  Il manquait celui de **celui qui demande** — un agent ne s'accorde
--  pas son propre delai, et sans cette table sa demande passait par le
--  telephone, ou elle ne laissait aucune trace.
--
--  L'etat n'est pas deduit : `en_attente` est un fait, et le responsable
--  qui ouvre sa liste doit pouvoir la trier sans recalculer.
--
--  Une seule demande en attente par courrier et par demandeur : redemander
--  n'est pas relancer, et deux demandes ouvertes feraient accorder deux
--  fois le meme report.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS demande_delai (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id    BIGINT      NOT NULL REFERENCES courrier(id) ON DELETE CASCADE,
    demandeur_id   BIGINT      NOT NULL REFERENCES utilisateur(id),
    jours_demandes SMALLINT    NOT NULL,
    motif          TEXT        NOT NULL,
    demandee_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    etat           TEXT        NOT NULL DEFAULT 'en_attente',
    decidee_le     TIMESTAMPTZ,
    decidee_par    BIGINT      REFERENCES utilisateur(id),
    -- Ce que le responsable repond. Obligatoire au refus : un refus sans
    -- un mot ne se distingue pas d'un oubli, et l'agent n'a rien a
    -- reprendre. Meme regle que la suite donnee d'un ecart.
    reponse        TEXT,
    CONSTRAINT demande_delai_jours_plausibles
      CHECK (jours_demandes BETWEEN 1 AND 90),
    CONSTRAINT demande_delai_motif_non_vide
      CHECK (length(btrim(motif)) BETWEEN 1 AND 2000),
    CONSTRAINT demande_delai_etat_valide
      CHECK (etat IN ('en_attente', 'accordee', 'refusee')),
    CONSTRAINT demande_delai_decision_datee
      CHECK ((etat = 'en_attente') = (decidee_le IS NULL))
);

COMMENT ON TABLE demande_delai IS
  'Demande de report d''echeance formee par l''agent — le responsable accorde ou refuse.';

CREATE UNIQUE INDEX IF NOT EXISTS demande_delai_une_seule_en_attente
    ON demande_delai (courrier_id, demandeur_id)
    WHERE etat = 'en_attente';


-- ---------------------------------------------------------------------
--  4. recherche_enregistree — la question qu'on repose chaque semaine.
--
--  Les criteres en `jsonb` et non en colonnes : ce sont ceux de l'ecran
--  A-14, et l'ecran en gagnera. Une colonne par critere aurait demande
--  une migration a chaque champ ajoute au formulaire, pour une donnee
--  que personne n'interroge — on la relit en bloc, on ne cherche jamais
--  « les recherches qui portent sur la DAF ».
--
--  `ON DELETE CASCADE` sur l'utilisateur : une recherche enregistree
--  n'est pas une trace, c'est un confort. Elle disparait avec le compte,
--  contrairement a tout le reste du pilier.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS recherche_enregistree (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id BIGINT      NOT NULL REFERENCES utilisateur(id) ON DELETE CASCADE,
    libelle        TEXT        NOT NULL,
    criteres       JSONB       NOT NULL,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT recherche_libelle_non_vide
      CHECK (length(btrim(libelle)) BETWEEN 1 AND 120),
    CONSTRAINT recherche_libelle_unique_par_agent
      UNIQUE (utilisateur_id, libelle)
);

COMMENT ON TABLE recherche_enregistree IS
  'Criteres de recherche conserves par un agent — un confort, pas une trace.';
