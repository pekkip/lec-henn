# CB Bretagne — Notes de développement

> **Ce fichier est le journal de référence du projet.** Il doit suffire à reprendre
> le travail à froid (nouvelle machine, nouveau collègue) après un simple
> `git pull` + lecture. Tenir à jour à chaque session.

## Consignes de collaboration

- **Doute sur ce que l'utilisateur voit ou veut** → poser des questions ciblées plutôt que partir sur des hypothèses. Utiliser l'outil `AskUserQuestion` pour des questions à choix, ou poser une question directe dans le chat.
- **Ne pas improviser** sur l'apparence, le comportement ou les données côté navigateur sans avoir confirmé le problème exact (ex. : demander si les dates sont absentes ou décalées, quel élément manque de contraste, etc.).
- **Modifications de fichiers** : utiliser les outils natifs `Edit`/`Read`/`Write` directement.

**État du projet (13/06/2026 — session 41) :** **Pré-remplissage factures — bugs corrigés.** (1) **`ligne_devis_source_id` perdu à la sauvegarde** : `create_lignes` dans `lignes_facture_save` supprimait et recréait les lignes sans relire `ligne_devis_source_id` depuis le JSON du frontend — le lien vers le devis était effacé à chaque save, rendant le pré-remplissage aveugle pour les factures suivantes. Fix : `ligne_devis_source_id=item.get('ligne_devis_source_id')` ajouté dans `create_lignes`. (2) **TITRE mis à 0 pour facturation partielle** : un TITRE inclus dans une facture précédente (qty=1) était systématiquement réduit à 0, même si des lignes C/S enfants avaient encore du restant — rendant le total à 0 après save. Nouveau comportement : TITRE démarre à qty devis, recurse ses enfants, puis se replie à 0 seulement si `was_billed=True` ET `total()==0` (tous les C/S épuisés). (3) **OUV/MO/MAT remis à 0** : ces types sont structurels (prix unitaire, jamais modifiés par l'utilisateur) — ils conservent désormais toujours la qty devis (`_TYPES_STRUCTURELS = frozenset({'OUV', 'MO', 'MAT'})`). 4 commits `3fdaf60`, `f506d93` sur main. **156 tests** (+1 test facturation complète, +1 test facturation partielle).

**État du projet (12/06/2026 — session 40) :** **Uniformisation CSS passe 5 (finale)** : le bloc `<style>` de base.html (~160 lignes, composants partagés) est extrait vers **`core/static/core/app.css`**, chargé via `{% static %}`. Storage statique scindé : **prod** (Railway, `DATABASE_URL` + `DEBUG=False`) = `CompressedManifestStaticFilesStorage` (noms hashés → cache navigateur long, invalidé à chaque déploiement par le collectstatic du Procfile) ; **dev/tests** = `StaticFilesStorage` + `WHITENOISE_USE_FINDERS`/`AUTOREFRESH` (servi depuis `core/static/`, pas de collectstatic après une retouche CSS). **Fix régression `<strong>`** : le sélecteur `.logo-txt strong` avait perdu son préfixe dans le commit 2de07cb (très tôt dans le projet) → la règle s'appliquait à **tous** les `<strong>` de l'app (blanc, 12px, display:block) ; préfixe restauré dans app.css. **Fix bug TITRE à 0** : `LigneFacture.total()` ne vérifiait pas `self.quantite == 0` pour les TITRE → le montant sauvegardé comptait les sections exclues ; `filtrer_lignes` dans l'aperçu idem. **Pré-remplissage factures (proto)** : `calc_deja_par_source_detail` + `_agreger_deja` + `copier_lignes_devis_vers_facture` refactorisés pour pré-remplir les quantités restantes et afficher les refs des factures précédentes par TITRE. Vérifié : 155 tests OK. Le CSS spécifique des écrans reste dans les templates (`extra_css`) — planning/émargement à uniformiser ~septembre 2026.

**État du projet (12/06/2026 — session 39) :** **Uniformisation CSS passes 3+4** : **(3) modales** — `.modal-lg` (640px) et `.modal-scroll` (max-height 90vh) ajoutés dans base.html ; définitions locales `.modal-lg` supprimées (devis_form, facture_compta_form) ; tous les `style="width:…"` inline remplacés par des classes (`.modal-wizard`/`.modal-ev` dans planning, `.modal-pret`/`.modal-aff-em` dans émargement, `.modal-lg` dans devis_detail). **(4) charte + contraste** : prune corrigé `#6B1F3A` → `#67123A` partout (base.html `:root` + SVG logo, login, mot_de_passe_oublie) — décisions actées : **Segoe UI conservée dans l'app** (Montserrat = documents clients/aide uniquement), **teal/amber app conservés** (`#2BBFA4`/`#E8A020`, adaptation écran volontaire — la charte stricte ne s'applique qu'aux PDF clients, déjà conformes) ; contraste : `btn-teal` passe en fond `--teal-dk` (blanc lisible, hover `--teal`), sidebar feuilles de présence `.active` en `--teal-dk` (était `--teal` sur fond teal clair, illisible — signalement utilisateur). **Fix curseur éditeur devis/biblio** : cliquer dans une description déjà active place désormais le curseur à l'endroit cliqué (1er clic = tout sélectionner, clic suivant = placer le curseur). Cause racine : `.node-row` est `draggable="true"` → le navigateur traitait chaque mousedown comme un début de drag et ne plaçait jamais le curseur ; fix = `draggable` désactivé au mousedown sur le contenteditable, réactivé au blur (drag par poignée intact). Factures/compta déjà correctes (inputs natifs, pas de drag). Émargement/planning/fiche présence volontairement non touchés. **151 tests** (inchangé — CSS/JS only).

**État du projet (12/06/2026 — session 38) :** **Planning — navigation fluide** : fenêtre de **26 semaines** rendue d'un coup (−6/+20 autour de la cible `?debut=`), flèches / « Aujourd'hui » = **scroll client sans rechargement** (rechargement recentré seulement aux bords de la fenêtre — historique et planification lointaine restent accessibles), zoom −/+ via variables CSS `--ch`/`--cw` (remplace le sélecteur 4/8/12 sem., préférence en localStorage), **mini-calendrier popover** de saut au mois (esthétique du calendrier prêt équipier), position de scroll restaurée après les reloads inévitables (sessionStorage, en unités de semaine), **auto-scroll pendant le drag/resize** près des bords (cache de positions du DnD compensé par le delta de scroll), **carte devis au clic sur une barre** (réf, client, chantier, lieu, % consommé, lien « Ouvrir le devis »). Approche validée sur 2 mockups HTML jetables (`mockups/`, non commités). **Bibliothèque — groupes d'ouvrages** : un TITRE entier glissé du devis vers la biblio devient un **groupe** (flag `groupe: true` dans le JSON `Bibliotheque.lignes`, aucune migration) — affiché comme un seul article dans la sidebar (badge « groupe », nb d'éléments + total €) et **réinséré en bloc** dans un devis (taux MO du devis appliqué) ; les TITRE sans flag restent des **catégories** (biblios existantes inchangées) ; page Bibliothèque : badge/teinte teal, bouton « Groupe », édition comme une catégorie, rangeable dans une catégorie ; garde anti-drop du pseudo-groupe Financements. Manuels mis à jour : `/aide/` § 7 (groupes d'ouvrages), `/insertion/aide/` § 2 (nouvelle navigation planning). **151 tests** (+2 fenêtre planning, +2 round-trip biblio).

**État du projet (12/06/2026 — session 37) :** **Tests feuilles + événements** : 41 tests ajoutés (`JoursFeriesTests`, `BuildGrilleTests` — régressions session 31 + chevauchement d'année, `JoursOuvresTests`, `EvenementSetsTests`, `EvenementEndpointTests` — recalcul en cascade `decale_chantier`/`travaille`, `FeuillesPresenceTests`). **Clôture mensuelle branchée** (`ClotureMois`) : verrou serveur dans `presence_save`/`fiche_presence_save`/`pret_save` (création ET suppression), règle = équipe maison de l'équipier ; endpoint `POST /planning/feuilles/cloture/` (encadrant clôt et déverrouille ; RH passe `est_encadrant` → peut corriger puis re-clôturer, conforme au circuit papier→RH) ; FicheNote non verrouillée (choix acté) ; UI : bouton + badge (feuilles), bannière + inputs readonly (fiche, y compris jours ambrés), cellules grisées (émargement) — 9 tests. **Perf wizard planning** : `planning_mois`/`emargement_view` ne chargent plus tous les devis acceptés ; nouvel endpoint `GET /planning/wizard-data/` appelé à l'ouverture des modals (cartes construites en JS, cache page). **`timezone.localdate()`** remplace `date.today()` (12 occurrences — Railway tourne en UTC, « aujourd'hui » pointait sur la veille entre minuit et 2 h Paris). **Uniformisation CSS passes 1+2** : badges (8 modificateurs couleur + statuts facture `b-f*` qui étaient des classes fantômes → badges transparents corrigés) et boutons (`btn-warning`/`btn-success`) consolidés dans base.html ; style `table` unique (`.eq-table`/`.ins-tbl` supprimées) ; classe `.scroll-y` remplace 7 wrappers inline ; scroll réparé sur tableau de bord insertion (piège flex-shrink) et utilisateurs. **Tests accélérés** : hacheur MD5 sous `manage.py test` → suite 68 s → **3,2 s**. **147 tests** au total. Reporté/acté : export PDF → serveur OVH (semaine du 15/06, plan WeasyPrint § Dette) ; bouton « Imprimer toutes les fiches » à brancher + clôture auto à l'impression ; export présences → logiciel RH (format inconnu).

**État du projet (11/06/2026 — session 36) :** **Refactoring planning** : helpers calendaires (`_jours_feries`, `_build_grille`, `_count_working_days`, `_build_evenement_sets`, `_add_working_days`, `_half_col_creneau`, `_in_loan`, `_planning_date`, `_recalcul_durees_tranche`, `_TAUX_JOUR_PLANNING`) extraits dans **`core/planning_utils.py`** (aucune dépendance HTTP ; `dashboard_widgets._prod_data` importe désormais depuis ce module et plus depuis `views`). Toutes les vues planning/insertion (équipiers, planning mensuel, émargement, événements, affectations, prêts, feuilles de présence, tableau de bord insertion, aide insertion) déplacées dans **`core/views_planning.py`** (~1 620 lignes) ; `views.py` redescend à ~2 775 lignes. `urls.py` pointe les routes planning sur `views_planning`. **Corrections** : `mo_mat_lignes` déplacée dans `totaux.py` avec parcours d'arbre unique (l'inline `_mo_mat` de `insertion_dashboard` doublait la récursion à chaque niveau) ; `affectation_move` retourne 400 (et plus 500) si `equipe_id` non numérique ; fichier parasite `core/template` supprimé ; import mort `Q as _Q` supprimé. Déplacement de code pur : aucun changement de comportement, 95 tests OK.

