(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const zone = 'Europe/Copenhagen';
  const calendar = new Intl.DateTimeFormat('en-CA', {timeZone:zone, year:'numeric',month:'2-digit',day:'2-digit'});
  const today = () => calendar.format(new Date());
  const dateOf = (s) => new Date(s + 'T12:00:00+01:00');
  const dateLabel = (s, options) => new Intl.DateTimeFormat('en-GB', {timeZone:zone, ...options}).format(dateOf(s));
  const monday = () => {
    const t = dateOf(today());
    t.setUTCDate(t.getUTCDate() - (t.getUTCDay() + 6) % 7);
    return calendar.format(t);
  };
  let data = null;
  let loading = false;
  let failed = false;
  function node(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function render() {
    if (!data) {
      $('#notice').hidden = !failed;
      $('#notice').textContent = 'The menu could not be downloaded. Try again when online, or open the original menu below.';
      $('#menu').replaceChildren(node('p','empty',failed ? 'Menu unavailable.' : 'Loading this week’s menu…'));
      return;
    }
    const current = data.weekStart === monday();
    const generated = new Date(data.generatedAt);
    $('#updated').textContent = Number.isFinite(generated.getTime())
      ? (calendar.format(generated) === today() ? 'Updated today' : 'Updated ' + new Intl.DateTimeFormat('en-GB',{timeZone:zone,dateStyle:'medium'}).format(generated)) : '';
    const warnings = [!current ? 'This week’s menu is not available yet. Showing the last published week.' : '',
      !navigator.onLine ? 'Offline · saved menu.' : failed ? 'Could not refresh. Showing the last downloaded menu.' : data.fetchFailed ? 'Source update failed. Showing the last available menu.' : ''];
    $('#notice').textContent = warnings.filter(Boolean).join(' ');
    $('#notice').hidden = !$('#notice').textContent;
    $('#week').textContent = current ? 'This week' : 'Saved menu';
    const end = data.days.at(-1)?.date || data.weekStart;
    $('#range').textContent = dateLabel(data.weekStart,{day:'numeric',month:'short'}) + ' – ' + dateLabel(end,{day:'numeric',month:'short',year:'numeric'});
    const links = [], cards = [];
    for (const d of data.days) {
      const isToday = d.date === today();
      const link = node('a','',dateLabel(d.date,{weekday:'short'}));
      link.href = '#day-' + d.date;
      if (isToday) link.setAttribute('aria-current','date');
      link.append(node('strong','',dateLabel(d.date,{day:'numeric'})));
      links.push(link);
      const card = node('article','day' + (isToday ? ' today' : ''));
      card.id = 'day-' + d.date;
      const heading = node('div','day-heading');
      heading.append(node('h3','',dateLabel(d.date,{weekday:'long'})),node(isToday ? 'span' : 'p',isToday ? 'badge' : 'muted',isToday ? 'Today' : dateLabel(d.date,{day:'numeric',month:'short'})));
      card.append(heading);
      if (d.hours) card.append(node('p','hours','Open ' + d.hours));
      for (const section of d.sections) {
        const box = node('section','section');
        if (section.title) box.append(node('h4','',section.title));
        box.append(node('p','',section.text));
        card.append(box);
      }
      if (!d.sections.length) card.append(node('p','muted',d.note || 'No menu published for this day.'));
      cards.push(card);
    }
    $('#days').replaceChildren(...links);
    $('#menu').replaceChildren(...cards);
  }
  async function refresh() {
    if (loading) return;
    loading = true; $('#refresh').disabled = true;
    try {
      const res = await fetch('data/menu.json', {cache:'no-cache'});
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const next = await res.json();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(next.weekStart) || !Array.isArray(next.days) || !next.days.length ||
        !next.days.every(d => /^\d{4}-\d{2}-\d{2}$/.test(d.date) && Array.isArray(d.sections) && d.sections.every(s => typeof s.text === 'string'))) throw new Error('Invalid menu');
      data = next; failed = false;
    } catch { failed = true; }
    finally { loading = false; $('#refresh').disabled = false; render(); }
  }
  $('#refresh').addEventListener('click',refresh);
  document.addEventListener('visibilitychange',()=> { if (!document.hidden) refresh(); });
  window.addEventListener('online',refresh);
  window.addEventListener('offline',render);
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(()=>{});
  refresh();
})();
