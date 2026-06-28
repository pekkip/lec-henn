# Handoff — Refonte des éditeurs (devis & facture)

**Pour :** Claude Code (codebase Django `cb-bretagne`)
**Périmètre :** réorganiser le **haut** des deux éditeurs (`devis_detail.html` et `facture_detail.html`) pour plus de lisibilité et les rendre **cohérents entre eux**. La refonte des listes est déjà implémentée et **hors périmètre** ici.

**On ne touche PAS** à la logique métier : arbre des lignes, calculs de totaux, drag-and-drop, progression par titre, acomptes, bibliothèque, aides/financements, endpoints de sauvegarde. Ce sont uniquement des changements de **structure et de présentation** du cadre autour de l'éditeur.

**Maquettes de référence (source de vérité visuelle) :**
- `Éditeur devis - fenêtre complète.dc.html` — devis, fenêtre entière (état cible).
- `Éditeur devis - organisation.dc.html` — devis, Avant/Après de la zone haute (montre les 3 corrections de structure).
- `Éditeur facture - fenêtre complète.dc.html` — facture, état actuel **annoté** (les 5 frictions).
- `Éditeur facture - Après.dc.html` — facture, état cible.

**Ordre de travail recommandé :** A (classes partagées dans `app.css`) → B (`devis_detail.html`) → C (`facture_detail.html`) → D (transverse).

---

## A. `core/static/core/app.css` — classes partagées des éditeurs (optionnel mais recommandé)

**Intention :** les deux éditeurs réutilisent désormais les mêmes briques de présentation. Les définir **une fois** dans `app.css` (plutôt que dupliquées dans chaque `extra_css`) garantit qu'ils restent identiques. Les classes spécifiques à un seul éditeur (arbre, progression, acomptes…) restent dans leur template.

**Changements (par intention) :**
- **Barre contexte** (`.ctx-bar` + `.ctx-ref` / `.ctx-f` / `.ctx-lbl` / `.ctx-val` / `.ctx-sep`) : bande blanche sous les onglets, qui affiche l'identité + le contexte de l'élément en cours. Libellés en micro-capitales grises au-dessus de valeurs compactes ; séparateurs verticaux fins.
- **Zone d'outils** (`.toolzone` + `.toolrow` + `.toolrow-lbl`) : bande **gris clair** (`--gray-lt`) qui regroupe les barres d'outils, visuellement détachée du contexte blanc au-dessus et des données en dessous. Chaque rangée a une micro-étiquette à gauche (« Ajouter », « Format », « Objet »).
- **Indicateur « non enregistré »** : petit point ambre + texte `Non enregistré`, à afficher à côté du bouton d'enregistrement **quand l'état `dirty` est vrai** (le flag existe déjà en JS dans les deux éditeurs).
- **Onglets prune** : aligner les onglets de `facture_detail` sur ceux de `devis_detail` (fond prune, onglet actif blanc à filet turquoise). Aujourd'hui ils sont blancs côté facture → incohérence.

**Résultat visible attendu :** les deux éditeurs partagent la même grammaire — onglets prune, une barre contexte blanche, une zone d'outils grise, le même indicateur de sauvegarde.

---

## B. `core/templates/core/devis_detail.html` — onglet Édition

**Intention :** réorganiser la pile haute de l'onglet Édition. Voir `Éditeur devis - organisation.dc.html` (Avant/Après).

**Changements (par intention) :**
- **Barre contexte détachée** (remplace `.editor-meta`) : réf devis · client · chantier · date · taux MO. **Le badge de statut passe à droite** de la barre.
- **Supprimer le bouton « Modifier l'en-tête »** : l'onglet « En-tête » fait déjà le travail. **Pas de lien de remplacement** — on retire purement.
- **Regrouper les outils** dans une `.toolzone` grise à deux rangées :
  - rangée **« Ajouter »** : Titre · Forfait MO · Forfait MTX · Ouvrage · Composite · Saut de page, puis à droite Aide CBB · Financements.
  - rangée **« Format »** : G/I/S, annuler/rétablir, taille, couleur, listes, effacer la mise en forme.