**État du projet (11/06/2026 — session 35) :** **Planning — ligne mois** : ligne "Juin 2026" ajoutée au-dessus des numéros de semaine dans la timeline (`mois_hdr` calculé côté vue, CSS `.tl-mois-track`). **Émargement — ligne mois** : idem au-dessus des colonnes jours ; gestion du chevauchement de mois ("Juin – Juillet 2026"). **Navigation planning ±1 semaine** : les flèches avancent/reculent d'une semaine (était 4). **Resize multi-équipes** : redimensionner la barre d'une équipe recalcule le MO restant et ajuste la durée des autres équipes de la tranche en conséquence (allonger A → raccourcit B, raccourcir A → allonge B) ; mono-équipe = resize libre. **Tableau de bord insertion** (`/insertion/tableau-de-bord/`) : nouvelle page dédiée (7 widgets prod retirés du dashboard principal) avec barre de filtres période + équipes, 3 KPIs globaux, tableau par équipe (taux + barre), tableau par chantier, **liste des factures** (colonnes MO HT / Matériaux HT / Total HT + ligne de totaux en pied, filtrées par `date_creation` sur la même période ; calcul MO/MAT par parcours récursif des `LigneFacture` en mémoire, 1 requête pour toutes les factures). **Navigation sidebar** : lien "Tableau de bord" insertion placé en tête du groupe Insertion. **Tests** : 23 tests `PlanningBarreTests` couvrant le flux émargement → `heures_par_tranche` → `pct_consomme` (ORM, chantiers partagés, prêts inter-équipes, `presence_save`, `pret_save`). **Seed** : `seed_production_demo --clear` génère désormais des `LigneFacture` (FMO + FMAT) pour chaque facture demo.

**État du projet (09/06/2026 — session 34) :** **Fix sélecteur statut devis** : le `{% block topbar_actions %}` était défini dans `devis_detail.html` mais absent de `base.html` — le select de changement de statut n'était jamais rendu. Correction : ajout du bloc dans `base.html`. **Fix CSS options dropdown** : les `<option>` héritaient de `color:rgba(255,255,255,.88)` (texte blanc de la topbar) → ajout de `select.btn-ghost option{color:var(--gray);background:#fff}` dans `base.html`.

**État du projet (08/06/2026 — session 33) :** **Coller depuis Excel sur facture structure** : bouton "Coller depuis Excel" dans l'éditeur facture compta → chaque ligne Excel devient un forfait, dates détectées automatiquement, alignement monospace via U+00A0. **Calcul Tutorat** : outil dédié aux services civiques dans l'éditeur facture compta — coller la liste volontaires (Secteur optionnel, Nom, Prénom, Date début, Date fin), choisir trimestre/année/taux mensuel → calcul JOURS360 (méthode européenne 30j/mois), génère titre "Xe trimestre YYYY — SERVICES CIVIQUES" + ligne repère colonnes + un forfait/personne (qté=jours, unité=J, PU=taux/30). Détection auto colonne Secteur (code numérique) et Nom+Prénom séparés ou fusionnés. **Refs cliquables** : dans la liste factures compta et la liste factures travaux, la référence et l'objet sont désormais des liens directs vers la facture. Colonne "Objet" ajoutée à la liste factures travaux. **Deux zones financement dans le devis** : la zone financement unique est remplacée par deux zones indépendantes — "Aide travaux CBB" (type FIN, icône 🎁) et "Financements organismes" (type FINX, icône 🏦, violet). Chaque zone a sa propre catégorie dans la sidebar bibliothèque Aides. Migration `0025_devis_zone_financement_ext_finx` appliquée (`zone_financement_ext` BooleanField + type FINX dans LigneDevis et BibliothèqueAides).

**État du projet (08/06/2026 — session 32) :** en test beta. **Module Planning & Émargement**
opérationnel sur railway (sessions 25–27). Drag & drop planning corrigé et accéléré (session 28) :
bug navigation URL supprimé + `location.reload()` éliminé (mise à jour DOM côté client depuis réponse serveur).
**Feuilles de présence mensuelles livrées (session 31)** : grille calendrier ISO corrigée (4 bugs),
jours fériés légaux FR (code F) + ponts Pont→Récup (code R) sur fiche et émargement.
**Widgets Production livrés (session 32)** : 7 widgets (`requires_planning=True`) dans le dashboard
existant + barre de filtres partagée (période + équipes) + commande `seed_production_demo` (6 équipes
Insertion 35, Jan–Mai 2026). **PERF LISTES & DASHBOARD** (session 23) : même cause racine (N+1) —
`total_brut()`/`reste_a_facturer()`/`LigneDevis.total()` parcourent l'arbre des lignes en
frappant la base à chaque nœud. Sur les **listes** (devis) c'était aggravé par un 2ᵉ calcul
dans le template ; sur le **dashboard**, plusieurs widgets (CA, reste à facturer, CA mensuel,
top clients, financements) sommaient ces méthodes sur **tous** les devis acceptés. Corrigé :
logique de totaux factorisée dans **`core/totaux.py`** (calcul **en mémoire** depuis des
lignes préchargées) + `prefetch_related` partout → nombre de requêtes **constant** (ne croît
plus avec le volume). **Pagination** (50/page, helper `paginer` + partial `_pagination.html`)
ajoutée aux 4 listes (devis, factures, compta, avoirs). **72 tests.** **TABLEAU DE BORD PERSONNALISABLE** (session 21) : dashboard modulaire par
utilisateur (widgets KPI / listes / graphiques Chart.js / activité), réordonnables en
glisser-déposer, masquables, avec **portée par widget** (Tous / Mes données / Mon équipe) ;
widgets compta réservés admin/comptable ; sidebar **repliable** (icônes seules). Icônes :
Devis → calculatrice, Factures → billets, Appels → `ti-phone-ringing`, Aides → cadeau.
Bug factures récentes (incluait compta/avoirs) corrigé. **Colonne Auteur** (session 22)
ajoutée en 1ʳᵉ colonne sur toutes les listes (devis, factures, compta, avoirs — « Coupable »
pour les avoirs) + **filtre par auteur** sur les listes Devis et Factures.
**Commande `seed_demo`** : jeu de données de démo (9 équipes 35, chantiers cohérents,
financements réels) — idempotent, sûr, marqué `SEED_DEMO`. **Diag. emails** (session 20) : les invitations vers `@compagnonsbatisseurs.eu`
rebondissent (M365 rejette Brevo, DNS non authentifié — voir § Infra) ; contournement = le mot de
passe temporaire est **toujours** affiché à l'écran à la création (communication manuelle). **OUTILS COMPTA** ajoutés (session 19) : factures structure + appels de
convention (facturation directe sans devis, réservée admin/comptable) et **avoirs** pour
tous les types. Export Excel temporaire toujours présent pour la beta (voir § Fonctionnalités
temporaires beta — à retirer). Email via **Brevo** (HTTP API) : invitations, bypass OTP et reset mot de
passe fonctionnels. Page `/aide/` publique (manuel utilisateur HTML). Correctifs sécurité
session 17 appliqués : bypass OTP protégé, durcissement config prod, Decimal robuste,
reset MDP sûr. Items restants : voir § Dette technique.

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
venv\Scripts\python manage.py test core      # 151 tests (core/tests.py)
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

## Session 32 — 08/06/2026 — Production : widgets dashboard + seed Insertion 35 + barre de filtres

### Contexte
Objectif : visualiser la production des équipes Insertion 35 directement dans le dashboard existant (pas de nouvelle page), avec des données de démo réalistes et une barre de filtres partagée (période + équipes).

### Livré

**7 widgets Production** (`requires_planning=True`) dans le dashboard existant :
- `prod_kpi_montant` — Montant facturé (mois)
- `prod_kpi_j_realises` — Jours réalisés (mois)
- `prod_kpi_ratio` — €/j réalisé (mois)
- `prod_kpi_taux` — Taux de réalisation (mois)
- `prod_list_chantiers` — table Production par chantier (J.fact / J.réal / écart / montant / €/j / taux)
- `prod_list_depassements` — Chantiers en dépassement (top 5 par écart)
- `prod_chart_equipes` — barres Avancement par équipe

**Métriques clés (définitions métier) :**
- **Jours facturables** = jours de travail (lun–jeu) dans la plage d'affectation intersectée avec la période filtrée, par equipe/devis
- **Jours réalisés** = `Count('date', distinct=True)` sur les `Presence(code='')` de la période → nombre de journées-équipe avec au moins un présent (≠ nb présences ÷ 2)
- **Taux de réalisation** = jours_réalisés / jours_facturables (100 % = équipe présente tous les jours planifiés)
- **Montant facturé** = factures validées/envoyées/payées (`validated_at` dans la période)

**`_prod_data(ctx=None)`** — agrégation commune dans `dashboard_widgets.py` :
- Sans `ctx` → mois courant, toutes équipes insertion
- Avec `ctx = {debut, fin, equipe_ids}` → filtre appliqué
- Architecture : Presence → `values('affectation__tranche__devis_id', 'affectation__equipe_id').annotate(n=Count('date', distinct=True))`, Affectation (jours_facturables avec `_count_working_days`), Facture (montant)

**`widgets_for(user)`** étendu pour filtrer `requires_planning` (même pattern que `requires_compta`).

**Barre de filtres partagée** (GET form, au-dessus de la grille, visible si `has_prod` + `prod_equipes`) :
- Présélections période : 6 derniers mois + trimestres de l'année + année entière (construits server-side dans `_build_period_presets(today)`)
- Dates personnalisées : `<input type="date">` nommés `debut` / `fin`
- Multi-sélection équipes : checkboxes `name="eq"` + toggle "Toutes"
- État en URL uniquement (GET params `debut`, `fin`, `eq[]`) — pas de stockage serveur
- JS inline : `prodApplyPreset()` (auto-submit au choix preset), `prodToggleAll()`, `prodEqChange()`
- Réinitialisation : lien `?` (efface tous les GET params)

