"""
Calcul des totaux de devis **en mémoire**, sans N+1.

`LigneDevis.total()` (models.py) parcourt l'arbre des lignes en frappant la
base à chaque nœud (`enfants.all()` + `enfants.exists()`). Appelée en boucle
sur une liste de devis (listes, dashboard), elle génère des milliers de
requêtes. Ces helpers calculent les mêmes totaux à partir de lignes déjà
chargées (prefetch ou fetch groupé), donc en un nombre de requêtes borné.

Source unique de la logique de totaux pour `views.py` ET `dashboard_widgets.py`
(placée ici pour éviter un import circulaire entre les deux).
"""
from decimal import Decimal

from .models import LigneDevis


def _total_depuis_map(ligne, enfants):
    """Total d'une ligne à partir d'une map {parent_id: [lignes]}.

    Réplique exactement `LigneDevis.total()` mais sans toucher la base.
    """
    sous = enfants.get(ligne.pk, [])
    if ligne.type_ligne == 'TITRE':
        return sum((_total_depuis_map(e, enfants) for e in sous), Decimal('0'))
    if sous:
        return ligne.quantite * sum((_total_depuis_map(e, enfants) for e in sous), Decimal('0'))
    if ligne.cout_unitaire is not None:
        return ligne.quantite * ligne.cout_unitaire
    return Decimal('0')


def total_brut_devis(devis):
    """`total_brut` d'un devis depuis ses lignes **préchargées**.

    Nécessite `prefetch_related('lignes')` sur le queryset source.
    """
    enfants = {}
    for l in devis.lignes.all():
        enfants.setdefault(l.parent_id, []).append(l)
    racines = enfants.get(None, [])
    return sum(
        (_total_depuis_map(l, enfants) for l in racines if l.type_ligne != 'FIN'),
        Decimal('0'),
    )


def total_facture_devis(devis):
    """`total_facture` d'un devis depuis ses factures **préchargées**.

    Nécessite `prefetch_related('factures')`. Même règle que
    `Devis.total_facture()` (un avoir porte un montant négatif → se déduit).
    """
    return sum(
        (f.montant for f in devis.factures.all()
         if f.status != 'cancelled' and f.type_doc in ('facture', 'acompte', 'avoir')),
        Decimal('0'),
    )


def attacher_totaux_devis(devis_iterable):
    """Attache `brut` et `rtf` (reste à facturer) à chaque devis, en mémoire.

    À appeler sur un queryset déjà `prefetch_related('lignes', 'factures')`.
    Remplace les appels en boucle à `total_brut()`/`reste_a_facturer()`.
    """
    for d in devis_iterable:
        brut = total_brut_devis(d)
        d.brut = brut
        d.rtf = brut - total_facture_devis(d)


def total_mo_devis(devis):
    """Total main d'œuvre (lignes MO + FMO) d'un devis depuis ses lignes préchargées.

    Nécessite `prefetch_related('lignes')` sur le queryset source.
    Suit le même pattern que `total_brut_devis` (pas de N+1).
    """
    enfants = {}
    for l in devis.lignes.all():
        enfants.setdefault(l.parent_id, []).append(l)

    def _mo(ligne):
        sous = enfants.get(ligne.pk, [])
        if ligne.type_ligne == 'TITRE':
            return sum((_mo(e) for e in sous), Decimal('0'))
        if sous:
            return ligne.quantite * sum((_mo(e) for e in sous), Decimal('0'))
        if ligne.type_ligne in ('MO', 'FMO') and ligne.cout_unitaire is not None:
            return ligne.quantite * ligne.cout_unitaire
        return Decimal('0')

    racines = enfants.get(None, [])
    return sum((_mo(l) for l in racines), Decimal('0'))


def mo_mat_lignes(lignes):
    """(total MO, total matériaux) HT d'une facture depuis ses lignes **préchargées**.

    MO = feuilles MO/FMO, matériaux = feuilles MAT/FMAT ; les lignes composites
    multiplient leurs enfants par leur quantité (même règle que `_total_depuis_map`).
    Chaque nœud n'est parcouru qu'une fois (les deux composantes remontent ensemble).
    """
    enfants = {}
    for l in lignes:
        enfants.setdefault(l.parent_id, []).append(l)

    def _walk(l):
        sous = enfants.get(l.pk, [])
        if l.type_ligne == 'TITRE':
            paires = [_walk(e) for e in sous]
            return (sum((p[0] for p in paires), Decimal('0')),
                    sum((p[1] for p in paires), Decimal('0')))
        if sous:
            mult = l.quantite or Decimal('0')
            paires = [_walk(e) for e in sous]
            return (mult * sum((p[0] for p in paires), Decimal('0')),
                    mult * sum((p[1] for p in paires), Decimal('0')))
        val = (l.quantite or Decimal('0')) * (l.cout_unitaire or Decimal('0'))
        if l.type_ligne in ('MO', 'FMO'):
            return val, Decimal('0')
        if l.type_ligne in ('MAT', 'FMAT'):
            return Decimal('0'), val
        return Decimal('0'), Decimal('0')

    paires = [_walk(r) for r in enfants.get(None, [])]
    return (sum((p[0] for p in paires), Decimal('0')),
            sum((p[1] for p in paires), Decimal('0')))


def totaux_lignes(lignes_qs):
    """Renvoie `{ligne_id: total}` pour un ensemble de lignes, en chargeant les
    sous-arbres des devis concernés en **une** requête (pas de N+1).

    Utile quand on a besoin du total de lignes précises (ex. lignes de
    financement liées à une aide) sans itérer `ligne.total()`.
    """
    lignes = list(lignes_qs)
    devis_ids = {l.devis_id for l in lignes}
    # Toutes les lignes des devis concernés, indexées par (devis, parent).
    enfants = {}
    for l in LigneDevis.objects.filter(devis_id__in=devis_ids):
        enfants.setdefault((l.devis_id, l.parent_id), []).append(l)

    def total(l):
        sous = enfants.get((l.devis_id, l.pk), [])
        if l.type_ligne == 'TITRE':
            return sum((total(e) for e in sous), Decimal('0'))
        if sous:
            return l.quantite * sum((total(e) for e in sous), Decimal('0'))
        if l.cout_unitaire is not None:
            return l.quantite * l.cout_unitaire
        return Decimal('0')

    return {l.pk: total(l) for l in lignes}
