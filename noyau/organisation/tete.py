"""
La tete de structure — l'unite de consolidation.

Une **tete de structure** est un enfant direct de la Direction generale : les
dix directions du Port, les cinq divisions rattachees a la Direction generale,
le Cabinet et les trois representations. Dix-neuf en tout. Toute autre
structure — departement, cellule, service, secteur — a pour tete son ancetre a
cet etage.

La Direction generale n'est pas la racine de l'arbre : la planche inscrit le
Conseil d'administration au-dessus d'elle. Le Conseil est un `Organe` — il
delibere, il ne dirige pas — et la fonction `structure_tete_de` l'ecarte a ce
titre. Definir la tete comme « enfant direct de la racine » aurait fait
remonter le Port entier sous une tete unique, la Direction generale.

Ce module repond a quatre questions, et a elles seules :

    tete_de(structure)              a quel etage cette structure se compte
    responsable_de(structure)       qui la dirige
    responsable_a_relancer(...)     a qui la relance s'adresse
    consolide(utilisateur)          cet agent lit-il par tetes

**Ce module ne decide d'aucun acces.** La consolidation est une regle de
presentation ; le perimetre reste la regle d'acces, et il vit dans
`noyau/perimetre/portee.py`. Les melanger ferait dependre ce qu'un agent a le
droit de voir de la facon dont on l'affiche — exactement ce que la regle 1 de
`portee.py` interdit.

La tete est lue dans `structure.tete_id`, materialisee par le declencheur
`structure_tete_apres_ecriture` (migration 0024). Ne l'ecrivez jamais depuis
l'ORM : le declencheur la reprendrait au prochain deplacement, et les deux
verites divergeraient sans qu'aucune erreur ne le dise.
"""

from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Poste, Structure
from noyau.perimetre.modeles import PORTEE_TOUTES
from noyau.perimetre.portee import perimetre_en_vigueur


def tete_de(structure: Structure) -> Structure | None:
    """
    La tete de structure. Une tete est sa propre tete.

    `None` pour la racine de l'organigramme et pour les organes qui pendent
    au-dessus d'elle — le Conseil d'administration n'a pas de tete parce qu'il
    n'est pas dans la ligne hierarchique.
    """
    if structure.tete_id is None:
        return None
    if structure.tete_id == structure.pk:
        return structure
    # `structure.tete` et non une requete a la main : un appelant qui a pose
    # `select_related("...__structure__tete")` a deja la ligne en memoire, et
    # une boucle de lecture ferait sinon une requete par agent.
    return structure.tete


def responsable_de(structure: Structure) -> Utilisateur | None:
    """
    L'occupant du poste de tete de **cette** structure. `None` s'il est vacant.

    Ne remonte pas l'arbre : la remontee est une decision d'appelant, pas du
    socle. `responsable_a_relancer()` la prend ; un ecran qui affiche « dirige
    par » ne doit pas la prendre, sous peine de nommer un directeur a la tete
    d'un departement qu'il ne dirige pas.
    """
    poste = Poste.objects.filter(
        structure=structure, est_responsable=True, valide_au__isnull=True
    ).first()
    if poste is None:
        return None
    return Utilisateur.objects.actifs().filter(poste=poste).first()


def responsable_a_relancer(structure: Structure) -> Utilisateur | None:
    """
    Le directeur a qui la relance s'adresse : le responsable de la tete.

    Remonte l'arbre quand le poste est vacant — un departement dont le
    directeur n'est pas nomme se relance chez son directeur general. `None`
    lorsque aucun poste de tete n'est pourvu jusqu'a la racine : l'appelant
    doit alors **ne pas emettre** la relance et inscrire
    `relance_sans_destinataire`. Une relance envoyee dans le vide est pire
    qu'une relance absente — elle fait croire que l'escalade a eu lieu.
    """
    courante: Structure | None = tete_de(structure) or structure
    # Borne dure : l'organigramme du Port descend a cinq etages, et une
    # boucle dans `parent_id` ferait tourner cette fonction sans fin.
    for _ in range(10):
        if courante is None:
            return None
        agent = responsable_de(courante)
        if agent is not None:
            return agent
        courante = courante.parent
    return None


