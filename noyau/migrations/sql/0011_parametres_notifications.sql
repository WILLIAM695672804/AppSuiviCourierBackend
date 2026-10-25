-- Les trois reglages de la file de notifications — A51.
--
-- 1. L'envoi par courriel est **coupe** (hypothese).
--
--    Le code d'envoi existe et fonctionne ; il passe par `django.core.mail`.
--    Ce qui n'existe pas, c'est la decision : ni le serveur SMTP, ni l'adresse
--    d'expedition, ni la politique de l'institution ne sont arretes — l'etat
--    des integrations le dit deja (« Messagerie institutionnelle : Non
--    connecte », RF-SUI-03).
--
--    Coupe par defaut, et non ouvert : un environnement de recette qui ecrit a
--    de vraies adresses d'agents est un incident, pas un essai. Ouvrir la
--    regle est un geste d'administration, tracable, qui n'attend aucune
--    livraison.
--
-- 2. Trois tentatives (hypothese).
--
--    Le nombre de passages du depileur sur un envoi en echec. Trois est
--    l'usage ; aucun document ne le fixe. Trop bas, un incident reseau d'une
--    minute perd des notifications ; trop haut, une adresse invalide fait
--    battre la file indefiniment contre un mur.
--
--    Un envoi `sans_transport` n'est jamais repris : ce n'est pas un echec,
--    c'est l'absence de destination. Le compteur ne le concerne pas.
--
-- 3. Deux cents envois par passage (hypothese).
--
--    Une borne, et non « tout ce qui traine ». Une file de dix mille lignes
--    accumulee pendant une panne ne doit pas partir d'un coup a la reprise :
--    un serveur de messagerie qui recoit dix mille messages en une seconde
--    d'un expediteur inconnu classe l'expediteur, pas les messages.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('notifications.courriel_actif',
   'Envoyer réellement les notifications par courriel',
   'false', 'booleen', 'notifications', 'hypothese',
   NULL,
   'Direction des systemes d''information — serveur SMTP et adresse d''expedition'),
  ('notifications.tentatives_max',
   'Nombre de tentatives avant abandon d''un envoi',
   '3', 'entier', 'notifications', 'hypothese',
   NULL,
   'Direction des systemes d''information'),
  ('notifications.lot_depilement',
   'Nombre d''envois traités à chaque passage du dépileur',
   '200', 'entier', 'notifications', 'hypothese',
   NULL,
   'Direction des systemes d''information')
ON CONFLICT (cle) DO NOTHING;