**Commande `seed_production_demo`** (`core/management/commands/seed_production_demo.py`) :
- 6 équipes : `55-AQRM A`, `55-AQRM B`, `58-AQSM`, `61-GOSM`, `65-GORM`, `65-SORM`
- 12 devis DEMO35 (2 par équipe), 12 affectations, ~8 000 présences, 11 factures
- Période : Jan–Mai 2026 ; `taux_ho = 47 €/h` (~330 €/j équipe 4 personnes)
- Avancement varié : 40 % à 130 % (dépassements + finitions rapides)
- Devis structurés : TITRE / C (composite) / S (sous-ouvrage) / MO / MAT / FMO / FMAT / F (forfaits)
- Montants : second œuvre 800–12 000 € MO (30–50 % du devis), maçonnerie 15 000–20 000 € MO (~60 %)
- **Marqueurs DEMO35** : `reference startswith 'DEMO35-'`, `notes = 'SEED_DEMO35'`, `chantier startswith '[Démo]'`
- **`--clear` ciblé** : supprime uniquement les données DEMO35 (Presence → Affectation → Facture → Devis via les marqueurs) — ne touche pas les données des collègues sur Railway

```powershell
# Sur Railway
railway run python manage.py seed_production_demo
railway run python manage.py seed_production_demo --clear
# En local
venv\Scripts\python manage.py seed_production_demo [--clear]
```

