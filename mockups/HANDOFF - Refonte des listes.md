# Handoff — Refonte du gabarit unique des listes

**Pour :** Claude Code (codebase Django `cb-bretagne`)
**Maquette de référence (source de vérité visuelle) :** `Listes harmonisées.dc.html` — ouvre-la pour voir le rendu cible (préférences couleur, liste Devis, liste Factures, zoom Avoirs).
**Périmètre :** harmoniser les 5 listes documentaires — **Devis, Factures, Avoirs, Factures Structure, Appels de convention** — sur un seul gabarit, plus lisible. Le chrome (topbar + sidebar) **ne change pas**. Aucune logique métier (calculs, permissions, statuts) ne change.

---

## 0. Décisions verrouillées (ne pas ré-arbitrer)

- **Lisibilité tableau** : zébrage discret (lignes alternées) + en-tête de tableau **collant** au scroll + hauteurs de ligne / police **identiques sur toutes les listes**.
- **Couleur par auteur** : chaque utilisateur a une couleur. Elle s'affiche en **liseré vertical (3 px) à gauche de chaque ligne** qu'il a créée. Couleur **attribuée automatiquement à la création du compte**, **modifiable par l'utilisateur dans ses préférences**.
- **Palette (14 couleurs)** — les seules valeurs autorisées pour le champ couleur :
  `#67123A` prune · `#C2185B` rose · `#C0392B` rouge · `#D35400` orange · `#F7A600` ambre · `#827717` olive · `#3B6D11` vert · `#00AA8D` turquoise · `#0097A7` cyan · `#185FA5` bleu · `#3949AB` indigo · `#5B3EA5` violet · `#795548` marron · `#546E7A` ardoise.
- **Navigation dans une ligne** :
  - Clic **n'importe où sur la ligne** → ouvre le **détail propre** de l'élément de la ligne (la facture ouvre la facture, l'avoir ouvre l'avoir).
  - Clic sur la **référence d'un objet lié** (ex. colonne « Devis » d'une facture, « Facture d'origine » d'un avoir) → ouvre **l'objet lié**. Cette référence est un vrai lien souligné ; il **doit** porter `event.stopPropagation()` (ou être un `<a>` qui stoppe la propagation) pour ne pas déclencher le clic de la ligne.
  - **Plus d'icône `↗` de navigation croisée** : la référence textuelle la remplace.
- **Actions de ligne** (icônes dupliquer / supprimer / valider / aperçu…) : **estompées par défaut, pleinement visibles au survol de la ligne**. Listes consultées **sur PC uniquement** — pas de contrainte tactile.
- **Filtres** : **chaque** liste a une barre d'outils cohérente (recherche + filtres pertinents + « Filtrer » + « Réinitialiser »), avec des **tailles de bouton identiques** (`.btn`, pas un mélange `.btn`/`.btn-sm`).

---

## 1. Ordre de travail recommandé

1. `core/static/core/app.css` — nouvelles classes + ajustements (rien de cassant, additif).
2. `core/models.py` (+ migration) — champ couleur sur le profil + couleur auto à la création.
3. `core/templates/core/profil.html` — sélecteur de couleur dans les préférences.
4. Les 5 templates de liste — appliquer le gabarit.
5. Vérif transverse : aucune régression sur les pages détail / formulaires (les classes existantes ne sont pas renommées).

---

## 2. `core/static/core/app.css`

**Intention :** ajouter les briques CSS du nouveau gabarit **sans renommer** l'existant. Tout est additif ; les classes actuelles (`.table`, `.badge`, `.toolbar`, `.page-hd`, `.ico-btn`, `.mono`…) restent valides.

**Changements (par intention) :**
- **En-tête de tableau collant** : dans les zones `.scroll-y`, les `th` restent visibles en haut quand le corps défile (sticky), avec un filet bas pour les détacher du contenu.
- **Hauteur de ligne + police uniformes** : toutes les cellules de tableau dans `.scroll-y` adoptent la **même** hauteur (padding vertical ≈ 12 px) et la **même** taille de police (13 px). Cible = le confort actuel de la liste Factures, un peu plus aéré que Devis/Avoirs aujourd'hui.
- **Tableau « par auteur »** (nouvelle classe, ex. `.tbl-author` à poser sur le `<table>` des listes) :
  - zébrage : lignes paires sur fond chaud très discret (`#FAF8F6`), survol de ligne légèrement teinté prune (`#F5EEF1`), **pas** de filet entre les lignes (le zébrage suffit) ;
  - **liseré auteur** : barre verticale de 3 px (coins arrondis, légèrement encartée haut/bas) à gauche de la **première cellule** de chaque ligne, dont la couleur vient d'une variable CSS `--rail` posée sur le `<tr>`. Prévoir un retrait gauche (`padding-left`) sur la 1ʳᵉ colonne (corps + en-tête) pour laisser la place au liseré.
