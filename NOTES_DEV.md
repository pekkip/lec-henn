# CB Bretagne — Notes de développement

> **Contexte essentiel du projet, à relire à froid.** Ce fichier se concentre sur l'essentiel :
> état actuel, démarrage, architecture, dette technique, infra et documents de conception.
> **Le journal chronologique détaillé (session par session) est dans
> [`NOTES_DEV_ARCHIVE.md`](NOTES_DEV_ARCHIVE.md).** Tenir les deux à jour à chaque session.

> **RAPPEL DESIGN** — refonte portée en code (sessions design 19-20/06/2026). Charte actée : Montserrat, prune #67123A / turquoise #00AA8D / or #F7A600 / rouge danger #C0392B. Chrome : topbar blanc (logo couleur) + slogan Montserrat Alternates italic, sidebar prune, page-hd prune (boutons primaires → fond blanc / texte prune). Textes ≥ 14 px, contraste AA. Relevé option A (canvas + tiroir), cibles ≥ 48 px. Planning : couleurs automatiques via variables. Wizard Affecter : indicateur cercles + barre. Émargement : cren-grp contraste corrigé (teal-dk). ✅ **Uniformisation design complète** — éditeur devis traité (session 53, 20/06/2026).

## Consignes de collaboration

- **Doute sur ce que l'utilisateur voit ou veut** → poser des questions ciblées plutôt que partir sur des hypothèses. Utiliser l'outil `AskUserQuestion` pour des questions à choix, ou poser une question directe dans le chat.
- **Ne pas improviser** sur l'apparence, le comportement ou les données côté navigateur sans avoir confirmé le problème exact (ex. : demander si les dates sont absentes ou décalées, quel élément manque de contraste, etc.).
- **Modifications de fichiers** : utiliser les outils natifs `Edit`/`Read`/`Write` directement.

## État actuel

Outil interne de **devis / facturation** pour les Compagnons Bâtisseurs Bretagne (Django 6,
VPS OVH, PostgreSQL en prod). Couvre : **clients** (carnet de contacts), **devis** (lignes
simple / composite / forfait, bibliothèque perso + Aides partagées), **factures** (partielles
avec report des lignes non facturées, acomptes, avoirs), **outils compta** (factures structure /
appels de convention), tableau de bord à widgets. **Import de devis PDF (OCR) + XLS/XLSX** =
fonction **transitoire** de reprise de l'historique EBP, disponible **jusqu'à la mise en service**
de l'outil. **Module Insertion** : planning, émargement, feuilles de présence (manuel séparé
`/insertion/aide/`). Numérotation continue `DE/FA/AC/AV#####`. Manuel utilisateur sur `/manuel/`.
~225 tests.

**En cours / en attente** : réponse de l'IT nationale (DNS `gestioncbb.compagnonsbatisseurs.eu`
+ app Entra ID `Mail.Send` pour remplacer Brevo — certificat déjà généré sur le VPS). Tant que
ce n'est pas livré, l'envoi d'e-mails vers `@compagnonsbatisseurs.eu` reste best-effort (rebond
M365). Détail : § Infra.

**Détail session par session → [`NOTES_DEV_ARCHIVE.md`](NOTES_DEV_ARCHIVE.md).** Les 3 dernières
entrées sont reproduites ci-dessous.

### Dernières sessions

**État du projet (29/06/2026 — session 72) : Import factures PDF (rattachées au devis) + fiabilisation du moteur de montants partagé.** Nouvel outil symétrique de l'import devis PDF, mais qui **rattache chaque facture au devis** dont la réf. figure dans le PDF (« Référence Devis : DE##### »). **Fichiers créés :** `core/import_facture_pdf.py` (`parse_facture_pdf` réutilise tout le moteur de `import_pdf` + extraction `reference_devis` ; `create_facture_from_parsed(parsed, devis, user)`), `core/templates/core/import_factures.html` (UI 2 étapes, miroir devis, **sans sélecteur d'équipe** — héritée du devis), `core/management/commands/import_factures_pdf.py` (**outil principal**, import par dossier, dry-run, blocage si devis absent). **Modifiés :** `views.py` (+`import_factures_view`/`_parse_one`/`_confirm`, **admin uniquement** via `is_admin`), `urls.py` (3 routes), `factures_list.html` (lien « Import PDF » **visible admin seulement**), `tests.py` (+10 tests `ImportFacturesTests`). **Décisions (utilisateur) :** factures importées au statut **« Envoyée »** (`sent`) ; `montant` figé sur le **« Montant Net de Taxes »** du PDF (source de vérité du `total_facture()`/`reste_a_facturer`, qui somment le champ `montant`) ; `date_creation` réécrite à la date du PDF (UPDATE car `auto_now_add`) ; **si le devis correspondant est introuvable → fichier BLOQUÉ + alerte** (réimporter après le devis). **Fiabilisation du moteur partagé `import_pdf._parse_amounts_from_text`** (bénéficie aussi au devis) : (1) **numéros de ligne alphanumériques** (`_NODE_NUM`) pour les factures de situation (sections `B`, `B.2.1`) ; (2) nouveau `_split_costs` — EBP imprime des montants lexicalement ambigus (coûts forfaitaires entiers « 50 »/« 2944 », coûts à 1 décimale « 17,5 », totaux à 2 décimales + milliers espacés « 1 068,00 » ; « 89 1 068,00 » = « 89 »+« 1 068,00 »). On lève l'ambiguïté par **recoupement arithmétique** : on cherche la partition (mat | mo | total) telle que `qté × (mat+mo) == total imprimé`. Repli sur l'ancien découpage naïf si rien ne recoupe → le marqueur « ⚠ ÉCART » signale les vraies anomalies. **Validé sur les 5 factures exemples** (`mockups/ExempleFactures/`) : FA02913/02954/02955/02961 recoupent au centime ; FA02985 a une **incohérence EBP réelle** ligne 1.4.1 (13 × (26,57+119,60)=1900,21 ≠ 1900,47 imprimé) → ligne marquée, montant = total PDF. **235 tests OK + `check` vert.** Note : l'« écart forfait entier » latent existait aussi à l'import devis ; il est désormais corrigé pour les deux outils.

