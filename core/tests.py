import json

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from .models import (
    Territoire, Service, Equipe, ProfilUtilisateur,
    Client, Devis, Facture,
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
        self.client.login(username='alice', password='pw')
        resp = self.client.get(
            reverse('core:facture-bypass-send', args=[self.facture.pk])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertNotIn('code', data)


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
