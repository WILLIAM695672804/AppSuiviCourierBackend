-- =====================================================================
--  Application de suivi des courriers et des activites
--  Script de creation de la base - premier livrable
--  PostgreSQL 16 ou superieur
--
--  Version 2 - 4 aout 2026
--  Conforme au document MODELE DE DONNEES v2
--
--  Ordre d'execution : ce fichier cree les tables dans l'ordre des
--  dependances, puis les cles etrangeres differees, puis les index,
--  les declencheurs et enfin les donnees initiales.
-- =====================================================================



-- ---------------------------------------------------------------------
--  0. Extensions
-- ---------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid, digest
CREATE EXTENSION IF NOT EXISTS btree_gist;    -- contrainte d'exclusion
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- recherche approximative
CREATE EXTENSION IF NOT EXISTS unaccent;      -- recherche sans accents

-- Configuration de recherche plein texte insensible aux accents.
DROP TEXT SEARCH CONFIGURATION IF EXISTS fr_unaccent;
CREATE TEXT SEARCH CONFIGURATION fr_unaccent (COPY = french);
ALTER TEXT SEARCH CONFIGURATION fr_unaccent
  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;


-- =====================================================================
--  1. DOMAINE ORGANISATION
-- =====================================================================

-- ---------------------------------------------------------------------
--  niveau_hierarchique
--  Les niveaux ne sont pas figes : l'administrateur en cree et en
--  supprime. Le nombre d'etapes de cotation et de validation en decoule.
-- ---------------------------------------------------------------------
CREATE TABLE niveau_hierarchique (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          TEXT        NOT NULL UNIQUE,
    libelle       TEXT        NOT NULL,
    rang          SMALLINT    NOT NULL,               -- 1 = sommet
    actif         BOOLEAN     NOT NULL DEFAULT true,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT,
    CONSTRAINT niveau_rang_positif CHECK (rang > 0)
);
CREATE UNIQUE INDEX niveau_rang_unique
    ON niveau_hierarchique (rang) WHERE invalide_le IS NULL;

COMMENT ON TABLE niveau_hierarchique IS
  'Niveaux de l''organigramme. Administrables : aucun niveau n''est ecrit dans le code.';

-- ---------------------------------------------------------------------
--  structure
--  Versionnee dans le temps : apres une reorganisation, une cotation
--  ancienne doit rester lisible telle qu'elle etait.
-- ---------------------------------------------------------------------
CREATE TABLE structure (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid                     UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    code                    TEXT        NOT NULL,
    libelle                 TEXT        NOT NULL,
    parent_id               BIGINT      REFERENCES structure(id),
    niveau_hierarchique_id  BIGINT      NOT NULL REFERENCES niveau_hierarchique(id),
    -- Ce qu'est la structure en droit, et non dans l'organigramme. Une filiale
    -- et une succursale ont leurs propres organes de gestion, dont la DSR suit
    -- les sessions et les prescriptions (descriptif fonctionnel, §3.3).
    nature                  TEXT        NOT NULL DEFAULT 'Direction',
    valide_du               DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au               DATE,
    cree_le                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par                BIGINT,
    modifie_le              TIMESTAMPTZ,
    modifie_par             BIGINT,
    invalide_le             TIMESTAMPTZ,
    invalide_par            BIGINT,
    CONSTRAINT structure_periode_valide CHECK (valide_au IS NULL OR valide_au >= valide_du),
    CONSTRAINT structure_pas_son_propre_parent CHECK (parent_id IS DISTINCT FROM id),
    CONSTRAINT structure_nature_valide
      CHECK (nature IN ('Direction','Service','Division','Filiale','Succursale'))
);
CREATE INDEX structure_parent      ON structure (parent_id);
CREATE INDEX structure_en_vigueur  ON structure (code) WHERE valide_au IS NULL;

COMMENT ON COLUMN structure.valide_au IS
  'NULL = ligne en vigueur. Une structure n''est jamais modifiee : on clot la ligne et on en insere une nouvelle.';

-- ---------------------------------------------------------------------
--  poste
--  Le poste porte la hierarchie, pas l'agent : la remontee au niveau
--  superieur reste juste quand l'occupant change.
-- ---------------------------------------------------------------------
CREATE TABLE poste (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    structure_id            BIGINT      NOT NULL REFERENCES structure(id),
    libelle                 TEXT        NOT NULL,
    niveau_hierarchique_id  BIGINT      NOT NULL REFERENCES niveau_hierarchique(id),
    poste_superieur_id      BIGINT      REFERENCES poste(id),
    valide_du               DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au               DATE,
    cree_le                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par                BIGINT,
    modifie_le              TIMESTAMPTZ,
    modifie_par             BIGINT,
    invalide_le             TIMESTAMPTZ,
    invalide_par            BIGINT
);
CREATE INDEX poste_structure ON poste (structure_id) WHERE valide_au IS NULL;
CREATE INDEX poste_superieur ON poste (poste_superieur_id);

-- ---------------------------------------------------------------------
--  utilisateur
--  Comptes crees dans l'application, authentification deleguee a
--  l'annuaire. Aucun mot de passe n'est stocke.
-- ---------------------------------------------------------------------
CREATE TABLE utilisateur (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid                   UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    identifiant_annuaire  TEXT        UNIQUE,           -- clef de rapprochement SSO
    matricule             TEXT        UNIQUE,
    nom                   TEXT        NOT NULL,
    prenom                TEXT        NOT NULL,
    courriel              TEXT        UNIQUE,
    telephone             TEXT,
    poste_id              BIGINT      REFERENCES poste(id),
    structure_id          BIGINT      REFERENCES structure(id),
    actif                 BOOLEAN     NOT NULL DEFAULT true,
    derniere_connexion    TIMESTAMPTZ,
    cree_le               TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par              BIGINT,
    modifie_le            TIMESTAMPTZ,
    modifie_par           BIGINT,
    invalide_le           TIMESTAMPTZ,
    invalide_par          BIGINT
);
CREATE INDEX utilisateur_structure ON utilisateur (structure_id) WHERE actif;
CREATE INDEX utilisateur_nom       ON utilisateur (nom, prenom);

-- ---------------------------------------------------------------------
--  session
--  Les quatre sessions d'enregistrement exigees par le cahier des
--  charges. lit_toutes_sessions n'est vrai que pour le confidentiel.
-- ---------------------------------------------------------------------
CREATE TABLE session (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                 TEXT        NOT NULL UNIQUE,
    libelle              TEXT        NOT NULL,
    sens                 TEXT        NOT NULL,
    lit_toutes_sessions  BOOLEAN     NOT NULL DEFAULT false,
    actif                BOOLEAN     NOT NULL DEFAULT true,
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par             BIGINT,
    modifie_le           TIMESTAMPTZ,
    modifie_par          BIGINT,
    invalide_le          TIMESTAMPTZ,
    invalide_par         BIGINT,
    CONSTRAINT session_code_valide CHECK (code IN ('arrive','depart','interne','confidentiel')),
    CONSTRAINT session_sens_valide CHECK (sens IN ('arrive','depart','interne'))
);

COMMENT ON COLUMN session.lit_toutes_sessions IS
  'Droit de lecture sur les autres sessions. Porte en donnee et non en code, pour pouvoir etre retire sans developpement.';

-- ---------------------------------------------------------------------
--  utilisateur_session
--  Rattachement EXCLUSIF : un agent n'appartient qu'a une session.
--  La contrainte est posee au niveau du moteur, non dans le code.
-- ---------------------------------------------------------------------
CREATE TABLE utilisateur_session (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id  BIGINT      NOT NULL REFERENCES utilisateur(id),
    session_id      BIGINT      NOT NULL REFERENCES session(id),
    attribue_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    attribue_par    BIGINT,
    retire_le       TIMESTAMPTZ,
    retire_par      BIGINT,
    CONSTRAINT une_seule_session_active
      EXCLUDE USING gist (utilisateur_id WITH =) WHERE (retire_le IS NULL)
);
CREATE INDEX utilisateur_session_actif
    ON utilisateur_session (session_id) WHERE retire_le IS NULL;


-- =====================================================================
--  2. DOMAINE SECURITE
-- =====================================================================

