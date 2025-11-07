/**
 * PG-Lazy-Prompt.js — v3.14
 * Build for in‑node "Lazy Prompt" (ComfyUI extension)
 *
 * What it does
 * - Adds an in‑node "History" button and a minimal searchable panel to re‑insert past prompts.
 * - Auto‑refreshes UI after writes to /pg/history/* endpoints (list/preview stays in sync).
 * - Optional auto‑layout from current node.size; manual CFG overrides still available.
 *
 * Key switches
 * - CFG.AUTO_FROM_NODE_SIZE = true → button positions/sizes derive from the node’s current size
 * - CFG.AUTO_RATIOS → tweak ratios without rebuilding the file
 * - Anchor mode: CFG.ANCHOR = 'between' | 'port' | 'fixed'
 *
 * How to override config at runtime (before this script runs):
 *   window.__PGHIST_CFG = { DEBUG: true, ANCHOR: 'port' };
 *
 * Author: Piotr Gredka & GPT. License: MIT.
 */

import { app } from "../../scripts/app.js";

(function(){
  if (window.__PG_HISTORY_V314__) return; window.__PG_HISTORY_V314__ = true;
  
  // Auto‑refresh after saving to history (writing endpoints /pg/history/*)
  (function installPgHistoryAutoRefresh(){
    if (window.__PGH_AUTOREFRESH__) return; window.__PGH_AUTOREFRESH__ = true;
    var origFetch = window.fetch.bind(window);
    function isWrite(url, init){
      try{
        if (typeof url !== 'string') return false;
        if (url.indexOf('/pg/history/') !== 0) return false;
        var m = (init && (init.method||'GET')).toUpperCase();
        if (m !== 'POST' && m !== 'PUT' && m !== 'DELETE') return false;
        return !/(?:\/list|\/get|\/prefs)(?:\?|$)/.test(url);
      }catch(_){ return false; }
    }
    function pickNode(){
      try{
        var g = app && app.graph; var c = app && app.canvas;
        var sel = (c && c.selected_nodes && c.selected_nodes[0]) || null;
        if (sel) return sel;
        var nodes = (g && g._nodes) || [];
        for (var i=0;i<nodes.length;i++){
          var n = nodes[i];
          if (n && n.widgets && findWidget(n,'history_select')) return n;
        }
      }catch(_){ }
      return null;
    }
    window.fetch = function(url, init){
      var p = origFetch(url, init);
      try{
        if (isWrite(url, init)){
          p.then(function(res){
            try{
              if (res && res.ok){ var node = pickNode(); if (node) runRefresh(node); }
            }catch(_){ }
          }).catch(function(){});
        }
      }catch(_){ }
      return p;
    };
  })();

  // ---------------- CONFIG (you can override via window.__PGHIST_CFG = {...}) ----------------
  var CFG = window.__PGHIST_CFG = Object.assign({
    // Visibility filters (from v3.13)
    LIMIT_TO_NODE_WITH_SLOT: true,
    ONLY_FOR_NODE_ID: null,
    ONLY_FOR_TITLE_RX: null,

    // Anchor mode: 'between' | 'port' | 'fixed'
    ANCHOR: 'port',

    // Manual constants (when AUTO_FROM_NODE_SIZE = false)
    X_LEFT: 30,
    Y_OFFSET: 10,
    GAP: 0,
    FIXED_X: 20,
    FIXED_Y: 120,
    BTN_W: 42,
    BTN_H: 24,
    PAD: 8,
    R: 6,
    FONT: '12px sans-serif',
    LABEL_HISTORY: 'History…',

    // Auto from node.size
    AUTO_FROM_NODE_SIZE: true,        // enable auto‑scaling
    AUTO_RATIOS: {                    // ratios relative to node.size
      X_LEFT: 0.33,                   // % of node width
      GAP: 0,                         // % of node height
      BTN_W: 0.32,                    // % of width
      BTN_H: 0.39,                    // % of height
      PAD:   0.50                     // % of width
    },
    AUTO_CLAMP: {                     // safe clamps
      X_LEFT: [25, 500],
      GAP:    [0, 0],
      BTN_W:  [22, 500],
      BTN_H:  [10, 24],
      PAD:    [6, 16]
    },

    DEBUG: false
  }, window.__PGHIST_CFG || {});

  var DBG = !!CFG.DEBUG; function dbg(){ if (!DBG) return; try{ console.log.apply(console, ['[pg-history v3.14]'].concat(Array.prototype.slice.call(arguments))); }catch(_){ } }

  // ---------------- Helpers ----------------
  function app(){ return (window.app || null); }
  function graph(){ var a = app(); return a && a.graph ? a.graph : null; }
  function findWidget(node, name){ if (!node || !node.widgets) return null; for (var i=0;i<node.widgets.length;i++){ var w=node.widgets[i]; if (w && w.name===name) return w; } return null; }
  function get(node, key, def){ var w=findWidget(node,key); return (w&&typeof w.value!=='undefined')?w.value:def; }
  const PG_LAZY_NAMES = new Set([
    // class names
    'PgLazyPrompt', 'PgLazyPromptMini', 'PgLazyPromptExt', 'PgPromptSimple',
    // display titles as they appear in ComfyUI UI
    'Lazy Prompt', 'Lazy Prompt (mini)', 'Lazy Prompt (ext)', 'Simple Prompt',
  ]);
  function _norm(x){
    return (x == null ? '' : String(x));
  }
  function _collectNames(x){
    if (!x) return [];
    const out = [];
    out.push(_norm(x.comfyClass), _norm(x.type), _norm(x.name), _norm(x.title));
    const c = x.constructor || {};
    out.push(_norm(c.comfyClass), _norm(c.type), _norm(c.name), _norm(c.title));
    return out.filter(Boolean);
  }
  function _matchesAnyLazyName(x){
    return _collectNames(x).some(n => PG_LAZY_NAMES.has(n));
  }
  function isPgLazyPromptClass(x){
    return _matchesAnyLazyName(x);
  }
  const __isMaybeOurs = (nodeType, nodeData) => (
    _matchesAnyLazyName(nodeType) || _matchesAnyLazyName(nodeData)
  );
  
  function _isCollapsed(n){ try { return !!(n && (n.flags?.collapsed || n.collapsed)); } catch(_) { return false; } }
  function setPreview(node, txt, opts){
    try{
      var s = String(txt == null ? '' : txt);
      var force = !!(opts && (opts.force || opts.clear));
      var singleLine = !/\n/.test(s);
      var shortish   = s.trim().length <= 160;
      var hasCue     = /(^\s*[✓✔✗✘]|\b(history|reloaded|loaded|saved|cleared|error|failed|ok|done|success)\b)/i.test(s);
      if (((singleLine && shortish && hasCue) || s.trim() === '') && !force){
        try{ console.debug('[PG history] status ignored for text fields:', s); }catch(_){ }
        return;
      }

      // Normal preview → split into POS / NEG by a line with "---"
      var parts = s.split(/\r?\n?-{3,}\r?\n?/);
      var pos = (parts[0] || '').trim();
      var neg = (parts.length > 1 ? parts.slice(1).join('\n---\n') : '').trim();

      function _findWidget(node, name){
        if (!node || !node.widgets) return null;
        for (var i=0; i<node.widgets.length; i++){
          var w = node.widgets[i];
          if (w && w.name === name) return w;
        }
        return null;
      }
      function _findByRegex(node, rx){
        if (!node || !node.widgets) return null;
        for (var i=0; i<node.widgets.length; i++){
          var w = node.widgets[i];
          if (w && typeof w.value === 'string' && rx.test(w.name)) return w;
        }
        return null;
      }

      var wPos = _findWidget(node, 'positive')
              || _findWidget(node, 'positive_text')
              || _findWidget(node, 'positive_prompt')
              || _findByRegex(node, /(^|[_-])pos(itive)?($|[_-])/i);

      var wNeg = _findWidget(node, 'negative')
              || _findWidget(node, 'negative_text')
              || _findWidget(node, 'negative_prompt')
              || _findByRegex(node, /(^|[_-])neg(ative)?($|[_-])/i);

      function _apply(w, val){
        try { w.value = String(val || ''); } catch(_){ }
        try { w.callback && w.callback(w.value, (window.app && window.app.canvas) || null, node, 0, 0); } catch(_){ }
        try { node && node.onWidgetChanged && node.onWidgetChanged(w, w.value); } catch(_){ }
      }

      if (wPos) _apply(wPos, pos);
      if (wNeg) _apply(wNeg, neg);

      try {
        var g = (window.app && window.app.graph) || null;
        g && g.setDirtyCanvas && g.setDirtyCanvas(true, true);
      } catch(_){ }
    }catch(_){ /* silent */ }
  }
  function pgNotifyStatus(msg){
    try { console.debug('[PG history]', msg); } catch(_){ }
  }
  function redraw(){ try{ graph()&&graph().setDirtyCanvas&&graph().setDirtyCanvas(true,true);}catch(_){} }
  function dedupe(a){ var m=Object.create(null),o=[]; for (var i=0;i<a.length;i++){ var v=String(a[i]); if(!m[v]){m[v]=1;o.push(v);} } return o; }
  function getHistoryPath(node){
    // Minimal: prefer the node's properties; fall back to 'prompt_history.json'
    try{
      const p = node && node.properties && node.properties.history_path;
      return (typeof p === 'string' && p.trim()) ? p : 'prompt_history.json';
    }catch(_){ return 'prompt_history.json'; }
  }
  function getMaxEntries(node){ var v=parseInt(get(node,'max_entries',500),10); return isNaN(v)||v<=0?500:v; }
  function widgetInfo(node, name) {
    if (!node || !node.widgets) return null;
    var y = (typeof node.widgets_start_y === 'number') ? node.widgets_start_y : 0;
    for (var i = 0; i < node.widgets.length; i++) {
      var w = node.widgets[i];
      if (!w) continue;
      var sz = null;
      try {
        sz = w.computeSize ? w.computeSize(node.size ? node.size[0] : 220) : null;
      } catch (_) {}
      var h = (sz && sz[1]) ? sz[1] : 20;
      if (w.name === name) return { y: y, h: h };
      y += h + 4;
    }
    return null;
  }
  function clamp(v, a, b){ v = Math.round(v); if (a!=null && v<a) v=a; if (b!=null && v>b) v=b; return v; }
  function autoFromSize(node){
    var s = node && node.size ? node.size : [220,150];
    var W = Math.max(100, s[0]|0), H = Math.max(80, s[1]|0);
    var rx = CFG.AUTO_RATIOS, cl = CFG.AUTO_CLAMP;
    return {
      X_LEFT: clamp(W * (rx.X_LEFT||0.07), cl.X_LEFT[0], cl.X_LEFT[1]),
      GAP:    clamp(H * (rx.GAP||0.08),    cl.GAP[0],    cl.GAP[1]),
      BTN_W:  clamp(W * (rx.BTN_W||0.34),  cl.BTN_W[0],  cl.BTN_W[1]),
      BTN_H:  clamp(H * (rx.BTN_H||0.09),  cl.BTN_H[0],  cl.BTN_H[1]),
      PAD:    clamp(W * (rx.PAD||0.04),    cl.PAD[0],    cl.PAD[1])
    };
  }

  // ---------------- Candidate filter ----------------
  function titleMatches(node) {
    var rx = CFG.ONLY_FOR_TITLE_RX;
    if (!rx) return true;
    try {
      if (typeof rx === 'string') rx = new RegExp(rx, 'i');
      var t = (node && (node.title || node.type) || '') + '';
      return !!(rx && rx.test && rx.test(t));
    } catch (_) {
      return false;
    }
  }
  function hasHistorySignature(node){
    try{
      if (!node) return false;

      // 1) Fast path: class/type match
      var cls = (node.comfyClass || node.type || '').toString();
      if (PG_LAZY_NAMES.has(cls)) return true;

      // 2) Heuristic by widget names (works even if some optional widgets are gone)
      var W = Array.isArray(node.widgets) ? node.widgets : [];
      if (!W.length) return false;

      // Build a quick name lookup
      var names = new Set();
      for (var i=0;i<W.length;i++){ var w=W[i]; if (w && w.name) names.add(String(w.name)); }

      // Core fields that are stable in your node
      var hasPos = names.has('positive') || /(^|[_-])pos(itive)?($|[_-])/i.test(Array.from(names).join(','));
      var hasNeg = names.has('negative') || /(^|[_-])neg(ative)?($|[_-])/i.test(Array.from(names).join(','));
      var hasLens = names.has('lens');
      var hasAll  = names.has('all_parameters_on');

      // Do NOT require: history_path, max_entries, history_select (they may be removed)
      return (hasPos && hasNeg && hasLens && hasAll);
    }catch(_){ return false; }
  }
  function isTargetNode(node) {
    if (!node) return false;
    if (CFG.ONLY_FOR_NODE_ID != null) return node.id === CFG.ONLY_FOR_NODE_ID;
    if (!titleMatches(node)) return false;
    if (CFG.LIMIT_TO_NODE_WITH_SLOT) return hasHistorySignature(node);
    return true;
  }

  // ---------------- API ----------------
  function dedupeByKeyHash(items){
    try{
      const seen = new Set();
      const out = [];
      for (const it of (items||[])){
        const kh = (it && it.key_hash) || '';
        const key = kh ? 'kh:'+kh : 'lbl:' + ((it && it.label_short) || '');
        if (seen.has(key)) continue;
        seen.add(key); out.push(it);
      }
      return out;
    }catch(_){ return Array.isArray(items) ? items : []; }
  }
  // --- 1) apiList: your async style, with `objects:true`
  async function apiList(node, searchQuery){
    const body = {
      history_path: getHistoryPath(node),
      max_entries:  getMaxEntries(node),
      objects: true,
    };
    if (searchQuery) {
      body.search_query = String(searchQuery).trim();
    }
    const r = await fetch('/pg/history/list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const j = await r.json().catch(function(){ return null; });
    if (!(r.ok && j && j.ok && Array.isArray(j.items)))
      throw new Error((j && (j.message||j.error)) || ('HTTP '+r.status));
    return dedupeByKeyHash(j.items);
  }
  async function apiPreview(node, sel) {
    var body = { history_path: getHistoryPath(node), history_select: sel };
    var r = await fetch('/pg/history/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    var j = await r.json().catch(function () { return null; });
    if (!(r.ok && j && j.ok)) throw new Error((j && j.message) || ('HTTP ' + r.status));
    return (j.preview_text || '');
  }
  async function apiRename(node, sel, customName) {
    var body = {
      history_path: getHistoryPath(node),
      history_select: sel,
      custom_name: String(customName || '').trim()
    };
    var r = await fetch('/pg/history/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    var j = await r.json().catch(function () { return null; });
    if (!(r.ok && j && j.ok)) throw new Error((j && j.message) || ('HTTP ' + r.status));
    return (j.custom_name || '');
  }
  // Helper: refresh list and preview
  function runRefresh(node){
    try{
      if (typeof apiList === 'function') {
        apiList(node).then(function(items){
          try{
            const hs = findWidget(node,'history_select');
            if(hs){
              if (Array.isArray(hs.options)) hs.options = items;
              if (Array.isArray(hs.values))  hs.values  = items;
              if (Array.isArray(items) && !items.includes(hs.value)) hs.value = (items[0] || 'none');
            }
          }catch(_){ }
          try{
            const hs = findWidget(node,'history_select');
            if(hs && hs.value && typeof apiPreview === 'function'){
              apiPreview(node, hs.value);
            }
          }catch(_){ }
        }).catch(function(){});
      }
    }catch(_){ }
  }
  // ---------------- Panel (new themable CSS for openPanelUI) ----------------
  ;(function css(){
    var ID = 'pg-history-panel-css-vNext';
    if (document.getElementById(ID)) return;
    var s = document.createElement('style'); s.id = ID;
    s.textContent = [
      // ===== Theme tokens you can override from outside =====
      ':root{',
      '  --pg-hist-width: 560px;',
      '  --pg-hist-radius: 12px;',
      '  --pg-hist-gap: 10px;',
      '  --pg-hist-overlay-bg: rgba(0,0,0,.28);',
      '  --pg-hist-card-bg: var(--comfy-menu-bg,#222);',
      '  --pg-hist-text: var(--comfy-text,#ddd);',
      '  --pg-hist-border: var(--comfy-input-border,#444);',
      '  --pg-hist-input-bg: var(--comfy-input-bg,#2a2a2a);',
      '  --pg-hist-hover: #333;',
      '  --pg-hist-shadow: 0 10px 30px rgba(0,0,0,.35);',
      '  --pg-hist-body-maxh: 42vh;',
      '}',

      // ===== Overlay & Card =====
      '.pg-hist-overlay{position:fixed;inset:0;z-index:9999;font-size:14px;background:var(--pg-hist-overlay-bg);}',
      '.pg-hist-card{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);',
      '  width:min(var(--pg-hist-width),calc(100vw - 32px));',
      '  color:var(--pg-hist-text);background:var(--pg-hist-card-bg);border:1px solid var(--pg-hist-border);',
      '  border-radius:var(--pg-hist-radius);box-shadow:var(--pg-hist-shadow);display:flex;flex-direction:column;overflow:hidden;}',

      // ===== Header =====
      '.pg-hist-header{display:flex;align-items:center;gap:var(--pg-hist-gap);padding:10px 12px;',
      '  border-bottom:1px solid var(--pg-hist-border);}',
      '.pg-hist-title{font-weight:500;opacity:.95;}',
      '.pg-hist-filter{flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--pg-hist-border);',
      '  background:var(--pg-hist-input-bg);color:var(--pg-hist-text);border-radius:8px;outline:none;}',
      '.pg-hist-filter::placeholder{opacity:.6;}',
      '.pg-hist-filter:focus{box-shadow:0 0 0 2px rgba(255,255,255,.08) inset;border-color:#666;}',

      // ===== Body / List =====
      '.pg-hist-body{height:var(--pg-hist-body-maxh);overflow:auto;}',
      '.pg-hist-list{display:block;}',
      '.pg-hist-row{padding:6px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;}',
      '.pg-hist-row:hover{background:var(--pg-hist-hover);}',
      '.pg-hist-empty,.pg-hist-status{padding:10px 12px;opacity:.8;}',

      // ===== Footer / Button =====
      '.pg-hist-footer{padding:10px 12px;border-top:1px solid var(--pg-hist-border);}',
      '.pg-hist-btn{display:block;width:100%;padding:6px 10px;border:1px solid var(--pg-hist-border);',
      '  background:var(--pg-hist-input-bg);color:var(--pg-hist-text);border-radius:8px;cursor:pointer;}',
      '.pg-hist-btn:hover{filter:brightness(1.06);}',
    ].join('\n');
    document.head.appendChild(s);
  })();

  function openPanelUI(node){
    // overlay & chrome
    var overlay = document.createElement('div'); overlay.className = 'pg-hist-overlay';
    var card    = document.createElement('div'); card.className    = 'pg-hist-card';
    var header  = document.createElement('div'); header.className  = 'pg-hist-header';
    var body    = document.createElement('div'); body.className    = 'pg-hist-body';
    var footer  = document.createElement('div'); footer.className  = 'pg-hist-footer';
    var status  = document.createElement('div'); status.className  = 'pg-hist-status'; status.textContent = 'Loading…';

    // header: title + filter (no close button)
    var title = document.createElement('div'); title.className = 'pg-hist-title'; title.textContent = 'History';
    var filter = document.createElement('input');
    filter.type = 'search';
    filter.className = 'pg-hist-filter';
    filter.placeholder = 'filter…';
    filter.autocapitalize = 'off'; filter.autocomplete = 'off'; filter.spellcheck = false;

    // destroy helper
    function destroy(){
      try { document.removeEventListener('keydown', escHandler); } catch(_){ }
      try { overlay.parentNode && overlay.parentNode.removeChild(overlay); } catch(_){ }
    }

    overlay.addEventListener('click', destroy);
    card.addEventListener('click', function(ev){ ev.stopPropagation(); });
    header.appendChild(title);
    header.appendChild(filter);

    // footer: New Prompt button (full width)
    var noneBtn = document.createElement('button');
    noneBtn.className = 'pg-hist-btn';
    noneBtn.textContent = 'New Prompt';
    noneBtn.style.display = 'block';
    noneBtn.style.width = '100%';
    noneBtn.onclick = function(){
      try { setPreview(node, '', { force: true }); } catch(_) { }
      destroy();
    };

    footer.appendChild(noneBtn);

    // assemble
    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    body.appendChild(status);

    // data & rendering
    var allItems = [];
    var listEl = null;

    function labelOf(it){
      return (it && (it.label_short || it.key_hash || it)) || '';
    }
    function matchItem(it, q){
      if (!q) return true;
      q = String(q).toLowerCase();
      var l = String(labelOf(it)).toLowerCase();
      if (l.includes(q)) return true;
      try {
        // Check positive and negative prompt content
        if (it && it.positive && String(it.positive).toLowerCase().includes(q)) return true;
        if (it && it.negative && String(it.negative).toLowerCase().includes(q)) return true;
        if (it && it.lens && String(it.lens).toLowerCase().includes(q)) return true;
        if (it && it.time_of_day && String(it.time_of_day).toLowerCase().includes(q)) return true;
        if (it && it.light_from && String(it.light_from).toLowerCase().includes(q)) return true;
      } catch(_){ }
      return false;
    }
    function renderList(){
      if (!listEl){
        listEl = document.createElement('div'); listEl.className = 'pg-hist-list';
        try { body.removeChild(status); } catch(_){ }
        body.innerHTML = '';
        body.appendChild(listEl);
      } else {
        listEl.innerHTML = '';
      }
      var q = filter.value.trim();
      // Use server-side search if query is provided
      if (q && allItems.length > 0) {
        // Client-side fallback for filtering (server already filtered if search_query was sent)
        var filtered = allItems.filter(function(it){ return matchItem(it, q); });
      } else {
        var filtered = allItems;
      }
      if (!filtered.length){
        var empty = document.createElement('div');
        empty.className = 'pg-hist-empty';
        empty.textContent = q ? 'No matches' : 'No history';
        listEl.appendChild(empty);
        return;
      }
      filtered.forEach(function(it){
        var lbl = (it && (it.label_short || it)) || '';
        var kh  = (it && it.key_hash) || '';
        var score = (it && it.search_score) || 100;
        var row = document.createElement('div');
        row.className = 'pg-hist-row';
        // Show score when searching, otherwise just label
        var displayText = (q && score < 100) ? (lbl + ' (' + score + '%)') : lbl;
        row.textContent = String(displayText);
        row.title = String(lbl);
        row.onclick = function(){
          status.textContent = 'Loading preview…';
          var sel = kh || String(lbl);
          apiPreview(node, sel).then(function(txt){
            try { setPreview(node, txt); } catch(_){ }
            destroy();
          }).catch(function(e){
            status.textContent = 'Error: ' + ((e && e.message) || String(e));
          });
        };
        // Right-click context menu for rename
        row.oncontextmenu = function(ev){
          ev.preventDefault();
          ev.stopPropagation();
          var currentName = (it && it.custom_name) || '';
          var newName = prompt('Rename entry:', currentName);
          if (newName !== null) {
            status.textContent = 'Renaming…';
            apiRename(node, kh, newName).then(function(){
              status.textContent = 'Renamed! Refreshing…';
              setTimeout(function(){
                apiList(node, q).then(function(items){
                  allItems = Array.isArray(items) ? items : [];
                  renderList();
                }).catch(function(e){
                  status.textContent = 'Error: ' + ((e && e.message) || String(e));
                });
              }, 300);
            }).catch(function(e){
              status.textContent = 'Rename failed: ' + ((e && e.message) || String(e));
            });
          }
        };
        listEl.appendChild(row);
      });
    }

    // interactions
    function escHandler(ev){ if (ev.key === 'Escape'){ destroy(); } }
    document.addEventListener('keydown', escHandler);

    // Filter input: send search query to server and re-render
    var filterTimeout = null;
    filter.addEventListener('input', function(){
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(function(){
        var q = filter.value.trim();
        status.textContent = 'Searching…';
        apiList(node, q).then(function(items){
          allItems = Array.isArray(items) ? items : [];
          renderList();
          try { status.style.display = 'none'; } catch(_){ }
        }).catch(function(e){
          status.textContent = 'Search error: ' + ((e && e.message) || String(e));
        });
      }, 250);
    });

    filter.addEventListener('keydown', function(ev){ if (ev.key === 'Escape'){ ev.stopPropagation(); destroy(); } });

    // load data
    apiList(node).then(function(items){
      allItems = Array.isArray(items) ? items : [];
      renderList();
      try { filter.focus(); filter.select(); } catch(_){ }
    }).catch(function(e){
      status.textContent = 'Error: ' + ((e && e.message) || String(e));
    });
  }

  window.__PG_HISTORY_OPEN_PANEL = function(node){ try{ openPanelUI(node); }catch(e){ console.error('[PG history] open', e); } };

  // ---------------- Draw (auto‑size aware) ----------------
  function attachUI(node){
    if (!node || node.__pg_hist_ui_attached_v314) return;
    if (!isTargetNode(node)) { dbg('skip node', node && (node.title||node.type), 'id=', node && node.id); return; }

    function _isCollapsed(n){ try { return !!(n && (n.flags?.collapsed || n.collapsed)); } catch(_) { return false; } }

    function myDraw(ctx){
      try{
        const n = this || node;
        if (_isCollapsed(n)){
          try { n.__pg_hist_ui_hit = []; } catch(_) {}
          return;
        }

        var S = CFG.AUTO_FROM_NODE_SIZE ? autoFromSize(node) : null;
        var X_LEFT = (S?S.X_LEFT:CFG.X_LEFT),
            GAP    = (S?S.GAP:CFG.GAP),
            BTN_W  = (S?S.BTN_W:CFG.BTN_W),
            BTN_H  = (S?S.BTN_H:CFG.BTN_H),
            PAD    = (S?S.PAD:CFG.PAD),
            R      = CFG.R;

        var x, y;
        if (CFG.ANCHOR === 'fixed'){
          x = CFG.FIXED_X; y = CFG.FIXED_Y;
        } else if (CFG.ANCHOR === 'port'){
          if (typeof node.getSlotPos === 'function' && node.inputs){
            for (var i = 0; i < node.inputs.length; i++) {
              var p = node.inputs[i];
              if (p && p.name === 'positive') {
                var lp = node.getSlotPos(true, i);
                if (lp) { x = X_LEFT; y = Math.max(4, lp[1] - Math.floor(BTN_H / 2)); }
                break;
              }
            }
          }
        } else {
          var prev = widgetInfo(node,'positive');
          var pos  = widgetInfo(node,'negative');
          var yBelowPrev = prev ? (prev.y + prev.h) : null;
          var yAbovePos  = pos  ? (pos.y - BTN_H)  : null;
          if (yBelowPrev!=null && yAbovePos!=null) y = Math.min(Math.max(yBelowPrev, 4), yAbovePos);
          else if (yBelowPrev!=null) y = yBelowPrev; else y = yAbovePos;
          x = X_LEFT; y = (y==null? ((typeof node.widgets_start_y==='number')?node.widgets_start_y:0) + 8 : y);
        }
        y += (CFG.Y_OFFSET|0);
        if (typeof x !== 'number' || typeof y !== 'number'){
          x = X_LEFT; y = ((typeof node.widgets_start_y==='number')?node.widgets_start_y:0) + 8 + (CFG.Y_OFFSET|0);
        }

        function rrect(ctx, x, y, w, h, r) {
          ctx.beginPath();
          ctx.moveTo(x + r, y);
          ctx.lineTo(x + w - r, y);
          ctx.quadraticCurveTo(x + w, y, x + w, y + r);
          ctx.lineTo(x + w, y + h - r);
          ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
          ctx.lineTo(x + r, y + h);
          ctx.quadraticCurveTo(x, y + h, x, y + h - r);
          ctx.lineTo(x, y + r);
          ctx.quadraticCurveTo(x, y, x + r, y);
          ctx.closePath();
        }

        var bx = x;
        ctx.save();
        ctx.font = CFG.FONT;
        rrect(ctx,bx,y,BTN_W,BTN_H,R);
        ctx.fillStyle='#2a2a2a'; ctx.fill();
        ctx.strokeStyle='#444'; ctx.stroke();
        ctx.fillStyle='#ddd';
        ctx.textAlign='center'; ctx.textBaseline='middle';
        ctx.font=CFG.BTN_FONT||CFG.FONT;
        ctx.fillText(CFG.LABEL_HISTORY, bx+BTN_W/2, y+BTN_H/2);
        ctx.restore();

        node.__pg_hist_ui_hit = [ {x:bx,y:y,w:BTN_W,h:BTN_H,id:'panel'} ];
      }catch(e){ /* ignore */ }
    }

    // ---- Wrap draw (single wrapper) --------------------------------------
    var __prevFG = node.onDrawForeground;
    node.onDrawForeground = function(ctx){
      if (typeof __prevFG === 'function'){
        try { __prevFG.apply(this, arguments); } catch(_){ }
      }
      return myDraw.call(this, ctx);
    };

    // ---- Keepalive (single interval) -------------------------------------
    node.__pg_hist_ui_keepalive = setInterval(function(){
      try {
        const fn = node.onDrawForeground;
        if (!fn || fn.toString().indexOf('myDraw') === -1){
          const prev = fn;
          node.onDrawForeground = function(ctx){
            if (typeof prev === 'function'){
              try { prev.apply(this, arguments); } catch(_){ }
            }
            const n = this || node;
            if (_isCollapsed(n)){
              try { n.__pg_hist_ui_hit = []; } catch(_){ }
              return;
            }
            return myDraw.call(this, ctx);
          };
        }
      } catch(_){ }
    }, 1000);

    // ---- Hit‑test ---------------------------------------------------------
    var __prevMD = node.onMouseDown;
    node.onMouseDown = function (e, localPos, graphcanvas) {
      const n = this || node;
      if (_isCollapsed(n)){
        return (typeof __prevMD === 'function') ? __prevMD.apply(this, arguments) : undefined;
      }
      try {
        const hits = n.__pg_hist_ui_hit || [];
        if (Array.isArray(hits) && hits.length){
          const x = localPos[0], y = localPos[1];
          for (let i = 0; i < hits.length; i++){
            const b = hits[i];
            const inside = x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h;
            if (inside){
              if (b.id === 'refresh'){
                apiList(n).then(function(){ pgNotifyStatus(n, '✓ History reloaded'); redraw(); }).catch(function(){});
              } else if (b.id === 'panel'){
                (window.__PG_HISTORY_OPEN_PANEL || openPanelUI)(n);
              }
              return true;
            }
          }
        }
      } catch(_){ }
      return (typeof __prevMD === 'function') ? __prevMD.apply(this, arguments) : undefined;
    };
    node.__pg_hist_ui_attached_v314 = true;
  }

  function mount() {
    var g = graph();
    if (!g) return false;
    try {
      var nodes = Array.from(g._nodes || g.nodes || []);
      for (var i = 0; i < nodes.length; i++) attachUI(nodes[i]);
      if (!app().__pg_history_v314) {
        app().registerExtension({
          name: 'pg.history.v314',
          nodeCreated: function (n) {
            try { attachUI(n); } catch (_) {}
          }
        });
        app().__pg_history_v314 = true;
      }
      return true;
    } catch (e) {
      console.error('[PG history] mount', e);
      return false;
    }
  }

  var t0=Date.now(); (function wait(){ if (mount()) return; if (Date.now()-t0>20000){ console.warn('[pg-history] waiting for app.graph...'); } setTimeout(wait,150); })();
})();

(function(){
  const EXT = 'pg.history.props.v3';
  if (globalThis[EXT]) return; globalThis[EXT] = true;

  const DEF_PATH = 'custom_nodes\\prompt_history.json';
  const DEF_MAX  = 500;

  function findWidget(node, name){
    try { return (node.widgets||[]).find(w=>w && w.name===name) || null; } catch(_) { return null; }
  }
  function hideWidget(w){ if (!w) return; try{ w.hidden=true; }catch(_){} try{ w.serialize=false; }catch(_){} }
  function setWidgetValue(node, w, val){
    if (!w) return; const g = app?.graph;
    try { w.value = val; } catch(_){ }
    try { w.callback && w.callback(w.value, app?.canvas, node, 0, 0); } catch(_){ }
    try { node?.onWidgetChanged?.(w, w.value); } catch(_){ }
    try { g?.setDirtyCanvas?.(true,true); } catch(_){ }
  }

  const PG_LAZY_NAMES = new Set([
    // class names
    'PgLazyPrompt', 'PgLazyPromptMini', 'PgLazyPromptExt', 'PgPromptSimple',
    // display titles as they appear in ComfyUI UI
    'Lazy Prompt', 'Lazy Prompt (mini)', 'Lazy Prompt (ext)', 'Simple Prompt',
  ]);
  function _norm(x){
    return (x == null ? '' : String(x));
  }
  function _collectNames(x){
    if (!x) return [];
    const out = [];
    out.push(_norm(x.comfyClass), _norm(x.type), _norm(x.name), _norm(x.title));
    const c = x.constructor || {};
    out.push(_norm(c.comfyClass), _norm(c.type), _norm(c.name), _norm(c.title));
    return out.filter(Boolean);
  }
  function _matchesAnyLazyName(x){
    return _collectNames(x).some(n => PG_LAZY_NAMES.has(n));
  }
  function isPgLazyPromptClass(x){
    return _matchesAnyLazyName(x);
  }
  const __isMaybeOurs = (nodeType, nodeData) => (
    _matchesAnyLazyName(nodeType) || _matchesAnyLazyName(nodeData)
  );

  function __attachPrefsOnce(nodeType){
    const proto = nodeType && nodeType.prototype;
    if (!proto || proto.__pg_prefs_attached__) return;

    const origCreated = proto.onNodeCreated;
    proto.onNodeCreated = function(){
      const r = (typeof origCreated === 'function') ? origCreated.apply(this, arguments) : undefined;

      const wPath = findWidget(this, 'history_path');
      const wMax  = findWidget(this, 'max_entries');
      if (!__isMaybeOurs(this?.constructor, this) && !wPath && !wMax) return r;
      if (this.__PG_PROPS_WIRED__) return r;

      const lsPath = localStorage.getItem('pg_history_path');
      const lsMax  = localStorage.getItem('pg_history_max');

      const initPath = (wPath && String(wPath.value||DEF_PATH))
                    || (this.properties?.history_path)
                    || lsPath
                    || DEF_PATH;
      const initMax  = (wMax  && parseInt(wMax.value||DEF_MAX))
                    || (this.properties?.max_entries)
                    || (lsMax ? parseInt(lsMax) : undefined)
                    || DEF_MAX;

      this.properties = this.properties || {};
      if (typeof this.addProperty === 'function'){
        if (!Object.prototype.hasOwnProperty.call(this.properties,'history_path')) this.addProperty('history_path', initPath, 'string');
        if (!Object.prototype.hasOwnProperty.call(this.properties,'max_entries'))  this.addProperty('max_entries',  initMax,  'number', {min:1,max:1000,step:1});
      } else {
        if (!Object.prototype.hasOwnProperty.call(this.properties,'history_path')) this.properties.history_path = initPath;
        if (!Object.prototype.hasOwnProperty.call(this.properties,'max_entries'))  this.properties.max_entries  = initMax;
      }

      hideWidget(wPath); hideWidget(wMax);

      if (wPath) setWidgetValue(this, wPath, this.properties.history_path);
      if (wMax)  setWidgetValue(this, wMax,  this.properties.max_entries);

      fetch('/pg/history/prefs', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) })
        .then(r=>r.json())
        .then(j=>{
          if (!j) return;
          const p = j.history_path || this.properties.history_path || DEF_PATH;
          const m = (j.max_entries ?? this.properties.max_entries ?? DEF_MAX);
          this.properties.history_path = p;
          this.properties.max_entries  = parseInt(m)||DEF_MAX;
          if (wPath) setWidgetValue(this, wPath, p);
          if (wMax)  setWidgetValue(this, wMax, this.properties.max_entries);
          try{ localStorage.setItem('pg_history_path', String(p)); }catch(_){ }
          try{ localStorage.setItem('pg_history_max',  String(this.properties.max_entries)); }catch(_){ }
        }).catch(()=>{});

      const self = this;
      const origOnProp = this.onPropertyChanged;
      this.onPropertyChanged = function(name, value){
        try {
          if (name === 'history_path' || name === 'max_entries') {
            const payload = { history_path: self.properties.history_path, max_entries: self.properties.max_entries };
            try{ localStorage.setItem('pg_history_path', String(payload.history_path||'')); }catch(_){ }
            try{ localStorage.setItem('pg_history_max',  String(payload.max_entries||DEF_MAX)); }catch(_){ }
            fetch('/pg/history/prefs', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }).catch(()=>{});
          }
        } catch(_){ }
        return (typeof origOnProp === 'function') ? origOnProp.apply(this, arguments) : undefined;
      };

      function wrapWidgetCb(w, prop){
        if (!w || w.__pg_wrapped__) return; w.__pg_wrapped__ = true;
        const orig = w.callback;
        w.callback = function(val){
          try {
            const v = (prop==='max_entries') ? (parseInt(val)||DEF_MAX) : String(val||'');
            self.properties[prop] = v;
            if (prop==='history_path') localStorage.setItem('pg_history_path', String(v));
            if (prop==='max_entries')  localStorage.setItem('pg_history_max',  String(v));
          } catch(_){ }
          try { app?.graph?.setDirtyCanvas?.(true,true); } catch(_){ }
          return (typeof orig === 'function') ? orig.apply(this, arguments) : undefined;
        };
      }
      wrapWidgetCb(wPath, 'history_path');
      wrapWidgetCb(wMax,  'max_entries');

      this.__PG_PROPS_WIRED__ = true;
      return r;
    };
    proto.__pg_prefs_attached__ = true;
  }

  app.registerExtension({
    name: EXT,
    async beforeRegisterNodeDef(nodeType, nodeData){
      const isMaybeOurs = (
        isPgLazyPromptClass(nodeType) || isPgLazyPromptClass(nodeData)
      );
      if (isMaybeOurs) __attachPrefsOnce(nodeType);
    },
  });
})();
