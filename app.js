(() => {
'use strict';

/* ---------- утилиты ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const uid = () => Math.random().toString(36).slice(2, 9) + Date.now().toString(36);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ICONS = {
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  book: '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z"/><path d="M4 21V5"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  data: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  aa: '<path d="M3 19l5-14 5 14M5 14h6M15 19l3.5-9 3.5 9M16.2 16h4.6"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 012-2h9"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  star: '<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.3l1-6.2L3 9.7l6.2-.9z"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
};
const ico = n => `<svg viewBox="0 0 24 24">${ICONS[n] || ''}</svg>`;
const hydrateIcons = (root = document) => $$('[data-ico]', root).forEach(e => { if (!e.firstChild) e.innerHTML = ico(e.dataset.ico); });

const STATUS = { plan: 'В планах', reading: 'Читаю', done: 'Прочитано' };
const domain = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };
const normUrl = u => { u = u.trim(); return /^[a-z][a-z0-9+.-]*:/i.test(u) ? u : 'https://' + u; };
const parseTags = s => [...new Set(String(s || '').split(/[,#\n]/).map(t => t.trim().toLowerCase()).filter(Boolean))];
const paras = text => {
  const t = String(text || '').replace(/\r\n?/g, '\n').trim();
  if (!t) return [];
  let p = t.split(/\n\s*\n/);
  if (p.length < 3 && t.includes('\n')) p = t.split('\n');
  return p.map(x => x.trim()).filter(Boolean);
};

/* ---------- хранилище (IndexedDB + запасной localStorage) ---------- */
const KEY = 'state';
const idb = () => new Promise((res, rej) => {
  const r = indexedDB.open('couswork', 1);
  r.onupgradeneeded = () => r.result.createObjectStore('kv');
  r.onsuccess = () => res(r.result);
  r.onerror = () => rej(r.error);
});
const store = {
  async load() {
    try {
      const db = await idb();
      return await new Promise((res, rej) => { const q = db.transaction('kv').objectStore('kv').get(KEY); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    } catch { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } }
  },
  async save(v) {
    try {
      const db = await idb();
      await new Promise((res, rej) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(v, KEY); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
    } catch { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { toast('Не удалось сохранить — не хватает места'); } }
  },
};

let S = { books: [], links: [], marks: [], set: { size: 19, lh: 1.75, width: 720, font: 'sans', tone: 'soft' } };
let saveT;
const save = () => { clearTimeout(saveT); saveT = setTimeout(() => store.save(S), 250); };
const ui = { tab: 'books', bf: 'all', lf: 'all', tag: '', q: '' };

/* ---------- уведомления, диалоги ---------- */
let toastT;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 1800);
}
const dlg = $('#dlg');
function openDlg(html) {
  return new Promise(resolve => {
    dlg.innerHTML = `<form method="dialog" class="dlg">${html}</form>`;
    dlg.onclose = () => resolve(dlg.returnValue === 'ok' ? new FormData($('form', dlg)) : null);
    dlg.returnValue = '';
    $('form', dlg).addEventListener('submit', e => { if (e.submitter?.value === 'ok') dlg.returnValue = 'ok'; });
    $$('[data-close]', dlg).forEach(b => b.onclick = () => dlg.close());
    dlg.showModal();
  });
}
const confirmDlg = async (msg) => !!(await openDlg(`<h3>${esc(msg)}</h3><div class="btns"><button class="btn" value="cancel">Отмена</button><button class="btn danger" value="ok">Удалить</button></div>`));
const askText = async (title, val = '') => {
  const f = await openDlg(`<h3>${esc(title)}</h3><textarea name="v" autofocus>${esc(val)}</textarea><div class="btns"><button class="btn" value="cancel">Отмена</button><button class="btn primary" value="ok">Сохранить</button></div>`);
  return f ? f.get('v').trim() : null;
};
async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch { const a = document.createElement('textarea'); a.value = text; a.style.cssText = 'position:fixed;opacity:0'; document.body.append(a); a.select(); document.execCommand('copy'); a.remove(); }
  toast('Скопировано');
}

/* ---------- отрисовка главных экранов ---------- */
function render() {
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === ui.tab));
  const done = S.books.filter(b => b.status === 'done').length;
  $('#stat').textContent = `${done}/${S.books.length} книг · ${S.links.filter(l => !l.read).length} ссылок`;
  $('#q').placeholder = { books: 'Поиск по книгам', links: 'Поиск по ссылкам', marks: 'Поиск по закладкам' }[ui.tab];
  $('#view').innerHTML = { books: viewBooks, links: viewLinks, marks: viewMarks }[ui.tab]();
  hydrateIcons($('#view'));
}

