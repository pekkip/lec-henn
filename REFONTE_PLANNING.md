# Refonte Planning, Émargement & Insertion — CB Bretagne

> Runbook pas-à-pas pour implémenter le handoff `mockups/HANDOFF - Refonte planning & insertion.md`.
> Source de vérité visuelle : `mockups/*.dc.html` (`Planning - refonte`, `Émargement - refonte`,
> `Feuille de présence`, `Modales harmonisées`). Les 3 autres handoffs (UI, listes, éditeurs) sont
> **déjà implémentés**.
> Conçu pour être suivi **phase par phase, une session par phase** (contexte léger) — cocher les ✅
> au fur et à mesure, comme `DEPLOY_OVH.md` l'a fait pour la migration OVH.

## État actuel

- [x] **Phase 1 — Planning : présentation** (voies empilées, filtre équipes, édition lisible) — _Opus_
- [ ] **Phase 2 — Émargement : permissions & codes d'événements** — _Sonnet_
- [ ] **Phase 3 — Rangées ponctuelles** (modèle + migration) — _Opus_
- [ ] **Phase 4 — Feuille logos + calendrier de modale commun** — _Sonnet (4b : Opus conseillé)_

- [x] **Complément — Imputation par demi-journée & couleurs chantiers** (hors phases 1-4) — _Opus_
  Handoff `mockups/HANDOFF - Imputation & couleurs chantiers.md` + maquette `Imputation & couleurs
  chantiers.dc.html`. **Imputation** : la grille d'émargement scinde chaque jour en 2 sous-colonnes
  matin|aprem ; un sélecteur de chantier par demi-journée impute toute l'équipe au bon devis
  (`Presence.affectation_id`, endpoint `presence_reassign`). **Couleurs** : palette de 8 teintes
  anti-collision attribuées par équipe (`couleurs_par_equipe`), surcharge manuelle via icône palette
  (`Affectation.couleur`). Commits `fcb7285` + `4787ad2` (22/06/2026, session 59). _Détails :
  `NOTES_DEV.md` § session 59._

À chaque phase terminée : cocher la case, commit sur `main` (pas de `Co-Authored-By`), mettre à jour
`NOTES_DEV.md`. NB : `git push` ≠ déploiement (deploy manuel SSH OVH, cf. `DEPLOY_OVH.md`).

## À lire avant de commencer (obligatoire)

Ce fichier est un **index/runbook** : il ne remplace ni le handoff (détail des intentions) ni les
maquettes (détail visuel exact : couleurs, états, agencement). Avant de coder une phase, **lire la
section de handoff** correspondante **et ouvrir la maquette** indiquée — la maquette `.dc.html` est
la **source de vérité visuelle**.

1. **Handoff complet** : `mockups/HANDOFF - Refonte planning & insertion.md` (intentions + décisions
   verrouillées §0, garde-fous §6). *Détail des intentions ; ce runbook n'en est qu'un index.*
2. **Environnement dev** : `NOTES_DEV.md` § « Démarrage rapide (dev Windows) » — venv, `migrate`,
   `venv\Scripts\python manage.py test core`, `manage.py check`. (Sans `DATABASE_URL`, base SQLite
   locale ; connexion via `/login/`.)
3. **Maquettes** (`mockups/`, ouvrir dans le navigateur) :

| Maquette `.dc.html` | Écran | Phases | Section handoff |
| --- | --- | --- | --- |
| `Planning - refonte` | Planning | 1, 3 (rendu rangées) | §0 (Planning), §1 |
| `Émargement - refonte` | Émargement | 2, 3 (grille temporaire) | §0 (Émargement), §2 |
| `Feuille de présence` | Feuille A4 | 4a | §0 (Feuille), §4 |
| `Modales harmonisées` | Modales | 4b (+ 2b modale événement) | §5 (E, F) |

> Modèle léger du handoff §3 (rangées ponctuelles + `code_absence`) → couvert par Phases 2b et 3.

## 0. Contexte / décisions actées

