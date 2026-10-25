-- ---------------------------------------------------------------------
--  Le profil du Cabinet du Directeur general.
--
--  Arbitrage du 28 aout 2026 : « c'est chez moi que l'on enregistre et que
--  l'on cote les ordres du directeur, car le directeur ne le fait pas ».
--
--  Le cabinet n'assiste pas le Directeur general : il fait le geste a sa
--  place. Trois consequences, et chacune est une permission.
-- ---------------------------------------------------------------------

INSERT INTO profil (code, libelle, systeme, description) VALUES
  ('CABINET', 'Cabinet du Directeur General', true,
   'Enregistre et cote au nom du Directeur general')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------
--  COT_DEL et non COT.
--
--  Les deux ouvrent la meme route. `COT` est portee par l'autorite qui
--  cote, `COT_DEL` par celui qui saisit la cotation d'un autre — et le
--  service distingue `decide_par` de `saisi_par`. C'est toute la question
--  ici : la decision reste celle du Directeur general, la frappe est celle
--  du cabinet. Donner `COT` au cabinet aurait inscrit le chef de service
--  comme decideur au registre, ce qui est faux et ne se rattrape pas.
--
--  Pas de `CONF` : le registre confidentiel a ses propres tenants
--  (ADR 024), et rien dans l'arbitrage ne dit que le cabinet en est.
--
--  Pas de `CLO` : clore un courrier n'est pas le coter. Le cabinet ouvre le
--  trajet, il ne le referme pas.
-- ---------------------------------------------------------------------
INSERT INTO profil_permission (profil_id, permission_id)
SELECT p.id, x.id
  FROM profil p, permission x
 WHERE p.code = 'CABINET'
   AND x.code IN ('LEC', 'ENR', 'COT_DEL', 'TRANS', 'IMP', 'STAT', 'DOS_LEC')
ON CONFLICT DO NOTHING;