- **Boutons d'ajout raccourcis** pour tenir sur une ligne : « Ouvrage simple » → **« Ouvrage »**, « Ouvrage composite » → **« Composite »**, « Aide travaux CBB » → **« Aide CBB »**, « Financements organismes » → **« Financements »** (icônes conservées, libellé complet en `title`).
- **La barre « Ajouter » doit rester fixe au défilement** : aujourd'hui elle est *dans* la zone scrollable (`.editor-body`), donc elle disparaît quand on descend (seul l'en-tête de colonnes est `sticky`). La placer dans la `.toolzone` fixe, au-dessus de la zone qui défile.
- **En-tête de colonnes juste au-dessus des lignes** : déplacer la ligne des noms de colonnes (`.col-hdr`) **sous** la zone d'outils, directement au-dessus de l'arbre — plus au-dessus des boutons d'ajout. La garder `sticky` en tête de la zone scrollable.
- **Pied** : renommer « Sauvegarder » → **« Enregistrer les lignes »** (et l'onglet En-tête → « Enregistrer l'en-tête ») pour lever l'ambiguïté des deux sauvegardes. Ajouter l'**indicateur « non enregistré »** quand `dirty`.

**Résultat visible attendu :** de haut en bas — onglets prune › barre contexte (badge à droite) › zone d'outils grise (Ajouter + Format) › en-tête de colonnes › arbre des lignes (défile, la barre Ajouter reste visible) › pied avec indicateur de sauvegarde et bouton « Enregistrer les lignes ».

---

## C. `core/templates/core/facture_detail.html`

**Intention :** aligner l'éditeur de facture sur celui du devis et désempiler le haut. Voir `Éditeur facture - fenêtre complète.dc.html` (frictions annotées) et `Éditeur facture - Après.dc.html` (cible).

**Changements (par intention) :**
- **Onglets prune** (comme le devis) au lieu de blancs. Onglets = navigation uniquement : « ← Devis DEV-… », « Facture FAC-… » (actif), « Aperçu ».
- **Supprimer la navigation en double** : le fil d'Ariane répété dans la topbar et l'**Aperçu en triple** disparaissent. Aperçu n'apparaît plus qu'**une fois** (dans les onglets).
- **Barre contexte** : état (badges) · client · chantier · échéance. **Ne pas y remettre la réf facture ni le n° de devis** (déjà dans les onglets). **Badges à droite.** L'info propre à la facture qui n'est nulle part ailleurs (ex. « Acompte 1/2 ») peut y figurer.
- **Regrouper Format + Objet** dans une `.toolzone` grise, **Objet au-dessus de Format** : rangée « Objet » (le champ objet/commentaire qui apparaît sur le PDF) puis rangée « Format » (G/I/S/barré). Supprime les deux bandes blanches empilées actuelles (`.fmt-bar` + `.notes-bar`).
- **En-tête de colonnes** : renommer la colonne **« Devis » → « Qté devis »** (ambiguïté quantité/montant) et **élargir légèrement cette colonne** pour que le libellé tienne sur une ligne **sans casser l'alignement** avec les cellules de données (élargir l'en-tête **et** la cellule `.nd-ref` de la même valeur).
- **Remonter « Acomptes versés » au-dessus du pied** : aujourd'hui cette section est rendue **après** le pied (totaux + bouton). La placer **avant** le pied (bande ambre, juste au-dessus des totaux).
- **Pied** : ajouter l'**indicateur « non enregistré »** (flag `dirty` déjà présent) à côté du bouton « Enregistrer ».

**Résultat visible attendu :** onglets prune (nav seule) › barre contexte (badges à droite, sans réf dupliquée) › zone d'outils grise (Objet puis Format) › en-tête de colonnes (« Qté devis » aligné) › lignes avec progression par titre › **acomptes** › pied avec indicateur + « Enregistrer ».

---

## D. Points transverses

- **Navigation clavier dans les quantités** (les deux éditeurs) : `Entrée` / `Tab` passe à la cellule quantité de la ligne suivante (et `Maj+Tab` à la précédente) pour une saisie rapide sans souris. Amélioration de confort, pas de changement visuel.
- **Cohérence** : à la fin, les deux éditeurs doivent être superposables (mêmes onglets, même barre contexte, même zone d'outils, même pied). Si une classe diverge, la promouvoir dans `app.css` (cf. section A).
- **Ne rien changer** au comportement de l'arbre, aux calculs de totaux, à la progression par titre, au drag-and-drop, ni aux endpoints de sauvegarde. Le périmètre est la **présentation du cadre** autour de l'éditeur.
- **Test rapide** : ouvrir un devis puis une facture → vérifier que les deux se ressemblent ; faire défiler les lignes (barre Ajouter fixe côté devis, en-tête de colonnes collant) ; modifier une valeur → l'indicateur « non enregistré » apparaît ; vérifier que l'Aperçu n'est présent qu'une fois côté facture et que les acomptes sont au-dessus du pied.
