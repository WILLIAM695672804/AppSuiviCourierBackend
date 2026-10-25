"""
Deposer, versionner et retirer une piece jointe — RF-GED-04 et RF-GED-09.

Ce module tient les regles ; `stockage.py` tient le disque ; `rattachement.py`
tient le droit d'attacher. La separation n'est pas decorative : le jour du
passage a MinIO, seul `stockage.py` change.

## Trois invariants, tous portes ici

**1. L'empreinte est calculee en lisant le fichier, jamais annoncee.**
RF-GED-09 demande une preuve d'integrite. Une empreinte fournie par le client
ne prouve que la bonne foi du client. La taille aussi est mesuree : un plafond
verifie sur un nombre envoye par celui qu'on veut limiter ne limite personne.

**2. Une version n'ecrase jamais la precedente.** RF-GED-04. Deposer une
nouvelle version insere une ligne qui pointe vers l'ancienne par
`piece_precedente` ; l'ancienne reste lisible, telechargeable et verifiable.
Il n'existe aucun chemin, dans ce module, qui modifie le binaire ou l'empreinte
d'une ligne existante.

**3. Rien ne se supprime.** `invalider` pose une date ; le fichier reste sur le
volume. Une piece effacee ferait echouer la verification d'integrite d'un
dossier deja archive, et le bordereau d'elimination — qui est la vraie facon de
detruire un document — n'aurait plus rien a decrire.

## Ce qui est refuse, et pourquoi

Le plafond de taille et la liste d'extensions vivent dans `parametre`, en
**hypothese** : aucun document de cadrage ne les fixe (A49 et A50). Les valeurs
en place sont celles d'un usage administratif courant, pas une regle du Port
autonome de Douala, et l'ecran de paramétrage permet de les trancher.

L'extension est verifiee, et le debut du fichier aussi. Le `Content-Type`
declare reste seulement une information : il est envoye par le client et vaut
ce que vaut sa parole. Ce controle n'est pas un antivirus ; il bloque les
deguisements evidents avant stockage, puis le fichier est rendu au
telechargement avec `Content-Disposition: attachment`.
"""

from django.db import transaction

from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.parametres.service import valeur as parametre
from noyau.pieces import stockage
from noyau.pieces.modeles import PieceJointe
from noyau.pieces.rattachement import REGISTRE

#: Les valeurs de repli, si la table `parametre` n'est pas peuplee. Elles
#: doublent la migration `0010` a dessein : `valeur()` accepte un defaut, et
#: laisser ce defaut a `None` ferait planter le depot sur une base fraiche
#: plutot que d'appliquer une regle prudente.
PLAFOND_DEFAUT_MO = 25
EXTENSIONS_DEFAUT = "pdf,doc,docx,xls,xlsx,odt,ods,jpg,jpeg,png,tif,tiff"