CREATE TABLE profil (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          TEXT        NOT NULL UNIQUE,
    libelle       TEXT        NOT NULL,
    description   TEXT,
    systeme       BOOLEAN     NOT NULL DEFAULT false,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT
);
COMMENT ON COLUMN profil.systeme IS
  'Profils initiaux, non supprimables. L''administrateur en cree d''autres librement.';

CREATE TABLE permission (
    id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code     TEXT NOT NULL UNIQUE,
    libelle  TEXT NOT NULL,
    domaine  TEXT NOT NULL,
    -- Un domaine par pilier du descriptif fonctionnel des utilisateurs.
    CONSTRAINT permission_domaine_valide
      CHECK (domaine IN ('courrier','activite','gouvernance','performance',
                         'dossier','archivage','exploitation','externe',
                         'administration'))
);

CREATE TABLE profil_permission (
    profil_id      BIGINT NOT NULL REFERENCES profil(id) ON DELETE CASCADE,
    permission_id  BIGINT NOT NULL REFERENCES permission(id),
    PRIMARY KEY (profil_id, permission_id)
);

CREATE TABLE utilisateur_profil (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id  BIGINT      NOT NULL REFERENCES utilisateur(id),
    profil_id       BIGINT      NOT NULL REFERENCES profil(id),
    attribue_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    attribue_par    BIGINT,
    retire_le       TIMESTAMPTZ,
    retire_par      BIGINT
);
CREATE INDEX utilisateur_profil_actif
    ON utilisateur_profil (utilisateur_id) WHERE retire_le IS NULL;

COMMENT ON TABLE utilisateur_profil IS
  'Attribution datee : permet de repondre a "quels droits avait cet agent le 12 mars ?".';

-- ---------------------------------------------------------------------
--  perimetre
--  Second axe d'habilitation, independant des permissions.
--  Les permissions disent QUOI, le perimetre dit SUR QUELLES DONNEES.
-- ---------------------------------------------------------------------
CREATE TABLE perimetre (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id  BIGINT      NOT NULL REFERENCES utilisateur(id),
    structure_id    BIGINT      REFERENCES structure(id),
    portee          TEXT        NOT NULL,
    valide_du       DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au       DATE,
    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par        BIGINT,
    CONSTRAINT perimetre_portee_valide
      CHECK (portee IN ('propre','structure','sous_arbre','toutes')),
    CONSTRAINT perimetre_structure_requise
      CHECK (portee = 'toutes' OR structure_id IS NOT NULL)
);
CREATE INDEX perimetre_utilisateur
    ON perimetre (utilisateur_id) WHERE valide_au IS NULL;

CREATE TABLE delegation (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nature                 TEXT        NOT NULL,
    titulaire_id           BIGINT      NOT NULL REFERENCES utilisateur(id),
    beneficiaire_id        BIGINT      NOT NULL REFERENCES utilisateur(id),
    debut                  TIMESTAMPTZ NOT NULL,
    fin                    TIMESTAMPTZ NOT NULL,
    perimetre_structure_id BIGINT      REFERENCES structure(id),
    motif                  TEXT,
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par               BIGINT,
    invalide_le            TIMESTAMPTZ,
    invalide_par           BIGINT,
    CONSTRAINT delegation_nature_valide CHECK (nature IN ('remplacement','delegation')),
    CONSTRAINT delegation_periode       CHECK (fin > debut),
    CONSTRAINT delegation_pas_soi_meme  CHECK (titulaire_id <> beneficiaire_id)
);
CREATE INDEX delegation_beneficiaire ON delegation (beneficiaire_id, debut, fin);

CREATE TABLE delegation_permission (
    delegation_id  BIGINT NOT NULL REFERENCES delegation(id) ON DELETE CASCADE,
    permission_id  BIGINT NOT NULL REFERENCES permission(id),
    PRIMARY KEY (delegation_id, permission_id)
);


-- =====================================================================
--  3. REFERENTIELS
-- =====================================================================

CREATE TABLE correspondant (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type           TEXT        NOT NULL,
    raison_sociale TEXT,
    nom            TEXT,
    prenom         TEXT,
    adresse        TEXT,
    ville          TEXT,
    courriel       TEXT,
    telephone      TEXT,
    structure_id   BIGINT      REFERENCES structure(id),
    actif          BOOLEAN     NOT NULL DEFAULT true,
    recherche      TSVECTOR,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    invalide_le    TIMESTAMPTZ,
    invalide_par   BIGINT,
    CONSTRAINT correspondant_type_valide
      CHECK (type IN ('externe','interne','usager','administration')),
    CONSTRAINT correspondant_identite
      CHECK (raison_sociale IS NOT NULL OR nom IS NOT NULL)
);
CREATE INDEX correspondant_recherche ON correspondant USING GIN (recherche);

CREATE TABLE nature (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                TEXT        NOT NULL UNIQUE,
    libelle             TEXT        NOT NULL,
    delai_defaut_jours  SMALLINT,
    actif               BOOLEAN     NOT NULL DEFAULT true,
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par            BIGINT,
    modifie_le          TIMESTAMPTZ,
    modifie_par         BIGINT,
    invalide_le         TIMESTAMPTZ,
    invalide_par        BIGINT
);

CREATE TABLE mention_type (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          TEXT        NOT NULL UNIQUE,
    libelle       TEXT        NOT NULL,
    ordre         SMALLINT    NOT NULL DEFAULT 0,
    actif         BOOLEAN     NOT NULL DEFAULT true,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT
);
COMMENT ON TABLE mention_type IS
  'Mentions portees a la cotation. A 500 courriers par jour, la saisie libre ne tient pas.';

CREATE TABLE priorite (
    id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code     TEXT     NOT NULL UNIQUE,
    libelle  TEXT     NOT NULL,
    rang     SMALLINT NOT NULL,
    couleur  TEXT,
    actif    BOOLEAN  NOT NULL DEFAULT true
);

-- ---------------------------------------------------------------------
--  sequence_numerotation
--  Compteur annuel par session, remis a zero au 1er janvier.
--  L'attribution se fait par UPDATE ... RETURNING dans la transaction
--  d'enregistrement : le verrou de ligne empeche deux agents d'obtenir
--  le meme numero.
-- ---------------------------------------------------------------------
CREATE TABLE sequence_numerotation (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      BIGINT   NOT NULL REFERENCES session(id),
    annee           SMALLINT NOT NULL,
    dernier_numero  INTEGER  NOT NULL DEFAULT 0,
    UNIQUE (session_id, annee)
);

CREATE TABLE jour_ferie (
    date_ferie DATE PRIMARY KEY,
    libelle    TEXT NOT NULL
);
COMMENT ON TABLE jour_ferie IS
  'Indispensable au calcul en jours ouvres. N''existe dans aucun document source : a administrer.';


-- =====================================================================
--  4. DOMAINE CIRCUIT
--  Le modele d'un circuit et son deroulement pour un courrier donne
--  sont deux choses distinctes. Les confondre est l'erreur classique.
-- =====================================================================

CREATE TABLE circuit (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          TEXT        NOT NULL UNIQUE,
    libelle       TEXT        NOT NULL,
    actif         BOOLEAN     NOT NULL DEFAULT true,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT
);

CREATE TABLE circuit_version (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    circuit_id          BIGINT      NOT NULL REFERENCES circuit(id),
    version             SMALLINT    NOT NULL,
    mode_cotation       TEXT        NOT NULL DEFAULT 'cascade',
    niveau_max_id       BIGINT      REFERENCES niveau_hierarchique(id),
    definition_bpmn     XML,
    publie_le           TIMESTAMPTZ,
    publie_par          BIGINT,
    motif_modification  TEXT,
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par            BIGINT,
    UNIQUE (circuit_id, version),
    CONSTRAINT circuit_mode_valide CHECK (mode_cotation IN ('directe','cascade'))
);
COMMENT ON COLUMN circuit_version.mode_cotation IS
  'directe = le DG cote a la structure qui traite. cascade = la cotation descend niveau par niveau.';

CREATE TABLE circuit_etape (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    circuit_version_id     BIGINT   NOT NULL REFERENCES circuit_version(id) ON DELETE CASCADE,
    rang                   SMALLINT NOT NULL,
    libelle                TEXT     NOT NULL,
    poste_id               BIGINT   REFERENCES poste(id),
    profil_id              BIGINT   REFERENCES profil(id),
    permission_requise_id  BIGINT   REFERENCES permission(id),
    delai_jours            SMALLINT,
    bloquante              BOOLEAN  NOT NULL DEFAULT true,
    condition_regle        JSONB,
    escalade_vers_poste_id BIGINT   REFERENCES poste(id),
    UNIQUE (circuit_version_id, rang)
);

