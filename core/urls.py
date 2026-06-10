from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profil/', views.profil_view, name='profil'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('tableau-de-bord/config/', views.dashboard_save, name='dashboard-save'),

    # Aide / Manuel utilisateur (public)
    path('aide/', views.aide_view, name='aide'),

    # Mot de passe oublié (public)
    path('mot-de-passe-oublie/', views.mot_de_passe_oublie, name='mot-de-passe-oublie'),

    # Clients
    path('clients/', views.clients_list, name='clients'),
    path('clients/nouveau/', views.client_create, name='client-create'),
    path('clients/recherche/', views.client_search, name='client-search'),
    path('clients/creation-rapide/', views.client_quick_create, name='client-quick-create'),
    path('clients/<int:pk>/modifier/', views.client_edit, name='client-edit'),
    path('clients/<int:pk>/supprimer/', views.client_delete, name='client-delete'),

    # Bibliothèque personnelle
    path('bibliotheque/',                 views.bibliotheque,    name='biblio'),
    path('bibliotheque/api/',             views.biblio_api_get,  name='biblio-get'),
    path('bibliotheque/api/sauvegarder/', views.biblio_api_save, name='biblio-save'),

    # Bibliothèque Aides (partagée)
    path('bibliotheque/aides/',           views.aides_page,      name='aides-page'),
    path('aides/',                        views.aides_api_get,   name='aides-get'),
    path('aides/sauvegarder/',            views.aides_api_save,  name='aides-save'),
    path('aides/<int:pk>/supprimer/',     views.aide_delete,     name='aide-delete'),

    # Devis
    path('devis/', views.devis_list, name='devis-list'),
    path('devis/nouveau/', views.devis_create, name='devis-create'),
    path('devis/<int:pk>/', views.devis_detail, name='devis-detail'),
    path('devis/<int:pk>/statut/', views.devis_status, name='devis-status'),
    path('devis/<int:pk>/dupliquer/', views.devis_duplicate, name='devis-duplicate'),
    path('devis/<int:pk>/supprimer/', views.devis_delete, name='devis-delete'),
    path('devis/<int:pk>/pdf/', views.devis_pdf, name='devis-pdf'),
    path('devis/<int:pk>/excel/', views.devis_export_excel, name='devis-excel'),
    path('devis/<int:pk>/entete/sauvegarder/', views.devis_entete_save, name='devis-entete-save'),

    # Lignes devis (API JSON)
    path('devis/<int:pk>/lignes/', views.lignes_get, name='lignes-get'),
    path('devis/<int:pk>/lignes/sauvegarder/', views.lignes_save, name='lignes-save'),

    # Factures
    path('factures/', views.factures_list, name='factures-list'),
    path('avoirs/', views.avoirs_list, name='avoirs-list'),
    path('devis/<int:devis_pk>/factures/nouvelle/', views.facture_create, name='facture-create'),
    path('factures/<int:pk>/valider/', views.facture_valider, name='facture-valider'),
    path('factures/<int:pk>/statut/', views.facture_status, name='facture-status'),
    path('factures/<int:pk>/bypass/', views.facture_bypass, name='facture-bypass'),
    path('factures/<int:pk>/bypass/send/', views.facture_bypass_send_code, name='facture-bypass-send'),
    path('factures/<int:pk>/',           views.facture_detail,       name='facture-detail'),
    path('factures/<int:pk>/apercu/',    views.facture_apercu,       name='facture-apercu'),
    path('factures/<int:pk>/libelle/',   views.facture_libelle_save, name='facture-libelle-save'),
    path('factures/<int:pk>/supprimer/', views.facture_delete, name='facture-delete'),
    path('factures/<int:pk>/date-versement/', views.facture_date_versement, name='facture-date-versement'),

    # Lignes facture (API JSON)
    path('factures/<int:pk>/lignes/', views.lignes_facture_get, name='lignes-facture-get'),
    path('factures/<int:pk>/lignes/sauvegarder/', views.lignes_facture_save, name='lignes-facture-save'),

    # Avoir (depuis n'importe quelle facture validée — chantier ou compta)
    path('factures/<int:facture_pk>/avoir/', views.avoir_create, name='avoir-create'),

    # OUTILS COMPTA — Factures structure / Appels de convention
    path('compta/structures/',          views.factures_compta_list, {'type_doc': 'structure'}, name='compta-structures-list'),
    path('compta/structures/nouvelle/', views.facture_compta_create, {'type_doc': 'structure'}, name='compta-structure-create'),
    path('compta/appels/',              views.factures_compta_list, {'type_doc': 'appel'},     name='compta-appels-list'),
    path('compta/appels/nouvelle/',     views.facture_compta_create, {'type_doc': 'appel'},     name='compta-appel-create'),
    path('compta/factures/<int:pk>/',            views.facture_compta_detail,  name='compta-facture-detail'),
    path('compta/factures/<int:pk>/valider/',    views.facture_compta_valider, name='compta-facture-valider'),
    path('compta/factures/<int:pk>/statut/',     views.facture_compta_status,  name='compta-facture-status'),
    path('compta/factures/<int:pk>/supprimer/',  views.facture_compta_delete,  name='compta-facture-delete'),
    path('compta/factures/<int:pk>/dupliquer/',  views.facture_compta_duplicate, name='compta-facture-duplicate'),
    path('compta/factures/<int:pk>/lignes/',             views.lignes_compta_get,  name='compta-lignes-get'),
    path('compta/factures/<int:pk>/lignes/sauvegarder/', views.lignes_compta_save, name='compta-lignes-save'),
    path('compta/clients/<int:client_pk>/contacts/',     views.client_contacts_get,   name='client-contacts-get'),
    path('compta/contacts/creation-rapide/',             views.contact_client_create, name='contact-client-create'),
    path('compta/contacts/<int:pk>/supprimer/',          views.contact_client_delete, name='contact-client-delete'),

    # PLANNING & ÉMARGEMENT (insertion) — réservé peut_acceder_planning
    path('planning/equipiers/',                  views.equipiers_list,        name='equipiers'),
    path('planning/equipiers/sauvegarder/',      views.equipier_save,         name='equipier-save'),
    path('planning/equipiers/<int:pk>/actif/',   views.equipier_toggle_actif, name='equipier-toggle-actif'),
    path('planning/',                            views.planning_mois,         name='planning'),
    path('planning/emargement/',                 views.emargement_view,       name='emargement'),
    path('planning/affectation/sauvegarder/',    views.affectation_save,      name='affectation-save'),
    path('planning/affectation/deplacer/',       views.affectation_move,      name='affectation-move'),
    path('planning/affectation/supprimer/',      views.affectation_delete,    name='affectation-delete'),
    path('planning/affectation/vendredi/',       views.vendredi_toggle,       name='vendredi-toggle'),
    path('planning/evenement/sauvegarder/',      views.evenement_save,         name='evenement-save'),
    path('planning/evenement/supprimer/',        views.evenement_delete,       name='evenement-delete'),
    path('planning/presence/sauvegarder/',       views.presence_save,         name='presence-save'),
    path('planning/pret/sauvegarder/',           views.pret_save,             name='pret-save'),
    path('planning/tranche/creer/',           views.tranche_creer,         name='tranche-creer'),
    path('insertion/aide/',                   views.aide_insertion_view,   name='aide-insertion'),
    path('insertion/tableau-de-bord/',        views.insertion_dashboard,   name='insertion-dashboard'),
    path('planning/feuilles/',                                    views.feuilles_liste,       name='feuilles-liste'),
    path('planning/feuilles/note/',                               views.fiche_note_save,      name='fiche-note-save'),
    path('planning/feuilles/presence/',                           views.fiche_presence_save,  name='fiche-presence-save'),
    path('planning/feuilles/<int:eq_pk>/<int:annee>/<int:mois>/', views.presence_feuille,     name='presence-feuille'),

    # Gestion utilisateurs
    path('utilisateurs/', views.utilisateurs_list, name='utilisateurs-list'),
    path('utilisateurs/nouveau/', views.utilisateur_create, name='utilisateur-create'),
    path('utilisateurs/<int:pk>/modifier/', views.utilisateur_edit, name='utilisateur-edit'),
    path('utilisateurs/<int:pk>/toggle/', views.utilisateur_toggle, name='utilisateur-toggle'),
    path('utilisateurs/nouveau/succes/', views.utilisateur_create_succes, name='utilisateur-create-succes'),
]