- **Contrainte d'or (transverse).** Ne pas casser la chaîne de rentabilité : chaque barre planning
  reste **une** `Affectation` reliée à sa `tranche` (on empile **plusieurs barres visuellement** pour
  une équipe, sans changer le modèle) ; les `Presence` restent indexées par `affectation_id` ;
  `pct_consomme = jours_realises / nb_jours` et `heures_par_tranche` (cf. `views_planning.py`) ne
  changent pas. Le chrome (topbar + sidebar) ne bouge pas.
- **Besoin métier clé (Phase 1).** Afficher **plusieurs lignes pour une même équipe** : cas d'un
  chantier qui se prolonge dans le temps pendant que l'équipe va aussi sur un chantier plus court sur
  la même période → c'est l'objet des **voies empilées**.
- **Permissions de démarrage.** Toute l'équipe insertion (responsable + assistante + encadrants)
  édite **planning ET émargement** ; **RH** édite la **feuille de présence**. Restrictions plus fines
  par équipe possibles plus tard (drapeau `peut_modifier` par ligne gardé comme point d'extension).
- **Logos financeurs.** Ajouter un `ImageField` sur `Financeur` (fallback `logo_cle`, puis nom).

### Fichiers pivots (existant repéré)

| Fichier | Repères |
| --- | --- |
| `core/templates/core/planning.html` (~1677 l.) | grille 12 col/sem, `.tl-row`/`.tl-track`/`.tl-bar`, drag&drop, modales `.modal-wizard` + `.modal-ev`. **Une seule voie par équipe** aujourd'hui. |
| `core/templates/core/emargement.html` | grille `.eg`, cellules `.cell`/`.cinp`, modale prêt `.modal-pret` + mini-cal `.pret-cal`. |
| `core/templates/core/presence_feuille.html` | fiche A4 paysage, `{% for fin in equipe.financeurs.all %}` affiche juste `{{ fin.nom }}`. |
| `core/views_planning.py` | `planning_mois()` (491-773), `emargement_view()` (242-488), `presence_save`/`fiche_presence_save`/`pret_save`, `presence_feuille()`, endpoints affectation/événement. |
| `core/planning_utils.py` | `_half_col_creneau`, `_build_evenement_sets`, `_count_working_days`, `_recalcul_durees_tranche`, `_jours_feries`. |
| `core/models.py` | `Equipe` (50-102), `Financeur` (847, `logo_cle` seul), `Affectation` (955), `Evenement` (1009, **pas** de `code_absence`), `Presence` (1065, `CODE_CHOICES`), `Pret`, `ClotureMois`. |
| `core/permissions.py` | `peut_acceder_planning` (295), `est_encadrant` (314). `Service.module_planning` = insertion. `ProfilUtilisateur.equipes` (M2M) existe → base de « Mes équipes ». |

> ⚠️ Tester après **chaque** phase : `venv\Scripts\python manage.py test core` + `manage.py check`.
> Vérifier que le dashboard insertion (rentabilité) affiche les **mêmes chiffres** qu'avant pour les
> équipes permanentes.

---

## 1. Planning — présentation (aucun changement de modèle) · _Opus_

> **À lire d'abord :** handoff §0 (Planning) + §1 ; ouvrir `mockups/Planning - refonte.dc.html`
> (voies empilées, week-ends étroits, bande « aujourd'hui », filtre Équipes).

**But :** voies empilées + filtre équipes persistant + édition lisible. 100 % présentation +
positionnement vertical. Aligner sur `mockups/Planning - refonte.dc.html`.

### 1a. Voies auto-empilées (interval partitioning)
- Dans `planning_mois()` (construction des `ligne['barres']`, ~624-711) : trier les affectations de
  l'équipe par `date_debut` (+créneau) et assigner un **index de voie** par « première voie libre qui
  ne chevauche pas » sur `[col_debut, col_fin_excl[` (réutilisable tel quel, pas de recalcul de
  dates). Stocker `barre['voie']` et `ligne['nb_voies'] = max(voie)+1`.
- Template : `.tl-track` → `grid-template-rows = 18px (jours) + nb_voies × hauteur_voie`. Chaque
  `.tl-bar` reçoit `grid-row: {{ barre.voie|add:2 }}`. Les `.tl-cell` de fond passent en
  `grid-row: 1 / -1`. Hauteur du `.tl-lbl.team` suit la hauteur de ligne.

> ⚠️ Ne toucher **ni** `col_debut`/`col_fin_excl`, **ni** le drag&drop. Le JS `applyBarUpdate()`
> doit re-router la voie après un move (recalcul de voie côté client après drop, ou reload léger si
> l'empilement change — acceptable, comme aujourd'hui sur certains gestes).

### 1b. Week-ends étroits + vendredi grisé — DÉJÀ IMPLÉMENTÉ (vérif + micro-retouches)
- `.fri-hd/.fri-cell`, `.we-hd/.we-cell` + variable `--cw` existent déjà — **ne pas reconstruire**.
- À faire malgré tout : **comparer le rendu à `mockups/Planning - refonte.dc.html`** et n'appliquer
  que des **micro-retouches CSS** dans `planning.html` *si* ça diverge (largeurs de colonnes week-end,
  teinte du vendredi, vendredi visuellement « non travaillé » tant qu'aucun événement `travaille=True`
  ne l'active — logique `_build_evenement_sets` déjà en place).
- Vérifier que les voies empilées (1a) n'altèrent pas ce rendu.

### 1c. Filtre par équipe (persistant par utilisateur)
- UI : bouton « Équipes » dans la toolbar `page-hd` → popover multi-sélection (checkboxes) avec
  « Mes équipes » et « Tout / Aucun » (cf. maquette). Filtre les `.tl-row` rendues.
- Persistance serveur : champ `planning_filtre_equipes = JSONField(default=list, blank=True)` sur
  `ProfilUtilisateur` (pattern `categories_biblio`) → migration. Endpoint
  `POST /planning/filtre-equipes/` (`views_planning.py` + route `urls.py`). `planning_mois()` lit la
  préférence et pré-coche. « Mes équipes » = `profil.equipes` (déjà existant).

### 1d. Édition lisible (lecture seule visible)
- `ligne['peut_modifier']` existe déjà (masque poignées/`+`/drag). Ajouter le **rendu** « lecture
  seule » : libellé + barres atténués, cadenas sur `.tl-lbl.team`, pas de `.add-btn`. CSS + condition
  template uniquement.
- NB : avec la permission de démarrage (§2a), toute l'équipe insertion peut éditer → aucune ligne
  grisée au lancement. Ce rendu est le point d'extension pour une future restriction par équipe.

**✅ Checklist Phase 1**
- [x] 2 chantiers concurrents sur une équipe → 2 voies, pas de chevauchement. _(test `test_planning_voies_empilees`)_
- [x] Équipe sans chevauchement → reste sur 1 voie. _(test `test_planning_voie_unique_sans_chevauchement`)_
- [x] Filtre « Mes équipes » conservé après rechargement (autre onglet/poste). _(préf serveur `planning_filtre_equipes` + `test_planning_filtre_equipes_persiste`)_
- [x] Lignes non modifiables grisées + cadenas (mécanisme câblé). _(classe `.tl-row.ro` + cadenas, basé sur `peut_modifier` existant — toujours `est_encadrant` en Phase 1)_
- [x] `pct_consomme` + drag&drop inchangés. `test core` + `check` verts. _(189 tests OK ; voies = positionnement vertical uniquement, recalc client après move via `relayoutTrack`)_
- [x] Commit + cocher l'état + NOTES_DEV.

---

## 2. Émargement — permissions & codes d'événements · _Sonnet_

> **À lire d'abord :** handoff §0 (Émargement) + §2 + §3 (`code_absence`) + §5 F (modale événement) ;
> ouvrir `mockups/Émargement - refonte.dc.html` (états cellules, légende « fériés et événements
> posent leur code automatiquement ») et `mockups/Modales harmonisées.dc.html` (champ code d'absence).

**But :** ouvrir l'écriture au service insertion ; propager le code d'un événement dans l'émargement.

### 2a. Permission élargie
- `core/permissions.py` : `peut_modifier_insertion(user)` = admin/responsable **ou** membre du
  service insertion (`profil.service.module_planning`, couvre assistante + encadrants) **ou**
  encadrant d'au moins une équipe.
- **Planning** : `ligne['peut_modifier']` (dans `planning_mois`) → `peut_modifier_insertion(user)`
  pour les équipes insertion (au lieu de la restriction encadrant-par-équipe). Mécanisme par-ligne
  conservé.
- **Émargement** : remplacer `est_encadrant(...)` par `peut_modifier_insertion(...)` dans
  `emargement_view` (`peut_modifier`, l.479), `presence_save` (l.1251/1254) et `pret_save`.
- **Feuille de présence** : `presence_feuille`/`fiche_presence_save` éditables par encadrant **et
  RH** (vérifier que `rh` est bien inclus dans le test et le conserver).

> ⚠️ Le verrou `ClotureMois` reste prioritaire partout.

### 2b. Code d'absence d'événement
- Modèle : `Evenement.code_absence = CharField(max_length=10, blank=True, choices=Presence.CODE_CHOICES)`
  → migration.
- Modale événement (`planning.html`, `.modal-ev`, §F handoff) : select « Code d'absence attribué »
  (les `CODE_CHOICES` + « aucun »). `evenement_save()` lit/écrit `code_absence`.
- Propagation : calquer sur le mécanisme férié (`emargement_view` l.393-399 calcule `special_code`
  'F'/'R' ; template l.309-311 l'affiche). Étendre `special_code` pour qu'un `Evenement` couvrant
  l'équipe/les jours pose son `code_absence` (affichage dynamique, modifiable), **sans** créer de
  `Presence` fictive. Idem `presence_feuille()` (`special_map`).

**✅ Checklist Phase 2**
- [ ] Membre insertion non-encadrant peut saisir une présence + modifier le planning.
- [ ] Mois clôturé reste verrouillé.
- [ ] Événement « Formation » + code `F` → jours couverts affichent `F` (émargement + feuille).
- [ ] Tests d'accès `core/tests.py` ajustés. `test core` + `check` verts.
- [ ] Commit + cocher l'état + NOTES_DEV.

---

## 3. Rangées ponctuelles (modèle + migration) · _Opus_

> **À lire d'abord :** handoff §0 (Planning, décision 5 : les 3 types) + §3 (modèle) + §6 (garde-fous
> rentabilité) ; ouvrir `mockups/Planning - refonte.dc.html` (rangées ponctuelles en bas : équipe
> temporaire, renfort, prestataire — avatars/badges/barre hachurée).

**But :** les 3 types de rangée non permanentes, **sans** perturber la rentabilité. Phase la plus
structurante — après stabilisation des phases 1-2.

### 3a. Modèle
- Sur `Equipe` : `type_rangee = CharField(choices=[permanente|temporaire|renfort|prestataire], default='permanente')`
  + `date_fin_temp` (DateField null), `mo_forfait` (DecimalField null, € — renfort), `archivee`
  (BooleanField). Réutiliser le mécanisme `Pret` pour peupler une **temporaire**. Migration.
- Rester sur `Equipe` (le moins invasif : tout le rendu itère sur les équipes), pas de nouveau modèle.

### 3b. Rentabilité (vigilance)
- **Temporaire** : équipe normale → barres + émargement + heures comptées (via `Presence`/`Affectation`).
- **Renfort** : équipe vide + `mo_forfait` décorrélé de la durée. **Pas d'émargement.** Le forfait
  s'ajoute au MO consommé du devis *en plus* des heures — agrégé côté dashboard insertion, **sans**
  `Presence` fictive. Barre affiche le **montant €** au lieu d'un %.
- **Prestataire** : externe, **aucune MO**, pas de `Presence`. Barre **hachurée grise** (`.bar.prest`),
  informative (libellé + plage). Coût = budget fourniture du devis (compta existante, hors scope).

### 3c. Rendu planning (`planning.html`)
- Mêmes `.tl-row`, avatar/badge distincts : temporaire (avatar pointillé prune, badge « Temp. » +
  date fin) ; renfort (avatar ambre, badge « MO forfaitaire », barre €) ; prestataire (avatar
  gris/outil, badge « Prestataire », `.bar.prest` hachurée, pas de poignées). Archivage auto des
  temporaires après `date_fin_temp`.
- Émargement : seules les **temporaires** ont une grille ; renfort & prestataire **n'apparaissent pas**.

**✅ Checklist Phase 3**
- [ ] Équipe temporaire (prêts) → barres + émargement + heures comptées.
- [ ] Renfort (MO forfait) → barre € sans émargement ; forfait visible côté rentabilité.
- [ ] Prestataire → barre hachurée sans MO ni émargement.
- [ ] `pct_consomme`/`heures_par_tranche` des équipes permanentes **identiques**. `test core` + `check` verts.
- [ ] Commit + cocher l'état + NOTES_DEV + proposer MAJ manuel `/aide/`.

---

## 4. Feuille de présence (logos) + calendrier de modale commun · _Sonnet (4b : Opus conseillé)_

> **À lire d'abord :** handoff §0 (Feuille) + §4 (logos) + §5 E (calendrier commun) ; ouvrir
> `mockups/Feuille de présence.dc.html` (zoom « logos selon les financements ») et
> `mockups/Modales harmonisées.dc.html` (calendrier de plage identique dans les 3 fenêtres).

### 4a. Logos financeurs (`presence_feuille.html` + `models.py` + `admin.py`)
- `Financeur.logo = ImageField(upload_to='financeurs/', blank=True, null=True)` → migration.
  Enregistrer le champ dans `core/admin.py` (upload PNG/SVG depuis l'admin).
- Template : `<img src="{{ fin.logo.url }}">` si `fin.logo`, sinon fallback `logo_cle`, sinon nom dans
  un cadre. **Hauteur fixe ~30 px** pour tenir sur **une** page A4 paysage. Vérifier
  `@page size:A4 landscape`, masquage chrome, saut de page par équipier.

### 4b. Calendrier de plage commun aux 3 modales
- Aujourd'hui dupliqué : `#aff-cal-grid` (modale affectation, `planning.html`) et `#cal-grid`/`.pret-cal`
  (modale prêt, `emargement.html`) ; la modale événement utilise des `<input type="date">` natifs.
- Extraire **un composant calendrier de plage réutilisable** (JS + styles dans
  `core/static/core/app.css`) : plage turquoise (bornes pleines, intérieur clair), jours déjà pris
  en ambre, « aujourd'hui » = point prune, nav mois `‹ ›`, demi-journées via segmenté Matin/Après-midi
  (réutiliser `.cren-grp`). Brancher les 3 modales dessus ; **remplacer les inputs date natifs** de la
  modale événement. Aligner sur `mockups/Modales harmonisées.dc.html`. Coquille modale : titre prune,
  sous-titre gris, boutons Annuler / Enregistrer (turquoise).

**✅ Checklist Phase 4**
- [ ] Feuille avec jeux de logos variables selon `equipe.financeurs` (image sinon nom), 1 page A4 paysage.
- [ ] Les 3 modales partagent le même calendrier ; modale événement sans `input date` natif.
- [ ] `test core` + `check` verts.
- [ ] Commit + cocher l'état + NOTES_DEV + proposer MAJ manuel `/aide/`.

---

## Vérification globale (scénario handoff §6)

Bout en bout : planning avec 2 chantiers concurrents (2 voies) → filtre « Mes équipes » → créer une
équipe temporaire / un renfort / un prestataire → poser un événement « Formation » avec code →
vérifier le report dans l'émargement → imprimer une feuille avec les bons logos. Confirmer que le
dashboard insertion affiche les mêmes chiffres qu'avant pour les équipes permanentes.
