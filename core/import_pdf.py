"""
Import de devis PDF (format CBB Bretagne, template historique).

Approche : extraction depuis le texte brut (extract_text) page par page.
La table pdfplumber fusionne plusieurs lignes en une cellule → non utilisée.

Fonctions principales :
  parse_devis_pdf(path_or_fp) → dict
  create_from_parsed(parsed, equipe, user) → (Devis, warnings)
"""
import io
import os
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date as date_type

import pdfplumber

logger = logging.getLogger(__name__)

_CENTS = Decimal('0.01')

# Numéro de ligne / N° Ordre du tableau EBP. Chaque segment est un groupe de
# chiffres OU une lettre majuscule isolée (sections « B », « B.2.1 » des factures
# de situation) — les devis n'utilisent que des chiffres, le motif reste donc
# rétro-compatible. Partagé par l'ancrage OCR (_number_row_positions) et le parsing
# texte (_parse_text_row) pour que l'arbre et les descriptions s'alignent.
_NODE_NUM = r'(?:[A-Z]|\d+)(?:\.(?:[A-Z]|\d+))*'


def _fmt_eur(v):
    """Decimal → "1 234,56" (format français, sans symbole)."""
    return f'{v:.2f}'.replace('.', ',')


# ─── OCR de la colonne « Descriptif » ─────────────────────────────────────────
#
# EBP exporte la colonne « Descriptif » en images raster (une bitmap par cellule,
# 1-bit DeviceGray ~300 DPI) : la couche texte du PDF ne contient QUE les nombres.
# On récupère donc les libellés par OCR (Tesseract), en rattachant chaque image à
# la ligne numérotée de la même rangée (alignement vertical par `top`).
#
# Prérequis : binaire `tesseract` + langue `fra`.
#   - VPS Ubuntu : apt install tesseract-ocr tesseract-ocr-fra (sur le PATH).
#   - Dev Windows : installer Tesseract puis renseigner les variables d'env
#       TESSERACT_CMD = chemin de tesseract.exe (si absent du PATH)
#       TESSDATA_DIR  = dossier tessdata contenant fra.traineddata (optionnel)
# Si l'OCR est indisponible, l'import continue sans descriptions (warning remonté).

_OCR_LANG = 'fra'
_TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '').strip()
_TESSDATA_DIR = os.environ.get('TESSDATA_DIR', '').strip()

# Géométrie de la colonne descriptif (points PDF, template EBP).
_DESC_X0_MAX = 110     # x0 d'une cellule descriptif (colonne de gauche)
_DESC_X1_MAX = 320     # x1 < seuil (avant la colonne Qté) — exclut chiffres/logo à droite
_ROW_MATCH_TOL = 12    # tolérance verticale (px) ligne numérotée ↔ image

_tesseract_checked = False
_tesseract_ok = False


def _tesseract_available():
    """Vérifie (une fois) que pytesseract + le binaire tesseract sont utilisables."""
    global _tesseract_checked, _tesseract_ok
    if _tesseract_checked:
        return _tesseract_ok
    _tesseract_checked = True
    try:
        import pytesseract
        if _TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
        if _TESSDATA_DIR:
            # Tesseract lit le dossier des langues via cette variable d'env
            # (préférée à --tessdata-dir : pas de souci d'espaces/guillemets).
            os.environ['TESSDATA_PREFIX'] = _TESSDATA_DIR
        pytesseract.get_tesseract_version()
        _tesseract_ok = True
    except Exception as e:  # ImportError, TesseractNotFoundError, …
        logger.warning('OCR Tesseract indisponible : %s', e)
        _tesseract_ok = False
    return _tesseract_ok


def _ocr_cell(pil_image):
    """OCR d'une cellule descriptif → texte normalisé (blancs ramenés à 1 espace)."""
    import pytesseract
    cfg = '--psm 6'  # bloc de texte uniforme (cellule multi-lignes)
    txt = pytesseract.image_to_string(pil_image, lang=_OCR_LANG, config=cfg)
    return re.sub(r'\s+', ' ', txt or '').strip()


