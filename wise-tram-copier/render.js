// Fills the pages with the values from config.js. Elements opt in with data-cfg="path.to.value".
// If a value is missing from the config the built-in HTML text stays; "" / null hides the element
// (or the closest ancestor matching data-cfg-hide).
(function () {
  var cfg = window.APP_CONFIG || {};
  var p = cfg.payment = Object.assign({}, cfg.payment);
  var has = function (v) { return v !== undefined && v !== null && v !== ''; };

  // derived values used by the payment screen
  if (p.amount !== undefined || p.currency !== undefined) {
    p.amountText = [p.amount, p.currency].filter(has).join(' ');
  }
  p.amountTakenText = has(p.amountTaken) ? p.amountTaken : p.amountText;
  p.footerNameText = has(p.footerName) ? p.footerName : p.merchant;

  function get(path) {
    return path.split('.').reduce(function (o, k) { return o == null ? undefined : o[k]; }, cfg);
  }

  document.querySelectorAll('[data-cfg]').forEach(function (el) {
    var v = get(el.getAttribute('data-cfg'));
    if (v === undefined) return;
    if (!has(v)) {
      var sel = el.getAttribute('data-cfg-hide');
      (sel && el.closest(sel) || el).style.display = 'none';
      return;
    }
    el.textContent = String(v);
  });

  // note: plain text instead of the "Add" link once a note is set
  var note = document.getElementById('note');
  if (note && has(p.note)) {
    note.className = 'v';
    note.style.cursor = 'default';
    note.textContent = String(p.note);
  }

  // country flag in "How you paid" (simple flags only)
  var flag = document.getElementById('flag');
  if (flag && p.flag !== undefined) {
    var W = 25, code = String(p.flag || '').toUpperCase();
    var CROSS = { // bg, outer cross, inner cross (optional)
      DK: ['#e2434b', '#fff'], SE: ['#006aa7', '#fecc00'], FI: ['#fff', '#003580'], NO: ['#ba0c2f', '#fff', '#00205b']
    };
    var ROWS = {
      DE: ['#000', '#dd0000', '#ffce00'], NL: ['#ae1c28', '#fff', '#21468b'], PL: ['#fff', '#dc143c'], AT: ['#ed2939', '#fff', '#ed2939']
    };
    var COLS = {
      FR: ['#0055a4', '#fff', '#ef4135'], IT: ['#009246', '#fff', '#ce2b37'], IE: ['#169b62', '#fff', '#ff883e'], BE: ['#000', '#fdda24', '#ef3340']
    };
    var body = '';
    var rect = function (x, y, w, h, fill) {
      return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" fill="' + fill + '"/>';
    };
    if (CROSS[code]) {
      var c = CROSS[code], ow = c[2] ? 5.2 : 3.6, iw = 2.4;
      body = rect(0, 0, W, W, c[0]) + rect(8.8 - ow / 2, 0, ow, W, c[1]) + rect(0, 12.5 - ow / 2, W, ow, c[1]);
      if (c[2]) body += rect(8.8 - iw / 2, 0, iw, W, c[2]) + rect(0, 12.5 - iw / 2, W, iw, c[2]);
    } else if (ROWS[code]) {
      body = ROWS[code].map(function (f, i, a) { return rect(0, i * W / a.length, W, W / a.length + .1, f); }).join('');
    } else if (COLS[code]) {
      body = COLS[code].map(function (f, i, a) { return rect(i * W / a.length, 0, W / a.length + .1, W, f); }).join('');
    }
    if (body) {
      flag.setAttribute('aria-label', code);
      flag.innerHTML = '<defs><clipPath id="flag-clip"><circle cx="12.5" cy="12.5" r="12.5"/></clipPath></defs>' +
        '<g clip-path="url(#flag-clip)">' + body + '</g>';
    } else {
      flag.style.display = 'none';
    }
  }
})();
