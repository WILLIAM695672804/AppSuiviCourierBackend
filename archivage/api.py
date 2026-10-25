"""
Routes de l'archivage — `/api/archivage/*`.

Deux gardes, et la coupure est celle des competences :

 * `ARCH` pour tout ce qui touche au fonds — referentiel, versements, preuve.
   C'est la permission de l'archiviste : « appliquer le referentiel de
   conservation » ;
 * `AUDIT` **ou** `ARCH` pour la conformite. Le §3.12 confie ce controle a un
   poste d'audit, mais l'archiviste regarde la meme matiere — et lui refuser la
   vue qui dit ce qui ne va pas dans son propre fonds aurait ete absurde.
   L'auditeur, lui, n'a que `AUDIT` : il constate, il ne verse pas.

`restreindre()` n'apparait pas, et c'est un choix motive : un fonds d'archives
reduit au perimetre de son lecteur ne se controle pas. Un dossier verse a
cesse d'etre un dossier en cours d'instruction ; ce qu'il porte de nominatif
n'est plus consulte pour agir mais pour conserver, et c'est le metier de
l'archiviste sur l'institution entiere. C'est la meme derogation que pour les
journaux (`noyau/tracabilite/api.py`), et pour la meme raison. Voir A41.

**Aucune route ne supprime.** Le sort final se propose, il ne s'execute pas :
la destruction d'archives publiques suppose un visa que le logiciel n'a pas a
donner.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from django.urls import register_converter
from ninja import Router

from archivage import lecture, services
from archivage.schemas import (
    ConformiteArchivistique,
    Creation,
    DemandePreuve,
    FileVersements,
    PreuveIntegrite,
    Referentiel,
    SaisieRegle,
    SaisieVersement,
    VersementDetail,
)
from noyau.habilitation.dependances import PERM, exige


class EntierSigne:
    """
    Un identifiant de la file, qui peut etre negatif.

    Le convertisseur `int` de Django ne reconnait que `[0-9]+` : un chemin
    `/versements/-42` ne trouvait **aucune route** et sortait en 404 HTML, sans
    jamais atteindre le pilier. La fiche d'un dossier pas encore verse — donc
    l'ecran qui dit ce qui empeche de le verser — etait inatteignable.

    L'identifiant negatif est la convention de la file (voir `lecture.py`) : il
    designe un dossier clos qui n'est pas encore un versement. Il faut donc un
    convertisseur qui l'accepte.
    """

    regex = r"-?[0-9]+"

    def to_python(self, valeur: str) -> int:
        return int(valeur)

    def to_url(self, valeur: int) -> str:
        return str(valeur)


register_converter(EntierSigne, "entier_signe")

routeur = Router()


# =====================================================================
#  Le referentiel de conservation
# =====================================================================


@routeur.get("/referentiel", response=Referentiel, auth=exige(PERM.ARCH))
def referentiel(request):
    """
    Les durees d'utilite administrative et les sorts finaux — RF-GED-06.

    Une regle sans visa du service des archives apparait, et elle est comptee a
    part : elle existe, elle se lit, et elle ne decide de rien.
    """
    return lecture.referentiel()


@routeur.post("/referentiel", response={201: Creation}, auth=exige(PERM.ARCH))
def creer_regle(request, saisie: SaisieRegle):
    """
    Pose une regle de conservation — **sans visa**.

    C'est le service des archives qui rend la regle applicable, pas celui qui
    la saisit : la creer deja visee lui aurait retire sa competence par voie
    logicielle (RF-ADM-05).
    """
    regle = services.creer_regle(
        request.auth,
        typologie=saisie.typologie,
        description=saisie.description,
        dua=saisie.dua,
        sort_final=saisie.sortFinal,
        fondement_juridique=saisie.fondementJuridique,
        pieces_attendues=saisie.piecesAttendues,
    )
    return 201, {"id": regle.pk}


@routeur.post(
    "/referentiel/{int:regle_id}/validation", response={201: Creation}, auth=exige(PERM.ARCH)
)
def viser_regle(request, regle_id: int):
    """
    Le visa du service des archives — RF-ADM-05.

    Une regle deja visee n'est pas revisee : le second visa effacerait le nom
    du premier signataire, et c'est ce nom qu'on cherche quand la duree est
    contestee.
    """
    regle = services.viser_regle(request.auth, regle_id=regle_id)
    return 201, {"id": regle.pk}


# =====================================================================
#  Les versements
# =====================================================================


@routeur.get("/versements", response=FileVersements, auth=exige(PERM.ARCH))
def versements(request, filtre: str = ""):
    """
    La file des dossiers clos a verser — triee par **echeance du sort final**.

    Ce qui presse n'est pas ce qui est vieux, c'est ce qui arrive a terme : un
    dossier clos hier dont la DUA est d'un an passe devant un dossier clos il y
    a quatre ans dont la DUA est de dix.
    """
    return lecture.versements(filtre)


@routeur.get(
    "/versements/{entier_signe:identifiant}", response=VersementDetail, auth=exige(PERM.ARCH)
)
def fiche(request, identifiant: int):
    """
    La fiche de versement — conformite, chaine d'empreintes, preuve.

    L'identifiant est **negatif** pour un dossier pas encore verse : c'est la
    seule facon d'ouvrir la fiche d'un dossier avant son versement, et donc de
    voir ce qui l'empeche.
    """
    return lecture.fiche(identifiant)


@routeur.post(
    "/versements/{entier_signe:identifiant}/versement",
    response={201: Creation},
    auth=exige(PERM.ARCH),
)
def verser(request, identifiant: int, saisie: SaisieVersement):
    """
    Verse un dossier clos aux archives.

    Une anomalie **bloquante** arrete le versement quoi qu'il arrive : verser
    un dossier dont aucune regle ne dit la duree de conservation reviendrait a
    le perdre proprement. Une anomalie non bloquante se passe outre, mais avec
    une observation.
    """
    versement = services.verser(
        request.auth,
        dossier_id=identifiant,
        observation=saisie.observation,
        anomalies_acceptees=saisie.anomaliesAcceptees,
    )
    return 201, {"id": versement.pk}


@routeur.post(
    "/versements/{entier_signe:identifiant}/preuve",
    response={201: PreuveIntegrite},
    auth=exige(PERM.ARCH),
)
def produire_preuve(request, identifiant: int, demande: DemandePreuve):
    """
    La preuve d'integrite remise a un tiers — RF-GED-09.

    Motif et destinataire obligatoires, et journalises : une preuve sort de
    l'institution, savoir a qui elle a ete remise fait partie de ce qu'elle
    prouve.
    """
    return 201, services.produire_preuve(
        request.auth,
        versement_id=identifiant,
        motif=demande.motif,
        destinataire=demande.destinataire,
    )


# =====================================================================
#  Le controle
# =====================================================================


@routeur.get("/conformite", response=ConformiteArchivistique, auth=exige(PERM.AUDIT, PERM.ARCH))
def conformite(request):
    """
    L'application effective du referentiel de conservation — §3.12.

    **Le taux sort a `null` sur un fonds vide**, et non a 0 ni a 100 : sur zero
    dossier clos les trois sont egalement faux, mais seuls les deux chiffres
    seraient recopies tels quels dans un rapport de controle (ADR 011).
    """
    return lecture.conformite()
