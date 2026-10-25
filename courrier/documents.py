"""
Les documents que le pilier courrier edite — ADR 023.

Deux documents, et une seule chaine : `noyau.documents.structure` compose,
`rendu_docx` verse dans le gabarit officiel de la DSR, `conversion` en tire le
PDF. Ce module ne connait ni Word, ni LibreOffice, ni le chemin du gabarit —
c'est ce qui permet de verifier ce qu'il compose sans ecrire un fichier.

 * **Le registre** — la liste telle que l'ecran la filtre, editee pour etre
   classee et signee. C'est la piece qu'un controle demande.
 * **La fiche de cotation** — B-03, le bordereau qui accompagne le pli quand il
   part en main propre, avec la decharge du recepteur. Elle seule fait foi quand
   le systeme est indisponible, et c'est pour cela qu'elle porte une decharge
   manuscrite plutot qu'un accuse ecran.

Jusqu'au 19 aout 2026, les deux etaient des `window.print()` sur l'ecran React :
en-tete institutionnel en page 1 seulement, mise en page a la merci du
navigateur de chaque agent, aucune reference de document. L'ADR 023 a tranche
pour le pilotage ; ces deux-la reprennent la meme chaine, sans la reecrire.

**Ce que ces documents ne disent pas.** Ni transmission, ni validation, ni
signature : `circuit_etape` est vide (A24). La fiche de cotation porte donc la
cotation et la decharge, et s'arrete la — un bordereau qui annoncerait un
circuit invente ferait circuler le papier sur une route qui n'existe pas.
"""

import unicodedata
from datetime import date, datetime

from django.utils import timezone

from courrier import lecture
from noyau.documents.structure import (
    Cellule,
    Chiffre,
    Chiffres,
    Colonne,
    Document,
    Paragraphe,
    Section,
    Tableau,
    retenir,
)
from noyau.erreurs import ErreurMetier
from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur

#: Les etapes en clair. Le front porte la meme table (`courrier/statut.ts`) ;
#: celle-ci lui repond mot pour mot, faute de quoi le document imprime ne dirait
#: pas ce que l'ecran d'ou il sort affichait.
LIBELLE_ETAPE = {
    "ENREGISTRE": "Enregistré",
    "COTE": "Coté",
    "TRANSMIS": "Transmis",
    "AFFECTE": "Affecté",
    "EN_TRAITEMENT": "En traitement",
    "EN_VALIDATION": "En validation",
    "SIGNE": "Signé",
    "PARTI": "Parti",
    "CLOTURE": "Clôturé",
}

#: Le titre de chaque vue du registre. Les six onglets de l'ecran A-02 : un
#: document tire de l'onglet « Hors délai » doit le dire dans son titre, sinon
#: il se lit comme le registre entier.
TITRE_VUE = {
    "tous": "",
    "nonCotes": "courriers non cotés",
    "affectes": "courriers qui me sont affectés",
    "horsDelai": "courriers hors délai",
    "urgents": "courriers urgents",
    "clotures": "courriers clôturés",
}

#: Le sens, en clair, pour le titre.
TITRE_SENS = {
    "ARRIVEE": "Registre des courriers arrivés",
    "DEPART": "Registre des courriers départ",
    "INTERNE": "Registre des courriers internes",
}


