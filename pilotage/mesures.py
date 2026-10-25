"""
Les mesures du pilotage, en un seul endroit.

Sept ecrans lisent les memes chiffres : le cockpit, le tableau de bord d'une
structure, les analyses croisees, les statistiques, la note de synthese et les
deux vues d'ensemble. **Si chacun les recalculait a sa facon, l'institution
lirait deux taux d'execution differents le meme matin** — et c'est le genre
d'ecart qui detruit la confiance dans l'outil bien plus surement qu'une panne.

Ce module ne rend donc aucune reponse d'ecran : il rend des mesures nues, que
les modules de restitution mettent en forme.

**Ce qui n'est pas mesurable rend `None`.** Jamais zero. Le pilier courrier
n'existe pas ; un taux de courrier a zero aurait fait paraitre en faillite
toute une institution qui n'a simplement pas encore l'outil. C'est la regle de
l'ADR 011, et elle vaut pour tout ce qui suit.

Depuis la mise en service du pilier dossiers, `instruction_dossiers` **mesure**
au lieu de rendre `None` : c'est la moitie de la question A30 qui se ferme. Le
`None` qu'elle rend encore ne veut plus dire « pas d'outil » mais « aucun
dossier clos » — et les deux ne se corrigent pas de la meme facon.
"""

from calendar import monthrange
from datetime import date

from django.db import connection
from django.db.models import QuerySet

from activite.modeles import Activite, Obligation
from dossier.lecture import instruction_dans_le_delai
from gouvernance.modeles import Disponibilite, Engagement, VueEngagementEtat
from noyau.calendrier import mois_precedent
from noyau.organisation.modeles import Structure

#: Ce qui accompagne une mesure de courrier absente **faute de matiere**, et non
#: faute d'outil : la cloture est en service depuis le 27 aout 2026, mais une
#: structure qui n'a referme aucun courrier sur la periode n'a pas de taux. Le
#: texte le dit, pour que l'agent ne lise pas une panne.
SANS_COURRIER_CLOS = (
    "Aucun courrier clôturé sur la période : le taux se calculera à la première clôture."
)

#: Les dossiers, eux, **sont** mesures depuis la mise en service du pilier. Ce
#: texte ne dit plus « pas d'outil » mais « pas encore de matiere » : une
#: structure qui n'a cloture aucun dossier n'instruit pas mal, elle n'a pas
#: fini. La nuance compte pour l'agent qui lit « non mesuré » sur son ecran.
SANS_DOSSIERS_CLOS = (
    "Aucun dossier clos sur la période : le taux se calculera à la première clôture."
)


# =====================================================================
#  Les activites
# =====================================================================


def activites_de(structures: QuerySet | list[Structure] | None = None) -> QuerySet:
    """
    Les activites vivantes, bornees aux structures passees.

    `None` signifie « toutes » : le cockpit et les vues d'ensemble sont
    institutionnels par construction. Passer la liste complete des structures
    aurait produit un `IN` de plusieurs centaines d'identifiants pour le meme
    resultat.
    """
    requete = Activite.objects.filter(invalide_le__isnull=True)
    if structures is None:
        return requete
    return requete.filter(plan__structure__in=structures)


def execution_activites(
    structures: QuerySet | list[Structure] | None = None,
    *,
    a_la_date: date | None = None,
) -> float | None:
    """
    L'avancement moyen des activites commencees — le taux du §3.1.

    Moyenne simple des avancements calcules, et non ponderee par le budget :
    ponderer serait une invention de plus, et `activite/lecture.py` a deja
    tranche dans ce sens pour le plan d'actions.

    `None` quand aucune activite n'a commence : une moyenne sur zero ligne
    n'est pas zero pour cent, c'est l'absence de mesure.
    """
    fin = a_la_date or date.today()
    lignes = activites_de(structures).filter(date_debut__lte=fin)

    total = 0.0
    nombre = 0
    # `avancement_retenu` et non `avancement_calcule` : un taux que la DSR a
    # rejete ne doit pas remonter dans la moyenne d'une direction (ADR 030).
    for avancement in lignes.values_list("avancement_retenu", flat=True):
        total += float(avancement)
        nombre += 1

    return round(total / nombre, 1) if nombre else None


