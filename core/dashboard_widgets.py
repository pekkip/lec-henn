"""
Registre des widgets du tableau de bord personnalisable.

Garde `views.py` lisible : ici vivent la définition des widgets (méta),
les fournisseurs de données par widget et la résolution de la configuration
utilisateur (`ProfilUtilisateur.dashboard_config`).

Portée (`scope`) par widget : 'all' (tout), 'mine' (créés par moi),
'team' (mon équipe, via get_collegues_ids).

Widgets compta (`requires_compta=True`) : visibles uniquement pour
admin/comptable (peut_acceder_compta), filtrés au rendu ET à la sauvegarde.
"""
from collections import OrderedDict
from datetime import date
from decimal import Decimal

from django.db.models import Sum, Count
from django.utils import timezone

import calendar

from .models import Devis, Facture, AuditLog, LigneDevis, Presence, Affectation
from .permissions import get_collegues_ids, peut_acceder_compta, peut_acceder_planning
from .totaux import (
    total_brut_devis, total_facture_devis,
    attacher_totaux_devis, totaux_lignes,
)


# ══════════════════════════════════════════
#  REGISTRE
# ══════════════════════════════════════════
# meta : title, type ('kpi'|'list'|'chart'|'activity'), icon (Tabler),
#        supports_scope (bool), requires_compta (bool)

WIDGETS = OrderedDict([
    # — KPIs ———————————————————————————————————————————————
    ('kpi_ca', {
        'title': 'CA accepté', 'type': 'kpi', 'icon': 'ti-cash',
        'supports_scope': True, 'requires_compta': False}),
    ('kpi_reste_a_facturer', {
        'title': 'Reste à facturer', 'type': 'kpi', 'icon': 'ti-hourglass',
        'supports_scope': True, 'requires_compta': False}),
    ('kpi_impayees', {
        'title': 'Factures impayées', 'type': 'kpi', 'icon': 'ti-alert-triangle',
        'supports_scope': True, 'requires_compta': False}),
    ('kpi_a_valider', {
        'title': 'Factures à valider', 'type': 'kpi', 'icon': 'ti-file-check',
        'supports_scope': True, 'requires_compta': False}),
    ('kpi_devis_en_cours', {
        'title': 'Devis en cours', 'type': 'kpi', 'icon': 'ti-progress',
        'supports_scope': True, 'requires_compta': False}),
    ('kpi_taux', {
        'title': "Taux d'acceptation", 'type': 'kpi', 'icon': 'ti-percentage',
        'supports_scope': True, 'requires_compta': False}),

    # — Listes —————————————————————————————————————————————
    ('list_devis_recents', {
        'title': 'Derniers devis', 'type': 'list', 'icon': 'ti-calculator',
        'supports_scope': True, 'requires_compta': False}),
    ('list_factures_a_valider', {
        'title': 'Factures à valider', 'type': 'list', 'icon': 'ti-file-check',
        'supports_scope': True, 'requires_compta': False}),
    ('list_factures_impayees', {
        'title': 'Factures impayées', 'type': 'list', 'icon': 'ti-alert-triangle',
        'supports_scope': True, 'requires_compta': False}),
    ('list_factures_recentes', {
        'title': 'Dernières factures (chantier)', 'type': 'list', 'icon': 'ti-cash',
        'supports_scope': True, 'requires_compta': False}),
    ('list_avoirs_recents', {
        'title': 'Derniers avoirs', 'type': 'list', 'icon': 'ti-receipt-refund',
        'supports_scope': True, 'requires_compta': True}),

    # — Analyses (Chart.js) ————————————————————————————————
    ('chart_ca_mensuel', {
        'title': 'CA par mois', 'type': 'chart', 'icon': 'ti-chart-line',
        'supports_scope': True, 'requires_compta': False}),
    ('chart_devis_statut', {
        'title': 'Devis par statut', 'type': 'chart', 'icon': 'ti-chart-donut',
        'supports_scope': True, 'requires_compta': False}),
    ('chart_top_clients', {
        'title': 'Top clients', 'type': 'chart', 'icon': 'ti-chart-bar',
        'supports_scope': True, 'requires_compta': False}),
    ('chart_financements', {
        'title': 'Suivi des financements', 'type': 'chart', 'icon': 'ti-gift',
        'supports_scope': True, 'requires_compta': False}),

    # — Activité ———————————————————————————————————————————
    ('activity_recent', {
        'title': 'Activité récente', 'type': 'activity', 'icon': 'ti-history',
        'supports_scope': True, 'requires_compta': False}),

])


