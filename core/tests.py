import json
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.contrib.auth.models import User

from datetime import date
from decimal import Decimal

from .models import (
    Territoire, Service, Equipe, ProfilUtilisateur,
    Client, ContactClient, Devis, LigneDevis, Facture, LigneFacture,
    Equipier,
)
from .permissions import peut_acceder_planning, est_encadrant


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

    # ── Édition (admin uniquement) ───────────────────────────────────

    def test_client_edit_admin_ok(self):
        self.client.login(username='admin', password='pw')
        resp = self.client.post(
            reverse('core:client-edit', args=[self.cli_alice.pk]),
            {'nom': 'Mairie de Quimper', 'ville': 'Quimper Centre', 'code_postal': '29000'},
        )
        self.assertEqual(resp.status_code, 302)
        self.cli_alice.refresh_from_db()
        self.assertEqual(self.cli_alice.ville, 'Quimper Centre')

    def test_client_edit_refuse_non_admin(self):
        self.client.login(username='alice', password='pw')
        resp = self.client.post(
            reverse('core:client-edit', args=[self.cli_alice.pk]),
            {'nom': 'Piraté', 'ville': 'Nulle Part'},
        )
        self.assertEqual(resp.status_code, 302)
        self.cli_alice.refresh_from_db()
        self.assertEqual(self.cli_alice.nom, 'Mairie de Quimper')  # inchangé


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
        # Une facture de devis et une facture structure partagent la séquence FAC.
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
        self.assertEqual(fac_devis.numero, f'FAC-{self.year}-001')

        struct = self._struct()
        self.client.post(reverse('core:compta-facture-valider', args=[struct.pk]))
        struct.refresh_from_db()
        self.assertEqual(struct.numero, f'FAC-{self.year}-002')

    def test_appel_prefixe_app(self):
        appel = Facture.objects.create(
            type_doc='appel', devis=None, client=self.client_compta,
            destinataire='Mairie', created_by=self.compta, status='draft',
        )
        self.client.login(username='admin', password='pw')
        self.client.post(reverse('core:compta-facture-valider', args=[appel.pk]))
        appel.refresh_from_db()
        self.assertEqual(appel.numero, f'APP-{self.year}-001')

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
        self.assertEqual(avoir.numero, f'AV-{self.year}-001')

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
        from .models import BibliothèqueAides

        aide = BibliothèqueAides.objects.create(
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
        service = Service.objects.create(territoire=terr, nom='Insertion')
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
