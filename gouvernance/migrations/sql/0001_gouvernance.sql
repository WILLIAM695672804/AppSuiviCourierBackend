-- =====================================================================
--  Application de suivi des courriers et des activites
--  Domaine GOUVERNANCE — le dispositif de la DSR
--  PostgreSQL 16 ou superieur
--
--  Version 1 — 12 aout 2026
--
--  S'execute apres init_base.sql et init_activite.sql, sur la meme base.
--
--  Source : descriptif fonctionnel §3.3, qui confie a la Direction du
--  Suivi et des Relations cinq charges distinctes :
--
--    * le suivi des decisions des instances jusqu'a leur execution ;
--    * le secretariat et la conservation des reunions et rapports ;
--    * la disponibilite des hauts responsables — une decision confiee a
--      un directeur en mission n'avancera pas ;
--    * la preparation des sessions des organes de gestion des filiales
--      et succursales, et le suivi de leurs prescriptions ;
--    * la representation du PAD dans les organisations exterieures, et
--      la mise en oeuvre de leurs avis et recommandations.
--
--  Plus une sixieme, distincte du registre de disponibilite : le projet
--  de planning des conges annuels des directeurs et du Cabinet.
--
--  DECISION STRUCTURANTE — ADR 006. Decision d'instance, prescription de
--  filiale et recommandation externe sont UN SEUL objet, `engagement`,
--  distingue par sa colonne `origine`. Ce sont les memes champs et le
--  meme suivi ; trois tables jumelles auraient triple chaque regle.
--
--  La table est obtenue en renommant `decision_reunion`, livree avec le
--  pilier activites : une decision du CODIR qui suspend une activite
--  reste ainsi la MEME ligne que celle que la gouvernance suit.
-- =====================================================================


-- =====================================================================
--  1. SEANCES — reunions, sessions, rapports
--  §3.3 : « assurer le secretariat des reunions et la conservation des
--  comptes rendus ». D'ou l'echeance de depot : un compte rendu rendu
--  trois mois plus tard ne sert plus a personne.
-- =====================================================================

CREATE TABLE seance (
    id                BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid               UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    reference         TEXT        NOT NULL UNIQUE,
    type_seance       TEXT        NOT NULL,
    intitule          TEXT        NOT NULL,
    date_seance       DATE        NOT NULL,
    president_id      BIGINT      REFERENCES utilisateur(id),
    -- La structure organisatrice. Elle borne la visibilite de la seance,
    -- comme le plan borne celle d'une activite.
    structure_id      BIGINT      NOT NULL REFERENCES structure(id),
    -- Le depot n'est pas un booleen : c'est une date attendue et une date
    -- constatee. « Hors delai » se deduit des deux, jamais ne se stocke —
    -- meme raison que pour le retard d'une activite (arbitrage n° 2).
    echeance_depot    DATE        NOT NULL,
    cree_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par          BIGINT,
    modifie_le        TIMESTAMPTZ,
    modifie_par       BIGINT,
    invalide_le       TIMESTAMPTZ,
    invalide_par      BIGINT,
    CONSTRAINT seance_type_valide CHECK (type_seance IN (
        'reunion_dg','session_ca','assemblee_generale','codir',
        'rapport_activite','rapport_sectoriel')),
    CONSTRAINT seance_depot_apres_seance CHECK (echeance_depot >= date_seance)
);
CREATE INDEX seance_date ON seance (date_seance DESC);
CREATE INDEX seance_structure ON seance (structure_id, date_seance DESC);

COMMENT ON TABLE seance IS
  'Reunions, sessions et rapports dont la DSR tient le secretariat — descriptif fonctionnel §3.3.';
COMMENT ON COLUMN seance.echeance_depot IS
  'Date a laquelle le compte rendu est attendu. « Hors delai » se deduit, ne se stocke pas.';

-- ---------------------------------------------------------------------
--  seance_point — l'ordre du jour
-- ---------------------------------------------------------------------
CREATE TABLE seance_point (
    id            BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seance_id     BIGINT   NOT NULL REFERENCES seance(id) ON DELETE CASCADE,
    rang          SMALLINT NOT NULL,
    point         TEXT     NOT NULL,
    rapporteur_id BIGINT   REFERENCES utilisateur(id),
    UNIQUE (seance_id, rang),
    CONSTRAINT seance_point_rang_positif CHECK (rang > 0)
);

