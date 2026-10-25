-- =====================================================================
--  Application de suivi des courriers et des activites
--  Domaine ACTIVITES - complement au script init_base.sql
--  PostgreSQL 16 ou superieur
--
--  Version 1 - 12 aout 2026
--
--  Ce fichier s'execute APRES init_base.sql, sur la meme base. Il ne
--  reprend rien de ce qui existe deja : le journal (evenement,
--  champ_historique), les pieces jointes, les relances, les structures
--  et les habilitations sont ceux du socle. C'est le meme systeme,
--  et non une seconde application posee a cote.
--
--  Origine des tables. Le document MODELE DE DONNEES v2 decrit dix
--  tables du domaine Activites, ecartees du premier livrable au motif
--  que « les modeliser plus avant sans disposer d'un plan d'actions
--  reel reviendrait a les refaire ». Elles sont ici reprises et
--  completees de ce que le cahier des charges (§15 a §20), le
--  descriptif fonctionnel et les ecrans deja maquettes exigent.
--
--  Ce que ce fichier ajoute au modele v2, et pourquoi :
--    * axe_strategique       - referentiel ferme communique le 11 aout
--                              2026 ; le §15 exigeait le rattachement
--                              sans jamais donner la liste
--    * activite_suspension   - le §19 fait de la suspension un etat
--                              motive et reversible, pas un simple
--                              effet de decision
--    * calendrier_production
--      et obligation         - le §3.3 du descriptif fonctionnel confie
--                              a la DSR « qui alimente quoi, a quelle
--                              frequence » ; les ecrans l'exigent
--    * relance.activite_id   - une relance reste une relance : la table
--                              du socle est etendue, pas dupliquee
--
--  Reserve. Le document « un PAA reel » n'a jamais ete communique
--  (decisions de cadrage, §6.2). Le niveau de detail retenu ici est
--  celui du cahier des charges ; il devra etre confronte a un plan
--  d'actions reel avant la premiere mise en service.
-- =====================================================================




-- =====================================================================
--  1. REFERENTIEL DU PLAN STRATEGIQUE
-- =====================================================================

-- ---------------------------------------------------------------------
--  axe_strategique
--  Referentiel FERME. Les trois axes ont ete arretes et communiques le
--  11 aout 2026. Un champ texte libre aurait produit quatre
--  orthographes pour un meme axe, et tout regroupement par axe -
--  c'est-a-dire la raison d'etre du rattachement - aurait ete faux.
--
--  La table existe malgre le petit nombre de lignes : le libelle
--  officiel est long, il s'affiche sur la fiche, et le jour ou le plan
--  strategique change, c'est une ligne et non une migration.
-- ---------------------------------------------------------------------
CREATE TABLE axe_strategique (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          TEXT        NOT NULL UNIQUE,
    libelle_court TEXT        NOT NULL,
    libelle       TEXT        NOT NULL,
    ordre         SMALLINT    NOT NULL,
    valide_du     DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au     DATE,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    CONSTRAINT axe_periode_valide CHECK (valide_au IS NULL OR valide_au >= valide_du)
);

COMMENT ON TABLE axe_strategique IS
  'Axes du plan strategique du Port autonome de Douala. Referentiel ferme, communique le 11 aout 2026.';
COMMENT ON COLUMN axe_strategique.libelle_court IS
  'Ce qui circule dans les listes et les regroupements. Le libelle complet ne s''affiche que sur la fiche et dans la liste deroulante.';


-- =====================================================================
--  2. EXERCICE ET PLAN D'ACTIONS ANNUEL
-- =====================================================================

-- ---------------------------------------------------------------------
--  exercice
--  L'annee de gestion. Table et non colonne : un exercice se clot, et
--  une fois clos plus aucune activite ne s'y ajoute. Sans cet etat, il
--  n'existe aucun moyen d'empecher la saisie retroactive dans une annee
--  dont les comptes sont rendus.
-- ---------------------------------------------------------------------
CREATE TABLE exercice (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    annee       SMALLINT    NOT NULL UNIQUE,
    ouvert      BOOLEAN     NOT NULL DEFAULT true,
    ouvert_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    clos_le     TIMESTAMPTZ,
    clos_par    BIGINT,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par    BIGINT,
    CONSTRAINT exercice_annee_plausible CHECK (annee BETWEEN 2020 AND 2100),
    CONSTRAINT exercice_cloture_coherente
      CHECK ((ouvert AND clos_le IS NULL) OR (NOT ouvert AND clos_le IS NOT NULL))
);

