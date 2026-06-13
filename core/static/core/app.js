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
