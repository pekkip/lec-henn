import json
import base64
import tempfile
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.db import connection
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.messages import get_messages

from datetime import date
from decimal import Decimal

from datetime import timedelta

from .models import (
    Territoire, Service, Equipe, ProfilUtilisateur,
    Client, ContactClient, Devis, LigneDevis, Facture, LigneFacture,
    Equipier, TrancheDevis, Affectation, Presence, Pret,
    Evenement, FicheNote, ClotureMois, BibliothequeAides,
    Financeur,
)
from .permissions import peut_acceder_planning, est_encadrant
from .planning_utils import (
    _jours_feries, _build_grille,
    _count_working_days, _add_working_days, _build_evenement_sets,
)


class AccesDevisFactureTests(TestCase):
    """
    Régressions sur le contrôle d'accès objet (IDOR) introduit après l'audit.

    Scénario : deux techniciens dans des équipes différentes + un comptable.
    Le technicien B ne doit jamais accéder aux devis/factures du technicien A.
    """

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Bretagne')
        service = Service.objects.create(territoire=terr, nom='Habitat')
        cls.equipe_a = Equipe.objects.create(service=service, nom='Équipe A')
        cls.equipe_b = Equipe.objects.create(service=service, nom='Équipe B')

        # Technicien A — créateur du devis, équipe A
        cls.user_a = User.objects.create_user('alice', password='pw')
        pa = ProfilUtilisateur.objects.create(user=cls.user_a, role='technicien')
        pa.equipes.set([cls.equipe_a])

        # Technicien B — équipe B, aucun lien avec le devis A
        cls.user_b = User.objects.create_user('bob', password='pw')
        pb = ProfilUtilisateur.objects.create(user=cls.user_b, role='technicien')
        pb.equipes.set([cls.equipe_b])

        # Comptable — doit pouvoir consulter pour valider
        cls.user_c = User.objects.create_user('carol', password='pw')
        ProfilUtilisateur.objects.create(user=cls.user_c, role='comptable')

        client = Client.objects.create(nom='Client Test')
        cls.devis = Devis.objects.create(
            reference='DEV-2026-001', client=client, chantier='Chantier A',
            equipe=cls.equipe_a, created_by=cls.user_a,
        )
        cls.facture = Facture.objects.create(
            devis=cls.devis, type_doc='facture', destinataire='Client Test',
            status='validated', created_by=cls.user_a,
        )

    # ── Lecture devis (visible par tout utilisateur connecté) ────────

    def test_lignes_get_autorise_autre_equipe(self):
        # Règle métier : lecture partagée entre équipes.
        self.client.login(username='bob', password='pw')
        resp = self.client.get(reverse('core:lignes-get', args=[self.devis.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_lignes_get_autorise_createur(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:lignes-get', args=[self.devis.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_lignes_get_autorise_comptable(self):
        self.client.login(username='carol', password='pw')
        resp = self.client.get(reverse('core:lignes-get', args=[self.devis.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_lignes_get_refuse_anonyme(self):
        # Non connecté → @login_required redirige vers la connexion.
        resp = self.client.get(reverse('core:lignes-get', args=[self.devis.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_devis_detail_autorise_autre_equipe(self):
        self.client.login(username='bob', password='pw')
        resp = self.client.get(reverse('core:devis-detail', args=[self.devis.pk]))
        self.assertEqual(resp.status_code, 200)  # consultable par tous

    def test_devis_detail_lecture_seule_hors_equipe(self):
        # Hors équipe : éditeur verrouillé (CAN_EDIT=false), bandeau consultation,
        # et le bouton Sauvegarder des lignes n'est pas rendu.
        self.client.login(username='bob', password='pw')
        resp = self.client.get(reverse('core:devis-detail', args=[self.devis.pk]))
        html = resp.content.decode()
        self.assertIn('const CAN_EDIT = false', html)
        # Phrase propre au bandeau de consultation (évite de matcher un commentaire JS).
        self.assertIn("ne faites pas partie de l'équipe", html)
        # Le <button ... onclick="saveTree()"> est masqué (la fonction JS, elle,
        # reste définie — on cible donc le markup du bouton).
        self.assertNotIn('btn-prune" onclick="saveTree()"', html)

    def test_devis_detail_editable_pour_createur(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:devis-detail', args=[self.devis.pk]))
        html = resp.content.decode()
        self.assertIn('const CAN_EDIT = true', html)
        self.assertIn('btn-prune" onclick="saveTree()"', html)
        self.assertNotIn("ne faites pas partie de l'équipe", html)

    # ── Reste à facturer (arrondi) ───────────────────────────────────

    def test_reste_a_facturer_pas_de_centime_fantome(self):
        # total_brut() en pleine précision (100,005) vs montant facture arrondi
        # (100,01) → l'ancien calcul brut donnait -0,005 affiché -0,01. Le reste doit
        # désormais être exactement 0 (les deux côtés arrondis au centime d'abord).
        LigneDevis.objects.create(
            devis=self.devis, type_ligne='F', description='Lot arrondi',
            quantite=Decimal('1.5'), cout_unitaire=Decimal('66.67'), ordre=9,
        )
        self.assertEqual(self.devis.total_brut(), Decimal('100.005'))
        Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('100.01'), created_by=self.user_a,
        )
        self.assertEqual(self.devis.reste_a_facturer(), Decimal('0.00'),
                         "Reste fantôme ±0,01 € quand brut et facturé arrondis sont égaux")

    # ── Modification facture (statut) ────────────────────────────────

    def test_facture_status_refuse_autre_equipe(self):
        self.client.login(username='bob', password='pw')
        resp = self.client.post(
            reverse('core:facture-status', args=[self.facture.pk]),
            {'status': 'paid'},
        )
        self.assertEqual(resp.status_code, 302)
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.status, 'validated')  # inchangé

    def test_facture_status_refuse_autre_equipe_ajax(self):
        self.client.login(username='bob', password='pw')
        resp = self.client.post(
            reverse('core:facture-status', args=[self.facture.pk]),
            {'status': 'paid'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 403)
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.status, 'validated')

    def test_lignes_facture_save_refuse_autre_equipe(self):
        self.client.login(username='bob', password='pw')
        resp = self.client.post(
            reverse('core:lignes-facture-save', args=[self.facture.pk]),
            data=json.dumps({'lignes': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_lignes_facture_titre_a_zero_exclu_du_total(self):
        # TITRE à 0 = section exclue de la facture ; le montant sauvegardé doit l'ignorer.
        f = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='Client Test',
            status='draft', created_by=self.user_a,
        )
        self.client.login(username='alice', password='pw')
        payload = {'lignes': [
            {'type_ligne': 'TITRE', 'description': 'Lot exclut', 'quantite': '0',
             'quantite_originale': '1', 'unite': '', 'cout_unitaire': None, 'ouvert': True,
             'enfants': [
                 {'type_ligne': 'F', 'description': 'Peinture', 'quantite': '10',
                  'quantite_originale': '10', 'unite': 'm2', 'cout_unitaire': '50', 'enfants': []},
             ]},
        ]}
        resp = self.client.post(
            reverse('core:lignes-facture-save', args=[f.pk]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['montant'], 0.0)
        f.refresh_from_db()
        self.assertEqual(float(f.montant), 0.0)

    def test_apercu_titre_a_zero_affiche_grise(self):
        # Un TITRE avec quantite=0 apparaît dans l'aperçu avec class row-nf (grisé, sans montant).
        f = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='Client Test',
            status='validated', montant=Decimal('0'), created_by=self.user_a,
        )
        titre = LigneFacture.objects.create(
            facture=f, type_ligne='TITRE', description='Section exclue',
            quantite=Decimal('0'), ordre=0,
        )
        LigneFacture.objects.create(
            facture=f, parent=titre, type_ligne='F', description='Travaux',
            quantite=Decimal('5'), cout_unitaire=Decimal('100'), ordre=0,
        )
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:facture-apercu', args=[f.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Section exclue', content)
        self.assertIn('row-nf', content)

    def test_apercu_titre_quantite_partielle(self):
        # TITRE.qty=0.5 : aperçu doit afficher 0,5 (pas 1) et deja_facture enfant = 50%
        titre_ld = LigneDevis.objects.create(
            devis=self.devis, type_ligne='TITRE', description='Lot partiel',
            quantite=Decimal('1'), ordre=0,
        )
        enfant_ld = LigneDevis.objects.create(
            devis=self.devis, parent=titre_ld, type_ligne='F', description='Travaux',
            quantite=Decimal('10'), cout_unitaire=Decimal('100'), ordre=0,
        )
        f1 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('500'), created_by=self.user_a,
        )
        titre_lf = LigneFacture.objects.create(
            facture=f1, type_ligne='TITRE', description='Lot partiel',
            quantite=Decimal('0.5'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=titre_ld,
        )
        LigneFacture.objects.create(
            facture=f1, parent=titre_lf, type_ligne='F', description='Travaux',
            quantite=Decimal('10'), quantite_originale=Decimal('10'),
            cout_unitaire=Decimal('100'), ordre=0, ligne_devis_source=enfant_ld,
        )
        # Aperçu : quantité affichée = 0,5 (pas 1)
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:facture-apercu', args=[f1.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('0,5', content)
        self.assertNotIn('>1<', content)  # pas de "1" seul dans une cellule td-num
        # deja_facture de l'enfant pour une 2e facture = 500 (50% de 10*100), pas 1000
        from core.views import calc_deja_par_source_detail
        f2 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='draft',
            montant=Decimal('0'), created_by=self.user_a,
        )
        deja = calc_deja_par_source_detail(self.devis, f2)
        enfant_deja = deja.get(enfant_ld.pk, {}).get('montant', 0.0)
        self.assertAlmostEqual(enfant_deja, 500.0, places=2)

    def test_nouvelle_facture_titre_completement_facture_a_zero(self):
        # TITRE (qty=1) + F entièrement facturé (10/10) → TITRE=0 dans la nouvelle facture
        titre_ld = LigneDevis.objects.create(
            devis=self.devis, type_ligne='TITRE', description='Lot A',
            quantite=Decimal('1'), ordre=0,
        )
        f_ld = LigneDevis.objects.create(
            devis=self.devis, parent=titre_ld, type_ligne='F', description='Peinture',
            quantite=Decimal('10'), cout_unitaire=Decimal('50'), ordre=0,
        )
        f1 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('500'), created_by=self.user_a,
        )
        titre_lf = LigneFacture.objects.create(
            facture=f1, type_ligne='TITRE', description='Lot A',
            quantite=Decimal('1'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=titre_ld,
        )
        LigneFacture.objects.create(
            facture=f1, parent=titre_lf, type_ligne='F', description='Peinture',
            quantite=Decimal('10'), quantite_originale=Decimal('10'),
            cout_unitaire=Decimal('50'), ordre=0, ligne_devis_source=f_ld,
        )
        self.client.login(username='alice', password='pw')
        resp = self.client.post(
            reverse('core:facture-create', args=[self.devis.pk]),
            {'type_doc': 'facture', 'destinataire': 'C', 'echeance_jours': '30'},
        )
        self.assertEqual(resp.status_code, 302)
        f2 = Facture.objects.filter(type_doc='facture', status='draft').last()
        titre_f2 = f2.lignes.get(ligne_devis_source=titre_ld)
        self.assertEqual(float(titre_f2.quantite), 0.0,
                         "TITRE entièrement facturé → doit démarrer à 0")
        f_f2 = f2.lignes.get(ligne_devis_source=f_ld)
        self.assertEqual(float(f_f2.quantite), 0.0,
                         "F entièrement facturé (10/10) → reste 0")

    def test_nouvelle_facture_titre_partiellement_facture(self):
        # TITRE (qty=1) + F partiellement facturé (5/10) → TITRE reste 1, F=5
        titre_ld = LigneDevis.objects.create(
            devis=self.devis, type_ligne='TITRE', description='Lot D',
            quantite=Decimal('1'), ordre=3,
        )
        f_ld = LigneDevis.objects.create(
            devis=self.devis, parent=titre_ld, type_ligne='F', description='Pose carrelage',
            quantite=Decimal('10'), cout_unitaire=Decimal('50'), ordre=0,
        )
        f1 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('250'), created_by=self.user_a,
        )
        titre_lf = LigneFacture.objects.create(
            facture=f1, type_ligne='TITRE', description='Lot D',
            quantite=Decimal('1'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=titre_ld,
        )
        LigneFacture.objects.create(
            facture=f1, parent=titre_lf, type_ligne='F', description='Pose carrelage',
            quantite=Decimal('5'), quantite_originale=Decimal('10'),
            cout_unitaire=Decimal('50'), ordre=0, ligne_devis_source=f_ld,
        )
        self.client.login(username='alice', password='pw')
        self.client.post(
            reverse('core:facture-create', args=[self.devis.pk]),
            {'type_doc': 'facture', 'destinataire': 'C', 'echeance_jours': '30'},
        )
        f2 = Facture.objects.filter(type_doc='facture', status='draft').last()
        titre_f2 = f2.lignes.get(ligne_devis_source=titre_ld)
        self.assertEqual(float(titre_f2.quantite), 1.0,
                         "TITRE partiellement facturé → reste actif (qty=1)")
        f_f2 = f2.lignes.get(ligne_devis_source=f_ld)
        self.assertEqual(float(f_f2.quantite), 5.0,
                         "F partiellement facturé (5/10) → reste 5")

    def test_nouvelle_facture_titre_non_facture_garde_qty(self):
        # TITRE exclu (qty=0) dans la 1ère facture → doit rester à 1 dans la 2ème
        titre_ld = LigneDevis.objects.create(
            devis=self.devis, type_ligne='TITRE', description='Lot B',
            quantite=Decimal('1'), ordre=1,
        )
        f1 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('0'), created_by=self.user_a,
        )
        LigneFacture.objects.create(
            facture=f1, type_ligne='TITRE', description='Lot B',
            quantite=Decimal('0'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=titre_ld,
        )
        self.client.login(username='alice', password='pw')
        self.client.post(
            reverse('core:facture-create', args=[self.devis.pk]),
            {'type_doc': 'facture', 'destinataire': 'C', 'echeance_jours': '30'},
        )
        f2 = Facture.objects.filter(type_doc='facture', status='draft').last()
        titre_f2 = f2.lignes.get(ligne_devis_source=titre_ld)
        self.assertEqual(float(titre_f2.quantite), 1.0,
                         "TITRE non facturé (qty=0 dans f1) doit rester à 1 dans f2")

    def test_nouvelle_facture_composite_partielle_garde_recette(self):
        # TITRE → composite C (métrage partiellement facturé) → section S (recette).
        # La S, facturée une fois, ne doit PAS tomber à 0 dans la facture suivante :
        # elle fait partie de la recette unitaire de la composite, pas du métrage.
        # Régression : sinon C.total()=0 → TITRE replié → montant facture = 0.
        titre_ld = LigneDevis.objects.create(
            devis=self.devis, type_ligne='TITRE', description='Lot E',
            quantite=Decimal('1'), ordre=5,
        )
        c_ld = LigneDevis.objects.create(
            devis=self.devis, parent=titre_ld, type_ligne='C', description='Peinture',
            quantite=Decimal('10'), ordre=0,
        )
        s_ld = LigneDevis.objects.create(
            devis=self.devis, parent=c_ld, type_ligne='S', description='Finition',
            quantite=Decimal('1'), ordre=0,
        )
        LigneDevis.objects.create(
            devis=self.devis, parent=s_ld, type_ligne='MAT', description='Peinture mat',
            quantite=Decimal('1'), cout_unitaire=Decimal('20'), ordre=0,
        )
        # Facture 1 validée : composite facturée partiellement (5/10), recette intacte.
        f1 = Facture.objects.create(
            devis=self.devis, type_doc='facture', destinataire='C', status='validated',
            montant=Decimal('100'), created_by=self.user_a,
        )
        titre_lf = LigneFacture.objects.create(
            facture=f1, type_ligne='TITRE', description='Lot E',
            quantite=Decimal('1'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=titre_ld,
        )
        c_lf = LigneFacture.objects.create(
            facture=f1, parent=titre_lf, type_ligne='C', description='Peinture',
            quantite=Decimal('5'), quantite_originale=Decimal('10'), ordre=0,
            ligne_devis_source=c_ld,
        )
        s_lf = LigneFacture.objects.create(
            facture=f1, parent=c_lf, type_ligne='S', description='Finition',
            quantite=Decimal('1'), quantite_originale=Decimal('1'), ordre=0,
            ligne_devis_source=s_ld,
        )
        LigneFacture.objects.create(
            facture=f1, parent=s_lf, type_ligne='MAT', description='Peinture mat',
            quantite=Decimal('1'), quantite_originale=Decimal('1'),
            cout_unitaire=Decimal('20'), ordre=0,
        )
        self.client.login(username='alice', password='pw')
        self.client.post(
            reverse('core:facture-create', args=[self.devis.pk]),
            {'type_doc': 'facture', 'destinataire': 'C', 'echeance_jours': '30'},
        )
        f2 = Facture.objects.filter(type_doc='facture', status='draft').last()
        c_f2 = f2.lignes.get(ligne_devis_source=c_ld)
        self.assertEqual(float(c_f2.quantite), 5.0,
                         "Composite partiellement facturée (5/10) → reste 5")
        s_f2 = f2.lignes.get(ligne_devis_source=s_ld)
        self.assertEqual(float(s_f2.quantite), 1.0,
                         "Section sous la composite = recette → garde sa qty devis (pas 0)")
        titre_f2 = f2.lignes.get(ligne_devis_source=titre_ld)
        self.assertEqual(float(titre_f2.quantite), 1.0,
                         "TITRE pas replié tant que la composite a du restant")
        self.assertGreater(float(c_f2.total()), 0.0,
                           "Le total de la composite restante ne doit pas être 0")

    # ── Critiques ────────────────────────────────────────────────────

    def test_facture_create_exige_login(self):
        resp = self.client.post(
            reverse('core:facture-create', args=[self.devis.pk]),
            {'type_doc': 'facture'},
        )
        # @login_required → redirection vers la page de connexion
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_bypass_send_ne_renvoie_pas_le_code(self):
        # alice doit avoir un email pour que la vue tente l'envoi
        self.user_a.email = 'alice@example.com'
        self.user_a.save()
        self.client.login(username='alice', password='pw')
        resp = self.client.get(
            reverse('core:facture-bypass-send', args=[self.facture.pk])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertNotIn('code', data)

    def test_bypass_send_refuse_hors_equipe(self):
        # Bob (équipe B) ne peut pas demander un code pour la facture d'Alice.
        self.user_b.email = 'bob@example.com'
        self.user_b.save()
        self.client.login(username='bob', password='pw')
        resp = self.client.get(
            reverse('core:facture-bypass-send', args=[self.facture.pk])
        )
        self.assertEqual(resp.status_code, 403)

    def test_bypass_refuse_hors_equipe(self):
        # Bob ne peut pas valider via bypass même avec un code en session.
        self.client.login(username='bob', password='pw')
        session = self.client.session
        session[f'bypass_code_{self.facture.pk}'] = '123456'
        session.save()
        resp = self.client.post(
            reverse('core:facture-bypass', args=[self.facture.pk]),
            {'code': '123456'},
        )
        self.assertEqual(resp.status_code, 403)
        self.facture.refresh_from_db()
        self.assertFalse(self.facture.bypass_validation)


class SecurityFixesTests(TestCase):
    """Régressions sur les correctifs de sécurité/robustesse (session 17)."""

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Bretagne')
        service = Service.objects.create(territoire=terr, nom='Habitat')
        equipe = Equipe.objects.create(service=service, nom='Équipe A')
        cls.user = User.objects.create_user('testuser', password='pw',
                                            email='test@example.com')
        ProfilUtilisateur.objects.create(user=cls.user, role='technicien')

    def test_aides_api_save_montant_invalide_retourne_400(self):
        # Un montant non numérique ne doit plus lever une 500.
        self.client.login(username='testuser', password='pw')
        resp = self.client.post(
            reverse('core:aides-save'),
            data=json.dumps({'description': 'Test aide', 'montant_defaut': 'pas-un-nombre'}),
            content_type='application/json',
        )
        self.assertNotEqual(resp.status_code, 500)

    def test_reset_mdp_preserve_mot_de_passe_si_email_echoue(self):
        # Si l'envoi d'email échoue, le mot de passe ne doit pas être changé.
        user = User.objects.create_user(
            'resetuser', password='ancien_mdp',
            email='resetuser@compagnonsbatisseurs.eu',
        )
        with patch('core.views.send_mail', side_effect=Exception('SMTP down')):
            self.client.post(
                reverse('core:mot-de-passe-oublie'),
                {'email': 'resetuser@compagnonsbatisseurs.eu'},
            )
        user.refresh_from_db()
        self.assertTrue(user.check_password('ancien_mdp'))


class BibliothequeTests(TestCase):
    """Bibliothèque personnelle : round-trip JSON, y compris les groupes
    d'ouvrages (TITRE avec flag ``groupe`` — sous-arbre réinsérable en bloc)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('biblio_user', password='pw')
        ProfilUtilisateur.objects.create(user=cls.user, role='technicien')

    GROUPE = {
        'type_ligne': 'TITRE', 'groupe': True,
        'description': 'Remplacement tableau électrique',
        'quantite': 1, 'ouvert': True,
        'enfants': [
            {'type_ligne': 'S', 'description': 'Dépose ancien tableau',
             'quantite': 1, 'unite': 'u', 'cout_unitaire': None,
             'enfants': [
                 {'type_ligne': 'MO', 'description': "Main d'œuvre", 'quantite': 4,
                  'unite': 'h', 'cout_unitaire': 46, 'enfants': []},
                 {'type_ligne': 'MAT', 'description': 'Petites fournitures', 'quantite': 1,
                  'unite': 'u', 'cout_unitaire': 25, 'enfants': []},
             ]},
            {'type_ligne': 'FMAT', 'description': 'Tableau 13 modules', 'quantite': 1,
             'unite': 'forfait', 'cout_unitaire': 180, 'enfants': []},
        ],
    }

    def test_round_trip_groupe(self):
        # Le flag `groupe` et le sous-arbre complet survivent à save → get.
        self.client.login(username='biblio_user', password='pw')
        lignes = [
            {'type_ligne': 'TITRE', 'description': 'Électricité', 'quantite': 1,
             'enfants': [self.GROUPE]},   # groupe rangé dans une catégorie
            self.GROUPE,                  # groupe à la racine
        ]
        resp = self.client.post(
            reverse('core:biblio-save'),
            data=json.dumps({'lignes': lignes}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        data = self.client.get(reverse('core:biblio-get')).json()
        self.assertEqual(data['lignes'], lignes)
        self.assertTrue(data['lignes'][1]['groupe'])
        self.assertEqual(len(data['lignes'][1]['enfants']), 2)

    def test_biblio_api_exige_connexion(self):
        resp = self.client.get(reverse('core:biblio-get'))
        self.assertNotEqual(resp.status_code, 200)  # redirection login


class ClientsTests(TestCase):
    """Recherche, création rapide, filtres de portée et édition des clients."""

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Bretagne')
        service = Service.objects.create(territoire=terr, nom='Habitat')
        cls.equipe = Equipe.objects.create(service=service, nom='Équipe A')

        # Alice et Bob partagent la même équipe ; Carol est dans une autre.
        cls.alice = User.objects.create_user('alice', password='pw')
        pa = ProfilUtilisateur.objects.create(user=cls.alice, role='technicien')
        pa.equipes.set([cls.equipe])

        cls.bob = User.objects.create_user('bob', password='pw')
        pb = ProfilUtilisateur.objects.create(user=cls.bob, role='technicien')
        pb.equipes.set([cls.equipe])

        equipe_autre = Equipe.objects.create(service=service, nom='Équipe B')
        cls.carol = User.objects.create_user('carol', password='pw')
        pc = ProfilUtilisateur.objects.create(user=cls.carol, role='technicien')
        pc.equipes.set([equipe_autre])

        cls.admin = User.objects.create_user('admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')

        # Clients : un par utilisateur, avec ville/CP pour les filtres.
        cls.cli_alice = Client.objects.create(
            nom='Mairie de Quimper', code_postal='29000', ville='Quimper',
            created_by=cls.alice,
        )
        cls.cli_bob = Client.objects.create(
            nom='Brest Métropole', code_postal='29200', ville='Brest',
            created_by=cls.bob,
        )
        cls.cli_carol = Client.objects.create(
            nom='Ville de Rennes', code_postal='35000', ville='Rennes',
            created_by=cls.carol,
        )

    # ── Recherche (autocomplétion / panneau) ─────────────────────────

    def test_client_search_correspondances(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:client-search'), {'q': 'quimper'})
        self.assertEqual(resp.status_code, 200)
        noms = [r['nom'] for r in resp.json()['results']]
        self.assertEqual(noms, ['Mairie de Quimper'])

    def test_client_search_refuse_anonyme(self):
        resp = self.client.get(reverse('core:client-search'), {'q': 'a'})
        self.assertEqual(resp.status_code, 302)

    # ── Création rapide ──────────────────────────────────────────────

    def test_client_quick_create_ok(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.post(reverse('core:client-quick-create'), {
            'nom': 'Nouveau Client', 'code_postal': '29100', 'ville': 'Douarnenez',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['nom'], 'Nouveau Client')
        cli = Client.objects.get(pk=data['id'])
        self.assertEqual(cli.created_by, self.alice)
        self.assertEqual(cli.ville, 'Douarnenez')

    def test_client_quick_create_nom_vide(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.post(reverse('core:client-quick-create'), {'nom': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    # ── Filtres de portée et géographiques ───────────────────────────

    def test_clients_list_portee_moi(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:clients'), {'portee': 'moi'})
        clients = list(resp.context['clients'])
        self.assertEqual(clients, [self.cli_alice])

    def test_clients_list_portee_equipe(self):
        # Alice voit ses clients ET ceux de Bob (même équipe), pas ceux de Carol.
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:clients'), {'portee': 'equipe'})
        clients = set(resp.context['clients'])
        self.assertEqual(clients, {self.cli_alice, self.cli_bob})

    def test_clients_list_filtre_departement(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.get(reverse('core:clients'), {'departement': '29'})
        clients = set(resp.context['clients'])
        self.assertEqual(clients, {self.cli_alice, self.cli_bob})

    # ── Édition (tout utilisateur connecté) ─────────────────────────

    def test_client_edit_admin_ok(self):
        self.client.login(username='admin', password='pw')
        resp = self.client.post(
            reverse('core:client-edit', args=[self.cli_alice.pk]),
            {'nom': 'Mairie de Quimper', 'ville': 'Quimper Centre', 'code_postal': '29000'},
        )
        self.assertEqual(resp.status_code, 302)
        self.cli_alice.refresh_from_db()
        self.assertEqual(self.cli_alice.ville, 'Quimper Centre')

    def test_client_edit_non_admin_ok(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.post(
            reverse('core:client-edit', args=[self.cli_alice.pk]),
            {'nom': 'Mairie de Landerneau', 'ville': 'Landerneau'},
        )
        self.assertEqual(resp.status_code, 302)
        self.cli_alice.refresh_from_db()
        self.assertEqual(self.cli_alice.nom, 'Mairie de Landerneau')


class FactureComptaTests(TestCase):
    """
    Outils compta : factures structure / appels de convention / avoirs.
    Création directe sans devis, réservée aux rôles compta.
    """

    @classmethod
    def setUpTestData(cls):
        cls.year = date.today().year
        cls.admin = User.objects.create_user('admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.compta = User.objects.create_user('compta', password='pw')
        ProfilUtilisateur.objects.create(user=cls.compta, role='comptable')
        cls.tech = User.objects.create_user('tech', password='pw')
        ProfilUtilisateur.objects.create(user=cls.tech, role='technicien')
        cls.client_compta = Client.objects.create(
            nom='Mairie de Brest', type_client='collectivite',
        )

    # ── Accès ────────────────────────────────────────────────

    def test_acces_compta_refuse_technicien(self):
        self.client.login(username='tech', password='pw')
        resp = self.client.get(reverse('core:compta-structures-list'))
        self.assertEqual(resp.status_code, 302)  # redirigé vers dashboard

    def test_acces_compta_autorise_comptable(self):
        self.client.login(username='compta', password='pw')
        resp = self.client.get(reverse('core:compta-structures-list'))
        self.assertEqual(resp.status_code, 200)

    # ── Création ─────────────────────────────────────────────

    def test_creation_structure_par_comptable(self):
        self.client.login(username='compta', password='pw')
        resp = self.client.post(
            reverse('core:compta-structure-create'),
            {'client': self.client_compta.pk, 'notes': 'Travaux école', 'echeance_jours': '30'},
        )
        self.assertEqual(resp.status_code, 302)
        f = Facture.objects.get(type_doc='structure')
        self.assertIsNone(f.devis)
        self.assertEqual(f.client, self.client_compta)
        self.assertEqual(f.destinataire, 'Mairie de Brest')

    def test_creation_refuse_technicien(self):
        self.client.login(username='tech', password='pw')
        resp = self.client.post(
            reverse('core:compta-structure-create'),
            {'client': self.client_compta.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Facture.objects.filter(type_doc='structure').exists())

    # ── Numérotation ─────────────────────────────────────────

    def _struct(self, status='draft'):
        return Facture.objects.create(
            type_doc='structure', devis=None, client=self.client_compta,
            destinataire='Mairie de Brest', created_by=self.compta, status=status,
        )

    def test_structure_partage_sequence_fac(self):
        # Facture chantier, acompte et structure partagent le compteur FA
        # (préfixes d'affichage distincts), à partir du plancher 7054.
        devis = Devis.objects.create(
            reference=f'DEV-{self.year}-001',
            client=self.client_compta, chantier='Chantier', created_by=self.admin,
        )
        fac_devis = Facture.objects.create(
            devis=devis, type_doc='facture', destinataire='X',
            status='draft', created_by=self.admin,
        )
        self.client.login(username='compta', password='pw')
        self.client.post(reverse('core:facture-valider', args=[fac_devis.pk]))
        fac_devis.refresh_from_db()
        self.assertEqual(fac_devis.numero, 'FA07054')

        struct = self._struct()
        self.client.post(reverse('core:compta-facture-valider', args=[struct.pk]))
        struct.refresh_from_db()
        self.assertEqual(struct.numero, 'FACTURE-ST07055')

    def test_appel_prefixe_app(self):
        appel = Facture.objects.create(
            type_doc='appel', devis=None, client=self.client_compta,
            destinataire='Mairie', created_by=self.compta, status='draft',
        )
        self.client.login(username='admin', password='pw')
        self.client.post(reverse('core:compta-facture-valider', args=[appel.pk]))
        appel.refresh_from_db()
        self.assertEqual(appel.numero, f'APP-{self.year}-001')

    def test_acompte_partage_sequence_fa(self):
        # L'acompte partage le compteur FA (préfixe d'affichage AC).
        devis = Devis.objects.create(
            reference=f'DEV-{self.year}-AC2', client=self.client_compta,
            chantier='C', created_by=self.admin,
        )
        fac = Facture.objects.create(
            devis=devis, type_doc='facture', destinataire='X',
            status='draft', created_by=self.admin,
        )
        acompte = Facture.objects.create(
            devis=devis, type_doc='acompte', destinataire='X',
            status='draft', montant=Decimal('100'), created_by=self.admin,
        )
        self.client.login(username='compta', password='pw')
        self.client.post(reverse('core:facture-valider', args=[fac.pk]))
        self.client.post(reverse('core:facture-valider', args=[acompte.pk]))
        fac.refresh_from_db()
        acompte.refresh_from_db()
        self.assertEqual(fac.numero, 'FA07054')
        self.assertEqual(acompte.numero, 'AC07055')

    def test_devis_numero_nouveau_format(self):
        from core.views import gen_numero_devis
        # Premier numéro attribué = plancher DE07022.
        self.assertEqual(gen_numero_devis(), 'DE07022')
        Devis.objects.create(reference='DE07022', client=self.client_compta,
                             chantier='C', created_by=self.admin)
        self.assertEqual(gen_numero_devis(), 'DE07023')
        # Un devis importé (réf EBP sous le plancher) n'avance pas le compteur.
        Devis.objects.create(reference='DE04124', client=self.client_compta,
                             chantier='C', created_by=self.admin)
        self.assertEqual(gen_numero_devis(), 'DE07023')

    def test_proforma_reference_client_pf(self):
        f = self._struct()
        self.assertEqual(f.get_reference_client(), f'PF-{f.pk}')
        self.assertTrue(f.get_reference().startswith('BROUILLON-'))

    # ── Validation ───────────────────────────────────────────

    def test_validation_par_admin_ou_comptable(self):
        for username in ('admin', 'compta'):
            f = self._struct()
            self.client.login(username=username, password='pw')
            resp = self.client.post(reverse('core:compta-facture-valider', args=[f.pk]))
            self.assertEqual(resp.status_code, 302)
            f.refresh_from_db()
            self.assertEqual(f.status, 'validated')
            self.assertIsNotNone(f.numero)

    # ── Lignes ───────────────────────────────────────────────

    def test_lignes_compta_save_recalcule_montant(self):
        f = self._struct()
        self.client.login(username='compta', password='pw')
        payload = {
            'notes': 'Objet',
            'lignes': [
                {'type_ligne': 'TITRE', 'description': 'Lot 1', 'enfants': [
                    {'type_ligne': 'F', 'description': 'Peinture', 'quantite': 20, 'unite': 'm2', 'cout_unitaire': 10},
                ]},
                {'type_ligne': 'F', 'description': 'Forfait', 'quantite': 1, 'cout_unitaire': 50},
            ],
        }
        resp = self.client.post(
            reverse('core:compta-lignes-save', args=[f.pk]),
            data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        f.refresh_from_db()
        self.assertEqual(float(f.montant), 250.0)  # 20*10 + 50

    # ── Avoirs ───────────────────────────────────────────────

    def _struct_validee_avec_lignes(self):
        f = self._struct(status='validated')
        f.numero = f'FAC-{self.year}-001'
        titre = LigneFacture.objects.create(facture=f, type_ligne='TITRE', description='Lot 1', ordre=0)
        LigneFacture.objects.create(
            facture=f, parent=titre, type_ligne='F', description='Peinture',
            quantite=20, unite='m2', cout_unitaire=10, ordre=0,
        )
        f.montant = sum(l.total() for l in f.lignes.filter(parent=None))
        f.save()
        return f

    def test_avoir_copie_quantites_negatives(self):
        source = self._struct_validee_avec_lignes()
        self.client.login(username='compta', password='pw')
        resp = self.client.post(reverse('core:avoir-create', args=[source.pk]))
        self.assertEqual(resp.status_code, 302)
        avoir = Facture.objects.get(type_doc='avoir')
        self.assertEqual(avoir.facture_origine, source)
        enfant = avoir.lignes.get(type_ligne='F')
        self.assertEqual(float(enfant.quantite), -20.0)
        self.assertEqual(float(avoir.montant), -200.0)

    def test_avoir_refuse_sur_brouillon(self):
        source = self._struct(status='draft')
        self.client.login(username='compta', password='pw')
        resp = self.client.post(reverse('core:avoir-create', args=[source.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Facture.objects.filter(type_doc='avoir').exists())

    def test_avoir_numero_av(self):
        avoir = Facture.objects.create(
            type_doc='avoir', devis=None, client=self.client_compta,
            destinataire='Mairie', created_by=self.compta, status='draft',
        )
        self.client.login(username='admin', password='pw')
        self.client.post(reverse('core:compta-facture-valider', args=[avoir.pk]))
        avoir.refresh_from_db()
        # Nouveau format : AV##### (compteur propre, plancher 1).
        self.assertEqual(avoir.numero, 'AV00001')

    def test_total_facture_avec_avoir(self):
        devis = Devis.objects.create(
            reference=f'DEV-{self.year}-009',
            client=self.client_compta, chantier='Chantier', created_by=self.admin,
        )
        Facture.objects.create(
            devis=devis, type_doc='facture', destinataire='X',
            status='validated', montant=100, created_by=self.admin,
        )
        Facture.objects.create(
            devis=devis, type_doc='avoir', destinataire='X',
            status='validated', montant=-30, created_by=self.admin,
        )
        self.assertEqual(float(devis.total_facture()), 70.0)

    def test_total_facture_acompte_non_double_compte(self):
        # Régression DE04026 : un acompte est une avance déduite du solde de la
        # facture (qui porte le montant PLEIN du devis), pas une facturation en
        # plus. Avant le fix : brut 2670 + acompte 400 + facture 2670 → « Facturé »
        # 3070, reste -400.
        from core.models import LigneDevis
        devis = Devis.objects.create(
            reference=f'DEV-{self.year}-ACO',
            client=self.client_compta, chantier='Chantier', created_by=self.admin,
        )
        LigneDevis.objects.create(
            devis=devis, type_ligne='F', description='Travaux',
            quantite=1, cout_unitaire=Decimal('2670'),
        )
        Facture.objects.create(
            devis=devis, type_doc='acompte', destinataire='X',
            status='paid', montant=Decimal('400'), created_by=self.admin,
        )
        Facture.objects.create(
            devis=devis, type_doc='facture', destinataire='X',
            status='validated', montant=Decimal('2670'), created_by=self.admin,
        )
        self.assertEqual(devis.total_facture(), Decimal('2670'))
        self.assertEqual(devis.reste_a_facturer(), Decimal('0.00'))

    def test_validation_solde_bloquee_si_acompte_non_paye(self):
        # La facture de solde ne déduit l'acompte que s'il est 'paid'. La valider
        # alors qu'un acompte émis (envoyé) n'est pas encore payé facturerait le
        # client deux fois → la validation doit être bloquée jusqu'au versement.
        devis = Devis.objects.create(
            reference=f'DEV-{self.year}-BLK',
            client=self.client_compta, chantier='Chantier', created_by=self.admin,
        )
        acompte = Facture.objects.create(
            devis=devis, type_doc='acompte', destinataire='X',
            status='sent', montant=Decimal('400'), created_by=self.admin,
        )
        solde = Facture.objects.create(
            devis=devis, type_doc='facture', destinataire='X',
            status='draft', montant=Decimal('2670'), created_by=self.admin,
        )
        self.client.login(username='compta', password='pw')
        self.client.post(reverse('core:facture-valider', args=[solde.pk]))
        solde.refresh_from_db()
        self.assertEqual(solde.status, 'draft', "Validation non bloquée malgré l'acompte impayé")

        # Acompte marqué payé → la validation passe.
        acompte.status = 'paid'
        acompte.save(update_fields=['status'])
        self.client.post(reverse('core:facture-valider', args=[solde.pk]))
        solde.refresh_from_db()
        self.assertEqual(solde.status, 'validated')

    # ── Typologie client ─────────────────────────────────────

    def test_filtre_type_client(self):
        Client.objects.create(nom='M. Dupont', type_client='particulier')
        self.client.login(username='admin', password='pw')
        resp = self.client.get(reverse('core:clients'), {'type_client': 'collectivite'})
        self.assertEqual(resp.status_code, 200)
        noms = [c.nom for c in resp.context['clients']]
        self.assertIn('Mairie de Brest', noms)
        self.assertNotIn('M. Dupont', noms)


class DashboardTests(TestCase):
    """Tableau de bord personnalisable : rendu, gating compta, config, portée."""

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Bretagne')
        service = Service.objects.create(territoire=terr, nom='Habitat')
        cls.equipe = Equipe.objects.create(service=service, nom='Équipe A')

        cls.tech = User.objects.create_user('tech', password='pw')
        pt = ProfilUtilisateur.objects.create(user=cls.tech, role='technicien')
        pt.equipes.set([cls.equipe])
        cls.compta = User.objects.create_user('compta', password='pw')
        ProfilUtilisateur.objects.create(user=cls.compta, role='comptable')
        cls.admin = User.objects.create_user('admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.autre = User.objects.create_user('autre', password='pw')
        ProfilUtilisateur.objects.create(user=cls.autre, role='technicien')

        client = Client.objects.create(nom='Client Test')
        # Devis de chantier (tech) + facture chantier
        cls.devis = Devis.objects.create(
            reference='DEV-2026-001', client=client, chantier='Chantier A',
            equipe=cls.equipe, created_by=cls.tech, status='accepted',
        )
        cls.facture_chantier = Facture.objects.create(
            devis=cls.devis, type_doc='facture', destinataire='Client Test',
            status='validated', montant=500, created_by=cls.tech,
        )
        # Facture compta (sans devis) + avoir — créées par le comptable
        cls.facture_compta = Facture.objects.create(
            type_doc='structure', destinataire='Mairie', client=client,
            status='validated', montant=800, created_by=cls.compta,
        )
        cls.avoir = Facture.objects.create(
            devis=cls.devis, type_doc='avoir', destinataire='Client Test',
            status='validated', montant=-100, created_by=cls.compta,
        )
        # Devis d'un autre utilisateur (pour la portée)
        cls.devis_autre = Devis.objects.create(
            reference='DEV-2026-002', client=client, chantier='Chantier B',
            created_by=cls.autre, status='draft',
        )

    def test_dashboard_rend_pour_chaque_role(self):
        for username in ('tech', 'compta', 'admin'):
            self.client.login(username=username, password='pw')
            resp = self.client.get(reverse('core:dashboard'))
            self.assertEqual(resp.status_code, 200, username)
            self.assertIn('widgets', resp.context)

    def test_factures_recentes_exclut_compta(self):
        from .dashboard_widgets import widget_data
        data = widget_data('list_factures_recentes', self.admin, 'all')
        factures = data['factures']
        self.assertIn(self.facture_chantier, factures)
        self.assertNotIn(self.facture_compta, factures)  # devis=None
        self.assertNotIn(self.avoir, factures)            # type_doc=avoir

    def test_widgets_compta_caches_hors_compta(self):
        from .dashboard_widgets import resolve_dashboard
        # Technicien : le widget avoirs (requires_compta) est absent partout.
        profil_tech = self.tech.profil
        visibles, dispos = resolve_dashboard(profil_tech, self.tech)
        ids = {w['id'] for w in visibles} | {w['id'] for w in dispos}
        self.assertNotIn('list_avoirs_recents', ids)
        # Comptable : le widget est proposé (au moins dans les disponibles).
        profil_compta = self.compta.profil
        visibles_c, dispos_c = resolve_dashboard(profil_compta, self.compta)
        ids_c = {w['id'] for w in visibles_c} | {w['id'] for w in dispos_c}
        self.assertIn('list_avoirs_recents', ids_c)

    def test_save_persiste_config(self):
        self.client.login(username='tech', password='pw')
        payload = {'widgets': [
            {'id': 'kpi_ca', 'hidden': False, 'scope': 'mine'},
            {'id': 'list_devis_recents', 'hidden': True, 'scope': 'all'},
        ]}
        resp = self.client.post(
            reverse('core:dashboard-save'),
            data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.tech.profil.refresh_from_db()
        widgets = self.tech.profil.dashboard_config['widgets']
        self.assertEqual(widgets[0], {'id': 'kpi_ca', 'hidden': False, 'scope': 'mine'})
        self.assertEqual(widgets[1]['id'], 'list_devis_recents')
        self.assertTrue(widgets[1]['hidden'])

    def test_save_ignore_widget_inconnu(self):
        self.client.login(username='tech', password='pw')
        payload = {'widgets': [
            {'id': 'kpi_ca', 'hidden': False, 'scope': 'all'},
            {'id': 'widget_bidon', 'hidden': False, 'scope': 'all'},
        ]}
        resp = self.client.post(
            reverse('core:dashboard-save'),
            data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.tech.profil.refresh_from_db()
        ids = [w['id'] for w in self.tech.profil.dashboard_config['widgets']]
        self.assertEqual(ids, ['kpi_ca'])

    def test_save_ignore_widget_compta_hors_droit(self):
        # Un technicien ne peut pas injecter un widget compta via le POST.
        self.client.login(username='tech', password='pw')
        payload = {'widgets': [
            {'id': 'list_avoirs_recents', 'hidden': False, 'scope': 'all'},
        ]}
        self.client.post(
            reverse('core:dashboard-save'),
            data=json.dumps(payload), content_type='application/json')
        self.tech.profil.refresh_from_db()
        ids = [w['id'] for w in self.tech.profil.dashboard_config['widgets']]
        self.assertNotIn('list_avoirs_recents', ids)

    def test_widget_scope_mine(self):
        from .dashboard_widgets import widget_data
        data = widget_data('list_devis_recents', self.tech, 'mine')
        refs = {d.reference for d in data['devis']}
        self.assertIn('DEV-2026-001', refs)      # créé par tech
        self.assertNotIn('DEV-2026-002', refs)   # créé par un autre

    def test_dashboard_rend_tous_les_widgets(self):
        # Affiche tous les widgets (admin) → vérifie chaque branche du template.
        from .dashboard_widgets import WIDGETS
        self.admin.profil.dashboard_config = {'widgets': [
            {'id': wid, 'hidden': False, 'scope': 'all'} for wid in WIDGETS
        ]}
        self.admin.profil.save()
        self.client.login(username='admin', password='pw')
        resp = self.client.get(reverse('core:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['widgets']), len(WIDGETS))


class ListesPerfTests(TestCase):
    """
    Optimisation des listes (session 23) : pagination + calcul des totaux
    sans explosion N+1.

    L'ancienne `devis_list` parcourait l'arbre des lignes de chaque devis en
    frappant la base à chaque nœud (`enfants.all()`/`exists()`), et le total
    brut était même recalculé une 2ᵉ fois dans le template. Ces tests
    verrouillent (a) l'équivalence des totaux avec les méthodes du modèle,
    (b) la pagination, (c) le caractère borné du nombre de requêtes.
    """

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Bretagne')
        service = Service.objects.create(territoire=terr, nom='Habitat')
        cls.equipe = Equipe.objects.create(service=service, nom='Équipe')
        cls.admin = User.objects.create_user('admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.client_obj = Client.objects.create(nom='Client')

    def _devis_avec_arbre(self, ref):
        """Devis avec un arbre de lignes : brut attendu = 350 €."""
        d = Devis.objects.create(
            reference=ref, client=self.client_obj, chantier='C',
            equipe=self.equipe, created_by=self.admin,
        )
        titre = LigneDevis.objects.create(
            devis=d, type_ligne='TITRE', description='Lot 1', ordre=0)
        # Composite : quantité 2 × (1 × 100) = 200
        comp = LigneDevis.objects.create(
            devis=d, parent=titre, type_ligne='C', quantite=2, ordre=0)
        LigneDevis.objects.create(
            devis=d, parent=comp, type_ligne='MAT', quantite=1,
            cout_unitaire=Decimal('100'), ordre=0)
        # Ligne simple : 3 × 50 = 150
        LigneDevis.objects.create(
            devis=d, parent=titre, type_ligne='S', quantite=3,
            cout_unitaire=Decimal('50'), ordre=1)
        # FIN : exclue du brut
        LigneDevis.objects.create(
            devis=d, type_ligne='FIN', quantite=1,
            cout_unitaire=Decimal('-80'), ordre=1)
        return d

    def test_totaux_identiques_aux_methodes_modele(self):
        from .views import attacher_totaux_devis
        d = self._devis_avec_arbre('DEV-2026-100')
        Facture.objects.create(
            devis=d, type_doc='facture', destinataire='x',
            status='validated', montant=Decimal('100'), created_by=self.admin)

        qs = list(Devis.objects.filter(pk=d.pk).prefetch_related('lignes', 'factures'))
        attacher_totaux_devis(qs)

        # Équivalence stricte avec les méthodes du modèle (non régression).
        self.assertEqual(qs[0].brut, d.total_brut())
        self.assertEqual(qs[0].rtf, d.reste_a_facturer())
        # Valeurs attendues explicites.
        self.assertEqual(qs[0].brut, Decimal('350'))
        self.assertEqual(qs[0].rtf, Decimal('250'))

    def test_pagination_devis(self):
        for i in range(55):
            Devis.objects.create(
                reference=f'DEV-2026-2{i:02d}', client=self.client_obj,
                chantier='C', equipe=self.equipe, created_by=self.admin)
        self.client.login(username='admin', password='pw')

        r1 = self.client.get(reverse('core:devis-list'))
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(len(r1.context['devis']), 50)
        self.assertEqual(r1.context['page_obj'].paginator.count, 55)

        r2 = self.client.get(reverse('core:devis-list') + '?page=2')
        self.assertEqual(len(r2.context['devis']), 5)

    def test_pagination_conserve_les_filtres(self):
        # base_qs doit transporter les filtres actifs (hors `page`).
        self.client.login(username='admin', password='pw')
        resp = self.client.get(reverse('core:devis-list') + '?status=draft&page=1')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('page=', resp.context['base_qs'])
        self.assertIn('status=draft', resp.context['base_qs'])

    def test_devis_list_requetes_bornees(self):
        # 10 devis × ~5 lignes : avec l'ancien N+1, des centaines de requêtes.
        # Le correctif (prefetch + calcul mémoire) borne le total.
        for i in range(10):
            self._devis_avec_arbre(f'DEV-2026-3{i:02d}')
        self.client.login(username='admin', password='pw')
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('core:devis-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertLess(len(ctx.captured_queries), 30)

        # Le chemin filtre `q` (recherche) doit rester borné lui aussi.
        with CaptureQueriesContext(connection) as ctx2:
            resp2 = self.client.get(reverse('core:devis-list') + '?q=C')
        self.assertEqual(resp2.status_code, 200)
        self.assertLess(len(ctx2.captured_queries), 30)

    def _seed_dashboard_devis(self, debut, fin, aide):
        for i in range(debut, fin):
            d = self._devis_avec_arbre(f'DEV-2026-4{i:03d}')
            d.status = 'accepted'
            d.save(update_fields=['status'])
            # Ligne de financement liée à une aide (exerce chart_financements).
            LigneDevis.objects.create(
                devis=d, type_ligne='FIN', quantite=1,
                cout_unitaire=Decimal('-200'), aide=aide, ordre=2)

    def _compter_requetes_dashboard(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('core:dashboard'))
        self.assertEqual(resp.status_code, 200)
        return len(ctx.captured_queries)

    def test_dashboard_pas_de_n_plus_un(self):
        # Même cause racine que les listes : plusieurs widgets sommaient
        # `total_brut()`/`reste_a_facturer()` sur TOUS les devis acceptés.
        # Preuve d'absence de N+1 : le nombre de requêtes ne doit PAS croître
        # avec le nombre de devis (prefetch → clauses IN, coût constant).
        from .dashboard_widgets import WIDGETS
        from .models import BibliothequeAides

        aide = BibliothequeAides.objects.create(
            description='ANAH', organisme='ANAH', created_by=self.admin)
        # Affiche TOUS les widgets (cas le plus lourd).
        self.admin.profil.dashboard_config = {'widgets': [
            {'id': wid, 'hidden': False, 'scope': 'all'} for wid in WIDGETS
        ]}
        self.admin.profil.save()
        self.client.login(username='admin', password='pw')

        self._seed_dashboard_devis(0, 4, aide)
        requetes_4 = self._compter_requetes_dashboard()

        self._seed_dashboard_devis(4, 20, aide)   # 5× plus de devis
        requetes_20 = self._compter_requetes_dashboard()

        # Avec l'ancien N+1, requetes_20 aurait explosé (× nombre de devis).
        # Ici l'écart doit rester nul (ou marginal).
        self.assertLessEqual(requetes_20, requetes_4 + 2)


class PlanningEquipiersTests(TestCase):
    """
    Module Planning (commit 2) : accès au module + CRUD des équipiers.
    """

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Ille-et-Vilaine')
        service = Service.objects.create(territoire=terr, nom='Insertion', module_planning=True)
        cls.equipe_a = Equipe.objects.create(service=service, nom='SORM')
        cls.equipe_b = Equipe.objects.create(service=service, nom='GORM')

        # Encadrant de l'équipe A (accès planning via l'équipe encadrée)
        cls.encadrant = User.objects.create_user('laurene', password='pw')
        ProfilUtilisateur.objects.create(user=cls.encadrant, role='technicien')
        cls.equipe_a.encadrant = cls.encadrant
        cls.equipe_a.save()

        # Technicien lambda — aucun accès au module
        cls.technicien = User.objects.create_user('tech', password='pw')
        ProfilUtilisateur.objects.create(user=cls.technicien, role='technicien')

        # Admin, responsable (assistante), RH — accès transverse
        cls.admin = User.objects.create_user('david', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.responsable = User.objects.create_user('assistante', password='pw')
        ProfilUtilisateur.objects.create(user=cls.responsable, role='responsable')
        cls.rh = User.objects.create_user('rh', password='pw')
        ProfilUtilisateur.objects.create(user=cls.rh, role='rh')

    # ── Permissions ──────────────────────────────────────────

    def test_peut_acceder_planning_par_role(self):
        self.assertTrue(peut_acceder_planning(self.admin))
        self.assertTrue(peut_acceder_planning(self.responsable))
        self.assertTrue(peut_acceder_planning(self.rh))
        self.assertTrue(peut_acceder_planning(self.encadrant))   # encadrant d'une équipe
        self.assertFalse(peut_acceder_planning(self.technicien))  # aucun rôle ni équipe

    def test_est_encadrant(self):
        self.assertTrue(est_encadrant(self.encadrant, self.equipe_a))
        self.assertFalse(est_encadrant(self.encadrant, self.equipe_b))  # pas son équipe
        self.assertTrue(est_encadrant(self.admin, self.equipe_b))       # admin partout
        self.assertTrue(est_encadrant(self.responsable, self.equipe_a)) # assistante partout
        self.assertFalse(est_encadrant(self.technicien, self.equipe_a))

    # ── Accès à la page ──────────────────────────────────────

    def test_liste_refusee_sans_acces(self):
        self.client.login(username='tech', password='pw')
        resp = self.client.get(reverse('core:equipiers'))
        self.assertEqual(resp.status_code, 403)

    def test_liste_ok_pour_encadrant(self):
        self.client.login(username='laurene', password='pw')
        resp = self.client.get(reverse('core:equipiers'))
        self.assertEqual(resp.status_code, 200)

    # ── CRUD ─────────────────────────────────────────────────

    def test_creation_equipier(self):
        self.client.login(username='laurene', password='pw')
        resp = self.client.post(reverse('core:equipier-save'), {
            'prenom': 'Habtom', 'nom': 'Tekie',
            'equipe': self.equipe_a.pk,
            'heures_contrat_hebdo': '26',
        })
        self.assertEqual(resp.status_code, 302)
        eq = Equipier.objects.get(nom='Tekie')
        self.assertEqual(eq.prenom, 'Habtom')
        self.assertEqual(eq.equipe, self.equipe_a)
        self.assertEqual(eq.type_contrat, 'CDDI - 26 heures')  # défaut appliqué
        self.assertTrue(eq.actif)

    def test_edition_equipier(self):
        eq = Equipier.objects.create(prenom='Habtom', nom='Tekie', equipe=self.equipe_a)
        self.client.login(username='david', password='pw')
        self.client.post(reverse('core:equipier-save'), {
            'pk': eq.pk, 'prenom': 'Habtom', 'nom': 'Tekie',
            'equipe': self.equipe_b.pk, 'matricule': 'M-042',
            'heures_contrat_hebdo': '28',
        })
        eq.refresh_from_db()
        self.assertEqual(eq.equipe, self.equipe_b)
        self.assertEqual(eq.matricule, 'M-042')
        self.assertEqual(eq.heures_contrat_hebdo, Decimal('28'))

    def test_toggle_actif(self):
        eq = Equipier.objects.create(prenom='Habtom', nom='Tekie')
        self.client.login(username='david', password='pw')
        self.client.post(reverse('core:equipier-toggle-actif', args=[eq.pk]))
        eq.refresh_from_db()
        self.assertFalse(eq.actif)
        self.client.post(reverse('core:equipier-toggle-actif', args=[eq.pk]))
        eq.refresh_from_db()
        self.assertTrue(eq.actif)

    def test_creation_refusee_sans_acces(self):
        self.client.login(username='tech', password='pw')
        resp = self.client.post(reverse('core:equipier-save'), {
            'prenom': 'X', 'nom': 'Y',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Equipier.objects.filter(nom='Y').exists())


class PlanningGrilleTests(TestCase):
    """
    Commit 3 : emargement_view, affectation_save, presence_save.
    """

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='Ille-et-Vilaine')
        service = Service.objects.create(territoire=terr, nom='Insertion', module_planning=True)
        cls.equipe = Equipe.objects.create(service=service, nom='65-SORM')
        cls.autre  = Equipe.objects.create(service=service, nom='65-GORM')

        cls.encadrant = User.objects.create_user('laurene2', password='pw')
        ProfilUtilisateur.objects.create(user=cls.encadrant, role='technicien')
        cls.equipe.encadrant = cls.encadrant
        cls.equipe.save()

        cls.admin = User.objects.create_user('david2', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')

        cls.technicien = User.objects.create_user('tech2', password='pw')
        ProfilUtilisateur.objects.create(user=cls.technicien, role='technicien')

        cls.client_obj = Client.objects.create(nom='Ville de Rennes')
        cls.devis = Devis.objects.create(
            reference='DEV-PLAN-001',
            client=cls.client_obj,
            chantier='École Guillevic',
            status='accepted',
            created_by=cls.admin,
        )
        cls.eq1 = Equipier.objects.create(prenom='Habtom', nom='Tekie',   equipe=cls.equipe)
        cls.eq2 = Equipier.objects.create(prenom='Amina',  nom='Dawlatz', equipe=cls.equipe)
        cls.lundi = date(2026, 6, 1)  # semaine de test

    # ── emargement_view ───────────────────────────────────────

    def test_emargement_view_ok(self):
        self.client.login(username='laurene2', password='pw')
        resp = self.client.get(reverse('core:emargement') + f'?equipe={self.equipe.pk}&debut=2026-06-01')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Habtom')

    def test_emargement_view_interdit_sans_acces(self):
        self.client.login(username='tech2', password='pw')
        resp = self.client.get(reverse('core:emargement'))
        self.assertEqual(resp.status_code, 403)

    # ── planning_mois ─────────────────────────────────────────

    def test_planning_mois_ok(self):
        self.client.login(username='david2', password='pw')
        resp = self.client.get(reverse('core:planning'))
        self.assertEqual(resp.status_code, 200)

    def test_planning_mois_interdit_sans_acces(self):
        self.client.login(username='tech2', password='pw')
        resp = self.client.get(reverse('core:planning'))
        self.assertEqual(resp.status_code, 403)

    def test_planning_mois_fenetre_defaut(self):
        """Fenêtre large : 26 semaines, démarrant 6 semaines avant le lundi courant."""
        self.client.login(username='david2', password='pw')
        resp = self.client.get(reverse('core:planning'))
        today = timezone.localdate()
        lundi = today - timedelta(days=today.weekday())
        self.assertEqual(resp.context['nb_semaines'], 26)
        self.assertEqual(resp.context['cible_lundi'], lundi)
        self.assertEqual(resp.context['debut_grille'], lundi - timedelta(weeks=6))

    def test_planning_mois_debut_recentre_la_fenetre(self):
        """?debut= = date cible : la fenêtre rendue commence 6 semaines avant."""
        self.client.login(username='david2', password='pw')
        resp = self.client.get(reverse('core:planning') + '?debut=2026-09-16')  # un mercredi
        self.assertEqual(resp.context['cible_lundi'], date(2026, 9, 14))
        self.assertEqual(resp.context['debut_grille'], date(2026, 9, 14) - timedelta(weeks=6))

    # ── voies empilées (présentation) ─────────────────────────

    def test_planning_voies_empilees(self):
        """2 chantiers qui se chevauchent sur une équipe → 2 voies."""
        self.client.login(username='david2', password='pw')
        t1 = TrancheDevis.objects.create(devis=self.devis, nom='T1', ordre=0)
        t2 = TrancheDevis.objects.create(devis=self.devis, nom='T2', ordre=1)
        Affectation.objects.create(equipe=self.equipe, tranche=t1,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 12), created_by=self.admin)
        Affectation.objects.create(equipe=self.equipe, tranche=t2,
            date_debut=date(2026, 6, 8), date_fin=date(2026, 6, 19), created_by=self.admin)
        resp = self.client.get(reverse('core:planning') + '?debut=2026-06-08')
        ligne = next(l for l in resp.context['lignes'] if l['equipe'].pk == self.equipe.pk)
        self.assertEqual(ligne['nb_voies'], 2)
        self.assertEqual(sorted(b['voie'] for b in ligne['barres']), [0, 1])

    def test_planning_voie_unique_sans_chevauchement(self):
        """2 chantiers séquentiels (sans chevauchement) → 1 seule voie."""
        self.client.login(username='david2', password='pw')
        t1 = TrancheDevis.objects.create(devis=self.devis, nom='T1', ordre=0)
        t2 = TrancheDevis.objects.create(devis=self.devis, nom='T2', ordre=1)
        Affectation.objects.create(equipe=self.equipe, tranche=t1,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5), created_by=self.admin)
        Affectation.objects.create(equipe=self.equipe, tranche=t2,
            date_debut=date(2026, 6, 15), date_fin=date(2026, 6, 19), created_by=self.admin)
        resp = self.client.get(reverse('core:planning') + '?debut=2026-06-08')
        ligne = next(l for l in resp.context['lignes'] if l['equipe'].pk == self.equipe.pk)
        self.assertEqual(ligne['nb_voies'], 1)
        self.assertTrue(all(b['voie'] == 0 for b in ligne['barres']))

    def test_planning_filtre_equipes_persiste(self):
        """Le filtre d'équipes est mémorisé sur le profil et pré-appliqué."""
        self.client.login(username='david2', password='pw')
        resp = self.client.post(
            reverse('core:planning-filtre-equipes'),
            data=json.dumps({'equipes': [self.equipe.pk]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.admin.profil.refresh_from_db()
        self.assertEqual(self.admin.profil.planning_filtre_equipes, [self.equipe.pk])
        resp = self.client.get(reverse('core:planning'))
        self.assertEqual(resp.context['filtre_ids'], {self.equipe.pk})
        ligne_autre = next(l for l in resp.context['lignes'] if l['equipe'].pk == self.autre.pk)
        self.assertTrue(ligne_autre['masquee'])

    # ── couleurs par équipe (anti-collision) ──────────────────

    def _aff(self, devis, debut, fin, ordre=0, couleur=''):
        tr = TrancheDevis.objects.create(devis=devis, nom=f'T{ordre}', ordre=ordre)
        return Affectation.objects.create(
            equipe=self.equipe, tranche=tr, date_debut=debut, date_fin=fin,
            couleur=couleur, created_by=self.admin,
        )

    def test_couleurs_chantiers_chevauchants_distinctes(self):
        """3 chantiers (devis distincts) qui se chevauchent → 3 teintes distinctes."""
        from core.planning_utils import couleurs_par_equipe
        d2 = Devis.objects.create(reference='DEV-PLAN-002', client=self.client_obj, status='accepted', created_by=self.admin)
        d3 = Devis.objects.create(reference='DEV-PLAN-003', client=self.client_obj, status='accepted', created_by=self.admin)
        a1 = self._aff(self.devis, date(2026, 6, 1), date(2026, 6, 12), 0)
        a2 = self._aff(d2,          date(2026, 6, 8), date(2026, 6, 19), 0)
        a3 = self._aff(d3,          date(2026, 6, 10), date(2026, 6, 15), 0)
        affs = list(Affectation.objects.filter(pk__in=[a1.pk, a2.pk, a3.pk]).select_related('tranche'))
        color = couleurs_par_equipe(affs)
        self.assertEqual(len({color[a1.pk], color[a2.pk], color[a3.pk]}), 3)

    def test_couleurs_meme_devis_meme_teinte(self):
        """Deux affectations du même devis sur l'équipe → même teinte."""
        from core.planning_utils import couleurs_par_equipe
        a1 = self._aff(self.devis, date(2026, 6, 1),  date(2026, 6, 5),  0)
        a2 = self._aff(self.devis, date(2026, 6, 15), date(2026, 6, 19), 1)
        affs = list(Affectation.objects.filter(pk__in=[a1.pk, a2.pk]).select_related('tranche'))
        color = couleurs_par_equipe(affs)
        self.assertEqual(color[a1.pk], color[a2.pk])

    def test_couleur_surcharge_manuelle_prioritaire(self):
        """La surcharge `Affectation.couleur` est respectée."""
        from core.planning_utils import couleurs_par_equipe
        a1 = self._aff(self.devis, date(2026, 6, 1), date(2026, 6, 5), 0, couleur='chf')
        affs = list(Affectation.objects.filter(pk=a1.pk).select_related('tranche'))
        self.assertEqual(couleurs_par_equipe(affs)[a1.pk], 'chf')

    # ── imputation par demi-journée ───────────────────────────

    def test_presence_reassign_impute_demi_journee(self):
        """Réimputer une demi-journée bascule les présences de l'équipe au bon chantier."""
        self.client.login(username='laurene2', password='pw')
        d2 = Devis.objects.create(reference='DEV-PLAN-002', client=self.client_obj, status='accepted', created_by=self.admin)
        aA = self._aff(self.devis, date(2026, 6, 1), date(2026, 6, 12), 0)
        aB = self._aff(d2,          date(2026, 6, 1), date(2026, 6, 12), 0)
        Presence.objects.create(equipier=self.eq1, affectation=aA, date=date(2026, 6, 2),
                                creneau='matin', heures=Decimal('4'), saisi_par=self.admin)
        resp = self.client.post(
            reverse('core:presence-reassign'),
            data=json.dumps({'equipe_id': self.equipe.pk, 'date': '2026-06-02',
                             'creneau': 'matin', 'affectation_id': aB.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        p = Presence.objects.get(equipier=self.eq1, date=date(2026, 6, 2), creneau='matin')
        self.assertEqual(p.affectation_id, aB.pk)
        # L'après-midi n'est pas touché (aucune présence) — pas d'effet de bord
        self.assertFalse(Presence.objects.filter(date=date(2026, 6, 2), creneau='aprem').exists())

    def test_presence_reassign_refuse_si_cloture(self):
        """Un mois clôturé verrouille la réimputation."""
        self.client.login(username='laurene2', password='pw')
        aA = self._aff(self.devis, date(2026, 6, 1), date(2026, 6, 12), 0)
        Presence.objects.create(equipier=self.eq1, affectation=aA, date=date(2026, 6, 2),
                                creneau='matin', heures=Decimal('4'), saisi_par=self.admin)
        ClotureMois.objects.create(equipe=self.equipe, annee=2026, mois=6)
        resp = self.client.post(
            reverse('core:presence-reassign'),
            data=json.dumps({'equipe_id': self.equipe.pk, 'date': '2026-06-02',
                             'creneau': 'matin', 'affectation_id': aA.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_affectation_couleur_surcharge(self):
        """L'endpoint écrit Affectation.couleur (et refuse une teinte invalide)."""
        self.client.login(username='laurene2', password='pw')
        a = self._aff(self.devis, date(2026, 6, 1), date(2026, 6, 5), 0)
        resp = self.client.post(
            reverse('core:affectation-couleur'),
            data=json.dumps({'affectation_id': a.pk, 'couleur': 'chg'}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.couleur, 'chg')
        resp = self.client.post(
            reverse('core:affectation-couleur'),
            data=json.dumps({'affectation_id': a.pk, 'couleur': 'zz'}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    # ── affectation_save ──────────────────────────────────────

    def test_affectation_save_ok(self):
        self.client.login(username='laurene2', password='pw')
        resp = self.client.post(
            reverse('core:affectation-save'),
            data=json.dumps({
                'devis_id': self.devis.pk,
                'equipe_id': self.equipe.pk,
                'date_debut': '2026-06-01',
                'date_fin':   '2026-06-05',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        aff = Affectation.objects.get(pk=data['affectation_id'])
        self.assertEqual(aff.equipe, self.equipe)
        self.assertEqual(aff.tranche.devis, self.devis)

    def test_affectation_save_refuse_autre_equipe(self):
        self.client.login(username='laurene2', password='pw')
        resp = self.client.post(
            reverse('core:affectation-save'),
            data=json.dumps({
                'devis_id': self.devis.pk,
                'equipe_id': self.autre.pk,
                'date_debut': '2026-06-01',
                'date_fin':   '2026-06-05',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_affectation_fin_avant_debut(self):
        self.client.login(username='laurene2', password='pw')
        resp = self.client.post(
            reverse('core:affectation-save'),
            data=json.dumps({
                'devis_id': self.devis.pk,
                'equipe_id': self.equipe.pk,
                'date_debut': '2026-06-05',
                'date_fin':   '2026-06-01',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # ── presence_save ─────────────────────────────────────────

    def _make_aff(self):
        tranche = TrancheDevis.objects.create(devis=self.devis, nom='Complet', ordre=0)
        return Affectation.objects.create(
            equipe=self.equipe, tranche=tranche,
            date_debut=self.lundi, date_fin=self.lundi + timedelta(days=4),
            created_by=self.admin,
        )

    def test_presence_save_heures(self):
        aff = self._make_aff()
        self.client.login(username='laurene2', password='pw')
        resp = self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': self.eq1.pk,
                'affectation_id': aff.pk,
                'date': '2026-06-01',
                'creneau': 'matin',
                'heures': '4',
                'code': '',
            }]}),
            content_type='application/json',
        )
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['saved'], 1)
        p = Presence.objects.get(equipier=self.eq1, date=date(2026, 6, 1), creneau='matin')
        self.assertEqual(p.heures, Decimal('4'))

    def test_presence_save_code_absence(self):
        aff = self._make_aff()
        self.client.login(username='laurene2', password='pw')
        self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': self.eq1.pk,
                'affectation_id': aff.pk,
                'date': '2026-06-02',
                'creneau': 'aprem',
                'heures': None,
                'code': 'c',
            }]}),
            content_type='application/json',
        )
        p = Presence.objects.get(equipier=self.eq1, date=date(2026, 6, 2), creneau='aprem')
        self.assertEqual(p.code, 'C')
        self.assertEqual(p.heures, Decimal('0'))

    def test_presence_save_suppression(self):
        aff = self._make_aff()
        Presence.objects.create(
            equipier=self.eq1, affectation=aff,
            date=date(2026, 6, 3), creneau='matin',
            heures=Decimal('4'),
        )
        self.client.login(username='laurene2', password='pw')
        self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': self.eq1.pk,
                'affectation_id': aff.pk,
                'date': '2026-06-03',
                'creneau': 'matin',
                'heures': None,
                'code': '',
            }]}),
            content_type='application/json',
        )
        self.assertFalse(
            Presence.objects.filter(equipier=self.eq1, date=date(2026, 6, 3), creneau='matin').exists()
        )

    def test_presence_unique_together(self):
        """Upsert : deux saves pour la même (equipier, date, creneau) → 1 seule ligne."""
        aff = self._make_aff()
        self.client.login(username='laurene2', password='pw')
        payload = lambda h: json.dumps({'presences': [{
            'equipier_id': self.eq1.pk, 'affectation_id': aff.pk,
            'date': '2026-06-01', 'creneau': 'matin', 'heures': h, 'code': '',
        }]})
        self.client.post(reverse('core:presence-save'), data=payload('4'), content_type='application/json')
        self.client.post(reverse('core:presence-save'), data=payload('3.5'), content_type='application/json')
        self.assertEqual(
            Presence.objects.filter(equipier=self.eq1, date=date(2026, 6, 1), creneau='matin').count(), 1
        )
        p = Presence.objects.get(equipier=self.eq1, date=date(2026, 6, 1), creneau='matin')
        self.assertEqual(p.heures, Decimal('3.5'))

    def test_presence_interdit_sans_acces(self):
        aff = self._make_aff()
        self.client.login(username='tech2', password='pw')
        resp = self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': self.eq1.pk,
                'affectation_id': aff.pk,
                'date': '2026-06-01',
                'creneau': 'matin',
                'heures': '4',
                'code': '',
            }]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    # ── Phase 2 : permission membre insertion ─────────────────

    def test_permission_membre_insertion_peut_modifier(self):
        """Membre du service insertion (non-encadrant) peut saisir une présence."""
        assistante = User.objects.create_user('assistante_test', password='pw')
        ProfilUtilisateur.objects.create(
            user=assistante, role='technicien', service=self.equipe.service
        )
        aff = self._make_aff()
        self.client.login(username='assistante_test', password='pw')
        resp = self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': self.eq1.pk,
                'affectation_id': aff.pk,
                'date': '2026-06-01',
                'creneau': 'matin',
                'heures': '4',
                'code': '',
            }]}),
            content_type='application/json',
        )
        data = json.loads(resp.content)
        self.assertTrue(data.get('ok'), f"Attendu ok=True, reçu {data}")
        self.assertEqual(data['saved'], 1)

    # ── Phase 2 : code_absence événement ─────────────────────

    def test_evenement_code_absence_propagation(self):
        """Événement avec code_absence='F' → special_code='F' dans les cellules émargement."""
        ev = Evenement.objects.create(
            type='formation',
            libelle='Formation sécurité',
            date_debut=self.lundi,
            date_fin=self.lundi + timedelta(days=4),
            code_absence='F',
        )
        ev.equipes.set([self.equipe])
        self.client.login(username='laurene2', password='pw')
        resp = self.client.get(
            reverse('core:emargement') + f'?equipe={self.equipe.pk}&debut={self.lundi.isoformat()}'
        )
        self.assertEqual(resp.status_code, 200)
        grid_rows = resp.context['grid_rows_maison']
        lundi_matin = next(
            c for row in grid_rows for c in row['cells']
            if c['jour'] == self.lundi and c['creneau'] == 'matin'
        )
        self.assertEqual(lundi_matin['special_code'], 'F')


class PlanningBarreTests(TestCase):
    """
    Batterie de tests : flux émargement → barre de progression planning.

    A. Calcul heures_par_tranche (ORM direct, sans HTTP)
       – cas nominal, multi-équipiers, code absence, plafond 100 %,
         budget MO nul, chantier partagé entre deux équipes.

    B. Prêts inter-équipes
       – heures du prêté comptent dans la tranche hôte, pas dans la maison.

    C. presence_save (HTTP)
       – affectation hôte explicite, auto-lookup, upsert.

    D. pret_save (HTTP)
       – création, garde-fou présences existantes, suppression + nettoyage.
    """

    # Budget de référence : 20 j × 82,50 €/j-éq = 1 650 €
    # heures_budget = 1650 / 82.5 * 7 = 140 heures
    MO_QTE   = Decimal('20')
    MO_PU    = Decimal('82.50')
    H_BUDGET = float(MO_QTE * MO_PU) / 82.5 * 7  # 140.0

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='Ille-et-Vilaine-Barre')
        service = Service.objects.create(
            territoire=terr, nom='Insertion Barre', module_planning=True
        )

        cls.eq_a = Equipe.objects.create(service=service, nom='AQRM-A', actif=True, nb_equipiers=4)
        cls.eq_b = Equipe.objects.create(service=service, nom='AQRM-B', actif=True, nb_equipiers=4)

        cls.admin = User.objects.create_user('adm_barre', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')

        cls.enc_a = User.objects.create_user('enc_a_barre', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()

        cls.enc_b = User.objects.create_user('enc_b_barre', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_b, role='technicien')
        cls.eq_b.encadrant = cls.enc_b
        cls.eq_b.save()

        client = Client.objects.create(nom='CBB Barre Client')
        cls.devis = Devis.objects.create(
            reference='DEV-BARRE-01', client=client,
            chantier='Réhab Guillou', status='accepted',
            created_by=cls.admin,
        )
        LigneDevis.objects.create(
            devis=cls.devis, type_ligne='FMO',
            description='MO test', quantite=cls.MO_QTE,
            cout_unitaire=cls.MO_PU,
        )

        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='Complet', ordre=0)
        # Chantier partagé : même tranche, deux affectations
        cls.aff_a = Affectation.objects.create(
            equipe=cls.eq_a, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 12),
            created_by=cls.admin,
        )
        cls.aff_b = Affectation.objects.create(
            equipe=cls.eq_b, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 12),
            created_by=cls.admin,
        )

        cls.eq1_a = Equipier.objects.create(prenom='Habtom', nom='Tekie',  equipe=cls.eq_a)
        cls.eq2_a = Equipier.objects.create(prenom='Amina',  nom='Diallo', equipe=cls.eq_a)
        cls.eq1_b = Equipier.objects.create(prenom='Jonas',  nom='Durand', equipe=cls.eq_b)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _heures_tranche(self, tranche):
        """Reproduit l'agrégation `heures_par_tranche` de planning_mois."""
        from django.db.models import Sum
        row = Presence.objects.filter(
            affectation__tranche=tranche
        ).aggregate(total=Sum('heures'))
        return float(row['total'] or 0)

    def _pct(self, tranche, mo_eur=None):
        """Reproduit le calcul `pct_consomme` de planning_mois."""
        if mo_eur is None:
            mo_eur = float(self.MO_QTE * self.MO_PU)
        heures_budget = mo_eur / 82.5 * 7
        heures_conso  = self._heures_tranche(tranche)
        return min(100, round(heures_conso / heures_budget * 100)) if heures_budget > 0 else 0

    def _presence(self, equipier, aff, date_val, creneau, heures=None, code=''):
        """Crée une Presence directement (sans HTTP)."""
        return Presence.objects.create(
            equipier=equipier, affectation=aff,
            date=date_val, creneau=creneau,
            heures=Decimal(str(heures)) if heures is not None else Decimal('0'),
            code=code,
        )

    def _post_presence(self, equipier, aff, date_iso, creneau, heures=None, code=''):
        self.client.login(username='adm_barre', password='pw')
        return self.client.post(
            reverse('core:presence-save'),
            data=json.dumps({'presences': [{
                'equipier_id': equipier.pk,
                'affectation_id': aff.pk if aff else None,
                'date': date_iso,
                'creneau': creneau,
                'heures': heures,
                'code': code,
            }]}),
            content_type='application/json',
        )

    # ── A. Calcul heures_par_tranche (ORM) ───────────────────────────────

    def test_pct_zero_sans_presences(self):
        """Sans présence, pct = 0."""
        self.assertEqual(self._pct(self.tranche), 0)

    def test_presence_simple_pct(self):
        """7 h sur budget 140 h → 5 %."""
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 1), 'matin', heures=7)
        self.assertEqual(self._pct(self.tranche), 5)

    def test_presence_deux_equipiers_meme_equipe_somme(self):
        """Heures de deux équipiers de la même équipe s'additionnent (14 h → 10 %)."""
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 2), 'matin', heures=7)
        self._presence(self.eq2_a, self.aff_a, date(2026, 6, 2), 'matin', heures=7)
        self.assertEqual(self._pct(self.tranche), 10)

    def test_chantier_partage_somme_deux_equipes(self):
        """
        Chantier partagé (même tranche, aff_a + aff_b) :
        les heures des deux équipes s'additionnent correctement.
        7 h équipe A + 7 h équipe B = 14 h → 10 %.
        """
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 3), 'matin', heures=7)
        self._presence(self.eq1_b, self.aff_b, date(2026, 6, 3), 'matin', heures=7)
        self.assertEqual(self._pct(self.tranche), 10)

    def test_chantier_partage_progression_independante(self):
        """
        Chantier partagé : la barre reflète la progression cumulée,
        indépendamment de quelle équipe a saisi les heures.
        4 j × 7 h = 28 h sur eq_b seule → 20 %.
        """
        for d_offset in range(4):
            self._presence(
                self.eq1_b, self.aff_b,
                date(2026, 6, 1) + timedelta(days=d_offset), 'matin', heures=7,
            )
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 28.0)
        self.assertEqual(self._pct(self.tranche), 20)

    def test_chantier_partage_accumulation_100_pct(self):
        """
        Chantier partagé : 5 j × 2 créneaux × 2 équipes × 7 h = 140 h → 100 %.
        """
        for eq, aff in ((self.eq1_a, self.aff_a), (self.eq1_b, self.aff_b)):
            for d_off in range(5):
                d = date(2026, 6, 2) + timedelta(days=d_off)
                self._presence(eq, aff, d, 'matin', heures=7)
                self._presence(eq, aff, d, 'aprem', heures=7)
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 140.0)
        self.assertEqual(self._pct(self.tranche), 100)

    def test_code_absence_ne_contribue_pas(self):
        """Code absence → heures = 0 → pct reste 0."""
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 4), 'matin', heures=0, code='M')
        self.assertEqual(self._pct(self.tranche), 0)

    def test_mix_presences_et_absences(self):
        """
        Matin présent (7 h) + après-midi absence (0 h) :
        seules les heures réelles comptent → 7 h → 5 %.
        """
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 5), 'matin', heures=7)
        self._presence(self.eq1_a, self.aff_a, date(2026, 6, 5), 'aprem', heures=0, code='C')
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 7.0)
        self.assertEqual(self._pct(self.tranche), 5)

    def test_pct_plafond_100(self):
        """150 h saisies sur budget 140 h → pct = 100 (plafonné, pas 107)."""
        client2 = Client.objects.create(nom='Client Plafond')
        devis2  = Devis.objects.create(
            reference='DEV-PLAF-01', client=client2, status='accepted',
            created_by=self.admin,
        )
        LigneDevis.objects.create(
            devis=devis2, type_ligne='FMO', description='MO plafond',
            quantite=self.MO_QTE, cout_unitaire=self.MO_PU,
        )
        tranche2 = TrancheDevis.objects.create(devis=devis2, nom='Complet', ordre=0)
        aff2 = Affectation.objects.create(
            equipe=self.eq_a, tranche=tranche2,
            date_debut=date(2026, 7, 1), date_fin=date(2026, 7, 31),
            created_by=self.admin,
        )
        for i in range(21):
            Presence.objects.create(
                equipier=self.eq1_a, affectation=aff2,
                date=date(2026, 7, 1) + timedelta(days=i), creneau='matin',
                heures=Decimal('7'),
            )
        Presence.objects.create(
            equipier=self.eq1_a, affectation=aff2,
            date=date(2026, 7, 22), creneau='aprem', heures=Decimal('3'),
        )
        self.assertAlmostEqual(self._heures_tranche(tranche2), 150.0)
        self.assertEqual(self._pct(tranche2), 100)

    def test_pct_budget_mo_nul(self):
        """Devis sans ligne MO (budget = 0) → pct = 0 sans division par zéro."""
        client_nm = Client.objects.create(nom='Client sans MO')
        devis_nm  = Devis.objects.create(
            reference='DEV-NOMO-01', client=client_nm, status='accepted',
            created_by=self.admin,
        )
        tranche_nm = TrancheDevis.objects.create(devis=devis_nm, nom='Complet', ordre=0)
        aff_nm = Affectation.objects.create(
            equipe=self.eq_a, tranche=tranche_nm,
            date_debut=date(2026, 8, 1), date_fin=date(2026, 8, 5),
            created_by=self.admin,
        )
        Presence.objects.create(
            equipier=self.eq1_a, affectation=aff_nm,
            date=date(2026, 8, 3), creneau='matin', heures=Decimal('7'),
        )
        self.assertEqual(self._pct(tranche_nm, mo_eur=0.0), 0)

    # ── B. Prêts inter-équipes : impact sur la barre ──────────────────────

    def test_pret_heures_comptent_dans_tranche_distincte(self):
        """
        eq1_a prêté à eq_b, présence sur tranche propre à eq_b :
        les heures alimentent la tranche hôte, pas la tranche maison.
        """
        client_h = Client.objects.create(nom='Chantier Hôte')
        devis_h  = Devis.objects.create(
            reference='DEV-HOTE-01', client=client_h, status='accepted',
            created_by=self.admin,
        )
        LigneDevis.objects.create(
            devis=devis_h, type_ligne='FMO', description='MO hôte',
            quantite=Decimal('10'), cout_unitaire=self.MO_PU,
        )
        tranche_h = TrancheDevis.objects.create(devis=devis_h, nom='Hôte', ordre=0)
        aff_hote  = Affectation.objects.create(
            equipe=self.eq_b, tranche=tranche_h,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5),
            created_by=self.admin,
        )
        self._presence(self.eq1_a, aff_hote, date(2026, 6, 2), 'matin', heures=7)
        # Tranche maison : non impactée
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 0.0)
        # Tranche hôte : alimentée
        self.assertAlmostEqual(self._heures_tranche(tranche_h), 7.0)

    def test_pret_chantier_partage_affectation_croisee(self):
        """
        Chantier partagé (même tranche) + prêt croisé :
        eq1_a dont la présence pointe sur aff_b contribue quand même
        à la tranche commune (car aff_b.tranche == self.tranche).
        """
        self._presence(self.eq1_a, self.aff_b, date(2026, 6, 8), 'matin', heures=7)
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 7.0)
        self.assertEqual(self._pct(self.tranche), 5)

    # ── C. presence_save — endpoint HTTP ─────────────────────────────────

    def test_presence_save_pret_affectation_hote(self):
        """
        Présence avec affectation_id de l'équipe hôte → Presence pointe bien
        sur l'affectation hôte (les heures iront dans la tranche hôte).
        """
        resp = self._post_presence(self.eq1_a, self.aff_b, '2026-06-01', 'matin', heures='7')
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        p = Presence.objects.get(equipier=self.eq1_a, date=date(2026, 6, 1), creneau='matin')
        self.assertEqual(p.affectation_id, self.aff_b.pk)

    def test_presence_save_pret_heures_alimentent_tranche(self):
        """Après save sur aff_b, le pct de la tranche partagée est mis à jour."""
        self._post_presence(self.eq1_a, self.aff_b, '2026-06-09', 'matin', heures='7')
        self.assertEqual(self._pct(self.tranche), 5)

    def test_presence_save_auto_lookup_trouve_aff_maison(self):
        """
        Sans affectation_id explicite, l'auto-lookup résout l'affectation
        active de l'équipe maison (aff_a pour eq1_a).
        """
        resp = self._post_presence(self.eq1_a, None, '2026-06-02', 'matin', heures='4')
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        p = Presence.objects.get(equipier=self.eq1_a, date=date(2026, 6, 2), creneau='matin')
        self.assertEqual(p.affectation_id, self.aff_a.pk)

    def test_presence_save_chantier_partage_deux_equipes(self):
        """
        Chantier partagé via API : une présence par équipe → somme correcte.
        """
        self._post_presence(self.eq1_a, self.aff_a, '2026-06-10', 'matin', heures='7')
        self._post_presence(self.eq1_b, self.aff_b, '2026-06-10', 'matin', heures='7')
        self.assertAlmostEqual(self._heures_tranche(self.tranche), 14.0)
        self.assertEqual(self._pct(self.tranche), 10)

    def test_presence_save_upsert_ne_duplique_pas(self):
        """
        Deux saves successifs → 1 seule ligne en base, pct = dernière valeur.
        """
        self._post_presence(self.eq1_a, self.aff_a, '2026-06-04', 'aprem', heures='7')
        self._post_presence(self.eq1_a, self.aff_a, '2026-06-04', 'aprem', heures='3.5')
        count = Presence.objects.filter(
            equipier=self.eq1_a, date=date(2026, 6, 4), creneau='aprem'
        ).count()
        self.assertEqual(count, 1)
        p = Presence.objects.get(equipier=self.eq1_a, date=date(2026, 6, 4), creneau='aprem')
        self.assertEqual(p.heures, Decimal('3.5'))
        # pct = 3.5/140*100 ≈ 2 % (pas 10.5 % comme si les deux saves s'additionnaient)
        self.assertEqual(self._pct(self.tranche), 2)

    def test_presence_save_absence_heures_zero(self):
        """Code absence → heures = 0 → pct reste à 0."""
        resp = self._post_presence(self.eq1_a, self.aff_a, '2026-06-03', 'aprem', code='C')
        self.assertTrue(json.loads(resp.content)['ok'])
        p = Presence.objects.get(equipier=self.eq1_a, date=date(2026, 6, 3), creneau='aprem')
        self.assertEqual(p.heures, Decimal('0'))
        self.assertEqual(p.code, 'C')
        self.assertEqual(self._pct(self.tranche), 0)

    # ── D. pret_save — endpoint HTTP ──────────────────────────────────────

    def test_pret_save_creation_ok(self):
        """Créer un prêt → objet Pret enregistré en base."""
        self.client.login(username='adm_barre', password='pw')
        resp = self.client.post(
            reverse('core:pret-save'),
            data=json.dumps({
                'action': 'create',
                'equipier_id':    self.eq1_a.pk,
                'equipe_hote_id': self.eq_b.pk,
                'date_debut':     '2026-06-08',
                'creneau_debut':  'matin',
                'date_fin':       '2026-06-09',
                'creneau_fin':    'aprem',
            }),
            content_type='application/json',
        )
        self.assertTrue(json.loads(resp.content)['ok'])
        self.assertTrue(Pret.objects.filter(equipier=self.eq1_a, equipe_hote=self.eq_b).exists())

    def test_pret_save_bloque_presences_existantes_maison(self):
        """
        Création d'un prêt refusée si des présences sont déjà saisies
        sur l'équipe maison pour la période demandée.
        """
        Presence.objects.create(
            equipier=self.eq1_a, affectation=self.aff_a,
            date=date(2026, 6, 15), creneau='matin', heures=Decimal('4'),
        )
        self.client.login(username='adm_barre', password='pw')
        resp = self.client.post(
            reverse('core:pret-save'),
            data=json.dumps({
                'action': 'create',
                'equipier_id':    self.eq1_a.pk,
                'equipe_hote_id': self.eq_b.pk,
                'date_debut':     '2026-06-15',
                'creneau_debut':  'matin',
                'date_fin':       '2026-06-15',
                'creneau_fin':    'aprem',
            }),
            content_type='application/json',
        )
        data = json.loads(resp.content)
        self.assertFalse(data['ok'])
        self.assertIn('error', data)

    def test_pret_save_suppression_nettoie_presences_hote(self):
        """
        Supprimer un prêt efface les présences de l'équipier sur l'affectation
        de l'équipe hôte, mais laisse intactes les présences maison.
        """
        pret = Pret.objects.create(
            equipier=self.eq1_a, equipe_hote=self.eq_b,
            date_debut=date(2026, 6, 22), creneau_debut='matin',
            date_fin=date(2026, 6, 23), creneau_fin='aprem',
            cree_par=self.admin,
        )
        p_hote = Presence.objects.create(
            equipier=self.eq1_a, affectation=self.aff_b,
            date=date(2026, 6, 22), creneau='matin', heures=Decimal('7'),
        )
        p_maison = Presence.objects.create(
            equipier=self.eq1_a, affectation=self.aff_a,
            date=date(2026, 6, 25), creneau='matin', heures=Decimal('4'),
        )
        self.client.login(username='adm_barre', password='pw')
        resp = self.client.post(
            reverse('core:pret-save'),
            data=json.dumps({'action': 'delete', 'pret_id': pret.pk}),
            content_type='application/json',
        )
        self.assertTrue(json.loads(resp.content)['ok'])
        self.assertFalse(Presence.objects.filter(pk=p_hote.pk).exists())
        self.assertTrue(Presence.objects.filter(pk=p_maison.pk).exists())
        self.assertFalse(Pret.objects.filter(pk=pret.pk).exists())

    def test_pret_save_suppression_pct_revient_a_zero(self):
        """
        Après suppression du prêt et de sa présence hôte,
        le pct de la tranche hôte repasse à 0.
        """
        client_h2 = Client.objects.create(nom='Hôte Pct')
        devis_h2  = Devis.objects.create(
            reference='DEV-HOTE-02', client=client_h2, status='accepted',
            created_by=self.admin,
        )
        LigneDevis.objects.create(
            devis=devis_h2, type_ligne='FMO', description='MO hôte2',
            quantite=self.MO_QTE, cout_unitaire=self.MO_PU,
        )
        tranche_h2 = TrancheDevis.objects.create(devis=devis_h2, nom='Hôte2', ordre=0)
        aff_h2 = Affectation.objects.create(
            equipe=self.eq_b, tranche=tranche_h2,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5),
            created_by=self.admin,
        )
        pret = Pret.objects.create(
            equipier=self.eq1_a, equipe_hote=self.eq_b,
            date_debut=date(2026, 6, 1), creneau_debut='matin',
            date_fin=date(2026, 6, 1), creneau_fin='aprem',
            cree_par=self.admin,
        )
        Presence.objects.create(
            equipier=self.eq1_a, affectation=aff_h2,
            date=date(2026, 6, 1), creneau='matin', heures=Decimal('7'),
        )
        self.assertEqual(self._pct(tranche_h2), 5)

        self.client.login(username='adm_barre', password='pw')
        self.client.post(
            reverse('core:pret-save'),
            data=json.dumps({'action': 'delete', 'pret_id': pret.pk}),
            content_type='application/json',
        )
        self.assertEqual(self._pct(tranche_h2), 0)

    def test_pret_save_interdit_sans_acces_planning(self):
        """Un technicien sans équipe ne peut pas créer un prêt."""
        user_ext = User.objects.create_user('user_ext_pret', password='pw')
        ProfilUtilisateur.objects.create(user=user_ext, role='technicien')
        self.client.login(username='user_ext_pret', password='pw')
        resp = self.client.post(
            reverse('core:pret-save'),
            data=json.dumps({
                'action': 'create',
                'equipier_id': self.eq1_a.pk,
                'equipe_hote_id': self.eq_b.pk,
                'date_debut': '2026-06-08',
                'date_fin':   '2026-06-09',
            }),
            content_type='application/json',
        )
        self.assertFalse(json.loads(resp.content)['ok'])