# Configuration par défaut (widgets visibles, dans l'ordre). Tout le reste
# tombe dans « disponibles » (panneau « Ajouter un widget »).
DASHBOARD_DEFAULT = [
    {'id': 'kpi_ca', 'scope': 'all'},
    {'id': 'kpi_reste_a_facturer', 'scope': 'all'},
    {'id': 'kpi_impayees', 'scope': 'all'},
    {'id': 'kpi_a_valider', 'scope': 'all'},
    {'id': 'list_devis_recents', 'scope': 'mine'},
    {'id': 'list_factures_a_valider', 'scope': 'all'},
    {'id': 'chart_ca_mensuel', 'scope': 'all'},
    {'id': 'chart_devis_statut', 'scope': 'all'},
    {'id': 'activity_recent', 'scope': 'mine'},
]

SCOPES = ('all', 'mine', 'team')

# Factures « impayées » = validées ou envoyées, non réglées.
_IMPAYEE_STATUTS = ('validated', 'sent')
# Types facturables (hors acompte / avoir) pour les montants dus.
_TYPES_FACTURABLES = ('facture', 'structure', 'appel')


# ══════════════════════════════════════════
#  PORTÉE (scope)
# ══════════════════════════════════════════

def _apply_scope(qs, user, scope, field='created_by'):
    """Restreint un queryset par créateur selon la portée."""
    if scope == 'mine':
        return qs.filter(**{field: user})
    if scope == 'team':
        return qs.filter(**{f'{field}__in': get_collegues_ids(user)})
    return qs


def scoped_devis(user, scope):
    return _apply_scope(Devis.objects.all(), user, scope)


def scoped_factures(user, scope):
    return _apply_scope(Facture.objects.all(), user, scope)


def scoped_audit(user, scope):
    return _apply_scope(AuditLog.objects.all(), user, scope, field='user')


# ══════════════════════════════════════════
#  DISPONIBILITÉ DES WIDGETS
# ══════════════════════════════════════════

def widgets_for(user):
    """IDs des widgets autorisés pour cet utilisateur."""
    compta = peut_acceder_compta(user)
    return {
        wid for wid, meta in WIDGETS.items()
        if (compta or not meta.get('requires_compta'))
    }


# ══════════════════════════════════════════
#  FOURNISSEURS DE DONNÉES
# ══════════════════════════════════════════

_C_PRUNE = 'var(--prune)'
_C_AMBER = 'var(--amber)'
_C_TEAL = 'var(--teal-dk)'
_C_GRAY = 'var(--gray)'


def _kpi_ca(user, scope):
    # Totaux calculés en mémoire (prefetch des lignes) — pas de N+1.
    qs = scoped_devis(user, scope).filter(status='accepted').prefetch_related('lignes')
    total = sum((total_brut_devis(d) for d in qs), Decimal('0'))
    return {'value': float(total), 'unit': '€', 'sub': 'devis acceptés', 'color': _C_PRUNE}


def _kpi_reste_a_facturer(user, scope):
    qs = (scoped_devis(user, scope).filter(status='accepted')
          .prefetch_related('lignes', 'factures'))
    total = sum((total_brut_devis(d) - total_facture_devis(d) for d in qs), Decimal('0'))
    return {'value': float(total), 'unit': '€', 'sub': 'devis acceptés', 'color': _C_AMBER}


def _kpi_impayees(user, scope):
    qs = scoped_factures(user, scope).filter(
        type_doc__in=_TYPES_FACTURABLES, status__in=_IMPAYEE_STATUTS)
    total = qs.aggregate(s=Sum('montant'))['s'] or 0
    return {'value': float(total), 'unit': '€', 'sub': 'validées/envoyées', 'color': _C_AMBER}


def _kpi_a_valider(user, scope):
    qs = scoped_factures(user, scope).filter(status='draft')
    if not peut_acceder_compta(user):
        qs = qs.filter(devis__isnull=False)
    return {'value': qs.count(), 'unit': '', 'sub': 'brouillons', 'color': _C_TEAL}


def _kpi_devis_en_cours(user, scope):
    n = scoped_devis(user, scope).filter(status__in=['draft', 'sent']).count()
    return {'value': n, 'unit': '', 'sub': 'brouillon ou envoyé', 'color': _C_GRAY}


