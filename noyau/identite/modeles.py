"""
Identite — le compte, et sa session d'enregistrement.

Le compte vit dans la table `utilisateur` du schema existant. Django ne cree
pas la sienne : celle-ci porte deja les colonnes metier (matricule, poste,
structure, identifiant d'annuaire) et sert de cible a une dizaine de cles
etrangeres.

Un ecart au schema d'origine, assume et documente : la colonne
`mot_de_passe`, nullable, ajoutee par la migration 0002. Le schema disait
« aucun mot de passe n'est stocke » parce que l'authentification doit etre
deleguee a l'annuaire (RF-ADM-02). Elle ne l'est pas encore, et il faut bien
pouvoir ouvrir une session d'ici la. La colonne reste vide pour tout compte
rattache a l'annuaire, et devra etre videe pour tous le jour de la bascule.
Voir docs/architecture/004-session-cookie-sans-jeton.md.

**Pourquoi ce modele n'herite pas de `AbstractBaseUser`.** La classe de Django
impose ses propres colonnes, `password` et `last_login`, que la table nomme
autrement. Il aurait fallu soit renommer les colonnes du schema livre, soit en
ajouter deux qui font double emploi. Django n'exige pas cet heritage : il
attend une interface, que ce modele fournit. Le prix est une trentaine de
lignes, ecrites une fois.
"""

import hmac
import uuid
from collections.abc import Iterator
from hashlib import sha256

from django.conf import settings
from django.contrib.auth.hashers import check_password, is_password_usable, make_password
from django.db import models
from django.utils.encoding import force_bytes

from noyau.organisation.modeles import Poste, Structure


class GestionnaireUtilisateur(models.Manager):
    """
    Django exige `get_by_natural_key`. La clef naturelle est l'identifiant
    d'annuaire, pas le courriel : c'est lui qui fera le rapprochement SSO,
    et un agent peut changer d'adresse sans changer de compte.
    """

    def get_by_natural_key(self, identifiant: str):
        return self.get(identifiant_annuaire=identifiant, actif=True)

    def actifs(self) -> models.QuerySet:
        return self.get_queryset().filter(actif=True, invalide_le__isnull=True)