### Corrections importantes
- **Jours réalisés** : première implémentation utilisait `Count('pk') / 2` → corrigé en `Count('date', distinct=True)` (une journée-équipe = 1, peu importe le nombre d'équipiers présents)
- **`--clear` trop large** : première version supprimait toutes les présences des 6 équipes → corrigé pour cibler uniquement les données DEMO35
- **Dates factures** : `date_creation` et `created_at` ont `auto_now_add=True` — Django ignore la valeur passée au `create()`. Contournement : `Facture.objects.filter(pk=fac.pk).update(date_creation=..., created_at=...)` juste après la création

### Fichiers modifiés
- `core/dashboard_widgets.py` — 7 nouveaux widgets + `_prod_data(ctx)` + providers + `widgets_for` étendu + `widget_data(prod_context)` + `resolve_dashboard(prod_context)`
- `core/views.py` — `_build_period_presets(today)` ; `dashboard()` : parsing GET params, `prod_context`, `prod_equipes`, `has_prod`, `prod_presets`
- `core/templates/core/dashboard.html` — barre de filtres GET form + blocs de rendu `prod_chantiers` / `prod_depassements` / `prod_equipes`
- `core/management/commands/seed_production_demo.py` — nouveau fichier

---

## Session 31 — 07/06/2026 — Insertion : feuilles de présence mensuelles (FSE/CISP)

### Contexte
Les feuilles de présence mensuelles sont des documents réglementaires FSE/CISP que les ETIs remettent à la RH avant le 27 du mois pour la paie. Mise en page à reproduire fidèlement (obligation des financeurs). Objectif : saisir une fois (émargement hebdo) → tout se dérive.

### Livré
- **Fix `_build_grille`** (4 bugs corrigés) :
  - S31 (juillet) non éditable : logique `first_current_mon` ne gérait pas les mois démarrant sam/dim
  - Juin 29/30 (fiche juillet) et août 31 (fiche septembre) grisés au lieu d'ambre : `in_range` manquait `d < first`
  - Août S30 superflu : le 26 juillet est dimanche → `week26_mon = lun 20 juil` → S30 ajoutée inutilement → ajout de `start_prev` qui utilise la semaine du dernier jour ouvré du mois précédent si le 26 est sam/dim
  - CSS ambre par cellule plutôt que par bloc : `jour.is_prev` (flag au niveau jour) remplace `bloc.is_prev` dans le template
- **Jours fériés légaux FR** : nouvelle fonction `_jours_feries(annee)` (algorithme Grégorien anonyme pour Pâques). Lundi de Pentecôte **exclu** (journée de solidarité travaillée chez CB Bretagne). Code `F` pré-rempli sur la fiche (via `SPECIAL_MAP` JSON injecté en JS) et dans l'émargement (`special_code`)
- **Ponts** : Evenements type `journee_ferie` → code `R` sur fiche et émargement (même mécanisme que `F`, priorité sur F)
- **Renommage** : `('journee_ferie', 'Jour férié / pont')` → `('journee_ferie', 'Pont → Récup')` dans `models.py`
- **Fiche** : suppression des placeholders (heures par défaut n'apparaissent plus à l'écran) ; cases Émarg. Salarié/ETI hauteur 3× (22px → 66px) ; icônes sidebar swappées (émargement `ti-clipboard-list` ↔ feuilles de présence `ti-signature`)
- **`seed_demo`** : équipiers créés avec tous les champs contrat (`date_debut_contrat`, `date_fin_contrat`, `date_visite_medicale`, `recup_base_heures`, `recup_base_date`, `droit_conges_jours`) ; message de fin mis à jour (affiche le nombre d'équipiers)
- **Migration 0024** (`fichenote_equipe_nullable_presence`) :
  - `Presence.affectation` → nullable + `on_delete=SET_NULL` (fix bloquant : émargement sans chantier assigné)
  - `Equipe` + 4 champs : `nom_programme`, `heures_matin_defaut`, `heures_aprem_defaut`, `afficher_plie`
  - `ProfilUtilisateur.ROLE_CHOICES` + `('encadrant', 'Encadrant / ETI')`
  - Nouveau modèle `FicheNote(equipier, annee, mois, num_semaine, chantier_texte, observation_texte)` — override chantier/obs par semaine ISO
- **Fix `presence_save`** : accepte `affectation_id=null` + lookup automatique (active → dernière → None). Corrige le "dash" (cellules non éditables sans affectation)
- **Fix `emargement_view`** : presences filtrées par `equipier__equipe` (et non plus `affectation__equipe`) → tous les équipiers actifs affichés même sans chantier planifié. `away_set` exclut les presences sans affectation
- **`permissions.py`** : `est_encadrant` étendu à `rh` (RH peut modifier les fiches)
- **4 nouvelles vues** : `feuilles_liste`, `presence_feuille`, `fiche_presence_save`, `fiche_note_save`
- **4 nouvelles routes** : `planning/feuilles/`, `planning/feuilles/<eq_pk>/<annee>/<mois>/`, `.../note/`, `.../presence/`
- **Sidebar** : lien "Feuilles de présence" (icône `ti-clipboard-list`) dans section Insertion
- **Templates** : `feuilles_liste.html` (vue liste + badges ○/⏳/✓) + `presence_feuille.html` (fiche format A4 paysage, auto-save JS blur + debounce)

### Choix techniques
- **Pas de bouton Clôturer** : auto-save partout, cohérent avec l'émargement. Statut = comptage presences vs théorique
- **Chantier en tête** = `Equipe.nom_programme` (dénomination réglementaire), pas le nom du devis
- **Données contrat** (ligne équipier sur la fiche) : champs éditables manuels pour l'instant. Intégration outil externe de contrats = future évolution
- **Navigation** : émargement hebdo conservé + feuilles de présence mensuelles coexistent (même data Presence)
- **JSON injection** : `presence_map_json`, `note_map_json`, `chantier_json` passés au template pour pré-remplissage JS (Django templates ne supportent pas les lookups dict à clé calculée)

### Fichiers modifiés
- `core/models.py` — FicheNote, Presence.affectation nullable, Equipe +4 champs, ROLE_CHOICES +encadrant ; `journee_ferie` renommé "Pont → Récup"
- `core/migrations/0024_fichenote_equipe_nullable_presence.py` — nouvelle migration
- `core/permissions.py` — `est_encadrant` inclut `rh`
- `core/views.py` — `_jours_feries(annee)` (jours fériés légaux FR) ; `_build_grille` corrigé (4 bugs) ; 4 vues + helper `_get_chantier_semaine` ; fix `presence_save` + `emargement_view` ; `presence_feuille` + `emargement_view` : `special_code` / `SPECIAL_MAP`
- `core/urls.py` — 4 routes feuilles + route `insertion/aide/`
- `core/templates/core/base.html` — lien sidebar ; icônes émargement ↔ feuilles swappées
- `core/templates/core/feuilles_liste.html` — nouveau
- `core/templates/core/presence_feuille.html` — SPECIAL_MAP JS, `jour.is_prev` pour CSS, suppression placeholders
- `core/templates/core/emargement.html` — `special_code` (F/R), hauteur Émarg Salarié/ETI 3×
- `core/templates/core/aide_insertion.html` — section 5 "Feuilles de présence" ajoutée
- `core/management/commands/seed_demo.py` — champs contrat équipiers + message fin (+ nb équipiers)

### À faire (prochaine session)
- Renseigner `Equipe.nom_programme` pour chaque équipe en admin
- Tester la fiche avec des données réelles (équipiers démo avec `(D)` dans le nom)
- Vue Production (jours facturables/réalisés/écart)
- Intégration outil externe contrats (hors scope session 31)
- **Après migration hébergement définitif** : créer les Evenements "Pont → Récup" pour
  les lundis de Pentecôte (journée de solidarité, non férié chez CB Bretagne).
  Dans Django admin → Evenements → Ajouter :
  - Type : Pont → Récup
  - Libellé : Pentecôte (journée de solidarité)
  - Date début = Date fin : la date du lundi de Pentecôte de l'année
    (2026 : 25/05, 2027 : 14/06, 2028 : 05/06…)
  - Créneau : Journée
  - Équipes : laisser vide (= toutes équipes)
  La cellule apparaîtra alors en ambré avec le code R dans l'émargement et la fiche.

---

## Session 30 — 07/06/2026 — Insertion : manuel "Fonctions insertion"

### Livré
- **Page manuel Insertion** (`/insertion/aide/`) — page autonome (hors layout app) avec table des matières latérale, même style CSS que `aide.html` (Montserrat, prune, teal)
- **4 sections** : Accès et rôles, Planning (vue, wizard affecter, drag&drop, événements, prêt), Émargement (saisie, prêts), Équipiers
- **Lien "Fonctions insertion"** dans la section Insertion de la sidebar (visible uniquement pour `peut_acceder_planning`)

### Fichiers modifiés
- `core/urls.py` — route `insertion/aide/` → `aide-insertion`
- `core/views.py` — vue `aide_insertion_view`
- `core/templates/core/base.html` — lien sidebar dans le bloc Insertion
- `core/templates/core/aide_insertion.html` — nouveau template

---

## Session 29 — 07/06/2026 — Planning : modal affecter un chantier (wizard 4 étapes)

### Livré
- **Wizard "Affecter un chantier"** — remplace l'ancienne modal formulaire par un tunnel en 4 étapes : Chantier → Équipe → Durée → Date
  - Étape 1 : cartes devis filtrables (client, chantier, référence) + affichage MO total / restant + badge équipes déjà assignées
  - Étape 2 : cartes équipe avec estimation jours restants (MO restant / TAUX_JOUR / nb_équipiers) et nb chantiers en cours ; pré-sélection automatique si ouvert depuis une ligne d'équipe
  - Étape 3 : sélection/création de tranche + saisie durée ("Prendre tout" ou nb jours custom)
  - Étape 4 : mini-calendrier style prêt équipier (couleurs ambre, clic simple pour date de début, aperçu des chantiers existants de l'équipe en jaune)
- **Backend** : route `POST /planning/tranche/creer/` + vue `tranche_creer` ; `affectation_save` accepte `tranche_id` optionnel ; 4 nouvelles clés de contexte (`tranches_par_devis_json`, `mo_planifie_par_devis_json`, `aff_par_equipe_json`, `equipes_plan_json`)
- **`verbose_name_plural`** corrigé sur `TrancheDevis` ("Tranches de devis" au lieu de "Tranche de deviss")
- **Consignes de collaboration** ajoutées en tête de NOTES_DEV.md + mémoire persistante

### Fichiers modifiés
- `core/views.py` — contexte planning + `tranche_creer` + `affectation_save`
- `core/urls.py` — route `tranche-creer`
- `core/models.py` — `verbose_name_plural` TrancheDevis
- `core/templates/core/planning.html` — CSS + HTML modal + JS wizard (~600 lignes nettes)
- `NOTES_DEV.md` — consignes de collaboration + cette entrée

---

## Session 28 — 07/06/2026 — Planning : corrections drag & drop & performance

### Contexte
Deux problèmes signalés en prod (Railway) sur le drag & drop du planning :
navigation parasite vers `https://0.0.0.4/` lors du drop, et fluidité moindre qu'en local.

### Problèmes diagnostiqués

**1. Navigation parasite** — `dragstart` sur `.tl-bar` retournait tôt si `e.target !== bar`
(drag initié depuis un enfant : texte, barre de progression). `dragData` restait `null`
→ `dragover` n'appelait pas `e.preventDefault()` → le navigateur interprétait le
texte enfant comme URL. Un ID court comme `4` donne `0.0.0.4` en notation IP.

**2. Fluidité** — `cellAtX` appelait `getBoundingClientRect()` sur chaque cellule à
chaque `dragover` (~60×/s), forçant un recalcul de layout DOM. Sur Railway la grille
est plus grande (plus d'équipes + de données).

**3. Rechargement complet** — `location.reload()` après chaque déplacement chargeait la
page entière (requête HTTP + rendu serveur complet + init JS).

### Fichiers modifiés

- `core/templates/core/planning.html` :
  - Guard `dragstart` : remplace `if (e.target !== bar) return` par
    `if (e.target.closest('.bar-del')) { e.preventDefault(); return; }`
  - `buildCellPositionCache()` : snapshot des positions (left/right) de toutes les cellules
    par équipe au début du drag
  - `cellAtX` utilise le cache au lieu de `getBoundingClientRect` en boucle
  - Throttle `dragover` via `requestAnimationFrame` (highlight 1×/frame ;
    `e.preventDefault()` reste synchrone)
  - `applyBarUpdate(bar, newTrack, u)` : repositionne une barre depuis les données
    serveur (lit `grid-column` des cellules existantes via `data-date` + classe `.aprem`)
  - Handler `drop` : lit `d.updated[]` et appelle `applyBarUpdate` — plus de
    `location.reload()` pour le cas commun ; reload conservé si barre hors fenêtre ou erreur

- `core/views.py` :
  - `_aff_update_dict(aff)` : sérialise une affectation avec `nb_jours` calculé
    côté serveur (event-aware via `_build_evenement_sets` + `_count_working_days`)
  - `affectation_move` : retourne `{ok, updated: [...]}` au lieu de `{ok, recalculated: [pks]}`

### Décisions actées

- **Pas de mise à jour optimiste** — `applyBarUpdate` appelé uniquement après `200 OK`
  avec les données autorisataires du serveur.
- Reload de secours si la date cible est hors fenêtre visible (cellule introuvable dans le DOM).
- `pct_consomme` non mis à jour (nécessite comptage présences) — stale jusqu'au prochain rechargement.

---

## Session 27 — 07/06/2026 — Planning : prêt équipier, émargement polish

### Fichiers modifiés

- `core/models.py` — `Pret` : ajout `creneau_debut` / `creneau_fin` (choix matin/aprem)
- `core/migrations/0023_…` — migration des nouveaux champs Pret
- `core/views.py` :
  - `_in_loan(jour, creneau, pret)` : fonction module-level (sortie de la closure) pour
    calcul précis demi-journée
  - `CRENEAU_ORDER` : constante module-level (ordre matin < aprem)
  - `pret_away_map` : clé `(equipier_id, date_iso, creneau)` pour granularité demi-journée
  - `_build_cren_rows` : utilise `is_jour_off()` (event-aware) au lieu de
    `jour.weekday()==4` pour les vendredis
  - `pret_save` : enregistre `creneau_debut` / `creneau_fin`
  - `jours_info` : liste de dicts `{jour, label, events, is_off}` consommée par le template
  - Jours fériés (`type='journee_ferie'`) : exclus de `jours_off_force` (décalage chantier)
    mais affichés avec rayures vertes dans l'émargement
  - Fix suppression prêt : nettoie les présences de l'équipe hôte → supprime les rayures
    grises côté équipe maison
- `core/templates/core/emargement.html` :
  - Modal prêt : boutons Matin/Après-midi pour début et fin
  - En-têtes de colonnes : tags d'événements colorés par type (toutes les équipes)
  - Cellules jour férié : rayures vertes 135° + libellé, non marquées `is_off`
  - Drag-select pour la plage de prêt (calendrier hebdomadaire)
  - Préfill grisée sur cellule déjà pointée + validation prêt si déjà émargé
  - Affichage équipe hôte dans les journées de prêt côté équipe prêteuse

### Décisions actées

- Demi-journée précise sur le prêt : `creneau_debut`/`creneau_fin` sur le modèle `Pret`,
  clé composée `(equipier_id, date, creneau)` dans `pret_away_map`
- Jours fériés affichés mais non bloquants (`is_off=False`) — équipe peut pointer ce jour-là
- **Renommage équipes Railway (prod)** : SORM→65-SORM, GORM→65-GORM, GOSM→61-GOSM,
  AQSM→58-AQSM, AQRM→AQRM A + AQRM B (puis 55-AQRM A/B)

---

## Session 26 — 06–07/06/2026 — Planning : multi-équipes, événements, émargement

### Fichiers modifiés

- `core/views.py` :
  - `_recalcul_durees_tranche` : recalcule `date_fin` de toutes les affectations d'une
    tranche en cas de changement d'équipe ou de suppression (équipes multiples sur un même chantier)
  - `affectation_move` + `affectation_delete` : gate check doublon + appel `_recalcul_durees_tranche`
  - `_build_evenement_sets`, `_is_working_day`, `_count_working_days`, `_add_working_days` :
    helpers calcul jours ouvrés event-aware
  - `evenement_save`, `evenement_delete` : CRUD événements (formation/visite/réunion/férié/jour_sup/autre),
    recalcul des tranches affectées si `decale_chantier=True`
  - `emargement_view` : réécrit (tab colonne-majeur M-A par jour par équipier),
    valeurs par défaut grisées, total live, validation codes absence
    (C/R/M/AT/A/AJ/S/PMSMP/DE/DI/F)
- `core/templates/core/planning.html` :
  - Grille demi-journées (12 colonnes/semaine : 5j×2 demi-j + Sam + Dim)
  - Système événements : barres `ev-bar` (négatifs) + icônes `ven-ind` (positifs/vendredi)
  - Indicateur vendredi actif par équipe/affectation
  - Barres plus hautes (78px) avec référence devis, lieu du chantier, jours/% consommé
  - Indicateur divergence durée (`divergent` outline amber si écart > 1j)
  - Poignées resize gauche/droite
  - Multi-équipes : check doublon + flash des barres recalculées
  - Colonne aujourd'hui (teal pointillé)
  - Tri équipes par ordre puis nom
- `core/templates/core/emargement.html` :
  - Tab M-A-M-A-… par jour par équipier
  - Valeurs par défaut grisées (prefill depuis `presence_save`)
  - Total live et validation des codes absence

### Décisions actées

- **Multi-équipes sur une tranche** : une tranche peut avoir N affectations (N équipes). La
  durée est répartie proportionnellement à l'effectif cumulé.
- **Grille demi-journées** : 12 colonnes/semaine (Lun-Ven ×2 + Sa + Di), colonnes 13px/8px.
  `_half_col_creneau` calcule les positions côté serveur.
- **Événements** : `decale_chantier=True` déclenche un recalcul des durées affectées ;
  `travaille=True` active un jour normalement chômé (vendredi ou autre).

---

## Session 25 — 06/06/2026 — Planning & Émargement : implémentation initiale

### Contexte
Session 24 : maquettes validées, aucun code Django écrit. Session 25 : implémentation
complète du socle (modèles, migrations, vues CRUD de base, templates fonctionnels).

### Fichiers créés / modifiés (3 commits socle + nombreux correctifs DnD)

- `core/models.py` — nouveaux modèles :
  `Financeur`, `Equipier` (nom/prénom/équipe/matricule/contrat/dates/récup/congés),
  `TrancheDevis` (statut en_cours/termine/facture), `Affectation` (équipe/dates/créneau/épinglé),
  `Evenement` (type/libellé/creneau/travaille/decale_chantier),
  `Presence` (pointage équipier × demi-journée, codes absence),
  `ClotureMois` (verrou mensuel par équipe)
  `Equipe` : ajout `encadrant`, `nb_equipiers`, `module_planning`, `activite`
  `Service`/`ParametresAssociation` : ajout `module_planning`, `taux_jour_facturable`
- `core/migrations/0018–0022` — schémas + données planning
- `core/views.py` — bloc Planning :
  - `equipiers_list`, `equipier_save`, `equipier_toggle_actif`
  - `planning_mois` : timeline multi-semaines CSS Grid (12 colonnes/sem)
  - `emargement_view` : grille hebdomadaire (version initiale)
  - `affectation_save`, `affectation_move`, `affectation_delete`
  - `vendredi_toggle`, `presence_save`, `pret_save`
  - `_half_col_creneau` : calcul positions colonnes serveur
  - `peut_acceder_planning` / `est_encadrant` dans `permissions.py`
  - Calcul `date_fin` auto depuis lignes MO/FMO du devis + `nb_equipiers`
  - **Fix `LigneDevis.total_mo()`** : condition étendue à `type_ligne in ('MO', 'FMO')` ;
    `total_mo_devis()` ajouté dans `core/totaux.py` (même pattern sans N+1)
- `core/urls.py` — bloc `/planning/` (14 routes)
- `core/templates/core/base.html` — section sidebar Insertion
- `core/templates/core/planning.html` (ébauche) — grille timeline + DnD déplacer/supprimer
- `core/templates/core/emargement.html` (ébauche) — grille hebdo + modal prêt initial
- `core/templates/core/equipiers.html` — liste + gestion équipiers

### Décisions actées

- Semaine Lun-Jeu par défaut ; vendredi activable par affectation via bouton `+`
- `TAUX_JOUR = 82.5 h/j` (heures MO par jour-équipier, calcul durée affectation)
- Planning visible uniquement admin + encadrants (`peut_acceder_planning`)
- Modèle `Pret` créé dès cette session (sans créneaux — ajoutés session 27)
- `seed_demo` mis à jour pour créer des équipiers de démo

---

## Session 23 — 05/06/2026 — Performance listes & dashboard (N+1) & pagination

### Contexte
Remontée : la liste des devis met du temps à s'afficher dès ~60 devis (objectif :
plusieurs centaines à terme), **puis le dashboard aussi**. Diagnostic : ce n'est pas
le volume mais une **explosion du nombre de requêtes SQL** (même cause sur les deux).

### Diagnostic
- `devis_list` faisait `for d in qs: d.rtf = d.reste_a_facturer()`.
  `reste_a_facturer()` → `total_brut()` → `LigneDevis.total()` qui parcourt l'arbre des
  lignes **récursivement** en appelant `self.enfants.all()` **et** `enfants.exists()` à
  **chaque nœud** → des dizaines de requêtes par devis.
- Le template appelait en plus `{{ d.total_brut }}` → **2ᵉ** parcours complet de l'arbre.
- Bilan : ~100-150 requêtes **par devis**. 60 devis ≈ 6 000-9 000 requêtes ; 300 devis ≈
  30 000+ → page inutilisable.

### Fichiers modifiés — Listes
- **`core/totaux.py` (nouveau)** — source unique de la logique de totaux **en mémoire**,
  partagée entre `views.py` et `dashboard_widgets.py` (placée à part pour éviter l'import
  circulaire). Expose : `total_brut_devis(d)`, `total_facture_devis(d)`,
  `attacher_totaux_devis(iterable)` (attache `brut`/`rtf`), `totaux_lignes(qs)`
  (`{ligne_id: total}` pour un lot de lignes, sous-arbres chargés en 1 requête).
  Réplique exactement `LigneDevis.total()` / `Devis.total_brut()` / `total_facture()`.
- `core/views.py` :
  - **`paginer(request, queryset, par_page=50)`** (nouveau helper) — renvoie
    `(page_obj, base_qs)` ; `base_qs` = query string courante sans `page` (conserve les
    filtres dans les liens de pagination).
  - Importe `attacher_totaux_devis` depuis `totaux.py`.
  - `devis_list` — `prefetch_related('lignes','factures')` posé sur le **queryset final**
    (après filtres) ; filtre `q` réécrit avec `Q(...)|Q(...)` (au lieu de `qs.filter()|qs.filter()`
    qui pouvait perdre le prefetch) ; pagination ; totaux attachés à la page seulement.
  - `factures_list`, `factures_compta_list`, `avoirs_list` — pagination ajoutée
    (`montant` est un champ DB, pas de N+1 — pagination seule).
  - Import `from django.core.paginator import Paginator`.
- `core/templates/core/_pagination.html` (**nouveau**) — contrôles réutilisables
  (première/préc./suiv./dernière + compteur), attend `page_obj` + `base_qs`.
- `devis_list.html` — compteur `{{ page_obj.paginator.count }}`, `d.total_brut` → `d.brut`,
  include du partial. `factures_list.html` / `facture_compta_list.html` / `avoirs_list.html` —
  compteur via `paginator.count` + include du partial.
### Fichiers modifiés — Dashboard
- `core/dashboard_widgets.py` — providers réécrits pour utiliser `totaux.py` au lieu des
  méthodes modèle appelées en boucle :
  - `_kpi_ca` / `_kpi_reste_a_facturer` — `prefetch_related('lignes'[, 'factures'])` +
    `total_brut_devis` / `total_facture_devis` (sommait `total_brut()`/`reste_a_facturer()`
    sur **tous** les devis acceptés).
  - `_chart_ca_mensuel` / `_chart_top_clients` — `prefetch_related('lignes')` + `total_brut_devis`.
  - `_chart_financements` — `totaux_lignes(lignes)` (1 requête pour tous les sous-arbres) au
    lieu de `ligne.total()` par ligne.
  - `_list_devis_recents` — `prefetch_related('lignes','factures')` + `attacher_totaux_devis`.
- `core/templates/core/dashboard.html` — **`d.total_brut` → `d.brut`** dans le widget
  « Derniers devis » : le template rappelait la **méthode modèle** (re-parcours d'arbre avec
  requête par nœud) sur les 6 devis affichés. Corrigé en lisant l'attribut préchargé.

### Tests
- `core/tests.py` — classe **`ListesPerfTests`** : équivalence des totaux avec les méthodes
  du modèle, pagination (50/page + page 2), conservation des filtres dans `base_qs`,
  **requêtes bornées** sur la liste devis (chemin normal + filtre `q`), et **absence de N+1
  sur le dashboard** (`test_dashboard_pas_de_n_plus_un` : le nb de requêtes ne change pas en
  passant de 4 à 20 devis acceptés, tous widgets affichés). **52 tests au total.**

### Décisions actées
- **Calcul en mémoire** plutôt que dénormalisation d'un champ total (pas de migration, pas de
  risque de staleness en beta) ; la dénormalisation reste une option Phase 3 si besoin.
- **`core/totaux.py`** = source unique de la logique de totaux, pour éviter de redévelopper
  (et désynchroniser) le calcul d'arbre dans `views.py` ET `dashboard_widgets.py`.
- **Pagination 50/page** sur les 4 listes — borne le coût et le poids HTML quel que soit le volume.
- `Devis.total_brut()`/`reste_a_facturer()`/`LigneDevis.total()` **conservées** (utilisées
  ailleurs, ex. devis_detail, lignes_save) ; on ne les appelle simplement plus **en boucle**.

### Pièges rencontrés
- `qs.filter(a) | qs.filter(b)` (ancien filtre `q`) risquait de **perdre le
  `prefetch_related`** → réécrit en `Q(a)|Q(b)` et prefetch déplacé après tous les filtres.
- `prefetch_related('lignes')` ramène **tout** l'arbre (le related_name `lignes` couvre toutes
  les `LigneDevis` du devis, parents comme enfants) → une seule requête pour l'arbre complet.
- **Piège subtil** : la 1ʳᵉ correction du dashboard laissait une croissance résiduelle des
  requêtes. Cause = le **template** `dashboard.html` appelait encore `d.total_brut` (méthode)
  sur les devis du widget « Derniers devis ». Diagnostic via `CaptureQueriesContext` (requêtes
  `SELECT 1 ... WHERE parent_id=N LIMIT 1` = `enfants.exists()`). Toujours vérifier les
  **templates**, pas seulement les vues.

---

## Session 24 — 06/06/2026 — Module Planning & Émargement (conception)

### Contexte
Nouveau module pour remplacer deux circuits manuels actuels :
1. **Émargement/paie** — papier → assistante re-saisit dans Excel pour la RH.
2. **Suivi de production** — assistante calcule manuellement la « fraction fine »
   (répartition jours par chantier) à partir des émargements → compare jours facturables
   vs réalisés dans un gros classeur Excel.

**Principe directeur : saisie unique.** L'encadrant pointe une fois (personne / demi-journée /
chantier) → tout se dérive : feuille de paie mensuelle réglementaire (FSE/CISP) ET
suivi de production (jours facturables / réalisés / écart). Supprime les deux re-saisies.

