"""
Regles de conversion du plan d'actions 2026 de la DFC vers le modele.

Le classeur source (`PLAN_ACTIONS_2026_DFC.xlsx`, 36 lignes) decrit le meme
objet que `activite.Activite`, mais dans le vocabulaire budgetaire de
l'institution. Trois choses n'y figurent pas sous la forme que le modele
exige, et ce fichier porte les regles qui comblent l'ecart.

**Chaque regle est marquee.** `SUR` : la correspondance est etablie par le
libelle lui-meme, sans interpretation. `A_VALIDER` : c'est une proposition,
qui engage une lecture du metier. Voir `docs/questions-ouvertes.md`.

**Rien ne bloque l'import** — arbitrage de William du 9 septembre 2026 : ce
qui ne se rapproche pas est laisse vide, et se complete depuis l'application.
Un sigle sans cible n'associe aucune structure ; une valeur cible non
convertible ne cree pas d'indicateur ; une periode absente couvre l'exercice.
La colonne `a_completer` du tableau nomme, ligne a ligne, ce qui reste a
saisir a l'ecran.

Le prix de ce choix doit etre dit : une activite importee avec un axe propose
et sans structure associee **a l'air complete**. Rien a l'ecran ne la
distingue d'une activite verifiee. C'est `activites.csv` qui garde la trace
de ce qui a ete devine, et lui seul.
"""

from __future__ import annotations

SUR = "sur"
A_VALIDER = "a_valider"

# ---------------------------------------------------------------------
#  1. Sigles de responsables -> structures de l'organigramme reel
#
#  Le classeur nomme les responsables par des sigles d'usage, qui ne sont
#  pas ceux du referentiel. Sept sur dix-neuf s'y retrouvent tels quels ;
#  les autres demandent une lecture.
#
#  Les `Dp*` sont les departements de la DFC, et leur developpement est
#  lisible dans le sigle meme (`DpCFI` = Comptabilite et FIscalite). Les
#  quatre derniers ne se laissent pas deviner : ils restent sans cible, et
#  l'import refusera de tourner tant qu'ils n'auront pas ete tranches.
# ---------------------------------------------------------------------
STRUCTURES: dict[str, tuple[str | None, str, str]] = {
    # sigle du fichier   (sigle en base, certitude, justification)
    "DFC": ("DFC", SUR, "identique"),
    "DDLM": ("DDLM", SUR, "identique"),
    "DSR": ("DSR", SUR, "identique"),
    "DSI": ("DSI", SUR, "identique"),
    "DRH": ("DRH", SUR, "identique"),
    "DAJ": ("DAJ", SUR, "identique"),
    "DCRP": ("DCRP", SUR, "identique"),
    "DpCFI": ("DFC-CPT", A_VALIDER, "Departement de la Comptabilite et de la Fiscalite"),
    "DpCREC": ("DFC-FIN-CR", A_VALIDER, "Departement du Controle du Recouvrement"),
    "DpFOT": ("DFC-FIN-OFT", A_VALIDER, "Departement des Operations Financieres et de Tresorerie"),
    "DPOFT": ("DFC-FIN-OFT", A_VALIDER, "meme departement, graphie differente dans le classeur"),
    "DIVF": ("DFC-FIN", A_VALIDER, "Division des Finances"),
    "DEX": ("DEXP", A_VALIDER, "Direction de l'Exploitation"),
    "DAP": ("DAPC", A_VALIDER, "arbitrage du 7 septembre 2026 pour les comptes de test"),
    # Quatre sigles absents de l'organigramme, tranches par William le
    # 10 septembre 2026 sur le contexte de leur ligne : la tache, l'indicateur
    # et les structures citees a cote. Aucun ne se deduit du sigle seul.
    "BC": ("DCG-ACB", A_VALIDER, "lu Budget/Controle — la ligne parle de rapports de controle"),
    "CCODRCV": ("DQDD-DDR", A_VALIDER, "developpement durable — ligne « finance verte »"),
    "DCOA": ("DAJ-RF", A_VALIDER, "recouvrement force — ligne « plan de recouvrement »"),
    # « SCO » redit le departement de la Comptabilite, deja cite par « DpCFI »
    # sur la meme ligne : il n'ajoute aucune structure.
    "SCO": (None, A_VALIDER, "redite de DFC-CPT, deja associe par DpCFI"),
    # Mention collective, sans destinataire : elle ne rattache rien.
    "AUTRES STRUCTURES": (None, SUR, "mention collective, volontairement ignoree"),
}

