-- =====================================================================
--  v_dossier_etat
--  Cinq etats affiches, aucun stocke.
--
--  L'ordre des cas est la regle metier, pas un detail d'ecriture :
--  le retard l'emporte sur l'attente d'un complement. Un dossier hors
--  delai qui attend une piece est d'abord hors delai — sans quoi
--  l'instructeur lirait « en attente » et se croirait couvert.
--
--  Le delai ne se suspend pas. Demander un complement ne repousse rien :
--  le demandeur qui ne repond pas ne dispense pas l'institution de son
--  obligation de reponse (§3.7). C'est pour cela que « en attente de
--  complement » vient APRES « hors delai » et non a sa place.
-- =====================================================================

CREATE VIEW v_dossier_etat AS
SELECT d.id,
       d.structure_id,
       d.etape,
       CASE
           WHEN d.etape = 'clos'                       THEN 'clos'
           WHEN d.echeance < CURRENT_DATE              THEN 'hors_delai'
           WHEN EXISTS (
                SELECT 1 FROM complement_dossier c
                 WHERE c.dossier_id = d.id AND c.recu_le IS NULL
           )                                           THEN 'attente_complement'
           -- « Retourne » se lit au journal : c'est le dernier fait inscrit
           -- sur ce dossier qui le dit. Une colonne aurait fait diverger
           -- l'etat affiche de l'historique le jour ou l'un des deux serait
           -- ecrit sans l'autre (ADR 012).
           WHEN (
                SELECT e.type_evenement
                  FROM evenement e
                 WHERE e.objet_type = 'dossier' AND e.objet_id = d.id
                 ORDER BY e.survenu_le DESC
                 LIMIT 1
           ) = 'dossier_retour_etape'                  THEN 'retourne'
           ELSE 'en_cours'
       END AS etat_affiche,
       -- Negatif quand l'echeance est depassee. Le registre affiche ce
       -- nombre plutot que la date : un instructeur qui balaie sa liste le
       -- matin cherche ce qui lui reste, pas une date a soustraire de tete.
       (d.echeance - CURRENT_DATE)::INTEGER AS jours_restants,
       (SELECT count(*)::INTEGER FROM complement_dossier c
         WHERE c.dossier_id = d.id AND c.recu_le IS NULL) AS complements_en_attente
  FROM dossier d
 WHERE d.invalide_le IS NULL;

COMMENT ON VIEW v_dossier_etat IS
  'Etat affiche d''un dossier. Le retard l''emporte sur l''attente d''un complement : demander une piece ne suspend pas le delai (§3.7).';
