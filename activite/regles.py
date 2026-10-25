"""
L'etat d'une activite, et pourquoi elle est en retard.

**Un seul endroit decide.** Deux definitions du retard coexistaient dans le
projet ; les laisser toutes deux vivantes dans le code aurait garanti que deux
ecrans affichent deux chiffres. Elles convergent ici.

La regle appliquee est l'**arbitrage n° 2** : une activite est en retard quand
son echeance est passee et qu'elle n'est ni realisee ni suspendue. Elle est
retenue parce qu'elle a une source — le MODELE DE DONNEES v2 la cite comme un
arbitrage rendu — et non parce qu'elle serait plus juste.

L'autre definition, l'**ecart a un avancement attendu**, n'a aucune source :
elle a ete inventee par la conception. Elle reste calculable (`ecart_a_attendu`)
et affichable comme indication, mais **elle ne determine plus l'etat**. Ses deux
parametres restent en `hypothese`. Voir docs/questions-ouvertes.md, A2.

Le choix lui-meme est en base (`activite.definition_retard`, statut `acte`) :
le jour ou la DSR tranche autrement, c'est une ligne et non un redeploiement.

**Ce module ne fait pas foi seul.** La vue `v_activite_etat` applique la meme
regle en SQL, et c'est elle qui sert aux registres et aux agregats — on ne
parcourt pas deux cents activites en Python pour recalculer ce que le moteur
donne d'un `SELECT`. Le module sert aux cas unitaires (une fiche, un test) et
tient la definition ecrite en un francais lisible. Le filet
`test_les_deux_definitions_du_retard_concordent` verifie qu'elles ne divergent
pas.
"""

from datetime import date
from decimal import Decimal

from noyau.parametres.service import valeur

#: Les cinq etats affiches. Trois sont stockes (`Activite.ETATS`), deux se
#: deduisent des dates — arbitrage n° 2.
PROGRAMMEE = "programmee"
EN_COURS = "en_cours"
REALISEE = "realisee"
EN_RETARD = "en_retard"
SUSPENDUE = "suspendue"

#: Les deux valeurs que `activite.definition_retard` peut prendre.
ECHEANCE_DEPASSEE = "echeance_depassee"
ECART_A_ATTENDU = "ecart_a_attendu"


def definition_retard() -> str:
    """
    Laquelle des deux regles fait foi.

    Le defaut vaut l'arbitrage n° 2 : si la ligne manque, c'est la regle sourcee
    qui s'applique, jamais l'invention.
    """
    return valeur("activite.definition_retard", ECHEANCE_DEPASSEE)


def etat_affiche(activite, *, aujourd_hui: date | None = None) -> str:
    """
    L'etat tel que l'agent le voit.

    Ni stocke ni stockable : le retard survient par le seul passage du temps,
    sans qu'aucune ecriture n'ait lieu. Une colonne d'etat serait fausse le
    lendemain de son ecriture.
    """
    jour = aujourd_hui or date.today()

    # L'ordre compte. Une activite suspendue dont l'echeance est passee est
    # suspendue, pas en retard : la reprocher a la structure alors qu'une
    # autorite lui a interdit d'avancer serait faux.
    if activite.etat == SUSPENDUE:
        return SUSPENDUE
    if activite.etat == REALISEE:
        return REALISEE
    if activite.date_debut > jour:
        return PROGRAMMEE
    if est_en_retard(activite, aujourd_hui=jour):
        return EN_RETARD
    return EN_COURS


def est_en_retard(activite, *, aujourd_hui: date | None = None) -> bool:
    """
    Arbitrage n° 2 : echeance passee, et activite ni realisee ni suspendue.

    La seconde definition est implementee mais **jamais appliquee par defaut**.
    Elle n'est ici que pour que le jour de l'arbitrage se resume a changer une
    valeur en base — et pour que la comparaison entre les deux soit possible
    avant de trancher.
    """
    jour = aujourd_hui or date.today()

    if activite.etat in (REALISEE, SUSPENDUE):
        return False

    if definition_retard() == ECART_A_ATTENDU:
        seuil = valeur("activite.seuil_retard_points", 10)
        ecart = ecart_a_attendu(activite, aujourd_hui=jour)
        return ecart is not None and ecart < -seuil

    return activite.date_fin < jour


def avancement_attendu(activite, *, aujourd_hui: date | None = None) -> Decimal | None:
    """
    Ou l'activite devrait en etre, par interpolation lineaire sur sa periode.

    **Cette regle n'a aucune source** — `activite.mode_avancement_attendu` est
    en `hypothese`. Elle est calculee pour etre affichee a titre indicatif ;
    elle ne decide de rien tant que la DSR n'a pas tranche A2.

    Renvoie `None` quand l'activite n'a pas commence : un attendu de zero se
    lirait comme une mesure, alors qu'il n'y a rien a attendre encore.
    """
    jour = aujourd_hui or date.today()

    if jour < activite.date_debut:
        return None
    if jour >= activite.date_fin:
        return Decimal(100)

    duree = (activite.date_fin - activite.date_debut).days
    if duree <= 0:
        return Decimal(100)

    ecoule = (jour - activite.date_debut).days
    return (Decimal(100) * ecoule / duree).quantize(Decimal("0.01"))


def ecart_a_attendu(activite, *, aujourd_hui: date | None = None) -> Decimal | None:
    """
    Points d'avance (positif) ou de retard (negatif) sur l'attendu.

    Indicatif. Voir `avancement_attendu` pour la reserve qui pese dessus.
    """
    attendu = avancement_attendu(activite, aujourd_hui=aujourd_hui)
    if attendu is None:
        return None
    return activite.avancement_retenu - attendu