# ---------------------------------------------------------------------
#  2. Periodes d'execution -> `date_debut` / `date_fin`
#
#  `Activite.date_debut` et `date_fin` sont non nulles. Or la colonne du
#  classeur melange deux natures : des periodes ("Aout-Nov.") et des
#  **rythmes** ("Mensuel", "Au jour le jour"). Un rythme n'est pas une
#  periode : faute de mieux, il couvre l'exercice entier, et le texte
#  d'origine est conserve dans `Activite.resultats_attendus` pour que la
#  fiche ne perde pas l'information.
#
#  Les mois sont bornes sur l'exercice 2026.
# ---------------------------------------------------------------------
PERIODES: dict[str, tuple[str, str, str, str]] = {
    # texte du fichier                    (debut,  fin,     certitude, nature)
    "Jan-Déc": ("01-01", "12-31", SUR, "periode"),
    "Jan-Dec": ("01-01", "12-31", SUR, "periode"),
    "Janv-Dec": ("01-01", "12-31", SUR, "periode"),
    "JANV-DEC": ("01-01", "12-31", SUR, "periode"),
    "Janvier à Décembre": ("01-01", "12-31", SUR, "periode"),
    "Aout-Nov.": ("08-01", "11-30", SUR, "periode"),
    "Mai-Sept": ("05-01", "09-30", SUR, "periode"),
    "Juil-Déc": ("07-01", "12-31", SUR, "periode"),
    "Aout": ("08-01", "08-31", SUR, "mois unique"),
    "Déc": ("12-01", "12-31", SUR, "mois unique"),
    # Sequences : l'enveloppe du premier au dernier mois cite.
    "Fev-Mai / Mai-Juil / Aout": ("02-01", "08-31", A_VALIDER, "enveloppe de trois jalons"),
    "Jan / Jan / Fev / Mars": ("01-01", "03-31", A_VALIDER, "enveloppe de quatre jalons"),
    # « Nov » precede « Fev-Mars » : soit l'exercice precedent, soit un
    # ordre de redaction. Non tranchable depuis le classeur.
    "Nov / Fev-Mars / Avril-Mai": ("01-01", "12-31", A_VALIDER, "ordre des jalons incoherent"),
    # Rythmes : couvrent l'exercice, le texte d'origine est conserve.
    "Mensuel": ("01-01", "12-31", A_VALIDER, "rythme"),
    "Mensuelle": ("01-01", "12-31", A_VALIDER, "rythme"),
    "Annuel": ("01-01", "12-31", A_VALIDER, "rythme"),
    "semestrielle": ("01-01", "12-31", A_VALIDER, "rythme"),
    "Au jour le jour": ("01-01", "12-31", A_VALIDER, "rythme"),
    "Au plus tard le 15 de chaque mois": ("01-01", "12-31", A_VALIDER, "rythme"),
}

# ---------------------------------------------------------------------
#  3. Axes strategiques
#
#  Le classeur porte une hierarchie **budgetaire** (programme, action,
#  activite) ; le modele exige un axe **strategique**, pris dans un
#  referentiel ferme de trois entrees. Les deux ne se recouvrent pas, et
#  aucune regle mecanique ne les relie.
#
#  Proposition par activite budgetaire, avec quatre exceptions au niveau de
#  la ligne. Tout est `A_VALIDER` : c'est une lecture du metier, elle
#  n'appartient pas a l'assistant.
#
#    A1  Port attractif et performant a l'aide des services surs et de qualite
#    A2  Port competitif par la fluidite du passage portuaire, a travers
#        l'amelioration et la densification de l'outil de production
#    A3  Port innovant, digital et societalement responsable
# ---------------------------------------------------------------------
#: Libelles courts exacts, tels que le referentiel les porte. `_axe()` les
#: compare caractere par caractere : un accent manquant rend « axe inconnu ».
LIBELLES_AXES: dict[str, str] = {
    "A1": "Port attractif et performant",
    "A2": "Port compétitif et fluide",
    "A3": "Port innovant et responsable",
}

AXE_PAR_ACTIVITE_BUDGETAIRE: dict[str, tuple[str, str]] = {
    "2205": ("A2", "gouvernance de l'action 22, qui porte les infrastructures"),
    "3101064": ("A3", "deontologie et ethique : responsabilite societale"),
    "3205": ("A1", "protection du patrimoine : performance interne"),
    "3207": ("A1", "gestion financiere"),
    "3208": ("A1", "comptabilite financiere"),
    "3209": ("A1", "controle du recouvrement"),
    "3210": ("A1", "controle du recouvrement et fiscalite"),
    "3215": ("A1", "activites transversales de la direction"),
}

#: Exceptions au niveau de la ligne, sur le code a sept chiffres.
AXE_PAR_LIGNE: dict[str, tuple[str, str]] = {
    "3207034": ("A3", "dematerialisation des titres"),
    "3207037": ("A3", "dematerialisation du systeme de paiement"),
    "3208025": ("A3", "finance verte"),
}

# ---------------------------------------------------------------------
#  4. Valeurs cibles
#
#  La colonne melange des taux ("100%"), des comptes ("1", "9", "12") et
#  une serie ("1 / 1 / 2"), pour un champ `valeur_cible` qui est un decimal
#  unique. Les deux premieres natures se convertissent sans perte ; la
#  serie n'a pas de traduction evidente et reste a trancher.
# ---------------------------------------------------------------------
CIBLES: dict[str, tuple[str | None, str | None, str]] = {
    # texte      (valeur, unite, certitude)
    "100%": ("100", "%", SUR),
    "1": ("1", None, SUR),
    "4": ("4", None, SUR),
    "9": ("9", None, SUR),
    "12": ("12", None, SUR),
    "13": ("13", None, SUR),
    "18": ("18", None, SUR),
    # Trois echeances dans une cellule : un seul indicateur a 4, ou trois
    # indicateurs distincts ? La fiche ne dit pas la meme chose selon le
    # choix. Aucun indicateur n'est cree ; il se saisit a l'ecran.
    "1 / 1 / 2": (None, None, A_VALIDER),
}


# ---------------------------------------------------------------------
#  5. Periode par defaut
#
#  `date_debut` et `date_fin` sont non nulles : une activite sans periode
#  ne peut pas exister. La ligne 13 du classeur n'en porte aucune — la
#  saisie s'y arrete a la valeur cible. Elle couvre donc l'exercice, et la
#  colonne `a_completer` le signale.
# ---------------------------------------------------------------------
PERIODE_PAR_DEFAUT = ("01-01", "12-31")