-- ---------------------------------------------------------------------
--  paa - plan d'actions annuel
--  Un plan par structure et par exercice. Le §15 le fait valider par la
--  Direction du Controle de Gestion.
--
--  Le statut porte quatre valeurs et non deux. Le MODELE DE DONNEES v2
--  prevoyait ('non_valide','valide') ; les ecrans exigent de distinguer
--  ce qui n'a pas encore ete soumis de ce qui attend le controle de
--  gestion, et de porter le motif d'un renvoi. Un plan renvoye sans
--  motif ne serait pas corrige, il serait resoumis a l'identique.
--
--  ATTENTION - le cycle lui-meme n'est pas arbitre. Le retour arriere,
--  l'avenant en cours d'annee et la modification d'un plan valide ne
--  sont decrits par aucun document. Voir docs/questions-ouvertes.md, A5.
-- ---------------------------------------------------------------------
CREATE TABLE paa (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid            UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    structure_id   BIGINT      NOT NULL REFERENCES structure(id),
    exercice_id    BIGINT      NOT NULL REFERENCES exercice(id),
    version        SMALLINT    NOT NULL DEFAULT 1,
    statut         TEXT        NOT NULL DEFAULT 'brouillon',
    soumis_le      TIMESTAMPTZ,
    soumis_par     BIGINT,
    valide_le      TIMESTAMPTZ,
    valide_par     BIGINT,
    motif_retour   TEXT,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    invalide_le    TIMESTAMPTZ,
    invalide_par   BIGINT,
    CONSTRAINT paa_unique_par_exercice UNIQUE (structure_id, exercice_id),
    CONSTRAINT paa_statut_valide
      CHECK (statut IN ('brouillon','soumis','valide','retourne')),
    -- Un plan valide sans validateur ni date ne prouve rien : la
    -- validation du controle de gestion est justement ce que le §15
    -- demande de tracer.
    CONSTRAINT paa_validation_complete
      CHECK (statut <> 'valide' OR (valide_le IS NOT NULL AND valide_par IS NOT NULL)),
    CONSTRAINT paa_retour_motive
      CHECK (statut <> 'retourne' OR motif_retour IS NOT NULL),
    CONSTRAINT paa_soumission_datee
      CHECK (statut NOT IN ('soumis','valide') OR soumis_le IS NOT NULL)
);
CREATE INDEX paa_structure ON paa (structure_id, exercice_id);
-- Corbeille du controle de gestion : les plans qui l'attendent, et eux
-- seuls. Index partiel, car ils sont une poignee sur plusieurs annees.
CREATE INDEX paa_a_valider ON paa (soumis_le) WHERE statut = 'soumis';

COMMENT ON COLUMN paa.motif_retour IS
  'Obligatoire au renvoi. Un plan renvoye sans motif est resoumis a l''identique.';

-- ---------------------------------------------------------------------
--  paa_version
--  L'historique des soumissions successives. Le champ_historique dit
--  quelle colonne a change ; celle-ci dit pourquoi une version entiere
--  a ete refaite, et c'est ce que lit un controleur de gestion.
-- ---------------------------------------------------------------------
CREATE TABLE paa_version (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paa_id     BIGINT      NOT NULL REFERENCES paa(id) ON DELETE CASCADE,
    version    SMALLINT    NOT NULL,
    statut     TEXT        NOT NULL,
    motif      TEXT,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par   BIGINT,
    UNIQUE (paa_id, version)
);


-- =====================================================================
--  3. ACTIVITE
-- =====================================================================

-- ---------------------------------------------------------------------
--  activite
--  Le §15 enumere ce qu'une activite comprend : objectif, etat de
--  reference, indicateurs, resultats attendus, taches, budget valide,
--  responsable, periode d'execution, cible, niveau d'avancement. Toutes
--  ces colonnes en decoulent, une a une.
--
--  La structure porteuse n'est PAS une colonne : elle vient du plan
--  (paa.structure_id). La dupliquer ici ferait exister deux verites,
--  et c'est la visibilite de l'activite qui en depend.
--
--  budget_valide / budget_consomme sont modelises mais sans ecran de
--  suivi : decision de cadrage D8, « le suivi budgetaire sort du
--  perimetre de la V1, les montants restent modelisables ». La colonne
--  budget_consomme n'a pas de source determinee - saisie ou reprise
--  depuis le systeme financier reste a trancher.
--
--  avancement_calcule est stocke bien qu'il soit calcule, conformement
--  a l'arbitrage n° 1 : il est recalcule a chaque changement d'etat de
--  tache par le declencheur maj_avancement_activite(), puis lu tel
--  quel. Le recalculer a l'affichage obligerait a parcourir toutes les
--  taches de toutes les activites a chaque ouverture d'un tableau de
--  bord.
--
--  Le RETARD N'EST PAS STOCKE, conformement a l'arbitrage n° 2 : une
--  activite est en retard lorsque date_fin < date du jour et que l'etat
--  n'est pas realisee. Voir la vue v_activite_etat et l'index partiel
--  activite_retard.
-- ---------------------------------------------------------------------
CREATE TABLE activite (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid                UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    paa_id             BIGINT      NOT NULL REFERENCES paa(id),
    axe_strategique_id BIGINT      NOT NULL REFERENCES axe_strategique(id),
    code               TEXT        NOT NULL UNIQUE,
    intitule           TEXT        NOT NULL,
    objectif           TEXT,
    etat_reference     TEXT,
    resultats_attendus TEXT,
    cible              TEXT,
    budget_valide      NUMERIC(18,2),
    budget_consomme    NUMERIC(18,2),
    responsable_id     BIGINT      NOT NULL REFERENCES utilisateur(id),
    date_debut         DATE        NOT NULL,
    date_fin           DATE        NOT NULL,
    etat               TEXT        NOT NULL DEFAULT 'en_cours',
    avancement_calcule NUMERIC(5,2) NOT NULL DEFAULT 0,
    derniere_relance_le TIMESTAMPTZ,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par           BIGINT,
    modifie_le         TIMESTAMPTZ,
    modifie_par        BIGINT,
    invalide_le        TIMESTAMPTZ,
    invalide_par       BIGINT,
    CONSTRAINT activite_periode_valide CHECK (date_fin >= date_debut),
    CONSTRAINT activite_etat_valide
      CHECK (etat IN ('en_cours','realisee','suspendue')),
    CONSTRAINT activite_avancement_borne
      CHECK (avancement_calcule BETWEEN 0 AND 100),
    CONSTRAINT activite_budget_positif
      CHECK (budget_valide IS NULL OR budget_valide >= 0)
);
CREATE INDEX activite_paa          ON activite (paa_id, etat);
CREATE INDEX activite_responsable  ON activite (responsable_id);
CREATE INDEX activite_axe          ON activite (axe_strategique_id);