-- ---------------------------------------------------------------------
--  circuit_regle
--  Selection du circuit applicable. La regle la plus specifique
--  l'emporte, la priorite departageant les cas restants. Permet
--  d'ecrire "cascade partout, sauf l'inspection en direct".
-- ---------------------------------------------------------------------
CREATE TABLE circuit_regle (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    circuit_id    BIGINT      NOT NULL REFERENCES circuit(id),
    structure_id  BIGINT      REFERENCES structure(id),
    nature_id     BIGINT      REFERENCES nature(id),
    sens          TEXT,
    confidentiel  BOOLEAN,
    priorite      SMALLINT    NOT NULL DEFAULT 100,
    actif         BOOLEAN     NOT NULL DEFAULT true,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    CONSTRAINT circuit_regle_sens_valide
      CHECK (sens IS NULL OR sens IN ('arrive','depart','interne'))
);
CREATE INDEX circuit_regle_selection
    ON circuit_regle (priorite) WHERE actif;


-- =====================================================================
--  5. DOMAINE COURRIER
-- =====================================================================

-- ---------------------------------------------------------------------
--  courrier
--  Le sens et la confidentialite sont DEUX colonnes distinctes :
--  un courrier confidentiel entrant est a la fois arrive et confidentiel.
-- ---------------------------------------------------------------------
CREATE TABLE courrier (
    id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid                       UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    numero                    TEXT        NOT NULL,
    numero_origine            TEXT,
    sens                      TEXT        NOT NULL,
    confidentiel              BOOLEAN     NOT NULL DEFAULT false,
    session_id                BIGINT      NOT NULL REFERENCES session(id),
    nature_id                 BIGINT      REFERENCES nature(id),
    date_courrier             DATE        NOT NULL,
    date_reception            DATE        NOT NULL DEFAULT CURRENT_DATE,
    expediteur_id             BIGINT      REFERENCES correspondant(id),
    expediteur_libelle        TEXT        NOT NULL,
    destinataire_id           BIGINT      REFERENCES correspondant(id),
    destinataire_libelle      TEXT,
    objet                     TEXT        NOT NULL,
    structure_chef_file_id    BIGINT      REFERENCES structure(id),
    original_papier_recu      BOOLEAN     NOT NULL DEFAULT false,
    observations              TEXT,
    priorite_id               BIGINT      REFERENCES priorite(id),
    nombre_pieces             SMALLINT    NOT NULL DEFAULT 0,
    statut_courrier           TEXT        NOT NULL DEFAULT 'cree',
    statut_reponse            TEXT        NOT NULL DEFAULT 'non_engagee',
    delai_reglementaire_jours SMALLINT,
    date_limite               DATE,
    courrier_lie_id           BIGINT      REFERENCES courrier(id),
    date_signature            DATE,                    -- signature manuscrite constatee
    cloture_le                TIMESTAMPTZ,
    cloture_par               BIGINT      REFERENCES utilisateur(id),
    motif_cloture             TEXT,
    recherche                 TSVECTOR,
    cree_le                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par                  BIGINT,
    modifie_le                TIMESTAMPTZ,
    modifie_par               BIGINT,
    invalide_le               TIMESTAMPTZ,
    invalide_par              BIGINT,
    CONSTRAINT courrier_sens_valide
      CHECK (sens IN ('arrive','depart','interne')),
    CONSTRAINT courrier_statut_valide
      CHECK (statut_courrier IN ('cree','en_cours','traite','cloture')),
    CONSTRAINT courrier_statut_reponse_valide
      CHECK (statut_reponse IN ('non_engagee','en_cours','en_signature','signe')),
    CONSTRAINT courrier_cloture_coherente
      CHECK ((statut_courrier = 'cloture') = (cloture_le IS NOT NULL)),
    -- Le numero est unique PAR SESSION, non globalement : chaque session
    -- dispose de son propre compteur, par coherence avec l'etancheite du
    -- circuit confidentiel. Deux courriers peuvent donc porter 0001/2026
    -- dans deux sessions differentes, comme deux registres papier distincts.
    CONSTRAINT courrier_numero_unique_par_session UNIQUE (session_id, numero)
);

COMMENT ON COLUMN courrier.structure_chef_file_id IS
  'Denormalise depuis cotation_structure de rang 1. Sert le tri des listes sans jointure.';

CREATE TABLE piece_jointe (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid                UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    courrier_id        BIGINT      REFERENCES courrier(id),
    nom_fichier        TEXT        NOT NULL,
    nom_original       TEXT        NOT NULL,
    extension          TEXT,
    taille_octets      BIGINT      NOT NULL,
    type_mime          TEXT,
    empreinte_sha256   TEXT        NOT NULL,          -- preuve d'integrite
    chemin_stockage    TEXT        NOT NULL,
    categorie          TEXT        NOT NULL DEFAULT 'annexe',
    version            SMALLINT    NOT NULL DEFAULT 1,
    piece_precedente_id BIGINT     REFERENCES piece_jointe(id),
    texte_reconnu      TEXT,
    recherche          TSVECTOR,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par           BIGINT,
    invalide_le        TIMESTAMPTZ,
    invalide_par       BIGINT,
    CONSTRAINT piece_categorie_valide
      CHECK (categorie IN ('original','annexe','reponse','accuse','justificatif'))
);
CREATE INDEX piece_jointe_courrier  ON piece_jointe (courrier_id);
CREATE INDEX piece_jointe_recherche ON piece_jointe USING GIN (recherche);

COMMENT ON COLUMN piece_jointe.chemin_stockage IS
  'Les fichiers ne sont pas en base mais sur volume dedie. Une base contenant les binaires devient insauvegardable.';

-- ---------------------------------------------------------------------
--  cotation
--  L'ACTE de cotation. Le DG cote une fois, eventuellement a plusieurs
--  structures : c'est une seule decision.
--
--  decide_par / saisi_par : le DG decide, l'agent de session enregistre.
--  Une colonne unique attribuerait a l'agent une decision qu'il n'a
--  pas prise, ce qui vide le journal de sa valeur probante.
-- ---------------------------------------------------------------------
CREATE TABLE cotation (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id         BIGINT      NOT NULL REFERENCES courrier(id),
    mention_type_id     BIGINT      REFERENCES mention_type(id),
    annotation          TEXT,
    delai_fixe          DATE,
    decide_par          BIGINT      NOT NULL REFERENCES utilisateur(id),
    decide_le           TIMESTAMPTZ NOT NULL,
    saisi_par           BIGINT      NOT NULL REFERENCES utilisateur(id),
    saisi_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    niveau_cotation     SMALLINT    NOT NULL DEFAULT 1,
    cotation_parente_id BIGINT      REFERENCES cotation(id),
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par            BIGINT,
    modifie_le          TIMESTAMPTZ,
    modifie_par         BIGINT,
    invalide_le         TIMESTAMPTZ,
    invalide_par        BIGINT,
    CONSTRAINT cotation_saisie_apres_decision CHECK (saisi_le >= decide_le)
);
CREATE INDEX cotation_courrier ON cotation (courrier_id);
CREATE INDEX cotation_parente  ON cotation (cotation_parente_id);

COMMENT ON COLUMN cotation.decide_par IS
  'L''autorite qui cote (le Directeur General). Ne jamais confondre avec saisi_par.';
COMMENT ON COLUMN cotation.saisi_par IS
  'L''agent de session qui enregistre. Egal a decide_par quand le responsable cote lui-meme.';

-- ---------------------------------------------------------------------
--  cotation_structure
--  Les structures visees, avec leur rang. LE RANG 1 EST CHEF DE FILE :
--  il coordonne et centralise la reponse.
-- ---------------------------------------------------------------------
CREATE TABLE cotation_structure (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cotation_id   BIGINT   NOT NULL REFERENCES cotation(id) ON DELETE CASCADE,
    structure_id  BIGINT   NOT NULL REFERENCES structure(id),
    rang          SMALLINT NOT NULL,
    chef_de_file  BOOLEAN  GENERATED ALWAYS AS (rang = 1) STORED,
    UNIQUE (cotation_id, rang),
    UNIQUE (cotation_id, structure_id),
    CONSTRAINT cotation_structure_rang_positif CHECK (rang > 0)
);
CREATE INDEX cotation_structure_structure ON cotation_structure (structure_id, rang);

