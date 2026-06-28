# Handoff — Refonte Planning, Émargement, Feuille de présence (+ modales)

**Pour :** Claude Code (codebase Django `cb-bretagne`)
**Maquettes de référence (source de vérité visuelle) :**
- `Planning - refonte.dc.html` — planning des équipes, fenêtre complète + zooms (voies, filtre, équipes ponctuelles, édition encadrant).
- `Émargement - refonte.dc.html` — grille hebdomadaire harmonisée + zooms (saisie, prêt).
- `Feuille de présence.dc.html` — fiche A4 mensuelle, reproduction fidèle du papier + logos variables.
- `Modales harmonisées.dc.html` — calendrier commun aux 3 modales + champ « code d'absence » sur l'événement.

**Périmètre :** harmoniser ces 3 écrans avec le reste de l'app (chrome prune, boutons, badges), améliorer lisibilité/densité, et introduire les évolutions UX arbitrées ci-dessous. **Le chrome (topbar + sidebar) ne change pas.**

> ⚠️ **Contrainte transverse — couplage planning ↔ émargement.** Le calcul du temps passé sur chantier (qui nourrit les indicateurs de rentabilité du dashboard insertion) **doit rester intact**. Règle d'or : **une barre du planning = une `Affectation`**, reliée à sa `tranche` de devis ; les `Présence` saisies en émargement restent indexées par `affectation_id`. `pct_consomme` = `jours_realises / nb_jours` et `heures_par_tranche` (cf. `views_planning.py`) ne changent pas. Tout ce qui suit est **présentation + ajouts de modèle ciblés** qui n'altèrent pas cette chaîne.

---

## 0. Décisions verrouillées (ne pas ré-arbitrer)