def _number_row_positions(page):
    """Position verticale de chaque ligne numérotée → [(top, num), …].

    Le N°/Ordre est le token le plus à gauche (x0 < 100) et purement numérique
    (« 1 », « 1.1 », « 2.1 »…). Les montants (« 720,00 ») ont une virgule → exclus.
    """
    result = []
    seen = set()
    for w in sorted(page.extract_words(), key=lambda w: w['top']):
        if w['x0'] < 100 and re.fullmatch(_NODE_NUM, w['text']):
            num = w['text']
            if num not in seen:
                seen.add(num)
                result.append((float(w['top']), num))
    return result


def _descriptif_image_boxes(page):
    """Bboxes des images de la colonne descriptif → [(top, bbox), …].

    Filtre par colonne (x) + exclut le logo (DeviceRGB). Le rattachement par
    tolérance verticale écarte de toute façon le logo (top ≈ 35, loin du tableau)
    et les images « TOTAL … » des récapitulatifs (≈25 px de toute ligne numérotée).
    """
    boxes = []
    for im in page.images:
        if im['x0'] >= _DESC_X0_MAX or im['x1'] >= _DESC_X1_MAX:
            continue
        if 'RGB' in str(im.get('colorspace', '')):
            continue
        boxes.append((float(im['top']), (im['x0'], im['top'], im['x1'], im['bottom'])))
    return boxes


_OCR_DPI = 300


def _total_row_tops(page):
    """Positions verticales des lignes « TOTAL » (récapitulatifs)."""
    tops = []
    for w in page.extract_words():
        if w['text'].upper() == 'TOTAL' and w['x0'] < 150:
            tops.append(float(w['top']))
    return tops


def _assign_boxes_to_rows(rows, boxes, total_tops=(), tol=_ROW_MATCH_TOL):
    """Rattache les images descriptif aux lignes numérotées → {num: [payloads]}.

    rows : [(top, num)] ; boxes : [(top, payload)] ; total_tops : tops des lignes « TOTAL ».
    Trois cas, dans l'ordre :
      1. image alignée (≤ tol) à une ligne numérotée → titre/ligne de cette ligne ;
      2. sinon, image alignée à une ligne « TOTAL » → récapitulatif, ignorée ;
      3. sinon, texte orphelin (corps sans numéro, ex. NOTA) → rattaché à la ligne
         numérotée juste au-dessus.
    Les payloads d'une même ligne sont renvoyés triés du haut vers le bas (titre
    puis corps). Fonction pure → testable sans OCR.
    """
    rows_sorted = sorted(rows)
    acc = {}
    for btop, payload in sorted(boxes):
        # 1) aligné à une ligne numérotée
        best, best_d = None, None
        for rtop, num in rows_sorted:
            d = abs(rtop - btop)
            if best_d is None or d < best_d:
                best_d, best = d, num
        if best is not None and best_d <= tol:
            acc.setdefault(best, []).append((btop, payload))
            continue
        # 2) récapitulatif (aligné à une ligne TOTAL) → ignoré
        if any(abs(btop - tt) <= tol for tt in total_tops):
            continue
        # 3) texte orphelin → ligne numérotée au-dessus
        above = [(rtop, num) for rtop, num in rows_sorted if rtop <= btop]
        if above:
            _, num = max(above, key=lambda x: x[0])
            acc.setdefault(num, []).append((btop, payload))
    return {num: [p for _, p in sorted(lst)] for num, lst in acc.items()}


