# CB Bretagne — Notes de développement

> **Ce fichier est le journal de référence du projet.** Il doit suffire à reprendre
> le travail à froid (nouvelle machine, nouveau collègue) après un simple
> `git pull` + lecture. Tenir à jour à chaque session.

**État du projet (01/06/2026 — session 14) :** en test beta, en attente de retours
des collègues. Zone financement dans l'éditeur de devis + bibliothèque Aides partagée
(page dédiée + panneau dans l'éditeur). Items sécurité toujours reportés (voir Session
10 « Hors scope ») : durcissement config (`DEBUG`/`SECRET_KEY`), politique de rôle du
bypass OTP.

## Stack
- Django 6 · SQLite (dev) · PostgreSQL (prod Railway)
- Python 3.12 (prod) · Python 3.14 (dev Windows)
- Railway (prod actuel) → OVH VPS (Phase 4)
- Gunicorn · WhiteNoise · Django Admin

## Démarrage rapide (dev Windows)
```powershell
# Setup initial
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Lancer / migrer / tester / vérifier (utiliser le python du venv)
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py runserver      # http://127.0.0.1:8000/
venv\Scripts\python manage.py test core      # 21 tests (core/tests.py)
venv\Scripts\python manage.py check
```
- Sans `DATABASE_URL`, la base est `db.sqlite3` (locale). Connexion via `/login/`.
- Les tests de contrôle d'accès vivent dans `core/tests.py`.

## Déploiement (Railway)
- Remote git : GitHub `pekkip/lec-henn`. Prod : `lec-henn-production.up.railway.app`.
- **`git push origin main` → Railway redéploie automatiquement.** Le `Procfile`
  exécute `collectstatic --noinput && migrate && gunicorn cbretagne.wsgi`.
  `runtime.txt` = python-3.12.
- Variables d'env prod : `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`,
  `DATABASE_URL` (PostgreSQL Railway).
- `.gitignore` présent à la racine : `venv/`, `__pycache__/`, `*.pyc`,
  `db.sqlite3`, `staticfiles/`, `media/`, `.env`, `core/Corrections*/`.

## Architecture
```
cb-bretagne/
├── cbretagne/
│   ├── settings.py
│   └── urls.py (inclut core.urls)
└── core/
    ├── models.py
    ├── views.py
    ├── urls.py
    ├── permissions.py
    ├── admin.py
    ├── tests.py               — 21 tests (contrôle d'accès, clients)
    ├── migrations/
    └── templates/core/
        ├── base.html
        ├── login.html
        ├── dashboard.html
        ├── devis_list.html
        ├── devis_form.html        — création devis (widget client autocomplété)
        ├── devis_detail.html      — éditeur JS + onglet factures + zone financement
        ├── devis_pdf.html         — vue client imprimable
        ├── factures_list.html
        ├── facture_detail.html
        ├── facture_apercu.html    — aperçu facture imprimable
        ├── _apercu_ligne.html     — partial (ligne d'aperçu)
        ├── clients.html           — liste + filtres + modales création/édition
        ├── bibliotheque.html      — bibliothèque perso (éditeur arbre)
        ├── aides.html             — bibliothèque Aides partagée (page dédiée)
        ├── profil.html            — préférences utilisateur
        ├── utilisateurs_list.html
        ├── utilisateur_form.html
        └── utilisateur_succes.html
```

## Modèles principaux
- `ParametresAssociation` — nom, adresse, logo, SIRET, slogan
- `Territoire` → `Service` → `Equipe` — hiérarchie organisationnelle
- `ProfilUtilisateur` (OneToOne User) — role, taux_mo_defaut, saisie_ht, conditions_devis, conditions_facture, coordonnees_cb
- `Client` — nom, contact, email, telephone, adresse (rue), code_postal, ville, created_by (FK User)
- `Devis` — reference, client, chantier, equipe, taux_mo, status, conditions_devis, coordonnees_cb, **zone_financement** (bool), created_by
- `LigneDevis` — arbre imbriqué (TITRE/S/C/OUV/MO/MAT/FMO/FMAT/FIN), parent FK, **aide FK nullable**
- `BibliothèqueAides` — bibliothèque partagée (tous) : description, type_ligne (FMO/FMAT/FIN), montant_defaut, unite, organisme, created_by
- `Facture` — devis FK, type_doc (acompte/facture/avoir), status (draft/validated/sent/paid), numero (unique), montant, date_versement, conditions_facture, created_by
- `LigneFacture` — même structure que LigneDevis, ligne_devis_source FK
- `AuditLog` — toutes les actions tracées (devis, facture, bypass)
- `Bibliotheque` — articles réutilisables par utilisateur