const empty = (icon, title, text) => `<div class="empty">${ico(icon)}<b>${title}</b><span>${text}</span></div>`;
const chips = (items, cur, key) => `<div class="chips">${items.map(([v, l]) => `<button class="chip ${cur === v ? 'on' : ''}" data-chip="${key}" data-v="${v}">${l}</button>`).join('')}</div>`;
const match = (q, ...f) => !q || f.join(' ').toLowerCase().includes(q.toLowerCase());

function viewBooks() {
  const cnt = s => s === 'all' ? S.books.length : S.books.filter(b => b.status === s).length;
  let list = S.books.filter(b => (ui.bf === 'all' || b.status === ui.bf) && match(ui.q, b.title, b.author, b.notes));
  const head = `<p class="eyebrow">Моя полка</p><h1>Книги</h1>` + chips([['all', `Все · ${cnt('all')}`], ['plan', `В планах · ${cnt('plan')}`], ['reading', `Читаю · ${cnt('reading')}`], ['done', `Прочитано · ${cnt('done')}`]], ui.bf, 'bf');
  if (!list.length) return head + empty('book', S.books.length ? 'Ничего не найдено' : 'Пока пусто', S.books.length ? 'Измените поиск или фильтр.' : 'Нажмите «+», чтобы добавить книгу — можно вставить текст или загрузить .txt.');
  return head + `<div class="list">${list.map(b => {
    const pr = Math.round((b.progress || 0) * 100);
    const has = !!b.text;
    return `<article class="card glass clickable ${b.status === 'done' ? 'done' : ''}" data-open="${b.id}">
      <div class="row"><div class="grow"><div class="ttl">${esc(b.title)}</div><div class="meta">${esc(b.author || 'Автор не указан')}${has ? '' : ' · без текста'}</div></div>
        <span class="badge ${b.status}">${STATUS[b.status]}</span></div>
      ${has && b.status !== 'plan' ? `<div class="bar"><i style="width:${b.status === 'done' ? 100 : pr}%"></i></div>` : ''}
      ${b.notes ? `<div class="note">${esc(b.notes)}</div>` : ''}
      <div class="acts" data-stop>
        <button class="sm ${b.status === 'done' ? 'on' : ''}" data-act="toggle-book" data-id="${b.id}">${ico('check')}${b.status === 'done' ? 'Прочитано' : 'Отметить прочитанной'}</button>
        <button class="sm" data-act="status" data-id="${b.id}">Статус: ${STATUS[b.status]}</button>
        <button class="sm" data-act="edit-book" data-id="${b.id}" aria-label="Изменить">${ico('edit')}</button>
        <button class="sm danger" data-act="del-book" data-id="${b.id}" aria-label="Удалить">${ico('trash')}</button>
      </div></article>`;
  }).join('')}</div>`;
}

