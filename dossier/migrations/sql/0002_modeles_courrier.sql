-- =====================================================================
--  Bibliotheque des courriers-type — RF-SUI-05
--
--  Les corps sont ecrits en entier, avec leurs variables entre accolades.
--  Ils sont PLAUSIBLES et NON OFFICIELS : le formalisme du courrier du
--  Port autonome de Douala (en-tete, formules, references legales) n'a
--  pas ete fourni. A confronter au modele en vigueur avant la mise en
--  service. Voir A35 dans docs/questions-ouvertes.md.
--
--  `ON CONFLICT DO NOTHING` : la migration doit pouvoir se rejouer sur
--  une base ou l'administrateur a deja corrige un corps. Ecraser sa
--  correction serait pire que ne rien semer.
-- =====================================================================

--  `cree_le` est porte explicitement : `auto_now_add` est un comportement
--  Django, pas un defaut de colonne. Un semis SQL qui l'omet echoue sur la
--  contrainte NOT NULL — voir docs/pieges.md.
INSERT INTO modele_courrier
    (code, libelle, typologie, description, corps, actif, utilisations, cree_le)
VALUES
('MOD-ACC', 'Accusé de réception d''une demande', 'Accusé',
 'Confirme au demandeur la prise en charge et annonce le délai d''instruction.',
 'Objet : accusé de réception — {reference}

Madame, Monsieur,

Nous accusons réception de votre demande relative à {objet}, enregistrée le
{ouvertLe} sous la référence {reference}.

Son instruction est confiée à {structure}. Sauf pièce complémentaire à
produire, une réponse vous parviendra au plus tard le {echeance}.

Nous vous prions d''agréer, Madame, Monsieur, l''expression de notre
considération distinguée.

{instructeur}
{structure}', true, 0, now()),

('MOD-COMP', 'Demande de pièce complémentaire', 'Demande',
 'Réclame au demandeur une pièce manquante, sans suspendre le délai d''instruction.',
 'Objet : pièce complémentaire — {reference}

Madame, Monsieur,

L''instruction de votre demande {reference}, relative à {objet}, appelle la
production de la pièce suivante :

    {complement}

Nous vous remercions de nous la faire parvenir avant le {echeanceComplement}.

Nous vous prions d''agréer, Madame, Monsieur, l''expression de notre
considération distinguée.

{instructeur}
{structure}', true, 0, now()),

('MOD-FAV', 'Notification de décision favorable', 'Notification',
 'Notifie au demandeur une suite favorable et les conditions qui l''accompagnent.',
 'Objet : suite donnée à votre demande — {reference}

Madame, Monsieur,

Votre demande {reference}, relative à {objet}, a fait l''objet d''un examen
favorable.

{conditions}

Nous vous prions d''agréer, Madame, Monsieur, l''expression de notre
considération distinguée.

{instructeur}
{structure}', true, 0, now()),

('MOD-DEF', 'Notification de décision défavorable', 'Notification',
 'Notifie un rejet motivé et rappelle les voies de recours.',
 'Objet : suite donnée à votre demande — {reference}

Madame, Monsieur,

Votre demande {reference}, relative à {objet}, ne peut recevoir une suite
favorable, pour le motif suivant :

    {motif}

Cette décision peut faire l''objet d''un recours gracieux auprès de la
Direction générale dans un délai de deux mois à compter de sa notification.

Nous vous prions d''agréer, Madame, Monsieur, l''expression de notre
considération distinguée.

{instructeur}
{structure}', true, 0, now()),

('MOD-TRANS', 'Transmission pour attribution', 'Transmission',
 'Transmet le dossier à la structure compétente, le demandeur en étant informé.',
 'Objet : transmission pour attribution — {reference}

Le dossier {reference}, relatif à {objet}, relève de votre compétence.

Il vous est transmis pour attribution. Son échéance d''instruction est fixée
au {echeance} ; elle court depuis son ouverture et n''est pas reportée par la
présente transmission.

{instructeur}
{structure}', true, 0, now())
ON CONFLICT (code) DO NOTHING;