## Modèle d'accès (règle métier — IMPORTANT)
- **Lecture** : **tout utilisateur connecté** peut consulter n'importe quel
  devis/facture (outil interne, visibilité partagée entre équipes).
- **Modification** : réservée à l'**équipe** — créateur du devis, membres de
  l'équipe du devis, responsable hiérarchique du créateur, ou admin.
- **Comptable** : lecture sur les devis (éditeur en consultation seule), mais
  conserve la validation/changement de statut des factures.
- Appliqué **côté serveur** (permissions.py) **et côté UI** : `devis_detail`
  passe `peut_modifier` → constante JS `CAN_EDIT` qui verrouille l'éditeur
  (bandeau « Consultation seule »). Le glisser-vers-bibliothèque reste actif pour
  tous (endpoints biblio par utilisateur). Voir Session 11.

## Permissions
```python
# core/permissions.py  — source unique des règles d'accès
get_profil_or_none(user)        # profil ou None (ne crée jamais ; vs views.get_profil)
# Lecture — tout utilisateur connecté :
peut_voir_devis() / peut_voir_facture()
# Modification — équipe (créateur / équipe / responsable / admin) :
peut_modifier_devis() / peut_modifier_facture()
peut_supprimer_devis()          # brouillons uniquement
peut_envoyer_facture()
peut_valider_facture()          # comptable + admin
peut_supprimer_facture()        # jamais si validée / envoyée / payée
peut_supprimer_client()         # admin
get_collegues_ids(user)         # IDs « mon équipe » (moi + équipes M2M + techniciens)
is_admin() / is_responsable() / is_comptable()
peut_gerer_utilisateurs() / peut_gerer_cet_utilisateur()
```

## URLs importantes
```
/                           dashboard
/devis/<pk>/                devis_detail (éditeur)
/devis/<pk>/pdf/            devis_pdf (vue client)
/devis/<pk>/entete/sauvegarder/   devis_entete_save (POST JSON)
/devis/<pk>/lignes/         lignes_get (GET JSON)
/devis/<pk>/lignes/sauvegarder/   lignes_save (POST JSON)
/factures/<pk>/             facture_detail
/factures/<pk>/apercu/      facture_apercu
/factures/<pk>/valider/     facture_valider (POST)
/factures/<pk>/statut/      facture_status (POST — attention: "statut" pas "status")
/factures/<pk>/date-versement/    facture_date_versement (POST JSON)
/factures/<pk>/bypass/      facture_bypass (POST)
/factures/<pk>/bypass/send/ facture_bypass_send_code
/profil/                    profil_view
/utilisateurs/              utilisateurs_list
/clients/                   clients_list (filtres GET : nom/code_postal/departement/ville/portee)
/clients/recherche/         client_search (GET JSON — autocomplétion + panneau)
/clients/creation-rapide/   client_quick_create (POST — JSON {id, nom})
/clients/<pk>/modifier/     client_edit (POST — admin uniquement)
/clients/<pk>/supprimer/    client_delete (POST — admin uniquement)
/bibliotheque/aides/        aides_page (page dédiée bibliothèque Aides)
/aides/                     aides_api_get (GET JSON — liste des aides)
/aides/sauvegarder/         aides_api_save (POST JSON — création aide)
/aides/<pk>/supprimer/      aide_delete (POST — suppression aide)
```

⚠️ Les noms d'URLs sont un mélange français/anglais à homogénéiser (statut/status, supprimer/delete).

## Charte graphique CB Bretagne
- Prune : #67123A (couleur principale)
- Teal : #00AA8D (accent)
- Amber : #F7A600 (accent secondaire — usage limité)
- Police : Montserrat (Google Fonts)
- Logo : embarqué en base64 dans devis_pdf.html et facture_apercu.html
- Logo horizontal pour en-tête documents, vertical pour usage courant

---

## Session 14 — 01/06/2026 — Zone financement & bibliothèque Aides