def _extract_descriptions(pdf):
    """OCR des descriptions → (dict {num: texte}, ocr_disponible: bool).

    Chaque page n'est rendue qu'une seule fois (puis recadrée en mémoire avec
    Pillow) — bien plus rapide que `page.crop(...).to_image()` par cellule.
    """
    descriptions = {}
    if not _tesseract_available():
        return descriptions, False

    scale = _OCR_DPI / 72.0
    for page in pdf.pages:
        rows = _number_row_positions(page)
        boxes = _descriptif_image_boxes(page)
        if not rows or not boxes:
            continue
        assigned = _assign_boxes_to_rows(rows, boxes, _total_row_tops(page))
        if not assigned:
            continue

        try:
            page_img = page.to_image(resolution=_OCR_DPI).original
        except Exception as e:
            logger.warning('Rendu page échoué pour OCR : %s', e)
            continue

        for num, bbox_list in assigned.items():
            parts = []
            for x0, top, x1, bottom in bbox_list:
                px = (int(x0 * scale), int(top * scale),
                      int(x1 * scale), int(bottom * scale))
                try:
                    txt = _ocr_cell(page_img.crop(px))
                except Exception as e:
                    logger.warning('OCR cellule échouée (num=%s) : %s', num, e)
                    continue
                if txt:
                    parts.append(txt)
            if parts:
                descriptions[num] = '\n'.join(parts)

    return descriptions, True


def _apply_descriptions(nodes, descriptions):
    """Pose le libellé OCR sur chaque nœud de l'arbre (par num)."""
    for n in nodes:
        txt = descriptions.get(n['num'])
        if txt:
            n['label'] = txt
        _apply_descriptions(n['children'], descriptions)


# ─── Helpers bas niveau ───────────────────────────────────────────────────────

def _parse_date_str(s):
    try:
        d, m, y = s.split('/')
        return date_type(int(y), int(m), int(d))
    except Exception:
        return None


# Nombre format français, signe optionnel : "1 668,00", "57,78", "-2 248,00"
# (les lignes de financement sont négatives — le signe doit être conservé)
_NUMBER_RE = re.compile(r'-?\d[\d ]*,\d{2}')
# Token alphabétique = unité (M2, F, U, Ml, J, KG, …)
_UNIT_RE = re.compile(r'\b([A-Za-z][A-Za-z0-9/]*)\b')


def _parse_amount(s):
    """"1 668,00" → Decimal("1668.00") ; "-2 248,00" → Decimal("-2248.00")."""
    if not s:
        return Decimal('0')
    s = str(s).strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
    neg = s.startswith('-')
    s = re.sub(r'[^\d.]', '', s)
    if not s:
        return Decimal('0')
    try:
        d = Decimal(s)
        return -d if neg else d
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


# ─── Extraction des blocs adresse par coordonnées ────────────────────────────

def _parse_addr_block(lines):
    """Convertit une liste de lignes texte en dict {nom, adresse, cp, ville}."""
    if not lines:
        return {}
    result = {'nom': _dedup_line(lines[0]), 'adresse': '', 'cp': '', 'ville': ''}
    if len(lines) > 1:
        cp, ville = _parse_cp_ville(lines[-1])
        result['cp'] = cp
        result['ville'] = ville
        mid = [_dedup_line(l) for l in lines[1:-1]]
        result['adresse'] = ' '.join(mid)
    return result