**État du projet (27/06/2026 — session 71) : Refonte complète du manuel utilisateur + renommage aide→manuel.** **(1) Renommage** : `aide.html` → `manuel.html` (`git mv`), route `/aide/` → `/manuel/`, vue `aide_view` → `manuel_view`, URL name `aide` → `manuel`, lien sidebar `base.html`, texte email invitation, références dans `NOTES_DEV.md` / `REFONTE_PLANNING.md` / `docs/plan_ameliorations.md`. **(2) Refonte complète de `manuel.html`** : réécriture totale (de ~session 32 à jour). 12 chapitres : Connexion, Tableau de bord, Clients, En bref (flux), Devis, Factures, Outils compta, Bibliothèque, Aides travaux, Numérotation, Profil, Utilisateurs. Points clés : flux Devis→Facture détaillé (sélection/création client, types de lignes Titre/Simple/Composite/Forfait/MO/MAT/Saut de page, bibliothèque catégories vs groupes) ; facturation partielle (lignes à 0 reportées, historique par titre) ; mécanique acompte (avance déduite du solde, verrou validation) ; cycle validation (Brouillon→Validée→Envoyée→Payée + bypass) ; import devis PDF + XLS ; aperçus sans TVA ; nouveau format de numérotation `DE#####`/`FA#####`/`AC#####`/`FACTURE-ST#####`/`AV#####`. **6 schémas HTML/CSS** inline (flux, cycle validation, acompte, facturation partielle, étapes import, mini-maquette éditeur). **11 captures** (`{% static 'core/manuel/*.png' %}`) avec fallback placeholder pointillé (`onerror` + `.shot-todo`). Supprimé : mention « mot de passe oublié » (email noreply non fonctionnel) + « email d'invitation automatique ». Séparation insertion : fonctions planning/émargement/feuilles restent dans `aide_insertion.html` (non touché). **(3) Correctifs CSS** : `.tip strong, .warn strong { display:block }` → `.tip strong.hd, .warn strong.hd { display:block }` (15 titres `class="hd"`) — le gras inline dans les encarts ne saute plus à la ligne. Correction `shot shot-todo` → `shot` en dur dans le template (les captures restaient masquées même présentes). **Nouveau dossier** `core/static/core/manuel/` (11 PNG fournis par l'utilisateur + README convention). **225 tests OK + `check` vert.**

**État du projet (27/06/2026 — session 70) : Import devis XLS/XLSX — extracteur complet (3 formats + métadonnées zones de texte BIFF).** Nouvel outil d'import des devis historiques au format tableur, symétrique à l'import PDF. **Fichiers créés/modifiés :** `core/import_xls.py` (parseur complet, ~350 lignes), `core/import_pdf.py` (1 ligne : `importe_pdf=parsed.get('importe_pdf', True)`), `core/views.py` (+3 vues `import_devis_xls_view` / `import_devis_xls_parse_one` / `import_devis_xls_confirm` + helper `_render_xls_preview` + constante `MAX_IMPORT_XLS=20`), `core/urls.py` (+3 routes), `core/templates/core/import_devis_xls.html` (UI 2 étapes, miroir de l'import PDF). **Trois formats détectés automatiquement** (scan `'descriptif'` dans les 40 premières lignes) : **Format A** (CHURAQUI, FAURE — N°ordre col 0, Descriptif col 1, cols 4-7) ; **Format B** (BLUMENAU, MARION — pas d'en-tête, cols 2-6) ; **Format C** (DEMAILLE .xlsx — N°ordre col 1, Descriptif col 2, cols 3-7). Construction de l'arbre : `_classify_row_A/B/C` → (`TITRE`, depth, node) ou (`LEAF`, …) → `_attach` (depth_stack) → `_prune_empty_titres`. Correctifs clés : float xlrd `1.0`→`'1.0'` (titres Format A) ; unité `'j'` = journée main-d'œuvre ; scan total limité aux 9 premières colonnes (évite les annotations). **Extraction métadonnées depuis les zones de texte BIFF (`_extract_shape_metadata`)** : les fichiers XLS stockent leurs en-têtes dans des records BIFF de type 0x3c (drawing text, inaccessibles via xlrd). Scan direct des bytes bruts : **(1) référence + date + validité** depuis le bloc `DD/MM/YYYY\nréf\n[X mois|date fin]\nXX` ; **(2) code secteur comptable** (2 chiffres, → `equipe_hint`) via regex `\n(\d{2})[\t<\x00]` sur bytes bruts (évite la contamination par les bytes d'en-tête de record BIFF qui suivent immédiatement le texte) ; **(3) objet** = dernière occurrence de `Objet :\s+<texte>` dans le fichier (les fichiers contiennent une zone blanche/blanc template identique en premier, le vrai objet vient ensuite) ; **(4) client (nom + adresse + CP + ville)** depuis le record `Client:|Habitant:|Adresse  :` (label + LF + nom + LF + adr + LF + cp ville). Formats des exemples : CHURAQUI `Client:`, FAURE `Habitant:`, BLUMENAU/MARION `Adresse  :` ; DEMAILLE (xlsx) extrait le client depuis les cellules. **Résultats sur les 5 fichiers exemples** : CHURAQUI (`FD01-2026`, Mme CHURAQUI Céline, 1051,82 €, 5 lignes ✓) ; FAURE (`DE-FD-05-2025`, M. et Mme FAURE Arnaud & Geneviève, 518,28 €, 8 lignes ✓) ; BLUMENAU (`GP 2026-35-01`, M BLUMENAU Bernhard, 2132,88 €, 19 lignes ✓) ; MARION (`GP 30 25016`, Mme MARION, 376,91 €, 9 lignes ✓) ; DEMAILLE (`D26-15`, Mme DEMAILLE Marine, 5405,58 €, 15 lignes ✓). Contrôle des totaux réutilise `create_from_parsed` existant (préfixe `⚠ ÉCART` sur le chantier si écart, identique à l'import PDF). Si pas de référence → `gen_numero_devis()` auto à la confirmation. **olefile** ajouté aux dépendances (exploration OLE2, non utilisé en prod — la solution retenue est le scan bytes bruts). **225 tests OK + `check` vert.**

## Stack
- Django 6 · SQLite (dev) · PostgreSQL (prod OVH)
- Python 3.12 (prod) · Python 3.14 (dev Windows)
- OVH VPS (`vps-28c76530.vps.ovh.net`, IP 51.178.24.126) — Ubuntu 24.04, nginx, gunicorn systemd
- Gunicorn · WhiteNoise · Django Admin