def registre_document(
    utilisateur: Utilisateur,
    *,
    sens: str = "ARRIVEE",
    vue: str = "tous",
    recherche: str = "",
) -> Document:
    """
    Le registre, edite.

    **Exactement ce que l'ecran montre** : meme requete, meme filtre, meme ordre
    (`lecture.registre_pour_export`). Un registre imprime qui ne correspond pas a
    l'ecran d'ou on l'a tire ne se defend devant personne.

    Le document **dit ce qu'il ne contient pas** : le filtre applique, la date
    d'edition, l'agent qui edite, et le fait qu'il a ete arrete a 500 lignes le
    cas echeant. Un tableau tronque en silence est un faux.
    """
    _exiger_impression(utilisateur)

    donnees = lecture.registre_pour_export(utilisateur, sens=sens, vue=vue, recherche=recherche)
    lignes = donnees["lignes"]
    aujourd_hui = timezone.localdate()

    sections = retenir(
        Section(
            titre="Ce que couvre cette édition",
            blocs=(
                Chiffres(
                    items=(
                        Chiffre(libelle="Courriers retenus", valeur=str(donnees["total"])),
                        Chiffre(libelle="Lignes éditées", valeur=str(len(lignes))),
                        Chiffre(libelle="Édité le", valeur=_jour(aujourd_hui)),
                    )
                ),
                Paragraphe(texte=_phrase_de_perimetre(utilisateur, vue, recherche, donnees)),
            ),
        ),
        _section_lignes(lignes),
    )

    return Document(
        titre=TITRE_SENS.get(sens, "Registre des courriers"),
        surtitre="Port autonome de Douala",
        sous_titre=(
            f"Édité le {_jour(aujourd_hui)} par {utilisateur.nom_complet}"
            + (f" · {TITRE_VUE[vue]}" if TITRE_VUE.get(vue) else "")
        ),
        reference=f"REGISTRE-{_sans_accent(sens)}-{aujourd_hui.isoformat()}",
        sections=sections,
    )


def _phrase_de_perimetre(utilisateur: Utilisateur, vue: str, recherche: str, donnees: dict) -> str:
    """
    Ce que le lecteur doit savoir avant de compter les lignes.

    Trois choses, et la premiere n'est pas negociable : **ce registre est celui
    de son lecteur**. La visibilite du pilier (ADR 022) fait que deux agents
    editent deux documents differents du meme jour, et un controleur qui
    l'ignore conclura a un registre incomplet.
    """
    morceaux = [
        "Cette édition ne porte que les courriers visibles de "
        f"{utilisateur.nom_complet} au jour de l'édition : rattachement, cotation, "
        "désignation, ou consolidation explicite."
    ]
    if TITRE_VUE.get(vue):
        morceaux.append(f"Filtre appliqué : {TITRE_VUE[vue]}.")
    if recherche.strip():
        morceaux.append(f"Recherche : « {recherche.strip()} ».")
    if donnees["tronque"]:
        morceaux.append(
            f"L'édition a été arrêtée à {len(donnees['lignes'])} lignes sur "
            f"{donnees['total']} retenues. Restreindre la période ou le filtre "
            "avant de rééditer."
        )
    return " ".join(morceaux)


def _section_lignes(lignes: list[dict]) -> Section:
    """
    Le tableau du registre, ou la phrase qui dit qu'il n'y a rien.

    Une section vide serait ecartee par `retenir()`, et le document sortirait
    sans son tableau : « aucun courrier » se lirait alors comme un document
    rate. La phrase est donc composee ici (ADR 011).
    """
    if not lignes:
        return Section(
            titre="Courriers",
            blocs=(
                Paragraphe(
                    texte=(
                        "Aucun courrier ne répond à ce filtre. Ce n'est pas une "
                        "erreur d'édition : le registre existe et il est vide de "
                        "ce point de vue."
                    )
                ),
            ),
        )

    return Section(
        titre="Courriers",
        blocs=(
            Tableau(
                colonnes=(
                    Colonne(entete="N°", poids=2),
                    Colonne(entete="Reçu le"),
                    Colonne(entete="Expéditeur", poids=3),
                    Colonne(entete="Objet", poids=5),
                    Colonne(entete="Coté à", poids=2),
                    Colonne(entete="Échéance"),
                    Colonne(entete="État", poids=2),
                ),
                lignes=tuple(
                    (
                        Cellule(texte=ligne["numero"]),
                        Cellule(texte=_jour(ligne["dateReception"])),
                        Cellule(texte=ligne["correspondant"]),
                        Cellule(texte=_objet_abrege(ligne["objet"])),
                        # Le chef de file d'abord : c'est lui qui repond. Les
                        # co-traitantes sont citees ensuite, sans quoi le
                        # document dirait « une structure » la ou la decision en
                        # visait quatre.
                        Cellule(texte=" · ".join(ligne["structuresCotees"]) or "Non cotée"),
                        Cellule(texte=_jour(ligne["echeance"])),
                        Cellule(texte=LIBELLE_ETAPE.get(ligne["etape"], ligne["etape"])),
                    )
                    for ligne in lignes
                ),
                legende=(
                    "Les courriers confidentiels ne figurent qu'aux éditions des agents "
                    "qui en portent l'habilitation."
                ),
            ),
        ),
    )


