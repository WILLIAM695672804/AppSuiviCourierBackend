"""
L'organigramme du Port autonome de Douala, transcrit du document officiel.

Source : « Organigramme du PAD Propose.pdf » (docs/), une planche A3 dressee
par la Direction generale le 10 novembre 2025. C'est le document que les
decisions de cadrage classaient parmi les trois reellement bloquants : sans
lui, les perimetres restaient theoriques.

Ce fichier est une **transcription**, pas une conception. Il ne decide rien ;
il recopie. Les endroits ou la planche laissait un doute sont marques
`# LECTURE` en clair et consignes dans `docs/questions-ouvertes.md` (A59 a
A62). Un doute resolu se corrige ici et se reporte la-bas — jamais l'inverse.

------------------------------------------------------------------------
  Comment lire la planche
------------------------------------------------------------------------

La planche superpose deux informations que le schema separe, et les confondre
est la seule facon de se tromper en la relisant :

  * le **nom** de la boite dit ce qu'est la structure — Direction, Division,
    Cellule, Departement, Service, Centre, Cabinet, Representation. C'est
    `structure.nature`.

  * la **couleur** de la boite dit le rang de son responsable, et la legende
    l'ecrit noir sur blanc : bleu = directeur, vert = directeur adjoint,
    saumon = sous-directeur, blanc = chef de service. C'est
    `structure.niveau_hierarchique`, et le rang du poste de responsable.

Les deux ne coincident pas. Le Cabinet du Directeur general est une boite
blanche : rang de chef de service, malgre le nom. Un Departement de la DSI est
saumon, un Departement du Cabinet n'existe pas. Suivre le nom plutot que la
couleur reclasserait la moitie de l'organigramme.

------------------------------------------------------------------------
  Les codes
------------------------------------------------------------------------

**La planche ne porte aucun sigle.** `structure.code` est pourtant obligatoire
et sert partout — colonne des tableaux, cle du classement, libelle court des
selecteurs. Les codes ci-dessous sont donc construits, selon une regle unique :
sigle usuel pour les directions et divisions rattachees a la Direction
generale, puis chainage par tiret pour ce qui descend (`DSI-GL`). Ils sont une
**hypothese** — A59. Le jour ou le Port communique sa propre nomenclature, ce
fichier se corrige et la commande `charger_organigramme` rejoue : elle clot les
anciennes lignes, elle n'en detruit aucune.
"""

from __future__ import annotations

# ---------------------------------------------------------------------
#  Les rangs de la legende.
#
#  Ce sont des codes de `niveau_hierarchique`, semes par la migration
#  0017. Ils ne sont pas ecrits dans le code applicatif — principe 3 de
#  `modeles.py` — mais une transcription doit bien nommer ce qu'elle
#  transcrit.
# ---------------------------------------------------------------------
DG = "DG"  # la Direction generale elle-meme, rang 1
DIR = "DIR"  # bleu   — rang de directeur
DIR_ADJ = "DIR_ADJ"  # vert   — rang de directeur adjoint
SOUS_DIR = "SOUS_DIR"  # saumon — rang de sous-directeur
SERV = "SERV"  # blanc  — rang de chef de service