-- ---------------------------------------------------------------------
--  seance_participant
--  Convoque et present sont deux choses. Un directeur convoque et absent
--  est precisement ce que la DSR doit voir : c'est le lien avec le
--  registre de disponibilite.
-- ---------------------------------------------------------------------
CREATE TABLE seance_participant (
    id             BIGINT  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seance_id      BIGINT  NOT NULL REFERENCES seance(id) ON DELETE CASCADE,
    utilisateur_id BIGINT  NOT NULL REFERENCES utilisateur(id),
    present        BOOLEAN NOT NULL DEFAULT true,
    excuse         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (seance_id, utilisateur_id)
);
CREATE INDEX seance_participant_utilisateur ON seance_participant (utilisateur_id);

-- ---------------------------------------------------------------------
--  seance_document
--  Ordre du jour, compte rendu, proces-verbal, dossier, rapport.
--
--  Le fichier lui-meme vit dans `piece_jointe`, comme partout ailleurs :
--  une seconde table de pieces aurait fait diverger l'empreinte, le
--  versionnement et la reconnaissance optique.
-- ---------------------------------------------------------------------
CREATE TABLE seance_document (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seance_id       BIGINT      NOT NULL REFERENCES seance(id) ON DELETE CASCADE,
    nature          TEXT        NOT NULL,
    libelle         TEXT        NOT NULL,
    piece_jointe_id BIGINT      REFERENCES piece_jointe(id),
    depose_le       DATE,
    depose_par      BIGINT      REFERENCES utilisateur(id),
    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par        BIGINT,
    CONSTRAINT seance_document_nature_valide CHECK (nature IN (
        'ordre_du_jour','compte_rendu','proces_verbal','dossier_seance','rapport')),
    CONSTRAINT seance_document_depot_complet
      CHECK ((depose_le IS NULL AND depose_par IS NULL)
          OR (depose_le IS NOT NULL AND depose_par IS NOT NULL))
);
CREATE INDEX seance_document_seance ON seance_document (seance_id);
-- Les documents encore attendus : c'est la requete du tableau de bord.
CREATE INDEX seance_document_attendus
    ON seance_document (seance_id) WHERE depose_le IS NULL;


-- =====================================================================
--  2. ENTITES EXTERIEURES
--  Filiales et succursales d'un cote, organisations ou le PAD est
--  represente de l'autre. Deux tables : dans un cas le PAD detient, dans
--  l'autre il siege. Les confondre aurait melange « preparer un dossier
--  de session » et « designer un representant ».
-- =====================================================================

CREATE TABLE entite_externe (
    id           BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sigle        TEXT        NOT NULL UNIQUE,
    libelle      TEXT        NOT NULL,
    nature       TEXT        NOT NULL,
    valide_du    DATE        NOT NULL DEFAULT CURRENT_DATE,
    valide_au    DATE,
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par     BIGINT,
    modifie_le   TIMESTAMPTZ,
    modifie_par  BIGINT,
    CONSTRAINT entite_nature_valide CHECK (nature IN ('filiale','succursale'))
);

COMMENT ON TABLE entite_externe IS
  'Filiales et succursales du PAD. La DSR n''y siege pas : elle prepare les dossiers de session et suit les prescriptions.';

-- ---------------------------------------------------------------------
--  organe_gestion — conseil, assemblee ou comite d'une entite
--
--  `prochaine_session` et `etat_preparation` sont sur l'organe et non
--  sur une table de sessions : le front suit la session A VENIR, une
--  seule a la fois. Modeliser l'historique des sessions passees serait
--  ajouter une table que rien ne lit — les prescriptions, elles, portent
--  deja leur session d'origine en texte.
-- ---------------------------------------------------------------------
CREATE TABLE organe_gestion (
    id                 BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entite_externe_id  BIGINT      NOT NULL REFERENCES entite_externe(id),
    organe             TEXT        NOT NULL,
    prochaine_session  DATE,
    etat_preparation   TEXT        NOT NULL DEFAULT 'a_preparer',
    documents_attendus SMALLINT    NOT NULL DEFAULT 0,
    documents_recus    SMALLINT    NOT NULL DEFAULT 0,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par           BIGINT,
    modifie_le         TIMESTAMPTZ,
    modifie_par        BIGINT,
    UNIQUE (entite_externe_id, organe),
    CONSTRAINT organe_valide CHECK (organe IN (
        'conseil_administration','assemblee_generale','comite_gestion')),
    CONSTRAINT organe_preparation_valide CHECK (etat_preparation IN (
        'a_preparer','dossier_en_cours','dossier_transmis','tenue')),
    CONSTRAINT organe_documents_coherents
      CHECK (documents_recus <= documents_attendus)
);