def activites_a_l_heure(
    structures: QuerySet | list[Structure] | None = None,
    *,
    a_la_date: date | None = None,
) -> tuple[int, int]:
    """
    Combien d'activites ne sont pas en retard, sur combien de commencees.

    L'etat vient de `v_activite_etat` et non de la colonne `etat` : celle-ci ne
    connait pas le retard, qui se deduit des dates (arbitrage n° 2 du pilier
    activites).
    """
    fin = a_la_date or date.today()
    filtre = ""
    parametres: list = [fin]

    if structures is not None:
        identifiants = [s.pk for s in structures]
        if not identifiants:
            return (0, 0)
        filtre = "AND v.structure_id = ANY(%s)"
        parametres.append(identifiants)

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT count(*), count(*) FILTER (WHERE v.etat_affiche <> 'en_retard')
            FROM v_activite_etat v
            JOIN activite a ON a.id = v.id
            WHERE a.invalide_le IS NULL
              AND a.date_debut <= %s
              {filtre}
            """,
            parametres,
        )
        total, a_l_heure = curseur.fetchone()

    return (a_l_heure or 0, total or 0)


def activites_critiques(structures: QuerySet | list[Structure] | None = None) -> int:
    """
    Les activites critiques au sens du §20 : en retard **et** portant une
    contrainte echue.

    Le retard seul ne suffit pas — sans quoi la moitie du plan serait critique
    et le mot ne trierait plus rien. C'est la regle que porte deja
    `v_activite_etat`.
    """
    filtre = ""
    parametres: list = []

    if structures is not None:
        identifiants = [s.pk for s in structures]
        if not identifiants:
            return 0
        filtre = "AND v.structure_id = ANY(%s)"
        parametres.append(identifiants)

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT count(*)
            FROM v_activite_etat v
            JOIN activite a ON a.id = v.id
            WHERE a.invalide_le IS NULL
              AND v.etat_affiche = 'en_retard'
              AND v.contrainte_echue
              {filtre}
            """,
            parametres,
        )
        (nombre,) = curseur.fetchone()

    return nombre or 0


# =====================================================================
#  Les decisions d'instance
# =====================================================================


def engagements_vivants(structures: QuerySet | list[Structure] | None = None) -> QuerySet:
    requete = Engagement.objects.filter(invalide_le__isnull=True)
    if structures is None:
        return requete
    return requete.filter(structures__structure__in=structures).distinct()


def etats_engagements(engagements: QuerySet) -> dict[int, str]:
    """L'etat affiche de chaque engagement, lu dans `v_engagement_etat`."""
    identifiants = list(engagements.values_list("pk", flat=True))
    if not identifiants:
        return {}
    return {
        vue.pk: vue.etat_affiche for vue in VueEngagementEtat.objects.filter(pk__in=identifiants)
    }


def decisions_en_retard(structures: QuerySet | list[Structure] | None = None) -> int:
    """Les engagements dont l'echeance est passee sans execution."""
    etats = etats_engagements(engagements_vivants(structures))
    return sum(1 for etat in etats.values() if etat == "en_retard")


def decisions_executees(
    annee: int, mois: int, structures: QuerySet | list[Structure] | None = None
) -> int:
    """Les engagements executes dans le mois — la mesure que le CODIR suit."""
    return (
        engagements_vivants(structures)
        .filter(execute_le__year=annee, execute_le__month=mois)
        .count()
    )


def decisions_echues(
    a_la_date: date | None = None, structures: QuerySet | list[Structure] | None = None
) -> int:
    """Les engagements dont l'echeance est passee, executes ou non."""
    fin = a_la_date or date.today()
    return engagements_vivants(structures).filter(echeance__lt=fin).count()


# =====================================================================
#  La disponibilite des responsables
# =====================================================================


def absences_sans_interim(a_la_date: date | None = None) -> int:
    """
    Les absences en cours sans interimaire designe — §3.3.

    C'est le point que la DSR doit voir : les dossiers de la structure
    s'arretent. Une absence a venir ne compte pas, elle laisse le temps de
    designer quelqu'un.
    """
    jour = a_la_date or date.today()
    return Disponibilite.objects.filter(
        invalide_le__isnull=True,
        interimaire__isnull=True,
        du__lte=jour,
        au__gte=jour,
    ).count()


# =====================================================================
#  Les rituels — le calendrier officiel de production
# =====================================================================


def ponctualite_obligations(
    structures: QuerySet | list[Structure] | None = None,
    *,
    annee: int | None = None,
    mois: int | None = None,
) -> tuple[int, int]:
    """
    Combien d'obligations echues ont ete deposees a temps, sur combien d'echues.

    Les obligations **echues** seulement : une production due le 5 du mois
    prochain n'est pas en retard aujourd'hui, et la compter comme non deposee
    reviendrait a punir une structure d'un delai qu'elle respecte.
    """
    requete = Obligation.objects.all()
    if structures is not None:
        requete = requete.filter(structure__in=structures)
    # L'annee seule est acceptee : le programme se lit par exercice, le tableau
    # de bord mensuel par mois.
    if annee is not None:
        requete = requete.filter(echeance__year=annee)
    if mois is not None:
        requete = requete.filter(echeance__month=mois)

    echues = requete.filter(echeance__lte=date.today())
    total = echues.count()
    if not total:
        return (0, 0)

    a_temps = sum(
        1
        for depose_le, echeance in echues.values_list("depose_le", "echeance")
        if depose_le is not None and depose_le <= echeance
    )
    return (a_temps, total)