# ---------------------------------------------------------------------
#  L'arbre.
#
#  (code, libelle, code du parent, niveau, nature)
#
#  **L'ordre n'est pas decoratif** : un parent est toujours declare avant
#  ses enfants, et le chargeur s'y fie. Ne triez pas cette liste.
# ---------------------------------------------------------------------
STRUCTURES: list[tuple[str, str, str | None, str, str]] = [
    # -----------------------------------------------------------------
    #  Le sommet
    # -----------------------------------------------------------------
    # LECTURE (A60) : le Conseil d'administration figure sur la planche, au
    # dessus de la Direction generale. Il n'est pas une direction : c'est
    # l'organe deliberant, il ne recoit pas de cotation et n'a pas d'agents.
    # Il est inscrit parce que le document l'inscrit — l'omettre aurait fait
    # de la Direction generale la racine, ce que la planche ne dit pas — et sa
    # nature « Organe » le distingue de tout ce qui travaille.
    ("CA", "Conseil d'Administration", None, DIR, "Organe"),
    ("DG", "Direction Générale", "CA", DG, "Direction"),
    # -----------------------------------------------------------------
    #  Le Cabinet et ses services
    #
    #  Boites blanches : rang de chef de service, y compris le Cabinet.
    #  C'est ici qu'entre le courrier — le Service du courrier central
    #  releve du Cabinet, et non de la Direction generale directement.
    # -----------------------------------------------------------------
    ("CAB", "Cabinet du Directeur Général", "DG", SERV, "Cabinet"),
    ("CAB-SEC-DG", "Secrétariat DG", "CAB", SERV, "Service"),
    ("CAB-SEC-DGA", "Secrétariat DGA", "CAB", SERV, "Service"),
    ("SCC", "Service du Courrier Central", "CAB", SERV, "Service"),
    ("CAB-APF", "Service de l'Accueil, du Protocole et de la Facilitation", "CAB", SERV, "Service"),
    ("CAB-SIS", "Service de l'Information Sécuritaire", "CAB", SERV, "Service"),
    # LECTURE (A61) : sur la planche, le Centre de la documentation et des
    # archives et la Cellule de la traduction pendent d'un trait qui descend du
    # Cabinet, sans que le point d'attache soit franc. Ils sont rattaches au
    # Cabinet — c'est la lecture la plus proche du trace. Leur rang, lui, est
    # certain : saumon, sous-directeur.
    ("CDA", "Centre de la Documentation et des Archives", "CAB", SOUS_DIR, "Centre"),
    (
        "CAB-TIB",
        "Cellule de la Traduction, de l'Interprétariat et de la Promotion du Bilinguisme",
        "CAB",
        SOUS_DIR,
        "Cellule",
    ),
    # -----------------------------------------------------------------
    #  Les divisions rattachees a la Direction generale
    #
    #  Boites bleues : rang de directeur, au meme etage que les dix
    #  directions metier. Leurs cellules sont saumon.
    # -----------------------------------------------------------------
    ("DQDD", "Division de la Qualité et du Développement Durable", "DG", DIR, "Division"),
    ("DQDD-QUA", "Cellule Qualité", "DQDD", SOUS_DIR, "Cellule"),
    (
        "DQDD-DDR",
        "Cellule du Développement Durable et des Relations avec les Communautés Riveraines",
        "DQDD",
        SOUS_DIR,
        "Cellule",
    ),
    ("DSR", "Division du Suivi et de la Relance", "DG", DIR, "Division"),
    ("DAI", "Division de l'Audit Interne", "DG", DIR, "Division"),
    (
        "DAPC",
        "Division de l'Analyse, de la Prospective et de la Coopération",
        "DG",
        DIR,
        "Division",
    ),
    ("DAPC-AS", "Cellule de l'Analyse et des Statistiques", "DAPC", SOUS_DIR, "Cellule"),
    (
        "DAPC-EPP",
        "Cellule des Études, des Partenariats et de la Prospective",
        "DAPC",
        SOUS_DIR,
        "Cellule",
    ),
    ("DAPC-COO", "Cellule de la Coopération", "DAPC", SOUS_DIR, "Cellule"),
    (
        "DAPC-FER",
        "Cellule de Facilitation des Échanges et de Régulation des Activités Maritimes",
        "DAPC",
        SOUS_DIR,
        "Cellule",
    ),
    ("DCRP", "Division de la Communication et des Relations Publiques", "DG", DIR, "Division"),
    ("DCRP-COM", "Cellule de la Communication", "DCRP", SOUS_DIR, "Cellule"),
    ("DCRP-RP", "Cellule des Relations Publiques", "DCRP", SOUS_DIR, "Cellule"),
    # -----------------------------------------------------------------
    #  Les representations exterieures
    #
    #  LECTURE (A62) : la planche ne montre qu'une boite verte,
    #  « Representations du PAD (Bangui, N'Djamena, Yaounde) ». Trois
    #  structures et non une : le Port n'a pas une representation en trois
    #  villes mais une representation par ville, et une cotation adressee
    #  a « la representation » ne designerait personne. La boite unique
    #  est une economie de place sur une planche A3.
    # -----------------------------------------------------------------
    ("REP-BGF", "Représentation du PAD à Bangui", "DG", DIR_ADJ, "Representation"),
    ("REP-NDJ", "Représentation du PAD à N'Djamena", "DG", DIR_ADJ, "Representation"),
    ("REP-YAO", "Représentation du PAD à Yaoundé", "DG", DIR_ADJ, "Representation"),
    # -----------------------------------------------------------------
    #  1. Direction de la Capitainerie
    # -----------------------------------------------------------------
    ("DCAP", "Direction de la Capitainerie", "DG", DIR, "Direction"),
    ("DCAP-NAV", "Département de la Navigation", "DCAP", SOUS_DIR, "Departement"),
    ("DCAP-SUR", "Département de la Sûreté et de la Sécurité", "DCAP", SOUS_DIR, "Departement"),
    (
        "DCAP-SIP",
        "Département Sécurité-Incendie-Pollution Portuaire",
        "DCAP",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  2. Direction de l'Exploitation
    # -----------------------------------------------------------------
    ("DEXP", "Direction de l'Exploitation", "DG", DIR, "Direction"),
    (
        "DEXP-ESA",
        "Département des Études et du Suivi-Évaluation des Activités Transférées",
        "DEXP",
        SOUS_DIR,
        "Departement",
    ),
    ("DEXP-OP", "Division des Opérations Portuaires", "DEXP", DIR_ADJ, "Division"),
    (
        "DEXP-OP-ECD",
        "Département des Études et du Contrôle du Domaine",
        "DEXP-OP",
        SOUS_DIR,
        "Departement",
    ),
    ("DEXP-OP-SAP", "Les Secteurs d'Activités Portuaires", "DEXP-OP", SOUS_DIR, "Secteur"),
    (
        "DEXP-CFM",
        "Division du Contrôle de la Facturation et du Marketing",
        "DEXP",
        DIR_ADJ,
        "Division",
    ),
    (
        "DEXP-CFM-CF",
        "Département du Contrôle de la Facturation",
        "DEXP-CFM",
        SOUS_DIR,
        "Departement",
    ),
    ("DEXP-CFM-MKT", "Département du Marketing", "DEXP-CFM", SOUS_DIR, "Departement"),
    # -----------------------------------------------------------------
    #  3. Direction du Dragage et de la Logistique Maritime
    # -----------------------------------------------------------------
    ("DDLM", "Direction du Dragage et de la Logistique Maritime", "DG", DIR, "Direction"),
    (
        "DDLM-LES",
        "Département Logistique, Exploitation et Signalisation Maritime",
        "DDLM",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DDLM-EPD",
        "Département des Études et de la Programmation du Dragage",
        "DDLM",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DDLM-MEN",
        "Département de la Maintenance des Engins, Équipements Nautiques et Connexes",
        "DDLM",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  4. Direction des Amenagements Portuaires
    # -----------------------------------------------------------------
    ("DAMP", "Direction des Aménagements Portuaires", "DG", DIR, "Direction"),
    ("DAMP-INF", "Département des Infrastructures Portuaires", "DAMP", SOUS_DIR, "Departement"),
    (
        "DAMP-CRB",
        "Département de la Construction et de la Réhabilitation des Bâtiments",
        "DAMP",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DAMP-ETA",
        "Division des Études Techniques d'Aménagement Portuaire",
        "DAMP",
        DIR_ADJ,
        "Division",
    ),
    (
        "DAMP-ETA-EMD",
        "Département des Études et du Montage des Dossiers de Consultation",
        "DAMP-ETA",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  5. Direction des Ressources Humaines
    # -----------------------------------------------------------------
    ("DRH", "Direction des Ressources Humaines", "DG", DIR, "Direction"),
    ("DRH-CMS", "Centre Médico-Social", "DRH", SOUS_DIR, "Centre"),
    ("DRH-GP", "Département Gestion du Personnel", "DRH", SOUS_DIR, "Departement"),
    (
        "DRH-FDC",
        "Département de la Formation et du Développement des Compétences",
        "DRH",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  6. Direction des Finances et de la Comptabilite
    # -----------------------------------------------------------------
    ("DFC", "Direction des Finances et de la Comptabilité", "DG", DIR, "Direction"),
    ("DFC-FIN", "Division des Finances", "DFC", DIR_ADJ, "Division"),
    ("DFC-FIN-CR", "Département du Contrôle du Recouvrement", "DFC-FIN", SOUS_DIR, "Departement"),
    (
        "DFC-FIN-AIM",
        "Département de l'Analyse, de l'Ingénierie et de la Modélisation Financière",
        "DFC-FIN",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DFC-FIN-OFT",
        "Département des Opérations Financières et de Trésorerie",
        "DFC-FIN",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DFC-CPT",
        "Département de la Comptabilité et de la Fiscalité",
        "DFC",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  7. Direction du Controle de Gestion
    # -----------------------------------------------------------------
    ("DCG", "Direction du Contrôle de Gestion", "DG", DIR, "Direction"),
    (
        "DCG-ORG",
        "Département de l'Organisation et des Méthodes",
        "DCG",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DCG-ACB",
        "Département de l'Analyse et du Contrôle Budgétaire",
        "DCG",
        SOUS_DIR,
        "Departement",
    ),
    ("DCG-MPE", "Département de Mesure de la Performance", "DCG", SOUS_DIR, "Departement"),
    # -----------------------------------------------------------------
    #  8. Direction des Affaires Generales
    # -----------------------------------------------------------------
    ("DAG", "Direction des Affaires Générales", "DG", DIR, "Direction"),
    ("DAG-MP", "Division des Marchés Publics", "DAG", DIR_ADJ, "Division"),
    (
        "DAG-MP-MAT",
        "Département de la Maturation, de la Programmation, du Contrôle"
        " et du Monitoring des Marchés",
        "DAG-MP",
        SOUS_DIR,
        "Departement",
    ),
    ("DAG-MP-MAR", "Département des Marchés", "DAG-MP", SOUS_DIR, "Departement"),
    ("DAG-AC", "Département des Affaires Communes", "DAG", SOUS_DIR, "Departement"),
    # LECTURE (A61) : ces deux departements pendent d'un trait qui court sous
    # la Division des marches publics sans s'y raccorder franchement. Ils sont
    # rattaches a la Direction des affaires generales : la gestion du
    # patrimoine et les approvisionnements ne sont pas des marches publics.
    ("DAG-PAT", "Département de la Gestion du Patrimoine", "DAG", SOUS_DIR, "Departement"),
    ("DAG-APP", "Département Gestion des Approvisionnements", "DAG", SOUS_DIR, "Departement"),
    # -----------------------------------------------------------------
    #  9. Direction des Systemes d'Information
    # -----------------------------------------------------------------
    ("DSI", "Direction des Systèmes d'Information", "DG", DIR, "Direction"),
    (
        "DSI-SSI",
        "Département de la Sécurité des Systèmes d'Information",
        "DSI",
        SOUS_DIR,
        "Departement",
    ),
    ("DSI-GL", "Département Génie Logiciel", "DSI", SOUS_DIR, "Departement"),
    (
        "DSI-ISI",
        "Département des Infrastructures et Systèmes Informatiques",
        "DSI",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DSI-TR",
        "Département des Télécommunications et des Réseaux",
        "DSI",
        SOUS_DIR,
        "Departement",
    ),
    # -----------------------------------------------------------------
    #  10. Direction des Affaires Juridiques
    # -----------------------------------------------------------------
    ("DAJ", "Direction des Affaires Juridiques", "DG", DIR, "Direction"),
    (
        "DAJ-RTA",
        "Département de la Réglementation, des Traités et des Actes",
        "DAJ",
        SOUS_DIR,
        "Departement",
    ),
    (
        "DAJ-EJC",
        "Département des Études Juridiques et du Contentieux",
        "DAJ",
        SOUS_DIR,
        "Departement",
    ),
    ("DAJ-RF", "Département du Recouvrement Forcé", "DAJ", SOUS_DIR, "Departement"),
]

# ---------------------------------------------------------------------
#  Les postes.
#
#  (code de la structure, libelle du poste, niveau, effectif prevu)
#
#  Deux familles s'y melangent, et il faut savoir laquelle on lit :
#
#  1. **Le poste de responsable**, que le chargeur ouvre tout seul pour
#     chaque structure de `STRUCTURES`, au rang de la structure. Il n'est
#     pas dans cette liste — l'y ecrire cent fois n'aurait rien appris.
#     Son libelle se deduit du rang : « Directeur de … », « Chef de
#     division … ». Voir `libelle_du_responsable` plus bas.
#
#  2. **Les postes que la planche dessine a part**, dans des boites
#     laterales rattachees a une structure sans en etre une :
#     « Attaches (02) » a cote de la Division du suivi et de la relance,
#     « Auditeurs principaux (03) » a cote de l'audit interne. Le nombre
#     entre parentheses est l'effectif, et il vient du document : c'est
#     la seule donnee d'effectif que le Port ait ecrite.
#
#  Tout poste cree ici est **vacant**. Nommer un agent releve de la DRH,
#  par l'ecran d'administration ou par `services.affecter()` — jamais par
#  cette commande, qui ne connait le nom de personne.
# ---------------------------------------------------------------------
POSTES: list[tuple[str, str, str, int]] = [
    # Les deux boites saumon posees a gauche de la Direction generale.
    # La planche ne donne pas leur nombre : effectif 1, faute de mieux.
    ("DG", "Attaché de direction", SOUS_DIR, 1),
    ("DG", "Conseiller technique", SOUS_DIR, 1),
    # Les boites blanches chiffrees. Le nombre est celui de la planche.
    ("DSR", "Attaché de suivi", SERV, 2),
    ("DAI", "Auditeur principal", SERV, 3),
    # LECTURE (A62) : « Les Secteurs d'activites portuaires (04) » est dessine
    # comme une structure — boite saumon dans l'arbre — mais compte quatre
    # unites. Faute de savoir comment les quatre se nomment, la structure est
    # unique et le poste de chef de secteur porte l'effectif. Le jour ou le
    # Port les nomme, ce sont quatre structures soeurs, et ce poste disparait.
    ("DEXP-OP-SAP", "Chef de secteur d'activités portuaires", SOUS_DIR, 4),
]

# ---------------------------------------------------------------------
#  Le libelle du poste de responsable, par rang.
#
#  Une table et non une regle : « Chef de division » ne se deduit pas de
#  « Division » par une transformation de chaine, et l'ecrire ainsi
#  produirait « Chef de cabinet du Directeur general » la ou le Port dit
#  « Directeur de cabinet ».
# ---------------------------------------------------------------------
LIBELLE_RESPONSABLE: dict[str, str] = {
    DG: "Directeur Général",
    DIR: "Directeur",
    DIR_ADJ: "Directeur Adjoint",
    SOUS_DIR: "Sous-Directeur",
    SERV: "Chef de Service",
}

#: Les structures qui ne portent pas de poste de responsable.
#:
#: Le Conseil d'administration est un organe deliberant : il n'a ni agent, ni
#: poste, ni cotation. Lui ouvrir un poste de responsable en ferait un echelon
#: de traitement du courrier, ce qu'il n'est pas.
SANS_RESPONSABLE = frozenset({"CA"})


def libelle_du_responsable(libelle_structure: str, niveau: str) -> str:
    """
    Le libelle du poste qui dirige une structure.

    Forme retenue : « <rang> — <structure> », par exemple
    « Directeur — Direction des Systèmes d'Information ». Le rang seul se
    repeterait quarante fois dans les selecteurs sans qu'on sache lequel ;
    la structure seule ne dirait pas qu'il s'agit du poste de tete.
    """
    return f"{LIBELLE_RESPONSABLE[niveau]} — {libelle_structure}"
