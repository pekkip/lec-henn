"""
Données de démonstration pour les 6 équipes Insertion 35 — Jan–Mai 2026.

Crée pour chaque équipe :
  - 2 devis acceptés (ref préfixée DEMO35-, chantier préfixé [Démo])
  - 1 TrancheDevis + 1 Affectation par devis
  - Présences Jan–Mai 2026 avec variété d'avancement (40–130 %)
  - Factures validées jusqu'à fin mai 2026

Marqueurs :
  - Devis  : reference startswith 'DEMO35-', chantier startswith '[Démo]'
  - Factures : libelle startswith '[Démo]', notes = 'SEED_DEMO35'

Utilisation :
    python manage.py seed_production_demo
    python manage.py seed_production_demo --clear
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Client, Equipe, Equipier, Devis, LigneDevis, TrancheDevis,
    Affectation, Presence, Facture,
)

MARKER = 'SEED_DEMO35'
EQUIPES_35 = ['55-AQRM A', '55-AQRM B', '58-AQSM', '61-GOSM', '65-GORM', '65-SORM']
TAUX_HO = Decimal('47')   # €/h MO insertion

R = random.Random(2026)   # seed stable → résultats reproductibles


# ══════════════════════════════════════════
#  RECETTES DE DEVIS (structures variées)
# ══════════════════════════════════════════

def rcp_peinture_mobilier():
    """AQRM A — Peinture, mobilier panneaux, dépose sélective, cloisonnement."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'Dépose sélective et protection', [
            ('S', 'Dépose de menuiseries et évacuation', [
                ('MO', "Main d'œuvre dépose", h(8, 18), 'h', TAUX_HO),
                ('F', 'Location benne 8m³', 1, 'forfait', R.randint(250, 450)),
            ]),
            ('F', 'Protection des sols et ouvertures', 1, 'forfait', R.randint(180, 360)),
        ]),
        ('TITRE', 'Peinture', [
            ('S', 'Préparation des supports (rebouchage, ponçage)', [
                ('MO', "Main d'œuvre peintre", h(12, 22), 'h', TAUX_HO),
                ('MAT', 'Enduit de rebouchage', h(10, 20), 'kg', R.randint(4, 8)),
            ]),
            ('S', 'Application peinture 2 couches (murs + plafonds)', [
                ('MO', "Main d'œuvre", h(25, 55), 'h', TAUX_HO),
                ('MAT', 'Peinture acrylique mate A+', h(15, 30), 'pot', R.randint(28, 42)),
            ]),
        ]),
        ('TITRE', 'Mobilier et agencement', [
            ('C', 'Fabrication et pose de meubles en panneaux mélaminés', [
                ('MO', "Main d'œuvre menuiserie", h(20, 45), 'h', TAUX_HO),
                ('MAT', 'Panneaux mélaminés 16 mm', h(15, 30), 'm²', R.randint(22, 34)),
                ('MAT', 'Quincaillerie et fixations', 1, 'forfait', R.randint(120, 280)),
            ]),
            ('S', "Pose d'étagères et rangements sur mesure", [
                ('MO', "Main d'œuvre", h(8, 16), 'h', TAUX_HO),
                ('MAT', 'Contreplaqué bouleau 18 mm', h(8, 14), 'm²', R.randint(28, 40)),
            ]),
        ]),
        ('TITRE', 'Cloisonnement', [
            ('C', 'Cloison placo BA13', [
                ('MO', "Main d'œuvre plaquiste", h(14, 28), 'h', TAUX_HO),
                ('MAT', 'Plaques BA13 + rail + montant', h(20, 40), 'm²', R.randint(16, 24)),
            ]),
        ]),
    ]