class JoursFeriesTests(TestCase):
    """`_jours_feries` : fériés légaux FR, Pâques mobile, Pentecôte exclue."""

    def test_feries_2026(self):
        attendus = {
            date(2026, 1, 1), date(2026, 4, 6),    # Lundi de Pâques (Pâques = 5 avril)
            date(2026, 5, 1), date(2026, 5, 8),
            date(2026, 5, 14),                     # Ascension
            date(2026, 7, 14), date(2026, 8, 15),
            date(2026, 11, 1), date(2026, 11, 11),
            date(2026, 12, 25),
        }
        self.assertEqual(set(_jours_feries(2026)), attendus)

    def test_pentecote_exclue(self):
        # Journée de solidarité travaillée chez CB Bretagne (2026 : 25 mai)
        self.assertNotIn(date(2026, 5, 25), _jours_feries(2026))

    def test_paques_mobile_2027(self):
        # Pâques 2027 = 28 mars → lundi 29 mars, Ascension 6 mai
        feries = _jours_feries(2027)
        self.assertIn(date(2027, 3, 29), feries)
        self.assertIn(date(2027, 5, 6), feries)


class BuildGrilleTests(TestCase):
    """
    `_build_grille` : régressions des 4 bugs corrigés session 31
    + chevauchement d'année. Les valeurs attendues reproduisent le
    comportement validé en beta.
    """

    def test_structure_blocs(self):
        # Invariants : 5 jours par bloc, labels L M M J V, chaque bloc démarre un lundi.
        for bloc in _build_grille(2026, 7):
            self.assertEqual(len(bloc['jours']), 5)
            self.assertEqual([j['label'] for j in bloc['jours']], ['L', 'M', 'M', 'J', 'V'])
            self.assertEqual(bloc['jours'][0]['date'].weekday(), 0)  # lundi

    def test_fiche_juillet_2026(self):
        # 26 juin = vendredi (ouvré) → ambré = semaine du 26 (S26) uniquement.
        blocs = _build_grille(2026, 7)
        self.assertEqual([b['num_semaine'] for b in blocs], [26, 27, 28, 29, 30, 31])
        self.assertTrue(blocs[0]['is_prev'])
        self.assertEqual(blocs[0]['jours'][0]['date'], date(2026, 6, 22))
        self.assertFalse(any(b['is_prev'] for b in blocs[1:]))

    def test_fiche_juillet_2026_jours_juin_editables(self):
        # Bug session 31 : 29-30 juin (1er bloc courant) doivent être
        # éditables (in_range) ET ambrés (is_prev) — pas grisés.
        blocs = _build_grille(2026, 7)
        s27 = blocs[1]
        jours = {j['date']: j for j in s27['jours']}
        for d in (date(2026, 6, 29), date(2026, 6, 30)):
            self.assertTrue(jours[d]['in_range'], f'{d} doit être éditable')
            self.assertTrue(jours[d]['is_prev'], f'{d} doit être ambré')
        self.assertFalse(jours[date(2026, 7, 1)]['is_prev'])

    def test_fiche_aout_2026_pas_de_semaine_superflue(self):
        # Bug session 31 : le 26 juillet 2026 est un dimanche → l'ambré part
        # de la semaine du dernier jour ouvré de juillet (S31, lun 27/07),
        # pas de la semaine du 26 (qui ajoutait une S30 superflue).
        # Le 1er août est un samedi → 1er bloc courant = lun 3 août.
        blocs = _build_grille(2026, 8)
        self.assertEqual([b['num_semaine'] for b in blocs], [31, 32, 33, 34, 35, 36])
        self.assertTrue(blocs[0]['is_prev'])
        self.assertEqual(blocs[0]['jours'][0]['date'], date(2026, 7, 27))
        self.assertEqual(blocs[1]['jours'][0]['date'], date(2026, 8, 3))

    def test_fiche_septembre_2026_aout_ambre(self):
        # Bug session 31 : le 31 août (1er bloc courant de la fiche septembre)
        # doit être ambré et éditable, pas grisé.
        blocs = _build_grille(2026, 9)
        s36 = blocs[1]
        jour_31 = {j['date']: j for j in s36['jours']}[date(2026, 8, 31)]
        self.assertTrue(jour_31['in_range'])
        self.assertTrue(jour_31['is_prev'])

    def test_fiche_janvier_chevauchement_annee(self):
        # Fiche janvier 2026 : ambré = S52/2025 (lun 22/12) ; la S1 ISO 2026
        # commence le 29/12/2025 (jours de décembre ambrés, 1er janv normal).
        blocs = _build_grille(2026, 1)
        self.assertEqual(blocs[0]['num_semaine'], 52)
        self.assertEqual(blocs[0]['annee_iso'], 2025)
        self.assertTrue(blocs[0]['is_prev'])
        s1 = blocs[1]
        self.assertEqual((s1['num_semaine'], s1['annee_iso']), (1, 2026))
        jours = {j['date']: j for j in s1['jours']}
        self.assertTrue(jours[date(2025, 12, 29)]['is_prev'])
        self.assertTrue(jours[date(2025, 12, 29)]['in_range'])
        self.assertFalse(jours[date(2026, 1, 1)]['is_prev'])