def deposer(
    acteur: Utilisateur,
    fichier,
    *,
    objet_type: str,
    objet_id: int,
    nom: str,
    categorie: str = "annexe",
    remplace_uid: str | None = None,
) -> PieceJointe:
    """
    Attache un fichier a un objet.

    `remplace_uid` verse une **nouvelle version** de la piece designee : la
    ligne precedente reste, la nouvelle pointe vers elle et porte `version + 1`.
    C'est RF-GED-04, et c'est la seule facon de « corriger » une piece.

    Le meme fichier depose deux fois n'occupe qu'une place sur le volume — le
    chemin derive de l'empreinte — mais produit bien deux lignes : ce sont deux
    actes distincts, sur deux objets peut-etre differents, et les confondre
    ferait disparaitre l'un des deux du journal.
    """
    cible = _cible_accessible(acteur, objet_type, objet_id, ecriture=True)
    nom = (nom or getattr(fichier, "name", "") or "").strip()
    if not nom:
        raise ErreurMetier("Un fichier sans nom ne peut pas etre depose.", code="nom_manquant")

    extension = _extension_valide(nom)
    empreinte, taille = stockage.empreinte_et_taille(fichier)
    _refuser_taille(taille, nom)

    precedente = _version_precedente(acteur, objet_type, objet_id, remplace_uid)

    with transaction.atomic():
        chemin = stockage.ecrire(fichier, empreinte, extension=extension, nom=nom)
        piece = PieceJointe.objects.create(
            objet_type=objet_type,
            objet_id=objet_id,
            # `courrier_id` double le rattachement generique pour ce seul type,
            # et ce n'est pas une connaissance du pilier : c'est une colonne du
            # socle, indexee, sur laquelle reposent les vues d'exploitation
            # ecrites avant le rattachement generique. La laisser nulle aurait
            # fait mentir ces vues sur les pieces deposees depuis le 19 aout.
            courrier_id=objet_id if objet_type == "courrier" else None,
            # Le nom sur le disque est l'empreinte ; celui-ci est le nom rendu
            # a l'agent au telechargement. Les deux sont volontairement
            # differents — voir `stockage`.
            nom_fichier=nom,
            nom_original=nom,
            extension=extension,
            taille_octets=taille,
            type_mime=getattr(fichier, "content_type", None),
            empreinte_sha256=empreinte,
            chemin_stockage=chemin,
            categorie=categorie,
            version=(precedente.version + 1) if precedente else 1,
            piece_precedente=precedente,
            cree_par=acteur.pk,
        )

        inscrire(
            acteur=acteur,
            objet_type=objet_type,
            objet_id=objet_id,
            # Meme raison que la colonne homonyme ci-dessus : le journal du
            # courrier se lit aussi par `courrier_id`.
            courrier_id=objet_id if objet_type == "courrier" else None,
            type_evenement="piece_versee",
            libelle=(
                f"Nouvelle version de « {nom} » (v{piece.version})"
                if precedente
                else f"Pièce « {nom} » versée"
            ),
            donnees={
                # `pieceUid` et non `uid` : c'est la cle que les fiches de vie
                # interrogent pour rattacher une piece au geste qui l'a versee
                # (`activite/lecture.py`). Le depot generique inscrivait `uid`,
                # et la fiche de vie ne trouvait donc jamais les pieces
                # televersees par `POST /pieces` — elles apparaissaient dans
                # l'onglet des pieces jointes, jamais dans la chronologie.
                "pieceUid": str(piece.uid),
                "taille": taille,
                # L'empreinte au journal : c'est elle qui permet, des annees
                # plus tard, de dire que le fichier telecharge est bien celui
                # qui a ete depose ce jour-la (RF-GED-09).
                "empreinte": empreinte,
                "version": piece.version,
                "objet": _libelle_de(cible, objet_type, objet_id),
            },
        )

    return piece


def invalider(acteur: Utilisateur, uid: str, *, motif: str) -> PieceJointe:
    """
    Retire une piece de la vue, sans rien effacer.

    Le binaire reste, l'empreinte reste verifiable, la ligne reste lisible d'un
    audit. Ce qui change, c'est que les ecrans cessent de la proposer.

    `motif` est obligatoire : une piece qui disparait sans raison ecrite est
    exactement ce qu'un controle regarde de pres.
    """
    motif = (motif or "").strip()
    if not motif:
        raise ErreurMetier(
            "Retirer une pièce suppose d'écrire pourquoi.",
            code="motif_exige",
        )

    piece = _piece_accessible(acteur, uid, ecriture=True)
    if piece.invalide_le is not None:
        raise ErreurMetier("Cette pièce a déjà été retirée.", code="piece_deja_retiree")

    from django.utils import timezone

    with transaction.atomic():
        piece.invalide_le = timezone.now()
        piece.invalide_par = acteur.pk
        piece.save(update_fields=["invalide_le", "invalide_par"])

        inscrire(
            acteur=acteur,
            objet_type=piece.objet_type or "piece",
            objet_id=piece.objet_id or piece.pk,
            courrier_id=piece.courrier_id,
            type_evenement="piece_retiree",
            libelle=f"Pièce « {piece.nom_original} » retirée",
            detail=motif,
            donnees={"pieceUid": str(piece.uid), "empreinte": piece.empreinte_sha256},
        )

    return piece