-- Les activites en retard, selon l'arbitrage n° 2. L'index partiel
-- exclut les activites realisees, qui forment la majorite du volume
-- passe la premiere annee.
CREATE INDEX activite_retard
    ON activite (date_fin)
    WHERE etat <> 'realisee' AND invalide_le IS NULL;

COMMENT ON TABLE activite IS
  'Action inscrite au plan d''actions annuel d''une structure - cahier des charges §15.';
COMMENT ON COLUMN activite.code IS
  'Reference lisible, attribuee par le declencheur : PAA-<code structure>-<numero>. Jamais saisie.';
COMMENT ON COLUMN activite.avancement_calcule IS
  'Calcule depuis les taches, pondere par tache.poids. Stocke pour ne pas reparcourir les taches a chaque tableau de bord (arbitrage n° 1).';
COMMENT ON COLUMN activite.budget_consomme IS
  'Source non determinee : saisie ou reprise depuis le systeme financier. Aucun ecran de suivi en V1 (decision D8).';
COMMENT ON COLUMN activite.etat IS
  'Trois etats stockes. « En retard » et « Programmee » se deduisent des dates : voir v_activite_etat.';


-- =====================================================================
--  4. INDICATEURS ET MESURES
-- =====================================================================

-- ---------------------------------------------------------------------
--  activite_indicateur
--  Ce que l'activite promet de faire bouger. La valeur de reference est
--  le point de depart constate, la cible le point d'arrivee vise.
--
--  Les deux sont NUMERIC et non TEXT : sans cela, aucun taux d'atteinte
--  n'est calculable, et le §16 comme le §20 en demandent un.
--  Consequence assumee : un indicateur non chiffrable ne se modelise
--  pas ici.
-- ---------------------------------------------------------------------
CREATE TABLE activite_indicateur (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_id      BIGINT      NOT NULL REFERENCES activite(id) ON DELETE CASCADE,
    libelle          TEXT        NOT NULL,
    unite            TEXT,
    valeur_reference NUMERIC(18,4),
    valeur_cible     NUMERIC(18,4) NOT NULL,
    -- Vrai lorsque atteindre la cible signifie DESCENDRE : un delai, un
    -- taux d'erreur, un encours. Sans cette colonne, le taux d'atteinte
    -- d'un indicateur decroissant est faux sans que rien ne le signale.
    sens_decroissant BOOLEAN     NOT NULL DEFAULT false,
    ordre            SMALLINT    NOT NULL DEFAULT 1,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par         BIGINT,
    modifie_le       TIMESTAMPTZ,
    modifie_par      BIGINT,
    invalide_le      TIMESTAMPTZ,
    invalide_par     BIGINT
);
CREATE INDEX activite_indicateur_activite ON activite_indicateur (activite_id);

COMMENT ON COLUMN activite_indicateur.sens_decroissant IS
  'Ajout au modele v2. La formule du taux d''atteinte n''est pas arbitree (questions-ouvertes A4) ; sans ce drapeau, elle serait fausse pour tout indicateur a reduire.';

-- ---------------------------------------------------------------------
--  indicateur_mesure
--  Un releve date. On n'ecrase jamais la valeur precedente : la suite
--  des mesures est ce qui montre une progression, et le §16 demande le
--  niveau d'execution, pas seulement le dernier chiffre.
-- ---------------------------------------------------------------------
CREATE TABLE indicateur_mesure (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_indicateur_id BIGINT      NOT NULL
                                       REFERENCES activite_indicateur(id) ON DELETE CASCADE,
    date_mesure            DATE        NOT NULL DEFAULT CURRENT_DATE,
    valeur_atteinte        NUMERIC(18,4) NOT NULL,
    commentaire            TEXT,
    saisie_par             BIGINT      NOT NULL REFERENCES utilisateur(id),
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (activite_indicateur_id, date_mesure)
);
CREATE INDEX indicateur_mesure_indicateur
    ON indicateur_mesure (activite_indicateur_id, date_mesure DESC);

