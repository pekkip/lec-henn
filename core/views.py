import json
import random
import string
import re
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone

from .models import (
    Client, Devis, LigneDevis,
    Facture, LigneFacture, AuditLog, ProfilUtilisateur,
    Territoire, Service, Equipe, ParametresAssociation, Bibliotheque
)
from .permissions import (
    peut_modifier_devis, peut_supprimer_devis,
    peut_valider_facture, peut_envoyer_facture, peut_supprimer_facture,
    peut_supprimer_client, is_admin
)
# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def get_profil(user):
    """Retourne le profil de l'utilisateur, le crée si nécessaire."""
    profil, _ = ProfilUtilisateur.objects.get_or_create(user=user)
    return profil


def gen_reference(prefix):
    year = date.today().year
    if prefix == 'DEV':
        qs = Devis.objects.filter(
            reference__startswith=f'DEV-{year}-'
        )
    elif prefix == 'FAC':
        qs = Facture.objects.filter(
            type_doc='facture',
            numero__startswith=f'FAC-{year}-'
        )
    else:
        qs = Facture.objects.filter(
            type_doc='avoir',
            numero__startswith=f'AV-{year}-'
        )

    # Extrait les numéros existants et prend le max
    nums = []
    for obj in qs:
        ref = obj.reference if prefix == 'DEV' else obj.numero
        if ref:
            try:
                nums.append(int(ref.split('-')[-1]))
            except ValueError:
                pass

    next_num = max(nums) + 1 if nums else 1
    return f"{prefix}-{year}-{str(next_num).zfill(3)}"


def add_audit(user, action, devis=None, facture=None, bypass=False):
    AuditLog.objects.create(
        user=user, action=action,
        devis=devis, facture=facture, bypass=bypass
    )


def ligne_to_dict(ligne):
    mo = ligne.total_mo()
    mat = ligne.total_mat()
    return {
        'id': ligne.pk,
        'type_ligne': ligne.type_ligne,
        'description': ligne.description,
        'quantite': float(ligne.quantite),
        'unite': ligne.unite,
        'cout_unitaire': float(ligne.cout_unitaire) if ligne.cout_unitaire is not None else None,
        'cout_mo': float(mo) if mo is not None else None,
        'cout_mat': float(mat) if mat is not None else None,
        'total': float(ligne.total()),
        'ordre': ligne.ordre,
        'ouvert': ligne.ouvert,
        'parent_id': ligne.parent_id,
        'enfants': [ligne_to_dict(e) for e in ligne.enfants.all()],
    }


def ligne_facture_to_dict(ligne, deja_par_source=None):
    """
    Sérialise une LigneFacture en dict JSON pour le frontend.

    deja_par_source : dict {ligne_devis_source_id: montant_total_deja_facture}
    Calculé une fois pour toute la facture et passé en paramètre (évite N+1).

    # PROTO : le calcul du "déjà facturé" est fait depuis les factures validées
    # uniquement (status='validated', 'sent', 'paid'). Les brouillons ne comptent pas.
    """
    if deja_par_source is None:
        deja_par_source = {}

    source_id = ligne.ligne_devis_source_id
    deja = float(deja_par_source.get(source_id, 0)) if source_id else 0

    return {
        'id': ligne.pk,
        'type_ligne': ligne.type_ligne,
        'description': ligne.description,
        'quantite': float(ligne.quantite),
        'quantite_originale': float(ligne.quantite_originale),
        'unite': ligne.unite,
        'cout_unitaire': float(ligne.cout_unitaire) if ligne.cout_unitaire is not None else None,
        'ordre': ligne.ordre,
        'ouvert': ligne.ouvert,
        'parent_id': ligne.parent_id,
        'deja_facture': deja,           # montant déjà facturé sur les factures précédentes validées
        'ligne_devis_source_id': source_id,
        'enfants': [ligne_facture_to_dict(e, deja_par_source) for e in ligne.enfants.all()],
    }


