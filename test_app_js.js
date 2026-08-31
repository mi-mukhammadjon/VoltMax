/* app.js mantig'ini brauzersiz tekshirish.
 *
 * Soxta DOM/sessionStorage yaratib, faylni shu muhitda ishga tushiramiz va
 * hodisalarni qo'lda chaqiramiz. Maqsad — skroll xotirasi, throttle va
 * confirm() bekor qilinganda so'rov ketmasligini tasdiqlash.
 */
const fs = require('fs');
const vm = require('vm');

let failures = 0;
function check(label, cond, extra = '') {
  console.log(`${cond ? 'OK  ' : 'XATO'}  ${label} ${extra}`);
  if (!cond) failures++;
}

// ── Minimal DOM ───────────────────────────────────────────────
const listeners = { window: {}, document: {} };
const store = {};
const fetchCalls = [];

/* Kichik DOM: sana tanlagich tugunlarni haqiqiy DOM API bilan yasaydi,
   shuning uchun stub ham bola-ota bog'lanishini va oddiy selektorlarni
   tushunishi kerak. */
function matches(el, sel) {
  if (!el || !sel) return false;
  const tag = (sel.match(/^[a-z]+/) || [])[0];
  if (tag && (el.tagName || '').toLowerCase() !== tag) return false;

  const attrs = sel.match(/\[[^\]]+\]/g) || [];
  for (const raw of attrs) {
    const [name, value] = raw.slice(1, -1).split('=');
    if (!el.hasAttribute(name)) return false;
    if (value !== undefined && el.getAttribute(name) !== value.replace(/['"]/g, '')) return false;
  }

  const classes = sel.match(/\.[A-Za-z0-9_-]+/g) || [];
  return classes.every((c) => el.classList.contains(c.slice(1)));
}

function makeEl(extra = {}) {
  const classes = new Set((extra.className || '').split(' ').filter(Boolean));
  const el = {
    tagName: (extra.tagName || 'div').toUpperCase(),
    className: extra.className || '', attributes: {},
    children: [], parentNode: null, textContent: '',
    style: {},
    classList: {
      // Brauzerdagidek: `toggle(c, on)` ikkinchi argumentni hisobga oladi
      toggle(c, on) {
        const want = on === undefined ? !classes.has(c) : !!on;
        if (want) classes.add(c); else classes.delete(c);
        return want;
      },
      add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
      contains(c) { return classes.has(c); },
    },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k] ?? null; },
    removeAttribute(k) { delete this.attributes[k]; },
    hasAttribute(k) { return k in this.attributes; },
    appendChild(child) {
      this.children.push(child);
      if (child) child.parentNode = this;
      return child;
    },
    removeChild(child) {
      this.children = this.children.filter((c) => c !== child);
      if (child) child.parentNode = null;
      return child;
    },
    get firstChild() { return this.children[0] || null; },
    matches(sel) { return matches(this, sel); },
    closest(sel) {
      let node = this;
      while (node) {
        if (matches(node, sel)) return node;
        node = node.parentNode;
      }
      return null;
    },
    querySelector(sel) {
      for (const child of this.children) {
        if (matches(child, sel)) return child;
        const found = child.querySelector ? child.querySelector(sel) : null;
        if (found) return found;
      }
      return null;
    },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 100, bottom: 130, left: 40, right: 240 }; },
    focus() {},
    dispatchEvent(evt) { (this._events || []).forEach((fn) => fn(evt)); return true; },
    addEventListener(type, fn) { (this._events ||= []).push(fn); },
  };
  // `className` sinflar to'plamiga ham tushsin (yasashda berilgani uchun)
  Object.defineProperty(el, 'className', {
    get() { return [...classes].join(' '); },
    set(v) { classes.clear(); String(v).split(' ').filter(Boolean).forEach((c) => classes.add(c)); },
  });
  el.className = extra.className || '';
  return Object.assign(el, extra);
}

const layoutEl = makeEl({ innerHTML: '<p>eski</p>' });

const sandbox = {
  console,
  setTimeout, clearTimeout,
  requestAnimationFrame: (fn) => fn(),
  window: {
    scrollY: 0, innerWidth: 1280, innerHeight: 900,
    scrollTo(x, y) { sandbox.window.scrollY = y; },
    addEventListener(type, fn) { (listeners.window[type] ||= []).push(fn); },
    location: { href: 'http://t/stations/', pathname: '/stations/', search: '' },
  },
  toasts: [],
  toggleBtn: null,
  toggleFields: [],
  checkbox: null,
  document: {
    title: '',
    documentElement: {
      attrs: { 'data-theme': 'dark', 'data-sidebar': 'expanded' },
      getAttribute(k) { return this.attrs[k]; },
      setAttribute(k, v) { this.attrs[k] = v; },
      classes: new Set(),
      classList: {
        add(c) { sandbox.document.documentElement.classes.add(c); },
        contains(c) { return sandbox.document.documentElement.classes.has(c); },
      },
    },
    body: makeEl({ tagName: 'body' }),
    createElement: (tag) => makeEl({ tagName: tag }),
    querySelector: (sel) => (sel === '.layout' ? layoutEl
      : sel.indexOf('checkbox') !== -1 ? sandbox.checkbox : null),
    querySelectorAll: (sel) => (sel.startsWith('.toast') ? sandbox.toasts
      : sel.startsWith('[data-toggle-when') ? sandbox.toggleFields : []),
    getElementById: (id) => (id === 'nav-open' ? sandbox.toggleBtn : null),
    addEventListener(type, fn) { (listeners.document[type] ||= []).push(fn); },
  },
  history: { scrollRestoration: 'auto', pushState() {} },
  sessionStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = v; },
  },
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = v; },
  },
  fetch: (url, opts) => {
    fetchCalls.push({ url, opts });
    return Promise.resolve({ url, text: () => Promise.resolve('<div class="layout"><p>yangi</p></div>') });
  },
  DOMParser: class {
    parseFromString() {
      return { title: 'yangi', querySelector: (s) => (s === '.layout' ? makeEl({ innerHTML: '<p>yangi</p>' }) : null) };
    }
  },
  HTMLFormElement: class {},
  // Brauzerda global, Node sandbox'ida esa qo'lda beriladi
  URLSearchParams,
  AbortController,
  FormData: class { constructor(form) { this.form = form; } },
  Event: class { constructor(type, opts) { this.type = type; Object.assign(this, opts || {}); } },
};
sandbox.location = sandbox.window.location;
sandbox.global = sandbox;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/dashboard/app.js', 'utf8'), sandbox);