-- ---------------------------------------------------------------------
--  affectation
--  La cotation va vers une STRUCTURE, l'affectation va vers une PERSONNE.
--  Deux actes distincts, deux acteurs distincts.
-- ---------------------------------------------------------------------
CREATE TABLE affectation (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cotation_structure_id BIGINT      NOT NULL REFERENCES cotation_structure(id),
    utilisateur_id        BIGINT      NOT NULL REFERENCES utilisateur(id),
    orientations          TEXT,
    delai_fixe            DATE,
    affecte_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    affecte_par           BIGINT      NOT NULL REFERENCES utilisateur(id),
    retire_le             TIMESTAMPTZ,
    retire_par            BIGINT      REFERENCES utilisateur(id)
);
CREATE INDEX affectation_utilisateur
    ON affectation (utilisateur_id) WHERE retire_le IS NULL;
CREATE INDEX affectation_cotation ON affectation (cotation_structure_id);

CREATE TABLE traitement (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cotation_structure_id BIGINT      NOT NULL REFERENCES cotation_structure(id),
    courrier_id           BIGINT      NOT NULL REFERENCES courrier(id),
    redacteur_id          BIGINT      NOT NULL REFERENCES utilisateur(id),
    version               SMALLINT    NOT NULL DEFAULT 1,
    contenu               TEXT,
    contenu_format        TEXT        NOT NULL DEFAULT 'html',
    statut                TEXT        NOT NULL DEFAULT 'brouillon',
    soumis_le             TIMESTAMPTZ,
    cree_le               TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par              BIGINT,
    modifie_le            TIMESTAMPTZ,
    modifie_par           BIGINT,
    invalide_le           TIMESTAMPTZ,
    invalide_par          BIGINT,
    CONSTRAINT traitement_format_valide CHECK (contenu_format IN ('texte','html')),
    CONSTRAINT traitement_statut_valide
      CHECK (statut IN ('brouillon','soumis','retourne','valide'))
);
CREATE INDEX traitement_courrier ON traitement (courrier_id);

COMMENT ON TABLE traitement IS
  'HYPOTHESE : ni le cahier des charges ni le BRD ne decrivent ce que produit un agent qui traite un courrier. A revoir des que l''ecran sera specifie.';

CREATE TABLE traitement_version (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    traitement_id BIGINT      NOT NULL REFERENCES traitement(id) ON DELETE CASCADE,
    version       SMALLINT    NOT NULL,
    contenu       TEXT,
    redacteur_id  BIGINT      NOT NULL REFERENCES utilisateur(id),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (traitement_id, version)
);

CREATE TABLE instance_circuit (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cotation_structure_id BIGINT      NOT NULL REFERENCES cotation_structure(id),
    circuit_version_id    BIGINT      NOT NULL REFERENCES circuit_version(id),
    statut                TEXT        NOT NULL DEFAULT 'en_cours',
    demarre_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    termine_le            TIMESTAMPTZ,
    CONSTRAINT instance_statut_valide
      CHECK (statut IN ('en_cours','termine','abandonne'))
);
CREATE INDEX instance_circuit_cotation ON instance_circuit (cotation_structure_id);

COMMENT ON COLUMN instance_circuit.circuit_version_id IS
  'FIGE le circuit sur le courrier. L''administrateur pouvant modifier l''organigramme, un circuit recalcule a la volee reecrirait l''histoire.';

CREATE TABLE instance_etape (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instance_circuit_id BIGINT      NOT NULL REFERENCES instance_circuit(id) ON DELETE CASCADE,
    circuit_etape_id    BIGINT      REFERENCES circuit_etape(id),
    rang                SMALLINT    NOT NULL,
    structure_id        BIGINT      REFERENCES structure(id),
    titulaire_id        BIGINT      REFERENCES utilisateur(id),
    acteur_reel_id      BIGINT      REFERENCES utilisateur(id),
    statut              TEXT        NOT NULL DEFAULT 'attente',
    echeance            DATE,
    entree_le           TIMESTAMPTZ,
    sortie_le           TIMESTAMPTZ,
    duree_ouvree        SMALLINT,
    CONSTRAINT instance_etape_statut_valide
      CHECK (statut IN ('attente','en_cours','franchie','retournee','sautee'))
);
CREATE INDEX instance_etape_a_traiter
    ON instance_etape (titulaire_id) WHERE statut = 'en_cours';
CREATE INDEX instance_etape_circuit ON instance_etape (instance_circuit_id, rang);

COMMENT ON COLUMN instance_etape.duree_ouvree IS
  'Calculee a la sortie et stockee. Evite de recalculer les jours ouvres a chaque lecture.';

CREATE TABLE validation (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    traitement_id          BIGINT      NOT NULL REFERENCES traitement(id),
    instance_etape_id      BIGINT      REFERENCES instance_etape(id),
    validateur_id          BIGINT      NOT NULL REFERENCES utilisateur(id),
    agit_pour_id           BIGINT      REFERENCES utilisateur(id),
    delegation_id          BIGINT      REFERENCES delegation(id),
    decision               TEXT        NOT NULL,
    motif                  TEXT,
    amendement             TEXT,
    destinataire_retour_id BIGINT      REFERENCES utilisateur(id),
    decidee_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par               BIGINT,
    CONSTRAINT validation_decision_valide
      CHECK (decision IN ('valide','amende','correction_demandee','retourne')),
    CONSTRAINT validation_motif_requis
      CHECK (decision = 'valide' OR motif IS NOT NULL)
);
CREATE INDEX validation_traitement ON validation (traitement_id, decidee_le DESC);

COMMENT ON COLUMN validation.agit_pour_id IS
  'Vide quand l''agent agit en son nom, renseigne quand il agit pour un autre (remplacant ou delegataire).';

-- ---------------------------------------------------------------------
--  transmission
--  La trace du courrier PHYSIQUE, indispensable tant que le papier
--  circule en parallele de l'application.
-- ---------------------------------------------------------------------
CREATE TABLE transmission (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id              BIGINT      NOT NULL REFERENCES courrier(id),
    structure_emettrice_id   BIGINT      REFERENCES structure(id),
    structure_destinataire_id BIGINT     REFERENCES structure(id),
    bordereau_reference      TEXT,
    transmis_le              TIMESTAMPTZ NOT NULL DEFAULT now(),
    transmis_par             BIGINT      NOT NULL REFERENCES utilisateur(id),
    recu_le                  TIMESTAMPTZ,
    recu_par_nom             TEXT,
    recu_par_id              BIGINT      REFERENCES utilisateur(id),
    observation              TEXT,
    cree_le                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par                 BIGINT,
    CONSTRAINT transmission_reception_coherente
      CHECK (recu_le IS NULL OR recu_le >= transmis_le)
);
CREATE INDEX transmission_courrier ON transmission (courrier_id);
CREATE INDEX transmission_sans_accuse
    ON transmission (structure_destinataire_id) WHERE recu_le IS NULL;

CREATE TABLE relance (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    courrier_id       BIGINT      REFERENCES courrier(id),
    instance_etape_id BIGINT      REFERENCES instance_etape(id),
    nature            TEXT        NOT NULL,
    emetteur_id       BIGINT      REFERENCES utilisateur(id),
    destinataire_id   BIGINT      NOT NULL REFERENCES utilisateur(id),
    motif             TEXT,
    emise_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    reponse_le        TIMESTAMPTZ,
    CONSTRAINT relance_nature_valide CHECK (nature IN ('automatique','manuelle'))
);
CREATE INDEX relance_courrier ON relance (courrier_id, emise_le DESC);


-- =====================================================================
--  6. TRACABILITE - trois journaux distincts
--  Les fusionner serait une erreur : leurs volumes different d'un
--  facteur cent, leurs lecteurs et leurs retentions ne sont pas
--  les memes.
-- =====================================================================

