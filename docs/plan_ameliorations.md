# Plan — Améliorations CB Bretagne (redondances code + cohérence/fluidité UI)

> Plan de travail établi le 13/06/2026. À exécuter **une phase par session/fenêtre**.
> Chemin de référence dans le dépôt : `docs/plan_ameliorations.md`.

## Context

Demande : analyser le projet en profondeur et proposer des améliorations sur deux axes —
**redondances de code** et **cohérence/fluidité de l'UI**. Le projet est mûr (42 sessions,
156 tests, beta en cours jusqu'à ~septembre 2026), bien structuré (`permissions.py`,
`totaux.py`, `dashboard_widgets.py`, helpers planning extraits). L'uniformisation CSS de
base (badges/boutons/tableaux/modales/charte) est déjà faite ; il reste de la **dérive
résiduelle** côté templates et de la **duplication réelle** côté backend Python et JS inline.

L'analyse (3 agents Explore + vérifications directes) a confirmé les points marquants :
- **JS dupliqué** : `calcTotal/calcMO/calcMat`, `assignNids/findNode/delFromTree` sont
  **sémantiquement identiques** entre `devis_detail.html` et `bibliotheque.html` (vérifié) ;
  aucun fichier JS partagé n'existe (tout est inline).
- **Backend** : `json.loads(request.body)` + try/except répété **22×**, `JsonResponse({'error':…})`
  ~94×, `get_profil(request.user)` 23×, `create_lignes` (save d'arbre) défini **3×**.
- **UI** : états vides présentés de 4 façons, filtres tantôt auto-submit tantôt bouton,
  `utilisateurs_list` structurellement divergent, styles inline de grille/largeur répétés.
- **Fluidité/risque** : `devis_detail`, `facture_compta_detail`, `bibliotheque` **n'ont pas
  de `beforeunload`** → fermeture d'onglet = perte des modifications non sauvegardées.

Objectif : un plan **en phases ordonnées** (dépendance + risque), chacune commitable
indépendamment, terminée par `test core` + entrée NOTES_DEV. Un **prompt prêt à coller**
par phase est fourni en fin de document pour lancer chaque session.

### Contraintes & conventions (rappels projet)
- **Commit direct sur `main`** ; déploiement = SSH manuel OVH (`./deploy.sh`), le push ne déploie PAS → committer phase par phase, vérifiée.
- Tests : `venv\Scripts\python manage.py test core` (doit rester vert, 156 tests).
- Commits **sans** `Co-Authored-By`. Mettre à jour NOTES_DEV à chaque session.
- Migration OVH semaine du 15/06 : les phases 1–2 sont sûres à tout moment ; phases 3–5
  (plus invasives) idéalement après stabilisation OVH, mais non bloquées par elle.
- Un fichier statique JS (`core/static/core/app.js`) se sert exactement comme `app.css`
  (déjà chargé via `{% static %}`) — pas de config supplémentaire.

---

## Ordre logique des phases

L'ordre suit la dépendance technique et le risque croissant :

| Phase | Thème | Risque | Modèle conseillé |
|-------|-------|--------|------------------|
| 1 | Socle backend (helpers transverses) | Faible | **Sonnet** |
| 2 | Cohérence UI / CSS | Faible | **Sonnet** |
| 3 | Socle JS partagé (`app.js`) | Moyen | **Opus** |
| 4 | Fluidité & sécurité d'usage (autosave / beforeunload / feedback) | Moyen | **Opus** |
| 5 | Propreté backend approfondie (fusion `create_lignes`, numéros) | Moyen-élevé | **Opus** (sauf sous-tâches triviales → Sonnet) |

Logique : 1 et 2 livrent de la valeur sûre tout de suite (mécanique, couverte par tests →
**Sonnet** suffit). 3 crée le socle JS partagé **avant** 4 pour que l'autosave/feedback se
construise dessus sans re-dupliquer ; 3 et 4 touchent l'éditeur de devis (calcul de prix,
critique) → **Opus**. 5 est la plus invasive (logique de sauvegarde) → **Opus**.

> **Lancement** : ouvrir une fenêtre neuve par phase, régler le modèle (`/model sonnet` ou
> `/model opus`) selon le tableau, puis coller le prompt de la phase (section finale).

---

## Phase 1 — Socle backend (helpers transverses)

**But** : supprimer la répétition mécanique la plus visible dans les vues.
**Modèle : Sonnet** — mécanique, périmètre clair, endpoints couverts par les tests.

