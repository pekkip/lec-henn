/* ============================================================================
 * CB Bretagne — socle JS partagé (chargé par base.html via {% static %}).
 *
 * Regroupe les utilitaires d'arbre + un wrapper fetch/CSRF qui étaient
 * dupliqués inline dans les éditeurs. Chargé AVANT le JS inline des pages :
 * les helpers sont donc disponibles dès le `{% block extra_js %}`.
 *
 * ⚠️ PARITÉ SERVEUR — NE PAS DIVERGER SANS SYNCHRONISER :
 *   `TreeHelpers.calcTotal / calcMO / calcMat` répliquent la logique de
 *   `core/totaux.py` (`_total_depuis_map`, `total_mo_devis`, `mo_mat_lignes`).
 *   Le test `test_totaux_identiques_aux_methodes_modele` garde le côté serveur.
 *   Toute modification du calcul ici DOIT être reportée dans `core/totaux.py`
 *   (et réciproquement). Voir le commentaire jumeau en tête de totaux.py.
 * ==========================================================================*/

/* Utilitaires d'arbre de lignes (TITRE / C / S / OUV / MO / MAT / FMO / FMAT…).
 * Versions de référence, identiques à celles qui vivaient dans devis_detail.html
 * et bibliotheque.html. facture_detail / facture_compta_detail gardent leurs
 * propres helpers (sémantique différente : id réel vs _nid, arbre à 2 niveaux). */
const TreeHelpers = (function () {

  // Allocateur d'identifiants de nœud, unique par chargement de page.
  // Partagé entre assignNids (arbre chargé) et la création/duplication de
  // nœuds côté éditeur, pour qu'aucun _nid ne collisionne.
  let _nidCounter = 0;
  function nextNid() { return '_' + (_nidCounter++); }

  function assignNids(nodes) {
    nodes.forEach(n => {
      n._nid = nextNid();
      if (n.enfants) assignNids(n.enfants);
    });
  }

  function findNode(nodes, nid) {
    for (const n of nodes) {
      if (n._nid === nid) return n;
      if (n.enfants) { const f = findNode(n.enfants, nid); if (f) return f; }
    }
    return null;
  }

  function delFromTree(nodes, nid) {
    const i = nodes.findIndex(n => n._nid === nid);
    if (i >= 0) { nodes.splice(i, 1); return true; }
    for (const n of nodes) { if (n.enfants && delFromTree(n.enfants, nid)) return true; }
    return false;
  }

  // ── CALCULS (parité core/totaux.py — cf. avertissement en tête) ──
  function calcTotal(n) {
    if (n.type_ligne === 'TITRE') {
      const sousTot = (n.enfants || []).reduce((s, c) => s + calcTotal(c), 0);
      return (n.quantite || 1) * sousTot;
    }
    if (!n.enfants || !n.enfants.length) return (n.quantite || 0) * (n.cout_unitaire || 0);
    return (n.quantite || 1) * n.enfants.reduce((s, c) => s + calcTotal(c), 0);
  }

  function calcMO(n) {
    if (n.type_ligne === 'TITRE') {
      return (n.quantite || 1) * (n.enfants || []).reduce((s, c) => s + calcMO(c), 0);
    }
    if (!n.enfants || !n.enfants.length)
      return ['MO', 'FMO'].includes(n.type_ligne) ? (n.quantite || 0) * (n.cout_unitaire || 0) : 0;
    return (n.quantite || 1) * n.enfants.reduce((s, c) => s + calcMO(c), 0);
  }

  function calcMat(n) {
    if (n.type_ligne === 'TITRE') {
      return (n.quantite || 1) * (n.enfants || []).reduce((s, c) => s + calcMat(c), 0);
    }
    if (!n.enfants || !n.enfants.length)
      return ['MAT', 'FMAT'].includes(n.type_ligne) ? (n.quantite || 0) * (n.cout_unitaire || 0) : 0;
    return (n.quantite || 1) * n.enfants.reduce((s, c) => s + calcMat(c), 0);
  }

  // Format français à 2 décimales, sans symbole € (le € est ajouté par le rendu).
  function fmtV(v) {
    if (v === null || v === undefined) return '—';
    return Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  return { nextNid, assignNids, findNode, delFromTree, calcTotal, calcMO, calcMat, fmtV };
})();

/* Jeton CSRF de la page. base.html rend toujours un {% csrf_token %} (formulaire
 * de déconnexion) pour un utilisateur authentifié → fiable sur tous les écrans
 * de l'app. */
function getCsrfToken() {
  const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return el ? el.value : '';
}

/* Wrapper unique pour les POST JSON + CSRF. Renvoie la réponse JSON parsée
 * (les appelants lisent `data.ok` / `data.error` comme avant). Lève en cas
 * d'erreur réseau (fetch rejeté) — les appelants conservent leur try/catch. */
async function apiPost(url, payload) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
    body: JSON.stringify(payload || {}),
  });
  return resp.json();
}

