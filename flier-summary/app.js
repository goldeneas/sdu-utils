// flier-summary: shows this week's supermarket offers in Odense and lets you star the ones you like.
// Data: data/offers.json (built daily by the GitHub Action). Stars: localStorage on this device only.
(() => {
  'use strict';

  const STAR_KEY = 'flier-summary:stars';
  const PREF_KEY = 'flier-summary:prefs';
  const $ = (sel) => document.querySelector(sel);

  const state = {
    data: null,
    stars: load(STAR_KEY, []),
    prefs: Object.assign({ tab: 'offers', when: 'today', stores: [], sort: 'store', query: '' }, load(PREF_KEY, {})),
  };

  function load(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: keep in memory */ }
  }
  const saveStars = () => save(STAR_KEY, state.stars);
  const savePrefs = () => save(PREF_KEY, state.prefs);

  // ---------------------------------------------------------------- matching
  // A star remembers the product name, not the offer id, so it matches again in next week's fliers
  // (and at the other stores). Matching is on normalized words: every word of the star must appear.
  const norm = (s) => (s || '').toLowerCase()
    .normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9æøå]+/g, ' ').trim();
  const words = (s) => norm(s).split(' ').filter(Boolean);

  function matches(star, offer) {
    const hay = ' ' + norm(offer.heading) + ' ';
    return words(star.key).every((w) => hay.includes(' ' + w + ' ') || (w.length >= 4 && hay.includes(' ' + w)));
  }
  const starFor = (offer) => state.stars.find((s) => norm(s.key) === norm(offer.heading));

  // ---------------------------------------------------------------- dates & money
  const now = () => new Date();
  const isCurrent = (o, t = now()) => (!o.from || new Date(o.from) <= t) && (!o.till || new Date(o.till) >= t);
  const isUpcoming = (o, t = now()) => o.from && new Date(o.from) > t;
  const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  const fmtDay = (iso) => (iso ? dayFmt.format(new Date(iso)) : '');
  const kr = (n) => (n == null ? '' : (Number.isInteger(n) ? String(n) : n.toFixed(2).replace('.', ',')) + ' kr');
  const discount = (o) => (o.prePrice && o.price ? Math.round((1 - o.price / o.prePrice) * 100) : 0);

  function ago(iso) {
    const mins = Math.round((Date.now() - new Date(iso)) / 60000);
    if (mins < 60) return `${Math.max(mins, 1)} min ago`;
    const h = Math.round(mins / 60);
    if (h < 36) return `${h} h ago`;
    return `${Math.round(h / 24)} days ago`;
  }

  // ---------------------------------------------------------------- data
  async function loadData() {
    try {
      const res = await fetch('data/offers.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(res.status);
      state.data = await res.json();
      refreshStarsFromData();
    } catch (err) {
      state.data = null;
      $('#status').textContent = 'Could not load offers. Open the app online once, or check that data/offers.json exists.';
    }
    render();
  }

  // Keep "last seen" info on each star up to date, so a star that is not on sale still shows its last price.
  function refreshStarsFromData() {
    let changed = false;
    for (const star of state.stars) {
      const hits = state.data.offers.filter((o) => isCurrent(o) && matches(star, o));
      if (!hits.length) continue;
      const best = hits.reduce((a, b) => ((b.price ?? 1e9) < (a.price ?? 1e9) ? b : a));
      const seen = { store: best.store, price: best.price, till: best.till, image: best.image, heading: best.heading };
      if (JSON.stringify(star.lastSeen) !== JSON.stringify(seen)) { star.lastSeen = seen; changed = true; }
    }
    if (changed) saveStars();
  }

  const storeInfo = (key) => (state.data?.stores || []).find((s) => s.key === key) || { key, name: key, color: '#666' };

  // ---------------------------------------------------------------- stars
  function toggleStar(offer) {
    const existing = starFor(offer);
    if (existing) {
      state.stars = state.stars.filter((s) => s !== existing);
    } else {
      state.stars.unshift({
        key: offer.heading, addedAt: new Date().toISOString(),
        lastSeen: { store: offer.store, price: offer.price, till: offer.till, image: offer.image, heading: offer.heading },
      });
    }
    saveStars();
    render();
  }

  function addWatchWord(text) {
    const key = text.trim();
    if (!key || state.stars.some((s) => norm(s.key) === norm(key))) return;
    state.stars.unshift({ key, addedAt: new Date().toISOString(), watch: true, lastSeen: null });
    saveStars();
    if (state.data) refreshStarsFromData();
    render();
  }

  // ---------------------------------------------------------------- rendering helpers
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (k === 'style') node.style.cssText = v;
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat()) if (c != null && c !== false) node.append(c.nodeType ? c : String(c));
    return node;
  }

  const STAR_SVG = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 2.8l2.83 5.74 6.33.92-4.58 4.47 1.08 6.3L12 17.25l-5.66 2.98 1.08-6.3L2.84 9.46l6.33-.92z"/></svg>';

  function starButton(offer) {
    const on = !!starFor(offer);
    const b = el('button', {
      class: 'star' + (on ? ' on' : ''), type: 'button', 'aria-pressed': String(on),
      'aria-label': on ? `Unstar ${offer.heading}` : `Star ${offer.heading}`,
      onclick: (e) => { e.stopPropagation(); toggleStar(offer); },
    });
    b.innerHTML = STAR_SVG;
    return b;
  }

  function storeBadge(key) {
    const s = storeInfo(key);
    return el('span', { class: 'badge', style: `--c:${s.color || '#666'}` }, s.name);
  }

  function thumb(src, alt) {
    const box = el('div', { class: 'thumb' });
    if (src) {
      const img = el('img', { src, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
      img.addEventListener('error', () => img.remove());
      box.append(img);
    }
    box.title = alt;
    return box;
  }

  function offerCard(o) {
    const d = discount(o);
    const meta = [o.quantity, o.unitPrice].filter(Boolean).join(' · ');
    const card = el('article', { class: 'offer', tabindex: '0', onclick: () => card.classList.toggle('open') },
      thumb(o.image, o.heading),
      el('div', { class: 'body' },
        el('div', { class: 'top' }, storeBadge(o.store), d >= 5 ? el('span', { class: 'save' }, `−${d}%`) : null),
        el('h3', {}, o.heading),
        meta ? el('p', { class: 'meta' }, meta) : null,
        o.description ? el('p', { class: 'desc' }, o.description) : null,
        el('p', { class: 'valid' }, isUpcoming(o) ? `From ${fmtDay(o.from)} to ${fmtDay(o.till)}` : `Until ${fmtDay(o.till)}`),
      ),
      el('div', { class: 'side' },
        starButton(o),
        el('div', { class: 'price' }, kr(o.price)),
        o.prePrice ? el('div', { class: 'pre' }, kr(o.prePrice)) : null,
      ),
    );
    return card;
  }

  // ---------------------------------------------------------------- views
  function visibleOffers() {
    const { when, stores, query, sort } = state.prefs;
    const t = now();
    const q = words(query);
    let list = state.data.offers.filter((o) => (when === 'today' ? isCurrent(o, t) : isUpcoming(o, t)));
    if (stores.length) list = list.filter((o) => stores.includes(o.store));
    if (q.length) list = list.filter((o) => { const h = norm(o.heading + ' ' + o.description); return q.every((w) => h.includes(w)); });
    const order = (state.data.stores || []).map((s) => s.key);
    const cmp = {
      store: (a, b) => order.indexOf(a.store) - order.indexOf(b.store) || (a.page ?? 0) - (b.page ?? 0),
      price: (a, b) => (a.price ?? 1e9) - (b.price ?? 1e9),
      discount: (a, b) => discount(b) - discount(a),
      name: (a, b) => a.heading.localeCompare(b.heading, 'da'),
    }[sort] || (() => 0);
    return list.sort(cmp);
  }

  function renderFilters() {
    const box = $('#stores');
    box.replaceChildren();
    const t = now();
    const pool = state.data.offers.filter((o) => (state.prefs.when === 'today' ? isCurrent(o, t) : isUpcoming(o, t)));
    for (const s of state.data.stores) {
      const on = state.prefs.stores.includes(s.key);
      const n = pool.filter((o) => o.store === s.key).length;
      box.append(el('button', {
        class: 'chip' + (on ? ' on' : ''), type: 'button', 'aria-pressed': String(on), style: `--c:${s.color || '#666'}`,
        onclick: () => {
          state.prefs.stores = on ? state.prefs.stores.filter((k) => k !== s.key) : [...state.prefs.stores, s.key];
          savePrefs(); render();
        },
      }, s.name, el('span', { class: 'n' }, n)));
    }
    for (const b of document.querySelectorAll('[data-when]')) b.setAttribute('aria-pressed', String(b.dataset.when === state.prefs.when));
    $('#sort').value = state.prefs.sort;
    if (document.activeElement !== $('#q')) $('#q').value = state.prefs.query;
  }

  let renderLimit = 60;
  function renderOffers() {
    const list = visibleOffers();
    const box = $('#list');
    box.replaceChildren();
    if (!list.length) {
      box.append(el('p', { class: 'empty' }, state.prefs.when === 'today'
        ? 'No offers match. Try another store or search.' : 'No upcoming fliers have been published yet.'));
    }
    list.slice(0, renderLimit).forEach((o) => box.append(offerCard(o)));
    if (list.length > renderLimit) {
      box.append(el('button', { class: 'more', type: 'button', onclick: () => { renderLimit += 120; renderOffers(); } },
        `Show more (${list.length - renderLimit} left)`));
    }
    $('#count').textContent = `${list.length} offer${list.length === 1 ? '' : 's'}`;
  }

  function starsOnSale() {
    if (!state.data) return [];
    const t = now();
    return state.stars.map((star) => ({
      star,
      hits: state.data.offers.filter((o) => isCurrent(o, t) && matches(star, o)).sort((a, b) => (a.price ?? 1e9) - (b.price ?? 1e9)),
    }));
  }

  function renderStars() {
    const box = $('#starred');
    box.replaceChildren();
    if (!state.stars.length) {
      box.append(el('p', { class: 'empty' }, 'Nothing starred yet. Tap ☆ on an offer, or add a word to watch above. ' +
        'Starred items stay here, and light up when any of the stores has them on sale again.'));
      return;
    }
    const rows = starsOnSale();
    const onSale = rows.filter((r) => r.hits.length);
    const offSale = rows.filter((r) => !r.hits.length);

    if (onSale.length) {
      box.append(el('h2', { class: 'section' }, `On sale now · ${onSale.length}`));
      for (const { star, hits } of onSale) {
        box.append(el('div', { class: 'group' },
          el('div', { class: 'group-head' }, el('strong', {}, star.key), star.watch ? el('span', { class: 'tag' }, 'watch word') : null,
            unstarButton(star)),
          hits.slice(0, 6).map(offerCard),
          hits.length > 6 ? el('p', { class: 'meta pad' }, `+ ${hits.length - 6} more matches`) : null));
      }
    }
    if (offSale.length) {
      box.append(el('h2', { class: 'section' }, `Not on sale right now · ${offSale.length}`));
      for (const { star } of offSale) {
        const seen = star.lastSeen;
        box.append(el('div', { class: 'offer idle' },
          thumb(seen?.image, star.key),
          el('div', { class: 'body' },
            el('h3', {}, star.key),
            el('p', { class: 'meta' }, seen
              ? [`Last seen at ${storeInfo(seen.store).name}`, seen.price != null ? ` for ${kr(seen.price)}` : '', seen.till ? `, until ${fmtDay(seen.till)}` : '']
              : star.watch ? 'Watching for this word in every flier' : 'Not seen yet')),
          el('div', { class: 'side' }, unstarButton(star))));
      }
    }
  }

  function unstarButton(star) {
    const b = el('button', {
      class: 'star on', type: 'button', 'aria-label': `Remove ${star.key}`,
      onclick: () => { state.stars = state.stars.filter((s) => s !== star); saveStars(); render(); },
    });
    b.innerHTML = STAR_SVG;
    return b;
  }

  function render() {
    const tab = state.prefs.tab;
    $('#view-offers').hidden = tab !== 'offers';
    $('#view-starred').hidden = tab !== 'starred';
    $('#title').textContent = tab === 'offers' ? 'Offers' : 'Starred';
    for (const b of document.querySelectorAll('[data-tab]')) b.setAttribute('aria-current', String(b.dataset.tab === tab));

    const live = starsOnSale().filter((r) => r.hits.length).length;
    $('#star-badge').textContent = live || '';
    $('#star-badge').hidden = !live;

    if (!state.data) return;
    $('#status').textContent = `Updated ${ago(state.data.generatedAt)} · ${state.data.location?.name || ''}`;
    if (tab === 'offers') { renderFilters(); renderOffers(); } else renderStars();
  }

  // ---------------------------------------------------------------- backup (stars live only on this device)
  function exportStars() {
    const blob = new Blob([JSON.stringify(state.stars, null, 2)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: 'flier-stars.json' });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function importStars(file) {
    file.text().then((text) => {
      const incoming = JSON.parse(text);
      if (!Array.isArray(incoming)) throw new Error('not a list');
      for (const s of incoming) {
        if (s && typeof s.key === 'string' && !state.stars.some((x) => norm(x.key) === norm(s.key))) state.stars.push(s);
      }
      saveStars(); if (state.data) refreshStarsFromData(); render();
    }).catch(() => alert('That file is not a flier-summary star backup.'));
  }

  // ---------------------------------------------------------------- wiring
  function setTab(tab) { state.prefs.tab = tab; savePrefs(); window.scrollTo(0, 0); render(); }

  document.addEventListener('DOMContentLoaded', () => {
    for (const b of document.querySelectorAll('[data-tab]')) b.addEventListener('click', () => setTab(b.dataset.tab));
    for (const b of document.querySelectorAll('[data-when]')) {
      b.addEventListener('click', () => { state.prefs.when = b.dataset.when; savePrefs(); renderLimit = 60; render(); });
    }
    $('#sort').addEventListener('change', (e) => { state.prefs.sort = e.target.value; savePrefs(); render(); });
    let timer;
    $('#q').addEventListener('input', (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.prefs.query = e.target.value; savePrefs(); renderLimit = 60; render(); }, 150);
    });
    $('#watch').addEventListener('submit', (e) => {
      e.preventDefault();
      addWatchWord($('#watch-word').value);
      $('#watch-word').value = '';
    });
    $('#export').addEventListener('click', exportStars);
    $('#import').addEventListener('change', (e) => { if (e.target.files[0]) importStars(e.target.files[0]); e.target.value = ''; });

    if (location.hash === '#starred') state.prefs.tab = 'starred';
    render();
    loadData();
    // Re-check when the app comes back to the foreground (an installed PWA is often left open for days).
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadData(); });
  });
})();
