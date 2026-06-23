"""
Commande CLI pour importer des devis PDF en masse.

Utilisation :
  python manage.py import_devis_pdf --dir "C:/chemin/vers/dossier" --equipe-id 5 --user admin
  python manage.py import_devis_pdf --file "DE04124.pdf" --equipe-id 5 --user admin
  python manage.py import_devis_pdf --dir "..." --equipe-id 5 --dry-run
"""
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from core.models import Devis, Equipe
from core.import_pdf import parse_devis_pdf, create_from_parsed


class Command(BaseCommand):
    help = 'Importe des devis PDF au format CBB Bretagne'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dir', dest='directory', help='Dossier contenant les PDFs')
        group.add_argument('--file', dest='file', help='Fichier PDF unique')
        parser.add_argument('--equipe-id', type=int, required=True, help='PK de l\'équipe')
        parser.add_argument('--user', default='', help='Username de l\'utilisateur (défaut : premier superuser)')
        parser.add_argument('--dry-run', action='store_true', help='Parse sans créer d\'objets en base')

    def handle(self, *args, **options):
        # Résolution de l'équipe
        try:
            equipe = Equipe.objects.get(pk=options['equipe_id'])
        except Equipe.DoesNotExist:
            raise CommandError(f"Équipe {options['equipe_id']} introuvable.")

        # Résolution de l'utilisateur
        username = options.get('user', '')
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"Utilisateur '{username}' introuvable.")
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                raise CommandError('Aucun superuser trouvé. Précisez --user.')

        dry_run = options['dry_run']

        # Collecte des PDFs
        pdfs = []
        if options['directory']:
            d = Path(options['directory'])
            if not d.is_dir():
                raise CommandError(f"Dossier introuvable : {d}")
            pdfs = sorted(d.glob('*.pdf'))
            if not pdfs:
                self.stdout.write(self.style.WARNING(f'Aucun PDF trouvé dans {d}'))
                return
        else:
            p = Path(options['file'])
            if not p.is_file():
                raise CommandError(f"Fichier introuvable : {p}")
            pdfs = [p]

        self.stdout.write(f'{len(pdfs)} fichier(s) à traiter — équipe : {equipe.nom} — user : {user.username}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Mode dry-run : aucun objet ne sera créé.'))

        imported = skipped = errored = 0

        for path in pdfs:
            self.stdout.write(f'  → {path.name}', ending=' ')
            parsed = parse_devis_pdf(path)

            if parsed['errors']:
                self.stdout.write(self.style.ERROR(f'[ERREUR] {"; ".join(parsed["errors"])}'))
                errored += 1
                continue

            ref = parsed.get('reference', '')
            if not ref:
                self.stdout.write(self.style.ERROR('[ERREUR] Référence introuvable'))
                errored += 1
                continue

            if Devis.objects.filter(reference=ref).exists():
                self.stdout.write(self.style.WARNING(f'[DOUBLON] {ref} déjà en base — ignoré'))
                skipped += 1
                continue

            if dry_run:
                nb = parsed.get('nb_lignes', 0)
                total = parsed.get('total_pdf', '?')
                self.stdout.write(self.style.SUCCESS(
                    f'[DRY-RUN] {ref} — {parsed["client"].get("nom","?")} — {nb} lignes — {total} €'
                ))
                imported += 1
                continue

            try:
                devis, warnings = create_from_parsed(parsed, equipe, user)
                msg = f'[OK] {ref} — {devis.chantier}'
                if warnings:
                    msg += f' ⚠ {warnings[0][:60]}…'
                self.stdout.write(self.style.SUCCESS(msg))
                imported += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERREUR] {e}'))
                errored += 1

        self.stdout.write('')
        self.stdout.write(
            f'Terminé — {imported} importé(s), {skipped} ignoré(s), {errored} erreur(s)'
        )
