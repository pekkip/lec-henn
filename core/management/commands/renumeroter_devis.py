"""
Renumérote les devis créés DANS l'outil au nouveau format DE##### (bascule définitive).

Contexte : à la bascule, on veut redonner aux devis de l'outil une numérotation
propre et continue à partir d'un numéro de départ (DE04022 en production), tout en
SUPPRIMANT les factures qui leur sont liées (créées en phase de test, sans valeur).

RÈGLES :
  - Les devis IMPORTÉS du PDF (`importe_pdf=True`) sont EXCLUS : ils conservent la
    référence EBP figurant sur leur PDF. Leurs numéros déjà au format DE##### sont
    « réservés » et la renumérotation les saute pour ne jamais entrer en collision.
  - Les devis sont traités dans l'ordre de leur référence ACTUELLE.
  - Pour chaque devis renuméroté, ses factures liées sont SUPPRIMÉES.

SÉCURITÉ : DRY-RUN par défaut (aucune écriture). Il faut `--confirm` pour appliquer.
La renumérotation se fait en deux temps dans une transaction (références temporaires
puis finales) pour ne jamais violer la contrainte d'unicité en cours de route.

Utilisation :
    python manage.py renumeroter_devis                  # aperçu (dry-run), départ 4022
    python manage.py renumeroter_devis --start 7022     # aperçu avec un autre départ
    python manage.py renumeroter_devis --confirm        # APPLIQUE (départ 4022)

⚠️ Sur le VPS : ``venv/bin/python`` ; en local Windows : ``venv\\Scripts\\python``.
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Devis, Facture
from core.views import DEVIS_PREFIX, DEVIS_FLOOR, NUM_WIDTH

_NEW_FMT = re.compile(rf'^{re.escape(DEVIS_PREFIX)}(\d+)$')


def _ref_sort_key(ref):
    """Tri « par numéro actuel » : par nombre de fin de référence si présent,
    sinon par chaîne — les références sans numéro passent après."""
    m = re.search(r'(\d+)\s*$', ref or '')
    return (0, int(m.group(1))) if m else (1, ref or '')


class Command(BaseCommand):
    help = "Renumérote les devis de l'outil au format DE##### et supprime leurs factures."

    def add_arguments(self, parser):
        parser.add_argument(
            '--start', type=int, default=DEVIS_FLOOR,
            help=f'Premier numéro attribué (défaut {DEVIS_FLOOR}). Ex. 4022 → DE04022.')
        parser.add_argument(
            '--confirm', action='store_true',
            help='Applique réellement les changements (sinon dry-run).')

    def handle(self, *args, **opts):
        start = opts['start']
        apply = opts['confirm']

        # Devis à renuméroter : ceux créés dans l'outil (pas les imports PDF).
        cibles = sorted(
            Devis.objects.filter(importe_pdf=False),
            key=lambda d: _ref_sort_key(d.reference),
        )
        # Numéros DE##### déjà pris par les devis NON renumérotés (imports) → réservés.
        reserves = set()
        for ref in (Devis.objects.filter(importe_pdf=True)
                    .values_list('reference', flat=True)):
            m = _NEW_FMT.match(ref or '')
            if m:
                reserves.add(int(m.group(1)))

        if not cibles:
            self.stdout.write("Aucun devis à renuméroter (tous importés ou base vide).")
            return

        nb_factures = Facture.objects.filter(devis__in=cibles).count()

        # Calcul du plan d'attribution (en sautant les numéros réservés).
        plan = []
        compteur = start
        for d in cibles:
            while compteur in reserves:
                compteur += 1
            plan.append((d, f"{DEVIS_PREFIX}{str(compteur).zfill(NUM_WIDTH)}"))
            compteur += 1

        mode = "APPLICATION" if apply else "DRY-RUN (aucune écriture)"
        self.stdout.write(self.style.WARNING(
            f"=== Renumérotation devis — {mode} ==="))
        self.stdout.write(
            f"{len(plan)} devis à renuméroter, départ {DEVIS_PREFIX}"
            f"{str(start).zfill(NUM_WIDTH)}, {nb_factures} facture(s) liée(s) à supprimer.")
        if reserves:
            self.stdout.write(
                f"{len(reserves)} numéro(s) réservé(s) par des devis importés (sautés).")
        for d, nouvelle in plan:
            self.stdout.write(f"  {d.reference:<22} → {nouvelle}")

        if not apply:
            self.stdout.write(self.style.NOTICE(
                "\nDry-run terminé. Relancer avec --confirm pour appliquer."))
            return

        with transaction.atomic():
            # 1) Supprimer les factures liées.
            Facture.objects.filter(devis__in=[d for d, _ in plan]).delete()
            # 2) Références temporaires (évite toute collision d'unicité intermédiaire).
            for d, _ in plan:
                d.reference = f"__RENUM_TMP__{d.pk}"
                d.save(update_fields=['reference'])
            # 3) Références finales.
            for d, nouvelle in plan:
                d.reference = nouvelle
                d.save(update_fields=['reference'])

        self.stdout.write(self.style.SUCCESS(
            f"\nOK — {len(plan)} devis renumérotés, {nb_factures} facture(s) supprimée(s)."))