## Démarrage rapide (dev Windows)
```powershell
# Setup initial
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Lancer / migrer / tester / vérifier (utiliser le python du venv)
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py runserver      # http://127.0.0.1:8000/
venv\Scripts\python manage.py test core      # 151 tests (core/tests.py)
venv\Scripts\python manage.py check
```
- Sans `DATABASE_URL`, la base est `db.sqlite3` (locale). Connexion via `/login/`.
- Les tests de contrôle d'accès vivent dans `core/tests.py`.

## Déploiement (OVH VPS)
- Remote git : GitHub `pekkip/lec-henn`. Prod : `https://vps-28c76530.vps.ovh.net`
  (domaine définitif `gestioncbb.compagnonsbatisseurs.eu` en attente DNS IT national).
- **`git push origin main` ne déclenche PAS de déploiement automatique.** Pour déployer,
  SSH sur le VPS et lancer `deploy.sh` :
  ```bash
  cd /srv/cbbretagne/app && ./deploy.sh
  ```
  `deploy.sh` fait : `git pull` → `pip install -r requirements.txt` → `migrate` →
  `collectstatic --noinput` → `sudo systemctl restart cbbretagne`.
- Variables d'env prod (`.env` sur le VPS, jamais commité) : `SECRET_KEY`, `DEBUG=False`,
  `ALLOWED_HOSTS`, `DATABASE_URL` (PostgreSQL local), `CSRF_TRUSTED_ORIGINS`, `SITE_URL`,
  `BREVO_API_KEY`.
- `.gitignore` présent à la racine : `venv/`, `__pycache__/`, `*.pyc`,
  `db.sqlite3`, `staticfiles/`, `media/`, `.env`, `core/Corrections*/`.
- Runbook complet : `DEPLOY_OVH.md`.

## Architecture
```
cb-bretagne/
├── cbretagne/
│   ├── settings.py
│   └── urls.py (inclut core.urls)
└── core/
    ├── models.py
    ├── views.py               — vues générales (devis, factures, compta, clients, utilisateurs…)
    ├── views_planning.py      — vues du module Planning & Émargement / Insertion
    ├── planning_utils.py      — helpers calendaires planning (jours ouvrés, fériés, grilles, recalcul durées)
    ├── urls.py
    ├── permissions.py
    ├── totaux.py              — calcul des totaux de devis en mémoire (anti N+1), partagé views/dashboard
    ├── dashboard_widgets.py   — registre + fournisseurs de données des widgets du dashboard
    ├── management/commands/seed_demo.py  — jeu de démo (9 équipes, idempotent, marqué SEED_DEMO)
    ├── management/commands/seed_production_demo.py  — démo production Insertion 35 (6 équipes, Jan–Mai 2026, marqué DEMO35)
    ├── admin.py
    ├── tests.py               — 151 tests (accès, clients, biblio, compta, dashboard, perf, planning, feuilles, événements)
    ├── migrations/
    ├── static/core/
    │   ├── app.css            — composants partagés (badges/boutons/tableaux/modales/charte)
    │   └── app.js             — socle JS partagé : TreeHelpers (calc/nids/fmtV), apiPost, debounce
    └── templates/core/
        ├── base.html
        ├── _pagination.html        — contrôles de pagination réutilisables (page_obj + base_qs)
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
        ├── clients.html           — liste + filtres (type) + modales + carnet contacts
        ├── facture_compta_list.html   — liste outil compta (structure/appel + avoirs liés)
        ├── facture_compta_form.html   — création facture compta (client + contact optionnel)
        ├── facture_compta_detail.html — éditeur 2 niveaux (titres+forfaits, glisser-déposer)
        ├── avoirs_list.html       — liste de tous les avoirs (Principal)
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
- `ProfilUtilisateur` (OneToOne User) — role, taux_mo_defaut, saisie_ht, conditions_devis, conditions_facture, coordonnees_cb, **dashboard_config** (JSONField — disposition du tableau de bord)
- `Client` — nom, **type_client** (particulier/association/bailleur/collectivite/autre), contact, email, telephone, adresse (rue), code_postal, ville, created_by (FK User)
- `ContactClient` — **carnet de contacts optionnel** (1..n par client) : client FK, service, nom, fonction, email, telephone. Pour distinguer plusieurs services au sein d'une structure (ex. collectivité).
- `Devis` — reference, client, chantier, equipe, taux_mo, status, conditions_devis, coordonnees_cb, **zone_financement** (bool), created_by
- `LigneDevis` — arbre imbriqué (TITRE/S/C/OUV/MO/MAT/FMO/FMAT/FIN), parent FK, **aide FK nullable**
- `BibliothèqueAides` — bibliothèque partagée (tous) : description, type_ligne (FMO/FMAT/FIN), montant_defaut, unite, organisme, created_by
- `Facture` — **devis FK nullable**, type_doc (facture/acompte/appel/**structure**/avoir), status (draft/validated/sent/paid/cancelled), numero (unique), montant, **client FK** (direct, compta), **contact_client FK**, **coordonnees_cb** (snapshot), **facture_origine FK** (avoir→facture créditée), conditions_facture, created_by
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
/                           dashboard (tableau de bord à widgets)
/tableau-de-bord/config/    dashboard_save (POST JSON — ordre/visibilité/portée des widgets)
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

# OUTILS COMPTA (admin/comptable — peut_acceder_compta)
/avoirs/                          avoirs_list (Principal — tous les avoirs)
/factures/<pk>/avoir/             avoir_create (POST — depuis facture validée, qtés inversées)
/compta/structures/               factures_compta_list {type_doc:structure}
/compta/structures/nouvelle/      facture_compta_create
/compta/appels/                   factures_compta_list {type_doc:appel}
/compta/appels/nouvelle/          facture_compta_create
/compta/factures/<pk>/            facture_compta_detail (éditeur 2 niveaux)
/compta/factures/<pk>/valider/    facture_compta_valider (POST — gen_numero_facture)
/compta/factures/<pk>/statut/     facture_compta_status (POST)
/compta/factures/<pk>/supprimer/  facture_compta_delete (POST — brouillon)
/compta/factures/<pk>/dupliquer/  facture_compta_duplicate (POST — nouveau brouillon)
/compta/factures/<pk>/lignes/[sauvegarder/]   lignes_compta_get / lignes_compta_save
/compta/clients/<pk>/contacts/    client_contacts_get (GET JSON)
/compta/contacts/creation-rapide/ contact_client_create (POST JSON)
/compta/contacts/<pk>/supprimer/  contact_client_delete (POST — admin)

# MODULE INSERTION (peut_acceder_planning)
/planning/                                  planning_mois (calendrier mensuel)
/planning/emargement/                       emargement_view (grille hebdo)
/planning/equipiers/                        equipiers_list
/planning/feuilles/                         feuilles_liste (liste fiches mensuelles)
/planning/feuilles/<eq_pk>/<annee>/<mois>/  presence_feuille (fiche individuelle)
/planning/feuilles/note/                    fiche_note_save (POST JSON — chantier/obs)
/planning/feuilles/presence/               fiche_presence_save (POST JSON — M/A)
/insertion/aide/                           aide_insertion_view (manuel insertion)
```