-- ---------------------------------------------------------------------
--  organisation_externe et representation — §3.3
-- ---------------------------------------------------------------------
CREATE TABLE organisation_externe (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sigle       TEXT        NOT NULL UNIQUE,
    libelle     TEXT        NOT NULL,
    nature      TEXT        NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par    BIGINT,
    CONSTRAINT organisation_nature_valide CHECK (nature IN (
        'comite_national','organisation_portuaire','association_professionnelle','groupement'))
);

CREATE TABLE representation (
    id                      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organisation_externe_id BIGINT      NOT NULL REFERENCES organisation_externe(id),
    representant_id         BIGINT      NOT NULL REFERENCES utilisateur(id),
    suppleant_id            BIGINT      REFERENCES utilisateur(id),
    mandat_du               DATE        NOT NULL,
    mandat_au               DATE        NOT NULL,
    -- Deux compteurs plutot qu'une table de presences : aucun ecran ne
    -- saisit la presence reunion par reunion, et une table que rien
    -- n'alimente resterait vide en affichant un taux faux.
    reunions_tenues         SMALLINT    NOT NULL DEFAULT 0,
    reunions_participees    SMALLINT    NOT NULL DEFAULT 0,
    -- Ce que l'institution retire de sa presence. Vide tant que rien
    -- n'est declare : inventer un apport serait pire que le silence.
    apport                  TEXT,
    cree_le                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par                BIGINT,
    modifie_le              TIMESTAMPTZ,
    modifie_par             BIGINT,
    invalide_le             TIMESTAMPTZ,
    invalide_par            BIGINT,
    CONSTRAINT representation_mandat_valide CHECK (mandat_au >= mandat_du),
    CONSTRAINT representation_participation_coherente
      CHECK (reunions_participees <= reunions_tenues),
    CONSTRAINT representation_suppleant_distinct
      CHECK (suppleant_id IS NULL OR suppleant_id <> representant_id)
);
CREATE INDEX representation_organisation ON representation (organisation_externe_id);
CREATE INDEX representation_representant ON representation (representant_id);


-- =====================================================================
--  3. ENGAGEMENT — ADR 006
--  `decision_reunion` devient `engagement` et accueille les trois
--  origines. Le renommage precede les ajouts pour que les contraintes
--  portent le bon nom.
-- =====================================================================

ALTER TABLE decision_reunion RENAME TO engagement;
ALTER TABLE engagement RENAME COLUMN reunion_date TO date_engagement;