#: Les permissions qui ouvrent une vue d'ensemble, independamment du perimetre.
#:
#: La regle de visibilite a **trois** portes, pas une : le rattachement, la
#: cotation, et « une permission explicite de consolidation ». Un membre du
#: CODIR est en portee `sous_arbre` sur sa propre direction — il reste
#: directeur — mais le conseil des directeurs siege pour comparer les
#: directions entre elles. Ne lire que le perimetre lui aurait rendu
#: quarante-six cellules la ou il attend dix-neuf directions.
#:
#: Les codes sont ecrits en clair, et non pris sur `PERM` : cette enumeration
#: vit dans `noyau/habilitation/dependances.py`, qui importe django-ninja pour
#: la garde des routes. Le socle de lecture n'a pas a en dependre.
CONSOLIDATION = ("VUE_DG", "VUE_CODIR", "COCKPIT")


def consolide(utilisateur: Utilisateur) -> bool:
    """
    Vrai si l'agent lit le Port par tetes de structure.

    Deux chemins y menent, et il en faut deux :

     1. **le perimetre** — portee `toutes` (DSR, Directeur general,
        administration) ou portee posee sur la Direction generale ;
     2. **une permission de consolidation** — `VUE_DG`, `VUE_CODIR`,
        `COCKPIT`. C'est le cas du membre du CODIR, directeur d'une seule
        branche mais siegeant sur toutes.

    Sans perimetre en vigueur ni permission : faux. L'agent ne voit rien de
    toute facon (regle 3 de `portee.py`), et rendre vrai ferait consolider un
    ecran vide.
    """
    if possede(utilisateur, *CONSOLIDATION):
        return True

    perimetre = perimetre_en_vigueur(utilisateur)
    if perimetre is None:
        return False
    if perimetre.portee == PORTEE_TOUTES:
        return True
    # Portee bornee : elle ne deborde une tete que si elle est posee sur le
    # sommet de la ligne hierarchique. On le reconnait a son absence de tete,
    # et non a `parent_id IS NULL` : la Direction generale a le Conseil
    # d'administration pour parent sur la planche.
    return perimetre.structure is not None and perimetre.structure.tete_id is None


def regrouper(
    utilisateur: Utilisateur, structures: list[Structure]
) -> list[tuple[Structure, list[Structure]]]:
    """
    Les lignes d'un tableau qui itere des structures en Python.

    Rend, pour chaque ligne, la structure qui la **nomme** et celles sur
    lesquelles ses chiffres se **mesurent**. Pour qui ne consolide pas, les deux
    coincident et chaque structure fait sa ligne. Pour qui consolide, une ligne
    par tete, mesuree sur tout son sous-arbre.

    Pendant de `champ_regroupement()`, pour les tableaux qui ne passent pas par
    un `values()`. Les deux disent la meme regle ; les separer les aurait fait
    diverger au premier ecran.

    Le sommet de la ligne hierarchique et les organes deliberants sortent du
    regroupement consolide : ils n'ont pas de tete, et une Direction generale
    comparee a ses propres directions ne se compare a rien.
    """
    if not consolide(utilisateur):
        return [(structure, [structure]) for structure in structures]

    par_tete: dict[int, list[Structure]] = {}
    for structure in structures:
        if structure.tete_id is None:
            continue
        par_tete.setdefault(structure.tete_id, []).append(structure)

    tetes = {s.pk: s for s in structures if s.tete_id == s.pk}
    return [(tetes[tete_id], membres) for tete_id, membres in par_tete.items() if tete_id in tetes]


def champ_regroupement(utilisateur: Utilisateur, *, prefixe: str = "structure") -> str:
    """
    Le chemin ORM par lequel regrouper les lignes d'un tableau.

    « structure » pour un directeur, « structure__tete » pour qui consolide.
    `prefixe` sert les objets dont la structure est indirecte —
    `plan__structure` pour une activite lue depuis son plan d'actions.

    **Le seul point de passage.** Un `values("structure")` recopie a la main
    est un regroupement qui sera oublie au prochain tableau, et le Directeur
    general y verra reapparaitre les quarante-six cellules du Port.
    """
    return f"{prefixe}__tete" if consolide(utilisateur) else prefixe
