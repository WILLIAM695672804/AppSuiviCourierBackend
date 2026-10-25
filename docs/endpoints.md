# Endpoints API

Liste generee depuis le schema OpenAPI de Django Ninja. Tous les chemins sont montes sous `/api/`.

Endpoints techniques:

- `GET /api/openapi.json`
- `GET /api/docs`

Total applicatif: 132 endpoints.

## Identite

- `POST /api/connexion`
- `POST /api/deconnexion`
- `GET /api/moi`

## Habilitation

- `GET /api/habilitations/utilisateurs`
- `POST /api/habilitations/utilisateurs`
- `GET /api/habilitations/utilisateurs/{utilisateur_id}`
- `PATCH /api/habilitations/utilisateurs/{utilisateur_id}`
- `PATCH /api/habilitations/utilisateurs/{utilisateur_id}/etat`
- `GET /api/habilitations/profils`
- `POST /api/habilitations/profils`
- `PATCH /api/habilitations/profils/{profil_id}`
- `POST /api/habilitations/profils/{profil_id}/invalidation`
- `PATCH /api/habilitations/profils/{profil_id}/permissions`
- `POST /api/habilitations/utilisateurs/{utilisateur_id}/profils`
- `DELETE /api/habilitations/utilisateurs/{utilisateur_id}/profils/{profil_id}`
- `GET /api/habilitations/perimetres`
- `PATCH /api/habilitations/utilisateurs/{utilisateur_id}/perimetre`
- `GET /api/habilitations/sessions`
- `POST /api/habilitations/sessions/{session_id}/agents`
- `DELETE /api/habilitations/sessions/{session_id}/agents/{utilisateur_id}`
- `GET /api/habilitations/delegations`
- `POST /api/habilitations/delegations`
- `GET /api/habilitations/delegations/miennes`
- `GET /api/habilitations/delegations/possible`
- `DELETE /api/habilitations/delegations/{delegation_id}`

## Referentiels

- `GET /api/referentiels/structures`
- `GET /api/referentiels/postes`

## Organisation

- `POST /api/organisation/structures`
- `GET /api/organisation/niveaux`
- `POST /api/organisation/niveaux`
- `PATCH /api/organisation/niveaux/{niveau_id}`
- `GET /api/organisation/postes`
- `POST /api/organisation/postes`
- `PATCH /api/organisation/postes/{poste_id}`
- `POST /api/organisation/postes/{poste_id}/cloture`
- `GET /api/organisation/affectations`
- `POST /api/organisation/affectations`
- `POST /api/organisation/affectations/{affectation_id}/fin`

## Administration

- `GET /api/administration/tableau-de-bord`

## Parametrage

- `GET /api/parametrage`
- `PATCH /api/parametrage/regles-metier/{cle}`
- `POST /api/parametrage/regles-metier/{cle}/arbitrage`

## Tracabilite

- `GET /api/tracabilite/evenements`
- `GET /api/tracabilite/acces`
- `GET /api/tracabilite/historique`

## Pieces jointes

- `GET /api/pieces`
- `POST /api/pieces`
- `GET /api/pieces/{uid}/contenu`
- `POST /api/pieces/{uid}/retrait`
- `GET /api/pieces/types`

## Notifications

- `GET /api/notifications`
- `POST /api/notifications/{notification_id}/lecture`
- `POST /api/notifications/lecture`
- `GET /api/notifications/file`

## Performance

- `GET /api/performance/matrice`
- `GET /api/performance/matrice/{sigle}`
- `GET /api/performance/dictionnaire`
- `GET /api/performance/calendrier`
- `POST /api/performance/calendrier`
- `POST /api/performance/indicateurs`

## Activites

- `GET /api/activites`
- `POST /api/activites`
- `GET /api/activites/plan`
- `GET /api/activites/plans`
- `GET /api/activites/obligations`
- `GET /api/activites/{activite_id}`
- `POST /api/activites/{activite_id}`
- `POST /api/activites/{activite_id}/avancement`
- `POST /api/activites/{activite_id}/indicateurs`
- `POST /api/activites/{activite_id}/indicateurs/{indicateur_id}/releve`
- `POST /api/activites/{activite_id}/taches`
- `POST /api/activites/{activite_id}/pieces`
- `POST /api/activites/{activite_id}/suspension`
- `POST /api/activites/{activite_id}/instructions`
- `POST /api/activites/{activite_id}/instructions/{instruction_id}/levee`
- `POST /api/activites/{activite_id}/relance`
- `POST /api/activites/plan/etat`
- `POST /api/activites/obligations/{obligation_id}/depot`

## Gouvernance

- `GET /api/gouvernance/tableau-de-bord`
- `GET /api/gouvernance/decisions`
- `POST /api/gouvernance/decisions`
- `GET /api/gouvernance/seances`
- `POST /api/gouvernance/seances`
- `GET /api/gouvernance/disponibilites`
- `POST /api/gouvernance/disponibilites`
- `GET /api/gouvernance/filiales`
- `GET /api/gouvernance/representations`
- `GET /api/gouvernance/conges`
- `GET /api/gouvernance/decisions/{engagement_id}`
- `GET /api/gouvernance/seances/{seance_id}`
- `POST /api/gouvernance/decisions/{engagement_id}/avancement`
- `POST /api/gouvernance/decisions/{engagement_id}/relance`
- `POST /api/gouvernance/seances/{seance_id}/documents`

## Exploitation

- `GET /api/exploitation/releves`
- `POST /api/exploitation/chenal`
- `POST /api/exploitation/recouvrements`

## Dossiers

- `GET /api/dossiers`
- `POST /api/dossiers`
- `GET /api/dossiers/modeles`
- `GET /api/dossiers/{identifiant}`
- `POST /api/dossiers/{identifiant}/complements`
- `POST /api/dossiers/{identifiant}/complements/{complement_id}/reception`
- `POST /api/dossiers/{identifiant}/retour`
- `POST /api/dossiers/{identifiant}/fusion`

## Archivage

- `GET /api/archivage/referentiel`
- `POST /api/archivage/referentiel`
- `POST /api/archivage/referentiel/{regle_id}/validation`
- `GET /api/archivage/versements`
- `GET /api/archivage/versements/{identifiant}`
- `POST /api/archivage/versements/{identifiant}/versement`
- `POST /api/archivage/versements/{identifiant}/preuve`
- `GET /api/archivage/conformite`

## Pilotage

- `GET /api/pilotage/cockpit`
- `GET /api/pilotage/synthese`
- `GET /api/pilotage/structures`
- `GET /api/pilotage/tableau-de-bord`
- `GET /api/pilotage/rapports`
- `GET /api/pilotage/rapports/export`
- `GET /api/pilotage/statistiques`
- `GET /api/pilotage/analyses`
- `GET /api/pilotage/programme`

## Direction generale

- `GET /api/direction/vue-ensemble`

## Comite de direction

- `GET /api/comite/vue-ensemble`

## Portail usagers

- `GET /api/portail/demandes`
- `POST /api/portail/demandes`
- `GET /api/portail/demandes/{identifiant}`
- `POST /api/portail/demandes/{identifiant}/messages`
- `GET /api/portail/preferences`
- `POST /api/portail/preferences`
- `GET /api/portail/echanges`

## Supervision

- `GET /api/supervision`
- `GET /api/supervision/integrations`
