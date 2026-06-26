"""
Import de devis XLS/XLSX — trois familles de mise en page.

Formats détectés :
  A (CHURAQUI, FAURE)  : N°Ordre col 0, Descriptif col 1, Qté col 4, PU col 6, Total col 7
  B (BLUMENAU, MARION) : pas d'en-tête Descriptif, cols 2-6
  C (DEMAILLE .xlsx)   : N°Ordre col 1, Descriptif col 2, cols 3-7

parse_devis_xls(path_or_fp) → dict (même format que parse_devis_pdf + clé importe_pdf)
"""
import io
import re
import unicodedata
import datetime
from decimal import Decimal, InvalidOperation


# ─── Helpers ───────────────────────────────────────────────────────────────

def _normalise(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')


def _cell_str(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return f'{v:g}'
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()[:10]
    return str(v).strip()


def _cell_decimal(v):
    if v is None:
        return None
    if isinstance(v, float):
        return Decimal(repr(v))
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str):
        s = v.strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
        if not s:
            return None
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _parse_date_cell(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = _cell_str(v).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


# ─── Chargement ────────────────────────────────────────────────────────────

def _pad_row(row, min_len=10):
    row = list(row)
    while len(row) < min_len:
        row.append(None)
    return row


def _load_rows(path_or_fp):
    """Charge un .xls ou .xlsx → (rows, content_bytes, is_xlsx)."""
    if isinstance(path_or_fp, str):
        with open(path_or_fp, 'rb') as f:
            content = f.read()
    else:
        content = path_or_fp.read()

    is_xlsx = content[:2] == b'PK'

    if is_xlsx:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = [_pad_row(row) for row in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        import xlrd
        wb = xlrd.open_workbook(file_contents=content)
        ws = wb.sheet_by_index(0)
        rows = [_pad_row(ws.row_values(r)) for r in range(ws.nrows)]

    return rows, content, is_xlsx


# ─── Détection du format ───────────────────────────────────────────────────

def _detect_header_and_cols(rows):
    """
    Retourne (header_idx, col_map, fmt).
    fmt ∈ {'A', 'B', 'C'}.
    """
    for r_idx, row in enumerate(rows[:40]):
        for c_idx, v in enumerate(row[:8]):
            if 'descriptif' in _normalise(_cell_str(v)):
                if c_idx <= 1:
                    # Format A : N°Ordre col 0, Descriptif col 1
                    col_map = {
                        'num': 0, 'desc': 1, 'qty': 4,
                        'unit': 5, 'uprice': 6, 'total': 7, 'subtotal': -1,
                    }
                    return r_idx, col_map, 'A'
                else:
                    # Format C : N°Ordre col 1, Descriptif col 2
                    col_map = {
                        'num': 1, 'desc': 2, 'qty': 3,
                        'unit': 4, 'uprice': 5, 'total': 6, 'subtotal': 7,
                    }
                    return r_idx, col_map, 'C'

    # Format B : pas d'en-tête
    col_map = {
        'num': -1, 'desc': 2, 'qty': 3,
        'unit': 4, 'uprice': 5, 'total': 6, 'subtotal': -1,
    }
    return None, col_map, 'B'


# ─── Métadonnées ───────────────────────────────────────────────────────────

def _extract_metadata(rows, header_idx, fmt):
    result = {
        'reference': '', 'date': None, 'equipe_hint': '', 'objet': '',
        'client_nom': '', 'client_adresse': '', 'client_cp': '', 'client_ville': '',
    }
    scan_end = header_idx if header_idx is not None else min(40, len(rows))

    if fmt == 'C':
        in_addr = False
        addr_parts = []
        for row in rows[:scan_end]:
            c1 = _cell_str(row[1]) if len(row) > 1 else ''
            if re.match(r'(?i)\s*objet\s*:', c1):
                result['objet'] = re.sub(r'(?i)^\s*objet\s*:\s*', '', c1).strip()

            c3 = _cell_str(row[3]) if len(row) > 3 else ''
            c6_raw = row[6] if len(row) > 6 else None
            c3n = _normalise(c3)

            if 'date' in c3n and 'validit' not in c3n and c6_raw is not None:
                result['date'] = _parse_date_cell(c6_raw)
            elif 'numero de devis' in c3n and c6_raw:
                result['reference'] = _cell_str(c6_raw).strip()
            elif 'secteur' in c3n and c6_raw:
                result['equipe_hint'] = _cell_str(c6_raw).strip()
            elif 'adresse' in c3n and not in_addr and not result['client_nom']:
                in_addr = True
                addr_parts = []
            elif in_addr and c3.strip():
                addr_parts.append(c3.strip())
                if len(addr_parts) >= 3:
                    in_addr = False

        if addr_parts:
            result['client_nom'] = addr_parts[0]
            if len(addr_parts) > 1:
                result['client_adresse'] = addr_parts[1]
            if len(addr_parts) > 2:
                m = re.match(r'^(\d{5})\s+(.+)$', addr_parts[2].strip())
                if m:
                    result['client_cp'] = m.group(1)
                    result['client_ville'] = m.group(2).strip()
                else:
                    result['client_ville'] = addr_parts[2]

    elif fmt == 'A':
        for row in rows[:scan_end]:
            c0 = _cell_str(row[0]) if row else ''
            m = re.match(r'(?i)\s*objet\s*:\s*(.+)', c0)
            if m:
                result['objet'] = m.group(1).strip()
                break

    return result


def _extract_shape_metadata(content):
    """
    Extrait date + référence + code secteur depuis la zone de texte d'en-tête BIFF (XLS).

    La zone de texte stocke ses champs séparés par LF (0x0a) :
      DD/MM/YYYY \\n référence \\n [durée | date_fin] \\n code_secteur (2 chiffres)

    Le code secteur est extrait sur les bytes bruts pour éviter la contamination
    par les bytes BIFF qui suivent immédiatement la fin du texte.
    """
    import calendar

    def _clean(raw):
        return re.sub(r'\s+', ' ', ''.join(chr(b) if 32 <= b < 127 else ' ' for b in raw)).strip()

    result = {'date': None, 'date_validite': None, 'reference': '', 'equipe_hint': ''}

    for m in re.finditer(rb'\d{2}/\d{2}/\d{4}', content):
        block = content[m.start():m.start() + 100]
        raw_fields = block.split(b'\x0a')
        fields = [_clean(f) for f in raw_fields[:5]]

        if len(fields) < 2:
            continue

        ref = re.sub(r'[^A-Za-z0-9 \-/]', '', fields[1]).strip()
        if not ref:
            continue

        date_str = re.sub(r'[^0-9/]', '', fields[0])
        try:
            date = datetime.datetime.strptime(date_str, '%d/%m/%Y').date()
        except ValueError:
            continue

        result['date'] = date
        result['reference'] = ref

        # Champ 2 : durée ("X mois") ou date de fin de validité
        if len(fields) > 2:
            f2 = fields[2]
            dm = re.match(r'\d{2}/\d{2}/\d{4}', f2)
            if dm:
                try:
                    result['date_validite'] = datetime.datetime.strptime(dm.group(0), '%d/%m/%Y').date()
                except ValueError:
                    pass
            else:
                mm = re.match(r'^(\d+)\s*mois', f2, re.IGNORECASE)
                if mm:
                    months = int(mm.group(1))
                    y = date.year + (date.month - 1 + months) // 12
                    mo = (date.month - 1 + months) % 12 + 1
                    day = min(date.day, calendar.monthrange(y, mo)[1])
                    result['date_validite'] = datetime.date(y, mo, day)

        # Code secteur : cherche \nXX[\t<\x00] dans les bytes bruts du bloc
        # (évite les faux positifs dus aux bytes de record BIFF après le texte)
        sm = re.search(rb'\n(\d{2})[\x09<\x00]', block[:80])
        if sm:
            result['equipe_hint'] = sm.group(1).decode('ascii')

        break  # Premier bloc valide = en-tête du devis

    # Objet : prend la dernière occurrence de "Objet :" dans le fichier.
    # Les fichiers contiennent parfois un objet template en début et l'objet réel
    # ensuite — le dernier est toujours le bon.
    objet_matches = list(re.finditer(rb'Objet\s*:\s+([^\x00<\n\r]{3,200})', content))
    if objet_matches:
        raw = objet_matches[-1].group(1)
        clean = bytes(b for b in raw if 0x20 <= b <= 0x7e or b >= 0xa0)
        objet = clean.decode('latin-1', errors='replace').strip()
        if objet and len(objet) >= 3:
            result['objet'] = objet

    # Client : text box avec label "Client:", "Habitant:" ou "Adresse  :"
    # Structure : \x3c\x00 + LE_length + \x00 + label\n + nom\n + adresse\n + cp_ville\n
    result.update({'client_nom': '', 'client_adresse': '', 'client_cp': '', 'client_ville': ''})
    for label_pat in (rb'Client', rb'Habitant', rb'Adresse'):
        cm = re.search(b'\x3c\x00[\x01-\xff]\x00\x00' + label_pat + rb'[^\x0a]*\x0a', content)
        if not cm:
            continue
        pos = cm.start()
        length = content[pos + 2] + content[pos + 3] * 256
        record = content[pos + 4: pos + 4 + length]  # inclut le null initial
        lines = record.split(b'\x0a')

        def _clean_line(raw):
            return bytes(b for b in raw if b >= 0x20 or b == 0x09).decode('latin-1', errors='replace').strip().strip('\t')

        nom = _clean_line(lines[1]) if len(lines) > 1 else ''
        adr = _clean_line(lines[2]) if len(lines) > 2 else ''
        cp_ville = _clean_line(lines[3]) if len(lines) > 3 else ''

        if not nom:
            continue
        result['client_nom'] = nom
        result['client_adresse'] = adr
        cpm = re.match(r'^(\d{5})\s+(.+)$', cp_ville)
        if cpm:
            result['client_cp'] = cpm.group(1)
            result['client_ville'] = cpm.group(2).strip()
        elif cp_ville:
            result['client_ville'] = cp_ville
        break

    return result


# ─── Filtres ───────────────────────────────────────────────────────────────

_SKIP_KW = (
    'ss total', 'sous-total', 'sous total',
    'cout total', 'total cout',
    'don de mat', 'travaux realises',
)

_STOP_KW = (
    'clauses de reserve', 'conditions generales',
    'pour le client', 'pour les compagnons', 'pour le maitre',
    'aides notifi', 'aides financ', 'montant du',
)


def _row_texts(row):
    return [_normalise(_cell_str(v)) for v in row if _cell_str(v).strip()]


def _is_skip_row(row):
    texts = _row_texts(row)
    if not texts:
        return True
    for t in texts:
        for kw in _SKIP_KW:
            if kw in t:
                return True
    return False


def _is_stop_row(row):
    for t in _row_texts(row):
        for kw in _STOP_KW:
            if kw in t:
                return True
    return False


def _is_section_end_row(row):
    for t in _row_texts(row):
        if 'ss total' in t:
            return True
    return False


# ─── Construction de nœuds ─────────────────────────────────────────────────

def _effective_uprice(qty_d, uprice_d, total_d):
    """Corrige le prix unitaire pour les lignes de taux (assurance %, forfait %)."""
    if qty_d is None:
        qty_d = Decimal('1')
    if uprice_d is None:
        uprice_d = Decimal('0')
    if total_d is None or total_d == 0:
        return uprice_d, qty_d
    calc = qty_d * uprice_d
    if abs(calc - total_d) > Decimal('0.02'):
        if qty_d != 0:
            return total_d / qty_d, qty_d
        return total_d, Decimal('1')
    return uprice_d, qty_d


def _make_leaf(desc, qty_d, unit, uprice_d, total_d):
    eff_up, eff_qty = _effective_uprice(qty_d, uprice_d, total_d)
    unit_n = _normalise(unit)
    is_labor = unit_n.startswith('jour') or unit_n == 'j'
    mat_str = '0' if is_labor else str(eff_up)
    mo_str = str(eff_up) if is_labor else '0'
    return {
        'label': desc.strip(), 'num': '', 'children': [], 'desc_extra': '',
        'qty_str': str(eff_qty),
        'unite': unit.strip(),
        'mat_str': mat_str,
        'mo_str': mo_str,
        'total_str': str(total_d) if total_d is not None else '',
        '_is_titre': False,
    }


def _make_titre(label, num=''):
    return {
        'label': label.strip(), 'num': num, 'children': [], 'desc_extra': '',
        '_is_titre': True,
    }


# ─── Classification d'une ligne ────────────────────────────────────────────

def _classify_row_A(row, col_map):
    num_raw = row[col_map['num']]
    # xlrd reads "1.0" as float 1.0 → must preserve ".0" suffix
    if isinstance(num_raw, float):
        num_v = f'{int(num_raw)}.0' if num_raw == int(num_raw) else f'{num_raw:g}'
    else:
        num_v = _cell_str(num_raw)
    desc = _cell_str(row[col_map['desc']])

    if num_v.strip() and re.match(r'^\d+\.\d+$', num_v.strip()):
        num = num_v.strip()
        depth = 1 if num.endswith('.0') else 2
        return ('TITRE', depth, _make_titre(desc or num, num))

    if not desc.strip():
        return None

    qty_d = _cell_decimal(row[col_map['qty']])
    uprice_d = _cell_decimal(row[col_map['uprice']])
    total_d = _cell_decimal(row[col_map['total']])

    if uprice_d is None and total_d is None:
        return None

    unit = _cell_str(row[col_map['unit']])
    return ('LEAF', 99, _make_leaf(desc, qty_d, unit, uprice_d, total_d))


def _classify_row_B(row, col_map):
    desc = _cell_str(row[col_map['desc']])
    if not desc.strip():
        return None

    desc_n = _normalise(desc)
    qty_d = _cell_decimal(row[col_map['qty']])
    uprice_d = _cell_decimal(row[col_map['uprice']])
    total_d = _cell_decimal(row[col_map['total']])
    has_price = qty_d is not None or uprice_d is not None or total_d is not None

    if desc_n.startswith('lot n') or 'encadrement' in desc_n:
        return ('TITRE', 1, _make_titre(desc))

    if not has_price:
        return ('TITRE', 2, _make_titre(desc))

    unit = _cell_str(row[col_map['unit']])
    return ('LEAF', 99, _make_leaf(desc, qty_d, unit, uprice_d, total_d))


def _classify_row_C(row, col_map):
    num_v = _cell_str(row[col_map['num']])
    desc = _cell_str(row[col_map['desc']])

    if re.match(r'(?i)\s*lot\s*n', num_v):
        label = desc.strip() or num_v.strip()
        return ('TITRE', 1, _make_titre(label, num_v.strip()))

    if not desc.strip():
        return None

    qty_d = _cell_decimal(row[col_map['qty']])
    uprice_d = _cell_decimal(row[col_map['uprice']])
    total_d = _cell_decimal(row[col_map['total']])

    if qty_d is None and uprice_d is None and total_d is None:
        return ('TITRE', 2, _make_titre(desc))

    unit = _cell_str(row[col_map['unit']])
    return ('LEAF', 99, _make_leaf(desc, qty_d, unit, uprice_d, total_d))


def _classify_row(row, col_map, fmt):
    if fmt == 'A':
        return _classify_row_A(row, col_map)
    if fmt == 'B':
        return _classify_row_B(row, col_map)
    return _classify_row_C(row, col_map)


# ─── Arbre ─────────────────────────────────────────────────────────────────

def _attach(roots, stack, node, depth, is_titre):
    while stack and stack[-1][1] >= depth:
        stack.pop()
    target = stack[-1][0]['children'] if stack else roots
    target.append(node)
    if is_titre:
        stack.append((node, depth))


def _prune_empty_titres(nodes):
    result = []
    for n in nodes:
        n['children'] = _prune_empty_titres(n['children'])
        if n.get('_is_titre') and not n['children']:
            continue
        result.append(n)
    return result


def _parse_tree(rows, header_idx, col_map, fmt):
    roots = []
    stack = []
    start = (header_idx + 1) if header_idx is not None else 0

    for row in rows[start:]:
        if _is_stop_row(row):
            break
        if _is_section_end_row(row):
            while stack:
                stack.pop()
            continue
        if _is_skip_row(row):
            continue

        result = _classify_row(row, col_map, fmt)
        if result is None:
            continue

        rtype, depth, node = result
        _attach(roots, stack, node, depth, rtype == 'TITRE')

    return _prune_empty_titres(roots)


# ─── Total ─────────────────────────────────────────────────────────────────

def _extract_total(rows):
    """Cherche 'cout total' / 'total cout' dans toutes les lignes."""
    for row in rows:
        texts = [_normalise(_cell_str(v)) for v in row]
        has_kw = any(
            ('cout total' in t or 'total cout' in t) and 'ss total' not in t
            for t in texts
        )
        if not has_kw:
            continue
        for v in reversed(list(row)[:9]):
            d = _cell_decimal(v)
            if d is not None and d > 0:
                return d
    return None


def _count_leaves(nodes):
    count = 0
    for n in nodes:
        if n['children']:
            count += _count_leaves(n['children'])
        else:
            count += 1
    return count


# ─── Point d'entrée ────────────────────────────────────────────────────────

def parse_devis_xls(path_or_fp):
    """Parse un devis XLS/XLSX. Retourne le même dict que parse_devis_pdf."""
    errors = []
    warnings = []

    try:
        rows, content, is_xlsx = _load_rows(path_or_fp)
    except Exception as exc:
        return {
            'reference': '', 'date': None, 'date_validite': None,
            'equipe_hint': '', 'objet': '',
            'client': {}, 'chantier': {},
            'tree': [], 'total_pdf': None, 'nb_lignes': 0,
            'errors': [f'Impossible de lire le fichier : {exc}'],
            'warnings': [],
            'importe_pdf': False,
        }

    header_idx, col_map, fmt = _detect_header_and_cols(rows)
    meta = _extract_metadata(rows, header_idx, fmt)

    # Pour les fichiers XLS, fusionner les métadonnées extraites des zones de texte
    if not is_xlsx:
        shape_meta = _extract_shape_metadata(content)
        for key in ('reference', 'date', 'date_validite', 'equipe_hint', 'objet',
                    'client_nom', 'client_adresse', 'client_cp', 'client_ville'):
            if shape_meta.get(key) and not meta.get(key):
                meta[key] = shape_meta[key]

    tree = _parse_tree(rows, header_idx, col_map, fmt)
    total_xls = _extract_total(rows)
    nb_lignes = _count_leaves(tree)

    if not tree:
        errors.append('Aucune ligne importable trouvée dans ce fichier.')

    has_ref = bool(meta.get('reference', '').strip())

    return {
        'reference': meta.get('reference', ''),
        'date': meta.get('date'),
        'date_validite': meta.get('date_validite'),
        'equipe_hint': meta.get('equipe_hint', ''),
        'objet': meta.get('objet', ''),
        'client': {
            'nom': meta.get('client_nom', ''),
            'adresse': meta.get('client_adresse', ''),
            'cp': meta.get('client_cp', ''),
            'ville': meta.get('client_ville', ''),
        },
        'chantier': {
            'nom': meta.get('objet', ''),
            'adresse': '',
            'cp': '',
            'ville': '',
        },
        'tree': tree,
        'total_pdf': total_xls,
        'nb_lignes': nb_lignes,
        'errors': errors,
        'warnings': warnings,
        'importe_pdf': has_ref,
    }