def rcp_peinture_sols():
    """AQRM B — Peinture et revêtement de sol PVC, cloisonnement."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'Peinture', [
            ('F', 'Préparation et protection des supports', 1, 'forfait', R.randint(250, 450)),
            ('S', 'Peinture murs (2 couches)', [
                ('MO', "Main d'œuvre peintre", h(20, 45), 'h', TAUX_HO),
                ('MAT', 'Peinture acrylique satin', h(12, 24), 'pot', R.randint(26, 40)),
            ]),
            ('S', 'Peinture plafonds (1 couche primaire + 1 couche finition)', [
                ('MO', "Main d'œuvre", h(10, 22), 'h', TAUX_HO),
                ('MAT', 'Peinture plafond blanche', h(6, 14), 'pot', R.randint(24, 36)),
            ]),
        ]),
        ('TITRE', 'Revêtement de sol PVC', [
            ('S', 'Ragréage et préparation du sol', [
                ('MO', "Main d'œuvre", h(6, 14), 'h', TAUX_HO),
                ('MAT', 'Ragréage autonivelant', h(20, 45), 'kg', R.randint(3, 6)),
            ]),
            ('S', 'Pose PVC en lés (dalles ou rouleaux)', [
                ('MO', 'Pose PVC', h(14, 28), 'h', TAUX_HO),
                ('MAT', 'PVC lés (épaisseur 2 mm)', h(40, 80), 'm²', R.randint(16, 26)),
                ('MAT', 'Colle à sol et plinthes PVC', h(40, 80), 'ml', R.randint(2, 5)),
            ]),
        ]),
        ('TITRE', 'Cloisonnement léger', [
            ('C', 'Cloison amovible placo BA13', [
                ('MO', "Main d'œuvre", h(10, 20), 'h', TAUX_HO),
                ('MAT', 'Plaques BA13 + ossature', h(15, 30), 'm²', R.randint(16, 24)),
            ]),
        ]),
    ]


def rcp_peinture_sorm():
    """SORM — Peinture (essentiel), mobilier léger, cloisonnement."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'Peinture intérieure', [
            ('S', 'Préparation des supports (lessivage, rebouchage)', [
                ('MO', "Main d'œuvre", h(10, 20), 'h', TAUX_HO),
                ('MAT', 'Produit de nettoyage et enduit', 1, 'forfait', R.randint(80, 160)),
            ]),
            ('S', 'Application peinture bi-couche murs', [
                ('MO', "Main d'œuvre peintre", h(28, 60), 'h', TAUX_HO),
                ('MAT', 'Peinture acrylique A+ (couleur au choix)', h(14, 28), 'pot', R.randint(28, 44)),
            ]),
            ('FMO', 'Reprise de peinture plafonds et huisseries', h(60, 120), 'm²', R.randint(6, 11)),
        ]),
        ('TITRE', 'Mobilier léger', [
            ('S', 'Fabrication et pose étagères murales', [
                ('MO', "Main d'œuvre", h(8, 18), 'h', TAUX_HO),
                ('MAT', 'Panneaux mélaminés + fixations', 1, 'forfait', R.randint(180, 380)),
            ]),
            ('F', "Pose d'un miroir et d'un tableau d'affichage", 1, 'forfait', R.randint(80, 180)),
        ]),
        ('TITRE', 'Cloisonnement', [
            ('C', 'Cloison BA13 + isolation phonique', [
                ('MO', "Main d'œuvre plaquiste", h(12, 24), 'h', TAUX_HO),
                ('MAT', 'Plaques BA13 + rail + isolant', h(18, 35), 'm²', R.randint(20, 30)),
            ]),
        ]),
    ]


