"""
L'en-tete institutionnel, en un seul endroit.

Le modele fait foi est `frontend/public/Entête DSR à utiliser.docx`, remis par
la Division du suivi et de la relance : tout document que l'application produit
— fiche imprimee, bordereau, rapport exporte — le porte. Le front en tient la
version mise en page (`components/EnTeteDocument.tsx`) ; ce module en tient la
version texte, celle des fichiers qui n'ont pas de mise en page.

Bilingue parce que les actes le sont au Cameroun. Un export ampute de sa
colonne anglaise n'est pas un document de l'institution.
"""

#: Le bloc d'en-tete, ligne a ligne : (francais, anglais).
#: L'ordre est celui du tableau du modele Word, lu de haut en bas.
ENTETE: tuple[tuple[str, str], ...] = (
    ("République du Cameroun", "Republic of Cameroon"),
    ("Paix – Travail – Patrie", "Peace – Work – Fatherland"),
    ("Port autonome de Douala (P.A.D)", "Port Authority of Douala (P.A.D)"),
    ("Direction générale", "Head Office"),
    ("Division du suivi et de la relance", "Monitoring and Recovery Division"),
)


def entete_lignes() -> list[tuple[str, str]]:
    """
    L'en-tete pret a etre ecrit dans un fichier a colonnes.

    Renvoie une copie : un appelant qui trierait ou completerait la liste ne
    doit pas modifier l'en-tete de tous les autres exports.
    """
    return list(ENTETE)