def copier_lignes_devis_vers_facture(lignes_devis, facture, parent_facture=None, ordre=0):
    """
    Copie récursivement les lignes du devis vers la facture.

    Différence vs version précédente :
    - quantite est initialisée à la qté du devis
      → l'utilisateur modifit ce qu'il veut facturer, 
    - ligne_devis_source est renseigné pour tracer l'origine
      → permet de calculer "déjà facturé" sur les factures suivantes

    # PROTO : quantite est initialisée avec la qté du devis (pas à 0).
    # L'utilisateur met à 0 ou ajuste ce qu'il ne veut pas facturer.
    # quantite_originale garde la qté devis figée comme référence (snapshot)
    """
    for ligne in lignes_devis:
        lf = LigneFacture.objects.create(
            facture=facture,
            parent=parent_facture,
            type_ligne=ligne.type_ligne,
            description=ligne.description,
            quantite=ligne.quantite,         # ← qté devis
            quantite_originale=ligne.quantite,  # qté devis figée au snapshot
            unite=ligne.unite,
            cout_unitaire=ligne.cout_unitaire,
            ordre=ordre,
            ouvert=ligne.ouvert,
            ligne_devis_source=ligne,       # ← NOUVEAU : traçabilité
        )
        if ligne.enfants.exists():
            copier_lignes_devis_vers_facture(
                ligne.enfants.all(), facture, lf, 0
            )
        ordre += 1


# ══════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════

def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    error = None
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user:
            login(request, user)
            return redirect('core:dashboard')
        error = "Identifiants incorrects."
    return render(request, 'core/login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('core:login')

@login_required
def profil_view(request):
    profil = get_profil(request.user)
    if request.method == 'POST':
        # Infos personnelles
        request.user.first_name = request.POST.get('first_name', '').strip()
        request.user.last_name = request.POST.get('last_name', '').strip()
        request.user.email = request.POST.get('email', '').strip()
        request.user.save()
        # Préférences
        taux = request.POST.get('taux_mo_defaut', '').strip().replace(',', '.')
        if taux:
            try:
                profil.taux_mo_defaut = Decimal(taux)
            except Exception:
                messages.error(request, 'Taux MO invalide.')
                return redirect('core:profil')
        profil.saisie_ht = request.POST.get('saisie_ht') == 'on'
        profil.conditions_devis = request.POST.get('conditions_devis', '').strip()
        profil.conditions_facture = request.POST.get('conditions_facture', '').strip()
        profil.save()
        messages.success(request, 'Profil mis à jour.')
        return redirect('core:profil')
    return render(request, 'core/profil.html', {'profil': profil})

    
# ══════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════

@login_required
def dashboard(request):
    profil = get_profil(request.user)
    devis_recents = Devis.objects.select_related('client', 'equipe').all()[:5]
    factures_recentes = Facture.objects.select_related('devis').all()[:5]
    stats = {
        'ca': sum(d.total_brut() for d in Devis.objects.filter(status='accepted')),
        'en_attente': sum(
            f.montant for f in Facture.objects.filter(
                type_doc='facture'
            ).exclude(status='paid')
        ),
        'en_cours': Devis.objects.filter(status__in=['draft', 'sent']).count(),
        'total_devis': Devis.objects.count(),
    }
    stats['taux'] = round(
        Devis.objects.filter(status='accepted').count() / stats['total_devis'] * 100
    ) if stats['total_devis'] else 0
    for d in devis_recents:
        d.rtf = d.reste_a_facturer()
    return render(request, 'core/dashboard.html', {
        'devis_recents': devis_recents,
        'factures_recentes': factures_recentes,
        'stats': stats,
        'profil': profil,
    })


# ══════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════

@login_required
def clients_list(request):
    clients = Client.objects.all()
    return render(request, 'core/clients.html', {'clients': clients})


@login_required
@require_POST
def client_create(request):
    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, 'Le nom est obligatoire.')
        return redirect('core:clients')
    Client.objects.create(
        nom=nom,
        contact=request.POST.get('contact', ''),
        email=request.POST.get('email', ''),
        telephone=request.POST.get('telephone', ''),
        adresse=request.POST.get('adresse', ''),
    )
    messages.success(request, f'Client "{nom}" créé.')
    return redirect('core:clients')


@login_required
@require_POST
def client_delete(request, pk):
    if not is_admin(request.user):
        messages.error(request, 'Action réservée à l\'administrateur.')
        return redirect('core:clients')
    client = get_object_or_404(Client, pk=pk)
    nom = client.nom
    client.delete()
    messages.success(request, f'Client "{nom}" supprimé.')
    return redirect('core:clients')