class JoursOuvresTests(TestCase):
    """`_count_working_days` / `_add_working_days` : semaine Lun–Jeu + exceptions."""

    LUNDI = date(2026, 6, 1)   # semaine du 1er juin 2026

    def test_semaine_standard_lun_jeu(self):
        self.assertEqual(_count_working_days(self.LUNDI, date(2026, 6, 7)), 4)

    def test_negatif_bloque_un_jour(self):
        neg = {date(2026, 6, 3)}  # mercredi bloqué
        self.assertEqual(_count_working_days(self.LUNDI, date(2026, 6, 7), set(), neg), 3)

    def test_positif_active_vendredi(self):
        pos = {date(2026, 6, 5)}  # vendredi travaillé
        self.assertEqual(_count_working_days(self.LUNDI, date(2026, 6, 7), pos, set()), 5)

    def test_add_4_jours_meme_semaine(self):
        self.assertEqual(_add_working_days(self.LUNDI, 4), date(2026, 6, 4))  # jeudi

    def test_add_5_jours_saute_weekend(self):
        self.assertEqual(_add_working_days(self.LUNDI, 5), date(2026, 6, 8))  # lundi suivant

    def test_add_5_jours_avec_vendredi_actif(self):
        pos = {date(2026, 6, 5)}
        self.assertEqual(_add_working_days(self.LUNDI, 5, pos), date(2026, 6, 5))  # vendredi

    def test_add_depart_weekend_avance_au_lundi(self):
        self.assertEqual(_add_working_days(date(2026, 6, 6), 1), date(2026, 6, 8))