- **Référence d'objet lié cliquable** (nouvelle classe, ex. `.cell-link` à combiner avec `.cell-ref`) : même rendu mono que `.cell-ref` mais **souligné discrètement** (filet prune à ~35 % d'opacité, offset 2 px), souligné franc + couleur prune foncée au survol, curseur main.
- **Actions au survol** : les `.ico-btn` d'une cellule d'actions sont à faible opacité (~0,4) au repos et passent à pleine opacité au survol de la ligne. Garder l'alignement à droite + `white-space:nowrap`.
- **Nuancier de préférences** (pour `profil.html`) : pastilles carrées arrondies cliquables (~30 px), bord blanc + fin contour gris ; état sélectionné = anneau gris foncé + coche blanche centrée (ombre portée pour le contraste sur les couleurs claires).

**Résultat visible attendu :**
- Au scroll d'une liste longue, la ligne d'en-tête reste affichée.
- Toutes les listes ont des lignes à la **même hauteur**.
- Chaque ligne porte un **trait coloré à gauche** = couleur de son auteur.
- Une ligne sur deux a un fond très légèrement plus chaud ; le survol tinte la ligne en rosé prune très pâle.
- Les références d'objets liés apparaissent **soulignées** ; les icônes d'action n'apparaissent nettement qu'au survol.

---

## 3. `core/models.py` (+ migration)

**Intention :** stocker une couleur par utilisateur et en attribuer une automatiquement à la création.

**Changements (par intention) :**
- Ajouter un champ **couleur** sur le modèle de profil utilisateur (`Profil`) : une chaîne hex limitée aux 14 valeurs de la palette (idéalement via `choices` pour cadrer les valeurs). Valeur par défaut = une couleur de la palette.
- À la **création** d'un profil (signal `post_save` sur le user, ou override de la création de profil existante) : assigner une couleur **automatiquement**. Stratégie souhaitée : prendre la couleur de la palette **la moins utilisée** parmi les utilisateurs existants (répartition équilibrée), à défaut une rotation simple sur l'ordre de la palette.
- Prévoir un **fallback** : si un ancien profil n'a pas de couleur, considérer une couleur neutre par défaut (ex. ardoise `#546E7A`) côté template, pour ne jamais afficher de liseré vide.
- Générer la **migration** correspondante.

**Résultat visible attendu :** chaque utilisateur (existant après data-migration ou nouveau) a une couleur exploitable par les listes et l'écran préférences.

---

## 4. `core/templates/core/profil.html` — préférences

**Intention :** permettre à l'utilisateur de choisir/changer sa couleur. Voir la carte « Mes préférences · ma couleur » de la maquette.

**Changements (par intention) :**
- Ajouter une section **« Couleur de mes lignes »** dans les préférences existantes.
- Afficher le **nuancier** des 14 couleurs (pastilles), la couleur courante de l'utilisateur **pré-sélectionnée** (anneau + coche).
- Sélection → enregistrement de la couleur sur le profil (form POST classique, ou champ inclus dans le formulaire de profil existant). Pas besoin d'AJAX.
- Petit texte d'aide : couleur attribuée à la création, modifiable ici.

**Résultat visible attendu :**
- Une grille de 14 pastilles colorées ; celle de l'utilisateur est entourée et cochée.
- Après enregistrement, le liseré de ses lignes dans toutes les listes prend la nouvelle couleur.

---

## 5. `core/templates/core/devis_list.html`

**Intention :** c'est la liste la plus complète — elle sert de **référence de structure** pour les autres. La toolbar riche existante est déjà presque conforme.

**Changements (par intention) :**
- Poser la classe **`.tbl-author`** sur le `<table>`.
- Sur chaque `<tr>` : exposer la couleur de l'auteur via `style="--rail: {{ d.created_by.profil.couleur }}"` (avec fallback couleur neutre).
- Conserver la ligne **entièrement cliquable** vers le détail du devis (déjà en place).
- Colonne d'actions (dupliquer / supprimer) : déjà avec `event.stopPropagation()` — la **conserver** ; ces icônes deviennent « au survol » via le CSS, pas de markup à changer.
- Remplacer le badge d'équipe **inline** (`style="…prune-lt…"`) par la classe existante **`.badge .b-prune`**.
- Vérifier que la toolbar utilise des boutons de **taille homogène** (`.btn`, pas `.btn-sm`).

**Résultat visible attendu :** liste Devis identique à la maquette « Écran · Devis » — liseré auteur, zébrage, en-tête collant, badge équipe en pilule prune, actions au survol.

---

## 6. `core/templates/core/factures_list.html`

**Intention :** aligner sur le gabarit + corriger les manques (pas de toolbar, pas d'action d'en-tête, navigation croisée par icône).