### Contexte
L'ancien bouton "Financement / subvention" ajoutait des lignes FIN en vrac sans
structure ni traçabilité. On a refactorisé vers une **zone financement** dédiée dans
l'éditeur + une **bibliothèque Aides partagée** permettant le suivi futur des
financements sur le dashboard.

### Fichiers modifiés
- `models.py` — nouveau modèle `BibliothèqueAides` (description, type_ligne
  FMO/FMAT/FIN, montant_defaut, unite, organisme, created_by) ; `Devis.zone_financement`
  (BooleanField, défaut False) ; `LigneDevis.aide` (FK nullable vers BibliothèqueAides)
- `migrations/0013_…` — schéma (3 champs + nouveau modèle)
- `migrations/0014_set_zone_financement_for_existing` — migration données : devis
  existants avec lignes FIN → `zone_financement=True`
- `views.py` — `ligne_to_dict` : ajout `aide_id` ; `lignes_get` : retourne
  `zone_financement` ; `lignes_save` : sauvegarde `zone_financement` + `aide_id` sur
  les LigneDevis ; nouvelles vues `aides_page`, `aides_api_get`, `aides_api_save`,
  `aide_delete`
- `urls.py` — routes `/bibliotheque/aides/`, `/aides/`, `/aides/sauvegarder/`,
  `/aides/<pk>/supprimer/`
- `base.html` — lien 🎁 Aides dans la sidebar (Configuration)
- `devis_detail.html` — refonte complète de la zone financement :
  - Bouton "Zone financement" (remplace "Financement / subvention"), disparaît quand
    la zone est active
  - `renderFinZone()` + `renderFinLine()` remplacent `renderFinGroup()`
  - Section "Aides" collapsible (−/+) en bas du panneau bibliothèque, visible
    seulement quand `zone_financement=True`
  - Glisser-déposer depuis la section Aides → zone financement, ou clic direct
  - Ligne liée à une aide : indicateur 🔗
  - Bouton "Ajouter une ligne" (ligne libre sans aide)
  - Bouton "Supprimer la zone" (supprime toutes les lignes FIN)
  - `saveTree()` inclut `zone_financement` dans le payload
  - Gestion inline des aides (créer / supprimer) depuis le panneau
- `aides.html` — page dédiée à la gestion de la bibliothèque Aides

### Décisions actées
- **Zone financement** : flag `zone_financement` sur Devis (plus propre que détecter
  la présence de lignes FIN) ; zone vide possible (activée sans lignes)
- **Suivi dashboard futur** : `LigneDevis.aide` FK nullable — dashboard pourra
  requêter `LigneDevis.objects.filter(aide__isnull=False, devis__status='accepted')`
  sans nouveau modèle. Pas de `UtilisationAide` séparé (simplifié).
- **Droits bibliothèque Aides** : tout le monde peut créer/supprimer — **choix assumé
  en BETA**. `aide_delete`/`aides_api_save` n'ont que `@login_required` (pas de rôle).
  À restreindre lors du passage à l'hébergement/stockage définitif (voir Phase 4).
- **FMO/FMAT dans la barre** : conservés tels quels pour les lignes normales
- **Statut devis** : select dans la topbar déjà présent (session précédente) — OK

### Dette introduite cette session
→ Reportée dans **§ Dette technique** (source unique) : tests manquants
(zone_financement / aides), nom de modèle `BibliothèqueAides` avec accent.

---

## Session 13 — 01/06/2026 — Refonte gestion & sélection des clients

### Contexte
La sélection du client à la création d'un devis se faisait via un `<select>` listant
tous les clients (`Client.objects.all()`) — ingérable à mesure que le volume monte.
La page liste clients n'avait aucun filtre et le modèle `Client` n'avait ni adresse
structurée ni traçabilité du créateur.

### Fichiers modifiés
- `models.py` — `Client` : ajout `code_postal`, `ville`, `created_by` (FK User,
  SET_NULL) ; `adresse` représente désormais la **rue**
- `migrations/0011_…` — schéma (3 champs) ; `migrations/0012_assign_clients_to_admin`
  — **migration de données** : clients existants attribués au 1er admin (role=='admin',
  fallback 1er superuser)
- `permissions.py` — ajout `get_collegues_ids(user)` (moi + membres partageant une
  équipe M2M + techniciens subordonnés), même logique de partage que `_partage_equipe_devis`