def contenu(acteur: Utilisateur, uid: str):
    """
    Le binaire d'une piece, pour telechargement.

    Rend le couple (piece, flux). L'appelant trace l'acces : c'est une lecture
    de document, et RF-ADM-03 veut savoir qui a telecharge quoi.

    Une piece **invalidee reste telechargeable** par qui voit l'objet. Le
    retrait dit qu'elle ne compte plus, pas qu'elle n'a jamais existe — et
    l'auditeur qui remonte un dossier a besoin de voir ce qui y figurait.

    Trois issues, et les trois messages different parce que les trois gestes
    different : une mention sans binaire se re-depose, un binaire manquant se
    signale a l'exploitation, un fichier present se telecharge.
    """
    piece = _piece_accessible(acteur, uid, ecriture=False)

    # Une ligne sans chemin n'est pas un incident : c'est une **mention** sans
    # fichier, inscrite par le pilier activite jusqu'au 17 aout 2026. Renvoyer
    # ici « enregistre mais introuvable sur le volume » faisait ouvrir un
    # ticket a l'exploitation pour un binaire qui n'a jamais existe. Les deux
    # cas se distinguent par le chemin : vide, il n'y a rien eu ; renseigne, il
    # y a eu quelque chose et il manque.
    if not piece.chemin_stockage:
        raise ErreurMetier(
            f"« {piece.nom_original} » n'est qu'une mention : le fichier lui-même n'a jamais "
            "été versé. Déposez-le de nouveau depuis l'onglet des pièces jointes.",
            code="piece_sans_binaire",
        )

    try:
        flux = stockage.ouvrir(piece.chemin_stockage)
    except (FileNotFoundError, OSError) as erreur:
        # Une ligne sans fichier n'est pas impossible : restauration partielle,
        # volume non monte. Une trace de pile ferait chercher un bogue la ou il
        # y a un incident d'exploitation.
        raise ErreurMetier(
            "Le fichier est enregistré mais introuvable sur le volume de stockage. "
            "Signalez-le à l'exploitation : la pièce n'est pas perdue en base.",
            code="binaire_absent",
        ) from erreur

    return piece, flux


# =====================================================================
#  Refus
# =====================================================================


def _cible_accessible(acteur: Utilisateur, objet_type: str, objet_id: int, *, ecriture: bool):
    """
    L'objet porteur, **vu a travers le perimetre de l'agent**.

    `ecriture` choisit laquelle des deux permissions du registre est exigee :
    celle de saisie pour deposer, versionner ou retirer ; celle de lecture pour
    lister et telecharger. Le parametre est **nomme et obligatoire** a dessein —
    un booleen positionnel a cet endroit serait le genre d'appel qu'on inverse
    sans que rien ne le signale, et l'inversion ouvrirait les pieces en ecriture
    a qui n'a que la lecture.

    Deux refus distincts, et la difference compte :

     * type inconnu du registre → 409, c'est une erreur d'appel ;
     * objet hors perimetre → 404, jamais 403. Repondre « interdit » confirme
       que l'objet existe, et cette confirmation est deja une fuite (D5).
    """
    entree = REGISTRE.get(objet_type)
    if entree is None:
        raise ErreurMetier(
            f"On ne peut pas joindre de pièce à un objet de type « {objet_type} ».",
            code="type_non_rattachable",
        )

    exigee = entree.permission_ecriture if ecriture else entree.permission_lecture
    if not possede(acteur, exigee):
        # 404 et non 403, pour la meme raison : la reponse ne doit pas
        # distinguer « vous n'avez pas le droit » de « cela n'existe pas ».
        raise HorsPerimetre()

    cible = entree.visibles(acteur).filter(pk=objet_id).first()
    if cible is None:
        raise HorsPerimetre()

    return cible