function viewLinks() {
  const tags = [...new Set(S.links.flatMap(l => l.tags || []))].sort();
  const cnt = f => S.links.filter(l => f === 'all' || (f === 'unread' ? !l.read : f === 'read' ? l.read : l.fav)).length;
  let list = S.links.filter(l => (ui.lf === 'all' || (ui.lf === 'unread' ? !l.read : ui.lf === 'read' ? l.read : l.fav)) && (!ui.tag || (l.tags || []).includes(ui.tag)) && match(ui.q, l.title, l.url, l.note, (l.tags || []).join(' ')));
  const head = `<p class="eyebrow">Сохранённое</p><h1>Ссылки</h1>` + chips([['all', `Все · ${cnt('all')}`], ['unread', `Не прочитано · ${cnt('unread')}`], ['read', `Прочитано · ${cnt('read')}`], ['fav', `★ · ${cnt('fav')}`]], ui.lf, 'lf')
    + (tags.length ? chips([['', 'Все теги'], ...tags.map(t => [t, '#' + esc(t)])], ui.tag, 'tag') : '');
  if (!list.length) return head + empty('link', S.links.length ? 'Ничего не найдено' : 'Пока пусто', S.links.length ? 'Измените поиск или фильтр.' : 'Нажмите «+» и вставьте одну или сразу несколько ссылок.');
  return head + `<div class="list">${list.map(l => `
    <article class="card glass ${l.read ? 'done' : ''}">
      <div class="row"><div class="grow"><div class="ttl">${esc(l.title || domain(l.url))}</div><a class="url" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.url)}</a></div>
      ${l.read ? '<span class="badge done">Прочитано</span>' : ''}</div>
      ${l.note ? `<div class="note">${esc(l.note)}</div>` : ''}
      ${(l.tags || []).length ? `<div class="tags">${l.tags.map(t => `<span class="tag" data-chip="tag" data-v="${esc(t)}">#${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="acts">
        <a class="sm" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${ico('ext')}Открыть</a>
        <button class="sm" data-act="copy-link" data-id="${l.id}">${ico('copy')}Копировать</button>
        <button class="sm ${l.read ? 'on' : ''}" data-act="toggle-link" data-id="${l.id}">${ico('check')}${l.read ? 'Прочитано' : 'Прочитал'}</button>
        <button class="sm star ${l.fav ? 'on' : ''}" data-act="fav-link" data-id="${l.id}" aria-label="В избранное">${ico('star')}</button>
        <button class="sm" data-act="edit-link" data-id="${l.id}" aria-label="Изменить">${ico('edit')}</button>
        <button class="sm danger" data-act="del-link" data-id="${l.id}" aria-label="Удалить">${ico('trash')}</button>
      </div></article>`).join('')}</div>`;
}

function viewMarks() {
  const head = `<p class="eyebrow">Всё важное</p><h1>Закладки</h1>`;
  const marks = S.marks.filter(m => { const b = S.books.find(x => x.id === m.bookId); return b && match(ui.q, b.title, m.quote, m.note); });
  const favs = S.links.filter(l => l.fav && match(ui.q, l.title, l.url, l.note));
  if (!marks.length && !favs.length) return head + empty('bookmark', 'Закладок пока нет', 'В читалке выделите текст и нажмите «В закладки», либо отметьте ссылку звездой.');
  const byBook = {};
  marks.forEach(m => (byBook[m.bookId] ||= []).push(m));
  let out = head;
  for (const [id, ms] of Object.entries(byBook)) {
    const b = S.books.find(x => x.id === id);
    out += `<h2>${esc(b.title)}</h2><div class="list">${ms.sort((a, c) => a.para - c.para).map(markCard).join('')}</div>`;
  }
  if (favs.length) out += `<h2>Избранные ссылки</h2><div class="list">${favs.map(l => `<article class="card glass"><div class="ttl">${esc(l.title || domain(l.url))}</div><a class="url" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.url)}</a><div class="acts"><button class="sm" data-act="copy-link" data-id="${l.id}">${ico('copy')}Копировать</button></div></article>`).join('')}</div>`;
  return out;
}
const markCard = m => `<article class="card glass">
  <div class="quote">${esc(m.quote)}</div>
  ${m.note ? `<div class="note">💬 ${esc(m.note)}</div>` : ''}
  <div class="acts"><button class="sm" data-act="goto-mark" data-id="${m.id}">${ico('book')}Перейти</button>
  <button class="sm" data-act="copy-mark" data-id="${m.id}">${ico('copy')}Копировать</button>
  <button class="sm" data-act="note-mark" data-id="${m.id}">${ico('edit')}Заметка</button>
  <button class="sm danger" data-act="del-mark" data-id="${m.id}" aria-label="Удалить">${ico('trash')}</button></div></article>`;

