from django.contrib import admin
from .models import (
    Territoire, Service, Equipe, ProfilUtilisateur,
    ParametresAssociation, Client, ContactClient,
    Devis, LigneDevis, Facture, LigneFacture, AuditLog,
    Bibliotheque,
    Financeur, Equipier, TrancheDevis, Affectation,
    Evenement, Presence, ClotureMois, Pret,
)


# ══════════════════════════════════════════
#  STRUCTURE ORGANISATIONNELLE
# ══════════════════════════════════════════

@admin.register(Territoire)
class TerritoireAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'ordre']
    ordering = ['ordre', 'nom']


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['nom', 'territoire']
    list_filter = ['territoire']
    search_fields = ['nom']


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ['nom', 'service', 'type_rangee', 'encadrant', 'nb_equipiers', 'activite', 'actif', 'archivee', 'ordre']
    list_editable = ['nb_equipiers']
    list_filter = ['actif', 'type_rangee', 'archivee', 'activite', 'service__territoire', 'service']
    search_fields = ['nom']
    raw_id_fields = ['encadrant']
    filter_horizontal = ['financeurs']


@admin.register(ProfilUtilisateur)
class ProfilUtilisateurAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'service', 'taux_mo_defaut', 'saisie_ht']
    list_filter = ['role', 'service__territoire', 'service']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    filter_horizontal = ['equipes']


# ══════════════════════════════════════════
#  PARAMÈTRES ASSOCIATION
# ══════════════════════════════════════════

@admin.register(ParametresAssociation)
class ParametresAssociationAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Identité', {
            'fields': ('nom', 'forme_juridique', 'siret', 'ape', 'slogan')
        }),
        ('Coordonnées', {
            'fields': ('adresse', 'email', 'telephone', 'site_web')
        }),
        ('Apparence', {
            'fields': ('logo', 'signature', 'couleur_principale', 'couleur_secondaire', 'couleur_accent')
        }),
    )

    def has_add_permission(self, request):
        # Une seule instance possible
        return not ParametresAssociation.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ══════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════

class ContactClientInline(admin.TabularInline):
    model = ContactClient
    extra = 0
    fields = ['service', 'nom', 'fonction', 'email', 'telephone']


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_client', 'contact', 'email', 'telephone', 'code_postal', 'ville', 'created_by']
    list_filter = ['type_client']
    search_fields = ['nom', 'contact', 'email', 'ville', 'code_postal']
    inlines = [ContactClientInline]



# ══════════════════════════════════════════
#  DEVIS
# ══════════════════════════════════════════

class LigneDevisInline(admin.TabularInline):
    model = LigneDevis
    extra = 0
    fields = ['type_ligne', 'description', 'quantite', 'unite', 'cout_unitaire', 'ordre', 'parent']
    show_change_link = True


class TrancheDevisInline(admin.TabularInline):
    model = TrancheDevis
    extra = 0
    fields = ['nom', 'ordre']


@admin.register(Devis)
class DevisAdmin(admin.ModelAdmin):
    list_display = ['reference', 'client', 'equipe', 'chantier', 'status', 'date_creation']
    list_filter = ['status', 'equipe__service__territoire', 'equipe__service']
    search_fields = ['reference', 'client__nom', 'chantier']
    inlines = [TrancheDevisInline, LigneDevisInline]
    readonly_fields = ['created_at', 'updated_at', 'created_by']


# ══════════════════════════════════════════
#  FACTURES
# ══════════════════════════════════════════

class LigneFactureInline(admin.TabularInline):
    model = LigneFacture
    extra = 0
    fields = ['type_ligne', 'description', 'quantite', 'quantite_originale', 'unite', 'cout_unitaire', 'ordre']


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ['get_reference', 'type_doc', 'devis', 'client', 'destinataire', 'montant', 'status']
    list_filter = ['status', 'type_doc', 'bypass_validation']
    search_fields = ['numero', 'destinataire']
    readonly_fields = ['created_at', 'validated_at', 'validated_by', 'created_by']
    raw_id_fields = ['devis', 'client', 'contact_client', 'facture_origine']
    inlines = [LigneFactureInline]


# ══════════════════════════════════════════
#  AUDIT
# ══════════════════════════════════════════

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'action', 'bypass']
    list_filter = ['bypass']
    readonly_fields = ['created_at', 'user', 'action', 'devis', 'facture', 'bypass']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ══════════════════════════════════════════
#  PLANNING & ÉMARGEMENT (insertion)
# ══════════════════════════════════════════

@admin.register(Financeur)
class FinanceurAdmin(admin.ModelAdmin):
    list_display = ['nom', 'logo', 'logo_cle', 'ordre']
    fields = ['nom', 'logo', 'logo_cle', 'ordre']
    ordering = ['ordre', 'nom']


@admin.register(Equipier)
class EquipierAdmin(admin.ModelAdmin):
    list_display = ['prenom', 'nom', 'equipe', 'type_contrat', 'actif']
    list_filter = ['actif', 'equipe']
    search_fields = ['nom', 'prenom', 'matricule']
    raw_id_fields = ['equipe']


@admin.register(TrancheDevis)
class TrancheDevisAdmin(admin.ModelAdmin):
    list_display = ['nom', 'devis', 'statut', 'termine_le', 'ordre']
    list_filter = ['statut']
    search_fields = ['nom', 'devis__reference']
    raw_id_fields = ['devis', 'termine_par']
    filter_horizontal = ['titres']


@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    list_display = ['equipe', 'tranche', 'date_debut', 'debut_creneau', 'date_fin', 'fin_creneau', 'duree_jours', 'epingle']
    list_filter = ['epingle', 'equipe']
    raw_id_fields = ['equipe', 'tranche', 'created_by']
    readonly_fields = ['created_at']


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display   = ['type', 'libelle', 'get_equipes', 'date_debut', 'date_fin', 'creneau', 'decale_chantier', 'travaille']
    list_filter    = ['type', 'decale_chantier', 'travaille']
    filter_horizontal = ['equipes']
    raw_id_fields  = ['equipe']

    @admin.display(description='Équipes')
    def get_equipes(self, obj):
        names = [e.nom for e in obj.equipes.all()]
        return ', '.join(names) if names else '— toutes —'


@admin.register(Presence)
class PresenceAdmin(admin.ModelAdmin):
    list_display = ['equipier', 'date', 'creneau', 'heures', 'code', 'affectation']
    list_filter = ['creneau', 'code', 'date']
    search_fields = ['equipier__nom', 'equipier__prenom']
    raw_id_fields = ['equipier', 'affectation', 'saisi_par']
    readonly_fields = ['saisi_le', 'created_at']


@admin.register(ClotureMois)
class ClotureMoisAdmin(admin.ModelAdmin):
    list_display = ['equipe', 'mois', 'annee', 'cloture_par', 'cloture_le']
    list_filter = ['annee', 'mois', 'equipe']
    raw_id_fields = ['equipe', 'cloture_par']
    readonly_fields = ['cloture_le']


@admin.register(Pret)
class PretAdmin(admin.ModelAdmin):
    list_display = ['equipier', 'equipe_hote', 'date_debut', 'date_fin', 'cree_par', 'cree_le']
    list_filter = ['equipe_hote']
    raw_id_fields = ['equipier', 'equipe_hote', 'cree_par']
    readonly_fields = ['cree_le']