-- =====================================================================
--  Une relance automatique n'a pas d'auteur.
--
--  `engagement_observation.auteur_id` etait NOT NULL : toute observation
--  etait signee. C'est vrai des observations humaines, et faux des
--  relances que la tache nocturne emet — personne ne les a signees, et
--  leur attribuer un agent serait faux.
--
--  Le socle avait deja tranche pareil pour le courrier : `relance.
--  emetteur_id` est nullable, et c'est precisement ce qui distingue une
--  relance automatique d'une relance signee par la DSR.
--
--  La contrainte ajoutee dit la regle qui remplace le NOT NULL : une
--  observation SANS auteur est necessairement une relance. Une remarque
--  anonyme dans le fil de suivi, elle, n'aurait aucun sens.
-- =====================================================================

ALTER TABLE engagement_observation ALTER COLUMN auteur_id DROP NOT NULL;

ALTER TABLE engagement_observation
    ADD CONSTRAINT engagement_observation_auteur_ou_relance
    CHECK (auteur_id IS NOT NULL OR relance);

COMMENT ON COLUMN engagement_observation.auteur_id IS
  'Nul pour une relance automatique : personne ne l''a signee. Meme regle que relance.emetteur_id.';