COMMENT ON CONSTRAINT indicateur_mesure_activite_indicateur_id_date_mesure_key
    ON indicateur_mesure IS
  'Un seul releve par jour et par indicateur. Deux releves le meme jour signifient une correction : elle remplace, elle ne s''ajoute pas.';


-- =====================================================================
--  5. TACHES
-- =====================================================================

-- ---------------------------------------------------------------------
--  tache
--  Le §15 les nomme « taches a realiser ». Elles portent l'avancement :
--  c'est leur etat qui alimente activite.avancement_calcule.
--
--  poids permet a une tache de peser plus qu'une autre. Sans lui,
--  « rediger le compte rendu » compterait autant que « livrer le
--  systeme », et l'avancement ne voudrait rien dire.
-- ---------------------------------------------------------------------
CREATE TABLE tache (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_id    BIGINT      NOT NULL REFERENCES activite(id) ON DELETE CASCADE,
    intitule       TEXT        NOT NULL,
    responsable_id BIGINT      REFERENCES utilisateur(id),
    date_echeance  DATE,
    poids          SMALLINT    NOT NULL DEFAULT 1,
    etat           TEXT        NOT NULL DEFAULT 'a_faire',
    fait_le        DATE,
    ordre          SMALLINT    NOT NULL DEFAULT 1,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    invalide_le    TIMESTAMPTZ,
    invalide_par   BIGINT,
    CONSTRAINT tache_etat_valide CHECK (etat IN ('a_faire','en_cours','faite')),
    CONSTRAINT tache_poids_positif CHECK (poids > 0),
    CONSTRAINT tache_faite_datee
      CHECK ((etat = 'faite' AND fait_le IS NOT NULL) OR (etat <> 'faite' AND fait_le IS NULL))
);
CREATE INDEX tache_activite ON tache (activite_id, etat);
-- Les taches echues non faites : c'est l'une des deux contraintes qui
-- rendent une activite critique au tableau de bord du DG (§20).
CREATE INDEX tache_echue
    ON tache (date_echeance)
    WHERE etat <> 'faite' AND invalide_le IS NULL;


-- =====================================================================
--  6. INSTRUCTIONS ET DECISIONS
-- =====================================================================

-- ---------------------------------------------------------------------
--  decision_reunion
--  Le §19 : les rapports d'activites et les reunions de coordination
--  engendrent des decisions du Directeur General. Elles sont
--  historisees, et leurs effets aussi.
-- ---------------------------------------------------------------------
CREATE TABLE decision_reunion (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reference     TEXT        UNIQUE,
    reunion_date  DATE        NOT NULL,
    objet         TEXT        NOT NULL,
    texte         TEXT,
    prise_par     BIGINT      NOT NULL REFERENCES utilisateur(id),
    saisie_par    BIGINT      NOT NULL REFERENCES utilisateur(id),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT
);
CREATE INDEX decision_reunion_date ON decision_reunion (reunion_date DESC);

COMMENT ON COLUMN decision_reunion.prise_par IS
  'L''autorite qui decide. Ne jamais confondre avec saisie_par, l''agent qui consigne - meme regle que cotation.decide_par.';

-- ---------------------------------------------------------------------
--  instruction_activite
--  Le §17 exige quatre attributs pour une instruction verbale du
--  Directeur General : l'activite, la date, le responsable, le delai.
--  Une instruction est donc un engagement date, pas un commentaire.
--
--  D'ou la levee : tant que levee_le est NULL, l'instruction pese. Une
--  instruction echue et non levee est l'une des deux contraintes qui
--  rendent une activite critique (§20).
--
--  Le §19 ajoute les decisions du DG. Meme forme, meme suivi : une
--  colonne origine les distingue plutot que deux tables jumelles.
-- ---------------------------------------------------------------------
CREATE TABLE instruction_activite (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_id         BIGINT      NOT NULL REFERENCES activite(id) ON DELETE CASCADE,
    origine             TEXT        NOT NULL DEFAULT 'instruction_verbale',
    decision_reunion_id BIGINT      REFERENCES decision_reunion(id),
    date_instruction    DATE        NOT NULL DEFAULT CURRENT_DATE,
    texte               TEXT        NOT NULL,
    responsable_id      BIGINT      NOT NULL REFERENCES utilisateur(id),
    echeance            DATE        NOT NULL,
    donnee_par          BIGINT      REFERENCES utilisateur(id),
    enregistree_par     BIGINT      NOT NULL REFERENCES utilisateur(id),
    levee_le            TIMESTAMPTZ,
    levee_par           BIGINT      REFERENCES utilisateur(id),
    commentaire_levee   TEXT,
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par            BIGINT,
    modifie_le          TIMESTAMPTZ,
    modifie_par         BIGINT,
    invalide_le         TIMESTAMPTZ,
    invalide_par        BIGINT,
    CONSTRAINT instruction_origine_valide
      CHECK (origine IN ('instruction_verbale','decision_dg')),
    CONSTRAINT instruction_levee_complete
      CHECK ((levee_le IS NULL AND levee_par IS NULL)
          OR (levee_le IS NOT NULL AND levee_par IS NOT NULL)),
    -- Une decision du DG sans decision de reunion rattachee est
    -- possible (instruction directe), mais l'inverse ne l'est pas :
    -- une instruction verbale ne nait pas d'une reunion.
    CONSTRAINT instruction_reference_coherente
      CHECK (decision_reunion_id IS NULL OR origine = 'decision_dg')
);
CREATE INDEX instruction_activite_activite ON instruction_activite (activite_id);
-- Les instructions qui pesent encore, echeance en tete. C'est la
-- requete du tableau de bord et celle du calcul de criticite.
CREATE INDEX instruction_activite_en_cours
    ON instruction_activite (echeance)
    WHERE levee_le IS NULL AND invalide_le IS NULL;