class EvenementSetsTests(TestCase):
    """`_build_evenement_sets` : portée équipe/global, positifs/négatifs, créneau."""

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-EvSets')
        service = Service.objects.create(territoire=terr, nom='Insertion EvSets', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='EVS-A')
        cls.eq_b = Equipe.objects.create(service=service, nom='EVS-B')
        cls.debut = date(2026, 6, 1)
        cls.fin   = date(2026, 6, 30)

    def test_evenement_global_negatif(self):
        Evenement.objects.create(type='formation', date_debut=date(2026, 6, 3), creneau='journee')
        pos, neg = _build_evenement_sets(self.eq_a.pk, self.debut, self.fin)
        self.assertIn(date(2026, 6, 3), neg)
        # Global → s'applique aussi à l'équipe B
        _, neg_b = _build_evenement_sets(self.eq_b.pk, self.debut, self.fin)
        self.assertIn(date(2026, 6, 3), neg_b)

    def test_evenement_cible_une_equipe(self):
        ev = Evenement.objects.create(type='visite', date_debut=date(2026, 6, 4), creneau='journee')
        ev.equipes.set([self.eq_b.pk])
        _, neg_a = _build_evenement_sets(self.eq_a.pk, self.debut, self.fin)
        _, neg_b = _build_evenement_sets(self.eq_b.pk, self.debut, self.fin)
        self.assertNotIn(date(2026, 6, 4), neg_a)
        self.assertIn(date(2026, 6, 4), neg_b)

    def test_evenement_travaille_positif(self):
        Evenement.objects.create(
            type='jour_sup', date_debut=date(2026, 6, 5),  # vendredi
            creneau='journee', travaille=True,
        )
        pos, neg = _build_evenement_sets(self.eq_a.pk, self.debut, self.fin)
        self.assertIn(date(2026, 6, 5), pos)
        self.assertNotIn(date(2026, 6, 5), neg)

    def test_evenement_demi_journee_ne_bloque_pas(self):
        # Seul un événement négatif sur la journée entière bloque le jour.
        Evenement.objects.create(type='reunion', date_debut=date(2026, 6, 2), creneau='matin')
        _, neg = _build_evenement_sets(self.eq_a.pk, self.debut, self.fin)
        self.assertNotIn(date(2026, 6, 2), neg)

    def test_plage_multi_jours(self):
        Evenement.objects.create(
            type='formation', date_debut=date(2026, 6, 8),
            date_fin=date(2026, 6, 9), creneau='journee',
        )
        _, neg = _build_evenement_sets(self.eq_a.pk, self.debut, self.fin)
        self.assertIn(date(2026, 6, 8), neg)
        self.assertIn(date(2026, 6, 9), neg)
        self.assertNotIn(date(2026, 6, 10), neg)


