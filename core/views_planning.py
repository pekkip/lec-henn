"""
Vues du module Planning & Émargement (insertion).

Équipiers, planning mensuel (timeline), émargement hebdomadaire, événements,
affectations, prêts, feuilles de présence mensuelles (FSE/CISP) et tableau de
bord insertion. Séparé de views.py (session 36) — les helpers calendaires
vivent dans planning_utils.py.
"""
import calendar
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, Prefetch, Max

from .models import (
    Devis, Facture, LigneDevis, LigneFacture, Equipe,
    Equipier, TrancheDevis, Affectation, Presence, Evenement, Pret,
    FicheNote, ClotureMois, COULEURS_CHANTIER,
)
from .permissions import peut_acceder_planning, est_encadrant, peut_modifier_devis, peut_modifier_insertion
from .planning_utils import (
    _TAUX_JOUR_PLANNING,
    _planning_date, _in_loan, _half_col_creneau,
    _build_evenement_sets, _count_working_days,
    _add_working_days, _recalcul_durees_tranche,
    _jours_feries, _build_grille, couleurs_par_equipe,
)
from .totaux import total_mo_devis, mo_mat_lignes
from .views import get_profil, to_decimal, _build_period_presets, parse_json_request, json_error, json_error_permission


def aide_insertion_view(request):
    return render(request, 'core/aide_insertion.html')


@login_required
def insertion_dashboard(request):
    import calendar as _cal
    from .permissions import peut_acceder_planning as _pap
    from .dashboard_widgets import _prod_data

    if not _pap(request.user):
        return redirect('core:dashboard')

    prod_equipes = list(
        Equipe.objects.filter(actif=True, service__module_planning=True)
        .order_by('nom').values('pk', 'nom')
    )

    eq_ids_selected = set()
    if request.GET.getlist('eq'):
        try:
            eq_ids_selected = {int(x) for x in request.GET.getlist('eq') if x.isdigit()}
        except (ValueError, TypeError):
            pass

    today = timezone.localdate()
    debut_str = request.GET.get('debut', '')
    fin_str   = request.GET.get('fin', '')
    try:
        debut = date.fromisoformat(debut_str)
    except (ValueError, TypeError):
        debut = date(today.year, today.month, 1)
    try:
        fin = date.fromisoformat(fin_str)
    except (ValueError, TypeError):
        fin = date(today.year, today.month, _cal.monthrange(today.year, today.month)[1])
    if debut > fin:
        debut, fin = fin, debut

    for eq in prod_equipes:
        eq['selected'] = (not eq_ids_selected) or (eq['pk'] in eq_ids_selected)

    ctx = {
        'debut': debut, 'fin': fin,
        'equipe_ids': eq_ids_selected,
        'debut_str': debut.isoformat(),
        'fin_str': fin.isoformat(),
    }
    data = _prod_data(ctx)

    fac_qs = (
        Facture.objects
        .filter(
            type_doc__in=('facture', 'acompte'),
            devis__isnull=False,
            devis__equipe__service__module_planning=True,
            status__in=('draft', 'validated', 'sent', 'paid'),
            date_creation__range=(debut, fin),
        )
        .select_related('devis__client', 'devis__equipe')
        .order_by('-date_creation', 'devis__equipe__nom')
    )
    if eq_ids_selected:
        fac_qs = fac_qs.filter(devis__equipe_id__in=eq_ids_selected)
    factures = list(fac_qs)

    # Calcul MO / matériaux par facture en mémoire (1 requête pour toutes les lignes)
    _by_fac = {}
    for _l in LigneFacture.objects.filter(facture_id__in=[f.pk for f in factures]):
        _by_fac.setdefault(_l.facture_id, []).append(_l)

    for f in factures:
        f.montant_mo, f.montant_mat = mo_mat_lignes(_by_fac.get(f.pk, []))

    tot_fac_mo    = sum(f.montant_mo  for f in factures)
    tot_fac_mat   = sum(f.montant_mat for f in factures)
    tot_fac_total = sum(f.montant     for f in factures)

    return render(request, 'core/insertion_dashboard.html', {
        'prod_equipes':  prod_equipes,
        'prod_context':  ctx,
        'prod_presets':  _build_period_presets(today),
        'chantiers':     data['chantiers'],
        'eq_bars':       data['eq_bars'],
        'tot_jf':        data['tot_jf'],
        'tot_jr':        data['tot_jr'],
        'debut_lbl':     data['debut_lbl'],
        'factures':       factures,
        'tot_fac_mo':     tot_fac_mo,
        'tot_fac_mat':    tot_fac_mat,
        'tot_fac_total':  tot_fac_total,
    })



# ══════════════════════════════════════════
#  PLANNING & ÉMARGEMENT — Équipiers
# ══════════════════════════════════════════
#
# Gestion des équipiers (salariés en insertion à pointer). Réservé au module
# Insertion (peut_acceder_planning : admin / responsable / rh / encadrant).
# Suppression = désactivation (actif=False), jamais de DELETE dur.