-- ---------------------------------------------------------------------
--  decision_effet
--  Le §19 enumere ce qu'une decision peut faire : modifier le planning,
--  modifier les priorites, accelerer une activite, suspendre une
--  activite, creer de nouvelles taches.
--
--  valeur_avant / valeur_apres conservent l'etat de part et d'autre, ce
--  qui permet de reconstituer le plan d'actions dans sa forme d'origine
--  malgre les decisions successives. Sans elles, on saurait qu'une
--  decision a ete prise, jamais ce qu'elle a change.
-- ---------------------------------------------------------------------
CREATE TABLE decision_effet (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_reunion_id BIGINT      NOT NULL REFERENCES decision_reunion(id) ON DELETE CASCADE,
    activite_id         BIGINT      REFERENCES activite(id),
    tache_id            BIGINT      REFERENCES tache(id),
    nature              TEXT        NOT NULL,
    valeur_avant        JSONB,
    valeur_apres        JSONB,
    applique_le         TIMESTAMPTZ,
    applique_par        BIGINT      REFERENCES utilisateur(id),
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par            BIGINT,
    CONSTRAINT decision_effet_nature_valide
      CHECK (nature IN ('planning','priorite','acceleration','suspension','creation_tache')),
    CONSTRAINT decision_effet_cible
      CHECK (activite_id IS NOT NULL OR tache_id IS NOT NULL)
);
CREATE INDEX decision_effet_decision ON decision_effet (decision_reunion_id);
CREATE INDEX decision_effet_activite ON decision_effet (activite_id);


-- =====================================================================
--  7. SUSPENSION
-- =====================================================================

-- ---------------------------------------------------------------------
--  activite_suspension
--  Ajout au modele v2, qui ne portait la suspension que comme un effet
--  de decision. Or le §19 en fait un ETAT : une activite suspendue
--  n'accepte plus de declaration d'avancement, et elle reprend. Il faut
--  donc savoir depuis quand, sur quel motif, et par qui - et pouvoir
--  lever la suspension sans effacer qu'elle a eu lieu.
--
--  La reference a une decision est facultative : une suspension peut
--  etre prononcee hors reunion.
-- ---------------------------------------------------------------------
CREATE TABLE activite_suspension (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activite_id         BIGINT      NOT NULL REFERENCES activite(id) ON DELETE CASCADE,
    decision_reunion_id BIGINT      REFERENCES decision_reunion(id),
    motif               TEXT        NOT NULL,
    suspendu_le         TIMESTAMPTZ NOT NULL DEFAULT now(),
    suspendu_par        BIGINT      NOT NULL REFERENCES utilisateur(id),
    repris_le           TIMESTAMPTZ,
    repris_par          BIGINT      REFERENCES utilisateur(id),
    motif_reprise       TEXT,
    CONSTRAINT suspension_reprise_complete
      CHECK ((repris_le IS NULL AND repris_par IS NULL)
          OR (repris_le IS NOT NULL AND repris_par IS NOT NULL)),
    CONSTRAINT suspension_reprise_posterieure
      CHECK (repris_le IS NULL OR repris_le >= suspendu_le)
);
-- Une seule suspension en cours a la fois. La contrainte est posee au
-- niveau du moteur : deux suspensions ouvertes rendraient la reprise
-- ambigue, et aucun code applicatif ne tient cette garantie sous
-- concurrence.
CREATE UNIQUE INDEX activite_suspension_unique_en_cours
    ON activite_suspension (activite_id) WHERE repris_le IS NULL;


-- =====================================================================
--  8. CALENDRIER DE PRODUCTION ET OBLIGATIONS
--  Descriptif fonctionnel §3.3 : la DSR decide « qui alimente quoi, a
--  quelle frequence ». Sans ce calendrier, chaque ecran redecrit la
--  meme regle de son cote et les deux finissent par diverger.
-- =====================================================================