class EvenementEndpointTests(TestCase):
    """
    `evenement_save` / `evenement_delete` : recalcul en cascade des
    affectations chevauchantes (`decale_chantier` / `travaille`).

    Budget : MO 330 € ÷ (82,5 €/j × 1 équipier) = 4 jours ouvrés.
    Affectation posée lun 1er juin 2026 → fin théorique jeu 4 juin.
    """

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-EvEnd')
        service = Service.objects.create(territoire=terr, nom='Insertion EvEnd', module_planning=True)
        cls.equipe = Equipe.objects.create(service=service, nom='EVE-A', actif=True, nb_equipiers=1)

        cls.admin = User.objects.create_user('adm_ev', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.technicien = User.objects.create_user('tech_ev', password='pw')
        ProfilUtilisateur.objects.create(user=cls.technicien, role='technicien')

        client = Client.objects.create(nom='Client EvEnd')
        cls.devis = Devis.objects.create(
            reference='DEV-EV-01', client=client, chantier='Chantier EvEnd',
            status='accepted', created_by=cls.admin,
        )
        cls.ligne_mo = LigneDevis.objects.create(
            devis=cls.devis, type_ligne='MO', description='MO',
            quantite=Decimal('4'), cout_unitaire=Decimal('82.50'),
        )
        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='Complet', ordre=0)
        cls.aff = Affectation.objects.create(
            equipe=cls.equipe, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 4),
            created_by=cls.admin,
        )

    def _post_evenement(self, payload, username='adm_ev'):
        self.client.login(username=username, password='pw')
        return self.client.post(
            reverse('core:evenement-save'),
            data=json.dumps(payload), content_type='application/json',
        )

    def test_evenement_decale_repousse_la_fin(self):
        # Mercredi 3 juin bloqué → le 4e jour ouvré passe au lundi 8 juin.
        resp = self._post_evenement({
            'type': 'formation', 'libelle': 'Formation sécurité',
            'date_debut': '2026-06-03', 'creneau': 'journee',
            'decale_chantier': True, 'equipe_ids': [self.equipe.pk],
        })
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        self.assertIn(self.aff.pk, data['recalculated'])
        self.aff.refresh_from_db()
        self.assertEqual(self.aff.date_fin, date(2026, 6, 8))

    def test_suppression_evenement_retablit_la_fin(self):
        self._post_evenement({
            'type': 'formation', 'date_debut': '2026-06-03',
            'creneau': 'journee', 'decale_chantier': True,
            'equipe_ids': [self.equipe.pk],
        })
        ev = Evenement.objects.get(type='formation')
        self.client.post(
            reverse('core:evenement-delete'),
            data=json.dumps({'pk': ev.pk}), content_type='application/json',
        )
        self.aff.refresh_from_db()
        self.assertEqual(self.aff.date_fin, date(2026, 6, 4))

    def test_evenement_travaille_avance_la_fin(self):
        # Budget porté à 5 jours, fin cohérente = lun 8 juin (le recalcul ne
        # touche que les affectations chevauchant l'événement). Avec le
        # vendredi 5 activé (travaille=True), la fin revient au ven 5 juin.
        self.ligne_mo.quantite = Decimal('5')
        self.ligne_mo.save()
        Affectation.objects.filter(pk=self.aff.pk).update(date_fin=date(2026, 6, 8))
        resp = self._post_evenement({
            'type': 'jour_sup', 'date_debut': '2026-06-05',
            'creneau': 'journee', 'travaille': True,
            'equipe_ids': [self.equipe.pk],
        })
        self.assertTrue(json.loads(resp.content)['ok'])
        self.aff.refresh_from_db()
        self.assertEqual(self.aff.date_fin, date(2026, 6, 5))

    def test_evenement_sans_decalage_ne_recalcule_pas(self):
        resp = self._post_evenement({
            'type': 'reunion', 'date_debut': '2026-06-03',
            'creneau': 'journee', 'equipe_ids': [self.equipe.pk],
        })
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['recalculated'], [])
        self.aff.refresh_from_db()
        self.assertEqual(self.aff.date_fin, date(2026, 6, 4))

    def test_evenement_refuse_sans_acces(self):
        resp = self._post_evenement(
            {'type': 'autre', 'date_debut': '2026-06-03'}, username='tech_ev')
        self.assertEqual(resp.status_code, 403)

    def test_evenement_date_invalide(self):
        resp = self._post_evenement({'type': 'autre', 'date_debut': 'pas-une-date'})
        self.assertEqual(resp.status_code, 400)