/* Anti-rebond : retarde l'appel de `fn` tant que de nouveaux appels arrivent
 * dans la fenêtre `delay`. Utilisé par les saisies à sauvegarde différée. */
function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

/* ── FEEDBACK DE SAUVEGARDE UNIFIÉ ─────────────────────────────────────────
 * Un seul style de toast pour toute l'app (bandeau flottant bas-droite ;
 * `ok` = vert, `err` = rouge ; cf. règles `.toast` dans app.css). Le div est
 * créé paresseusement → aucune page n'a besoin de déclarer `<div id="toast">`. */
let _toastTimer;
function showToast(msg, type = 'ok') {
  let t = document.getElementById('toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = `toast ${type} show`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}

/* ── CALENDRIER DE PLAGE PARTAGÉ ───────────────────────────────────────────
 * Composant unique des 3 modales du planning/émargement (affecter un chantier,
 * prêt d'équipier, événement). Rend une grille de mois (7 col.), gère la
 * sélection d'une plage et la navigation de mois. Styles : `.cal*` dans app.css
 * (plage turquoise, jours pris en ambre, aujourd'hui = point prune).
 *
 * opts :
 *   grid       (élément)  conteneur de la grille                    — requis
 *   monthLabel (élément)  reçoit « Mars 2026 »                      — requis
 *   mode       'range' (clic-glissé début→fin) | 'start' (clic =
 *              début, fin calculée par computeEnd)        — défaut 'range'
 *   computeEnd (startIso) => endIso                  — requis en mode 'start'
 *   isBusy     (iso) => false | true | 'titre'  marque .busy (+ title) — opt.
 *   onChange   (startIso, endIso) => void   après chaque changement   — opt.
 *
 * API : nav(dir), goToMonth(y,m), setRange(s,e), clear(), getStart(),
 *       getEnd(), render().
 */
function RangeCalendar(opts) {
  const MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet',
                'Août','Septembre','Octobre','Novembre','Décembre'];
  const mode = opts.mode || 'range';
  const now  = new Date();
  let year = now.getFullYear(), month = now.getMonth();
  let start = null, end = null;
  let dragging = false, anchor = null, hover = null;

  function iso(y, m, d) {
    return y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  }

  function fireChange() { if (opts.onChange) opts.onChange(start, end); }

  function commitDrag() {
    if (!anchor) return;
    const h = hover || anchor;
    start = anchor <= h ? anchor : h;
    end   = anchor <= h ? h : anchor;
  }

  function render() {
    opts.monthLabel.textContent = MOIS[month] + ' ' + year;
    const grid = opts.grid;
    grid.innerHTML = '';
    ['L','M','M','J','V','S','D'].forEach(function(h) {
      const el = document.createElement('div');
      el.className = 'cal-h'; el.textContent = h; grid.appendChild(el);
    });

    // Plage affichée : en cours de glissé, dérivée d'anchor/hover.
    let rS = start, rE = end;
    if (dragging && anchor) {
      const h = hover || anchor;
      rS = anchor <= h ? anchor : h;
      rE = anchor <= h ? h : anchor;
    }

    const todayIso = new Date().toISOString().slice(0, 10);
    const firstDow = new Date(year, month, 1).getDay();
    const off      = firstDow === 0 ? 6 : firstDow - 1;
    const dim      = new Date(year, month + 1, 0).getDate();
    const prevDim  = new Date(year, month, 0).getDate();

    for (let i = off - 1; i >= 0; i--) {
      const el = document.createElement('div');
      el.className = 'cal-d out'; el.textContent = prevDim - i; grid.appendChild(el);
    }
    for (let day = 1; day <= dim; day++) {
      const ds = iso(year, month, day);
      const el = document.createElement('div');
      el.className = 'cal-d'; el.textContent = day;
      if (ds === todayIso) el.classList.add('today');
      if (opts.isBusy) {
        const b = opts.isBusy(ds);
        if (b) { el.classList.add('busy'); if (typeof b === 'string') el.title = b; }
      }
      if (rS && rE) {
        if (ds === rS && ds === rE) el.classList.add('s', 'e');
        else if (ds === rS)         el.classList.add('s');
        else if (ds === rE)         el.classList.add('e');
        else if (ds > rS && ds < rE) el.classList.add('in');
      } else if (rS && ds === rS) {
        el.classList.add('s', 'e');
      }
      bindCell(el, ds);
      grid.appendChild(el);
    }
    const total = off + dim;
    const fill  = total % 7 === 0 ? 0 : 7 - total % 7;
    for (let i = 1; i <= fill; i++) {
      const el = document.createElement('div');
      el.className = 'cal-d out'; el.textContent = i; grid.appendChild(el);
    }
  }

  function bindCell(el, ds) {
    if (mode === 'start') {
      el.addEventListener('click', function() {
        start = ds;
        end   = opts.computeEnd ? opts.computeEnd(ds) : ds;
        anchor = start; hover = end;
        render(); fireChange();
      });
    } else {
      el.addEventListener('mousedown', function(e) {
        e.preventDefault();
        dragging = true; anchor = ds; hover = ds; render();
      });
      el.addEventListener('mouseenter', function() {
        if (dragging) { hover = ds; render(); }
      });
      el.addEventListener('mouseup', function() {
        if (dragging) { dragging = false; commitDrag(); render(); fireChange(); }
      });
    }
  }

  // Fin de glissé relâché hors de la grille.
  document.addEventListener('mouseup', function() {
    if (dragging) { dragging = false; commitDrag(); render(); fireChange(); }
  });

  return {
    el: opts.grid,
    nav: function(dir) {
      month += dir;
      if (month > 11) { month = 0; year++; }
      if (month < 0)  { month = 11; year--; }
      render();
    },
    goToMonth: function(y, m) { year = y; month = m; render(); },
    setRange: function(s, e) {
      start = s; end = e || s;
      anchor = s; hover = e || s;
      if (s) { const d = new Date(s + 'T12:00:00'); year = d.getFullYear(); month = d.getMonth(); }
      render(); fireChange();
    },
    clear: function() { start = end = anchor = hover = null; render(); fireChange(); },
    getStart: function() { return start; },
    getEnd:   function() { return end; },
    render: render,
  };
}

/* Garde-fou de sortie de page : avertit (boîte native du navigateur) si des
 * modifications ne sont pas sauvegardées. Couvre fermeture d'onglet,
 * rechargement ET navigation arrière/avant (Alt+←). `isDirty` est rappelé à
 * chaque tentative de sortie pour lire l'état courant. */
function installUnloadGuard(isDirty) {
  window.addEventListener('beforeunload', e => {
    if (isDirty()) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
}
