"""
Helpers calendaires et métier du module Planning & Émargement.

Fonctions de calcul pur (jours ouvrés, jours fériés, grilles, positions de
colonnes) + logique de recalcul des durées d'affectation. Aucune dépendance
aux requêtes HTTP : utilisable depuis les vues, `dashboard_widgets` et les
commandes de management sans import circulaire.

Règle métier : la semaine travaillée est Lun–Jeu ; le vendredi (ou un jour
chômé) peut être activé par un `Evenement` avec `travaille=True`, un jour
ouvré peut être bloqué par un événement `travaille=False, creneau='journee'`.
"""
import calendar
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from .models import Affectation, Evenement
from .totaux import total_mo_devis

_TAUX_JOUR_PLANNING = Decimal('82.5')  # €/jour/équipier, cohérent avec TAUX_JOUR dans planning.html

CRENEAU_ORDER = {'matin': 0, 'aprem': 1}


def _planning_date(val):
    """Parse une date 'YYYY-MM-DD' issue d'un <input type=date> ; '' -> None."""
    val = (val or '').strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except ValueError:
        return None


def _in_loan(jour, creneau, pret):
    """Retourne True si le couple (jour, creneau) est dans la plage de prêt."""
    if not (pret.date_debut <= jour <= pret.date_fin):
        return False
    if pret.date_debut < jour < pret.date_fin:
        return True
    co = CRENEAU_ORDER[creneau]
    if jour == pret.date_debut == pret.date_fin:
        return CRENEAU_ORDER[pret.creneau_debut] <= co <= CRENEAU_ORDER[pret.creneau_fin]
    if jour == pret.date_debut:
        return co >= CRENEAU_ORDER[pret.creneau_debut]
    return co <= CRENEAU_ORDER[pret.creneau_fin]  # jour == pret.date_fin


def _half_col_creneau(d, debut_grille, creneau='journee'):
    """Retourne (col_start, col_fin_excl) en base 1 pour la grille demi-journées.
    Grille : 12 cols/semaine = 10 demi-j ouvrées (Lun-Ven) + 1 Sam + 1 Dim."""
    weeks = (d - debut_grille).days // 7
    wd = d.weekday()
    if wd == 5:   # Samedi → col 11 de la semaine
        c = weeks * 12 + 11
        return (c, c + 1)
    if wd == 6:   # Dimanche → col 12
        c = weeks * 12 + 12
        return (c, c + 1)
    c_matin = weeks * 12 + wd * 2 + 1
    if creneau == 'matin':
        return (c_matin, c_matin + 1)
    if creneau == 'aprem':
        return (c_matin + 1, c_matin + 2)
    return (c_matin, c_matin + 2)  # journee = span entier


def _build_evenement_sets(equipe_id, debut, fin):
    """Retourne (positifs, negatifs) sets[date] pour une équipe + événements globaux sur [debut, fin].
    positifs : jours normalement non-ouvrés devenus ouvrés (travaille=True).
    negatifs : jours ouvrés bloqués (travaille=False, creneau=journee)."""
    evs = (Evenement.objects
           .filter(date_debut__lte=fin)
           .prefetch_related('equipes'))
    positifs, negatifs = set(), set()
    for ev in evs:
        eq_ids = {e.pk for e in ev.equipes.all()}
        is_global = len(eq_ids) == 0
        if not is_global and equipe_id not in eq_ids:
            continue
        d, end = ev.date_debut, ev.date_fin or ev.date_debut
        while d <= end:
            if debut <= d <= fin:
                if ev.travaille:
                    positifs.add(d)
                elif ev.creneau == 'journee':
                    negatifs.add(d)
            d += timedelta(days=1)
    return positifs, negatifs


def _is_working_day(d, positifs, negatifs):
    if d in negatifs:
        return False
    if d in positifs:
        return True
    return d.weekday() < 4  # Lun=0..Jeu=3


def _count_working_days(start_date, end_date, positifs=None, negatifs=None):
    """Compte les jours ouvrés entre start_date et end_date inclus, tenant compte des exceptions."""
    pos, neg = positifs or set(), negatifs or set()
    n, d = 0, start_date
    while d <= end_date:
        if _is_working_day(d, pos, neg):
            n += 1
        d += timedelta(days=1)
    return n


def _add_working_days(start_date, n_days, positifs=None, negatifs=None):
    """Ajoute n_days jours ouvrés à start_date, tenant compte des exceptions."""
    pos, neg = positifs or set(), negatifs or set()
    d = start_date
    while not _is_working_day(d, pos, neg):
        d += timedelta(days=1)
    rem = n_days - 1
    while rem > 0:
        d += timedelta(days=1)
        if _is_working_day(d, pos, neg):
            rem -= 1
    return d


