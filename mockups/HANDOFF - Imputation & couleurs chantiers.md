# Handoff — Imputation par demi-journée &amp; couleurs de chantiers

> ✅ **IMPLÉMENTÉ (22/06/2026, session 59 — commits `fcb7285` palette + `4787ad2` imputation).**
> Voir `NOTES_DEV.md` § session 59. Écarts assumés vs ce handoff : (1) CSS des 8 teintes posé dans
> les `<style>` de `planning.html` / `emargement.html` (et non `app.css`) — là où `cha/chb/chc`
> existaient déjà ; (2) **sélecteurs de demi-journée = couleur seule** (pastille) + bande
> « Chantiers de la semaine » enrichie (réf · nom · plage) comme clé de lecture, au lieu du chip à
> libellé tronqué — *décision utilisateur, plus lisible* ; (3) **exception par équipier supprimée**
> (sémantique « toute l'équipe sur un seul chantier par demi-journée ») ; (4) override couleur via
> **icône palette dans la bande émargement** (pas dans la modale d'affectation, pour ne pas charger
> les barres planning). Persistance imputation = `Presence.affectation_id` (option retenue du §2).

**Pour :** Claude Code (codebase Django `cb-bretagne`)
**Maquette de référence :** `Imputation & couleurs chantiers.dc.html`
**Portée :** deux ajouts **ciblés** sur l'émargement / le planning **déjà en place**. Le reste de la refonte est implémenté — **ne pas y toucher**.

Fichiers concernés : `core/views_planning.py` (palette + attribution), `core/static/core/app.css` (classes de couleur), `core/templates/core/emargement.html` (sélecteurs de demi-journée), et le modèle de l'affectation (couleur surchargée optionnelle).

---

## 1. Palette de chantiers — 8 teintes anti-collision

### Constat
`views_planning.py` :
```python
COLORS_AFF = ['cha', 'chb', 'chc', 'cha', 'chb']
aff_color = {aff.pk: COLORS_AFF[aff.tranche.devis_id % len(COLORS_AFF)] for aff in affectations}
```
→ seulement **3 teintes réelles**, cyclées par `devis_id % 5`. Deux chantiers d'une même équipe peuvent recevoir la **même couleur**.

### Cible — 8 classes
Ajouter 5 teintes aux 3 existantes. Valeurs (fond clair / bordure / filet gauche+pastille / texte) :

| Classe | Nom | Filet + pastille | Fond | Bordure | Texte |
|---|---|---|---|---|---|
| `cha` | Turquoise *(DS)* | `#00AA8D` | `#E0F4F0` | `#A9DDD3` | `#066B59` |
| `chb` | Or *(DS)* | `#F7A600` | `#FDF0D6` | `#F0D9A8` | `#8B5E0A` |
| `chc` | Prune *(DS)* | `#67123A` | `#F3E4EC` | `#D9B8C9` | `#4E1529` |
| `chd` | Bleu | `#2F6DB3` | `#E6EFF8` | `#BBD4EE` | `#1B4C86` |
| `che` | Violet | `#6C4AA6` | `#EEE9F5` | `#CFC0E5` | `#4A3175` |
| `chf` | Vert | `#3E8E5A` | `#E4F1E7` | `#BBD9C2` | `#276B40` |
| `chg` | Terracotta | `#B85C2E` | `#F6E7DD` | `#E6C7B2` | `#8A3F1C` |
| `chh` | Ardoise | `#4A6B7C` | `#E8EEF1` | `#C2D2DA` | `#324D5A` |

> Le **rouge** reste réservé aux absences (maladie/AT) — il n'entre **pas** dans la palette chantiers.

### Cible — attribution **par équipe** (plus de doublon visible)
Remplacer le `devis_id % n` global par une attribution **première teinte libre au sein de l'équipe** :

```python
PALETTE = ['cha','chb','chc','chd','che','chf','chg','chh']

def couleurs_par_equipe(affectations_de_l_equipe):
    """affectations triées par date_debut (puis pk pour stabilité)."""
    used = {}          # classe -> aff active la plus récente
    color = {}
    for aff in sorted(affectations_de_l_equipe, key=lambda a: (a.date_debut, a.pk)):
        # surcharge manuelle prioritaire
        if aff.couleur:
            color[aff.pk] = aff.couleur
            used[aff.couleur] = aff
            continue
        # 1re teinte non utilisée par un chantier qui CHEVAUCHE cette affectation
        libre = next((c for c in PALETTE
                      if not _chevauche_couleur(c, aff, color, affectations_de_l_equipe)), None)
        color[aff.pk] = libre or PALETTE[aff.pk % len(PALETTE)]  # secours si >8 simultanés
    return color
```
- La couleur est **stable** : tant que le chantier reste actif, il garde sa teinte.
- « Libre » se juge sur les chantiers qui **se chevauchent dans le temps** (mêmes critères que les voies du planning) ; deux chantiers d'une équipe qui ne se recouvrent jamais peuvent réutiliser une teinte sans gêne.
- Au-delà de 8 chantiers simultanés (improbable), on recycle.

### Modèle
- Ajouter sur l'affectation un champ **`couleur`** (`CharField`, choix = les 8 classes, **vide par défaut**) → permet la **surcharge manuelle** via la pastille de couleur dans la modale d'affectation. Si vide, attribution automatique ci-dessus.
- **Migration** à générer.

### CSS (`app.css`)
Décliner les 8 classes là où `cha/chb/chc` sont déjà utilisées :
- **planning** : `.bar.<c>` (fond/bordure/filet gauche/texte).
- **émargement** : `.<c>::before` (filet 3 px haut de cellule) + `.plan-legend .sw.<c> i` (pastille de légende).
- **sélecteur demi-journée** (cf. §2) : pastille + chip colorés.

---

## 2. Imputation par demi-journée (sélecteur matin / après-midi)

### Constat
Dans `emargement.html`, chaque cellule porte déjà `data-aff-id`, `data-creneau` (M/A) et `cell.color`. Mais la couleur/le chantier d'une demi-journée **découle de l'affectation** couvrant le jour ; il n'y a **pas** de moyen, quand l'équipe a **plusieurs chantiers actifs le même jour**, de choisir *quel* chantier pour le matin vs l'après-midi.

### Cible
Au-dessus de la grille, **scinder l'en-tête de chaque jour en deux sélecteurs** de chantier — un **matin**, un **après-midi** :
- Le sélecteur liste les **chantiers actifs de l'équipe ce jour-là** (affectations couvrant la date), avec leur **pastille de couleur** (palette §1).
- Choisir un chantier **applique** ce chantier (donc `aff_id`) à **toute la colonne demi-journée** : toutes les cellules de cette demi-journée, tous les équipiers, prennent la couleur et **imputent leurs heures** à cette affectation (donc au bon devis).
- **Défaut** : si **un seul** chantier est actif ce jour, les deux demi-journées héritent automatiquement — le sélecteur affiche le chantier sans rien demander. Le choix n'est requis que s'il y a **2 chantiers ou plus** simultanés.
- **Exception par équipier** : un clic sur **une cellule isolée** permet de la réimputer à un autre chantier du jour (cas rare où un seul équipier diverge). La colonne reste le geste principal.

### Données / vue
- Exposer par jour la **liste des affectations actives** de l'équipe (id, libellé court, classe couleur) pour alimenter les deux sélecteurs.
- Le choix « chantier de la demi-journée » se **persiste** : soit au niveau de chaque `Presence` (champ `affectation` déjà porté par la cellule — il suffit de l'écrire à la valeur choisie pour toutes les cellules de la colonne), soit via une petite table `imputation(equipe, date, creneau) -> affectation` qui sert de défaut de colonne. **Préférer** écrire l'`affectation` sur les `Presence` (la rentabilité lit déjà `Presence.affectation_id` — rien d'autre à changer).
- **Couplage rentabilité inchangé** : on ne fait que **renseigner le bon `affectation_id`** par demi-journée ; `pct_consomme` / `heures_par_tranche` continuent de fonctionner tels quels.

### UI (cf. maquette)
- En-tête jour = bandeau jour (date) sur 2 sous-colonnes ; sous chaque sous-colonne, un **chip sélecteur** : `[• Libellé court ▾]` coloré (fond clair + texte foncé de la teinte du chantier), légende « matin » / « ap.-m. » dessous.
- Largeur : la grille passe de N colonnes-jours à **2×N sous-colonnes** (matin/après-midi) — ce qui correspond déjà aux deux créneaux M/A pointés. Conserver le scroll horizontal.
- Jours **non travaillés** (vendredi par défaut, fériés) : pas de sélecteur, fond grisé « non travaillé ».

---

## 3. Garde-fous

- **Ne rien casser** de l'émargement existant (saisie heures/codes, Tab, auto-save, prêt d'équipier, clôture, fériés/événements → code auto). Ces points sont **déjà implémentés**.
- **Rentabilité** : la seule donnée qui compte est le bon `Presence.affectation_id` par demi-journée — le reste de la chaîne est inchangé.
- **Test rapide** : équipe avec 2 chantiers actifs le même jour → choisir Chantier A le matin, Chantier B l'après-midi → vérifier que les heures s'imputent à A puis B, que les couleurs sont distinctes, et qu'aucune autre équipe n'est affectée. Vérifier qu'une équipe avec 4+ chantiers actifs reçoit 4 couleurs différentes.