-- ---------------------------------------------------------------------
--  evenement  (~1,2 million de lignes par an)
--  Alimente la fiche de vie. Partitionne par annee.
-- ---------------------------------------------------------------------
CREATE TABLE evenement (
    id             BIGINT GENERATED ALWAYS AS IDENTITY,
    objet_type     TEXT        NOT NULL,
    objet_id       BIGINT      NOT NULL,
    courrier_id    BIGINT,
    type_evenement TEXT        NOT NULL,
    libelle        TEXT        NOT NULL,
    detail         TEXT,
    acteur_id      BIGINT,                       -- qui a saisi
    agit_pour_id   BIGINT,                       -- pour le compte de qui
    survenu_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    donnees        JSONB,
    PRIMARY KEY (id, survenu_le)
) PARTITION BY RANGE (survenu_le);

CREATE TABLE evenement_2026 PARTITION OF evenement
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE evenement_2027 PARTITION OF evenement
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');

-- Filet de securite : sans partition par defaut, toute insertion hors
-- des bornes ci-dessus echoue (no partition found for row) et arrete
-- le service. La partition par defaut absorbe le debordement en
-- attendant la creation de la partition nominale.
CREATE TABLE evenement_defaut PARTITION OF evenement DEFAULT;

CREATE INDEX evenement_courrier ON evenement (courrier_id, survenu_le DESC);
CREATE INDEX evenement_objet    ON evenement (objet_type, objet_id, survenu_le DESC);

-- ---------------------------------------------------------------------
--  champ_historique  (~2 millions de lignes par an)
--  Alimente par declencheur, non par le code applicatif : une
--  modification faite hors application est ainsi tracee elle aussi.
-- ---------------------------------------------------------------------
CREATE TABLE champ_historique (
    id            BIGINT GENERATED ALWAYS AS IDENTITY,
    table_cible   TEXT        NOT NULL,
    ligne_id      BIGINT      NOT NULL,
    colonne       TEXT        NOT NULL,
    valeur_avant  TEXT,
    valeur_apres  TEXT,
    acteur_id     BIGINT,
    survenu_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, survenu_le)
) PARTITION BY RANGE (survenu_le);

CREATE TABLE champ_historique_2026 PARTITION OF champ_historique
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE champ_historique_2027 PARTITION OF champ_historique
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');

CREATE TABLE champ_historique_defaut PARTITION OF champ_historique DEFAULT;

CREATE INDEX champ_historique_ligne
    ON champ_historique (table_cible, ligne_id, survenu_le DESC);

-- ---------------------------------------------------------------------
--  journal_acces  (~12 a 20 millions de lignes par an)
--  Chaine par empreinte : toute suppression rompt la chaine et
--  devient detectable. Partitionne par mois.
-- ---------------------------------------------------------------------
CREATE TABLE journal_acces (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    acteur_id           BIGINT      NOT NULL,
    objet_type          TEXT        NOT NULL,
    objet_id            BIGINT,
    action              TEXT        NOT NULL,
    adresse_ip          INET,
    agent_utilisateur   TEXT,
    survenu_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- L'empreinte n'est pas calculee a l'insertion mais par un
    -- traitement d'arriere-plan (voir chainer_journal_lot). Elle reste
    -- donc NULL le temps que le lot passe : une ligne sans empreinte
    -- est une ligne en attente de scellement, pas une ligne douteuse.
    empreinte           TEXT,
    empreinte_precedente TEXT,
    PRIMARY KEY (id, survenu_le),
    CONSTRAINT journal_action_valide
      CHECK (action IN ('consultation','liste','impression','export','telechargement'))
) PARTITION BY RANGE (survenu_le);

CREATE TABLE journal_acces_2026_08 PARTITION OF journal_acces
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE journal_acces_2026_09 PARTITION OF journal_acces
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE journal_acces_2026_10 PARTITION OF journal_acces
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- Les partitions mensuelles nominales s'arretent au 31 octobre 2026.
-- Sans cette partition par defaut, toute ecriture au 1er novembre
-- 2026 echouerait et le service serait interrompu. La creation des
-- partitions mensuelles suivantes reste a automatiser (pg_partman).
CREATE TABLE journal_acces_defaut PARTITION OF journal_acces DEFAULT;

-- Index BRIN : quelques megaoctets la ou un index classique en
-- prendrait plusieurs gigaoctets, la table etant chronologique.
CREATE INDEX journal_acces_periode ON journal_acces USING BRIN (survenu_le);
CREATE INDEX journal_acces_acteur  ON journal_acces (acteur_id, survenu_le DESC);

-- Index partiel des lignes restant a sceller. Il ne contient que la
-- file d'attente du chainage, soit quelques milliers de lignes au
-- plus, et non les vingt millions de lignes deja scellees.
CREATE INDEX journal_acces_a_chainer
    ON journal_acces (survenu_le, id) WHERE empreinte IS NULL;


-- =====================================================================
--  7. AGREGATS PRE-CALCULES
--  Les tableaux de bord ne doivent jamais agreger la table des
--  courriers a la volee.
-- =====================================================================

CREATE TABLE agregat_structure_jour (
    structure_id       BIGINT      NOT NULL REFERENCES structure(id),
    jour               DATE        NOT NULL,
    nb_en_attente      INTEGER     NOT NULL DEFAULT 0,
    nb_hors_delai      INTEGER     NOT NULL DEFAULT 0,
    nb_traites         INTEGER     NOT NULL DEFAULT 0,
    nb_en_signature    INTEGER     NOT NULL DEFAULT 0,
    nb_urgents         INTEGER     NOT NULL DEFAULT 0,
    delai_moyen_ouvre  NUMERIC(6,2),
    taux_respect_delai NUMERIC(5,2),
    calcule_le         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (structure_id, jour)
);


-- =====================================================================
--  8. CLES ETRANGERES DIFFEREES
--  Les colonnes systematiques referencent utilisateur(id), qui porte
--  lui-meme ces colonnes. Elles sont donc ajoutees apres coup.
-- =====================================================================

DO $$
DECLARE
    t TEXT;
    c TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'niveau_hierarchique','structure','poste','utilisateur','session',
        'utilisateur_session','profil','utilisateur_profil','perimetre',
        'delegation','correspondant','nature','mention_type','circuit',
        'circuit_version','circuit_regle','courrier','piece_jointe',
        'cotation','traitement','traitement_version','validation',
        'transmission'
    ] LOOP
        FOREACH c IN ARRAY ARRAY[
            'cree_par','modifie_par','invalide_par','attribue_par',
            'retire_par','publie_par'
        ] LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = t AND column_name = c
                  AND table_schema = current_schema()
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage k
                  ON tc.constraint_name = k.constraint_name
                WHERE tc.table_name = t AND k.column_name = c
                  AND tc.constraint_type = 'FOREIGN KEY'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES utilisateur(id)',
                    t, t || '_' || c || '_fk', c);
            END IF;
        END LOOP;
    END LOOP;
END $$;


-- =====================================================================
--  9. INDEX LIES AUX ECRANS
--  Un index ne se pose pas sur une colonne parce qu'elle semble
--  importante, mais parce qu'une requete reelle le reclame.
-- =====================================================================

-- Tableau de bord du responsable : les courriers dont ma structure est
-- chef de file, non traites, tries par echeance. Requete la plus
-- frequente de l'application.
CREATE INDEX courrier_tableau_bord
    ON courrier (structure_chef_file_id, statut_courrier, date_limite)
    WHERE invalide_le IS NULL;

-- Liste de travail d'un agent et registre imprimable.
CREATE INDEX courrier_session
    ON courrier (session_id, date_reception DESC)
    WHERE invalide_le IS NULL;

-- Courriers hors delai et a echeance. Index partiel sur les seuls
-- courriers actifs, soit une fraction du total apres quelques annees.
CREATE INDEX courrier_echeance
    ON courrier (date_limite)
    WHERE statut_courrier IN ('cree','en_cours') AND invalide_le IS NULL;

-- Recherche plein texte sur objet, observations et texte reconnu.
CREATE INDEX courrier_recherche ON courrier USING GIN (recherche);

-- Courriers confidentiels : filtre de perimetre de la DSR.
CREATE INDEX courrier_confidentiel
    ON courrier (date_reception DESC) WHERE confidentiel;

