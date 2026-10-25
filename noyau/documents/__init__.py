"""
Les documents que l'application produit.

**Un document est ecrit, pas capture.** L'application ne rend plus une image de
son interface : elle ouvre le gabarit Word officiel du Port autonome de Douala,
y verse un contenu, et LibreOffice en tire le PDF. Voir l'ADR 023.

Trois couches, etanches :

 * `structure` — le document en objets neutres. Un pilier metier compose une
   `Document` et ne sait rien d'autre : ni python-docx, ni le chemin du
   gabarit, ni `soffice`. C'est ce qui permet de tester une note sans ecrire
   un seul fichier Word.
 * `rendu_docx` — la traduction dans le gabarit. Seul module a importer
   python-docx.
 * `conversion` — le PDF. Seul module a connaitre LibreOffice.

`entete` est l'ancien `noyau/documents.py` : l'en-tete en texte, pour les
fichiers qui n'ont pas de mise en page — l'export CSV des rapports s'en sert.
Il est reexporte ici pour que `from noyau import documents` continue de rendre
`ENTETE` et `entete_lignes` comme avant.
"""

from noyau.documents.entete import ENTETE, entete_lignes

__all__ = ["ENTETE", "entete_lignes"]
