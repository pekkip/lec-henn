"""
Import de devis PDF (format CBB Bretagne, template historique).

Approche : extraction depuis le texte brut (extract_text) page par page.
La table pdfplumber fusionne plusieurs lignes en une cellule → non utilisée.

Fonctions principales :
  parse_devis_pdf(path_or_fp) → dict
  create_from_parsed(parsed, equipe, user) → (Devis, warnings)
"""
import io
import re
from decimal import Decimal, InvalidOperation
from datetime import date as date_type

import pdfplumber


# ─── Helpers bas niveau ───────────────────────────────────────────────────────

def _parse_date_str(s):
    try:
        d, m, y = s.split('/')
        return date_type(int(y), int(m), int(d))
    except Exception:
        return None


# Nombre format français : "1 668,00" ou "57,78"
_NUMBER_RE = re.compile(r'\d[\d ]*,\d{2}')
# Token alphabétique = unité (M2, F, U, Ml, J, KG, …)
_UNIT_RE = re.compile(r'\b([A-Za-z][A-Za-z0-9/]*)\b')


def _parse_amount(s):
    """"1 668,00" → Decimal("1668.00")."""
    if not s:
        return Decimal('0')
    s = str(s).strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
    s = re.sub(r'[^\d.]', '', s)
    if not s:
        return Decimal('0')
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal('0')


def _dedup_line(s):
    """Supprime la duplication dans les lignes à deux colonnes extraites.

    Ex : "APRAS APRAS" → "APRAS"
    Ex : "Hotel de Ville Hotel de Ville" → "Hotel de Ville"
    Une ligne non dupliquée est retournée telle quelle.
    """
    words = s.split()
    n = len(words)
    for half in range(1, n):
        left = ' '.join(words[:half])
        right = ' '.join(words[half:])
        if left == right:
            return left
    return s


def _parse_cp_ville(line):
    """Extrait (cp, ville) depuis "35700 RENNES" ou "35700 RENNES 35000 RENNES".

    Prend le premier CP+Ville trouvé.
    """
    m = re.search(r'(\d{5})\s+(\S+)', (line or '').strip())
    if m:
        return m.group(1), m.group(2)
    return '', (line or '').strip()


# ─── Lignes footer/header à ignorer ──────────────────────────────────────────

_FOOTER_FRAGMENTS = [
    '22 rue de la',
    'cbbretagne@',
    'Association de chantiers',
    'Association conventionn',
    'Pour les Compagnons',
    'Pour le Maitre',
    'Signature',
    'Conditions g',
    "L'association des Compagnons",
    "l'association des Compagnons",
    'SIRET',
    'APE :',
]

_HEADER_PATTERNS = [
    re.compile(r'^N[°o]\s+Co', re.IGNORECASE),
    re.compile(r'^Descriptif\s+Qt', re.IGNORECASE),
    re.compile(r'^Ordre\s+Mat', re.IGNORECASE),
    re.compile(r'^N[°o]\s*Ordre', re.IGNORECASE),
]


def _is_footer(line):
    return any(frag in line for frag in _FOOTER_FRAGMENTS)


def _is_table_header(line):
    return any(p.match(line) for p in _HEADER_PATTERNS)


# ─── Récapitulatifs ──────────────────────────────────────────────────────────

def _is_recapitulatif(label):
    if not label:
        return False
    low = label.lower()
    return ('récapitulatif' in low or 'recapitulatif' in low or
            bool(re.match(r'co[uû]t total (mat[eé]riaux|main|intervention)', low)))


# ─── Extraction des métadonnées ───────────────────────────────────────────────