def _extract_address_blocks(page):
    """Sépare les blocs adresse chantier (colonne gauche) et MO (colonne droite)
    en utilisant les coordonnées x des mots. Retourne (chantier_lines, mo_lines).

    Si la colonne chantier est vide (cas particulier sans adresse chantier distincte),
    chantier_lines est vide — l'appelant doit alors utiliser mo_lines pour les deux.
    """
    words = page.extract_words()

    # Trouver la ligne d'en-tête : "Coordonnées du Maître d'Ouvrage" donne le x de la col droite
    header_y = None
    coord_x = None
    for w in words:
        if 'coordonn' in w['text'].lower():
            same_line = [ww for ww in words if abs(ww['top'] - w['top']) < 6]
            if any('ouvrage' in ww['text'].lower() or 'ma' in ww['text'].lower()
                   for ww in same_line):
                coord_x = w['x0']
                header_y = w['top']
                break

    if header_y is None or coord_x is None:
        return [], []

    # Trouver la limite basse : "Contact" (ou "Secteur") après la ligne d'en-tête
    end_y = None
    for w in words:
        if w['top'] > header_y + 6 and w['text'].lower().startswith('contact'):
            end_y = w['top']
            break
    if end_y is None:
        end_y = header_y + 200  # fallback : 200px sous l'en-tête

    # Collecter les mots entre header_y et end_y, séparer par x
    chantier_by_y = {}
    mo_by_y = {}
    for w in words:
        if w['top'] <= header_y + 3 or w['top'] >= end_y:
            continue
        bucket = round(w['top'] / 4) * 4
        entry = (w['x0'], w['text'])
        if w['x0'] < coord_x - 5:
            chantier_by_y.setdefault(bucket, []).append(entry)
        else:
            mo_by_y.setdefault(bucket, []).append(entry)

    def to_lines(by_y):
        lines = []
        for y in sorted(by_y):
            words_sorted = sorted(by_y[y], key=lambda e: e[0])
            lines.append(' '.join(t for _, t in words_sorted).strip())
        return [l for l in lines if l]

    return to_lines(chantier_by_y), to_lines(mo_by_y)


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

    # Blocs adresses : colonne gauche = chantier, colonne droite = MO
    # On utilise les coordonnées x des mots pour séparer les deux colonnes.
    # Si la colonne chantier est vide (particulier sans adresse chantier distincte),
    # le chantier reprend les coordonnées du MO.
    chantier_lines, mo_lines = _extract_address_blocks(pdf.pages[0])
    mo = _parse_addr_block(mo_lines)
    chantier = _parse_addr_block(chantier_lines) if chantier_lines else mo

    result['client_nom'] = mo.get('nom', '')
    result['client_adresse'] = mo.get('adresse', '')
    result['client_cp'] = mo.get('cp', '')
    result['client_ville'] = mo.get('ville', '')
    result['chantier_nom'] = chantier.get('nom', result['client_nom'])
    result['chantier_adresse'] = chantier.get('adresse', result['client_adresse'])
    result['chantier_cp'] = chantier.get('cp', result['client_cp'])
    result['chantier_ville'] = chantier.get('ville', result['client_ville'])

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
    """Extrait (qty, unite, mat_str, mo_str, total_str) depuis la partie données.

    `total_str` = « Total Net de Taxes » imprimé par EBP (dernière colonne), utilisé
    pour recouper chaque ligne (cf. _create_node) ; '' si la ligne ne l'affiche pas.

    Exemples :
      "57,78 M2 14,24 822,79"           → qty=57,78 unit=M2 mat=14,24 mo='' total=822,79
      "1,00 J 0,00 420,00 420,00"       → qty=1,00  unit=J  mat=0,00  mo=420,00 total=420,00
      "1,00 1 668,00 2 040,00 3 708,00" → qty=1,00  unit=''  mat=1668 mo=2040 total=3708
      "0,00"                             → qty=''   unit=''  mat=0,00 mo='' total=''
    """
    numbers = _NUMBER_RE.findall(rest)

    if not numbers:
        return '', '', '', '', ''

    # Cas particulier : une seule valeur → forfait ou Pour Mémoire
    if len(numbers) == 1:
        val = numbers[0]
        if val == '0,00':
            return '', '', '0,00', '', ''
        return val, '', '', '', ''

    # Cherche une unité alphabétique immédiatement après le premier nombre
    first_num_m = _NUMBER_RE.search(rest)
    first_num_end = first_num_m.end()
    rest_after_first = rest[first_num_end:].lstrip()
    unit_m = _UNIT_RE.match(rest_after_first)

    if unit_m:
        qty = numbers[0]
        unit = unit_m.group(1)
        after_unit = rest_after_first[unit_m.end():]
    else:
        qty = numbers[0]
        unit = ''
        after_unit = rest_after_first

    mat, mo, total = _split_costs(after_unit, qty)
    return qty, unit, mat, mo, total


# Groupe « nombre-esque » : chiffres/espaces avec au plus une partie décimale finale.
# Sert à valider un groupe de jetons recollés (un coût ou le total) — la validation
# forte vient du recoupement arithmétique avec le total, pas du motif seul.
_NUMISH_RE = re.compile(r'-?[\d ]+(?:,\d{1,2})?')
_ENDS_2DEC_RE = re.compile(r',\d{2}$')