def _kpi_taux(user, scope):
    qs = scoped_devis(user, scope)
    total = qs.count()
    accepted = qs.filter(status='accepted').count()
    taux = round(accepted / total * 100) if total else 0
    return {'value': taux, 'unit': '%', 'sub': f'{total} devis total', 'color': _C_TEAL}


def _list_devis_recents(user, scope):
    devis = list(scoped_devis(user, scope).select_related('client', 'equipe')
                 .prefetch_related('lignes', 'factures').order_by('-created_at')[:6])
    attacher_totaux_devis(devis)
    return {'devis': devis}


def _list_factures_a_valider(user, scope):
    qs = scoped_factures(user, scope).filter(status='draft').select_related('devis')
    if not peut_acceder_compta(user):
        qs = qs.filter(devis__isnull=False)
    return {'factures': list(qs.order_by('-created_at')[:6])}


def _list_factures_impayees(user, scope):
    qs = (scoped_factures(user, scope)
          .filter(type_doc__in=_TYPES_FACTURABLES, status__in=_IMPAYEE_STATUTS)
          .select_related('devis').order_by('date_echeance', '-created_at')[:6])
    today = timezone.now().date()
    factures = list(qs)
    for f in factures:
        f.en_retard = bool(f.date_echeance and f.date_echeance < today)
    return {'factures': factures, 'today': today}


def _list_factures_recentes(user, scope):
    # Factures de chantier uniquement (corrige le bug : exclut compta + avoirs).
    qs = (scoped_factures(user, scope)
          .filter(devis__isnull=False).exclude(type_doc='avoir')
          .select_related('devis').order_by('-created_at')[:6])
    return {'factures': list(qs)}


def _list_avoirs_recents(user, scope):
    qs = (scoped_factures(user, scope).filter(type_doc='avoir')
          .select_related('devis', 'facture_origine').order_by('-created_at')[:6])
    return {'avoirs': list(qs)}


_STATUT_COULEURS = {
    'draft': '#9CA3AF', 'sent': '#F7A600', 'accepted': '#00AA8D',
    'refused': '#E0575B', 'expired': '#B8B8B8',
}


def _chart_ca_mensuel(user, scope):
    """CA (total_brut des devis acceptés) par mois sur 12 mois glissants."""
    today = timezone.now().date()
    # 12 derniers mois (clé année-mois → label court)
    buckets = OrderedDict()
    y, m = today.year, today.month
    months = []
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    for ym in reversed(months):
        buckets[ym] = 0.0
    depuis = date(months[-1][0], months[-1][1], 1)
    qs = scoped_devis(user, scope).filter(
        status='accepted', date_creation__gte=depuis).prefetch_related('lignes')
    for d in qs:
        key = (d.date_creation.year, d.date_creation.month)
        if key in buckets:
            buckets[key] += float(total_brut_devis(d))
    mois_fr = ['', 'Janv', 'Févr', 'Mars', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']
    labels = [f'{mois_fr[mm]} {yy % 100:02d}' for (yy, mm) in buckets]
    return {'labels': labels, 'values': list(buckets.values())}


def _chart_devis_statut(user, scope):
    rows = (scoped_devis(user, scope).values('status')
            .annotate(n=Count('id')))
    labels_map = dict(Devis.STATUS_CHOICES)
    data = {r['status']: r['n'] for r in rows}
    labels, values, colors = [], [], []
    for code, libelle in Devis.STATUS_CHOICES:
        if data.get(code):
            labels.append(libelle)
            values.append(data[code])
            colors.append(_STATUT_COULEURS.get(code, '#67123A'))
    return {'labels': labels, 'values': values, 'colors': colors}


def _chart_top_clients(user, scope):
    """Top 7 clients par CA accepté (total_brut Python → agrégation manuelle)."""
    qs = (scoped_devis(user, scope).filter(status='accepted')
          .select_related('client').prefetch_related('lignes'))
    totaux = {}
    for d in qs:
        if not d.client_id:
            continue
        totaux[d.client] = totaux.get(d.client, 0.0) + float(total_brut_devis(d))
    top = sorted(totaux.items(), key=lambda kv: kv[1], reverse=True)[:7]
    return {
        'labels': [str(c) for c, _ in top],
        'values': [v for _, v in top],
    }


def _chart_financements(user, scope):
    """Montant des financements (lignes liées à une aide) par organisme,
    sur les devis acceptés."""
    qs = LigneDevis.objects.filter(
        aide__isnull=False, devis__status='accepted'
    ).select_related('aide', 'devis')
    qs = _apply_scope(qs, user, scope, field='devis__created_by')
    # Totaux des lignes calculés en mémoire (1 requête pour tous les sous-arbres).
    lignes = list(qs)
    total_par_ligne = totaux_lignes(lignes)
    totaux = {}
    for ligne in lignes:
        org = ligne.aide.organisme or 'Autre'
        totaux[org] = totaux.get(org, 0.0) + float(total_par_ligne[ligne.pk])
    items = sorted(totaux.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        'labels': [org for org, _ in items],
        'values': [v for _, v in items],
    }


def _activity_recent(user, scope):
    events = list(scoped_audit(user, scope)
                  .select_related('user', 'devis', 'facture')[:10])
    return {'events': events}


# ══════════════════════════════════════════
#  PRODUCTION (planning/insertion)
# ══════════════════════════════════════════

def _mois_courant():
    today = timezone.localdate()
    return (date(today.year, today.month, 1),
            date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]))