def _extract_metadata(pdf):
    """Extrait les métadonnées depuis la page 1 (texte brut structuré)."""
    text = pdf.pages[0].extract_text() or ''

    result = {
        'reference': '',
        'date': None,
        'date_validite': None,
        'equipe_hint': '',
        'objet': '',
        'client_nom': '',
        'client_adresse': '',
        'client_cp': '',
        'client_ville': '',
        'chantier_nom': '',
        'chantier_adresse': '',
        'chantier_cp': '',
        'chantier_ville': '',
    }

    # Référence — "Numéro : DE04124"
    m = re.search(r'Num[eé]ro\s*:\s*(\S+)', text)
    if m:
        result['reference'] = m.group(1).strip()

    # Date de création — "Date : 12/06/2026"
    m = re.search(r'\bDate\s*:\s*(\d{2}/\d{2}/\d{4})', text)
    if m:
        result['date'] = _parse_date_str(m.group(1))

    # Date de validité — "Date de validité : 11/08/2026"
    m = re.search(r'Date de validit[eé]\s*:\s*(\d{2}/\d{2}/\d{4})', text)
    if m:
        result['date_validite'] = _parse_date_str(m.group(1))

    # Équipe / Secteur — "Secteur : AQRM 55"
    m = re.search(r'Secteur\s*:\s*(.+?)(?:\n|$)', text)
    if m:
        result['equipe_hint'] = m.group(1).strip()

    # Objet — "Objet : Fabrication d'un meuble casiers"
    m = re.search(r'Objet\s*:\s*(.+?)(?:\n|$)', text)
    if m:
        result['objet'] = m.group(1).strip()

    # Bloc adresses : entre "Adresse du chantier ... Maître d'Ouvrage" et "Contact téléphonique"
    # Le "." après "d" couvre toutes les formes d'apostrophe (ASCII, curly quote…)
    m = re.search(
        r'Adresse du chantier.+?Coordonn[eé]es du Ma[iî]tre d.Ouvrage\s*\n'
        r'(.*?)(?=Contact t[eé]l[eé]phonique)',
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        block = m.group(1).strip()
        addr_lines = [l.strip() for l in block.split('\n') if l.strip()]
        if addr_lines:
            result['client_nom'] = _dedup_line(addr_lines[0])
            result['chantier_nom'] = result['client_nom']
        if len(addr_lines) > 1:
            cp, ville = _parse_cp_ville(addr_lines[-1])
            result['client_cp'] = result['chantier_cp'] = cp
            result['client_ville'] = result['chantier_ville'] = ville
            mid = [_dedup_line(l) for l in addr_lines[1:-1]]
            result['client_adresse'] = result['chantier_adresse'] = ' '.join(mid)

    return result


def _extract_total(pdf):
    """Extrait "Montant Net de Taxes" depuis la dernière page."""
    for page in reversed(pdf.pages):
        text = page.extract_text() or ''
        m = re.search(r'Montant Net de Taxes\s+([\d ]+,\d{2})', text)
        if m:
            return _parse_amount(m.group(1))
    return None


# ─── Parsing du texte du tableau ──────────────────────────────────────────────

def _parse_amounts_from_text(rest):
    """Extrait (qty, unite, mat_str, mo_str) depuis la partie données d'une ligne.

    Exemples :
      "57,78 M2 14,24 822,79"           → qty=57,78  unit=M2 mat=14,24  mo=''
      "1,00 J 0,00 420,00 420,00"       → qty=1,00   unit=J  mat=0,00   mo=420,00
      "1,00 1 668,00 2 040,00 3 708,00" → qty=1,00   unit='' mat=1668   mo=2040
      "0,00"                             → qty=''    unit='' mat=0,00   mo=''
    """
    numbers = _NUMBER_RE.findall(rest)

    if not numbers:
        return '', '', '', ''

    # Cas particulier : une seule valeur → forfait ou Pour Mémoire
    if len(numbers) == 1:
        val = numbers[0]
        if val == '0,00':
            return '', '', '0,00', ''
        return val, '', '', ''

    # Cherche une unité alphabétique immédiatement après le premier nombre
    first_num_m = _NUMBER_RE.search(rest)
    first_num_end = first_num_m.end()
    rest_after_first = rest[first_num_end:].lstrip()
    unit_m = _UNIT_RE.match(rest_after_first)

    if unit_m:
        qty = numbers[0]
        unit = unit_m.group(1)
        after_unit = rest_after_first[unit_m.end():]
        amounts = _NUMBER_RE.findall(after_unit)
    else:
        qty = numbers[0]
        unit = ''
        amounts = numbers[1:]

    if len(amounts) == 0:
        mat, mo = '', ''
    elif len(amounts) == 1:
        mat = amounts[0]
        mo = ''
    elif len(amounts) == 2:
        # [mat, total] — la colonne MO n'est pas affichée si = 0
        mat = amounts[0]
        mo = ''
    else:
        # [mat, mo, total, …] → prend antépénultième et avant-dernier
        mat = amounts[-3]
        mo = amounts[-2]

    return qty, unit, mat, mo


def _collect_text_lines(pdf):
    """Collecte toutes les lignes de la section tableau sur toutes les pages."""
    all_lines = []
    in_table = False

    for page in pdf.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if _is_footer(line):
                continue
            if re.search(
                r'Montant Net de Taxes|Clauses de r[eé]serve|Conform[eé]ment'
                r'|Pour les Compagnons|L.association des',
                line
            ):
                in_table = False
                continue
            if _is_table_header(line):
                in_table = True
                continue
            if in_table:
                # Continuation : montant séparé sur la ligne suivante par pdfplumber.
                # Ex: "4.1 81,00 M2" puis "26,18 2 120,58" → fusionner.
                if (all_lines
                        and not re.match(r'TOTAL\b', line, re.IGNORECASE)
                        and _parse_text_row(line) is None
                        and re.match(r'^\d[\d ]*,\d{2}', line)):
                    prev = _parse_text_row(all_lines[-1])
                    if prev and prev['qty_str'] and not prev['mat_str'] and not prev['mo_str']:
                        all_lines[-1] += ' ' + line
                        continue
                all_lines.append(line)

    return all_lines


def _parse_text_row(line):
    """Convertit une ligne de texte en nœud ou None."""
    if re.match(r'TOTAL\b', line, re.IGNORECASE):
        return None

    # Le N° doit être suivi d'un espace (ou de la fin de ligne) — pas d'une virgule.
    # Cela empêche "0,00" (montant seul) d'être interprété comme N°="0".
    m = re.match(r'^(\d+(?:\.\d+)*)(?:\s+(.*))?$', line)
    if not m:
        return None

    num = m.group(1)
    rest = (m.group(2) or '').strip()

    if not rest:
        return {
            'num': num, 'depth': num.count('.') + 1, 'label': '',
            'qty_str': '', 'unite': '', 'mat_str': '', 'mo_str': '',
            'children': [], 'desc_extra': '',
        }

    qty, unit, mat, mo = _parse_amounts_from_text(rest)
    return {
        'num': num, 'depth': num.count('.') + 1, 'label': '',
        'qty_str': qty, 'unite': unit, 'mat_str': mat, 'mo_str': mo,
        'children': [], 'desc_extra': '',
    }


def _build_tree(lines):
    """Construit l'arbre hiérarchique depuis les lignes de texte."""
    roots = []
    depth_stack = {}

    for line in lines:
        node = _parse_text_row(line)
        if node is None:
            continue

        depth = node['depth']
        depth_stack[depth] = node
        for d in list(depth_stack.keys()):
            if d > depth:
                del depth_stack[d]

        if depth == 1:
            roots.append(node)
        else:
            parent = depth_stack.get(depth - 1)
            if parent is not None:
                parent['children'].append(node)
            else:
                roots.append(node)

    return roots


def _count_leaves(nodes):
    count = 0
    for n in nodes:
        if n['children']:
            count += _count_leaves(n['children'])
        else:
            count += 1
    return count


# ─── Point d'entrée du parseur ────────────────────────────────────────────────

def parse_devis_pdf(path_or_fp):
    """
    Parse un devis PDF au format CBB Bretagne.

    Accepte un chemin (str/Path) ou un objet fichier.
    """
    errors = []

    try:
        if hasattr(path_or_fp, 'read'):
            fp = io.BytesIO(path_or_fp.read())
        else:
            fp = path_or_fp

        with pdfplumber.open(fp) as pdf:
            meta = _extract_metadata(pdf)
            total_pdf = _extract_total(pdf)
            lines = _collect_text_lines(pdf)
            tree = _build_tree(lines)

    except Exception as e:
        errors.append(f'Erreur lecture PDF : {e}')
        return {
            'reference': '', 'date': None, 'date_validite': None,
            'equipe_hint': '', 'objet': '',
            'client': {}, 'chantier': {},
            'tree': [], 'total_pdf': None, 'nb_lignes': 0,
            'errors': errors,
        }

    if not meta['reference']:
        errors.append('Référence du devis introuvable dans le PDF.')

    nb_lignes = _count_leaves(tree)

    return {
        'reference': meta['reference'],
        'date': meta['date'],
        'date_validite': meta['date_validite'],
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
        'nb_lignes': nb_lignes,
        'errors': errors,
    }


# ─── Création des objets Django ───────────────────────────────────────────────

def _create_node(devis, node, parent_ligne, ordre):
    from .models import LigneDevis

    label = node.get('label', '')
    desc_extra = node.get('desc_extra', '')
    description = label
    if desc_extra:
        description = (label + '\n' + desc_extra).strip()
    if not description:
        description = node.get('num', '')

    if _is_recapitulatif(label):
        return

    has_children = bool(node['children'])

    if has_children:
        ligne = LigneDevis.objects.create(
            devis=devis,
            parent=parent_ligne,
            type_ligne='TITRE',
            description=description,
            quantite=Decimal('1'),
            ordre=ordre[0],
        )
        ordre[0] += 1
        for child in node['children']:
            _create_node(devis, child, ligne, ordre)
    else:
        qty = Decimal('1')
        qty_str = (node.get('qty_str') or '').replace(',', '.').replace(' ', '')
        if qty_str:
            try:
                qty = Decimal(qty_str)
            except InvalidOperation:
                pass

        mat = _parse_amount(node.get('mat_str', ''))
        mo = _parse_amount(node.get('mo_str', ''))

        ligne = LigneDevis.objects.create(
            devis=devis,
            parent=parent_ligne,
            type_ligne='S',
            description=description,
            quantite=qty,
            unite=node.get('unite', ''),
            cout_unitaire=None,
            ordre=ordre[0],
        )
        ordre[0] += 1

        if mat > 0:
            LigneDevis.objects.create(
                devis=devis, parent=ligne,
                type_ligne='FMAT', description='Matériaux',
                quantite=Decimal('1'), cout_unitaire=mat,
                ordre=ordre[0],
            )
            ordre[0] += 1

        if mo > 0:
            LigneDevis.objects.create(
                devis=devis, parent=ligne,
                type_ligne='FMO', description="Main d'œuvre",
                quantite=Decimal('1'), cout_unitaire=mo,
                ordre=ordre[0],
            )
            ordre[0] += 1

        if mat == 0 and mo == 0:
            ligne.cout_unitaire = Decimal('0')
            ligne.save(update_fields=['cout_unitaire'])


def create_from_parsed(parsed, equipe, user):
    """Crée un Devis + ses LigneDevis depuis les données parsées. Retourne (devis, warnings)."""
    from .models import Client, Devis
    from decimal import ROUND_HALF_UP

    warnings = list(parsed.get('errors', []))

    client_data = parsed.get('client', {})
    client, _ = Client.objects.get_or_create(
        nom=client_data.get('nom') or 'Inconnu',
        defaults={
            'adresse': client_data.get('adresse', ''),
            'code_postal': client_data.get('cp', ''),
            'ville': client_data.get('ville', ''),
            'created_by': user,
        }
    )

    chantier_data = parsed.get('chantier', {})
    chantier_nom = parsed.get('objet') or chantier_data.get('nom', '')

    devis = Devis.objects.create(
        reference=parsed['reference'],
        client=client,
        equipe=equipe,
        chantier=chantier_nom,
        chantier_adresse1=chantier_data.get('adresse', ''),
        chantier_cp=chantier_data.get('cp', ''),
        chantier_ville=chantier_data.get('ville', ''),
        date_validite=parsed.get('date_validite'),
        status='draft',
        created_by=user,
    )

    ordre = [0]
    for root_node in parsed.get('tree', []):
        _create_node(devis, root_node, None, ordre)

    total_pdf = parsed.get('total_pdf')
    if total_pdf is not None:
        total_calc = devis.total_brut()
        cents = Decimal('0.01')
        ecart = abs(
            total_calc.quantize(cents, rounding=ROUND_HALF_UP) -
            Decimal(str(total_pdf)).quantize(cents, rounding=ROUND_HALF_UP)
        )
        if ecart > Decimal('0.01'):
            msg = (
                f'⚠ Import PDF — Différence de {ecart:.2f} €, '
                f'probable erreur d\'arrondi venant d\'EBP. '
                f'À vérifier si cela semble anormal '
                f'(calculé : {total_calc:.2f} € / PDF : {total_pdf:.2f} €).'
            )
            devis.notes = msg
            devis.save(update_fields=['notes'])
            warnings.append(msg)

    return devis, warnings
