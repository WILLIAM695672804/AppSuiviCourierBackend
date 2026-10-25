"""
Backend d'authentification.

L'authentification doit etre deleguee a l'annuaire (RF-ADM-02). Elle ne l'est
pas encore : le connecteur OIDC est un chantier a part, et il faut bien pouvoir
ouvrir une session d'ici la — en developpement comme a la demonstration.

Ce backend fait donc les deux, dans cet ordre :

 1. si le compte porte un `identifiant_annuaire` et que le SSO est actif, il
    n'authentifie rien : c'est `mozilla-django-oidc` qui s'en chargera ;
 2. sinon, il verifie le mot de passe local.

Le jour de la bascule SSO, la seconde branche disparait et la colonne
`mot_de_passe` est videe pour tous. C'est une dette assumee, inscrite au
registre : docs/architecture/004-session-cookie-sans-jeton.md.
"""

from django.contrib.auth.backends import BaseBackend
from django.http import HttpRequest

from noyau.identite.modeles import Utilisateur


class BackendAnnuaire(BaseBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: object,
    ) -> Utilisateur | None:
        if not username or not password:
            return None

        utilisateur = Utilisateur.objects.filter(
            identifiant_annuaire=username, actif=True, invalide_le__isnull=True
        ).first()

        # `mot_de_passe`, et non `password` : `Utilisateur` n'herite pas
        # d'`AbstractBaseUser` — les colonnes sont celles du schema livre,
        # en francais. Ecrire `password` ici ne leve rien au demarrage et
        # fait echouer TOUTE connexion par AttributeError.
        if utilisateur is None or not utilisateur.mot_de_passe:
            # Pas de mot de passe local : le compte est cense passer par le SSO.
            # On ne dit pas lequel des deux a echoue — une reponse differenciee
            # permettrait d'enumerer les comptes.
            return None

        return utilisateur if utilisateur.check_password(password) else None

    def get_user(self, user_id: int) -> Utilisateur | None:
        return Utilisateur.objects.filter(pk=user_id, actif=True).first()