# =====================================================================
#  Ce qui se compte sur une periode close — les rapports periodiques
# =====================================================================
#
# Les mesures ci-dessus repondent a « ou en sommes-nous » : elles regardent
# l'etat du systeme a une date. Un rapport periodique pose l'autre question —
# « qu'a-t-on fait entre ces deux dates » — et elle ne se repond pas avec les
# memes chiffres. Compter les obligations echues *a ce jour* dans un rapport de
# mars aurait rendu, en decembre, un rapport de mars different de celui imprime
# en avril : un document date qui change apres coup n'est plus un rapport.
#
# D'ou ces fonctions bornees, qui prennent toutes `debut` et `fin` inclus.


def obligations_de_la_periode(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> tuple[int, int]:
    """
    Les obligations echues **dans la periode**, et combien l'ont ete a temps.

    Bornee a l'echeance et non au depot : une production due en mars et deposee
    en mai reste une production de mars, en retard. La rattacher au mois du
    depot aurait fait disparaitre le retard du rapport de mars.
    """
    requete = Obligation.objects.filter(echeance__gte=debut, echeance__lte=fin)
    if structures is not None:
        identifiants = [structure.pk for structure in structures]
        if not identifiants:
            return (0, 0)
        requete = requete.filter(structure_id__in=identifiants)

    total = 0
    a_temps = 0
    for depose_le, echeance in requete.values_list("depose_le", "echeance"):
        total += 1
        if depose_le is not None and depose_le <= echeance:
            a_temps += 1
    return (a_temps, total)


def obligations_non_deposees(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> int:
    """Les obligations echues dans la periode et jamais deposees, a ce jour."""
    requete = Obligation.objects.filter(
        echeance__gte=debut, echeance__lte=fin, depose_le__isnull=True
    )
    if structures is not None:
        identifiants = [structure.pk for structure in structures]
        if not identifiants:
            return 0
        requete = requete.filter(structure_id__in=identifiants)
    return requete.count()


def decisions_executees_periode(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> int:
    """Les engagements executes dans la periode."""
    return (
        engagements_vivants(structures).filter(execute_le__gte=debut, execute_le__lte=fin).count()
    )


def decisions_echues_periode(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> int:
    """Les engagements dont l'echeance tombe dans la periode."""
    return engagements_vivants(structures).filter(echeance__gte=debut, echeance__lte=fin).count()


def activites_ouvertes_periode(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> int:
    """Les activites dont la date de debut tombe dans la periode."""
    return activites_de(structures).filter(date_debut__gte=debut, date_debut__lte=fin).count()


def activites_achevees_periode(
    structures: QuerySet | list[Structure] | None,
    *,
    debut: date,
    fin: date,
) -> int:
    """
    Les activites achevees dans la periode — avancement a 100 et fin echue.

    L'avancement fait foi, pas la colonne `etat` : c'est l'arbitrage n° 2 du
    pilier activites, tenu partout ailleurs dans ce module.
    """
    return (
        activites_de(structures)
        .filter(date_fin__gte=debut, date_fin__lte=fin, avancement_retenu__gte=100)
        .count()
    )


# =====================================================================
#  Ce qui, dans un classement, repose sur une mesure
# =====================================================================


def lignes_mesurees(lignes: list[dict]) -> list[dict]:
    """
    Les lignes du classement dont **au moins un critere est mesuré**.

    La matrice note a `0` un critere sans donnee, parce qu'un classement doit
    ranger toutes les structures — c'est son metier, et l'ADR 010 l'assume.
    Mais un score de zero faute de saisie n'est pas un score de zero : une
    structure qui n'a rien inscrit a son plan d'actions n'est pas une structure
    en echec, et l'alerter au cockpit aurait noye les vraies alertes des le
    premier jour de mise en service.

    Le signal est le feu du critere : la matrice y met « inconnu » quand la
    note est absente, la ou elle met `0` dans `note`. C'est cette distinction,
    deja portee par la matrice, qui est lue ici — et non un second calcul qui
    aurait diverge du premier.
    """
    return [
        ligne
        for ligne in lignes
        if any(critere["feu"] != "inconnu" for critere in ligne.get("criteres", []))
    ]


# =====================================================================
#  Ce que le courrier dirait, s'il existait — et ce que les dossiers disent
# =====================================================================


def traitement_courrier(structures: QuerySet | list[Structure] | None = None) -> float | None:
    """
    Le taux de courriers traites dans le delai — **non mesurable a ce jour**.

    Une fonction qui rend toujours `None` peut sembler inutile ; elle ne l'est
    pas. Elle nomme la mesure manquante a l'endroit ou les autres sont
    calculees, et le jour ou le pilier courrier entrera, il y aura **un** point
    a modifier au lieu de sept. C'est le meme raisonnement que
    `performance/matrice.py`, ou le critere courrier rend deja `None`.
    """
    return None


def instruction_dossiers(
    structures: QuerySet | list[Structure] | None = None,
) -> float | None:
    """
    Le taux de dossiers clos dans le delai d'instruction.

    **Cette mesure existe depuis que le pilier dossiers est en service** — elle
    rendait `None` comme le courrier, et c'etait la moitie de la question A30.
    L'autre moitie reste ouverte : le courrier, lui, n'est toujours pas mesure.

    `None` quand **aucun dossier n'est clos**, et non zero pour cent. Une
    structure qui n'a rien encore cloture n'instruit pas mal, elle n'a pas
    fini : c'est l'ADR 011, et c'est le meme raisonnement que pour l'execution
    des activites.
    """
    dans_le_delai, clos = instruction_dans_le_delai(structures)
    return round(dans_le_delai / clos * 100, 1) if clos else None


# =====================================================================
#  Le courrier
# =====================================================================


def _identifiants(structures: QuerySet | list[Structure] | None) -> list[int] | None:
    """Les cles des structures a retenir, ou `None` pour « toutes »."""
    if structures is None:
        return None
    return sorted(s.pk for s in structures)


def _filtre_structures(structures: QuerySet | list[Structure] | None) -> tuple[str, list]:
    """
    Le fragment de `WHERE` qui borne une mesure de courrier a des structures.

    Rendu sous forme de couple plutot que d'une chaine prete a coller :
    interpoler une liste d'identifiants dans une chaine SQL est la faute qu'on
    ne veut pas voir passer une fois.

    `EXISTS` et non une jointure : un courrier cote a trois structures produirait
    trois lignes, et compterait trois fois.
    """
    cles = _identifiants(structures)
    if cles is None:
        return "", []
    if not cles:
        # Aucune structure au perimetre : la mesure ne porte sur rien.
        return " AND false", []
    return (
        """ AND EXISTS (
                SELECT 1
                  FROM cotation ct
                  JOIN cotation_structure cs ON cs.cotation_id = ct.id
                 WHERE ct.courrier_id = c.id
                   AND ct.invalide_le IS NULL
                   AND cs.structure_id = ANY(%s)
            )""",
        [cles],
    )


def courriers_enregistres(
    debut: date, fin: date, structures: QuerySet | list[Structure] | None = None
) -> int:
    """
    Les courriers entres au registre sur la periode.

    Un volume, donc **zero est une reponse** et non une absence de mesure : une
    structure a qui rien n'a ete cote n'a rien recu, et c'est un fait. C'est la
    difference avec un taux, que l'ADR 011 interdit de rendre a zero faute de
    matiere.
    """
    cloison, arguments = _filtre_structures(structures)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*)
              FROM courrier c
             WHERE c.invalide_le IS NULL
               AND c.date_reception >= %s
               AND c.date_reception < (%s::date + INTERVAL '1 day')
            """
            + cloison,
            [debut, fin, *arguments],
        )
        return curseur.fetchone()[0]


def _courriers_clotures(
    debut: date, fin: date, structures: QuerySet | list[Structure] | None
) -> tuple[int, int, float | None]:
    """
    Le triplet des courriers refermes sur la periode : clos, clos dans le delai,
    delai moyen en jours calendaires.

    La date se lit sur `courrier.cloture_le`, que le socle lie au statut par la
    contrainte `courrier_cloture_coherente` : l'un ne va pas sans l'autre, donc
    la colonne ne peut pas etre nulle sur un courrier clos. `modifie_le` n'aurait
    pas convenu — il bouge a chaque correction de saisie.

    Ce fut d'abord lu au journal, sur `courrier.cloture`, faute d'avoir vu la
    colonne. Le journal disait la meme chose au prix d'une jointure sur une
    table partitionnee et d'un `DISTINCT ON` pour ne pas tripler les courriers
    cotes a trois structures. Voir l'ADR 037.
    """
    cloison, arguments = _filtre_structures(structures)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (
                       WHERE c.date_limite IS NOT NULL
                         AND c.cloture_le::date <= c.date_limite
                   ),
                   avg(c.cloture_le::date - c.date_reception::date)
              FROM courrier c
             WHERE c.invalide_le IS NULL
               AND c.cloture_le >= %s
               AND c.cloture_le < (%s::date + INTERVAL '1 day')
            """
            + cloison,
            [debut, fin, *arguments],
        )
        total, dans_le_delai, moyenne = curseur.fetchone()
    return total, dans_le_delai, (round(float(moyenne), 1) if moyenne is not None else None)


def courriers_clotures(
    debut: date, fin: date, structures: QuerySet | list[Structure] | None = None
) -> int:
    """Le nombre de courriers refermes sur la periode — un volume, donc zero
    est une reponse."""
    total, _, _ = _courriers_clotures(debut, fin, structures)
    return total


def courrier_dans_le_delai(
    debut: date, fin: date, structures: QuerySet | list[Structure] | None = None
) -> tuple[float | None, int, int]:
    """
    Le taux de courriers clotures dans le delai, et les deux nombres qui le font.

    `None` quand **aucun courrier n'a ete cloture** sur la periode, jamais zero
    pour cent : une structure qui n'a rien referme ce mois-ci ne traite pas mal,
    elle n'a rien eu a refermer. Meme regle que l'instruction des dossiers.

    Les courriers **sans echeance** sortent du numerateur comme du denominateur :
    un courrier a qui l'on n'a fixe aucun delai n'est ni a l'heure ni en retard.
    Le denominateur est donc recompte ici, et n'est pas celui de
    `courriers_clotures`.
    """
    cloison, arguments = _filtre_structures(structures)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE c.cloture_le::date <= c.date_limite)
              FROM courrier c
             WHERE c.invalide_le IS NULL
               AND c.cloture_le >= %s
               AND c.cloture_le < (%s::date + INTERVAL '1 day')
               AND c.date_limite IS NOT NULL
            """
            + cloison,
            [debut, fin, *arguments],
        )
        total, dans_le_delai = curseur.fetchone()

    if not total:
        return None, 0, 0
    return round(dans_le_delai / total * 100, 1), dans_le_delai, total


def delai_moyen_courrier(
    debut: date, fin: date, structures: QuerySet | list[Structure] | None = None
) -> float | None:
    """
    Le nombre de jours calendaires entre l'arrivee et la cloture, en moyenne.

    Calendaires et non ouvres : c'est la duree que voit l'expediteur, et c'est
    elle qu'un directeur compare d'un mois a l'autre. Les jours ouvres servent a
    fixer les echeances, pas a les commenter.

    `None` quand aucun courrier n'a ete cloture — voir `courrier_dans_le_delai`.
    """
    _, _, moyenne = _courriers_clotures(debut, fin, structures)
    return moyenne


# =====================================================================
#  Series mensuelles
# =====================================================================


def execution_mensuelle(
    annee: int, mois: int, structures: QuerySet | list[Structure] | None = None
) -> float | None:
    """
    Le taux d'execution tel qu'il etait a la fin du mois donne.

    Calcule sur les activites commencees a cette date-la, et non sur toutes :
    une activite qui debute en octobre ne tirait pas la moyenne de mars vers le
    bas.
    """
    dernier_jour = date(annee, mois, monthrange(annee, mois)[1])
    return execution_activites(structures, a_la_date=dernier_jour)


def variation(courant: float | None, precedent: float | None) -> str | None:
    """
    L'ecart entre deux mesures, deja formate — « +3,2 pts », « −1,0 pt ».

    `None` des qu'une des deux manque : une variation calculee contre une
    mesure absente serait un chiffre invente, et c'est precisement ce que
    l'ADR 011 interdit.
    """
    if courant is None or precedent is None:
        return None

    ecart = round(courant - precedent, 1)
    signe = "+" if ecart > 0 else "−" if ecart < 0 else ""
    unite = "pt" if abs(ecart) < 2 else "pts"
    return f"{signe}{abs(ecart):.1f} {unite}".replace(".", ",")


def mois_glissants(annee: int, mois: int, nombre: int = 12) -> list[tuple[int, int]]:
    """Les `nombre` derniers mois, du plus ancien au plus recent."""
    serie: list[tuple[int, int]] = []
    courant = (annee, mois)
    for _ in range(nombre):
        serie.append(courant)
        courant = mois_precedent(*courant)
    return list(reversed(serie))