# ══════════════════════════════════════════
#  BIBLIOTHÈQUE PERSONNELLE (API JSON)
# ══════════════════════════════════════════

@login_required
def bibliotheque(request):
    profil = get_profil(request.user)
    return render(request, 'core/bibliotheque.html', {
        'profil': profil,
        'taux_mo_js': str(profil.taux_mo_defaut).replace(',', '.'),
    })

@login_required
def biblio_api_get(request):
    biblio, _ = Bibliotheque.objects.get_or_create(user=request.user)
    profil = get_profil(request.user)
    return JsonResponse({
        'lignes': biblio.lignes,
        'taux_mo': float(profil.taux_mo_defaut),
    })

@login_required
@require_POST
def biblio_api_save(request):
    biblio, _ = Bibliotheque.objects.get_or_create(user=request.user)
    try:
        data = json.loads(request.body)
        biblio.lignes = data.get('lignes', [])
        biblio.save()
        return JsonResponse({'ok': True})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)


# ══════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════

@login_required
def clients_list(request):
    clients = Client.objects.all()
    return render(request, 'core/clients.html', {'clients': clients})


@login_required
@require_POST
def client_create(request):
    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, 'Le nom est obligatoire.')
        return redirect('core:clients')
    Client.objects.create(
        nom=nom,
        contact=request.POST.get('contact', ''),
        email=request.POST.get('email', ''),
        telephone=request.POST.get('telephone', ''),
        adresse=request.POST.get('adresse', ''),
    )
    messages.success(request, f'Client "{nom}" créé.')
    return redirect('core:clients')


@login_required
@require_POST
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    nom = client.nom
    client.delete()
    messages.success(request, f'Client "{nom}" supprimé.')
    return redirect('core:clients')


# ══════════════════════════════════════════
#  DEVIS — LISTE
# ══════════════════════════════════════════

@login_required
def devis_list(request):
    profil = get_profil(request.user)
    qs = Devis.objects.select_related('client', 'equipe__service__territoire').all()

    # Filtres
    status = request.GET.get('status', '')
    client_id = request.GET.get('client', '')
    equipe_id = request.GET.get('equipe', '')
    service_id = request.GET.get('service', '')
    territoire_id = request.GET.get('territoire', '')
    q = request.GET.get('q', '')

    if status:
        qs = qs.filter(status=status)
    if client_id:
        qs = qs.filter(client_id=client_id)
    if equipe_id:
        qs = qs.filter(equipe_id=equipe_id)
    if service_id:
        qs = qs.filter(equipe__service_id=service_id)
    if territoire_id:
        qs = qs.filter(equipe__service__territoire_id=territoire_id)
    if q:
        qs = qs.filter(
            chantier__icontains=q
        ) | qs.filter(
            client__nom__icontains=q
        ) | qs.filter(
            reference__icontains=q
        )

    for d in qs:
        d.rtf = d.reste_a_facturer()

    return render(request, 'core/devis_list.html', {
        'devis': qs,
        'clients': Client.objects.all(),
        'equipes': Equipe.objects.select_related('service__territoire').all(),
        'services': Service.objects.select_related('territoire').all(),
        'territoires': Territoire.objects.all(),
        'profil': profil,
        'status_filter': status,
        'client_filter': client_id,
        'equipe_filter': equipe_id,
        'service_filter': service_id,
        'territoire_filter': territoire_id,
        'q': q,
        'peut_supprimer': {d.pk: peut_supprimer_devis(request.user, d) for d in qs},  # ← ici
    })


# ══════════════════════════════════════════
#  DEVIS — CRÉATION
# ══════════════════════════════════════════