CREATE TABLE calendrier_production (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    structure_id  BIGINT      NOT NULL REFERENCES structure(id),
    nature        TEXT        NOT NULL,
    intitule      TEXT        NOT NULL,
    periodicite   TEXT        NOT NULL,
    -- Jour de la periode SUIVANTE ou le depot est attendu : le rapport
    -- de juillet est du le 5 aout.
    jour_echeance SMALLINT    NOT NULL DEFAULT 5,
    actif         BOOLEAN     NOT NULL DEFAULT true,
    valide_du     DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au     DATE,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    CONSTRAINT calendrier_nature_valide
      CHECK (nature IN ('rapport_mensuel','proces_verbal','rapport_sectoriel')),
    CONSTRAINT calendrier_periodicite_valide
      CHECK (periodicite IN ('mensuelle','trimestrielle','semestrielle','annuelle')),
    CONSTRAINT calendrier_jour_valide CHECK (jour_echeance BETWEEN 1 AND 28)
);
CREATE INDEX calendrier_production_structure
    ON calendrier_production (structure_id) WHERE actif;

-- ---------------------------------------------------------------------
--  obligation
--  L'occurrence : ce que telle structure doit deposer pour telle
--  periode. Engendree depuis le calendrier, jamais saisie a la main -
--  sinon une structure qui ne cree pas son obligation n'est jamais en
--  retard, ce qui est exactement l'inverse du but.
--
--  Le retard n'est pas stocke, par coherence avec l'arbitrage n° 2 :
--  une obligation est en retard quand echeance < aujourd'hui et
--  depose_le est NULL.
-- ---------------------------------------------------------------------
CREATE TABLE obligation (
    id                      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    calendrier_production_id BIGINT     NOT NULL REFERENCES calendrier_production(id),
    structure_id            BIGINT      NOT NULL REFERENCES structure(id),
    intitule                TEXT        NOT NULL,
    periode_libelle         TEXT        NOT NULL,
    periode_debut           DATE        NOT NULL,
    periode_fin             DATE        NOT NULL,
    echeance                DATE        NOT NULL,
    depose_le               DATE,
    depose_par              BIGINT      REFERENCES utilisateur(id),
    piece_jointe_id         BIGINT      REFERENCES piece_jointe(id),
    commentaire             TEXT,
    cree_le                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT obligation_periode_valide CHECK (periode_fin >= periode_debut),
    CONSTRAINT obligation_unique_par_periode
      UNIQUE (calendrier_production_id, periode_debut),
    CONSTRAINT obligation_depot_complet
      CHECK ((depose_le IS NULL AND depose_par IS NULL)
          OR (depose_le IS NOT NULL AND depose_par IS NOT NULL))
);
CREATE INDEX obligation_structure ON obligation (structure_id, echeance DESC);
CREATE INDEX obligation_en_retard
    ON obligation (echeance) WHERE depose_le IS NULL;


-- =====================================================================
--  9. EXTENSIONS DES TABLES DU SOCLE
--  Le domaine Activites n'a pas ses propres relances ni ses propres
--  pieces jointes : c'est la meme application.
-- =====================================================================

-- Une relance reste une relance : meme table, meme registre, meme
-- notion d'emetteur et de destinataire. Seule la cible change.
ALTER TABLE relance ADD COLUMN activite_id BIGINT REFERENCES activite(id);
CREATE INDEX relance_activite ON relance (activite_id, emise_le DESC);

-- La table portait implicitement l'idee qu'une relance vise un
-- courrier. Maintenant qu'elle peut viser une activite, l'absence des
-- deux devient une ligne orpheline qu'aucun ecran ne montrera jamais.
ALTER TABLE relance ADD CONSTRAINT relance_a_une_cible
    CHECK (courrier_id IS NOT NULL OR activite_id IS NOT NULL);

COMMENT ON COLUMN relance.activite_id IS
  'Relance d''une structure en retard sur une activite - §16 et descriptif fonctionnel §3.3 (DSR).';

-- Les pieces jointes d'une activite passent par les colonnes
-- generiques objet_type / objet_id ajoutees au socle. Rien a creer
-- ici : une seconde table de pieces aurait fait diverger l'empreinte,
-- le versionnement et la reconnaissance optique.


-- =====================================================================
--  10. VUE DE L'ETAT AFFICHE
--  Trois etats sont stockes, cinq sont affiches. Les deux autres se
--  deduisent des dates, conformement a l'arbitrage n° 2 : les stocker
--  imposerait de reecrire toutes les lignes chaque nuit pour un
--  resultat que la date donne deja.
-- =====================================================================

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
  'Etat affiche et contrainte echue. La criticite du §20 se lit ici : etat_affiche = ''en_retard'' ET contrainte_echue.';


-- =====================================================================
--  11. AGREGATS PRE-CALCULES
--  Meme regle que pour le courrier : le tableau de bord du Directeur
--  General (§20) n'agrege jamais la table des activites a la volee.
-- =====================================================================

CREATE TABLE agregat_activite_jour (
    structure_id      BIGINT      NOT NULL REFERENCES structure(id),
    exercice_id       BIGINT      NOT NULL REFERENCES exercice(id),
    jour              DATE        NOT NULL,
    nb_total          INTEGER     NOT NULL DEFAULT 0,
    nb_realisees      INTEGER     NOT NULL DEFAULT 0,
    nb_en_cours       INTEGER     NOT NULL DEFAULT 0,
    nb_en_retard      INTEGER     NOT NULL DEFAULT 0,
    nb_suspendues     INTEGER     NOT NULL DEFAULT 0,
    nb_critiques      INTEGER     NOT NULL DEFAULT 0,
    taux_execution    NUMERIC(5,2),
    budget_valide     NUMERIC(18,2),
    budget_consomme   NUMERIC(18,2),
    calcule_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (structure_id, exercice_id, jour)
);

