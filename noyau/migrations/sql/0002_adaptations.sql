-- =====================================================================
--  Adaptations du socle
--
--  Trois modifications du schema d'origine, chacune motivee. Elles sont
--  dans un fichier separe et non fondues dans 0001_socle.sql : celui-ci
--  doit rester la copie fidele du script livre, pour qu'on puisse voir
--  d'un diff ce que le backend a change.
--
--  Le correctif de la contrainte permission_domaine_valide, lui, est
--  applique directement dans 0001 : le script d'origine ne pouvait pas
--  s'executer sans lui (les permissions EXP_SAI et EXP_LEC sont inserees
--  avec un domaine que la contrainte refusait).
-- =====================================================================


-- ---------------------------------------------------------------------
--  1. Mot de passe local, transitoire
--
--  Le schema disait « aucun mot de passe n'est stocke », l'authentification
--  devant etre deleguee a l'annuaire (RF-ADM-02). Elle ne l'est pas encore :
--  le connecteur OIDC est un chantier a part, et il faut pouvoir ouvrir une
--  session d'ici la.
--
--  Cette colonne doit etre videe pour tous le jour de la bascule SSO.
--  Voir docs/architecture/004-session-cookie-sans-jeton.md.
-- ---------------------------------------------------------------------
ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS mot_de_passe TEXT;

COMMENT ON COLUMN utilisateur.mot_de_passe IS
  'Transitoire. Vide pour tout compte rattache a l''annuaire. A supprimer a la bascule SSO.';


-- ---------------------------------------------------------------------
--  2. Pieces jointes generiques
--
--  La table etait couplee au courrier. Le §18 range les pieces jointes
--  parmi les elements de la fiche de vie d'une ACTIVITE, et RF-GED-04
--  impose le versionnement pour tout document, pas seulement pour les
--  courriers.
--
--  `courrier_id` est conservee : les index et les requetes du pilier
--  courrier s'y appuient. Les deux coexistent, comme dans `evenement`.
-- ---------------------------------------------------------------------
ALTER TABLE piece_jointe ADD COLUMN IF NOT EXISTS objet_type TEXT;
ALTER TABLE piece_jointe ADD COLUMN IF NOT EXISTS objet_id   BIGINT;

CREATE INDEX IF NOT EXISTS piece_jointe_objet
    ON piece_jointe (objet_type, objet_id);

COMMENT ON COLUMN piece_jointe.objet_type IS
  'Rattachement generique : « activite », « evenement », « versement ». Meme principe que evenement.objet_type.';

-- Les pieces existantes sont toutes des pieces de courrier.
UPDATE piece_jointe
   SET objet_type = 'courrier', objet_id = courrier_id
 WHERE courrier_id IS NOT NULL AND objet_type IS NULL;


-- ---------------------------------------------------------------------
--  3. Parametres des regles de gestion
--
--  Plusieurs regles appliquees par l'application n'ont AUCUNE source
--  documentaire : elles ont ete inventees par la conception, faute de
--  reponse du metier. Les coder en dur aurait rendu leur correction
--  impossible sans redeploiement, et aurait fait passer une hypothese
--  pour une decision.
--
--  La colonne `statut` porte cette distinction, et le rapport d'audit
--  peut donc lister ce qui reste a trancher.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parametre (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cle             TEXT        NOT NULL UNIQUE,
    libelle         TEXT        NOT NULL,
    valeur          TEXT        NOT NULL,
    type_valeur     TEXT        NOT NULL DEFAULT 'entier',
    domaine         TEXT        NOT NULL,
    statut          TEXT        NOT NULL DEFAULT 'hypothese',
    source          TEXT,
    a_trancher_par  TEXT,
    modifie_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    modifie_par     BIGINT,
    CONSTRAINT parametre_type_valide
      CHECK (type_valeur IN ('entier','decimal','texte','booleen')),
    CONSTRAINT parametre_statut_valide
      CHECK (statut IN ('acte','hypothese')),
    -- Une hypothese doit dire qui la tranchera, sinon elle ne sera jamais
    -- tranchee : c'est exactement ce qui est arrive aux quatre premieres.
    CONSTRAINT parametre_hypothese_a_un_responsable
      CHECK (statut = 'acte' OR a_trancher_par IS NOT NULL)
);

COMMENT ON TABLE parametre IS
  'Regles de gestion parametrables. Le statut « hypothese » signale une regle sans source documentaire.';


-- Les quatre regles du pilier « activites » identifiees comme sans source.
INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('activite.mode_avancement_attendu',
   'Mode de calcul de l''avancement attendu',
   'lineaire_jours_ouvres', 'texte', 'activite', 'hypothese',
   NULL,
   'DSR et contrôle de gestion'),

  ('activite.seuil_retard_points',
   'Ecart en points au-dela duquel une activite passe « en retard »',
   '10', 'entier', 'activite', 'hypothese',
   NULL,
   'DSR'),

  ('activite.criticite_exige_contrainte',
   'Une activite critique doit porter, en plus du retard, une instruction ou une tache echue',
   'true', 'booleen', 'activite', 'hypothese',
   NULL,
   'Direction generale'),

  ('activite.mode_taux_indicateur',
   'Formule du taux d''atteinte d''un indicateur',
   'reference_vers_cible', 'texte', 'activite', 'hypothese',
   NULL,
   'Contrôle de gestion')
ON CONFLICT (cle) DO NOTHING;


-- Les trois axes du plan strategique. Referentiel ferme : la valeur est
-- connue et arretee (communication du 11 aout 2026), et une saisie libre
-- aurait produit quatre orthographes pour un meme axe.
INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source)
VALUES
  ('activite.axes_strategiques',
   'Axes du plan strategique du Port autonome de Douala',
   'A1|A2|A3', 'texte', 'activite', 'acte',
   'Communication de la Direction generale du 11 aout 2026')
ON CONFLICT (cle) DO NOTHING;