⚠️ **Aperçu réutilisé** : les factures compta utilisent la route existante
`/factures/<pk>/apercu/` (`facture_apercu` généralisée pour `devis=None`).

⚠️ Les noms d'URLs sont un mélange français/anglais à homogénéiser (statut/status, supprimer/delete).

## Charte graphique CB Bretagne
- Prune : #67123A (couleur principale)
- Teal : #00AA8D (accent)
- Amber : #F7A600 (accent secondaire — usage limité)
- Police : Montserrat (Google Fonts)
- Logo : embarqué en base64 dans devis_pdf.html et facture_apercu.html
- Logo horizontal pour en-tête documents, vertical pour usage courant

---

## Documents de conception

Décisions ergonomiques & esthétiques et maquettes de référence (la charte couleur/typo est
résumée dans le **RAPPEL DESIGN** en tête de fichier).

- **Décisions ergonomiques (verrouillées)** — `mockups/HANDOFF*.md` :
  - [`HANDOFF - Refonte UI.md`](<mockups/HANDOFF - Refonte UI.md>) — gabarit listes + éditeurs :
    palette 14 couleurs par auteur, `.tbl-author` (zébrage, en-tête collant, navigation
    ligne / référence liée), `.ctx-bar` / `.toolzone`, onglets prune.
  - [`HANDOFF - Refonte des listes.md`](<mockups/HANDOFF - Refonte des listes.md>)
  - [`HANDOFF - Refonte éditeurs.md`](<mockups/HANDOFF - Refonte éditeurs.md>)
  - [`HANDOFF - Refonte planning & insertion.md`](<mockups/HANDOFF - Refonte planning & insertion.md>)
- **Maquettes (source de vérité visuelle)** — `mockups/*.dc.html` : Listes harmonisées,
  Modales harmonisées, Planning - refonte, Émargement - refonte, Feuille de présence,
  Éditeur devis (fenêtre complète / organisation), Éditeur facture (fenêtre complète / Après).
- **Runbooks / plans (terminés, valeur de référence)** :
  - [`docs/plan_ameliorations.md`](docs/plan_ameliorations.md) — refactor code/UI, phases 1-5
    ✅ (sessions 43-47).
  - [`REFONTE_PLANNING.md`](REFONTE_PLANNING.md) — refonte planning, phases 1-4 ✅ (sessions 58-64).
  - [`DEPLOY_OVH.md`](DEPLOY_OVH.md) — déploiement OVH (runbook).

---

## Prochaines étapes

1. **Valider l'éditeur de facture avec Frédérick et Yann** — colonnes MO/MTx séparées ou prix unique
2. **Valider la logique conditions** devis/facture (niveau service vs utilisateur) avec l'équipe
3. ~~**Champ Client** — adresse structurée (rue / CP / ville)~~ ✅ fait session 13
4. **Changement de mot de passe depuis le profil** (attendre SMTP M365)
5. **Statut devis "envoyé au client"** ✅ select dans la topbar (session 14), mais pas encore affiché dans la liste des devis
6. ~~**Dashboard — section suivi financements**~~ ✅ fait session 21 : widget `chart_financements`
   (`LigneDevis.filter(aide__isnull=False, devis__status='accepted')`, regroupé par organisme).
   Tableau de bord entièrement refondu en widgets personnalisables (session 21).
7. **PDF WeasyPrint — Phase 3**
8. **🔴 Emails — correctif durable : authentification DNS du domaine dans Brevo, à faire par
   l'IT nationale** (SPF `include:spf.brevo.com` + DKIM Brevo + TXT de vérif sur
   `compagnonsbatisseurs.eu`). Tant que ce n'est pas fait, les invitations vers
   `@compagnonsbatisseurs.eu` rebondissent (soft bounce « Access denied ») ; contournement =
   message d'invitation affiché à l'écran à la création (session 20). Voir § Infra.
   **Mise à jour 13/06/2026 : remplacé par la demande IT unique Graph (`Mail.Send`) —
   voir § Infra, ne pas faire la demande DNS Brevo séparément.**

---

## Fonctionnalités temporaires beta — À RETIRER avant version finale

> Code ajouté uniquement pour faciliter la phase de test. **Ne pas laisser en prod.**

### Export Excel (`devis_export_excel`) — ajouté session 18

Pour supprimer proprement :