def fiche_de_cotation_document(utilisateur: Utilisateur, identifiant: int) -> Document:
    """
    La fiche de cotation — B-03.

    Le bordereau qui accompagne le pli. Il porte ce qu'il faut pour que le
    recepteur sache **ce qu'il recoit, de qui, pour quand**, et une decharge a
    signer a la main : c'est la piece qui fait foi quand le systeme est
    indisponible, et un accuse a l'ecran ne remplace pas une signature sur un
    registre de coursier.

    La cotation retenue est la **plus recente** : c'est la decision en vigueur.
    Les precedentes restent a la fiche de vie, qui raconte l'histoire ; le
    bordereau, lui, accompagne un pli qui part maintenant.
    """
    _exiger_impression(utilisateur)

    fiche = lecture.fiche(utilisateur, identifiant)
    cotations = fiche["cotations"]
    cotation = cotations[-1] if cotations else None

    sections = retenir(
        Section(titre="Le pli", blocs=(_tableau_du_pli(fiche),)),
        Section(titre="Cotation", blocs=_blocs_de_cotation(fiche, cotation)),
        Section(titre="Décharge du récepteur", blocs=_blocs_de_decharge()),
    )

    return Document(
        titre="Fiche de cotation",
        surtitre="Port autonome de Douala",
        sous_titre=f"Courrier n° {fiche['numero']} · {fiche['sessionLibelle']}",
        reference=f"COTATION-{_sans_accent(fiche['numero']).replace('/', '-')}",
        sections=sections,
    )


def _tableau_du_pli(fiche: dict) -> Tableau:
    """L'identification du courrier, en deux colonnes libelle / valeur."""
    pieces = f"{fiche['nombrePages']} page(s)"
    if fiche["nombreAnnexes"]:
        pieces += f" · {fiche['nombreAnnexes']} annexe(s) numérisée(s)"

    entrees = [
        ("Numéro d'enregistrement", fiche["numero"]),
        ("Objet", fiche["objet"]),
        ("Expéditeur", fiche["correspondant"]),
        ("Référence de l'expéditeur", fiche["referenceExpediteur"] or "—"),
        ("Nature", fiche["nature"]),
        ("Reçu le", _jour(fiche["dateReception"])),
        ("Enregistré par", fiche["enregistrePar"]),
        ("Pièces au pli", pieces),
    ]
    if fiche["confidentiel"]:
        # Ecrit en toutes lettres sur le bordereau : le pli passe de main en
        # main, et c'est la seule mention que le coursier lira.
        entrees.append(("Mention", "CONFIDENTIEL — remise en main propre"))

    return Tableau(
        colonnes=(Colonne(entete="Élément", poids=2), Colonne(entete="Valeur", poids=5)),
        lignes=tuple(
            (Cellule(texte=libelle), Cellule(texte=str(valeur))) for libelle, valeur in entrees
        ),
    )


