-- Les reglages du portail usagers et de la supervision technique — A43 et A47.
--
-- Trois valeurs sans source, une valeur qui en a une. La distinction est
-- portee par la colonne `statut` : `hypothese` pour ce que personne n'a
-- tranche, `valide` pour ce qui sort d'un document.
--
-- 1. Le delai de reponse annonce a l'usager (hypothese).
--
--    Trente jours, annonces **avant** le depot et figes sur la demande. C'est
--    l'usage administratif courant, pas une regle ecrite du Port autonome de
--    Douala. Il varie tres probablement selon le type de demande — une
--    autorisation d'occupation du domaine et une demande d'information ne se
--    traitent pas dans le meme temps. La valeur decide de ce que l'institution
--    promet en son nom : elle ne peut pas rester dans le code.
--
-- 2. Le fournisseur d'identite et son protocole (hypotheses).
--
--    RF-ADM-02 exige l'authentification unique via l'annuaire d'entreprise. Ni
--    le produit ni le protocole ne sont nommes nulle part. Les deux valeurs
--    sont vides : l'ecran de supervision lit alors « aucun fournisseur
--    declare », ce qui est la verite tant que la bascule n'a pas eu lieu.
--    Inventer « Active Directory » aurait fait croire a une integration.
--
-- 3. La cible de reprise d'activite (actee).
--
--    Quatre heures — RNF-DISP-02 du BRD. Celle-ci a une source, et c'est
--    pourquoi elle est `acte` : elle n'est pas a trancher, elle est a tenir.
--    Elle vit tout de meme en base parce qu'un engagement contractuel se
--    renegocie, et qu'une constante Python se serait retrouvee en desaccord
--    avec l'avenant.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('portail.delai_reponse_jours',
   'Delai de reponse annonce a l''usager avant le depot de sa demande',
   '30', 'entier', 'portail', 'hypothese',
   NULL,
   'Direction generale, sur proposition des directions instructrices'),
  ('supervision.sso_fournisseur',
   'Nom du fournisseur d''identite de l''annuaire d''entreprise',
   '', 'texte', 'supervision', 'hypothese',
   NULL,
   'Direction des systemes d''information'),
  ('supervision.sso_protocole',
   'Protocole d''authentification unique retenu (SAML 2.0, OIDC, LDAP)',
   '', 'texte', 'supervision', 'hypothese',
   NULL,
   'Direction des systemes d''information'),
  ('supervision.reprise_cible_minutes',
   'Duree maximale de reprise apres incident majeur, en minutes',
   '240', 'entier', 'supervision', 'acte',
   'BRD, RNF-DISP-02 — reprise en moins de 4 heures',
   NULL)
ON CONFLICT (cle) DO NOTHING;