### État actuel (fin session 24)
**Phase maquettes uniquement.** Aucun code Django écrit.
- `mockups/planning/1-planning-mois.html` — timeline mois, 6 équipes repliables,
  barres de chantiers (durée ajustable), événements au-dessus en voie haute, renfort
  pointillé, demi-journées en pointillé léger, Sa/Di bloqués, vendredi `+` par équipe.
- `mockups/planning/2-emargement-semaine.html` — grille hebdo, M/A sur 2 lignes, panel
  équipiers façon bibliothèque, prêt par plage (grillé « ↩ équipe »).
- `mockups/planning/3-production.html` — widgets configurables (réutilise dashboard).
- `mockups/planning/4-feuille-emargement.html` — fiche réglementaire FSE/CISP, semaines
  ISO, paraphes salarié + ETI (2 lignes), mois précédent éditable (ocre).

### Plan d'implémentation
Plan complet dans `.claude/plans/twinkly-whistling-wirth.md` (modèle de données, 7 commits,
pièges, tests, URLs). `NOTES_PLANNING.md` sera créé à la 1ʳᵉ session de code.

### Décisions actées (extrait)
- Semaine = **Lun–Jeu** (vendredi activable par équipe via `+`, Sa/Di bloqués).
- Pas de vendredi dans le calcul des jours facturables → helper `jours_ouvres(d1,d2)` Lun-Jeu.
- `taux_jour_facturable` ≈ 472 €/j (onglet SORM du classeur Excel) — à confirmer uniforme.
- Timeline : **CSS Grid + SVG background 232 px/semaine** (5j×40px + Sa16px + Di16px).
- Module visible uniquement admin + encadrants (`peut_acceder_planning`).
- Maquettes validées par David P. — prêt à passer au code commit 1 (modèles + migration).

---

## Session 22 — 04/06/2026 — Colonne Auteur, filtres, icônes, seed_demo

### Fichiers modifiés / créés
- `core/templates/core/devis_list.html` + `factures_list.html` + `facture_compta_list.html`
  + `avoirs_list.html` — colonne **Auteur** (1ʳᵉ colonne) sur toutes les listes ;
  libellé **« Coupable »** pour les avoirs. `select_related('created_by')` ajouté
  dans toutes les vues correspondantes.
- `core/views.py` — `devis_list` + `factures_list` : paramètre `?auteur=<pk>`,
  queryset `created_by_id`, liste `auteurs` (utilisateurs ayant créé des objets).
  `factures_list` : nouvelle barre de filtres (auparavant aucune).
- `core/templates/core/base.html` — icônes finales : Appels de convention →
  `ti-phone-ringing`, Aides travaux → `ti-gift` (cadeau rétabli).
