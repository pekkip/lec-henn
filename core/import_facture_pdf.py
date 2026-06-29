"""
Import de factures PDF (format CBB Bretagne, template historique EBP).

Symétrique de `import_pdf` (devis) : le gabarit de tableau est **identique**
(N° Ordre, Descriptif en images OCR, Qté, Unité, coûts Matériaux/Intervention,
Total Net de Taxes). On réutilise donc tout le moteur de parsing de `import_pdf`
et on n'ajoute que :
  - l'extraction de « Référence Devis : DE##### » (lien vers le devis source) ;
  - la création d'une `Facture` rattachée au `Devis` correspondant.

Différence métier clé : une facture importée est rattachée à un devis existant
(`Référence Devis`). Si ce devis est introuvable, l'import du fichier est **bloqué**
(la vue / la commande remontent une alerte) — il faut d'abord importer le devis.

Fonctions principales :
  parse_facture_pdf(path_or_fp) → dict
  create_facture_from_parsed(parsed, devis, user) → (Facture, warnings)
"""
import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pdfplumber

from .import_pdf import (
    _extract_metadata,
    _extract_total,
    _collect_text_lines,
    _build_tree,
    _extract_descriptions,
    _apply_descriptions,
    _count_leaves,
    _is_recapitulatif,
    _parse_amount,
    _fmt_eur,
    _CENTS,
)


def _empty_parsed():
    return {
        'reference': '', 'reference_devis': '', 'date': None,
        'equipe_hint': '', 'objet': '',
        'client': {}, 'chantier': {},
        'tree': [], 'total_pdf': None, 'nb_lignes': 0,
        'errors': [], 'warnings': [],
    }


def parse_facture_pdf(path_or_fp):
    """Parse une facture PDF au format CBB Bretagne.

    Accepte un chemin (str/Path) ou un objet fichier.
    """
    errors = []      # bloquants (réf introuvable, lecture impossible)
    warnings = []    # non bloquants (OCR indisponible…)

    try:
        if hasattr(path_or_fp, 'read'):
            fp = io.BytesIO(path_or_fp.read())
        else:
            fp = path_or_fp

        with pdfplumber.open(fp) as pdf:
            meta = _extract_metadata(pdf)
            # « Référence Devis : DE03967 » — lien vers le devis source.
            page1 = pdf.pages[0].extract_text() or ''
            m = re.search(r'R[ée]f[ée]rence\s+Devis\s*:\s*(\S+)', page1)
            reference_devis = m.group(1).strip() if m else ''

            total_pdf = _extract_total(pdf)
            lines = _collect_text_lines(pdf)
            tree = _build_tree(lines)
            descriptions, ocr_ok = _extract_descriptions(pdf)
            _apply_descriptions(tree, descriptions)
    except Exception as e:
        result = _empty_parsed()
        result['errors'].append(f'Erreur lecture PDF : {e}')
        return result

    if not meta['reference']:
        errors.append('Numéro de facture introuvable dans le PDF.')
    if not reference_devis:
        errors.append('Référence Devis introuvable dans le PDF (facture non rattachable).')
    if not ocr_ok:
        warnings.append(
            'OCR indisponible — descriptions de lignes non importées '
            '(seuls les numéros figurent). Installer Tesseract pour les récupérer.'
        )

    return {
        'reference': meta['reference'],
        'reference_devis': reference_devis,
        'date': meta['date'],
        'equipe_hint': meta['equipe_hint'],
        'objet': meta['objet'],
        'client': {
            'nom': meta['client_nom'],
            'adresse': meta['client_adresse'],
            'cp': meta['client_cp'],
            'ville': meta['client_ville'],
        },
        'chantier': {
            'nom': meta['chantier_nom'],
            'adresse': meta['chantier_adresse'],
            'cp': meta['chantier_cp'],
            'ville': meta['chantier_ville'],
        },
        'tree': tree,
        'total_pdf': total_pdf,
        'nb_lignes': _count_leaves(tree),
        'errors': errors,
        'warnings': warnings,
    }


# ─── Création des objets Django ───────────────────────────────────────────────

