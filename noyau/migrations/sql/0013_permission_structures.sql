-- Les structures reviennent a l'administrateur fonctionnel — ADR 021.
--
-- Le socle donnait `ADM_STR` a la DSR : tenir le referentiel des structures
-- sans passer par l'administrateur, au titre du §3.3. L'administrateur, lui,
-- portait `ADM_ORG` — niveaux, postes, affectations — mais **pas** la creation
-- des structures que ces postes surmontent.
--
-- Le decoupage ne tenait pas a l'usage : creer une structure ouvre son poste
-- responsable, et pourvoir ce poste est un geste `ADM_ORG`. La DSR ajoutait
-- donc des directions dont elle ne pouvait nommer personne a la tete, et
-- l'administrateur nommait dans des structures qu'il ne pouvait pas creer.
--
-- Une seule permission desormais : `ADM_ORG`. `ADM_STR` disparait du
-- referentiel, ce qui est sans risque — aucune donnee metier ne la reference,
-- seules deux tables de liaison la citent.
--
-- La DSR garde la **lecture** du referentiel : elle est ouverte a toute session
-- authentifiee depuis l'ADR 007, et rien ici ne la touche.

-- Une etape de circuit pourrait exiger la permission : aucune ne le fait
-- aujourd'hui, et la supprimer sans le verifier casserait le circuit en
-- silence. On refuse plutot de migrer.
DO $$
DECLARE
  etapes INTEGER;
BEGIN
  SELECT count(*) INTO etapes
    FROM circuit_etape e
    JOIN permission p ON p.id = e.permission_requise_id
   WHERE p.code = 'ADM_STR';

  IF etapes > 0 THEN
    RAISE EXCEPTION
      'ADM_STR est exigee par % etape(s) de circuit. Reprenez ces etapes sous ADM_ORG avant de migrer.',
      etapes;
  END IF;
END $$;

DELETE FROM delegation_permission
 WHERE permission_id IN (SELECT id FROM permission WHERE code = 'ADM_STR');

DELETE FROM profil_permission
 WHERE permission_id IN (SELECT id FROM permission WHERE code = 'ADM_STR');

DELETE FROM permission WHERE code = 'ADM_STR';

-- L'administrateur fonctionnel tenait deja ADM_ORG : rien a lui ajouter. La
-- ligne ci-dessous n'est la que pour les bases ou le profil aurait ete cree
-- sans elle — l'ecriture de l'organigramme ne doit dependre d'aucun semis.
INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id
  FROM profil p, permission x
 WHERE p.code = 'ADMIN' AND x.code = 'ADM_ORG'
ON CONFLICT DO NOTHING;
