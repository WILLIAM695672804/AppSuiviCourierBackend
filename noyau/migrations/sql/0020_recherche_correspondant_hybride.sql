-- ---------------------------------------------------------------------
--  Recherche hybride du carnet d'adresses.
--
--  Trois manques, un seul symptome : l'agent ne retrouve pas une entree
--  qui existe, la cree en double, et le compte « 14 courriers recus »
--  qu'affiche le selecteur devient faux pour les deux moities.
--
--   1. Le sigle n'etait nulle part. « MINFI » est pourtant ce qu'un agent
--      tape en premier — c'est ce qui est imprime sur l'en-tete.
--   2. Le plein texte ne pardonne aucune faute, et l'apostrophe coupe le
--      mot : « N'Djamena » s'indexe sous « djamen », donc « ndjamena » ne
--      le trouve pas.
--   3. Rien ne servait `pg_trgm`, pourtant installee.
-- ---------------------------------------------------------------------

ALTER TABLE correspondant ADD COLUMN IF NOT EXISTS sigle TEXT;

COMMENT ON COLUMN correspondant.sigle IS
  'Sigle usuel — MINFI, APN. Ce que l''agent tape en premier.';

-- ---------------------------------------------------------------------
--  Forme sous laquelle un texte se cherche : minuscules, sans accent,
--  sans apostrophe, ponctuation reduite a l'espace.
--
--  **Pourquoi une fonction a nous plutot que `unaccent`.** La forme a un
--  argument de `unaccent` est declaree STABLE — elle depend du dictionnaire
--  courant, que la session peut changer — et PostgreSQL refuse de l'indexer.
--  La forme a deux arguments nomme le dictionnaire et leve la dependance :
--  c'est la parade documentee, et elle tient tant que `public.unaccent`
--  n'est pas redefinie.
--
--  **L'apostrophe est retiree, pas remplacee.** « N'Djamena » donne
--  « ndjamena », qui est ce que l'agent tape. La remplacer par un espace
--  aurait garde le mot coupe en deux, c'est-a-dire le defaut d'origine.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION texte_recherche(t TEXT) RETURNS TEXT AS $$
    SELECT btrim(regexp_replace(
        regexp_replace(
            public.unaccent('public.unaccent', lower(coalesce(t, ''))),
            '[''`’]', '', 'g'
        ),
        '[^a-z0-9]+', ' ', 'g'
    ))
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

-- ---------------------------------------------------------------------
--  La cible des trigrammes : le nom et le sigle, rien d'autre.
--
--  Colonne generee et non expression calculee a la lecture : l'index doit
--  porter sur une valeur stockee, sans quoi le planificateur recomposerait
--  la chaine ligne a ligne et l'index ne servirait a rien.
--
--  **La ville n'y est pas, et c'est deliberé.** Elle reste dans le vecteur
--  plein texte (poids C), ou chercher « Douala » a un sens. Dans les
--  trigrammes, elle produisait du faux : « douanes » ressemble a « Douala »
--  a 0,71, et la Direction Generale des Douanes se retrouvait derriere
--  quatre entreprises doualaises. Un filet a fautes de frappe ne doit
--  pardonner que sur ce qu'on cherche — un nom.
--
--  `DROP` avant `ADD` : la definition d'une colonne generee ne se modifie
--  pas, et cette migration doit pouvoir etre rejouee sur une base ou la
--  premiere version de la colonne existe deja. L'index qui en depend tombe
--  avec elle et se recree en dessous.
-- ---------------------------------------------------------------------
ALTER TABLE correspondant DROP COLUMN IF EXISTS cible_recherche;

ALTER TABLE correspondant
  ADD COLUMN cible_recherche TEXT
  GENERATED ALWAYS AS (
      coalesce(raison_sociale, '') || ' ' ||
      coalesce(nom, '')            || ' ' ||
      coalesce(prenom, '')         || ' ' ||
      coalesce(sigle, '')
  ) STORED;

-- L'index GIN trigramme sert la similarite (`%`) **et** le `LIKE '%…%'` :
-- une seule structure pour la faute de frappe et pour la sous-chaine.
CREATE INDEX IF NOT EXISTS correspondant_trigrammes
    ON correspondant USING GIN (texte_recherche(cible_recherche) gin_trgm_ops);

-- ---------------------------------------------------------------------
--  Le vecteur plein texte porte desormais le sigle, au meme poids que la
--  raison sociale : « MINFI » n'est pas une precision sur l'entree, c'est
--  son autre nom.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION maj_recherche_correspondant() RETURNS TRIGGER AS $$
BEGIN
    NEW.recherche :=
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.raison_sociale,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent',
            coalesce(NEW.nom,'') || ' ' || coalesce(NEW.prenom,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.sigle,'')), 'A') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.ville,'')), 'C') ||
        setweight(to_tsvector('fr_unaccent', coalesce(NEW.courriel,'')), 'D');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

-- Les lignes existantes ne portent pas le sigle dans leur vecteur : le
-- declencheur est BEFORE UPDATE, une ecriture neutre suffit a le refaire.
UPDATE correspondant SET modifie_le = modifie_le;

-- ---------------------------------------------------------------------
--  Le seuil de la similarite par mot.
--
--  Par defaut 0,6. « minstere » compare a « ministere » vaut 0,58 : la
--  faute de frappe la plus banale — une lettre oubliee au milieu d'un mot
--  long — passait juste sous la barre. 0,5 l'attrape sans ouvrir la porte
--  aux rapprochements de hasard, qui plafonnent bien plus bas.
--
--  Pose sur la base et non par session : le seuil est une propriete de ce
--  referentiel, pas de qui l'interroge. Une session qui l'ignorerait
--  rendrait des resultats differents pour la meme frappe. Il ne prend effet
--  que sur les connexions ouvertes ensuite.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET pg_trgm.word_similarity_threshold = 0.5',
        current_database()
    );
END $$;
