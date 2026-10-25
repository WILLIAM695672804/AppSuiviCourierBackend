-- Le seuil qui fait d'un volume de consultations une anomalie — A23.
--
-- Un seuil absolu ne veut rien dire : l'agent du courrier central consulte
-- cent fois par jour, un directeur trois fois par semaine. Le seuil est donc
-- relatif — la mediane des agents actifs sur sept jours, multipliee par ce
-- facteur.
--
-- Le facteur, lui, n'a aucune source. Il vaut 3 parce qu'il faut une valeur,
-- et il vit ici pour etre corrigible sans redeploiement : c'est un reglage
-- d'auditeur, pas une constante d'application.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('tracabilite.facteur_volume_anormal',
   'Multiple de la mediane au-dela duquel un volume de consultations est signale',
   '3', 'entier', 'tracabilite', 'hypothese',
   NULL,
   'Poste d''audit (§3.12)')
ON CONFLICT (cle) DO NOTHING;