- `views.py` (section CLIENTS) :
  - `clients_list` — filtrage serveur GET : `nom` (icontains), `code_postal`
    (startswith), `departement` (startswith), `ville` (icontains), `portee`
    (tous/moi/equipe via `get_collegues_ids`) ; passe `is_admin` + valeurs de filtres
  - `client_search` (GET JSON) — `nom__icontains`, 20 résultats max ; sert
    l'autocomplétion **et** le panneau filtrable
  - `client_quick_create` (POST JSON) — création depuis l'écran de devis, renvoie
    `{id, nom}`, set `created_by`
  - `client_create` — lit `code_postal`/`ville` + set `created_by`
  - `client_edit` (POST, **admin only**) — édition complète (la suppression existait déjà)
- `urls.py` — routes `client-search`, `client-quick-create`, `client-edit`
- `base.html` — helper JS global `remplirVilleDepuisCP(cpInput, villeInput)` :
  interroge **geo.api.gouv.fr** (gratuit, sans clé) ; 1 commune → auto, plusieurs →
  datalist de choix, API injoignable → saisie manuelle conservée
- `devis_form.html` — `<select>` remplacé par widget autocomplétion (input texte +
  hidden `name="client"`) + panneau « Parcourir » + modal « Nouveau client » (CP→ville) ;
  garde-fou JS bloquant l'envoi sans client. **Vue `devis_create` inchangée.**
- `devis_detail.html` (en-tête) — même widget (préfixes `eh*`), hidden `#eh-client`
  conserve le pk → `saveEntete()` **inchangée** ; boutons masqués en consultation seule
- `clients.html` — barre de filtres GET, colonnes Ville/CP, modal création (CP→ville),
  modal édition pré-rempli via `data-*` + boutons Éditer/Supprimer **admin only**
- `admin.py` — `ClientAdmin` : ajout `code_postal`, `ville`, `created_by`
- `tests.py` — classe `ClientsTests` (9 tests) : recherche, création rapide
  (created_by + nom vide→400), filtres portée moi/équipe + département, édition admin
  vs refus non-admin. **21/21 OK.**

### Décisions actées
- **Adresse structurée** : `code_postal` + `ville` ajoutés (étape 3 NOTES_DEV faite) ;
  `adresse` = rue
- **CP → ville** via geo.api.gouv.fr côté navigateur ; multi-communes → liste de choix
- **Portée liste clients** = sélecteur 3 choix (Tous / Mes clients / Mon équipe)
- **Clients orphelins** (sans créateur) → migration de données vers le 1er admin
- **Édition/suppression client** réservées à l'**admin** (pour l'instant)
- Compat ascendante : `devis_create` et `devis_entete_save` lisent toujours
  `client`/`client_id` ; seuls les widgets de saisie changent

---

## Session 12 — 01/06/2026 — Correctifs aperçu facture, acompte, coordonnées CB