class FeuillesPresenceTests(TestCase):
    """
    Feuilles de présence mensuelles : vues (liste + fiche) et endpoints
    d'auto-save (`fiche_presence_save`, `fiche_note_save`).
    """

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Feuilles')
        service = Service.objects.create(territoire=terr, nom='Insertion Feuilles', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='FEU-A', actif=True)
        cls.eq_b = Equipe.objects.create(service=service, nom='FEU-B', actif=True)

        cls.enc_a = User.objects.create_user('enc_a_feu', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()

        cls.enc_b = User.objects.create_user('enc_b_feu', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_b, role='technicien')
        cls.eq_b.encadrant = cls.enc_b
        cls.eq_b.save()

        cls.technicien = User.objects.create_user('tech_feu', password='pw')
        ProfilUtilisateur.objects.create(user=cls.technicien, role='technicien')

        cls.equipier    = Equipier.objects.create(prenom='Habtom', nom='Tekie', equipe=cls.eq_a)
        cls.sans_equipe = Equipier.objects.create(prenom='Sans', nom='Équipe')

    def _post_fiche_presence(self, payload, username='enc_a_feu'):
        self.client.login(username=username, password='pw')
        return self.client.post(
            reverse('core:fiche-presence-save'),
            data=json.dumps(payload), content_type='application/json',
        )

    def _post_fiche_note(self, payload, username='enc_a_feu'):
        self.client.login(username=username, password='pw')
        return self.client.post(
            reverse('core:fiche-note-save'),
            data=json.dumps(payload), content_type='application/json',
        )

    # ── Vues ─────────────────────────────────────────────────────────────

    def test_feuilles_liste_ok_encadrant(self):
        self.client.login(username='enc_a_feu', password='pw')
        resp = self.client.get(reverse('core:feuilles-liste'))
        self.assertEqual(resp.status_code, 200)
        # L'encadrant ne voit que ses équipes
        self.assertEqual([e.pk for e in resp.context['equipes']], [self.eq_a.pk])

    def test_feuilles_liste_refusee_sans_acces(self):
        self.client.login(username='tech_feu', password='pw')
        resp = self.client.get(reverse('core:feuilles-liste'))
        self.assertEqual(resp.status_code, 403)

    def test_presence_feuille_ok(self):
        self.client.login(username='enc_a_feu', password='pw')
        resp = self.client.get(
            reverse('core:presence-feuille', args=[self.equipier.pk, 2026, 6]))
        self.assertEqual(resp.status_code, 200)

    def test_presence_feuille_equipier_sans_equipe(self):
        self.client.login(username='enc_a_feu', password='pw')
        resp = self.client.get(
            reverse('core:presence-feuille', args=[self.sans_equipe.pk, 2026, 6]))
        self.assertEqual(resp.status_code, 403)

    # ── Logos financeurs (Phase 4a) ──────────────────────────────────────

    # PNG 1×1 transparent — évite la dépendance PIL pour téléverser un logo.
    _PNG_1PX = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
        '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
    )

    def test_feuille_logo_fallback_nom(self):
        """Financeur sans logo → son nom s'affiche dans un cadre (.logo-nom)."""
        fin = Financeur.objects.create(nom='Région Bretagne')
        self.eq_a.financeurs.add(fin)
        self.client.login(username='enc_a_feu', password='pw')
        resp = self.client.get(
            reverse('core:presence-feuille', args=[self.equipier.pk, 2026, 6]))
        html = resp.content.decode()
        self.assertIn('class="logo-nom"', html)
        self.assertIn('Région Bretagne', html)
        self.assertNotIn('<img class="logo-img"', html)

    def test_feuille_logo_image(self):
        """Financeur avec logo → balise <img class="logo-img"> pointant le média."""
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                fin = Financeur.objects.create(nom='Ille-et-Vilaine')
                fin.logo.save('iv.png', SimpleUploadedFile(
                    'iv.png', self._PNG_1PX, content_type='image/png'))
                self.eq_a.financeurs.add(fin)
                self.client.login(username='enc_a_feu', password='pw')
                resp = self.client.get(
                    reverse('core:presence-feuille', args=[self.equipier.pk, 2026, 6]))
                html = resp.content.decode()
                self.assertIn('<img class="logo-img"', html)
                self.assertIn('financeurs/iv', html)

    # ── fiche_presence_save ──────────────────────────────────────────────

    def test_save_heures(self):
        resp = self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-01', 'creneau': 'matin', 'heures': '4',
        })
        self.assertTrue(json.loads(resp.content)['ok'])
        p = Presence.objects.get(equipier=self.equipier, date=date(2026, 6, 1), creneau='matin')
        self.assertEqual(p.heures, Decimal('4'))
        self.assertEqual(p.code, '')
        self.assertEqual(p.saisi_par, self.enc_a)

    def test_save_code_absence_force_heures_zero(self):
        self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-01', 'creneau': 'aprem',
            'code': 'm', 'heures': '3',
        })
        p = Presence.objects.get(equipier=self.equipier, date=date(2026, 6, 1), creneau='aprem')
        self.assertEqual(p.code, 'M')          # normalisé en majuscule
        self.assertEqual(p.heures, Decimal('0'))

    def test_save_vide_supprime_la_presence(self):
        Presence.objects.create(
            equipier=self.equipier, date=date(2026, 6, 2),
            creneau='matin', heures=Decimal('4'),
        )
        resp = self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-02', 'creneau': 'matin', 'heures': '', 'code': '',
        })
        self.assertEqual(json.loads(resp.content)['action'], 'deleted')
        self.assertFalse(Presence.objects.filter(
            equipier=self.equipier, date=date(2026, 6, 2), creneau='matin').exists())

    def test_save_lie_affectation_active(self):
        admin = User.objects.create_user('adm_feu', password='pw')
        ProfilUtilisateur.objects.create(user=admin, role='admin')
        client_obj = Client.objects.create(nom='Client Feuilles')
        devis = Devis.objects.create(
            reference='DEV-FEU-01', client=client_obj,
            status='accepted', created_by=admin,
        )
        tranche = TrancheDevis.objects.create(devis=devis, nom='Complet', ordre=0)
        aff = Affectation.objects.create(
            equipe=self.eq_a, tranche=tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 30),
            created_by=admin,
        )
        self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-03', 'creneau': 'matin', 'heures': '4',
        })
        p = Presence.objects.get(equipier=self.equipier, date=date(2026, 6, 3), creneau='matin')
        self.assertEqual(p.affectation, aff)

    def test_save_upsert_ne_duplique_pas(self):
        for heures in ('4', '3.5'):
            self._post_fiche_presence({
                'equipier_id': self.equipier.pk,
                'date': '2026-06-04', 'creneau': 'matin', 'heures': heures,
            })
        qs = Presence.objects.filter(
            equipier=self.equipier, date=date(2026, 6, 4), creneau='matin')
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().heures, Decimal('3.5'))

    def test_save_refuse_encadrant_autre_equipe(self):
        resp = self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-01', 'creneau': 'matin', 'heures': '4',
        }, username='enc_b_feu')
        self.assertEqual(resp.status_code, 403)

    def test_save_creneau_invalide(self):
        resp = self._post_fiche_presence({
            'equipier_id': self.equipier.pk,
            'date': '2026-06-01', 'creneau': 'soir', 'heures': '4',
        })
        self.assertEqual(resp.status_code, 400)

    # ── fiche_note_save ──────────────────────────────────────────────────

    def test_note_creation(self):
        resp = self._post_fiche_note({
            'equipier_id': self.equipier.pk,
            'annee': 2026, 'mois': 6, 'num_semaine': 23,
            'chantier_texte': 'Mairie de Rennes',
        })
        self.assertTrue(json.loads(resp.content)['ok'])
        note = FicheNote.objects.get(equipier=self.equipier, annee=2026, mois=6, num_semaine=23)
        self.assertEqual(note.chantier_texte, 'Mairie de Rennes')

    def test_note_update_partiel_conserve_chantier(self):
        # Mettre à jour la seule observation ne doit pas écraser le chantier.
        self._post_fiche_note({
            'equipier_id': self.equipier.pk,
            'annee': 2026, 'mois': 6, 'num_semaine': 24,
            'chantier_texte': 'École Guillevic',
        })
        self._post_fiche_note({
            'equipier_id': self.equipier.pk,
            'annee': 2026, 'mois': 6, 'num_semaine': 24,
            'observation_texte': 'Reprise enduits',
        })
        note = FicheNote.objects.get(equipier=self.equipier, annee=2026, mois=6, num_semaine=24)
        self.assertEqual(note.chantier_texte, 'École Guillevic')
        self.assertEqual(note.observation_texte, 'Reprise enduits')
        self.assertEqual(FicheNote.objects.filter(
            equipier=self.equipier, annee=2026, mois=6, num_semaine=24).count(), 1)

    def test_note_refuse_encadrant_autre_equipe(self):
        resp = self._post_fiche_note({
            'equipier_id': self.equipier.pk,
            'annee': 2026, 'mois': 6, 'num_semaine': 23,
            'chantier_texte': 'X',
        }, username='enc_b_feu')
        self.assertEqual(resp.status_code, 403)