def _blocs_de_cotation(fiche: dict, cotation: dict | None) -> tuple:
    """
    La decision, ou son absence — dite, jamais tue.

    Un bordereau sans cotation n'est pas un bordereau rate : c'est un pli qui
    part avant d'avoir ete cote, et le recepteur doit le savoir.
    """
    if cotation is None:
        return (
            Paragraphe(
                texte=(
                    "Ce courrier n'a pas encore été coté. Le pli circule sous la seule "
                    "responsabilité du service courrier, et aucune structure n'en a "
                    "reçu la charge."
                )
            ),
        )

    structures = tuple(
        (
            Cellule(texte=str(structure["rang"])),
            Cellule(texte=structure["libelle"]),
            Cellule(texte="Chef de file" if structure["chefDeFile"] else "Co-traitante"),
        )
        for structure in cotation["structures"]
    )

    entrees = [
        ("Décidée par", cotation["decidePar"]["nomComplet"]),
        ("Le", _jour(cotation["decideLe"])),
        ("Saisie par", cotation["saisiPar"]["nomComplet"]),
        ("Mention", cotation["mention"] or "—"),
        ("Échéance", _jour(cotation["delaiFixe"] or fiche["echeance"])),
        ("Instruction", cotation["annotation"] or "—"),
    ]

    return (
        Tableau(
            colonnes=(
                Colonne(entete="Rang"),
                Colonne(entete="Structure destinataire", poids=5),
                Colonne(entete="Rôle", poids=2),
            ),
            lignes=structures,
            legende=(
                "Le rang 1 est chef de file : il coordonne et centralise la réponse."
                if len(structures) > 1
                else ""
            ),
        ),
        Tableau(
            colonnes=(Colonne(entete="Élément", poids=2), Colonne(entete="Valeur", poids=5)),
            lignes=tuple(
                (Cellule(texte=libelle), Cellule(texte=str(valeur))) for libelle, valeur in entrees
            ),
        ),
    )


def _blocs_de_decharge() -> tuple:
    """
    Les deux cadres a signer.

    Un tableau a deux lignes vides plutot qu'un texte : c'est ce qui laisse la
    place d'ecrire. La deuxieme ligne est haute parce qu'on y porte un nom, une
    qualite, une date, une heure et une signature.
    """
    return (
        Paragraphe(
            texte=(
                "Le récepteur porte ci-dessous son nom, sa qualité, la date et l'heure "
                "de la remise, puis signe. Cette décharge fait foi de la transmission "
                "du pli papier."
            )
        ),
        Tableau(
            colonnes=(
                Colonne(entete="Remis par (service courrier)", poids=1),
                Colonne(entete="Reçu par (nom, qualité, date et heure)", poids=1),
            ),
            lignes=(
                (Cellule(texte=""), Cellule(texte="")),
                (Cellule(texte=""), Cellule(texte="")),
                (Cellule(texte="Signature :"), Cellule(texte="Signature :")),
            ),
        ),
    )


def _exiger_impression(utilisateur: Utilisateur) -> None:
    """
    Editer un document est une **sortie**, et elle a sa permission.

    `IMP` — « Imprimer » — s'ajoute a la garde de lecture posee sur la route.
    Elle ne s'y substitue pas : lire le registre a l'ecran et en sortir un
    fichier signable sont deux gestes, et le second quitte l'application.

    Le refus sort en `ErreurMetier` 403 et non en 404 : l'objet n'est pas en
    cause — l'agent le voit — c'est le geste qui lui est fermé, et le dire ne
    revele rien qu'il ne sache deja (D5 ne joue pas ici).
    """
    if not possede(utilisateur, PERM.IMP):
        raise ErreurMetier(
            "L'édition d'un document demande la permission « Imprimer ».",
            code="impression_refusee",
            statut=403,
        )


def _objet_abrege(objet: str, limite: int = 90) -> str:
    """
    L'objet, coupe au mot.

    Un objet de trois lignes dans une cellule fait une ligne de tableau haute
    comme un paragraphe, et le registre cesse d'etre lisible en diagonale — ce
    pour quoi on l'imprime.
    """
    if len(objet) <= limite:
        return objet
    coupe = objet[:limite].rsplit(" ", 1)[0]
    return f"{coupe}…"


def _jour(valeur) -> str:
    """
    Une date a la francaise, quelle que soit sa forme d'origine.

    `lecture` rend tantot une `date`, tantot un `datetime`, tantot `None` :
    laisser chaque appelant s'en debrouiller a produit, ailleurs dans ce projet,
    un « Invalid time value » en pleine page. Voir `docs/pieges.md`.
    """
    if valeur is None or valeur == "":
        return "—"
    if isinstance(valeur, datetime):
        return timezone.localtime(valeur).strftime("%d/%m/%Y")
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    return str(valeur)


def _sans_accent(valeur: str) -> str:
    """La reference se tape a la main et se cite a voix haute : ni accent, ni casse."""
    return unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode().upper().strip()
