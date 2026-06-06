"""
Jeu de données de démonstration pour peupler le tableau de bord.

SÉCURITÉ : tout ce qui est créé est **marqué** et **attribué à un seul
utilisateur** (par défaut le 1er admin). Rien n'est jamais supprimé en dehors de
ces données de démo :
  - Devis / Factures : marqueur ``SEED_DEMO`` dans le champ ``notes`` ;
  - Clients : nom préfixé ``DÉMO — `` ;
  - Équipiers : nom préfixé ``(D)`` et matricule préfixé ``(D)`` ;
  - Journal d'audit : action préfixée ``[DÉMO] ``.
Les équipes / services / territoires existants sont **réutilisés** (jamais
supprimés) ; créés seulement s'ils manquent.

Utilisation :
    python manage.py seed_demo                  # crée la démo pour le 1er admin
    python manage.py seed_demo --user alice      # attribue à un login précis
    python manage.py seed_demo --per-team 4      # nb de devis par équipe (défaut 3)
    python manage.py seed_demo --clear           # supprime UNIQUEMENT la démo de cet utilisateur

Le seed efface d'abord sa propre démo (idempotent) puis recrée un jeu cohérent
réparti sur ~6 mois et sur les équipes d'Ille-et-Vilaine :
  - 65-GORM / 61-GOSM : maçonnerie pierre, enduits, rejointoiement chaux (remparts) ;
  - 65-SORM / AQRM A / AQRM B / 58-AQSM : rénovation (peinture, cloison, menuiserie, sols PVC) ;
  - Bricobus rural : sécurisation électrique & plomberie ;
  - Bricobus urbain : petite rénovation de logement ;
  - ARA PO : isolation naturelle, réseaux, poêle à granulés ;
  - ARA LOC : petits chantiers de rénovation.
Équipiers démo créés pour les 6 équipes d'insertion (préfixe ``(D)``).
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Client, Territoire, Service, Equipe, Devis, LigneDevis, Facture,
    ProfilUtilisateur, AuditLog, BibliothèqueAides, Equipier,
)

MARKER = 'SEED_DEMO'
CLIENT_PREFIX = 'DÉMO — '
AUDIT_PREFIX = '[DÉMO] '
TAUX = 46

R = random.Random()


# ══════════════════════════════════════════
#  RECETTES D'ARTICLES (variées : titres, composites, simples, forfaits)
# ══════════════════════════════════════════
# Format des nœuds :
#   conteneur : (type, description, [enfants])           → TITRE / C / S
#   feuille    : (type, description, quantite, unite, pu) → MO / MAT / F / FMO / FMAT / FIN

def rcp_walls():
    """Maçonnerie pierre, enduits, rejointoiement chaux (remparts)."""
    return [
        ('TITRE', 'Installation de chantier', [
            ('F', 'Installation, échafaudage et protection', 1, 'forfait', R.randint(900, 1600)),
        ]),
        ('TITRE', 'Maçonnerie en pierre', [
            ('C', 'Reprise de maçonnerie en pierre de taille', [
                ('MO', "Main d'œuvre maçon", R.randint(45, 80), 'h', TAUX),
                ('MAT', 'Pierre de taille (granit)', R.randint(8, 16), 'u', R.randint(120, 160)),
                ('MAT', 'Mortier de chaux NHL 3.5', R.randint(10, 20), 'sac', R.randint(28, 38)),
            ]),
            ('S', 'Rejointoiement à la chaux', [
                ('MO', "Main d'œuvre", R.randint(30, 55), 'h', TAUX),
                ('MAT', 'Chaux aérienne + sable', R.randint(15, 25), 'sac', R.randint(22, 30)),
            ]),
        ]),
        ('TITRE', 'Enduits à la chaux', [
            ('FMO', "Application d'enduit à la chaux", R.randint(70, 110), 'm²', R.randint(18, 26)),
            ('FMAT', 'Fourniture chaux + sable', R.randint(70, 110), 'm²', R.randint(7, 12)),
        ]),
    ]


def rcp_reno():
    """Rénovation : peinture, cloison, menuiserie int., sols PVC (lés + clips)."""
    return [
        ('TITRE', 'Peinture', [
            ('S', 'Peinture murs et plafonds (2 couches)', [
                ('MO', "Main d'œuvre peintre", R.randint(25, 45), 'h', TAUX),
                ('MAT', 'Peinture acrylique mate', R.randint(12, 22), 'pot', R.randint(28, 40)),
            ]),
            ('F', 'Préparation et protection des supports', 1, 'forfait', R.randint(350, 650)),
        ]),
        ('TITRE', 'Cloisonnement & menuiserie intérieure', [
            ('C', 'Cloison placo BA13 + isolation', [
                ('MO', "Main d'œuvre", R.randint(20, 40), 'h', TAUX),
                ('MAT', 'Plaques BA13 + rails', R.randint(30, 55), 'm²', R.randint(15, 22)),
                ('MAT', 'Isolant laine de bois', R.randint(30, 55), 'm²', R.randint(10, 16)),
            ]),
            ('S', 'Pose de blocs-portes intérieurs', [
                ('MO', 'Pose menuiserie', R.randint(8, 18), 'h', TAUX),
                ('MAT', 'Bloc-porte alvéolaire', R.randint(2, 5), 'u', R.randint(150, 210)),
            ]),
        ]),
        ('TITRE', 'Agencement & revêtement de sol', [
            ('F', 'Ragréage et préparation du sol', 1, 'forfait', R.randint(400, 800)),
            ('S', 'Revêtement de sol PVC en lés', [
                ('MO', 'Pose PVC en lés', R.randint(12, 22), 'h', TAUX),
                ('MAT', 'PVC en lés', R.randint(35, 60), 'm²', R.randint(18, 26)),
            ]),
            ('S', 'Revêtement de sol PVC à clipser', [
                ('MO', 'Pose PVC à clipser', R.randint(10, 20), 'h', TAUX),
                ('MAT', 'Lames PVC clipsables', R.randint(25, 45), 'm²', R.randint(24, 32)),
            ]),
            ('FMAT', 'Plinthes et finitions', R.randint(60, 100), 'ml', R.randint(3, 6)),
        ]),
    ]


def rcp_bricobus_rural():
    """Sécurisation électrique et plomberie."""
    return [
        ('TITRE', 'Sécurisation électrique', [
            ('S', 'Remplacement du tableau électrique', [
                ('MO', "Main d'œuvre électricien", R.randint(8, 16), 'h', TAUX),
                ('MAT', 'Tableau + disjoncteurs', 1, 'u', R.randint(280, 480)),
            ]),
            ('S', 'Mise à la terre et différentiel', [
                ('MO', "Main d'œuvre", R.randint(5, 10), 'h', TAUX),
                ('MAT', 'Piquet de terre + différentiel', 1, 'u', R.randint(120, 220)),
            ]),
            ('F', 'Diagnostic et sécurisation des prises', 1, 'forfait', R.randint(150, 300)),
        ]),
        ('TITRE', 'Plomberie', [
            ('S', 'Remplacement de robinetterie', [
                ('MO', "Main d'œuvre plombier", R.randint(4, 9), 'h', TAUX),
                ('MAT', 'Mitigeurs', R.randint(1, 3), 'u', R.randint(60, 120)),
            ]),
            ('F', 'Réparation de fuite et purge du réseau', 1, 'forfait', R.randint(120, 260)),
        ]),
    ]


def rcp_bricobus_urbain():
    """Petite rénovation : papier peint (1 mur), peinture plafond, meubles cuisine."""
    return [
        ('TITRE', 'Embellissement', [
            ('S', 'Pose de papier peint (un mur)', [
                ('MO', 'Pose papier peint', R.randint(4, 8), 'h', TAUX),
                ('MAT', 'Papier peint + colle', R.randint(3, 6), 'rouleau', R.randint(20, 40)),
            ]),
            ('S', 'Réfection peinture plafond', [
                ('MO', 'Peinture plafond', R.randint(4, 9), 'h', TAUX),
                ('MAT', 'Peinture plafond', R.randint(2, 4), 'pot', R.randint(25, 38)),
            ]),
        ]),
        ('TITRE', 'Cuisine', [
            ('F', 'Dépose et évacuation des meubles existants', 1, 'forfait', R.randint(150, 300)),
            ('C', 'Remplacement de meubles de cuisine', [
                ('MO', 'Pose de meubles', R.randint(6, 14), 'h', TAUX),
                ('MAT', 'Meubles bas et hauts', R.randint(3, 6), 'u', R.randint(120, 260)),
                ('MAT', 'Plan de travail stratifié', R.randint(2, 4), 'ml', R.randint(60, 110)),
            ]),
        ]),
    ]


def rcp_ara_po():
    """Isolation matériaux naturels, réseaux élec/plomberie, poêle à granulés."""
    return [
        ('TITRE', 'Isolation en matériaux naturels', [
            ('C', 'Isolation des combles en ouate de cellulose', [
                ('MO', "Main d'œuvre", R.randint(15, 30), 'h', TAUX),
                ('MAT', 'Ouate de cellulose', R.randint(40, 80), 'm²', R.randint(12, 20)),
            ]),
            ('S', 'Isolation des murs en fibre de bois', [
                ('MO', 'Pose isolant', R.randint(18, 32), 'h', TAUX),
                ('MAT', 'Panneaux fibre de bois', R.randint(30, 60), 'm²', R.randint(18, 28)),
            ]),
        ]),
        ('TITRE', 'Réseaux', [
            ('S', 'Création du réseau électrique', [
                ('MO', 'Électricien', R.randint(20, 40), 'h', TAUX),
                ('MAT', 'Câblage, gaines et tableau', 1, 'ens', R.randint(450, 900)),
            ]),
            ('S', 'Création du réseau de plomberie', [
                ('MO', 'Plombier', R.randint(15, 30), 'h', TAUX),
                ('MAT', 'Tubes PER, raccords', 1, 'ens', R.randint(300, 650)),
            ]),
        ]),
        ('TITRE', 'Chauffage', [
            ('C', "Fourniture et pose d'un poêle à granulés", [
                ('MO', 'Installation', R.randint(8, 16), 'h', TAUX),
                ('MAT', 'Poêle à granulés', 1, 'u', R.randint(2200, 3600)),
                ('MAT', 'Conduit et tubage', 1, 'ens', R.randint(400, 800)),
            ]),
        ]),
    ]


def rcp_ara_loc():
    """Petits chantiers de rénovation (logement)."""
    return [
        ('TITRE', 'Rénovation', [
            ('S', 'Peinture séjour et chambre', [
                ('MO', 'Peinture', R.randint(12, 24), 'h', TAUX),
                ('MAT', 'Peinture + enduit', R.randint(4, 8), 'pot', R.randint(26, 40)),
            ]),
            ('S', 'Pose de sol stratifié', [
                ('MO', 'Pose', R.randint(8, 16), 'h', TAUX),
                ('MAT', 'Sol stratifié + sous-couche', R.randint(25, 45), 'm²', R.randint(14, 22)),
            ]),
            ('F', 'Petits travaux de menuiserie (portes, plinthes)', 1, 'forfait', R.randint(200, 450)),
        ]),
    ]


RECIPES = {
    'walls': rcp_walls, 'reno': rcp_reno,
    'bricobus_rural': rcp_bricobus_rural, 'bricobus_urbain': rcp_bricobus_urbain,
    'ara_po': rcp_ara_po, 'ara_loc': rcp_ara_loc,
}


# ── Clients de démo (clé → nom, type, CP, ville) ──────────────
CLIENT_DEFS = {
    'ville_rennes': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
    'ville_stmalo': ('Ville de Saint-Malo', 'collectivite', '35400', 'Saint-Malo'),
    'archipel': ('Archipel Habitat', 'bailleur', '35000', 'Rennes'),
    'neotoa': ('Néotoa', 'bailleur', '35000', 'Rennes'),
    'college_zola': ('Collège Émile Zola', 'collectivite', '35000', 'Rennes'),
    'rennes_metro': ('Rennes Métropole', 'collectivite', '35000', 'Rennes'),
    'emeraude': ('Émeraude Habitation', 'bailleur', '35400', 'Saint-Malo'),
    'mairie_sm': ('Mairie de Saint-Malo', 'collectivite', '35400', 'Saint-Malo'),
    'ecole_moulin': ('École Jean Moulin', 'collectivite', '35400', 'Saint-Malo'),
    # Particuliers (Bricobus / ARA)
    'p_urb1': ('M. et Mme Le Gall', 'particulier', '35000', 'Rennes'),
    'p_urb2': ('Mme Tanguy', 'particulier', '35200', 'Rennes'),
    'p_urb3': ('M. Riou', 'particulier', '35700', 'Rennes'),
    'p_rur1': ('M. et Mme Morvan', 'particulier', '35190', 'Tinténiac'),
    'p_rur2': ('Mme Guéguen', 'particulier', '35630', 'Hédé-Bazouges'),
    'p_rur3': ('M. Le Coz', 'particulier', '35270', 'Combourg'),
    'p_ara1': ('Mme Lucas', 'particulier', '35510', 'Cesson-Sévigné'),
    'p_ara2': ('M. et Mme Pérès', 'particulier', '35135', 'Chantepie'),
    'p_ara3': ('M. Renaud', 'particulier', '35740', 'Pacé'),
}

WALLS_RM = ['Restauration des remparts — courtine des Lices',
            'Rejointoiement à la chaux — Portes Mordelaises',
            "Réfection d'enduits chaux — mur d'enceinte gallo-romain",
            'Maçonnerie pierre — tour de la Visitation']
WALLS_SM = ['Remparts intra-muros — courtine Nord',
            'Maçonnerie pierre — Bastion Saint-Philippe',
            'Rejointoiement à la chaux — Tour Bidouane',
            "Réfection d'enduits — Grande Porte"]
RENO_CH = ['Réfection peinture & sols', 'Cloisonnement et aménagement',
           'Rénovation de salles de classe', 'Réhabilitation de logements',
           'Aménagement de bureaux']
BR_RURAL_CH = ['Sécurisation électrique et plomberie',
               'Mise en sécurité de l\'installation électrique',
               'Réparations plomberie et électricité']
BR_URBAIN_CH = ["Rafraîchissement d'un logement",
                'Petite rénovation (séjour + cuisine)',
                'Embellissement et meubles de cuisine']
ARA_PO_CH = ['Isolation et installation poêle à granulés',
             'Isolation naturelle + réseaux',
             'Auto-réhabilitation — isolation et chauffage']
ARA_LOC_CH = ['Petite rénovation de logement', 'Rafraîchissement locatif',
              'Rénovation logement (peinture + sols)']

# Aides / fonds existants (réutilisés s'ils existent — clé → description, organisme, type, montant)
AIDE_DEFS = {
    'anah': ('ANAH', 'ANAH', 'FMO', Decimal('2000.00')),
    'cbb': ('Fond CBB', 'CBB', 'FMAT', Decimal('50.00')),
    'schneider': ('Don matériel électrique', 'Schneider Electric', 'FMAT', None),
    'aubade': ('Dons sanitaires', 'Aubade', 'FMAT', None),
    'atlantic': ('Dons chauffages, plomberie', 'Atlantic', 'FMAT', None),
}
# Quels fonds pour quelles équipes (financement réservé aux autres équipes, pas l'insertion)
AIDE_POOL = {
    'bricobus_rural': ['schneider', 'aubade', 'cbb'],
    'bricobus_urbain': ['cbb', 'anah'],
    'ara_po': ['anah', 'atlantic', 'schneider', 'cbb'],
    'ara_loc': ['cbb', 'anah'],
}
# Montant de la ligne FIN quand l'aide n'a pas de montant par défaut (dons en nature)
FIN_FALLBACK = {
    'schneider': (150, 450), 'aubade': (120, 350), 'atlantic': (250, 650),
    'anah': (1500, 2500), 'cbb': (50, 200),
}

# Équipes : code, recette, service de repli (si à créer), chantiers, clients possibles
TEAMS = [
    ('65-GORM',  'walls',          'Insertion 35', WALLS_RM,  ['ville_rennes']),
    ('61-GOSM',  'walls',          'Insertion 35', WALLS_SM,  ['ville_stmalo']),
    ('65-SORM',  'reno',           'Insertion 35', RENO_CH,   ['archipel', 'neotoa', 'college_zola', 'rennes_metro']),
    ('AQRM A',   'reno',           'Insertion 35', RENO_CH,   ['archipel', 'neotoa', 'college_zola']),
    ('AQRM B',   'reno',           'Insertion 35', RENO_CH,   ['archipel', 'neotoa', 'college_zola']),
    ('58-AQSM',  'reno',           'Insertion 35', RENO_CH,   ['emeraude', 'mairie_sm', 'ecole_moulin']),
    ('Bricobus rural',  'bricobus_rural',  'Bricobus 35', BR_RURAL_CH,  ['p_rur1', 'p_rur2', 'p_rur3']),
    ('Bricobus urbain', 'bricobus_urbain', 'Bricobus 35', BR_URBAIN_CH, ['p_urb1', 'p_urb2', 'p_urb3']),
    ('ARA PO',  'ara_po',  'Habitat 35', ARA_PO_CH,  ['p_ara1', 'p_ara2', 'p_ara3']),
    ('ARA LOC', 'ara_loc', 'Habitat 35', ARA_LOC_CH, ['p_ara1', 'p_ara2', 'p_ara3']),
]

# Équipiers démo pour les 6 équipes d'insertion (prénoms/noms bretons fictifs).
# Marqueur : nom préfixé '(D)', matricule préfixé '(D)'.
EQUIP_DEMO = {
    '65-GORM': [
        ('Corentin', 'LE BERRE'),  ('Erwann', 'KERMARREC'), ('Loïc', 'CADIOU'),
        ('Maël', 'KERGUERIS'),     ('Tifenn', 'QUENTEL'),   ('Yann', 'GUILLOU'),
        ('Noé', 'HERVE'),          ('Aziliz', 'CALVEZ'),
    ],
    '61-GOSM': [
        ('Goulven', 'QUERE'),      ('Tugdual', 'BODENNEC'), ('Brendan', 'MORVAN'),
        ('Soizic', 'JAOUEN'),      ('Fanch', 'RIOU'),       ('Gurvan', 'MARC'),
        ('Bleunvenn', 'CARRE'),    ('Malo', 'THOMAS'),
    ],
    '65-SORM': [
        ('Rozenn', 'GUYADER'),     ('Yuna', 'PENNARUN'),    ('Talig', 'EVEN'),
        ('Naig', 'CROZON'),        ('Loeiz', 'PRIGENT'),    ('Gwenola', 'JARNO'),
    ],
    'AQRM A': [
        ('Gwenael', 'OLLIVIER'),   ('Mikael', 'KERGUELEN'), ('Perig', 'BOUDIC'),
        ('Denez', 'PLOUZANE'),     ('Enora', 'TANGUY'),
    ],
    'AQRM B': [
        ('Riwanon', 'ROPARS'),     ('Efflam', 'STEPHAN'),   ('Naig', 'DERIEN'),
        ('Gaetan', 'KERIVEL'),     ('Sterenn', 'PEREZ'),
    ],
    '58-AQSM': [
        ('Alan', 'TREBAOL'),       ('Breval', 'SALAUN'),    ('Katell', 'LARVOR'),
        ('Nolwenn', 'GLOAGUEN'),   ('Yannig', 'KERVELLA'),
    ],
}


class Command(BaseCommand):
    help = ("Crée (ou supprime avec --clear) un jeu de données de démonstration, "
            "marqué SEED_DEMO et attribué à un seul utilisateur. Sans danger pour "
            "les vraies données.")

    def add_arguments(self, parser):
        parser.add_argument('--user', dest='username', default=None,
                            help="Login de l'utilisateur cible (défaut : 1er admin).")
        parser.add_argument('--per-team', dest='per_team', type=int, default=3,
                            help="Nombre de devis par équipe (défaut 3).")
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

        self._seed(user, max(1, opts['per_team']))

    def _seed_equipiers(self):
        """Crée les équipiers démo (idempotent via matricule). Ne recrée pas si déjà présents."""
        for code, personnes in EQUIP_DEMO.items():
            equipe = Equipe.objects.filter(nom__icontains=code).first()
            if equipe is None:
                continue
            for i, (prenom, nom) in enumerate(personnes, start=1):
                matricule = f'(D){code}-{i:02d}'
                Equipier.objects.get_or_create(
                    matricule=matricule,
                    defaults=dict(
                        prenom=prenom,
                        nom=f'(D){nom}',
                        equipe=equipe,
                        type_contrat='CDDI - 26 heures',
                        actif=True,
                    ),
                )

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
        f = Facture.objects.filter(created_by=user, notes__contains=MARKER)
        total += f.count(); f.delete()
        d = Devis.objects.filter(created_by=user, notes__contains=MARKER)
        total += d.count(); d.delete()
        c = (Client.objects.filter(created_by=user, nom__startswith=CLIENT_PREFIX)
             .filter(devis__isnull=True))
        total += c.count(); c.delete()
        a = AuditLog.objects.filter(user=user, action__startswith=AUDIT_PREFIX)
        total += a.count(); a.delete()
        eq = Equipier.objects.filter(matricule__startswith='(D)')
        total += eq.count(); eq.delete()
        return total

    # ── Résolution d'équipe (réutilise l'existant) ────────────
    def _team(self, code, service_fallback):
        e = Equipe.objects.filter(nom__icontains=code).first()
        if e:
            return e
        terr, _ = Territoire.objects.get_or_create(nom='Ille-et-Vilaine')
        svc, _ = Service.objects.get_or_create(territoire=terr, nom=service_fallback)
        return Equipe.objects.create(service=svc, nom=code)

    # ── Création ──────────────────────────────────────────────
    def _seed(self, user, per_team):
        now = timezone.now()
        today = now.date()
        client_cache = {}
        seq = {'fac': 0, 'av': 0}
        accepted = []
        n_devis = 0

        aides = self._aides(user)
        for code, recipe_key, svc_fallback, chantiers, client_keys in TEAMS:
            equipe = self._team(code, svc_fallback)
            aide_pool = AIDE_POOL.get(recipe_key)   # None pour les équipes insertion
            for j in range(per_team):
                n_devis += 1
                cli = self._client(user, client_cache, R.choice(client_keys))
                chantier = R.choice(chantiers)
                nodes = RECIPES[recipe_key]()

                status = R.choices(
                    ['accepted', 'sent', 'draft', 'refused'],
                    weights=[50, 20, 22, 8])[0]
                d = Devis.objects.create(
                    reference=f'DEMO-D-{n_devis:03d}',
                    client=cli, equipe=equipe, chantier=f'{chantier} — {cli.ville}',
                    chantier_ville=cli.ville, chantier_cp=cli.code_postal,
                    status=status, taux_mo=Decimal(TAUX),
                    zone_financement=bool(aide_pool), created_by=user, notes=MARKER,
                )
                self._build(d, None, nodes)

                # Frais de déplacement (< 20 km) — ligne forfait NORMALE (pas un
                # financement, pas en zone financement) : 1-2 devis insertion.
                if (code == '65-GORM' and j == 0) or (code == '65-SORM' and j == 0):
                    LigneDevis.objects.create(
                        devis=d, parent=None, type_ligne='F',
                        description='Frais de déplacement (< 20 km)',
                        quantite=1, unite='forfait',
                        cout_unitaire=Decimal(R.randint(60, 150)), ordre=800)

                # Financements — fonds existants, réservés aux autres équipes (Bricobus / ARA).
                if aide_pool:
                    for o, key in enumerate(R.sample(aide_pool, R.randint(1, min(2, len(aide_pool))))):
                        aide = aides[key]
                        amount = aide.montant_defaut or Decimal(R.randint(*FIN_FALLBACK[key]))
                        LigneDevis.objects.create(
                            devis=d, parent=None, type_ligne='FIN',
                            description=aide.description, quantite=1, unite='forfait',
                            cout_unitaire=amount, ordre=900 + o, aide=aide)

                created = today - timedelta(days=R.randint(0, 180))
                Devis.objects.filter(pk=d.pk).update(date_creation=created)
                if status == 'accepted':
                    accepted.append(d)
                self._audit(user, f"Création du devis {d.reference} ({equipe.nom})", devis=d)

        # Équipiers démo pour les 6 équipes d'insertion (nom préfixé '(D)').
        self._seed_equipiers()

        # Factures sur les devis acceptés : à valider / validées / envoyées / payées.
        cycle = ['draft', 'validated', 'sent', 'paid']
        validated_facture = None
        for i, d in enumerate(accepted):
            brut = d.total_brut() or Decimal('5000')
            for k in range(R.randint(1, 2)):
                st = cycle[(i + k) % len(cycle)]
                montant = (Decimal(brut) * (Decimal('0.5') if k else Decimal('0.6'))
                           ).quantize(Decimal('0.01'))
                numero = validated_by = validated_at = None
                if st != 'draft':
                    seq['fac'] += 1
                    numero = f'DEMO-F-{seq["fac"]:04d}'
                    validated_by, validated_at = user, now
                ech = today + timedelta(days=R.choice([-25, -8, 14, 30, 45]))
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
            Facture.objects.create(
                devis=validated_facture.devis, type_doc='avoir',
                destinataire=validated_facture.destinataire,
                montant=-(validated_facture.montant / Decimal(4)).quantize(Decimal('0.01')),
                status='validated', numero=f'DEMO-AV-{seq["av"]:03d}',
                facture_origine=validated_facture, created_by=user, notes=MARKER,
                validated_by=user, validated_at=now,
            )

        # Quelques factures compta (structure + appel de convention).
        rennes = self._client(user, client_cache, 'ville_rennes')
        metro = self._client(user, client_cache, 'rennes_metro')
        seq['fac'] += 1
        Facture.objects.create(
            type_doc='structure', client=rennes, destinataire=str(rennes),
            montant=Decimal('6400.00'), status='validated',
            numero=f'DEMO-F-{seq["fac"]:04d}', created_by=user, notes=MARKER,
            validated_by=user, validated_at=now,
        )
        Facture.objects.create(
            type_doc='appel', client=metro, destinataire=str(metro),
            montant=Decimal('2300.00'), status='draft',
            created_by=user, notes=MARKER,
        )

        nd = Devis.objects.filter(created_by=user, notes__contains=MARKER).count()
        nf = Facture.objects.filter(created_by=user, notes__contains=MARKER).count()
        nc = Client.objects.filter(created_by=user, nom__startswith=CLIENT_PREFIX).count()
        self.stdout.write(self.style.SUCCESS(
            f"Démo créée pour « {user.username} » : {nd} devis, {nf} factures/avoirs, "
            f"{nc} clients, sur {len(TEAMS)} équipes. "
            f"Tout est marqué SEED_DEMO — retirable avec : manage.py seed_demo --clear"))

    # ── Helpers ───────────────────────────────────────────────
    def _aides(self, user):
        """Réutilise les aides/fonds existants (par description + organisme) ;
        les crée s'ils manquent (utile en dev). Non supprimées par --clear."""
        out = {}
        for key, (desc, org, typ, montant) in AIDE_DEFS.items():
            aide, _ = BibliothèqueAides.objects.get_or_create(
                description=desc, organisme=org,
                defaults={'type_ligne': typ, 'montant_defaut': montant,
                          'unite': 'forfait', 'created_by': user})
            out[key] = aide
        return out

    def _client(self, user, cache, key):
        if key in cache:
            return cache[key]
        nom, typ, cp, ville = CLIENT_DEFS[key]
        cli = Client.objects.create(
            nom=CLIENT_PREFIX + nom, type_client=typ,
            code_postal=cp, ville=ville, created_by=user,
        )
        cache[key] = cli
        return cli

    def _build(self, devis, parent, nodes):
        """Crée récursivement l'arbre de lignes à partir des nœuds de recette."""
        for ordre, node in enumerate(nodes):
            if len(node) == 3:  # conteneur (TITRE / C / S) avec enfants
                type_ligne, desc, enfants = node
                ligne = LigneDevis.objects.create(
                    devis=devis, parent=parent, type_ligne=type_ligne,
                    description=desc, quantite=1, ordre=ordre,
                )
                self._build(devis, ligne, enfants)
            else:  # feuille (MO / MAT / F / FMO / FMAT / FIN)
                type_ligne, desc, qte, unite, pu = node
                LigneDevis.objects.create(
                    devis=devis, parent=parent, type_ligne=type_ligne,
                    description=desc, quantite=Decimal(str(qte)), unite=unite,
                    cout_unitaire=Decimal(str(pu)), ordre=ordre,
                )

    def _audit(self, user, action, devis=None, facture=None):
        AuditLog.objects.create(
            user=user, action=AUDIT_PREFIX + action, devis=devis, facture=facture,
        )