class ClotureMoisTests(TestCase):
    """
    Verrou mensuel (`ClotureMois`) : un mois clôturé bloque toute écriture
    de présences (émargement, fiche, prêts) pour les équipiers de l'équipe.
    Endpoint `cloture_toggle` : encadrant clôt et déverrouille (choix S36).
    Les notes de semaine (FicheNote) restent modifiables.
    """

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Cloture')
        service = Service.objects.create(territoire=terr, nom='Insertion Cloture', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='CLO-A', actif=True)
        cls.eq_b = Equipe.objects.create(service=service, nom='CLO-B', actif=True)

        cls.enc_a = User.objects.create_user('enc_a_clo', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()

        cls.enc_b = User.objects.create_user('enc_b_clo', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_b, role='technicien')
        cls.eq_b.encadrant = cls.enc_b
        cls.eq_b.save()

        cls.equipier = Equipier.objects.create(prenom='Habtom', nom='Tekie', equipe=cls.eq_a)

    def _cloturer(self, annee=2026, mois=6):
        return ClotureMois.objects.create(
            equipe=self.eq_a, annee=annee, mois=mois, cloture_par=self.enc_a)

    def _post_json(self, url_name, payload, username='enc_a_clo'):
        self.client.login(username=username, password='pw')
        return self.client.post(
            reverse(url_name), data=json.dumps(payload),
            content_type='application/json')

    # ── cloture_toggle ───────────────────────────────────────────────────

    def test_toggle_cloture_puis_deverrouille(self):
        resp = self._post_json('core:cloture-toggle',
                               {'equipe_id': self.eq_a.pk, 'annee': 2026, 'mois': 6})
        self.assertTrue(json.loads(resp.content)['cloture'])
        c = ClotureMois.objects.get(equipe=self.eq_a, annee=2026, mois=6)
        self.assertEqual(c.cloture_par, self.enc_a)

        resp = self._post_json('core:cloture-toggle',
                               {'equipe_id': self.eq_a.pk, 'annee': 2026, 'mois': 6})
        self.assertFalse(json.loads(resp.content)['cloture'])
        self.assertFalse(ClotureMois.objects.filter(equipe=self.eq_a, annee=2026, mois=6).exists())

    def test_toggle_refuse_encadrant_autre_equipe(self):
        resp = self._post_json('core:cloture-toggle',
                               {'equipe_id': self.eq_a.pk, 'annee': 2026, 'mois': 6},
                               username='enc_b_clo')
        self.assertEqual(resp.status_code, 403)

    # ── Verrou sur fiche_presence_save ───────────────────────────────────

    def test_fiche_save_bloquee_mois_cloture(self):
        self._cloturer()
        resp = self._post_json('core:fiche-presence-save', {
            'equipier_id': self.equipier.pk,
            'date': '2026-06-15', 'creneau': 'matin', 'heures': '4',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertIn('clôturé', json.loads(resp.content)['error'])
        self.assertFalse(Presence.objects.exists())

    def test_fiche_save_ok_apres_deverrouillage(self):
        c = self._cloturer()
        c.delete()
        resp = self._post_json('core:fiche-presence-save', {
            'equipier_id': self.equipier.pk,
            'date': '2026-06-15', 'creneau': 'matin', 'heures': '4',
        })
        self.assertTrue(json.loads(resp.content)['ok'])
        self.assertEqual(Presence.objects.count(), 1)

    def test_fiche_save_autre_mois_non_bloque(self):
        self._cloturer(mois=5)   # mai clôturé, juin libre
        resp = self._post_json('core:fiche-presence-save', {
            'equipier_id': self.equipier.pk,
            'date': '2026-06-15', 'creneau': 'matin', 'heures': '4',
        })
        self.assertTrue(json.loads(resp.content)['ok'])

    # ── Verrou sur presence_save (émargement) ────────────────────────────

    def test_emargement_save_bloque_mois_cloture(self):
        self._cloturer()
        resp = self._post_json('core:presence-save', {'presences': [{
            'equipier_id': self.equipier.pk, 'affectation_id': None,
            'date': '2026-06-15', 'creneau': 'matin', 'heures': '4', 'code': '',
        }]})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Presence.objects.exists())

    # ── Verrou sur pret_save ─────────────────────────────────────────────

    def test_pret_creation_bloquee_mois_cloture(self):
        self._cloturer()
        resp = self._post_json('core:pret-save', {
            'action': 'create',
            'equipier_id': self.equipier.pk,
            'equipe_hote_id': self.eq_b.pk,
            'date_debut': '2026-06-08', 'date_fin': '2026-06-09',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Pret.objects.exists())

    def test_pret_suppression_bloquee_mois_cloture(self):
        pret = Pret.objects.create(
            equipier=self.equipier, equipe_hote=self.eq_b,
            date_debut=date(2026, 6, 8), date_fin=date(2026, 6, 9),
            cree_par=self.enc_a,
        )
        self._cloturer()
        resp = self._post_json('core:pret-save', {'action': 'delete', 'pret_id': pret.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Pret.objects.filter(pk=pret.pk).exists())

    # ── FicheNote non verrouillée (choix S36) ────────────────────────────

    def test_note_modifiable_malgre_cloture(self):
        self._cloturer()
        resp = self._post_json('core:fiche-note-save', {
            'equipier_id': self.equipier.pk,
            'annee': 2026, 'mois': 6, 'num_semaine': 25,
            'observation_texte': 'Correction RH',
        })
        self.assertTrue(json.loads(resp.content)['ok'])


class PlanningWizardDataTests(TestCase):
    """
    `planning_wizard_data` : données de la modal Affecter, servies à la
    demande (sorties du rendu de planning_mois / emargement_view).
    """

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Wizard')
        service = Service.objects.create(territoire=terr, nom='Insertion Wizard', module_planning=True)
        cls.equipe = Equipe.objects.create(service=service, nom='WIZ-A', actif=True, nb_equipiers=1)

        cls.admin = User.objects.create_user('adm_wiz', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.technicien = User.objects.create_user('tech_wiz', password='pw')
        ProfilUtilisateur.objects.create(user=cls.technicien, role='technicien')

        client = Client.objects.create(nom='Client Wizard')
        cls.devis = Devis.objects.create(
            reference='DEV-WIZ-01', client=client, chantier='Chantier Wizard',
            status='accepted', created_by=cls.admin,
        )
        LigneDevis.objects.create(
            devis=cls.devis, type_ligne='MO', description='MO',
            quantite=Decimal('4'), cout_unitaire=Decimal('82.50'),
        )
        # Devis non accepté → ne doit pas apparaître
        cls.devis_brouillon = Devis.objects.create(
            reference='DEV-WIZ-02', client=client,
            status='draft', created_by=cls.admin,
        )
        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='Complet', ordre=0)
        cls.aff = Affectation.objects.create(
            equipe=cls.equipe, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 4),  # 4 j ouvrés
            created_by=cls.admin,
        )

    def test_refuse_sans_acces(self):
        self.client.login(username='tech_wiz', password='pw')
        resp = self.client.get(reverse('core:planning-wizard-data'))
        self.assertEqual(resp.status_code, 403)

    def test_payload_complet(self):
        self.client.login(username='adm_wiz', password='pw')
        resp = self.client.get(reverse('core:planning-wizard-data'))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])

        pks = [d['pk'] for d in data['devis']]
        self.assertIn(self.devis.pk, pks)
        self.assertNotIn(self.devis_brouillon.pk, pks)
        d = next(x for x in data['devis'] if x['pk'] == self.devis.pk)
        self.assertEqual(d['ref'], 'DEV-WIZ-01')
        self.assertEqual(d['client'], 'Client Wizard')
        self.assertIn(f'/devis/{self.devis.pk}/', d['url'])

        # MO total = 4 × 82,50 = 330 € ; MO planifié = 4 j × 1 éq × 82,5
        self.assertEqual(data['devis_mo'][str(self.devis.pk)], 330.0)
        self.assertEqual(data['mo_planifie'][str(self.devis.pk)], 330.0)

        tranches = data['tranches'][str(self.devis.pk)]
        self.assertEqual(len(tranches), 1)
        self.assertEqual(tranches[0]['nom'], 'Complet')
        self.assertEqual(tranches[0]['equipes'], [{'nom': 'WIZ-A'}])


class AidesBibliothequeTests(TestCase):
    """Bibliothèque d'aides/financements partagée : save → get → delete.
    (Le cas montant invalide est couvert par SecurityFixesTests.)"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('aide_user', password='pw')
        ProfilUtilisateur.objects.create(user=cls.user, role='technicien')

    def _save(self, **kw):
        payload = {'description': 'ANAH', 'type_ligne': 'FIN',
                   'montant_defaut': '1500', 'unite': 'forfait',
                   'organisme': 'ANAH'}
        payload.update(kw)
        return self.client.post(
            reverse('core:aides-save'),
            data=json.dumps(payload), content_type='application/json')

    def test_save_cree_aide(self):
        self.client.login(username='aide_user', password='pw')
        resp = self._save()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        aide = BibliothequeAides.objects.get(pk=body['aide']['id'])
        self.assertEqual(aide.description, 'ANAH')
        self.assertEqual(aide.montant_defaut, Decimal('1500'))
        self.assertEqual(aide.created_by, self.user)

    def test_save_description_vide_refuse(self):
        self.client.login(username='aide_user', password='pw')
        resp = self._save(description='   ')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BibliothequeAides.objects.count(), 0)

    def test_save_type_invalide_refuse(self):
        self.client.login(username='aide_user', password='pw')
        resp = self._save(type_ligne='ZZZ')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BibliothequeAides.objects.count(), 0)

    def test_get_retourne_aides(self):
        BibliothequeAides.objects.create(
            description='Région', type_ligne='FINX',
            organisme='Région Bretagne', created_by=self.user)
        self.client.login(username='aide_user', password='pw')
        data = self.client.get(reverse('core:aides-get')).json()
        self.assertEqual(len(data['aides']), 1)
        self.assertEqual(data['aides'][0]['organisme'], 'Région Bretagne')
        self.assertEqual(data['aides'][0]['type_ligne'], 'FINX')

    def test_delete_supprime_aide(self):
        aide = BibliothequeAides.objects.create(description='Temp', created_by=self.user)
        self.client.login(username='aide_user', password='pw')
        resp = self.client.post(reverse('core:aide-delete', args=[aide.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertFalse(BibliothequeAides.objects.filter(pk=aide.pk).exists())

    def test_delete_inexistant_404(self):
        self.client.login(username='aide_user', password='pw')
        resp = self.client.post(reverse('core:aide-delete', args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_api_exige_connexion(self):
        resp = self.client.get(reverse('core:aides-get'))
        self.assertNotEqual(resp.status_code, 200)  # redirection login


class ZoneFinancementTests(TestCase):
    """Persistance des drapeaux zone_financement / zone_financement_ext via
    lignes_save, contrôlée par round-trip lignes_get."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('zf_admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        client = Client.objects.create(nom='Client ZF')
        cls.devis = Devis.objects.create(
            reference='DEV-ZF-01', client=client,
            status='draft', created_by=cls.admin)

    def _save(self, payload):
        self.client.login(username='zf_admin', password='pw')
        return self.client.post(
            reverse('core:lignes-save', args=[self.devis.pk]),
            data=json.dumps(payload), content_type='application/json')

    def test_persistance_et_round_trip(self):
        resp = self._save({
            'lignes': [], 'zone_financement': True,
            'zone_financement_ext': True, 'fin_group_title': 'Aides mobilisées',
        })
        self.assertEqual(resp.status_code, 200)
        self.devis.refresh_from_db()
        self.assertTrue(self.devis.zone_financement)
        self.assertTrue(self.devis.zone_financement_ext)
        self.assertEqual(self.devis.fin_group_title, 'Aides mobilisées')

        data = self.client.get(
            reverse('core:lignes-get', args=[self.devis.pk])).json()
        self.assertTrue(data['zone_financement'])
        self.assertTrue(data['zone_financement_ext'])
        self.assertEqual(data['fin_group_title'], 'Aides mobilisées')

    def test_defaut_false_si_absent(self):
        # Un devis dont la zone a été activée puis le payload ne porte plus
        # les drapeaux → repassent à False (défaut de lignes_save).
        self.devis.zone_financement = True
        self.devis.zone_financement_ext = True
        self.devis.save()
        resp = self._save({'lignes': []})
        self.assertEqual(resp.status_code, 200)
        self.devis.refresh_from_db()
        self.assertFalse(self.devis.zone_financement)
        self.assertFalse(self.devis.zone_financement_ext)


class InsertionDashboardTests(TestCase):
    """Tableau de bord insertion : rendu, totaux MO/matériaux (mo_mat_lignes),
    filtres équipe et période, gating peut_acceder_planning."""

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Dashboard')
        service = Service.objects.create(
            territoire=terr, nom='Insertion Dashboard', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='DSH-A', actif=True)
        cls.eq_b = Equipe.objects.create(service=service, nom='DSH-B', actif=True)

        cls.admin = User.objects.create_user('adm_dsh', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.tech = User.objects.create_user('tech_dsh', password='pw')
        ProfilUtilisateur.objects.create(user=cls.tech, role='technicien')

        client = Client.objects.create(nom='Client DSH')
        cls.devis_a = Devis.objects.create(
            reference='DEV-DSH-A', client=client, chantier='Chantier A',
            status='accepted', equipe=cls.eq_a, created_by=cls.admin)
        cls.devis_b = Devis.objects.create(
            reference='DEV-DSH-B', client=client, chantier='Chantier B',
            status='accepted', equipe=cls.eq_b, created_by=cls.admin)

        # Facture équipe A : MO 10×46 = 460 €, MAT 1×180 = 180 €
        cls.fac_a = cls._facture(cls.devis_a, montant=Decimal('640'),
                                 mo=(Decimal('10'), Decimal('46')),
                                 mat=(Decimal('1'), Decimal('180')))
        # Facture équipe B : MO 5×46 = 230 €, MAT 1×100 = 100 €
        cls.fac_b = cls._facture(cls.devis_b, montant=Decimal('330'),
                                 mo=(Decimal('5'), Decimal('46')),
                                 mat=(Decimal('1'), Decimal('100')))

    @classmethod
    def _facture(cls, devis, montant, mo, mat):
        f = Facture.objects.create(
            type_doc='facture', status='validated', devis=devis,
            destinataire=devis.client.nom, montant=montant, created_by=cls.admin)
        # date_creation est auto_now_add → forcée en juin 2026 pour les filtres période.
        Facture.objects.filter(pk=f.pk).update(date_creation=date(2026, 6, 15))
        LigneFacture.objects.create(
            facture=f, type_ligne='MO', description='MO',
            quantite=mo[0], cout_unitaire=mo[1])
        LigneFacture.objects.create(
            facture=f, type_ligne='MAT', description='Matériaux',
            quantite=mat[0], cout_unitaire=mat[1])
        return f

    PERIODE = {'debut': '2026-06-01', 'fin': '2026-06-30'}

    def test_gating_redirige_sans_acces(self):
        self.client.login(username='tech_dsh', password='pw')
        resp = self.client.get(reverse('core:insertion-dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_totaux_mo_mat(self):
        self.client.login(username='adm_dsh', password='pw')
        resp = self.client.get(reverse('core:insertion-dashboard'), self.PERIODE)
        self.assertEqual(resp.status_code, 200)
        # A + B : MO = 460 + 230 = 690 ; MAT = 180 + 100 = 280 ; total = 640 + 330
        self.assertEqual(resp.context['tot_fac_mo'], Decimal('690'))
        self.assertEqual(resp.context['tot_fac_mat'], Decimal('280'))
        self.assertEqual(resp.context['tot_fac_total'], Decimal('970'))
        self.assertEqual(len(resp.context['factures']), 2)

    def test_filtre_equipe(self):
        self.client.login(username='adm_dsh', password='pw')
        resp = self.client.get(
            reverse('core:insertion-dashboard'),
            {**self.PERIODE, 'eq': self.eq_a.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['factures']), 1)
        self.assertEqual(resp.context['tot_fac_mo'], Decimal('460'))
        self.assertEqual(resp.context['tot_fac_mat'], Decimal('180'))

    def test_filtre_periode_exclut_hors_borne(self):
        self.client.login(username='adm_dsh', password='pw')
        resp = self.client.get(
            reverse('core:insertion-dashboard'),
            {'debut': '2026-07-01', 'fin': '2026-07-31'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['factures']), 0)
        self.assertEqual(resp.context['tot_fac_mo'], 0)


class AffectationMoveTests(TestCase):
    """affectation_move : resize avec redistribution du MO restant aux autres
    affectations de la tranche (multi-équipes), changement d'équipe, garde-fous."""

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Move')
        service = Service.objects.create(
            territoire=terr, nom='Insertion Move', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='MOV-A', actif=True, nb_equipiers=1)
        cls.eq_b = Equipe.objects.create(service=service, nom='MOV-B', actif=True, nb_equipiers=1)
        cls.eq_c = Equipe.objects.create(service=service, nom='MOV-C', actif=True, nb_equipiers=1)

        cls.admin = User.objects.create_user('adm_mov', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.enc_a = User.objects.create_user('enc_a_mov', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()
        cls.enc_b = User.objects.create_user('enc_b_mov', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_b, role='technicien')
        cls.eq_b.encadrant = cls.enc_b
        cls.eq_b.save()

        client = Client.objects.create(nom='Client Move')
        cls.devis = Devis.objects.create(
            reference='DEV-MOV-01', client=client, chantier='Réhab Move',
            status='accepted', created_by=cls.admin)
        # Budget MO = 30 j × 82,50 € (à 1 équipier) → marge de redistribution large.
        LigneDevis.objects.create(
            devis=cls.devis, type_ligne='FMO', description='MO',
            quantite=Decimal('30'), cout_unitaire=Decimal('82.50'))

        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='Complet', ordre=0)
        cls.aff_a = Affectation.objects.create(
            equipe=cls.eq_a, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5), created_by=cls.admin)
        cls.aff_b = Affectation.objects.create(
            equipe=cls.eq_b, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5), created_by=cls.admin)

    def _move(self, aff, debut, fin, username='adm_mov', **extra):
        self.client.login(username=username, password='pw')
        payload = {'aff_id': aff.pk, 'date_debut': debut, 'date_fin': fin}
        payload.update(extra)
        return self.client.post(
            reverse('core:affectation-move'),
            data=json.dumps(payload), content_type='application/json')

    def test_resize_redistribue_aux_autres(self):
        # aff_a courte → MO restant élevé → aff_b s'allonge ;
        # aff_a longue → MO restant faible → aff_b se raccourcit.
        self._move(self.aff_a, '2026-06-01', '2026-06-02')   # 2 j ouvrés
        self.aff_b.refresh_from_db()
        fin_courte_a = self.aff_b.date_fin

        resp = self._move(self.aff_a, '2026-06-01', '2026-06-26')  # ~18 j ouvrés
        self.aff_b.refresh_from_db()
        fin_longue_a = self.aff_b.date_fin

        self.assertGreater(fin_courte_a, fin_longue_a)
        # La réponse renvoie l'affectation déplacée + celle recalculée.
        updated_ids = {u['aff_id'] for u in resp.json()['updated']}
        self.assertIn(self.aff_a.pk, updated_ids)
        self.assertIn(self.aff_b.pk, updated_ids)

    def test_changement_equipe(self):
        resp = self._move(self.aff_a, '2026-06-01', '2026-06-05',
                          equipe_id=self.eq_c.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.aff_a.refresh_from_db()
        self.assertEqual(self.aff_a.equipe_id, self.eq_c.pk)

    def test_changement_equipe_doublon_refuse(self):
        # eq_b porte déjà cette tranche (aff_b) → conflit.
        resp = self._move(self.aff_a, '2026-06-01', '2026-06-05',
                          equipe_id=self.eq_b.pk)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['ok'])
        self.assertIn('déjà assigné', body['error'])

    def test_non_encadrant_refuse(self):
        resp = self._move(self.aff_a, '2026-06-01', '2026-06-05', username='enc_b_mov')
        self.assertEqual(resp.status_code, 403)

    def test_affectation_introuvable_404(self):
        self.client.login(username='adm_mov', password='pw')
        resp = self.client.post(
            reverse('core:affectation-move'),
            data=json.dumps({'aff_id': 999999, 'date_debut': '2026-06-01',
                             'date_fin': '2026-06-05'}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)

    def test_dates_invalides_400(self):
        resp = self._move(self.aff_a, 'pas-une-date', '2026-06-05')
        self.assertEqual(resp.status_code, 400)

    def test_fin_avant_debut_400(self):
        resp = self._move(self.aff_a, '2026-06-10', '2026-06-01')
        self.assertEqual(resp.status_code, 400)


class VendrediToggleTests(TestCase):
    """vendredi_toggle : bascule le drapeau vendredi_actif (encadrant requis)."""

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Vendredi')
        service = Service.objects.create(
            territoire=terr, nom='Insertion Vendredi', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='VEN-A', actif=True)
        cls.eq_b = Equipe.objects.create(service=service, nom='VEN-B', actif=True)
        cls.enc_a = User.objects.create_user('enc_a_ven', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()
        cls.enc_b = User.objects.create_user('enc_b_ven', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_b, role='technicien')
        cls.eq_b.encadrant = cls.enc_b
        cls.eq_b.save()

        client = Client.objects.create(nom='Client Vendredi')
        cls.devis = Devis.objects.create(
            reference='DEV-VEN-01', client=client, status='accepted', created_by=cls.enc_a)
        LigneDevis.objects.create(
            devis=cls.devis, type_ligne='FMO', description='MO',
            quantite=Decimal('10'), cout_unitaire=Decimal('82.50'))
        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='Complet', ordre=0)
        cls.aff = Affectation.objects.create(
            equipe=cls.eq_a, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 5), created_by=cls.enc_a)

    def _toggle(self, aff_id, username='enc_a_ven'):
        self.client.login(username=username, password='pw')
        return self.client.post(
            reverse('core:vendredi-toggle'),
            data=json.dumps({'aff_id': aff_id}), content_type='application/json')

    def test_toggle_bascule(self):
        self.assertFalse(self.aff.vendredi_actif)
        resp = self._toggle(self.aff.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['actif'])
        self.aff.refresh_from_db()
        self.assertTrue(self.aff.vendredi_actif)
        # Re-bascule → False.
        resp = self._toggle(self.aff.pk)
        self.assertFalse(resp.json()['actif'])
        self.aff.refresh_from_db()
        self.assertFalse(self.aff.vendredi_actif)

    def test_non_encadrant_refuse(self):
        resp = self._toggle(self.aff.pk, username='enc_b_ven')
        self.assertEqual(resp.status_code, 403)
        self.aff.refresh_from_db()
        self.assertFalse(self.aff.vendredi_actif)

    def test_affectation_introuvable_404(self):
        resp = self._toggle(999999)
        self.assertEqual(resp.status_code, 404)


class TrancheCreerTests(TestCase):
    """tranche_creer : création d'une tranche sur un devis accepté, ordre
    incrémental, nom par défaut, garde-fous statut/permission."""

    @classmethod
    def setUpTestData(cls):
        terr    = Territoire.objects.create(nom='35-Tranche')
        service = Service.objects.create(
            territoire=terr, nom='Insertion Tranche', module_planning=True)
        cls.eq_a = Equipe.objects.create(service=service, nom='TRA-A', actif=True)
        cls.enc_a = User.objects.create_user('enc_a_tra', password='pw')
        ProfilUtilisateur.objects.create(user=cls.enc_a, role='technicien')
        cls.eq_a.encadrant = cls.enc_a
        cls.eq_a.save()
        # Technicien sans équipe → pas d'accès planning.
        cls.sans_acces = User.objects.create_user('tech_tra', password='pw')
        ProfilUtilisateur.objects.create(user=cls.sans_acces, role='technicien')

        client = Client.objects.create(nom='Client Tranche')
        cls.devis = Devis.objects.create(
            reference='DEV-TRA-01', client=client, status='accepted', created_by=cls.enc_a)
        cls.devis_brouillon = Devis.objects.create(
            reference='DEV-TRA-02', client=client, status='draft', created_by=cls.enc_a)

    def _creer(self, devis_id, nom=None, username='enc_a_tra'):
        self.client.login(username=username, password='pw')
        payload = {'devis_id': devis_id}
        if nom is not None:
            payload['nom'] = nom
        return self.client.post(
            reverse('core:tranche-creer'),
            data=json.dumps(payload), content_type='application/json')

    def test_creation_ordre_incremental(self):
        r1 = self._creer(self.devis.pk, nom='Phase 1')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['nom'], 'Phase 1')
        t1 = TrancheDevis.objects.get(pk=r1.json()['id'])
        self.assertEqual(t1.ordre, 1)

        r2 = self._creer(self.devis.pk, nom='Phase 2')
        t2 = TrancheDevis.objects.get(pk=r2.json()['id'])
        self.assertEqual(t2.ordre, 2)

    def test_nom_par_defaut(self):
        resp = self._creer(self.devis.pk, nom='   ')
        self.assertEqual(resp.json()['nom'], 'Nouvelle tranche')

    def test_devis_non_accepte_404(self):
        resp = self._creer(self.devis_brouillon.pk, nom='X')
        self.assertEqual(resp.status_code, 404)

    def test_sans_acces_planning_refuse(self):
        resp = self._creer(self.devis.pk, nom='X', username='tech_tra')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(TrancheDevis.objects.filter(devis=self.devis).exists())


class RangeesPonctuellesTests(TestCase):
    """
    Phase 3 — rangées ponctuelles : équipe temporaire (prêts + émargement),
    renfort (MO forfaitaire, sans émargement), prestataire (informatif, aucune MO).
    Vérifie la non-régression de la rentabilité des équipes permanentes.
    """

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='Ille-et-Vilaine')
        cls.service = Service.objects.create(
            territoire=terr, nom='Insertion Rangées', module_planning=True)
        # Équipe permanente + son chantier (base de rentabilité)
        cls.perm = Equipe.objects.create(service=cls.service, nom='65-SORM', nb_equipiers=4)
        cls.admin = User.objects.create_user('adm_rg', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin', service=cls.service)
        cls.perm.encadrant = cls.admin
        cls.perm.save()

        cls.client_obj = Client.objects.create(nom='Ville de Rennes')
        cls.devis = Devis.objects.create(
            reference='DEV-RG-001', client=cls.client_obj, chantier='École Guillevic',
            status='accepted', created_by=cls.admin,
        )
        cls.tranche = TrancheDevis.objects.create(devis=cls.devis, nom='T1', ordre=0)
        cls.aff_perm = Affectation.objects.create(
            equipe=cls.perm, tranche=cls.tranche,
            date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 12), created_by=cls.admin)
        cls.eq_perm = Equipier.objects.create(prenom='Habtom', nom='Tekie', equipe=cls.perm)
        # Une présence pour donner une base de pct_consomme / heures
        Presence.objects.create(
            equipier=cls.eq_perm, affectation=cls.aff_perm,
            date=date(2026, 6, 2), creneau='matin', heures=Decimal('4'))
        # Équipiers d'une autre équipe permanente, prêtables vers une temporaire
        cls.src = Equipe.objects.create(service=cls.service, nom='65-GORM', nb_equipiers=3)
        cls.lend1 = Equipier.objects.create(prenom='Amina', nom='Dawlatz', equipe=cls.src)
        cls.lend2 = Equipier.objects.create(prenom='Youssef', nom='Ben', equipe=cls.src)

    def _post_rangee(self, **payload):
        self.client.login(username='adm_rg', password='pw')
        return self.client.post(
            reverse('core:rangee-save'),
            data=json.dumps(payload), content_type='application/json')

    def _ligne(self, resp, equipe_pk):
        return next((l for l in resp.context['lignes'] if l['equipe'].pk == equipe_pk), None)

    # ── Temporaire : prêts + émargement + heures ──────────────
    def test_rangee_temporaire_emargement_et_heures(self):
        # Dates futures : une temporaire dont la date de fin est passée serait
        # archivée automatiquement (cf. test_rangee_temporaire_archivage_auto).
        today = timezone.localdate()
        lundi = today - timedelta(days=today.weekday()) + timedelta(weeks=2)
        fin = lundi + timedelta(days=4)
        resp = self._post_rangee(
            type_rangee='temporaire', nom='Renfort Plérin', devis_id=self.devis.pk,
            date_debut=lundi.isoformat(), date_fin=fin.isoformat(),
            equipier_ids=[self.lend1.pk, self.lend2.pk])
        self.assertTrue(resp.json()['ok'], resp.content)
        eq = Equipe.objects.get(pk=resp.json()['equipe_id'])
        self.assertEqual(eq.type_rangee, 'temporaire')
        self.assertEqual(eq.date_fin_temp, fin)
        # Les prêts ont été créés vers l'équipe temporaire
        self.assertEqual(Pret.objects.filter(equipe_hote=eq).count(), 2)
        # La temporaire a bien une grille d'émargement (équipiers prêtés visibles)
        em = self.client.get(reverse('core:emargement') + f'?equipe={eq.pk}&debut={lundi.isoformat()}')
        self.assertEqual(em.status_code, 200)
        self.assertIn(eq.pk, [e.pk for e in em.context['equipes']])
        self.assertContains(em, 'Amina')
        # Une présence pointée sur son affectation compte dans les heures de la tranche
        aff = Affectation.objects.get(equipe=eq)
        Presence.objects.create(
            equipier=self.lend1, affectation=aff,
            date=lundi, creneau='matin', heures=Decimal('4'))
        pl = self.client.get(reverse('core:planning') + f'?debut={lundi.isoformat()}')
        ligne = self._ligne(pl, eq.pk)
        self.assertIsNotNone(ligne)
        self.assertTrue(ligne['barres'][0]['has_presences'])

    # ── Renfort : barre €, pas d'émargement, pas de Presence ──
    def test_rangee_renfort_barre_sans_emargement(self):
        resp = self._post_rangee(
            type_rangee='renfort', nom='Renfort Espaces verts', devis_id=self.devis.pk,
            date_debut='2026-06-15', date_fin='2026-06-18', mo_forfait='1200')
        self.assertTrue(resp.json()['ok'], resp.content)
        eq = Equipe.objects.get(pk=resp.json()['equipe_id'])
        self.assertEqual(eq.type_rangee, 'renfort')
        self.assertEqual(eq.mo_forfait, Decimal('1200'))
        self.assertEqual(eq.nb_equipiers, 0)
        # Absent du sélecteur d'émargement
        em = self.client.get(reverse('core:emargement') + '?debut=2026-06-15')
        self.assertNotIn(eq.pk, [e.pk for e in em.context['equipes']])
        # Aucune présence créée
        self.assertFalse(Presence.objects.filter(affectation__equipe=eq).exists())
        # Présent sur le planning avec son type et son montant
        pl = self.client.get(reverse('core:planning') + '?debut=2026-06-15')
        ligne = self._ligne(pl, eq.pk)
        self.assertEqual(ligne['type_rangee'], 'renfort')
        self.assertEqual(ligne['mo_forfait'], Decimal('1200'))

    def test_rangee_renfort_montant_obligatoire(self):
        resp = self._post_rangee(
            type_rangee='renfort', nom='Sans montant', devis_id=self.devis.pk,
            date_debut='2026-06-15', date_fin='2026-06-18')
        self.assertFalse(resp.json()['ok'])

    # ── Prestataire : informatif, exclu émargement, aucune MO ──
    def test_rangee_prestataire_sans_mo(self):
        resp = self._post_rangee(
            type_rangee='prestataire', nom="Élec'Ouest", devis_id=self.devis.pk,
            date_debut='2026-06-15', date_fin='2026-06-17')
        self.assertTrue(resp.json()['ok'], resp.content)
        eq = Equipe.objects.get(pk=resp.json()['equipe_id'])
        self.assertEqual(eq.type_rangee, 'prestataire')
        self.assertIsNone(eq.mo_forfait)
        em = self.client.get(reverse('core:emargement') + '?debut=2026-06-15')
        self.assertNotIn(eq.pk, [e.pk for e in em.context['equipes']])
        pl = self.client.get(reverse('core:planning') + '?debut=2026-06-15')
        ligne = self._ligne(pl, eq.pk)
        self.assertEqual(ligne['type_rangee'], 'prestataire')
        # Barre informative : toujours en lecture seule (pas de poignées)
        self.assertFalse(ligne['peut_modifier'])

    # ── Non-régression : permanente inchangée ─────────────────
    def test_rentabilite_permanente_inchangee(self):
        self.client.login(username='adm_rg', password='pw')
        pl_avant = self.client.get(reverse('core:planning') + '?debut=2026-06-01')
        b_avant = self._ligne(pl_avant, self.perm.pk)['barres'][0]
        pct_avant, jours_avant = b_avant['pct_consomme'], b_avant['nb_jours']
        # Ajout des 3 rangées sur le même devis
        self._post_rangee(type_rangee='temporaire', nom='Temp', devis_id=self.devis.pk,
                          date_debut='2026-06-15', date_fin='2026-06-19',
                          equipier_ids=[self.lend1.pk])
        self._post_rangee(type_rangee='renfort', nom='Renf', devis_id=self.devis.pk,
                          date_debut='2026-06-15', date_fin='2026-06-18', mo_forfait='800')
        self._post_rangee(type_rangee='prestataire', nom='Prest', devis_id=self.devis.pk,
                          date_debut='2026-06-15', date_fin='2026-06-17')
        pl_apres = self.client.get(reverse('core:planning') + '?debut=2026-06-01')
        b_apres = self._ligne(pl_apres, self.perm.pk)['barres'][0]
        self.assertEqual(b_apres['pct_consomme'], pct_avant)
        self.assertEqual(b_apres['nb_jours'], jours_avant)

    # ── Archivage auto des temporaires échues ─────────────────
    def test_rangee_temporaire_archivage_auto(self):
        eq = Equipe.objects.create(
            service=self.service, nom='Temp échue', type_rangee='temporaire',
            date_fin_temp=date(2020, 1, 1))
        Affectation.objects.create(
            equipe=eq, tranche=self.tranche,
            date_debut=date(2020, 1, 1), date_fin=date(2020, 1, 3), created_by=self.admin)
        self.client.login(username='adm_rg', password='pw')
        pl = self.client.get(reverse('core:planning'))
        eq.refresh_from_db()
        self.assertTrue(eq.archivee)
        self.assertIsNone(self._ligne(pl, eq.pk))


# ─── Import devis PDF — OCR du descriptif ─────────────────────────────────────

_OCR_FIXTURE = (settings.BASE_DIR / 'docs' / 'exempledevis'
                / 'DE04026 ARASS Mobilier chambres - DPH.pdf')


def _ocr_fixture_available():
    """Vrai si le PDF d'exemple existe ET que Tesseract est utilisable."""
    try:
        from .import_pdf import _tesseract_available
        return _OCR_FIXTURE.exists() and _tesseract_available()
    except Exception:
        return False


class ImportDevisOcrTests(TestCase):
    """Import devis PDF : rattachement OCR ligne↔image + chemin de prévisualisation."""

    def test_assign_boxes_titres_alignes(self):
        from .import_pdf import _assign_boxes_to_rows
        # tops réels relevés sur DE04026 (ligne ↔ image alignées à ~2 px près)
        rows = [(420.0, '1'), (436.0, '1.1'), (503.0, '2')]
        boxes = [(418.0, 'A'), (434.0, 'B'), (500.0, 'C')]
        self.assertEqual(
            _assign_boxes_to_rows(rows, boxes, total_tops=[], tol=12),
            {'1': ['A'], '1.1': ['B'], '2': ['C']},
        )

    def test_assign_boxes_exclut_recapitulatifs(self):
        from .import_pdf import _assign_boxes_to_rows
        # l'image « TOTAL … » (top 475, ligne TOTAL en texte à 477) est écartée
        rows = [(436.0, '1.1'), (503.0, '2')]
        boxes = [(434.0, 'body'), (475.0, 'TOTAL'), (500.0, 'titre2')]
        assigned = _assign_boxes_to_rows(rows, boxes, total_tops=[477.0], tol=12)
        self.assertEqual(assigned, {'1.1': ['body'], '2': ['titre2']})

    def test_assign_boxes_corps_orphelin_rattache_au_dessus(self):
        """Un corps sans numéro (ex. NOTA) est rattaché à la ligne numérotée au-dessus."""
        from .import_pdf import _assign_boxes_to_rows
        rows = [(598.0, '3')]
        boxes = [(596.0, 'NOTA'), (612.0, 'corps'), (643.0, 'TOTALimg')]
        assigned = _assign_boxes_to_rows(rows, boxes, total_tops=[645.0], tol=12)
        # titre + corps rattachés à « 3 » (dans l'ordre vertical), récap écarté
        self.assertEqual(assigned, {'3': ['NOTA', 'corps']})

    def test_apply_descriptions_recursif(self):
        from .import_pdf import _apply_descriptions
        tree = [{'num': '1', 'label': '', 'children': [
                    {'num': '1.1', 'label': '', 'children': []}]}]
        _apply_descriptions(tree, {'1': 'Table de chevet', '1.1': 'Réalisation'})
        self.assertEqual(tree[0]['label'], 'Table de chevet')
        self.assertEqual(tree[0]['children'][0]['label'], 'Réalisation')

    def test_preview_depuis_results_json(self):
        """Chemin JS : devis déjà parsés postés → prévisualisation sans re-parser."""
        User.objects.create_user('imp_ocr', password='pw')
        self.client.login(username='imp_ocr', password='pw')
        parsed = {
            'reference': 'DE-TEST-1', 'date': None, 'date_validite': None,
            'objet': 'Réfection toiture', 'nb_lignes': 2,
            'client': {'nom': 'Mairie'}, 'chantier': {'nom': ''},
            'total_pdf': {'__decimal__': '1234.00'},
            'tree': [], 'errors': [], 'warnings': [],
        }
        payload = json.dumps([{'filename': 'DE-TEST-1.pdf', 'parsed': parsed}])
        resp = self.client.post(reverse('core:import-devis'),
                                {'equipe_id': '', 'results_json': payload})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DE-TEST-1')
        self.assertContains(resp, 'Réfection toiture')
        self.assertContains(resp, '1 234,00')

    def test_parse_amount_conserve_le_signe(self):
        from .import_pdf import _parse_amount
        self.assertEqual(_parse_amount('1 668,00'), Decimal('1668.00'))
        self.assertEqual(_parse_amount('-2 248,00'), Decimal('-2248.00'))
        self.assertEqual(_parse_amount('-900,00'), Decimal('-900.00'))
        self.assertEqual(_parse_amount('0,00'), Decimal('0'))

    def test_ecart_total_marque_objet(self):
        """Un écart total calculé vs PDF → marqueur dans l'objet (chantier) + note."""
        from .import_pdf import create_from_parsed
        terr = Territoire.objects.create(nom='Tc')
        serv = Service.objects.create(territoire=terr, nom='Sc')
        eq = Equipe.objects.create(service=serv, nom='Ec')
        user = User.objects.create_user('imp_ec', password='pw')
        parsed = {
            'reference': 'TST-ECART', 'objet': 'Mon chantier', 'date_validite': None,
            'client': {'nom': 'Client'}, 'chantier': {'nom': '', 'adresse': '', 'cp': '', 'ville': ''},
            'total_pdf': Decimal('50.00'),  # PDF annonce 50, lignes valent 100 → écart
            'tree': [{'num': '1', 'label': 'Ligne', 'children': [],
                      'qty_str': '1,00', 'unite': '', 'mat_str': '100,00',
                      'mo_str': '', 'desc_extra': ''}],
            'errors': [], 'warnings': [],
        }
        devis, warnings = create_from_parsed(parsed, eq, user)
        self.assertEqual(devis.total_brut(), Decimal('100.00'))
        self.assertTrue(devis.chantier.startswith('⚠ ÉCART'))
        self.assertIn('Mon chantier', devis.chantier)
        self.assertTrue(devis.notes)
        self.assertTrue(warnings)

    def test_ecart_un_centime_marque_objet(self):
        """Seuil = 0 : même un écart de 0,01 € est signalé (sommes identiques exigées)."""
        from .import_pdf import create_from_parsed
        terr = Territoire.objects.create(nom='Tc1')
        serv = Service.objects.create(territoire=terr, nom='Sc1')
        eq = Equipe.objects.create(service=serv, nom='Ec1')
        user = User.objects.create_user('imp_ec1', password='pw')
        parsed = {
            'reference': 'TST-CENT', 'objet': 'Chantier', 'date_validite': None,
            'client': {'nom': 'Client'}, 'chantier': {'nom': '', 'adresse': '', 'cp': '', 'ville': ''},
            'total_pdf': Decimal('100.00'),
            'tree': [{'num': '1', 'label': 'Ligne', 'children': [],
                      'qty_str': '1,00', 'unite': '', 'mat_str': '100,01',
                      'mo_str': '', 'desc_extra': ''}],
            'errors': [], 'warnings': [],
        }
        devis, _ = create_from_parsed(parsed, eq, user)
        self.assertTrue(devis.chantier.startswith('⚠ ÉCART'))

    @skipUnless(_ocr_fixture_available(), 'Tesseract+fra ou PDF exemple absent')
    def test_montant_negatif_soustrait_du_total(self):
        """Les financements négatifs (-2 248 €) viennent en soustraction (DE03065)."""
        from .import_pdf import parse_devis_pdf, create_from_parsed
        fixture = (settings.BASE_DIR / 'docs' / 'exempledevis'
                   / 'MURUGANANTHAN 2 - DE03065 - Plomb+Elec 655€.pdf')
        if not fixture.exists():
            self.skipTest('PDF DE03065 absent')
        terr = Territoire.objects.create(nom='Tn')
        serv = Service.objects.create(territoire=terr, nom='Sn')
        eq = Equipe.objects.create(service=serv, nom='En')
        user = User.objects.create_user('imp_neg', password='pw')
        parsed = parse_devis_pdf(str(fixture))
        self.assertEqual(parsed['total_pdf'], Decimal('655.00'))
        devis, warnings = create_from_parsed(parsed, eq, user)
        self.assertEqual(devis.total_brut().quantize(Decimal('0.01')), Decimal('655.00'))
        self.assertFalse(devis.chantier.startswith('⚠'))  # pas d'écart

    def test_ligne_ecart_marque_descriptif(self):
        """Une ligne dont le total calculé ≠ total EBP imprimé est marquée devant son descriptif."""
        from .import_pdf import create_from_parsed
        from .models import LigneDevis
        terr = Territoire.objects.create(nom='Tl')
        serv = Service.objects.create(territoire=terr, nom='Sl')
        eq = Equipe.objects.create(service=serv, nom='El')
        user = User.objects.create_user('imp_lg', password='pw')
        parsed = {
            'reference': 'TST-LIGNE', 'objet': 'Obj', 'date_validite': None,
            'client': {'nom': 'C'}, 'chantier': {'nom': '', 'adresse': '', 'cp': '', 'ville': ''},
            'total_pdf': Decimal('100.00'),
            'tree': [{'num': '1', 'label': 'Ma ligne', 'children': [],
                      'qty_str': '1,00', 'unite': '', 'mat_str': '100,00',
                      'mo_str': '', 'total_str': '105,00', 'desc_extra': ''}],
            'errors': [], 'warnings': [],
        }
        devis, _ = create_from_parsed(parsed, eq, user)
        s = LigneDevis.objects.filter(devis=devis, type_ligne='S').first()
        self.assertTrue(s.description.startswith('⚠ ÉCART'))
        self.assertIn('Total calculé = 100,00 €', s.description)
        self.assertIn('Montant EBP = 105,00 €', s.description)
        self.assertIn('Ma ligne', s.description)

    def test_import_page_affiche_barre_progression(self):
        """L'étape upload rend la barre de progression + le cap (template OK)."""
        User.objects.create_user('imp_pg', password='pw')
        self.client.login(username='imp_pg', password='pw')
        resp = self.client.get(reverse('core:import-devis'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="prog-box"')
        self.assertContains(resp, 'maximum 5 PDF')

    @skipUnless(_ocr_fixture_available(), 'Tesseract+fra ou PDF exemple absent')
    def test_parse_one_endpoint_ocr(self):
        """Endpoint un-PDF : JSON OK + descriptions dans l'arbre sérialisé."""
        User.objects.create_user('imp_one', password='pw')
        self.client.login(username='imp_one', password='pw')
        with open(_OCR_FIXTURE, 'rb') as fh:
            up = SimpleUploadedFile('DE04026.pdf', fh.read(),
                                    content_type='application/pdf')
        resp = self.client.post(reverse('core:import-devis-parse-one'), {'pdf': up})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['filename'], 'DE04026.pdf')
        labels = []

        def walk(nodes):
            for n in nodes:
                labels.append(n['label'])
                walk(n['children'])

        walk(data['parsed']['tree'])
        self.assertIn('Table de chevet', ' | '.join(labels))

    @skipUnless(_ocr_fixture_available(), 'Tesseract+fra ou PDF exemple absent')
    def test_parse_de04026_descriptions_ocr(self):
        """Bout en bout : les libellés du descriptif sont lus et rattachés."""
        from .import_pdf import parse_devis_pdf
        parsed = parse_devis_pdf(str(_OCR_FIXTURE))
        labels = []

        def walk(nodes):
            for n in nodes:
                labels.append(n['label'])
                walk(n['children'])

        walk(parsed['tree'])
        joined = ' | '.join(labels)
        self.assertIn('Table de chevet', joined)
        self.assertIn('Armoire', joined)
        self.assertEqual(parsed['warnings'], [])


# ─── Renumérotation des devis (bascule définitive) ────────────────────────────

class RenumeroterDevisTests(TestCase):
    """Commande renumeroter_devis : renumérote l'outil, exclut les imports, dry-run."""

    @classmethod
    def setUpTestData(cls):
        cls.client_obj = Client.objects.create(nom='X')
        cls.user = User.objects.create_user('renum', password='pw')

    def _devis(self, ref, importe=False):
        return Devis.objects.create(
            reference=ref, client=self.client_obj, chantier='C',
            created_by=self.user, importe_pdf=importe)

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        call_command('renumeroter_devis', *args, stdout=StringIO())

    def test_renumerote_outil_et_exclut_imports(self):
        d2 = self._devis('DEV-2026-002')
        d1 = self._devis('DEV-2026-001')
        imp = self._devis('DE04124', importe=True)
        Facture.objects.create(devis=d1, type_doc='facture', destinataire='X',
                               status='draft', created_by=self.user)
        self._run('--start', '4022', '--confirm')
        d1.refresh_from_db(); d2.refresh_from_db(); imp.refresh_from_db()
        self.assertEqual(d1.reference, 'DE04022')  # 001 traité avant 002
        self.assertEqual(d2.reference, 'DE04023')
        self.assertEqual(imp.reference, 'DE04124')  # import inchangé
        self.assertFalse(Facture.objects.filter(devis=d1).exists())

    def test_saute_numero_reserve_par_import(self):
        d1 = self._devis('DEV-2026-001')
        self._devis('DE04022', importe=True)  # occupe DE04022
        self._run('--start', '4022', '--confirm')
        d1.refresh_from_db()
        self.assertEqual(d1.reference, 'DE04023')

    def test_dry_run_ne_change_rien(self):
        d1 = self._devis('DEV-2026-001')
        f = Facture.objects.create(devis=d1, type_doc='facture', destinataire='X',
                                   status='draft', created_by=self.user)
        self._run('--start', '4022')  # pas de --confirm
        d1.refresh_from_db()
        self.assertEqual(d1.reference, 'DEV-2026-001')
        self.assertTrue(Facture.objects.filter(pk=f.pk).exists())


# ─── Import factures PDF (rattachement au devis) ──────────────────────────────

_FAC_FIXTURE = (settings.BASE_DIR / 'mockups' / 'ExempleFactures'
                / 'FA02913 Centre social Ty Blosne Bienvenue.pdf')


def _leaf(num, label, qty='1,00', unite='', mat='', mo='', total=''):
    return {'num': num, 'label': label, 'children': [],
            'qty_str': qty, 'unite': unite, 'mat_str': mat, 'mo_str': mo,
            'total_str': total, 'desc_extra': ''}


class ImportFacturesTests(TestCase):
    """Import factures PDF : rattachement au devis, statut, montant, blocages, droits."""

    @classmethod
    def setUpTestData(cls):
        terr = Territoire.objects.create(nom='T')
        serv = Service.objects.create(territoire=terr, nom='S')
        cls.equipe = Equipe.objects.create(service=serv, nom='E')
        cls.client_obj = Client.objects.create(nom='Mairie')
        cls.admin = User.objects.create_user('fa_admin', password='pw')
        ProfilUtilisateur.objects.create(user=cls.admin, role='admin')
        cls.tech = User.objects.create_user('fa_tech', password='pw')
        ProfilUtilisateur.objects.create(user=cls.tech, role='technicien')
        cls.devis = Devis.objects.create(
            reference='DE03967', client=cls.client_obj, chantier='Studio',
            equipe=cls.equipe, created_by=cls.admin)

    def _parsed(self, **over):
        base = {
            'reference': 'FA02913', 'reference_devis': 'DE03967',
            'date': date(2026, 1, 13), 'objet': 'Studio peinture',
            'client': {'nom': 'Association Bienvenue'}, 'chantier': {'nom': ''},
            'total_pdf': Decimal('252.40'),
            'tree': [_leaf('1', 'Peinture', qty='1,00', mat='252,40', total='252,40')],
            'errors': [], 'warnings': [],
        }
        base.update(over)
        return base

    # ── create_facture_from_parsed ───────────────────────────────────

    def test_create_lie_au_devis_statut_envoyee(self):
        from .import_facture_pdf import create_facture_from_parsed
        facture, warnings = create_facture_from_parsed(self._parsed(), self.devis, self.admin)
        self.assertEqual(facture.devis, self.devis)
        self.assertEqual(facture.type_doc, 'facture')
        self.assertEqual(facture.status, 'sent')
        self.assertEqual(facture.numero, 'FA02913')
        self.assertEqual(facture.montant, Decimal('252.40'))
        self.assertEqual(facture.date_creation, date(2026, 1, 13))
        self.assertFalse([w for w in warnings if 'Écart' in w])

    def test_montant_alimente_total_facture_du_devis(self):
        from .import_facture_pdf import create_facture_from_parsed
        create_facture_from_parsed(self._parsed(), self.devis, self.admin)
        self.assertEqual(self.devis.total_facture(), Decimal('252.40'))

    def test_ecart_total_ajoute_note(self):
        from .import_facture_pdf import create_facture_from_parsed
        # total_pdf annonce 300 mais les lignes valent 252,40 → note + montant = PDF
        facture, warnings = create_facture_from_parsed(
            self._parsed(total_pdf=Decimal('300.00')), self.devis, self.admin)
        self.assertEqual(facture.montant, Decimal('300.00'))
        self.assertIn('Écart', facture.notes)
        self.assertTrue([w for w in warnings if 'Écart' in w])

    def test_sections_alphanumeriques(self):
        """L'arbre accepte les sections « B / B.2 » des factures de situation."""
        from .import_facture_pdf import create_facture_from_parsed
        parsed = self._parsed(
            total_pdf=Decimal('100.00'),
            tree=[{'num': 'B', 'label': 'Lot B', 'desc_extra': '',
                   'qty_str': '', 'unite': '', 'mat_str': '', 'mo_str': '', 'total_str': '',
                   'children': [_leaf('B.2', 'Poste', mat='100,00', total='100,00')]}])
        facture, _ = create_facture_from_parsed(parsed, self.devis, self.admin)
        self.assertEqual(facture.montant, Decimal('100.00'))
        self.assertTrue(facture.lignes.filter(type_ligne='TITRE').exists())

    # ── Vue de confirmation (blocage / création / droits) ────────────

    def _post_confirm(self, parsed_list):
        payload = json.dumps(parsed_list)
        return self.client.post(reverse('core:import-factures-confirm'),
                                {'parsed_json': payload})

    def test_confirm_cree_et_lie(self):
        self.client.login(username='fa_admin', password='pw')
        parsed = self._parsed()
        parsed['total_pdf'] = {'__decimal__': '252.40'}
        parsed['date'] = {'__date__': '2026-01-13'}
        resp = self._post_confirm([parsed])
        self.assertEqual(resp.status_code, 302)
        f = Facture.objects.get(numero='FA02913')
        self.assertEqual(f.devis, self.devis)
        self.assertEqual(f.status, 'sent')

    def test_confirm_bloque_si_devis_absent(self):
        self.client.login(username='fa_admin', password='pw')
        parsed = self._parsed(reference='FA09999', reference_devis='DE99999')
        parsed['total_pdf'] = {'__decimal__': '252.40'}
        parsed['date'] = None
        resp = self._post_confirm([parsed])
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Facture.objects.filter(numero='FA09999').exists())
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any('introuvable' in m for m in msgs))

    def test_confirm_doublon_ignore(self):
        self.client.login(username='fa_admin', password='pw')
        Facture.objects.create(devis=self.devis, type_doc='facture', numero='FA02913',
                               destinataire='X', status='sent', created_by=self.admin)
        parsed = self._parsed()
        parsed['total_pdf'] = {'__decimal__': '252.40'}
        parsed['date'] = None
        self._post_confirm([parsed])
        self.assertEqual(Facture.objects.filter(numero='FA02913').count(), 1)

    def test_import_factures_reserve_admin(self):
        # Technicien : 403 ; admin : 200
        self.client.login(username='fa_tech', password='pw')
        self.assertEqual(self.client.get(reverse('core:import-factures')).status_code, 403)
        self.client.login(username='fa_admin', password='pw')
        self.assertEqual(self.client.get(reverse('core:import-factures')).status_code, 200)

    def test_lien_import_visible_admin_seulement(self):
        self.client.login(username='fa_tech', password='pw')
        self.assertNotContains(self.client.get(reverse('core:factures-list')),
                               reverse('core:import-factures'))
        self.client.login(username='fa_admin', password='pw')
        self.assertContains(self.client.get(reverse('core:factures-list')),
                            reverse('core:import-factures'))

    @skipUnless(_FAC_FIXTURE.exists(), 'PDF exemple FA02913 absent')
    def test_parse_exemple_extrait_reference_devis(self):
        from .import_facture_pdf import parse_facture_pdf
        parsed = parse_facture_pdf(str(_FAC_FIXTURE))
        self.assertEqual(parsed['reference'], 'FA02913')
        self.assertEqual(parsed['reference_devis'], 'DE03967')
        self.assertEqual(parsed['total_pdf'], Decimal('394.48'))
        self.assertEqual(parsed['date'], date(2026, 1, 13))