### Fichiers modifiés
- `.gitignore` — créé (n'existait pas) : `venv/`, `__pycache__/`, `*.pyc`, `db.sqlite3`, `staticfiles/`, `media/`, `.env`, `core/Corrections*/`. 157 fichiers parasites retirés du suivi git (25 `.pyc`, 130 `staticfiles/`, `db.sqlite3`, logo media).
- `models.py` — ajout `prix_unitaire()` sur `LigneFacture` (fallback `total()/quantite` si `cout_unitaire` est `None`)
- `views.py`
  - `facture_apercu` : correction déduction acompte — ne s'applique plus qu'à la **première** facture non-acompte non-annulée (par `created_at`) ; les autres factures affichent solde = montant brut
  - `devis_pdf` : ajout `coordonnees_cb` au contexte (le template avait déjà le bloc HTML/CSS mais la variable n'était pas transmise)
  - `profil_view` : sauvegarde de `coordonnees_cb` depuis le POST
  - `devis_entete_save` : sauvegarde de `coordonnees_cb` depuis le JSON
- `facture_apercu.html` — lignes TITRE affichent désormais : description | Qté 1 | unité vide | P.U. HT = total section | Total HT = total section. Les lignes enfants utilisent `prix_unitaire()` (méthode modèle) à la place de `cout_unitaire` brut.
- `profil.html` — nouvelle carte « Coordonnées CB Bretagne » (textarea avant « Conditions par défaut »)
- `devis_detail.html` — textarea `coordonnees_cb` dans l'onglet En-tête (Paramètres) + inclus dans le payload `saveEntete()`

### Décisions actées
- **Acompte** : règle métier — déduction uniquement sur la 1ʳᵉ facture non-acompte du devis ; les suivantes n'en tiennent pas compte
- **Lignes TITRE** dans l'aperçu facture : traitées comme un forfait (Qté 1, pas d'unité, P.U. = total de la section)
- **`coordonnees_cb`** : champ texte libre sur `ProfilUtilisateur` et `Devis` (snapshot à la création), éditable dans l'en-tête du devis, affiché dans `devis_pdf` et `facture_apercu` au-dessus de la désignation
- **Media/** entièrement exclus du git (logo prod non servi jusqu'à Phase 4 volume persistant OVH)

### Incidents Railway
- Trial Railway expiré brièvement en cours de session (faux positif, résolu seul)
- Railway a redéployé un ancien commit (`817ae84`) → commit vide `043280e` pour forcer un redéclenchement du webhook

---

## Session 11 — 01/06/2026 — Mode consultation seule (hors équipe)

### Contexte
Règle métier confirmée : **tout utilisateur connecté peut consulter** n'importe
quel devis/facture, mais seuls les membres de l'équipe (créateur / équipe /
responsable / admin) peuvent **modifier**. La session 10 avait trop restreint la
lecture ; corrigé ici. Côté UI, l'éditeur de devis paraissait modifiable pour
tout le monde (échec seulement à l'enregistrement, 403). On verrouille désormais
visuellement l'éditeur pour les non-membres, tout en gardant le glisser-vers-biblio.

### Fichiers modifiés
- `permissions.py` — `peut_voir_devis` relâché : tout utilisateur connecté peut
  consulter (la restriction équipe ne porte que sur la modification)
- `views.py` — `devis_detail` passe le flag `peut_modifier` au template
- `devis_detail.html` — mode consultation seule piloté par `CAN_EDIT` :
  - lignes non éditables (contenteditable off, inputs désactivés, boutons
    copier/supprimer + ajout masqués), réorganisation et raccourcis clavier bloqués
  - boutons Sauvegarder (lignes + en-tête), sélecteur de statut, « Nouvelle
    facture » masqués ; champs En-tête désactivés
  - bandeau « 🔒 Consultation seule »
  - **glisser une ligne → « Ajouter à ma biblio » conservé** (les lignes restent
    draggable ; seules les cibles de réorganisation sont bloquées). Endpoints
    biblio par utilisateur, jamais bloqués par l'équipe.
- `tests.py` — tests mis à jour (lecture autorisée hors équipe) + 2 tests mode
  consultation seule / éditable. 12/12 OK.

### Décisions actées
- Lecture = tout utilisateur connecté ; modification = équipe (inchangé côté serveur)
- Le comptable obtient aussi l'éditeur en lecture seule (il ne saisit pas les
  lignes) mais garde ses actions sur les factures (validation/statut) via leurs
  propres permissions
- Le glisser-vers-bibliothèque fonctionne pour tous, y compris en consultation seule

---

## Session 10 — 01/06/2026 — Audit sécurité & contrôle d'accès

### Contexte
Audit du code : l'autorisation était appliquée de façon incohérente. Plusieurs
vues `@login_required` agissaient sur un objet récupéré par `pk` **sans vérifier
que l'utilisateur y a droit** (IDOR). Plusieurs corrections annoncées en session 9
n'étaient en réalité **pas** présentes dans le code (notes/code divergés) — elles
sont maintenant réellement faites.

### Fichiers modifiés
- `permissions.py` — `_get_profil` → `get_profil_or_none` (exception resserrée sur
  `ProfilUtilisateur.DoesNotExist`) ; ajout `peut_voir_devis`, `peut_voir_facture`,
  `peut_modifier_facture` (source unique des règles d'accès)
- `views.py` — gates d'accès sur toutes les vues devis/facture non protégées,
  correctifs critiques, nettoyage doublons + casts numériques
- `models.py` — suppression de `ProfilUtilisateur.peut_acceder_devis` (logique
  déplacée dans permissions.py)
- `devis_detail.html` — modale bypass : vérification du code côté serveur
  (plus de comparaison client), variable morte `savedCode` retirée
- `tests.py` — 9 tests de régression sur le contrôle d'accès (9/9 OK)

### Décisions actées
- **Critique — `facture_status`** : ajout de `peut_modifier_facture` (était
  totalement ouvert : n'importe quel utilisateur pouvait passer une facture à payé)
- **Critique — bypass OTP** : `code` retiré de la réponse JSON + vérification
  déplacée côté serveur. ⚠️ Le bypass est donc **dormant** tant que SMTP n'est pas
  branché (le code n'est jamais délivré). Politique de rôle (admin/responsable
  uniquement vs suppression de la fonctionnalité) **à décider**.
- **Critique — `facture_create`** : `@login_required` réellement ajouté + routé via
  `peut_modifier_devis`
- **IDOR** : gates ajoutés sur `devis_detail`, `devis_pdf`, `devis_duplicate`,
  `lignes_get`, `devis_status`, `facture_apercu`, `facture_detail` (laisse
  désormais entrer le comptable), `facture_date_versement`, `facture_libelle_save`,
  `lignes_facture_get`, `lignes_facture_save` (403 JSON pour l'API, redirect pour
  le HTML)
- **Réconciliation des permissions** : `permissions.py` est désormais la source
  unique ; le doublon `ProfilUtilisateur.peut_acceder_devis` est supprimé
- **Doublon `clients_list`/`client_create`** réellement supprimé
- **Casts numériques** (`validite_jours`, `echeance_jours`, `taux_mo`) protégés par
  try/except (plus de 500 sur saisie invalide)
- **Format de date** `facture_date_versement` (`%d/%m/%Y`) confirmé correct — le JS
  envoie bien jj/mm/aaaa ; rien à changer

### Hors scope (reporté)
→ Items consolidés dans **§ Dette technique** (bas du fichier, source unique) :
durcissement config, race `gen_reference`, double comptage `total_facture()`,
politique de rôle du bypass OTP.

---

## Session 9 — 01/06/2026

### Fichiers modifiés
- `models.py` — ajout `coordonnees_cb` sur ProfilUtilisateur et Devis
- `views.py` — 10 corrections (voir décisions)
- `devis_detail.html` — saisie_ht + bugs JS + refonte liste factures + modale paiement
- `devis_pdf.html` — refonte complète charte CB Bretagne
- `facture_apercu.html` — refonte complète charte CB Bretagne + acomptes + solde
- `migrations/0010_devis_coordonnees_cb_and_more.py` — migration coordonnees_cb

### Décisions actées
- `saisie_ht` branché dans l'éditeur JS — conversion HT→TTC ×1.20 avant stockage
- 5 bugs JS corrigés dans devis_detail (historySnapshot double, _tauxMOCourant, saveTree icône, doublons biblio, console.log)
- Comportement focus/clic corrigé sur les zones de texte contenteditable
- `coordonnees_cb` — snapshot à la création du devis depuis le profil, modifiable dans l'en-tête, transmis à devis_pdf et facture_apercu
- Logique conditions service → utilisateur → devis/facture implémentée dans devis_create et facture_create
- Charte CB Bretagne appliquée sur devis_pdf et facture_apercu
- Facture proforma — brouillon affiché "Facture proforma" dans l'aperçu client uniquement
- Cycle facture complet — draft → validé → envoyé → payé, boutons matriciels par statut, journal d'audit tracé
- Acomptes — déduction visuelle dans la facture finale (montant brut − acomptes payés = solde), non modifié en DB
- `gen_reference('FAC')` corrigé — cherche dans tous les types de factures (évite collision champ unique)
- `ligne_devis_source_id` préservé dans `lignes_facture_save`
- `@login_required` ajouté sur `facture_create`
- `conditions_facture` copié à la création de facture
- OTP bypass — code retiré de la réponse JSON (commentaire WARNING ajouté, à sécuriser dès SMTP)
- Doublon `clients_list`/`client_create` supprimé
- `datetime.strptime` corrigé dans `facture_date_versement`

---

## Session 8 — session précédente

### Fichiers modifiés
- `permissions.py` — renommage `_get_profil` + ajout `peut_gerer_utilisateurs` / `peut_gerer_cet_utilisateur`
- `views.py` — suppression doublon clients_list, OTP bypass retiré, 5 vues utilisateurs
- `urls.py` — regroupement devis-entete-save + 4 routes utilisateurs + succès création
- `dashboard.html` — f.reference → f.get_reference
- `base.html` — lien Utilisateurs sidebar (admin + responsable)
- `utilisateurs_list.html` — liste avec désactivation/réactivation inline
- `utilisateur_form.html` — formulaire création / édition
- `utilisateur_succes.html` — mot de passe temporaire affiché une fois
- `settings.py` — whitenoise middleware + STATICFILES_STORAGE
- Railway — collectstatic --noinput avant migrate

### Décisions actées
- Pas de suppression d'utilisateur — désactivation uniquement (is_active = False)
- Responsable voit uniquement ses propres équipes dans le formulaire de création
- Seul un admin peut créer ou attribuer le rôle admin
- Mot de passe temporaire affiché une seule fois — invitation email dès SMTP M365 dispo
- Copie de bibliothèque optionnelle — tous les utilisateurs actifs, sans filtre équipe

---

## Prochaines étapes

1. **Valider l'éditeur de facture avec Frédérick et Yann** — colonnes MO/MTx séparées ou prix unique
2. **Valider la logique conditions** devis/facture (niveau service vs utilisateur) avec l'équipe
3. ~~**Champ Client** — adresse structurée (rue / CP / ville)~~ ✅ fait session 13
4. **Changement de mot de passe depuis le profil** (attendre SMTP M365)
5. **Statut devis "envoyé au client"** ✅ select dans la topbar (session 14), mais pas encore affiché dans la liste des devis
6. **Dashboard — section suivi financements** : `LigneDevis.objects.filter(aide__isnull=False, devis__status='accepted')` prêt à requêter
7. **PDF WeasyPrint — Phase 3**

---

## Dette technique (SOURCE UNIQUE)

> Liste **vivante** de la dette ouverte. Les logs de session (au-dessus) sont
> figés — ne pas y dupliquer de TODO : tout item à reprendre vit **ici**.

### Sécurité / config
- **Durcissement config** — `DEBUG` défaut True + `SECRET_KEY` retombe sur une clé dev
  si les variables d'env manquent (settings.py). Cible : `DEBUG=False` par défaut, échec
  fort si `SECRET_KEY` absente en prod.
- **OTP bypass** — ✅ `code` retiré du JSON + vérif côté serveur (session 10). Reste :
  envoyer le code par e-mail à `request.user.email` dans `facture_bypass_send_code` dès
  SMTP M365 branché ; décider la politique de rôle. ⚠️ Bypass **dormant** d'ici là.
- **Bibliothèque Aides — droits** — `aide_delete`/`aides_api_save` ouverts à tout
  utilisateur connecté (**BETA assumé**). Restreindre (admin/responsable ?) au passage
  hébergement définitif — Phase 4.

### Données / logique métier
- **`gen_reference`** — calcule max+1 en Python → race condition sur la numérotation concurrente.
- **`total_facture()`** (models.py) — double comptage potentiel acompte + facture, à confirmer vs compta.
- **TVA** — "non applicable art. 293B CGI" à adapter selon le régime fiscal réel.

### Code / archi
- **URLs à homogénéiser** — mélange français/anglais (statut/status, supprimer/delete). Choisir une convention et corriger partout.
- **Context processor** — injecter `profil` automatiquement dans tous les templates (évite `get_profil(request.user)` dans chaque vue).
- **Modèle `BibliothèqueAides`** — nom de classe avec accent (non-ASCII), fragile pour imports/outils. Renommer en ASCII (`BibliothequeAides`) si on retouche le modèle.
- **Auditer les templates** — chercher `f.reference` parasites (→ doit être `f.get_reference`).

### Tests
- **Couverture session 14 manquante** — zone_financement (persistance), `aides_api_save` (nom vide → 400, type invalide), `aide_delete`. **21 tests** au total aujourd'hui.

### Performance
- **Dashboard** — remplacer les boucles Python par `aggregate(Sum(...))` — Phase 3.

### Fonctionnel (à prévoir)
- **Snapshot PDF** — case "marquer comme envoyé" + mécanisme de dégel.
- **Barre de progression par titre** — affiche le total des factures précédentes, pas le montant par titre.

### Infra
- **SMTP Microsoft 365** — boîte partagée `noreply@domaine.fr`, SMTP AUTH dans Exchange admin, `EMAIL_BACKEND` Django.
- **Migration Railway → OVH (Phase 4)** — volume persistent pour les fichiers uploadés (logo, etc.).