COMMENT ON TABLE agregat_activite_jour IS
  'Alimente par tache planifiee nocturne. Le retard evolue avec le temps sans qu''aucune ecriture ne survienne : sans ce recalcul, seules les activites touchees paraissent en retard.';


-- =====================================================================
--  12. DECLENCHEURS
-- =====================================================================

-- ---------------------------------------------------------------------
--  Reference lisible de l'activite : PAA-<code structure>-<numero>,
--  numerote par plan. Jamais saisie, comme le numero du courrier.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION attribuer_code_activite() RETURNS TRIGGER AS $$
DECLARE
    v_code_structure TEXT;
    v_numero         INTEGER;
BEGIN
    IF NEW.code IS NOT NULL AND NEW.code <> '' THEN
        RETURN NEW;
    END IF;

    -- Le verrou de ligne sur le plan serialise les insertions
    -- concurrentes dans un meme plan. Sans lui, deux points focaux
    -- saisissant en meme temps obtiendraient le meme numero.
    SELECT s.code INTO v_code_structure
      FROM paa p
      JOIN structure s ON s.id = p.structure_id
     WHERE p.id = NEW.paa_id
       FOR UPDATE OF p;

    SELECT COALESCE(MAX(substring(code FROM '[0-9]+$')::INTEGER), 0) + 1
      INTO v_numero
      FROM activite
     WHERE paa_id = NEW.paa_id;

    NEW.code := 'PAA-' || v_code_structure || '-' || lpad(v_numero::TEXT, 2, '0');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER activite_code
    BEFORE INSERT ON activite
    FOR EACH ROW EXECUTE FUNCTION attribuer_code_activite();

-- ---------------------------------------------------------------------
--  Avancement calcule - arbitrage n° 1.
--  Recalcule a chaque changement d'etat de tache, pondere par le poids.
--  Une activite sans tache reste a l'avancement qu'elle porte : c'est
--  le seul cas ou la structure le declare directement.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_avancement_activite() RETURNS TRIGGER AS $$
DECLARE
    v_activite BIGINT := COALESCE(NEW.activite_id, OLD.activite_id);
    v_total    INTEGER;
    v_faites   INTEGER;
BEGIN
    SELECT COALESCE(SUM(poids), 0),
           COALESCE(SUM(poids) FILTER (WHERE etat = 'faite'), 0)
      INTO v_total, v_faites
      FROM tache
     WHERE activite_id = v_activite AND invalide_le IS NULL;

    IF v_total = 0 THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    -- La clause finale evite de reecrire la ligne quand l'avancement ne
    -- change pas : sans elle, chaque enregistrement de tache
    -- declencherait l'historisation complete de l'activite pour un
    -- resultat identique. Meme precaution que maj_chef_de_file().
    UPDATE activite
       SET avancement_calcule = round(100.0 * v_faites / v_total, 2)
     WHERE id = v_activite
       AND avancement_calcule IS DISTINCT FROM round(100.0 * v_faites / v_total, 2);

    RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;

CREATE TRIGGER tache_avancement
    AFTER INSERT OR UPDATE OR DELETE ON tache
    FOR EACH ROW EXECUTE FUNCTION maj_avancement_activite();

-- ---------------------------------------------------------------------
--  Une activite suspendue n'accepte plus de declaration d'avancement.
--  La regle est posee au niveau du moteur et non dans le code : c'est
--  la seule facon qu'elle tienne aussi pour une reprise de donnees ou
--  une correction faite en SQL direct.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION refuser_avancement_si_suspendue() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.etat = 'suspendue'
       AND NEW.avancement_calcule IS DISTINCT FROM OLD.avancement_calcule THEN
        RAISE EXCEPTION
            'Activite % suspendue : l''avancement ne peut pas etre modifie tant que la suspension n''est pas levee.',
            OLD.code
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER activite_avancement_suspendue
    BEFORE UPDATE ON activite
    FOR EACH ROW EXECUTE FUNCTION refuser_avancement_si_suspendue();