def _create_facture_node(facture, node, parent_ligne, ordre):
    """Crée récursivement les LigneFacture depuis l'arbre parsé (miroir de
    import_pdf._create_node, cible LigneFacture).

    `quantite_originale` = `quantite` (snapshot du devis indisponible à l'import),
    `ligne_devis_source` = None (les lignes de la facture importée ne sont pas
    réappariées poste par poste au devis — le rattachement se fait au niveau du
    document via Facture.devis).
    """
    from .models import LigneFacture

    label = node.get('label', '')
    desc_extra = node.get('desc_extra', '')
    description = label
    if desc_extra:
        description = (label + '\n' + desc_extra).strip()
    if not description:
        description = node.get('num', '')

    if _is_recapitulatif(label):
        return

    if node['children']:
        ligne = LigneFacture.objects.create(
            facture=facture, parent=parent_ligne,
            type_ligne='TITRE', description=description,
            quantite=Decimal('1'), quantite_originale=Decimal('1'),
            ordre=ordre[0],
        )
        ordre[0] += 1
        for child in node['children']:
            _create_facture_node(facture, child, ligne, ordre)
        return

    qty = Decimal('1')
    qty_str = (node.get('qty_str') or '').replace(',', '.').replace(' ', '')
    if qty_str:
        try:
            qty = Decimal(qty_str)
        except InvalidOperation:
            pass

    mat = _parse_amount(node.get('mat_str', ''))
    mo = _parse_amount(node.get('mo_str', ''))

    # Recoupement par ligne : total calculé (qté × coûts) vs « Total Net de Taxes »
    # imprimé. Écart → marqueur devant le descriptif (repère la ligne mal lue).
    printed = node.get('total_str', '')
    if printed:
        calc = (qty * (mat + mo)).quantize(_CENTS, rounding=ROUND_HALF_UP)
        pdf_total = _parse_amount(printed).quantize(_CENTS, rounding=ROUND_HALF_UP)
        if calc != pdf_total:
            description = (
                f'⚠ ÉCART {_fmt_eur(abs(calc - pdf_total))} € — '
                f'Total calculé = {_fmt_eur(calc)} € / Montant EBP = '
                f'{_fmt_eur(pdf_total)} €\n{description}'
            )

    ligne = LigneFacture.objects.create(
        facture=facture, parent=parent_ligne,
        type_ligne='S', description=description,
        quantite=qty, quantite_originale=qty,
        unite=node.get('unite', ''), cout_unitaire=None,
        ordre=ordre[0],
    )
    ordre[0] += 1

    # != 0 (et non > 0) : les lignes de financement portent des coûts négatifs.
    if mat != 0:
        LigneFacture.objects.create(
            facture=facture, parent=ligne,
            type_ligne='FMAT', description='Matériaux',
            quantite=Decimal('1'), quantite_originale=Decimal('1'),
            cout_unitaire=mat, ordre=ordre[0],
        )
        ordre[0] += 1
    if mo != 0:
        LigneFacture.objects.create(
            facture=facture, parent=ligne,
            type_ligne='FMO', description="Main d'œuvre",
            quantite=Decimal('1'), quantite_originale=Decimal('1'),
            cout_unitaire=mo, ordre=ordre[0],
        )
        ordre[0] += 1
    if mat == 0 and mo == 0:
        ligne.cout_unitaire = Decimal('0')
        ligne.save(update_fields=['cout_unitaire'])


def _facture_total(facture):
    """Somme des totaux des lignes racines de la facture."""
    return sum((l.total() for l in facture.lignes.filter(parent=None)), Decimal('0'))


def create_facture_from_parsed(parsed, devis, user):
    """Crée une Facture rattachée à `devis` depuis les données parsées.

    La facture est importée au statut **« Envoyée »** (elle portait déjà un numéro
    dans l'ancien outil → au moins émise) et son `montant` est figé sur le « Montant
    Net de Taxes » du PDF (source de vérité du suivi facturé / reste à facturer).
    Retourne (facture, warnings).
    """
    from django.utils import timezone
    from .models import Facture

    warnings = list(parsed.get('warnings', []))

    total_pdf = parsed.get('total_pdf')
    montant = (Decimal(str(total_pdf)).quantize(_CENTS, rounding=ROUND_HALF_UP)
               if total_pdf is not None else Decimal('0'))

    client = devis.client
    destinataire = (parsed.get('client', {}).get('nom') or str(client) or 'Sans nom')

    facture = Facture.objects.create(
        devis=devis,
        type_doc='facture',
        numero=parsed.get('reference') or None,
        destinataire=destinataire[:200],
        montant=montant,
        status='sent',
        created_by=user,
    )

    ordre = [0]
    for root in parsed.get('tree', []):
        _create_facture_node(facture, root, None, ordre)

    # Date historique : date_creation est auto_now_add → on la réécrit via UPDATE
    # (le seul moyen de conserver la date d'émission réelle du PDF).
    pdf_date = parsed.get('date')
    if pdf_date is not None:
        Facture.objects.filter(pk=facture.pk).update(date_creation=pdf_date)
        facture.date_creation = pdf_date

    facture.validated_by = user
    facture.validated_at = timezone.now()
    facture.save(update_fields=['validated_by', 'validated_at'])

    # Contrôle : total des lignes lues vs « Montant Net de Taxes » figé sur le montant.
    # Écart → note de vérification (montant reste = PDF, autoritaire pour le suivi).
    if total_pdf is None:
        note = ('⚠ Import PDF — « Montant Net de Taxes » introuvable : montant à '
                f'vérifier (total des lignes lues : {_fmt_eur(_facture_total(facture))} €).')
        facture.notes = note
        facture.save(update_fields=['notes'])
        warnings.append(note)
    else:
        calc = _facture_total(facture).quantize(_CENTS, rounding=ROUND_HALF_UP)
        if calc != montant:
            note = (
                f'⚠ Import PDF — Écart de {_fmt_eur(abs(calc - montant))} € entre le total '
                f'des lignes lues ({_fmt_eur(calc)} €) et le Montant Net de Taxes du PDF '
                f'({_fmt_eur(montant)} €). Montant facturé conservé = PDF ; vérifier '
                f'les lignes marquées « ⚠ ÉCART », ou arrondi EBP.'
            )
            facture.notes = note
            facture.save(update_fields=['notes'])
            warnings.append(note)

    return facture, warnings