def _piece_accessible(acteur: Utilisateur, uid: str, *, ecriture: bool) -> PieceJointe:
    """
    Une piece, si l'agent peut atteindre l'objet qui la porte.

    **La piece n'a pas de droits propres.** Ils sont ceux de son objet : une
    piece jointe a un dossier confidentiel se lit comme le dossier, et lui
    poser une regle a part aurait cree une seconde verite — celle qu'on finit
    toujours par oublier de mettre a jour. C'est aussi pourquoi `ecriture` est
    transmis tel quel : telecharger la piece demande ce que demande la lecture
    de l'objet, la retirer ce que demande son instruction.
    """
    piece = PieceJointe.objects.filter(uid=uid).first()
    if piece is None or not piece.objet_type or piece.objet_id is None:
        raise HorsPerimetre()

    # Leve si l'objet est hors perimetre, exactement comme au depot.
    _cible_accessible(acteur, piece.objet_type, piece.objet_id, ecriture=ecriture)
    return piece


def _version_precedente(
    acteur: Utilisateur, objet_type: str, objet_id: int, uid: str | None
) -> PieceJointe | None:
    if uid is None:
        return None

    # `ecriture=True` : verser une version est un acte d'ecriture sur la piece
    # remplacee autant que sur la nouvelle.
    precedente = _piece_accessible(acteur, uid, ecriture=True)
    if precedente.objet_type != objet_type or precedente.objet_id != objet_id:
        # Sans ce controle, une « nouvelle version » pourrait migrer une piece
        # d'un objet a un autre en silence, et la chaine des versions
        # traverserait deux dossiers.
        raise ErreurMetier(
            "La version précédente est rattachée à un autre objet.",
            code="version_d_un_autre_objet",
        )
    if precedente.invalide_le is not None:
        raise ErreurMetier(
            "Cette pièce a été retirée : versez-en une nouvelle plutôt qu'une version.",
            code="version_d_une_piece_retiree",
        )
    return precedente


def _extension_valide(nom: str) -> str:
    """
    L'extension, en minuscules et sans le point.

    Un nom sans extension est refuse. Ce n'est pas du formalisme : c'est ce qui
    permet a l'agent qui telecharge d'ouvrir le fichier, et a la GED de savoir
    ce qu'elle range.
    """
    _, _, extension = nom.rpartition(".")
    extension = extension.strip().lower()

    if not extension or extension == nom.lower():
        raise ErreurMetier(
            f"« {nom} » n'a pas d'extension : le type du fichier ne peut pas être établi.",
            code="extension_manquante",
        )

    autorisees = {
        e.strip().lower()
        for e in str(parametre("pieces.extensions_autorisees", EXTENSIONS_DEFAUT)).split(",")
        if e.strip()
    }
    if extension not in autorisees:
        raise ErreurMetier(
            f"Les fichiers « .{extension} » ne sont pas acceptés. "
            f"Formats admis : {', '.join(sorted(autorisees))}.",
            code="extension_refusee",
        )

    return extension


def _refuser_taille(taille: int, nom: str) -> None:
    plafond_mo = int(parametre("pieces.taille_maximale_mo", PLAFOND_DEFAUT_MO))
    if taille > plafond_mo * 1024 * 1024:
        raise ErreurMetier(
            f"« {nom} » pèse {taille / (1024 * 1024):.1f} Mo, au-delà du plafond "
            f"de {plafond_mo} Mo.",
            code="fichier_trop_lourd",
        )
    if taille == 0:
        raise ErreurMetier(f"« {nom} » est vide.", code="fichier_vide")


def _libelle_de(cible, objet_type: str, objet_id: int) -> str:
    """Comment l'objet porteur se nomme au journal."""
    entree = REGISTRE[objet_type]
    return f"{entree.libelle} #{objet_id}"