const fire = (target, type, evt) => (listeners[target][type] || []).forEach((fn) => fn(evt));

// ── 1. scrollRestoration qo'lga olindimi ──────────────────────
check('scrollRestoration = manual', sandbox.history.scrollRestoration === 'manual');

// ── 2. Skroll pozitsiyasi saqlanadimi ─────────────────────────
sandbox.window.scrollY = 640;
fire('window', 'scroll');

setTimeout(() => {
  const saved = JSON.parse(store['voltmax_scroll_v2'] || '{}');
  check('skroll sessionStorage ga yozildi', saved['/stations/'] && saved['/stations/'].y === 640,
        `-> ${JSON.stringify(saved)}`);

  // ── 3. Throttle: hodisa obyekti immediate deb qabul qilinmasin ──
  const before = store['voltmax_scroll_v2'];
  sandbox.window.scrollY = 700;
  fire('window', 'scroll');
  fire('window', 'scroll');
  fire('window', 'scroll');
  check('ketma-ket scroll darhol yozmadi (throttle)', store['voltmax_scroll_v2'] === before);

  setTimeout(() => {
    const after = JSON.parse(store['voltmax_scroll_v2']);
    check('throttle tugagach yozildi', after['/stations/'].y === 700);

    // ── 4. confirm() bekor qilsa — so'rov ketmasin ──────────────
    fetchCalls.length = 0;
    const form = Object.create(sandbox.HTMLFormElement.prototype);
    Object.assign(form, makeEl({ getAttribute: (k) => (k === 'method' ? 'post' : '/act/') }));
    fire('document', 'submit', { defaultPrevented: true, target: form, preventDefault() {} });
    check('bekor qilingan formada fetch chaqirilmadi', fetchCalls.length === 0, `-> ${fetchCalls.length}`);

    // ── 5. Tasdiqlangan forma — fetch ketadi ───────────────────
    let prevented = false;
    fire('document', 'submit', {
      defaultPrevented: false, target: form, preventDefault() { prevented = true; },
    });
    check('tasdiqlangan formada fetch ketdi', fetchCalls.length === 1, `-> ${fetchCalls.length}`);
    check('standart yuborish to\'xtatildi', prevented);
    check('AJAX sarlavhasi qo\'yildi',
          fetchCalls[0]?.opts?.headers?.['X-Requested-With'] === 'XMLHttpRequest');

    // ── 6. Toast: yopish tugmasi ─────────────────────────────
    let removed = null;
    const toast = makeEl({ className: 'toast success' });
    toast.parentNode = { removeChild(el) { removed = el; }, children: [], parentNode: null };
    const closeBtn = makeEl();
    closeBtn.closest = (sel) => (sel === '.toast-close' ? closeBtn : sel === '.toast' ? toast : null);
    fire('document', 'click', {
      target: closeBtn, defaultPrevented: false, button: 0,
      preventDefault() {}, metaKey: false, ctrlKey: false, shiftKey: false,
    });
    check('yopish tugmasi toastni yashirdi', toast.classList.contains('hiding'));

    setTimeout(() => {
      check('toast DOM dan olib tashlandi', removed === toast);

      // ── 7. Toastlar ishga tushirildimi ─────────────────────
      const okToast = makeEl({ className: 'toast success' });
      const errToast = makeEl({ className: 'toast error' });
      [okToast, errToast].forEach((t) => {
        t.parentNode = { removeChild() {}, children: [], parentNode: null };
        t.addEventListener = () => {};
      });
      sandbox.toasts = [okToast, errToast];
      fire('document', 'DOMContentLoaded');
      check('muvaffaqiyat toasti armed', okToast.getAttribute('data-armed') === '1');
      check('xato toasti ham armed', errToast.getAttribute('data-armed') === '1');

      // ── 8. Gamburger: sidebarni yig'ish va qayta ochish ──
      const root = sandbox.document.documentElement;
      const tgl = makeEl();
      tgl.closest = (sel) => (sel === '#nav-open' ? tgl : null);
      sandbox.toggleBtn = tgl;
      const clickOn = (el) => fire('document', 'click', {
        target: el, defaultPrevented: false, button: 0,
        preventDefault() {}, metaKey: false, ctrlKey: false, shiftKey: false,
      });

      clickOn(tgl);
      check("bosilganda yigildi", root.getAttribute('data-sidebar') === 'collapsed',
            `-> ${root.getAttribute('data-sidebar')}`);
      check("tugma yozuvi yangilandi", tgl.getAttribute('title') === 'Menyuni yoyish',
            `-> ${tgl.getAttribute('title')}`);

      clickOn(tgl);
      check("qayta bosilganda ochildi", root.getAttribute('data-sidebar') === 'expanded',
            `-> ${root.getAttribute('data-sidebar')}`);
      check("holat saqlandi", store['voltmax_sidebar'] === 'expanded', `-> ${store['voltmax_sidebar']}`);

      // ── 9. Shartli maydon: checkbox bilan ochilishi ──────
      const field = makeEl();
      field.getAttribute = (k) => (k === 'data-toggle-when' ? 'apply_discount' : null);
      field.hidden = null;
      sandbox.toggleFields = [field];
      sandbox.checkbox = { type: 'checkbox', name: 'apply_discount', checked: false };

      fire('document', 'change', { target: sandbox.checkbox });
      check("belgilanmagan holda maydon yashirin", field.hidden === true, `-> ${field.hidden}`);

      sandbox.checkbox.checked = true;
      fire('document', 'change', { target: sandbox.checkbox });
      check("belgilangach maydon ochildi", field.hidden === false, `-> ${field.hidden}`);

      // ── 10. Pul maydoni: vergul/nuqta = kasr ajratgichi ──
      const money = makeEl();
      money.classList.contains = (c) => c === 'money-input';
      money.selectionStart = 0;
      money.setSelectionRange = () => {};

      const type = (v) => { money.value = v; fire('document', 'input', { target: money }); };
      const blurIt = (v) => { money.value = v; fire('document', 'blur', { target: money }); };
      const focusIt = (v) => { money.value = v; fire('document', 'focusin', { target: money }); };

      type('1500');
      check("1500 -> 1 500", money.value === "1 500", JSON.stringify(money.value));
      type('1500.5');
      check("nuqta kasr ochadi", money.value === "1 500.5", JSON.stringify(money.value));
      type('1500,5');
      check("vergul ham kasr ochadi", money.value === "1 500.5", JSON.stringify(money.value));
      type('1500,');
      check("nuqta bosilishi bilan saqlanadi", money.value === "1 500.", JSON.stringify(money.value));
      type('1500,567');
      check("kasr 2 xonagacha", money.value === "1 500.56", JSON.stringify(money.value));
      type('1234567');
      check("butun qism guruhlanadi", money.value === "1 234 567", JSON.stringify(money.value));
      type('ab12cd,3x4');
      check("harflar tashlandi", money.value === "12.34", JSON.stringify(money.value));

      blurIt('1500,5');
      check("blur -> 1 500.50", money.value === "1 500.50", JSON.stringify(money.value));
      blurIt('1500');
      check("blur -> 1 500.00", money.value === "1 500.00", JSON.stringify(money.value));
      blurIt('');
      check("bosh qiymat bosh qoladi", money.value === "", JSON.stringify(money.value));

      focusIt("1 500.00");
      check("fokusda bosh kasr olindi", money.value === "1 500", JSON.stringify(money.value));
      focusIt("1 500.50");
      check("nolga teng bolmagan kasr saqlandi", money.value === "1 500.50", JSON.stringify(money.value));




      /* ══ Rasm yuklash maydoni ══════════════════════════════
         Soxta maydon quramiz: box + ichidagi qismlar. `closest`
         har bir bolaga box ni qaytaradi. */
      function makeImageDrop(initialSrc) {
        const cls = new Set(initialSrc ? ['has-image'] : []);
        // `closest` haqiqiy DOM'dagidek — hodisa nishonidan box topiladi
        const file = { className: 'id-input', value: '', files: [],
                       classList: { contains: (c) => c === 'id-input' },
                       closest: (sel) => (sel === '[data-image-drop]' ? box : null) };
        const clear = { value: '' };
        const preview = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
                          getAttribute(k) { return this.attrs[k] ?? null; } };
        const nameEl = { textContent: '', classList: { toggle(c, on) { this.on = on; } } };
        const undo = { hidden: true };
        const box = {
          attrs: initialSrc ? { 'data-initial-src': initialSrc, 'data-initial-name': 'hero.png' } : {},
          getAttribute(k) { return this.attrs[k] ?? null; },
          setAttribute(k, v) { this.attrs[k] = v; },
          contains: () => false,
          classList: {
            add: (c) => cls.add(c), remove: (c) => cls.delete(c),
            contains: (c) => cls.has(c),
            toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)),
          },
          querySelector(sel) {
            return { '.id-input': file, '[data-clear-flag]': clear, '[data-preview]': preview,
                     '[data-file-name]': nameEl, '[data-undo]': undo }[sel] || null;
          },
        };
        if (initialSrc) preview.setAttribute('src', initialSrc);
        const child = (own) => ({
          closest: (sel) => (sel === '[data-image-drop]' ? box : (sel === own ? {} : null)),
        });
        return { box, file, clear, preview, nameEl, undo, cls, child };
      }

      // -- O'chirish: yashirin maydon to'ladi, ko'rinish bo'shaydi --
      let drop = makeImageDrop('/media/hero.png');
      fire('document', 'click', { target: drop.child('[data-remove]'), preventDefault() {} });
      check("o'chirishda -clear = 1", drop.clear.value === '1', JSON.stringify(drop.clear.value));
      check("o'chirishda ko'rinish tozalandi", drop.preview.getAttribute('src') === '');
      check("o'chirishda has-image olindi", !drop.cls.has('has-image'));
      check("o'chirishda qaytarish ko'rindi", drop.undo.hidden === false);

      // -- Qaytarish: saqlangan rasmga qaytadi --
      fire('document', 'click', { target: drop.child('[data-undo]'), preventDefault() {} });
      check("qaytarishda -clear bo'shadi", drop.clear.value === '');
      check('qaytarishda rasm tiklandi', drop.preview.getAttribute('src') === '/media/hero.png');
      check('qaytarishda has-image qaytdi', drop.cls.has('has-image'));

      // -- Yangi fayl tanlash: o'chirish belgisi bekor bo'ladi --
      drop = makeImageDrop('/media/hero.png');
      fire('document', 'click', { target: drop.child('[data-remove]'), preventDefault() {} });
      drop.file.files = [{ name: 'yangi.png', type: 'image/png', size: 1024 }];
      fire('document', 'change', { target: drop.file });
      check('yangi faylda -clear bekor qilindi', drop.clear.value === '',
            JSON.stringify(drop.clear.value));
      check("yangi fayl nomi ko'rsatildi", drop.nameEl.textContent === 'yangi.png',
            JSON.stringify(drop.nameEl.textContent));
      check("yangi faylda has-image qo'yildi", drop.cls.has('has-image'));

      // -- Rasm bo'lmagan fayl rad etiladi --
      drop = makeImageDrop(null);
      drop.file.files = [{ name: 'hujjat.pdf', type: 'application/pdf', size: 10 }];
      fire('document', 'change', { target: drop.file });
      check('pdf rad etildi', !drop.cls.has('has-image'));
      check('pdf da input tozalandi', drop.file.value === '');
      check('pdf da xato matni', /rasm/i.test(drop.nameEl.textContent), drop.nameEl.textContent);

      // -- Katta fayl rad etiladi --
      drop = makeImageDrop(null);
      drop.file.files = [{ name: 'katta.png', type: 'image/png', size: 9 * 1024 * 1024 }];
      fire('document', 'change', { target: drop.file });
      check('katta fayl rad etildi', !drop.cls.has('has-image'));
      check('katta faylda MB ogohlantirishi', /MB/.test(drop.nameEl.textContent),
            drop.nameEl.textContent);


      /* ══ Jonli filtr ════════════════════════════════════════
         Tekshiriladi: so'rov darhol ketmasligi (debounce), keyin ketishi,
         FAQAT belgilangan hudud almashishi va tab bosilganda ham shunday
         bo'lishi. */
      function makeSearchForm(value) {
        const field = {
          type: 'search', name: 'q', value: value, disabled: false,
          selectionStart: value.length,
          closest: (sel) => (sel === '[data-live-search]' ? form : null),
        };
        // Yashirin `status` maydoni — tab bosilganda shu yerga yoziladi
        const hidden = { name: 'status', value: '', type: 'hidden', disabled: false };
        const form = {
          elements: [hidden, field],
          classList: { add() {}, remove() {}, toggle() {} },
          getAttribute: (k) => (k === 'action' ? '/rfid/' : k === 'data-target' ? '#card-results' : null),
          hasAttribute: (k) => k === 'data-live-search',
          querySelector: (sel) => (sel === 'input[type=search]' ? field
            : sel === 'input[name=status]' ? hidden : null),
          // Kengaytirilgan filtr oynasi shu formaning ichida bo'lishi mumkin
          modals: [],
          querySelectorAll(sel) { return sel === '.modal' ? this.modals : []; },
        };
        return { form, field, hidden };
      }

      // Oldingi testlar `.layout` ni almashtirgan — toza holatdan boshlaymiz
      layoutEl.innerHTML = '<p>tegilmagan</p>';

      const search = makeSearchForm('ab');
      const statusInput = search.hidden;
      // Almashtiriladigan hudud — `.layout` EMAS, faqat shu bo'lak
      const region = makeEl({ innerHTML: '<table>eski</table>' });

      sandbox.document.querySelector = (sel) => {
        if (sel === '.layout') return layoutEl;
        if (sel === '#card-results' || sel === '[data-live-region]') return region;
        if (sel === '[data-live-search]') return search.form;
        if (sel.indexOf('live-search') !== -1) return search.field;
        if (sel.indexOf('checkbox') !== -1) return sandbox.checkbox;
        return null;
      };
      // Javobda hudud topilishi uchun DOMParser ham uni qaytarsin
      sandbox.DOMParser = class {
        parseFromString() {
          return {
            title: 'yangi',
            querySelector: (s) => ((s === '#card-results' || s === '[data-live-region]')
              ? makeEl({ innerHTML: '<table>yangi</table>' })
              : s === '.layout' ? makeEl({ innerHTML: '<p>yangi</p>' }) : null),
          };
        }
      };

      fetchCalls.length = 0;
      fire('document', 'input', { target: search.field });
      check('yozilganda so\'rov darhol ketmadi', fetchCalls.length === 0, fetchCalls.length);

      setTimeout(() => {
        check('kechikishdan keyin so\'rov ketdi', fetchCalls.length === 1,
              fetchCalls.length);
        check('manzilda qidiruv bor',
              (fetchCalls[0] || {}).url === '/rfid/?q=ab', (fetchCalls[0] || {}).url);
        check('AJAX sarlavhasi qo\'yildi',
              fetchCalls[0]?.opts?.headers?.['X-Requested-With'] === 'XMLHttpRequest');

        // Bir xil qiymatda takror so'rov ketmasin
        fetchCalls.length = 0;
        fire('document', 'input', { target: search.field });
        setTimeout(() => {
          check('bir xil qiymatda takror so\'rov yo\'q', fetchCalls.length === 0,
                fetchCalls.length);

          // Enter bosilsa kutmasdan ketadi
          fetchCalls.length = 0;
          search.field.value = 'abc';
          fire('document', 'submit', {
            target: Object.assign(Object.create(sandbox.HTMLFormElement.prototype), search.form),
            defaultPrevented: false, preventDefault() {},
          });
          check('Enter darhol qidiradi', fetchCalls.length === 1, fetchCalls.length);

          setTimeout(() => {
            // Butun sahifa emas, FAQAT hudud almashishi kerak
            check('faqat hudud almashdi', region.innerHTML === '<table>yangi</table>',
                  region.innerHTML);
            check('sahifaning qolgani tegilmadi',
                  layoutEl.innerHTML === '<p>tegilmagan</p>', layoutEl.innerHTML);

            // ── Filtr tabi ham qisman almashtiradi ──
            const tabs = makeEl();
            const tabA = makeEl({ className: 'active' });
            const tabB = makeEl({ href: '/rfid/?status=active' });
            [tabA, tabB].forEach((t) => {
              t.attributes['data-live-filter'] = '';
              t.closest = (sel) => (sel === '[data-live-filter]' ? t
                : sel === '.filter-tabs' ? tabs : null);
            });
            tabB.attributes['data-filter-value'] = 'active';
            tabs.querySelectorAll = () => [tabA, tabB];

            fetchCalls.length = 0;
            region.innerHTML = '<table>eski</table>';
            fire('document', 'click', {
              target: tabB, defaultPrevented: false, button: 0,
              metaKey: false, ctrlKey: false, shiftKey: false, preventDefault() {},
            });
            check('tab bosilganda so\'rov ketdi', fetchCalls.length === 1, fetchCalls.length);
            // Manzil forma bo'yicha quriladi — qidiruv ham birga ketadi
            check('tab manzilida barcha filtr bor',
                  (fetchCalls[0] || {}).url === '/rfid/?status=active&q=abc',
                  (fetchCalls[0] || {}).url);
            check('aktiv tab ko\'chdi',
                  tabB.classList.contains('active') && !tabA.classList.contains('active'));
            check('filtr qidiruv formasiga yozildi', statusInput.value === 'active',
                  statusInput.value);

            setTimeout(() => {
              check('tabda ham faqat hudud almashdi',
                    region.innerHTML === '<table>yangi</table>', region.innerHTML);


              /* ══ Ko'p tanlovli korporativ filtr ══════════════════ */
              const msItems = [
                { type: 'checkbox', name: 'company', value: 'none', checked: false, disabled: false },
                { type: 'checkbox', name: 'company', value: '7', checked: false, disabled: false },
              ];
              const msBox = makeEl();
              const msPanel = makeEl();
              msPanel.hidden = true;
              const msToggle = makeEl();
              const msCount = makeEl();
              msCount.hidden = true;

              msBox.querySelector = (sel) => (sel === '[data-ms-panel]' ? msPanel
                : sel === '[data-ms-toggle]' ? msToggle
                : sel === '[data-ms-count]' ? msCount : null);
              msBox.querySelectorAll = () => msItems;
              msBox.closest = (sel) => (sel === '[data-live-search]' ? search.form
                : sel === '[data-multi-select]' ? msBox : null);

              msItems.forEach((i) => {
                i.matches = (sel) => sel === '[data-ms-item]';
                i.closest = (sel) => (sel === '[data-multi-select]' ? msBox : null);
              });
              // Katakchalar formaga ham tegishli — manzilga tushishi kerak
              search.form.elements = [search.hidden, search.field].concat(msItems);

              const openBtn = makeEl();
              openBtn.closest = (sel) => (sel === '[data-multi-select]' ? msBox
                : sel === '[data-ms-toggle]' ? openBtn : null);

              sandbox.document.querySelectorAll = (sel) =>
                (sel.indexOf('multi-select') !== -1
                  ? (msBox.classList.contains('is-open') ? [msBox] : [])
                  : sel.startsWith('.toast') ? sandbox.toasts
                  : sel.startsWith('[data-toggle-when') ? sandbox.toggleFields : []);

              const clickMs = (el) => fire('document', 'click', {
                target: el, defaultPrevented: false, button: 0,
                metaKey: false, ctrlKey: false, shiftKey: false, preventDefault() {},
              });

              clickMs(openBtn);
              check('ro\'yxat ochildi', msBox.classList.contains('is-open') && !msPanel.hidden);

              fetchCalls.length = 0;
              msItems[1].checked = true;
              fire('document', 'change', { target: msItems[1] });
              check('tanlangach so\'rov ketdi', fetchCalls.length === 1, fetchCalls.length);
              check('manzilda korporativ bor',
                    (fetchCalls[0] || {}).url.indexOf('company=7') !== -1,
                    (fetchCalls[0] || {}).url);
              check('son yangilandi', msCount.textContent === '1' && !msCount.hidden,
                    msCount.textContent);

              // Ikkinchisini ham tanlaymiz — ikkalasi manzilga tushsin
              fetchCalls.length = 0;
              msItems[0].checked = true;
              fire('document', 'change', { target: msItems[0] });
              const url2 = (fetchCalls[0] || {}).url || '';
              check('ikkala tanlov ham manzilda',
                    url2.indexOf('company=none') !== -1 && url2.indexOf('company=7') !== -1, url2);
              check('son ikkiga oshdi', msCount.textContent === '2', msCount.textContent);

              // Tozalash
              fetchCalls.length = 0;
              const clearBtn = makeEl();
              clearBtn.closest = (sel) => (sel === '[data-multi-select]' ? msBox
                : sel === '[data-ms-clear]' ? clearBtn : null);
              clickMs(clearBtn);
              check('tozalash belgilarni oldi',
                    msItems.every((i) => !i.checked));
              check('tozalashdan keyin manzil toza',
                    ((fetchCalls[0] || {}).url || '').indexOf('company=') === -1,
                    (fetchCalls[0] || {}).url);

              // Esc bilan yopiladi
              msBox.classList.add('is-open');
              fire('document', 'keydown', { key: 'Escape' });
              check('Esc ro\'yxatni yopdi', !msBox.classList.contains('is-open'));


              // ── 12. Sana tanlagich ──────────────────────────
              check('JS belgisi <html> ga qo\'yildi',
                    sandbox.document.documentElement.classList.contains('js'));

              // Bayramlar seans xotirasidan olinadi — tarmoqqa chiqilmaydi
              store['voltmax_holidays'] = JSON.stringify({
                v: '0',   // <body data-holidays> yo'q — versiya "0"
                days: {
                  '2026-08-31': 'Mustaqillik kuni',
                  '2026-09-01': 'Mustaqillik kuni (dam olish)',
                },
              });

              const dateInput = makeEl({ tagName: 'input' });
              dateInput.setAttribute('type', 'date');
              dateInput.value = '2026-08-30';

              const press = (el, extra = {}) => fire('document', 'mousedown', {
                target: el, preventDefault() {}, ...extra,
              });
              const clickDp = (el) => fire('document', 'click', {
                target: el, defaultPrevented: false, button: 0,
                preventDefault() {}, metaKey: false, ctrlKey: false, shiftKey: false,
              });
              // Ochiq maydonni qayta bosish oynani yopadi (toggle), shuning
              // uchun test har safar avval Esc bilan yopib, keyin ochadi
              const openDp = (el) => {
                fire('document', 'keydown', { key: 'Escape' });
                press(el);
              };
              const panelOf = () => sandbox.document.body.children
                .find((c) => c.classList && c.classList.contains('datepicker'));

              press(dateInput);
              const dp = panelOf();
              check('sana maydoni bosilganda kalendar ochildi', !!dp && dp.hidden === false);

              const title = dp.querySelector('[data-dp-title]');
              check('sarlavhada maydondagi oy turibdi', title.textContent === 'Avgust 2026',
                    title.textContent);

              const grid = dp.querySelector('[data-dp-grid]');
              // 2026-yil avgust shanbadan boshlanadi va 31 kun — 6 hafta
              check('avgust uchun 6 hafta chizildi', grid.children.length === 42,
                    grid.children.length);
              check('hafta dushanbadan boshlandi',
                    grid.children[0].getAttribute('data-dp-day') === '2026-07-27',
                    grid.children[0].getAttribute('data-dp-day'));

              const selected = grid.children.filter((d) => d.classList.contains('is-selected'));
              check('tanlangan kun bittagina belgilandi',
                    selected.length === 1 && selected[0].getAttribute('data-dp-day') === '2026-08-30',
                    selected.map((d) => d.getAttribute('data-dp-day')).join());
              check('boshqa oy kunlari xiralashtirildi',
                    grid.children[0].classList.contains('is-other'));

              // Oyni almashtirish
              const next = dp.querySelector('[data-dp-move="1"]');
              clickDp(next);
              check('keyingi oyga o\'tdi', title.textContent === 'Sentabr 2026', title.textContent);
              clickDp(dp.querySelector('[data-dp-move="-1"]'));
              clickDp(dp.querySelector('[data-dp-move="-1"]'));
              check('ikki marta ortga qaytdi', title.textContent === 'Iyul 2026', title.textContent);

              // Kun tanlash: qiymat yoziladi, change ketadi, oyna yopiladi
              let changed = 0;
              dateInput.addEventListener('change', () => { changed++; });
              // Yopib qayta ochamiz: kalendar maydondagi qiymat oyiga qaytishi kerak
              fire('document', 'keydown', { key: 'Escape' });
              press(dateInput);
              check('qayta ochilganda qiymat oyiga qaytdi',
                    title.textContent === 'Avgust 2026', title.textContent);
              const day15 = dp.querySelector('[data-dp-day="2026-08-15"]');
              clickDp(day15);
              check('bosilgan kun maydonga yozildi', dateInput.value === '2026-08-15',
                    dateInput.value);
              check('change hodisasi yuborildi', changed === 1, changed);
              check('tanlangach oyna yopildi', dp.hidden === true);

              // Chegaralar: min'dan oldingi kunlar bosilmaydi
              dateInput.setAttribute('min', '2026-08-10');
              dateInput.setAttribute('max', '2026-08-20');
              openDp(dateInput);
              const days = dp.querySelector('[data-dp-grid]').children;
              const blocked = days.find((d) => d.getAttribute('data-dp-day') === '2026-08-09');
              const allowed = days.find((d) => d.getAttribute('data-dp-day') === '2026-08-12');
              check('chegaradan tashqari kun o\'chirilgan', blocked.disabled === true);
              check('chegara ichidagi kun ochiq', !allowed.disabled);
              dateInput.removeAttribute('min');
              dateInput.removeAttribute('max');

              // "Tozalash" va "Bugun"
              openDp(dateInput);
              clickDp(dp.querySelector('[data-dp-clear]'));
              check('tozalash qiymatni bo\'shatdi', dateInput.value === '');

              openDp(dateInput);
              clickDp(dp.querySelector('[data-dp-today]'));
              const today = new Date();
              const iso = today.getFullYear() + '-'
                + String(today.getMonth() + 1).padStart(2, '0') + '-'
                + String(today.getDate()).padStart(2, '0');
              check('"Bugun" bugungi sanani qo\'ydi', dateInput.value === iso, dateInput.value);

              // Esc va tashqariga bosish yopadi
              openDp(dateInput);
              fire('document', 'keydown', { key: 'Escape' });
              check('Esc kalendarni yopdi', dp.hidden === true);

              openDp(dateInput);
              press(makeEl());   // begona element
              check('tashqariga bosilganda yopildi', dp.hidden === true);

              // ── 13. Dam olish va bayram kunlari ─────────────
              const holInput = makeEl({ tagName: 'input' });
              holInput.setAttribute('type', 'date');
              holInput.value = '2026-08-10';
              openDp(holInput);

              const cells = dp.querySelector('[data-dp-grid]').children;
              const byIso = (iso) => cells.find((d) => d.getAttribute('data-dp-day') === iso);

              // 2026-08-15 — shanba, 2026-08-16 — yakshanba, 2026-08-17 — dushanba
              check('shanba dam olish deb belgilandi',
                    byIso('2026-08-15').classList.contains('is-weekend'));
              check('yakshanba ham dam olish',
                    byIso('2026-08-16').classList.contains('is-weekend'));
              check('dushanba ish kuni bo\'lib qoldi',
                    !byIso('2026-08-17').classList.contains('is-weekend'));

              check('bayram kuni belgilandi',
                    byIso('2026-08-31').classList.contains('is-holiday'));
              check('bayram nomi ustiga olib borilganda ko\'rinadi',
                    byIso('2026-08-31').getAttribute('title') === 'Mustaqillik kuni',
                    byIso('2026-08-31').getAttribute('title'));
              check('bayram bo\'lmagan kun belgilanmadi',
                    !byIso('2026-08-17').classList.contains('is-holiday'));
              check('qo\'shni oydagi bayram ham belgilandi',
                    byIso('2026-09-01').classList.contains('is-holiday')
                    && byIso('2026-09-01').classList.contains('is-other'));

              check('izohli qator chizildi',
                    !!dp.querySelector('.dp-legend'));

              // ── 14. Haftalar soni oyga qarab o'zgaradi ──────
              // Fevral 2026: yakshanbadan boshlanadi, 28 kun -> 5 hafta
              const weekInput = makeEl({ tagName: 'input' });
              weekInput.setAttribute('type', 'date');

              const weeksFor = (iso) => {
                weekInput.value = iso;
                openDp(weekInput);
                return dp.querySelector('[data-dp-grid]').children.length / 7;
              };

              check('2026 fevral — 5 hafta', weeksFor('2026-02-10') === 5,
                    weeksFor('2026-02-10'));
              check('2026 mart — 6 hafta', weeksFor('2026-03-10') === 6,
                    weeksFor('2026-03-10'));
              // 2021 fevral dushanbadan boshlanib 28 kun — eng qisqa hol
              check('2021 fevral — 4 hafta', weeksFor('2021-02-10') === 4,
                    weeksFor('2021-02-10'));

              weekInput.value = '2026-02-10';
              openDp(weekInput);
              const febCells = dp.querySelector('[data-dp-grid]').children;
              check('oxirgi hafta oyning oxirgi kunini qamradi',
                    febCells.some((d) => d.getAttribute('data-dp-day') === '2026-02-28'));
              check('ortiqcha hafta chizilmadi',
                    !febCells.some((d) => d.getAttribute('data-dp-day') === '2026-03-08'),
                    febCells[febCells.length - 1].getAttribute('data-dp-day'));

              // ── 15. Filtr oynasi "Qo'llash"da yopiladi ──────
              // Oyna qidiruv formasining ICHIDA turadi: natija almashgach
              // u ochiq qolsa jadval oyna ostida ko'rinmay qolardi
              const filterModal = makeEl({ className: 'modal' });
              filterModal.hidden = false;
              search.form.modals = [filterModal];
              fetchCalls.length = 0;
              // Manzil oldingisidan farq qilsin: bir xil so'rov takrorlanmaydi
              search.field.value = 'filtr-sinov';

              fire('document', 'submit', {
                target: Object.assign(
                  Object.create(sandbox.HTMLFormElement.prototype), search.form),
                defaultPrevented: false, preventDefault() {},
              });
              check('qo\'llangach filtr oynasi yopildi', filterModal.hidden === true);
              check('qo\'llangach jadval yangilandi', fetchCalls.length === 1,
                    fetchCalls.length);
              search.form.modals = [];

              // ── 17. Telefon maydoni ─────────────────────────
              const phoneEl = makeEl({ tagName: 'input', className: 'phone-input' });
              phoneEl.value = '';
              phoneEl.selectionStart = 0;
              phoneEl.setSelectionRange = function (a) { this.selectionStart = a; };

              const type = (text) => {
                phoneEl.value = text;
                phoneEl.selectionStart = text.length;
                fire('document', 'input', { target: phoneEl });
                return phoneEl.value;
              };

              // Bo'sh maydonga kirilganda kod o'zi paydo bo'ladi
              fire('document', 'focusin', { target: phoneEl });
              check('bo\'sh maydonda kod paydo bo\'ldi', phoneEl.value === '+998 (',
                    phoneEl.value);

              check('raqam yozilgani sari formatlandi',
                    type('998950995510') === '+998 (95) 099-55-10', phoneEl.value);
              check('kodsiz yozilgani ham formatlandi',
                    type('950995510') === '+998 (95) 099-55-10', phoneEl.value);
              check('eski 8 bilan yozuv to\'g\'rilandi',
                    type('8950995510') === '+998 (95) 099-55-10', phoneEl.value);
              check('ortiqcha raqam qabul qilinmadi',
                    type('99895099551099') === '+998 (95) 099-55-10', phoneEl.value);
              check('yarim raqam ham buzilmadi',
                    type('9509') === '+998 (95) 09', phoneEl.value);

              // Faqat kod qolgan bo'lsa maydon bo'shatiladi
              phoneEl.value = '+998 (';
              fire('document', 'focusout', { target: phoneEl });
              check('kodgina qolgan maydon bo\'shatildi', phoneEl.value === '',
                    phoneEl.value);

              // To'liq raqam saqlanib qoladi
              type('950995510');
              fire('document', 'focusout', { target: phoneEl });
              check('to\'liq raqam o\'chirilmadi', phoneEl.value === '+998 (95) 099-55-10',
                    phoneEl.value);

              // ── 16. Filtr qatori AJAX'dan keyin yangilanadi ──
              // Qator almashadigan hududdan tashqarida: tugmadagi son va
              // "qo'llanilgan" belgisi serverdan qayta olinmasa eski holat
              // qolib ketardi (filtr olib tashlangach ham qizil turaverardi)
              const chrome = makeEl({ className: 'filter-actions' });
              chrome.setAttribute('id', 'company-filter-actions');
              chrome.setAttribute('data-live-sync', '');
              chrome.innerHTML = '<button class="btn secondary is-filtered">Filtr</button>';

              const freshChrome = { innerHTML: '<button class="btn secondary">Filtr</button>' };
              sandbox.document.querySelectorAll = (sel) => (
                sel === '[data-live-sync]' ? [chrome]
                  : sel.startsWith('.toast') ? sandbox.toasts
                  : sel.startsWith('[data-toggle-when') ? sandbox.toggleFields : []);

              // Javobdagi hujjatda o'sha `id` bo'yicha yangi bo'lak topiladi
              sandbox.DOMParser = class {
                parseFromString() {
                  return {
                    title: 'yangi',
                    querySelector: (s) => (s === '#card-results' || s === '[data-live-region]'
                      ? makeEl({ innerHTML: '<table>yangi</table>' }) : null),
                    getElementById: (id) => (id === 'company-filter-actions' ? freshChrome : null),
                  };
                }
              };

              search.field.value = 'sync-sinov';
              fire('document', 'submit', {
                target: Object.assign(
                  Object.create(sandbox.HTMLFormElement.prototype), search.form),
                defaultPrevented: false, preventDefault() {},
              });

              setTimeout(() => {
                check('filtr qatori serverdan yangilandi',
                      chrome.innerHTML === freshChrome.innerHTML, chrome.innerHTML);
                check('eski "qo\'llanilgan" belgisi yo\'qoldi',
                      chrome.innerHTML.indexOf('is-filtered') === -1);

              // ── 18. Bank hisob raqami maydoni ───────────────
              const accEl = makeEl({ tagName: 'input', className: 'account-input' });
              accEl.setSelectionRange = function (a) { this.selectionStart = a; };
              const typeAcc = (text) => {
                accEl.value = text;
                accEl.selectionStart = text.length;
                fire('document', 'input', { target: accEl });
                return accEl.value;
              };

              check("hisob raqami bo'laklandi",
                    typeAcc('20208000500123612001') === '20208 000 5 00123612 001',
                    accEl.value);
              check("yarim raqam ham bo'laklandi",
                    typeAcc('202080005') === '20208 000 5', accEl.value);
              check("20 xonadan ortig'i qabul qilinmadi",
                    typeAcc('2020800050012361200199') === '20208 000 5 00123612 001',
                    accEl.value);
              check("harflar tashlab yuborildi",
                    typeAcc('20208abc000') === '20208 000', accEl.value);

              check("STIR bo'laklandi",
                    (function () {
                      const innEl = makeEl({ tagName: 'input', className: 'inn-input' });
                      innEl.setSelectionRange = function (a) { this.selectionStart = a; };
                      innEl.value = '305123456';
                      innEl.selectionStart = 9;
                      fire('document', 'input', { target: innEl });
                      return innEl.value;
                    })() === '305 123 456');

                console.log('\n' + (failures ? `*** ${failures} TA XATO ***` : 'HAMMASI OK'));
                process.exit(failures ? 1 : 0);
              }, 60);
              return;

              console.log('\n' + (failures ? `*** ${failures} TA XATO ***` : 'HAMMASI OK'));
              process.exit(failures ? 1 : 0);
            }, 60);
          }, 60);
        }, 350);
      }, 350);
    }, 300);
  }, 250);
}, 250);