/* ---------- формы ---------- */
async function bookForm(b = {}) {
  const f = await openDlg(`<h3>${b.id ? 'Изменить книгу' : 'Новая книга'}</h3>
    <label>Название<input name="title" required autofocus value="${esc(b.title)}"></label>
    <div class="two"><label>Автор<input name="author" value="${esc(b.author)}"></label>
    <label>Статус<select name="status">${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${(b.status || 'plan') === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label></div>
    <label>Текст книги (вставьте или загрузите файл .txt)<textarea name="text" placeholder="Вставьте текст сюда — потом его будет удобно читать и копировать">${esc(b.text)}</textarea></label>
    <label>Файл .txt / .md<input type="file" name="file" accept=".txt,.md,text/plain"></label>
    <label>Заметки<textarea name="notes" style="min-height:70px">${esc(b.notes)}</textarea></label>
    <div class="btns"><button class="btn" value="cancel">Отмена</button><button class="btn primary" value="ok">Сохранить</button></div>`);
  if (!f) return;
  const file = f.get('file');
  let text = f.get('text');
  if (file && file.size) text = await file.text();
  const title = f.get('title').trim() || (file?.name || 'Без названия').replace(/\.\w+$/, '');
  if (b.id) {
    Object.assign(b, { title, author: f.get('author').trim(), status: f.get('status'), notes: f.get('notes').trim() });
    if (text !== b.text) { b.text = text; b.pos = 0; b.progress = 0; }
  } else {
    S.books.unshift({ id: uid(), title, author: f.get('author').trim(), status: f.get('status'), text, notes: f.get('notes').trim(), pos: 0, progress: 0, added: Date.now() });
  }
  save(); render();
}

async function linkForm(l) {
  const f = await openDlg(`<h3>${l ? 'Изменить ссылку' : 'Новые ссылки'}</h3>
    ${l ? `<label>Адрес<input name="url" required value="${esc(l.url)}"></label>` : `<label>Адреса (по одному на строку)<textarea name="url" required autofocus placeholder="https://…"></textarea></label>`}
    ${l ? `<label>Название<input name="title" value="${esc(l.title)}"></label>` : `<label>Название (для одной ссылки, можно пустым)<input name="title"></label>`}
    <label>Заметка<textarea name="note" style="min-height:70px">${esc(l?.note)}</textarea></label>
    <label>Теги через запятую<input name="tags" value="${esc((l?.tags || []).join(', '))}" placeholder="статьи, программирование"></label>
    <div class="btns"><button class="btn" value="cancel">Отмена</button><button class="btn primary" value="ok">Сохранить</button></div>`);
  if (!f) return;
  const tags = parseTags(f.get('tags')), note = f.get('note').trim(), title = f.get('title').trim();
  if (l) Object.assign(l, { url: normUrl(f.get('url')), title, note, tags });
  else {
    const urls = f.get('url').split(/\s+/).filter(Boolean).map(normUrl);
    urls.reverse().forEach(u => S.links.unshift({ id: uid(), url: u, title: urls.length === 1 ? title : '', note, tags, read: false, fav: false, added: Date.now() }));
    ui.tab = 'links';
  }
  save(); render();
}

