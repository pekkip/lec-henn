import io
import json
import logging
import math
import random
import string
import re
from calendar import monthrange
from datetime import date, timedelta, datetime
from datetime import datetime as dt
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden

logger = logging.getLogger(__name__)

from django.db.models import Prefetch, Count

from .models import (
    Client, ContactClient, Devis, LigneDevis,
    Facture, LigneFacture, AuditLog, ProfilUtilisateur,
    Territoire, Service, Equipe, ParametresAssociation, Bibliotheque,
    BibliothèqueAides,
    Equipier, TrancheDevis, Affectation, Presence, Evenement, Pret,
    FicheNote, ClotureMois, Financeur,
)
from .permissions import (
    peut_modifier_devis, peut_supprimer_devis, peut_voir_devis,
    peut_valider_facture, peut_envoyer_facture, peut_supprimer_facture,
    peut_voir_facture, peut_modifier_facture,
    peut_supprimer_client, is_admin,
    peut_gerer_utilisateurs, peut_gerer_cet_utilisateur,
    get_collegues_ids, peut_acceder_compta,
    peut_acceder_planning, est_encadrant,
)
from .dashboard_widgets import resolve_dashboard, sanitize_config
from .totaux import attacher_totaux_devis, total_mo_devis
# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def get_profil(user):
    """Retourne le profil de l'utilisateur, le crée si nécessaire."""
    profil, _ = ProfilUtilisateur.objects.get_or_create(user=user)
    return profil


def to_decimal(val, default=None):
    if val is None or val == '':
        return default
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return default


