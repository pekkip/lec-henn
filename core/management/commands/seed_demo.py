"""
Jeu de données de démonstration pour peupler le tableau de bord.

SÉCURITÉ : tout ce qui est créé est **marqué** et **attribué à un seul
utilisateur** (par défaut le 1er admin). Rien n'est jamais supprimé en dehors de
ces données de démo :
  - Devis / Factures : marqueur ``SEED_DEMO`` dans le champ ``notes`` ;
  - Clients : nom préfixé ``DÉMO — `` ;
  - Journal d'audit : action préfixée ``[DÉMO] ``.

Utilisation :
    python manage.py seed_demo                 # crée la démo pour le 1er admin
    python manage.py seed_demo --user alice     # attribue à un login précis
    python manage.py seed_demo --clear          # supprime UNIQUEMENT la démo de cet utilisateur

Le seed efface d'abord sa propre démo (idempotent) puis recrée un jeu cohérent :
devis en cours, factures à valider / validées / envoyées / payées, un avoir,
et quelques factures compta.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Client, Devis, LigneDevis, Facture, ProfilUtilisateur, AuditLog,
)

MARKER = 'SEED_DEMO'
CLIENT_PREFIX = 'DÉMO — '
AUDIT_PREFIX = '[DÉMO] '


class Command(BaseCommand):
    help = ("Crée (ou supprime avec --clear) un jeu de données de démonstration, "
            "marqué SEED_DEMO et attribué à un seul utilisateur. Sans danger pour "
            "les vraies données.")

    def add_arguments(self, parser):
        parser.add_argument('--user', dest='username', default=None,
                            help="Login de l'utilisateur cible (défaut : 1er admin).")
        parser.add_argument('--clear', action='store_true',
                            help="Supprime uniquement les données SEED_DEMO de cet utilisateur.")

    # ── Entrée ────────────────────────────────────────────────
    def handle(self, *args, **opts):
        user = self._resolve_user(opts['username'])
        if not user:
            self.stderr.write(self.style.ERROR(
                "Aucun utilisateur cible trouvé (préciser --user <login>)."))
            return

        n = self._clear(user)
        if opts['clear']:
            self.stdout.write(self.style.SUCCESS(
                f"Démo supprimée pour « {user.username} » : {n} objet(s) retiré(s)."))
            return

        self._seed(user)

    def _resolve_user(self, username):
        if username:
            return User.objects.filter(username=username).first()
        admin = (ProfilUtilisateur.objects.filter(role='admin')
                 .select_related('user').first())
        if admin:
            return admin.user
        return User.objects.filter(is_superuser=True).first() or User.objects.first()

    # ── Suppression ciblée (jamais globale) ───────────────────
    def _clear(self, user):
        total = 0
        # Factures (avoirs inclus) d'abord — devis est protégé (PROTECT).
        f = Facture.objects.filter(created_by=user, notes__contains=MARKER)
        total += f.count(); f.delete()
        d = Devis.objects.filter(created_by=user, notes__contains=MARKER)
        total += d.count(); d.delete()
        # Clients de démo désormais sans devis rattaché.
        c = (Client.objects.filter(created_by=user, nom__startswith=CLIENT_PREFIX)
             .filter(devis__isnull=True))
        total += c.count(); c.delete()
        a = AuditLog.objects.filter(user=user, action__startswith=AUDIT_PREFIX)
        total += a.count(); a.delete()
        return total

    # ── Création ──────────────────────────────────────────────
    def _seed(self, user):
        now = timezone.now()
        today = now.date()

        clients = self._make_clients(user)
        seq = {'fac': 0, 'av': 0}

        # 8 devis répartis sur plusieurs statuts/mois.
        plan = [
            ('accepted', 3),   # acceptés → CA + factures
            ('sent', 2),       # envoyés (en cours)
            ('draft', 2),      # brouillons (en cours)
            ('refused', 1),    # refusé
        ]
        idx = 0
        accepted = []
        for status, count in plan:
            for _ in range(count):
                idx += 1
                cli = random.choice(clients)
                montant = Decimal(random.choice([3500, 7200, 12500, 4800, 9100, 15400]))
                d = Devis.objects.create(
                    reference=f'DEMO-D-{idx:03d}',
                    client=cli, chantier=self._chantier(cli),
                    status=status, taux_mo=Decimal('46.00'),
                    created_by=user, notes=MARKER,
                )
                self._make_lignes(d, montant)
                # Étale la date sur ~6 mois pour le graphique CA mensuel.
                created = today - timedelta(days=random.randint(0, 175))
                Devis.objects.filter(pk=d.pk).update(date_creation=created)
                if status == 'accepted':
                    accepted.append(d)
                self._audit(user, f"Création du devis {d.reference}", devis=d)

        # Factures sur les devis acceptés : à valider / validées / envoyées / payées.
        statuses = ['draft', 'validated', 'sent', 'paid']
        validated_facture = None
        for i, d in enumerate(accepted):
            brut = d.total_brut() or Decimal('5000')
            # 1 à 2 factures par devis accepté.
            for j in range(random.randint(1, 2)):
                st = statuses[(i + j) % len(statuses)]
                montant = (Decimal(brut) / Decimal(2)).quantize(Decimal('0.01')) \
                    if j == 0 else (Decimal(brut) / Decimal(2)).quantize(Decimal('0.01'))
                numero = None
                validated_by = validated_at = None
                if st != 'draft':
                    seq['fac'] += 1
                    numero = f'DEMO-F-{seq["fac"]:04d}'
                    validated_by, validated_at = user, now
                ech = today + timedelta(days=random.choice([-20, -5, 15, 30]))
                f = Facture.objects.create(
                    devis=d, type_doc='facture', destinataire=str(d.client),
                    montant=montant, status=st, numero=numero,
                    date_echeance=ech, created_by=user, notes=MARKER,
                    validated_by=validated_by, validated_at=validated_at,
                )
                if st in ('validated', 'sent', 'paid') and validated_facture is None:
                    validated_facture = f
                self._audit(user, f"Facture {f.get_reference()} ({st})", facture=f, devis=d)

        # Un avoir sur une facture validée.
        if validated_facture:
            seq['av'] += 1
            av = Facture.objects.create(
                devis=validated_facture.devis, type_doc='avoir',
                destinataire=validated_facture.destinataire,
                montant=-(validated_facture.montant / Decimal(4)).quantize(Decimal('0.01')),
                status='validated', numero=f'DEMO-AV-{seq["av"]:03d}',
                facture_origine=validated_facture, created_by=user, notes=MARKER,
                validated_by=user, validated_at=now,
            )
            self._audit(user, f"Avoir {av.get_reference()}", facture=av)

        # Quelques factures compta (structure + appel de convention).
        cli = clients[0]
        fs = Facture.objects.create(
            type_doc='structure', client=cli, destinataire=str(cli),
            montant=Decimal('6400.00'), status='validated',
            numero=f'DEMO-F-{(seq["fac"] + 1):04d}', created_by=user, notes=MARKER,
            validated_by=user, validated_at=now,
        )
        self._audit(user, f"Facture structure {fs.get_reference()}", facture=fs)
        fa = Facture.objects.create(
            type_doc='appel', client=clients[1], destinataire=str(clients[1]),
            montant=Decimal('2300.00'), status='draft',
            created_by=user, notes=MARKER,
        )
        self._audit(user, f"Appel de convention {fa.get_reference()} (à valider)", facture=fa)

        # Résumé.
        self.stdout.write(self.style.SUCCESS(
            f"Démo créée pour « {user.username} » : "
            f"{Devis.objects.filter(created_by=user, notes__contains=MARKER).count()} devis, "
            f"{Facture.objects.filter(created_by=user, notes__contains=MARKER).count()} factures/avoirs, "
            f"{len(clients)} clients. "
            f"Tout est marqué SEED_DEMO — retirable avec : manage.py seed_demo --clear"))

    # ── Helpers de contenu ────────────────────────────────────
    def _make_clients(self, user):
        data = [
            ('Mairie de Plouézec', 'collectivite', '22470', 'Plouézec'),
            ('Habitat 29', 'bailleur', '29200', 'Brest'),
            ('Asso Ti Solidaire', 'association', '35000', 'Rennes'),
            ('Communauté de communes Aulne-Mer', 'collectivite', '29150', 'Châteaulin'),
        ]
        clients = []
        for nom, typ, cp, ville in data:
            clients.append(Client.objects.create(
                nom=CLIENT_PREFIX + nom, type_client=typ,
                code_postal=cp, ville=ville, created_by=user,
            ))
        return clients

    def _chantier(self, cli):
        libelles = ['Rénovation logement', 'Isolation combles',
                    'Réfection toiture', 'Auto-réhabilitation accompagnée',
                    'Chantier participatif', 'Mise aux normes électriques']
        return f"{random.choice(libelles)} — {cli.ville}"

    def _make_lignes(self, devis, montant_cible):
        """Crée un titre avec 2 lignes (MO + MAT) totalisant ~montant_cible."""
        titre = LigneDevis.objects.create(
            devis=devis, parent=None, type_ligne='TITRE',
            description='Travaux', quantite=1, ordre=0,
        )
        mo = (montant_cible * Decimal('0.6')).quantize(Decimal('0.01'))
        mat = (montant_cible - mo).quantize(Decimal('0.01'))
        LigneDevis.objects.create(
            devis=devis, parent=titre, type_ligne='MO',
            description="Main d'œuvre", quantite=1, cout_unitaire=mo, ordre=0,
        )
        LigneDevis.objects.create(
            devis=devis, parent=titre, type_ligne='MAT',
            description='Matériaux', quantite=1, cout_unitaire=mat, ordre=1,
        )

    def _audit(self, user, action, devis=None, facture=None):
        AuditLog.objects.create(
            user=user, action=AUDIT_PREFIX + action, devis=devis, facture=facture,
        )
