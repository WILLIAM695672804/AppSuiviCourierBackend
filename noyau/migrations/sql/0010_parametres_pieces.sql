-- Ce qu'une piece jointe a le droit d'etre — A49 et A50.
--
-- Deux hypotheses, et elles ne sont pas anodines : la premiere decide de ce
-- qu'un agent peut verser au dossier, la seconde de ce que l'institution
-- accepte de conserver.
--
-- 1. Le plafond de taille (hypothese).
--
--    Vingt-cinq megaoctets. C'est l'usage administratif courant, pas une regle
--    du Port autonome de Douala. Le chiffre juste depend de deux choses que
--    personne n'a communiquees : la bande passante des sites distants — un
--    agent d'un terminal qui verse un plan scanne sur une liaison lente — et
--    la capacite du volume de stockage a l'horizon de la duree de
--    conservation. Trop bas, il fait rejeter des scans legitimes ; trop haut,
--    il laisse verser des videos dans une GED de courrier.
--
--    Le plafond est verifie sur la **taille reellement lue**, jamais sur celle
--    annoncee par le client : un plafond controle sur un nombre envoye par
--    celui qu'on veut limiter ne limite personne.
--
-- 2. Les extensions acceptees (hypothese).
--
--    RF-GED-04 exige le versionnement de « tout document » sans dire ce qu'est
--    un document. La liste posee ici couvre ce qui circule reellement dans un
--    bureau d'ordre : bureautique, tableurs, et images de numerisation.
--
--    Ce qui n'y figure pas est aussi une decision. Les archives ouvertes
--    (`zip`, `rar`) sont absentes : une piece jointe doit etre lisible sans
--    outil tiers, et une archive rend la preuve d'integrite de RF-GED-09
--    inutile — l'empreinte porte alors sur le conteneur, pas sur ce que
--    quelqu'un lira. Les executables et les scripts sont absents pour la
--    raison evidente.
--
--    Le controle porte sur l'extension et **non sur le type MIME declare** :
--    un `Content-Type` est envoye par le client et vaut ce que vaut sa parole.
--    Ce qui protege reellement, c'est que le fichier n'est jamais execute,
--    jamais servi depuis un domaine de confiance, et rendu au telechargement
--    avec `Content-Disposition: attachment`.

INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine, statut, source, a_trancher_par)
VALUES
  ('pieces.taille_maximale_mo',
   'Poids maximal d''une piece jointe, en megaoctets',
   '25', 'entier', 'pieces', 'hypothese',
   NULL,
   'Direction des systemes d''information, avec le bureau d''ordre'),
  ('pieces.extensions_autorisees',
   'Extensions de fichier acceptees au depot, separees par des virgules',
   'pdf,doc,docx,xls,xlsx,odt,ods,jpg,jpeg,png,tif,tiff',
   'texte', 'pieces', 'hypothese',
   NULL,
   'Direction des systemes d''information, avec les archives')
ON CONFLICT (cle) DO NOTHING;
