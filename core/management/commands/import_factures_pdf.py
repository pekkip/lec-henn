"""
Commande CLI pour importer des factures PDF en masse (outil principal).

Chaque facture est rattachée au devis dont la référence figure dans le PDF
(« Référence Devis : DE##### »). Si ce devis est introuvable en base, le fichier
est BLOQUÉ (signalé en alerte) : il faut d'abord importer le devis correspondant.

Utilisation :
  python manage.py import_factures_pdf --dir "C:/chemin/vers/dossier" --user admin
  python manage.py import_factures_pdf --file "FA02913.pdf" --user admin
  python manage.py import_factures_pdf --dir "..." --dry-run
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from core.models import Devis, Facture
from core.import_facture_pdf import parse_facture_pdf, create_facture_from_parsed


class Command(BaseCommand):
    help = 'Importe des factures PDF au format CBB Bretagne (rattachées à leur devis)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dir', dest='directory', help='Dossier contenant les PDFs')
        group.add_argument('--file', dest='file', help='Fichier PDF unique')
        parser.add_argument('--user', default='', help="Username (défaut : premier superuser)")
        parser.add_argument('--dry-run', action='store_true', help="Parse sans rien créer")

    def handle(self, *args, **options):
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

        self.stdout.write(f'{len(pdfs)} fichier(s) à traiter — user : {user.username}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Mode dry-run : aucun objet ne sera créé.'))

        imported = skipped = blocked = errored = 0

        for path in pdfs:
            self.stdout.write(f'  → {path.name}', ending=' ')
            parsed = parse_facture_pdf(path)

            if parsed['errors']:
                self.stdout.write(self.style.ERROR(f'[ERREUR] {"; ".join(parsed["errors"])}'))
                errored += 1
                continue

            numero = parsed.get('reference', '')
            devis_ref = parsed.get('reference_devis', '')

            if Facture.objects.filter(numero=numero).exists():
                self.stdout.write(self.style.WARNING(f'[DOUBLON] {numero} déjà en base — ignorée'))
                skipped += 1
                continue

            devis = Devis.objects.filter(reference=devis_ref).first() if devis_ref else None
            if devis is None:
                self.stdout.write(self.style.ERROR(
                    f'[BLOQUÉE] {numero} — devis « {devis_ref or "?"} » introuvable '
                    f'(importez d\'abord le devis)'
                ))
                blocked += 1
                continue

            if dry_run:
                nb = parsed.get('nb_lignes', 0)
                total = parsed.get('total_pdf', '?')
                self.stdout.write(self.style.SUCCESS(
                    f'[DRY-RUN] {numero} → devis {devis.reference} — {nb} lignes — {total} €'
                ))
                imported += 1
                continue

            try:
                facture, warnings = create_facture_from_parsed(parsed, devis, user)
                msg = f'[OK] {numero} → devis {devis.reference} ({facture.montant} €)'
                if warnings:
                    msg += f' ⚠ {warnings[0][:60]}…'
                self.stdout.write(self.style.SUCCESS(msg))
                imported += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERREUR] {e}'))
                errored += 1

        self.stdout.write('')
        self.stdout.write(
            f'Terminé — {imported} importée(s), {skipped} ignorée(s) (doublon), '
            f'{blocked} bloquée(s) (devis absent), {errored} erreur(s)'
        )