def rcp_maconnerie_gorm():
    """GORM — Maçonnerie traditionnelle (enduit chaux, pierre, terre). MO élevé."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'Installation de chantier', [
            ('F', 'Échafaudage, protection, signalétique', 1, 'forfait', R.randint(800, 1800)),
        ]),
        ('TITRE', 'Maçonnerie en pierre', [
            ('C', 'Reprise de maçonnerie en moellons de granit', [
                ('MO', "Main d'œuvre maçon", h(80, 160), 'h', TAUX_HO),
                ('MAT', 'Moellons de granit (calibrés)', h(1000, 2500), 'kg', Decimal('0.28')),
                ('MAT', 'Sable de carrière', h(2, 5), 'T', R.randint(38, 62)),
            ]),
            ('S', 'Rejointoiement au mortier de chaux', [
                ('MO', "Main d'œuvre", h(50, 100), 'h', TAUX_HO),
                ('MAT', 'Chaux NHL 3.5', h(20, 40), 'sac', R.randint(24, 36)),
                ('MAT', 'Sable fin de rivière', h(1, 3), 'T', R.randint(38, 55)),
            ]),
        ]),
        ('TITRE', 'Enduits à la chaux', [
            ('FMO', "Application d'enduit de corps à la chaux aérienne", h(80, 160), 'm²', R.randint(18, 26)),
            ('FMO', 'Enduit de finition taloché fin', h(80, 160), 'm²', R.randint(12, 18)),
            ('FMAT', 'Fourniture chaux aérienne + sable de dune', h(80, 160), 'm²', R.randint(8, 14)),
        ]),
        ('TITRE', 'Maçonnerie en terre', [
            ('S', 'Bouchage de vides et ragréage adobe', [
                ('MO', "Main d'œuvre", h(20, 40), 'h', TAUX_HO),
                ('MAT', 'Terre argileuse préparée', h(200, 500), 'kg', Decimal('0.12')),
            ]),
        ]),
    ]


def rcp_peinture_bailleur():
    """AQSM — Peinture et rénovation logements bailleurs sociaux."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'État des lieux et protection', [
            ('F', 'Relevé contradictoire, protection des sols et mobilier', 1, 'forfait', R.randint(150, 300)),
        ]),
        ('TITRE', 'Peinture', [
            ('S', 'Peinture murs séjour + chambres (2 couches)', [
                ('MO', "Main d'œuvre peintre", h(22, 50), 'h', TAUX_HO),
                ('MAT', 'Peinture acrylique lavable A+', h(12, 25), 'pot', R.randint(28, 42)),
            ]),
            ('S', 'Peinture plafonds et huisseries', [
                ('MO', "Main d'œuvre", h(10, 22), 'h', TAUX_HO),
                ('MAT', 'Peinture plafond + laque huisseries', 1, 'forfait', R.randint(120, 260)),
            ]),
            ('F', 'Impression primaire sur supports neufs', 1, 'forfait', R.randint(120, 240)),
        ]),
        ('TITRE', 'Rénovation salle de bain', [
            ('C', 'Carrelage mural partiel (crédence + derrière vasque)', [
                ('MO', "Main d'œuvre carreleur", h(8, 18), 'h', TAUX_HO),
                ('MAT', 'Carrelage 20×20 + joint', h(4, 10), 'm²', R.randint(18, 34)),
            ]),
        ]),
        ('TITRE', 'Pose de sols PVC', [
            ('S', 'Revêtement sol PVC lés (toutes pièces)', [
                ('MO', 'Pose PVC', h(12, 24), 'h', TAUX_HO),
                ('MAT', 'PVC lés 2 mm qualité bailleur', h(35, 70), 'm²', R.randint(14, 22)),
                ('MAT', 'Plinthes et profils de seuil', 1, 'forfait', R.randint(80, 180)),
            ]),
        ]),
    ]


