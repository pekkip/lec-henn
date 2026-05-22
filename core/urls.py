from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Clients
    path('clients/', views.clients_list, name='clients'),
    path('clients/nouveau/', views.client_create, name='client-create'),
    path('clients/<int:pk>/supprimer/', views.client_delete, name='client-delete'),

    # Bibliothèque
    path('bibliotheque/', views.biblio_list, name='biblio'),
    path('bibliotheque/nouveau/', views.article_create, name='article-create'),
    path('bibliotheque/<int:pk>/supprimer/', views.article_delete, name='article-delete'),

    # Devis
    path('devis/', views.devis_list, name='devis-list'),
    path('devis/nouveau/', views.devis_create, name='devis-create'),
    path('devis/<int:pk>/', views.devis_detail, name='devis-detail'),
    path('devis/<int:pk>/statut/', views.devis_status, name='devis-status'),
    path('devis/<int:pk>/dupliquer/', views.devis_duplicate, name='devis-duplicate'),
    path('devis/<int:pk>/supprimer/', views.devis_delete, name='devis-delete'),
    path('devis/<int:pk>/pdf/', views.devis_pdf, name='devis-pdf'),

    # Lignes devis (API JSON)
    path('devis/<int:pk>/lignes/', views.lignes_get, name='lignes-get'),
    path('devis/<int:pk>/lignes/sauvegarder/', views.lignes_save, name='lignes-save'),

    # Factures
    path('factures/', views.factures_list, name='factures-list'),
    path('devis/<int:devis_pk>/factures/nouvelle/', views.facture_create, name='facture-create'),
    path('factures/<int:pk>/valider/', views.facture_valider, name='facture-valider'),
    path('factures/<int:pk>/statut/', views.facture_status, name='facture-status'),
    path('factures/<int:pk>/bypass/', views.facture_bypass, name='facture-bypass'),
    path('factures/<int:pk>/bypass/send/', views.facture_bypass_send_code, name='facture-bypass-send'),

    # Lignes facture (API JSON)
    path('factures/<int:pk>/lignes/', views.lignes_facture_get, name='lignes-facture-get'),
    path('factures/<int:pk>/lignes/sauvegarder/', views.lignes_facture_save, name='lignes-facture-save'),

    # En tête
    path('devis/<int:pk>/entete/sauvegarder/', views.devis_entete_save, name='devis-entete-save'),
]