@login_required
def devis_create(request):
    profil = get_profil(request.user)
    if request.method == 'POST':
        client_id = request.POST.get('client')
        chantier = request.POST.get('chantier', '').strip()
        if not client_id or not chantier:
            messages.error(request, 'Client et chantier sont obligatoires.')
            return redirect('core:devis-list')
        client = get_object_or_404(Client, pk=client_id)
        equipe_id = request.POST.get('equipe') or None
        validite_jours = int(request.POST.get('validite_jours', 30))
        devis = Devis.objects.create(
            reference=gen_reference('DEV'),
            client=client,
            chantier=chantier,
            equipe_id=equipe_id,
            date_validite=date.today() + timedelta(days=validite_jours),
            taux_mo=Decimal(request.POST.get('taux_mo') or profil.taux_mo_defaut),
            notes=request.POST.get('notes', ''),
            conditions_devis=profil.conditions_devis,
            created_by=request.user,
        )
        add_audit(
            request.user,
            f"Création devis {devis.reference} — {client.nom} · {chantier}",
            devis=devis
        )
        return redirect('core:devis-detail', pk=devis.pk)

    # Déterminer les équipes disponibles selon le profil
    if profil.service:
        equipes = Equipe.objects.filter(
            service__territoire=profil.get_territoire()
        ).select_related('service')
    else:
        equipes = Equipe.objects.select_related('service').all()

    return render(request, 'core/devis_form.html', {
        'clients': Client.objects.all(),
        'equipes': equipes,
        'profil': profil,
    })


# ══════════════════════════════════════════
#  DEVIS — DÉTAIL
# ══════════════════════════════════════════