def rcp_maconnerie_gosm():
    """GOSM — Maçonnerie pierre traditionnelle (remparts, façades). MO très élevé."""
    h = lambda a, b: R.randint(a, b)
    return [
        ('TITRE', 'Préparation de chantier', [
            ('F', 'Échafaudage de pied ou suspendu, protection, signalétique', 1, 'forfait', R.randint(1200, 2800)),
        ]),
        ('TITRE', 'Maçonnerie de pierre de taille (granite)', [
            ('C', 'Remplacement de pierres dégradées (taille + pose)', [
                ('MO', "Main d'œuvre tailleur de pierre", h(100, 200), 'h', TAUX_HO),
                ('MAT', 'Granite bleu Kersanton (sur mesure)', h(3, 8), 'u', R.randint(380, 680)),
            ]),
            ('S', 'Rejointoiement à la chaux naturelle NHL 5', [
                ('MO', "Main d'œuvre", h(60, 120), 'h', TAUX_HO),
                ('MAT', 'Chaux NHL 5 + sable de carrière', h(25, 50), 'sac', R.randint(28, 42)),
            ]),
            ('C', "Reconstitution d'assises effondrées", [
                ('MO', "Main d'œuvre", h(40, 80), 'h', TAUX_HO),
                ('MAT', 'Moellons + mortier de chaux', 1, 'forfait', R.randint(600, 1400)),
            ]),
        ]),
        ('TITRE', 'Enduits de finition', [
            ('FMO', 'Enduit corps chaux aérienne (1er passage)', h(60, 120), 'm²', R.randint(20, 28)),
            ('FMO', 'Enduit de finition chaux (tiré au couteau)', h(60, 120), 'm²', R.randint(16, 22)),
            ('FMAT', 'Fourniture chaux + sable + adjuvants', h(60, 120), 'm²', R.randint(10, 16)),
        ]),
    ]


RECIPES = {
    '55-AQRM A': rcp_peinture_mobilier,
    '55-AQRM B': rcp_peinture_sols,
    '58-AQSM':   rcp_peinture_bailleur,
    '61-GOSM':   rcp_maconnerie_gosm,
    '65-GORM':   rcp_maconnerie_gorm,
    '65-SORM':   rcp_peinture_sorm,
}


# ══════════════════════════════════════════
#  CHANTIERS PAR ÉQUIPE
#  factor = taux de réalisation cible (jours d'équipe travaillés / jours facturables)
#  Variété : 40–130 %
# ══════════════════════════════════════════

# Slot : (date_debut, date_fin_affectation)
# facture_mois  : (year, month) de validation de la facture (None = pas encore facturé)
# facture_ratio : part du total_brut facturée