def paginer(request, queryset, par_page=50):
    """Pagine un queryset et renvoie (page_obj, base_qs).

    `base_qs` = la query string courante SANS le paramètre `page`, pour
    construire des liens de pagination qui conservent les filtres actifs.
    """
    page_obj = Paginator(queryset, par_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page_obj, params.urlencode()


def gen_reference(prefix):
    year = date.today().year
    if prefix == 'DEV':
        qs = Devis.objects.filter(
            reference__startswith=f'DEV-{year}-'
        )
    elif prefix == 'FAC':
        # Cherche dans toutes les factures (acomptes inclus) pour éviter
        # les collisions sur le champ unique `numero`
        qs = Facture.objects.filter(
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


# Numérotation des factures : découple le préfixe AFFICHÉ de la SÉQUENCE de comptage.
# Pour basculer les appels sur la séquence FAC (en gardant le préfixe APP), il suffit
# de passer 'appel' -> {'prefix': 'APP', 'sequence': 'FAC'} (une ligne).
NUMEROTATION_FACTURE = {
    'facture':   {'prefix': 'FAC', 'sequence': 'FAC'},
    'acompte':   {'prefix': 'FAC', 'sequence': 'FAC'},
    'structure': {'prefix': 'FAC', 'sequence': 'FAC'},  # partage la séquence FAC
    'appel':     {'prefix': 'APP', 'sequence': 'APP'},  # séquence propre (pour l'instant)
    'avoir':     {'prefix': 'AV',  'sequence': 'AV'},
}


def gen_numero_facture(type_doc):
    """Génère le prochain numéro de facture selon le type_doc (préfixe + séquence)."""
    cfg = NUMEROTATION_FACTURE.get(type_doc, NUMEROTATION_FACTURE['facture'])
    prefix, seq = cfg['prefix'], cfg['sequence']
    year = date.today().year
    group = [td for td, c in NUMEROTATION_FACTURE.items() if c['sequence'] == seq]
    qs = Facture.objects.filter(type_doc__in=group, numero__isnull=False)
    nums = []
    for f in qs:
        tail = f.numero.split('-')[-1] if f.numero else ''
        if tail.isdigit():
            nums.append(int(tail))
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
        'aide_id': ligne.aide_id,
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

def aide_view(request):
    return render(request, 'core/aide.html')

def aide_insertion_view(request):
    return render(request, 'core/aide_insertion.html')


DOMAINE_AUTORISE = 'compagnonsbatisseurs.eu'

def mot_de_passe_oublie(request):
    succes = False
    erreur = None

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        if not email.endswith(f'@{DOMAINE_AUTORISE}'):
            erreur = f'Seules les adresses @{DOMAINE_AUTORISE} sont acceptées.'
        else:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                mdp_temp = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                try:
                    send_mail(
                        subject='Réinitialisation de votre mot de passe CB Bretagne',
                        message=(
                            f'Bonjour {user.first_name or user.username},\n\n'
                            f'Votre mot de passe a été réinitialisé suite à votre demande.\n\n'
                            f'Identifiant : {user.username}\n'
                            f'Mot de passe temporaire : {mdp_temp}\n\n'
                            f'Connectez-vous ici : {settings.SITE_URL}/login/\n\n'
                            f'Pensez à changer votre mot de passe après connexion.\n\n'
                            f'CB Bretagne'
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        fail_silently=False,
                    )
                    # MDP changé seulement si l'email est parti — évite de bloquer l'accès
                    user.set_password(mdp_temp)
                    user.save()
                except Exception as e:
                    logger.error('Password reset email error (user %s): %s', user.username, e)
            # Même message qu'un email inexistant pour éviter l'énumération
            succes = True

    return render(request, 'core/mot_de_passe_oublie.html', {
        'succes': succes,
        'erreur': erreur,
        'domaine': DOMAINE_AUTORISE,
    })


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
        profil.coordonnees_cb = request.POST.get('coordonnees_cb', '').strip()
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
    visibles, disponibles = resolve_dashboard(profil, request.user)
    return render(request, 'core/dashboard.html', {
        'widgets': visibles,
        'widgets_disponibles': disponibles,
        'profil': profil,
    })


@login_required
@require_POST
def dashboard_save(request):
    """Enregistre la disposition du tableau de bord (ordre + hidden + scope).

    Ignore les ids inconnus et les widgets compta si l'utilisateur n'y a pas
    droit (cf. sanitize_config). Renvoie du JSON.
    """
    profil = get_profil(request.user)
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

    widgets = sanitize_config(payload.get('widgets'), request.user)
    profil.dashboard_config = {'widgets': widgets}
    profil.save(update_fields=['dashboard_config'])
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════

@login_required
def clients_list(request):
    nom = request.GET.get('nom', '').strip()
    code_postal = request.GET.get('code_postal', '').strip()
    departement = request.GET.get('departement', '').strip()
    ville = request.GET.get('ville', '').strip()
    portee = request.GET.get('portee', 'tous')
    type_client = request.GET.get('type_client', '').strip()

    clients = Client.objects.all()
    if nom:
        clients = clients.filter(nom__icontains=nom)
    if code_postal:
        clients = clients.filter(code_postal__startswith=code_postal)
    if departement:
        clients = clients.filter(code_postal__startswith=departement)
    if ville:
        clients = clients.filter(ville__icontains=ville)
    if type_client:
        clients = clients.filter(type_client=type_client)
    if portee == 'moi':
        clients = clients.filter(created_by=request.user)
    elif portee == 'equipe':
        clients = clients.filter(created_by__in=get_collegues_ids(request.user))

    return render(request, 'core/clients.html', {
        'clients': clients.prefetch_related('contacts'),
        'is_admin': is_admin(request.user),
        'type_choices': Client.TYPE_CLIENT_CHOICES,
        'f_nom': nom,
        'f_code_postal': code_postal,
        'f_departement': departement,
        'f_ville': ville,
        'f_portee': portee,
        'f_type_client': type_client,
    })


@login_required
def client_search(request):
    """Recherche client (autocomplétion + filtre du panneau). Renvoie du JSON."""
    q = request.GET.get('q', '').strip()
    clients = Client.objects.all()
    if q:
        clients = clients.filter(nom__icontains=q)
    results = [
        {
            'id': c.pk,
            'nom': c.nom,
            'ville': c.ville,
            'code_postal': c.code_postal,
        }
        for c in clients[:20]
    ]
    return JsonResponse({'results': results})


@login_required
@require_POST
def client_quick_create(request):
    """Création rapide depuis l'écran de devis. Renvoie le client créé en JSON."""
    nom = request.POST.get('nom', '').strip()
    if not nom:
        return JsonResponse({'error': 'Le nom est obligatoire.'}, status=400)
    client = Client.objects.create(
        nom=nom,
        contact=request.POST.get('contact', ''),
        email=request.POST.get('email', ''),
        telephone=request.POST.get('telephone', ''),
        adresse=request.POST.get('adresse', ''),
        code_postal=request.POST.get('code_postal', ''),
        ville=request.POST.get('ville', ''),
        created_by=request.user,
    )
    return JsonResponse({'id': client.pk, 'nom': client.nom})


@login_required
@require_POST
def client_create(request):
    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, 'Le nom est obligatoire.')
        return redirect('core:clients')
    Client.objects.create(
        nom=nom,
        type_client=request.POST.get('type_client', 'particulier'),
        contact=request.POST.get('contact', ''),
        email=request.POST.get('email', ''),
        telephone=request.POST.get('telephone', ''),
        adresse=request.POST.get('adresse', ''),
        code_postal=request.POST.get('code_postal', ''),
        ville=request.POST.get('ville', ''),
        created_by=request.user,
    )
    messages.success(request, f'Client "{nom}" créé.')
    return redirect('core:clients')


@login_required
@require_POST
def client_edit(request, pk):
    if not is_admin(request.user):
        messages.error(request, 'Action réservée à l\'administrateur.')
        return redirect('core:clients')
    client = get_object_or_404(Client, pk=pk)
    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, 'Le nom est obligatoire.')
        return redirect('core:clients')
    client.nom = nom
    client.type_client = request.POST.get('type_client', client.type_client)
    client.contact = request.POST.get('contact', '')
    client.email = request.POST.get('email', '')
    client.telephone = request.POST.get('telephone', '')
    client.adresse = request.POST.get('adresse', '')
    client.code_postal = request.POST.get('code_postal', '')
    client.ville = request.POST.get('ville', '')
    client.save()
    messages.success(request, f'Client "{nom}" modifié.')
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
#  BIBLIOTHÈQUE AIDES (partagée)
# ══════════════════════════════════════════

@login_required
def aides_page(request):
    profil = get_profil(request.user)
    return render(request, 'core/aides.html', {'profil': profil})


@login_required
def aides_api_get(request):
    aides = BibliothèqueAides.objects.select_related('created_by').all()
    return JsonResponse({
        'aides': [
            {
                'id': a.pk,
                'description': a.description,
                'type_ligne': a.type_ligne,
                'montant_defaut': float(a.montant_defaut) if a.montant_defaut is not None else None,
                'unite': a.unite,
                'organisme': a.organisme,
            }
            for a in aides
        ]
    })


@login_required
@require_POST
def aides_api_save(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    description = data.get('description', '').strip()
    if not description:
        return JsonResponse({'error': 'Description requise'}, status=400)
    type_ligne = data.get('type_ligne', 'FIN')
    if type_ligne not in ('FMO', 'FMAT', 'FIN'):
        return JsonResponse({'error': 'Type invalide'}, status=400)
    montant_raw = data.get('montant_defaut')
    montant = to_decimal(montant_raw)
    aide = BibliothèqueAides.objects.create(
        description=description,
        type_ligne=type_ligne,
        montant_defaut=montant,
        unite=data.get('unite', 'forfait'),
        organisme=data.get('organisme', ''),
        created_by=request.user,
    )
    return JsonResponse({
        'ok': True,
        'aide': {
            'id': aide.pk,
            'description': aide.description,
            'type_ligne': aide.type_ligne,
            'montant_defaut': float(aide.montant_defaut) if aide.montant_defaut is not None else None,
            'unite': aide.unite,
            'organisme': aide.organisme,
        }
    })


@login_required
@require_POST
def aide_delete(request, pk):
    aide = get_object_or_404(BibliothèqueAides, pk=pk)
    aide.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════
#  DEVIS — LISTE
# ══════════════════════════════════════════

@login_required
def devis_list(request):
    profil = get_profil(request.user)
    qs = Devis.objects.select_related(
        'client', 'equipe__service__territoire', 'created_by'
    )

    # Filtres
    status = request.GET.get('status', '')
    client_id = request.GET.get('client', '')
    equipe_id = request.GET.get('equipe', '')
    service_id = request.GET.get('service', '')
    territoire_id = request.GET.get('territoire', '')
    auteur_id = request.GET.get('auteur', '')
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
    if auteur_id:
        qs = qs.filter(created_by_id=auteur_id)
    if q:
        qs = qs.filter(
            Q(chantier__icontains=q)
            | Q(client__nom__icontains=q)
            | Q(reference__icontains=q)
        )

    # Prefetch posé sur le queryset final (après tous les filtres) pour que
    # `attacher_totaux_devis` calcule les totaux en mémoire, sans N+1.
    qs = qs.prefetch_related('lignes', 'factures')

    page_obj, base_qs = paginer(request, qs)
    # Totaux calculés en mémoire sur la page courante uniquement (pas de N+1).
    attacher_totaux_devis(page_obj.object_list)

    return render(request, 'core/devis_list.html', {
        'devis': page_obj,
        'page_obj': page_obj,
        'base_qs': base_qs,
        'clients': Client.objects.all(),
        'equipes': Equipe.objects.select_related('service__territoire').all(),
        'services': Service.objects.select_related('territoire').all(),
        'territoires': Territoire.objects.all(),
        'auteurs': User.objects.filter(devis_crees__isnull=False).distinct().order_by('first_name', 'username'),
        'profil': profil,
        'status_filter': status,
        'client_filter': client_id,
        'equipe_filter': equipe_id,
        'service_filter': service_id,
        'territoire_filter': territoire_id,
        'auteur_filter': auteur_id,
        'q': q,
        'peut_supprimer': {d.pk: peut_supprimer_devis(request.user, d) for d in page_obj},
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
        try:
            validite_jours = int(request.POST.get('validite_jours') or 30)
        except (TypeError, ValueError):
            validite_jours = 30
        try:
            taux_mo = Decimal(str(request.POST.get('taux_mo') or profil.taux_mo_defaut))
        except (InvalidOperation, TypeError, ValueError):
            taux_mo = profil.taux_mo_defaut
        devis = Devis.objects.create(
            reference=gen_reference('DEV'),
            client=client,
            chantier=chantier,
            equipe_id=equipe_id,
            date_validite=date.today() + timedelta(days=validite_jours),
            taux_mo=taux_mo,
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
    if not peut_voir_devis(request.user, devis):
        messages.error(request, "Vous n'avez pas accès à ce devis.")
        return redirect('core:devis-list')
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
        'saisie_ht': profil.saisie_ht,  # ← ajouté
        'peut_modifier': peut_modifier_devis(request.user, devis),  # éditeur verrouillé si hors équipe
        'clients': Client.objects.all(),
        'equipes': Equipe.objects.select_related('service__territoire').all(),
    })


@login_required
@require_POST
def devis_status(request, pk):
    devis = get_object_or_404(Devis, pk=pk)
    if not peut_modifier_devis(request.user, devis):
        messages.error(request, 'Vous ne pouvez pas modifier ce devis.')
        return redirect('core:devis-detail', pk=pk)
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
    if not peut_voir_devis(request.user, src):
        messages.error(request, "Vous n'avez pas accès à ce devis.")
        return redirect('core:devis-list')
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
    if not peut_voir_devis(request.user, devis):
        messages.error(request, "Vous n'avez pas accès à ce devis.")
        return redirect('core:devis-list')
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
        'coordonnees_cb': devis.coordonnees_cb,
    })

@login_required
def devis_export_excel(request, pk):
    import html as html_module
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    def strip_html(text):
        if not text or '<' not in text:
            return text or ''
        # <div> → saut de ligne (sauf le premier)
        t = re.sub(r'<div>', '\n', text, flags=re.IGNORECASE)
        # <br> variants → saut de ligne
        t = re.sub(r'<br\s*/?>', '\n', t, flags=re.IGNORECASE)
        # Supprimer toutes les balises restantes
        t = re.sub(r'<[^>]+>', '', t)
        # Décoder les entités HTML (&amp; &lt; etc.)
        t = html_module.unescape(t)
        # Nettoyer les lignes vides et espaces superflus
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        return '\n'.join(lines)

    devis = get_object_or_404(Devis, pk=pk)
    if not peut_voir_devis(request.user, devis):
        messages.error(request, "Vous n'avez pas accès à ce devis.")
        return redirect('core:devis-list')

    PRUNE    = '67123A'
    PRUNE_LT = 'F2DCDB'
    GRAY     = 'E0E0E0'
    AMBER_LT = 'FFF2CC'
    GREEN_LT = 'E2EFDA'
    GREEN_MID = 'C6EFCE'
    GREEN_DK  = '375623'

    def fill(hex_color):
        return PatternFill('solid', fgColor=hex_color)

    FN = Font(name='Calibri', size=10)
    FB = Font(name='Calibri', size=10, bold=True)
    FW = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
    FWL = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    FT = Font(name='Calibri', size=14, bold=True, color='FFFFFF')
    FC = Font(name='Calibri', size=10, bold=True, color=PRUNE)

    AL = Alignment(vertical='center', wrap_text=True)
    AR = Alignment(horizontal='right', vertical='center')
    AC = Alignment(horizontal='center', vertical='center')
    AT = Alignment(wrap_text=True, vertical='top')

    FMT_EUR = '#,##0.00 "€"'
    FMT_QTY = '#,##0.###'

    wb = Workbook()
    ws = wb.active
    ws.title = 'Devis'

    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 46
    ws.column_dimensions['C'].width = 10
    ws.column_dimensions['D'].width = 10
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 14

    row = 1

    def c(r, col, value='', font=None, fill_=None, align=None, fmt=None):
        obj = ws.cell(row=r, column=col, value=value)
        if font:  obj.font      = font
        if fill_: obj.fill      = fill_
        if align: obj.alignment = align
        if fmt:   obj.number_format = fmt
        return obj

    def full_row(r, font=None, fill_=None, value=None, align=None, height=16):
        ws.row_dimensions[r].height = height
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        for col in range(1, 7):
            ws.cell(r, col).fill = fill_ or PatternFill()
        if value is not None:
            ws.cell(r, 1).value = value
        if font:  ws.cell(r, 1).font = font
        if align: ws.cell(r, 1).alignment = align

    def total_row(r, label, amount, font_label=None, font_amount=None, fill_=None, height=16):
        ws.row_dimensions[r].height = height
        for col in range(1, 7):
            ws.cell(r, col).fill = fill_ or PatternFill()
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        ws.cell(r, 1).value = label
        ws.cell(r, 1).font = font_label or FB
        ws.cell(r, 1).alignment = AR
        ws.cell(r, 6).value = float(amount)
        ws.cell(r, 6).font = font_amount or FB
        ws.cell(r, 6).number_format = FMT_EUR
        ws.cell(r, 6).alignment = AR

    # ── En-tête ──────────────────────────────────────────────────
    ws.row_dimensions[row].height = 28
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
    for col in range(1, 7):
        ws.cell(row, col).fill = fill(PRUNE)
    ws.cell(row, 1).value = f"DEVIS TRAVAUX — {devis.reference}"
    ws.cell(row, 1).font = FT
    ws.cell(row, 1).alignment = AL
    ws.cell(row, 5).value = f"Date : {devis.date_creation.strftime('%d/%m/%Y')}"
    ws.cell(row, 5).font = Font(name='Calibri', size=10, color='FFFFFF')
    ws.cell(row, 5).alignment = AR
    row += 1

    ws.row_dimensions[row].height = 18
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    for col in range(1, 7):
        ws.cell(row, col).fill = fill(PRUNE_LT)
    ws.cell(row, 1).value = (
        f"Statut : {devis.get_status_display()}"
        f"   |   Chantier : {devis.chantier}"
    )
    ws.cell(row, 1).font = FB
    ws.cell(row, 1).alignment = AL
    row += 1

    def info_row(r, label, value):
        ws.row_dimensions[r].height = 14
        ws.cell(r, 1).value = label
        ws.cell(r, 1).font = FB
        ws.cell(r, 2).value = value
        ws.cell(r, 2).font = FN
        ws.cell(r, 2).alignment = AL

    info_row(row, 'Client :', str(devis.client))
    if devis.client.telephone:
        ws.cell(row, 4).value = f"Tél : {devis.client.telephone}"
        ws.cell(row, 4).font = FN
    if devis.client.email:
        ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
        ws.cell(row, 5).value = devis.client.email
        ws.cell(row, 5).font = FN
    row += 1

    adresse_client = ' — '.join(filter(None, [
        devis.client.adresse,
        f"{devis.client.code_postal} {devis.client.ville}".strip() or None,
    ]))
    if adresse_client:
        info_row(row, '', adresse_client)
        row += 1

    chantier_adresse = ' — '.join(filter(None, [
        devis.chantier_adresse1,
        devis.chantier_adresse2,
        f"{devis.chantier_cp} {devis.chantier_ville}".strip() or None,
    ]))
    if chantier_adresse:
        info_row(row, 'Adresse chantier :', chantier_adresse)
        row += 1

    if devis.equipe:
        info_row(row, 'Équipe :', str(devis.equipe))
        row += 1

    if devis.coordonnees_cb:
        info_row(row, 'Contact CB :', devis.coordonnees_cb.replace('\n', ' | '))
        row += 1

    if devis.date_validite:
        info_row(row, "Valable jusqu'au :", devis.date_validite.strftime('%d/%m/%Y'))
        row += 1

    row += 1  # séparateur

    # En-tête colonnes
    ws.row_dimensions[row].height = 18
    for col, label in enumerate(['N°', 'Description', 'Unité', 'Quantité', 'P.U. HT', 'Total HT'], 1):
        ws.cell(row, col).value = label
        ws.cell(row, col).font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        ws.cell(row, col).fill = fill('444444')
        ws.cell(row, col).alignment = AC
    row += 1

    # ── Lignes de devis ──────────────────────────────────────────
    racines_pos = list(
        devis.lignes.filter(parent=None).exclude(type_ligne='FIN')
        .prefetch_related('enfants', 'enfants__enfants', 'enfants__enfants__enfants')
        .order_by('ordre')
    )
    racines_fin = list(
        devis.lignes.filter(parent=None, type_ligne='FIN').order_by('ordre')
    )

    titres      = [l for l in racines_pos if l.type_ligne == 'TITRE']
    autres_rac  = [l for l in racines_pos if l.type_ligne != 'TITRE']

    def write_enfants(r, parent_ligne, depth=1):
        for enfant in parent_ligne.enfants.all():
            r = write_ligne(r, enfant, depth)
        return r

    def write_ligne(r, ligne, depth=0):
        ws.row_dimensions[r].height = 15
        indent = '  ' * depth
        t = ligne.type_ligne

        if t == 'TITRE':
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
            for col in range(1, 7):
                ws.cell(r, col).fill = fill(PRUNE_LT)
            ws.cell(r, 1).value = indent + strip_html(ligne.description)
            ws.cell(r, 1).font = FC
            ws.cell(r, 1).alignment = AL
            ws.cell(r, 6).value = float(ligne.total())
            ws.cell(r, 6).font = FC
            ws.cell(r, 6).number_format = FMT_EUR
            ws.cell(r, 6).alignment = AR
            r += 1
            r = write_enfants(r, ligne, depth + 1)
            # SS TOTAL du titre
            ws.row_dimensions[r].height = 15
            for col in range(1, 7):
                ws.cell(r, col).fill = fill(GRAY)
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
            ws.cell(r, 1).value = f"SS TOTAL — {strip_html(ligne.description)}"
            ws.cell(r, 1).font = FB
            ws.cell(r, 1).alignment = AR
            ws.cell(r, 6).value = float(ligne.total())
            ws.cell(r, 6).font = FB
            ws.cell(r, 6).number_format = FMT_EUR
            ws.cell(r, 6).alignment = AR
            r += 1
            ws.row_dimensions[r].height = 6   # ligne vide entre LOTs
            r += 1
            return r

        # Ligne ordinaire
        num = getattr(ligne, 'num', '')
        ws.cell(r, 1).value = indent + (num or '')
        ws.cell(r, 1).font = FN
        ws.cell(r, 1).alignment = AC

        ws.cell(r, 2).value = indent + strip_html(ligne.description)
        ws.cell(r, 2).font = FN
        ws.cell(r, 2).alignment = AL

        ws.cell(r, 3).value = ligne.unite or ''
        ws.cell(r, 3).font = FN
        ws.cell(r, 3).alignment = AC

        if t not in ('FMO', 'FMAT'):
            ws.cell(r, 4).value = float(ligne.quantite)
            ws.cell(r, 4).number_format = FMT_QTY
            ws.cell(r, 4).font = FN
            ws.cell(r, 4).alignment = AR

        if ligne.cout_unitaire is not None:
            ws.cell(r, 5).value = float(ligne.cout_unitaire)
            ws.cell(r, 5).number_format = FMT_EUR
            ws.cell(r, 5).font = FN
            ws.cell(r, 5).alignment = AR

        total_val = float(ligne.total())
        ws.cell(r, 6).value = total_val if total_val != 0 else None
        ws.cell(r, 6).number_format = FMT_EUR
        ws.cell(r, 6).font = FB if t in ('FMO', 'FMAT') else FN
        ws.cell(r, 6).alignment = AR

        if t in ('FMO', 'FMAT'):
            for col in range(1, 7):
                ws.cell(r, col).fill = fill(AMBER_LT)

        r += 1
        r = write_enfants(r, ligne, depth + 1)
        return r

    # Section Travaux réalisés
    full_row(row, font=FW, fill_=fill(PRUNE),
             value='TRAVAUX RÉALISÉS', align=AL, height=18)
    for col in range(2, 7):
        ws.cell(row, col).fill = fill(PRUNE)
    row += 1

    for titre in titres:
        row = write_ligne(row, titre, depth=0)

    for ligne in autres_rac:
        row = write_ligne(row, ligne, depth=0)

    # SS TOTAL Travaux
    total_travaux = sum(l.total() for l in titres + autres_rac)
    total_row(row, 'SS TOTAL TRAVAUX', total_travaux, fill_=fill(GRAY), height=16)
    row += 1

    # Total brut net de taxes
    row += 1
    total_row(row, 'TOTAL COÛT DES TRAVAUX NET DE TAXES',
              devis.total_brut(),
              font_label=FW, font_amount=FWL, fill_=fill(PRUNE), height=20)
    row += 1

    # Section Aides / Financements
    if racines_fin:
        row += 1
        full_row(row, font=FW, fill_=fill(GREEN_DK),
                 value='AIDES NOTIFIÉES', align=AL, height=18)
        for col in range(2, 7):
            ws.cell(row, col).fill = fill(GREEN_DK)
        row += 1
        for ligne in racines_fin:
            ws.row_dimensions[row].height = 15
            for col in range(1, 7):
                ws.cell(row, col).fill = fill(GREEN_LT)
            ws.cell(row, 2).value = strip_html(ligne.description)
            ws.cell(row, 2).font = FN
            ws.cell(row, 2).alignment = AL
            ws.cell(row, 3).value = ligne.unite or ''
            ws.cell(row, 3).font = FN
            ws.cell(row, 3).alignment = AC
            ws.cell(row, 6).value = float(ligne.total())
            ws.cell(row, 6).number_format = FMT_EUR
            ws.cell(row, 6).font = FN
            ws.cell(row, 6).alignment = AR
            row += 1
        total_row(row, 'SS TOTAL Aides', devis.total_financement(),
                  fill_=fill(GREEN_MID), height=16)
        row += 1

    # Montant dû
    row += 1
    total_row(row, "MONTANT DÛ PAR LE MAÎTRE D'OUVRAGE",
              devis.net_client(),
              font_label=FW, font_amount=FWL, fill_=fill(PRUNE), height=20)
    row += 1

    # Acomptes versés
    acomptes = list(devis.factures.filter(type_doc='acompte', status='paid'))
    if acomptes:
        row += 1
        ws.row_dimensions[row].height = 14
        ws.cell(row, 1).value = 'NB : mettre les dates de versement'
        ws.cell(row, 1).font = Font(name='Calibri', size=9, italic=True)
        ws.cell(row, 2).value = 'Acompte déjà versé'
        ws.cell(row, 2).font = FB
        row += 1
        for f in acomptes:
            ws.row_dimensions[row].height = 14
            label = f.libelle or f.get_reference()
            if f.date_versement:
                label += f" (versé le {f.date_versement.strftime('%d/%m/%Y')})"
            ws.cell(row, 2).value = label
            ws.cell(row, 2).font = FN
            ws.cell(row, 6).value = float(f.montant)
            ws.cell(row, 6).number_format = FMT_EUR
            ws.cell(row, 6).alignment = AR
            row += 1
        total_acomptes = sum(f.montant for f in acomptes)
        total_row(row, 'Reste à payer',
                  devis.net_client() - total_acomptes,
                  fill_=fill(GRAY), height=16)
        row += 1

    # Conditions
    if devis.conditions_devis:
        row += 1
        ws.row_dimensions[row].height = 14
        ws.cell(row, 1).value = 'Conditions :'
        ws.cell(row, 1).font = FB
        row += 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.cell(row, 1).value = devis.conditions_devis
        ws.cell(row, 1).font = Font(name='Calibri', size=9)
        ws.cell(row, 1).alignment = AT
        ws.row_dimensions[row].height = max(
            30, min(len(devis.conditions_devis) // 5, 100)
        )
        row += 2

    # Signatures
    ws.row_dimensions[row].height = 14
    ws.cell(row, 2).value = "Pour le Maître d'ouvrage"
    ws.cell(row, 2).font = FB
    ws.cell(row, 5).value = "Pour les Compagnons Bâtisseurs Bretagne"
    ws.cell(row, 5).font = FB
    row += 1
    ws.cell(row, 2).value = 'Signature précédée de la mention "Bon pour accord"'
    ws.cell(row, 2).font = Font(name='Calibri', size=9, italic=True)
    ws.cell(row, 5).value = 'Signature + Cachet'
    ws.cell(row, 5).font = Font(name='Calibri', size=9, italic=True)

    # ── Réponse ──────────────────────────────────────────────────
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    ref_clean = devis.reference.replace('/', '-')
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="devis_{ref_clean}.xlsx"'
    return response


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
    devis.coordonnees_cb   = data.get('coordonnees_cb', '').strip()

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
    if not peut_voir_devis(request.user, devis):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    racines = devis.lignes.filter(parent=None)
    data = [ligne_to_dict(l) for l in racines]
    return JsonResponse({
        'lignes': data,
        'taux_mo': float(devis.taux_mo),
        'fin_group_title': devis.fin_group_title or 'Financements',
        'zone_financement': devis.zone_financement,
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
        zone_financement = data.get('zone_financement', False)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    devis.lignes.all().delete()

    def create_lignes(items, parent=None, ordre=0):
        for item in items:
            cout = item.get('cout_unitaire')
            aide_id = item.get('aide_id')
            aide = None
            if aide_id:
                try:
                    aide = BibliothèqueAides.objects.get(pk=aide_id)
                except BibliothèqueAides.DoesNotExist:
                    pass
            ligne = LigneDevis.objects.create(
                devis=devis, parent=parent,
                type_ligne=item.get('type_ligne', 'F'),
                description=item.get('description', ''),
                quantite=to_decimal(item.get('quantite'), default=Decimal('1')),
                unite=item.get('unite', ''),
                cout_unitaire=to_decimal(cout),
                ordre=ordre,
                ouvert=item.get('ouvert', True),
                aide=aide,
            )
            create_lignes(item.get('enfants', []), parent=ligne)
            ordre += 1

    create_lignes(lignes)
    devis.fin_group_title = fin_group_title
    devis.zone_financement = zone_financement
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
    # Factures de chantier uniquement (liées à un devis, hors avoirs).
    # Les factures compta (structure/appel) et les avoirs ont leurs propres listes.
    factures = Facture.objects.select_related(
        'devis', 'devis__client', 'devis__equipe', 'created_by'
    ).prefetch_related('avoirs').filter(devis__isnull=False).exclude(type_doc='avoir')

    auteur_id = request.GET.get('auteur', '')
    if auteur_id:
        factures = factures.filter(created_by_id=auteur_id)

    page_obj, base_qs = paginer(request, factures)

    return render(request, 'core/factures_list.html', {
        'factures': page_obj,
        'page_obj': page_obj,
        'base_qs': base_qs,
        'auteurs': User.objects.filter(
            factures_creees__devis__isnull=False
        ).exclude(factures_creees__type_doc='avoir').distinct().order_by('first_name', 'username'),
        'auteur_filter': auteur_id,
    })


@login_required
def avoirs_list(request):
    """
    Liste de tous les avoirs (chantier + compta).
    Lecture partagée pour les avoirs de chantier ; les avoirs compta (sans devis)
    ne sont visibles que par les rôles compta — chaque ligne affichée est donc
    accessible à l'utilisateur.
    """
    avoirs = Facture.objects.filter(type_doc='avoir').select_related(
        'devis', 'client', 'facture_origine', 'created_by'
    ).order_by('-created_at')
    if not peut_acceder_compta(request.user):
        avoirs = avoirs.filter(devis__isnull=False)
    page_obj, base_qs = paginer(request, avoirs)
    return render(request, 'core/avoirs_list.html', {
        'avoirs': page_obj,
        'page_obj': page_obj,
        'base_qs': base_qs,
    })


@login_required
def facture_create(request, devis_pk):
    devis = get_object_or_404(Devis, pk=devis_pk)
    if not peut_modifier_devis(request.user, devis):
        return HttpResponseForbidden()

    if request.method != 'POST':
        return redirect('core:devis-detail', devis_pk)

    type_doc     = request.POST.get('type_doc', 'facture')
    destinataire = request.POST.get('destinataire', '').strip()
    notes        = request.POST.get('notes', '').strip()

    if type_doc == 'acompte': 
        # -> facture acompte
        montant_raw = request.POST.get('montant', '').strip()
        try:
            montant = Decimal(montant_raw)
        except Exception:
            montant = Decimal('0')

        facture = Facture.objects.create(
            devis=devis,
            type_doc='acompte',
            destinataire=destinataire or str(devis.client),
            montant=montant,
            notes=notes,
            created_by=request.user,
        )
        AuditLog.objects.create(
            user=request.user,
            action=f"Facture d'acompte {facture.get_reference()} créée ({montant} €)",
            devis=devis,
            facture=facture,
        )
        return redirect('core:devis-detail', devis_pk)

    else:
        # -> facture normale
        try:
            echeance_jours = int(request.POST.get('echeance_jours') or 30)
        except (TypeError, ValueError):
            echeance_jours = 30
        date_echeance  = date.today() + timedelta(days=echeance_jours)

        facture = Facture.objects.create(
            devis=devis,
            type_doc='facture',
            destinataire=destinataire or str(devis.client),
            notes=notes,
            date_echeance=date_echeance,
            created_by=request.user,
        )
        # Copie des lignes du devis
        copier_lignes_devis_vers_facture(devis.lignes.filter(parent=None), facture)

        AuditLog.objects.create(
            user=request.user,
            action=f"Facture {facture.get_reference()} créée",
            devis=devis,
            facture=facture,
        )
        return redirect('core:facture-detail', facture.pk)

@login_required
@require_POST
def facture_date_versement(request, pk):
    facture = get_object_or_404(Facture, pk=pk, type_doc='acompte')
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'ok': False, 'error': 'Permission refusée'}, status=403)
    try:
        data = json.loads(request.body)
        date_str = data.get('date_versement', '').strip()
        if date_str:
            facture.date_versement = dt.strptime(date_str, '%d/%m/%Y').date()
        else:
            facture.date_versement = None
        facture.save(update_fields=['date_versement'])
        return JsonResponse({'ok': True})
    except (ValueError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Format invalide (jj/mm/aaaa)'})

@login_required
@require_POST
def facture_valider(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_valider_facture(request.user, facture):
        messages.error(request, 'Validation réservée au comptable.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
    if not facture.numero:
        facture.numero = gen_numero_facture(facture.type_doc)
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
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
    if not peut_modifier_facture(request.user, facture):
        if is_ajax:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
        messages.error(request, 'Vous ne pouvez pas modifier cette facture.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
    old = facture.status
    new_status = request.POST.get('status', facture.status)
    facture.status = new_status
    facture.save()
    add_audit(
        request.user,
        f"Statut {facture.get_reference()} : {old} → {new_status}",
        devis=facture.devis, facture=facture
    )
    # Si appel AJAX (fetch depuis JS), retourner JSON
    if is_ajax:
        return JsonResponse({'ok': True})
    # Sinon redirect normal (formulaires HTML)
    return redirect('core:devis-detail', pk=facture.devis.pk)


@login_required
@require_POST
def facture_bypass(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    code = request.POST.get('code', '')
    stored = request.session.get(f'bypass_code_{pk}')
    if not stored or code != stored:
        return JsonResponse({'error': 'Code incorrect'}, status=400)
    if not facture.numero:
        facture.numero = gen_numero_facture(facture.type_doc)
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
    # Vérification permission avant le statut (évite de donner une info sur l'existence)
    if not peut_supprimer_facture(request.user, facture):
        messages.error(request, 'Vous ne pouvez pas supprimer cette facture.')
        return redirect('core:devis-detail', pk=facture.devis.pk)
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
    if not request.user.email:
        return JsonResponse({'ok': False, 'error': 'Aucune adresse email sur votre compte. Contactez un administrateur.'})

    facture = get_object_or_404(Facture, pk=pk)
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'ok': False, 'error': 'Permission refusée'}, status=403)

    code = ''.join(random.choices(string.digits, k=6))

    try:
        send_mail(
            subject=f'Code bypass — {facture.get_reference()}',
            message=(
                f'Bonjour {request.user.first_name or request.user.username},\n\n'
                f'Votre code de bypass pour la facture {facture.get_reference()} est :\n\n'
                f'    {code}\n\n'
                f'Ce code est valable 10 minutes.\n\n'
                f'CB Bretagne'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
            fail_silently=False,
        )
        request.session[f'bypass_code_{pk}'] = code
        return JsonResponse({'ok': True})
    except Exception as e:
        logger.error('Bypass email error (facture %s): %s', pk, e)
        return JsonResponse({'ok': False, 'error': "Impossible d'envoyer le code par email. Contactez un administrateur."})


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

    """
    facture = get_object_or_404(Facture, pk=pk)
    devis = facture.devis
    profil = get_profil(request.user)

    # Vérification accès — lecture (comptable inclus pour la validation)
    if not peut_voir_facture(request.user, facture):
        messages.error(request, "Vous n'avez pas accès à cette facture.")
        return redirect('core:devis-list')

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
    if not peut_voir_facture(request.user, facture):
        messages.error(request, "Vous n'avez pas accès à cette facture.")
        return redirect('core:devis-list')
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
                    lf.enfants_filtres = enfants
                    result.append(lf)
            else:
                if float(lf.quantite) > 0:
                    result.append(lf)
        return result

    # Pour un avoir, les quantités sont négatives → on garde tout (pas de filtre > 0),
    # mais on attache enfants_filtres pour que les titres affichent leurs enfants.
    def garder_tout(lignes_qs):
        result = []
        for lf in lignes_qs:
            if lf.type_ligne == 'TITRE':
                lf.enfants_filtres = garder_tout(lf.enfants.all())
                result.append(lf)
            else:
                result.append(lf)
        return result

    if facture.type_doc == 'avoir':
        lignes_filtrees = garder_tout(facture.lignes.filter(parent=None).exclude(type_ligne='FIN'))
    else:
        lignes_filtrees = filtrer_lignes(facture.lignes.filter(parent=None).exclude(type_ligne='FIN'))

    from decimal import Decimal
    if devis is not None:
        # Lignes financement du devis (FIN, niveau racine) — section informative
        lignes_fin = list(devis.lignes.filter(parent=None, type_ligne='FIN'))

        # Acomptes déduits uniquement sur la première facture non-acompte du devis
        premiere_facture = devis.factures.exclude(
            type_doc='acompte'
        ).exclude(status='cancelled').order_by('created_at').first()

        if premiere_facture and premiere_facture.pk == facture.pk:
            acomptes = devis.factures.filter(
                type_doc='acompte',
            ).exclude(status='draft').order_by('created_at')
            total_acomptes = sum(
                a.montant for a in acomptes if a.status == 'paid'
            )
        else:
            acomptes = devis.factures.none()
            total_acomptes = Decimal('0')
        coordonnees_cb = facture.coordonnees_cb or devis.coordonnees_cb
    else:
        # Facture compta (sans devis) : pas de financement ni d'acomptes
        lignes_fin = []
        acomptes = Facture.objects.none()
        total_acomptes = Decimal('0')
        coordonnees_cb = facture.coordonnees_cb

    solde = facture.montant - total_acomptes

    return render(request, 'core/facture_apercu.html', {
        'facture': facture,
        'devis': devis,
        'client': facture.get_client(),
        'contact': facture.contact_client,
        'params': params,
        'lignes': lignes_filtrees,
        'lignes_fin': lignes_fin,
        'coordonnees_cb': coordonnees_cb,
        'acomptes': acomptes,
        'total_acomptes': total_acomptes,
        'solde': solde,
        'has_acomptes': total_acomptes > 0,
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
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
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
    if not peut_voir_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
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

     # Acomptes versés — affichés dans la zone financement
    acomptes = facture.devis.factures.filter(
        status__in=STATUTS_VALIDES,
        type_doc='acompte',
    ).order_by('created_at')

    acomptes_data = [
        {
            'pk': f.pk,
            'reference': f.get_reference(),
            'montant': float(f.montant),
            'notes': f.notes or '',
            'date_versement': f.date_versement.strftime('%d/%m/%Y') if f.date_versement else '',
        }
        for f in acomptes
    ]

    return JsonResponse({
        'lignes': data,
        'montant': float(facture.montant),
        'taux_mo': float(facture.devis.taux_mo),
        'total_devis': float(facture.devis.total_brut()),
        'total_deja': float(facture.devis.total_facture()),
        'factures_prec': factures_prec_data,
        'acomptes': acomptes_data,
    })

@login_required
@require_POST
def lignes_facture_save(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
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
                quantite=to_decimal(item.get('quantite'), default=Decimal('1')),
                quantite_originale=to_decimal(item.get('quantite_originale', item.get('quantite')), default=Decimal('1')),
                unite=item.get('unite', ''),
                cout_unitaire=to_decimal(cout),
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


@login_required
def utilisateurs_list(request):
    """
    Liste des utilisateurs.
    - Admin : voit tous les utilisateurs actifs et inactifs
    - Responsable : voit uniquement les membres de ses équipes
    """
    if not peut_gerer_utilisateurs(request.user):
        messages.error(request, 'Accès réservé aux administrateurs et responsables.')
        return redirect('core:dashboard')

    profil = get_profil(request.user)

    if profil.role == 'admin':
        profils = ProfilUtilisateur.objects.select_related(
            'user', 'service__territoire', 'responsable__user'
        ).prefetch_related('equipes__service').order_by(
            'user__last_name', 'user__first_name'
        )
    else:
        # Responsable — uniquement les membres de ses équipes
        equipes_ids = profil.equipes.values_list('pk', flat=True)
        profils = ProfilUtilisateur.objects.filter(
            equipes__pk__in=equipes_ids
        ).exclude(
            pk=profil.pk  # s'exclut lui-même de la liste
        ).select_related(
            'user', 'service__territoire', 'responsable__user'
        ).prefetch_related('equipes__service').distinct().order_by(
            'user__last_name', 'user__first_name'
        )

    return render(request, 'core/utilisateurs_list.html', {
        'profils': profils,
        'profil': profil,
    })


@login_required
def utilisateur_create(request):
    """
    Création d'un nouvel utilisateur.
    - Génère un mot de passe temporaire affiché une seule fois
    - Copie optionnelle de la bibliothèque d'un utilisateur existant
    - Admin : peut attribuer tous les rôles et toutes les équipes
    - Responsable : ne peut pas créer d'admin, voit uniquement ses équipes
    """
    if not peut_gerer_utilisateurs(request.user):
        messages.error(request, 'Accès réservé aux administrateurs et responsables.')
        return redirect('core:dashboard')

    profil_courant = get_profil(request.user)

    if request.method == 'POST':
        username   = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        role       = request.POST.get('role', 'technicien')
        service_id = request.POST.get('service') or None
        equipes_ids = request.POST.getlist('equipes')
        responsable_id = request.POST.get('responsable') or None
        copier_biblio_de = request.POST.get('copier_biblio_de') or None

        # Validation
        if not username:
            messages.error(request, 'Le nom d\'utilisateur est obligatoire.')
            return redirect('core:utilisateur-create')

        # TODO (avant passage Phase 4) : limiter les emails à @compagnonsbatisseurs.eu
        # if email and not email.endswith(f'@{DOMAINE_AUTORISE}'):
        #     messages.error(request, f'L\'adresse email doit être une adresse @{DOMAINE_AUTORISE}.')
        #     return redirect('core:utilisateur-create')

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Le nom d\'utilisateur "{username}" est déjà utilisé.')
            return redirect('core:utilisateur-create')

        # Responsable ne peut pas créer d'admin
        if profil_courant.role == 'responsable' and role == 'admin':
            messages.error(request, 'Vous ne pouvez pas créer un administrateur.')
            return redirect('core:utilisateur-create')

        # Génération mot de passe temporaire
        mdp_temp = ''.join(random.choices(
            string.ascii_letters + string.digits, k=12
        ))

        # Création User Django
        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=mdp_temp,
        )

        # Création ProfilUtilisateur
        nouveau_profil = ProfilUtilisateur.objects.create(
            user=user,
            role=role,
            service_id=service_id,
            responsable_id=responsable_id,
        )

        # Attribution des équipes
        if equipes_ids:
            nouveau_profil.equipes.set(equipes_ids)

        # Copie de bibliothèque
        if copier_biblio_de:
            try:
                source_user = User.objects.get(pk=copier_biblio_de)
                biblio_source, _ = Bibliotheque.objects.get_or_create(user=source_user)
                Bibliotheque.objects.create(
                    user=user,
                    lignes=biblio_source.lignes,
                )
            except User.DoesNotExist:
                pass
        else:
            Bibliotheque.objects.create(user=user, lignes=[])

        # Envoi de l'email d'invitation (best-effort) + affichage du mot de passe.
        # BETA : la délivrance vers les adresses @compagnonsbatisseurs.eu n'est pas
        # fiable (M365 rejette les mails relayés par Brevo, faute d'authentification
        # DNS du domaine — voir NOTES_DEV § Infra). On affiche donc TOUJOURS le mot
        # de passe temporaire pour communication manuelle, et l'email reste un bonus
        # (utile pour d'éventuelles adresses externes).
        nom_affiche = f'{first_name} {last_name}'.strip() or username
        email_statut = None

        # Texte d'invitation construit une seule fois : sert à l'envoi ET à
        # l'affichage à l'écran (copier-coller pour communication manuelle).
        message_invitation = (
            f'Bonjour {first_name or username},\n\n'
            f'Votre compte CB Bretagne a été créé.\n\n'
            f'Identifiant : {username}\n'
            f'Mot de passe temporaire : {mdp_temp}\n\n'
            f'Connectez-vous ici : {settings.SITE_URL}/login/\n\n'
            f'Merci de changer votre mot de passe dès votre première connexion.\n\n'
            f'Un manuel utilisateur est disponible directement sur le site : {settings.SITE_URL}/aide/\n\n'
            f'CB Bretagne'
        )

        if email:
            try:
                send_mail(
                    subject='Votre compte CB Bretagne',
                    message=message_invitation,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
                nouveau_profil.invitation_envoyee = True
                nouveau_profil.save(update_fields=['invitation_envoyee'])
                email_statut = (
                    f"Un email d'invitation a été envoyé à {email}. ⚠️ En beta, la "
                    f"délivrance vers les adresses @compagnonsbatisseurs.eu n'est pas "
                    f"garantie : copiez le message ci-dessous et envoyez-le par un autre "
                    f"canal (Teams, votre messagerie)."
                )
            except Exception as e:
                logger.error('Invitation email error (user %s): %s', username, e)
                email_statut = (
                    f"L'email d'invitation vers {email} n'a pas pu être envoyé — "
                    f"copiez le message ci-dessous et transmettez-le manuellement."
                )
        else:
            email_statut = 'Aucune adresse email renseignée — copiez le message ci-dessous et transmettez-le manuellement.'

        # Toujours afficher le message d'invitation complet (une seule fois)
        request.session['nouveau_user_mdp'] = {
            'username': username,
            'mdp': mdp_temp,
            'nom': nom_affiche,
            'email': email,
            'message': message_invitation,
            'email_statut': email_statut,
        }
        return redirect('core:utilisateur-create-succes')

    # GET — construction du formulaire
    if profil_courant.role == 'admin':
        equipes_disponibles = Equipe.objects.select_related('service__territoire').all().order_by('service__nom', 'nom')
        roles_disponibles = ProfilUtilisateur.ROLE_CHOICES
    else:
        equipes_disponibles = profil_courant.equipes.select_related('service__territoire').all().order_by('service__nom', 'nom')
        # Responsable ne peut pas créer d'admin
        roles_disponibles = [
            (k, v) for k, v in ProfilUtilisateur.ROLE_CHOICES if k != 'admin'
        ]

    return render(request, 'core/utilisateur_form.html', {
        'profil': profil_courant,
        'equipes': equipes_disponibles,
        'roles': roles_disponibles,
        'services': Service.objects.select_related('territoire').all(),
        'responsables': ProfilUtilisateur.objects.filter(
            role__in=('admin', 'responsable'), user__is_active=True
        ).select_related('user').order_by('user__last_name'),
        'utilisateurs_biblio': User.objects.filter(
            is_active=True
        ).select_related('profil').order_by('last_name', 'first_name'),
        'mode': 'creation',
    })


@login_required
def utilisateur_create_succes(request):
    """
    Page affichée une seule fois après la création d'un utilisateur.
    Affiche le mot de passe temporaire puis le supprime de la session.
    """
    if not peut_gerer_utilisateurs(request.user):
        return redirect('core:dashboard')

    infos = request.session.pop('nouveau_user_mdp', None)
    if not infos:
        return redirect('core:utilisateurs-list')

    return render(request, 'core/utilisateur_succes.html', {
        'infos': infos,
        'profil': get_profil(request.user),
    })


@login_required
def utilisateur_edit(request, pk):
    """
    Modification d'un utilisateur existant : rôle, équipes, service, responsable.
    Ne modifie pas le mot de passe (feature séparée).
    """
    if not peut_gerer_utilisateurs(request.user):
        messages.error(request, 'Accès réservé aux administrateurs et responsables.')
        return redirect('core:dashboard')

    cible_profil = get_object_or_404(ProfilUtilisateur, user__pk=pk)
    profil_courant = get_profil(request.user)

    if not peut_gerer_cet_utilisateur(request.user, cible_profil):
        messages.error(request, 'Vous ne pouvez pas modifier cet utilisateur.')
        return redirect('core:utilisateurs-list')

    if request.method == 'POST':
        # Infos de base
        cible_profil.user.first_name = request.POST.get('first_name', '').strip()
        cible_profil.user.last_name  = request.POST.get('last_name', '').strip()
        cible_profil.user.email      = request.POST.get('email', '').strip()
        cible_profil.user.save()

        role = request.POST.get('role', cible_profil.role)

        # Responsable ne peut pas promouvoir en admin
        if profil_courant.role == 'responsable' and role == 'admin':
            messages.error(request, 'Vous ne pouvez pas attribuer le rôle administrateur.')
            return redirect('core:utilisateur-edit', pk=pk)

        cible_profil.role          = role
        cible_profil.service_id    = request.POST.get('service') or None
        cible_profil.responsable_id = request.POST.get('responsable') or None
        cible_profil.save()

        equipes_ids = request.POST.getlist('equipes')
        cible_profil.equipes.set(equipes_ids)

        messages.success(request, f'Utilisateur "{cible_profil.user.username}" mis à jour.')
        return redirect('core:utilisateurs-list')

    # GET
    if profil_courant.role == 'admin':
        equipes_disponibles = Equipe.objects.select_related('service__territoire').all().order_by('service__nom', 'nom')
        roles_disponibles = ProfilUtilisateur.ROLE_CHOICES
    else:
        equipes_disponibles = profil_courant.equipes.select_related('service__territoire').all().order_by('service__nom', 'nom')
        roles_disponibles = [
            (k, v) for k, v in ProfilUtilisateur.ROLE_CHOICES if k != 'admin'
        ]

    return render(request, 'core/utilisateur_form.html', {
        'profil': profil_courant,
        'cible': cible_profil,
        'equipes': equipes_disponibles,
        'roles': roles_disponibles,
        'services': Service.objects.select_related('territoire').all(),
        'responsables': ProfilUtilisateur.objects.filter(
            role__in=('admin', 'responsable'), user__is_active=True
        ).select_related('user').order_by('user__last_name'),
        'mode': 'edition',
    })


@login_required
@require_POST
def utilisateur_toggle(request, pk):
    """
    Bascule is_active de l'utilisateur (désactiver / réactiver).
    Un admin ne peut pas se désactiver lui-même.
    """
    if not peut_gerer_utilisateurs(request.user):
        messages.error(request, 'Accès réservé aux administrateurs et responsables.')
        return redirect('core:dashboard')

    cible_profil = get_object_or_404(ProfilUtilisateur, user__pk=pk)

    if not peut_gerer_cet_utilisateur(request.user, cible_profil):
        messages.error(request, 'Vous ne pouvez pas modifier cet utilisateur.')
        return redirect('core:utilisateurs-list')

    # Empêcher l'auto-désactivation
    if cible_profil.user == request.user:
        messages.error(request, 'Vous ne pouvez pas désactiver votre propre compte.')
        return redirect('core:utilisateurs-list')

    cible_user = cible_profil.user
    cible_user.is_active = not cible_user.is_active
    cible_user.save()

    action = 'réactivé' if cible_user.is_active else 'désactivé'
    messages.success(request, f'Utilisateur "{cible_user.username}" {action}.')
    return redirect('core:utilisateurs-list')


# ══════════════════════════════════════════
#  OUTILS COMPTA — Factures structure / Appels de convention / Avoirs
# ══════════════════════════════════════════
#
# Factures créées directement, sans devis. Réservées aux rôles compta
# (peut_acceder_compta). Réutilisent le modèle Facture/LigneFacture :
#   - devis = None
#   - type_doc in ('structure', 'appel')  (+ 'avoir' généré depuis une facture)
#   - lignes plates à 2 niveaux : TITRE (groupe) + F (forfait)
# La validation suit peut_valider_facture (admin ou comptable). draft = proforma.

from django.db.models import Q

# Métadonnées d'affichage par type d'outil compta
COMPTA_TYPES = {
    'structure': {'titre': 'Factures Structure',     'singulier': 'Facture structure',
                  'list_url': 'core:compta-structures-list'},
    'appel':     {'titre': 'Appels de convention',   'singulier': 'Appel de convention',
                  'list_url': 'core:compta-appels-list'},
}


def _compta_lignes_to_dict(ligne):
    """Sérialise une LigneFacture compta (TITRE/forfait) en dict JSON."""
    return {
        'id': ligne.pk,
        'type_ligne': ligne.type_ligne,
        'description': ligne.description,
        'quantite': float(ligne.quantite),
        'unite': ligne.unite,
        'cout_unitaire': float(ligne.cout_unitaire) if ligne.cout_unitaire is not None else None,
        'ordre': ligne.ordre,
        'enfants': [_compta_lignes_to_dict(e) for e in ligne.enfants.all().order_by('ordre')],
    }


@login_required
def factures_compta_list(request, type_doc):
    """Liste des factures d'un outil compta + leurs avoirs liés."""
    if not peut_acceder_compta(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('core:dashboard')

    meta = COMPTA_TYPES[type_doc]
    factures = Facture.objects.filter(
        Q(type_doc=type_doc, devis__isnull=True)
        | Q(type_doc='avoir', facture_origine__type_doc=type_doc)
    ).select_related('client', 'facture_origine', 'created_by').prefetch_related('avoirs').order_by('-created_at')

    page_obj, base_qs = paginer(request, factures)

    return render(request, 'core/facture_compta_list.html', {
        'factures': page_obj,
        'page_obj': page_obj,
        'base_qs': base_qs,
        'type_doc': type_doc,
        'meta': meta,
    })


@login_required
def facture_compta_create(request, type_doc):
    """Création directe d'une facture compta (structure ou appel)."""
    if not peut_acceder_compta(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('core:dashboard')

    meta = COMPTA_TYPES[type_doc]
    profil = get_profil(request.user)

    if request.method == 'POST':
        client_id = request.POST.get('client') or None
        client = Client.objects.filter(pk=client_id).first() if client_id else None
        contact_id = request.POST.get('contact_client') or None
        contact = None
        if contact_id and client:
            contact = ContactClient.objects.filter(pk=contact_id, client=client).first()

        objet = request.POST.get('notes', '').strip()
        try:
            echeance_jours = int(request.POST.get('echeance_jours') or 30)
        except (TypeError, ValueError):
            echeance_jours = 30

        destinataire = (client.nom if client else request.POST.get('destinataire', '').strip())

        facture = Facture.objects.create(
            type_doc=type_doc,
            devis=None,
            client=client,
            contact_client=contact,
            destinataire=destinataire or 'Sans nom',
            notes=objet,
            date_echeance=date.today() + timedelta(days=echeance_jours),
            conditions_facture=profil.conditions_facture,
            coordonnees_cb=profil.coordonnees_cb,
            created_by=request.user,
        )
        add_audit(request.user, f"Création {meta['singulier']} {facture.get_reference()}",
                  facture=facture)
        return redirect('core:compta-facture-detail', pk=facture.pk)

    return render(request, 'core/facture_compta_form.html', {
        'type_doc': type_doc,
        'meta': meta,
        'profil': profil,
    })


@login_required
def facture_compta_detail(request, pk):
    """Éditeur 2 niveaux (titres + forfaits) d'une facture compta ou d'un avoir."""
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_voir_facture(request.user, facture):
        messages.error(request, "Vous n'avez pas accès à cette facture.")
        return redirect('core:dashboard')

    meta = COMPTA_TYPES.get(
        facture.facture_origine.type_doc if facture.type_doc == 'avoir' and facture.facture_origine
        else facture.type_doc,
        {'titre': 'Facture', 'singulier': 'Facture', 'list_url': 'core:factures-list'},
    )
    return render(request, 'core/facture_compta_detail.html', {
        'facture': facture,
        'meta': meta,
        'modifiable': facture.status == 'draft' and peut_modifier_facture(request.user, facture),
        'profil': get_profil(request.user),
    })


@login_required
def lignes_compta_get(request, pk):
    """Retourne les lignes (titres + forfaits) + montant de la facture compta."""
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_voir_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    racines = facture.lignes.filter(parent=None).order_by('ordre')
    return JsonResponse({
        'lignes': [_compta_lignes_to_dict(l) for l in racines],
        'montant': float(facture.montant),
        'notes': facture.notes,
    })


@login_required
@require_POST
def lignes_compta_save(request, pk):
    """Remplace les lignes (titres + forfaits) ; recalcule le montant (± pour les avoirs)."""
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_modifier_facture(request.user, facture):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    if facture.status != 'draft':
        return JsonResponse({'error': 'Facture non modifiable'}, status=400)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    notes = data.get('notes', None)
    if notes is not None:
        facture.notes = notes
    lignes = data.get('lignes', [])

    facture.lignes.all().delete()

    def create_lignes(items, parent=None, ordre=0):
        for item in items:
            type_ligne = item.get('type_ligne', 'F')
            lf = LigneFacture.objects.create(
                facture=facture, parent=parent,
                type_ligne=type_ligne,
                description=item.get('description', ''),
                quantite=to_decimal(item.get('quantite'), default=Decimal('1')),
                unite=item.get('unite', ''),
                cout_unitaire=to_decimal(item.get('cout_unitaire')),
                ordre=ordre,
            )
            if type_ligne == 'TITRE':
                create_lignes(item.get('enfants', []), parent=lf)
            ordre += 1

    create_lignes(lignes)

    total = sum(l.total() for l in facture.lignes.filter(parent=None))
    facture.montant = total
    facture.save()
    return JsonResponse({'ok': True, 'montant': float(total)})


@login_required
@require_POST
def facture_compta_valider(request, pk):
    """Validation comptable d'une facture compta — assigne le numéro."""
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_acceder_compta(request.user) or not peut_valider_facture(request.user, facture):
        messages.error(request, "Validation réservée à la comptabilité.")
        return redirect('core:compta-facture-detail', pk=pk)
    if not facture.numero:
        facture.numero = gen_numero_facture(facture.type_doc)
    facture.status = 'validated'
    facture.validated_by = request.user
    facture.validated_at = timezone.now()
    facture.save()
    add_audit(request.user, f"Validation {facture.numero} ({facture.destinataire})", facture=facture)
    return redirect('core:compta-facture-detail', pk=pk)


@login_required
@require_POST
def facture_compta_status(request, pk):
    """Changement de statut d'une facture compta (validée → envoyée → payée)."""
    facture = get_object_or_404(Facture, pk=pk)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
    if not peut_modifier_facture(request.user, facture):
        if is_ajax:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
        messages.error(request, 'Vous ne pouvez pas modifier cette facture.')
        return redirect('core:compta-facture-detail', pk=pk)
    old = facture.status
    facture.status = request.POST.get('status', facture.status)
    facture.save()
    add_audit(request.user, f"Statut {facture.get_reference()} : {old} → {facture.status}", facture=facture)
    if is_ajax:
        return JsonResponse({'ok': True})
    return redirect('core:compta-facture-detail', pk=pk)


@login_required
@require_POST
def facture_compta_delete(request, pk):
    """Suppression d'une facture compta — brouillons uniquement."""
    facture = get_object_or_404(Facture, pk=pk)
    if not peut_supprimer_facture(request.user, facture):
        messages.error(request, 'Vous ne pouvez pas supprimer cette facture.')
        return redirect('core:compta-facture-detail', pk=pk)
    # Liste de retour selon le type (avoir → liste de la facture d'origine)
    type_retour = (facture.facture_origine.type_doc
                   if facture.type_doc == 'avoir' and facture.facture_origine
                   else facture.type_doc)
    list_url = COMPTA_TYPES.get(type_retour, {}).get('list_url', 'core:dashboard')
    ref = facture.get_reference()
    add_audit(request.user, f"Suppression facture compta {ref}", facture=None)
    facture.delete()
    messages.success(request, f'Facture {ref} supprimée.')
    return redirect(list_url)


@login_required
@require_POST
def facture_compta_duplicate(request, pk):
    """Duplique une facture compta (structure/appel) en un nouveau brouillon."""
    source = get_object_or_404(Facture, pk=pk)
    if not peut_acceder_compta(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('core:dashboard')
    if source.type_doc not in ('structure', 'appel'):
        messages.error(request, "Seules les factures structure et appels peuvent être dupliqués.")
        return redirect('core:compta-facture-detail', pk=source.pk)

    copie = Facture.objects.create(
        type_doc=source.type_doc,
        devis=None,
        client=source.client,
        contact_client=source.contact_client,
        destinataire=source.destinataire,
        notes=source.notes,
        date_echeance=source.date_echeance,
        conditions_facture=source.conditions_facture,
        coordonnees_cb=source.coordonnees_cb,
        created_by=request.user,
    )

    def copier(lignes_src, parent=None):
        for l in lignes_src.order_by('ordre'):
            nl = LigneFacture.objects.create(
                facture=copie, parent=parent,
                type_ligne=l.type_ligne,
                description=l.description,
                quantite=l.quantite,
                quantite_originale=l.quantite_originale,
                unite=l.unite,
                cout_unitaire=l.cout_unitaire,
                ordre=l.ordre,
            )
            copier(l.enfants.all(), parent=nl)

    copier(source.lignes.filter(parent=None))
    copie.montant = sum(l.total() for l in copie.lignes.filter(parent=None))
    copie.save()

    add_audit(request.user, f"Duplication {source.get_reference()} → brouillon", facture=copie)
    return redirect('core:compta-facture-detail', pk=copie.pk)


@login_required
@require_POST
def avoir_create(request, facture_pk):
    """
    Crée un avoir depuis une facture validée : copie les lignes avec quantités
    inversées (négatives), modifiables ensuite dans l'éditeur. Fonctionne pour
    tous les types (chantier / structure / appel).
    """
    source = get_object_or_404(Facture, pk=facture_pk)
    if not peut_modifier_facture(request.user, source):
        messages.error(request, "Vous ne pouvez pas créer d'avoir sur cette facture.")
        return redirect('core:dashboard')
    if source.status not in ('validated', 'sent', 'paid'):
        messages.error(request, "Un avoir ne peut être créé que depuis une facture validée.")
        return redirect('core:compta-facture-detail', pk=source.pk)

    avoir = Facture.objects.create(
        type_doc='avoir',
        devis=source.devis,
        client=source.client,
        contact_client=source.contact_client,
        facture_origine=source,
        destinataire=source.destinataire,
        notes=f"Avoir sur facture {source.get_reference()}",
        conditions_facture=source.conditions_facture,
        coordonnees_cb=source.coordonnees_cb,
        created_by=request.user,
    )

    # Copie des lignes avec quantités inversées (récursif : titres + enfants)
    def copier_negatif(lignes_src, parent=None):
        for l in lignes_src.order_by('ordre'):
            qte = l.quantite if l.type_ligne == 'TITRE' else (l.quantite * Decimal('-1'))
            nl = LigneFacture.objects.create(
                facture=avoir, parent=parent,
                type_ligne=l.type_ligne,
                description=l.description,
                quantite=qte,
                quantite_originale=l.quantite_originale,
                unite=l.unite,
                cout_unitaire=l.cout_unitaire,
                ordre=l.ordre,
                ligne_devis_source=l.ligne_devis_source,
            )
            copier_negatif(l.enfants.all(), parent=nl)

    copier_negatif(source.lignes.filter(parent=None))
    avoir.montant = sum(l.total() for l in avoir.lignes.filter(parent=None))
    avoir.save()

    add_audit(request.user, f"Création avoir sur {source.get_reference()}",
              devis=source.devis, facture=avoir)
    return redirect('core:compta-facture-detail', pk=avoir.pk)


# ── Contacts client (carnet optionnel) ──────────────────────────────

@login_required
def client_contacts_get(request, client_pk):
    """Liste JSON des contacts d'un client (pour le select du formulaire compta)."""
    if not peut_acceder_compta(request.user):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    client = get_object_or_404(Client, pk=client_pk)
    contacts = [
        {'id': c.pk, 'label': str(c), 'service': c.service, 'nom': c.nom,
         'email': c.email, 'telephone': c.telephone}
        for c in client.contacts.all()
    ]
    return JsonResponse({'contacts': contacts})


@login_required
@require_POST
def contact_client_create(request):
    """Ajout rapide d'un contact à un client → {id, label}."""
    if not peut_acceder_compta(request.user):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    client = get_object_or_404(Client, pk=data.get('client'))
    service = (data.get('service') or '').strip()
    nom = (data.get('nom') or '').strip()
    if not service and not nom:
        return JsonResponse({'error': 'Service ou nom requis'}, status=400)
    contact = ContactClient.objects.create(
        client=client,
        service=service,
        nom=nom,
        fonction=(data.get('fonction') or '').strip(),
        email=(data.get('email') or '').strip(),
        telephone=(data.get('telephone') or '').strip(),
    )
    return JsonResponse({'ok': True, 'id': contact.pk, 'label': str(contact)})


@login_required
@require_POST
def contact_client_delete(request, pk):
    """Suppression d'un contact (admin uniquement, comme l'édition client)."""
    if not is_admin(request.user):
        return JsonResponse({'error': 'Réservé à l\'administrateur'}, status=403)
    contact = get_object_or_404(ContactClient, pk=pk)
    contact.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════
#  PLANNING & ÉMARGEMENT — Équipiers
# ══════════════════════════════════════════
#
# Gestion des équipiers (salariés en insertion à pointer). Réservé au module
# Insertion (peut_acceder_planning : admin / responsable / rh / encadrant).
# Suppression = désactivation (actif=False), jamais de DELETE dur.

def _planning_date(val):
    """Parse une date 'YYYY-MM-DD' issue d'un <input type=date> ; '' -> None."""
    val = (val or '').strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except ValueError:
        return None


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

COLORS_AFF    = ['cha', 'chb', 'chc', 'cha', 'chb']
JOURS_FR      = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven']
CRENEAUX      = [('matin', 'M'), ('aprem', 'A')]
DEF_H         = {'matin': '4', 'aprem': '3'}
CRENEAU_ORDER = {'matin': 0, 'aprem': 1}


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


@login_required
def emargement_view(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    equipe_id = request.GET.get('equipe', '').strip()
    debut_str = request.GET.get('debut', '').strip()

    today = date.today()
    try:
        debut = datetime.strptime(debut_str, '%Y-%m-%d').date() if debut_str else today
    except ValueError:
        debut = today
    lundi   = debut - timedelta(days=debut.weekday())
    vendredi = lundi + timedelta(days=4)

    profil = get_profil(request.user)
    if profil.role in ('admin', 'responsable', 'rh'):
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
    aff_color = {aff.pk: COLORS_AFF[aff.tranche.devis_id % len(COLORS_AFF)] for aff in affectations}
    for aff in affectations:
        aff.css_color = aff_color[aff.pk]

    # Affectation active par jour (première couvrant ce jour)
    day_aff = {}
    for jour in jours:
        for aff in affectations:
            if aff.date_debut <= jour <= aff.date_fin:
                day_aff[jour] = aff
                break
    aff_default = affectations[0] if affectations else None

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

    def _build_cren_rows(eq, is_borrowed, pret=None):
        total_h = Decimal('0')
        cren_rows = []
        for creneau, label in CRENEAUX:
            cells = []
            for jour in jours:
                date_iso = jour.isoformat()
                key = (eq.pk, date_iso, creneau)
                pres = pres_map.get(key)
                if pres and pres.heures:
                    total_h += pres.heures
                is_off         = is_jour_off(jour)
                is_ferie       = jour in jours_feries_ev
                ferie_label    = jours_feries_ev[jour].libelle if is_ferie else ''
                is_ferie_legal = jour in feries_legaux
                special_code   = 'R' if is_ferie else ('F' if is_ferie_legal else None)
                if is_borrowed:
                    loan = _in_loan(jour, creneau, pret) and not is_off
                    is_lent = loan
                    is_away = not loan and not is_off
                    away_team_nom = None
                    aff_c = pres.affectation if pres else (day_aff.get(jour, aff_default) if loan else None)
                else:
                    pret_away_team = pret_away_map.get((eq.pk, date_iso, creneau))
                    is_lent = False
                    is_away = (key in away_set) or bool(pret_away_team)
                    away_team_nom = pret_away_team
                    aff_c = pres.affectation if pres else day_aff.get(jour, aff_default)
                cells.append({
                    'jour': jour,
                    'date_iso': date_iso,
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
                    'is_mon': (jour.weekday() == 0),
                })
            cren_rows.append({'label': label, 'creneau': creneau, 'cells': cells})
        return cren_rows, total_h

    grid_rows_maison = []
    for eq in equipiers_maison:
        cren_rows, total_h = _build_cren_rows(eq, is_borrowed=False)
        grid_rows_maison.append({'equipier': eq, 'is_borrowed': False, 'pret_id': None, 'cren_rows': cren_rows, 'total_h': total_h})

    grid_rows_empruntes = []
    for eq in equip_empruntes:
        pret = pret_map[eq.pk]
        cren_rows, total_h = _build_cren_rows(eq, is_borrowed=True, pret=pret)
        grid_rows_empruntes.append({
            'equipier': eq, 'is_borrowed': True, 'pret_id': pret.pk,
            'pret_debut': pret.date_debut, 'pret_fin': pret.date_fin,
            'pret_debut_creneau': pret.creneau_debut, 'pret_fin_creneau': pret.creneau_fin,
            'cren_rows': cren_rows, 'total_h': total_h,
        })

    panel_equipes = list(
        Equipe.objects.filter(actif=True, service__module_planning=True)
        .prefetch_related(
            Prefetch('equipiers',
                     queryset=Equipier.objects.filter(actif=True).order_by('nom', 'prenom'))
        ).order_by('nom')
    )

    devis_dispo = list(
        Devis.objects.filter(status='accepted')
        .select_related('client')
        .prefetch_related('lignes')
        .order_by('client__nom')
    )
    devis_mo_json  = {d.pk: float(total_mo_devis(d)) for d in devis_dispo}
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

    return render(request, 'core/emargement.html', {
        'equipes': equipes,
        'equipe_sel': equipe_sel,
        'lundi': lundi,
        'vendredi': vendredi,
        'jours': jours,
        'jours_info': jours_info,
        'affectations': affectations,
        'aff_color': aff_color,
        'aff_default': aff_default,
        'grid_rows_maison': grid_rows_maison,
        'grid_rows_empruntes': grid_rows_empruntes,
        'panel_equipes': panel_equipes_all,
        'devis_dispo': devis_dispo,
        'devis_mo_json': devis_mo_json,
        'equipe_effectifs_json': equipe_effectifs_json,
        'semaine_prec': (lundi - timedelta(weeks=1)).isoformat(),
        'semaine_suiv': (lundi + timedelta(weeks=1)).isoformat(),
        'peut_modifier': est_encadrant(request.user, equipe_sel),
    })


@login_required
def planning_mois(request):
    if not peut_acceder_planning(request.user):
        return HttpResponseForbidden("Accès réservé au module Insertion.")

    profil = get_profil(request.user)
    peut_modifier_global = profil.role in ('admin', 'responsable')

    default_sem = 8 if profil.role in ('admin', 'responsable', 'rh') else 4
    nb_semaines = max(1, min(52, int(request.GET.get('semaines', '') or default_sem)))

    today = date.today()
    debut_str = request.GET.get('debut', '')
    try:
        debut_grille = datetime.strptime(debut_str, '%Y-%m-%d').date()
        debut_grille -= timedelta(days=debut_grille.weekday())  # recaler au lundi
    except (ValueError, AttributeError):
        debut_grille = today - timedelta(days=today.weekday())

    nb_jours   = nb_semaines * 7
    fin_grille = debut_grille + timedelta(days=nb_jours - 1)
    jours      = [debut_grille + timedelta(days=i) for i in range(nb_jours)]

    # En-têtes semaines : numéro ISO
    semaines = [
        {'num': (debut_grille + timedelta(weeks=w)).isocalendar()[1]}
        for w in range(nb_semaines)
    ]

    equipes = Equipe.objects.filter(actif=True, service__module_planning=True).order_by('ordre', 'nom')
    affectations = list(
        Affectation.objects
        .filter(equipe__in=equipes, date_debut__lte=fin_grille, date_fin__gte=debut_grille)
        .select_related('tranche__devis__client', 'equipe')
        .order_by('date_debut')
    )
    aff_color = {aff.pk: COLORS_AFF[aff.tranche.devis_id % len(COLORS_AFF)] for aff in affectations}
    equipes_modifiables_ids = {e.pk for e in equipes if est_encadrant(request.user, e)}

    # MO des devis sur la grille (pour pct_consomme)
    devis_dispo = list(
        Devis.objects.filter(status='accepted')
        .select_related('client')
        .prefetch_related('lignes')
        .order_by('client__nom')
    )
    devis_mo_json = {d.pk: float(total_mo_devis(d)) for d in devis_dispo}
    equipe_effectifs_json = {e.pk: e.nb_equipiers for e in equipes}

    # Heures consommées par tranche (somme presences de toutes les équipes affectées)
    from django.db.models import Sum as _DbSum
    tranche_ids = list({aff.tranche_id for aff in affectations})
    _rows = (
        Presence.objects.filter(affectation__tranche_id__in=tranche_ids)
        .values('affectation__tranche_id')
        .annotate(total=_DbSum('heures'))
    ) if tranche_ids else []
    heures_par_tranche = {r['affectation__tranche_id']: float(r['total']) for r in _rows}

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
            mo_eur = devis_mo_json.get(aff.tranche.devis_id, 0)
            heures_budget = mo_eur / float(_TAUX_JOUR_PLANNING) * 7
            heures_conso  = heures_par_tranche.get(aff.tranche_id, 0)
            pct_consomme  = min(100, round(heures_conso / heures_budget * 100)) if heures_budget > 0 else 0
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

        peut_modifier_ligne = peut_modifier_global or equipe.pk in equipes_modifiables_ids
        lignes.append({
            'equipe': equipe,
            'barres': barres,
            'ev_barres': ev_barres,
            'jours_sup': jours_sup,
            'peut_modifier': peut_modifier_ligne,
        })

    prec_debut = (debut_grille - timedelta(weeks=4)).isoformat()
    suiv_debut = (debut_grille + timedelta(weeks=4)).isoformat()

    # Pour chaque devis déjà affiché sur la grille : liste des équipes déjà affectées
    devis_equipes: dict[int, list[int]] = {}
    for aff in affectations:
        did = aff.tranche.devis_id
        devis_equipes.setdefault(did, [])
        if aff.equipe_id not in devis_equipes[did]:
            devis_equipes[did].append(aff.equipe_id)

    # 12 cols/semaine : 10 demi-j (10×13px) + 1 Sam (8px) + 1 Dim (8px)
    tl_min_width = 180 + nb_semaines * (10 * 13 + 2 * 8)

    # —— Nouvelles données pour la modal d'affectation ——
    tranches_par_devis = {}
    for t in TrancheDevis.objects.filter(devis__in=devis_dispo).prefetch_related('affectations__equipe').order_by('ordre', 'nom'):
        tranches_par_devis.setdefault(t.devis_id, []).append({
            'id': t.pk,
            'nom': t.nom,
            'equipes': [{'nom': a.equipe.nom} for a in t.affectations.all()],
        })
    mo_planifie_par_devis = {}
    for _a in Affectation.objects.filter(tranche__devis__in=devis_dispo).select_related('equipe', 'tranche__devis'):
        _pos, _neg = _build_evenement_sets(_a.equipe_id, _a.date_debut, _a.date_fin)
        _nbj = _count_working_days(_a.date_debut, _a.date_fin, _pos, _neg)
        _mo = float(_nbj * _a.equipe.nb_equipiers * _TAUX_JOUR_PLANNING)
        mo_planifie_par_devis[_a.tranche.devis_id] = mo_planifie_par_devis.get(_a.tranche.devis_id, 0) + _mo
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
        'tl_min_width': tl_min_width,
        'semaines': semaines,
        'lignes': lignes,
        'debut_grille': debut_grille,
        'fin_grille': fin_grille,
        'prec_debut': prec_debut,
        'suiv_debut': suiv_debut,
        'peut_modifier_global': peut_modifier_global,
        'equipes_modifiables_ids': list(equipes_modifiables_ids),
        'devis_dispo': devis_dispo,
        'devis_mo_json': devis_mo_json,
        'equipe_effectifs_json': equipe_effectifs_json,
        'devis_equipes_json': json.dumps(devis_equipes),
        'tranches_par_devis_json': json.dumps(tranches_par_devis),
        'mo_planifie_par_devis_json': json.dumps(mo_planifie_par_devis),
        'aff_par_equipe_json': json.dumps(aff_par_equipe),
        'equipes_plan_json': json.dumps([{'id': e.pk, 'nom': e.nom, 'nb_eq': e.nb_equipiers, 'modifiable': e.pk in equipes_modifiables_ids} for e in equipes]),
        'ev_positifs_json': json.dumps(ev_positifs_json_data),
        'ev_negatifs_json': json.dumps(ev_negatifs_json_data),
        'today': date.today(),
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
            }
            for ev in evenements
        }),
    })


@login_required
@require_POST
def tranche_creer(request):
    if not peut_acceder_planning(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)
    devis = get_object_or_404(Devis, pk=data.get('devis_id'), status='accepted')
    nom = (data.get('nom') or '').strip() or 'Nouvelle tranche'
    ordre = TrancheDevis.objects.filter(devis=devis).count() + 1
    t = TrancheDevis.objects.create(devis=devis, nom=nom, ordre=ordre)
    return JsonResponse({'ok': True, 'id': t.pk, 'nom': t.nom})


_TAUX_JOUR_PLANNING = Decimal('82.5')  # €/jour/équipier, cohérent avec TAUX_JOUR dans planning.html


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
    from django.db.models import Q
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


@login_required
@require_POST
def evenement_save(request):
    if not peut_acceder_planning(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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

    ev.type           = type_ev
    ev.libelle        = libelle
    ev.date_debut     = date_debut
    ev.date_fin       = date_fin
    ev.creneau        = creneau
    ev.travaille      = travaille
    ev.decale_chantier = decale and not travaille  # décalage seulement si événement négatif
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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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

    changing_equipe = equipe_id and int(equipe_id) != aff.equipe_id
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
    recalculated_pks = _recalcul_durees_tranche(tranche, tranche.devis) if changing_equipe else []

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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

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


@login_required
@require_POST
def presence_save(request):
    if not peut_acceder_planning(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

    saved = deleted = 0
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

        # Résolution de l'affectation — nullable depuis migration 0024.
        aff_id_raw = item.get('affectation_id')
        aff = None
        if aff_id_raw:
            try:
                aff = Affectation.objects.select_related('equipe').filter(pk=int(aff_id_raw)).first()
            except (ValueError, TypeError):
                pass

        # Gate permission : via l'affectation si elle existe, sinon via l'équipe maison.
        if aff:
            if not est_encadrant(request.user, aff.equipe):
                continue
        else:
            if not equipier.equipe or not est_encadrant(request.user, equipier.equipe):
                continue
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

    return JsonResponse({'ok': True, 'saved': saved, 'deleted': deleted})


@login_required
def pret_save(request):
    if not peut_acceder_planning(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST requis'}, status=405)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

    action = data.get('action', 'create')
    if action == 'delete':
        try:
            pret = Pret.objects.select_related('equipe_hote', 'equipier').get(pk=data.get('pret_id'))
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

import calendar
from django.db.models import Q as _Q


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
        paques + timedelta(days=1),
        paques + timedelta(days=39),
        paques + timedelta(days=50),
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
    today  = date.today()

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
    for d_sp in pont_dates:
        special_map[d_sp.isoformat()] = 'R'   # pont écrase légal si même jour

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

    return render(request, 'core/presence_feuille.html', {
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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

    try:
        equipier_id = int(data.get('equipier_id', 0))
        d           = datetime.strptime(data.get('date', ''), '%Y-%m-%d').date()
        creneau     = data.get('creneau', '')
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Paramètres invalides'}, status=400)

    if creneau not in ('matin', 'aprem'):
        return JsonResponse({'ok': False, 'error': 'Créneau invalide'}, status=400)

    equipier = Equipier.objects.select_related('equipe').filter(pk=equipier_id, actif=True).first()
    if not equipier or not equipier.equipe:
        return JsonResponse({'ok': False, 'error': 'Équipier introuvable'}, status=404)

    if not est_encadrant(request.user, equipier.equipe):
        return JsonResponse({'ok': False, 'error': 'Permission refusée'}, status=403)

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
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'JSON invalide'}, status=400)

    try:
        equipier_id = int(data.get('equipier_id', 0))
        annee       = int(data.get('annee', 0))
        mois        = int(data.get('mois', 0))
        num_semaine = int(data.get('num_semaine', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Paramètres invalides'}, status=400)

    equipier = Equipier.objects.select_related('equipe').filter(pk=equipier_id, actif=True).first()
    if not equipier or not equipier.equipe:
        return JsonResponse({'ok': False, 'error': 'Équipier introuvable'}, status=404)

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
