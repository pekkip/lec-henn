import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from datetime import date

from .models import (
    Territoire, Service, Equipe, ProfilUtilisateur,
    Client, ContactClient, Devis, Facture, LigneFacture,
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