CHANTIERS = {
    '55-AQRM A': [
        {
            'ref_suffix': 'AQRMA-01',
            'nom': 'Rénovation des bureaux — Service Social CD35',
            'client': ('Conseil Départemental d\'Ille-et-Vilaine', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 1, 5), date(2026, 3, 27)),
            'factor': 0.82,                        # termine un peu en avance
            'facture_mois': (2026, 3),
            'facture_ratio': Decimal('0.70'),
        },
        {
            'ref_suffix': 'AQRMA-02',
            'nom': 'Aménagement salle de réunion — Mairie de Rennes',
            'client': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 4, 6), date(2026, 6, 30)),    # actif en juin
            'factor': 1.05,                        # léger dépassement
            'facture_mois': (2026, 5),
            'facture_ratio': Decimal('0.45'),
        },
    ],
    '55-AQRM B': [
        {
            'ref_suffix': 'AQRMB-01',
            'nom': 'Réfection appartements famille — CD35',
            'client': ('Conseil Départemental d\'Ille-et-Vilaine', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 1, 12), date(2026, 4, 10)),
            'factor': 1.20,                        # dépassement net
            'facture_mois': (2026, 3),
            'facture_ratio': Decimal('0.60'),
        },
        {
            'ref_suffix': 'AQRMB-02',
            'nom': 'Local associatif — Quartier Villejean',
            'client': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 4, 13), date(2026, 6, 30)),   # actif en juin
            'factor': 0.70,                        # en retard (40 % du mois)
            'facture_mois': (2026, 5),
            'facture_ratio': Decimal('0.40'),
        },
    ],
    '58-AQSM': [
        {
            'ref_suffix': 'AQSM-01',
            'nom': 'Résidence Duguay-Trouin — rénovation logements',
            'client': ('OPH Saint-Malo Emeraude', 'bailleur', '35400', 'Saint-Malo'),
            'slot': (date(2026, 2, 2), date(2026, 4, 24)),
            'factor': 0.95,                        # quasi dans les temps
            'facture_mois': (2026, 4),
            'facture_ratio': Decimal('0.65'),
        },
        {
            'ref_suffix': 'AQSM-02',
            'nom': 'Logements Paramé — rafraîchissement peinture',
            'client': ('OPH Saint-Malo Emeraude', 'bailleur', '35400', 'Saint-Malo'),
            'slot': (date(2026, 4, 27), date(2026, 6, 30)),   # actif en juin
            'factor': 1.10,                        # dépassement
            'facture_mois': (2026, 5),
            'facture_ratio': Decimal('0.50'),
        },
    ],
    '61-GOSM': [
        {
            'ref_suffix': 'GOSM-01',
            'nom': 'Remparts Saint-Malo — section Tour Bidouane',
            'client': ('Ville de Saint-Malo', 'collectivite', '35400', 'Saint-Malo'),
            'slot': (date(2026, 1, 19), date(2026, 4, 17)),
            'factor': 1.30,                        # gros dépassement (maçonnerie complexe)
            'facture_mois': (2026, 3),
            'facture_ratio': Decimal('0.55'),
        },
        {
            'ref_suffix': 'GOSM-02',
            'nom': 'Façade intra-muros — Rue de Dinan',
            'client': ('Ville de Saint-Malo', 'collectivite', '35400', 'Saint-Malo'),
            'slot': (date(2026, 4, 20), date(2026, 6, 30)),   # actif en juin
            'factor': 0.80,
            'facture_mois': (2026, 5),
            'facture_ratio': Decimal('0.45'),
        },
    ],
    '65-GORM': [
        {
            'ref_suffix': 'GORM-01',
            'nom': 'Mur du jardin du Thabor — rejointoiement chaux',
            'client': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 1, 5), date(2026, 3, 27)),
            'factor': 0.65,                        # en retard (météo)
            'facture_mois': (2026, 3),
            'facture_ratio': Decimal('0.50'),
        },
        {
            'ref_suffix': 'GORM-02',
            'nom': 'Façade école de Cesson-Sévigné — enduits chaux',
            'client': ('Conseil Départemental d\'Ille-et-Vilaine', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 3, 16), date(2026, 5, 29)),
            'factor': 1.15,                        # dépassement
            'facture_mois': (2026, 4),
            'facture_ratio': Decimal('0.60'),
        },
    ],
    '65-SORM': [
        {
            'ref_suffix': 'SORM-01',
            'nom': 'École Jean Moulin — peinture intérieure',
            'client': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 2, 16), date(2026, 5, 8)),
            'factor': 0.45,                        # très en retard (absentéisme élevé)
            'facture_mois': (2026, 4),
            'facture_ratio': Decimal('0.40'),
        },
        {
            'ref_suffix': 'SORM-02',
            'nom': 'Centre social Villejean — rénovation salles',
            'client': ('Ville de Rennes', 'collectivite', '35000', 'Rennes'),
            'slot': (date(2026, 3, 2), date(2026, 5, 22)),
            'factor': 1.00,                        # dans les temps
            'facture_mois': (2026, 5),
            'facture_ratio': Decimal('0.55'),
        },
    ],
}

# Codes d'absence et leur probabilité relative (somme = 1 pour la partie absence)
_ABSENCE_POOL = [('R', 12), ('M', 10), ('C', 8), ('PMSMP', 3), ('AJ', 1), ('AT', 1)]
_ABSENCE_CODES = [c for c, w in _ABSENCE_POOL for _ in range(w)]


def _working_days(d_start, d_end):
    """Jours ouvrés Lun–Jeu entre d_start et d_end inclus."""
    out, d = [], d_start
    while d <= d_end:
        if d.weekday() < 4:   # 0=Lun … 3=Jeu
            out.append(d)
        d += timedelta(days=1)
    return out