def _split_costs(after_unit, qty_str):
    """Sépare (mat_str, mo_str, total_str) depuis la zone après qté+unité.

    EBP imprime des montants lexicalement ambigus : coûts forfaitaires entiers
    (« 50 », « 2944 »), coûts à 1 décimale (« 17,5 »), totaux à 2 décimales avec
    séparateur de milliers espacé (« 1 068,00 »). « 89 1 068,00 » peut se lire
    « 89 » + « 1 068,00 » ou « 89 1 068,00 ». On lève l'ambiguïté par RECOUPEMENT :
    on cherche la partition en colonnes (mat | mo | total) ou (mat | total) telle que
    qté × (mat+mo) == total imprimé (toujours à 2 décimales, dernière colonne).
    À défaut de recoupement (ligne réellement incohérente : erreur EBP / lecture
    douteuse), on revient à l'ancien découpage naïf → le marqueur « ⚠ ÉCART » signale
    la ligne. Aucune incidence sur les lignes déjà cohérentes.
    """
    toks = after_unit.split()
    if not toks:
        return '', '', ''

    qty = _parse_amount(qty_str)
    n = len(toks)

    def numish(s):
        return bool(_NUMISH_RE.fullmatch(s)) and any(c.isdigit() for c in s)

    def is_total(s):
        return numish(s) and bool(_ENDS_2DEC_RE.search(s))

    def join(a, b):
        return ' '.join(toks[a:b])

    def recon(mat, mo, tot):
        return ((qty * (_parse_amount(mat) + _parse_amount(mo))).quantize(
                    _CENTS, rounding=ROUND_HALF_UP)
                == _parse_amount(tot).quantize(_CENTS, rounding=ROUND_HALF_UP))

    if qty != 0:
        # 3 colonnes : mat | mo | total
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                mat, mo, tot = join(0, i), join(i, j), join(j, n)
                if numish(mat) and numish(mo) and is_total(tot) and recon(mat, mo, tot):
                    return mat, mo, tot
        # 2 colonnes : mat | total (colonne MO masquée car = 0)
        for i in range(1, n):
            mat, tot = join(0, i), join(i, n)
            if numish(mat) and is_total(tot) and recon(mat, '0', tot):
                return mat, '', tot

    # Repli : aucun recoupement (ou pas de qté / pas de total). Découpage naïf
    # identique à l'historique — préserve le comportement sur les lignes douteuses.
    amounts = _NUMBER_RE.findall(after_unit)
    if len(amounts) >= 3:
        return amounts[-3], amounts[-2], amounts[-1]
    if len(amounts) == 2:
        return amounts[0], '', amounts[1]
    if len(amounts) == 1:
        return amounts[0], '', ''
    return '', '', ''


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
                        and re.match(r'^-?\d[\d ]*,\d{2}', line)):
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
    m = re.match(rf'^({_NODE_NUM})(?:\s+(.*))?$', line)
    if not m:
        return None

    num = m.group(1)
    rest = (m.group(2) or '').strip()

    if not rest:
        return {
            'num': num, 'depth': num.count('.') + 1, 'label': '',
            'qty_str': '', 'unite': '', 'mat_str': '', 'mo_str': '', 'total_str': '',
            'children': [], 'desc_extra': '',
        }

    qty, unit, mat, mo, total = _parse_amounts_from_text(rest)
    return {
        'num': num, 'depth': num.count('.') + 1, 'label': '',
        'qty_str': qty, 'unite': unit, 'mat_str': mat, 'mo_str': mo, 'total_str': total,
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
    errors = []      # bloquants (réf introuvable, lecture impossible)
    warnings = []    # non bloquants (OCR indisponible…) — l'import a quand même lieu

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
            descriptions, ocr_ok = _extract_descriptions(pdf)
            _apply_descriptions(tree, descriptions)

    except Exception as e:
        errors.append(f'Erreur lecture PDF : {e}')
        return {
            'reference': '', 'date': None, 'date_validite': None,
            'equipe_hint': '', 'objet': '',
            'client': {}, 'chantier': {},
            'tree': [], 'total_pdf': None, 'nb_lignes': 0,
            'errors': errors, 'warnings': warnings,
        }

    if not meta['reference']:
        errors.append('Référence du devis introuvable dans le PDF.')

    if not ocr_ok:
        warnings.append(
            'OCR indisponible — descriptions de lignes non importées '
            '(seuls les numéros figurent). Installer Tesseract pour les récupérer.'
        )

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
        'warnings': warnings,
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

        # Recoupement par ligne : total calculé (qté × coûts) vs « Total Net de
        # Taxes » imprimé par EBP. En cas d'écart au centime, on marque la ligne
        # DEVANT son descriptif → on repère la ligne mal lue dans le devis.
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

        # != 0 (et non > 0) : les lignes de financement portent des coûts négatifs
        if mat != 0:
            LigneDevis.objects.create(
                devis=devis, parent=ligne,
                type_ligne='FMAT', description='Matériaux',
                quantite=Decimal('1'), cout_unitaire=mat,
                ordre=ordre[0],
            )
            ordre[0] += 1

        if mo != 0:
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


def _normalise_nom(s):
    """Minuscules + suppression des accents pour comparaison souple."""
    s = s.strip().lower()
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')


def _find_or_create_client(client_data, user):
    """Recherche un client par nom normalisé (casse + accents), le crée si absent."""
    from .models import Client
    nom = (client_data.get('nom') or 'Inconnu').strip()
    nom_cible = _normalise_nom(nom)
    for c in Client.objects.only('id', 'nom'):
        if _normalise_nom(c.nom) == nom_cible:
            return c
    return Client.objects.create(
        nom=nom,
        adresse=client_data.get('adresse', ''),
        code_postal=client_data.get('cp', ''),
        ville=client_data.get('ville', ''),
        created_by=user,
    )


def create_from_parsed(parsed, equipe, user):
    """Crée un Devis + ses LigneDevis depuis les données parsées. Retourne (devis, warnings)."""
    from .models import Client, Devis
    from decimal import ROUND_HALF_UP

    warnings = list(parsed.get('warnings', [])) + list(parsed.get('errors', []))

    client_data = parsed.get('client', {})
    client = _find_or_create_client(client_data, user)

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
        importe_pdf=parsed.get('importe_pdf', True),
        created_by=user,
    )

    ordre = [0]
    for root_node in parsed.get('tree', []):
        _create_node(devis, root_node, None, ordre)

    # Contrôle systématique : total calculé vs « Montant Net de Taxes » du PDF.
    # En cas d'anomalie, on marque l'OBJET du devis (visible en liste) + une note.
    total_pdf = parsed.get('total_pdf')
    total_calc = devis.total_brut()
    flag = note = ''

    if total_pdf is None:
        flag = '⚠ TOTAL PDF INTROUVABLE'
        note = (
            f'⚠ Import PDF — le « Montant Net de Taxes » est introuvable dans le PDF : '
            f'total non vérifié (calculé : {_fmt_eur(total_calc)} €).'
        )
    else:
        ecart = abs(
            total_calc.quantize(_CENTS, rounding=ROUND_HALF_UP) -
            Decimal(str(total_pdf)).quantize(_CENTS, rounding=ROUND_HALF_UP)
        )
        # Les totaux doivent être identiques au centime → toute différence est signalée.
        if ecart > Decimal('0'):
            flag = f'⚠ ÉCART TOTAL {_fmt_eur(ecart)} €'
            note = (
                f'⚠ Import PDF — Écart de {_fmt_eur(ecart)} € entre le total calculé '
                f'({_fmt_eur(total_calc)} €) et le Montant Net de Taxes du PDF '
                f'({_fmt_eur(total_pdf)} €). À vérifier : ligne(s) marquées « ⚠ ÉCART » '
                f'dans le devis, ou arrondi EBP.'
            )

    if flag:
        devis.chantier = (flag if not devis.chantier
                          else f'{flag} — {devis.chantier}')[:300]
        devis.notes = note
        devis.save(update_fields=['chantier', 'notes'])
        warnings.append(note)

    return devis, warnings