ALTER TABLE engagement
    ADD COLUMN origine                 TEXT NOT NULL DEFAULT 'instance',
    ADD COLUMN instance                TEXT,
    ADD COLUMN seance_id               BIGINT REFERENCES seance(id),
    ADD COLUMN organe_gestion_id       BIGINT REFERENCES organe_gestion(id),
    ADD COLUMN organisation_externe_id BIGINT REFERENCES organisation_externe(id),
    ADD COLUMN contexte                TEXT,
    ADD COLUMN echeance                DATE,
    -- Calcule depuis engagement_structure, par declencheur. Meme
    -- arbitrage que pour l'avancement d'une activite : stocke pour ne pas
    -- reparcourir les structures a chaque tableau de bord.
    ADD COLUMN avancement              NUMERIC(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN suspendu_le             TIMESTAMPTZ,
    ADD COLUMN suspendu_par            BIGINT REFERENCES utilisateur(id),
    ADD COLUMN motif_suspension        TEXT,
    ADD COLUMN execute_le              TIMESTAMPTZ,
    ADD COLUMN execute_par             BIGINT REFERENCES utilisateur(id);

ALTER TABLE engagement
    ADD CONSTRAINT engagement_origine_valide
      CHECK (origine IN ('instance','organe_filiale','organisation_externe')),
    -- Une et une seule provenance. Un engagement sans origine ne serait
    -- rattachable a aucun ecran ; deux origines le feraient apparaitre
    -- sur deux registres avec deux libelles.
    ADD CONSTRAINT engagement_provenance_unique CHECK (
        (origine = 'instance'              AND organe_gestion_id IS NULL
                                           AND organisation_externe_id IS NULL)
     OR (origine = 'organe_filiale'        AND organe_gestion_id IS NOT NULL
                                           AND seance_id IS NULL
                                           AND organisation_externe_id IS NULL)
     OR (origine = 'organisation_externe'  AND organisation_externe_id IS NOT NULL
                                           AND seance_id IS NULL
                                           AND organe_gestion_id IS NULL)),
    -- L'instance ne qualifie qu'un engagement interne : une recommandation
    -- d'une organisation portuaire n'est pas rendue par le CODIR.
    ADD CONSTRAINT engagement_instance_coherente
      CHECK ((origine = 'instance' AND instance IS NOT NULL)
          OR (origine <> 'instance' AND instance IS NULL)),
    ADD CONSTRAINT engagement_instance_valide
      CHECK (instance IS NULL OR instance IN (
          'conseil_administration','codir','directeur_general','assemblee_generale')),
    ADD CONSTRAINT engagement_avancement_borne
      CHECK (avancement BETWEEN 0 AND 100),
    ADD CONSTRAINT engagement_suspension_motivee
      CHECK (suspendu_le IS NULL OR motif_suspension IS NOT NULL);

CREATE INDEX engagement_origine  ON engagement (origine, date_engagement DESC);
CREATE INDEX engagement_seance   ON engagement (seance_id);
CREATE INDEX engagement_organe   ON engagement (organe_gestion_id);
CREATE INDEX engagement_externe  ON engagement (organisation_externe_id);
-- Les engagements en retard, selon l'arbitrage n° 2 : echeance depassee,
-- ni executes ni suspendus. Index partiel, comme pour les activites.
CREATE INDEX engagement_retard
    ON engagement (echeance)
    WHERE execute_le IS NULL AND suspendu_le IS NULL AND invalide_le IS NULL;

COMMENT ON TABLE engagement IS
  'Decision d''instance, prescription de filiale ou recommandation externe. Un seul objet, trois origines — ADR 006.';
COMMENT ON COLUMN engagement.avancement IS
  'Calcule depuis engagement_structure, pondere a parts egales. Stocke pour ne pas reparcourir les structures a chaque tableau de bord.';

-- ---------------------------------------------------------------------
--  engagement_structure — qui est charge, et ou il en est
--  RANG 1 = STRUCTURE PILOTE : celle qui rend compte. Meme regle que le
--  chef de file d'une cotation, et meme raison.
-- ---------------------------------------------------------------------
CREATE TABLE engagement_structure (
    id            BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engagement_id BIGINT       NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    structure_id  BIGINT       NOT NULL REFERENCES structure(id),
    rang          SMALLINT     NOT NULL,
    pilote        BOOLEAN      GENERATED ALWAYS AS (rang = 1) STORED,
    avancement    NUMERIC(5,2) NOT NULL DEFAULT 0,
    cree_le       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    UNIQUE (engagement_id, rang),
    UNIQUE (engagement_id, structure_id),
    CONSTRAINT engagement_structure_rang_positif CHECK (rang > 0),
    CONSTRAINT engagement_structure_avancement_borne
      CHECK (avancement BETWEEN 0 AND 100)
);
CREATE INDEX engagement_structure_structure
    ON engagement_structure (structure_id, rang);

-- ---------------------------------------------------------------------
--  engagement_jalon — les etapes datees
-- ---------------------------------------------------------------------
CREATE TABLE engagement_jalon (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engagement_id BIGINT      NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    structure_id  BIGINT      REFERENCES structure(id),
    libelle       TEXT        NOT NULL,
    echeance      DATE        NOT NULL,
    fait_le       DATE,
    ordre         SMALLINT    NOT NULL DEFAULT 1,
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par      BIGINT,
    modifie_le    TIMESTAMPTZ,
    modifie_par   BIGINT,
    invalide_le   TIMESTAMPTZ,
    invalide_par  BIGINT
);
CREATE INDEX engagement_jalon_engagement ON engagement_jalon (engagement_id, ordre);
CREATE INDEX engagement_jalon_echu
    ON engagement_jalon (echeance) WHERE fait_le IS NULL AND invalide_le IS NULL;

-- ---------------------------------------------------------------------
--  engagement_observation — le fil de suivi
--
--  Une RELANCE de la DSR n'est pas une observation ordinaire : elle se
--  voit, et elle se compte. D'ou le drapeau plutot qu'une seconde table :
--  les deux s'affichent dans le meme fil, dans l'ordre.
-- ---------------------------------------------------------------------
CREATE TABLE engagement_observation (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engagement_id BIGINT      NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    texte         TEXT        NOT NULL,
    relance       BOOLEAN     NOT NULL DEFAULT false,
    auteur_id     BIGINT      NOT NULL REFERENCES utilisateur(id),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX engagement_observation_engagement
    ON engagement_observation (engagement_id, cree_le DESC);
CREATE INDEX engagement_observation_relances
    ON engagement_observation (engagement_id) WHERE relance;


-- =====================================================================
--  4. DISPONIBILITE DES RESPONSABLES
--  §3.3. Une decision confiee a un directeur en mission n'avancera pas :
--  c'est ce registre qui le dit avant qu'on ne s'en apercoive.
-- =====================================================================

CREATE TABLE disponibilite (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id BIGINT      NOT NULL REFERENCES utilisateur(id),
    type_absence   TEXT        NOT NULL,
    du             DATE        NOT NULL,
    au             DATE        NOT NULL,
    motif          TEXT,
    -- Sans interimaire designe, les dossiers de la structure s'arretent.
    -- C'est le point que la DSR doit voir : d'ou l'index partiel.
    interimaire_id BIGINT      REFERENCES utilisateur(id),
    saisi_par      BIGINT      NOT NULL REFERENCES utilisateur(id),
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    invalide_le    TIMESTAMPTZ,
    invalide_par   BIGINT,
    CONSTRAINT disponibilite_periode_valide CHECK (au >= du),
    CONSTRAINT disponibilite_type_valide CHECK (type_absence IN (
        'conge_annuel','mission','interim','formation','absence_exceptionnelle')),
    CONSTRAINT disponibilite_interimaire_distinct
      CHECK (interimaire_id IS NULL OR interimaire_id <> utilisateur_id)
);
CREATE INDEX disponibilite_utilisateur ON disponibilite (utilisateur_id, du DESC);
CREATE INDEX disponibilite_sans_interim
    ON disponibilite (du, au) WHERE interimaire_id IS NULL AND invalide_le IS NULL;

-- Deux absences ne se chevauchent pas pour un meme agent. La contrainte
-- est posee au moteur : deux absences simultanees rendraient la question
-- « qui le remplace ? » sans reponse, et aucun code applicatif ne tient
-- cette garantie sous concurrence. Meme mecanisme que utilisateur_session.
ALTER TABLE disponibilite
    ADD CONSTRAINT disponibilite_sans_chevauchement
    EXCLUDE USING gist (
        utilisateur_id WITH =,
        daterange(du, au, '[]') WITH &&
    ) WHERE (invalide_le IS NULL);


-- =====================================================================
--  5. PLANNING DES CONGES
--  §3.3 : « confectionner les projets de planning des conges annuels des
--  Directeurs de services et membres du Cabinet, en liaison avec la DRH ».
--
--  A NE PAS CONFONDRE avec le registre de disponibilite : celui-ci
--  enregistre une absence decidee, celui-la arbitre des souhaits avant
--  qu'ils ne le deviennent. Deux objets, deux moments.
-- =====================================================================

CREATE TABLE conge_droit (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utilisateur_id BIGINT      NOT NULL REFERENCES utilisateur(id),
    annee          SMALLINT    NOT NULL,
    -- Le nombre de jours vient de la DRH. Le PAD ne le calcule pas ici :
    -- l'anciennete, les reports et les majorations sont son affaire.
    droits_jours   SMALLINT    NOT NULL DEFAULT 30,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    UNIQUE (utilisateur_id, annee),
    CONSTRAINT conge_droit_positif CHECK (droits_jours >= 0),
    CONSTRAINT conge_droit_annee_plausible CHECK (annee BETWEEN 2020 AND 2100)
);

CREATE TABLE conge_periode (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conge_droit_id BIGINT      NOT NULL REFERENCES conge_droit(id) ON DELETE CASCADE,
    du             DATE        NOT NULL,
    au             DATE        NOT NULL,
    etat           TEXT        NOT NULL DEFAULT 'souhaite',
    motif_report   TEXT,
    arbitre_le     TIMESTAMPTZ,
    arbitre_par    BIGINT      REFERENCES utilisateur(id),
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    cree_par       BIGINT,
    modifie_le     TIMESTAMPTZ,
    modifie_par    BIGINT,
    CONSTRAINT conge_periode_valide CHECK (au >= du),
    CONSTRAINT conge_periode_etat_valide
      CHECK (etat IN ('souhaite','arbitre','valide','reporte')),
    -- Un report sans motif ne se corrige pas : le directeur resoumettra
    -- la meme periode. Meme regle que le renvoi d'un plan d'actions.
    CONSTRAINT conge_periode_report_motive
      CHECK (etat <> 'reporte' OR motif_report IS NOT NULL)
);
CREATE INDEX conge_periode_droit ON conge_periode (conge_droit_id);
CREATE INDEX conge_periode_dates ON conge_periode (du, au);


-- =====================================================================
--  6. DECLENCHEURS
-- =====================================================================

-- ---------------------------------------------------------------------
--  Avancement d'un engagement : moyenne des structures chargees.
--
--  A PARTS EGALES, et c'est une hypothese : rien ne dit qu'une structure
--  pilote pese plus que ses co-chargees. Ponderer par le rang aurait
--  invente une regle ; la moyenne simple en invente une aussi, mais elle
--  est lisible et se corrige sans redeploiement le jour de l'arbitrage.
--  Voir docs/questions-ouvertes.md, A17.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_avancement_engagement() RETURNS TRIGGER AS $$
DECLARE
    v_engagement BIGINT := COALESCE(NEW.engagement_id, OLD.engagement_id);
    v_moyenne    NUMERIC(5,2);
BEGIN
    SELECT round(AVG(avancement), 2) INTO v_moyenne
      FROM engagement_structure
     WHERE engagement_id = v_engagement;

    IF v_moyenne IS NULL THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    -- La clause finale evite de reecrire la ligne quand rien ne change :
    -- sans elle, chaque enregistrement declencherait l'historisation
    -- complete de l'engagement pour un resultat identique.
    UPDATE engagement
       SET avancement = v_moyenne
     WHERE id = v_engagement
       AND avancement IS DISTINCT FROM v_moyenne;

    RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;

CREATE TRIGGER engagement_structure_avancement
    AFTER INSERT OR UPDATE OR DELETE ON engagement_structure
    FOR EACH ROW EXECUTE FUNCTION maj_avancement_engagement();

-- ---------------------------------------------------------------------
--  Reference lisible de l'engagement, numerotee par annee et par origine.
--  Jamais saisie, comme le numero du courrier et le code d'une activite.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION attribuer_reference_engagement() RETURNS TRIGGER AS $$
DECLARE
    v_prefixe TEXT;
    v_annee   TEXT;
    v_numero  INTEGER;
BEGIN
    IF NEW.reference IS NOT NULL AND NEW.reference <> '' THEN
        RETURN NEW;
    END IF;

    v_prefixe := CASE NEW.origine
        WHEN 'instance'             THEN 'DEC'
        WHEN 'organe_filiale'       THEN 'PRE'
        WHEN 'organisation_externe' THEN 'REC'
    END;
    v_annee := to_char(COALESCE(NEW.date_engagement, CURRENT_DATE), 'YYYY');

    -- Verrou d'avis sur (prefixe, annee) : deux insertions concurrentes
    -- obtiendraient sinon le meme numero. Il n'y a pas de ligne parente a
    -- verrouiller ici, contrairement au code d'une activite.
    PERFORM pg_advisory_xact_lock(hashtext(v_prefixe || v_annee));

    SELECT COALESCE(MAX(substring(reference FROM '[0-9]+$')::INTEGER), 0) + 1
      INTO v_numero
      FROM engagement
     WHERE reference LIKE v_prefixe || '-' || v_annee || '-%';

    NEW.reference := v_prefixe || '-' || v_annee || '-' || lpad(v_numero::TEXT, 4, '0');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER engagement_reference
    BEFORE INSERT ON engagement
    FOR EACH ROW EXECUTE FUNCTION attribuer_reference_engagement();

-- ---------------------------------------------------------------------
--  Historisation, par le meme declencheur que partout ailleurs.
--  Rappel : l'application doit positionner SET LOCAL app.utilisateur_id,
--  ou SET LOCAL app.contexte pour un traitement non nominatif.
-- ---------------------------------------------------------------------
CREATE TRIGGER seance_historique
    AFTER UPDATE ON seance
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER engagement_structure_historique
    AFTER UPDATE ON engagement_structure
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER disponibilite_historique
    AFTER UPDATE ON disponibilite
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();

CREATE TRIGGER conge_periode_historique
    AFTER UPDATE ON conge_periode
    FOR EACH ROW EXECUTE FUNCTION historiser_champs();


-- =====================================================================
--  7. VUE DE L'ETAT AFFICHE
--  Cinq etats affiches, deux stockes. Meme raisonnement que pour les
--  activites : le retard se deduit des dates (arbitrage n° 2), et le
--  stocker imposerait de reecrire toutes les lignes chaque nuit.
-- =====================================================================

CREATE VIEW v_engagement_etat AS
SELECT e.id,
       e.origine,
       e.instance,
       CASE
           WHEN e.suspendu_le IS NOT NULL              THEN 'suspendu'
           WHEN e.execute_le  IS NOT NULL              THEN 'execute'
           WHEN e.echeance IS NOT NULL
            AND e.echeance < CURRENT_DATE              THEN 'en_retard'
           WHEN e.avancement = 0                       THEN 'a_lancer'
           ELSE 'en_cours'
       END AS etat_affiche,
       e.avancement,
       (SELECT count(*) FROM engagement_observation o
         WHERE o.engagement_id = e.id AND o.relance) AS relances,
       -- Un jalon echu non fait : le signal qui distingue un engagement
       -- qui prend du retard d'un engagement qu'on a oublie.
       EXISTS (
           SELECT 1 FROM engagement_jalon j
            WHERE j.engagement_id = e.id AND j.fait_le IS NULL
              AND j.echeance < CURRENT_DATE AND j.invalide_le IS NULL
       ) AS jalon_echu
  FROM engagement e
 WHERE e.invalide_le IS NULL;

COMMENT ON VIEW v_engagement_etat IS
  'Etat affiche des engagements. « A lancer » signifie avancement nul : c''est ce que le front attend, et cela ne se stocke pas.';


-- =====================================================================
--  8. AGREGAT
--  Meme regle que pour le courrier et les activites : le tableau de bord
--  n'agrege jamais a la volee.
-- =====================================================================

CREATE TABLE agregat_gouvernance_jour (
    jour                 DATE        NOT NULL,
    origine              TEXT        NOT NULL,
    instance             TEXT        NOT NULL DEFAULT '',
    nb_total             INTEGER     NOT NULL DEFAULT 0,
    nb_a_lancer          INTEGER     NOT NULL DEFAULT 0,
    nb_en_cours          INTEGER     NOT NULL DEFAULT 0,
    nb_executes          INTEGER     NOT NULL DEFAULT 0,
    nb_en_retard         INTEGER     NOT NULL DEFAULT 0,
    nb_suspendus         INTEGER     NOT NULL DEFAULT 0,
    depots_en_souffrance INTEGER     NOT NULL DEFAULT 0,
    absences_sans_interim INTEGER    NOT NULL DEFAULT 0,
    calcule_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (jour, origine, instance)
);

COMMENT ON TABLE agregat_gouvernance_jour IS
  'Alimente par tache planifiee nocturne. Le retard evolue avec le temps sans qu''aucune ecriture ne survienne.';


-- =====================================================================
--  9. CLES ETRANGERES DIFFEREES
--  Les colonnes systematiques referencent utilisateur(id), comme dans
--  init_base.sql et init_activite.sql.
-- =====================================================================

DO $$
DECLARE
    t TEXT;
    c TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'seance','seance_document','entite_externe','organe_gestion',
        'organisation_externe','representation','engagement_structure',
        'engagement_jalon','disponibilite','conge_droit','conge_periode'
    ] LOOP
        FOREACH c IN ARRAY ARRAY['cree_par','modifie_par','invalide_par'] LOOP
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
