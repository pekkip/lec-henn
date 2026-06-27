# Captures d'écran du manuel utilisateur

Ce dossier accueille les **captures d'écran** intégrées au manuel
(`core/templates/core/manuel.html`, route `/manuel/`).

## Convention

- Format **PNG**, largeur conseillée ~1200 px (lisible sans être lourd).
- Nom de fichier **exactement** celui attendu par le manuel (voir le tableau ci-dessous) —
  le manuel pointe dessus via `{% static 'core/manuel/<nom>.png' %}`.
- Tant qu'une capture est absente, le manuel affiche un **emplacement pointillé**
  « 📷 Capture à intégrer » avec le chemin attendu — rien ne casse.

## Fichiers attendus

| Fichier | Écran |
|---|---|
| `clients_liste.png` | Liste des clients + filtres |
| `client_fiche.png` | Modale client + carnet de contacts |
| `devis_form_client.png` | Création d'un devis — sélection du client |
| `devis_editeur.png` | Éditeur de devis rempli (toolbar + arbre de lignes) |
| `devis_biblio_panneau.png` | Panneau bibliothèque dans l'éditeur (glisser-déposer) |
| `biblio_page.png` | Page Bibliothèque (catégories + groupes) |
| `devis_onglet_factures.png` | Onglet Factures d'un devis |
| `facture_nouvelle.png` | Modale Nouvelle facture (Facture / Acompte) |
| `facture_editeur.png` | Éditeur de facture (quantités, lignes non facturées) |
| `import_devis.png` | Écran d'import de devis (upload + prévisualisation) |
| `dashboard_perso.png` | Tableau de bord en mode personnalisation |

> Après avoir déposé des fichiers ici en production, lancer
> `python manage.py collectstatic` (inclus dans `deploy.sh`).