-- Cles etrangeres. PostgreSQL n'indexe pas automatiquement le cote
-- referencant : sans ces index, toute suppression ou modification de
-- cle dans correspondant, nature, priorite ou utilisateur impose un
-- balayage complet de la table referencante, verrou en main.
CREATE INDEX courrier_expediteur   ON courrier (expediteur_id);
CREATE INDEX courrier_destinataire ON courrier (destinataire_id);
CREATE INDEX courrier_nature       ON courrier (nature_id);
CREATE INDEX courrier_priorite     ON courrier (priorite_id);
CREATE INDEX traitement_redacteur  ON traitement (redacteur_id);


-- =====================================================================
--  10. DECLENCHEURS
-- =====================================================================

-- ---------------------------------------------------------------------
--  Attribution du numero : compteur annuel par session, remis a zero
--  au 1er janvier. Le verrou de ligne empeche deux agents saisissant
--  simultanement d'obtenir le meme numero.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION attribuer_numero() RETURNS TRIGGER AS $$
DECLARE
    v_annee   SMALLINT := EXTRACT(YEAR FROM COALESCE(NEW.date_reception, CURRENT_DATE));
    v_numero  INTEGER;
BEGIN
    IF NEW.numero IS NOT NULL AND NEW.numero <> '' THEN
        RETURN NEW;
    END IF;

    INSERT INTO sequence_numerotation (session_id, annee, dernier_numero)
         VALUES (NEW.session_id, v_annee, 0)
    ON CONFLICT (session_id, annee) DO NOTHING;

    UPDATE sequence_numerotation
       SET dernier_numero = dernier_numero + 1
     WHERE session_id = NEW.session_id AND annee = v_annee
    RETURNING dernier_numero INTO v_numero;

    NEW.numero := lpad(v_numero::TEXT, 4, '0') || '/' || v_annee::TEXT;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER courrier_numero
    BEFORE INSERT ON courrier
    FOR EACH ROW EXECUTE FUNCTION attribuer_numero();

-- ---------------------------------------------------------------------
--  Mise a jour de l'index plein texte du courrier.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_recherche_courrier() RETURNS TRIGGER AS $$
BEGIN
    NEW.recherche :=
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.objet,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.expediteur_libelle,'')), 'B') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.numero,'')), 'B') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.observations,'')), 'D');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER courrier_recherche_maj
    BEFORE INSERT OR UPDATE ON courrier
    FOR EACH ROW EXECUTE FUNCTION maj_recherche_courrier();

-- ---------------------------------------------------------------------
--  Mise a jour de l'index plein texte du correspondant.
--  La colonne recherche et son index GIN existaient sans alimentation :
--  la recherche par correspondant ne renvoyait donc jamais rien.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_recherche_correspondant() RETURNS TRIGGER AS $$
BEGIN
    NEW.recherche :=
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.raison_sociale,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent',
            coalesce(NEW.nom,'') || ' ' || coalesce(NEW.prenom,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.ville,'')), 'C') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.courriel,'')), 'D');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER correspondant_recherche_maj
    BEFORE INSERT OR UPDATE ON correspondant
    FOR EACH ROW EXECUTE FUNCTION maj_recherche_correspondant();

-- ---------------------------------------------------------------------
--  Mise a jour de l'index plein texte de la piece jointe.
--  texte_reconnu, produit par la reconnaissance optique, depasse
--  frequemment la page de 8 KB et part en table TOAST. Le declencheur
--  ne recalcule donc le vecteur que si ce champ a reellement change,
--  pour ne pas payer la decompression a chaque mise a jour de la ligne.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_recherche_piece() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.texte_reconnu IS NOT DISTINCT FROM OLD.texte_reconnu
       AND NEW.nom_original  IS NOT DISTINCT FROM OLD.nom_original THEN
        RETURN NEW;
    END IF;

    NEW.recherche :=
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.nom_original,'')), 'B') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.texte_reconnu,'')), 'D');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER piece_jointe_recherche_maj
    BEFORE INSERT OR UPDATE ON piece_jointe
    FOR EACH ROW EXECUTE FUNCTION maj_recherche_piece();

-- ---------------------------------------------------------------------
--  Denormalisation du chef de file sur le courrier.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_chef_de_file() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.rang = 1 THEN
        -- La clause sur structure_chef_file_id evite de reecrire la
        -- ligne quand le chef de file ne change pas. Sans elle, chaque
        -- enregistrement de cotation declenchait une mise a jour du
        -- courrier, donc l'historisation complete de ses champs, pour
        -- un resultat identique.
        UPDATE courrier c
           SET structure_chef_file_id = NEW.structure_id,
               modifie_le = now()
          FROM cotation co
         WHERE co.id = NEW.cotation_id
           AND c.id  = co.courrier_id
           AND c.structure_chef_file_id IS DISTINCT FROM NEW.structure_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER cotation_structure_chef_file
    AFTER INSERT OR UPDATE ON cotation_structure
    FOR EACH ROW EXECUTE FUNCTION maj_chef_de_file();

-- ---------------------------------------------------------------------
--  Historisation des champs, au niveau du moteur.
--  L'acteur est lu dans la variable app.utilisateur_id, que
--  l'application doit positionner AU DEBUT DE CHAQUE TRANSACTION :
--      BEGIN;
--      SET LOCAL app.utilisateur_id = '42';
--      ... les ecritures ...
--      COMMIT;
--  Hors transaction, SET LOCAL est sans effet et l'acteur reste vide.
--
--  L'absence de cette variable n'est plus toleree en silence : une
--  modification enregistree sans acteur retire toute valeur probante a
--  l'audit, et l'oubli passerait inapercu jusqu'au jour ou l'on aurait
--  besoin de la trace. Un traitement legitimement non nominatif doit
--  le declarer explicitement :
--      SET LOCAL app.contexte = 'batch';
-- ---------------------------------------------------------------------
--  La comparaison passe par to_jsonb(OLD) / to_jsonb(NEW), fonctions
--  natives qui decomposent le tuple en memoire. La version precedente
--  interrogeait information_schema.columns (vue joignant pg_class,
--  pg_attribute, pg_type et pg_namespace) puis executait deux requetes
--  dynamiques par colonne et par ligne modifiee : aucun acces au
--  catalogue systeme ni aucune requete SQL ne subsiste ici.
CREATE OR REPLACE FUNCTION historiser_champs() RETURNS TRIGGER AS $$
DECLARE
    v_acteur BIGINT := nullif(current_setting('app.utilisateur_id', true), '')::BIGINT;
    v_avant_json JSONB := to_jsonb(OLD) - 'modifie_le' - 'recherche';
    v_apres_json JSONB := to_jsonb(NEW) - 'modifie_le' - 'recherche';
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

CREATE TRIGGER courrier_historique
    AFTER UPDATE ON courrier
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER cotation_historique
    AFTER UPDATE ON cotation
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER structure_historique
    AFTER UPDATE ON structure
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

-- ---------------------------------------------------------------------
--  Chainage du journal d'acces : chaque ligne porte l'empreinte de la
--  precedente, donc toute suppression rompt la chaine.
--
--  Le chainage NE PEUT PAS se faire dans un declencheur a l'insertion.
--  Un tel declencheur lirait la derniere empreinte par un SELECT, or
--  ce SELECT ne verrouille rien : deux transactions simultanees lisent
--  la meme empreinte precedente et produisent deux lignes soeurs. La
--  chaine se dedouble sans qu'aucune erreur ne soit levee, et la
--  preuve d'integrite ne vaut plus rien. S'y ajoutait le cout d'un
--  parcours de toutes les partitions a chaque ecriture.
--
--  Les acces sont donc inseres bruts, empreinte a NULL, sans aucune
--  contention. Le scellement est confie a la fonction ci-dessous,
--  appelee periodiquement par une tache planifiee (pg_cron, ou un
--  ordonnanceur externe) :
--      SELECT chainer_journal_lot(5000);
--  Un verrou consultatif garantit qu'une seule execution scelle a la
--  fois, ce qui rend l'ordre de la chaine deterministe.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION chainer_journal_lot(p_taille INTEGER DEFAULT 5000)
RETURNS INTEGER AS $$
DECLARE
    v_precedente TEXT;
    v_courante   TEXT;
    v_ligne      RECORD;
    v_traitees   INTEGER := 0;