-- ---------------------------------------------------------------------
--  Coherence entre l'etat de l'activite et la table de suspension.
--
--  Sans ce declencheur, le meme fait est ecrit a deux endroits :
--  activite.etat = 'suspendue' et une ligne ouverte dans
--  activite_suspension. Ils divergent au premier oubli, et rien ne le
--  signale - un essai sur base neuve a produit une activite portant une
--  suspension ouverte et l'etat « en cours ».
--
--  La suspension est donc la source : on l'inscrit, l'etat suit. Le
--  code applicatif ne doit jamais ecrire activite.etat = 'suspendue'
--  directement.
--
--  A la reprise, l'etat revient a « en cours » et non a ce qu'il etait
--  avant : une activite qu'on reprend n'est, par definition, pas
--  realisee.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_etat_suspension() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.repris_le IS NULL THEN
        UPDATE activite SET etat = 'suspendue'
         WHERE id = NEW.activite_id AND etat <> 'suspendue';

    ELSIF TG_OP = 'UPDATE'
          AND OLD.repris_le IS NULL AND NEW.repris_le IS NOT NULL THEN
        UPDATE activite SET etat = 'en_cours'
         WHERE id = NEW.activite_id AND etat = 'suspendue';
    END IF;

    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER activite_suspension_etat
    AFTER INSERT OR UPDATE ON activite_suspension
    FOR EACH ROW EXECUTE FUNCTION maj_etat_suspension();

-- ---------------------------------------------------------------------
--  Historisation des champs, par le meme declencheur que le courrier.
--  Rappel : l'application doit positionner SET LOCAL app.utilisateur_id
--  au debut de chaque transaction, faute de quoi l'ecriture est
--  refusee. Un traitement legitimement non nominatif declare
--  SET LOCAL app.contexte = 'batch'.
-- ---------------------------------------------------------------------
CREATE TRIGGER activite_historique
    AFTER UPDATE ON activite
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER paa_historique
    AFTER UPDATE ON paa
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER tache_historique
    AFTER UPDATE ON tache
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER instruction_activite_historique
    AFTER UPDATE ON instruction_activite
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();


-- =====================================================================
--  13. CLES ETRANGERES DIFFEREES
--  Les colonnes systematiques referencent utilisateur(id). Meme
--  mecanisme que la section 8 d'init_base.sql.
-- =====================================================================

DO $$
DECLARE
    t TEXT;
    c TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'axe_strategique','exercice','paa','paa_version','activite',
        'activite_indicateur','tache','decision_reunion',
        'instruction_activite','decision_effet','calendrier_production'
    ] LOOP
        FOREACH c IN ARRAY ARRAY[
            'cree_par','modifie_par','invalide_par','clos_par',
            'soumis_par','valide_par'
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
--  14. DONNEES INITIALES
-- =====================================================================

-- Les trois axes du plan strategique. Referentiel ferme, communique
-- par la Direction generale le 11 aout 2026.
INSERT INTO axe_strategique (code, libelle_court, libelle, ordre) VALUES
  ('A1', 'Port attractif et performant',
   'Port attractif et performant a l''aide des services surs et de qualite', 1),
  ('A2', 'Port competitif et fluide',
   'Port competitif par la fluidite du passage portuaire a travers l''amelioration et la densification de l''outil de production', 2),
  ('A3', 'Port innovant et responsable',
   'Port innovant, digital et societalement responsable', 3)
ON CONFLICT (code) DO NOTHING;

-- L'exercice en cours. Les suivants s'ouvrent par l'ecran
-- d'administration ; celui-ci existe pour que la base soit utilisable
-- des la premiere connexion.
INSERT INTO exercice (annee, ouvert)
VALUES (EXTRACT(YEAR FROM CURRENT_DATE)::SMALLINT, true)
ON CONFLICT (annee) DO NOTHING;



-- =====================================================================
--  A FAIRE APRES L'INSTALLATION
--
--  1. Confronter ces tables a un PLAN D'ACTIONS ANNUEL REEL. Le
--     document n'a jamais ete communique (decisions de cadrage, §6.2) :
--     « sans lui, le module Activites reste concu a l'aveugle ». Le
--     niveau de detail retenu ici vient du seul cahier des charges.
--
--  2. Faire trancher les regles de gestion qui n'ont pas de source.
--     Elles sont dans la table parametre avec statut = 'hypothese', et
--     detaillees dans docs/questions-ouvertes.md :
--       - le cycle du plan d'actions : retour arriere, avenant en cours
--         d'annee, modification d'un plan valide (A5) ;
--       - la formule du taux d'atteinte d'un indicateur (A4). Huit des
--         dix indicateurs du programme restent sans formule, de l'aveu
--         meme du BRD §9.
--
--  3. Arbitrer la definition du retard. Deux regles coexistent
--     aujourd'hui : l'arbitrage n° 2 (date_fin depassee, etat non
--     realisee), applique ici et par la vue v_activite_etat ; et
--     l'ecart a un avancement attendu, applique par les ecrans. Elles
--     ne designent pas les memes activites. Tant que ce n'est pas
--     tranche, deux ecrans afficheront deux chiffres.
--
--  4. Charger le calendrier de production de la DSR
--     (calendrier_production) : sans lui, aucune obligation n'est
--     engendree et aucune structure n'est jamais en retard.
--
--  5. Planifier les deux taches nocturnes :
--       - engendrement des obligations de la periode suivante ;
--       - recalcul de agregat_activite_jour. Le retard evolue avec le
--         temps sans qu'aucune ecriture ne survienne ; sans ce
--         recalcul, seules les activites que quelqu'un a touchees
--         paraissent en retard.
--
--  6. Ouvrir l'exercice suivant avant le 1er janvier.
-- =====================================================================