**Changements (par intention) :**
- Poser **`.tbl-author`** sur le `<table>` + `--rail` par auteur sur chaque `<tr>`.
- **Ligne cliquable** → ouvre le **détail de la facture** (`facture-detail`). Aujourd'hui la ligne n'est pas cliquable ; la rendre cliquable comme Devis.
- **Colonne « Devis »** : transformer la référence du devis en **lien souligné** (`.cell-ref.cell-link`) vers `devis-detail`, **avec `event.stopPropagation()`**. Supprimer l'icône `↗ ti-external-link` de la colonne d'actions (redondante).
- **Barre d'outils** : ajouter une toolbar cohérente — recherche (référence / destinataire / objet) + filtre auteur + filtre statut + « Filtrer » + « Réinitialiser ». (Le filtre auteur seul actuel est insuffisant.)
- **En-tête de page** : ajouter une action à droite pour équilibrer (ex. **« Exporter »** en `.btn`). Pas de « Nouvelle facture » (les factures naissent d'un devis) — d'où une action secondaire plutôt que `.btn-prune`.
- Regrouper les badges secondaires (Bypass, Avoir) dans un conteneur **`.badges`** (flex + gap) au lieu des `margin-left:4px` inline.
- Conserver les actions de statut contextuelles (valider / marquer envoyée / marquer payée / créer un avoir) ; elles deviennent « au survol » via le CSS.

**Résultat visible attendu :** liste Factures identique à la maquette « Écran · Factures » — référence Devis **soulignée cliquable** (plus d'icône `↗`), toolbar complète, action « Exporter » dans l'en-tête, badges groupés proprement.

---

## 7. `core/templates/core/avoirs_list.html`

**Intention :** la liste la plus pauvre aujourd'hui (ni action, ni toolbar) — l'aligner. Voir le « Zoom · Avoirs » de la maquette.

**Changements (par intention) :**
- Poser **`.tbl-author`** + `--rail` par auteur.
- **Renommer la colonne « Coupable » en « Auteur »** (cohérence avec les autres listes).
- **Ligne cliquable** → ouvre le **détail de l'avoir** (`compta-facture-detail`).
- **Colonne « Facture d'origine »** : référence en **lien souligné** (`.cell-ref.cell-link`) vers la facture d'origine, **avec `event.stopPropagation()`**. Retirer l'icône `↗` correspondante.
- **Barre d'outils** : ajouter recherche (référence / client / facture d'origine) + filtre auteur + « Filtrer » + « Réinitialiser ».
- **En-tête de page** : ajouter une action **« Exporter »** (`.btn`) pour l'équilibre.
- Conserver l'action **aperçu** (`ti-eye`) ; elle passe « au survol ».

**Résultat visible attendu :** liste Avoirs comme dans le zoom — colonne « Auteur » (plus « Coupable »), facture d'origine **soulignée cliquable**, toolbar + bouton Exporter, liserés auteur.

---

## 8. `core/templates/core/facture_compta_list.html` (Factures Structure **et** Appels de convention)

**Intention :** ce template sert les deux écrans (`type_doc == 'structure'` / `'appel'`). Une seule passe couvre les deux listes.

**Changements (par intention) :**
- Poser **`.tbl-author`** + `--rail` par auteur.
- **Ligne cliquable** → détail du document (`compta-facture-detail`).
- Si une **référence d'objet lié** est affichée, appliquer le même motif `.cell-ref.cell-link` + `event.stopPropagation()` ; retirer toute icône `↗`.
- **Barre d'outils** : ajouter recherche + filtre auteur (+ statut si pertinent) + « Filtrer » + « Réinitialiser » — aujourd'hui absente.
- Conserver l'action d'en-tête existante (« Nouvelle facture » / « Nouvel appel » en `.btn-prune`).
- Badges secondaires (Bypass / Avoir) regroupés dans **`.badges`**.

**Résultat visible attendu :** les deux listes compta adoptent le même gabarit (liseré auteur, zébrage, toolbar, en-tête collant), avec leur bouton de création respectif conservé.

---

## 9. Points transverses / garde-fous

- **Ne pas renommer** les classes existantes ni toucher aux pages détail, formulaires, planning, émargement, relevé, dashboard. Le travail est circonscrit aux 5 listes + app.css + profil + model.
- **`clients.html`** est aussi une liste : si tu veux, applique le même gabarit (`.tbl-author`, toolbar déjà presque conforme) — **optionnel**, non bloquant.
- **Fallback couleur** systématique dans les templates : `{{ d.created_by.profil.couleur|default:'#546E7A' }}` (ou équivalent) pour ne jamais produire un `--rail` vide.
- **`event.stopPropagation()`** : indispensable sur **tout** lien interne à une ligne cliquable (références liées **et** boutons d'action). C'est déjà le motif utilisé dans la colonne d'actions de `devis_list.html` aujourd'hui — le généraliser.
- **Accessibilité** : le liseré couleur est un **repère secondaire** (qui a créé la ligne) ; l'information de statut reste portée par les badges texte, pas par la couleur du liseré. Ne pas encoder de sens « statut » dans le liseré.
- **Test rapide** : ouvrir chaque liste, scroller (en-tête collant), survoler une ligne (actions + teinte), cliquer une ligne (détail propre), cliquer une référence liée (objet lié, sans déclencher la ligne), changer sa couleur dans le profil et revérifier les liserés.