Portée :
- `core/views.py` : ajouter en tête deux helpers
  - `parse_json_request(request)` → `(data, None)` ou `(None, JsonResponse 400)` ; remplace
    les **22** blocs `try: json.loads(request.body) except …` (10 dans `views.py`,
    12 dans `views_planning.py`).
  - `json_error(message, status=400)` + `json_error_permission()` (403) ; uniformise les
    ~94 `JsonResponse({'error':…})` / `{'ok':False,'error':…}` (choisir **un** format ;
    conserver `ok:False` là où le JS client le lit déjà — vérifier côté template avant).
- `core/context_processors.py` : ajouter `profil_utilisateur(request)` (même forme que
  `planning_access` existant) + l'enregistrer dans `settings.py`. Permet de retirer le
  passage manuel `'profil': profil` dans les `render(...)`. ⚠️ Ne **pas** retirer les
  `profil = get_profil(request.user)` utilisés dans la **logique** des vues — seulement le
  passage au template.

Fichiers : `core/views.py`, `core/views_planning.py`, `core/context_processors.py`,
`cbretagne/settings.py`.

Risque : faible. Vérif : `test core` + `manage.py check` + ouvrir 2-3 écrans (devis,
planning) pour confirmer que `profil` est bien dispo dans les templates.

---

## Phase 2 — Cohérence UI / CSS

**But** : finir l'uniformisation visuelle là où elle a dérivé. **Inclut planning.html et
emargement.html** (composants génériques qui ont dérivé). **Seule `presence_feuille.html`
(feuille de présence) reste visuellement intacte pour l'instant** (mise en page réglementaire
A4 à figer).
**Modèle : Sonnet** — édition de templates + classes CSS, peu d'ambiguïté, vérif visuelle.

⚠️ Sur planning/émargement : harmoniser **uniquement les composants génériques** (badges,
boutons, cartes, états vides, styles inline de grille/largeur, modales). **Ne pas toucher** au
CSS spécifique légitime (timeline planning, grille demi-journées, barres d'affectation,
calendriers) — il est métier et volontaire (cf. NOTES_DEV § Dette).

Portée (ajouts à `core/static/core/app.css` + remplacement des inline dans les templates) :
- `.empty-state` (centrage + padding + gris) → remplace les 4 variantes d'état vide
  (`devis_list`, `factures_list`, `avoirs_list`, `clients`, `equipiers`, `utilisateurs_list`,
  + `.dash-empty`/`.empty-msg` locales).
- `.grid-2`, `.grid-3`, `.grid-2-1` → remplace les `style="display:grid;grid-template-columns:…"`
  répétés (profil, clients, equipiers, utilisateur_form…).
- Largeurs de filtres : `.sel-narrow` / `.search-wrap` → remplace `style="max-width:…"`.
- `.breadcrumb` / `.breadcrumb-sep` → remplace les fils d'ariane inline (aides, bibliotheque,
  devis_detail, facture_detail).