- `core/management/commands/seed_demo.py` (**nouveau**, puis enrichi) :
  - 9 équipes 35 (GORM/GOSM maçonnerie pierre+chaux remparts Rennes/St-Malo ;
    SORM/AQRM/AQSM rénovation peinture/cloison/sols PVC ; Bricobus rural élec+plomberie ;
    Bricobus urbain petite reno ; ARA PO isolation naturelle+réseaux+poêle ; ARA LOC reno).
  - Articles variés : titres, composites, simples, forfaits, MO, MAT.
  - Frais de déplacement (< 20 km) = ligne **forfait F** (pas FIN) sur 1-2 devis insertion.
  - Autres équipes : lignes FIN liées aux fonds existants (ANAH, CBB, Schneider, Aubade,
    Atlantic) via `get_or_create` sur la bibliothèque des aides.
  - Équipes réutilisées (`icontains`) ; tout marqué `SEED_DEMO` ;
    `--clear` supprime uniquement la démo de l'utilisateur cible.
  - Lancé sur Railway via `railway run python manage.py seed_demo`.

### Décisions actées
- Colonne Auteur = `get_full_name|default:username|default:"—"` (pas d'impact modèle).
- Filtre auteur = liste restreinte aux utilisateurs ayant réellement créé des objets
  (pas tous les users, menu propre).
- seed_demo **ne supprime jamais** les aides/équipes/services/territoires — uniquement
  les devis, factures et clients de démo (Facture d'abord car `PROTECT` sur Devis).

---

## Session 21 — 04/06/2026 — Tableau de bord personnalisable & repli sidebar

### Contexte
Le dashboard était figé (4 KPIs + 2 listes). Deux besoins : (1) corriger un bug — la liste
« Dernières factures » incluait depuis la session 19 les factures compta (`devis=None`) et les
avoirs (colonne « Devis » vide) ; (2) le rendre **personnalisable par utilisateur** (widgets
choisis, ordonnés, avec portée Tous/Mes données/Mon équipe). Plus une demande UX : **replier la
sidebar** (icônes seules) et changer deux icônes.

### Fichiers modifiés / créés
- `models.py` — `ProfilUtilisateur.dashboard_config` (JSONField, défaut dict). Migration
  `0017_profilutilisateur_dashboard_config`.
- **`core/dashboard_widgets.py` (nouveau)** — registre `WIDGETS` (id → méta : title, type
  kpi/list/chart/activity, icon, supports_scope, **requires_compta**), `DASHBOARD_DEFAULT`,
  fournisseurs de données (`scoped_devis/factures/audit`, `widget_data`), `widgets_for(user)`
  (filtre compta via `peut_acceder_compta`), `resolve_dashboard(profil, user)` (calcul **lazy** :
  seuls les widgets visibles), `sanitize_config` (nettoyage avant stockage — ignore ids inconnus
  ET widgets compta non autorisés).
- `views.py` — `dashboard` réécrite (utilise `resolve_dashboard`) ; **`dashboard_save`** (POST
  JSON, `@require_POST`). Import du module.
- `urls.py` — route `/tableau-de-bord/config/`.
- `templates/core/dashboard.html` — **réécrit** : grille de widgets (KPI en `.stat`, listes/
  charts/activité en `.card`), rendu générique par type + par id, **Chart.js via CDN** (line/
  doughnut/bar), sélecteur de portée par widget (header), mode édition (glisser-déposer,
  masquer, panneau « Ajouter un widget », bouton Personnaliser/Verrouiller), état d'édition
  conservé via `sessionStorage` après un rechargement (ajout/portée).
- `templates/core/base.html` — **icônes** Devis `ti-file-text`→`ti-calculator`, Factures
  `ti-receipt`→`ti-cash` ; **repli sidebar** : libellés en `<span class="nav-label">`, € en
  `<i class="nav-euro">`, bouton bascule en bas (`.nav-collapse-btn`), classe `html.sb-collapsed`
  (largeur 56px, libellés/sections masqués), script anti-flash en `<head>` (localStorage
  `sidebar-collapsed`), `toggleSidebar()`, tooltips `title` sur chaque item.
- `tests.py` — classe `DashboardTests` (8 tests) : rendu par rôle, **rendu de tous les
  widgets**, exclusion compta de `list_factures_recentes` (régression du bug), gating compta
  (caché hors compta), persistance config, ids inconnus ignorés, widget compta non injectable
  par POST, portée `mine`. **47 tests au total.**

### Décisions actées
- **Réutilisation** : `created_by` (Devis/Facture) + `get_collegues_ids` pour la portée ;
  `peut_acceder_compta` pour le gating ; CSS existant (`.stat`/`.card`/badges) ; pattern
  glisser-déposer proche de `facture_compta_detail.html`.
- **Widgets compta gatés** (`requires_compta=True` : `list_avoirs_recents`) — invisibles et
  **non injectables** pour les non admin/comptable (filtré au rendu ET à la sauvegarde).
  `list_factures_a_valider`/`kpi_a_valider` : pour un non-compta, restreints au chantier.
- **Chart.js via CDN** (`@4`), chargé dans `extra_js` (pas globalement) ; données passées via
  `json_script` (id = id du widget).
- **Perf** : on ne calcule que les widgets visibles ; counts/sommes DB via `aggregate` ;
  les sommes de `total_brut` (méthode Python) restent en boucle — dette déjà notée.
- **Repli sidebar** : état sur `<html>` (`sb-collapsed`) pour appliquer avant peint (anti-flash),
  mémorisé en `localStorage`.

### Pièges rencontrés
- `total_brut()` est une méthode Python (pas un champ) → impossible d'agréger en SQL pour le CA
  et les graphiques de CA ; agrégation manuelle en Python (acceptable beta).
- Repli sidebar : le `€` « Aides travaux » était un `<span>` (pas d'`<i>`) → converti en
  `<i class="nav-euro">` pour être centré comme une icône en mode replié.
- Hors-scope noté (tâche suivante) : colonne + filtre « Créateur » dans les listes Devis/Factures.

---

## Session 20 — 04/06/2026 — Diagnostic envoi emails & contournement fallback MDP

### Contexte
Remontée : « les mails de création utilisateur ne partent pas ». Diagnostic mené avec les
logs Brevo.

### Diagnostic
- Test d'envoi via `manage.py shell` : en **local**, `BREVO_API_KEY` est un placeholder
  (`VOTRE_CLE…`) → 401, normal. La vraie clé est sur Railway.
- En **prod**, l'écran affichait *« Email envoyé »* mais rien n'était reçu. Logs Brevo :
  clé valide (Brevo accepte, 2xx, un mail *Delivered*) **mais soft bounce « Access denied »**
  vers les adresses `@compagnonsbatisseurs.eu`.
- **Cause racine** : envoi **depuis** `@compagnonsbatisseurs.eu` **via Brevo** → le M365 de
  l'association rejette (anti-usurpation, DNS du domaine non authentifié auprès de Brevo).
  Détails + alternatives (DNS via IT nationale / domaine dédié / Graph API) : **§ Infra**.

### Fichiers modifiés
- `core/views.py` — `utilisateur_create` : l'email devient **best-effort** ; le **texte
  complet de l'invitation** (`message_invitation`, construit une seule fois, sert à l'envoi
  ET à l'affichage) est **toujours** montré à la création pour copier-coller (plus de
  redirection « Email envoyé » trompeuse). `invitation_envoyee` passé à True seulement si
  Brevo a accepté. Champ session renommé `email_erreur` → `email_statut` ; ajout `email` +
  `message` dans la session.
- `core/templates/core/utilisateur_succes.html` — affiche le mot de passe + le **message
  d'invitation complet** dans un `<pre>` avec bouton « Copier le message » ; `email_erreur`
  → `email_statut`.
- `NOTES_DEV.md` — § Infra (diagnostic + alternatives), ligne d'état, cette session.

### Décisions actées
- **Contournement beta = D** (fallback écran) : afficher toujours le MDP, communication
  manuelle. Le vrai correctif (authentifier le domaine dans Brevo, action DNS de l'IT
  nationale) reste à demander — voir § Infra.
- Pas touché au durcissement `settings.py` (erreur si clé vide en prod) — proposé, non retenu
  pour l'instant (la clé est bien présente sur Railway).
- **Correctif durable** (rappel) : authentification DNS du domaine dans Brevo, **à faire par
  l'IT nationale** — voir § Infra et § Prochaines étapes (point 8).
- Commité + poussé sur `main` (déploiement Railway prod).

---

## Session 19 — 04/06/2026 — OUTILS COMPTA (factures structure/appel) & avoirs

### Contexte
Besoin de facturer directement des **structures** (collectivités, bailleurs, associations)
sans passer par un devis, via deux outils — **Factures Structure** et **Appels de convention** —
regroupés dans une section sidebar « OUTILS COMPTA » réservée aux comptables et admins.
Ajout aussi des **avoirs** (factures négatives) pour tous les types. Choix structurant :
**réutiliser le modèle `Facture`/`LigneFacture`** (devis rendu optionnel) plutôt que des
modèles parallèles.

### Fichiers modifiés
- `models.py` :
  - `Client.type_client` (choices particulier/association/bailleur/collectivite/autre)
  - **`ContactClient`** (nouveau) — carnet optionnel 1..n par client (service, nom, fonction, email, tél)
  - `Facture` : `devis` → **nullable** ; `client` FK, `contact_client` FK, `coordonnees_cb`
    (snapshot), `facture_origine` FK (avoir→source) ; type_doc `structure` ajouté
  - Helpers `Facture` : `is_compta`, `get_client()`, `get_reference_client()` (proforma `PF-`)
  - `Devis.total_facture()` **corrigé** : somme directe de tous les types (l'avoir porte un
    montant négatif et se déduit naturellement)
  - `ProfilUtilisateur.peut_voir_compta()` (sidebar)
- `migrations/0016_…` — type_client, ContactClient, champs Facture
- `permissions.py` : **`peut_acceder_compta`** (admin/comptable, extensible 'responsable') ;
  **gardes null-devis** sur `peut_voir/modifier/envoyer/supprimer_facture`
  (`if facture.devis and _partage_equipe_devis(...)`) ; `peut_voir_facture` restreint les
  factures compta (devis None) aux rôles compta
- `views.py` :
  - **`NUMEROTATION_FACTURE`** + **`gen_numero_facture(type_doc)`** : découple préfixe affiché
    et séquence de comptage. structure→FAC (séquence partagée), appel→APP (séquence propre),
    avoir→AV. `facture_valider`/`facture_bypass` branchés dessus.
  - Bloc « OUTILS COMPTA » : `factures_compta_list`, `facture_compta_create`,
    `facture_compta_detail`, `facture_compta_valider`, `facture_compta_status`,
    `facture_compta_delete`, `facture_compta_duplicate`, `lignes_compta_get/save`,
    `client_contacts_get`, `contact_client_create`, `contact_client_delete`
  - **`avoir_create`** : copie les lignes avec **quantités inversées** (titres + forfaits),
    `facture_origine` renseigné ; gate `peut_modifier_facture(source)` ; source validée requise
  - **`avoirs_list`** (Principal) : tous les avoirs ; filtré aux avoirs de chantier si l'user
    n'a pas accès compta
  - `factures_list` **restreinte** aux factures de chantier (`devis__isnull=False`, hors avoirs)
    + `prefetch_related('avoirs')` pour le badge
  - `facture_apercu` **généralisée** : gère `devis=None` (gardes sur `devis.*`, acomptes/FIN/réf
    devis conditionnés), client via `get_client()`, coordonnées snapshot, titre dynamique
  - `clients_list`/`client_create`/`client_edit` : champ `type_client` + filtre
- `urls.py` — routes `/avoirs/`, `/factures/<pk>/avoir/`, bloc `/compta/...`
- `admin.py` — `ContactClient` inline, `type_client` sur ClientAdmin, raw_id_fields sur Facture
- Templates :
  - `base.html` — section sidebar « OUTILS COMPTA » (admin/comptable) + lien « Avoirs » dans
    Principal ; **`.btn i,.ico-btn i,… {pointer-events:none}`** (icônes transparentes à la souris)
  - `facture_compta_list.html`, `facture_compta_form.html`, `facture_compta_detail.html` (nouveaux)
  - `avoirs_list.html` (nouveau) — icône d'origine (structure/appel/chantier) par ligne
  - `facture_apercu.html` — bloc chantier **conditionnel** (masqué si vide), titre dynamique
    (FACTURE / Facture d'appel de convention / AVOIR + PROFORMA), réf client `get_reference_client`
  - `factures_list.html` — badge « ↩ Avoir » cliquable + bouton « Créer un avoir »
  - `clients.html` — colonne/filtre type, gestion des contacts dans la modale d'édition
- `tests.py` — classe `FactureComptaTests` (14 tests) : accès, création, numérotation FAC/APP/AV,
  proforma PF-, validation admin/comptable, lignes, avoirs (qtés négatives, refus brouillon),
  filtre type_client. **39 tests au total.**

### Décisions actées
- **Réutilisation `Facture`/`LigneFacture`** : `devis` nullable, type_doc `structure`/`appel`,
  lignes plates 2 niveaux (TITRE + `F` forfait). `LigneFacture` inchangé.
- **Numérotation** : structure partage la séquence FAC (gratuit car même table) ; appel = préfixe
  APP + séquence propre. **Reconfigurable** : passer `appel.sequence` à `'FAC'` (1 ligne) bascule
  les appels sur la numérotation FAC en gardant le préfixe APP.
- **Proforma** : `draft` = proforma ; éditions client préfixées `PF-` (`get_reference_client`),
  l'outil interne garde « BROUILLON ».
- **Validation** : `peut_valider_facture` existant (admin OU comptable) — un seul suffit.
- **Avoirs** : créés depuis une facture validée, quantités inversées **modifiables** (corriger si
  seule une partie est annulée), édités dans l'éditeur compta simple, liés via `facture_origine`.
  `montant` négatif ⇒ `total_facture()` les déduit.
- **Aperçu non forké** : bloc chantier masqué quand vide (vrai aussi pour particuliers sans chantier).
- **Base client unique** + `type_client` + carnet `ContactClient` optionnel (créé à la demande).
- **Accès compta** = admin/comptable (sidebar + toutes les vues), via `peut_acceder_compta`.
- **Éditeur compta** : glisser-déposer (poignée), dupliquer/supprimer par ligne, copier les titres
  avec leurs forfaits.

### Pièges rencontrés
- `{# … #}` Django **ne gère pas le multiligne** → utiliser `{% comment %}`.
- **Toast invisible** (`opacity:0`) sans `pointer-events:none` recouvrait le coin bas-droit et
  bloquait le clic sur « Sauvegarder » → ajouté `pointer-events:none`.
- **Icônes** `<i>` dans les boutons captaient la souris → `pointer-events:none` global (base.html).
- `factures_list` montrait toutes les factures (y compris compta, `devis=None`) → plantait le
  template sur `devis.pk` ; restreinte aux factures de chantier.

---

## Session 18 — 03/06/2026 — Export Excel (beta temporaire)

### Contexte
Fonctionnalité **temporaire** ajoutée pour la phase beta : permet aux collègues qui
testent l'outil d'exporter un devis en `.xlsx` pour conserver leur travail. **À
supprimer avant la version finale** — voir § Fonctionnalités temporaires beta.

### Fichiers modifiés
- `requirements.txt` — ajout `openpyxl`
- `core/views.py` — ajout `import io` (ligne 1) ; vue `devis_export_excel` (environ
  200 lignes, insérée juste avant `devis_entete_save`)
- `core/urls.py` — route `path('devis/<int:pk>/excel/', views.devis_export_excel, name='devis-excel')`
- `core/templates/core/devis_detail.html` — onglet `<a href="{% url 'core:devis-excel' ... %}">Excel</a>`
  ajouté dans la barre d'onglets après "Vue client"

### Décisions actées
- Export `.xlsx` (openpyxl) — pas de remplissage du template `.xls` existant
  (xlwt ne supporte pas l'insertion de lignes dynamiques)
- Structure : en-tête devis → LOTs avec lignes → SS totaux → Total brut →
  Aides/financements (FIN) → Montant dû → Acomptes payés → Conditions → Signatures
- HTML dans les descriptions (`<div>`, `<br>`) nettoyé via `strip_html()` (helper
  interne à la vue)
- Migration locale manquante `0015_profil_invitation_envoyee` appliquée en cours
  de session (`manage.py migrate`)
- `core/templates/core/base.html` — renommage sidebar : "Aide" → "Manuel" (icône `?`
  conservée) ; "Aides" → "Aides travaux" (icône cadeau remplacée par € temporaire)

---

## Session 17 — 03/06/2026 — Audit sécurité & correctifs

### Fichiers modifiés
- `cbretagne/settings.py` — `ImproperlyConfigured` si `SECRET_KEY` absente en prod
  (détection via `DATABASE_URL`) ; bloc `if not DEBUG and DATABASE_URL:` avec
  `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`. Import `ImproperlyConfigured`.
- `core/views.py` :
  - `facture_bypass` + `facture_bypass_send_code` — gate `peut_modifier_facture` sur les
    deux vues ; code OTP posé en session uniquement après envoi email réussi.
  - Helper `to_decimal(val, default)` ajouté dans HELPERS.
  - `aides_api_save` — `montant_defaut` via `to_decimal` (protège la 500).
  - `lignes_save` + `lignes_facture_save` — `quantite`/`cout_unitaire` via `to_decimal`.
  - `mot_de_passe_oublie` — `set_password`+`save` uniquement si `send_mail` réussit
    (évite de bloquer l'accès de l'utilisateur en cas d'échec Brevo).
  - Guillemets typographiques (U+2018/U+2019) remplacés par des apostrophes ASCII dans
    tout le fichier (bug d'encodage introduit lors d'un Edit précédent).
- `core/tests.py` — 4 nouveaux tests dans 2 classes :
  - `AccesDevisFactureTests` : `test_bypass_send_refuse_hors_equipe`,
    `test_bypass_refuse_hors_equipe`
  - `SecurityFixesTests` (nouvelle classe) : `test_aides_api_save_montant_invalide_retourne_400`,
    `test_reset_mdp_preserve_mot_de_passe_si_email_echoue`
- `NOTES_DEV.md` — corrections dette (DEBUG, Brevo, bypass) ; session 17.
- `core/templates/core/devis_form.html` + `devis_detail.html` — `step="0.5"` → `step="0.01"`
  sur le champ Taux horaire MO (€/h) : permet la saisie à 2 décimales (ex : 47.24).

### Décisions actées
- **Bypass OTP** : gate `peut_modifier_facture` (= équipe du devis) en beta ; rôle à
  restreindre (admin/comptable uniquement ?) en Phase 4 selon les retours.
- **Sécurité settings** : détection prod via `DATABASE_URL` (présent sur Railway, absent
  en dev/test) — évite d'activer `SECURE_SSL_REDIRECT` dans les tests locaux.
- **HSTS** : volontairement différé (post-beta) — effet persistant côté navigateur.
- **Race `gen_reference`** : laissé en dette (proba nulle à l'échelle beta).
- **`total_facture()` brouillons** : comportement inchangé (décision métier à confirmer).

---

## Session 16 — 02/06/2026 — SMTP, invitations, manuel utilisateur & reset MDP

### Fichiers modifiés
- `requirements.txt` — ajout `python-dotenv`
- `cbretagne/settings.py` — chargement `.env` via `load_dotenv()` ; config SMTP M365
  (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `DEFAULT_FROM_EMAIL`) ; `SITE_URL` (Railway ou localhost)
- `.env` — fichier local (gitignore) avec les credentials SMTP de la boîte
  `noreply@compagnonsbatisseurs.eu`
- `core/models.py` — `ProfilUtilisateur.invitation_envoyee` (BooleanField, défaut False)
- `core/migrations/0015_profil_invitation_envoyee.py`
- `core/views.py` :
  - `aide_view` — page publique (pas de `@login_required`)
  - `mot_de_passe_oublie` — reset MDP restreint au domaine `@compagnonsbatisseurs.eu` ;
    génère un mot de passe temporaire et l'envoie par email (même message si adresse
    inconnue → pas d'énumération)
  - `utilisateur_create` — envoie l'email d'invitation avec identifiant + MDP temp +
    lien connexion + lien manuel ; `invitation_envoyee=True` si envoi OK ; fallback page
    de succès avec affichage MDP si envoi échoue ou pas d'email
  - `facture_bypass_send_code` — envoie le code OTP par email à `request.user.email` ;
    retourne `{'ok': False, 'error': '...'}` si pas d'email ou SMTP échoue
  - `utilisateur_create` (GET) + `utilisateur_edit` (GET) — équipes triées par
    `service__nom, nom` pour le `{% regroup %}`
- `core/urls.py` — routes `/aide/` et `/mot-de-passe-oublie/`
- `core/templates/core/aide.html` — page manuel utilisateur autonome (pas de base.html) :
  TOC sticky, 9 sections, lien "← Retour à l'application" encadré vert
- `core/templates/core/mot_de_passe_oublie.html` — page reset MDP (style login.html)
- `core/templates/core/login.html` — lien "Mot de passe oublié ?" sous le bouton
- `core/templates/core/utilisateur_form.html` — équipes groupées par service via
  `{% regroup %}` (plus compact, prévu pour ~6 services × ~5 équipes)
- `core/templates/core/utilisateur_succes.html` — page fallback (email non envoyé) :
  affiche le MDP + message d'erreur contextuel
- `core/templates/core/utilisateurs_list.html` — badge "Invitation envoyée" (vert) ou
  "Invitation non envoyée" (orange) sous l'email de chaque utilisateur
- `core/templates/core/devis_detail.html` — `openBypass()` devient `async` : attend la
  réponse du `/send/` et affiche l'erreur dans la modale si envoi impossible
- `core/tests.py` — `test_bypass_send` : alice reçoit un email pour que la vue réussisse

- `requirements.txt` — contrainte `django>=4.2,<6.0` → `django>=6.0` (alignée avec
  la version réelle en prod)
- `cbretagne/settings.py` — `STATICFILES_STORAGE` (supprimé dans Django 6) remplacé
  par le dict `STORAGES` avec `whitenoise.storage.CompressedStaticFilesStorage`
- `railway.toml` — créé : `collectstatic` déplacé en phase **build** Railway ;
  `migrate + gunicorn` en phase **deploy**. Remplace le Procfile pour le contrôle
  des phases build/start.

### Décisions actées
- **Email — Brevo** : Railway bloque les ports SMTP sortants (587/465) sur les comptes
  hobby. Migration vers Brevo (HTTP API via `django-anymail[brevo]`). Variable Railway :
  `BREVO_API_KEY`. Expéditeur `noreply@compagnonsbatisseurs.eu` vérifié dans le dashboard
  Brevo. `DEFAULT_FROM_EMAIL` hardcodé dans settings.py.
  M365 SMTP fonctionnel en local uniquement (testé session 16, abandonné pour prod).
- **Invitation** : email prioritaire (pas d'affichage MDP à l'écran si envoi OK) ;
  fallback écran si pas d'email ou SMTP KO — pas de perte d'accès.
- **Bypass OTP** : désormais fonctionnel (code envoyé par email) — dette session 10 soldée.
- **Reset MDP** : restriction domaine `@compagnonsbatisseurs.eu` côté serveur ;
  pas d'énumération (même message quel que soit l'email).
- **Manuel `/aide/`** : page HTML publique (sans `@login_required`), maintenu manuellement
  à chaque grosse session. Lien dans la sidebar + dans l'email d'invitation.
- **Équipes groupées** : `{% regroup %}` Django (pas de JS) ; tri `order_by('service__nom', 'nom')`
  dans les deux vues (création + édition).
- **CSS admin Railway** : `STATICFILES_STORAGE` supprimé en Django 6 → `STORAGES` dict.
  Cause racine : `collectstatic` tournait dans la phase start (Procfile) mais les fichiers
  ne persistaient pas jusqu'à gunicorn. Résolu par `railway.toml` qui déplace
  `collectstatic` en phase build (fichiers intégrés à l'image container).

---

## Session 15 — 02/06/2026 — Correctifs UX onglet Factures & section financement

### Fichiers modifiés
- `devis_detail.html` — persistance de l'onglet Factures après tout rechargement
  déclenché par une action facture (changement de statut, validation, bypass, paiement).
  Mécanisme : `sessionStorage` (`devis-next-tab-<pk>`) posé avant le rechargement,
  lu et effacé au chargement suivant. Couvre : forms POST dans `#pane-factures`,
  `#delete-facture-form` (modal hors pane), `confirmBypass()`, `confirmerPaye()`.
- `devis_detail.html` — description par défaut à la création d'un acompte :
  `setModalType('acompte')` pré-remplit le champ Notes avec *"Montant à régler avant
  le démarrage des travaux"* si vide ; re-basculer sur Facture efface le texte par
  défaut (sauf si l'utilisateur l'a modifié).
- `devis_pdf.html` — CSS `.sep-fin td` : titre "Financements & subventions" passe de
  gris discret (fond `--gray-lt`, couleur `--gray-md`, 9px) à rouge clair (fond
  `--red-lt`, couleur `--red`, 10px, bordure `#F5C6C2`) — cohérent avec les lignes FIN.
- `views.py` — `facture_apercu` : ajout de `lignes_fin` au contexte (lignes FIN
  racines du devis) ; exclusion des lignes FIN du queryset `lignes_filtrees` (évite
  l'affichage double positif/négatif).
- `facture_apercu.html` — CSS `.sep-fin` et `.row-fin` (même style que devis_pdf) ;
  section financement ajoutée en fin de tableau, **uniquement pour les factures
  classiques** (`facture.type_doc != 'acompte'`) ; les totaux restent inchangés.

### Décisions actées
- **Onglet Factures** : `sessionStorage` plutôt que hash URL ou param serveur —
  aucun changement côté Django, clé scoped par devis pk, effacée après usage.
- **Section financement sur la facture** : informatif uniquement (lignes FIN du devis
  dans le tableau) ; les totaux de la facture ne sont pas recalculés (le montant
  facturé reste la référence comptable).
- **Financement masqué sur les acomptes** : sans pertinence comptable sur un acompte,
  la section ne s'affiche pas sur les aperçus `type_doc='acompte'`.

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
- **`gen_reference`** — calcule max+1 en Python → race condition sur la numérotation concurrente.
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
- **Context processor** — injecter `profil` automatiquement dans tous les templates (évite `get_profil(request.user)` dans chaque vue).
- **Modèle `BibliothèqueAides`** — nom de classe avec accent (non-ASCII), fragile pour imports/outils. Renommer en ASCII (`BibliothequeAides`) si on retouche le modèle.
- ✅ **Auditer les templates** — vérifié session 36 (11/06/2026) : aucun `{{ f.reference }}` parasite restant dans `core/templates/`.
- **Calcul des totaux dupliqué (2 implémentations)** — le parcours d'arbre du total existe à
  **deux endroits** : `core/totaux.py` (version **en mémoire**, anti N+1, utilisée par les
  **listes ET le dashboard** via un import partagé) et `models.py` `LigneDevis.total()` /
  `Devis.total_brut()` (version **une requête par nœud**, conservée pour l'affichage d'**un
  seul** devis : `devis_detail`, réponse `lignes_save`, PDF…). C'est **volontaire** (inutile
  de précharger pour un objet unique), mais les deux doivent rester **sémantiquement
  identiques** — garde-fou : `test_totaux_identiques_aux_methodes_modele` (égalité stricte).
  Consolidation possible (Phase 3, propreté seulement) : faire déléguer `models.py` à
  `totaux.py` en préchargeant l'arbre du devis courant → une seule implémentation. Non requis
  pour la perf.

### Tests
- **Couverture session 14 manquante** — zone_financement (persistance), `aide_delete`.
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
  `fiche_presence_save`/`fiche_note_save`, permissions). **136 tests** au total.
  Reste non couvert : resize multi-équipes (`affectation_move`), tableau de bord
  insertion (`mo_mat_lignes`, filtres), `vendredi_toggle`, `tranche_creer`.

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
- **Dépôt SharePoint via Microsoft Graph — factures + fiches de présence** (acté 13/06/2026) :
  pousser les PDF générés vers le SharePoint partagé (tenant M365 de l'association) —
  factures au passage validé/envoyé, fiches de présence à la clôture du mois (s'emboîte
  avec la clôture auto à l'impression, déjà actée). Répond en partie à la conservation
  réglementaire FSE. **Ordre des dépendances : OVH → WeasyPrint → ce chantier.**
  Côté code : `msal` (jeton applicatif) + `PUT /sites/{site-id}/drive/items/.../content`.
  Prérequis bloquant : **demande IT nationale unique** (voir § Infra) — ne rien développer
  avant d'avoir les identifiants.
- **Annexes au devis (croquis, fiches techniques, plans)** (spec actée 13/06/2026) :
  nouveau modèle `AnnexeDevis` (FK devis, FileField, titre, created_by, created_at) +
  upload/liste/suppression dans l'éditeur de devis (droits = `peut_modifier_devis`).
  **Formats acceptés : images (JPG/PNG) et PDF uniquement.** **Intégrées au PDF client** :
  images = pages d'annexe ajoutées en fin de devis (WeasyPrint), PDF joints = fusion via
  `pypdf` après génération. **Dépend de : OVH (volume persistant `media/` — Railway perd
  les uploads au redéploiement, cf. session 12 logo) puis WeasyPrint.** Les annexes
  suivront aussi le dépôt SharePoint (même pipeline que les factures).
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
- **🔴 Demande IT nationale unique — app Entra ID / Microsoft Graph** (actée 13/06/2026,
  **à envoyer une fois l'OVH en place** — une seule demande, couvre SharePoint + emails) :
  1. App registration « CB Bretagne — outil devis/facturation » dans Entra ID
     (récupérer `tenant_id` + `client_id`).
  2. Permission Graph **`Sites.Selected`** (type Application) + **grant en écriture sur le
     site SharePoint CB Bretagne** (fournir l'URL du site dans la demande — sans ce grant
     explicite, `Sites.Selected` ne donne accès à rien).
  3. Permission **`Mail.Send`** (type Application) + **`ApplicationAccessPolicy`** limitée
     à la boîte `noreply@compagnonsbatisseurs.eu` (sans la policy, l'app pourrait envoyer
     depuis n'importe quelle adresse du tenant).
  4. De préférence authentification par **certificat** (clé publique fournie par nous) ;
     à défaut secret client de durée maximale — **noter la date d'expiration** (≤ 24 mois,
     panne silencieuse classique au renouvellement).

  Brouillon prêt à envoyer :
  > Objet : Enregistrement d'une application Entra ID pour l'outil de gestion CB Bretagne
  >
  > Bonjour, dans le cadre de notre outil interne de devis/facturation (hébergé sur notre
  > VPS OVH), nous aurions besoin d'un enregistrement d'application dans Entra ID :
  > (1) app « CB Bretagne — outil devis/facturation », en nous communiquant tenant_id et
  > client_id ; (2) permission Microsoft Graph Sites.Selected (Application) avec grant en
  > écriture sur notre site SharePoint : [URL du site] ; (3) permission Mail.Send
  > (Application) restreinte par ApplicationAccessPolicy à noreply@compagnonsbatisseurs.eu ;
  > (4) de préférence une authentification par certificat (nous fournissons la clé
  > publique), sinon un secret client avec sa date d'expiration. Cette demande remplace
  > notre demande précédente d'authentification du domaine dans Brevo (SPF/DKIM), qui
  > devient sans objet.
- **Migration Railway → OVH (Phase 4)** — volume persistent pour les fichiers uploadés
  (logo, etc.). **Mise en place prévue semaine du 15/06/2026** (info 11/06). Conditionne :
  export PDF (WeasyPrint + snapshots), restriction email à décommenter, authentification
  domaine Brevo (IT nationale), HSTS, mise à jour `CSRF_TRUSTED_ORIGINS`/`SITE_URL`.
- ✅ **Renommage équipes sur Railway (prod)** — fait session 27 : SORM→65-SORM, GORM→65-GORM, GOSM→61-GOSM, AQSM→58-AQSM, AQRM→AQRM A + AQRM B.