1. **`requirements.txt`** — retirer la ligne `openpyxl`
2. **`core/views.py`** — retirer `import io` (ligne 1) + supprimer la fonction
   `devis_export_excel` (chercher `def devis_export_excel` — environ 200 lignes
   jusqu'au prochain `@login_required`)
3. **`core/urls.py`** — retirer la ligne :
   `path('devis/<int:pk>/excel/', views.devis_export_excel, name='devis-excel'),`
4. **`core/templates/core/devis_detail.html`** — retirer la ligne :
   `<a href="{% url 'core:devis-excel' devis.pk %}" class="tab">...</a>`
   (dans la barre d'onglets, après "Vue client")

---

## Dette technique (SOURCE UNIQUE)

> Liste **vivante** de la dette ouverte. Les logs de session (au-dessus) sont
> figés — ne pas y dupliquer de TODO : tout item à reprendre vit **ici**.

### Sécurité / config
- ✅ **Durcissement config** — réglé session 17 : `DEBUG` défaut déjà `False` (était
  noté à tort comme True) ; `SECRET_KEY` lève `ImproperlyConfigured` si absente et
  `DATABASE_URL` présente (= prod Railway) ; cookies secure + `SECURE_SSL_REDIRECT`
  activés uniquement si `DATABASE_URL` (même garde-fou). HSTS **différé** post-beta.
- ✅ **OTP bypass** — ✅ sécurisé session 17 : gate `peut_modifier_facture` sur les deux
  endpoints ; code posé en session uniquement après envoi réussi. Rôle : équipe du devis
  (à restreindre admin/comptable en Phase 4 si besoin).
- **Bibliothèque Aides — droits** — `aide_delete`/`aides_api_save` ouverts à tout
  utilisateur connecté (**BETA assumé**). Restreindre (admin/responsable ?) au passage
  hébergement définitif — Phase 4.
- **Accès OUTILS COMPTA** — `peut_acceder_compta` = admin/comptable (création + lecture des
  factures compta). À étendre à 'responsable' si le besoin se confirme (1 ligne dans
  `permissions.py`). Suppression de contact (`contact_client_delete`) = admin uniquement.
- **Avoir — rôle de création** — `avoir_create` gate `peut_modifier_facture(source)` (équipe
  du devis pour le chantier, compta pour les factures compta). À restreindre éventuellement
  (admin/comptable only) en Phase 4 selon les retours.

### Données / logique métier
- **Numérotation (`gen_numero_sequence`)** — ✅ fusion faite session 47 (Phase 5) :
  `gen_reference` + `gen_numero_facture` partageaient la mécanique « scan champ →
  suffixe après dernier `-` → max+1 → zfill(3) », désormais factorisée dans
  **`gen_numero_sequence(prefix, model, field, queryset=None)`**. `gen_reference`
  supprimée (branches FAC/AV mortes) ; devis appelle directement
  `gen_numero_sequence('DEV', Devis, 'reference')` ; `gen_numero_facture` conserve
  `NUMEROTATION_FACTURE` et son **découplage prefix/sequence** (scan par groupe de
  séquence via `queryset`, affichage par préfixe). **Race max+1 toujours présente**
  (dette ouverte — proba nulle à l'échelle beta). ⚠️ **Arbitrage à venir** : la
  stratégie de numérotation (séquences partagées vs séparées, format réglementaire)
  reste un **point d'incertitude** — la direction doit se renseigner sur les
  **aspects légaux** auprès du conseil de l'association avant de figer la règle. Tant
  que ce n'est pas tranché, on garde le découplage en place sans le réduire.
- **`total_facture()`** (models.py) — double comptage potentiel acompte + facture, à confirmer vs compta.
- **TVA** — "non applicable art. 293B CGI" à adapter selon le régime fiscal réel.
- ✅ **`LigneDevis.total_mo()` ignorait les lignes FMO** — les feuilles de type `FMO` (Forfait main d'œuvre) retournaient 0 au lieu de `quantite × cout_unitaire`. Corrigé session 25 : condition étendue à `type_ligne in ('MO', 'FMO')`. `total_mo_devis()` ajouté dans `totaux.py` (même pattern sans N+1, compte MO + FMO).

### Code / archi
- **Uniformisation CSS** (diagnostic 11/06/2026, session 36) — le socle existe (variables
  `:root` + composants partagés dans `base.html`, utilisés partout ; les 9 templates de
  listes n'ont aucun CSS local). La dérive réelle : **redéfinitions locales de composants
  génériques** — `.btn` recopié dans ~7 templates, badges réinventés par page
  (`utilisateurs_list` ×10, `feuilles_liste` ×4…), retouches `.card`/modales éparses.
  Le CSS spécifique (éditeur devis 331 l., timeline planning 167 l., fiche A4, aperçus)
  est légitime — ne pas y toucher. **Plan en petites passes, écrans stables d'abord**
  (pas de big-bang, ni avant la prod réelle) : ✅ **(1) badges + boutons** — fait 12/06/2026 :
  8 modificateurs couleur génériques (`b-gray/teal/prune/green/amber/red/blue/violet`) +
  statuts facture manquants (`b-fdraft/fvalidated/fcancelled/fbypass` — étaient des
  classes fantômes, badges transparents) + `btn-warning`/`btn-success` dans base.html ;
  7 templates nettoyés ; scroll ajouté sur tableau de bord insertion (piège flex-shrink :
  les cartes se compressaient au lieu de déborder) et utilisateurs (`page-body` + classes
  fantômes `page-header`/`btn-primary`/`alert` remplacées). ✅ **(2) tableaux de listes** —
  fait 12/06/2026 : `.eq-table` (feuilles) et `.ins-tbl` (×3, tableau de bord insertion)
  supprimées → style `table` standard de base.html partout ; classe `.scroll-y` remplace
  les 7 wrappers `style="flex:1;overflow-y:auto"` inline des listes. ✅ **(3) modales** —
  fait 12/06/2026 (session 39) : `.modal-lg`/`.modal-scroll` dans base.html, définitions
  locales et width inline supprimés (6 templates). ✅ **(4) incohérences de charte** —
  tranché 12/06/2026 (session 39) : prune `#6B1F3A` → `#67123A` partout (erreur corrigée) ;
  **Segoe UI conservée dans l'app** et **teal/amber app conservés** (choix actés — la charte
  stricte ne s'applique qu'aux documents clients, déjà conformes) ; + corrections de
  contraste (btn-teal, sidebar feuilles). ✅ **(5) CSS de base.html → fichier statique** —
  fait 12/06/2026 (session 40) : `core/static/core/app.css` (lien `{% static %}`) ; prod =
  `CompressedManifestStaticFilesStorage` (noms hashés, cache long, invalidation auto au
  déploiement) ; dev/tests = `StaticFilesStorage` + `WHITENOISE_USE_FINDERS` (pas de
  collectstatic à chaque retouche). Fix au passage : sélecteur `strong` global restauré en
  `.logo-txt strong` (préfixe perdu dans le commit 2de07cb — tous les `<strong>` de l'app
  étaient en blanc 12px depuis). **Uniformisation CSS terminée** sauf planning/émargement
  (encore en évolution fonctionnelle, attendre ~septembre 2026).
- **URLs à homogénéiser** — mélange français/anglais (statut/status, supprimer/delete). Choisir une convention et corriger partout.
- ✅ **Context processor `profil`** — réglé session 43 (Phase 1) : `profil_utilisateur(request)` ajouté dans `core/context_processors.py` et enregistré dans `settings.py` → `profil` injecté dans tous les templates, passage manuel retiré de 14 `render()` de `views.py`. Les `get_profil(request.user)` **utilisés dans la logique** des vues sont conservés (le context processor ne couvre que le template).
- ✅ **Modèle `BibliothèqueAides` → `BibliothequeAides`** — réglé : nom de classe renommé en
  ASCII (accent retiré, fragile pour imports/outils/introspection). Migration `RenameModel`
  `0026_rename_bibliothequeaides` (table `core_bibliothèqueaides` → `core_bibliothequeaides`,
  données de test uniquement, sans risque). Références mises à jour : `models.py` (classe + FK
  string), `views.py`, `tests.py`, `seed_demo.py`. 158 tests OK.
- ✅ **Auditer les templates** — vérifié session 36 (11/06/2026) : aucun `{{ f.reference }}` parasite restant dans `core/templates/`.
- **Calcul des totaux dupliqué (côté Python)** — le parcours d'arbre du total existe à
  **deux endroits** : `core/totaux.py` (version **en mémoire**, anti N+1, utilisée par les
  **listes ET le dashboard** via un import partagé) et `models.py` `LigneDevis.total()` /
  `Devis.total_brut()` (version **une requête par nœud**, conservée pour l'affichage d'**un
  seul** devis : `devis_detail`, réponse `lignes_save`, PDF…). C'est **volontaire** (inutile
  de précharger pour un objet unique), mais les deux doivent rester **sémantiquement
  identiques** — garde-fou : `test_totaux_identiques_aux_methodes_modele` (égalité stricte).
  Consolidation Python possible (propreté seulement) : faire déléguer `models.py` à
  `totaux.py` en préchargeant l'arbre du devis courant → une seule implémentation. Non requis
  pour la perf.
- ✅ **Calcul des totaux dupliqué (côté JS)** — réglé session 45 (Phase 3) : `calcTotal/calcMO/
  calcMat` + `fmtV/assignNids/findNode/delFromTree` étaient copiés à l'identique dans
  `devis_detail.html` ET `bibliotheque.html`. Consolidés dans **`core/static/core/app.js`**
  (`TreeHelpers`), chargé par `base.html`. Commentaire de **parité** ajouté en tête d'app.js ET
  de `totaux.py` (le garde-fou serveur reste `test_totaux_identiques_aux_methodes_modele`).
  `facture_detail` (findNode sur `id`, fmtV avec ` €`) et `facture_compta_detail` (arbre 2
  niveaux, `_nid` entiers) gardent **volontairement** leurs helpers locaux (sémantique
  différente). `apiPost(url,payload)` (POST JSON + CSRF) + `debounce` aussi dans app.js ;
  les saves JSON des 4 éditeurs (sauf compta, qui lit `resp.ok`) passent par `apiPost`.
- ✅ **`beforeunload` manquant + feedback de sauvegarde incohérent** — réglé session 46
  (Phase 4) : `devis_detail`, `facture_compta_detail`, `bibliotheque` n'avaient aucun garde-fou
  → fermeture d'onglet / rechargement / **Alt+←** = perte silencieuse des modifs de l'arbre.
  Suivi `dirty` + `installUnloadGuard` (app.js) ajoutés aux trois ; `facture_detail` (qui avait
  déjà le pattern) basculé sur le socle. Feedback unifié sur **un seul** toast (`showToast`
  dans app.js, `.toast` dans app.css) ; `eh-status`/`bib-status`/mutation de bouton supprimés.
  **Pas d'autosave** (décision actée — sauvegarde explicite, moins risqué sur l'éditeur de prix).

### Tests
- ✅ **Couverture session 14 manquante** — réglée : zone_financement (persistance) et
  `aide_delete` désormais couverts (`ZoneFinancementTests`, `AidesBibliothequeTests`).
  `aides_api_save` montant invalide : ✅ couvert session 17 (test `test_aides_api_save_montant_invalide_retourne_400`).
  Compta (factures structure/appel, avoirs, type_client) : ✅ couvert session 19 (`FactureComptaTests`).
  Tableau de bord (rendu, gating compta, config, portée) : ✅ couvert session 21 (`DashboardTests`).
  Perf listes + dashboard (totaux, pagination, requêtes bornées, anti N+1) : ✅ couvert
  session 23 (`ListesPerfTests`). Émargement → barre planning : ✅ couvert session 35
  (`PlanningBarreTests`, 23 tests). Feuilles de présence + événements : ✅ couvert
  session 36 (`JoursFeriesTests`, `BuildGrilleTests`, `JoursOuvresTests`,
  `EvenementSetsTests`, `EvenementEndpointTests`, `FeuillesPresenceTests` — 41 tests :
  fériés/Pâques, grille fiche mensuelle (régressions session 31, chevauchement d'année),
  jours ouvrés Lun–Jeu, recalcul en cascade `decale_chantier`/`travaille`,
  `fiche_presence_save`/`fiche_note_save`, permissions).
  ✅ **Endpoints planning/insertion restants** — couverts : resize multi-équipes avec
  redistribution du MO (`AffectationMoveTests`), tableau de bord insertion — totaux MO/mat
  via `mo_mat_lignes` + filtres équipe/période + gating (`InsertionDashboardTests`),
  `vendredi_toggle` (`VendrediToggleTests`), `tranche_creer` (`TrancheCreerTests`).
  **185 tests** au total.

### Performance
- ✅ **Listes (devis/factures/compta/avoirs)** — réglé session 23 : N+1 du calcul des
  totaux supprimé (`prefetch_related` + `attacher_totaux_devis` en mémoire) + pagination
  50/page sur les 4 listes. ~milliers de requêtes → ~10.
- ✅ **Dashboard** — réglé session 23 : les widgets CA / reste à facturer / CA mensuel /
  top clients / financements sommaient `total_brut()`/`reste_a_facturer()`/`ligne.total()`
  sur tous les devis acceptés (N+1). Migré sur `core/totaux.py` (calcul mémoire + prefetch).
  Nombre de requêtes désormais **constant** (testé). Les sommes restent en Python (total
  d'arbre non agrégeable en SQL) mais sans requête par nœud ; dénormalisation = option Phase 3
  seulement si le volume l'exige.

### Fonctionnel (à prévoir)

> Contexte (11/06/2026) : uniquement des données de test dans l'outil — pas de prod réelle
> avant l'hébergement définitif, et la phase de test se prolongera probablement jusqu'en
> septembre 2026. Les items ci-dessous sont à arbitrer avant implémentation.

- ✅ **`date.today()` → `timezone.localdate()`** — réglé session 36 : 12 occurrences
  remplacées dans le code applicatif (views ×6, views_planning ×5, dashboard_widgets ×1).
  Railway tourne en UTC : entre minuit et 2 h (heure de Paris), « aujourd'hui » pointait
  sur la veille. `tests.py` et `seed_demo.py` conservent `date.today()` (setup de données
  et commande manuelle — sans enjeu).
- **🔶 Import suivi prod 2026 — barre planning & finalisation** (session 48, EN PAUSE) :
  la commande `import_planning_xlsx` est livrée et validée en local (49 chantiers,
  10 factures, 2109 présences), **non commitée**. Deux chantiers ouverts :
  1. **Barre planning « % consommé »** : intérim en place (jours réalisés / plage
     d'affectation) dans `views_planning.py` + `planning.html` → corrige le 0 % mais ne
     montre **pas les dépassements** (la plage = les jours émargés) et compte en **dates
     distinctes** alors que le tableur compte en **jours-équipe fractionnaires**. Cible
     visée : `réalisé team-days (créneaux/(2N)) ÷ jours facturables prévus` (col G du
     tableur → `Affectation.duree_jours`), **sans plafond** (dépassement affiché tel quel,
     ex. 115 % ; `pct_bar=min(pct,120)` + classe `over`). **Décision à prendre** : garder
     l'intérim ou revenir au calcul d'origine `heures_conso/heures_budget`.
  2. **Données source insuffisantes** : le xlsx actuel ne permet pas de dériver le budget
     prévu (MO/Matx & jours facturables) de façon fiable. **L'utilisateur restructure le
     fichier** pour y intégrer, par chantier, la facture correspondante (MO & Matx prévus).
     Reprendre l'import + la barre une fois le fichier finalisé (même structure, rempli
     jusqu'à fin juin). Rappel : pour la **prod**, purger d'abord devis/factures
     `created_by ∈ {admin, pekkip}` avant d'importer.
- **Audit des présences** — aucun `add_audit` dans `views_planning.py` alors que les
  présences alimentent la paie (contrôles FSE possibles). Tracer au minimum les
  modifications rétroactives. À coupler avec le chantier `ClotureMois` ci-dessous.
- ✅ **`planning_mois` / `emargement_view` chargeaient tous les devis acceptés** (avec
  lignes prefetch) à chaque affichage — réglé session 36 : `devis_mo_json` restreint aux
  devis affichés sur la grille ; liste complète + MO planifié + tranches servis à la
  demande par `GET /planning/wizard-data/` (`planning_wizard_data`), appelé à l'ouverture
  de la modal Affecter (cache JS, page rechargée après chaque création). Les cartes de
  l'étape 1 du wizard sont construites côté client. Requête `panel_equipes` dupliquée
  supprimée dans `emargement_view`.
- **Sauvegarde / conservation réglementaire** — les justificatifs FSE doivent rester
  disponibles plusieurs années (contrôles a posteriori). Définir la stratégie de backup
  (dump périodique, export des présences par mois clôturé) au passage hébergement OVH.
- ✅ **`ClotureMois` branché** — réglé session 36. Verrou serveur dans les **trois**
  endpoints d'écriture (`presence_save`, `fiche_presence_save`, `pret_save` création ET
  suppression — la suppression d'un prêt efface des présences). Règle : le verrou suit
  l'**équipe maison** de l'équipier (sa fiche est partie à la RH). Endpoint
  `POST /planning/feuilles/cloture/` (`cloture_toggle`) : **l'encadrant clôt et
  déverrouille** (choix acté ; `est_encadrant` couvre aussi admin/responsable/rh →
  la RH peut déverrouiller → corriger sur la fiche → re-clôturer, conforme au circuit
  papier). **FicheNote non verrouillée** (présences seulement — choix acté). UI :
  bouton Clôturer/Déverrouiller + badge dans `feuilles_liste` ; bannière + inputs
  readonly sur la fiche (y compris jours ambrés d'un mois précédent clôturé) ; cellules
  grisées dans l'émargement + alert si le serveur refuse. 9 tests `ClotureMoisTests`.
- **Export présences → logiciel RH** — à prévoir : les feuilles imprimées/signées
  partent à la RH pour la paie, et les données de présence devront être exportées vers
  le logiciel RH. **Format d'échange pas encore connu** (info 11/06/2026) — attendre la
  spec avant d'implémenter.
- **Bouton « Imprimer toutes les fiches » inactif** — le lien passe `?imprimer=1` mais
  `feuilles_liste` ne lit jamais ce paramètre (le bouton recharge la liste). À
  implémenter : page imprimable regroupant les fiches de tous les équipiers de l'équipe
  (une page A4 paysage par fiche) + **clôture automatique du mois au déclenchement de
  l'impression** (acté 11/06/2026 — l'impression matérialise la remise à la RH).
  ⚠️ Le manuel `/insertion/aide/` documente déjà ce bouton comme fonctionnel — corriger
  le manuel ou livrer la fonction.
- **Export PDF de tous les documents** (priorité devis/factures, puis fiches) — **acté
  11/06/2026 : chantier reporté à la mise en place du serveur OVH** (prévue semaine du
  15/06/2026) — volume persistant pour les snapshots + libs système via apt. Plan retenu :
  (1) WeasyPrint sur OVH (devis_pdf.html / facture_apercu.html sont rendus serveur, sans
  JS — cas idéal) ; (2) endpoint `devis/<pk>/pdf/telecharger/` + passe CSS paged media
  (`@page`, Montserrat en fichier local, masquer la barre de boutons) ; (3) idem facture ;
  (4) snapshot au passage « envoyé » + pièce jointe email. ⚠️ La fiche de présence remplit
  ses cases en JS → rendre les valeurs côté serveur avant de la passer à WeasyPrint.
- ~~**Dépôt SharePoint via Microsoft Graph — factures + fiches de présence**~~ **(abandonné 28/06/2026)** :
  trop complexe à maintenir. Remplacé par export PDF manuel + rangement dans le répertoire SharePoint
  approprié par l'utilisateur. La permission `Sites.Selected` est retirée de la demande IT.
- **Annexes au devis (croquis, fiches techniques, plans)** (spec actée 13/06/2026) :
  nouveau modèle `AnnexeDevis` (FK devis, FileField, titre, created_by, created_at) +
  upload/liste/suppression dans l'éditeur de devis (droits = `peut_modifier_devis`).
  **Formats acceptés : images (JPG/PNG) et PDF uniquement.** **Intégrées au PDF client** :
  images = pages d'annexe ajoutées en fin de devis (WeasyPrint), PDF joints = fusion via
  `pypdf` après génération. **Dépend de : OVH (volume persistant `media/` — Railway perd
  les uploads au redéploiement, cf. session 12 logo) puis WeasyPrint.** Les annexes
  suivront aussi le dépôt SharePoint (même pipeline que les factures).
- **Sauts de page manuels dans l'éditeur de devis** — permettre d'insérer un saut de page
  entre deux lignes (ex. type de ligne `SAUT_PAGE`, ignoré dans les totaux, rendu en
  `page-break-before: always` dans le PDF WeasyPrint). À faire après stabilisation de l'export PDF.
- **Snapshot PDF** — case "marquer comme envoyé" + mécanisme de dégel.
- **Barre de progression par titre** — affiche le total des factures précédentes, pas le montant par titre.
- **Restriction email @compagnonsbatisseurs.eu à la création d'utilisateur** — validation
  commentée dans `views.py` (`utilisateur_create`, TODO Phase 4). Décommenter avant
  passage en hébergement définitif.

### Infra
- ✅ ~~**SMTP Microsoft 365**~~ — abandonné (Railway bloque les ports SMTP). **Brevo HTTP API** en prod (`django-anymail[brevo]`, variable `BREVO_API_KEY`). M365 SMTP uniquement en local.
- ⚠️ **Délivrance email vers @compagnonsbatisseurs.eu — bloquée (diag. session 20)** :
  la clé `BREVO_API_KEY` est OK (Brevo accepte les envois, code 2xx) mais les mails
  vers les adresses internes `@compagnonsbatisseurs.eu` **rebondissent** en *soft bounce
  « Access denied »*. Cause : on envoie **depuis** `@compagnonsbatisseurs.eu` **via Brevo**,
  or Brevo n'est pas autorisé dans le DNS du domaine → le **Microsoft 365 de l'association
  rejette comme usurpation** (SPF/DKIM/DMARC non alignés). **🔴 Correctif durable = authentifier
  le domaine `compagnonsbatisseurs.eu` dans Brevo** (DKIM + `include:spf.brevo.com` + TXT de
  vérif), **à faire par l'IT nationale** car le **DNS est géré par l'association nationale**
  (pas d'accès direct). Alternatives si l'IT ne peut/veut pas : (A) demander les
  enregistrements à l'IT nationale ; (B) envoyer depuis un domaine dédié qu'on contrôle
  (Reply-To `@compagnonsbatisseurs.eu`) ; (C) API Microsoft Graph (HTTPS, tenant M365).
  **Contournement actif (session 20)** : `utilisateur_create` affiche **toujours** le mot de
  passe temporaire à l'écran (communication manuelle), l'email reste best-effort.
  **Mise à jour 13/06/2026** : la demande DNS Brevo devient caduque si la demande Graph
  ci-dessous aboutit (`Mail.Send` remplace Brevo) — ne pas faire les deux demandes.
- **🔴 Demande IT nationale — app Entra ID / Microsoft Graph + DNS** (envoyée 28/06/2026,
  **en attente de réponse**) :
  1. App registration « CB Bretagne — outil devis/facturation » dans Entra ID
     (récupérer `tenant_id` + `client_id`).
  2. Permission **`Mail.Send`** (type Application) + **`ApplicationAccessPolicy`** limitée
     à la boîte `noreply@compagnonsbatisseurs.eu` — remplace Brevo, élimine le problème
     SPF/DKIM. ~~`Sites.Selected` retiré~~ (dépôt SharePoint abandonné).
  3. Authentification par **certificat** (durée 10 ans, pas de renouvellement à gérer).
     **Certificat généré sur le VPS (28/06/2026)** :
     - Clé publique (à envoyer à l'IT) : `/srv/cbbretagne/app/cbb_graph.crt`
     - Clé privée (secret, ne quitte pas le VPS) : `/etc/cbbretagne/cbb_graph.key` (chmod 600)
     - Commande : `openssl req -x509 -newkey rsa:2048 -days 3650 -nodes -subj "/CN=cbb-graph"`
  4. **(DNS)** Enregistrement **A** `gestioncbb.compagnonsbatisseurs.eu` → **51.178.24.126**
     + **AAAA** → **2001:41d0:367:4d7::1**. Certificat HTTPS géré côté VPS (Let's Encrypt).
     Mettre à jour `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` / `SITE_URL` dès DNS résolu.
  **Dès réception `tenant_id` + `client_id`** : câbler `msal` dans Django pour remplacer Brevo.
- ✅ **Migration Railway → OVH terminée** — runbook : `DEPLOY_OVH.md`.
  VPS opérationnel : Ubuntu 24.04, nginx, PostgreSQL local, gunicorn systemd, HTTPS Let's Encrypt
  sur `https://vps-28c76530.vps.ovh.net`. Railway coupé. **En attente** : DNS IT national
  (`gestioncbb.compagnonsbatisseurs.eu` → 51.178.24.126) + Entra ID Graph (`Mail.Send` — SharePoint abandonné).
  Dès DNS résolu : `certbot --nginx -d vps-28c76530.vps.ovh.net -d gestioncbb.…` + mise à jour `.env`.
- ✅ **Renommage équipes en prod** — fait session 27 : SORM→65-SORM, GORM→65-GORM, GOSM→61-GOSM, AQSM→58-AQSM, AQRM→AQRM A + AQRM B.
