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

from .models import Devis, Facture, AuditLog, LigneDevis
from .permissions import get_collegues_ids, peut_acceder_compta
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
    """IDs des widgets autorisés pour cet utilisateur (filtre compta)."""
    compta = peut_acceder_compta(user)
    return {
        wid for wid, meta in WIDGETS.items()
        if compta or not meta['requires_compta']
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
    return provider(user, scope) if provider else {}


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