@login_required
def equipiers_list(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")
    q = request.GET.get('q', '').strip()
    equipe_id = request.GET.get('equipe', '').strip()
    statut = request.GET.get('statut', 'actifs')

    equipes_planning = Equipe.objects.filter(
        actif=True, service__module_planning=True
    ).select_related('service').order_by('nom')

    equipiers = Equipier.objects.filter(
        equipe__service__module_planning=True
    ).select_related('equipe', 'equipe__service')
    if q:
        equipiers = equipiers.filter(
            Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(matricule__icontains=q)
        )
    if equipe_id:
        equipiers = equipiers.filter(equipe_id=equipe_id)
    if statut == 'actifs':
        equipiers = equipiers.filter(actif=True)
    elif statut == 'inactifs':
        equipiers = equipiers.filter(actif=False)

    return render(request, 'core/equipiers.html', {
        'equipiers': equipiers,
        'equipes': equipes_planning,
        'f_q': q, 'f_equipe': equipe_id, 'f_statut': statut,
    })


@login_required
@require_POST
def equipier_save(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")
    pk = request.POST.get('pk')
    nom = request.POST.get('nom', '').strip()
    prenom = request.POST.get('prenom', '').strip()
    if not nom or not prenom:
        messages.error(request, 'Nom et prénom sont obligatoires.')
        return redirect('core:equipiers')

    equipe_id = request.POST.get('equipe') or None
    equipe = Equipe.objects.filter(pk=equipe_id).first() if equipe_id else None

    champs = dict(
        nom=nom,
        prenom=prenom,
        equipe=equipe,
        matricule=request.POST.get('matricule', '').strip(),
        type_contrat=request.POST.get('type_contrat', '').strip() or 'CDDI - 26 heures',
        heures_contrat_hebdo=to_decimal(request.POST.get('heures_contrat_hebdo'), Decimal('26.00')),
        date_debut_contrat=_planning_date(request.POST.get('date_debut_contrat')),
        date_fin_contrat=_planning_date(request.POST.get('date_fin_contrat')),
        date_visite_medicale=_planning_date(request.POST.get('date_visite_medicale')),
        recup_base_heures=to_decimal(request.POST.get('recup_base_heures'), Decimal('0')),
        recup_base_date=_planning_date(request.POST.get('recup_base_date')),
        droit_conges_jours=to_decimal(request.POST.get('droit_conges_jours'), Decimal('0')),
    )

    if pk:
        equipier = get_object_or_404(Equipier, pk=pk)
        for k, v in champs.items():
            setattr(equipier, k, v)
        equipier.save()
        messages.success(request, f'Équipier « {prenom} {nom} » modifié.')
    else:
        Equipier.objects.create(**champs)
        messages.success(request, f'Équipier « {prenom} {nom} » créé.')
    return redirect('core:equipiers')


@login_required
@require_POST
def equipier_toggle_actif(request, pk):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")
    equipier = get_object_or_404(Equipier, pk=pk)
    equipier.actif = not equipier.actif
    equipier.save(update_fields=['actif'])
    action = 'réactivé' if equipier.actif else 'désactivé'
    messages.success(request, f'Équipier « {equipier.prenom} {equipier.nom} » {action}.')
    return redirect('core:equipiers')


# ══════════════════════════════════════════
#  PLANNING — Grille d'émargement & présences
# ══════════════════════════════════════════

JOURS_FR      = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven']
CRENEAUX      = [('matin', 'M'), ('aprem', 'A')]
DEF_H         = {'matin': '4', 'aprem': '3'}


@login_required
def emargement_view(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    equipe_id = request.GET.get('equipe', '').strip()
    debut_str = request.GET.get('debut', '').strip()

    today = timezone.localdate()
    try:
        debut = datetime.strptime(debut_str, '%Y-%m-%d').date() if debut_str else today
    except ValueError:
        debut = today
    lundi   = debut - timedelta(days=debut.weekday())
    vendredi = lundi + timedelta(days=4)

    profil = get_profil(request.user)
    if peut_modifier_insertion(request.user):
        equipes = Equipe.objects.filter(
            actif=True, service__module_planning=True
        ).select_related('service').order_by('nom')
    else:
        equipes = Equipe.objects.filter(
            encadrant=request.user, actif=True, service__module_planning=True
        ).select_related('service').order_by('nom')

    equipe_sel = equipes.filter(pk=equipe_id).first() if equipe_id else None
    if not equipe_sel:
        equipe_sel = equipes.first()

    if not equipe_sel:
        return render(request, 'core/emargement.html', {
            'equipes': equipes, 'equipe_sel': None,
            'lundi': lundi, 'jours': [], 'grid_rows': [], 'affectations': [],
        })

    jours = [lundi + timedelta(days=i) for i in range(5)]

    # Événements qui modifient les journées (travaille / décale chantier)
    evs_semaine = list(
        Evenement.objects.filter(date_debut__lte=vendredi)
        .filter(
            Q(date_fin__isnull=True, date_debut__gte=lundi) | Q(date_fin__gte=lundi)
        )
        .filter(Q(equipes=equipe_sel) | Q(equipes__isnull=True))
        .distinct()
    )
    jours_travailles = set()   # jours off devenus on
    jours_off_force  = set()   # jours on devenus off (formation, décalé, etc.)
    events_by_jour  = {j: [] for j in jours}
    jours_feries_ev = {}  # jour -> Evenement de type journee_ferie
    feries_legaux   = _jours_feries(lundi.year)
    if vendredi.year != lundi.year:
        feries_legaux = feries_legaux | _jours_feries(vendredi.year)
    for ev in evs_semaine:
        cur = max(ev.date_debut, lundi)
        end = min(ev.date_fin or ev.date_debut, vendredi)
        while cur <= end:
            events_by_jour[cur].append(ev)
            if ev.type == 'journee_ferie' and cur not in jours_feries_ev:
                jours_feries_ev[cur] = ev
            if ev.travaille:
                jours_travailles.add(cur)
            elif ev.decale_chantier and ev.type != 'journee_ferie':
                jours_off_force.add(cur)
            cur += timedelta(days=1)

    def is_jour_off(jour):
        if jour in jours_travailles:
            return False
        if jour in jours_off_force:
            return True
        return jour.weekday() == 4

    jours_off = {j for j in jours if is_jour_off(j)}

    affectations = list(
        Affectation.objects.filter(
            equipe=equipe_sel,
            date_debut__lte=vendredi,
            date_fin__gte=lundi,
        ).select_related('tranche__devis__client').order_by('date_debut')
    )
    # Couleurs anti-collision (une seule équipe ici → un seul appel).
    aff_color = couleurs_par_equipe(affectations)
    for aff in affectations:
        aff.css_color = aff_color[aff.pk]

    equipiers_maison = list(
        Equipier.objects.filter(equipe=equipe_sel, actif=True)
        .select_related('equipe').order_by('nom', 'prenom')
    )

    # Filtre par équipier maison (pas par affectation — nullable depuis migration 0024)
    presences_qs = list(
        Presence.objects.filter(
            equipier__equipe=equipe_sel,
            date__range=(lundi, vendredi),
        ).select_related('equipier', 'affectation')
    )
    pres_map = {(p.equipier_id, p.date.isoformat(), p.creneau): p for p in presences_qs}

    # Chantier imputé par demi-journée (toute l'équipe sur un seul chantier par
    # créneau). Dérivé des présences existantes (n'importe quel équipier du
    # créneau imputé à une affectation de l'équipe fait foi) ; à défaut, 1ʳᵉ
    # affectation couvrant ce jour. Aucune table dédiée (cf. plan, Option A).
    aff_by_pk = {aff.pk: aff for aff in affectations}
    slot_pres_aff = {}   # (date_iso, creneau) -> affectation_id (présence existante)
    for p in presences_qs:
        if p.affectation_id in aff_by_pk:
            slot_pres_aff.setdefault((p.date.isoformat(), p.creneau), p.affectation_id)

    slot_aff = {}   # (jour, creneau) -> Affectation | None
    for jour in jours:
        actives = [aff for aff in affectations if aff.date_debut <= jour <= aff.date_fin]
        for creneau, _ in CRENEAUX:
            from_pres = slot_pres_aff.get((jour.isoformat(), creneau))
            slot_aff[(jour, creneau)] = (
                aff_by_pk.get(from_pres) if from_pres
                else (actives[0] if actives else None)
            )

    prets_semaine = list(
        Pret.objects.filter(
            equipe_hote=equipe_sel,
            date_fin__gte=lundi,
            date_debut__lte=vendredi,
        ).select_related('equipier__equipe')
    )
    equip_empruntes = [p.equipier for p in prets_semaine]
    pret_map = {p.equipier_id: p for p in prets_semaine}

    away_set = set()
    if equipiers_maison:
        for p in Presence.objects.filter(
            equipier__in=equipiers_maison,
            date__range=(lundi, vendredi),
            affectation__isnull=False,  # presences sans affectation ne sont pas « away »
        ).exclude(affectation__equipe=equipe_sel):
            away_set.add((p.equipier_id, p.date.isoformat(), p.creneau))

    # Jours+créneaux où un équipier maison est prêté à une autre équipe
    pret_away_map = {}  # (equipier_id, date_iso, creneau) -> nom équipe hôte
    if equipiers_maison:
        for p in Pret.objects.filter(
            equipier__in=equipiers_maison,
            date_fin__gte=lundi,
            date_debut__lte=vendredi,
        ).exclude(equipe_hote=equipe_sel).select_related('equipe_hote'):
            for jour in jours:
                for creneau, _ in CRENEAUX:
                    if _in_loan(jour, creneau, p):
                        pret_away_map[(p.equipier_id, jour.isoformat(), creneau)] = p.equipe_hote.nom

    def _build_row_cells(eq, is_borrowed, pret=None):
        # 1 ligne / équipier : 10 cellules ordonnées (j1-matin, j1-aprem, …).
        total_h = Decimal('0')
        cells = []
        for jour in jours:
            for creneau, label in CRENEAUX:
                date_iso = jour.isoformat()
                key = (eq.pk, date_iso, creneau)
                pres = pres_map.get(key)
                if pres and pres.heures:
                    total_h += pres.heures
                is_off         = is_jour_off(jour)
                is_ferie       = jour in jours_feries_ev
                ferie_label    = jours_feries_ev[jour].libelle if is_ferie else ''
                is_ferie_legal = jour in feries_legaux
                ev_code = next(
                    (ev.code_absence for ev in events_by_jour.get(jour, [])
                     if ev.code_absence and ev.type != 'journee_ferie'),
                    None,
                )
                special_code = 'R' if is_ferie else (ev_code or ('F' if is_ferie_legal else None))
                slot = slot_aff.get((jour, creneau))
                if is_borrowed:
                    loan = _in_loan(jour, creneau, pret) and not is_off
                    is_lent = loan
                    is_away = not loan and not is_off
                    away_team_nom = None
                    aff_c = pres.affectation if pres else (slot if loan else None)
                else:
                    pret_away_team = pret_away_map.get((eq.pk, date_iso, creneau))
                    is_lent = False
                    is_away = (key in away_set) or bool(pret_away_team)
                    away_team_nom = pret_away_team
                    aff_c = pres.affectation if pres else slot
                cells.append({
                    'jour': jour,
                    'date_iso': date_iso,
                    'creneau': creneau,
                    'pres': pres,
                    'is_off': is_off,
                    'is_ferie': is_ferie,
                    'ferie_label': ferie_label,
                    'is_ferie_legal': is_ferie_legal,
                    'special_code': special_code,
                    'is_away': is_away,
                    'is_lent': is_lent,
                    'away_team_nom': away_team_nom,
                    'color': aff_color.get(aff_c.pk, '') if aff_c else '',
                    'aff_id': aff_c.pk if aff_c else '',
                    'default_h': DEF_H[creneau],
                    'is_mon': (jour.weekday() == 0 and creneau == 'matin'),
                })
        return cells, total_h

    grid_rows_maison = []
    for eq in equipiers_maison:
        cells, total_h = _build_row_cells(eq, is_borrowed=False)
        grid_rows_maison.append({'equipier': eq, 'is_borrowed': False, 'pret_id': None, 'cells': cells, 'total_h': total_h})

    grid_rows_empruntes = []
    for eq in equip_empruntes:
        pret = pret_map[eq.pk]
        cells, total_h = _build_row_cells(eq, is_borrowed=True, pret=pret)
        grid_rows_empruntes.append({
            'equipier': eq, 'is_borrowed': True, 'pret_id': pret.pk,
            'pret_debut': pret.date_debut, 'pret_fin': pret.date_fin,
            'pret_debut_creneau': pret.creneau_debut, 'pret_fin_creneau': pret.creneau_fin,
            'cells': cells, 'total_h': total_h,
        })

    # Sélecteurs de chantier par demi-journée (en-tête de grille).
    jour_slots = []
    for jour in jours:
        actives = [aff for aff in affectations if aff.date_debut <= jour <= aff.date_fin]
        opts = [{'id': a.pk, 'color': aff_color[a.pk],
                 'libelle': a.tranche.devis.chantier or a.tranche.devis.client.nom} for a in actives]
        slot = {'jour': jour, 'is_off': is_jour_off(jour), 'creneaux': []}
        for creneau, label in CRENEAUX:
            chosen = slot_aff.get((jour, creneau))
            slot['creneaux'].append({
                'creneau': creneau, 'label': label,
                'aff_id': chosen.pk if chosen else '',
                'color': aff_color[chosen.pk] if chosen else '',
                'choix_requis': len(actives) >= 2,
                'options': opts,
            })
        jour_slots.append(slot)

    # Liste des devis acceptés + MO : servis à la demande par
    # planning_wizard_data (ouverture de la modal Affecter).
    panel_equipes_all = list(
        Equipe.objects.filter(actif=True, service__module_planning=True)
        .prefetch_related(
            Prefetch('equipiers',
                     queryset=Equipier.objects.filter(actif=True).order_by('nom', 'prenom'))
        ).order_by('nom')
    )
    equipe_effectifs_json = {e.pk: e.nb_equipiers for e in panel_equipes_all}
    jours_info = [
        {'jour': j, 'label': JOURS_FR[i], 'events': events_by_jour[j], 'is_off': is_jour_off(j)}
        for i, j in enumerate(jours)
    ]

    # Options des sélecteurs de demi-journée pour le JS (popover de réimputation).
    imp_slots_json = json.dumps({
        f"{s['jour'].isoformat()}|{cr['creneau']}": {
            'aff_id': cr['aff_id'],
            'choix_requis': cr['choix_requis'],
            'options': cr['options'],
        }
        for s in jour_slots for cr in s['creneaux']
    })

    return render(request, 'core/emargement.html', {
        'equipes': equipes,
        'equipe_sel': equipe_sel,
        'lundi': lundi,
        'vendredi': vendredi,
        'jours': jours,
        'jours_info': jours_info,
        'affectations': affectations,
        'aff_color': aff_color,
        'jour_slots': jour_slots,
        'imp_slots_json': imp_slots_json,
        'grid_rows_maison': grid_rows_maison,
        'grid_rows_empruntes': grid_rows_empruntes,
        'panel_equipes': panel_equipes_all,
        'equipe_effectifs_json': equipe_effectifs_json,
        'semaine_prec': (lundi - timedelta(weeks=1)).isoformat(),
        'semaine_suiv': (lundi + timedelta(weeks=1)).isoformat(),
        'peut_modifier': peut_modifier_insertion(request.user),
        # Mois clôturés couvrant la semaine affichée (équipe sélectionnée) —
        # le serveur reste seul juge (équipe maison de chaque équipier).
        'clotures_json': json.dumps([
            '%04d-%02d' % (a, m)
            for a, m in ClotureMois.objects.filter(equipe=equipe_sel)
            .filter(Q(annee=lundi.year, mois=lundi.month) | Q(annee=vendredi.year, mois=vendredi.month))
            .values_list('annee', 'mois')
        ] if equipe_sel else []),
    })


@login_required
def planning_mois(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    profil = get_profil(request.user)
    peut_modifier_global = peut_modifier_insertion(request.user)

    # Fenêtre large : 26 semaines rendues d'un coup (−6/+20 autour de la
    # semaine cible) ; la navigation se fait par scroll côté client, sans
    # rechargement. `?debut=` = date cible (un saut hors fenêtre recharge
    # la page recentrée sur cette date).
    SEM_AVANT, SEM_APRES = 6, 20
    nb_semaines = SEM_AVANT + SEM_APRES

    today = timezone.localdate()
    debut_str = request.GET.get('debut', '')
    try:
        cible = datetime.strptime(debut_str, '%Y-%m-%d').date()
    except (ValueError, AttributeError):
        cible = today
    cible_lundi = cible - timedelta(days=cible.weekday())  # recaler au lundi
    debut_grille = cible_lundi - timedelta(weeks=SEM_AVANT)

    nb_jours   = nb_semaines * 7
    fin_grille = debut_grille + timedelta(days=nb_jours - 1)
    jours      = [debut_grille + timedelta(days=i) for i in range(nb_jours)]

    # En-têtes semaines : numéro ISO
    semaines = [
        {'num': (debut_grille + timedelta(weeks=w)).isocalendar()[1]}
        for w in range(nb_semaines)
    ]

    # En-têtes mois : grouper les semaines consécutives par mois
    mois_hdr = []
    for w in range(nb_semaines):
        lundi = debut_grille + timedelta(weeks=w)
        if mois_hdr and mois_hdr[-1]['date'].month == lundi.month and mois_hdr[-1]['date'].year == lundi.year:
            mois_hdr[-1]['span'] += 12
        else:
            mois_hdr.append({'date': lundi, 'span': 12})

    equipes = Equipe.objects.filter(actif=True, service__module_planning=True).order_by('ordre', 'nom')
    affectations = list(
        Affectation.objects
        .filter(equipe__in=equipes, date_debut__lte=fin_grille, date_fin__gte=debut_grille)
        .select_related('tranche__devis__client', 'equipe')
        .order_by('date_debut')
    )
    # Couleurs anti-collision, attribuées par équipe (cf. couleurs_par_equipe).
    aff_color = {}
    _aff_par_eq = {}
    for aff in affectations:
        _aff_par_eq.setdefault(aff.equipe_id, []).append(aff)
    for _affs in _aff_par_eq.values():
        aff_color.update(couleurs_par_equipe(_affs))
    if peut_modifier_insertion(request.user):
        equipes_modifiables_ids = {e.pk for e in equipes}
    else:
        equipes_modifiables_ids = {e.pk for e in equipes if e.encadrant_id == request.user.pk}

    # Filtre par équipe persistant (préférence utilisateur). Liste d'ids
    # d'équipes affichées ; vide = toutes affichées. On ne garde que les ids
    # encore valides (équipes actives du module).
    equipes_ids = {e.pk for e in equipes}
    filtre_ids = {pk for pk in (profil.planning_filtre_equipes or []) if pk in equipes_ids}
    mes_equipes_ids = set(profil.equipes.values_list('pk', flat=True)) & equipes_ids

    # MO des seuls devis affichés sur la grille (pct_consomme, drag & drop,
    # indicateur de divergence). La liste complète des devis acceptés est
    # servie à la demande par planning_wizard_data (ouverture de la modal).
    devis_ids_grille = {aff.tranche.devis_id for aff in affectations}
    devis_grille = Devis.objects.filter(pk__in=devis_ids_grille).prefetch_related('lignes')
    devis_mo_json = {d.pk: float(total_mo_devis(d)) for d in devis_grille}
    equipe_effectifs_json = {e.pk: e.nb_equipiers for e in equipes}

    # Heures consommées par tranche (somme presences de toutes les équipes affectées)
    from django.db.models import Sum as _DbSum, Count as _DbCount
    tranche_ids = list({aff.tranche_id for aff in affectations})
    _rows = (
        Presence.objects.filter(affectation__tranche_id__in=tranche_ids)
        .values('affectation__tranche_id')
        .annotate(total=_DbSum('heures'))
    ) if tranche_ids else []
    heures_par_tranche = {r['affectation__tranche_id']: float(r['total']) for r in _rows}

    # Jours réalisés par affectation = dates distinctes avec ≥1 présence pointée
    # (code=''). Base du % d'avancement de la barre (cohérent avec le tableau de
    # bord insertion). 1 jour par date, peu importe le nombre d'équipiers présents.
    aff_ids = [aff.pk for aff in affectations]
    _jr_rows = (
        Presence.objects.filter(affectation_id__in=aff_ids, code='')
        .values('affectation_id')
        .annotate(n=_DbCount('date', distinct=True))
    ) if aff_ids else []
    jours_realises_par_aff = {r['affectation_id']: r['n'] for r in _jr_rows}

    # ── Événements dans la fenêtre ──────────────────────────────────────
    evenements = list(
        Evenement.objects
        .filter(date_debut__lte=fin_grille)
        .prefetch_related('equipes')
        .order_by('date_debut')
    )

    # Sets JSON pour JS : {equipe_pk|'global': [date_iso, ...]}
    ev_positifs_json_data = {}
    ev_negatifs_json_data = {}
    for ev in evenements:
        eq_ids = [e.pk for e in ev.equipes.all()]
        keys = [str(pk) for pk in eq_ids] if eq_ids else ['global']
        d_ev, end_ev = ev.date_debut, ev.date_fin or ev.date_debut
        d_cur = d_ev
        while d_cur <= end_ev and d_cur <= fin_grille:
            if d_cur >= debut_grille:
                iso = d_cur.isoformat()
                target = ev_positifs_json_data if ev.travaille else ev_negatifs_json_data
                for k in keys:
                    target.setdefault(k, [])
                    if iso not in target[k]:
                        target[k].append(iso)
            d_cur += timedelta(days=1)

    # ── Cellules de fond (header jours + track) ────────────────────────
    # Pour le header : une cellule par jour (span 2 pour les jours ouvrés)
    jours_hdr = []
    for d in jours:
        wd = d.weekday()
        col_s = _half_col_creneau(d, debut_grille, 'journee')[0]
        col_e = _half_col_creneau(d, debut_grille, 'journee')[1]
        jours_hdr.append({'date': d, 'weekday': wd, 'col_debut': col_s, 'col_fin': col_e})

    # Pour les tracks : deux cellules par jour ouvré (matin + aprem), une par weekend
    jours_cells = []
    for d in jours:
        wd = d.weekday()
        is_today = (d == today)
        if wd >= 5:  # Weekend : une seule cellule
            col_s = _half_col_creneau(d, debut_grille, 'journee')[0]
            jours_cells.append({'date': d, 'weekday': wd, 'col': col_s, 'aprem': False, 'is_we': True, 'is_today': is_today})
        else:
            col_m = _half_col_creneau(d, debut_grille, 'matin')[0]
            col_a = _half_col_creneau(d, debut_grille, 'aprem')[0]
            jours_cells.append({'date': d, 'weekday': wd, 'col': col_m, 'aprem': False, 'is_we': False, 'is_today': is_today})
            jours_cells.append({'date': d, 'weekday': wd, 'col': col_a, 'aprem': True,  'is_we': False, 'is_today': is_today})

    # ── Lignes équipes ──────────────────────────────────────────────────
    lignes = []
    for equipe in equipes:
        barres = []
        for aff in affectations:
            if aff.equipe_id != equipe.pk:
                continue
            starts_before = aff.date_debut < debut_grille
            ends_after    = aff.date_fin   > fin_grille
            d_debut = max(aff.date_debut, debut_grille)
            d_fin   = min(aff.date_fin,   fin_grille)

            # Demi-colonnes avec creneaux
            if starts_before:
                col_d = _half_col_creneau(debut_grille, debut_grille, 'matin')[0]
            else:
                col_d = _half_col_creneau(d_debut, debut_grille, aff.debut_creneau)[0]
            if ends_after:
                col_f = _half_col_creneau(fin_grille, debut_grille, 'aprem')[1]
            else:
                col_f = _half_col_creneau(d_fin, debut_grille, aff.fin_creneau)[1]

            lundi_em = d_debut - timedelta(days=d_debut.weekday())
            label = aff.tranche.devis.chantier or aff.tranche.devis.client.nom
            pos, neg = _build_evenement_sets(equipe.pk, aff.date_debut, aff.date_fin)
            nb_jours = _count_working_days(aff.date_debut, aff.date_fin, pos, neg)
            # % d'avancement = jours réalisés / jours facturables (prévus), en jours.
            # PAS de plafond : un dépassement s'affiche tel quel (ex. 115 %).
            jours_realises = jours_realises_par_aff.get(aff.pk, 0)
            heures_conso   = heures_par_tranche.get(aff.tranche_id, 0)
            pct_consomme   = round(jours_realises / nb_jours * 100) if nb_jours > 0 else 0
            pct_bar        = min(pct_consomme, 120)   # largeur de barre bornée
            over           = pct_consomme > 100       # style « dépassement »
            devis = aff.tranche.devis
            lieu_parts = [p for p in (devis.chantier_cp, devis.chantier_ville) if p]
            lieu = ' '.join(lieu_parts)
            barres.append({
                'aff': aff,
                'color': aff_color[aff.pk],
                'label': label,
                'lieu': lieu,
                'col_debut': col_d,
                'col_fin_excl': col_f,
                'starts_before': starts_before,
                'ends_after': ends_after,
                'lundi_em': lundi_em.isoformat(),
                'nb_jours': nb_jours,
                'pct_consomme': pct_consomme,
                'pct_bar': pct_bar,
                'over': over,
                'has_presences': heures_conso > 0,
            })

        # ── Événements de cette équipe ──────────────────────────────────
        ev_barres = []   # événements négatifs → barres hachurées
        jours_sup = []   # événements positifs → icône sur la colonne
        for ev in evenements:
            eq_ids = {e.pk for e in ev.equipes.all()}
            if eq_ids and equipe.pk not in eq_ids:
                continue
            d_ev_debut = max(ev.date_debut, debut_grille)
            d_ev_fin   = min(ev.date_fin or ev.date_debut, fin_grille)
            if d_ev_debut > fin_grille or d_ev_fin < debut_grille:
                continue
            cren_debut = 'matin' if ev.creneau != 'aprem'  else 'aprem'
            cren_fin   = 'aprem' if ev.creneau != 'matin'  else 'matin'
            col_ev_d = _half_col_creneau(d_ev_debut, debut_grille, cren_debut)[0]
            col_ev_f = _half_col_creneau(d_ev_fin,   debut_grille, cren_fin)[1]
            if ev.travaille:
                jours_sup.append({
                    'col': col_ev_d,
                    'pk': ev.pk,
                    'libelle': ev.libelle or ev.get_type_display(),
                })
            else:
                ev_barres.append({
                    'ev': ev,
                    'col_debut': col_ev_d,
                    'col_fin_excl': col_ev_f,
                    'decale': ev.decale_chantier,
                })

        # ── Voies empilées (interval partitioning, purement visuel) ──────
        # Chaque barre reçoit un index de voie = première voie libre qui ne
        # chevauche pas son intervalle de colonnes [col_debut, col_fin_excl[.
        # Aucun impact modèle : on n'empile que le positionnement vertical.
        lane_fins = []   # col_fin_excl de la dernière barre posée sur chaque voie
        for b in sorted(barres, key=lambda x: (x['col_debut'], x['col_fin_excl'])):
            for i, fin in enumerate(lane_fins):
                if b['col_debut'] >= fin:
                    b['voie'] = i
                    lane_fins[i] = b['col_fin_excl']
                    break
            else:
                b['voie'] = len(lane_fins)
                lane_fins.append(b['col_fin_excl'])
        nb_voies = max(len(lane_fins), 1)

        peut_modifier_ligne = peut_modifier_global or equipe.pk in equipes_modifiables_ids
        lignes.append({
            'equipe': equipe,
            'barres': barres,
            'ev_barres': ev_barres,
            'jours_sup': jours_sup,
            'nb_voies': nb_voies,
            'peut_modifier': peut_modifier_ligne,
            'masquee': bool(filtre_ids) and equipe.pk not in filtre_ids,
        })

    # Cibles de rechargement quand on bute sur un bord de la fenêtre :
    # la nouvelle fenêtre (−6/+20 autour de la cible) chevauche l'ancienne.
    prec_debut = (debut_grille - timedelta(weeks=1)).isoformat()
    suiv_debut = (fin_grille + timedelta(days=1)).isoformat()

    # Pour chaque devis déjà affiché sur la grille : liste des équipes déjà affectées
    devis_equipes: dict[int, list[int]] = {}
    for aff in affectations:
        did = aff.tranche.devis_id
        devis_equipes.setdefault(did, [])
        if aff.equipe_id not in devis_equipes[did]:
            devis_equipes[did].append(aff.equipe_id)

    aff_par_equipe = {}
    for _a in affectations:
        aff_par_equipe.setdefault(str(_a.equipe_id), []).append({
            'debut': _a.date_debut.isoformat(),
            'fin':   _a.date_fin.isoformat(),
            'label': str(_a.tranche.devis.chantier or _a.tranche.devis.client.nom),
        })

    return render(request, 'core/planning.html', {
        'equipes': equipes,
        'jours': jours,
        'jours_hdr': jours_hdr,
        'jours_cells': jours_cells,
        'nb_jours': nb_jours,
        'nb_semaines': nb_semaines,
        'semaines': semaines,
        'mois_hdr': mois_hdr,
        'lignes': lignes,
        'debut_grille': debut_grille,
        'cible_lundi': cible_lundi,
        'fin_grille': fin_grille,
        'prec_debut': prec_debut,
        'suiv_debut': suiv_debut,
        'peut_modifier_global': peut_modifier_global,
        'equipes_modifiables_ids': list(equipes_modifiables_ids),
        'filtre_ids': filtre_ids,
        'mes_equipes_ids': mes_equipes_ids,
        'filtre_actif': bool(filtre_ids),
        'nb_equipes_affichees': len(equipes_ids) - sum(1 for l in lignes if l['masquee']),
        'devis_mo_json': devis_mo_json,
        'equipe_effectifs_json': equipe_effectifs_json,
        'devis_equipes_json': json.dumps(devis_equipes),
        'aff_par_equipe_json': json.dumps(aff_par_equipe),
        'equipes_plan_json': json.dumps([{'id': e.pk, 'nom': e.nom, 'nb_eq': e.nb_equipiers, 'modifiable': e.pk in equipes_modifiables_ids} for e in equipes]),
        'ev_positifs_json': json.dumps(ev_positifs_json_data),
        'ev_negatifs_json': json.dumps(ev_negatifs_json_data),
        'today': timezone.localdate(),
        'equipes_json': json.dumps([{'pk': e.pk, 'nom': e.nom} for e in equipes]),
        'evenements_data_json': json.dumps({
            ev.pk: {
                'type': ev.type,
                'libelle': ev.libelle,
                'date_debut': ev.date_debut.isoformat(),
                'date_fin': ev.date_fin.isoformat() if ev.date_fin else '',
                'creneau': ev.creneau,
                'travaille': ev.travaille,
                'decale_chantier': ev.decale_chantier,
                'equipe_ids': [e.pk for e in ev.equipes.all()],
                'code_absence': ev.code_absence,
            }
            for ev in evenements
        }),
    })


@login_required
@require_POST
def planning_filtre_equipes(request):
    """Persiste le filtre d'équipes du planning (préférence par utilisateur)."""
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err
    ids = data.get('equipes', [])
    if not isinstance(ids, list):
        return json_error('Format invalide')
    # Ne conserver que des entiers valides
    clean = []
    for v in ids:
        try:
            clean.append(int(v))
        except (TypeError, ValueError):
            continue
    profil = get_profil(request.user)
    profil.planning_filtre_equipes = clean
    profil.save(update_fields=['planning_filtre_equipes'])
    return JsonResponse({'ok': True})


@login_required
def planning_wizard_data(request):
    """
    Données de la modal « Affecter un chantier », chargées à son ouverture.

    Sorti du rendu de planning_mois : la liste complète des devis acceptés
    (avec l'arbre des lignes pour le MO) croît avec le volume de devis et
    n'est utile qu'au wizard, pas à l'affichage de la timeline.
    """
    if not peut_acceder_planning(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)

    devis_dispo = list(
        Devis.objects.filter(status='accepted')
        .select_related('client')
        .prefetch_related('lignes')
        .order_by('client__nom')
    )
    devis_data = [{
        'pk': d.pk,
        'ref': d.reference,
        'client': d.client.nom,
        'chantier': d.chantier or '',
        'url': reverse('core:devis-detail', args=[d.pk]),
    } for d in devis_dispo]
    devis_mo = {d.pk: float(total_mo_devis(d)) for d in devis_dispo}

    tranches_par_devis = {}
    for t in TrancheDevis.objects.filter(devis__in=devis_dispo).prefetch_related('affectations__equipe').order_by('ordre', 'nom'):
        tranches_par_devis.setdefault(t.devis_id, []).append({
            'id': t.pk,
            'nom': t.nom,
            'equipes': [{'nom': a.equipe.nom} for a in t.affectations.all()],
        })
    mo_planifie = {}
    for a in Affectation.objects.filter(tranche__devis__in=devis_dispo).select_related('equipe', 'tranche'):
        pos, neg = _build_evenement_sets(a.equipe_id, a.date_debut, a.date_fin)
        nbj = _count_working_days(a.date_debut, a.date_fin, pos, neg)
        mo = float(nbj * a.equipe.nb_equipiers * _TAUX_JOUR_PLANNING)
        mo_planifie[a.tranche.devis_id] = mo_planifie.get(a.tranche.devis_id, 0) + mo

    return JsonResponse({
        'ok': True,
        'devis': devis_data,
        'devis_mo': devis_mo,
        'mo_planifie': mo_planifie,
        'tranches': tranches_par_devis,
    })


@login_required
@require_POST
def tranche_creer(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err
    devis = get_object_or_404(Devis, pk=data.get('devis_id'), status='accepted')
    nom = (data.get('nom') or '').strip() or 'Nouvelle tranche'
    ordre = TrancheDevis.objects.filter(devis=devis).count() + 1
    t = TrancheDevis.objects.create(devis=devis, nom=nom, ordre=ordre)
    return JsonResponse({'ok': True, 'id': t.pk, 'nom': t.nom})


@login_required
@require_POST
def evenement_save(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    pk           = data.get('pk')
    type_ev      = data.get('type', 'autre')
    libelle      = (data.get('libelle') or '').strip()
    equipe_ids   = data.get('equipe_ids', [])
    date_debut_s = (data.get('date_debut') or '').strip()
    date_fin_s   = (data.get('date_fin')   or '').strip()
    creneau      = data.get('creneau', 'journee') or 'journee'
    travaille    = bool(data.get('travaille', False))
    decale       = bool(data.get('decale_chantier', False))

    try:
        date_debut = datetime.strptime(date_debut_s, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Date de début invalide'}, status=400)
    date_fin = None
    if date_fin_s:
        try:
            date_fin = datetime.strptime(date_fin_s, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'Date de fin invalide'}, status=400)

    if pk:
        try:
            ev = Evenement.objects.prefetch_related('equipes').get(pk=pk)
        except Evenement.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Événement introuvable'}, status=404)
    else:
        ev = Evenement()

    code_absence = (data.get('code_absence') or '').strip().upper()
    _valid_codes = {'C', 'R', 'M', 'AT', 'A', 'AJ', 'S', 'PMSMP', 'DE', 'DI', 'F', ''}
    if code_absence not in _valid_codes:
        code_absence = ''

    ev.type           = type_ev
    ev.libelle        = libelle
    ev.date_debut     = date_debut
    ev.date_fin       = date_fin
    ev.creneau        = creneau
    ev.travaille      = travaille
    ev.decale_chantier = decale and not travaille  # décalage seulement si événement négatif
    ev.code_absence   = code_absence
    ev.save()
    ev.equipes.set(equipe_ids)

    # Recalcul des affectations chevauchantes si nécessaire
    recalculated = []
    if travaille or decale:
        from django.db.models import Q
        d_end = date_fin or date_debut
        if equipe_ids:
            aff_qs = Affectation.objects.filter(
                equipe_id__in=equipe_ids,
                date_debut__lte=d_end, date_fin__gte=date_debut,
            ).select_related('tranche__devis').prefetch_related('tranche__devis__lignes')
        else:
            aff_qs = Affectation.objects.filter(
                date_debut__lte=d_end, date_fin__gte=date_debut,
            ).select_related('tranche__devis').prefetch_related('tranche__devis__lignes')
        tranches_done = set()
        for aff in aff_qs:
            if aff.tranche_id not in tranches_done:
                tranches_done.add(aff.tranche_id)
                recalculated.extend(_recalcul_durees_tranche(aff.tranche, aff.tranche.devis))

    return JsonResponse({'ok': True, 'evenement_id': ev.pk, 'recalculated': recalculated})


@login_required
@require_POST
def evenement_delete(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    pk = data.get('pk')
    try:
        ev = Evenement.objects.prefetch_related('equipes').get(pk=pk)
    except Evenement.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Événement introuvable'}, status=404)

    # Récupérer les infos avant suppression pour le recalcul
    equipe_ids  = [e.pk for e in ev.equipes.all()]
    date_debut  = ev.date_debut
    date_fin    = ev.date_fin or ev.date_debut
    do_recalc   = ev.travaille or ev.decale_chantier

    ev.delete()

    recalculated = []
    if do_recalc:
        if equipe_ids:
            aff_qs = Affectation.objects.filter(
                equipe_id__in=equipe_ids,
                date_debut__lte=date_fin, date_fin__gte=date_debut,
            ).select_related('tranche__devis').prefetch_related('tranche__devis__lignes')
        else:
            aff_qs = Affectation.objects.filter(
                date_debut__lte=date_fin, date_fin__gte=date_debut,
            ).select_related('tranche__devis').prefetch_related('tranche__devis__lignes')
        tranches_done = set()
        for aff in aff_qs:
            if aff.tranche_id not in tranches_done:
                tranches_done.add(aff.tranche_id)
                recalculated.extend(_recalcul_durees_tranche(aff.tranche, aff.tranche.devis))

    return JsonResponse({'ok': True, 'recalculated': recalculated})


@login_required
@require_POST
def vendredi_toggle(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    aff_id = data.get('aff_id')
    try:
        aff = (Affectation.objects
               .select_related('equipe', 'tranche__devis')
               .prefetch_related('tranche__devis__lignes')
               .get(pk=aff_id))
    except Affectation.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Affectation introuvable'}, status=404)

    if not est_encadrant(request.user, aff.equipe):
        return JsonResponse({'ok': False, 'error': 'Non autorisé'}, status=403)

    aff.vendredi_actif = not aff.vendredi_actif
    aff.save(update_fields=['vendredi_actif'])
    recalculated = _recalcul_durees_tranche(aff.tranche, aff.tranche.devis)
    return JsonResponse({'ok': True, 'actif': aff.vendredi_actif, 'recalculated': recalculated})


@login_required
@require_POST
def affectation_save(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    devis_id   = data.get('devis_id')
    equipe_id  = data.get('equipe_id')
    debut_s    = (data.get('date_debut') or '').strip()
    fin_s      = (data.get('date_fin') or '').strip()

    devis  = Devis.objects.prefetch_related('lignes').filter(pk=devis_id).first()
    equipe = Equipe.objects.filter(pk=equipe_id).first()
    if not devis or not equipe:
        return JsonResponse({'ok': False, 'error': 'Devis ou équipe introuvable'}, status=404)
    if not est_encadrant(request.user, equipe):
        return JsonResponse({'ok': False, 'error': 'Non autorisé sur cette équipe'}, status=403)
    try:
        date_debut = datetime.strptime(debut_s, '%Y-%m-%d').date()
        date_fin   = datetime.strptime(fin_s,   '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Dates invalides'}, status=400)
    if date_fin < date_debut:
        return JsonResponse({'ok': False, 'error': 'Fin < début'}, status=400)

    tranche_id = data.get('tranche_id')
    if tranche_id:
        try:
            tranche = TrancheDevis.objects.get(pk=tranche_id, devis=devis)
        except TrancheDevis.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Tranche introuvable'}, status=404)
    else:
        tranche, _ = TrancheDevis.objects.get_or_create(
            devis=devis,
            defaults={'nom': 'Chantier complet', 'ordre': 0},
        )
    if Affectation.objects.filter(equipe=equipe, tranche=tranche).exists():
        label = str(devis.chantier or devis.client)
        return JsonResponse({'ok': False, 'error': f'"{label}" est déjà assigné à cette équipe.'})

    debut_creneau = data.get('debut_creneau', 'matin') or 'matin'
    fin_creneau   = data.get('fin_creneau',   'aprem') or 'aprem'

    aff = Affectation.objects.create(
        equipe=equipe, tranche=tranche,
        date_debut=date_debut, date_fin=date_fin,
        debut_creneau=debut_creneau, fin_creneau=fin_creneau,
        created_by=request.user,
    )
    recalculated = _recalcul_durees_tranche(tranche, devis)
    return JsonResponse({
        'ok': True,
        'affectation_id': aff.pk,
        'chantier': str(devis.chantier or devis.client),
        'recalculated': recalculated,
    })


def _aff_update_dict(aff):
    """Sérialise une affectation pour la mise à jour DOM côté client (sans reload)."""
    pos, neg = _build_evenement_sets(aff.equipe_id, aff.date_debut, aff.date_fin)
    nb_j = _count_working_days(aff.date_debut, aff.date_fin, pos, neg)
    return {
        'aff_id':        aff.pk,
        'equipe_id':     aff.equipe_id,
        'date_debut':    aff.date_debut.isoformat(),
        'date_fin':      aff.date_fin.isoformat(),
        'debut_creneau': aff.debut_creneau,
        'fin_creneau':   aff.fin_creneau,
        'nb_jours':      nb_j,
    }


@login_required
@require_POST
def affectation_move(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    aff_id    = data.get('aff_id')
    debut_s   = (data.get('date_debut') or '').strip()
    fin_s     = (data.get('date_fin') or '').strip()
    equipe_id = data.get('equipe_id')

    try:
        aff = Affectation.objects.select_related('equipe').get(pk=aff_id)
    except Affectation.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Affectation introuvable'}, status=404)

    if not est_encadrant(request.user, aff.equipe):
        return JsonResponse({'ok': False, 'error': 'Non autorisé sur cette équipe'}, status=403)

    try:
        date_debut = datetime.strptime(debut_s, '%Y-%m-%d').date()
        date_fin   = datetime.strptime(fin_s,   '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Dates invalides'}, status=400)
    if date_fin < date_debut:
        return JsonResponse({'ok': False, 'error': 'Fin < début'}, status=400)

    try:
        equipe_id = int(equipe_id) if equipe_id else None
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Équipe invalide'}, status=400)
    changing_equipe = equipe_id and equipe_id != aff.equipe_id
    if changing_equipe:
        try:
            new_equipe = Equipe.objects.get(pk=equipe_id, actif=True, service__module_planning=True)
        except Equipe.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Équipe cible introuvable'}, status=404)
        if not est_encadrant(request.user, new_equipe):
            return JsonResponse({'ok': False, 'error': 'Non autorisé sur l\'équipe cible'}, status=403)
        tranche = aff.tranche if hasattr(aff, 'tranche') else Affectation.objects.select_related('tranche').get(pk=aff.pk).tranche
        if Affectation.objects.filter(equipe=new_equipe, tranche=tranche).exclude(pk=aff.pk).exists():
            label = str(tranche.devis.chantier or tranche.devis.client)
            return JsonResponse({'ok': False, 'error': f'"{label}" est déjà assigné à cette équipe.'})
        aff.equipe = new_equipe

    aff.date_debut = date_debut
    aff.date_fin   = date_fin
    if 'debut_creneau' in data:
        aff.debut_creneau = data['debut_creneau'] or 'matin'
    if 'fin_creneau' in data:
        aff.fin_creneau = data['fin_creneau'] or 'aprem'
    aff.save()

    tranche = Affectation.objects.select_related('tranche__devis').prefetch_related('tranche__devis__lignes').get(pk=aff.pk).tranche

    if changing_equipe:
        # Changement d'équipe : recalcul complet depuis le MO (comportement d'origine)
        recalculated_pks = _recalcul_durees_tranche(tranche, tranche.devis)
    else:
        # Resize ou déplacement sans changement d'équipe :
        # MO consommé par cette affectation → MO restant redistribué aux autres.
        pos_a, neg_a = _build_evenement_sets(aff.equipe_id, aff.date_debut, aff.date_fin)
        n_jours_a    = _count_working_days(aff.date_debut, aff.date_fin, pos_a, neg_a)
        mo_consomme  = n_jours_a * float(_TAUX_JOUR_PLANNING) * aff.equipe.nb_equipiers
        total_mo     = float(total_mo_devis(tranche.devis) or 0)
        mo_restant   = max(0.0, total_mo - mo_consomme)
        other_affs   = list(Affectation.objects.filter(tranche=tranche).exclude(pk=aff.pk).select_related('equipe'))
        recalculated_pks = []
        if other_affs:
            total_nbEq_others = sum(o.equipe.nb_equipiers for o in other_affs)
            n_jours_others = max(1, math.ceil(mo_restant / (float(_TAUX_JOUR_PLANNING) * total_nbEq_others))) if (total_nbEq_others > 0 and mo_restant > 0) else 1
            for other in other_affs:
                borne_max = other.date_debut + timedelta(days=n_jours_others * 2 + 30)
                pos, neg  = _build_evenement_sets(other.equipe_id, other.date_debut, borne_max)
                new_fin   = _add_working_days(other.date_debut, n_jours_others, pos, neg)
                if other.date_fin != new_fin:
                    other.date_fin    = new_fin
                    other.fin_creneau = 'aprem'
                    other.save(update_fields=['date_fin', 'fin_creneau'])
                    recalculated_pks.append(other.pk)

    aff.refresh_from_db()
    updated = [_aff_update_dict(aff)]
    if recalculated_pks:
        for ra in Affectation.objects.filter(pk__in=recalculated_pks).select_related('equipe'):
            updated.append(_aff_update_dict(ra))
    return JsonResponse({'ok': True, 'updated': updated})


@login_required
@require_POST
def affectation_delete(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    aff_id = data.get('aff_id')
    try:
        aff = Affectation.objects.select_related('equipe').get(pk=aff_id)
    except Affectation.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Affectation introuvable'}, status=404)

    if not est_encadrant(request.user, aff.equipe):
        return JsonResponse({'ok': False, 'error': 'Non autorisé sur cette équipe'}, status=403)

    # Récupère tranche+devis avant suppression pour recalcul
    aff_full = Affectation.objects.select_related('tranche__devis').prefetch_related('tranche__devis__lignes').get(pk=aff_id)
    tranche = aff_full.tranche
    devis   = tranche.devis

    aff.delete()
    recalculated = _recalcul_durees_tranche(tranche, devis)
    return JsonResponse({'ok': True, 'recalculated': recalculated})


def _mois_cloture(equipe_id, d, cache=None):
    """True si le mois de `d` est clôturé (ClotureMois) pour cette équipe.

    Le verrou suit l'équipe **maison** de l'équipier : c'est sa fiche de
    présence qui a été remise à la RH. `cache` ({(eq, an, mois): bool})
    évite de re-frapper la base dans les boucles de saisie.
    """
    if not equipe_id:
        return False
    key = (equipe_id, d.year, d.month)
    if cache is not None and key in cache:
        return cache[key]
    val = ClotureMois.objects.filter(equipe_id=equipe_id, annee=d.year, mois=d.month).exists()
    if cache is not None:
        cache[key] = val
    return val


def _plage_cloturee(equipe_id, d1, d2):
    """True si au moins un mois de l'intervalle [d1, d2] est clôturé pour l'équipe."""
    if not equipe_id:
        return False
    mois = Q()
    d = date(d1.year, d1.month, 1)
    while d <= d2:
        mois |= Q(annee=d.year, mois=d.month)
        d = date(d.year + (1 if d.month == 12 else 0), (d.month % 12) + 1, 1)
    return ClotureMois.objects.filter(equipe_id=equipe_id).filter(mois).exists()


MSG_MOIS_CLOTURE = 'Mois clôturé (fiche remise à la RH) — saisie verrouillée.'


@login_required
@require_POST
def presence_save(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    saved = deleted = verrouille = 0
    clotures_cache = {}
    for item in data.get('presences', []):
        try:
            equipier_id = int(item.get('equipier_id', 0))
            d           = datetime.strptime(item.get('date', ''), '%Y-%m-%d').date()
            creneau     = item.get('creneau', '')
        except (ValueError, TypeError):
            continue
        if creneau not in ('matin', 'aprem'):
            continue

        equipier = Equipier.objects.select_related('equipe').filter(pk=equipier_id, actif=True).first()
        if not equipier:
            continue

        if _mois_cloture(equipier.equipe_id, d, clotures_cache):
            verrouille += 1
            continue

        # Résolution de l'affectation — nullable depuis migration 0024.
        aff_id_raw = item.get('affectation_id')
        aff = None
        if aff_id_raw:
            try:
                aff = Affectation.objects.select_related('equipe').filter(pk=int(aff_id_raw)).first()
            except (ValueError, TypeError):
                pass

        # Gate permission : tout membre insertion peut saisir sur n'importe quelle équipe.
        if not peut_modifier_insertion(request.user):
            continue
        if not aff and not equipier.equipe:
            continue
        if not aff:
            # Auto-lookup : affectation active à cette date sur l'équipe maison.
            aff = (
                Affectation.objects.filter(
                    equipe=equipier.equipe,
                    date_debut__lte=d,
                    date_fin__gte=d,
                ).order_by('date_debut').first()
                or Affectation.objects.filter(
                    equipe=equipier.equipe,
                    date_fin__lt=d,
                ).order_by('-date_fin').first()
            )

        code       = (item.get('code') or '').strip().upper()
        heures_raw = (item.get('heures') or '')
        heures = Decimal('0') if code else to_decimal(heures_raw, None)

        if heures is None and not code:
            Presence.objects.filter(
                equipier_id=equipier_id, date=d, creneau=creneau
            ).delete()
            deleted += 1
        else:
            Presence.objects.update_or_create(
                equipier_id=equipier_id, date=d, creneau=creneau,
                defaults={
                    'affectation': aff,
                    'heures': heures if heures is not None else Decimal('0'),
                    'code': code,
                    'saisi_par': request.user,
                }
            )
            saved += 1

    if verrouille and not (saved or deleted):
        return JsonResponse({'ok': False, 'error': MSG_MOIS_CLOTURE}, status=403)
    return JsonResponse({'ok': True, 'saved': saved, 'deleted': deleted, 'verrouille': verrouille})


@login_required
@require_POST
def presence_reassign(request):
    """
    Réimpute une demi-journée entière (toute l'équipe) à un chantier.
    Sémantique métier : l'équipe est sur UN seul chantier par demi-journée.
    Met à jour les présences déjà imputées à l'équipe pour ce (jour, créneau).
    """
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err
    try:
        equipe_id = int(data.get('equipe_id'))
        d = datetime.strptime(data.get('date', ''), '%Y-%m-%d').date()
        aff_id = int(data.get('affectation_id'))
    except (TypeError, ValueError):
        return json_error('Paramètres invalides')
    creneau = data.get('creneau', '')
    if creneau not in ('matin', 'aprem'):
        return json_error('Créneau invalide')

    equipe = Equipe.objects.filter(pk=equipe_id).first()
    if not equipe or not peut_modifier_insertion(request.user):
        return json_error_permission()
    if _mois_cloture(equipe_id, d):
        return JsonResponse({'ok': False, 'error': MSG_MOIS_CLOTURE}, status=403)
    aff = Affectation.objects.filter(pk=aff_id, equipe=equipe).first()
    if not aff:
        return json_error('Chantier invalide pour cette équipe')

    # Toutes les présences de ce créneau déjà imputées à l'équipe (maison ET
    # empruntés) basculent sur le chantier choisi. Les présences « away »
    # (imputées à une autre équipe) ne sont pas touchées.
    n = Presence.objects.filter(
        date=d, creneau=creneau, affectation__equipe=equipe,
    ).update(affectation=aff)
    return JsonResponse({'ok': True, 'updated': n})


@login_required
@require_POST
def affectation_couleur(request):
    """Surcharge manuelle de la teinte d'un chantier (Affectation.couleur)."""
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err
    try:
        aff_id = int(data.get('affectation_id'))
    except (TypeError, ValueError):
        return json_error('Paramètres invalides')
    couleur = (data.get('couleur') or '').strip()
    valides = {c[0] for c in COULEURS_CHANTIER}
    if couleur and couleur not in valides:
        return json_error('Teinte invalide')
    aff = Affectation.objects.select_related('equipe').filter(pk=aff_id).first()
    if not aff or not est_encadrant(request.user, aff.equipe):
        return json_error_permission()
    aff.couleur = couleur   # '' = retour à l'attribution automatique
    aff.save(update_fields=['couleur'])
    return JsonResponse({'ok': True})


@login_required
def pret_save(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    if request.method != 'POST':
        return json_error('POST requis', status=405)
    data, err = parse_json_request(request)
    if err:
        return err

    action = data.get('action', 'create')
    if action == 'delete':
        try:
            pret = Pret.objects.select_related('equipe_hote', 'equipier').get(pk=data.get('pret_id'))
            # Supprimer le prêt effacerait les présences saisies chez l'hôte
            if _plage_cloturee(pret.equipier.equipe_id, pret.date_debut, pret.date_fin):
                return JsonResponse({'ok': False, 'error': MSG_MOIS_CLOTURE}, status=403)
            Presence.objects.filter(
                equipier=pret.equipier,
                date__range=(pret.date_debut, pret.date_fin),
                affectation__equipe=pret.equipe_hote,
            ).delete()
            pret.delete()
        except Pret.DoesNotExist:
            pass
        return JsonResponse({'ok': True})

    try:
        equipier = Equipier.objects.select_related('equipe').get(pk=int(data['equipier_id']))
        date_debut = data['date_debut']
        date_fin   = data['date_fin']

        if _plage_cloturee(
            equipier.equipe_id,
            date.fromisoformat(date_debut), date.fromisoformat(date_fin),
        ):
            return JsonResponse({'ok': False, 'error': MSG_MOIS_CLOTURE}, status=403)

        deja_saisi = Presence.objects.filter(
            equipier=equipier,
            date__range=(date_debut, date_fin),
            affectation__equipe=equipier.equipe,
        ).exists()
        if deja_saisi:
            return JsonResponse({
                'ok': False,
                'error': f"{equipier.prenom} {equipier.nom} a déjà des émargements saisis dans {equipier.equipe.nom} sur cette période."
            })

        creneau_debut = data.get('creneau_debut', 'matin')
        creneau_fin   = data.get('creneau_fin', 'aprem')
        pret, _ = Pret.objects.update_or_create(
            equipier=equipier,
            equipe_hote_id=int(data['equipe_hote_id']),
            defaults={
                'date_debut':    date_debut,
                'creneau_debut': creneau_debut,
                'date_fin':      date_fin,
                'creneau_fin':   creneau_fin,
                'cree_par':      request.user,
            },
        )
        return JsonResponse({'ok': True, 'pret_id': pret.pk})
    except Equipier.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Équipier introuvable.'}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)


# ══════════════════════════════════════════
#  FEUILLES DE PRÉSENCE MENSUELLES (insertion)
# ══════════════════════════════════════════

def _get_chantier_semaine(equipier, annee, mois, note_map):
    """
    Construit le dict {num_semaine: chantier_str} pour un équipier.
    Priorité : FicheNote > affectation active > référence devis.
    """
    result = {}
    # Semaines couvertes par le mois
    first = date(annee, mois, 1)
    last_day = calendar.monthrange(annee, mois)[1]
    last  = date(annee, mois, last_day)

    # Presences du mois pour cet équipier
    presences = list(
        Presence.objects.filter(
            equipier=equipier,
            date__year=annee, date__month=mois,
            affectation__isnull=False,
        ).select_related('affectation__tranche__devis').order_by('date')
    )

    # Indexer par semaine : première affectation connue de la semaine
    aff_par_semaine = {}
    for p in presences:
        sem = p.date.isocalendar()[1]
        if sem not in aff_par_semaine:
            aff_par_semaine[sem] = p.affectation

    grille = _build_grille(annee, mois)
    for bloc in grille:
        sem = bloc['num_semaine']
        note = note_map.get(sem)
        if note and note.chantier_texte:
            result[sem] = note.chantier_texte
        elif sem in aff_par_semaine:
            aff = aff_par_semaine[sem]
            chantier_raw = getattr(aff.tranche.devis, 'chantier', '') or ''
            if chantier_raw:
                result[sem] = chantier_raw.split('\n')[0][:60]
            else:
                result[sem] = aff.tranche.devis.reference
        else:
            result[sem] = ''
    return result


@login_required
def feuilles_liste(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    profil = get_profil(request.user)
    today  = timezone.localdate()

    try:
        annee = int(request.GET.get('annee', today.year))
        mois  = int(request.GET.get('mois',  today.month))
    except ValueError:
        annee, mois = today.year, today.month
    annee = max(2020, min(annee, today.year + 1))
    mois  = max(1, min(mois, 12))

    if profil.role in ('admin', 'responsable', 'rh'):
        equipes = Equipe.objects.filter(actif=True, service__module_planning=True).select_related('service').order_by('nom')
    else:
        equipes = Equipe.objects.filter(encadrant=request.user, actif=True, service__module_planning=True).select_related('service').order_by('nom')

    equipe_id = request.GET.get('equipe', '')
    equipe_sel = equipes.filter(pk=equipe_id).first() if equipe_id else equipes.first()

    # Calcul complétion par équipier
    jours_ouvres = sum(
        1 for d in (date(annee, mois, day) for day in range(1, calendar.monthrange(annee, mois)[1] + 1))
        if d.weekday() < 5
    )
    n_theorique = jours_ouvres * 2  # matin + aprem

    equipe_data = []
    if equipe_sel:
        equipiers = list(
            Equipier.objects.filter(equipe=equipe_sel, actif=True).order_by('nom', 'prenom')
        )
        presences_mois = Presence.objects.filter(
            equipier__in=equipiers,
            date__year=annee, date__month=mois,
        ).values('equipier_id').annotate(n=Count('pk'))
        pres_count = {row['equipier_id']: row['n'] for row in presences_mois}

        for eq in equipiers:
            n = pres_count.get(eq.pk, 0)
            if n == 0:
                statut = 'vide'
            elif n >= n_theorique:
                statut = 'complet'
            else:
                statut = 'partiel'
            equipe_data.append({'equipier': eq, 'n_realise': n, 'n_theorique': n_theorique, 'statut': statut})

    # Navigation mois prev/next
    if mois == 1:
        prev_annee, prev_mois = annee - 1, 12
    else:
        prev_annee, prev_mois = annee, mois - 1
    if mois == 12:
        next_annee, next_mois = annee + 1, 1
    else:
        next_annee, next_mois = annee, mois + 1

    MOIS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
               'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    return render(request, 'core/feuilles_liste.html', {
        'equipes':      equipes,
        'equipe_sel':   equipe_sel,
        'equipe_data':  equipe_data,
        'annee':        annee,
        'mois':         mois,
        'mois_nom':     MOIS_FR[mois],
        'prev_annee':   prev_annee,
        'prev_mois':    prev_mois,
        'next_annee':   next_annee,
        'next_mois':    next_mois,
        'peut_modifier': est_encadrant(request.user, equipe_sel) if equipe_sel else False,
        'cloture': (
            ClotureMois.objects.filter(equipe=equipe_sel, annee=annee, mois=mois)
            .select_related('cloture_par').first()
            if equipe_sel else None
        ),
    })


@login_required
def presence_feuille(request, eq_pk, annee, mois):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    equipier = get_object_or_404(Equipier, pk=eq_pk)
    equipe   = equipier.equipe
    if not equipe:
        return HttpResponseForbidden("Cet équipier n'est rattaché à aucune équipe.")

    MOIS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
               'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    blocs = _build_grille(annee, mois)

    # Toutes les presences du mois (+ 1re semaine potentiellement du mois préc.)
    first = date(annee, mois, 1)
    last_day = calendar.monthrange(annee, mois)[1]
    last  = date(annee, mois, last_day)
    # Inclure la semaine du mois précédent si le 1er n'est pas un lundi
    range_start = first - timedelta(days=first.isoweekday() - 1)

    presences = list(
        Presence.objects.filter(
            equipier=equipier,
            date__range=(range_start, last),
        ).select_related('affectation')
    )
    # presence_map : clé "date_iso,creneau" pour faciliter le rendu JSON
    presence_map = {}
    for p in presences:
        key = p.date.isoformat() + ',' + p.creneau
        h_defaut = equipe.heures_matin_defaut if p.creneau == 'matin' else equipe.heures_aprem_defaut
        presence_map[key] = {
            'heures':       '{:g}'.format(float(p.heures)),
            'code':         p.code,
            'is_nondefaut': p.heures != h_defaut or bool(p.code),
        }

    # FicheNotes du mois
    notes = list(FicheNote.objects.filter(equipier=equipier, annee=annee, mois=mois))
    note_map = {n.num_semaine: n for n in notes}

    chantier_par_semaine = _get_chantier_semaine(equipier, annee, mois, note_map)

    # Jours fériés légaux + Evenements type journee_ferie (ponts → R)
    all_dates = [j['date'] for b in blocs for j in b['jours']]
    fiche_start = min(all_dates) if all_dates else first
    fiche_end   = max(all_dates) if all_dates else last
    feries_legaux = _jours_feries(fiche_end.year)
    if fiche_start.year != fiche_end.year:
        feries_legaux = feries_legaux | _jours_feries(fiche_start.year)
    ponts_qs = Evenement.objects.filter(
        type='journee_ferie',
        date_debut__lte=fiche_end,
    ).filter(
        Q(date_fin__isnull=True, date_debut__gte=fiche_start) | Q(date_fin__gte=fiche_start)
    ).filter(
        Q(equipes=equipe) | Q(equipes__isnull=True)
    ).distinct()
    pont_dates = set()
    for ev in ponts_qs:
        d_cur = max(ev.date_debut, fiche_start)
        d_end = min(ev.date_fin or ev.date_debut, fiche_end)
        while d_cur <= d_end:
            pont_dates.add(d_cur)
            d_cur += timedelta(days=1)
    special_map = {}
    for d_sp in feries_legaux:
        if fiche_start <= d_sp <= fiche_end:
            special_map[d_sp.isoformat()] = 'F'
    # Événements avec code_absence (Formation, etc.) — priorité sur F légal, sous R pont
    ev_code_qs = Evenement.objects.filter(
        code_absence__gt='',
        date_debut__lte=fiche_end,
    ).filter(
        Q(date_fin__isnull=True, date_debut__gte=fiche_start) | Q(date_fin__gte=fiche_start)
    ).filter(
        Q(equipes=equipe) | Q(equipes__isnull=True)
    ).exclude(type='journee_ferie').distinct()
    for ev in ev_code_qs:
        d_cur = max(ev.date_debut, fiche_start)
        d_end = min(ev.date_fin or ev.date_debut, fiche_end)
        while d_cur <= d_end:
            special_map[d_cur.isoformat()] = ev.code_absence
            d_cur += timedelta(days=1)
    for d_sp in pont_dates:
        special_map[d_sp.isoformat()] = 'R'   # pont écrase légal et événement

    # Sérialisation JSON pour injection dans le template
    note_map_json = json.dumps({
        sem: {'chantier_texte': n.chantier_texte, 'observation_texte': n.observation_texte}
        for sem, n in note_map.items()
    })
    chantier_json = json.dumps({sem: txt for sem, txt in chantier_par_semaine.items()})

    encadrant = equipe.encadrant
    encadrant_profil = None
    if encadrant:
        try:
            encadrant_profil = encadrant.profil
        except Exception:
            pass

    def fmt_h(val):
        """Formate un Decimal d'heures sans décimales inutiles : 4.00→'4', 1.50→'1.5'"""
        return '{:g}'.format(float(val))

    # Mois clôturés visibles sur la fiche (mois courant + mois précédent pour
    # les jours ambrés) → inputs verrouillés côté JS, banner si mois courant.
    prev_an = annee if mois > 1 else annee - 1
    prev_mo = mois - 1 if mois > 1 else 12
    clotures_fiche = list(
        ClotureMois.objects.filter(equipe=equipe)
        .filter(Q(annee=annee, mois=mois) | Q(annee=prev_an, mois=prev_mo))
        .values_list('annee', 'mois')
    )
    cloture_courante = (annee, mois) in clotures_fiche

    return render(request, 'core/presence_feuille.html', {
        'cloture_courante':  cloture_courante,
        'clotures_json':     json.dumps(['%04d-%02d' % (a, m) for a, m in clotures_fiche]),
        'equipier':         equipier,
        'equipe':           equipe,
        'encadrant':        encadrant,
        'encadrant_profil': encadrant_profil,
        'blocs':            blocs,
        'presence_map_json': json.dumps(presence_map),
        'note_map_json':    note_map_json,
        'chantier_json':    chantier_json,
        'annee':            annee,
        'mois':             mois,
        'mois_nom':         MOIS_FR[mois],
        'peut_modifier':    est_encadrant(request.user, equipe),
        'special_map_json':  json.dumps(special_map),
        'def_matin':        fmt_h(equipe.heures_matin_defaut),
        'def_aprem':        fmt_h(equipe.heures_aprem_defaut),
    })


@login_required
@require_POST
def fiche_presence_save(request):
    """
    Sauvegarde d'une présence depuis la fiche mensuelle (ou l'émargement hebdo).
    Lookup affectation automatique — null autorisé depuis migration 0024.
    """
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    try:
        equipier_id = int(data.get('equipier_id', 0))
        d           = datetime.strptime(data.get('date', ''), '%Y-%m-%d').date()
        creneau     = data.get('creneau', '')
    except (ValueError, TypeError):
        return json_error('Paramètres invalides')

    if creneau not in ('matin', 'aprem'):
        return json_error('Créneau invalide')

    equipier = Equipier.objects.select_related('equipe').filter(pk=equipier_id, actif=True).first()
    if not equipier or not equipier.equipe:
        return json_error('Équipier introuvable', status=404)

    if not est_encadrant(request.user, equipier.equipe):
        return JsonResponse({'ok': False, 'error': 'Permission refusée'}, status=403)

    if _mois_cloture(equipier.equipe_id, d):
        return JsonResponse({'ok': False, 'error': MSG_MOIS_CLOTURE}, status=403)

    # Résolution affectation : présence existante → active → dernière → None
    existing = Presence.objects.filter(equipier=equipier, date=d, creneau=creneau).select_related('affectation').first()
    if existing and existing.affectation:
        aff = existing.affectation
    else:
        aff = (
            Affectation.objects.filter(equipe=equipier.equipe, date_debut__lte=d, date_fin__gte=d)
            .order_by('date_debut').first()
            or Affectation.objects.filter(equipe=equipier.equipe, date_fin__lt=d)
            .order_by('-date_fin').first()
        )

    code       = (data.get('code') or '').strip().upper()
    heures_raw = (data.get('heures') or '')
    heures = Decimal('0') if code else to_decimal(heures_raw, None)

    if heures is None and not code:
        Presence.objects.filter(equipier=equipier, date=d, creneau=creneau).delete()
        return JsonResponse({'ok': True, 'action': 'deleted'})

    # Heures = 0 pour les codes d'absence / jours fériés / ponts
    heures_val = heures if heures is not None else Decimal('0')
    Presence.objects.update_or_create(
        equipier=equipier, date=d, creneau=creneau,
        defaults={
            'affectation': aff,
            'heures':      heures_val,
            'code':        code,
            'saisi_par':   request.user,
        }
    )
    return JsonResponse({'ok': True, 'action': 'saved'})


@login_required
@require_POST
def fiche_note_save(request):
    """
    Sauvegarde du chantier et/ou de l'observation d'une semaine ISO (FicheNote).
    Endpoint partagé entre émargement hebdo et fiche mensuelle.
    """
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    try:
        equipier_id = int(data.get('equipier_id', 0))
        annee       = int(data.get('annee', 0))
        mois        = int(data.get('mois', 0))
        num_semaine = int(data.get('num_semaine', 0))
    except (ValueError, TypeError):
        return json_error('Paramètres invalides')

    equipier = Equipier.objects.select_related('equipe').filter(pk=equipier_id, actif=True).first()
    if not equipier or not equipier.equipe:
        return json_error('Équipier introuvable', status=404)

    if not est_encadrant(request.user, equipier.equipe):
        return JsonResponse({'ok': False, 'error': 'Permission refusée'}, status=403)

    defaults = {}
    if 'chantier_texte' in data:
        defaults['chantier_texte'] = (data['chantier_texte'] or '').strip()[:200]
    if 'observation_texte' in data:
        defaults['observation_texte'] = (data['observation_texte'] or '').strip()

    if defaults:
        FicheNote.objects.update_or_create(
            equipier=equipier, annee=annee, mois=mois, num_semaine=num_semaine,
            defaults=defaults,
        )

    return JsonResponse({'ok': True})


@login_required
@require_POST
def cloture_toggle(request):
    """
    Clôture / déverrouille un mois pour une équipe (fiche remise à la RH).
    Un mois clôturé bloque toute écriture de présences (émargement, fiche,
    prêts) pour les équipiers de l'équipe. Les notes de semaine (FicheNote)
    restent modifiables — choix acté session 36.
    """
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err
    try:
        equipe_id = int(data.get('equipe_id', 0))
        annee     = int(data.get('annee', 0))
        mois      = int(data.get('mois', 0))
    except (ValueError, TypeError):
        return json_error('Paramètres invalides')
    if not (1 <= mois <= 12 and 2020 <= annee <= 2100):
        return json_error('Mois invalide')

    equipe = Equipe.objects.filter(pk=equipe_id, actif=True, service__module_planning=True).first()
    if not equipe:
        return json_error('Équipe introuvable', status=404)
    if not est_encadrant(request.user, equipe):
        return json_error('Non autorisé sur cette équipe', status=403)

    existing = ClotureMois.objects.filter(equipe=equipe, annee=annee, mois=mois).first()
    if existing:
        existing.delete()
        return JsonResponse({'ok': True, 'cloture': False})
    ClotureMois.objects.create(equipe=equipe, annee=annee, mois=mois, cloture_par=request.user)
    return JsonResponse({'ok': True, 'cloture': True})


# ── Companion app Relevé ──────────────────────────────────────────────────────

@login_required
def releve_view(request):
    if not peut_acceder_planning(request.user):
        return redirect('core:dashboard')
    devis_qs = (
        Devis.objects.filter(status__in=['draft', 'accepted'])
        .select_related('client')
        .order_by('-created_at')[:100]
    )
    devis_json = json.dumps([
        {
            'id': d.id,
            'ref': d.reference,
            'client': str(d.client),
            'chantier': d.chantier or '',
        }
        for d in devis_qs
    ])
    preselect = request.GET.get('devis', '')
    return render(request, 'core/releve.html', {
        'devis_json': devis_json,
        'preselect': preselect,
    })


@login_required
@require_POST
def releve_import(request):
    if not peut_acceder_planning(request.user):
        return json_error_permission()
    data, err = parse_json_request(request)
    if err:
        return err

    devis_id = data.get('devis_id')
    lignes   = data.get('lignes', [])

    devis = get_object_or_404(Devis, pk=devis_id)
    if not peut_modifier_devis(request.user, devis):
        return json_error_permission()

    max_ordre = (
        LigneDevis.objects.filter(devis=devis, parent=None)
        .aggregate(m=Max('ordre'))['m'] or 0
    )

    def _create(nodes, parent, ordre_start):
        for i, node in enumerate(nodes):
            cu = node.get('cout_unitaire')
            ligne = LigneDevis.objects.create(
                devis=devis,
                parent=parent,
                type_ligne=node.get('type_ligne', 'S'),
                description=node.get('description', ''),
                quantite=to_decimal(node.get('quantite'), default=1),
                unite=(node.get('unite') or ''),
                cout_unitaire=None if cu is None else to_decimal(cu, default=None),
                ordre=ordre_start + i,
                ouvert=True,
            )
            _create(node.get('enfants') or [], ligne, 0)

    _create(lignes, None, max_ordre + 1)
    return JsonResponse({
        'ok': True,
        'devis_url': reverse('core:devis-detail', args=[devis.pk]),
    })
