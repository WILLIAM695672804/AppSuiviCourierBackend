"""
Routes des pieces jointes — `/api/pieces/*`.

**Une seule route de depot pour tous les piliers.** Six routes de televersement
— une par pilier — auraient fait six fois le meme travail, dont cinq auraient
fini par diverger sur le plafond de taille, le calcul de l'empreinte ou le
versionnement. Ce qui varie d'un pilier a l'autre — la permission exigee et la
visibilite de l'objet porteur — est declare une fois dans
`noyau/pieces/rattachement.py`.

## La garde n'est pas dans le decorateur

Les autres routes du depot ecrivent `auth=exige(PERM.…)`. Ici, la permission
**depend de l'objet auquel on rattache** — activite, dossier, demande d'usager
— **et du geste** : deposer, versionner ou retirer demande la permission de
saisie du pilier (`ACT_SAI`, `DOS_INS`, `EXT`), lister ou telecharger celle de
lecture (`ACT_LEC`, `DOS_LEC`, `EXT`). `exige()` ne sait poser aucune de ces
deux questions : la premiere depend du corps de la requete, la seconde de la
route.

La garde est donc `session_seule` — session valide obligatoire — **plus**
la verification portee par `services._cible_accessible`, qui refuse la
permission manquante **et** l'objet hors perimetre, tous deux en 404 (D5).
Ce n'est pas un contournement de la regle du depot : c'est le seul endroit ou
elle ne peut pas s'ecrire dans le decorateur, et le service la porte en entier.

Le couple de permissions est declare par type d'objet dans `rattachement.py`.
Exiger celle d'ecriture pour lire — ce que ce module a fait jusqu'a la
correction — masquait les pieces d'une activite a tous ceux qui la voyaient
sans droit d'y ecrire ; voir `docs/pieges.md`.

## Le telechargement trace

`GET /pieces/{uid}/contenu` appelle `tracer_acces`. C'est exactement le cas que
RF-ADM-03 vise : sortir un document de l'application est le geste apres lequel
l'institution n'en a plus le controle.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from django.http import FileResponse
from ninja import File, Form, Router, UploadedFile

from noyau.habilitation.dependances import session_seule
from noyau.journal.service import tracer_acces
from noyau.pieces import lecture, services
from noyau.pieces.rattachement import REGISTRE
from noyau.pieces.schemas import PieceSortie, SaisieRetraitPiece

routeur = Router()


@routeur.get("", response=list[PieceSortie], auth=session_seule)
def pieces(request, objetType: str, objetId: int):
    """
    Les pieces d'un objet, versions courantes seulement.

    Les versions anterieures sont dans le champ `versions` de la ligne qui les
    remplace. Les lister a plat ferait chercher longtemps laquelle est la bonne.
    """
    return lecture.pieces_de(request.auth, objetType, objetId)


@routeur.post("", response=PieceSortie, auth=session_seule)
def deposer(
    request,
    # `B008` est desactive ici a dessein : `File(...)` et `Form(...)` en valeur
    # par defaut sont la facon dont django-ninja declare un envoi multipart. Les
    # deplacer dans le corps de la fonction ferait perdre la declaration a
    # OpenAPI, et la route cesserait d'accepter un fichier.
    fichier: UploadedFile = File(...),  # noqa: B008
    objetType: str = Form(...),
    objetId: int = Form(...),
    nom: str = Form(""),
    categorie: str = Form("annexe"),
    remplaceUid: str = Form(""),
):
    """
    Depose un fichier — RF-GED-04 et RF-GED-09.

    `multipart/form-data` et non JSON : encoder le binaire en base64 aurait
    ajoute un tiers de poids pour rien.

    `nom` est facultatif — le nom du fichier envoye sert de repli. Le fournir
    permet de deposer sous un nom lisible un fichier issu d'un scanner, qui
    s'appelle souvent `SCAN_0042.pdf`.

    `remplaceUid` verse une **nouvelle version** : l'ancienne reste lisible,
    telechargeable et verifiable.
    """
    piece = services.deposer(
        request.auth,
        fichier,
        objet_type=objetType,
        objet_id=objetId,
        nom=nom or (fichier.name or ""),
        categorie=categorie,
        remplace_uid=remplaceUid or None,
    )
    return _relire(request.auth, piece)


@routeur.get("/{uid}/contenu", auth=session_seule)
def telecharger(request, uid: str):
    """
    Le binaire, en piece attachee.

    `as_attachment=True` sans exception : servir un fichier depose par un tiers
    en affichage direct ferait executer, dans le domaine de l'application, du
    contenu que l'application n'a pas produit.
    """
    piece, flux = services.contenu(request.auth, uid)

    tracer_acces(
        acteur=request.auth,
        objet_type="piece_jointe",
        objet_id=piece.pk,
        action="telechargement",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    return FileResponse(flux, as_attachment=True, filename=piece.nom_original)


@routeur.post("/{uid}/retrait", response=PieceSortie, auth=session_seule)
def retirer(request, uid: str, saisie: SaisieRetraitPiece):
    """
    Retire une piece de la vue — sans rien effacer.

    Il n'y a pas de `DELETE` sur cette ressource, et il n'y en aura pas : un
    binaire efface ferait echouer la verification d'integrite d'un dossier deja
    archive.
    """
    piece = services.invalider(request.auth, uid, motif=saisie.motif)
    return _relire(request.auth, piece)


@routeur.get("/types", response=list[dict], auth=session_seule)
def types_rattachables(request):
    """
    Les types d'objet auxquels une piece peut se rattacher.

    Sert au front a savoir ce qu'il peut proposer, plutot qu'a le deviner. Un
    type absent d'ici est refuse au depot.
    """
    return [{"cle": cle, "libelle": entree.libelle} for cle, entree in REGISTRE.items()]


def _relire(acteur, piece) -> dict:
    """
    La piece telle que la liste la sert.

    Relire plutot que construire la reponse a la main : c'est `lecture` qui
    decide de la forme, et deux constructions divergentes finiraient par
    afficher un champ que la liste ne montre pas.
    """
    lignes = lecture.pieces_de(acteur, piece.objet_type, piece.objet_id)
    for ligne in lignes:
        if ligne["uid"] == str(piece.uid):
            return ligne

    # La piece vient d'etre remplacee par une version plus recente dans le meme
    # appel : elle n'est plus en tete de chaine. On rend la ligne courante, qui
    # est celle que l'ecran doit afficher.
    return lignes[0] if lignes else _minimal(piece)


def _minimal(piece) -> dict:
    """Repli : la piece seule, sans sa chaine. Ne devrait pas servir."""
    return {
        "uid": str(piece.uid),
        "nom": piece.nom_original,
        "extension": piece.extension or "",
        "taille": piece.taille_octets,
        "tailleLisible": lecture._lisible(piece.taille_octets),
        "categorie": piece.categorie,
        "version": piece.version,
        "empreinte": piece.empreinte_sha256,
        "deposeeLe": piece.cree_le.strftime("%d/%m/%Y") if piece.cree_le else "",
        "retiree": piece.invalide_le is not None,
        "versions": [],
    }