def _prod_eur_color(eur_j, taux_j):
    if eur_j is None:
        return _C_GRAY
    if eur_j >= taux_j:
        return _C_TEAL
    if eur_j >= taux_j * Decimal('0.8'):
        return _C_AMBER
    return 'var(--red)'


def _prod_taux_color(taux):
    if taux is None:
        return _C_GRAY
    if taux >= 100:
        return _C_TEAL
    if taux >= 80:
        return _C_AMBER
    return 'var(--red)'


def _prod_data(ctx=None):
    """Agrège les données de production pour la période et équipes du contexte."""
    from django.db.models import Count, Sum as DSum
    from .planning_utils import _count_working_days
    from .models import ParametresAssociation

    if ctx:
        debut = ctx.get('debut')
        fin   = ctx.get('fin')
        if not debut or not fin:
            debut, fin = _mois_courant()
        equipe_ids = ctx.get('equipe_ids') or set()
    else:
        debut, fin = _mois_courant()
        equipe_ids = set()

    # Jours réalisés = jours distincts où l'équipe a travaillé (≥1 présence code='')
    pres_qs = Presence.objects.filter(
        affectation__isnull=False, code='', date__gte=debut, date__lte=fin)
    if equipe_ids:
        pres_qs = pres_qs.filter(affectation__equipe_id__in=equipe_ids)
    pres_rows = (pres_qs
                 .values('affectation__tranche__devis_id', 'affectation__equipe_id')
                 .annotate(n=Count('date', distinct=True)))
    jr_d, jr_e = {}, {}
    for r in pres_rows:
        d_id = r['affectation__tranche__devis_id']
        e_id = r['affectation__equipe_id']
        j = Decimal(r['n'])   # 1 par jour d'équipe, pas ÷2
        if d_id:
            jr_d[d_id] = jr_d.get(d_id, Decimal('0')) + j
        if e_id:
            jr_e[e_id] = jr_e.get(e_id, Decimal('0')) + j

    # Jours facturables par (devis, équipe) — affectations intersectant la période
    aff_qs = Affectation.objects.filter(
        date_debut__isnull=False, date_fin__isnull=False,
        date_debut__lte=fin, date_fin__gte=debut)
    if equipe_ids:
        aff_qs = aff_qs.filter(equipe_id__in=equipe_ids)
    aff_qs = aff_qs.select_related('tranche__devis', 'equipe')
    jf_d, jf_e, eq_noms = {}, {}, {}
    for aff in aff_qs:
        d_s = max(aff.date_debut, debut)
        d_e = min(aff.date_fin, fin)
        if d_s > d_e:
            continue
        n = Decimal(_count_working_days(d_s, d_e))
        d_id = aff.tranche.devis_id
        e_id = aff.equipe_id
        jf_d[d_id] = jf_d.get(d_id, Decimal('0')) + n
        jf_e[e_id] = jf_e.get(e_id, Decimal('0')) + n
        eq_noms[e_id] = aff.equipe.nom

    # Montant facturé par devis (validé dans la période)
    fac_qs = Facture.objects.filter(
        devis__isnull=False, type_doc__in=('facture', 'acompte'),
        status__in=('validated', 'sent', 'paid'),
        validated_at__isnull=False,
        validated_at__date__gte=debut, validated_at__date__lte=fin)
    if equipe_ids:
        fac_qs = fac_qs.filter(devis__equipe_id__in=equipe_ids)
    mt_d = {
        r['devis_id']: r['total'] or Decimal('0')
        for r in fac_qs.values('devis_id').annotate(total=DSum('montant'))
    }

    params = ParametresAssociation.get()
    taux_j = params.taux_jour_facturable

    all_ids = set(jf_d) | set(jr_d) | set(mt_d)
    devis_lk = {d.pk: d for d in
                Devis.objects.filter(pk__in=all_ids).select_related('client', 'equipe')}

    chantiers = []
    for d_id in all_ids:
        devis = devis_lk.get(d_id)
        if not devis:
            continue
        j_f = jf_d.get(d_id, Decimal('0'))
        j_r = jr_d.get(d_id, Decimal('0'))
        mt  = mt_d.get(d_id, Decimal('0'))
        eur_j = (mt / j_r).quantize(Decimal('0.01')) if j_r else None
        taux  = (j_r / j_f * 100).quantize(Decimal('0.1')) if j_f else None
        chantiers.append({
            'devis': devis, 'j_fact': j_f, 'j_real': j_r, 'montant': mt,
            'ecart': j_r - j_f, 'eur_j': eur_j, 'taux': taux,
            'en_depassement': j_r > j_f > 0,
            'eur_color': _prod_eur_color(eur_j, taux_j),
            'taux_color': _prod_taux_color(taux),
        })
    chantiers.sort(key=lambda c: c['devis'].chantier or '')

    eq_bars = []
    for e_id in set(jf_e) | set(jr_e):
        j_f = jf_e.get(e_id, Decimal('0'))
        j_r = jr_e.get(e_id, Decimal('0'))
        pct = (j_r / j_f * 100).quantize(Decimal('0.1')) if j_f else Decimal('0')
        eq_bars.append({
            'nom': eq_noms.get(e_id, '?'), 'j_fact': j_f, 'j_real': j_r,
            'ecart': j_r - j_f,
            'pct': pct, 'pct_bar': min(pct, Decimal('120')), 'over': pct > 100,
        })
    eq_bars.sort(key=lambda b: b['nom'])

    tot_mt = sum((c['montant'] for c in chantiers), Decimal('0'))
    tot_jr = sum((c['j_real']  for c in chantiers), Decimal('0'))
    tot_jf = sum((c['j_fact']  for c in chantiers), Decimal('0'))
    kpi_eur_j = (tot_mt / tot_jr).quantize(Decimal('0.01')) if tot_jr else None
    kpi_taux  = (tot_jr / tot_jf * 100).quantize(Decimal('0.1')) if tot_jf else None

    mois_fr = ['', 'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin',
               'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
    if debut.month == fin.month and debut.year == fin.year:
        debut_lbl = f"{mois_fr[debut.month]} {debut.year}"
    else:
        debut_lbl = f"{debut.day} {mois_fr[debut.month]} – {fin.day} {mois_fr[fin.month]} {fin.year}"

    return {
        'chantiers': chantiers, 'eq_bars': eq_bars, 'taux_j': taux_j,
        'tot_mt': tot_mt, 'tot_jr': tot_jr, 'tot_jf': tot_jf,
        'kpi_eur_j': kpi_eur_j, 'kpi_taux': kpi_taux, 'debut_lbl': debut_lbl,
    }


def _prod_kpi_montant(user, scope, ctx=None):
    d = _prod_data(ctx)
    return {'value': float(d['tot_mt']), 'unit': '€', 'sub': d['debut_lbl'], 'color': _C_PRUNE}


def _prod_kpi_j_realises(user, scope, ctx=None):
    d = _prod_data(ctx)
    return {
        'value': float(d['tot_jr']), 'unit': 'j',
        'sub': f"sur {float(d['tot_jf']):.1f} j facturables", 'color': _C_TEAL,
    }


def _prod_kpi_ratio(user, scope, ctx=None):
    d = _prod_data(ctx)
    eur_j = d['kpi_eur_j']
    return {
        'value': float(eur_j) if eur_j else None, 'unit': '€/j',
        'sub': f"réf. {float(d['taux_j']):.0f} €/j",
        'color': _prod_eur_color(eur_j, d['taux_j']),
    }


def _prod_kpi_taux(user, scope, ctx=None):
    d = _prod_data(ctx)
    return {
        'value': float(d['kpi_taux']) if d['kpi_taux'] else None, 'unit': '%',
        'sub': '100 % = au plan', 'color': _prod_taux_color(d['kpi_taux']),
    }


def _prod_list_chantiers(user, scope, ctx=None):
    return {'chantiers': _prod_data(ctx)['chantiers']}


def _prod_list_depassements(user, scope, ctx=None):
    d = _prod_data(ctx)
    dep = sorted(
        [c for c in d['chantiers'] if c['en_depassement']],
        key=lambda c: c['ecart'], reverse=True,
    )[:5]
    return {'depassements': dep}


def _prod_chart_equipes(user, scope, ctx=None):
    return {'eq_bars': _prod_data(ctx)['eq_bars']}


_PROVIDERS = {
    'kpi_ca': _kpi_ca,
    'kpi_reste_a_facturer': _kpi_reste_a_facturer,
    'kpi_impayees': _kpi_impayees,
    'kpi_a_valider': _kpi_a_valider,
    'kpi_devis_en_cours': _kpi_devis_en_cours,
    'kpi_taux': _kpi_taux,
    'list_devis_recents': _list_devis_recents,
    'list_factures_a_valider': _list_factures_a_valider,
    'list_factures_impayees': _list_factures_impayees,
    'list_factures_recentes': _list_factures_recentes,
    'list_avoirs_recents': _list_avoirs_recents,
    'chart_ca_mensuel': _chart_ca_mensuel,
    'chart_devis_statut': _chart_devis_statut,
    'chart_top_clients': _chart_top_clients,
    'chart_financements': _chart_financements,
    'activity_recent': _activity_recent,
}


def widget_data(widget_id, user, scope):
    """Calcule les données d'un widget (dispatch). Scope normalisé."""
    if scope not in SCOPES:
        scope = 'all'
    provider = _PROVIDERS.get(widget_id)
    if not provider:
        return {}
    return provider(user, scope)


# ══════════════════════════════════════════
#  RÉSOLUTION DE LA CONFIG UTILISATEUR
# ══════════════════════════════════════════

def _normalise_scope(meta, scope):
    if not meta['supports_scope']:
        return 'all'
    return scope if scope in SCOPES else 'all'


def resolve_dashboard(profil, user):
    """
    À partir de `profil.dashboard_config` (ou DASHBOARD_DEFAULT), renvoie :
      - `visibles` : liste ordonnée de widgets {id,type,title,icon,scope,
        supports_scope,data} (données calculées, lazy : seulement les visibles) ;
      - `disponibles` : widgets masqués ou non encore ajoutés (pour « Ajouter »).
    Filtre les widgets non autorisés (compta) et les ids inconnus.
    """
    config = (profil.dashboard_config or {}).get('widgets')
    if not config:
        config = DASHBOARD_DEFAULT
    autorises = widgets_for(user)

    visibles, disponibles, vus = [], [], set()
    for entry in config:
        wid = entry.get('id')
        if wid not in WIDGETS or wid not in autorises or wid in vus:
            continue
        vus.add(wid)
        meta = WIDGETS[wid]
        if entry.get('hidden'):
            disponibles.append({'id': wid, 'title': meta['title'],
                                'icon': meta['icon'], 'type': meta['type']})
            continue
        scope = _normalise_scope(meta, entry.get('scope', 'all'))
        visibles.append({
            'id': wid, 'type': meta['type'], 'title': meta['title'],
            'icon': meta['icon'], 'scope': scope,
            'supports_scope': meta['supports_scope'],
            'data': widget_data(wid, user, scope),
        })

    # Widgets autorisés jamais rencontrés → disponibles (nouveautés).
    for wid, meta in WIDGETS.items():
        if wid in autorises and wid not in vus:
            disponibles.append({'id': wid, 'title': meta['title'],
                                'icon': meta['icon'], 'type': meta['type']})

    return visibles, disponibles


def sanitize_config(raw_widgets, user):
    """
    Nettoie une config reçue du client avant stockage :
      - ne garde que les ids connus ET autorisés (filtre compta) ;
      - normalise hidden (bool) et scope (all|mine|team) ;
      - dédoublonne en gardant le premier ordre rencontré.
    """
    autorises = widgets_for(user)
    out, vus = [], set()
    for entry in (raw_widgets or []):
        if not isinstance(entry, dict):
            continue
        wid = entry.get('id')
        if wid not in WIDGETS or wid not in autorises or wid in vus:
            continue
        vus.add(wid)
        meta = WIDGETS[wid]
        scope = entry.get('scope', 'all')
        if scope not in SCOPES or not meta['supports_scope']:
            scope = 'all'
        out.append({
            'id': wid,
            'hidden': bool(entry.get('hidden')),
            'scope': scope,
        })
    return out