class Command(BaseCommand):
    help = "Crée les données de démo production pour les 6 équipes Insertion 35."

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help="Supprime les données démo DEMO35 et les présences/affectations des 6 équipes.",
        )

    def handle(self, *args, **opts):
        if opts['clear']:
            self._clear()
            return
        self._seed()

    # ── Nettoyage ─────────────────────────────────────────────
    def _clear(self):
        # Cible uniquement les données DEMO35 — ne touche pas les données des collègues.
        # Ordre : Presence → Affectation → Facture → Devis (cascade TrancheDevis)
        n_pres, _ = Presence.objects.filter(
            affectation__tranche__devis__reference__startswith='DEMO35-'
        ).delete()
        n_aff, _ = Affectation.objects.filter(
            tranche__devis__reference__startswith='DEMO35-'
        ).delete()
        n_fac, _ = Facture.objects.filter(notes=MARKER).delete()
        n_dev, _ = Devis.objects.filter(reference__startswith='DEMO35-').delete()

        self.stdout.write(self.style.SUCCESS(
            f"Nettoyé (DEMO35 uniquement) : {n_pres} présences, "
            f"{n_aff} affectations, {n_fac} factures, {n_dev} devis."
        ))

    # ── Création ─────────────────────────────────────────────
    def _seed(self):
        user = (User.objects.filter(is_superuser=True).first()
                or User.objects.first())
        if not user:
            self.stderr.write("Aucun utilisateur — lance d'abord createsuperuser.")
            return

        client_cache = {}
        n_dev = n_aff = n_pres = n_fac = 0

        for equipe_nom in EQUIPES_35:
            equipe = Equipe.objects.filter(nom=equipe_nom).first()
            if not equipe:
                self.stderr.write(f"  ⚠ Équipe '{equipe_nom}' introuvable — ignorée.")
                continue

            equipiers = list(Equipier.objects.filter(equipe=equipe, actif=True))
            if not equipiers:
                self.stderr.write(f"  ⚠ Aucun équipier actif dans '{equipe_nom}' — ignorée.")
                continue

            recipe_fn = RECIPES[equipe_nom]

            for chantier_cfg in CHANTIERS[equipe_nom]:
                # ── Devis ──
                cli_nom, cli_type, cli_cp, cli_ville = chantier_cfg['client']
                client = self._get_or_create_client(client_cache, cli_nom, cli_type, cli_cp, cli_ville, user)

                ref = f'DEMO35-{chantier_cfg["ref_suffix"]}'
                if Devis.objects.filter(reference=ref).exists():
                    devis = Devis.objects.get(reference=ref)
                else:
                    devis = Devis.objects.create(
                        reference=ref,
                        client=client,
                        equipe=equipe,
                        chantier=f'[Démo] {chantier_cfg["nom"]}',
                        chantier_ville=cli_ville,
                        chantier_cp=cli_cp,
                        status='accepted',
                        taux_mo=TAUX_HO,
                        notes=MARKER,
                        created_by=user,
                    )
                    self._build(devis, None, recipe_fn())
                n_dev += 1

                # ── TrancheDevis ──
                tranche, _ = TrancheDevis.objects.get_or_create(
                    devis=devis,
                    defaults={'nom': 'Chantier complet', 'ordre': 0},
                )

                # ── Affectation ──
                d_debut, d_fin = chantier_cfg['slot']
                aff, _ = Affectation.objects.get_or_create(
                    equipe=equipe,
                    tranche=tranche,
                    defaults={
                        'date_debut': d_debut,
                        'date_fin': d_fin,
                        'debut_creneau': 'matin',
                        'fin_creneau': 'aprem',
                        'created_by': user,
                    },
                )
                n_aff += 1

                # ── Présences ──
                jours = _working_days(d_debut, date(2026, 5, 31))  # jusqu'à fin mai
                factor = chantier_cfg['factor']

                # Sélectionner les jours où l'équipe travaille effectivement
                n_target = int(round(len(jours) * min(factor, 1.0)))
                # Dépassements : quelques jours supplémentaires au-delà du plan
                extra_days = []
                if factor > 1.0:
                    extra_count = int(round(len(jours) * (factor - 1.0)))
                    d_extra = d_fin + timedelta(days=1)
                    limite = date(2026, 5, 31)
                    while len(extra_days) < extra_count and d_extra <= limite:
                        if d_extra.weekday() < 4:
                            extra_days.append(d_extra)
                        d_extra += timedelta(days=1)

                jours_tous = jours + extra_days
                travailles = set(R.sample(jours, min(n_target, len(jours))))
                travailles |= set(extra_days)

                for jour in jours_tous:
                    for equipier in equipiers:
                        if jour in travailles:
                            # Présences effectives (matin + aprem)
                            for creneau in ('matin', 'aprem'):
                                heures = Decimal('4.00') if creneau == 'matin' else Decimal('3.00')
                                Presence.objects.get_or_create(
                                    equipier=equipier,
                                    date=jour,
                                    creneau=creneau,
                                    defaults={
                                        'affectation': aff,
                                        'heures': heures,
                                        'code': '',
                                    },
                                )
                                n_pres += 1
                        else:
                            # Absence (1 enregistrement par jour, creneau matin)
                            code = R.choice(_ABSENCE_CODES)
                            Presence.objects.get_or_create(
                                equipier=equipier,
                                date=jour,
                                creneau='matin',
                                defaults={
                                    'affectation': aff,
                                    'heures': Decimal('0'),
                                    'code': code,
                                },
                            )
                            n_pres += 1

                # ── Facture ──
                fac_mois = chantier_cfg.get('facture_mois')
                if fac_mois:
                    fac_ref = f'[Démo] Facture — {devis.reference}'
                    if not Facture.objects.filter(notes=MARKER, devis=devis).exists():
                        brut = devis.total_brut() or Decimal('3000')
                        montant = (brut * chantier_cfg['facture_ratio']).quantize(Decimal('0.01'))
                        fac_day = R.randint(8, 22)
                        fac_date = date(fac_mois[0], fac_mois[1], fac_day)
                        fac_dt = timezone.make_aware(
                            __import__('datetime').datetime(fac_mois[0], fac_mois[1], fac_day, R.randint(8, 17), 0)
                        )
                        fac = Facture.objects.create(
                            devis=devis,
                            type_doc='facture',
                            destinataire=str(client),
                            libelle=fac_ref,
                            montant=montant,
                            status='validated',
                            validated_by=user,
                            validated_at=fac_dt,
                            date_echeance=fac_date + timedelta(days=30),
                            created_by=user,
                            notes=MARKER,
                        )
                        # date_creation et created_at ont auto_now_add=True → update() pour forcer la date historique
                        Facture.objects.filter(pk=fac.pk).update(
                            date_creation=fac_date,
                            created_at=fac_dt,
                        )
                        n_fac += 1

        self.stdout.write(self.style.SUCCESS(
            f"Démo Insertion 35 créée : {n_dev} devis, {n_aff} affectations, "
            f"{n_pres} présences, {n_fac} factures. "
            f"Marqueur : reference startswith 'DEMO35-' | notes='{MARKER}'"
        ))

    # ── Helpers ──────────────────────────────────────────────
    def _get_or_create_client(self, cache, nom, type_client, cp, ville, user):
        if nom in cache:
            return cache[nom]
        cli, _ = Client.objects.get_or_create(
            nom=nom,
            defaults={
                'type_client': type_client,
                'code_postal': cp,
                'ville': ville,
                'created_by': user,
            },
        )
        cache[nom] = cli
        return cli

    def _build(self, devis, parent, nodes):
        """Crée récursivement l'arbre de lignes (même logique que seed_demo)."""
        for ordre, node in enumerate(nodes):
            if len(node) == 3:
                type_ligne, desc, enfants = node
                ligne = LigneDevis.objects.create(
                    devis=devis, parent=parent, type_ligne=type_ligne,
                    description=desc, quantite=1, ordre=ordre,
                )
                self._build(devis, ligne, enfants)
            else:
                type_ligne, desc, qte, unite, pu = node
                LigneDevis.objects.create(
                    devis=devis, parent=parent, type_ligne=type_ligne,
                    description=desc, quantite=Decimal(str(qte)),
                    unite=unite, cout_unitaire=Decimal(str(pu)), ordre=ordre,
                )