- `.form-hint` (petite note sous un champ).
- Harmoniser **utilisateurs_list.html** sur le pattern standard `page-hd` + `toolbar` +
  `scroll-y` (aujourd'hui `page-body` + `card`, divergent) ; classes fantômes
  `text-center`/`text-muted` à remplacer.
- Filtres : passer **tous** les filtres en `onchange="this.form.submit()"` (clients,
  equipiers, insertion_dashboard alignés sur devis/factures). Garder un lien « Réinitialiser ».
- `.modal-scroll` sur les modales longues (clients, equipiers).

Fichiers : `core/static/core/app.css` + listes/formulaires cités + **planning.html /
emargement.html** (composants génériques seulement). **Ne pas toucher `presence_feuille.html`**
ni le CSS spécifique de la timeline/grille planning.

Risque : faible (CSS/HTML, pas de logique). Vérif : ouvrir chaque écran modifié, vérifier
filtres + état vide + modales. Pas de nouveau test (CSS/template).

---

## Phase 3 — Socle JS partagé (`core/static/core/app.js`)

**But** : une seule implémentation des utilitaires d'arbre + un wrapper fetch/CSRF.
**Modèle : Opus** — touche l'éditeur de devis (calcul de prix, critique) ; la consolidation
exige de vérifier que les variantes locales sont bien équivalentes avant fusion.

Portée :
- Créer `core/static/core/app.js`, chargé dans `base.html` (via `{% static %}`, avant le JS
  inline des pages). Y placer :
  - `TreeHelpers` : `calcTotal`, `calcMO`, `calcMat`, `fmtV`, `assignNids`, `findNode`,
    `delFromTree` (versions de référence, identiques à l'existant — vérifié).
  - `apiPost(url, payload)` : wrapper `fetch` POST JSON + `X-CSRFToken`, gestion d'erreur
    unifiée (remplace les ~13 réinventions inline).
  - `debounce(fn, delay)`.
- Brancher dans les **4 éditeurs** (`devis_detail`, `facture_detail`, `facture_compta_detail`,
  `bibliotheque`) : supprimer les copies locales, appeler les helpers partagés.
- ⚠️ **Parité serveur** : `TreeHelpers.calc*` doivent rester identiques à `core/totaux.py`
  (garde-fou serveur `test_totaux_identiques_aux_methodes_modele`). Ajouter un commentaire de
  synchronisation en tête de `app.js` ET dans `totaux.py`.
- Vérifier `assignNids`/`findNode` de `facture_detail`/`facture_compta_detail` (signatures
  légèrement différentes) : aligner ou conserver localement si la sémantique diffère
  réellement — ne pas forcer une fusion qui changerait le comportement.

Fichiers : `core/static/core/app.js` (nouveau), `base.html`, les 4 éditeurs.

Risque : moyen (éditeur de prix). Vérif : `test core` + **test manuel** d'un devis complet
(ajout TITRE/MO/MAT, drag&drop, total affiché == total après save), idem facture brouillon,
facture compta, biblio (round-trip groupe). Comparer les totaux avant/après refactor sur un
devis de démo (`seed_demo`).

---

## Phase 4 — Fluidité & sécurité d'usage

**But** : ne plus perdre de saisie ; feedback de sauvegarde cohérent.
**Modèle : Opus** — choix d'UX + gestion d'état sur l'éditeur critique ; risque de
régression sur la sauvegarde.

Portée (s'appuie sur les helpers de la Phase 3) :
- **`beforeunload`** sur `devis_detail`, `facture_compta_detail`, `bibliotheque` (avertir si
  modifications non sauvegardées — aujourd'hui absentes, perte silencieuse possible).
- **Suivi `dirty`** unifié (modèle de `facture_detail` qui le fait déjà) sur ces trois écrans.
- **Autosave optionnel** (à arbitrer avec l'utilisateur) : debounce sur blur dans
  `devis_detail` / `facture_compta_detail` / `bibliotheque`, OU se contenter du `beforeunload`
  + bouton explicite (moins risqué). **Décision à confirmer en début de session** (autosave
  sur un devis = écritures fréquentes ; voir si souhaité).
- **Feedback unifié** : un seul style d'indicateur « enregistré / en cours / erreur »
  (toast OU bandeau de statut — choisir un seul) réutilisé partout, dans `app.js`.
- Émargement : toast de fin « semaine enregistrée » après la dernière cellule (debounce) —
  optionnel.

Fichiers : `app.js`, `devis_detail.html`, `facture_compta_detail.html`, `bibliotheque.html`,
éventuellement `emargement.html`.

Risque : moyen. Vérif : `test core` + scénarios manuels (éditer puis fermer l'onglet →
avertissement ; sauvegarde → feedback ; erreur réseau simulée → message).

---

## Phase 5 — Propreté backend approfondie (optionnelle)

**But** : éliminer la dernière grosse duplication structurelle.
**Modèle : Opus** pour la fusion `create_lignes` (logique de sauvegarde, subtile et critique) ;
**Sonnet** acceptable pour les sous-tâches triviales (fusion `gen_reference`/`gen_numero_facture`).

Portée :
- **Fusion `create_lignes`** (défini 3× : `lignes_devis_save`, `lignes_facture_save`,
  `facture_compta_brouillon_save`) en une factory paramétrée (modèle cible, champs extra
  `aide`/`quantite_originale`/`ligne_devis_source_id`, filtre de récursion pour la compta).
  ⚠️ Les 3 diffèrent réellement (aide devis-only, filtre TITRE compta) — préserver chaque
  comportement. Couvert par les tests facturation (sessions 41) — bien les faire tourner.
- Fusion `gen_reference` / `gen_numero_facture` en `gen_numero_sequence(prefix, model, field)`
  (trivial — **Sonnet**). Note : la race condition `max+1` reste (dette connue, hors scope).
- (Optionnel, à arbitrer) petit helper `_check_facture_draft(facture)` pour les 3-4 gardes
  `status != 'draft'`. **Ne pas** introduire de décorateur de permission qui charge l'objet
  (le pattern `get_object_or_404` explicite actuel est plus lisible — écarté).

Fichiers : `core/views.py`.

Risque : moyen-élevé (sauvegarde). Vérif : `test core` (notamment `FactureComptaTests` et
les tests facturation partielle/complète session 41) + test manuel de save sur les 3 types.

---

## Vérification (toutes phases)

- `venv\Scripts\python manage.py test core` vert (156 tests, +tests si nouvelle logique).
- `venv\Scripts\python manage.py check`.
- Test manuel ciblé selon la phase (cf. chaque section).
- Entrée NOTES_DEV (session N+1) + mise à jour du § Dette technique (cocher les items traités :
  context_processor profil, calculs totaux dupliqués, etc.).
- Proposer une mise à jour du manuel `/aide/` si une phase change l'UX visible (Phase 4).

---

## Prompts prêts à coller (une session par phase)

> Ouvrir une fenêtre neuve, régler le modèle indiqué, puis coller le prompt.

### Phase 1 — Sonnet
> Lis NOTES_DEV (état projet) et le plan `docs/plan_ameliorations.md`.
> Exécute la **Phase 1 — Socle backend**. Ajoute dans `core/views.py` les helpers
> `parse_json_request(request)` et `json_error()/json_error_permission()`, et remplace les 22
> blocs `json.loads(request.body)` + les `JsonResponse({'error':…})` dans `views.py` et
> `views_planning.py` (vérifie avant chaque remplacement si le JS client lit `ok:False`).
> Ajoute le context_processor `profil_utilisateur` et enregistre-le ; retire le passage manuel
> `'profil': profil` des `render()` SANS toucher aux `get_profil` utilisés dans la logique.
> Fais tourner `test core` + `check`, puis ajoute l'entrée NOTES_DEV. Ne committe pas sans
> mon feu vert (push = prod).

### Phase 2 — Sonnet
> Lis NOTES_DEV et le plan `docs/plan_ameliorations.md` (Phase 2 — Cohérence UI/CSS).
> Ajoute à `core/static/core/app.css` les classes
> `.empty-state`, `.grid-2/.grid-3/.grid-2-1`, `.sel-narrow/.search-wrap`, `.breadcrumb`,
> `.form-hint`, et remplace les styles inline équivalents dans les listes/formulaires.
> Harmonise `utilisateurs_list.html` sur `page-hd`+`toolbar`+`scroll-y`,
> passe tous les filtres en `onchange="this.form.submit()"`, ajoute `.modal-scroll` aux modales
> longues (clients, equipiers). Harmonise AUSSI les composants génériques de planning.html et
> emargement.html (badges/boutons/cartes/états vides/inline grilles), MAIS ne touche pas au CSS
> spécifique timeline/grille ni à presence_feuille.html. Vérifie visuellement chaque écran.
> Mets à jour NOTES_DEV.

### Phase 3 — Opus
> Lis NOTES_DEV et le plan `docs/plan_ameliorations.md` (Phase 3 — Socle JS partagé).
> Crée `core/static/core/app.js` (chargé dans
> base.html via {% static %}) avec `TreeHelpers` (calcTotal/MO/Mat/fmtV/assignNids/findNode/
> delFromTree), `apiPost(url,payload)` (fetch+CSRF), `debounce`. Branche-le dans devis_detail,
> facture_detail, facture_compta_detail, bibliotheque en supprimant les copies locales.
> ATTENTION : les calc* doivent rester identiques à core/totaux.py (ajoute un commentaire de
> sync des deux côtés) ; ne fusionne assignNids/findNode que si la sémantique est vraiment
> identique. Vérifie sur un devis seed que le total est inchangé avant/après. `test core` + test
> manuel des 4 éditeurs. NOTES_DEV + coche « calculs dupliqués » au § Dette.

### Phase 4 — Opus
> Lis NOTES_DEV et le plan `docs/plan_ameliorations.md` (Phase 4 — Fluidité & sécurité d'usage).
> En t'appuyant sur app.js (Phase 3),
> ajoute `beforeunload` + suivi `dirty` sur devis_detail, facture_compta_detail, bibliotheque
> (calqués sur facture_detail). Unifie l'indicateur de sauvegarde (un seul style, dans app.js).
> AVANT de coder : demande-moi si je veux l'autosave (blur+debounce) sur le devis ou seulement
> le beforeunload + bouton explicite. Vérifie : éditer puis fermer l'onglet déclenche
> l'avertissement ; feedback OK à la sauvegarde et à l'erreur. `test core`. Propose une MAJ du
> manuel /aide/ si l'UX change. NOTES_DEV.

### Phase 5 — Opus (sous-tâche numéros : Sonnet possible)
> Lis NOTES_DEV et le plan `docs/plan_ameliorations.md` (Phase 5 — Propreté backend).
> Fusionne les 3 `create_lignes` (devis / facture /
> facture compta) en une factory paramétrée préservant chaque comportement (aide devis-only,
> quantite_originale, ligne_devis_source_id, filtre TITRE compta). Fusionne aussi
> `gen_reference`/`gen_numero_facture` en `gen_numero_sequence`. Fais tourner TOUTE la suite,
> en particulier FactureComptaTests et les tests facturation session 41. Test manuel de save sur
> les 3 types. NOTES_DEV + coche les items au § Dette. Ne committe pas sans mon feu vert.