def _recalcul_durees_tranche(tranche, devis):
    """Recalcule date_fin de toutes les affectations d'une tranche selon l'effectif cumulé + événements.
    Retourne la liste des PKs modifiés."""
    all_aff = list(Affectation.objects.filter(tranche=tranche).select_related('equipe'))
    if not all_aff:
        return []
    total_nbEq = sum(a.equipe.nb_equipiers for a in all_aff)
    total_mo   = total_mo_devis(devis)
    if not total_mo or total_nbEq <= 0:
        return []
    n_jours = max(1, math.ceil(float(total_mo) / (float(_TAUX_JOUR_PLANNING) * total_nbEq)))
    updated = []
    for a in all_aff:
        borne_max = a.date_debut + timedelta(days=n_jours * 2 + 30)
        pos, neg  = _build_evenement_sets(a.equipe_id, a.date_debut, borne_max)
        new_fin   = _add_working_days(a.date_debut, n_jours, pos, neg)
        if a.date_fin != new_fin:
            a.date_fin     = new_fin
            a.fin_creneau  = 'aprem'
            a.save(update_fields=['date_fin', 'fin_creneau'])
            updated.append(a.pk)
    return updated


def _jours_feries(annee):
    """Retourne le frozenset des jours fériés légaux français pour l'année donnée."""
    def _paques(y):
        a = y % 19; b = y // 100; c = y % 100
        d = b // 4; e = b % 4; f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19*a + b - d - g + 15) % 30
        i = c // 4; k = c % 4
        l = (32 + 2*e + 2*i - h - k) % 7
        m = (a + 11*h + 22*l) // 451
        month = (h + l - 7*m + 114) // 31
        day   = ((h + l - 7*m + 114) % 31) + 1
        return date(y, month, day)
    paques = _paques(annee)
    return frozenset({
        date(annee, 1,  1),
        date(annee, 5,  1),
        date(annee, 5,  8),
        date(annee, 7, 14),
        date(annee, 8, 15),
        date(annee, 11,  1),
        date(annee, 11, 11),
        date(annee, 12, 25),
        paques + timedelta(days=1),    # Lundi de Pâques
        paques + timedelta(days=39),   # Ascension
        # Lundi de Pentecôte exclu : journée de solidarité travaillée
    })


def _build_grille(annee, mois):
    """
    Grille semaines ISO pour la fiche mensuelle.

    Règle :
      - Blocs ambré : toutes les semaines ISO du mois précédent visibles dans la
        fiche (lun-ven), en partant de la semaine du 26 du mois précédent si le 26
        est un jour ouvré ; sinon, de la semaine du dernier jour ouvré du mois
        précédent (le 26 sam/dim n'apparaissant pas sur la fiche).
      - Blocs courants : de first_current_mon (premier lundi avec des jours du mois
        courant) jusqu'à la fin du mois. Les jours du mois précédent qui se trouvent
        dans le premier bloc courant sont aussi affichés en ambré (jour.is_prev=True)
        et éditables, les jours du mois suivant restent gris.
    """
    first    = date(annee, mois, 1)
    last_day = calendar.monthrange(annee, mois)[1]
    last     = date(annee, mois, last_day)

    # Premier lundi avec des jours ouvrés du mois courant
    dow = first.isoweekday()  # 1=lun … 5=ven  6=sam  7=dim
    if dow <= 5:
        first_current_mon = first - timedelta(days=dow - 1)
    else:
        first_current_mon = first + timedelta(days=8 - dow)

    # 26 du mois précédent
    prev_mois  = mois - 1 if mois > 1 else 12
    prev_annee = annee if mois > 1 else annee - 1
    day26      = date(prev_annee, prev_mois, 26)
    week26_mon = day26 - timedelta(days=day26.isoweekday() - 1)

    # Début des blocs ambré :
    # - 26 ouvrable (lun-ven) → semaine du 26
    # - 26 sam/dim → semaine du dernier jour ouvré du mois précédent
    if day26.isoweekday() <= 5:
        start_prev = week26_mon
    else:
        prev_last = first - timedelta(days=1)
        if prev_last.isoweekday() > 5:          # sam ou dim → reculer au ven
            prev_last -= timedelta(days=prev_last.isoweekday() - 5)
        start_prev = prev_last - timedelta(days=prev_last.isoweekday() - 1)

    JOURS_LABELS = ['L', 'M', 'M', 'J', 'V']

    def make_bloc(mon, is_prev=False):
        jours = []
        for i in range(5):
            d = mon + timedelta(days=i)
            # in_range : le jour a un input (éditable)
            # - tous les jours des blocs ambré (is_prev=True)
            # - jours du mois courant dans les blocs courants
            # - jours du mois précédent dans le 1er bloc courant (d < first)
            in_range = is_prev or d.month == mois or d < first
            # is_prev au niveau du jour : détermine le fond ambré dans le template
            jour_is_prev = is_prev or d < first
            jours.append({
                'date':     d,
                'date_iso': d.isoformat(),
                'label':    JOURS_LABELS[i],
                'num':      d.day,
                'in_range': in_range,
                'is_prev':  jour_is_prev,
            })
        iso_cal = mon.isocalendar()
        return {
            'num_semaine': iso_cal[1],
            'annee_iso':   iso_cal[0],
            'is_prev':     is_prev,
            'jours':       jours,
        }

    blocs = []

    # Blocs ambré : de start_prev jusqu'à first_current_mon (exclue)
    cur = start_prev
    while cur < first_current_mon:
        blocs.append(make_bloc(cur, is_prev=True))
        cur += timedelta(7)

    # Blocs courants : de first_current_mon jusqu'à la fin du mois
    cur = first_current_mon
    while cur <= last:
        blocs.append(make_bloc(cur, is_prev=False))
        cur += timedelta(7)

    return blocs
