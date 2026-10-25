"""
Le referentiel des correspondants — qui ecrit au Port, et a qui il ecrit.

On ne saisit jamais un expediteur au clavier : c'est ainsi qu'un meme ministere
finit ecrit de six manieres et que les statistiques deviennent fausses. Le
referentiel doit donc etre garni avant le premier courrier, et il l'est ici.

Les quatre types de `correspondant.type` sont representes, parce qu'ils ne se
traitent pas pareil : une administration de tutelle n'attend pas le meme delai
qu'un usager, et le registre les distingue.
"""

from __future__ import annotations

from noyau.parametrage.modeles import Correspondant

#: (type, raison sociale, ville, courriel)
#:
#: Les tutelles d'abord — ce sont elles qui imposent les delais courts — puis
#: les operateurs du port, puis les usagers. Aucun nom n'est reel.
CORRESPONDANTS = [
    ("administration", "Ministère des Transports", "Yaoundé", "courrier@mintransports.cm"),
    ("administration", "Ministère des Finances", "Yaoundé", "sg@minfi.cm"),
    (
        "administration",
        "Ministère de l'Économie et de la Planification",
        "Yaoundé",
        "sg@minepat.cm",
    ),
    ("administration", "Services du Premier Ministre", "Yaoundé", "courrier@spm.gov.cm"),
    ("administration", "Direction Générale des Douanes", "Douala", "dg@douanes.cm"),
    ("administration", "Chambre des Comptes", "Yaoundé", "greffe@chambredescomptes.cm"),
    ("administration", "Préfecture du Wouri", "Douala", "prefecture@wouri.cm"),
    ("administration", "Autorité Portuaire Nationale", "Douala", "contact@apn.cm"),
    ("externe", "SOTRAPAL SA", "Douala", "contact@sotrapal.cm"),
    ("externe", "CAMTRANS Logistique", "Douala", "direction@camtrans.cm"),
    ("externe", "Maersk Cameroun", "Douala", "douala@maersk-cm.com"),
    ("externe", "Bolloré Transport & Logistics", "Douala", "cm.contact@bollore.com"),
    ("externe", "Douala International Terminal", "Douala", "secretariat@dit.cm"),
    ("externe", "Cameroon Shipping Lines", "Douala", "info@camship.cm"),
    ("externe", "Groupement des Transitaires du Littoral", "Douala", "gtl@transit.cm"),
    ("externe", "Société Générale Cameroun", "Douala", "entreprises@socgen.cm"),
    ("externe", "Afriland First Bank", "Douala", "corporate@afrilandfirstbank.cm"),
    ("externe", "Cabinet NGUELE & Associés", "Douala", "contact@nguele-avocats.cm"),
    ("externe", "SIC Assurances", "Douala", "sinistres@sic-assur.cm"),
    ("externe", "Entreprise BATIPORT", "Douala", "devis@batiport.cm"),
    ("usager", "Établissements MBALLA & Fils", "Douala", "mballa.fils@gmail.com"),
    ("usager", "COOP-PECHE Littoral", "Douala", "cooppeche@yahoo.fr"),
    ("usager", "Syndicat des Dockers du Port", "Douala", "sdp.douala@gmail.com"),
    ("usager", "Association des Riverains de Bonabéri", "Douala", "riverains.bonaberi@gmail.com"),
    ("interne", "Représentation du PAD à N'Djamena", "N'Djamena", "rep.ndjamena@pad.cm"),
    ("interne", "Représentation du PAD à Bangui", "Bangui", "rep.bangui@pad.cm"),
]


def semer(ecrire) -> list[Correspondant]:
    """Pose le referentiel et le rend, dans l'ordre de la liste."""
    poses: list[Correspondant] = []
    for type_correspondant, raison_sociale, ville, courriel in CORRESPONDANTS:
        correspondant, cree = Correspondant.objects.get_or_create(
            raison_sociale=raison_sociale,
            invalide_le__isnull=True,
            defaults={
                "type": type_correspondant,
                "ville": ville,
                "courriel": courriel,
            },
        )
        poses.append(correspondant)
        if cree:
            ecrire(f"  correspondant {raison_sociale}")
    return poses