class Utilisateur(models.Model):
    # `default` cote Python et non cote base : Django envoie toujours la
    # colonne dans son INSERT, ce qui court-circuite le DEFAULT
    # gen_random_uuid() du schema et insere NULL.
    uid = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)
    identifiant_annuaire = models.TextField(unique=True, null=True, blank=True)
    matricule = models.TextField(unique=True, null=True, blank=True)
    nom = models.TextField()
    prenom = models.TextField()
    courriel = models.EmailField(unique=True, null=True, blank=True)
    telephone = models.TextField(null=True, blank=True)

    poste = models.ForeignKey(
        Poste, null=True, blank=True, on_delete=models.PROTECT, db_column="poste_id"
    )
    structure = models.ForeignKey(
        Structure, null=True, blank=True, on_delete=models.PROTECT, db_column="structure_id"
    )

    actif = models.BooleanField(default=True)
    derniere_connexion = models.DateTimeField(null=True, blank=True)
    mot_de_passe = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    USERNAME_FIELD = "identifiant_annuaire"
    REQUIRED_FIELDS = ["nom", "prenom"]

    objects = GestionnaireUtilisateur()

    class Meta:
        db_table = "utilisateur"
        ordering = ["nom", "prenom"]

    def __str__(self) -> str:
        return self.nom_complet

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}".strip()

    @property
    def initiales(self) -> str:
        """« Sekou Bamba » donne « SB ». Affichees dans chaque avatar du front."""
        premiere = self.prenom[:1].upper() if self.prenom else ""
        seconde = self.nom[:1].upper() if self.nom else ""
        return f"{premiere}{seconde}" or "?"

    # -----------------------------------------------------------------
    #  Interface attendue par Django (session, middleware, `login()`).
    #
    #  Ces membres ne sont pas du remplissage : `AuthenticationMiddleware`
    #  et `login()` les appellent nommement. Les retirer casse l'ouverture
    #  de session sans message clair.
    # -----------------------------------------------------------------
    is_anonymous = False
    is_authenticated = True

    @property
    def is_active(self) -> bool:
        return self.actif and self.invalide_le is None

    def get_username(self) -> str:
        return self.identifiant_annuaire or ""

    def set_password(self, mot_de_passe: str | None) -> None:
        self.mot_de_passe = make_password(mot_de_passe)

    def check_password(self, mot_de_passe: str) -> bool:
        if not self.mot_de_passe or not is_password_usable(self.mot_de_passe):
            return False

        def enregistrer(hache: str | None) -> None:
            """Rehachage transparent quand l'algorithme evolue."""
            self.mot_de_passe = hache
            self.save(update_fields=["mot_de_passe"])

        return check_password(mot_de_passe, self.mot_de_passe, enregistrer)

    def _empreinte_session(self, secret: str | bytes) -> str:
        # `SECRET_KEY_FALLBACKS` accepte des chaines comme des octets — Django
        # lui-meme passe par `force_bytes`. Appeler `.encode()` a l'aveugle
        # ferait echouer la rotation de clef sur une entree en octets.
        graine = self.mot_de_passe or f"annuaire:{self.identifiant_annuaire}"
        return hmac.new(force_bytes(secret), graine.encode(), digestmod=sha256).hexdigest()

    def get_session_auth_hash(self) -> str:
        """
        Empreinte liant la session au mot de passe.

        Elle permet a Django d'invalider les sessions ouvertes lorsqu'un mot
        de passe change. Sur un compte SSO sans mot de passe local, elle est
        derivee de l'identifiant : la valeur importe peu, sa stabilite oui.
        """
        return self._empreinte_session(settings.SECRET_KEY)

    def get_session_auth_fallback_hash(self) -> Iterator[str]:
        """
        Empreintes calculees avec les anciennes clefs (`SECRET_KEY_FALLBACKS`).

        `django.contrib.auth.get_user` appelle cette methode des que
        l'empreinte portee par la session ne correspond plus a celle du
        compte — apres une rotation de `SECRET_KEY`, ou un changement de mot
        de passe. Sans elle, le middleware leve `AttributeError` et toute
        requete authentifiee repond 500. `AbstractBaseUser` la fournit ; ce
        modele n'en herite pas (voir l'en-tete du module), il doit donc la
        porter lui-meme.
        """
        for ancienne_clef in settings.SECRET_KEY_FALLBACKS:
            yield self._empreinte_session(ancienne_clef)


class SessionCourrier(models.Model):
    """
    Les quatre sessions d'enregistrement du cahier des charges (§4.2).

    `lit_toutes_sessions` n'est vrai que pour le confidentiel. La propriete
    est portee en donnee et non en code, pour pouvoir etre retiree sans
    developpement — le §4.2 la donne « selon les habilitations definies ».
    """

    CODES = [
        ("arrive", "Courrier arrive"),
        ("depart", "Courrier depart"),
        ("interne", "Courrier interne"),
        ("confidentiel", "Courrier confidentiel"),
    ]

    code = models.TextField(unique=True, choices=CODES)
    libelle = models.TextField()
    sens = models.TextField()
    lit_toutes_sessions = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "session"
        verbose_name = "session d'enregistrement"
        verbose_name_plural = "sessions d'enregistrement"

    def __str__(self) -> str:
        return self.libelle


class UtilisateurSession(models.Model):
    """
    Rattachement exclusif : un agent n'appartient qu'a une session.

    La contrainte est posee au niveau du moteur (EXCLUDE USING gist), pas
    dans le code. Ne jamais la reimplementer en Python : deux enregistrements
    concurrents passeraient entre les mailles.
    """

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, db_column="utilisateur_id"
    )
    session = models.ForeignKey(SessionCourrier, on_delete=models.PROTECT, db_column="session_id")
    attribue_le = models.DateTimeField(auto_now_add=True)
    attribue_par = models.BigIntegerField(null=True, blank=True)
    retire_le = models.DateTimeField(null=True, blank=True)
    retire_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "utilisateur_session"