BEGIN
    -- Une seule instance de scellement a la fois. Si un lot precedent
    -- tourne encore, on ressort sans rien faire plutot que d'attendre.
    IF NOT pg_try_advisory_xact_lock(hashtext('journal_acces_chainage')) THEN
        RETURN 0;
    END IF;

    SELECT empreinte INTO v_precedente
      FROM journal_acces
     WHERE empreinte IS NOT NULL
     ORDER BY survenu_le DESC, id DESC
     LIMIT 1;

    v_precedente := coalesce(v_precedente, repeat('0', 64));

    FOR v_ligne IN
        SELECT id, survenu_le, acteur_id, objet_type, objet_id, action
          FROM journal_acces
         WHERE empreinte IS NULL
         ORDER BY survenu_le, id
         LIMIT p_taille
    LOOP
        v_courante := encode(digest(
            v_precedente || coalesce(v_ligne.acteur_id::TEXT,'') ||
            v_ligne.objet_type || coalesce(v_ligne.objet_id::TEXT,'') ||
            v_ligne.action || v_ligne.survenu_le::TEXT, 'sha256'), 'hex');

        UPDATE journal_acces
           SET empreinte_precedente = v_precedente,
               empreinte            = v_courante
         WHERE id = v_ligne.id AND survenu_le = v_ligne.survenu_le;

        v_precedente := v_courante;
        v_traitees   := v_traitees + 1;
    END LOOP;

    RETURN v_traitees;
END $$ LANGUAGE plpgsql;

COMMENT ON FUNCTION chainer_journal_lot(INTEGER) IS
  'Scelle par lots les lignes de journal_acces non encore chainees. A appeler periodiquement (toutes les minutes suffit). Retourne le nombre de lignes scellees.';