async function dataDlg() {
  const f = await openDlg(`<h3>Данные</h3>
    <p class="hint">Всё хранится в вашем браузере на этом устройстве. Чтобы не потерять книги и ссылки или перенести их на другое устройство — сделайте экспорт и сохраните файл.</p>
    <div class="btns" style="justify-content:flex-start"><button type="button" class="btn primary" id="exp">Экспорт в файл</button><label class="btn" style="display:inline-grid;place-items:center;cursor:pointer">Импорт<input type="file" id="imp" accept=".json,application/json" hidden></label></div>
    <div class="btns"><button class="btn" value="cancel">Закрыть</button></div>`);
  return f;
}
document.addEventListener('click', e => {
  if (e.target.id === 'exp') {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(S, null, 1)], { type: 'application/json' }));
    a.download = `biblioteka-${new Date().toISOString().slice(0, 10)}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
});
document.addEventListener('change', async e => {
  if (e.target.id !== 'imp' || !e.target.files[0]) return;
  try {
    const d = JSON.parse(await e.target.files[0].text());
    if (!Array.isArray(d.books) || !Array.isArray(d.links)) throw 0;
    if (!confirm('Заменить текущие данные импортированными?')) return;
    S = { ...S, ...d, marks: d.marks || [], set: { ...S.set, ...(d.set || {}) } };
    save(); render(); dlg.close(); toast('Импортировано');
  } catch { toast('Файл не подходит'); }
});

/* ---------- читалка ---------- */
const R = { book: null, paras: [], cur: 0, raf: 0, selPara: -1, selText: '' };
const rs = $('#rscroll'), rt = $('#rtext');

function openReader(id, para) {
  const b = S.books.find(x => x.id === id); if (!b) return;
  if (!b.text) return bookForm(b);
  R.book = b; R.paras = paras(b.text);
  $('#rt').textContent = b.title;
  rt.innerHTML = R.paras.map((p, i) => `<p data-i="${i}">${esc(p)}<span class="pact"><button class="sm" data-p="copy">${ico('copy')}Абзац</button><button class="sm" data-p="mark">${ico('bookmark')}Закладка</button></span></p>`).join('');
  applyReaderSettings(); markParas(); updateDone();
  $('#reader').hidden = false; document.body.style.overflow = 'hidden';
  $('#rset').hidden = $('#rmarks').hidden = true;
  const target = para ?? b.pos ?? 0;
  requestAnimationFrame(() => {
    const el = rt.children[Math.min(target, R.paras.length - 1)];
    if (el && target > 0) { rs.scrollTop = el.offsetTop - 20; if (para != null) { el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1600); } }
    else rs.scrollTop = 0;
    trackScroll();
  });
  if (b.status === 'plan') { b.status = 'reading'; save(); }
}
function closeReader() {
  $('#reader').hidden = true; document.body.style.overflow = ''; hideSel();
  R.book = null; render();
}
function applyReaderSettings() {
  const s = S.set;
  rt.style.setProperty('--size', s.size + 'px'); rt.style.setProperty('--lh', s.lh); rt.style.setProperty('--width', s.width + 'px');
  rt.classList.toggle('serif', s.font === 'serif'); rt.classList.toggle('bright', s.tone === 'bright');
  $$('#rset [data-set]').forEach(i => { i.value = s[i.dataset.set]; i.nextElementSibling.textContent = i.dataset.set === 'size' ? s.size + ' px' : i.dataset.set === 'width' ? s.width : s.lh; });
  $$('#rset .seg').forEach(g => $$('button', g).forEach(b => b.classList.toggle('on', s[g.dataset.seg] === b.dataset.v)));
}
function markParas() {
  const set = new Set(S.marks.filter(m => m.bookId === R.book.id).map(m => m.para));
  $$('p', rt).forEach(p => p.classList.toggle('marked', set.has(+p.dataset.i)));
}
function updateDone() {
  const d = R.book.status === 'done';
  const btn = $('[data-r=done]'); btn.classList.toggle('on', d); btn.title = d ? 'Снять отметку «прочитано»' : 'Отметить прочитанной';
}
function trackScroll() {
  cancelAnimationFrame(R.raf);
  R.raf = requestAnimationFrame(() => {
    if (!R.book) return;
    const max = rs.scrollHeight - rs.clientHeight;
    const pr = max > 0 ? Math.min(1, rs.scrollTop / max) : 1;
    let lo = 0, hi = rt.children.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (rt.children[m].offsetTop - 30 <= rs.scrollTop) lo = m; else hi = m - 1; }
    R.cur = lo; R.book.pos = lo; R.book.progress = pr;
    $('#rbar').style.width = pr * 100 + '%';
    $('#rp').textContent = `${Math.round(pr * 100)}% · абзац ${lo + 1} из ${R.paras.length}`;
    $('#rend').innerHTML = pr > .985 && R.book.status !== 'done' ? '<button class="btn primary" data-r="done">Отметить прочитанной</button>' : '';
    save();
  });
}
rs.addEventListener('scroll', trackScroll, { passive: true });

function addMark(para, quote) {
  const m = { id: uid(), bookId: R.book.id, para, quote: quote.slice(0, 600), note: '', added: Date.now() };
  S.marks.push(m); save(); markParas(); toast('Закладка добавлена');
}
function bookMarksDrawer() {
  const ms = S.marks.filter(m => m.bookId === R.book.id).sort((a, b) => a.para - b.para);
  const d = $('#rmarks');
  d.innerHTML = `<h3>Закладки книги</h3>` + (ms.length ? ms.map(markCard).join('') : '<div class="empty"><span>Выделите текст и нажмите «В закладки».</span></div>');
  hydrateIcons(d);
}

/* выделение текста → панель «Копировать / В закладки» */
const sel = $('#seltools');
function hideSel() { sel.hidden = true; }
document.addEventListener('selectionchange', () => {
  if ($('#reader').hidden) return;
  const s = getSelection();
  const text = s.toString().trim();
  const node = s.anchorNode && (s.anchorNode.nodeType === 3 ? s.anchorNode.parentElement : s.anchorNode);
  const p = node?.closest?.('#rtext p');
  if (!text || !p) return hideSel();
  R.selPara = +p.dataset.i; R.selText = text.replace(/\s*(Абзац|Закладка)\s*$/g, '');
  const r = s.getRangeAt(0).getBoundingClientRect();
  sel.hidden = false;
  const w = sel.offsetWidth;
  sel.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
  sel.style.top = (r.top > 70 ? r.top - 56 : r.bottom + 12) + 'px';
});
sel.addEventListener('mousedown', e => e.preventDefault());
sel.addEventListener('click', e => {
  const a = e.target.dataset.sel; if (!a) return;
  if (a === 'copy') copy(R.selText); else addMark(R.selPara, R.selText);
  getSelection().removeAllRanges(); hideSel();
});

/* клик по абзацу — показать кнопки */
rt.addEventListener('click', e => {
  const btn = e.target.closest('[data-p]');
  const p = e.target.closest('p'); if (!p) return;
  const i = +p.dataset.i;
  if (btn) {
    if (btn.dataset.p === 'copy') copy(R.paras[i]);
    else {
      const ex = S.marks.filter(m => m.bookId === R.book.id && m.para === i);
      if (ex.length) { S.marks = S.marks.filter(m => !ex.includes(m)); save(); markParas(); toast('Закладка снята'); }
      else addMark(i, R.paras[i]);
    }
    return;
  }
  if (getSelection().toString().trim()) return;
  const was = p.classList.contains('sel');
  $$('p.sel', rt).forEach(x => x.classList.remove('sel'));
  if (!was) p.classList.add('sel');
});

/* ---------- обработчики событий ---------- */
$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-tab]'); if (!b) return;
  ui.tab = b.dataset.tab; ui.q = ''; $('#q').value = ''; render(); scrollTo(0, 0);
});
$('#q').addEventListener('input', e => { ui.q = e.target.value.trim(); render(); });

const find = (arr, id) => arr.find(x => x.id === id);
const actions = {
  add: () => ui.tab === 'links' ? linkForm() : bookForm(),
  data: dataDlg,
  'toggle-book'(id) { const b = find(S.books, id); b.status = b.status === 'done' ? 'reading' : 'done'; save(); render(); },
  status(id) { const b = find(S.books, id); b.status = { plan: 'reading', reading: 'done', done: 'plan' }[b.status]; save(); render(); },
  'edit-book': id => bookForm(find(S.books, id)),
  async 'del-book'(id) {
    const b = find(S.books, id);
    if (await confirmDlg(`Удалить «${b.title}»?`)) { S.books = S.books.filter(x => x !== b); S.marks = S.marks.filter(m => m.bookId !== id); save(); render(); }
  },
  'copy-link': id => copy(find(S.links, id).url),
  'toggle-link'(id) { const l = find(S.links, id); l.read = !l.read; save(); render(); },
  'fav-link'(id) { const l = find(S.links, id); l.fav = !l.fav; save(); render(); },
  'edit-link': id => linkForm(find(S.links, id)),
  async 'del-link'(id) { if (await confirmDlg('Удалить ссылку?')) { S.links = S.links.filter(l => l.id !== id); save(); render(); } },
  'goto-mark'(id) { const m = find(S.marks, id); if (R.book) { rs.scrollTop = rt.children[m.para].offsetTop - 20; $('#rmarks').hidden = true; } else openReader(m.bookId, m.para); },
  'copy-mark': id => copy(find(S.marks, id).quote),
  async 'note-mark'(id) { const m = find(S.marks, id); const v = await askText('Заметка к закладке', m.note); if (v !== null) { m.note = v; save(); R.book ? bookMarksDrawer() : render(); } },
  'del-mark'(id) { S.marks = S.marks.filter(m => m.id !== id); save(); if (R.book) { markParas(); bookMarksDrawer(); } else render(); },
};
document.addEventListener('click', e => {
  const c = e.target.closest('[data-chip]');
  if (c) { const k = c.dataset.chip, v = c.dataset.v; ui[k] = k === 'tag' && ui.tag === v ? '' : v; render(); return; }
  const a = e.target.closest('[data-act]');
  if (a) { actions[a.dataset.act]?.(a.dataset.id); return; }
  const o = e.target.closest('[data-open]');
  if (o && !e.target.closest('[data-stop]')) openReader(o.dataset.open);
});

/* панель читалки */
$('#reader .rbar').addEventListener('click', e => {
  const k = e.target.closest('[data-r]')?.dataset.r; if (!k) return;
  if (k === 'close') closeReader();
  if (k === 'aa') { $('#rmarks').hidden = true; $('#rset').hidden = !$('#rset').hidden; }
  if (k === 'marks') { $('#rset').hidden = true; bookMarksDrawer(); $('#rmarks').hidden = !$('#rmarks').hidden; }
});
$('#reader').addEventListener('click', e => {
  if (e.target.closest('[data-r=done]')) {
    R.book.status = R.book.status === 'done' ? 'reading' : 'done'; save(); updateDone(); trackScroll();
    toast(R.book.status === 'done' ? 'Отмечено как прочитанное' : 'Отметка снята');
  }
});
$('#rset').addEventListener('input', e => { const k = e.target.dataset.set; if (!k) return; S.set[k] = +e.target.value; applyReaderSettings(); save(); });
$('#rset').addEventListener('click', e => {
  const g = e.target.closest('[data-seg]'), b = e.target.closest('[data-v]');
  if (g && b) { S.set[g.dataset.seg] = b.dataset.v; applyReaderSettings(); save(); }
});
document.addEventListener('keydown', e => {
  if (!$('#reader').hidden && e.key === 'Escape' && !dlg.open) closeReader();
});

/* ---------- старт ---------- */
(async () => {
  const d = await store.load();
  if (d) S = { ...S, ...d, set: { ...S.set, ...(d.set || {}) } };
  hydrateIcons();
  $('[data-act=add]').innerHTML = ico('plus');
  $('[data-act=data]').innerHTML = ico('data');
  $('[data-r=close]').innerHTML = ico('back');
  $('[data-r=marks]').innerHTML = ico('bookmark');
  $('[data-r=aa]').innerHTML = ico('aa');
  $('[data-r=done]').innerHTML = ico('check');
  render();
  if (navigator.storage?.persist) navigator.storage.persist();
})();
})();
