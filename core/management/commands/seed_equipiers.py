"""
Génère des ÉQUIPIERS fictifs (et rien d'autre) pour tester planning / émargement.

SÉCURITÉ : chaque équipier créé porte un **matricule préfixé ``FIC-``**, qui sert
de marqueur unique. ``--clear`` ne supprime QUE ces équipiers-là (et, par cascade,
leurs présences/prêts éventuels). Aucune autre donnée n'est touchée ; les équipes
existantes sont seulement **réutilisées**, jamais créées ni supprimées.

Utilisation :
    python manage.py seed_equipiers                 # effectif = nb_equipiers de chaque équipe Insertion 35
    python manage.py seed_equipiers --per-equipe 8  # forcer 8 par équipe
    python manage.py seed_equipiers --equipe GORM    # seulement les équipes dont le nom contient « GORM »
    python manage.py seed_equipiers --clear          # supprime UNIQUEMENT les équipiers FIC-

Idempotent : le matricule est ``FIC-<id_équipe>-<NN>``. Relancer avec le même
``--per-equipe`` ne crée pas de doublon ; augmenter ``--per-equipe`` en ajoute.

⚠️ Sur le VPS : ``venv/bin/python`` ; en local Windows : ``venv\\Scripts\\python``.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import Equipe, Equipier

MARKER = 'FIC-'  # préfixe de matricule = marqueur des équipiers fictifs

PRENOMS = [
    'Yannick', 'Soaz', 'Morgan', 'Nolwenn', 'Tangi', 'Awen', 'Glenn', 'Maïwenn',
    'Ronan', 'Solenn', 'Killian', 'Maela', 'Erwan', 'Gaelle', 'Padrig', 'Lenaig',
    'Briac', 'Anaig', 'Youenn', 'Klervi', 'Ewen', 'Mona', 'Gwendal', 'Tiphaine',
    'Loïc', 'Hervé', 'Katell', 'Goulven', 'Rozenn', 'Maël',
]
NOMS = [
    'LE GALL', 'LE ROUX', 'TANGUY', 'PRIGENT', 'GUÉGUEN', 'LE GOFF', 'RIOU',
    'LE BIHAN', 'KERVELLA', 'SALAÜN', 'LE CORRE', 'JÉZÉQUEL', 'GUIVARCH', 'LE DÛ',
    'MAHÉ', 'CABON', 'LE BRAS', 'QUÉMÉNER', 'SCOUARNEC', 'BERNARD', 'CADIOU',
    'KERMARREC', 'MORVAN', 'JAOUEN', 'EVEN', 'TRÉBAOL',
]
TYPES_CONTRAT = ['CDDI - 26 heures', 'CDDI - 20 heures', 'CDDI - 30 heures']


class Command(BaseCommand):
    help = ("Crée des équipiers fictifs (matricule FIC-…) pour tester planning/"
            "émargement, ou les supprime avec --clear.")

    def add_arguments(self, parser):
        parser.add_argument('--per-equipe', dest='per_equipe', type=int, default=None,
                            help="Forcer un nombre d'équipiers par équipe "
                                 "(défaut : l'effectif théorique `nb_equipiers` de chaque équipe).")
        parser.add_argument('--equipe', dest='equipe', default=None,
                            help="Ne cibler que les équipes dont le nom contient ce texte.")
        parser.add_argument('--all-equipes', action='store_true',
                            help="Cibler toutes les équipes actives (pas seulement l'insertion).")
        parser.add_argument('--clear', action='store_true',
                            help="Supprime UNIQUEMENT les équipiers fictifs (matricule FIC-).")

    def handle(self, *args, **opts):
        if opts['clear']:
            qs = Equipier.objects.filter(matricule__startswith=MARKER)
            n = qs.count()
            qs.delete()
            self.stdout.write(self.style.SUCCESS(
                f"{n} équipier(s) fictif(s) supprimé(s) (+ présences/prêts liés par cascade)."))
            return

        # Équipiers permanents → uniquement les rangées permanentes (jamais les
        # rangées ponctuelles temporaire/renfort/prestataire).
        equipes = Equipe.objects.filter(actif=True, archivee=False, type_rangee='permanente')
        if not opts['all_equipes']:
            equipes = equipes.filter(service__module_planning=True)
        if opts['equipe']:
            equipes = equipes.filter(nom__icontains=opts['equipe'])
        equipes = list(equipes.order_by('nom'))

        if not equipes:
            self.stderr.write(self.style.ERROR(
                "Aucune équipe cible (essayer --all-equipes ou ajuster --equipe)."))
            return

        rnd = random.Random(42)  # déterministe → mêmes noms à chaque exécution
        today = date.today()
        total = 0
        for equipe in equipes:
            # Effectif : override --per-equipe sinon `nb_equipiers` de l'équipe.
            n_cible = opts['per_equipe'] if opts['per_equipe'] is not None else (equipe.nb_equipiers or 0)
            for i in range(1, n_cible + 1):
                matricule = f"{MARKER}{equipe.pk}-{i:02d}"
                debut = today - timedelta(days=rnd.randint(90, 540))
                fin = debut + timedelta(days=rnd.randint(180, 730))
                _, created = Equipier.objects.get_or_create(
                    matricule=matricule,
                    defaults=dict(
                        prenom=rnd.choice(PRENOMS),
                        nom=rnd.choice(NOMS),
                        equipe=equipe,
                        type_contrat=rnd.choice(TYPES_CONTRAT),
                        actif=True,
                        date_debut_contrat=debut,
                        date_fin_contrat=fin,
                        date_visite_medicale=debut + timedelta(days=rnd.randint(0, 21)),
                        recup_base_heures=Decimal(str(rnd.randint(0, 20))),
                        recup_base_date=debut,
                        droit_conges_jours=Decimal(str(rnd.choice([25, 26, 27, 28, 30]))),
                    ),
                )
                if created:
                    total += 1
            self.stdout.write(f"  • {equipe.nom} : {n_cible} équipiers fictifs (nb_equipiers={equipe.nb_equipiers})")

        self.stdout.write(self.style.SUCCESS(
            f"{total} équipier(s) fictif(s) créé(s) sur {len(equipes)} équipe(s). "
            f"Retrait : python manage.py seed_equipiers --clear"))