-- ---------------------------------------------------------------------
--  Verification de la chaine. Retourne les lignes dont l'empreinte ne
--  correspond plus au contenu ou dont le maillon precedent a ete
--  altere : c'est la requete que produira un controle d'integrite.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION verifier_journal(p_depuis TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE (id BIGINT, survenu_le TIMESTAMPTZ, anomalie TEXT) AS $$
    WITH chaine AS (
        SELECT j.id, j.survenu_le, j.empreinte, j.empreinte_precedente,
               encode(digest(
                   j.empreinte_precedente || coalesce(j.acteur_id::TEXT,'') ||
                   j.objet_type || coalesce(j.objet_id::TEXT,'') ||
                   j.action || j.survenu_le::TEXT, 'sha256'), 'hex') AS attendue,
               lag(j.empreinte) OVER (ORDER BY j.survenu_le, j.id) AS empreinte_amont
          FROM journal_acces j
         WHERE j.empreinte IS NOT NULL
           AND (p_depuis IS NULL OR j.survenu_le >= p_depuis)
    )
    SELECT c.id, c.survenu_le,
           CASE WHEN c.empreinte <> c.attendue THEN 'contenu altere'
                ELSE 'maillon precedent rompu' END
      FROM chaine c
     WHERE c.empreinte <> c.attendue
        OR (c.empreinte_amont IS NOT NULL
            AND c.empreinte_precedente <> c.empreinte_amont)
     ORDER BY c.survenu_le, c.id;
$$ LANGUAGE sql STABLE;


-- =====================================================================
--  11. DONNEES INITIALES
--  L'application doit fonctionner des l'installation, sans que
--  l'administrateur ait a intervenir.
-- =====================================================================

INSERT INTO niveau_hierarchique (code, libelle, rang) VALUES
  ('DG',   'Direction Generale', 1),
  ('DIR',  'Direction',          2),
  ('DEP',  'Departement',        3),
  ('SERV', 'Service',            4);

INSERT INTO session (code, libelle, sens, lit_toutes_sessions) VALUES
  ('arrive',       'Courrier Arrive',       'arrive',   false),
  ('depart',       'Courrier Depart',       'depart',   false),
  ('interne',      'Courrier Interne',      'interne',  false),
  ('confidentiel', 'Courrier Confidentiel', 'arrive',   true);

INSERT INTO mention_type (code, libelle, ordre) VALUES
  ('ATTRIB', 'Pour attribution',      1),
  ('AVIS',   'Pour avis',             2),
  ('INFO',   'Pour information',      3),
  ('COMPTE', 'A me rendre compte',    4),
  ('SUITE',  'Pour suite a donner',   5);

INSERT INTO priorite (code, libelle, rang, couleur) VALUES
  ('URGENT',  'Urgent',   1, '#d92d20'),
  ('ELEVEE',  'Elevee',   2, '#f79009'),
  ('NORMALE', 'Normale',  3, '#2f6bed'),
  ('BASSE',   'Basse',    4, '#667085');

INSERT INTO nature (code, libelle, delai_defaut_jours) VALUES
  ('DEMANDE',    'Demande',              15),
  ('RECLAMATION','Reclamation',          10),
  ('INVITATION', 'Invitation',            5),
  ('RAPPORT',    'Rapport',              30),
  ('NOTE',       'Note de service',       7),
  ('AUTRE',      'Autre',                15);

INSERT INTO permission (code, libelle, domaine) VALUES
  ('LEC',      'Consulter',                        'courrier'),
  ('ENR',      'Enregistrer un courrier',          'courrier'),
  ('COT',      'Coter',                            'courrier'),
  ('COT_DEL',  'Saisir une cotation pour un autre','courrier'),
  ('AFF',      'Affecter a un collaborateur',      'courrier'),
  ('TRA',      'Traiter et rediger',               'courrier'),
  ('VAL',      'Valider',                          'courrier'),
  ('TRANS',    'Transmettre et accuser reception', 'courrier'),
  ('CLO',      'Cloturer',                         'courrier'),
  ('REL',      'Relancer',                         'courrier'),
  ('IMP',      'Imprimer bordereaux et registres', 'courrier'),
  ('CONF',     'Acceder aux courriers confidentiels','courrier'),
  ('STAT',     'Consulter les statistiques',       'courrier'),
  ('ACT_LEC',  'Consulter les activites',          'activite'),
  ('ACT_SAI',  'Saisir les activites de sa structure','activite'),
  ('ACT_VAL',  'Valider un plan d''actions annuel', 'activite'),
  ('DEC',      'Tenir le registre des decisions',  'gouvernance'),
  ('INST',     'Tenir le registre des reunions',   'gouvernance'),
  ('DISPO',    'Renseigner la disponibilite',      'gouvernance'),
  ('SCORE',    'Consulter le classement des structures','performance'),
  ('SCORE_ADM','Administrer indicateurs et calendrier','performance'),
  ('COCKPIT',  'Acceder au cockpit executif',      'performance'),
  -- Seule permission de la table qui designe un poste plutot qu'un geste.
  -- La vue d'ensemble n'a ni perimetre ni declinaison : elle appartient au
  -- Directeur General, et l'ouvrir a un second profil la viderait de son objet.
  ('VUE_DG',   'Acceder a la vue d''ensemble de la Direction generale','performance'),
  -- Meme exception, meme raison. Le Comite de Direction est le conseil des
  -- directeurs : une instance, pas un poste. Sa vue d'ensemble a le meme
  -- appareil que celle du Directeur General, mais elle compare les directions
  -- entre elles la ou celle du DG agrege l'institution. Separee de COCKPIT,
  -- qui reste l'ecran d'arbitrage partage entre les deux.
  ('VUE_CODIR','Acceder a la vue d''ensemble du Comite de Direction','performance'),
  ('ADM_STR',  'Tenir le referentiel des structures','performance'),
  -- Quatrieme famille de donnees, a cote du courrier, des activites et des
  -- decisions : ce que le port mesure de lui-meme. La DDLM et sa Regie
  -- relevent la cote du chenal, la Direction de l'exploitation constate les
  -- recouvrements par secteur, celle des finances les autres recettes.
  -- Demande du Directeur General du 11 aout 2026.
  ('EXP_SAI',  'Saisir les releves d''exploitation de sa structure','exploitation'),
  ('EXP_LEC',  'Consulter la cote du chenal et les recouvrements','exploitation'),
  ('DOS_LEC',  'Consulter les dossiers a instruire','dossier'),
  ('DOS_INS',  'Instruire un dossier',             'dossier'),
  ('DOS_VAL',  'Valider ou retourner un dossier',  'dossier'),
  ('ARCH',     'Appliquer le referentiel de conservation','archivage'),
  ('EXT',      'Deposer et suivre sa propre demande', 'externe'),
  ('ADM_ORG',  'Administrer l''organigramme',      'administration'),
  ('ADM_HAB',  'Administrer les habilitations',    'administration'),
  ('ADM_PAR',  'Administrer le parametrage',       'administration'),
  ('AUDIT',    'Consulter les journaux',           'administration'),
  ('ADM_TEC',  'Superviser la plateforme et les integrations','administration');

INSERT INTO profil (code, libelle, systeme, description) VALUES
  ('ADMIN',      'Administrateur fonctionnel', true, 'Organigramme, habilitations, parametrage'),
  ('ADMIN_TECH', 'Administrateur technique',   true, 'Exploitation et securite'),
  ('DG',         'Directeur General',          true, 'Cotation, validation, pilotage'),
  ('AGENT_SESS', 'Agent de session courrier',  true, 'Enregistrement, saisie de cotation, transmission'),
  ('RESP',       'Responsable de structure',   true, 'Cotation en cascade, affectation, validation'),
  ('COLLAB',     'Collaborateur',              true, 'Traitement des courriers affectes'),
  -- Le code DSR designe la Division elle-meme, telle que le descriptif
  -- fonctionnel la decrit au §3.3 : acces transversal, tenue des registres,
  -- administration du dispositif. L'attache exerce le suivi de portefeuille
  -- et la relance sur les seules structures qui lui sont confiees (CDC §12).
  ('DSR',        'Division du suivi et de la relance', true, 'Suivi transversal et co-administration'),
  ('ATT_DSR',    'Attache a la DSR',           true, 'Suivi de portefeuille et relance'),
  ('DCG',        'Controle de gestion',        true, 'Analyse de la performance'),
  ('AUDITEUR',   'Auditeur',                   true, 'Consultation seule et journaux'),
  ('CODIR',      'Membre du Comite de Direction', true, 'Pilotage tactique et arbitrages inter-structures'),
  ('POINT_FOCAL','Point focal de structure',   true, 'Alimentation des donnees de sa seule structure'),
  -- Un seul profil pour les quatre structures qui mesurent le port : DDLM,
  -- Regie du dragage, Direction de l'exploitation, Direction des finances et
  -- de la comptabilite. Ce n'est pas leur metier qui les rassemble, c'est le
  -- geste — rendre compte d'un chiffre releve. Le perimetre de chacune decide
  -- ensuite de ce qu'elle saisit et de ce qu'elle voit.
  ('EXPLOITATION','Structure d''exploitation',  true, 'Releve la cote du chenal ou constate les recouvrements'),
  ('ARCHIVISTE', 'Archiviste / records manager', true, 'Conservation, versement et sort final'),
  ('EXTERNE',    'Usager ou partenaire externe', true, 'Depot et suivi de sa demande, via le portail dedie');

-- Attribution des permissions aux profils.
INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id FROM profil p, permission x
    -- Pas de LEC : celui qui distribue les droits ne consulte pas les
    -- dossiers. Separation des taches exigee par le BRD (RNF-SEC-02).
 WHERE (p.code = 'ADMIN'      AND x.code IN ('ADM_ORG','ADM_HAB','ADM_PAR'))
    OR (p.code = 'ADMIN_TECH' AND x.code IN ('AUDIT','ADM_PAR','ADM_TEC'))
    OR (p.code = 'DG'         AND x.code IN ('LEC','COT','VAL','STAT','CONF',
                                             'VUE_DG','COCKPIT','ACT_LEC','DEC','SCORE','DOS_LEC',
                                             'EXP_LEC'))
    OR (p.code = 'AGENT_SESS' AND x.code IN ('LEC','ENR','COT_DEL','TRANS','CLO','IMP','DOS_LEC'))
    OR (p.code = 'RESP'       AND x.code IN ('LEC','COT','AFF','VAL','TRANS','STAT',
                                             'ACT_LEC','ACT_SAI','SCORE',
                                             'DOS_LEC','DOS_INS','DOS_VAL'))
    OR (p.code = 'COLLAB'     AND x.code IN ('LEC','TRA','DOS_LEC','DOS_INS'))
    OR (p.code = 'ATT_DSR'    AND x.code IN ('LEC','REL','STAT','ACT_LEC','DEC','INST','DISPO','SCORE'))
    -- La DSR est autonome sur son dispositif : elle tient le referentiel des
    -- structures, le dictionnaire des indicateurs et le calendrier de
    -- production sans passer par l'administrateur fonctionnel.
    --
    -- Pas d'ADM_HAB en revanche : distribuer les profils et les perimetres
    -- releve du §3.9, et l'y ajouter la ferait basculer dans la zone
    -- d'administration, qui n'est pas son espace de travail.
    OR (p.code = 'DSR'        AND x.code IN ('LEC','REL','STAT','IMP','ADM_STR',
                                             'ACT_LEC','ACT_VAL','DEC','INST','DISPO',
                                             'SCORE','SCORE_ADM','COCKPIT','DOS_LEC'))
    -- SCORE_ADM : le §3.11 lui confie la contribution au dictionnaire des
    -- indicateurs et aux seuils d'alerte.
    OR (p.code = 'DCG'        AND x.code IN ('LEC','STAT','ACT_LEC','ACT_VAL','SCORE','SCORE_ADM'))
    -- Le descriptif (§3.12) lui donne l'historique d'un objet designe, sur
    -- autorisation : c'est AUDIT. Ni le registre, ni les statistiques.
    OR (p.code = 'AUDITEUR'   AND x.code IN ('AUDIT'))
    OR (p.code = 'CODIR'      AND x.code IN ('LEC','STAT','ACT_LEC','DEC','SCORE',
                                             'VUE_CODIR','COCKPIT','EXP_LEC'))
    -- Les structures d'exploitation saisissent ce qu'elles mesurent, et rien
    -- de plus : aucune ne porte EXP_LEC, donc aucune ne lit les chiffres des
    -- autres. C'est la regle de visibilite, tenue par le serveur.
    OR (p.code = 'EXPLOITATION' AND x.code IN ('LEC','COT','AFF','STAT','ACT_LEC',
                                               'ACT_SAI','SCORE','EXP_SAI'))
    OR (p.code = 'POINT_FOCAL'AND x.code IN ('LEC','ACT_LEC','ACT_SAI','DISPO'))
    OR (p.code = 'ARCHIVISTE' AND x.code IN ('LEC','ARCH','IMP'))
    OR (p.code = 'EXTERNE'    AND x.code IN ('EXT'));

-- ---------------------------------------------------------------------
--  Les deux circuits preconfigures, reproduisant le trajet decrit par
--  l'institution. L'application fonctionne des l'installation.
-- ---------------------------------------------------------------------
INSERT INTO circuit (code, libelle) VALUES
  ('ORDINAIRE',   'Circuit ordinaire'),
  ('CONFIDENTIEL','Circuit confidentiel');

INSERT INTO circuit_version (circuit_id, version, mode_cotation, publie_le, motif_modification)
SELECT id, 1, 'cascade', now(), 'Version initiale'
  FROM circuit WHERE code IN ('ORDINAIRE','CONFIDENTIEL');

INSERT INTO circuit_regle (circuit_id, confidentiel, priorite)
SELECT id, false, 100 FROM circuit WHERE code = 'ORDINAIRE';

INSERT INTO circuit_regle (circuit_id, confidentiel, priorite)
SELECT id, true, 10 FROM circuit WHERE code = 'CONFIDENTIEL';


-- =====================================================================
--  A FAIRE APRES L'INSTALLATION
--
--  1. Charger l'organigramme reel (table structure) - le document
--     n'a pas encore ete communique par l'institution.
--  2. Confronter les colonnes de courrier au registre papier vierge :
--     si la saisie est plus lente que le registre, l'application
--     sera abandonnee.
--  3. Charger le calendrier des jours feries (table jour_ferie).
--  4. Confirmer le format du numero : 0147/2026 est l'hypothese
--     retenue par le declencheur attribuer_numero().
--  5. Activer pg_stat_statements des le premier jour. Les problemes
--     de performance apparaissent au bout de dix-huit mois, quand
--     plus personne ne se souvient de la requete fautive.
--  6. Creer les partitions des annees suivantes avant leur echeance
--     (evenement, champ_historique) et des mois suivants
--     (journal_acces).
-- =====================================================================
