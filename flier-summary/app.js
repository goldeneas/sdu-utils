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
    prefs: Object.assign({ tab: 'offers', when: 'today', stores: [], sort: 'store', query: '', cat: 'all', en: false }, load(PREF_KEY, {})),
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
  const isStarredMatch = (offer) => state.stars.some((s) => matches(s, offer));

  // ---------------------------------------------------------------- English names
  // The nightly fetcher adds headingEn (machine translated). The setting only changes what is shown:
  // stars, matching and the flier stay on the Danish name, so switching back and forth loses nothing.
  let englishByHeading = new Map();
  const name = (o) => (state.prefs.en && o.headingEn) || o.heading;
  const starName = (star) => (state.prefs.en && !star.watch && englishByHeading.get(star.key)) || star.key;

  // ---------------------------------------------------------------- categories
  // Each offer has cats like ['dairy', 'protein'] (keyword based, see the scraper). The first
  // entry is its main category; 'protein' is an extra tag. Offers without a main one are 'other'.
  const mainCat = (o) => (o.cats || []).find((c) => c !== 'protein') || 'other';
  const inCat = (o, cat) => cat === 'all' || (cat === 'protein' ? (o.cats || []).includes('protein') : mainCat(o) === cat);

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
      englishByHeading = new Map(state.data.offers.filter((o) => o.headingEn).map((o) => [o.heading, o.headingEn]));
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
      'aria-label': on ? `Unstar ${name(offer)}` : `Star ${name(offer)}`,
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
    const meta = [o.quantity, o.unitPrice].filter(Boolean).join(' · ');
    const card = el('article', { class: 'offer' + (isStarredMatch(o) ? ' hl' : ''), tabindex: '0', onclick: () => openDetail(o), onkeydown: (e) => { if (e.key === 'Enter') openDetail(o); } },
      thumb(o.image, name(o)),
      el('div', { class: 'body' },
        el('div', { class: 'top' }, storeBadge(o.store)),
        el('h3', {}, name(o)),
        meta ? el('p', { class: 'meta' }, meta) : null,
        o.description ? el('p', { class: 'desc' }, o.description) : null,
        el('p', { class: 'valid' }, isUpcoming(o) ? `From ${fmtDay(o.from)} to ${fmtDay(o.till)}` : `Until ${fmtDay(o.till)}`),
      ),
      el('div', { class: 'side' },
        starButton(o),
        el('div', { class: 'price' }, kr(o.price)),  // the old price is shown on the product page only
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
    if (state.prefs.cat !== 'all') list = list.filter((o) => inCat(o, state.prefs.cat));
    if (q.length) list = list.filter((o) => { const h = norm(o.heading + ' ' + (o.headingEn || '') + ' ' + o.description); return q.every((w) => h.includes(w)); });
    const order = (state.data.stores || []).map((s) => s.key);
    const cmp = {
      store: (a, b) => order.indexOf(a.store) - order.indexOf(b.store) || (a.page ?? 0) - (b.page ?? 0),
      price: (a, b) => (a.price ?? 1e9) - (b.price ?? 1e9),
      discount: (a, b) => discount(b) - discount(a),
      name: (a, b) => name(a).localeCompare(name(b), state.prefs.en ? 'en' : 'da'),
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
    renderCats(pool.filter((o) => !state.prefs.stores.length || state.prefs.stores.includes(o.store)));
    for (const b of document.querySelectorAll('[data-when]')) b.setAttribute('aria-pressed', String(b.dataset.when === state.prefs.when));
    for (const b of document.querySelectorAll('[data-sort]')) b.setAttribute('aria-pressed', String(b.dataset.sort === state.prefs.sort));
    const active = activeFilters();
    $('#filter-badge').textContent = active || '';
    $('#filter-badge').hidden = !active;
    $('#open-filters').setAttribute('aria-label', active ? `Filters, ${active} on` : 'Filters');
    const n = visibleOffers().length;
    $('#close-filters').textContent = `Show ${n} offer${n === 1 ? '' : 's'}`;
    if (document.activeElement !== $('#q')) $('#q').value = state.prefs.query;
  }

  // How many filters differ from the defaults (shown as a badge on the filter button).
  const activeFilters = () => [state.prefs.stores.length > 0, state.prefs.cat !== 'all',
    state.prefs.when !== 'today', state.prefs.sort !== 'store'].filter(Boolean).length;

  function resetFilters() {
    Object.assign(state.prefs, { when: 'today', stores: [], cat: 'all', sort: 'store' });
    savePrefs(); renderLimit = 60; render();
  }

  // ---------------------------------------------------------------- filter sheet
  function openFilters() {
    $('#filters').hidden = false; $('#filter-scrim').hidden = false;
    document.documentElement.classList.add('sheet-open');
  }
  function closeFilters() {
    $('#filters').hidden = true; $('#filter-scrim').hidden = true;
    document.documentElement.classList.remove('sheet-open');
  }

  function renderCats(pool) {
    const box = $('#cats');
    box.replaceChildren();
    const names = Object.fromEntries((state.data.categories || []).map((c) => [c.key, c.name]));
    if (!Object.keys(names).length) { $('#cats-box').hidden = true; return; }
    $('#cats-box').hidden = false;
    // Food first; household, non-food and other last. Unknown keys from a newer scraper go before them.
    const known = ['protein', 'meat', 'dairy', 'produce', 'bakery', 'drinks', 'snacks', 'pantry', 'household', 'nonfood'];
    const extra = Object.keys(names).filter((k) => !known.includes(k));
    const keys = ['all', ...known.slice(0, 8), ...extra, 'household', 'nonfood', 'other'];
    names.all = 'All'; names.other = 'Other';
    for (const key of keys) {
      const n = key === 'all' ? pool.length : pool.filter((o) => inCat(o, key)).length;
      const on = state.prefs.cat === key;
      if (!n && !on) continue;
      box.append(el('button', {
        class: 'cat' + (on ? ' on' : ''), type: 'button', 'aria-pressed': String(on),
        onclick: () => { state.prefs.cat = on && key !== 'all' ? 'all' : key; savePrefs(); renderLimit = 60; render(); },
      }, names[key] || key, key === 'all' ? null : el('span', { class: 'n' }, n)));
    }
  }

  // Offers matching the stars, shown in a row above the list. Product stars come before watch
  // words, in the order they were starred, cheapest first within each star.
  function featuredOffers() {
    const { when, stores } = state.prefs;
    const t = now();
    const pool = state.data.offers.filter((o) => (when === 'today' ? isCurrent(o, t) : isUpcoming(o, t))
      && (!stores.length || stores.includes(o.store)) && inCat(o, state.prefs.cat));
    const order = [...state.stars.filter((s) => !s.watch), ...state.stars.filter((s) => s.watch)];
    const seen = new Set();
    const out = [];
    for (const star of order) {
      for (const o of pool.filter((x) => matches(star, x)).sort((a, b) => (a.price ?? 1e9) - (b.price ?? 1e9))) {
        if (!seen.has(o.id)) { seen.add(o.id); out.push(o); }
      }
    }
    return out;
  }

  function featuredCard(o) {
    return el('article', { class: 'fcard', tabindex: '0', onclick: () => openDetail(o), onkeydown: (e) => { if (e.key === 'Enter') openDetail(o); } },
      thumb(o.image, name(o)),
      el('div', { class: 'top' }, storeBadge(o.store)),
      el('h3', {}, name(o)),
      o.quantity ? el('p', { class: 'meta' }, o.quantity) : null,
      el('div', { class: 'fprice' },
        el('span', { class: 'price' }, kr(o.price)),
        starButton(o)),
    );
  }

  function renderFeatured() {
    const box = $('#featured');
    const list = state.prefs.query ? [] : featuredOffers();
    box.hidden = !list.length;
    if (!list.length) return;
    box.replaceChildren(
      el('div', { class: 'feat-head' },
        el('h2', {}, 'Featured for you'),
        el('span', {}, `${list.length} ${state.prefs.when === 'today' ? 'on sale' : 'coming up'}`)),
      el('div', { class: 'rail' }, list.slice(0, 24).map(featuredCard)));
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
          el('div', { class: 'group-head' }, el('strong', {}, starName(star)), star.watch ? el('span', { class: 'tag' }, 'watch word') : null,
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
          thumb(seen?.image, starName(star)),
          el('div', { class: 'body' },
            el('h3', {}, starName(star)),
            el('p', { class: 'meta' }, seen
              ? [`Last seen at ${storeInfo(seen.store).name}`, seen.price != null ? ` for ${kr(seen.price)}` : '', seen.till ? `, until ${fmtDay(seen.till)}` : '']
              : star.watch ? 'Watching for this word in every flier' : 'Not seen yet')),
          el('div', { class: 'side' }, unstarButton(star))));
      }
    }
  }

  function unstarButton(star) {
    const b = el('button', {
      class: 'star on', type: 'button', 'aria-label': `Remove ${starName(star)}`,
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
    for (const b of document.querySelectorAll('[data-lang]')) b.setAttribute('aria-pressed', String((b.dataset.lang === 'en') === !!state.prefs.en));

    const live = starsOnSale().filter((r) => r.hits.length).length;
    $('#star-badge').textContent = live || '';
    $('#star-badge').hidden = !live;

    if (!state.data) return;
    $('#status').textContent = [ago(state.data.generatedAt), (state.data.location?.name || '').toUpperCase()].filter(Boolean).join(' - ');
    if (tab === 'offers') { renderFilters(); renderFeatured(); renderOffers(); } else renderStars();
    renderDetail();
  }

  // ---------------------------------------------------------------- detail page
  // Tapping an offer opens #offer/<id> as a full-screen page over the list, so the phone's back
  // gesture closes it and the list keeps its scroll position.
  const detailId = () => (location.hash.startsWith('#offer/') ? decodeURIComponent(location.hash.slice(7)) : null);
  let openedFromList = false;

  function openDetail(o) {
    openedFromList = true;
    location.hash = 'offer/' + encodeURIComponent(o.id);
  }
  function closeDetail() {
    if (openedFromList) { openedFromList = false; history.back(); } else { history.replaceState(null, '', location.pathname + location.search); renderDetail(); }
  }

  const daysLeft = (iso) => Math.ceil((new Date(iso) - now()) / 86400000);

  function renderDetail() {
    const box = $('#view-detail');
    const id = detailId();
    document.documentElement.classList.toggle('detail-open', !!id);
    box.hidden = !id;
    if (!id) { box.replaceChildren(); return; }
    if (!state.data) { box.replaceChildren(el('p', { class: 'empty' }, 'Loading…')); return; }
    const o = state.data.offers.find((x) => x.id === id);
    const back = el('button', { class: 'back', type: 'button', 'aria-label': 'Back', onclick: closeDetail });
    back.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';
    if (!o) {
      box.replaceChildren(el('div', { class: 'detail-bar' }, back),
        el('p', { class: 'empty' }, 'This offer is no longer in the fliers.'));
      return;
    }
    const d = discount(o);
    const s = storeInfo(o.store);
    const img = el('img', { src: o.imageLarge || o.image, alt: name(o), decoding: 'async', referrerpolicy: 'no-referrer' });
    img.addEventListener('error', () => { if (o.image && img.src !== o.image) img.src = o.image; });
    const pic = el('div', { class: 'detail-pic', role: 'button', tabindex: '0', 'aria-label': 'Zoom picture',
      onclick: () => pic.classList.toggle('zoomed') }, img);
    const t = now();
    const upcoming = isUpcoming(o, t);
    const left = o.till ? daysLeft(o.till) : null;
    const when = upcoming ? `Starts ${fmtDay(o.from)}, until ${fmtDay(o.till)}`
      : [o.from ? `${fmtDay(o.from)} – ${fmtDay(o.till)}` : `Until ${fmtDay(o.till)}`,
        left != null ? (left <= 1 ? 'last day today' : `${left} days left`) : ''].filter(Boolean).join(' · ');
    const others = state.data.offers
      .filter((x) => x.id !== o.id && (isCurrent(x, t) || isUpcoming(x, t)) && matches({ key: o.heading }, x))
      .sort((a, b) => (a.price ?? 1e9) - (b.price ?? 1e9)).slice(0, 6);
    const rows = [
      o.quantity ? ['Amount', o.quantity] : null,
      o.unitPrice ? ['Unit price', o.unitPrice] : null,
      ['Valid', when],
      o.page ? ['In the flier', `${s.name}, page ${o.page}`] : null,
    ].filter(Boolean);
    box.replaceChildren(
      el('div', { class: 'detail-bar' }, back, el('span', { class: 'badge', style: `--c:${s.color || '#666'}` }, s.name), starButton(o)),
      pic,
      el('p', { class: 'zoom-hint' }, 'Tap the picture to zoom'),
      el('div', { class: 'detail-body' },
        el('h2', {}, name(o)),
        state.prefs.en && o.headingEn ? el('p', { class: 'orig', lang: 'da' }, o.heading) : null,
        el('div', { class: 'detail-price' },
          el('span', { class: 'price' }, kr(o.price)),
          o.prePrice ? el('span', { class: 'pre' }, kr(o.prePrice)) : null,
          d >= 1 ? el('span', { class: 'save' }, `Save ${kr(Math.round((o.prePrice - o.price) * 100) / 100)}`) : null),
        o.description ? el('p', { class: 'detail-desc' }, o.description) : null,
        el('dl', { class: 'facts' }, rows.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])),
        others.length ? el('h3', { class: 'section' }, 'Similar offers') : null,
        others.length ? el('div', { class: 'list' }, others.map(offerCard)) : null,
      ),
    );
    box.scrollTop = 0;
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
    for (const b of document.querySelectorAll('[data-lang]')) {
      b.addEventListener('click', () => { state.prefs.en = b.dataset.lang === 'en'; savePrefs(); render(); });
    }
    for (const b of document.querySelectorAll('[data-sort]')) {
      b.addEventListener('click', () => { state.prefs.sort = b.dataset.sort; savePrefs(); render(); });
    }
    $('#open-filters').addEventListener('click', openFilters);
    $('#close-filters').addEventListener('click', () => { closeFilters(); window.scrollTo(0, 0); });
    $('#filter-scrim').addEventListener('click', closeFilters);
    $('#reset-filters').addEventListener('click', resetFilters);
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
    window.addEventListener('hashchange', () => { if (!detailId()) openedFromList = false; renderDetail(); });
    document.addEventListener('keydown', (e) => { if (e.key !== 'Escape') return; if (!$('#filters').hidden) closeFilters(); else if (detailId()) closeDetail(); });
    render();
    loadData();
    // Re-check when the app comes back to the foreground (an installed PWA is often left open for days).
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadData(); });
  });
})();