### Planning
1. **Voies auto-empilées (option A).** Une équipe affiche autant de **voies horizontales** que nécessaire : ses barres ne s'empilent que lorsqu'elles **se chevauchent dans le temps**. Une équipe sans chevauchement reste sur **une** voie. Le calcul des voies est **purement visuel, côté client** (lanes = lignes de grille calculées par détection de recouvrement de dates) — **aucun changement** au modèle `Affectation`/`Presence`.
2. **Lignes plus hautes.** Avec le filtre (moins d'équipes affichées), on peut donner plus de hauteur aux lignes : chaque barre montre **réf · nom (jusqu'à 2 lignes) · avancement**.
3. **Vendredi non travaillé par défaut**, grisé (activable via un événement « jour travaillé » — fonction déjà en place). **Week-ends en colonnes étroites** (resserrées), pour la vue d'ensemble. Lun–Jeu = colonnes pleines.
4. **Filtre par équipe.** Multi-sélection dans le bandeau (boutons à cocher), **mémorisé par utilisateur**. Raccourci **« Mes équipes »**. (Dimension *lieu/ville* possible mais **optionnelle** — l'utilisateur fera le tri qui l'intéresse.)
5. **Trois types de rangée ponctuelle** (en plus des équipes permanentes) :
   - **Équipe temporaire** — montée à partir d'**équipiers prêtés** d'une/plusieurs équipes, durée bornée. Se comporte comme une équipe normale : barres + **grille d'émargement** + heures qui **comptent dans la rentabilité**. Badge « Temp. » + date de fin, archivée après.
   - **Renfort d'un autre service** — **équipe vide** à laquelle on saisit un **montant MO forfaitaire**, **décorrélé de la durée**. **Pas d'émargement**, mais le forfait **compte dans la rentabilité** du devis. Badge « MO forfaitaire ».
   - **Prestataire / sous-traitant** — ressource **externe** (pas d'équipiers). Barre **hachurée grise**, **visuelle seulement** : pas d'émargement, **aucune MO** ; son coût est **budgété dans le budget fourniture** du devis.
6. **Édition par l'encadrant.** Le planning reste l'outil de pilotage de la coordination, mais chaque encadrant peut **ajouter / déplacer un chantier sur ses propres équipes** ; les autres équipes lui sont **en lecture seule** (barres grisées, pas de poignées ni bouton +). Le drapeau `peut_modifier` par ligne **existe déjà** côté serveur — il s'agit de le **rendre lisible**.

### Émargement
7. **Éditable par tous les membres du service insertion 35** (pas seulement l'encadrant de l'équipe). Élargir la permission d'écriture en conséquence.
8. **Codes d'absence inchangés** : `C R M AT A AJ S PMSMP DE DI F`.
9. **Fériés *et* événements du planning posent automatiquement leur code** dans les cellules concernées (le férié le fait déjà ; ajouter la propagation du **code d'événement** — cf. modale §F).
10. **Clôture mensuelle inchangée** (verrou anti-erreur, **déverrouillable**).

### Feuille de présence
11. **Inchangée dans sa structure** : reproduction fidèle du document papier (mêmes blocs, mêmes colonnes), **imprimée puis signée** (émargement salarié + ETI). Sobre, police document, A4 paysage.
12. **Logos de financeurs variables** en bas à droite selon `equipe.financeurs`.

### Modales
13. **Un calendrier de plage commun** aux 3 modales (Assigner un chantier, Prêt d'équipier, Formation/événement) — extraire le mini-calendrier dupliqué, **remplacer les champs date natifs** de la modale événement. Sélection de plage **turquoise**, jours déjà pris en **ambre**, « aujourd'hui » = point prune, **demi-journées** via segmenté Matin/Après-midi.

---

## 1. `core/templates/core/planning.html`

**Intention :** passer d'un rail unique par équipe à des **voies empilées**, harmoniser le bandeau, ajouter le filtre et les rangées ponctuelles. La logique d'affectation, drag&drop, événements, calcul `pct_consomme` reste en place.

**Changements (par intention) :**
- **Voies (lanes).** Pour chaque équipe, calculer côté serveur (ou JS au rendu) un **index de voie** par affectation : algorithme d'« interval partitioning » sur `[date_debut, date_fin]` (demi-journées) — la 1ʳᵉ voie libre qui ne chevauche pas. La hauteur de la ligne équipe = `nb_voies × hauteur_voie`. Les barres conservent leur positionnement colonne existant (`col_debut`/`col_fin_excl`) ; on ajoute juste `grid-row: <voie>`.
- **Hauteur de barre** augmentée ; la barre affiche réf + nom (clamp 2 lignes) + barre d'avancement `pct_consomme` (inchangé).
- **Vendredi grisé** par défaut (déjà non ouvré) + **week-ends en colonnes étroites** : conserver le modèle demi-journées Lun–Ven + Sam/Dim fins déjà présent ; s'assurer que Ven est visuellement « non travaillé » tant qu'aucun événement `travaille=True` ne l'active.
- **Bandeau (page-hd) prune** harmonisé ; toolbar : nav ±1 sem / Aujourd'hui / saut de mois / zoom + **nouveau bouton filtre « Équipes »** + « Assigner un chantier » (prune) + « Événement ».
- **Filtre par équipe** : popover multi-sélection (cf. maquette), avec « Mes équipes » et « Tout / Aucun ». **Persistance par utilisateur** (préférence en base ou `localStorage` côté client — préférer une **préférence serveur** pour suivre l'utilisateur entre postes). Filtrer les lignes rendues.
- **Rangées ponctuelles** (cf. §3 modèle) : mêmes `tl-row`, avec avatar/badge distincts :
  - équipe temporaire → avatar pointillé prune, badge « Temp. », `enc` = « n équipiers prêtés · jusqu'au jj/mm » ;
  - renfort autre service → avatar ambre, badge « MO forfaitaire » ; barre montrant le **montant** (€) au lieu d'un % ;
  - prestataire → avatar gris (icône outil), badge « Prestataire », **barre hachurée grise** (`.bar.prest`), pas de poignées.
- **Édition encadrant** : pour les équipes dont `peut_modifier` est faux, retirer poignées/drag/bouton + et **griser** la rangée (libellé + barres atténuées, cadenas).

**Résultat visible attendu :** cf. maquette « Écran cible · fenêtre complète » — voies empilées (AQ St Malo & Brico Brest sur 2 voies, ARA Rennes sur 1), vendredis grisés, week-ends étroits, bande « aujourd'hui » turquoise, filtre Équipes, et les 3 rangées ponctuelles en bas.

---

## 2. `core/templates/core/emargement.html`

**Intention :** harmoniser et clarifier les états ; ouvrir l'écriture au service insertion ; refléter les codes d'événements.

**Changements (par intention) :**
- **Bandeau prune** harmonisé (sélecteur équipe, nav semaine, + Chantier).
- **Permission d'écriture** : autoriser **tout membre du service insertion (35)**, pas seulement l'encadrant de l'équipe. Adapter le test `peut_modifier` de la vue.
- **Liseré chantier** en haut de cellule (couleur de l'affectation) conservé ; **codes** stylés (congé turquoise, maladie rouge, autres ambre) ; **off** (vendredi/non ouvré) grisé ; **away** (emprunté hors plage) hachuré.
- **Fériés + événements → code auto** : les cellules couvertes par un événement portant un `code_absence` (cf. §F) affichent ce code automatiquement (comme les fériés aujourd'hui), en lecture (modifiable si besoin).
- **Prêt d'équipier** : geste glisser-déposer conservé ; la modale de prêt utilise désormais le **calendrier commun** (cf. §E).
- **Rangées ponctuelles** : l'**équipe temporaire** (équipiers prêtés) a sa grille d'émargement normale ; **renfort** et **prestataire** n'apparaissent **pas** en émargement.
- **Clôture** : comportement actuel conservé (verrou déverrouillable).

**Résultat visible attendu :** cf. maquette « Émargement — AQ St Malo, semaine 11 » : panneau équipiers, grille M/A colorée, ligne empruntée (liseré ambre + cases hachurées hors plage), légende des codes avec mention « fériés et événements posent leur code automatiquement ».

---

## 3. `core/models.py` (+ migration) — rangées ponctuelles & code d'événement

**Intention :** supporter les 3 types de rangée et la propagation de code, sans toucher à la chaîne de rentabilité existante.

**Changements (par intention) :**
- **Type d'équipe / rangée.** Sur `Equipe` (ou un nouveau modèle léger d'affectation-rangée), ajouter un **type** : `permanente` (défaut) · `temporaire` · `renfort` · `prestataire`. Pour `temporaire` : date de fin + lien vers les **prêts** d'équipiers existants (réutiliser le mécanisme de prêt). Pour `temporaire`, **archivage auto** après la date de fin.
- **MO forfaitaire (renfort).** Champ **`mo_forfait`** (Decimal, €) sur l'affectation de renfort, **décorrélé de la durée**. À intégrer au **MO consommé** du devis **en plus** des heures pointées (le dashboard insertion l'agrège ; ne pas le faire transiter par des `Presence` fictives).
- **Prestataire.** Pas de MO, **pas de présences**. Son coût relève du **budget fourniture** du devis (suivi compta existant) — la rangée planning est **informative**. Prévoir au minimum un libellé + plage de dates pour la barre.
- **Code d'absence d'événement.** Sur `Evenement`, ajouter **`code_absence`** (choix parmi les codes, ou vide). Quand l'événement couvre une équipe/des jours, l'émargement de ces jours **prend ce code** (générer/мaj `Presence` avec `code`, `heures=0`, comme les fériés) ou l'afficher dynamiquement — aligner sur le mécanisme férié actuel.
- **Couleur/lieu équipe (optionnel)** si on veut la dimension lieu du filtre : champ `lieu`/`ville` sur `Equipe` pour le défaut encadrant.
- Générer les **migrations**.

---

## 4. `core/templates/core/presence_feuille.html` — feuille A4

**Intention :** **ne pas modifier la structure** (fidélité au papier) ; seul ajout : rendre les **logos financeurs variables** et soigner l'impression.

**Changements (par intention) :**
- Conserver l'agencement exact (en-tête chantier/ETI/mois, ligne équipier, tableau « Mois précédent / Dernière semaine » + semaines du mois, lignes M/A, Émargement Salarié, Chantier, Observation, Émargement ETI, légende).
- **Logos de financeurs** en bas à droite : itérer sur `equipe.financeurs` et afficher `financeur.logo`. **À ajouter au modèle** : un champ **`logo = ImageField(upload_to="financeurs/")`** sur `Financeur` (aujourd'hui le modèle existe mais **sans image**), pour que les logos soient **téléversables depuis la page admin** (enregistrer le champ dans `admin.py`, formats PNG/SVG). Fallback : si pas de logo, afficher le **nom** du financeur dans un cadre (comme la version actuelle). **Hauteur fixe ~30 px** pour garder la fiche sur **une page** A4 paysage.
- Vérifier l'**impression** : `@page size:A4 landscape`, masquer chrome/actions, 1 fiche par équipier (saut de page).

**Résultat visible attendu :** cf. maquette « Feuille de présence » + son zoom « logos selon les financements » (jeux de logos différents par équipe).

---

## 5. Modales — `planning.html` & `emargement.html`

**Intention :** unifier les 3 modales sur **un seul composant calendrier de plage**, et enrichir la modale événement.

### E. Calendrier de plage commun
- Extraire le mini-calendrier (aujourd'hui dupliqué entre `#aff-cal-grid` et `#cal-grid`) en **un composant réutilisable** (JS + styles communs dans `app.css`).
- **Remplacer les champs `<input type="date">`** de la modale événement par ce calendrier.
- Conventions visuelles (cf. maquette) : **plage en turquoise** (bornes pleines, intérieur clair), **jours déjà pris en ambre**, **aujourd'hui** = point prune, navigation mois `‹ ›`, **demi-journées** via segmenté **Matin / Après-midi** (début, et fin selon la modale).
- Même coquille de modale : titre **prune**, sous-titre gris, boutons **Annuler / Enregistrer (turquoise)**.

### F. Modale « Formation / événement »
- Conserver Type / Créneau / Équipes concernées / Jour travaillé / Décale les chantiers.
- **Nouveau champ « Code d'absence attribué »** (select : `F`, code formation, `S`, … ou « aucun »). À l'enregistrement, le code se **reporte automatiquement** dans l'émargement des équipes concernées sur les jours couverts (cf. §3 `code_absence`).

**Résultat visible attendu :** cf. maquette « Modales harmonisées » — calendrier identique dans les 3 fenêtres, champ « code d'absence » mis en avant sur l'événement.

---

## 6. Points transverses / garde-fous

- **Ne pas casser** : modèle `Affectation`/`Presence`, calculs `pct_consomme` / `heures_par_tranche`, drag&drop, redimensionnement, événements, totaux. Les voies sont **uniquement** une couche de positionnement vertical.
- **Rentabilité** : les indicateurs vivent sur le **dashboard insertion** (autre chantier). Ici, veiller seulement à ce que **toutes les sources de MO consommé** soient bien rattachées au devis : heures pointées (équipes permanentes & temporaires) **+** `mo_forfait` (renfort). Le prestataire **n'entre pas** dans la MO.
- **Permissions** : planning → écriture sur **mes équipes** (encadrant) / toutes (coordination) ; émargement → **service insertion 35**. Deux portées distinctes, à ne pas confondre.
- **Persistance filtre** : par utilisateur, idéalement côté serveur.
- **Test rapide** : ouvrir le planning avec 2 chantiers concurrents sur une équipe (→ 2 voies, pas de chevauchement) ; filtrer pour ne garder que ses équipes ; créer une équipe temporaire (prêts), un renfort (MO forfait), un prestataire ; poser un événement « Formation » avec code → vérifier le report dans l'émargement ; imprimer une feuille de présence avec les bons logos.