@login_required
def devis_detail(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    profil = get_profil(request.user)
    factures = devis.factures.all()
    audit_logs = devis.audit_logs.all()



    circuit_steps = [
        ('ti-file-plus', 'var(--gray-lt)', 'var(--gray-bd)', 'Brouillon auto'),
        ('ti-user-check', '#E6F1FB', '#B5D4F4', 'Validation comptable'),
        ('ti-circle-check', 'var(--teal-lt)', 'var(--teal-bd)', 'Validée'),
        ('ti-send', 'var(--prune-lt)', 'var(--prune-bd)', 'Envoyée'),
        ('ti-cash', '#EAF3DE', '#C0DD97', 'Payée'),
    ]

    taux_mo_js = str(devis.taux_mo).replace(',', '.')
    articles_biblio = []
    return render(request, 'core/devis_detail.html', {
        'devis': devis,
        'factures': factures,
        'audit_logs': audit_logs,
        'articles_biblio': articles_biblio,
        'circuit_steps': circuit_steps,
        'profil': profil,
        'taux_mo_js': taux_mo_js,
        'clients': Client.objects.all(),
        'equipes': Equipe.objects.select_related('service__territoire').all(),
    })


@login_required
@require_POST
def devis_status(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    old = devis.status
    devis.status = request.POST.get('status', devis.status)
    devis.save()
    add_audit(
        request.user,
        f"Statut devis {devis.reference} : {old} → {devis.status}",
        devis=devis
    )
    return redirect('core:devis-detail', pk=pk)


@login_required
def devis_duplicate(request, pk):
    src = get_object_or_404(Devis, pk=pk)
    profil = get_profil(request.user)
    new_devis = Devis.objects.create(
        reference=gen_reference('DEV'),
        client=src.client,
        chantier=src.chantier + ' (copie)',
        equipe=src.equipe,
        status='draft',
        date_validite=date.today() + timedelta(days=30),
        taux_mo=src.taux_mo,
        notes=src.notes,
        conditions_devis=src.conditions_devis,
        fin_group_title=src.fin_group_title,
        created_by=request.user,
    )

    def copy_lignes(lignes, parent=None):
        for l in lignes:
            new_l = LigneDevis.objects.create(
                devis=new_devis, parent=parent,
                type_ligne=l.type_ligne,
                description=l.description,
                quantite=l.quantite,
                unite=l.unite,
                cout_unitaire=l.cout_unitaire,
                ordre=l.ordre,
            )
            copy_lignes(l.enfants.all(), parent=new_l)

    copy_lignes(src.lignes.filter(parent=None))
    add_audit(
        request.user,
        f"Duplication {src.reference} → {new_devis.reference}",
        devis=new_devis
    )
    return redirect('core:devis-detail', pk=new_devis.pk)


@login_required
@require_POST
def devis_delete(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    if not peut_supprimer_devis(request.user, devis):
        messages.error(request, 'Vous ne pouvez pas supprimer ce devis.')
        return redirect('core:devis-list')
    ref = devis.reference
    devis.delete()
    messages.success(request, f'Devis {ref} supprimé.')
    return redirect('core:devis-list')


def assign_numbers_python(lignes, prefix=''):
    flat = []
    local_counter = [0]

    for ligne in lignes:
        if ligne.type_ligne in ('TITRE', 'S'):
            local_counter[0] += 1
            num = f"{prefix}{local_counter[0]}" if prefix else str(local_counter[0])
        else:
            num = ''

        ligne.num = num
        flat.append(ligne)

        # On descend uniquement dans les TITRE
        if ligne.type_ligne == 'TITRE':
            enfants = list(ligne.enfants.all())
            if enfants:
                flat.extend(assign_numbers_python(enfants, prefix=f"{num}."))

    return flat


@login_required
def devis_pdf(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    factures = devis.factures.exclude(status='cancelled')
    params = ParametresAssociation.get()

    # Lignes racines (parent=None), séparées FIN / reste
    racines_pos = list(
        devis.lignes.filter(parent=None).exclude(type_ligne='FIN').prefetch_related('enfants')
    )
    racines_fin = list(
        devis.lignes.filter(parent=None, type_ligne='FIN').prefetch_related('enfants')
    )

    # Arbre aplati avec numérotation
    lignes_pos = assign_numbers_python(racines_pos)
    lignes_fin = assign_numbers_python(racines_fin)

    # Date d'expiry (utilisée dans le template)
    expiry = devis.date_validite

    return render(request, 'core/devis_pdf.html', {
        'devis': devis,
        'factures': factures,
        'lignes_pos': lignes_pos,
        'lignes_fin': lignes_fin,
        'params': params,
        'expiry': expiry,
    })

@login_required
@require_POST
def devis_entete_save(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    if not peut_modifier_devis(request.user, devis):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    # Client
    client_id = data.get('client_id')
    if client_id:
        client = get_object_or_404(Client, pk=client_id)
        devis.client = client

    # Équipe (peut être vide)
    equipe_id = data.get('equipe_id')
    if equipe_id:
        devis.equipe = get_object_or_404(Equipe, pk=equipe_id)
    else:
        devis.equipe = None

    # Chantier (obligatoire)
    chantier = data.get('chantier', '').strip()
    if chantier:
        devis.chantier = chantier

    # Adresse chantier
    devis.chantier_adresse1 = data.get('chantier_adresse1', '').strip()
    devis.chantier_adresse2 = data.get('chantier_adresse2', '').strip()
    devis.chantier_cp       = data.get('chantier_cp', '').strip()
    devis.chantier_ville    = data.get('chantier_ville', '').strip()

    # Notes et conditions
    devis.notes            = data.get('notes', '').strip()
    devis.conditions_devis = data.get('conditions_devis', '').strip()

    # Date de validité
    date_validite_str = data.get('date_validite', '')
    if date_validite_str:
        try:
            from datetime import datetime as dt
            devis.date_validite = dt.strptime(date_validite_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Taux MO
    taux_mo = data.get('taux_mo')
    if taux_mo is not None:
        try:
            devis.taux_mo = Decimal(str(taux_mo))
        except Exception:
            pass

    devis.save()
    add_audit(
        request.user,
        f"Modification en-tête devis {devis.reference}",
        devis=devis
    )
    return JsonResponse({
        'ok': True,
        'client_nom': devis.client.nom,
        'chantier': devis.chantier,
        'equipe': str(devis.equipe) if devis.equipe else '',
        'taux_mo': float(devis.taux_mo),
    })

    
# ══════════════════════════════════════════
#  LIGNES DEVIS (API JSON)
# ══════════════════════════════════════════

@login_required
def lignes_get(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    racines = devis.lignes.filter(parent=None)
    data = [ligne_to_dict(l) for l in racines]
    return JsonResponse({
        'lignes': data,
        'taux_mo': float(devis.taux_mo),
        'fin_group_title': devis.fin_group_title or 'Financements',
    })


@login_required
@require_POST
def lignes_save(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    if not peut_modifier_devis(request.user, devis):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    try:
        data = json.loads(request.body)
        lignes = data.get('lignes', [])
        fin_group_title = data.get('fin_group_title', 'Financements')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    devis.lignes.all().delete()

    def create_lignes(items, parent=None, ordre=0):
        for item in items:
            cout = item.get('cout_unitaire')
            ligne = LigneDevis.objects.create(
                devis=devis, parent=parent,
                type_ligne=item.get('type_ligne', 'F'),
                description=item.get('description', ''),
                quantite=Decimal(str(item.get('quantite', 1))),
                unite=item.get('unite', ''),
                cout_unitaire=Decimal(str(cout)) if cout is not None else None,
                ordre=ordre,
                ouvert=item.get('ouvert', True),
            )
            create_lignes(item.get('enfants', []), parent=ligne)
            ordre += 1

    create_lignes(lignes)
    devis.fin_group_title = fin_group_title
    devis.updated_at = timezone.now()
    devis.save()

    return JsonResponse({
        'ok': True,
        'total_brut': float(devis.total_brut()),
        'net_client': float(devis.net_client()),
    })


# ══════════════════════════════════════════
#  FACTURES
# ══════════════════════════════════════════

@login_required
def factures_list(request):
    factures = Facture.objects.select_related(
        'devis', 'devis__client', 'devis__equipe'
    ).all()
    return render(request, 'core/factures_list.html', {'factures': factures})


@login_required
@require_POST
def facture_create(request, devis_pk):
    devis = get_object_or_404(Devis, pk=devis_pk)
    profil = get_profil(request.user)
    type_doc = request.POST.get('type_doc', 'facture')
    echeance_jours = int(request.POST.get('echeance_jours', 30))

    facture = Facture.objects.create(
        # Pas de numéro — assigné à la validation
        type_doc=type_doc,
        devis=devis,
        destinataire=request.POST.get('destinataire', devis.client.nom),
        montant=0,  # calculé depuis les lignes
        date_echeance=date.today() + timedelta(days=echeance_jours),
        notes=request.POST.get('notes', ''),
        conditions_facture=profil.conditions_facture,
        created_by=request.user,
    )

    # Copier les lignes du devis vers la facture
    copier_lignes_devis_vers_facture(
        devis.lignes.filter(parent=None),
        facture
    )

    type_label = 'Avoir' if type_doc == 'avoir' else 'Facture'
    add_audit(
        request.user,
        f"Génération {type_label} (brouillon) — {devis.reference} · {facture.destinataire}",
        devis=devis, facture=facture
    )
    return redirect('core:devis-detail', pk=devis_pk)


@login_required
@require_POST
def facture_valider(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_valider_facture(request.user, facture):
        messages.error(request, 'Validation réservée au comptable.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
    if not facture.numero:
        prefix = 'AV' if facture.type_doc == 'avoir' else 'FAC'
        facture.numero = gen_reference(prefix)
    facture.status = 'validated'
    facture.validated_by = request.user
    facture.validated_at = timezone.now()
    facture.save()
    add_audit(
        request.user,
        f"Validation comptable {facture.numero} ({facture.destinataire})",
        devis=facture.devis, facture=facture
    )
    return redirect('core:devis-detail', pk=facture.devis.pk)


@login_required
@require_POST
def facture_status(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    old = facture.status
    new_status = request.POST.get('status', facture.status)
    facture.status = new_status
    facture.save()
    add_audit(
        request.user,
        f"Statut {facture.get_reference()} : {old} → {new_status}",
        devis=facture.devis, facture=facture
    )
    return redirect('core:devis-detail', pk=facture.devis.pk)


@login_required
@require_POST
def facture_bypass(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    code = request.POST.get('code', '')
    stored = request.session.get(f'bypass_code_{pk}')
    if not stored or code != stored:
        return JsonResponse({'error': 'Code incorrect'}, status=400)
    if not facture.numero:
        prefix = 'AV' if facture.type_doc == 'avoir' else 'FAC'
        facture.numero = gen_reference(prefix)
    facture.status = 'validated'
    facture.bypass_validation = True
    facture.validated_by = request.user
    facture.validated_at = timezone.now()
    facture.save()
    del request.session[f'bypass_code_{pk}']
    add_audit(
        request.user,
        f"Bypass comptable {facture.numero} ({facture.destinataire}) — code e-mail utilisé",
        devis=facture.devis, facture=facture, bypass=True
    )
    return JsonResponse({'ok': True, 'redirect': f'/devis/{facture.devis.pk}/'})

@login_required
@require_POST
def facture_delete(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if facture.status != 'draft':
        messages.error(request, 'Seules les factures en brouillon peuvent être supprimées.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
    devis = facture.devis
    ref = facture.get_reference()
    add_audit(request.user, f"Suppression facture brouillon {ref}", devis=devis)
    facture.delete()
    messages.success(request, f'Facture {ref} supprimée.')
    return redirect('core:devis-detail', pk=devis.pk)

@login_required
def facture_bypass_send_code(request, pk):
    code = ''.join(random.choices(string.digits, k=6))
    request.session[f'bypass_code_{pk}'] = code
    return JsonResponse({'ok': True, 'code': code})


def calc_deja_facture_par_source(devis, facture_courante):
    """
    Retourne un dict {ligne_devis_id: montant_total_facture} pour toutes les
    factures VALIDÉES du devis, en excluant la facture courante.

    Statuts comptabilisés : validated, sent, paid.
    Exclus : draft, cancelled.

    # PROTO : on agrège par ligne_devis_source_id. Si une facture n'a pas ce champ
    # renseigné (factures créées avant session 6), elle est ignorée dans le calcul.
    """
    STATUTS_VALIDES = ('validated', 'sent', 'paid')

    factures_prec = devis.factures.filter(
        status__in=STATUTS_VALIDES,
        type_doc='facture',
    ).exclude(pk=facture_courante.pk)

    deja = {}
    for f in factures_prec:
        for lf in f.lignes.filter(parent=None):
            _agreger_ligne(lf, deja)

    return deja


def _agreger_ligne(ligne, deja):
    """Parcourt récursivement et accumule les montants par source."""
    if ligne.ligne_devis_source_id:
        montant = float(ligne.total())
        deja[ligne.ligne_devis_source_id] = deja.get(ligne.ligne_devis_source_id, 0) + montant
    for enfant in ligne.enfants.all():
        _agreger_ligne(enfant, deja)


# ──────────────────────────────────────────
#  VUE — Détail / éditeur d'une facture
#  NOUVELLE — URL : /factures/<pk>/
# ──────────────────────────────────────────

@login_required
def facture_detail(request, pk):
    """
    Page d'édition d'une facture brouillon.
    Accessible depuis l'onglet Factures du devis.

    # PROTO : pour l'instant, toute personne connectée peut accéder.
    # À terme : restreindre selon rôle (voir notes session 6).
    """
    facture = get_object_or_404(Facture, pk=pk)
    devis = facture.devis
    profil = get_profil(request.user)

    # Factures précédentes validées sur le même devis (pour le récapitulatif)
    # PROTO : on affiche toutes les factures validées, pas les avoirs.
    STATUTS_VALIDES = ('validated', 'sent', 'paid')
    factures_prec = devis.factures.filter(
        status__in=STATUTS_VALIDES,
        type_doc='facture',
    ).exclude(pk=facture.pk).order_by('created_at')

    # Totaux pour le footer
    total_devis = float(devis.total_brut())
    total_deja = float(devis.total_facture())  # méthode existante sur Devis

    return render(request, 'core/facture_detail.html', {
        'facture': facture,
        'devis': devis,
        'profil': profil,
        'factures_prec': factures_prec,
        'total_devis': total_devis,
        'total_deja': total_deja,
        'modifiable': facture.status == 'draft',
    })


# ──────────────────────────────────────────
#  VUE — Aperçu imprimable d'une facture
#  NOUVELLE — URL : /factures/<pk>/apercu/
# ──────────────────────────────────────────

@login_required
def facture_apercu(request, pk):
    """
    Aperçu HTML imprimable de la facture.
    Lecture seule — même données que facture_detail.
    window.print() déclenché par un bouton, CSS @media print intégré.

    # PROTO : remplacé par WeasyPrint en Phase 3.
    # Affiche uniquement les lignes avec quantite > 0.
    """
    facture = get_object_or_404(Facture, pk=pk)
    devis = facture.devis

    from .models import ParametresAssociation
    params = ParametresAssociation.get()

    # Lignes racines avec quantite > 0 uniquement (vue client)
    # PROTO : règle d'affichage à affiner selon retours Frédérick/Yann
    def filtrer_lignes(lignes_qs):
        result = []
        for lf in lignes_qs:
            if lf.type_ligne == 'TITRE':
                enfants = filtrer_lignes(lf.enfants.all())
                if enfants:  # titre affiché seulement s'il a des enfants visibles
                    lf._enfants_filtres = enfants
                    result.append(lf)
            else:
                if float(lf.quantite) > 0:
                    result.append(lf)
        return result

    lignes_filtrees = filtrer_lignes(facture.lignes.filter(parent=None))

    return render(request, 'core/facture_apercu.html', {
        'facture': facture,
        'devis': devis,
        'params': params,
        'lignes': lignes_filtrees,
    })


# ──────────────────────────────────────────
#  VUE — Sauvegarde du libellé inline
#  NOUVELLE — URL : /factures/<pk>/libelle/
# ──────────────────────────────────────────

@login_required
@require_POST
def facture_libelle_save(request, pk):
    """
    Sauvegarde le libellé court d'une facture (éditable inline dans le
    récapitulatif des factures précédentes).

    # PROTO : pas de validation de longueur côté serveur pour l'instant.
    # max_length=200 est géré par le modèle.
    """
    facture = get_object_or_404(Facture, pk=pk)
    try:
        data = json.loads(request.body)
        libelle = data.get('libelle', '').strip()[:200]
        facture.libelle = libelle
        facture.save(update_fields=['libelle'])
        return JsonResponse({'ok': True, 'libelle': libelle})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

# ══════════════════════════════════════════
#  LIGNES FACTURE (API JSON)
# ══════════════════════════════════════════

@login_required
def lignes_facture_get(request, pk):
    """
    Retourne les lignes de la facture + montant "déjà facturé" par ligne.

    # PROTO : deja_par_source est calculé à chaque appel.
    # Optimisation possible si les factures sont nombreuses.
    """
    facture = get_object_or_404(Facture, pk=pk)
    deja_par_source = calc_deja_facture_par_source(facture.devis, facture)
    racines = facture.lignes.filter(parent=None)
    data = [ligne_facture_to_dict(l, deja_par_source) for l in racines]

    # Factures précédentes pour le récapitulatif JS (libellé + montant global)
    STATUTS_VALIDES = ('validated', 'sent', 'paid')
    factures_prec = facture.devis.factures.filter(
        status__in=STATUTS_VALIDES,
        type_doc='facture',
    ).exclude(pk=facture.pk).order_by('created_at')

    factures_prec_data = [
        {
            'pk': f.pk,
            'reference': f.get_reference(),
            'libelle': f.libelle or '',
            'montant': float(f.montant),
            'libelle_save_url': f'/factures/{f.pk}/libelle/',
        }
        for f in factures_prec
    ]

    return JsonResponse({
        'lignes': data,
        'montant': float(facture.montant),
        'taux_mo': float(facture.devis.taux_mo),
        'total_devis': float(facture.devis.total_brut()),
        'total_deja': float(facture.devis.total_facture()),
        'factures_prec': factures_prec_data,
    })

@login_required
@require_POST
def facture_delete(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if facture.status != 'draft':
        messages.error(request, 'Seules les factures en brouillon peuvent être supprimées.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
    devis_pk = facture.devis.pk
    ref = facture.get_reference()
    facture.delete()
    add_audit(request.user, f"Suppression facture brouillon {ref}", devis=facture.devis)
    messages.success(request, f'Facture {ref} supprimée.')
    return redirect('core:devis-detail', pk=devis_pk)

    
@login_required
@require_POST
def lignes_facture_save(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if facture.status != 'draft':
        return JsonResponse({'error': 'Facture non modifiable'}, status=400)
    try:
        data = json.loads(request.body)
        notes = data.get('notes', None)
        if notes is not None:
            facture.notes = notes
        lignes = data.get('lignes', [])
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    facture.lignes.all().delete()

    def create_lignes(items, parent=None, ordre=0):
        for item in items:
            cout = item.get('cout_unitaire')
            lf = LigneFacture.objects.create(
                facture=facture, parent=parent,
                type_ligne=item.get('type_ligne', 'F'),
                description=item.get('description', ''),
                quantite=Decimal(str(item.get('quantite', 1))),
                quantite_originale=Decimal(str(item.get('quantite_originale', item.get('quantite', 1)))),
                unite=item.get('unite', ''),
                cout_unitaire=Decimal(str(cout)) if cout is not None else None,
                ordre=ordre,
                ouvert=item.get('ouvert', True),
            )
            create_lignes(item.get('enfants', []), parent=lf)
            ordre += 1

    create_lignes(lignes)

    # Recalculer le montant total de la facture
    total = sum(l.total() for l in facture.lignes.filter(parent=None))
    facture.montant = total
    facture.save()

    return JsonResponse({'ok': True, 'montant': float(total)})